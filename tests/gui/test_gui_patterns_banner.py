"""GUI tests: the 2D pattern view's status banner (shared design)."""

from __future__ import annotations

from envelopelab_app.main_window import MainWindow
from envelopelab_app.panels.patterns import REGENERATE


def test_banner_follows_the_pattern_state_and_regenerates(gore_window: MainWindow) -> None:
    w = gore_window
    panel = w.patterns
    panel.regenerate()
    assert w.controller.artifact_status("patterns") == "current"
    assert panel.banner.kind == "ok" and "current" in panel.banner.text()
    assert panel.banner.action.isHidden()
    # A seam-allowance edit makes the patterns stale: grey banner with the action.
    panel.default_allowance.setValue(panel.default_allowance.value() + 5.0)
    panel.default_allowance.editingFinished.emit()
    assert w.controller.artifact_status("patterns") == "stale"
    assert panel.banner.kind == "stale" and "STALE" in panel.banner.text()
    assert panel.banner.action.text() == REGENERATE and not panel.banner.action.isHidden()
    # The banner's own button regenerates them.
    panel.banner.action.click()
    assert w.controller.artifact_status("patterns") == "current"
    assert panel.banner.kind == "ok"
