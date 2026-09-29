"""CalculiX adapter progress reports and cancellation (the GUI's progress monitor).

Skipped without ccx. Reporting progress must not change results: a solve with a progress
callback is compared bit for bit with one without.
"""

from __future__ import annotations

import numpy as np
import pytest

from calculix_adapter import (
    CalculixCancelledError,
    CalculixInstallation,
    CalculixProgress,
    CalculixSettings,
    run_calculix,
)
from envelopelab.materials.membrane import MembraneMaterial
from envelopelab.solvers.dynamic_relaxation import CancellationToken
from envelopelab.solvers.model import OperatingConditions, SolverModel, SymmetryPlane
from envelopelab.validation.meshes import sphere


def octant_model(divisions: int = 4) -> SolverModel:
    mesh = sphere(2.0, divisions, octant=True)
    planes = [
        SymmetryPlane(name, mesh.node_sets[name], (float(k == 0), float(k == 1), float(k == 2)))
        for k, name in enumerate(("x0", "y0", "z0"))
    ]
    return SolverModel.uniform(
        mesh.positions,
        mesh.triangles,
        mesh.rest_uv,
        MembraneMaterial.isotropic("isotropic test", 1.0e5, 0.3),
        OperatingConditions(1.2, 1.2, uniform_pressure=1000.0, self_weight=False),
        symmetry=planes,
        name="octant sphere",
    )


def test_progress_reports_every_job_without_changing_results(ccx: CalculixInstallation) -> None:
    model = octant_model()
    reports: list[CalculixProgress] = []
    with_progress = run_calculix(model, CalculixSettings(), progress=reports.append)
    plain = run_calculix(model, CalculixSettings())
    assert reports[0].job == "held" and reports[0].pass_no == 1
    assert reports[-1].job == "done" and reports[-1].fraction == 1.0
    assert {r.job for r in reports} == {"held", "release", "done"}
    assert all(0.0 <= r.fraction <= 1.0 for r in reports)
    np.testing.assert_array_equal(with_progress.positions, plain.positions)
    assert with_progress.converged == plain.converged


def test_cancel_stops_ccx(ccx: CalculixInstallation) -> None:
    token = CancellationToken()
    seen: list[str] = []

    def cancel_on_first(report: CalculixProgress) -> None:
        seen.append(report.job)
        token.cancel()

    with pytest.raises(CalculixCancelledError):
        run_calculix(octant_model(), CalculixSettings(), progress=cancel_on_first, cancel=token)
    assert seen == ["held"]
