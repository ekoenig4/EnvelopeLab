"""3D mesh exchange with Blender: OBJ scenes out, OBJ/STL/PLY shapes in.

Axes
----
EnvelopeLab works in metres with :math:`z` up. Blender's OBJ importer and exporter
default to *forward -Z, up Y*, so an OBJ file is written and read with :math:`y` up:

.. math:: (x, y, z)_{OBJ} = (x,\\ z,\\ -y)_{EnvelopeLab}

and a model saved from Blender with the default settings comes back the right way up.
STL and PLY default to *forward Y, up Z* in Blender and are written and read with
:math:`z` up (no change). Blender's unit is the metre (unit scale 1), so no scaling is
applied; use ``scale`` when reading a model built in other units.

Each object (envelope, each shape as designed, each shape as simulated) is a named
``o`` block, so the scene opens in Blender as separate objects.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np

from envelopelab.io.reference_mesh import ReferenceMesh, read_mesh, write_stl
from envelopelab.solvers.membrane import FloatArray, IntArray

UpAxis = Literal["Y", "Z"]


@dataclass(frozen=True)
class MeshObject:
    """A named triangle mesh (m, :math:`z` up)."""

    name: str
    vertices: FloatArray
    triangles: IntArray


def to_obj_axes(points: FloatArray) -> FloatArray:
    """EnvelopeLab (z up) to OBJ (y up) coordinates, m."""
    p = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    return np.column_stack([p[:, 0], p[:, 2], -p[:, 1]])


def from_obj_axes(points: FloatArray) -> FloatArray:
    """OBJ (y up) to EnvelopeLab (z up) coordinates, m."""
    p = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    return np.column_stack([p[:, 0], -p[:, 2], p[:, 1]])


def write_obj_scene(path: str | Path, objects: Sequence[MeshObject], up: UpAxis = "Y") -> Path:
    """Write several meshes as one OBJ file, one named object each.

    Parameters
    ----------
    path : str or Path
        Output ``.obj`` file.
    objects : sequence of MeshObject
        Meshes, m, :math:`z` up.
    up : {"Y", "Z"}
        Up axis of the file ("Y": Blender's default OBJ import).

    Returns
    -------
    Path
        The written file.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# EnvelopeLab scene, units m, " + ("Y up (Blender default)" if up == "Y" else "Z up")]
    offset = 1
    for obj in objects:
        v = to_obj_axes(obj.vertices) if up == "Y" else np.asarray(obj.vertices, float)
        lines.append(f"o {obj.name.replace(' ', '_')}")
        lines += [f"v {x:.6f} {y:.6f} {z:.6f}" for x, y, z in v]
        lines += [f"f {a + offset} {b + offset} {c + offset}" for a, b, c in obj.triangles]
        offset += len(v)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def write_stl_object(path: str | Path, obj: MeshObject) -> Path:
    """Write one mesh as binary STL (m, :math:`z` up, Blender's default STL axes)."""
    return write_stl(path, ReferenceMesh(np.asarray(obj.vertices, float), obj.triangles))


def read_shape_mesh(
    path: str | Path, scale: float = 1.0, up: UpAxis | None = None
) -> ReferenceMesh:
    """Read a shape modelled in Blender (or any OBJ/STL/PLY tool) as a :math:`z`-up mesh.

    Parameters
    ----------
    path : str or Path
        ``.obj``, ``.stl`` or ``.ply`` file.
    scale : float
        Metres per file unit (1 for Blender's default metres).
    up : {"Y", "Z"}, optional
        Up axis of the file; default "Y" for OBJ (Blender's default export) and "Z" for
        STL and PLY.

    Returns
    -------
    ReferenceMesh
        Vertices in m with :math:`z` up.
    """
    mesh = read_mesh(path, scale)
    axis = up or ("Y" if Path(path).suffix.lower() == ".obj" else "Z")
    if axis == "Y":
        return ReferenceMesh(from_obj_axes(mesh.vertices), mesh.triangles, mesh.source)
    return mesh
