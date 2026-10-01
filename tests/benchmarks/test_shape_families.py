from __future__ import annotations

from pathlib import Path

import pytest

from envelopelab.validation.analytic_geometry import BenchmarkResult
from envelopelab.validation.shape_families import render_markdown, run_benchmarks

ROOT = Path(__file__).resolve().parents[2]
RESULTS = run_benchmarks(ROOT)
PAGE = ROOT / "docs" / "validation" / "shape-families.md"


@pytest.mark.parametrize("result", RESULTS, ids=[r.name for r in RESULTS])
def test_benchmark_within_tolerance(result: BenchmarkResult) -> None:
    assert result.passed, result


def test_generated_page_is_current() -> None:
    assert PAGE.read_text(encoding="utf-8") == render_markdown(RESULTS), (
        "docs/validation/shape-families.md is stale; "
        "run python scripts/generate_validation_docs.py shapes"
    )
