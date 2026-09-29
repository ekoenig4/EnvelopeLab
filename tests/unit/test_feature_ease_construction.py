"""Designed ease, match points, seam classification and construction checks."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from envelopelab.assembly.pipeline import import_build_pack
from envelopelab.features.construction import (
    ConstructionCheck,
    check_sequence,
    check_strip_assembly,
)
from envelopelab.features.ease import (
    classify_audit,
    classify_seam,
    loop_length,
    point_on_loop,
    rim_correspondence,
    rim_ease,
)
from envelopelab.features.spec import ConstructionStep, FeatureSpec, HostPlacement

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_match_points_share_the_surplus_evenly() -> None:
    ease = rim_ease(10.0, 10.8, 16)
    assert ease.ease == pytest.approx(0.8)
    assert ease.ease_fraction == pytest.approx(0.08)
    assert np.allclose(ease.segment_ease, 0.05)
    # Point at 30 % of segment 3 on the footprint meets 30 % of skin segment 3.
    s_fp = 3 * 10.0 / 16 + 0.3 * 10.0 / 16
    assert rim_correspondence(np.array([s_fp]), ease)[0] == pytest.approx(3 * 0.675 + 0.3 * 0.675)


def test_pooled_ease_ends_up_in_the_last_segment() -> None:
    ease = rim_ease(10.0, 10.8, 16, mode="pooled")
    assert ease.segment_ease[:-1] == pytest.approx(np.zeros(15))
    assert ease.max_segment_ease == pytest.approx(0.8)
    assert ease.max_segment_ease > rim_ease(10.0, 10.8, 16).max_segment_ease * 10


def test_seam_classes() -> None:
    assert classify_seam(1.0, 1.001) == "matched"
    assert classify_seam(1.0, 1.05, designed_ease=0.05) == "designed ease"
    assert classify_seam(1.0, 1.05) == "seam error"
    assert classify_seam(1.0, 1.08, designed_ease=0.05) == "seam error"


def test_intentional_ease_is_designed_ease_not_a_seam_error() -> None:
    """The generic special-shape fixture's appendage seam carries 40 mm designed ease."""
    built = import_build_pack(FIXTURES / "special_shape" / "build-pack.yaml")
    classes = classify_audit(built.audit)
    assert classes.of("tube_base") == "designed ease"
    assert classes.errors == []
    assert classes.counts()["designed ease"] >= 1


def test_loop_helpers() -> None:
    square = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]])
    assert loop_length(square) == pytest.approx(4.0)
    assert np.allclose(point_on_loop(square, np.array([1.5, 4.5])), [[1.0, 0.5], [0.5, 0.0]])


def _feature(steps: list[str]) -> FeatureSpec:
    return FeatureSpec(
        name="pod",
        kind="ram_air_pod",
        host=HostPlacement(ring="body", gores=(1, 2), rows=("A", "B")),
        construction=[ConstructionStep(step=s) for s in steps],  # type: ignore[arg-type]
    )


def test_construction_sequence_order_is_checked() -> None:
    good = check_sequence(
        _feature(["strip_seams", "ordinate_check", "rim_tape", "feed_holes", "ease_onto_envelope"])
    )
    assert all(isinstance(c, ConstructionCheck) and c.passed for c in good)
    bad = check_sequence(_feature(["ordinate_check", "strip_seams", "ease_onto_envelope"]))
    assert any(
        c.severity == "error" and c.check == "strip_seams before ordinate_check" for c in bad
    )
    reversed_ease = check_sequence(
        _feature(["strip_seams", "ease_onto_envelope", "ordinate_check"])
    )
    assert any(c.severity == "error" for c in reversed_ease)


def test_strip_assembly_within_tolerance() -> None:
    outline = np.array([[0.0, 0.0], [4.0, 0.0], [4.0, 2.0], [0.0, 2.0]])
    strips = [
        np.array([[0.0, 0.0], [4.0, 0.0], [4.0, 1.0], [0.0, 1.0]]),
        np.array([[0.0, 1.0], [4.0, 1.0], [4.0, 2.0], [0.0, 2.0]]),
    ]
    severity, deviation, _ = check_strip_assembly(strips, outline, 0.010)
    assert severity == "ok" and deviation == pytest.approx(0.0, abs=1e-12)
    # A strip seam that took 15 mm too little grows the assembly by 15 mm: out of tolerance.
    grown = [strips[0], strips[1] + np.array([0.0, 0.015])]
    severity, deviation, message = check_strip_assembly(grown, outline, 0.010)
    assert severity == "error" and deviation == pytest.approx(0.015, abs=1e-3), message
