"""Progress and remaining-time estimates of solves (the progress bar and its text)."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from calculix_adapter.results import job_fraction
from envelopelab.solvers.progress import (
    HELD_SHARE,
    ConvergenceEstimator,
    PassProgress,
    format_duration,
)


def stall_then_drop(n: int = 200) -> list[tuple[float, float, int]]:
    """(time s, residual, iteration) of a dynamic-relaxation-like solve: the residual
    swings between 1e-1 and 1e-2 for 60 % of the time, then falls steadily from 1e-2 to
    the target 1e-6; 200 iterations per report, 10 reports a second."""
    out = []
    for k in range(1, n + 1):
        t = 0.1 * k
        if k < 0.6 * n:
            r = 10 ** (-1.5 + 0.5 * math.sin(k))
        else:
            r = 10 ** (-2.0 - 4.0 * (k - 0.6 * n) / (0.4 * n))
        out.append((t, r, 200 * k))
    return out


def test_the_bar_never_goes_back_and_ends_full_on_convergence() -> None:
    est = ConvergenceEstimator(1e-6)
    fractions = [est.update(t, r, i, 200_000).fraction for t, r, i in stall_then_drop()]
    assert all(b >= a for a, b in zip(fractions, fractions[1:], strict=False))
    assert fractions[-1] == 1.0
    # The swinging residual of the stall does not move the bar back or to the end.
    assert 0.0 < fractions[int(0.5 * len(fractions))] < 0.5


def test_a_stuck_solve_fills_the_bar_by_its_iteration_limit() -> None:
    est = ConvergenceEstimator(1e-6)
    last = None
    for k in range(1, 101):
        last = est.update(0.5 * k, 10 ** (-1.2 + 0.3 * math.sin(k)), 2000 * k, 200_000)
    assert last is not None
    assert last.fraction == pytest.approx(1.0)
    assert last.seconds_to_limit == pytest.approx(0.0, abs=1e-9)


def test_remaining_time_follows_a_clean_decline_and_the_limit_uses_the_recent_rate() -> None:
    est = ConvergenceEstimator(1e-6)
    # A slow first report (kernel compilation), then 1000 iterations and one decade of
    # residual per second.
    est.update(5.0, 1.0, 100, 100_000)
    last = None
    for k in range(1, 11):
        last = est.update(5.0 + k, 10.0**-k * 0.99, 100 + 1000 * k, 100_000)
    assert last is not None
    # Residual 1e-10 is below the target: done.
    assert last.fraction == 1.0
    est = ConvergenceEstimator(1e-6)
    est.update(5.0, 1.0, 100, 100_000)
    for k in range(1, 4):
        last = est.update(5.0 + k, 10.0**-k, 100 + 1000 * k, 100_000)
    assert last is not None and last.seconds_left is not None
    assert last.seconds_left == pytest.approx(3.0, rel=0.05)  # 3 decades at 1 per second
    assert last.seconds_to_limit == pytest.approx((100_000 - 3100) / 1000.0, rel=0.02)
    assert last.describe() == f"about 3 s left, limit in {format_duration(96.9)}"


def test_no_remaining_time_while_the_residual_stalls() -> None:
    est = ConvergenceEstimator(1e-6)
    last = None
    for k in range(1, 30):
        last = est.update(float(k), 0.05, 100 * k, 1_000_000)
    assert last is not None
    assert last.seconds_left is None and not last.may_not_converge
    assert last.describe().startswith("limit in")


def test_a_trend_past_the_limit_warns() -> None:
    est = ConvergenceEstimator(1e-6)
    last = None
    for k in range(1, 20):
        last = est.update(float(k), 10 ** (-0.05 * k), 1000 * k, 25_000)
    assert last is not None and last.may_not_converge
    assert "may not converge" in last.describe()


def test_durations_read_naturally() -> None:
    assert format_duration(42.4) == "42 s"
    assert format_duration(185) == "3 min 05 s"
    assert format_duration(3725) == "1 h 02 min"


def test_a_calculix_start_below_the_target_is_not_the_end() -> None:
    """A warm start's held job can begin below the target: the bar follows the pass."""
    est = PassProgress(1e-5, 60)
    first = est.update(0.0, 1, "held", 0.0, math.inf)
    held = est.update(0.5, 1, "release", 0.0, 9.6e-7)
    mid = est.update(3.0, 1, "release", 0.5, 9.6e-7)
    end = est.update(6.0, 1, "release", 1.0, 6.7e-7, pass_ended=True)
    assert first.fraction == 0.0
    assert held.fraction == pytest.approx(HELD_SHARE)
    assert mid.fraction == pytest.approx(HELD_SHARE + (1 - HELD_SHARE) * 0.5)
    assert end.fraction < 1.0  # the final equilibrium check still runs
    assert est.update(6.6, 2, "done").fraction == 1.0


def test_calculix_remaining_time_comes_from_the_passes_so_far() -> None:
    est = PassProgress(1e-5, 60)
    est.update(0.0, 1, "held", 0.0, 1e-1)
    est.update(10.0, 1, "release", 1.0, 1e-3, pass_ended=True)  # 2 of 4 decades
    after = est.update(10.0, 2, "held", 0.0, 1e-3)
    assert after.convergence_fraction == pytest.approx(0.5)
    assert after.seconds_left is not None
    # One more pass of 10 s, then the final held job.
    assert after.seconds_left == pytest.approx(10.0 * (1.0 + HELD_SHARE), rel=1e-6)
    assert after.seconds_to_limit == pytest.approx(10.0 * 59, rel=1e-6)


def test_job_progress_is_read_from_the_status_file(tmp_path: Path) -> None:
    sta = tmp_path / "job.sta"
    assert job_fraction(sta, 3) == 0.0
    sta.write_text(
        "SUMMARY OF JOB INFORMATION\n"
        " STEP      INC     ATT    ITRS     TOT TIME     STEP TIME         INC TIME\n"
        "    1        1       1       3  0.100000E+01  0.100000E+01  0.100000E+01\n"
        "    2        1       1       4  0.125000E+01  0.250000E+00  0.250000E+00\n"
        "    2        2       1",  # a line being written
        encoding="utf-8",
    )
    assert job_fraction(sta, 3) == pytest.approx((1 + 0.25) / 3)
