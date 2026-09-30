"""User-created fabrics in the shared fabric library (envelopelab.materials.repository)."""

from __future__ import annotations

import dataclasses
import math
import sqlite3
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from envelopelab.materials import (
    Fabric,
    FabricLibraryError,
    FabricLibraryRepository,
    FabricValidationError,
    MaterialProperty,
    open_user_library,
    validate_fabric,
)
from envelopelab.materials.repository import (
    EXAMPLE_FABRIC_IDS,
    SCHEMA_VERSION,
    fabric_data,
    source_tag,
)


def make_fabric(fabric_id: str = "my_poly", **changes: object) -> Fabric:
    base = FabricLibraryRepository()
    base.seed_example_data()
    template = base.fabric("polyester")
    assert template is not None
    measured = {
        f.name: MaterialProperty(getattr(template, f.name).value, "measured - test coupon")
        for f in dataclasses.fields(Fabric)
        if isinstance(getattr(template, f.name), MaterialProperty)
    }
    fabric = dataclasses.replace(
        template,
        fabric_id=fabric_id,
        name="My polyester",
        color="#c03020",
        color_source="measured",
        **measured,
    )
    return dataclasses.replace(fabric, **changes)  # type: ignore[arg-type]


def test_created_fabric_is_shared_through_the_library_file(tmp_path: Path) -> None:
    path = tmp_path / "library" / "materials.sqlite"
    with open_user_library(path) as library:
        library.add_fabric(make_fabric())
    # A second opening (another design, another app start) sees the same fabric.
    with open_user_library(path) as library:
        fabric = library.fabric("my_poly")
        assert fabric == make_fabric()
        assert library.is_editable("my_poly")
        assert EXAMPLE_FABRIC_IDS <= library.known_fabric_ids()


def test_update_and_delete_user_fabric(tmp_path: Path) -> None:
    with open_user_library(tmp_path / "m.sqlite") as library:
        library.add_fabric(make_fabric())
        changed = make_fabric(areal_mass=MaterialProperty(61.5, "datasheet - rev B"))
        library.update_fabric(changed)
        assert library.fabric("my_poly") == changed
        library.delete_fabric("my_poly")
        assert library.fabric("my_poly") is None
        with pytest.raises(FabricLibraryError, match="no fabric"):
            library.update_fabric(changed)
        with pytest.raises(FabricLibraryError, match="no fabric"):
            library.delete_fabric("my_poly")


def test_duplicate_ids_are_refused() -> None:
    library = FabricLibraryRepository()
    library.add_fabric(make_fabric())
    with pytest.raises(FabricLibraryError, match="already exists"):
        library.add_fabric(make_fabric(name="other"))
    with pytest.raises(FabricLibraryError, match="reserved"):
        library.add_fabric(make_fabric("nomex"))


def test_example_fabrics_are_read_only_and_restored() -> None:
    library = FabricLibraryRepository()
    library.seed_example_data()
    assert library.origin("nomex") == "example"
    assert not library.is_editable("nomex")
    edited = dataclasses.replace(make_fabric("nomex"))
    with pytest.raises(FabricLibraryError, match="read-only"):
        library.update_fabric(edited)
    with pytest.raises(FabricLibraryError, match="read-only"):
        library.delete_fabric("nomex")
    before = library.fabrics()
    library.seed_example_data()
    assert library.fabrics() == before


def test_invalid_values_are_refused_with_every_reason() -> None:
    library = FabricLibraryRepository()
    bad = make_fabric(
        "bad id",
        name=" ",
        areal_mass=MaterialProperty(-1.0, "measured"),
        seam_efficiency=MaterialProperty(1.2, "assumed"),
        roll_width=MaterialProperty(math.nan, "datasheet"),
        tear=MaterialProperty(20.0, "supplier said so"),
    )
    with pytest.raises(FabricValidationError) as info:
        library.add_fabric(bad)
    text = "; ".join(info.value.problems)
    for expected in (
        "id 'bad id'",
        "name is empty",
        "areal mass: -1 g/m² must be > 0",
        "seam efficiency: 1.2 must be > 0 and <= 1",
        "roll width: nan is not a finite number",
        "tear strength: source 'supplier said so' must start with one of",
    ):
        assert expected in text
    assert library.fabric("bad id") is None


def test_poisson_ratio_must_be_orthotropically_stable() -> None:
    fabric = make_fabric(
        e_warp=MaterialProperty(1.0e9, "measured"),
        e_weft=MaterialProperty(4.0e9, "measured"),
        nu=MaterialProperty(0.5, "measured"),
    )
    assert any("orthotropic stability" in p for p in validate_fabric(fabric))
    assert validate_fabric(dataclasses.replace(fabric, nu=MaterialProperty(0.49, "measured"))) == []


@pytest.mark.parametrize(
    ("source", "tag"),
    [
        ("datasheet", "datasheet"),
        ("Measured - lab 2026-03", "measured"),
        ("assumed - verify", "assumed"),
        ("assumed(typical)", "assumed"),
        ("datasheets", None),
        ("supplier", None),
        ("", None),
    ],
)
def test_source_tag(source: str, tag: str | None) -> None:
    assert source_tag(source) == tag


def test_version_0_library_file_is_upgraded(tmp_path: Path) -> None:
    """A file written before user fabrics existed keeps its rows and gains origins."""
    path = tmp_path / "old.sqlite"
    old = sqlite3.connect(path)
    new = FabricLibraryRepository()
    new.seed_example_data()
    new.add_fabric(make_fabric())
    columns = [c for c in new._connection.execute("PRAGMA table_info(fabrics)")]
    names = [str(c[1]) for c in columns if c[1] != "origin"]
    old.execute(
        "CREATE TABLE fabrics ("
        + ", ".join(
            f"{n} {'TEXT' if n.endswith(('source', 'id')) or n in ('name', 'color') else 'REAL'}"
            for n in names
        )
        + ")"
    )
    rows = new._connection.execute(f"SELECT {', '.join(names)} FROM fabrics").fetchall()
    old.executemany(
        f"INSERT INTO fabrics VALUES ({', '.join('?' for _ in names)})", [tuple(r) for r in rows]
    )
    old.commit()
    old.close()

    with FabricLibraryRepository(path) as upgraded:
        assert upgraded.fabrics() == new.fabrics()
        assert upgraded.origin("nomex") == "example"
        assert upgraded.origin("my_poly") == "user"
        version = upgraded._connection.execute("PRAGMA user_version").fetchone()[0]
        assert version == SCHEMA_VERSION


def test_newer_library_file_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "future.sqlite"
    conn = sqlite3.connect(path)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    conn.commit()
    conn.close()
    with pytest.raises(FabricLibraryError, match="Update EnvelopeLab"):
        FabricLibraryRepository(path)


def test_fabric_data_changes_with_any_value() -> None:
    fabric = make_fabric()
    assert fabric_data(fabric) == fabric_data(make_fabric())
    changed = dataclasses.replace(fabric, roll_width=MaterialProperty(1.61, "measured"))
    assert fabric_data(changed) != fabric_data(fabric)
    retagged = dataclasses.replace(fabric, roll_width=MaterialProperty(1.6, "assumed"))
    assert fabric_data(retagged) != fabric_data(fabric)


@given(
    areal_mass=st.floats(min_value=1.0, max_value=500.0),
    roll_width=st.floats(min_value=0.1, max_value=5.0),
    tag=st.sampled_from(["datasheet", "measured", "assumed"]),
)
def test_round_trip_is_lossless(areal_mass: float, roll_width: float, tag: str) -> None:
    fabric = make_fabric(
        areal_mass=MaterialProperty(areal_mass, f"{tag} - note"),
        roll_width=MaterialProperty(roll_width, tag),
    )
    library = FabricLibraryRepository()
    library.add_fabric(fabric)
    assert library.fabric(fabric.fabric_id) == fabric
