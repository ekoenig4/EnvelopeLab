"""Main-window layout: workflow modes, resizing, and saving/loading/resetting the layout."""

from __future__ import annotations

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QSplitter
from pytestqt.qtbot import QtBot

from envelopelab_app import layout
from envelopelab_app.main_window import MainWindow, panel_titles

from .gui_support import make_window

#: The window must fit a 1280 x 800 laptop screen (px).
SMALL_SCREEN = (1280, 800)


def sizes(window: MainWindow, name: str) -> list[int]:
    return layout.named_splitters(window)[name].sizes()


def test_window_fits_a_small_screen(gore_window: MainWindow) -> None:
    # The dock layout needed at least 2137 x 1036 px with the fixture project open.
    hint = gore_window.minimumSizeHint()
    assert hint.width() <= SMALL_SCREEN[0] and hint.height() <= SMALL_SCREEN[1]
    gore_window.resize(*SMALL_SCREEN)
    assert (gore_window.width(), gore_window.height()) == SMALL_SCREEN


def test_each_mode_shows_its_panels_and_always_the_warnings(gore_window: MainWindow) -> None:
    w = gore_window
    assert [w.mode_tabs.tabText(i) for i in range(w.mode_tabs.count())][0] == "Shape"
    assert w.mode() == "shape" and w.mode_stack.currentWidget() is w.gore_editor
    for key in layout.MODE_KEYS:
        w.set_mode(key)
        assert w.mode() == key and w.mode_actions[key].isChecked()
        assert w.panels["validation"].isVisible()  # safety warnings are never hidden
        assert w.panels["tree"].isVisible() and w.panels["properties"].isVisible()
        for panel, mode in w.panel_modes.items():
            assert w.panels[panel].isVisible() == w.panel_visible(panel)
            if mode is not None:
                assert w.panels[panel].isVisible() == (mode == key)
    w.show_panel("runs")
    assert w.mode() == "simulate"


def test_mode_shortcuts_and_tab_clicks_agree(gore_window: MainWindow) -> None:
    w = gore_window
    w.mode_actions["history"].trigger()
    assert w.mode_tabs.currentIndex() == layout.MODE_KEYS.index("history")
    w.mode_tabs.setCurrentIndex(layout.MODE_KEYS.index("patterns"))
    assert w.mode_actions["patterns"].isChecked()
    assert w.mode_actions["rigging"].shortcut().toString() == "Ctrl+3"


def test_mode_tabs_repeat_the_panel_indicators(gore_window: MainWindow) -> None:
    w = gore_window
    patterns_tab = layout.MODE_KEYS.index("patterns")
    w.patterns.regenerate()
    assert "[STALE]" not in w.mode_tabs.tabText(patterns_tab)
    w.patterns.default_allowance.setValue(30.0)  # mm; makes the patterns stale
    w.patterns.default_allowance.editingFinished.emit()
    assert "[STALE]" in panel_titles(w)["patterns"]
    assert "[STALE]" in w.panels["patterns"].header.text()
    assert "[STALE]" in w.mode_tabs.tabText(patterns_tab)
    assert "●" in w.mode_tabs.tabText(patterns_tab)
    w.undo_action.trigger()
    assert "[STALE]" not in w.mode_tabs.tabText(patterns_tab)


def test_sidebar_collapses_but_the_mode_page_does_not(gore_window: MainWindow) -> None:
    w = gore_window
    side = layout.named_splitters(w)["sideSplitter"]
    assert side.isCollapsible(0) and not side.isCollapsible(1)
    outer = layout.named_splitters(w)["outerSplitter"]
    assert not outer.isCollapsible(0) and not outer.isCollapsible(1)
    w.toggle_sidebar()
    assert not w.sidebar_visible() and not w.sidebar_action.isChecked()
    w.show_panel("properties")
    assert w.sidebar_visible() and w.sidebar_action.isChecked()


def test_save_load_and_reset_layout(gore_window: MainWindow) -> None:
    w = gore_window
    w.resize(*SMALL_SCREEN)
    defaults = sizes(w, "sideSplitter")
    assert not w.load_saved_layout()  # nothing saved yet

    w.set_mode("simulate")
    w.toggle_sidebar()
    saved = sizes(w, "sideSplitter")
    assert saved[0] == 0
    w.save_layout()

    w.reset_layout()
    assert w.mode() == "shape" and w.sidebar_visible()
    assert sizes(w, "sideSplitter") == defaults

    assert w.load_saved_layout()
    assert w.mode() == "simulate" and sizes(w, "sideSplitter") == saved
    assert not w.sidebar_action.isChecked()


def test_last_layout_is_restored_in_the_next_window(
    qtbot: QtBot, gore_window: MainWindow, settings: QSettings
) -> None:
    w = gore_window
    w.resize(*SMALL_SCREEN)
    w.set_mode("history")
    splitter = layout.named_splitters(w)["outerSplitter"]
    splitter.setSizes([500, 200])
    expected = splitter.sizes()
    w.close()

    other = make_window(qtbot, settings)
    other.resize(*SMALL_SCREEN)  # the stored geometry of an offscreen window
    assert other.mode() == "history"
    assert sizes(other, "outerSplitter") == expected


def test_unreadable_or_old_layouts_are_ignored(
    qtbot: QtBot, settings: QSettings, window: MainWindow
) -> None:
    settings.setValue("layout/saved/version", layout.LAYOUT_VERSION - 1)
    settings.setValue("layout/saved/mode", "patterns")
    assert layout.load(settings, layout.SAVED_SLOT) is None
    assert not window.load_saved_layout()

    settings.setValue("layout/last/version", "garbage")
    assert layout.load(settings, layout.LAST_SLOT) is None
    settings.setValue("layout/last/version", layout.LAYOUT_VERSION)
    settings.setValue("layout/last/mode", "no-such-mode")
    settings.setValue("layout/last/splitters/outerSplitter", "not a byte array")
    state = layout.load(settings, layout.LAST_SLOT)
    assert state is not None and state.mode == "shape" and not state.splitters
    other = make_window(qtbot, settings)
    assert other.mode() == "shape"


def test_every_named_splitter_has_a_default() -> None:
    names = set(layout.DEFAULT_SIZES)
    assert {"outerSplitter", "sideSplitter", "goreEditorSplitter"} <= names
    assert all(len(v) == 2 and min(v) > 0 for v in layout.DEFAULT_SIZES.values())


def test_all_layout_splitters_exist_in_the_window(window: MainWindow) -> None:
    found = {s.objectName() for s in window.findChildren(QSplitter)}
    assert set(layout.DEFAULT_SIZES) <= found
