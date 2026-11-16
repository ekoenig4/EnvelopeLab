r"""Will the envelope's panels print on the roll, and what would make them fit.

A panel's 1:1 page must lie across the print roll (:func:`envelopelab.export.templates.
roll_fit`: turned a quarter, upright, or to its narrowest). Three changes make a panel's
page narrower, and :func:`roll_advice` says which would work for the current design:

* **more gores**: a panel's width falls with the gore count :math:`N` (roughly as
  :math:`1/N` at a given radius) while its height stays; the smallest :math:`N` at which
  every piece fits is found by bisection over :math:`N` (the narrowest page of every
  piece does not grow with :math:`N`; checked, not assumed: the result is re-checked);
* **half gores**: each panel of the rows that do not fit is cut in two down the gore
  centreline (:func:`envelopelab.geometry.gore.half_panel`), about halving its width;
* **more rows**: a panel that is still too wide must be split into shorter rows.

The advice is computed, never applied: the builder chooses (the gore count changes the
balloon's look and every row's panels; half gores add a centre seam).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from envelopelab.export.templates import roll_fit
from envelopelab.project.gore_design import panel_rows, row_pieces

if TYPE_CHECKING:
    from envelopelab.design.model import DesignDocument
    from envelopelab.project.model import PatternSet

#: Largest gore count :func:`roll_advice` tries.
MAX_GORES = 200


@dataclass(frozen=True)
class PieceFit:
    """One piece on the roll.

    Attributes
    ----------
    name : str
        Piece (``row C`` or ``row C left half``).
    row : str
        Row letter.
    across, along : float
        Its page across and along the roll at the chosen turn, m.
    fits : bool
        Whether the page lies within the roll's width.
    turn : str
        How it is turned, in words.
    """

    name: str
    row: str
    across: float
    along: float
    fits: bool
    turn: str


@dataclass(frozen=True)
class RollAdvice:
    """Whether the envelope panels fit the roll, and what would make them fit.

    Attributes
    ----------
    roll : float
        Roll width, m.
    gores : int
        The design's gore count.
    pieces : list of PieceFit
        Every row piece of the design as it is.
    gores_needed : int or None
        Smallest gore count (from the current one up to :data:`MAX_GORES`) at which every
        piece fits, with the rows cut as they are now; None when none does.
    half_gores_rows : list of str
        Rows to cut as half gores so that every piece fits at the current gore count
        (the rows that do not fit now); empty when that does not make them all fit or
        nothing needs to change.
    too_wide_halved : list of str
        Rows whose halves are still wider than the roll at the current gore count: they
        need more gores or splitting into shorter rows.
    """

    roll: float
    gores: int
    pieces: list[PieceFit] = field(default_factory=list)
    gores_needed: int | None = None
    half_gores_rows: list[str] = field(default_factory=list)
    too_wide_halved: list[str] = field(default_factory=list)

    @property
    def oversize(self) -> list[PieceFit]:
        """The pieces wider than the roll however they are turned."""
        return [p for p in self.pieces if not p.fits]

    @property
    def fits(self) -> bool:
        """Every piece fits the roll."""
        return not self.oversize

    def summary(self) -> str:
        """The advice in words, for the builder."""
        roll = f"{self.roll * 1000:.0f} mm roll"
        if self.fits:
            widest = max((p.across for p in self.pieces), default=0.0)
            return f"Every panel fits the {roll} (widest page {widest * 1000:.0f} mm across)."
        rows = sorted({p.row for p in self.oversize})
        lines = [
            f"{len(self.oversize)} piece(s) of row {', '.join(rows)} are LARGER THAN THE "
            f"{roll}. Any of these makes them fit:"
        ]
        if self.gores_needed is not None:
            lines.append(
                f"• {self.gores_needed} gores or more (now {self.gores}): every panel is narrower."
            )
        if self.half_gores_rows:
            lines.append(
                f"• Half gores for row {', '.join(self.half_gores_rows)}: each panel cut in "
                "two down the centre."
            )
        if self.too_wide_halved:
            lines.append(
                f"• Split row {', '.join(self.too_wide_halved)} into shorter rows (even its "
                "halves are wider than the roll)."
            )
        if len(lines) == 1:
            lines.append("• Split the rows into shorter ones, or join paper.")
        return "\n".join(lines)


def piece_fits(design: DesignDocument, patterns: PatternSet, roll: float) -> list[PieceFit]:
    """Every envelope row piece (:func:`~envelopelab.project.gore_design.row_pieces`) on a
    roll ``roll`` m wide.

    Raises
    ------
    ValueError
        When the design's rows cannot be made.
    """
    out = []
    for piece in row_pieces(design, patterns, panel_rows(design, patterns)):
        fit = roll_fit(piece.cut, roll)
        out.append(
            PieceFit(piece.name, piece.row.label, fit.across, fit.along, fit.fits, fit.describe())
        )
    return out


def _with(
    design: DesignDocument, count: int | None = None, halves: set[str] | None = None
) -> DesignDocument:
    assert design.gores is not None
    gores = design.gores
    update: dict[str, object] = {}
    if count is not None:
        update["count"] = count
    if halves is not None:
        update["panel_rows"] = [
            r.model_copy(update={"half_gore": r.half_gore or r.letter in halves})
            for r in gores.panel_rows
        ]
    return design.model_copy(update={"gores": gores.model_copy(update=update)})


def _all_fit(design: DesignDocument, patterns: PatternSet, roll: float) -> bool:
    try:
        return all(p.fits for p in piece_fits(design, patterns, roll))
    except ValueError:
        return False


def roll_advice(design: DesignDocument, patterns: PatternSet, roll: float) -> RollAdvice:
    """Whether the panels fit a roll ``roll`` m wide, and the gore count or half gores
    that would make them fit (module docstring).

    Parameters
    ----------
    design : DesignDocument
        Standard-gore design.
    patterns : PatternSet
        Row seam-allowance overrides (m).
    roll : float
        Print roll width, m.

    Returns
    -------
    RollAdvice
        Lengths in m.

    Raises
    ------
    ValueError
        When the design's rows cannot be made.
    """
    assert design.gores is not None
    n = design.gores.count
    pieces = piece_fits(design, patterns, roll)
    advice = RollAdvice(roll, n, pieces)
    if advice.fits:
        return advice
    # Smallest gore count that fits: bisection between the current count and the most
    # tried, then a check of the result.
    needed: int | None = None
    if _all_fit(_with(design, count=MAX_GORES), patterns, roll):
        lo, hi = n, MAX_GORES  # lo does not fit, hi does
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if _all_fit(_with(design, count=mid), patterns, roll):
                hi = mid
            else:
                lo = mid
        needed = hi
    oversize_rows = {p.row for p in advice.oversize}
    halved = _with(design, halves=oversize_rows)
    halved_fits = piece_fits(halved, patterns, roll)
    still = sorted({p.row for p in halved_fits if not p.fits})
    return RollAdvice(
        roll,
        n,
        pieces,
        needed,
        []
        if still
        else sorted(oversize_rows - {r.letter for r in design.gores.panel_rows if r.half_gore}),
        still,
    )
