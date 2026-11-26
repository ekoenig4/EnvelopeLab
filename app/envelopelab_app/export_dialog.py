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
from envelopelab.export.scale_model import DEFAULT_PAPER_MARGIN, PAPER_SIZES, ScaleModel
from envelopelab_app.theme import STATUS_STYLES

INCH = 0.0254  # m
MM = 0.001  # m
DEFAULT_MODEL_ALLOWANCE = 0.005  # m (a 5 mm glue or sewing tab on a model; source: assumed)


class ExportPackDialog(QDialog):
    """Choose the folder, the fabric roll width and the documents of a build pack.

    ``roll_width`` (m) is the starting roll width (the *Print roll width* preference).
    ``lift_settings`` opens the project's lift-chart settings (a button beside the lift
    charts' check box).

    The 1:1 templates and ``cad/`` (one DXF per piece and ``index.json``) are always
    written; the documents are optional.

    *Scale model* writes a 1:n model instead (:mod:`envelopelab.export.scale_model`):
    every piece scaled and printed on one sheet of the chosen paper, without documents.
    ``fit`` returns the scale denominator of the largest model whose pieces all fit
    (*Fit to paper*) and ``check`` the pieces that do not fit at a scale (the status
    line); both get the :class:`ScaleModel` set in the dialog and return None when the
    design gives no sheets.
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        folder: str = "",
        roll_width: float = DEFAULT_ROLL_WIDTH,
        lift_settings: Callable[[], object] | None = None,
        fit: Callable[[ScaleModel], float | None] | None = None,
        check: Callable[[ScaleModel], list[str] | None] | None = None,
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
        self._fit, self._check = fit, check
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
            "Write a scale model's templates instead of the full-size pack (no documents)"
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
        self.margin = QDoubleSpinBox()
        self.margin.setObjectName("modelMargin")
        self.margin.setRange(0.0, 50.0)
        self.margin.setDecimals(1)
        self.margin.setSuffix(" mm")
        self.margin.setValue(DEFAULT_PAPER_MARGIN / MM)
        self.margin.setToolTip("Blank border the printer needs on every side of the sheet")
        self.fixed_allowance = QCheckBox("Fixed")
        self.fixed_allowance.setObjectName("modelFixedAllowance")
        self.fixed_allowance.setToolTip(
            "Unchecked: the design's seam allowance is scaled with the piece (exact 1:n "
            "copy). Checked: every piece gets this allowance at model size."
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
        self.model_status = QLabel("")
        self.model_status.setObjectName("modelStatus")
        self.model_status.setWordWrap(True)
        note = QLabel(
            "A model shows the shape of the patterns; it is not structurally similar to "
            "the full-size envelope and says nothing about its strength."
        )
        note.setWordWrap(True)
        note.setProperty("role", "muted")
        form = QFormLayout(box)
        form.addRow("Scale", scale_row)
        form.addRow("Paper", self.paper)
        form.addRow("Margin", self.margin)
        form.addRow("Seam allowance", allowance_row)
        form.addRow(self.model_status)
        form.addRow(note)
        box.toggled.connect(self._model_toggled)
        self.fixed_allowance.toggled.connect(self.allowance.setEnabled)
        self.allowance.setEnabled(False)
        for spin in (self.scale, self.margin, self.allowance):
            spin.valueChanged.connect(self.update_model_status)
        self.paper.currentIndexChanged.connect(self.update_model_status)
        self.fixed_allowance.toggled.connect(self.update_model_status)
        return box

    def _model_toggled(self, on: bool) -> None:
        # The documents and the roll describe the full-size envelope.
        self.roll.setEnabled(not on)
        for box in self.checks.values():
            box.setEnabled(not on)
        if on:
            self.update_model_status()

    def _paper_model(self, denominator: float) -> ScaleModel:
        allowance = self.allowance.value() * MM if self.fixed_allowance.isChecked() else None
        return ScaleModel(
            denominator,
            PAPER_SIZES[str(self.paper.currentData())],
            self.margin.value() * MM,
            allowance,
        )

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
        """Say whether every piece fits its sheet at the scale set (red when not)."""
        if not self.model_box.isChecked() or self._check is None:
            return
        try:
            model = self._paper_model(self.scale.value())
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
        k = self.paper.findData(str(state.get("paper", "letter")))
        self.paper.setCurrentIndex(max(k, 0))
        self.margin.setValue(number("margin_mm", self.margin.value()))
        self.allowance.setValue(number("allowance_mm", self.allowance.value()))
        self.fixed_allowance.setChecked(str(state.get("fixed", "")).lower() in ("1", "true"))
        self.model_box.setChecked(str(state.get("enabled", "")).lower() in ("1", "true"))

    def model_state(self) -> dict[str, object]:
        """The scale-model settings, to be saved between exports."""
        return {
            "enabled": self.model_box.isChecked(),
            "scale": self.scale.value(),
            "paper": str(self.paper.currentData()),
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
        """The documents checked (none for a scale model)."""
        if self.model_box.isChecked():
            return frozenset()
        return frozenset(k for k, box in self.checks.items() if box.isChecked())

    def roll_width(self) -> float:
        """The roll width, m."""
        return float(self.roll.value()) * INCH

    def path(self) -> Path:
        """The pack folder."""
        return Path(self.folder.text().strip())
