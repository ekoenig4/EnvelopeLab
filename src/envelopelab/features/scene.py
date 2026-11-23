r"""3D scene of an envelope with its special shapes, as designed and as simulated.

The objects are triangle meshes in the envelope frame (m, :math:`z` up, the mouth's
axis on :math:`z`) ready for :func:`envelopelab.io.blender.write_obj_scene`:

* ``envelope``: the surface of revolution of the load-tape meridian, one ring of quads
  per profile sample and gore-aligned meridians (the lobe bulge is not drawn);
* ``<name> designed``: the shape's designed skin (the tessellated surface of a dome,
  tube or revolved shape with its tip disc, or the clipped mesh of a free-form shape);
* ``<name> simulated``: the skin of a solved sub-model (preview or CalculiX), moved from
  the sub-model's frame back onto the envelope; only a converged result is a prediction.

:func:`designed_display` and :func:`simulated_display` give the same skins split into
their cut pieces (the piece of every triangle) with the lines where the pieces are sewn,
for drawing a shape as it is sewn: piece :math:`k` is the wedge between the skin seams at
:math:`\phi_k` and :math:`\phi_{k+1}` round the shape's axis (the seams of every
primitive kind and of a free-form mesh lie on half-planes through the axis), and a tube's
or revolved shape's flat tip disc is piece :math:`m`.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from envelopelab.io.blender import MeshObject, UpAxis, write_obj_scene
from envelopelab.solvers.membrane import FloatArray, IntArray

if TYPE_CHECKING:
    from envelopelab.features.builder import AppendageModel
    from envelopelab.features.primitives import EnvelopeSurface, PrimitiveDesign
    from envelopelab.solvers.simulation import SimulationResult


def _grid(points: FloatArray, rows: int, cols: int, periodic: bool) -> IntArray:
    """Two triangles per quad of a (rows x cols) point grid (row-major)."""
    tris = []
    last = cols if periodic else cols - 1
    for i in range(rows - 1):
        for j in range(last):
            a, b = i * cols + j, i * cols + (j + 1) % cols
            c, d = a + cols, b + cols
            tris += [[a, b, d], [a, d, c]]
    return np.asarray(tris, dtype=np.int64)


def envelope_object(surface: EnvelopeSurface, rings: int = 120, per_gore: int = 8) -> MeshObject:
    """The envelope surface, m.

    Parameters
    ----------
    surface : EnvelopeSurface
        Envelope.
    rings : int
        Profile samples from mouth to crown.
    per_gore : int
        Segments across each gore.

    Returns
    -------
    MeshObject
        ``envelope``.
    """
    s = np.linspace(0.0, surface.profile.meridian_length, rings)
    th = np.linspace(0.0, 2 * math.pi, surface.gore_count * per_gore, endpoint=False)
    ss, tt = np.meshgrid(s, th, indexing="ij")
    pts = surface.point(ss.ravel(), tt.ravel())
    return MeshObject("envelope", pts, _grid(pts, rings, len(th), True))


def designed_object(design: PrimitiveDesign, rows: int = 60, per_piece: int = 16) -> MeshObject:
    """The designed skin of a placed shape, m (``<name> designed``)."""
    name = f"{design.primitive.name} designed"
    skin = design._skin
    mesh_tri = getattr(skin, "tri", None)
    if mesh_tri is not None:  # a free-form mesh: its clipped mesh is the designed skin
        return MeshObject(name, np.array(getattr(skin, "x", None)), np.array(mesh_tri))
    cols = design.primitive.pieces * per_piece
    t = np.linspace(0.0, 1.0, rows)
    ph = np.linspace(0.0, 2 * math.pi, cols, endpoint=False)
    tt, pp = np.meshgrid(t, ph, indexing="ij")
    pts = skin.at(tt.ravel(), pp.ravel())
    tri = _grid(pts, rows, cols, True)
    if design.primitive.closed_tip:
        centre = _cap_centre(design)
        c = len(pts)
        pts = np.vstack([pts, centre])
        top = (rows - 1) * cols
        fan = [[top + (j + 1) % cols, top + j, c] for j in range(cols)]
        # The tip disc faces out along the axis.
        tri = np.vstack([tri, np.asarray(fan, dtype=np.int64)[:, ::-1]])
    return MeshObject(name, pts, tri)


def to_envelope_frame(design: PrimitiveDesign, positions: FloatArray) -> FloatArray:
    """Sub-model positions (host frame, m) back in the envelope frame, m."""
    p = np.asarray(positions, dtype=np.float64).reshape(-1, 3).copy()
    r0, _ = design.surface.radius_height(np.array([design.base_s]))
    p[:, 0] += float(r0[0])
    c, s = math.cos(design.base_theta), math.sin(design.base_theta)
    return np.column_stack([p[:, 0] * c - p[:, 1] * s, p[:, 0] * s + p[:, 1] * c, p[:, 2]])


def simulated_object(
    design: PrimitiveDesign, appendage: AppendageModel, result: SimulationResult
) -> MeshObject:
    """The solved skin of a shape on the envelope, m (``<name> simulated``).

    The object name says ``unconverged`` when the solve did not converge.
    """
    tri = appendage.model.triangles[appendage.skin_triangles]
    used = np.unique(tri)
    remap = np.full(len(result.positions), -1, dtype=np.int64)
    remap[used] = np.arange(len(used))
    pts = to_envelope_frame(design, result.positions[used])
    state = "simulated" if result.converged else "simulated UNCONVERGED"
    return MeshObject(f"{design.primitive.name} {state}", pts, remap[tri])


@dataclass
class ShapeDisplay:
    """A shape's skin split into its cut pieces, for drawing it as sewn.

    Attributes
    ----------
    points : ndarray, shape (n, 3)
        Skin vertices in the envelope frame, m.
    triangles : ndarray of int, shape (t, 3)
        Skin triangles.
    piece : ndarray of int, shape (t,)
        Cut piece of every triangle: 0 .. m-1 for the gores or panels in order round the
        axis (every tier of a split shape alike; the splits are drawn as seams), m for a
        flat tip disc.
    pieces : int
        Number of gores or panels m.
    seams : list of ndarray
        Sewn lines (each shape (k, 3), m): every skin seam from the rim to the pole or tip,
        every horizontal split, and the tip seam of a tip disc.
    rim : ndarray, shape (r, 3)
        The rim, sewn to the envelope along the footprint (closed: first point repeated), m.
    tier : ndarray of int, shape (t,) or None
        Tier of every triangle from the rim, from 0, by the meridian position of its
        centre and the horizontal splits (display only: a triangle that straddles a split
        takes the tier of its centre); None: every triangle in the first tier.
    """

    points: FloatArray
    triangles: IntArray
    piece: IntArray
    pieces: int
    seams: list[FloatArray] = field(default_factory=list)
    rim: FloatArray = field(default_factory=lambda: np.zeros((0, 3)))
    tier: IntArray | None = None


def _piece_of(
    design: PrimitiveDesign, centroids: FloatArray, tip: np.ndarray | None = None
) -> IntArray:
    """Cut piece of points by their angle round the axis (and the tip-disc mask)."""
    from envelopelab.features.primitives import _seams

    prim = design.primitive
    m = prim.pieces
    seams = _seams(prim)
    # About the seam line: a mesh shape's moved meeting point shifts it off the axis.
    origin = (
        getattr(design._skin, "base", design.base_point)
        if prim.kind == "mesh"
        else design.base_point
    )
    rel = centroids - origin
    phi = np.arctan2(rel @ design.b2, rel @ design.b1)
    rel_phi = np.mod(phi - seams[0], 2.0 * math.pi)
    out: IntArray
    if prim.panel_widths:
        out = np.minimum(np.searchsorted(seams - seams[0], rel_phi, side="right") - 1, m - 1)
    else:
        out = np.minimum((rel_phi // (2.0 * math.pi / m)).astype(np.int64), m - 1)
    if tip is not None:
        out[tip] = m
    return out


def _cap_centre(design: PrimitiveDesign) -> FloatArray:
    """Centre of a shape's cap (moved off the tip or not), m."""
    shaped = getattr(design._skin, "_crown", None)
    if shaped is not None:  # where the panels meet, on the skin (ADR-0054)
        point: FloatArray = shaped.point
        return point
    if getattr(design._skin, "_cap", None) is not None:
        origin: FloatArray = design._skin.cap_frame()[0]
        return origin
    out: FloatArray = design.base_point + design.primitive.tip_height * design.axis
    return out


def designed_display(design: PrimitiveDesign, rows: int = 60, per_piece: int = 16) -> ShapeDisplay:
    """The designed skin of a placed shape with its pieces and seams, m.

    Parameters
    ----------
    design : PrimitiveDesign
        Placed shape.
    rows, per_piece : int
        Tessellation of a parametric skin (:func:`designed_object`).

    Returns
    -------
    ShapeDisplay
        Envelope frame, m.
    """
    from envelopelab.features.primitives import _seams, split_heights

    prim = design.primitive
    skin = design._skin
    m = prim.pieces
    ph = np.linspace(0.0, 2.0 * math.pi, max(m * per_piece, 64) + 1)
    rim = skin.rim_points(ph)
    panels = getattr(skin, "panels", None)
    if panels is not None:  # free-form: the clipped mesh; each panel's left run is a seam
        obj = designed_object(design)
        cen = obj.vertices[obj.triangles].mean(axis=1)
        seams = [np.asarray(p.x[p.left], dtype=np.float64) for p in panels]
        cap = getattr(skin, "cap", None)
        tip = None
        if cap is not None:
            tip = np.asarray(skin.cap_mask, dtype=bool)
            seams.append(np.asarray(cap.x[[*cap.top, cap.top[0]]], dtype=np.float64))
        return ShapeDisplay(obj.vertices, obj.triangles, _piece_of(design, cen, tip), m, seams, rim)
    # Parametric skin: a grid whose columns start on the first seam, so every piece is a
    # whole number of columns (designed_object's grid starts at phi = 0).
    cols = m * per_piece
    seams_phi = _seams(prim)
    t = np.linspace(0.0, 1.0, rows)
    if prim.panel_widths:
        phi = np.concatenate(
            [
                np.linspace(seams_phi[k], seams_phi[k + 1], per_piece, endpoint=False)
                for k in range(m)
            ]
        )
    else:
        phi = seams_phi[0] + np.linspace(0.0, 2.0 * math.pi, cols, endpoint=False)
    tt, pp = np.meshgrid(t, phi, indexing="ij")
    pts = skin.at(tt.ravel(), pp.ravel())
    tri = _grid(pts, rows, cols, True)
    # _grid writes two triangles per quad, row by row, column by column.
    column = np.repeat(np.tile(np.arange(cols), rows - 1), 2)
    piece = (column // per_piece).astype(np.int64)
    heights = split_heights(prim, skin.total)
    if len(heights):
        u = np.asarray(skin.u_of(tt.ravel(), pp.ravel()), dtype=np.float64)
        tier = np.searchsorted(heights, u[tri].mean(axis=1), side="right").astype(np.int64)
    else:
        tier = np.zeros(len(tri), dtype=np.int64)
    seams = [skin.at(t, np.full(rows, float(p))) for p in seams_phi[:-1]]
    # Horizontal splits: circles round the skin at their meridian arc lengths.
    around = seams_phi[0] + np.linspace(0.0, 2.0 * math.pi, cols + 1)
    seams += [skin.at_u(np.full(len(around), u), around) for u in split_heights(prim, skin.total)]
    if prim.closed_tip and getattr(skin, "_crown", None) is not None:
        # A shaped cap (ADR-0054): the skin it is cut from, as is.
        cx, ctri, _loop, _ang = skin.crown_mesh()
        c = len(pts)
        pts = np.vstack([pts, cx])
        tri = np.vstack([tri, ctri + c])
        piece = np.concatenate([piece, np.full(len(ctri), m, dtype=np.int64)])
        tier = np.concatenate([tier, np.full(len(ctri), len(heights), dtype=np.int64)])
        ring = seams_phi[0] + np.linspace(0.0, 2.0 * math.pi, cols + 1)
        seams.append(skin.at(np.ones(len(ring)), ring))
    elif prim.closed_tip:
        centre = _cap_centre(design)
        c = len(pts)
        pts = np.vstack([pts, centre])
        top = (rows - 1) * cols
        fan = np.asarray([[top + (j + 1) % cols, top + j, c] for j in range(cols)], dtype=np.int64)
        tri = np.vstack([tri, fan[:, ::-1]])
        piece = np.concatenate([piece, np.full(cols, m, dtype=np.int64)])
        tier = np.concatenate([tier, np.full(cols, len(heights), dtype=np.int64)])
        ring = seams_phi[0] + np.linspace(0.0, 2.0 * math.pi, cols + 1)
        seams.append(skin.at(np.ones(len(ring)), ring))
    return ShapeDisplay(pts, tri, piece, m, seams, rim, tier)


def _chains(edges: IntArray) -> list[list[int]]:
    """Node chains of a set of mesh edges (open or closed)."""
    nbr: dict[int, list[int]] = {}
    for a, b in np.asarray(edges, dtype=np.int64).reshape(-1, 2):
        nbr.setdefault(int(a), []).append(int(b))
        nbr.setdefault(int(b), []).append(int(a))
    seen: set[tuple[int, int]] = set()
    out: list[list[int]] = []
    starts = [n for n, v in nbr.items() if len(v) != 2] + list(nbr)
    for start in starts:
        for first in nbr[start]:
            if (start, first) in seen:
                continue
            chain, prev, cur = [start], start, first
            seen |= {(start, first), (first, start)}
            while True:
                chain.append(cur)
                nxt = [n for n in nbr[cur] if n != prev and (cur, n) not in seen]
                if len(nbr[cur]) != 2 or not nxt:
                    break
                prev, cur = cur, nxt[0]
                seen |= {(prev, cur), (cur, prev)}
            out.append(chain)
    return out


def _point_triangle_distance(
    p: FloatArray, a: FloatArray, b: FloatArray, c: FloatArray
) -> FloatArray:
    """Distance of points ``p`` from triangles ``(a, b, c)`` (row by row), m."""
    ab, ac, ap = b - a, c - a, p - a
    normal = np.cross(ab, ac)
    area2 = np.einsum("ij,ij->i", normal, normal)
    unit = normal / np.sqrt(np.maximum(area2, 1e-300))[:, None]
    height = np.einsum("ij,ij->i", ap, unit)
    q = p - height[:, None] * unit  # projection onto the plane
    # Barycentric coordinates of the projection.
    v0, v1, v2 = ab, ac, q - a
    d00 = np.einsum("ij,ij->i", v0, v0)
    d01 = np.einsum("ij,ij->i", v0, v1)
    d11 = np.einsum("ij,ij->i", v1, v1)
    d20 = np.einsum("ij,ij->i", v2, v0)
    d21 = np.einsum("ij,ij->i", v2, v1)
    denom = np.maximum(d00 * d11 - d01 * d01, 1e-300)
    v = (d11 * d20 - d01 * d21) / denom
    w = (d00 * d21 - d01 * d20) / denom
    inside = (v >= 0.0) & (w >= 0.0) & (v + w <= 1.0)

    def segment(x: FloatArray, y: FloatArray) -> FloatArray:
        d = y - x
        t = np.clip(
            np.einsum("ij,ij->i", p - x, d) / np.maximum(np.einsum("ij,ij->i", d, d), 1e-300),
            0.0,
            1.0,
        )
        out: FloatArray = np.linalg.norm(p - (x + t[:, None] * d), axis=1)
        return out

    edge = np.minimum(np.minimum(segment(a, b), segment(b, c)), segment(c, a))
    out: FloatArray = np.where(inside, np.abs(height), edge)
    return out


def designed_labels(
    designed: ShapeDisplay, points: FloatArray, candidates: int = 12
) -> tuple[IntArray, IntArray | None]:
    """Piece and tier of the designed skin's triangle nearest each point.

    Parameters
    ----------
    designed : ShapeDisplay
        The designed display (:func:`designed_display`), envelope frame, m.
    points : ndarray, shape (k, 3)
        Points on (or near) the designed skin, m.
    candidates : int
        Designed triangles (by nearest centre) among which the nearest by true
        point-to-triangle distance is taken.

    Returns
    -------
    (ndarray of int, ndarray of int or None)
        Piece (``pieces`` for the cap or tip disc) and tier of each point (None when the
        designed display has no tiers).
    """
    from scipy.spatial import cKDTree

    corners = designed.points[designed.triangles]
    centres = corners.mean(axis=1)
    k = min(candidates, len(centres))
    _, near = cKDTree(centres).query(np.asarray(points, dtype=np.float64), k=k)
    near = np.asarray(near, dtype=np.int64).reshape(len(points), k)
    p = np.repeat(np.asarray(points, dtype=np.float64), k, axis=0)
    flat = near.ravel()
    dist = _point_triangle_distance(
        p, corners[flat, 0], corners[flat, 1], corners[flat, 2]
    ).reshape(len(points), k)
    best = near[np.arange(len(points)), np.argmin(dist, axis=1)]
    piece: IntArray = np.asarray(designed.piece, dtype=np.int64)[best]
    tier: IntArray | None = (
        None if designed.tier is None else np.asarray(designed.tier, dtype=np.int64)[best]
    )
    return piece, tier


def simulated_display(
    design: PrimitiveDesign, appendage: AppendageModel, result: SimulationResult
) -> ShapeDisplay:
    """The solved skin of a shape with its pieces and seams, on the envelope, m.

    Pieces, tiers and the cap are told apart by where each triangle starts (the
    sub-model's designed initial shape): each takes those of the designed skin's triangle
    it starts on (:func:`designed_labels`), so the colouring is the designed one and
    follows the cloth however far the solve moves it.

    Parameters
    ----------
    design : PrimitiveDesign
        The placed shape that was solved.
    appendage : AppendageModel
        Its sub-model.
    result : SimulationResult
        The solve (only a converged one is a prediction).

    Returns
    -------
    ShapeDisplay
        Envelope frame, m.
    """
    model = appendage.model
    tri = model.triangles[appendage.skin_triangles]
    used = np.unique(tri)
    remap = np.full(len(result.positions), -1, dtype=np.int64)
    remap[used] = np.arange(len(used))
    start = to_envelope_frame(design, model.positions)
    cen = start[tri].mean(axis=1)
    prim = design.primitive
    # Each triangle is the designed skin's where it starts: its piece, tier and cap are
    # those of the designed display (exact for every kind, split and cap shape).
    piece, tier = designed_labels(designed_display(design), cen)
    pts = to_envelope_frame(design, result.positions)
    name = prim.name
    seams = [
        pts[chain]
        for s in model.seams
        if s.name.startswith((f"{name}:seam", f"{name}:split")) or s.name == f"{name}:tip seam"
        for chain in _chains(s.edges)
    ]
    rim_nodes = np.asarray(appendage.rim_nodes, dtype=np.int64)
    rim = pts[np.append(rim_nodes, rim_nodes[:1])]
    return ShapeDisplay(pts[used], remap[tri], piece, prim.pieces, seams, rim, tier)


def export_scene(
    path: str | Path,
    surface: EnvelopeSurface,
    designs: Sequence[PrimitiveDesign] = (),
    solved: Sequence[tuple[PrimitiveDesign, AppendageModel, SimulationResult]] = (),
    up: UpAxis = "Y",
    objects: Sequence[MeshObject] = (),
) -> Path:
    """Write the envelope, its shapes and their solved skins as one OBJ scene.

    Parameters
    ----------
    path : str or Path
        Output ``.obj`` file.
    surface : EnvelopeSurface
        Envelope.
    designs : sequence of PrimitiveDesign
        Shapes as designed.
    solved : sequence of (PrimitiveDesign, AppendageModel, SimulationResult)
        Solved sub-models.
    up : {"Y", "Z"}
        Up axis of the file ("Y": Blender's default OBJ import).
    objects : sequence of MeshObject
        More objects, written last (e.g. kept simulations, :func:`display_object`).

    Returns
    -------
    Path
        The written file.
    """
    scene = [envelope_object(surface)]
    scene += [designed_object(d) for d in designs]
    scene += [simulated_object(d, a, r) for d, a, r in solved]
    scene += list(objects)
    return write_obj_scene(path, scene, up)


def display_object(name: str, display: ShapeDisplay, converged: bool) -> MeshObject:
    """A solved shape's display skin as an object (``<name> simulated``, marked
    ``UNCONVERGED`` when the solve did not converge), m."""
    state = "simulated" if converged else "simulated UNCONVERGED"
    return MeshObject(f"{name} {state}", display.points, display.triangles)
