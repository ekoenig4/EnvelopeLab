r"""Transfer a solved shape between two meshes of the same build pack.

Two rest meshes of one build pack (e.g. an 800 mm and a 400 mm mesh) triangulate the same
flat pattern pieces. Every node of the new mesh knows the piece instance and flat
coordinates :math:`(u, v)` it was sewn from (``RestMesh.node_refs``), so its 3D position
can be interpolated from the solved shape of the old mesh inside the same flat piece:

.. math:: x(u, v) = \sum_{a=1}^{3} \lambda_a(u, v)\, x_a ,

with :math:`\lambda_a` the barycentric coordinates of :math:`(u, v)` in the old triangle
of that instance that contains it and :math:`x_a` its solved corner positions. Points just
outside every old triangle (a curved edge meshed with different chords) use the nearest
triangle, with the barycentric coordinates clipped to it.

The transfer is exact for a shape that is linear inside every old triangle (the old
solution itself, as the constant-strain elements represent it). It is a *starting guess*
for the solver on the new mesh, never a result: the solver still has to converge on its
own criteria.

References
----------
.. [Zienkiewicz] O. C. Zienkiewicz, R. L. Taylor and J. Z. Zhu, *The Finite Element
   Method: Its Basis and Fundamentals*, 7th ed., Butterworth-Heinemann (2013), ch. 6
   (triangle area coordinates).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from envelopelab.assembly.mesh import RestMesh

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int64]


@dataclass(frozen=True)
class SolvedShape:
    """A solved mesh with the flat data needed to transfer it.

    Attributes
    ----------
    triangles : ndarray of int, shape (m, 3)
        Node indices of each triangle.
    rest_uv : ndarray, shape (m, 3, 2)
        Flat rest coordinates of each corner in its instance frame, m.
    tri_instance : ndarray of int, shape (m,)
        Instance index of each triangle (into ``instance_ids``).
    instance_ids : sequence of str
        Piece-instance ids (e.g. ``body/C@3``).
    positions : ndarray, shape (n, 3)
        Solved node positions, m.
    """

    triangles: IntArray
    rest_uv: FloatArray
    tri_instance: IntArray
    instance_ids: Sequence[str]
    positions: FloatArray

    @classmethod
    def from_mesh(cls, mesh: RestMesh, positions: npt.ArrayLike) -> SolvedShape:
        """Shape of ``mesh`` at ``positions`` (m)."""
        return cls(
            np.asarray(mesh.triangles, dtype=np.int64),
            np.asarray(mesh.rest_uv, dtype=np.float64),
            np.asarray(mesh.tri_instance, dtype=np.int64),
            list(mesh.instance_ids),
            np.asarray(positions, dtype=np.float64).reshape(-1, 3),
        )


def _barycentric(points: FloatArray, corners: FloatArray) -> FloatArray:
    """Barycentric coordinates of every point in every triangle, shape (p, t, 3)."""
    a, b, c = corners[:, 0], corners[:, 1], corners[:, 2]
    v0, v1 = b - a, c - a
    d00 = np.einsum("ti,ti->t", v0, v0)
    d01 = np.einsum("ti,ti->t", v0, v1)
    d11 = np.einsum("ti,ti->t", v1, v1)
    den = d00 * d11 - d01 * d01
    v2 = points[:, None, :] - a[None, :, :]
    d20 = np.einsum("pti,ti->pt", v2, v0)
    d21 = np.einsum("pti,ti->pt", v2, v1)
    l1 = (d11 * d20 - d01 * d21) / den
    l2 = (d00 * d21 - d01 * d20) / den
    return np.stack((1.0 - l1 - l2, l1, l2), axis=-1)


def transfer_positions(source: SolvedShape, target: RestMesh) -> FloatArray:
    """Positions of the nodes of ``target`` interpolated from a solved ``source`` shape.

    Parameters
    ----------
    source : SolvedShape
        Solved shape of another mesh of the same build pack (positions in m).
    target : RestMesh
        The new mesh (flat coordinates in m).

    Returns
    -------
    ndarray, shape (target.n_nodes, 3)
        Interpolated positions, m.

    Raises
    ------
    ValueError
        When a target instance does not exist in the source (a different build pack).
    """
    index = {name: i for i, name in enumerate(source.instance_ids)}
    out = np.zeros((target.n_nodes, 3), dtype=np.float64)
    wanted: dict[int, list[tuple[int, float, float]]] = {}
    for node, refs in enumerate(target.node_refs):
        inst, u, v = refs[0]
        name = target.instance_ids[inst]
        if name not in index:
            raise ValueError(f"instance {name!r} is not in the source mesh (another build pack?)")
        wanted.setdefault(index[name], []).append((node, u, v))
    for inst, items in wanted.items():
        tris = np.flatnonzero(source.tri_instance == inst)
        nodes = np.array([n for n, _, _ in items], dtype=np.int64)
        points = np.array([(u, v) for _, u, v in items], dtype=np.float64)
        # Chunked so that very fine meshes stay within a modest memory footprint.
        for start in range(0, len(nodes), 2048):
            sl = slice(start, start + 2048)
            lam = _barycentric(points[sl], source.rest_uv[tris])
            best = np.argmax(lam.min(axis=2), axis=1)
            w = np.clip(lam[np.arange(len(best)), best], 0.0, None)
            w /= w.sum(axis=1, keepdims=True)
            corners = source.positions[source.triangles[tris[best]]]  # (p, 3, 3)
            out[nodes[sl]] = np.einsum("pa,pai->pi", w, corners)
    return out
