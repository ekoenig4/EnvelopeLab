"""Colours mode (ADR-0055): the panel grid, the tools, the colour picker and undo."""

from __future__ import annotations

from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from envelopelab.project.colours import CAP, PanelRef
from envelopelab_app.colour_picker import MAX_RECENT, STANDARD, theme_columns, with_recent
from envelopelab_app.main_window import MainWindow
from envelopelab_app.panels.colours import RECENT_KEY


def _rows(window: MainWindow) -> list[str]:
    design = window.controller.design
    assert design is not None and design.gores is not None
    return [r.letter for r in design.gores.panel_rows]


def _click(qtbot: QtBot, window: MainWindow, ref: PanelRef) -> None:
    grid = window.colours.grid
    at = grid.centre_of(ref).toPoint()
    QTest.mouseClick(grid, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, at)


def test_colours_mode_shows_every_panel(gore_window: MainWindow) -> None:
    labels = [gore_window.mode_tabs.tabText(i) for i in range(gore_window.mode_tabs.count())]
    assert any(label.startswith("Colours") for label in labels)
    gore_window.set_mode("colours")
    panel = gore_window.colours
    design = gore_window.controller.design
    assert design is not None and design.gores is not None
    cells = panel.grid.scene.cells
    assert len(cells) == design.gores.count * len(design.gores.panel_rows)


def test_click_paint_fill_and_undo(qtbot: QtBot, gore_window: MainWindow) -> None:
    gore_window.set_mode("colours")
    panel, session = gore_window.colours, gore_window.controller.session
    assert session is not None
    rows = _rows(gore_window)
    fingerprints = session.fingerprints()
    panel.picker.set_colour(STANDARD[1])
    _click(qtbot, gore_window, PanelRef(None, rows[0], 2))
    colours = session.state.colours
    assert colours.colour_of(PanelRef(None, rows[0], 2)) == STANDARD[1]
    assert colours.colour_of(PanelRef(None, rows[0], 1)) is None
    assert panel.grid.colours == colours  # the grid shows it at once
    assert session.fingerprints() == fingerprints  # nothing is stale
    # Fill row with a repeat-independent scope: every gore of the row, one undo step.
    depth = session.stack.index
    panel.set_tool("row")
    panel.picker.set_colour("#00b050")
    _click(qtbot, gore_window, PanelRef(None, rows[1], 3))
    assert session.stack.index == depth + 1
    count = len(panel.grid.scene.cells) // len(rows)
    assert all(
        session.state.colours.colour_of(PanelRef(None, rows[1], g)) == "#00b050"
        for g in range(1, count + 1)
    )
    # Paint with a repeat every 2 gores.
    panel.set_tool("paint")
    panel.repeat.setValue(2)
    panel.picker.set_colour("#ffc000")
    _click(qtbot, gore_window, PanelRef(None, rows[-1], 1))
    painted = {
        g
        for g in range(1, count + 1)
        if session.state.colours.colour_of(PanelRef(None, rows[-1], g)) == "#ffc000"
    }
    assert painted == set(range(1, count + 1, 2))
    # The design row lists the colours, most used first; recents remember them.
    assert panel.picker.design_row.swatches[0].colour == "#00b050"
    assert panel.picker.recent[:3] == ["#ffc000", "#00b050", STANDARD[1]]
    session.undo()
    assert session.state.colours.colour_of(PanelRef(None, rows[-1], 1)) is None
    assert panel.grid.colours == session.state.colours


def test_eyedropper_and_no_colour(qtbot: QtBot, gore_window: MainWindow) -> None:
    gore_window.set_mode("colours")
    panel, session = gore_window.colours, gore_window.controller.session
    assert session is not None
    ref = PanelRef(None, _rows(gore_window)[0], 4)
    panel.picker.set_colour("#7030a0")
    _click(qtbot, gore_window, ref)
    panel.picker.set_colour("#ffffff")
    panel.set_tool("row")
    panel.set_tool("pick")
    _click(qtbot, gore_window, ref)
    assert panel.picker.colour == "#7030a0"
    assert panel.tool == "row"  # back to the tool used before
    panel.set_tool("paint")
    panel.picker.none_button.click()
    assert panel.picker.colour is None
    _click(qtbot, gore_window, ref)
    assert session.state.colours.is_empty()


def test_hex_entry_and_replace(gore_window: MainWindow) -> None:
    gore_window.set_mode("colours")
    panel, session = gore_window.colours, gore_window.controller.session
    assert session is not None
    panel.picker.hex_edit.setText("0a0")
    panel.picker.hex_edit.editingFinished.emit()
    assert panel.picker.colour == "#00aa00"
    panel.picker.hex_edit.setText("nope")
    panel.picker.hex_edit.editingFinished.emit()
    assert panel.picker.colour == "#00aa00"  # a bad code changes nothing
    panel.fill_all()
    assert session.state.colours.used() == ["#00aa00"]
    panel.picker.replaceRequested.emit("#00aa00", "#0070c0")
    assert session.state.colours.used() == ["#0070c0"]


def test_special_shape_pieces_are_painted(qtbot: QtBot, gore_window: MainWindow) -> None:
    gore_window.show_panel("shapes")
    gore_window.shapes.add_shape("dome")
    assert gore_window.controller.shapes.wait(120_000)
    session = gore_window.controller.session
    assert session is not None
    name = session.state.shapes[0].name
    gore_window.set_mode("colours")
    panel = gore_window.colours
    assert name in panel._grids
    panel.picker.set_colour("#c00000")
    _click(qtbot, gore_window, PanelRef(name, CAP, 1))
    panel.set_tool("row")
    _click(qtbot, gore_window, PanelRef(name, "A", 1))
    grid = panel._grids[name]
    assert all(session.state.colours.colour_of(ref) == "#c00000" for ref in grid.all_refs())


def test_recent_colours_are_kept_in_the_settings(
    gore_window: MainWindow, settings: QSettings
) -> None:
    gore_window.set_mode("colours")
    panel = gore_window.colours
    panel.picker.set_colour("#123456")
    panel.paint([PanelRef(None, _rows(gore_window)[0], 1)])
    stored = settings.value(RECENT_KEY)
    assert (stored if isinstance(stored, str) else list(stored))[0] == "#123456"


def test_palettes() -> None:
    columns = theme_columns()
    assert len(columns) == 10 and all(len(c) == 6 for c in columns)
    assert all(c.startswith("#") and len(c) == 7 for col in columns for c in col)
    recent: list[str] = []
    for i in range(MAX_RECENT + 3):
        recent = with_recent(recent, f"#0000{i:02x}")
    assert len(recent) == MAX_RECENT and recent[0] == f"#0000{MAX_RECENT + 2:02x}"
    assert with_recent(recent, recent[3])[0] == recent[3]
    assert len(with_recent(recent, recent[3])) == MAX_RECENT
