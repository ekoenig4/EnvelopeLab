r"""Solved tape meridian of a run, its deviation from the drawn profile, and profile updates.

The drawn meridian profile of a standard-gore design is the *intended* tape line. The
patterns cut from it inflate to a shape set by equilibrium, which can differ noticeably
(tape stretch, lobing, crown flattening). This module reads the solved tape line out of a
run's result arrays so the editor can show it over the drawn profile, measures the
difference, and offers two profile updates.

Solved tape line
----------------
The initial shape places gore :math:`g` of :math:`G` between azimuths
:math:`\theta = 2\pi g/G` and :math:`2\pi(g+1)/G`
(:func:`envelopelab.assembly.initial_shape.gore_revolution`), so the nodes of the vertical
seams (the load tapes) are the nodes whose *initial* azimuth is a multiple of
:math:`2\pi/G`. Each seam is walked from the mouth along the mesh edges joining its nodes;
a seam whose nodes do not form one simple path (a turning vent simulated open has two
unsewn edges on the same line) is skipped. Along a seam the material station is the
normalised arc length of the *initial* seam line,

.. math:: \sigma = \frac{1}{S}\int_0^{s} |\mathbf{x}_0'|\,ds \in [0, 1],

which equals :math:`s/L` of the drawn profile because the initial shape is a surface of
revolution parameterised by meridian arc length. The solved line is
:math:`(r, z) = (\sqrt{x^2 + y^2}, z)` of the solved positions, averaged over the seams at
common stations, and shifted in height so that the mouth (held fixed by the solver) sits
at the drawn profile's mouth height.

Profile updates
---------------
With :math:`\mathbf{C}(\sigma)` the drawn (cut) profile at :math:`s = \sigma L`,
:math:`\mathbf{Q}(\sigma)` the solved line of a run of that cut, :math:`\mathbf{T}` the
intended line and :math:`\sigma_i` the station of control point :math:`\mathbf{c}_i`:

* **Compensate** (pre-distort the cut so the inflated tape lands on the intended line, a
  fixed-point iteration of the inverse problem; one step per solve):

  .. math:: \mathbf{c}_i \leftarrow \mathbf{c}_i - \alpha\,
     \bigl(\mathbf{Q}(\sigma_i) - \mathbf{T}(\sigma_i)\bigr)

  :math:`\mathbf{T}` is the drawn profile on the first step; the caller keeps it (the
  project's :class:`~envelopelab.project.model.ProfileTarget`) so later steps do not
  drift with the cut. The step converges when the solved shape follows a change of the
  cut roughly one to one; measured on the generic fixture the error falls by a third to
  a half per step at :math:`\alpha = 1` (``docs/theory/profile-matching.md``). A step
  that does not reduce the deviation should be under-relaxed (:math:`\alpha < 1`).

* **Adopt** (make the drawn profile what the patterns actually fly):
  :math:`\mathbf{c}_i \leftarrow \mathbf{Q}(\sigma_i)`. Repeating it after each solve
  tends to a self-consistent profile whose patterns inflate onto themselves; the original
  intended shape is not kept.

Assumptions and valid range
---------------------------
Standard-gore rings only, solved with the mouth fixed (the setup of
:func:`envelopelab.project.simulation.build_solver_model`). The mapping by normalised
station assumes the tape stretch is nearly uniform along the tape (small, smoothly
varying tape strain). Axisymmetry is assumed: the seams are
averaged, and their spread is reported so an asymmetric result is visible.

References
----------
.. [Struik] D. J. Struik, *Lectures on Classical Differential Geometry*, Dover (1988):
   surfaces of revolution parameterised by meridian arc length.
.. [Bletzinger] K.-U. Bletzinger, R. Wüchner, F. Daoud and N. Camprubí, "Computational
   methods for form finding and optimization of shells and membranes", Computer Methods
   in Applied Mechanics and Engineering 194 (2005) 3438-3452: compensating a cutting
   pattern for the deformation under load.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

import numpy as np
from scipy.interpolate import CubicSpline

from envelopelab.design.model import DesignDocument
from envelopelab.geometry.gore import MeridianProfile
from envelopelab.geometry.polygon import FloatArray
from envelopelab.project.gore_design import control_arrays, design_profile, profile_from_arrays
from envelopelab.project.model import ProfileTarget, RunRecord
from envelopelab.project.session import ProjectSession

#: Tolerance on a seam node's initial azimuth, as a fraction of one gore's angle.
SEAM_AZIMUTH_TOLERANCE = 1e-6
#: Stations of the averaged solved line (dimensionless, mouth to top).
STATION_SAMPLES = 201
#: Fit tolerance of an updated profile, m (AGENTS.md default geometry tolerance).
FIT_TOLERANCE = 1e-3
#: Largest number of control points an update may grow the profile to.
MAX_CONTROL_POINTS = 40


class ProfileMatchError(ValueError):
    """The run's arrays do not give a solved tape line (the message says why)."""


@dataclass(frozen=True)
class SolvedMeridian:
    """Tape line of a solved run, in the drawn profile's frame.

    Attributes
    ----------
    station : ndarray
        Normalised material station :math:`\\sigma` (0 at the mouth, 1 at the top), -.
    r, z : ndarray
        Mean solved radius and height of the tapes at each station, m (height shifted so
        the mouth is at the drawn mouth height).
    seams : int
        Number of seams averaged.
    spread : float
        Largest distance between one seam and the mean line, m (0 for an axisymmetric
        result).
    nodes : ndarray, shape (k, 2)
        Solved (r, z) of every seam node, m, in the same height frame: the solved points
        themselves, free of interpolation error.
    """

    station: FloatArray
    r: FloatArray
    z: FloatArray
    seams: int
    spread: float
    nodes: FloatArray

    def at(self, station: FloatArray) -> FloatArray:
        """Solved points ``(k, 2)`` (r, z in m) at stations (dimensionless)."""
        return np.column_stack(
            (np.interp(station, self.station, self.r), np.interp(station, self.station, self.z))
        )


@dataclass(frozen=True)
class ProfileDeviation:
    """How far a solved tape line lies from the drawn profile.

    Attributes
    ----------
    max_distance, rms_distance : float
        Largest and root-mean-square distance from the solved seam nodes to the drawn
        curve (closest point, meridian plane), m.
    max_station_offset : float
        Largest distance between solved and drawn points of the same station, m (what
        the compensation corrects).
    height_change, max_diameter_change : float
        Solved minus drawn height and maximum diameter, m.
    """

    max_distance: float
    rms_distance: float
    max_station_offset: float
    height_change: float
    max_diameter_change: float


@dataclass(frozen=True)
class ProfileUpdate:
    """New control points from a solved line.

    Attributes
    ----------
    points : list of (float, float)
        Control points (radius, height), m, mouth first.
    fit_error : float
        Largest distance from the new profile's sampled curve to its target line
        (drawn line minus the offset for a compensation, the solved line for an
        adoption), m: what the control-point count cannot follow.
    """

    points: list[tuple[float, float]]
    fit_error: float
    #: Relative stretch of the solved tape line taken out (:func:`flight_shape_points`),
    #: dimensionless; 0 for the other updates.
    stretch: float = 0.0


def _seam_paths(initial: FloatArray, triangles: np.ndarray, gore_count: int) -> list[np.ndarray]:
    """Node paths of the vertical seams, mouth first (module docstring)."""
    radius = np.hypot(initial[:, 0], initial[:, 1])
    angle = np.arctan2(initial[:, 1], initial[:, 0]) % (2.0 * math.pi)
    gore = angle * gore_count / (2.0 * math.pi)
    nearest = np.rint(gore)
    on_seam = (np.abs(gore - nearest) < SEAM_AZIMUTH_TOLERANCE * gore_count) & (radius > 1e-9)
    seam_of = np.where(on_seam, nearest.astype(np.int64) % gore_count, -1)
    tri = np.asarray(triangles, dtype=np.int64)
    edges = np.concatenate((tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]))
    edges = np.unique(np.sort(edges, axis=1), axis=0)
    same = (seam_of[edges[:, 0]] >= 0) & (seam_of[edges[:, 0]] == seam_of[edges[:, 1]])
    edges = edges[same]
    paths: list[np.ndarray] = []
    for g in range(gore_count):
        nodes = np.flatnonzero(seam_of == g)
        if nodes.size < 2:
            continue
        mine = edges[seam_of[edges[:, 0]] == g]
        neighbours: dict[int, list[int]] = {int(n): [] for n in nodes}
        for a, b in mine:
            neighbours[int(a)].append(int(b))
            neighbours[int(b)].append(int(a))
        degrees = [len(v) for v in neighbours.values()]
        if max(degrees) > 2 or degrees.count(1) != 2 or len(mine) != nodes.size - 1:
            continue  # not one simple path (an open vent, or a broken seam)
        ends = [n for n, v in neighbours.items() if len(v) == 1]
        current = min(ends, key=lambda n: (initial[n, 2], -radius[n]))
        path, previous = [current], -1
        while len(path) < nodes.size:
            following = next(n for n in neighbours[current] if n != previous)
            previous, current = current, following
            path.append(current)
        paths.append(np.asarray(path, dtype=np.int64))
    return paths


def solved_meridian(
    arrays: Mapping[str, np.ndarray], gore_count: int, mouth_height: float = 0.0
) -> SolvedMeridian:
    """Tape line of a solved standard-gore run (module docstring).

    Parameters
    ----------
    arrays : mapping of str to ndarray
        Run result arrays: ``positions`` and ``initial_positions`` ``(n, 3)`` in m and
        ``triangles`` ``(m, 3)``; ``gore_count`` (stored with newer runs) overrides the
        argument.
    gore_count : int
        Gores of the solved design (used when the arrays do not carry it).
    mouth_height : float
        Height of the drawn profile's mouth, m; the solved line is shifted to it.

    Returns
    -------
    SolvedMeridian
        Mean solved tape line at :data:`STATION_SAMPLES` stations, m.

    Raises
    ------
    ProfileMatchError
        When the arrays are missing or fewer than half the seams form a simple
        mouth-to-top path (for example a special shape, or a gore count that differs from
        the solved one).
    """
    try:
        x = np.asarray(arrays["positions"], dtype=np.float64)
        x0 = np.asarray(arrays["initial_positions"], dtype=np.float64)
        tri = np.asarray(arrays["triangles"], dtype=np.int64)
    except KeyError as exc:
        raise ProfileMatchError(f"run has no {exc.args[0]} array") from exc
    if "gore_count" in arrays:
        gore_count = int(np.asarray(arrays["gore_count"]).reshape(-1)[0])
    if x.shape != x0.shape or x.ndim != 2 or x.shape[1] != 3:
        raise ProfileMatchError("positions and initial positions must both be (n, 3)")
    if gore_count < 3:
        raise ProfileMatchError("a standard-gore run has at least 3 gores")
    paths = _seam_paths(x0, tri, gore_count)
    if 2 * len(paths) < gore_count:
        # Open vents unsew a few seams; most missing means the gore count is wrong.
        raise ProfileMatchError(
            f"only {len(paths)} of {gore_count} load-tape seams found in the run (not a "
            "standard-gore run of this gore count)"
        )
    station = np.linspace(0.0, 1.0, STATION_SAMPLES)
    lines: list[FloatArray] = []
    nodes: list[FloatArray] = []
    z_mouth: list[float] = []
    for path in paths:
        p0 = x0[path]
        rest = np.concatenate(([0.0], np.cumsum(np.linalg.norm(np.diff(p0, axis=0), axis=1))))
        if rest[-1] <= 0.0:
            continue
        sigma = rest / rest[-1]
        r = np.hypot(x[path, 0], x[path, 1])
        # A cubic through the seam nodes: straight chords between nodes one mesh edge
        # apart would sag by L^2/(8R) (27 mm for 0.8 m edges on a 3 m radius).
        if path.size >= 4:
            line = np.column_stack(
                (CubicSpline(sigma, r)(station), CubicSpline(sigma, x[path, 2])(station))
            )
        else:
            line = np.column_stack(
                (np.interp(station, sigma, r), np.interp(station, sigma, x[path, 2]))
            )
        lines.append(line)
        nodes.append(np.column_stack((r, x[path, 2])))
        z_mouth.append(float(p0[0, 2]))
    if not lines:
        raise ProfileMatchError("the load-tape seams of the run have zero length")
    stack = np.stack(lines)
    mean = stack.mean(axis=0)
    spread = float(np.max(np.linalg.norm(stack - mean[None], axis=2)))
    shift = mouth_height - float(np.mean(z_mouth))
    seam_nodes = np.concatenate(nodes) + np.array([0.0, shift])
    return SolvedMeridian(station, mean[:, 0], mean[:, 1] + shift, len(lines), spread, seam_nodes)


#: Nearest curve vertices whose two segments are checked for each point.
NEAREST_VERTICES = 8
#: Curves with at most this many vertices are measured against every segment.
BRUTE_FORCE_VERTICES = 64


def _segment_distance(points: FloatArray, a: FloatArray, b: FloatArray) -> FloatArray:
    """Distance of points ``(..., 2)`` to segments ``a``-``b`` of the same shape, m."""
    ab = b - a
    length2 = np.maximum(np.sum(ab * ab, axis=-1), 1e-300)
    t = np.clip(np.sum((points - a) * ab, axis=-1) / length2, 0.0, 1.0)
    out: FloatArray = np.linalg.norm(points - (a + t[..., None] * ab), axis=-1)
    return out


def _distance_to_polyline(points: FloatArray, curve: FloatArray) -> FloatArray:
    """Distance of each point ``(k, 2)`` to the polyline ``(n, 2)``, m.

    Only the segments at a point's :data:`NEAREST_VERTICES` nearest curve vertices are
    measured (a k-d tree finds them). The nearest segment of a densely sampled curve ends
    at one of them, so the distance is the one over all segments; against every segment
    it would cost k n operations (17 million for a full-size run on a 4001-point profile).
    """
    from scipy.spatial import cKDTree

    n = len(curve)
    if n < 2:
        out: FloatArray = np.linalg.norm(points - curve[:1], axis=1)
        return out
    if n <= BRUTE_FORCE_VERTICES:
        every = _segment_distance(points[:, None, :], curve[None, :-1], curve[None, 1:])
        result_all: FloatArray = np.min(every, axis=1)
        return result_all
    k = min(NEAREST_VERTICES, n)
    _, near = cKDTree(curve).query(points, k=k)
    near = np.asarray(near).reshape(len(points), k)
    seg = np.concatenate((np.maximum(near - 1, 0), np.minimum(near, n - 2)), axis=1)
    distance = _segment_distance(points[:, None, :], curve[seg], curve[seg + 1])
    result: FloatArray = np.min(distance, axis=1)
    return result


def station_points(profile: MeridianProfile, station: FloatArray) -> FloatArray:
    """Points ``(k, 2)`` (r, z in m) of a profile at normalised stations (0 to 1)."""
    s = np.asarray(station) * profile.meridian_length
    return np.column_stack((np.interp(s, profile.s, profile.r), np.interp(s, profile.s, profile.z)))


def solved_deviation(profile: MeridianProfile, solved: SolvedMeridian) -> ProfileDeviation:
    """Deviation of a solved tape line from a profile (the drawn one, or the compensation
    target), m (see the class)."""
    curve = np.column_stack((profile.r, profile.z))
    points = np.column_stack((solved.r, solved.z))
    distance = _distance_to_polyline(solved.nodes, curve)
    offset = np.linalg.norm(points - station_points(profile, solved.station), axis=1)
    return ProfileDeviation(
        max_distance=float(distance.max()),
        rms_distance=float(np.sqrt(np.mean(distance**2))),
        max_station_offset=float(offset.max()),
        height_change=float(np.ptp(solved.z)) - profile.height,
        max_diameter_change=2.0 * float(solved.r.max()) - profile.max_width,
    )


def target_profile(target: ProfileTarget) -> MeridianProfile:
    """Meridian profile of a stored compensation target, m."""
    r = np.array([p[0] for p in target.control_points], dtype=np.float64)
    z = np.array([p[1] for p in target.control_points], dtype=np.float64)
    return profile_from_arrays(r, z, target.interpolation)


def control_point_stations(design: DesignDocument) -> FloatArray:
    """Station :math:`\\sigma_i` of each control point on the drawn profile (0 to 1)."""
    profile = design_profile(design)
    r, z = control_arrays(design)
    curve = np.column_stack((profile.r, profile.z))
    stations = np.empty(r.size)
    for i, point in enumerate(np.column_stack((r, z))):
        stations[i] = profile.s[int(np.argmin(np.linalg.norm(curve - point, axis=1)))]
    stations /= profile.meridian_length
    stations[0], stations[-1] = 0.0, 1.0
    return stations


SEGMENTS_REFUSAL = (
    "a segment profile (lines, arcs and curves) cannot follow a solved line: set "
    "'Profile between points' to Spline or Straight segments first"
)


def updatable_interpolation(design: DesignDocument) -> Literal["spline", "linear"]:
    """The design's interpolation when a solved line can update its profile.

    Raises
    ------
    ValueError
        For a segment profile (:data:`SEGMENTS_REFUSAL`) or a special-shape design.
    """
    if design.gores is None:
        raise ValueError("not a standard-gore design")
    interpolation = design.gores.profile_interpolation
    if interpolation not in ("spline", "linear"):
        raise ValueError(SEGMENTS_REFUSAL)
    return "linear" if interpolation == "linear" else "spline"


def adopted_interpolation(design: DesignDocument) -> Literal["spline", "linear"]:
    """How an adopted solved line runs between its control points: the design's own
    interpolation, or a spline for a segment profile (whose lines, arcs and curves cannot
    follow a solved line).

    Raises
    ------
    ValueError
        For a special-shape design.
    """
    if design.gores is None:
        raise ValueError("not a standard-gore design")
    return "linear" if design.gores.profile_interpolation == "linear" else "spline"


def _fit(
    design: DesignDocument,
    stations: FloatArray,
    target: FloatArray,
    tolerance: float,
    max_points: int,
    interpolation: Literal["spline", "linear"] | None = None,
) -> ProfileUpdate:
    """Control points on ``target`` (points at :attr:`SolvedMeridian.station`), adding
    points at the station of largest error until the profile follows it within
    ``tolerance`` (m) or there are ``max_points``. The interpolation defaults to
    :func:`updatable_interpolation`."""
    if interpolation is None:
        interpolation = updatable_interpolation(design)
    dense = np.linspace(0.0, 1.0, target.shape[0])
    chosen = sorted({float(v) for v in stations})

    def points_at(sigma: list[float]) -> FloatArray:
        pts = np.column_stack(
            (np.interp(sigma, dense, target[:, 0]), np.interp(sigma, dense, target[:, 1]))
        )
        pts[:, 0] = np.maximum(pts[:, 0], 0.0)
        return pts

    while True:
        pts = points_at(chosen)
        new = profile_from_arrays(pts[:, 0], pts[:, 1], interpolation)
        error = _distance_to_polyline(target, np.column_stack((new.r, new.z)))
        worst = int(np.argmax(error))
        if error[worst] <= tolerance or len(chosen) >= max_points:
            break
        candidate = float(dense[worst])
        if any(abs(candidate - c) < 0.5 / target.shape[0] for c in chosen):
            break  # the worst point already is a control point: no insertion helps
        chosen = sorted([*chosen, candidate])
    return ProfileUpdate([(float(a), float(b)) for a, b in pts], float(error.max()))


def compensated_control_points(
    design: DesignDocument,
    solved: SolvedMeridian,
    relaxation: float = 1.0,
    tolerance: float = FIT_TOLERANCE,
    max_points: int = MAX_CONTROL_POINTS,
    target: MeridianProfile | None = None,
) -> ProfileUpdate:
    """Control points corrected so the inflated tapes land on the target profile.

    One fixed-point step :math:`\\mathbf{c}_i \\leftarrow \\mathbf{c}_i - \\alpha
    (\\mathbf{Q}(\\sigma_i) - \\mathbf{T}(\\sigma_i))` (module docstring), with the
    target :math:`\\mathbf{T}` the drawn profile on the first step.

    Parameters
    ----------
    design : DesignDocument
        Gore design that was solved (its drawn profile is the cut, m).
    solved : SolvedMeridian
        Solved tape line of that design, m.
    relaxation : float
        Step factor :math:`\\alpha` in (0, 1] (module docstring), dimensionless.
    tolerance : float
        Fit tolerance of the new profile, m.
    max_points : int
        Largest number of control points.
    target : MeridianProfile, optional
        Intended inflated tape line, m (default: the drawn profile).

    Returns
    -------
    ProfileUpdate
        New control points, m, and the fit error against the corrected line, m.
    """
    if not 0.0 < relaxation <= 1.0:
        raise ValueError("relaxation must be in (0, 1]")
    drawn = design_profile(design)
    dense = solved.station
    goal = station_points(target if target is not None else drawn, dense)
    line = station_points(drawn, dense) - relaxation * (solved.at(dense) - goal)
    return _fit(design, control_point_stations(design), line, tolerance, max_points)


def adopted_control_points(
    design: DesignDocument,
    solved: SolvedMeridian,
    tolerance: float = FIT_TOLERANCE,
    max_points: int = MAX_CONTROL_POINTS,
) -> ProfileUpdate:
    """Control points moved onto the solved tape line at their own stations, for the
    interpolation of :func:`adopted_interpolation` (a spline for a segment profile).

    Parameters
    ----------
    design : DesignDocument
        Gore design (m).
    solved : SolvedMeridian
        Solved tape line of that design, m.
    tolerance : float
        Fit tolerance of the new profile, m.
    max_points : int
        Largest number of control points.

    Returns
    -------
    ProfileUpdate
        New control points, m, and the fit error against the solved line, m.
    """
    target = np.column_stack((solved.r, solved.z))
    return _fit(
        design,
        control_point_stations(design),
        target,
        tolerance,
        max_points,
        adopted_interpolation(design),
    )


#: Passes of the flight-shape scale (each corrects the length the top-radius blend adds;
#: the change falls by about 1000x per pass).
FLIGHT_PASSES = 4


def flight_shape_points(
    design: DesignDocument,
    solved: SolvedMeridian,
    tolerance: float = FIT_TOLERANCE,
    max_points: int = MAX_CONTROL_POINTS,
) -> ProfileUpdate:
    r"""Control points of the solved shape with its stretch taken out (the flight shape).

    The solved tape line :math:`\mathbf{Q}(\sigma)` is the cut stretched by its load. The
    flight shape keeps the solved shape and the mouth (held by the rigging) and scales it
    about the mouth point so that its length is the design's tape length :math:`L_d`:

    .. math::
        \mathbf{C}(\sigma) = \mathbf{M} + c\,\bigl(\mathbf{Q}(\sigma) - \mathbf{Q}(0)\bigr),

    with :math:`\mathbf{M}` the drawn mouth point and :math:`c` close to
    :math:`L_d / L_s`, :math:`L_s` the length of the solved line. The top opening keeps its
    design radius :math:`r_t`: its ring stretches more than the tapes, so the radial
    difference :math:`r_t - C_r(1)` is added as :math:`\sigma^2 (r_t - C_r(1))`, leaving the
    mouth exact, and :math:`c` is corrected until the curve's length is :math:`L_d`.
    Repeating the update keeps the tape length, where :func:`adopted_control_points`
    lengthens it by the stretch every time. The shape itself can still move from one cycle
    to the next when the re-cut patterns change the equilibrium
    (``docs/theory/profile-matching.md``). The stretch removed is :math:`L_s / L_d - 1`.

    Parameters
    ----------
    design : DesignDocument
        Gore design that was solved, m.
    solved : SolvedMeridian
        Solved tape line of that design, m.
    tolerance : float
        Fit tolerance of the new profile, m.
    max_points : int
        Largest number of control points.

    Returns
    -------
    ProfileUpdate
        New control points (m), their fit error against the flight shape (m) and the
        stretch taken out (dimensionless).

    Notes
    -----
    Assumes the stretch is about the same along and across the tapes, so that one factor
    takes it out (on the full-size fixture the tapes stretch 0.14-0.35 %). A segment
    profile becomes a spline (:func:`adopted_interpolation`).
    """
    line = np.column_stack((solved.r, solved.z))
    solved_length = float(np.sum(np.linalg.norm(np.diff(line, axis=0), axis=1)))
    if not solved_length > 0.0:
        raise ProfileMatchError("the solved tape line has no length")
    drawn = design_profile(design)
    mouth = np.array([float(drawn.r[0]), float(drawn.z[0])])
    sigma = np.asarray(solved.station, dtype=np.float64)
    scale = drawn.meridian_length / solved_length
    for _ in range(FLIGHT_PASSES):
        target = mouth + scale * (line - line[0])
        # The top opening keeps its design radius: its ring stretches more than the tapes
        # (1.2 % against 0.38 % on the full-size fixture), so one scale factor would cut it
        # wider every time. The radial difference is blended in as sigma^2 (the mouth stays
        # exact), and the scale is corrected for the length that adds.
        target[:, 0] += (float(drawn.r[-1]) - float(target[-1, 0])) * sigma**2
        length = float(np.sum(np.linalg.norm(np.diff(target, axis=0), axis=1)))
        scale *= drawn.meridian_length / length
    update = _fit(
        design,
        control_point_stations(design),
        target,
        tolerance,
        max_points,
        adopted_interpolation(design),
    )
    return ProfileUpdate(update.points, update.fit_error, solved_length / drawn.meridian_length - 1)


@dataclass(frozen=True)
class RunShape:
    """The latest run of one solver, read as a tape line for the profile editor.

    Attributes
    ----------
    record : RunRecord
        The run.
    current : bool
        The run solved the current design state.
    solved : SolvedMeridian or None
        Its tape line (None when it could not be read; see ``message``).
    deviation : ProfileDeviation or None
        Deviation from the compensation target when the project has one, else from the
        drawn profile, m.
    message : str
        Why ``solved`` is missing, else empty.
    """

    record: RunRecord
    current: bool
    solved: SolvedMeridian | None
    deviation: ProfileDeviation | None
    message: str = ""

    @property
    def usable(self) -> bool:
        """The run may drive a profile update: current, converged and read."""
        return self.current and self.record.converged and self.solved is not None

    @property
    def refusal(self) -> str:
        """Why the run may not drive a profile update (empty when it may)."""
        if self.solved is None:
            return self.message
        if not self.record.converged:
            return f"the latest run is not converged ({self.record.status})"
        if not self.current:
            return "the latest run is stale: the design changed since; run it again"
        return ""


def latest_run_shape(session: ProjectSession, solver: str) -> RunShape | None:
    """Tape line of the latest run of ``solver`` in a gore project (None without one).

    Parameters
    ----------
    session : ProjectSession
        Open project with a standard-gore design.
    solver : str
        ``envelopelab-preview`` or ``calculix``.

    Returns
    -------
    RunShape or None
        The run, whether it is current, and its tape line and deviation (m).
    """
    design = session.design
    if design.gores is None:
        return None
    record = next((r for r in reversed(session.project.runs) if r.solver == solver), None)
    if record is None:
        return None
    current = session.run_status(record) == "current"
    arrays = session.run_arrays(record.run_id)
    if arrays is None:
        return RunShape(record, current, None, None, "the run's result arrays are not available")
    _, z = control_arrays(design)
    target = session.project.profile_target
    try:
        solved = solved_meridian(arrays, design.gores.count, float(z[0]))
        reference = design_profile(design) if target is None else target_profile(target)
        deviation = solved_deviation(reference, solved)
    except (ProfileMatchError, ValueError) as exc:
        return RunShape(record, current, None, None, str(exc))
    return RunShape(record, current, solved, deviation)


def usable_run_shape(session: ProjectSession, preferred: str) -> RunShape | None:
    """The latest run that may drive a profile update: of ``preferred`` when its latest
    run is usable (:attr:`RunShape.usable`), else of the other solver, else None.

    Parameters
    ----------
    session : ProjectSession
        Open project with a standard-gore design.
    preferred : str
        ``envelopelab-preview`` or ``calculix``.
    """
    others = [s for s in ("calculix", "envelopelab-preview") if s != preferred]
    for solver in (preferred, *others):
        shape = latest_run_shape(session, solver)
        if shape is not None and shape.usable:
            return shape
    return None
