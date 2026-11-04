"""Marking sheets of a special shape: the envelope panels it is sewn on.

Each sheet is one envelope panel a shape crosses or lies over, gore by gore, as on the
build pack's marking sheets (:func:`envelopelab.export.build_pack.primitive_sheets`): the
footprint line the shape's rim is sewn on with short ticks on the shape's side, the
numbered match marks naming their skin pieces, and the feed holes at their cut (dashed) and
finished (solid) sizes. The sheets are laid out side by side on shelves that fill the view;
the view first zooms to the marked area (the marks are close together round a small
footprint), the mouse wheel zooms and a double click switches between the marked area and
every whole panel.

Display only: the geometry comes from the export module, so what is shown is what the
build pack prints.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsPolygonItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
)

from envelopelab_app.pattern_layout import shelf_layout

#: Gap between sheets, m.
GAP = 0.25
#: Colours of the markings and of a panel's outline (greyed when the patterns are stale).
MARK_COLOR = "#c0392b"
OUTLINE_COLOR = "#9467bd"
STALE_COLOR = "#9e9e9e"


def _polygon(points: np.ndarray) -> QPolygonF:
    """Panel coordinates (x right, y up, m) to scene coordinates (y down)."""
    return QPolygonF([QPointF(float(x), -float(y)) for x, y in np.asarray(points)])


class MarkingView(QGraphicsView):
    """Draws a list of marking sheets (see the module docstring)."""

    def __init__(self) -> None:
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setToolTip("Mouse wheel: zoom; drag: pan; double click: marked area / whole panels")
        self.sheets: list[Any] = []
        self.stale = False
        self._content = QRectF()
        #: Scene box of the markings (lines, ticks, marks, holes) of every sheet.
        self._marked = QRectF()
        #: What the last fit showed: the marked area or the whole panels.
        self.showing_all = False

    def set_sheets(self, sheets: list[Any], stale: bool = False) -> None:
        """Show these marking sheets; ``stale`` greys them (patterns out of date)."""
        refit = [s.piece for s in sheets] != [s.piece for s in self.sheets]
        self.sheets = list(sheets)
        self.stale = stale
        self._draw()
        if refit:
            self.fit()

    def labels(self) -> list[str]:
        """Every text drawn in the view (for tests and accessibility)."""
        return [i.text() for i in self.scene().items() if isinstance(i, QGraphicsSimpleTextItem)]

    def fit(self, whole: bool = False) -> None:
        """Fit the marked area (default) or every whole sheet in the view."""
        box = self._content if whole or self._marked.isEmpty() else self._marked
        if box.isEmpty():
            return
        pad = 0.25 * max(box.width(), box.height()) if box is self._marked else 0.1
        self.fitInView(box.adjusted(-pad, -pad, pad, pad), Qt.AspectRatioMode.KeepAspectRatio)
        self.showing_all = box is self._content

    def showEvent(self, event: Any) -> None:  # noqa: N802 (Qt API)
        """Fit again when shown: sheets set while the tab was hidden had no view size."""
        super().showEvent(event)
        self.fit(whole=self.showing_all)

    def wheelEvent(self, event: Any) -> None:  # noqa: N802 (Qt API)
        notches = event.angleDelta().y() / 120.0
        if notches:
            factor = 1.25**notches
            self.scale(factor, factor)
        event.accept()

    def mouseDoubleClickEvent(self, _event: Any) -> None:  # noqa: N802 (Qt API)
        self.fit(whole=not self.showing_all)

    def _draw(self) -> None:
        scene = self.scene()
        scene.clear()
        self._content = QRectF()
        self._marked = QRectF()
        if not self.sheets:
            return
        boxes = [_polygon(s.cut).boundingRect() for s in self.sheets]
        viewport = self.viewport()
        aspect = viewport.width() / viewport.height() if viewport.height() > 0 else 1.6
        places = shelf_layout([(b.width(), b.height()) for b in boxes], aspect, GAP).positions
        for sheet, box, (x, top) in zip(self.sheets, boxes, places, strict=True):
            container = QGraphicsRectItem()
            container.setPen(QPen(Qt.PenStyle.NoPen))
            container.setPos(QPointF(x - box.left(), top - box.top()))
            scene.addItem(container)
            marked = self._draw_sheet(sheet, container)
            self._content = self._content.united(box.translated(container.pos()))
            if not marked.isEmpty():
                self._marked = self._marked.united(marked.translated(container.pos()))

    def _draw_sheet(self, sheet: Any, parent: QGraphicsItem) -> QRectF:
        """Draw one sheet in ``parent``; return the box of its markings (parent coords)."""
        marked = QRectF()
        grey = QColor(STALE_COLOR)
        red = grey if self.stale else QColor(MARK_COLOR)
        outline = QGraphicsPolygonItem(_polygon(sheet.finished), parent)
        outline.setBrush(QBrush(QColor(200, 200, 200, 60) if self.stale else QColor("#fdf6e3")))
        pen = QPen(grey if self.stale else QColor(OUTLINE_COLOR), 1.5)
        pen.setCosmetic(True)
        outline.setPen(pen)
        tip = "\n".join([sheet.piece, sheet.note, *sheet.notes, *(w for _, _, w in sheet.texts)])
        outline.setToolTip(tip)
        outline.setZValue(-1.0)
        cut = QGraphicsPolygonItem(_polygon(sheet.cut), parent)
        cut_pen = QPen(grey, 1.0, Qt.PenStyle.DashLine)
        cut_pen.setCosmetic(True)
        cut.setPen(cut_pen)
        cut.setZValue(-2.0)

        def path(points: np.ndarray, width: float) -> None:
            item = QGraphicsPathItem(parent)
            p = QPainterPath(QPointF(float(points[0][0]), -float(points[0][1])))
            for x, y in points[1:]:
                p.lineTo(float(x), -float(y))
            item.setPath(p)
            nonlocal marked
            marked = marked.united(p.boundingRect())
            line_pen = QPen(red, width)
            line_pen.setCosmetic(True)
            item.setPen(line_pen)

        for line in sheet.lines:
            path(line, 2.0)
        for tick in sheet.ticks:
            path(tick, 1.0)
        for circles, style in (
            (sheet.holes, Qt.PenStyle.SolidLine),
            (sheet.hole_cuts, Qt.PenStyle.DashLine),
        ):
            for x, y, r in circles:
                if r <= 0.0:
                    continue
                ring = QGraphicsEllipseItem(x - r, -y - r, 2 * r, 2 * r, parent)
                marked = marked.united(ring.rect())
                ring_pen = QPen(red, 1.0, style)
                ring_pen.setCosmetic(True)
                ring.setPen(ring_pen)

        def text(x: float, y: float, words: str, size: float = 6.5) -> QGraphicsSimpleTextItem:
            item = QGraphicsSimpleTextItem(words, parent)
            font = item.font()
            font.setPointSizeF(size)
            item.setFont(font)
            item.setBrush(QBrush(red))
            item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
            item.setPos(x, -y)
            return item

        for x, y, words in sheet.marks:
            path(np.array([[x - 0.02, y], [x + 0.02, y]]), 1.0)
            path(np.array([[x, y - 0.02], [x, y + 0.02]]), 1.0)
            text(x + 0.02, y + 0.02, words)
        for (x, y, r), (_, _, rc) in zip(sheet.holes, sheet.hole_cuts, strict=True):
            text(x - r, y + r + 0.03, f"hole: cut {2000 * rc:.0f} / finished {2000 * r:.0f} mm")
        lo, hi = sheet.finished.min(axis=0), sheet.finished.max(axis=0)
        # Short on the panel; the full directions are in the tooltip and on the sheets.
        shape = sheet.note.removeprefix("mark ").removesuffix(" on this panel before assembly")
        label = text(float(lo[0]), float(hi[1]) + 0.05, f"{sheet.piece.upper()}: {shape}", 7.5)
        label.setBrush(QBrush(QColor("#1f2933")))
        label.setToolTip(tip)
        return marked
