"""Colours mode: paint every panel of the envelope and of the special shapes (ADR-0055).

A tool bar over the panel grid (:mod:`envelopelab_app.colour_grid`), the balloon in 3D
(:class:`~envelopelab_app.placement_view.EnvelopeInlay`, painted as you go) and the colour
picker (:mod:`envelopelab_app.colour_picker`) beside it:

* **Paint** (P) paints the panels clicked or dragged over (on a row cut as half gores,
  the half clicked: each half may have its own colour); **Fill row** (R) every panel
  of the row clicked (every piece of a shape's tier); **Fill gore** (G) every panel of
  the gore clicked (every tier of a shape's piece); **Eyedropper** (I) takes the colour
  of the panel clicked and goes back to the previous tool;
* **Repeat every N gores** also paints every N-th gore (or shape piece) round from the
  one clicked, for repeating patterns (0: off);
* **Fill everything** paints every panel; **Clear all** removes every colour;
* **Show on the 3D views** draws the colours on the balloon in every 3D view (the inlays,
  On the balloon, 3D / Simulation); off, they show the fabric shades as before.

Every paint is one undo step (:func:`envelopelab.project.edits.paint_panels`). Colours
are a visual layer (:mod:`envelopelab.project.colours`): they never make patterns or
simulations stale. The recent colours are kept in the application settings.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from envelopelab.project.colours import (
    PanelRef,
    Scope,
    ShapeGrid,
    coloured_panels,
    envelope_cells,
    envelope_targets,
    shape_grid,
)
from envelopelab.project.placement_map import gore_map
from envelopelab_app.colour_grid import ColourGridView, grid_scene
from envelopelab_app.colour_picker import ColourPicker
from envelopelab_app.controller import WorkspaceController
from envelopelab_app.placement_view import EnvelopeInlay
from envelopelab_app.refresh import Refresher

#: Tools: key, button text, shortcut, scope of a click, tooltip.
TOOLS: tuple[tuple[str, str, str, Scope, str], ...] = (
    ("paint", "🖌 Paint", "P", "panel", "Paint the panels you click or drag over (P)"),
    ("row", "▤ Fill row", "R", "row", "Paint every panel of the row (shape: tier) clicked (R)"),
    (
        "gore",
        "▥ Fill gore",
        "G",
        "gore",
        "Paint every panel of the gore (shape: piece) clicked (G)",
    ),
    ("pick", "💧 Eyedropper", "I", "panel", "Take the colour of the panel clicked (I)"),
)
#: Settings key of the recent colours.
RECENT_KEY = "colours/recent"


class ColoursPanel(QWidget):
    """See module docstring."""

    def __init__(self, controller: WorkspaceController, gpu: bool = False) -> None:
        super().__init__()
        self.controller = controller
        #: Application settings (recent colours); None: kept for this session only.
        self.settings: QSettings | None = None
        self._grids: dict[str, ShapeGrid] = {}
        self._envelope_key: object = None
        self._envelope: list[Any] = []
        self._map: Any = None
        self.tool = "paint"
        self._before_pick = "paint"

        self.grid = ColourGridView()
        self.grid.targets = self.targets
        self.grid.stroked.connect(self._stroked)
        self.picker = ColourPicker()
        self.picker.colourChanged.connect(self._colour_changed)
        self.picker.replaceRequested.connect(self._replace)
        self.grid.brush = self.picker.colour

        bar = QHBoxLayout()
        bar.setSpacing(4)
        self.tool_buttons: dict[str, QToolButton] = {}
        group = QButtonGroup(self)
        group.setExclusive(True)
        for key, text, shortcut, _scope, tip in TOOLS:
            b = QToolButton()
            b.setObjectName(f"colourTool_{key}")
            b.setText(text)
            b.setCheckable(True)
            b.setToolTip(tip)
            b.clicked.connect(lambda _c=False, k=key: self.set_tool(k))
            group.addButton(b)
            bar.addWidget(b)
            self.tool_buttons[key] = b
            sc = QShortcut(QKeySequence(shortcut), self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(lambda k=key: self.set_tool(k))
        bar.addSpacing(12)
        bar.addWidget(QLabel("Repeat every"))
        self.repeat = QSpinBox()
        self.repeat.setObjectName("colourRepeat")
        self.repeat.setRange(0, 64)
        self.repeat.setSpecialValueText("off")
        self.repeat.setSuffix(" gores")
        self.repeat.setToolTip(
            "Also paint every N-th gore (or shape piece) round from the one clicked, for "
            "repeating patterns (off: only the one clicked)"
        )
        self.repeat.valueChanged.connect(lambda _v: self.grid.update())
        bar.addWidget(self.repeat)
        bar.addStretch(1)
        bar2 = QHBoxLayout()
        bar2.setSpacing(4)
        fill_all = QPushButton("Fill everything")
        fill_all.setObjectName("colourFillAll")
        fill_all.setToolTip("Paint every panel of the envelope and of every shape")
        fill_all.clicked.connect(self.fill_all)
        clear = QPushButton("Clear all")
        clear.setObjectName("colourClearAll")
        clear.setToolTip("Remove every panel colour (undoable)")
        clear.clicked.connect(lambda _c=False: self.controller.edit("clear_colours"))
        bar2.addWidget(fill_all)
        bar2.addWidget(clear)
        self.show_3d = QCheckBox("Show on the 3D views")
        self.show_3d.setObjectName("colourShow3d")
        self.show_3d.setChecked(controller.show_panel_colours)
        self.show_3d.setToolTip(
            "Draw the panel colours on the balloon in every 3D view (off: fabric shades)"
        )
        self.show_3d.toggled.connect(controller.set_show_panel_colours)
        bar2.addSpacing(12)
        bar2.addWidget(self.show_3d)
        bar2.addStretch(1)
        # The balloon in 3D, painted as you go (nothing is selected in this mode).
        self.inlay = EnvelopeInlay("coloursInlay", controller, gpu, selection=lambda: "")
        self.inlay.caption.hide()
        self.inlay.sketch.setToolTip("The balloon as painted. Drag: turn; wheel: zoom")

        self.status = QLabel()
        self.status.setObjectName("hint")
        self.status.setWordWrap(True)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addLayout(bar)
        left_layout.addLayout(bar2)
        left_layout.addWidget(self.grid, 1)
        left_layout.addWidget(self.status)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setObjectName("coloursSplitter")
        splitter.addWidget(left)
        splitter.addWidget(self.inlay)
        splitter.addWidget(self.picker)
        splitter.setStretchFactor(0, 1)
        splitter.setCollapsible(0, False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)
        self.set_tool("paint")

        self.refresher = Refresher(
            self,
            self.refresh,
            lambda: controller.revision,
            (controller.stateChanged, controller.sessionChanged, controller.fileChanged),
            defer_hidden=lambda: controller.defer_hidden,
        )
        self.refresh()

    # -- settings ---------------------------------------------------------------------

    def load_recent(self) -> None:
        """Read the recent colours from the settings."""
        if self.settings is None:
            return
        value: Any = self.settings.value(RECENT_KEY, [])
        # QSettings returns a one-item list as a plain string (INI files).
        items = [value] if isinstance(value, str) else list(value or [])
        try:
            self.picker.set_recent([str(c) for c in items if c])
        except ValueError:
            self.picker.set_recent([])

    def _remember(self, colour: str | None) -> None:
        if colour is None:
            return
        self.picker.remember(colour)
        if self.settings is not None:
            self.settings.setValue(RECENT_KEY, self.picker.recent)

    # -- tools ------------------------------------------------------------------------

    def set_tool(self, key: str) -> None:
        """Use tool ``key`` (one of :data:`TOOLS`)."""
        if key == "pick" and self.tool != "pick":
            self._before_pick = self.tool
        self.tool = key
        self.tool_buttons[key].setChecked(True)
        self.grid.update()

    def scope(self) -> Scope:
        """What a click paints with the current tool."""
        return next(s for k, _t, _sc, s, _tip in TOOLS if k == self.tool)

    def targets(self, ref: PanelRef) -> list[PanelRef]:
        """The panels a click on ``ref`` paints with the current tool and repeat."""
        if self.tool == "pick":
            return [ref]
        every = self.repeat.value()
        if ref.shape is None:
            m = self._map
            if m is None:
                return [ref]
            rows = [label for label, _s0, _s1 in m.rows]
            return envelope_targets(
                rows, m.gores, ref.group, ref.index, self.scope(), every, ref.half
            )
        grid = self._grids.get(ref.shape)
        return [ref] if grid is None else grid.targets(ref.group, ref.index, self.scope(), every)

    def _colour_changed(self, colour: str) -> None:
        self.grid.brush = colour or None

    def _stroked(self, refs: list[PanelRef]) -> None:
        if self.tool == "pick":
            self.pick(refs[0])
            return
        targets: list[PanelRef] = []
        for ref in refs:
            targets += [t for t in self.targets(ref) if t not in targets]
        self.paint(targets)

    def paint(self, refs: list[PanelRef]) -> None:
        """Paint ``refs`` with the current colour (one undo step)."""
        if not refs:
            return
        colour = self.picker.colour
        self.controller.edit("paint_panels", refs, colour)
        self._remember(colour)

    def pick(self, ref: PanelRef) -> None:
        """Take the colour of panel ``ref`` and go back to the previous tool."""
        session = self.controller.session
        if session is not None:
            self.picker.set_colour(session.state.colours.colour_of(ref))
        self.set_tool(self._before_pick)

    def fill_all(self) -> None:
        """Paint every panel with the current colour."""
        self.paint([ref for ref, _poly in self.grid.scene.cells])

    def _replace(self, old: str, new: str) -> None:
        self.controller.edit("replace_colour", old, new or None)
        self._remember(new or None)

    # -- refresh ----------------------------------------------------------------------

    def _envelope_cells(self) -> None:
        """Rebuild the envelope cells when the envelope's shape changed."""
        session = self.controller.session
        gores = None if session is None else session.design.gores
        halved = tuple(r.letter for r in gores.panel_rows if r.half_gore) if gores else ()
        key = (self.controller.shape_host_hash(), halved) if session else None
        if key == self._envelope_key:
            return
        self._envelope_key = key
        surface = self.controller.envelope_surface()
        self._map = None if surface is None else gore_map(surface)
        self._envelope = [] if self._map is None else envelope_cells(self._map, halved)

    def refresh(self) -> None:
        """Show the current design's panels and colours."""
        session = self.controller.session
        if session is None:
            self._envelope_key, self._map, self._envelope, self._grids = None, None, [], {}
            self.grid.set_scene(grid_scene([], [], 0, 1.0, []))
            self.picker.set_design_colours([])
            self.status.setText("")
            return
        self._envelope_cells()
        grids: dict[str, ShapeGrid] = {}
        for spec in session.state.shapes:
            try:
                grids[spec.name] = shape_grid(spec)
            except ValueError:
                continue
        self._grids = grids
        m = self._map
        scene = grid_scene(
            self._envelope,
            [] if m is None else m.rows,
            0 if m is None else m.gores,
            1.0 if m is None else m.column,
            list(grids.values()),
        )
        self.grid.set_scene(scene)
        colours = session.state.colours
        self.grid.set_colours(colours)
        used = colours.used()
        counts = [sum(1 for _r, c in coloured_panels(colours) if c == u) for u in used]
        self.picker.set_design_colours(used, counts)
        notes = []
        if m is None:
            notes.append("The envelope cannot be drawn (no standard-gore design to colour).")
        notes.append(
            "Colours are for display only: they do not change fabrics, mass, patterns or "
            "simulations. Wheel: zoom; right drag: pan; double click: fit."
        )
        self.status.setText(" ".join(notes))


__all__ = ["RECENT_KEY", "TOOLS", "ColoursPanel"]
