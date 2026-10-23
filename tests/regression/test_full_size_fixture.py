"""The full-size gore fixture: a 2600 m^3, 20-gore envelope that solves."""

from __future__ import annotations

import math
import tempfile
from pathlib import Path

import numpy as np
import pytest

from envelopelab.geometry.gore import lofted_volume
from envelopelab.project.gore_design import design_profile, design_width_model
from envelopelab.project.session import ProjectSession
from envelopelab.project.simulation import build_solver_model, solve_preview

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "full_size_gore" / "design.elproj"


def test_the_fixture_is_a_full_size_twenty_gore_envelope() -> None:
    design = ProjectSession.open(FIXTURE).design
    assert design.gores is not None
    profile = design_profile(design)
    assert design.gores.count == 20
    assert len(design.gores.panel_rows) == 12
    assert lofted_volume(profile, design_width_model(design)) == pytest.approx(2600.0, rel=1e-3)
    # Shape-family values of the held design (regression, 1 mm).
    assert float(profile.z.max() - profile.z.min()) == pytest.approx(15.140, abs=1e-3)
    assert 2.0 * float(profile.r.max()) == pytest.approx(17.991, abs=1e-3)
    assert profile.meridian_length == pytest.approx(20.907, abs=1e-3)
    assert design.operating.internal_temperature == pytest.approx(373.15)
    assert design.operating.payload_mass == pytest.approx(400.0)


@pytest.mark.slow
def test_the_preview_solve_converges_and_balances_the_lift() -> None:
    session = ProjectSession.open(FIXTURE)
    with tempfile.TemporaryDirectory() as tmp:
        built = build_solver_model(session.design, session.patterns, Path(tmp) / "p", 1600.0)
        result = solve_preview(built)
    assert result.converged, result.status
    lift = result.volume * built.model.conditions.pressure_gradient
    # Hot air at 100 degC in 2.5-2.6 thousand m^3: about 7 kN of lift (hand check below).
    rho_ratio = 1.0 - 288.15 / 373.15
    assert lift == pytest.approx(result.volume * 1.225 * rho_ratio * 9.80665, rel=0.01)
    vertical = [t for name, t in result.tape_tensions.items() if name.startswith("body:v:")]
    assert len(vertical) == 20 * 12
    assert all(float(np.max(t)) > 0.0 for t in vertical)
    assert math.isfinite(result.volume) and result.volume > 2400.0
