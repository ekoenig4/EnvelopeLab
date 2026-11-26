"""File ▸ Export build pack…: where to write the pack, the roll width and its documents,
or a 1:n scale model with every piece on one sheet of paper."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from envelopelab.export.build_pack import DEFAULT_ROLL_WIDTH
from envelopelab.export.documents import DOCUMENTS
from envelopelab.export.scale_model import (
    DEFAULT_PAPER_MARGIN,
    PAPER_SIZES,
    ModelSummary,
    PaperSize,
    ScaleModel,
)
from envelopelab_app.theme import STATUS_STYLES

INCH = 0.0254  # m
MM = 0.001  # m
DEFAULT_MODEL_ALLOWANCE = 0.005  # m (a 5 mm glue or sewing tab on a model; source: assumed)
CUSTOM = "custom"  # print size: width and height typed
WIDTH_ONLY = "width"  # print size: only a maximum width (any length)
CUBIC_FOOT = 0.3048**3  # m^3 (exact, by definition)


def format_volume(m3: float) -> str:
    """A volume for the dialog, metric and English: ``0.250 m3 (8.83 cu ft)``."""
    cu = m3 / CUBIC_FOOT
    metric = f"{m3:,.0f} m3" if m3 >= 100.0 else f"{m3:.3g} m3"
    english = f"{cu:,.0f} cu ft" if cu >= 100.0 else f"{cu:.3g} cu ft"
    return f"{metric} ({english})"


class ExportPackDialog(QDialog):
    """Choose the folder, the fabric roll width and the documents of a build pack.

    ``roll_width`` (m) is the starting roll width (the *Print roll width* preference).
    ``lift_settings`` opens the project's lift-chart settings (a button beside the lift
    charts' check box).

    The 1:1 templates and ``cad/`` (one DXF per piece and ``index.json``) are always
    written; the documents are optional.

    *Scale model* writes a 1:n model instead (:mod:`envelopelab.export.scale_model`):
    every piece and document at model size, each piece printed on one sheet of the
    chosen paper; the lift charts are left out (lift does not scale with the patterns).
    ``fit`` returns the scale denominator of the largest model whose pieces all fit
    (*Fit to paper*) and ``check`` the pieces that do not fit at a scale (the status
    line); both get the :class:`ScaleModel` set in the dialog and return None when the
    design gives no sheets. ``summary`` gives the model's volume, height and width at
    the scale set (:func:`envelopelab.export.scale_model.model_summary`; None: unknown).

    The print size is a standard paper, a custom width and height, or a maximum width
    only (a roll or strip: each page as long as its piece). The seam allowance is either
    set at model size (default 5 mm) or the design's, scaled with the piece.
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        folder: str = "",
        roll_width: float = DEFAULT_ROLL_WIDTH,
        lift_settings: Callable[[], object] | None = None,
        fit: Callable[[ScaleModel], float | None] | None = None,
        check: Callable[[ScaleModel], list[str] | None] | None = None,
        summary: Callable[[ScaleModel], ModelSummary | None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export build pack")
        self.folder = QLineEdit(folder)
        self.folder.setObjectName("packFolder")
        self.folder.setPlaceholderText("Folder for the pack (created if needed)")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.folder, 1)
        row.addWidget(browse)
        self.roll = QDoubleSpinBox()
        self.roll.setObjectName("rollWidth")
        self.roll.setRange(10.0, 200.0)
        self.roll.setDecimals(1)
        self.roll.setSuffix(" in")
        self.roll.setValue(roll_width / INCH)
        self.roll.setToolTip("Fabric roll width: one side of every 1:1 page is no longer")
        form = QFormLayout()
        form.addRow("Folder", row)
        form.addRow("Roll width", self.roll)
        self.checks: dict[str, QCheckBox] = {}
        docs = QVBoxLayout()
        always = QLabel(
            "Always: the 1:1 panel and piece templates (PDF), cad/ (one DXF per piece, index.json)"
        )
        always.setProperty("role", "muted")
        docs.addWidget(always)
        for key in DOCUMENTS:
            box = QCheckBox(DOCUMENTS[key].title)
            box.setObjectName(f"pack_{key}")
            box.setChecked(True)
            box.setToolTip(", ".join(suffix for suffix, _what in DOCUMENTS[key].files))
            self.checks[key] = box
            if key == "lift_chart" and lift_settings is not None:
                # The curves are the project's; edit them without leaving the export.
                settings = QPushButton("Curves and units…")
                settings.setObjectName("packLiftSettings")
                settings.setToolTip("Altitudes, temperatures, load axis and top-to-mean offset")
                settings.clicked.connect(lift_settings)
                row_box = QHBoxLayout()
                row_box.addWidget(box, 1)
                row_box.addWidget(settings)
                docs.addLayout(row_box)
                continue
            docs.addWidget(box)
        form.addRow("Include", docs)
        self._fit, self._check, self._summary = fit, check, summary
        self.model_box = self._model_box()
        note = QLabel(
            "The 3D view shows the run chosen in the 3D view, with its status; a stale or "
            "unconverged run is never coloured as a result."
        )
        note.setWordWrap(True)
        note.setProperty("role", "muted")
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Export")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.model_box)
        layout.addWidget(note)
        layout.addWidget(buttons)
        self._model_toggled(False)

    def _model_box(self) -> QGroupBox:
        box = QGroupBox("Scale model: every piece at 1:n, one per sheet of paper")
        box.setObjectName("scaleModel")
        box.setCheckable(True)
        box.setChecked(False)
        box.setToolTip(
            "Write the pack as a scale model: every piece and document at model size, no "
            "lift charts"
        )
        self.scale = QDoubleSpinBox()
        self.scale.setObjectName("modelScale")
        self.scale.setRange(1.0, 10000.0)
        self.scale.setDecimals(2)
        self.scale.setPrefix("1 : ")
        self.scale.setValue(20.0)
        self.scale.setToolTip("Scale denominator n: every length is divided by n")
        fit = QPushButton("Fit to paper")
        fit.setObjectName("modelFit")
        fit.setToolTip("The largest whole-number scale at which every piece fits one sheet")
        fit.clicked.connect(self.fit_to_paper)
        fit.setEnabled(self._fit is not None)
        scale_row = QHBoxLayout()
        scale_row.addWidget(self.scale, 1)
        scale_row.addWidget(fit)
        self.paper = QComboBox()
        self.paper.setObjectName("modelPaper")
        for key, paper in PAPER_SIZES.items():
            self.paper.addItem(paper.name, key)
        self.paper.addItem("Custom width x height", CUSTOM)
        self.paper.addItem("Maximum width only (any length)", WIDTH_ONLY)
        self.print_width = QDoubleSpinBox()
        self.print_width.setObjectName("modelPrintWidth")
        self.print_height = QDoubleSpinBox()
        self.print_height.setObjectName("modelPrintHeight")
        for spin, value in ((self.print_width, 215.9), (self.print_height, 279.4)):
            spin.setRange(20.0, 10000.0)
            spin.setDecimals(1)
            spin.setSuffix(" mm")
            spin.setValue(value)
        self.print_width.setToolTip("Widest the printer prints, across the paper")
        self.print_height.setToolTip("Longest page the printer takes")
        size_row = QHBoxLayout()
        size_row.addWidget(self.print_width, 1)
        size_row.addWidget(QLabel("x"))
        size_row.addWidget(self.print_height, 1)
        self.margin = QDoubleSpinBox()
        self.margin.setObjectName("modelMargin")
        self.margin.setRange(0.0, 50.0)
        self.margin.setDecimals(1)
        self.margin.setSuffix(" mm")
        self.margin.setValue(DEFAULT_PAPER_MARGIN / MM)
        self.margin.setToolTip("Blank border the printer needs on every side of the sheet")
        self.fixed_allowance = QCheckBox("Set at model size")
        self.fixed_allowance.setObjectName("modelFixedAllowance")
        self.fixed_allowance.setChecked(True)
        self.fixed_allowance.setToolTip(
            "Checked: every piece gets this allowance at model size. Unchecked: the "
            "design's seam allowance is scaled with the piece (an exact 1:n copy, often "
            "too narrow to sew or glue)."
        )
        self.allowance = QDoubleSpinBox()
        self.allowance.setObjectName("modelAllowance")
        self.allowance.setRange(0.0, 50.0)
        self.allowance.setDecimals(1)
        self.allowance.setSuffix(" mm")
        self.allowance.setValue(DEFAULT_MODEL_ALLOWANCE / MM)
        allowance_row = QHBoxLayout()
        allowance_row.addWidget(self.fixed_allowance)
        allowance_row.addWidget(self.allowance, 1)
        self.model_size = QLabel("")
        self.model_size.setObjectName("modelSize")
        self.model_size.setWordWrap(True)
        self.model_status = QLabel("")
        self.model_status.setObjectName("modelStatus")
        self.model_status.setWordWrap(True)
        note = QLabel(
            "A model shows the shape of the patterns; it is not structurally similar to "
            "the full-size envelope. Its documents give weights, loads, strengths and "
            "factors of safety as n/a, and it has no lift charts."
        )
        note.setWordWrap(True)
        note.setProperty("role", "muted")
        form = QFormLayout(box)
        form.addRow("Scale", scale_row)
        form.addRow("Paper", self.paper)
        form.addRow("Print size", size_row)
        form.addRow("Margin", self.margin)
        form.addRow("Seam allowance", allowance_row)
        form.addRow("Model", self.model_size)
        form.addRow(self.model_status)
        form.addRow(note)
        box.toggled.connect(self._model_toggled)
        self.fixed_allowance.toggled.connect(self.allowance.setEnabled)
        for spin in (self.scale, self.margin, self.allowance, self.print_width, self.print_height):
            spin.valueChanged.connect(self.update_model_status)
        self.paper.currentIndexChanged.connect(self._paper_changed)
        self._enable_size()
        self.fixed_allowance.toggled.connect(self.update_model_status)
        return box

    def _model_toggled(self, on: bool) -> None:
        # A model is printed on paper, not a roll, and has no lift charts (lift does not
        # scale with the patterns); every other document is written at model size.
        self.roll.setEnabled(not on)
        if "lift_chart" in self.checks:
            self.checks["lift_chart"].setEnabled(not on)
        if on:
            self.update_model_status()

    def _enable_size(self) -> None:
        # The print size is typed for a custom size (both) or a maximum width (width).
        key = str(self.paper.currentData())
        self.print_width.setEnabled(key in (CUSTOM, WIDTH_ONLY))
        self.print_height.setEnabled(key == CUSTOM)

    def _paper_changed(self) -> None:
        self._enable_size()
        self.update_model_status()

    def paper_size(self) -> PaperSize:
        """The print size chosen: a standard paper, a custom one or a maximum width."""
        key = str(self.paper.currentData())
        if key == CUSTOM:
            return PaperSize.custom(self.print_width.value() * MM, self.print_height.value() * MM)
        if key == WIDTH_ONLY:
            return PaperSize.custom(self.print_width.value() * MM)
        return PAPER_SIZES[key]

    def _paper_model(self, denominator: float) -> ScaleModel:
        allowance = self.allowance.value() * MM if self.fixed_allowance.isChecked() else None
        return ScaleModel(denominator, self.paper_size(), self.margin.value() * MM, allowance)

    def fit_to_paper(self) -> float | None:
        """*Fit to paper*: set the scale to the largest whole-number 1:n at which every
        piece fits; returns n (None when it cannot be found)."""
        if self._fit is None:
            return None
        try:
            n = self._fit(self._paper_model(self.scale.value()))
        except ValueError as exc:
            self._status(str(exc), ok=False)
            return None
        if n is None:
            return None
        if n > self.scale.maximum():
            self._status(f"needs 1:{n:g}, smaller than this dialog allows", ok=False)
            return None
        self.scale.setValue(n)
        self.update_model_status()
        return n

    def update_model_status(self) -> None:
        """Show the model's size at the scale set and say whether every piece fits its
        sheet (red when not)."""
        if not self.model_box.isChecked():
            return
        try:
            model = self._paper_model(self.scale.value())
        except ValueError as exc:
            self._status(str(exc), ok=False)
            return
        size = None if self._summary is None else self._summary(model)
        self.model_size.setText(
            ""
            if size is None
            else f"volume {format_volume(size.volume)}, height {size.height * 1000:,.0f} mm, "
            f"widest {size.max_diameter * 1000:,.0f} mm"
        )
        if self._check is None:
            return
        try:
            big = self._check(model)
        except ValueError as exc:
            self._status(str(exc), ok=False)
            return
        if big is None:
            self._status("", ok=True)
        elif big:
            names = ", ".join(big[:4]) + (f" and {len(big) - 4} more" if len(big) > 4 else "")
            self._status(
                f"{len(big)} piece(s) larger than the paper at {model.label()}: {names}. "
                "Their pages are enlarged and marked in red; choose a smaller scale.",
                ok=False,
            )
        else:
            self._status(f"Every piece fits one sheet at {model.label()}.", ok=True)

    def _status(self, text: str, ok: bool) -> None:
        self.model_status.setText(text)
        colour = STATUS_STYLES["error"].border
        self.model_status.setStyleSheet("" if ok else f"color: {colour}; font-weight: bold;")

    def scale_model(self) -> ScaleModel | None:
        """The scale model to write, or None for the full-size pack."""
        if not self.model_box.isChecked():
            return None
        return self._paper_model(self.scale.value())

    def set_model_state(self, state: dict[str, object]) -> None:
        """Restore the scale-model settings saved by :meth:`model_state`."""

        def number(key: str, default: float) -> float:
            try:
                return float(state.get(key, default))  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return default

        self.scale.setValue(number("scale", self.scale.value()))
        self.print_width.setValue(number("print_width_mm", self.print_width.value()))
        self.print_height.setValue(number("print_height_mm", self.print_height.value()))
        k = self.paper.findData(str(state.get("paper", "letter")))
        self.paper.setCurrentIndex(max(k, 0))
        self.margin.setValue(number("margin_mm", self.margin.value()))
        self.allowance.setValue(number("allowance_mm", self.allowance.value()))
        fixed = str(state.get("fixed", "true")).lower()
        self.fixed_allowance.setChecked(fixed in ("1", "true"))
        self.model_box.setChecked(str(state.get("enabled", "")).lower() in ("1", "true"))

    def model_state(self) -> dict[str, object]:
        """The scale-model settings, to be saved between exports."""
        return {
            "enabled": self.model_box.isChecked(),
            "scale": self.scale.value(),
            "paper": str(self.paper.currentData()),
            "print_width_mm": self.print_width.value(),
            "print_height_mm": self.print_height.value(),
            "margin_mm": self.margin.value(),
            "fixed": self.fixed_allowance.isChecked(),
            "allowance_mm": self.allowance.value(),
        }

    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Build pack folder", self.folder.text())
        if path:
            self.folder.setText(path)

    def _accept(self) -> None:
        if self.folder.text().strip():
            self.accept()

    def include(self) -> frozenset[str]:
        """The documents checked (a scale model: all but the lift charts)."""
        chosen = frozenset(k for k, box in self.checks.items() if box.isChecked())
        return chosen - {"lift_chart"} if self.model_box.isChecked() else chosen

    def roll_width(self) -> float:
        """The roll width, m."""
        return float(self.roll.value()) * INCH

    def path(self) -> Path:
        """The pack folder."""
        return Path(self.folder.text().strip())
