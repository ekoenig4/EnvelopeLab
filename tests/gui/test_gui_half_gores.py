"""Changing the gore count and cutting half gores after the project started, to fit the
print roll (Shape mode's Panels and print roll box, the rows table, Patterns)."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton

from envelopelab_app.main_window import MainWindow


def _halves(window: MainWindow) -> list[bool]:
    design = window.controller.design
    assert design is not None and design.gores is not None
    return [r.half_gore for r in design.gores.panel_rows]


def test_the_panels_box_changes_the_gore_count_and_half_gores(gore_window: MainWindow) -> None:
    gore_window.mode_tabs.setCurrentIndex(0)  # Shape
    editor = gore_window.gore_editor
    controller = gore_window.controller
    # The fixture's panels are wider than a 60 in roll.
    assert "LARGER THAN THE 1524 mm roll" in editor.roll_status.text()
    editor.suggest_roll_fit()
    advice = editor.roll_advice_text.text()
    assert "gores or more (now 8)" in advice and "Half gores for row A, B, C, D" in advice
    # Half gores for the rows too wide: one edit; every piece then fits.
    buttons = {b.objectName(): b for b in editor.panels_box.findChildren(QPushButton)}
    buttons["halfGores_oversize"].click()
    assert _halves(gore_window) == [True, True, True, True]
    assert editor.roll_status.text().startswith("✓ every piece fits the 1524 mm roll")
    assert controller.envelope_roll_findings() == []
    buttons["halfGores_none"].click()
    assert _halves(gore_window) == [False] * 4
    # The gore count, at the top of the box.
    editor.gore_count.setValue(14)
    editor.gore_count.editingFinished.emit()
    assert controller.design is not None and controller.design.gores is not None
    assert controller.design.gores.count == 14
    assert editor.roll_status.text().startswith("✓")
    gore_window.undo()
    assert controller.design.gores.count == 8


def test_the_rows_table_ticks_a_row_as_half_gores(gore_window: MainWindow) -> None:
    gore_window.mode_tabs.setCurrentIndex(0)
    editor = gore_window.gore_editor
    item = editor.rows_table.item(1, 5)
    assert item is not None and item.checkState() == Qt.CheckState.Unchecked
    item.setCheckState(Qt.CheckState.Checked)
    assert _halves(gore_window) == [False, True, False, False]
    item = editor.rows_table.item(1, 5)
    assert item is not None and item.checkState() == Qt.CheckState.Checked
    # The validation names the halves that still do not fit.
    messages = [f.message for f in gore_window.controller.envelope_roll_findings()]
    assert not any(m.startswith("row B") for m in messages)
    assert any(m.startswith("row A:") for m in messages)


def test_patterns_cut_the_selected_row_as_half_gores(gore_window: MainWindow) -> None:
    gore_window.show_panel("patterns")
    patterns = gore_window.patterns
    patterns.regenerate()
    gore_window.controller.select("row:C")
    patterns.refresh()
    assert not patterns.half_gore.isChecked()
    patterns.half_gore.setChecked(True)
    assert _halves(gore_window) == [False, False, True, False]
    patterns.refresh()
    assert patterns.half_gore.isChecked()
    assert patterns.roll_label.text().startswith("each half: ")
    texts = [i.text() for i in patterns.view.scene().items() if hasattr(i, "text")]
    assert any("PANEL C x8 (2 half gores)" in t for t in texts)
    # On the print roll each half is a page of its own.
    gore_window.apply_preferences(replace(gore_window.prefs, print_roll_width=3.7))
    patterns.layout_mode.setCurrentIndex(patterns.layout_mode.findData("roll"))
    patterns._layout_changed(0)
    texts = [i.text() for i in patterns.view.scene().items() if hasattr(i, "text")]
    assert any(t.startswith("row C left half: ") for t in texts)
    assert any(t.startswith("row C right half: ") for t in texts)
    assert not any(t.startswith("row C: ") for t in texts)
