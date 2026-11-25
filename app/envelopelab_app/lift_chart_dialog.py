"""The lift-chart settings form, and Design ▸ Lift charts… (the form in a dialog).

The form chooses the curves of the lift charts and the top-to-mean offset; the Lift
charts mode shows it beside the charts, the dialog alone.

The values are typed in metric (m, °C, kg) or English (ft, °F, lb) units; switching the
units converts what is typed. Conversion and validation live in
:mod:`envelopelab.project.lift_chart_settings`; this dialog only shows them.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from envelopelab.design.model import SourceTagName
from envelopelab.project.lift_chart_settings import (
    MAX_ALTITUDES,
    MAX_CURVES,
    UNIT_LABELS,
    DisplayedSettings,
    LiftChartSettings,
    MeanModel,
    UnitSystem,
    displayed,
    error_text,
    format_numbers,
    from_displayed,
    parse_numbers,
)

UNIT_CHOICES: tuple[tuple[UnitSystem, str], ...] = (
    ("metric", "Metric (m, °C, kg)"),
    ("english", "English (ft, °F, lb)"),
)
SOURCES = ("assumed", "measured", "datasheet")
MEAN_MODELS: tuple[tuple[MeanModel, str], ...] = (
    ("envelope_shape", "From envelope shape (assumed linear profile)"),
    ("fixed_offset", "Fixed offset below the crown"),
)
#: Load-axis end shown while the axis is automatic, kg.
AUTOMATIC_START = 1000.0


class LiftChartSettingsForm(QWidget):
    """Fields of the lift-chart settings in the builder's units, validated as typed.

    ``edited`` is emitted on every change the builder makes, with the settings typed
    (SI) or None while something does not read (the reason is in :attr:`error`).
    :meth:`show_settings` fills the fields without emitting it.

    Parameters
    ----------
    settings : LiftChartSettings
        Starting settings, SI.
    units : {"metric", "english"}
        Units to type in.
    parent : QWidget, optional
    """

    edited = Signal(object)

    def __init__(
        self,
        settings: LiftChartSettings,
        units: UnitSystem = "metric",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("liftChartSettingsForm")
        self._loading = False
        self._result: LiftChartSettings | None = settings
        self.units = QComboBox()
        self.units.setObjectName("liftUnits")
        for key, text in UNIT_CHOICES:
            self.units.addItem(text, key)
        self.altitudes = self._line("liftAltitudes", f"1 to {MAX_ALTITUDES} pressure altitudes")
        self.ambients = self._line(
            "liftAmbients", f"1 to {MAX_CURVES} ambient temperatures at those altitudes"
        )
        self.isa = self._line(
            "liftIsa", f"1 to {MAX_CURVES} ISA deviations for the ceiling chart (0 = standard day)"
        )
        self.auto_load = QCheckBox("Automatic (the most the balloon lifts)")
        self.auto_load.setObjectName("liftAutoLoad")
        self.max_load = QDoubleSpinBox()
        self.max_load.setObjectName("liftMaxLoad")
        self.max_load.setRange(1.0, 100000.0)
        self.max_load.setDecimals(0)
        self.lowest_top = QDoubleSpinBox()
        self.lowest_top.setObjectName("liftLowestTop")
        self.lowest_top.setRange(-100.0, 500.0)
        self.lowest_top.setDecimals(0)
        self.lowest_top.setToolTip("Lowest crown temperature listed in the CSV")
        self.offset = QDoubleSpinBox()
        self.offset.setObjectName("liftOffset")
        self.offset.setRange(0.0, 200.0)
        self.offset.setDecimals(1)
        self.offset.setToolTip(
            "Crown (top) temperature minus the mean gas temperature. Measure it on your "
            "envelope (crown sensor vs. temperatures logged at several heights)."
        )
        self.source = QComboBox()
        self.source.setObjectName("liftOffsetSource")
        self.source.addItems(SOURCES)
        self.note = QLineEdit()
        self.note.setObjectName("liftOffsetNote")
        self.note.setPlaceholderText("Where the value comes from")
        self.mean_model = QComboBox()
        self.mean_model.setObjectName("liftMeanModel")
        for model_key, model_text in MEAN_MODELS:
            self.mean_model.addItem(model_text, model_key)
        self.mean_model.setToolTip(
            "From envelope shape: the gas is assumed to warm linearly from the mouth to the "
            "crown, and the mean is weighted by where the design's volume lies; never less "
            "than the offset below the crown. Fixed offset: the mean is exactly the offset "
            "below the crown."
        )
        self.mouth = QDoubleSpinBox()
        self.mouth.setObjectName("liftMouthExcess")
        self.mouth.setRange(0.0, 100.0)
        self.mouth.setDecimals(0)
        self.mouth.setSuffix(" %")
        self.mouth.setToolTip(
            "Temperature rise above ambient at the mouth, as a share of the crown's rise. "
            "Lower means a cooler lower envelope: less lift, more conservative."
        )
        self.mouth_source = QComboBox()
        self.mouth_source.setObjectName("liftMouthSource")
        self.mouth_source.addItems(SOURCES)
        self.mouth_note = QLineEdit()
        self.mouth_note.setObjectName("liftMouthNote")
        self.mouth_note.setPlaceholderText("Where the mouth value comes from")
        self._suffix: list[QLabel] = []
        load_row = QHBoxLayout()
        load_row.addWidget(self.max_load)
        load_row.addWidget(self._unit_label("mass"))
        load_row.addWidget(self.auto_load, 1)
        top_row = QHBoxLayout()
        top_row.addWidget(self.lowest_top)
        top_row.addWidget(self._unit_label("temperature"), 1)
        offset_row = QHBoxLayout()
        offset_row.addWidget(self.offset)
        offset_row.addWidget(self._unit_label("difference"))
        offset_row.addWidget(self.source)
        self.limit_auto = QCheckBox("From the fabrics")
        self.limit_auto.setObjectName("liftLimitAuto")
        self.limit_auto.setToolTip(
            "Use the lowest maximum service temperature of the design's fabrics (fabric "
            "library); untick to set this project's own crown temperature limit."
        )
        self.limit = QDoubleSpinBox()
        self.limit.setObjectName("liftLimit")
        self.limit.setRange(-100.0, 700.0)
        self.limit.setDecimals(0)
        self.limit_source = QComboBox()
        self.limit_source.setObjectName("liftLimitSource")
        self.limit_source.addItems(("datasheet", "measured", "assumed"))
        self.limit_note = QLineEdit()
        self.limit_note.setObjectName("liftLimitNote")
        self.limit_note.setPlaceholderText("Where the limit comes from (e.g. fabric datasheet)")
        self.limit_hint = QLabel()
        self.limit_hint.setObjectName("liftLimitHint")
        self.limit_hint.setWordWrap(True)
        self.limit_hint.setProperty("role", "muted")
        self.limit_warning = QLabel()
        self.limit_warning.setObjectName("liftLimitWarning")
        self.limit_warning.setWordWrap(True)
        self.limit_warning.setStyleSheet("color: #b3302f; font-weight: bold;")
        #: Lowest fabric service temperature, K, and its source (set by the owner).
        self._fabric_limit: tuple[float, str] | None = None
        limit_row = QHBoxLayout()
        limit_row.addWidget(self.limit)
        limit_row.addWidget(self._unit_label("temperature"))
        limit_row.addWidget(self.limit_auto, 1)
        limit_row.addWidget(self.limit_source)
        mouth_row = QHBoxLayout()
        mouth_row.addWidget(self.mouth)
        mouth_row.addWidget(QLabel("of the crown's rise above ambient"), 1)
        mouth_row.addWidget(self.mouth_source)
        form = QFormLayout()
        form.addRow("Units", self.units)
        form.addRow("Altitudes", self._with_unit(self.altitudes, "altitude"))
        form.addRow("Ambient temperatures", self._with_unit(self.ambients, "temperature"))
        form.addRow("ISA deviations", self._with_unit(self.isa, "difference"))
        form.addRow("Load axis up to", load_row)
        form.addRow("Lowest top temperature", top_row)
        form.addRow("Crown temperature limit", limit_row)
        self.limit_note_label = QLabel("Limit source note")
        form.addRow(self.limit_note_label, self.limit_note)
        form.addRow("", self.limit_hint)
        form.addRow("", self.limit_warning)
        form.addRow("Mean temperature", self.mean_model)
        self.mouth_label = QLabel("Mouth temperature rise")
        form.addRow(self.mouth_label, mouth_row)
        self.mouth_note_label = QLabel("Mouth source note")
        form.addRow(self.mouth_note_label, self.mouth_note)
        self.offset_label = QLabel("Top minus mean temperature")
        form.addRow(self.offset_label, offset_row)
        form.addRow("Source note", self.note)
        self.error = QLabel()
        self.error.setObjectName("liftError")
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #b3302f;")
        self.defaults = QPushButton("Restore defaults")
        self.defaults.setObjectName("liftDefaults")
        self.defaults.clicked.connect(self._restore_defaults)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(form)
        layout.addWidget(self.error)
        self.units.setCurrentIndex(next(k for k, (u, _t) in enumerate(UNIT_CHOICES) if u == units))
        self._units: UnitSystem = units
        self.show_settings(settings)
        self.units.currentIndexChanged.connect(self._units_changed)
        lines = (self.altitudes, self.ambients, self.isa, self.note, self.mouth_note)
        for line in (*lines, self.limit_note):
            line.textChanged.connect(self._changed)
        for spin in (self.max_load, self.lowest_top, self.offset, self.mouth, self.limit):
            spin.valueChanged.connect(self._changed)
        self.auto_load.toggled.connect(self._changed)
        self.limit_auto.toggled.connect(self._changed)
        for combo in (self.source, self.mean_model, self.mouth_source, self.limit_source):
            combo.currentIndexChanged.connect(self._changed)

    # -- layout helpers -----------------------------------------------------------------

    def _line(self, name: str, tip: str) -> QLineEdit:
        line = QLineEdit()
        line.setObjectName(name)
        line.setToolTip(tip)
        line.setPlaceholderText(tip)
        return line

    def _unit_label(self, kind: str) -> QLabel:
        label = QLabel()
        label.setProperty("unitKind", kind)
        self._suffix.append(label)
        return label

    def _with_unit(self, line: QLineEdit, kind: str) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(line, 1)
        row.addWidget(self._unit_label(kind))
        return row

    def _label_units(self) -> None:
        labels = UNIT_LABELS[self._units]
        for label in self._suffix:
            label.setText(labels[str(label.property("unitKind"))])

    # -- state --------------------------------------------------------------------------

    def unit_system(self) -> UnitSystem:
        """The units typed in."""
        return cast(UnitSystem, self.units.currentData())

    def _shown_temperature(self, kelvin: float) -> float:
        celsius = kelvin - 273.15
        return celsius if self._units == "metric" else celsius * 1.8 + 32.0

    def set_fabric_limit(self, kelvin: float | None, source: str = "") -> None:
        """The lowest service temperature of the design's fabrics, K, and its source tag
        (None: unknown): shown beside the limit and checked against a limit typed."""
        self._fabric_limit = None if kelvin is None else (kelvin, source)
        if self.limit_auto.isChecked() and kelvin is not None:
            self._loading = True
            try:
                self.limit.setValue(self._shown_temperature(kelvin))
            finally:
                self._loading = False
        self._show_limit_check(not self.limit_auto.isChecked())

    def _show_limit_check(self, manual: bool) -> None:
        unit = UNIT_LABELS[self._units]["temperature"]
        if self._fabric_limit is None:
            self.limit_hint.setText("")
            self.limit_warning.setText("")
            return
        kelvin, source = self._fabric_limit
        fabric = self._shown_temperature(kelvin)
        self.limit_hint.setText(f"The design's fabrics allow {fabric:.0f} {unit} [{source}].")
        typed = float(self.limit.value())
        above = manual and typed > fabric + 1e-9
        self.limit_warning.setText(
            f"Above the fabrics' service temperature by {typed - fabric:.0f} "
            f"{UNIT_LABELS[self._units]['difference']}: loads and ceilings at this limit are "
            "not conservative."
            if above
            else ""
        )

    def show_settings(self, settings: LiftChartSettings) -> None:
        """Fill the fields with ``settings`` (SI) in the current units; emits nothing."""
        self._loading = True
        try:
            units = self._units
            shown = displayed(settings, units)
            self._label_units()
            self.altitudes.setText(format_numbers(shown.altitudes))
            self.ambients.setText(format_numbers(shown.ambient_temperatures))
            self.isa.setText(format_numbers(shown.isa_offsets))
            self.auto_load.setChecked(shown.max_load is None)
            # Automatic: start the box at a round 1 000 kg should the builder untick it.
            manual = settings.model_copy(update={"max_load": settings.max_load or AUTOMATIC_START})
            self.max_load.setValue(displayed(manual, units).max_load or AUTOMATIC_START)
            self.lowest_top.setValue(shown.lowest_top_temperature)
            self.offset.setValue(shown.top_to_mean)
            self.source.setCurrentText(shown.source)
            self.note.setText(shown.note)
            self.mean_model.setCurrentIndex(
                next(k for k, (m, _t) in enumerate(MEAN_MODELS) if m == shown.mean_model)
            )
            self.mouth.setValue(shown.mouth_excess)
            self.mouth_source.setCurrentText(shown.mouth_source)
            self.mouth_note.setText(shown.mouth_note)
            self.limit_auto.setChecked(shown.top_limit is None)
            if shown.top_limit is not None:
                self.limit.setValue(shown.top_limit)
            elif self._fabric_limit is not None:
                self.limit.setValue(self._shown_temperature(self._fabric_limit[0]))
            self.limit_source.setCurrentText(shown.limit_source)
            self.limit_note.setText(shown.limit_note)
        finally:
            self._loading = False
        self._validate()

    def _read(self) -> LiftChartSettings:
        """The settings typed, SI; raises ValueError (or a pydantic ValidationError)."""
        values = DisplayedSettings(
            units=self._units,
            altitudes=parse_numbers(self.altitudes.text(), "altitudes"),
            ambient_temperatures=parse_numbers(self.ambients.text(), "ambient temperatures"),
            isa_offsets=parse_numbers(self.isa.text(), "ISA deviations"),
            max_load=None if self.auto_load.isChecked() else float(self.max_load.value()),
            lowest_top_temperature=float(self.lowest_top.value()),
            top_to_mean=float(self.offset.value()),
            source=cast(SourceTagName, self.source.currentText()),
            note=self.note.text().strip(),
            mean_model=cast(MeanModel, self.mean_model.currentData()),
            mouth_excess=float(self.mouth.value()),
            mouth_source=cast(SourceTagName, self.mouth_source.currentText()),
            mouth_note=self.mouth_note.text().strip(),
            top_limit=None if self.limit_auto.isChecked() else float(self.limit.value()),
            limit_source=cast(SourceTagName, self.limit_source.currentText()),
            limit_note=self.limit_note.text().strip(),
        )
        return from_displayed(values)

    def _validate(self) -> None:
        self.max_load.setEnabled(not self.auto_load.isChecked())
        shape = self.mean_model.currentData() == "envelope_shape"
        for widget in (
            self.mouth,
            self.mouth_source,
            self.mouth_note,
            self.mouth_label,
            self.mouth_note_label,
        ):
            widget.setEnabled(shape)
        manual = not self.limit_auto.isChecked()
        for widget in (self.limit, self.limit_source, self.limit_note, self.limit_note_label):
            widget.setEnabled(manual)
        self._show_limit_check(manual)
        # With the shape model the offset is a floor: the profile may need more.
        self.offset_label.setText(
            "Minimum top minus mean" if shape else "Top minus mean temperature"
        )
        try:
            self._result = self._read()
        except ValueError as exc:  # pydantic's ValidationError is a ValueError
            self._result = None
            self.error.setText(error_text(exc))
        else:
            self.error.setText("")

    def _changed(self) -> None:
        if self._loading:
            return
        self._validate()
        self.edited.emit(self._result)

    def _restore_defaults(self) -> None:
        self.show_settings(LiftChartSettings())
        self.edited.emit(self._result)

    def _units_changed(self) -> None:
        # Convert what is typed; when it does not read, keep the text and relabel only.
        current = self._result
        self._units = self.unit_system()
        if current is not None:
            self.show_settings(current)
        else:
            self._label_units()
            self._validate()

    def settings(self) -> LiftChartSettings | None:
        """The settings typed, SI (None while something does not read)."""
        return self._result


class LiftChartDialog(QDialog):
    """The settings form in a dialog; :meth:`settings` returns what was typed (SI).

    Parameters
    ----------
    settings : LiftChartSettings
        Starting settings, SI.
    units : {"metric", "english"}
        Units to type in (remembered by the caller).
    parent : QWidget, optional
    preview : callable, optional
        ``preview(settings)`` shows the charts for the settings typed (e.g. writes a PDF
        and opens it); the *Preview…* button appears only with it.
    """

    def __init__(
        self,
        settings: LiftChartSettings,
        units: UnitSystem = "metric",
        parent: QWidget | None = None,
        preview: Callable[[LiftChartSettings], object] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Lift charts")
        self._preview = preview
        intro = QLabel(
            "Choose the curves the lift charts draw. Type several values separated by "
            "commas. The charts always show metric and English units."
        )
        intro.setWordWrap(True)
        self.form = LiftChartSettingsForm(settings, units, self)
        # The form's fields, under the names the dialog has always had.
        f = self.form
        self.units, self.altitudes, self.ambients, self.isa = (
            f.units,
            f.altitudes,
            f.ambients,
            f.isa,
        )
        self.auto_load, self.max_load, self.lowest_top = f.auto_load, f.max_load, f.lowest_top
        self.offset, self.source, self.note, self.error = f.offset, f.source, f.note, f.error
        self.defaults = f.defaults
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.addButton(self.defaults, QDialogButtonBox.ButtonRole.ResetRole)
        if preview is not None:
            self.preview_button = QPushButton("Preview…")
            self.preview_button.setObjectName("liftPreview")
            self.preview_button.clicked.connect(self._run_preview)
            self.buttons.addButton(self.preview_button, QDialogButtonBox.ButtonRole.ActionRole)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(self.form)
        layout.addWidget(self.buttons)
        f.edited.connect(self._enable)
        f.units.currentIndexChanged.connect(self._enable)
        self._enable()

    def _enable(self, *_args: object) -> None:
        ok = self.form.settings() is not None
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(ok)
        if self._preview is not None:
            self.preview_button.setEnabled(ok)

    def _run_preview(self) -> None:
        settings = self.form.settings()
        if self._preview is not None and settings is not None:
            self._preview(settings)

    def unit_system(self) -> UnitSystem:
        """The units typed in."""
        return self.form.unit_system()

    def settings(self) -> LiftChartSettings | None:
        """The settings typed, SI (None while something does not read)."""
        return self.form.settings()
