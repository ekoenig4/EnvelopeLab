"""Shape files (``envelopelab.shape`` v1 and v2): a shape family and the values that fix a design.

A shape file is YAML (format: ``docs/formats/shape-file.md``). Lengths and volumes are
written with their unit (``92000 ft^3``, ``2 in``, ``6 m``) and converted to SI here, at
the input boundary; stations are bare fractions of the gore length or station names.

Version 1 holds the profile, named stations, a lobe loft and the three held values.
Version 2 adds everything else a design needs, so a pattern set is described natively
instead of by edits after loading: a profile known only from the mouth to the top opening
(``span: cut``) with straight tape segments, the gore construction (flat-chord gores with
measured seam bows or a crest loft), named panel rows with material zones, panel zones,
the parachute opening, rigging, and ``extends`` (a file built on another one). Version-1
files are read unchanged.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import numpy as np
import yaml

from envelopelab.geometry.gore import CrestLoft, GoreLoft, GoreWidthModel
from envelopelab.project.shape_family import (
    QUANTITIES,
    VARIABLES,
    Dimension,
    NormalizedShape,
    ShapeParameters,
    ShapeSolution,
    solve_shape,
)

if TYPE_CHECKING:
    from pydantic import BaseModel

    from envelopelab.design.model import DesignDocument

FORMAT = "envelopelab.shape"
FORMAT_VERSION = 2
SUPPORTED_VERSIONS = (1, 2)
Span = Literal["poles", "cut"]
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


# --------------------------------------------------------------------------------------
# Version 2: rows, zones, openings, rigging, crest loft, extends
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RowSpec:
    """A panel row of a shape file (SI).

    Attributes
    ----------
    name : str
        Row letter or name (up to 8 characters).
    top : float or None
        Station of the row's top seam, fraction of L (the profile's length unit); None for
        the last row, which ends at the top opening.
    zone : str or None
        Material zone (key of the file's ``zones``); None for the first zone.
    bows : (float, float) or None
        Measured (bottom, top) seam bows, m, positive outward (flat-chord gores only).
    """

    name: str
    top: float | None
    zone: str | None = None
    bows: tuple[float, float] | None = None


#: Lengths in the ``rigging`` section (written with a unit, converted to m).
RIGGING_LENGTHS = frozenset(
    {
        "shroud_attachment",
        "centralizing_depth",
        "centre_ring_diameter",
        "spare_length",
        "frame_radius",
        "frame_drop",
        "crows_foot_drop",
        "height",
        "opening_width",
    }
)
RIGGING_SECTIONS = ("parachute", "red_line", "flying_wires", "scoop", "turning_vents", "crown_line")


def _rigging_values(raw: object, where: str) -> Any:
    """Convert the lengths of a rigging mapping (recursively) to m."""
    if isinstance(raw, dict):
        out: dict[str, Any] = {}
        for key, value in raw.items():
            name = f"{where}.{key}"
            if key in RIGGING_LENGTHS:
                out[key] = parse_quantity(value, "length", name)
            else:
                out[key] = _rigging_values(value, name)
        return out
    if isinstance(raw, list):
        return [_rigging_values(v, f"{where}[{i}]") for i, v in enumerate(raw)]
    return raw


def _parse_rigging(raw: object) -> dict[str, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ShapeFileError("rigging: a mapping of parachute, red_line, flying_wires, ...")
    unknown = sorted(set(raw) - set(RIGGING_SECTIONS))
    if unknown:
        raise ShapeFileError(
            f"rigging: unknown section(s) {', '.join(unknown)} "
            f"(known: {', '.join(RIGGING_SECTIONS)})"
        )
    if "turning_vents" in raw and not isinstance(raw["turning_vents"], list):
        raise ShapeFileError("rigging.turning_vents: a list of vents")
    for key in ("parachute", "red_line", "flying_wires", "scoop"):
        if key in raw and raw[key] is not None and not isinstance(raw[key], dict):
            raise ShapeFileError(f"rigging.{key}: a mapping")
    return dict(_rigging_values(raw, "rigging"))


def _station(value: object, stations: Mapping[str, float], key: str) -> float:
    if isinstance(value, str):
        if value not in stations:
            named = ", ".join(stations) or "none"
            raise ShapeFileError(f"{key}: unknown station {value!r} (named stations: {named})")
        return float(stations[value])
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ShapeFileError(f"{key}: a station (fraction or station name)")
    return float(value)


def _parse_rows(raw: object, stations: Mapping[str, float]) -> tuple[RowSpec, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list) or not raw:
        raise ShapeFileError("rows: a list of {name, top, zone, bow} entries, mouth first")
    rows: list[RowSpec] = []
    for i, entry in enumerate(raw):
        key = f"rows[{i}]"
        if not isinstance(entry, dict) or "name" not in entry:
            raise ShapeFileError(f"{key}: a mapping with at least 'name'")
        unknown = sorted(set(entry) - {"name", "top", "zone", "bow"})
        if unknown:
            raise ShapeFileError(f"{key}: unknown key(s) {', '.join(unknown)}")
        name = str(entry["name"])
        if not 1 <= len(name) <= 8:
            raise ShapeFileError(f"{key}.name: 1 to 8 characters")
        last = i == len(raw) - 1
        if "top" not in entry and not last:
            raise ShapeFileError(f"{key}.top: required except for the last row")
        top = None if "top" not in entry else _station(entry["top"], stations, f"{key}.top")
        bows = None
        if "bow" in entry:
            pair = entry["bow"]
            if not isinstance(pair, list) or len(pair) != 2:
                raise ShapeFileError(f"{key}.bow: [bottom, top] lengths")
            bows = (
                parse_quantity(pair[0], "length", f"{key}.bow[0]"),
                parse_quantity(pair[1], "length", f"{key}.bow[1]"),
            )
        zone = None if entry.get("zone") is None else str(entry["zone"])
        rows.append(RowSpec(name=name, top=top, zone=zone, bows=bows))
    names = [r.name for r in rows]
    if len(set(names)) != len(names):
        raise ShapeFileError("rows: row names must be unique")
    tops = [r.top for r in rows if r.top is not None]
    if any(b <= a for a, b in zip(tops, tops[1:], strict=False)):
        raise ShapeFileError("rows: tops must increase from the mouth up")
    with_bows = [r.bows is not None for r in rows]
    if any(with_bows) and not all(with_bows):
        raise ShapeFileError("rows: give 'bow' for every row or for none")
    return tuple(rows)


def _parse_crest(raw: object, stations: Mapping[str, float]) -> CrestLoft:
    if not isinstance(raw, dict) or "fraction" not in raw:
        raise ShapeFileError("loft.crest: {fraction, taper: [[s, taper], ...]}")
    taper = raw.get("taper", [[0.0, 1.0]])
    if not isinstance(taper, list) or not taper:
        raise ShapeFileError("loft.crest.taper: a list of [s, taper] entries")
    points = []
    for i, entry in enumerate(taper):
        if not isinstance(entry, list) or len(entry) != 2:
            raise ShapeFileError(f"loft.crest.taper[{i}]: [s, taper]")
        points.append((_station(entry[0], stations, f"loft.crest.taper[{i}]"), float(entry[1])))
    points.sort()
    try:
        return CrestLoft(
            float(raw["fraction"]), tuple(s for s, _ in points), tuple(t for _, t in points)
        )
    except (TypeError, ValueError) as exc:
        raise ShapeFileError(f"loft.crest: {exc}") from exc


#: Keys a child file replaces whole instead of merging (its own regression data).
MERGE_REPLACED = frozenset({"published", "format_version", "extends"})
#: Lists of named entries that a child file merges by name (others are replaced).
MERGE_BY_NAME = frozenset({"special_shapes", "panel_zones", "turning_vents"})


def _merge_named(base: list[Any], child: list[Any], key: str) -> list[Any]:
    for entry in [*base, *child]:
        if not isinstance(entry, dict) or "name" not in entry:
            raise ShapeFileError(f"{key}: every entry needs a name to be merged with extends")
    out = [dict(v) for v in base]
    index = {v["name"]: i for i, v in enumerate(out)}
    for value in child:
        if value["name"] in index:
            out[index[value["name"]]] = value
        else:
            out.append(value)
    return out


def _deep_merge(base: Any, child: Any, key: str = "") -> Any:
    """``child`` over ``base``: mappings merge key by key, the lists in :data:`MERGE_BY_NAME`
    merge by entry name, everything else (including other lists) is replaced."""
    if isinstance(base, dict) and isinstance(child, dict):
        out = dict(base)
        for name, value in child.items():
            if name in MERGE_REPLACED or name not in out:
                out[name] = value
            else:
                out[name] = _deep_merge(out[name], value, name)
        return out
    if key in MERGE_BY_NAME and isinstance(base, list) and isinstance(child, list):
        return _merge_named(base, child, key)
    return child


def _read_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ShapeFileError(f"{path.name}: not valid YAML ({exc})") from exc
    except OSError as exc:
        raise ShapeFileError(f"{path.name}: cannot read ({exc.strerror})") from exc


def resolve_extends(raw: Any, path: Path, seen: tuple[Path, ...] = ()) -> Any:
    """The file's mapping merged over the file it ``extends`` (recursively).

    Raises
    ------
    ShapeFileError
        For a missing base file or a cycle (the message names ``extends``).
    """
    if not isinstance(raw, dict) or "extends" not in raw:
        return raw
    target = (path.parent / str(raw["extends"])).resolve()
    chain = (*seen, path.resolve())
    if target in chain:
        raise ShapeFileError(f"extends: {raw['extends']} is already in the chain (a cycle)")
    if not target.is_file():
        raise ShapeFileError(f"extends: base file {raw['extends']} not found")
    base = resolve_extends(_read_yaml(target), target, chain)
    if not isinstance(base, dict):
        raise ShapeFileError(f"extends: {raw['extends']} is not a shape file mapping")
    child = {k: v for k, v in raw.items() if k != "extends"}
    if base.get("format_version") != child.get("format_version", base.get("format_version")):
        raise ShapeFileError("extends: the base and the file must have the same format_version")
    return _deep_merge(base, child)


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
        Held values that fix the file's design (m, m^3 or fractions of L). A ``cut`` span
        holds the mouth and top stations at 0 and 1 itself.
    gore_count : int
        Gores N.
    seam_allowance : float
        Cut allowance per gore edge, m.
    source_file, reference : str
        Where the design comes from.
    published : dict
        The file's ``published`` block as written (regression data, never an input).
    format_version : int
        1 or 2.
    span : {"poles", "cut"}
        ``poles``: the profile runs pole to pole and L is the gore length; ``cut``: it runs
        from the mouth (0) to the top opening (1) and L is the tape length.
    rows : tuple of RowSpec
        Named panel rows, mouth first (empty: equal rows chosen when the design is made).
    zones : dict of str to str
        Material zone to fabric id (empty: one ``body`` zone of the chosen fabric).
    panel_zones : tuple of dict
        ``GoreSpec.panel_zones`` entries (name, row, gores, zone).
    crest : CrestLoft or None
        Crest loft of a flat-chord gore, stations as fractions of L.
    seal_overlap, crown_ring : float or None
        Parachute seal overlap and crown ring diameter, m (None: the defaults).
    rigging : dict
        The ``rigging`` section with lengths in m (design-model field names).
    special_shapes : tuple of dict
        The ``special_shapes`` section as written (see :meth:`shapes`).
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
    format_version: int = FORMAT_VERSION
    span: Span = "poles"
    rows: tuple[RowSpec, ...] = ()
    zones: dict[str, str] = field(default_factory=dict)
    panel_zones: tuple[dict[str, Any], ...] = ()
    crest: CrestLoft | None = None
    seal_overlap: float | None = None
    crown_ring: float | None = None
    rigging: dict[str, Any] = field(default_factory=dict)
    special_shapes: tuple[dict[str, Any], ...] = ()

    def start(self) -> ShapeParameters:
        """Starting design for :meth:`solve`: held variables, else named or typical ones.

        The gore length starts from the held nominal volume when there is one, else 20 m;
        the cut stations from the ``mouth`` and ``vent`` stations, else 0.15 and 0.9 (0 and
        1 for a ``cut`` span).
        """
        named = self.shape.stations
        if "gore_length" in self.hold:
            length = self.hold["gore_length"]
        elif "tape_length" in self.hold and self.span == "cut":
            length = self.hold["tape_length"]
        elif "nominal_volume" in self.hold:
            coefficient = self.shape.nominal_volume_coefficient(self.gore_count)
            length = (self.hold["nominal_volume"] / coefficient) ** (1 / 3)
        else:
            length = 20.0
        low, high = (0.0, 1.0) if self.span == "cut" else (0.15, 0.9)
        return ShapeParameters(
            gore_length=length,
            mouth_station=self.hold.get("mouth_station", named.get("mouth", low)),
            top_station=self.hold.get("top_station", named.get("vent", high)),
            gore_count=self.gore_count,
            seam_allowance=self.seam_allowance,
        )

    def solve(self, hold: dict[str, float] | None = None) -> ShapeSolution:
        """Solve the file's design, or a variant holding other values (SI)."""
        return solve_shape(self.shape, self.start(), self.hold if hold is None else hold)

    def design(
        self,
        solution: ShapeSolution | None = None,
        name: str | None = None,
        fabric_id: str = "ripstop_nylon",
        row_count: int = 12,
        internal_temperature: float = 373.15,
        ambient_temperature: float = 288.15,
        ambient_pressure: float = 101325.0,
        payload_mass: float = 0.0,
        seams: Literal["measured", "crest"] = "measured",
    ) -> DesignDocument:
        """Standard-gore design document of a solved design of this file.

        Everything the file describes goes into the design: the profile (spline or
        straight tape), the gore construction and loft, the named rows with their zones
        and seam bows, panel zones, the parachute opening and the rigging (the defaults of
        :func:`envelopelab.rigging.with_default_rigging` where the file says nothing).
        Measured seam bows are scaled with the gore length from the file's own design.

        Parameters
        ----------
        solution : ShapeSolution, optional
            A converged solution (default: the file's own design, :meth:`solve`).
        name : str, optional
            Design name (default the file's name).
        fabric_id : str
            Fabric of the ``body`` zone when the file has no ``zones``.
        row_count : int
            Equal panel rows when the file has no ``rows``.
        internal_temperature, ambient_temperature : float
            K.
        ambient_pressure : float
            Pa.
        payload_mass : float
            kg.
        seams : {"measured", "crest"}
            Flat-chord gores with both measured row bows and a crest loft: use the measured
            bows (scaled) or generate the bows from the crest loft.

        Returns
        -------
        DesignDocument
            With its content hash.

        Raises
        ------
        ShapeFileError
            For a section that does not fit the solved design (the message names it).
        ValueError
            When the solution did not converge (no design is made from it).
        """
        from envelopelab.design.model import DesignDocument
        from envelopelab.project.gore_design import equal_row_heights
        from envelopelab.project.templates import new_design
        from envelopelab.rigging import with_default_rigging

        solution = self.solve() if solution is None else solution
        if not solution.converged:
            raise ValueError(f"the shape did not solve, so no design was made: {solution.message}")
        params, values = solution.parameters, solution.values
        length = params.gore_length
        lower, upper = params.mouth_station, params.top_station
        r, z = self.shape.control_points(lower, upper)
        if self.rows:
            heights, letters, row_zones, bows = self._rows(lower, upper, length)
        else:
            heights = equal_row_heights(values["tape_length"], row_count)
            letters, row_zones, bows = None, None, None
        overlap = self.seal_overlap
        named = self.shape.stations.get("parachute_overlap")
        if overlap is None and named is not None and lower < named < upper:
            overlap = (upper - named) * length
            if overlap >= values["top_diameter"] / 2.0:
                overlap = None
        document = new_design(
            name=name or self.name,
            points=list(zip((r * length).tolist(), (z * length).tolist(), strict=True)),
            gore_count=params.gore_count,
            row_heights=heights,
            mouth_diameter=values["mouth_diameter"],
            top_diameter=values["top_diameter"],
            fabric_id=fabric_id,
            seam_allowance=params.seam_allowance,
            internal_temperature=internal_temperature,
            ambient_temperature=ambient_temperature,
            ambient_pressure=ambient_pressure,
            payload_mass=payload_mass,
            row_letters=letters,
            seal_overlap=overlap,
            rigging=False,
            row_zones=row_zones,
            loft=self.shape.design_loft(lower, upper),
        )
        raw = document.model_dump(by_alias=True, mode="json")
        gores = raw["gores"]
        if self.zones:
            raw["zones"] = dict(self.zones)
        gores["construction"] = self.shape.construction
        gores["profile_interpolation"] = self.shape.interpolation
        if self.crown_ring is not None:
            gores["crown_ring"] = self.crown_ring
        if seams == "crest" and self.crest is None:
            raise ShapeFileError("design: the file has no crest loft to generate the seams")
        if bows is not None and seams == "measured":
            reference = self._reference_length()
            for row, (bottom, top) in zip(gores["panel_rows"], bows, strict=True):
                row["bow_bottom"] = bottom * length / reference
                row["bow_top"] = top * length / reference
        elif self.crest is not None:
            gores["crest_loft"] = self._design_crest(lower, upper)
        gores["panel_zones"] = [dict(z) for z in self.panel_zones]
        try:
            document = DesignDocument.model_validate(raw)
        except ValueError as exc:
            raise ShapeFileError(f"design: {exc}") from exc
        document = with_default_rigging(self._apply_rigging(document))
        return document.with_updated_hash()

    def _rows(
        self, lower: float, upper: float, length: float
    ) -> tuple[list[float], list[str], list[str | None], list[tuple[float, float]] | None]:
        """Row heights (m), names, zones and measured bows of the cut design."""
        tops = [row.top for row in self.rows[:-1]]
        bounds = [lower, *[t for t in tops if t is not None], upper]
        if len(bounds) != len(self.rows) + 1 or any(
            b <= a for a, b in zip(bounds, bounds[1:], strict=False)
        ):
            raise ShapeFileError(
                "rows: every row top must lie between the mouth and the top opening "
                f"(stations {lower:g} to {upper:g})"
            )
        heights = [(b - a) * length for a, b in zip(bounds, bounds[1:], strict=False)]
        zones = [row.zone for row in self.rows]
        known = set(self.zones) if self.zones else {"body"}
        for row in self.rows:
            if row.zone is not None and row.zone not in known:
                raise ShapeFileError(f"rows: zone {row.zone!r} of row {row.name} is not in zones")
        bows = None
        if self.rows[0].bows is not None:
            bows = [row.bows for row in self.rows if row.bows is not None]
        return heights, [row.name for row in self.rows], zones, bows

    def _reference_length(self) -> float:
        """L of the file's own design (measured bows are at this size), m."""
        solution = self.solve()
        if not solution.converged:
            raise ValueError(f"the file's own design does not solve: {solution.message}")
        return solution.parameters.gore_length

    def _design_crest(self, lower: float, upper: float) -> dict[str, Any]:
        """The crest loft re-expressed in fractions of the design's tape length."""
        assert self.crest is not None
        crest = self.crest
        inside = [s for s in crest.stations if lower < s < upper]
        stations = [lower, *inside, upper]
        taper = [float(v) for v in np.interp(stations, crest.stations, crest.taper)]
        span = upper - lower
        return {
            "fraction": crest.fraction,
            "taper": [
                {"station": min(max((s - lower) / span, 0.0), 1.0), "taper": v}
                for s, v in zip(stations, taper, strict=True)
            ],
        }

    def _apply_rigging(self, document: DesignDocument) -> DesignDocument:
        """``document`` with the file's rigging over the defaults (SI)."""
        from envelopelab.design.model import DesignDocument
        from envelopelab.rigging.defaults import (
            default_flying_wires,
            default_parachute,
            default_red_line,
            default_scoop,
            turning_vent_pair,
        )

        if not self.rigging:
            return document
        raw = document.model_dump(by_alias=True, mode="json")
        rig = self.rigging
        defaults: dict[str, Callable[[DesignDocument], BaseModel]] = {
            "parachute": default_parachute,
            "red_line": default_red_line,
            "flying_wires": default_flying_wires,
            "scoop": default_scoop,
        }
        for key, make in defaults.items():
            if key not in rig:
                continue
            value = rig[key]
            merged = (
                None
                if value is None
                else {**make(document).model_dump(mode="json", by_alias=True), **value}
            )
            if key == "parachute":
                raw["parachute"] = merged
            elif key == "scoop":
                raw["scoop"] = merged
            else:
                raw["rigging"][key] = merged
        if "crown_line" in rig:
            raw["rigging"]["crown_line"] = str(rig["crown_line"])
        if "turning_vents" in rig:
            template = turning_vent_pair(document)[0].model_dump(mode="json", by_alias=True)
            vents = []
            for i, vent in enumerate(rig["turning_vents"]):
                if not isinstance(vent, dict):
                    raise ShapeFileError(f"rigging.turning_vents[{i}]: a mapping")
                vents.append({**template, "name": f"turning vent {i + 1}", **vent})
            raw["turning_vents"] = vents
        try:
            return DesignDocument.model_validate(raw)
        except ValueError as exc:
            raise ShapeFileError(f"rigging: {exc}") from exc


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


def _parse_loft(raw: object, stations: dict[str, float]) -> GoreLoft | CrestLoft | None:
    """The ``loft`` block: ``{ratio: k}`` or ``{stations: [[s, k], ...]}`` (a lobe loft; s a
    fraction of L or a station name; k the lobe-radius ratio, dimensionless), or
    ``{crest: {fraction, taper}}`` (a crest loft of a flat-chord gore)."""
    if raw is None:
        return None
    if isinstance(raw, dict) and "crest" in raw:
        if len(raw) != 1:
            raise ShapeFileError("loft: give either a lobe loft or 'crest', not both")
        return _parse_crest(raw["crest"], stations)
    if not isinstance(raw, dict) or ("ratio" in raw) == ("stations" in raw):
        raise ShapeFileError(
            "loft: give either 'ratio' (constant), 'stations' ([s, k] list) or 'crest'"
        )
    try:
        if "ratio" in raw:
            return GoreLoft.constant(float(raw["ratio"]))
        table = raw["stations"]
        if not isinstance(table, list) or not table:
            raise ShapeFileError("loft.stations: a list of [s, k] entries")
        points: list[tuple[float, float]] = []
        for entry in table:
            if not isinstance(entry, list) or len(entry) != 2:
                raise ShapeFileError("loft.stations: each entry is [s, k]")
            s, k = entry
            if isinstance(s, str):
                if s not in stations:
                    named = ", ".join(stations) or "none"
                    raise ShapeFileError(
                        f"loft.stations: unknown station {s!r} (named stations: {named})"
                    )
                s = stations[s]
            points.append((float(s), float(k)))
        points.sort()
        return GoreLoft(tuple(s for s, _ in points), tuple(k for _, k in points))
    except (TypeError, ValueError) as exc:
        if isinstance(exc, ShapeFileError):
            raise
        raise ShapeFileError(f"loft: {exc}") from exc


#: Top-level keys of a version-2 file.
KEYS_V2 = frozenset(
    {
        "format",
        "format_version",
        "extends",
        "name",
        "description",
        "source",
        "profile",
        "stations",
        "loft",
        "design",
        "rows",
        "zones",
        "panel_zones",
        "openings",
        "rigging",
        "special_shapes",
        "published",
    }
)
#: Keys that need format version 2.
ONLY_V2 = frozenset(
    KEYS_V2
    - {
        "format",
        "format_version",
        "name",
        "description",
        "source",
        "profile",
        "stations",
        "loft",
        "design",
        "published",
    }
)


def parse_shape_file(raw: object, path: Path) -> ShapeFile:
    """Validate a parsed shape-file mapping (``extends`` already resolved) and convert it to SI.

    Raises
    ------
    ShapeFileError
        For a wrong format, missing keys, unknown units or an invalid profile.
    """
    if not isinstance(raw, dict):
        raise ShapeFileError("a shape file is a YAML mapping")
    if raw.get("format") != FORMAT:
        raise ShapeFileError(f"format must be {FORMAT!r}")
    version = raw.get("format_version")
    if version not in SUPPORTED_VERSIONS:
        raise ShapeFileError(f"unsupported format_version {version!r}")
    if version == 1:
        newer = sorted(set(raw) & ONLY_V2)
        if newer:
            raise ShapeFileError(f"{', '.join(newer)}: needs format_version 2")
    else:
        unknown = sorted(set(raw) - KEYS_V2)
        if unknown:
            raise ShapeFileError(f"unknown key(s): {', '.join(unknown)}")
    profile = _require(raw, "profile", dict)
    source = str(profile.get("source", "assumed"))
    if source not in SOURCE_TAGS:
        raise ShapeFileError(f"profile.source must be one of {', '.join(SOURCE_TAGS)}")
    span = str(profile.get("span", "poles"))
    interpolation = str(profile.get("interpolation", "spline"))
    if version == 1 and ("span" in profile or "interpolation" in profile):
        raise ShapeFileError("profile.span, profile.interpolation: need format_version 2")
    if span not in ("poles", "cut"):
        raise ShapeFileError("profile.span must be 'poles' or 'cut'")
    if interpolation not in ("spline", "linear"):
        raise ShapeFileError("profile.interpolation must be 'spline' or 'linear'")
    table = _require(profile, "stations", list, "profile.")
    try:
        s = [float(p[0]) for p in table]
        r = [float(p[1]) for p in table]
        if any(len(p) != 2 for p in table):
            raise TypeError
    except (TypeError, ValueError, IndexError) as exc:
        raise ShapeFileError("profile.stations: each entry is [s, r]") from exc
    stations = {str(k): float(v) for k, v in (raw.get("stations") or {}).items()}
    design = _require(raw, "design", dict)
    construction = str(design.get("construction", "lobe"))
    if construction not in ("lobe", "flat_chord"):
        raise ShapeFileError("design.construction must be 'lobe' or 'flat_chord'")
    if version == 1 and "construction" in design:
        raise ShapeFileError("design.construction: needs format_version 2")
    loft = _parse_loft(raw.get("loft"), stations)
    crest = loft if isinstance(loft, CrestLoft) else None
    lobe = loft if isinstance(loft, GoreLoft) else None
    if crest is not None and construction != "flat_chord":
        raise ShapeFileError("loft.crest: needs design.construction: flat_chord")
    if lobe is not None and construction != "lobe":
        raise ShapeFileError("loft: a flat_chord gore is lofted by 'crest'")
    try:
        shape = NormalizedShape(
            s=s,  # type: ignore[arg-type]
            r=r,  # type: ignore[arg-type]
            stations=stations,
            source=source,
            loft=lobe,
            interpolation=interpolation,  # type: ignore[arg-type]
            construction=construction,  # type: ignore[arg-type]
        )
    except ValueError as exc:
        raise ShapeFileError(f"profile: {exc}") from exc
    hold_raw = _require(design, "hold", dict, "design.")
    hold = {str(k): _hold_value(shape, str(k), v) for k, v in hold_raw.items()}
    if span == "cut":
        if "nominal_volume" in hold:
            raise ShapeFileError(
                "design.hold.nominal_volume: a 'cut' profile has no closed shape; hold "
                "envelope_volume instead"
            )
        hold.setdefault("mouth_station", 0.0)
        hold.setdefault("top_station", 1.0)
    gore_count = _require(design, "gore_count", int, "design.")
    if lobe is not None:
        try:
            GoreWidthModel.lofted(gore_count, lobe)
        except ValueError as exc:
            raise ShapeFileError(f"loft: {exc}") from exc
    allowance = parse_quantity(
        design.get("seam_allowance", "0 m"), "length", "design.seam_allowance"
    )
    rows = _parse_rows(raw.get("rows"), stations)
    if any(row.bows is not None for row in rows):
        if construction != "flat_chord":
            raise ShapeFileError("rows.bow: needs design.construction: flat_chord")
    zones_raw = raw.get("zones") or {}
    if not isinstance(zones_raw, dict):
        raise ShapeFileError("zones: a mapping of zone name to fabric id")
    zones = {str(k): str(v) for k, v in zones_raw.items()}
    panel_zones = raw.get("panel_zones") or []
    if not isinstance(panel_zones, list) or not all(isinstance(z, dict) for z in panel_zones):
        raise ShapeFileError("panel_zones: a list of {name, row, gores, zone}")
    openings = raw.get("openings") or {}
    if not isinstance(openings, dict) or set(openings) - {"seal_overlap", "crown_ring"}:
        raise ShapeFileError("openings: {seal_overlap, crown_ring} lengths")
    seal = openings.get("seal_overlap")
    crown = openings.get("crown_ring")
    shapes = raw.get("special_shapes") or []
    if not isinstance(shapes, list) or not all(isinstance(z, dict) for z in shapes):
        raise ShapeFileError("special_shapes: a list of shapes")
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
        format_version=int(version),
        span=span,  # type: ignore[arg-type]
        rows=rows,
        zones=zones,
        panel_zones=tuple(dict(z) for z in panel_zones),
        crest=crest,
        seal_overlap=None
        if seal is None
        else parse_quantity(seal, "length", "openings.seal_overlap"),
        crown_ring=None
        if crown is None
        else parse_quantity(crown, "length", "openings.crown_ring"),
        rigging=_parse_rigging(raw.get("rigging")),
        special_shapes=tuple(dict(z) for z in shapes),
    )


def load_shape_file(path: str | Path) -> ShapeFile:
    """Read a shape file (``*.yaml``), merged over the file it ``extends``.

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
    raw = resolve_extends(_read_yaml(p), p)
    return parse_shape_file(raw, p)


__all__ = [
    "FORMAT",
    "FORMAT_VERSION",
    "LENGTH_UNITS",
    "SUPPORTED_VERSIONS",
    "UNITS",
    "VOLUME_UNITS",
    "RowSpec",
    "ShapeFile",
    "ShapeFileError",
    "format_quantity",
    "load_shape_file",
    "parse_quantity",
    "parse_shape_file",
    "resolve_extends",
]
