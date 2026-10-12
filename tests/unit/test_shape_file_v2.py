"""Shape files, format version 2: cut span, rows, zones, openings, rigging, extends."""

from __future__ import annotations

import copy
import math
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import yaml

from envelopelab.io.shape_file import (
    ShapeFileError,
    load_shape_file,
    parse_shape_file,
    resolve_extends,
)
from envelopelab.project.gore_design import design_profile, panel_rows, seam_mismatches
from envelopelab.project.model import PatternSet

PATH = Path("cut.yaml")
#: A cut profile: mouth radius 0.1 T, widest 0.3 T, top 0.12 T (fractions of the tape).
STATIONS = [[0.0, 0.1], [0.25, 0.22], [0.5, 0.3], [0.75, 0.25], [1.0, 0.12]]


def _raw(**changes: Any) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "format": "envelopelab.shape",
        "format_version": 2,
        "name": "cut",
        "profile": {
            "source": "measured",
            "span": "cut",
            "interpolation": "linear",
            "stations": copy.deepcopy(STATIONS),
        },
        "design": {
            "construction": "flat_chord",
            "hold": {"tape_length": "20 m"},
            "gore_count": 16,
            "seam_allowance": "25 mm",
        },
        "rows": [
            {"name": "NOMEX", "top": 0.25, "zone": "nomex", "bow": ["0 mm", "2 mm"]},
            {"name": "B", "top": 0.5, "bow": ["2 mm", "5 mm"]},
            {"name": "C", "top": 0.75, "bow": ["5 mm", "3 mm"]},
            {"name": "D", "bow": ["3 mm", "0 mm"]},
        ],
        "zones": {"body": "ripstop_nylon", "nomex": "nomex"},
        "loft": {"crest": {"fraction": 0.02, "taper": [[0.0, 0.0], [0.5, 1.0], [1.0, 0.0]]}},
        "openings": {"seal_overlap": "300 mm"},
    }
    raw.update(changes)
    return raw


def test_cut_span_holds_the_mouth_and_top_and_scales_by_the_tape_length() -> None:
    sf = parse_shape_file(_raw(), PATH)
    assert sf.span == "cut"
    assert sf.hold == {"tape_length": 20.0, "mouth_station": 0.0, "top_station": 1.0}
    solution = sf.solve()
    assert solution.converged
    assert solution.values["tape_length"] == pytest.approx(20.0, abs=1e-6)
    assert solution.values["mouth_diameter"] == pytest.approx(2 * 0.1 * 20.0, abs=1e-9)
    assert solution.values["top_diameter"] == pytest.approx(2 * 0.12 * 20.0, abs=1e-9)
    # Straight tape segments: dz = sqrt(ds^2 - dr^2) per interval.
    s, r = np.array(STATIONS).T
    height = 20.0 * np.sum(np.sqrt(np.diff(s) ** 2 - np.diff(r) ** 2))
    assert solution.values["height"] == pytest.approx(height, rel=1e-9)


def test_design_carries_rows_zones_bows_and_openings() -> None:
    sf = parse_shape_file(_raw(), PATH)
    design = sf.design()
    gores = design.gores
    assert gores is not None
    assert gores.construction == "flat_chord"
    assert gores.profile_interpolation == "linear"
    assert [r.letter for r in gores.panel_rows] == ["NOMEX", "B", "C", "D"]
    assert [r.zone for r in gores.panel_rows] == ["nomex", None, None, None]
    assert [r.finished_height for r in gores.panel_rows] == pytest.approx([5.0] * 4)
    assert gores.panel_rows[1].bow_top == pytest.approx(0.005)
    assert gores.crest_loft is None  # measured bows win
    assert gores.seal_overlap == pytest.approx(0.3)
    assert design.zones == {"body": "ripstop_nylon", "nomex": "nomex"}
    rows = panel_rows(design, PatternSet(), design_profile(design))
    assert [(r.bottom_bow, r.top_bow) for r in rows][1] == pytest.approx((0.002, 0.005))
    # Rows meet at the profile corners: each side is its straight tape segment, and the
    # corners lie a flat chord apart.
    assert rows[0].side_length == pytest.approx(0.25 * 20.0, rel=1e-9)
    assert rows[0].top_width == pytest.approx(2 * 0.22 * 20.0 * math.sin(math.pi / 16))
    assert design.parachute is not None and design.rigging.flying_wires is not None


def test_measured_bows_scale_with_the_design() -> None:
    sf = parse_shape_file(_raw(), PATH)
    hold = {**sf.hold, "tape_length": 40.0}
    design = sf.design(sf.solve(hold))
    assert design.gores is not None
    assert design.gores.panel_rows[1].bow_top == pytest.approx(0.010)


def test_crest_seams_on_request() -> None:
    sf = parse_shape_file(_raw(), PATH)
    design = sf.design(seams="crest")
    assert design.gores is not None
    assert design.gores.crest_loft is not None
    assert all(r.bow_top is None for r in design.gores.panel_rows)
    rows = panel_rows(design, PatternSet())
    assert rows[1].top_bow > 0.0
    assert seam_mismatches(rows, PatternSet()) == []


def test_crest_seams_need_a_crest_loft() -> None:
    raw = _raw()
    del raw["loft"]
    with pytest.raises(ShapeFileError, match="no crest loft"):
        parse_shape_file(raw, PATH).design(seams="crest")


def test_rows_without_bows_and_crest_loft_generate_bows() -> None:
    raw = _raw()
    for row in raw["rows"]:
        del row["bow"]
    design = parse_shape_file(raw, PATH).design()
    assert design.gores is not None and design.gores.crest_loft is not None


def test_rigging_section_overrides_the_defaults() -> None:
    rigging = {
        "parachute": {"panel_count": 16, "shroud_attachment": "1.2 m"},
        "turning_vents": [
            {"name": "left", "seam": 4, "rows": ["B", "C"], "direction": "clockwise"}
        ],
        "scoop": {"first_gore": 2, "gore_count": 5, "height": "1.5 m"},
        "crown_line": "crown line 31 m",
    }
    design = parse_shape_file(_raw(rigging=rigging), PATH).design()
    assert design.parachute is not None
    assert design.parachute.panel_count == 16
    assert design.parachute.shroud_attachment == pytest.approx(1.2)
    assert [v.seam for v in design.turning_vents] == [4]
    assert design.turning_vents[0].rows == ["B", "C"]
    assert design.scoop is not None and design.scoop.height == pytest.approx(1.5)
    assert design.rigging.crown_line == "crown line 31 m"


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"rigging": {"winch": {}}}, "unknown section"),
        ({"rigging": {"parachute": {"shroud_attachment": 1.2}}}, "give a unit"),
        ({"rigging": {"parachute": {"panel_count": 2}}}, "rigging"),
        ({"rigging": {"turning_vents": {"seam": 3}}}, "a list of vents"),
        ({"openings": {"hole": "5 m"}}, "openings"),
        ({"zones": ["body"]}, "zones"),
        ({"colour": "green"}, "unknown key"),
    ],
)
def test_v2_sections_name_the_key_in_errors(change: dict[str, Any], message: str) -> None:
    with pytest.raises(ShapeFileError, match=message):
        parse_shape_file(_raw(**change), PATH).design()


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ([{"name": "A", "top": 0.5}, {"name": "B", "top": 0.4}, {"name": "C"}], "increase"),
        ([{"name": "A"}, {"name": "B"}], "top: required"),
        ([{"name": "A", "top": 0.5}, {"name": "A"}], "unique"),
        ([{"name": "TOOLONGNAME", "top": 0.5}, {"name": "B"}], "1 to 8"),
        ([{"name": "A", "top": 0.5, "bow": ["1 mm", "1 mm"]}, {"name": "B"}], "every row"),
        ([{"name": "A", "top": 0.5, "zone": "silk"}, {"name": "B"}], "not in zones"),
        ([{"name": "A", "top": "equator"}, {"name": "B"}], "unknown station"),
    ],
)
def test_row_errors(rows: list[dict[str, Any]], message: str) -> None:
    with pytest.raises(ShapeFileError, match=message):
        parse_shape_file(_raw(rows=rows), PATH).design()


def test_rows_outside_the_cut_are_refused() -> None:
    raw = _raw()
    raw["profile"]["span"] = "poles"
    raw["profile"]["stations"] = [[0.0, 0.0], [0.25, 0.2], [0.5, 0.3], [0.75, 0.2], [1.0, 0.0]]
    raw["design"]["hold"] = {"gore_length": "20 m", "mouth_station": 0.3, "top_station": 0.9}
    with pytest.raises(ShapeFileError, match="between the mouth and the top opening"):
        parse_shape_file(raw, PATH).design()


def test_cut_span_refuses_the_nominal_volume() -> None:
    raw = _raw()
    raw["design"]["hold"] = {"nominal_volume": "2600 m^3"}
    with pytest.raises(ShapeFileError, match="no closed shape"):
        parse_shape_file(raw, PATH)


def test_construction_and_loft_must_agree() -> None:
    raw = _raw()
    raw["design"]["construction"] = "lobe"
    for row in raw["rows"]:
        del row["bow"]
    with pytest.raises(ShapeFileError, match="needs design.construction: flat_chord"):
        parse_shape_file(raw, PATH)
    raw["loft"] = {"ratio": 1.05}
    raw["design"]["construction"] = "flat_chord"
    with pytest.raises(ShapeFileError, match="lofted by 'crest'"):
        parse_shape_file(raw, PATH)


def test_version_1_files_cannot_use_v2_sections() -> None:
    raw = _raw(format_version=1)
    with pytest.raises(ShapeFileError, match="needs format_version 2"):
        parse_shape_file(raw, PATH)


def _write(path: Path, data: dict[str, Any]) -> Path:
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def test_extends_merges_over_the_base(tmp_path: Path) -> None:
    base = _raw(panel_zones=[{"name": "applique", "row": "B", "gores": [1], "zone": "nomex"}])
    base["published"] = {"volume": "100 m^3"}
    _write(tmp_path / "base.yaml", base)
    child = {
        "format": "envelopelab.shape",
        "format_version": 2,
        "extends": "base.yaml",
        "name": "child",
        "zones": {"black": "ripstop_nylon"},
        "panel_zones": [
            {"name": "applique", "row": "C", "gores": [2, 3], "zone": "black"},
            {"name": "doubler", "row": "D", "gores": [4], "zone": "body"},
        ],
        "published": {"rim": "1 m"},
    }
    sf = load_shape_file(_write(tmp_path / "child.yaml", child))
    assert sf.name == "child"
    assert sf.zones == {"body": "ripstop_nylon", "nomex": "nomex", "black": "ripstop_nylon"}
    assert [z["name"] for z in sf.panel_zones] == ["applique", "doubler"]
    assert sf.panel_zones[0]["row"] == "C"
    assert sf.published == {"rim": "1 m"}  # the child's own regression data only
    assert [r.name for r in sf.rows] == ["NOMEX", "B", "C", "D"]
    design = sf.design()
    assert design.gores is not None and len(design.gores.panel_zones) == 2


def test_extends_cycle_and_missing_base(tmp_path: Path) -> None:
    a = _raw(extends="b.yaml")
    b = _raw(extends="a.yaml")
    _write(tmp_path / "a.yaml", a)
    _write(tmp_path / "b.yaml", b)
    with pytest.raises(ShapeFileError, match="cycle"):
        load_shape_file(tmp_path / "a.yaml")
    _write(tmp_path / "c.yaml", _raw(extends="missing.yaml"))
    with pytest.raises(ShapeFileError, match="not found"):
        load_shape_file(tmp_path / "c.yaml")


def test_extends_needs_named_entries_to_merge(tmp_path: Path) -> None:
    _write(tmp_path / "base.yaml", _raw(panel_zones=[{"row": "B", "gores": [1], "zone": "x"}]))
    child = {
        "extends": "base.yaml",
        "panel_zones": [{"name": "a", "row": "B", "gores": [2], "zone": "x"}],
    }
    with pytest.raises(ShapeFileError, match="needs a name"):
        resolve_extends(child, tmp_path / "child.yaml")


def test_extends_keeps_the_format_version(tmp_path: Path) -> None:
    _write(tmp_path / "base.yaml", _raw())
    child = {"extends": "base.yaml", "format_version": 1}
    with pytest.raises(ShapeFileError, match="same format_version"):
        resolve_extends(child, tmp_path / "child.yaml")


def test_smalley_version_1_file_is_unchanged() -> None:
    sf = load_shape_file("tests/fixtures/smalley_90k/shape.yaml")
    assert sf.format_version == 1
    assert sf.span == "poles" and sf.rows == () and sf.rigging == {}
    assert sf.shape.interpolation == "spline" and sf.shape.construction == "lobe"
