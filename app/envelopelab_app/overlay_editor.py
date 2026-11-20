"""Editor of an overlay: an appliqué patch sewn on the envelope (ADR-0056).

Shown in the Special shapes mode in place of the shape editor when an overlay is selected
in the list. From the top: name; where its centre lies (gore, tape position, across); its
outline (circle, ellipse, rectangle, polygon by corners, or an outline imported from a DXF
or SVG file), size and turn; the hem turned under round it; its fabric and colour; then
the cut piece drawn (the cut line, the sew line dotted, the numbered marks where it
crosses seams) with what it covers and how well it fits the curved envelope.

A polygon is shaped in that drawing (:class:`PiecePreview`): drag a corner to move it,
double click an edge to add a corner, double click or right click a corner to remove it;
the corner table (folded away) is for typing exact values. **Symmetry** gives it mirror
axes (shape one slice, the rest follows) and the **Scale** dial beside the drawing scales
the whole shape about its centre.

The editor computes nothing: it shows the overlay and its layout
(:func:`envelopelab.project.overlays.overlay_layout`) it is given, and reports every
change as field values (JSON: m, degrees) through ``changed`` (live: being spun).
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDial,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from envelopelab.project.overlays import OUTLINE_KINDS

#: Symmetry choices: mirror axes and their text.
SYMMETRIES: tuple[tuple[int, str], ...] = (
    (0, "None"),
    (1, "1 axis (left/right)"),
    (2, "2 axes (left/right, up/down)"),
    (3, "3 axes"),
    (4, "4 axes"),
    (5, "5 axes (star)"),
    (6, "6 axes"),
    (8, "8 axes"),
)
#: Dial steps each way: a full turn either way scales by 2 (or 1/2).
SCALE_STEPS = 100

KIND_TEXT = {
    "circle": "Circle",
    "ellipse": "Ellipse",
    "rectangle": "Rectangle",
    "polygon": "Polygon (corners)",
    "outline": "Imported outline (DXF/SVG)",
}


#: Distance from a corner (or an edge) within which the pointer takes it, px.
PICK_PX = 8.0


def _turn(points: np.ndarray, deg: float) -> np.ndarray:
    """``points`` turned anticlockwise by ``deg`` degrees (as the overlay's turn)."""
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    out: np.ndarray = np.asarray(points, dtype=np.float64) @ np.array([[c, s], [-s, c]])
    return out


def _slice_angle(point: np.ndarray) -> float:
    """Angle of a corner from the first mirror axis (up), anticlockwise, degrees."""
    return (math.degrees(math.atan2(float(point[1]), float(point[0]))) - 90.0) % 360.0


def _in_slice(point: np.ndarray, axes: int) -> bool:
    """Whether a corner lies in the slice between the first two mirror axes."""
    return _slice_angle(point) <= 180.0 / axes + 1e-9


class PiecePreview(QWidget):
    """The overlay's cut piece: cut line solid, sew line dotted, seam marks numbered.

    For a polygon the corners are handles (module docstring of
    :mod:`envelopelab_app.overlay_editor`): drag a corner to move it, double click an
    edge to add a corner, double click or right click a corner to remove it (three stay).
    The drawing keeps its scale while a corner is dragged. A change that would make the
    outline cross itself is drawn red and not reported.

    Signals
    -------
    cornersChanged(list, bool)
        The new corners (m about the centre, before the turn) and whether the change is
        live (a corner being dragged: the drag is one undo step).
    """

    cornersChanged = Signal(list, bool)  # noqa: N815 (Qt naming)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("overlayPiecePreview")
        self.finished: np.ndarray | None = None
        self.cut: np.ndarray | None = None
        self.marks: list[tuple[float, float, str]] = []
        self.colour: str | None = None
        #: Polygon corners about the centre before the turn, m (None: not a polygon): the
        #: whole outline, generated from ``chain`` when it has mirror axes.
        self.corners: np.ndarray | None = None
        #: The corners stored (one slice between two axes when ``axes`` > 0), m.
        self.chain: np.ndarray | None = None
        #: Mirror axes (0: none) and, per corner of ``corners``, the chain corner it is an
        #: image of and the matrix making it (:func:`envelopelab.project.overlays.
        #: symmetric_polygon`).
        self.axes = 0
        self._owners: list[tuple[int, np.ndarray]] = []
        self.turn_deg = 0.0
        #: Returns "" for corners that make a valid outline, else why not.
        self.validate: Any = lambda _corners: ""
        self._drag: int | None = None
        self._frozen: tuple[float, float, float] | None = None
        self._invalid = False
        self.setMinimumSize(240, 300)
        self.setMouseTracking(True)

    def set_piece(
        self,
        finished: np.ndarray | None,
        cut: np.ndarray | None,
        marks: list[tuple[float, float, str]],
        colour: str | None,
    ) -> None:
        self.finished, self.cut, self.marks, self.colour = finished, cut, marks, colour
        self.update()

    def set_corners(self, corners: Any, turn_deg: float, axes: int = 0) -> None:
        """Make the polygon ``corners`` (m about the centre; with ``axes`` mirror axes the
        corners of one slice) draggable (None: none)."""
        if self._drag is not None:
            return  # the corners being dragged are ours
        self.axes = axes
        self.turn_deg = turn_deg
        self._set_chain(None if corners is None else np.asarray(corners, dtype=np.float64))
        self._invalid = False
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()

    # -- frame: m to pixels -------------------------------------------------------------

    def frame(self) -> tuple[float, float, float]:
        """Scale (px per m) and the centre of the drawing (m); kept while dragging."""
        if self._frozen is not None:
            return self._frozen
        parts = [a for a in (self.cut, self._turned()) if a is not None and len(a)]
        if not parts:
            return 1.0, 0.0, 0.0
        pts = np.vstack(parts)
        lo, hi = pts.min(axis=0), pts.max(axis=0)
        k = 0.85 * min(
            self.width() / max(hi[0] - lo[0], 1e-9), self.height() / max(hi[1] - lo[1], 1e-9)
        )
        return k, 0.5 * float(lo[0] + hi[0]), 0.5 * float(lo[1] + hi[1])

    def to_screen(self, x: float, y: float) -> QPointF:
        k, cx, cy = self.frame()
        return QPointF(self.width() / 2 + (x - cx) * k, self.height() / 2 - (y - cy) * k)

    def to_cloth(self, p: QPointF) -> tuple[float, float]:
        k, cx, cy = self.frame()
        return cx + (p.x() - self.width() / 2) / k, cy - (p.y() - self.height() / 2) / k

    def _set_chain(self, chain: np.ndarray | None) -> None:
        from envelopelab.project.overlays import symmetric_polygon

        self.chain = chain
        if chain is None:
            self.corners, self._owners = None, []
        elif self.axes:
            self.corners, self._owners = symmetric_polygon(chain, self.axes)
        else:
            identity = np.eye(2)
            self.corners, self._owners = chain, [(i, identity) for i in range(len(chain))]

    def _turned(self) -> np.ndarray | None:
        return None if self.corners is None else _turn(self.corners, self.turn_deg)

    def corner_at(self, p: QPointF) -> int | None:
        """The corner under widget point ``p`` (None: none)."""
        turned = self._turned()
        if turned is None:
            return None
        for i, (x, y) in enumerate(turned):
            q = self.to_screen(float(x), float(y))
            if math.hypot(q.x() - p.x(), q.y() - p.y()) <= PICK_PX:
                return i
        return None

    def edge_at(self, p: QPointF) -> int | None:
        """The edge (from corner i to i + 1) under widget point ``p`` (None: none)."""
        turned = self._turned()
        if turned is None:
            return None
        n = len(turned)
        for i in range(n):
            a = self.to_screen(*map(float, turned[i]))
            b = self.to_screen(*map(float, turned[(i + 1) % n]))
            dx, dy = b.x() - a.x(), b.y() - a.y()
            length2 = dx * dx + dy * dy
            if length2 <= 0.0:
                continue
            t = max(0.0, min(1.0, ((p.x() - a.x()) * dx + (p.y() - a.y()) * dy) / length2))
            if math.hypot(a.x() + t * dx - p.x(), a.y() + t * dy - p.y()) <= PICK_PX:
                return i
        return None

    # -- editing ------------------------------------------------------------------------

    def _unturned(self, p: QPointF) -> np.ndarray:
        """Widget point ``p`` as a corner about the centre before the turn, m (to 1 mm)."""
        point = _turn(np.array([self.to_cloth(p)]), -self.turn_deg)[0]
        out: np.ndarray = np.round(point, 3)
        return out

    def _report(self, chain: np.ndarray, live: bool) -> None:
        """Show ``chain`` (the corners stored) and report it when it is valid."""
        self._set_chain(chain)
        reason = self.validate(chain.tolist())
        self._invalid = bool(reason)
        self.setToolTip(reason)
        if not reason:
            self.cornersChanged.emit(chain.tolist(), live)
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt API)
        if self.corners is None:
            return
        i = self.corner_at(event.position())
        if event.button() == Qt.MouseButton.RightButton and i is not None:
            self.remove_corner(i)
            return
        if event.button() == Qt.MouseButton.LeftButton and i is not None:
            self._drag = i
            self._frozen = self.frame()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt API)
        if self.corners is None:
            return
        if self._drag is None:
            over = self.corner_at(event.position()) is not None
            self.setCursor(Qt.CursorShape.OpenHandCursor if over else Qt.CursorShape.ArrowCursor)
            return
        assert self.chain is not None
        # The corner dragged is an image of a chain corner: move that one (every image
        # follows; T is orthogonal, so its inverse is its transpose).
        g, t = self._owners[self._drag]
        chain = self.chain.copy()
        chain[g] = np.round(self._unturned(event.position()) @ t.T, 3)
        self._report(chain, live=True)

    def mouseReleaseEvent(self, _event: QMouseEvent) -> None:  # noqa: N802 (Qt API)
        if self._drag is None:
            return
        self._drag = None
        self._frozen = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.update()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt API)
        if self.corners is None:
            return
        i = self.corner_at(event.position())
        if i is not None:
            self.remove_corner(i)
            return
        edge = self.edge_at(event.position())
        if edge is not None:
            self.add_corner(edge, event.position())

    def add_corner(self, edge: int, at: QPointF) -> None:
        """Add a corner at widget point ``at`` on the edge after corner ``edge``."""
        if self.corners is None or self.chain is None:
            return
        n = len(self.corners)
        (ga, ta), (gb, tb) = self._owners[edge], self._owners[(edge + 1) % n]
        q = self._unturned(at)
        if not self.axes:
            index, point = edge + 1, q
        elif np.allclose(ta, tb):
            # Between two corners of the same image of the slice.
            index, point = max(ga, gb), q @ ta.T
        else:
            # The edge crosses an axis: take the click back into the slice through the
            # image it lands in, and add it at that end of the slice.
            g, t = next(
                ((g, t) for g, t in ((ga, ta), (gb, tb)) if _in_slice(q @ t.T, self.axes)),
                (ga, ta),
            )
            point = q @ t.T
            index = 0 if g == 0 and len(self.chain) > 1 else len(self.chain)
            if g == 0 and len(self.chain) == 1:
                # One corner: before it if the click is nearer the first axis.
                index = 0 if _slice_angle(point) < _slice_angle(self.chain[0]) else 1
        self._report(np.insert(self.chain, index, np.round(point, 3), axis=0), live=False)

    def remove_corner(self, i: int) -> None:
        """Remove corner ``i`` (a polygon keeps at least three)."""
        if self.chain is None:
            return
        least = 3 if not self.axes else (2 if self.axes == 1 else 1)
        if len(self.chain) <= least:
            return
        g = self._owners[i][0]
        self._report(np.delete(self.chain, g, axis=0), live=False)

    # -- drawing ------------------------------------------------------------------------

    def paintEvent(self, _event: object) -> None:  # noqa: N802 (Qt API)
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("white"))
        if self.cut is None or self.finished is None:
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No piece")
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        def path(points: np.ndarray, closed: bool = True) -> QPainterPath:
            out = QPainterPath()
            out.addPolygon(QPolygonF([self.to_screen(float(x), float(y)) for x, y in points]))
            if closed:
                out.closeSubpath()
            return out

        fill = QColor(self.colour) if self.colour else QColor("#f3e6cf")
        p.fillPath(path(self.finished), fill)
        p.strokePath(path(self.cut), QPen(QColor("#202020"), 1.2))
        dotted = QPen(QColor("#606060"), 1.0)
        dotted.setStyle(Qt.PenStyle.DotLine)
        p.strokePath(path(self.finished), dotted)
        p.setPen(QPen(QColor("#c62828")))
        for x, y, text in self.marks:
            q = self.to_screen(x, y)
            p.drawLine(QPointF(q.x() - 4, q.y()), QPointF(q.x() + 4, q.y()))
            p.drawLine(QPointF(q.x(), q.y() - 4), QPointF(q.x(), q.y() + 4))
            p.drawText(QPointF(q.x() + 5, q.y() - 5), text)
        turned = self._turned()
        if turned is None:
            return
        # The mirror axes through the centre, turned with the overlay.
        if self.axes:
            from envelopelab.project.overlays import axis_angles

            reach = 0.6 * float(np.max(np.ptp(self.cut, axis=0)))
            axis_pen = QPen(QColor("#2e7d32"), 1.0)
            axis_pen.setStyle(Qt.PenStyle.DashDotLine)
            p.setPen(axis_pen)
            for angle in axis_angles(self.axes):
                a = math.radians(angle + self.turn_deg)
                d = reach * np.array([math.cos(a), math.sin(a)])
                p.drawLine(self.to_screen(*map(float, -d)), self.to_screen(*map(float, d)))
        # The corners: their polygon (red while it would cross itself) and a handle each.
        line = QPen(QColor("#c62828" if self._invalid else "#1565c0"), 1.0)
        line.setStyle(Qt.PenStyle.DashLine)
        p.strokePath(path(turned), line)
        p.setPen(QPen(QColor("#0d47a1"), 1.2))
        for i, (x, y) in enumerate(turned):
            q = self.to_screen(float(x), float(y))
            p.setBrush(QColor("#ff8f00") if i == self._drag else QColor("white"))
            p.drawRect(int(q.x()) - 4, int(q.y()) - 4, 8, 8)
        p.setPen(QPen(QColor("#5f6b7a")))
        p.drawText(
            8,
            self.height() - 8,
            "Drag a corner; double click an edge: add one; double click or right click a "
            "corner: remove it",
        )


class OverlayEditor(QWidget):
    """See module docstring.

    Signals
    -------
    changed(dict, bool)
        New field values (JSON, m and degrees; ``placement`` holds only the fields that
        change) and whether the change is live (a value being spun: one undo step).
    colourRequested()
        Choose the overlay's colour.
    """

    changed = Signal(dict, bool)
    colourRequested = Signal()  # noqa: N815 (Qt naming)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("overlayEditor")
        self._filling = False
        self.spec: Any = None
        layout = QVBoxLayout(self)
        intro = QLabel(
            "An overlay is an appliqué: a flat patch of cloth sewn on top of the envelope, "
            "anywhere and across seams. Drag it on the gore map or in 3D; the build pack "
            "gets its cut piece and the line to sew it on, marked on every panel it crosses."
        )
        intro.setWordWrap(True)
        intro.setObjectName("hint")
        layout.addWidget(intro)
        form = QFormLayout()
        self.name = QLineEdit()
        self.name.setObjectName("overlayName")
        self.name.editingFinished.connect(self._name_done)
        form.addRow("Name", self.name)
        self.gore = QSpinBox()
        self.gore.setRange(1, 200)
        self.gore.valueChanged.connect(lambda v: self._emit({"placement": {"gore": v}}))
        form.addRow("Gore", self.gore)
        self.tape = self._spin(0.0, 1000.0, 3, " m", lambda v: {"placement": {"tape_position": v}})
        form.addRow("Tape position from mouth", self.tape)
        self.across = self._spin(-0.5, 0.5, 3, "", lambda v: {"placement": {"across": v}})
        self.across.setSingleStep(0.05)
        form.addRow("Across gore (-0.5...0.5)", self.across)
        self.kind = QComboBox()
        self.kind.setObjectName("overlayKind")
        for kind in OUTLINE_KINDS:
            self.kind.addItem(KIND_TEXT[kind], kind)
        self.kind.currentIndexChanged.connect(self._kind_chosen)
        form.addRow("Outline", self.kind)
        self.width_box = self._spin(1.0, 50000.0, 0, " mm", lambda v: {"width": v / 1000.0})
        self.width_box.setObjectName("overlayWidth")
        form.addRow("Width (across)", self.width_box)
        self.height_box = self._spin(1.0, 50000.0, 0, " mm", lambda v: {"height": v / 1000.0})
        self.height_box.setObjectName("overlayHeight")
        form.addRow("Height (up the tape)", self.height_box)
        self.turn = self._spin(-180.0, 180.0, 1, "°", lambda v: {"turn_deg": v})
        form.addRow("Turn", self.turn)
        self.hem = self._spin(0.0, 100.0, 0, " mm", lambda v: {"hem": v / 1000.0})
        form.addRow("Hem turned under", self.hem)
        self.fabric = QLineEdit()
        self.fabric.setPlaceholderText("as the panel under its centre")
        self.fabric.editingFinished.connect(
            lambda: self._emit({"fabric": self.fabric.text().strip() or None})
        )
        form.addRow("Fabric", self.fabric)
        self.colour_button = QPushButton("Colour…")
        self.colour_button.setObjectName("overlayColour")
        self.colour_button.clicked.connect(lambda _c=False: self.colourRequested.emit())
        form.addRow("Colour", self.colour_button)
        layout.addLayout(form)

        # Polygon: the corners are dragged in the drawing below; the table (folded away)
        # is for typing exact values.
        self.points_box = QWidget()
        points_layout = QVBoxLayout(self.points_box)
        points_layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.smooth = QCheckBox("Smooth curve through the corners")
        self.smooth.toggled.connect(lambda on: self._emit({"smooth": on}))
        self.symmetry = QComboBox()
        self.symmetry.setObjectName("overlaySymmetry")
        self.symmetry.setToolTip(
            "Mirror axes through the centre: shape one slice between two axes and the "
            "rest follows (dashed green lines in the drawing)"
        )
        for axes, text in SYMMETRIES:
            self.symmetry.addItem(text, axes)
        self.symmetry.currentIndexChanged.connect(self._symmetry_chosen)
        self.table_button = QToolButton()
        self.table_button.setObjectName("overlayTableToggle")
        self.table_button.setText("Corner table (mm) ▸")
        self.table_button.setCheckable(True)
        self.table_button.setToolTip("Type exact corner positions instead of dragging them")
        row.addWidget(QLabel("Symmetry"))
        row.addWidget(self.symmetry)
        row.addWidget(self.smooth)
        row.addStretch(1)
        row.addWidget(self.table_button)
        points_layout.addLayout(row)
        self.table_box = QWidget()
        table_layout = QVBoxLayout(self.table_box)
        table_layout.setContentsMargins(0, 0, 0, 0)
        self.table_label = QLabel("Corners about the centre (mm): across, up")
        table_layout.addWidget(self.table_label)
        self.points = QTableWidget(0, 2)
        self.points.setObjectName("overlayPoints")
        self.points.setHorizontalHeaderLabels(["across", "up"])
        self.points.itemChanged.connect(self._points_edited)
        table_layout.addWidget(self.points)
        buttons = QHBoxLayout()
        add = QPushButton("Add corner")
        add.clicked.connect(self._add_point)
        remove = QPushButton("Remove corner")
        remove.clicked.connect(self._remove_point)
        buttons.addWidget(add)
        buttons.addWidget(remove)
        table_layout.addLayout(buttons)
        self.table_box.setVisible(False)
        self.table_button.toggled.connect(self._show_table)
        points_layout.addWidget(self.table_box)
        layout.addWidget(self.points_box)
        self.import_box = QWidget()
        import_layout = QHBoxLayout(self.import_box)
        import_layout.setContentsMargins(0, 0, 0, 0)
        self.import_button = QPushButton("Import outline…")
        self.import_button.setObjectName("overlayImport")
        self.import_button.clicked.connect(self._import_dialog)
        self.source = QLabel()
        import_layout.addWidget(self.import_button)
        import_layout.addWidget(self.source, 1)
        layout.addWidget(self.import_box)

        self.preview = PiecePreview()
        self.preview.validate = self._corners_problem
        self.preview.cornersChanged.connect(
            lambda corners, live: self._emit({"points": corners}, live=live)
        )
        # The drawing with the scale dial beside it.
        drawing = QHBoxLayout()
        drawing.addWidget(self.preview, 1)
        dial_box = QVBoxLayout()
        dial_box.addWidget(QLabel("Scale"), 0, Qt.AlignmentFlag.AlignHCenter)
        self.scale_dial = QDial()
        self.scale_dial.setObjectName("overlayScale")
        self.scale_dial.setRange(-SCALE_STEPS, SCALE_STEPS)
        self.scale_dial.setNotchesVisible(True)
        self.scale_dial.setFixedSize(72, 72)
        self.scale_dial.setToolTip(
            "Turn to scale the whole shape about its centre (×0.5 to ×2 per turn; one undo "
            "step per turn)"
        )
        self.scale_dial.valueChanged.connect(self._scale_turned)
        self.scale_dial.sliderReleased.connect(self._scale_done)
        self.scale_label = QLabel("×1.00")
        self.scale_label.setObjectName("overlayScaleLabel")
        dial_box.addWidget(self.scale_dial)
        dial_box.addWidget(self.scale_label, 0, Qt.AlignmentFlag.AlignHCenter)
        dial_box.addStretch(1)
        drawing.addLayout(dial_box)
        layout.addLayout(drawing, 1)
        #: What the dial scales from: the corners, or width and height (None: idle).
        self._scale_base: dict[str, Any] | None = None
        self.info = QLabel()
        self.info.setObjectName("overlayInfo")
        self.info.setWordWrap(True)
        layout.addWidget(self.info)

    def _spin(
        self, lo: float, hi: float, decimals: int, suffix: str, values: Any
    ) -> QDoubleSpinBox:
        box = QDoubleSpinBox()
        box.setRange(lo, hi)
        box.setDecimals(decimals)
        box.setSuffix(suffix)
        box.setKeyboardTracking(False)
        box.valueChanged.connect(lambda v: self._emit(values(v), live=True))
        return box

    # -- showing ----------------------------------------------------------------------

    def set_overlay(
        self, spec: Any, layout: Any, error: str, colour: str | None, gores: int
    ) -> None:
        """Show ``spec`` and its ``layout`` (None when it cannot be laid: ``error``)."""
        self.spec = spec
        self._filling = True
        try:
            self.name.setText(spec.name)
            self.gore.setMaximum(max(gores, 1))
            self.gore.setValue(spec.placement.gore)
            self.tape.setValue(spec.placement.tape_position)
            self.across.setValue(spec.placement.across)
            self.kind.setCurrentIndex(OUTLINE_KINDS.index(spec.outline))
            self.width_box.setValue(spec.width * 1000.0)
            self.height_box.setValue(spec.height * 1000.0)
            # A polygon's size is its corners (dragged in the drawing).
            self.width_box.setEnabled(spec.outline != "polygon")
            self.height_box.setEnabled(spec.outline not in ("circle", "polygon"))
            self.turn.setValue(spec.turn_deg)
            self.hem.setValue(spec.hem * 1000.0)
            self.fabric.setText(spec.fabric or "")
            self.smooth.setChecked(spec.smooth)
            self.points_box.setVisible(spec.outline == "polygon")
            self.import_box.setVisible(spec.outline == "outline")
            self.source.setText(spec.source or "no file imported")
            self.points.setRowCount(len(spec.points))
            for i, (x, y) in enumerate(spec.points):
                self.points.setItem(i, 0, QTableWidgetItem(f"{x * 1000.0:.0f}"))
                self.points.setItem(i, 1, QTableWidgetItem(f"{y * 1000.0:.0f}"))
            self.colour_button.setText(colour or "Colour…")
            self.colour_button.setStyleSheet(
                f"background: {colour}; color: {'white' if _dark(colour) else 'black'};"
                if colour
                else ""
            )
        finally:
            self._filling = False
        polygon = spec.outline == "polygon"
        self.preview.set_corners(spec.points if polygon else None, spec.turn_deg, spec.symmetry)
        self._filling = True
        try:
            self.symmetry.setCurrentIndex(
                next((i for i, (a, _t) in enumerate(SYMMETRIES) if a == spec.symmetry), 0)
            )
        finally:
            self._filling = False
        self.table_label.setText(
            "Corners of one slice between the first two axes (mm): across, up"
            if spec.symmetry
            else "Corners about the centre (mm): across, up"
        )
        if layout is None:
            self.preview.set_piece(None, None, [], colour)
            self.info.setText(f"<span style='color:#b00020'>{error}</span>")
            return
        from envelopelab.geometry.polygon import offset_polygon

        finished = layout.outline
        cut = offset_polygon(finished, spec.hem) if spec.hem > 0 else finished
        marks = [
            (float(p[0]), float(p[1]), str(k + 1)) for k, (p, *_r) in enumerate(layout.crossings)
        ]
        self.preview.set_piece(finished, cut, marks, colour)
        area = 0.5 * abs(
            float(np.dot(finished[:, 0], np.roll(finished[:, 1], -1)))
            - float(np.dot(np.roll(finished[:, 0], -1), finished[:, 1]))
        )
        panels = ", ".join(f"G{g}{r}" for g, r in layout.covered)
        text = (
            f"Finished outline {layout.perimeter * 1000:.0f} mm, area {area:.2f} m²; "
            f"crosses {len(layout.crossings)} seam(s); lies over {panels}. "
            f"Outline on the piece less the line marked on the panels: "
            f"{layout.ease * 1000:+.0f} mm."
        )
        warnings = layout.warnings()
        if warnings:
            text += "<br><span style='color:#b26a00'>⚠ " + "<br>⚠ ".join(warnings) + "</span>"
        self.info.setText(text)

    # -- edits ------------------------------------------------------------------------

    def _symmetry_chosen(self, index: int) -> None:
        """Give the polygon ``axes`` mirror axes, keeping its shape where it can: the
        corners in the first slice become the corners stored (none: the whole outline)."""
        from envelopelab.project.overlays import slice_corners, symmetric_polygon

        axes = int(self.symmetry.itemData(index))
        spec = self.spec
        if self._filling or spec is None or axes == spec.symmetry:
            return
        if spec.outline == "polygon" and spec.points:
            whole = (
                symmetric_polygon(spec.points, spec.symmetry)[0]
                if spec.symmetry
                else np.asarray(spec.points, dtype=np.float64)
            )
        elif spec.outline in ("circle", "ellipse") and axes:
            # A finely sampled curve would give a corner every few degrees: start from a
            # star (one axis: a diamond) as large instead. With no corners given,
            # slice_corners returns one 0.5 m out.
            r = 0.5 * max(spec.width, spec.height)
            star = slice_corners(np.zeros((0, 2)), axes) * (r / 0.5)
            self._emit(
                {"outline": "polygon", "symmetry": axes, "points": np.round(star, 4).tolist()}
            )
            return
        else:  # a rectangle or an imported outline: keep its corners
            from envelopelab.project.overlays import outline_points

            whole = _turn(outline_points(spec), -spec.turn_deg)
        points = slice_corners(whole, axes) if axes else whole
        self._emit(
            {
                "outline": "polygon",
                "symmetry": axes,
                "points": np.round(points, 4).tolist(),
            }
        )

    def _scale_turned(self, value: int) -> None:
        """Scale the shape by the dial's turn from where it was when the turn began."""
        spec = self.spec
        if self._filling or spec is None:
            return
        factor = 2.0 ** (value / SCALE_STEPS)
        self.scale_label.setText(f"×{factor:.2f}")
        if self._scale_base is None:
            self._scale_base = {
                "points": [list(p) for p in spec.points],
                "width": spec.width,
                "height": spec.height,
            }
        base = self._scale_base
        if spec.outline == "polygon":
            values: dict[str, Any] = {
                "points": np.round(np.asarray(base["points"]) * factor, 4).tolist()
            }
        else:
            values = {"width": base["width"] * factor, "height": base["height"] * factor}
        self._emit(values, live=True)

    def _scale_done(self) -> None:
        """The dial is let go: the next turn scales from the new size."""
        self._scale_base = None
        self.scale_dial.blockSignals(True)
        self.scale_dial.setValue(0)
        self.scale_dial.blockSignals(False)
        self.scale_label.setText("×1.00")

    def _show_table(self, on: bool) -> None:
        self.table_box.setVisible(on)
        self.table_button.setText("Corner table (mm) ▾" if on else "Corner table (mm) ▸")

    def _corners_problem(self, corners: list[list[float]]) -> str:
        """Why ``corners`` (m) make no valid outline ("" when they do)."""
        from envelopelab.project.overlays import outline_points

        if self.spec is None:
            return "no overlay"
        try:
            outline_points(self.spec.model_copy(update={"points": [tuple(c) for c in corners]}))
        except ValueError as exc:
            return str(exc)
        return ""

    def _emit(self, values: dict[str, Any], live: bool = False) -> None:
        if not self._filling and self.spec is not None:
            self.changed.emit(values, live)

    def _name_done(self) -> None:
        text = self.name.text().strip()
        if self.spec is not None and text and text != self.spec.name:
            self._emit({"name": text})

    def _kind_chosen(self, index: int) -> None:
        kind = self.kind.itemData(index)
        if self._filling or self.spec is None or kind == self.spec.outline:
            return
        values: dict[str, Any] = {"outline": kind}
        if kind == "polygon" and len(self.spec.points) < 3:
            w, h = 0.5 * self.spec.width, 0.5 * self.spec.height
            values["points"] = [[0.0, h], [w, -h], [-w, -h]]  # a triangle to start from
        if kind == "outline" and len(self.spec.points) < 3:
            self.import_dialog_then(values)
            return
        self._emit(values)

    def import_dialog_then(self, values: dict[str, Any]) -> None:
        """Ask for an outline file, then apply ``values`` with its points."""
        path, _ = QFileDialog.getOpenFileName(self, "Import outline", "", "Outlines (*.dxf *.svg)")
        if path:
            self.import_outline(path, values)
        else:
            self.set_overlay(self.spec, None, "choose an outline file", None, self.gore.maximum())

    def _import_dialog(self) -> None:
        self.import_dialog_then({})

    def import_outline(self, path: str, values: dict[str, Any] | None = None) -> None:
        """Use the largest closed outline of a DXF or SVG file."""
        from pathlib import Path

        from envelopelab.io.outline_file import OutlineFileError, read_outline

        try:
            points = read_outline(path)
        except (OutlineFileError, OSError, ValueError) as exc:
            self.info.setText(f"<span style='color:#b00020'>{exc}</span>")
            return
        data = dict(values or {})
        data.update(
            {
                "outline": "outline",
                "points": [[float(x), float(y)] for x, y in points],
                "source": Path(path).name,
            }
        )
        self._emit(data)

    def _table_points(self) -> list[list[float]] | None:
        out = []
        for i in range(self.points.rowCount()):
            try:
                x = float(self.points.item(i, 0).text()) / 1000.0  # type: ignore[union-attr]
                y = float(self.points.item(i, 1).text()) / 1000.0  # type: ignore[union-attr]
            except (AttributeError, ValueError):
                return None
            out.append([x, y])
        return out

    def _points_edited(self, _item: object) -> None:
        if self._filling:
            return
        points = self._table_points()
        if points is not None and len(points) >= 3:
            self._emit({"points": points})

    def _add_point(self) -> None:
        points = self._table_points() or []
        if len(points) >= 2:
            a, b = np.array(points[-1]), np.array(points[0])
            points.append(list(0.5 * (a + b)))
        else:
            points.append([0.0, 0.0])
        if len(points) >= 3:
            self._emit({"points": points})

    def _remove_point(self) -> None:
        points = self._table_points() or []
        row = self.points.currentRow()
        if len(points) > 3:
            points.pop(row if 0 <= row < len(points) else -1)
            self._emit({"points": points})


def _dark(colour: str | None) -> bool:
    return colour is not None and QColor(colour).lightnessF() < 0.5


__all__ = ["KIND_TEXT", "OverlayEditor", "PiecePreview"]
