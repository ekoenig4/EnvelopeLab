"""Special shapes panel: domes, tubes, revolved and imported mesh shapes on the envelope.

The panel has three columns: the project's special shapes; the selected one's editor in
tabs (*Placement & size*, *Profile* for a revolved shape, *Feed holes & cap*, *Panel
layout* (where the seams sit round the axis, how wide each gore or panel is, and where
they are split across), *Simulation*; every change is one undoable edit of the design
state); and in tabs what
:mod:`envelopelab.features.primitives` derives from it: the cut pieces (a drawing of their
outlines that zooms with the mouse wheel and pans by dragging, and their sizes), the
pattern checks and the attachment lines on the envelope panels. The shape simulation
with the preview solver is on the *Simulation* tab. Placing a shape runs in a worker thread
(:class:`~envelopelab_app.shapes_service.ShapeService`), so editing never waits for it;
the panel says "being placed…" until the result arrives. The *On the balloon* tab of the
right column shows where every shape and symmetry axis sits on the balloon, a 3D sketch
over a gore map (:mod:`envelopelab_app.placement_view`); a shape is selected by clicking
it on the map and moved by dragging it there.

Nothing is hidden: a shape that cannot be placed, a failed check, an unconverged or
stale simulation and a factor of safety below the requirement are shown in red here and
listed in the Validation panel. Lengths are shown in m, angles in degrees.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from envelopelab.export.build_pack import DEFAULT_ROLL_WIDTH, PackExtras
from envelopelab.export.templates import MARGIN, roll_fit, turn_points
from envelopelab.features.metrics import REQUIRED_FOS
from envelopelab.features.primitives import CutPiece, PrimitiveDesign, PrimitiveError
from envelopelab.project.model import SOLVER_LABELS
from envelopelab.project.placement_map import snap
from envelopelab.project.shape_groups import group_names
from envelopelab.project.shapes import (
    CAP_PANEL_TOP_WIDTH,
    MAX_PIECES,
    DomeShape,
    MeshShape,
    RevolvedShape,
    ShapeKind,
    ShapePlacement,
    ShapeSpec,
    TubeShape,
    auto_cap_diameter,
    cap_diameter,
    default_shape,
    mesh_shape,
    piece_count,
    placement_at,
    pointed,
    shape_fabrics,
)
from envelopelab.project.symmetry import axis_gore_label
from envelopelab_app.controller import WorkspaceController
from envelopelab_app.hints import set_hint
from envelopelab_app.marking_view import MarkingView
from envelopelab_app.overlay_editor import OverlayEditor
from envelopelab_app.placement_view import (
    AxisPreview,
    PlacedShape,
    PlacementData,
    PlacementView,
)
from envelopelab_app.refresh import Refresher
from envelopelab_app.view_tools import FitButton

FAIL_COLOR = "#b00020"
#: The gore or panel being edited in the Panel layout (as the balloon views' amber).
EDITED_FILL = "#ffc062"
EDITED_EDGE = "#e65100"
WARN_COLOR = "#8a6d3b"
OK_COLOR = "#2e7d32"
SEVERITY_COLORS = {"error": FAIL_COLOR, "warning": WARN_COLOR, "info": "#31708f"}
#: Fill of a cut piece whose page is larger than the print roll both ways.
OVERSIZE_FILL = "#f6e3b4"
KIND_LABELS: dict[str, str] = {
    "dome": "Dome",
    "tube": "Tube",
    "revolved": "Revolved profile",
    "mesh": "Mesh (free-form)",
}
#: Default target element size of a shape simulation, mm.
DEFAULT_MESH_MM = 60.0


@dataclass(frozen=True)
class FieldSpec:
    """One editable number of a shape.

    Attributes
    ----------
    path : tuple of str
        Key of the value in the shape data (``("placement", "gore")`` for placement).
    label : str
        Form label with its unit.
    integer : bool
        Whole number.
    minimum, maximum : float
        Allowed range (unit of the label).
    decimals : int
        Shown decimals.
    """

    path: tuple[str, ...]
    label: str
    integer: bool = False
    minimum: float = 0.0
    maximum: float = 1000.0
    decimals: int = 3


PLACEMENT_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec(("placement", "gore"), "Gore", integer=True, minimum=1, maximum=999),
    FieldSpec(("placement", "tape_position"), "Tape position from mouth (m)", minimum=0.001),
    FieldSpec(("placement", "across"), "Across gore (-0.5…0.5)", minimum=-0.5, maximum=0.5),
    FieldSpec(("placement", "lean_deg"), "Lean (deg)", maximum=75.0, decimals=1),
    FieldSpec(
        ("placement", "lean_toward_deg"),
        "Lean toward (deg, 0 = up)",
        minimum=-360.0,
        maximum=360.0,
        decimals=1,
    ),
)
KIND_FIELDS: dict[str, tuple[FieldSpec, ...]] = {
    "dome": (
        FieldSpec(("base_radius",), "Base radius (m)", minimum=0.001),
        FieldSpec(("height",), "Height (m)", minimum=0.001),
        FieldSpec(("gores",), "Skin gores", integer=True, minimum=3, maximum=64),
    ),
    "tube": (
        FieldSpec(("base_radius",), "Base radius (m)", minimum=0.001),
        FieldSpec(("tip_radius",), "Tip radius (m)"),
        FieldSpec(("length",), "Length (m)", minimum=0.001),
        FieldSpec(("panels",), "Panels", integer=True, minimum=1, maximum=64),
    ),
    "revolved": (FieldSpec(("gores",), "Skin gores", integer=True, minimum=3, maximum=64),),
    "mesh": (FieldSpec(("panels",), "Panels", integer=True, minimum=2, maximum=64),),
}
COMMON_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec(("marks_per_piece",), "Match marks per piece", integer=True, minimum=1, maximum=8),
    FieldSpec(("seam_allowance",), "Seam allowance (m)", maximum=0.2, decimals=4),
)


def _get(data: dict[str, Any], path: tuple[str, ...]) -> Any:
    for key in path:
        data = data[key]
    return data


def _values(path: tuple[str, ...], value: Any) -> dict[str, Any]:
    """Update for :func:`envelopelab.project.edits.update_shape`."""
    if len(path) == 1:
        return {path[0]: value}
    return {path[0]: {path[1]: value}}


def _ask(
    parent: QWidget,
    title: str,
    fields: list[tuple[str, float, float, float, int]],
    check: str | None = None,
) -> list[float] | None:
    """A small dialog of numbers (label, minimum, maximum, value, decimals) and an
    optional tick box (its state comes last, 1 or 0); None when cancelled."""
    from PySide6.QtWidgets import QDialog, QDialogButtonBox

    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    form = QFormLayout(dialog)
    boxes = []
    for label, lo, hi, value, decimals in fields:
        box = QDoubleSpinBox()
        box.setRange(lo, hi)
        box.setDecimals(decimals)
        box.setValue(value)
        form.addRow(label, box)
        boxes.append(box)
    tick = QCheckBox(check) if check else None
    if tick is not None:
        tick.setChecked(True)
        form.addRow(tick)
    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    form.addRow(buttons)
    if not dialog.exec():
        return None
    out = [float(b.value()) for b in boxes]
    return out + ([1.0 if tick.isChecked() else 0.0] if tick is not None else [])


@dataclass
class _AxisSession:
    """A symmetry axis being placed in the On the balloon tab.

    ``mode``: "add", "edit" (``axis`` is moved), "mirror" or "mirror group"; ``line``
    the chosen gore position (None: not yet), ``hover`` the one under the pointer;
    ``targets`` the shapes whose mirror images are previewed; ``fixed`` an existing axis
    was chosen to mirror across; ``grabbed`` it was started by dragging an axis on the
    map (done when the drag ends)."""

    mode: str
    axis: str | None
    line: float | None
    targets: list[str]
    hover: float | None = None
    fixed: bool = False
    grabbed: bool = False
    group: str | None = None


def _scrolled(page: QWidget) -> QScrollArea:
    """``page`` in a frameless scroll area (a tab scrolls instead of squeezing its rows)."""
    area = QScrollArea()
    area.setWidget(page)
    area.setWidgetResizable(True)
    area.setFrameShape(QScrollArea.Shape.NoFrame)
    return area


class MeetingPointPad(QWidget):
    """Where a shape's panels meet, seen from above the shape (ADR-0052).

    The circle is the shape's outline at its widest; the cross marks the tip (0, 0). It
    is drawn as the balloon is seen from outside: right is across the gores (towards
    the next gore), up is up the tape. The seams are
    drawn from the meeting point to where they leave the rim, so the panel layout round
    the point can be seen. Click or drag to move the point (inside the circle); double
    click to put it back on the tip.

    Signals
    -------
    moved(float, float)
        The point was moved to (across, up), fractions of the widest radius.
    """

    moved = Signal(float, float)

    def __init__(self) -> None:
        super().__init__()
        self.across = 0.0
        self.up = 0.0
        #: Seam angles where they leave the rim, rad (0 up the tape, as the seam turn).
        self.seams: list[float] = []
        #: Gore or panel being edited (0-based), filled amber; None: none.
        self.edited: int | None = None
        #: The cap's outline round the point (fractions of the widest radius; None: none).
        self.cap: np.ndarray | None = None
        self.setMinimumSize(230, 190)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setToolTip(
            "Where the panels meet, seen from above the shape: right = across the gores, "
            "up = up the tape. Click or drag to move it; double click: back to the tip."
        )

    def set_state(self, across: float, up: float, seams: list[float]) -> None:
        """Show the point at (across, up) and the seams leaving the rim at ``seams``."""
        self.across, self.up, self.seams = float(across), float(up), list(seams)
        self.update()

    @staticmethod
    def rim_at(phi: float) -> tuple[float, float]:
        """Where seam angle ``phi`` (rad, the shape's frame: 0 up the tape, turning
        towards the previous gore) meets the outline in the pad, as (across, up)
        fractions. Seen from outside the balloon the previous gore is to the left."""
        return -math.sin(phi), math.cos(phi)

    def set_cap(self, outline: np.ndarray | None) -> None:
        """Draw the cap's outline round the point (fractions of the widest radius)."""
        self.cap = None if outline is None else np.asarray(outline, dtype=float)
        self.update()

    def set_edited(self, piece: int | None) -> None:
        """Fill gore or panel ``piece`` (0-based) amber; None: none."""
        self.edited = piece
        self.update()

    def _frame(self) -> tuple[QPointF, float]:
        """Centre and radius of the outline (room for the labels outside it), px."""
        radius = max(min(self.width() - 80.0, self.height() - 34.0) / 2.0, 10.0)
        return QPointF(radius + 10.0, self.height() / 2.0 + 6.0), radius

    def _to_screen(self, across: float, up: float) -> QPointF:
        centre, radius = self._frame()
        return QPointF(centre.x() + across * radius, centre.y() - up * radius)

    def _from_screen(self, point: QPointF) -> tuple[float, float]:
        centre, radius = self._frame()
        across = (point.x() - centre.x()) / radius
        up = (centre.y() - point.y()) / radius
        h = math.hypot(across, up)
        if h > 1.0:  # stay inside the outline
            across, up = across / h, up / h
        if h < 0.03:  # snap to the tip
            across = up = 0.0
        return round(across, 3), round(up, 3)

    def paintEvent(self, _event: object) -> None:  # noqa: N802 (Qt API)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        centre, radius = self._frame()
        enabled = self.isEnabled()
        painter.setBrush(QBrush(QColor("#f3ede2" if enabled else "#f0f0f0")))
        painter.setPen(QPen(QColor("#8a7a66" if enabled else "#bbbbbb"), 1.2))
        painter.drawEllipse(centre, radius, radius)
        point = self._to_screen(self.across, self.up)
        k = self.edited
        if k is not None and enabled and 0 <= k < len(self.seams):
            # The piece being edited: from the point out to its stretch of the rim.
            a = self.seams[k]
            span = (self.seams[(k + 1) % len(self.seams)] - a) % (2.0 * math.pi)
            b = a + (span if span > 0.0 else 2.0 * math.pi)
            arc = [self._to_screen(*self.rim_at(float(t))) for t in np.linspace(a, b, 24)]
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(EDITED_FILL)))
            painter.drawPolygon(QPolygonF([point, *arc]))
            painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor("#5a4a3a" if enabled else "#c4c4c4"), 1.0))
        for phi in self.seams:
            rim = self._to_screen(*self.rim_at(phi))
            painter.drawLine(point, rim)
        painter.setPen(QPen(QColor("#9aa3ad"), 1.0, Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(centre.x() - 6, centre.y()), QPointF(centre.x() + 6, centre.y()))
        painter.drawLine(QPointF(centre.x(), centre.y() - 6), QPointF(centre.x(), centre.y() + 6))
        painter.setPen(QPen(QColor("#6b7785")))
        painter.drawText(QPointF(centre.x() - 14, centre.y() - radius - 5), "up ↑")
        painter.drawText(QPointF(centre.x() + radius + 5, centre.y() + 4), "across →")
        if self.cap is not None and len(self.cap) >= 3:
            # The cap the panels meet round, seen from above.
            ring = [self._to_screen(self.across + a, self.up + u) for a, u in self.cap.tolist()]
            painter.setPen(QPen(QColor("#8a5a2b" if enabled else "#c4c4c4"), 1.6))
            painter.setBrush(QBrush(QColor(233, 220, 197, 200)))
            painter.drawPolygon(QPolygonF(ring))
            painter.setBrush(Qt.BrushStyle.NoBrush)
        colour = QColor("#d6008f" if enabled else "#c4c4c4")
        painter.setPen(QPen(colour, 2.0))
        painter.setBrush(QBrush(colour))
        painter.drawEllipse(point, 5.0, 5.0)

    def _pick(self, event: QMouseEvent) -> None:
        if not self.isEnabled():
            return
        self.across, self.up = self._from_screen(event.position())
        self.update()
        self.moved.emit(self.across, self.up)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt API)
        self._pick(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt API)
        if event.buttons():
            self._pick(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt API)
        if self.isEnabled():
            self.across = self.up = 0.0
            self.update()
            self.moved.emit(0.0, 0.0)


class PiecePreview(QWidget):
    """Draws the cut pieces of a shape side by side (finished line solid, cut line dashed).

    A piece whose 1:1 page is wider than the print roll however it is turned
    (``oversize``) is filled in the warning colour and labelled so. With ``on_roll`` the
    pieces are drawn as they are printed: one after another down a strip of the print
    roll (its edges drawn, the page width across it, as the Patterns view and the 1:1
    PDF pages lay it), each turned as on its page
    (:func:`envelopelab.export.templates.roll_fit`), so how every piece lies across the
    roll can be seen. The mouse wheel zooms about the pointer, dragging pans and a double
    click fits every piece again.
    """

    #: Zoom step per wheel notch, and the zoom range (1: every piece fits).
    ZOOM_STEP = 1.25
    ZOOM_RANGE = (1.0, 200.0)

    def __init__(self) -> None:
        super().__init__()
        self.pieces: list[CutPiece] = []
        self.oversize: frozenset[str] = frozenset()
        #: Gore or panel being edited (0-based): its pieces (every tier) filled amber.
        self.edited: int | None = None
        self.on_roll = False
        self.roll_width = DEFAULT_ROLL_WIDTH
        self.zoom = 1.0
        self.pan = QPointF(0.0, 0.0)
        self._drag: QPointF | None = None
        self.setMinimumHeight(160)
        self.setToolTip(
            "Mouse wheel: zoom; drag (any button): pan; double click or Fit: all pieces"
        )
        self.fit_button = FitButton(self, self.reset_view, "Show every piece again")

    def set_pieces(
        self,
        pieces: list[CutPiece],
        oversize: frozenset[str] = frozenset(),
        roll_width: float | None = None,
    ) -> None:
        """Show these pieces (m), those labelled in ``oversize`` as larger than the roll
        ``roll_width`` (m); the view fits them again when the set of pieces changes."""
        if [p.label for p in pieces] != [p.label for p in self.pieces]:
            self.reset_view()
        self.pieces = pieces
        self.oversize = oversize
        if roll_width is not None:
            self.roll_width = roll_width
        self.update()

    def set_on_roll(self, on: bool) -> None:
        """Draw the pieces side by side (False) or as printed on the roll (True)."""
        self.on_roll = on
        self.reset_view()

    def drawn(self) -> tuple[list[tuple[CutPiece, list[np.ndarray]]], float, float]:
        """Every piece with its outlines as drawn (finished, cut, rim or empty; m, in the
        drawing's frame) and the drawing's width and height, m."""
        out: list[tuple[CutPiece, list[np.ndarray]]] = []
        if not self.on_roll:
            offsets, width, height = self.layout_offsets()
            for piece, off in zip(self.pieces, offsets, strict=True):
                rim = piece.rim if piece.rim is not None else np.zeros((0, 2))
                out.append((piece, [piece.finished + off, piece.cut + off, rim + off]))
            return out, width, height
        # On the roll, as the 1:1 PDF pages and the Patterns view lay it: each page's width
        # across the roll (x in [0, roll width]), the pages one after the other down it.
        fits = [roll_fit(piece.cut, self.roll_width) for piece in self.pieces]
        total = sum(f.along for f in fits)
        top = total
        for piece, fit in zip(self.pieces, fits, strict=True):
            rim = piece.rim if piece.rim is not None else np.zeros((0, 2))
            turned = [turn_points(a, fit.angle) for a in (piece.finished, piece.cut, rim)]
            lo, hi = turned[1].min(axis=0), turned[1].max(axis=0)
            shift = np.array([MARGIN - lo[0], top - MARGIN - hi[1]])
            out.append((piece, [a + shift for a in turned]))
            top -= fit.along
        widest = max((f.across for f in fits), default=0.0)
        return out, max(self.roll_width, widest), total

    def reset_view(self) -> None:
        """Fit every piece in the widget."""
        self.zoom = 1.0
        self.pan = QPointF(0.0, 0.0)
        self.update()

    def zoom_at(self, factor: float, at: QPointF) -> None:
        """Zoom by ``factor`` keeping the drawing point under ``at`` (widget px) still."""
        old = self.zoom
        lo, hi = self.ZOOM_RANGE
        self.zoom = min(max(old * factor, lo), hi)
        k = self.zoom / old
        # Screen point = origin + pan + world * scale: keep ``at`` on the same world point.
        origin = QPointF(self._margin, -self._margin)
        rel = at - origin - QPointF(0.0, float(self.height())) - self.pan
        self.pan = at - origin - QPointF(0.0, float(self.height())) - rel * k
        self.update()

    _margin = 8.0

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802 (Qt API)
        notches = event.angleDelta().y() / 120.0
        if notches:
            self.zoom_at(self.ZOOM_STEP**notches, event.position())
        event.accept()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt API)
        if event.button() in (
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.MiddleButton,
            Qt.MouseButton.RightButton,
        ):
            self._drag = event.position()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt API)
        if self._drag is not None:
            self.pan += event.position() - self._drag
            self._drag = event.position()
            self.update()

    def mouseReleaseEvent(self, _event: QMouseEvent) -> None:  # noqa: N802 (Qt API)
        self._drag = None

    def mouseDoubleClickEvent(self, _event: QMouseEvent) -> None:  # noqa: N802 (Qt API)
        self.reset_view()

    def layout_offsets(self) -> tuple[list[np.ndarray], float, float]:
        """Where each piece goes, m: offsets, and the width and height of the layout.

        The pieces are laid out in rows, in order, with the number per row that draws them
        largest in the widget's shape (one row for a few pieces, a grid for many).
        """
        sizes = [p.cut.max(axis=0) - p.cut.min(axis=0) for p in self.pieces]
        if not sizes:
            return [], 0.0, 0.0
        aspect = max(self.width() - 2 * self._margin, 1.0) / max(
            self.height() - 2 * self._margin, 1.0
        )
        best: tuple[float, int] | None = None
        for cols in range(1, len(sizes) + 1):
            width, height = self._grid_extent(sizes, cols)
            fit = min(aspect / max(width, 1e-9), 1.0 / max(height, 1e-9))
            if best is None or fit > best[0]:
                best = (fit, cols)
        assert best is not None
        cols = best[1]
        offsets: list[np.ndarray] = []
        _, total_height = self._grid_extent(sizes, cols)
        y_top = total_height
        for start in range(0, len(sizes), cols):
            row = range(start, min(start + cols, len(sizes)))
            row_height = max(float(sizes[i][1]) for i in row)
            x = 0.0
            for i in row:
                lo = self.pieces[i].cut.min(axis=0)
                offsets.append(np.array([x - lo[0], y_top - row_height - lo[1]]))
                x += float(sizes[i][0]) * (1.0 + self.GAP)
            y_top -= row_height * (1.0 + self.GAP)
        width, height = self._grid_extent(sizes, cols)
        return offsets, width, height

    #: Gap between pieces, as a fraction of the piece's width (or the row's height).
    GAP = 0.15

    def _grid_extent(self, sizes: list[np.ndarray], cols: int) -> tuple[float, float]:
        width = height = 0.0
        for start in range(0, len(sizes), cols):
            row = sizes[start : start + cols]
            width = max(width, sum(float(s[0]) * (1.0 + self.GAP) for s in row))
            height += max(float(s[1]) for s in row) * (1.0 + self.GAP)
        return width, height

    def paintEvent(self, _event: object) -> None:  # noqa: N802 (Qt API)
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("white"))
        if not self.pieces:
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No cut pieces")
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        drawn, width, height = self.drawn()
        margin = self._margin
        scale = self.zoom * min(
            (self.width() - 2 * margin) / max(width, 1e-9),
            (self.height() - 2 * margin) / max(height, 1e-9),
        )
        px, py = self.pan.x(), self.pan.y()

        def polygon(points: np.ndarray, offset: np.ndarray | None = None) -> QPolygonF:
            p = (points if offset is None else points + offset) * scale
            return QPolygonF(
                [QPointF(margin + px + x, self.height() - margin + py - y) for x, y in p.tolist()]
            )

        if self.on_roll:
            # The roll: a strip of its width, its edges in blue, labelled.
            roll = self.roll_width
            strip = np.array([[0.0, 0.0], [roll, 0.0], [roll, height], [0.0, height]])
            painter.fillPath(_path(polygon(strip)), QBrush(QColor("#f4f7fb")))
            painter.setPen(QPen(QColor("#1565c0"), 2.0))
            for x in (0.0, roll):
                painter.drawPolyline(polygon(np.array([[x, 0.0], [x, height]])))
            top = polygon(np.array([[0.0, height]])).at(0)
            painter.drawText(
                QPointF(top.x() + 4.0, top.y() + 14.0),
                f"Print roll {roll * 1000:.0f} mm wide (edges in blue), running down",
            )

        for piece, (finished, cut, rim) in drawn:
            path = _path(polygon(finished))
            big = piece.label in self.oversize
            edited = self.edited is not None and piece.role != "tip" and piece.index == self.edited
            fill = OVERSIZE_FILL if big else EDITED_FILL if edited else "#e8eef7"
            painter.fillPath(path, QBrush(QColor(fill)))
            edge = QColor(EDITED_EDGE if edited else "#1f3b73")
            painter.setPen(QPen(edge, 2.5 if edited else 1.5))
            painter.drawPolygon(polygon(finished))
            pen = QPen(QColor("#555555"), 1.0)
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawPolygon(polygon(cut))
            if len(rim):
                painter.setPen(QPen(QColor(FAIL_COLOR), 2.0))
                painter.drawPolyline(polygon(rim))
            # The piece's short name under it (the part after the shape name).
            label = piece.label.rsplit("-", 1)[-1]
            if big:
                label += " ▲ larger than roll"
            box = polygon(cut).boundingRect()
            painter.setPen(QPen(QColor(WARN_COLOR if big else "#333333")))
            painter.drawText(
                QPointF(box.center().x() - 4.0 * len(label), box.bottom() - 4.0)
                if box.height() > 30.0
                else box.bottomLeft(),
                label,
            )


def _path(poly: QPolygonF) -> QPainterPath:
    path = QPainterPath()
    path.addPolygon(poly)
    path.closeSubpath()
    return path


class ShapesPanel(QWidget):
    """See module docstring."""

    #: The user wants to drag shape ``name`` in the 3D view (the main window shows it).
    dragRequested = Signal(str)  # noqa: N815 (Qt naming)
    #: The Export build pack… button: the main window opens its export dialog.
    exportRequested = Signal()  # noqa: N815 (Qt naming)

    def __init__(self, controller: WorkspaceController, enable_3d: bool = False) -> None:
        super().__init__()
        self.controller = controller
        self.selected: str | None = None
        #: Gore or panel of the selected shape being edited in the Panel layout (0-based;
        #: None: none), highlighted in every view of it.
        self.edited_piece: int | None = None
        self.mesh_mm = DEFAULT_MESH_MM
        self._form_key: tuple[str, str, int] | None = None
        self._placement_key: tuple[str, tuple[str, ...]] | None = None
        self._placement_shown: tuple[int, str | None] | None = None
        #: Each placed shape's drawing: (placed design, gore map, 3D points, triangles,
        #: footprint on the map, base point), rebuilt when the shape is placed again.
        self._drawn: dict[str, tuple[Any, ...]] = {}
        #: The lines of each placed shape the hints draw (its seams, rim, base point).
        self._hint_lines: dict[str, tuple[Any, ...]] = {}
        self._placement_cache: tuple[Any, Any] = (None, None)
        self.fields: dict[tuple[str, ...], QSpinBox | QDoubleSpinBox] = {}

        # -- shape list ------------------------------------------------------------------
        self.add_button = QToolButton()
        self.add_button.setText("Add shape")
        self.add_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.add_button)
        for kind in ("dome", "tube", "revolved"):
            menu.addAction(KIND_LABELS[kind], self._adder(kind))
        menu.addAction("Import mesh (OBJ/STL/PLY)…", self._import_mesh_dialog)
        menu.addSeparator()
        # An appliqué sewn on the envelope (ADR-0056), listed and placed like a shape.
        menu.addAction("Overlay (appliqué)", self.add_overlay)
        self.add_button.setMenu(menu)
        self.overlay_editor = OverlayEditor()
        self.overlay_editor.changed.connect(self._overlay_changed)
        self.overlay_editor.colourRequested.connect(self._overlay_colour)
        self.overlay_editor.exportRequested.connect(lambda: self.export_overlay_pattern())
        #: Each overlay's layout on the envelope: name -> (spec, surface, layout, error).
        self._overlay_layouts: dict[str, tuple[Any, Any, Any, str]] = {}
        self.duplicate_button = QPushButton("Duplicate")
        self.duplicate_button.clicked.connect(self.duplicate_selected)
        self.remove_button = QPushButton("Remove")
        self.remove_button.clicked.connect(self.remove_selected)
        self.list = QListWidget()
        self.list.setObjectName("shapeList")
        self.list.currentItemChanged.connect(self._current_changed)
        self.busy_label = QLabel()
        self.busy_label.setWordWrap(True)

        # -- parameters ------------------------------------------------------------------
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setObjectName("shapeStatus")
        self.form_box = QWidget()
        self.form = QFormLayout(self.form_box)
        self.holes_box = QWidget()
        self.holes_form = QFormLayout(self.holes_box)
        for form in (self.form, self.holes_form):
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.profile_table = QTableWidget(0, 2)
        self.profile_table.setHorizontalHeaderLabels(["Radius ρ (m)", "Height ζ (m)"])
        self.profile_table.setMinimumHeight(120)
        self.profile_table.itemChanged.connect(self._profile_edited)
        self.profile_box = QWidget()
        profile_layout = QVBoxLayout(self.profile_box)
        profile_layout.addWidget(QLabel("Profile points, base first, axis last (m)"))
        profile_layout.addWidget(self.profile_table, 1)
        row_buttons = QHBoxLayout()
        add_row = QPushButton("Add point")
        add_row.clicked.connect(self._add_profile_point)
        del_row = QPushButton("Remove point")
        del_row.clicked.connect(self._remove_profile_point)
        row_buttons.addWidget(add_row)
        row_buttons.addWidget(del_row)
        profile_layout.addLayout(row_buttons)

        # -- panel layout ----------------------------------------------------------------
        self.layout_box = QWidget()
        self.layout_box.setObjectName("shapePanelLayout")
        self.seam_turn = QDoubleSpinBox()
        self.seam_turn.setObjectName("shapeSeamTurn")
        self.seam_turn.setRange(-180.0, 180.0)
        self.seam_turn.setDecimals(1)
        self.seam_turn.setSuffix(" °")
        self.seam_turn.setKeyboardTracking(False)
        self.seam_turn.setToolTip(
            "Turn every seam round the shape's axis: the first gore or panel is centred this "
            "far round from the direction up the tape (0°), towards the previous gore (90°; "
            "−90° towards the next gore)"
        )
        self.seam_turn.valueChanged.connect(
            lambda v: self.set_value_live(("seam_offset_deg",), round(float(v), 1))
        )
        self.widths_table = QTableWidget(0, 2)
        self.widths_table.setObjectName("shapePanelWidths")
        self.widths_table.setHorizontalHeaderLabels(["Relative width", "Spans round the axis"])
        self.widths_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.widths_table.setMinimumHeight(140)
        self.widths_table.setToolTip(
            "Relative width of every gore or panel, piece 1 first: 2 is twice as wide as 1"
        )
        self.widths_table.itemChanged.connect(self._width_edited)
        self.widths_table.currentCellChanged.connect(
            lambda row, _c, _pr, _pc: self.set_edited_piece(row if row >= 0 else None)
        )
        equal = QPushButton("Equal widths")
        equal.setObjectName("shapeEqualWidths")
        equal.clicked.connect(lambda: self.set_value(("panel_widths",), []))
        self.split_piece_button = QPushButton("Split panel in two")
        self.split_piece_button.setObjectName("shapeSplitPiece")
        self.split_piece_button.setToolTip(
            "Split the gore or panel selected above into two of half its width (one more "
            "gore or panel; every other seam stays where it is). Undo merges them again."
        )
        self.split_piece_button.clicked.connect(lambda: self.split_piece(self.edited_piece))
        self.splits_table = QTableWidget(0, 1)
        self.splits_table.setObjectName("shapeSplits")
        self.splits_table.setHorizontalHeaderLabels(["Split at (% of the profile)"])
        self.splits_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.splits_table.setMinimumHeight(100)
        self.splits_table.setToolTip(
            "Where every gore or panel is cut across: per cent of the profile's length from "
            "the base circle (0) to the tip (100). Tiers are labelled A (at the rim), B, ..."
        )
        self.splits_table.itemChanged.connect(self._split_edited)
        self.add_split_button = QPushButton("Add split")
        self.add_split_button.setObjectName("shapeAddSplit")
        self.add_split_button.clicked.connect(self.add_split)
        self.remove_split_button = QPushButton("Remove split")
        self.remove_split_button.clicked.connect(self.remove_split)
        self.layout_note = QLabel()
        self.layout_note.setObjectName("shapeLayoutNote")
        self.layout_note.setWordWrap(True)
        layout_form = QFormLayout(self.layout_box)
        layout_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self._crown_filling = False
        layout_form.addRow("Seam turn", self.seam_turn)
        widths = QVBoxLayout()
        widths.addWidget(self.widths_table)
        width_buttons = QHBoxLayout()
        width_buttons.addWidget(self.split_piece_button)
        width_buttons.addWidget(equal)
        widths.addLayout(width_buttons)
        layout_form.addRow("Panel widths", widths)
        splits = QVBoxLayout()
        splits.addWidget(self.splits_table)
        split_buttons = QHBoxLayout()
        split_buttons.addWidget(self.add_split_button)
        split_buttons.addWidget(self.remove_split_button)
        splits.addLayout(split_buttons)
        layout_form.addRow("Horizontal splits", splits)
        layout_form.addRow(self.layout_note)
        layout_form.addRow(self._crown_box())

        # -- results ---------------------------------------------------------------------
        self.checks = QTreeWidget()
        self.checks.setHeaderLabels(["Check", "Value", "Limit", "Result"])
        self.checks.setMinimumHeight(110)
        self.pieces = QTreeWidget()
        self.pieces.setHeaderLabels(
            [
                "Piece",
                "Cut",
                "Finished W × H (m)",
                "Flat area (m²)",
                "3D area (m²)",
                "Page on print roll",
            ]
        )
        self.attachment = QTreeWidget()
        self.attachment.setHeaderLabels(["Envelope panel", "Attachment line (m)"])
        self.preview = PiecePreview()

        # -- simulation and export -------------------------------------------------------
        self.mesh_spin = QDoubleSpinBox()
        self.mesh_spin.setObjectName("shapeMeshSize")
        self.mesh_spin.setRange(10.0, 500.0)
        self.mesh_spin.setDecimals(0)
        self.mesh_spin.setSuffix(" mm")
        self.mesh_spin.setValue(self.mesh_mm)
        self.mesh_spin.valueChanged.connect(lambda v: setattr(self, "mesh_mm", float(v)))
        self.simulate_button = QPushButton("Simulate shape (preview solver)")
        self.simulate_button.clicked.connect(self.simulate_selected)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(controller.shape_simulator.cancel)
        self.sim_status = QLabel()
        self.sim_status.setWordWrap(True)
        self.sim_tree = QTreeWidget()
        self.sim_tree.setHeaderLabels(["Result", "Value"])
        self.sim_tree.setMinimumHeight(120)
        self.sim_tree.setColumnWidth(0, 260)
        self.export_pack_button = QPushButton("Export build pack…")
        self.export_pack_button.clicked.connect(self._export_pack_dialog)
        self.drag_button = QPushButton("Drag in 3D view…")
        self.drag_button.setToolTip(
            "Open the 3D view with dragging on: press on the shape, drag it over the "
            "envelope and release to place it"
        )
        self.drag_button.clicked.connect(self._request_drag)
        self.export_blender_button = QPushButton("Export to Blender (OBJ)…")
        self.export_blender_button.clicked.connect(self._export_blender_dialog)
        # -- shape groups (objects made of several shapes) ------------------------------
        self.move_group_button = QPushButton("Move group…")
        self.move_group_button.setObjectName("shapeMoveGroup")
        self.move_group_button.setToolTip(
            "Move every shape of the selected shape's group round the envelope and along "
            "the tape, feed holes with them (one undo step)"
        )
        self.move_group_button.clicked.connect(self._move_group_dialog)
        self.mirror_group_button = QPushButton("Mirror group…")
        self.mirror_group_button.setObjectName("shapeMirrorGroup")
        self.mirror_group_button.setToolTip(
            "Add a linked mirror twin of every shape of the group across a symmetry axis "
            "(the other side of a face); shapes on the axis are left as they are"
        )
        self.mirror_group_button.clicked.connect(self._mirror_group_dialog)
        self.export_group_button = QPushButton("Export group to Blender…")
        self.export_group_button.clicked.connect(self._export_group_dialog)
        # -- symmetry: named axes and linked mirror twins ---------------------------------
        self.mirror_button = QPushButton("Mirror…")
        self.mirror_button.setObjectName("shapeMirror")
        self.mirror_button.setToolTip(
            "Add the mirror image of the selected shape across a symmetry axis, as a linked "
            "twin: edit or drag either side and the other follows"
        )
        self.mirror_button.clicked.connect(self._mirror_dialog)
        self.axes_list = QListWidget()
        self.axes_list.setObjectName("symmetryAxes")
        self.axes_list.setMaximumHeight(90)
        self.axes_list.setToolTip(
            "Symmetry axes: meridian planes of the envelope that shapes are mirrored across "
            "(drawn on the envelope in the 3D view)"
        )
        self.axes_list.itemDoubleClicked.connect(lambda _i: self._edit_axis_dialog())
        self.add_axis_button = QPushButton("Add axis…")
        self.add_axis_button.setObjectName("addSymmetryAxis")
        self.add_axis_button.clicked.connect(self._add_axis_dialog)
        self.edit_axis_button = QPushButton("Edit…")
        self.edit_axis_button.clicked.connect(self._edit_axis_dialog)
        self.remove_axis_button = QPushButton("Remove")
        self.remove_axis_button.clicked.connect(self._remove_axis)
        self.mirror_label = QLabel()
        self.mirror_label.setObjectName("shapeMirrorLink")
        self.mirror_label.setWordWrap(True)
        self.unlink_button = QPushButton("Unlink")
        self.unlink_button.setObjectName("shapeUnlinkMirror")
        self.unlink_button.setToolTip(
            "Make this mirror twin an ordinary shape (it keeps its geometry and stops "
            "following the shape it mirrors)"
        )
        self.unlink_button.clicked.connect(self.unlink_selected)
        sim_box = QWidget()
        sim_layout = QVBoxLayout(sim_box)
        sim_row = QHBoxLayout()
        sim_row.addWidget(QLabel("Mesh size"))
        sim_row.addWidget(self.mesh_spin)
        sim_row.addWidget(self.simulate_button)
        sim_row.addWidget(self.cancel_button)
        sim_row.addStretch(1)
        sim_layout.addLayout(sim_row)
        sim_layout.addWidget(self.sim_status)
        sim_layout.addWidget(self.sim_tree, 1)

        # Column 1: the shapes, and what applies to all of them.
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(self.list, 1)
        left_layout.addWidget(self.busy_label)
        for button in (
            self.add_button,
            self.duplicate_button,
            self.mirror_button,
            self.remove_button,
            self.move_group_button,
            self.mirror_group_button,
            self.export_group_button,
            self.export_pack_button,
            self.export_blender_button,
        ):
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            left_layout.addWidget(button)
        axes_title = QLabel("Symmetry axes")
        axes_title.setProperty("role", "muted")
        left_layout.addWidget(axes_title)
        left_layout.addWidget(self.axes_list)
        axis_buttons = QHBoxLayout()
        for button in (self.add_axis_button, self.edit_axis_button, self.remove_axis_button):
            axis_buttons.addWidget(button)
        left_layout.addLayout(axis_buttons)

        # Column 2: the selected shape's editor in tabs.
        self.editor_tabs = QTabWidget()
        self.editor_tabs.setObjectName("shapeEditorTabs")
        place = QWidget()
        place_layout = QVBoxLayout(place)
        place_layout.addWidget(self.form_box)
        place_layout.addWidget(self.drag_button)
        place_layout.addStretch(1)
        holes_page = QWidget()
        holes_layout = QVBoxLayout(holes_page)
        holes_layout.addWidget(self.holes_box, 1)
        for page, title in (
            (place, "Placement && size"),
            (self.profile_box, "Profile"),
            (holes_page, "Feed holes && cap"),
            (self.layout_box, "Panel layout"),
            (sim_box, "Simulation"),
        ):
            self.editor_tabs.addTab(_scrolled(page), title)
        middle = QWidget()
        middle_layout = QVBoxLayout(middle)
        middle_layout.setContentsMargins(0, 0, 0, 0)
        middle_layout.addWidget(self.status)
        mirror_row = QHBoxLayout()
        mirror_row.addWidget(self.mirror_label, 1)
        mirror_row.addWidget(self.unlink_button)
        middle_layout.addLayout(mirror_row)
        # The shape editor, or the overlay editor when an overlay is selected.
        self.editor_stack = QStackedWidget()
        self.editor_stack.addWidget(self.editor_tabs)
        self.editor_stack.addWidget(_scrolled(self.overlay_editor))
        middle_layout.addWidget(self.editor_stack, 1)

        # Column 3: what is derived from it, in tabs.
        self.result_tabs = QTabWidget()
        self.result_tabs.setObjectName("shapeResultTabs")
        pieces_split = QSplitter(Qt.Orientation.Vertical)
        pieces_split.setObjectName("shapePiecesSplitter")
        drawing = QWidget()
        drawing_layout = QVBoxLayout(drawing)
        drawing_layout.setContentsMargins(0, 0, 0, 0)
        drawing_layout.addWidget(
            QLabel(
                "Finished line solid, cut line dashed, rim (sewn to the envelope) red. "
                "Wheel: zoom, drag: pan, double click: fit."
            )
        )
        self.on_roll_check = QCheckBox("Show as printed on the roll")
        self.on_roll_check.setObjectName("shapeOnRoll")
        self.on_roll_check.setToolTip(
            "Lay the pieces along a strip of the print roll (Preferences ▸ Print roll "
            "width), each turned as on its 1:1 page: the page width runs across the roll"
        )
        self.on_roll_check.toggled.connect(self.preview.set_on_roll)
        drawing_layout.addWidget(self.on_roll_check)
        drawing_layout.addWidget(self.preview, 1)
        pieces_split.addWidget(drawing)
        pieces_split.addWidget(self.pieces)
        pieces_split.setStretchFactor(0, 3)
        pieces_split.setStretchFactor(1, 1)
        self.result_tabs.addTab(pieces_split, "Cut pieces")
        # Where the shapes sit on the balloon: the 3D sketch over the gore map.
        # Where the shapes sit on the balloon: the first tab, shown by default.
        self.placement = PlacementView(gpu=enable_3d)
        self.placement.map.shapeClicked.connect(self.select)
        self.placement.shapeMoved.connect(self.move_object)
        self.placement.nudged.connect(self.nudge)
        self._axis: _AxisSession | None = None
        self.placement.axisPointed.connect(self._axis_pointed)
        self.placement.axisTyped.connect(self._axis_typed)
        self.placement.axisTargetChosen.connect(self._axis_target)
        self.placement.axisAccepted.connect(self.accept_axis)
        self.placement.axisCancelled.connect(self.cancel_axis)
        self.placement.axisGrabbed.connect(self._axis_grabbed)
        self.placement.axisReleased.connect(self._axis_released)
        self.placement.axis_name.textEdited.connect(lambda _t: self._update_axis_preview())
        self.result_tabs.insertTab(0, self.placement, "On the balloon")
        self.result_tabs.setCurrentIndex(0)
        self._results_stale = False
        self.result_tabs.currentChanged.connect(self._result_tab_shown)
        # The envelope panels the shape is sewn on (its marking sheets); the Patterns
        # view shows only the base envelope.
        self.markings = MarkingView()
        self.markings.setObjectName("shapeMarkings")
        self.marking_notes = QLabel()
        self.marking_notes.setObjectName("shapeMarkingNotes")
        self.marking_notes.setWordWrap(True)
        self.marking_notes.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        envelope_panels = QWidget()
        envelope_layout = QVBoxLayout(envelope_panels)
        envelope_layout.setContentsMargins(0, 0, 0, 0)
        caption = QLabel(
            "Envelope panels this shape is sewn on, as on the build pack's marking "
            "sheets: footprint line (ticks on the shape's side), numbered match marks, "
            "feed holes cut (dashed) and finished (solid). Wheel: zoom; double click: marked "
            "area / whole panel."
        )
        caption.setWordWrap(True)
        envelope_layout.addWidget(caption)
        envelope_layout.addWidget(self.markings, 1)
        envelope_layout.addWidget(self.marking_notes)
        self.result_tabs.addTab(envelope_panels, "Envelope panels")
        self.result_tabs.addTab(self.checks, "Checks")
        self.result_tabs.addTab(self.attachment, "Attachment")

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setObjectName("shapesSplitter")
        for i, widget in enumerate((left, middle, self.result_tabs)):
            self.splitter.addWidget(widget)
            self.splitter.setCollapsible(i, False)
        self.splitter.setStretchFactor(2, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.splitter)

        simulator = controller.shape_simulator
        simulator.progress.connect(lambda text, _f: self.sim_status.setText(text))
        simulator.failed.connect(self._simulation_failed)
        simulator.finished.connect(lambda _n: self._show_selected())
        simulator.started.connect(lambda _n: self._update_buttons())
        simulator.idle.connect(self._update_buttons)
        controller.shapes.busyChanged.connect(self._busy_changed)
        controller.selectionChanged.connect(self._selection)
        self.refresher = Refresher(
            self,
            self.refresh,
            lambda: controller.revision,
            (controller.stateChanged, controller.sessionChanged, controller.shapesChanged),
            defer_hidden=lambda: controller.defer_hidden,
        )
        self.refresh()

    # -- data ---------------------------------------------------------------------------

    def specs(self) -> list[ShapeSpec]:
        """The project's shapes."""
        session = self.controller.session
        return [] if session is None else list(session.state.shapes)

    def spec(self, name: str | None = None) -> ShapeSpec | None:
        """Shape ``name`` (default: the selected one)."""
        name = self.selected if name is None else name
        return next((s for s in self.specs() if s.name == name), None)

    def placed(self, name: str | None = None) -> PrimitiveDesign | None:
        """Placed design of shape ``name`` (None while it is computed or when it failed)."""
        name = self.selected if name is None else name
        result = None if name is None else self.controller.shapes.result(name)
        return None if result is None else result.design

    def overlays(self) -> list[Any]:
        """The project's overlays (appliqués, ADR-0056)."""
        session = self.controller.session
        return [] if session is None else list(session.state.overlays)

    def overlay(self, name: str | None = None) -> Any:
        """Overlay ``name`` (default: the selected one; None: not an overlay)."""
        name = self.selected if name is None else name
        return next((o for o in self.overlays() if o.name == name), None)

    def overlay_layout(self, name: str | None = None) -> tuple[Any, Any, str]:
        """(surface, layout, error) of overlay ``name``: its layout on the envelope
        (:func:`envelopelab.project.overlays.overlay_layout`; None when it cannot be laid,
        ``error`` says why), cached until the overlay or the envelope changes."""
        from envelopelab.project.overlays import overlay_layout

        spec = self.overlay(name)
        surface = self.controller.envelope_surface()
        if spec is None or surface is None:
            return surface, None, "no standard-gore envelope"
        hit = self._overlay_layouts.get(spec.name)
        if hit is not None and hit[0] == spec and hit[1] is surface:
            return surface, hit[2], hit[3]
        try:
            layout, error = overlay_layout(spec, surface), ""
        except ValueError as exc:
            layout, error = None, str(exc)
        self._overlay_layouts[spec.name] = (spec, surface, layout, error)
        return surface, layout, error

    def move_object(self, name: str, placement: Any) -> bool:
        """Move shape or overlay ``name`` to ``placement`` (dragged or nudged; one step)."""
        if self.overlay(name) is not None:
            values = {
                "gore": placement.gore,
                "tape_position": placement.tape_position,
                "across": placement.across,
            }
            return bool(self.controller.edit("update_overlay", name, {"placement": values}))
        return bool(self.controller.place_shape(name, placement))

    def add_overlay(self) -> str | None:
        """Add a 1 m circle overlay on gore 1, half way up the envelope; returns its name."""
        from envelopelab.project.edits import unique_name
        from envelopelab.project.overlays import default_overlay

        session = self.controller.session
        surface = self.controller.envelope_surface()
        if session is None or surface is None:
            return None
        name = unique_name(session, "overlay")
        spec = default_overlay(name, 1, 0.5 * float(surface.profile.meridian_length))
        if not self.controller.edit("add_overlay", spec):
            return None
        self.select(name)
        return name

    def _overlay_changed(self, values: dict[str, Any], live: bool) -> None:
        name = self.selected
        if name is None or self.overlay(name) is None:
            return
        if "name" in values:
            self.selected = str(values["name"])
        if live:
            self.controller.edit_live(
                f"overlay:{name}:{','.join(values)}",
                lambda: self.controller.edit("update_overlay", name, values),
            )
            return
        if not self.controller.edit("update_overlay", name, values):
            self.selected = name
            self._show_selected()

    def _show_overlay_result(self, layout: Any) -> None:
        """The selected overlay's pattern in the result tabs: its cut piece (Cut pieces,
        with how its 1:1 page lies on the print roll), its checks (fit on the envelope,
        on the roll), the line marked on each panel it crosses (Envelope panels) and the
        length of that line per panel (Attachment)."""
        from envelopelab.export.overlays import overlay_checks, overlay_cut_piece, overlay_sheets

        if layout is None:
            return
        roll = self.controller.prefs.print_roll_width
        piece = overlay_cut_piece(layout)
        fit = roll_fit(piece.cut, roll)
        w, h = piece.size
        on_roll = (
            f"LARGER THAN {roll * 1000:.0f} mm ROLL"
            if fit.oversize
            else f"{fit.across * 1000:.0f} mm across, {fit.describe()}"
        )
        item = QTreeWidgetItem(
            [
                piece.label,
                str(piece.cut_count),
                f"{w:.3f} × {h:.3f}",
                f"{piece.flat_area:.4f}",
                f"{piece.surface_area:.4f}",
                on_roll,
            ]
        )
        if fit.oversize:
            item.setForeground(5, QBrush(QColor(WARN_COLOR)))
        self.pieces.addTopLevelItem(item)
        for check in overlay_checks(layout, roll):
            row = QTreeWidgetItem(
                [
                    check.name,
                    f"{check.value:.4g} {check.unit}",
                    f"{check.limit:.4g} {check.unit}",
                    "passed" if check.passed else check.severity.upper(),
                ]
            )
            row.setToolTip(0, check.message)
            row.setForeground(3, QBrush(QColor(SEVERITY_COLORS[check.severity])))
            self.checks.addTopLevelItem(row)
        for run in layout.runs:
            length = float(np.linalg.norm(np.diff(run.panel, axis=0), axis=1).sum())
            self.attachment.addTopLevelItem(
                QTreeWidgetItem([f"gore {run.gore}, row {run.row}", f"{length:.3f}"])
            )
        for tree in (self.pieces, self.checks, self.attachment):
            for column in range(tree.columnCount()):
                tree.resizeColumnToContents(column)
        self.preview.set_pieces([piece], frozenset({piece.label} if fit.oversize else ()), roll)
        surface = self.controller.envelope_surface()
        if surface is None:
            return
        sheets, _pairs = overlay_sheets(layout, surface, "envelope")
        markings = [s for s in sheets if s.kind == "marking"]
        stale = self.controller.artifact_status("patterns") == "stale"
        self.markings.set_sheets(markings, stale)
        lines = [
            f"{len(markings)} envelope panel(s) to mark: "
            + ", ".join(s.piece for s in markings)
            + "; match each numbered mark to the same number on the piece."
        ]
        if stale:
            lines.append("Patterns are STALE: regenerate them before marking (shown greyed).")
        self.marking_notes.setText("\n".join(lines))

    def export_overlay_pattern(self, out_dir: str | Path | None = None) -> list[Path]:
        """Write the selected overlay's own cutting pattern (its 1:1 template PDF and the
        DXFs of the piece and of every panel marking) into ``out_dir`` (asked for when
        None); returns the files written (empty when refused or cancelled)."""
        from PySide6.QtWidgets import QFileDialog

        from envelopelab.export.overlays import write_overlay_pattern
        from envelopelab.project.colours import PanelRef

        overlay = self.overlay()
        session = self.controller.session
        surface, layout, error = self.overlay_layout()
        if overlay is None or session is None or surface is None:
            return []
        if layout is None:
            self.controller.editRejected.emit(f"pattern not written: {error}")
            return []
        if out_dir is None:
            chosen = QFileDialog.getExistingDirectory(self, f"Export the pattern of {overlay.name}")
            if not chosen:
                return []
            out_dir = chosen
        fabric = overlay.fabric
        if not fabric:
            row = surface.rows[
                int(surface.row_index(np.array([overlay.placement.tape_position]))[0])
            ]
            from envelopelab.project.gore_design import row_zone

            zone = row_zone(session.design, session.patterns, row.label)
            fabric = session.design.zones.get(zone, zone)
        colour = session.state.colours.colour_of(PanelRef(overlay.name, "A", 1))
        files = self.controller.attempt(
            write_overlay_pattern,
            layout,
            surface,
            fabric,
            out_dir,
            self.controller.prefs.print_roll_width,
            session.design.meta.name,
            colour,
        )
        if files:
            self.controller.message.emit(
                f"Pattern of {overlay.name} written to {out_dir} ({len(files)} files)"
            )
        return list(files or [])

    def _overlay_colour(self) -> None:
        from PySide6.QtWidgets import QColorDialog

        from envelopelab.project.colours import PanelRef

        name = self.selected
        session = self.controller.session
        if name is None or session is None:
            return
        ref = PanelRef(name, "A", 1)
        current = session.state.colours.colour_of(ref) or "#ffffff"
        chosen = QColorDialog.getColor(QColor(current), self, f"Colour of {name}")
        if chosen.isValid():
            self.controller.edit("paint_panels", [ref], chosen.name())

    # -- edits --------------------------------------------------------------------------

    def select(self, name: str | None) -> None:
        """Select a shape by name."""
        if name != self.selected:
            self._forget_edited_piece()
        self.selected = name
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == name:
                self.list.setCurrentItem(item)
                break
        self._show_selected()

    def add_shape(self, kind: ShapeKind) -> str | None:
        """Add a default shape of ``kind`` (dome, tube or revolved); returns its name."""
        design = self.controller.design
        if design is None:
            return None
        name = self._free_name(KIND_LABELS[kind].split()[0])
        spec = self.controller.attempt(default_shape, kind, design, name)
        if spec is None or not self.controller.edit("add_shape", spec):
            return None
        self.select(name)
        return name

    def _adder(self, kind: ShapeKind) -> Callable[[], None]:
        def add() -> None:
            self.add_shape(kind)

        return add

    def import_mesh(
        self, path: str | Path, scale: float = 1.0, up: str | None = None
    ) -> str | None:
        """Add a mesh shape from an OBJ/STL/PLY file (m per file unit ``scale``)."""
        from envelopelab.io.blender import read_shape_mesh

        design = self.controller.design
        if design is None:
            return None
        mesh = self.controller.attempt(read_shape_mesh, path, scale, up)
        if mesh is None:
            return None
        base = default_shape("dome", design, "x")
        name = self._free_name(Path(path).stem[:30] or "Mesh")
        spec = self.controller.attempt(
            mesh_shape,
            name,
            mesh.vertices,
            mesh.triangles,
            ShapePlacement.model_validate(base.placement.model_dump()),
            Path(path).name,
        )
        if spec is None or not self.controller.edit("add_shape", spec):
            return None
        self.select(name)
        return name

    def duplicate_selected(self) -> str | None:
        """Copy the selected shape (or overlay) one gore further round."""
        if self.selected is None:
            return None
        if self.overlay() is not None:
            copy = self.controller.edit("duplicate_overlay", self.selected)
            if copy:
                self.select(copy)
            return copy  # type: ignore[no-any-return]
        new = self.controller.edit("duplicate_shape", self.selected)
        if new:
            self.select(new)
        return new  # type: ignore[no-any-return]

    def remove_selected(self) -> None:
        """Remove the selected shape (or overlay)."""
        edit = "remove_overlay" if self.overlay() is not None else "remove_shape"
        if self.selected is not None and self.controller.edit(edit, self.selected):
            self.selected = None
            self.refresh()

    def set_value_live(self, path: tuple[str, ...], value: Any) -> None:
        """Change one value of the selected shape in real time (a spin box being spun or
        held: :meth:`WorkspaceController.edit_live`; the newest value wins, one undo
        step)."""
        name = self.selected
        if name is None or self.overlay(name) is not None:
            return
        self.controller.edit_live(
            f"shape:{name}:{'.'.join(path)}", lambda: self._set_value_of(name, path, value)
        )

    def _set_value_of(self, name: str, path: tuple[str, ...], value: Any) -> None:
        if self.selected == name:
            self.set_value(path, value)

    def set_value(self, path: tuple[str, ...], value: Any) -> bool:
        """Change one value of the selected shape (undoable)."""
        if self.selected is None or self.overlay() is not None:
            return False
        spec = self.spec()
        if spec is not None and _get(spec.model_dump(mode="json"), path) == value:
            return False
        old = self.selected
        if path == ("name",):
            # Selected under its new name before the edit refreshes the panel.
            self.selected = str(value)
        values = _values(path, value)
        if spec is not None and path in (("gores",), ("panels",)):
            # Keep the widths given and make the new pieces as wide as the last one.
            count = int(value)
            for key in ("panel_widths", "crown_panel_widths"):
                widths = list(getattr(spec, key))[:count]
                if widths:
                    values[key] = widths + [widths[-1]] * (count - len(widths))
        ok = bool(self.controller.edit("update_shape", old, values))
        if not ok:
            self.selected = old
            self.refresh()
        return ok

    def _free_name(self, base: str) -> str:
        names = {s.name for s in self.specs()}
        if base not in names:
            return base
        k = 2
        while f"{base} {k}" in names:
            k += 1
        return f"{base} {k}"

    # -- simulation and export ----------------------------------------------------------

    def simulate_selected(self) -> bool:
        """Solve the selected shape's sub-model with the preview solver (worker thread)."""
        session, name = self.controller.session, self.selected
        spec, placed = self.spec(), self.placed()
        if session is None or name is None or spec is None:
            return False
        if placed is None:
            self.sim_status.setText("The shape is not placed yet (or cannot be placed).")
            return False
        request = self.controller.shape_solve_request(name, self.mesh_mm)
        if request is None:
            return False
        # A chosen solve goes first: an automatic one that is running stops for it.
        started = self.controller.shape_simulator.start(request, replace=True)
        self._update_buttons()
        return started

    def export_pack(
        self,
        out_dir: str | Path,
        extras: PackExtras | None = None,
        roll_width: float = DEFAULT_ROLL_WIDTH,
    ) -> Path | None:
        """Write the build pack of the envelope and every placed shape; returns the index.

        Refused (None) while a shape is being placed or cannot be placed, so a pack never
        silently leaves a shape out. ``extras`` chooses the documents written with the
        sheets (:class:`envelopelab.export.build_pack.PackExtras`; default none);
        ``roll_width`` is the fabric roll width, m.
        """
        from envelopelab.export.build_pack import export_build_pack

        session = self.controller.session
        if session is None or session.design.gores is None:
            return None
        placed, fabrics = [], {}
        for spec in session.state.shapes:
            design = self.placed(spec.name)
            if design is None:
                self.controller.editRejected.emit(
                    f"build pack not written: shape {spec.name} is not placed"
                )
                return None
            placed.append(design)
            fabrics[spec.name] = shape_fabrics(spec, session.design, session.patterns, design)[1]
        groups = {s.name: s.group for s in session.state.shapes if s.group}
        index = self.controller.attempt(
            export_build_pack,
            session.design,
            placed,
            out_dir,
            session.patterns,
            fabrics,
            roll_width=roll_width,
            extras=extras,
            groups=groups,
            colours=session.state.colours,
            overlays=session.state.overlays,
        )
        if index is not None:
            self.controller.message.emit(f"Build pack written to {out_dir}")
        return index

    def export_blender(self, path: str | Path, group: str | None = None) -> Path | None:
        """Write the envelope, the placed shapes and their current simulations as OBJ
        (only the shapes of ``group`` when given)."""
        from envelopelab.features.scene import display_object, export_scene
        from envelopelab.project.shapes import envelope_surface

        session = self.controller.session
        if session is None or session.design.gores is None:
            return None
        service = self.controller.shapes
        names = [s.name for s in session.state.shapes if group is None or s.group == group]
        designs = [d for d in (self.placed(n) for n in names) if d]
        solved = [
            display_object(name, sim.display, sim.record.converged)
            for name, sim in service.simulations.items()
            if name in names and service.simulation_status(name) == "current"
        ]
        surface = self.controller.attempt(envelope_surface, session.design, session.patterns)
        if surface is None:
            return None
        out = self.controller.attempt(export_scene, path, surface, designs, (), "Y", solved)
        if out is not None:
            self.controller.message.emit(f"Blender scene written to {path}")
        return out

    def _import_mesh_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import shape mesh", "", "Meshes (*.obj *.stl *.ply)"
        )
        if path:
            self.import_mesh(path)

    def _export_pack_dialog(self) -> None:
        self.exportRequested.emit()

    def _export_blender_dialog(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export to Blender", "", "OBJ (*.obj)")
        if path:
            self.export_blender(path)

    def _simulation_failed(self, message: str) -> None:
        self.sim_status.setText(message)
        self.sim_status.setStyleSheet(f"color: {FAIL_COLOR};")
        self.controller.message.emit(message)
        self._update_buttons()
        if self.controller.defer_hidden and self.isVisible():
            QMessageBox.warning(self, "Shape simulation", message)

    def _request_drag(self) -> None:
        if self.selected is not None and self.overlay() is None:
            self.dragRequested.emit(self.selected)

    def _selection(self, target: str) -> None:
        if target.startswith("shape:"):
            self.select(target.removeprefix("shape:"))

    def _busy_changed(self, busy: bool) -> None:
        self.busy_label.setText("Placing shapes…" if busy else "")

    # -- display ------------------------------------------------------------------------

    def refresh(self) -> None:
        """Rebuild the list and the selected shape's view."""
        specs = self.specs()
        overlays = self.overlays()
        names = [s.name for s in specs] + [o.name for o in overlays]
        if self.selected not in names:
            self.selected = names[0] if names else None
        self.list.blockSignals(True)
        self.list.clear()
        twinned = {s.mirror.of for s in specs if s.mirror is not None}
        for spec in specs:
            prefix = f"{spec.group} ▸ " if spec.group else ""
            suffix = (
                f"  ⇄ mirror of {spec.mirror.of}"
                if spec.mirror is not None
                else "  ⇄"
                if spec.name in twinned
                else ""
            )
            item = QListWidgetItem(f"{prefix}{spec.name}  ({KIND_LABELS[spec.kind]}){suffix}")
            item.setData(Qt.ItemDataRole.UserRole, spec.name)
            colour = self._state_colour(spec.name)
            if colour:
                item.setForeground(QBrush(QColor(colour)))
            self.list.addItem(item)
            if spec.name == self.selected:
                self.list.setCurrentItem(item)
        for overlay in overlays:
            item = QListWidgetItem(f"{overlay.name}  (overlay)")
            item.setData(Qt.ItemDataRole.UserRole, overlay.name)
            if self.overlay_layout(overlay.name)[1] is None:
                item.setForeground(QBrush(QColor(FAIL_COLOR)))
            self.list.addItem(item)
            if overlay.name == self.selected:
                self.list.setCurrentItem(item)
        self.list.blockSignals(False)
        self._fill_axes()
        self._show_selected()

    def _state_colour(self, name: str) -> str | None:
        result = self.controller.shapes.result(name)
        if result is None:
            return None
        checks = self.controller.shape_checks(name)
        if result.design is None or any(c.severity == "error" for c in checks):
            return FAIL_COLOR
        if not all(c.passed for c in checks):
            return WARN_COLOR
        return None

    def _current_changed(self, item: QListWidgetItem | None, _previous: object) -> None:
        if item is not None:
            name = str(item.data(Qt.ItemDataRole.UserRole))
            if name != self.selected:
                self._forget_edited_piece()
            self.selected = name
            self._show_selected()

    def _result_tab_shown(self, _index: int) -> None:
        if self.overlay() is not None:
            return  # an overlay's results are filled when it is shown (they are quick)
        if self._results_stale and self.result_tabs.currentWidget() is not self.placement:
            self._show_result(self.spec())

    def _show_selected(self) -> None:
        spec = self.spec()
        key = (self.controller.revision, self.selected)
        if key != self._placement_shown:
            self._placement_shown = key
            data = self.placement_data()
            data.hint, data.hint_face = (
                self.controller.hint_highlight(),
                self.controller.hint_focused,
            )
            self.placement.set_data(data)
            if self._axis is not None:
                self._update_axis_preview()  # the mirror images follow the new data
        overlay = self.overlay()
        self.editor_stack.setCurrentIndex(0 if overlay is None else 1)
        if overlay is not None:
            session = self.controller.session
            _surface, layout, error = self.overlay_layout()
            colour = None
            if session is not None:
                from envelopelab.project.colours import PanelRef

                colour = session.state.colours.colour_of(PanelRef(overlay.name, "A", 1))
            gores = session.design.gores.count if session and session.design.gores else 1
            self.overlay_editor.set_overlay(overlay, layout, error, colour, gores)
        self._update_form(spec)
        self._show_result(spec)
        self._show_simulation(spec)
        self._update_buttons()
        if overlay is not None:
            self._show_overlay_result(layout)
            self.status.setText(
                f"{overlay.name}: overlay (appliqué)"
                + ("" if layout is not None else f" - CANNOT BE LAID: {error}")
            )
            self.duplicate_button.setEnabled(True)
            self.remove_button.setEnabled(True)

    def _update_buttons(self) -> None:
        has = self.spec() is not None
        spec = self.spec()
        self.mirror_button.setEnabled(spec is not None and spec.mirror is None)
        session = self.controller.session
        has_axes = session is not None and bool(session.state.symmetry_axes)
        self.add_axis_button.setEnabled(self.controller.is_gore)
        self.edit_axis_button.setEnabled(has_axes)
        self.remove_axis_button.setEnabled(has_axes)
        self._show_mirror_link(spec)
        running = self.controller.shape_simulator.running
        gore = self.controller.is_gore
        self.add_button.setEnabled(gore)
        self.duplicate_button.setEnabled(has)
        self.drag_button.setEnabled(has)
        self.remove_button.setEnabled(has)
        self.simulate_button.setEnabled(has and not running and self.placed() is not None)
        self.cancel_button.setEnabled(running)
        self.export_pack_button.setEnabled(gore)
        self.export_blender_button.setEnabled(gore)
        grouped = has and self.group() is not None
        for button in (
            self.move_group_button,
            self.mirror_group_button,
            self.export_group_button,
        ):
            button.setEnabled(grouped)

    def _show_mirror_link(self, spec: ShapeSpec | None) -> None:
        """The banner over the editor: what the selected shape mirrors, or is mirrored by."""
        text = ""
        twin = spec is not None and spec.mirror is not None
        if spec is not None and spec.mirror is not None:
            text = (
                f"⇄ Mirror twin of {spec.mirror.of} across axis {spec.mirror.axis}: edit or "
                "drag either side and the other follows."
            )
        elif spec is not None:
            twins = [s for s in self.specs() if s.mirror is not None and s.mirror.of == spec.name]
            if twins:
                text = (
                    "⇄ Mirrored by "
                    + ", ".join(
                        f"{t.name} across {t.mirror.axis}"  # type: ignore[union-attr]
                        for t in twins
                    )
                    + ": edit or drag either side and the other follows."
                )
        self.mirror_label.setText(text)
        self.mirror_label.setVisible(bool(text))
        self.unlink_button.setVisible(twin)

    def _update_form(self, spec: ShapeSpec | None) -> None:
        design = self.controller.design
        gores = design.gores.count if design is not None and design.gores is not None else 0
        key = None if spec is None else (spec.name, spec.kind, gores)
        if key != self._form_key:
            self._build_form(spec)
            self._form_key = key
        if spec is None:
            return
        self.name_edit.setText(spec.name)  # also undoes a refused rename
        self.group_combo.blockSignals(True)
        self.group_combo.clear()
        self.group_combo.addItems(["", *group_names(self.specs())])
        self.group_combo.setCurrentText(spec.group or "")
        self.group_combo.blockSignals(False)
        data = spec.model_dump(mode="json")
        for path, box in self.fields.items():
            box.blockSignals(True)
            box.setValue(_get(data, path))
            box.blockSignals(False)
        self.holes_table.blockSignals(True)
        self.holes_table.setRowCount(len(spec.feed_holes))
        for i, hole in enumerate(spec.feed_holes):
            for j, text in enumerate(
                (
                    str(hole.gore),
                    f"{hole.tape_position:.4f}",
                    f"{hole.across:.3f}",
                    f"{hole.radius:.4f}",
                )
            ):
                self.holes_table.setItem(i, j, QTableWidgetItem(text))
        self.holes_table.blockSignals(False)
        self.feed_check.blockSignals(True)
        self.feed_check.setChecked(spec.feed_hole_radius is not None)
        self.feed_check.blockSignals(False)
        self.feed_radius.blockSignals(True)
        self.feed_radius.setEnabled(spec.feed_hole_radius is not None)
        if spec.feed_hole_radius is not None:
            self.feed_radius.setValue(spec.feed_hole_radius)
        self.feed_radius.blockSignals(False)
        capped = pointed(spec)
        self.cap_auto.blockSignals(True)
        self.cap_auto.setChecked(spec.cap_diameter is None)
        self.cap_auto.setEnabled(capped)
        self.cap_auto.blockSignals(False)
        self.cap_diameter.blockSignals(True)
        self.cap_diameter.setValue(cap_diameter(spec))
        self.cap_diameter.setEnabled(capped and spec.cap_diameter is not None)
        self.cap_diameter.blockSignals(False)
        self._fill_layout(spec)
        self._fill_crown(spec)
        self.fabric_combo.blockSignals(True)
        index = self.fabric_combo.findData(spec.fabric or "")
        self.fabric_combo.setCurrentIndex(max(index, 0))
        self.fabric_combo.blockSignals(False)
        if isinstance(spec, RevolvedShape):
            self.smooth_check.blockSignals(True)
            self.smooth_check.setChecked(spec.smooth)
            self.smooth_check.blockSignals(False)
            self.profile_table.blockSignals(True)
            self.profile_table.setRowCount(len(spec.profile))
            for i, (rho, zeta) in enumerate(spec.profile):
                self.profile_table.setItem(i, 0, QTableWidgetItem(f"{rho:.4f}"))
                self.profile_table.setItem(i, 1, QTableWidgetItem(f"{zeta:.4f}"))
            self.profile_table.blockSignals(False)

    def _build_form(self, spec: ShapeSpec | None) -> None:
        for form in (self.form, self.holes_form):
            while form.rowCount():
                form.removeRow(0)
        self.fields = {}
        self.editor_tabs.setTabVisible(1, isinstance(spec, RevolvedShape))
        self.editor_tabs.setEnabled(spec is not None)
        if spec is None:
            return
        self.name_edit = QLineEdit(spec.name)
        self.name_edit.setObjectName("shapeName")
        self.name_edit.editingFinished.connect(
            lambda: self.set_value(("name",), self.name_edit.text().strip())
        )
        self.form.addRow("Name", self.name_edit)
        self.form.addRow("Kind", QLabel(KIND_LABELS[spec.kind]))
        self.group_combo = QComboBox()
        self.group_combo.setObjectName("shapeGroup")
        self.group_combo.setEditable(True)
        self.group_combo.setToolTip(
            "Object this shape belongs to: shapes of one group are moved, mirrored and "
            "exported together (type a new name to start a group, clear it to take the "
            "shape out)"
        )
        line = self.group_combo.lineEdit()
        if line is not None:
            line.setPlaceholderText("none")
            line.editingFinished.connect(self._group_edited)
        self.group_combo.activated.connect(lambda _i: self._group_edited())
        self.form.addRow("Group", self.group_combo)
        if isinstance(spec, MeshShape):
            mesh_label = QLabel(
                f"{spec.source or 'imported'}: {len(spec.vertices)} vertices, "
                f"{len(spec.triangles)} triangles"
            )
            mesh_label.setWordWrap(True)
            self.form.addRow("Mesh", mesh_label)
        gores = self.controller.design.gores.count if self.controller.is_gore else 999  # type: ignore[union-attr]
        for field in (*PLACEMENT_FIELDS, *KIND_FIELDS[spec.kind], *COMMON_FIELDS):
            box: QSpinBox | QDoubleSpinBox
            if field.integer:
                box = QSpinBox()
                maximum = gores if field.path == ("placement", "gore") else int(field.maximum)
                box.setRange(int(field.minimum), maximum)
            else:
                box = QDoubleSpinBox()
                box.setDecimals(field.decimals)
                box.setRange(field.minimum, field.maximum)
                box.setSingleStep(10.0 ** (1 - field.decimals))
            box.setKeyboardTracking(False)
            box.setObjectName("shape_" + "_".join(field.path))
            box.valueChanged.connect(lambda v, p=field.path: self.set_value_live(p, v))
            self.fields[field.path] = box
            set_hint(box, "shape:" + ".".join(field.path))
            self.form.addRow(field.label, box)
        self.feed_check = QCheckBox("Feed hole in the envelope")
        self.feed_radius = QDoubleSpinBox()
        self.feed_radius.setDecimals(3)
        self.feed_radius.setRange(0.001, 100.0)
        self.feed_radius.setSingleStep(0.01)
        self.feed_radius.setKeyboardTracking(False)
        self.feed_check.toggled.connect(self._feed_toggled)
        self.feed_radius.valueChanged.connect(
            lambda v: self.set_value_live(("feed_hole_radius",), float(v))
        )
        feed_row = QHBoxLayout()
        feed_row.addWidget(self.feed_check)
        feed_row.addWidget(self.feed_radius)
        self.holes_form.addRow("Feed hole radius (m)", feed_row)
        self.cap_auto = QCheckBox("Automatic")
        self.cap_auto.setObjectName("shapeCapAuto")
        self.cap_diameter = QDoubleSpinBox()
        self.cap_diameter.setObjectName("shapeCapDiameter")
        self.cap_diameter.setDecimals(3)
        self.cap_diameter.setRange(0.0, 100.0)
        self.cap_diameter.setSingleStep(0.01)
        self.cap_diameter.setKeyboardTracking(False)
        tip = (
            "Diameter of the cap the tops of the skin pieces are sewn round, so they do not "
            "meet in a point. Automatic: every piece's top at least "
            f"{CAP_PANEL_TOP_WIDTH * 1000:.0f} mm wide (at most half the base diameter). "
            "0: the pieces meet in a point."
        )
        self.cap_auto.setToolTip(tip)
        self.cap_diameter.setToolTip(tip)
        self.cap_auto.toggled.connect(self._cap_toggled)
        self.cap_diameter.valueChanged.connect(
            lambda v: self.set_value_live(("cap_diameter",), float(v))
        )
        cap_row = QHBoxLayout()
        cap_row.addWidget(self.cap_auto)
        cap_row.addWidget(self.cap_diameter)
        self.holes_form.addRow("Cap diameter (m)", cap_row)
        self.holes_table = QTableWidget(0, 4)
        self.holes_table.setObjectName("extraFeedHoles")
        self.holes_table.setHorizontalHeaderLabels(
            ["gore", "tape position (m)", "across (−0.5–0.5)", "radius (m)"]
        )
        self.holes_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.holes_table.setMinimumHeight(160)
        self.holes_table.setToolTip(
            "More feed holes inside the footprint: gore number, tape length from the mouth, "
            "fraction of the gore width from its centreline, finished radius."
        )
        self.holes_table.itemChanged.connect(self._hole_edited)
        add_hole = QPushButton("Add feed hole")
        add_hole.clicked.connect(self.add_feed_hole)
        remove_hole = QPushButton("Remove feed hole")
        remove_hole.clicked.connect(self._remove_feed_hole)
        clear_holes = QPushButton("Move feed holes clear of seams")
        clear_holes.setToolTip(
            "Move every shape's extra feed holes the least distance, inside their panels and "
            "footprints, so each is clear of its panel's seams by the hole tape and the seam "
            "allowance (one undo step)"
        )
        clear_holes.clicked.connect(self.move_holes_clear)
        holes_buttons = QHBoxLayout()
        holes_buttons.setSpacing(4)
        holes_buttons.addWidget(add_hole)
        holes_buttons.addWidget(remove_hole)
        holes_buttons.addWidget(clear_holes)
        holes = QVBoxLayout()
        holes.addWidget(self.holes_table)
        holes.addLayout(holes_buttons)
        self.holes_form.addRow("More feed holes", holes)
        self.fabric_combo = QComboBox()
        self.fabric_combo.addItem("Same as the envelope row", "")
        for fabric in self.controller.fabrics.fabrics():
            self.fabric_combo.addItem(f"{fabric.name} ({fabric.fabric_id})", fabric.fabric_id)
        self.fabric_combo.currentIndexChanged.connect(
            lambda _i: self.set_value(("fabric",), self.fabric_combo.currentData() or None)
        )
        self.form.addRow("Skin fabric", self.fabric_combo)
        if isinstance(spec, RevolvedShape):
            self.smooth_check = QCheckBox("Smooth profile (spline through the points)")
            self.smooth_check.toggled.connect(lambda on: self.set_value(("smooth",), bool(on)))
            self.form.addRow("", self.smooth_check)
        self._tag_hints()

    # -- shape groups ----------------------------------------------------------------

    def group(self) -> str | None:
        """Group of the selected shape (None: none, or no shape selected)."""
        spec = self.spec()
        return None if spec is None else spec.group

    def _group_edited(self) -> None:
        text = self.group_combo.currentText().strip()
        if not self.set_value(("group",), text or None):
            spec = self.spec()
            self.group_combo.blockSignals(True)
            self.group_combo.setCurrentText("" if spec is None else spec.group or "")
            self.group_combo.blockSignals(False)

    def move_group(self, d_gore: float, d_tape: float, group: str | None = None) -> bool:
        """Move ``group`` (default: the selected shape's) ``d_gore`` gore widths round the
        envelope and ``d_tape`` m up the tape (one undo step)."""
        group = group or self.group()
        if group is None:
            return False
        return bool(self.controller.edit("move_shape_group", group, d_gore, d_tape))

    # -- where the shapes sit -------------------------------------------------------

    def placement_data(self) -> PlacementData:
        """What the 3D sketch and the gore map draw: the envelope, every shape (as placed,
        or only its base point while it is being placed or cannot be), its feed holes and
        the symmetry axes (:mod:`envelopelab.project.placement_map`)."""
        from envelopelab.features.scene import designed_display
        from envelopelab.project import placement_map as pm
        from envelopelab.project.gore_design import display_points
        from envelopelab.project.shapes import display_offset
        from envelopelab.project.symmetry import symmetry_lines

        session = self.controller.session
        surface = self.controller.envelope_surface()
        if session is None or surface is None or session.design.gores is None:
            return PlacementData()
        design = session.design
        # The envelope inputs only (and the half-gore rows the sketch colours by halves).
        halved = tuple(r.letter for r in session.design.gores.panel_rows if r.half_gore)
        key = (self.controller.shape_host_hash(), halved)
        if self._placement_key != key:
            self._placement_cache = (pm.gore_map(surface), pm.envelope_sketch(design))
            self._placement_key = key
        gore_map, sketch = self._placement_cache
        axes = [
            (a.name, pm.axis_line(gore_map, a), symmetry_lines(design, [a]))
            for a in session.state.symmetry_axes
        ]
        shapes = []
        for spec in session.state.shapes:
            g, s = pm.gore_position(spec.placement), spec.placement.tape_position
            holes: list[np.ndarray] = []
            if spec.feed_hole_radius is not None:
                holes += pm.ring_lines(gore_map, g, s, spec.feed_hole_radius)
            for h in spec.feed_holes:
                holes += pm.ring_lines(gore_map, h.gore - 0.5 + h.across, h.tape_position, h.radius)
            # While the shape is placed again its last placed design is drawn: the
            # views keep the shape on screen and change it when the new one arrives.
            result = self.controller.shapes.shown(spec.name)
            placed = None if result is None else result.design
            if placed is not None:
                cached = self._drawn.get(spec.name)
                if cached is None or cached[0] is not placed or cached[1] is not gore_map:
                    shown = designed_display(placed, rows=14, per_piece=3)
                    shift = display_offset(design, placed)
                    cached = (
                        placed,
                        gore_map,
                        shown.points + shift,
                        shown.triangles,
                        pm.footprint_lines(gore_map, placed),
                        placed.base_point + shift,
                        (
                            np.asarray(placed.surface.gore_position(placed.footprint_theta)),
                            np.asarray(placed.footprint_s),
                        ),
                        np.asarray(placed.footprint_points)[::4] + shift,
                        np.asarray(shown.piece),
                        shown.pieces,
                        [np.asarray(seam, float) + shift for seam in shown.seams],
                        None if shown.tier is None else np.asarray(shown.tier),
                    )
                    self._drawn[spec.name] = cached
                (
                    _p,
                    _m,
                    points,
                    triangles,
                    footprint,
                    base3d,
                    gs,
                    fp3d,
                    piece,
                    pieces,
                    seams,
                    tier,
                ) = cached
            else:
                theta = surface.theta_at(spec.placement.gore, spec.placement.across)
                base3d = display_points(design, np.array([s]), np.array([theta]))[0]
                points, triangles = np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64)
                footprint = []
                gs, fp3d = None, None
                piece, pieces, seams, tier = None, 0, [], None
            shapes.append(
                PlacedShape(
                    spec.name,
                    footprint,
                    holes,
                    gore_map.points(np.array([g]), np.array([s]))[0],
                    points,
                    triangles,
                    np.asarray(base3d, float),
                    spec.placement,
                    gs,
                    fp3d,
                    piece,
                    pieces,
                    seams,
                    tier,
                )
            )
        shapes += self._placed_overlays(design, gore_map)
        specs: dict[str, Any] = {s.name: s for s in session.state.shapes}
        specs.update({o.name: o for o in session.state.overlays})

        def place_at(name: str, point: np.ndarray) -> Any:
            return placement_at(surface, point, specs[name].placement)

        data = PlacementData(gore_map, sketch, axes, shapes, self.selected, place_at)
        data.edited_piece = self.edited_piece
        if self.controller.show_panel_colours and not session.state.colours.is_empty():
            data.colours = session.state.colours
        return data

    def _placed_overlays(self, design: Any, gore_map: Any) -> list[PlacedShape]:
        """Every overlay as the views draw it: its outline on the gore map (broken at the
        seams), and a patch on the envelope (3D) coloured as one piece."""
        from envelopelab.project.gore_design import display_points
        from envelopelab.project.overlays import map_polygons, overlay_mesh

        out = []
        n = gore_map.gores

        def on_map(gore: int, g: np.ndarray, s: np.ndarray) -> np.ndarray:
            half = np.asarray(gore_map.half_width(s), float)
            x = (gore - 0.5) * gore_map.column + 2.0 * (g - (gore - 1) - 0.5) * half
            return np.column_stack([x, s])

        def to_3d(g: np.ndarray, s: np.ndarray) -> np.ndarray:
            pts = np.asarray(display_points(design, s, 2.0 * math.pi * g / n), float)
            r = np.hypot(pts[:, 0], pts[:, 1])[:, None]
            # Just outside the drawn envelope so the patch is not hidden by it.
            pts[:, :2] *= (r + 0.01) / np.maximum(r, 1e-9)
            return pts

        for spec in self.overlays():
            surface, layout, _error = self.overlay_layout(spec.name)
            pl = spec.placement
            g0, s0 = pl.gore - 0.5 + pl.across, pl.tape_position
            base = on_map(pl.gore, np.array([g0]), np.array([s0]))[0]
            base3d = to_3d(np.array([g0]), np.array([s0]))[0]
            footprint: list[np.ndarray] = []
            points, triangles = np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64)
            if layout is not None:
                footprint = [poly for _gore, poly in map_polygons(layout, gore_map)]
                points, triangles = overlay_mesh(layout, surface, to_3d)
            out.append(
                PlacedShape(
                    spec.name,
                    footprint,
                    [],
                    base,
                    points,
                    triangles,
                    base3d,
                    spec.placement,
                    piece=np.zeros(len(triangles), dtype=np.int64),
                    pieces=1,
                    tier=np.zeros(len(triangles), dtype=np.int64),
                )
            )
        return out

    def show_hint(self) -> None:
        """Draw the controller's hint on the On the balloon tab (amber, no redraw of the
        rest)."""
        if not self.isVisible() and self.controller.defer_hidden:
            return
        hint, face = self.controller.hint_highlight(), self.controller.hint_focused
        self.placement.data.hint, self.placement.data.hint_face = hint, face
        self.placement.view3d.set_hint(hint, face)  # type: ignore[attr-defined]

    def _overlay_hint(self, key: str) -> Any:
        """Where a value of the selected overlay (``shape:overlay.<field>``) acts: its
        outline on the balloon, faced at its centre (``Highlight``; None: not laid)."""
        from envelopelab.project.gore_design import display_points
        from envelopelab.project.highlight import Highlight

        overlay = self.overlay()
        session = self.controller.session
        _surface, layout, _error = self.overlay_layout()
        if overlay is None or layout is None or session is None or session.design.gores is None:
            return None
        n = session.design.gores.count
        g, s = layout.gs[:, 0], layout.gs[:, 1]
        line = np.asarray(display_points(session.design, s, 2.0 * math.pi * g / n), float)
        pl = overlay.placement
        centre = np.asarray(
            display_points(
                session.design,
                np.array([pl.tape_position]),
                np.array([2.0 * math.pi * (pl.gore - 0.5 + pl.across) / n]),
            ),
            float,
        )[0]
        field = key.removeprefix("shape:overlay.")
        what = "where it sits" if field.startswith("placement") else "its outline"
        if field == "hem":
            what = "its outline (the hem is added round it on the cut piece)"
        words = field.split(".")[-1].replace("_deg", "").replace("_", " ")
        closed = np.vstack([line, line[:1]])
        return Highlight(f"{overlay.name} {words}: {what}", [closed], centre, key)

    def shape_hint(self, key: str) -> Any:
        """Where a value of the selected shape (``shape:<field path>``) acts, as lines on
        the balloon (``Highlight``; None: the shape is not placed)."""
        from envelopelab.features.scene import designed_display
        from envelopelab.project.highlight import Highlight
        from envelopelab.project.shapes import display_offset

        field = key.removeprefix("shape:")
        if field.startswith("overlay."):
            return self._overlay_hint(key)
        spec = self.spec()
        result = None if spec is None else self.controller.shapes.shown(spec.name)
        placed = None if result is None else result.design
        session = self.controller.session
        if spec is None or placed is None or session is None:
            return None
        cached = self._hint_lines.get(spec.name)
        if cached is None or cached[0] is not placed:
            shown = designed_display(placed, rows=24, per_piece=4)
            shift = display_offset(session.design, placed)
            seams = [np.asarray(s, float) + shift for s in shown.seams]
            rim = np.asarray(shown.rim, float) + shift
            cached = (placed, seams, rim, np.asarray(placed.base_point, float) + shift)
            self._hint_lines[spec.name] = cached
        _p, seams, rim, base = cached
        m = piece_count(spec)
        gore_seams, rest = seams[:m], seams[m:]
        splits = rest[: len(spec.splits)]
        cap = rest[len(spec.splits) :]
        words = field.split(".")[-1].replace("_deg", "").replace("_", " ")
        label = f"{spec.name} {words}"
        if field.startswith("placement"):
            return Highlight(f"{label}: where the shape sits (its rim)", [rim], base, key)
        if field in (
            "seam_offset_deg",
            "panel_widths",
            "crown_seam_offset_deg",
            "crown_panel_widths",
        ):
            return Highlight(f"{label}: its seams", gore_seams, base, key)
        if field == "splits":
            lines = splits or gore_seams
            return Highlight(f"{label}: its horizontal splits", lines, base, key)
        if field in (
            "cap_diameter",
            "cap_shift",
            "cap_direction_deg",
            "cap_across",
            "cap_up",
            "crown_shape",
        ):
            lines = cap or gore_seams
            return Highlight(f"{label}: its cap", lines, lines[0][0] if lines else base, key)
        if field.startswith("feed_hole"):
            return Highlight(f"{label}: the feed hole(s) inside its rim", [rim], base, key)
        if field in ("marks_per_piece",):
            return Highlight(f"{label}: the match marks round its rim", [rim], base, key)
        return Highlight(f"{label}: the whole shape", [rim, *seams], base, key)

    def nudge(self, d_hoop: float, d_tape: float) -> bool:
        """Move the selected shape ``d_hoop`` m round the envelope (towards higher gores)
        and ``d_tape`` m up the tape (:func:`envelopelab.project.placement_map.nudged`);
        one undo step. True when it moved."""
        from envelopelab.project.placement_map import nudged

        spec = self.spec() or self.overlay()
        gore_map = self._placement_cache[0]
        if spec is None or gore_map is None:
            return False
        return self.move_object(spec.name, nudged(gore_map, spec.placement, d_hoop, d_tape))

    # -- symmetry axes and mirror twins ----------------------------------------------

    def axes(self) -> list[Any]:
        """The project's symmetry axes."""
        session = self.controller.session
        return [] if session is None else list(session.state.symmetry_axes)

    def _gores(self) -> int:
        design = self.controller.design
        return design.gores.count if design is not None and design.gores is not None else 1

    def _fill_axes(self) -> None:
        current = self.axes_list.currentItem()
        chosen = None if current is None else current.data(Qt.ItemDataRole.UserRole)
        self.axes_list.blockSignals(True)
        self.axes_list.clear()
        for axis in self.axes():
            users = [s.name for s in self.specs() if s.mirror and s.mirror.axis == axis.name]
            text = f"{axis.name} — {axis_gore_label(axis.line, self._gores())}"
            item = QListWidgetItem(text + (f"  ({len(users)} twin(s))" if users else ""))
            item.setData(Qt.ItemDataRole.UserRole, axis.name)
            self.axes_list.addItem(item)
            if axis.name == chosen:
                self.axes_list.setCurrentItem(item)
        self.axes_list.blockSignals(False)

    def add_axis(self, name: str, line: float) -> bool:
        """Add the symmetry axis ``name`` at gore position ``line`` (gore widths from the
        first seam; gore n's centreline is n - 0.5)."""
        return bool(self.controller.edit("add_symmetry_axis", name, line))

    def mirror_selected(self, axis: str) -> str | None:
        """Add a linked mirror twin of the selected shape across ``axis``; its name."""
        if self.selected is None:
            return None
        twin = self.controller.edit("mirror_shape", self.selected, axis)
        if twin:
            self.select(str(twin))
        return str(twin) if twin else None

    def unlink_selected(self) -> bool:
        """Make the selected mirror twin an ordinary shape."""
        if self.selected is None:
            return False
        return bool(self.controller.edit("unlink_mirror", self.selected))

    # -- placing a symmetry axis, seen while it is placed -----------------------------

    def _base_line(self) -> float:
        """Gore position of the selected shape's base point (or gore 1's centreline)."""
        spec = self.spec()
        if spec is None:
            return 0.5
        return spec.placement.gore - 0.5 + spec.placement.across

    def _free_axis_name(self) -> str:
        names = {a.name for a in self.axes()}
        k = 1
        while f"Axis {k}" in names:
            k += 1
        return f"Axis {k}"

    def _chosen_axis(self) -> Any:
        item = self.axes_list.currentItem() or self.axes_list.item(0)
        if item is None:
            return None
        name = item.data(Qt.ItemDataRole.UserRole)
        return next((a for a in self.axes() if a.name == name), None)

    def _start_axis(self, session: _AxisSession, title: str, accept: str, name: str) -> None:
        """Open the axis bar on the On the balloon tab and let the pointer place it."""
        self.result_tabs.setCurrentWidget(self.placement)
        self._axis = session
        targets = [a.name for a in self.axes()] if session.mode.startswith("mirror") else None
        self.placement.begin_axis(title, accept, name, self._gores(), targets)
        if session.line is not None:
            self.placement.show_axis_line(
                session.line, axis_gore_label(session.line, self._gores())
            )
        else:
            self.placement.show_axis_line(self._base_line(), "click on the map or the 3D view")
        self._update_axis_preview()

    def begin_add_axis(self) -> None:
        """Place a new symmetry axis: it starts on the selected shape's base point, follows
        the pointer, and a click (or the gore line typed) puts it there; Place adds it.
        The selected shape's mirror image across it is shown as it moves."""
        spec = self.spec()
        targets = [spec.name] if spec is not None and spec.mirror is None else []
        line = snap(self._base_line()) if spec is not None else 0.5
        self._start_axis(
            _AxisSession("add", None, line, targets),
            "Place a new symmetry axis: move the pointer over the gore map or the 3D view "
            "and click where it goes (or type the gore line). Dashed magenta: where the "
            "selected shape's mirror image would be.",
            "Place axis",
            self._free_axis_name(),
        )

    def begin_edit_axis(self, name: str | None = None, grabbed: bool = False) -> None:
        """Move or rename axis ``name`` (default: the one chosen in the list), seeing it and
        where its mirror twins go while it moves."""
        axis = (
            next((a for a in self.axes() if a.name == name), None)
            if name is not None
            else self._chosen_axis()
        )
        if axis is None:
            return
        sources = [s.mirror.of for s in self.specs() if s.mirror and s.mirror.axis == axis.name]
        self._start_axis(
            _AxisSession("edit", axis.name, float(axis.line), sources, grabbed=grabbed),
            f"Move axis {axis.name}: click or drag on the gore map or the 3D view (or type "
            "the gore line). Dashed magenta: where its mirror twins go.",
            "Move axis",
            axis.name,
        )

    def begin_mirror(self) -> None:
        """Mirror the selected shape: pick an existing axis or place a new one, seeing
        where the mirror image lands while the axis moves; then add the linked twin."""
        spec = self.spec()
        if spec is None or spec.mirror is not None:
            return
        self._start_axis(
            _AxisSession("mirror", None, None, [spec.name]),
            f"Mirror {spec.name}: move the pointer to see where its mirror image lands, and "
            "click to place the axis (or choose an existing axis).",
            "Mirror across it",
            self._free_axis_name(),
        )

    def begin_mirror_group(self) -> None:
        """Mirror the selected shape's group across an axis placed or chosen the same
        way, seeing every member's mirror image."""
        group = self.group()
        if group is None:
            return
        members = [s.name for s in self.specs() if s.group == group and s.mirror is None]
        self._start_axis(
            _AxisSession("mirror group", None, None, members, group=group),
            f"Mirror group {group}: move the pointer to see where the mirror images land, "
            "and click to place the axis (or choose an existing axis).",
            "Mirror across it",
            self._free_axis_name(),
        )

    def _axis_pointed(self, g: float, chosen: bool) -> None:
        session = self._axis
        if session is None or session.fixed:
            return
        if self.placement.axis_snap.isChecked():
            g = snap(g)
        g %= self._gores()
        if chosen:
            session.line = g
            self.placement.show_axis_line(g, axis_gore_label(g, self._gores()))
        else:
            session.hover = g
            if session.line is None:  # nothing chosen yet: the bar follows the pointer
                self.placement.show_axis_line(
                    g, f"pointer: {axis_gore_label(g, self._gores())}, click to place it"
                )
        self._update_axis_preview()

    def _axis_typed(self, g: float) -> None:
        if self._axis is not None and not self._axis.fixed:
            self._axis.line = g % self._gores()
            self.placement.show_axis_line(self._axis.line, axis_gore_label(g, self._gores()))
            self._update_axis_preview()

    def _axis_target(self, name: str) -> None:
        """Mirror across the existing axis ``name`` ("": place a new one)."""
        session = self._axis
        if session is None:
            return
        axis = next((a for a in self.axes() if a.name == name), None)
        session.fixed = axis is not None
        session.axis = None if axis is None else axis.name
        session.line = None if axis is None else float(axis.line)
        if axis is not None:
            self.placement.show_axis_line(
                axis.line, axis_gore_label(axis.line, self._gores()), editable=False
            )
        else:
            self.placement.show_axis_line(self._base_line(), "click on the map or the 3D view")
        self._update_axis_preview()

    def axis_preview(self) -> AxisPreview | None:
        """What the views draw while an axis is placed: the chosen axis, the one under the
        pointer, and the mirror images the axis would make (at the chosen axis, or at the
        one under the pointer until one is chosen)."""
        from envelopelab.project.placement_map import axis_line, mirrored_lines, reflect
        from envelopelab.project.symmetry import SymmetryAxis, symmetry_lines

        session, data = self._axis, self.placement.data
        if session is None or data.gore_map is None or self.controller.design is None:
            return None
        m, design, n = data.gore_map, self.controller.design, self._gores()

        def lines(g: float) -> tuple[np.ndarray, list[np.ndarray]]:
            axis = SymmetryAxis(name="preview", line=g % n)
            return axis_line(m, axis), symmetry_lines(design, [axis])

        name = self.placement.axis_name.text().strip() or "axis"
        chosen = session.line
        preview = AxisPreview(
            name if not session.fixed else str(session.axis),
            axis_gore_label(chosen, n) if chosen is not None else "not placed yet",
        )
        if chosen is not None:
            preview.map_line, preview.lines3d = lines(chosen)
        if session.hover is not None and not session.fixed:
            preview.hover, preview.hover3d = lines(session.hover)
        ghost = chosen if chosen is not None else session.hover
        if ghost is not None:
            for shape in data.shapes:
                if shape.name not in session.targets:
                    continue
                if shape.footprint_gs is not None:
                    preview.ghosts += mirrored_lines(m, *shape.footprint_gs, ghost)
                if shape.footprint3d is not None:
                    preview.ghosts3d.append(reflect(shape.footprint3d, ghost, n))
        return preview

    def _update_axis_preview(self) -> None:
        self.placement.set_preview(self.axis_preview())

    def accept_axis(self) -> bool:
        """Do what the axis bar was opened for (add, move, mirror); True when done."""
        session = self._axis
        if session is None:
            return False
        if session.line is None:
            self.controller.editRejected.emit(
                "place the axis first: click on the gore map or the 3D view"
            )
            return False
        name = self.placement.axis_name.text().strip()
        line = session.line
        ok: Any
        if session.mode == "add":
            ok = self.controller.edit("add_symmetry_axis", name, line)
        elif session.mode == "edit":
            ok = self.controller.edit("update_symmetry_axis", session.axis, line, name)
        else:
            axis = session.axis
            if axis is None:  # a new axis first, then the twins across it
                if not self.controller.edit("add_symmetry_axis", name, line):
                    return False
                axis = name
            if session.mode == "mirror":
                ok = self.mirror_selected(axis)
            else:
                ok = self.mirror_group(group=session.group, axis=axis)
        if ok is None or ok is False:
            return False
        self.cancel_axis()
        return True

    def cancel_axis(self) -> None:
        """Close the axis bar without changing anything."""
        self._axis = None
        self.placement.end_axis()

    def _axis_grabbed(self, name: str) -> None:
        if self._axis is None:
            self.begin_edit_axis(name, grabbed=True)

    def _axis_released(self) -> None:
        if self._axis is not None and self._axis.grabbed:
            self.accept_axis()

    def _add_axis_dialog(self) -> None:
        self.begin_add_axis()

    def _edit_axis_dialog(self) -> None:
        self.begin_edit_axis()

    def _remove_axis(self) -> None:
        axis = self._chosen_axis()
        if axis is not None:
            self.controller.edit("remove_symmetry_axis", axis.name)

    def _mirror_dialog(self) -> None:
        self.begin_mirror()

    def mirror_group(
        self,
        line: float | None = None,
        copy: bool = True,
        group: str | None = None,
        axis: str | None = None,
    ) -> bool:
        """Mirror ``group`` (default: the selected shape's): across the symmetry axis
        ``axis`` as linked twins, or about the gore line ``line`` (gore position: gore n's
        centreline is n - 0.5, the seam after it n) as independent copies or in place
        (one undo step)."""
        group = group or self.group()
        if group is None:
            return False
        before = self.controller.revision
        out = self.controller.edit("mirror_shape_group", group, line, copy, axis)
        if out is None:
            return False
        if copy and not out:
            self.controller.message.emit(f"{group}: every shape lies on the mirror line")
        return self.controller.revision != before

    def _move_group_dialog(self) -> None:
        values = _ask(
            self,
            f"Move group {self.group()}",
            [
                ("Round the envelope (gores)", -100.0, 100.0, 0.0, 2),
                ("Up the tape (m)", -100.0, 100.0, 0.0, 3),
            ],
        )
        if values is not None:
            self.move_group(values[0], values[1])

    def _mirror_group_dialog(self) -> None:
        self.begin_mirror_group()

    def _export_group_dialog(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export group to Blender", f"{self.group()}.obj", "OBJ (*.obj)"
        )
        if path:
            self.export_blender(path, self.group())

    # -- panel layout ----------------------------------------------------------------

    def _fill_layout(self, spec: ShapeSpec) -> None:
        """Show ``spec``'s panel layout: seam turn, widths (and the angle each piece
        spans), splits."""
        count = piece_count(spec)
        widths = spec.panel_widths or [1.0] * count
        total = sum(widths)
        self.seam_turn.blockSignals(True)
        self.seam_turn.setValue(spec.seam_offset_deg)
        self.seam_turn.blockSignals(False)
        self.widths_table.blockSignals(True)
        self.widths_table.setRowCount(count)
        self.widths_table.setVerticalHeaderLabels([str(k + 1) for k in range(count)])
        for k, w in enumerate(widths):
            self.widths_table.setItem(k, 0, QTableWidgetItem(f"{w:g}"))
            span = QTableWidgetItem(f"{360.0 * w / total:.1f}°")
            span.setFlags(span.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.widths_table.setItem(k, 1, span)
        self.widths_table.blockSignals(False)
        if self.edited_piece is not None and self.edited_piece >= count:
            self.edited_piece = None
        self.preview.edited = self.edited_piece
        self.meeting_pad.set_edited(self.edited_piece)
        self.split_piece_button.setEnabled(self.edited_piece is not None and count < MAX_PIECES)
        mesh = isinstance(spec, MeshShape)
        self.splits_table.blockSignals(True)
        self.splits_table.setRowCount(len(spec.splits))
        letters = [chr(ord("A") + i) for i in range(len(spec.splits) + 1)]
        self.splits_table.setVerticalHeaderLabels(
            [f"{letters[i]}|{letters[i + 1]}" for i in range(len(spec.splits))]
        )
        for i, f in enumerate(spec.splits):
            self.splits_table.setItem(i, 0, QTableWidgetItem(f"{100.0 * f:.1f}"))
        self.splits_table.blockSignals(False)
        for widget in (self.splits_table, self.add_split_button, self.remove_split_button):
            widget.setEnabled(not mesh)
        tiers = len(spec.splits) + 1
        text = (
            f"{count} {'gores' if spec.kind in ('dome', 'revolved') else 'panels'} round the "
            f"axis{' (equal)' if not spec.panel_widths else ''}"
        )
        text += f" in {tiers} tiers, A at the rim" if tiers > 1 else ", one tier"
        if mesh:
            text += "; a mesh shape's panels cannot be split across"
        self.layout_note.setText(text + ".")

    def _tag_hints(self) -> None:
        """Say where on the balloon each value of the selected shape acts
        (:mod:`envelopelab_app.hints`; :meth:`shape_hint` draws it)."""
        for widget, key in (
            (self.feed_radius, "shape:feed_hole_radius"),
            (self.feed_check, "shape:feed_hole_radius"),
            (self.cap_diameter, "shape:cap_diameter"),
            (self.cap_auto, "shape:cap_diameter"),
            (self.holes_table, "shape:feed_holes"),
            (self.seam_turn, "shape:seam_offset_deg"),
            (self.widths_table, "shape:panel_widths"),
            (self.split_piece_button, "shape:panel_widths"),
            (self.splits_table, "shape:splits"),
            (self.add_split_button, "shape:splits"),
            (self.remove_split_button, "shape:splits"),
            (self.crown_turn, "shape:crown_seam_offset_deg"),
            (self.crown_widths_table, "shape:crown_panel_widths"),
            (self.crown_own, "shape:crown_seam_offset_deg"),
            (self.meeting_pad, "shape:cap_across"),
            (self.cap_across, "shape:cap_across"),
            (self.cap_up, "shape:cap_up"),
            (self.meeting_centre, "shape:cap_across"),
            (self.cap_kind, "shape:crown_shape"),
            (self.cap_turn, "shape:crown_shape"),
            (self.cap_width, "shape:crown_shape"),
            (self.cap_length, "shape:crown_shape"),
            (self.cap_points, "shape:crown_shape"),
            (self.cap_import, "shape:crown_shape"),
            (self.profile_table, "shape:profile"),
        ):
            set_hint(widget, key)

    def _crown_box(self) -> QGroupBox:
        """Where the panels meet at the crown: the seams' angles there and the cap's
        position (ADR-0049)."""
        box = QGroupBox("Where the panels meet (crown)")
        box.setObjectName("shapeCrownBox")
        box.setToolTip(
            "Where the gores or panels meet at the top: the point they meet at (seen from "
            "above the shape, click or drag it) and their angles there. The seams leave the "
            "rim where the seam turn and widths above put them and turn smoothly to the "
            "angles set here."
        )
        form = QFormLayout(box)
        self.crown_own = QCheckBox("Own crown layout (otherwise as at the rim)")
        self.crown_own.setObjectName("shapeCrownOwn")
        self.crown_own.toggled.connect(self._crown_own_toggled)
        form.addRow(self.crown_own)
        self.crown_turn = QDoubleSpinBox()
        self.crown_turn.setObjectName("shapeCrownTurn")
        self.crown_turn.setRange(-180.0, 180.0)
        self.crown_turn.setDecimals(1)
        self.crown_turn.setSuffix(" °")
        self.crown_turn.setKeyboardTracking(False)
        self.crown_turn.setToolTip(
            "Seam turn at the crown: where piece 1 is centred round the axis at the top"
        )
        self.crown_turn.valueChanged.connect(
            lambda v: self.set_value_live(("crown_seam_offset_deg",), round(float(v), 1))
        )
        form.addRow("Crown seam turn", self.crown_turn)
        self.crown_widths_table = QTableWidget(0, 2)
        self.crown_widths_table.setObjectName("shapeCrownWidths")
        self.crown_widths_table.setHorizontalHeaderLabels(
            ["Relative width at the crown", "Spans round the axis"]
        )
        self.crown_widths_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.crown_widths_table.setMinimumHeight(120)
        self.crown_widths_table.itemChanged.connect(self._crown_width_edited)
        self.crown_widths_table.currentCellChanged.connect(
            lambda row, _c, _pr, _pc: self.set_edited_piece(row if row >= 0 else None)
        )
        equal = QPushButton("Equal at crown")
        equal.setObjectName("shapeCrownEqual")
        equal.setToolTip("Every piece the same width where they meet at the top")
        equal.clicked.connect(lambda: self.set_crown_widths(None))
        same = QPushButton("As at the rim")
        same.setObjectName("shapeCrownAsRim")
        same.clicked.connect(lambda: self.set_value(("crown_panel_widths",), []))
        widths = QVBoxLayout()
        widths.addWidget(self.crown_widths_table)
        buttons = QHBoxLayout()
        buttons.addWidget(equal)
        buttons.addWidget(same)
        widths.addLayout(buttons)
        form.addRow("Crown widths", widths)
        # Where the panels meet (the cap's centre), as plan fractions (ADR-0052).
        self.meeting_pad = MeetingPointPad()
        self.meeting_pad.setObjectName("shapeMeetingPad")
        self.meeting_pad.moved.connect(self._meeting_dragged)
        self.cap_across = QDoubleSpinBox()
        self.cap_across.setObjectName("shapeCapAcross")
        self.cap_up = QDoubleSpinBox()
        self.cap_up.setObjectName("shapeCapUp")
        for spin, tip in (
            (self.cap_across, "across the gores (+ towards the next gore)"),
            (self.cap_up, "up the tape (+ towards the crown of the balloon)"),
        ):
            spin.setRange(-1.0, 1.0)
            spin.setDecimals(3)
            spin.setSingleStep(0.05)
            spin.setKeyboardTracking(False)
            spin.setToolTip(
                f"Where the panels meet, {tip}, as a fraction of the shape's widest radius "
                "seen from above (0, 0: the tip; it stays in place when the shape is resized)"
            )
            spin.valueChanged.connect(self._meeting_typed)
        self.meeting_centre = QPushButton("Back to the tip")
        self.meeting_centre.setObjectName("shapeMeetingCentre")
        self.meeting_centre.clicked.connect(lambda: self.set_meeting_point(0.0, 0.0))
        numbers = QFormLayout()
        numbers.addRow("Across", self.cap_across)
        numbers.addRow("Up", self.cap_up)
        numbers.addRow(self.meeting_centre)
        self.meeting_info = QLabel()
        self.meeting_info.setObjectName("shapeMeetingInfo")
        self.meeting_info.setWordWrap(True)
        numbers.addRow(self.meeting_info)
        meeting = QHBoxLayout()
        meeting.addWidget(self.meeting_pad)
        meeting.addLayout(numbers, 1)
        form.insertRow(0, "Where the panels meet", meeting)
        form.insertRow(1, "Cap shape", self._cap_shape_box())
        self.crown_note = QLabel()
        self.crown_note.setObjectName("shapeCrownNote")
        self.crown_note.setWordWrap(True)
        form.addRow(self.crown_note)
        return box

    # -- the cap's shape (ADR-0054) -----------------------------------------------------

    #: Cap shapes offered (label, kind; None: a circle).
    CAP_KINDS = (
        ("Circle (cap diameter)", None),
        ("Footprint, scaled to the cap diameter", "footprint"),
        ("Ellipse", "ellipse"),
        ("Polygon by points", "polygon"),
        ("Imported outline (DXF or SVG)", "outline"),
    )

    def _cap_shape_box(self) -> QWidget:
        """Kind of cap outline and its values: an ellipse's width and length, a polygon's
        corners, an imported file, and the turn."""
        box = QWidget()
        box.setObjectName("shapeCapShape")
        layout = QFormLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        self.cap_kind = QComboBox()
        self.cap_kind.setObjectName("shapeCapKind")
        for label, kind in self.CAP_KINDS:
            self.cap_kind.addItem(label, kind)
        self.cap_kind.setToolTip(
            "The cap's outline seen from above, round where the panels meet: the panels end "
            "on its edge and it is cut from the skin inside it"
        )
        self.cap_kind.activated.connect(lambda _i: self._cap_kind_chosen())
        layout.addRow(self.cap_kind)
        self.cap_turn = QDoubleSpinBox()
        self.cap_turn.setObjectName("shapeCapTurn")
        self.cap_turn.setRange(-180.0, 180.0)
        self.cap_turn.setDecimals(1)
        self.cap_turn.setSuffix(" °")
        self.cap_turn.setKeyboardTracking(False)
        self.cap_turn.setToolTip("Turn of the outline, from across towards up")
        self.cap_turn.valueChanged.connect(lambda v: self._cap_value("turn_deg", float(v)))
        turn = QHBoxLayout()
        turn.setContentsMargins(0, 0, 0, 0)
        turn.addWidget(QLabel("Turn"))
        turn.addWidget(self.cap_turn, 1)
        self.cap_turn_row = QWidget()
        self.cap_turn_row.setLayout(turn)
        layout.addRow(self.cap_turn_row)
        self.cap_width = QDoubleSpinBox()
        self.cap_width.setObjectName("shapeCapWidth")
        self.cap_length = QDoubleSpinBox()
        self.cap_length.setObjectName("shapeCapLength")
        for spin, key, tip in (
            (self.cap_width, "width", "across the gores"),
            (self.cap_length, "length", "up the tape"),
        ):
            spin.setRange(1.0, 20000.0)
            spin.setDecimals(0)
            spin.setSuffix(" mm")
            spin.setKeyboardTracking(False)
            spin.setToolTip(f"The ellipse's size {tip}")
            spin.valueChanged.connect(
                lambda v, k=key: self._cap_value(k, round(float(v) / 1000.0, 4))
            )
        size = QHBoxLayout()
        size.addWidget(QLabel("width"))
        size.addWidget(self.cap_width)
        size.addWidget(QLabel("length"))
        size.addWidget(self.cap_length)
        self.cap_size_row = QWidget()
        self.cap_size_row.setLayout(size)
        layout.addRow(self.cap_size_row)
        self.cap_points = QTableWidget(0, 2)
        self.cap_points.setObjectName("shapeCapPoints")
        self.cap_points.setHorizontalHeaderLabels(["Across (mm)", "Up (mm)"])
        self.cap_points.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.cap_points.setMinimumHeight(120)
        self.cap_points.setToolTip(
            "The polygon's corners from where the panels meet: across towards the next gore, "
            "up the tape. Every direction from the point must cross the outline once."
        )
        self.cap_points.itemChanged.connect(lambda _item: self._cap_points_edited())
        self.cap_smooth = QCheckBox("Smooth edges")
        self.cap_smooth.setObjectName("shapeCapSmooth")
        self.cap_smooth.toggled.connect(lambda on: self._cap_value("smooth", bool(on), live=False))
        add_point = QPushButton("Add point")
        add_point.setObjectName("shapeCapAddPoint")
        add_point.clicked.connect(self.add_cap_point)
        remove_point = QPushButton("Remove point")
        remove_point.setObjectName("shapeCapRemovePoint")
        remove_point.clicked.connect(self.remove_cap_point)
        points = QVBoxLayout()
        points.addWidget(self.cap_points)
        buttons = QHBoxLayout()
        buttons.addWidget(add_point)
        buttons.addWidget(remove_point)
        buttons.addWidget(self.cap_smooth)
        points.addLayout(buttons)
        self.cap_points_row = QWidget()
        self.cap_points_row.setLayout(points)
        layout.addRow(self.cap_points_row)
        self.cap_import = QPushButton("Import outline…")
        self.cap_import.setObjectName("shapeCapImport")
        self.cap_import.setToolTip(
            "Read the largest closed outline of a DXF or SVG drawing; it is scaled to the cap "
            "diameter (its widest width) and centred where the panels meet"
        )
        self.cap_import.clicked.connect(self._choose_cap_outline)
        self.cap_source = QLabel()
        self.cap_source.setObjectName("shapeCapSource")
        imported = QHBoxLayout()
        imported.addWidget(self.cap_import)
        imported.addWidget(self.cap_source, 1)
        self.cap_import_row = QWidget()
        self.cap_import_row.setLayout(imported)
        layout.addRow(self.cap_import_row)
        self.cap_shape_note = QLabel()
        self.cap_shape_note.setObjectName("shapeCapNote")
        self.cap_shape_note.setWordWrap(True)
        layout.addRow(self.cap_shape_note)
        return box

    def _fill_cap_shape(self, spec: ShapeSpec, capped: bool) -> None:
        """Show ``spec``'s cap shape in the controls."""
        c = spec.crown_shape
        kind = None if c is None else c.kind
        tube = isinstance(spec, TubeShape)
        widgets = (
            self.cap_kind,
            self.cap_turn,
            self.cap_width,
            self.cap_length,
            self.cap_points,
            self.cap_smooth,
            self.cap_import,
        )
        for widget in widgets:
            widget.blockSignals(True)
        try:
            self.cap_kind.setCurrentIndex(max(0, self.cap_kind.findData(kind)))
            self.cap_turn.setValue(0.0 if c is None else c.turn_deg)
            self.cap_width.setValue(1000.0 * (c.width if c is not None and c.width else 0.0))
            self.cap_length.setValue(1000.0 * (c.length if c is not None and c.length else 0.0))
            self.cap_smooth.setChecked(c is not None and c.smooth)
            corners = list(c.points) if c is not None and kind == "polygon" else []
            self.cap_points.setRowCount(len(corners))
            for i, (a, u) in enumerate(corners):
                self.cap_points.setItem(i, 0, QTableWidgetItem(f"{a * 1000.0:.1f}"))
                self.cap_points.setItem(i, 1, QTableWidgetItem(f"{u * 1000.0:.1f}"))
        finally:
            for widget in widgets:
                widget.blockSignals(False)
        self.cap_source.setText(c.source if c is not None and kind == "outline" else "")
        self.cap_turn_row.setVisible(kind in ("footprint", "ellipse", "outline"))
        self.cap_size_row.setVisible(kind == "ellipse")
        self.cap_points_row.setVisible(kind == "polygon")
        self.cap_import_row.setVisible(kind == "outline")
        enabled = capped and not tube
        for widget in widgets:
            widget.setEnabled(enabled)
        if tube:
            self.cap_shape_note.setText("A tube's tip disc stays round.")
        elif not capped:
            self.cap_shape_note.setText(
                "Shaping the cap needs a cap: set a cap diameter (Feed holes & cap)."
            )
        elif kind in ("footprint", "outline"):
            self.cap_shape_note.setText(
                "Scaled so its widest width is the cap diameter (Feed holes & cap)."
            )
        elif kind is not None:
            self.cap_shape_note.setText(
                "The cap is cut from the skin inside this outline and flattened; a large cap "
                "on a strongly curved top cannot lie quite flat (see area distortion)."
            )
        else:
            self.cap_shape_note.setText("")

    def set_crown_shape(self, data: dict[str, Any] | None, live: bool = False) -> bool:
        """Give the selected shape's cap the outline ``data`` (``CrownShapeSpec`` fields;
        None: a circle); one undo step for a held value (``live``)."""
        name, spec = self.selected, self.spec()
        if name is None or spec is None:
            return False
        current = None if spec.crown_shape is None else spec.crown_shape.model_dump(mode="json")
        if data == current:
            return False
        values = {"crown_shape": data}
        if live:
            self.controller.edit_live(
                f"shape:{name}:crown_shape",
                lambda: self.controller.edit("update_shape", name, values),
            )
            return True
        ok = bool(self.controller.edit("update_shape", name, values))
        if not ok:
            self.refresh()
        return ok

    def _cap_data(self) -> dict[str, Any] | None:
        spec = self.spec()
        if spec is None or spec.crown_shape is None:
            return None
        data: dict[str, Any] = spec.crown_shape.model_dump(mode="json")
        return data

    def _cap_value(self, key: str, value: Any, live: bool = True) -> None:
        data = self._cap_data()
        if data is None:
            return
        data[key] = value
        self.set_crown_shape(data, live=live)

    def _cap_kind_chosen(self) -> None:
        spec = self.spec()
        kind = self.cap_kind.currentData()
        if spec is None:
            return
        if kind == "outline":
            if not self._choose_cap_outline():
                self.refresh()
            return
        d = cap_diameter(spec)
        if kind is None:
            self.set_crown_shape(None)
        elif kind == "footprint":
            self.set_crown_shape({"kind": "footprint"})
        elif kind == "ellipse":
            self.set_crown_shape({"kind": "ellipse", "width": d, "length": d})
        else:  # a square the cap's size to start from
            r = round(d / 2.0, 4)
            self.set_crown_shape(
                {"kind": "polygon", "points": [[r, r], [-r, r], [-r, -r], [r, -r]]}
            )

    def _choose_cap_outline(self) -> bool:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import a cap outline", "", "Outlines (*.dxf *.svg)"
        )
        return bool(path) and self.import_cap_outline(path)

    def import_cap_outline(self, path: str | Path) -> bool:
        """Shape the selected shape's cap like the largest closed outline of a DXF or SVG
        file (:func:`envelopelab.io.outline_file.read_outline`)."""
        from envelopelab.io.outline_file import OutlineFileError, read_outline

        try:
            points = read_outline(path)
        except OutlineFileError as exc:
            QMessageBox.warning(self, "Import a cap outline", str(exc))
            return False
        data = {
            "kind": "outline",
            "points": [[float(a), float(b)] for a, b in points],
            "source": Path(path).name,
        }
        return self.set_crown_shape(data)

    def _cap_points_edited(self) -> None:
        points = []
        for i in range(self.cap_points.rowCount()):
            cells = (self.cap_points.item(i, 0), self.cap_points.item(i, 1))
            try:
                a, u = (float(c.text()) / 1000.0 if c is not None else math.nan for c in cells)
                if not (math.isfinite(a) and math.isfinite(u)):
                    raise ValueError
            except ValueError:
                spec = self.spec()
                if spec is not None:
                    self._fill_cap_shape(spec, True)
                return
            points.append([round(a, 5), round(u, 5)])
        self._cap_value("points", points, live=False)

    def add_cap_point(self) -> bool:
        """Add a corner to the polygon cap halfway along its last edge."""
        data = self._cap_data()
        if data is None or data.get("kind") != "polygon":
            return False
        pts = data["points"]
        a, b = pts[-1], pts[0]
        data["points"] = [*pts, [round(0.5 * (a[0] + b[0]), 5), round(0.5 * (a[1] + b[1]), 5)]]
        return self.set_crown_shape(data)

    def remove_cap_point(self) -> bool:
        """Remove the selected corner of the polygon cap (or its last one)."""
        data = self._cap_data()
        if data is None or data.get("kind") != "polygon" or len(data["points"]) <= 3:
            return False
        row = self.cap_points.currentRow()
        pts = list(data["points"])
        pts.pop(row if 0 <= row < len(pts) else -1)
        data["points"] = pts
        return self.set_crown_shape(data)

    def _fill_meeting(self, spec: ShapeSpec, capped: bool, mesh: bool = False) -> None:
        """Show where ``spec``'s panels meet (pad, numbers and the distance it means)."""
        from envelopelab.features.primitives import crown_seam_angles
        from envelopelab.project.shapes import meeting_point, to_primitive

        try:
            across, up = meeting_point(spec)
            prim: Any = to_primitive(spec)
            seams = [float(a) for a in crown_seam_angles(prim)[:-1]]
            shift = float(getattr(prim, "cap_shift", 0.0))
        except (PrimitiveError, ValueError):
            across, up, seams, shift = 0.0, 0.0, [], 0.0
        for box, value in ((self.cap_across, across), (self.cap_up, up)):
            box.blockSignals(True)
            box.setValue(value)
            box.blockSignals(False)
        self.meeting_pad.set_state(across, up, seams)
        self.meeting_pad.set_cap(self._cap_view(spec))
        for widget in (self.meeting_pad, self.cap_across, self.cap_up, self.meeting_centre):
            widget.setEnabled(capped)
        if not capped:
            self.meeting_info.setText("At the tip (the shape has no cap).")
        elif mesh:
            self.meeting_info.setText(
                "The seams are cut about the line through this point (along the shape's "
                "axis); the panels meet where it leaves the mesh."
                if across or up
                else "At the top, where the shape's axis leaves the mesh."
            )
        elif shift > 0.0:
            self.meeting_info.setText(
                f"The cap's centre is {shift * 1000.0:.0f} mm down the skin from the tip."
            )
        else:
            self.meeting_info.setText("At the tip.")

    def _cap_view(self, spec: ShapeSpec) -> np.ndarray | None:
        from envelopelab.project.shapes import crown_view

        shown = self.controller.shapes.shown(spec.name)
        try:
            out: np.ndarray | None = crown_view(spec, None if shown is None else shown.design)
        except (PrimitiveError, ValueError):
            return None
        return out

    def _meeting_dragged(self, across: float, up: float) -> None:
        for box, value in ((self.cap_across, across), (self.cap_up, up)):
            box.blockSignals(True)
            box.setValue(value)
            box.blockSignals(False)
        self.set_meeting_point(across, up, live=True)

    def _meeting_typed(self, _value: float) -> None:
        across, up = float(self.cap_across.value()), float(self.cap_up.value())
        h = math.hypot(across, up)
        if h > 1.0:  # keep it inside the outline: shorten towards the tip
            across, up = round(across / h, 3), round(up / h, 3)
        self.meeting_pad.set_state(across, up, self.meeting_pad.seams)
        self.set_meeting_point(across, up, live=True)

    def set_meeting_point(self, across: float, up: float, live: bool = False) -> bool:
        """Put the point where the selected shape's panels meet at plan fractions
        (``across``, ``up``) of its widest radius, seen from above (ADR-0052); one undo
        step for a drag or a held value (``live``). True when applied (or queued)."""
        name = self.selected
        spec = self.spec()
        if name is None or spec is None:
            return False
        values = {"cap_across": float(across), "cap_up": float(up), "cap_shift": 0.0}
        if (spec.cap_across, spec.cap_up, spec.cap_shift) == (across, up, 0.0):
            return False
        if live:
            self.controller.edit_live(
                f"shape:{name}:meeting",
                lambda: self.controller.edit("update_shape", name, values),
            )
            return True
        ok = bool(self.controller.edit("update_shape", name, values))
        if not ok:
            self.refresh()
        return ok

    def _crown_own_toggled(self, on: bool) -> None:
        spec = self.spec()
        if spec is None or self._crown_filling:
            return
        if on:
            self.set_value(("crown_seam_offset_deg",), float(spec.seam_offset_deg))
        else:
            values: dict[str, Any] = {"crown_seam_offset_deg": None, "crown_panel_widths": []}
            if self.selected is not None:
                self.controller.edit("update_shape", self.selected, values)

    def set_crown_widths(self, widths: list[float] | None) -> bool:
        """Set the relative widths of the pieces at the crown (None: all equal there)."""
        spec = self.spec()
        if spec is None:
            return False
        values = [1.0] * piece_count(spec) if widths is None else [float(w) for w in widths]
        return self.set_value(("crown_panel_widths",), values)

    def _crown_width_edited(self, item: QTableWidgetItem) -> None:
        spec = self.spec()
        if spec is None or item.column() != 0:
            return
        count = piece_count(spec)
        widths = list(spec.crown_panel_widths or spec.panel_widths or [1.0] * count)
        try:
            widths[item.row()] = float(item.text())
        except ValueError:
            self._fill_crown(spec)
            return
        if not self.set_crown_widths(widths):
            self._fill_crown(spec)

    def _fill_crown(self, spec: ShapeSpec) -> None:
        """Show where ``spec``'s panels meet at the crown."""
        self._crown_filling = True
        try:
            mesh = isinstance(spec, MeshShape)
            own = spec.crown_seam_offset_deg is not None or bool(spec.crown_panel_widths)
            self.crown_own.setChecked(own)
            self.crown_own.setEnabled(not mesh)
            count = piece_count(spec)
            widths = spec.crown_panel_widths or spec.panel_widths or [1.0] * count
            total = sum(widths)
            self.crown_turn.blockSignals(True)
            self.crown_turn.setValue(
                spec.seam_offset_deg
                if spec.crown_seam_offset_deg is None
                else spec.crown_seam_offset_deg
            )
            self.crown_turn.blockSignals(False)
            self.crown_widths_table.blockSignals(True)
            self.crown_widths_table.setRowCount(count)
            self.crown_widths_table.setVerticalHeaderLabels([str(k + 1) for k in range(count)])
            for k, w in enumerate(widths):
                self.crown_widths_table.setItem(k, 0, QTableWidgetItem(f"{w:g}"))
                span = QTableWidgetItem(f"{360.0 * w / total:.1f}°")
                span.setFlags(span.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.crown_widths_table.setItem(k, 1, span)
            self.crown_widths_table.blockSignals(False)
            for widget in (self.crown_turn, self.crown_widths_table):
                widget.setEnabled(own and not mesh)
            capped = (
                isinstance(spec, DomeShape | RevolvedShape)
                and pointed(spec)
                and cap_diameter(spec) > 0.0
            )
            self._fill_meeting(spec, capped or mesh, mesh)
            self._fill_cap_shape(spec, capped or (mesh and cap_diameter(spec) > 0.0))
            notes = []
            if mesh:
                notes.append(
                    "A mesh shape's seams are cut straight from the rim to where the panels "
                    "meet; their turn and widths at the crown stay as at the rim."
                )
            elif own:
                notes.append(
                    "The seams turn smoothly from the rim to these angles above the "
                    "footprint; the Checks tab says how much the pieces are distorted."
                )
            if not capped and not mesh:
                notes.append(
                    "Moving where the panels meet needs a dome or revolved shape with a cap: "
                    "the panels meet round its edge (Feed holes & cap)."
                )
            self.crown_note.setText(" ".join(notes))
        finally:
            self._crown_filling = False

    def _forget_edited_piece(self) -> None:
        """Another shape is selected: no piece of it is being edited yet."""
        self.edited_piece = None
        self.preview.edited = None
        self.meeting_pad.set_edited(None)
        for table in (self.widths_table, self.crown_widths_table):
            table.blockSignals(True)
            table.setCurrentCell(-1, -1)
            table.blockSignals(False)

    def set_edited_piece(self, piece: int | None) -> None:
        """Highlight gore or panel ``piece`` (0-based) of the selected shape as the one
        being edited: amber on the balloon, in the cut pieces and in the meeting pad."""
        spec = self.spec()
        if spec is None or piece is None or not 0 <= piece < piece_count(spec):
            piece = None
        changed = piece != self.edited_piece
        self.edited_piece = piece
        self.preview.edited = piece
        self.preview.update()
        self.meeting_pad.set_edited(piece)
        self.split_piece_button.setEnabled(
            piece is not None and spec is not None and piece_count(spec) < MAX_PIECES
        )
        if changed and self.placement.data.sketch is not None:
            self.placement.data.edited_piece = piece
            self.placement.set_data(self.placement.data)

    def split_piece(self, piece: int | None) -> bool:
        """Split gore or panel ``piece`` (0-based) of the selected shape into two of half
        its width, every other seam in place (:func:`envelopelab.project.shapes.
        split_piece`); one undo step. The first half stays highlighted."""
        from envelopelab.project.shapes import split_piece

        name, spec = self.selected, self.spec()
        if name is None or spec is None or piece is None:
            return False
        try:
            values = split_piece(spec, piece)
        except ValueError:
            return False
        if not self.controller.edit("update_shape", name, values):
            self.refresh()
            return False
        self.widths_table.setCurrentCell(piece, 0)
        self.set_edited_piece(piece)
        return True

    def set_panel_widths(self, widths: list[float]) -> bool:
        """Set the relative widths of the gores or panels (empty: all equal)."""
        return self.set_value(("panel_widths",), [float(w) for w in widths])

    def set_splits(self, fractions: list[float]) -> bool:
        """Set the horizontal splits (fractions of the profile, sorted here)."""
        return self.set_value(("splits",), sorted(round(float(f), 4) for f in fractions))

    def add_split(self) -> bool:
        """Add a horizontal split in the middle of the tallest tier."""
        spec = self.spec()
        if spec is None or isinstance(spec, MeshShape):
            return False
        edges = [0.0, *spec.splits, 1.0]
        gaps = [b - a for a, b in zip(edges, edges[1:], strict=False)]
        i = gaps.index(max(gaps))
        return self.set_splits([*spec.splits, round(0.5 * (edges[i] + edges[i + 1]), 3)])

    def remove_split(self) -> bool:
        """Remove the selected horizontal split (the top one when none is selected)."""
        spec = self.spec()
        if spec is None or not spec.splits:
            return False
        row = self.splits_table.currentRow()
        row = row if 0 <= row < len(spec.splits) else len(spec.splits) - 1
        return self.set_splits([f for i, f in enumerate(spec.splits) if i != row])

    def _width_edited(self, item: QTableWidgetItem) -> None:
        spec = self.spec()
        if spec is None or item.column() != 0:
            return
        widths = list(spec.panel_widths or [1.0] * piece_count(spec))
        try:
            widths[item.row()] = float(item.text())
        except ValueError:
            self._fill_layout(spec)
            return
        if not self.set_panel_widths(widths):
            self._fill_layout(spec)

    def _split_edited(self, item: QTableWidgetItem) -> None:
        spec = self.spec()
        if spec is None:
            return
        splits = list(spec.splits)
        try:
            splits[item.row()] = float(item.text()) / 100.0
        except ValueError:
            self._fill_layout(spec)
            return
        if not self.set_splits(splits):
            self._fill_layout(spec)

    def _holes(self) -> list[dict[str, Any]]:
        spec = self.spec()
        return [] if spec is None else [h.model_dump(mode="json") for h in spec.feed_holes]

    def add_feed_hole(self) -> bool:
        """Add a feed hole at the shape's base point (100 mm radius) to edit."""
        spec = self.spec()
        if spec is None:
            return False
        hole = {
            "gore": spec.placement.gore,
            "tape_position": spec.placement.tape_position,
            "across": spec.placement.across,
            "radius": 0.1,
        }
        return self.set_value(("feed_holes",), [*self._holes(), hole])

    def move_holes_clear(self) -> list[str] | None:
        """Move every shape's extra feed holes clear of their panels' seams (one undo step);
        returns what was done, None when refused (e.g. a shape is still being placed)."""
        session = self.controller.session
        if session is None:
            return None
        placed = {}
        for spec in session.state.shapes:
            design = self.placed(spec.name)
            if design is None:
                self.controller.editRejected.emit(
                    f"feed holes not moved: shape {spec.name} is not placed yet"
                )
                return None
            placed[spec.name] = design
        notes = self.controller.edit("move_feed_holes_clear", placed)
        if notes is None:
            return None
        self.controller.message.emit(
            "; ".join(notes) if notes else "Every feed hole is clear of the seams."
        )
        return list(notes)

    def remove_feed_hole(self, index: int) -> bool:
        """Remove extra feed hole ``index``."""
        holes = self._holes()
        if not 0 <= index < len(holes):
            return False
        del holes[index]
        return self.set_value(("feed_holes",), holes)

    def _remove_feed_hole(self) -> None:
        rows = self.holes_table.selectionModel().selectedRows()
        if rows:
            self.remove_feed_hole(rows[0].row())

    def _hole_edited(self, item: QTableWidgetItem) -> None:
        holes = self._holes()
        if item.row() >= len(holes):
            return
        key = ("gore", "tape_position", "across", "radius")[item.column()]
        try:
            value: float | int = int(item.text()) if key == "gore" else float(item.text())
        except ValueError:
            self.controller.editRejected.emit(f"{key}: not a number: {item.text()!r}")
            self._update_form(self.spec())
            return
        holes[item.row()][key] = value
        if not self.set_value(("feed_holes",), holes):
            self._update_form(self.spec())

    def _cap_toggled(self, on: bool) -> None:
        spec = self.spec()
        if spec is None:
            return
        # Leaving automatic keeps the automatic diameter as the starting value.
        self.set_value(("cap_diameter",), None if on else auto_cap_diameter(spec))

    def _feed_toggled(self, on: bool) -> None:
        spec = self.spec()
        if spec is None:
            return
        radius = None
        if on:
            base = getattr(spec, "base_radius", None)
            radius = round(0.4 * base, 3) if base else 0.1
        self.set_value(("feed_hole_radius",), radius)

    def _profile_points(self) -> list[list[float]] | None:
        points = []
        for i in range(self.profile_table.rowCount()):
            cells = (self.profile_table.item(i, 0), self.profile_table.item(i, 1))
            if cells[0] is None or cells[1] is None:
                return None
            try:
                rho, zeta = float(cells[0].text()), float(cells[1].text())
            except ValueError:
                return None
            points.append([rho, zeta])
        return points

    def _profile_edited(self, _item: QTableWidgetItem) -> None:
        points = self._profile_points()
        if points is None:
            self.controller.editRejected.emit("profile points must be numbers (m)")
            self._update_form(self.spec())
            return
        if not self.set_value(("profile",), points):
            self._update_form(self.spec())

    def _add_profile_point(self) -> None:
        spec = self.spec()
        if not isinstance(spec, RevolvedShape):
            return
        points = [list(p) for p in spec.profile]
        row = max(self.profile_table.currentRow(), 0)
        row = min(row, len(points) - 2)
        a, b = points[row], points[row + 1]
        points.insert(row + 1, [0.5 * (a[0] + b[0]), 0.5 * (a[1] + b[1])])
        self.set_value(("profile",), points)

    def _remove_profile_point(self) -> None:
        spec = self.spec()
        row = self.profile_table.currentRow()
        if not isinstance(spec, RevolvedShape) or row < 0 or len(spec.profile) <= 2:
            return
        points = [list(p) for i, p in enumerate(spec.profile) if i != row]
        self.set_value(("profile",), points)

    def _show_result(self, spec: ShapeSpec | None) -> None:
        self.checks.clear()
        self.pieces.clear()
        self.attachment.clear()
        self.preview.set_pieces([])
        self.markings.set_sheets([])
        self.marking_notes.clear()
        if spec is None:
            text = "No special shapes. Add a dome, a tube, a revolved profile or a mesh."
            self.status.setText(text if self.controller.is_gore else "")
            self.status.setStyleSheet("")
            return
        result = self.controller.shapes.result(spec.name)
        if result is None:
            updating = self.controller.shapes.updating(spec.name)
            self.status.setText(
                f"{spec.name}: updating… (the views show it as last placed)"
                if updating
                else f"{spec.name}: being placed…"
            )
            self.status.setStyleSheet("")
            return
        design = result.design
        if design is None:
            self.status.setText(f"{spec.name} CANNOT BE PLACED: {result.error}")
            self.status.setStyleSheet(f"color: {FAIL_COLOR}; font-weight: bold;")
            return
        checks = self.controller.shape_checks(spec.name)
        failed = [c for c in checks if c.severity != "info"]
        if failed:
            worst = "error" if any(c.severity == "error" for c in failed) else "warning"
            self.status.setText(
                f"{spec.name}: {len(failed)} check(s) need attention; see the list."
            )
            self.status.setStyleSheet(f"color: {SEVERITY_COLORS[worst]}; font-weight: bold;")
        else:
            self.status.setText(
                f"{spec.name}: placed; {len(design.pieces)} cut piece(s), footprint "
                f"{design.footprint_length:.3f} m, designed height {design.designed_height:.3f} m"
            )
            self.status.setStyleSheet(f"color: {OK_COLOR};")
        if self.controller.defer_hidden and self.result_tabs.currentWidget() is self.placement:
            # The other result tabs are hidden: fill them when one is shown.
            self._results_stale = True
            return
        self._results_stale = False
        for check in checks:
            item = QTreeWidgetItem(
                [
                    check.name,
                    f"{check.value:.4g} {check.unit}",
                    f"{check.limit:.4g} {check.unit}",
                    "passed" if check.passed else check.severity.upper(),
                ]
            )
            item.setToolTip(0, check.message)
            item.setForeground(3, QBrush(QColor(SEVERITY_COLORS[check.severity])))
            self.checks.addTopLevelItem(item)
        roll = self.controller.prefs.print_roll_width
        oversize: set[str] = set()
        for piece in design.pieces:
            w, h = piece.size
            fit = roll_fit(piece.cut, roll)
            if fit.oversize:
                oversize.add(piece.label)
                on_roll = f"LARGER THAN {roll * 1000:.0f} mm ROLL"
            else:
                on_roll = f"{fit.across * 1000:.0f} mm across, {fit.describe()}"
            item = QTreeWidgetItem(
                [
                    piece.label,
                    str(piece.cut_count),
                    f"{w:.3f} × {h:.3f}",
                    f"{piece.flat_area:.4f}",
                    f"{piece.surface_area:.4f}",
                    on_roll,
                ]
            )
            item.setToolTip(
                5,
                f"1:1 page {fit.across * 1000:.0f} mm across the roll × "
                f"{fit.along * 1000:.0f} mm along it (cut line + margin), piece "
                f"{fit.describe()}",
            )
            if fit.oversize:
                item.setForeground(5, QBrush(QColor(WARN_COLOR)))
            self.pieces.addTopLevelItem(item)
        for column in range(self.pieces.columnCount()):
            self.pieces.resizeColumnToContents(column)
        for tree in (self.pieces, self.checks, self.attachment):
            for column in range(tree.columnCount()):
                tree.resizeColumnToContents(column)
        for line in design.attachment:
            length = float(np.linalg.norm(np.diff(line.points, axis=0), axis=1).sum())
            self.attachment.addTopLevelItem(
                QTreeWidgetItem([f"gore {line.gore}, row {line.row}", f"{length:.3f}"])
            )
        for tree in (self.pieces, self.checks, self.attachment):
            for column in range(tree.columnCount()):
                tree.resizeColumnToContents(column)
        self.preview.set_pieces(design.pieces, frozenset(oversize), roll)
        self._show_markings(design)

    def _show_markings(self, design: Any) -> None:
        """The envelope panels ``design`` (a placed shape) is sewn on, and per row which
        gores they are (:mod:`envelopelab.export.build_pack`)."""
        from envelopelab.export.build_pack import (
            default_hole_hem,
            primitive_sheets,
            shape_row_notes,
        )

        session = self.controller.session
        if session is None:
            return
        hem, tape = default_hole_hem(session.design)
        sheets = [
            s for s in primitive_sheets(design, "skin", None, hem, tape) if s.kind == "marking"
        ]
        stale = self.controller.artifact_status("patterns") == "stale"
        self.markings.set_sheets(sheets, stale)
        notes = [
            f"Row {row}: {note}"
            for row, row_notes in shape_row_notes([design]).items()
            for note in row_notes
        ]
        lines = [f"{len(sheets)} envelope panel(s) to mark."] if sheets else []
        if stale:
            lines.append("Patterns are STALE: regenerate them before marking (shown greyed).")
        self.marking_notes.setText("\n".join(lines + notes))

    def _show_simulation(self, spec: ShapeSpec | None) -> None:
        self.sim_tree.clear()
        service = self.controller.shapes
        sim = None if spec is None else service.simulations.get(spec.name)
        if self.controller.shape_simulator.running:
            return
        if spec is None or sim is None:
            self.sim_status.setText("Not simulated.")
            self.sim_status.setStyleSheet("")
            return
        m = sim.record
        stale = service.simulation_status(spec.name) == "stale"
        problems = []
        if not m.converged:
            problems.append(f"NOT CONVERGED ({m.status}): results are not final")
        if stale:
            problems.append("STALE: the shape or the envelope changed since this solve")
        low = {k: v for k, v in m.fos.items() if v < REQUIRED_FOS}
        if low:
            problems.append(f"FACTOR OF SAFETY BELOW {REQUIRED_FOS:g}")
        solver = SOLVER_LABELS.get(m.solver, m.solver)
        origin = " with the envelope run" if m.envelope_run_id else ""
        if problems:
            self.sim_status.setText(f"{solver}{origin}: " + "; ".join(problems))
            self.sim_status.setStyleSheet(f"color: {FAIL_COLOR}; font-weight: bold;")
        elif m.solver == "calculix":
            self.sim_status.setText(f"{solver}{origin}: converged (stiffness values are assumed)")
            self.sim_status.setStyleSheet(f"color: {OK_COLOR};")
        else:
            self.sim_status.setText(
                f"{solver}{origin}: converged (preview stiffness values are assumed; not "
                "verified with CalculiX)"
            )
            self.sim_status.setStyleSheet(f"color: {OK_COLOR};")
        v = m.metrics
        rows = [
            ("Status", m.status),
            ("Iterations", str(m.iterations)),
            (f"Final residual ({m.residual_measure})", f"{m.residual:.2e}"),
            (
                "Mesh",
                f"{m.n_nodes} nodes, {m.n_elements} elements (target {m.mesh_target_mm:g} mm)",
            ),
            ("Run time", f"{m.run_time:.1f} s"),
            ("Solved", m.created.strftime("%Y-%m-%d %H:%M UTC")),
            ("Height above envelope (designed)", f"{v['initial_projected_height_m']:.3f} m"),
            ("Height above envelope (inflated)", f"{v['projected_height_m']:.3f} m"),
            ("Chamber pressure", f"{v['chamber_pressure_pa']:.1f} Pa"),
            ("Skin wrinkled", f"{100 * v['skin_wrinkled_fraction']:.0f} %"),
            ("Rim tape max tension", f"{v['rim_tape_max_tension_n']:.0f} N"),
            (
                "Footprint max normal movement",
                f"{1000 * v['footprint_max_normal_displacement_m']:.1f} mm",
            ),
        ]
        for region, fos in sorted(m.fos.items()):
            rows.append((f"FoS {region}", f"{fos:.2f}" + ("  FAILS" if fos < REQUIRED_FOS else "")))
        for label, value in rows:
            item = QTreeWidgetItem([label, value])
            if "FAILS" in value or (label == "Status" and not m.converged):
                item.setForeground(1, QBrush(QColor(FAIL_COLOR)))
            self.sim_tree.addTopLevelItem(item)

    def messages(self) -> list[str]:
        """Status texts as shown (for tests)."""
        return [self.status.text(), self.sim_status.text()]
