r"""Analytic, equilibrium and convergence benchmarks of the preview (dynamic-relaxation) solver.

The same functions back ``tests/benchmarks/test_preview_solver.py`` and the generated page
``docs/validation/preview-solver-benchmarks.md`` (``scripts/generate_validation_docs.py``),
so the published table is always the one the test suite checks (AGENTS.md §6.4).

Hand calculations
-----------------
* Hydrostatic pressure, 15 degC ambient / 100 degC internal at sea level: gradient
  2.736 Pa/m (``envelopelab.atmosphere`` module docstring), so 10 m above the mouth
  :math:`\Delta p = 2.736 \times 10 = 27.36` Pa and below the mouth 0 Pa.
* Lift of a sphere of radius 8 m under the same conditions:
  :math:`V = \tfrac43 \pi 8^3 = 2144.66\ \mathrm{m^3}`,
  :math:`L = 2144.66 \times 0.2790 \times 9.80665 = 5868\ \mathrm{N}`.
  For an open envelope with :math:`\Delta p = 0` at the mouth the pressure resultant
  equals the lift (divergence theorem), which the solver's load assembly must reproduce.

Closed forms
------------
* Sphere, radius :math:`r`, uniform pressure :math:`p`: :math:`N = p r / 2` in every
  direction. With the St. Venant-Kirchhoff law the stretch :math:`\lambda = r/R_0` solves
  :math:`\frac{Et}{1-\nu}\frac{\lambda^2-1}{2} = \frac{p\lambda R_0}{2}`.
* Closed cylinder: hoop :math:`N_\theta = p r`, axial :math:`N_z = p r / 2`.
* Elastic catenary [Irvine]_, span :math:`l`, unstretched length :math:`L_0`, weight
  :math:`W = w L_0`, supports level: horizontal tension :math:`H` solves
  :math:`l = H L_0 / EA + (2H/w)\,\mathrm{asinh}(W/2H)`; midspan sag
  :math:`h = W L_0/(8 EA) + (H L_0/W)(\sqrt{1 + (W/2H)^2} - 1)`.
* Tension field in simple shear [Mansfield]_: a sheet sheared by :math:`\gamma` with no
  pre-tension wrinkles everywhere at 45 deg and carries uniaxial tension
  :math:`N_1 = Et\gamma/2`, so the shear resultant is :math:`N_{xy} = Et\gamma/4`
  (independent of :math:`\nu`; the compression-carrying membrane gives
  :math:`G t \gamma`).

References
----------
.. [Irvine] H. M. Irvine, *Cable Structures*, MIT Press (1981), sec. 1.4 (elastic
   catenary).
.. [Mansfield] E. H. Mansfield, *The Bending and Stretching of Plates*, 2nd ed., Cambridge
   University Press (1989), ch. 10 (tension field theory); see also Y. W. Wong and
   S. Pellegrino, "Wrinkled membranes part II: analytical models", J. Mech. Mater. Struct.
   1 (2006) 27-61.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy.optimize import brentq

from envelopelab.atmosphere import celsius_to_kelvin, gas_density
from envelopelab.materials.membrane import MaterialValue, MembraneMaterial, TapeMaterial
from envelopelab.solvers.dynamic_relaxation import SolveResult, solve
from envelopelab.solvers.membrane import WRINKLED, FloatArray, IntArray
from envelopelab.solvers.model import (
    CableSet,
    NodeConstraint,
    OperatingConditions,
    PressureClosure,
    SolverModel,
    SolverSettings,
    SymmetryPlane,
    model_from_rest_model,
)
from envelopelab.solvers.results import force_balance
from envelopelab.validation.analytic_geometry import BenchmarkResult
from envelopelab.validation.meshes import cylinder, sheet, sphere

HAND_PRESSURE_10M = 27.36  # Pa, 2.736 Pa/m x 10 m (module docstring)
HAND_LIFT_SPHERE_8 = 5868.0  # N, module docstring
#: Target edge lengths (mm) of the envelope mesh-refinement study, coarse to fine.
REFINEMENT_LEVELS_MM = (2400.0, 1700.0, 1200.0, 850.0, 600.0)
SMOKE_LEVEL_MM = 1700.0


def _assumed(value: float, unit: str) -> MaterialValue:
    return MaterialValue(value, unit, "assumed", "generic benchmark value")


#: Generic coated-nylon fabric for the envelope benchmarks (assumed values).
GENERIC_FABRIC = MembraneMaterial(
    name="generic coated nylon (assumed)",
    stiffness_warp=_assumed(1.0e5, "N/m"),
    stiffness_weft=_assumed(0.8e5, "N/m"),
    shear_stiffness=_assumed(5.0e3, "N/m"),
    poisson_warp_weft=_assumed(0.3, "-"),
    areal_mass=_assumed(0.065, "kg/m^2"),
    strength_warp=_assumed(1.5e4, "N/m"),
    strength_weft=_assumed(1.4e4, "N/m"),
    seam_efficiency=_assumed(0.8, "-"),
    max_service_temperature=_assumed(celsius_to_kelvin(120.0), "K"),
)
#: Generic 25 mm polyester load tape (assumed values).
GENERIC_TAPE = TapeMaterial(
    name="generic 25 mm load tape (assumed)",
    axial_stiffness=_assumed(5.0e4, "N"),
    breaking_strength=_assumed(7.0e3, "N"),
    linear_mass=_assumed(0.02, "kg/m"),
)


@dataclass(frozen=True)
class RefinementLevel:
    """One mesh of the refinement study (lengths m, volume m^3)."""

    target_mm: float
    nodes: int
    triangles: int
    converged: bool
    max_displacement: float
    max_tape_displacement: float
    volume: float
    crown_rise: float


@dataclass
class PreviewBenchmarks:
    """All benchmark rows plus the refinement table."""

    results: list[BenchmarkResult]
    refinement: list[RefinementLevel] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """True when every row is within tolerance."""
        return all(r.passed for r in self.results)


def _isotropic(stiffness: float = 1.0e5, poisson: float = 0.3) -> MembraneMaterial:
    return MembraneMaterial.isotropic("isotropic benchmark", stiffness, poisson)


def _sphere_case(
    divisions: int, radius: float = 2.0, pressure: float = 1000.0, stiffness: float = 1.0e5
) -> tuple[SolverModel, SolveResult]:
    mesh = sphere(radius, divisions, octant=True)
    material = _isotropic(stiffness)
    planes = [
        SymmetryPlane(name, mesh.node_sets[name], tuple(np.eye(3)[k]))
        for k, name in enumerate(("x0", "y0", "z0"))
    ]
    model = SolverModel.uniform(
        mesh.positions,
        mesh.triangles,
        mesh.rest_uv,
        material,
        OperatingConditions(1.2, 1.2, uniform_pressure=pressure, self_weight=False),
        symmetry=planes,
        name=f"octant sphere, {divisions} divisions",
    )
    return model, solve(model)


def sphere_benchmarks(divisions: int = 24) -> list[BenchmarkResult]:
    """Pressurised spherical membrane (octant with three symmetry planes).

    Parameters
    ----------
    divisions : int
        Subdivisions of the octant edge.

    Returns
    -------
    list of BenchmarkResult
        Mean principal resultants vs :math:`p r / 2` (N/m), radius vs the SVK closed form
        (m), largest element deviation (relative) and symmetry-reaction balance (N).
    """
    radius, pressure, stiffness, nu = 2.0, 1000.0, 1.0e5, 0.3
    model, result = _sphere_case(divisions, radius, pressure, stiffness)
    r = float(np.linalg.norm(result.positions, axis=1).mean())
    area = _areas(result.positions, model.triangles)
    n1 = float(np.average(result.principal[:, 0], weights=area))
    n2 = float(np.average(result.principal[:, 1], weights=area))
    ref = pressure * r / 2.0
    k = stiffness / (1.0 - nu) / 2.0
    b = pressure * radius / 2.0
    stretch = (b + math.sqrt(b * b + 4.0 * k * k)) / (2.0 * k)
    deviation = float(np.max(np.abs(result.principal - ref))) / ref
    balance = force_balance(result)
    tag = f"Sphere R0=2 m, p=1 kPa, octant {divisions} div"
    return [
        BenchmarkResult(f"{tag}: mean N1 vs p r/2", n1, ref, "N/m", "relative", 0.02),
        BenchmarkResult(f"{tag}: mean N2 vs p r/2", n2, ref, "N/m", "relative", 0.02),
        BenchmarkResult(
            f"{tag}: largest element deviation from p r/2",
            deviation,
            0.0,
            "-",
            "absolute",
            0.05,
        ),
        BenchmarkResult(
            f"{tag}: mean radius vs SVK closed form",
            r,
            stretch * radius,
            "m",
            "absolute",
            1e-3,
        ),
        BenchmarkResult(
            f"{tag}: symmetry reactions vs pressure resultant",
            balance.imbalance,
            0.0,
            "-",
            "absolute",
            5e-3,
        ),
    ] + _converged_row(tag, result)


def _areas(x: FloatArray, tri: IntArray) -> FloatArray:
    e = x[tri]
    out: FloatArray = 0.5 * np.linalg.norm(np.cross(e[:, 1] - e[:, 0], e[:, 2] - e[:, 0]), axis=1)
    return out


def _converged_row(tag: str, result: SolveResult) -> list[BenchmarkResult]:
    return [
        BenchmarkResult(
            f"{tag}: relative residual",
            result.convergence.residual if result.converged else math.inf,
            0.0,
            "-",
            "absolute",
            result.convergence.tolerance,
        )
    ]


def cylinder_benchmarks(n_around: int = 48, n_along: int = 16) -> list[BenchmarkResult]:
    """Closed pressurised cylinder: half length with a z = 0 symmetry plane, capped top.

    Returns
    -------
    list of BenchmarkResult
        Mean hoop resultant vs :math:`p r` and axial vs :math:`p r/2` (N/m), with
        :math:`r` the mean node radius of the deformed mesh.
    """
    radius, half_length, pressure = 1.0, 1.0, 1000.0
    mesh = cylinder(radius, half_length, n_around, n_along)
    model = SolverModel.uniform(
        mesh.positions,
        mesh.triangles,
        mesh.rest_uv,
        _isotropic(),
        OperatingConditions(1.2, 1.2, uniform_pressure=pressure, self_weight=False),
        symmetry=[
            SymmetryPlane("z0", mesh.node_sets["bottom"], (0.0, 0.0, 1.0)),
            SymmetryPlane("x0", mesh.node_sets["x0"], (1.0, 0.0, 0.0)),
            SymmetryPlane("y0", mesh.node_sets["y0"], (0.0, 1.0, 0.0)),
        ],
        closures=[PressureClosure("end cap", mesh.node_sets["top"])],
        name="closed cylinder",
    )
    result = solve(model)
    x = result.positions
    r = float(np.hypot(x[:, 0], x[:, 1]).mean())
    centroid = x[model.triangles].mean(axis=1)
    hoop_dir = np.column_stack([-centroid[:, 1], centroid[:, 0], np.zeros(len(centroid))])
    hoop_dir /= np.linalg.norm(hoop_dir, axis=1)[:, None]
    axial = np.array([0.0, 0.0, 1.0])
    hoop = np.einsum("mi,mij,mj->m", hoop_dir, result.stress, hoop_dir)
    axial_n = np.einsum("i,mij,j->m", axial, result.stress, axial)
    area = _areas(x, model.triangles)
    tag = f"Cylinder R0=1 m, p=1 kPa, {n_around}x{n_along}"
    return [
        BenchmarkResult(
            f"{tag}: mean hoop N vs p r",
            float(np.average(hoop, weights=area)),
            pressure * r,
            "N/m",
            "relative",
            0.02,
        ),
        BenchmarkResult(
            f"{tag}: mean axial N vs p r/2",
            float(np.average(axial_n, weights=area)),
            pressure * r / 2.0,
            "N/m",
            "relative",
            0.02,
        ),
        BenchmarkResult(
            f"{tag}: equilibrium imbalance",
            force_balance(result).imbalance,
            0.0,
            "-",
            "absolute",
            5e-3,
        ),
    ] + _converged_row(tag, result)


def _irvine(span: float, length: float, weight: float, ea: float) -> tuple[float, float]:
    w = weight / length

    def gap(h: float) -> float:
        return h * length / ea + 2.0 * h / w * math.asinh(weight / (2.0 * h)) - span

    horizontal = float(brentq(gap, 1e-6 * weight, 1e6 * weight, xtol=1e-12, rtol=1e-14))
    sag = weight * length / (8.0 * ea) + horizontal * length / weight * (
        math.sqrt(1.0 + (weight / (2.0 * horizontal)) ** 2) - 1.0
    )
    return horizontal, sag


def catenary_benchmarks(elements: int = 80) -> list[BenchmarkResult]:
    """Elastic catenary: a cable under its own weight between level supports.

    The cable starts straight between the supports (slack, zero tension).

    Returns
    -------
    list of BenchmarkResult
        Midspan sag (m), horizontal tension (N) and support vertical reaction (N) vs
        the elastic-catenary closed form.
    """
    span, length, ea, mass = 10.0, 12.0, 1.0e5, 1.0
    cond = OperatingConditions(1.2, 1.2, self_weight=True)
    weight = mass * length * cond.gravity
    x = np.linspace(0.0, span, elements + 1)
    positions = np.column_stack([x, np.zeros_like(x), np.zeros_like(x)])
    # A small initial sag avoids starting exactly on the straight (singular) line.
    positions[:, 2] = -0.01 * np.sin(np.pi * x / span)
    edges = np.column_stack([np.arange(elements), np.arange(1, elements + 1)])
    tape = TapeMaterial(
        "benchmark cable",
        MaterialValue(ea, "N", "assumed"),
        MaterialValue(1e9, "N", "assumed"),
        MaterialValue(mass, "kg/m", "assumed"),
    )
    model = SolverModel(
        positions,
        np.zeros((0, 3), dtype=np.int64),
        np.zeros((0, 3, 2)),
        np.zeros((0, 2)),
        np.zeros(0, dtype=np.int64),
        [],
        {},
        cond,
        cables=[CableSet("cable", edges, tape, np.full(elements, length / elements))],
        constraints=[
            NodeConstraint("left support", np.array([0])),
            NodeConstraint("right support", np.array([elements])),
        ],
        name="elastic catenary",
    )
    result = solve(model)
    horizontal, sag = _irvine(span, length, weight, ea)
    mid = result.positions[elements // 2]
    reaction = result.loads.reactions["left support"]
    tag = f"Catenary l=10 m, L0=12 m, EA=100 kN, {elements} elements"
    return [
        BenchmarkResult(f"{tag}: midspan sag", -float(mid[2]), sag, "m", "relative", 1e-3),
        BenchmarkResult(
            f"{tag}: horizontal tension", -float(reaction[0]), horizontal, "N", "relative", 0.02
        ),
        BenchmarkResult(
            f"{tag}: support vertical reaction",
            float(reaction[2]),
            weight / 2.0,
            "N",
            "relative",
            0.02,
        ),
    ] + _converged_row(tag, result)


def wrinkling_benchmarks(cells: int = 12, shear: float = 2e-3) -> list[BenchmarkResult]:
    """Tension-field simple shear of a square sheet (all edges prescribed).

    Returns
    -------
    list of BenchmarkResult
        Wrinkled area fraction, residual compression ratio, shear resultant from stresses
        and from top-edge reactions (N/m) vs :math:`Et\\gamma/4`, and the
        compression-carrying control vs :math:`Gt\\gamma`.
    """
    size, stiffness, nu = 1.0, 1.0e5, 0.3
    mesh = sheet(size, size, cells, cells)
    x0 = mesh.positions
    boundary = mesh.node_sets["boundary"]
    top = mesh.node_sets["top"]
    others = np.setdiff1d(boundary, top)
    sheared = x0.copy()
    sheared[:, 0] += shear * x0[:, 1]
    rows: list[BenchmarkResult] = []
    tag = f"Simple shear {cells}x{cells}, gamma={shear:g}"
    for tension_field in (True, False):
        model = SolverModel.uniform(
            x0,
            mesh.triangles,
            mesh.rest_uv,
            _isotropic(stiffness, nu),
            OperatingConditions(1.2, 1.2, self_weight=False),
            constraints=[
                NodeConstraint("top edge", top, sheared[top]),
                NodeConstraint("other edges", others, sheared[others]),
            ],
            name="simple shear",
        )
        result = solve(model, SolverSettings(tension_field=tension_field))
        area = _areas(result.positions, model.triangles)
        n_xy = float(np.average(result.stress[:, 0, 1], weights=area))
        edge = float(result.loads.reactions["top edge"][0]) / size
        if tension_field:
            ref = stiffness * shear / 4.0
            wrinkled = float(area[result.state == WRINKLED].sum() / area.sum())
            ratio = float(np.max(np.maximum(-result.principal[:, 1], 0.0))) / float(
                np.max(result.principal[:, 0])
            )
            rows += [
                BenchmarkResult(
                    f"{tag}: wrinkled area fraction", wrinkled, 1.0, "-", "absolute", 1e-9
                ),
                BenchmarkResult(
                    f"{tag}: residual compression / tension",
                    ratio,
                    0.0,
                    "-",
                    "absolute",
                    1e-2,
                ),
                BenchmarkResult(
                    f"{tag}: mean N_xy vs E t gamma / 4", n_xy, ref, "N/m", "relative", 0.02
                ),
                BenchmarkResult(
                    f"{tag}: top-edge reaction vs E t gamma / 4",
                    edge,
                    ref,
                    "N/m",
                    "relative",
                    0.02,
                ),
            ] + _converged_row(tag, result)
        else:
            ref = stiffness / (2.0 * (1.0 + nu)) * shear
            rows.append(
                BenchmarkResult(
                    f"{tag}, no tension field (control): N_xy vs G t gamma",
                    n_xy,
                    ref,
                    "N/m",
                    "relative",
                    0.02,
                )
            )
    return rows


def hydrostatic_and_lift_benchmarks(divisions: int = 32) -> list[BenchmarkResult]:
    """Hydrostatic pressure law and lift from the solver's pressure load assembly.

    A rigid (all nodes fixed) closed sphere of radius 8 m with its mouth at the bottom pole
    is evaluated under 15 degC / 100 degC; the pressure resultant must equal the lift.

    Returns
    -------
    list of BenchmarkResult
        Pressure at 10 m and below the mouth (Pa), pressure resultant and reported lift
        vs the hand calculation (N), and their mutual consistency.
    """
    ambient = gas_density(101325.0, celsius_to_kelvin(15.0))
    internal = gas_density(101325.0, celsius_to_kelvin(100.0))
    cond = OperatingConditions(
        ambient, internal, mouth_height=-8.0, self_weight=False, label="15/100 degC"
    )
    mesh = sphere(8.0, divisions)
    model = SolverModel.uniform(
        mesh.positions,
        mesh.triangles,
        mesh.rest_uv,
        _isotropic(),
        cond,
        constraints=[NodeConstraint("rigid", np.arange(len(mesh.positions)))],
        name="rigid sphere",
    )
    result = solve(model)
    pressure_z = float(result.loads.pressure[2])
    return [
        BenchmarkResult(
            "Hydrostatic dp 10 m above mouth, 15/100 degC",
            float(cond.pressure(2.0)),
            HAND_PRESSURE_10M,
            "Pa",
            "relative",
            1e-2,
        ),
        BenchmarkResult(
            "Hydrostatic dp 1 m below mouth (open mouth: zero)",
            float(cond.pressure(-9.0)),
            0.0,
            "Pa",
            "absolute",
            1e-12,
        ),
        BenchmarkResult(
            f"Lift, sphere R=8 m ({divisions} div): pressure resultant vs hand calc",
            pressure_z,
            HAND_LIFT_SPHERE_8,
            "N",
            "relative",
            1e-2,
        ),
        BenchmarkResult(
            f"Lift, sphere R=8 m ({divisions} div): V (rho_a - rho_i) g vs hand calc",
            result.lift,
            HAND_LIFT_SPHERE_8,
            "N",
            "relative",
            1e-2,
        ),
        BenchmarkResult(
            f"Lift, sphere R=8 m ({divisions} div): pressure resultant vs V (rho_a - rho_i) g",
            pressure_z,
            result.lift,
            "N",
            "relative",
            5e-3,
        ),
    ]


def envelope_model(
    fixture: Path, target_mm: float, self_weight: bool = True, seam_symmetry: bool = False
) -> SolverModel:
    """Solver model of the generic spherical envelope fixture.

    Parameters
    ----------
    fixture : Path
        ``tests/fixtures/spherical_envelope/build-pack.yaml``.
    target_mm : float
        Uniform target edge length (seams and interior), mm.
    self_weight : bool
        Include fabric and tape weight.
    seam_symmetry : bool
        Keep the seam meridians that lie in the planes x = 0 and y = 0 on those planes
        (symmetry of the 12-gore standard envelope; suppresses the near-mechanism twist
        of wrinkled fabric).

    Returns
    -------
    SolverModel
        Mouth fixed, crown closed by an unmeshed parachute, generic fabric and tapes,
        100 degC internal in ISA sea level.
    """
    from envelopelab.assembly.pipeline import import_build_pack
    from envelopelab.assembly.spec import MeshOptions

    options = MeshOptions(
        target_edge_length_mm=target_mm,
        seam_edge_length_mm=target_mm,
        corner_edge_length_mm=0.5 * target_mm,
    )
    built = import_build_pack(fixture, mesh_options=options)
    if built.rest_model is None:
        raise RuntimeError(f"{fixture}: no rest model")
    z_mouth = float(built.rest_model.positions[:, 2].min())
    cond = OperatingConditions.hot_air(
        celsius_to_kelvin(100.0), mouth_height=z_mouth, self_weight=self_weight
    )
    tapes = {
        "vertical load tape": GENERIC_TAPE,
        "mouth webbing": GENERIC_TAPE,
        "crown ring tape": GENERIC_TAPE,
    }
    model = model_from_rest_model(
        built.rest_model,
        {"default": GENERIC_FABRIC},
        cond,
        tapes,
        fixed_openings=("mouth",),
        closed_openings=("crown",),
        name=f"generic spherical envelope, {target_mm:g} mm mesh",
    )
    if seam_symmetry:
        tol = 1e-6 * float(np.abs(model.positions).max())
        for axis, name in ((0, "x = 0"), (1, "y = 0")):
            normal = np.zeros(3)
            normal[axis] = 1.0
            nodes = np.flatnonzero(np.abs(model.positions[:, axis]) < tol)
            model.symmetry.append(
                SymmetryPlane(f"seams on {name}", nodes, (normal[0], normal[1], normal[2]))
            )
    return model


def envelope_benchmarks(fixture: Path) -> tuple[list[BenchmarkResult], list[RefinementLevel]]:
    """Global equilibrium and mesh refinement on the generic spherical envelope.

    Returns
    -------
    rows : list of BenchmarkResult
        Force balance without and with self-weight, and the refinement changes.
    levels : list of RefinementLevel
        Per-level results of the refinement study.
    """
    rows: list[BenchmarkResult] = []
    tag = "Spherical envelope, 100 degC, mouth fixed"
    for weight in (False, True):
        result = solve(envelope_model(fixture, SMOKE_LEVEL_MM, self_weight=weight))
        balance = force_balance(result)
        pressure = result.loads.pressure[2] + sum(v[2] for v in result.loads.closures.values())
        mouth = result.loads.reactions["mouth"][2]
        label = f"{tag}, {'with' if weight else 'no'} weight"
        if weight:
            rows.append(
                BenchmarkResult(
                    f"{label}: global force imbalance",
                    balance.imbalance,
                    0.0,
                    "-",
                    "absolute",
                    5e-3,
                )
            )
        else:
            rows += [
                BenchmarkResult(
                    f"{label}: pressure force vs mouth reaction",
                    float(-mouth),
                    float(pressure),
                    "N",
                    "relative",
                    5e-3,
                ),
                BenchmarkResult(
                    f"{label}: pressure force vs lift V (rho_a - rho_i) g",
                    float(pressure),
                    result.lift,
                    "N",
                    "relative",
                    5e-3,
                ),
            ]
        rows += _converged_row(label, result)
    levels: list[RefinementLevel] = []
    for target in REFINEMENT_LEVELS_MM:
        model = envelope_model(fixture, target, seam_symmetry=True)
        res = solve(model)
        disp = np.linalg.norm(res.displacements, axis=1)
        tape_nodes = np.unique(np.concatenate([c.edges.ravel() for c in model.cables]))
        crown = model.closures[0].nodes
        levels.append(
            RefinementLevel(
                target,
                model.n_nodes,
                model.n_triangles,
                res.converged,
                float(disp.max()),
                float(disp[tape_nodes].max()),
                res.volume,
                float(res.displacements[crown, 2].mean()),
            )
        )
    fine, finer = levels[-2], levels[-1]
    rows += [
        BenchmarkResult(
            "Refinement, last two levels: total volume",
            finer.volume,
            fine.volume,
            "m^3",
            "relative",
            0.02,
        ),
        BenchmarkResult(
            "Refinement, last two levels: max displacement (all nodes)",
            finer.max_displacement,
            fine.max_displacement,
            "m",
            "relative",
            0.02,
        ),
        BenchmarkResult(
            "Refinement, last two levels: max displacement (load tapes)",
            finer.max_tape_displacement,
            fine.max_tape_displacement,
            "m",
            "relative",
            0.02,
        ),
        BenchmarkResult(
            "Refinement, last two levels: crown rise",
            finer.crown_rise,
            fine.crown_rise,
            "m",
            "relative",
            0.02,
        ),
        BenchmarkResult(
            "Refinement: all levels converged",
            float(sum(not lv.converged for lv in levels)),
            0.0,
            "-",
            "absolute",
            0.0,
        ),
    ]
    return rows, levels


def run_benchmarks(fixture: Path) -> PreviewBenchmarks:
    """Run every preview-solver benchmark.

    Parameters
    ----------
    fixture : Path
        Build-pack YAML of the generic spherical envelope.

    Returns
    -------
    PreviewBenchmarks
        Rows in display order and the refinement table.
    """
    results: list[BenchmarkResult] = []
    results += sphere_benchmarks()
    results += cylinder_benchmarks()
    results += hydrostatic_and_lift_benchmarks()
    results += catenary_benchmarks()
    results += wrinkling_benchmarks()
    rows, levels = envelope_benchmarks(fixture)
    results += rows
    return PreviewBenchmarks(results, levels)


def _fmt(value: float) -> str:
    return f"{value:.4g}"


def _fmt_error(result: BenchmarkResult) -> str:
    # Errors are shown to two significant digits and tiny errors as bounds so that the
    # page does not change between platforms (the solver converges to 1e-6 relative).
    if not math.isfinite(result.error):
        return "not converged"
    if result.kind == "relative":
        return "< 1e-05" if result.error < 1e-5 else f"{result.error:.1g}"
    if result.unit == "-" and result.error < 1e-5:
        return "< 1e-05"
    if result.unit == "m":
        return "< 0.01 mm" if result.error < 1e-5 else f"{result.error * 1000:.2g} mm"
    return f"{result.error:.1g}"


def _fmt_tolerance(result: BenchmarkResult) -> str:
    if result.unit == "m" and result.kind == "absolute":
        return f"{result.tolerance * 1000:g} mm"
    return f"{result.tolerance:g}"


def render_markdown(bench: PreviewBenchmarks) -> str:
    """Render the benchmark results as the Markdown validation page.

    Parameters
    ----------
    bench : PreviewBenchmarks
        Output of :func:`run_benchmarks`.

    Returns
    -------
    str
        Page content.
    """
    lines = [
        "# Preview solver benchmarks",
        "",
        "_Auto-generated by `python scripts/generate_validation_docs.py` from "
        "`envelopelab.validation.preview_solver`. Do not edit by hand; "
        "`tests/benchmarks/test_preview_solver.py` fails if this page is stale._",
        "",
        "Benchmarks required by AGENTS.md §6.4 for the dynamic-relaxation preview solver",
        "(`envelopelab.solvers.dynamic_relaxation`). Relative errors are fractions",
        "(0.01 = 1 %); absolute errors are in the unit shown. Every solve must reach the",
        "relative residual tolerance 1e-06; a solve that does not is shown as",
        "*not converged* and fails. Values are rounded to four significant digits and",
        "errors to one significant digit so that platform-dependent trailing digits do",
        "not change the page.",
        "",
        "| Benchmark | Computed | Reference | Unit | Error | Tolerance | Status |",
        "|---|---|---|---|---|---|---|",
    ]
    for result in bench.results:
        show = result.kind == "relative"
        value = _fmt(result.value) if show else "-"
        reference = _fmt(result.reference) if show else "-"
        status = "pass" if result.passed else "**FAIL**"
        lines.append(
            f"| {result.name} | {value} | {reference} | {result.unit} | "
            f"{_fmt_error(result)} | {_fmt_tolerance(result)} | {status} |"
        )
    lines += [
        "",
        "## Mesh refinement: generic spherical envelope",
        "",
        "Fixture `tests/fixtures/spherical_envelope` (12 gores x 5 rows, sphere of radius",
        "7 m between -72 deg and +78 deg latitude) imported from its DXF patterns and sewn",
        "with a uniform target edge length. Load case: 100 degC internal, ISA sea level,",
        "fabric and tape weight, mouth ring fixed, crown ring closed by an unmeshed",
        "parachute, and the four seam meridians in the planes x = 0 and y = 0 kept on",
        "those symmetry planes. Generic fabric and tapes (assumed values).",
        "",
        "| Target edge (mm) | Nodes | Triangles | Converged | Max displacement, all "
        "nodes (m) | Max displacement, load tapes (m) | Crown rise (m) | Volume (m^3) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for lv in bench.refinement:
        lines.append(
            f"| {lv.target_mm:g} | {lv.nodes} | {lv.triangles} | "
            f"{'yes' if lv.converged else '**no**'} | {lv.max_displacement:.3g} | "
            f"{lv.max_tape_displacement:.3g} | {lv.crown_rise:.3g} | {lv.volume:.4g} |"
        )
    lines += [
        "",
    ]
    levels = bench.refinement
    changes = [
        abs(b.max_displacement - a.max_displacement) / a.max_displacement
        for a, b in zip(levels[:-1], levels[1:], strict=True)
    ]
    lines += [
        "Change of the all-node maximum displacement between consecutive levels: "
        + ", ".join(f"{c * 100:.1f} %" for c in changes)
        + ".",
        "",
        '!!! warning "Maximum displacement is not mesh-converged in wrinkled fabric"',
        "    The largest displacements (over all nodes and over tape nodes) occur in the",
        "    wrinkled lower part of the envelope, where the tension-field solution leaves",
        "    the position of slack fabric, and of the tapes crossing it, only weakly",
        "    determined; they scatter between levels (see the changes above). The last",
        "    two automated levels agree within 2 %, but a one-off development run at",
        "    425 mm (5 028 nodes; not automated: about 90 000 iterations, 25 min) gave",
        "    1.07 m over all nodes (+12 %) and 0.83 m over tape nodes (+9 %) against the",
        "    600 mm level, while the volume changed by 0.15 % and the crown rise by",
        "    1.3 %. Treat displacements of wrinkled regions as indicative; the volume and",
        "    the crown rise are mesh-converged.",
        "",
        "## Notes",
        "",
        "* Sphere: stress-free flat facets of a geodesic octant. The largest single-element",
        "  deviation comes from the facet-angle error of the faceted surface, not from the",
        "  equilibrium (limit 5 %: element stresses are for display; the 2 % stress",
        "  tolerance applies to the mean).",
        "* Cylinder: unrolled polygonal pattern (stress-free initial shape); the end cap is",
        "  an unmeshed closure whose pressure is transferred to the top ring.",
        "* Catenary: 80 tension-only bars under self-weight, starting nearly straight.",
        "* Simple shear: all edges prescribed; the compression-carrying control shows that",
        "  the tension field changes the answer (Gt = Et / 2.6 vs Et / 4).",
        "* Lift: pressure integrated by the solver's follower-load assembly on a rigid",
        "  sphere; the mouth (zero pressure) is at the bottom pole.",
        "",
    ]
    return "\n".join(lines)
