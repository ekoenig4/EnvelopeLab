"""Simulation Runs panel: separate preview and CalculiX actions and every run's record.

Each row names the solver (with its colour), the convergence state, final residual,
iterations, run time and mesh size. Stale runs are greyed and labelled STALE; unconverged
runs are red. A result is never shown as current when its inputs changed.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from envelopelab.project.model import RunRecord
from envelopelab_app.controller import WorkspaceController
from envelopelab_app.panels.view3d import LAYER_COLORS
from envelopelab_app.simulation import CALCULIX, PREVIEW, SimulationManager

COLUMNS = (
    "Solver",
    "State",
    "Converged",
    "Residual",
    "Iterations",
    "Run time (s)",
    "Nodes / elements",
    "Mesh (mm)",
    "Volume (m³)",
    "Lift (N)",
    "Material sources",
    "Run id",
)


def state_text(record: RunRecord, status: str) -> str:
    """The *State* column: CURRENT / STALE plus convergence."""
    parts = ["STALE" if status == "stale" else "CURRENT"]
    if not record.converged:
        parts.append("NOT CONVERGED")
    if record.error_count:
        parts.append(f"{record.error_count} error(s)")
    return ", ".join(parts)


class RunsPanel(QWidget):
    """See module docstring."""

    def __init__(self, controller: WorkspaceController, manager: SimulationManager) -> None:
        super().__init__()
        self.controller = controller
        self.manager = manager
        self.run_preview = QPushButton("Run Preview")
        self.run_preview.setToolTip("Dynamic-relaxation preview solve (EnvelopeLab)")
        self.run_preview.clicked.connect(lambda: manager.start(PREVIEW))
        self.run_calculix = QPushButton("Run CalculiX")
        self.run_calculix.setToolTip("CalculiX verification solve (external ccx process)")
        self.run_calculix.clicked.connect(lambda: manager.start(CALCULIX))
        self.cancel = QPushButton("Cancel")
        self.cancel.clicked.connect(manager.cancel)
        self.remove = QPushButton("Remove run")
        self.remove.clicked.connect(self._remove)
        self.calculix_label = QLabel()
        self.calculix_label.setObjectName("calculixStatus")
        self.calculix_label.setWordWrap(True)
        self.progress_label = QLabel("Idle")
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(list(COLUMNS))
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        buttons = QHBoxLayout()
        for b in (self.run_preview, self.run_calculix, self.cancel, self.remove):
            buttons.addWidget(b)
        layout = QVBoxLayout(self)
        layout.addLayout(buttons)
        layout.addWidget(self.calculix_label)
        layout.addWidget(self.progress_label)
        layout.addWidget(self.progress)
        layout.addWidget(self.table)
        manager.calculixChanged.connect(self.update_actions)
        manager.started.connect(self._started)
        manager.progress.connect(self._progress)
        manager.finished.connect(self._finished)
        manager.failed.connect(self._failed)
        manager.idle.connect(self.update_actions)
        for signal in (controller.runsChanged, controller.stateChanged, controller.sessionChanged):
            signal.connect(self.refresh)
        self.update_actions()
        self.refresh()

    def update_actions(self) -> None:
        """Enable the run buttons that can be used now."""
        has_design = self.controller.is_gore
        running = self.manager.running
        self.run_preview.setEnabled(has_design and not running)
        self.run_calculix.setEnabled(has_design and not running and self.manager.calculix_available)
        self.cancel.setEnabled(running)
        if self.manager.calculix_available:
            self.calculix_label.setText(self.manager.calculix_message)
            self.calculix_label.setStyleSheet("color: #155724;")
            self.run_calculix.setToolTip("CalculiX verification solve (external ccx process)")
        else:
            self.calculix_label.setText(self.manager.calculix_message)
            self.calculix_label.setStyleSheet("color: #b00020; font-weight: bold;")
            self.run_calculix.setToolTip(self.manager.calculix_message)

    def refresh(self) -> None:
        """Show every run of the session, newest first."""
        session = self.controller.session
        runs = [] if session is None else list(reversed(session.project.runs))
        self.table.setRowCount(len(runs))
        for i, record in enumerate(runs):
            status = self.controller.run_status(record)
            cells = (
                record.solver_label,
                state_text(record, status),
                "yes" if record.converged else "NO",
                f"{record.residual:.3e}",
                str(record.iterations),
                f"{record.run_time:.1f}",
                f"{record.n_nodes} / {record.n_elements}",
                f"{record.mesh_target_mm:g}",
                f"{record.volume:.2f}",
                f"{record.lift:.0f}",
                ", ".join(record.material_sources),
                record.run_id,
            )
            for j, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, record.run_id)
                if j == 3:
                    item.setToolTip(record.residual_measure)
                if status == "stale":
                    item.setForeground(QBrush(QColor("#8a8a8a")))
                    font = QFont()
                    font.setItalic(True)
                    item.setFont(font)
                elif not record.converged and j in (1, 2):
                    item.setForeground(QBrush(QColor("#b00020")))
                if j == 0:
                    color = QColor(LAYER_COLORS[record.solver])
                    color.setAlpha(70)
                    item.setBackground(QBrush(color))
                self.table.setItem(i, j, item)
        self.update_actions()

    def _remove(self) -> None:
        session = self.controller.session
        rows = self.table.selectionModel().selectedRows()
        if session is None or not rows:
            return
        cell = self.table.item(rows[0].row(), 0)
        if cell is not None:
            session.remove_run(str(cell.data(Qt.ItemDataRole.UserRole)))

    def _started(self, solver: str) -> None:
        self.progress.setValue(0)
        name = "Preview (dynamic relaxation)" if solver == PREVIEW else "CalculiX verification"
        self.progress_label.setText(f"Running: {name}…")
        self.update_actions()

    def _progress(self, message: str, fraction: float) -> None:
        self.progress_label.setText(message)
        self.progress.setValue(int(1000 * max(0.0, min(1.0, fraction))))

    def _finished(self, record: RunRecord) -> None:
        self.progress.setValue(1000)
        verdict = "converged" if record.converged else f"NOT converged ({record.status})"
        self.progress_label.setText(
            f"{record.solver_label}: {verdict}, residual {record.residual:.2e}, "
            f"{record.run_time:.1f} s"
        )
        self.update_actions()

    def _failed(self, message: str) -> None:
        self.progress_label.setText(message.splitlines()[0])
        self.progress.setValue(0)
        self.update_actions()
