"""Generic hemispherical blister: protrusion trends and the apex resultant, both solvers."""

from __future__ import annotations

import pytest

from calculix_adapter import CalculixInstallation, run_calculix
from envelopelab.features.metrics import appendage_metrics
from envelopelab.solvers.dynamic_relaxation import solve
from envelopelab.solvers.model import SolverModel
from envelopelab.solvers.simulation import SimulationResult, from_preview
from envelopelab.validation.special_shapes import (
    blister_checks,
    blister_model,
    blister_rows,
)


def test_preview_blister_trends_and_apex_resultant() -> None:
    rows = blister_rows()
    checks = blister_checks(rows)
    assert checks and all(ok for _, ok, _ in checks), [c for c in checks if not c[1]]


def test_blister_metrics_are_identical_in_format_for_both_solvers(
    ccx: CalculixInstallation,
) -> None:
    am = blister_model(200.0, 1.0e5)
    preview = from_preview(am.model, solve(am.model))
    verified = run_calculix(am.model, start_positions=preview.positions)
    mp, mv = appendage_metrics(am, preview), appendage_metrics(am, verified)
    assert mp.as_dict().keys() == mv.as_dict().keys()
    assert not mp.verified and mv.verified
    assert mv.projected_height == pytest.approx(mp.projected_height, rel=0.05)


def test_calculix_blister_trends(ccx: CalculixInstallation) -> None:
    """Larger protrusion with pressure, smaller with stiffness, verified by CalculiX."""

    def verify(model: SolverModel, start) -> SimulationResult:  # type: ignore[no-untyped-def]
        return run_calculix(model, start_positions=start)

    rows = blister_rows(verify)
    checks = blister_checks(rows)
    names = [c for c, _, _ in checks]
    assert any(n.startswith("calculix: protrusion rises with pressure") for n in names)
    assert any(n.startswith("calculix: protrusion falls with stiffness") for n in names)
    assert all(ok for _, ok, _ in checks), [c for c in checks if not c[1]]
