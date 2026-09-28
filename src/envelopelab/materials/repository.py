from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Literal

SourceTag = Literal["datasheet", "measured", "assumed"]


@dataclass(frozen=True)
class MaterialProperty:
    value: float
    source: str


@dataclass(frozen=True)
class Fabric:
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


class FabricLibraryRepository:
    def __init__(self, db_path: str = ":memory:") -> None:
        self._connection = sqlite3.connect(db_path)
        self._connection.row_factory = sqlite3.Row
        self._ensure_schema()

    def _ensure_schema(self) -> None:
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
              max_service_temperature REAL NOT NULL, max_service_temperature_source TEXT NOT NULL,
              roll_width REAL NOT NULL, roll_width_source TEXT NOT NULL,
              color TEXT NOT NULL, color_source TEXT NOT NULL,
              cost REAL NOT NULL, cost_source TEXT NOT NULL
            )
            """
        )
        self._connection.commit()

    def seed_example_data(self) -> None:
        source = "assumed - verify"
        self._connection.executemany(
            """
            INSERT OR REPLACE INTO fabrics (
              fabric_id, name,
              areal_mass, areal_mass_source,
              warp_tensile, warp_tensile_source,
              weft_tensile, weft_tensile_source,
              tear, tear_source,
              seam_efficiency, seam_efficiency_source,
              e_warp, e_warp_source,
              e_weft, e_weft_source,
              g, g_source,
              nu, nu_source,
              porosity, porosity_source,
              max_service_temperature, max_service_temperature_source,
              roll_width, roll_width_source,
              color, color_source,
              cost, cost_source
            ) VALUES (
              ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
              ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
              ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            [
                (
                    "ripstop_nylon",
                    "Ripstop Nylon",
                    42.0,
                    source,
                    850.0,
                    source,
                    790.0,
                    source,
                    21.0,
                    source,
                    0.78,
                    source,
                    1.2e9,
                    source,
                    1.1e9,
                    source,
                    4.2e8,
                    source,
                    0.34,
                    source,
                    12.0,
                    source,
                    120.0,
                    source,
                    1.5,
                    source,
                    "orange",
                    source,
                    11.5,
                    source,
                ),
                (
                    "polyester",
                    "Polyester",
                    55.0,
                    source,
                    900.0,
                    source,
                    880.0,
                    source,
                    24.0,
                    source,
                    0.81,
                    source,
                    1.5e9,
                    source,
                    1.4e9,
                    source,
                    5.2e8,
                    source,
                    0.31,
                    source,
                    10.0,
                    source,
                    145.0,
                    source,
                    1.6,
                    source,
                    "white",
                    source,
                    8.2,
                    source,
                ),
                (
                    "nomex",
                    "Nomex",
                    93.0,
                    source,
                    1200.0,
                    source,
                    1100.0,
                    source,
                    38.0,
                    source,
                    0.76,
                    source,
                    2.0e9,
                    source,
                    1.8e9,
                    source,
                    7.0e8,
                    source,
                    0.29,
                    source,
                    8.0,
                    source,
                    350.0,
                    source,
                    1.4,
                    source,
                    "tan",
                    source,
                    28.0,
                    source,
                ),
            ],
        )
        self._connection.commit()

    def known_fabric_ids(self) -> set[str]:
        rows = self._connection.execute("SELECT fabric_id FROM fabrics").fetchall()
        return {str(row["fabric_id"]) for row in rows}

    def fabric_exists(self, fabric_id: str) -> bool:
        row = self._connection.execute(
            "SELECT 1 FROM fabrics WHERE fabric_id = ? LIMIT 1", (fabric_id,)
        ).fetchone()
        return row is not None
