r"""Post-processing of preview-solver results.

Everything here derives from a :class:`~envelopelab.solvers.dynamic_relaxation.SolveResult`
and its :class:`~envelopelab.solvers.model.SolverModel`. It provides:

* scalar result fields (nodes, triangles or tape elements) with units for heat maps:
  displacement, principal and fabric-axis stress resultants, strain, wrinkle state,
  pressure and tape tension;
* the deformed mesh (and an OBJ writer);
* the global force-balance table;
* factors of safety by material zone (warp and weft), seam and tape.

Factor of safety
----------------
For a fabric zone, :math:`\mathrm{FoS} = N_{ult} / \max N` separately along warp and weft,
where :math:`N` is the Cauchy resultant along the deformed yarn direction. For a seam,
the demand is the resultant normal to the seam line, :math:`N_{nn} = m^\mathsf{T}\sigma m`
(:math:`m` the in-plane normal to the seam edge), and the capacity is
:math:`\eta \min(N_{ult,warp}, N_{ult,weft})` with seam efficiency :math:`\eta` (the
smaller strength is used because the seam crosses the grain at varying angles). For a
tape, :math:`\mathrm{FoS} = T_{ult} / \max T`.

The required factor defaults to 5 and is tagged ``assumed``: take the value from the
airworthiness code that applies to the build (for example EASA CS-31HB, "Factor of
safety"). A factor from an unconverged solve is never reported as a pass.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np

from envelopelab.solvers.dynamic_relaxation import UNITS, SolveResult
from envelopelab.solvers.membrane import STATE_NAMES, FloatArray, IntArray
from envelopelab.solvers.model import SolverModel

Location = Literal["node", "triangle", "cable"]
SafetyKind = Literal["zone", "seam", "tape"]
DEFAULT_REQUIRED_FOS = 5.0


@dataclass(frozen=True)
class ResultField:
    """A scalar field for plotting.

    Attributes
    ----------
    name : str
        Field key.
    location : {"node", "triangle", "cable"}
        Where the values live (cable values follow :func:`cable_edges` order).
    values : ndarray
        One value per location.
    unit : str
        SI unit.
    description : str
        What the field is.
    """

    name: str
    location: Location
    values: FloatArray
    unit: str
    description: str

    @property
    def range(self) -> tuple[float, float]:
        """(min, max) of the finite values, in ``unit``."""
        finite = self.values[np.isfinite(self.values)]
        if not finite.size:
            return (math.nan, math.nan)
        return (float(finite.min()), float(finite.max()))


def cable_edges(model: SolverModel) -> tuple[IntArray, list[str]]:
    """All tape elements in model order and the tape name of each.

    Returns
    -------
    edges : ndarray of int, shape (e, 2)
        Node pairs.
    names : list of str
        Cable-set name per element.
    """
    if not model.cables:
        return np.zeros((0, 2), dtype=np.int64), []
    edges = np.concatenate([c.edges for c in model.cables])
    names = [c.name for c in model.cables for _ in range(len(c.edges))]
    return edges, names


def result_fields(model: SolverModel, result: SolveResult) -> dict[str, ResultField]:
    """Every plottable scalar field of a solve.

    Parameters
    ----------
    model : SolverModel
        The solved model.
    result : SolveResult
        Its result.

    Returns
    -------
    dict of str to ResultField
        ``displacement`` (m), ``pressure`` (Pa), ``n1``/``n2`` principal resultants
        (N/m), ``n_warp``/``n_weft``/``n_shear`` (N/m), ``strain_major``/``strain_minor``
        (-), ``area_ratio`` (-), ``wrinkle_state`` (0 taut, 1 wrinkled, 2 slack),
        ``released_compression`` (N/m, compression removed by the tension field) and
        ``tape_tension`` (N).
    """
    xe = result.positions[model.triangles]
    area = 0.5 * np.linalg.norm(np.cross(xe[:, 1] - xe[:, 0], xe[:, 2] - xe[:, 0]), axis=1)
    uv = model.rest_uv
    a, b = uv[:, 1] - uv[:, 0], uv[:, 2] - uv[:, 0]
    rest_area = 0.5 * np.abs(a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0])
    tension = (
        np.concatenate([result.tape_tensions[c.name] for c in model.cables])
        if model.cables
        else np.zeros(0)
    )
    fields = [
        ResultField(
            "displacement",
            "node",
            np.linalg.norm(result.displacements, axis=1),
            UNITS["displacements"],
            "displacement magnitude from the initial (as-sewn guess) positions",
        ),
        ResultField(
            "pressure", "node", result.node_pressure, UNITS["pressure"], "differential pressure"
        ),
        ResultField(
            "n1",
            "triangle",
            result.principal[:, 0],
            UNITS["stress_resultants"],
            "major principal Cauchy stress resultant",
        ),
        ResultField(
            "n2",
            "triangle",
            result.principal[:, 1],
            UNITS["stress_resultants"],
            "minor principal Cauchy stress resultant",
        ),
        ResultField(
            "n_warp",
            "triangle",
            result.fabric_resultants[:, 0],
            UNITS["stress_resultants"],
            "resultant along the deformed warp (grain) direction",
        ),
        ResultField(
            "n_weft",
            "triangle",
            result.fabric_resultants[:, 1],
            UNITS["stress_resultants"],
            "resultant along the deformed weft direction",
        ),
        ResultField(
            "n_shear",
            "triangle",
            result.fabric_resultants[:, 2],
            UNITS["stress_resultants"],
            "in-plane shear resultant on the warp axis",
        ),
        ResultField(
            "strain_major", "triangle", result.strain[:, 0], "-", "major Green-Lagrange strain"
        ),
        ResultField(
            "strain_minor", "triangle", result.strain[:, 1], "-", "minor Green-Lagrange strain"
        ),
        ResultField("area_ratio", "triangle", area / rest_area, "-", "current / as-cut area"),
        ResultField(
            "wrinkle_state",
            "triangle",
            result.state.astype(np.float64),
            "-",
            "tension-field state: " + ", ".join(f"{k} {v}" for k, v in sorted(STATE_NAMES.items())),
        ),
        ResultField(
            "released_compression",
            "triangle",
            np.maximum(-result.trial_minor, 0.0),
            UNITS["stress_resultants"],
            "compression the fabric cannot carry (released by the tension field); "
            "non-zero marks probable wrinkle zones",
        ),
        ResultField("tape_tension", "cable", tension, UNITS["tape_tensions"], "tape/cable tension"),
    ]
    return {f.name: f for f in fields}


def wrinkle_zones(result: SolveResult) -> IntArray:
    """Indices of triangles where compression was released (wrinkled or slack)."""
    return np.flatnonzero(result.state != 0)


def deformed_mesh(model: SolverModel, result: SolveResult) -> tuple[FloatArray, IntArray]:
    """Equilibrium node positions (m) and triangles."""
    return result.positions.copy(), model.triangles.copy()


def write_obj(path: str | Path, positions: FloatArray, triangles: IntArray) -> Path:
    """Write a triangle mesh as Wavefront OBJ (m).

    Parameters
    ----------
    path : str or Path
        Output file.
    positions : ndarray, shape (n, 3)
        m.
    triangles : ndarray of int, shape (m, 3)
        Zero-based node indices.

    Returns
    -------
    Path
        The written file.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# EnvelopeLab preview-solver deformed mesh, units m"]
    lines += [f"v {x:.6f} {y:.6f} {z:.6f}" for x, y, z in positions]
    lines += [f"f {a + 1} {b + 1} {c + 1}" for a, b, c in triangles]
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


# --------------------------------------------------------------------------------------
# Force balance
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class BalanceRow:
    """One line of the force-balance table: a force resultant in N."""

    item: str
    kind: Literal["applied", "reaction", "residual"]
    force: tuple[float, float, float]

    @property
    def magnitude(self) -> float:
        """Magnitude, N."""
        return float(np.linalg.norm(self.force))


@dataclass(frozen=True)
class ForceBalance:
    """Global equilibrium check.

    Attributes
    ----------
    rows : list of BalanceRow
        Applied loads, reactions and the free-node residual, N.
    applied : tuple of float
        Sum of applied loads, N.
    reactions : tuple of float
        Sum of reactions, N.
    reference : float
        Magnitude of the pressure resultant (membrane plus closures), N; the scale of the
        imbalance.
    imbalance : float
        :math:`|\\sum F_{applied} + \\sum R| / F_{ref}`, dimensionless.
    tolerance : float
        Pass limit (AGENTS.md: 0.5 %).
    converged : bool
        Whether the solve converged.
    """

    rows: list[BalanceRow]
    applied: tuple[float, float, float]
    reactions: tuple[float, float, float]
    reference: float
    imbalance: float
    tolerance: float
    converged: bool

    @property
    def passed(self) -> bool:
        """True when converged and the imbalance is within tolerance."""
        return self.converged and self.imbalance <= self.tolerance


def _vec(v: FloatArray) -> tuple[float, float, float]:
    return (float(v[0]), float(v[1]), float(v[2]))


def force_balance(result: SolveResult, tolerance: float = 5e-3) -> ForceBalance:
    """Global force-balance table of a solve.

    Parameters
    ----------
    result : SolveResult
        Solve result.
    tolerance : float
        Allowed relative imbalance, dimensionless (default 0.5 %).

    Returns
    -------
    ForceBalance
        Rows in N and the relative imbalance.
    """
    loads = result.loads
    rows = [BalanceRow("pressure on membrane", "applied", _vec(loads.pressure))]
    rows += [
        BalanceRow(f"pressure on closure {k}", "applied", _vec(v))
        for k, v in loads.closures.items()
    ]
    rows.append(BalanceRow("fabric weight", "applied", _vec(loads.fabric_weight)))
    rows.append(BalanceRow("tape weight", "applied", _vec(loads.tape_weight)))
    for label, group in (
        ("point load", loads.point_loads),
        ("line load", loads.line_loads),
        ("distributed load", loads.distributed_loads),
    ):
        rows += [BalanceRow(f"{label} {k}", "applied", _vec(v)) for k, v in group.items()]
    rows += [BalanceRow(f"reaction {k}", "reaction", _vec(v)) for k, v in loads.reactions.items()]
    rows.append(BalanceRow("unbalanced (free nodes)", "residual", _vec(loads.unbalanced)))
    applied = loads.external_total()
    reactions = sum((v for v in loads.reactions.values()), np.zeros(3))
    pressure = loads.pressure + sum((v for v in loads.closures.values()), np.zeros(3))
    reference = float(np.linalg.norm(pressure)) or float(np.linalg.norm(applied)) or 1.0
    imbalance = float(np.linalg.norm(applied + reactions)) / reference
    return ForceBalance(
        rows,
        _vec(applied),
        _vec(reactions),
        reference,
        imbalance,
        tolerance,
        result.converged,
    )


# --------------------------------------------------------------------------------------
# Factor of safety
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SafetyRow:
    """Factor of safety of one zone direction, seam or tape.

    Attributes
    ----------
    kind : {"zone", "seam", "tape"}
        Item type.
    name : str
        Zone (with direction), seam id or tape id.
    demand : float
        Largest load: N/m (zone, seam) or N (tape).
    capacity : float
        Strength in the same unit.
    unit : str
        Unit of demand and capacity.
    fos : float
        capacity / demand (``inf`` when unloaded), dimensionless.
    required : float
        Required factor, dimensionless.
    source : str
        Source tags of the strength values.
    converged : bool
        Whether the solve converged (unconverged rows never pass).
    location : int
        Triangle, seam edge or tape element index of the maximum (-1 when unloaded).
    """

    kind: SafetyKind
    name: str
    demand: float
    capacity: float
    unit: str
    fos: float
    required: float
    source: str
    converged: bool
    location: int

    @property
    def status(self) -> str:
        """``pass``, ``FAIL`` or ``not converged``."""
        if not self.converged:
            return "not converged"
        return "pass" if self.fos >= self.required else "FAIL"

    @property
    def passed(self) -> bool:
        """True only for a converged solve with FoS at or above the requirement."""
        return self.status == "pass"


def _row(
    kind: SafetyKind,
    name: str,
    demand: FloatArray,
    capacity: float,
    unit: str,
    required: float,
    source: str,
    converged: bool,
) -> SafetyRow:
    loaded = demand.size and float(np.max(demand)) > 0.0
    where = int(np.argmax(demand)) if loaded else -1
    peak = float(demand[where]) if loaded else 0.0
    fos = capacity / peak if peak > 0.0 else math.inf
    return SafetyRow(kind, name, peak, capacity, unit, fos, required, source, converged, where)


def _edge_triangles(triangles: IntArray) -> dict[tuple[int, int], list[int]]:
    out: dict[tuple[int, int], list[int]] = {}
    for t, tri in enumerate(triangles):
        for a, b in ((0, 1), (1, 2), (2, 0)):
            i, j = int(tri[a]), int(tri[b])
            out.setdefault((min(i, j), max(i, j)), []).append(t)
    return out


def factors_of_safety(
    model: SolverModel,
    result: SolveResult,
    required: float | Mapping[str, float] = DEFAULT_REQUIRED_FOS,
) -> list[SafetyRow]:
    """Factors of safety by material zone (warp, weft), seam and tape.

    Parameters
    ----------
    model : SolverModel
        Solved model (materials, seams, tapes).
    result : SolveResult
        Its result.
    required : float or mapping
        Required factor, dimensionless; a mapping may give ``zone``, ``seam`` and
        ``tape`` separately. Default 5 (assumed, see module docstring).

    Returns
    -------
    list of SafetyRow
        Zones first, then seams and tapes.
    """

    def req(kind: str) -> float:
        if isinstance(required, Mapping):
            return float(required.get(kind, DEFAULT_REQUIRED_FOS))
        return float(required)

    ok = result.converged
    rows: list[SafetyRow] = []
    for k, zone in enumerate(model.zone_names):
        mat = model.materials[zone]
        mask = model.tri_zone == k
        for col, direction, strength in (
            (0, "warp", mat.strength_warp),
            (1, "weft", mat.strength_weft),
        ):
            demand = np.where(mask, result.fabric_resultants[:, col], -np.inf)
            row = _row(
                "zone",
                f"{zone} ({direction})",
                demand,
                strength.value,
                "N/m",
                req("zone"),
                strength.source,
                ok,
            )
            rows.append(row)
    if model.seams:
        edge_tris = _edge_triangles(model.triangles)
        x = result.positions
        xe = x[model.triangles]
        normals = np.cross(xe[:, 1] - xe[:, 0], xe[:, 2] - xe[:, 0])
        for seam in model.seams:
            demand = np.zeros(len(seam.edges))
            capacity = math.inf
            sources: set[str] = set()
            for e, (i, j) in enumerate(seam.edges):
                t_vec = x[j] - x[i]
                for t in edge_tris.get((int(min(i, j)), int(max(i, j))), []):
                    m = np.cross(t_vec, normals[t])
                    m /= max(float(np.linalg.norm(m)), 1e-300)
                    demand[e] = max(demand[e], float(m @ result.stress[t] @ m))
                    mat = model.materials[model.zone_names[int(model.tri_zone[t])]]
                    cap = mat.seam_efficiency.value * min(
                        mat.strength_warp.value, mat.strength_weft.value
                    )
                    capacity = min(capacity, cap)
                    sources.update(
                        (
                            mat.seam_efficiency.source,
                            mat.strength_warp.source,
                            mat.strength_weft.source,
                        )
                    )
            rows.append(
                _row(
                    "seam",
                    seam.name,
                    demand,
                    capacity,
                    "N/m",
                    req("seam"),
                    "/".join(sorted(sources)),
                    ok,
                )
            )
    for cable in model.cables:
        strength = cable.material.breaking_strength
        rows.append(
            _row(
                "tape",
                cable.name,
                result.tape_tensions[cable.name],
                strength.value,
                "N",
                req("tape"),
                strength.source,
                ok,
            )
        )
    return rows


# --------------------------------------------------------------------------------------
# Summary and export
# --------------------------------------------------------------------------------------


def summary_markdown(
    model: SolverModel,
    result: SolveResult,
    required: float | Mapping[str, float] = DEFAULT_REQUIRED_FOS,
    max_rows: int = 20,
) -> str:
    """Human-readable summary: status, force balance, factors of safety, warnings.

    Parameters
    ----------
    model : SolverModel
        Solved model.
    result : SolveResult
        Its result.
    required : float or mapping
        Required factor of safety.
    max_rows : int
        Factor-of-safety rows shown (lowest factors first).

    Returns
    -------
    str
        Markdown text.
    """
    conv = result.convergence
    status = "CONVERGED" if conv.converged else "NOT CONVERGED - NOT A VALID RESULT"
    lines = [
        f"# Preview solve: {model.name}",
        "",
        f"**Status: {status}** ({conv.status}, {conv.iterations} iterations, relative "
        f"residual {conv.residual:.2e}, tolerance {conv.tolerance:.0e}, {conv.run_time:.1f} s)",
        "",
        f"Load case: {model.conditions.label}. Mesh: {model.n_nodes} nodes, "
        f"{model.n_triangles} triangles, "
        f"{sum(len(c.edges) for c in model.cables)} tape elements.",
        "",
        f"Volume {result.volume:.2f} m^3, gross lift {result.lift:.1f} N.",
        "",
        "## Force balance (N)",
        "",
        "| Item | Fx | Fy | Fz |",
        "|---|---|---|---|",
    ]
    balance = force_balance(result)
    for row in balance.rows:
        fx, fy, fz = row.force
        lines.append(f"| {row.item} | {fx:.2f} | {fy:.2f} | {fz:.2f} |")
    lines += [
        "",
        f"Imbalance {balance.imbalance:.2e} of the pressure resultant "
        f"({balance.reference:.1f} N); limit {balance.tolerance:.1e}: "
        f"{'pass' if balance.passed else '**FAIL**'}.",
        "",
        "## Factors of safety (lowest first)",
        "",
        "| Item | Demand | Capacity | Unit | FoS | Required | Source | Status |",
        "|---|---|---|---|---|---|---|---|",
    ]
    safety = sorted(factors_of_safety(model, result, required), key=lambda r: r.fos)
    for item in safety[:max_rows]:
        status_text = item.status if item.status == "pass" else f"**{item.status}**"
        lines.append(
            f"| {item.kind} {item.name} | {item.demand:.4g} | {item.capacity:.4g} | "
            f"{item.unit} | {item.fos:.3g} | {item.required:g} | {item.source} | "
            f"{status_text} |"
        )
    if len(safety) > max_rows:
        lines.append(f"| ... {len(safety) - max_rows} more | | | | | | | |")
    lines += ["", "## Warnings", ""]
    if result.warnings:
        lines += [f"- **{w.severity}** `{w.code}`: {w.message}" for w in result.warnings]
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def result_to_dict(model: SolverModel, result: SolveResult) -> dict[str, Any]:
    """JSON-ready result with units and metadata (format ``envelopelab.preview-result`` 1).

    Parameters
    ----------
    model : SolverModel
        Solved model.
    result : SolveResult
        Its result.

    Returns
    -------
    dict
        Metadata, fields (with units), force balance, factors of safety and warnings.
    """
    fields = result_fields(model, result)
    balance = force_balance(result)
    return {
        "format": "envelopelab.preview-result",
        "format_version": 1,
        "metadata": result.metadata,
        "converged": result.converged,
        "units": dict(UNITS),
        "volume_m3": result.volume,
        "lift_n": result.lift,
        "positions_m": np.round(result.positions, 9).tolist(),
        "triangles": model.triangles.tolist(),
        "fields": {
            name: {
                "location": f.location,
                "unit": f.unit,
                "description": f.description,
                "values": np.round(f.values, 9).tolist(),
            }
            for name, f in fields.items()
        },
        "force_balance": {
            "rows": [
                {"item": r.item, "kind": r.kind, "force_n": list(r.force)} for r in balance.rows
            ],
            "imbalance": balance.imbalance,
            "passed": balance.passed,
        },
        "factors_of_safety": [
            {
                "kind": r.kind,
                "name": r.name,
                "demand": r.demand,
                "capacity": r.capacity,
                "unit": r.unit,
                "fos": None if math.isinf(r.fos) else r.fos,
                "required": r.required,
                "source": r.source,
                "status": r.status,
            }
            for r in factors_of_safety(model, result)
        ],
        "warnings": [
            {"code": w.code, "message": w.message, "severity": w.severity} for w in result.warnings
        ],
    }


def save_result(model: SolverModel, result: SolveResult, path: str | Path) -> Path:
    """Write :func:`result_to_dict` as JSON.

    Parameters
    ----------
    model : SolverModel
        Solved model.
    result : SolveResult
        Its result.
    path : str or Path
        Output file.

    Returns
    -------
    Path
        The written file.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result_to_dict(model, result)), encoding="utf-8")
    return target
