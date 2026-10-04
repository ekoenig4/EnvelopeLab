"""EnvelopeLab main window: project files, workflow modes, undo/redo, runs, autosave."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QTabBar,
    QVBoxLayout,
    QWidget,
)

from envelopelab.design.model import DesignDocument
from envelopelab.project.dependencies import artifact_inputs
from envelopelab.project.model import PROJECT_SUFFIX
from envelopelab.project.recovery import (
    autosave_file,
    discard,
    find_recoverable,
    read_autosave,
    write_autosave,
)
from envelopelab.project.session import ProjectSession
from envelopelab_app import layout as layout_state
from envelopelab_app.controller import WorkspaceController
from envelopelab_app.dialogs import PreferencesDialog
from envelopelab_app.gore_editor import GoreEditor
from envelopelab_app.layout import MODE_KEYS, MODES
from envelopelab_app.panels.base import UNSAVED_MARK, Panel
from envelopelab_app.panels.design_tree import DesignTreePanel
from envelopelab_app.panels.history import HistoryPanel
from envelopelab_app.panels.materials import MaterialsPanel
from envelopelab_app.panels.patterns import PatternPanel
from envelopelab_app.panels.properties import PropertiesPanel
from envelopelab_app.panels.rigging import RiggingPanel
from envelopelab_app.panels.runs import RunsPanel
from envelopelab_app.panels.shapes import ShapesPanel
from envelopelab_app.panels.validation import ValidationPanel
from envelopelab_app.panels.view3d import View3DPanel
from envelopelab_app.settings import (
    Preferences,
    add_recent_project,
    load_preferences,
    recent_projects,
    save_preferences,
)
from envelopelab_app.simulation import CALCULIX, PREVIEW, SimulationManager
from envelopelab_app.wizard import NewDesignWizard

FILE_FILTER = f"EnvelopeLab projects (*{PROJECT_SUFFIX})"


class MainWindow(QMainWindow):
    """The application window.

    Parameters
    ----------
    settings : QSettings
        Where preferences and recent projects are stored.
    enable_3d : bool, optional
        Override the preference (tests pass False to run without OpenGL).
    interactive : bool
        Ask before discarding changes and offer crash recovery (False in tests).
    """

    def __init__(
        self,
        settings: QSettings,
        enable_3d: bool | None = None,
        interactive: bool = True,
    ) -> None:
        super().__init__()
        self.settings = settings
        self.prefs: Preferences = load_preferences(settings)
        self.interactive = interactive
        self.instance_id = uuid.uuid4().hex
        self.controller = WorkspaceController(self.prefs)
        self.controller.defer_hidden = interactive
        self.simulation = SimulationManager(self.controller)
        self.setWindowTitle("EnvelopeLab")
        self.resize(1500, 950)

        self.gore_editor = GoreEditor(self.controller)
        use_3d = self.prefs.enable_3d if enable_3d is None else enable_3d
        self.design_tree = DesignTreePanel(self.controller)
        self.properties = PropertiesPanel(self.controller)
        self.validation = ValidationPanel(self.controller)
        self.runs = RunsPanel(self.controller, self.simulation)
        self.materials = MaterialsPanel(self.controller)
        self.view3d = View3DPanel(
            self.controller, enable_renderer=use_3d, defer_renderer=interactive
        )
        self.patterns = PatternPanel(self.controller)
        self.history = HistoryPanel(self.controller)
        self.rigging = RiggingPanel(self.controller)
        self.shapes = ShapesPanel(self.controller)
        pattern_scope = artifact_inputs("patterns")
        self.panels: dict[str, Panel] = {
            "tree": Panel("Design Tree", self.controller, self.design_tree),
            "properties": Panel("Properties", self.controller, self.properties),
            "materials": Panel(
                "Materials", self.controller, self.materials, scope={"materials", "row_zones"}
            ),
            "validation": Panel("Validation / Warnings", self.controller, self.validation),
            "runs": Panel(
                "Simulation Runs",
                self.controller,
                self.runs,
                scope=artifact_inputs("simulation"),
                artifacts=("simulation",),
                runs=True,
            ),
            "view3d": Panel(
                "3D View",
                self.controller,
                self.view3d,
                scope=artifact_inputs("simulation"),
                artifacts=("rest_mesh",),
                runs=True,
            ),
            "patterns": Panel(
                "2D Pattern View",
                self.controller,
                self.patterns,
                scope=pattern_scope,
                artifacts=("patterns",),
            ),
            "history": Panel("History", self.controller, self.history),
            "rigging": Panel(
                "Rigging",
                self.controller,
                self.rigging,
                scope={"parachute", "rigging", "turning_vents", "scoop", "operating"},
                scroll=True,
            ),
            "shapes": Panel(
                "Special Shapes",
                self.controller,
                self.shapes,
                scope={"shapes"},
                artifacts=("shapes",),
            ),
        }
        self._build_workspace()

        self._build_status_bar()
        self._build_actions()
        self.controller.editRejected.connect(self._rejected)
        self.controller.selectionChanged.connect(self._selection_mode)
        self.controller.message.connect(lambda text: self.statusBar().showMessage(text, 8000))
        self.controller.fileChanged.connect(self._update_title)
        self.controller.stateChanged.connect(self._update_actions)
        self.controller.sessionChanged.connect(self._update_actions)
        self.simulation.started.connect(lambda s: self._task(f"running {s}…"))
        self.simulation.progress.connect(self._progress)
        self.simulation.finished.connect(self._run_finished)
        self.simulation.failed.connect(self._run_failed)
        self.simulation.calculixChanged.connect(self._update_ccx_label)
        self.simulation.idle.connect(self._update_actions)

        self.autosave_timer = QTimer(self)
        self.autosave_timer.timeout.connect(self.autosave)
        self._apply_autosave_interval()
        self._update_ccx_label()
        self._update_actions()
        self._update_title()
        if self.controller.library_error is not None:
            self.task_label.setText("Fabric library not opened (temporary library in use)")
            if interactive:
                QTimer.singleShot(
                    0,
                    lambda: self._error("Fabric library", self.controller.library_error or ""),
                )
        self.restore_last_layout()
        if interactive:
            QTimer.singleShot(0, self.offer_recovery)
            # The window is on screen before PyVista/OpenGL start (seconds).
            QTimer.singleShot(50, self.view3d.load_renderer)

    # -- construction -------------------------------------------------------------------

    def _splitter(self, name: str, orientation: Qt.Orientation, *widgets: QWidget) -> QSplitter:
        splitter = QSplitter(orientation)
        splitter.setObjectName(name)
        splitter.setChildrenCollapsible(False)
        for i, widget in enumerate(widgets):
            splitter.addWidget(widget)
            # Explicit per child: a nested splitter would otherwise count as collapsible.
            splitter.setCollapsible(i, False)
        return splitter

    def _build_workspace(self) -> None:
        """Mode tabs over [sidebar | mode pages], above the Validation / Warnings strip.

        Each panel lives in exactly one place (the 3D renderer cannot be moved between
        parents safely), and only the sidebar may be collapsed: the mode page and the
        warnings strip always stay visible.
        """
        vertical = Qt.Orientation.Vertical
        horizontal = Qt.Orientation.Horizontal
        pages: dict[str, QWidget] = {
            "shape": self.gore_editor,
            "patterns": self._splitter(
                "patternsModeSplitter",
                horizontal,
                self.panels["patterns"],
                self.panels["materials"],
            ),
            "rigging": self.panels["rigging"],
            "shapes": self.panels["shapes"],
            "simulate": self._splitter(
                "simulateSplitter", vertical, self.panels["view3d"], self.panels["runs"]
            ),
            "history": self.panels["history"],
        }
        #: Mode holding each panel (the sidebar and warnings strip show in every mode).
        self.panel_modes: dict[str, str | None] = {
            "tree": None,
            "properties": None,
            "validation": None,
            "patterns": "patterns",
            "materials": "patterns",
            "rigging": "rigging",
            "shapes": "shapes",
            "view3d": "simulate",
            "runs": "simulate",
            "history": "history",
        }
        self.mode_stack = QStackedWidget()
        self.mode_tabs = QTabBar()
        self.mode_tabs.setObjectName("modeTabs")
        self.mode_tabs.setExpanding(False)
        self.mode_tabs.setDrawBase(False)
        #: Content of each mode page (inside its scroll area).
        self.mode_pages = pages
        for key, label in MODES:
            # A stacked widget is as large as its largest page, hidden pages included, so
            # each page scrolls when the window is smaller than its content instead of
            # setting the window's minimum size (which depends on platform font metrics).
            scroll = QScrollArea()
            scroll.setObjectName(f"{key}ModePage")
            scroll.setWidget(pages[key])
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            self.mode_stack.addWidget(scroll)
            self.mode_tabs.addTab(label)
        self.mode_tabs.currentChanged.connect(self._mode_changed)

        sidebar = self._splitter(
            "sidebarSplitter", vertical, self.panels["tree"], self.panels["properties"]
        )
        side = self._splitter("sideSplitter", horizontal, sidebar, self.mode_stack)
        side.setCollapsible(0, True)
        side.setStretchFactor(1, 1)
        outer = self._splitter("outerSplitter", vertical, side, self.panels["validation"])
        outer.setStretchFactor(0, 1)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(4, 2, 4, 0)
        layout.setSpacing(2)
        layout.addWidget(self.mode_tabs)
        layout.addWidget(outer)
        self.setCentralWidget(central)
        for panel in self.panels.values():
            panel.windowTitleChanged.connect(self._update_mode_tabs)
        layout_state.apply_defaults(self)
        self._update_mode_tabs()

    def _build_status_bar(self) -> None:
        bar = self.statusBar()
        self.task_label = QLabel("Ready")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setMaximumWidth(220)
        self.progress_bar.setVisible(False)
        self.dirty_label = QLabel()
        self.ccx_label = QLabel()
        self.ccx_label.setObjectName("ccxStatus")
        bar.addWidget(self.task_label, 1)
        bar.addPermanentWidget(self.progress_bar)
        bar.addPermanentWidget(self.dirty_label)
        bar.addPermanentWidget(self.ccx_label)

    def _action(
        self,
        text: str,
        slot: Callable[[], object],
        shortcut: QKeySequence.StandardKey | str | None = None,
    ) -> QAction:
        action = QAction(text, self)
        if shortcut is not None:
            action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(slot)
        return action

    def _build_actions(self) -> None:
        std = QKeySequence.StandardKey
        self.new_action = self._action("&New design…", self.new_design_dialog, std.New)
        self.open_action = self._action("&Open…", self.open_dialog, std.Open)
        self.template_action = self._action("New from &template…", self.template_dialog)
        self.save_action = self._action("&Save", self.save, std.Save)
        self.save_as_action = self._action("Save &As…", self.save_as_dialog, std.SaveAs)
        self.prefs_action = self._action("&Preferences…", self.preferences_dialog, std.Preferences)
        self.quit_action = self._action("&Quit", self.close, std.Quit)
        self.undo_action = self._action("&Undo", self.undo, std.Undo)
        self.redo_action = self._action("&Redo", self.redo, std.Redo)
        self.snapshot_action = self._action("Take &snapshot…", self.history._take)
        self.version_action = self._action("Commit &version…", self.history._commit)
        self.regen_action = self._action("&Regenerate patterns", self.patterns.regenerate, "F5")
        self.preview_action = self._action(
            "Run &Preview", lambda: self.simulation.start(PREVIEW), "F9"
        )
        self.calculix_action = self._action(
            "Run &CalculiX", lambda: self.simulation.start(CALCULIX), "Shift+F9"
        )
        self.cancel_action = self._action("C&ancel run", self.simulation.cancel)
        self.reference_action = self._action("Load &reference mesh…", self.reference_dialog)
        self.detect_action = self._action("Detect CalculiX again", self.simulation.detect_calculix)

        menu = self.menuBar()
        file_menu = menu.addMenu("&File")
        file_menu.addAction(self.new_action)
        file_menu.addAction(self.template_action)
        file_menu.addAction(self.open_action)
        self.recent_menu = file_menu.addMenu("Open &Recent")
        self.recent_menu.aboutToShow.connect(self._fill_recent)
        file_menu.addAction(self.save_action)
        file_menu.addAction(self.save_as_action)
        file_menu.addSeparator()
        file_menu.addAction(self.prefs_action)
        file_menu.addSeparator()
        file_menu.addAction(self.quit_action)
        edit_menu = menu.addMenu("&Edit")
        edit_menu.addAction(self.undo_action)
        edit_menu.addAction(self.redo_action)
        edit_menu.addSeparator()
        edit_menu.addAction(self.snapshot_action)
        edit_menu.addAction(self.version_action)
        design_menu = menu.addMenu("&Design")
        design_menu.addAction(self.regen_action)
        design_menu.addAction(self.reference_action)
        sim_menu = menu.addMenu("&Simulation")
        sim_menu.addAction(self.preview_action)
        sim_menu.addAction(self.calculix_action)
        sim_menu.addAction(self.cancel_action)
        sim_menu.addSeparator()
        sim_menu.addAction(self.detect_action)
        view_menu = menu.addMenu("&View")
        self.mode_actions: dict[str, QAction] = {}
        mode_group = QActionGroup(self)
        for i, (key, label) in enumerate(MODES):
            action = self._action(label, self._mode_slot(key), f"Ctrl+{i + 1}")
            action.setCheckable(True)
            mode_group.addAction(action)
            view_menu.addAction(action)
            self.mode_actions[key] = action
        self.mode_actions[self.mode()].setChecked(True)
        view_menu.addSeparator()
        self.sidebar_action = self._action("Show &sidebar", self.toggle_sidebar)
        self.sidebar_action.setCheckable(True)
        self.sidebar_action.setChecked(True)
        view_menu.addAction(self.sidebar_action)
        view_menu.addSeparator()
        self.save_layout_action = self._action("Sa&ve layout", self.save_layout)
        self.load_layout_action = self._action("&Load saved layout", self.load_saved_layout)
        self.reset_layout_action = self._action("&Reset layout", self.reset_layout)
        for action in (self.save_layout_action, self.load_layout_action, self.reset_layout_action):
            view_menu.addAction(action)
        view_menu.aboutToShow.connect(self._update_layout_actions)
        toolbar = self.addToolBar("Main")
        toolbar.setObjectName("mainToolbar")
        for action in (
            self.new_action,
            self.open_action,
            self.save_action,
            self.undo_action,
            self.redo_action,
            self.regen_action,
            self.preview_action,
            self.calculix_action,
            self.cancel_action,
        ):
            toolbar.addAction(action)

    # -- modes and layout ---------------------------------------------------------------

    def mode(self) -> str:
        """Key of the visible workflow mode."""
        return MODE_KEYS[self.mode_tabs.currentIndex()]

    def set_mode(self, key: str) -> None:
        """Show the workflow mode ``key`` (one of ``layout.MODE_KEYS``)."""
        self.mode_tabs.setCurrentIndex(MODE_KEYS.index(key))

    def show_panel(self, key: str) -> None:
        """Switch to the mode that holds panel ``key`` (and show the sidebar for its
        panels)."""
        mode = self.panel_modes[key]
        if mode is not None:
            self.set_mode(mode)
        elif key in ("tree", "properties") and not self.sidebar_visible():
            self.toggle_sidebar()

    def panel_visible(self, key: str) -> bool:
        """Panel ``key`` is on screen in the current mode."""
        mode = self.panel_modes[key]
        if mode is None:
            return key == "validation" or self.sidebar_visible()
        return mode == self.mode()

    def _mode_slot(self, key: str) -> Callable[[], None]:
        return lambda: self.set_mode(key)

    def _selection_mode(self, target: str) -> None:
        """Show the Special shapes mode when a shape is selected (tree, warnings)."""
        if target == "shapes" or target.startswith("shape:"):
            self.show_panel("shapes")

    def _mode_changed(self, index: int) -> None:
        self.mode_stack.setCurrentIndex(index)
        action = getattr(self, "mode_actions", {}).get(MODE_KEYS[index])
        if action is not None:
            action.setChecked(True)

    def _update_mode_tabs(self) -> None:
        """Repeat the panels' ● and [STALE] indicators on the tab of their mode (the
        Shape mode has no panel of its own; the sidebar's Design Tree carries its ●)."""
        for i, (key, label) in enumerate(MODES):
            panels = [self.panels[p] for p, m in self.panel_modes.items() if m == key]
            text = label
            if any(p.unsaved() for p in panels):
                text += f" {UNSAVED_MARK}"
            if any(p.stale() for p in panels):
                text += " [STALE]"
            self.mode_tabs.setTabText(i, text)

    def _side_splitter(self) -> QSplitter:
        return layout_state.named_splitters(self)["sideSplitter"]

    def sidebar_visible(self) -> bool:
        """The design tree / properties sidebar is not collapsed."""
        return self._side_splitter().sizes()[0] > 0

    def toggle_sidebar(self) -> None:
        """Collapse or re-open the design tree / properties sidebar."""
        splitter = self._side_splitter()
        total = sum(splitter.sizes())
        if self.sidebar_visible():
            splitter.setSizes([0, total])
        else:
            default = layout_state.DEFAULT_SIZES["sideSplitter"]
            width = max(1, total) * default[0] // sum(default)
            splitter.setSizes([width, max(1, total) - width])
        self.sidebar_action.setChecked(self.sidebar_visible())

    def _update_layout_actions(self) -> None:
        self.sidebar_action.setChecked(self.sidebar_visible())
        self.load_layout_action.setEnabled(
            layout_state.load(self.settings, layout_state.SAVED_SLOT) is not None
        )

    def capture_layout(self) -> layout_state.LayoutState:
        """The current mode, splitter sizes and window geometry."""
        return layout_state.capture(self, self.mode(), self.saveGeometry())

    def apply_layout(self, state: layout_state.LayoutState, geometry: bool = False) -> None:
        """Show ``state``'s mode and splitter sizes (and window geometry if asked)."""
        if geometry and not state.geometry.isEmpty():
            self.restoreGeometry(state.geometry)
        layout_state.apply_splitters(self, state)
        self.set_mode(state.mode)
        self.sidebar_action.setChecked(self.sidebar_visible())

    def save_layout(self) -> None:
        """View ▸ Save layout: store the current layout for Load saved layout."""
        layout_state.store(self.settings, layout_state.SAVED_SLOT, self.capture_layout())
        self._task("Layout saved")

    def load_saved_layout(self) -> bool:
        """View ▸ Load saved layout (the window keeps its size). False if none is saved."""
        state = layout_state.load(self.settings, layout_state.SAVED_SLOT)
        if state is None:
            self._task("No saved layout")
            return False
        self.apply_layout(state)
        self._task("Saved layout loaded")
        return True

    def reset_layout(self) -> None:
        """View ▸ Reset layout: default splitter sizes and the Shape mode."""
        layout_state.apply_defaults(self)
        self.set_mode(MODE_KEYS[0])
        self.sidebar_action.setChecked(True)
        self._task("Layout reset")

    def restore_last_layout(self) -> bool:
        """Restore the layout of the last window closed (False if none is stored)."""
        state = layout_state.load(self.settings, layout_state.LAST_SLOT)
        if state is None:
            return False
        self.apply_layout(state, geometry=True)
        return True

    # -- state display ------------------------------------------------------------------

    def _update_title(self) -> None:
        session = self.controller.session
        if session is None:
            self.setWindowTitle("EnvelopeLab")
            self.dirty_label.setText("")
            return
        where = str(session.path) if session.path else "unsaved"
        mark = "*" if session.is_dirty else ""
        self.setWindowTitle(f"EnvelopeLab — {session.design.meta.name}{mark} [{where}]")
        self.dirty_label.setText("Unsaved changes" if session.is_dirty else "Saved")
        self._update_actions()

    def _update_actions(self) -> None:
        session = self.controller.session
        has = session is not None
        stack = session.stack if session is not None else None
        self.save_action.setEnabled(has)
        self.save_as_action.setEnabled(has)
        self.undo_action.setEnabled(bool(stack and stack.can_undo))
        self.redo_action.setEnabled(bool(stack and stack.can_redo))
        self.undo_action.setText(
            f"&Undo {stack.undo_text()}" if stack and stack.can_undo else "&Undo"
        )
        self.redo_action.setText(
            f"&Redo {stack.redo_text()}" if stack and stack.can_redo else "&Redo"
        )
        self.snapshot_action.setEnabled(has)
        self.version_action.setEnabled(has)
        running = self.simulation.running
        gore = self.controller.is_gore
        self.regen_action.setEnabled(gore)
        self.preview_action.setEnabled(gore and not running)
        self.calculix_action.setEnabled(gore and not running and self.simulation.calculix_available)
        self.calculix_action.setToolTip(
            "CalculiX verification solve"
            if self.simulation.calculix_available
            else self.simulation.calculix_message
        )
        self.cancel_action.setEnabled(running)
        self.runs.update_actions()

    def _update_ccx_label(self) -> None:
        if self.simulation.calculix_available:
            self.ccx_label.setText(f"CalculiX {self.simulation.calculix_version}")
            self.ccx_label.setStyleSheet("")
        else:
            self.ccx_label.setText("CalculiX not installed — Run CalculiX disabled")
            self.ccx_label.setStyleSheet("color: #b00020; font-weight: bold;")
        self.ccx_label.setToolTip(self.simulation.calculix_message)
        self._update_actions()

    def _task(self, text: str) -> None:
        self.task_label.setText(text)

    def _progress(self, message: str, fraction: float) -> None:
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(int(1000 * max(0.0, min(1.0, fraction))))
        self.task_label.setText(message)

    def _run_finished(self, record: object) -> None:
        self.progress_bar.setVisible(False)
        converged = getattr(record, "converged", False)
        label = getattr(record, "solver_label", "run")
        self.task_label.setText(f"{label}: {'converged' if converged else 'NOT CONVERGED'}")
        self._update_actions()

    def _run_failed(self, message: str) -> None:
        self.progress_bar.setVisible(False)
        self.task_label.setText(message.splitlines()[0])
        self._update_actions()

    def _rejected(self, message: str) -> None:
        self.statusBar().showMessage(f"Edit refused: {message}", 8000)
        self.task_label.setText(f"Edit refused: {message}")

    # -- projects -----------------------------------------------------------------------

    def set_session(self, session: ProjectSession | None) -> None:
        """Show ``session``."""
        if self.simulation.running:
            self.simulation.cancel()
        self.controller.set_session(session)
        self._update_title()

    def new_project(self, design: DesignDocument) -> ProjectSession:
        """Start an unsaved project around ``design``."""
        session = ProjectSession.new(design)
        self.set_session(session)
        return session

    def open_project(self, path: str | Path) -> ProjectSession | None:
        """Open a project file (errors are shown, not raised)."""
        try:
            session = ProjectSession.open(path)
        except (OSError, ValueError) as exc:
            self._error(f"Could not open {path}", str(exc))
            return None
        self.set_session(session)
        add_recent_project(self.settings, Path(path))
        return session

    def save(self) -> bool:
        """Save to the current file (asks for a name for a new project)."""
        session = self.controller.session
        if session is None:
            return False
        if session.path is None:
            return self.save_as_dialog()
        return self.save_to(session.path)

    def save_to(self, path: str | Path) -> bool:
        """Save the project to ``path``."""
        session = self.controller.session
        if session is None:
            return False
        target = Path(path)
        if target.suffix != PROJECT_SUFFIX:
            target = target.with_name(target.name + PROJECT_SUFFIX)
        try:
            session.save(target)
        except OSError as exc:
            self._error(f"Could not save {target}", str(exc))
            return False
        add_recent_project(self.settings, target)
        discard(self.autosave_path())
        self._task(f"Saved {target}")
        self._update_title()
        return True

    def autosave_path(self) -> Path:
        """This window's autosave file."""
        return autosave_file(self.prefs.resolved_recovery_dir(), self.instance_id)

    def autosave(self) -> Path | None:
        """Write the autosave file when there are unsaved changes."""
        session = self.controller.session
        if session is None or not session.is_dirty:
            return None
        try:
            return write_autosave(session.project, self.autosave_path(), session.path)
        except OSError as exc:
            self._task(f"Autosave failed: {exc}")
            return None

    def _apply_autosave_interval(self) -> None:
        minutes = self.prefs.autosave_minutes
        if minutes > 0:
            self.autosave_timer.start(int(minutes * 60_000))
        else:
            self.autosave_timer.stop()

    def offer_recovery(self) -> None:
        """Offer autosave files of sessions that ended without saving."""
        items = find_recoverable(self.prefs.resolved_recovery_dir(), exclude=self.autosave_path())
        for item in items:
            where = str(item.original_path) if item.original_path else "never saved"
            answer = QMessageBox.question(
                self,
                "Recover unsaved work?",
                f"EnvelopeLab found unsaved changes to '{item.name}' ({where}) from "
                f"{item.saved:%Y-%m-%d %H:%M} UTC.\n\nRecover them?",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No
                | QMessageBox.StandardButton.Discard,
            )
            if answer == QMessageBox.StandardButton.Yes:
                self.recover(item.autosave_path)
                return
            if answer == QMessageBox.StandardButton.Discard:
                discard(item.autosave_path)

    def recover(self, autosave: str | Path) -> ProjectSession | None:
        """Open an autosave file as an unsaved project and remove the file."""
        try:
            project, original = read_autosave(autosave)
        except (OSError, ValueError) as exc:
            self._error("Could not recover", str(exc))
            return None
        session = ProjectSession(project, original)
        session.mark_aux_dirty()
        self.set_session(session)
        discard(autosave)
        self.autosave()
        return session

    def maybe_discard(self) -> bool:
        """True when it is fine to drop the open project (saved, or the user agreed)."""
        session = self.controller.session
        if session is None or not session.is_dirty or not self.interactive:
            return True
        answer = QMessageBox.question(
            self,
            "Unsaved changes",
            f"Save changes to '{session.design.meta.name}'?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Save:
            return self.save()
        return answer == QMessageBox.StandardButton.Discard

    # -- dialogs ------------------------------------------------------------------------

    def new_design_dialog(self) -> None:
        if not self.maybe_discard():
            return
        wizard = NewDesignWizard(self.controller.fabrics, self, self.settings)
        if wizard.exec() and wizard.design is not None:
            self.new_project(wizard.design)
            self.controller.regenerate_patterns()

    def new_from_template(self, path: str | Path, name: str) -> ProjectSession | None:
        """Start an unsaved project whose design is a copy of the project at ``path``."""
        try:
            session = ProjectSession.from_template(path, name)
        except (OSError, ValueError) as exc:
            self._error(f"Could not use {path} as a template", str(exc))
            return None
        self.set_session(session)
        self.controller.regenerate_patterns()
        return session

    def template_dialog(self) -> None:
        if not self.maybe_discard():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Template project", "", FILE_FILTER)
        if not path:
            return
        name, ok = QInputDialog.getText(
            self, "New from template", "Name of the new design:", text="New envelope"
        )
        if ok:
            self.new_from_template(path, name)

    def open_dialog(self) -> None:
        if not self.maybe_discard():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Open project", "", FILE_FILTER)
        if path:
            self.open_project(path)

    def save_as_dialog(self) -> bool:
        if self.controller.session is None:
            return False
        path, _ = QFileDialog.getSaveFileName(self, "Save project as", "", FILE_FILTER)
        return bool(path) and self.save_to(path)

    def reference_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Reference mesh", "", "Meshes (*.obj *.stl *.ply)"
        )
        if path:
            self.view3d.load_reference(path)

    def preferences_dialog(self) -> None:
        dialog = PreferencesDialog(self.prefs, self)
        if dialog.exec():
            self.apply_preferences(dialog.result_preferences())

    def apply_preferences(self, prefs: Preferences) -> None:
        """Use and store new preferences."""
        for name, value in prefs.__dict__.items():
            setattr(self.prefs, name, value)
        save_preferences(self.settings, self.prefs)
        self._apply_autosave_interval()
        self.simulation.detect_calculix()

    def _fill_recent(self) -> None:
        self.recent_menu.clear()
        for path in recent_projects(self.settings):
            action = self.recent_menu.addAction(str(path))
            action.triggered.connect(
                lambda _c=False, p=path: self.maybe_discard() and self.open_project(p)
            )
        if self.recent_menu.isEmpty():
            self.recent_menu.addAction("(none)").setEnabled(False)

    def _error(self, title: str, text: str) -> None:
        self._task(f"{title}: {text.splitlines()[0] if text else ''}")
        if self.interactive:
            QMessageBox.critical(self, title, text)

    # -- editing ------------------------------------------------------------------------

    def undo(self) -> None:
        if self.controller.session is not None:
            self.controller.session.undo()

    def redo(self) -> None:
        if self.controller.session is not None:
            self.controller.session.redo()

    # -- shutdown -----------------------------------------------------------------------

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if not self.maybe_discard():
            event.ignore()
            return
        if self.simulation.running:
            self.simulation.cancel()
            self.simulation.wait(30_000)
        if self.controller.shape_simulator.running:
            self.controller.shape_simulator.cancel()
            self.controller.shape_simulator.wait(30_000)
        self.controller.shapes.wait(30_000)
        discard(self.autosave_path())
        layout_state.store(self.settings, layout_state.LAST_SLOT, self.capture_layout())
        self.view3d.close_renderer()
        event.accept()


def panel_titles(window: MainWindow) -> dict[str, str]:
    """Current panel titles (with indicators), for tests and scripting."""
    return {key: panel.windowTitle() for key, panel in window.panels.items()}


__all__ = ["MainWindow", "QWidget", "panel_titles"]
