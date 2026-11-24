"""Design edits used by the editors, each one undoable command on a :class:`ProjectSession`.

Profile edits apply the constraint locks (:func:`~envelopelab.project.gore_design.apply_locks`)
and, when ``keep_rows_fitted`` is set, rescale the panel rows to the new meridian length in
the same command, so the design stays consistent and one undo restores both.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import numpy as np

from envelopelab.design.model import DesignDocument, row_bottom_fraction
from envelopelab.geometry import profile_editing
from envelopelab.geometry.gore import LENGTH_TOLERANCE, GoreLoft, GoreWidthModel
from envelopelab.geometry.profile_editing import Falloff, FloatArray
from envelopelab.geometry.profile_segments import (
    MAX_BULGE,
    SEGMENT_KINDS,
    Segment,
    SegmentKind,
    arc_points,
    merge_segments,
    resolve_segments,
    split_segment,
)
from envelopelab.materials.repository import FabricCatalog, FabricLibraryRepository
from envelopelab.project.colours import (
    PanelColours,
    PanelRef,
    normalise_colour,
    painted,
    replaced,
)
from envelopelab.project.dependencies import canonical_hash
from envelopelab.project.gore_design import (
    DEFAULT_CREST_LOFT,
    LockError,
    SegmentLayout,
    apply_locks,
    control_arrays,
    design_profile,
    design_seam_bows,
    design_volume,
    design_width_model,
    editable_outline,
    fit_row_heights,
    outline_edges,
    panel_rows,
    profile_from_arrays,
    profile_layout,
)
from envelopelab.project.model import (
    ConstraintLocks,
    ManualOutline,
    PatternSet,
    ProfileTarget,
    utc_now,
)
from envelopelab.project.overlays import OverlaySpec
from envelopelab.project.profile_match import (
    FIT_TOLERANCE,
    MAX_CONTROL_POINTS,
    ProfileUpdate,
    SolvedMeridian,
    adopted_control_points,
    compensated_control_points,
    flight_shape_points,
    solved_deviation,
    target_profile,
    updatable_interpolation,
)
from envelopelab.project.session import ProjectSession
from envelopelab.project.shapes import ShapeSpec
from envelopelab.solvers.axisymmetric import hold_shape

if TYPE_CHECKING:
    from envelopelab.features.primitives import PrimitiveDesign

LOCKABLE = (
    "height",
    "volume",
    "max_diameter",
    "mouth_diameter",
    "top_diameter",
    "gore_count",
)
#: Opening locks and the design fields that state the same diameter.
OPENING_FIELDS = {
    "mouth_diameter": ("mouth_diameter",),
    "top_diameter": ("parachute_hole_diameter", "crown_ring"),
}


def _gores(design: dict[str, Any]) -> dict[str, Any]:
    gores = design.get("gores")
    if not isinstance(gores, dict):
        raise ValueError("not a standard-gore design")
    return gores


def _segments_of(design: DesignDocument) -> list[Segment] | None:
    """The design's profile segments (a copy), or None when it is not a segment profile."""
    assert design.gores is not None
    layout = profile_layout(design.gores)
    return list(layout.segments) if isinstance(layout, SegmentLayout) else None


def _segment_dicts(segments: Sequence[Segment]) -> list[dict[str, Any]]:
    return [{"kind": s.kind, "bulge": float(s.bulge), "smooth": bool(s.smooth)} for s in segments]


def set_control_points(
    session: ProjectSession,
    points: Sequence[tuple[float, float]],
    description: str = "Edit profile",
    keep_rows_fitted: bool = True,
    segments: Sequence[Segment] | None = None,
) -> bool:
    """Replace the meridian control points (radius, height in m).

    Parameters
    ----------
    session : ProjectSession
        Session to edit.
    points : sequence of (float, float)
        New control points, m, mouth first (at least two).
    description : str
        History text.
    keep_rows_fitted : bool
        Rescale the panel rows to the new meridian length.
    segments : sequence of Segment, optional
        New profile segments, one per span, for a segment profile whose number of points
        changes (default: keep the design's).

    Returns
    -------
    bool
        Whether the design changed.

    Raises
    ------
    LockError
        When the edit cannot keep the locked quantities.
    ValueError
        For an invalid profile.
    """
    if len(points) < 2:
        raise ValueError("a profile needs at least two control points")
    r = np.array([p[0] for p in points], dtype=np.float64)
    z = np.array([p[1] for p in points], dtype=np.float64)
    if not (np.all(np.isfinite(r)) and np.all(np.isfinite(z))):
        raise ValueError("control points must be finite")
    design = session.design
    assert design.gores is not None
    layout = profile_layout(design.gores)
    if segments is not None:
        if not isinstance(layout, SegmentLayout):
            raise ValueError("segments are given only for a segment profile")
        layout = SegmentLayout(tuple(segments))
    if isinstance(layout, SegmentLayout) and len(layout.segments) != r.size - 1:
        raise ValueError(f"{r.size} control points need {r.size - 1} profile segments")
    r, z = apply_locks(r, z, session.project.locks, design_width_model(design), layout)
    profile = profile_from_arrays(r, z, layout)

    def mutate(design: dict[str, Any], _patterns: dict[str, Any]) -> None:
        gores = _gores(design)
        gores["meridian_profile_control_points"] = [
            {"x": float(a), "y": float(b)} for a, b in zip(r, z, strict=True)
        ]
        if isinstance(layout, SegmentLayout):
            gores["profile_segments"] = _segment_dicts(layout.segments)
        if keep_rows_fitted:
            heights = [row["finished_height"] for row in gores["panel_rows"]]
            for row, h in zip(
                gores["panel_rows"],
                fit_row_heights(heights, profile.meridian_length),
                strict=True,
            ):
                row["finished_height"] = h

    return session.edit(description, mutate)


def move_control_point(
    session: ProjectSession, index: int, radius: float, height: float, keep_rows_fitted: bool = True
) -> bool:
    """Move one control point to (radius, height), m (see :func:`set_control_points`)."""
    r, z = control_arrays(session.design)
    points = list(zip(r.tolist(), z.tolist(), strict=True))
    points[index] = (float(radius), float(height))
    return set_control_points(session, points, f"Move control point {index + 1}", keep_rows_fitted)


def _points(r: FloatArray, z: FloatArray) -> list[tuple[float, float]]:
    return list(zip(r.tolist(), z.tolist(), strict=True))


def move_points(
    session: ProjectSession,
    selected: Sequence[int],
    dr: float,
    dz: float,
    radius: float = 0.0,
    falloff: Falloff = "smooth",
    keep_rows_fitted: bool = True,
) -> bool:
    """Move the selected control points by (dr, dz) m, with soft selection of radius
    ``radius`` m (:func:`~envelopelab.geometry.profile_editing.move_points`); one command,
    locks applied (:func:`set_control_points`)."""
    r, z = profile_editing.move_points(
        *control_arrays(session.design), selected, dr, dz, radius, falloff
    )
    return set_control_points(
        session, _points(r, z), f"Move {len(set(selected))} point(s)", keep_rows_fitted
    )


def scale_points(
    session: ProjectSession,
    selected: Sequence[int],
    factor_r: float,
    factor_z: float,
    pivot: tuple[float, float] | None = None,
    radius: float = 0.0,
    falloff: Falloff = "smooth",
    keep_rows_fitted: bool = True,
) -> bool:
    """Scale the selected control points about ``pivot`` (m; default their centroid),
    dimensionless factors across and up (:func:`~envelopelab.geometry.profile_editing.
    scale_points`); one command, locks applied."""
    r, z = profile_editing.scale_points(
        *control_arrays(session.design), selected, factor_r, factor_z, pivot, radius, falloff
    )
    return set_control_points(
        session, _points(r, z), f"Scale {len(set(selected))} point(s)", keep_rows_fitted
    )


def rotate_points(
    session: ProjectSession,
    selected: Sequence[int],
    angle: float,
    pivot: tuple[float, float] | None = None,
    radius: float = 0.0,
    falloff: Falloff = "smooth",
    keep_rows_fitted: bool = True,
) -> bool:
    """Rotate the selected control points by ``angle`` rad about ``pivot`` (m; default
    their centroid); one command, locks applied."""
    r, z = profile_editing.rotate_points(
        *control_arrays(session.design), selected, angle, pivot, radius, falloff
    )
    return set_control_points(
        session, _points(r, z), f"Rotate {len(set(selected))} point(s)", keep_rows_fitted
    )


def straighten_points(
    session: ProjectSession, first: int, last: int, keep_rows_fitted: bool = True
) -> bool:
    """Put the control points between ``first`` and ``last`` on the straight line
    joining them (a straight section); one command, locks applied."""
    r, z = profile_editing.straighten_points(*control_arrays(session.design), first, last)
    lo, hi = sorted((first, last))
    segments = _segments_of(session.design)
    if segments is not None:  # a straight section of a segment profile is lines
        for k in range(lo, hi):
            segments[k] = Segment("line", 0.0, segments[k].smooth if k == lo else True)
    return set_control_points(
        session,
        _points(r, z),
        f"Straighten points {lo + 1} to {hi + 1}",
        keep_rows_fitted,
        segments,
    )


def smooth_points(
    session: ProjectSession,
    selected: Sequence[int],
    strength: float = 0.5,
    iterations: int = 1,
    keep_rows_fitted: bool = True,
) -> bool:
    """Laplacian smoothing of the selected interior control points; one command, locks
    applied (they also undo the slight shrinkage of smoothing)."""
    r, z = profile_editing.smooth_points(
        *control_arrays(session.design), selected, strength, iterations
    )
    return set_control_points(
        session, _points(r, z), f"Smooth {len(set(selected))} point(s)", keep_rows_fitted
    )


def simplify_profile(
    session: ProjectSession,
    tolerance: float,
    max_points: int | None = None,
    keep_rows_fitted: bool = True,
) -> profile_editing.Simplified:
    """Replace the control points by fewer ones whose profile stays within ``tolerance``
    m of the current one (:func:`~envelopelab.geometry.profile_editing.simplify_profile`).

    Returns
    -------
    Simplified
        The new points and their deviation (before the locks are re-applied).

    Raises
    ------
    ValueError
        When no profile with fewer points meets the tolerance; nothing is changed.
    """
    design = session.design
    assert design.gores is not None
    r, z = control_arrays(design)
    if r.size <= 2:
        raise ValueError("the profile has only two control points")
    interpolation = design.gores.profile_interpolation
    if interpolation == "segments":
        raise ValueError(
            "Simplify works on spline and straight-segment profiles; a segment profile's "
            "points are its joints"
        )
    result = profile_editing.simplify_profile(r, z, tolerance, interpolation, max_points)
    if not result.within_tolerance or result.count >= r.size:
        raise ValueError(
            f"no profile with fewer than {r.size} points stays within "
            f"{tolerance * 1e3:g} mm (best: {result.count} points, "
            f"{result.deviation * 1e3:.1f} mm)"
        )
    set_control_points(
        session,
        _points(result.r, result.z),
        f"Simplify profile to {result.count} points ({result.deviation * 1e3:.1f} mm)",
        keep_rows_fitted,
    )
    return result


def _replace_profile(
    session: ProjectSession,
    r: FloatArray,
    z: FloatArray,
    interpolation: Literal["spline", "linear", "segments"],
    segments: Sequence[Segment] | None,
    description: str,
    keep_rows_fitted: bool,
) -> bool:
    """Replace the profile (points, interpolation, segments) in one command: the locks
    are applied, the rows refitted, and the stated mouth, parachute-hole and crown-ring
    diameters set to the new profile's ends."""
    design = session.design
    assert design.gores is not None
    layout: Literal["spline", "linear"] | SegmentLayout
    if interpolation == "segments":
        if segments is None or len(segments) != r.size - 1:
            raise ValueError("a segment profile needs one segment per span")
        layout = SegmentLayout(tuple(segments))
    else:
        layout = interpolation
    r, z = apply_locks(r, z, session.project.locks, design_width_model(design), layout)
    profile = profile_from_arrays(r, z, layout)
    heights = fit_row_heights(
        [row.finished_height for row in design.gores.panel_rows], profile.meridian_length
    )

    def mutate(data: dict[str, Any], _patterns: dict[str, Any]) -> None:
        gores = _gores(data)
        gores["meridian_profile_control_points"] = [
            {"x": float(a), "y": float(b)} for a, b in zip(r, z, strict=True)
        ]
        gores["profile_interpolation"] = interpolation
        gores["profile_segments"] = None if segments is None else _segment_dicts(segments)
        gores["mouth_diameter"] = 2.0 * float(r[0])
        gores["parachute_hole_diameter"] = 2.0 * float(r[-1])
        gores["crown_ring"] = 2.0 * float(r[-1])
        if keep_rows_fitted:
            for row, h in zip(gores["panel_rows"], heights, strict=True):
                row["finished_height"] = h

    return session.edit(description, mutate)


def set_profile_from_design(
    session: ProjectSession,
    source: DesignDocument,
    label: str = "another design",
    keep_rows_fitted: bool = True,
) -> bool:
    """Take another design's profile (control points, interpolation and segments) into
    this design in one undoable command. Everything else (rows, zones, construction,
    rigging) stays; the rows are refitted to the new tape length, the locks applied
    (unlock them to take the profile exactly), and the stated opening diameters follow
    the new profile's ends.

    Raises
    ------
    ValueError
        When ``source`` has no profile or the result is not a valid design (e.g. the
        parachute's overlap no longer fits the new top hole); nothing is changed.
    LockError
        When the locks cannot be held with the new profile.
    """
    gores = source.gores
    if gores is None:
        raise ValueError(f"{label} is not a standard-gore design: it has no profile")
    r, z = control_arrays(source)
    segments = _segments_of(source)
    return _replace_profile(
        session,
        r,
        z,
        gores.profile_interpolation,
        segments,
        f"Profile from {label}",
        keep_rows_fitted,
    )


def set_profile_from_file(
    session: ProjectSession, path: str | Path, keep_rows_fitted: bool = True
) -> bool:
    """Take the profile of a shape file (``.yaml``) or project file (``.elproj``)
    (:func:`set_profile_from_design`)."""
    from envelopelab.project.references import design_from_file

    file = Path(path)
    return set_profile_from_design(session, design_from_file(file), file.name, keep_rows_fitted)


def set_profile_from_reference(
    session: ProjectSession,
    index: int,
    tolerance: float = 0.002,
    keep_rows_fitted: bool = True,
) -> profile_editing.Simplified:
    """Use reference profile ``index`` (with its offset) as the design's profile.

    A reference outline has hundreds of points; it is fitted with as few spline control
    points as keep it within ``tolerance`` m (:func:`~envelopelab.geometry.
    profile_editing.simplify_profile`), which become the design's control points. One
    undoable command; the locks are applied and the rows refitted.

    Returns
    -------
    Simplified
        The fit (its points and its distance from the reference).

    Raises
    ------
    ValueError
        When no spline within the tolerance is found, or the result is not a valid
        design; nothing is changed.
    """
    from envelopelab.project.references import reference_profile

    refs = session.project.references
    if not 0 <= index < len(refs):
        raise IndexError(f"no reference {index}")
    outline = reference_profile(refs[index])
    fit = profile_editing.simplify_profile(outline.r, outline.z, tolerance, "spline")
    if not fit.within_tolerance:
        raise ValueError(
            f"no spline within {tolerance * 1e3:g} mm of {refs[index].name} "
            f"(best {fit.deviation * 1e3:.1f} mm)"
        )
    _replace_profile(
        session,
        fit.r,
        fit.z,
        "spline",
        None,
        f"Profile from reference {refs[index].name}",
        keep_rows_fitted,
    )
    return fit


def insert_control_point(
    session: ProjectSession, after: int, keep_rows_fitted: bool = True
) -> bool:
    """Insert a control point on the profile halfway along the tape after point ``after``."""
    r, z = control_arrays(session.design)
    if not 0 <= after < len(r) - 1:
        raise IndexError("insert between two existing control points")
    gores = session.design.gores
    assert gores is not None
    layout = profile_layout(gores)
    if isinstance(layout, SegmentLayout):
        # Halfway along the span itself, so a split arc or line draws the same: an arc's
        # exact angular middle, else halfway along the sampled curve.
        span = resolve_segments(r, z, layout.segments)[after]
        if span.kind == "arc":
            ends = np.array([[r[after], z[after]], [r[after + 1], z[after + 1]]])
            middle = arc_points(ends[0], ends[1], span.bulge, 3)[1]
            new = (float(middle[0]), float(middle[1]))
        else:
            pts = span.points
            along = np.concatenate(([0.0], np.cumsum(np.hypot(*np.diff(pts, axis=0).T))))
            half = 0.5 * along[-1]
            new = (
                float(np.interp(half, along, pts[:, 0])),
                float(np.interp(half, along, pts[:, 1])),
            )
    else:
        profile = design_profile(session.design)
        chord = np.concatenate(([0.0], np.cumsum(np.hypot(np.diff(r), np.diff(z)))))
        s_mid = 0.5 * (chord[after] + chord[after + 1]) * profile.meridian_length / chord[-1]
        new = (float(profile.radius_at(s_mid)), float(profile.height_at(s_mid)))
    points = list(zip(r.tolist(), z.tolist(), strict=True))
    points.insert(after + 1, new)
    segments = _segments_of(session.design)
    if segments is not None:
        segments[after : after + 1] = split_segment(segments[after])
    return set_control_points(
        session, points, f"Insert control point {after + 2}", keep_rows_fitted, segments
    )


def delete_control_point(
    session: ProjectSession, index: int, keep_rows_fitted: bool = True
) -> bool:
    """Remove a control point (at least two remain).

    Raises
    ------
    LockError
        For the mouth or top point while that opening's diameter is locked: the next
        point would be pulled out to the locked radius instead.
    """
    r, z = control_arrays(session.design)
    if len(r) <= 2:
        raise ValueError("a profile needs at least two control points")
    locks = session.project.locks
    end = index % len(r)
    for at, locked, name in (
        (0, locks.mouth_diameter, "mouth"),
        (len(r) - 1, locks.top_diameter, "top hole"),
    ):
        if end == at and locked is not None:
            raise LockError(
                f"the {name} point holds the locked {name} diameter; unlock it to delete the point"
            )
    points = list(zip(r.tolist(), z.tolist(), strict=True))
    del points[index]
    segments = _segments_of(session.design)
    if segments is not None:
        if index == 0:
            del segments[0]
        elif index == len(segments):
            del segments[-1]
        else:
            segments[index - 1 : index + 1] = [merge_segments(segments[index - 1], segments[index])]
    return set_control_points(
        session, points, f"Delete control point {index + 1}", keep_rows_fitted, segments
    )


@dataclass(frozen=True)
class HoldSnap:
    """Result of :func:`snap_profile_to_hold`: control points, fit distance (m) and the
    changed fraction of the tape (0 when the drawn shape already holds)."""

    points: int
    fit_distance: float
    changed: float


#: Locks that a profile update from a solved shape would fight (it moves these on purpose).
SHAPE_LOCKS = ("height", "volume", "max_diameter", "mouth_diameter", "top_diameter")


def _check_shape_locks(session: ProjectSession) -> None:
    locked = [name for name in SHAPE_LOCKS if getattr(session.project.locks, name) is not None]
    if locked:
        raise LockError(
            f"unlock {', '.join(n.replace('_', ' ') for n in locked)} first: a profile "
            "update from a solved shape changes them on purpose"
        )


def _with_target(
    session: ProjectSession, target: ProfileTarget | None, edit: Callable[[], bool]
) -> bool:
    """Run a profile edit with ``target`` as the project's compensation target.

    The target is set first, so that views refreshed by the edit already show it, and put
    back when the edit is refused.
    """
    previous = session.project.profile_target
    session.project.profile_target = target
    try:
        changed = edit()
    except Exception:
        session.project.profile_target = previous
        raise
    if target != previous:
        session.mark_aux_dirty()
    return changed


def snap_profile_to_hold(
    session: ProjectSession,
    fabrics: FabricLibraryRepository | FabricCatalog | None = None,
    tolerance: float = 0.005,
    keep_rows_fitted: bool = True,
) -> HoldSnap:
    """Move the profile to the nearest shape its load can hold: no hoop compression.

    See :func:`envelopelab.solvers.axisymmetric.hold_shape`: the curvature is limited to
    the zero-hoop value where the drawn profile would need hoop compression, and kept
    elsewhere; mouth, top opening and tape length stay. The shape is fitted with control
    points within ``tolerance`` (m; spline, or straight segments for a straight-segment
    profile). One undoable command.

    Returns
    -------
    HoldSnap
        The fit's control-point count and distance (m), and the fraction of the tape that
        was changed.

    Raises
    ------
    LockError
        When height, volume or maximum diameter is locked.
    ValueError
        When the shape does not converge, the fit misses the tolerance, or the result is
        not a valid design; nothing is changed.
    """
    from envelopelab.project.profile_physics import design_load

    locked = [n for n in SHAPE_LOCKS[:3] if getattr(session.project.locks, n) is not None]
    if locked:
        raise LockError(
            f"unlock {', '.join(n.replace('_', ' ') for n in locked)} first: the shape "
            "that holds has its own height, volume and diameter"
        )
    design = session.design
    assert design.gores is not None
    load = design_load(design, session.patterns, fabrics).load
    held = hold_shape(design_profile(design), load)
    if not held.converged:
        raise ValueError(
            f"no shape that holds was found ({held.iterations} passes; the load may not "
            "keep the envelope taut)"
        )
    if held.changed == 0.0:
        return HoldSnap(0, 0.0, 0.0)
    interpolation: Literal["spline", "linear"] = (
        "linear" if design.gores.profile_interpolation == "linear" else "spline"
    )
    s = np.linspace(0.0, held.profile.meridian_length, 401)
    fit = profile_editing.simplify_profile(
        held.profile.radius_at(s), held.profile.height_at(s), tolerance, interpolation, 60
    )
    if not fit.within_tolerance:
        raise ValueError(
            f"no profile within {tolerance * 1e3:g} mm of the shape that holds "
            f"(best {fit.deviation * 1e3:.1f} mm)"
        )
    _replace_profile(
        session,
        fit.r,
        fit.z,
        interpolation,
        None,
        "Snap profile to a shape that holds",
        keep_rows_fitted,
    )
    return HoldSnap(len(fit.r), float(fit.deviation), held.changed)


def compensate_profile(
    session: ProjectSession,
    solved: SolvedMeridian,
    relaxation: float = 1.0,
    tolerance: float = FIT_TOLERANCE,
    keep_rows_fitted: bool = True,
) -> ProfileUpdate:
    """Correct the cut profile so the inflated tapes land on the intended line (one step).

    The first step stores the drawn profile as the project's
    :class:`~envelopelab.project.model.ProfileTarget`; later steps correct towards that
    target, so repeated steps converge on it instead of drifting with the cut line. See
    :func:`envelopelab.project.profile_match.compensated_control_points`.

    Parameters
    ----------
    session : ProjectSession
        Session to edit; ``solved`` must come from a run of its current design.
    solved : SolvedMeridian
        Solved tape line, m.
    relaxation : float
        Step factor in (0, 1], dimensionless.
    tolerance : float
        Fit tolerance, m.
    keep_rows_fitted : bool
        Rescale the panel rows to the new meridian length.

    Returns
    -------
    ProfileUpdate
        The control points written (m) and their fit error (m).

    Raises
    ------
    LockError
        When height, volume, maximum, mouth or top-hole diameter is locked.
    ValueError
        For a segment profile (switch it to a spline or straight segments first).
    """
    _check_shape_locks(session)
    design = session.design
    interpolation = updatable_interpolation(design)
    target = session.project.profile_target
    if target is None:
        r, z = control_arrays(design)
        target = ProfileTarget(
            control_points=list(zip(r.tolist(), z.tolist(), strict=True)),
            interpolation=interpolation,
        )
    goal = target_profile(target)
    update = compensated_control_points(
        design, solved, relaxation, tolerance, MAX_CONTROL_POINTS, goal
    )
    deviation = solved_deviation(goal, solved).max_distance
    _with_target(
        session,
        target.model_copy(update={"step_deviations": [*target.step_deviations, deviation]}),
        lambda: set_control_points(
            session, update.points, "Compensate profile for the solved shape", keep_rows_fitted
        ),
    )
    return update


def adopt_solved_profile(
    session: ProjectSession,
    solved: SolvedMeridian,
    tolerance: float = FIT_TOLERANCE,
    keep_rows_fitted: bool = True,
) -> ProfileUpdate:
    """Replace the profile by the solved tape line; any compensation target is dropped
    (the solved line becomes the intent).

    A segment profile becomes a spline: its lines, arcs and curves cannot follow a solved
    line. See :func:`envelopelab.project.profile_match.adopted_control_points`;
    parameters, return value and lock errors as :func:`compensate_profile`.
    """
    _check_shape_locks(session)
    update = adopted_control_points(session.design, solved, tolerance, MAX_CONTROL_POINTS)
    _adopt(session, update, "Adopt solved profile", keep_rows_fitted)
    return update


def fit_flight_shape(
    session: ProjectSession,
    solved: SolvedMeridian,
    tolerance: float = FIT_TOLERANCE,
    keep_rows_fitted: bool = True,
) -> ProfileUpdate:
    """Replace the profile by the solved shape with its stretch taken out; any
    compensation target is dropped.

    See :func:`envelopelab.project.profile_match.flight_shape_points`: the tape length
    stays, so repeating it settles on the shape the patterns fly in. Parameters, return
    value and lock errors as :func:`compensate_profile`; a segment profile becomes a
    spline.
    """
    _check_shape_locks(session)
    update = flight_shape_points(session.design, solved, tolerance, MAX_CONTROL_POINTS)
    _adopt(session, update, "Fit profile to flight shape", keep_rows_fitted)
    return update


def _adopt(
    session: ProjectSession, update: ProfileUpdate, description: str, keep_rows_fitted: bool
) -> None:
    """Write adopted control points in one command, dropping any compensation target (a
    segment profile becomes a spline)."""
    design = session.design
    if design.gores is not None and design.gores.profile_interpolation == "segments":
        pts = np.asarray(update.points, dtype=np.float64)
        _with_target(
            session,
            None,
            lambda: _replace_profile(
                session,
                pts[:, 0],
                pts[:, 1],
                "spline",
                None,
                f"{description} (as a spline)",
                keep_rows_fitted,
            ),
        )
        return
    _with_target(
        session,
        None,
        lambda: set_control_points(session, update.points, description, keep_rows_fitted),
    )


def restore_profile_target(session: ProjectSession, keep_rows_fitted: bool = True) -> bool:
    """Set the drawn profile back to the compensation target and drop the target
    (undoes every compensation step in one command; the target is not restored by undo).

    Raises
    ------
    ValueError
        When the project has no compensation target.
    """
    target = session.project.profile_target
    if target is None:
        raise ValueError("no compensation target to restore")
    _check_shape_locks(session)
    return _with_target(
        session,
        None,
        lambda: set_control_points(
            session, target.control_points, "Restore the intended profile", keep_rows_fitted
        ),
    )


def clear_profile_target(session: ProjectSession) -> None:
    """Forget the compensation target, keeping the drawn (cut) profile as it is.

    Like the locks the target is an editor setting saved with the project, not a design
    edit, so this does not enter the undo history.
    """
    if session.project.profile_target is not None:
        session.project.profile_target = None
        session.mark_aux_dirty()


def set_gore_count(session: ProjectSession, count: int) -> bool:
    """Set the number of gores N (refused while N is locked)."""
    locked = session.project.locks.gore_count
    if locked is not None and count != locked:
        raise LockError(f"the gore count is locked at {locked}")
    return session.set_design_value(("gores", "count"), int(count), f"Set gore count to {count}")


def set_loft(
    session: ProjectSession,
    points: Sequence[tuple[float, float]] | None,
    keep_rows_fitted: bool = True,
) -> bool:
    """Set the gore loft: (station, ratio) pairs, or None for small-bulge gores.

    A loft changes the enclosed volume, so while the volume is locked the control points
    are corrected in the same command (:func:`~envelopelab.project.gore_design.apply_locks`
    with the new loft), and the panel rows are refitted when ``keep_rows_fitted`` is set.

    Parameters
    ----------
    session : ProjectSession
        Session to edit.
    points : sequence of (float, float) or None
        Stations as fractions of the tape length (0 mouth .. 1 top opening) and the
        lobe-radius ratio k = ρ/r at each, dimensionless. They are sorted by station.
        ``None`` or empty removes the loft (k = 1 everywhere).
    keep_rows_fitted : bool
        Rescale the panel rows when a volume lock moves the profile.

    Returns
    -------
    bool
        Whether the design changed.

    Raises
    ------
    LockError
        When the locked volume cannot be held with the new loft.
    ValueError
        For an invalid loft (stations outside 0..1 or repeated, ratio below sin(π/N)).
    """
    design = session.design
    assert design.gores is not None
    loft: GoreLoft | None = None
    if points:
        ordered = sorted((float(f), float(k)) for f, k in points)
        loft = GoreLoft(tuple(f for f, _ in ordered), tuple(k for _, k in ordered))
    width_model = GoreWidthModel.lofted(design.gores.count, loft)
    value = (
        None
        if loft is None
        else [{"station": f, "ratio": k} for f, k in zip(loft.stations, loft.ratios, strict=True)]
    )
    new_points: list[dict[str, float]] | None = None
    heights: list[float] | None = None
    if session.project.locks.volume is not None:
        r0, z0 = control_arrays(design)
        interpolation = profile_layout(design.gores)
        r, z = apply_locks(r0, z0, session.project.locks, width_model, interpolation)
        if not (np.array_equal(r, r0) and np.array_equal(z, z0)):
            new_points = [{"x": float(a), "y": float(b)} for a, b in zip(r, z, strict=True)]
            if keep_rows_fitted:
                heights = fit_row_heights(
                    [row.finished_height for row in design.gores.panel_rows],
                    profile_from_arrays(r, z, interpolation).meridian_length,
                )

    def mutate(data: dict[str, Any], _patterns: dict[str, Any]) -> None:
        gores = _gores(data)
        gores["loft"] = value
        if new_points is not None:
            gores["meridian_profile_control_points"] = new_points
        if heights is not None:
            for row, h in zip(gores["panel_rows"], heights, strict=True):
                row["finished_height"] = h

    return session.edit("Remove gore loft" if loft is None else "Set gore loft", mutate)


def set_construction(
    session: ProjectSession,
    construction: Literal["lobe", "flat_chord"],
    keep_rows_fitted: bool = True,
) -> bool:
    """Cut the gores as lobes (straight seams) or flat chords (bowed seams).

    Switching to flat chords removes the lobe loft and adds
    :data:`~envelopelab.project.gore_design.DEFAULT_CREST_LOFT`; switching to lobes removes
    the crest loft and any measured seam bows. The design volume changes with the width
    model, so a locked volume is held by correcting the control points in the same command.

    Parameters
    ----------
    session : ProjectSession
        Session to edit.
    construction : {"lobe", "flat_chord"}
        Gore construction (``GoreSpec.construction``).
    keep_rows_fitted : bool
        Rescale the panel rows when a volume lock moves the profile.

    Returns
    -------
    bool
        Whether the design changed.

    Raises
    ------
    LockError
        When the locked volume cannot be held with the new construction.
    """
    design = session.design
    assert design.gores is not None
    if construction not in ("lobe", "flat_chord"):
        raise ValueError(f"unknown gore construction {construction!r}")
    if design.gores.construction == construction:
        return False
    crest = DEFAULT_CREST_LOFT if construction == "flat_chord" else None
    changed = design.gores.model_copy(
        update={"construction": construction, "loft": None, "crest_loft": crest}
    )
    width_model = design_width_model(design.model_copy(update={"gores": changed}))
    interpolation = profile_layout(design.gores)
    new_points: list[dict[str, float]] | None = None
    heights: list[float] | None = None
    if session.project.locks.volume is not None:
        r0, z0 = control_arrays(design)
        r, z = apply_locks(r0, z0, session.project.locks, width_model, interpolation)
        new_points = [{"x": float(a), "y": float(b)} for a, b in zip(r, z, strict=True)]
        if keep_rows_fitted:
            heights = fit_row_heights(
                [row.finished_height for row in design.gores.panel_rows],
                profile_from_arrays(r, z, interpolation).meridian_length,
            )

    def mutate(data: dict[str, Any], _patterns: dict[str, Any]) -> None:
        gores = _gores(data)
        gores["construction"] = construction
        gores["loft"] = None
        gores["crest_loft"] = None if crest is None else crest.model_dump(mode="json")
        for row in gores["panel_rows"]:
            row["bow_bottom"] = row["bow_top"] = None
        if new_points is not None:
            gores["meridian_profile_control_points"] = new_points
        if heights is not None:
            for row, h in zip(gores["panel_rows"], heights, strict=True):
                row["finished_height"] = h

    label = "flat-chord gores" if construction == "flat_chord" else "lobe gores"
    return session.edit(f"Construction: {label}", mutate)


def set_crest_loft(
    session: ProjectSession,
    fraction: float | None,
    taper: Sequence[tuple[float | str, float]] | None = None,
) -> bool:
    """Set the crest loft of a flat-chord design, or remove it (straight seams).

    A crest loft and measured seam bows exclude each other, so the rows' measured bows are
    removed in the same command. The design volume does not change: it is the flat-chord
    polygon's, the crest is not added (ADR-0021).

    Parameters
    ----------
    session : ProjectSession
        Session to edit.
    fraction : float or None
        Crest offset over the tape radius where the taper is 1, dimensionless
        (0.02 = 2 %). ``None`` removes the crest loft and every seam bow.
    taper : sequence of (float or str, float)
        (station, taper), taper dimensionless; at least one, sorted by station. A station
        is a fraction of the tape length from the mouth (0) to the top opening (1), or a
        row name: the bottom seam of that row, which the station then follows when rows
        are resized, renamed or split (``TaperPoint.at_row``).

    Returns
    -------
    bool
        Whether the design changed.

    Raises
    ------
    ValueError
        For a lobe design, an unknown row or an invalid crest loft (negative fraction, no
        taper, repeated or out-of-range station); nothing is changed.
    """
    value: dict[str, Any] | None = None
    if fraction is not None:
        gores = session.design.gores
        assert gores is not None
        letters = [r.letter for r in gores.panel_rows]
        heights = [r.finished_height for r in gores.panel_rows]
        points: list[dict[str, Any]] = []
        for where, k in taper or ():
            if isinstance(where, str):
                if where not in letters:
                    raise ValueError(f"crest-loft taper: unknown row {where!r}")
                station = row_bottom_fraction(heights, letters.index(where))
                points.append({"station": station, "taper": float(k), "at_row": where})
            else:
                points.append({"station": float(where), "taper": float(k), "at_row": None})
        points.sort(key=lambda point: point["station"])
        value = {"fraction": float(fraction), "taper": points}

    def mutate(data: dict[str, Any], _patterns: dict[str, Any]) -> None:
        gores = _gores(data)
        gores["crest_loft"] = value
        for row in gores["panel_rows"]:
            row["bow_bottom"] = row["bow_top"] = None

    return session.edit("Remove crest loft" if value is None else "Set crest loft", mutate)


def _write_bows(session: ProjectSession, bows: Sequence[tuple[float, float]], label: str) -> bool:
    def mutate(data: dict[str, Any], _patterns: dict[str, Any]) -> None:
        gores = _gores(data)
        gores["crest_loft"] = None
        for row, (bottom, top) in zip(gores["panel_rows"], bows, strict=True):
            row["bow_bottom"], row["bow_top"] = float(bottom), float(top)

    return session.edit(label, mutate)


def freeze_crest_bows(session: ProjectSession) -> bool:
    """Replace the crest loft by the seam bows it gives, as measured bows of the rows.

    The cut panels do not change; afterwards single seams can be edited
    (:func:`set_row_bows`). Returns False when the design has no crest loft.
    """
    design = session.design
    assert design.gores is not None
    if design.gores.crest_loft is None:
        return False
    return _write_bows(session, design_seam_bows(design), "Freeze crest loft as seam bows")


def set_row_bows(session: ProjectSession, index: int, bottom: float, top: float) -> bool:
    """Set the measured seam bows of one row of a flat-chord design (m, positive outward).

    Bows are given for every row or for none, so the other rows keep the bows the design
    cuts now: their measured bows, the crest loft's (which is then removed), or 0.

    Raises
    ------
    ValueError
        For a lobe design, a row index out of range or a non-finite bow.
    """
    design = session.design
    assert design.gores is not None
    if design.gores.construction != "flat_chord":
        raise ValueError("seam bows need the flat_chord construction")
    if not (math.isfinite(bottom) and math.isfinite(top)):
        raise ValueError("seam bows must be finite")
    bows = design_seam_bows(design)
    if not 0 <= index < len(bows):
        raise IndexError(f"no row {index}")
    bows[index] = (float(bottom), float(top))
    letter = design.gores.panel_rows[index].letter
    return _write_bows(session, bows, f"Seam bows of row {letter}")


def set_profile_interpolation(
    session: ProjectSession,
    interpolation: Literal["spline", "linear", "segments"],
    keep_rows_fitted: bool = True,
) -> bool:
    """Choose how the profile runs between control points: a spline, straight segments,
    or segments (a line, arc or curve per span).

    Switching to segments draws the same profile: every span becomes a smooth curve
    (from a spline) or a line (from straight segments), to be changed span by span
    (:func:`set_profile_segment`). Other switches change the tape length, volume, height
    and widest diameter, so the control points are corrected for the locked quantities
    and the panel rows refitted in the same command.

    Parameters
    ----------
    session : ProjectSession
        Session to edit.
    interpolation : {"spline", "linear", "segments"}
        ``GoreSpec.profile_interpolation``.
    keep_rows_fitted : bool
        Rescale the panel rows to the new tape length.

    Returns
    -------
    bool
        Whether the design changed.

    Raises
    ------
    LockError
        When the locked quantities cannot be held with the new profile.
    """
    design = session.design
    assert design.gores is not None
    if interpolation not in ("spline", "linear", "segments"):
        raise ValueError(f"unknown profile interpolation {interpolation!r}")
    current = design.gores.profile_interpolation
    if current == interpolation:
        return False
    r0, z0 = control_arrays(design)
    spans = r0.size - 1
    segments: list[Segment] | None = None
    layout: Literal["spline", "linear"] | SegmentLayout
    if interpolation == "segments":
        kind: SegmentKind = "line" if current == "linear" else "curve"
        segments = [Segment(kind, 0.0, kind == "curve") for _ in range(spans)]
        layout = SegmentLayout(tuple(segments))
    else:
        layout = interpolation
    r, z = apply_locks(r0, z0, session.project.locks, design_width_model(design), layout)
    heights = fit_row_heights(
        [row.finished_height for row in design.gores.panel_rows],
        profile_from_arrays(r, z, layout).meridian_length,
    )

    def mutate(data: dict[str, Any], _patterns: dict[str, Any]) -> None:
        gores = _gores(data)
        gores["profile_interpolation"] = interpolation
        gores["profile_segments"] = None if segments is None else _segment_dicts(segments)
        gores["meridian_profile_control_points"] = [
            {"x": float(a), "y": float(b)} for a, b in zip(r, z, strict=True)
        ]
        if keep_rows_fitted:
            for row, h in zip(gores["panel_rows"], heights, strict=True):
                row["finished_height"] = h

    label = {"linear": "straight segments", "spline": "spline", "segments": "segments"}
    return session.edit(f"Profile between points: {label[interpolation]}", mutate)


def set_profile_segment(
    session: ProjectSession,
    index: int,
    kind: SegmentKind | None = None,
    bulge: float | None = None,
    smooth: bool | None = None,
    keep_rows_fitted: bool = True,
) -> bool:
    """Change how span ``index`` (from control point ``index`` to ``index + 1``) of a
    segment profile is drawn: its kind, its arc bulge (dimensionless,
    :class:`~envelopelab.geometry.profile_segments.Segment`) or whether the joint at
    its start is smooth. One command; the locks are re-applied and the rows refitted
    (:func:`set_control_points`).

    Raises
    ------
    ValueError
        When the design is not a segment profile or a value is out of range.
    IndexError
        For an unknown span.
    """
    segments = _segments_of(session.design)
    if segments is None:
        raise ValueError("choose 'segments' for the profile first")
    if not 0 <= index < len(segments):
        raise IndexError(f"no span {index}")
    old = segments[index]
    if kind is not None and kind not in SEGMENT_KINDS:
        raise ValueError(f"unknown segment kind {kind!r}")
    if bulge is not None and not (math.isfinite(bulge) and abs(bulge) <= MAX_BULGE):
        raise ValueError(f"the arc bulge must be between -{MAX_BULGE} and {MAX_BULGE}")
    new = Segment(
        kind if kind is not None else old.kind,
        float(bulge) if bulge is not None else old.bulge,
        bool(smooth) if smooth is not None else old.smooth,
    )
    if new == old:
        return False
    segments[index] = new
    r, z = control_arrays(session.design)
    what = (
        f"{new.kind}"
        if kind is not None
        else f"bulge {new.bulge:g}"
        if bulge is not None
        else ("smooth joint" if new.smooth else "corner")
    )
    return set_control_points(
        session, _points(r, z), f"Span {index + 1}: {what}", keep_rows_fitted, segments
    )


def set_row_heights(session: ProjectSession, heights: Sequence[float], description: str) -> bool:
    """Set every panel row's finished height (m)."""

    def mutate(design: dict[str, Any], _patterns: dict[str, Any]) -> None:
        rows = _gores(design)["panel_rows"]
        if len(rows) != len(heights):
            raise ValueError("one height per row")
        for row, h in zip(rows, heights, strict=True):
            row["finished_height"] = float(h)

    return session.edit(description, mutate)


def fit_rows(session: ProjectSession) -> bool:
    """Rescale the panel rows so they cover the meridian exactly."""
    assert session.design.gores is not None
    length = design_profile(session.design).meridian_length
    heights = [r.finished_height for r in session.design.gores.panel_rows]
    return set_row_heights(session, fit_row_heights(heights, length), "Fit rows to meridian")


def _next_letter(letters: Sequence[str]) -> str:
    alphabet = [chr(ord("A") + i) for i in range(26)]
    for candidate in [*alphabet, *(a + b for a in alphabet for b in alphabet)]:
        if candidate not in letters:
            return candidate
    raise ValueError("no free row letter")


#: Most panel rows :func:`set_row_count` makes.
MAX_ROWS = 52
#: Row-level pattern settings a new row takes from the old row at its middle; the marks
#: placed on a row (notches, tape paths, features, a manual outline) are not kept.
ROW_SETTINGS = ("label_text", "grain_angle_deg", "zone", "seam_allowance")


def row_letters(count: int) -> list[str]:
    """Row letters from the mouth: A..Z, then AA, AB, ..."""
    alphabet = [chr(ord("A") + i) for i in range(26)]
    letters = [*alphabet, *(a + b for a in alphabet for b in alphabet)]
    return letters[:count]


def set_row_count(session: ProjectSession, count: int) -> bool:
    r"""Divide every gore into ``count`` panel rows of equal length along the load tape.

    Row :math:`k` (from 0, mouth first) runs from :math:`s = kL/n` to :math:`(k+1)L/n` on a
    tape of length :math:`L` (heights stored to 0.1 mm, the top row taking the rounding).
    The rows are lettered A, B, C ... from the mouth. What belonged to the old rows
    follows by position along the tape:

    * a new row takes the material zone, half-gore cut and row settings (label, grain,
      seam allowance) of the old row at its middle;
    * a turning vent covers the new rows over the old rows' stretch of seam, and a panel
      zone (applique) the new rows over its old row (one zone per new row);
    * crest-loft taper stations anchored to a row seam stay where they are, free;
    * the marks placed on the old rows (notches, tape paths, feature marks, manual
      outlines) are removed: their positions belong to the old panels. Undo restores them.

    Parameters
    ----------
    session : ProjectSession
        Session to edit.
    count : int
        Number of panel rows, 1 to :data:`MAX_ROWS`.

    Returns
    -------
    bool
        Whether the design changed (False when it already has ``count`` equal rows).

    Raises
    ------
    ValueError
        For a count out of range, or a flat-chord design with measured seam bows (they
        belong to the old seams: use the crest loft or straight seams first).
    """
    design = session.design
    gores = design.gores
    assert gores is not None
    if not 1 <= int(count) <= MAX_ROWS:
        raise ValueError(f"the number of panel rows must be between 1 and {MAX_ROWS}")
    count = int(count)
    if any(r.bow_bottom is not None for r in gores.panel_rows):
        raise ValueError(
            "the rows have measured seam bows, which belong to the old seams: use the crest "
            "loft or straight seams first (Seam bows), then set the number of rows"
        )
    length = float(design_profile(design).meridian_length)
    step = math.floor(length / count * 1e4) / 1e4
    heights = [step] * (count - 1) + [length - step * (count - 1)]
    old = gores.panel_rows
    old_h = [r.finished_height for r in old]
    old_h[-1] = length - sum(old_h[:-1])
    old_edges = [0.0, *np.cumsum(old_h).tolist()]
    new_edges = [0.0, *np.cumsum(heights).tolist()]
    letters = row_letters(count)
    if [r.letter for r in old] == letters and all(
        abs(a - b) < 1e-4 for a, b in zip(old_h, heights, strict=True)
    ):
        return False

    def old_at(s: float) -> int:
        """Index of the old row over tape position ``s`` (m)."""
        for j in range(len(old)):
            if s < old_edges[j + 1]:
                return j
        return len(old) - 1

    def new_over(lo: float, hi: float) -> list[str]:
        """Letters of the new rows overlapping the stretch ``lo``..``hi`` of tape (m)."""
        eps = 1e-6
        return [
            letters[i]
            for i in range(count)
            if new_edges[i] < hi - eps and new_edges[i + 1] > lo + eps
        ]

    source = [old_at(0.5 * (new_edges[i] + new_edges[i + 1])) for i in range(count)]
    span = {r.letter: (old_edges[j], old_edges[j + 1]) for j, r in enumerate(old)}

    def mutate(data: dict[str, Any], patterns: dict[str, Any]) -> None:
        g = _gores(data)
        old_rows = g["panel_rows"]
        rows = []
        for i, h in enumerate(heights):
            parent = old_rows[source[i]]
            row: dict[str, Any] = {"letter": letters[i], "finished_height": h}
            if parent.get("zone") is not None:
                row["zone"] = parent["zone"]
            if parent.get("half_gore"):
                row["half_gore"] = True
            rows.append(row)
        g["panel_rows"] = rows
        old_patterns = patterns.get("rows", {})
        new_patterns: dict[str, Any] = {}
        for i, letter in enumerate(letters):
            ann = old_patterns.get(old[source[i]].letter) or {}
            kept = {k: ann[k] for k in ROW_SETTINGS if k in ann}
            if kept:
                new_patterns[letter] = kept
        patterns["rows"] = new_patterns
        for point in (g.get("crest_loft") or {}).get("taper") or []:
            point["at_row"] = None  # stays at its station, free
        zones = []
        names = {z["name"] for z in g.get("panel_zones") or []}
        for zone in g.get("panel_zones") or []:
            targets = new_over(*span.get(zone["row"], (0.0, 0.0))) or [letters[0]]
            for k, letter in enumerate(targets):
                copy = dict(zone, row=letter)
                if k:
                    name = f"{zone['name']} {letter}"
                    while name in names:
                        name += "'"
                    names.add(name)
                    copy["name"] = name
                zones.append(copy)
        if g.get("panel_zones") is not None:
            g["panel_zones"] = zones
        for vent in data.get("turning_vents") or []:
            stretch = [span[r] for r in vent.get("rows", []) if r in span]
            if stretch:
                vent["rows"] = new_over(min(a for a, _ in stretch), max(b for _, b in stretch))

    return session.edit(f"Divide the gores into {count} equal panel rows", mutate)


def set_half_gores(session: ProjectSession, letters: Sequence[str] | None, on: bool) -> bool:
    """Cut panel rows as half gores (two halves sewn down the gore centreline) or whole.

    The sewn envelope does not change (:func:`envelopelab.geometry.gore.half_panel`): the
    patterns, build pack and mass estimate do; the rest mesh and simulations stay current.

    Parameters
    ----------
    session : ProjectSession
        Session to edit.
    letters : sequence of str or None
        Rows to set; None: every row.
    on : bool
        Half gores (True) or whole panels (False).

    Returns
    -------
    bool
        Whether the design changed.

    Raises
    ------
    KeyError
        For a letter that is not a row of the design.
    """
    assert session.design.gores is not None
    rows = session.design.gores.panel_rows
    known = [r.letter for r in rows]
    chosen = list(known) if letters is None else list(letters)
    unknown = [x for x in chosen if x not in known]
    if unknown:
        raise KeyError(f"no panel row {', '.join(unknown)}")
    if all(r.half_gore == on for r in rows if r.letter in chosen):
        return False

    def mutate(design: dict[str, Any], _patterns: dict[str, Any]) -> None:
        for row in _gores(design)["panel_rows"]:
            if row["letter"] in chosen:
                row["half_gore"] = bool(on)

    what = (
        "every row"
        if letters is None or len(chosen) == len(known)
        else ("row " + ", ".join(chosen))
    )
    return session.edit(f"{'Half gores' if on else 'Whole panels'}: {what}", mutate)


def split_row(session: ProjectSession, index: int) -> bool:
    """Split a panel row into two rows of half its height (a new letter for the upper)."""
    assert session.design.gores is not None
    rows = session.design.gores.panel_rows
    letter = _next_letter([r.letter for r in rows])

    def mutate(design: dict[str, Any], _patterns: dict[str, Any]) -> None:
        data = _gores(design)["panel_rows"]
        row = data[index]
        h = row["finished_height"]
        row["finished_height"] = math.floor(h / 2 * 1e4) / 1e4
        # The new upper row gets the first free letter; existing rows keep their letters
        # so that their pattern annotations stay attached. It keeps the row's material.
        upper: dict[str, Any] = {
            "letter": letter,
            "finished_height": h - row["finished_height"],
            "zone": row.get("zone"),
        }
        if row.get("half_gore"):
            upper["half_gore"] = True  # cut as the row was
        if row.get("bow_top") is not None:
            # Measured bows: the new seam inside the row is straight on both sides.
            upper["bow_bottom"], upper["bow_top"] = 0.0, row["bow_top"]
            row["bow_top"] = 0.0
        data.insert(index + 1, upper)

    return session.edit(f"Split row {rows[index].letter}", mutate)


def merge_row_with_next(session: ProjectSession, index: int) -> bool:
    """Merge a panel row with the row above it."""
    assert session.design.gores is not None
    rows = session.design.gores.panel_rows
    if not 0 <= index < len(rows) - 1:
        raise IndexError("no row above to merge with")

    def mutate(design: dict[str, Any], patterns: dict[str, Any]) -> None:
        data = _gores(design)["panel_rows"]
        data[index]["finished_height"] += data[index + 1]["finished_height"]
        upper = data.pop(index + 1)
        # The seam under the upper row is gone: stations anchored there stay where they are.
        for point in (_gores(design).get("crest_loft") or {}).get("taper") or []:
            if point.get("at_row") == upper["letter"]:
                point["at_row"] = None
        if upper.get("bow_top") is not None:
            data[index]["bow_top"] = upper["bow_top"]  # the merged row ends at its seam
        removed = upper["letter"]
        patterns["rows"].pop(removed, None)

    return session.edit(f"Merge rows {rows[index].letter} and {rows[index + 1].letter}", mutate)


# --------------------------------------------------------------------------------------
# Zones, row zones and row names: every reference follows
# --------------------------------------------------------------------------------------


def zone_users(design: DesignDocument, patterns: PatternSet, zone: str) -> list[str]:
    """What uses a material zone: rows, panel zones, the parachute and the scoop.

    A row without a zone of its own uses the design's first zone, so that zone is used by
    those rows too.
    """
    users: list[str] = []
    first = next(iter(design.zones), None)
    if design.gores is not None:
        for row in design.gores.panel_rows:
            annotation = patterns.row(row.letter).zone
            own = annotation if annotation is not None else row.zone
            if own == zone or (own is None and zone == first):
                users.append(f"row {row.letter}")
        users += [f"panel zone {z.name}" for z in design.gores.panel_zones if z.zone == zone]
    if design.parachute is not None and design.parachute.zone == zone:
        users.append("parachute")
    if design.scoop is not None and design.scoop.zone == zone:
        users.append("scoop")
    return users


def add_zone(session: ProjectSession, name: str, fabric_id: str) -> bool:
    """Add a material zone (``fabric_id`` from the fabric library).

    Raises
    ------
    ValueError
        For an empty name or a name the design already has.
    """
    name = name.strip()
    if not name:
        raise ValueError("a zone needs a name")
    if name in session.design.zones:
        raise ValueError(f"zone {name!r} already exists")

    def mutate(design: dict[str, Any], _patterns: dict[str, Any]) -> None:
        design["zones"][name] = fabric_id

    return session.edit(f"Add zone {name}", mutate)


def remove_zone(session: ProjectSession, name: str) -> bool:
    """Remove a material zone that nothing uses.

    Raises
    ------
    ValueError
        When the zone is used (the message names the users) or does not exist.
    """
    if name not in session.design.zones:
        raise ValueError(f"no zone {name!r}")
    users = zone_users(session.design, session.patterns, name)
    if users:
        raise ValueError(f"zone {name!r} is used by {', '.join(users)}")

    def mutate(design: dict[str, Any], _patterns: dict[str, Any]) -> None:
        design["zones"].pop(name)

    return session.edit(f"Remove zone {name}", mutate)


def rename_zone(session: ProjectSession, old: str, new: str) -> bool:
    """Rename a material zone and every reference to it, keeping its place and fabric.

    Raises
    ------
    ValueError
        For an unknown zone, an empty name or a name the design already has.
    """
    new = new.strip()
    if old not in session.design.zones:
        raise ValueError(f"no zone {old!r}")
    if not new:
        raise ValueError("a zone needs a name")
    if new == old:
        return False
    if new in session.design.zones:
        raise ValueError(f"zone {new!r} already exists")

    def mutate(design: dict[str, Any], patterns: dict[str, Any]) -> None:
        design["zones"] = {(new if k == old else k): v for k, v in design["zones"].items()}
        gores = design.get("gores") or {}
        for item in [*(gores.get("panel_rows") or []), *(gores.get("panel_zones") or [])]:
            if item.get("zone") == old:
                item["zone"] = new
        for section in ("parachute", "scoop"):
            if (design.get(section) or {}).get("zone") == old:
                design[section]["zone"] = new
        for row in patterns.get("rows", {}).values():
            if row.get("zone") == old:
                row["zone"] = new

    return session.edit(f"Rename zone {old} to {new}", mutate)


def set_row_zone(session: ProjectSession, letter: str, zone: str | None) -> bool:
    """Set a row's material zone (None: the design's first zone).

    The zone is stored on the design row; a zone set on the row's pattern annotation by
    an earlier version is removed in the same command, so the row's zone has one home.

    Raises
    ------
    ValueError
        For an unknown row or zone.
    """
    design = session.design
    assert design.gores is not None
    letters = [r.letter for r in design.gores.panel_rows]
    if letter not in letters:
        raise ValueError(f"no row {letter!r}")
    if zone is not None and zone not in design.zones:
        raise ValueError(f"no zone {zone!r}")
    index = letters.index(letter)

    def mutate(data: dict[str, Any], patterns: dict[str, Any]) -> None:
        _gores(data)["panel_rows"][index]["zone"] = zone
        annotation = patterns.get("rows", {}).get(letter)
        if annotation is not None:
            annotation["zone"] = None

    return session.edit(f"Row {letter}: zone {zone or 'default'}", mutate)


def rename_row(session: ProjectSession, old: str, new: str) -> bool:
    """Rename a panel row and every reference to it (pattern annotations, panel zones,
    turning vents).

    Raises
    ------
    ValueError
        For an unknown row, an invalid name (1-8 characters) or one another row has.
    """
    design = session.design
    assert design.gores is not None
    new = new.strip()
    letters = [r.letter for r in design.gores.panel_rows]
    if old not in letters:
        raise ValueError(f"no row {old!r}")
    if not 1 <= len(new) <= 8:
        raise ValueError("a row name has 1 to 8 characters")
    if new == old:
        return False
    if new in letters:
        raise ValueError(f"row {new!r} already exists")

    def mutate(data: dict[str, Any], patterns: dict[str, Any]) -> None:
        gores = _gores(data)
        gores["panel_rows"][letters.index(old)]["letter"] = new
        for zone in gores.get("panel_zones") or []:
            if zone["row"] == old:
                zone["row"] = new
        for vent in data.get("turning_vents") or []:
            vent["rows"] = [new if r == old else r for r in vent["rows"]]
        for point in (gores.get("crest_loft") or {}).get("taper") or []:
            if point.get("at_row") == old:
                point["at_row"] = new
        rows = patterns.get("rows", {})
        if old in rows:
            rows[new] = rows.pop(old)

    return session.edit(f"Rename row {old} to {new}", mutate)


def set_lock_target(session: ProjectSession, name: str, value: float) -> bool:
    """Lock a quantity at a typed value and solve the design to it in one command.

    The other locks keep their values: the control points are corrected for all of them
    (:func:`~envelopelab.project.gore_design.apply_locks`) and the rows refitted. For the
    gore count the design gets that count and the lock holds it. A mouth or top-hole
    diameter also sets the design fields that state it (``gores.mouth_diameter``;
    ``gores.parachute_hole_diameter`` and ``gores.crown_ring``).

    Parameters
    ----------
    session : ProjectSession
        Session to edit.
    name : {"height", "volume", "max_diameter", "mouth_diameter", "top_diameter", "gore_count"}
        Quantity to lock.
    value : float
        Target: m (height and the diameters), m^3 (volume) or a count.

    Returns
    -------
    bool
        Whether the design changed.

    Raises
    ------
    LockError
        When the targets cannot all be met; nothing is changed.
    """
    if name not in LOCKABLE:
        raise KeyError(name)
    design = session.design
    assert design.gores is not None
    if name == "gore_count":
        count = int(value)
        session.project.locks = session.project.locks.model_copy(update={"gore_count": None})
        changed = set_gore_count(session, count)
        set_lock(session, "gore_count", True)
        return changed
    if not (math.isfinite(value) and value > 0.0):
        raise ValueError(f"{name} must be a positive number")
    locks = session.project.locks.model_copy(update={name: float(value)})
    interpolation = profile_layout(design.gores)
    r0, z0 = control_arrays(design)
    r, z = apply_locks(r0, z0, locks, design_width_model(design), interpolation)
    heights = fit_row_heights(
        [row.finished_height for row in design.gores.panel_rows],
        profile_from_arrays(r, z, interpolation).meridian_length,
    )

    def mutate(data: dict[str, Any], _patterns: dict[str, Any]) -> None:
        gores = _gores(data)
        gores["meridian_profile_control_points"] = [
            {"x": float(a), "y": float(b)} for a, b in zip(r, z, strict=True)
        ]
        for row, h in zip(gores["panel_rows"], heights, strict=True):
            row["finished_height"] = h
        for field in OPENING_FIELDS.get(name, ()):
            gores[field] = float(value)

    changed = session.edit(f"Lock {name.replace('_', ' ')} at {value:g}", mutate)
    session.project.locks = locks
    session.mark_aux_dirty()
    return changed


def set_lock(session: ProjectSession, name: str, enabled: bool) -> ConstraintLocks:
    """Switch a constraint lock on (holding the current value) or off.

    Locks are editor settings saved with the project; they are not design edits and do not
    enter the undo history.
    """
    if name not in LOCKABLE:
        raise KeyError(name)
    assert session.design.gores is not None
    value: float | int | None = None
    if enabled:
        profile = design_profile(session.design)
        r, _ = control_arrays(session.design)
        value = {
            "height": profile.height,
            "volume": design_volume(session.design, profile),
            "max_diameter": profile.max_width,
            "mouth_diameter": 2.0 * float(r[0]),
            "top_diameter": 2.0 * float(r[-1]),
            "gore_count": session.design.gores.count,
        }[name]
    session.project.locks = session.project.locks.model_copy(update={name: value})
    session.mark_aux_dirty()
    return session.project.locks


def set_seam_allowance(
    session: ProjectSession, allowance: float, letter: str | None = None
) -> bool:
    """Set the seam allowance (m): the default (first seam type) or one row's override."""
    if allowance < 0.0:
        raise ValueError("seam allowance must be non-negative")
    if letter is None:
        if not session.design.seam_types:
            raise ValueError("the design has no seam type")
        return session.set_design_value(
            ("seam_types", 0, "allowance"),
            float(allowance),
            f"Set seam allowance to {allowance * 1000:g} mm",
        )
    return session.set_row_pattern(
        letter,
        {"seam_allowance": float(allowance)},
        f"Row {letter}: seam allowance {allowance * 1000:g} mm",
    )


def geometry_hash(session: ProjectSession) -> str:
    """Hash of the design geometry (what a manual outline override is drawn over)."""
    return session.group_hashes()["geometry"]


def set_manual_outline(
    session: ProjectSession,
    letter: str,
    points: Sequence[tuple[float, float]],
    reason: str = "manual edit in the 2D pattern editor",
) -> bool:
    """Replace a row's finished outline by hand: a flagged manual override.

    The override is recorded in the provenance log with the largest vertex movement and
    the edge-length changes; seam matching and simulation staleness follow from the
    dependency graph.

    Parameters
    ----------
    session : ProjectSession
        Session to edit.
    letter : str
        Panel row.
    points : sequence of (float, float)
        Outline in the editable layout (:func:`~envelopelab.project.gore_design.
        outline_edges`), m.
    reason : str
        Why the outline was edited.
    """
    edges = outline_edges(points)
    assert session.design.gores is not None
    base = next(r for r in panel_rows(session.design, session.patterns) if r.label == letter)
    reference = np.asarray(editable_outline(base, len(points) // 2))
    moved = float(np.max(np.hypot(*(np.asarray(points) - reference).T)))
    override = ManualOutline(
        points=[(float(x), float(y)) for x, y in points],
        created=utc_now(),
        reason=reason,
        base_hash=geometry_hash(session),
    )
    detail = (
        f"finished outline overridden by hand ({reason}); largest vertex movement "
        f"{moved * 1000:.1f} mm; edges right {edges['right']:.4f} m, left "
        f"{edges['left']:.4f} m, top {edges['top']:.4f} m, bottom {edges['bottom']:.4f} m; "
        f"outline hash {canonical_hash(override.points)[:12]}"
    )
    return session.set_row_pattern(
        letter,
        {"manual_outline": override.model_dump(mode="json")},
        f"Row {letter}: manual outline override",
        provenance=("manual outline override", f"row {letter}", detail),
    )


def clear_manual_outline(session: ProjectSession, letter: str) -> bool:
    """Remove a row's manual outline override (logged in the provenance)."""
    return session.set_row_pattern(
        letter,
        {"manual_outline": None},
        f"Row {letter}: remove manual outline override",
        provenance=(
            "remove manual outline override",
            f"row {letter}",
            "generated outline restored",
        ),
    )


def manual_override_is_outdated(session: ProjectSession, letter: str) -> bool:
    """True when the geometry changed after the row's manual override was drawn."""
    manual = session.patterns.row(letter).manual_outline
    return manual is not None and manual.base_hash != geometry_hash(session)


def outline_within_tolerance(
    a: Sequence[tuple[float, float]], b: Sequence[tuple[float, float]]
) -> bool:
    """Two outlines with the same vertices within the geometry tolerance (1 mm)."""
    pa, pb = np.asarray(a), np.asarray(b)
    return pa.shape == pb.shape and bool(np.all(np.hypot(*(pa - pb).T) <= LENGTH_TOLERANCE))


# -- special shapes ---------------------------------------------------------------------


def unique_shape_name(session: ProjectSession, base: str) -> str:
    """``base``, or ``base 2``, ``base 3``, ... when the name is taken."""
    taken = {s.name for s in session.state.shapes}
    if base not in taken:
        return base
    k = 2
    while f"{base} {k}" in taken:
        k += 1
    return f"{base} {k}"


def add_shape(session: ProjectSession, spec: ShapeSpec) -> bool:
    """Add a special shape (lengths in m, angles in degrees).

    Raises
    ------
    ValueError
        When a shape of that name exists.
    """
    data = spec.model_dump(mode="json")

    def mutate(shapes: list[dict[str, Any]]) -> None:
        if any(s["name"] == spec.name for s in shapes):
            raise ValueError(f"a special shape named {spec.name!r} exists")
        shapes.append(data)

    return session.edit_shapes(f"Add {spec.kind} shape {spec.name}", mutate)


def update_shape(session: ProjectSession, name: str, values: dict[str, Any]) -> bool:
    """Change fields of shape ``name`` (JSON values: m, deg; ``placement`` merges).

    Parameters
    ----------
    session : ProjectSession
        Session to edit.
    name : str
        Shape to change.
    values : dict
        New field values; ``placement`` may hold only the placement fields that change.

    Raises
    ------
    KeyError
        For an unknown shape.
    ValueError
        For invalid values or a name that is taken (nothing is changed).
    """

    def mutate(shapes: list[dict[str, Any]]) -> None:
        shape = next((s for s in shapes if s["name"] == name), None)
        if shape is None:
            raise KeyError(f"no special shape {name!r}")
        for key, value in values.items():
            if key == "placement":
                shape["placement"].update(value)
            elif key == "kind":
                raise ValueError("the kind of a shape cannot be changed")
            else:
                shape[key] = value
        new_name = values.get("name", name)
        if new_name != name:
            for other in shapes:
                link = other.get("mirror")
                if link and link["of"] == name:
                    link["of"] = new_name

    return session.edit_shapes(f"Edit shape {values.get('name', name)}", mutate)


def scale_mesh_shape(
    session: ProjectSession, name: str, along: float, across: float, height: float
) -> bool:
    """Resize mesh shape ``name`` about its base point (one undo step).

    The stored vertices are scaled (:func:`envelopelab.project.shapes.
    scaled_mesh_vertices`); a linked mirror twin follows.

    Parameters
    ----------
    session : ProjectSession
        Session to edit.
    name : str
        Mesh shape to resize.
    along, across, height : float
        Scale factors up the tape, across the gores and out of the envelope,
        dimensionless (1: unchanged).

    Returns
    -------
    bool
        Whether the shape changed (False when every factor is 1).

    Raises
    ------
    KeyError
        For an unknown shape.
    ValueError
        For a shape that is not a mesh, or a factor that is not finite and positive
        (nothing is changed).
    """
    from envelopelab.project.shapes import scaled_mesh_vertices

    def mutate(shapes: list[dict[str, Any]]) -> None:
        shape = next((s for s in shapes if s["name"] == name), None)
        if shape is None:
            raise KeyError(f"no special shape {name!r}")
        if shape["kind"] != "mesh":
            raise ValueError(f"{name!r} is not a mesh shape")
        scaled = scaled_mesh_vertices(np.asarray(shape["vertices"]), along, across, height)
        shape["vertices"] = [[float(c) for c in v] for v in scaled]

    return session.edit_shapes(f"Resize shape {name}", mutate)


def convert_mesh_to_revolved(
    session: ProjectSession,
    name: str,
    profile: Sequence[tuple[float, float]],
    smooth: bool = True,
) -> bool:
    """Replace mesh shape ``name`` by a revolved shape of ``profile`` (one undo step).

    The profile normally comes from :func:`envelopelab.features.mesh_profile.fit_profile`
    (whose deviation from the mesh the user has seen). The new shape keeps the name,
    placement, fabric, feed holes, cap, seam turn, panel widths, group and mirror link;
    the mesh's panels become its gores (at least 3; with fewer, equal widths). Undo
    brings the mesh back; a linked mirror twin follows.

    Parameters
    ----------
    session : ProjectSession
        Session to edit.
    name : str
        Mesh shape to convert.
    profile : sequence of (float, float)
        Profile points :math:`(\\rho, \\zeta)`, m, base first.
    smooth : bool
        Join the points by a spline (True) or straight segments.

    Returns
    -------
    bool
        Whether the state changed.

    Raises
    ------
    KeyError
        For an unknown shape.
    ValueError
        For a shape that is not a mesh, or a profile the shape does not accept (nothing
        is changed).
    """

    from envelopelab.project.shapes import RevolvedShape, to_primitive

    def mutate(shapes: list[dict[str, Any]]) -> None:
        index = next((i for i, s in enumerate(shapes) if s["name"] == name), None)
        if index is None:
            raise KeyError(f"no special shape {name!r}")
        shape = shapes[index]
        if shape["kind"] != "mesh":
            raise ValueError(f"{name!r} is not a mesh shape")
        mesh_only = ("kind", "vertices", "triangles", "source", "panels")
        new = {k: v for k, v in shape.items() if k not in mesh_only}
        gores = max(int(shape["panels"]), 3)
        if gores != int(shape["panels"]):
            new["panel_widths"] = []
        new.update(
            kind="revolved",
            profile=[[float(r), float(z)] for r, z in profile],
            gores=gores,
            smooth=bool(smooth),
        )
        # The profile must make a shape (base at zeta = 0, off the axis, ...), not only
        # valid data.
        to_primitive(RevolvedShape.model_validate(new)).validate()
        shapes[index] = new

    return session.edit_shapes(f"Convert shape {name} to a revolved profile", mutate)


def remove_shape(session: ProjectSession, name: str) -> bool:
    """Remove shape ``name`` (``KeyError`` if unknown)."""

    def mutate(shapes: list[dict[str, Any]]) -> None:
        index = next((i for i, s in enumerate(shapes) if s["name"] == name), None)
        if index is None:
            raise KeyError(f"no special shape {name!r}")
        del shapes[index]
        # Its mirror twins stay, as ordinary shapes.
        for other in shapes:
            link = other.get("mirror")
            if link and link["of"] == name:
                other["mirror"] = None

    return session.edit_shapes(f"Remove shape {name}", mutate)


def duplicate_shape(session: ProjectSession, name: str) -> str:
    """Copy shape ``name`` under a free name one gore further round; returns the new name."""
    spec = next((s for s in session.state.shapes if s.name == name), None)
    if spec is None:
        raise KeyError(f"no special shape {name!r}")
    new = unique_shape_name(session, f"{name} copy")
    data = spec.model_dump(mode="json")
    data["name"] = new
    data["mirror"] = None  # a copy of a twin is an ordinary shape
    count = session.design.gores.count if session.design.gores is not None else 1
    data["placement"]["gore"] = data["placement"]["gore"] % count + 1

    def mutate(shapes: list[dict[str, Any]]) -> None:
        shapes.append(data)

    session.edit_shapes(f"Duplicate shape {name}", mutate)
    return new


def _gore_frame(session: ProjectSession) -> tuple[int, float]:
    """Gore count and load-tape length (m) shapes are placed with."""
    from envelopelab.project.gore_design import design_profile

    design = session.design
    if design.gores is None:
        raise ValueError("special shapes are placed on a standard-gore design")
    return design.gores.count, float(design_profile(design).meridian_length)


def set_shape_group(session: ProjectSession, names: Sequence[str], group: str | None) -> bool:
    """Put shapes ``names`` in ``group`` (None: take them out of their group); one step.

    Raises
    ------
    KeyError
        For an unknown shape.
    ValueError
        For an invalid group name (nothing is changed).
    """

    def mutate(shapes: list[dict[str, Any]]) -> None:
        known = {s["name"] for s in shapes}
        for name in names:
            if name not in known:
                raise KeyError(f"no special shape {name!r}")
        for shape in shapes:
            if shape["name"] in names:
                shape["group"] = group

    what = f"Group {', '.join(names)} as {group}" if group else f"Ungroup {', '.join(names)}"
    return session.edit_shapes(what, mutate)


def rename_shape_group(session: ProjectSession, old: str, new: str) -> bool:
    """Rename group ``old`` to ``new`` (every member; one step).

    Raises
    ------
    KeyError
        For an unknown group.
    ValueError
        When ``new`` is taken or invalid.
    """

    def mutate(shapes: list[dict[str, Any]]) -> None:
        groups = {s.get("group") for s in shapes}
        if old not in groups:
            raise KeyError(f"no shape group {old!r}")
        if new in groups:
            raise ValueError(f"a shape group named {new!r} exists")
        for shape in shapes:
            if shape.get("group") == old:
                shape["group"] = new

    return session.edit_shapes(f"Rename shape group {old} to {new}", mutate)


def move_shape_group(session: ProjectSession, group: str, d_gore: float, d_tape: float) -> bool:
    """Move every shape of ``group`` ``d_gore`` gore widths round the envelope and
    ``d_tape`` m up the tape, feed holes with them (one step;
    :func:`envelopelab.project.shape_groups.moved`).

    Raises
    ------
    KeyError
        For an unknown group.
    ValueError
        When a shape or feed hole would leave the envelope (nothing is changed).
    """
    from envelopelab.project.shape_groups import group_members, moved

    members = group_members(session.state.shapes, group)
    if not members:
        raise KeyError(f"no shape group {group!r}")
    gores, length = _gore_frame(session)
    new = {s.name: moved(s, d_gore, d_tape, gores, length) for s in members}
    inside = set(new)
    # The axes the group's twins are mirrored across turn with the group; a twin pair
    # split between the group and other shapes, or an axis shared with other shapes,
    # cannot move with it.
    carried: set[str] = set()
    for s in session.state.shapes:
        if s.mirror is None:
            continue
        pair = {s.name, s.mirror.of}
        if pair & inside and not pair <= inside:
            raise ValueError(
                f"{s.name} mirrors {s.mirror.of} across {s.mirror.axis}: put both in "
                f"group {group} (or unlink them) to move it"
            )
        if pair <= inside:
            carried.add(s.mirror.axis)
    for s in session.state.shapes:
        if s.mirror is not None and s.mirror.axis in carried and s.name not in inside:
            raise ValueError(
                f"axis {s.mirror.axis} also mirrors {s.mirror.of}, outside group {group}"
            )

    def mutate(shapes: list[dict[str, Any]], axes: list[dict[str, Any]]) -> None:
        for i, shape in enumerate(shapes):
            if shape["name"] in new:
                shapes[i] = new[shape["name"]]
        for axis in axes:
            if axis["name"] in carried:
                axis["line"] = round((axis["line"] + d_gore) % gores, 6)

    return session.edit_symmetry(f"Move shape group {group}", mutate)


def mirror_shape_group(
    session: ProjectSession,
    group: str,
    line: float | None = None,
    copy: bool = True,
    axis: str | None = None,
) -> list[str]:
    """Mirror the shapes of ``group`` in the meridian plane at gore position ``line``
    (gore widths from the first seam; :func:`envelopelab.project.shape_groups.mirrored`).

    ``copy``: add a mirrored copy of every member whose base point is not on the line
    (``<name> mirror``, in the same group); otherwise mirror the members in place. One
    undo step either way.

    Returns
    -------
    list of str
        The names of the shapes added (empty when mirrored in place).

    Raises
    ------
    KeyError
        For an unknown group.
    """
    from envelopelab.project.shape_groups import group_members, mirrored, on_line

    members = group_members(session.state.shapes, group)
    if not members:
        raise KeyError(f"no shape group {group!r}")
    gores, _ = _gore_frame(session)
    if axis is not None:
        # Linked twins of every member that is not a twin and not on the axis.
        twinned = {s.mirror.of for s in session.state.shapes if s.mirror is not None}
        names = [
            s.name
            for s in members
            if s.mirror is None
            and s.name not in twinned
            and not on_line(s, _axis_line(session, axis), gores)
        ]
        return _add_twins(session, names, axis, f"Mirror shape group {group} across {axis}")
    if line is None:
        raise ValueError("give a mirror line or an axis")
    if not copy:
        new = {s.name: mirrored(s, line, gores) for s in members}

        def flip(shapes: list[dict[str, Any]]) -> None:
            for i, shape in enumerate(shapes):
                if shape["name"] in new:
                    shapes[i] = new[shape["name"]]

        session.edit_shapes(f"Mirror shape group {group}", flip)
        return []
    taken = {s.name for s in session.state.shapes}
    added: list[dict[str, Any]] = []
    for spec in members:
        if on_line(spec, line, gores):
            continue
        data = mirrored(spec, line, gores)
        base, k = f"{spec.name} mirror", 2
        name = base
        while name in taken:
            name, k = f"{base} {k}", k + 1
        taken.add(name)
        data["name"] = name
        data["mirror"] = None  # an independent copy, not a linked twin
        added.append(data)

    def append(shapes: list[dict[str, Any]]) -> None:
        shapes.extend(added)

    if added:
        session.edit_shapes(f"Mirror copy of shape group {group}", append)
    return [d["name"] for d in added]


def _axis_line(session: ProjectSession, axis: str) -> float:
    found = next((a for a in session.state.symmetry_axes if a.name == axis), None)
    if found is None:
        raise KeyError(f"no symmetry axis {axis!r}")
    return float(found.line)


def add_symmetry_axis(session: ProjectSession, name: str, line: float) -> bool:
    """Add the symmetry axis ``name`` at gore position ``line`` (gore widths from the
    first seam; gore n's centreline is n - 0.5).

    Raises
    ------
    ValueError
        When the name is taken or invalid.
    """
    gores, _ = _gore_frame(session)

    def mutate(_shapes: list[dict[str, Any]], axes: list[dict[str, Any]]) -> None:
        if any(a["name"] == name for a in axes):
            raise ValueError(f"a symmetry axis named {name!r} exists")
        axes.append({"name": name, "line": round(float(line) % gores, 6)})

    return session.edit_symmetry(f"Add symmetry axis {name}", mutate)


def update_symmetry_axis(
    session: ProjectSession, name: str, line: float | None = None, new_name: str | None = None
) -> bool:
    """Move (``line``, gore position) or rename the symmetry axis ``name``; its mirror
    twins follow (one step).

    Raises
    ------
    KeyError
        For an unknown axis.
    ValueError
        When the new name is taken or invalid.
    """
    gores, _ = _gore_frame(session)

    def mutate(shapes: list[dict[str, Any]], axes: list[dict[str, Any]]) -> None:
        axis = next((a for a in axes if a["name"] == name), None)
        if axis is None:
            raise KeyError(f"no symmetry axis {name!r}")
        if line is not None:
            axis["line"] = round(float(line) % gores, 6)
        if new_name is not None and new_name != name:
            if any(a["name"] == new_name for a in axes):
                raise ValueError(f"a symmetry axis named {new_name!r} exists")
            axis["name"] = new_name
            for s in shapes:
                link = s.get("mirror")
                if link and link["axis"] == name:
                    link["axis"] = new_name

    return session.edit_symmetry(f"Edit symmetry axis {name}", mutate)


def remove_symmetry_axis(session: ProjectSession, name: str) -> bool:
    """Remove the symmetry axis ``name``.

    Raises
    ------
    KeyError
        For an unknown axis.
    ValueError
        While mirror twins are mirrored across it (unlink or remove them first).
    """
    users = [s.name for s in session.state.shapes if s.mirror and s.mirror.axis == name]
    if users:
        raise ValueError(
            f"symmetry axis {name} mirrors {', '.join(users)}; unlink or remove them first"
        )

    def mutate(_shapes: list[dict[str, Any]], axes: list[dict[str, Any]]) -> None:
        index = next((i for i, a in enumerate(axes) if a["name"] == name), None)
        if index is None:
            raise KeyError(f"no symmetry axis {name!r}")
        del axes[index]

    return session.edit_symmetry(f"Remove symmetry axis {name}", mutate)


def _add_twins(session: ProjectSession, names: list[str], axis: str, what: str) -> list[str]:
    """Add a linked mirror twin of every shape of ``names`` across ``axis``."""
    from envelopelab.project.symmetry import mirrored_data

    gores, _ = _gore_frame(session)
    line = _axis_line(session, axis)
    taken = {s.name for s in session.state.shapes}
    added: list[dict[str, Any]] = []
    for name in names:
        spec = next(s for s in session.state.shapes if s.name == name)
        base, k = f"{name} mirror", 2
        new = base
        while new in taken:
            new, k = f"{base} {k}", k + 1
        taken.add(new)
        data = mirrored_data(spec.model_dump(mode="json"), line, gores)
        data.update(name=new, mirror={"of": name, "axis": axis})
        added.append(data)
    if added:
        session.edit_shapes(what, lambda shapes: shapes.extend(added))
    return [d["name"] for d in added]


def mirror_shape(session: ProjectSession, name: str, axis: str) -> str:
    """Add a mirror twin of shape ``name`` across the symmetry axis ``axis``: named
    ``<name> mirror``, kept the mirror image of ``name`` after every edit (either side
    can be edited or dragged); returns its name.

    Raises
    ------
    KeyError
        For an unknown shape or axis.
    ValueError
        For a twin, a shape that already has a twin across that axis, or a shape whose
        base point lies on the axis (it would be its own mirror image).
    """
    from envelopelab.project.shape_groups import on_line

    spec = next((s for s in session.state.shapes if s.name == name), None)
    if spec is None:
        raise KeyError(f"no special shape {name!r}")
    if spec.mirror is not None:
        raise ValueError(f"{name} is already the mirror twin of {spec.mirror.of}")
    if any(
        s.mirror and s.mirror.of == name and s.mirror.axis == axis for s in session.state.shapes
    ):
        raise ValueError(f"{name} already has a mirror twin across {axis}")
    gores, _ = _gore_frame(session)
    if on_line(spec, _axis_line(session, axis), gores):
        raise ValueError(f"{name} stands on axis {axis}: it is its own mirror image")
    return _add_twins(session, [name], axis, f"Mirror shape {name} across {axis}")[0]


def unlink_mirror(session: ProjectSession, name: str) -> bool:
    """Make the mirror twin ``name`` an ordinary shape (it keeps its current geometry)."""

    def mutate(shapes: list[dict[str, Any]]) -> None:
        shape = next((s for s in shapes if s["name"] == name), None)
        if shape is None:
            raise KeyError(f"no special shape {name!r}")
        shape["mirror"] = None

    return session.edit_shapes(f"Unlink mirror twin {name}", mutate)


def move_feed_holes_clear(
    session: ProjectSession, placed: dict[str, PrimitiveDesign] | None = None
) -> list[str]:
    """Move every special shape's extra feed holes clear of their panels' seams (one undo
    step; :func:`envelopelab.project.shapes.clear_feed_holes`).

    ``placed`` maps shape names to the shapes already placed from the current state (the
    others are placed here).

    Returns
    -------
    list of str
        What was moved, and the holes that could not be (a hole under a shape's base point
        moves with the shape).

    Raises
    ------
    ValueError
        For a design without gores, or a shape that cannot be placed.
    """
    from envelopelab.project.shapes import clear_feed_holes, envelope_surface, feed_hole_clearance

    design = session.design
    if design.gores is None:
        raise ValueError("special shapes are placed on a standard-gore design")
    surface = envelope_surface(design, session.patterns)
    clearance = feed_hole_clearance(design, session.patterns)
    moved: dict[str, list[dict[str, Any]]] = {}
    notes: list[str] = []
    for spec in session.state.shapes:
        done = (placed or {}).get(spec.name)
        new, said = clear_feed_holes(spec, surface, clearance, done)
        notes += said
        if new.feed_holes != spec.feed_holes:
            moved[spec.name] = [h.model_dump(mode="json") for h in new.feed_holes]
    if moved:

        def mutate(shapes: list[dict[str, Any]]) -> None:
            for shape in shapes:
                if shape["name"] in moved:
                    shape["feed_holes"] = moved[shape["name"]]

        session.edit_shapes("Move feed holes clear of seams", mutate)
    return notes


# -- panel colours (a visual layer, ADR-0055) ---------------------------------------------


def paint_panels(
    session: ProjectSession,
    refs: Sequence[PanelRef],
    colour: str | None,
    description: str | None = None,
) -> bool:
    """Set the display colour of the panels ``refs`` (one undo step).

    Parameters
    ----------
    session : ProjectSession
        Open project.
    refs : sequence of PanelRef
        Envelope panels and special-shape pieces (:mod:`envelopelab.project.colours`).
    colour : str or None
        sRGB ``#rrggbb`` (or ``#rgb``); None clears the colour.
    description : str, optional
        History text (default: says what was painted).

    Returns
    -------
    bool
        Whether the state changed.

    Raises
    ------
    ValueError
        For a malformed colour (nothing is changed).
    """
    value = None if colour is None else normalise_colour(colour)
    if description is None:
        what = refs[0].label() if len(refs) == 1 else f"{len(refs)} panels"
        description = f"Clear colour of {what}" if value is None else f"Paint {what} {value}"
    return session.edit_colours(description, lambda c: painted(c, refs, value))


def replace_colour(session: ProjectSession, old: str, new: str | None) -> bool:
    """Repaint every panel of colour ``old`` with ``new`` (None: clear them; one step).

    Raises
    ------
    ValueError
        For a malformed colour.
    """
    old = normalise_colour(old)
    value = None if new is None else normalise_colour(new)
    text = f"Replace colour {old} with {value}" if value else f"Clear colour {old}"
    return session.edit_colours(text, lambda c: replaced(c, old, value))


def clear_colours(session: ProjectSession) -> bool:
    """Clear every panel colour (one step)."""
    return session.edit_colours("Clear all panel colours", lambda _c: PanelColours())


# -- overlays: appliqués sewn on the envelope (ADR-0056) ---------------------------------


def unique_name(session: ProjectSession, base: str) -> str:
    """``base`` or ``base 2``, ``base 3``, ... : a name no special shape or overlay has."""
    taken = {s.name for s in session.state.shapes} | {o.name for o in session.state.overlays}
    if base not in taken:
        return base
    k = 2
    while f"{base} {k}" in taken:
        k += 1
    return f"{base} {k}"


def add_overlay(session: ProjectSession, spec: OverlaySpec) -> bool:
    """Add an overlay (one step).

    Raises
    ------
    ValueError
        When a special shape or overlay of that name exists, or the overlay does not fit
        on the envelope (nothing is changed).
    """
    _check_overlay(session, spec)
    data = spec.model_dump(mode="json")

    def mutate(overlays: list[dict[str, Any]]) -> None:
        overlays.append(data)

    return session.edit_overlays(f"Add overlay {spec.name}", mutate)


def _check_overlay(session: ProjectSession, spec: OverlaySpec) -> None:
    """Refuse an overlay that cannot be laid on the envelope (ValueError)."""
    from envelopelab.project.overlays import overlay_layout
    from envelopelab.project.shapes import envelope_surface

    if session.design.gores is None:
        raise ValueError("overlays are placed on a standard-gore design")
    overlay_layout(spec, envelope_surface(session.design, session.patterns))


def update_overlay(session: ProjectSession, name: str, values: dict[str, Any]) -> bool:
    """Change fields of overlay ``name`` (JSON values: m, deg; ``placement`` merges; one
    step).

    Raises
    ------
    KeyError
        For an unknown overlay.
    ValueError
        For invalid values, a name that is taken, or an overlay that would not fit on the
        envelope (nothing is changed).
    """
    from envelopelab.project.overlays import OverlaySpec as Spec

    current = next((o for o in session.state.overlays if o.name == name), None)
    if current is None:
        raise KeyError(f"no overlay {name!r}")
    data = current.model_dump(mode="json")
    for key, value in values.items():
        if key == "placement":
            data["placement"].update(value)
        else:
            data[key] = value
    spec = Spec.model_validate(data)
    _check_overlay(session, spec)

    def mutate(overlays: list[dict[str, Any]]) -> None:
        for i, o in enumerate(overlays):
            if o["name"] == name:
                overlays[i] = spec.model_dump(mode="json")

    return session.edit_overlays(f"Edit overlay {spec.name}", mutate)


def remove_overlay(session: ProjectSession, name: str) -> bool:
    """Remove overlay ``name`` (``KeyError`` if unknown; one step)."""

    def mutate(overlays: list[dict[str, Any]]) -> None:
        kept = [o for o in overlays if o["name"] != name]
        if len(kept) == len(overlays):
            raise KeyError(f"no overlay {name!r}")
        overlays[:] = kept

    return session.edit_overlays(f"Remove overlay {name}", mutate)


def duplicate_overlay(session: ProjectSession, name: str) -> str:
    """Copy overlay ``name`` one gore round the envelope; returns the copy's name."""
    current = next((o for o in session.state.overlays if o.name == name), None)
    if current is None:
        raise KeyError(f"no overlay {name!r}")
    gores = session.design.gores.count if session.design.gores else 1
    placement = current.placement.model_copy(update={"gore": current.placement.gore % gores + 1})
    copy = current.model_copy(update={"name": unique_name(session, name), "placement": placement})
    add_overlay(session, copy)
    return copy.name
