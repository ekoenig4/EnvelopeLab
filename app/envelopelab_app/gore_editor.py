"""Standard-gore editor: profile canvas, control-point, panel-row and loft tables, gore
construction (lobe or flat chord, with its crest loft and seam bows), locks, outputs."""

from __future__ import annotations

import math
from typing import Literal

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

from envelopelab.geometry.gore import loft_extra_width
from envelopelab.project.gore_design import (
    DEFAULT_CREST_LOFT,
    control_arrays,
    design_seam_bows,
    profile_from_arrays,
    row_zone,
)
from envelopelab_app.controller import WorkspaceController
from envelopelab_app.refresh import Refresher

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
        self.interpolation: Literal["spline", "linear"] = "spline"
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

    def set_points(
        self, r: np.ndarray, z: np.ndarray, interpolation: Literal["spline", "linear"] = "spline"
    ) -> None:
        """Show control points (m), joined as the design joins them."""
        self.interpolation = interpolation
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
        self.crest_table = QTableWidget(0, 2)
        self.crest_table.setObjectName("crestTable")
        self.crest_table.setHorizontalHeaderLabels(["station (0–1)", "taper"])
        self.crest_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.crest_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.crest_table.setToolTip(
            "Taper of the crest offset along the tape (station: fraction of the tape length, "
            "0 at the mouth, 1 at the top opening), interpolated linearly and held beyond the "
            "first and last station."
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
            self.canvas.set_points(r, z, design.gores.profile_interpolation)
            self.points_table.setRowCount(len(r))
            for i, (a, b) in enumerate(zip(r, z, strict=True)):
                self.points_table.setItem(i, 0, _item(f"{a:.4f}"))
                self.points_table.setItem(i, 1, _item(f"{b:.4f}"))
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
            profile = profile_from_arrays(r, z, design.gores.profile_interpolation)
            current = {
                "height": f"{profile.height:.3f}",
                "max_diameter": f"{profile.max_width:.3f}",
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
        self.crest_table.setRowCount(len(points))
        for i, point in enumerate(points):
            self.crest_table.setItem(i, 0, _item(f"{point.station:.4f}"))
            self.crest_table.setItem(i, 1, _item(f"{point.taper:.4f}"))
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

    def _crest_points(self) -> list[tuple[float, float]]:
        design = self.controller.design
        assert design is not None and design.gores is not None
        crest = design.gores.crest_loft
        return [] if crest is None else [(p.station, p.taper) for p in crest.taper]

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
        station, taper = points[item.row()]
        points[item.row()] = (value, taper) if item.column() == 0 else (station, value)
        if self.controller.edit("set_crest_loft", self._crest_fraction(), points) is None:
            self.refresh()

    def _add_crest_station(self) -> None:
        points = self._crest_points()
        if not points:
            return
        # Middle of the widest gap (ends included), with the interpolated taper, so the
        # new station does not change the seams until it is edited.
        stations = [p[0] for p in points]
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
