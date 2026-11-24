"""Lift charts mode: the curve settings beside the charts of the current design.

Edits in the settings form redraw the charts at once and are saved to the project
(one undo step per pause in typing, :data:`APPLY_DELAY_MS`). The charts are the build
pack's (:func:`envelopelab.export.lift_chart.design_charts`); nothing is computed here.
"""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from envelopelab.export.lift_chart import (
    DesignCharts,
    design_charts,
    input_lines,
    theory_sections,
)
from envelopelab.project.lift_chart_settings import LiftChartSettings, UnitSystem
from envelopelab_app.controller import WorkspaceController
from envelopelab_app.lift_chart_dialog import LiftChartSettingsForm
from envelopelab_app.lift_chart_view import LiftChartView, screen_text
from envelopelab_app.refresh import Refresher

#: Pause in typing after which an edit is saved to the project (one undo step), ms.
APPLY_DELAY_MS = 600
#: QSettings key of the units typed in (shared with the Lift charts dialog).
UNITS_KEY = "lift_chart/units"
#: Chart tabs: (key, label).
CHART_TABS = (
    ("loading", "Maximum load"),
    ("gross", "Gross lift"),
    ("temperature", "Top temperature"),
    ("ceiling", "Ceiling"),
    ("theory", "Theory"),
)
#: Plain-text notation of the theory text and how it is shown (presentation only).
_NOTATION = (
    ("rho_amb", "ρ<sub>amb</sub>"),
    ("rho_int", "ρ<sub>int</sub>"),
    ("rho", "ρ"),
    ("T_amb", "T<sub>amb</sub>"),
    ("T_mean", "T<sub>mean</sub>"),
    ("T_top", "T<sub>top</sub>"),
    ("degR", "°R"),
    ("m3", "m³"),
    ("ft2", "ft²"),
    ("m/s2", "m/s²"),
    ("^5.25588", "<sup>5.25588</sup>"),
)


def theory_html(sections: list[tuple[str, list[str]]]) -> str:
    """The theory text of :func:`envelopelab.export.lift_chart.theory_sections` as rich
    text (headings, paragraphs, Greek letters, sub- and superscripts)."""
    out = []
    for heading, lines in sections:
        out.append(f"<h3>{html.escape(heading)}</h3>")
        for line in lines:
            text = html.escape(screen_text(line))
            for plain, shown in _NOTATION:
                text = text.replace(plain, shown)
            out.append(f"<p>{text}</p>")
    return "\n".join(out)


class LiftChartsPanel(QWidget):
    """Settings form (left); the lift charts and how they are calculated (right).

    Parameters
    ----------
    controller : WorkspaceController
        Workspace (design, outputs, fabric library, edits).
    """

    def __init__(self, controller: WorkspaceController) -> None:
        super().__init__()
        self.controller = controller
        self.settings: QSettings | None = None  # set by the main window
        #: The project's settings last shown in the form (to tell undo from typing).
        self._shown: LiftChartSettings | None = None
        #: Settings typed but not yet saved (None: nothing pending).
        self._pending: LiftChartSettings | None = None
        self.charts: DesignCharts | None = None

        self.form = LiftChartSettingsForm(LiftChartSettings())
        self.form.edited.connect(self._typed)
        self.form.units.currentIndexChanged.connect(self._units_changed)
        intro = QLabel(
            "Choose the curves. The charts redraw as you type and the settings are saved "
            "with the project (Edit ▸ Undo reverts them)."
        )
        intro.setWordWrap(True)
        intro.setProperty("role", "muted")
        self.export_button = QPushButton("Export PDF…")
        self.export_button.setObjectName("liftExportPdf")
        self.export_button.setToolTip("Write these charts as a PDF, with every point as CSV")
        self.export_button.clicked.connect(self.export_dialog)
        buttons = QHBoxLayout()
        buttons.addWidget(self.form.defaults)
        buttons.addStretch(1)
        buttons.addWidget(self.export_button)
        settings_box = QGroupBox("Curves")
        settings_layout = QVBoxLayout(settings_box)
        settings_layout.addWidget(intro)
        settings_layout.addWidget(self.form)
        settings_layout.addLayout(buttons)
        self.notes = QLabel()
        self.notes.setObjectName("liftNotes")
        self.notes.setWordWrap(True)
        self.notes.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        notes_box = QGroupBox("Inputs and assumptions")
        notes_layout = QVBoxLayout(notes_box)
        # The safety notice is last; the notes scroll rather than lose it.
        notes_scroll = QScrollArea()
        notes_scroll.setWidget(self.notes)
        notes_scroll.setWidgetResizable(True)
        notes_scroll.setFrameShape(QFrame.Shape.NoFrame)
        notes_layout.addWidget(notes_scroll)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(settings_box)
        left_layout.addWidget(notes_box, 1)

        self.loading = LiftChartView()
        self.loading.setObjectName("liftLoadingChart")
        self.ceiling = LiftChartView()
        self.ceiling.setObjectName("liftCeilingChart")
        self.temperatures = [LiftChartView() for _ in range(4)]
        self.gross = [LiftChartView() for _ in range(4)]
        gross_page = QWidget()
        gross_page.setObjectName("liftGrossCharts")
        gross_grid = QGridLayout(gross_page)
        gross_grid.setContentsMargins(0, 0, 0, 0)
        for k, view in enumerate(self.gross):
            view.setObjectName(f"liftGrossChart{k}")
            gross_grid.addWidget(view, k // 2, k % 2)
        self.theory = QTextBrowser()
        self.theory.setObjectName("liftTheory")
        self.theory.setOpenExternalLinks(False)
        temperature_page = QWidget()
        grid = QGridLayout(temperature_page)
        grid.setContentsMargins(0, 0, 0, 0)
        for k, view in enumerate(self.temperatures):
            view.setObjectName(f"liftTemperatureChart{k}")
            grid.addWidget(view, k // 2, k % 2)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("liftChartTabs")
        temperature_page.setObjectName("liftTemperatureCharts")
        pages = (self.loading, gross_page, temperature_page, self.ceiling, self.theory)
        for (_name, label), page in zip(CHART_TABS, pages, strict=True):
            self.tabs.addTab(page, label)
        self.status = QLabel()
        self.status.setObjectName("liftStatus")
        self.status.setWordWrap(True)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(self.status)
        right_layout.addWidget(self.tabs, 1)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setObjectName("liftChartsSplitter")
        self.splitter.addWidget(left)
        self.splitter.addWidget(right)
        self.splitter.setStretchFactor(1, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.splitter)

        self._apply_timer = QTimer(self)
        self._apply_timer.setSingleShot(True)
        self._apply_timer.setInterval(APPLY_DELAY_MS)
        self._apply_timer.timeout.connect(self.apply_pending)
        self.refresher = Refresher(
            self,
            self.refresh,
            lambda: controller.revision,
            (controller.stateChanged, controller.sessionChanged, controller.libraryChanged),
            defer_hidden=lambda: controller.defer_hidden,
        )
        self.refresh()

    # -- units --------------------------------------------------------------------------

    def load_units(self) -> None:
        """Type in the units last chosen (``self.settings``)."""
        if self.settings is None:
            return
        units = str(self.settings.value(UNITS_KEY, "metric") or "metric")
        index = 1 if units == "english" else 0
        if self.form.units.currentIndex() != index:
            self.form.units.setCurrentIndex(index)

    def _units_changed(self) -> None:
        if self.settings is not None:
            self.settings.setValue(UNITS_KEY, self.form.unit_system())

    def unit_system(self) -> UnitSystem:
        """The units typed in."""
        return self.form.unit_system()

    # -- project → form and charts ------------------------------------------------------

    def _project_settings(self) -> LiftChartSettings | None:
        session = self.controller.session
        return None if session is None else session.project.state.lift_chart

    def refresh(self) -> None:
        """Show the project's settings (after an undo or on open) and redraw the charts."""
        project = self._project_settings()
        enabled = project is not None
        self.form.setEnabled(enabled)
        self.export_button.setEnabled(enabled)
        if project is not None and project != self._shown and self._pending is None:
            self._shown = project
            self.form.show_settings(project)
        self.redraw()

    def _typed(self, settings: LiftChartSettings | None) -> None:
        if settings is None:
            # Something does not read: keep the charts of the last good settings.
            self._pending = None
            self._apply_timer.stop()
            return
        self._pending = settings
        self.redraw(settings)
        self._apply_timer.start()

    def apply_pending(self) -> bool:
        """Save the settings typed to the project (one undo step); returns whether it
        changed."""
        self._apply_timer.stop()
        pending, self._pending = self._pending, None
        if pending is None or self.controller.session is None:
            return False
        self._shown = pending
        return bool(self.controller.edit("set_lift_chart", pending))

    def redraw(self, settings: LiftChartSettings | None = None) -> None:
        """Draw the charts of the current design with ``settings`` (the form's valid
        settings, else the project's)."""
        session = self.controller.session
        chosen = settings or self.form.settings() or self._project_settings()
        message = ""
        self.charts = None
        if session is None:
            message = "Open or create a design to see its lift charts."
        elif session.design.gores is None:
            message = "Lift charts need a standard-gore design."
        else:
            outputs = self.controller.outputs
            charts = self.controller.attempt(
                design_charts,
                session.design,
                outputs,
                self.controller.fabrics.catalog(),
                chosen,
            )
            if charts is None:
                reason = self.controller.outputs_error or "the envelope mass is not estimated"
                message = f"No lift charts: {reason} (see Validation / Warnings)."
            self.charts = charts
        self._show(message)

    def _show(self, message: str) -> None:
        charts = self.charts
        if charts is None:
            for view in (self.loading, self.ceiling, *self.temperatures, *self.gross):
                view.set_plot(None, message)
            self.status.setText(message)
            self.notes.setText("")
            self.theory.setHtml(f"<p>{html.escape(message)}</p>")
            return
        plots = charts.plots
        self.loading.set_plot(plots.loading)
        self.ceiling.set_plot(plots.ceiling)
        for views, shown in ((self.temperatures, plots.temperatures), (self.gross, plots.gross)):
            for k, view in enumerate(views):
                if k < len(shown):
                    view.set_plot(shown[k])
                    view.show()
                else:
                    view.set_plot(None)
                    view.hide()
        scroll = self.theory.verticalScrollBar().value()
        self.theory.setHtml(theory_html(theory_sections(charts.inputs, charts.axes)))
        self.theory.verticalScrollBar().setValue(scroll)
        limit = charts.inputs.top_limit
        self.status.setText(
            screen_text(
                "Static equilibrium, still air. Red: above the top-temperature limit "
                f"({limit.value - 273.15:.0f} degC, {limit.source}), not permitted."
            )
        )
        self.notes.setText("\n\n".join(screen_text(line) for line in input_lines(charts.inputs)))

    # -- export -------------------------------------------------------------------------

    def export_pdf(self, path: str | Path) -> Path | None:
        """Write the charts shown as ``path`` (PDF) and the points beside it (``.csv``)."""
        from envelopelab.export.lift_chart import write_design_lift_chart

        session = self.controller.session
        if session is None or session.design.gores is None:
            return None
        self.apply_pending()
        pdf = Path(path).with_suffix(".pdf")
        written: Any = self.controller.attempt(
            write_design_lift_chart,
            session.design,
            self.controller.outputs,
            pdf,
            pdf.with_suffix(".csv"),
            self.controller.fabrics.catalog(),
            session.project.state.lift_chart,
        )
        return None if written is None else pdf

    def export_dialog(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export lift charts", "lift-chart.pdf", "PDF (*.pdf)"
        )
        if path:
            self.export_pdf(path)
