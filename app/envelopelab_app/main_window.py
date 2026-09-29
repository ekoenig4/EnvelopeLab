"""EnvelopeLab main window: project files, dockable panels, undo/redo, autosave."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
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
from envelopelab_app.controller import WorkspaceController
from envelopelab_app.dialogs import PreferencesDialog
from envelopelab_app.gore_editor import GoreEditor
from envelopelab_app.panels.base import PanelDock
from envelopelab_app.panels.design_tree import DesignTreePanel
from envelopelab_app.panels.history import HistoryPanel
from envelopelab_app.panels.materials import MaterialsPanel
from envelopelab_app.panels.patterns import PatternPanel
from envelopelab_app.panels.properties import PropertiesPanel
from envelopelab_app.panels.validation import ValidationPanel
from envelopelab_app.settings import (
    Preferences,
    add_recent_project,
    load_preferences,
    recent_projects,
    save_preferences,
)
from envelopelab_app.wizard import NewDesignWizard

FILE_FILTER = f"EnvelopeLab projects (*{PROJECT_SUFFIX})"


class MainWindow(QMainWindow):
    """The application window.

    Parameters
    ----------
    settings : QSettings
        Where preferences and recent projects are stored.
    enable_3d : bool, optional
        Reserved for the 3D view.
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
        self.setWindowTitle("EnvelopeLab")
        self.resize(1500, 950)

        self.gore_editor = GoreEditor(self.controller)
        self.setCentralWidget(self.gore_editor)
        self.design_tree = DesignTreePanel(self.controller)
        self.properties = PropertiesPanel(self.controller)
        self.validation = ValidationPanel(self.controller)
        self.materials = MaterialsPanel(self.controller)
        self.patterns = PatternPanel(self.controller)
        self.history = HistoryPanel(self.controller)
        pattern_scope = artifact_inputs("patterns")
        self.docks: dict[str, PanelDock] = {
            "tree": PanelDock("Design Tree", self.controller, self.design_tree),
            "properties": PanelDock("Properties", self.controller, self.properties),
            "materials": PanelDock(
                "Materials", self.controller, self.materials, scope={"materials", "row_zones"}
            ),
            "validation": PanelDock("Validation / Warnings", self.controller, self.validation),
            "patterns": PanelDock(
                "2D Pattern View",
                self.controller,
                self.patterns,
                scope=pattern_scope,
                artifacts=("patterns",),
            ),
            "history": PanelDock("History", self.controller, self.history),
        }
        area = Qt.DockWidgetArea
        self.addDockWidget(area.LeftDockWidgetArea, self.docks["tree"])
        self.addDockWidget(area.LeftDockWidgetArea, self.docks["properties"])
        self.tabifyDockWidget(self.docks["properties"], self.docks["materials"])
        self.addDockWidget(area.RightDockWidgetArea, self.docks["patterns"])
        self.addDockWidget(area.RightDockWidgetArea, self.docks["history"])
        self.addDockWidget(area.BottomDockWidgetArea, self.docks["validation"])
        self.docks["properties"].raise_()
        self.docks["validation"].raise_()

        self._build_status_bar()
        self._build_actions()
        self.controller.editRejected.connect(self._rejected)
        self.controller.fileChanged.connect(self._update_title)
        self.controller.stateChanged.connect(self._update_actions)
        self.controller.sessionChanged.connect(self._update_actions)

        self.autosave_timer = QTimer(self)
        self.autosave_timer.timeout.connect(self.autosave)
        self._apply_autosave_interval()
        self._update_actions()
        self._update_title()
        if interactive:
            QTimer.singleShot(0, self.offer_recovery)

    # -- construction -------------------------------------------------------------------

    def _build_status_bar(self) -> None:
        bar = self.statusBar()
        self.task_label = QLabel("Ready")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setMaximumWidth(220)
        self.progress_bar.setVisible(False)
        self.dirty_label = QLabel()
        bar.addWidget(self.task_label, 1)
        bar.addPermanentWidget(self.progress_bar)
        bar.addPermanentWidget(self.dirty_label)

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
        self.save_action = self._action("&Save", self.save, std.Save)
        self.save_as_action = self._action("Save &As…", self.save_as_dialog, std.SaveAs)
        self.prefs_action = self._action("&Preferences…", self.preferences_dialog, std.Preferences)
        self.quit_action = self._action("&Quit", self.close, std.Quit)
        self.undo_action = self._action("&Undo", self.undo, std.Undo)
        self.redo_action = self._action("&Redo", self.redo, std.Redo)
        self.snapshot_action = self._action("Take &snapshot…", self.history._take)
        self.version_action = self._action("Commit &version…", self.history._commit)
        self.regen_action = self._action("&Regenerate patterns", self.patterns.regenerate, "F5")

        menu = self.menuBar()
        file_menu = menu.addMenu("&File")
        file_menu.addAction(self.new_action)
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
        view_menu = menu.addMenu("&View")
        for dock in self.docks.values():
            view_menu.addAction(dock.toggleViewAction())
        toolbar = self.addToolBar("Main")
        toolbar.setObjectName("mainToolbar")
        for action in (
            self.new_action,
            self.open_action,
            self.save_action,
            self.undo_action,
            self.redo_action,
            self.regen_action,
        ):
            toolbar.addAction(action)

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
        self.regen_action.setEnabled(self.controller.is_gore)

    def _task(self, text: str) -> None:
        self.task_label.setText(text)

    def _rejected(self, message: str) -> None:
        self.statusBar().showMessage(f"Edit refused: {message}", 8000)
        self.task_label.setText(f"Edit refused: {message}")

    # -- projects -----------------------------------------------------------------------

    def set_session(self, session: ProjectSession | None) -> None:
        """Show ``session``."""
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
        wizard = NewDesignWizard(self.controller.fabrics, self)
        if wizard.exec() and wizard.design is not None:
            self.new_project(wizard.design)
            self.controller.regenerate_patterns()

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
        discard(self.autosave_path())
        event.accept()


def dock_titles(window: MainWindow) -> dict[str, str]:
    """Current dock titles (with indicators), for tests and scripting."""
    return {key: dock.windowTitle() for key, dock in window.docks.items()}


__all__ = ["MainWindow", "QWidget", "dock_titles"]
