"""Shared fabric library in the GUI: create a fabric once, use it in every design."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings
from pytestqt.qtbot import QtBot

from envelopelab.materials.repository import Fabric
from envelopelab.project.gore_design import zone_areal_masses
from envelopelab_app.dialogs import FabricDialog, format_value, join_source, split_source
from envelopelab_app.main_window import MainWindow
from envelopelab_app.panels.materials import MaterialsPanel
from envelopelab_app.wizard import NewDesignWizard

from .gui_support import GORE_PROJECT, make_window
from .test_gui_workflows import fake_run

VALUES = {
    "areal_mass": "61",
    "warp_tensile": "900",
    "weft_tensile": "870",
    "tear": "25",
    "seam_efficiency": "0.8",
    "e_warp": "1.4e9",
    "e_weft": "1.3e9",
    "g": "5e8",
    "nu": "0.3",
    "porosity": "9",
    "max_service_temperature": "130",
    "roll_width": "1.52",
    "cost": "9.5",
}


def fill(dialog: FabricDialog, fabric_id: str, **values: str) -> None:
    """Fill every field of the form (measured values, with a note on the areal mass)."""
    dialog.fabric_id.setText(fabric_id)
    dialog.name.setText("Club polyester")
    dialog.color.value.setText("#2050c0")
    dialog.color.tag.setCurrentText("measured")
    for name, text in {**VALUES, **values}.items():
        field = dialog.fields[name]
        field.value.setText(text)
        field.tag.setCurrentText("measured")
    dialog.fields["areal_mass"].note.setText("coupon 2026-09")


def answer_dialogs(
    monkeypatch: pytest.MonkeyPatch, fabric_id: str = "club_poly", **values: str
) -> list[FabricDialog]:
    """Make every fabric dialog of the panel fill itself in and press OK."""
    shown: list[FabricDialog] = []

    def run(_panel: MaterialsPanel, dialog: FabricDialog) -> Fabric | None:
        shown.append(dialog)
        if dialog.mode != "edit":
            fill(dialog, fabric_id, **values)
        else:
            for name, text in values.items():
                dialog.fields[name].value.setText(text)
        dialog.try_accept()
        return dialog.result_fabric()

    monkeypatch.setattr(MaterialsPanel, "run_dialog", run)
    return shown


def test_library_file_lives_outside_designs(window: MainWindow, tmp_path: Path) -> None:
    library = window.controller.fabrics
    assert library.path == tmp_path / "materials.sqlite"
    assert library.path.is_file()
    assert str(library.path) in window.materials.library_label.text()
    assert {"nomex", "polyester", "ripstop_nylon"} <= library.known_fabric_ids()
    window.materials.select_fabric("nomex")
    assert window.materials.duplicate_button.isEnabled()
    assert not window.materials.edit_button.isEnabled()
    assert not window.materials.delete_button.isEnabled()
    assert not window.materials.edit_selected()


def test_fabric_created_once_is_available_in_other_designs(
    qtbot: QtBot, window: MainWindow, settings: QSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    answer_dialogs(monkeypatch)
    assert window.materials.new_fabric()
    fabric = window.controller.fabrics.fabric("club_poly")
    assert fabric is not None
    assert fabric.areal_mass.value == 61.0
    assert fabric.areal_mass.source == "measured - coupon 2026-09"
    assert window.materials.selected_fabric_id() == "club_poly"
    assert window.controller.fabrics.is_editable("club_poly")

    # Another window (another design, or the next start of the app) sees the fabric...
    other = make_window(qtbot, settings)
    assert other.controller.fabrics.fabric("club_poly") == fabric
    wizard = NewDesignWizard(other.controller.fabrics, other)
    qtbot.addWidget(wizard)
    assert "club_poly" in [wizard.fabric.itemText(i) for i in range(wizard.fabric.count())]
    # ...and a design opened there can use it for a zone.
    session = other.open_project(GORE_PROJECT)
    assert session is not None
    zone = next(iter(session.design.zones))
    other.controller.set_value(("zones", zone), "club_poly")
    assert session.design.zones[zone] == "club_poly"
    masses = zone_areal_masses(session.design, other.controller.fabrics)
    assert masses[zone].value == pytest.approx(0.061)
    assert masses[zone].source == "measured - coupon 2026-09"


def test_invalid_fabric_is_not_saved(window: MainWindow, qtbot: QtBot) -> None:
    dialog = window.materials.make_dialog("new")
    qtbot.addWidget(dialog)
    fill(dialog, "bad", areal_mass="heavy", seam_efficiency="1.5")
    dialog.fields["tear"].tag.setCurrentText("assumed")
    dialog.color.value.setText("not-a-colour")
    dialog.try_accept()
    assert dialog.result_fabric() is None
    text = dialog.problems.text()
    assert "Areal mass: 'heavy' is not a number" in text
    assert "seam efficiency: 1.5 must be > 0 and <= 1" in text
    assert "not a colour" in text
    assert "not finite" not in text  # the parse error is not reported twice
    # Reusing an id already in the library is refused before anything is written.
    duplicate = window.materials.make_dialog("new")
    qtbot.addWidget(duplicate)
    fill(duplicate, "nomex")
    duplicate.try_accept()
    assert duplicate.result_fabric() is None
    assert "already in the library" in duplicate.problems.text()


def test_duplicate_example_then_edit_marks_results_stale(
    gore_window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = gore_window
    session = w.controller.session
    assert session is not None
    zone, used = next(iter(session.design.zones.items()))
    w.materials.select_fabric(used)
    shown = answer_dialogs(monkeypatch, fabric_id="my_copy")
    assert w.materials.duplicate_selected()
    assert shown[-1].mode == "duplicate"
    assert shown[-1].fabric_id.text() == "my_copy"
    w.controller.set_value(("zones", zone), "my_copy")
    record, arrays = fake_run(session)
    session.add_run(record, arrays)
    assert w.controller.run_status(record) == "current"
    outputs = w.controller.outputs
    assert outputs is not None and outputs.envelope_mass is not None
    mass_before = outputs.envelope_mass
    unsaved_before = session.unsaved_groups()
    history_before = session.stack.history()

    shown = answer_dialogs(monkeypatch, areal_mass="75")
    w.materials.select_fabric("my_copy")
    assert w.materials.edit_selected()
    assert [d.mode for d in shown] == ["edit"]
    fabric = w.controller.fabrics.fabric("my_copy")
    assert fabric is not None and fabric.areal_mass.value == 75.0
    # The run was built from the old values: stale. The design file itself is unchanged.
    assert w.controller.run_status(record) == "stale"
    assert session.unsaved_groups() == unsaved_before
    assert session.stack.history() == history_before
    assert "stale" in w.statusBar().currentMessage()
    outputs = w.controller.outputs
    assert outputs is not None and outputs.envelope_mass is not None
    assert outputs.envelope_mass > mass_before  # live outputs use the new areal mass


def test_delete_user_fabric_after_confirmation(
    gore_window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = gore_window
    answer_dialogs(monkeypatch, fabric_id="to_delete")
    assert w.materials.new_fabric()
    asked: list[str] = []

    def answer(reply: bool) -> None:
        def confirm(_panel: MaterialsPanel, _title: str, text: str) -> bool:
            asked.append(text)
            return reply

        monkeypatch.setattr(MaterialsPanel, "confirm", confirm)

    answer(False)
    w.materials.select_fabric("to_delete")
    assert not w.materials.delete_selected()
    assert w.controller.fabrics.fabric_exists("to_delete")
    answer(True)
    assert w.materials.delete_selected()
    assert not w.controller.fabrics.fabric_exists("to_delete")
    assert "Other designs that use it will show it as missing" in asked[-1]


def test_missing_fabric_is_shown_as_missing(gore_window: MainWindow) -> None:
    w = gore_window
    session = w.controller.session
    assert session is not None
    zone = next(iter(session.design.zones))
    w.controller.set_value(("zones", zone), "someone_elses_fabric")
    combo = w.materials.zones.cellWidget(0, 1)
    assert combo is not None
    assert "not in your fabric library" in combo.toolTip()


def test_unreadable_library_falls_back_with_a_warning(
    qtbot: QtBot, settings: QSettings, tmp_path: Path
) -> None:
    broken = tmp_path / "broken.sqlite"
    broken.write_bytes(b"this is not a database" * 100)
    settings.setValue("preferences/material_library", str(broken))
    settings.sync()
    w = make_window(qtbot, settings)
    assert w.controller.library_error is not None
    assert str(broken) in w.controller.library_error
    assert "not saved" in w.materials.library_label.text()
    assert w.controller.fabrics.path is None
    assert w.controller.fabrics.fabric_exists("ripstop_nylon")
    assert broken.read_bytes().startswith(b"this is not a database")  # left untouched


@pytest.mark.parametrize(
    ("source", "parts"),
    [
        ("assumed - verify", ("assumed", "verify")),
        ("datasheet", ("datasheet", "")),
        ("measured: lab 3", ("measured", "lab 3")),
        ("supplier said", ("assumed", "supplier said")),
    ],
)
def test_source_split_and_join(source: str, parts: tuple[str, str]) -> None:
    assert split_source(source) == parts
    tag, note = parts
    assert split_source(join_source(tag, note)) == parts


def test_edit_without_changes_keeps_every_value_exactly(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch, qtbot: QtBot
) -> None:
    answer_dialogs(monkeypatch, areal_mass="61.23456789012", e_warp="1234567891.5")
    assert window.materials.new_fabric()
    stored = window.controller.fabrics.fabric("club_poly")
    assert stored is not None
    dialog = window.materials.make_dialog("edit", stored)
    qtbot.addWidget(dialog)
    dialog.try_accept()
    assert dialog.result_fabric() == stored


def test_comma_is_not_read_as_a_decimal_point(window: MainWindow, qtbot: QtBot) -> None:
    dialog = window.materials.make_dialog("new")
    qtbot.addWidget(dialog)
    fill(dialog, "comma", areal_mass="1,200")
    dialog.try_accept()
    assert dialog.result_fabric() is None
    assert "Areal mass: '1,200' is not a number" in dialog.problems.text()


@pytest.mark.parametrize("value", [42.0, 0.1, 1.2e9, 61.23456789012, 1e-7, -273.0])
def test_format_value_round_trips(value: float) -> None:
    assert float(format_value(value)) == value
