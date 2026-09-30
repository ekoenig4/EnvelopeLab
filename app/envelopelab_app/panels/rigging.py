"""Rigging panel: add or remove the parachute, red line, flying wires and turning vents,
and read their lengths, limit loads and factors of safety.

Placements are edited in the Properties panel (select Parachute, Rigging or Turning vents
in the Design Tree); this panel shows what :func:`envelopelab.rigging.rigging_outputs`
computes from them. A factor of safety below the requirement is shown in red and listed
in the Validation panel; a value that is not assessed says so.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QGridLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from envelopelab.rigging import (
    LineResult,
    RiggingOutputs,
    default_flying_wires,
    default_parachute,
    default_red_line,
    turning_vent_pair,
)
from envelopelab_app.controller import WorkspaceController

FAIL_COLOR = "#b00020"


def _fos_text(line: LineResult) -> str:
    fos = line.safety_factor
    if fos is None:
        return "not assessed"
    mark = "" if line.passes else "  FAILS"
    return f"{fos:.1f} (required {line.required_safety_factor:.1f}){mark}"


def _travel(value: float | None) -> str:
    return "NOT REACHABLE" if value is None else f"{value:.3f} m"


class RiggingPanel(QWidget):
    """See module docstring."""

    def __init__(self, controller: WorkspaceController) -> None:
        super().__init__()
        self.controller = controller
        self.buttons: dict[str, QPushButton] = {}
        grid = QGridLayout()
        for i, (key, text, action) in enumerate(
            (
                ("add_parachute", "Add parachute", self.add_parachute),
                ("remove_parachute", "Remove parachute", self.remove_parachute),
                ("add_red_line", "Add red line", self.add_red_line),
                ("remove_red_line", "Remove red line", self.remove_red_line),
                ("add_flying_wires", "Add flying wires", self.add_flying_wires),
                ("remove_flying_wires", "Remove flying wires", self.remove_flying_wires),
                ("add_vents", "Add turning-vent pair", self.add_turning_vents),
                ("remove_vents", "Remove turning vents", self.remove_turning_vents),
            )
        ):
            button = QPushButton(text)
            button.setObjectName(f"rigging_{key}")
            button.clicked.connect(action)
            self.buttons[key] = button
            grid.addWidget(button, i // 2, i % 2)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Item", "Value"])
        layout = QVBoxLayout(self)
        layout.addLayout(grid)
        layout.addWidget(self.summary)
        layout.addWidget(self.tree)
        controller.stateChanged.connect(self.refresh)
        controller.sessionChanged.connect(self.refresh)
        self.refresh()

    # -- edits --------------------------------------------------------------------------

    def _set(self, path: tuple[str, ...], value: Any, description: str) -> None:
        if self.controller.session is None:
            return
        self.controller.attempt(self.controller.session.set_design_value, path, value, description)

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

    # -- display ------------------------------------------------------------------------

    def _row(
        self, parent: QTreeWidget | QTreeWidgetItem, name: str, value: str, fail: bool = False
    ) -> QTreeWidgetItem:
        item = QTreeWidgetItem([name, value])
        if fail:
            for col in (0, 1):
                item.setForeground(col, QBrush(QColor(FAIL_COLOR)))
        if isinstance(parent, QTreeWidget):
            parent.addTopLevelItem(item)
        else:
            parent.addChild(item)
        return item

    def _line(self, parent: QTreeWidgetItem, line: LineResult) -> None:
        node = self._row(
            parent, f"{line.name} x{line.count}", f"{line.length:.3f} m", not line.passes
        )
        if line.tension is not None:
            self._row(node, "limit tension", f"{line.tension:.0f} N")
        self._row(node, "strength", f"{line.strength.value:.0f} N ({line.strength.source})")
        self._row(node, "factor of safety", _fos_text(line), not line.passes)
        self._row(node, "mass", f"{line.mass:.3f} kg")

    def refresh(self) -> None:
        """Show the current rigging outputs."""
        self.tree.clear()
        design = self.controller.design
        gore = design is not None and design.gores is not None
        for button in self.buttons.values():
            button.setEnabled(gore)
        if design is None:
            self.summary.setText("No project open")
            return
        if not gore:
            self.summary.setText(
                "Parachute and rigging analysis is available for standard-gore designs only."
            )
            return
        self.buttons["add_parachute"].setEnabled(design.parachute is None)
        self.buttons["remove_parachute"].setEnabled(design.parachute is not None)
        self.buttons["add_red_line"].setEnabled(design.rigging.red_line is None)
        self.buttons["remove_red_line"].setEnabled(design.rigging.red_line is not None)
        self.buttons["add_flying_wires"].setEnabled(design.rigging.flying_wires is None)
        self.buttons["remove_flying_wires"].setEnabled(design.rigging.flying_wires is not None)
        self.buttons["remove_vents"].setEnabled(bool(design.turning_vents))
        out = self.controller.rigging
        if out is None:
            self.summary.setText(self.controller.outputs_error or "Rigging not evaluated.")
            return
        self._show(out)

    def _show(self, out: RiggingOutputs) -> None:
        errors = [f for f in out.findings if f.severity == "error"]
        rig = self.controller.design.rigging  # type: ignore[union-attr]
        self.summary.setText(
            f"Load case: limit load factor {rig.load_factor.value:g} ({rig.load_factor.source}), "
            f"required factor of safety {rig.required_safety_factor.value:g} "
            f"({rig.required_safety_factor.source}). Rigging mass {out.total_mass:.2f} kg. "
            + (f"<b>{len(errors)} error(s)</b> — see Validation." if errors else "")
        )
        self.summary.setStyleSheet(f"color: {FAIL_COLOR};" if errors else "")
        pr = out.parachute
        if pr is not None:
            g = pr.geometry
            node = self._row(self.tree, "Parachute", f"{g.diameter:.3f} m diameter")
            self._row(node, "panels", f"{pr.panel_count}")
            self._row(node, "hole diameter", f"{2 * g.hole_radius:.3f} m")
            self._row(node, "fabric length edge to apex", f"{g.meridian_length:.3f} m")
            self._row(node, "fabric area", f"{g.area:.2f} m²")
            if pr.panel is not None:
                self._row(
                    node,
                    "panel (cut)",
                    f"{pr.panel.bottom_width:.3f} m wide at the edge, "
                    f"{pr.panel.side_length:.3f} m long",
                )
            self._row(node, "crown pressure", f"{pr.crown_pressure:.1f} Pa")
            self._row(node, "shroud-line load (static)", f"{pr.force:.0f} N")
            self._line(node, pr.shroud)
            self._line(node, pr.centralizing)
            op = pr.opening
            fail = op.full_open_travel is None
            self._row(node, "red-line pull: seal open", _travel(op.seal_open_travel), fail)
            self._row(node, "red-line pull: full open", _travel(op.full_open_travel), fail)
            node.setExpanded(True)
        rl = out.red_line
        if rl is not None:
            node = self._row(self.tree, "Red line", f"{rl.line.length:.3f} m")
            self._row(node, "route (without spare)", f"{rl.route_length:.3f} m")
            self._row(node, "confluence height", f"{rl.confluence[2]:.3f} m")
            self._row(
                node, "basket anchor", "unknown (no flying wires)" if rl.anchor is None else "frame"
            )
            self._row(node, "pull force", "not assessed")
            self._row(node, "mass", f"{rl.line.mass:.3f} kg")
        fw = out.flying_wires
        if fw is not None:
            node = self._row(
                self.tree,
                "Flying wires",
                f"{fw.wires.count} wires, {fw.geometry.group_size} tapes each",
            )
            self._row(node, "suspended weight", f"{fw.suspended_weight:.0f} N")
            self._row(node, "limit weight", f"{fw.limit_weight:.0f} N")
            lengths = ", ".join(f"{v:.3f}" for v in fw.geometry.wire_lengths)
            self._row(node, "wire lengths", f"{lengths} m")
            self._line(node, fw.wires)
            self._line(node, fw.legs)
            node.setExpanded(True)
        for v in out.turning_vents:
            node = self._row(
                self.tree,
                v.name,
                f"seam {v.seam}, {'counter-clockwise' if v.counterclockwise else 'clockwise'}",
            )
            self._row(node, "slot", f"{v.jet.slot_length:.3f} m long, {v.jet.area:.3f} m² open")
            self._row(node, "thrust (fully open)", f"{v.jet.thrust:.1f} N")
            self._row(node, "torque (fully open)", f"{v.jet.torque:.0f} N m")
            self._row(node, "air loss", f"{v.jet.mass_flow:.2f} kg/s")
            self._row(node, "heat loss", f"{v.jet.heat_loss / 1000:.0f} kW")
            self._line(node, v.control_line)
        if out.turning_vents:
            self._row(self.tree, "Net turning torque", f"{out.net_torque:.0f} N m")
            self._row(self.tree, "Net side force", f"{out.net_side_force:.1f} N")
        self.tree.resizeColumnToContents(0)

    def texts(self) -> dict[str, str]:
        """Top-level item texts (tests and scripting)."""
        out: dict[str, str] = {}
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if item is not None:
                out[item.text(0)] = item.text(1)
        return out

    def find_items(self, name: str) -> list[QTreeWidgetItem]:
        """Items whose first column is ``name`` (any depth)."""
        return self.tree.findItems(name, Qt.MatchFlag.MatchExactly | Qt.MatchFlag.MatchRecursive)
