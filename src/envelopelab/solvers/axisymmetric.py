r"""Axisymmetric membrane statics of a gore envelope: stress check and natural shape.

A fast check (milliseconds) that runs while a profile is edited, before any mesh exists.

Geometry and loads
------------------
The meridian runs from the mouth (arc length :math:`s = 0`) to the top opening
(:math:`s = L`) with tangent angle :math:`\theta` from the horizontal,
:math:`r' = \cos\theta`, :math:`z' = \sin\theta`, outward normal
:math:`n = (\sin\theta, -\cos\theta)` and meridional curvature :math:`\kappa_m = \theta'`
(positive where the envelope is convex). The loads per unit area are

* the differential pressure :math:`p(z) = p_0 + \gamma (z - z_0)`, with
  :math:`\gamma = (\rho_{amb} - \rho_{int}) g` for hot air and :math:`p_0 = 0` at the open
  mouth, acting along :math:`n`;
* the weight :math:`w` of fabric and tapes (N/m², downward), whose normal component is
  :math:`w\cos\theta`;

and the top opening is closed by a parachute that hands the pressure on its disk,
:math:`P_{top} = \pi r_L^2\, p(z_L)`, to the rim as a vertical load.

Stress check (membrane theory of shells of revolution [Timoshenko]_)
--------------------------------------------------------------------
Vertical equilibrium of everything above the parallel at :math:`s` gives the meridional
resultant, and normal equilibrium the hoop resultant:

.. math::
    N_m = \frac{V(s)}{2\pi r \sin\theta}, \qquad
    V(s) = P_{top} + \int_s^L \bigl(-p\cos\theta - w\bigr)\, 2\pi r\, ds',
    \qquad
    N_h = \frac{r\,(p_n - N_m \kappa_m)}{\sin\theta}, \quad p_n = p + w\cos\theta.

Membrane theory holds where :math:`\sin\theta` is not small (no horizontal tangent);
elsewhere the values are not evaluated. A straight-segment profile has its curvature
concentrated at the kinks: a kink turning by :math:`\Delta\theta` puts a hoop force
:math:`F = N_m r \Delta\theta` (N) into the horizontal tape there, tension for a convex
kink.

A gore envelope carries meridional load in its tapes and fabric and hoop load only in the
fabric between tapes. Hoop **compression** (:math:`N_h < 0`) or meridional compression
cannot be carried: the fabric wrinkles and that part of the envelope does not keep the
drawn shape.

Natural shape (zero hoop stress [Taylor]_ [Smalley]_)
----------------------------------------------------
With :math:`N_h = 0` the whole load is carried meridionally. With the total meridional
tension :math:`T = 2\pi r N_m`, equilibrium of a meridian element gives

.. math::
    \theta' = \frac{2\pi r\,(p + w\cos\theta)}{T}, \qquad
    T' = 2\pi r\, w \sin\theta, \qquad r' = \cos\theta, \qquad z' = \sin\theta,

integrated from the mouth :math:`(r_0, z_0)` with RK4. The mouth angle :math:`\theta_0`
and tension :math:`T_0` are shot (Newton on a finite-difference Jacobian) so that at the
end the radius is the top-opening radius :math:`r_L` and the rim balances the parachute,
:math:`T_L \sin\theta_L = P_{top}`. The end is at the given tape length :math:`L`, or at
the given height.

Assumptions and valid range
---------------------------
Axisymmetric, quasi-static, membrane (no bending); weight uniform per area; inextensible
meridian: the natural shape is the loaded shape. Tape stretch of order :math:`T/(N\,EA)`
(about 1 % on the generic fixture) is left to the solved-shape compensation
(:mod:`envelopelab.project.profile_match`). Lobing between tapes is not resolved: the
check is the global (tape-line) membrane state. Valid for envelopes from scale models to
crewed sizes, while the shape stays between the axis and its mouth and top radii.

References
----------
.. [Timoshenko] S. Timoshenko and S. Woinowsky-Krieger, *Theory of Plates and Shells*,
   2nd ed., McGraw-Hill (1959), ch. 16: membrane theory of shells of revolution.
.. [Taylor] G. I. Taylor, "On the shapes of parachutes" (1919), in *Scientific Papers*,
   vol. III, Cambridge (1963): zero-hoop-stress (natural) shapes of loaded membranes.
.. [Smalley] J. H. Smalley, "Determination of the shape of a free balloon", AFCRL-64-734
   (1964): the natural-shape equations solved by shooting.
.. [Paulsen] W. H. Paulsen, "What is the shape of a mylar balloon?", *American
   Mathematical Monthly* 101 (1994) 953-958: thickness/diameter = 0.59907 under uniform
   pressure, the closed-form check of the natural-shape integration.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from envelopelab.geometry.gore import MeridianProfile
from envelopelab.geometry.polygon import FloatArray

#: |sin(theta)| below which membrane theory is not evaluated (near-horizontal tangent).
MIN_SIN = 0.05
#: Turn between two samples that marks a kink of a straight-segment profile, rad.
KINK_ANGLE = math.radians(2.0)
#: Hoop compression below this fraction of the largest meridional resultant is flagged.
COMPRESSION_FRACTION = 0.02


@dataclass(frozen=True)
class AxisymmetricLoad:
    """Loads of an axisymmetric envelope (SI).

    Attributes
    ----------
    pressure_gradient : float
        :math:`\\gamma`, N/m^3 (positive: the pressure grows with height).
    mouth_height : float
        :math:`z_0`, m, where the pressure is ``base_pressure``.
    base_pressure : float
        :math:`p_0`, Pa (0 at an open mouth).
    areal_weight : float
        :math:`w`, fabric and tape weight per envelope area, N/m^2.
    top_closed : bool
        The top opening is closed (by a parachute) and its pressure load acts on the rim.
    """

    pressure_gradient: float
    mouth_height: float = 0.0
    base_pressure: float = 0.0
    areal_weight: float = 0.0
    top_closed: bool = True

    def pressure(self, z: FloatArray | float) -> FloatArray:
        """Differential pressure at height ``z`` (m), Pa."""
        return np.asarray(
            self.base_pressure + self.pressure_gradient * (np.asarray(z) - self.mouth_height)
        )

    def top_load(self, r_top: float, z_top: float) -> float:
        """Vertical load of the closed top opening on its rim, N."""
        if not self.top_closed:
            return 0.0
        return math.pi * r_top**2 * float(self.pressure(z_top))


@dataclass(frozen=True)
class Kink:
    """A kink of a straight-segment profile and the hoop force it needs.

    Attributes
    ----------
    s : float
        Arc length from the mouth, m.
    turn : float
        Turn of the tangent, rad (positive: convex).
    ring_force : float
        Hoop force in the horizontal tape at the kink, N (negative: compression, which a
        tape cannot carry).
    """

    s: float
    turn: float
    ring_force: float


@dataclass(frozen=True)
class MembraneCheck:
    """Membrane resultants of a profile under its load (module docstring).

    Attributes
    ----------
    s, r, z : ndarray
        Arc length, radius and height of the samples, m.
    meridional, hoop : ndarray
        :math:`N_m` and :math:`N_h`, N/m (NaN where not evaluated).
    evaluated : ndarray of bool
        Samples where membrane theory holds (:data:`MIN_SIN`).
    kinks : list of Kink
        Concentrated turns (straight-segment profiles).
    """

    s: FloatArray
    r: FloatArray
    z: FloatArray
    meridional: FloatArray
    hoop: FloatArray
    evaluated: np.ndarray
    kinks: list[Kink] = field(default_factory=list)

    @property
    def scale(self) -> float:
        """Largest meridional resultant, N/m (the reference for the flags)."""
        values = self.meridional[self.evaluated]
        return float(np.max(np.abs(values))) if values.size else 0.0

    @property
    def hoop_compression(self) -> np.ndarray:
        """Samples whose hoop resultant is compressive beyond
        :data:`COMPRESSION_FRACTION` of :attr:`scale`."""
        limit = -COMPRESSION_FRACTION * self.scale
        return self.evaluated & (np.nan_to_num(self.hoop, nan=0.0) < limit)

    @property
    def meridional_compression(self) -> np.ndarray:
        """Samples whose meridional resultant is compressive (tapes slack)."""
        return self.evaluated & (np.nan_to_num(self.meridional, nan=0.0) < 0.0)

    @property
    def holds(self) -> np.ndarray:
        """Samples where the drawn shape can be held (no compression)."""
        bad: np.ndarray = self.hoop_compression | self.meridional_compression
        return ~bad

    @property
    def compressed_fraction(self) -> float:
        """Fraction of the tape length that cannot hold its shape, dimensionless."""
        bad = ~self.holds
        ds = np.diff(self.s)
        mid = bad[:-1] | bad[1:]
        return float(np.sum(ds[mid]) / self.s[-1]) if self.s[-1] > 0 else 0.0

    @property
    def compressed_kinks(self) -> list[Kink]:
        """Kinks whose ring force is compressive."""
        return [k for k in self.kinks if k.ring_force < 0.0]


def _angles(r: FloatArray, z: FloatArray) -> tuple[FloatArray, FloatArray]:
    """Tangent angle of every segment, unwrapped, and at every sample (mean of its two
    segments), rad."""
    seg = np.unwrap(np.arctan2(np.diff(z), np.diff(r)))
    node = np.empty(r.size)
    node[0], node[-1] = seg[0], seg[-1]
    node[1:-1] = 0.5 * (seg[:-1] + seg[1:])
    return seg, node


def membrane_check(profile: MeridianProfile, load: AxisymmetricLoad) -> MembraneCheck:
    """Meridional and hoop resultants of a profile under its load (module docstring).

    Parameters
    ----------
    profile : MeridianProfile
        Drawn profile, m, mouth first (densely sampled).
    load : AxisymmetricLoad
        Pressure (Pa, N/m^3), weight (N/m^2) and top closure.

    Returns
    -------
    MembraneCheck
        :math:`N_m`, :math:`N_h` (N/m) at the samples, and the kinks' ring forces (N).
    """
    s, r, z = profile.s, profile.r, profile.z
    seg, theta = _angles(r, z)
    turn = np.diff(seg)  # at interior samples
    kink = np.zeros(r.size, dtype=bool)
    kink[1:-1] = np.abs(turn) > KINK_ANGLE
    ds_seg = np.diff(s)
    curvature = np.zeros(r.size)
    smooth_turn = np.where(kink[1:-1], 0.0, turn)
    curvature[1:-1] = smooth_turn / (0.5 * (ds_seg[:-1] + ds_seg[1:]))
    curvature[0], curvature[-1] = curvature[1], curvature[-2]
    p = load.pressure(z)
    w = load.areal_weight
    # V(s) by the trapezoidal rule from the top down.
    integrand = (-p * np.cos(theta) - w) * 2.0 * math.pi * r
    pieces = 0.5 * (integrand[:-1] + integrand[1:]) * ds_seg
    above = np.concatenate((np.cumsum(pieces[::-1])[::-1], [0.0]))
    vertical = load.top_load(float(r[-1]), float(z[-1])) + above
    sin_t = np.sin(theta)
    evaluated = (np.abs(sin_t) >= MIN_SIN) & (r > 1e-9)
    safe = np.where(evaluated, sin_t, 1.0)
    ring = 2.0 * math.pi * np.maximum(r, 1e-9) * safe
    meridional = np.where(evaluated, vertical / ring, np.nan)
    p_n = p + w * np.cos(theta)
    hoop = np.where(evaluated, r * (p_n - meridional * curvature) / safe, np.nan)
    kinks = [
        Kink(float(s[i]), float(turn[i - 1]), float(meridional[i] * r[i] * turn[i - 1]))
        for i in np.flatnonzero(kink)
        if evaluated[i]
    ]
    return MembraneCheck(s, r, z, meridional, hoop, evaluated, kinks)


@dataclass(frozen=True)
class NaturalShape:
    """A zero-hoop-stress meridian (module docstring).

    Attributes
    ----------
    profile : MeridianProfile
        The shape, m, mouth first.
    tension : ndarray
        Total meridional tension :math:`T` at the profile samples, N.
    mouth_angle : float
        :math:`\\theta_0`, rad from the horizontal.
    residual : float
        Remaining end-condition error: radius (m) and rim balance relative to the top
        load, combined (dimensionless with the radius scaled by the mouth radius).
    converged : bool
        The shooting met its tolerance.
    """

    profile: MeridianProfile
    tension: FloatArray
    mouth_angle: float
    residual: float
    converged: bool


def _integrate(
    load: AxisymmetricLoad,
    r0: float,
    z0: float,
    theta0: float,
    t0: float,
    length: float | None,
    height: float | None,
    steps: int,
) -> FloatArray:
    """RK4 integration of (r, z, theta, T); rows are the samples. Stops at ``length`` of
    tape, or when ``z - z0`` reaches ``height`` (then the last step is cut to land on it),
    or when the meridian reaches the axis."""
    w = load.areal_weight

    def rhs(y: FloatArray) -> FloatArray:
        r, z, th, t = y
        p = float(load.pressure(z))
        tension = t if abs(t) > 1e-12 else 1e-12
        return np.array(
            [
                math.cos(th),
                math.sin(th),
                2.0 * math.pi * r * (p + w * math.cos(th)) / tension,
                2.0 * math.pi * r * w * math.sin(th),
            ]
        )

    total = length if length is not None else 4.0 * (height or 1.0) + 4.0 * r0
    h = total / steps
    y = np.array([r0, z0, theta0, t0], dtype=np.float64)
    rows = [y.copy()]
    for _ in range(steps if length is not None else 4 * steps):
        k1 = rhs(y)
        k2 = rhs(y + 0.5 * h * k1)
        k3 = rhs(y + 0.5 * h * k2)
        k4 = rhs(y + h * k3)
        y_new = y + h / 6.0 * (k1 + 2.0 * k2 + 2.0 * k3 + k4)
        if height is not None and y_new[1] - z0 >= height:
            frac = (z0 + height - y[1]) / (y_new[1] - y[1])
            rows.append(y + frac * (y_new - y))
            break
        if y_new[0] <= 0.0:
            frac = y[0] / (y[0] - y_new[0])
            rows.append(y + frac * (y_new - y))
            break
        y = y_new
        rows.append(y.copy())
    return np.asarray(rows)


def natural_shape(
    load: AxisymmetricLoad,
    mouth: tuple[float, float],
    top_radius: float,
    length: float | None = None,
    height: float | None = None,
    guess: tuple[float, float] | None = None,
    steps: int = 400,
    tolerance: float = 1e-9,
    max_iterations: int = 40,
) -> NaturalShape:
    """Zero-hoop-stress meridian between a mouth and a top opening (module docstring).

    Parameters
    ----------
    load : AxisymmetricLoad
        Pressure and weight (Pa, N/m^3, N/m^2).
    mouth : (float, float)
        Mouth radius and height, m.
    top_radius : float
        Radius of the top opening, m (> 0).
    length, height : float, optional
        Tape length or height above the mouth of the shape, m (exactly one).
    guess : (float, float), optional
        Starting mouth angle (rad) and mouth tension (N), e.g. from the drawn profile.
    steps : int
        RK4 steps along the tape.
    tolerance : float
        Convergence limit of the end-condition residual (radius relative to the mouth
        radius, rim balance relative to the top load).
    max_iterations : int
        Newton iterations.

    Returns
    -------
    NaturalShape
        The shape (m), its tension (N) and whether the shooting converged.

    Raises
    ------
    ValueError
        For inconsistent arguments (both or neither of ``length`` and ``height``, a
        non-positive radius or length).
    """
    if (length is None) == (height is None):
        raise ValueError("give exactly one of the tape length and the height")
    r0, z0 = mouth
    if r0 <= 0.0 or top_radius <= 0.0:
        raise ValueError("the mouth and top radii must be positive")
    if (length is not None and length <= 0.0) or (height is not None and height <= 0.0):
        raise ValueError("the tape length and height must be positive")
    given = length if length is not None else height
    assert given is not None
    span = float(given)
    if guess is None:
        # A sphere-like guess: the mouth leaves at 60 degrees, the tension carries the
        # pressure on a disk of the equator radius.
        guess = (
            math.radians(60.0),
            math.pi * (span / math.pi) ** 2 * max(float(load.pressure(z0 + 0.5 * span)), 1e-6),
        )
    x = np.array([guess[0], math.log(max(guess[1], 1e-9))])
    top_scale = max(load.top_load(top_radius, z0 + 0.8 * span), 1e-6)

    def ends(v: FloatArray) -> tuple[FloatArray, FloatArray]:
        rows = _integrate(load, r0, z0, float(v[0]), math.exp(float(v[1])), length, height, steps)
        r_l, z_l, th_l, t_l = rows[-1]
        balance = (t_l * math.sin(th_l) - load.top_load(r_l, z_l)) / top_scale
        radius = (r_l - top_radius) / r0
        # Stopped at the axis before the end: the missing tape length (or height) counts
        # as further radius error, so the residual stays continuous.
        if length is not None and rows.shape[0] < steps + 1:
            done = float(np.sum(np.hypot(np.diff(rows[:, 0]), np.diff(rows[:, 1]))))
            radius -= max(length - done, 0.0) / r0
        elif height is not None and z_l < z0 + span - 1e-9 * span:
            radius -= (z0 + span - z_l) / r0
        return np.array([radius, balance]), rows

    f, rows = ends(x)
    if float(np.max(np.abs(f))) > 1e-2:
        # A coarse grid of mouth angles and tensions around the guess picks the start.
        best = (float(np.max(np.abs(f))), x, f, rows)
        for angle in np.linspace(0.2, 1.4, 7):
            for factor in (0.25, 0.5, 1.0, 2.0, 4.0):
                trial = np.array([angle, x[1] + math.log(factor)])
                f_trial, rows_trial = ends(trial)
                if float(np.max(np.abs(f_trial))) < best[0]:
                    best = (float(np.max(np.abs(f_trial))), trial, f_trial, rows_trial)
        _, x, f, rows = best
    for _ in range(max_iterations):
        if float(np.max(np.abs(f))) <= tolerance:
            break
        jac = np.empty((2, 2))
        for k in range(2):
            dx = np.zeros(2)
            dx[k] = 1e-6 * max(1.0, abs(x[k]))
            jac[:, k] = (ends(x + dx)[0] - f) / dx[k]
        try:
            step = np.linalg.solve(jac, -f)
        except np.linalg.LinAlgError:
            break
        # Damped Newton: halve the step until the residual drops.
        for _ in range(20):
            trial = x + step
            f_trial, rows_trial = ends(trial)
            if float(np.max(np.abs(f_trial))) < float(np.max(np.abs(f))):
                x, f, rows = trial, f_trial, rows_trial
                break
            step = 0.5 * step
        else:
            break
    profile = MeridianProfile.from_points(np.clip(rows[:, 0], 0.0, None), rows[:, 1])
    residual = float(np.max(np.abs(f)))
    return NaturalShape(profile, rows[:, 3], float(x[0]), residual, residual <= tolerance)


@dataclass(frozen=True)
class HeldShape:
    """The nearest shape that holds under its load (:func:`hold_shape`).

    Attributes
    ----------
    profile : MeridianProfile
        The shape, m, mouth first.
    check : MembraneCheck
        Its membrane check.
    changed : float
        Fraction of the tape length whose curvature was limited, dimensionless.
    iterations : int
        Passes used.
    converged : bool
        The shape stopped changing (within ``tolerance``) and holds everywhere.
    """

    profile: MeridianProfile
    check: MembraneCheck
    changed: float
    iterations: int
    converged: bool


def _rebuild(
    s: FloatArray,
    curvature: FloatArray,
    turns: FloatArray,
    r0: float,
    z0: float,
    theta0: float,
) -> tuple[FloatArray, FloatArray]:
    """Curve from the mouth with sample curvatures (1/m) and concentrated turns (rad) at
    the samples, over the arc lengths ``s`` (m); ``theta0`` is the first segment's angle.
    The exact inverse of the curvature and turns :func:`membrane_check` reads."""
    ds = np.diff(s)
    step = curvature[1:-1] * 0.5 * (ds[:-1] + ds[1:]) + turns[1:-1]
    seg = theta0 + np.concatenate(([0.0], np.cumsum(step)))
    r = r0 + np.concatenate(([0.0], np.cumsum(np.cos(seg) * ds)))
    z = z0 + np.concatenate(([0.0], np.cumsum(np.sin(seg) * ds)))
    return r, z


def hold_shape(
    profile: MeridianProfile,
    load: AxisymmetricLoad,
    tolerance: float = 1e-4,
    max_iterations: int = 60,
    hoop_margin: float = 0.0,
) -> HeldShape:
    r"""Nearest shape to ``profile`` that its load can hold: no hoop compression.

    Where the check finds hoop compression (:attr:`MembraneCheck.hoop_compression`) the
    drawn curvature is larger than the fabric can follow; there, and wherever it was
    found in an earlier pass, it is limited to the zero-hoop (natural) curvature
    :math:`\kappa \le p_n / N_m`, and concave kinks (a compressed horizontal tape) are
    straightened. Everywhere else the drawn curvature is kept. The curve is rebuilt from
    the mouth over the same tape length, the mouth angle shot (secant) so that it ends at
    the top-opening radius, and the check repeated until the shape stops changing.

    Parameters
    ----------
    profile : MeridianProfile
        Drawn profile, m.
    load : AxisymmetricLoad
        Load (Pa, N/m^3, N/m^2).
    tolerance : float
        Convergence limit of the largest change of a point between passes, relative to the
        tape length.
    max_iterations : int
        Passes.

    Returns
    -------
    HeldShape
        The shape (m) and its check.
    """
    s = profile.s
    r0, z0, r_top = float(profile.r[0]), float(profile.z[0]), float(profile.r[-1])
    seg, theta = _angles(profile.r, profile.z)
    turns = np.zeros(s.size)
    turns[1:-1] = np.diff(seg)
    kinked = np.abs(turns) > KINK_ANGLE
    drawn_turns = np.where(kinked, turns, 0.0)
    drawn_curv = np.zeros(s.size)
    ds = np.diff(s)
    drawn_curv[1:-1] = np.where(kinked[1:-1], 0.0, turns[1:-1]) / (0.5 * (ds[:-1] + ds[1:]))
    drawn_curv[0], drawn_curv[-1] = drawn_curv[1], drawn_curv[-2]
    theta0 = float(seg[0])
    r, z = profile.r.copy(), profile.z.copy()
    limited = np.zeros(s.size, dtype=bool)
    # Samples once found in compression keep the limited curvature (no oscillation).
    capped = np.zeros(s.size, dtype=bool)
    converged = False
    iterations = 0
    while iterations < max_iterations:
        iterations += 1
        current = MeridianProfile(s=s.copy(), r=np.clip(r, 0.0, None), z=z)
        chk = membrane_check(current, load)
        capped |= chk.hoop_compression
        theta_now = _angles(r, z)[1]
        natural = np.where(
            chk.evaluated & (chk.meridional > 0.0),
            (load.pressure(z) + load.areal_weight * np.cos(theta_now))
            / np.where(chk.meridional > 0.0, chk.meridional, 1.0)
            - hoop_margin * np.sin(theta_now) / np.maximum(r, 1e-9),
            np.inf,
        )
        curvature = np.where(capped, np.minimum(drawn_curv, natural), drawn_curv)
        limited = curvature < drawn_curv
        kink_turns = np.where(drawn_turns < 0.0, 0.0, drawn_turns)

        def end_radius(
            t0: float, curvature: FloatArray = curvature, kink_turns: FloatArray = kink_turns
        ) -> float:
            return float(_rebuild(s, curvature, kink_turns, r0, z0, t0)[0][-1]) - r_top

        # Secant on the mouth angle from the current one.
        a, b = theta0, theta0 + 1e-3
        fa, fb = end_radius(a), end_radius(b)
        for _ in range(50):
            if abs(fb) < 1e-10 * s[-1] or fb == fa:
                break
            a, b, fa = b, b - fb * (b - a) / (fb - fa), fb
            fb = end_radius(b)
        theta0 = b
        r_new, z_new = _rebuild(s, curvature, kink_turns, r0, z0, theta0)
        change = float(np.max(np.hypot(r_new - r, z_new - z))) / float(s[-1])
        r, z = r_new, z_new
        if change <= tolerance:
            converged = True
            break
    shape = MeridianProfile(s=s.copy(), r=np.clip(r, 0.0, None), z=z)
    chk = membrane_check(shape, load)
    holds = not np.any(chk.hoop_compression | chk.meridional_compression)
    ds_mid = np.diff(s)
    changed = float(np.sum(ds_mid[(limited[:-1] | limited[1:])]) / s[-1])
    return HeldShape(shape, chk, changed, iterations, converged and holds)
