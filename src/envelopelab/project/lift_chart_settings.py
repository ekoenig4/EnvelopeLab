"""Lift-chart settings of a project: which curves the build-pack lift charts draw (ADR-0059).

Stored in the project's design state (``state.lift_chart``, project format 9) in SI: m for
altitudes, K for temperatures and ISA deviations, kg for loads. The application converts
from the units the builder types (metric or English) at the dialog boundary.

The settings choose *where* the equilibrium is evaluated (:mod:`envelopelab.lift_chart`).
The only one that changes a result is the top-to-mean temperature offset, so it is a
:class:`~envelopelab.design.model.TaggedValue` with its source tag (``assumed`` until the
builder enters a measured value).

Defaults reproduce the charts written before the settings existed, and a project whose
settings are the defaults writes no ``lift_chart`` key, so its file and fingerprints are
unchanged.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from envelopelab.atmosphere import CELSIUS_OFFSET, ISA_MIN_ALTITUDE
from envelopelab.design.model import SourceTagName, TaggedValue
from envelopelab.lift_chart import DEFAULT_TOP_TO_MEAN, MAX_SEARCH_ALTITUDE

#: Most curves of one kind (one colour each; the temperature page has one panel per
#: altitude, laid out 2 x 2).
MAX_ALTITUDES = 4
MAX_CURVES = 6
#: Ambient temperatures a chart may use, K (-50 degC to 60 degC).
AMBIENT_RANGE = (223.15, 333.15)
#: ISA deviations a chart may use, K.
ISA_OFFSET_RANGE = (-50.0, 50.0)
#: Lowest top temperature tabulated may lie between, K (0 degC to 200 degC).
TOP_RANGE = (273.15, 473.15)
#: Top-to-mean offset range, K.
OFFSET_RANGE = (0.0, 100.0)


MeanModel = Literal["envelope_shape", "fixed_offset"]


def _default_excess() -> TaggedValue:
    from envelopelab.stratification import DEFAULT_MOUTH_EXCESS

    return TaggedValue(
        value=DEFAULT_MOUTH_EXCESS.value,
        source=DEFAULT_MOUTH_EXCESS.source,
        note=DEFAULT_MOUTH_EXCESS.reference,
    )


def _default_offset() -> TaggedValue:
    return TaggedValue(
        value=DEFAULT_TOP_TO_MEAN.value,
        source=DEFAULT_TOP_TO_MEAN.source,
        note=DEFAULT_TOP_TO_MEAN.reference,
    )


def _sorted_unique(values: list[float], what: str, count: int) -> list[float]:
    if not values:
        raise ValueError(f"{what}: give at least one value")
    out = sorted(set(values))
    if len(out) != len(values):
        raise ValueError(f"{what}: values must differ")
    if len(out) > count:
        raise ValueError(f"{what}: at most {count} values")
    return out


class LiftChartSettings(BaseModel):
    """What the lift charts draw.

    Attributes
    ----------
    altitudes : list of float
        Pressure altitudes of the curves (loading chart) and panels (temperature page),
        m; 1 to 4 values from -5 000 m to 11 000 m.
    ambient_temperatures : list of float
        Ambient temperatures of the temperature-page curves, K; 1 to 6 values from
        -50 degC to 60 degC.
    isa_offsets : list of float
        ISA deviations of the ceiling curves, K; 1 to 6 values from -50 K to 50 K.
    max_load : float or None
        Load axis end, kg (> 0); None picks the most the balloon lifts.
    lowest_top_temperature : float
        Lowest top temperature tabulated in the CSV, K (0 degC to 200 degC).
    top_to_mean : TaggedValue
        Top minus mean internal gas temperature, K (0 to 100), with its source tag: the
        offset with ``fixed_offset``, its floor with ``envelope_shape``.
    mean_model : {"envelope_shape", "fixed_offset"}
        How the mean gas temperature follows from the crown temperature:
        ``envelope_shape`` (default, ADR-0060) from the envelope's shape and an assumed
        linear temperature profile (:mod:`envelopelab.stratification`), never less than
        ``top_to_mean`` below the top; ``fixed_offset`` exactly ``top_to_mean`` below.
    mouth_excess : TaggedValue
        Temperature rise above ambient at the mouth as a fraction of the rise at the
        crown, dimensionless (0 to 1), with its source tag (``envelope_shape`` only).
    """

    model_config = ConfigDict(extra="forbid")

    altitudes: list[float] = Field(default_factory=lambda: [0.0, 1000.0, 2000.0, 3000.0])
    ambient_temperatures: list[float] = Field(
        default_factory=lambda: [t + CELSIUS_OFFSET for t in (-10.0, 0.0, 10.0, 20.0, 30.0)]
    )
    isa_offsets: list[float] = Field(default_factory=lambda: [-15.0, 0.0, 15.0, 30.0])
    max_load: float | None = None
    lowest_top_temperature: float = 70.0 + CELSIUS_OFFSET
    top_to_mean: TaggedValue = Field(default_factory=_default_offset)
    mean_model: MeanModel = "envelope_shape"
    mouth_excess: TaggedValue = Field(default_factory=_default_excess)

    @field_validator("altitudes")
    @classmethod
    def _altitudes(cls, values: list[float]) -> list[float]:
        out = _sorted_unique(values, "altitudes", MAX_ALTITUDES)
        if out[0] < ISA_MIN_ALTITUDE or out[-1] > MAX_SEARCH_ALTITUDE:
            raise ValueError(
                f"altitudes must lie between {ISA_MIN_ALTITUDE:.0f} m and "
                f"{MAX_SEARCH_ALTITUDE:.0f} m"
            )
        return out

    @field_validator("ambient_temperatures")
    @classmethod
    def _ambients(cls, values: list[float]) -> list[float]:
        out = _sorted_unique(values, "ambient temperatures", MAX_CURVES)
        lo, hi = AMBIENT_RANGE
        if out[0] < lo or out[-1] > hi:
            raise ValueError(
                f"ambient temperatures must lie between {lo - CELSIUS_OFFSET:.0f} degC and "
                f"{hi - CELSIUS_OFFSET:.0f} degC"
            )
        return out

    @field_validator("isa_offsets")
    @classmethod
    def _offsets(cls, values: list[float]) -> list[float]:
        out = _sorted_unique(values, "ISA deviations", MAX_CURVES)
        lo, hi = ISA_OFFSET_RANGE
        if out[0] < lo or out[-1] > hi:
            raise ValueError(f"ISA deviations must lie between {lo:.0f} K and {hi:.0f} K")
        return out

    @field_validator("max_load")
    @classmethod
    def _max_load(cls, value: float | None) -> float | None:
        if value is not None and not value > 0.0:
            raise ValueError("the load axis must end above 0 kg")
        return value

    @field_validator("lowest_top_temperature")
    @classmethod
    def _lowest_top(cls, value: float) -> float:
        lo, hi = TOP_RANGE
        if not lo <= value <= hi:
            raise ValueError(
                f"lowest top temperature must lie between {lo - CELSIUS_OFFSET:.0f} degC "
                f"and {hi - CELSIUS_OFFSET:.0f} degC"
            )
        return value

    @model_validator(mode="after")
    def _offset_range(self) -> LiftChartSettings:
        lo, hi = OFFSET_RANGE
        if not lo <= self.top_to_mean.value <= hi:
            raise ValueError(
                f"top-to-mean temperature offset must lie between {lo:.0f} K and {hi:.0f} K"
            )
        if not 0.0 <= self.mouth_excess.value <= 1.0:
            raise ValueError("mouth temperature rise must lie between 0 % and 100 %")
        return self

    def is_default(self) -> bool:
        """Whether every setting is its default (then the project file omits them)."""
        return self == LiftChartSettings()

    def to_data(self) -> dict[str, Any]:
        """JSON data; empty for the defaults."""
        return {} if self.is_default() else self.model_dump(mode="json")


# -- entry in the builder's units (the dialog boundary) -------------------------------------

#: A number written with thousands separators, e.g. ``-10,000.5``.
_THOUSANDS = re.compile(r"[-+]?[1-9]\d{0,2}(,\d{3})+(\.\d*)?")
UnitSystem = Literal["metric", "english"]
#: Exact unit definitions (international foot and pound, 1959; NIST SP 811).
M_PER_FT = 0.3048
KG_PER_LB = 0.45359237
#: Unit labels of each entry, per unit system.
UNIT_LABELS: dict[str, dict[str, str]] = {
    "metric": {"altitude": "m", "temperature": "°C", "difference": "K", "mass": "kg"},
    "english": {"altitude": "ft", "temperature": "°F", "difference": "°F", "mass": "lb"},
}


@dataclass(frozen=True)
class DisplayedSettings:
    """Lift-chart settings in the builder's units (``units``).

    Attributes
    ----------
    units : {"metric", "english"}
        Unit system of every value below.
    altitudes : list of float
        m or ft.
    ambient_temperatures : list of float
        degC or degF.
    isa_offsets : list of float
        K or degF (temperature differences).
    max_load : float or None
        kg or lb; None: automatic.
    lowest_top_temperature : float
        degC or degF.
    top_to_mean : float
        K or degF (a temperature difference).
    source : {"datasheet", "measured", "assumed"}
        Source tag of ``top_to_mean``.
    note : str
        Reference of ``top_to_mean``.
    mean_model : {"envelope_shape", "fixed_offset"}
        See :class:`LiftChartSettings`.
    mouth_excess : float
        Mouth temperature rise, % of the crown's rise above ambient.
    mouth_source : {"datasheet", "measured", "assumed"}
        Source tag of ``mouth_excess``.
    mouth_note : str
        Reference of ``mouth_excess``.
    """

    units: UnitSystem
    altitudes: list[float]
    ambient_temperatures: list[float]
    isa_offsets: list[float]
    max_load: float | None
    lowest_top_temperature: float
    top_to_mean: float
    source: SourceTagName
    note: str
    mean_model: MeanModel = "envelope_shape"
    mouth_excess: float = 50.0
    mouth_source: SourceTagName = "assumed"
    mouth_note: str = ""


def _temp_out(kelvin: float, units: UnitSystem) -> float:
    celsius = kelvin - CELSIUS_OFFSET
    return celsius if units == "metric" else celsius * 1.8 + 32.0


def _temp_in(value: float, units: UnitSystem) -> float:
    celsius = value if units == "metric" else (value - 32.0) / 1.8
    return celsius + CELSIUS_OFFSET


def _diff_out(kelvin: float, units: UnitSystem) -> float:
    return kelvin if units == "metric" else kelvin * 1.8


def _diff_in(value: float, units: UnitSystem) -> float:
    return value if units == "metric" else value / 1.8


def displayed(settings: LiftChartSettings, units: UnitSystem) -> DisplayedSettings:
    """``settings`` (SI) in the builder's units.

    Parameters
    ----------
    settings : LiftChartSettings
        SI: m, K, kg.
    units : {"metric", "english"}
        metric: m, degC, K, kg; english: ft, degF, degF, lb.

    Returns
    -------
    DisplayedSettings
    """
    length = 1.0 if units == "metric" else 1.0 / M_PER_FT
    mass = 1.0 if units == "metric" else 1.0 / KG_PER_LB
    return DisplayedSettings(
        units=units,
        altitudes=[h * length for h in settings.altitudes],
        ambient_temperatures=[_temp_out(t, units) for t in settings.ambient_temperatures],
        isa_offsets=[_diff_out(d, units) for d in settings.isa_offsets],
        max_load=None if settings.max_load is None else settings.max_load * mass,
        lowest_top_temperature=_temp_out(settings.lowest_top_temperature, units),
        top_to_mean=_diff_out(settings.top_to_mean.value, units),
        source=settings.top_to_mean.source,
        note=settings.top_to_mean.note,
        mean_model=settings.mean_model,
        mouth_excess=100.0 * settings.mouth_excess.value,
        mouth_source=settings.mouth_excess.source,
        mouth_note=settings.mouth_excess.note,
    )


def from_displayed(values: DisplayedSettings) -> LiftChartSettings:
    """SI settings from values in the builder's units (inverse of :func:`displayed`).

    Raises
    ------
    pydantic.ValidationError
        When a value is out of range (the message names it and the range in SI).
    """
    units = values.units
    length = 1.0 if units == "metric" else M_PER_FT
    mass = 1.0 if units == "metric" else KG_PER_LB
    return LiftChartSettings(
        altitudes=[h * length for h in values.altitudes],
        ambient_temperatures=[_temp_in(t, units) for t in values.ambient_temperatures],
        isa_offsets=[_diff_in(d, units) for d in values.isa_offsets],
        max_load=None if values.max_load is None else values.max_load * mass,
        lowest_top_temperature=_temp_in(values.lowest_top_temperature, units),
        top_to_mean=TaggedValue(
            value=_diff_in(values.top_to_mean, units), source=values.source, note=values.note
        ),
        mean_model=values.mean_model,
        mouth_excess=TaggedValue(
            value=values.mouth_excess / 100.0, source=values.mouth_source, note=values.mouth_note
        ),
    )


def parse_numbers(text: str, what: str) -> list[float]:
    """Numbers typed as a list, separated by commas, semicolons or spaces.

    A comma between digit groups of three is a thousands separator, so
    ``"0, 1,000, 10,000"``, ``"0; 1000; 10000"`` and ``"0 1000 10000"`` all read as
    0, 1000 and 10000; ``"0,500,1000"`` reads as 0, 500 and 1000.

    Raises
    ------
    ValueError
        Naming ``what`` and the text that is not a number.
    """
    out: list[float] = []
    for token in text.replace(";", " ").split():
        token = token.strip(",")
        if not token:
            continue
        parts = [token.replace(",", "")] if _THOUSANDS.fullmatch(token) else token.split(",")
        for part in (q for q in parts if q):
            try:
                value = float(part)
            except ValueError:
                raise ValueError(f"{what}: {part!r} is not a number") from None
            if not math.isfinite(value):
                raise ValueError(f"{what}: {part!r} is not a number")
            out.append(value)
    if not out:
        raise ValueError(f"{what}: give at least one value")
    return out


def format_numbers(values: list[float]) -> str:
    """``"0, 1000, 2000"``: rounded to 0.1, without trailing zeros."""
    return ", ".join(f"{round(v, 1):g}" for v in values)


def error_text(exc: Exception) -> str:
    """One line per problem of a refused entry (pydantic or ValueError), for the dialog."""
    errors = getattr(exc, "errors", None)
    if callable(errors):
        lines = []
        for err in errors():
            msg = str(err.get("msg", ""))
            lines.append(msg.removeprefix("Value error, "))
        return "\n".join(lines)
    return str(exc)
