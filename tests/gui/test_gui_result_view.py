"""GUI tests: results in the 3D view (colour bands, status banner, run details)."""

from __future__ import annotations

import os

import numpy as np
import pytest
from pytestqt.qtbot import QtBot

from envelopelab.project.gore_design import control_arrays
from envelopelab_app.main_window import MainWindow
from envelopelab_app.result_view import RunState, banner_for, fos_bands, wrinkle_bands
from envelopelab_app.simulation import PREVIEW
from envelopelab_app.theme import FAIL_COLOR


def _state(**changes: object) -> RunState:
    base: dict[str, object] = {
        "solver": "envelopelab-preview",
        "solver_label": "Preview",
        "run_id": "r1",
        "converged": True,
        "stale": False,
        "status": "converged",
        "iterations": 1840,
        "residual": 8.2e-7,
    }
    base.update(changes)
    return RunState(**base)  # type: ignore[arg-type]


def test_fos_bands_put_everything_below_the_limit_in_the_fail_colour() -> None:
    bands = fos_bands(np.array([1.0, 4.99, 5.0, 6.5, 9.0, 10.0, np.inf]), 5.0)
    assert bands.colors[0] == FAIL_COLOR
    assert bands.index.tolist() == [0, 0, 1, 2, 3, 4, 4]
    assert bands.labels == ("< 5  FAIL", "5 – 6", "6 – 8", "8 – 10", "≥ 10")


def test_wrinkle_bands() -> None:
    assert wrinkle_bands(np.array([0.0, 1.0, 2.0])).index.tolist() == [0, 1, 2]


def test_banner_order_worst_first() -> None:
    assert banner_for(None) is None
    failing = _state(failing_zones=("crown (warp)",), min_fos=4.1)
    unconverged = banner_for(_state(converged=False, status="iteration limit", stale=True))
    assert unconverged is not None and unconverged.kind == "error"
    assert "not final" in unconverged.title
    stale = banner_for(_state(stale=True, failing_zones=("crown (warp)",)))
    assert stale is not None and stale.kind == "stale" and stale.request == PREVIEW
    fail = banner_for(failing)
    assert fail is not None and fail.kind == "fail"
    assert "crown (warp)" in fail.message and "4.10" in fail.message
    temperature = banner_for(_state(warnings=("zone crown: temperature exceeds the limit",)))
    assert temperature is not None and temperature.kind == "fail"
    assert "temperature" in temperature.message
    preview_only = banner_for(_state())
    assert preview_only is not None and preview_only.kind == "info"
    assert "not yet verified" in preview_only.message and preview_only.request == "calculix"
    verified = banner_for(_state(verified=True))
    assert verified is not None and verified.kind == "ok" and not verified.action


def test_error_findings_block_a_converged_banner() -> None:
    banner = banner_for(_state(errors=("tape t1 broke",)))
    assert banner is not None and banner.kind == "error" and "tape t1 broke" in banner.message


def test_no_run_means_no_banner_and_no_fields(gore_window: MainWindow) -> None:
    view = gore_window.view3d
    assert view.banner.kind is None
    assert view.run_choice.currentData() is None and not view.run_choice.isEnabled()
    assert view.field_choice.count() == 1 and view.shown_field() is None
    assert "No solver result" in view.run_details.text()


@pytest.mark.slow
def test_preview_run_colours_by_fos_and_goes_grey_when_stale(
    gore_window: MainWindow, qtbot: QtBot
) -> None:
    w = gore_window
    view = w.view3d
    session = w.controller.session
    assert session is not None
    assert w.simulation.start(PREVIEW)
    assert w.simulation.wait(600_000)
    qtbot.waitUntil(lambda: len(session.project.runs) == 1, timeout=10_000)
    qtbot.waitUntil(lambda: view.run_choice.currentData() == PREVIEW, timeout=10_000)
    record = session.project.runs[0]
    assert record.converged
    # A current, converged preview: coloured by warp FoS, banner says it is unverified
    # (or names the failing zones), and the run details give the §6.5 facts.
    field = view.shown_field()
    assert field is not None and field.name == "fos_warp"
    assert len(field.values) == record.n_elements
    assert view.banner.kind in ("info", "fail")
    details = view.run_details.text()
    for fact in ("Iterations", "Residual", "nodes", "Load case", "Materials", "Run time"):
        assert fact in details
    assert f"{record.iterations}" in details
    # The runs table gives the same lowest factor as the colours.
    from envelopelab_app.panels.runs import FOS_COLUMN
    from envelopelab_app.result_view import lowest_fos

    low = lowest_fos(view.fields)
    assert low is not None
    cell = w.runs.table.item(0, FOS_COLUMN)
    assert cell is not None and cell.text().startswith(f"{low:.2f}")
    if os.environ.get("ENVELOPELAB_TEST_3D") and view.plotter is not None:
        view.redraw()
        assert view.plotter.scalar_bars  # the colour scale is drawn
    # Any design edit makes the run stale: no colour, a stale banner, fields disabled.
    r, z = control_arrays(session.design)
    pts = [(float(a) * 1.01, float(b)) for a, b in zip(r, z, strict=True)]
    w.controller.edit("set_control_points", pts, "Widen")
    qtbot.waitUntil(lambda: view.banner.kind == "stale", timeout=10_000)
    assert view.shown_field() is None and not view.fields
    assert "stale" in view.missing["fos_warp"]
    assert view.banner.action.text().startswith("Re-run")
    requested: list[str] = []
    view.rerunRequested.connect(requested.append)
    view.banner.action.click()
    assert requested == [PREVIEW]


def test_layer_list_shows_short_names_with_the_full_label_as_tooltip(
    gore_window: MainWindow,
) -> None:
    from envelopelab_app.panels.view3d import Layer
    from envelopelab_app.theme import STATUS_STYLES

    view = gore_window.view3d
    item = view.layer_list.item(0)
    assert item is not None and item.text() == "Design surface"
    assert item.toolTip() == view.labels()["design"]  # the full description
    assert len(item.text()) < len(item.toolTip())
    empty = np.zeros((0, 3))
    stale = Layer("envelopelab-preview", "envelopelab-preview", "long [STALE]", empty, empty)
    stale.stale = True
    stale.converged = False
    # The status stays on the row, never only in the tooltip.
    assert stale.display_name == (
        f"Preview result  {STATUS_STYLES['error'].symbol} not converged"
        f"  {STATUS_STYLES['stale'].symbol} stale"
    )
    assert Layer("shape-sim:Ear", "shape-simulated", "x", empty, empty).short == "Ear (inflated)"
    assert Layer("shape:Ear", "shape", "x", empty, empty).short == "Ear (designed)"
    ref = Layer("reference", "reference", "Reference mesh (scan.obj)", empty, empty)
    assert ref.short == "Reference: scan.obj"


def test_pattern_overlay_says_why_without_a_current_run(gore_window: MainWindow) -> None:
    panel = gore_window.patterns
    panel.regenerate()
    panel.overlay.setCurrentIndex(panel.overlay.findData("deviation"))
    panel.refresh()
    assert not panel.overlay_note.isHidden()
    assert "no current, converged run" in panel.overlay_note.text()
    panel.overlay.setCurrentIndex(0)
    panel.refresh()
    assert panel.overlay_note.isHidden()


@pytest.mark.slow
def test_deviation_from_design_in_3d_and_on_the_patterns(
    gore_window: MainWindow, qtbot: QtBot
) -> None:
    from PySide6.QtWidgets import QGraphicsPolygonItem

    w = gore_window
    session = w.controller.session
    assert session is not None
    w.patterns.regenerate()
    assert w.simulation.start(PREVIEW)
    assert w.simulation.wait(600_000)
    qtbot.waitUntil(lambda: len(session.project.runs) == 1, timeout=10_000)
    view = w.view3d
    qtbot.waitUntil(lambda: "deviation" in view.fields, timeout=10_000)
    field = view.fields["deviation"]
    assert field.location == "node" and len(field.values) == session.project.runs[0].n_nodes
    assert np.isfinite(field.values).all()
    assert field.values.min() < 0.0 < field.values.max()  # inside somewhere, outside elsewhere
    # The flat panels: one heat grid per row, with the same full scale as the nodes.
    panel = w.patterns
    w.show_panel("patterns")
    panel.overlay.setCurrentIndex(panel.overlay.findData("deviation"))
    panel.refresh()
    heat = panel._heat
    assert heat is not None and set(heat[1]) == set(panel.rows_by_letter())
    assert panel._heat_limit == pytest.approx(float(np.abs(field.values).max()))
    assert "red outside, blue inside" in panel.overlay_note.text()
    tips = [
        i.toolTip()
        for i in panel.view.scene().items()
        if isinstance(i, QGraphicsPolygonItem) and "worst of the gores" in i.toolTip()
    ]
    assert tips and all(t.startswith("Row ") for t in tips)
