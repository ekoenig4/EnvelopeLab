"""Standard-gore editor: profile canvas, control-point, panel-row and loft tables, gore
construction (lobe or flat chord, with its crest loft and seam bows), locks, outputs."""

from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QDoubleValidator,
    QIntValidator,
    QPainter,
    QPainterPath,
    QPen,
    QTransform,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsSceneMouseEvent,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from envelopelab.geometry.gore import MeridianProfile, loft_extra_width
from envelopelab.geometry.profile_editing import FALLOFFS, Falloff, curvature, move_points
from envelopelab.geometry.profile_segments import resolve_segments
from envelopelab.project.gore_design import (
    DEFAULT_CREST_LOFT,
    Interpolation,
    SegmentLayout,
    control_arrays,
    design_seam_bows,
    profile_equator,
    profile_from_arrays,
    profile_layout,
    row_zone,
    seam_fractions,
)
from envelopelab_app.controller import WorkspaceController
from envelopelab_app.refresh import Refresher

HANDLE_RADIUS = 6.0  # px


#: Handle colours: normal and selected.
HANDLE_COLOR = "#1f77b4"
SELECTED_COLOR = "#ff7f0e"
#: Colour of the parachute marks (as in the pattern and 3D views).
PARACHUTE_COLOR = "#9467bd"
#: Curvature-comb spikes drawn (about) and the longest spike, as a share of the view.
COMB_SPIKES = 160
COMB_LENGTH = 0.12


def _point_and_normal(
    profile: MeridianProfile, s: float
) -> tuple[tuple[float, float], tuple[float, float]]:
    """Point (r, z) at tape length ``s`` and the unit normal pointing away from the axis
    side of the curve (right of the direction of travel), m."""
    ds = 1e-3 * profile.meridian_length
    lo, hi = max(0.0, s - ds), min(profile.meridian_length, s + ds)
    dr = float(profile.radius_at(hi) - profile.radius_at(lo))
    dz = float(profile.height_at(hi) - profile.height_at(lo))
    norm = math.hypot(dr, dz) or 1.0
    point = (float(profile.radius_at(s)), float(profile.height_at(s)))
    return point, (dz / norm, -dr / norm)


class ControlPointHandle(QGraphicsEllipseItem):
    """A selectable, draggable control point (scene units: m, y axis down = -z).

    Dragging moves the selection (and, with soft selection, its neighbours) through the
    canvas, so a group moves as one.
    """

    def __init__(self, canvas: ProfileCanvas, index: int, r: float, z: float) -> None:
        super().__init__(-HANDLE_RADIUS, -HANDLE_RADIUS, 2 * HANDLE_RADIUS, 2 * HANDLE_RADIUS)
        self.canvas = canvas
        self.index = index
        self.setPos(QPointF(r, -z))
        self.setPen(QPen(QColor("white"), 1.5))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setZValue(10)
        self.setToolTip(
            f"control point {index + 1}: drag to move the selection; Ctrl+click to add to "
            "or remove from it; drag on empty space to box-select"
        )
        self._colour()

    def _colour(self) -> None:
        self.setBrush(QBrush(QColor(SELECTED_COLOR if self.isSelected() else HANDLE_COLOR)))

    def itemChange(self, change: QGraphicsItem.GraphicsItemChange, value: object) -> object:  # noqa: N802
        if change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            self._colour()
        return super().itemChange(change, value)

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent) -> None:  # noqa: N802
        toggle = bool(
            event.modifiers()
            & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
        )
        self.canvas.begin_drag(self, event.scenePos(), toggle)
        event.accept()

    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent) -> None:  # noqa: N802
        self.canvas.drag_to(event.scenePos())
        event.accept()

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent) -> None:  # noqa: N802
        self.canvas.end_drag()
        event.accept()


class ProfileCanvas(QGraphicsView):
    """2D meridian profile (radius right, height up) with selectable control points.

    Click a point, Ctrl/Shift+click to add or remove points, or drag a box on empty space
    to select several. Dragging any selected point moves the whole selection; with a soft
    radius (m, along the control polygon) the neighbours follow by the falloff
    (:mod:`envelopelab.geometry.profile_editing`). When a drag ends
    ``pointsDragged(indices, dr_m, dz_m)`` is emitted (``pointMoved(index, r_m, z_m)``
    for one point without soft selection); the editor turns it into one undoable command.
    """

    pointMoved = Signal(int, float, float)  # noqa: N815
    pointsDragged = Signal(object, float, float)  # noqa: N815
    pointsSelected = Signal()  # noqa: N815

    def __init__(self) -> None:
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setMinimumSize(320, 320)
        self.handles: list[ControlPointHandle] = []
        self.interpolation: Interpolation = "spline"
        self.soft_radius = 0.0
        self.falloff: Falloff = "smooth"
        self.show_comb = False
        self._drag_start: QPointF | None = None
        self._drag_points: tuple[np.ndarray, np.ndarray] | None = None
        self._drag_delta = (0.0, 0.0)
        self._curve = QGraphicsPathItem()
        self._curve.setPen(QPen(QColor(HANDLE_COLOR), 0))
        self._mirror = QGraphicsPathItem()
        pen = QPen(QColor("#9aa5b1"), 0)
        pen.setStyle(Qt.PenStyle.DashLine)
        self._mirror.setPen(pen)
        self._axis = QGraphicsPathItem()
        self._axis.setPen(QPen(QColor("#888888"), 0, Qt.PenStyle.DotLine))
        self.comb = QGraphicsPathItem()
        self.comb.setPen(QPen(QColor("#d62728"), 0))
        self.seam_ticks = QGraphicsPathItem()
        self.seam_ticks.setPen(QPen(QColor("#555555"), 0))
        self.row_highlight = QGraphicsPathItem()
        highlight = QPen(QColor(SELECTED_COLOR), 5.0)
        highlight.setCosmetic(True)
        self.row_highlight.setPen(highlight)
        self.equator = QGraphicsPathItem()
        self.equator.setPen(QPen(QColor("#2ca02c"), 0, Qt.PenStyle.DashLine))
        self.openings = QGraphicsPathItem()
        self.openings.setPen(QPen(QColor("#1f4e79"), 0, Qt.PenStyle.DashDotLine))
        self.parachute = QGraphicsPathItem()
        self.parachute.setPen(QPen(QColor(PARACHUTE_COLOR), 0, Qt.PenStyle.DashLine))
        for item in (
            self._axis,
            self._mirror,
            self.comb,
            self.row_highlight,
            self.seam_ticks,
            self.equator,
            self.openings,
            self.parachute,
            self._curve,
        ):
            self.scene().addItem(item)
        #: Row seams as fractions of the tape length, row letters, highlighted row.
        self.seams: list[float] = []
        self.row_names: list[str] = []
        self.highlighted_row: int | None = None
        #: Control points whose radius is locked (the mouth or top hole), m.
        self.locked_radii: dict[int, float] = {}
        #: Parachute overlap along the tape below the top opening, m (None: no parachute).
        self.seal_overlap: float | None = None
        self.labels: list[QGraphicsSimpleTextItem] = []
        # A bound slot: Qt drops it when the view is destroyed, before the scene's items.
        self.scene().selectionChanged.connect(self._scene_selection)

    def _scene_selection(self) -> None:
        self.pointsSelected.emit()

    # -- points -------------------------------------------------------------------------

    def set_points(
        self,
        r: np.ndarray,
        z: np.ndarray,
        interpolation: Interpolation = "spline",
        corners: frozenset[int] = frozenset(),
    ) -> None:
        """Show control points (m), joined as the design joins them; ``corners`` are the
        joints of a segment profile that are not smooth (drawn with a dark ring). The
        selection is kept when the number of points is unchanged."""
        self.interpolation = interpolation
        keep = self.selected_indices() if len(self.handles) == len(r) else []
        blocker = self.scene().blockSignals(True)
        for handle in self.handles:
            self.scene().removeItem(handle)
        self.handles = [
            ControlPointHandle(self, i, float(a), float(b))
            for i, (a, b) in enumerate(zip(r, z, strict=True))
        ]
        for handle in self.handles:
            self.scene().addItem(handle)
            handle.setSelected(handle.index in keep)
            if handle.index in self.locked_radii:
                pen = QPen(QColor("#1f4e79"), 2.5, Qt.PenStyle.DotLine)
                handle.setPen(pen)
                handle.setCursor(Qt.CursorShape.SizeVerCursor)
                handle.setToolTip(
                    handle.toolTip() + " (radius locked: the opening's diameter is locked; "
                    "the point moves up and down only)"
                )
            if handle.index in corners:
                handle.setPen(QPen(QColor("#222222"), 2.5))
                handle.setToolTip(handle.toolTip() + " (corner: the joint is not smooth)")
        self.scene().blockSignals(blocker)
        self.pointsSelected.emit()
        self._draw(r, z)
        span = max(float(np.max(r)), float(np.ptp(z)), 1e-3)
        rect = QRectF(
            -1.1 * float(np.max(r)),
            -float(np.max(z)) - 0.1 * span,
            2.2 * float(np.max(r)) + 1e-3,
            float(np.ptp(z)) + 0.2 * span,
        )
        self.scene().setSceneRect(rect)
        self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)

    def clear(self) -> None:
        """No design."""
        for handle in self.handles:
            self.scene().removeItem(handle)
        self.handles = []
        for item in (
            self._curve,
            self._mirror,
            self.comb,
            self.seam_ticks,
            self.equator,
            self.openings,
            self.parachute,
        ):
            item.setPath(QPainterPath())
        self.row_highlight.setPath(QPainterPath())
        self._clear_labels()

    def current_points(self) -> tuple[np.ndarray, np.ndarray]:
        """Positions of the handles (m)."""
        r = np.array([h.pos().x() for h in self.handles])
        z = np.array([-h.pos().y() for h in self.handles])
        return r, z

    def selected_indices(self) -> list[int]:
        """Indices of the selected control points, mouth first."""
        return [h.index for h in self.handles if h.isSelected()]

    def select(self, indices: list[int]) -> None:
        """Select exactly these control points."""
        wanted = set(indices)
        blocker = self.scene().blockSignals(True)
        for handle in self.handles:
            handle.setSelected(handle.index in wanted)
        self.scene().blockSignals(blocker)
        self.pointsSelected.emit()

    # -- dragging -----------------------------------------------------------------------

    def begin_drag(self, handle: ControlPointHandle, pos: QPointF, toggle: bool) -> None:
        """Start dragging from ``handle`` (scene position ``pos``)."""
        if toggle:
            handle.setSelected(not handle.isSelected())
        elif not handle.isSelected():
            self.select([handle.index])
        self._drag_start = QPointF(pos)
        self._drag_points = self.current_points()
        self._drag_delta = (0.0, 0.0)

    def drag_to(self, pos: QPointF) -> None:
        """Preview the drag at scene position ``pos`` (no command yet)."""
        if self._drag_start is None or self._drag_points is None:
            return
        selected = self.selected_indices()
        if not selected:
            return
        dr = float(pos.x() - self._drag_start.x())
        dz = float(self._drag_start.y() - pos.y())
        self._drag_delta = (dr, dz)
        r, z = move_points(*self._drag_points, selected, dr, dz, self.soft_radius, self.falloff)
        for index, radius in self.locked_radii.items():
            if 0 <= index < r.size:
                r[index] = radius
        for handle, a, b in zip(self.handles, r, z, strict=True):
            handle.setPos(QPointF(float(a), float(-b)))
        self._draw(r, z)

    def end_drag(self) -> None:
        """Finish a drag: emit the move as one edit (after this event returns, because the
        edit rebuilds the handles)."""
        selected = self.selected_indices()
        dr, dz = self._drag_delta
        self._drag_start, self._drag_points = None, None
        self._drag_delta = (0.0, 0.0)
        if not selected or (dr == 0.0 and dz == 0.0):
            return
        if len(selected) == 1 and self.soft_radius == 0.0:
            handle = self.handles[selected[0]]
            index, r, z = handle.index, float(handle.pos().x()), float(-handle.pos().y())
            QTimer.singleShot(0, lambda: self.pointMoved.emit(index, r, z))
        else:
            QTimer.singleShot(0, lambda: self.pointsDragged.emit(selected, dr, dz))

    def preview(self) -> None:
        """Redraw the curve through the handles' current positions."""
        if len(self.handles) >= 2:
            self._draw(*self.current_points())

    # -- drawing ------------------------------------------------------------------------

    def set_rows(
        self, seams: list[float], names: list[str], highlighted: int | None = None
    ) -> None:
        """Mark the panel rows on the profile: ``seams`` are the seams' fractions of the
        tape length (mouth first, one more than ``names``). The marks follow the curve
        while points are dragged, as fitted rows do."""
        self.seams, self.row_names, self.highlighted_row = list(seams), list(names), highlighted
        self.preview()

    def highlight_row(self, index: int | None) -> None:
        """Highlight row ``index`` (mouth first) on the profile, or none."""
        self.highlighted_row = index
        self.preview()

    def set_comb(self, on: bool) -> None:
        """Show or hide the curvature comb."""
        self.show_comb = on
        self.preview()

    def _draw(self, r: np.ndarray, z: np.ndarray) -> None:
        try:
            profile = profile_from_arrays(r, z, self.interpolation)
        except ValueError:
            return
        path, mirror = QPainterPath(), QPainterPath()
        path.moveTo(profile.r[0], -profile.z[0])
        mirror.moveTo(-profile.r[0], -profile.z[0])
        for a, b in zip(profile.r[1:], profile.z[1:], strict=True):
            path.lineTo(float(a), float(-b))
            mirror.lineTo(float(-a), float(-b))
        self._curve.setPath(path)
        self._mirror.setPath(mirror)
        axis = QPainterPath()
        axis.moveTo(0.0, -float(np.min(z)))
        axis.lineTo(0.0, -float(np.max(profile.z)))
        self._axis.setPath(axis)
        self.comb.setPath(self._comb_path(profile) if self.show_comb else QPainterPath())
        self._draw_rows(profile)
        self._draw_equator(profile)
        self._draw_openings(profile)

    def _label(
        self, text: str, r: float, z: float, colour: str, tip: str, above: bool = False
    ) -> None:
        """A label whose top-left corner is at (r, z), m; ``above`` puts it on top of that
        point instead (its height is in pixels, since labels ignore the zoom)."""
        label = QGraphicsSimpleTextItem(text)
        if above:
            label.setTransform(QTransform.fromTranslate(0.0, -label.boundingRect().height()))
        label.setBrush(QBrush(QColor(colour)))
        label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        label.setPos(QPointF(r, -z))
        label.setToolTip(tip)
        label.setZValue(5)
        self.scene().addItem(label)
        self.labels.append(label)

    def _clear_labels(self) -> None:
        for label in self.labels:
            self.scene().removeItem(label)
        self.labels = []

    def _draw_rows(self, profile: MeridianProfile) -> None:
        """Seam ticks across the curve, row letters beside their spans, and the
        highlighted row's span."""
        self._clear_labels()
        ticks, highlight = QPainterPath(), QPainterPath()
        if len(self.seams) >= 2 and len(self.row_names) == len(self.seams) - 1:
            length = profile.meridian_length
            size = 0.03 * max(profile.height, profile.max_width)
            s = np.clip(np.array(self.seams) * length, 0.0, length)
            for k, sk in enumerate(s):
                (r, z), (nr, nz) = _point_and_normal(profile, float(sk))
                ticks.moveTo(r - size * nr, -(z - size * nz))
                ticks.lineTo(r + size * nr, -(z + size * nz))
                if k == len(s) - 1:
                    break
                mid = 0.5 * (sk + s[k + 1])
                (mr, mz), (mnr, mnz) = _point_and_normal(profile, float(mid))
                name = self.row_names[k]
                self._label(
                    name,
                    mr + 2.0 * size * mnr,
                    mz + 2.0 * size * mnz,
                    "#444444",
                    f"row {name}: {s[k + 1] - sk:.3f} m of tape",
                )
            if self.highlighted_row is not None and self.highlighted_row < len(s) - 1:
                lo, hi = s[self.highlighted_row], s[self.highlighted_row + 1]
                band = (profile.s >= lo) & (profile.s <= hi)
                rr, zz = profile.r[band], profile.z[band]
                if rr.size:
                    highlight.moveTo(float(rr[0]), float(-zz[0]))
                    for a, b in zip(rr[1:], zz[1:], strict=True):
                        highlight.lineTo(float(a), float(-b))
        self.seam_ticks.setPath(ticks)
        self.row_highlight.setPath(highlight)

    def _draw_equator(self, profile: MeridianProfile) -> None:
        """A dashed line from the axis to the widest point, labelled."""
        eq = profile_equator(profile)
        path = QPainterPath()
        path.moveTo(0.0, -eq.z)
        path.lineTo(eq.r, -eq.z)
        self.equator.setPath(path)
        self._label(
            f"equator Ø {2 * eq.r:.2f} m",
            0.15 * eq.r,
            eq.z,
            "#2ca02c",
            f"widest point: radius {eq.r:.3f} m, {eq.height_above_mouth:.3f} m above the "
            f"mouth, {eq.s:.3f} m along the tape",
        )

    def _draw_openings(self, profile: MeridianProfile) -> None:
        """Dash-dot lines from the axis to the mouth and to the top opening, and a dashed
        line to the parachute's edge (the overlap down the tape from the top opening)."""
        path = QPainterPath()
        ends = (
            ("mouth", float(profile.r[0]), float(profile.z[0]), "the mouth", False),
            ("top hole", float(profile.r[-1]), float(profile.z[-1]), "the parachute hole", True),
        )
        for name, r, z, what, above in ends:
            path.moveTo(0.0, -z)
            path.lineTo(r, -z)
            self._label(
                f"{name} Ø {2 * r:.2f} m",
                0.05 * max(r, 1e-3),
                z,
                "#1f4e79",
                f"{what}: diameter {2 * r:.3f} m at height {z - float(profile.z[0]):.3f} m",
                above,
            )
        self.openings.setPath(path)
        chute = QPainterPath()
        overlap = self.seal_overlap
        if overlap is not None and 0.0 < overlap < profile.meridian_length:
            s_edge = profile.meridian_length - overlap
            r_edge = float(profile.radius_at(s_edge))
            z_edge = float(profile.height_at(s_edge))
            chute.moveTo(0.0, -z_edge)
            chute.lineTo(r_edge, -z_edge)
            self._label(
                f"parachute Ø {2 * r_edge:.2f} m",
                0.45 * r_edge,
                z_edge,
                PARACHUTE_COLOR,
                f"parachute edge: diameter {2 * r_edge:.3f} m, overlapping the envelope "
                f"{overlap:.3f} m down the tape from the top opening",
            )
        self.parachute.setPath(chute)

    @staticmethod
    def _comb_path(profile: MeridianProfile) -> QPainterPath:
        """Curvature comb: spikes of length proportional to the curvature, drawn on the
        side away from the centre of curvature, and the line joining their tips."""
        k = curvature(profile)
        step = max(1, profile.s.size // COMB_SPIKES)
        idx = np.arange(0, profile.s.size, step)
        tr = np.gradient(profile.r)[idx]
        tz = np.gradient(profile.z)[idx]
        norm = np.hypot(tr, tz)
        norm[norm == 0.0] = 1.0
        nr, nz = -tz / norm, tr / norm  # left normal, towards the centre where k > 0
        k_max = float(np.max(np.abs(k[idx]))) or 1.0
        scale = COMB_LENGTH * max(profile.height, profile.max_width) / k_max
        tip_r = profile.r[idx] - scale * k[idx] * nr
        tip_z = profile.z[idx] - scale * k[idx] * nz
        comb = QPainterPath()
        for a, b, c, d in zip(profile.r[idx], profile.z[idx], tip_r, tip_z, strict=True):
            comb.moveTo(float(a), float(-b))
            comb.lineTo(float(c), float(-d))
        comb.moveTo(float(tip_r[0]), float(-tip_z[0]))
        for c, d in zip(tip_r[1:], tip_z[1:], strict=True):
            comb.lineTo(float(c), float(-d))
        return comb

    def resizeEvent(self, event: object) -> None:  # noqa: N802
        super().resizeEvent(event)  # type: ignore[arg-type]
        self.fitInView(self.scene().sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)


def _item(text: str, editable: bool = True) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    if not editable:
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    return item


class GoreEditor(QWidget):
    """Central editor of standard-gore designs (see module docstring)."""

    def __init__(self, controller: WorkspaceController) -> None:
        super().__init__()
        self.controller = controller
        self._updating = False
        self._syncing = False
        self.header = QLabel()
        self.header.setObjectName("goreEditorHeader")
        self.canvas = ProfileCanvas()
        self.canvas.pointMoved.connect(self._point_moved)
        self.canvas.pointsDragged.connect(self._points_dragged)
        self.canvas.pointsSelected.connect(self._canvas_selection)

        self.points_table = QTableWidget(0, 2)
        self.points_table.setHorizontalHeaderLabels(["radius r (m)", "height z (m)"])
        self.points_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.points_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.points_table.itemChanged.connect(self._point_edited)
        add_point = QPushButton("Insert point after")
        add_point.clicked.connect(self._insert_point)
        del_point = QPushButton("Delete point")
        del_point.clicked.connect(self._delete_point)
        self.points_table.itemSelectionChanged.connect(self._table_selection)
        tools = self._build_point_tools()

        self.rows_table = QTableWidget(0, 5)
        self.rows_table.setHorizontalHeaderLabels(
            ["row", "height (m)", "zone", "bow bottom (mm)", "bow top (mm)"]
        )
        self.rows_table.setToolTip(
            "Flat-chord gores: seam bows, positive outward, at the middle of the panel's "
            "bottom and top seams.\nMeasured bows are edited here; bows from a crest loft "
            "are shown read-only (Freeze as measured bows to edit them).\n"
            "Type over a row's name to rename it everywhere; clear its zone for the "
            "design's first zone."
        )
        self.rows_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for col in (0, 3, 4):
            self.rows_table.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeMode.ResizeToContents
            )
        self.rows_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.rows_table.itemChanged.connect(self._row_edited)
        self.rows_table.itemSelectionChanged.connect(self._row_selected)
        split = QPushButton("Split row")
        split.clicked.connect(self._split_row)
        merge = QPushButton("Merge with next")
        merge.clicked.connect(self._merge_row)
        fit = QPushButton("Fit rows to meridian")
        fit.clicked.connect(lambda: self.controller.edit("fit_rows"))

        self.loft_table = QTableWidget(0, 3)
        self.loft_table.setObjectName("loftTable")
        self.loft_table.setHorizontalHeaderLabels(
            ["station (0–1)", "lobe ratio k = ρ/r", "extra width"]
        )
        self.loft_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.loft_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.loft_table.setToolTip(
            "Fabric bulge between adjacent load tapes. Each gore's lobe is a circular arc of "
            "radius ρ = k·r (r = tape radius), interpolated between stations along the tape\n"
            "(station: fraction of the tape length, 0 at the mouth, 1 at the top opening).\n"
            "k = 1: small bulge (lobe on the circle through the tapes); larger k: flatter, "
            "narrower gores; smaller k: fuller, wider gores.\n"
            "Extra width: flat gore width over the straight tape-to-tape chord."
        )
        self.loft_table.itemChanged.connect(self._loft_edited)
        self.loft_status = QLabel()
        self.loft_status.setObjectName("loftStatus")
        self.loft_status.setWordWrap(True)
        add_loft = QPushButton("Add station")
        add_loft.clicked.connect(self._add_loft_station)
        del_loft = QPushButton("Remove station")
        del_loft.clicked.connect(self._remove_loft_station)
        clear_loft = QPushButton("Small bulge (no loft)")
        clear_loft.clicked.connect(lambda: self.controller.edit("set_loft", None))

        self.construction = QComboBox()
        self.construction.setObjectName("construction")
        self.construction.addItem("Lobe (straight seams)", "lobe")
        self.construction.addItem("Flat chord (bowed seams)", "flat_chord")
        self.construction.setToolTip(
            "Lobe: the gore is cut wider than the tape-to-tape chord and bulges between tapes "
            "(gore loft).\nFlat chord: every row is a flat trapezoid between the tapes and "
            "the gore is lofted lengthwise by bowed horizontal seams (crest loft)."
        )
        self.construction.activated.connect(self._construction_chosen)
        self.interpolation = QComboBox()
        self.interpolation.setObjectName("interpolation")
        self.interpolation.addItem("Spline", "spline")
        self.interpolation.addItem("Straight segments", "linear")
        self.interpolation.addItem("Segments (lines, arcs, curves)", "segments")
        self.interpolation.setToolTip(
            "How the profile runs between control points: a smooth spline, or straight tape "
            "segments (panel sides of a measured pattern)."
        )
        self.interpolation.activated.connect(self._interpolation_chosen)
        construction_box = QGroupBox("Gore construction")
        construction_layout = QFormLayout(construction_box)
        construction_layout.addRow("Gores cut as", self.construction)
        construction_layout.addRow("Profile between points", self.interpolation)

        self.crest_fraction = QDoubleSpinBox()
        self.crest_fraction.setObjectName("crestFraction")
        self.crest_fraction.setRange(0.0, 50.0)
        self.crest_fraction.setDecimals(3)
        self.crest_fraction.setSingleStep(0.1)
        self.crest_fraction.setSuffix(" % of r")
        self.crest_fraction.setToolTip(
            "Crest offset over the tape radius where the taper is 1 (δ = fraction · taper · r)."
        )
        self.crest_fraction.editingFinished.connect(self._crest_fraction_edited)
        self.crest_table = QTableWidget(0, 3)
        self.crest_table.setObjectName("crestTable")
        self.crest_table.setHorizontalHeaderLabels(["station (0–1)", "taper", "follows seam"])
        self.crest_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.crest_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.crest_table.setToolTip(
            "Taper of the crest offset along the tape (station: fraction of the tape length, "
            "0 at the mouth, 1 at the top opening), interpolated linearly and held beyond the "
            "first and last station.\nFollows seam: put the station on a row's bottom seam; "
            "it then moves with the seam when rows are resized, renamed or split. Typing a "
            "station frees it."
        )
        self.crest_table.itemChanged.connect(self._crest_edited)
        self.crest_status = QLabel()
        self.crest_status.setObjectName("crestStatus")
        self.crest_status.setWordWrap(True)
        add_taper = QPushButton("Add station")
        add_taper.clicked.connect(self._add_crest_station)
        del_taper = QPushButton("Remove station")
        del_taper.clicked.connect(self._remove_crest_station)
        self.use_crest = QPushButton("Use crest loft")
        self.use_crest.setToolTip("Replace the seam bows by the default crest loft, then edit it.")
        self.use_crest.clicked.connect(self._use_crest)
        self.freeze_crest = QPushButton("Freeze as measured bows")
        self.freeze_crest.setToolTip(
            "Write the bows of the crest loft into the rows, to edit single seams."
        )
        self.freeze_crest.clicked.connect(lambda: self.controller.edit("freeze_crest_bows"))
        self.straight_seams = QPushButton("Straight seams")
        self.straight_seams.setToolTip("Remove the crest loft and every seam bow.")
        self.straight_seams.clicked.connect(lambda: self.controller.edit("set_crest_loft", None))
        self.crest_box = QGroupBox("Crest loft (lengthwise loft, bowed seams)")
        self.crest_box.setObjectName("crestBox")
        crest_layout = QVBoxLayout(self.crest_box)
        crest_layout.addWidget(self.crest_status)
        crest_form = QFormLayout()
        crest_form.addRow("Crest fraction", self.crest_fraction)
        crest_layout.addLayout(crest_form)
        crest_layout.addWidget(self.crest_table)
        crest_buttons = QHBoxLayout()
        for b in (add_taper, del_taper):
            crest_buttons.addWidget(b)
        crest_layout.addLayout(crest_buttons)
        seam_buttons = QHBoxLayout()
        for b in (self.use_crest, self.freeze_crest, self.straight_seams):
            seam_buttons.addWidget(b)
        crest_layout.addLayout(seam_buttons)

        self.gore_count = QSpinBox()
        self.gore_count.setRange(3, 200)
        self.gore_count.editingFinished.connect(self._count_edited)
        self.locks: dict[str, QCheckBox] = {}
        self.lock_values: dict[str, QLineEdit] = {}
        locks_box = QGroupBox("Constraint locks")
        locks_box.setToolTip(
            "A lock holds its quantity through profile edits. Type a value to lock the "
            "quantity there: the profile is solved to it, keeping the other locks."
        )
        locks_layout = QFormLayout(locks_box)
        for name, text, unit in (
            ("height", "Fixed height", "m"),
            ("volume", "Fixed volume", "m³"),
            ("max_diameter", "Fixed maximum diameter", "m"),
            ("mouth_diameter", "Fixed mouth diameter", "m"),
            ("top_diameter", "Fixed top (parachute) hole diameter", "m"),
            ("gore_count", "Fixed N (gore count)", ""),
        ):
            box = QCheckBox(text)
            box.toggled.connect(lambda on, n=name: self._lock_toggled(n, on))
            self.locks[name] = box
            value = QLineEdit()
            value.setObjectName(f"lockValue_{name}")
            value.setPlaceholderText(unit)
            value.setValidator(
                QIntValidator(3, 200) if name == "gore_count" else QDoubleValidator()
            )
            value.editingFinished.connect(lambda n=name: self._lock_value_edited(n))
            self.lock_values[name] = value
            locks_layout.addRow(box, value)
        locks_layout.addRow("Gores N", self.gore_count)

        self.outputs: dict[str, QLabel] = {}
        outputs_box = QGroupBox("Live outputs")
        outputs_layout = QFormLayout(outputs_box)
        for key, text in (
            ("meridian_length", "Meridian (tape) length"),
            ("height", "Height"),
            ("max_diameter", "Maximum diameter"),
            ("equator", "Equator (widest point)"),
            ("openings", "Mouth / top hole Ø"),
            ("parachute", "Parachute Ø (seated edge)"),
            ("area", "Fabric area"),
            ("volume", "Volume"),
            ("gross_lift", "Gross lift"),
            ("envelope_mass", "Estimated envelope mass"),
            ("rigging_mass", "Parachute and rigging mass"),
            ("lift_margin", "Lift margin (after rigging and payload)"),
            ("sources", "Material sources"),
        ):
            label = QLabel("-")
            label.setObjectName(f"output_{key}")
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.outputs[key] = label
            outputs_layout.addRow(text, label)
        self.output_message = QLabel()
        self.output_message.setWordWrap(True)
        self.output_message.setStyleSheet("color: #b00020;")
        outputs_layout.addRow(self.output_message)

        side = QWidget()
        side_layout = QVBoxLayout(side)
        side_layout.addWidget(QLabel("Profile control points (mouth first)"))
        side_layout.addWidget(self.points_table)
        buttons = QHBoxLayout()
        buttons.addWidget(add_point)
        buttons.addWidget(del_point)
        side_layout.addLayout(buttons)
        side_layout.addWidget(tools)
        side_layout.addWidget(QLabel("Panel rows (mouth first)"))
        side_layout.addWidget(self.rows_table)
        row_buttons = QHBoxLayout()
        for b in (split, merge, fit):
            row_buttons.addWidget(b)
        side_layout.addLayout(row_buttons)
        side_layout.addWidget(construction_box)
        self.lobe_box = QGroupBox("Gore loft (lobe bulge between tapes)")
        self.lobe_box.setObjectName("lobeBox")
        lobe_layout = QVBoxLayout(self.lobe_box)
        lobe_layout.addWidget(self.loft_status)
        lobe_layout.addWidget(self.loft_table)
        loft_buttons = QHBoxLayout()
        for b in (add_loft, del_loft, clear_loft):
            loft_buttons.addWidget(b)
        lobe_layout.addLayout(loft_buttons)
        side_layout.addWidget(self.lobe_box)
        side_layout.addWidget(self.crest_box)
        side_layout.addWidget(locks_box)
        side_layout.addWidget(outputs_box)

        # The tables and outputs scroll, so they do not set the window's minimum height.
        side_scroll = QScrollArea()
        side_scroll.setWidget(side)
        side_scroll.setWidgetResizable(True)
        side_scroll.setFrameShape(QFrame.Shape.NoFrame)
        splitter = QSplitter()
        splitter.setObjectName("goreEditorSplitter")
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self.canvas)
        splitter.addWidget(side_scroll)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout = QVBoxLayout(self)
        layout.addWidget(self.header)
        layout.addWidget(splitter, 1)

        self.refresher = Refresher(
            self,
            self.refresh,
            lambda: controller.revision,
            (controller.stateChanged, controller.sessionChanged),
            defer_hidden=lambda: controller.defer_hidden,
        )
        controller.fileChanged.connect(self._update_header)
        self.refresh()

    # -- refresh ------------------------------------------------------------------------

    def _update_header(self) -> None:
        session = self.controller.session
        if session is None:
            self.header.setText("No project open")
            return
        mark = " ● unsaved changes" if session.unsaved_groups() else ""
        kind = "Standard gore" if self.controller.is_gore else "Special shape"
        self.header.setText(f"<b>{session.design.meta.name}</b> — {kind} editor{mark}")

    def refresh(self) -> None:
        """Show the current design."""
        self._updating = True
        try:
            self._update_header()
            design = self.controller.design
            gore = design is not None and design.gores is not None
            self.setEnabled(gore)
            if not gore or design is None or design.gores is None:
                self.canvas.clear()
                self.points_table.setRowCount(0)
                self.rows_table.setRowCount(0)
                self.loft_table.setRowCount(0)
                self.loft_status.setText("")
                self.crest_table.setRowCount(0)
                self.crest_status.setText("")
                for label in self.outputs.values():
                    label.setText("-")
                self.output_message.setText(
                    "" if design is None else "Special shapes are edited in the 3D view."
                )
                return
            r, z = control_arrays(design)
            layout = profile_layout(design.gores)
            corners = (
                frozenset(k for k, s in enumerate(layout.segments) if k > 0 and not s.smooth)
                if isinstance(layout, SegmentLayout)
                else frozenset()
            )
            self.canvas.seal_overlap = (
                design.gores.seal_overlap if design.parachute is not None else None
            )
            self.canvas.seams = seam_fractions(design)
            self.canvas.row_names = [row.letter for row in design.gores.panel_rows]
            selected_rows = self.rows_table.selectionModel().selectedRows()
            self.canvas.highlighted_row = selected_rows[0].row() if selected_rows else None
            locks = self.controller.session.project.locks if self.controller.session else None
            self.canvas.locked_radii = {}
            if locks is not None and locks.mouth_diameter is not None:
                self.canvas.locked_radii[0] = 0.5 * locks.mouth_diameter
            if locks is not None and locks.top_diameter is not None:
                self.canvas.locked_radii[len(r) - 1] = 0.5 * locks.top_diameter
            self.canvas.set_points(r, z, layout, corners)
            self._show_points(r, z, layout)
            session = self.controller.session
            assert session is not None
            rows = design.gores.panel_rows
            flat = design.gores.construction == "flat_chord"
            computed = flat and design.gores.crest_loft is not None
            bows = design_seam_bows(design) if flat else []
            self.rows_table.setRowCount(len(rows))
            for i, row in enumerate(rows):
                self.rows_table.setItem(i, 0, _item(row.letter))
                self.rows_table.setItem(i, 1, _item(f"{row.finished_height:.4f}"))
                zone = row_zone(design, session.patterns, row.letter)
                self.rows_table.setItem(i, 2, _item(zone))
                for col, bow in (
                    (3, bows[i][0] if flat else 0.0),
                    (4, bows[i][1] if flat else 0.0),
                ):
                    self.rows_table.setItem(
                        i, col, _item(f"{bow * 1e3:.2f}", editable=not computed)
                    )
            self.rows_table.setColumnHidden(3, not flat)
            self.rows_table.setColumnHidden(4, not flat)
            self.construction.setCurrentIndex(self.construction.findData(design.gores.construction))
            self.interpolation.setCurrentIndex(
                self.interpolation.findData(design.gores.profile_interpolation)
            )
            self.lobe_box.setVisible(not flat)
            self.crest_box.setVisible(flat)
            self._show_loft()
            if flat:
                self._show_crest(bows)
            self.gore_count.setValue(design.gores.count)
            locks = session.project.locks
            profile = profile_from_arrays(r, z, profile_layout(design.gores))
            current = {
                "height": f"{profile.height:.3f}",
                "max_diameter": f"{profile.max_width:.3f}",
                "mouth_diameter": f"{2.0 * r[0]:.3f}",
                "top_diameter": f"{2.0 * r[-1]:.3f}",
                "volume": ""
                if self.controller.outputs is None
                else f"{self.controller.outputs.volume:.2f}",
                "gore_count": str(design.gores.count),
            }
            for name, box in self.locks.items():
                box.setChecked(getattr(locks, name) is not None)
                self.lock_values[name].setText(current[name])
            self.gore_count.setEnabled(locks.gore_count is None)
            self._show_outputs()
        finally:
            self._updating = False

    def _show_points(self, r: np.ndarray, z: np.ndarray, layout: Interpolation) -> None:
        """Fill the control-point table; a segment profile adds, per row, the span to the
        next point (kind and arc bulge) and whether the joint at the point is smooth."""
        # Replaced cell widgets are not deleted with their cell: remove the old ones first.
        for combo in self.points_table.findChildren(QComboBox):
            combo.hide()
            combo.deleteLater()
        for row in range(self.points_table.rowCount()):
            self.points_table.removeCellWidget(row, 2)
        segmented = isinstance(layout, SegmentLayout)
        headers = ["radius r (m)", "height z (m)"]
        if segmented:
            headers += ["span to next", "smooth joint", "arc bulge"]
        self.points_table.setColumnCount(len(headers))
        self.points_table.setHorizontalHeaderLabels(headers)
        self.points_table.setRowCount(len(r))
        for i, (a, b) in enumerate(zip(r, z, strict=True)):
            radius = _item(f"{a:.4f}", editable=i not in self.canvas.locked_radii)
            if i in self.canvas.locked_radii:
                radius.setToolTip("locked: unlock the opening's diameter to change it")
            self.points_table.setItem(i, 0, radius)
            self.points_table.setItem(i, 1, _item(f"{b:.4f}"))
        if not isinstance(layout, SegmentLayout):
            return
        resolved = resolve_segments(r, z, layout.segments, samples=200)
        n = len(r)
        for i in range(n):
            if i < n - 1:
                combo = QComboBox()
                combo.setObjectName(f"spanKind{i}")
                for kind, label in (("line", "line"), ("arc", "arc"), ("curve", "curve")):
                    combo.addItem(label, kind)
                combo.setCurrentIndex(combo.findData(layout.segments[i].kind))
                combo.activated.connect(lambda _x, k=i, c=combo: self._span_kind(k, c))
                self.points_table.setCellWidget(i, 2, combo)
            else:
                self.points_table.removeCellWidget(i, 2)
                self.points_table.setItem(i, 2, _item("", editable=False))
            joint = _item("", editable=False)
            if 0 < i < n - 1:
                joint.setFlags(joint.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                joint.setCheckState(
                    Qt.CheckState.Checked if layout.segments[i].smooth else Qt.CheckState.Unchecked
                )
            self.points_table.setItem(i, 3, joint)
            if i < n - 1 and layout.segments[i].kind == "arc":
                own = resolved[i].bulge == layout.segments[i].bulge
                bulge = _item(f"{resolved[i].bulge:.4f}", editable=own)
                bulge.setToolTip(
                    "tan of a quarter of the arc's angle; positive bows outward going up"
                    if own
                    else "set by the tangent of the neighbouring span (smooth joint)"
                )
            else:
                bulge = _item("", editable=False)
            self.points_table.setItem(i, 4, bulge)

    def _span_kind(self, index: int, combo: QComboBox) -> None:
        if self._updating:
            return
        if self.controller.edit("set_profile_segment", index, kind=combo.currentData()) is None:
            self.refresh()

    def _show_loft(self) -> None:
        design = self.controller.design
        assert design is not None and design.gores is not None
        n = design.gores.count
        points = design.gores.loft or []
        self.loft_table.setRowCount(len(points))
        for i, point in enumerate(points):
            extra = float(loft_extra_width(n, point.ratio))
            self.loft_table.setItem(i, 0, _item(f"{point.station:.4f}"))
            self.loft_table.setItem(i, 1, _item(f"{point.ratio:.4f}"))
            self.loft_table.setItem(i, 2, _item(f"{extra * 100:.2f} %", editable=False))
        if points:
            self.loft_status.setText(f"{len(points)} station(s); k ≥ {math.sin(math.pi / n):.4f}")
        else:
            small = float(loft_extra_width(n, 1.0))
            self.loft_status.setText(
                f"No loft: small-bulge gores (k = 1, extra width {small * 100:.2f} %). "
                "Add a station to set one."
            )

    def _loft_points(self) -> list[tuple[float, float]]:
        design = self.controller.design
        assert design is not None and design.gores is not None
        return [(p.station, p.ratio) for p in design.gores.loft or []]

    def _loft_edited(self, item: QTableWidgetItem) -> None:
        design = self.controller.design
        if self._updating or design is None or design.gores is None or item.column() > 1:
            return
        try:
            value = float(item.text().replace("%", ""))
        except ValueError:
            self.controller.editRejected.emit(f"not a number: {item.text()!r}")
            self.refresh()
            return
        points = self._loft_points()
        station, ratio = points[item.row()]
        points[item.row()] = (value, ratio) if item.column() == 0 else (station, value)
        if self.controller.edit("set_loft", points) is None:
            self.refresh()

    def _add_loft_station(self) -> None:
        points = self._loft_points()
        if not points:
            self.controller.edit("set_loft", [(0.0, 1.0)])
            return
        # Middle of the widest gap (ends included), with the interpolated ratio, so the
        # new station does not change the loft until it is edited.
        stations = [p[0] for p in points]
        bounds = sorted({0.0, *stations, 1.0})
        gaps = [(b - a, a, b) for a, b in zip(bounds, bounds[1:], strict=False)]
        _, a, b = max(gaps)
        station = 0.5 * (a + b)
        ratio = float(np.interp(station, stations, [p[1] for p in points]))
        self.controller.edit("set_loft", [*points, (station, ratio)])

    def _remove_loft_station(self) -> None:
        rows = self.loft_table.selectionModel().selectedRows()
        if not rows:
            return
        points = self._loft_points()
        del points[rows[0].row()]
        self.controller.edit("set_loft", points or None)

    def _show_crest(self, bows: list[tuple[float, float]]) -> None:
        design = self.controller.design
        assert design is not None and design.gores is not None
        crest = design.gores.crest_loft
        points = [] if crest is None else crest.taper
        seams = [r.letter for r in design.gores.panel_rows[1:]]
        self.crest_table.setRowCount(len(points))
        for i, point in enumerate(points):
            self.crest_table.setItem(i, 0, _item(f"{point.station:.4f}"))
            self.crest_table.setItem(i, 1, _item(f"{point.taper:.4f}"))
            combo = QComboBox()
            combo.addItem("(free)", None)
            for letter in seams:
                combo.addItem(f"bottom of {letter}", letter)
            combo.setCurrentIndex(max(0, combo.findData(point.at_row)))
            combo.activated.connect(
                lambda _i, row=i, c=combo: self.anchor_crest_station(row, c.currentData())
            )
            self.crest_table.setCellWidget(i, 2, combo)
        self.crest_fraction.setValue(0.0 if crest is None else crest.fraction * 100.0)
        excess = sum(a + b for a, b in bows) * 1e3
        measured = any(r.bow_bottom is not None for r in design.gores.panel_rows)
        if crest is not None:
            text = (
                f"Seams from the crest loft: the seam bows add {excess:.1f} mm to the gore "
                "centreline."
            )
        elif measured:
            text = (
                "Measured seam bows, edited in the panel-row table: they add "
                f"{excess:.1f} mm to the gore centreline."
            )
        else:
            text = "Straight seams: no crest loft and no seam bows."
        self.crest_status.setText(text)
        for widget in (self.crest_fraction, self.crest_table):
            widget.setEnabled(crest is not None)
        self.use_crest.setEnabled(crest is None)
        self.freeze_crest.setEnabled(crest is not None)
        self.straight_seams.setEnabled(crest is not None or measured)

    def _crest_points(self) -> list[tuple[float | str, float]]:
        """(station or anchoring row, taper) of every taper point."""
        design = self.controller.design
        assert design is not None and design.gores is not None
        crest = design.gores.crest_loft
        if crest is None:
            return []
        return [(p.station if p.at_row is None else p.at_row, p.taper) for p in crest.taper]

    def _crest_stations(self) -> list[float]:
        """Every taper point's station, fraction of the tape length."""
        design = self.controller.design
        assert design is not None and design.gores is not None
        crest = design.gores.crest_loft
        return [] if crest is None else [p.station for p in crest.taper]

    def anchor_crest_station(self, index: int, row: str | None) -> None:
        """Put taper point ``index`` on the bottom seam of ``row`` (None: free it where it
        is)."""
        if self._updating:
            return
        points = self._crest_points()
        stations = self._crest_stations()
        if not 0 <= index < len(points):
            return
        where: float | str = stations[index] if row is None else row
        points[index] = (where, points[index][1])
        if self.controller.edit("set_crest_loft", self._crest_fraction(), points) is None:
            self.refresh()

    def _crest_fraction(self) -> float:
        design = self.controller.design
        assert design is not None and design.gores is not None
        crest = design.gores.crest_loft
        return DEFAULT_CREST_LOFT.fraction if crest is None else crest.fraction

    def _crest_fraction_edited(self) -> None:
        design = self.controller.design
        if self._updating or design is None or design.gores is None:
            return
        if design.gores.crest_loft is None:
            return
        value = self.crest_fraction.value() / 100.0
        if not math.isclose(value, design.gores.crest_loft.fraction, rel_tol=0, abs_tol=1e-9):
            if self.controller.edit("set_crest_loft", value, self._crest_points()) is None:
                self.refresh()

    def _crest_edited(self, item: QTableWidgetItem) -> None:
        design = self.controller.design
        if self._updating or design is None or design.gores is None:
            return
        try:
            value = float(item.text())
        except ValueError:
            self.controller.editRejected.emit(f"not a number: {item.text()!r}")
            self.refresh()
            return
        points = self._crest_points()
        where, taper = points[item.row()]
        # A typed station is a free one; a taper keeps the point where it is.
        points[item.row()] = (value, taper) if item.column() == 0 else (where, value)
        if self.controller.edit("set_crest_loft", self._crest_fraction(), points) is None:
            self.refresh()

    def _add_crest_station(self) -> None:
        points = self._crest_points()
        if not points:
            return
        # Middle of the widest gap (ends included), with the interpolated taper, so the
        # new station does not change the seams until it is edited.
        stations = self._crest_stations()
        bounds = sorted({0.0, *stations, 1.0})
        gaps = [(b - a, a, b) for a, b in zip(bounds, bounds[1:], strict=False)]
        _, a, b = max(gaps)
        station = 0.5 * (a + b)
        taper = float(np.interp(station, stations, [p[1] for p in points]))
        self.controller.edit("set_crest_loft", self._crest_fraction(), [*points, (station, taper)])

    def _remove_crest_station(self) -> None:
        rows = self.crest_table.selectionModel().selectedRows()
        points = self._crest_points()
        if not rows or len(points) < 2:
            if points:
                self.controller.editRejected.emit("a crest loft needs at least one station")
            return
        del points[rows[0].row()]
        self.controller.edit("set_crest_loft", self._crest_fraction(), points)

    def _use_crest(self) -> None:
        crest = DEFAULT_CREST_LOFT
        self.controller.edit(
            "set_crest_loft", crest.fraction, [(p.station, p.taper) for p in crest.taper]
        )

    def _construction_chosen(self, _index: int) -> None:
        if self._updating:
            return
        if self.controller.edit("set_construction", self.construction.currentData()) is None:
            self.refresh()

    def _interpolation_chosen(self, _index: int) -> None:
        if self._updating:
            return
        value = self.interpolation.currentData()
        if self.controller.edit("set_profile_interpolation", value) is None:
            self.refresh()

    def _openings_text(self) -> str:
        design = self.controller.design
        if design is None or design.gores is None:
            return "-"
        r, _ = control_arrays(design)
        return f"{2 * r[0]:.3f} m / {2 * r[-1]:.3f} m"

    def _show_outputs(self) -> None:
        out = self.controller.outputs
        if out is None:
            for label in self.outputs.values():
                label.setText("-")
            self.output_message.setText(self.controller.outputs_error or "")
            return
        values = {
            "meridian_length": f"{out.meridian_length:.3f} m",
            "height": f"{out.height:.3f} m",
            "max_diameter": f"{out.max_diameter:.3f} m",
            "equator": "-"
            if out.equator is None
            else f"{out.equator.height_above_mouth:.3f} m above the mouth, "
            f"{out.equator.s:.3f} m along the tape ({out.equator.fraction:.0%})",
            "openings": self._openings_text(),
            "parachute": "-"
            if out.rigging is None or out.rigging.parachute is None
            else f"{out.rigging.parachute.geometry.diameter:.3f} m",
            "area": f"{out.area:.2f} m²",
            "volume": f"{out.volume:.2f} m³",
            "gross_lift": f"{out.gross_lift:.0f} N ({out.gross_lift / 9.80665:.1f} kg)",
            "envelope_mass": "-" if out.envelope_mass is None else f"{out.envelope_mass:.1f} kg",
            "rigging_mass": "-" if out.rigging_mass is None else f"{out.rigging_mass:.1f} kg",
            "lift_margin": "-" if out.lift_margin is None else f"{out.lift_margin:.1f} kg",
            "sources": ", ".join(out.sources) or "-",
        }
        for key, text in values.items():
            self.outputs[key].setText(text)
        margin = out.lift_margin
        self.outputs["lift_margin"].setStyleSheet(
            "color: #b00020; font-weight: bold;" if margin is not None and margin < 0 else ""
        )
        self.output_message.setText("\n".join(f.message for f in out.findings))

    # -- edits --------------------------------------------------------------------------

    def _point_moved(self, index: int, radius: float, height: float) -> None:
        if not self.controller.edit("move_control_point", index, radius, height):
            self.refresh()  # refused, or undone by the locks: put the handle back

    def _point_edited(self, item: QTableWidgetItem) -> None:
        if self._updating or self.controller.design is None:
            return
        if item.column() == 3:
            smooth = item.checkState() == Qt.CheckState.Checked
            if self.controller.edit("set_profile_segment", item.row(), smooth=smooth) is None:
                self.refresh()
            return
        if item.column() == 4:
            try:
                bulge = float(item.text())
            except ValueError:
                self.controller.editRejected.emit(f"not a number: {item.text()!r}")
                self.refresh()
                return
            if self.controller.edit("set_profile_segment", item.row(), bulge=bulge) is None:
                self.refresh()
            return
        if item.column() > 1:
            return
        try:
            value = float(item.text())
        except ValueError:
            self.controller.editRejected.emit(f"not a number: {item.text()!r}")
            self.refresh()
            return
        if not math.isfinite(value):
            self.refresh()
            return
        r, z = control_arrays(self.controller.design)
        radius = value if item.column() == 0 else float(r[item.row()])
        height = value if item.column() == 1 else float(z[item.row()])
        if self.controller.edit("move_control_point", item.row(), radius, height) is None:
            self.refresh()

    # -- bulk point editing -------------------------------------------------------------

    def _build_point_tools(self) -> QGroupBox:
        box = QGroupBox("Edit selected points")
        box.setToolTip(
            "Select points on the profile (click, Ctrl+click, or drag a box on empty space) "
            "or in the table, then drag any selected point or use the tools below.\n"
            "Soft radius: neighbours within this distance along the profile follow a drag, "
            "scale or rotation, less the further away they are."
        )
        form = QFormLayout(box)
        self.selection_label = QLabel("no points selected")
        self.selection_label.setObjectName("selectionLabel")
        select_all = QPushButton("Select all")
        select_all.clicked.connect(
            lambda: self.canvas.select(list(range(len(self.canvas.handles))))
        )
        top = QHBoxLayout()
        top.addWidget(self.selection_label, 1)
        top.addWidget(select_all)
        form.addRow(top)
        self.soft_radius = QDoubleSpinBox()
        self.soft_radius.setObjectName("softRadius")
        self.soft_radius.setRange(0.0, 1000.0)
        self.soft_radius.setDecimals(2)
        self.soft_radius.setSingleStep(0.25)
        self.soft_radius.setSuffix(" m")
        self.soft_radius.setSpecialValueText("off")
        self.soft_radius.valueChanged.connect(self._soft_changed)
        self.falloff = QComboBox()
        self.falloff.setObjectName("falloff")
        for name in FALLOFFS:
            self.falloff.addItem(name, name)
        self.falloff.currentIndexChanged.connect(self._soft_changed)
        soft = QHBoxLayout()
        soft.addWidget(self.soft_radius)
        soft.addWidget(self.falloff)
        form.addRow("Soft radius, falloff", soft)
        self.scale_r = QDoubleSpinBox()
        self.scale_z = QDoubleSpinBox()
        for spin, object_name in ((self.scale_r, "scaleR"), (self.scale_z, "scaleZ")):
            spin.setObjectName(object_name)
            spin.setRange(1.0, 1000.0)
            spin.setValue(100.0)
            spin.setSuffix(" %")
        scale = QPushButton("Scale")
        scale.setObjectName("scalePoints")
        scale.clicked.connect(self.scale_selected)
        row = QHBoxLayout()
        row.addWidget(QLabel("across"))
        row.addWidget(self.scale_r)
        row.addWidget(QLabel("up"))
        row.addWidget(self.scale_z)
        row.addWidget(scale)
        form.addRow("Scale about centre", row)
        self.rotate_deg = QDoubleSpinBox()
        self.rotate_deg.setObjectName("rotateDeg")
        self.rotate_deg.setRange(-180.0, 180.0)
        self.rotate_deg.setSuffix(" °")
        rotate = QPushButton("Rotate")
        rotate.setObjectName("rotatePoints")
        rotate.clicked.connect(self.rotate_selected)
        row = QHBoxLayout()
        row.addWidget(self.rotate_deg)
        row.addWidget(rotate)
        form.addRow("Rotate about centre", row)
        straighten = QPushButton("Straighten")
        straighten.setObjectName("straightenPoints")
        straighten.setToolTip(
            "Make a straight section: the points between the first and last selected point "
            "go onto the line joining them."
        )
        straighten.clicked.connect(self.straighten_selected)
        smooth = QPushButton("Smooth")
        smooth.setObjectName("smoothPoints")
        smooth.setToolTip("Even out the selected points (the ends of the profile stay put).")
        smooth.clicked.connect(self.smooth_selected)
        self.comb_box = QCheckBox("Curvature comb")
        self.comb_box.setObjectName("curvatureComb")
        self.comb_box.setToolTip(
            "Spikes show how sharply the profile bends: look for wiggles, flat spots and "
            "kinks (one tall spike)."
        )
        self.comb_box.toggled.connect(self.canvas.set_comb)
        row = QHBoxLayout()
        row.addWidget(straighten)
        row.addWidget(smooth)
        row.addWidget(self.comb_box)
        form.addRow(row)
        self.simplify_tolerance = QDoubleSpinBox()
        self.simplify_tolerance.setObjectName("simplifyTolerance")
        self.simplify_tolerance.setRange(0.1, 1000.0)
        self.simplify_tolerance.setValue(2.0)
        self.simplify_tolerance.setSuffix(" mm")
        simplify = QPushButton("Simplify")
        simplify.setObjectName("simplifyProfile")
        simplify.setToolTip(
            "Replace all control points by as few as keep the profile within the tolerance "
            "(the mouth and top points stay)."
        )
        simplify.clicked.connect(self.simplify)
        row = QHBoxLayout()
        row.addWidget(self.simplify_tolerance)
        row.addWidget(simplify)
        form.addRow("Simplify within", row)
        self.simplify_status = QLabel()
        self.simplify_status.setObjectName("simplifyStatus")
        self.simplify_status.setWordWrap(True)
        form.addRow(self.simplify_status)
        return box

    def select_all_points(self) -> None:
        """Select every control point."""
        self.canvas.select(list(range(len(self.canvas.handles))))

    def _soft_changed(self) -> None:
        self.canvas.soft_radius = float(self.soft_radius.value())
        self.canvas.falloff = self.falloff.currentData()

    def _canvas_selection(self) -> None:
        selected = self.canvas.selected_indices()
        self.selection_label.setText(
            f"{len(selected)} point(s) selected" if selected else "no points selected"
        )
        if self._syncing:
            return
        self._syncing = True
        try:
            model = self.points_table.selectionModel()
            self.points_table.clearSelection()
            for i in selected:
                index = self.points_table.model().index(i, 0)
                model.select(
                    index,
                    model.SelectionFlag.Select | model.SelectionFlag.Rows,
                )
        finally:
            self._syncing = False

    def _table_selection(self) -> None:
        if self._syncing:
            return
        self._syncing = True
        try:
            rows = sorted({i.row() for i in self.points_table.selectionModel().selectedRows()})
            self.canvas.select(rows)
        finally:
            self._syncing = False

    def _need_selection(self, at_least: int = 1) -> list[int] | None:
        selected = self.canvas.selected_indices()
        if len(selected) < at_least:
            self.controller.editRejected.emit(
                f"select at least {at_least} control point(s) on the profile first"
            )
            return None
        return selected

    def _soft(self) -> tuple[float, Falloff]:
        return float(self.soft_radius.value()), self.falloff.currentData()

    def _points_dragged(self, selected: list[int], dr: float, dz: float) -> None:
        if not self.controller.edit("move_points", selected, dr, dz, *self._soft()):
            self.refresh()  # refused, or undone by the locks: put the handles back

    def scale_selected(self) -> None:
        """Scale the selected points about their centre by the typed percentages."""
        selected = self._need_selection()
        if selected is None:
            return
        kr, kz = self.scale_r.value() / 100.0, self.scale_z.value() / 100.0
        if self.controller.edit("scale_points", selected, kr, kz, None, *self._soft()) is None:
            self.refresh()

    def rotate_selected(self) -> None:
        """Rotate the selected points about their centre by the typed angle."""
        selected = self._need_selection()
        if selected is None:
            return
        angle = math.radians(self.rotate_deg.value())
        if self.controller.edit("rotate_points", selected, angle, None, *self._soft()) is None:
            self.refresh()

    def straighten_selected(self) -> None:
        """Make the stretch between the first and last selected point straight."""
        selected = self._need_selection(2)
        if selected is None:
            return
        if self.controller.edit("straighten_points", selected[0], selected[-1]) is None:
            self.refresh()

    def smooth_selected(self) -> None:
        """Smooth the selected points (all points when none is selected)."""
        selected = self.canvas.selected_indices() or list(range(len(self.canvas.handles)))
        if self.controller.edit("smooth_points", selected, 0.5, 1) is None:
            self.refresh()

    def simplify(self) -> None:
        """Replace the control points by fewer within the typed tolerance."""
        before = len(self.canvas.handles)
        tolerance = self.simplify_tolerance.value() / 1000.0
        result = self.controller.edit("simplify_profile", tolerance)
        if result is None:
            self.simplify_status.setText("")
            self.refresh()
            return
        self.simplify_status.setText(
            f"{before} → {result.count} points; largest change {result.deviation * 1e3:.1f} mm "
            "(before the locks are re-applied)."
        )

    def _selected_row(self, table: QTableWidget) -> int:
        rows = table.selectionModel().selectedRows()
        return rows[0].row() if rows else max(0, table.rowCount() - 2)

    def _insert_point(self) -> None:
        self.controller.edit("insert_control_point", self._selected_row(self.points_table))

    def _delete_point(self) -> None:
        rows = self.points_table.selectionModel().selectedRows()
        if rows:
            self.controller.edit("delete_control_point", rows[0].row())

    def _row_edited(self, item: QTableWidgetItem) -> None:
        design = self.controller.design
        if self._updating or design is None or design.gores is None:
            return
        letter = design.gores.panel_rows[item.row()].letter
        if item.column() == 0:
            if self.controller.edit("rename_row", letter, item.text()) is None:
                self.refresh()
        elif item.column() == 1:
            try:
                value = float(item.text())
            except ValueError:
                self.controller.editRejected.emit(f"not a number: {item.text()!r}")
                self.refresh()
                return
            if (
                self.controller.set_value(
                    ("gores", "panel_rows", item.row(), "finished_height"), value
                )
                is None
            ):
                self.refresh()
        elif item.column() in (3, 4):
            try:
                value = float(item.text()) / 1e3
            except ValueError:
                self.controller.editRejected.emit(f"not a number: {item.text()!r}")
                self.refresh()
                return
            bottom, top = design_seam_bows(design)[item.row()]
            bottom, top = (value, top) if item.column() == 3 else (bottom, value)
            if self.controller.edit("set_row_bows", item.row(), bottom, top) is None:
                self.refresh()
        elif item.column() == 2:
            zone = item.text().strip() or None
            if self.controller.edit("set_row_zone", letter, zone) is None:
                self.refresh()

    def _row_selected(self) -> None:
        design = self.controller.design
        rows = self.rows_table.selectionModel().selectedRows()
        self.canvas.highlight_row(rows[0].row() if rows else None)
        if rows and design is not None and design.gores is not None:
            self.controller.select(f"row:{design.gores.panel_rows[rows[0].row()].letter}")

    def _split_row(self) -> None:
        rows = self.rows_table.selectionModel().selectedRows()
        if rows:
            self.controller.edit("split_row", rows[0].row())

    def _merge_row(self) -> None:
        rows = self.rows_table.selectionModel().selectedRows()
        if rows:
            self.controller.edit("merge_row_with_next", rows[0].row())

    def _count_edited(self) -> None:
        design = self.controller.design
        if self._updating or design is None or design.gores is None:
            return
        if self.gore_count.value() != design.gores.count:
            if self.controller.edit("set_gore_count", self.gore_count.value()) is None:
                self.refresh()

    def _lock_value_edited(self, name: str) -> None:
        if self._updating or self.controller.design is None:
            return
        text = self.lock_values[name].text().strip()
        try:
            value = float(text)
        except ValueError:
            self.refresh()
            return
        self.set_lock_target(name, value)

    def set_lock_target(self, name: str, value: float) -> None:
        """Lock ``name`` at ``value`` (m, m³ or a count) and solve the design to it."""
        if self.controller.edit("set_lock_target", name, value) is None:
            self.refresh()
        else:
            self.controller.bump()
            self.controller.stateChanged.emit()

    def _lock_toggled(self, name: str, on: bool) -> None:
        if self._updating:
            return
        self.controller.edit("set_lock", name, on)
