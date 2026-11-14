"""How a piece's 1:1 page lies on the print roll (envelopelab.export.templates).

Pages are in the roll's frame: the page width runs across the roll (never wider than
it), the page height along the roll (any length).
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from envelopelab.export.build_pack import Sheet
from envelopelab.export.templates import MARGIN, layout, roll_checks, roll_fit, turn_points

ROLL = 60 * 0.0254  # m


def _rect(w: float, h: float) -> np.ndarray:
    return np.array([[0.0, 0.0], [w, 0.0], [w, h], [0.0, h]])


def test_the_row_height_goes_across_the_roll_first() -> None:
    """A panel wider than the roll but not as tall prints turned a quarter: its height
    (the row height, as panels are cut across the bolt) runs across the roll."""
    fit = roll_fit(_rect(2.4, 1.2) + 3.0, ROLL)
    assert fit.angle == 90.0 and fit.fits
    assert fit.across == pytest.approx(1.2 + 2 * MARGIN)
    assert fit.along == pytest.approx(2.4 + 2 * MARGIN)
    assert "height across the roll" in fit.describe()


def test_a_tall_narrow_piece_prints_upright() -> None:
    fit = roll_fit(_rect(1.0, 2.0), ROLL)
    assert fit.angle == 0.0 and fit.fits
    assert fit.across == pytest.approx(1.0 + 2 * MARGIN)
    assert fit.along == pytest.approx(2.0 + 2 * MARGIN)


def test_a_long_diagonal_piece_is_turned_to_its_narrowest() -> None:
    """A 0.6 m wide strip lying at 45 deg is 1.5 m+ wide both ways, but fits turned."""
    strip = turn_points(_rect(3.0, 0.6), 45.0)
    assert min(np.ptp(strip, axis=0)) > ROLL
    fit = roll_fit(strip, ROLL)
    assert fit.fits
    assert fit.across == pytest.approx(0.6 + 2 * MARGIN, abs=1e-6)
    assert fit.angle == pytest.approx(45.0) or fit.angle == pytest.approx(-45.0)


def test_a_piece_wider_than_the_roll_at_any_turn_is_oversize() -> None:
    fit = roll_fit(_rect(1.6, 2.0), ROLL)
    assert fit.oversize
    assert fit.across == pytest.approx(1.6 + 2 * MARGIN)  # its narrowest


def test_the_margin_alone_can_make_a_piece_oversize() -> None:
    side = ROLL - MARGIN  # the cut outline fits, its page does not
    assert roll_fit(_rect(side, side), ROLL).oversize


@given(st.floats(0.1, 4.0), st.floats(0.1, 4.0), st.floats(-180.0, 180.0), st.floats(0.5, 2.0))
@settings(max_examples=80, deadline=None)
def test_a_page_is_never_wider_than_the_roll_when_the_piece_can_fit(
    w: float, h: float, turn: float, roll: float
) -> None:
    """Whatever the piece's drawn orientation, a rectangle whose short side fits is
    printed no wider than the roll, and the page is drawn exactly as wide as reported."""
    piece = turn_points(_rect(w, h), turn)
    fit = roll_fit(piece, roll)
    if min(w, h) + 2 * MARGIN <= roll - 1e-6:
        assert fit.fits
    if fit.fits:
        assert fit.across <= roll
    lay = layout(Sheet("p", "p", "skin piece", 1, "skin", piece, piece, {}), roll)
    corners = np.array([lay.to_page(float(x), float(y)) for x, y in piece]) / (72 / 0.0254)
    assert corners.min(axis=0) == pytest.approx([MARGIN, MARGIN], abs=1e-9)
    assert corners[:, 0].max() + MARGIN == pytest.approx(lay.width)
    assert corners[:, 1].max() + MARGIN == pytest.approx(lay.height)

    # A turn, never a mirror image: the outline keeps its winding.
    def signed(a: np.ndarray) -> float:
        x, y = a[:, 0], a[:, 1]
        return float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))

    assert np.sign(signed(corners)) == np.sign(signed(piece))


def test_roll_checks_warn_once_per_oversize_piece() -> None:
    checks = roll_checks(
        [("a-P1", _rect(0.5, 0.5)), ("a-P2", _rect(2.0, 2.0)), ("a-P3", _rect(1.7, 3.0))],
        ROLL,
    )
    assert [c.severity for c in checks] == ["warning", "warning"]
    assert "a-P2" in checks[0].message and "a-P3" in checks[1].message
    assert all("LARGER THAN THE 1524 mm ROLL AT ANY TURN" in c.message for c in checks)
    assert checks[0].value == pytest.approx(2.0 + 2 * MARGIN)
    assert checks[0].limit == pytest.approx(ROLL)


def test_roll_checks_pass_with_the_widest_page_across_the_roll() -> None:
    checks = roll_checks([("a", _rect(0.5, 0.4)), ("b", _rect(1.0, 3.0))], ROLL)
    assert len(checks) == 1 and checks[0].passed
    assert checks[0].value == pytest.approx(1.0 + 2 * MARGIN)
    assert roll_checks([], ROLL) == []
    assert math.isfinite(checks[0].value)
