"""The balloon's panels as a flat grid to paint (Colours mode).

The envelope is drawn as its gore map (with the overlays, the appliqués sewn on it,
over its panels): the gores side by side at their true flat width,
cut at the row seams (:func:`envelopelab.project.colours.envelope_cells`, m). Every
special shape follows on the right as a schematic grid, one column per gore or panel
round its axis and one band per tier, its cap a band on top
(:meth:`envelopelab.project.colours.ShapeGrid.cells`), scaled to a fraction of the
envelope's height.

Press a panel to paint it; drag across panels to paint them all in one undo step. While
the pointer is over a panel the panels a click would paint are outlined (the tool's
scope, e.g. its whole row, and the repeat round the envelope), and the tooltip names the
panel and its colour. The wheel zooms about the pointer, a right or middle drag pans, a
double click or **Fit** shows everything again.

Nothing is computed here but what is drawn: the cell outlines are painter paths built
once per change of the envelope or the shapes.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
    QTransform,
    QWheelEvent,
)
from PySide6.QtWidgets import QToolTip, QWidget

from envelopelab.project.colours import CAP, CAP_BAND, PanelColours, PanelRef, ShapeGrid
from envelopelab_app.view_tools import FitButton

#: Uncoloured panels: alternate gores (or pieces) in two light greys, as the gore map.
EMPTY_FILL = ("#eef2f8", "#e3e9f2")
SEAM = "#4d4d4d"
#: An overlay with no colour chosen.
OVERLAY_FILL = "#f3e6cf"
#: Outline of the panels a click would paint.
TARGET = "#e8590c"
#: Height of a shape's grid, as a fraction of the envelope's (display only).
SHAPE_HEIGHT = 0.3
#: Gap between the envelope and the shapes, and between shapes, as a fraction of the
#: shape height (display only).
SHAPE_GAP = 0.35


@dataclass
class GridScene:
    """Everything the grid draws, in map units (m for the envelope).

    Attributes
    ----------
    cells : list of (PanelRef, ndarray of shape (n, 2))
        Every panel's outline.
    labels : list of (str, float, float, str)
        Text, position and alignment (``"top"``, ``"left"``, ``"title"``).
    overlays : set of str
        Names of the overlays among the cells (drawn last, so on top, and hit first).
    """

    cells: list[tuple[PanelRef, np.ndarray]] = field(default_factory=list)
    labels: list[tuple[str, float, float, str]] = field(default_factory=list)
    #: Overlays (appliqués) drawn over the envelope cells: their names.
    overlays: set[str] = field(default_factory=set)

    def bounds(self) -> QRectF:
        """Smallest rectangle round every cell."""
        if not self.cells:
            return QRectF(0.0, 0.0, 1.0, 1.0)
        pts = np.vstack([poly for _r, poly in self.cells])
        lo, hi = pts.min(axis=0), pts.max(axis=0)
        return QRectF(float(lo[0]), float(lo[1]), float(hi[0] - lo[0]), float(hi[1] - lo[1]))


def grid_scene(
    envelope: Sequence[tuple[PanelRef, np.ndarray]],
    rows: Sequence[tuple[str, float, float]],
    gores: int,
    column: float,
    grids: Sequence[ShapeGrid],
) -> GridScene:
    """Lay out the envelope cells (m) and the shape grids beside them.

    Parameters
    ----------
    envelope : sequence of (PanelRef, ndarray)
        Envelope cells (:func:`envelopelab.project.colours.envelope_cells`), m; may be
        empty (no gore envelope).
    rows : sequence of (str, float, float)
        Row letter and tape positions of its seams, m (labels).
    gores : int
        Gore count (labels).
    column : float
        Gore column width, m.
    grids : sequence of ShapeGrid
        Special shapes.

    Returns
    -------
    GridScene
    """
    scene = GridScene(cells=list(envelope))
    height = max((s1 for _l, _s0, s1 in rows), default=0.0)
    for g in range(gores):
        scene.labels.append((str(g + 1), (g + 0.5) * column, height, "top"))
    for label, s0, s1 in rows:
        scene.labels.append((label, 0.0, 0.5 * (s0 + s1), "left"))
    if envelope:
        scene.labels.append(("Envelope", 0.5 * gores * column, height, "title"))
    h = SHAPE_HEIGHT * height if height > 0 else 1.0
    x0 = gores * column + SHAPE_GAP * h if envelope else 0.0
    top = height if height > 0 else (1.0 + CAP_BAND) * h
    for grid in grids:
        w = max(h, grid.pieces * h / 8.0)
        bottom = top - (1.0 + (CAP_BAND if grid.cap else 0.0)) * h
        for ref, unit in grid.cells():
            poly = np.column_stack([x0 + unit[:, 0] * w, bottom + unit[:, 1] * h])
            scene.cells.append((ref, poly))
        scene.labels.append((grid.name, x0 + 0.5 * w, top, "title"))
        top = bottom - SHAPE_GAP * h
    return scene


def _path(poly: np.ndarray) -> QPainterPath:
    path = QPainterPath()
    path.addPolygon(QPolygonF([QPointF(float(x), float(y)) for x, y in poly]))
    path.closeSubpath()
    return path


def _pen(colour: str, width: float) -> QPen:
    pen = QPen(QColor(colour), width)
    pen.setCosmetic(True)  # pixels, whatever the zoom
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


class ColourGridView(QWidget):
    """See module docstring.

    Signals
    -------
    stroked(list)
        The panels pressed or dragged over (``PanelRef``, in order, each once), when the
        button is released.
    """

    stroked = Signal(list)

    MARGIN = 26.0

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("colourGrid")
        self.scene = GridScene()
        self.colours = PanelColours()
        #: Panels a click on a panel would paint (set by the Colours panel).
        self.targets: Callable[[PanelRef], list[PanelRef]] = lambda ref: [ref]
        #: Colour a stroke previews (None: clearing).
        self.brush: str | None = None
        self._paths: list[tuple[PanelRef, QPainterPath]] = []
        self._index: dict[PanelRef, int] = {}
        self.zoom, self.pan = 1.0, QPointF(0.0, 0.0)
        self.bounds = QRectF(0.0, 0.0, 1.0, 1.0)
        self._pan_from: QPointF | None = None
        self._stroke: list[PanelRef] | None = None
        self.hover: PanelRef | None = None
        self.setMouseTracking(True)
        self.setMinimumSize(320, 240)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.fit_button = FitButton(self, self.fit, "Show every panel again")

    # -- data -------------------------------------------------------------------------

    def set_scene(self, scene: GridScene) -> None:
        """Draw ``scene`` (paths are built here once)."""
        self.scene = scene
        self._paths = [(ref, _path(poly)) for ref, poly in scene.cells]
        self._index = {ref: i for i, (ref, _p) in enumerate(self._paths)}
        self.bounds = scene.bounds()
        if self.hover not in self._index:
            self.hover = None
        self.update()

    def set_colours(self, colours: PanelColours) -> None:
        """Fill the panels with ``colours``."""
        self.colours = colours
        self.update()

    # -- frame: map units to pixels ---------------------------------------------------

    def scale(self) -> float:
        b = self.bounds
        sx = (self.width() - 2 * self.MARGIN) / max(b.width(), 1e-9)
        sy = (self.height() - 2 * self.MARGIN) / max(b.height(), 1e-9)
        return self.zoom * max(min(sx, sy), 1e-9)

    def transform(self) -> QTransform:
        """Map units to widget pixels (y up)."""
        k, b = self.scale(), self.bounds
        cx = self.width() / 2 + self.pan.x() - b.center().x() * k
        cy = self.height() / 2 + self.pan.y() + b.center().y() * k
        return QTransform(k, 0.0, 0.0, -k, cx, cy)

    def to_world(self, p: QPointF) -> QPointF:
        inverse, _ok = self.transform().inverted()
        return inverse.map(p)

    def to_screen(self, p: QPointF) -> QPointF:
        return self.transform().map(p)

    def fit(self) -> None:
        self.zoom, self.pan = 1.0, QPointF(0.0, 0.0)
        self.update()

    def panel_at(self, p: QPointF) -> PanelRef | None:
        """The panel under widget point ``p`` (None: none)."""
        w = self.to_world(p)
        # Last drawn first: an overlay lies over the panels under it.
        for ref, path in reversed(self._paths):
            if path.contains(w):
                return ref
        return None

    def centre_of(self, ref: PanelRef) -> QPointF:
        """Widget point at the middle of panel ``ref`` (for scripted clicks)."""
        path = self._paths[self._index[ref]][1]
        return self.to_screen(path.boundingRect().center())

    # -- mouse ------------------------------------------------------------------------

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802 (Qt API)
        notches = event.angleDelta().y() / 120.0
        if notches:
            at = event.position()
            before = self.to_world(at)
            self.zoom = min(max(self.zoom * 1.25**notches, 0.5), 200.0)
            self.pan += at - self.to_screen(before)
            self.update()
        event.accept()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt API)
        if event.button() in (Qt.MouseButton.RightButton, Qt.MouseButton.MiddleButton):
            self._pan_from = event.position()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        ref = self.panel_at(event.position())
        self._stroke = [] if ref is None else [ref]
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt API)
        if self._pan_from is not None:
            self.pan += event.position() - self._pan_from
            self._pan_from = event.position()
            self.update()
            return
        ref = self.panel_at(event.position())
        if self._stroke is not None and ref is not None and ref not in self._stroke:
            self._stroke.append(ref)
        if ref != self.hover:
            self.hover = ref
            self.update()
            if ref is None:
                self.setToolTip("")
            else:
                colour = self.colours.colour_of(ref)
                text = f"{ref.label()}: {colour or 'no colour'}"
                self.setToolTip(text)
                QToolTip.showText(event.globalPosition().toPoint(), text, self)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt API)
        if self._pan_from is not None:
            self._pan_from = None
            return
        if event.button() != Qt.MouseButton.LeftButton or self._stroke is None:
            return
        stroke, self._stroke = self._stroke, None
        self.update()
        if stroke:
            self.stroked.emit(stroke)

    def mouseDoubleClickEvent(self, _event: QMouseEvent) -> None:  # noqa: N802 (Qt API)
        self.fit()

    def leaveEvent(self, _event: Any) -> None:  # noqa: N802 (Qt API)
        if self.hover is not None:
            self.hover = None
            self.update()

    # -- drawing ----------------------------------------------------------------------

    def _fill(self, ref: PanelRef, preview: set[PanelRef]) -> QColor:
        if ref in preview:
            return QColor(self.brush) if self.brush else QColor("white")
        colour = self.colours.colour_of(ref)
        if colour is not None:
            return QColor(colour)
        if ref.shape in self.scene.overlays:
            return QColor(OVERLAY_FILL)
        shade = (ref.index + (1 if ref.group == CAP else 0)) % 2
        return QColor(EMPTY_FILL[shade])

    def paintEvent(self, _event: object) -> None:  # noqa: N802 (Qt API)
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("white"))
        if not self._paths:
            painter.setPen(QPen(QColor("#5f6b7a")))
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                "No panels to colour: open or create a standard-gore design",
            )
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = self.transform()
        preview: set[PanelRef] = set()
        for ref in self._stroke or []:
            preview.update(self.targets(ref))
        outlined: set[PanelRef] = set(preview)
        if self.hover is not None and self._stroke is None:
            outlined.update(self.targets(self.hover))
        painter.save()
        painter.setTransform(t)
        seam = _pen(SEAM, 0.8)
        for ref, path in self._paths:
            painter.fillPath(path, QBrush(self._fill(ref, preview)))
            painter.strokePath(path, seam)
        target = _pen(TARGET, 2.2)
        for ref in outlined:
            i = self._index.get(ref)
            if i is not None:
                painter.strokePath(self._paths[i][1], target)
        painter.restore()
        small = QFont(painter.font())
        small.setPointSizeF(max(small.pointSizeF() - 1.5, 6.0))
        bold = QFont(painter.font())
        bold.setBold(True)
        painter.setPen(QPen(QColor(SEAM)))
        for text, x, y, where in self.scene.labels:
            p = t.map(QPointF(x, y))
            if where == "title":
                painter.setFont(bold)
                width = painter.fontMetrics().horizontalAdvance(text)
                painter.drawText(QPointF(p.x() - width / 2, p.y() - 16), text)
            elif where == "top":
                painter.setFont(small)
                width = painter.fontMetrics().horizontalAdvance(text)
                painter.drawText(QPointF(p.x() - width / 2, p.y() - 3), text)
            else:
                painter.setFont(small)
                width = painter.fontMetrics().horizontalAdvance(text)
                painter.drawText(QPointF(p.x() - width - 4, p.y() + 4), text)


__all__ = ["ColourGridView", "GridScene", "grid_scene"]
