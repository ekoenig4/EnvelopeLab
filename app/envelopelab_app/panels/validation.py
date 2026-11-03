"""Validation / Warnings panel: design errors, seam mismatches, manual overrides, stale
artifacts, unconverged and failing runs. Nothing is hidden; errors are listed first.

Laid out in the shared design: a header with one status chip per severity (✕ errors,
▲ warnings, i notes, or ✓ when there is nothing to report) and filter buttons, then the
findings, each with its severity's symbol and colour. The filters only hide rows from the
list while they are off; the counts always include every finding, so a problem is never
hidden from the summary. Clicking a finding selects the element it is about.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from envelopelab.project.gore_design import DesignFinding
from envelopelab_app.controller import WorkspaceController
from envelopelab_app.refresh import Refresher
from envelopelab_app.theme import STATUS_STYLES, StatusChip

#: Severity of a finding to the shared status it is shown with.
SEVERITY_STATUS = {"error": "error", "warning": "fail", "info": "info"}
#: Severity names (singular, plural) for the chips and filters.
SEVERITY_WORDS = {
    "error": ("error", "errors"),
    "warning": ("warning", "warnings"),
    "info": ("note", "notes"),
}
#: Text colour of each severity's rows (the shared status colours).
SEVERITY_COLORS = {
    severity: STATUS_STYLES[status].chip_text for severity, status in SEVERITY_STATUS.items()
}


def count_text(severity: str, count: int) -> str:
    """``"1 error"``, ``"3 warnings"``, ... (empty for none)."""
    if count == 0:
        return ""
    one, many = SEVERITY_WORDS[severity]
    return f"{count} {one if count == 1 else many}"


class ValidationPanel(QWidget):
    """See module docstring."""

    def __init__(self, controller: WorkspaceController) -> None:
        super().__init__()
        self.controller = controller
        self.summary = QLabel()
        self.summary.setObjectName("validationSummary")
        self.summary.setProperty("role", "muted")
        # The chips show the counts; the plain summary stays for accessibility and callers.
        self.summary.setVisible(False)
        self.summary.setAccessibleName("Findings summary")
        self.chips = {severity: StatusChip() for severity in SEVERITY_STATUS}
        self.clear_chip = StatusChip()
        self.filters: dict[str, QToolButton] = {}
        header = QWidget()
        header.setObjectName("panelToolbar")
        bar = QHBoxLayout(header)
        bar.setContentsMargins(8, 4, 8, 4)
        bar.addWidget(self.clear_chip)
        for chip in self.chips.values():
            bar.addWidget(chip)
        bar.addWidget(self.summary)
        bar.addStretch(1)
        bar.addWidget(QLabel("Show:"))
        for severity in SEVERITY_STATUS:
            button = QToolButton()
            button.setText(SEVERITY_WORDS[severity][1].capitalize())
            button.setObjectName(f"show_{severity}")
            button.setCheckable(True)
            button.setChecked(True)
            button.setToolTip(
                f"Show {SEVERITY_WORDS[severity][1]} in the list (the counts always "
                "include every finding)"
            )
            button.toggled.connect(lambda _on: self._apply_filters())
            self.filters[severity] = button
            bar.addWidget(button)
        self.list = QListWidget()
        self.list.setObjectName("findingsList")
        self.list.setAlternatingRowColors(True)
        self.list.itemActivated.connect(self._activated)
        self.list.itemClicked.connect(self._activated)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(header)
        layout.addWidget(self.list)
        self.findings: list[DesignFinding] = []
        self.refresher = Refresher(
            self,
            self.refresh,
            lambda: controller.revision,
            (
                controller.stateChanged,
                controller.artifactsChanged,
                controller.runsChanged,
                controller.sessionChanged,
                controller.shapesChanged,
            ),
            defer_hidden=lambda: controller.defer_hidden,
        )
        self.refresh()

    def refresh(self) -> None:
        """Recompute the findings."""
        self.findings = self.controller.findings()
        self.list.clear()
        for f in self.findings:
            status = STATUS_STYLES[SEVERITY_STATUS[f.severity]]
            item = QListWidgetItem(f"{status.symbol}  {f.message}")
            item.setData(Qt.ItemDataRole.UserRole, f.target)
            item.setData(Qt.ItemDataRole.UserRole + 1, f.severity)
            item.setForeground(QBrush(QColor(SEVERITY_COLORS[f.severity])))
            tip = SEVERITY_WORDS[f.severity][0].capitalize()
            item.setToolTip(f"{tip}: click to select {f.target}" if f.target else tip)
            self.list.addItem(item)
        counts = {s: sum(f.severity == s for f in self.findings) for s in SEVERITY_STATUS}
        for severity, chip in self.chips.items():
            chip.set_status(SEVERITY_STATUS[severity], count_text(severity, counts[severity]))
        self.clear_chip.set_status("ok", "" if self.findings else "No problems found")
        # Plain-text summary (kept for screen readers and the existing callers).
        self.summary.setText(f"{counts['error']} error(s), {counts['warning']} warning(s)")
        self._apply_filters()

    def _apply_filters(self) -> None:
        for i in range(self.list.count()):
            item = self.list.item(i)
            severity = str(item.data(Qt.ItemDataRole.UserRole + 1))
            item.setHidden(not self.filters[severity].isChecked())

    def messages(self) -> list[str]:
        """Every finding as ``"[SEVERITY] message"``, whatever the filters show."""
        return [f"[{f.severity.upper()}] {f.message}" for f in self.findings]

    def shown(self) -> list[str]:
        """Finding texts as shown in the list (filtered rows left out)."""
        return [
            self.list.item(i).text()
            for i in range(self.list.count())
            if not self.list.item(i).isHidden()
        ]

    def _activated(self, item: QListWidgetItem) -> None:
        target = item.data(Qt.ItemDataRole.UserRole)
        if target:
            self.controller.select(str(target))
