"""Presentation of solver results in the 3D view: colour bands and the status banner.

Display only: the values come from :mod:`envelopelab.project.run_fields`; this module
decides how they are coloured and what the banner over the view says. The rules follow
the safety rules of the project: a failing factor of safety is always drawn in
:data:`~envelopelab_app.theme.FAIL_COLOR` and named in the banner, a stale result is never
coloured, and an unconverged result is never coloured as a normal one.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from envelopelab.project.run_fields import SAFETY_FIELDS
from envelopelab.solvers.results import ResultField
from envelopelab_app.theme import FAIL_COLOR

#: Factor-of-safety bands above the limit, as multiples of the limit (with a limit of 5:
#: 5-6, 6-8, 8-10, >= 10), and their colours (light = more margin).
FOS_BAND_FACTORS = (1.0, 1.2, 1.6, 2.0)
FOS_BAND_COLORS = ("#2f6fb0", "#5b97cf", "#9cc3e6", "#d3e5f5")
#: Wrinkle state colours: taut, wrinkled, slack.
WRINKLE_COLORS = ("#d3e5f5", "#e7ba52", "#b42318")
#: Continuous colour map of the other fields (perceptually uniform, colour-blind safe).
CONTINUOUS_CMAP = "viridis"


@dataclass(frozen=True)
class Bands:
    """A categorical colouring.

    Attributes
    ----------
    index : ndarray of int
        Band of every value (0 = first entry of ``labels``).
    colors : tuple of str
        Colour per band (hex).
    labels : tuple of str
        Label per band, for the scalar bar.
    """

    index: np.ndarray
    colors: tuple[str, ...]
    labels: tuple[str, ...]


def fos_bands(values: np.ndarray, limit: float) -> Bands:
    """Factor-of-safety bands: below ``limit`` (FAIL), then the bands of
    :data:`FOS_BAND_FACTORS` (an unloaded element, ``inf``, is in the last band).

    Parameters
    ----------
    values : ndarray
        Factors of safety, dimensionless.
    limit : float
        Required factor, dimensionless.
    """
    edges = np.array([f * limit for f in FOS_BAND_FACTORS])
    index = np.digitize(np.asarray(values, dtype=float), edges)
    labels = [f"< {limit:g}  FAIL"]
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        labels.append(f"{lo:g} – {hi:g}")
    labels.append(f"≥ {edges[-1]:g}")
    return Bands(index.astype(np.int64), (FAIL_COLOR, *FOS_BAND_COLORS), tuple(labels))


def wrinkle_bands(values: np.ndarray) -> Bands:
    """Wrinkle state bands: taut, wrinkled, slack."""
    index = np.clip(np.rint(np.asarray(values, dtype=float)), 0, 2).astype(np.int64)
    return Bands(index, WRINKLE_COLORS, ("taut", "wrinkled", "slack"))


@dataclass(frozen=True)
class Banner:
    """What the status banner says.

    Attributes
    ----------
    kind : str
        A key of :data:`envelopelab_app.theme.STATUS_STYLES`.
    title, message : str
        Statement and details.
    action : str
        Action button text ("" for none).
    request : str
        Solver to run when the action is chosen ("" for none).
    """

    kind: str
    title: str
    message: str = ""
    action: str = ""
    request: str = ""


@dataclass(frozen=True)
class RunState:
    """The facts about one run that decide its banner.

    Attributes
    ----------
    solver, solver_label, run_id : str
        Solver id and name, and run id.
    converged, stale : bool
        Convergence and staleness.
    status : str
        The solver's stop reason.
    iterations : int
    residual : float
        Final residual, dimensionless.
    errors : tuple of str
        Error-level findings.
    warnings : tuple of str
        Temperature and other limit findings to report as failures.
    failing_zones : tuple of str
        Material zones (with direction) whose factor of safety is below the limit.
    min_fos : float, optional
        Lowest factor of safety, dimensionless (None when not available).
    limit : float
        Required factor, dimensionless.
    limit_source : str
        Source tag of the limit.
    verified : bool
        A current, converged CalculiX run exists too.
    """

    solver: str
    solver_label: str
    run_id: str
    converged: bool
    stale: bool
    status: str
    iterations: int
    residual: float
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    failing_zones: tuple[str, ...] = ()
    min_fos: float | None = None
    limit: float = 5.0
    limit_source: str = "assumed"
    verified: bool = False


def banner_for(run: RunState | None) -> Banner | None:
    """The banner for the run shown in the 3D view (None: no run, nothing to say).

    Order, worst first: not converged (or error findings), stale, limits exceeded
    (factor of safety, temperature), then current and converged (verified or not).
    """
    if run is None:
        return None
    if not run.converged or run.errors:
        detail = f"{run.solver_label} run {run.run_id} stopped: {run.status}; "
        detail += f"{run.iterations} iterations, residual {run.residual:.1e}."
        if run.errors:
            detail += " " + " ".join(run.errors[:2])
        return Banner(
            "error",
            "Not converged — values are not final.",
            detail + " The surface is not coloured as a result.",
        )
    if run.stale:
        return Banner(
            "stale",
            "Stale result.",
            f"The design has changed since {run.solver_label} run {run.run_id}. "
            "The surface is drawn grey; its values are not current.",
            f"Re-run {run.solver_label}",
            run.solver,
        )
    if run.failing_zones or run.warnings:
        parts = []
        if run.failing_zones:
            zones = ", ".join(run.failing_zones[:4])
            more = len(run.failing_zones) - 4
            if more > 0:
                zones += f" and {more} more"
            low = f"minimum {run.min_fos:.2f}" if run.min_fos is not None else ""
            parts.append(
                f"Factor of safety below {run.limit:g} ({run.limit_source}) in "
                f"{len(run.failing_zones)} zone direction(s): {zones}; {low}. "
                "Failing regions are drawn orange."
            )
        parts.extend(run.warnings[:2])
        title = (
            "Factor of safety below the limit."
            if run.failing_zones
            else "A design limit is exceeded."
        )
        return Banner("fail", title, " ".join(parts))
    if run.solver == "calculix" or run.verified:
        return Banner(
            "ok",
            "Current and converged.",
            "A current, converged CalculiX run exists for this design.",
        )
    return Banner(
        "info",
        "Current and converged.",
        f"{run.solver_label} only — not yet verified with CalculiX.",
        "Run CalculiX",
        "calculix",
    )


def failing_zone_names(
    fos: np.ndarray, zone_of_triangle: list[str], direction: str, limit: float
) -> list[str]:
    """Zones (named ``"<zone> (<direction>)"``) with a triangle below ``limit``."""
    below = np.asarray(fos) < limit
    return sorted({f"{zone_of_triangle[i]} ({direction})" for i in np.flatnonzero(below)})


def lowest_fos(fields: Mapping[str, ResultField]) -> float | None:
    """Lowest finite fabric factor of safety of a run's fields (None when the run has
    none: no warp/weft resultants, not current, or every element unloaded)."""
    lows = []
    for name in SAFETY_FIELDS:
        field = fields.get(name)
        if field is None:
            continue
        finite = field.values[np.isfinite(field.values)]
        if finite.size:
            lows.append(float(finite.min()))
    return min(lows) if lows else None


def design_banner(
    outputs_error: str | None,
    errors: list[str],
    lift_margin: float | None,
    compressed_fraction: float,
    compression_text: str = "",
) -> Banner | None:
    """The banner over the gore editor's profile (None: nothing wrong to report).

    Worst first: the outputs cannot be computed or the design has errors; then a negative
    lift margin and a profile that needs compression under load (both design limits).

    Parameters
    ----------
    outputs_error : str, optional
        Why the live outputs could not be computed.
    errors : list of str
        Error-level design findings.
    lift_margin : float, optional
        Lift margin after rigging and payload, kg (None when unknown).
    compressed_fraction : float
        Fraction of the tape that needs compression under load (0 when it holds, or
        when the shape check is off), dimensionless.
    compression_text : str
        The shape check's own description of the compressed part.
    """
    if outputs_error or errors:
        messages = ([outputs_error] if outputs_error else []) + errors
        return Banner(
            "error",
            "The design has errors — outputs are not final.",
            " ".join(m.rstrip(".") + "." for m in messages[:3]),
        )
    parts: list[str] = []
    if lift_margin is not None and lift_margin < 0.0:
        parts.append(
            f"Lift margin {lift_margin:.1f} kg: the envelope cannot lift its rigging and "
            "payload at these conditions."
        )
    if compressed_fraction > 0.0:
        fallback = f"{compressed_fraction:.0%} of the tape needs compression."
        parts.append(compression_text or fallback)
    if parts:
        if len(parts) > 1:
            title = "A design limit is exceeded."
        elif compressed_fraction > 0.0:
            title = "The shape will not hold under load."
        else:
            title = "Negative lift margin."
        return Banner("fail", title, " ".join(parts))
    return None
