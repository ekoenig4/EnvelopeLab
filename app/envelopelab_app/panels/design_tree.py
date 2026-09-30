"""Design Tree panel: the design's sections, rows, snapshots, runs and artifact states."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from envelopelab.project.dependencies import ARTIFACTS
from envelopelab.project.gore_design import row_zone
from envelopelab_app.controller import WorkspaceController

STATUS_COLORS = {"current": "#155724", "stale": "#b00020", "not built": "#6c757d"}

#: Tree sections: (target, title, input group that makes it "unsaved").
SECTIONS = (
    ("meta", "Design", "meta"),
    ("gores", "Gores", "geometry"),
    ("zones", "Material zones", "materials"),
    ("tapes", "Tapes", "tapes"),
    ("seam_types", "Seam types", "seam_allowance"),
    ("operating", "Operating conditions", "operating"),
    ("features", "Features", "features"),
    ("parachute", "Parachute", "parachute"),
    ("rigging", "Rigging (red line, flying wires)", "rigging"),
    ("turning_vents", "Turning vents", "turning_vents"),
    ("scoop", "Scoop", "scoop"),
    ("special", "Special shape", "geometry"),
)


class DesignTreePanel(QWidget):
    """See module docstring. Selecting an item selects that element everywhere."""

    def __init__(self, controller: WorkspaceController) -> None:
        super().__init__()
        self.controller = controller
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Element", "State"])
        self.tree.itemSelectionChanged.connect(self._selected)
        layout = QVBoxLayout(self)
        layout.addWidget(self.tree)
        for signal in (
            controller.stateChanged,
            controller.artifactsChanged,
            controller.runsChanged,
            controller.snapshotsChanged,
            controller.sessionChanged,
            controller.fileChanged,
        ):
            signal.connect(self.refresh)
        self.refresh()

    def _add(
        self, parent: QTreeWidget | QTreeWidgetItem, title: str, target: str, state: str = ""
    ) -> QTreeWidgetItem:
        item = QTreeWidgetItem([title, state])
        item.setData(0, Qt.ItemDataRole.UserRole, target)
        if isinstance(parent, QTreeWidget):
            parent.addTopLevelItem(item)
        else:
            parent.addChild(item)
        return item

    def refresh(self) -> None:
        """Rebuild the tree."""
        self.tree.blockSignals(True)
        self.tree.clear()
        session = self.controller.session
        if session is None:
            self.tree.blockSignals(False)
            return
        design = session.design
        unsaved = session.unsaved_groups()
        root = self._add(self.tree, design.meta.name, "meta", "unsaved" if session.is_dirty else "")
        for target, title, group in SECTIONS:
            if target == "gores" and design.gores is None:
                continue
            if target == "special" and design.special is None:
                continue
            state = "● unsaved" if group in unsaved else ""
            if target in ("parachute", "scoop") and getattr(design, target) is None:
                state = (state + " not defined").strip()
            item = self._add(root, title, target, state)
            if target == "gores" and design.gores is not None:
                self._add(
                    item,
                    f"Profile ({len(design.gores.meridian_profile_control_points)} control points)",
                    "profile",
                )
                rows = self._add(item, f"Panel rows ({len(design.gores.panel_rows)})", "rows")
                for row in design.gores.panel_rows:
                    flag = (
                        " (manual override)"
                        if session.patterns.row(row.letter).manual_outline
                        else ""
                    )
                    zone = row_zone(design, session.patterns, row.letter)
                    fabric = design.zones.get(zone, "?")
                    self._add(
                        rows, f"Row {row.letter}: {zone} ({fabric}){flag}", f"row:{row.letter}"
                    )
                if design.parachute is not None:
                    self._add(rows, "Top: parachute", "parachute")
            if target == "turning_vents":
                for vent in design.turning_vents:
                    self._add(item, f"{vent.name} (seam {vent.seam})", "turning_vents")
            if target == "zones":
                for zone, fabric in design.zones.items():
                    self._add(item, f"{zone}: {fabric}", "zones")
        artifacts = self._add(self.tree, "Derived artifacts", "artifacts")
        for spec in ARTIFACTS:
            status = self.controller.artifact_status(spec.name)
            child = self._add(artifacts, spec.title, f"artifact:{spec.name}", status)
            child.setForeground(1, QBrush(QColor(STATUS_COLORS[status])))
        snaps = self._add(self.tree, f"Snapshots ({len(session.project.snapshots)})", "snapshots")
        for snap in session.project.snapshots:
            self._add(
                snaps, snap.name, f"snapshot:{snap.name}", snap.created.strftime("%Y-%m-%d %H:%M")
            )
        versions = self._add(self.tree, f"Versions ({len(session.project.versions)})", "versions")
        for version in session.project.versions:
            self._add(
                versions, version.version_id, f"version:{version.version_id}", version.message
            )
        runs = self._add(self.tree, f"Simulation runs ({len(session.project.runs)})", "runs")
        for record in session.project.runs:
            status = self.controller.run_status(record)
            text = status.upper() + ("" if record.converged else ", NOT CONVERGED")
            child = self._add(
                runs, f"{record.solver_label} {record.run_id}", f"run:{record.run_id}", text
            )
            child.setForeground(
                1,
                QBrush(
                    QColor(
                        STATUS_COLORS[
                            "stale" if status == "stale" or not record.converged else "current"
                        ]
                    )
                ),
            )
        self.tree.expandToDepth(1)
        self.tree.resizeColumnToContents(0)
        self.tree.blockSignals(False)

    def _selected(self) -> None:
        items = self.tree.selectedItems()
        if items:
            self.controller.select(str(items[0].data(0, Qt.ItemDataRole.UserRole)))
