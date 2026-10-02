"""Regenerate the generated pages under docs/validation/ from the validation suites."""

from __future__ import annotations

import sys
from pathlib import Path

from envelopelab.validation import (
    analytic_geometry,
    pattern_import,
    preview_solver,
    rigging,
    shape_families,
)

ROOT = Path(__file__).resolve().parents[1]
ANALYTIC = ROOT / "docs" / "validation" / "analytic-geometry.md"
FIXTURES = ROOT / "docs" / "validation" / "pattern-import-fixtures.md"
PREVIEW = ROOT / "docs" / "validation" / "preview-solver-benchmarks.md"
RIGGING = ROOT / "docs" / "validation" / "rigging-benchmarks.md"
CALCULIX = ROOT / "docs" / "validation" / "preview-vs-calculix"  # .json, .md, .svg
SPECIAL = ROOT / "docs" / "validation" / "special-shape-fixtures"  # .json, .md
SHAPES = ROOT / "docs" / "validation" / "shape-families.md"
ENVELOPE_FIXTURE = ROOT / "tests" / "fixtures" / "spherical_envelope" / "build-pack.yaml"
# Regression fixture of the special-shape page: which features to run, with generic
# assumed materials for its material zones and tapes, and the known limitations.
SPECIAL_FIXTURE_FEATURES = ("eye_pod_left", "antenna_g18")
SPECIAL_FIXTURE_ZONES = ("ripstop", "ripstop_black", "ripstop_doubled", "nomex")
SPECIAL_FIXTURE_TAPES = ("Class 3 1/2 in", "25 mm load tape", "lightweight horizontal tape")
SPECIAL_FIXTURE_NOTES = [
    "The pod sub-model converges with the preview solver at its fixture mesh (800 mm); at "
    "500 mm it does not converge within 200 000 iterations (the host fabric under the pod "
    "carries almost no pressure and wrinkles), so the pod height above is mesh-dependent "
    "and is not a prediction of the built pod.",
    "CalculiX did not converge on the 800 mm pod sub-model in a trial run (tension-field "
    "states kept changing "
    "between passes); the fixture's reports are therefore not verified.",
]


def main(argv: list[str] | None = None) -> None:
    """Regenerate all pages, or only those named (``analytic``, ``fixtures``, ``preview``,
    ``shapes``, ``rigging``, ``calculix``, ``special``).

    ``calculix`` runs the CalculiX verification study (needs ``ccx``, several minutes) and
    ``special`` the special-shape feature benchmarks (CalculiX rows when ``ccx`` is
    installed, a few minutes); both are regenerated only when named.
    """
    pages = set(argv if argv is not None else sys.argv[1:]) or {
        "analytic",
        "fixtures",
        "preview",
        "shapes",
        "rigging",
    }
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
    if "rigging" in pages:
        rig_results = rigging.run_benchmarks()
        RIGGING.write_text(rigging.render_markdown(rig_results), encoding="utf-8")
        failed += [r.name for r in rig_results if not r.passed]
    if "preview" in pages:
        bench = preview_solver.run_benchmarks(ENVELOPE_FIXTURE)
        PREVIEW.write_text(preview_solver.render_markdown(bench), encoding="utf-8")
        failed += [r.name for r in bench.results if not r.passed]
    if "shapes" in pages:
        shape_results = shape_families.run_benchmarks(ROOT)
        SHAPES.write_text(shape_families.render_markdown(shape_results), encoding="utf-8")
        failed += [r.name for r in shape_results if not r.passed]
    if "calculix" in pages:
        # Imported here: the adapter is optional and the other pages must not need it.
        from calculix_adapter import validation as calculix_validation

        data = calculix_validation.run_validation(ENVELOPE_FIXTURE, progress=print)
        data.save(CALCULIX.with_suffix(".json"))
        CALCULIX.with_suffix(".md").write_text(
            calculix_validation.render_markdown(data), encoding="utf-8"
        )
        CALCULIX.with_suffix(".svg").write_text(
            calculix_validation.render_svg(data), encoding="utf-8"
        )
        failed += [b.name for b in data.benchmarks if not b.passed]
    if "special" in pages:
        from envelopelab.validation import special_shapes

        verify = None
        version = ""
        try:
            from calculix_adapter import find_calculix, run_calculix

            inst = find_calculix()
            if inst is not None:
                version = inst.version

                def verify(model, start):  # type: ignore[no-untyped-def]
                    return run_calculix(model, start_positions=start)

        except ImportError:
            pass
        if verify is None:
            print("ccx not found: special-shape page without CalculiX rows")
        case = special_shapes.FixtureCase(
            "alien",
            SPECIAL_FIXTURE_FEATURES,
            {z: preview_solver.GENERIC_FABRIC for z in SPECIAL_FIXTURE_ZONES},
            {t: preview_solver.GENERIC_TAPE for t in SPECIAL_FIXTURE_TAPES},
            SPECIAL_FIXTURE_NOTES,
        )
        sdata = special_shapes.run_validation(ROOT, case, verify, version)
        sdata.save(SPECIAL.with_suffix(".json"))
        SPECIAL.with_suffix(".md").write_text(
            special_shapes.render_markdown(sdata), encoding="utf-8"
        )
        checks = special_shapes.blister_checks(sdata.blister)
        checks += special_shapes.load_transfer_checks(sdata.load_transfer)
        failed += [name for name, ok, _ in checks if not ok]
    if failed:
        raise SystemExit(f"validation failed: {', '.join(failed)}")


if __name__ == "__main__":
    main()
