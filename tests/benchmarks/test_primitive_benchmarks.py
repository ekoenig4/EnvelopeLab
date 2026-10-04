"""Special-shape primitives: closed-form geometry and the preview-solver study page."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from envelopelab.validation.analytic_geometry import BenchmarkResult
from envelopelab.validation.pages import page_differences
from envelopelab.validation.primitives import geometry_benchmarks, render_markdown, solve_study

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "docs" / "validation" / "special-shape-primitives.md"
STUDY = ROOT / "docs" / "validation" / "special-shape-primitives.json"
RESULTS = geometry_benchmarks()


@pytest.mark.parametrize("result", RESULTS, ids=[r.name for r in RESULTS])
def test_geometry_within_tolerance(result: BenchmarkResult) -> None:
    assert result.passed, result


def test_generated_page_is_current() -> None:
    study = json.loads(STUDY.read_text(encoding="utf-8"))
    assert PAGE.read_text(encoding="utf-8") == render_markdown(RESULTS, study), (
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
    study = json.loads(STUDY.read_text(encoding="utf-8"))
    fresh = solve_study()
    assert page_differences(render_markdown(RESULTS, study), render_markdown(RESULTS, fresh)) == []
