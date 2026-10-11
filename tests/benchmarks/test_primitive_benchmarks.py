"""Special-shape primitives: closed-form geometry and the preview-solver study page."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from envelopelab.validation.analytic_geometry import BenchmarkResult
from envelopelab.validation.pages import page_differences
from envelopelab.validation.primitives import (
    geometry_benchmarks,
    render_markdown,
    solve_study,
    study_differences,
)

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "docs" / "validation" / "special-shape-primitives.md"
STUDY = ROOT / "docs" / "validation" / "special-shape-primitives.json"
RESULTS = geometry_benchmarks()


@pytest.mark.parametrize("result", RESULTS, ids=[r.name for r in RESULTS])
def test_geometry_within_tolerance(result: BenchmarkResult) -> None:
    assert result.passed, result


def test_generated_page_is_current() -> None:
    # Compared number by number: closed-form errors are round-off (1e-16 m) whose last
    # digits differ between platforms.
    study = json.loads(STUDY.read_text(encoding="utf-8"))
    assert (
        page_differences(PAGE.read_text(encoding="utf-8"), render_markdown(RESULTS, study)) == []
    ), (
        "docs/validation/special-shape-primitives.md is stale; "
        "run python scripts/generate_validation_docs.py primitives"
    )


def test_study_converges_and_tracks_the_designed_height() -> None:
    study = json.loads(STUDY.read_text(encoding="utf-8"))
    cut = [r for r in study if r["skin_rest"] == "cut pattern"]
    assert all(r["converged"] for r in study)
    # The inflated dome stays within 3 % of its designed height at every mesh size, and
    # the two finest meshes agree within 1 %.
    for r in cut:
        assert abs(r["projected_height_m"] / r["designed_height_m"] - 1.0) < 0.03
    assert abs(cut[-1]["projected_height_m"] / cut[-2]["projected_height_m"] - 1.0) < 0.01


@pytest.mark.slow
def test_study_reproduces_the_committed_results() -> None:
    # Row by row within STUDY_TOLERANCES: the Gmsh/OCC mesh differs between operating
    # systems, so node counts and peak values are compared within mesh tolerances
    # (ekoenig4/EnvelopeLab#14); heights and pressure within the platform tolerance.
    study = json.loads(STUDY.read_text(encoding="utf-8"))
    assert study_differences(study, solve_study()) == []


def test_study_differences_flag_real_changes() -> None:
    study = json.loads(STUDY.read_text(encoding="utf-8"))
    assert study_differences(study, study) == []
    # Observed macOS vs Linux mesh differences are accepted.
    mac = [dict(r) for r in study]
    mac[-1]["nodes"], mac[-1]["lowest_fos"] = 1407, mac[-1]["lowest_fos"] * 113 / 119
    mac[0]["skin_wrinkled_fraction"] -= 0.01
    assert study_differences(study, mac) == []
    # A height change of 1 % or a lost convergence is not.
    taller = [dict(r) for r in study]
    taller[0]["projected_height_m"] *= 1.01
    assert study_differences(study, taller)
    failed = [dict(r) for r in study]
    failed[1]["converged"] = False
    assert study_differences(study, failed)
