"""GUI tests: the Simulation Runs panel in the shared design (chips, FoS column, empty state)."""

from __future__ import annotations

from envelopelab.project.model import RunRecord
from envelopelab_app.main_window import MainWindow
from envelopelab_app.panels.runs import EMPTY_TEXT, FOS_COLUMN, STATE_COLUMN, state_kind
from envelopelab_app.theme import StatusChip

from .test_gui_workflows import fake_run


def _record(window: MainWindow, **changes: object) -> RunRecord:
    session = window.controller.session
    assert session is not None
    record, _ = fake_run(session)
    return record.model_copy(update=changes)


def test_state_kind_is_worst_first(gore_window: MainWindow) -> None:
    ok = _record(gore_window)
    assert state_kind(ok, "current", None) == "info"  # preview: not verified
    assert state_kind(ok.model_copy(update={"solver": "calculix"}), "current", None) == "ok"
    assert state_kind(ok, "current", 4.0) == "fail"  # below the required 5
    assert state_kind(ok, "current", 6.0) == "info"
    assert state_kind(ok, "stale", 4.0) == "stale"
    unconverged = ok.model_copy(update={"converged": False})
    assert state_kind(unconverged, "stale", 4.0) == "error"


def test_empty_state_then_a_run_row_with_a_state_chip(gore_window: MainWindow) -> None:
    w = gore_window
    w.show_panel("runs")
    panel = w.runs
    assert not panel.empty.isHidden() and panel.empty.text() == EMPTY_TEXT
    assert panel.table.isHidden()
    session = w.controller.session
    assert session is not None
    record, arrays = fake_run(session)
    session.add_run(record, arrays)
    assert panel.empty.isHidden() and not panel.table.isHidden()
    holder = panel.table.cellWidget(0, STATE_COLUMN)
    assert holder is not None
    chips = holder.findChildren(StatusChip)
    assert len(chips) == 1 and chips[0].kind == "info" and "Current" in chips[0].text()
    # The cell text stays for sorting, copying and the existing checks.
    assert panel.table.item(0, STATE_COLUMN).text() == "CURRENT"  # type: ignore[union-attr]
    # No warp/weft resultants in the fake run: no factor of safety, said in the tooltip.
    fos = panel.table.item(0, FOS_COLUMN)
    assert fos is not None and fos.text() == "—" and "current, converged" in fos.toolTip()


def test_calculix_chip_or_banner(gore_window: MainWindow) -> None:
    panel = gore_window.runs
    if panel.manager.calculix_available:
        assert panel.calculix_chip.kind == "ok" and "CalculiX" in panel.calculix_chip.text()
        assert panel.calculix_banner.kind is None
    else:
        assert panel.calculix_chip.kind == "error"
        assert panel.calculix_banner.kind == "error"
        assert panel.calculix_label.text() == panel.manager.calculix_message
