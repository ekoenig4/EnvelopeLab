"""Visual editor of a revolved special shape's profile: drag its points and its horizontal
splits on the drawn outline (radius to the right, height up, the mirror image to the left).

The view only draws and reports what the mouse did; the shapes panel turns that into
edits with :mod:`envelopelab.project.shape_profile` (one undo step per drag).
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QResizeEvent,
)
from PySide6.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
)

from envelopelab.project.shape_profile import Profile, move_profile_points, profile_curve

HANDLE_RADIUS = 6.0  # px
PICK_DISTANCE = 9.0  # px: how close a press must be to a point or split
HANDLE_COLOR = "#1f77b4"
SELECTED_COLOR = "#ff7f0e"
SPLIT_COLOR = "#2ca02c"


class ShapeProfileView(QGraphicsView):
    """The profile of a revolved shape, edited with the mouse.

    * Press a point to select it (Ctrl/Shift+press adds or removes it), press empty space
      to clear the selection, and drag to move the selection; with a soft radius (m,
      along the control polygon) its neighbours follow. ``pointsDropped(profile)`` gives
      the new points when the drag ends.
    * Drag a split (green line across the shape) along the outline;
      ``splitDropped(index, rho, zeta)`` gives where it was let go, m.
    * Double-click the outline to add a point there: ``insertRequested(rho, zeta)``.
    * Delete or Backspace removes the selected points: ``removeRequested(indices)``.
    """

    pointsDropped = Signal(object)  # noqa: N815
    splitDropped = Signal(int, float, float)  # noqa: N815
    insertRequested = Signal(float, float)  # noqa: N815
    removeRequested = Signal(object)  # noqa: N815
    selectionChanged = Signal()  # noqa: N815

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("shapeProfileView")
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setMinimumSize(240, 240)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setToolTip(
            "Drag a point to reshape; Ctrl+click selects several. Drag a green split along "
            "the outline. Double-click the outline to add a point; Delete removes the "
            "selected points."
        )
        self.profile: Profile = []
        self.smooth = True
        self.splits: list[tuple[float, float]] = []
        self.curve = np.zeros((0, 2))
        self.selected: list[int] = []
        self.soft_radius = 0.0
        self._drag: str | None = None  # "points" or "split"
        self._drag_from = QPointF()
        self._drag_split = -1
        self._preview: Profile | None = None
        scene = self.scene()
        self._axis = scene.addPath(QPainterPath(), QPen(QColor("#888888"), 0, Qt.PenStyle.DotLine))
        self._base = scene.addPath(QPainterPath(), QPen(QColor("#888888"), 0))
        mirror = QPen(QColor("#9aa5b1"), 0, Qt.PenStyle.DashLine)
        self._mirror = scene.addPath(QPainterPath(), mirror)
        self._polygon = scene.addPath(
            QPainterPath(), QPen(QColor("#9aa5b1"), 0, Qt.PenStyle.DotLine)
        )
        curve = QPen(QColor(HANDLE_COLOR), 2.0)
        curve.setCosmetic(True)
        self._curve = scene.addPath(QPainterPath(), curve)
        split = QPen(QColor(SPLIT_COLOR), 2.0, Qt.PenStyle.DashLine)
        split.setCosmetic(True)
        self._split_lines = scene.addPath(QPainterPath(), split)
        self._handles: list[QGraphicsEllipseItem] = []
        self._split_handles: list[QGraphicsEllipseItem] = []
        self._labels: list[QGraphicsSimpleTextItem] = []

    # -- data ------------------------------------------------------------------------
    def set_shape(
        self,
        profile: Sequence[tuple[float, float]],
        smooth: bool,
        curve: np.ndarray,
        splits: np.ndarray,
    ) -> None:
        """Show a profile (points, m), its curve (m) and its splits ((rho, zeta), m)."""
        self.profile = [(float(r), float(z)) for r, z in profile]
        self.smooth = smooth
        self.curve = np.asarray(curve, dtype=np.float64).reshape(-1, 2)
        self.splits = [(float(r), float(z)) for r, z in np.asarray(splits).reshape(-1, 2)]
        self.selected = [i for i in self.selected if i < len(self.profile)]
        self._preview = None
        self._draw()
        self._fit()

    def select(self, indices: Sequence[int]) -> None:
        """Select these points (indices into the profile)."""
        self.selected = sorted({int(i) for i in indices if 0 <= i < len(self.profile)})
        self._draw()
        self.selectionChanged.emit()

    # -- drawing ---------------------------------------------------------------------
    def _draw(self) -> None:
        points = self._preview if self._preview is not None else self.profile
        curve = self.curve
        if self._preview is not None:
            try:
                curve = profile_curve(self._preview, self.smooth)
            except ValueError:
                curve = np.asarray(self._preview)
        right = QPainterPath()
        left = QPainterPath()
        for k, (r, z) in enumerate(curve):
            (right.lineTo if k else right.moveTo)(QPointF(r, -z))
            (left.lineTo if k else left.moveTo)(QPointF(-r, -z))
        self._curve.setPath(right)
        self._mirror.setPath(left)
        polygon = QPainterPath()
        for k, (r, z) in enumerate(points):
            (polygon.lineTo if k else polygon.moveTo)(QPointF(r, -z))
        self._polygon.setPath(polygon)
        top = float(max((z for _, z in points), default=1.0))
        widest = float(max((r for r, _ in points), default=1.0))
        axis = QPainterPath()
        axis.moveTo(0.0, 0.1 * top)
        axis.lineTo(0.0, -1.05 * top)
        self._axis.setPath(axis)
        base = QPainterPath()
        base.moveTo(-1.2 * widest, 0.0)
        base.lineTo(1.2 * widest, 0.0)
        self._base.setPath(base)
        splits = QPainterPath()
        for r, z in self.splits:
            splits.moveTo(-r, -z)
            splits.lineTo(r, -z)
        self._split_lines.setPath(splits if self._preview is None else QPainterPath())
        self._sync_handles(points)

    def _dot(self, colour: str, tip: str) -> QGraphicsEllipseItem:
        dot = QGraphicsEllipseItem(
            -HANDLE_RADIUS, -HANDLE_RADIUS, 2 * HANDLE_RADIUS, 2 * HANDLE_RADIUS
        )
        dot.setPen(QPen(QColor("white"), 1.5))
        dot.setBrush(QBrush(QColor(colour)))
        dot.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        dot.setZValue(10)
        dot.setToolTip(tip)
        self.scene().addItem(dot)
        return dot

    def _sync_handles(self, points: Sequence[tuple[float, float]]) -> None:
        for item in (*self._handles, *self._split_handles, *self._labels):
            self.scene().removeItem(item)
        self._handles, self._split_handles, self._labels = [], [], []
        for k, (r, z) in enumerate(points):
            colour = SELECTED_COLOR if k in self.selected else HANDLE_COLOR
            dot = self._dot(colour, f"point {k + 1}: radius {r:.3f} m, height {z:.3f} m")
            dot.setPos(QPointF(r, -z))
            self._handles.append(dot)
        if self._preview is not None:
            return
        for k, (r, z) in enumerate(self.splits):
            dot = self._dot(SPLIT_COLOR, f"split {k + 1}: drag along the outline")
            dot.setPos(QPointF(r, -z))
            self._split_handles.append(dot)
        # Tier letters between the splits, as the pieces are named (A at the rim).
        heights = (
            [0.0, *(z for _, z in self.splits), float(self.curve[-1, 1])] if len(self.curve) else []
        )
        for k in range(len(heights) - 1):
            label = QGraphicsSimpleTextItem(chr(ord("A") + k))
            label.setBrush(QBrush(QColor(SPLIT_COLOR)))
            label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
            label.setPos(QPointF(0.0, -0.5 * (heights[k] + heights[k + 1])))
            self.scene().addItem(label)
            self._labels.append(label)

    def _fit(self) -> None:
        if not self.profile:
            return
        pts = np.asarray([*self.profile, *map(tuple, self.curve)], dtype=np.float64)
        widest = max(float(pts[:, 0].max()), 1e-3)
        top, bottom = float(pts[:, 1].max()), min(float(pts[:, 1].min()), 0.0)
        span = max(widest, top - bottom, 1e-3)
        rect = QRectF(-1.25 * widest, -top - 0.1 * span, 2.5 * widest, (top - bottom) + 0.2 * span)
        self.scene().setSceneRect(rect)
        self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.fitInView(self.scene().sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    # -- picking ---------------------------------------------------------------------
    def _nearest_with_distance(
        self, at: QPointF, points: Sequence[tuple[float, float]]
    ) -> tuple[int | None, float]:
        """The point nearest view position ``at`` within :data:`PICK_DISTANCE` px (None)
        and its distance, px."""
        best, index = PICK_DISTANCE, None
        for k, (r, z) in enumerate(points):
            p = self.mapFromScene(QPointF(r, -z))
            d = math.hypot(p.x() - at.x(), p.y() - at.y())
            if d <= best:
                best, index = d, k
        return index, best

    def _nearest(self, at: QPointF, points: Sequence[tuple[float, float]]) -> int | None:
        return self._nearest_with_distance(at, points)[0]

    def point_at(self, at: QPointF) -> int | None:
        """Index of the profile point under view position ``at`` (px), or None."""
        return self._nearest(at, self.profile)

    def split_at(self, at: QPointF) -> int | None:
        """Index of the split handle under view position ``at`` (px), or None."""
        return self._nearest(at, self.splits)

    def on_curve(self, at: QPointF) -> tuple[float, float] | None:
        """The outline point nearest view position ``at`` when within reach (m), or None."""
        if not len(self.curve):
            return None
        k = self._nearest(at, [(float(r), float(z)) for r, z in self.curve])
        return None if k is None else (float(self.curve[k, 0]), float(self.curve[k, 1]))

    def _metres(self, at: QPointF) -> tuple[float, float]:
        p = self.mapToScene(at.toPoint())
        return float(p.x()), float(-p.y())

    # -- mouse and keys --------------------------------------------------------------
    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        at = event.position()
        split, d_split = self._nearest_with_distance(at, self.splits)
        point, d_point = self._nearest_with_distance(at, self.profile)
        if split is not None and (point is None or d_split <= d_point):
            self._drag, self._drag_split = "split", split
        elif point is not None:
            toggle = bool(
                event.modifiers()
                & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
            )
            if toggle:
                chosen = set(self.selected) ^ {point}
                self.select(sorted(chosen))
            elif point not in self.selected:
                self.select([point])
            self._drag = "points" if point in self.selected else None
        else:
            self.select([])
            self._drag = None
        self._drag_from = at
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag == "points" and self.selected:
            r0, z0 = self._metres(self._drag_from)
            r1, z1 = self._metres(event.position())
            self._preview = move_profile_points(
                self.profile, self.selected, r1 - r0, z1 - z0, self.soft_radius
            )
            self._draw()
        elif self._drag == "split":
            r, z = self._metres(event.position())
            k = int(np.argmin(np.hypot(self.curve[:, 0] - r, self.curve[:, 1] - z)))
            self.splits[self._drag_split] = (float(self.curve[k, 0]), float(self.curve[k, 1]))
            self._draw()
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        drag, self._drag = self._drag, None
        if drag == "points" and self._preview is not None:
            moved, self._preview = self._preview, None
            if moved != self.profile:
                self.pointsDropped.emit(moved)
            else:
                self._draw()
        elif drag == "split":
            r, z = self.splits[self._drag_split]
            self.splitDropped.emit(self._drag_split, r, z)
        event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self.point_at(event.position()) is None:
            hit = self.on_curve(event.position())
            if hit is not None:
                self.insertRequested.emit(*hit)
        event.accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self.selected:
            self.removeRequested.emit(list(self.selected))
            event.accept()
            return
        super().keyPressEvent(event)
