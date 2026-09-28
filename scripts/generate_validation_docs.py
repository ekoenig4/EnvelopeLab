"""Regenerate docs/validation/analytic-geometry.md from the analytic benchmark suite."""

from __future__ import annotations

from pathlib import Path

from envelopelab.validation.analytic_geometry import render_markdown, run_benchmarks

TARGET = Path(__file__).resolve().parents[1] / "docs" / "validation" / "analytic-geometry.md"


def main() -> None:
    results = run_benchmarks()
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(render_markdown(results), encoding="utf-8")
    failed = [result.name for result in results if not result.passed]
    if failed:
        raise SystemExit(f"benchmarks failed: {', '.join(failed)}")


if __name__ == "__main__":
    main()
