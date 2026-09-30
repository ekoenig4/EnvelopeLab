"""Properties panel: edit the fields of the selected design section.

Editors are generated from the design data: numbers get a line edit with exact numeric
entry (values in SI; the unit is shown beside the field, temperatures also in degC), text a
line edit, lists of text a comma-separated line edit. Every change is one undoable command
and is validated against the design schema before it is applied.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtGui import QDoubleValidator
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from envelopelab_app.controller import WorkspaceController

#: Unit shown next to a field (SI values; boundary display only).
UNITS = {
    "mouth_diameter": "m",
    "crown_ring": "m (diameter)",
    "parachute_hole_diameter": "m",
    "seal_overlap": "m",
    "width": "m",
    "strength": "N",
    "allowance": "m",
    "efficiency": "-",
    "ambient_temperature": "K",
    "internal_temperature": "K",
    "ambient_pressure": "Pa",
    "altitude": "m",
    "payload_mass": "kg",
    "finished_height": "m",
    "factor_k": "-",
    "billow": "- (rise / hole diameter)",
    "shroud_attachment": "m",
    "centralizing_depth": "m",
    "spare_length": "m",
    "frame_radius": "m",
    "frame_drop": "m",
    "frame_azimuth_deg": "deg",
    "crows_foot_drop": "m",
    "opening_width": "m",
}
#: Unit of a tagged ``value`` field, by the name of the field that holds it.
VALUE_UNITS = {
    "strength": "N",
    "linear_mass": "kg/m",
    "load_factor": "-",
    "required_safety_factor": "-",
    "discharge_coefficient": "-",
}

EDITABLE_SECTIONS = (
    "meta",
    "gores",
    "tapes",
    "seam_types",
    "operating",
    "parachute",
    "rigging",
    "turning_vents",
    "special",
    "zones",
)
READ_ONLY = {
    "content_hash",
    "created",
    "modified",
    "version_id",
    "parent_id",
    "meridian_profile_control_points",
    "panel_rows",
    "count",
}


class PropertiesPanel(QWidget):
    """See module docstring."""

    def __init__(self, controller: WorkspaceController) -> None:
        super().__init__()
        self.controller = controller
        self.section = "operating"
        self.title = QLabel()
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.form_layout = QVBoxLayout()
        layout = QVBoxLayout(self)
        layout.addWidget(self.title)
        layout.addWidget(self.scroll_area)
        self.editors: dict[tuple[str | int, ...], QLineEdit] = {}
        controller.selectionChanged.connect(self._selection)
        controller.stateChanged.connect(self.refresh)
        controller.sessionChanged.connect(self.refresh)
        self.refresh()

    def _selection(self, target: str) -> None:
        section = target.split(":")[0]
        if section in ("profile", "rows") or section.startswith("row"):
            section = "gores"
        if section in EDITABLE_SECTIONS:
            self.section = section
            self.refresh()

    def refresh(self) -> None:
        """Rebuild the form for the selected section."""
        # A fresh body widget each time; the scroll area deletes the previous one.
        body = QWidget()
        self.form_layout = QVBoxLayout(body)
        self.scroll_area.setWidget(body)
        self.editors = {}
        session = self.controller.session
        if session is None:
            self.title.setText("No project open")
            return
        data = session.design.model_dump(by_alias=True, mode="json").get(self.section)
        self.title.setText(f"<b>{self.section.replace('_', ' ').title()}</b>")
        if data is None or data == []:
            text = (
                "(not defined — add it in the Rigging panel)"
                if self.section in ("parachute", "turning_vents")
                else "(not used by this design)"
            )
            self.form_layout.addWidget(QLabel(text))
            return
        self._build(data, (self.section,), self.form_layout)
        self.form_layout.addStretch(1)

    def _build(self, data: Any, path: tuple[str | int, ...], layout: QVBoxLayout) -> None:
        box = QGroupBox(" / ".join(str(p) for p in path[1:]) or None)
        form = QFormLayout(box)
        items = data.items() if isinstance(data, dict) else enumerate(data)
        nested: list[tuple[Any, tuple[str | int, ...]]] = []
        for key, value in items:
            sub = (*path, key)
            if isinstance(value, dict) or (
                isinstance(value, list) and value and isinstance(value[0], dict)
            ):
                nested.append((value, sub))
                continue
            name = str(key)
            editor = QLineEdit(self._text(value))
            editor.setMinimumWidth(120)
            editor.setObjectName("prop_" + "_".join(str(p) for p in sub))
            read_only = name in READ_ONLY
            editor.setReadOnly(read_only)
            if isinstance(value, float):
                editor.setValidator(QDoubleValidator())
            editor.editingFinished.connect(
                lambda sub=sub, v=value, e=editor: self._edited(sub, v, e)
            )
            unit = UNITS.get(name, "")
            if name == "value" and len(sub) >= 2:
                unit = VALUE_UNITS.get(str(sub[-2]), "")
            if name.endswith("temperature") and isinstance(value, (int, float)):
                unit = f"K ({float(value) - 273.15:.1f} °C)"
            label = f"{name.replace('_', ' ')}" + (f" [{unit}]" if unit else "")
            form.addRow(label, editor)
            self.editors[sub] = editor
        layout.addWidget(box)
        for value, sub in nested:
            self._build(value, sub, layout)

    @staticmethod
    def _text(value: Any) -> str:
        if isinstance(value, list):
            return ", ".join(str(v) for v in value)
        if value is None:
            return ""
        if isinstance(value, float):
            return repr(value)
        return str(value)

    def _edited(self, path: tuple[str | int, ...], old: Any, editor: QLineEdit) -> None:
        if editor.isReadOnly():
            return
        text = editor.text().strip()
        try:
            value: Any
            if isinstance(old, bool):
                value = text.lower() in ("1", "true", "yes")
            elif isinstance(old, int):
                value = int(text)
            elif isinstance(old, float):
                value = float(text.replace(",", "."))
            elif isinstance(old, list):
                value = [t.strip() for t in text.split(",") if t.strip()]
            elif old is None:
                value = text or None
            else:
                value = text
        except ValueError:
            self.controller.editRejected.emit(f"{path[-1]}: not a valid value: {text!r}")
            self.refresh()
            return
        if value == old:
            return
        if self.controller.set_value(path, value) is None:
            self.refresh()

    def set_field(self, path: tuple[str | int, ...], text: str) -> None:
        """Type ``text`` into the editor of ``path`` and finish editing (tests, scripts)."""
        editor = self.editors[path]
        editor.setText(text)
        editor.editingFinished.emit()
