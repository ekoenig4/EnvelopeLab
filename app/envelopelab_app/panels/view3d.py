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
from html import escape
from typing import Any

import numpy as np
from PySide6.QtCore import QEvent, QKeyCombination, QObject, QSettings, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QIcon,
    QKeyEvent,
    QKeySequence,
    QPixmap,
    QShortcut,
    QStandardItemModel,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from envelopelab.project.deviation import interpolate_on_mesh
from envelopelab.project.gore_design import (
    DisplaySurface,
    control_arrays,
    display_surface,
    envelope_marks,
    panel_zone,
)
from envelopelab.project.model import SOLVER_LABELS, RunRecord
from envelopelab.project.run_fields import (
    FIELD_LABELS,
    SAFETY_FIELDS,
    missing_fields,
    run_fields,
    shape_missing_fields,
    shape_run_fields,
)
from envelopelab.project.shapes import (
    ShapePlacement,
    base_radius,
    display_offset,
    feed_hole_rings,
    footprint_preview,
    placement_at,
    shape_fabrics,
)
from envelopelab.rigging.common import seam_azimuth
from envelopelab.solvers.results import DEFAULT_REQUIRED_FOS, ResultField
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
from envelopelab_app.result_view import (
    CONTINUOUS_CMAP,
    Bands,
    RunState,
    banner_for,
    diverging_colors,
    failing_zone_names,
    fos_bands,
    wrinkle_bands,
)
from envelopelab_app.theme import STATUS_STYLES, StatusBanner

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
    "skin_seams": "#1a1a1a",
    "skin_rim": "#1a1a1a",
}
#: Short layer names by layer key (others: see :attr:`Layer.short`).
SHORT_NAMES = {
    "design": "Design surface",
    "marks": "Panel details",
    "rigging": "Rigging",
    "rest": "Rest mesh",
    "envelopelab-preview": "Preview result",
    "calculix": "CalculiX result",
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
    "skin_seams": 2,
    "skin_rim": 3,
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

    @property
    def short(self) -> str:
        """Short name for the layer list, the legend and the Run list (the full
        description, :attr:`label`, is the tooltip)."""
        name = SHORT_NAMES.get(self.key)
        if name is not None:
            return name
        if self.key.startswith("shape-sim:"):
            return f"{self.key.removeprefix('shape-sim:')} (inflated)"
        if self.key.startswith("shape:"):
            return f"{self.key.removeprefix('shape:')} (designed)"
        if self.kind == "reference" and "(" in self.label:
            return "Reference: " + self.label.split("(", 1)[1].rstrip(")")
        return self.label

    @property
    def display_name(self) -> str:
        """:attr:`short` with the layer's status when it is not a current result: never
        hidden in a tooltip (stale and unconverged layers say so on their row)."""
        parts = [self.short]
        if not self.converged:
            parts.append(f"{STATUS_STYLES['error'].symbol} not converged")
        if self.stale:
            parts.append(f"{STATUS_STYLES['stale'].symbol} stale")
        return "  ".join(parts)

    @property
    def legend_name(self) -> str:
        """:attr:`display_name` in plain text for the scene legend (VTK's font has no
        status symbols)."""
        flags = (("NOT CONVERGED", not self.converged), ("stale", self.stale))
        status = [word for word, on in flags if on]
        return f"{self.short} ({', '.join(status)})" if status else self.short


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


#: Shown in place of the renderer when there is none.
NO_RENDERER_TEXT = (
    "3D rendering is not available (PyVista/OpenGL missing or disabled in the "
    "preferences). The layer list, the run details and the status banner still show "
    "every result, its source and its status."
)
#: Display modes of the surfaces (the toolbar's Display list).
DISPLAY_MODES = ("Shaded", "Shaded + mesh edges", "Wireframe")
#: "Colour by" entry that draws the result in its layer colour.
LAYER_COLOUR = "Layer colour"
#: Required fabric factor of safety used for the colour bands, and its source tag.
FOS_LIMIT = DEFAULT_REQUIRED_FOS
FOS_LIMIT_SOURCE = "assumed"
#: Fields shown in another unit than SI: key to (scale factor, unit).
DISPLAY_UNITS = {"displacement": (1000.0, "mm"), "deviation": (1000.0, "mm")}
#: Fields on a diverging colour map, symmetric about zero (blue inside, red outside).
DIVERGING_FIELDS = ("deviation",)
DIVERGING_CMAP = diverging_colors()
#: Scalar bar titles (short: the bar is narrow).
SHORT_TITLES = {
    "fos_warp": "FoS warp",
    "fos_weft": "FoS weft",
    "n1": "N1",
    "n2": "N2",
    "n_warp": "N warp",
    "n_weft": "N weft",
    "wrinkle_state": "Wrinkling",
    "displacement": "Displacement",
    "deviation": "Deviation, + outside",
}
#: Kinds of layers that are solver results (the toolbar's Run list).
RESULT_KINDS = ("envelopelab-preview", "calculix")


def _tool_button(text: str, tip: str, checkable: bool = True) -> QToolButton:
    """A button of the tool rail (checkable tools stay pressed while active)."""
    button = QToolButton()
    button.setText(text)
    button.setToolTip(tip)
    button.setAccessibleName(tip.split(":")[0])
    button.setCheckable(checkable)
    button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
    return button


def _add_view_cube(plotter: Any) -> None:
    """The orientation cube in the corner of the view (click a face to look along it).

    It needs VTK 9.1 or newer; without it the view buttons and keys still work.
    """
    try:
        plotter.add_camera_orientation_widget()
    except (AttributeError, TypeError, ImportError):
        pass


def _swatch(color: str) -> QIcon:
    """A small square of ``color`` for the layer list."""
    pixmap = QPixmap(12, 12)
    pixmap.fill(QColor(color))
    return QIcon(pixmap)


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
    """The 3D view panel (see module docstring).

    Signals
    -------
    rerunRequested(str)
        The banner's action asks for a solve with this solver (``envelopelab-preview``
        or ``calculix``).
    """

    rerunRequested = Signal(str)  # noqa: N815 (Qt naming)

    def __init__(
        self,
        controller: WorkspaceController,
        enable_renderer: bool = True,
        defer_renderer: bool = False,
    ) -> None:
        super().__init__()
        self.controller = controller
        self.layers: dict[str, Layer] = {}
        #: Layer visibility the user set in the list (kept when the layers are rebuilt).
        self._chosen_visibility: dict[str, bool] = {}
        self.plotter: Any = None
        self.layer_list = QListWidget()
        self.layer_list.setObjectName("layerList")
        self.layer_list.itemChanged.connect(self._visibility_changed)
        # Tools: checkable buttons on the rail left of the view.
        self.section = _tool_button("Section", "Section plane: clip the result layers")
        self.section.toggled.connect(self.redraw)
        self.spline = _tool_button("Profile", "Edit profile (spline widget)")
        self.spline.toggled.connect(self.redraw)
        self.pick = _tool_button(
            "Probe", "Pick zones and tapes: click an element to show its zone and values"
        )
        self.pick.toggled.connect(self._toggle_pick)
        self.drag_shapes = _tool_button(
            "Drag",
            "Drag special shapes: press on a special shape and drag it over the envelope; "
            "release to place it (one undo step). Press elsewhere to orbit the camera.",
        )
        self.drag_shapes.toggled.connect(self._toggle_drag)
        self.drag: ShapeDrag | None = None
        self._drag_observers: list[tuple[Any, int]] = []
        reset = _tool_button("Reset", "Reset camera", checkable=False)
        reset.clicked.connect(self._reset_camera)
        rail = QWidget()
        rail.setObjectName("toolRail")
        rail_layout = QVBoxLayout(rail)
        rail_layout.setContentsMargins(4, 4, 4, 4)
        rail_layout.setSpacing(4)
        for w in (self.pick, self.drag_shapes, self.spline, self.section, reset):
            rail_layout.addWidget(w)
        rail_layout.addStretch(1)
        # Toolbar: which run, what to colour by, how to draw.
        self.run_choice = QComboBox()
        self.run_choice.setObjectName("runChoice")
        self.run_choice.setToolTip("Result layer that the colour, banner and run details describe")
        self.run_choice.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.run_choice.setMinimumContentsLength(24)
        self.run_choice.activated.connect(lambda _i: self._result_changed())
        self.field_choice = QComboBox()
        self.field_choice.setObjectName("fieldChoice")
        self.field_choice.setToolTip("Colour the chosen result by a field")
        self.field_choice.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.field_choice.activated.connect(lambda _i: self._result_changed())
        self.display_mode = QComboBox()
        self.display_mode.setObjectName("displayMode")
        self.display_mode.addItems(DISPLAY_MODES)
        self.display_mode.activated.connect(lambda _i: self.redraw())
        screenshot = QPushButton("Screenshot…")
        screenshot.setObjectName("screenshot")
        screenshot.setToolTip("Save the 3D view as a PNG image")
        screenshot.clicked.connect(self._screenshot_clicked)
        toolbar = QWidget()
        toolbar.setObjectName("panelToolbar")
        bar = QHBoxLayout(toolbar)
        bar.setContentsMargins(8, 4, 8, 4)
        for text, choice in (
            ("Run:", self.run_choice),
            ("Colour by:", self.field_choice),
            ("Display:", self.display_mode),
        ):
            bar.addWidget(QLabel(text))
            bar.addWidget(choice)
        bar.addStretch(1)
        bar.addWidget(screenshot)
        self.banner = StatusBanner()
        self.banner.actionTriggered.connect(self._banner_action)
        self._banner_request = ""
        # Viewpoints: standard views, one-gore turns about the envelope axis, projection.
        self.view_buttons: dict[str, QPushButton] = {}
        #: View keys and their actions, also caught on the render widget (VTK would take
        #: the key presses there: its 3 toggles stereo rendering).
        self.view_keys: dict[str, Callable[[], None]] = {}
        views = QHBoxLayout()
        views.setSpacing(2)
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
        places.setSpacing(4)
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
        camera_bar = QWidget()
        camera_bar.setObjectName("cameraBar")
        camera_layout = QVBoxLayout(camera_bar)
        camera_layout.setContentsMargins(8, 4, 8, 4)
        camera_layout.setSpacing(2)
        camera_layout.addLayout(views)
        camera_layout.addLayout(places)
        #: Where saved viewpoints are kept (the main window's settings); None keeps them
        #: for this session only.
        self.settings: QSettings | None = None
        self._session_views: dict[str, list[dict[str, object]]] = {}
        self.info = QLabel()
        self.info.setObjectName("probeInfo")
        self.info.setWordWrap(True)
        self.info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        # Side panel: layers, run details and the probe read-out.
        self.run_details = QLabel()
        self.run_details.setObjectName("runDetails")
        self.run_details.setWordWrap(True)
        self.run_details.setTextFormat(Qt.TextFormat.RichText)
        self.run_details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        side = QWidget()
        side.setObjectName("sidePanel")
        side.setMinimumWidth(280)
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(8, 8, 8, 8)
        side_title = QLabel("Layers")
        side_title.setObjectName("cardTitle")
        side_layout.addWidget(side_title)
        self.layer_list.setMinimumHeight(120)
        self.layer_list.setMaximumHeight(220)
        side_layout.addWidget(self.layer_list)
        for title, body in (("Run details", self.run_details), ("Probe", self.info)):
            card = QFrame()
            card.setObjectName("card")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(10, 8, 10, 8)
            heading = QLabel(title)
            heading.setObjectName("cardTitle")
            card_layout.addWidget(heading)
            card_layout.addWidget(body)
            side_layout.addWidget(card)
        side_layout.addStretch(1)
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
            _add_view_cube(interactor)
        else:
            self.renderer_widget = QLabel(NO_RENDERER_TEXT)
            self.renderer_widget.setWordWrap(True)
            self.renderer_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
        viewport = QWidget()
        viewport_layout = QHBoxLayout(viewport)
        viewport_layout.setContentsMargins(4, 4, 0, 4)
        viewport_layout.setSpacing(4)
        viewport_layout.addWidget(rail)
        self._viewport_layout = viewport_layout
        viewport_layout.addWidget(self.renderer_widget, 1)
        side_scroll = QScrollArea()
        side_scroll.setWidget(side)
        side_scroll.setWidgetResizable(True)
        side_scroll.setFrameShape(QFrame.Shape.NoFrame)
        side_scroll.setMinimumWidth(300)
        splitter.addWidget(viewport)
        splitter.addWidget(side_scroll)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(toolbar)
        layout.addWidget(self.banner)
        layout.addWidget(splitter, 1)
        layout.addWidget(camera_bar)
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
        #: Deviation interpolated onto the design surface, and what it was made for.
        self._deviation_cache: tuple[tuple[Any, ...], np.ndarray] | None = None
        #: Fields of the chosen result run (key to field), and why others are missing.
        self.fields: dict[str, ResultField] = {}
        self.missing: dict[str, str] = {}
        self.refresh()

    def load_renderer(self) -> bool:
        """Start the deferred 3D renderer (see ``defer_renderer``); True when it runs."""
        if not self._renderer_pending:
            return self.plotter is not None
        self._renderer_pending = False
        if not pyvista_available():
            label = self.renderer_widget
            assert isinstance(label, QLabel)
            label.setText(NO_RENDERER_TEXT)
            label.setWordWrap(True)
            return False
        interactor = _interactor(self)
        interactor.installEventFilter(self)
        old = self.renderer_widget
        self._viewport_layout.replaceWidget(old, interactor)
        old.deleteLater()
        self.plotter = interactor
        self.renderer_widget = interactor
        _add_view_cube(interactor)
        self.redraw()
        if self.drag_shapes.isChecked():
            self._toggle_drag(True)  # ticked before the renderer was there
        return True

    # -- layers -------------------------------------------------------------------------

    def refresh(self) -> None:
        """Rebuild the layers from the session (the visibility the user chose is kept; other
        layers take their default)."""
        visible = dict(self._chosen_visibility)
        self.layers = {}
        #: Run record of each result layer (key to record; shape simulations too).
        self._records: dict[str, Any] = {}
        #: A shape simulation layer's simulation and designed skin (envelope frame, m).
        self._shape_runs: dict[str, tuple[Any, Any]] = {}
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
                self._records[solver] = record
        if self._reference_path is not None:
            self._load_reference(self._reference_path)
        for key, value in visible.items():
            if key in self.layers:
                self.layers[key].visible = value
        self._fill_list()
        self._fill_results()
        self.seam_number.setMaximum(self._gore_count())
        self._fill_saved()
        self.redraw()

    def _shape_layers(self) -> None:
        """Special shapes as sewn: the latest simulation of each shape (the skin sewn from
        its cut pieces and inflated, kept with the project) and the designed shape, both
        drawn piece by piece in the skin fabric's colour with their seams. The designed
        layer starts hidden while a current simulation is shown."""
        from envelopelab.features.scene import designed_display

        service = self.controller.shapes
        session = self.controller.session
        design = self.controller.design
        host = design if design is not None and design.gores is not None else None
        specs = {s.name: s for s in session.state.shapes} if session is not None else {}
        designed: dict[str, Any] = {}
        for name in service.keys:
            result = service.result(name)
            if result is None or result.design is None:
                continue
            shown = designed_display(result.design)
            designed[name] = shown
            # Sit the shape and its feed holes on the drawn envelope (display only).
            shift = display_offset(host, result.design) if host else np.zeros(3)
            holes = feed_hole_rings(host, result.design) if host else []
            lines = self._shifted_lines(shown, shift)
            if holes:
                lines["feed_holes"] = holes
            layer = Layer(
                f"shape:{name}",
                "shape",
                f"Special shape {name} (as designed, current)"
                + (f", {len(holes)} feed hole(s)" if holes else ""),
                shown.points + shift,
                shown.triangles,
                polylines=lines,
                face_colors=self._piece_colors(shown, specs.get(name), result.design),
            )
            layer.visible = service.simulation_status(name) != "current"
            self.layers[layer.key] = layer
        for name, sim in service.simulations.items():
            result = service.result(name)
            if name not in service.keys or result is None or result.design is None:
                continue
            placed = result.design  # the shape as placed now (offset and fabric)
            shown = sim.display
            shift = display_offset(host, placed) if host else np.zeros(3)
            stale = service.simulation_status(name) != "current"
            converged = bool(sim.record.converged)
            solver = SOLVER_LABELS.get(sim.record.solver, sim.record.solver)
            label = f"Special shape {name} as sewn and inflated ({solver})"
            if not converged:
                label += " [NOT CONVERGED]"
            if stale:
                label += " [STALE]"
            key = f"shape-sim:{name}"
            self._records[key] = sim.record
            self._shape_runs[key] = (sim, designed.get(name) or designed_display(placed))
            self.layers[key] = Layer(
                key,
                "shape-simulated",
                label,
                shown.points + shift,
                shown.triangles,
                stale,
                converged,
                polylines=self._shifted_lines(shown, shift),
                face_colors=self._piece_colors(shown, specs.get(name), placed),
            )

    @staticmethod
    def _shifted_lines(shown: Any, shift: np.ndarray) -> dict[str, list[np.ndarray]]:
        """Seams and rim of a shape display, moved by the display offset."""
        return {
            "skin_seams": [s + shift for s in shown.seams],
            "skin_rim": [shown.rim + shift] if len(shown.rim) else [],
        }

    def _piece_colors(self, shown: Any, spec: Any, placed: Any) -> np.ndarray | None:
        """Skin fabric colour per triangle, every second piece darker (display only)."""
        session = self.controller.session
        if session is None or spec is None or session.design.gores is None:
            return None
        fabric_id = shape_fabrics(spec, session.design, session.patterns, placed)[1]
        fabric = self.controller.fabrics.fabric(fabric_id) if fabric_id else None
        color = QColor(fabric.color) if fabric is not None else QColor(LAYER_COLORS["shape"])
        if not color.isValid():
            color = QColor(LAYER_COLORS["shape"])
        rgb = np.tile(
            np.array([color.red(), color.green(), color.blue()], dtype=float),
            (len(shown.piece), 1),
        )
        rgb[shown.piece % 2 == 1] *= ALTERNATE_GORE_SHADE
        return np.asarray(rgb.astype(np.uint8))

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
            item = QListWidgetItem(layer.display_name)
            item.setToolTip(layer.label)
            item.setData(Qt.ItemDataRole.UserRole, key)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if layer.visible else Qt.CheckState.Unchecked)
            item.setForeground(QBrush(QColor(layer.color).darker(130)))
            item.setIcon(_swatch(layer.color))
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
            self._chosen_visibility[key] = self.layers[key].visible
            self.redraw()

    # -- results: run, field, banner and run details ------------------------------------

    def _result_key(self) -> str | None:
        """Key of the result layer chosen in the toolbar (None without results)."""
        key = self.run_choice.currentData()
        return key if isinstance(key, str) and key in self.layers else None

    def _current_model(self) -> Any:
        """The solver model of the current design state (None when it is not current)."""
        cache = self.controller.model_cache
        if cache is None or self.controller.artifact_status("rest_mesh") != "current":
            return None
        return cache.built.model

    def _fill_results(self) -> None:
        """Fill the Run and Colour-by lists (keeping the user's choice where it still
        exists), then the fields, the banner and the run details."""
        chosen_run = self.run_choice.currentData()
        self.run_choice.blockSignals(True)
        self.run_choice.clear()
        keys = [k for k in RESULT_KINDS if k in self.layers]
        keys += sorted(k for k in self.layers if k.startswith("shape-sim:"))
        for key in keys:
            if key in self.layers:
                result = self.layers[key]
                self.run_choice.addItem(result.display_name, key)
                self.run_choice.setItemData(
                    self.run_choice.count() - 1, result.label, Qt.ItemDataRole.ToolTipRole
                )
        if self.run_choice.count() == 0:
            self.run_choice.addItem("No result yet: run the preview", None)
        index = self.run_choice.findData(chosen_run) if chosen_run else -1
        if index < 0:
            # Prefer a current, converged run: that is the one to read values from.
            good = [
                i
                for i in range(self.run_choice.count())
                if (layer := self.layers.get(str(self.run_choice.itemData(i)))) is not None
                and not layer.stale
                and layer.converged
            ]
            index = good[0] if good else 0
        self.run_choice.setCurrentIndex(index)
        self.run_choice.setEnabled(self._result_key() is not None)
        self.run_choice.blockSignals(False)
        self._update_fields()

    def _result_changed(self) -> None:
        self._update_fields()
        self.redraw()

    def _update_fields(self) -> None:
        """Fields of the chosen run and the Colour-by list (fields a run cannot give are
        listed but disabled, with the reason as tooltip)."""
        chosen = self.field_choice.currentData()
        key = self._result_key()
        record = self._records.get(key) if key is not None else None
        session = self.controller.session
        self.fields, self.missing = {}, {}
        if record is not None and session is not None:
            layer = self.layers[key] if key is not None else None
            shape = self._shape_runs.get(key) if key is not None else None
            arrays = (
                (shape[0].arrays or session.run_arrays(record.run_id))
                if shape is not None
                else session.run_arrays(record.run_id)
            )
            if arrays is not None and layer is not None:
                if not layer.converged:
                    reason = "not converged: values are not final"
                    self.missing = dict.fromkeys(FIELD_LABELS, reason)
                elif layer.stale:
                    reason = "stale: the design has changed since this run"
                    self.missing = dict.fromkeys(FIELD_LABELS, reason)
                elif shape is not None:
                    designed = shape[1]
                    self.fields = shape_run_fields(arrays, designed.points, designed.triangles)
                    self.missing = shape_missing_fields(arrays)
                else:
                    model = self._current_model()
                    design = session.design if session.design.gores is not None else None
                    self.fields = run_fields(arrays, model, design)
                    self.missing = missing_fields(arrays, model, record.solver, design)
        self.field_choice.blockSignals(True)
        self.field_choice.clear()
        self.field_choice.addItem(LAYER_COLOUR, None)
        items = self.field_choice.model()
        for name, label in FIELD_LABELS.items():
            if name not in self.fields and name not in self.missing:
                continue
            if name in DISPLAY_UNITS:  # the list says the unit the scale shows
                label = label.rsplit("[", 1)[0] + f"[{DISPLAY_UNITS[name][1]}]"
            self.field_choice.addItem(label, name)
            i = self.field_choice.count() - 1
            if name in self.missing:
                self.field_choice.setItemData(i, self.missing[name], Qt.ItemDataRole.ToolTipRole)
                if isinstance(items, QStandardItemModel):
                    item = items.item(i)
                    if item is not None:
                        item.setEnabled(False)
        index = self.field_choice.findData(chosen) if chosen in self.fields else -1
        if index < 0:
            first = next((f for f in SAFETY_FIELDS if f in self.fields), None)
            index = self.field_choice.findData(first) if first else 0
        self.field_choice.setCurrentIndex(max(index, 0))
        self.field_choice.blockSignals(False)
        self._update_status()

    def shown_field(self) -> ResultField | None:
        """The field the chosen result is coloured by (None: layer colour)."""
        name = self.field_choice.currentData()
        return self.fields.get(name) if isinstance(name, str) else None

    def run_state(self) -> RunState | None:
        """Facts about the chosen run for the status banner (None without a run)."""
        key = self._result_key()
        record = self._records.get(key) if key is not None else None
        session = self.controller.session
        if key is None or record is None or session is None:
            return None
        layer = self.layers[key]
        failing: list[str] = []
        lows: list[float] = []
        shape = key.startswith("shape-sim:")
        model = None if shape else self._current_model()
        for name, direction in zip(SAFETY_FIELDS, ("warp", "weft"), strict=True):
            field = self.fields.get(name)
            if field is None or (model is None and not shape):
                continue
            zone_of = (
                [f"{layer.short.removesuffix(' (inflated)')} skin"] * len(field.values)
                if model is None
                else [model.zone_names[int(i)] for i in model.tri_zone]
            )
            failing += failing_zone_names(field.values, zone_of, direction, FOS_LIMIT)
            finite = field.values[np.isfinite(field.values)]
            if finite.size:
                lows.append(float(finite.min()))
        verified = (
            record.solver == "calculix"
            if shape
            else any(
                r.solver == "calculix" and r.converged and session.run_status(r) == "current"
                for r in session.project.runs
            )
        )
        return RunState(
            solver=record.solver,
            solver_label=SOLVER_LABELS.get(record.solver, record.solver),
            run_id=record.run_id,
            converged=layer.converged,
            stale=layer.stale,
            status=record.status,
            iterations=record.iterations,
            residual=record.residual,
            errors=tuple(f.message for f in record.findings if f.severity == "error"),
            warnings=tuple(f.message for f in record.findings if "exceed" in f.code),
            failing_zones=tuple(failing),
            min_fos=min(lows) if lows else None,
            limit=FOS_LIMIT,
            limit_source=FOS_LIMIT_SOURCE,
            verified=verified,
        )

    def _update_status(self) -> None:
        """The banner and the run details for the chosen run."""
        banner = banner_for(self.run_state())
        if banner is None:
            self.banner.clear()
            self._banner_request = ""
        else:
            self.banner.set_status(banner.kind, banner.title, banner.message, banner.action)
            self._banner_request = banner.request
        key = self._result_key()
        record = self._records.get(key) if key is not None else None
        if record is None:
            self.run_details.setText("No solver result for this design yet.")
            return
        sources = ", ".join(
            f"<b>{escape(s)}</b>" if s == "assumed" else escape(s) for s in record.material_sources
        )
        rows = (
            (
                "Solver",
                f"{SOLVER_LABELS.get(record.solver, record.solver)} "
                f"{record.solver_version}".strip(),
            ),
            (
                "Status",
                record.status
                if record.converged and record.status == "converged"
                else f"{record.status} (NOT converged)"
                if not record.converged
                else f"{record.status} (converged)",
            ),
            ("Iterations", f"{record.iterations}"),
            ("Residual", f"{record.residual:.2e}"),
            (
                "Mesh",
                f"{record.n_nodes} nodes, {record.n_elements} elements"
                + (
                    f", {record.n_tape_elements} tape elements"
                    if hasattr(record, "n_tape_elements")
                    else ""
                ),
            ),
            ("Load case", record.load_case),
            ("Run time", f"{record.run_time:.1f} s"),
        ) + ((("Volume", f"{record.volume:.1f} m³"),) if hasattr(record, "volume") else ())
        body = "".join(f"<tr><td>{escape(k)}&nbsp;</td><td>{escape(v)}</td></tr>" for k, v in rows)
        body += f"<tr><td>Materials&nbsp;</td><td>{sources or '—'}</td></tr>"
        self.run_details.setText(f"<table>{body}</table>")
        self.run_details.setToolTip(f"Residual: {record.residual_measure}")

    def _banner_action(self) -> None:
        if self._banner_request:
            self.rerunRequested.emit(self._banner_request)

    def save_screenshot(self, path: str) -> bool:
        """Save the 3D view as an image; False without a renderer."""
        if self.plotter is None:
            return False
        self.plotter.screenshot(path)
        return True

    def _screenshot_clicked(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save 3D view", "", "PNG image (*.png)")
        if path:
            if not path.lower().endswith(".png"):
                path += ".png"
            if not self.save_screenshot(path):
                self.info.setText("No 3D view to save (rendering is not available).")

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
                    legend.append([layer.legend_name, layer.color])
            if not layer.visible or len(layer.faces) == 0:
                continue
            faces = np.hstack([np.full((len(layer.faces), 1), 3), layer.faces]).ravel()
            mesh = pv.PolyData(np.asarray(layer.points, dtype=float), faces)
            mode = self.display_mode.currentText()
            wire = layer.kind == "rest" or mode == "Wireframe"
            style = "wireframe" if wire else "surface"
            with_edges = mode == "Shaded + mesh edges"
            opacity = 0.35 if layer.kind == "reference" else 1.0
            deviation = self._design_deviation(layer)
            if deviation is not None:
                # The deviation from the design is drawn on the design surface itself.
                plotter.add_mesh(
                    mesh,
                    name=layer.key,
                    show_edges=with_edges,
                    style=style,
                    **self._deviation_kwargs(mesh, deviation),
                )
                legend.append([layer.legend_name, layer.color])
                continue
            coloured = layer.key == self._result_key() and self.shown_field() is not None
            if layer.face_colors is not None and not layer.stale and not coloured:
                mesh.cell_data["rgb"] = layer.face_colors
                plotter.add_mesh(
                    mesh,
                    scalars="rgb",
                    rgb=True,
                    name=layer.key,
                    show_edges=with_edges,
                    style=style,
                )
                legend.append([layer.legend_name, layer.color])
                continue
            colour_by = self.shown_field() if layer.key == self._result_key() else None
            if colour_by is not None and colour_by.name in DIVERGING_FIELDS and self._on_design():
                # The design surface carries the colours: the result is a faint outline.
                colour_by = None
                style, opacity = "wireframe", 0.25
            kwargs: dict[str, Any]
            if colour_by is not None and not layer.stale and layer.converged:
                kwargs = self._field_kwargs(mesh, colour_by)
            else:
                kwargs = {"color": layer.color}
            kwargs.update(style=style, opacity=opacity)
            if colour_by is not None and "scalars" in kwargs:
                kwargs["show_edges"] = with_edges  # edges would hide the colours
            if not layer.converged:
                # Never drawn like a normal result: red mesh edges over the layer colour.
                kwargs.update(show_edges=True, edge_color="#b42318")
            if self.section.isChecked() and layer.kind != "design":
                plotter.add_mesh_clip_plane(mesh, **kwargs)
            else:
                kwargs.setdefault("show_edges", with_edges or layer.kind not in SMOOTH_KINDS)
                plotter.add_mesh(mesh, name=layer.key, **kwargs)
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
            legend.append([layer.legend_name, layer.color])
        if legend:
            # Lower left: the view cube is top right and the colour scale on the right.
            # VTK scales the text to fill the box: keep it small for the short names.
            height = min(0.04 * len(legend), 0.2)
            plotter.add_legend(legend, bcolor="white", size=(0.22, height), loc="lower left")
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

    def _field_kwargs(self, mesh: Any, field: ResultField) -> dict[str, Any]:
        """``add_mesh`` arguments that colour ``mesh`` by ``field``, with its scalar bar.

        Factors of safety and the wrinkle state are drawn in bands (values below the limit
        always in the fail colour); other fields on a continuous colour map, in the units
        of :data:`DISPLAY_UNITS`.
        """
        scale, unit = DISPLAY_UNITS.get(field.name, (1.0, field.unit))
        title = SHORT_TITLES[field.name] + (f" [{unit}]" if unit != "-" else "")
        data = mesh.cell_data if field.location == "triangle" else mesh.point_data
        bands: Bands | None = None
        if field.name in SAFETY_FIELDS:
            bands = fos_bands(field.values, FOS_LIMIT)
            title += f"\nlimit {FOS_LIMIT:g} ({FOS_LIMIT_SOURCE})"
        elif field.name == "wrinkle_state":
            bands = wrinkle_bands(field.values)
        bar = {
            "title": title,
            "vertical": True,
            "position_x": 0.84,
            "position_y": 0.08,
            "height": 0.5,
            "width": 0.06,
            "title_font_size": 14,
            "label_font_size": 12,
        }
        if bands is not None:
            n = len(bands.colors)
            data["field"] = bands.index.astype(np.float64)
            return {
                "scalars": "field",
                "cmap": list(bands.colors),
                "clim": (-0.5, n - 0.5),
                "n_colors": n,
                "annotations": {float(i): text for i, text in enumerate(bands.labels)},
                "scalar_bar_args": {**bar, "n_labels": 0},
            }
        data["field"] = np.asarray(field.values, dtype=np.float64) * scale
        if field.name in DIVERGING_FIELDS:
            return self._deviation_kwargs(mesh, np.asarray(field.values), data=data)
        return {
            "scalars": "field",
            "cmap": CONTINUOUS_CMAP,
            "scalar_bar_args": {**bar, "fmt": "%.3g"},
        }

    def _design_key(self) -> str:
        """The layer of the chosen run's design: the envelope's design surface, or a
        special shape's designed skin."""
        key = self._result_key() or ""
        if key.startswith("shape-sim:"):
            return "shape:" + key.removeprefix("shape-sim:")
        return "design"

    def _on_design(self) -> bool:
        """The deviation is drawn on the design surface (shown and current)."""
        design = self.layers.get(self._design_key())
        return design is not None and design.visible and not design.stale

    def _design_deviation(self, layer: Layer) -> np.ndarray | None:
        """Deviation (m) at the design surface's points when ``layer`` is the design
        surface and it is coloured by the deviation, else None. Interpolated linearly from
        the result's nodes (where the deviation is exact) for display."""
        field = self.shown_field()
        key = self._result_key()
        if (
            layer.key != self._design_key()
            or field is None
            or field.name not in DIVERGING_FIELDS
            or key is None
            or not self._on_design()
        ):
            return None
        result = self.layers[key]
        cache_key = (key, self.controller.revision, len(layer.points))
        if self._deviation_cache is None or self._deviation_cache[0] != cache_key:
            values = interpolate_on_mesh(layer.points, result.points, result.faces, field.values)
            self._deviation_cache = (cache_key, values)
        return self._deviation_cache[1]

    def _deviation_kwargs(self, mesh: Any, values: np.ndarray, data: Any = None) -> dict[str, Any]:
        """``add_mesh`` arguments for a deviation (m, per point): diverging colours
        symmetric about zero, in mm, red outside the design and blue inside."""
        mm = np.asarray(values, dtype=np.float64) * 1000.0
        (mesh.point_data if data is None else data)["field"] = mm
        # The scale comes from the exact values at the result's nodes, so interpolating
        # onto the design surface never hides the largest deviation.
        field = self.shown_field()
        exact = field.values * 1000.0 if field is not None and field.name == "deviation" else mm
        finite = exact[np.isfinite(exact)]
        limit = max(float(np.abs(finite).max()), 1.0) if finite.size else 1.0
        title = "Deviation [mm]\n+ outside, - inside"
        return {
            "scalars": "field",
            "cmap": DIVERGING_CMAP,
            "clim": (-limit, limit),
            "nan_color": "#c7c7c7",
            "scalar_bar_args": {
                "title": title,
                "vertical": True,
                "position_x": 0.84,
                "position_y": 0.08,
                "height": 0.5,
                "width": 0.06,
                "title_font_size": 14,
                "label_font_size": 12,
                "fmt": "%.0f",
            },
        }

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
        text = f"element {tri}: material zone {zone}"
        for name, shown_field in self.fields.items():
            if shown_field.location == "triangle" and tri < len(shown_field.values):
                scale, unit = DISPLAY_UNITS.get(name, (1.0, shown_field.unit))
                value = float(shown_field.values[tri]) * scale
                label = FIELD_LABELS[name].rsplit(" [", 1)[0]
                shown = "unloaded" if math.isinf(value) else f"{value:.3g} {unit}".rstrip(" -")
                if name in SAFETY_FIELDS and value < FOS_LIMIT:
                    shown += f" — BELOW LIMIT {FOS_LIMIT:g}"
                text += f"\n{label}: {shown}"
        self.info.setText(text)

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
