"""Simulation Runs panel: separate preview and CalculiX actions and every run's record.

Laid out like the 3D view (shared theme): an action toolbar (*Run Preview* first), the
CalculiX availability as a status chip (or a banner saying why it is disabled), the run
progress, then one row per run, newest first. Each row names the solver (with its colour
swatch), its state as a status chip (current, stale, not converged, factor of safety
below the limit), the lowest fabric factor of safety, final residual, iterations, run
time and mesh size. Stale runs are greyed and labelled STALE; unconverged runs are red. A
result is never shown as current when its inputs changed.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont, QIcon, QPixmap
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
from envelopelab.project.run_fields import run_fields
from envelopelab_app.controller import WorkspaceController
from envelopelab_app.panels.view3d import FOS_LIMIT, FOS_LIMIT_SOURCE, LAYER_COLORS
from envelopelab_app.refresh import Refresher
from envelopelab_app.result_view import lowest_fos
from envelopelab_app.simulation import CALCULIX, PREVIEW, SimulationManager
from envelopelab_app.theme import STATUS_STYLES, StatusBanner, StatusChip

COLUMNS = (
    "Solver",
    "State",
    "Converged",
    "Min FoS",
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
#: Column of the state chip and of the lowest factor of safety.
STATE_COLUMN = COLUMNS.index("State")
FOS_COLUMN = COLUMNS.index("Min FoS")
EMPTY_TEXT = "No runs yet. Run Preview to solve the design; CalculiX then verifies it."


def state_text(record: RunRecord, status: str) -> str:
    """The *State* column: CURRENT / STALE plus convergence."""
    parts = ["STALE" if status == "stale" else "CURRENT"]
    if not record.converged:
        parts.append("NOT CONVERGED")
    if record.error_count:
        parts.append(f"{record.error_count} error(s)")
    return ", ".join(parts)


def state_kind(record: RunRecord, status: str, fos: float | None) -> str:
    """Status (a key of :data:`~envelopelab_app.theme.STATUS_STYLES`) of a run's row,
    worst first: not converged or errors, stale, factor of safety below the limit."""
    if not record.converged or record.error_count:
        return "error"
    if status == "stale":
        return "stale"
    if fos is not None and fos < FOS_LIMIT:
        return "fail"
    return "ok" if record.solver == CALCULIX else "info"


def _swatch(color: str) -> QIcon:
    pixmap = QPixmap(12, 12)
    pixmap.fill(QColor(color))
    return QIcon(pixmap)


class RunsPanel(QWidget):
    """See module docstring."""

    def __init__(self, controller: WorkspaceController, manager: SimulationManager) -> None:
        super().__init__()
        self.controller = controller
        self.manager = manager
        self.run_preview = QPushButton("Run Preview")
        self.run_preview.setObjectName("primaryAction")
        self.run_preview.setToolTip("Dynamic-relaxation preview solve (EnvelopeLab)")
        self.run_preview.clicked.connect(lambda: manager.start(PREVIEW))
        self.run_calculix = QPushButton("Run CalculiX")
        self.run_calculix.setToolTip("CalculiX verification solve (external ccx process)")
        self.run_calculix.clicked.connect(lambda: manager.start(CALCULIX))
        self.cancel = QPushButton("Cancel")
        self.cancel.clicked.connect(manager.cancel)
        self.remove = QPushButton("Remove run")
        self.remove.setToolTip("Remove the selected run and its result file")
        self.remove.clicked.connect(self._remove)
        self.calculix_chip = StatusChip()
        #: Why CalculiX cannot run (shown only then); its message is ``calculix_label``.
        self.calculix_banner = StatusBanner()
        self.calculix_label = self.calculix_banner.message
        self.calculix_label.setObjectName("calculixStatus")
        self.progress_label = QLabel("Idle")
        self.progress_label.setProperty("role", "muted")
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setMaximumHeight(14)
        self.progress.setTextVisible(False)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(list(COLUMNS))
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.horizontalHeaderItem(FOS_COLUMN).setToolTip(  # type: ignore[union-attr]
            f"Lowest fabric factor of safety (warp or weft) of a current, converged preview "
            f"run; required {FOS_LIMIT:g} ({FOS_LIMIT_SOURCE}). Seams and tapes: see the "
            "Reality Check."
        )
        self.empty = QLabel(EMPTY_TEXT)
        self.empty.setObjectName("emptyState")
        self.empty.setProperty("role", "muted")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        toolbar = QWidget()
        toolbar.setObjectName("panelToolbar")
        bar = QHBoxLayout(toolbar)
        bar.setContentsMargins(8, 4, 8, 4)
        for b in (self.run_preview, self.run_calculix, self.cancel):
            bar.addWidget(b)
        bar.addWidget(self.calculix_chip)
        bar.addStretch(1)
        bar.addWidget(self.remove)
        progress_row = QHBoxLayout()
        progress_row.setContentsMargins(8, 2, 8, 2)
        progress_row.addWidget(self.progress_label, 1)
        progress_row.addWidget(self.progress, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(toolbar)
        layout.addWidget(self.calculix_banner)
        layout.addLayout(progress_row)
        layout.addWidget(self.empty)
        layout.addWidget(self.table, 1)
        manager.calculixChanged.connect(self.update_actions)
        manager.started.connect(self._started)
        manager.progress.connect(self._progress)
        manager.finished.connect(self._finished)
        manager.failed.connect(self._failed)
        manager.idle.connect(self.update_actions)
        self.refresher = Refresher(
            self,
            self.refresh,
            lambda: controller.revision,
            (controller.runsChanged, controller.stateChanged, controller.sessionChanged),
            defer_hidden=lambda: controller.defer_hidden,
        )
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
            version = getattr(self.manager, "calculix_version", "")
            self.calculix_chip.set_status("ok", f"CalculiX {version}".strip())
            self.calculix_chip.setToolTip(self.manager.calculix_message)
            self.calculix_banner.clear()
            self.run_calculix.setToolTip("CalculiX verification solve (external ccx process)")
        else:
            self.calculix_chip.set_status("error", "CalculiX not found")
            self.calculix_banner.set_status(
                "error",
                "CalculiX not found — verification runs are disabled.",
                self.manager.calculix_message,
            )
            self.run_calculix.setToolTip(self.manager.calculix_message)

    def _model(self) -> Any:
        """Solver model of the current design state (None when it is not current)."""
        cache = self.controller.model_cache
        if cache is None or self.controller.artifact_status("rest_mesh") != "current":
            return None
        return cache.built.model

    def _lowest_fos(self, record: RunRecord, status: str) -> float | None:
        """Lowest fabric factor of safety of a current, converged run (else None)."""
        session = self.controller.session
        if session is None or status == "stale" or not record.converged:
            return None
        arrays = session.run_arrays(record.run_id)
        model = self._model()
        if arrays is None or model is None:
            return None
        return lowest_fos(run_fields(arrays, model))

    def refresh(self) -> None:
        """Show every run of the session, newest first."""
        session = self.controller.session
        runs = [] if session is None else list(reversed(session.project.runs))
        self.table.setRowCount(len(runs))
        self.empty.setVisible(not runs)
        self.table.setVisible(bool(runs))
        chip_width = self.table.horizontalHeader().sectionSizeHint(STATE_COLUMN)
        for i, record in enumerate(runs):
            status = self.controller.run_status(record)
            fos = self._lowest_fos(record, status)
            cells = (
                record.solver_label,
                state_text(record, status),
                "yes" if record.converged else "NO",
                "—" if fos is None else f"{fos:.2f}",
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
                if j == COLUMNS.index("Residual"):
                    item.setToolTip(record.residual_measure)
                if status == "stale":
                    item.setForeground(QBrush(QColor("#6b7280")))
                    font = QFont()
                    font.setItalic(True)
                    item.setFont(font)
                elif not record.converged and j in (STATE_COLUMN, 2):
                    item.setForeground(QBrush(QColor(STATUS_STYLES["error"].chip_text)))
                if j == 0:
                    item.setIcon(_swatch(LAYER_COLORS[record.solver]))
                if j == FOS_COLUMN:
                    right = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    item.setTextAlignment(right)
                    if fos is None:
                        item.setToolTip("Only for a current, converged preview run")
                    elif fos < FOS_LIMIT:
                        item.setText(f"{fos:.2f} FAIL")
                        item.setForeground(QBrush(QColor(STATUS_STYLES["fail"].chip_text)))
                        font = QFont()
                        font.setBold(True)
                        item.setFont(font)
                if j == STATE_COLUMN:
                    # The chip shows the state; the text stays for copying and sorting.
                    item.setForeground(QBrush(QColor(0, 0, 0, 0)))
                self.table.setItem(i, j, item)
            kind = state_kind(record, status, fos)
            words = {
                "error": "Not converged" if not record.converged else "Errors",
                "stale": "Stale",
                "fail": "FoS fail",
                "info": "Current",
                "ok": "Current",
            }[kind]
            holder = QWidget()
            box = QHBoxLayout(holder)
            box.setContentsMargins(4, 0, 4, 0)
            box.addWidget(StatusChip(kind, words), 0, Qt.AlignmentFlag.AlignVCenter)
            box.addStretch(1)
            holder.setToolTip(state_text(record, status))
            self.table.setCellWidget(i, STATE_COLUMN, holder)
            chip_width = max(chip_width, holder.sizeHint().width())
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(STATE_COLUMN, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(STATE_COLUMN, chip_width)
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
