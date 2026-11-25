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


# -- the Lift charts mode -------------------------------------------------------------------


def test_lift_charts_mode_shows_the_three_charts(gore_window: MainWindow) -> None:
    labels = [gore_window.mode_tabs.tabText(i) for i in range(gore_window.mode_tabs.count())]
    assert any(label.startswith("Lift charts") for label in labels)
    gore_window.set_mode("lift")
    assert not gore_window.sidebar_visible()  # a wide mode
    panel = gore_window.lift_charts
    assert panel.charts is not None
    assert panel.loading.plot is not None and len(panel.loading.plot.series) == 4
    assert panel.ceiling.plot is not None
    shown = [v for v in panel.temperatures if v.plot is not None]
    assert len(shown) == 4
    assert [panel.tabs.tabText(i) for i in range(panel.tabs.count())] == [
        "Maximum load",
        "Gross lift",
        "Stratification",
        "Top temperature",
        "Ceiling",
        "Theory",
    ]
    assert [v.plot is not None for v in panel.gross] == [True] * 4
    assert "assumed" in panel.status.text() and "not permitted" in panel.status.text()
    assert "not certified engineering software" in panel.notes.text()


def test_typing_redraws_at_once_and_saves_as_one_undo_step(gore_window: MainWindow) -> None:
    gore_window.set_mode("lift")
    panel = gore_window.lift_charts
    session = gore_window.controller.session
    assert session is not None
    panel.form.altitudes.setText("0, 1")
    panel.form.altitudes.setText("0, 15")
    panel.form.altitudes.setText("0, 1500")
    # Drawn at once, not yet saved.
    assert panel.loading.plot is not None
    assert [s.label for s in panel.loading.plot.series][1] == "1,500 m / 4,921 ft"
    assert [not v.isHidden() for v in panel.temperatures] == [True, True, False, False]
    assert session.project.state.lift_chart.is_default()
    assert panel.apply_pending()
    assert session.project.state.lift_chart.altitudes == [0.0, 1500.0]
    # One undo step brings the defaults back, in the form and the charts.
    session.undo()
    assert session.project.state.lift_chart.is_default()
    assert panel.form.altitudes.text() == "0, 1000, 2000, 3000"
    assert panel.loading.plot is not None and len(panel.loading.plot.series) == 4


def test_bad_entry_keeps_the_last_charts_and_saves_nothing(gore_window: MainWindow) -> None:
    gore_window.set_mode("lift")
    panel = gore_window.lift_charts
    before = panel.loading.plot
    panel.form.ambients.setText("cold")
    assert "'cold' is not a number" in panel.form.error.text()
    assert panel.loading.plot is before
    assert not panel.apply_pending()
    session = gore_window.controller.session
    assert session is not None and session.project.state.lift_chart.is_default()


def test_design_edits_redraw_the_charts(gore_window: MainWindow) -> None:
    gore_window.set_mode("lift")
    panel = gore_window.lift_charts
    assert panel.charts is not None
    old = panel.charts.inputs.fixed_mass
    session = gore_window.controller.session
    assert session is not None
    session.set_design_value(("operating", "payload_mass"), 77.0)
    assert panel.charts is not None
    temp = panel.temperatures[0].plot
    assert temp is not None and temp.vlines[0][0] == pytest.approx(77.0)
    assert panel.charts.inputs.fixed_mass == pytest.approx(old)


def test_units_are_remembered(gore_window: MainWindow) -> None:
    panel = gore_window.lift_charts
    panel.form.units.setCurrentIndex(1)
    assert panel.settings is not None
    assert panel.settings.value("lift_chart/units") == "english"
    assert panel.form.altitudes.text() == "0, 3280.8, 6561.7, 9842.5"


def test_export_pdf_from_the_tab(gore_window: MainWindow, tmp_path: Path) -> None:
    panel = gore_window.lift_charts
    path = panel.export_pdf(tmp_path / "charts")
    assert path == tmp_path / "charts.pdf"
    assert path.read_bytes().startswith(b"%PDF")
    assert (tmp_path / "charts.csv").read_text(encoding="utf-8").startswith("solved_for,")


def test_tab_without_a_design_says_why(window: MainWindow) -> None:
    panel = window.lift_charts
    assert panel.charts is None and not panel.form.isEnabled()
    assert "Open or create a design" in panel.loading.message


def test_gross_lift_charts_mark_where_the_crown_reaches_its_limit(
    gore_window: MainWindow,
) -> None:
    gore_window.set_mode("lift")
    panel = gore_window.lift_charts
    plot = panel.gross[0].plot
    assert plot is not None and plot.shade_right is not None
    assert "Gross lift vs crown temperature" in plot.title
    assert panel.charts is not None
    inputs = panel.charts.inputs
    assert plot.shade_right[0] == pytest.approx(inputs.top_limit.value - 273.15)
    assert plot.xlabel.startswith("Crown (top) temperature")


def test_theory_tab_states_the_equations_and_follows_the_offset(gore_window: MainWindow) -> None:
    gore_window.set_mode("lift")
    panel = gore_window.lift_charts
    text = panel.theory.toPlainText()
    assert "Gross lift (Archimedes)" in text
    assert "L = V (ρamb - ρint) g" in text
    assert "53.352 ft lbf/(lb °R)" in text
    assert "°R = °F + 459.67" in text
    assert "never less than 20 K below the top" in text
    # A measured offset typed in the form shows in the theory at once.
    panel.form.offset.setValue(12.0)
    panel.form.source.setCurrentText("measured")
    assert "never less than 12 K below the top" in panel.theory.toPlainText()
    assert "[measured" in panel.theory.toPlainText()


def test_stratification_tab_and_mean_model_control(gore_window: MainWindow) -> None:
    gore_window.set_mode("lift")
    panel = gore_window.lift_charts
    form = panel.form
    # Default: from the envelope's shape; the offset is a minimum.
    assert form.mean_model.currentData() == "envelope_shape"
    assert form.mouth.value() == pytest.approx(50.0) and form.mouth.isEnabled()
    assert form.offset_label.text() == "Minimum top minus mean"
    profile, pressure = (v.plot for v in panel.stratification)
    assert profile is not None and "Gas temperature by height" in profile.title
    assert pressure is not None and len(pressure.series) == 2
    assert "envelope's shape" in panel.theory.toPlainText()
    # A cooler mouth lowers the mean at the limit (more conservative).
    assert panel.charts is not None
    limit = panel.charts.inputs.top_limit.value
    before = panel.charts.inputs.mean_of(limit, 288.15)
    form.mouth.setValue(30.0)
    assert panel.charts is not None
    assert panel.charts.inputs.mean_of(limit, 288.15) < before
    # Fixed offset: the mouth fields are disabled and there is no profile to draw.
    form.mean_model.setCurrentIndex(1)
    assert not form.mouth.isEnabled()
    assert form.offset_label.text() == "Top minus mean temperature"
    assert all(v.plot is None for v in panel.stratification)
    assert "Fixed offset" in panel.stratification[0].message
    assert panel.apply_pending()
    session = gore_window.controller.session
    assert session is not None
    assert session.project.state.lift_chart.mean_model == "fixed_offset"
