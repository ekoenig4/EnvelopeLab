"""Special shapes panel: domes, tubes, revolved and imported mesh shapes on the envelope.

The panel lists the project's special shapes, edits the selected one (every change is one
undoable edit of the design state), and shows what :mod:`envelopelab.features.primitives`
derives from it: the pattern checks, the cut pieces (with a drawing of their outlines),
the attachment lines on the envelope panels, and the result of a shape simulation with
the preview solver. Placing a shape runs in a worker thread
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
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from envelopelab.features.metrics import REQUIRED_FOS
from envelopelab.features.primitives import CutPiece, PrimitiveDesign
from envelopelab.project.shapes import (
    MeshShape,
    RevolvedShape,
    ShapeKind,
    ShapePlacement,
    ShapeSpec,
    default_shape,
    mesh_shape,
    shape_fabrics,
)
from envelopelab_app.controller import WorkspaceController
from envelopelab_app.refresh import Refresher
from envelopelab_app.shapes_service import ShapeSolveRequest

FAIL_COLOR = "#b00020"
WARN_COLOR = "#8a6d3b"
OK_COLOR = "#2e7d32"
SEVERITY_COLORS = {"error": FAIL_COLOR, "warning": WARN_COLOR, "info": "#31708f"}
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


class PiecePreview(QWidget):
    """Draws the cut pieces of a shape side by side (finished line solid, cut line dashed)."""

    def __init__(self) -> None:
        super().__init__()
        self.pieces: list[CutPiece] = []
        self.setMinimumHeight(160)

    def set_pieces(self, pieces: list[CutPiece]) -> None:
        """Show these pieces (m)."""
        self.pieces = pieces
        self.update()

    def layout_offsets(self) -> tuple[list[np.ndarray], float, float]:
        """x offset per piece (m), the total width and the height of the row (m)."""
        offsets, x, height = [], 0.0, 0.0
        for piece in self.pieces:
            lo, hi = piece.cut.min(axis=0), piece.cut.max(axis=0)
            offsets.append(np.array([x - lo[0], -lo[1]]))
            gap = 0.1 * (hi[0] - lo[0])
            x += hi[0] - lo[0] + gap
            height = max(height, float(hi[1] - lo[1]))
        return offsets, x, height

    def paintEvent(self, _event: object) -> None:  # noqa: N802 (Qt API)
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("white"))
        if not self.pieces:
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No cut pieces")
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        offsets, width, height = self.layout_offsets()
        margin = 8.0
        scale = min(
            (self.width() - 2 * margin) / max(width, 1e-9),
            (self.height() - 2 * margin) / max(height, 1e-9),
        )

        def polygon(points: np.ndarray, offset: np.ndarray) -> QPolygonF:
            p = (points + offset) * scale
            return QPolygonF(
                [QPointF(margin + x, self.height() - margin - y) for x, y in p.tolist()]
            )

        for piece, offset in zip(self.pieces, offsets, strict=True):
            path = QPainterPath()
            path.addPolygon(polygon(piece.finished, offset))
            path.closeSubpath()
            painter.fillPath(path, QBrush(QColor("#e8eef7")))
            painter.setPen(QPen(QColor("#1f3b73"), 1.5))
            painter.drawPolygon(polygon(piece.finished, offset))
            pen = QPen(QColor("#555555"), 1.0)
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawPolygon(polygon(piece.cut, offset))
            if piece.rim is not None:
                painter.setPen(QPen(QColor(FAIL_COLOR), 2.0))
                painter.drawPolyline(polygon(piece.rim, offset))


class ShapesPanel(QWidget):
    """See module docstring."""

    #: The user wants to drag shape ``name`` in the 3D view (the main window shows it).
    dragRequested = Signal(str)  # noqa: N815 (Qt naming)

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
        self.list.setMaximumHeight(140)
        self.list.currentItemChanged.connect(self._current_changed)
        buttons = QHBoxLayout()
        buttons.addWidget(self.add_button)
        buttons.addWidget(self.duplicate_button)
        buttons.addWidget(self.remove_button)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addLayout(buttons)
        left_layout.addWidget(self.list)
        self.busy_label = QLabel()
        left_layout.addWidget(self.busy_label)

        # -- parameters ------------------------------------------------------------------
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.form_box = QGroupBox("Parameters")
        self.form = QFormLayout(self.form_box)
        self.profile_table = QTableWidget(0, 2)
        self.profile_table.setHorizontalHeaderLabels(["Radius ρ (m)", "Height ζ (m)"])
        self.profile_table.setMinimumHeight(120)
        self.profile_table.itemChanged.connect(self._profile_edited)
        self.profile_box = QGroupBox("Revolved profile (base first, axis last)")
        profile_layout = QVBoxLayout(self.profile_box)
        profile_layout.addWidget(self.profile_table)
        row_buttons = QHBoxLayout()
        add_row = QPushButton("Add point")
        add_row.clicked.connect(self._add_profile_point)
        del_row = QPushButton("Remove point")
        del_row.clicked.connect(self._remove_profile_point)
        row_buttons.addWidget(add_row)
        row_buttons.addWidget(del_row)
        profile_layout.addLayout(row_buttons)

        # -- results ---------------------------------------------------------------------
        self.checks = QTreeWidget()
        self.checks.setHeaderLabels(["Check", "Value", "Limit", "Result"])
        self.checks.setMinimumHeight(110)
        self.pieces = QTreeWidget()
        self.pieces.setHeaderLabels(
            ["Piece", "Cut", "Finished W × H (m)", "Flat area (m²)", "3D area (m²)"]
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
        sim_box = QGroupBox("Simulation")
        sim_layout = QVBoxLayout(sim_box)
        sim_row = QHBoxLayout()
        sim_row.addWidget(QLabel("Mesh size"))
        sim_row.addWidget(self.mesh_spin)
        sim_row.addWidget(self.simulate_button)
        sim_row.addWidget(self.cancel_button)
        sim_layout.addLayout(sim_row)
        sim_layout.addWidget(self.sim_status)
        sim_layout.addWidget(self.sim_tree)
        export_row = QHBoxLayout()
        export_row.addWidget(self.export_pack_button)
        export_row.addWidget(self.export_blender_button)

        middle = QWidget()
        middle_layout = QVBoxLayout(middle)
        middle_layout.setContentsMargins(0, 0, 0, 0)
        middle_layout.addWidget(left)
        middle_layout.addWidget(self.status)
        middle_layout.addWidget(self.drag_button)
        middle_layout.addWidget(self.form_box)
        middle_layout.addWidget(self.profile_box)
        middle_layout.addWidget(sim_box)
        middle_layout.addLayout(export_row)
        middle_layout.addStretch(1)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(QLabel("Pattern checks"))
        right_layout.addWidget(self.checks)
        right_layout.addWidget(QLabel("Cut pieces (finished line solid, cut line dashed)"))
        right_layout.addWidget(self.preview, 1)
        right_layout.addWidget(self.pieces)
        right_layout.addWidget(QLabel("Attachment to the envelope"))
        right_layout.addWidget(self.attachment)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setObjectName("shapesSplitter")
        for i, widget in enumerate((middle, right)):
            self.splitter.addWidget(widget)
            self.splitter.setCollapsible(i, False)
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
        ok = bool(self.controller.edit("update_shape", old, _values(path, value)))
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
        key = self.controller.shapes.current_simulation_key(name)
        assert key is not None
        host, skin = shape_fabrics(spec, session.design, session.patterns, placed)
        request = ShapeSolveRequest(
            name,
            key,
            placed,
            session.design,
            host,
            skin,
            self.controller.fabrics.catalog(),
            self.mesh_mm,
        )
        started = self.controller.shape_simulator.start(request)
        self._update_buttons()
        return started

    def export_pack(self, out_dir: str | Path) -> Path | None:
        """Write the build pack of the envelope and every placed shape; returns the index.

        Refused (None) while a shape is being placed or cannot be placed, so a pack never
        silently leaves a shape out.
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
        index = self.controller.attempt(
            export_build_pack, session.design, placed, out_dir, session.patterns, fabrics
        )
        if index is not None:
            self.controller.message.emit(f"Build pack written to {out_dir}")
        return index

    def export_blender(self, path: str | Path) -> Path | None:
        """Write the envelope, the placed shapes and their current simulations as OBJ."""
        from envelopelab.features.scene import export_scene
        from envelopelab.project.shapes import envelope_surface

        session = self.controller.session
        if session is None or session.design.gores is None:
            return None
        service = self.controller.shapes
        designs = [d for d in (self.placed(s.name) for s in session.state.shapes) if d]
        solved = [
            (sim.design, sim.appendage, sim.result)
            for name, sim in service.simulations.items()
            if service.simulation_status(name) == "current"
        ]
        surface = self.controller.attempt(envelope_surface, session.design, session.patterns)
        if surface is None:
            return None
        out = self.controller.attempt(export_scene, path, surface, designs, solved)
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
        path = QFileDialog.getExistingDirectory(self, "Build pack folder")
        if path:
            self.export_pack(path)

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
            item = QListWidgetItem(f"{spec.name}  ({KIND_LABELS[spec.kind]})")
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
        if result.design is None or any(c.severity == "error" for c in result.design.checks):
            return FAIL_COLOR
        if not result.design.ok:
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
        data = spec.model_dump(mode="json")
        for path, box in self.fields.items():
            box.blockSignals(True)
            box.setValue(_get(data, path))
            box.blockSignals(False)
        self.feed_check.blockSignals(True)
        self.feed_check.setChecked(spec.feed_hole_radius is not None)
        self.feed_check.blockSignals(False)
        self.feed_radius.blockSignals(True)
        self.feed_radius.setEnabled(spec.feed_hole_radius is not None)
        if spec.feed_hole_radius is not None:
            self.feed_radius.setValue(spec.feed_hole_radius)
        self.feed_radius.blockSignals(False)
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
        while self.form.rowCount():
            self.form.removeRow(0)
        self.fields = {}
        self.profile_box.setVisible(isinstance(spec, RevolvedShape))
        self.form_box.setVisible(spec is not None)
        if spec is None:
            return
        self.name_edit = QLineEdit(spec.name)
        self.name_edit.setObjectName("shapeName")
        self.name_edit.editingFinished.connect(
            lambda: self.set_value(("name",), self.name_edit.text().strip())
        )
        self.form.addRow("Name", self.name_edit)
        self.form.addRow("Kind", QLabel(KIND_LABELS[spec.kind]))
        if isinstance(spec, MeshShape):
            self.form.addRow(
                "Mesh",
                QLabel(
                    f"{spec.source or 'imported'}: {len(spec.vertices)} vertices, "
                    f"{len(spec.triangles)} triangles"
                ),
            )
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
        self.form.addRow("Feed hole radius (m)", feed_row)
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
        failed = [c for c in design.checks if c.severity != "info"]
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
        for check in design.checks:
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
        for piece in design.pieces:
            w, h = piece.size
            self.pieces.addTopLevelItem(
                QTreeWidgetItem(
                    [
                        piece.label,
                        str(piece.cut_count),
                        f"{w:.3f} × {h:.3f}",
                        f"{piece.flat_area:.4f}",
                        f"{piece.surface_area:.4f}",
                    ]
                )
            )
        for line in design.attachment:
            length = float(np.linalg.norm(np.diff(line.points, axis=0), axis=1).sum())
            self.attachment.addTopLevelItem(
                QTreeWidgetItem([f"gore {line.gore}, row {line.row}", f"{length:.3f}"])
            )
        self.preview.set_pieces(design.pieces)

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
        m = sim.metrics
        stale = service.simulation_status(spec.name) == "stale"
        problems = []
        if not m.converged:
            problems.append(f"NOT CONVERGED ({m.status}): results are not final")
        if stale:
            problems.append("STALE: the shape or the envelope changed since this solve")
        low = {k: v for k, v in m.fos.items() if v < REQUIRED_FOS}
        if low:
            problems.append(f"FACTOR OF SAFETY BELOW {REQUIRED_FOS:g}")
        if problems:
            self.sim_status.setText("Preview solver: " + "; ".join(problems))
            self.sim_status.setStyleSheet(f"color: {FAIL_COLOR}; font-weight: bold;")
        else:
            self.sim_status.setText(
                "Preview solver: converged (preview stiffness values are assumed; not "
                "verified with CalculiX)"
            )
            self.sim_status.setStyleSheet(f"color: {OK_COLOR};")
        r = sim.result
        iterations, residual = r.residual_history[-1] if r.residual_history else (0, float("nan"))
        rows = [
            ("Status", m.status),
            ("Iterations", str(iterations)),
            (f"Final residual ({r.residual_measure})", f"{residual:.2e}"),
            ("Mesh", f"{r.n_nodes} nodes, {r.n_elements} elements"),
            ("Run time", f"{r.elapsed:.1f} s"),
            ("Height above envelope (designed)", f"{m.initial_projected_height:.3f} m"),
            ("Height above envelope (inflated)", f"{m.projected_height:.3f} m"),
            ("Chamber pressure", f"{m.chamber_pressure:.1f} Pa"),
            ("Skin wrinkled", f"{100 * m.skin_wrinkled_fraction:.0f} %"),
            ("Rim tape max tension", f"{m.rim_tape_max_tension:.0f} N"),
            (
                "Footprint max normal movement",
                f"{1000 * m.footprint_max_normal_displacement:.1f} mm",
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
