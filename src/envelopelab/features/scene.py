"""3D scene of an envelope with its special shapes, as designed and as simulated.

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
        centre = design.base_point + design.primitive.tip_height * design.axis
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
        axis, m for a flat tip disc.
    pieces : int
        Number of gores or panels m.
    seams : list of ndarray
        Sewn lines (each shape (k, 3), m): every skin seam from the rim to the pole or tip,
        and the tip seam of a tip disc.
    rim : ndarray, shape (r, 3)
        The rim, sewn to the envelope along the footprint (closed: first point repeated), m.
    """

    points: FloatArray
    triangles: IntArray
    piece: IntArray
    pieces: int
    seams: list[FloatArray] = field(default_factory=list)
    rim: FloatArray = field(default_factory=lambda: np.zeros((0, 3)))


def _piece_of(
    design: PrimitiveDesign, centroids: FloatArray, tip: np.ndarray | None = None
) -> IntArray:
    """Cut piece of points by their angle round the axis (and the tip-disc mask)."""
    from envelopelab.features.primitives import _seams

    prim = design.primitive
    m = prim.pieces
    seams = _seams(prim)
    rel = centroids - design.base_point
    phi = np.arctan2(rel @ design.b2, rel @ design.b1)
    width = 2.0 * math.pi / m
    out: IntArray = np.minimum(
        (np.mod(phi - seams[0], 2.0 * math.pi) // width).astype(np.int64), m - 1
    )
    if tip is not None:
        out[tip] = m
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
    from envelopelab.features.primitives import _seams

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
        return ShapeDisplay(obj.vertices, obj.triangles, _piece_of(design, cen), m, seams, rim)
    # Parametric skin: a grid whose columns start on the first seam, so every piece is a
    # whole number of columns (designed_object's grid starts at phi = 0).
    cols = m * per_piece
    seams_phi = _seams(prim)
    t = np.linspace(0.0, 1.0, rows)
    phi = seams_phi[0] + np.linspace(0.0, 2.0 * math.pi, cols, endpoint=False)
    tt, pp = np.meshgrid(t, phi, indexing="ij")
    pts = skin.at(tt.ravel(), pp.ravel())
    tri = _grid(pts, rows, cols, True)
    # _grid writes two triangles per quad, row by row, column by column.
    column = np.repeat(np.tile(np.arange(cols), rows - 1), 2)
    piece = (column // per_piece).astype(np.int64)
    seams = [skin.at(t, np.full(rows, float(p))) for p in seams_phi[:-1]]
    if prim.closed_tip:
        centre = design.base_point + prim.tip_height * design.axis
        c = len(pts)
        pts = np.vstack([pts, centre])
        top = (rows - 1) * cols
        fan = np.asarray([[top + (j + 1) % cols, top + j, c] for j in range(cols)], dtype=np.int64)
        tri = np.vstack([tri, fan[:, ::-1]])
        piece = np.concatenate([piece, np.full(cols, m, dtype=np.int64)])
        ring = seams_phi[0] + np.linspace(0.0, 2.0 * math.pi, cols + 1)
        seams.append(skin.at(np.ones(len(ring)), ring))
    return ShapeDisplay(pts, tri, piece, m, seams, rim)


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


def simulated_display(
    design: PrimitiveDesign, appendage: AppendageModel, result: SimulationResult
) -> ShapeDisplay:
    """The solved skin of a shape with its pieces and seams, on the envelope, m.

    Pieces are told apart by where each triangle starts (the sub-model's designed initial
    shape), so the colouring follows the cloth however far the solve moves it.

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
    tip = None
    if prim.closed_tip:
        height = (cen - design.base_point) @ design.axis
        tip = height > prim.tip_height - 1e-6 * max(prim.tip_height, 1.0)
    piece = _piece_of(design, cen, tip)
    pts = to_envelope_frame(design, result.positions)
    name = prim.name
    seams = [
        pts[chain]
        for s in model.seams
        if s.name.startswith(f"{name}:seam") or s.name == f"{name}:tip seam"
        for chain in _chains(s.edges)
    ]
    rim_nodes = np.asarray(appendage.rim_nodes, dtype=np.int64)
    rim = pts[np.append(rim_nodes, rim_nodes[:1])]
    return ShapeDisplay(pts[used], remap[tri], piece, prim.pieces, seams, rim)


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
