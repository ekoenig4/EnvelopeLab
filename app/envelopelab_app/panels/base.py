"""Titled panel with a dirty-state and staleness indicator in its header."""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtWidgets import QFrame, QLabel, QScrollArea, QVBoxLayout, QWidget

from envelopelab.project.dependencies import INPUT_GROUPS, artifact_inputs
from envelopelab_app.controller import WorkspaceController
from envelopelab_app.refresh import Refresher

UNSAVED_MARK = "●"  # black circle


def scope_of(artifacts: Iterable[str]) -> set[str]:
    """Input groups read by the given artifacts."""
    out: set[str] = set()
    for name in artifacts:
        out |= artifact_inputs(name)
    return out


class Panel(QFrame):
    """A titled panel whose header shows ``●`` for unsaved changes in its scope and
    ``[STALE]`` when an artifact it displays is stale.

    The full title (with indicators) is also the widget's ``windowTitle()``, so the main
    window can repeat the indicators on the mode tab that holds the panel.

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
    scroll : bool
        Put the content in a scroll area, so a tall form does not set the window's
        minimum height.
    """

    def __init__(
        self,
        title: str,
        controller: WorkspaceController,
        widget: QWidget,
        scope: Iterable[str] | None = None,
        artifacts: Iterable[str] = (),
        runs: bool = False,
        scroll: bool = False,
    ) -> None:
        super().__init__()
        self.base_title = title
        self.controller = controller
        self.scope = set(scope) if scope is not None else set(INPUT_GROUPS)
        self.artifacts = tuple(artifacts)
        self.runs = runs
        self.setObjectName(title.replace(" ", "").replace("/", "") + "Panel")
        self.content = widget
        self.header = QLabel(title)
        self.header.setObjectName("panelHeader")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.header)
        if scroll:
            area = QScrollArea()
            area.setWidget(widget)
            area.setWidgetResizable(True)
            area.setFrameShape(QFrame.Shape.NoFrame)
            layout.addWidget(area)
        else:
            layout.addWidget(widget)
        # The mode tabs repeat the indicators, so they update while hidden too.
        self.indicator = Refresher(
            self,
            self.update_indicator,
            lambda: controller.revision,
            (
                controller.stateChanged,
                controller.fileChanged,
                controller.artifactsChanged,
                controller.runsChanged,
                controller.sessionChanged,
            ),
            defer_hidden=False,
        )
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
        """Refresh the header and the window title."""
        title = self.base_title
        if self.unsaved():
            title += f" {UNSAVED_MARK}"
        if self.stale():
            title += " [STALE]"
        self.header.setText(title)
        colour = "color: #b00020; " if self.stale() else ""
        self.header.setStyleSheet(f"{colour}font-weight: bold; padding: 2px 4px;")
        self.setWindowTitle(title)
