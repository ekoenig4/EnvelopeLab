"""Special-shape sub-models can be built and solved in parallel threads.

Gmsh keeps one global model; ``envelopelab.assembly.mesh.GMSH_LOCK`` serialises every use
of it, and the compiled preview solver keeps no global state, so threads give the same
models and results as one thread.
"""

from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from envelopelab.atmosphere import celsius_to_kelvin
from envelopelab.features.builder import build_appendage
from envelopelab.features.primitives import Dome, Placement, design_primitive, primitive_appendage
from envelopelab.solvers.dynamic_relaxation import solve
from envelopelab.solvers.model import OperatingConditions, SolverSettings
from envelopelab.validation.preview_solver import GENERIC_FABRIC, GENERIC_TAPE
from envelopelab.validation.primitives import SPHERE_RADIUS, sphere_envelope

SPHERE = sphere_envelope()
HOT = OperatingConditions.hot_air(
    celsius_to_kelvin(100.0), mouth_height=float(SPHERE.profile.z[0]), self_weight=False
)


def _build_and_solve(gore: int) -> tuple[np.ndarray, np.ndarray, str]:
    design = design_primitive(
        Dome(f"pod{gore}", Placement(gore, 0.35 * math.pi * SPHERE_RADIUS), 0.6, 0.4, gores=6),
        SPHERE,
        feed_hole_radius=0.15,
    )
    am = build_appendage(
        primitive_appendage(design, 0.3, load_tape=GENERIC_TAPE),
        HOT,
        {"host": GENERIC_FABRIC, "skin": GENERIC_FABRIC},
    )
    result = solve(am.model, SolverSettings(max_iterations=3000))
    return am.model.positions, result.positions, result.convergence.status


def test_threads_build_and_solve_the_same_shapes_as_one_thread() -> None:
    gores = [1, 2, 3, 4]
    sequential = [_build_and_solve(g) for g in gores]
    with ThreadPoolExecutor(max_workers=4) as pool:
        parallel = list(pool.map(_build_and_solve, gores))
    for (x0, x, status), (y0, y, status_p) in zip(sequential, parallel, strict=True):
        assert np.array_equal(x0, y0)  # same sub-model mesh
        assert np.array_equal(x, y) and status == status_p  # same solve, bit for bit
