"""Boxes for a point on the envelope, shown in metres or in balloon coordinates.

The point is stored as gore, fraction ``across`` from the gore's centreline and tape
position (m). The boxes show it as the units preference says
(:mod:`envelopelab.project.coordinates`):

* metres: gore, offset from the gore's centreline (m) and tape position from the mouth (m);
* balloon coordinates: gore, fraction across it from seam to seam (0-1), and panel row
  with the fraction up it (0-1).

Edits always come out in the stored form (``edited``), so what is saved never depends on
the preference.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QSpinBox,
    QWidget,
)

from envelopelab.project.coordinates import (
    PositionUnits,
    across_from_metres,
    across_metres,
    envelope_position,
    row_position,
)
from envelopelab_app.hints import set_hint


class PositionEditor(QObject):
    """Gore, across and up boxes of one point on the envelope.

    ``edited(gore, across, tape)`` gives the point as stored: gore number (from 1),
    fraction from the gore's centreline in [-0.5, 0.5] and tape position from the mouth,
    m. ``hint`` prefixes the hint keys of the boxes (``<hint>gore``, ``<hint>across``,
    ``<hint>tape_position``).
    """

    edited = Signal(int, float, float)

    def __init__(self, name: str, hint: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.units: PositionUnits = "metres"
        self.surface: Any = None
        self._stored = (1, 0.0, 0.0)
        self._filling = False
        self.gore = QSpinBox()
        self.gore.setObjectName(f"{name}Gore")
        self.gore.setRange(1, 999)
        self.across = QDoubleSpinBox()
        self.across.setObjectName(f"{name}Across")
        self.across.setDecimals(3)
        self.tape = QDoubleSpinBox()
        self.tape.setObjectName(f"{name}Tape")
        self.tape.setDecimals(3)
        self.tape.setRange(0.001, 1000.0)
        self.tape.setSuffix(" m")
        self.tape.setSingleStep(0.05)
        self.row = QComboBox()
        self.row.setObjectName(f"{name}Row")
        self.row_fraction = QDoubleSpinBox()
        self.row_fraction.setObjectName(f"{name}RowFraction")
        self.row_fraction.setDecimals(3)
        self.row_fraction.setRange(0.0, 1.0)
        self.row_fraction.setSingleStep(0.05)
        for box in (self.gore, self.across, self.tape, self.row_fraction):
            box.setKeyboardTracking(False)
        self.gore.valueChanged.connect(lambda _v: self._gore_changed())
        self.across.valueChanged.connect(lambda _v: self._across_changed())
        self.tape.valueChanged.connect(lambda _v: self._up_changed())
        self.row.activated.connect(lambda _i: self._up_changed())
        self.row_fraction.valueChanged.connect(lambda _v: self._up_changed())
        set_hint(self.gore, f"{hint}gore")
        set_hint(self.across, f"{hint}across")
        for widget in (self.tape, self.row, self.row_fraction):
            set_hint(widget, f"{hint}tape_position")
        self.row_box = QWidget()
        row_layout = QHBoxLayout(self.row_box)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(self.row)
        row_layout.addWidget(self.row_fraction, 1)

    # -- layout -----------------------------------------------------------------------
    def add_to(self, form: QFormLayout) -> None:
        """Add the boxes as rows of ``form`` (labels follow the units)."""
        form.addRow("Gore", self.gore)
        form.addRow(self._across_label(), self.across)
        form.addRow("Up the tape from mouth", self.tape)
        form.addRow("Panel row, fraction up", self.row_box)
        self._show_units(form)

    def _across_label(self) -> str:
        if self.units == "balloon":
            return "Across gore (0 seam … 1 next seam)"
        return "From gore centre (m, + towards next)"

    def _show_units(self, form: QFormLayout | None = None) -> None:
        balloon = self.units == "balloon"
        form = form or self._form()
        if form is not None:
            for widget, shown in ((self.tape, not balloon), (self.row_box, balloon)):
                form.setRowVisible(widget, shown)
            label = form.labelForField(self.across)
            if label is not None:
                label.setText(self._across_label())  # type: ignore[attr-defined]

    def _form(self) -> QFormLayout | None:
        parent = self.gore.parentWidget()
        layout = parent.layout() if parent is not None else None
        return layout if isinstance(layout, QFormLayout) else None

    # -- data -------------------------------------------------------------------------
    def set_context(self, surface: Any, units: PositionUnits, gores: int) -> None:
        """The envelope (rows and widths), the units preference and the number of gores."""
        self.surface = surface
        self.units = units if surface is not None else "metres"
        self.gore.blockSignals(True)
        self.gore.setMaximum(max(int(gores), 1))
        self.gore.blockSignals(False)
        self.row.blockSignals(True)
        self.row.clear()
        if surface is not None:
            for r in surface.rows:
                self.row.addItem(r.label, r.label)
        self.row.blockSignals(False)
        self._show_units()
        self.set_position(*self._stored)

    def set_position(self, gore: int, across: float, tape: float) -> None:
        """Show a stored point (gore, fraction from the centreline, tape position m)."""
        self._stored = (int(gore), float(across), float(tape))
        self._filling = True
        try:
            for box in (self.gore, self.across, self.tape, self.row_fraction):
                box.blockSignals(True)
            self.gore.setValue(int(gore))
            self.tape.setValue(float(tape))
            if self.units == "balloon" and self.surface is not None:
                self.across.setRange(0.0, 1.0)
                self.across.setSuffix("")
                self.across.setSingleStep(0.05)
                self.across.setValue(float(across) + 0.5)
                row, fraction = row_position(self.surface, tape)
                self.row.setCurrentIndex(max(self.row.findData(row), 0))
                self.row_fraction.setValue(fraction)
            elif self.surface is not None:
                half = abs(across_metres(self.surface, 0.5, tape))
                self.across.setRange(-half, half)
                self.across.setSuffix(" m")
                self.across.setSingleStep(0.01)
                self.across.setValue(across_metres(self.surface, across, tape))
            else:
                self.across.setRange(-0.5, 0.5)
                self.across.setSuffix("")
                self.across.setValue(float(across))
        finally:
            for box in (self.gore, self.across, self.tape, self.row_fraction):
                box.blockSignals(False)
            self._filling = False

    def position(self) -> tuple[int, float, float]:
        """The stored point the boxes show."""
        return self._stored

    # -- edits ------------------------------------------------------------------------
    def _emit(self, gore: int, across: float, tape: float) -> None:
        self._stored = (gore, across, tape)
        self.edited.emit(gore, across, tape)

    def _gore_changed(self) -> None:
        _, across, tape = self._stored
        self._emit(int(self.gore.value()), across, tape)

    def _across_changed(self) -> None:
        gore, _, tape = self._stored
        if self.units == "balloon":
            across = float(self.across.value()) - 0.5
        elif self.surface is not None:
            across = across_from_metres(self.surface, float(self.across.value()), tape)
        else:
            across = float(self.across.value())
        self._emit(gore, across, tape)

    def _up_changed(self) -> None:
        gore, across, _ = self._stored
        if self.units == "balloon" and self.surface is not None:
            row = str(self.row.currentData())
            _, _, tape = envelope_position(
                self.surface, gore, across + 0.5, row, float(self.row_fraction.value())
            )
        else:
            tape = float(self.tape.value())
        # The fraction across the gore is kept; its offset in metres follows the width.
        self._emit(gore, across, tape)
        self.set_position(gore, across, tape)
