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

import json
import math
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial
from typing import Any

import numpy as np
from PySide6.QtCore import QEvent, QKeyCombination, QObject, QSettings, Qt
from PySide6.QtGui import QBrush, QColor, QKeyEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from envelopelab.project.gore_design import (
    DisplaySurface,
    control_arrays,
    display_surface,
    envelope_marks,
    panel_zone,
)
from envelopelab.project.model import SOLVER_LABELS, RunRecord
from envelopelab.project.shapes import (
    ShapePlacement,
    base_radius,
    display_offset,
    feed_hole_rings,
    footprint_preview,
    placement_at,
)
from envelopelab.rigging.common import seam_azimuth
from envelopelab_app.camera import (
    CameraPose,
    facing,
    fit_to_bounds,
    gore_centre_azimuth,
    gore_step,
    pose_from_dict,
    pose_to_dict,
    turn_about_axis,
    view_pose,
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
    "marks": "#2b8cbe",
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
    "panel_zones": "#2b8cbe",
    "tape_paths": "#1a1a1a",
    "feature_locations": "#e6550d",
    "feed_holes": "#ff00ff",
}
#: Layers drawn without mesh edges: display meshes (the design surface and the designed
#: shapes, whose dense grids would render as solid black with edges), not solver meshes.
SMOOTH_KINDS = ("design", "shape")
#: Colour and actor name of the footprint outline shown while dragging a shape.
DRAG_COLOR = "#ff00ff"
DRAG_ACTOR = "shape-drag-outline"
#: Line widths of polyline kinds (pixels); default 2.
LINE_WIDTHS = {
    "red_line": 4,
    "vertical_seams": 3,
    "horizontal_seams": 2,
    "panel_zones": 3,
    "tape_paths": 3,
    "feed_holes": 3,
}
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
        ``rigging``, ``marks`` (panel zones, tape paths, feature locations), ``shape``
        (a special shape as designed) or ``shape-simulated``.
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


def _interactor(parent: QWidget) -> Any:
    """The PyVista Qt render widget, without its auto-update timer.

    pyvistaqt re-renders 5 times a second by default, changed or not. On a software
    OpenGL renderer (WSLg, Mesa llvmpipe) a frame of a large window takes about 0.1 s, so
    the timer alone kept the GUI thread half busy while the 3D view was shown. The panel
    renders after every change itself, and the interactor renders while the view is moved.
    """
    from pyvistaqt import QtInteractor

    return QtInteractor(parent, auto_update=False)


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


#: View buttons: (key, label, shortcut). The number keys follow the numeric-keypad views of
#: common 3D programs (1 front, 3 side, 7 top; Ctrl for the opposite side).
VIEW_CONTROLS = (
    ("front", "Front", "1"),
    ("back", "Back", "Ctrl+1"),
    ("right", "Side", "3"),
    ("left", "Other side", "Ctrl+3"),
    ("top", "Top", "7"),
    ("bottom", "Into mouth", "Ctrl+7"),
    ("iso", "Isometric", "0"),
    ("fit", "Fit", "Home"),
)
VIEW_TIPS = {
    "front": "Look at the envelope from the front (along +y), mouth down",
    "back": "Look at the envelope from the back (along -y), mouth down",
    "right": "Look at the envelope from the side (along -x), mouth down",
    "left": "Look at the envelope from the other side (along +x), mouth down",
    "top": "Look down onto the crown",
    "bottom": "Look up into the mouth",
    "iso": "Three-quarter view from above",
    "fit": "Fit the whole scene in the current view direction",
}


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
        # Viewpoints: standard views, one-gore turns about the envelope axis, projection.
        self.view_buttons: dict[str, QPushButton] = {}
        #: View keys and their actions, also caught on the render widget (VTK would take
        #: the key presses there: its 3 toggles stereo rendering).
        self.view_keys: dict[str, Callable[[], None]] = {}
        views = QHBoxLayout()
        views.addWidget(QLabel("View:"))
        for key, text, shortcut in VIEW_CONTROLS:
            button = QPushButton(text)
            button.setObjectName(f"view_{key}")
            button.setToolTip(f"{VIEW_TIPS[key]} (key {shortcut})")
            button.clicked.connect(lambda _c=False, k=key: self.set_view(k))
            self.view_buttons[key] = button
            views.addWidget(button)
            self.view_keys[shortcut] = partial(self.set_view, key)
        for step, text, shortcut, tip in (
            (-1, "◀ Gore", "4", "Turn the view one gore clockwise, seen from above"),
            (1, "Gore ▶", "6", "Turn the view one gore counter-clockwise, seen from above"),
        ):
            button = QPushButton(text)
            button.setObjectName("gore_prev" if step < 0 else "gore_next")
            button.setToolTip(f"{tip} (key {shortcut})")
            button.clicked.connect(lambda _c=False, n=step: self.turn_gores(n))
            self.view_buttons[button.objectName()] = button
            views.addWidget(button)
            self.view_keys[shortcut] = partial(self.turn_gores, step)
        self.orthographic = QCheckBox("Orthographic")
        self.orthographic.setToolTip(
            "Parallel projection: no perspective, so profiles and lengths can be compared (key 5)"
        )
        self.orthographic.toggled.connect(self._set_projection)
        self.view_keys["5"] = self.orthographic.toggle
        for sequence, action in self.view_keys.items():
            # The same key on the numeric keypad ("Num+7") as on the number row.
            keypad = f"Num+{sequence}" if sequence[-1].isdigit() else None
            for text in filter(None, (sequence, keypad)):
                QShortcut(QKeySequence(text), self, action).setContext(
                    Qt.ShortcutContext.WidgetWithChildrenShortcut
                )
        views.addWidget(self.orthographic)
        views.addStretch(1)
        # Seams and gores, a layer, and saved viewpoints.
        places = QHBoxLayout()
        self.seam_number = QSpinBox()
        self.seam_number.setObjectName("faceNumber")
        self.seam_number.setRange(1, 12)
        self.seam_number.setPrefix("No. ")
        self.seam_number.setToolTip("Seam or gore to face (numbered as in the rigging)")
        places.addWidget(QLabel("Seam/gore:"))
        places.addWidget(self.seam_number)
        for key, text, tip, action in (
            (
                "face_seam",
                "Face seam",
                "Look straight at the seam, running up the middle",
                lambda: self.face_seam(self.seam_number.value()),
            ),
            (
                "face_gore",
                "Face gore",
                "Look straight at the centre of the gore",
                lambda: self.face_gore(self.seam_number.value()),
            ),
            (
                "zoom_layer",
                "Zoom to layer",
                "Fit the view to the layer selected in the list",
                lambda: self.zoom_to_layer(self._selected_layer()),
            ),
        ):
            button = QPushButton(text)
            button.setObjectName(key)
            button.setToolTip(tip)
            button.clicked.connect(lambda _c=False, a=action: a())
            self.view_buttons[key] = button
            places.addWidget(button)
        places.addSpacing(12)
        self.saved_views = QComboBox()
        self.saved_views.setObjectName("savedViews")
        self.saved_views.setMinimumContentsLength(12)
        self.saved_views.setToolTip("Saved viewpoints of this project; choose one to go there")
        self.saved_views.activated.connect(
            lambda i: self.restore_view(self.saved_views.itemText(i))
        )
        save = QPushButton("Save view")
        save.setObjectName("save_view")
        save.setToolTip("Remember the current viewpoint under a name (kept per project)")
        save.clicked.connect(self._save_view_clicked)
        delete = QPushButton("Delete view")
        delete.setObjectName("delete_view")
        delete.clicked.connect(lambda: self.delete_view(self.saved_views.currentText()))
        self.view_buttons["save_view"] = save
        self.view_buttons["delete_view"] = delete
        places.addWidget(QLabel("Views:"))
        for widget in (self.saved_views, save, delete):
            places.addWidget(widget)
        places.addStretch(1)
        #: Where saved viewpoints are kept (the main window's settings); None keeps them
        #: for this session only.
        self.settings: QSettings | None = None
        self._session_views: dict[str, list[dict[str, object]]] = {}
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
            interactor = _interactor(self)
            interactor.installEventFilter(self)
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
        layout.addLayout(views)
        layout.addLayout(places)
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
        interactor = _interactor(self)
        interactor.installEventFilter(self)
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
                gores = session.design.gores
                what = "profile"
                if gores.construction == "flat_chord":
                    what = "profile, flat-chord gores with " + (
                        "crest loft"
                        if gores.crest_loft is not None
                        else "crest from the seam bows"
                        if any(r.bow_top for r in gores.panel_rows)
                        else "straight seams"
                    )
                elif gores.loft is not None:
                    what = "profile, lobe loft"
                self.layers["design"] = Layer(
                    "design",
                    "design",
                    f"Design surface ({what}, current): {n} gores x "
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
            try:
                marks = envelope_marks(session.design, session.patterns, self.controller.rows())
            except ValueError:
                marks = {}
            if marks:
                parts = ", ".join(k.replace("_", " ") for k in marks)
                self.layers["marks"] = Layer(
                    "marks",
                    "marks",
                    f"Panel details (design, current): {parts}",
                    np.zeros((0, 3)),
                    np.zeros((0, 3), dtype=np.int64),
                    polylines=marks,
                )
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
        self.seam_number.setMaximum(self._gore_count())
        self._fill_saved()
        self.redraw()

    def _shape_layers(self) -> None:
        """Special shapes as designed and their latest shape simulations."""
        from envelopelab.features.scene import designed_object, simulated_object

        service = self.controller.shapes
        design = self.controller.design
        host = design if design is not None and design.gores is not None else None
        for name in service.keys:
            result = service.result(name)
            if result is None or result.design is None:
                continue
            obj = designed_object(result.design)
            # Sit the shape and its feed holes on the drawn envelope (display only).
            shift = display_offset(host, result.design) if host else np.zeros(3)
            holes = feed_hole_rings(host, result.design) if host else []
            self.layers[f"shape:{name}"] = Layer(
                f"shape:{name}",
                "shape",
                f"Special shape {name} (as designed, current)"
                + (f", {len(holes)} feed hole(s)" if holes else ""),
                obj.vertices + shift,
                obj.triangles,
                polylines={"feed_holes": holes} if holes else {},
            )
        for name, sim in service.simulations.items():
            if name not in service.keys:
                continue
            obj = simulated_object(sim.design, sim.appendage, sim.result)
            shift = display_offset(host, sim.design) if host else np.zeros(3)
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
                obj.vertices + shift,
                obj.triangles,
                stale,
                converged,
            )

    def _face_colors(self, surface: DisplaySurface) -> np.ndarray:
        """Fabric colour per triangle: the panel's zone (a panel zone, else its row's),
        every second gore darker (display only)."""
        session = self.controller.session
        assert session is not None
        design = session.design
        assert design.gores is not None
        n = design.gores.count
        palette = np.zeros((len(surface.row_letters), n, 3))
        for i, letter in enumerate(surface.row_letters):
            for g in range(1, n + 1):
                zone = panel_zone(design, session.patterns, letter, g)
                fabric_id = design.zones.get(zone, "")
                fabric = self.controller.fabrics.fabric(fabric_id) if fabric_id else None
                color = QColor(fabric.color) if fabric is not None else QColor("#d9e7f5")
                if not color.isValid():
                    color = QColor("#d9e7f5")
                palette[i, g - 1] = (color.red(), color.green(), color.blue())
        rgb = palette[surface.face_row, surface.face_gore - 1]
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
        """Draw the visible layers (no-op without a renderer).

        The scene is rebuilt with rendering suppressed and rendered once at the end:
        PyVista renders after every added actor otherwise, which took 22 s for the
        full-size fixture's 473 actors on a software OpenGL renderer (47 ms a frame).
        """
        plotter = self.plotter
        if plotter is None:
            return
        suppressed = plotter.suppress_rendering
        plotter.suppress_rendering = True
        try:
            self._build_scene(plotter)
        finally:
            plotter.suppress_rendering = suppressed
        plotter.render()

    def _build_scene(self, plotter: Any) -> None:
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
                # Every tape in one line actor (one actor per tape was 462 actors on the
                # full-size fixture, each a draw call in every frame).
                edges = np.vstack([np.asarray(e).reshape(-1, 2) for e in layer.tapes.values()])
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

    # -- viewpoints ---------------------------------------------------------------------

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 (Qt API)
        """View keys pressed over the render widget choose views (VTK never sees them)."""
        if watched is self.plotter and event.type() in (
            QEvent.Type.KeyPress,
            QEvent.Type.ShortcutOverride,
        ):
            assert isinstance(event, QKeyEvent)
            # A keypad digit is the same view key as the number-row digit.
            modifiers = event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
            combination = QKeyCombination(modifiers, Qt.Key(event.key()))
            sequence = QKeySequence(combination).toString()
            action = self.view_keys.get(sequence)
            if action is not None:
                if event.type() == QEvent.Type.KeyPress:
                    action()
                event.accept()
                return True
        return super().eventFilter(watched, event)

    def _apply_pose(self, pose: CameraPose) -> None:
        plotter = self.plotter
        camera = plotter.camera
        camera.position = tuple(pose.position)
        camera.focal_point = tuple(pose.focal_point)
        camera.up = tuple(pose.view_up)
        camera.parallel_scale = pose.parallel_scale
        plotter.reset_camera_clipping_range()
        plotter.render()

    def _pose(self) -> CameraPose:
        camera = self.plotter.camera
        return CameraPose(
            np.array(camera.position, dtype=float),
            np.array(camera.focal_point, dtype=float),
            np.array(camera.up, dtype=float),
            float(camera.parallel_scale),
        )

    def set_view(self, key: str) -> None:
        """Look at the whole visible scene from a standard view (:data:`VIEWS`), or fit
        the current view to it (``"fit"``)."""
        plotter = self.plotter
        if plotter is None:
            return
        if key == "fit":
            plotter.reset_camera()
            plotter.render()
            return
        angle = float(plotter.camera.view_angle)
        self._apply_pose(view_pose(tuple(plotter.bounds), key, angle))

    def turn_gores(self, gores: int) -> None:
        """Turn the view about the envelope axis by ``gores`` gores (counter-clockwise
        seen from above for a positive count)."""
        if self.plotter is None:
            return
        design = self.controller.design
        count = design.gores.count if design is not None and design.gores is not None else 12
        self._apply_pose(turn_about_axis(self._pose(), gores * gore_step(count)))

    def face_seam(self, seam: int) -> None:
        """Look straight at vertical seam ``seam`` (1..N), mouth down."""
        if self.plotter is None:
            return
        count = self._gore_count()
        azimuth = seam_azimuth(min(max(seam, 1), count), count)
        self._apply_pose(facing(tuple(self.plotter.bounds), azimuth, self._view_angle()))

    def face_gore(self, gore: int) -> None:
        """Look straight at the centre of gore ``gore`` (1..N), mouth down."""
        if self.plotter is None:
            return
        count = self._gore_count()
        azimuth = gore_centre_azimuth(min(max(gore, 1), count), count)
        self._apply_pose(facing(tuple(self.plotter.bounds), azimuth, self._view_angle()))

    def zoom_to_layer(self, key: str | None) -> None:
        """Fit the view to one layer, keeping the viewing direction."""
        layer = self.layers.get(key) if key is not None else None
        if self.plotter is None or layer is None:
            return
        parts = [np.asarray(layer.points, dtype=float).reshape(-1, 3)]
        for lines in layer.polylines.values():
            parts += [np.asarray(line, dtype=float).reshape(-1, 3) for line in lines]
        points = np.vstack([p for p in parts if len(p)]) if any(len(p) for p in parts) else None
        if points is None:
            return
        lo, hi = points.min(axis=0), points.max(axis=0)
        bounds = (lo[0], hi[0], lo[1], hi[1], lo[2], hi[2])
        self._apply_pose(fit_to_bounds(self._pose(), bounds, self._view_angle()))

    def _selected_layer(self) -> str | None:
        item = self.layer_list.currentItem()
        return None if item is None else str(item.data(Qt.ItemDataRole.UserRole))

    def _gore_count(self) -> int:
        design = self.controller.design
        return design.gores.count if design is not None and design.gores is not None else 12

    def _view_angle(self) -> float:
        return float(self.plotter.camera.view_angle)

    # -- saved viewpoints ---------------------------------------------------------------

    def _views_key(self) -> str:
        session = self.controller.session
        path = None if session is None else session.path
        return "view3d/saved/" + (str(path.resolve()) if path is not None else "unsaved")

    def saved(self) -> list[dict[str, object]]:
        """Saved viewpoints of this project, oldest first (``name`` and the camera)."""
        key = self._views_key()
        if self.settings is None:
            return list(self._session_views.get(key, []))
        raw = self.settings.value(key)
        try:
            views = json.loads(str(raw)) if raw else []
        except json.JSONDecodeError:
            views = []
        return [v for v in views if isinstance(v, dict) and "name" in v]

    def _store(self, views: list[dict[str, object]]) -> None:
        key = self._views_key()
        if self.settings is None:
            self._session_views[key] = views
        else:
            self.settings.setValue(key, json.dumps(views))
            self.settings.sync()
        self._fill_saved()

    def _fill_saved(self) -> None:
        self.saved_views.blockSignals(True)
        self.saved_views.clear()
        for view in self.saved():
            self.saved_views.addItem(str(view["name"]))
        self.saved_views.blockSignals(False)

    def save_view(self, name: str) -> bool:
        """Remember the current viewpoint as ``name`` (replacing one of that name)."""
        name = name.strip()
        if self.plotter is None or not name:
            return False
        entry = {"name": name, **pose_to_dict(self._pose(), self.orthographic.isChecked())}
        views = [v for v in self.saved() if v.get("name") != name] + [entry]
        self._store(views)
        self.saved_views.setCurrentText(name)
        return True

    def restore_view(self, name: str) -> bool:
        """Go to the saved viewpoint ``name``."""
        if self.plotter is None:
            return False
        for view in self.saved():
            if view.get("name") == name:
                try:
                    pose, parallel = pose_from_dict(view)
                except ValueError:
                    return False
                self.orthographic.setChecked(parallel)
                self._apply_pose(pose)
                return True
        return False

    def delete_view(self, name: str) -> bool:
        """Forget the saved viewpoint ``name``."""
        views = self.saved()
        kept = [v for v in views if v.get("name") != name]
        if len(kept) == len(views):
            return False
        self._store(kept)
        return True

    def _save_view_clicked(self) -> None:
        default = f"View {len(self.saved()) + 1}"
        if not self.controller.defer_hidden:  # scripted window: no dialog
            self.save_view(default)
            return
        name, ok = QInputDialog.getText(self, "Save view", "Name of this viewpoint:", text=default)
        if ok:
            self.save_view(name)

    def _set_projection(self, parallel: bool) -> None:
        plotter = self.plotter
        if plotter is None:
            return
        if parallel:
            plotter.enable_parallel_projection()
        else:
            plotter.disable_parallel_projection()
        plotter.render()

    def close_renderer(self) -> None:
        """Release the VTK render window."""
        self._remove_drag_observers()
        if self.plotter is not None:
            self.plotter.close()
            self.plotter = None
