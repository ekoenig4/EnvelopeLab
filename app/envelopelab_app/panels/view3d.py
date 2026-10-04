"""3D view: design surface, rigging, rest mesh, preview and CalculiX results, reference mesh.

Every layer has its own colour and a label naming where it comes from; a stale or
unconverged layer says so in its label (and is drawn grey or hatched), so a result is never
mistaken for another solver's or for a current one. The layer list is always available;
the PyVista renderer (orbit, zoom, section plane, picking of zones and tapes, spline
widget for the profile, dragging special shapes over the envelope) is used when PyVista,
pyvistaqt and OpenGL are available and the 3D view is enabled in the preferences.

Dragging a special shape: with **Drag special shapes** on, pressing the left button on a
shape and moving the mouse slides the shape's base point over the design surface. An
outline of its footprint follows the cursor (computed by
:func:`envelopelab.project.shapes.footprint_preview`; the shape itself is not re-placed
while dragging), and releasing the button moves the shape there as one undo step. A press
anywhere else orbits the camera as usual.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from envelopelab.project.gore_design import (
    DisplaySurface,
    control_arrays,
    display_surface,
    row_zone,
)
from envelopelab.project.model import SOLVER_LABELS, RunRecord
from envelopelab.project.shapes import (
    ShapePlacement,
    base_radius,
    footprint_preview,
    placement_at,
)
from envelopelab_app.controller import WorkspaceController
from envelopelab_app.refresh import Refresher

#: Layer colours (one per source, never shared).
LAYER_COLORS = {
    "design": "#8c8c8c",
    "rest": "#bcbd22",
    "envelopelab-preview": "#1f77b4",
    "calculix": "#ff7f0e",
    "reference": "#2ca02c",
    "rigging": "#9467bd",
    "shape": "#e7298a",
    "shape-simulated": "#7570b3",
}
#: Line colours of the rigging layer, per element kind.
RIGGING_COLORS = {
    "parachute": "#9467bd",
    "shroud_lines": "#8c564b",
    "centralizing_lines": "#e377c2",
    "red_line": "#d62728",
    "flying_wires": "#17becf",
    "turning_vents": "#e7ba52",
    "scoop": "#843c39",
    "vertical_seams": "#1a1a1a",
    "horizontal_seams": "#4d4d4d",
}
#: Layers drawn without mesh edges: display meshes (the design surface and the designed
#: shapes, whose dense grids would render as solid black with edges), not solver meshes.
SMOOTH_KINDS = ("design", "shape")
#: Colour and actor name of the footprint outline shown while dragging a shape.
DRAG_COLOR = "#ff00ff"
DRAG_ACTOR = "shape-drag-outline"
#: Line widths of polyline kinds (pixels); default 2.
LINE_WIDTHS = {"red_line": 4, "vertical_seams": 3, "horizontal_seams": 2}
#: Brightness of every second gore, so that neighbouring gores are told apart.
ALTERNATE_GORE_SHADE = 0.8


@dataclass
class ShapeDrag:
    """A special shape being dragged in the 3D view.

    Attributes
    ----------
    name : str
        Shape name.
    start, placement : ShapePlacement
        Placement when the drag began, and where the shape would go now (m, deg).
    outline : ndarray, shape (n, 3), optional
        Footprint preview at ``placement``, m (None until the mouse moves).
    """

    name: str
    start: ShapePlacement
    placement: ShapePlacement
    outline: np.ndarray | None = None


@dataclass
class Layer:
    """One displayed mesh.

    Attributes
    ----------
    key : str
        Unique id.
    kind : str
        ``design``, ``rest``, ``envelopelab-preview``, ``calculix``, ``reference``,
        ``rigging``, ``shape`` (a special shape as designed) or ``shape-simulated``.
    label : str
        Text shown in the list and the scene legend.
    points : ndarray, shape (n, 3)
        m.
    faces : ndarray of int, shape (m, 3)
        Triangles.
    stale : bool
        Built from another design state than the current one.
    converged : bool
        False for an unconverged solve.
    visible : bool
        Shown.
    zones : list of str
        Zone name per triangle (for picking), optional.
    tapes : dict of str to ndarray
        Tape paths as node pairs, optional.
    polylines : dict of str to list of ndarray
        Line-only content (rigging, seams), m, keyed by element kind, optional.
    face_colors : ndarray of uint8, shape (m, 3), optional
        RGB colour per triangle (the design surface: row fabric, alternate gores shaded).
    """

    key: str
    kind: str
    label: str
    points: np.ndarray
    faces: np.ndarray
    stale: bool = False
    converged: bool = True
    visible: bool = True
    zones: list[str] = field(default_factory=list)
    tapes: dict[str, np.ndarray] = field(default_factory=dict)
    polylines: dict[str, list[np.ndarray]] = field(default_factory=dict)
    face_colors: np.ndarray | None = None

    @property
    def color(self) -> str:
        """Display colour (grey when stale)."""
        return "#c7c7c7" if self.stale else LAYER_COLORS[self.kind]


def _merged_lines(polylines: list[Any]) -> Any:
    """All polylines of one kind as a single PyVista line mesh (None when empty)."""
    import pyvista as pv

    parts = [np.asarray(line, dtype=float) for line in polylines if len(line) >= 2]
    if not parts:
        return None
    points = np.vstack(parts)
    cells = []
    start = 0
    for part in parts:
        cells.append(np.concatenate([[len(part)], np.arange(start, start + len(part))]))
        start += len(part)
    return pv.PolyData(points, lines=np.concatenate(cells))


def pyvista_available() -> bool:
    """PyVista and pyvistaqt can be imported and a 3D view is allowed."""
    if os.environ.get("ENVELOPELAB_NO_3D"):
        return False
    try:
        import pyvista  # noqa: F401
        import pyvistaqt  # noqa: F401
    except ImportError:
        return False
    return True


class View3DPanel(QWidget):
    """The 3D view panel (see module docstring)."""

    def __init__(
        self,
        controller: WorkspaceController,
        enable_renderer: bool = True,
        defer_renderer: bool = False,
    ) -> None:
        super().__init__()
        self.controller = controller
        self.layers: dict[str, Layer] = {}
        self.plotter: Any = None
        self.layer_list = QListWidget()
        self.layer_list.itemChanged.connect(self._visibility_changed)
        self.section = QCheckBox("Section plane")
        self.section.toggled.connect(self.redraw)
        self.spline = QCheckBox("Edit profile (spline widget)")
        self.spline.toggled.connect(self.redraw)
        self.pick = QCheckBox("Pick zones and tapes")
        self.pick.toggled.connect(self._toggle_pick)
        self.drag_shapes = QCheckBox("Drag special shapes")
        self.drag_shapes.setToolTip(
            "Press on a special shape and drag it over the envelope; release to place it "
            "(one undo step). Press elsewhere to orbit the camera."
        )
        self.drag_shapes.toggled.connect(self._toggle_drag)
        self.drag: ShapeDrag | None = None
        self._drag_observers: list[tuple[Any, int]] = []
        reset = QPushButton("Reset camera")
        reset.clicked.connect(self._reset_camera)
        self.info = QLabel()
        self.info.setWordWrap(True)
        controls = QHBoxLayout()
        for w in (self.section, self.spline, self.pick, self.drag_shapes, reset):
            controls.addWidget(w)
        side = QWidget()
        side_layout = QVBoxLayout(side)
        side_layout.addWidget(QLabel("Layers"))
        side_layout.addWidget(self.layer_list)
        side_layout.addWidget(self.info)
        splitter = QSplitter()
        self.splitter = splitter
        self.renderer_widget: QWidget
        self._renderer_pending = enable_renderer and defer_renderer
        if self._renderer_pending:
            # Importing PyVista and starting OpenGL takes seconds; the window shows first
            # and the main window calls load_renderer() from its event loop.
            self.renderer_widget = QLabel("Loading the 3D view…")
            self.renderer_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
        elif enable_renderer and pyvista_available():
            from pyvistaqt import QtInteractor

            interactor = QtInteractor(self)
            self.plotter = interactor
            self.renderer_widget = interactor
        else:
            self.renderer_widget = QLabel(
                "3D rendering is not available (PyVista/OpenGL missing or disabled in the "
                "preferences). The layer list still shows every result and its source."
            )
            self.renderer_widget.setWordWrap(True)
            self.renderer_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
        splitter.addWidget(self.renderer_widget)
        splitter.addWidget(side)
        splitter.setStretchFactor(0, 4)
        layout = QVBoxLayout(self)
        layout.addLayout(controls)
        layout.addWidget(splitter)
        self.refresher = Refresher(
            self,
            self.refresh,
            lambda: controller.revision,
            (
                controller.stateChanged,
                controller.runsChanged,
                controller.artifactsChanged,
                controller.sessionChanged,
                controller.shapesChanged,
            ),
            defer_hidden=lambda: controller.defer_hidden,
        )
        self._reference_path: str | None = None
        self.refresh()

    def load_renderer(self) -> bool:
        """Start the deferred 3D renderer (see ``defer_renderer``); True when it runs."""
        if not self._renderer_pending:
            return self.plotter is not None
        self._renderer_pending = False
        if not pyvista_available():
            label = self.renderer_widget
            assert isinstance(label, QLabel)
            label.setText(
                "3D rendering is not available (PyVista/OpenGL missing or disabled in the "
                "preferences). The layer list still shows every result and its source."
            )
            label.setWordWrap(True)
            return False
        from pyvistaqt import QtInteractor

        interactor = QtInteractor(self)
        old = self.renderer_widget
        self.splitter.replaceWidget(0, interactor)
        old.deleteLater()
        self.plotter = interactor
        self.renderer_widget = interactor
        self.redraw()
        if self.drag_shapes.isChecked():
            self._toggle_drag(True)  # ticked before the renderer was there
        return True

    # -- layers -------------------------------------------------------------------------

    def refresh(self) -> None:
        """Rebuild the layers from the session."""
        visible = {k: layer.visible for k, layer in self.layers.items()}
        self.layers = {}
        session = self.controller.session
        if session is not None and session.design.gores is not None:
            try:
                surface = display_surface(session.design)
                n = session.design.gores.count
                self.layers["design"] = Layer(
                    "design",
                    "design",
                    f"Design surface (profile, current): {n} gores x "
                    f"{len(surface.row_letters)} panel rows, seams dark",
                    surface.points,
                    surface.faces,
                    polylines={
                        "vertical_seams": surface.vertical_seams,
                        "horizontal_seams": surface.horizontal_seams,
                    },
                    face_colors=self._face_colors(surface),
                )
            except ValueError:
                pass
            lines = self.controller.rigging_polylines()
            if lines:
                parts = ", ".join(k.replace("_", " ") for k in lines)
                self.layers["rigging"] = Layer(
                    "rigging",
                    "rigging",
                    f"Parachute and rigging (design, current): {parts}",
                    np.zeros((0, 3)),
                    np.zeros((0, 3), dtype=np.int64),
                    polylines=lines,
                )
        if session is not None:
            self._shape_layers()
        cache = self.controller.model_cache
        if session is not None and cache is not None:
            model = cache.built.model
            stale = self.controller.artifact_status("rest_mesh") != "current"
            zones = [model.zone_names[i] for i in model.tri_zone]
            self.layers["rest"] = Layer(
                "rest",
                "rest",
                "Rest mesh (as-sewn initial shape)" + (" [STALE]" if stale else ""),
                model.positions,
                model.triangles,
                stale=stale,
                zones=zones,
                tapes={c.name: c.edges for c in model.cables},
            )
        if session is not None:
            latest: dict[str, RunRecord] = {}
            for record in session.project.runs:
                latest[record.solver] = record
            for solver, record in latest.items():
                arrays = session.run_arrays(record.run_id)
                if arrays is None:
                    continue
                stale = session.run_status(record) != "current"
                converged = bool(record.converged)
                label = f"{SOLVER_LABELS[solver]} result, run {record.run_id}"
                if not converged:
                    label += " [NOT CONVERGED]"
                if stale:
                    label += " [STALE]"
                self.layers[solver] = Layer(
                    solver,
                    solver,
                    label,
                    arrays["positions"],
                    arrays["triangles"],
                    stale,
                    converged,
                )
        if self._reference_path is not None:
            self._load_reference(self._reference_path)
        for key, value in visible.items():
            if key in self.layers:
                self.layers[key].visible = value
        self._fill_list()
        self.redraw()

    def _shape_layers(self) -> None:
        """Special shapes as designed and their latest shape simulations."""
        from envelopelab.features.scene import designed_object, simulated_object

        service = self.controller.shapes
        for name in service.keys:
            result = service.result(name)
            if result is None or result.design is None:
                continue
            obj = designed_object(result.design)
            self.layers[f"shape:{name}"] = Layer(
                f"shape:{name}",
                "shape",
                f"Special shape {name} (as designed, current)",
                obj.vertices,
                obj.triangles,
            )
        for name, sim in service.simulations.items():
            if name not in service.keys:
                continue
            obj = simulated_object(sim.design, sim.appendage, sim.result)
            stale = service.simulation_status(name) != "current"
            converged = bool(sim.result.converged)
            label = f"Special shape {name}, preview solver result"
            if not converged:
                label += " [NOT CONVERGED]"
            if stale:
                label += " [STALE]"
            self.layers[f"shape-sim:{name}"] = Layer(
                f"shape-sim:{name}",
                "shape-simulated",
                label,
                obj.vertices,
                obj.triangles,
                stale,
                converged,
            )

    def _face_colors(self, surface: DisplaySurface) -> np.ndarray:
        """Row fabric colour per triangle, every second gore darker (display only)."""
        session = self.controller.session
        assert session is not None
        design = session.design
        palette = []
        for letter in surface.row_letters:
            fabric_id = design.zones.get(row_zone(design, session.patterns, letter), "")
            fabric = self.controller.fabrics.fabric(fabric_id) if fabric_id else None
            color = QColor(fabric.color) if fabric is not None else QColor("#d9e7f5")
            if not color.isValid():
                color = QColor("#d9e7f5")
            palette.append((color.red(), color.green(), color.blue()))
        rgb = np.array(palette, dtype=np.float64)[surface.face_row]
        rgb[surface.face_gore % 2 == 0] *= ALTERNATE_GORE_SHADE
        return np.asarray(rgb.astype(np.uint8))

    def _fill_list(self) -> None:
        self.layer_list.blockSignals(True)
        self.layer_list.clear()
        for key, layer in self.layers.items():
            item = QListWidgetItem(layer.label)
            item.setData(Qt.ItemDataRole.UserRole, key)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if layer.visible else Qt.CheckState.Unchecked)
            item.setForeground(QBrush(QColor(layer.color).darker(130)))
            self.layer_list.addItem(item)
        self.layer_list.blockSignals(False)

    def labels(self) -> dict[str, str]:
        """Layer key to label (as shown)."""
        return {k: layer.label for k, layer in self.layers.items()}

    def load_reference(self, path: str) -> None:
        """Show a reference mesh (OBJ, STL, PLY in m)."""
        self._reference_path = path
        self.refresh()

    def _load_reference(self, path: str) -> None:
        from envelopelab.io.reference_mesh import ReferenceMeshError, read_mesh

        try:
            mesh = read_mesh(path)
        except (OSError, ReferenceMeshError) as exc:
            self.info.setText(f"reference mesh not loaded: {exc}")
            self._reference_path = None
            return
        self.layers["reference"] = Layer(
            "reference",
            "reference",
            f"Reference mesh ({os.path.basename(path)})",
            mesh.vertices,
            mesh.triangles,
        )

    def _visibility_changed(self, item: QListWidgetItem) -> None:
        key = item.data(Qt.ItemDataRole.UserRole)
        if key in self.layers:
            self.layers[key].visible = item.checkState() == Qt.CheckState.Checked
            self.redraw()

    # -- rendering ----------------------------------------------------------------------

    def redraw(self) -> None:
        """Draw the visible layers (no-op without a renderer)."""
        plotter = self.plotter
        if plotter is None:
            return
        import pyvista as pv

        plotter.clear()
        plotter.clear_plane_widgets()
        plotter.clear_spline_widgets()
        legend = []
        for layer in self.layers.values():
            if layer.visible and layer.polylines:
                for kind, polylines in layer.polylines.items():
                    merged = _merged_lines(polylines)
                    if merged is None:
                        continue
                    # One actor per kind of line: far cheaper to build and to render
                    # than one actor per polyline.
                    plotter.add_mesh(
                        merged,
                        color=RIGGING_COLORS.get(kind, layer.color),
                        line_width=LINE_WIDTHS.get(kind, 2),
                    )
                if len(layer.faces) == 0:
                    legend.append([layer.label, layer.color])
            if not layer.visible or len(layer.faces) == 0:
                continue
            faces = np.hstack([np.full((len(layer.faces), 1), 3), layer.faces]).ravel()
            mesh = pv.PolyData(np.asarray(layer.points, dtype=float), faces)
            style = "wireframe" if layer.kind == "rest" else "surface"
            opacity = 0.35 if layer.kind == "reference" else 1.0
            if layer.face_colors is not None and not layer.stale:
                mesh.cell_data["rgb"] = layer.face_colors
                plotter.add_mesh(mesh, scalars="rgb", rgb=True, name=layer.key, show_edges=False)
                legend.append([layer.label, layer.color])
                continue
            if self.section.isChecked() and layer.kind != "design":
                plotter.add_mesh_clip_plane(mesh, color=layer.color, style=style, opacity=opacity)
            else:
                plotter.add_mesh(
                    mesh,
                    color=layer.color,
                    style=style,
                    opacity=opacity,
                    show_edges=layer.kind not in SMOOTH_KINDS,
                    name=layer.key,
                )
            if layer.tapes:
                for edges in layer.tapes.values():
                    lines = np.hstack([np.full((len(edges), 1), 2), edges]).ravel()
                    plotter.add_mesh(
                        pv.PolyData(np.asarray(layer.points, dtype=float), lines=lines),
                        color="#d62728",
                        line_width=3,
                    )
            legend.append([layer.label, layer.color])
        if legend:
            plotter.add_legend(legend, bcolor="white", size=(0.45, 0.2))
        if (
            self.spline.isChecked()
            and self.controller.design is not None
            and self.controller.design.gores is not None
        ):
            r, z = control_arrays(self.controller.design)
            pts = np.column_stack([r, np.zeros_like(r), z])
            plotter.add_spline_widget(
                self._spline_changed,
                initial_points=pts,
                n_handles=len(pts),
                resolution=200,
                interaction_event="end",
            )

    def _spline_changed(self, polyline: object) -> None:
        handles = self.spline_widgets()
        if not handles:
            return
        widget = handles[0]
        pts = np.array([widget.GetHandlePosition(i) for i in range(widget.GetNumberOfHandles())])
        points = [(float(math.hypot(p[0], p[1])), float(p[2])) for p in pts]
        self.controller.edit("set_control_points", points, "Edit profile in the 3D view")

    def spline_widgets(self) -> list[Any]:
        """The active VTK spline widgets (empty without a renderer)."""
        plotter = self.plotter
        if plotter is None:
            return []
        widgets = getattr(plotter, "widgets", None)  # PyVista >= 0.47
        found = getattr(widgets, "spline_widgets", None) if widgets is not None else None
        if found is None:
            found = getattr(plotter, "spline_widgets", [])
        return list(found)

    def _toggle_pick(self, on: bool) -> None:
        plotter = self.plotter
        if on:
            # Picking replaces the mouse handling that dragging relies on.
            self.drag_shapes.setChecked(False)
        if plotter is None:
            return
        if on:
            plotter.enable_cell_picking(callback=self._picked, through=False, show_message=False)
        else:
            plotter.disable_picking()

    def _picked(self, cell: object) -> None:
        layer = self.layers.get("rest")
        if layer is None or cell is None:
            return
        ids = getattr(cell, "cell_data", {}).get("vtkOriginalCellIds")
        if ids is None or len(ids) == 0:
            return
        tri = int(ids[0])
        zone = layer.zones[tri] if tri < len(layer.zones) else "?"
        self.info.setText(f"element {tri}: material zone {zone}")

    # -- dragging special shapes -------------------------------------------------------

    def begin_shape_drag(self, name: str) -> bool:
        """Start dragging special shape ``name``; False for an unknown shape."""
        session = self.controller.session
        spec = (
            None
            if session is None
            else next((s for s in session.state.shapes if s.name == name), None)
        )
        if spec is None or self.controller.envelope_surface() is None:
            return False
        self.drag = ShapeDrag(name, spec.placement, spec.placement)
        self.info.setText(f"Moving {name}: drag over the envelope and release to place it")
        return True

    def drag_shape_to(self, point: np.ndarray) -> ShapePlacement | None:
        """Move the dragged shape's preview to the envelope point nearest ``point`` (m)."""
        drag, surface = self.drag, self.controller.envelope_surface()
        session = self.controller.session
        if drag is None or surface is None or session is None:
            return None
        spec = next((s for s in session.state.shapes if s.name == drag.name), None)
        if spec is None:
            self.cancel_shape_drag()
            return None
        drag.placement = placement_at(surface, point, drag.placement)
        drag.outline = footprint_preview(surface, drag.placement, base_radius(spec))
        p = drag.placement
        self.info.setText(
            f"Moving {drag.name}: gore {p.gore}, {p.tape_position:.3f} m up the tape from "
            f"the mouth, {p.across:+.2f} of the gore width across; release to place it"
        )
        self._draw_drag_outline()
        return drag.placement

    def end_shape_drag(self) -> bool:
        """Place the dragged shape where its preview is (one undo step); True if it moved."""
        drag, self.drag = self.drag, None
        self._remove_drag_outline()
        if drag is None:
            return False
        p, s = drag.placement, drag.start
        if (p.gore, p.tape_position, p.across) == (s.gore, s.tape_position, s.across):
            self.info.setText("")
            return False
        values = {"gore": p.gore, "tape_position": p.tape_position, "across": p.across}
        moved = bool(self.controller.edit("update_shape", drag.name, {"placement": values}))
        self.info.setText(
            f"Moved {drag.name} to gore {p.gore}, {p.tape_position:.3f} m up the tape; it is "
            "being placed (see Special shapes)"
            if moved
            else ""
        )
        return moved

    def cancel_shape_drag(self) -> None:
        """Stop dragging without moving the shape."""
        self.drag = None
        self._remove_drag_outline()
        self.info.setText("")

    def _draw_drag_outline(self) -> None:
        plotter, drag = self.plotter, self.drag
        if plotter is None or drag is None or drag.outline is None:
            return
        import pyvista as pv

        plotter.add_mesh(
            pv.lines_from_points(drag.outline),
            color=DRAG_COLOR,
            line_width=4,
            name=DRAG_ACTOR,
            pickable=False,
            reset_camera=False,
        )
        plotter.render()

    def _remove_drag_outline(self) -> None:
        if self.plotter is not None and DRAG_ACTOR in self.plotter.actors:
            self.plotter.remove_actor(DRAG_ACTOR)
            self.plotter.render()

    def _toggle_drag(self, on: bool) -> None:
        if on:
            self.pick.setChecked(False)
        self._remove_drag_observers()
        if not on:
            self.cancel_shape_drag()
            return
        plotter = self.plotter
        if plotter is None:
            return
        # Observers on the interactor style replace its default handling of these
        # events; each handler calls the default itself unless a shape is being dragged,
        # so the camera still orbits when the press misses every shape.
        style = plotter.iren.interactor.GetInteractorStyle()
        for event, handler in (
            ("LeftButtonPressEvent", self._vtk_press),
            ("MouseMoveEvent", self._vtk_move),
            ("LeftButtonReleaseEvent", self._vtk_release),
        ):
            self._drag_observers.append((style, style.AddObserver(event, handler)))

    def _remove_drag_observers(self) -> None:
        for style, tag in self._drag_observers:
            style.RemoveObserver(tag)
        self._drag_observers = []

    def _pick(self, keys: list[str]) -> tuple[str, np.ndarray] | None:
        """Layer key and point (m) under the mouse among the actors of ``keys``."""
        plotter = self.plotter
        if plotter is None:
            return None
        from vtkmodules.vtkRenderingCore import vtkCellPicker

        actors = {k: plotter.actors[k] for k in keys if k in plotter.actors}
        if not actors:
            return None
        picker = vtkCellPicker()
        picker.SetTolerance(0.0005)
        picker.PickFromListOn()
        for actor in actors.values():
            picker.AddPickList(actor)
        x, y = plotter.iren.interactor.GetEventPosition()
        if not picker.Pick(x, y, 0, plotter.renderer):
            return None
        hit = picker.GetActor()
        key = next((k for k, a in actors.items() if a is hit), None)
        return None if key is None else (key, np.array(picker.GetPickPosition()))

    def _shape_keys(self) -> list[str]:
        return [k for k, layer in self.layers.items() if layer.kind == "shape" and layer.visible]

    def _vtk_press(self, style: Any, _event: str) -> None:
        # The design surface is in the pick list so a shape hidden behind it is not hit.
        hit = self._pick([*self._shape_keys(), "design"])
        if hit is None or not hit[0].startswith("shape:"):
            style.OnLeftButtonDown()
            return
        self.begin_shape_drag(hit[0].removeprefix("shape:"))

    def _vtk_move(self, style: Any, _event: str) -> None:
        if self.drag is None:
            style.OnMouseMove()
            return
        hit = self._pick(["design"])
        if hit is not None:
            self.drag_shape_to(hit[1])

    def _vtk_release(self, style: Any, _event: str) -> None:
        if self.drag is None:
            style.OnLeftButtonUp()
            return
        self.end_shape_drag()

    def _reset_camera(self) -> None:
        if self.plotter is not None:
            self.plotter.reset_camera()

    def close_renderer(self) -> None:
        """Release the VTK render window."""
        self._remove_drag_observers()
        if self.plotter is not None:
            self.plotter.close()
            self.plotter = None
