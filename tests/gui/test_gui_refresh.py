"""Refresh scheduling: one refresh per edit, hidden panels wait until they are shown."""

from __future__ import annotations

from envelopelab_app.main_window import MainWindow


def _move_point(window: MainWindow) -> None:
    design = window.controller.design
    assert design is not None and design.gores is not None
    p = design.gores.meridian_profile_control_points[3]
    window.controller.edit("move_control_point", 3, p.x + 0.01, p.y)


def test_one_edit_refreshes_each_visible_panel_once(gore_window: MainWindow) -> None:
    validation = gore_window.validation.refresher
    tree = gore_window.design_tree.refresher
    before = (validation.runs, tree.runs)
    _move_point(gore_window)
    # The edit emits stateChanged, artifactsChanged and fileChanged: one refresh each.
    assert (validation.runs, tree.runs) == (before[0] + 1, before[1] + 1)
    assert validation.skipped > 0


def test_hidden_panels_refresh_when_shown(gore_window: MainWindow) -> None:
    gore_window.controller.defer_hidden = True
    gore_window.set_mode("shape")
    view = gore_window.view3d
    assert not view.isVisible()
    runs = view.refresher.runs
    _move_point(gore_window)
    _move_point(gore_window)
    assert view.refresher.runs == runs and view.refresher.dirty
    gore_window.show_panel("view3d")
    assert view.isVisible()
    assert view.refresher.runs == runs + 1 and not view.refresher.dirty
    # Panel indicators are not deferred: the mode tabs show them while hidden.
    assert gore_window.panels["view3d"].indicator.defer_hidden is False


def test_controller_computes_rows_and_findings_once_per_change(gore_window: MainWindow) -> None:
    c = gore_window.controller
    rows = c.rows()
    assert c.rows() is rows
    findings = c.findings()
    assert c.findings() == findings
    _move_point(gore_window)
    assert c.rows() is not rows
