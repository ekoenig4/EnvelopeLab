r"""Reference meshes: import (OBJ, STL, PLY), rigid registration (ICP) and deviation.

A *reference mesh* is the shape a design is meant to have (a sculptor's model, a 3D
concept, a scan of a built envelope). The Reality Check report compares simulated shapes
with it. Any triangle mesh in Wavefront OBJ, STL (ASCII or binary) or PLY (ASCII or
binary, little or big endian) can be read; units are converted to m by ``scale``.

Registration
------------
The simulated shape and the reference are brought into one frame by a rigid motion
:math:`x \mapsto R x + t` found with the iterative closest point algorithm [Besl]_:
alternately pair every source point with its closest reference point and solve the
least-squares rigid motion of the pairs [Kabsch]_, rejecting pairs further apart than a
distance threshold. With Open3D installed (optional, MIT licence) its implementation
(``open3d.pipelines.registration.registration_icp``, point-to-plane) is used; otherwise
the same point-to-point algorithm runs with SciPy KD-trees. The backend is recorded. ICP
converges to the nearest local minimum, so a coarse start matters:
:func:`coarse_align_about_axis` tries rotations about the vertical axis first.

Signed distance
---------------
For each point the closest point on the reference surface is found (candidate triangles
from a KD-tree of triangle centroids, exact point-triangle distance [Ericson]_); the
distance is positive when the point lies outside the reference (along the outward face
normal) and negative inside.

Volume notation
---------------
:func:`parse_volume_notation` reads an envelope volume written in a title or caption
(``1,800 m³``, ``1800 m3``, ``90,000 cu ft``) and returns it in m^3.

References
----------
.. [Besl] P. J. Besl and N. D. McKay, "A method for registration of 3-D shapes", IEEE
   Trans. PAMI 14 (1992) 239-256.
.. [Kabsch] W. Kabsch, Acta Cryst. A32 (1976) 922-923.
.. [Ericson] C. Ericson, *Real-Time Collision Detection*, Morgan Kaufmann (2005),
   sec. 5.1.5.
"""

from __future__ import annotations

import math
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np
from scipy.spatial import cKDTree

from envelopelab.assembly.initial_shape import closest_points_on_triangles
from envelopelab.solvers.membrane import FloatArray, IntArray

Backend = Literal["auto", "open3d", "scipy"]
#: Cubic metres per cubic foot (exact: 0.3048^3).
CUBIC_FOOT = 0.3048**3


class ReferenceMeshError(ValueError):
    """Raised for unreadable or empty mesh files."""


@dataclass
class ReferenceMesh:
    """A triangle mesh in m.

    Attributes
    ----------
    vertices : ndarray, shape (n, 3)
        m.
    triangles : ndarray of int, shape (m, 3)
        Vertex indices.
    source : str
        File the mesh came from.
    """

    vertices: FloatArray
    triangles: IntArray
    source: str = ""

    def transformed(self, rotation: FloatArray, translation: FloatArray) -> ReferenceMesh:
        """Copy moved by :math:`x \\mapsto R x + t`."""
        return ReferenceMesh(self.vertices @ rotation.T + translation, self.triangles, self.source)

    @property
    def volume(self) -> float:
        """Enclosed volume by the divergence theorem, m^3 (meaningful for closed meshes)."""
        e = self.vertices[self.triangles]
        return abs(float(np.einsum("mi,mi->m", e[:, 0], np.cross(e[:, 1], e[:, 2])).sum()) / 6.0)

    @property
    def area(self) -> float:
        """Surface area, m^2."""
        e = self.vertices[self.triangles]
        return 0.5 * float(
            np.linalg.norm(np.cross(e[:, 1] - e[:, 0], e[:, 2] - e[:, 0]), axis=1).sum()
        )


def _fan(poly: list[int]) -> list[list[int]]:
    return [[poly[0], poly[k], poly[k + 1]] for k in range(1, len(poly) - 1)]


def _read_obj(data: bytes) -> tuple[list[list[float]], list[list[int]]]:
    vertices: list[list[float]] = []
    faces: list[list[int]] = []
    for line in data.decode("utf-8", errors="replace").splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "v":
            vertices.append([float(x) for x in parts[1:4]])
        elif parts[0] == "f":
            idx = [int(p.split("/")[0]) for p in parts[1:]]
            faces.extend(_fan([i - 1 if i > 0 else len(vertices) + i for i in idx]))
    return vertices, faces


def _read_stl(data: bytes) -> tuple[FloatArray, IntArray]:
    if len(data) >= 84:
        count = struct.unpack("<I", data[80:84])[0]
        if len(data) == 84 + 50 * count:
            rec = np.frombuffer(
                data[84:], dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
            )
            pts = rec["v"].reshape(-1, 3).astype(np.float64)
            return _weld(pts)
    text = data.decode("utf-8", errors="replace")
    pts = np.array(
        [
            [float(x) for x in m.groups()]
            for m in re.finditer(r"vertex\s+(\S+)\s+(\S+)\s+(\S+)", text)
        ]
    )
    if not len(pts) or len(pts) % 3:
        raise ReferenceMeshError("STL file has no complete facets")
    return _weld(pts)


def _weld(points: FloatArray) -> tuple[FloatArray, IntArray]:
    keys = np.round(points, 9)
    uniq, inverse = np.unique(keys, axis=0, return_inverse=True)
    return uniq, inverse.reshape(-1, 3).astype(np.int64)


_PLY_TYPES = {
    "char": "i1", "int8": "i1", "uchar": "u1", "uint8": "u1", "short": "i2", "int16": "i2",
    "ushort": "u2", "uint16": "u2", "int": "i4", "int32": "i4", "uint": "u4", "uint32": "u4",
    "float": "f4", "float32": "f4", "double": "f8", "float64": "f8",
}  # fmt: skip


def _read_ply(data: bytes) -> tuple[FloatArray, IntArray]:
    end = data.find(b"end_header")
    if not data.startswith(b"ply") or end < 0:
        raise ReferenceMeshError("not a PLY file")
    header = data[:end].decode("ascii", errors="replace").splitlines()
    body = data[data.index(b"\n", end) + 1 :]
    fmt = "ascii"
    elements: list[tuple[str, int, list[tuple[str, ...]]]] = []
    for line in header:
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "format":
            fmt = parts[1]
        elif parts[0] == "element":
            elements.append((parts[1], int(parts[2]), []))
        elif parts[0] == "property" and elements:
            elements[-1][2].append(tuple(parts[1:]))
    vertices: FloatArray | None = None
    faces: list[list[int]] = []
    if fmt == "ascii":
        tokens = body.decode("ascii", errors="replace").split()
        pos = 0
        for name, count, props in elements:
            rows = []
            for _ in range(count):
                row: list[Any] = []
                for prop in props:
                    if prop[0] == "list":
                        n = int(float(tokens[pos]))
                        row.append([float(t) for t in tokens[pos + 1 : pos + 1 + n]])
                        pos += 1 + n
                    else:
                        row.append(float(tokens[pos]))
                        pos += 1
                rows.append(row)
            if name == "vertex":
                names = [p[-1] for p in props]
                ix, iy, iz = (names.index(k) for k in ("x", "y", "z"))
                vertices = np.array([[r[ix], r[iy], r[iz]] for r in rows], dtype=np.float64)
            elif name == "face":
                for r in rows:
                    faces.extend(_fan([int(i) for i in r[0]]))
    else:
        endian = "<" if fmt == "binary_little_endian" else ">"
        pos = 0
        for name, count, props in elements:
            if all(p[0] != "list" for p in props):
                dt = np.dtype([(p[-1], endian + _PLY_TYPES[p[0]]) for p in props])
                arr = np.frombuffer(body, dtype=dt, count=count, offset=pos)
                pos += dt.itemsize * count
                if name == "vertex":
                    vertices = np.column_stack([arr["x"], arr["y"], arr["z"]]).astype(np.float64)
                continue
            for _ in range(count):
                row_faces = None
                for prop in props:
                    if prop[0] == "list":
                        ct = np.dtype(endian + _PLY_TYPES[prop[1]])
                        it = np.dtype(endian + _PLY_TYPES[prop[2]])
                        n = int(np.frombuffer(body, ct, 1, pos)[0])
                        pos += ct.itemsize
                        vals = np.frombuffer(body, it, n, pos)
                        pos += it.itemsize * n
                        row_faces = [int(v) for v in vals]
                    else:
                        pos += np.dtype(_PLY_TYPES[prop[0]]).itemsize
                if name == "face" and row_faces is not None:
                    faces.extend(_fan(row_faces))
    if vertices is None:
        raise ReferenceMeshError("PLY file has no vertex element")
    return vertices, np.array(faces, dtype=np.int64).reshape(-1, 3)


def read_mesh(path: str | Path, scale: float = 1.0) -> ReferenceMesh:
    """Read a triangle mesh from OBJ, STL or PLY.

    Parameters
    ----------
    path : str or Path
        Mesh file (format from the extension: ``.obj``, ``.stl``, ``.ply``).
    scale : float
        Metres per file unit (1 for m, 0.001 for mm, 0.0254 for in).

    Returns
    -------
    ReferenceMesh
        Vertices in m and triangles (polygons fan-triangulated, STL facets welded).

    Raises
    ------
    ReferenceMeshError
        For unknown extensions or files without triangles.
    """
    p = Path(path)
    data = p.read_bytes()
    ext = p.suffix.lower()
    if ext == ".obj":
        v, f = _read_obj(data)
        vertices, triangles = np.array(v, dtype=np.float64), np.array(f, dtype=np.int64)
    elif ext == ".stl":
        vertices, triangles = _read_stl(data)
    elif ext == ".ply":
        vertices, triangles = _read_ply(data)
    else:
        raise ReferenceMeshError(f"{p}: unsupported mesh format {ext!r} (use OBJ, STL or PLY)")
    if not len(vertices) or not len(triangles):
        raise ReferenceMeshError(f"{p}: no vertices or triangles")
    return ReferenceMesh(vertices.reshape(-1, 3) * scale, triangles.reshape(-1, 3), str(p))


def write_ply(path: str | Path, mesh: ReferenceMesh) -> Path:
    """Write an ASCII PLY file (m)."""
    p = Path(path)
    lines = [
        "ply",
        "format ascii 1.0",
        f"element vertex {len(mesh.vertices)}",
        "property double x",
        "property double y",
        "property double z",
        f"element face {len(mesh.triangles)}",
        "property list uchar int vertex_indices",
        "end_header",
    ]
    lines += [f"{x:.9g} {y:.9g} {z:.9g}" for x, y, z in mesh.vertices]
    lines += [f"3 {a} {b} {c}" for a, b, c in mesh.triangles]
    p.write_text("\n".join(lines) + "\n", encoding="ascii")
    return p


def write_stl(path: str | Path, mesh: ReferenceMesh) -> Path:
    """Write a binary STL file (m)."""
    p = Path(path)
    e = mesh.vertices[mesh.triangles].astype(np.float32)
    n = np.cross(e[:, 1] - e[:, 0], e[:, 2] - e[:, 0])
    n /= np.maximum(np.linalg.norm(n, axis=1), 1e-30)[:, None]
    rec = np.zeros(len(e), dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]))
    rec["n"], rec["v"] = n, e
    p.write_bytes(b"EnvelopeLab mesh".ljust(80, b" ") + struct.pack("<I", len(e)) + rec.tobytes())
    return p


# --------------------------------------------------------------------------------------
# Distance
# --------------------------------------------------------------------------------------


def closest_points(
    points: FloatArray, mesh: ReferenceMesh, candidates: int = 16
) -> tuple[FloatArray, IntArray]:
    """Closest points on ``mesh`` to ``points`` (m) and the triangle each lies on."""
    tri = mesh.triangles
    v = mesh.vertices
    centroids = v[tri].mean(axis=1)
    tree = cKDTree(centroids)
    k = min(candidates, len(tri))
    _, idx = tree.query(points, k=k)
    idx = np.asarray(idx).reshape(len(points), k)
    best = np.full(len(points), np.inf)
    best_pt = np.zeros_like(points)
    best_tri = np.zeros(len(points), dtype=np.int64)
    for j in range(k):
        t = idx[:, j]
        cp = closest_points_on_triangles(points, v[tri[t, 0]], v[tri[t, 1]], v[tri[t, 2]])
        d = np.linalg.norm(cp - points, axis=1)
        better = d < best
        best[better] = d[better]
        best_pt[better] = cp[better]
        best_tri[better] = t[better]
    return best_pt, best_tri


def signed_distance(points: FloatArray, mesh: ReferenceMesh) -> FloatArray:
    """Signed distance of points to the reference surface, m (positive outside).

    Parameters
    ----------
    points : ndarray, shape (k, 3)
        Query points, m.
    mesh : ReferenceMesh
        Reference with outward-oriented faces.

    Returns
    -------
    ndarray, shape (k,)
        m.
    """
    points = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    cp, t = closest_points(points, mesh)
    e = mesh.vertices[mesh.triangles[t]]
    n = np.cross(e[:, 1] - e[:, 0], e[:, 2] - e[:, 0])
    diff = points - cp
    sign = np.sign(np.einsum("ij,ij->i", diff, n))
    sign[sign == 0] = 1.0
    out: FloatArray = sign * np.linalg.norm(diff, axis=1)
    return out


@dataclass(frozen=True)
class DeviationStats:
    """Summary of signed distances (m)."""

    mean: float
    rms: float
    max_outside: float
    max_inside: float
    p95_abs: float
    count: int

    def as_dict(self) -> dict[str, float | int]:
        """JSON-ready dictionary (m)."""
        return {
            "mean_m": self.mean,
            "rms_m": self.rms,
            "max_outside_m": self.max_outside,
            "max_inside_m": self.max_inside,
            "p95_abs_m": self.p95_abs,
            "count": self.count,
        }


def deviation_stats(distances: FloatArray) -> DeviationStats:
    """Mean, RMS, extremes and 95th percentile of absolute signed distances (m)."""
    d = np.asarray(distances, dtype=np.float64)
    return DeviationStats(
        float(d.mean()),
        float(np.sqrt((d**2).mean())),
        float(d.max()),
        float(d.min()),
        float(np.percentile(np.abs(d), 95)),
        int(len(d)),
    )


# --------------------------------------------------------------------------------------
# Registration
# --------------------------------------------------------------------------------------


@dataclass
class Registration:
    """Rigid transform mapping source points onto the reference.

    Attributes
    ----------
    rotation : ndarray, shape (3, 3)
        Rotation, -.
    translation : ndarray, shape (3,)
        m.
    rmse : float
        RMS distance of the inlier pairs, m.
    fitness : float
        Fraction of source points with a pair within the threshold, -.
    iterations : int
        ICP iterations.
    backend : str
        ``open3d`` or ``scipy``.
    converged : bool
        The last iteration changed the RMS by less than the tolerance.
    notes : list of str
        Coarse-alignment and backend notes.
    """

    rotation: FloatArray
    translation: FloatArray
    rmse: float
    fitness: float
    iterations: int
    backend: str
    converged: bool
    notes: list[str] = field(default_factory=list)

    def apply(self, points: FloatArray) -> FloatArray:
        """Transformed points, m."""
        out: FloatArray = np.asarray(points) @ self.rotation.T + self.translation
        return out

    @property
    def matrix(self) -> FloatArray:
        """Homogeneous 4x4 transform."""
        m = np.eye(4)
        m[:3, :3], m[:3, 3] = self.rotation, self.translation
        return m

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready dictionary."""
        return {
            "matrix": self.matrix.tolist(),
            "rmse_m": self.rmse,
            "fitness": self.fitness,
            "iterations": self.iterations,
            "backend": self.backend,
            "converged": self.converged,
            "notes": self.notes,
        }


def _kabsch(src: FloatArray, dst: FloatArray) -> tuple[FloatArray, FloatArray]:
    cs, cd = src.mean(axis=0), dst.mean(axis=0)
    h = (src - cs).T @ (dst - cd)
    u, _, vt = np.linalg.svd(h)
    d = np.sign(np.linalg.det(vt.T @ u.T)) or 1.0
    rot = vt.T @ np.diag([1.0, 1.0, d]) @ u.T
    return rot, cd - rot @ cs


def open3d_available() -> bool:
    """True when the optional Open3D package can be imported."""
    try:
        import open3d  # noqa: F401
    except ImportError:
        return False
    return True


def _sample_surface(mesh: ReferenceMesh, count: int) -> FloatArray:
    rng = np.random.default_rng(0)
    e = mesh.vertices[mesh.triangles]
    area = 0.5 * np.linalg.norm(np.cross(e[:, 1] - e[:, 0], e[:, 2] - e[:, 0]), axis=1)
    t = rng.choice(len(area), size=count, p=area / area.sum())
    r1, r2 = rng.random(count), rng.random(count)
    s = np.sqrt(r1)
    out: FloatArray = (
        e[t, 0] * (1 - s)[:, None] + e[t, 1] * (s * (1 - r2))[:, None] + e[t, 2] * (s * r2)[:, None]
    )
    return out


def icp(
    source: FloatArray,
    reference: ReferenceMesh,
    threshold: float,
    max_iterations: int = 100,
    tolerance: float = 1e-7,
    backend: Backend = "auto",
    initial: FloatArray | None = None,
) -> Registration:
    """Rigid ICP registration of ``source`` points onto a reference surface.

    Parameters
    ----------
    source : ndarray, shape (k, 3)
        Points to move (e.g. the simulated surface vertices), m.
    reference : ReferenceMesh
        Fixed surface.
    threshold : float
        Largest pair distance kept, m.
    max_iterations : int
        Iteration limit.
    tolerance : float
        Converged when the RMS changes by less than this, m.
    backend : {"auto", "open3d", "scipy"}
        ``auto`` uses Open3D when installed, else SciPy.
    initial : ndarray, shape (4, 4), optional
        Starting transform (default identity).

    Returns
    -------
    Registration
        Transform, RMS (m), fitness (-), iterations, backend.
    """
    src = np.asarray(source, dtype=np.float64).reshape(-1, 3)
    start = np.eye(4) if initial is None else np.asarray(initial, dtype=np.float64)
    use_o3d = backend == "open3d" or (backend == "auto" and open3d_available())
    if use_o3d:
        return _icp_open3d(src, reference, threshold, max_iterations, start)
    return _icp_scipy(src, reference, threshold, max_iterations, tolerance, start)


def _icp_open3d(
    src: FloatArray,
    reference: ReferenceMesh,
    threshold: float,
    max_iterations: int,
    start: FloatArray,
) -> Registration:
    import open3d as o3d

    target_mesh = o3d.geometry.TriangleMesh(
        o3d.utility.Vector3dVector(reference.vertices),
        o3d.utility.Vector3iVector(reference.triangles),
    )
    target_mesh.compute_vertex_normals()
    count = max(len(src), 20_000)
    target = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(_sample_surface(reference, count)))
    target.estimate_normals()
    source = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(src))
    result = o3d.pipelines.registration.registration_icp(
        source,
        target,
        threshold,
        start,
        o3d.pipelines.registration.TransformationEstimationPointToPlane(),
        o3d.pipelines.registration.ICPConvergenceCriteria(max_iteration=max_iterations),
    )
    m = np.asarray(result.transformation, dtype=np.float64)
    return Registration(
        m[:3, :3].copy(),
        m[:3, 3].copy(),
        float(result.inlier_rmse),
        float(result.fitness),
        max_iterations,
        f"open3d {o3d.__version__} (point-to-plane)",
        True,
    )


def _icp_scipy(
    src: FloatArray,
    reference: ReferenceMesh,
    threshold: float,
    max_iterations: int,
    tolerance: float,
    start: FloatArray,
) -> Registration:
    rot, trans = start[:3, :3].copy(), start[:3, 3].copy()
    prev = math.inf
    rmse = math.inf
    fitness = 0.0
    converged = False
    it = 0
    for step in range(1, max_iterations + 1):
        it = step
        moved = src @ rot.T + trans
        cp, _ = closest_points(moved, reference)
        d = np.linalg.norm(cp - moved, axis=1)
        keep = d <= threshold
        fitness = float(keep.mean())
        if keep.sum() < 3:
            break
        rmse = float(np.sqrt((d[keep] ** 2).mean()))
        r_step, t_step = _kabsch(moved[keep], cp[keep])
        rot, trans = r_step @ rot, r_step @ trans + t_step
        if abs(prev - rmse) < tolerance:
            converged = True
            break
        prev = rmse
    moved = src @ rot.T + trans
    cp, _ = closest_points(moved, reference)
    d = np.linalg.norm(cp - moved, axis=1)
    keep = d <= threshold
    if keep.any():
        rmse = float(np.sqrt((d[keep] ** 2).mean()))
        fitness = float(keep.mean())
    return Registration(rot, trans, rmse, fitness, it, "scipy (point-to-point)", converged)


def coarse_align_about_axis(
    source: FloatArray,
    reference: ReferenceMesh,
    steps: int = 72,
    axis_point: FloatArray | None = None,
    sample: int = 2000,
) -> FloatArray:
    """Best rotation of ``source`` about the vertical axis (brute force), as a 4x4 transform.

    Parameters
    ----------
    source : ndarray, shape (k, 3)
        Source points, m (already in a frame with a vertical z axis).
    reference : ReferenceMesh
        Target.
    steps : int
        Number of trial angles over 360 deg.
    axis_point : ndarray, shape (3,), optional
        A point on the rotation axis (default the origin).
    sample : int
        Source points used for scoring.

    Returns
    -------
    ndarray, shape (4, 4)
        Transform with the smallest mean closest-point distance.
    """
    rng = np.random.default_rng(0)
    pts = (
        source if len(source) <= sample else source[rng.choice(len(source), sample, replace=False)]
    )
    c = np.zeros(3) if axis_point is None else np.asarray(axis_point, dtype=np.float64)
    best, best_m = math.inf, np.eye(4)
    for k in range(steps):
        a = 2.0 * math.pi * k / steps
        r = np.array(
            [[math.cos(a), -math.sin(a), 0.0], [math.sin(a), math.cos(a), 0.0], [0, 0, 1.0]]
        )
        t = c - r @ c
        cp, _ = closest_points(pts @ r.T + t, reference)
        score = float(np.linalg.norm(cp - (pts @ r.T + t), axis=1).mean())
        if score < best:
            best = score
            best_m = np.eye(4)
            best_m[:3, :3], best_m[:3, 3] = r, t
    return best_m


# --------------------------------------------------------------------------------------
# Volume notation
# --------------------------------------------------------------------------------------

_VOLUME = re.compile(
    r"(?P<num>\d{1,3}(?:[,\s ]\d{3})+|\d+(?:\.\d+)?)\s*"
    r"(?P<unit>m³|m\^?3|cubic\s+met(?:er|re)s?|cu\.?\s*ft|ft³|ft\^?3|cubic\s+feet)",
    re.IGNORECASE,
)


def parse_volume_notation(text: str) -> float | None:
    """First envelope volume written in ``text``, in m^3 (None when there is none).

    Recognises thousands separators (``2,550``) and the units m³, m3, m^3, cubic metres,
    cu ft, ft³, ft3 and cubic feet (converted exactly).
    """
    m = _VOLUME.search(text)
    if m is None:
        return None
    value = float(re.sub(r"[,\s ]", "", m.group("num")))
    unit = m.group("unit").lower()
    return value * CUBIC_FOOT if ("ft" in unit or "feet" in unit) else value


def title_text(path: str | Path) -> str:
    """Title-like text of a document: HTML ``<title>`` and heading/bold text, or plain text."""
    raw = Path(path).read_text(encoding="utf-8", errors="replace")
    if "<" not in raw:
        return raw[:2000]
    parts = re.findall(r"<title>(.*?)</title>", raw, re.S | re.I)
    parts += re.findall(r"<(?:h1|h2|b|strong)[^>]*>(.*?)</(?:h1|h2|b|strong)>", raw, re.S | re.I)
    text = " | ".join(re.sub(r"<[^>]+>", "", p).strip() for p in parts)
    return text
