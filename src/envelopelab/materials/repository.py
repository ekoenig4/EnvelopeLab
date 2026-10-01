"""Fabric library: a SQLite store of fabrics that any design can use.

The library is independent of any design: designs refer to fabrics only by id (the
``zones`` map of :class:`~envelopelab.design.model.DesignDocument`), so a fabric created
once can be chosen in every design that opens the same library. The desktop application
keeps one library file per user (see :func:`open_user_library`).

Two kinds of record live in a library:

* **example** fabrics, seeded by :meth:`FabricLibraryRepository.seed_example_data`. They
  are read-only placeholders tagged ``assumed - verify``; duplicate one to make your own.
* **user** fabrics, created with :meth:`FabricLibraryRepository.add_fabric` and changed
  with :meth:`~FabricLibraryRepository.update_fabric` /
  :meth:`~FabricLibraryRepository.delete_fabric`.

Every value carries a source whose first word is a source tag
(``datasheet | measured | assumed``), optionally followed by a note, e.g.
``"datasheet - Dimension Polyant PN 2020"``. :func:`validate_fabric` rejects anything else,
so no untagged value can enter a library.

Library units (a display boundary, converted to SI where the values are used): areal mass
g/m^2, tensile and tear strength as entered, moduli Pa, porosity as entered, maximum
service temperature degC, roll width m, cost per m^2 as entered.
"""

from __future__ import annotations

import math
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

SourceTag = Literal["datasheet", "measured", "assumed"]
SOURCE_TAGS: tuple[SourceTag, ...] = ("datasheet", "measured", "assumed")
Origin = Literal["example", "user"]

#: Version of the library file layout, stored as SQLite ``PRAGMA user_version``.
#: 0: the original table without an ``origin`` column. 1: adds ``origin``.
SCHEMA_VERSION = 1

_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,63}$")
_EXAMPLE_SOURCE = "assumed - verify"


@dataclass(frozen=True)
class MaterialProperty:
    """A material value and its source (``"<tag>"`` or ``"<tag> - <note>"``)."""

    value: float
    source: str


@dataclass(frozen=True)
class Fabric:
    """One fabric; values in library units (see module docstring)."""

    fabric_id: str
    name: str
    areal_mass: MaterialProperty
    warp_tensile: MaterialProperty
    weft_tensile: MaterialProperty
    tear: MaterialProperty
    seam_efficiency: MaterialProperty
    e_warp: MaterialProperty
    e_weft: MaterialProperty
    g: MaterialProperty
    nu: MaterialProperty
    porosity: MaterialProperty
    max_service_temperature: MaterialProperty
    roll_width: MaterialProperty
    color: str
    color_source: str
    cost: MaterialProperty


@dataclass(frozen=True)
class FabricCatalog:
    """Immutable copy of fabric records (safe to use on any thread, unlike the SQLite
    connection of :class:`FabricLibraryRepository`)."""

    records: tuple[Fabric, ...]

    def fabric(self, fabric_id: str) -> Fabric | None:
        """Fabric ``fabric_id``, or None."""
        return next((f for f in self.records if f.fabric_id == fabric_id), None)

    def fabrics(self) -> list[Fabric]:
        """Every fabric, ordered by id."""
        return sorted(self.records, key=lambda f: f.fabric_id)


class FabricValidationError(ValueError):
    """A fabric was refused; ``problems`` lists every reason."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


class FabricLibraryError(ValueError):
    """A library operation was refused (duplicate id, missing or read-only fabric)."""


def source_tag(source: str) -> SourceTag | None:
    """The source tag a source string starts with, or None.

    ``"datasheet"``, ``"measured - lab 2026-03"`` and ``"assumed - verify"`` are tagged;
    ``"supplier says"`` and ``""`` are not.
    """
    head = re.split(r"[\s\-:,;(]", source.strip(), maxsplit=1)[0].lower()
    for tag in SOURCE_TAGS:
        if head == tag:
            return tag
    return None


# name, label, unit, lower bound, lower bound inclusive, upper bound (inclusive)
_LIMITS: tuple[tuple[str, str, str, float, bool, float], ...] = (
    ("areal_mass", "areal mass", "g/m²", 0.0, False, math.inf),
    ("warp_tensile", "warp tensile strength", "", 0.0, False, math.inf),
    ("weft_tensile", "weft tensile strength", "", 0.0, False, math.inf),
    ("tear", "tear strength", "", 0.0, False, math.inf),
    ("seam_efficiency", "seam efficiency", "", 0.0, False, 1.0),
    ("e_warp", "warp modulus", "Pa", 0.0, False, math.inf),
    ("e_weft", "weft modulus", "Pa", 0.0, False, math.inf),
    ("g", "shear modulus", "Pa", 0.0, False, math.inf),
    ("nu", "Poisson's ratio", "", 0.0, True, math.inf),
    ("porosity", "porosity", "", 0.0, True, math.inf),
    ("max_service_temperature", "max service temperature", "°C", -273.15, False, math.inf),
    ("roll_width", "roll width", "m", 0.0, False, math.inf),
    ("cost", "cost", "", 0.0, True, math.inf),
)


def validate_fabric(fabric: Fabric) -> list[str]:
    """Every reason ``fabric`` cannot be stored (empty: valid).

    Parameters
    ----------
    fabric : Fabric
        Fabric in library units.

    Returns
    -------
    list of str
        Problems; empty when the fabric is valid.

    Notes
    -----
    Checks: an id of 1-64 letters, digits, ``_``, ``.`` or ``-`` (starting with a letter or
    digit); a name and colour; finite values in their physical range (areal mass, strengths,
    moduli and roll width > 0; 0 < seam efficiency <= 1; Poisson's ratio, porosity and cost
    >= 0; service temperature above absolute zero); orthotropic stability
    :math:`\\nu^2 < E_{warp}/E_{weft}` (the condition :class:`MembraneMaterial
    <envelopelab.materials.membrane.MembraneMaterial>` enforces); and a source tag on every
    value (AGENTS.md hard rule).
    """
    problems: list[str] = []
    if not _ID_PATTERN.match(fabric.fabric_id):
        problems.append(
            f"id {fabric.fabric_id!r}: use 1-64 letters, digits, '_', '.' or '-', "
            "starting with a letter or digit"
        )
    if not fabric.name.strip():
        problems.append("name is empty")
    if not fabric.color.strip():
        problems.append("colour is empty")
    if source_tag(fabric.color_source) is None:
        problems.append(f"colour: source {fabric.color_source!r} has no source tag")
    for name, label, unit, low, low_inclusive, high in _LIMITS:
        prop: MaterialProperty = getattr(fabric, name)
        value = prop.value
        suffix = f" {unit}" if unit else ""
        if not math.isfinite(value):
            problems.append(f"{label}: {value} is not a finite number")
        elif value < low or (value == low and not low_inclusive) or value > high:
            bound = f"{'>=' if low_inclusive else '>'} {low:g}{suffix}"
            if math.isfinite(high):
                bound += f" and <= {high:g}{suffix}"
            problems.append(f"{label}: {value:g}{suffix} must be {bound}")
        if source_tag(prop.source) is None:
            problems.append(
                f"{label}: source {prop.source!r} must start with one of {', '.join(SOURCE_TAGS)}"
            )
    e_warp, e_weft, nu = fabric.e_warp.value, fabric.e_weft.value, fabric.nu.value
    if e_warp > 0 and e_weft > 0 and math.isfinite(nu) and nu >= 0 and nu * nu >= e_warp / e_weft:
        problems.append(
            f"Poisson's ratio: {nu:g}² must be < warp/weft modulus ratio {e_warp / e_weft:g} "
            "(orthotropic stability)"
        )
    return problems


def fabric_data(fabric: Fabric) -> dict[str, Any]:
    """JSON-ready values and sources of ``fabric`` (library units).

    Used to fingerprint the fabrics a design uses, so that editing a library fabric marks
    the results built from it stale.
    """
    data: dict[str, Any] = {"name": fabric.name, "color": fabric.color}
    for name, *_ in _LIMITS:
        prop: MaterialProperty = getattr(fabric, name)
        data[name] = [prop.value, prop.source]
    return data


_PROPERTIES = (
    "areal_mass",
    "warp_tensile",
    "weft_tensile",
    "tear",
    "seam_efficiency",
    "e_warp",
    "e_weft",
    "g",
    "nu",
    "porosity",
    "max_service_temperature",
    "roll_width",
)
_COLUMNS = (
    "fabric_id",
    "name",
    *(c for p in _PROPERTIES for c in (p, f"{p}_source")),
    "color",
    "color_source",
    "cost",
    "cost_source",
    "origin",
)


def _example(
    fabric_id: str, name: str, values: tuple[float, ...], color: str, cost: float
) -> Fabric:
    props = {
        p: MaterialProperty(v, _EXAMPLE_SOURCE) for p, v in zip(_PROPERTIES, values, strict=True)
    }
    return Fabric(
        fabric_id=fabric_id,
        name=name,
        color=color,
        color_source=_EXAMPLE_SOURCE,
        cost=MaterialProperty(cost, _EXAMPLE_SOURCE),
        **props,
    )


# Placeholder values (in _PROPERTIES order), not datasheet data.
EXAMPLE_FABRICS: tuple[Fabric, ...] = (
    _example(
        "ripstop_nylon",
        "Ripstop Nylon",
        (42.0, 850.0, 790.0, 21.0, 0.78, 1.2e9, 1.1e9, 4.2e8, 0.34, 12.0, 120.0, 1.5),
        "orange",
        11.5,
    ),
    _example(
        "polyester",
        "Polyester",
        (55.0, 900.0, 880.0, 24.0, 0.81, 1.5e9, 1.4e9, 5.2e8, 0.31, 10.0, 145.0, 1.6),
        "white",
        8.2,
    ),
    _example(
        "nomex",
        "Nomex",
        (93.0, 1200.0, 1100.0, 38.0, 0.76, 2.0e9, 1.8e9, 7.0e8, 0.29, 8.0, 350.0, 1.4),
        "tan",
        28.0,
    ),
)
EXAMPLE_FABRIC_IDS = frozenset(f.fabric_id for f in EXAMPLE_FABRICS)


class FabricLibraryRepository:
    """A fabric library in a SQLite database.

    Parameters
    ----------
    db_path : str or Path, optional
        Database file; ``":memory:"`` (default) for a library that lives only as long as
        this object. A file is created if missing and upgraded to :data:`SCHEMA_VERSION`.
    """

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self.path = None if str(db_path) == ":memory:" else Path(db_path)
        self._connection = sqlite3.connect(str(db_path))
        self._connection.row_factory = sqlite3.Row
        self._ensure_schema()

    # -- schema ---------------------------------------------------------------------------

    def _ensure_schema(self) -> None:
        version = int(self._connection.execute("PRAGMA user_version").fetchone()[0])
        if version > SCHEMA_VERSION:
            raise FabricLibraryError(
                f"fabric library {self.path} has schema version {version}; this EnvelopeLab "
                f"reads up to {SCHEMA_VERSION}. Update EnvelopeLab to use it."
            )
        with self._transaction():
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS fabrics (
                  fabric_id TEXT PRIMARY KEY,
                  name TEXT NOT NULL,
                  areal_mass REAL NOT NULL, areal_mass_source TEXT NOT NULL,
                  warp_tensile REAL NOT NULL, warp_tensile_source TEXT NOT NULL,
                  weft_tensile REAL NOT NULL, weft_tensile_source TEXT NOT NULL,
                  tear REAL NOT NULL, tear_source TEXT NOT NULL,
                  seam_efficiency REAL NOT NULL, seam_efficiency_source TEXT NOT NULL,
                  e_warp REAL NOT NULL, e_warp_source TEXT NOT NULL,
                  e_weft REAL NOT NULL, e_weft_source TEXT NOT NULL,
                  g REAL NOT NULL, g_source TEXT NOT NULL,
                  nu REAL NOT NULL, nu_source TEXT NOT NULL,
                  porosity REAL NOT NULL, porosity_source TEXT NOT NULL,
                  max_service_temperature REAL NOT NULL,
                  max_service_temperature_source TEXT NOT NULL,
                  roll_width REAL NOT NULL, roll_width_source TEXT NOT NULL,
                  color TEXT NOT NULL, color_source TEXT NOT NULL,
                  cost REAL NOT NULL, cost_source TEXT NOT NULL,
                  origin TEXT NOT NULL DEFAULT 'user'
                )
                """
            )
            columns = {
                str(row["name"])
                for row in self._connection.execute("PRAGMA table_info(fabrics)").fetchall()
            }
            if "origin" not in columns:
                # Version 0 libraries predate the example/user split; their example ids
                # held the seeded placeholders, everything else was entered by a user.
                self._connection.execute(
                    "ALTER TABLE fabrics ADD COLUMN origin TEXT NOT NULL DEFAULT 'user'"
                )
                self._connection.executemany(
                    "UPDATE fabrics SET origin = 'example' WHERE fabric_id = ?",
                    [(i,) for i in sorted(EXAMPLE_FABRIC_IDS)],
                )
            self._connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        try:
            yield
        except BaseException:
            self._connection.rollback()
            raise
        self._connection.commit()

    def close(self) -> None:
        """Close the database connection."""
        self._connection.close()

    def __enter__(self) -> FabricLibraryRepository:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # -- writing --------------------------------------------------------------------------

    def _write(self, fabric: Fabric, origin: Origin, replace: bool) -> None:
        values = (
            fabric.fabric_id,
            fabric.name,
            *(x for p in _PROPERTIES for x in _pair(getattr(fabric, p))),
            fabric.color,
            fabric.color_source,
            fabric.cost.value,
            fabric.cost.source,
            origin,
        )
        verb = "INSERT OR REPLACE" if replace else "INSERT"
        placeholders = ", ".join("?" for _ in _COLUMNS)
        self._connection.execute(
            f"{verb} INTO fabrics ({', '.join(_COLUMNS)}) VALUES ({placeholders})", values
        )

    def seed_example_data(self) -> None:
        """Add (or restore) the read-only example fabrics."""
        with self._transaction():
            for fabric in EXAMPLE_FABRICS:
                self._write(fabric, "example", replace=True)

    def add_fabric(self, fabric: Fabric) -> None:
        """Store a new user fabric.

        Raises
        ------
        FabricValidationError
            If :func:`validate_fabric` finds a problem.
        FabricLibraryError
            If a fabric with this id exists or the id is reserved for an example fabric.
        """
        _check(fabric)
        if fabric.fabric_id in EXAMPLE_FABRIC_IDS:
            raise FabricLibraryError(f"id {fabric.fabric_id!r} is reserved for an example fabric")
        if self.fabric_exists(fabric.fabric_id):
            raise FabricLibraryError(f"a fabric with id {fabric.fabric_id!r} already exists")
        with self._transaction():
            self._write(fabric, "user", replace=False)

    def update_fabric(self, fabric: Fabric) -> None:
        """Replace the values of an existing user fabric (matched by id).

        Raises
        ------
        FabricValidationError
            If :func:`validate_fabric` finds a problem.
        FabricLibraryError
            If the fabric does not exist or is a read-only example.
        """
        _check(fabric)
        self._require_user(fabric.fabric_id)
        with self._transaction():
            self._write(fabric, "user", replace=True)

    def delete_fabric(self, fabric_id: str) -> None:
        """Remove a user fabric.

        Designs that still name it keep the id; the application then shows it as missing
        and uses the documented assumed areal mass (see ``zone_areal_masses``).

        Raises
        ------
        FabricLibraryError
            If the fabric does not exist or is a read-only example.
        """
        self._require_user(fabric_id)
        with self._transaction():
            self._connection.execute("DELETE FROM fabrics WHERE fabric_id = ?", (fabric_id,))

    def _require_user(self, fabric_id: str) -> None:
        origin = self.origin(fabric_id)
        if origin is None:
            raise FabricLibraryError(f"no fabric with id {fabric_id!r}")
        if origin == "example":
            raise FabricLibraryError(
                f"{fabric_id!r} is a read-only example fabric; duplicate it to make your own"
            )

    # -- reading --------------------------------------------------------------------------

    def origin(self, fabric_id: str) -> Origin | None:
        """``"example"`` or ``"user"`` for a stored fabric, None if it does not exist."""
        row = self._connection.execute(
            "SELECT origin FROM fabrics WHERE fabric_id = ?", (fabric_id,)
        ).fetchone()
        if row is None:
            return None
        return "example" if row["origin"] == "example" else "user"

    def is_editable(self, fabric_id: str) -> bool:
        """True for a stored user fabric."""
        return self.origin(fabric_id) == "user"

    def known_fabric_ids(self) -> set[str]:
        rows = self._connection.execute("SELECT fabric_id FROM fabrics").fetchall()
        return {str(row["fabric_id"]) for row in rows}

    def fabric(self, fabric_id: str) -> Fabric | None:
        """Fabric ``fabric_id`` with every value and its source tag, or None (library
        units, see module docstring)."""
        row = self._connection.execute(
            "SELECT * FROM fabrics WHERE fabric_id = ?", (fabric_id,)
        ).fetchone()
        return None if row is None else _fabric_from_row(row)

    def fabrics(self) -> list[Fabric]:
        """Every fabric, ordered by id."""
        rows = self._connection.execute("SELECT * FROM fabrics ORDER BY fabric_id").fetchall()
        return [_fabric_from_row(row) for row in rows]

    def catalog(self) -> FabricCatalog:
        """Immutable copy of the library (for worker threads)."""
        return FabricCatalog(tuple(self.fabrics()))

    def fabric_exists(self, fabric_id: str) -> bool:
        row = self._connection.execute(
            "SELECT 1 FROM fabrics WHERE fabric_id = ? LIMIT 1", (fabric_id,)
        ).fetchone()
        return row is not None


def open_user_library(path: str | Path) -> FabricLibraryRepository:
    """Open (creating if needed) the fabric library shared by all designs of a user.

    Parameters
    ----------
    path : str or Path
        Library file (SQLite); its folder is created if missing.

    Returns
    -------
    FabricLibraryRepository
        The library, with the example fabrics present.
    """
    library_path = Path(path)
    library_path.parent.mkdir(parents=True, exist_ok=True)
    repo = FabricLibraryRepository(library_path)
    repo.seed_example_data()
    return repo


def _check(fabric: Fabric) -> None:
    problems = validate_fabric(fabric)
    if problems:
        raise FabricValidationError(problems)


def _pair(prop: MaterialProperty) -> tuple[float, str]:
    return prop.value, prop.source


def _fabric_from_row(row: sqlite3.Row) -> Fabric:
    props = {
        name: MaterialProperty(float(row[name]), str(row[f"{name}_source"])) for name in _PROPERTIES
    }
    return Fabric(
        fabric_id=str(row["fabric_id"]),
        name=str(row["name"]),
        color=str(row["color"]),
        color_source=str(row["color_source"]),
        cost=MaterialProperty(float(row["cost"]), str(row["cost_source"])),
        **props,
    )
