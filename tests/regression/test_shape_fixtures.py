"""Shape-file fixtures against their source spreadsheets.

The spreadsheet is read with the standard library (an ``.xlsx`` file is a zip of XML
parts); its cached cell values are what the spreadsheet computed when it was saved.
"""

from __future__ import annotations

import math
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import pytest

from envelopelab.io.shape_file import load_shape_file, parse_quantity
from envelopelab.project.gore_design import design_profile
from envelopelab.project.shape_family import shape_design, station_points

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "smalley_90k"
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
FT, INCH = 0.3048, 0.0254


def read_xlsx_values(path: Path) -> dict[str, float | str]:
    """Cached values of the first sheet, by cell reference (``"B10"``)."""
    with zipfile.ZipFile(path) as z:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in z.namelist():
            root = ElementTree.fromstring(z.read("xl/sharedStrings.xml"))
            shared = ["".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t")) for si in root]
        sheet = ElementTree.fromstring(z.read("xl/worksheets/sheet1.xml"))
    cells: dict[str, float | str] = {}
    for c in sheet.iter(f"{{{NS['m']}}}c"):
        v = c.find("m:v", NS)
        if v is None or v.text is None:
            continue
        cells[c.attrib["r"]] = shared[int(v.text)] if c.attrib.get("t") == "s" else float(v.text)
    return cells


CELLS = read_xlsx_values(FIXTURE / "source" / "Smalley_90K.xlsx")
SHAPE_FILE = load_shape_file(FIXTURE / "shape.yaml")
ROWS = range(10, 61)  # station rows, s = 1 (top) down to s = 0
LABELS = {
    "Mouth": "mouth",
    "Equator": "equator",
    "Chute ties": "chute_ties",
    "Parachute Over lap": "parachute_overlap",
    "Vent Openig": "vent",
}


def test_profile_table_is_the_spreadsheet_table() -> None:
    sheet = sorted((float(CELLS[f"A{i}"]), float(CELLS[f"B{i}"])) for i in ROWS)
    shape = SHAPE_FILE.shape
    assert len(sheet) == shape.s.size == 51
    for (s, r), s_file, r_file in zip(sheet, shape.s, shape.r, strict=True):
        assert s_file == pytest.approx(s, abs=1e-12)
        assert r_file == r


def test_named_stations_are_the_spreadsheet_labels() -> None:
    labelled = {
        LABELS[str(CELLS[f"I{i}"])]: float(CELLS[f"A{i}"]) for i in ROWS if f"I{i}" in CELLS
    }
    assert labelled == pytest.approx(dict(SHAPE_FILE.shape.stations), abs=1e-12)


def test_design_inputs_and_published_values_are_the_spreadsheet_ones() -> None:
    pub = SHAPE_FILE.published
    assert SHAPE_FILE.hold["nominal_volume"] == pytest.approx(float(CELLS["C3"]) * FT**3)
    assert SHAPE_FILE.gore_count == CELLS["C5"]
    assert parse_quantity(pub["seam_allowance"], "length") == pytest.approx(
        float(CELLS["C4"]) * INCH
    )
    # Cut half gore = sewn half gore + 2 x SEAM ALLOWANCE (spreadsheet column H).
    assert SHAPE_FILE.seam_allowance == pytest.approx(2 * float(CELLS["C4"]) * INCH)
    assert float(pub["volume_coefficient"]["value"]) == pytest.approx(
        float(CELLS["C3"]) / float(CELLS["G4"]) ** 3, rel=1e-12
    )
    assert parse_quantity(pub["gore_length"], "length") == pytest.approx(
        float(CELLS["G4"]) * FT, abs=1e-4
    )
    rows = {LABELS[str(CELLS[f"I{i}"])]: i for i in ROWS if f"I{i}" in CELLS}
    for name, values in pub["stations"].items():
        i = rows[name]
        assert parse_quantity(values["radius"], "length") == pytest.approx(
            float(CELLS[f"D{i}"]) * FT, abs=1e-4
        )
        assert parse_quantity(values["sewn_half_gore"], "length") == pytest.approx(
            float(CELLS[f"G{i}"]) * INCH, abs=1e-5
        )
        assert parse_quantity(values["cut_half_gore"], "length") == pytest.approx(
            float(CELLS[f"H{i}"]) * INCH, abs=1e-5
        )


def test_solved_design_reproduces_every_spreadsheet_gore_width() -> None:
    """All 51 stations: sewn and cut half-gore widths within 0.1 % (geometry default)."""
    solution = SHAPE_FILE.solve()
    assert solution.converged, solution.message
    params = solution.parameters
    shape = SHAPE_FILE.shape
    for i in ROWS:
        r = shape.point(float(CELLS[f"A{i}"]))[0] * params.gore_length
        sewn = math.pi * r / params.gore_count
        assert r == pytest.approx(float(CELLS[f"D{i}"]) * FT, rel=1e-3, abs=1e-9)
        assert sewn == pytest.approx(float(CELLS[f"G{i}"]) * INCH, rel=1e-3, abs=1e-9)
        assert sewn + params.seam_allowance == pytest.approx(float(CELLS[f"H{i}"]) * INCH, rel=1e-3)


def test_holding_the_spreadsheet_gore_length_cuts_its_gores_exactly() -> None:
    hold = dict(SHAPE_FILE.hold)
    del hold["nominal_volume"]
    hold["gore_length"] = float(CELLS["G4"]) * FT
    solution = SHAPE_FILE.solve(hold)
    assert solution.converged
    for p in station_points(SHAPE_FILE.shape, solution.parameters):
        i = next(i for i in ROWS if LABELS.get(str(CELLS.get(f"I{i}"))) == p.name)
        assert p.radius == pytest.approx(float(CELLS[f"D{i}"]) * FT, abs=1e-6)


def test_fixture_design_document() -> None:
    solution = SHAPE_FILE.solve()
    doc = shape_design(SHAPE_FILE.name, SHAPE_FILE.shape, solution, row_count=12)
    assert doc.gores is not None
    assert doc.gores.count == 20
    assert design_profile(doc).volume == pytest.approx(
        solution.values["envelope_volume"], rel=1e-12
    )
    # Parachute seal overlap: tape distance from the overlap station to the vent.
    assert doc.gores.seal_overlap == pytest.approx(0.02 * solution.parameters.gore_length)
    assert re.fullmatch(r"[0-9a-f]{64}", doc.meta.content_hash or "")
