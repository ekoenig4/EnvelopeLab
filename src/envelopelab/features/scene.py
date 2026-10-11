"""3D scene of an envelope with its special shapes, as designed and as simulated.

The objects are triangle meshes in the envelope frame (m, :math:`z` up, the mouth's
axis on :math:`z`) ready for :func:`envelopelab.io.blender.write_obj_scene`:

* ``envelope``: the surface of revolution of the load-tape meridian, one ring of quads
  per profile sample and gore-aligned meridians (the lobe bulge is not drawn);
* ``<name> designed``: the shape's designed skin (the tessellated surface of a dome,
  tube or revolved shape with its tip disc, or the clipped mesh of a free-form shape);
* ``<name> simulated``: the skin of a solved sub-model (preview or CalculiX), moved from
  the sub-model's frame back onto the envelope; only a converged result is a prediction.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
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


def export_scene(
    path: str | Path,
    surface: EnvelopeSurface,
    designs: Sequence[PrimitiveDesign] = (),
    solved: Sequence[tuple[PrimitiveDesign, AppendageModel, SimulationResult]] = (),
    up: UpAxis = "Y",
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

    Returns
    -------
    Path
        The written file.
    """
    objects = [envelope_object(surface)]
    objects += [designed_object(d) for d in designs]
    objects += [simulated_object(d, a, r) for d, a, r in solved]
    return write_obj_scene(path, objects, up)
