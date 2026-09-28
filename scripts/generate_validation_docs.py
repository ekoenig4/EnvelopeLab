"""Regenerate the generated pages under docs/validation/ from the validation suites."""

from __future__ import annotations

from pathlib import Path

from envelopelab.validation import analytic_geometry, pattern_import

ROOT = Path(__file__).resolve().parents[1]
ANALYTIC = ROOT / "docs" / "validation" / "analytic-geometry.md"
FIXTURES = ROOT / "docs" / "validation" / "pattern-import-fixtures.md"


def main() -> None:
    ANALYTIC.parent.mkdir(parents=True, exist_ok=True)
    results = analytic_geometry.run_benchmarks()
    ANALYTIC.write_text(analytic_geometry.render_markdown(results), encoding="utf-8")
    summaries = pattern_import.run_fixtures(pattern_import.fixture_paths(ROOT))
    FIXTURES.write_text(pattern_import.render_markdown(summaries), encoding="utf-8")
    failed = [r.name for r in results if not r.passed]
    failed += [s.name for s in summaries if not s.passed]
    if failed:
        raise SystemExit(f"validation failed: {', '.join(failed)}")


if __name__ == "__main__":
    main()
