"""Validation / Warnings panel: design errors, seam mismatches, manual overrides, stale
artifacts, unconverged and failing runs. Nothing is hidden; errors are listed first."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QLabel, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from envelopelab.project.gore_design import DesignFinding
from envelopelab_app.controller import WorkspaceController

SEVERITY_COLORS = {"error": "#b00020", "warning": "#8a6d3b", "info": "#31708f"}


class ValidationPanel(QWidget):
    """See module docstring."""

    def __init__(self, controller: WorkspaceController) -> None:
        super().__init__()
        self.controller = controller
        self.summary = QLabel()
        self.list = QListWidget()
        self.list.itemActivated.connect(self._activated)
        self.list.itemClicked.connect(self._activated)
        layout = QVBoxLayout(self)
        layout.addWidget(self.summary)
        layout.addWidget(self.list)
        self.findings: list[DesignFinding] = []
        for signal in (
            controller.stateChanged,
            controller.artifactsChanged,
            controller.runsChanged,
            controller.sessionChanged,
        ):
            signal.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        """Recompute the findings."""
        self.findings = self.controller.findings()
        self.list.clear()
        for f in self.findings:
            item = QListWidgetItem(f"[{f.severity.upper()}] {f.message}")
            item.setData(Qt.ItemDataRole.UserRole, f.target)
            item.setForeground(QBrush(QColor(SEVERITY_COLORS[f.severity])))
            self.list.addItem(item)
        errors = sum(f.severity == "error" for f in self.findings)
        warnings = sum(f.severity == "warning" for f in self.findings)
        self.summary.setText(f"{errors} error(s), {warnings} warning(s)")
        self.summary.setStyleSheet("color: #b00020; font-weight: bold;" if errors else "")

    def messages(self) -> list[str]:
        """Finding texts as shown."""
        return [self.list.item(i).text() for i in range(self.list.count())]

    def _activated(self, item: QListWidgetItem) -> None:
        target = item.data(Qt.ItemDataRole.UserRole)
        if target:
            self.controller.select(str(target))
