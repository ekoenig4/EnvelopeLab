r"""Shape groups: several special shapes handled as one object (ADR-0041).

A *group* is a name shared by several shapes of a project (``ShapeSpec.group``), for
example a head made of a dome, two ears and a nose. Every shape keeps its own pieces,
checks and simulation; the group moves, mirrors and exports them together. Groups are
part of the shapes' data, so they are saved, undone and versioned with them, and a shape
that is removed or renamed cannot leave a group pointing at nothing.

Moving a group
--------------
A shape stands on the envelope at gore position :math:`g = n - \tfrac{1}{2} + a` (gore
number :math:`n` from 1, fraction :math:`a` across the gore from its centreline, gore
widths from the first seam) and tape position :math:`s` from the mouth (m). Moving a
group by :math:`(\Delta g, \Delta s)` moves every member's base point and feed holes to

.. math:: g' = (g + \Delta g) \bmod N, \qquad s' = s + \Delta s .

A turn :math:`\Delta g` is a rotation of the group about the envelope's axis, so the
shapes keep their sizes and spacing exactly. A shift :math:`\Delta s` along the tape
keeps each shape's own size and lean but not the arc between members, because gores
narrow towards the mouth and the crown: two shapes 1 m apart round the equator end up
about :math:`r(s')/r(s)` m apart.

Mirroring a group
-----------------
Mirroring in the meridian plane at gore position :math:`g_m` maps
:math:`g' = 2 g_m - g` (mod :math:`N`) and turns every direction round the shape's
axis the other way: the lean direction :math:`\psi' = -\psi`, the seam turn
:math:`\phi'_{off} = -\phi_{off}`, the panel widths :math:`w_1, w_M, \dots, w_2` (piece
1 stays centred on the turned seam, the others follow in the mirrored order), and a
mesh's vertices :math:`y' = -y` with every triangle turned over to keep its normal out.
A dome, tube or revolved profile is its own mirror image round its axis.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from envelopelab.project.shapes import ShapeSpec

#: A base point closer than this to the mirror line (gore widths) is on it: a mirrored
#: copy of that shape would lie on the shape itself (source: assumed).
ON_LINE = 1e-3


def group_members(shapes: Sequence[ShapeSpec], group: str) -> list[ShapeSpec]:
    """The shapes of ``group``, in project order."""
    return [s for s in shapes if s.group == group]


def group_names(shapes: Sequence[ShapeSpec]) -> list[str]:
    """Every group of ``shapes``, in the order of their first member."""
    out: list[str] = []
    for s in shapes:
        if s.group is not None and s.group not in out:
            out.append(s.group)
    return out


def _gore_position(gore: int, across: float) -> float:
    """Gore position of a placement (gore widths from the first seam)."""
    return gore - 0.5 + across


def _from_gore_position(g: float, count: int) -> tuple[int, float]:
    """Gore number (from 1) and fraction across (in [-0.5, 0.5)) of gore position ``g``."""
    g = g % count
    cell = min(int(math.floor(g)), count - 1)
    return cell + 1, round(g - cell - 0.5, 6)


def _tape(s: float, tape_length: float, what: str) -> float:
    if not 0.0 < s < tape_length:
        raise ValueError(f"{what} would leave the envelope (tape position {s:.3f} m)")
    return round(s, 6)


def moved(
    spec: ShapeSpec, d_gore: float, d_tape: float, gores: int, tape_length: float
) -> dict[str, Any]:
    """JSON data of ``spec`` moved by ``d_gore`` gore widths round the envelope and
    ``d_tape`` m up the tape (its feed holes with it).

    Parameters
    ----------
    spec : ShapeSpec
        Shape to move.
    d_gore : float
        Turn round the envelope's axis, gore widths (positive: towards higher gores).
    d_tape : float
        Shift along the load tape, m (positive: towards the crown).
    gores : int
        Number of gores N.
    tape_length : float
        Load-tape length from the mouth to the crown, m.

    Returns
    -------
    dict
        The shape's data (m, deg).

    Raises
    ------
    ValueError
        When the base point or a feed hole would leave the envelope.
    """
    data = spec.model_dump(mode="json")
    pl = data["placement"]
    g = _gore_position(pl["gore"], pl["across"]) + d_gore
    pl["gore"], pl["across"] = _from_gore_position(g, gores)
    pl["tape_position"] = _tape(pl["tape_position"] + d_tape, tape_length, spec.name)
    for i, hole in enumerate(data["feed_holes"]):
        g = _gore_position(hole["gore"], hole["across"]) + d_gore
        hole["gore"], hole["across"] = _from_gore_position(g, gores)
        what = f"{spec.name}: feed hole {i + 1}"
        hole["tape_position"] = _tape(hole["tape_position"] + d_tape, tape_length, what)
    return data


def on_line(spec: ShapeSpec, line: float, gores: int) -> bool:
    """True when ``spec``'s base point lies on the mirror line at gore position ``line``."""
    g = _gore_position(spec.placement.gore, spec.placement.across)
    gap = (g - line + 0.5 * gores) % gores - 0.5 * gores
    return abs(gap) < ON_LINE


def _angle(deg: float) -> float:
    """``deg`` in (-180, 180]."""
    out = -((-deg + 180.0) % 360.0) + 180.0
    return 180.0 if out == -180.0 else out


def mirrored(spec: ShapeSpec, line: float, gores: int) -> dict[str, Any]:
    """JSON data of ``spec`` mirrored in the meridian plane at gore position ``line``
    (module docstring): placement, lean direction, feed holes, seam turn, panel widths
    and a mesh's vertices and triangles.

    Parameters
    ----------
    spec : ShapeSpec
        Shape to mirror.
    line : float
        Gore position of the mirror plane, gore widths from the first seam (gore
        :math:`n`'s centreline is :math:`n - 1/2`, the seam after it :math:`n`).
    gores : int
        Number of gores N.

    Returns
    -------
    dict
        The mirrored shape's data (m, deg), under the same name.
    """
    data = spec.model_dump(mode="json")
    pl = data["placement"]
    g = 2.0 * line - _gore_position(pl["gore"], pl["across"])
    pl["gore"], pl["across"] = _from_gore_position(g, gores)
    pl["lean_toward_deg"] = _angle(-float(pl["lean_toward_deg"]))
    for hole in data["feed_holes"]:
        g = 2.0 * line - _gore_position(hole["gore"], hole["across"])
        hole["gore"], hole["across"] = _from_gore_position(g, gores)
    data["seam_offset_deg"] = _angle(-float(data["seam_offset_deg"]))
    widths = data["panel_widths"]
    if widths:
        data["panel_widths"] = [widths[0], *widths[1:][::-1]]
    if data.get("crown_seam_offset_deg") is not None:
        data["crown_seam_offset_deg"] = _angle(-float(data["crown_seam_offset_deg"]))
    crown = data.get("crown_panel_widths") or []
    if crown:
        data["crown_panel_widths"] = [crown[0], *crown[1:][::-1]]
    if "cap_direction_deg" in data:
        data["cap_direction_deg"] = _angle(-float(data["cap_direction_deg"]))
    if data.get("cap_across"):  # across the gores flips, up the tape stays (ADR-0052)
        data["cap_across"] = -float(data["cap_across"])
    crown = data.get("crown_shape")
    if crown:  # the crown outline mirrored across the gores too (ADR-0054)
        crown["turn_deg"] = _angle(-float(crown.get("turn_deg", 0.0)))
        crown["points"] = [[-float(a), float(b)] for a, b in crown.get("points", [])]
    if data["kind"] == "mesh":
        data["vertices"] = [[x, -y, z] for x, y, z in data["vertices"]]
        data["triangles"] = [[a, c, b] for a, b, c in data["triangles"]]
    return data
