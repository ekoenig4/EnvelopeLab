"""Seam graph: which finished edges are sewn to which.

Nodes are finished edges: panel edges, feature edges (appendage outlines, embedded marks,
hole rims), tape paths and the composite mouth / parachute-opening boundaries. Graph
edges ("seams") are sewn relationships between two *chains* of nodes: horizontal panel
seams, vertical gore seams, reinforcement, appendage and closing seams, plus one-sided rim
seams (hems) on openings. Seam metadata carries the type, allowance, stitch rows, load
tape, designed ease, construction order and orientation.

The graph is built from the finished pieces and the assembly spec by
:func:`build_assembly` and can be exported as JSON and human-readable CSV.
"""

from __future__ import annotations

import csv
import io
import json
import math
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np

from envelopelab.assembly.pieces import FinishedPiece
from envelopelab.assembly.spec import (
    AssemblySpec,
    EdgeRef,
    FeatureSelector,
    OpeningKind,
    RingBoundaryRef,
    RingSpec,
    SeamProperties,
    SeamType,
)
from envelopelab.geometry.polygon import (
    FloatArray,
    OutlineEdge,
    cumulative_length,
    distance_to_polyline,
    orient_ccw,
    point_at_fractions,
    points_in_polygon,
    polyline_length,
    signed_area,
    split_edges,
)
from envelopelab.io.pattern_import import ImportWarning, PatternEntity, Provenance

NodeKind = Literal[
    "panel_edge",
    "feature_edge",
    "tape_path",
    "mouth_boundary",
    "parachute_boundary",
    "opening_boundary",
]
LoopKind = Literal["opening", "mark", "tape"]


#: Embedded tape lines stop this far inside a finished outline, m, so that they do not
#: add nodes to seam edges (which must match the sewn neighbour node for node).
TAPE_EDGE_MARGIN = 0.01


class AssemblyError(ValueError):
    """Raised when the assembly spec cannot be applied to the imported pieces."""


def clip_inside(points: FloatArray, outline: FloatArray, margin: float) -> FloatArray | None:
    """Longest part of an open polyline that stays inside an outline by ``margin``.

    Parameters
    ----------
    points : ndarray, shape (n, 2)
        Open polyline, m.
    outline : ndarray, shape (k, 2)
        Closed outline, m.
    margin : float
        Minimum distance from the outline, m.

    Returns
    -------
    ndarray, shape (m, 2) or None
        Clipped polyline (resampled at 1 mm where it is cut), or None if nothing is left.
    """
    inside = points_in_polygon(points, outline) & (
        distance_to_polyline(points, outline, closed=True) > margin
    )
    if np.all(inside):
        return points
    length = polyline_length(points)
    n = max(2, int(np.ceil(length / 1e-3)) + 1)
    dense = point_at_fractions(points, np.linspace(0.0, 1.0, n))
    ok = points_in_polygon(dense, outline) & (
        distance_to_polyline(dense, outline, closed=True) > margin
    )
    best: tuple[int, int] | None = None
    start: int | None = None
    for i, flag in enumerate([*ok.tolist(), False]):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            if best is None or i - start > best[1] - best[0]:
                best = (start, i)
            start = None
    if best is None or best[1] - best[0] < 2:
        return None
    run = dense[best[0] : best[1]]
    # Keep the original vertices inside the run, plus the two cut points.
    s_dense = np.linspace(0.0, 1.0, n)[best[0] : best[1]]
    s_orig = cumulative_length(points) / max(length, 1e-300)
    interior = points[(s_orig > s_dense[0]) & (s_orig < s_dense[-1])]
    return np.vstack([run[:1], interior, run[-1:]])


@dataclass(eq=False)
class InstanceLoop:
    """A hole, embedded mark or tape path inside an instance (local frame).

    Attributes
    ----------
    name : str
        Name, unique within the instance.
    points : ndarray, shape (n, 2)
        Vertices in the instance local frame, m (closed loops counter-clockwise, first
        vertex not repeated; for loops the start vertex is the topmost one).
    closed : bool
        Closed loop.
    role : {"opening", "mark", "tape"}
        Hole kept open, line embedded in the mesh, or load-tape path.
    kind : str
        Opening kind for holes (``feed_hole``, ``vent``, ...).
    provenance : Provenance
        Source entity.
    hem : SeamProperties, optional
        Hem metadata for openings.
    """

    name: str
    points: FloatArray
    closed: bool
    role: LoopKind
    kind: str
    provenance: Provenance
    hem: SeamProperties | None = None
    note: str | None = None


@dataclass(eq=False)
class Instance:
    """One placed copy of a finished piece.

    Attributes
    ----------
    instance_id : str
        ``<ring>/<row>@<gore>`` for ring panels, the part name otherwise.
    piece : FinishedPiece
        Source piece.
    mirrored : bool
        The instance is the mirror image of the drawn piece.
    material_zone : str
        Material zone.
    mesh : bool
        Included in the rest mesh.
    outline : ndarray, shape (n, 2)
        Finished outline in the local frame (counter-clockwise), m.
    edges : dict of str to OutlineEdge
        Named outline edges in the local frame.
    loops : dict of str to InstanceLoop
        Holes, marks and tape paths.
    grain : ndarray, shape (2,), optional
        Unit grain vector in the local frame.
    ring, row, gore
        Ring placement (None for parts).
    reason : str, optional
        Why the instance is excluded from the mesh.
    """

    instance_id: str
    piece: FinishedPiece
    mirrored: bool
    material_zone: str
    mesh: bool
    outline: FloatArray
    edges: dict[str, OutlineEdge]
    loops: dict[str, InstanceLoop]
    grain: FloatArray | None
    ring: str | None = None
    row: str | None = None
    gore: int | None = None
    reason: str | None = None

    @property
    def openings(self) -> list[InstanceLoop]:
        """Hole loops kept open."""
        return [loop for loop in self.loops.values() if loop.role == "opening"]

    @property
    def finished_area(self) -> float:
        """Outline area minus opening areas, m^2."""
        return abs(signed_area(self.outline)) - sum(
            abs(signed_area(loop.points)) for loop in self.openings
        )


@dataclass(frozen=True)
class EdgeUse:
    """A node used in a seam side, optionally traversed backwards."""

    node_id: str
    reversed: bool = False


@dataclass(eq=False)
class GraphNode:
    """A finished edge (or a composite boundary) in the seam graph.

    Attributes
    ----------
    node_id : str
        ``<instance>:<edge>`` or ``<instance>:<loop>``; composite boundaries use
        ``<ring>:<boundary name>``.
    kind : str
        Node kind.
    instance_id : str
        Owning instance ('' for composite boundaries).
    piece_id : str
        Source piece.
    name : str
        Edge or loop name.
    length : float
        Finished length, m.
    closed : bool
        Closed loop (a hole rim, a mark circle or a cornerless outline).
    points : ndarray, shape (n, 2)
        Polyline in the instance local frame, m (closed loops repeat the first vertex).
    measured_allowance : float or None
        Median cut-to-finished distance along the edge, m.
    mirrored : bool
        Owning instance is mirrored.
    provenance : Provenance, optional
        Source entity of the outline or loop.
    members : list of EdgeUse
        For composite boundaries, the member edges.
    """

    node_id: str
    kind: NodeKind
    instance_id: str
    piece_id: str
    name: str
    length: float
    closed: bool
    points: FloatArray
    measured_allowance: float | None
    mirrored: bool
    provenance: Provenance | None
    members: list[EdgeUse] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready dictionary (without geometry)."""
        return {
            "id": self.node_id,
            "kind": self.kind,
            "instance": self.instance_id,
            "piece": self.piece_id,
            "name": self.name,
            "length_m": round(self.length, 6),
            "closed": self.closed,
            "measured_allowance_m": (
                None if self.measured_allowance is None else round(self.measured_allowance, 6)
            ),
            "mirrored": self.mirrored,
            "provenance": self.provenance.as_dict() if self.provenance else None,
            "members": [{"node": m.node_id, "reversed": m.reversed} for m in self.members],
        }


@dataclass(eq=False)
class GraphSeam:
    """A sewn relationship between two node chains (or a one-sided hem).

    Attributes
    ----------
    seam_id : str
        Unique id.
    seam_type : str
        ``horizontal_panel``, ``vertical_gore``, ``reinforcement``, ``appendage``,
        ``rim`` or ``closing``.
    side_a, side_b : list of EdgeUse
        Node chains in sewing order. ``side_b`` is empty for rim seams.
    props : SeamProperties
        Metadata (allowance, stitch rows, load tape, designed ease, order, orientation,
        tolerance).
    mesh : bool
        Joined in the rest mesh (False when an instance is not meshed).
    attachment : bool
        Side A is a line marked on a panel surface (T-junction in the mesh).
    orientation_check : {"ok", "error", "unchecked"}
        Whether the declared orientation agrees with the pattern geometry.
    """

    seam_id: str
    seam_type: SeamType
    side_a: list[EdgeUse]
    side_b: list[EdgeUse]
    props: SeamProperties
    mesh: bool = True
    attachment: bool = False
    orientation_check: str = "unchecked"

    def as_dict(self, graph: SeamGraph) -> dict[str, Any]:
        """JSON-ready dictionary."""
        return {
            "id": self.seam_id,
            "type": self.seam_type,
            "side_a": [{"node": u.node_id, "reversed": u.reversed} for u in self.side_a],
            "side_b": [{"node": u.node_id, "reversed": u.reversed} for u in self.side_b],
            "length_a_m": round(graph.chain_length(self.side_a), 6),
            "length_b_m": round(graph.chain_length(self.side_b), 6),
            "mesh": self.mesh,
            "attachment": self.attachment,
            "orientation": self.props.orientation,
            "orientation_check": self.orientation_check,
            "allowance_a_m": self.props.side_allowance_m("a"),
            "allowance_b_m": self.props.side_allowance_m("b"),
            "stitch_rows": self.props.stitch_rows,
            "stitch": self.props.stitch,
            "load_tape": self.props.load_tape,
            "designed_ease_m": self.props.designed_ease_m,
            "construction_order": self.props.construction_order,
            "tolerance_m": self.props.tolerance_m,
            "notes": self.props.notes,
        }


@dataclass(eq=False)
class Opening:
    """An intended opening: a chain of nodes forming a boundary loop."""

    name: str
    kind: OpeningKind
    uses: list[EdgeUse]
    reason: str | None = None


@dataclass
class SeamGraph:
    """Nodes (finished edges), seams (sewn relationships) and intended openings."""

    nodes: dict[str, GraphNode] = field(default_factory=dict)
    seams: list[GraphSeam] = field(default_factory=list)
    openings: list[Opening] = field(default_factory=list)

    def chain_length(self, chain: list[EdgeUse]) -> float:
        """Total finished length of a node chain, m."""
        return sum(self.nodes[u.node_id].length for u in chain)

    def chain_pieces(self, chain: list[EdgeUse]) -> list[str]:
        """Distinct instance ids along a chain, in order."""
        out: list[str] = []
        for use in chain:
            inst = self.nodes[use.node_id].instance_id
            if inst not in out:
                out.append(inst)
        return out

    def to_json(self) -> str:
        """Serialise the graph (without geometry) as JSON text."""
        return json.dumps(
            {
                "nodes": [n.as_dict() for n in self.nodes.values()],
                "seams": [s.as_dict(self) for s in self.seams],
                "openings": [
                    {
                        "name": o.name,
                        "kind": o.kind,
                        "nodes": [u.node_id for u in o.uses],
                        "reason": o.reason,
                    }
                    for o in self.openings
                ],
            },
            indent=2,
        )

    def to_csv(self) -> str:
        """One row per seam, with readable side descriptions."""
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(
            [
                "seam_id",
                "type",
                "side_a",
                "side_b",
                "length_a_mm",
                "length_b_mm",
                "designed_ease_mm",
                "allowance_a_mm",
                "allowance_b_mm",
                "stitch_rows",
                "load_tape",
                "construction_order",
                "orientation",
                "orientation_check",
                "meshed",
                "attachment",
            ]
        )
        for seam in self.seams:
            allow_a = seam.props.side_allowance_m("a")
            allow_b = seam.props.side_allowance_m("b")
            writer.writerow(
                [
                    seam.seam_id,
                    seam.seam_type,
                    " + ".join(u.node_id for u in seam.side_a),
                    " + ".join(u.node_id for u in seam.side_b),
                    f"{self.chain_length(seam.side_a) * 1e3:.1f}",
                    f"{self.chain_length(seam.side_b) * 1e3:.1f}" if seam.side_b else "",
                    f"{seam.props.designed_ease_mm:.1f}",
                    "" if allow_a is None else f"{allow_a * 1e3:.1f}",
                    "" if allow_b is None else f"{allow_b * 1e3:.1f}",
                    seam.props.stitch_rows,
                    seam.props.load_tape or "",
                    seam.props.construction_order,
                    seam.props.orientation,
                    seam.orientation_check,
                    "yes" if seam.mesh else "no",
                    "yes" if seam.attachment else "no",
                ]
            )
        return buffer.getvalue()


@dataclass
class Assembly:
    """Instances, the seam graph and warnings produced from an assembly spec."""

    spec: AssemblySpec
    instances: dict[str, Instance]
    graph: SeamGraph
    warnings: list[ImportWarning]


# --------------------------------------------------------------------------------------
# Instances
# --------------------------------------------------------------------------------------


def _mirror(points: FloatArray, closed: bool) -> FloatArray:
    out = points * np.array([-1.0, 1.0])
    return np.asarray(out[::-1] if closed else out, dtype=np.float64)


def _start_at_top(loop: FloatArray) -> FloatArray:
    k = int(np.argmax(loop[:, 1] - 1e-9 * loop[:, 0]))
    return np.roll(loop, -k, axis=0)


def _select_feature(piece: FinishedPiece, selector: FeatureSelector, context: str) -> PatternEntity:
    candidates = [e for e in piece.entities.get("feature", []) if e.closed]
    if selector.entity_id is not None:
        candidates = [e for e in candidates if e.provenance.entity_id == selector.entity_id]
    if selector.circle_radius_mm is not None:
        r = selector.circle_radius_mm * 1e-3
        tol = selector.tolerance_mm * 1e-3
        candidates = [e for e in candidates if e.circle is not None and abs(e.circle[2] - r) <= tol]
    if selector.near_mm is not None and candidates:
        target = piece.origin + np.array(selector.near_mm) * 1e-3
        candidates = [min(candidates, key=lambda e: float(np.hypot(*(e.anchor - target))))]
    if not candidates:
        raise AssemblyError(f"{context}: no feature in piece {piece.piece_id} matches {selector}")
    if len(candidates) > 1:
        raise AssemblyError(
            f"{context}: {len(candidates)} features in piece {piece.piece_id} match {selector}; "
            "add near_mm or entity_id to disambiguate"
        )
    return candidates[0]


def make_instance(
    instance_id: str,
    piece: FinishedPiece,
    *,
    mirrored: bool = False,
    material_zone: str | None = None,
    mesh: bool = True,
    ring: str | None = None,
    row: str | None = None,
    gore: int | None = None,
    reason: str | None = None,
) -> Instance:
    """Place a finished piece as an instance in its local frame.

    Parameters
    ----------
    instance_id : str
        Unique instance id.
    piece : FinishedPiece
        Source piece.
    mirrored : bool
        Mirror the piece about its local vertical axis.
    material_zone : str, optional
        Overrides the piece's zone.
    mesh : bool
        Include in the rest mesh.
    ring, row, gore
        Ring placement.
    reason : str, optional
        Why the instance is not meshed.

    Returns
    -------
    Instance
        The instance with named edges, piece holes and tape paths.
    """
    outline = piece.local(piece.outline)
    if mirrored:
        outline = _mirror(outline, closed=True)
    outline = orient_ccw(outline)
    edges = {e.name: e for e in split_edges(outline, piece.corner_angle_deg)}
    loops: dict[str, InstanceLoop] = {}
    for k, hole in enumerate(piece.holes):
        pts = piece.local(hole.finished)
        pts = orient_ccw(_mirror(pts, True) if mirrored else pts)
        loops[f"hole{k}"] = InstanceLoop(
            f"hole{k}", _start_at_top(pts), True, "opening", "feature_opening", hole.provenance
        )
    for k, tape in enumerate(piece.entities.get("tape", [])):
        pts = piece.local(tape.points)
        pts = _mirror(pts, tape.closed) if mirrored else pts
        note = None
        if tape.closed:
            pts = _start_at_top(orient_ccw(pts))
        else:
            clipped = clip_inside(pts, outline, TAPE_EDGE_MARGIN)
            if clipped is None:
                continue
            if len(clipped) != len(pts) or not np.allclose(clipped, pts):
                note = (
                    f"tape line clipped to stay {TAPE_EDGE_MARGIN * 1e3:.0f} mm inside the "
                    "finished outline (tape along seams is carried by the seam metadata)"
                )
            pts = clipped
        loops[f"tape{k}"] = InstanceLoop(
            f"tape{k}", pts, tape.closed, "tape", "tape", tape.provenance, note=note
        )
    grain = None
    if piece.grain is not None:
        grain = np.array(piece.grain) * (np.array([-1.0, 1.0]) if mirrored else 1.0)
    return Instance(
        instance_id=instance_id,
        piece=piece,
        mirrored=mirrored,
        material_zone=material_zone or piece.material_zone,
        mesh=mesh,
        outline=outline,
        edges=edges,
        loops=loops,
        grain=grain,
        ring=ring,
        row=row,
        gore=gore,
        reason=reason,
    )


def _add_feature_loop(
    instance: Instance,
    name: str,
    selector: FeatureSelector,
    role: LoopKind,
    kind: str,
    hem: SeamProperties | None,
) -> None:
    entity = _select_feature(instance.piece, selector, f"{instance.instance_id}:{name}")
    pts = instance.piece.local(entity.points)
    if instance.mirrored:
        pts = _mirror(pts, True)
    pts = _start_at_top(orient_ccw(pts))
    if name in instance.loops or name in instance.edges:
        raise AssemblyError(f"{instance.instance_id}: loop name {name!r} is already used")
    instance.loops[name] = InstanceLoop(name, pts, True, role, kind, entity.provenance, hem)


# --------------------------------------------------------------------------------------
# Graph construction
# --------------------------------------------------------------------------------------


def _edge_allowance(instance: Instance, points: FloatArray) -> float | None:
    piece = instance.piece
    if piece.outline_source != "sew" or len(points) < 2:
        return None
    cut = piece.local(piece.cut_outline)
    if instance.mirrored:
        cut = _mirror(cut, True)
    # Interior vertices only: the corners sit on the corner treatment of the cut line.
    sample = points[1:-1] if len(points) > 2 else (points[:1] + points[-1:]) / 2.0
    return float(np.median(distance_to_polyline(sample, cut, closed=True)))


def _add_instance_nodes(graph: SeamGraph, instance: Instance) -> None:
    piece = instance.piece
    edge_kind: NodeKind = "panel_edge" if piece.kind == "panel" else "feature_edge"
    for name, edge in instance.edges.items():
        node_id = f"{instance.instance_id}:{name}"
        graph.nodes[node_id] = GraphNode(
            node_id=node_id,
            kind=edge_kind,
            instance_id=instance.instance_id,
            piece_id=piece.piece_id,
            name=name,
            length=edge.length,
            closed=edge.closed_loop,
            points=edge.points,
            measured_allowance=_edge_allowance(instance, edge.points),
            mirrored=instance.mirrored,
            provenance=piece.sew_provenance or piece.provenance,
        )
    for loop in instance.loops.values():
        _add_loop_node(graph, instance, loop)


def _add_loop_node(graph: SeamGraph, instance: Instance, loop: InstanceLoop) -> None:
    node_id = f"{instance.instance_id}:{loop.name}"
    pts = np.vstack([loop.points, loop.points[:1]]) if loop.closed else loop.points
    kind: NodeKind = "tape_path" if loop.role == "tape" else "feature_edge"
    graph.nodes[node_id] = GraphNode(
        node_id=node_id,
        kind=kind,
        instance_id=instance.instance_id,
        piece_id=instance.piece.piece_id,
        name=loop.name,
        length=polyline_length(pts),
        closed=loop.closed,
        points=pts,
        measured_allowance=None,
        mirrored=instance.mirrored,
        provenance=loop.provenance,
    )


def _node_for_edge(
    instances: dict[str, Instance], graph: SeamGraph, ref: EdgeRef, context: str
) -> EdgeUse:
    if ref.instance not in instances:
        raise AssemblyError(f"{context}: unknown instance {ref.instance!r}")
    inst = instances[ref.instance]
    name = ref.edge if ref.edge is not None else ref.mark
    assert name is not None
    if ref.edge is not None and ref.edge not in inst.edges:
        raise AssemblyError(
            f"{context}: instance {ref.instance} has no edge {ref.edge!r}; edges: "
            f"{', '.join(inst.edges)} (check corner detection or corner_angle_deg)"
        )
    if ref.mark is not None and ref.mark not in inst.loops:
        raise AssemblyError(
            f"{context}: instance {ref.instance} has no mark {ref.mark!r}; marks: "
            f"{', '.join(inst.loops) or 'none'}"
        )
    return EdgeUse(f"{ref.instance}:{name}", ref.reverse)


def _ring_boundary(ring: RingSpec, which: Literal["bottom", "top"]) -> list[EdgeUse]:
    row = ring.rows[0] if which == "bottom" else ring.rows[-1]
    edge = ring.edges[which]
    uses = [EdgeUse(f"{ring.instance_id(row, g)}:{edge}") for g in ring.gores]
    # Bottom edges run left to right in each panel (gore order); top edges right to left.
    return uses if which == "bottom" else list(reversed(uses))


def _orientation_check(graph: SeamGraph, seam: GraphSeam, instances: dict[str, Instance]) -> str:
    """Compare the declared orientation with the pattern-frame edge directions."""
    if len(seam.side_a) != 1 or len(seam.side_b) != 1:
        return "unchecked"
    na = graph.nodes[seam.side_a[0].node_id]
    nb = graph.nodes[seam.side_b[0].node_id]
    if na.closed or nb.closed:
        return "unchecked"
    ia, ib = instances[na.instance_id], instances[nb.instance_id]
    same_frame = ia is ib or (ia.ring is not None and ia.ring == ib.ring)
    if not same_frame:
        return "unchecked"
    da = na.points[-1] - na.points[0]
    db = nb.points[-1] - nb.points[0]
    if seam.side_a[0].reversed:
        da = -da
    if seam.side_b[0].reversed:
        db = -db
    dot = float(np.dot(da, db))
    expected_negative = seam.props.orientation == "reversed"
    return "ok" if (dot < 0) == expected_negative else "error"


def build_assembly(spec: AssemblySpec, pieces: dict[str, FinishedPiece]) -> Assembly:
    """Create instances and the seam graph from an assembly spec.

    Parameters
    ----------
    spec : AssemblySpec
        Assembly specification.
    pieces : dict of str to FinishedPiece
        Finished pieces keyed by id.

    Returns
    -------
    Assembly
        Instances, seam graph and warnings.
    """
    warnings: list[ImportWarning] = []
    instances: dict[str, Instance] = {}
    graph = SeamGraph()

    def piece(pid: str, context: str) -> FinishedPiece:
        if pid not in pieces:
            raise AssemblyError(f"{context}: unknown piece {pid!r}; known: {', '.join(pieces)}")
        return pieces[pid]

    for ring in spec.rings:
        for row in ring.rows:
            p = piece(row, f"ring {ring.name}")
            if not p.valid:
                raise AssemblyError(f"ring {ring.name}: piece {row} has invalid geometry")
            for gore in ring.gores:
                iid = ring.instance_id(row, gore)
                instances[iid] = make_instance(
                    iid, p, material_zone=ring.material_zone, ring=ring.name, row=row, gore=gore
                )
            missing = [
                ring.edges[s] for s in ring.edges if ring.edges[s] not in instances[iid].edges
            ]
            if missing:
                raise AssemblyError(
                    f"ring {ring.name}: piece {row} has no edge(s) {missing}; detected edges: "
                    f"{', '.join(instances[iid].edges)} (adjust corner_angle_deg)"
                )
    for part in spec.parts:
        p = piece(part.piece, f"part {part.name}")
        if not p.valid and part.mesh:
            raise AssemblyError(f"part {part.name}: piece {part.piece} has invalid geometry")
        instances[part.name] = make_instance(
            part.name,
            p,
            mirrored=part.mirror,
            material_zone=part.material_zone,
            mesh=part.mesh,
            reason=part.reason,
        )
        if not part.mesh:
            warnings.append(
                ImportWarning(
                    "assumption",
                    f"part {part.name} ({part.piece}) is audited but not meshed"
                    + (f": {part.reason}" if part.reason else ""),
                    piece_id=part.piece,
                )
            )

    ring_names = {r.name for r in spec.rings}
    for override in spec.instances:
        sel = override.select
        if sel.ring not in ring_names:
            raise AssemblyError(f"instance override: unknown ring {sel.ring!r}")
        chosen = [
            inst
            for inst in instances.values()
            if inst.ring == sel.ring
            and (not sel.rows or inst.row in sel.rows)
            and (not sel.gores or inst.gore in sel.gores)
        ]
        if not chosen:
            raise AssemblyError(f"instance override selects nothing: {sel}")
        for inst in chosen:
            if override.material_zone is not None:
                inst.material_zone = override.material_zone
            for feat in override.openings:
                _add_feature_loop(inst, feat.name, feat.feature, "opening", feat.kind, feat.hem)
            for feat in override.marks:
                _add_feature_loop(inst, feat.name, feat.feature, "mark", "mark", None)

    for inst in instances.values():
        _add_instance_nodes(graph, inst)
        for loop in inst.loops.values():
            if loop.note is not None:
                warnings.append(
                    ImportWarning(
                        "assumption",
                        f"{inst.instance_id}:{loop.name}: {loop.note}",
                        severity="info",
                        piece_id=inst.piece.piece_id,
                        provenance=loop.provenance,
                    )
                )

    # Ring seams, boundaries and open seams.
    for ring in spec.rings:
        gores = ring.gores
        e = ring.edges
        for gore in gores:
            for lower, upper in zip(ring.rows[:-1], ring.rows[1:], strict=True):
                graph.seams.append(
                    GraphSeam(
                        f"{ring.name}:h:{lower}/{upper}@{gore}",
                        "horizontal_panel",
                        [EdgeUse(f"{ring.instance_id(lower, gore)}:{e['top']}")],
                        [EdgeUse(f"{ring.instance_id(upper, gore)}:{e['bottom']}")],
                        ring.horizontal_seam,
                    )
                )
        open_rows: dict[tuple[int, int], tuple[str, set[str]]] = {}
        for open_seam in ring.open_seams:
            g1, g2 = open_seam.gores
            if g1 not in gores or g2 not in gores:
                raise AssemblyError(f"open seam {open_seam.name}: gores {open_seam.gores} unknown")
            if gores[(gores.index(g1) + 1) % len(gores)] != g2:
                raise AssemblyError(
                    f"open seam {open_seam.name}: gores {g1} and {g2} are not neighbours in "
                    "ring order (list the left gore first)"
                )
            unknown_rows = set(open_seam.rows) - set(ring.rows)
            if unknown_rows:
                raise AssemblyError(f"open seam {open_seam.name}: unknown rows {unknown_rows}")
            open_rows[(g1, g2)] = (open_seam.name, set(open_seam.rows))
            rows_in_order = [r for r in ring.rows if r in open_seam.rows]
            left = [EdgeUse(f"{ring.instance_id(r, g1)}:{e['right']}") for r in rows_in_order]
            right = [
                EdgeUse(f"{ring.instance_id(r, g2)}:{e['left']}") for r in reversed(rows_in_order)
            ]
            graph.openings.append(Opening(open_seam.name, open_seam.kind, left + right))
            if open_seam.hem is not None:
                graph.seams.append(
                    GraphSeam(
                        f"{ring.name}:rim:{open_seam.name}", "rim", left + right, [], open_seam.hem
                    )
                )
        for k, gore in enumerate(gores):
            nxt = gores[(k + 1) % len(gores)]
            name_rows = open_rows.get((gore, nxt))
            for row in ring.rows:
                if name_rows is not None and row in name_rows[1]:
                    continue
                graph.seams.append(
                    GraphSeam(
                        f"{ring.name}:v:{gore}/{nxt}:{row}",
                        "vertical_gore",
                        [EdgeUse(f"{ring.instance_id(row, gore)}:{e['right']}")],
                        [EdgeUse(f"{ring.instance_id(row, nxt)}:{e['left']}")],
                        ring.vertical_seam,
                    )
                )
        for which, boundary in (("bottom", ring.bottom), ("top", ring.top)):
            uses = _ring_boundary(ring, which)  # type: ignore[arg-type]
            kind: NodeKind = (
                "mouth_boundary"
                if boundary.kind == "mouth"
                else "parachute_boundary"
                if boundary.kind == "parachute_opening"
                else "opening_boundary"
            )
            node_id = f"{ring.name}:{boundary.name}"
            graph.nodes[node_id] = GraphNode(
                node_id=node_id,
                kind=kind,
                instance_id="",
                piece_id=ring.rows[0] if which == "bottom" else ring.rows[-1],
                name=boundary.name,
                length=graph.chain_length(uses),
                closed=True,
                points=np.zeros((0, 2)),
                measured_allowance=None,
                mirrored=False,
                provenance=None,
                members=uses,
            )
            graph.openings.append(Opening(boundary.name, boundary.kind, uses))
            if boundary.hem is not None:
                graph.seams.append(
                    GraphSeam(f"{ring.name}:rim:{boundary.name}", "rim", uses, [], boundary.hem)
                )

    # Holes and feature openings inside instances.
    for inst in instances.values():
        for loop in inst.openings:
            use = EdgeUse(f"{inst.instance_id}:{loop.name}")
            reason = "hole drawn in the pattern" if loop.name.startswith("hole") else None
            graph.openings.append(
                Opening(f"{inst.instance_id}:{loop.name}", loop.kind, [use], reason)  # type: ignore[arg-type]
            )
            if loop.hem is not None:
                graph.seams.append(
                    GraphSeam(f"{inst.instance_id}:rim:{loop.name}", "rim", [use], [], loop.hem)
                )

    for seam_spec in spec.seams:
        sides: list[list[EdgeUse]] = []
        for side in (seam_spec.a, seam_spec.b):
            chain: list[EdgeUse] = []
            for ref in side:
                if isinstance(ref, RingBoundaryRef):
                    ring_ref = next((r for r in spec.rings if r.name == ref.ring), None)
                    if ring_ref is None:
                        raise AssemblyError(f"seam {seam_spec.name}: unknown ring {ref.ring!r}")
                    chain.extend(_ring_boundary(ring_ref, ref.boundary))
                else:
                    chain.append(_node_for_edge(instances, graph, ref, f"seam {seam_spec.name}"))
            sides.append(chain)
        meshed = all(
            instances[graph.nodes[u.node_id].instance_id].mesh for u in sides[0] + sides[1]
        )
        props = SeamProperties.model_validate(
            seam_spec.model_dump(include=set(SeamProperties.model_fields))
        )
        graph.seams.append(
            GraphSeam(
                seam_spec.name,
                seam_spec.type,
                sides[0],
                sides[1],
                props,
                mesh=meshed,
                attachment=seam_spec.attachment,
            )
        )
    # A hole whose rim is sewn to an appendage (a feed hole under a pod or tube) is covered:
    # it stays a hole in the panel but is no longer an open boundary of the envelope.
    sewn = {
        u.node_id
        for s in graph.seams
        if s.seam_type != "rim" and s.side_b
        for u in s.side_a + s.side_b
    }
    graph.openings = [
        o
        for o in graph.openings
        if not (len(o.uses) == 1 and o.uses[0].node_id in sewn and o.name == o.uses[0].node_id)
    ]
    for opening in spec.openings:
        uses = [
            _node_for_edge(instances, graph, ref, f"opening {opening.name}")
            for ref in opening.edges
        ]
        graph.openings.append(Opening(opening.name, opening.kind, uses, opening.reason))
        if opening.hem is not None:
            graph.seams.append(GraphSeam(f"rim:{opening.name}", "rim", uses, [], opening.hem))

    for seam in graph.seams:
        if seam.seam_type != "rim":
            seam.orientation_check = _orientation_check(graph, seam, instances)

    if math.isnan(sum(n.length for n in graph.nodes.values())):
        raise AssemblyError("seam graph contains an edge of undefined length")
    return Assembly(spec, instances, graph, warnings)
