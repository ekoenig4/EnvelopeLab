from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from envelopelab.io.shape_file import (
    ShapeFileError,
    format_quantity,
    parse_quantity,
    parse_shape_file,
)


@pytest.mark.parametrize(
    ("text", "dimension", "expected"),
    [
        ("2 in", "length", 0.0508),
        ("90.081 ft", "length", 27.4566888),
        ("6 m", "length", 6.0),
        ("25mm", "length", 0.025),
        ("92000 ft^3", "volume", 92000 * 0.3048**3),
        ("2600 m^3", "volume", 2600.0),
        (0.14, "fraction", 0.14),
    ],
)
def test_parse_quantity_converts_to_si(text: object, dimension: Any, expected: float) -> None:
    assert parse_quantity(text, dimension) == pytest.approx(expected, rel=1e-5)


@pytest.mark.parametrize(
    ("text", "dimension", "message"),
    [
        (6.0, "length", "give a unit"),
        ("6 ft^3", "length", "not a length unit"),
        ("six m", "length", "cannot read"),
        (True, "fraction", "expected a number"),
    ],
)
def test_parse_quantity_refuses_missing_or_wrong_units(
    text: object, dimension: Any, message: str
) -> None:
    with pytest.raises(ShapeFileError, match=message):
        parse_quantity(text, dimension)


def test_format_quantity_round_trips() -> None:
    assert format_quantity(0.0508, "in") == "2 in"
    assert parse_quantity(format_quantity(2605.0, "ft^3"), "volume") == pytest.approx(2605.0)


def _raw() -> dict[str, Any]:
    return {
        "format": "envelopelab.shape",
        "format_version": 1,
        "name": "cone-ish",
        "profile": {
            "source": "assumed",
            "stations": [[0.0, 0.0], [0.25, 0.2], [0.5, 0.3], [0.75, 0.2], [1.0, 0.0]],
        },
        "stations": {"mouth": 0.1, "vent": 0.9},
        "design": {
            "hold": {"gore_length": "20 m", "mouth_station": "mouth", "top_station": 0.85},
            "gore_count": 12,
            "seam_allowance": "1 in",
        },
    }


def test_parse_shape_file_resolves_station_names_and_units() -> None:
    sf = parse_shape_file(_raw(), Path("cone.yaml"))
    assert sf.hold == {"gore_length": 20.0, "mouth_station": 0.1, "top_station": 0.85}
    assert sf.seam_allowance == pytest.approx(0.0254)
    assert sf.solve().converged


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        (lambda r: r.update(format="other"), "format must be"),
        (lambda r: r.update(format_version=2), "format_version"),
        (lambda r: r["profile"].update(source="guess"), "profile.source"),
        (lambda r: r["profile"].update(stations=[[0.0], [1.0, 0.0]]), r"\[s, r\]"),
        (lambda r: r["design"]["hold"].update(gore_length=20), "give a unit"),
        (lambda r: r["design"]["hold"].update(mouth_station="neck"), "unknown station"),
        (lambda r: r["design"]["hold"].update(width="1 m"), "unknown quantity"),
        (lambda r: r.pop("design"), "missing key design"),
    ],
)
def test_parse_shape_file_errors_name_the_key(edit: Any, message: str) -> None:
    raw = _raw()
    edit(raw)
    with pytest.raises(ShapeFileError, match=message):
        parse_shape_file(raw, Path("cone.yaml"))
