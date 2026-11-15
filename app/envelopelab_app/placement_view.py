"""Where the special shapes sit on the balloon: a 3D sketch and a gore map, side by side.

Shown under the shape editor in the Special shapes mode (ADR-0044), so positions typed
as numbers can be seen at once:

* **3D**: the envelope (gore and row seams), every shape as designed (the selected one
  in magenta), the symmetry axes in green (dashed where they run behind the envelope).
  Drag to turn it, wheel to zoom; it turns to face a shape when it is selected, and a
  double click faces the selected shape again.
* **Gore map**: the gores side by side as they are cut, at their true flat width, with
  the row seams, gore numbers and row letters (:mod:`envelopelab.project.placement_map`);
  every footprint, base point and feed hole, and the symmetry axes. Click a shape to
  select it; drag the selected shape to move it (one undo step; a grouped shape takes
  its group, a mirror twin its source). The wheel zooms about the pointer, the right
  button pans, a double click fits the map.

Both are drawn with QPainter, so they need no OpenGL (they work where the 3D View is
off). They draw what the project's placed shapes are; nothing is computed here.
"""

from __future__ import annotations

import math
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
    QWheelEvent,
)
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

SELECTED = "#d6008f"
OTHER = "#e98fc2"
AXIS = "#00a087"
SEAM = "#4d4d4d"
GORE_FILL = ("#eef2f8", "#e3e9f2")
ENVELOPE = (0.86, 0.89, 0.94)


@dataclass
class PlacedShape:
    """One shape as the two views draw it (m).

    Attributes
    ----------
    name : str
        Shape name.
    footprint : list of ndarray
        Footprint on the gore map (broken at seams).
    holes : list of ndarray
        Feed holes on the gore map.
    base : ndarray, shape (2,)
        Base point on the gore map.
    points, triangles : ndarray
        The shape as designed, on the envelope (3D sketch).
    base3d : ndarray, shape (3,)
        Base point on the envelope.
    placement : Any
        The shape's placement (kept when it is dragged).
    """

    name: str
    footprint: list[np.ndarray]
    holes: list[np.ndarray]
    base: np.ndarray
    points: np.ndarray
    triangles: np.ndarray
    base3d: np.ndarray
    placement: Any


@dataclass
class PlacementData:
    """Everything the views draw: the gore map, the 3D sketch, the axes and the shapes."""

    gore_map: Any = None
    sketch: Any = None
    axes: list[tuple[str, np.ndarray, list[np.ndarray]]] = field(default_factory=list)
    shapes: list[PlacedShape] = field(default_factory=list)
    selected: str | None = None


class _Zoomable(QWidget):
    """Fit, zoom (wheel, about the pointer) and pan (right button) of a 2D drawing."""

    MARGIN = 10.0

    def __init__(self) -> None:
        super().__init__()
        self.zoom, self.pan = 1.0, QPointF(0.0, 0.0)
        self._pan_from: QPointF | None = None
        self.bounds = QRectF(0.0, 0.0, 1.0, 1.0)

    def scale(self) -> float:
        b = self.bounds
        sx = (self.width() - 2 * self.MARGIN) / max(b.width(), 1e-9)
        sy = (self.height() - 2 * self.MARGIN) / max(b.height(), 1e-9)
        return self.zoom * max(min(sx, sy), 1e-9)

    def to_screen(self, x: float, y: float) -> QPointF:
        k, b = self.scale(), self.bounds
        cx = self.width() / 2 + self.pan.x()
        cy = self.height() / 2 + self.pan.y()
        return QPointF(cx + (x - b.center().x()) * k, cy - (y - b.center().y()) * k)

    def to_world(self, p: QPointF) -> tuple[float, float]:
        k, b = self.scale(), self.bounds
        cx = self.width() / 2 + self.pan.x()
        cy = self.height() / 2 + self.pan.y()
        return b.center().x() + (p.x() - cx) / k, b.center().y() - (p.y() - cy) / k

    def poly(self, pts: np.ndarray) -> QPolygonF:
        return QPolygonF([self.to_screen(float(x), float(y)) for x, y in pts])

    def fit(self) -> None:
        self.zoom, self.pan = 1.0, QPointF(0.0, 0.0)
        self.update()

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802 (Qt API)
        notches = event.angleDelta().y() / 120.0
        if notches:
            at = event.position()
            before = self.to_world(at)
            self.zoom = min(max(self.zoom * 1.25**notches, 1.0), 200.0)
            after = self.to_screen(*before)
            self.pan += at - after
            self.update()
        event.accept()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt API)
        if event.button() == Qt.MouseButton.RightButton:
            self._pan_from = event.position()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt API)
        if self._pan_from is not None:
            self.pan += event.position() - self._pan_from
            self._pan_from = event.position()
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt API)
        if event.button() == Qt.MouseButton.RightButton:
            self._pan_from = None


class GoreMapView(_Zoomable):
    """The gores side by side with the shapes and axes on them (module docstring)."""

    #: A shape was clicked (its name).
    shapeClicked = Signal(str)  # noqa: N815 (Qt naming)
    #: The selected shape was dragged to a new placement (name, placement).
    shapeMoved = Signal(str, object)  # noqa: N815 (Qt naming)

    def __init__(self) -> None:
        super().__init__()
        self.data = PlacementData()
        self._drag: tuple[str, QPointF, QPointF] | None = None  # shape, start, now (px)
        self.setMouseTracking(True)
        self.setMinimumSize(220, 180)
        self.setObjectName("shapeGoreMap")

    def set_data(self, data: PlacementData) -> None:
        self.data = data
        m = data.gore_map
        if m is not None:
            self.bounds = QRectF(0.0, 0.0, m.gores * m.column, m.length)
        self.update()

    def shape_at(self, p: QPointF) -> str | None:
        """The shape whose footprint (or base point) is under widget point ``p``."""
        x, y = self.to_world(p)
        best: tuple[float, str] | None = None
        for shape in self.data.shapes:
            pts = np.vstack(shape.footprint) if shape.footprint else shape.base[None]
            lo, hi = pts.min(axis=0), pts.max(axis=0)
            pad = 6.0 / self.scale()
            if lo[0] - pad <= x <= hi[0] + pad and lo[1] - pad <= y <= hi[1] + pad:
                d = math.hypot(x - shape.base[0], y - shape.base[1])
                if best is None or d < best[0]:
                    best = (d, shape.name)
        return None if best is None else best[1]

    def placement_at(self, name: str, p: QPointF) -> Any:
        """Where shape ``name`` goes when its base point is dragged by the drag so far to
        widget point ``p``."""
        from envelopelab.project.placement_map import map_to_placement

        shape = next(s for s in self.data.shapes if s.name == name)
        assert self._drag is not None
        x0, y0 = self.to_world(self._drag[1])
        x1, y1 = self.to_world(p)
        x, y = float(shape.base[0]) + x1 - x0, float(shape.base[1]) + y1 - y0
        return map_to_placement(self.data.gore_map, x, y, shape.placement)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt API)
        super().mousePressEvent(event)
        if event.button() != Qt.MouseButton.LeftButton:
            return
        name = self.shape_at(event.position())
        if name is None:
            return
        if name != self.data.selected:
            self.shapeClicked.emit(name)
        self._drag = (name, event.position(), event.position())

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt API)
        super().mouseMoveEvent(event)
        if self._drag is not None:
            self._drag = (self._drag[0], self._drag[1], event.position())
            self.update()
        m = self.data.gore_map
        if m is not None:
            x, y = self.to_world(event.position())
            if 0.0 <= y <= m.length and 0.0 <= x <= m.gores * m.column:
                k = int(min(x // m.column, m.gores - 1))
                row = next((r for r, lo, hi in m.rows if lo <= y <= hi), "")
                self.setToolTip(f"gore {k + 1}, row {row}, {y:.2f} m up the tape from the mouth")

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt API)
        super().mouseReleaseEvent(event)
        if event.button() != Qt.MouseButton.LeftButton or self._drag is None:
            return
        name, start, _now = self._drag
        moved = (event.position() - start).manhattanLength() > 3
        placement = self.placement_at(name, event.position()) if moved else None
        self._drag = None
        self.update()
        if placement is not None:
            self.shapeMoved.emit(name, placement)

    def mouseDoubleClickEvent(self, _event: QMouseEvent) -> None:  # noqa: N802 (Qt API)
        self.fit()

    def paintEvent(self, _event: object) -> None:  # noqa: N802 (Qt API)
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("white"))
        m = self.data.gore_map
        if m is None:
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No envelope")
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        small = QFont(painter.font())
        small.setPointSizeF(max(small.pointSizeF() - 1.5, 6.0))
        painter.setFont(small)
        # Gores, row seams, gore numbers and row letters.
        for k, outline in enumerate(m.outlines):
            path = QPainterPath()
            path.addPolygon(self.poly(outline))
            path.closeSubpath()
            painter.fillPath(path, QBrush(QColor(GORE_FILL[k % 2])))
            painter.setPen(QPen(QColor(SEAM), 1.0))
            painter.drawPath(path)
            top = self.to_screen((k + 0.5) * m.column, m.length)
            painter.drawText(QPointF(top.x() - 6, top.y() - 3), str(k + 1))
        painter.setPen(QPen(QColor("#9aa3ad"), 0.8))
        for _label, lo, _hi in m.rows:
            if lo > 0.0:
                w = float(m.half_width(np.array([lo]))[0])
                for k in range(m.gores):
                    xc = (k + 0.5) * m.column
                    painter.drawLine(self.to_screen(xc - w, lo), self.to_screen(xc + w, lo))
        painter.setPen(QPen(QColor("#5f6b7a")))
        for label, lo, hi in m.rows:
            p = self.to_screen(0.0, 0.5 * (lo + hi))
            painter.drawText(QPointF(p.x() - 9, p.y() + 4), label)
        # Symmetry axes.
        for name, line, _lines3d in self.data.axes:
            painter.setPen(QPen(QColor(AXIS), 2.2))
            painter.drawPolyline(self.poly(line))
            top = self.to_screen(float(line[-1][0]), float(line[-1][1]))
            painter.drawText(QPointF(top.x() + 3, top.y() + 12), name)
        # Shapes: footprints, feed holes, base points and names.
        drag_name = None if self._drag is None else self._drag[0]
        delta = QPointF(0.0, 0.0)
        if self._drag is not None:
            delta = self._drag[2] - self._drag[1]
        for shape in self.data.shapes:
            selected = shape.name == self.data.selected
            colour = QColor(SELECTED if selected else OTHER)
            shift = delta if shape.name == drag_name else QPointF(0.0, 0.0)
            painter.setPen(QPen(colour, 2.4 if selected else 1.4))
            for part in shape.footprint:
                painter.drawPolyline(self.poly(part).translated(shift))
            dashed = QPen(colour, 1.0)
            dashed.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(dashed)
            for part in shape.holes:
                painter.drawPolyline(self.poly(part).translated(shift))
            base = self.to_screen(float(shape.base[0]), float(shape.base[1])) + shift
            painter.setBrush(QBrush(colour))
            painter.setPen(QPen(colour))
            painter.drawEllipse(base, 3.0, 3.0)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawText(QPointF(base.x() + 5, base.y() - 5), shape.name)


class BalloonSketch(QWidget):
    """The envelope, the shapes and the axes in 3D, drawn with QPainter (module
    docstring)."""

    def __init__(self) -> None:
        super().__init__()
        self.data = PlacementData()
        self.azimuth, self.elevation, self.zoom = -90.0, 10.0, 1.0
        self._turn: QPointF | None = None
        self._faced: str | None = None
        self.setMinimumSize(200, 180)
        self.setObjectName("shapeSketch3d")
        self.setToolTip("Drag: turn; wheel: zoom; double click: face the selected shape")

    def set_data(self, data: PlacementData) -> None:
        self.data = data
        if data.selected != self._faced:
            self._faced = data.selected
            self.face_selected()
        self.update()

    def face_selected(self) -> None:
        """Turn to look straight at the selected shape's base point."""
        shape = next((s for s in self.data.shapes if s.name == self.data.selected), None)
        if shape is None or self.data.sketch is None:
            return
        centre = self._centre()
        rel = shape.base3d - centre
        self.azimuth = math.degrees(math.atan2(rel[1], rel[0]))
        self.elevation = math.degrees(math.atan2(rel[2], math.hypot(rel[0], rel[1])))
        self.elevation = min(max(self.elevation, -80.0), 80.0)
        self.update()

    def _centre(self) -> np.ndarray:
        pts = self.data.sketch.points
        return np.asarray(0.5 * (pts.min(axis=0) + pts.max(axis=0)), float)

    def _frame(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        az, el = math.radians(self.azimuth), math.radians(self.elevation)
        view = np.array([math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)])
        right = np.array([-math.sin(az), math.cos(az), 0.0])
        up = np.cross(view, right)
        return view, right, up

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt API)
        self._turn = event.position()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt API)
        if self._turn is not None:
            d = event.position() - self._turn
            self._turn = event.position()
            self.azimuth -= 0.5 * d.x()
            self.elevation = min(max(self.elevation + 0.5 * d.y(), -85.0), 85.0)
            self.update()

    def mouseReleaseEvent(self, _event: QMouseEvent) -> None:  # noqa: N802 (Qt API)
        self._turn = None

    def mouseDoubleClickEvent(self, _event: QMouseEvent) -> None:  # noqa: N802 (Qt API)
        self.face_selected()

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802 (Qt API)
        notches = event.angleDelta().y() / 120.0
        self.zoom = min(max(self.zoom * 1.2**notches, 0.5), 20.0)
        self.update()
        event.accept()

    def paintEvent(self, _event: object) -> None:  # noqa: N802 (Qt API)
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#f7f9fc"))
        sketch = self.data.sketch
        if sketch is None:
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No envelope")
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        view, right, up = self._frame()
        centre = self._centre()
        extent = float(np.linalg.norm(sketch.points.max(axis=0) - sketch.points.min(axis=0)))
        k = self.zoom * 0.9 * min(self.width(), self.height()) / max(extent, 1e-9)
        cx, cy = self.width() / 2, self.height() / 2

        def screen(p: np.ndarray) -> np.ndarray:
            rel = p - centre
            return np.column_stack([cx + k * (rel @ right), cy - k * (rel @ up)])

        light = view + 0.5 * up
        light /= np.linalg.norm(light)
        faces: list[tuple[float, np.ndarray, tuple[float, float, float]]] = []

        def add(
            points: np.ndarray, tris: np.ndarray, colour: tuple[float, float, float], cull: bool
        ) -> None:
            if not len(tris):
                return
            p = points[tris]
            n = np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0])
            norm = np.linalg.norm(n, axis=1)
            n = n / np.maximum(norm, 1e-12)[:, None]
            cen = p.mean(axis=1)
            outward = cen - centre
            n *= np.sign(np.sum(n * outward, axis=1))[:, None]  # point away from the middle
            facing = n @ view
            keep = facing > 0.0 if cull else np.ones(len(tris), dtype=bool)
            shade = 0.5 + 0.5 * np.clip(np.abs(n @ light), 0.0, 1.0)
            for i in np.flatnonzero(keep):
                c = tuple(min(1.0, v * float(shade[i])) for v in colour)
                faces.append((float(cen[i] @ view), screen(p[i]), c))  # type: ignore[arg-type]

        add(sketch.points, sketch.triangles, ENVELOPE, cull=True)
        for shape in self.data.shapes:
            selected = shape.name == self.data.selected
            colour = (0.84, 0.0, 0.56) if selected else (0.91, 0.56, 0.76)
            add(shape.points, shape.triangles, colour, cull=False)
        faces.sort(key=lambda f: f[0])
        painter.setPen(Qt.PenStyle.NoPen)
        for _depth, tri, c in faces:
            painter.setBrush(QBrush(QColor.fromRgbF(*c)))
            painter.drawPolygon(QPolygonF([QPointF(x, y) for x, y in tri]))

        def lines(polyline: np.ndarray, pen: QPen, hidden: QPen | None) -> None:
            front = (polyline - centre) @ view > 0.0
            xy = screen(polyline)
            for i in range(len(polyline) - 1):
                visible = front[i] and front[i + 1]
                if not visible and hidden is None:
                    continue
                painter.setPen(pen if visible else hidden)
                painter.drawLine(QPointF(*xy[i]), QPointF(*xy[i + 1]))

        for seam in sketch.seams:
            lines(seam, QPen(QColor(SEAM), 0.7), None)
        hidden = QPen(QColor(AXIS), 1.2)
        hidden.setStyle(Qt.PenStyle.DashLine)
        for name, _map_line, lines3d in self.data.axes:
            for polyline in lines3d:
                lines(polyline, QPen(QColor(AXIS), 2.6), hidden)
                top = screen(polyline[-8:-7])[0]
                painter.setPen(QPen(QColor(AXIS)))
                painter.drawText(QPointF(top[0] + 4, top[1]), name)


class PlacementView(QWidget):
    """The 3D sketch and the gore map side by side, with a caption (module docstring)."""

    def __init__(self) -> None:
        super().__init__()
        self.sketch = BalloonSketch()
        self.map = GoreMapView()
        caption = QLabel(
            "Where on the balloon: <b>3D</b> (drag: turn, wheel: zoom, double click: face "
            "the selected shape) · <b>gore map</b>, the gores side by side as cut (click: "
            "select, drag: move the shape, wheel: zoom, right drag: pan, double click: fit). "
            f"Selected shape <span style='color:{SELECTED}'>magenta</span>, symmetry axes "
            f"<span style='color:{AXIS}'>green</span>."
        )
        caption.setWordWrap(True)
        caption.setObjectName("placementCaption")
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.sketch, 1)
        row.addWidget(self.map, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(caption)
        layout.addLayout(row, 1)

    def set_data(self, data: PlacementData) -> None:
        """Draw ``data`` in both views."""
        self.sketch.set_data(data)
        self.map.set_data(data)
