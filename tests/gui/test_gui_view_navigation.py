"""Pan and reset in the 2D views of the Special shapes mode: the gore map (On the balloon),
the envelope panels (marking sheets) and the cut pieces. Every view pans with a left drag
on empty space (and with the middle or right button), and resets with a double click or
its Fit button."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractButton, QWidget

from envelopelab_app.main_window import MainWindow
from envelopelab_app.marking_view import MarkingView
from envelopelab_app.panels.shapes import ShapesPanel


def _dome(window: MainWindow) -> ShapesPanel:
    window.resize(1600, 1000)
    window.show()
    window.show_panel("shapes")
    panel = window.shapes
    panel.add_shape("dome")
    assert window.controller.shapes.wait(120_000)
    window.controller.regenerate_patterns()
    panel.refresh()
    return panel


def _drag(widget: QWidget, start: QPoint, end: QPoint, button: Qt.MouseButton) -> None:
    QTest.mousePress(widget, button, Qt.KeyboardModifier.NoModifier, start)
    for k in range(1, 6):
        p = start + (end - start) * k / 5
        QTest.mouseMove(widget, p)
    QTest.mouseRelease(widget, button, Qt.KeyboardModifier.NoModifier, end)


def _fit_button(view: QWidget) -> QAbstractButton:
    button = view.findChild(QAbstractButton, "fitView")
    assert button is not None, "the view has no Fit button"
    return button


def test_the_gore_map_pans_with_a_left_drag_on_empty_space_and_resets(
    gore_window: MainWindow,
) -> None:
    panel = _dome(gore_window)
    view = panel.placement.map
    view.setMouseTracking(True)
    m = view.data.gore_map
    assert m is not None
    # A corner beyond the gores: no shape or axis there.
    empty = view.to_screen(-0.0, m.length * 0.02).toPoint() + QPoint(2, -2)
    assert view.shape_at(QPointF(empty)) is None
    for button in (Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton):
        before = QPointF(view.pan)  # a copy: += changes the point in place
        _drag(view, empty, empty + QPoint(40, 25), button)
        assert view.pan - before == QPointF(40, 25), button
    # Zoomed out below the fit, so the whole map can be seen with room round it.
    view.zoom = 0.5
    _fit_button(view).click()
    assert view.zoom == 1.0 and view.pan == QPointF(0.0, 0.0)
    view.pan = QPointF(30.0, 30.0)
    QTest.mouseDClick(view, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, empty)
    assert view.pan == QPointF(0.0, 0.0)


def _centre(view: MarkingView) -> QPointF:
    return view.mapToScene(view.viewport().rect().center())


def test_the_envelope_panels_pan_at_any_zoom_and_reset(gore_window: MainWindow) -> None:
    panel = _dome(gore_window)
    tab = panel.markings.parentWidget()
    assert tab is not None
    panel.result_tabs.setCurrentIndex(panel.result_tabs.indexOf(tab))
    view = panel.markings
    view.fit(whole=True)  # every whole panel in view: nothing left for scroll bars
    before = _centre(view)
    vp = view.viewport()
    c = vp.rect().center()
    _drag(vp, c, c + QPoint(60, 40), Qt.MouseButton.LeftButton)
    after = _centre(view)
    assert after != before, "a drag does not pan the fitted view"
    # Reset: the Fit button shows the marked area again, wherever the view was.
    _fit_button(view).click()
    assert _centre(view) != after
    fitted = _centre(view)
    _drag(vp, c, c + QPoint(-50, 30), Qt.MouseButton.RightButton)
    assert _centre(view) != fitted
    _fit_button(view).click()
    assert (_centre(view) - fitted).manhattanLength() < 1e-6


def test_the_cut_pieces_pan_and_reset(gore_window: MainWindow) -> None:
    panel = _dome(gore_window)
    view = panel.preview
    c = view.rect().center()
    _drag(view, c, c + QPoint(30, 20), Qt.MouseButton.MiddleButton)
    assert view.pan == QPointF(30, 20)
    _fit_button(view).click()
    assert view.pan == QPointF(0.0, 0.0) and view.zoom == 1.0
