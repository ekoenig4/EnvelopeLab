"""GUI tests: Design ▸ Lift charts… (curves and units) and its use in the build pack."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from envelopelab.design.model import TaggedValue
from envelopelab.project.lift_chart_settings import LiftChartSettings
from envelopelab_app.lift_chart_dialog import LiftChartDialog
from envelopelab_app.main_window import MainWindow


def _dialog(qtbot: QtBot, settings: LiftChartSettings, units: str = "metric") -> LiftChartDialog:
    dialog = LiftChartDialog(settings, units)  # type: ignore[arg-type]
    qtbot.addWidget(dialog)
    return dialog


def test_dialog_shows_the_settings_in_metric(qtbot: QtBot) -> None:
    dialog = _dialog(qtbot, LiftChartSettings())
    assert dialog.altitudes.text() == "0, 1000, 2000, 3000"
    assert dialog.ambients.text() == "-10, 0, 10, 20, 30"
    assert dialog.isa.text() == "-15, 0, 15, 30"
    assert dialog.auto_load.isChecked() and not dialog.max_load.isEnabled()
    assert dialog.offset.value() == pytest.approx(20.0)
    assert dialog.source.currentText() == "assumed"
    assert dialog.settings() == LiftChartSettings()


def test_switching_to_english_converts_what_is_typed(qtbot: QtBot) -> None:
    dialog = _dialog(qtbot, LiftChartSettings())
    dialog.units.setCurrentIndex(1)
    assert dialog.unit_system() == "english"
    assert dialog.altitudes.text() == "0, 3280.8, 6561.7, 9842.5"
    assert dialog.ambients.text() == "14, 32, 50, 68, 86"
    assert dialog.isa.text() == "-27, 0, 27, 54"
    assert dialog.offset.value() == pytest.approx(36.0)
    # Unchanged values survive the round trip.
    settings = dialog.settings()
    assert settings is not None
    assert settings.altitudes == pytest.approx(LiftChartSettings().altitudes, abs=0.02)


def test_english_entry_is_stored_in_si(qtbot: QtBot) -> None:
    dialog = _dialog(qtbot, LiftChartSettings(), "english")
    dialog.altitudes.setText("0, 5,000, 10,000")
    dialog.ambients.setText("32; 59; 86")
    dialog.isa.setText("0")
    dialog.auto_load.setChecked(False)
    dialog.max_load.setValue(2000.0)
    dialog.offset.setValue(27.0)
    dialog.source.setCurrentText("measured")
    dialog.note.setText("crown sensor vs. mid-height logger, 2026-10 flights")
    settings = dialog.settings()
    assert settings is not None
    assert settings.altitudes == pytest.approx([0.0, 1524.0, 3048.0])
    assert settings.ambient_temperatures == pytest.approx([273.15, 288.15, 303.15])
    assert settings.max_load == pytest.approx(907.18474)
    assert settings.top_to_mean == TaggedValue(
        value=15.0, source="measured", note="crown sensor vs. mid-height logger, 2026-10 flights"
    )


def test_bad_entry_is_explained_and_blocks_ok(qtbot: QtBot) -> None:
    from PySide6.QtWidgets import QDialogButtonBox

    dialog = _dialog(qtbot, LiftChartSettings())
    ok = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)
    dialog.altitudes.setText("0, high")
    assert not ok.isEnabled() and "'high' is not a number" in dialog.error.text()
    dialog.altitudes.setText("0, 20000")
    assert not ok.isEnabled() and "between" in dialog.error.text()
    dialog.altitudes.setText("0, 0")
    assert "must differ" in dialog.error.text()
    dialog.altitudes.setText("500")
    assert ok.isEnabled() and dialog.error.text() == ""
    # A unit switch with a bad entry keeps the text and only relabels.
    dialog.ambients.setText("cold")
    dialog.units.setCurrentIndex(1)
    assert dialog.ambients.text() == "cold" and not ok.isEnabled()


def test_restore_defaults(qtbot: QtBot) -> None:
    custom = LiftChartSettings(altitudes=[500.0], max_load=800.0)
    dialog = _dialog(qtbot, custom)
    assert dialog.altitudes.text() == "500" and not dialog.auto_load.isChecked()
    dialog.defaults.click()
    assert dialog.settings() == LiftChartSettings()


def test_menu_dialog_sets_the_project_settings_with_undo(
    gore_window: MainWindow, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    custom = LiftChartSettings(altitudes=[250.0, 1250.0], isa_offsets=[5.0])
    monkeypatch.setattr(LiftChartDialog, "exec", lambda self: 1)
    monkeypatch.setattr(LiftChartDialog, "settings", lambda self: custom)
    design_menu = next(a for a in gore_window.menuBar().actions() if a.text() == "&Design")
    assert gore_window.lift_chart_action in design_menu.menu().actions()  # type: ignore[attr-defined]
    assert gore_window.lift_chart_dialog()
    session = gore_window.controller.session
    assert session is not None
    assert session.project.state.lift_chart == custom
    # The pack uses them.
    gore_window.export_build_pack(tmp_path / "pack", frozenset({"lift_chart"}))
    (path,) = (tmp_path / "pack").glob("*-lift-chart.csv")
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert {r["altitude_m"] for r in rows if r["solved_for"] == "load"} == {"250.0", "1250.0"}
    session.undo()
    assert session.project.state.lift_chart.is_default()


def test_preview_writes_a_pdf(gore_window: MainWindow) -> None:
    path = gore_window.preview_lift_chart(LiftChartSettings(altitudes=[0.0]))
    assert path is not None and path.read_bytes().startswith(b"%PDF")


def test_export_dialog_offers_the_curve_settings(gore_window: MainWindow, qtbot: QtBot) -> None:
    from PySide6.QtWidgets import QPushButton

    from envelopelab_app.export_dialog import ExportPackDialog

    calls: list[int] = []
    dialog = ExportPackDialog(gore_window, "/tmp/pack", lift_settings=lambda: calls.append(1))
    qtbot.addWidget(dialog)
    button = dialog.findChild(QPushButton, "packLiftSettings")
    assert button is not None
    button.click()
    assert calls == [1]
