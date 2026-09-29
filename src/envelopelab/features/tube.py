r"""Tubular appendages (horns, masts, fins, legs) sewn onto a host footprint.

The tube is made from a flat conical pattern with four named edges: ``base`` (sewn to
the footprint line on the host), ``neck`` (the far end, closed by an unmeshed cap such
as a ball or end cap, or left open) and two ``sides`` sewn together (the closing seam).
Its gas chamber is fed like any appendage (:mod:`envelopelab.features.pressure`).

Initial shape
-------------
With the pattern apex :math:`O` (least-squares centre of the neck edge) every pattern
point has polar coordinates :math:`(\varrho, \alpha)`. A developed cone of included
angle :math:`\Theta` closes into a cone of half angle :math:`\gamma` with
:math:`\sin\gamma = \Theta / 2\pi`, and

.. math:: X = A - \varrho\cos\gamma\, a + \varrho\sin\gamma\,(\cos\phi\, e_1 + \sin\phi\, e_2),
          \qquad \phi = \frac{2\pi}{\Theta}(\alpha - \alpha_0)

for apex :math:`A` and axis :math:`a`. The mapped base ring is then fitted onto the host
footprint by the least-squares rigid motion [Kabsch]_ and its nodes are sewn to the
footprint nodes. This is a starting guess only: the lean of the tube follows from the
cut of the base edge (an oblique base edge leans the tube) and from the equilibrium, not
from the guess.

Optional internal structure
---------------------------
* ``internal_ties``: pattern levels :math:`\varrho` at which tension-only ties join
  opposite points of the section (internal lines that hold the section round and resist
  ovalling).
* support lines (:class:`SupportLine`): tension-only lines from a neck-ring fraction to a
  fixed anchor point, for line-supported appendages (fins, stayed masts).

References
----------
.. [Kabsch] W. Kabsch, "A solution for the best rotation to relate two sets of vectors",
   Acta Cryst. A32 (1976) 922-923.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field

import numpy as np
from scipy.spatial import cKDTree

from envelopelab.features.builder import (
    AppendageModel,
    AppendageSpec,
    FeatureBuildError,
    _Gmsh,
    _mesh_disc,
    build_appendage,
)
from envelopelab.features.ease import loop_arclength, loop_length
from envelopelab.materials.membrane import MembraneMaterial, TapeMaterial
from envelopelab.solvers.membrane import FloatArray, IntArray
from envelopelab.solvers.model import (
    AMBIENT,
    CableSet,
    LineLoad,
    NodeConstraint,
    OperatingConditions,
    PressureClosure,
    SeamLine,
    SolverModel,
)


@dataclass
class SupportLine:
    """Tension-only line from the neck ring to a fixed anchor.

    Attributes
    ----------
    name : str
        Line name.
    neck_fraction : float
        Attachment point as a fraction of the neck ring (0 = first neck node), -.
    anchor : tuple of float
        Anchor position, m (fixed).
    material : TapeMaterial
        Line.
    slack : float
        Unstressed length minus the initial distance, m (0 = just taut).
    """

    name: str
    neck_fraction: float
    anchor: tuple[float, float, float]
    material: TapeMaterial
    slack: float = 0.0


@dataclass
class TubeSpec:
    """Tubular appendage on a host (SI units).

    Attributes
    ----------
    base : AppendageSpec
        Host, footprint (the base line), holes, tapes, pressure and zones; its skin
        fields are ignored.
    base_edge, neck_edge, side_a, side_b : ndarray, shape (k, 2)
        Pattern edges, m; ``base_edge`` and ``neck_edge`` run in the same direction,
        ``side_a`` joins the base start to the neck start and ``side_b`` the base end to
        the neck end.
    tube_zone : str
        Material zone of the tube.
    tip_load : float
        Weight of an unmodelled end piece (ball, cap) hung on the neck ring, N.
    neck_closed : bool
        Close the neck with a pressure cap of the tube chamber.
    internal_ties : list of float
        Pattern radii of internal tie rings, m.
    tie_material : TapeMaterial, optional
        Material of the internal ties.
    supports : list of SupportLine
        Line supports.
    intended_lean_deg : float, optional
        Designed lean from the host normal, deg.
    intended_length : float, optional
        Designed length along the axis, m.
    """

    base: AppendageSpec
    base_edge: FloatArray
    neck_edge: FloatArray
    side_a: FloatArray
    side_b: FloatArray
    tube_zone: str = "tube"
    tip_load: float = 0.0
    neck_closed: bool = True
    internal_ties: list[float] = field(default_factory=list)
    tie_material: TapeMaterial | None = None
    supports: list[SupportLine] = field(default_factory=list)
    intended_lean_deg: float | None = None
    intended_length: float | None = None


@dataclass
class TubeModel:
    """Assembled tube: the appendage model plus tube index sets.

    Attributes
    ----------
    appendage : AppendageModel
        Host, footprint, chamber and solver model (``skin_triangles`` = tube skin).
    neck_nodes : ndarray of int
        Neck ring nodes.
    base_nodes : ndarray of int
        Base ring nodes (= footprint loop).
    pattern_radius : ndarray, shape (n,)
        Pattern distance from the apex of each tube node (NaN elsewhere), m.
    stations : ndarray
        Pattern radii of the centreline stations, m.
    spec : TubeSpec
        Input.
    """

    appendage: AppendageModel
    neck_nodes: IntArray
    base_nodes: IntArray
    pattern_radius: FloatArray
    stations: FloatArray
    spec: TubeSpec

    @property
    def model(self) -> SolverModel:
        """The solver model."""
        return self.appendage.model


def _circle_fit(points: FloatArray) -> FloatArray:
    a = np.column_stack([2.0 * points, np.ones(len(points))])
    b = (points**2).sum(axis=1)
    sol, *_ = np.linalg.lstsq(a, b, rcond=None)
    return np.asarray(sol[:2], dtype=np.float64)


def _resample(points: FloatArray, count: int) -> FloatArray:
    seg = np.linalg.norm(np.diff(points, axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    s = np.linspace(0.0, cum[-1], count)
    return np.column_stack([np.interp(s, cum, points[:, k]) for k in range(2)])


def _kabsch(src: FloatArray, dst: FloatArray) -> tuple[FloatArray, FloatArray]:
    cs, cd = src.mean(axis=0), dst.mean(axis=0)
    h = (src - cs).T @ (dst - cd)
    u, _, vt = np.linalg.svd(h)
    d = np.sign(np.linalg.det(vt.T @ u.T))
    rot = vt.T @ np.diag([1.0, 1.0, d]) @ u.T
    return rot, cd - rot @ cs


def build_tube(
    spec: TubeSpec,
    conditions: OperatingConditions,
    materials: Mapping[str, MembraneMaterial],
) -> TubeModel:
    """Assemble a tubular appendage on its host (see module docstring).

    Parameters
    ----------
    spec : TubeSpec
        Pattern edges (m), host and pressure specification, loads (N).
    conditions : OperatingConditions
        Envelope load case.
    materials : mapping of str to MembraneMaterial
        Fabric per zone (host zone and ``spec.tube_zone``).

    Returns
    -------
    TubeModel
        Solver model and tube index sets.
    """
    if spec.tube_zone not in materials:
        raise FeatureBuildError(f"{spec.base.name}: no material for zone {spec.tube_zone!r}")
    # The host patch, footprint and chamber come from the generic builder with a dummy
    # spherical-cap skin that is replaced below.
    base_spec = AppendageSpec(
        **{
            **spec.base.__dict__,
            "skin_mode": "spherical_cap",
            "cap_height": 0.1 * math.sqrt(abs(_area(spec.base.footprint))),
            "skin_zone": spec.tube_zone,
            "match_points": 1,
        }
    )
    host_model = build_appendage(base_spec, conditions, materials)
    hm = host_model.model
    keep = np.setdiff1d(np.arange(hm.n_triangles), host_model.skin_triangles)
    loop = host_model.rim_nodes
    size = spec.base.mesh_size

    # Pattern boundary: base points one per footprint node (arc-length correspondence).
    s_fp = loop_arclength(host_model.chart[loop])
    l_fp = loop_length(host_model.chart[loop])
    base_edge = np.asarray(spec.base_edge, dtype=np.float64)
    seg = np.linalg.norm(np.diff(base_edge, axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    t = s_fp / l_fp * cum[-1]
    base_pts = np.column_stack([np.interp(t, cum, base_edge[:, k]) for k in range(2)])
    base_pts = np.vstack([base_pts, base_edge[-1:]])  # the base end (sewn to node 0)
    side_len = max(float(np.linalg.norm(np.diff(spec.side_a, axis=0), axis=1).sum()), size)
    n_side = max(3, int(math.ceil(side_len / size)) + 1)
    side_a = _resample(np.asarray(spec.side_a, dtype=np.float64), n_side)
    side_b = _resample(np.asarray(spec.side_b, dtype=np.float64), n_side)
    neck_len = float(np.linalg.norm(np.diff(spec.neck_edge, axis=0), axis=1).sum())
    n_neck = max(6, int(math.ceil(neck_len / size)) + 1)
    neck = _resample(np.asarray(spec.neck_edge, dtype=np.float64), n_neck)
    outline = np.vstack([base_pts[:-1], side_b[:-1], neck[::-1][:-1], side_a[::-1][:-1]])
    signed = _area(outline)
    with _Gmsh():
        xy, tri = _mesh_disc(outline if signed > 0 else outline[::-1], size)
    tree = cKDTree(xy)
    tol = 1e-6 * max(float(np.ptp(xy, axis=0).max()), 1.0)

    def ids(points: FloatArray) -> IntArray:
        d, i = tree.query(points)
        if np.any(d > tol):
            raise FeatureBuildError(f"{spec.base.name}: tube pattern boundary not preserved")
        out: IntArray = np.asarray(i, dtype=np.int64)
        return out

    base_ids = ids(base_pts)
    a_ids, b_ids, neck_ids = ids(side_a), ids(side_b), ids(neck)
    # Global node numbering: base nodes -> footprint nodes, side_b -> side_a (closing).
    g = np.full(len(xy), -1, dtype=np.int64)
    g[base_ids[:-1]] = loop
    g[base_ids[-1]] = loop[0]
    next_id = hm.n_nodes
    for i in range(len(xy)):
        if g[i] < 0 and i not in set(b_ids.tolist()):
            g[i] = next_id
            next_id += 1
    g[b_ids] = g[a_ids]
    tri_tube = g[tri]
    n = next_id

    # Pattern polar coordinates about the apex and cone mapping.
    apex = _circle_fit(neck)
    rel = xy - apex
    rho = np.linalg.norm(rel, axis=1)
    alpha = np.unwrap(np.arctan2(rel[:, 1], rel[:, 0]))
    ang_a = np.arctan2(*(side_a[0] - apex)[::-1])
    ang_b = np.arctan2(*(side_b[0] - apex)[::-1])
    theta = abs(float(np.angle(np.exp(1j * (ang_b - ang_a)))))
    if theta <= 0.0 or theta >= 2.0 * math.pi:
        raise FeatureBuildError(f"{spec.base.name}: pattern is not a developed cone")
    alpha = np.angle(np.exp(1j * (np.arctan2(rel[:, 1], rel[:, 0]) - ang_a)))
    alpha = np.where(alpha < -1e-9, alpha + 2.0 * math.pi, alpha)
    sin_g = min(theta / (2.0 * math.pi), 0.999)
    cos_g = math.sqrt(1.0 - sin_g**2)
    best: FloatArray | None = None
    for sign in (1.0, -1.0):
        phi = sign * alpha * 2.0 * math.pi / theta
        local = np.column_stack(
            [rho * sin_g * np.cos(phi), rho * sin_g * np.sin(phi), -rho * cos_g]
        )
        rot, shift = _kabsch(local[base_ids[:-1]], hm.positions[loop])
        mapped = local @ rot.T + shift
        e = mapped[tri]
        nrm = np.cross(e[:, 1] - e[:, 0], e[:, 2] - e[:, 0])
        axis_pt = mapped[neck_ids].mean(axis=0)
        base_c = mapped[base_ids].mean(axis=0)
        axis = (axis_pt - base_c) / np.linalg.norm(axis_pt - base_c)
        c = e.mean(axis=1)
        radial = (c - base_c) - ((c - base_c) @ axis)[:, None] * axis
        if float(np.einsum("mi,mi->m", nrm, radial).sum()) > 0.0:
            best = mapped
            break
    if best is None:
        raise FeatureBuildError(f"{spec.base.name}: cannot orient the tube outward")
    positions = np.zeros((n, 3))
    positions[: hm.n_nodes] = hm.positions
    for i in range(len(xy)):
        if g[i] >= hm.n_nodes:
            positions[g[i]] = best[i]

    # Assemble: host triangles, tube triangles, optional diaphragms.
    m_h = len(keep)
    tri_all = np.concatenate([hm.triangles[keep], tri_tube])
    rest = np.concatenate([hm.rest_uv[keep], xy[tri]])
    zone_names = sorted(set(hm.zone_names) | {spec.tube_zone})
    tri_zone = np.concatenate(
        [
            np.array([zone_names.index(hm.zone_names[z]) for z in hm.tri_zone[keep]]),
            np.full(len(tri_tube), zone_names.index(spec.tube_zone)),
        ]
    )
    grain = np.concatenate([hm.grain[keep], np.tile(spec.base.skin_grain, (len(tri_tube), 1))])
    assert hm.tri_chambers is not None
    tri_chambers = np.concatenate(
        [hm.tri_chambers[keep], np.tile([0, AMBIENT], (len(tri_tube), 1))]
    )
    pattern_radius = np.full(n, np.nan)
    for i in range(len(xy)):
        if g[i] >= hm.n_nodes or g[i] in set(loop.tolist()):
            pattern_radius[g[i]] = rho[i]
    neck_nodes = np.unique(g[neck_ids])
    closures = []
    line_loads = []
    if spec.neck_closed:
        closures.append(
            PressureClosure(f"{spec.base.name}:neck", neck_nodes, host_model.chamber.name)
        )
    neck_order = g[neck_ids]
    neck_edges = np.column_stack([neck_order[:-1], neck_order[1:]])
    if spec.tip_load > 0.0:
        length = float(np.linalg.norm(np.diff(positions[neck_order], axis=0), axis=1).sum())
        line_loads.append(
            LineLoad(
                f"{spec.base.name}:tip load",
                neck_edges,
                np.array([0.0, 0.0, -spec.tip_load / length]),
            )
        )
    cables = list(hm.cables)
    constraints = list(hm.constraints)
    for level in spec.internal_ties:
        if spec.tie_material is None:
            raise FeatureBuildError(f"{spec.base.name}: internal ties need a tie material")
        width = 0.75 * size
        ring = [
            i for i in range(len(xy)) if abs(rho[i] - level) <= 0.5 * width and g[i] >= hm.n_nodes
        ]
        nodes = np.unique(g[ring])
        if len(nodes) < 4:
            raise FeatureBuildError(f"{spec.base.name}: no tube section at radius {level} m")
        centre = positions[nodes].mean(axis=0)
        pairs = []
        for a in nodes:
            opposite = 2.0 * centre - positions[a]
            b = nodes[int(np.argmin(np.linalg.norm(positions[nodes] - opposite, axis=1)))]
            if a < b:
                pairs.append((int(a), int(b)))
        edges = np.array(sorted(set(pairs)), dtype=np.int64)
        rest_len = np.linalg.norm(positions[edges[:, 1]] - positions[edges[:, 0]], axis=1)
        cables.append(
            CableSet(f"{spec.base.name}:tie@{level:g}", edges, spec.tie_material, rest_len)
        )
    for line in spec.supports:
        k = int(round(line.neck_fraction * (len(neck_order) - 1)))
        node = int(neck_order[k])
        anchor_id = len(positions)
        positions = np.vstack([positions, np.asarray(line.anchor, dtype=np.float64)])
        dist = float(np.linalg.norm(positions[anchor_id] - positions[node]))
        cables.append(
            CableSet(
                line.name,
                np.array([[node, anchor_id]]),
                line.material,
                np.array([dist + line.slack]),
            )
        )
        constraints.append(NodeConstraint(f"{line.name}:anchor", np.array([anchor_id])))
    model = SolverModel(
        positions=positions,
        triangles=tri_all,
        rest_uv=rest,
        grain=grain,
        tri_zone=tri_zone,
        zone_names=zone_names,
        materials={z: materials[z] for z in zone_names},
        conditions=conditions,
        cables=cables,
        seams=[SeamLine(f"{spec.base.name}:base", np.column_stack([loop, np.roll(loop, -1)]))]
        + [s for s in hm.seams if not s.name.endswith(":rim")],
        constraints=constraints,
        closures=closures,
        line_loads=line_loads,
        chambers=list(hm.chambers),
        tri_chambers=tri_chambers,
        name=f"tube {spec.base.name}",
    )
    finite = pattern_radius[np.isfinite(pattern_radius)]
    stations = np.linspace(float(np.median(rho[base_ids])), float(finite.min()), 9)
    appendage = AppendageModel(
        spec=spec.base,
        model=model,
        chart=np.vstack(
            [
                host_model.chart[: hm.n_nodes],
                np.full((n - hm.n_nodes + len(spec.supports), 2), np.nan),
            ]
        ),
        skin_triangles=np.arange(m_h, len(tri_all)),
        footprint_triangles=np.flatnonzero(np.isin(keep, host_model.footprint_triangles)),
        host_triangles=np.flatnonzero(np.isin(keep, host_model.host_triangles)),
        rim_nodes=loop,
        match_nodes=loop[:1],
        rim_tape=host_model.rim_tape,
        host_tape_names=host_model.host_tape_names,
        boundary_nodes=host_model.boundary_nodes,
        ease=None,
        feed=host_model.feed,
        chamber=host_model.chamber,
        footprint_normal=host_model.footprint_normal,
        footprint_centre=host_model.footprint_centre,
    )
    return TubeModel(appendage, neck_nodes, loop, pattern_radius, stations, spec)


def frustum_pattern(
    base_radius: float, tip_radius: float, length: float, lean_deg: float = 0.0, count: int = 96
) -> dict[str, FloatArray]:
    r"""Developed pattern of a conical frustum whose base is cut obliquely.

    A cone of half angle :math:`\gamma` (:math:`\tan\gamma = (r_b - r_t)/L`) with apex
    height :math:`h_a = r_b / \tan\gamma` above the base centre is cut by a base plane
    tilted by the lean :math:`\lambda`; the generator at azimuth :math:`\phi` meets it at
    slant distance

    .. math:: \varrho(\phi) = \frac{h_a\cos\lambda}
              {\cos\lambda\cos\gamma - \sin\lambda\sin\gamma\cos\phi}

    and unrolls to the polar angle :math:`\alpha = \phi\sin\gamma`. Sewn onto a host
    with its base plane tangent to it, the tube's axis leans by :math:`\lambda` from the
    host normal towards :math:`\phi = \pi` (the short side).

    Parameters
    ----------
    base_radius, tip_radius : float
        Radii of the perpendicular sections at the base centre and at the tip, m.
    length : float
        Axial distance from base centre to tip, m.
    lean_deg : float
        Lean :math:`\lambda`, deg (0 for a straight cut).
    count : int
        Points per edge.

    Returns
    -------
    dict of str to ndarray
        ``base``, ``neck``, ``side_a``, ``side_b`` pattern edges, m.
    """
    if not 0.0 < tip_radius < base_radius or length <= 0.0:
        raise FeatureBuildError("frustum needs 0 < tip radius < base radius and length > 0")
    gamma = math.atan((base_radius - tip_radius) / length)
    lam = math.radians(lean_deg)
    h_a = base_radius / math.tan(gamma)
    phi = np.linspace(-math.pi, math.pi, count)
    rho_b = (
        h_a
        * math.cos(lam)
        / (math.cos(lam) * math.cos(gamma) - math.sin(lam) * math.sin(gamma) * np.cos(phi))
    )
    rho_t = tip_radius / math.sin(gamma)
    a = phi * math.sin(gamma)
    base = np.column_stack([rho_b * np.cos(a), rho_b * np.sin(a)])
    neck = np.column_stack([rho_t * np.cos(a), rho_t * np.sin(a)])
    side_a = np.column_stack([np.linspace(base[0], neck[0], count)])
    side_b = np.column_stack([np.linspace(base[-1], neck[-1], count)])
    return {"base": base, "neck": neck, "side_a": side_a, "side_b": side_b}


def _area(points: FloatArray) -> float:
    x, y = points[:, 0], points[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def tube_metrics(tube: TubeModel, positions: FloatArray) -> dict[str, float | list[list[float]]]:
    r"""Centreline, tip displacement, base reaction and lean of a solved tube.

    Parameters
    ----------
    tube : TubeModel
        The assembled tube.
    positions : ndarray, shape (n, 3)
        Solved node positions, m.

    Returns
    -------
    dict
        ``centreline_m`` (stations, m), ``centreline_max_deflection_m`` (largest
        station movement from the initial shape, m), ``tip_displacement_m`` (m),
        ``base_reaction_n`` (magnitude of the resultant of every applied load on the
        tube, which equilibrium passes through the base, N), ``lean_deg`` (angle between
        the base-to-tip chord and the host normal at the base, deg),
        ``intended_lean_deg`` and ``lean_error_deg`` when a lean is intended, and
        ``length_m`` (base centre to tip, m).
    """
    model = tube.model
    x0 = model.positions

    def centreline(x: FloatArray) -> FloatArray:
        pts = []
        r = tube.pattern_radius
        width = abs(tube.stations[1] - tube.stations[0])
        for level in tube.stations:
            sel = np.flatnonzero(np.isfinite(r) & (np.abs(r - level) <= 0.5 * width))
            if len(sel):
                pts.append(x[sel].mean(axis=0))
        return np.array(pts)

    line, line0 = centreline(positions), centreline(x0)
    k = min(len(line), len(line0))
    tip = positions[tube.neck_nodes].mean(axis=0)
    tip0 = x0[tube.neck_nodes].mean(axis=0)
    base = positions[tube.base_nodes].mean(axis=0)
    chord = tip - base
    normal = tube.appendage.footprint_normal
    lean = math.degrees(math.acos(float(np.clip(chord @ normal / np.linalg.norm(chord), -1, 1))))
    # Applied loads on the tube: pressure on its skin, the neck cap, weight, tip load.
    tri = model.triangles[tube.appendage.skin_triangles]
    xe = positions[tri]
    area_n = 0.5 * np.cross(xe[:, 1] - xe[:, 0], xe[:, 2] - xe[:, 0])
    p = model.triangle_pressure(xe[:, :, 2], tube.appendage.skin_triangles).mean(axis=1)
    force = (p[:, None] * area_n).sum(axis=0)
    for closure in model.closures:
        ring = positions[closure.nodes]
        centre = ring.mean(axis=0)
        cap = np.zeros(3)
        order = tube.neck_nodes
        for a, b in zip(order, np.roll(order, -1), strict=True):
            cap += 0.5 * np.cross(positions[a] - centre, positions[b] - centre)
        pc = float(
            model.chamber_pressure(model.chamber_index(closure.chamber), np.array([centre[2]]))[0]
        )
        cap_dir = cap if cap @ (centre - base) > 0 else -cap
        force += pc * cap_dir
    if model.conditions.self_weight:
        uv = model.rest_uv[tube.appendage.skin_triangles]
        a = uv[:, 1] - uv[:, 0]
        b = uv[:, 2] - uv[:, 0]
        rest_area = 0.5 * np.abs(a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0])
        zones = model.tri_zone[tube.appendage.skin_triangles]
        mass = sum(
            float(rest_area[zones == zi].sum()) * model.materials[z].areal_mass.value
            for zi, z in enumerate(model.zone_names)
        )
        force += np.array([0.0, 0.0, -mass * model.conditions.gravity])
    force += np.array([0.0, 0.0, -tube.spec.tip_load])
    out: dict[str, float | list[list[float]]] = {
        "centreline_m": line.tolist(),
        "centreline_max_deflection_m": float(np.linalg.norm(line[:k] - line0[:k], axis=1).max()),
        "tip_displacement_m": float(np.linalg.norm(tip - tip0)),
        "base_reaction_n": float(np.linalg.norm(force)),
        "lean_deg": lean,
        "length_m": float(np.linalg.norm(chord)),
    }
    if tube.spec.intended_lean_deg is not None:
        out["intended_lean_deg"] = float(tube.spec.intended_lean_deg)
        out["lean_error_deg"] = lean - float(tube.spec.intended_lean_deg)
    if tube.spec.intended_length is not None:
        out["intended_length_m"] = float(tube.spec.intended_length)
    return out


__all__ = ["SupportLine", "TubeModel", "TubeSpec", "build_tube", "frustum_pattern", "tube_metrics"]
