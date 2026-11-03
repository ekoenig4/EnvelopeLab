"""GUI tests: patterns regenerate automatically after every edit (the default)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings
from pytestqt.qtbot import QtBot

from envelopelab_app.settings import (
    PREFERENCES_VERSION,
    Preferences,
    load_preferences,
    save_preferences,
)

from .gui_support import GORE_PROJECT, make_window


def test_automatic_regeneration_is_the_default_and_resets_old_settings(tmp_path: Path) -> None:
    assert Preferences().auto_regenerate_patterns
    old = QSettings(str(tmp_path / "old.ini"), QSettings.Format.IniFormat)
    old.setValue("preferences/auto_regenerate_patterns", False)  # saved by an older version
    old.setValue("preferences/autosave_minutes", 5.0)
    assert load_preferences(old).auto_regenerate_patterns  # the new default, once
    assert load_preferences(old).autosave_minutes == 5.0  # other choices are kept
    prefs = load_preferences(old)
    prefs.auto_regenerate_patterns = False  # chosen now: kept from here on
    save_preferences(old, prefs)
    assert int(str(old.value("preferences/version"))) == PREFERENCES_VERSION
    assert not load_preferences(old).auto_regenerate_patterns


def test_an_edit_regenerates_the_patterns(qtbot: QtBot, settings: QSettings) -> None:
    settings.setValue("preferences/auto_regenerate_patterns", True)
    w = make_window(qtbot, settings)
    assert w.open_project(GORE_PROJECT) is not None
    assert w.controller.artifact_status("patterns") == "current"  # built on open
    panel = w.patterns
    panel.default_allowance.setValue(panel.default_allowance.value() + 5.0)
    panel.default_allowance.editingFinished.emit()
    assert w.controller.artifact_status("patterns") == "current"
    assert panel.banner.kind == "ok"


def test_a_failed_regeneration_says_why(
    qtbot: QtBot, settings: QSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings.setValue("preferences/auto_regenerate_patterns", True)
    w = make_window(qtbot, settings)
    assert w.open_project(GORE_PROJECT) is not None
    controller = w.controller

    def broken() -> object:
        raise ValueError("row C does not fit the tape")

    with monkeypatch.context() as mp:
        mp.setattr(controller, "rows", broken)
        panel = w.patterns
        panel.default_allowance.setValue(panel.default_allowance.value() + 5.0)
        panel.default_allowance.editingFinished.emit()
        assert controller.artifact_status("patterns") == "stale"
        assert controller.patterns_error == "row C does not fit the tape"
        w.show_panel("patterns")
        panel.refresh()
        assert panel.banner.kind == "error"
        assert "row C does not fit the tape" in panel.banner.text()
    assert controller.regenerate_patterns()
    assert controller.patterns_error is None
