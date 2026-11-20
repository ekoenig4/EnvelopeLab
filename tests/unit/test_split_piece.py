"""Splitting one gore or panel of a special shape in two (split_piece)."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from envelopelab.features.primitives import crown_seam_angles, seam_angles
from envelopelab.project.session import ProjectSession
from envelopelab.project.shapes import (
    MAX_PIECES,
    DomeShape,
    TubeShape,
    default_shape,
    piece_count,
    split_piece,
    to_primitive,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "standard_gore" / "design.elproj"
SESSION = ProjectSession.open(FIXTURE)


def _angles(values: np.ndarray) -> np.ndarray:
    return np.sort(np.mod(np.asarray(values[:-1], float), 2.0 * math.pi))


def _split(spec: Any, index: int) -> Any:
    return type(spec).model_validate({**spec.model_dump(), **split_piece(spec, index)})


def _check(spec: Any, index: int, crown: bool = False) -> None:
    angles = crown_seam_angles if crown else seam_angles
    before = _angles(angles(to_primitive(spec)))
    after_spec = _split(spec, index)
    after = _angles(angles(to_primitive(after_spec)))
    assert piece_count(after_spec) == piece_count(spec) + 1
    # Every old seam is still there, plus one in the middle of the split piece.
    full = np.asarray(angles(to_primitive(spec)), float)
    middle = math.fmod(0.5 * (full[index] + full[index + 1]), 2.0 * math.pi) % (2.0 * math.pi)
    expected = np.sort(np.append(before, middle))
    assert after == pytest.approx(expected, abs=1e-9)


@pytest.mark.parametrize("index", [0, 1, 7, 15])
def test_splitting_an_equal_gore_keeps_every_other_seam(index: int) -> None:
    spec = default_shape("dome", SESSION.design, "X")
    _check(spec.model_copy(update={"seam_offset_deg": 12.0}), index)


@pytest.mark.parametrize("index", [0, 2])
def test_splitting_unequal_panels_and_the_crown(index: int) -> None:
    spec = default_shape("dome", SESSION.design, "X")
    assert isinstance(spec, DomeShape)
    widths = [3.0, 1.0, 2.0] + [1.0] * (spec.gores - 3)
    spec = DomeShape.model_validate(
        {
            **spec.model_dump(),
            "panel_widths": widths,
            "seam_offset_deg": -30.0,
            "crown_seam_offset_deg": 20.0,
            "crown_panel_widths": [1.0, 2.0] + [1.0] * (spec.gores - 2),
        }
    )
    _check(spec, index)
    _check(spec, index, crown=True)
    halves = split_piece(spec, index)["panel_widths"]
    assert halves[index] == halves[index + 1] == widths[index] / 2.0


def test_a_tube_takes_one_more_panel_and_the_limit_holds() -> None:
    spec = default_shape("tube", SESSION.design, "X")
    assert isinstance(spec, TubeShape)
    assert split_piece(spec, 0)["panels"] == spec.panels + 1
    with pytest.raises(ValueError):
        split_piece(spec, spec.panels)
    full = spec.model_copy(update={"panels": MAX_PIECES})
    with pytest.raises(ValueError):
        split_piece(full, 0)
