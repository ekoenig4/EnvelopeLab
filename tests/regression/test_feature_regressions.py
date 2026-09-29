"""Special-shape feature regressions: rim-tape load transfer, designed ease, the Alien pack.

The load-transfer golden output (tests/regression/golden/rim-load-transfer-calculix.json)
is the CalculiX result of envelopelab.validation.special_shapes.load_transfer_model;
the Alien build pack is a regression fixture only (tests/fixtures/alien/README.md).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pytest

from calculix_adapter import CalculixInstallation, run_calculix
from envelopelab.assembly.pipeline import BuildPackResult, import_build_pack
from envelopelab.features.construction import feature_checks
from envelopelab.features.ease import classify_audit
from envelopelab.features.importer import appendage_spec, tube_spec
from envelopelab.features.metrics import appendage_metrics
from envelopelab.features.spec import load_features
from envelopelab.report.feature_workflow import FeatureRunConfig, feature_reality_check
from envelopelab.solvers.dynamic_relaxation import solve
from envelopelab.solvers.model import OperatingConditions
from envelopelab.solvers.simulation import from_preview
from envelopelab.validation.pages import page_differences
from envelopelab.validation.preview_solver import GENERIC_FABRIC, GENERIC_TAPE
from envelopelab.validation.special_shapes import (
    MEASURABLE_RISE,
    SpecialShapeData,
    load_transfer_model,
    render_markdown,
)

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = Path(__file__).resolve().parent / "golden" / "rim-load-transfer-calculix.json"
ALIEN = ROOT / "tests" / "fixtures" / "alien" / "build-pack.yaml"
PAGE = ROOT / "docs" / "validation" / "special-shape-fixtures"
TAPES = {
    k: GENERIC_TAPE for k in ("Class 3 1/2 in", "25 mm load tape", "lightweight horizontal tape")
}
MATERIALS = {z: GENERIC_FABRIC for z in ("ripstop", "ripstop_black", "ripstop_doubled", "nomex")}


def _golden() -> dict[str, dict[str, float]]:
    data: dict[str, dict[str, float]] = json.loads(GOLDEN.read_text(encoding="utf-8"))["cases"]
    return data


def test_preview_load_transfer_matches_the_calculix_golden_output() -> None:
    """Preview vs CalculiX golden within 5 % (AGENTS.md cross-solver tolerance)."""
    golden = _golden()
    for key, caught in (("caught", True), ("not_caught", False)):
        am = load_transfer_model(caught)
        res = from_preview(am.model, solve(am.model))
        assert res.converged
        n1 = appendage_metrics(am, res).host_rim_max_n1
        assert n1 == pytest.approx(golden[key]["host_rim_max_n1_n_per_m"], rel=0.05)


@pytest.mark.slow
def test_removing_the_rim_to_tape_connection_raises_host_stress_calculix(
    ccx: CalculixInstallation,
) -> None:
    """CalculiX regression against the golden output: +20 % or more without the connection."""
    golden = _golden()
    values = {}
    for key, caught in (("caught", True), ("not_caught", False)):
        am = load_transfer_model(caught)
        preview = solve(am.model)
        res = run_calculix(am.model, start_positions=preview.positions)
        assert res.converged, [f.message for f in res.errors]
        m = appendage_metrics(am, res)
        assert m.verified
        values[key] = m.host_rim_max_n1
        assert m.host_rim_max_n1 == pytest.approx(golden[key]["host_rim_max_n1_n_per_m"], rel=1e-3)
        assert m.rim_tape_max_tension == pytest.approx(
            golden[key]["rim_tape_max_tension_n"], rel=1e-3
        )
    assert values["not_caught"] >= (1.0 + MEASURABLE_RISE) * values["caught"]


def test_special_shape_page_matches_its_data() -> None:
    data = SpecialShapeData.load(PAGE.with_suffix(".json"))
    committed = PAGE.with_suffix(".md").read_text(encoding="utf-8")
    assert page_differences(committed, render_markdown(data)) == []
    # The committed CalculiX load-transfer rows are the golden output.
    golden = _golden()
    for row in data.load_transfer:
        if row["solver"] == "calculix":
            key = "caught" if row["rim_tape_caught"] else "not_caught"
            assert row["host_rim_max_n1_n_per_m"] == pytest.approx(
                golden[key]["host_rim_max_n1_n_per_m"], rel=1e-9
            )


# --------------------------------------------------------------------------------------
# Alien regression fixture
# --------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def alien() -> BuildPackResult:
    return import_build_pack(ALIEN)


def test_alien_eye_rim_ease_is_designed_ease(alien: BuildPackResult) -> None:
    classes = classify_audit(alien.audit)
    doc = load_features(ALIEN)
    for feature in doc.features:
        if feature.rim.seam:
            assert classes.of(feature.rim.seam) == "designed ease"
    assert classes.errors == []


def test_alien_feature_geometry_from_the_patterns(alien: BuildPackResult) -> None:
    """Measured from the DXF against the pack's own figures (build-pack YAML intended)."""
    doc = load_features(ALIEN)
    pod = next(f for f in doc.features if f.kind == "ram_air_pod")
    spec, placement, geo = appendage_spec(pod, alien, TAPES)
    intended = pod.intended_si()
    assert geo.values["skin_offset_mean_m"] == pytest.approx(intended["skin_offset_m"], abs=0.005)
    assert geo.values["rim_ease_m"] == pytest.approx(intended["rim_ease_m"], abs=0.005)
    per_segment = geo.values["ease_per_segment_m"]
    assert per_segment == pytest.approx(intended["rim_ease_m"] / pod.rim.match_points, abs=1e-3)
    assert geo.values["footprint_height_m"] == pytest.approx(placement.span_height, abs=1e-3)
    assert not geo.findings  # every feed hole lies inside the footprint
    assert len(spec.holes) == len(pod.feed_holes)
    assert {t.name.split(" ")[0] for t in spec.host_tapes} == {"gore", "row"}


def test_alien_construction_sequence(alien: BuildPackResult) -> None:
    """Strip seams first, ordinates within 10 mm, then ease on; doubler caught at assembly."""
    doc = load_features(ALIEN)
    for feature in doc.features:
        checks = feature_checks(feature, alien, ALIEN.parent)
        assert all(c.passed for c in checks), [c for c in checks if not c.passed]
        names = [c.check for c in checks]
        if feature.kind == "ram_air_pod":
            steps = [s.step for s in feature.construction]
            assert (
                steps.index("strip_seams")
                < steps.index("ordinate_check")
                < steps.index("ease_onto_envelope")
            )
            ordinate = next(c for c in checks if c.check == "ordinate check")
            assert ordinate.value is not None and ordinate.value <= 0.010
        if feature.doubler is not None:
            doubler = next(c for c in checks if c.check == "doubler caught into seams")
            assert doubler.severity == "ok" and doubler.value == 4.0
        assert names


def test_alien_antenna_pattern_does_not_lean(alien: BuildPackResult) -> None:
    """The supplied cone pattern has equal side seams: a finding against the intended lean."""
    doc = load_features(ALIEN)
    antenna = next(f for f in doc.features if f.kind == "tubular")
    assert alien.rest_model is not None
    z_mouth = float(alien.rest_model.positions[:, 2].min())
    cond = OperatingConditions.hot_air(373.15, mouth_height=z_mouth)
    _, _, geo = tube_spec(antenna, alien, TAPES, cond)
    assert abs(geo.values["side_difference_m"]) < 0.01
    assert any("does not lean the tube" in msg for _, msg in geo.findings)


@pytest.mark.slow
def test_alien_full_reality_check_report(tmp_path: Path) -> None:
    """Import feature geometry and generate the full report (preview; not verified)."""
    cfg = FeatureRunConfig(MATERIALS, TAPES)
    run = feature_reality_check(ALIEN, "eye_pod_left", cfg)
    report = run.report
    assert run.preview.converged
    assert not report.verified and report.status_line.startswith("NOT VERIFIED")
    kinds = [s.kind for s in report.states]
    assert kinds == ["as_sewn", "preview"]
    assert report.deviation_stats["preview"].count == run.preview.n_nodes
    quantities = {d["quantity"] for d in report.dimensions}
    assert "reference volume (title notation)" in quantities
    ref_row = next(
        d for d in report.dimensions if d["quantity"] == "reference volume (title notation)"
    )
    doc = load_features(ALIEN)
    title = (ALIEN.parent / str(doc.reference["title_source"])).read_text(encoding="utf-8")
    assert re.search(r"2,550", title) and ref_row["reference"] == pytest.approx(2550.0)
    assert any(q.startswith("as-sewn envelope volume") for q in quantities)
    out = report.write_all(tmp_path)
    for key in ("html", "pdf", "json", "dimensions.csv", "deviation.csv", "sensitivity.csv"):
        assert out[key].exists() and out[key].stat().st_size > 0
    assert "NOT VERIFIED" in out["html"].read_text(encoding="utf-8")
    # Antenna with a one-parameter sensitivity sweep.
    cfg_sweep = FeatureRunConfig(MATERIALS, TAPES, sweep=True, sweep_parameters=("loss_factor",))
    ant = feature_reality_check(ALIEN, "antenna_g18", cfg_sweep)
    assert ant.report.input.sensitivity is not None
    assert len(ant.report.input.sensitivity.rows) == 3
    lean = ant.report.input.features[0].tube["preview"]
    assert lean["intended_lean_deg"] == pytest.approx(35.0)
    assert abs(lean["lean_error_deg"]) > 20.0  # the supplied pattern stands upright
    assert np.isfinite(lean["base_reaction_n"])


def test_no_fixture_specific_values_in_application_code() -> None:
    """Application packages name no fixture and hold none of its dimensions."""
    banned = re.compile(
        r"alien|eye_pod|eye_rim|antenna_g\d|\b1240\b|\b2550\b|\b3750\b|\b2250\b", re.I
    )
    packages = (
        "assembly",
        "commands",
        "design",
        "features",
        "geometry",
        "io",
        "materials",
        "report",
        "solvers",
    )
    offenders = []
    for pkg in packages:
        for path in (ROOT / "src" / "envelopelab" / pkg).rglob("*.py"):
            for k, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if banned.search(line):
                    offenders.append(f"{path.relative_to(ROOT)}:{k}: {line.strip()}")
    for path in (ROOT / "solvers").rglob("*.py"):
        for k, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if banned.search(line):
                offenders.append(f"{path.relative_to(ROOT)}:{k}: {line.strip()}")
    assert offenders == []
