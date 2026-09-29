"""Reality Check report: verification gating, labels and exports."""

from __future__ import annotations

import csv
import json
import math
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from envelopelab.features.builder import (
    AppendageModel,
    AppendageSpec,
    PressureSpec,
    build_appendage,
)
from envelopelab.features.metrics import appendage_metrics
from envelopelab.features.pressure import independent_chamber
from envelopelab.io.reference_mesh import ReferenceMesh
from envelopelab.report.pdf import PdfCanvas
from envelopelab.report.reality_check import (
    FeatureSection,
    ReportInput,
    VerificationPolicy,
    build_report,
)
from envelopelab.report.sensitivity import SweepSettings, sensitivity_sweep, sweep_cases
from envelopelab.solvers.dynamic_relaxation import solve
from envelopelab.solvers.model import OperatingConditions
from envelopelab.solvers.simulation import SimulationResult, from_preview
from envelopelab.validation.meshes import sphere
from envelopelab.validation.preview_solver import _isotropic

COND = OperatingConditions(1.2, 1.2, self_weight=False)


def _blister(pressure: float = 200.0) -> tuple[AppendageModel, SimulationResult]:
    t = np.linspace(0.0, 2.0 * math.pi, 48, endpoint=False)
    spec = AppendageSpec(
        "blister",
        np.column_stack([np.cos(t), np.sin(t)]),
        skin_mode="spherical_cap",
        cap_height=1.0,
        mesh_size=0.2,
        skin_zone="s",
        pressure=PressureSpec(
            "independent", chamber=independent_chamber("blister", pressure, 0.0, 0.0)
        ),
        intended={"dome_height_m": 1.0},
    )
    am = build_appendage(spec, COND, {"s": _isotropic()})
    return am, from_preview(am.model, solve(am.model))


def _as_calculix(
    result: SimulationResult, converged: bool, target: float = 1e-5
) -> SimulationResult:
    manifest = replace(
        result.manifest, solver_settings={"residual_target": target, "balance_tolerance": 5e-3}
    )
    return replace(
        result,
        solver="calculix",
        status="converged" if converged else "not converged",
        converged=converged,
        manifest=manifest,
        findings=[],
    )


def test_verification_requires_a_converged_calculix_solve() -> None:
    _, preview = _blister()
    policy = VerificationPolicy()
    assert policy.check(None) == (False, "no CalculiX verification solve")
    ok, reason = policy.check(preview)
    assert not ok and "not the verification solver" in reason
    ok, reason = policy.check(_as_calculix(preview, converged=False))
    assert not ok and "not converged" in reason
    ok, reason = policy.check(_as_calculix(preview, converged=True, target=1e-3))
    assert not ok and "looser" in reason
    assert policy.check(_as_calculix(preview, converged=True))[0]


def test_preview_is_never_labelled_verified_and_unconverged_is_flagged(tmp_path: Path) -> None:
    am, preview = _blister()
    unconverged = replace(preview, converged=False, status="max_iterations")
    report = build_report(
        ReportInput(
            "blister",
            am.model,
            am.model.positions,
            preview=unconverged,
            verification=_as_calculix(preview, False),
        )
    )
    assert not report.verified
    labels = [s.label for s in report.states]
    assert labels[0].startswith("AS-SEWN")
    assert "NOT CONVERGED" in labels[1] and "VERIFIED -" not in labels[1]
    assert "NOT VERIFIED" in labels[2]
    assert report.status_line.startswith("NOT VERIFIED")
    assert any(f.severity == "error" for f in report.findings)
    out = report.write_all(tmp_path)
    page = out["html"].read_text()
    assert "NOT VERIFIED" in page and "PREVIEW - NOT CONVERGED" in page
    data = json.loads(out["json"].read_text())
    assert data["verified"] is False
    assert all(not s["verified"] for s in data["states"])
    with out["states.csv"].open() as fh:
        first = next(csv.reader(fh))
    assert first[0].startswith("# NOT VERIFIED")
    pdf = out["pdf"].read_bytes()
    assert pdf.startswith(b"%PDF-1.4") and pdf.rstrip().endswith(b"%%EOF")


def test_converged_calculix_makes_the_report_verified(tmp_path: Path) -> None:
    am, preview = _blister()
    verification = _as_calculix(preview, converged=True)
    section = FeatureSection(
        "blister",
        "blister",
        preview=appendage_metrics(am, preview),
        verification=appendage_metrics(am, verification),
    )
    ref = sphere(1.0, 12)
    reference = ReferenceMesh(ref.positions, ref.triangles, "unit sphere")
    report = build_report(
        ReportInput(
            "blister",
            am.model,
            am.model.positions,
            preview=preview,
            verification=verification,
            reference=reference,
            features=[section],
        )
    )
    assert report.verified
    assert report.states[2].label.startswith("VERIFIED")
    assert report.states[1].label.startswith("PREDICTED - PREVIEW")
    assert section.verification is not None and section.verification.verified
    assert section.preview is not None and not section.preview.verified
    # The hemisphere lies on the unit sphere: deviations are facet-sized.
    assert report.deviation_stats["preview"].p95_abs < 0.03
    assert any(d["quantity"] == "blister: projected height" for d in report.dimensions)
    assert report.to_dict()["scope"].startswith("Appendage external aerodynamics")


def test_sensitivity_sweep_runs_every_case() -> None:
    base = SweepSettings(internal_temperature=373.15, loss_factor=0.1)
    cases = sweep_cases(base)
    assert len(cases) == 10
    assert {c[0] for c in cases} == {
        "internal_temperature",
        "stiffness_factor",
        "weight_factor",
        "seam_length_error",
        "loss_factor",
    }

    def factory(s: SweepSettings):  # type: ignore[no-untyped-def]
        am, _ = _blister(200.0 * s.stiffness_factor)
        return am.model, lambda r: {"projected_height_m": appendage_metrics(am, r).projected_height}

    result = sensitivity_sweep(factory, base, parameters=("stiffness_factor",))
    assert result.solver == "envelopelab-preview"
    assert len(result.rows) == 3
    rows = [r for r in result.sensitivities() if r["parameter"] == "stiffness_factor"]
    assert rows and rows[0]["converged"] and rows[0]["slope"] > 0.0


def test_pdf_canvas_writes_a_valid_file(tmp_path: Path) -> None:
    pdf = PdfCanvas()
    pdf.text(40, 500, "Hello (world)", 12, bold=True)
    pdf.polygon([(40, 40), (100, 40), (70, 90)], fill=(0.2, 0.4, 0.8))
    pdf.new_page()
    pdf.line(0, 0, 100, 100)
    data = pdf.save(tmp_path / "t.pdf").read_bytes()
    assert data.count(b"/Type /Page ") == 2
    xref = int(data.rsplit(b"startxref", 1)[1].split()[0])
    assert data[xref : xref + 4] == b"xref"
    pytest.importorskip("zlib")
