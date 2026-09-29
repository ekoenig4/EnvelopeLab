"""2D pattern editor: flat panel rows with allowances, labels, grain, zones, tapes, features.

Rows are drawn from the *last generated* patterns, stacked as they are sewn into a gore
(mouth at the bottom, crown at the top) or side by side (the *Stack rows* toggle). When the
design changed since then the view says so (a STALE banner, greyed rows) until the patterns
are regenerated: it never shows outdated patterns as current. Dragging outline handles in
*Edit outline* mode makes a flagged manual override (recorded in the provenance log).
"""

from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsPolygonItem,
    QGraphicsScene,
    QGraphicsSceneMouseEvent,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from envelopelab.geometry.gore import PanelRow
from envelopelab.project.gore_design import (
    default_allowance,
    editable_outline,
    row_allowance,
    row_zone,
)
from envelopelab.project.model import RowPattern
from envelopelab_app.controller import WorkspaceController

GAP = 0.4  # m between rows in the layout
Offset = tuple[float, float]  # (x, y) of a row's panel origin in the layout, m
ZONE_FALLBACK = "#d9e7f5"


def _polygon(points: np.ndarray, offset: Offset) -> QPolygonF:
    dx, dy = offset
    return QPolygonF([QPointF(float(x) + dx, -(float(y) + dy)) for x, y in points])


def _point(x: float, y: float, offset: Offset) -> QPointF:
    """Scene point of panel point (x, y) m (scene y points down)."""
    return QPointF(x + offset[0], -(y + offset[1]))


def layout_offsets(rows: list[PanelRow], stacked: bool, gap: float = GAP) -> dict[str, Offset]:
    """Layout origin of every row, m.

    Parameters
    ----------
    rows : list of PanelRow
        Rows mouth first; outlines in panel coordinates, m.
    stacked : bool
        Stack the rows vertically as they are sewn (mouth at the bottom); otherwise place
        them side by side from left to right.
    gap : float
        Clear space between neighbouring cut outlines, m.

    Returns
    -------
    dict of str to (float, float)
        Row label to the (x, y) offset of its panel origin, m.
    """
    offsets: dict[str, Offset] = {}
    x = y = 0.0
    previous_top: float | None = None
    for row in rows:
        cut = row.cut_outline
        if stacked:
            if previous_top is not None:
                y = previous_top + gap - float(cut[:, 1].min())
            offsets[row.label] = (0.0, y)
            previous_top = y + float(cut[:, 1].max())
        else:
            width = float(np.ptp(cut[:, 0]))
            x += width / 2
            offsets[row.label] = (x, 0.0)
            x += width / 2 + gap
    return offsets


class OutlineHandle(QGraphicsEllipseItem):
    """Draggable vertex of an outline being edited (scene units m)."""

    def __init__(self, view: PatternView, index: int, pos: QPointF) -> None:
        super().__init__(-5, -5, 10, 10)
        self.view = view
        self.index = index
        self.setPos(pos)
        self.setBrush(QBrush(QColor("#d62728")))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        self.setZValue(20)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent) -> None:  # noqa: N802
        super().mouseReleaseEvent(event)
        QTimer.singleShot(0, self.view.commit_outline)


class FeatureMarker(QGraphicsEllipseItem):
    """A feature location; dragging it moves the feature (one undoable edit)."""

    def __init__(self, view: PatternView, letter: str, index: int, radius: float) -> None:
        super().__init__(-radius, -radius, 2 * radius, 2 * radius)
        self.view = view
        self.letter = letter
        self.index = index
        self.setPen(QPen(QColor("#9467bd"), 0))
        self.setBrush(QBrush(QColor(148, 103, 189, 60)))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setZValue(15)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent) -> None:  # noqa: N802
        super().mouseReleaseEvent(event)
        QTimer.singleShot(0, lambda: self.view.commit_feature(self))


class PatternView(QGraphicsView):
    """The drawing (see module docstring)."""

    def __init__(self, panel: PatternPanel) -> None:
        super().__init__()
        self.panel = panel
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.offsets: dict[str, Offset] = {}
        self.handles: list[OutlineHandle] = []
        self.edit_letter: str | None = None
        self.content_rect = QRectF()

    def wheelEvent(self, event: object) -> None:  # noqa: N802
        delta = event.angleDelta().y()  # type: ignore[attr-defined]
        factor = 1.15 if delta > 0 else 1 / 1.15
        self.scale(factor, factor)

    def mousePressEvent(self, event: object) -> None:  # noqa: N802
        point: QPoint = event.position().toPoint()  # type: ignore[attr-defined]
        pos = self.mapToScene(point)
        for letter, offset in self.offsets.items():
            rows = self.panel.rows_by_letter()
            row = rows.get(letter)
            if row is None:
                continue
            outline = _polygon(row.cut_outline, offset)
            if outline.containsPoint(pos, Qt.FillRule.OddEvenFill):
                self.panel.controller.select(f"row:{letter}")
                break
        super().mousePressEvent(event)  # type: ignore[arg-type]

    def commit_outline(self) -> None:
        """Turn the handle positions into a manual outline override."""
        if self.edit_letter is None or not self.handles:
            return
        dx, dy = self.offsets.get(self.edit_letter, (0.0, 0.0))
        points = [(float(h.pos().x() - dx), float(-h.pos().y() - dy)) for h in self.handles]
        self.panel.controller.edit("set_manual_outline", self.edit_letter, points)

    def commit_feature(self, marker: FeatureMarker) -> None:
        """Move a feature location to where its marker was dropped."""
        session = self.panel.controller.session
        if session is None:
            return
        row = session.patterns.row(marker.letter)
        if marker.index >= len(row.feature_locations):
            return
        dx, dy = self.offsets.get(marker.letter, (0.0, 0.0))
        centre = marker.mapToScene(marker.rect().center())
        features = [f.model_dump() for f in row.feature_locations]
        features[marker.index]["x"] = float(centre.x() - dx)
        features[marker.index]["y"] = float(-centre.y() - dy)
        self.panel.controller.set_row_pattern(
            marker.letter, {"feature_locations": features}, f"Row {marker.letter}: move feature"
        )


class PatternPanel(QWidget):
    """2D pattern editor panel."""

    def __init__(self, controller: WorkspaceController) -> None:
        super().__init__()
        self.controller = controller
        self._updating = False
        self.banner = QLabel()
        self.banner.setObjectName("patternBanner")
        self.banner.setWordWrap(True)
        self.view = PatternView(self)
        toolbar = QToolBar()
        self.regenerate_action = toolbar.addAction("Regenerate patterns")
        self.regenerate_action.triggered.connect(self.regenerate)
        fit = toolbar.addAction("Fit view")
        fit.triggered.connect(self.fit)
        self.edit_outline = QCheckBox("Edit outline (manual override)")
        self.edit_outline.toggled.connect(self._toggle_edit)
        toolbar.addWidget(self.edit_outline)
        self.stack_rows = QCheckBox("Stack rows (as sewn)")
        self.stack_rows.setToolTip(
            "Stack the rows vertically as they are sewn into a gore (mouth at the bottom, "
            "crown at the top); unchecked: side by side"
        )
        self.stack_rows.setChecked(controller.prefs.stack_pattern_rows)
        self.stack_rows.toggled.connect(self._toggle_stack)
        toolbar.addWidget(self.stack_rows)

        form_box = QGroupBox("Selected row")
        form = QFormLayout(form_box)
        self.row_label = QLabel("-")
        self.label_text = QLineEdit()
        self.label_text.setPlaceholderText("PANEL <row> x<N>")
        self.label_text.editingFinished.connect(self._label_edited)
        self.grain = QDoubleSpinBox()
        self.grain.setRange(-180.0, 180.0)
        self.grain.setSuffix(" °")
        self.grain.setDecimals(1)
        self.grain.editingFinished.connect(self._grain_edited)
        self.zone = QComboBox()
        self.zone.activated.connect(self._zone_edited)
        self.default_allowance = QDoubleSpinBox()
        self.default_allowance.setRange(0.0, 200.0)
        self.default_allowance.setSuffix(" mm")
        self.default_allowance.setDecimals(1)
        self.default_allowance.editingFinished.connect(self._default_allowance_edited)
        self.row_allowance = QDoubleSpinBox()
        self.row_allowance.setRange(-1.0, 200.0)
        self.row_allowance.setSpecialValueText("design default")
        self.row_allowance.setSuffix(" mm")
        self.row_allowance.setDecimals(1)
        self.row_allowance.editingFinished.connect(self._row_allowance_edited)
        form.addRow("Row", self.row_label)
        form.addRow("Label", self.label_text)
        form.addRow("Grain direction", self.grain)
        form.addRow("Fabric zone", self.zone)
        form.addRow("Seam allowance (all rows)", self.default_allowance)
        form.addRow("Seam allowance (this row)", self.row_allowance)

        self.notch_edge = QComboBox()
        self.notch_edge.addItems(["left", "right", "bottom", "top"])
        self.notch_pos = QDoubleSpinBox()
        self.notch_pos.setRange(0.0, 1.0)
        self.notch_pos.setSingleStep(0.05)
        self.notch_pos.setValue(0.5)
        add_notch = QPushButton("Add notch")
        add_notch.clicked.connect(self._add_notch)
        notch_row = QHBoxLayout()
        for w in (self.notch_edge, self.notch_pos, add_notch):
            notch_row.addWidget(w)
        form.addRow("Notch (edge, fraction)", notch_row)

        self.tape_y = QDoubleSpinBox()
        self.tape_y.setRange(0.0, 100.0)
        self.tape_y.setSuffix(" m")
        self.tape_y.setDecimals(3)
        add_tape = QPushButton("Add tape across")
        add_tape.clicked.connect(self._add_tape)
        tape_row = QHBoxLayout()
        tape_row.addWidget(self.tape_y)
        tape_row.addWidget(add_tape)
        form.addRow("Tape path at height", tape_row)

        self.feature = QComboBox()
        self.feature_r = QDoubleSpinBox()
        self.feature_r.setRange(0.01, 10.0)
        self.feature_r.setValue(0.2)
        self.feature_r.setSuffix(" m")
        add_feature = QPushButton("Place feature")
        add_feature.clicked.connect(self._add_feature)
        feature_row = QHBoxLayout()
        for w in (self.feature, self.feature_r, add_feature):
            feature_row.addWidget(w)
        form.addRow("Feature (radius)", feature_row)

        clear_ann = QPushButton("Clear notches, tapes and features")
        clear_ann.clicked.connect(self._clear_annotations)
        self.clear_override = QPushButton("Remove manual override")
        self.clear_override.clicked.connect(self._clear_override)
        form.addRow(clear_ann)
        form.addRow(self.clear_override)

        scroll = QScrollArea()
        scroll.setWidget(form_box)
        scroll.setWidgetResizable(True)
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.view)
        splitter.addWidget(scroll)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        # Stretch factors only share extra space; start the drawing at 3/4 of the height so
        # a stacked gore is not squeezed by the form's size hint.
        splitter.setSizes([3, 1])
        layout = QVBoxLayout(self)
        layout.addWidget(toolbar)
        layout.addWidget(self.banner)
        layout.addWidget(splitter)

        controller.stateChanged.connect(self.refresh)
        controller.artifactsChanged.connect(self.refresh)
        controller.sessionChanged.connect(self.refresh)
        controller.selectionChanged.connect(lambda _t: self.refresh())
        self.refresh()

    # -- data ---------------------------------------------------------------------------

    def rows_by_letter(self) -> dict[str, PanelRow]:
        cache = self.controller.patterns_cache
        return {} if cache is None else {r.label: r for r in cache.rows}

    def selected_letter(self) -> str | None:
        sel = self.controller.selection
        if sel.startswith("row:"):
            return sel[4:]
        design = self.controller.design
        if design is not None and design.gores is not None and design.gores.panel_rows:
            return design.gores.panel_rows[0].letter
        return None

    def regenerate(self) -> None:
        """Generate the patterns from the current design."""
        self.controller.regenerate_patterns()
        self.fit()

    def fit(self) -> None:
        """Zoom to the drawn panels."""
        rect = self.view.content_rect
        if not rect.isEmpty():
            self.view.fitInView(
                rect.adjusted(-0.2, -0.2, 0.2, 0.2), Qt.AspectRatioMode.KeepAspectRatio
            )

    # -- drawing ------------------------------------------------------------------------

    def _zone_color(self, zone: str) -> QColor:
        design = self.controller.design
        fabric_id = design.zones.get(zone) if design is not None else None
        fabric = self.controller.fabrics.fabric(fabric_id) if fabric_id else None
        color = QColor(fabric.color) if fabric is not None else QColor(ZONE_FALLBACK)
        if not color.isValid():
            color = QColor(ZONE_FALLBACK)
        color.setAlpha(90)
        return color

    def refresh(self) -> None:
        """Redraw from the last generated patterns and the current annotations."""
        self._updating = True
        try:
            self._draw()
            self._fill_form()
        finally:
            self._updating = False

    def _draw(self) -> None:
        scene = self.view.scene()
        scene.clear()
        self.view.handles = []
        self.view.offsets = {}
        first = self.view.content_rect.isEmpty()
        self.view.content_rect = QRectF()
        session = self.controller.session
        status = self.controller.artifact_status("patterns")
        if session is None or not self.controller.is_gore:
            self.banner.setText("No standard-gore design: nothing to draw.")
            self.banner.setStyleSheet("")
            return
        if status == "not built":
            self.banner.setText("Patterns have not been generated yet — press Regenerate patterns.")
            self.banner.setStyleSheet("background: #fff3cd; padding: 4px;")
            return
        if status == "stale":
            self.banner.setText(
                "Patterns are STALE: the design changed since they were generated (shown "
                "greyed). Press Regenerate patterns before using them."
            )
            self.banner.setStyleSheet("background: #f8d7da; color: #721c24; padding: 4px;")
        else:
            self.banner.setText("Patterns are current.")
            self.banner.setStyleSheet("background: #d4edda; color: #155724; padding: 4px;")
        stale = status == "stale"
        design = session.design
        assert design.gores is not None
        selected = self.selected_letter()
        rows = list(self.rows_by_letter().values())
        self.view.offsets = layout_offsets(rows, self.controller.prefs.stack_pattern_rows)
        for row in rows:
            ann = session.patterns.row(row.label)
            offset = self.view.offsets[row.label]
            self._draw_row(row, ann, offset, stale, row.label == selected, design.gores.count)
            bounds = _polygon(row.cut_outline, offset).boundingRect()
            self.view.content_rect = self.view.content_rect.united(bounds)
        # Labels ignore the view transform, so their pixel extents would count as metres in
        # the default scene rect and keep the panels from being centred; use the panels,
        # with room to pan around them.
        rect = self.view.content_rect
        margin = max(rect.width(), rect.height())
        scene.setSceneRect(rect.adjusted(-margin, -margin, margin, margin))
        if first:
            QTimer.singleShot(0, self.fit)

    def _draw_row(
        self, row: PanelRow, ann: RowPattern, offset: Offset, stale: bool, selected: bool, n: int
    ) -> None:
        scene = self.view.scene()
        session = self.controller.session
        assert session is not None
        grey = QColor("#9e9e9e")
        cut = QGraphicsPolygonItem(_polygon(row.cut_outline, offset))
        pen = QPen(grey if stale else QColor("#333333"), 0, Qt.PenStyle.DashLine)
        cut.setPen(pen)
        scene.addItem(cut)
        manual = ann.manual_outline
        finished_pts = np.asarray(manual.points) if manual is not None else row.finished_outline
        finished = QGraphicsPolygonItem(_polygon(finished_pts, offset))
        zone = row_zone(session.design, session.patterns, row.label)
        finished.setBrush(QBrush(QColor(200, 200, 200, 60) if stale else self._zone_color(zone)))
        color = QColor("#d62728") if manual is not None else (grey if stale else QColor("#1f3b57"))
        finished.setPen(QPen(color, 3 if selected else 1.5))
        finished.pen().setCosmetic(True)
        pen2 = finished.pen()
        pen2.setCosmetic(True)
        finished.setPen(pen2)
        scene.addItem(finished)
        text = ann.label_text or f"PANEL {row.label} x{n}"
        allowance = row_allowance(session.design, session.patterns, row.label)
        label = QGraphicsSimpleTextItem(text)
        font = label.font()
        font.setPointSizeF(7.5)
        label.setFont(font)
        label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        label.setPos(_point(-0.25 * row.bottom_width, row.finished_height * 0.6, offset))
        label.setToolTip(f"{text}; zone {zone}; seam allowance {allowance * 1000:g} mm")
        scene.addItem(label)
        finished.setToolTip(label.toolTip())
        if manual is not None:
            flag = QGraphicsSimpleTextItem("MANUAL OVERRIDE")
            flag.setBrush(QBrush(QColor("#d62728")))
            flag.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
            flag.setPos(_point(-0.3, row.finished_height * 0.9, offset))
            scene.addItem(flag)
        # Grain arrow at mid-height.
        a = math.radians(ann.grain_angle_deg)
        length = 0.25 * max(row.bottom_width, row.top_width, 0.2)
        centre = _point(0.0, row.finished_height * 0.3, offset)
        cx, cy = centre.x(), centre.y()
        tip = QPointF(cx + length * math.cos(a), cy - length * math.sin(a))
        tail = QPointF(cx - length * math.cos(a), cy + length * math.sin(a))
        arrow = QPainterPath(tail)
        arrow.lineTo(tip)
        for side in (+1, -1):
            b = a + math.pi + side * 0.4
            arrow.moveTo(tip)
            arrow.lineTo(tip.x() + 0.3 * length * math.cos(b), tip.y() - 0.3 * length * math.sin(b))
        grain = QGraphicsPathItem(arrow)
        gp = QPen(QColor("#2ca02c"), 2)
        gp.setCosmetic(True)
        grain.setPen(gp)
        grain.setToolTip(f"grain {ann.grain_angle_deg:g}°")
        scene.addItem(grain)
        # Notches: short ticks into the finished outline.
        edges = self._edges(row)
        for notch in ann.notches:
            p0, p1 = edges[notch.edge]
            px = p0 + (p1 - p0) * notch.position
            tick = QPainterPath(_point(px[0], px[1], offset))
            direction = (
                np.array([1.0, 0.0])
                if notch.edge == "left"
                else (
                    np.array([-1.0, 0.0])
                    if notch.edge == "right"
                    else (np.array([0.0, 1.0]) if notch.edge == "bottom" else np.array([0.0, -1.0]))
                )
            )
            end = px + 0.08 * direction
            tick.lineTo(_point(end[0], end[1], offset))
            item = QGraphicsPathItem(tick)
            np_ = QPen(QColor("#ff7f0e"), 2)
            np_.setCosmetic(True)
            item.setPen(np_)
            item.setToolTip(f"notch {notch.edge} {notch.position:.2f}")
            scene.addItem(item)
        for tape in ann.tape_paths:
            path = QPainterPath(_point(tape.points[0][0], tape.points[0][1], offset))
            for px_, py_ in tape.points[1:]:
                path.lineTo(_point(px_, py_, offset))
            item = QGraphicsPathItem(path)
            tp = QPen(QColor("#ff7f0e"), 4)
            tp.setCosmetic(True)
            item.setPen(tp)
            item.setToolTip(f"tape {tape.name}")
            scene.addItem(item)
        for i, feature in enumerate(ann.feature_locations):
            marker = FeatureMarker(self.view, row.label, i, feature.radius)
            marker.setPos(_point(feature.x, feature.y, offset))
            marker.setToolTip(f"feature {feature.feature} (r {feature.radius:g} m)")
            scene.addItem(marker)
        if selected and self.edit_outline.isChecked():
            points = manual.points if manual is not None else editable_outline(row)
            self.view.edit_letter = row.label
            for i, (px_, py_) in enumerate(points):
                handle = OutlineHandle(self.view, i, _point(px_, py_, offset))
                scene.addItem(handle)
                self.view.handles.append(handle)

    @staticmethod
    def _edges(row: PanelRow) -> dict[str, tuple[np.ndarray, np.ndarray]]:
        e = row.right_edge
        br, tr = e[0], e[-1]
        bl, tl = br * np.array([-1.0, 1.0]), tr * np.array([-1.0, 1.0])
        return {"right": (br, tr), "left": (bl, tl), "bottom": (bl, br), "top": (tl, tr)}

    # -- form ---------------------------------------------------------------------------

    def _fill_form(self) -> None:
        session = self.controller.session
        letter = self.selected_letter()
        enabled = session is not None and letter is not None and self.controller.is_gore
        for w in (
            self.label_text,
            self.grain,
            self.zone,
            self.row_allowance,
            self.default_allowance,
        ):
            w.setEnabled(enabled)
        if not enabled or session is None or letter is None:
            self.row_label.setText("-")
            return
        design = session.design
        ann = session.patterns.row(letter)
        self.row_label.setText(letter)
        self.label_text.setText(ann.label_text or "")
        self.grain.setValue(ann.grain_angle_deg)
        self.zone.clear()
        self.zone.addItems(list(design.zones))
        self.zone.setCurrentText(row_zone(design, session.patterns, letter))
        self.default_allowance.setValue(default_allowance(design) * 1000)
        self.row_allowance.setValue(
            -1.0 if ann.seam_allowance is None else ann.seam_allowance * 1000
        )
        self.feature.clear()
        for i, f in enumerate(design.features):
            self.feature.addItem(f"{i}: {f.type}", i)
        self.clear_override.setEnabled(ann.manual_outline is not None)
        row = self.rows_by_letter().get(letter)
        if row is not None:
            self.tape_y.setMaximum(row.finished_height)

    def _row_edit(self, values: dict[str, object], text: str) -> None:
        letter = self.selected_letter()
        if letter is not None and not self._updating:
            self.controller.set_row_pattern(letter, values, f"Row {letter}: {text}")

    def _label_edited(self) -> None:
        self._row_edit({"label_text": self.label_text.text().strip() or None}, "label")

    def _grain_edited(self) -> None:
        self._row_edit({"grain_angle_deg": float(self.grain.value())}, "grain direction")

    def _zone_edited(self) -> None:
        self._row_edit({"zone": self.zone.currentText() or None}, "fabric zone")

    def _default_allowance_edited(self) -> None:
        if not self._updating:
            self.controller.edit("set_seam_allowance", self.default_allowance.value() / 1000)

    def _row_allowance_edited(self) -> None:
        value = self.row_allowance.value()
        letter = self.selected_letter()
        if self._updating or letter is None:
            return
        if value < 0:
            self._row_edit({"seam_allowance": None}, "seam allowance default")
        else:
            self.controller.edit("set_seam_allowance", value / 1000, letter)

    def _add_notch(self) -> None:
        session = self.controller.session
        letter = self.selected_letter()
        if session is None or letter is None:
            return
        notches = [n.model_dump() for n in session.patterns.row(letter).notches]
        notches.append({"edge": self.notch_edge.currentText(), "position": self.notch_pos.value()})
        self._row_edit({"notches": notches}, "add notch")

    def _add_tape(self) -> None:
        session = self.controller.session
        letter = self.selected_letter()
        row = self.rows_by_letter().get(letter or "")
        if session is None or letter is None or row is None:
            return
        y = self.tape_y.value()
        half = float(np.interp(y, row.right_edge[:, 1], row.right_edge[:, 0]))
        tapes = [t.model_dump() for t in session.patterns.row(letter).tape_paths]
        tapes.append(
            {"name": f"tape {len(tapes) + 1}", "points": [(-0.8 * half, y), (0.8 * half, y)]}
        )
        self._row_edit({"tape_paths": tapes}, "add tape path")

    def _add_feature(self) -> None:
        session = self.controller.session
        letter = self.selected_letter()
        row = self.rows_by_letter().get(letter or "")
        if session is None or letter is None or row is None:
            return
        if self.feature.currentData() is None:
            self.controller.editRejected.emit("the design has no features to place")
            return
        feats = [f.model_dump() for f in session.patterns.row(letter).feature_locations]
        feats.append(
            {
                "feature": int(self.feature.currentData()),
                "x": 0.0,
                "y": row.finished_height / 2,
                "radius": self.feature_r.value(),
            }
        )
        self._row_edit({"feature_locations": feats}, "place feature")

    def _clear_annotations(self) -> None:
        self._row_edit({"notches": [], "tape_paths": [], "feature_locations": []}, "clear marks")

    def _clear_override(self) -> None:
        letter = self.selected_letter()
        if letter is not None:
            self.controller.edit("clear_manual_outline", letter)

    def _toggle_stack(self, on: bool) -> None:
        self.controller.prefs.stack_pattern_rows = on
        self.refresh()
        self.fit()

    def _toggle_edit(self, on: bool) -> None:
        if on and self.controller.artifact_status("patterns") != "current":
            self.controller.regenerate_patterns()
        self.refresh()
