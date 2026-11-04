"""Rigging panel: add or remove the parachute, red line, flying wires, turning vents and
scoop, and read their lengths, limit loads and factors of safety.

The panel follows the shared look (:mod:`envelopelab_app.theme`):

* a toolbar with the key figures (rigging mass, lowest factor of safety against the
  requirement, limit load factor), always in view;
* a status banner stating the worst problem first: a factor of safety below the
  requirement (named, with its value), then rigging that is not complete, else that
  every assessed line passes, with what is *not* assessed;
* one card per component, each with its own status chip, its *Add* / *Remove* button,
  its key values and a table of its lines (count, length, limit load, strength with its
  source tag, factor of safety, mass). A failing factor of safety is marked with a
  symbol and the word "FAILS", never by colour alone; a value that is not assessed
  says so.

The parachute's overlap with the envelope and its centre panel are set in its card; the
other placements are edited in the Properties panel (select Parachute, Rigging or Turning
vents in the Design Tree). Every value shown is computed by
:func:`envelopelab.rigging.rigging_outputs`; this panel only lays it out.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QDoubleValidator, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from envelopelab.rigging import (
    LineResult,
    RiggingOutputs,
    default_flying_wires,
    default_parachute,
    default_red_line,
    default_scoop,
    turning_vent_pair,
)
from envelopelab_app.controller import WorkspaceController
from envelopelab_app.refresh import Refresher
from envelopelab_app.theme import STATUS_STYLES, StatusBanner, StatusChip, worst

#: Text colour of a failing value (the fail status's text colour: 4.5:1 on white).
FAIL_COLOR = STATUS_STYLES["fail"].chip_text
#: Columns of a card's lines table.
LINE_COLUMNS = (
    "Line",
    "Count",
    "Length",
    "Limit load",
    "Strength",
    "Factor of safety",
    "Mass",
)
FOS_COLUMN = LINE_COLUMNS.index("Factor of safety")
RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter

#: Cards in display order: key, title, add button text, what is missing without it.
COMPONENTS = (
    (
        "parachute",
        "Parachute",
        "Add parachute",
        "No parachute: the crown opening is not closed.",
    ),
    (
        "flying_wires",
        "Flying wires",
        "Add flying wires",
        "No flying wires: the basket is not attached to the load tapes.",
    ),
    (
        "red_line",
        "Red line",
        "Add red line",
        "No red line: the parachute cannot be opened in flight.",
    ),
    (
        "turning_vents",
        "Turning vents",
        "Add turning-vent pair",
        "No turning vents (optional): the balloon cannot be rotated in flight.",
    ),
    ("scoop", "Scoop", "Add scoop", "No scoop (optional)."),
)
#: Components a flight needs (the others are optional).
REQUIRED = ("parachute", "flying_wires", "red_line")
#: Button keys of each card (kept from the earlier panel for scripting and tests).
BUTTON_KEYS = {
    "parachute": ("add_parachute", "remove_parachute"),
    "flying_wires": ("add_flying_wires", "remove_flying_wires"),
    "red_line": ("add_red_line", "remove_red_line"),
    "turning_vents": ("add_vents", "remove_vents"),
    "scoop": ("add_scoop", "remove_scoop"),
}
REMOVE_TEXT = {
    "parachute": "Remove",
    "flying_wires": "Remove",
    "red_line": "Remove",
    "turning_vents": "Remove all",
    "scoop": "Remove",
}


def _fos_text(line: LineResult) -> str:
    fos = line.safety_factor
    if fos is None:
        return "not assessed"
    if line.passes:
        return f"{fos:.2f}"
    symbol = STATUS_STYLES["fail"].symbol
    return f"{symbol} {fos:.2f} FAILS (required {line.required_safety_factor:g})"


def _travel(value: float | None) -> tuple[str, bool]:
    if value is None:
        return f"{STATUS_STYLES['fail'].symbol} NOT REACHABLE", True
    return f"{value:.3f} m", False


def _wires_text(count: int, group: int) -> str:
    return f"{count} wires, {group} tape{'' if group == 1 else 's'} each"


@dataclass(frozen=True)
class Fact:
    """One labelled value of a card (``fail`` marks a value that fails a check)."""

    name: str
    value: str
    fail: bool = False


def assessed_lines(out: RiggingOutputs) -> list[LineResult]:
    """Every line and ring of ``out`` (assessed or not), in card order."""
    lines: list[LineResult] = []
    if out.parachute is not None:
        lines += [out.parachute.shroud, out.parachute.centralizing]
        lines += list(out.parachute.rings.values())
    if out.flying_wires is not None:
        lines += [out.flying_wires.wires, out.flying_wires.legs]
    if out.red_line is not None:
        lines.append(out.red_line.line)
    lines += [v.control_line for v in out.turning_vents]
    return lines


@dataclass(frozen=True)
class RiggingBanner:
    """What the banner states: a theme status kind, a title and a message."""

    kind: str
    title: str
    message: str


def rigging_banner(
    out: RiggingOutputs | None,
    missing: Sequence[str],
    required_fos: float,
    source: str,
    error: str | None = None,
) -> RiggingBanner:
    """The worst state of the rigging, for the banner.

    Parameters
    ----------
    out : RiggingOutputs or None
        The rigging outputs (None when they could not be computed).
    missing : sequence of str
        Titles of required components not yet added.
    required_fos : float
        Required factor of safety (dimensionless), with ``source`` its source tag.
    error : str, optional
        Why the outputs could not be computed.
    """
    if out is None:
        return RiggingBanner(
            "error", "Rigging not evaluated.", error or "The rigging outputs are not available."
        )
    errors = [f.message for f in out.findings if f.severity == "error"]
    if errors:
        more = f" (and {len(errors) - 2} more in Validation)" if len(errors) > 2 else ""
        return RiggingBanner("fail", "Rigging fails a check.", "; ".join(errors[:2]) + more)
    if missing:
        return RiggingBanner(
            "info",
            "Rigging not complete.",
            "Not yet added: " + ", ".join(m.lower() for m in missing) + ".",
        )
    lines = assessed_lines(out)
    unassessed = [line.name for line in lines if line.safety_factor is None]
    unassessed += ["red-line pull force"] if out.red_line is not None else []
    unassessed += ["scoop wind load"] if out.scoop is not None else []
    note = f" Not assessed: {', '.join(unassessed)}." if unassessed else ""
    return RiggingBanner(
        "ok",
        "Rigging checked.",
        f"Every assessed line meets the required factor of safety {required_fos:g} "
        f"({source}).{note}",
    )


class FactList(QWidget):
    """Labelled values in two columns, rebuilt on every refresh."""

    def __init__(self) -> None:
        super().__init__()
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(12)
        self.grid.setVerticalSpacing(2)
        self.grid.setColumnStretch(1, 1)
        self.facts: list[Fact] = []

    def set_facts(self, facts: Sequence[Fact]) -> None:
        """Show ``facts`` (replacing what was shown)."""
        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                # Off screen at once: deleteLater alone leaves it drawn until the event loop
                # runs, under the new values.
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        self.facts = list(facts)
        for row, fact in enumerate(self.facts):
            name = QLabel(fact.name)
            name.setProperty("role", "muted")
            value = QLabel(fact.value)
            value.setWordWrap(True)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            if fact.fail:
                value.setStyleSheet(f"color: {FAIL_COLOR}; font-weight: 600;")
            self.grid.addWidget(name, row, 0, Qt.AlignmentFlag.AlignTop)
            self.grid.addWidget(value, row, 1)
        self.setVisible(bool(self.facts))


class LineTable(QTableWidget):
    """The lines of one component: one row per kind of line, sized to its rows."""

    def __init__(self) -> None:
        super().__init__(0, len(LINE_COLUMNS))
        self.setHorizontalHeaderLabels(list(LINE_COLUMNS))
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setAlternatingRowColors(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        header = self.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)

    def set_lines(self, rows: Sequence[tuple[LineResult, bool]]) -> None:
        """Show ``rows``: each line with whether it is a ring (length is a diameter)."""
        self.setRowCount(len(rows))
        for r, (line, ring) in enumerate(rows):
            length = f"Ø {line.length / math.pi:.3f} m" if ring else f"{line.length:.3f} m"
            if line.tension is None:
                load = "not assessed"
            else:
                load = f"{line.tension:.0f} N" + (" hoop" if ring else "")
            cells = (
                line.name,
                f"×{line.count}",
                length,
                load,
                f"{line.strength.value:.0f} N ({line.strength.source})",
                _fos_text(line),
                f"{line.mass:.3f} kg",
            )
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if c > 0:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                if c == FOS_COLUMN and not line.passes:
                    item.setForeground(QBrush(QColor(FAIL_COLOR)))
                    font = QFont(item.font())
                    font.setBold(True)
                    item.setFont(font)
                    item.setToolTip(
                        f"{line.name}: factor of safety {line.safety_factor:.2f} is below the "
                        f"required {line.required_safety_factor:g}"
                    )
                elif c == FOS_COLUMN and line.safety_factor is None:
                    item.setForeground(QBrush(QColor(STATUS_STYLES["stale"].chip_text)))
                self.setItem(r, c, item)
        self.resizeRowsToContents()
        height = self.horizontalHeader().height() + sum(
            self.rowHeight(r) for r in range(self.rowCount())
        )
        self.setFixedHeight(height + 2 * self.frameWidth() + 2)
        self.setVisible(bool(rows))

    def fos_texts(self) -> list[str]:
        """The factor-of-safety cell of every row."""
        out = []
        for r in range(self.rowCount()):
            item = self.item(r, FOS_COLUMN)
            out.append("" if item is None else item.text())
        return out


class ComponentCard(QFrame):
    """One rigging component: title, status chip, Add/Remove, values and lines."""

    def __init__(
        self,
        key: str,
        title: str,
        add_text: str,
        empty_text: str,
        remove_text: str,
        wide: bool = False,
    ) -> None:
        super().__init__()
        self.key = key
        self.setObjectName("card")
        self.setProperty("component", key)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)
        header = QHBoxLayout()
        self.title = QLabel(title)
        self.title.setObjectName("cardTitle")
        self.chip = StatusChip()
        self.add_button = QPushButton(add_text)
        self.remove_button = QPushButton(remove_text)
        self.remove_button.setToolTip(f"Remove the {title.lower()} (undoable)")
        header.addWidget(self.title)
        header.addWidget(self.chip)
        header.addStretch(1)
        header.addWidget(self.add_button)
        header.addWidget(self.remove_button)
        layout.addLayout(header)
        self.empty = QLabel(empty_text)
        self.empty.setProperty("role", "muted")
        self.empty.setWordWrap(True)
        layout.addWidget(self.empty)
        # A wide card puts its values beside its lines table, a narrow one above it.
        body = QHBoxLayout() if wide else QVBoxLayout()
        body.setSpacing(16)
        left = QVBoxLayout()
        self.settings_slot = QVBoxLayout()
        left.addLayout(self.settings_slot)
        self.facts = FactList()
        left.addWidget(self.facts)
        left.addStretch(1)
        body.addLayout(left, 1)
        self.lines = LineTable()
        body.addWidget(self.lines, 1, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(body)
        layout.addStretch(1)

    def show_absent(self, enabled: bool) -> None:
        """No such component in the design: the empty text and the Add button."""
        self.chip.set_status("ok", "")
        self.empty.setVisible(True)
        self.facts.set_facts([])
        self.lines.set_lines([])
        self.add_button.setVisible(True)
        self.add_button.setEnabled(enabled)
        self.remove_button.setVisible(False)
        self.remove_button.setEnabled(False)

    def show_present(
        self,
        facts: Sequence[Fact],
        lines: Sequence[tuple[LineResult, bool]],
        can_add: bool = False,
    ) -> None:
        """The component's values and lines; the chip states its worst check."""
        self.empty.setVisible(False)
        self.facts.set_facts(facts)
        self.lines.set_lines(lines)
        self.add_button.setVisible(can_add)
        self.add_button.setEnabled(can_add)
        self.remove_button.setVisible(True)
        self.remove_button.setEnabled(True)
        failing = [line for line, _ring in lines if not line.passes]
        failing_facts = [f for f in facts if f.fail]
        if failing:
            names = ", ".join(line.name for line in failing)
            self.chip.set_status("fail", "Fails")
            self.chip.setToolTip(f"Factor of safety below the requirement: {names}")
        elif failing_facts:
            self.chip.set_status("fail", "Fails")
            self.chip.setToolTip("; ".join(f"{f.name}: {f.value}" for f in failing_facts))
        elif any(line.safety_factor is not None for line, _ring in lines):
            self.chip.set_status("ok", "Meets FoS")
            self.chip.setToolTip("Every assessed line meets the required factor of safety")
        else:
            self.chip.set_status("info", "Not assessed")
            self.chip.setToolTip("No load is assessed for this component")


class RiggingPanel(QWidget):
    """See module docstring."""

    def __init__(self, controller: WorkspaceController) -> None:
        super().__init__()
        self.controller = controller
        self._updating = False
        self.buttons: dict[str, QPushButton] = {}
        self.cards: dict[str, ComponentCard] = {}
        actions: dict[str, tuple[Callable[[], None], Callable[[], None]]] = {
            "parachute": (self.add_parachute, self.remove_parachute),
            "flying_wires": (self.add_flying_wires, self.remove_flying_wires),
            "red_line": (self.add_red_line, self.remove_red_line),
            "turning_vents": (self.add_turning_vents, self.remove_turning_vents),
            "scoop": (self.add_scoop, self.remove_scoop),
        }
        for key, title, add_text, empty_text in COMPONENTS:
            card = ComponentCard(
                key, title, add_text, empty_text, REMOVE_TEXT[key], wide=key == "parachute"
            )
            add_key, remove_key = BUTTON_KEYS[key]
            add, remove = actions[key]
            card.add_button.setObjectName(f"rigging_{add_key}")
            card.remove_button.setObjectName(f"rigging_{remove_key}")
            card.add_button.clicked.connect(add)
            card.remove_button.clicked.connect(remove)
            self.buttons[add_key] = card.add_button
            self.buttons[remove_key] = card.remove_button
            self.cards[key] = card
        # The parachute's own settings, in its card.
        self.settings: dict[str, QLineEdit] = {}
        self.parachute_box = QWidget()
        form = QFormLayout(self.parachute_box)
        form.setContentsMargins(0, 0, 0, 4)
        for key, text, tip in (
            (
                "overlap",
                "Overlap with the envelope (m)",
                "How far the parachute reaches past the top hole onto the envelope, measured "
                "along the fabric; internal pressure presses this band against the envelope "
                "to seal it.",
            ),
            (
                "centre_panel",
                "Centre panel diameter (m)",
                "A flat circular panel at the centre: the radial panels end at this circle "
                "(trapezoids). Empty or 0: no centre panel, the radial panels are wedges.",
            ),
        ):
            edit = QLineEdit()
            edit.setObjectName(f"parachute_{key}")
            edit.setValidator(QDoubleValidator(0.0, 1e3, 4))
            edit.setToolTip(tip)
            edit.setMaximumWidth(140)
            edit.editingFinished.connect(lambda k=key: self._settings_edited(k))
            self.settings[key] = edit
            form.addRow(text, edit)
        self.cards["parachute"].settings_slot.addWidget(self.parachute_box)
        # Toolbar: key figures, always in view.
        top = QWidget()
        top.setObjectName("panelToolbar")
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(8, 4, 8, 4)
        self.figures: dict[str, QLabel] = {}
        for key, tip in (
            ("mass", "Mass of every rigging item (lines, rings, parachute, scoop)"),
            ("fos", "Lowest factor of safety of the assessed lines, against the requirement"),
            ("load_factor", "Limit load factor applied to the static loads"),
        ):
            label = QLabel("-")
            label.setObjectName(f"figure_{key}")
            label.setProperty("role", "figure")
            label.setToolTip(tip)
            self.figures[key] = label
            top_layout.addWidget(label)
        top_layout.addStretch(1)
        self.fos_chip = StatusChip()
        top_layout.addWidget(self.fos_chip)
        self.banner = StatusBanner()
        # Cards: the parachute across the top, the others two by two.
        body = QWidget()
        grid = QGridLayout(body)
        grid.setContentsMargins(8, 8, 8, 8)
        grid.setSpacing(8)
        grid.addWidget(self.cards["parachute"], 0, 0, 1, 2)
        grid.addWidget(self.cards["flying_wires"], 1, 0)
        grid.addWidget(self.cards["red_line"], 1, 1)
        grid.addWidget(self.cards["turning_vents"], 2, 0)
        grid.addWidget(self.cards["scoop"], 2, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(3, 1)
        scroll = QScrollArea()
        scroll.setObjectName("sidePanel")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body.setObjectName("sidePanel")
        scroll.setWidget(body)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(top)
        layout.addWidget(self.banner)
        layout.addWidget(scroll, 1)
        self._summaries: dict[str, str] = {}
        self.refresher = Refresher(
            self,
            self.refresh,
            lambda: controller.revision,
            (controller.stateChanged, controller.sessionChanged),
            defer_hidden=lambda: controller.defer_hidden,
        )
        self.refresh()

    # -- edits --------------------------------------------------------------------------

    def _set(self, path: tuple[str, ...], value: Any, description: str) -> None:
        if self.controller.session is None:
            return
        self.controller.attempt(self.controller.session.set_design_value, path, value, description)

    def _overlap(self) -> float:
        design = self.controller.design
        return 0.0 if design is None or design.gores is None else design.gores.seal_overlap

    def set_seal_overlap(self, value: float) -> None:
        """Set how far the parachute overlaps the envelope round the top hole (m, along the
        fabric)."""
        self._set(("gores", "seal_overlap"), float(value), f"Parachute overlap {value:g} m")

    def set_centre_panel(self, diameter: float | None) -> None:
        """Give the parachute a flat centre panel of ``diameter`` (m), or none."""
        text = "none" if diameter is None else f"{diameter:g} m"
        self._set(
            ("parachute", "centre_panel_diameter"),
            None if diameter is None else float(diameter),
            f"Parachute centre panel {text}",
        )

    def _settings_edited(self, key: str) -> None:
        if self._updating:
            return
        text = self.settings[key].text().strip()
        if key == "centre_panel" and text in ("", "0"):
            self.set_centre_panel(None)
        else:
            try:
                value = float(text)
            except ValueError:
                self.refresh()
                return
            if key == "overlap":
                self.set_seal_overlap(value)
            else:
                self.set_centre_panel(value)
        self.refresh()

    def _dump(self, spec: Any) -> Any:
        return spec.model_dump(by_alias=True, mode="json")

    def add_parachute(self) -> None:
        """Add the default parachute (one shroud line per load tape)."""
        design = self.controller.design
        if design is not None and design.gores is not None:
            self._set(("parachute",), self._dump(default_parachute(design)), "Add parachute")

    def remove_parachute(self) -> None:
        """Remove the parachute."""
        self._set(("parachute",), None, "Remove parachute")

    def add_red_line(self) -> None:
        """Add the default red line (led down seam 1)."""
        design = self.controller.design
        if design is not None and design.gores is not None:
            self._set(("rigging", "red_line"), self._dump(default_red_line(design)), "Add red line")

    def remove_red_line(self) -> None:
        """Remove the red line."""
        self._set(("rigging", "red_line"), None, "Remove red line")

    def add_flying_wires(self) -> None:
        """Add the default flying wires to a four-point burner frame."""
        design = self.controller.design
        if design is not None and design.gores is not None:
            self._set(
                ("rigging", "flying_wires"),
                self._dump(default_flying_wires(design)),
                "Add flying wires",
            )

    def remove_flying_wires(self) -> None:
        """Remove the flying wires."""
        self._set(("rigging", "flying_wires"), None, "Remove flying wires")

    def add_turning_vents(self) -> None:
        """Add two opposite turning vents (both turning counter-clockwise)."""
        design = self.controller.design
        if design is None or design.gores is None:
            return
        taken = {v.name for v in design.turning_vents}
        vents = [self._dump(v) for v in design.turning_vents]
        for vent in turning_vent_pair(design):
            name, k = vent.name, len(vents) + 1
            while name in taken:
                name, k = f"turning vent {k}", k + 1
            taken.add(name)
            vents.append({**self._dump(vent), "name": name})
        self._set(("turning_vents",), vents, "Add turning-vent pair")

    def remove_turning_vents(self) -> None:
        """Remove every turning vent."""
        self._set(("turning_vents",), [], "Remove turning vents")

    def add_scoop(self) -> None:
        """Add the default half scoop in the mouth row's fabric."""
        design = self.controller.design
        if design is not None and design.gores is not None:
            self._set(("scoop",), self._dump(default_scoop(design)), "Add scoop")

    def remove_scoop(self) -> None:
        """Remove the scoop."""
        self._set(("scoop",), None, "Remove scoop")

    # -- display ------------------------------------------------------------------------

    def _present(self) -> dict[str, bool]:
        design = self.controller.design
        if design is None or design.gores is None:
            return {key: False for key, *_ in COMPONENTS}
        return {
            "parachute": design.parachute is not None,
            "flying_wires": design.rigging.flying_wires is not None,
            "red_line": design.rigging.red_line is not None,
            "turning_vents": bool(design.turning_vents),
            "scoop": design.scoop is not None,
        }

    def refresh(self) -> None:
        """Show the current rigging outputs."""
        self._summaries = {}
        design = self.controller.design
        gore = design is not None and design.gores is not None
        present = self._present()
        for card in self.cards.values():
            card.show_absent(gore)
        for label in self.figures.values():
            label.setText("-")
        self.fos_chip.set_status("ok", "")
        self.parachute_box.setVisible(False)
        if design is None:
            self.banner.set_status("info", "No project open.")
            return
        if not gore:
            self.banner.set_status(
                "info",
                "Rigging is not available for this design.",
                "Parachute and rigging analysis is available for standard-gore designs only.",
            )
            return
        self._updating = True
        try:
            self.parachute_box.setEnabled(design.parachute is not None)
            self.settings["overlap"].setText(f"{self._overlap():g}")
            centre = design.parachute.centre_panel_diameter if design.parachute else None
            self.settings["centre_panel"].setText("" if centre is None else f"{centre:g}")
        finally:
            self._updating = False
        rig = design.rigging
        self.figures["load_factor"].setText(
            f"Limit load factor {rig.load_factor.value:g} ({rig.load_factor.source})"
        )
        missing = [title for key, title, *_ in COMPONENTS if key in REQUIRED and not present[key]]
        out = self.controller.rigging
        banner = rigging_banner(
            out,
            missing,
            rig.required_safety_factor.value,
            rig.required_safety_factor.source,
            self.controller.outputs_error,
        )
        self.banner.set_status(banner.kind, banner.title, banner.message)
        if out is None:
            return
        self._show(out, present)
        self.figures["mass"].setText(f"Rigging {out.total_mass:.2f} kg")
        required = rig.required_safety_factor.value
        factors = [f for line in assessed_lines(out) if (f := line.safety_factor) is not None]
        if not factors:
            self.figures["fos"].setText(f"Lowest FoS: none assessed (required {required:g})")
            self.fos_chip.set_status("ok", "")
        else:
            low = min(factors)
            self.figures["fos"].setText(f"Lowest FoS {low:.2f} (required {required:g})")
            kinds = [card.chip.kind for card in self.cards.values() if card.chip.text()]
            if worst(kinds) == "fail":
                self.fos_chip.set_status("fail", "Below the required FoS")
            else:
                self.fos_chip.set_status("ok", "Meets the required FoS")

    def _show(self, out: RiggingOutputs, present: dict[str, bool]) -> None:
        pr = out.parachute
        if pr is not None and present["parachute"]:
            self.parachute_box.setVisible(True)
            g = pr.geometry
            facts = [
                Fact("Diameter", f"{g.diameter:.3f} m, {pr.panel_count} panels"),
                Fact("Hole diameter", f"{2 * g.hole_radius:.3f} m"),
                Fact("Seal overlap", f"{self._overlap():.3f} m along the fabric"),
                Fact("Fabric", f"{g.meridian_length:.3f} m edge to apex, {g.area:.2f} m²"),
            ]
            if pr.panel is not None:
                top = pr.panel.top_width
                shape = "trapezoid" if top > 1e-6 else "wedge"
                facts.append(
                    Fact(
                        f"Radial panel ×{pr.panel_count}",
                        f"{shape}, finished: {pr.panel.bottom_width:.3f} m wide at the edge, "
                        f"{top:.3f} m at the top, {pr.panel.side_length:.3f} m long",
                    )
                )
            centre = pr.centre_panel
            facts.append(
                Fact(
                    "Centre panel",
                    "none (the radial panels meet at the centre)"
                    if centre is None
                    else f"circle {centre.diameter:.3f} m diameter, edge "
                    f"{centre.seam_length:.3f} m (finished)",
                )
            )
            facts += [
                Fact("Crown pressure", f"{pr.crown_pressure:.1f} Pa"),
                Fact("Shroud-line load", f"{pr.force:.0f} N (static)"),
            ]
            seal, seal_fail = _travel(pr.opening.seal_open_travel)
            full, full_fail = _travel(pr.opening.full_open_travel)
            facts.append(
                Fact("Red-line pull", f"seal open {seal}, full open {full}", seal_fail or full_fail)
            )
            lines = [(pr.shroud, False), (pr.centralizing, False)]
            lines += [(ring, True) for ring in pr.rings.values()]
            self.cards["parachute"].show_present(facts, lines)
            self._summaries["Parachute"] = f"{g.diameter:.3f} m diameter"
        fw = out.flying_wires
        if fw is not None and present["flying_wires"]:
            lengths = ", ".join(f"{v:.3f}" for v in fw.geometry.wire_lengths)
            facts = [
                Fact("Wires", _wires_text(fw.wires.count, fw.geometry.group_size)),
                Fact("Suspended weight", f"{fw.suspended_weight:.0f} N"),
                Fact("Limit weight", f"{fw.limit_weight:.0f} N"),
                Fact("Wire lengths", f"{lengths} m"),
            ]
            self.cards["flying_wires"].show_present(facts, [(fw.wires, False), (fw.legs, False)])
            self._summaries["Flying wires"] = _wires_text(fw.wires.count, fw.geometry.group_size)
        rl = out.red_line
        if rl is not None and present["red_line"]:
            facts = [
                Fact("Length", f"{rl.line.length:.3f} m ({rl.route_length:.3f} m without spare)"),
                Fact("Confluence height", f"{rl.confluence[2]:.3f} m"),
                Fact(
                    "Basket anchor",
                    "unknown (no flying wires)" if rl.anchor is None else "burner frame",
                ),
                Fact("Pull force", "not assessed"),
            ]
            self.cards["red_line"].show_present(facts, [(rl.line, False)])
            self._summaries["Red line"] = f"{rl.line.length:.3f} m"
        if out.turning_vents and present["turning_vents"]:
            facts = []
            for v in out.turning_vents:
                way = "counter-clockwise" if v.counterclockwise else "clockwise"
                text = (
                    f"seam {v.seam}, {way}; slot {v.jet.slot_length:.3f} m, "
                    f"{v.jet.area:.3f} m² open; fully open: thrust {v.jet.thrust:.1f} N, "
                    f"torque {v.jet.torque:.0f} N m, air loss {v.jet.mass_flow:.2f} kg/s, "
                    f"heat loss {v.jet.heat_loss / 1000:.0f} kW"
                )
                facts.append(Fact(v.name, text))
                self._summaries[v.name] = f"seam {v.seam}, {way}"
            facts += [
                Fact("Net turning torque", f"{out.net_torque:.0f} N m (all fully open)"),
                Fact("Net side force", f"{out.net_side_force:.1f} N"),
            ]
            self._summaries["Net turning torque"] = f"{out.net_torque:.0f} N m"
            self._summaries["Net side force"] = f"{out.net_side_force:.1f} N"
            self.cards["turning_vents"].show_present(
                facts, [(v.control_line, False) for v in out.turning_vents], can_add=True
            )
        sc = out.scoop
        if sc is not None and present["scoop"]:
            last = sc.first_gore + sc.gore_count - 1
            facts = [
                Fact("Gores", f"{sc.first_gore}–{last}, {sc.zone}"),
                Fact("Slant length", f"{sc.slant_length:.3f} m"),
                Fact("Bottom radius", f"{sc.bottom_radius:.3f} m"),
                Fact(
                    "Panel (finished)",
                    f"{sc.panel.top_width:.3f} m at the mouth, {sc.panel.bottom_width:.3f} m "
                    "at the bottom",
                ),
                Fact("Mass", f"{sc.mass.total_mass:.2f} kg"),
                Fact("Wind load", "not assessed"),
            ]
            self.cards["scoop"].show_present(facts, [])
            self._summaries["Scoop"] = f"gores {sc.first_gore}-{last}"

    def texts(self) -> dict[str, str]:
        """Each shown component (and turning vent) with its one-line summary (tests and
        scripting)."""
        return dict(self._summaries)

    def fos_texts(self) -> list[str]:
        """The factor-of-safety cell of every line shown, in card order."""
        return [text for card in self.cards.values() for text in card.lines.fos_texts()]

    def line_row(self, name: str) -> dict[str, str] | None:
        """The table cells of the first line called ``name`` (column title to text)."""
        for card in self.cards.values():
            table = card.lines
            for r in range(table.rowCount()):
                first = table.item(r, 0)
                if first is not None and first.text() == name:
                    return {
                        column: (cell.text() if (cell := table.item(r, c)) else "")
                        for c, column in enumerate(LINE_COLUMNS)
                    }
        return None

    def card_status(self, key: str) -> str | None:
        """The status kind of a card's chip (None when the component is absent)."""
        card = self.cards[key]
        return card.chip.kind if card.chip.text() else None
