"""Dockable panel with a dirty-state and staleness indicator in its title."""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtWidgets import QDockWidget, QWidget

from envelopelab.project.dependencies import INPUT_GROUPS, artifact_inputs
from envelopelab_app.controller import WorkspaceController

UNSAVED_MARK = "●"  # black circle


def scope_of(artifacts: Iterable[str]) -> set[str]:
    """Input groups read by the given artifacts."""
    out: set[str] = set()
    for name in artifacts:
        out |= artifact_inputs(name)
    return out


class PanelDock(QDockWidget):
    """A dock whose title shows ``●`` for unsaved changes in its scope and ``[STALE]``
    when an artifact it displays is stale.

    Parameters
    ----------
    title : str
        Base title.
    controller : WorkspaceController
        Workspace.
    widget : QWidget
        Panel content.
    scope : iterable of str, optional
        Input groups the panel shows (default: all).
    artifacts : iterable of str
        Artifacts whose staleness the panel reflects.
    runs : bool
        The panel also shows run records (unsaved runs count as changes, stale runs as
        stale).
    """

    def __init__(
        self,
        title: str,
        controller: WorkspaceController,
        widget: QWidget,
        scope: Iterable[str] | None = None,
        artifacts: Iterable[str] = (),
        runs: bool = False,
    ) -> None:
        super().__init__(title)
        self.base_title = title
        self.controller = controller
        self.scope = set(scope) if scope is not None else set(INPUT_GROUPS)
        self.artifacts = tuple(artifacts)
        self.runs = runs
        self.setObjectName(title.replace(" ", "") + "Dock")
        self.setWidget(widget)
        for signal in (
            controller.stateChanged,
            controller.fileChanged,
            controller.artifactsChanged,
            controller.runsChanged,
            controller.sessionChanged,
        ):
            signal.connect(self.update_indicator)
        self.update_indicator()

    def unsaved(self) -> bool:
        """Unsaved changes in the panel's scope."""
        session = self.controller.session
        if session is None:
            return False
        if session.unsaved_groups() & self.scope:
            return True
        return self.runs and bool(session.unsaved_runs())

    def stale(self) -> bool:
        """An artifact (or run) shown by the panel is stale."""
        if any(self.controller.artifact_status(a) == "stale" for a in self.artifacts):
            return True
        session = self.controller.session
        if self.runs and session is not None:
            return any(session.run_status(r) == "stale" for r in session.project.runs)
        return False

    def update_indicator(self) -> None:
        """Refresh the title."""
        title = self.base_title
        if self.unsaved():
            title += f" {UNSAVED_MARK}"
        if self.stale():
            title += " [STALE]"
        self.setWindowTitle(title)
