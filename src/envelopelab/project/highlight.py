r"""What a selection is on the balloon: 3D lines to highlight and a point to face.

Every design mode shows the envelope in 3D beside its editor (ADR-0047). The selected
element (a panel row, a profile control point, a rigging component, ...) is drawn over
the envelope in the highlight colour, and the view turns to face it.

All lines are on the display surface (:func:`envelopelab.project.gore_design.
display_points`), whose frame is shared with the rigging lines (:func:`envelopelab.
rigging.analysis.rigging_polylines`): :math:`z` up from the mouth plane's reference,
gore :math:`g` (1..N) spanning azimuths :math:`2\pi(g-1)/N` to :math:`2\pi g/N`.

* ``row:X``: the row's band (the rings at its bottom and top seams) and the outline of
  one of its panels (gore 1), faced at that panel's centre.
* ``point:i``: the ring through profile control point :math:`i` (at the tape position
  on the profile nearest the point), faced at its height.
* ``profile`` / ``gores``: the meridian of gore 1's seam, the profile as designed.
* ``parachute``, ``flying_wires``, ``red_line``, ``turning_vents``: that component's
  rigging lines (the parachute with its shroud and centralizing lines); ``rigging``:
  them all.
* ``scoop``: the mouth arc over the gores the scoop is sewn to.

**Where a number acts** (:func:`hint_highlight`, ADR-0050): every number of the design
that can be edited names the part of the balloon it changes, so the 3D views draw that
part while the number is pointed at or edited. A *hint key* is a selection as above or
``field:<path>``, the field's path in the design data (``field:gores.mouth_diameter``):
the mouth ring for the mouth diameter, the top ring for the crown ring and the parachute
hole, the gore seams for the gore count and the vertical tapes, the row seams for the
horizontal tapes, a row's band for its height, the parachute's, the rigging's, a vent's
or the scoop's lines for theirs, and the whole envelope (every seam and both openings)
for what acts on all of it: the operating conditions, seams and materials.

Display only: nothing here enters a calculation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from envelopelab.design.model import DesignDocument
    from envelopelab.solvers.membrane import FloatArray

#: Points round a ring (per gore), and up a meridian.
RING_PER_GORE = 12
MERIDIAN_SAMPLES = 61

#: The rigging lines shown for each rigging selection (keys of ``rigging_polylines``).
RIGGING_KINDS: dict[str, tuple[str, ...]] = {
    "parachute": ("parachute", "shroud_lines", "centralizing_lines"),
    "flying_wires": ("flying_wires",),
    "red_line": ("red_line",),
    "turning_vents": ("turning_vents",),
}


@dataclass
class Highlight:
    """A selection drawn on the balloon.

    Attributes
    ----------
    label : str
        What is highlighted, in words.
    lines : list of ndarray, shape (k, 3)
        Polylines to draw in the highlight colour, m.
    focus : ndarray, shape (3,), or None
        The point to face, m (None: keep the view).
    key : str
        The selection it was made for (the view turns only when this changes).
    """

    label: str
    lines: list[FloatArray] = field(default_factory=list)
    focus: FloatArray | None = None
    key: str = ""


def ring(
    design: DesignDocument, s: float, theta0: float = 0.0, theta1: float = 2 * math.pi
) -> FloatArray:
    """The display surface round the envelope at tape position ``s``.

    Parameters
    ----------
    design : DesignDocument
        Gore design.
    s : float
        Tape position from the mouth, m.
    theta0, theta1 : float
        Azimuth range, rad (default: the whole ring).

    Returns
    -------
    ndarray, shape (k, 3)
        Points, m.
    """
    from envelopelab.project.gore_design import display_points

    assert design.gores is not None
    n = design.gores.count
    k = max(3, int(round(RING_PER_GORE * n * (theta1 - theta0) / (2 * math.pi)))) + 1
    theta = np.linspace(theta0, theta1, k)
    return np.asarray(display_points(design, np.full(k, float(s)), theta), float)


def meridian(design: DesignDocument, theta: float, s0: float, s1: float) -> FloatArray:
    """The display surface up the envelope at azimuth ``theta`` from tape position
    ``s0`` to ``s1`` (m); points (k, 3), m."""
    from envelopelab.project.gore_design import display_points

    s = np.linspace(s0, s1, MERIDIAN_SAMPLES)
    return np.asarray(display_points(design, s, np.full(len(s), float(theta))), float)


def tape_at(design: DesignDocument, r: float, z: float) -> float:
    """Tape position (m from the mouth) of the profile point nearest ``(r, z)`` (m)."""
    from envelopelab.project.gore_design import design_profile

    profile = design_profile(design)
    s = np.linspace(0.0, float(profile.meridian_length), 2001)
    d = np.hypot(np.asarray(profile.radius_at(s)) - r, np.asarray(profile.height_at(s)) - z)
    return float(s[int(np.argmin(d))])


def selection_highlight(
    design: DesignDocument,
    selection: str,
    rows: list[Any] | None = None,
    rigging: dict[str, list[FloatArray]] | None = None,
) -> Highlight | None:
    """The 3D highlight of a selected design element (module docstring).

    Parameters
    ----------
    design : DesignDocument
        Gore design.
    selection : str
        The selection (``row:B``, ``point:2``, ``parachute``, ...).
    rows : list of PanelRow, optional
        The design's panel rows (``s_bottom``, ``s_top``, ``label``; m), for ``row:``.
    rigging : dict of str to list of ndarray, optional
        The rigging lines (m), for the rigging selections.

    Returns
    -------
    Highlight or None
        None when the selection has nothing to show on the balloon.
    """
    from envelopelab.project.gore_design import design_profile

    if design.gores is None:
        return None
    n = design.gores.count
    length = float(design_profile(design).meridian_length)
    if selection.startswith("row:"):
        letter = selection[4:]
        row = next((r for r in rows or [] if r.label == letter), None)
        if row is None:
            return None
        s0, s1 = float(row.s_bottom), float(row.s_top)
        width = 2 * math.pi / n
        panel = np.vstack(
            [
                meridian(design, 0.0, s0, s1),
                ring(design, s1, 0.0, width),
                meridian(design, width, s1, s0),
                ring(design, s0, width, 0.0),
            ]
        )
        centre = meridian(design, 0.5 * width, 0.5 * (s0 + s1), 0.5 * (s0 + s1))[0]
        return Highlight(
            f"row {letter} (one of its {n} panels outlined)",
            [ring(design, s0), ring(design, s1), panel],
            centre,
            selection,
        )
    if selection.startswith("point:"):
        try:
            index = int(selection[6:])
            cp = design.gores.meridian_profile_control_points[index]
        except (ValueError, IndexError):
            return None
        s = tape_at(design, float(cp.x), float(cp.y))
        line = ring(design, s)
        return Highlight(f"control point {index + 1}", [line], line[len(line) // 4], selection)
    if selection in ("profile", "gores"):
        line = meridian(design, 0.0, 0.0, length)
        return Highlight("the profile (a gore seam)", [line], line[len(line) // 2], selection)
    if selection == "scoop":
        scoop = getattr(design, "scoop", None)
        if scoop is None:
            return None
        t0 = 2 * math.pi * (scoop.first_gore - 1) / n
        arc = ring(design, 0.0, t0, t0 + 2 * math.pi * scoop.gore_count / n)
        return Highlight(
            f"scoop (gores {scoop.first_gore}-{scoop.first_gore + scoop.gore_count - 1})",
            [arc],
            arc[len(arc) // 2],
            selection,
        )
    kinds = (
        tuple(k for v in RIGGING_KINDS.values() for k in v)
        if selection == "rigging"
        else RIGGING_KINDS.get(selection)
    )
    if kinds is None or rigging is None:
        return None
    lines = [np.asarray(line, float) for k in kinds for line in rigging.get(k, [])]
    if not lines:
        return None
    points = np.vstack(lines)
    return Highlight(selection.replace("_", " "), lines, points.mean(axis=0), selection)


def gore_seams(design: DesignDocument) -> list[FloatArray]:
    """Every vertical gore seam (the load tapes), mouth to top, m."""
    from envelopelab.project.gore_design import design_profile

    assert design.gores is not None
    n = design.gores.count
    length = float(design_profile(design).meridian_length)
    return [meridian(design, 2.0 * math.pi * k / n, 0.0, length) for k in range(n)]


def row_seams(design: DesignDocument, rows: list[Any] | None) -> list[FloatArray]:
    """Every horizontal row seam (the horizontal tapes) between the rows, m."""
    return [ring(design, float(r.s_top)) for r in (rows or [])[:-1]]


def _whole(design: DesignDocument, rows: list[Any] | None) -> list[FloatArray]:
    from envelopelab.project.gore_design import design_profile

    length = float(design_profile(design).meridian_length)
    return [*gore_seams(design), *row_seams(design, rows), ring(design, 0.0), ring(design, length)]


#: Sections of the design whose numbers act on the whole envelope, and what to say.
WHOLE_ENVELOPE = {
    "operating": "acts on the whole envelope (lift, pressure, temperature)",
    "seam_types": "every seam of the envelope",
    "zones": "the whole envelope's fabric",
    "features": "the envelope",
    "scale_variants": "the whole envelope",
}


def hint_highlight(
    design: DesignDocument,
    key: str,
    rows: list[Any] | None = None,
    rigging: dict[str, list[FloatArray]] | None = None,
) -> Highlight | None:
    """Where on the balloon the number (or element) ``key`` acts (module docstring).

    Parameters
    ----------
    design : DesignDocument
        Gore design.
    key : str
        Hint key: ``field:<dotted path>`` into the design data, or a selection
        (:func:`selection_highlight`).
    rows : list of PanelRow, optional
        The design's panel rows (m).
    rigging : dict of str to list of ndarray, optional
        The rigging lines (m).

    Returns
    -------
    Highlight or None
        Lines in m; None when the number has no place on the balloon (a name, a version).
    """
    from envelopelab.project.gore_design import design_profile

    if design.gores is None:
        return None
    if key == "equator":
        profile = design_profile(design)
        s = np.linspace(0.0, float(profile.meridian_length), 2001)
        widest = float(s[int(np.argmax(np.asarray(profile.radius_at(s))))])
        line = ring(design, widest)
        return Highlight("the equator (widest)", [line], line[len(line) // 4], key)
    if not key.startswith("field:"):
        return selection_highlight(design, key, rows=rows, rigging=rigging)
    path = key[len("field:") :].split(".")
    section, name = path[0], path[-1]
    length = float(design_profile(design).meridian_length)
    words = name.replace("_", " ")

    def made(label: str, lines: list[FloatArray], focus: FloatArray | None = None) -> Highlight:
        if focus is None and lines:
            focus = lines[0][len(lines[0]) // 4]
        return Highlight(label, lines, focus, key)

    if section == "gores":
        if name == "count":
            return made("gore count: every gore seam", gore_seams(design))
        if name == "mouth_diameter":
            return made("mouth diameter: the mouth", [ring(design, 0.0)])
        if name in ("crown_ring", "parachute_hole_diameter"):
            return made(f"{words}: the top opening", [ring(design, length)])
        if name == "seal_overlap":
            lo = max(0.0, length - float(design.gores.seal_overlap))
            return made(
                "seal overlap: the band below the top", [ring(design, length), ring(design, lo)]
            )
        if len(path) >= 3 and path[1] == "meridian_profile_control_points":
            return selection_highlight(design, f"point:{path[2]}")
        if path[1:] == ["panel_rows"]:
            return made("panel rows: every row seam", row_seams(design, rows))
        if len(path) >= 3 and path[1] == "panel_rows":
            index = int(path[2])
            letter = design.gores.panel_rows[index].letter
            h = selection_highlight(design, f"row:{letter}", rows=rows)
            return None if h is None else made(f"row {letter} {words}", h.lines, h.focus)
        return made(f"{words}: the profile", [meridian(design, 0.0, 0.0, length)])
    if section == "tapes":
        kind = path[1] if len(path) > 1 else ""
        if kind == "vertical":
            return made(f"vertical tape {words}: every gore seam", gore_seams(design))
        if kind == "horizontal":
            return made(f"horizontal tape {words}: the row seams", row_seams(design, rows))
        if kind == "rim":
            return made(f"rim tape {words}: the mouth", [ring(design, 0.0)])
        if kind == "hole":
            return made(f"hole tape {words}: the top opening", [ring(design, length)])
        return made(f"tapes {words}: every seam", _whole(design, rows))
    if section in ("parachute", "turning_vents", "scoop"):
        h = selection_highlight(design, section, rows=rows, rigging=rigging)
        return None if h is None else made(f"{section.replace('_', ' ')} {words}", h.lines, h.focus)
    if section == "rigging":
        part = next((p for p in path[1:] if p in ("flying_wires", "red_line")), "rigging")
        h = selection_highlight(design, part, rows=rows, rigging=rigging)
        return None if h is None else made(f"{part.replace('_', ' ')} {words}", h.lines, h.focus)
    if section in WHOLE_ENVELOPE:
        lines = _whole(design, rows)
        return made(f"{words}: {WHOLE_ENVELOPE[section]}", lines, lines[0][len(lines[0]) // 2])
    return None
