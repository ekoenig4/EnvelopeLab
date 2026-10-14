"""Design edits used by the editors, each one undoable command on a :class:`ProjectSession`.

Profile edits apply the constraint locks (:func:`~envelopelab.project.gore_design.apply_locks`)
and, when ``keep_rows_fitted`` is set, rescale the panel rows to the new meridian length in
the same command, so the design stays consistent and one undo restores both.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any, Literal

import numpy as np

from envelopelab.design.model import DesignDocument, row_bottom_fraction
from envelopelab.geometry.gore import LENGTH_TOLERANCE, GoreLoft, GoreWidthModel
from envelopelab.project.dependencies import canonical_hash
from envelopelab.project.gore_design import (
    DEFAULT_CREST_LOFT,
    LockError,
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
)
from envelopelab.project.model import ConstraintLocks, ManualOutline, PatternSet, utc_now
from envelopelab.project.session import ProjectSession
from envelopelab.project.shapes import ShapeSpec

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
    design = session.design
    assert design.gores is not None
    interpolation = design.gores.profile_interpolation
    r, z = apply_locks(r, z, session.project.locks, design_width_model(design), interpolation)
    profile = profile_from_arrays(r, z, interpolation)

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
        interpolation = design.gores.profile_interpolation
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
    interpolation = design.gores.profile_interpolation
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
    interpolation: Literal["spline", "linear"],
    keep_rows_fitted: bool = True,
) -> bool:
    """Choose how the profile runs between control points: a spline or straight segments.

    The tape length, volume, height and widest diameter all depend on it, so the control
    points are corrected for the locked quantities and the panel rows refitted in the same
    command.

    Parameters
    ----------
    session : ProjectSession
        Session to edit.
    interpolation : {"spline", "linear"}
        Parametric cubic spline or straight tape segments (``GoreSpec.profile_interpolation``).
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
    if interpolation not in ("spline", "linear"):
        raise ValueError(f"unknown profile interpolation {interpolation!r}")
    if design.gores.profile_interpolation == interpolation:
        return False
    r0, z0 = control_arrays(design)
    r, z = apply_locks(r0, z0, session.project.locks, design_width_model(design), interpolation)
    heights = fit_row_heights(
        [row.finished_height for row in design.gores.panel_rows],
        profile_from_arrays(r, z, interpolation).meridian_length,
    )

    def mutate(data: dict[str, Any], _patterns: dict[str, Any]) -> None:
        gores = _gores(data)
        gores["profile_interpolation"] = interpolation
        gores["meridian_profile_control_points"] = [
            {"x": float(a), "y": float(b)} for a, b in zip(r, z, strict=True)
        ]
        if keep_rows_fitted:
            for row, h in zip(gores["panel_rows"], heights, strict=True):
                row["finished_height"] = h

    label = "straight segments" if interpolation == "linear" else "spline"
    return session.edit(f"Profile between points: {label}", mutate)


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
    interpolation = design.gores.profile_interpolation
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
