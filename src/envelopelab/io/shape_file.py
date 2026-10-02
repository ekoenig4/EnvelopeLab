"""Shape files (``envelopelab.shape`` v1): a shape family and the values that fix a design.

A shape file is YAML (format: ``docs/formats/shape-file.md``). Lengths and volumes are
written with their unit (``92000 ft^3``, ``2 in``, ``6 m``) and converted to SI here, at
the input boundary; stations are bare fractions of the gore length or station names.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from envelopelab.project.shape_family import (
    QUANTITIES,
    VARIABLES,
    Dimension,
    NormalizedShape,
    ShapeParameters,
    ShapeSolution,
    solve_shape,
)

FORMAT = "envelopelab.shape"
FORMAT_VERSION = 1
SOURCE_TAGS = ("datasheet", "measured", "assumed")

#: Metres per unit (exact by definition of the inch, 0.0254 m).
LENGTH_UNITS: dict[str, float] = {
    "m": 1.0,
    "cm": 0.01,
    "mm": 0.001,
    "ft": 0.3048,
    "in": 0.0254,
}
#: Cubic metres per unit.
VOLUME_UNITS: dict[str, float] = {
    "m^3": 1.0,
    "m3": 1.0,
    "ft^3": 0.3048**3,
    "ft3": 0.3048**3,
    "cu ft": 0.3048**3,
}
UNITS: dict[Dimension, dict[str, float]] = {
    "length": LENGTH_UNITS,
    "volume": VOLUME_UNITS,
    "fraction": {"": 1.0},
}
_QUANTITY = re.compile(r"^\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)\s*(.*?)\s*$")


class ShapeFileError(ValueError):
    """A shape file is invalid (the message names the key)."""


def parse_quantity(value: object, dimension: Dimension, key: str = "value") -> float:
    """Convert ``"92000 ft^3"``, ``"2 in"`` or a bare fraction to SI.

    Parameters
    ----------
    value : str or float
        Number with unit (lengths, volumes) or bare number (fractions).
    dimension : {"length", "volume", "fraction"}
        Expected dimension.
    key : str
        Name used in error messages.

    Returns
    -------
    float
        m, m^3 or dimensionless.
    """
    if isinstance(value, bool):
        raise ShapeFileError(f"{key}: expected a number, got {value!r}")
    if isinstance(value, int | float):
        if dimension != "fraction":
            raise ShapeFileError(f"{key}: give a unit, e.g. '{value} m' ({dimension})")
        return float(value)
    match = _QUANTITY.match(str(value))
    if match is None:
        raise ShapeFileError(f"{key}: cannot read {value!r} as a number with a unit")
    number, unit = float(match.group(1)), match.group(2)
    factors = UNITS[dimension]
    if unit not in factors:
        known = ", ".join(u for u in factors if u) or "none (a bare number)"
        raise ShapeFileError(f"{key}: unit {unit!r} is not a {dimension} unit ({known})")
    return number * factors[unit]


def format_quantity(value: float, unit: str, digits: int = 6) -> str:
    """SI value as ``"<number> <unit>"`` in one of :data:`UNITS`."""
    for factors in UNITS.values():
        if unit in factors:
            return f"{value / factors[unit]:.{digits}g} {unit}".strip()
    raise ValueError(f"unknown unit {unit!r}")


@dataclass(frozen=True)
class ShapeFile:
    """A loaded shape file (SI).

    Attributes
    ----------
    path : Path
        File the shape was read from.
    name, description : str
        Design name and description.
    shape : NormalizedShape
        Shape family.
    hold : dict of str to float
        Held values that fix the file's design (m, m^3 or fractions of L).
    gore_count : int
        Gores N.
    seam_allowance : float
        Cut allowance per gore edge, m.
    source_file, reference : str
        Where the design comes from.
    published : dict
        The file's ``published`` block as written (regression data, never an input).
    """

    path: Path
    name: str
    description: str
    shape: NormalizedShape
    hold: dict[str, float]
    gore_count: int
    seam_allowance: float
    source_file: str = ""
    reference: str = ""
    published: dict[str, Any] = field(default_factory=dict)

    def start(self) -> ShapeParameters:
        """Starting design for :meth:`solve`: held variables, else named or typical ones.

        The gore length starts from the held nominal volume when there is one, else 20 m;
        the cut stations from the ``mouth`` and ``vent`` stations, else 0.15 and 0.9.
        """
        named = self.shape.stations
        if "gore_length" in self.hold:
            length = self.hold["gore_length"]
        elif "nominal_volume" in self.hold:
            length = (self.hold["nominal_volume"] / self.shape.volume_coefficient) ** (1 / 3)
        else:
            length = 20.0
        return ShapeParameters(
            gore_length=length,
            mouth_station=self.hold.get("mouth_station", named.get("mouth", 0.15)),
            top_station=self.hold.get("top_station", named.get("vent", 0.9)),
            gore_count=self.gore_count,
            seam_allowance=self.seam_allowance,
        )

    def solve(self, hold: dict[str, float] | None = None) -> ShapeSolution:
        """Solve the file's design, or a variant holding other values (SI)."""
        return solve_shape(self.shape, self.start(), self.hold if hold is None else hold)


def _require(raw: dict[str, Any], key: str, kind: type, where: str = "") -> Any:
    if key not in raw:
        raise ShapeFileError(f"missing key {where}{key}")
    value = raw[key]
    if not isinstance(value, kind):
        raise ShapeFileError(f"{where}{key}: expected {kind.__name__}")
    return value


def _hold_value(shape: NormalizedShape, name: str, value: object) -> float:
    if name not in QUANTITIES:
        raise ShapeFileError(f"design.hold: unknown quantity {name!r}")
    if name in VARIABLES[1:] and isinstance(value, str):
        if value in shape.stations:
            return shape.resolve_station(value)
        try:
            return float(value)
        except ValueError:
            named = ", ".join(shape.stations) or "none"
            raise ShapeFileError(
                f"design.hold.{name}: unknown station {value!r} (named stations: {named})"
            ) from None
    return parse_quantity(value, QUANTITIES[name].dimension, f"design.hold.{name}")


def parse_shape_file(raw: object, path: Path) -> ShapeFile:
    """Validate a parsed shape-file mapping and convert it to SI.

    Raises
    ------
    ShapeFileError
        For a wrong format, missing keys, unknown units or an invalid profile.
    """
    if not isinstance(raw, dict):
        raise ShapeFileError("a shape file is a YAML mapping")
    if raw.get("format") != FORMAT:
        raise ShapeFileError(f"format must be {FORMAT!r}")
    if raw.get("format_version") != FORMAT_VERSION:
        raise ShapeFileError(f"unsupported format_version {raw.get('format_version')!r}")
    profile = _require(raw, "profile", dict)
    source = str(profile.get("source", "assumed"))
    if source not in SOURCE_TAGS:
        raise ShapeFileError(f"profile.source must be one of {', '.join(SOURCE_TAGS)}")
    table = _require(profile, "stations", list, "profile.")
    try:
        s = [float(p[0]) for p in table]
        r = [float(p[1]) for p in table]
        if any(len(p) != 2 for p in table):
            raise TypeError
    except (TypeError, ValueError, IndexError) as exc:
        raise ShapeFileError("profile.stations: each entry is [s, r]") from exc
    stations = {str(k): float(v) for k, v in (raw.get("stations") or {}).items()}
    try:
        shape = NormalizedShape(s=s, r=r, stations=stations, source=source)  # type: ignore[arg-type]
    except ValueError as exc:
        raise ShapeFileError(f"profile: {exc}") from exc
    design = _require(raw, "design", dict)
    hold_raw = _require(design, "hold", dict, "design.")
    hold = {str(k): _hold_value(shape, str(k), v) for k, v in hold_raw.items()}
    gore_count = _require(design, "gore_count", int, "design.")
    allowance = parse_quantity(
        design.get("seam_allowance", "0 m"), "length", "design.seam_allowance"
    )
    src = raw.get("source") or {}
    return ShapeFile(
        path=path,
        name=str(raw.get("name", path.stem)),
        description=str(raw.get("description", "")),
        shape=shape,
        hold=hold,
        gore_count=gore_count,
        seam_allowance=allowance,
        source_file=str(src.get("file", "")),
        reference=str(src.get("reference", "")),
        published=dict(raw.get("published") or {}),
    )


def load_shape_file(path: str | Path) -> ShapeFile:
    """Read a shape file (``*.yaml``).

    Parameters
    ----------
    path : str or Path
        File path.

    Returns
    -------
    ShapeFile
        In SI.
    """
    p = Path(path)
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ShapeFileError(f"{p.name}: not valid YAML ({exc})") from exc
    return parse_shape_file(raw, p)


__all__ = [
    "FORMAT",
    "FORMAT_VERSION",
    "LENGTH_UNITS",
    "UNITS",
    "VOLUME_UNITS",
    "ShapeFile",
    "ShapeFileError",
    "format_quantity",
    "load_shape_file",
    "parse_quantity",
    "parse_shape_file",
]
