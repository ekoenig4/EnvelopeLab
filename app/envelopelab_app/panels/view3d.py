"""3D view: design surface, rigging, rest mesh, preview and CalculiX results, reference mesh.

Every layer has its own colour and a label naming where it comes from; a stale or
unconverged layer says so in its label (and is drawn grey or hatched), so a result is never
mistaken for another solver's or for a current one. The layer list is always available;
the PyVista renderer (orbit, zoom, section plane, picking of zones and tapes, spline
widget for the profile) is used when PyVista, pyvistaqt and OpenGL are available and the
3D view is enabled in the preferences.
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

from envelopelab.project.gore_design import control_arrays, design_profile
from envelopelab.project.model import SOLVER_LABELS, RunRecord
from envelopelab_app.controller import WorkspaceController

#: Layer colours (one per source, never shared).
LAYER_COLORS = {
    "design": "#8c8c8c",
    "rest": "#bcbd22",
    "envelopelab-preview": "#1f77b4",
    "calculix": "#ff7f0e",
    "reference": "#2ca02c",
    "rigging": "#9467bd",
}
#: Line colours of the rigging layer, per element kind.
RIGGING_COLORS = {
    "parachute": "#9467bd",
    "shroud_lines": "#8c564b",
    "centralizing_lines": "#e377c2",
    "red_line": "#d62728",
    "flying_wires": "#17becf",
    "turning_vents": "#e7ba52",
}


@dataclass
class Layer:
    """One displayed mesh.

    Attributes
    ----------
    key : str
        Unique id.
    kind : str
        ``design``, ``rest``, ``envelopelab-preview``, ``calculix`` or ``reference``.
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
        Line-only content (rigging), m, keyed by element kind, optional.
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

    @property
    def color(self) -> str:
        """Display colour (grey when stale)."""
        return "#c7c7c7" if self.stale else LAYER_COLORS[self.kind]


def surface_of_revolution(
    r: np.ndarray, z: np.ndarray, segments: int
) -> tuple[np.ndarray, np.ndarray]:
    """Triangles of a profile swept about the z axis (display only), m."""
    angles = np.linspace(0.0, 2 * math.pi, segments, endpoint=False)
    pts = np.array(
        [
            [ri * math.cos(a), ri * math.sin(a), zi]
            for ri, zi in zip(r, z, strict=True)
            for a in angles
        ]
    )
    faces = []
    for i in range(len(r) - 1):
        for j in range(segments):
            a = i * segments + j
            b = i * segments + (j + 1) % segments
            c = a + segments
            d = b + segments
            faces += [[a, b, d], [a, d, c]]
    return pts, np.array(faces, dtype=np.int64)


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

    def __init__(self, controller: WorkspaceController, enable_renderer: bool = True) -> None:
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
        reset = QPushButton("Reset camera")
        reset.clicked.connect(self._reset_camera)
        self.info = QLabel()
        self.info.setWordWrap(True)
        controls = QHBoxLayout()
        for w in (self.section, self.spline, self.pick, reset):
            controls.addWidget(w)
        side = QWidget()
        side_layout = QVBoxLayout(side)
        side_layout.addWidget(QLabel("Layers"))
        side_layout.addWidget(self.layer_list)
        side_layout.addWidget(self.info)
        splitter = QSplitter()
        self.renderer_widget: QWidget
        if enable_renderer and pyvista_available():
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
        for signal in (
            controller.stateChanged,
            controller.runsChanged,
            controller.artifactsChanged,
            controller.sessionChanged,
        ):
            signal.connect(self.refresh)
        self._reference_path: str | None = None
        self.refresh()

    # -- layers -------------------------------------------------------------------------

    def refresh(self) -> None:
        """Rebuild the layers from the session."""
        visible = {k: layer.visible for k, layer in self.layers.items()}
        self.layers = {}
        session = self.controller.session
        if session is not None and session.design.gores is not None:
            try:
                profile = design_profile(session.design)
                idx = np.linspace(0, len(profile.r) - 1, 60).astype(int)
                pts, faces = surface_of_revolution(
                    profile.r[idx], profile.z[idx], 4 * session.design.gores.count
                )
                self.layers["design"] = Layer(
                    "design", "design", "Design surface (profile, current)", pts, faces
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
                    for line in polylines:
                        plotter.add_mesh(
                            pv.lines_from_points(np.asarray(line, dtype=float)),
                            color=RIGGING_COLORS.get(kind, layer.color),
                            line_width=4 if kind == "red_line" else 2,
                        )
                legend.append([layer.label, layer.color])
            if not layer.visible or len(layer.faces) == 0:
                continue
            faces = np.hstack([np.full((len(layer.faces), 1), 3), layer.faces]).ravel()
            mesh = pv.PolyData(np.asarray(layer.points, dtype=float), faces)
            style = "wireframe" if layer.kind in ("rest", "design") else "surface"
            opacity = 0.35 if layer.kind == "reference" else 1.0
            if self.section.isChecked() and layer.kind != "design":
                plotter.add_mesh_clip_plane(mesh, color=layer.color, style=style, opacity=opacity)
            else:
                plotter.add_mesh(
                    mesh,
                    color=layer.color,
                    style=style,
                    opacity=opacity,
                    show_edges=layer.kind != "design",
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

    def _reset_camera(self) -> None:
        if self.plotter is not None:
            self.plotter.reset_camera()

    def close_renderer(self) -> None:
        """Release the VTK render window."""
        if self.plotter is not None:
            self.plotter.close()
            self.plotter = None
