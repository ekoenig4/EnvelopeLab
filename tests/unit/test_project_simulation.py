"""From a design document to a solver model, through the pattern-import pipeline."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from envelopelab.materials import FabricLibraryRepository
from envelopelab.project import edits
from envelopelab.project.gore_design import editable_outline, panel_rows
from envelopelab.project.session import ProjectSession
from envelopelab.project.simulation import (
    BuildError,
    build_solver_model,
    membrane_for_fabric,
    run_record,
    solve_preview,
    write_build_pack,
)
from envelopelab.project.templates import special_design_from_mesh

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
FIXTURE = FIXTURES / "standard_gore" / "design.elproj"
COARSE_MM = 1600.0


def test_build_pack_carries_rows_zones_grain_and_allowance(tmp_path: Path) -> None:
    s = ProjectSession.open(FIXTURE)
    s.set_row_pattern("B", {"grain_angle_deg": 90.0})
    config = write_build_pack(s.design, s.patterns, tmp_path)
    data = yaml.safe_load(config.read_text(encoding="utf-8"))
    ring = data["assembly"]["rings"][0]
    assert ring["gore_count"] == 8 and ring["rows"] == ["A", "B", "C", "D"]
    assert data["import"]["pieces"]["B"]["grain"] == pytest.approx([0.0, 1.0])
    assert data["import"]["pieces"]["A"]["material_zone"] == "body"
    assert data["import"]["seam_allowance_mm"] == pytest.approx(25.0)
    assert (tmp_path / "design.dxf").is_file()


def test_solver_model_from_the_fixture_design(tmp_path: Path) -> None:
    repo = FabricLibraryRepository()
    repo.seed_example_data()
    s = ProjectSession.open(FIXTURE)
    built = build_solver_model(s.design, s.patterns, tmp_path, COARSE_MM, repo)
    assert built.build.status == "PASS"
    assert built.model.source_hash == s.content_hash() == built.design_hash
    assert built.model.zone_names == ["body"]
    material = built.model.materials["body"]
    assert material.areal_mass.value == pytest.approx(0.042)
    assert material.areal_mass.source == "assumed"  # library tag "assumed - verify"
    assert built.material_sources == ["assumed"]
    names = {c.name.split(":")[1] for c in built.model.cables}
    assert names  # vertical, horizontal, mouth and crown tapes become cables
    assert built.model.conditions.internal_temperature == pytest.approx(373.15)


def test_manual_override_reaches_the_seam_audit(tmp_path: Path) -> None:
    s = ProjectSession.open(FIXTURE)
    row = panel_rows(s.design, s.patterns)[1]
    points = editable_outline(row)
    points[4] = (points[4][0] + 0.08, points[4][1])
    edits.set_manual_outline(s, row.label, points)
    built = build_solver_model(s.design, s.patterns, tmp_path, COARSE_MM)
    assert any(f.code == "seam_audit" or "differ" in f.message for f in built.findings)


def test_special_shapes_are_not_simulated_without_panels(tmp_path: Path) -> None:
    mesh = FIXTURES / "alien" / "reference" / "alien-reference.ply"
    if not mesh.is_file():
        candidates = sorted((FIXTURES / "alien" / "reference").glob("*.*"))
        mesh = next(p for p in candidates if p.suffix.lower() in (".ply", ".stl", ".obj"))
    design = special_design_from_mesh("alien", mesh)
    with pytest.raises(BuildError, match="needs panels"):
        build_solver_model(design, ProjectSession.new(design).patterns, tmp_path)


def test_unknown_fabric_is_fully_assumed() -> None:
    material = membrane_for_fabric("unobtainium", None)
    assert {v["source"] for v in material.sources().values()} == {"assumed"}


@pytest.mark.slow
def test_preview_run_record(tmp_path: Path) -> None:
    s = ProjectSession.open(FIXTURE)
    built = build_solver_model(s.design, s.patterns, tmp_path, 1600.0)
    result = solve_preview(built)
    record, arrays = run_record(result, built, s.fingerprints()["simulation"])
    assert record.solver == "envelopelab-preview" and record.solver_label.startswith("Preview")
    assert record.converged and record.residual < 1e-6
    assert record.n_nodes == built.model.n_nodes and arrays["positions"].shape[0] == record.n_nodes
    assert record.design_content_hash == s.content_hash()
    assert 140.0 < record.volume < 175.0  # the design's profile holds 160.7 m^3
    assert s.run_status(record) == "current"


def test_calculix_final_residual_is_the_last_out_of_balance() -> None:
    """The last Newton iteration of a CalculiX job can report 0; the run's residual is the
    relative out-of-balance of the last pass (what decides convergence)."""
    from types import SimpleNamespace

    from envelopelab.project.simulation import final_residual
    from envelopelab.solvers.simulation import IterationRecord

    history = [
        IterationRecord("pass: start out-of-balance (exact law)", 1, 0, 0, 0.5),
        IterationRecord("inflation 1/4", 2, 1, 3, 0.0),
        IterationRecord("pass: largest node movement (m)", 1, 0, 0, 0.002),
        IterationRecord("pass: relative out-of-balance", 1, 0, 0, 7.2e-2),
        IterationRecord("pass 2: release 1/1", 2, 1, 2, 0.0),
    ]
    result = SimpleNamespace(
        solver="calculix", residual_history=[(1, 0.3), (2, 0.0)], iteration_history=history
    )
    value, measure = final_residual(result)  # type: ignore[arg-type]
    assert value == 7.2e-2 and "out-of-balance" in measure
    preview = SimpleNamespace(
        solver="envelopelab-preview",
        residual_history=[(200, 1e-3), (400, 9e-7)],
        iteration_history=[],
        residual_measure="relative out-of-balance force ||P R|| / ||F_ext||",
    )
    assert final_residual(preview) == (9e-7, preview.residual_measure)  # type: ignore[arg-type]
