r"""Appendage result metrics, identical for preview and CalculiX results.

Every metric is computed from a solver-independent
:class:`~envelopelab.solvers.simulation.SimulationResult` and the
:class:`~envelopelab.features.builder.AppendageModel` it came from, so a preview solve and
a CalculiX solve of the same model produce rows with the same keys and units.

Definitions
-----------
* **Projected (dome) height** :math:`h = \max_{i \in skin} d(x_i)`, the largest height of
  the skin above the designed host surface (for a rigidly held rim: above the rim plane,
  :math:`(x_i - c)\cdot n` with :math:`c` the footprint centre and :math:`n` its normal).
* **Footprint displacement**: largest and mean normal displacement of the rim nodes
  :math:`(x_i - X_i)\cdot n`.
* **Rim tape tension**: largest and mean tension, N.
* **Force transferred into a host tape**: largest tension of the host tape minus its
  tension at the patch edge (the far-field value), N.
* **Host fabric stress**: largest major principal resultant :math:`N_1` over the host
  triangles that touch the rim (both sides of the footprint line), N/m.
* **Fabric factor of safety** per region:
  :math:`\mathrm{FoS} = \min(N_{ult,warp}, N_{ult,weft}) / \max N_1`, the conservative
  bound for a stress direction that is not along the yarns.
* **Wrinkle / pucker zones**: wrinkled or slack fraction of the skin area, and of the
  skin triangles next to each rim segment between match points; a segment whose
  fraction exceeds the mean by :data:`PUCKER_EXCESS` is a predicted pucker.
* **Tubular appendage**: centreline stations (centroids of node rings at fixed pattern
  levels), tip displacement, base reaction (resultant of every applied load on the
  appendage, which equilibrium sends through its base) and lean angle between the
  base-to-tip chord and the host normal.

A metric from a result that is not converged is still reported (so that the user sees
it) but carries ``converged = False`` and must not be read as a prediction.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

from envelopelab.features.builder import AppendageModel
from envelopelab.solvers.membrane import FloatArray, IntArray
from envelopelab.solvers.simulation import SimulationResult

#: Wrinkled-fraction excess over the rim mean that marks a pucker, dimensionless.
PUCKER_EXCESS = 0.25
#: Required fabric factor of safety (assumed; see envelopelab.solvers.results).
REQUIRED_FOS = 5.0


@dataclass
class TapeTransfer:
    """Load a host tape picks up from the feature (N)."""

    tape: str
    max_tension: float
    far_field_tension: float

    @property
    def transferred(self) -> float:
        """Largest minus far-field tension, N."""
        return self.max_tension - self.far_field_tension


@dataclass
class AppendageMetrics:
    """Metrics of one appendage solve (SI units; see module docstring).

    ``verified`` is True only for a converged CalculiX result.
    """

    feature: str
    solver: str
    status: str
    converged: bool
    verified: bool
    projected_height: float
    initial_projected_height: float
    footprint_max_normal_displacement: float
    footprint_mean_normal_displacement: float
    rim_tape_max_tension: float
    rim_tape_mean_tension: float
    tape_transfer: list[TapeTransfer]
    host_rim_max_n1: float
    fos: dict[str, float]
    skin_wrinkled_fraction: float
    segment_wrinkled_fraction: list[float]
    pucker_segments: list[int]
    chamber_volume: float
    chamber_pressure: float
    intended: dict[str, float] = field(default_factory=dict)
    tube: dict[str, Any] = field(default_factory=dict)

    @property
    def fos_passed(self) -> bool:
        """Every region meets :data:`REQUIRED_FOS` and the solve converged."""
        return self.converged and all(v >= REQUIRED_FOS for v in self.fos.values())

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready dictionary (keys carry units)."""
        out: dict[str, Any] = {
            "feature": self.feature,
            "solver": self.solver,
            "status": self.status,
            "converged": self.converged,
            "verified": self.verified,
            "projected_height_m": self.projected_height,
            "initial_projected_height_m": self.initial_projected_height,
            "footprint_max_normal_displacement_m": self.footprint_max_normal_displacement,
            "footprint_mean_normal_displacement_m": self.footprint_mean_normal_displacement,
            "rim_tape_max_tension_n": self.rim_tape_max_tension,
            "rim_tape_mean_tension_n": self.rim_tape_mean_tension,
            "tape_transfer_n": {
                t.tape: {
                    "max_tension_n": t.max_tension,
                    "far_field_tension_n": t.far_field_tension,
                    "transferred_n": t.transferred,
                }
                for t in self.tape_transfer
            },
            "host_rim_max_n1_n_per_m": self.host_rim_max_n1,
            "fos": self.fos,
            "required_fos": REQUIRED_FOS,
            "required_fos_source": "assumed",
            "fos_passed": self.fos_passed,
            "skin_wrinkled_fraction": self.skin_wrinkled_fraction,
            "segment_wrinkled_fraction": self.segment_wrinkled_fraction,
            "pucker_segments": self.pucker_segments,
            "chamber_volume_m3": self.chamber_volume,
            "chamber_pressure_pa": self.chamber_pressure,
            "intended": self.intended,
        }
        if self.tube:
            out["tube"] = self.tube
        return out

    def rows(self) -> list[tuple[str, float | str, str]]:
        """(quantity, value, unit) rows for tables and CSV."""
        rows: list[tuple[str, float | str, str]] = [
            ("projected height", self.projected_height, "m"),
            ("footprint max normal displacement", self.footprint_max_normal_displacement, "m"),
            ("rim tape max tension", self.rim_tape_max_tension, "N"),
            ("host fabric max N1 at rim", self.host_rim_max_n1, "N/m"),
            ("skin wrinkled fraction", self.skin_wrinkled_fraction, "-"),
            ("chamber volume", self.chamber_volume, "m^3"),
            ("chamber pressure", self.chamber_pressure, "Pa"),
        ]
        rows += [(f"FoS {k}", v, "-") for k, v in self.fos.items()]
        rows += [(f"transferred into {t.tape}", t.transferred, "N") for t in self.tape_transfer]
        for key, value in self.tube.items():
            if isinstance(value, float):
                rows.append((key.replace("_", " "), value, _unit(key)))
        return rows


def _unit(key: str) -> str:
    if key.endswith("_deg"):
        return "deg"
    if key.endswith("_n"):
        return "N"
    return "m"


def _areas(x: FloatArray, tri: IntArray) -> FloatArray:
    e = x[tri]
    out: FloatArray = 0.5 * np.linalg.norm(np.cross(e[:, 1] - e[:, 0], e[:, 2] - e[:, 0]), axis=1)
    return out


def _fos(am: AppendageModel, result: SimulationResult, tris: IntArray) -> float:
    if not len(tris):
        return math.inf
    model = am.model
    strength = np.array(
        [
            min(model.materials[z].strength_warp.value, model.materials[z].strength_weft.value)
            for z in model.zone_names
        ]
    )[model.tri_zone[tris]]
    demand = np.maximum(result.principal[tris, 0], 1e-300)
    return float(np.min(strength / demand))


def appendage_metrics(am: AppendageModel, result: SimulationResult) -> AppendageMetrics:
    """Metrics of a solved appendage sub-model.

    Parameters
    ----------
    am : AppendageModel
        The assembled appendage.
    result : SimulationResult
        Preview (:func:`~envelopelab.solvers.simulation.from_preview`) or CalculiX result
        of ``am.model``.

    Returns
    -------
    AppendageMetrics
        Heights and displacements (m), tensions (N), resultants (N/m), volumes (m^3),
        pressures (Pa), fractions (-).
    """
    model = am.model
    x, x0 = result.positions, result.initial_positions
    n = am.footprint_normal
    skin_nodes = np.unique(model.triangles[am.skin_triangles])
    host = am.spec.host
    if host is not None:
        height = float(host.height_above(x[skin_nodes]).max())
        height0 = float(host.height_above(model.positions[skin_nodes]).max())
    else:
        height = float(((x[skin_nodes] - am.footprint_centre) @ n).max())
        height0 = float(((model.positions[skin_nodes] - am.footprint_centre) @ n).max())
    rim_disp = (x[am.rim_nodes] - x0[am.rim_nodes]) @ n
    tensions = result.tape_tensions
    rim_t = tensions.get(am.rim_tape, np.zeros(0)) if am.rim_tape else np.zeros(0)
    transfers = []
    boundary = set(int(i) for i in am.boundary_nodes)
    for name in am.host_tape_names:
        t = tensions[name]
        edges = result.tape_edges[name]
        at_edge = np.array([int(a) in boundary or int(b) in boundary for a, b in edges])
        far = float(t[at_edge].mean()) if at_edge.any() else float(t.min())
        transfers.append(TapeTransfer(name, float(t.max()), far))
    rim_set: np.ndarray = np.asarray(np.isin(model.triangles, am.rim_nodes).any(axis=1))
    host_all = np.concatenate([am.host_triangles, am.footprint_triangles])
    near_rim = host_all[rim_set[host_all]]
    host_rim_n1 = float(result.principal[near_rim, 0].max()) if len(near_rim) else 0.0
    fos = {"skin": _fos(am, result, am.skin_triangles)}
    if len(am.host_triangles):
        fos["host"] = _fos(am, result, am.host_triangles)
        fos["footprint"] = _fos(am, result, am.footprint_triangles)
    state = (
        result.wrinkle_state
        if result.wrinkle_state is not None
        else np.zeros(result.n_elements, np.int8)
    )
    area = _areas(model.positions, model.triangles)
    skin = am.skin_triangles
    wr = state[skin] != 0
    skin_frac = float(area[skin][wr].sum() / max(area[skin].sum(), 1e-300))
    # Skin triangles touching each rim segment between consecutive match points.
    seg_frac: list[float] = []
    loop = list(int(i) for i in am.rim_nodes)
    positions = {node: k for k, node in enumerate(loop)}
    marks = sorted(positions[int(m)] for m in am.match_nodes)
    skin_tri = model.triangles[skin]
    for j, start in enumerate(marks):
        stop = marks[(j + 1) % len(marks)]
        span = loop[start : stop + 1] if stop > start else loop[start:] + loop[: stop + 1]
        touch = np.isin(skin_tri, span).any(axis=1)
        a = area[skin][touch]
        seg_frac.append(float(a[wr[touch]].sum() / max(a.sum(), 1e-300)) if touch.any() else 0.0)
    mean = float(np.mean(seg_frac)) if seg_frac else 0.0
    puckers = [j for j, f in enumerate(seg_frac) if f > mean + PUCKER_EXCESS]
    volume = result.chamber_volumes.get(am.chamber.name, math.nan)
    pressure = float(am.chamber.pressure(np.array([am.footprint_centre[2]]))[0])
    return AppendageMetrics(
        feature=am.spec.name,
        solver=result.solver,
        status=result.status,
        converged=result.converged,
        verified=result.solver == "calculix" and result.converged and not result.errors,
        projected_height=height,
        initial_projected_height=height0,
        footprint_max_normal_displacement=float(np.abs(rim_disp).max()),
        footprint_mean_normal_displacement=float(rim_disp.mean()),
        rim_tape_max_tension=float(rim_t.max()) if len(rim_t) else 0.0,
        rim_tape_mean_tension=float(rim_t.mean()) if len(rim_t) else 0.0,
        tape_transfer=transfers,
        host_rim_max_n1=host_rim_n1,
        fos=fos,
        skin_wrinkled_fraction=skin_frac,
        segment_wrinkled_fraction=seg_frac,
        pucker_segments=puckers,
        chamber_volume=float(volume),
        chamber_pressure=pressure,
        intended=dict(am.spec.intended),
    )


def metrics_dict(metrics: AppendageMetrics) -> dict[str, Any]:
    """Plain dictionary of every dataclass field (for golden files)."""
    return asdict(metrics)
