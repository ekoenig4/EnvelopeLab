"""Positions shown and typed in metres or balloon coordinates (Preferences ▸ Positions
shown in); what is stored is the same either way."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from envelopelab.project.coordinates import across_metres, balloon_position, tape_at
from envelopelab_app.main_window import MainWindow
from envelopelab_app.settings import load_preferences


def _units(window: MainWindow, units: str) -> None:
    window.apply_preferences(replace(window.prefs, position_units=units))


def _placed(window: MainWindow) -> None:
    assert window.controller.shapes.wait(120_000)


def test_the_preference_is_stored_and_defaults_to_metres(gore_window: MainWindow) -> None:
    assert gore_window.controller.position_units == "metres"
    _units(gore_window, "balloon")
    assert str(gore_window.controller.position_units) == "balloon"
    assert load_preferences(gore_window.settings).position_units == "balloon"
    gore_window.prefs.position_units = "furlongs"  # an unknown value reads as metres
    assert gore_window.controller.position_units == "metres"


def test_a_shape_is_placed_by_panel_row_in_balloon_coordinates(gore_window: MainWindow) -> None:
    gore_window.show_panel("shapes")
    panel = gore_window.shapes
    panel.add_shape("dome")
    _placed(gore_window)
    surface = gore_window.controller.envelope_surface()
    assert surface is not None
    spec = panel.spec()
    assert spec is not None
    p = spec.placement
    editor = panel.position

    # Metres: offset from the gore centre in m and tape position in m; no row boxes.
    assert editor.tape.isVisibleTo(panel) and not editor.row_box.isVisibleTo(panel)
    assert editor.across.suffix() == " m"
    assert editor.across.value() == pytest.approx(
        across_metres(surface, p.across, p.tape_position), abs=1e-3
    )
    assert editor.tape.value() == pytest.approx(p.tape_position, abs=1e-3)

    _units(gore_window, "balloon")
    assert editor.row_box.isVisibleTo(panel) and not editor.tape.isVisibleTo(panel)
    b = balloon_position(surface, p.gore, p.across, p.tape_position)
    assert editor.row.currentData() == b.row
    assert editor.row_fraction.value() == pytest.approx(b.row_fraction, abs=1e-3)
    assert editor.across.value() == pytest.approx(b.gore_fraction, abs=1e-3)

    # Halfway up the row below and a quarter across the gore: stored as metres.
    lower = surface.rows[
        max(surface.rows.index(next(r for r in surface.rows if r.label == b.row)) - 1, 0)
    ]
    editor.row.setCurrentIndex(editor.row.findData(lower.label))
    editor.row.activated.emit(editor.row.currentIndex())
    editor.row_fraction.setValue(0.5)
    editor.across.setValue(0.25)
    gore_window.controller.flush_live()
    _placed(gore_window)
    moved = panel.spec()
    assert moved is not None
    assert moved.placement.tape_position == pytest.approx(tape_at(surface, lower.label, 0.5))
    assert moved.placement.across == pytest.approx(-0.25)
    assert moved.placement.gore == p.gore
    assert panel.placed(moved.name) is not None, panel.status.text()


def test_metre_offsets_across_the_gore_are_stored_as_fractions(gore_window: MainWindow) -> None:
    gore_window.show_panel("shapes")
    panel = gore_window.shapes
    panel.add_shape("dome")
    _placed(gore_window)
    surface = gore_window.controller.envelope_surface()
    spec = panel.spec()
    assert surface is not None and spec is not None
    s = spec.placement.tape_position
    w = float(surface.half_width(np.array([s]))[0])
    panel.position.across.setValue(0.5 * w)  # a quarter of the width from the centre
    gore_window.controller.flush_live()
    moved = panel.spec()
    assert moved is not None and moved.placement.across == pytest.approx(0.25, abs=1e-3)


def test_feed_holes_are_typed_by_row_in_balloon_coordinates(gore_window: MainWindow) -> None:
    gore_window.show_panel("shapes")
    panel = gore_window.shapes
    panel.add_shape("dome")
    _placed(gore_window)
    assert panel.add_feed_hole()
    surface = gore_window.controller.envelope_surface()
    assert surface is not None
    _units(gore_window, "balloon")
    header = panel.holes_table.horizontalHeaderItem(1)
    assert header is not None and header.text() == "row + fraction up"
    hole = panel.spec().feed_holes[0]  # type: ignore[union-attr]
    b = balloon_position(surface, hole.gore, hole.across, hole.tape_position)
    up = panel.holes_table.item(0, 1)
    assert up is not None and up.text() == f"{b.row} + {b.row_fraction:.3f}"
    up.setText(f"{b.row} + 0.5")
    moved = panel.spec().feed_holes[0]  # type: ignore[union-attr]
    assert moved.tape_position == pytest.approx(tape_at(surface, b.row, 0.5))
    across = panel.holes_table.item(0, 2)
    assert across is not None
    across.setText("1.5")  # outside the gore: refused, nothing changes
    assert panel.spec().feed_holes[0] == moved  # type: ignore[union-attr]
    across = panel.holes_table.item(0, 2)
    assert across is not None and across.text() == f"{moved.across + 0.5:.3f}"


def test_readouts_and_the_overlay_editor_follow_the_units(gore_window: MainWindow) -> None:
    controller = gore_window.controller
    surface = controller.envelope_surface()
    assert surface is not None
    row = surface.rows[1]
    s = 0.5 * (row.s_bottom + row.s_top)
    assert controller.describe_position(2, 0.0, s).endswith(f"{s:.3f} m up the tape")
    _units(gore_window, "balloon")
    assert controller.describe_position(2, 0.0, s) == f"gore 2 + 0.50, row {row.label} + 0.50"
    tip = gore_window.shapes._describe_point(2.75, s)  # gore 3, three quarters across
    assert tip == f"gore 3 + 0.75, row {row.label} + 0.50"
    assert gore_window.shapes._axis_label(2.75) == "gore 3 + 0.75"

    gore_window.show_panel("shapes")
    name = gore_window.shapes.add_overlay()
    assert name is not None
    editor = gore_window.shapes.overlay_editor.position
    assert editor.units == "balloon" and editor.row.count() == len(surface.rows)


def test_shape_positions_are_metres_or_the_shapes_own_fractions(gore_window: MainWindow) -> None:
    from envelopelab.project.coordinates import skin_length
    from envelopelab.project.shapes import widest_radius

    gore_window.show_panel("shapes")
    panel = gore_window.shapes
    panel.add_shape("revolved")
    _placed(gore_window)
    assert panel.set_value(("splits",), [0.5])
    _placed(gore_window)
    spec = panel.spec()
    assert spec is not None
    total, widest = skin_length(spec), widest_radius(spec)

    # Metres: the split along the skin from the rim, where the panels meet in m.
    header = panel.splits_table.horizontalHeaderItem(0)
    cell = panel.splits_table.item(0, 0)
    assert header is not None and "m along the skin" in header.text()
    assert cell is not None and float(cell.text()) == pytest.approx(0.5 * total, abs=1e-3)
    cell.setText(f"{0.25 * total:.4f}")
    spec = panel.spec()
    assert spec is not None and spec.splits[0] == pytest.approx(0.25, abs=1e-3)
    panel.cap_across.setValue(0.2 * widest)
    gore_window.controller.flush_live()
    spec = panel.spec()
    assert spec is not None and spec.cap_across == pytest.approx(0.2, abs=1e-3)
    assert panel.cap_across.suffix() == " m"

    # Balloon coordinates: the shape's own fractions (% of the profile, of the radius).
    _units(gore_window, "balloon")
    header = panel.splits_table.horizontalHeaderItem(0)
    cell = panel.splits_table.item(0, 0)
    assert header is not None and "% of the profile" in header.text()
    assert cell is not None and float(cell.text()) == pytest.approx(25.0, abs=0.1)
    assert panel.cap_across.value() == pytest.approx(0.2, abs=1e-3)
    assert panel.cap_across.suffix() == ""
    cell.setText("40")
    spec = panel.spec()
    assert spec is not None and spec.splits[0] == pytest.approx(0.4)
