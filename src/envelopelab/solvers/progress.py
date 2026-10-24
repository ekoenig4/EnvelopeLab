r"""Progress and remaining-time estimates of iterative solves, for progress displays.

An iterative solve reports a relative residual :math:`r` that must fall to a target
:math:`r^\ast`. The residual of dynamic relaxation is not monotonic. It stalls between
:math:`10^{-1}` and :math:`10^{-2}` for most of a solve and swings by a decade when the
kinetic damping resets, so a bar that maps :math:`r` itself to a position runs backwards
and sits near the start until the final drop. This module estimates progress from the
**best** residual so far, which never goes backwards:

.. math::
    f_{conv} = \frac{\log_{10}(r_0 / r_{best})}{\log_{10}(r_0 / r^\ast)}

with :math:`r_0` the first residual reported. With an iteration (or pass) limit, the
share of the limit used :math:`f_{lim} = i / i_{max}` bounds the time to the end of the
solve. The fraction shown is :math:`\max(f_{conv}, f_{lim})`. It is monotonic and reaches
1 when the solve ends either way, converged or stopped at its limit.

Remaining time
--------------
*To convergence*: the least-squares slope :math:`k` (decades per second) of
:math:`\log_{10} r_{best}` against time over the recent half of the solve (at least four
reports) gives :math:`t = \log_{10}(r_{best} / r^\ast) / k` while :math:`k < 0` and the
fit explains at least :data:`MIN_TREND_R2` of the variance (a stalled residual gives no
estimate, only the time to the limit). *To the
limit*: the remaining iterations at the iteration rate of the same recent window. When
the convergence estimate is longer than the time to the limit, the solve may stop
unconverged, and the text says so.

These are estimates for the display only; they never decide convergence.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

#: Least number of reports for a convergence-rate estimate.
MIN_TREND_SAMPLES = 4
#: Share of the elapsed time (the most recent) the convergence rate is fitted over.
TREND_WINDOW = 0.5
#: Least coefficient of determination of that fit for a remaining-time estimate.
MIN_TREND_R2 = 0.6


@dataclass(frozen=True)
class ProgressEstimate:
    """Progress of a solve.

    Attributes
    ----------
    fraction : float
        Progress in [0, 1], monotonic over a solve.
    convergence_fraction : float
        Decades of residual gained over the decades needed, in [0, 1].
    seconds_left : float or None
        Estimated time to convergence, s (None without a falling trend).
    seconds_to_limit : float or None
        Time until the iteration or pass limit at the current rate, s.
    """

    fraction: float
    convergence_fraction: float
    seconds_left: float | None
    seconds_to_limit: float | None

    @property
    def may_not_converge(self) -> bool:
        """A clear convergence trend runs past the limit: the solve may stop
        unconverged."""
        if self.seconds_to_limit is None or self.seconds_left is None:
            return False
        return self.seconds_left > self.seconds_to_limit

    def describe(self) -> str:
        """Short text: remaining time to convergence and to the limit."""
        parts = []
        if self.seconds_left is not None and not self.may_not_converge:
            parts.append(f"about {format_duration(self.seconds_left)} left")
        elif self.seconds_to_limit is not None and self.may_not_converge:
            parts.append("may not converge before the limit")
        if self.seconds_to_limit is not None:
            parts.append(f"limit in {format_duration(self.seconds_to_limit)}")
        return ", ".join(parts)


def format_duration(seconds: float) -> str:
    """``42 s``, ``3 min 05 s`` or ``1 h 02 min`` for a duration in seconds."""
    s = max(0, int(round(seconds)))
    if s < 60:
        return f"{s} s"
    if s < 3600:
        return f"{s // 60} min {s % 60:02d} s"
    return f"{s // 3600} h {(s % 3600) // 60:02d} min"


@dataclass
class ConvergenceEstimator:
    """Running progress estimate of one solve (module docstring).

    Parameters
    ----------
    tolerance : float
        Target relative residual :math:`r^\\ast` (> 0), dimensionless.
    """

    tolerance: float
    _first: float | None = None
    _best: float = math.inf
    _history: list[tuple[float, float]] = field(default_factory=list)
    _done: list[tuple[float, int]] = field(default_factory=list)
    _fraction: float = 0.0

    def __post_init__(self) -> None:
        if not self.tolerance > 0.0:
            raise ValueError("the target residual must be positive")

    def update(
        self,
        elapsed: float,
        residual: float,
        done: int | None = None,
        limit: int | None = None,
    ) -> ProgressEstimate:
        """Add a report and return the estimate.

        Parameters
        ----------
        elapsed : float
            Wall time since the start, s.
        residual : float
            Current relative residual, dimensionless (non-finite values are ignored for
            the convergence part).
        done, limit : int, optional
            Iterations (or passes) done and the limit.

        Returns
        -------
        ProgressEstimate
        """
        if math.isfinite(residual) and residual > 0.0:
            if self._first is None:
                self._first = max(residual, self.tolerance * 10.0)
            self._best = min(self._best, residual)
            self._history.append((elapsed, math.log10(self._best)))
        conv = self._convergence()
        limit_fraction = (
            min(1.0, done / limit) if done is not None and limit is not None and limit > 0 else 0.0
        )
        self._fraction = max(self._fraction, conv, limit_fraction)
        to_limit = None
        if done is not None and limit is not None and limit >= done:
            self._done.append((elapsed, done))
            to_limit = self._seconds_to_limit(limit)
        return ProgressEstimate(self._fraction, conv, self._seconds_left(), to_limit)

    def _seconds_to_limit(self, limit: int) -> float | None:
        """Remaining iterations over the recent iteration rate (the start of a solve can
        include one-off work, such as compiling the solver kernel)."""
        t_end, done = self._done[-1]
        recent = [(t, d) for t, d in self._done if t >= (1.0 - TREND_WINDOW) * t_end]
        t0, d0 = recent[0]
        if t_end <= t0 or done <= d0:
            return None  # no rate yet
        return (limit - done) * (t_end - t0) / (done - d0)

    def _convergence(self) -> float:
        if self._first is None or not math.isfinite(self._best):
            return 0.0
        if self._best <= self.tolerance:
            return 1.0
        span = math.log10(self._first / self.tolerance)
        return max(0.0, min(1.0, math.log10(self._first / self._best) / span))

    def _seconds_left(self) -> float | None:
        if not self._history or self._best <= self.tolerance:
            return 0.0 if self._best <= self.tolerance else None
        t_end = self._history[-1][0]
        recent = [(t, y) for t, y in self._history if t >= (1.0 - TREND_WINDOW) * t_end]
        if len(recent) < MIN_TREND_SAMPLES:
            return None
        n = len(recent)
        mt = sum(t for t, _ in recent) / n
        my = sum(y for _, y in recent) / n
        var = sum((t - mt) ** 2 for t, _ in recent)
        if var <= 0.0:
            return None
        slope = sum((t - mt) * (y - my) for t, y in recent) / var
        if slope >= 0.0:
            return None
        # Only a clear decline predicts anything: while the residual stalls (dynamic
        # relaxation often does for most of a solve) the fit is noise.
        total = sum((y - my) ** 2 for _, y in recent)
        explained = slope**2 * var
        if total <= 0.0 or explained / total < MIN_TREND_R2:
            return None
        return (math.log10(self._best) - math.log10(self.tolerance)) / -slope


#: Share of a CalculiX pass taken by its held job (the release job takes the rest);
#: measured on the generic fixture (17 s of 145 s over 60 passes).
HELD_SHARE = 0.12


@dataclass
class PassProgress:
    """Progress of a solve made of passes (the CalculiX verification solve).

    Within a pass the bar follows the running job (``job_fraction``, from the solver's
    status file). Across passes it follows the residual decades gained (module
    docstring), interpolated over the pass with the gain of the passes so far. The first
    pass is assumed to converge, as a solve started from an equilibrium does. Remaining
    time: the mean pass time times the passes still needed at the mean gain per pass.

    Parameters
    ----------
    tolerance : float
        Target relative residual, dimensionless.
    max_passes : int
        Pass limit.
    """

    tolerance: float
    max_passes: int
    _first: float | None = None
    _best: float = math.inf
    _pass_ends: list[tuple[float, float]] = field(default_factory=list)
    _fraction: float = 0.0

    def _decades(self) -> float:
        if self._first is None or not math.isfinite(self._best):
            return 0.0
        if self._best <= self.tolerance:
            return 1.0
        span = math.log10(self._first / self.tolerance)
        return max(0.0, min(1.0, math.log10(self._first / self._best) / span))

    def update(
        self,
        elapsed: float,
        pass_no: int,
        job: str,
        job_fraction: float = 0.0,
        residual: float | None = None,
        pass_ended: bool = False,
    ) -> ProgressEstimate:
        """Add a report and return the estimate.

        Parameters
        ----------
        elapsed : float
            Wall time since the start, s.
        pass_no : int
            Current pass, 1-based.
        job : str
            ``held``, ``release`` or ``done``.
        job_fraction : float
            Progress of the running job in [0, 1].
        residual : float, optional
            Latest relative out-of-balance, dimensionless.
        pass_ended : bool
            ``residual`` is the out-of-balance at the end of pass ``pass_no``.
        """
        if job == "done":
            self._fraction = 1.0
            return ProgressEstimate(1.0, self._decades(), 0.0, None)
        if residual is not None and math.isfinite(residual) and residual > 0.0:
            if self._first is None:
                self._first = max(residual, self.tolerance * 10.0)
            # Only the out-of-balance after a pass shows progress: the one a held job
            # starts from can already be below the target while the pass still runs.
            if pass_ended:
                self._best = min(self._best, residual)
        if pass_ended:
            self._pass_ends.append((elapsed, self._decades()))
        within = (
            HELD_SHARE * job_fraction
            if job == "held"
            else (HELD_SHARE + (1.0 - HELD_SHARE) * job_fraction)
        )
        reached = self._decades()
        # Mean gain per completed pass (decade fraction), counted from the start.
        mean_gain = self._pass_ends[-1][1] / len(self._pass_ends) if self._pass_ends else 0.0
        gain = mean_gain if mean_gain > 0.0 else 1.0 - reached
        expected = min(1.0, reached + gain * within)
        limit_part = min(1.0, (pass_no - 1 + within) / self.max_passes)
        # The final equilibrium check (a held job) still runs after the last pass.
        self._fraction = min(max(self._fraction, expected, limit_part), 1.0 - HELD_SHARE / 4)
        seconds_left = to_limit = None
        if self._pass_ends:
            per_pass = self._pass_ends[-1][0] / len(self._pass_ends)
            to_limit = per_pass * max(self.max_passes - (pass_no - 1) - within, 0.0)
            if mean_gain > 0.0:
                passes_needed = (1.0 - reached) / mean_gain
                # The final held job (the equilibrium check) follows the last pass.
                seconds_left = (max(passes_needed - within, 0.0) + HELD_SHARE) * per_pass
        return ProgressEstimate(self._fraction, reached, seconds_left, to_limit)
