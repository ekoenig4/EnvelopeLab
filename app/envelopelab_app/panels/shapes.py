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
the panel says "being placed…" until the result arrives.

Nothing is hidden: a shape that cannot be placed, a failed check, an unconverged or
stale simulation and a factor of safety below the requirement are shown in red here and
listed in the Validation panel. Lengths are shown in m, angles in degrees.
"""

from __future__ import annotations

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
from envelopelab.export.templates import roll_fit
from envelopelab.features.metrics import REQUIRED_FOS
from envelopelab.features.primitives import CutPiece, PrimitiveDesign
from envelopelab.project.model import SOLVER_LABELS
from envelopelab.project.shape_groups import group_names
from envelopelab.project.shapes import (
    CAP_PANEL_TOP_WIDTH,
    MeshShape,
    RevolvedShape,
    ShapeKind,
    ShapePlacement,
    ShapeSpec,
    auto_cap_diameter,
    cap_diameter,
    default_shape,
    mesh_shape,
    piece_count,
    pointed,
    shape_fabrics,
)
from envelopelab_app.controller import WorkspaceController
from envelopelab_app.marking_view import MarkingView
from envelopelab_app.refresh import Refresher

FAIL_COLOR = "#b00020"
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


def _scrolled(page: QWidget) -> QScrollArea:
    """``page`` in a frameless scroll area (a tab scrolls instead of squeezing its rows)."""
    area = QScrollArea()
    area.setWidget(page)
    area.setWidgetResizable(True)
    area.setFrameShape(QScrollArea.Shape.NoFrame)
    return area


class PiecePreview(QWidget):
    """Draws the cut pieces of a shape side by side (finished line solid, cut line dashed).

    A piece whose 1:1 page is wider than the print roll both ways (``oversize``) is filled
    in the warning colour and labelled so. The mouse wheel zooms about the pointer,
    dragging pans and a double click fits every piece again.
    """

    #: Zoom step per wheel notch, and the zoom range (1: every piece fits).
    ZOOM_STEP = 1.25
    ZOOM_RANGE = (1.0, 200.0)

    def __init__(self) -> None:
        super().__init__()
        self.pieces: list[CutPiece] = []
        self.oversize: frozenset[str] = frozenset()
        self.zoom = 1.0
        self.pan = QPointF(0.0, 0.0)
        self._drag: QPointF | None = None
        self.setMinimumHeight(160)
        self.setToolTip("Mouse wheel: zoom; drag: pan; double click: fit all pieces")

    def set_pieces(self, pieces: list[CutPiece], oversize: frozenset[str] = frozenset()) -> None:
        """Show these pieces (m), those labelled in ``oversize`` as larger than the roll;
        the view fits them again when the set of pieces changes."""
        if [p.label for p in pieces] != [p.label for p in self.pieces]:
            self.reset_view()
        self.pieces = pieces
        self.oversize = oversize
        self.update()

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
        if event.button() == Qt.MouseButton.LeftButton:
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
        offsets, width, height = self.layout_offsets()
        margin = self._margin
        scale = self.zoom * min(
            (self.width() - 2 * margin) / max(width, 1e-9),
            (self.height() - 2 * margin) / max(height, 1e-9),
        )
        px, py = self.pan.x(), self.pan.y()

        def polygon(points: np.ndarray, offset: np.ndarray) -> QPolygonF:
            p = (points + offset) * scale
            return QPolygonF(
                [QPointF(margin + px + x, self.height() - margin + py - y) for x, y in p.tolist()]
            )

        for piece, offset in zip(self.pieces, offsets, strict=True):
            path = QPainterPath()
            path.addPolygon(polygon(piece.finished, offset))
            path.closeSubpath()
            big = piece.label in self.oversize
            painter.fillPath(path, QBrush(QColor(OVERSIZE_FILL if big else "#e8eef7")))
            painter.setPen(QPen(QColor("#1f3b73"), 1.5))
            painter.drawPolygon(polygon(piece.finished, offset))
            pen = QPen(QColor("#555555"), 1.0)
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawPolygon(polygon(piece.cut, offset))
            if piece.rim is not None:
                painter.setPen(QPen(QColor(FAIL_COLOR), 2.0))
                painter.drawPolyline(polygon(piece.rim, offset))
            # The piece's short name under it (the part after the shape name).
            label = piece.label.rsplit("-", 1)[-1]
            if big:
                label += " ▲ larger than roll"
            box = polygon(piece.cut, offset).boundingRect()
            painter.setPen(QPen(QColor(WARN_COLOR if big else "#333333")))
            painter.drawText(
                QPointF(box.center().x() - 4.0 * len(label), box.bottom() - 4.0)
                if box.height() > 30.0
                else box.bottomLeft(),
                label,
            )


class ShapesPanel(QWidget):
    """See module docstring."""

    #: The user wants to drag shape ``name`` in the 3D view (the main window shows it).
    dragRequested = Signal(str)  # noqa: N815 (Qt naming)
    #: The Export build pack… button: the main window opens its export dialog.
    exportRequested = Signal()  # noqa: N815 (Qt naming)

    def __init__(self, controller: WorkspaceController) -> None:
        super().__init__()
        self.controller = controller
        self.selected: str | None = None
        self.mesh_mm = DEFAULT_MESH_MM
        self._form_key: tuple[str, str, int] | None = None
        self.fields: dict[tuple[str, ...], QSpinBox | QDoubleSpinBox] = {}

        # -- shape list ------------------------------------------------------------------
        self.add_button = QToolButton()
        self.add_button.setText("Add shape")
        self.add_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.add_button)
        for kind in ("dome", "tube", "revolved"):
            menu.addAction(KIND_LABELS[kind], self._adder(kind))
        menu.addAction("Import mesh (OBJ/STL/PLY)…", self._import_mesh_dialog)
        self.add_button.setMenu(menu)
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
            "far round from the direction up the tape (0°), towards the next gore (90°)"
        )
        self.seam_turn.valueChanged.connect(
            lambda v: self.set_value(("seam_offset_deg",), round(float(v), 1))
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
        equal = QPushButton("Equal widths")
        equal.setObjectName("shapeEqualWidths")
        equal.clicked.connect(lambda: self.set_value(("panel_widths",), []))
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
        layout_form.addRow("Seam turn", self.seam_turn)
        widths = QVBoxLayout()
        widths.addWidget(self.widths_table)
        widths.addWidget(equal)
        layout_form.addRow("Panel widths", widths)
        splits = QVBoxLayout()
        splits.addWidget(self.splits_table)
        split_buttons = QHBoxLayout()
        split_buttons.addWidget(self.add_split_button)
        split_buttons.addWidget(self.remove_split_button)
        splits.addLayout(split_buttons)
        layout_form.addRow("Horizontal splits", splits)
        layout_form.addRow(self.layout_note)

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
            "Mirror the group about a gore line: add a mirrored copy of every shape (the "
            "other side of a face) or mirror the shapes in place (one undo step)"
        )
        self.mirror_group_button.clicked.connect(self._mirror_group_dialog)
        self.export_group_button = QPushButton("Export group to Blender…")
        self.export_group_button.clicked.connect(self._export_group_dialog)
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
            self.remove_button,
            self.move_group_button,
            self.mirror_group_button,
            self.export_group_button,
            self.export_pack_button,
            self.export_blender_button,
        ):
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            left_layout.addWidget(button)

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
        middle_layout.addWidget(self.editor_tabs, 1)

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
        drawing_layout.addWidget(self.preview, 1)
        pieces_split.addWidget(drawing)
        pieces_split.addWidget(self.pieces)
        pieces_split.setStretchFactor(0, 3)
        pieces_split.setStretchFactor(1, 1)
        self.result_tabs.addTab(pieces_split, "Cut pieces")
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

    # -- edits --------------------------------------------------------------------------

    def select(self, name: str | None) -> None:
        """Select a shape by name."""
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
        """Copy the selected shape one gore further round."""
        if self.selected is None:
            return None
        new = self.controller.edit("duplicate_shape", self.selected)
        if new:
            self.select(new)
        return new  # type: ignore[no-any-return]

    def remove_selected(self) -> None:
        """Remove the selected shape."""
        if self.selected is not None and self.controller.edit("remove_shape", self.selected):
            self.selected = None
            self.refresh()

    def set_value(self, path: tuple[str, ...], value: Any) -> bool:
        """Change one value of the selected shape (undoable)."""
        if self.selected is None:
            return False
        spec = self.spec()
        if spec is not None and _get(spec.model_dump(mode="json"), path) == value:
            return False
        old = self.selected
        if path == ("name",):
            # Selected under its new name before the edit refreshes the panel.
            self.selected = str(value)
        values = _values(path, value)
        if spec is not None and path in (("gores",), ("panels",)) and spec.panel_widths:
            # Keep the widths given and make the new pieces as wide as the last one.
            count = int(value)
            widths = list(spec.panel_widths)[:count]
            values["panel_widths"] = widths + [widths[-1]] * (count - len(widths))
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
        if self.selected is not None:
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
        names = [s.name for s in specs]
        if self.selected not in names:
            self.selected = names[0] if names else None
        self.list.blockSignals(True)
        self.list.clear()
        for spec in specs:
            prefix = f"{spec.group} ▸ " if spec.group else ""
            item = QListWidgetItem(f"{prefix}{spec.name}  ({KIND_LABELS[spec.kind]})")
            item.setData(Qt.ItemDataRole.UserRole, spec.name)
            colour = self._state_colour(spec.name)
            if colour:
                item.setForeground(QBrush(QColor(colour)))
            self.list.addItem(item)
            if spec.name == self.selected:
                self.list.setCurrentItem(item)
        self.list.blockSignals(False)
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
            self.selected = str(item.data(Qt.ItemDataRole.UserRole))
            self._show_selected()

    def _show_selected(self) -> None:
        spec = self.spec()
        self._update_form(spec)
        self._show_result(spec)
        self._show_simulation(spec)
        self._update_buttons()

    def _update_buttons(self) -> None:
        has = self.spec() is not None
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
            box.valueChanged.connect(lambda v, p=field.path: self.set_value(p, v))
            self.fields[field.path] = box
            self.form.addRow(field.label, box)
        self.feed_check = QCheckBox("Feed hole in the envelope")
        self.feed_radius = QDoubleSpinBox()
        self.feed_radius.setDecimals(3)
        self.feed_radius.setRange(0.001, 100.0)
        self.feed_radius.setSingleStep(0.01)
        self.feed_radius.setKeyboardTracking(False)
        self.feed_check.toggled.connect(self._feed_toggled)
        self.feed_radius.valueChanged.connect(
            lambda v: self.set_value(("feed_hole_radius",), float(v))
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
            lambda v: self.set_value(("cap_diameter",), float(v))
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

    def mirror_group(self, line: float, copy: bool = True, group: str | None = None) -> bool:
        """Mirror ``group`` (default: the selected shape's) about the gore line ``line``
        (gore position: gore n's centreline is n - 0.5, the seam after it n): a mirrored
        copy of every shape off the line, or the shapes in place (one undo step)."""
        group = group or self.group()
        if group is None:
            return False
        before = self.controller.revision
        out = self.controller.edit("mirror_shape_group", group, line, copy)
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
        spec = self.spec()
        if spec is None:
            return
        here = spec.placement.gore + spec.placement.across  # gore line through the base
        values = _ask(
            self,
            f"Mirror group {self.group()}",
            [("Mirror line (gore: 6 = centre of gore 6, 6.5 = seam 6|7)", 0.5, 999.0, here, 2)],
            "Add a mirrored copy (untick: mirror in place)",
        )
        if values is not None:
            line, copy = values[0] - 0.5, bool(values[1])
            self.mirror_group(line, copy)

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
            self.status.setText(f"{spec.name}: being placed…")
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
                on_roll = "fits turned" if fit.turned else "fits"
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
                5, f"page {fit.width * 1000:.0f} × {fit.height * 1000:.0f} mm (cut line + margin)"
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
        self.preview.set_pieces(design.pieces, frozenset(oversize))
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
