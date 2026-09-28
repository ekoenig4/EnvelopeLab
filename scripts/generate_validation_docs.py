"""Regenerate the generated pages under docs/validation/ from the validation suites."""

from __future__ import annotations

import sys
from pathlib import Path

from envelopelab.validation import analytic_geometry, pattern_import, preview_solver

ROOT = Path(__file__).resolve().parents[1]
ANALYTIC = ROOT / "docs" / "validation" / "analytic-geometry.md"
FIXTURES = ROOT / "docs" / "validation" / "pattern-import-fixtures.md"
PREVIEW = ROOT / "docs" / "validation" / "preview-solver-benchmarks.md"
ENVELOPE_FIXTURE = ROOT / "tests" / "fixtures" / "spherical_envelope" / "build-pack.yaml"


def main(argv: list[str] | None = None) -> None:
    """Regenerate all pages, or only those named (``analytic``, ``fixtures``, ``preview``)."""
    pages = set(argv if argv is not None else sys.argv[1:]) or {"analytic", "fixtures", "preview"}
    failed: list[str] = []
    ANALYTIC.parent.mkdir(parents=True, exist_ok=True)
    if "analytic" in pages:
        results = analytic_geometry.run_benchmarks()
        ANALYTIC.write_text(analytic_geometry.render_markdown(results), encoding="utf-8")
        failed += [r.name for r in results if not r.passed]
    if "fixtures" in pages:
        summaries = pattern_import.run_fixtures(pattern_import.fixture_paths(ROOT))
        FIXTURES.write_text(pattern_import.render_markdown(summaries), encoding="utf-8")
        failed += [s.name for s in summaries if not s.passed]
    if "preview" in pages:
        bench = preview_solver.run_benchmarks(ENVELOPE_FIXTURE)
        PREVIEW.write_text(preview_solver.render_markdown(bench), encoding="utf-8")
        failed += [r.name for r in bench.results if not r.passed]
    if failed:
        raise SystemExit(f"validation failed: {', '.join(failed)}")


if __name__ == "__main__":
    main()
