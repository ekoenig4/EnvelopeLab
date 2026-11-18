"""Where the special shapes sit on the balloon: a 3D view over a gore map, with nudging.

The *On the balloon* tab of the Special shapes mode (ADR-0044, ADR-0045), so positions
typed as numbers can be seen, and changed by hand, at once:

* **3D**: the envelope (gore and row seams), every shape as designed (the selected one in
  magenta), the symmetry axes in green. With the 3D View on it is drawn by the graphics
  card (:class:`BalloonGpuView`, PyVista); otherwise by :class:`BalloonSketch`, which
  needs no OpenGL. Drag the background to turn it, wheel to zoom; drag a shape over the
  envelope to move it. It turns to face a shape when that shape is selected; a double
  click faces it again.
* **Gore map** (:class:`GoreMapView`): the gores side by side as cut, at their true flat
  width (:mod:`envelopelab.project.placement_map`), with every footprint, base point,
  feed hole and axis. Click a shape to select it; drag it to move it. The wheel zooms
  about the pointer, the right button pans, a double click fits the map.
* **Nudge**: the arrow buttons, or the arrow keys in either view (Shift: five steps),
  move the selected shape by the chosen step round the envelope or up the tape.

Every move is one undo step through the workspace controller (a grouped shape takes its
group, a mirror twin its original). Nothing is computed here but what is drawn: the gore
map is built once per change as painter paths in metres and drawn through a transform,
so panning, zooming and dragging redraw no geometry point by point; the software 3D
sketch projects every point in one array operation, keeps its shaded picture until the
view or the data change, and draws only its seams, axes and shape markers while it is
being turned or while changes keep coming (the shaded picture follows once they stop).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
    QShowEvent,
    QTransform,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from envelopelab_app.view_tools import FitButton

SELECTED = "#d6008f"
OTHER = "#e98fc2"
AXIS = "#00a087"
#: The axis being placed (chosen: dashed and bright; under the pointer: dotted).
AXIS_PREVIEW = "#00c853"
GHOST = "#d6008f"
SEAM = "#4d4d4d"
#: Lines drawn for context only (e.g. the rigging not selected).
CONTEXT = "#6b7785"
#: Where the number pointed at or being edited acts (:mod:`envelopelab_app.hints`).
HINT = "#ff8f00"
GORE_FILL = ("#eef2f8", "#e3e9f2")
ENVELOPE = (0.86, 0.89, 0.94)
#: How long the 3D sketch waits after the last change before it draws its shaded
#: picture, ms (until then it draws its seams, axes and shape markers).
SETTLE_MS = 200
#: Nudge steps offered, mm (the default is the third).
NUDGE_STEPS_MM = (10, 25, 50, 100, 250)
#: Arrow key to the direction it nudges: (round the envelope, up the tape).
ARROWS = {
    Qt.Key.Key_Left: (-1.0, 0.0),
    Qt.Key.Key_Right: (1.0, 0.0),
    Qt.Key.Key_Up: (0.0, 1.0),
    Qt.Key.Key_Down: (0.0, -1.0),
}


@dataclass
class PlacedShape:
    """One shape as the views draw it (m).

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
        The shape as designed, on the envelope (3D).
    base3d : ndarray, shape (3,)
        Base point on the envelope.
    placement : Any
        The shape's placement (its lean is kept when it is moved).
    footprint_gs : (ndarray, ndarray) or None
        Footprint as gore positions and tape positions (m), for its mirror image.
    footprint3d : ndarray or None
        Footprint on the envelope (3D, m), for its mirror image.
    """

    name: str
    footprint: list[np.ndarray]
    holes: list[np.ndarray]
    base: np.ndarray
    points: np.ndarray
    triangles: np.ndarray
    base3d: np.ndarray
    placement: Any
    footprint_gs: tuple[np.ndarray, np.ndarray] | None = None
    footprint3d: np.ndarray | None = None


@dataclass
class AxisPreview:
    """A symmetry axis being placed, as the views draw it (m).

    Attributes
    ----------
    name : str
        Axis name.
    label : str
        Where it lies, in words (``centre of gore 6``).
    map_line : ndarray or None
        The chosen axis on the gore map (None: not chosen yet).
    lines3d : list of ndarray
        The chosen axis on the envelope.
    hover : ndarray or None
        The axis under the pointer on the gore map (where a click puts it).
    hover3d : list of ndarray
        The axis under the pointer on the envelope.
    ghosts, ghosts3d : list of ndarray
        Footprints of the mirror images the axis would make (gore map; envelope).
    """

    name: str
    label: str = ""
    map_line: np.ndarray | None = None
    lines3d: list[np.ndarray] = field(default_factory=list)
    hover: np.ndarray | None = None
    hover3d: list[np.ndarray] = field(default_factory=list)
    ghosts: list[np.ndarray] = field(default_factory=list)
    ghosts3d: list[np.ndarray] = field(default_factory=list)


@dataclass
class PlacementData:
    """Everything the views draw.

    Attributes
    ----------
    gore_map, sketch : Any
        :class:`~envelopelab.project.placement_map.GoreMap` and
        :class:`~envelopelab.project.placement_map.Sketch` (None: no envelope).
    axes : list of (str, ndarray, list of ndarray)
        Every symmetry axis: name, line on the map, lines on the envelope (3D).
    shapes : list of PlacedShape
        Every shape.
    selected : str or None
        The selected shape.
    place_at : callable, optional
        ``place_at(name, point)``: the placement of shape ``name`` with its base point at
        the envelope point nearest ``point`` (3D, m); for dragging in 3D.
    highlight : Highlight or None
        The selected design element (:mod:`envelopelab.project.highlight`), drawn in the
        highlight colour and faced when no shape is selected.
    context : list of ndarray
        Lines drawn thin and grey for context (e.g. every rigging line), m.
    hint : Highlight or None
        Where the number pointed at or being edited acts (:mod:`envelopelab_app.hints`),
        drawn in amber.
    hint_face : bool
        Turn to face the hint (its number is being edited, not only pointed at).
    """

    gore_map: Any = None
    sketch: Any = None
    axes: list[tuple[str, np.ndarray, list[np.ndarray]]] = field(default_factory=list)
    shapes: list[PlacedShape] = field(default_factory=list)
    selected: str | None = None
    place_at: Callable[[str, np.ndarray], Any] | None = None
    highlight: Any = None
    context: list[np.ndarray] = field(default_factory=list)
    hint: Any = None
    hint_face: bool = False

    @property
    def facing_key(self) -> str | None:
        """What the 3D view faces: the hint of a number being edited, else the selected
        shape, else the highlighted element."""
        if self.hint is not None and self.hint_face and self.hint.focus is not None:
            return f"hint:{self.hint.key}"
        if self.selected is not None:
            return f"shape:{self.selected}"
        return None if self.highlight is None else str(self.highlight.key)

    def facing_point(self) -> np.ndarray | None:
        """The point to face (m): the selected shape's base point, else the highlight's
        focus."""
        if self.hint is not None and self.hint_face and self.hint.focus is not None:
            return np.asarray(self.hint.focus, float)
        shape = next((s for s in self.shapes if s.name == self.selected), None)
        if shape is not None:
            return shape.base3d
        if self.highlight is not None and self.highlight.focus is not None:
            return np.asarray(self.highlight.focus, float)
        return None


def _path(parts: list[np.ndarray], closed: bool = False) -> QPainterPath:
    """Polylines (m) as one painter path."""
    path = QPainterPath()
    for part in parts:
        if len(part) < 2:
            continue
        path.addPolygon(QPolygonF([QPointF(float(x), float(y)) for x, y in part]))
        if closed:
            path.closeSubpath()
    return path


def _same(a: list[np.ndarray] | None, b: list[np.ndarray]) -> bool:
    """Two lists of polylines are equal."""
    return (
        a is not None
        and len(a) == len(b)
        and all(
            x.shape == y.shape and bool(np.array_equal(x, y)) for x, y in zip(a, b, strict=True)
        )
    )


def _pen(colour: str, width: float, dashed: bool = False, dotted: bool = False) -> QPen:
    """A pen whose width is in pixels whatever the painter's transform."""
    pen = QPen(QColor(colour), width)
    pen.setCosmetic(True)
    if dashed:
        pen.setStyle(Qt.PenStyle.DashLine)
    if dotted:
        pen.setStyle(Qt.PenStyle.DotLine)
    return pen


# -- gore map ----------------------------------------------------------------------------


class GoreMapView(QWidget):
    """The gores side by side with the shapes and axes on them (module docstring)."""

    #: A shape was clicked (its name).
    shapeClicked = Signal(str)  # noqa: N815 (Qt naming)
    #: A shape was dragged to a new placement (name, placement).
    shapeMoved = Signal(str, object)  # noqa: N815 (Qt naming)
    #: Placing an axis: the gore position under the pointer, and whether it was chosen
    #: (pressed or dragged) or only hovered.
    axisPointed = Signal(float, bool)  # noqa: N815 (Qt naming)
    #: An existing axis was pressed (its name): it is being dragged.
    axisGrabbed = Signal(str)  # noqa: N815 (Qt naming)
    #: The drag of a grabbed axis ended.
    axisReleased = Signal()  # noqa: N815 (Qt naming)

    MARGIN = 14.0

    def __init__(self) -> None:
        super().__init__()
        self.data = PlacementData()
        #: Placing an axis: the pointer places it instead of picking shapes.
        self.axis_mode = False
        self.preview: AxisPreview | None = None
        self._axis_drag = False
        self.zoom, self.pan = 1.0, QPointF(0.0, 0.0)
        self.bounds = QRectF(0.0, 0.0, 1.0, 1.0)
        self._pan_from: QPointF | None = None
        self._drag: tuple[str, QPointF, QPointF] | None = None  # shape, start, now (px)
        self._paths: dict[str, Any] = {}
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(220, 160)
        self.setObjectName("shapeGoreMap")
        self.setToolTip(
            "Click a shape: select it; drag it: move it. Drag empty space (or with the "
            "middle or right button): pan; wheel: zoom; double click or Fit: whole map"
        )
        self.fit_button = FitButton(self, self.fit, "Show the whole gore map again")

    # The drawing's frame: metres to pixels.
    def scale(self) -> float:
        b = self.bounds
        sx = (self.width() - 2 * self.MARGIN) / max(b.width(), 1e-9)
        sy = (self.height() - 2 * self.MARGIN) / max(b.height(), 1e-9)
        return self.zoom * max(min(sx, sy), 1e-9)

    def transform(self) -> QTransform:
        """Metres on the map to widget pixels (y up)."""
        k, b = self.scale(), self.bounds
        cx = self.width() / 2 + self.pan.x() - b.center().x() * k
        cy = self.height() / 2 + self.pan.y() + b.center().y() * k
        return QTransform(k, 0.0, 0.0, -k, cx, cy)

    def to_screen(self, x: float, y: float) -> QPointF:
        return self.transform().map(QPointF(x, y))

    def to_world(self, p: QPointF) -> tuple[float, float]:
        inverse, _ok = self.transform().inverted()
        q = inverse.map(p)
        return q.x(), q.y()

    def fit(self) -> None:
        self.zoom, self.pan = 1.0, QPointF(0.0, 0.0)
        self.update()

    def set_data(self, data: PlacementData) -> None:
        """Draw ``data``: its paths are built here, the envelope's only when the envelope
        changes and a shape's only when its footprint or feed holes do."""
        self.data = data
        m = data.gore_map
        if m is None:
            self._paths = {}
            self.update()
            return
        self.bounds = QRectF(0.0, 0.0, m.gores * m.column, m.length)
        if self._paths.get("map") is not m:
            self._paths = {"map": m, **self._envelope_paths(m)}
        axes = [line for _n, line, _l in data.axes]
        if not _same(self._paths.get("axis lines"), axes):
            self._paths["axis lines"] = axes
            self._paths["axes"] = _path(axes)
        old = self._paths.get("shapes", {})
        shapes = {}
        for s in data.shapes:
            hit = old.get(s.name)
            if hit is None or hit[2] is not s.footprint or not _same(hit[3], s.holes):
                hit = (_path(s.footprint), _path(s.holes), s.footprint, s.holes)
            shapes[s.name] = hit
        self._paths["shapes"] = shapes
        self.update()

    @staticmethod
    def _envelope_paths(m: Any) -> dict[str, Any]:
        """The gores' fills and outlines and the row seams, as paths in metres."""
        fills = (QPainterPath(), QPainterPath())
        for k, outline in enumerate(m.outlines):
            fills[k % 2].addPath(_path([outline], closed=True))
        rows = []
        for _label, lo, _hi in m.rows:
            if lo > 0.0:
                w = float(m.half_width(np.array([lo]))[0])
                rows += [
                    np.array([[(k + 0.5) * m.column - w, lo], [(k + 0.5) * m.column + w, lo]])
                    for k in range(m.gores)
                ]
        return {
            "fills": fills,
            "outlines": _path(m.outlines, closed=True),
            "rows": _path(rows),
        }

    def shape_at(self, p: QPointF) -> str | None:
        """The shape whose footprint (or base point) is under widget point ``p``."""
        x, y = self.to_world(p)
        pad = 6.0 / self.scale()
        best: tuple[float, str] | None = None
        for shape in self.data.shapes:
            pts = np.vstack(shape.footprint) if shape.footprint else shape.base[None]
            lo, hi = pts.min(axis=0), pts.max(axis=0)
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

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802 (Qt API)
        notches = event.angleDelta().y() / 120.0
        if notches:
            at = event.position()
            before = self.to_world(at)
            self.zoom = min(max(self.zoom * 1.25**notches, 1.0), 200.0)
            self.pan += at - self.to_screen(*before)
            self.update()
        event.accept()

    def gore_at(self, p: QPointF) -> float | None:
        """Gore position under widget point ``p`` (None off the map)."""
        from envelopelab.project.placement_map import gore_position_at

        if self.data.gore_map is None:
            return None
        return gore_position_at(self.data.gore_map, *self.to_world(p))

    def axis_at(self, p: QPointF) -> str | None:
        """The symmetry axis drawn within 6 px of widget point ``p``."""
        for name, line, _lines3d in self.data.axes:
            xy = np.array([[q.x(), q.y()] for q in map(lambda r: self.to_screen(*r), line)])
            if float(np.min(np.hypot(xy[:, 0] - p.x(), xy[:, 1] - p.y()))) < 6.0:
                return name
        return None

    def set_preview(self, preview: AxisPreview | None) -> None:
        self.preview = preview
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt API)
        if event.button() in (Qt.MouseButton.RightButton, Qt.MouseButton.MiddleButton):
            self._pan_from = event.position()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self.axis_mode:
            g = self.gore_at(event.position())
            if g is not None:
                self._axis_drag = True
                self.axisPointed.emit(g, True)
            return
        axis = self.axis_at(event.position()) if self.shape_at(event.position()) is None else None
        if axis is not None:
            self.axisGrabbed.emit(axis)
            self._axis_drag = True
            g = self.gore_at(event.position())
            if g is not None:
                self.axisPointed.emit(g, True)
            return
        name = self.shape_at(event.position())
        if name is None:
            self._pan_from = event.position()  # empty space: pan
            return
        if name != self.data.selected:
            self.shapeClicked.emit(name)
        self._drag = (name, event.position(), event.position())

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt API)
        if self._pan_from is not None:
            self.pan += event.position() - self._pan_from
            self._pan_from = event.position()
            self.update()
            return
        if self.axis_mode or self._axis_drag:
            g = self.gore_at(event.position())
            if g is not None:
                self.axisPointed.emit(g, self._axis_drag)
        if self._drag is not None:
            self._drag = (self._drag[0], self._drag[1], event.position())
            self.update()
            return
        m = self.data.gore_map
        if m is not None:
            x, y = self.to_world(event.position())
            if 0.0 <= y <= m.length and 0.0 <= x <= m.gores * m.column:
                k = int(min(x // m.column, m.gores - 1))
                row = next((r for r, lo, hi in m.rows if lo <= y <= hi), "")
                self.setToolTip(f"gore {k + 1}, row {row}, {y:.2f} m up the tape from the mouth")

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt API)
        if self._pan_from is not None:
            self._pan_from = None
            return
        if event.button() == Qt.MouseButton.LeftButton and self._axis_drag:
            self._axis_drag = False
            self.axisReleased.emit()
            return
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
        if m is None or not self._paths:
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No envelope")
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = self.transform()
        k = self.scale()
        painter.save()
        painter.setTransform(t)
        paths = self._paths
        painter.setPen(Qt.PenStyle.NoPen)
        for i, fill in enumerate(paths["fills"]):
            painter.fillPath(fill, QBrush(QColor(GORE_FILL[i])))
        painter.strokePath(paths["outlines"], _pen(SEAM, 1.0))
        painter.strokePath(paths["rows"], _pen("#9aa3ad", 0.8))
        painter.strokePath(paths["axes"], _pen(AXIS, 2.2))
        drag_name = None if self._drag is None else self._drag[0]
        shift = QPointF(0.0, 0.0)
        if self._drag is not None:
            d = self._drag[2] - self._drag[1]
            shift = QPointF(d.x() / k, -d.y() / k)
        for name, (footprint, holes, _f, _h) in paths["shapes"].items():
            selected = name == self.data.selected
            colour = SELECTED if selected else OTHER
            painter.save()
            if name == drag_name:
                painter.translate(shift)
            painter.strokePath(footprint, _pen(colour, 2.4 if selected else 1.4))
            painter.strokePath(holes, _pen(colour, 1.0, dashed=True))
            painter.restore()
        preview = self.preview
        if preview is not None:
            if preview.hover is not None:
                painter.strokePath(_path([preview.hover]), _pen(AXIS_PREVIEW, 1.2, dotted=True))
            if preview.map_line is not None:
                painter.strokePath(_path([preview.map_line]), _pen(AXIS_PREVIEW, 3.0, True))
            painter.strokePath(_path(preview.ghosts), _pen(GHOST, 1.6, dashed=True))
        painter.restore()
        if preview is not None and preview.map_line is not None:
            top = t.map(QPointF(float(preview.map_line[-1][0]), float(preview.map_line[-1][1])))
            painter.setPen(QPen(QColor(AXIS_PREVIEW)))
            bold = QFont(painter.font())
            bold.setBold(True)
            painter.setFont(bold)
            painter.drawText(QPointF(top.x() + 4, top.y() + 26), f"{preview.name}: {preview.label}")
        # Labels in pixels: gore numbers, row letters, axis and shape names.
        small = QFont(painter.font())
        small.setPointSizeF(max(small.pointSizeF() - 1.5, 6.0))
        painter.setFont(small)
        painter.setPen(QPen(QColor(SEAM)))
        for g in range(m.gores):
            top = t.map(QPointF((g + 0.5) * m.column, m.length))
            painter.drawText(QPointF(top.x() - 4, top.y() - 3), str(g + 1))
        painter.setPen(QPen(QColor("#5f6b7a")))
        for label, lo, hi in m.rows:
            p = t.map(QPointF(0.0, 0.5 * (lo + hi)))
            painter.drawText(QPointF(p.x() - 11, p.y() + 4), label)
        painter.setPen(QPen(QColor(AXIS)))
        for name, line, _lines3d in self.data.axes:
            top = t.map(QPointF(float(line[-1][0]), float(line[-1][1])))
            painter.drawText(QPointF(top.x() + 3, top.y() + 12), name)
        for shape in self.data.shapes:
            selected = shape.name == self.data.selected
            pen_colour = QColor(SELECTED if selected else OTHER)
            base = t.map(QPointF(float(shape.base[0]), float(shape.base[1])))
            if shape.name == drag_name:
                base += self._drag[2] - self._drag[1]  # type: ignore[index]
            painter.setBrush(QBrush(pen_colour))
            painter.setPen(QPen(pen_colour))
            painter.drawEllipse(base, 3.0, 3.0)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawText(QPointF(base.x() + 5, base.y() - 5), shape.name)


# -- 3D: shared camera geometry ---------------------------------------------------------


def _centre(sketch: Any) -> np.ndarray:
    pts = sketch.points
    return np.asarray(0.5 * (pts.min(axis=0) + pts.max(axis=0)), float)


def _facing(centre: np.ndarray, point: np.ndarray) -> tuple[float, float]:
    """Azimuth and elevation (deg) looking at ``point`` from outside, through ``centre``."""
    rel = np.asarray(point, float) - centre
    az = math.degrees(math.atan2(rel[1], rel[0]))
    el = math.degrees(math.atan2(rel[2], math.hypot(rel[0], rel[1])))
    return az, min(max(el, -80.0), 80.0)


class BalloonSketch(QWidget):
    """The envelope, the shapes and the axes in 3D, drawn with QPainter without OpenGL
    (module docstring)."""

    #: A shape was dragged to a new placement (name, placement).
    shapeMoved = Signal(str, object)  # noqa: N815 (Qt naming)
    #: Placing an axis: gore position under the pointer and whether it was chosen.
    axisPointed = Signal(float, bool)  # noqa: N815 (Qt naming)

    def __init__(self) -> None:
        super().__init__()
        self.data = PlacementData()
        self.axis_mode = False
        self.preview: AxisPreview | None = None
        self._axis_drag = False
        self.azimuth, self.elevation, self.zoom = -90.0, 10.0, 1.0
        self._turn: QPointF | None = None
        self._drag: tuple[str, np.ndarray | None] | None = None  # shape, envelope point
        self._faced: str | None = None
        self._picture: tuple[tuple[Any, ...], QPixmap] | None = None
        self._envelope: tuple[tuple[Any, ...], QPixmap] | None = None
        #: The shaded picture waits until the data has stopped changing for a moment, so
        #: a run of nudges or edits only redraws the light view.
        self._settle = QTimer(self)
        self._settle.setSingleShot(True)
        self._settle.setInterval(SETTLE_MS)
        self._settle.timeout.connect(self.update)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(200, 160)
        self.setObjectName("shapeSketch3d")
        self.setToolTip(
            "Drag: turn; drag a shape: move it over the envelope; wheel: zoom; double "
            "click: face the selected shape"
        )

    def set_data(self, data: PlacementData) -> None:
        self.data = data
        self._picture = None
        self._settle.start()
        if data.facing_key != self._faced:
            self._faced = data.facing_key
            self.face_selected()
        self.update()

    def face_selected(self) -> None:
        """Turn to look straight at the selected shape's base point (or, with no shape
        selected, at the highlighted element)."""
        point = self.data.facing_point()
        if point is None or self.data.sketch is None:
            return
        self.azimuth, self.elevation = _facing(_centre(self.data.sketch), point)
        self.update()

    def _frame(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        az, el = math.radians(self.azimuth), math.radians(self.elevation)
        view = np.array([math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)])
        right = np.array([-math.sin(az), math.cos(az), 0.0])
        return view, right, np.cross(view, right)

    def _projector(self) -> Callable[[np.ndarray], np.ndarray]:
        """Envelope-frame points (m) to widget pixels, for the current view."""
        sketch = self.data.sketch
        _view, right, up = self._frame()
        centre = _centre(sketch)
        extent = float(np.linalg.norm(np.ptp(sketch.points, axis=0)))
        k = self.zoom * 0.9 * min(self.width(), self.height()) / max(extent, 1e-9)
        cx, cy = self.width() / 2, self.height() / 2

        def screen(p: np.ndarray) -> np.ndarray:
            rel = np.asarray(p, float) - centre
            out: np.ndarray = np.stack([cx + k * (rel @ right), cy - k * (rel @ up)], axis=-1)
            return out

        return screen

    def _shape_near(self, p: QPointF) -> str | None:
        """The shape whose base point is drawn within 14 px of ``p`` (front side only)."""
        if self.data.sketch is None:
            return None
        view, _r, _u = self._frame()
        screen, centre = self._projector(), _centre(self.data.sketch)
        best: tuple[float, str] | None = None
        for shape in self.data.shapes:
            if (shape.base3d - centre) @ view <= 0.0:
                continue
            x, y = screen(shape.base3d)
            d = math.hypot(float(x) - p.x(), float(y) - p.y())
            if d < 14.0 and (best is None or d < best[0]):
                best = (d, shape.name)
        return None if best is None else best[1]

    def _envelope_point(self, p: QPointF) -> np.ndarray | None:
        """The front-facing envelope point drawn nearest widget point ``p``."""
        sketch = self.data.sketch
        view, _r, _u = self._frame()
        pts = sketch.points
        front = (pts - _centre(sketch)) @ view > 0.0
        if not front.any():
            return None
        xy = self._projector()(pts[front])
        i = int(np.argmin(np.hypot(xy[:, 0] - p.x(), xy[:, 1] - p.y())))
        out: np.ndarray = pts[front][i]
        return out

    def set_preview(self, preview: AxisPreview | None) -> None:
        self.preview = preview
        self.update()

    def _gore_at(self, p: QPointF) -> float | None:
        from envelopelab.project.placement_map import azimuth_position

        if self.data.sketch is None or self.data.gore_map is None:
            return None
        point = self._envelope_point(p)
        return None if point is None else azimuth_position(point, self.data.gore_map.gores)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt API)
        if self.axis_mode and event.button() == Qt.MouseButton.LeftButton:
            g = self._gore_at(event.position())
            if g is not None:
                self._axis_drag = True
                self.axisPointed.emit(g, True)
                return
        name = self._shape_near(event.position()) if self.data.place_at else None
        if name is not None and event.button() == Qt.MouseButton.LeftButton:
            self._drag = (name, None)
            return
        self._turn = event.position()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt API)
        if self.axis_mode and self._turn is None:
            g = self._gore_at(event.position())
            if g is not None:
                self.axisPointed.emit(g, self._axis_drag)
            return
        if self._drag is not None:
            self._drag = (self._drag[0], self._envelope_point(event.position()))
            self.update()
            return
        if self._turn is not None:
            d = event.position() - self._turn
            self._turn = event.position()
            self.azimuth -= 0.5 * d.x()
            self.elevation = min(max(self.elevation + 0.5 * d.y(), -85.0), 85.0)
            self.update()

    def mouseReleaseEvent(self, _event: QMouseEvent) -> None:  # noqa: N802 (Qt API)
        self._axis_drag = False
        drag, self._drag = self._drag, None
        self._turn = None
        self.update()  # the full picture again
        if drag is not None and drag[1] is not None and self.data.place_at is not None:
            self.shapeMoved.emit(drag[0], self.data.place_at(drag[0], drag[1]))

    def mouseDoubleClickEvent(self, _event: QMouseEvent) -> None:  # noqa: N802 (Qt API)
        self.face_selected()

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802 (Qt API)
        notches = event.angleDelta().y() / 120.0
        self.zoom = min(max(self.zoom * 1.2**notches, 0.5), 20.0)
        self.update()
        event.accept()

    def paintEvent(self, _event: object) -> None:  # noqa: N802 (Qt API)
        painter = QPainter(self)
        if self.data.sketch is None:
            painter.fillRect(self.rect(), QColor("#f7f9fc"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No envelope")
            return
        moving = self._turn is not None or self._settle.isActive()
        if moving:
            painter.fillRect(self.rect(), QColor("#f7f9fc"))
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            self._draw_lines(painter, light=True)
            self._draw_preview(painter)
            self._draw_hint(painter)
            return
        view_key = (self.azimuth, self.elevation, self.zoom, self.width(), self.height())
        key = (*view_key, id(self.data))
        if self._picture is None or self._picture[0] != key:
            picture = self._envelope_picture(view_key).copy()
            p = QPainter(picture)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            self._draw_shapes(p)
            self._draw_lines(p, light=False, seams=False)
            p.end()
            self._picture = (key, picture)
        painter.drawPixmap(0, 0, self._picture[1])
        self._draw_preview(painter)
        self._draw_hint(painter)
        if self._drag is not None and self._drag[1] is not None:
            ((x, y),) = self._projector()(self._drag[1][None])
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QPen(QColor(SELECTED), 2.0))
            painter.setBrush(QBrush(QColor(SELECTED)))
            painter.drawEllipse(QPointF(float(x), float(y)), 6.0, 6.0)
            painter.drawText(QPointF(float(x) + 9, float(y) - 6), f"move {self._drag[0]}")

    def set_hint(self, hint: Any, face: bool) -> None:
        """Draw where the number pointed at acts (amber, over the picture: no redraw of
        the envelope or the shapes); ``face``: turn to it (its number is being edited)."""
        self.data.hint, self.data.hint_face = hint, face
        if self.data.facing_key != self._faced:
            self._faced = self.data.facing_key
            if face:
                self.face_selected()
        self.update()

    def _draw_hint(self, painter: QPainter) -> None:
        hint = self.data.hint
        if hint is None or self.data.sketch is None:
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        view, _r, _u = self._frame()
        centre = _centre(self.data.sketch)
        screen = self._projector()
        front_pen, back_pen = QPen(QColor(HINT), 3.5), _pen(HINT, 1.2, dashed=True)
        for polyline in hint.lines:
            front = (polyline - centre) @ view > 0.0
            xy = screen(polyline)
            for visible, pen in ((True, front_pen), (False, back_pen)):
                seg = (front[:-1] & front[1:]) if visible else ~(front[:-1] & front[1:])
                if not seg.any():
                    continue
                path = QPainterPath()
                for i in np.flatnonzero(seg):
                    path.moveTo(*xy[i])
                    path.lineTo(*xy[i + 1])
                painter.strokePath(path, pen)

    def _draw_preview(self, painter: QPainter) -> None:
        """The axis being placed (dashed where it runs behind) and the mirror images it
        would make (their footprints, on the side facing the viewer)."""
        preview = self.preview
        if preview is None or self.data.sketch is None:
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        view, _r, _u = self._frame()
        centre = _centre(self.data.sketch)
        screen = self._projector()

        def stroke(polyline: np.ndarray, pen: QPen, hidden: QPen | None) -> None:
            front = (polyline - centre) @ view > 0.0
            xy = screen(polyline)
            for visible, use in ((True, pen), (False, hidden)):
                if use is None:
                    continue
                seg = (front[:-1] & front[1:]) if visible else ~(front[:-1] & front[1:])
                path = QPainterPath()
                for i in np.flatnonzero(seg):
                    path.moveTo(*xy[i])
                    path.lineTo(*xy[i + 1])
                painter.strokePath(path, use)

        for line in preview.hover3d:
            stroke(line, _pen(AXIS_PREVIEW, 1.2, dotted=True), None)
        for line in preview.lines3d:
            stroke(line, _pen(AXIS_PREVIEW, 3.0, dashed=True), _pen(AXIS_PREVIEW, 1.0, True))
        for loop in preview.ghosts3d:
            stroke(np.vstack([loop, loop[:1]]), _pen(GHOST, 2.0, dashed=True), None)
        if preview.lines3d:
            ((x, y),) = screen(preview.lines3d[0][-12:-11])
            painter.setPen(QPen(QColor(AXIS_PREVIEW)))
            painter.drawText(QPointF(float(x) + 6, float(y)), f"{preview.name}: {preview.label}")

    def _envelope_picture(self, view_key: tuple[float, ...]) -> QPixmap:
        """The shaded envelope and its seams for the current view, drawn once per view
        (the shapes are drawn over it: a nudge or an edit does not draw it again)."""
        key = (*view_key, id(self.data.sketch))
        if self._envelope is None or self._envelope[0] != key:
            picture = QPixmap(self.size())
            picture.fill(QColor("#f7f9fc"))
            p = QPainter(picture)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            sketch = self.data.sketch
            self._draw_faces(p, [(sketch.points, sketch.triangles, ENVELOPE, _centre(sketch))])
            self._draw_lines(p, light=False, axes=False)
            p.end()
            self._envelope = (key, picture)
        return self._envelope[1]

    def _draw_shapes(self, painter: QPainter) -> None:
        """The shapes on the side facing the viewer (the envelope hides the others)."""
        view, _r, _u = self._frame()
        centre = _centre(self.data.sketch)
        parts = []
        for shape in self.data.shapes:
            if not len(shape.triangles) or (shape.base3d - centre) @ view <= 0.0:
                continue
            colour = (0.84, 0.0, 0.56) if shape.name == self.data.selected else (0.91, 0.56, 0.76)
            parts.append((shape.points, shape.triangles, colour, shape.points.mean(axis=0)))
        self._draw_faces(painter, parts)

    def _draw_faces(
        self, painter: QPainter, parts: list[tuple[np.ndarray, np.ndarray, Any, np.ndarray]]
    ) -> None:
        """Shaded, depth-sorted triangles of each part (points, triangles, colour, a point
        inside it), those facing away from the viewer left out."""
        view, _right, up = self._frame()
        screen = self._projector()
        light = view + 0.5 * up
        light /= np.linalg.norm(light)
        depth, polys, colours = [], [], []
        for points, tris, colour, inside in parts:
            if not len(tris):
                continue
            p = points[tris]
            n = np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0])
            n /= np.maximum(np.linalg.norm(n, axis=1), 1e-12)[:, None]
            cen = p.mean(axis=1)
            n *= np.sign(np.sum(n * (cen - inside), axis=1))[:, None]  # point outward
            keep = n @ view > 0.0
            # 24 shade levels: one brush per level, not one per triangle.
            shade = np.round((0.5 + 0.5 * np.abs(n[keep] @ light)) * 24) / 24
            depth.append(cen[keep] @ view)
            polys.append(screen(p[keep]))
            colours.append(np.minimum(1.0, np.asarray(colour)[None] * shade[:, None]))
        if not depth:
            return
        order = np.argsort(np.concatenate(depth))
        all_polys = np.concatenate(polys)[order]
        all_colours = np.concatenate(colours)[order]
        painter.setPen(Qt.PenStyle.NoPen)
        last: tuple[float, ...] | None = None
        for tri, c in zip(all_polys.tolist(), all_colours.tolist(), strict=True):
            rgb = tuple(c)
            if rgb != last:
                painter.setBrush(QBrush(QColor.fromRgbF(*rgb)))
                last = rgb
            painter.drawPolygon(QPolygonF([QPointF(x, y) for x, y in tri]))

    def _draw_lines(
        self, painter: QPainter, light: bool, seams: bool = True, axes: bool = True
    ) -> None:
        """Seams, axes and (``light``: while turning or changing) the shapes' base
        points."""
        sketch = self.data.sketch
        view, _r, _u = self._frame()
        centre = _centre(sketch)
        screen = self._projector()

        def stroke(polyline: np.ndarray, pen: QPen, hidden: QPen | None) -> None:
            front = (polyline - centre) @ view > 0.0
            xy = screen(polyline)
            for visible in (True, False):
                use = pen if visible else hidden
                if use is None:
                    continue
                seg = (front[:-1] & front[1:]) if visible else ~(front[:-1] & front[1:])
                if not seg.any():
                    continue
                path = QPainterPath()
                for i in np.flatnonzero(seg):
                    path.moveTo(*xy[i])
                    path.lineTo(*xy[i + 1])
                painter.strokePath(path, use)

        for seam in sketch.seams if seams else []:
            stroke(seam, QPen(QColor(SEAM if not light else "#9aa3ad"), 0.7), None)
        hidden = QPen(QColor(AXIS), 1.2)
        hidden.setStyle(Qt.PenStyle.DashLine)
        for name, _map_line, lines3d in self.data.axes if axes else []:
            for polyline in lines3d:
                stroke(polyline, QPen(QColor(AXIS), 2.6), hidden)
                ((x, y),) = screen(polyline[-8:-7])
                painter.setPen(QPen(QColor(AXIS)))
                painter.drawText(QPointF(float(x) + 4, float(y)), name)
        if axes:
            for polyline in self.data.context:
                stroke(polyline, QPen(QColor(CONTEXT), 1.0), None)
            highlight = self.data.highlight
            for polyline in [] if highlight is None else highlight.lines:
                stroke(polyline, QPen(QColor(SELECTED), 3.0), _pen(SELECTED, 1.0, dashed=True))

        if light:
            for shape in self.data.shapes:
                if (shape.base3d - centre) @ view <= 0.0:
                    continue
                ((x, y),) = screen(shape.base3d[None])
                colour = QColor(SELECTED if shape.name == self.data.selected else OTHER)
                painter.setBrush(QBrush(colour))
                painter.setPen(QPen(colour))
                painter.drawEllipse(QPointF(float(x), float(y)), 5.0, 5.0)


# -- 3D on the graphics card -------------------------------------------------------------


class BalloonGpuView(QWidget):
    """The 3D view drawn by the graphics card (PyVista), for when the 3D View is on.

    Same content and gestures as :class:`BalloonSketch`: drag the background to turn,
    the wheel to zoom, drag a shape over the envelope to move it; it faces a shape when
    that shape is selected. Only the actors that change are rebuilt: the envelope when
    the design changes, the shapes and axes when they do; one frame is rendered per
    change (no timer re-rendering an unchanged view)."""

    #: A shape was dragged to a new placement (name, placement).
    shapeMoved = Signal(str, object)  # noqa: N815 (Qt naming)
    #: Placing an axis: gore position under the pointer and whether it was chosen.
    axisPointed = Signal(float, bool)  # noqa: N815 (Qt naming)

    def __init__(self) -> None:
        super().__init__()
        from pyvistaqt import QtInteractor

        self.data = PlacementData()
        self.axis_mode = False
        self._axis_drag = False
        self.plotter = QtInteractor(self, auto_update=False)
        self.plotter.set_background("#f7f9fc")
        self.plotter.enable_lightkit()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.plotter)
        self.setObjectName("shapeView3d")
        self._sketch: Any = None
        self._faced: str | None = None
        self._shape_keys: set[str] = set()
        #: What each shape actor shows: (its points array, its colour).
        self._shown: dict[str, tuple[np.ndarray, str]] = {}
        #: The axis lines and names drawn.
        self._axes_shown: tuple[list[np.ndarray] | None, list[str]] = (None, [])
        #: The context and highlight lines drawn.
        self._lines_shown: dict[str, list[np.ndarray]] = {}
        #: Fit the whole balloon in view after turning to the selection (the inlays).
        self.fit_on_face = False
        self._drag: tuple[str, np.ndarray | None] | None = None
        style = self.plotter.iren.interactor.GetInteractorStyle()
        for event, handler in (
            ("LeftButtonPressEvent", self._press),
            ("MouseMoveEvent", self._move),
            ("LeftButtonReleaseEvent", self._release),
        ):
            style.AddObserver(event, handler)

    def set_data(self, data: PlacementData) -> None:
        import pyvista as pv

        self.data = data
        p = self.plotter
        sketch = data.sketch
        if sketch is None:
            p.clear()
            self._sketch = None
            self._shown, self._shape_keys, self._axes_shown = {}, set(), (None, [])
            self._lines_shown = {}
            p.render()
            return
        if sketch is not self._sketch:
            faces = np.hstack([np.full((len(sketch.triangles), 1), 3), sketch.triangles])
            p.add_mesh(
                pv.PolyData(sketch.points, faces.ravel()),
                color=ENVELOPE,
                smooth_shading=True,
                name="envelope",
                reset_camera=False,
            )
            p.add_mesh(
                _lines(sketch.seams),
                color=SEAM,
                line_width=1,
                name="seams",
                pickable=False,
                reset_camera=False,
            )
            if self._sketch is None:
                p.reset_camera()
            self._sketch = sketch
        keys = set()
        for shape in data.shapes:
            key = f"shape:{shape.name}"
            keys.add(key)
            colour = SELECTED if shape.name == data.selected else OTHER
            if not len(shape.triangles):
                p.remove_actor(key)
                self._shown.pop(key, None)
                continue
            shown = self._shown.get(key)
            if shown is not None and shown[0] is shape.points and key in p.actors:
                if shown[1] != colour:  # only the colour changed: no new mesh
                    p.actors[key].prop.color = colour
                    self._shown[key] = (shape.points, colour)
                continue
            faces = np.hstack([np.full((len(shape.triangles), 1), 3), shape.triangles])
            p.add_mesh(
                pv.PolyData(shape.points, faces.ravel()),
                color=colour,
                smooth_shading=True,
                name=key,
                reset_camera=False,
            )
            self._shown[key] = (shape.points, colour)
        for key in self._shape_keys - keys:
            p.remove_actor(key)
            self._shown.pop(key, None)
        self._shape_keys = keys
        lines = [line for _n, _m, lines3d in data.axes for line in lines3d]
        names = [n for n, _m, lines3d in data.axes for _ in lines3d]
        if _same(self._axes_shown[0], lines) and self._axes_shown[1] == names:
            pass  # the axes are drawn already
        elif lines:
            p.add_mesh(
                _lines(lines),
                color=AXIS,
                line_width=4,
                name="axes",
                pickable=False,
                reset_camera=False,
            )
            p.add_point_labels(
                np.array([line[-8] for line in lines]),
                [n for n, _m, lines3d in data.axes for _ in lines3d],
                name="axis-labels",
                text_color=AXIS,
                font_size=12,
                shape_opacity=0.0,
                show_points=False,
                reset_camera=False,
            )
        else:
            p.remove_actor("axes")
            p.remove_actor("axis-labels")
        self._axes_shown = (lines, names)
        highlight = [] if data.highlight is None else list(data.highlight.lines)
        hint = [] if data.hint is None else list(data.hint.lines)
        for key, polylines, colour, width in (
            ("context", data.context, CONTEXT, 1),
            ("highlight", highlight, SELECTED, 5),
            ("hint", hint, HINT, 6),
        ):
            if _same(self._lines_shown.get(key), polylines):
                continue
            self._lines_shown[key] = polylines
            if polylines:
                p.add_mesh(
                    _lines(polylines),
                    color=colour,
                    line_width=width,
                    name=key,
                    pickable=False,
                    reset_camera=False,
                )
            else:
                p.remove_actor(key)
        if data.facing_key != self._faced:
            self._faced = data.facing_key
            self.face_selected()
        p.render()

    def set_hint(self, hint: Any, face: bool) -> None:
        """Draw where the number pointed at acts (one actor); ``face``: turn to it."""
        self.data.hint, self.data.hint_face = hint, face
        lines = [] if hint is None else list(hint.lines)
        if not _same(self._lines_shown.get("hint"), lines):
            self._lines_shown["hint"] = lines
            if lines:
                self.plotter.add_mesh(
                    _lines(lines),
                    color=HINT,
                    line_width=6,
                    name="hint",
                    pickable=False,
                    reset_camera=False,
                )
            else:
                self.plotter.remove_actor("hint")
        if self.data.facing_key != self._faced:
            self._faced = self.data.facing_key
            if face:
                self.face_selected()
        self.plotter.render()

    def face_selected(self) -> None:
        """Look straight at the selected shape's base point (or, with no shape selected,
        at the highlighted element)."""
        point = self.data.facing_point()
        if point is None or self.data.sketch is None:
            return
        centre = _centre(self.data.sketch)
        cam = self.plotter.camera
        distance = float(np.linalg.norm(np.asarray(cam.position) - np.asarray(cam.focal_point)))
        direction = point - centre
        direction /= max(float(np.linalg.norm(direction)), 1e-9)
        cam.focal_point = tuple(centre)
        cam.position = tuple(centre + distance * direction)
        # Mouth down; looking along the envelope axis, any up across it.
        cam.up = (0.0, 1.0, 0.0) if abs(direction[2]) > 0.999 else (0.0, 0.0, 1.0)
        if self.fit_on_face:
            self.plotter.reset_camera()  # the whole balloon, seen from there
        self.plotter.render()

    def _pick(self, keys: list[str]) -> tuple[str, np.ndarray] | None:
        from vtkmodules.vtkRenderingCore import vtkCellPicker

        p = self.plotter
        actors = {k: p.actors[k] for k in keys if k in p.actors}
        if not actors:
            return None
        picker = vtkCellPicker()
        picker.SetTolerance(0.0005)
        picker.PickFromListOn()
        for actor in actors.values():
            picker.AddPickList(actor)
        x, y = p.iren.interactor.GetEventPosition()
        if not picker.Pick(x, y, 0, p.renderer):
            return None
        key = next((k for k, a in actors.items() if a is picker.GetActor()), None)
        return None if key is None else (key, np.array(picker.GetPickPosition()))

    def set_preview(self, preview: AxisPreview | None) -> None:
        """Draw the axis being placed and the mirror images it would make."""
        p = self.plotter
        for key in ("axis-preview", "axis-hover", "axis-ghosts"):
            p.remove_actor(key)
        if preview is not None:
            if preview.lines3d:
                p.add_mesh(
                    _lines(preview.lines3d),
                    color=AXIS_PREVIEW,
                    line_width=6,
                    name="axis-preview",
                    pickable=False,
                    reset_camera=False,
                )
            if preview.hover3d:
                p.add_mesh(
                    _lines(preview.hover3d),
                    color=AXIS_PREVIEW,
                    line_width=2,
                    opacity=0.6,
                    name="axis-hover",
                    pickable=False,
                    reset_camera=False,
                )
            if preview.ghosts3d:
                loops = [np.vstack([g, g[:1]]) for g in preview.ghosts3d]
                p.add_mesh(
                    _lines(loops),
                    color=GHOST,
                    line_width=3,
                    name="axis-ghosts",
                    pickable=False,
                    reset_camera=False,
                )
        p.render()

    def _axis_point(self) -> float | None:
        from envelopelab.project.placement_map import azimuth_position

        hit = self._pick(["envelope"])
        if hit is None or self.data.gore_map is None:
            return None
        return azimuth_position(hit[1], self.data.gore_map.gores)

    def _press(self, style: Any, _event: str) -> None:
        if self.axis_mode:
            g = self._axis_point()
            if g is not None:
                self._axis_drag = True
                self.axisPointed.emit(g, True)
                return
            style.OnLeftButtonDown()
            return
        hit = self._pick([*sorted(self._shape_keys), "envelope"]) if self.data.place_at else None
        if hit is None or not hit[0].startswith("shape:"):
            style.OnLeftButtonDown()
            return
        self._drag = (hit[0].removeprefix("shape:"), None)

    def _move(self, style: Any, _event: str) -> None:
        if self.axis_mode and (self._axis_drag or not style.GetState()):
            g = self._axis_point()
            if g is not None:
                self.axisPointed.emit(g, self._axis_drag)
            if not self._axis_drag:
                style.OnMouseMove()
            return
        if self._drag is None:
            style.OnMouseMove()
            return
        hit = self._pick(["envelope"])
        if hit is not None:
            import pyvista as pv

            self._drag = (self._drag[0], hit[1])
            self.plotter.add_mesh(
                pv.Sphere(radius=0.15, center=hit[1]),
                color=SELECTED,
                name="drag-marker",
                pickable=False,
                reset_camera=False,
            )
            self.plotter.render()

    def _release(self, style: Any, _event: str) -> None:
        if self._axis_drag:
            self._axis_drag = False
            return
        drag, self._drag = self._drag, None
        if drag is None:
            style.OnLeftButtonUp()
            return
        self.plotter.remove_actor("drag-marker")
        self.plotter.render()
        if drag[1] is not None and self.data.place_at is not None:
            self.shapeMoved.emit(drag[0], self.data.place_at(drag[0], drag[1]))


def _lines(polylines: list[np.ndarray]) -> Any:
    """Polylines (m) as one PyVista line set."""
    import pyvista as pv

    points = np.vstack(polylines)
    cells, start = [], 0
    for part in polylines:
        cells.append(np.concatenate([[len(part)], np.arange(start, start + len(part))]))
        start += len(part)
    return pv.PolyData(points, lines=np.concatenate(cells))


# -- the tab -----------------------------------------------------------------------------


class PlacementView(QWidget):
    """The 3D view over the gore map (a splitter shares the height), a caption and the
    nudge bar (module docstring).

    ``gpu``: draw the 3D view with the graphics card when PyVista is available (it is
    created the first time the view is shown, so the window opens without waiting for
    OpenGL); otherwise, and until then, :class:`BalloonSketch`.
    """

    #: Nudge the selected shape: (round the envelope, up the tape), m.
    nudged = Signal(float, float)
    #: A shape was dragged to a new placement in the 3D view or on the map.
    shapeMoved = Signal(str, object)  # noqa: N815 (Qt naming)
    #: Placing an axis: gore position pointed at in either view, and whether chosen.
    axisPointed = Signal(float, bool)  # noqa: N815 (Qt naming)
    #: An existing axis was grabbed on the map (its name), and its drag ended.
    axisGrabbed = Signal(str)  # noqa: N815 (Qt naming)
    axisReleased = Signal()  # noqa: N815 (Qt naming)
    #: The axis bar's Place button, its Cancel button (or Escape), the gore line typed,
    #: and the choice of axis to mirror across (an axis name, or "" for a new one).
    axisAccepted = Signal()  # noqa: N815 (Qt naming)
    axisCancelled = Signal()  # noqa: N815 (Qt naming)
    axisTyped = Signal(float)  # noqa: N815 (Qt naming)
    axisTargetChosen = Signal(str)  # noqa: N815 (Qt naming)

    def __init__(self, gpu: bool = False) -> None:
        super().__init__()
        self.sketch = BalloonSketch()
        self.gpu_view: BalloonGpuView | None = None
        self._want_gpu = gpu
        self.map = GoreMapView()
        self.data = PlacementData()
        caption = QLabel(
            "<b>3D</b> (drag: turn; drag a shape: move it; wheel: zoom; double click: face "
            "the selected shape) over the <b>gore map</b>, the gores side by side as cut "
            "(click: select; drag: move; drag empty space: pan; wheel: zoom; double click or "
            "Fit: whole map). "
            f"Selected shape <span style='color:{SELECTED}'>magenta</span>, symmetry axes "
            f"<span style='color:{AXIS}'>green</span>."
        )
        caption.setWordWrap(True)
        caption.setObjectName("placementCaption")
        # Nudge bar: arrows and the step.
        bar = QHBoxLayout()
        bar.setContentsMargins(0, 0, 0, 0)
        bar.addWidget(QLabel("Nudge the selected shape (or arrow keys, Shift: ×5):"))
        self.nudge_buttons: dict[str, QToolButton] = {}
        for key, (text, tip, d) in {
            "left": ("◀", "Round the envelope, towards lower gores", (-1.0, 0.0)),
            "right": ("▶", "Round the envelope, towards higher gores", (1.0, 0.0)),
            "up": ("▲", "Up the tape, towards the crown", (0.0, 1.0)),
            "down": ("▼", "Down the tape, towards the mouth", (0.0, -1.0)),
        }.items():
            button = QToolButton()
            button.setText(text)
            button.setToolTip(tip)
            button.setObjectName(f"nudge_{key}")
            button.setAutoRepeat(True)
            button.clicked.connect(lambda _c=False, d=d: self.nudge(*d))
            self.nudge_buttons[key] = button
            bar.addWidget(button)
        self.step = QComboBox()
        self.step.setObjectName("nudgeStep")
        for mm in NUDGE_STEPS_MM:
            self.step.addItem(f"{mm} mm", mm / 1000.0)
        self.step.setCurrentIndex(2)
        bar.addWidget(self.step)
        bar.addStretch(1)
        self.axis_bar = self._axis_bar()
        self.split = QSplitter(Qt.Orientation.Vertical)
        self.split.setObjectName("placementSplitter")
        self.split.addWidget(self.sketch)
        self.split.addWidget(self.map)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(caption)
        layout.addLayout(bar)
        layout.addWidget(self.axis_bar)
        layout.addWidget(self.split, 1)
        self.sketch.shapeMoved.connect(self.shapeMoved)
        self.map.shapeMoved.connect(self.shapeMoved)
        for source in (self.sketch, self.map):
            source.axisPointed.connect(self.axisPointed)
        self.map.axisGrabbed.connect(self.axisGrabbed)
        self.map.axisReleased.connect(self.axisReleased)
        for view in (self.sketch, self.map):
            view.installEventFilter(self)

    @property
    def view3d(self) -> QWidget:
        """The 3D view shown (on the graphics card, or the sketch)."""
        return self.gpu_view if self.gpu_view is not None else self.sketch

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 (Qt API)
        super().showEvent(event)
        if self._want_gpu and self.gpu_view is None:
            self._want_gpu = False
            self.start_gpu()

    def start_gpu(self) -> bool:
        """Draw the 3D view with the graphics card (True when PyVista is available)."""
        from envelopelab_app.panels.view3d import pyvista_available

        if self.gpu_view is not None:
            return True
        if not pyvista_available():
            return False
        view = BalloonGpuView()
        view.shapeMoved.connect(self.shapeMoved)
        view.axisPointed.connect(self.axisPointed)
        view.axis_mode = self.map.axis_mode
        view.plotter.installEventFilter(self)
        self.split.replaceWidget(0, view)
        self.sketch.hide()
        self.gpu_view = view
        view.set_data(self.data)
        return True

    def set_data(self, data: PlacementData) -> None:
        """Draw ``data`` in both views."""
        self.data = data
        self.view3d.set_data(data)  # type: ignore[attr-defined]
        self.map.set_data(data)

    # -- placing a symmetry axis -------------------------------------------------------

    def _axis_bar(self) -> QWidget:
        """The bar shown while an axis is placed: what is being done, which axis (when
        mirroring), its name, its gore line, snapping, where it lies, Place and Cancel."""
        bar = QWidget()
        bar.setObjectName("axisBar")
        bar.setStyleSheet(f"#axisBar {{ border: 2px solid {AXIS_PREVIEW}; border-radius: 4px; }}")
        self.axis_title = QLabel()
        self.axis_title.setWordWrap(True)
        self.axis_target = QComboBox()
        self.axis_target.setObjectName("axisTarget")
        self.axis_target.setToolTip("Mirror across an existing axis, or place a new one")
        self.axis_target.currentIndexChanged.connect(
            lambda _i: self.axisTargetChosen.emit(str(self.axis_target.currentData() or ""))
        )
        self.axis_name = QLineEdit()
        self.axis_name.setObjectName("axisName")
        self.axis_name.setPlaceholderText("axis name")
        self.axis_line = QDoubleSpinBox()
        self.axis_line.setObjectName("axisLine")
        self.axis_line.setDecimals(2)
        self.axis_line.setSingleStep(0.5)
        self.axis_line.setWrapping(True)
        self.axis_line.setPrefix("gore ")
        self.axis_line.setKeyboardTracking(False)
        self.axis_line.setToolTip("Gore line: 6 = the centreline of gore 6, 6.5 = seam 6|7")
        self.axis_line.valueChanged.connect(lambda v: self.axisTyped.emit(float(v) - 0.5))
        self.axis_snap = QCheckBox("Snap to gore centres and seams")
        self.axis_snap.setObjectName("axisSnap")
        self.axis_snap.setChecked(True)
        self.axis_where = QLabel()
        self.axis_where.setObjectName("axisWhere")
        self.axis_ok = QPushButton("Place axis")
        self.axis_ok.setObjectName("axisPlace")
        self.axis_ok.setDefault(True)
        self.axis_ok.clicked.connect(self.axisAccepted)
        cancel = QPushButton("Cancel")
        cancel.setObjectName("axisCancel")
        cancel.clicked.connect(self.axisCancelled)
        row = QHBoxLayout()
        row.addWidget(self.axis_target)
        row.addWidget(self.axis_name)
        row.addWidget(self.axis_line)
        row.addWidget(self.axis_snap)
        row.addWidget(self.axis_where, 1)
        row.addWidget(self.axis_ok)
        row.addWidget(cancel)
        layout = QVBoxLayout(bar)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.addWidget(self.axis_title)
        layout.addLayout(row)
        bar.hide()
        return bar

    def begin_axis(
        self,
        title: str,
        accept: str,
        name: str,
        gores: int,
        targets: list[str] | None = None,
    ) -> None:
        """Show the axis bar and let the pointer place the axis in both views.

        ``targets``: the existing axes offered when mirroring (a "New axis" choice is
        added first); None hides the choice.
        """
        self.axis_title.setText(title)
        self.axis_ok.setText(accept)
        self.axis_name.setText(name)
        self.axis_line.blockSignals(True)
        self.axis_line.setRange(0.5, gores + 0.5)
        self.axis_line.blockSignals(False)
        self.axis_target.blockSignals(True)
        self.axis_target.clear()
        if targets is not None:
            self.axis_target.addItem("New axis (place it)", "")
            for t in targets:
                self.axis_target.addItem(f"Across {t}", t)
        self.axis_target.setVisible(targets is not None)
        self.axis_target.blockSignals(False)
        self.set_axis_mode(True)
        self.axis_bar.show()
        self.axis_name.setFocus()

    def end_axis(self) -> None:
        """Hide the axis bar and stop placing; the pointer picks shapes again."""
        self.axis_bar.hide()
        self.set_axis_mode(False)
        self.set_preview(None)

    def set_axis_mode(self, on: bool) -> None:
        """Let the pointer place an axis (True) or pick and move shapes (False)."""
        for view in (self.sketch, self.map, self.gpu_view):
            if view is not None:
                view.axis_mode = on
        self.map.setCursor(Qt.CursorShape.CrossCursor if on else Qt.CursorShape.ArrowCursor)
        self.sketch.setCursor(Qt.CursorShape.CrossCursor if on else Qt.CursorShape.ArrowCursor)

    def show_axis_line(self, line: float, where: str, editable: bool = True) -> None:
        """Show the chosen gore line (gore position) and where it lies in the bar."""
        self.axis_line.blockSignals(True)
        self.axis_line.setValue(line + 0.5)
        self.axis_line.blockSignals(False)
        self.axis_line.setEnabled(editable)
        self.axis_name.setEnabled(editable)
        self.axis_snap.setEnabled(editable)
        self.axis_where.setText(where)

    def set_preview(self, preview: AxisPreview | None) -> None:
        """Draw the axis being placed (and the mirror images it would make) in both
        views."""
        self.map.set_preview(preview)
        self.view3d.set_preview(preview)  # type: ignore[attr-defined]

    def nudge(self, hoop: float, tape: float, factor: float = 1.0) -> None:
        """Nudge the selected shape ``hoop``, ``tape`` steps (round, up) by the chosen step."""
        step = float(self.step.currentData()) * factor
        self.nudged.emit(hoop * step, tape * step)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 (Qt API)
        if event.type() == QEvent.Type.KeyPress:
            assert isinstance(event, QKeyEvent)
            if event.key() == Qt.Key.Key_Escape and self.axis_bar.isVisible():
                self.axisCancelled.emit()
                return True
            d = ARROWS.get(Qt.Key(event.key()))
            if d is not None:
                shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
                self.nudge(*d, factor=5.0 if shift else 1.0)
                return True
        return super().eventFilter(watched, event)


# -- the 3D inlay of the design modes ----------------------------------------------------


class EnvelopeInlay(QWidget):
    """The balloon in 3D beside a design mode's editor (Shape, Patterns, Rigging;
    ADR-0047): the envelope, the special shapes and symmetry axes, and the selected
    element (:func:`envelopelab.project.highlight.selection_highlight`) drawn in the
    highlight colour, the view turned to face it.

    Same drawing as the Special shapes' **On the balloon** tab (:class:`BalloonSketch`,
    or :class:`BalloonGpuView` on the graphics card when ``gpu`` and PyVista are
    available, started the first time the inlay is shown). Turn, zoom and double click
    (face the selection) work the same; shapes are not moved here.

    Parameters
    ----------
    name : str
        Object name.
    controller : WorkspaceController
        The workspace; its ``placement_provider`` gives the envelope, shapes and axes.
    gpu : bool
        Draw with the graphics card when shown.
    selection : callable, optional
        The selection to highlight (default: the controller's).
    rigging_context : bool
        Draw every rigging line thin and grey.
    """

    def __init__(
        self,
        name: str,
        controller: Any,
        gpu: bool = False,
        selection: Callable[[], str] | None = None,
        rigging_context: bool = False,
    ) -> None:
        from envelopelab_app.refresh import Refresher

        super().__init__()
        self.setObjectName(name)
        self.controller = controller
        self.selection = selection or (lambda: str(controller.selection))
        self.rigging_context = rigging_context
        self.sketch = BalloonSketch()
        self.sketch.setToolTip("Drag: turn; wheel: zoom; double click: face the selection")
        self.gpu_view: BalloonGpuView | None = None
        self._want_gpu = gpu
        self.data = PlacementData()
        self.caption = QLabel()
        self.caption.setObjectName("inlayCaption")
        self.caption.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(self.caption)
        layout.addWidget(self.sketch, 1)
        self.setMinimumSize(200, 180)
        self.refresher = Refresher(
            self,
            self.refresh,
            lambda: controller.revision,
            (
                controller.stateChanged,
                controller.sessionChanged,
                controller.selectionChanged,
                controller.shapesChanged,
                controller.artifactsChanged,
            ),
            defer_hidden=lambda: controller.defer_hidden,
        )
        controller.hintChanged.connect(self.show_hint)

    def show_hint(self) -> None:
        """Draw the controller's hint: where the number pointed at or being edited acts."""
        if not self.isVisible() and self.controller.defer_hidden:
            return
        hint = self.controller.hint_highlight()
        self.data.hint, self.data.hint_face = hint, self.controller.hint_focused
        self.view3d.set_hint(hint, self.controller.hint_focused)  # type: ignore[attr-defined]
        self._caption()

    @property
    def view3d(self) -> QWidget:
        """The 3D view shown (on the graphics card, or the sketch)."""
        return self.gpu_view if self.gpu_view is not None else self.sketch

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 (Qt API)
        super().showEvent(event)
        if self._want_gpu and self.gpu_view is None:
            self._want_gpu = False
            self.start_gpu()

    def start_gpu(self) -> bool:
        """Draw with the graphics card (True when PyVista is available)."""
        from envelopelab_app.panels.view3d import pyvista_available

        if self.gpu_view is not None:
            return True
        if not pyvista_available():
            return False
        view = BalloonGpuView()
        view.fit_on_face = True
        view.setToolTip(self.sketch.toolTip())
        layout = self.layout()
        assert layout is not None
        layout.replaceWidget(self.sketch, view)
        self.sketch.hide()
        self.gpu_view = view
        view.set_data(self.data)
        return True

    def changed(self) -> None:
        """The host's own selection changed (not the controller's): redraw."""
        self.refresher.dirty = True
        self.refresher.request()

    def refresh(self) -> None:
        """Redraw from the controller: the placement views' envelope, shapes and axes,
        with the selection highlighted."""
        from envelopelab.project.highlight import selection_highlight

        c = self.controller
        provider = getattr(c, "placement_provider", None)
        data = provider() if provider is not None else PlacementData()
        selection = self.selection()
        if not selection.startswith("shape:"):
            data.selected = None
        design = c.design
        rigging: dict[str, list[np.ndarray]] = {}
        highlight = None
        if design is not None and design.gores is not None and data.sketch is not None:
            rigging = c.rigging_polylines()
            try:
                rows = c.rows()
            except ValueError:
                rows = []
            highlight = selection_highlight(design, selection, rows=rows, rigging=rigging)
        data.highlight = highlight
        if self.rigging_context:
            data.context = [line for lines in rigging.values() for line in lines]
        data.hint, data.hint_face = c.hint_highlight(), c.hint_focused
        self.set_data(data)

    def set_data(self, data: PlacementData) -> None:
        """Draw ``data`` (its shapes are shown, not movable here)."""
        data.place_at = None
        self.data = data
        self._caption()
        self.view3d.set_data(data)  # type: ignore[attr-defined]

    def _caption(self) -> None:
        data = self.data
        highlight, hint = data.highlight, data.hint
        if data.sketch is None:
            what = "no standard-gore envelope to show"
        elif highlight is not None:
            what = f"<span style='color:{SELECTED}'>{highlight.label}</span>"
        else:
            what = "select a row, point or component to see it here"
        if hint is not None and data.sketch is not None:
            what = f"<span style='color:{HINT}'>▶ {hint.label}</span>; " + what
        self.caption.setText(f"<b>On the balloon</b>: {what}")
