"""Every field of a design can be changed in the GUI, and the reference-keeping editors work.

The coverage test walks the design schema: each field is either edited in the Properties
panel (and has an editor there when the section holds data), owned by a dedicated editor
that exists, or fixed for the design (schema version, envelope type). A new schema field
without an editor fails it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest
from pydantic import BaseModel

from envelopelab.design.model import DesignDocument
from envelopelab.io.shape_file import load_shape_file
from envelopelab.project.field_editing import field_info
from envelopelab_app.main_window import MainWindow
from envelopelab_app.panels.properties import EDITABLE_SECTIONS, OWNED, owner

ROOT = Path(__file__).resolve().parents[2]
SPECIAL = ROOT / "tests" / "fixtures" / "flat_chord_pattern" / "special.yaml"
#: Fields fixed for a design: what kind of document it is.
FIXED = {("schema_version",), ("envelope_type",)}


def schema_leaves(model: type[BaseModel], prefix: tuple[str, ...] = ()) -> list[tuple[str, ...]]:
    """Every field path of the schema (``*`` for list indices), sections expanded."""
    out: list[tuple[str, ...]] = []
    for name, spec in model.model_fields.items():
        key = spec.alias or name
        path = (*prefix, key)
        info = field_info(tuple(0 if p == "*" else p for p in path))
        if info.kind == "object" and info.model is not None:
            out += schema_leaves(info.model, path)
        elif info.kind == "objects" and info.model is not None:
            out += schema_leaves(info.model, (*path, "*"))
        else:
            out.append(path)
    return out


def data_leaves(data: Any, path: tuple[str | int, ...]) -> list[tuple[str | int, ...]]:
    info = field_info(path)
    if info.kind == "object" and isinstance(data, dict):
        return [p for k, v in data.items() for p in data_leaves(v, (*path, k))]
    if info.kind == "objects" and isinstance(data, list):
        return [p for i, v in enumerate(data) for p in data_leaves(v, (*path, i))]
    return [path]


def test_every_schema_field_has_a_home() -> None:
    owners = set(OWNED.values())
    for path in schema_leaves(DesignDocument):
        if path[:1] in FIXED or path in FIXED:
            continue
        concrete = tuple(0 if p == "*" else p for p in path)
        if owner(concrete) is not None:
            assert owner(concrete) in owners
            continue
        assert path[0] in EDITABLE_SECTIONS, f"{'/'.join(path)} has no editor"


def test_owned_fields_have_their_editors(gore_window: MainWindow) -> None:
    editor = gore_window.gore_editor
    widgets = {
        ("gores", "count"): editor.gore_count,
        ("gores", "meridian_profile_control_points"): editor.points_table,
        ("gores", "panel_rows"): editor.rows_table,
        ("gores", "loft"): editor.loft_table,
        ("gores", "crest_loft"): editor.crest_table,
        ("gores", "construction"): editor.construction,
        ("gores", "profile_interpolation"): editor.interpolation,
        ("gores", "profile_segments"): editor.points_table,
        ("zones",): gore_window.materials.zones,
    }
    for pattern, name in OWNED.items():
        if pattern[0] == "meta":
            assert name == "set when the design is saved"
            continue
        assert pattern in widgets, pattern


def test_every_field_of_a_full_design_has_a_properties_editor(window: MainWindow) -> None:
    design = load_shape_file(SPECIAL).design()
    session = window.new_project(design)
    window.rigging.buttons["add_red_line"].click()
    window.rigging.buttons["add_flying_wires"].click()
    window.rigging.buttons["add_scoop"].click()
    props = window.properties
    for section in ("features", "scale_variants", "seam_types"):
        window.controller.select(section)
        props.add_entry((section, len(session.design_value((section,)))))
    data = session.design.model_dump(by_alias=True, mode="json")
    for section in EDITABLE_SECTIONS:
        if data.get(section) is None:
            continue
        window.controller.select(section)
        for path in data_leaves(data[section], (section,)):
            if owner(path) is not None:
                continue
            assert path in props.editors, f"no editor for {'/'.join(map(str, path))}"


def test_zones_rename_add_and_remove_in_the_materials_panel(window: MainWindow) -> None:
    session = window.new_project(load_shape_file(SPECIAL).design())
    materials = window.materials
    assert materials.add_zone("trim")
    assert "trim" in session.design.zones
    assert not materials.add_zone("trim")  # refused: exists
    assert materials.remove_zone("trim")
    assert not materials.remove_zone("accent")  # refused: panel zone badge uses it
    row = list(session.design.zones).index("mouth")
    item = materials.zones.item(row, 0)
    assert item is not None
    item.setText("skirt")
    assert "skirt" in session.design.zones and "mouth" not in session.design.zones
    assert session.design.gores is not None
    assert session.design.gores.panel_rows[0].zone == "skirt"


def test_rows_are_renamed_and_zoned_in_the_gore_editor(window: MainWindow) -> None:
    session = window.new_project(load_shape_file(SPECIAL).design())
    editor = window.gore_editor
    name = editor.rows_table.item(5, 0)
    assert name is not None and name.text() == "E"
    name.setText("EQ")
    assert all(v.rows == ["EQ", "F"] for v in session.design.turning_vents)
    zone = editor.rows_table.item(2, 2)
    assert zone is not None
    zone.setText("mouth")
    assert session.design.gores is not None
    assert session.design.gores.panel_rows[2].zone == "mouth"
    # The pattern view's zone choice edits the same field.
    window.controller.select("row:B")
    patterns = window.patterns
    patterns.refresh()
    assert patterns.zone.currentData() == "mouth"
    patterns.zone.setCurrentIndex(0)
    patterns.zone.activated.emit(0)
    assert session.design.gores.panel_rows[2].zone is None


def test_single_marks_are_removed_in_the_pattern_view(gore_window: MainWindow) -> None:
    session = gore_window.controller.session
    assert session is not None and session.design.gores is not None
    letter = session.design.gores.panel_rows[1].letter
    gore_window.controller.select(f"row:{letter}")
    patterns = gore_window.patterns
    patterns._add_notch()
    patterns.notch_pos.setValue(0.25)
    patterns._add_notch()
    patterns.refresh()
    assert patterns.marks.count() == 2
    patterns.remove_mark("notches", 0)
    notches = session.patterns.row(letter).notches
    assert [n.position for n in notches] == [0.25]


def test_extra_feed_holes_in_the_shapes_panel(window: MainWindow) -> None:
    session = window.new_project(load_shape_file(SPECIAL).design())
    for shape in load_shape_file(SPECIAL).shapes(session.design):
        window.controller.edit("add_shape", shape)
    shapes = window.shapes
    shapes.select("blister")
    assert shapes.holes_table.rowCount() == 2
    assert shapes.add_feed_hole()
    assert shapes.holes_table.rowCount() == 3
    radius = shapes.holes_table.item(2, 3)
    assert radius is not None
    radius.setText("0.12")
    blister = shapes.spec("blister")
    assert blister is not None and blister.feed_holes[2].radius == 0.12
    assert shapes.remove_feed_hole(0)
    blister = shapes.spec("blister")
    assert blister is not None and len(blister.feed_holes) == 2


def test_lock_targets_are_typed_in_the_gore_editor(gore_window: MainWindow) -> None:
    session = gore_window.controller.session
    assert session is not None
    editor = gore_window.gore_editor
    outputs = gore_window.controller.outputs
    assert outputs is not None
    target = round(1.05 * outputs.volume, 1)
    editor.lock_values["volume"].setText(str(target))
    editor.lock_values["volume"].editingFinished.emit()
    assert session.project.locks.volume == target
    assert editor.locks["volume"].isChecked()
    outputs = gore_window.controller.outputs
    assert outputs is not None and abs(outputs.volume / target - 1.0) < 1e-3


def test_the_3d_view_follows_the_gore_and_pattern_edits(window: MainWindow) -> None:
    session = window.new_project(load_shape_file(SPECIAL).design())
    for shape in load_shape_file(SPECIAL).shapes(session.design):
        window.controller.edit("add_shape", shape)
    window.controller.shapes.wait(60_000)
    view = window.view3d
    view.refresh()
    labels = view.labels()
    assert "crest from the seam bows" in labels["design"]
    before = view.layers["design"].points.copy()
    # Panel zones are outlined, the blister's two extra feed holes drawn.
    assert "panel zones" in labels["marks"]
    assert len(view.layers["marks"].polylines["panel_zones"]) == 3
    assert "2 feed hole(s)" in labels["shape:blister"]
    # A crest-loft edit changes the drawn surface; straight seams flatten it.
    window.gore_editor.use_crest.click()
    view.refresh()
    assert "crest loft" in view.labels()["design"]
    crest = view.layers["design"].points.copy()
    assert not np.allclose(crest, before)
    window.gore_editor.straight_seams.click()
    view.refresh()
    assert "straight seams" in view.labels()["design"]
    flat = view.layers["design"].points
    assert np.max(np.linalg.norm(crest - flat, axis=1)) > 0.05
    # A tape path placed in the pattern view shows on every panel of the row.
    window.patterns.regenerate()
    window.controller.select("row:C")
    window.patterns.tape_y.setValue(1.0)
    window.patterns._add_tape()
    assert session.patterns.row("C").tape_paths
    view.refresh()
    assert "tape paths" in view.labels()["marks"]
    assert session.design.gores is not None
    assert len(view.layers["marks"].polylines["tape_paths"]) == session.design.gores.count


def test_taper_stations_follow_row_seams_in_the_gore_editor(window: MainWindow) -> None:
    from PySide6.QtWidgets import QComboBox

    session = window.new_project(load_shape_file(SPECIAL).design())
    editor = window.gore_editor
    editor.use_crest.click()  # default crest loft: stations 0, 0.5, 1
    combo = editor.crest_table.cellWidget(1, 2)
    assert isinstance(combo, QComboBox) and combo.currentData() is None
    index = combo.findData("E")
    combo.setCurrentIndex(index)
    combo.activated.emit(index)
    gores = session.design.gores
    assert gores is not None and gores.crest_loft is not None
    point = gores.crest_loft.taper[1]
    assert point.at_row == "E"
    heights = [r.finished_height for r in gores.panel_rows]
    assert point.station == pytest.approx(sum(heights[:5]) / sum(heights))
    # Making row B taller moves the station with the seam under E.
    height = editor.rows_table.item(2, 1)
    assert height is not None
    height.setText(f"{heights[2] + 0.3:.4f}")
    gores = session.design.gores
    assert gores is not None and gores.crest_loft is not None
    heights = [r.finished_height for r in gores.panel_rows]
    assert gores.crest_loft.taper[1].station == pytest.approx(sum(heights[:5]) / sum(heights))
    # Typing a station frees the point.
    station = editor.crest_table.item(1, 0)
    assert station is not None
    station.setText("0.45")
    gores = session.design.gores
    assert gores is not None and gores.crest_loft is not None
    assert gores.crest_loft.taper[1].at_row is None
    assert gores.crest_loft.taper[1].station == 0.45


def test_mouth_and_top_hole_diameters_are_locked_in_the_gore_editor(
    gore_window: MainWindow,
) -> None:
    session = gore_window.controller.session
    assert session is not None and session.design.gores is not None
    editor = gore_window.gore_editor
    top = round(session.design.gores.parachute_hole_diameter + 0.2, 3)
    editor.lock_values["top_diameter"].setText(str(top))
    editor.lock_values["top_diameter"].editingFinished.emit()
    assert session.project.locks.top_diameter == top
    assert editor.locks["top_diameter"].isChecked()
    gores = session.design.gores
    assert gores is not None and gores.parachute_hole_diameter == top
    assert 2.0 * gores.meridian_profile_control_points[-1].x == pytest.approx(top)
    editor.locks["mouth_diameter"].click()
    assert session.project.locks.mouth_diameter == pytest.approx(
        2.0 * gores.meridian_profile_control_points[0].x
    )
