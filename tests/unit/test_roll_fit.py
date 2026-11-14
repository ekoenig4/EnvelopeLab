"""Whether a piece's 1:1 page fits the print roll (envelopelab.export.templates)."""

from __future__ import annotations

import numpy as np
import pytest

from envelopelab.export.templates import MARGIN, roll_checks, roll_fit

ROLL = 60 * 0.0254  # m


def _rect(w: float, h: float) -> np.ndarray:
    return np.array([[0.0, 0.0], [w, 0.0], [w, h], [0.0, h]])


def test_page_is_the_cut_outline_plus_the_margin() -> None:
    fit = roll_fit(_rect(1.0, 0.5) + 3.0, ROLL)
    assert fit.width == pytest.approx(1.0 + 2 * MARGIN)
    assert fit.height == pytest.approx(0.5 + 2 * MARGIN)
    assert not fit.turned and not fit.oversize


def test_a_tall_narrow_piece_fits_turned() -> None:
    fit = roll_fit(_rect(1.0, 2.0), ROLL)
    assert fit.turned and not fit.oversize
    assert fit.short_side == pytest.approx(1.0 + 2 * MARGIN)


def test_a_piece_wider_than_the_roll_both_ways_is_oversize() -> None:
    fit = roll_fit(_rect(1.6, 2.0), ROLL)
    assert fit.oversize and not fit.turned


def test_the_margin_alone_can_make_a_piece_oversize() -> None:
    side = ROLL - MARGIN  # cut outline fits, its page does not
    assert roll_fit(_rect(side, side), ROLL).oversize


def test_roll_checks_warn_once_per_oversize_piece() -> None:
    checks = roll_checks(
        [("a-P1", _rect(0.5, 0.5)), ("a-P2", _rect(2.0, 2.0)), ("a-P3", _rect(1.7, 3.0))],
        ROLL,
    )
    assert [c.severity for c in checks] == ["warning", "warning"]
    assert "a-P2" in checks[0].message and "a-P3" in checks[1].message
    assert all("LARGER THAN THE 1524 mm ROLL" in c.message for c in checks)
    assert checks[0].value == pytest.approx(2.0 + 2 * MARGIN)
    assert checks[0].limit == pytest.approx(ROLL)


def test_roll_checks_pass_with_the_widest_short_side() -> None:
    checks = roll_checks([("a", _rect(0.5, 0.4)), ("b", _rect(1.0, 3.0))], ROLL)
    assert len(checks) == 1 and checks[0].passed
    assert checks[0].value == pytest.approx(1.0 + 2 * MARGIN)
    assert roll_checks([], ROLL) == []
