"""Preferences dialog and the fabric form of the shared fabric library."""

from __future__ import annotations

from typing import Literal

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from envelopelab.materials.repository import (
    SOURCE_TAGS,
    Fabric,
    MaterialProperty,
    source_tag,
    validate_fabric,
)
from envelopelab_app.settings import Preferences


class PreferencesDialog(QDialog):
    """Edit a copy of the preferences; ``result_preferences()`` returns it."""

    def __init__(self, prefs: Preferences, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.autosave = QDoubleSpinBox()
        self.autosave.setRange(0.0, 120.0)
        self.autosave.setSuffix(" min (0 = off)")
        self.autosave.setValue(prefs.autosave_minutes)
        self.preview_mesh = QDoubleSpinBox()
        self.preview_mesh.setRange(50.0, 10000.0)
        self.preview_mesh.setSuffix(" mm")
        self.preview_mesh.setValue(prefs.preview_mesh_mm)
        self.calculix_mesh = QDoubleSpinBox()
        self.calculix_mesh.setRange(50.0, 10000.0)
        self.calculix_mesh.setSuffix(" mm")
        self.calculix_mesh.setValue(prefs.calculix_mesh_mm)
        self.ccx = QLineEdit(prefs.ccx_path)
        self.ccx.setPlaceholderText("ccx on PATH or $ENVELOPELAB_CCX")
        self.auto_patterns = QCheckBox("Regenerate patterns after every edit")
        self.auto_patterns.setChecked(prefs.auto_regenerate_patterns)
        self.keep_rows = QCheckBox("Keep panel rows fitted to the meridian after profile edits")
        self.keep_rows.setChecked(prefs.keep_rows_fitted)
        self.enable_3d = QCheckBox("Use the PyVista 3D view (next start)")
        self.enable_3d.setChecked(prefs.enable_3d)
        self.recovery = QLineEdit(prefs.recovery_dir)
        self.recovery.setPlaceholderText("application data folder")
        self.material_library = QLineEdit(prefs.material_library)
        self.material_library.setPlaceholderText(
            "$ENVELOPELAB_MATERIAL_LIBRARY or materials.sqlite in the application data folder"
        )
        form = QFormLayout()
        form.addRow("Autosave every", self.autosave)
        form.addRow("Preview mesh edge length", self.preview_mesh)
        form.addRow("CalculiX mesh edge length", self.calculix_mesh)
        form.addRow("CalculiX executable", self.ccx)
        form.addRow(self.auto_patterns)
        form.addRow(self.keep_rows)
        form.addRow(self.enable_3d)
        form.addRow("Recovery folder", self.recovery)
        form.addRow("Fabric library file (next start)", self.material_library)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def result_preferences(self) -> Preferences:
        """Preferences as edited."""
        return Preferences(
            autosave_minutes=self.autosave.value(),
            preview_mesh_mm=self.preview_mesh.value(),
            calculix_mesh_mm=self.calculix_mesh.value(),
            ccx_path=self.ccx.text().strip(),
            auto_regenerate_patterns=self.auto_patterns.isChecked(),
            keep_rows_fitted=self.keep_rows.isChecked(),
            enable_3d=self.enable_3d.isChecked(),
            recovery_dir=self.recovery.text().strip(),
            material_library=self.material_library.text().strip(),
        )


#: Fabric properties in form order: (field, label, library unit).
FABRIC_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("areal_mass", "Areal mass", "g/m²"),
    ("warp_tensile", "Warp tensile strength", "as entered"),
    ("weft_tensile", "Weft tensile strength", "as entered"),
    ("tear", "Tear strength", "as entered"),
    ("seam_efficiency", "Seam efficiency", "0-1"),
    ("e_warp", "Warp modulus", "Pa"),
    ("e_weft", "Weft modulus", "Pa"),
    ("g", "Shear modulus", "Pa"),
    ("nu", "Poisson's ratio", "-"),
    ("porosity", "Porosity", "as entered"),
    ("max_service_temperature", "Max service temperature", "°C"),
    ("roll_width", "Roll width", "m"),
    ("cost", "Cost", "per m²"),
)

FabricDialogMode = Literal["new", "edit", "duplicate"]


def split_source(source: str) -> tuple[str, str]:
    """``(tag, note)`` of a source string; an untagged source becomes an ``assumed`` note."""
    tag = source_tag(source)
    if tag is None:
        return "assumed", source.strip()
    rest = source.strip()[len(tag) :]
    return tag, rest.strip(" -:,;")


def format_value(value: float) -> str:
    """Shortest text that reads back as exactly ``value`` (``42``, ``1.2e+09``)."""
    short = f"{value:g}"
    return short if float(short) == value else repr(value)


def join_source(tag: str, note: str) -> str:
    """Source string from a tag and an optional note (``"measured - lab 3"``)."""
    note = note.strip()
    return f"{tag} - {note}" if note else tag


class _SourceField:
    """Value, source-tag and note editors of one fabric property."""

    def __init__(self, value: str, source: str) -> None:
        self.value = QLineEdit(value)
        self.tag = QComboBox()
        self.tag.addItems(list(SOURCE_TAGS))
        tag, note = split_source(source)
        self.tag.setCurrentText(tag)
        self.note = QLineEdit(note)
        self.note.setPlaceholderText("note: datasheet name, test, reason")

    def source(self) -> str:
        return join_source(self.tag.currentText(), self.note.text())


class FabricDialog(QDialog):
    """Create or edit a fabric of the shared library.

    Every value needs a source tag (``datasheet | measured | assumed``) and may carry a
    note. *OK* only closes the dialog when :func:`~envelopelab.materials.repository.
    validate_fabric` accepts the fabric; otherwise the problems are listed. Values are in
    library units (see :mod:`envelopelab.materials.repository`).

    Parameters
    ----------
    mode : {"new", "edit", "duplicate"}
        ``edit`` keeps the id fixed; ``duplicate`` starts from ``fabric`` with a new id.
    fabric : Fabric, optional
        Values to start from (required for ``edit`` and ``duplicate``).
    taken_ids : set of str
        Ids already in the library (a new or duplicated fabric must not reuse one).
    """

    def __init__(
        self,
        mode: FabricDialogMode,
        fabric: Fabric | None = None,
        taken_ids: set[str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        if mode != "new" and fabric is None:
            raise ValueError(f"a {mode} fabric dialog needs a fabric")
        self.mode = mode
        self.taken_ids = set(taken_ids or ())
        self._result: Fabric | None = None
        titles = {"new": "New fabric", "edit": "Edit fabric", "duplicate": "Duplicate fabric"}
        self.setWindowTitle(titles[mode])
        start_id = "" if fabric is None else fabric.fabric_id
        start_name = "" if fabric is None else fabric.name
        if mode == "duplicate" and fabric is not None:
            start_id = self._free_id(f"{fabric.fabric_id}_copy")
            start_name = f"{fabric.name} (copy)"
        self.fabric_id = QLineEdit(start_id)
        self.fabric_id.setReadOnly(mode == "edit")
        self.fabric_id.setPlaceholderText("e.g. my_polyester_2026")
        self.name = QLineEdit(start_name)
        self.color = _SourceField(
            "" if fabric is None else fabric.color,
            "assumed" if fabric is None else fabric.color_source,
        )
        self.color.value.setPlaceholderText("colour name or #rrggbb")
        self.fields: dict[str, _SourceField] = {}
        grid = QGridLayout()
        for col, heading in enumerate(("Property", "Value", "Unit", "Source", "Note")):
            grid.addWidget(QLabel(f"<b>{heading}</b>"), 0, col)
        for row, (name, label, unit) in enumerate(FABRIC_FIELDS, start=1):
            prop: MaterialProperty | None = None if fabric is None else getattr(fabric, name)
            field = _SourceField(
                "" if prop is None else format_value(prop.value),
                "assumed" if prop is None else prop.source,
            )
            self.fields[name] = field
            grid.addWidget(QLabel(label), row, 0)
            grid.addWidget(field.value, row, 1)
            grid.addWidget(QLabel(unit), row, 2)
            grid.addWidget(field.tag, row, 3)
            grid.addWidget(field.note, row, 4)
        colour_row = len(FABRIC_FIELDS) + 1
        grid.addWidget(QLabel("Colour"), colour_row, 0)
        grid.addWidget(self.color.value, colour_row, 1)
        grid.addWidget(self.color.tag, colour_row, 3)
        grid.addWidget(self.color.note, colour_row, 4)
        head = QFormLayout()
        head.addRow("Id", self.fabric_id)
        head.addRow("Name", self.name)
        self.problems = QLabel()
        self.problems.setWordWrap(True)
        self.problems.setStyleSheet("color: #b00020")
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.try_accept)
        buttons.rejected.connect(self.reject)
        note = QLabel(
            "This fabric is saved in the fabric library shared by all your designs. "
            "Every value needs a source tag; use <i>assumed</i> for anything not taken "
            "from a datasheet or a measurement."
        )
        note.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addWidget(note)
        layout.addLayout(head)
        layout.addLayout(grid)
        layout.addWidget(self.problems)
        layout.addWidget(buttons)

    def _free_id(self, base: str) -> str:
        candidate, n = base, 2
        while candidate in self.taken_ids:
            candidate, n = f"{base}{n}", n + 1
        return candidate

    def fabric_and_problems(self) -> tuple[Fabric | None, list[str]]:
        """The fabric as entered and every problem with it."""
        problems: list[str] = []
        values: dict[str, MaterialProperty] = {}
        labels = {name: label for name, label, _ in FABRIC_FIELDS}
        for name, field in self.fields.items():
            # No comma-to-point conversion: "1,200" must not silently become 1.2.
            text = field.value.text().strip()
            try:
                number = float(text)
            except ValueError:
                problems.append(f"{labels[name]}: {text!r} is not a number")
                number = float("nan")
            values[name] = MaterialProperty(number, field.source())
        fabric_id = self.fabric_id.text().strip()
        if self.mode != "edit" and fabric_id in self.taken_ids:
            problems.append(f"id {fabric_id!r} is already in the library")
        colour = self.color.value.text().strip()
        if colour and not QColor(colour).isValid():
            problems.append(f"colour {colour!r} is not a colour name or #rrggbb")
        cost = values.pop("cost")
        fabric = Fabric(
            fabric_id=fabric_id,
            name=self.name.text().strip(),
            color=colour,
            color_source=self.color.source(),
            cost=cost,
            **values,
        )
        # Parse errors already name the field; skip validate_fabric's "not finite" repeat.
        parsed = {p.split(":")[0] for p in problems}
        problems += [
            p for p in validate_fabric(fabric) if p.split(":")[0].capitalize() not in parsed
        ]
        return (None if problems else fabric), problems

    def try_accept(self) -> None:
        """Close with the fabric if it is valid, else list the problems."""
        fabric, problems = self.fabric_and_problems()
        if fabric is None:
            self.problems.setText("Not saved:\n• " + "\n• ".join(problems))
            return
        self._result = fabric
        self.accept()

    def result_fabric(self) -> Fabric | None:
        """The accepted fabric (None if cancelled or not yet accepted)."""
        return self._result
