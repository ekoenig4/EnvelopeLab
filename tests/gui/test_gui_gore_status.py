"""GUI tests: the gore editor's status banner, key figures and lift-margin chip."""

from __future__ import annotations

from envelopelab_app.main_window import MainWindow
from envelopelab_app.result_view import design_banner


def test_design_banner_worst_first() -> None:
    assert design_banner(None, [], 12.0, 0.0) is None
    error = design_banner("no profile", ["rows do not fit"], -5.0, 0.3)
    assert error is not None and error.kind == "error"
    assert "no profile" in error.message and "rows do not fit" in error.message
    margin = design_banner(None, [], -2.5, 0.0)
    assert margin is not None and margin.kind == "fail" and margin.title == "Negative lift margin."
    assert "-2.5 kg" in margin.message
    shape = design_banner(None, [], 3.0, 0.25, "25% of the tape needs compression.")
    assert shape is not None and shape.title == "The shape will not hold under load."
    both = design_banner(None, [], -1.0, 0.1)
    assert both is not None and both.title == "A design limit is exceeded."
    assert "10%" in both.message and "-1.0 kg" in both.message


def test_fixture_shows_its_compressed_span_in_the_banner(gore_window: MainWindow) -> None:
    editor = gore_window.gore_editor
    physics = editor.shape_physics
    # The fixture's lowest span needs compression under load (drawn red on the canvas).
    assert physics.compressed_fraction > 0.0
    assert editor.banner.kind == "fail"
    assert "compression" in editor.banner.text()
    # Switching the check off removes that finding from the banner.
    physics.check_on.setChecked(False)
    assert physics.compressed_fraction == 0.0 and editor.banner.kind is None
    physics.check_on.setChecked(True)
    assert editor.banner.kind == "fail"


def test_key_figures_and_margin_chip_follow_the_outputs(gore_window: MainWindow) -> None:
    editor = gore_window.gore_editor
    out = gore_window.controller.outputs
    assert out is not None and out.lift_margin is not None
    assert editor.figures["volume"].text() == f"V {out.volume:.1f} m³"
    assert editor.figures["height"].text() == f"H {out.height:.2f} m"
    kind = "fail" if out.lift_margin < 0 else "ok"
    assert editor.margin_chip.kind == kind
    assert f"{out.lift_margin:.1f} kg" in editor.margin_chip.text()
