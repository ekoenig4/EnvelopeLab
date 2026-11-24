r"""Positions on the balloon in metres or in balloon coordinates (gore and panel row).

A point on the envelope is stored as its gore :math:`k` (from 1), the fraction
:math:`a \in [-\tfrac12, \tfrac12]` of the gore's width from its centreline (``across``,
positive towards gore :math:`k + 1`) and its tape position :math:`s` (m along the load
tape from the mouth). The application can show and take every such position in one of
two ways (a display preference; what is stored does not change):

**Metres.** Gore :math:`k`, the offset from the gore's centreline across the cloth,

.. math:: x = 2\,a\,w(s) \quad \text{(m)},

with :math:`w(s)` the flat half width of the gore at :math:`s`, and :math:`s` itself.

**Balloon coordinates.** Gore :math:`k` plus the fraction across it from the seam with
gore :math:`k - 1` (0) to the seam with gore :math:`k + 1` (1),

.. math:: f_g = a + \tfrac12,

and the panel row :math:`r` that contains :math:`s` plus the fraction up it from its
bottom seam (0) to its top seam (1),

.. math:: f_r = \frac{s - s_{r,0}}{s_{r,1} - s_{r,0}}.

A point on a row seam belongs to the row above it (:math:`f_r = 0`), except at the
crown end of the top row (:math:`f_r = 1`). Both forms give the same point: the
conversions are exact inverses (up to rounding).

Assumptions: the rows tile the load tape from the mouth to the crown without gaps
(:class:`envelopelab.features.primitives.EnvelopeSurface` rows); the gore width is the
flat width the patterns are cut to.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import numpy as np

if TYPE_CHECKING:
    from envelopelab.features.primitives import EnvelopeSurface
    from envelopelab.project.shapes import ShapeSpec

PositionUnits = Literal["metres", "balloon"]
#: Ways of showing a position, the first the default.
POSITION_UNITS: tuple[PositionUnits, ...] = ("metres", "balloon")
#: Names of the ways of showing a position, for the user.
POSITION_UNIT_LABELS: dict[PositionUnits, str] = {
    "metres": "Metres",
    "balloon": "Balloon coordinates (gore and panel)",
}


@dataclass(frozen=True)
class BalloonPosition:
    """A point on the envelope in balloon coordinates.

    Attributes
    ----------
    gore : int
        Gore number, from 1.
    gore_fraction : float
        Fraction across the gore from the seam with the previous gore (0) to the seam
        with the next (1), dimensionless.
    row : str
        Label of the panel row that contains the point.
    row_fraction : float
        Fraction up the row from its bottom seam (0) to its top seam (1), dimensionless.
    """

    gore: int
    gore_fraction: float
    row: str
    row_fraction: float

    def label(self) -> str:
        """The position in words, e.g. ``gore 3 + 0.62, row F + 0.40``."""
        return (
            f"gore {self.gore} + {self.gore_fraction:.2f}, row {self.row} + {self.row_fraction:.2f}"
        )


def row_labels(surface: EnvelopeSurface) -> list[str]:
    """Labels of the envelope's panel rows, from the mouth up."""
    return [r.label for r in surface.rows]


def _row(surface: EnvelopeSurface, row: str) -> tuple[float, float]:
    for r in surface.rows:
        if r.label == row:
            return float(r.s_bottom), float(r.s_top)
    raise ValueError(f"no panel row {row!r}")


def row_position(surface: EnvelopeSurface, tape: float) -> tuple[str, float]:
    """The row containing tape position ``tape`` (m) and the fraction up it.

    Returns
    -------
    (str, float)
        Row label and fraction from its bottom seam (0) to its top seam (1),
        dimensionless. Positions beyond the ends of the tape are taken at the ends.
    """
    rows = surface.rows
    s = min(max(float(tape), float(rows[0].s_bottom)), float(rows[-1].s_top))
    i = min(int(surface.row_index(np.array([s]))[0]), len(rows) - 1)
    lo, hi = float(rows[i].s_bottom), float(rows[i].s_top)
    return rows[i].label, (s - lo) / (hi - lo) if hi > lo else 0.0


def tape_at(surface: EnvelopeSurface, row: str, fraction: float) -> float:
    """Tape position of the point ``fraction`` (dimensionless) up row ``row``, m.

    Raises
    ------
    ValueError
        For an unknown row or a fraction outside [0, 1].
    """
    if not 0.0 <= fraction <= 1.0:
        raise ValueError("a fraction up a row is between 0 (its bottom) and 1 (its top)")
    lo, hi = _row(surface, row)
    return lo + fraction * (hi - lo)


def balloon_position(
    surface: EnvelopeSurface, gore: int, across: float, tape: float
) -> BalloonPosition:
    """Balloon coordinates of a stored position (module docstring).

    Parameters
    ----------
    surface : EnvelopeSurface
        The envelope with its rows.
    gore : int
        Gore number, from 1.
    across : float
        Fraction of the gore's width from its centreline, in [-0.5, 0.5].
    tape : float
        Tape position from the mouth, m.
    """
    row, fraction = row_position(surface, tape)
    return BalloonPosition(int(gore), float(across) + 0.5, row, fraction)


def envelope_position(
    surface: EnvelopeSurface, gore: int, gore_fraction: float, row: str, row_fraction: float
) -> tuple[int, float, float]:
    """The stored form of a position given in balloon coordinates.

    Returns
    -------
    (int, float, float)
        Gore number, fraction ``across`` from its centreline in [-0.5, 0.5], and tape
        position from the mouth, m.

    Raises
    ------
    ValueError
        For a fraction outside [0, 1] or an unknown row.
    """
    if not 0.0 <= gore_fraction <= 1.0:
        raise ValueError("a fraction across a gore is between 0 (one seam) and 1 (the other)")
    return int(gore), float(gore_fraction) - 0.5, tape_at(surface, row, row_fraction)


def across_metres(surface: EnvelopeSurface, across: float, tape: float) -> float:
    """Offset from the gore's centreline (m, towards the next gore) of a point ``across``
    (fraction of the width) at tape position ``tape`` (m): :math:`x = 2 a w(s)`."""
    return 2.0 * float(across) * float(surface.half_width(np.array([float(tape)]))[0])


def across_from_metres(surface: EnvelopeSurface, offset: float, tape: float) -> float:
    """Fraction of the gore's width from its centreline of a point ``offset`` m from it
    at tape position ``tape`` (m).

    Raises
    ------
    ValueError
        When the point lies outside the gore there (more than its half width away).
    """
    w = float(surface.half_width(np.array([float(tape)]))[0])
    if w <= 0.0:
        if abs(offset) > 1e-9:
            raise ValueError("the gore has no width there")
        return 0.0
    across = float(offset) / (2.0 * w)
    if abs(across) > 0.5 + 1e-9:
        raise ValueError(
            f"{offset:.3f} m from the centreline is outside the gore there "
            f"(its half width is {w:.3f} m)"
        )
    return min(max(across, -0.5), 0.5)


def describe_position(
    surface: EnvelopeSurface, units: PositionUnits, gore: int, across: float, tape: float
) -> str:
    """A stored position in words, in metres or in balloon coordinates.

    Examples: ``gore 3, 0.120 m from its centre, 4.250 m up the tape`` and
    ``gore 3 + 0.62, row F + 0.40``.
    """
    if units == "balloon":
        return balloon_position(surface, gore, across, tape).label()
    x = across_metres(surface, across, tape)
    return f"gore {gore}, {x:+.3f} m from its centre, {tape:.3f} m up the tape"


_ROW_TEXT = re.compile(r"^\s*([^\s+]+)\s*(?:\+\s*([0-9]*\.?[0-9]+)\s*)?$")


def format_row_position(row: str, fraction: float) -> str:
    """A row and a fraction up it as text, e.g. ``F + 0.40``."""
    return f"{row} + {fraction:.3f}"


def parse_row_position(text: str) -> tuple[str, float]:
    """Read ``<row> + <fraction>`` (e.g. ``F + 0.4``; a row alone means its bottom seam).

    Returns
    -------
    (str, float)
        Row label and fraction up it, dimensionless.

    Raises
    ------
    ValueError
        For text of another form.
    """
    m = _ROW_TEXT.match(text)
    if m is None:
        raise ValueError(f"expected a row and a fraction up it, such as 'F + 0.4': {text!r}")
    return m.group(1), float(m.group(2)) if m.group(2) else 0.0


# -- positions on a special shape ----------------------------------------------------
#
# A position on a special shape uses the shape's own frame, not the envelope's: in
# balloon coordinates the fractions the shape stores (a horizontal split as the fraction
# of the skin's length from the rim, where the panels meet as fractions of the widest
# radius seen from above); in metres the same lengths in m.


def skin_length(spec: ShapeSpec) -> float:
    """Length :math:`S` of the shape's skin meridian from the rim (base circle) to the tip
    or the edge of a centred cap, m: the 100 % of its horizontal splits
    (:func:`envelopelab.features.primitives.split_heights`).

    Raises
    ------
    ValueError
        For a mesh shape (its panels cannot be split across).
    """
    from envelopelab.project.shapes import MeshShape, to_primitive

    if isinstance(spec, MeshShape):
        raise ValueError("a mesh shape's panels cannot be split across")
    rho, zeta = to_primitive(spec).meridian()  # type: ignore[union-attr]
    return float(np.sum(np.hypot(np.diff(rho), np.diff(zeta))))


def split_metres(spec: ShapeSpec) -> list[float]:
    """The shape's horizontal splits as lengths along the skin from the rim,
    :math:`f_i S`, m."""
    if not spec.splits:
        return []
    total = skin_length(spec)
    return [float(f) * total for f in spec.splits]


def split_fraction(spec: ShapeSpec, metres: float) -> float:
    """The split fraction of a point ``metres`` m along the skin from the rim,
    :math:`f = d / S`, dimensionless.

    Raises
    ------
    ValueError
        When the point is not between the rim and the top of the skin.
    """
    total = skin_length(spec)
    if not 0.0 < metres < total:
        raise ValueError(f"a split lies between the rim (0) and the top ({total:.3f} m)")
    return float(metres) / total
