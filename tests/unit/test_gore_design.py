"""Gore-editor helpers: live outputs vs hand calculations, constraint locks, wizard."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from envelopelab.atmosphere import G0, gas_density
from envelopelab.materials import FabricLibraryRepository
from envelopelab.project import edits
from envelopelab.project.gore_design import (
    LockError,
    apply_locks,
    control_arrays,
    design_findings,
    editable_outline,
    fit_row_heights,
    gore_outputs,
    outline_edges,
    panel_rows,
    profile_from_arrays,
    standard_gore_design,
    wizard_control_points,
)
from envelopelab.project.model import ConstraintLocks, PatternSet
from envelopelab.project.session import ProjectSession
from envelopelab.project.templates import design_from_measurements, new_design

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "standard_gore" / "design.elproj"


def frustum_design(r0: float = 1.0, r1: float = 2.0, h: float = 3.0):  # type: ignore[no-untyped-def]
    """Two control points: the profile is exactly a conical frustum."""
    slant = math.hypot(r1 - r0, h)
    return new_design(
        "frustum",
        [(r0, 0.0), (r1, h)],
        gore_count=12,
        row_heights=fit_row_heights([1.0, 1.0], slant),
        mouth_diameter=2 * r0,
        top_diameter=2 * r1,
    )


def test_outputs_match_the_frustum_hand_calculation() -> None:
    r0, r1, h = 1.0, 2.0, 3.0
    design = frustum_design(r0, r1, h)
    out = gore_outputs(design, PatternSet())
    slant = math.hypot(r1 - r0, h)
    volume = math.pi * h / 3 * (r0 * r0 + r0 * r1 + r1 * r1)
    assert out.volume == pytest.approx(volume, rel=1e-9)
    assert out.area == pytest.approx(math.pi * (r0 + r1) * slant, rel=1e-9)
    assert out.height == pytest.approx(h) and out.max_diameter == pytest.approx(2 * r1)
    op = design.operating
    rho_a = gas_density(op.ambient_pressure, op.ambient_temperature)
    rho_i = gas_density(op.ambient_pressure, op.internal_temperature)
    # Hand calculation (docs/theory/atmosphere.md densities at 15 and 100 degC):
    # V = 7 pi = 21.991 m^3; L = 21.991 x (1.2250 - 0.9460) x 9.80665 = 60.17 N.
    assert out.gross_lift == pytest.approx(volume * (rho_a - rho_i) * G0.value, rel=1e-12)
    assert out.gross_lift == pytest.approx(60.17, abs=0.01)


def test_mass_estimate_uses_library_areal_mass_with_sources() -> None:
    repo = FabricLibraryRepository()
    repo.seed_example_data()
    design = frustum_design()
    out = gore_outputs(design, PatternSet(), repo)
    assert out.mass is not None and out.envelope_mass is not None
    zone = out.mass.zones["body"]
    assert zone.areal_mass.value == pytest.approx(0.042)  # 42 g/m^2 ripstop (library)
    assert zone.finished_area == pytest.approx(out.area, rel=0.02)  # flat gores vs revolution
    assert "assumed - verify" in out.sources and "assumed" in out.sources
    assert out.lift_margin == pytest.approx(
        out.gross_lift / G0.value - out.envelope_mass - design.operating.payload_mass
    )


def test_invalid_rows_report_instead_of_hiding() -> None:
    design = frustum_design()
    assert design.gores is not None
    design.gores.panel_rows[0].finished_height += 0.1
    out = gore_outputs(design, PatternSet())
    assert out.mass is None and any(f.code == "rows" for f in out.findings)
    assert any(
        f.code == "rows" and f.severity == "error" for f in design_findings(design, PatternSet())
    )
    with pytest.raises(ValueError, match="cover"):
        panel_rows(design, PatternSet())


def test_cold_envelope_is_an_error() -> None:
    design = frustum_design()
    design.operating.internal_temperature = design.operating.ambient_temperature
    out = gore_outputs(design, PatternSet())
    assert any(f.code == "no_lift" and f.severity == "error" for f in out.findings)


def test_fit_row_heights_covers_exactly() -> None:
    heights = fit_row_heights([2.0, 2.0, 3.0], 9.7691)
    assert sum(heights) == pytest.approx(9.7691, abs=1e-12)
    assert heights[0] == pytest.approx(9.7691 * 2 / 7, abs=1e-4)


@pytest.mark.parametrize(
    "locks",
    [
        {"height": True},
        {"max_diameter": True},
        {"volume": True},
        {"volume": True, "height": True},
        {"volume": True, "max_diameter": True},
        {"volume": True, "height": True, "max_diameter": True},
    ],
)
def test_locks_hold_after_an_edit(locks: dict[str, bool]) -> None:
    s = ProjectSession.open(FIXTURE)
    before = profile_from_arrays(*control_arrays(s.design))
    for name in locks:
        edits.set_lock(s, name, True)
    pts = s.design.gores.meridian_profile_control_points  # type: ignore[union-attr]
    edits.move_control_point(s, 2, pts[2].x + 0.4, pts[2].y + 0.3)
    after = profile_from_arrays(*control_arrays(s.design))
    if "height" in locks:
        assert after.height == pytest.approx(before.height, abs=1e-3)
    if "max_diameter" in locks:
        assert after.max_width == pytest.approx(before.max_width, abs=1e-3)
    if "volume" in locks:
        assert after.volume == pytest.approx(before.volume, rel=1e-3)
    # Rows stay fitted to the changed meridian in the same command.
    assert s.design.gores is not None
    total = sum(r.finished_height for r in s.design.gores.panel_rows)
    assert total == pytest.approx(after.meridian_length, abs=1e-3)
    s.undo()
    assert profile_from_arrays(*control_arrays(s.design)).volume == pytest.approx(before.volume)


def test_gore_count_lock_refuses_changes() -> None:
    s = ProjectSession.open(FIXTURE)
    edits.set_lock(s, "gore_count", True)
    with pytest.raises(LockError):
        edits.set_gore_count(s, 10)
    edits.set_lock(s, "gore_count", False)
    assert edits.set_gore_count(s, 10)


def test_collapsed_profile_cannot_hold_a_volume_lock() -> None:
    r = np.array([1.0, 1.0])
    z = np.array([0.0, 1.0])
    with pytest.raises(LockError):
        apply_locks(r * 0.0, z, ConstraintLocks(volume=10.0, max_diameter=2.0, height=1.0))


def test_wizard_meets_volume_height_and_width() -> None:
    design = standard_gore_design("w", 2200.0, 17.0, 16.0, 12, 5)
    out = gore_outputs(design, PatternSet())
    assert out.volume == pytest.approx(2200.0, rel=1e-3)
    assert out.height == pytest.approx(17.0, abs=1e-3)
    assert out.max_diameter == pytest.approx(16.0, abs=1e-3)
    assert design.gores is not None and design.gores.count == 12
    assert len(panel_rows(design, PatternSet())) == 5
    assert not [f for f in design_findings(design, PatternSet()) if f.severity == "error"]


def test_wizard_reports_the_achievable_range() -> None:
    with pytest.raises(ValueError, match="outside that range"):
        wizard_control_points(50.0, 17.0, 16.0, 4.8, 4.0)


def test_editable_outline_has_the_generated_edge_lengths() -> None:
    s = ProjectSession.open(FIXTURE)
    row = panel_rows(s.design, s.patterns)[1]
    e = outline_edges(editable_outline(row, 33))
    assert e["right"] == pytest.approx(row.side_length, abs=1e-3)
    assert e["left"] == pytest.approx(row.side_length, abs=1e-3)
    assert e["top"] == pytest.approx(row.top_width, abs=1e-9)
    assert e["bottom"] == pytest.approx(row.bottom_width, abs=1e-9)
    with pytest.raises(ValueError):
        outline_edges([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)])


def test_design_from_measurements_is_a_documented_stub() -> None:
    with pytest.raises(NotImplementedError, match="not implemented"):
        design_from_measurements()
