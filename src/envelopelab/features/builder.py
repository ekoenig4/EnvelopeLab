r"""Assembly of an appendage onto its host: footprint, skin, seams, ease, tapes, chambers.

A feature is modelled as a local *sub-model*: a patch of the host envelope around the
footprint, the feature skin sewn to the footprint line, the tapes and the gas chambers.
The result is an ordinary :class:`~envelopelab.solvers.model.SolverModel`, so the preview
solver and the CalculiX adapter solve it unchanged.

Host patch
----------
The host is a patch of a surface of revolution about the vertical axis whose meridian
is locally a circle of radius :math:`R_1` and whose parallel through the patch centre has
normal radius :math:`R_2` (:class:`HostSurface`). The patch is parameterised by the chart

.. math::
    v = R_1 \psi, \qquad u = \rho(\psi)\,\theta, \qquad
    \rho(\psi) = \rho_c + R_1 \cos(\beta + \psi), \quad z(\psi) = z_c + R_1\sin(\beta+\psi)

(:math:`v` meridian arc length, :math:`u` hoop arc length across the panels at that
height, :math:`\beta` the elevation of the outward normal), which is the frame in which
a footprint is marked panel by panel on the envelope. The host fabric's rest geometry is
the designed patch shrunk by the far-field prestrain :math:`\lambda_i = \sqrt{1 + 2E_i}`,
:math:`E = \mathbb{C}^{-1} N_\infty`, so that with its edge nodes fixed on the designed
patch the host carries the envelope's membrane resultants :math:`N_\infty` before the
feature perturbs it. Without a global solution :math:`N_\infty` follows the membrane
theory of shells of revolution [Timoshenko]_:

.. math:: N_v = \frac{p R_2}{2}, \qquad N_u = p R_2\left(1 - \frac{R_2}{2 R_1}\right)

with :math:`p` the envelope pressure at the patch centre (:math:`N_u` clipped at zero).

Skin
----
* ``flat_pattern``: the skin's flat as-cut outline. Its rim nodes meet the footprint
  nodes by the match-point correspondence of :mod:`envelopelab.features.ease`, so the
  designed ease enters as the difference between the skin's rest edge lengths and the
  footprint's.
* ``spherical_cap``: a designed doubly curved skin (stress-free on a spherical cap of the
  given height over a circular footprint), for analytic blister benchmarks.
* ``designed``: a skin sewn from several cut pieces, supplied by a factory that meshes
  every piece in its own flat pattern coordinates round the footprint nodes
  (:class:`DesignedSkin`; :mod:`envelopelab.features.primitives`). Each triangle rests
  in the cut cloth, seams are shared mesh lines and the designed 3D shape is only the
  starting position; the footprint is meshed at the nodes the factory's caller gave
  (no resampling).

Assumptions: the patch edge is fixed on the designed surface (submodel boundary; keep the
margin at least half the footprint size); the host far-field state is uniform over the
patch; seam allowances, stitching and tape widths are not modelled as material.

References
----------
.. [Timoshenko] S. P. Timoshenko and S. Woinowsky-Krieger, *Theory of Plates and Shells*,
   2nd ed., McGraw-Hill (1959), sec. 105 (membrane stresses in shells of revolution).
.. [Tutte] W. T. Tutte, "How to draw a graph", Proc. London Math. Soc. 13 (1963) 743-767
   (harmonic embedding used for the initial skin guess).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.linalg import spsolve
from scipy.spatial import cKDTree

from envelopelab.features.ease import (
    EaseMode,
    RimEase,
    loop_arclength,
    loop_length,
    point_on_loop,
    rim_correspondence,
    rim_ease,
)
from envelopelab.features.pressure import FeedHole, FeedPressure, fed_chamber
from envelopelab.geometry.polygon import (
    distance_to_polyline,
    orient_ccw,
    points_in_polygon,
)
from envelopelab.materials.membrane import MembraneMaterial, TapeMaterial
from envelopelab.solvers.membrane import FloatArray, IntArray
from envelopelab.solvers.model import (
    AMBIENT,
    MAIN_CHAMBER,
    CableSet,
    NodeConstraint,
    OperatingConditions,
    PressureChamber,
    SeamLine,
    SolverModel,
)

SkinMode = Literal["flat_pattern", "spherical_cap", "designed"]
#: 3D area of the initial flat-pattern skin guess as a fraction of its rest area, -.
INITIAL_SKIN_AREA = 0.97


class FeatureBuildError(ValueError):
    """Raised when a feature cannot be assembled (bad geometry, missing material)."""


# --------------------------------------------------------------------------------------
# Host surface
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class HostSurface:
    """Local surface of revolution carrying a feature (see module docstring).

    Attributes
    ----------
    meridian_radius : float
        :math:`R_1`, radius of curvature of the meridian, m.
    hoop_radius : float
        :math:`R_2`, normal radius of the parallel through the patch centre, m.
    normal_elevation : float
        :math:`\\beta`, elevation of the outward normal above the horizontal, rad.
    centre_height : float
        Height of the chart origin, m.
    source : str
        Where the geometry comes from (e.g. "as-sewn initial shape").
    """

    meridian_radius: float
    hoop_radius: float
    normal_elevation: float = 0.0
    centre_height: float = 0.0
    source: str = "assumed"

    def __post_init__(self) -> None:
        if self.meridian_radius <= 0.0 or self.hoop_radius <= 0.0:
            raise FeatureBuildError("host radii must be positive")
        if abs(self.normal_elevation) >= 0.5 * math.pi:
            raise FeatureBuildError("normal elevation must be within (-90, 90) deg")

    def _profile(self, v: FloatArray) -> tuple[FloatArray, FloatArray, FloatArray]:
        r1, b = self.meridian_radius, self.normal_elevation
        rho0 = self.hoop_radius * math.cos(b)
        psi = v / r1
        rho = rho0 - r1 * math.cos(b) + r1 * np.cos(b + psi)
        z = self.centre_height - r1 * math.sin(b) + r1 * np.sin(b + psi)
        return psi, rho, z

    def hoop_radius_at(self, v: float) -> float:
        """Distance from the axis of the parallel at chart height ``v`` (m), m."""
        _, rho, _ = self._profile(np.array([v], dtype=np.float64))
        return float(rho[0])

    def height_above(self, points: FloatArray) -> FloatArray:
        """Signed distance of 3D points from the host surface along its normal, m.

        Exact for the surface of revolution with a circular meridian (the distance in
        the meridian plane to the meridian circle).
        """
        p = np.asarray(points, dtype=np.float64).reshape(-1, 3)
        r1, b = self.meridian_radius, self.normal_elevation
        rho0 = self.hoop_radius * math.cos(b)
        rho = np.hypot(p[:, 0] + rho0, p[:, 1])
        rho_c = rho0 - r1 * math.cos(b)
        z_c = self.centre_height - r1 * math.sin(b)
        out: FloatArray = np.hypot(rho - rho_c, p[:, 2] - z_c) - r1
        return out

    def map(self, uv: FloatArray) -> FloatArray:
        """3D positions of chart points ``uv`` (m), shape (n, 3)."""
        uv = np.asarray(uv, dtype=np.float64).reshape(-1, 2)
        _, rho, z = self._profile(uv[:, 1])
        if np.any(rho <= 0.0):
            raise FeatureBuildError("host patch reaches the axis; reduce the margin")
        theta = uv[:, 0] / rho
        rho0 = self.hoop_radius * math.cos(self.normal_elevation)
        return np.column_stack([rho * np.cos(theta) - rho0, rho * np.sin(theta), z])

    def normal(self, uv: FloatArray) -> FloatArray:
        """Outward unit normals at chart points, shape (n, 3)."""
        uv = np.asarray(uv, dtype=np.float64).reshape(-1, 2)
        psi, rho, _ = self._profile(uv[:, 1])
        theta = uv[:, 0] / rho
        a = self.normal_elevation + psi
        return np.column_stack([np.cos(a) * np.cos(theta), np.cos(a) * np.sin(theta), np.sin(a)])

    def tangent_u(self, uv: FloatArray) -> FloatArray:
        """Unit hoop tangents at chart points, shape (n, 3)."""
        uv = np.asarray(uv, dtype=np.float64).reshape(-1, 2)
        _, rho, _ = self._profile(uv[:, 1])
        theta = uv[:, 0] / rho
        return np.column_stack([-np.sin(theta), np.cos(theta), np.zeros(len(uv))])

    def as_dict(self) -> dict[str, object]:
        """JSON-ready dictionary with units."""
        return {
            "meridian_radius_m": self.meridian_radius,
            "hoop_radius_m": self.hoop_radius,
            "normal_elevation_deg": math.degrees(self.normal_elevation),
            "centre_height_m": self.centre_height,
            "source": self.source,
        }


def shell_prestress(pressure: float, host: HostSurface) -> tuple[float, float]:
    """Membrane resultants (hoop, meridional) of a shell of revolution, N/m.

    Parameters
    ----------
    pressure : float
        Differential pressure, Pa.
    host : HostSurface
        Radii :math:`R_1`, :math:`R_2`, m.

    Returns
    -------
    (float, float)
        :math:`N_u = p R_2 (1 - R_2 / 2R_1)` (clipped at 0) and :math:`N_v = p R_2 / 2`,
        N/m.
    """
    r1, r2 = host.meridian_radius, host.hoop_radius
    n_v = pressure * r2 / 2.0
    n_u = max(pressure * r2 * (1.0 - r2 / (2.0 * r1)), 0.0)
    return n_u, n_v


# --------------------------------------------------------------------------------------
# Specification
# --------------------------------------------------------------------------------------


@dataclass
class RimTapeSpec:
    """Tape sewn round the footprint line.

    Attributes
    ----------
    material : TapeMaterial
        Tape.
    caught_into_host_tapes : bool
        True when the rim tape is sewn into every host tape it crosses (shared node).
        False models a rim tape that stops short of each crossing by ``gap`` on both
        sides, so the rim load reaches the host tapes through the host fabric.
    gap : float, optional
        Length left free either side of a crossing when not caught, m (default twice
        the mesh size).
    """

    material: TapeMaterial
    caught_into_host_tapes: bool = True
    gap: float | None = None


@dataclass
class HostTape:
    """A host load tape (seam) crossing the patch, in chart coordinates (m)."""

    name: str
    polyline: FloatArray
    material: TapeMaterial


@dataclass
class ChartHole:
    """A feed hole cut in the host inside the footprint (chart centre and radius, m)."""

    name: str
    centre: tuple[float, float]
    radius: float
    hem_tape: TapeMaterial | None = None

    @property
    def area(self) -> float:
        """Open area, m^2."""
        return math.pi * self.radius**2


@dataclass
class PressureSpec:
    """How the appendage chamber pressure is set.

    ``mode="fed"`` derives it from the feed holes with the loss factor (source
    ``assumed``); ``mode="independent"`` uses the given chamber directly.
    """

    mode: Literal["fed", "independent"] = "fed"
    loss_factor: float = 0.0
    chamber: PressureChamber | None = None


@dataclass
class DesignedSkin:
    """A skin meshed from its cut pieces (``skin_mode="designed"``).

    Attributes
    ----------
    positions : ndarray, shape (n, 3)
        Starting node positions in the host frame, m (rim nodes are moved onto the host).
    triangles : ndarray of int, shape (m, 3)
        Triangles, oriented with their normal pointing away from the host.
    rest_uv : ndarray, shape (m, 3, 2)
        Corner coordinates of every triangle in its cut piece, m.
    grain : ndarray, shape (m, 2)
        Warp direction of every triangle in its rest coordinates.
    rim_index : ndarray of int
        Skin node of every footprint node, in the order the factory received them.
    seams : dict of str to ndarray
        Skin seams as edge lists (skin node pairs).
    notes : list of str
        Adjustments made while meshing.
    """

    positions: FloatArray
    triangles: IntArray
    rest_uv: FloatArray
    grain: FloatArray
    rim_index: IntArray
    seams: dict[str, IntArray] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


SkinFactory = Callable[[FloatArray, float], DesignedSkin]
"""``factory(rim_chart, mesh_size)``: the skin round the footprint nodes (chart, m)."""


@dataclass
class AppendageSpec:
    """Everything needed to assemble one appendage sub-model (SI units).

    Attributes
    ----------
    name : str
        Feature name (also the chamber name).
    footprint : ndarray, shape (k, 2)
        Footprint line in the host chart, m (closed, any orientation).
    skin_outline : ndarray, shape (q, 2), optional
        Finished rim of the flat skin pattern, m (``flat_pattern``).
    skin_mode : {"flat_pattern", "spherical_cap", "designed"}
        Skin rest geometry.
    skin_mesh : callable, optional
        Skin factory of a ``designed`` skin (:data:`SkinFactory`).
    cap_height : float, optional
        Designed dome height of a ``spherical_cap`` skin, m.
    match_points : int
        Number of rim match points.
    ease_mode : {"match_points", "pooled"}
        Rim ease distribution.
    match_start : ndarray, shape (2,), optional
        Chart direction from the footprint centroid to match point 1 (default: the
        leftmost footprint point, ``-u``); the skin uses the same direction.
    host : HostSurface, optional
        Host surface; ``None`` holds the rim rigidly (analytic benchmarks).
    margin : float, optional
        Host patch margin round the footprint bounding box, m (default half its larger
        side).
    mesh_size : float
        Target edge length, m.
    host_zone, skin_zone : str
        Material zones.
    host_grain, skin_grain : tuple of float
        Warp direction in the chart and in the skin pattern.
    prestress : (float, float), optional
        Far-field host resultants (hoop, meridional), N/m (default
        :func:`shell_prestress`).
    rim_tape : RimTapeSpec, optional
        Perimeter reinforcement.
    host_tapes : list of HostTape
        Host load tapes crossing the patch.
    holes : list of ChartHole
        Feed holes cut in the host inside the footprint.
    pressure : PressureSpec
        Chamber pressure.
    intended : dict
        Intended values from the design (e.g. ``dome_height_m``), for the report.
    """

    name: str
    footprint: FloatArray
    skin_outline: FloatArray | None = None
    skin_mode: SkinMode = "flat_pattern"
    cap_height: float | None = None
    skin_mesh: SkinFactory | None = None
    match_points: int = 16
    ease_mode: EaseMode = "match_points"
    match_start: tuple[float, float] | None = None
    host: HostSurface | None = None
    margin: float | None = None
    mesh_size: float = 0.25
    host_zone: str = "host"
    skin_zone: str = "skin"
    host_grain: tuple[float, float] = (1.0, 0.0)
    skin_grain: tuple[float, float] = (1.0, 0.0)
    prestress: tuple[float, float] | None = None
    rim_tape: RimTapeSpec | None = None
    host_tapes: list[HostTape] = field(default_factory=list)
    holes: list[ChartHole] = field(default_factory=list)
    pressure: PressureSpec = field(default_factory=PressureSpec)
    intended: dict[str, float] = field(default_factory=dict)


@dataclass
class AppendageModel:
    """An assembled appendage sub-model and the index sets its metrics need.

    Attributes
    ----------
    spec : AppendageSpec
        Input.
    model : SolverModel
        Solver model (m, N, Pa).
    chart : ndarray, shape (n, 2)
        Chart coordinates of every node (skin nodes: harmonic image in the footprint),
        m.
    skin_triangles, footprint_triangles, host_triangles : ndarray of int
        Triangle index sets.
    rim_nodes : ndarray of int
        Footprint loop, ordered from match point 1.
    match_nodes : ndarray of int
        Rim nodes nearest to each match point.
    rim_tape : str or None
        Cable-set name of the rim tape.
    host_tape_names : list of str
        Cable-set names of the host tapes.
    boundary_nodes : ndarray of int
        Fixed nodes (patch edge or rigid rim).
    ease : RimEase or None
        Rim ease (``flat_pattern``).
    feed : FeedPressure or None
        Derived chamber pressure (``fed``).
    chamber : PressureChamber
        The appendage chamber.
    footprint_normal : ndarray, shape (3,)
        Host outward normal at the footprint centroid.
    footprint_centre : ndarray, shape (3,)
        Designed position of the footprint centroid, m.
    notes : list of str
        Geometry adjustments made while meshing (tape shifts off tangencies).
    """

    spec: AppendageSpec
    model: SolverModel
    chart: FloatArray
    skin_triangles: IntArray
    footprint_triangles: IntArray
    host_triangles: IntArray
    rim_nodes: IntArray
    match_nodes: IntArray
    rim_tape: str | None
    host_tape_names: list[str]
    boundary_nodes: IntArray
    ease: RimEase | None
    feed: FeedPressure | None
    chamber: PressureChamber
    footprint_normal: FloatArray
    footprint_centre: FloatArray
    notes: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------------------
# Meshing helpers
# --------------------------------------------------------------------------------------


class _Gmsh:
    def __enter__(self) -> _Gmsh:
        import gmsh

        self.owner = not gmsh.isInitialized()
        if self.owner:
            gmsh.initialize(interruptible=False)
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("General.NumThreads", 1)
        gmsh.option.setNumber("Mesh.RandomSeed", 1)
        gmsh.option.setNumber("Mesh.Algorithm", 6)
        return self

    def __exit__(self, *exc: object) -> None:
        import gmsh

        gmsh.clear()
        if self.owner:
            gmsh.finalize()


def _read_mesh() -> tuple[FloatArray, IntArray]:
    import gmsh

    tags, coords, _ = gmsh.model.mesh.getNodes()
    xy = np.asarray(coords, dtype=np.float64).reshape(-1, 3)[:, :2]
    types, _, nodes = gmsh.model.mesh.getElements(2)
    tri_parts = [
        np.asarray(n, dtype=np.int64).reshape(-1, 3)
        for t, n in zip(types, nodes, strict=True)
        if t == 2
    ]
    if not tri_parts:
        raise FeatureBuildError("Gmsh produced no triangles")
    tri = np.concatenate(tri_parts)
    lookup = np.full(int(np.max(tags)) + 1, -1, dtype=np.int64)
    lookup[np.asarray(tags, dtype=np.int64)] = np.arange(len(tags))
    tri = lookup[tri]
    used = np.unique(tri)
    remap = np.full(len(xy), -1, dtype=np.int64)
    remap[used] = np.arange(len(used))
    return xy[used], remap[tri]


def _ccw(xy: FloatArray, tri: IntArray) -> IntArray:
    a = xy[tri[:, 1]] - xy[tri[:, 0]]
    b = xy[tri[:, 2]] - xy[tri[:, 0]]
    cw = a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0] < 0
    out = tri.copy()
    out[cw] = out[cw][:, [0, 2, 1]]
    return out


def resample_loop(points: FloatArray, size: float) -> FloatArray:
    """Closed polyline resampled at about ``size`` spacing (vertices kept at corners), m."""
    length = loop_length(points)
    count = max(12, int(math.ceil(length / size)))
    return point_on_loop(points, np.linspace(0.0, length, count, endpoint=False))


def _resample_open(points: FloatArray, size: float) -> FloatArray:
    seg = np.linalg.norm(np.diff(points, axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    count = max(2, int(math.ceil(cum[-1] / size)) + 1)
    s = np.linspace(0.0, cum[-1], count)
    return np.column_stack([np.interp(s, cum, points[:, k]) for k in range(2)])


def _segment_hits(
    a: FloatArray, b: FloatArray, closed_a: bool
) -> list[tuple[int, int, FloatArray]]:
    """Intersections of polyline ``a`` (closed or open) with open polyline ``b``."""
    na = len(a) if closed_a else len(a) - 1
    out = []
    p0, p1 = a[:na], np.roll(a, -1, axis=0)[:na]
    for j in range(len(b) - 1):
        q0, q1 = b[j], b[j + 1]
        r = p1 - p0
        sv = q1 - q0
        den = r[:, 0] * sv[1] - r[:, 1] * sv[0]
        ok = np.abs(den) > 1e-15
        qp = q0 - p0
        t = np.where(ok, (qp[:, 0] * sv[1] - qp[:, 1] * sv[0]) / np.where(ok, den, 1.0), -1.0)
        u = np.where(ok, (qp[:, 0] * r[:, 1] - qp[:, 1] * r[:, 0]) / np.where(ok, den, 1.0), -1.0)
        hit = ok & (t >= 0.0) & (t < 1.0) & (u >= 0.0) & (u <= 1.0)
        for i in np.flatnonzero(hit):
            out.append((int(i), j, p0[i] + t[i] * r[i]))
    return out


def conform_tapes(
    footprint: FloatArray, tapes: list[FloatArray], size: float, names: Sequence[str]
) -> tuple[FloatArray, list[FloatArray], list[str]]:
    """Make tape lines and the footprint line meet cleanly before meshing.

    Where a tape crosses the footprint, the crossing point is inserted into both lines
    and their vertices within ``0.3 size`` of it are removed (no sliver elements).
    Where a tape only touches the footprint (a tangency, e.g. a row seam at the top of
    a footprint that spans whole rows), the tape is moved away from the footprint until
    they are ``0.3 size`` apart, and a note records the shift.

    Parameters
    ----------
    footprint : ndarray, shape (k, 2)
        Closed footprint line, m.
    tapes : list of ndarray
        Open tape lines, m.
    size : float
        Mesh size, m.
    names : sequence of str
        Tape names (for the notes).

    Returns
    -------
    footprint : ndarray
        Footprint with the crossings inserted, m.
    tapes : list of ndarray
        Conformed tape lines, m.
    notes : list of str
        Shifts applied.
    """
    clear = 0.3 * size
    fp = footprint.copy()
    out: list[FloatArray] = []
    notes: list[str] = []
    centre = fp.mean(axis=0)
    for tape, name in zip(tapes, names, strict=True):
        line = tape.copy()
        hits: list[tuple[int, int, FloatArray]] = []
        for hit in _segment_hits(fp, line, True):
            if all(np.linalg.norm(hit[2] - h[2]) > 1e-9 for h in hits):
                hits.append(hit)
        # A tape that touches without crossing meets the closed footprint an odd number of
        # times (once at the touching point) or twice very close together.
        close = (
            len(hits) % 2 == 1
            or len(hits) >= 2
            and any(
                np.linalg.norm(h1[2] - h2[2]) < 2.0 * clear
                for k, h1 in enumerate(hits)
                for h2 in hits[k + 1 :]
            )
        )
        gap = float(distance_to_polyline(fp, line, False).min())
        if close or (not hits and gap < clear):
            # Tangency: move the tape away from the footprint.
            k = int(np.argmin(distance_to_polyline(fp, line, False)))
            j = int(np.clip(np.argmin(np.linalg.norm(line - fp[k], axis=1)), 0, len(line) - 2))
            t = line[j + 1] - line[j]
            n = np.array([-t[1], t[0]]) / np.linalg.norm(t)
            if (centre - line[j]) @ n < 0.0:
                n = -n
            near = np.linalg.norm(fp - fp[k], axis=1) < 4.0 * size
            depth = float(((fp[near] - line[j]) @ n).min())
            shift = depth - clear
            line = line + shift * n
            notes.append(
                f"tape {name} moved {abs(shift) * 1000:.0f} mm off a tangency with the footprint"
            )
            out.append(line)
            continue
        for i, _, point in sorted(hits, key=lambda h: -h[0]):
            if np.linalg.norm(fp - point, axis=1).min() > 1e-9:
                fp = np.insert(fp, i + 1, point, axis=0)
        for _, j, point in sorted(hits, key=lambda h: -h[1]):
            if np.linalg.norm(line - point, axis=1).min() > 1e-9:
                line = np.insert(line, j + 1, point, axis=0)
        for _, _, point in hits:
            dist_fp = np.linalg.norm(fp - point, axis=1)
            fp = fp[(dist_fp >= clear) | (dist_fp < 1e-12)]
            dist_t = np.linalg.norm(line - point, axis=1)
            keep = (dist_t >= clear) | (dist_t < 1e-12)
            keep[0] = keep[-1] = True
            line = line[keep]
        fp, line, moved = _share_close_runs(fp, line, clear)
        if moved > 0.0:
            notes.append(
                f"tape {name} follows the footprint line where they run within "
                f"{clear * 1000:.0f} mm (largest move {moved * 1000:.0f} mm)"
            )
        out.append(line)
    return fp, out, notes


def _project_on_line(line: FloatArray, point: FloatArray) -> tuple[float, FloatArray]:
    """Arc-length position (m) and closest point on an open polyline."""
    a, b = line[:-1], line[1:]
    ab = b - a
    t = np.clip(
        np.einsum("ij,ij->i", point - a, ab) / np.maximum(np.einsum("ij,ij->i", ab, ab), 1e-300),
        0.0,
        1.0,
    )
    proj = a + t[:, None] * ab
    k = int(np.argmin(np.linalg.norm(proj - point, axis=1)))
    cum = np.concatenate([[0.0], np.cumsum(np.linalg.norm(ab, axis=1))])
    return float(cum[k] + t[k] * np.linalg.norm(ab[k])), proj[k]


def _share_close_runs(
    fp: FloatArray, line: FloatArray, clear: float
) -> tuple[FloatArray, FloatArray, float]:
    """Let a tape follow the footprint where the two run within ``clear`` of each other.

    Runs of consecutive footprint vertices closer than ``clear`` to the tape replace the
    tape between the projections of their end vertices, so the two lines share those
    vertices exactly instead of forming sliver elements.
    """
    d = distance_to_polyline(fp, line, False)
    near = d < clear
    n = len(fp)
    if not near.any() or near.all():
        return fp, line, 0.0
    # Cyclic runs of near footprint vertices with at least two members.
    start = int(np.flatnonzero(~near)[0])
    runs: list[list[int]] = []
    current: list[int] = []
    for step in range(1, n + 1):
        k = (start + step) % n
        if near[k]:
            current.append(k)
        elif current:
            runs.append(current)
            current = []
    if current:
        runs.append(current)
    moved = 0.0
    cum = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(line, axis=0), axis=1))])
    pieces = []
    for run in runs:
        if len(run) < 2 or float(d[run].max()) < 1e-12 and len(run) < 3:
            continue
        s_a, _ = _project_on_line(line, fp[run[0]])
        s_b, _ = _project_on_line(line, fp[run[-1]])
        path = fp[run]
        if s_b < s_a:
            s_a, s_b = s_b, s_a
            path = path[::-1]
        pieces.append((s_a, s_b, path))
        moved = max(moved, float(d[run].max()))
    if not pieces:
        return fp, line, 0.0
    pieces.sort(key=lambda p: p[0])
    out = []
    cursor = -1.0
    for s_a, s_b, path in pieces:
        keep = (cum > cursor) & (cum < s_a - clear)
        out.append(line[keep])
        out.append(path)
        cursor = s_b + clear
    out.append(line[cum > cursor])
    new_line = np.vstack([o for o in out if len(o)])
    if np.linalg.norm(new_line[0] - line[0]) > 1e-12:
        new_line = np.vstack([line[:1], new_line])
    if np.linalg.norm(new_line[-1] - line[-1]) > 1e-12:
        new_line = np.vstack([new_line, line[-1:]])
    return fp, new_line, moved


def _near_edge(line: FloatArray, rect: tuple[float, float, float, float], clear: float) -> bool:
    """True when an interior stretch of the line runs within ``clear`` of a patch side."""
    x0, y0, x1, y1 = rect
    inside = (line[:, 0] > x0) & (line[:, 0] < x1) & (line[:, 1] > y0) & (line[:, 1] < y1)
    pts = line[inside]
    if len(pts) < 2:
        return False
    gap = np.minimum.reduce([pts[:, 0] - x0, x1 - pts[:, 0], pts[:, 1] - y0, y1 - pts[:, 1]])
    return bool(np.sum(gap < clear) >= 2)


def _mesh_host(
    rect: tuple[float, float, float, float],
    footprint: FloatArray,
    holes: Sequence[ChartHole],
    tapes: Sequence[FloatArray],
    size: float,
) -> tuple[FloatArray, IntArray]:
    import gmsh

    gmsh.clear()
    gmsh.model.add("host patch")
    occ = gmsh.model.occ
    x0, y0, x1, y1 = rect
    surf: list[tuple[int, int]] = [(2, occ.addRectangle(x0, y0, 0.0, x1 - x0, y1 - y0))]
    if holes:
        disks = [(2, occ.addDisk(h.centre[0], h.centre[1], 0.0, h.radius, h.radius)) for h in holes]
        surf, _ = occ.cut(surf, disks)
    curves: list[tuple[int, int]] = []
    pts = [occ.addPoint(float(x), float(y), 0.0) for x, y in footprint]
    n = len(pts)
    curves += [(1, occ.addLine(pts[i], pts[(i + 1) % n])) for i in range(n)]
    fp_segments = {
        (tuple(np.round(footprint[i], 9)), tuple(np.round(footprint[(i + 1) % n], 9)))
        for i in range(n)
    }
    fp_segments |= {(b, a) for a, b in fp_segments}
    for line in tapes:
        for i in range(len(line) - 1):
            key = (tuple(np.round(line[i], 9)), tuple(np.round(line[i + 1], 9)))
            if key in fp_segments or np.linalg.norm(line[i + 1] - line[i]) < 1e-9:
                continue
            a = occ.addPoint(float(line[i, 0]), float(line[i, 1]), 0.0)
            b = occ.addPoint(float(line[i + 1, 0]), float(line[i + 1, 1]), 0.0)
            curves.append((1, occ.addLine(a, b)))
    occ.fragment(surf, curves)
    occ.synchronize()
    gmsh.option.setNumber("Mesh.MeshSizeMax", size)
    gmsh.option.setNumber("Mesh.MeshSizeMin", 0.25 * size)
    gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
    gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
    gmsh.model.mesh.generate(2)
    xy, tri = _read_mesh()
    # Drop triangles in holes (fragment keeps free curves but not the removed disks).
    return xy, _ccw(xy, tri)


def _mesh_disc(boundary: FloatArray, size: float) -> tuple[FloatArray, IntArray]:
    """Triangulate a polygon keeping its vertices as the only boundary nodes."""
    import gmsh

    gmsh.clear()
    gmsh.model.add("skin")
    geo = gmsh.model.geo
    pts = [geo.addPoint(float(x), float(y), 0.0, size) for x, y in boundary]
    n = len(pts)
    lines = [geo.addLine(pts[i], pts[(i + 1) % n]) for i in range(n)]
    loop = geo.addCurveLoop(lines)
    geo.addPlaneSurface([loop])
    geo.synchronize()
    for line in lines:
        gmsh.model.mesh.setTransfiniteCurve(line, 2)
    gmsh.option.setNumber("Mesh.MeshSizeMax", size)
    gmsh.option.setNumber("Mesh.MeshSizeMin", 0.25 * size)
    gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 1)
    gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 1)
    gmsh.model.mesh.generate(2)
    xy, tri = _read_mesh()
    return xy, _ccw(xy, tri)


def _edges_on(
    xy: FloatArray,
    tri: IntArray,
    polyline: FloatArray,
    closed: bool,
    tol: float,
    mid_tol: float | None = None,
) -> IntArray:
    edges = np.unique(
        np.sort(np.concatenate([tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]]), axis=1), axis=0
    )
    near = distance_to_polyline(xy, polyline, closed) < tol
    cand: IntArray = edges[near[edges[:, 0]] & near[edges[:, 1]]]
    if not len(cand):
        return cand
    mid = 0.5 * (xy[cand[:, 0]] + xy[cand[:, 1]])
    limit = tol if mid_tol is None else mid_tol
    out: IntArray = cand[distance_to_polyline(mid, polyline, closed) < limit]
    return out


def _order_loop(edges: IntArray) -> IntArray:
    nbr: dict[int, list[int]] = {}
    for a, b in edges:
        nbr.setdefault(int(a), []).append(int(b))
        nbr.setdefault(int(b), []).append(int(a))
    if any(len(v) != 2 for v in nbr.values()):
        raise FeatureBuildError("footprint line is not a simple closed loop in the mesh")
    start = min(nbr)
    loop = [start, nbr[start][0]]
    while True:
        a, b = nbr[loop[-1]]
        nxt = a if a != loop[-2] else b
        if nxt == start:
            break
        loop.append(nxt)
    if len(loop) != len(nbr):
        raise FeatureBuildError("footprint line splits into several loops")
    return np.array(loop, dtype=np.int64)


def _harmonic(n: int, tri: IntArray, fixed: IntArray, values: FloatArray) -> FloatArray:
    """Graph-harmonic extension of ``values`` (at ``fixed``) to all nodes [Tutte]_."""
    e = np.concatenate([tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]])
    e = np.concatenate([e, e[:, ::-1]])
    adj = coo_matrix((np.ones(len(e)), (e[:, 0], e[:, 1])), shape=(n, n)).tocsr()
    adj.data[:] = 1.0
    deg = np.asarray(adj.sum(axis=1)).ravel()
    lap = (coo_matrix((deg, (np.arange(n), np.arange(n))), shape=(n, n)) - adj).tocsr()
    free = np.setdiff1d(np.arange(n), fixed)
    out = np.zeros((n, values.shape[1]))
    out[fixed] = values
    if len(free):
        rhs = -lap[free][:, fixed] @ values
        sol = spsolve(lap[free][:, free].tocsc(), rhs)
        out[free] = np.asarray(sol).reshape(len(free), -1)
    return out


def _bubble(n: int, tri: IntArray, fixed: IntArray) -> FloatArray:
    """Solution of the graph Poisson problem L phi = 1, phi = 0 on ``fixed``, max 1."""
    e = np.concatenate([tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]])
    e = np.concatenate([e, e[:, ::-1]])
    adj = coo_matrix((np.ones(len(e)), (e[:, 0], e[:, 1])), shape=(n, n)).tocsr()
    adj.data[:] = 1.0
    deg = np.asarray(adj.sum(axis=1)).ravel()
    lap = (coo_matrix((deg, (np.arange(n), np.arange(n))), shape=(n, n)) - adj).tocsr()
    free = np.setdiff1d(np.arange(n), fixed)
    phi = np.zeros(n)
    if len(free):
        phi[free] = spsolve(lap[free][:, free].tocsc(), np.ones(len(free)))
    return phi / max(float(phi.max()), 1e-300)


def _frame_uv(x: FloatArray, tri: IntArray, t_u: FloatArray) -> FloatArray:
    """Corner coordinates of each triangle in its plane, first axis along ``t_u``."""
    xe = x[tri]
    nrm = np.cross(xe[:, 1] - xe[:, 0], xe[:, 2] - xe[:, 0])
    nrm /= np.linalg.norm(nrm, axis=1)[:, None]
    e1 = t_u - np.einsum("mi,mi->m", t_u, nrm)[:, None] * nrm
    e1 /= np.linalg.norm(e1, axis=1)[:, None]
    e2 = np.cross(nrm, e1)
    d = xe - xe[:, :1]
    return np.stack([np.einsum("mki,mi->mk", d, e1), np.einsum("mki,mi->mk", d, e2)], axis=2)


def _prestretch(
    material: MembraneMaterial, n_u: float, n_v: float, grain_u: bool
) -> tuple[float, float]:
    comp = np.linalg.inv(material.plane_stress_matrix())
    n = np.array([n_u, n_v, 0.0]) if grain_u else np.array([n_v, n_u, 0.0])
    e = comp @ n
    e_u, e_v = (e[0], e[1]) if grain_u else (e[1], e[0])
    return math.sqrt(1.0 + 2.0 * e_u), math.sqrt(1.0 + 2.0 * e_v)


def _rest_lengths(edges: IntArray, tri: IntArray, uv: FloatArray, subset: IntArray) -> FloatArray:
    lengths: dict[tuple[int, int], list[float]] = {}
    for t in subset:
        for a, b in ((0, 1), (1, 2), (2, 0)):
            key = (int(min(tri[t, a], tri[t, b])), int(max(tri[t, a], tri[t, b])))
            lengths.setdefault(key, []).append(float(np.linalg.norm(uv[t, a] - uv[t, b])))
    out = np.empty(len(edges))
    for k, (i, j) in enumerate(edges):
        key = (int(min(i, j)), int(max(i, j)))
        if key not in lengths:
            raise FeatureBuildError(f"edge ({i}, {j}) is not a host edge")
        out[k] = float(np.mean(lengths[key]))
    return out


def _loop_edges(loop: IntArray) -> IntArray:
    return np.column_stack([loop, np.roll(loop, -1)])


def _start_index(points: FloatArray, direction: tuple[float, float] | None) -> int:
    centre = points.mean(axis=0)
    d = np.array(direction if direction is not None else (-1.0, 0.0), dtype=np.float64)
    return int(np.argmax((points - centre) @ d))


# --------------------------------------------------------------------------------------
# Builder
# --------------------------------------------------------------------------------------


def build_appendage(
    spec: AppendageSpec,
    conditions: OperatingConditions,
    materials: Mapping[str, MembraneMaterial],
) -> AppendageModel:
    """Assemble an appendage sub-model (see module docstring).

    Parameters
    ----------
    spec : AppendageSpec
        Geometry (m), materials by zone, tapes, holes and pressure specification.
    conditions : OperatingConditions
        Envelope load case; the host pressure and a ``fed`` chamber derive from it.
    materials : mapping of str to MembraneMaterial
        Fabric per zone (``spec.host_zone`` and ``spec.skin_zone``).

    Returns
    -------
    AppendageModel
        Solver model and index sets.

    Raises
    ------
    FeatureBuildError
        For inconsistent geometry, missing materials or a fed chamber without holes.
    """
    for zone in {spec.skin_zone} | ({spec.host_zone} if spec.host is not None else set()):
        if zone not in materials:
            raise FeatureBuildError(f"{spec.name}: no material for zone {zone!r}")
    size = spec.mesh_size
    fp = orient_ccw(np.asarray(spec.footprint, dtype=np.float64))
    if spec.skin_mode != "designed":
        fp = resample_loop(fp, size)
    elif spec.skin_mesh is None:
        raise FeatureBuildError(f"{spec.name}: a designed skin needs a skin factory")
    lo, hi = fp.min(axis=0), fp.max(axis=0)
    tol = 1e-6 * max(float((hi - lo).max()), 1.0)
    host = spec.host
    tapes = list(spec.host_tapes) if host is not None else []

    with _Gmsh():
        if host is not None:
            margin = spec.margin if spec.margin is not None else 0.5 * float((hi - lo).max())
            rect = (lo[0] - margin, lo[1] - margin, hi[0] + margin, hi[1] + margin)
            tape_lines = [_resample_open(t.polyline, size) for t in tapes]
            # Tapes running along the patch edge would make sliver elements; they lie in
            # the fixed far field anyway.
            clear = 0.3 * size
            kept = [
                k
                for k, line in enumerate(tape_lines)
                if not (
                    np.abs(line[:, 0] - rect[0]).min() < clear
                    and np.ptp(line[:, 0]) < clear
                    or np.abs(line[:, 0] - rect[2]).min() < clear
                    and np.ptp(line[:, 0]) < clear
                    or np.abs(line[:, 1] - rect[1]).min() < clear
                    and np.ptp(line[:, 1]) < clear
                    or np.abs(line[:, 1] - rect[3]).min() < clear
                    and np.ptp(line[:, 1]) < clear
                )
                and _near_edge(line, rect, clear) is False
            ]
            dropped = [tapes[k].name for k in range(len(tapes)) if k not in kept]
            tapes = [tapes[k] for k in kept]
            tape_lines = [tape_lines[k] for k in kept]
            fp, tape_lines, notes = conform_tapes(fp, tape_lines, size, [t.name for t in tapes])
            notes += [f"tape {n} runs along the patch edge and is left out" for n in dropped]
            xy_h, tri_h = _mesh_host(rect, fp, spec.holes, tape_lines, size)
        else:
            if spec.holes:
                raise FeatureBuildError(f"{spec.name}: holes need a host")
            xy_h = fp.copy()
            tri_h = np.zeros((0, 3), dtype=np.int64)
            notes = []
        # Footprint loop in the host mesh, ordered counter-clockwise from match point 1.
        if host is not None:
            loop = _order_loop(_edges_on(xy_h, tri_h, fp, True, tol))
            if _signed(xy_h[loop]) < 0:
                loop = loop[::-1]
        else:
            loop = np.arange(len(fp))
        start = _start_index(xy_h[loop], spec.match_start)
        loop = np.roll(loop, -start)
        rim_xy = xy_h[loop]
        s_fp = loop_arclength(rim_xy)
        l_fp = loop_length(rim_xy)

        # Skin pattern with rim points matched to the footprint nodes.
        ease: RimEase | None = None
        designed: DesignedSkin | None = None
        if spec.skin_mode == "designed":
            assert spec.skin_mesh is not None
            designed = spec.skin_mesh(rim_xy, size)
            notes += designed.notes
            rim_pattern = rim_xy.copy()
        elif spec.skin_mode == "flat_pattern":
            if spec.skin_outline is None:
                raise FeatureBuildError(f"{spec.name}: flat_pattern skin needs an outline")
            skin = orient_ccw(np.asarray(spec.skin_outline, dtype=np.float64))
            k0 = _start_index(skin, spec.match_start)
            skin = np.roll(skin, -k0, axis=0)
            l_sk = loop_length(skin)
            ease = rim_ease(l_fp, l_sk, spec.match_points, spec.ease_mode)
            rim_pattern = point_on_loop(skin, rim_correspondence(s_fp, ease))
        else:
            if spec.cap_height is None or spec.cap_height <= 0.0:
                raise FeatureBuildError(f"{spec.name}: spherical_cap skin needs cap_height > 0")
            rim_pattern = rim_xy.copy()
        if designed is None:
            xy_s, tri_s = _mesh_disc(rim_pattern, size)

    n_h = len(xy_h)
    if designed is not None:
        tri_s = designed.triangles
        n_s = len(designed.positions)
        skin_rim = designed.rim_index
        if len(skin_rim) != len(loop) or len(np.unique(skin_rim)) != len(loop):
            raise FeatureBuildError(f"{spec.name}: skin rim nodes do not match the footprint")
    else:
        # Match skin rim nodes to the prescribed rim points (one per footprint node).
        tree = cKDTree(xy_s)
        dist, skin_rim = tree.query(rim_pattern)
        if np.any(dist > 1e-6 * max(l_fp, 1.0)) or len(np.unique(skin_rim)) != len(loop):
            raise FeatureBuildError(f"{spec.name}: skin rim nodes do not match the footprint")
        n_s = len(xy_s)
    skin_map = np.full(n_s, -1, dtype=np.int64)
    skin_map[skin_rim] = loop
    interior = np.flatnonzero(skin_map < 0)
    skin_map[interior] = n_h + np.arange(len(interior))
    n = n_h + len(interior)
    tri_skin = skin_map[tri_s]

    # 3D positions: host from the chart, skin from a harmonic chart image lifted outward.
    chart = np.zeros((n, 2))
    chart[:n_h] = xy_h
    skin_chart = _harmonic(n_s, tri_s, skin_rim, rim_xy)
    chart[skin_map] = skin_chart
    if host is not None:
        base = host.map(chart)
        normal = host.normal(chart)
    else:
        base = np.column_stack([chart, np.zeros(n)])
        normal = np.tile([0.0, 0.0, 1.0], (n, 1))
    area_fp = abs(_signed(rim_xy))
    radius_eq = math.sqrt(area_fp / math.pi)
    positions = base.copy()
    if designed is not None:
        # Designed shape, moved so its rim lies on the host footprint: the rim offset
        # (true envelope against the fitted host) is spread harmonically over the skin.
        offset = _harmonic(n_s, tri_s, skin_rim, base[loop] - designed.positions[skin_rim])
        sk = np.flatnonzero(skin_map >= n_h)
        positions[skin_map[sk]] = designed.positions[sk] + offset[sk]
    elif spec.skin_mode == "spherical_cap":
        h = float(spec.cap_height)  # type: ignore[arg-type]
        rc = (radius_eq**2 + h**2) / (2.0 * h)
        centre = rim_xy.mean(axis=0)
        r = np.linalg.norm(skin_chart - centre, axis=1) / radius_eq
        psi_max = (
            math.asin(min(radius_eq / rc, 1.0)) if h <= rc else math.pi - math.asin(radius_eq / rc)
        )
        psi = np.clip(r, 0.0, 1.0) * psi_max
        rad = rc * np.sin(psi)
        direction = (skin_chart - centre) / np.maximum(
            np.linalg.norm(skin_chart - centre, axis=1), 1e-300
        )[:, None]
        flat = centre + direction * rad[:, None]
        lift = rc * np.cos(psi) - rc * math.cos(psi_max)
        chart_skin = flat
        if host is not None:
            skin_pos = host.map(chart_skin) + host.normal(chart_skin) * lift[:, None]
        else:
            skin_pos = np.column_stack([chart_skin, lift])
        sk = np.flatnonzero(skin_map >= n_h)
        positions[skin_map[sk]] = skin_pos[sk]
    else:
        # Equal-arc spherical-cap guess: a node at fraction s of the way from the
        # footprint centre to the rim (harmonic image) sits at polar angle s psi_m of a
        # cap over that direction, so radial lengths stretch uniformly. psi_m is chosen
        # so that the skin starts slightly slack (3D area INITIAL_SKIN_AREA of the rest
        # area): an over-stretched start makes the explicit solver take huge first steps.
        area_skin = _mesh_area(xy_s, tri_s)
        sk = np.flatnonzero(skin_map >= n_h)
        g = skin_map[sk]
        # Polar coordinates in the pattern about its centroid; pattern angles map to
        # footprint angles through the rim correspondence (skin rim node k meets
        # footprint node k), pattern radius fractions carry over unchanged.
        c_f = _polygon_centroid(rim_xy)
        rim_pat = xy_s[skin_rim]
        c_p = _polygon_centroid(rim_pat)
        pat_rel = xy_s[sk] - c_p
        pat_ang = np.arctan2(pat_rel[:, 1], pat_rel[:, 0])
        rim_pat_rel = rim_pat - c_p
        rim_pat_ang = np.unwrap(np.arctan2(rim_pat_rel[:, 1], rim_pat_rel[:, 0]))
        rim_fp_rel = rim_xy - c_f
        rim_fp_ang = np.unwrap(np.arctan2(rim_fp_rel[:, 1], rim_fp_rel[:, 0]))
        rim_fp_ang += 2.0 * math.pi * round((rim_pat_ang[0] - rim_fp_ang[0]) / (2.0 * math.pi))
        order = np.argsort(rim_pat_ang)
        wrap = np.concatenate
        xp = wrap(
            [rim_pat_ang[order] - 2 * math.pi, rim_pat_ang[order], rim_pat_ang[order] + 2 * math.pi]
        )
        fp_ang_of = wrap(
            [rim_fp_ang[order] - 2 * math.pi, rim_fp_ang[order], rim_fp_ang[order] + 2 * math.pi]
        )
        pat_r_of = np.tile(np.linalg.norm(rim_pat_rel, axis=1)[order], 3)
        fp_r_of = np.tile(np.linalg.norm(rim_fp_rel, axis=1)[order], 3)
        base_ang = rim_pat_ang[order][0]
        pa = base_ang + np.mod(pat_ang - base_ang, 2.0 * math.pi)
        frac = np.clip(np.linalg.norm(pat_rel, axis=1) / np.interp(pa, xp, pat_r_of), 0.0, 1.0)
        chart_ang = np.interp(pa, xp, fp_ang_of)
        direction = np.column_stack([np.cos(chart_ang), np.sin(chart_ang)])
        rim_dir_ang = np.arctan2(rim_fp_rel[:, 1], rim_fp_rel[:, 0])
        order_f = np.argsort(rim_dir_ang)
        radius_dir = np.interp(
            chart_ang,
            rim_dir_ang[order_f],
            np.linalg.norm(rim_fp_rel, axis=1)[order_f],
            period=2.0 * math.pi,
        )
        _ = fp_r_of

        def cap(psi_m: float) -> FloatArray:
            psi = frac * psi_m
            horizontal = radius_dir * np.sin(psi) / math.sin(psi_m)
            lift = radius_dir * (np.cos(psi) - math.cos(psi_m)) / math.sin(psi_m)
            chart_pts = c_f + direction * horizontal[:, None]
            trial = positions.copy()
            if host is not None:
                trial[g] = host.map(chart_pts) + host.normal(chart_pts) * lift[:, None]
            else:
                trial[g] = np.column_stack([chart_pts, lift])
            return trial

        def cap_area(psi_m: float) -> float:
            e = cap(psi_m)[tri_skin]
            return 0.5 * float(
                np.linalg.norm(np.cross(e[:, 1] - e[:, 0], e[:, 2] - e[:, 0]), axis=1).sum()
            )

        target = INITIAL_SKIN_AREA * area_skin
        lo_psi, hi_psi = 1e-3, 0.5 * math.pi
        for _ in range(50):
            mid = 0.5 * (lo_psi + hi_psi)
            lo_psi, hi_psi = (mid, hi_psi) if cap_area(mid) < target else (lo_psi, mid)
        positions = cap(lo_psi)

    # Rest geometry.
    tri_all = np.concatenate([tri_h, tri_skin])
    m_h = len(tri_h)
    rest = np.zeros((len(tri_all), 3, 2))
    host_prestress = (0.0, 0.0)
    if host is not None and m_h:
        centre_uv = xy_h[tri_h].mean(axis=1)
        t_u = host.tangent_u(centre_uv)
        uv = _frame_uv(positions, tri_h, t_u)
        p_centre = float(conditions.pressure(np.array([host.centre_height]))[0])
        host_prestress = (
            spec.prestress if spec.prestress is not None else shell_prestress(p_centre, host)
        )
        grain_u = abs(spec.host_grain[0]) >= abs(spec.host_grain[1])
        lam_u, lam_v = _prestretch(materials[spec.host_zone], *host_prestress, grain_u)
        uv[:, :, 0] /= lam_u
        uv[:, :, 1] /= lam_v
        rest[:m_h] = uv
    if designed is not None:
        rest[m_h:] = designed.rest_uv
    elif spec.skin_mode == "flat_pattern":
        rest[m_h:] = xy_s[tri_s]
    else:
        from envelopelab.validation.meshes import facet_rest_coordinates

        rest[m_h:] = facet_rest_coordinates(positions, tri_skin)

    # Orientation: host normals outward (chart CCW maps to outward), skin away from host.
    skin_idx = np.arange(m_h, len(tri_all))
    xe = positions[tri_all[skin_idx]]
    nrm = np.cross(xe[:, 1] - xe[:, 0], xe[:, 2] - xe[:, 0])
    if float(np.einsum("mi,mi->m", nrm, normal[tri_all[skin_idx, 0]]).sum()) < 0.0:
        raise FeatureBuildError(f"{spec.name}: skin orientation is inverted")

    # Zones and grain.
    zone_names = sorted({spec.skin_zone} | ({spec.host_zone} if host is not None else set()))
    tri_zone = np.concatenate(
        [
            np.full(m_h, zone_names.index(spec.host_zone) if host is not None else 0),
            np.full(len(tri_skin), zone_names.index(spec.skin_zone)),
        ]
    )
    grain = np.zeros((len(tri_all), 2))
    grain[:m_h] = (1.0, 0.0) if abs(spec.host_grain[0]) >= abs(spec.host_grain[1]) else (0.0, 1.0)
    grain[m_h:] = designed.grain if designed is not None else spec.skin_grain

    # Chambers.
    feed: FeedPressure | None = None
    if spec.pressure.mode == "fed":
        if host is None or not spec.holes:
            raise FeatureBuildError(f"{spec.name}: a fed chamber needs feed holes in a host")
        heights = host.map(np.array([h.centre for h in spec.holes]))[:, 2]
        holes = [
            FeedHole(h.name, float(z), h.area) for h, z in zip(spec.holes, heights, strict=True)
        ]
        feed = fed_chamber(spec.name, conditions, holes, spec.pressure.loss_factor)
        chamber = feed.chamber
    else:
        if spec.pressure.chamber is None:
            raise FeatureBuildError(f"{spec.name}: independent pressure needs a chamber")
        chamber = spec.pressure.chamber
        if chamber.name != spec.name:
            chamber = PressureChamber(
                spec.name,
                chamber.reference_pressure,
                chamber.reference_height,
                chamber.gradient,
                chamber.source,
                chamber.description,
            )
    fp_tris = (
        np.flatnonzero(points_in_polygon(xy_h[tri_h].mean(axis=1), rim_xy))
        if m_h
        else np.zeros(0, np.int64)
    )
    tri_chambers = np.empty((len(tri_all), 2), dtype=np.int64)
    tri_chambers[:m_h] = (MAIN_CHAMBER, AMBIENT)
    tri_chambers[fp_tris] = (MAIN_CHAMBER, 0)
    tri_chambers[m_h:] = (0, AMBIENT)

    # Constraints.
    if host is not None:
        x0, y0, x1, y1 = rect
        edge = (
            (np.abs(xy_h[:, 0] - x0) < tol)
            | (np.abs(xy_h[:, 0] - x1) < tol)
            | (np.abs(xy_h[:, 1] - y0) < tol)
            | (np.abs(xy_h[:, 1] - y1) < tol)
        )
        boundary = np.flatnonzero(edge)
        constraints = [NodeConstraint("host boundary", boundary)]
    else:
        boundary = loop.copy()
        constraints = [NodeConstraint("rigid rim", boundary)]

    # Tapes and seams.
    cables: list[CableSet] = []
    seams = [SeamLine(f"{spec.name}:rim", _loop_edges(loop))]
    if designed is not None:
        seams += [SeamLine(name, skin_map[e]) for name, e in designed.seams.items() if len(e)]
    host_subset = np.arange(m_h)
    host_tape_names: list[str] = []
    crossing_nodes: list[int] = []
    for tape, line in zip(tapes, tape_lines if host is not None else [], strict=True):
        edges = _edges_on(xy_h, tri_h, line, False, tol)
        if not len(edges):
            continue
        name = f"{spec.name}:host:{tape.name}"
        cables.append(
            CableSet(name, edges, tape.material, _rest_lengths(edges, tri_all, rest, host_subset))
        )
        seams.append(SeamLine(name, edges))
        host_tape_names.append(name)
        crossing_nodes += [int(i) for i in np.intersect1d(np.unique(edges), loop)]
    for hole in spec.holes:
        if hole.hem_tape is None:
            continue
        circle = np.array(
            [
                (
                    hole.centre[0] + hole.radius * math.cos(t),
                    hole.centre[1] + hole.radius * math.sin(t),
                )
                for t in np.linspace(0.0, 2.0 * math.pi, 720, endpoint=False)
            ]
        )
        # Nodes lie on the circle; chord midpoints sit up to one sagitta inside it.
        sagitta = size**2 / (8.0 * hole.radius) + 1e-3 * hole.radius
        edges = _edges_on(xy_h, tri_h, circle, True, 1e-3 * hole.radius, sagitta)
        if len(edges):
            name = f"{spec.name}:hem:{hole.name}"
            cables.append(
                CableSet(
                    name, edges, hole.hem_tape, _rest_lengths(edges, tri_all, rest, host_subset)
                )
            )
    rim_tape_name: str | None = None
    if spec.rim_tape is not None:
        edges = _loop_edges(loop)
        if not spec.rim_tape.caught_into_host_tapes and crossing_nodes:
            gap = spec.rim_tape.gap if spec.rim_tape.gap is not None else 2.0 * size
            s_node = s_fp  # arc length of each loop node
            s_cross = np.array([s_fp[int(np.flatnonzero(loop == c)[0])] for c in crossing_nodes])
            seg_mid = 0.5 * (s_node + np.roll(s_node, -1))
            seg_mid[-1] = 0.5 * (s_node[-1] + l_fp)
            gaps = np.abs(seg_mid[:, None] - s_cross[None, :])
            gaps = np.minimum(gaps, l_fp - gaps).min(axis=1)
            edges = edges[gaps > gap]
        if spec.host is None:
            lengths = np.linalg.norm(positions[edges[:, 1]] - positions[edges[:, 0]], axis=1)
        else:
            lengths = _rest_lengths(edges, tri_all, rest, host_subset)
        rim_tape_name = f"{spec.name}:rim tape"
        cables.append(CableSet(rim_tape_name, edges, spec.rim_tape.material, lengths))

    match_nodes = loop[
        [
            int(np.argmin(np.abs(s_fp - j * l_fp / spec.match_points)))
            for j in range(spec.match_points)
        ]
    ]
    centre_uv = rim_xy.mean(axis=0)[None, :]
    if host is not None:
        fp_normal = host.normal(centre_uv)[0]
        fp_centre = host.map(centre_uv)[0]
    else:
        fp_normal = np.array([0.0, 0.0, 1.0])
        fp_centre = np.array([centre_uv[0, 0], centre_uv[0, 1], 0.0])
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
        seams=seams,
        constraints=constraints,
        chambers=[chamber],
        tri_chambers=tri_chambers,
        name=f"appendage {spec.name}",
    )
    return AppendageModel(
        spec=spec,
        model=model,
        chart=chart,
        skin_triangles=skin_idx,
        footprint_triangles=fp_tris,
        host_triangles=np.setdiff1d(host_subset, fp_tris),
        rim_nodes=loop,
        match_nodes=match_nodes,
        rim_tape=rim_tape_name,
        host_tape_names=host_tape_names,
        boundary_nodes=boundary,
        ease=ease,
        feed=feed,
        chamber=chamber,
        footprint_normal=fp_normal,
        footprint_centre=fp_centre,
        notes=notes,
    )


def _polygon_centroid(points: FloatArray) -> FloatArray:
    x, y = points[:, 0], points[:, 1]
    cross = x * np.roll(y, -1) - np.roll(x, -1) * y
    a = 3.0 * cross.sum()
    return np.array(
        [((x + np.roll(x, -1)) * cross).sum() / a, ((y + np.roll(y, -1)) * cross).sum() / a]
    )


def _signed(points: FloatArray) -> float:
    x, y = points[:, 0], points[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def _mesh_area(xy: FloatArray, tri: IntArray) -> float:
    a = xy[tri[:, 1]] - xy[tri[:, 0]]
    b = xy[tri[:, 2]] - xy[tri[:, 0]]
    return float(np.abs(a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0]).sum() / 2.0)


__all__ = [
    "AppendageModel",
    "AppendageSpec",
    "ChartHole",
    "FeatureBuildError",
    "HostSurface",
    "HostTape",
    "PressureSpec",
    "RimTapeSpec",
    "build_appendage",
    "resample_loop",
    "shell_prestress",
]
