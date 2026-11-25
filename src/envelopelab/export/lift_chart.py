"""Build-pack lift chart: ``<slug>-lift-chart.pdf`` and ``<slug>-lift-chart.csv``.

The equilibrium points come from :mod:`envelopelab.lift_chart`; this module only picks
the chart axes from the design and draws them. Pages (A4 landscape):

1. maximum load at the top-temperature limit vs ambient temperature, one curve per
   altitude (the flight-manual loading chart), with the inputs and their source tags;
2. gross lift vs crown (top) temperature, the temperature the pilot reads, one panel per
   altitude, one curve per ambient temperature (the classic lift chart of builders'
   spreadsheets, with the mean gas temperature behind each point taken from the crown
   temperature), with the envelope + rigging mass and the design load as lines and the
   crown limit marked;
3. top temperature needed vs load, one panel per altitude, one curve per ambient
   temperature; the region above the limit is shaded and labelled;
4. equilibrium altitude (ceiling) vs load at the limit, one curve per ISA deviation;
5. how the charts are calculated (:func:`theory_sections`): the equations, constants and
   the values this envelope's charts use.

The CSV lists every equilibrium point of the grid with its status. Nothing is hidden: a
state above the limit is marked ``above_limit``, a load the envelope cannot lift
``no_equilibrium``.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from envelopelab.atmosphere import (
    CELSIUS_OFFSET,
    PhysicalConstant,
    differential_pressure,
    gas_density,
    isa,
)
from envelopelab.export.documents import SAFETY_NOTICE, pdf_text
from envelopelab.lift_chart import (
    DEFAULT_TOP_TO_MEAN,
    LiftChart,
    LiftChartInputs,
    equilibrium_altitude,
    equilibrium_load,
    equilibrium_top_temperature,
    lift_chart,
    lift_mass,
    nice_step,
)
from envelopelab.stratification import (
    DEFAULT_MOUTH_EXCESS,
    StratificationModel,
    VolumeDistribution,
)

if TYPE_CHECKING:
    from envelopelab.design.model import DesignDocument
    from envelopelab.export.shop import PackContext
    from envelopelab.project.gore_design import GoreOutputs
    from envelopelab.project.lift_chart_settings import LiftChartSettings

RGB = tuple[float, float, float]
#: Ambient temperature axis of the loading chart, degC (widened to cover the chosen
#: ambient temperatures).
AMBIENT_AXIS_C = (-20.0, 40.0)
#: Points per curve.
SAMPLES = 61
COLOURS: tuple[RGB, ...] = (
    (0.11, 0.37, 0.71),
    (0.85, 0.45, 0.05),
    (0.20, 0.55, 0.20),
    (0.55, 0.25, 0.65),
    (0.10, 0.60, 0.65),
    (0.45, 0.45, 0.45),
)
RED = (0.75, 0.12, 0.10)
MUTED = (0.33, 0.36, 0.40)
GRID = (0.85, 0.87, 0.90)
TINT = (0.99, 0.90, 0.89)
BLUE = (0.11, 0.37, 0.71)
#: Start of the crown-temperature axis of the gross-lift chart, degC.
TOP_AXIS_START_C = 40.0
#: Exact unit definitions (international pound and foot, 1959; NIST SP 811).
KG_PER_LB = 0.45359237
M_PER_FT = 0.3048


def lb(kg: float) -> float:
    """Pounds (lb) of a mass in kg."""
    return kg / KG_PER_LB


def ft(m: float) -> float:
    """Feet (ft) of a length in m."""
    return m / M_PER_FT


def fahrenheit(celsius: float) -> float:
    """degF of a temperature in degC."""
    return celsius * 1.8 + 32.0


def kg_lb(kg: float) -> str:
    """``300 kg / 661 lb``."""
    return f"{kg:,.0f} kg / {lb(kg):,.0f} lb"


def c_f(celsius: float) -> str:
    """``120 degC / 248 degF``."""
    return f"{celsius:.0f} degC / {fahrenheit(celsius):.0f} degF"


@dataclass(frozen=True)
class SecondAxis:
    """English-unit scale opposite a metric axis: ``english = scale * metric + offset``."""

    label: str
    scale: float
    offset: float = 0.0


LB_AXIS = SecondAxis("lb", 1.0 / KG_PER_LB)
F_AXIS = SecondAxis("degF", 1.8, 32.0)
FT_AXIS = SecondAxis("ft", 1.0 / M_PER_FT)


def top_temperature_limit(design: DesignDocument, fabrics: Any = None) -> PhysicalConstant:
    """Lowest service temperature of the design's fabrics, K, as the top-temperature limit.

    Parameters
    ----------
    design : DesignDocument
        Design whose zones name the fabrics.
    fabrics : FabricLibraryRepository or FabricCatalog, optional
        Fabric library; a fabric missing from it gets the generic ``assumed`` 120 degC of
        :func:`envelopelab.project.simulation.membrane_for_fabric`.

    Returns
    -------
    PhysicalConstant
        Limit in K with the source tag of the fabric that sets it.
    """
    from envelopelab.project.simulation import membrane_for_fabric

    best: PhysicalConstant | None = None
    for zone, fabric_id in sorted(design.zones.items()):
        value = membrane_for_fabric(fabric_id, fabrics).max_service_temperature
        if best is None or value.value < best.value:
            known = fabrics is not None and fabrics.fabric(fabric_id) is not None
            where = value.note if known else "not in the fabric library: generic value"
            best = PhysicalConstant(
                value.value,
                "K",
                value.source,
                f"service temperature of fabric {fabric_id!r} (zone {zone}); {where}",
            )
    if best is None:
        fallback = membrane_for_fabric("", None).max_service_temperature
        best = PhysicalConstant(fallback.value, "K", fallback.source, "no fabric zones")
    return best


def chart_inputs(
    design: DesignDocument,
    outputs: GoreOutputs | None,
    fabrics: Any = None,
    top_to_mean: PhysicalConstant = DEFAULT_TOP_TO_MEAN,
    stratify: bool = True,
    mouth_excess: PhysicalConstant = DEFAULT_MOUTH_EXCESS,
    top_limit: PhysicalConstant | None = None,
) -> LiftChartInputs | None:
    """The lift-chart inputs of a gore design, or None when its mass is not estimated.

    Parameters
    ----------
    design : DesignDocument
        Gore design.
    outputs : GoreOutputs or None
        Its live outputs (volume m^3, envelope and rigging mass kg).
    fabrics : FabricLibraryRepository or FabricCatalog, optional
        Fabric library for the top-temperature limit.
    top_to_mean : PhysicalConstant, optional
        Top minus mean internal temperature, K: the offset, or the floor when
        ``stratify``.
    stratify : bool, optional
        Take the mean from the envelope's shape and an assumed linear temperature
        profile (:mod:`envelopelab.stratification`; the default, ADR-0060); False: a fixed
        offset.
    mouth_excess : PhysicalConstant, optional
        Mouth temperature rise as a fraction of the crown's, dimensionless (``stratify``).
    top_limit : PhysicalConstant, optional
        Crown temperature limit, K, with its source; default the lowest service
        temperature of the design's fabrics (:func:`top_temperature_limit`), which is
        kept for comparison when a limit is given.

    Returns
    -------
    LiftChartInputs or None
    """
    if outputs is None or outputs.envelope_mass is None:
        return None
    fabric_limit = top_temperature_limit(design, fabrics)
    stratification = None
    if stratify:
        from envelopelab.project.gore_design import design_profile

        profile = design_profile(design)
        stratification = StratificationModel(
            VolumeDistribution.from_profile(profile.r, profile.z, outputs.volume),
            mouth_excess,
            top_to_mean,
        )
    return LiftChartInputs(
        volume=outputs.volume,
        volume_note="lofted design profile (as drawn, not a solved inflated shape)",
        fixed_mass=outputs.envelope_mass + (outputs.rigging_mass or 0.0),
        fixed_mass_sources=outputs.sources,
        top_limit=fabric_limit if top_limit is None else top_limit,
        top_to_mean=top_to_mean,
        stratification=stratification,
        fabric_limit=None if top_limit is None else fabric_limit,
    )


@dataclass(frozen=True)
class ChartAxes:
    """The grid of a build-pack lift chart (SI: m, K, kg)."""

    altitudes: tuple[float, ...]
    ambient_temperatures: tuple[float, ...]
    top_temperatures: tuple[float, ...]
    loads: tuple[float, ...]
    isa_offsets: tuple[float, ...]


def chart_axes(inputs: LiftChartInputs, settings: LiftChartSettings | None = None) -> ChartAxes:
    """The chart grid from the project's lift-chart settings (defaults when None).

    Altitudes, ambient temperatures and ISA deviations are the settings' own; top
    temperatures run every 10 degC from the lowest top temperature up to the limit (the
    limit always included); loads run from 0 to the settings' load-axis end, or else to
    the most the balloon lifts (lowest altitude, coldest ambient, at the limit), in round
    steps.

    Parameters
    ----------
    inputs : LiftChartInputs
        Volume (m^3), fixed mass (kg), limit and offset (K).
    settings : LiftChartSettings, optional
        Curves (SI: m, K, kg).

    Returns
    -------
    ChartAxes
    """
    from envelopelab.project.lift_chart_settings import LiftChartSettings

    s = settings if settings is not None else LiftChartSettings()
    limit = inputs.top_limit.value
    tops: list[float] = []
    t = s.lowest_top_temperature
    while t < limit - 1e-9:
        tops.append(t)
        t += 10.0
    tops.append(limit)
    ambients = tuple(s.ambient_temperatures)
    if s.max_load is not None:
        top_load = s.max_load
    else:
        most = equilibrium_load(inputs, min(s.altitudes), min(ambients), limit).load
        top_load = max(most, 100.0)
    step = nice_step(top_load, 10)
    loads = tuple(step * k for k in range(int(math.ceil(top_load / step - 1e-9)) + 1))
    return ChartAxes(tuple(s.altitudes), ambients, tuple(tops), loads, tuple(s.isa_offsets))


def build_chart(inputs: LiftChartInputs, axes: ChartAxes) -> LiftChart:
    """The equilibrium points of ``axes`` (:func:`envelopelab.lift_chart.lift_chart`)."""
    return lift_chart(
        inputs,
        axes.altitudes,
        axes.ambient_temperatures,
        axes.top_temperatures,
        axes.loads,
        axes.isa_offsets,
    )


# --------------------------------------------------------------------------------------
# CSV
# --------------------------------------------------------------------------------------

CSV_COLUMNS = (
    "solved_for",
    "altitude_m",
    "isa_offset_K",
    "ambient_C",
    "top_C",
    "mean_C",
    "load_kg",
    "gross_lift_N",
    "status",
)


def _c(kelvin: float) -> str:
    return "" if not math.isfinite(kelvin) else f"{kelvin - CELSIUS_OFFSET:.2f}"


def _num(value: float, digits: int = 2) -> str:
    return "" if not math.isfinite(value) else f"{value:.{digits}f}"


def csv_rows(chart: LiftChart) -> list[list[str]]:
    """One row per equilibrium point (:data:`CSV_COLUMNS`; blank where undefined)."""
    return [
        [
            p.solved_for,
            _num(p.altitude, 1),
            _num(p.isa_offset, 1),
            _c(p.ambient_temperature),
            _c(p.top_temperature),
            _c(p.mean_temperature),
            _num(p.load, 2),
            _num(p.gross_lift, 1),
            p.status,
        ]
        for p in chart.points()
    ]


def write_lift_chart_csv(chart: LiftChart, path: str | Path) -> Path:
    """Write ``chart``'s equilibrium points as CSV; returns the path."""
    out = Path(path)
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_COLUMNS)
        writer.writerows(csv_rows(chart))
    return out


# --------------------------------------------------------------------------------------
# PDF
# --------------------------------------------------------------------------------------


@dataclass
class Series:
    """One curve: label, (x, y) points (``nan`` breaks the line) and colour."""

    label: str
    points: list[tuple[float, float]]
    colour: RGB
    dash: tuple[float, float] | None = None


@dataclass
class Plot:
    """A line chart in a box of the page (points)."""

    box: tuple[float, float, float, float]  # x, y (bottom left), width, height
    title: str
    xlabel: str
    ylabel: str
    xrange: tuple[float, float]
    yrange: tuple[float, float]
    series: list[Series] = field(default_factory=list)
    hlines: list[tuple[float, str, RGB]] = field(default_factory=list)
    vlines: list[tuple[float, str, RGB]] = field(default_factory=list)
    shade_above: tuple[float, str] | None = None
    shade_right: tuple[float, str] | None = None
    legend_at_bottom: bool = False
    #: Legend at the left instead of the right (clear of curves that rise to the right).
    legend_left: bool = False
    x2: SecondAxis | None = None
    y2: SecondAxis | None = None


def _clip(
    a: tuple[float, float], b: tuple[float, float], lo: tuple[float, float], hi: tuple[float, float]
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """Liang-Barsky clip of segment ab to the box [lo, hi]; None when outside."""
    t0, t1 = 0.0, 1.0
    dx, dy = b[0] - a[0], b[1] - a[1]
    for p, q in (
        (-dx, a[0] - lo[0]),
        (dx, hi[0] - a[0]),
        (-dy, a[1] - lo[1]),
        (dy, hi[1] - a[1]),
    ):
        if p == 0.0:
            if q < 0.0:
                return None
            continue
        r = q / p
        if p < 0.0:
            t0 = max(t0, r)
        else:
            t1 = min(t1, r)
        if t0 > t1:
            return None
    return (a[0] + t0 * dx, a[1] + t0 * dy), (a[0] + t1 * dx, a[1] + t1 * dy)


def _ticks(lo: float, hi: float, count: int = 8) -> list[float]:
    step = nice_step(hi - lo, count)
    start = math.ceil(lo / step - 1e-9) * step
    out, k = [], 0
    while start + k * step <= hi + 1e-9 * step:
        out.append(start + k * step)
        k += 1
    return out


def _label(value: float) -> str:
    return f"{value:,.0f}" if abs(value - round(value)) < 1e-9 else f"{value:,.1f}"


def draw_plot(canvas: Any, plot: Plot) -> None:
    """Draw ``plot`` on the current page of a :class:`~envelopelab.report.pdf.PdfCanvas`."""
    x0, y0, w, h = plot.box
    (xa, xb), (ya, yb) = plot.xrange, plot.yrange

    def to_page(x: float, y: float) -> tuple[float, float]:
        return x0 + (x - xa) / (xb - xa) * w, y0 + (y - ya) / (yb - ya) * h

    if plot.shade_above is not None and plot.shade_above[0] < yb:
        level = max(plot.shade_above[0], ya)
        _, py = to_page(xa, level)
        canvas.rect(x0, py, w, y0 + h - py, fill=TINT)
    if plot.shade_right is not None and plot.shade_right[0] < xb:
        px, _ = to_page(max(plot.shade_right[0], xa), ya)
        canvas.rect(px, y0, x0 + w - px, h, fill=TINT)
    for x in _ticks(xa, xb):
        px, _ = to_page(x, ya)
        canvas.line(px, y0, px, y0 + h, GRID, 0.3)
        canvas.text(px - 2.2 * len(_label(x)), y0 - 10, _label(x), 7, color=MUTED)
    for y in _ticks(ya, yb):
        _, py = to_page(xa, y)
        canvas.line(x0, py, x0 + w, py, GRID, 0.3)
        canvas.text(x0 - 4 - 3.9 * len(_label(y)), py - 2.5, _label(y), 7, color=MUTED)
    if plot.x2 is not None:
        sa, sb = sorted(plot.x2.scale * v + plot.x2.offset for v in (xa, xb))
        for t in _ticks(sa, sb):
            px, _ = to_page((t - plot.x2.offset) / plot.x2.scale, ya)
            canvas.line(px, y0 + h, px, y0 + h + 3, MUTED, 0.5)
            canvas.text(px - 2.2 * len(_label(t)), y0 + h + 5, _label(t), 7, color=MUTED)
    if plot.y2 is not None:
        sa, sb = sorted(plot.y2.scale * v + plot.y2.offset for v in (ya, yb))
        for t in _ticks(sa, sb):
            _, py = to_page(xa, (t - plot.y2.offset) / plot.y2.scale)
            canvas.line(x0 + w, py, x0 + w + 3, py, MUTED, 0.5)
            canvas.text(x0 + w + 5, py - 2.5, _label(t), 7, color=MUTED)
        y2 = pdf_text(f"({plot.y2.label})")
        canvas.text(x0 + w - 4.0 * len(y2), y0 + h + 16, y2, 8)
    canvas.rect(x0, y0, w, h, stroke=(0.0, 0.0, 0.0))
    canvas.text(x0, y0 + h + 28, pdf_text(plot.title), 9, True)
    xlabel = plot.xlabel
    if plot.x2 is not None:
        xlabel += f"; top scale {plot.x2.label}"
    canvas.text(x0 + w / 2 - 2.0 * len(xlabel), y0 - 22, pdf_text(xlabel), 8)
    canvas.text(x0, y0 + h + 16, pdf_text(plot.ylabel), 8)
    for level, text, colour in plot.hlines:
        if ya <= level <= yb:
            _, py = to_page(xa, level)
            canvas.polygon(
                [(x0, py), (x0 + w, py)], stroke=colour, width=1.0, dash=(4, 3), closed=False
            )
            canvas.text(x0 + w - 4.0 * len(text) - 4, py + 3, pdf_text(text), 7, True, colour)
    for level, text, colour in plot.vlines:
        if xa <= level <= xb:
            px, _ = to_page(level, ya)
            canvas.polygon(
                [(px, y0), (px, y0 + h)], stroke=colour, width=0.8, dash=(2, 2), closed=False
            )
            # Left of the line: the legend sits at the bottom right.
            label = pdf_text(text)
            canvas.text(px - 3 - 3.5 * len(label), y0 + 4, label, 7, color=colour)
    for s in plot.series:
        run: list[tuple[float, float]] = []
        segments: list[list[tuple[float, float]]] = []
        for a, b in zip(s.points, s.points[1:], strict=False):
            if not all(math.isfinite(v) for v in (*a, *b)):
                continue
            clipped = _clip(a, b, (xa, ya), (xb, yb))
            if clipped is None:
                continue
            p, q = to_page(*clipped[0]), to_page(*clipped[1])
            if run and math.dist(run[-1], p) < 1e-6:
                run.append(q)
            else:
                if len(run) > 1:
                    segments.append(run)
                run = [p, q]
        if len(run) > 1:
            segments.append(run)
        for seg in segments:
            canvas.polygon(seg, stroke=s.colour, width=1.4, dash=s.dash, closed=False)
    if plot.shade_above is not None and plot.shade_above[0] < yb:
        text = pdf_text(plot.shade_above[1])
        canvas.rect(x0 + 2, y0 + h - 13, 3.9 * len(text) + 4, 11, fill=TINT)
        canvas.text(x0 + 4, y0 + h - 10, text, 7, True, RED)
    if plot.shade_right is not None and plot.shade_right[0] < xb:
        text = pdf_text(plot.shade_right[1])
        canvas.rect(x0 + w - 3.9 * len(text) - 6, y0 + h - 13, 3.9 * len(text) + 4, 11, fill=TINT)
        canvas.text(x0 + w - 3.9 * len(text) - 4, y0 + h - 10, text, 7, True, RED)
    # Legend inside the box, top right (or bottom right, clear of rising curves).
    ly = y0 + 6 + 11 * (len(plot.series) - 1) if plot.legend_at_bottom else y0 + h - 12
    for s in plot.series:
        lx = x0 + 6 if plot.legend_left else x0 + w - 132
        canvas.rect(lx - 2, ly - 3, 130, 11, fill=(1.0, 1.0, 1.0))
        canvas.rect(lx, ly + 1, 14, 2.4, fill=s.colour)
        canvas.text(lx + 18, ly, pdf_text(s.label), 7)
        ly -= 11


def _sweep(lo: float, hi: float, n: int = SAMPLES) -> list[float]:
    return [lo + (hi - lo) * k / (n - 1) for k in range(n)]


def _ceil_to(value: float, step: float) -> float:
    return math.ceil(value / step) * step


def _loading_plot(
    inputs: LiftChartInputs, axes: ChartAxes, box: tuple[float, float, float, float]
) -> Plot:
    limit = inputs.top_limit.value
    coldest = min(axes.ambient_temperatures) - CELSIUS_OFFSET
    warmest = max(axes.ambient_temperatures) - CELSIUS_OFFSET
    x_range = (
        min(AMBIENT_AXIS_C[0], 10.0 * math.floor(coldest / 10.0 - 1.0)),
        max(AMBIENT_AXIS_C[1], 10.0 * math.ceil(warmest / 10.0 + 1.0)),
    )
    xs = _sweep(*x_range)
    series = []
    lows, highs = [0.0], [0.0]
    for k, h in enumerate(axes.altitudes):
        pts = [(x, equilibrium_load(inputs, h, x + CELSIUS_OFFSET, limit).load) for x in xs]
        lows += [y for _, y in pts]
        highs += [y for _, y in pts]
        series.append(Series(f"{h:,.0f} m / {ft(h):,.0f} ft", pts, COLOURS[k % len(COLOURS)]))
    step = nice_step(max(highs) - min(lows), 8)
    yr = (min(0.0, math.floor(min(lows) / step) * step), _ceil_to(max(highs), step))
    return Plot(
        box,
        f"Maximum load at the top-temperature limit {c_f(limit - CELSIUS_OFFSET)}",
        "Ambient temperature at altitude (degC)",
        "Load (kg)",
        x_range,
        yr,
        series,
        hlines=[(0.0, "cannot lift its own mass below 0 kg", RED)] if yr[0] < 0 else [],
        x2=F_AXIS,
        y2=LB_AXIS,
    )


def _temperature_plot(
    inputs: LiftChartInputs,
    axes: ChartAxes,
    altitude: float,
    box: tuple[float, float, float, float],
    payload: float | None,
) -> Plot:
    limit = inputs.top_limit.value
    load_max = axes.loads[-1]
    xs = _sweep(0.0, load_max)
    series = []
    for k, t_amb in enumerate(axes.ambient_temperatures):
        pts = [
            (m, equilibrium_top_temperature(inputs, altitude, t_amb, m).top_temperature) for m in xs
        ]
        pts = [(m, t - CELSIUS_OFFSET) for m, t in pts]
        series.append(
            Series(f"ambient {c_f(t_amb - CELSIUS_OFFSET)}", pts, COLOURS[k % len(COLOURS)])
        )
    lo = min(axes.ambient_temperatures) - CELSIUS_OFFSET
    y_top = limit - CELSIUS_OFFSET + 40.0
    return Plot(
        box,
        f"Top temperature needed - pressure altitude {altitude:,.0f} m / {ft(altitude):,.0f} ft",
        "Load (kg)",
        "Top (degC)",
        (0.0, load_max),
        (lo, y_top),
        series,
        hlines=[(limit - CELSIUS_OFFSET, f"LIMIT {c_f(limit - CELSIUS_OFFSET)}", RED)],
        vlines=[] if payload is None else [(payload, f"design load {kg_lb(payload)}", MUTED)],
        shade_above=(limit - CELSIUS_OFFSET, "ABOVE TOP-TEMPERATURE LIMIT - NOT PERMITTED"),
        legend_at_bottom=True,
        x2=LB_AXIS,
        y2=F_AXIS,
    )


def _ceiling_plot(
    inputs: LiftChartInputs, axes: ChartAxes, box: tuple[float, float, float, float]
) -> Plot:
    limit = inputs.top_limit.value
    xs = _sweep(0.0, axes.loads[-1], 81)
    series = []
    for k, dt in enumerate(axes.isa_offsets):
        # The curve ends exactly where the balloon floats the load at sea level.
        end = equilibrium_load(inputs, 0.0, isa(0.0, dt).temperature, limit).load
        loads = sorted({*(m for m in xs if m < end), max(end, 0.0)})
        pts = [(m, equilibrium_altitude(inputs, dt, limit, m).altitude) for m in loads]
        if end >= 0.0:
            pts[-1] = (end, 0.0)
        series.append(
            Series(f"ISA {dt:+.0f} K / {1.8 * dt:+.0f} degF", pts, COLOURS[k % len(COLOURS)])
        )
    return Plot(
        box,
        f"Equilibrium altitude (ceiling) at the top-temperature limit "
        f"{c_f(limit - CELSIUS_OFFSET)}, from sea level",
        "Load (kg)",
        "Altitude (m)",
        (0.0, axes.loads[-1]),
        (0.0, 11000.0),
        series,
        x2=LB_AXIS,
        y2=FT_AXIS,
    )


def _gross_plot(
    inputs: LiftChartInputs,
    axes: ChartAxes,
    altitude: float,
    box: tuple[float, float, float, float],
    payload: float | None,
) -> Plot:
    """Gross lift vs the crown (top) temperature the pilot reads; the lift of each point
    uses the mean gas temperature that crown gives (:meth:`LiftChartInputs.mean_of`)."""
    limit_c = inputs.top_limit.value - CELSIUS_OFFSET
    x_range = (TOP_AXIS_START_C, 10.0 * math.ceil((limit_c + 10.0) / 10.0))
    # Each curve ends at the limit: a crown hotter than that is not permitted.
    xs = sorted({*(x for x in _sweep(*x_range) if x < limit_c), limit_c})
    series = []
    highs = [inputs.fixed_mass + (payload or 0.0)]
    for k, t_amb in enumerate(axes.ambient_temperatures):
        pts = [
            (
                x,
                lift_mass(
                    inputs.volume,
                    altitude,
                    t_amb,
                    inputs.mean_of(x + CELSIUS_OFFSET, t_amb),
                ),
            )
            for x in xs
        ]
        highs += [y for _, y in pts]
        series.append(
            Series(f"ambient {c_f(t_amb - CELSIUS_OFFSET)}", pts, COLOURS[k % len(COLOURS)])
        )
    step = nice_step(max(highs), 8)
    hlines = [
        (inputs.fixed_mass, f"envelope + rigging {kg_lb(inputs.fixed_mass)}", MUTED),
    ]
    if payload:
        total = inputs.fixed_mass + payload
        hlines.append((total, f"+ design load = {kg_lb(total)}", BLUE))
    return Plot(
        box,
        f"Gross lift vs crown temperature - pressure altitude "
        f"{altitude:,.0f} m / {ft(altitude):,.0f} ft",
        "Crown (top) temperature (degC)",
        "Gross lift (kg)",
        x_range,
        (0.0, _ceil_to(max(highs), step)),
        series,
        hlines=hlines,
        vlines=[(limit_c, f"limit {c_f(limit_c)}", RED)],
        shade_right=(limit_c, "CROWN ABOVE LIMIT"),
        legend_left=True,
        x2=F_AXIS,
        y2=LB_AXIS,
    )


def half_volume_height(dist: VolumeDistribution) -> float:
    """Height above the mouth below which half the gas volume lies, m."""
    import numpy as np

    cumulative = np.cumsum(dist.weights)
    return float(np.interp(0.5, cumulative, dist.heights))


def _profile_plot(
    inputs: LiftChartInputs, axes: ChartAxes, box: tuple[float, float, float, float]
) -> Plot | None:
    strat = inputs.stratification
    if strat is None:
        return None
    import numpy as np

    top = inputs.top_limit.value
    dist = strat.distribution
    heights = np.linspace(0.0, dist.crown_height, 41)
    series = []
    for k, t_amb in enumerate(axes.ambient_temperatures):
        t = strat.profile(top, t_amb, heights) - CELSIUS_OFFSET
        mean = inputs.mean_of(top, t_amb) - CELSIUS_OFFSET
        label = (
            f"ambient {c_f(t_amb - CELSIUS_OFFSET)}: mean {mean:.0f} degC "
            f"(top - {top - CELSIUS_OFFSET - mean:.0f} K)"
        )
        series.append(Series(label, list(zip(t, heights, strict=True)), COLOURS[k % 6]))
    lo = 10.0 * math.floor((min(axes.ambient_temperatures) - CELSIUS_OFFSET) / 10.0)
    half = half_volume_height(dist)
    return Plot(
        box,
        f"Gas temperature by height with the crown at its limit {c_f(top - CELSIUS_OFFSET)}",
        "Gas temperature (degC)",
        "Height above the mouth (m)",
        (lo, 10.0 * math.ceil((top - CELSIUS_OFFSET + 10.0) / 10.0)),
        (0.0, dist.crown_height),
        series,
        hlines=[(half, f"half the volume lies below {half:.1f} m / {ft(half):.0f} ft", MUTED)],
        legend_left=True,
        x2=F_AXIS,
        y2=FT_AXIS,
    )


def _pressure_plot(
    inputs: LiftChartInputs, axes: ChartAxes, box: tuple[float, float, float, float]
) -> Plot | None:
    strat = inputs.stratification
    if strat is None:
        return None
    import numpy as np

    top = inputs.top_limit.value
    t_amb = sorted(axes.ambient_temperatures)[len(axes.ambient_temperatures) // 2]
    altitude = axes.altitudes[0]
    pressure = isa(altitude).pressure
    dist = strat.distribution
    heights = np.linspace(0.0, dist.crown_height, 41)
    layered = strat.pressure_profile(top, t_amb, pressure, heights)
    mean = inputs.mean_of(top, t_amb)
    rho_amb, rho_mean = gas_density(pressure, t_amb), gas_density(pressure, mean)
    uniform = np.array([differential_pressure(float(h), 0.0, rho_amb, rho_mean) for h in heights])
    return Plot(
        box,
        f"Pressure difference by height, ambient {c_f(t_amb - CELSIUS_OFFSET)}, "
        f"{altitude:,.0f} m, crown at its limit",
        "Internal minus ambient pressure (Pa)",
        "Height above the mouth (m)",
        (0.0, _ceil_to(float(max(layered.max(), uniform.max())) * 1.05, 5.0)),
        (0.0, dist.crown_height),
        [
            Series("stratified (this profile)", list(zip(layered, heights, strict=True)), BLUE),
            Series(
                f"uniform at the same mean {c_f(mean - CELSIUS_OFFSET)}",
                list(zip(uniform, heights, strict=True)),
                MUTED,
                dash=(4.0, 3.0),
            ),
        ],
        legend_at_bottom=True,
        y2=FT_AXIS,
    )


#: Box of a plot drawn by its own renderer (the on-screen charts), unitless.
UNIT_BOX = (0.0, 0.0, 1.0, 1.0)


@dataclass(frozen=True)
class ChartSet:
    """Every chart of the lift-chart document, as plot data.

    Attributes
    ----------
    loading : Plot
        Maximum load at the top-temperature limit vs ambient temperature (page 1).
    temperatures : list of Plot
        Top temperature needed vs load, one per altitude (page 3).
    ceiling : Plot
        Equilibrium altitude vs load at the limit, one curve per ISA deviation (page 4).
    gross : list of Plot
        Gross lift vs crown temperature, one per altitude (page 2).
    stratification : list of Plot
        Gas temperature and pressure difference by height (page 3); empty with a fixed
        offset.
    """

    loading: Plot
    temperatures: list[Plot]
    ceiling: Plot
    gross: list[Plot]
    stratification: list[Plot] = field(default_factory=list)


def chart_plots(inputs: LiftChartInputs, axes: ChartAxes, payload: float | None = None) -> ChartSet:
    """The plot data of every lift chart, the same the PDF draws (units: kg, degC, m on
    the axes, with lb, degF and ft second scales).

    Parameters
    ----------
    inputs : LiftChartInputs
        Volume (m^3), fixed mass (kg), limit and offset (K).
    axes : ChartAxes
        The curves (:func:`chart_axes`).
    payload : float, optional
        Design load, kg, marked on the temperature charts.

    Returns
    -------
    ChartSet
        Plots in :data:`UNIT_BOX`; a renderer maps their ranges to its own area.
    """
    return ChartSet(
        _loading_plot(inputs, axes, UNIT_BOX),
        [_temperature_plot(inputs, axes, h, UNIT_BOX, payload) for h in axes.altitudes],
        _ceiling_plot(inputs, axes, UNIT_BOX),
        [_gross_plot(inputs, axes, h, UNIT_BOX, payload) for h in axes.altitudes],
        [
            plot
            for plot in (
                _profile_plot(inputs, axes, UNIT_BOX),
                _pressure_plot(inputs, axes, UNIT_BOX),
            )
            if plot is not None
        ],
    )


def ticks(lo: float, hi: float, count: int = 8) -> list[float]:
    """Round tick values (1-2-2.5-5 steps) from ``lo`` to ``hi``, about ``count`` of them;
    same unit as ``lo`` and ``hi``."""
    return _ticks(lo, hi, count)


def tick_label(value: float) -> str:
    """``1,000`` or ``2.5``: a tick value as printed on the charts."""
    return _label(value)


def input_lines(inputs: LiftChartInputs) -> list[str]:
    """The inputs of the chart with their units and source tags, one per line."""
    sources = ", ".join(sorted(set(inputs.fixed_mass_sources))) or "none recorded"
    return [
        f"Envelope volume: {inputs.volume:,.0f} m3 / {inputs.volume / M_PER_FT**3:,.0f} cu ft "
        f"({inputs.volume_note}).",
        f"Envelope + rigging mass: {inputs.fixed_mass:,.1f} kg / {lb(inputs.fixed_mass):,.0f} lb "
        f"(sources: {sources}). "
        "Load = everything else: basket, burners, fuel, occupants.",
        *limit_lines(inputs),
        *_mean_model_lines(inputs, short=True),
        "Equilibrium: V (rho_amb - rho_int) = envelope + rigging + load; dry air, ISA pressure "
        "at the pressure altitude, ambient temperature as given at that altitude; still "
        "air, no climb or descent. Ceiling: ISA temperature profile shifted by the ISA "
        "deviation.",
        "Humid air and combustion products are not modelled: on a humid day the real lift "
        "is slightly lower. Keep a margin: these are static equilibrium values.",
        SAFETY_NOTICE,
    ]


def limit_lines(inputs: LiftChartInputs) -> list[str]:
    """Where the crown temperature limit comes from, and a warning when it exceeds the
    fabrics' service temperature."""
    limit = inputs.top_limit
    fabric = inputs.fabric_limit
    if fabric is None:
        return [
            f"Top-temperature limit: {c_f(limit.value - CELSIUS_OFFSET)} "
            f"[{limit.source}] - {limit.reference}."
        ]
    out = [
        f"Top-temperature limit: {c_f(limit.value - CELSIUS_OFFSET)} set for this project "
        f"[{limit.source}] - {limit.reference}. The fabrics' service temperature is "
        f"{c_f(fabric.value - CELSIUS_OFFSET)} [{fabric.source}] - {fabric.reference}."
    ]
    if inputs.limit_above_fabric:
        out.append(limit_warning(inputs))
    return out


def limit_warning(inputs: LiftChartInputs) -> str:
    """The warning when the limit exceeds the fabrics' service temperature ("" if not)."""
    if not inputs.limit_above_fabric or inputs.fabric_limit is None:
        return ""
    excess = inputs.top_limit.value - inputs.fabric_limit.value
    return (
        f"WARNING: the limit is {excess:.0f} K above the fabrics' service temperature "
        f"{c_f(inputs.fabric_limit.value - CELSIUS_OFFSET)}: loads and ceilings at the limit "
        "are not conservative."
    )


def _mean_model_lines(inputs: LiftChartInputs, short: bool = False) -> list[str]:
    """How the mean gas temperature follows from the top, with this envelope's numbers."""
    off = inputs.top_to_mean
    strat = inputs.stratification
    if strat is None:
        return [
            f"Mean gas temperature = top - {off.value:.0f} K ({1.8 * off.value:.0f} degF), a "
            f"fixed offset [{off.source}: {off.reference}]."
        ]
    phi = strat.mouth_excess
    dist = strat.distribution
    limit = inputs.top_limit.value
    examples = []
    for t_c in (0.0, 15.0, 30.0):
        t_amb = t_c + CELSIUS_OFFSET
        eff = strat.effective_mean(limit, t_amb)
        floor = " (floor applies)" if strat.floor_applies(limit, t_amb) else ""
        examples.append(
            f"ambient {t_c:.0f} degC: profile offset {limit - eff:.1f} K, "
            f"used {strat.offset(limit, t_amb):.1f} K{floor}"
        )
    head = (
        "Mean gas temperature from the envelope's shape (level 1): the gas temperature is "
        "assumed to rise linearly from the mouth to the crown, the mouth "
        f"{100.0 * phi.value:.0f} % of the crown's rise above ambient [{phi.source}: "
        f"{phi.reference}]; lift uses its volume-weighted mean, 1/T_mean = (1/V) sum dV / T, "
        f"never less than {off.value:.0f} K below the top [{off.source}: {off.reference}]."
    )
    if short:
        return [head, "With the crown at its limit: " + "; ".join(examples) + "."]
    half = half_volume_height(dist)
    return [
        head,
        f"T(h) = T_amb + (T_top - T_amb) ({phi.value:.2f} + {1.0 - phi.value:.2f} h / H), "
        f"h above the mouth, crown height H = {dist.crown_height:.2f} m "
        f"({ft(dist.crown_height):.1f} ft). The volume by height comes from the design's "
        "profile (each segment sweeps a frustum), scaled to the lofted volume: half the gas "
        f"lies below {half:.2f} m ({100.0 * half / dist.crown_height:.0f} % of H).",
        "With the crown at its limit "
        + c_f(limit - CELSIUS_OFFSET)
        + ": "
        + "; ".join(examples)
        + ". When the floor applies, the profile is taken with a "
        "cooler mouth so that its mean meets the floor.",
        "The pressure difference consistent with the profile grows faster near the hot "
        "crown than a uniform envelope's (stratification chart); the structural solver "
        "still assumes a uniform temperature.",
    ]


#: Pascal per pound-force per square foot (exact from the lbf and ft definitions).
PA_PER_PSF = 4.4482216152605 / M_PER_FT**2


def theory_sections(
    inputs: LiftChartInputs, axes: ChartAxes | None = None
) -> list[tuple[str, list[str]]]:
    """How the lift charts are calculated, with the values this envelope's charts use.

    The single source of the theory shown in the application and on the last page of
    the PDF (the theory page of the documentation, ``docs/theory/lift-charts.md``,
    derives it). Plain text: ``rho`` for density, ``degC``/``degF``/``degR``.

    Parameters
    ----------
    inputs : LiftChartInputs
        Volume (m^3), fixed mass (kg), limit and offset (K).
    axes : ChartAxes, optional
        The chart grid; its altitudes get their ISA pressures listed.

    Returns
    -------
    list of (str, list of str)
        Headings and their paragraphs.
    """
    from envelopelab.atmosphere import G0, R_DRY_AIR

    r_si = R_DRY_AIR.value
    r_eng = r_si * KG_PER_LB / (4.4482216152605 * M_PER_FT) / 1.8
    limit = inputs.top_limit.value
    t15 = 15.0 + CELSIUS_OFFSET
    mean15 = inputs.mean_of(limit, t15)
    uniform = lift_mass(inputs.volume, 0.0, t15, limit)
    stratified = lift_mass(inputs.volume, 0.0, t15, mean15)
    altitudes = axes.altitudes if axes is not None else (0.0,)
    pressures = [
        f"{h:,.0f} m ({ft(h):,.0f} ft): p = {isa(h).pressure:,.0f} Pa "
        f"({isa(h).pressure / PA_PER_PSF:,.1f} lbf/ft2)"
        for h in altitudes
    ]
    return [
        (
            "1. Gross lift (Archimedes)",
            [
                "L = V (rho_amb - rho_int) g. The air the envelope displaces weighs "
                "V rho_amb g; the hot air inside weighs V rho_int g. L is the gross lift: "
                "everything the balloon can carry, its own envelope and rigging included.",
                "Both densities follow the ideal-gas law at the same static pressure p (the "
                "mouth is open, so the inside is at ambient pressure): rho = p / (R T), so "
                "L / g = (p V / R) (1/T_amb - 1/T_mean).",
                f"R = {r_si:.5f} J/(kg K) for dry air [datasheet, ISO 2533] = "
                f"{r_eng:.3f} ft lbf/(lb degR); g = {G0.value} m/s2. Temperatures are "
                "absolute: K = degC + 273.15, degR = degF + 459.67.",
            ],
        ),
        (
            "2. Equilibrium (what the load charts solve)",
            [
                "The balloon floats when L / g = envelope + rigging + load. Any three of "
                "top temperature, ambient temperature, altitude and load fix the fourth.",
                f"Envelope + rigging: {inputs.fixed_mass:,.1f} kg / "
                f"{lb(inputs.fixed_mass):,.0f} lb. Load: basket, burners, fuel, occupants.",
                "Load at a top temperature: load = L/g - envelope - rigging. Top "
                "temperature for a load: 1/T_mean = 1/T_amb - R (envelope + rigging + load) "
                "/ (p V); no temperature works when the mass exceeds V rho_amb. Ceiling: "
                "the lowest altitude, in the ISA shifted by the ISA deviation, where the "
                "spare lift turns negative.",
            ],
        ),
        (
            "3. Which temperature: mean vs top (crown)",
            [
                "Lift depends on the mean temperature of the gas in the whole envelope. "
                "Pilots read, and the fabric limit applies to, the crown (top), which is "
                "hotter.",
                *_mean_model_lines(inputs),
                "Spreadsheets that enter one 'envelope temperature' treat the envelope as "
                "uniform: that temperature is the mean. Entering the crown reading there "
                "overstates lift. For this envelope at sea level, 15 degC: with the crown "
                f"at its limit {c_f(limit - CELSIUS_OFFSET)} (mean "
                f"{mean15 - CELSIUS_OFFSET:.0f} degC) the gross lift is "
                f"{kg_lb(stratified)}; a uniform envelope at that temperature would "
                f"lift {kg_lb(uniform)} ({100.0 * (uniform / stratified - 1.0):+.0f} %).",
                "The gross-lift chart is drawn against the crown temperature, the one the "
                "pilot reads; each point's lift uses the mean that crown temperature gives. "
                "With a fixed offset of 0 the crown is the mean and the chart is the "
                "uniform-temperature spreadsheet's.",
            ],
        ),
        (
            "4. Atmosphere",
            [
                "Pressure: International Standard Atmosphere (ISO 2533) at the pressure "
                "altitude, p = 101,325 Pa (1 - 0.0065 h / 288.15)^5.25588 below 11 km "
                "(h in m; 0.0065 K/m = 0.0019812 degF/ft).",
                *pressures,
                "Ambient temperature: as given at that altitude (not derived from the "
                "lapse rate), except for the ceiling chart, which follows the ISA "
                "temperature shifted by the ISA deviation.",
            ],
        ),
        (
            "5. This envelope",
            [
                f"Volume V = {inputs.volume:,.0f} m3 / {inputs.volume / M_PER_FT**3:,.0f} "
                f"cu ft: {inputs.volume_note}.",
                *limit_lines(inputs),
            ],
        ),
        (
            "6. Assumptions and limits",
            [
                "Static equilibrium in still air (no climb, descent, wind or drag); dry "
                "air inside and out (humid air and combustion products, not modelled, "
                "lower the real lift slightly); uniform densities over the envelope "
                "height (< 0.4 % over 30 m); the top-to-mean relation above (assumed); the volume "
                "does not change with temperature. Valid from -5,000 m to 11,000 m.",
                "Gross lift is not payload: subtract the envelope, rigging, basket, "
                "burners, fuel and people. Keep a margin: these are equilibrium values, "
                "not a certified loading chart.",
            ],
        ),
    ]


def write_lift_chart_pdf(
    inputs: LiftChartInputs,
    axes: ChartAxes,
    path: str | Path,
    title: str,
    payload: float | None = None,
) -> Path:
    """Write the lift-chart PDF (module docstring: pages); returns the path.

    Parameters
    ----------
    inputs : LiftChartInputs
        Volume (m^3), fixed mass (kg), temperature limit and offset (K).
    axes : ChartAxes
        Grid of the charts.
    path : str or Path
        Output file.
    title : str
        Page title (design name).
    payload : float, optional
        Design load, kg, marked on the temperature charts.
    """
    from envelopelab.export.shop import A4_LANDSCAPE, Pages

    doc = Pages(A4_LANDSCAPE)
    canvas = doc.canvas
    width, height = A4_LANDSCAPE
    margin = 40.0

    def header(subtitle: str) -> None:
        canvas.text(margin, height - margin, pdf_text(f"{title.upper()} - LIFT CHART"), 14, True)
        canvas.text(margin, height - margin - 16, pdf_text(subtitle), 8, color=MUTED)

    header("Static equilibrium: the load the balloon floats, and the top temperature it needs.")
    draw_plot(canvas, _loading_plot(inputs, axes, (margin + 40, 270, 470, 220)))
    y = 225.0
    for line in input_lines(inputs):
        for text in _wrap(pdf_text(line), 150):
            colour = MUTED if line == SAFETY_NOTICE else (0.0, 0.0, 0.0)
            if line.startswith("WARNING"):
                colour = RED
            canvas.text(margin, y, text, 7.5, colour == RED, colour)
            y -= 10
        y -= 2
    legend_x = margin + 560
    lines = [
        "How to read it:",
        "Each curve is one pressure altitude.",
        "Go up from the ambient temperature",
        "at that altitude to the curve: that",
        "load floats with the crown at the",
        "limit. More load cannot float",
        "without exceeding the limit.",
        "",
        "English units: lb on the right",
        "scale, degF on the top scale.",
    ]
    ly = 500.0
    for text in lines:
        canvas.text(legend_x + 10, ly, text, 8, text.endswith(":"))
        ly -= 11

    canvas.new_page()
    header(
        "Gross lift (everything the balloon can carry, envelope included) vs the crown "
        "temperature the pilot reads. Where a curve crosses a dashed line the balloon floats."
    )
    cols, rows = 2, 2
    pw, ph = 330.0, 185.0
    for k, altitude in enumerate(axes.altitudes[: cols * rows]):
        c, r = k % cols, k // cols
        box = (margin + 50 + c * (pw + 60), height - 285 - r * (ph + 70), pw, ph)
        draw_plot(canvas, _gross_plot(inputs, axes, altitude, box, payload))

    if inputs.stratification is not None:
        canvas.new_page()
        header(
            "Assumed temperature profile from the envelope's shape (level 1): linear from "
            "mouth to crown; lift uses its volume-weighted mean. Not measured."
        )
        profile = _profile_plot(inputs, axes, (margin + 50, 120, 330, 360))
        pressure = _pressure_plot(inputs, axes, (margin + 440, 120, 320, 360))
        for plot in (profile, pressure):
            if plot is not None:
                draw_plot(canvas, plot)

    canvas.new_page()
    header("Top temperature that floats a load. Above the red line the fabric limit is exceeded.")
    cols, rows = 2, 2
    pw, ph = 330.0, 185.0
    for k, altitude in enumerate(axes.altitudes[: cols * rows]):
        c, r = k % cols, k // cols
        box = (margin + 50 + c * (pw + 60), height - 285 - r * (ph + 70), pw, ph)
        draw_plot(canvas, _temperature_plot(inputs, axes, altitude, box, payload))

    canvas.new_page()
    header(
        "Highest altitude the balloon floats a load with the crown at the limit "
        "(lines end where it cannot lift the load at sea level)."
    )
    draw_plot(canvas, _ceiling_plot(inputs, axes, (margin + 60, 90, 700, 400)))

    canvas.new_page()
    header("How these charts are calculated.")
    y = height - margin - 40
    for heading, lines in theory_sections(inputs, axes):
        if y < margin + 40:
            canvas.new_page()
            header("How these charts are calculated (continued).")
            y = height - margin - 40
        canvas.text(margin, y, pdf_text(heading), 9, True)
        y -= 12
        for line in lines:
            for text in _wrap(pdf_text(line), 165):
                if y < margin:
                    canvas.new_page()
                    header("How these charts are calculated (continued).")
                    y = height - margin - 40
                canvas.text(margin + 8, y, text, 7.5)
                y -= 9.5
        y -= 6
    return doc.save(path)


def _wrap(text: str, width: int) -> list[str]:
    words, line, out = text.split(), "", []
    for word in words:
        if line and len(line) + len(word) + 1 > width:
            out.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    out.append(line)
    return out


@dataclass(frozen=True)
class DesignCharts:
    """The lift charts of a design: their inputs, grid and plot data."""

    inputs: LiftChartInputs
    axes: ChartAxes
    plots: ChartSet


def design_charts(
    design: DesignDocument,
    outputs: GoreOutputs | None,
    fabrics: Any = None,
    settings: LiftChartSettings | None = None,
) -> DesignCharts | None:
    """The lift charts of a design with the project's settings (None when the envelope
    mass is not estimated).

    Parameters
    ----------
    design : DesignDocument
        Gore design (payload kg, fabric zones).
    outputs : GoreOutputs or None
        Its live outputs (volume m^3, envelope and rigging mass kg).
    fabrics : FabricLibraryRepository or FabricCatalog, optional
        Fabric library for the top-temperature limit.
    settings : LiftChartSettings, optional
        Curves (SI) and the top-to-mean offset (K, tagged); defaults when None.

    Returns
    -------
    DesignCharts or None
    """
    from envelopelab.project.lift_chart_settings import LiftChartSettings

    s = settings if settings is not None else LiftChartSettings()
    offset = PhysicalConstant(
        s.top_to_mean.value, "K", s.top_to_mean.source, s.top_to_mean.note or "lift-chart settings"
    )
    excess = PhysicalConstant(
        s.mouth_excess.value,
        "-",
        s.mouth_excess.source,
        s.mouth_excess.note or "lift-chart settings",
    )
    limit = (
        None
        if s.top_limit is None
        else PhysicalConstant(
            s.top_limit.value, "K", s.top_limit.source, s.top_limit.note or "lift-chart settings"
        )
    )
    inputs = chart_inputs(
        design, outputs, fabrics, offset, s.mean_model == "envelope_shape", excess, limit
    )
    if inputs is None:
        return None
    axes = chart_axes(inputs, s)
    return DesignCharts(inputs, axes, chart_plots(inputs, axes, design.operating.payload_mass))


def write_lift_chart(
    ctx: PackContext,
    pdf_path: Path,
    csv_path: Path,
    fabrics: Any = None,
    settings: LiftChartSettings | None = None,
) -> tuple[Path, Path]:
    """Write the build pack's lift chart PDF and CSV (:func:`write_design_lift_chart` of
    the pack's design and outputs)."""
    write_design_lift_chart(ctx.design, ctx.outputs, pdf_path, csv_path, fabrics, settings)
    return pdf_path, csv_path


def write_design_lift_chart(
    design: DesignDocument,
    outputs: GoreOutputs | None,
    pdf_path: Path,
    csv_path: Path | None = None,
    fabrics: Any = None,
    settings: LiftChartSettings | None = None,
) -> tuple[Path, Path | None]:
    """Write the lift chart PDF (and CSV) of a design.

    When the envelope mass is not estimated both files say so instead of charting.

    Parameters
    ----------
    design : DesignDocument
        Gore design (name, payload, fabric zones).
    outputs : GoreOutputs or None
        Its live outputs (volume m^3, envelope and rigging mass kg).
    pdf_path : Path
        PDF file.
    csv_path : Path, optional
        CSV file (none written when None, e.g. for a preview).
    fabrics : FabricLibraryRepository or FabricCatalog, optional
        Fabric library for the top-temperature limit.
    settings : LiftChartSettings, optional
        The project's curves and top-to-mean offset (defaults when None).

    Returns
    -------
    (Path, Path or None)
        The PDF and CSV paths.
    """
    name = design.meta.name or "design"
    charts = design_charts(design, outputs, fabrics, settings)
    if charts is None:
        from envelopelab.export.shop import A4_LANDSCAPE, Pages

        doc = Pages(A4_LANDSCAPE)
        doc.title(f'"{name.upper()}" - LIFT CHART')
        doc.lines(
            [
                "NOT PRODUCED: the envelope mass is not estimated (see the design findings).",
                SAFETY_NOTICE,
            ],
            doc.margin,
            doc.size[0] - 2 * doc.margin,
        )
        doc.save(pdf_path)
        if csv_path is not None:
            with csv_path.open("w", newline="", encoding="utf-8") as handle:
                csv.writer(handle).writerow(CSV_COLUMNS)
        return pdf_path, csv_path
    inputs, axes = charts.inputs, charts.axes
    write_lift_chart_pdf(inputs, axes, pdf_path, name, design.operating.payload_mass)
    if csv_path is not None:
        write_lift_chart_csv(build_chart(inputs, axes), csv_path)
    return pdf_path, csv_path
