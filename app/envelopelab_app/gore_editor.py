"""Standard-gore editor: profile canvas, control-point and panel-row tables, locks, outputs."""

from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFormLayout,
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsSceneMouseEvent,
    QGraphicsView,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from envelopelab.project.gore_design import control_arrays, profile_from_arrays
from envelopelab_app.controller import WorkspaceController

HANDLE_RADIUS = 6.0  # px


class ControlPointHandle(QGraphicsEllipseItem):
    """A draggable control point (scene units: m, y axis pointing down = -z)."""

    def __init__(self, canvas: ProfileCanvas, index: int, r: float, z: float) -> None:
        super().__init__(-HANDLE_RADIUS, -HANDLE_RADIUS, 2 * HANDLE_RADIUS, 2 * HANDLE_RADIUS)
        self.canvas = canvas
        self.index = index
        self.setPos(QPointF(r, -z))
        self.setBrush(QBrush(QColor("#1f77b4")))
        self.setPen(QPen(QColor("white"), 1.5))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setZValue(10)
        self.setToolTip(f"control point {index + 1}")

    def itemChange(self, change: QGraphicsItem.GraphicsItemChange, value: object) -> object:  # noqa: N802
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange and isinstance(
            value, QPointF
        ):
            # Radii cannot be negative.
            return QPointF(max(0.0, value.x()), value.y())
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self.canvas.preview()
        return super().itemChange(change, value)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent) -> None:  # noqa: N802
        super().mouseReleaseEvent(event)
        pos = self.pos()
        index, r, z = self.index, float(pos.x()), float(-pos.y())
        # Emit after this event returns: the edit rebuilds the handles, this one included.
        QTimer.singleShot(0, lambda: self.canvas.pointMoved.emit(index, r, z))


class ProfileCanvas(QGraphicsView):
    """2D meridian profile (radius right, height up) with draggable control points.

    ``pointMoved(index, radius_m, height_m)`` is emitted when a drag ends; the editor
    turns it into one undoable command.
    """

    pointMoved = Signal(int, float, float)  # noqa: N815

    def __init__(self) -> None:
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setMinimumSize(320, 320)
        self.handles: list[ControlPointHandle] = []
        self._curve = QGraphicsPathItem()
        self._curve.setPen(QPen(QColor("#1f77b4"), 0))
        self._mirror = QGraphicsPathItem()
        pen = QPen(QColor("#9aa5b1"), 0)
        pen.setStyle(Qt.PenStyle.DashLine)
        self._mirror.setPen(pen)
        self._axis = QGraphicsPathItem()
        self._axis.setPen(QPen(QColor("#888888"), 0, Qt.PenStyle.DotLine))
        for item in (self._axis, self._mirror, self._curve):
            self.scene().addItem(item)

    def set_points(self, r: np.ndarray, z: np.ndarray) -> None:
        """Show control points (m)."""
        for handle in self.handles:
            self.scene().removeItem(handle)
        self.handles = [
            ControlPointHandle(self, i, float(a), float(b))
            for i, (a, b) in enumerate(zip(r, z, strict=True))
        ]
        for handle in self.handles:
            self.scene().addItem(handle)
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
        self._curve.setPath(QPainterPath())
        self._mirror.setPath(QPainterPath())

    def current_points(self) -> tuple[np.ndarray, np.ndarray]:
        """Positions of the handles (m)."""
        r = np.array([h.pos().x() for h in self.handles])
        z = np.array([-h.pos().y() for h in self.handles])
        return r, z

    def preview(self) -> None:
        """Redraw the curve while a point is dragged (no command yet)."""
        if len(self.handles) >= 2:
            self._draw(*self.current_points())

    def _draw(self, r: np.ndarray, z: np.ndarray) -> None:
        try:
            profile = profile_from_arrays(r, z)
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
        self.header = QLabel()
        self.header.setObjectName("goreEditorHeader")
        self.canvas = ProfileCanvas()
        self.canvas.pointMoved.connect(self._point_moved)

        self.points_table = QTableWidget(0, 2)
        self.points_table.setHorizontalHeaderLabels(["radius r (m)", "height z (m)"])
        self.points_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.points_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.points_table.itemChanged.connect(self._point_edited)
        add_point = QPushButton("Insert point after")
        add_point.clicked.connect(self._insert_point)
        del_point = QPushButton("Delete point")
        del_point.clicked.connect(self._delete_point)

        self.rows_table = QTableWidget(0, 3)
        self.rows_table.setHorizontalHeaderLabels(["row", "height (m)", "zone"])
        self.rows_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.rows_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.rows_table.itemChanged.connect(self._row_edited)
        self.rows_table.itemSelectionChanged.connect(self._row_selected)
        split = QPushButton("Split row")
        split.clicked.connect(self._split_row)
        merge = QPushButton("Merge with next")
        merge.clicked.connect(self._merge_row)
        fit = QPushButton("Fit rows to meridian")
        fit.clicked.connect(lambda: self.controller.edit("fit_rows"))

        self.gore_count = QSpinBox()
        self.gore_count.setRange(3, 200)
        self.gore_count.editingFinished.connect(self._count_edited)
        self.locks: dict[str, QCheckBox] = {}
        locks_box = QGroupBox("Constraint locks")
        locks_layout = QFormLayout(locks_box)
        for name, text in (
            ("height", "Fixed height"),
            ("volume", "Fixed volume"),
            ("max_diameter", "Fixed maximum diameter"),
            ("gore_count", "Fixed N (gore count)"),
        ):
            box = QCheckBox(text)
            box.toggled.connect(lambda on, n=name: self._lock_toggled(n, on))
            self.locks[name] = box
            locks_layout.addRow(box)
        locks_layout.addRow("Gores N", self.gore_count)

        self.outputs: dict[str, QLabel] = {}
        outputs_box = QGroupBox("Live outputs")
        outputs_layout = QFormLayout(outputs_box)
        for key, text in (
            ("meridian_length", "Meridian (tape) length"),
            ("height", "Height"),
            ("max_diameter", "Maximum diameter"),
            ("area", "Fabric area"),
            ("volume", "Volume"),
            ("gross_lift", "Gross lift"),
            ("envelope_mass", "Estimated envelope mass"),
            ("lift_margin", "Lift margin (after payload)"),
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
        side_layout.addWidget(QLabel("Panel rows (mouth first)"))
        side_layout.addWidget(self.rows_table)
        row_buttons = QHBoxLayout()
        for b in (split, merge, fit):
            row_buttons.addWidget(b)
        side_layout.addLayout(row_buttons)
        side_layout.addWidget(locks_box)
        side_layout.addWidget(outputs_box)

        splitter = QSplitter()
        splitter.addWidget(self.canvas)
        splitter.addWidget(side)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout = QVBoxLayout(self)
        layout.addWidget(self.header)
        layout.addWidget(splitter)

        controller.stateChanged.connect(self.refresh)
        controller.sessionChanged.connect(self.refresh)
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
                for label in self.outputs.values():
                    label.setText("-")
                self.output_message.setText(
                    "" if design is None else "Special shapes are edited in the 3D view."
                )
                return
            r, z = control_arrays(design)
            self.canvas.set_points(r, z)
            self.points_table.setRowCount(len(r))
            for i, (a, b) in enumerate(zip(r, z, strict=True)):
                self.points_table.setItem(i, 0, _item(f"{a:.4f}"))
                self.points_table.setItem(i, 1, _item(f"{b:.4f}"))
            session = self.controller.session
            assert session is not None
            rows = design.gores.panel_rows
            self.rows_table.setRowCount(len(rows))
            for i, row in enumerate(rows):
                self.rows_table.setItem(i, 0, _item(row.letter, editable=False))
                self.rows_table.setItem(i, 1, _item(f"{row.finished_height:.4f}"))
                zone = session.patterns.row(row.letter).zone or next(iter(design.zones), "")
                self.rows_table.setItem(i, 2, _item(zone))
            self.gore_count.setValue(design.gores.count)
            locks = session.project.locks
            for name, box in self.locks.items():
                box.setChecked(getattr(locks, name) is not None)
            self.gore_count.setEnabled(locks.gore_count is None)
            self._show_outputs()
        finally:
            self._updating = False

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
            "area": f"{out.area:.2f} m²",
            "volume": f"{out.volume:.2f} m³",
            "gross_lift": f"{out.gross_lift:.0f} N ({out.gross_lift / 9.80665:.1f} kg)",
            "envelope_mass": "-" if out.envelope_mass is None else f"{out.envelope_mass:.1f} kg",
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
        if self.controller.edit("move_control_point", index, radius, height) is None:
            self.refresh()  # refused: put the handle back

    def _point_edited(self, item: QTableWidgetItem) -> None:
        if self._updating or self.controller.design is None:
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
        if item.column() == 1:
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
        elif item.column() == 2:
            zone = item.text().strip() or None
            if (
                self.controller.set_row_pattern(
                    letter, {"zone": zone}, f"Row {letter}: zone {zone}"
                )
                is None
            ):
                self.refresh()

    def _row_selected(self) -> None:
        design = self.controller.design
        rows = self.rows_table.selectionModel().selectedRows()
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

    def _lock_toggled(self, name: str, on: bool) -> None:
        if self._updating:
            return
        self.controller.edit("set_lock", name, on)
