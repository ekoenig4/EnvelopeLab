"""GUI tests: File ▸ Export build pack… with its documents and the 3D view page."""

from __future__ import annotations

from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from envelopelab.export.build_pack import DEFAULT_ROLL_WIDTH
from envelopelab.export.documents import DOCUMENTS
from envelopelab.export.qa import check_pack
from envelopelab.export.viewer import STATUS_COLORS, STATUS_SYMBOLS, read_scene
from envelopelab.project.gore_design import control_arrays
from envelopelab_app.main_window import MainWindow
from envelopelab_app.simulation import PREVIEW
from envelopelab_app.theme import STATUS_STYLES


def test_viewer_banner_colours_are_the_themes() -> None:
    for kind, style in STATUS_STYLES.items():
        assert STATUS_COLORS[kind] == (style.background, style.border, style.text)
        assert STATUS_SYMBOLS[kind] in (style.symbol, "+", "i", "~", "!", "x")


def test_export_dialog_defaults_and_file_menu(gore_window: MainWindow, qtbot: QtBot) -> None:
    from envelopelab_app.export_dialog import ExportPackDialog

    dialog = ExportPackDialog(gore_window, "/tmp/pack")
    qtbot.addWidget(dialog)
    assert dialog.include() == frozenset(DOCUMENTS)
    assert dialog.roll_width() == pytest.approx(DEFAULT_ROLL_WIDTH)
    dialog.checks["viewer"].setChecked(False)
    assert "viewer" not in dialog.include()
    assert gore_window.export_pack_action.text() == "&Export build pack…"
    file_menu = gore_window.menuBar().actions()[0]
    assert file_menu.text() == "&File"
    assert gore_window.export_pack_action in file_menu.menu().actions()  # type: ignore[attr-defined]


def test_export_without_a_run_writes_the_design_only_page(
    gore_window: MainWindow, tmp_path: Path
) -> None:
    from envelopelab.export.templates import slug

    design = gore_window.controller.design
    assert design is not None
    stem = slug(design.meta.name)
    index = gore_window.export_build_pack(tmp_path / "pack", roll_width=1.0)
    assert index is not None and check_pack(tmp_path / "pack") == []
    scene = read_scene(tmp_path / "pack" / f"{stem}-3d.html")
    assert [m["key"] for m in scene["meshes"]] == ["design"]
    assert scene["meshes"][0]["visible"]
    assert scene["status"]["title"] == "Design only."
    assert (tmp_path / "pack" / f"{stem}-00-BUILD-PACK-INDEX.pdf").is_file()
    # Only the chosen documents.
    gore_window.export_build_pack(tmp_path / "few", frozenset({"planning"}))
    assert not (tmp_path / "few" / f"{stem}-3d.html").exists()
    assert (tmp_path / "few" / f"{stem}-panel-dimensions.csv").is_file()


@pytest.mark.slow
def test_export_after_a_run_colours_the_result_and_keeps_its_status(
    gore_window: MainWindow, qtbot: QtBot, tmp_path: Path
) -> None:
    w = gore_window
    session = w.controller.session
    assert session is not None
    assert w.simulation.start(PREVIEW)
    assert w.simulation.wait(600_000)
    qtbot.waitUntil(lambda: len(session.project.runs) == 1, timeout=10_000)
    view = w.view3d
    qtbot.waitUntil(lambda: "fos_warp" in view.fields, timeout=10_000)
    from envelopelab.export.templates import slug

    stem = slug(session.design.meta.name)
    assert w.export_build_pack(tmp_path / "pack") is not None
    assert check_pack(tmp_path / "pack") == []
    scene = read_scene(tmp_path / "pack" / f"{stem}-3d.html")
    run = next(m for m in scene["meshes"] if m["role"] == "result")
    assert {"fos_warp", "deviation"} <= set(run["colorings"])
    assert "preview" in run["note"]
    design = next(m for m in scene["meshes"] if m["key"] == "design")
    assert not design["visible"] and "deviation" in design["colorings"]
    assert scene["initial"] == ""  # opens in fabric colours; FoS is a Colour-by mode
    assert run["base"]  # the inflated envelope in its zones' fabric colours
    assert scene["status"]["kind"] == view.banner.kind
    assert scene["status"]["title"] == view.banner.title.text()
    # A stale run is never coloured as a result, and says so.
    r, z = control_arrays(session.design)
    w.controller.edit(
        "set_control_points", [(a * 1.01, b) for a, b in zip(r, z, strict=True)], "Widen"
    )
    qtbot.waitUntil(lambda: view.banner.kind == "stale", timeout=10_000)
    assert w.export_build_pack(tmp_path / "stale") is not None
    scene = read_scene(tmp_path / "stale" / f"{stem}-3d.html")
    run = next(m for m in scene["meshes"] if m["role"] == "result")
    assert run["colorings"] == {} and "stale" in run["note"]
    assert scene["status"]["kind"] == "stale"
