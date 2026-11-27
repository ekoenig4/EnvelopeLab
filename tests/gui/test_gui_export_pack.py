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
    assert (run["object"], run["state"]) == ("envelope", "envelopelab-preview")
    design = next(m for m in scene["meshes"] if m["key"] == "design")
    assert (design["object"], design["state"]) == ("envelope", "design")
    assert "deviation@envelopelab-preview" in design["colorings"]
    # The page offers the view's Shape choices and opens on the one the view shows.
    assert [k for k, _t in scene["states"]] == ["design", "envelopelab-preview"]
    assert scene["state"] == view.state() == "envelopelab-preview"
    assert scene["statuses"]["design"]["title"] == "Design only."
    assert scene["initial"] == ""  # opens in fabric colours; FoS is a Colour-by mode
    assert run["base"]  # the inflated envelope in its zones' fabric colours
    assert scene["status"]["kind"] == view.banner.kind
    assert scene["status"]["title"] == view.banner.title.text()
    assert scene["statuses"]["envelopelab-preview"]["title"] == view.banner.title.text()
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


def test_each_special_shape_gets_its_own_3d_page(gore_window: MainWindow, tmp_path: Path) -> None:
    from envelopelab.export.templates import slug

    w = gore_window
    assert w.shapes.add_shape("dome") == "Dome"
    assert w.controller.shapes.wait(120_000)
    design = w.controller.design
    assert design is not None
    stem = slug(design.meta.name)
    assert w.export_build_pack(tmp_path / "pack") is not None
    assert check_pack(tmp_path / "pack") == []
    page = read_scene(tmp_path / "pack" / f"{stem}-Dome-3d.html")
    assert [m["key"] for m in page["meshes"]] == ["shape:Dome"]
    # The pack's main 3D view has the shape too, as an object of its own.
    main = read_scene(tmp_path / "pack" / f"{stem}-3d.html")
    assert {"key": "shape:Dome", "label": "Dome", "group": "Special shapes"} in main["objects"]
    assert main["objects"][0]["key"] == "envelope"
    dome = next(m for m in main["meshes"] if m["object"] == "shape:Dome")
    assert dome["state"] == "design"
    assert page["status"]["title"] == "Not simulated."  # no metrics without a simulation
    assert (tmp_path / "pack" / f"{stem}-assembly-Dome.pdf").is_file()


def test_scale_model_dialog_fits_the_paper(gore_window: MainWindow, qtbot: QtBot) -> None:
    from envelopelab.export.scale_model import (
        ScaleModel,
        fit_scale,
        model_summary,
        oversize_pieces,
    )
    from envelopelab_app.export_dialog import ExportPackDialog

    sheets = gore_window.shapes.pack_sheets()
    out = gore_window.controller.outputs
    assert sheets and out is not None

    dialog = ExportPackDialog(
        gore_window,
        "/tmp/pack",
        fit=lambda m: fit_scale(sheets, m),
        check=lambda m: oversize_pieces(sheets, m),
        summary=lambda m: model_summary(out.volume, out.height, out.max_diameter, m),
    )
    qtbot.addWidget(dialog)
    assert dialog.scale_model() is None and dialog.include() == frozenset(DOCUMENTS)
    dialog.model_box.setChecked(True)
    # Every document but the lift charts; no roll.
    assert dialog.include() == frozenset(DOCUMENTS) - {"lift_chart"}
    assert not dialog.roll.isEnabled() and not dialog.checks["lift_chart"].isEnabled()
    assert dialog.checks["viewer"].isEnabled()
    dialog.scale.setValue(2.0)
    assert "larger than the paper at 1:2" in dialog.model_status.text()
    n = dialog.fit_to_paper()
    assert n is not None and n.is_integer() and dialog.scale.value() == n
    assert dialog.model_status.text() == f"Every piece fits one sheet at 1:{n:g}."
    # The model's volume, height and width at that scale.
    volume = out.volume / n**3
    assert f"height {out.height / n * 1000:,.0f} mm" in dialog.model_size.text()
    assert f"{volume:.3g} m3" in dialog.model_size.text()
    model = dialog.scale_model()
    assert model is not None and model.denominator == n
    assert model.seam_allowance == pytest.approx(0.005)  # set at model size by default
    assert model.paper.name.startswith("US Letter")
    assert not dialog.print_width.isEnabled()
    # A custom size, then a maximum width only.
    dialog.paper.setCurrentIndex(dialog.paper.findData("custom"))
    assert dialog.print_width.isEnabled() and dialog.print_height.isEnabled()
    dialog.print_width.setValue(300.0)
    dialog.print_height.setValue(400.0)
    model = dialog.scale_model()
    assert model is not None
    assert (model.paper.width, model.paper.height) == pytest.approx((0.3, 0.4))
    dialog.paper.setCurrentIndex(dialog.paper.findData("width"))
    assert dialog.print_width.isEnabled() and not dialog.print_height.isEnabled()
    model = dialog.scale_model()
    assert model is not None and model.paper.width == pytest.approx(0.3)
    assert model.paper.height is None
    wide = dialog.fit_to_paper()
    assert wide is not None and wide <= n  # 300 mm of any length takes a larger model
    # The design's allowance, scaled; the state round-trips.
    dialog.fixed_allowance.setChecked(False)
    model = dialog.scale_model()
    assert model is not None and model.seam_allowance is None
    other = ExportPackDialog(gore_window, "/tmp/pack")
    qtbot.addWidget(other)
    other.set_model_state(dialog.model_state())
    assert other.scale_model() == model
    dialog.model_box.setChecked(False)
    assert dialog.roll.isEnabled() and dialog.scale_model() is None
    assert dialog.include() == frozenset(DOCUMENTS)
    assert isinstance(model, ScaleModel)


def test_export_scale_model_writes_every_document(gore_window: MainWindow, tmp_path: Path) -> None:
    import json

    from envelopelab.export.scale_model import PAPER_SIZES, ScaleModel

    model = ScaleModel(40.0, PAPER_SIZES["letter"], seam_allowance=0.005)
    index = gore_window.export_scale_model(tmp_path / "model", model)
    assert index is not None and check_pack(tmp_path / "model") == []
    data = json.loads(index.read_text())
    assert data["scale_model"]["scale"] == "1:40"
    assert data["scale_model"]["seam_allowance_mm"] == 5.0
    files = {d["file"] for d in data["documents"]}
    assert any(f.endswith("-00-BUILD-PACK-INDEX.pdf") for f in files)
    assert any(f.endswith("-sewing-schedule.html") for f in files)
    assert any(f.endswith("-3d.html") for f in files)
    assert not any("lift-chart" in f for f in files)
    scene = read_scene(tmp_path / "model" / next(f for f in files if f.endswith("-3d.html")))
    assert scene["status"]["title"] == "Scale model 1:40."
