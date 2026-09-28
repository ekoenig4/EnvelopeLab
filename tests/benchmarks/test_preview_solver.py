"""AGENTS.md §6.4 benchmarks for the preview solver and the generated validation page.

Running every benchmark (including the envelope mesh-refinement study) takes a few
minutes, so these tests are marked slow; the unit tests cover the same physics on small
meshes in the fast suite.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from envelopelab.validation.preview_solver import (
    PreviewBenchmarks,
    render_markdown,
    run_benchmarks,
)

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "docs" / "validation" / "preview-solver-benchmarks.md"
FIXTURE = ROOT / "tests" / "fixtures" / "spherical_envelope" / "build-pack.yaml"


@pytest.fixture(scope="module")
def bench() -> PreviewBenchmarks:
    return run_benchmarks(FIXTURE)


@pytest.mark.slow
def test_every_benchmark_is_within_tolerance(bench: PreviewBenchmarks) -> None:
    failed = [r for r in bench.results if not r.passed]
    assert not failed, "\n".join(f"{r.name}: error {r.error:.3g} > {r.tolerance}" for r in failed)


@pytest.mark.slow
def test_required_benchmarks_are_present(bench: PreviewBenchmarks) -> None:
    names = " ".join(r.name for r in bench.results)
    for required in (
        "Sphere",
        "Cylinder",
        "Hydrostatic",
        "Lift",
        "Catenary",
        "Simple shear",
        "pressure force vs mouth reaction",
        "Refinement, last two levels: total volume",
        "Refinement, last two levels: max displacement (all nodes)",
    ):
        assert required in names
    assert len(bench.refinement) >= 3
    assert all(level.converged for level in bench.refinement)


@pytest.mark.slow
def test_generated_page_is_current(bench: PreviewBenchmarks) -> None:
    assert PAGE.read_text(encoding="utf-8") == render_markdown(bench), (
        "docs/validation/preview-solver-benchmarks.md is stale; "
        "run python scripts/generate_validation_docs.py preview"
    )
