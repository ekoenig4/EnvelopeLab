"""Properties panel: edit the fields of the selected design section.

Editors are generated from the design schema (``envelopelab.project.field_editing``), not
from the current value, so an empty optional field still gets the right editor:

* numbers get a line edit with exact numeric entry (values in SI; the unit is shown beside
  the field, temperatures also in degC), text a line edit, lists and name-to-value maps a
  comma-separated line edit (``a, b`` or ``key=value, key=value``);
* yes/no fields get a check box and fields with fixed choices a combo box;
* an optional value has a *Clear* button, an optional section an *Add* or *Remove* button,
  and every list of sections *Add* and *Remove* buttons.

Fields that a dedicated editor owns (the gore profile and rows in the gore editor, the
material zones in the Materials panel) are shown read-only with the editor's name. Every
change is one undoable command and is validated against the design schema before it is
applied; a refused change is reported and nothing changes.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from PySide6.QtGui import QDoubleValidator, QIntValidator
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from envelopelab.project.field_editing import NEW_ENTRIES, FieldInfo, field_info, new_value
from envelopelab_app.controller import WorkspaceController
from envelopelab_app.refresh import Refresher

FieldPath = tuple[str | int, ...]

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
    "centre_ring_diameter": "m",
    "height": "m",
    "flare_deg": "deg",
    "fixed_size_overrides": "m",
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
    "features",
    "parachute",
    "rigging",
    "turning_vents",
    "scoop",
    "scale_variants",
    "special",
    "zones",
)
#: Fields edited elsewhere, by path pattern (``*`` matches a list index), with the editor
#: that owns them. A pattern also covers everything below it.
OWNED: dict[tuple[str, ...], str] = {
    ("meta", "version_id"): "set when the design is saved",
    ("meta", "parent_id"): "set when the design is saved",
    ("meta", "content_hash"): "set when the design is saved",
    ("meta", "created"): "set when the design is saved",
    ("meta", "modified"): "set when the design is saved",
    ("gores", "count"): "Gore editor",
    ("gores", "meridian_profile_control_points"): "Gore editor",
    ("gores", "panel_rows"): "Gore editor",
    ("gores", "loft"): "Gore editor",
    ("gores", "crest_loft"): "Gore editor",
    ("gores", "construction"): "Gore editor",
    ("gores", "profile_interpolation"): "Gore editor",
    ("zones",): "Materials panel",
}


def owner(path: Sequence[str | int]) -> str | None:
    """Editor that owns the field at ``path`` (None: edited in the Properties panel)."""
    keys = tuple("*" if isinstance(p, int) else p for p in path)
    for pattern, name in OWNED.items():
        if len(keys) >= len(pattern) and all(
            p in ("*", k) for p, k in zip(pattern, keys, strict=False)
        ):
            return name
    return None


def _label(path: FieldPath) -> str:
    return " / ".join(str(p) for p in path[1:])


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
        self.editors: dict[FieldPath, QWidget] = {}
        self.buttons: dict[tuple[str, FieldPath], QPushButton] = {}
        controller.selectionChanged.connect(self._selection)
        self.refresher = Refresher(
            self,
            self.refresh,
            lambda: controller.revision,
            (controller.stateChanged, controller.sessionChanged),
            defer_hidden=lambda: controller.defer_hidden,
        )
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
        self.buttons = {}
        session = self.controller.session
        if session is None:
            self.title.setText("No project open")
            return
        data = session.design.model_dump(by_alias=True, mode="json").get(self.section)
        self.title.setText(f"<b>{self.section.replace('_', ' ').title()}</b>")
        path: FieldPath = (self.section,)
        info = field_info(path)
        if data is None:
            if self.section == "gores" or self.section == "special":
                self.form_layout.addWidget(QLabel("(not used by this design)"))
            else:
                self.form_layout.addWidget(QLabel("(not defined)"))
                self._add_button(self.form_layout, path, f"Add {self._name(path)}")
            self.form_layout.addStretch(1)
            return
        if info.kind == "objects":
            self._build_list(data, path, self.form_layout)
        elif info.kind == "object":
            # The gore and special-shape sections say what kind of design it is.
            removable = info.optional and self.section not in ("gores", "special")
            self._build(data, path, self.form_layout, removable=removable)
        else:
            box = QGroupBox()
            form = QFormLayout(box)
            self._row(form, path, data, info)
            self.form_layout.addWidget(box)
        self.form_layout.addStretch(1)

    # -- building -----------------------------------------------------------------------

    @staticmethod
    def _name(path: FieldPath) -> str:
        return str(path[-1]).replace("_", " ")

    def _add_button(self, layout: QVBoxLayout | QFormLayout, path: FieldPath, text: str) -> None:
        if self._can_add(path):
            button = QPushButton(text)
            button.setObjectName("add_" + "_".join(map(str, path)))
            button.clicked.connect(lambda _=False, p=path: self.add_entry(p))
            self.buttons[("add", path)] = button
            layout.addWidget(button) if isinstance(layout, QVBoxLayout) else layout.addRow(button)

    def _can_add(self, path: FieldPath) -> bool:
        design = self.controller.design
        if design is None or owner(path) is not None:
            return False
        keys = tuple("*" if isinstance(p, int) else p for p in path)
        if keys in NEW_ENTRIES:
            return True
        if isinstance(path[-1], int):
            try:
                new_value(design, path)
            except (KeyError, ValueError):
                return False
            return True
        return False

    def _remove_button(self, form: QFormLayout, path: FieldPath, text: str) -> None:
        button = QPushButton(text)
        button.setObjectName("remove_" + "_".join(map(str, path)))
        button.clicked.connect(lambda _=False, p=path: self.remove_entry(p))
        self.buttons[("remove", path)] = button
        form.addRow(button)

    def _build_list(self, data: list[Any], path: FieldPath, layout: QVBoxLayout) -> None:
        owned = owner(path)
        if owned is not None:
            self._owned_note(layout, path, owned)
            return
        for i, entry in enumerate(data):
            self._build(entry, (*path, i), layout, removable=True)
        if not data:
            layout.addWidget(QLabel(f"(no {self._name(path)})"))
        self._add_button(layout, (*path, len(data)), f"Add {self._name(path).rstrip('s')}")

    @staticmethod
    def _owned_note(layout: QVBoxLayout, path: FieldPath, owned: str) -> None:
        name = (_label(path) or str(path[0])).replace("_", " ")
        label = QLabel(f"{name}: edited in the {owned}")
        label.setObjectName("owned_" + "_".join(map(str, path)))
        label.setWordWrap(True)
        layout.addWidget(label)

    def _build(
        self, data: dict[str, Any], path: FieldPath, layout: QVBoxLayout, removable: bool
    ) -> None:
        owned = owner(path)
        if owned is not None and len(path) > 1:
            self._owned_note(layout, path, owned)
            return
        box = QGroupBox(_label(path) or None)
        form = QFormLayout(box)
        nested: list[tuple[Any, FieldPath, FieldInfo]] = []
        for key, value in data.items():
            sub = (*path, key)
            info = field_info(sub)
            if info.kind in ("object", "objects"):
                nested.append((value, sub, info))
                continue
            self._row(form, sub, value, info)
        if removable and owned is None:
            what = "entry" if isinstance(path[-1], int) else self._name(path)
            self._remove_button(form, path, f"Remove {what}")
        layout.addWidget(box)
        for value, sub, info in nested:
            sub_owner = owner(sub)
            if sub_owner is not None:
                self._owned_note(layout, sub, sub_owner)
            elif info.kind == "objects":
                self._build_list(value or [], sub, layout)
            elif value is None:
                note = QGroupBox(_label(sub))
                note_layout = QFormLayout(note)
                note_layout.addRow(QLabel("(none)"))
                self._add_button(note_layout, sub, f"Add {self._name(sub)}")
                layout.addWidget(note)
            else:
                self._build(value, sub, layout, removable=info.optional)

    def _row(self, form: QFormLayout, path: FieldPath, value: Any, info: FieldInfo) -> None:
        name = str(path[-1])
        owned = owner(path)
        editor: QWidget
        if info.kind == "bool":
            box = QCheckBox()
            box.setChecked(bool(value))
            box.toggled.connect(lambda on, p=path: self._commit(p, on))
            editor = box
        elif info.kind == "choice":
            combo = QComboBox()
            if info.optional:
                combo.addItem("(none)", None)
            for choice in info.choices:
                combo.addItem(choice, choice)
            combo.setCurrentIndex(max(0, combo.findData(value)))
            combo.activated.connect(lambda _i, p=path, c=combo: self._commit(p, c.currentData()))
            editor = combo
        else:
            line = QLineEdit(self._text(value, info))
            line.setMinimumWidth(120)
            if info.kind == "number":
                line.setValidator(QDoubleValidator())
            elif info.kind == "integer":
                line.setValidator(QIntValidator())
            line.editingFinished.connect(lambda p=path, e=line, i=info: self._edited(p, e, i))
            line.setReadOnly(owned is not None)
            editor = line
        editor.setObjectName("prop_" + "_".join(str(p) for p in path))
        if owned is not None:
            editor.setEnabled(False)
            editor.setToolTip(f"Edited in the {owned}")
        unit = UNITS.get(name, "")
        if name == "value" and len(path) >= 2:
            unit = VALUE_UNITS.get(str(path[-2]), "")
        if name.endswith("temperature") and isinstance(value, (int, float)):
            unit = f"K ({float(value) - 273.15:.1f} °C)"
        label = name.replace("_", " ") + (f" [{unit}]" if unit else "")
        if info.optional and value is not None and owned is None and info.kind != "choice":
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(editor, 1)
            clear = QPushButton("Clear")
            clear.setObjectName("clear_" + "_".join(str(p) for p in path))
            clear.setToolTip("Remove this value (none)")
            clear.clicked.connect(lambda _=False, p=path: self.clear_field(p))
            self.buttons[("clear", path)] = clear
            row_layout.addWidget(clear)
            form.addRow(label, row)
        else:
            form.addRow(label, editor)
        self.editors[path] = editor

    @staticmethod
    def _text(value: Any, info: FieldInfo) -> str:
        if value is None:
            return ""
        if info.kind == "mapping":
            return ", ".join(
                f"{k}={v!r}" if isinstance(v, float) else f"{k}={v}" for k, v in value.items()
            )
        if isinstance(value, list):
            return ", ".join(repr(v) if isinstance(v, float) else str(v) for v in value)
        if isinstance(value, float):
            return repr(value)
        return str(value)

    # -- parsing and committing --------------------------------------------------------

    @staticmethod
    def _scalar(text: str, kind: str) -> Any:
        text = text.strip()
        if kind == "number":
            return float(text.replace(",", "."))
        if kind == "integer":
            return int(text)
        if kind == "bool":
            return text.lower() in ("1", "true", "yes")
        return text

    def _parse(self, text: str, info: FieldInfo) -> Any:
        text = text.strip()
        if not text and info.optional:
            return None
        if info.kind == "scalars":
            # Numbers use "." here: "," separates the entries.
            return [self._scalar(t, info.item_kind) for t in text.split(",") if t.strip()]
        if info.kind == "mapping":
            out: dict[str, Any] = {}
            for part in (p for p in text.split(",") if p.strip()):
                key, sep, value = part.partition("=")
                if not sep or not key.strip():
                    raise ValueError(f"not key=value: {part.strip()!r}")
                out[key.strip()] = self._scalar(value, info.item_kind)
            return out
        return self._scalar(text, info.kind)

    def _edited(self, path: FieldPath, editor: QLineEdit, info: FieldInfo) -> None:
        if editor.isReadOnly():
            return
        try:
            value = self._parse(editor.text(), info)
        except ValueError:
            self.controller.editRejected.emit(f"{path[-1]}: not a valid value: {editor.text()!r}")
            self.refresh()
            return
        self._commit(path, value)

    def _commit(self, path: FieldPath, value: Any) -> None:
        session = self.controller.session
        if session is None:
            return
        if value == session.design_value(path):
            return
        if self.controller.set_value(path, value) is None:
            self.refresh()

    # -- actions (buttons, tests, scripts) ----------------------------------------------

    def set_field(self, path: FieldPath, text: str) -> None:
        """Type ``text`` into the editor of ``path`` and finish editing (tests, scripts).

        A check box takes ``true``/``false``, a combo box the choice's value.
        """
        editor = self.editors[path]
        if isinstance(editor, QCheckBox):
            editor.setChecked(text.strip().lower() in ("1", "true", "yes"))
        elif isinstance(editor, QComboBox):
            index = editor.findData(None if text == "" else text)
            if index < 0:
                raise ValueError(f"{text!r} is not a choice of {path}")
            editor.setCurrentIndex(index)
            editor.activated.emit(index)
        else:
            assert isinstance(editor, QLineEdit)
            editor.setText(text)
            editor.editingFinished.emit()

    def clear_field(self, path: FieldPath) -> None:
        """Set an optional field to none."""
        self._commit(path, None)

    def add_entry(self, path: FieldPath) -> None:
        """Add an optional section (``path`` names it) or a list entry (``path`` ends with
        the list's length)."""
        session = self.controller.session
        design = self.controller.design
        if session is None or design is None:
            return
        try:
            value = new_value(design, path)
        except (KeyError, ValueError) as exc:
            self.controller.editRejected.emit(str(exc))
            return
        if isinstance(path[-1], int):
            entries = list(session.design_value(path[:-1]) or [])
            self._commit(path[:-1], [*entries, value])
        else:
            self._commit(path, value)

    def remove_entry(self, path: FieldPath) -> None:
        """Remove an optional section (set it to none) or a list entry."""
        session = self.controller.session
        if session is None:
            return
        if isinstance(path[-1], int):
            entries = list(session.design_value(path[:-1]) or [])
            del entries[path[-1]]
            self._commit(path[:-1], entries)
        else:
            self._commit(path, None)
