r"""Virtual sewing: triangulate finished panels with Gmsh and join them along seams.

Method
------
1. **Seam-conforming boundary discretisation.** Every finished edge is resampled by arc
   length. For a seam between chains :math:`A` and :math:`B` both sides receive the *same*
   node fractions :math:`t_j` along the chain (the union of both sides' corner fractions,
   subdivided at the seam size, graded towards corners). Node :math:`j` of side A is sewn
   to node :math:`j` (orientation ``same``) or :math:`N - j` (``reversed``) of side B. A
   length difference between the sides (mismatch or designed ease) is therefore spread
   uniformly along the seam, as when a seam is eased by hand between match marks.
2. **Panel triangulation.** Each distinct instance geometry is meshed once in its flat
   local frame with Gmsh (Frontal-Delaunay by default [Gmsh]_). The prescribed boundary
   points are kept exactly (every boundary segment is a transfinite line with two nodes);
   embedded marks and tape paths become embedded mesh lines. A background size field
   refines the mesh near seams, holes, marks and corners and grows to the target edge
   length inside the panel.
3. **Sewing.** Local nodes of all instances are merged with a union-find over the seam
   node pairs, producing one topological mesh. Openings are left unsewn. Every triangle
   keeps its flat rest coordinates (the as-cut geometry), panel id, material zone, grain
   direction and source pattern id.

Assumptions: fabric is inextensible for the purpose of the rest geometry; seam ease is
uniform between the chain breakpoints; the rest area of the mesh equals the finished
panel area (seam allowances are folded away and not modelled as material).

References
----------
.. [Gmsh] C. Geuzaine and J.-F. Remacle, "Gmsh: a 3-D finite element mesh generator with
   built-in pre- and post-processing facilities", Int. J. Numer. Meth. Engng 79 (2009)
   1309-1331.
.. [Tarjan] R. E. Tarjan, "Efficiency of a good but not linear set union algorithm",
   J. ACM 22 (1975) 215-225 (union-find).
"""

from __future__ import annotations

import hashlib
import math
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import numpy.typing as npt
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

from envelopelab.assembly.seam_graph import Assembly, EdgeUse, GraphSeam, Instance
from envelopelab.assembly.spec import MeshOptions
from envelopelab.geometry.polygon import (
    FloatArray,
    distance_to_polyline,
    graded_fractions,
    point_at_fractions,
    points_in_polygon,
)

IntArray = npt.NDArray[np.int64]
#: Relative tolerance (x target size) used to match Gmsh nodes to prescribed points.
MATCH_TOLERANCE = 1e-6


class MeshingError(RuntimeError):
    """Raised when an assembly cannot be meshed (e.g. duplicate seam assignments)."""


@dataclass
class RestMesh:
    """The sewn as-cut mesh.

    Attributes
    ----------
    n_nodes : int
        Number of unique (sewn) nodes.
    triangles : ndarray of int, shape (m, 3)
        Global node indices, counter-clockwise in each panel's flat frame.
    rest_uv : ndarray, shape (m, 3, 2)
        Flat rest coordinates of each triangle corner in its instance frame, m.
    tri_instance : ndarray of int, shape (m,)
        Index into ``instance_ids``.
    instance_ids, instance_pieces, instance_zones, instance_sources : list of str
        Per-instance panel id, piece id, material zone and source pattern id
        (``file:layer:handle``).
    instance_grain : ndarray, shape (k, 2)
        Unit grain vector per instance in its flat frame (NaN when unknown).
    node_refs : list of list of (int, float, float)
        For each global node, the (instance index, u, v) positions it was sewn from.
    seam_edges : dict of str to ndarray of int, shape (e, 2)
        Mesh edges along each sewn seam (future cable elements), keyed by seam id.
    seam_pairs : dict of str to ndarray, shape (n, 4)
        Per seam node pair: global node, fraction on side A, length side A, length side B.
    tape_edges : dict of str to ndarray of int, shape (e, 2)
        Mesh edges along embedded tape paths and marks.
    openings : dict of str to ndarray of int
        Node chain of each declared opening.
    attachment_edges : set of (int, int)
        Sorted node pairs of T-junction seams (appendage sewn onto a marked line).
    options : MeshOptions
        Settings used.
    gmsh_runs : int
        Number of distinct panel geometries triangulated.
    run_time : float
        Wall time, s.
    """

    n_nodes: int
    triangles: IntArray
    rest_uv: FloatArray
    tri_instance: IntArray
    instance_ids: list[str]
    instance_pieces: list[str]
    instance_zones: list[str]
    instance_sources: list[str]
    instance_grain: FloatArray
    node_refs: list[list[tuple[int, float, float]]]
    seam_edges: dict[str, IntArray]
    seam_pairs: dict[str, FloatArray]
    tape_edges: dict[str, IntArray]
    openings: dict[str, IntArray]
    attachment_edges: set[tuple[int, int]]
    options: MeshOptions
    gmsh_runs: int = 0
    run_time: float = 0.0

    @property
    def rest_areas(self) -> FloatArray:
        """Signed flat area of each triangle, m^2."""
        a = self.rest_uv[:, 1] - self.rest_uv[:, 0]
        b = self.rest_uv[:, 2] - self.rest_uv[:, 0]
        return 0.5 * (a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0])

    @property
    def total_rest_area(self) -> float:
        """Sum of flat triangle areas, m^2."""
        return float(np.sum(np.abs(self.rest_areas)))

    def tags(self, triangle: int) -> dict[str, Any]:
        """Tags of one triangle (panel id, piece, zone, grain, source pattern id)."""
        k = int(self.tri_instance[triangle])
        grain = self.instance_grain[k]
        return {
            "panel_id": self.instance_ids[k],
            "piece_id": self.instance_pieces[k],
            "material_zone": self.instance_zones[k],
            "grain": None if np.isnan(grain[0]) else (float(grain[0]), float(grain[1])),
            "source_pattern_id": self.instance_sources[k],
        }


# --------------------------------------------------------------------------------------
# Boundary discretisation
# --------------------------------------------------------------------------------------


def _seam_size(seam: GraphSeam, opts: MeshOptions) -> float:
    if seam.seam_type in {"appendage", "reinforcement", "closing"} or seam.attachment:
        return opts.appendage
    return opts.seam


def _chain_breaks(assembly: Assembly, chain: list[EdgeUse]) -> tuple[FloatArray, float]:
    lengths = np.array([assembly.graph.nodes[u.node_id].length for u in chain])
    total = float(lengths.sum())
    return np.concatenate([[0.0], np.cumsum(lengths)]) / max(total, 1e-300), total


def _merge_close(values: FloatArray, tol: float = 1e-9) -> FloatArray:
    values = np.sort(values)
    keep = [values[0]]
    for v in values[1:]:
        if v - keep[-1] > tol:
            keep.append(v)
    keep[-1] = 1.0
    keep[0] = 0.0
    return np.array(keep)


def _seam_fractions(
    assembly: Assembly, seam: GraphSeam, opts: MeshOptions
) -> tuple[FloatArray, FloatArray, FloatArray]:
    """Chain-level fractions on side A and B for one seam, plus side A break points."""
    breaks_a, la = _chain_breaks(assembly, seam.side_a)
    breaks_b, lb = _chain_breaks(assembly, seam.side_b)
    b_in_a = breaks_b if seam.props.orientation == "same" else 1.0 - breaks_b
    union = _merge_close(np.concatenate([breaks_a, b_in_a]))
    size = _seam_size(seam, opts)
    longest = max(la, lb)
    parts = [np.array([0.0])]
    for u0, u1 in zip(union[:-1], union[1:], strict=True):
        f = graded_fractions((u1 - u0) * longest, size, opts.corner, opts.growth)
        parts.append(u0 + (u1 - u0) * f[1:])
    ta = np.concatenate(parts)
    ta[-1] = 1.0
    tb = ta if seam.props.orientation == "same" else 1.0 - ta[::-1]
    return ta, tb, breaks_a


def _assign_chain(
    assembly: Assembly,
    chain: list[EdgeUse],
    t_chain: FloatArray,
    fractions: dict[str, FloatArray],
    context: str,
) -> None:
    breaks, _ = _chain_breaks(assembly, chain)
    for k, use in enumerate(chain):
        lo, hi = breaks[k], breaks[k + 1]
        inside = t_chain[(t_chain >= lo - 1e-12) & (t_chain <= hi + 1e-12)]
        local = (inside - lo) / max(hi - lo, 1e-300)
        local = np.clip(local, 0.0, 1.0)
        if use.reversed:
            local = 1.0 - local[::-1]
        local[0], local[-1] = 0.0, 1.0
        if use.node_id in fractions:
            raise MeshingError(
                f"{context}: edge {use.node_id} is already sewn in another seam; resolve the "
                "duplicate assignment reported by the seam audit"
            )
        fractions[use.node_id] = local


def discretize(assembly: Assembly, opts: MeshOptions) -> dict[str, FloatArray]:
    """Node fractions along every meshed graph node.

    Parameters
    ----------
    assembly : Assembly
        Instances and seam graph.
    opts : MeshOptions
        Mesh sizes.

    Returns
    -------
    dict of str to ndarray
        Increasing arc-length fractions (0 to 1) per node id.
    """
    graph = assembly.graph
    fractions: dict[str, FloatArray] = {}
    for seam in graph.seams:
        if not seam.mesh or seam.seam_type == "rim" or not seam.side_b:
            continue
        ta, tb, _ = _seam_fractions(assembly, seam, opts)
        _assign_chain(assembly, seam.side_a, ta, fractions, seam.seam_id)
        _assign_chain(assembly, seam.side_b, tb, fractions, seam.seam_id)
    for node_id, node in graph.nodes.items():
        if node_id in fractions or not node.instance_id:
            continue
        inst = assembly.instances[node.instance_id]
        if not inst.mesh:
            continue
        loop = inst.loops.get(node.name)
        size = opts.hole if loop is not None and loop.role != "tape" else opts.seam
        end = opts.corner if loop is None else None
        fractions[node_id] = graded_fractions(node.length, size, end, opts.growth)
    return fractions


# --------------------------------------------------------------------------------------
# Gmsh
# --------------------------------------------------------------------------------------


@dataclass
class _PanelGeometry:
    outer: FloatArray
    outer_size: FloatArray
    holes: list[tuple[FloatArray, float]]
    embeds: list[tuple[FloatArray, bool, float]]
    corners: list[int]

    def key(self) -> str:
        digest = hashlib.sha256()
        for arr in [self.outer, self.outer_size]:
            digest.update(np.round(arr, 9).tobytes())
        digest.update(str(self.corners).encode())
        for pts, size in self.holes:
            digest.update(np.round(pts, 9).tobytes() + str(size).encode())
        for pts, closed, size in self.embeds:
            digest.update(np.round(pts, 9).tobytes() + str((closed, size)).encode())
        return digest.hexdigest()


_ALGORITHMS = {"frontal_delaunay": 6, "delaunay": 5, "meshadapt": 1}


def _gmsh_triangulate(geom: _PanelGeometry, opts: MeshOptions) -> tuple[FloatArray, IntArray]:
    import gmsh

    gmsh.model.add("panel")
    geo = gmsh.model.geo
    line_classes: dict[float, list[int]] = defaultdict(list)
    all_lines: list[int] = []

    def add_polyline(
        pts: FloatArray, closed: bool, sizes: FloatArray
    ) -> tuple[list[int], list[int]]:
        ptags = [
            geo.addPoint(float(x), float(y), 0.0, float(s))
            for (x, y), s in zip(pts, sizes, strict=True)
        ]
        n = len(ptags)
        count = n if closed else n - 1
        lines = [geo.addLine(ptags[i], ptags[(i + 1) % n]) for i in range(count)]
        for i, line in enumerate(lines):
            # Size classes are rounded to 1 % so that similar spacings share one field.
            size = float(min(sizes[i], sizes[(i + 1) % n]))
            line_classes[float(f"{size:.2g}")].append(line)
        all_lines.extend(lines)
        return ptags, lines

    outer_points, outer_lines = add_polyline(geom.outer, True, geom.outer_size)
    loops = [geo.addCurveLoop(outer_lines)]
    for pts, size in geom.holes:
        _, lines = add_polyline(pts, True, np.full(len(pts), size))
        loops.append(geo.addCurveLoop(lines))
    surface = geo.addPlaneSurface(loops)
    embedded: list[int] = []
    for pts, closed, size in geom.embeds:
        embedded.extend(add_polyline(pts, closed, np.full(len(pts), size))[1])
    geo.synchronize()
    if embedded:
        gmsh.model.mesh.embed(1, embedded, 2, surface)
    for line in all_lines:
        gmsh.model.mesh.setTransfiniteCurve(line, 2)

    field = gmsh.model.mesh.field
    thresholds: list[int] = []
    for size, lines in line_classes.items():
        dist = field.add("Distance")
        field.setNumbers(dist, "CurvesList", lines)
        field.setNumber(dist, "Sampling", 4)
        thr = field.add("Threshold")
        field.setNumber(thr, "InField", dist)
        field.setNumber(thr, "SizeMin", size)
        field.setNumber(thr, "SizeMax", opts.target)
        field.setNumber(thr, "DistMin", 0.5 * size)
        field.setNumber(thr, "DistMax", opts.refinement_distance)
        thresholds.append(thr)
    if geom.corners:
        dist = field.add("Distance")
        field.setNumbers(dist, "PointsList", [outer_points[i] for i in geom.corners])
        thr = field.add("Threshold")
        field.setNumber(thr, "InField", dist)
        field.setNumber(thr, "SizeMin", opts.corner)
        field.setNumber(thr, "SizeMax", opts.target)
        field.setNumber(thr, "DistMin", opts.corner)
        field.setNumber(thr, "DistMax", opts.refinement_distance)
        thresholds.append(thr)
    combined = field.add("Min")
    field.setNumbers(combined, "FieldsList", thresholds)
    field.setAsBackgroundMesh(combined)
    gmsh.model.mesh.generate(2)
    tags, coords, _ = gmsh.model.mesh.getNodes()
    xy = np.asarray(coords, dtype=np.float64).reshape(-1, 3)[:, :2]
    index = {int(t): i for i, t in enumerate(tags)}
    etypes, _, enodes = gmsh.model.mesh.getElements(2, surface)
    tris_list = [
        np.asarray(nodes).reshape(-1, 3)
        for et, nodes in zip(etypes, enodes, strict=True)
        if et == 2
    ]
    if len(tris_list) != len(etypes):
        raise MeshingError("Gmsh produced non-triangular surface elements")
    tris = np.vectorize(index.__getitem__)(np.vstack(tris_list)).astype(np.int64)
    gmsh.model.remove()
    # Orient every triangle counter-clockwise in the flat frame.
    a = xy[tris[:, 1]] - xy[tris[:, 0]]
    b = xy[tris[:, 2]] - xy[tris[:, 0]]
    flip = (a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0]) < 0
    tris[flip] = tris[flip][:, [0, 2, 1]]
    return xy, tris


class _GmshSession:
    def __init__(self, opts: MeshOptions) -> None:
        self.opts = opts
        self.started = False

    def __enter__(self) -> _GmshSession:
        import gmsh

        if not gmsh.isInitialized():
            try:
                gmsh.initialize(readConfigFiles=False, interruptible=False)
            except TypeError:  # older Gmsh without the keyword
                gmsh.initialize(readConfigFiles=False)
            self.started = True
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("General.Verbosity", 1)
        gmsh.option.setNumber("General.NumThreads", 1)
        gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
        gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
        gmsh.option.setNumber("Mesh.Algorithm", _ALGORITHMS[self.opts.algorithm])
        gmsh.option.setNumber("Mesh.RandomSeed", 1)
        return self

    def __exit__(self, *exc: object) -> None:
        import gmsh

        if self.started:
            gmsh.finalize()


# --------------------------------------------------------------------------------------
# Sewing
# --------------------------------------------------------------------------------------


class _UnionFind:
    def __init__(self, n: int) -> None:
        self.parent = np.arange(n)

    def find(self, i: int) -> int:
        root = i
        while self.parent[root] != root:
            root = int(self.parent[root])
        while self.parent[i] != root:
            self.parent[i], i = root, int(self.parent[i])
        return root

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


@dataclass
class _InstanceMesh:
    instance: Instance
    xy: FloatArray
    tris: IntArray
    curve_nodes: dict[str, IntArray] = field(default_factory=dict)
    offset: int = 0


def _curve_points(points: FloatArray, fractions: FloatArray) -> FloatArray:
    return point_at_fractions(points, fractions)


def _panel_geometry(
    assembly: Assembly, inst: Instance, fractions: dict[str, FloatArray], opts: MeshOptions
) -> tuple[_PanelGeometry, dict[str, FloatArray]]:
    graph = assembly.graph
    outer_parts: list[FloatArray] = []
    size_parts: list[FloatArray] = []
    curve_pts: dict[str, FloatArray] = {}
    corners: list[int] = []
    count = 0
    for name, edge in inst.edges.items():
        node_id = f"{inst.instance_id}:{name}"
        pts = _curve_points(edge.points, fractions[node_id])
        curve_pts[node_id] = pts
        seg = np.hypot(*np.diff(pts, axis=0).T)
        body = pts[:-1]
        sizes = np.maximum(np.concatenate([[seg[0]], np.minimum(seg[:-1], seg[1:])]), 1e-6)
        outer_parts.append(body)
        size_parts.append(sizes)
        if not edge.closed_loop:
            corners.append(count)
        count += len(body)
    holes: list[tuple[FloatArray, float]] = []
    embeds: list[tuple[FloatArray, bool, float]] = []
    for name, loop in inst.loops.items():
        node_id = f"{inst.instance_id}:{name}"
        base = graph.nodes[node_id].points
        pts = _curve_points(base, fractions[node_id])
        if not loop.closed and loop.role != "opening":
            # Open embedded lines stop about half a boundary spacing inside the outline so
            # that no sliver triangles form between a line end and a seam.
            far = distance_to_polyline(pts, inst.outline, closed=True) >= 0.5 * opts.seam
            keep = np.flatnonzero(far)
            if len(keep) < 2:
                continue
            pts = pts[keep[0] : keep[-1] + 1]
        curve_pts[node_id] = pts
        seg = float(np.min(np.hypot(*np.diff(pts, axis=0).T)))
        body = pts[:-1] if loop.closed else pts
        if loop.role == "opening":
            holes.append((body, seg))
        else:
            inside = points_in_polygon(body, inst.outline)
            if not np.all(inside):
                raise MeshingError(
                    f"{inst.instance_id}: embedded line {name} leaves the finished outline"
                )
            embeds.append((body, loop.closed, seg))
    geom = _PanelGeometry(
        outer=np.vstack(outer_parts),
        outer_size=np.concatenate(size_parts),
        holes=holes,
        embeds=embeds,
        corners=corners,
    )
    return geom, curve_pts


def _match_nodes(xy: FloatArray, pts: FloatArray, tol: float, context: str) -> IntArray:
    tree = cKDTree(xy)
    dist, idx = tree.query(pts)
    if np.any(dist > tol):
        worst = int(np.argmax(dist))
        raise MeshingError(
            f"{context}: prescribed boundary point {pts[worst]} not found in the Gmsh mesh "
            f"(nearest node {dist[worst]:.3g} m away)"
        )
    return np.asarray(idx, dtype=np.int64)


def sew(assembly: Assembly, opts: MeshOptions | None = None) -> RestMesh:
    """Triangulate every meshed instance and sew them into one topological mesh.

    Parameters
    ----------
    assembly : Assembly
        Instances and seam graph (from :func:`~envelopelab.assembly.seam_graph.build_assembly`).
    opts : MeshOptions, optional
        Mesh settings; defaults to ``assembly.spec.mesh``.

    Returns
    -------
    RestMesh
        The sewn mesh with per-triangle tags and seam/tape/opening annotations.
    """
    start = time.perf_counter()
    opts = opts or assembly.spec.mesh
    graph = assembly.graph
    fractions = discretize(assembly, opts)
    meshed = [inst for inst in assembly.instances.values() if inst.mesh]
    if not meshed:
        raise MeshingError("no meshed instances in the assembly")
    tol = MATCH_TOLERANCE * max(opts.target, 1e-3)
    cache: dict[str, tuple[FloatArray, IntArray]] = {}
    parts: list[_InstanceMesh] = []
    with _GmshSession(opts):
        for inst in meshed:
            geom, curve_pts = _panel_geometry(assembly, inst, fractions, opts)
            key = geom.key()
            if key not in cache:
                cache[key] = _gmsh_triangulate(geom, opts)
            xy, tris = cache[key]
            part = _InstanceMesh(inst, xy, tris)
            for node_id, pts in curve_pts.items():
                part.curve_nodes[node_id] = _match_nodes(xy, pts, tol, node_id)
            parts.append(part)
    offset = 0
    for part in parts:
        part.offset = offset
        offset += len(part.xy)
    uf = _UnionFind(offset)
    by_instance = {p.instance.instance_id: p for p in parts}

    def chain_nodes(chain: list[EdgeUse]) -> IntArray:
        out: list[int] = []
        prev_end: int | None = None
        for use in chain:
            node = graph.nodes[use.node_id]
            part = by_instance[node.instance_id]
            ids = part.curve_nodes[use.node_id] + part.offset
            ids = ids[::-1] if use.reversed else ids
            if prev_end is not None:
                uf.union(prev_end, int(ids[0]))
                ids = ids[1:]
            out.extend(int(i) for i in ids)
            prev_end = out[-1]
        return np.array(out, dtype=np.int64)

    seam_chains: dict[str, tuple[IntArray, IntArray]] = {}
    for seam in graph.seams:
        if not seam.mesh or seam.seam_type == "rim" or not seam.side_b:
            continue
        a = chain_nodes(seam.side_a)
        b = chain_nodes(seam.side_b)
        if len(a) != len(b):
            raise MeshingError(f"{seam.seam_id}: sides have {len(a)} and {len(b)} nodes")
        b_matched = b if seam.props.orientation == "same" else b[::-1]
        for i, j in zip(a, b_matched, strict=True):
            uf.union(int(i), int(j))
        seam_chains[seam.seam_id] = (a, b_matched)

    roots = np.array([uf.find(i) for i in range(offset)])
    unique, compact = np.unique(roots, return_inverse=True)
    n_nodes = len(unique)
    tri_list: list[IntArray] = []
    uv_list: list[FloatArray] = []
    inst_list: list[IntArray] = []
    node_refs: list[list[tuple[int, float, float]]] = [[] for _ in range(n_nodes)]
    for k, part in enumerate(parts):
        glob = compact[part.offset : part.offset + len(part.xy)]
        tri_list.append(glob[part.tris])
        uv_list.append(part.xy[part.tris])
        inst_list.append(np.full(len(part.tris), k, dtype=np.int64))
        for local, g in enumerate(glob):
            node_refs[int(g)].append((k, float(part.xy[local, 0]), float(part.xy[local, 1])))
    triangles = np.vstack(tri_list).astype(np.int64)
    degenerate = (
        (triangles[:, 0] == triangles[:, 1])
        | (triangles[:, 1] == triangles[:, 2])
        | (triangles[:, 0] == triangles[:, 2])
    )
    if np.any(degenerate):
        raise MeshingError(
            f"sewing collapsed {int(degenerate.sum())} triangles; a seam joins nodes of the "
            "same triangle (check seam pairing and orientation)"
        )

    def glob_of(ids: IntArray) -> IntArray:
        return np.asarray(compact[ids], dtype=np.int64)

    seam_edges: dict[str, IntArray] = {}
    seam_pairs: dict[str, FloatArray] = {}
    attachment: set[tuple[int, int]] = set()
    for seam in graph.seams:
        if seam.seam_id not in seam_chains:
            continue
        a, _ = seam_chains[seam.seam_id]
        ga = glob_of(a)
        edges = np.column_stack([ga[:-1], ga[1:]])
        edges = edges[edges[:, 0] != edges[:, 1]]
        seam_edges[seam.seam_id] = edges
        ta, _, _ = _seam_fractions(assembly, seam, opts)
        la = graph.chain_length(seam.side_a)
        lb = graph.chain_length(seam.side_b)
        seam_pairs[seam.seam_id] = np.column_stack(
            [ga.astype(float), ta, np.full(len(ga), la), np.full(len(ga), lb)]
        )
        if seam.attachment:
            attachment.update((int(min(e)), int(max(e))) for e in edges)
    for seam in graph.seams:
        if seam.seam_type != "rim" or not all(
            assembly.instances[graph.nodes[u.node_id].instance_id].mesh
            for u in seam.side_a
            if graph.nodes[u.node_id].instance_id
        ):
            continue
        edge_rows: list[IntArray] = []
        for use in seam.side_a:
            node = graph.nodes[use.node_id]
            ids = glob_of(
                by_instance[node.instance_id].curve_nodes[use.node_id]
                + by_instance[node.instance_id].offset
            )
            edge_rows.append(np.column_stack([ids[:-1], ids[1:]]))
        seam_edges[seam.seam_id] = np.vstack(edge_rows)
    tape_edges: dict[str, IntArray] = {}
    for part in parts:
        for name, loop in part.instance.loops.items():
            if loop.role == "opening":
                continue
            node_id = f"{part.instance.instance_id}:{name}"
            if node_id not in part.curve_nodes:
                continue  # too short to embed after trimming
            ids = glob_of(part.curve_nodes[node_id] + part.offset)
            tape_edges[node_id] = np.column_stack([ids[:-1], ids[1:]])
    openings: dict[str, IntArray] = {}
    for opening in graph.openings:
        chain: list[int] = []
        ok = True
        for use in opening.uses:
            node = graph.nodes[use.node_id]
            if node.instance_id not in by_instance:
                ok = False
                break
            part = by_instance[node.instance_id]
            chain.extend(int(i) for i in glob_of(part.curve_nodes[use.node_id] + part.offset))
        if ok:
            openings[opening.name] = np.array(chain, dtype=np.int64)
    grains = np.array(
        [
            p.instance.grain if p.instance.grain is not None else np.array([np.nan, np.nan])
            for p in parts
        ],
        dtype=np.float64,
    )
    return RestMesh(
        n_nodes=n_nodes,
        triangles=triangles,
        rest_uv=np.concatenate(uv_list),
        tri_instance=np.concatenate(inst_list),
        instance_ids=[p.instance.instance_id for p in parts],
        instance_pieces=[p.instance.piece.piece_id for p in parts],
        instance_zones=[p.instance.material_zone for p in parts],
        instance_sources=[p.instance.piece.provenance.pattern_id for p in parts],
        instance_grain=grains,
        node_refs=node_refs,
        seam_edges=seam_edges,
        seam_pairs=seam_pairs,
        tape_edges=tape_edges,
        openings=openings,
        attachment_edges=attachment,
        options=opts,
        gmsh_runs=len(cache),
        run_time=time.perf_counter() - start,
    )


# --------------------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------------------


@dataclass
class BoundaryLoop:
    """A closed chain of boundary edges and the declared opening it matches."""

    nodes: list[int]
    rest_length: float
    opening: str | None

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready dictionary."""
        return {
            "edges": len(self.nodes),
            "rest_length_m": round(self.rest_length, 6),
            "opening": self.opening,
            "intended": self.opening is not None,
        }


@dataclass
class MeshReport:
    """Mesh validation report.

    Attributes
    ----------
    nodes, triangles : int
        Counts.
    edges_boundary, edges_manifold, edges_attachment, edges_nonmanifold : int
        Edge counts by incident-triangle count (1, 2, declared T-junction, other > 2).
    nonmanifold_vertices : int
        Vertices whose triangle fan is not connected through edges (excluding the ends of
        declared attachment lines).
    orientation_conflicts : int
        Interior edges traversed in the same direction by both triangles.
    boundary_loops : list of BoundaryLoop
        Every boundary loop with the opening it matches (None = unintended hole).
    components : int
        Connected parts.
    min_quality, mean_quality : float
        Triangle quality :math:`q = 4\\sqrt3 A / \\sum l^2` (1 = equilateral).
    low_quality : int
        Triangles below ``MeshOptions.min_quality``.
    inverted : int
        Triangles with non-positive flat area.
    total_rest_area, expected_area : float
        Sum of flat triangle areas and of finished instance areas (outline minus openings),
        m^2.
    area_relative_error : float
        ``(total_rest_area - expected_area) / expected_area``.
    euler_characteristic : int
        :math:`V - E + F`.
    missing_openings : list of str
        Declared openings with no matching boundary loop.
    """

    nodes: int
    triangles: int
    edges_boundary: int
    edges_manifold: int
    edges_attachment: int
    edges_nonmanifold: int
    nonmanifold_vertices: int
    orientation_conflicts: int
    boundary_loops: list[BoundaryLoop]
    components: int
    min_quality: float
    mean_quality: float
    low_quality: int
    inverted: int
    total_rest_area: float
    expected_area: float
    area_relative_error: float
    euler_characteristic: int
    missing_openings: list[str]
    min_quality_threshold: float
    area_tolerance: float = 0.005
    gmsh_runs: int = 0
    run_time: float = 0.0

    @property
    def unintended_holes(self) -> int:
        """Boundary loops that match no declared opening."""
        return sum(loop.opening is None for loop in self.boundary_loops)

    @property
    def checks(self) -> dict[str, bool]:
        """Named pass/fail checks."""
        return {
            "no unintended holes": self.unintended_holes == 0,
            "all declared openings present": not self.missing_openings,
            "single connected part": self.components == 1,
            "no non-manifold edges": self.edges_nonmanifold == 0,
            "no non-manifold vertices": self.nonmanifold_vertices == 0,
            "consistent orientation": self.orientation_conflicts == 0,
            "no inverted elements": self.inverted == 0,
            f"min quality >= {self.min_quality_threshold:g}": self.min_quality
            >= self.min_quality_threshold,
            f"rest area within {self.area_tolerance * 100:g} % of finished area": abs(
                self.area_relative_error
            )
            <= self.area_tolerance,
        }

    @property
    def passed(self) -> bool:
        """All checks pass."""
        return all(self.checks.values())

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready dictionary."""
        return {
            "passed": self.passed,
            "checks": self.checks,
            "nodes": self.nodes,
            "triangles": self.triangles,
            "edges": {
                "boundary": self.edges_boundary,
                "manifold": self.edges_manifold,
                "attachment_t_junction": self.edges_attachment,
                "non_manifold": self.edges_nonmanifold,
            },
            "nonmanifold_vertices": self.nonmanifold_vertices,
            "orientation_conflicts": self.orientation_conflicts,
            "boundary_loops": [loop.as_dict() for loop in self.boundary_loops],
            "unintended_holes": self.unintended_holes,
            "missing_openings": self.missing_openings,
            "components": self.components,
            "quality": {
                "min": round(self.min_quality, 4),
                "mean": round(self.mean_quality, 4),
                "below_threshold": self.low_quality,
                "threshold": self.min_quality_threshold,
            },
            "inverted_elements": self.inverted,
            "total_rest_area_m2": round(self.total_rest_area, 6),
            "expected_finished_area_m2": round(self.expected_area, 6),
            "area_relative_error": self.area_relative_error,
            "euler_characteristic": self.euler_characteristic,
            "gmsh_runs": self.gmsh_runs,
            "run_time_s": round(self.run_time, 3),
        }


def triangle_quality(uv: FloatArray) -> FloatArray:
    r"""Shape quality of triangles, :math:`q = 4\sqrt{3}\,A / (l_1^2 + l_2^2 + l_3^2)`.

    Parameters
    ----------
    uv : ndarray, shape (m, 3, 2)
        Corner coordinates, m.

    Returns
    -------
    ndarray, shape (m,)
        Quality in [0, 1] (1 for equilateral, 0 for degenerate); negative for inverted.
    """
    a = uv[:, 1] - uv[:, 0]
    b = uv[:, 2] - uv[:, 0]
    c = uv[:, 2] - uv[:, 1]
    area = 0.5 * (a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0])
    denom = np.einsum("ij,ij->i", a, a) + np.einsum("ij,ij->i", b, b) + np.einsum("ij,ij->i", c, c)
    return np.asarray(4.0 * math.sqrt(3.0) * area / np.maximum(denom, 1e-300))


def validate_mesh(mesh: RestMesh, assembly: Assembly, area_tolerance: float = 0.005) -> MeshReport:
    """Check manifoldness, boundary loops, connectivity, quality and rest area.

    Parameters
    ----------
    mesh : RestMesh
        Sewn mesh.
    assembly : Assembly
        Assembly it was built from (declared openings, finished areas).
    area_tolerance : float
        Allowed relative difference between rest-mesh area and finished area.

    Returns
    -------
    MeshReport
        Validation report.
    """
    tris = mesh.triangles
    directed = np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
    uv = mesh.rest_uv
    directed_len = np.concatenate(
        [
            np.hypot(*(uv[:, 1] - uv[:, 0]).T),
            np.hypot(*(uv[:, 2] - uv[:, 1]).T),
            np.hypot(*(uv[:, 0] - uv[:, 2]).T),
        ]
    )
    undirected = np.sort(directed, axis=1)
    uniq, inverse, counts = np.unique(undirected, axis=0, return_inverse=True, return_counts=True)
    inverse = inverse.ravel()
    attach = (
        np.array([(int(a), int(b)) in mesh.attachment_edges for a, b in uniq], dtype=bool)
        if mesh.attachment_edges
        else np.zeros(len(uniq), dtype=bool)
    )
    boundary_mask = counts == 1
    manifold_mask = counts == 2
    attach_ok = attach & (counts == 3)
    nonmanifold = (counts > 2) & ~attach_ok
    # Orientation: on manifold edges the two directed copies must be opposite.
    forward = directed[:, 0] < directed[:, 1]
    fwd_count = np.bincount(inverse, weights=forward.astype(float), minlength=len(uniq))
    conflicts = int(np.sum(manifold_mask & (fwd_count != 1)))
    # Boundary loops from directed boundary edges.
    b_mask = boundary_mask[inverse]
    b_edges = directed[b_mask]
    b_length = {
        (int(s), int(t)): float(length)
        for (s, t), length in zip(b_edges, directed_len[b_mask], strict=True)
    }
    nxt: dict[int, list[int]] = defaultdict(list)
    for s, t in b_edges:
        nxt[int(s)].append(int(t))
    visited: set[tuple[int, int]] = set()
    loops: list[list[int]] = []
    for s, t in b_edges:
        if (int(s), int(t)) in visited:
            continue
        loop = [int(s)]
        cur, target = int(s), int(t)
        while (cur, target) not in visited:
            visited.add((cur, target))
            loop.append(target)
            cur = target
            options = [n for n in nxt.get(cur, []) if (cur, n) not in visited]
            if not options:
                break
            target = options[0]
        loops.append(loop[:-1] if loop[0] == loop[-1] else loop)
    opening_sets = {name: set(int(n) for n in nodes) for name, nodes in mesh.openings.items()}
    boundary_loops: list[BoundaryLoop] = []
    matched: set[str] = set()
    for loop in loops:
        nodes = set(loop)
        name = next((n for n, members in opening_sets.items() if nodes and nodes <= members), None)
        if name is not None:
            matched.add(name)
        length = sum(
            b_length.get((a, b), 0.0) for a, b in zip(loop, loop[1:] + loop[:1], strict=True)
        )
        boundary_loops.append(BoundaryLoop(loop, length, name))
    missing = sorted(set(opening_sets) - matched)
    # Components through shared nodes.
    n_tri = len(tris)
    rows = np.repeat(np.arange(n_tri), 3)
    adj = coo_matrix((np.ones(3 * n_tri), (rows, tris.ravel())), shape=(n_tri, mesh.n_nodes))
    node_graph = (adj.T @ adj).tocsr()
    n_comp, labels = connected_components(node_graph, directed=False)
    used_nodes = np.unique(tris)
    components = len(np.unique(labels[used_nodes])) if len(used_nodes) else 0
    del n_comp
    # Non-manifold vertices: triangle fans not connected through edges.
    attach_nodes = {n for e in mesh.attachment_edges for n in e}
    vertex_tris: dict[int, list[int]] = defaultdict(list)
    for t, (a, b, c) in enumerate(tris):
        vertex_tris[int(a)].append(t)
        vertex_tris[int(b)].append(t)
        vertex_tris[int(c)].append(t)
    edge_tris: dict[tuple[int, int], list[int]] = defaultdict(list)
    for t, (a, b, c) in enumerate(tris):
        for u, v in ((a, b), (b, c), (c, a)):
            edge_tris[(int(min(u, v)), int(max(u, v)))].append(t)
    nm_vertices = 0
    for v, tlist in vertex_tris.items():
        if v in attach_nodes:
            continue
        parent = {t: t for t in tlist}

        def root(t: int, parent: dict[int, int] = parent) -> int:
            while parent[t] != t:
                parent[t] = parent[parent[t]]
                t = parent[t]
            return t

        for t in tlist:
            for u in tris[t]:
                u = int(u)
                if u == v:
                    continue
                for other in edge_tris[(min(u, v), max(u, v))]:
                    if other in parent:
                        ra, rb = root(t), root(other)
                        if ra != rb:
                            parent[ra] = rb
        if len({root(t) for t in tlist}) > 1:
            nm_vertices += 1
    quality = triangle_quality(mesh.rest_uv)
    areas = mesh.rest_areas
    expected = sum(inst.finished_area for inst in assembly.instances.values() if inst.mesh)
    total = mesh.total_rest_area
    n_edges = len(uniq)
    return MeshReport(
        nodes=mesh.n_nodes,
        triangles=n_tri,
        edges_boundary=int(boundary_mask.sum()),
        edges_manifold=int(manifold_mask.sum()),
        edges_attachment=int(attach_ok.sum()),
        edges_nonmanifold=int(nonmanifold.sum()),
        nonmanifold_vertices=nm_vertices,
        orientation_conflicts=conflicts,
        boundary_loops=boundary_loops,
        components=components,
        min_quality=float(quality.min()) if n_tri else 0.0,
        mean_quality=float(quality.mean()) if n_tri else 0.0,
        low_quality=int(np.sum(quality < mesh.options.min_quality)),
        inverted=int(np.sum(areas <= 0)),
        total_rest_area=total,
        expected_area=expected,
        area_relative_error=(total - expected) / expected if expected else float("nan"),
        euler_characteristic=mesh.n_nodes - n_edges + n_tri,
        missing_openings=missing,
        min_quality_threshold=mesh.options.min_quality,
        area_tolerance=area_tolerance,
        gmsh_runs=mesh.gmsh_runs,
        run_time=mesh.run_time,
    )
