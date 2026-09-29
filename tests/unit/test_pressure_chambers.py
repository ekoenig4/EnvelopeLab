"""Pressure chambers in the solver model and pressure communication of appendages."""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from envelopelab.atmosphere import celsius_to_kelvin
from envelopelab.features.pressure import (
    DEFAULT_LOSS_FACTOR,
    FeedHole,
    fed_chamber,
    independent_chamber,
)
from envelopelab.solvers.dynamic_relaxation import ModelEvaluator, enclosed_volume, solve
from envelopelab.solvers.model import (
    AMBIENT,
    MAIN_CHAMBER,
    ModelError,
    OperatingConditions,
    PressureChamber,
    SolverModel,
)
from envelopelab.validation.meshes import sphere
from envelopelab.validation.preview_solver import _isotropic

HOT = OperatingConditions.hot_air(celsius_to_kelvin(100.0), mouth_height=0.0)


def test_fed_chamber_samples_envelope_pressure_at_the_holes() -> None:
    holes = [FeedHole("a", 10.0, 0.2), FeedHole("b", 12.0, 0.1)]
    feed = fed_chamber("pod", HOT, holes, loss_factor=0.25)
    g = HOT.pressure_gradient
    mean = (0.2 * g * 10.0 + 0.1 * g * 12.0) / 0.3
    assert feed.mean_envelope_pressure == pytest.approx(mean)
    assert feed.reference_height == pytest.approx((0.2 * 10 + 0.1 * 12) / 0.3)
    assert feed.chamber.reference_pressure == pytest.approx(0.75 * mean)
    assert feed.chamber.gradient == pytest.approx(g)
    assert feed.chamber.source == "assumed"
    # Hand check: the chamber pressure 1 m above the holes rises by the gradient.
    z = feed.reference_height + 1.0
    assert float(feed.chamber.pressure(z)) == pytest.approx(0.75 * mean + g)
    assert feed.as_dict()["loss_factor_source"] == "assumed"


def test_fed_chamber_rejects_bad_inputs() -> None:
    with pytest.raises(ValueError):
        fed_chamber("pod", HOT, [])
    with pytest.raises(ValueError):
        fed_chamber("pod", HOT, [FeedHole("a", 5.0, 0.1)], loss_factor=1.0)
    with pytest.raises(ValueError):
        fed_chamber("pod", HOT, [FeedHole("a", -1.0, 0.1)])
    assert 0.0 <= DEFAULT_LOSS_FACTOR < 1.0


def test_independent_chamber_is_uniform_without_gradient() -> None:
    ch = independent_chamber("b", 150.0, 3.0, 0.0)
    assert np.allclose(ch.pressure(np.array([0.0, 3.0, 9.0])), 150.0)


def _closed_sphere(chambers: bool) -> SolverModel:
    mesh = sphere(1.0, 8)
    m = len(mesh.triangles)
    kwargs: dict[str, Any] = {}
    if chambers:
        kwargs = {
            "chambers": [PressureChamber("c", 100.0, 0.0, 0.0)],
            "tri_chambers": np.tile([0, AMBIENT], (m, 1)),
        }
    cond = OperatingConditions(1.2, 1.2, uniform_pressure=100.0, self_weight=False)
    from envelopelab.solvers.model import NodeConstraint

    return SolverModel.uniform(
        mesh.positions,
        mesh.triangles,
        mesh.rest_uv,
        _isotropic(),
        cond,
        constraints=[NodeConstraint("pin", np.array([0, 1, 2]))],
        **kwargs,
    )


def test_chamber_pressure_matches_the_main_gas_definition() -> None:
    main, chamber = _closed_sphere(False), _closed_sphere(True)
    z = main.positions[main.triangles][:, :, 2]
    assert np.allclose(main.triangle_pressure(z), chamber.triangle_pressure(z))
    ev = ModelEvaluator(chamber)
    vols = ev.chamber_volumes(chamber.positions)
    assert set(vols) == {"c"}
    assert vols["c"] == pytest.approx(ModelEvaluator(main).volume(main.positions), rel=1e-12)
    assert enclosed_volume(main.positions, main.triangles) == pytest.approx(vols["c"], rel=1e-12)


def test_shared_wall_carries_the_pressure_difference() -> None:
    model = _closed_sphere(False)
    m = model.n_triangles
    codes = np.tile([MAIN_CHAMBER, AMBIENT], (m, 1))
    codes[: m // 2] = (MAIN_CHAMBER, 0)
    model.chambers = [PressureChamber("pod", 30.0, 0.0, 0.0)]
    model.tri_chambers = codes
    model.validate()
    z = np.zeros((m, 3))
    p = model.triangle_pressure(z)
    assert np.allclose(p[: m // 2], 100.0 - 30.0)
    assert np.allclose(p[m // 2 :], 100.0)
    # A diaphragm with the same gas on both sides carries nothing.
    model.tri_chambers = np.tile([0, 0], (m, 1))
    assert np.allclose(model.triangle_pressure(z), 0.0)


def test_invalid_chamber_codes_are_rejected() -> None:
    model = _closed_sphere(False)
    model.tri_chambers = np.tile([3, AMBIENT], (model.n_triangles, 1))
    with pytest.raises(ModelError):
        model.validate()


def test_models_without_chambers_solve_identically() -> None:
    """The chamber code path is only taken when chambers are given (bit-identical)."""
    a, b = _closed_sphere(False), _closed_sphere(True)
    ra, rb = solve(a), solve(b)
    assert ra.converged and rb.converged
    assert np.allclose(ra.positions, rb.positions, atol=1e-12)
    assert ra.chamber_volumes == {}
    assert rb.chamber_volumes["c"] == pytest.approx(ra.volume, rel=1e-12)
    assert a.content_hash() != b.content_hash()
