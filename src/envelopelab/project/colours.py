r"""Display colours of the panels: the envelope's and every special shape's (ADR-0055).

Builders choose the colour of every panel before they order cloth. This module keeps
those choices as a **visual layer** of the design state (``DesignState.colours``,
project format 8): it changes no fabric, material zone, mass, pattern or simulation, and
no artifact fingerprint reads it (:mod:`envelopelab.project.dependencies`), so painting
never makes anything stale.

Colours are sRGB hex strings ``#rrggbb`` (lower case; :func:`normalise_colour` also reads
``#rgb`` and the forms without ``#``). A panel is addressed by a :class:`PanelRef`:

* an **envelope panel** by its row letter and gore number (from 1); a row cut as half
  gores (ADR-0048) is coloured as one panel, both halves alike;
* a **special-shape piece** by the shape name, its tier letter (``A`` at the rim, then
  ``B``, ... above each horizontal split; ``A`` when the shape is not split) or
  :data:`CAP` for the cap that closes its top, and its gore or panel number round the
  axis (from 1; the cap is piece 1), as in the cut-piece labels ``<name>-G3B``.

The Colours mode draws the panels as a flat grid. The envelope cells are the gore map's
columns (:mod:`envelopelab.project.placement_map`) cut at the row seams: gore :math:`k`
(from 0) and row :math:`[s_0, s_1]` is the region

.. math:: |x - x_k| \le w(s), \qquad s_0 \le s \le s_1, \qquad x_k = (k + \tfrac12)\,W,

(:math:`w` the gore's flat half width, :math:`W` the column width; m). A shape's cells are
a schematic unit square, one column per piece at its relative width (``panel_widths``) and
one band per tier at its fraction of the profile (``splits``), with the cap a band above
(dimensionless; it shows the pieces, not their cut outlines).

Colours that point at panels no longer in the design (a row removed, fewer gores, a shape
deleted) are kept but not drawn; :func:`pruned` drops them, and every colour edit applies
it.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

import numpy as np
from numpy.typing import ArrayLike
from pydantic import BaseModel, ConfigDict, Field, field_validator

if TYPE_CHECKING:
    from envelopelab.project.placement_map import GoreMap
    from envelopelab.project.shapes import ShapeSpec
    from envelopelab.solvers.membrane import FloatArray

#: Tier key of the cap that closes a special shape's top.
CAP = "cap"
#: Tier letters of a special shape's pieces, from the rim up (as the cut-piece labels).
TIER_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
#: Height of a shape grid's cap band, as a fraction of the shape's (display only).
CAP_BAND = 0.14
#: Samples up the tape of every envelope cell's sides (display only).
CELL_SAMPLES = 17

_HEX = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

Scope = Literal["panel", "row", "gore", "all"]


def normalise_colour(text: str) -> str:
    """A colour as ``#rrggbb`` (lower case).

    Parameters
    ----------
    text : str
        ``#rrggbb``, ``#rgb``, ``rrggbb`` or ``rgb`` (sRGB, hexadecimal; spaces around
        are ignored).

    Returns
    -------
    str
        ``#rrggbb``.

    Raises
    ------
    ValueError
        For anything else.
    """
    match = _HEX.match(text.strip())
    if match is None:
        raise ValueError(f"not a colour: {text!r} (use #rrggbb)")
    digits = match.group(1).lower()
    if len(digits) == 3:
        digits = "".join(c * 2 for c in digits)
    return f"#{digits}"


def _normalise_map(value: Mapping[Any, Any]) -> dict[int, str]:
    out: dict[int, str] = {}
    for key, colour in value.items():
        index = int(key)
        if index < 1:
            raise ValueError("gore and piece numbers start at 1")
        out[index] = normalise_colour(str(colour))
    return out


class PanelColours(BaseModel):
    """Display colour of every coloured panel (module docstring); uncoloured panels are
    left out.

    Attributes
    ----------
    envelope : dict of str to dict of int to str
        Row letter to gore number (from 1) to colour (``#rrggbb``).
    shapes : dict of str to dict of str to dict of int to str
        Shape name to tier letter (or :data:`CAP`) to piece number (from 1) to colour.
    """

    model_config = ConfigDict(extra="forbid")

    envelope: dict[str, dict[int, str]] = Field(default_factory=dict)
    shapes: dict[str, dict[str, dict[int, str]]] = Field(default_factory=dict)

    @field_validator("envelope", mode="before")
    @classmethod
    def _envelope(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value
        out = {str(row): _normalise_map(gores) for row, gores in value.items()}
        return {row: gores for row, gores in out.items() if gores}

    @field_validator("shapes", mode="before")
    @classmethod
    def _shapes(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value
        out: dict[str, dict[str, dict[int, str]]] = {}
        for name, tiers in value.items():
            kept = {str(t): _normalise_map(p) for t, p in tiers.items()}
            kept = {t: p for t, p in kept.items() if p}
            if kept:
                out[str(name)] = kept
        return out

    def is_empty(self) -> bool:
        """No panel is coloured."""
        return not self.envelope and not self.shapes

    def colour_of(self, ref: PanelRef) -> str | None:
        """Colour of one panel (None: not coloured)."""
        if ref.shape is None:
            return self.envelope.get(ref.group, {}).get(ref.index)
        return self.shapes.get(ref.shape, {}).get(ref.group, {}).get(ref.index)

    def used(self) -> list[str]:
        """Every colour in use, the most used first (ties: the first painted first)."""
        counts: Counter[str] = Counter()
        for gores in self.envelope.values():
            counts.update(gores.values())
        for tiers in self.shapes.values():
            for pieces in tiers.values():
                counts.update(pieces.values())
        return [c for c, _ in counts.most_common()]

    def to_data(self) -> dict[str, Any]:
        """JSON data (sorted keys; gore and piece numbers as strings)."""
        data: dict[str, Any] = self.model_dump(mode="json")
        return data


@dataclass(frozen=True)
class PanelRef:
    """One panel (module docstring).

    Attributes
    ----------
    shape : str or None
        Special shape name; None: the envelope.
    group : str
        Envelope row letter, or a shape's tier letter or :data:`CAP`.
    index : int
        Gore number (envelope) or piece number round the shape's axis, from 1.
    """

    shape: str | None
    group: str
    index: int

    def label(self) -> str:
        """Short name for the user (``row C, gore 5``; ``Dome G3B``; ``Dome cap``)."""
        if self.shape is None:
            return f"row {self.group}, gore {self.index}"
        if self.group == CAP:
            return f"{self.shape} cap"
        return f"{self.shape} piece {self.index}{self.group}"


def painted(colours: PanelColours, refs: Iterable[PanelRef], colour: str | None) -> PanelColours:
    """``colours`` with the panels ``refs`` set to ``colour`` (None: uncoloured).

    Parameters
    ----------
    colours : PanelColours
        Current colours (not changed).
    refs : iterable of PanelRef
        Panels to paint.
    colour : str or None
        Colour (any form :func:`normalise_colour` reads), or None to clear.

    Returns
    -------
    PanelColours
        New colours.
    """
    value = None if colour is None else normalise_colour(colour)
    data = colours.model_dump()
    for ref in refs:
        if ref.shape is None:
            target = data["envelope"].setdefault(ref.group, {})
        else:
            target = data["shapes"].setdefault(ref.shape, {}).setdefault(ref.group, {})
        if value is None:
            target.pop(ref.index, None)
        else:
            target[ref.index] = value
    return PanelColours.model_validate(data)


def replaced(colours: PanelColours, old: str, new: str | None) -> PanelColours:
    """``colours`` with every panel of colour ``old`` set to ``new`` (None: uncoloured)."""
    old = normalise_colour(old)
    refs = [ref for ref, colour in coloured_panels(colours) if colour == old]
    return painted(colours, refs, new)


def coloured_panels(colours: PanelColours) -> list[tuple[PanelRef, str]]:
    """Every coloured panel with its colour."""
    out = [
        (PanelRef(None, row, gore), colour)
        for row, gores in colours.envelope.items()
        for gore, colour in gores.items()
    ]
    out += [
        (PanelRef(name, tier, piece), colour)
        for name, tiers in colours.shapes.items()
        for tier, pieces in tiers.items()
        for piece, colour in pieces.items()
    ]
    return out


def repeated(index: int, count: int, every: int = 0) -> list[int]:
    """``index`` and, when ``every`` > 0, every ``every``-th number round from it.

    Parameters
    ----------
    index : int
        Gore or piece number, from 1.
    count : int
        Number of gores or pieces round the axis.
    every : int
        Repeat period in gores or pieces (0: no repeat).

    Returns
    -------
    list of int
        Numbers from 1 to ``count``, ``index`` first.
    """
    if every <= 0 or every >= count:
        return [index]
    out = [index]
    k = index + every
    while (k - 1) % count + 1 != index:
        out.append((k - 1) % count + 1)
        k += every
    return out


def envelope_targets(
    rows: Sequence[str],
    count: int,
    row: str,
    gore: int,
    scope: Scope = "panel",
    every: int = 0,
) -> list[PanelRef]:
    """Envelope panels a click on ``row``, ``gore`` paints.

    Parameters
    ----------
    rows : sequence of str
        Row letters from the mouth up.
    count : int
        Number of gores.
    row : str
        Row letter clicked.
    gore : int
        Gore number clicked, from 1.
    scope : {"panel", "row", "gore", "all"}
        The panel, its whole row, its whole gore or every panel.
    every : int
        Also every ``every``-th gore round from it (0: no repeat); :func:`repeated`.

    Returns
    -------
    list of PanelRef
    """
    gores = list(range(1, count + 1)) if scope in ("row", "all") else repeated(gore, count, every)
    letters = list(rows) if scope in ("gore", "all") else [row]
    return [PanelRef(None, r, g) for r in letters for g in gores]


@dataclass(frozen=True)
class ShapeGrid:
    """A special shape's pieces as a grid (module docstring).

    Attributes
    ----------
    name : str
        Shape name.
    pieces : int
        Gores or panels round the axis.
    widths : tuple of float
        Relative width of every piece (sum 1).
    tiers : tuple of float
        Fractions of the profile where every tier starts and ends, from 0 (rim) to 1.
    cap : bool
        The shape has a cap (or, a tube, a flat tip disc), its piece :data:`CAP`.
    """

    name: str
    pieces: int
    widths: tuple[float, ...]
    tiers: tuple[float, ...]
    cap: bool

    @property
    def tier_letters(self) -> tuple[str, ...]:
        """Tier keys from the rim up (without the cap)."""
        return tuple(TIER_LETTERS[i] for i in range(len(self.tiers) - 1))

    def targets(
        self, group: str, index: int, scope: Scope = "panel", every: int = 0
    ) -> list[PanelRef]:
        """Pieces a click on tier ``group``, piece ``index`` paints (as
        :func:`envelope_targets`; ``row`` is a tier, ``gore`` a column of pieces; the cap
        is in every scope but ``panel`` and ``gore``, and alone when clicked)."""
        if group == CAP:
            if scope in ("panel", "gore", "row"):
                return [PanelRef(self.name, CAP, 1)]
            return self.all_refs()
        pieces = (
            list(range(1, self.pieces + 1))
            if scope in ("row", "all")
            else repeated(index, self.pieces, every)
        )
        letters = list(self.tier_letters) if scope in ("gore", "all") else [group]
        out = [PanelRef(self.name, t, p) for t in letters for p in pieces]
        if scope == "all" and self.cap:
            out.append(PanelRef(self.name, CAP, 1))
        return out

    def all_refs(self) -> list[PanelRef]:
        """Every piece."""
        out = [PanelRef(self.name, t, p + 1) for t in self.tier_letters for p in range(self.pieces)]
        if self.cap:
            out.append(PanelRef(self.name, CAP, 1))
        return out

    def cells(self) -> list[tuple[PanelRef, FloatArray]]:
        """Every piece as a polygon in the unit square (x across, y up; the cap band
        above y = 1, :data:`CAP_BAND` high), dimensionless."""
        xs = np.concatenate([[0.0], np.cumsum(self.widths)])
        xs[-1] = 1.0
        out: list[tuple[PanelRef, FloatArray]] = []
        for t, letter in enumerate(self.tier_letters):
            y0, y1 = self.tiers[t], self.tiers[t + 1]
            for p in range(self.pieces):
                x0, x1 = float(xs[p]), float(xs[p + 1])
                box = np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], dtype=np.float64)
                out.append((PanelRef(self.name, letter, p + 1), box))
        if self.cap:
            box = np.array(
                [[0.0, 1.0], [1.0, 1.0], [1.0, 1.0 + CAP_BAND], [0.0, 1.0 + CAP_BAND]],
                dtype=np.float64,
            )
            out.append((PanelRef(self.name, CAP, 1), box))
        return out


def shape_grid(spec: ShapeSpec) -> ShapeGrid:
    """The grid of a special shape's pieces (its count, widths, splits and cap)."""
    from envelopelab.project.shapes import TubeShape, cap_diameter, piece_count

    n = piece_count(spec)
    widths = np.asarray(spec.panel_widths or [1.0] * n, dtype=np.float64)
    widths = widths / widths.sum()
    tiers = (0.0, *(float(f) for f in spec.splits), 1.0)
    return ShapeGrid(
        spec.name,
        n,
        tuple(float(w) for w in widths),
        tiers,
        cap_diameter(spec) > 0.0 or (isinstance(spec, TubeShape) and spec.tip_radius > 0.0),
    )


def envelope_cells(m: GoreMap) -> list[tuple[PanelRef, FloatArray]]:
    """Every envelope panel as a polygon on the gore map (module docstring), m.

    Parameters
    ----------
    m : GoreMap
        Gore map (:func:`envelopelab.project.placement_map.gore_map`).

    Returns
    -------
    list of (PanelRef, ndarray of shape (n, 2))
        Gore 1 first, rows from the mouth up within each gore; closed polygons (the last
        point is not repeated), m.
    """
    out: list[tuple[PanelRef, FloatArray]] = []
    bands = [
        (label, s, np.asarray(m.half_width(s), dtype=np.float64))
        for label, s0, s1 in m.rows
        for s in [np.linspace(s0, s1, CELL_SAMPLES)]
    ]
    for k in range(m.gores):
        xc = (k + 0.5) * m.column
        for label, s, half in bands:
            poly = np.vstack(
                [np.column_stack([xc - half, s]), np.column_stack([xc + half, s])[::-1]]
            )
            out.append((PanelRef(None, label, k + 1), poly))
    return out


def pruned(
    colours: PanelColours,
    rows: Sequence[str],
    gores: int,
    grids: Iterable[ShapeGrid] = (),
) -> PanelColours:
    """``colours`` without the panels that are not in the design.

    Parameters
    ----------
    colours : PanelColours
        Colours.
    rows : sequence of str
        The envelope's row letters.
    gores : int
        The envelope's gore count (0: no gore envelope).
    grids : iterable of ShapeGrid
        Every special shape (:func:`shape_grid`).

    Returns
    -------
    PanelColours
    """
    live = {(ref.shape, ref.group, ref.index) for g in grids for ref in g.all_refs()}
    keep = [
        (ref, colour)
        for ref, colour in coloured_panels(colours)
        if (ref.shape is None and ref.group in rows and 1 <= ref.index <= gores)
        or (ref.shape is not None and (ref.shape, ref.group, ref.index) in live)
    ]
    out = PanelColours()
    for ref, colour in keep:
        out = painted(out, [ref], colour)
    return out


def colour_rgb(colour: str) -> tuple[float, float, float]:
    """sRGB components of a colour, 0-1 each."""
    digits = normalise_colour(colour)[1:]
    return (
        int(digits[0:2], 16) / 255.0,
        int(digits[2:4], 16) / 255.0,
        int(digits[4:6], 16) / 255.0,
    )


def _lookup(table: Mapping[int, str], keys: Sequence[int]) -> tuple[FloatArray, np.ndarray]:
    rgb = np.zeros((len(keys), 3), dtype=np.float64)
    mask = np.zeros(len(keys), dtype=bool)
    for index, colour in table.items():
        hit = np.asarray(keys) == index
        if hit.any():
            rgb[hit] = colour_rgb(colour)
            mask |= hit
    return rgb, mask


def envelope_face_colours(
    colours: PanelColours,
    rows: Sequence[str],
    face_row: ArrayLike,
    face_gore: ArrayLike,
) -> tuple[FloatArray, np.ndarray]:
    """Colour of every triangle of an envelope display mesh by its panel.

    Parameters
    ----------
    colours : PanelColours
        Panel colours.
    rows : sequence of str
        Row letters, mouth first.
    face_row : sequence of int
        Row index (into ``rows``) of every triangle.
    face_gore : sequence of int
        Gore number (from 1) of every triangle.

    Returns
    -------
    rgb : ndarray, shape (t, 3)
        sRGB 0-1 (0 where not coloured).
    mask : ndarray of bool, shape (t,)
        The triangle's panel is coloured.
    """
    row_of = np.asarray(face_row, dtype=np.int64)
    gore_of = np.asarray(face_gore, dtype=np.int64)
    rgb = np.zeros((len(row_of), 3), dtype=np.float64)
    mask = np.zeros(len(row_of), dtype=bool)
    for i, letter in enumerate(rows):
        table = colours.envelope.get(letter)
        on = row_of == i
        if not table or not on.any():
            continue
        part, hit = _lookup(table, gore_of[on].tolist())
        sub_rgb, sub_mask = rgb[on], mask[on]
        sub_rgb[hit], sub_mask[hit] = part[hit], True
        rgb[on], mask[on] = sub_rgb, sub_mask
    return rgb, mask


def shape_face_colours(
    colours: PanelColours,
    name: str,
    piece: ArrayLike,
    pieces: int,
    tier: ArrayLike | None = None,
) -> tuple[FloatArray, np.ndarray]:
    """Colour of every triangle of a special shape's display mesh by its cut piece.

    Parameters
    ----------
    colours : PanelColours
        Panel colours.
    name : str
        Shape name.
    piece : sequence of int
        Piece of every triangle round the axis, from 0; ``pieces`` (or more): the cap or
        tip disc.
    pieces : int
        Gores or panels round the axis.
    tier : sequence of int, optional
        Tier of every triangle from the rim, from 0 (None: all in the first tier).

    Returns
    -------
    rgb : ndarray, shape (t, 3)
        sRGB 0-1 (0 where not coloured).
    mask : ndarray of bool, shape (t,)
        The triangle's piece is coloured.
    """
    piece_of = np.asarray(piece, dtype=np.int64)
    count = len(piece_of)
    tiers = np.zeros(count, dtype=np.int64) if tier is None else np.asarray(tier, dtype=np.int64)
    rgb = np.zeros((count, 3), dtype=np.float64)
    mask = np.zeros(count, dtype=bool)
    for key, table in colours.shapes.get(name, {}).items():
        if key == CAP:
            on = piece_of >= pieces
            index = np.ones(count, dtype=np.int64)
        else:
            on = (piece_of < pieces) & (tiers == TIER_LETTERS.index(key))
            index = piece_of + 1
        if not on.any():
            continue
        part, hit = _lookup(table, index[on].tolist())
        sub_rgb, sub_mask = rgb[on], mask[on]
        sub_rgb[hit], sub_mask[hit] = part[hit], True
        rgb[on], mask[on] = sub_rgb, sub_mask
    return rgb, mask


def renamed(
    colours: PanelColours, before: Sequence[str], after: Sequence[str], shapes: bool
) -> PanelColours:
    """``colours`` following renamed rows (``shapes`` False) or shapes (True).

    A name is renamed when the list keeps its length and only the name at a position
    changed (a rename edits one name in place); any other change keeps the colours as
    they are (a removed name's colours are dropped by :func:`pruned` at the next colour
    edit).
    """
    if len(before) != len(after) or list(before) == list(after):
        return colours
    moves = {a: b for a, b in zip(before, after, strict=True) if a != b}
    if set(moves) & set(moves.values()):
        return colours  # a reorder or swap, not a rename
    data = colours.model_dump()
    table = data["shapes"] if shapes else data["envelope"]
    for old, new in moves.items():
        if old in table:
            table[new] = table.pop(old)
    return PanelColours.model_validate(data)


__all__ = [
    "CAP",
    "CAP_BAND",
    "TIER_LETTERS",
    "PanelColours",
    "PanelRef",
    "Scope",
    "ShapeGrid",
    "colour_rgb",
    "coloured_panels",
    "envelope_cells",
    "envelope_face_colours",
    "envelope_targets",
    "normalise_colour",
    "painted",
    "pruned",
    "renamed",
    "repeated",
    "replaced",
    "shape_face_colours",
    "shape_grid",
]
