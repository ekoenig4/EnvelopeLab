"""Design edits used by the editors, each one undoable command on a :class:`ProjectSession`.

Profile edits apply the constraint locks (:func:`~envelopelab.project.gore_design.apply_locks`)
and, when ``keep_rows_fitted`` is set, rescale the panel rows to the new meridian length in
the same command, so the design stays consistent and one undo restores both.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

import numpy as np

from envelopelab.geometry.gore import LENGTH_TOLERANCE, GoreLoft, GoreWidthModel
from envelopelab.project.dependencies import canonical_hash
from envelopelab.project.gore_design import (
    LockError,
    apply_locks,
    control_arrays,
    design_profile,
    design_volume,
    design_width_model,
    editable_outline,
    fit_row_heights,
    outline_edges,
    panel_rows,
    profile_from_arrays,
)
from envelopelab.project.model import ConstraintLocks, ManualOutline, utc_now
from envelopelab.project.session import ProjectSession
from envelopelab.project.shapes import ShapeSpec

LOCKABLE = ("height", "volume", "max_diameter", "gore_count")


def _gores(design: dict[str, Any]) -> dict[str, Any]:
    gores = design.get("gores")
    if not isinstance(gores, dict):
        raise ValueError("not a standard-gore design")
    return gores


def set_control_points(
    session: ProjectSession,
    points: Sequence[tuple[float, float]],
    description: str = "Edit profile",
    keep_rows_fitted: bool = True,
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
    r, z = apply_locks(r, z, session.project.locks, design_width_model(session.design))
    profile = profile_from_arrays(r, z)

    def mutate(design: dict[str, Any], _patterns: dict[str, Any]) -> None:
        gores = _gores(design)
        gores["meridian_profile_control_points"] = [
            {"x": float(a), "y": float(b)} for a, b in zip(r, z, strict=True)
        ]
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


def insert_control_point(
    session: ProjectSession, after: int, keep_rows_fitted: bool = True
) -> bool:
    """Insert a control point on the profile halfway along the tape after point ``after``."""
    r, z = control_arrays(session.design)
    if not 0 <= after < len(r) - 1:
        raise IndexError("insert between two existing control points")
    profile = design_profile(session.design)
    chord = np.concatenate(([0.0], np.cumsum(np.hypot(np.diff(r), np.diff(z)))))
    s_mid = 0.5 * (chord[after] + chord[after + 1]) * profile.meridian_length / chord[-1]
    new = (float(profile.radius_at(s_mid)), float(profile.height_at(s_mid)))
    points = list(zip(r.tolist(), z.tolist(), strict=True))
    points.insert(after + 1, new)
    return set_control_points(
        session, points, f"Insert control point {after + 2}", keep_rows_fitted
    )


def delete_control_point(
    session: ProjectSession, index: int, keep_rows_fitted: bool = True
) -> bool:
    """Remove a control point (at least two remain)."""
    r, z = control_arrays(session.design)
    if len(r) <= 2:
        raise ValueError("a profile needs at least two control points")
    points = list(zip(r.tolist(), z.tolist(), strict=True))
    del points[index]
    return set_control_points(
        session, points, f"Delete control point {index + 1}", keep_rows_fitted
    )


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
        r, z = apply_locks(r0, z0, session.project.locks, width_model)
        if not (np.array_equal(r, r0) and np.array_equal(z, z0)):
            new_points = [{"x": float(a), "y": float(b)} for a, b in zip(r, z, strict=True)]
            if keep_rows_fitted:
                heights = fit_row_heights(
                    [row.finished_height for row in design.gores.panel_rows],
                    profile_from_arrays(r, z).meridian_length,
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
    for i in range(26):
        candidate = chr(ord("A") + i)
        if candidate not in letters:
            return candidate
    raise ValueError("no free row letter")


def split_row(session: ProjectSession, index: int) -> bool:
    """Split a panel row into two rows of half its height (a new letter for the upper)."""
    assert session.design.gores is not None
    rows = session.design.gores.panel_rows
    letter = _next_letter([r.letter for r in rows])

    def mutate(design: dict[str, Any], _patterns: dict[str, Any]) -> None:
        data = _gores(design)["panel_rows"]
        h = data[index]["finished_height"]
        data[index]["finished_height"] = math.floor(h / 2 * 1e4) / 1e4
        # The new upper row gets the first free letter; existing rows keep their letters
        # so that their pattern annotations stay attached.
        data.insert(
            index + 1, {"letter": letter, "finished_height": h - data[index]["finished_height"]}
        )

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
        removed = data.pop(index + 1)["letter"]
        patterns["rows"].pop(removed, None)

    return session.edit(f"Merge rows {rows[index].letter} and {rows[index + 1].letter}", mutate)


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
        value = {
            "height": profile.height,
            "volume": design_volume(session.design, profile),
            "max_diameter": profile.max_width,
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

    return session.edit_shapes(f"Edit shape {values.get('name', name)}", mutate)


def remove_shape(session: ProjectSession, name: str) -> bool:
    """Remove shape ``name`` (``KeyError`` if unknown)."""

    def mutate(shapes: list[dict[str, Any]]) -> None:
        index = next((i for i, s in enumerate(shapes) if s["name"] == name), None)
        if index is None:
            raise KeyError(f"no special shape {name!r}")
        del shapes[index]

    return session.edit_shapes(f"Remove shape {name}", mutate)


def duplicate_shape(session: ProjectSession, name: str) -> str:
    """Copy shape ``name`` under a free name one gore further round; returns the new name."""
    spec = next((s for s in session.state.shapes if s.name == name), None)
    if spec is None:
        raise KeyError(f"no special shape {name!r}")
    new = unique_shape_name(session, f"{name} copy")
    data = spec.model_dump(mode="json")
    data["name"] = new
    count = session.design.gores.count if session.design.gores is not None else 1
    data["placement"]["gore"] = data["placement"]["gore"] % count + 1

    def mutate(shapes: list[dict[str, Any]]) -> None:
        shapes.append(data)

    session.edit_shapes(f"Duplicate shape {name}", mutate)
    return new
