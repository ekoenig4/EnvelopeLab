"""Materials panel: the fabric library (with source tags) and the zone-to-fabric map."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from envelopelab_app.controller import WorkspaceController

LIBRARY_COLUMNS = (
    "id",
    "name",
    "areal mass (g/m²)",
    "max service temp (°C)",
    "roll width (m)",
    "source",
)


class MaterialsPanel(QWidget):
    """See module docstring."""

    def __init__(self, controller: WorkspaceController) -> None:
        super().__init__()
        self.controller = controller
        self.library = QTableWidget(0, len(LIBRARY_COLUMNS))
        self.library.setHorizontalHeaderLabels(list(LIBRARY_COLUMNS))
        self.library.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.library.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.zones = QTableWidget(0, 2)
        self.zones.setHorizontalHeaderLabels(["zone", "fabric"])
        self.zones.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        add = QPushButton("Add zone")
        add.clicked.connect(self._add_zone)
        remove = QPushButton("Remove zone")
        remove.clicked.connect(self._remove_zone)
        buttons = QHBoxLayout()
        buttons.addWidget(add)
        buttons.addWidget(remove)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Fabric library (values as entered, with source tags)"))
        layout.addWidget(self.library)
        layout.addWidget(QLabel("Material zones of this design"))
        layout.addWidget(self.zones)
        layout.addLayout(buttons)
        controller.stateChanged.connect(self.refresh)
        controller.sessionChanged.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        """Show the library and the design's zones."""
        fabrics = self.controller.fabrics.fabrics()
        self.library.setRowCount(len(fabrics))
        for i, f in enumerate(fabrics):
            cells = (
                f.fabric_id,
                f.name,
                f"{f.areal_mass.value:g}",
                f"{f.max_service_temperature.value:g}",
                f"{f.roll_width.value:g}",
                f.areal_mass.source,
            )
            for j, text in enumerate(cells):
                self.library.setItem(i, j, QTableWidgetItem(text))
        design = self.controller.design
        zones = {} if design is None else dict(design.zones)
        self.zones.setRowCount(len(zones))
        ids = [f.fabric_id for f in fabrics]
        for i, (zone, fabric_id) in enumerate(zones.items()):
            self.zones.setItem(i, 0, QTableWidgetItem(zone))
            combo = QComboBox()
            combo.addItems(ids if fabric_id in ids else [*ids, fabric_id])
            combo.setCurrentText(fabric_id)
            combo.activated.connect(
                lambda _i, z=zone, c=combo: self._fabric_chosen(z, c.currentText())
            )
            self.zones.setCellWidget(i, 1, combo)

    def _fabric_chosen(self, zone: str, fabric_id: str) -> None:
        self.controller.set_value(("zones", zone), fabric_id)

    def _add_zone(self) -> None:
        name, ok = QInputDialog.getText(self, "Add zone", "Zone name:")
        design = self.controller.design
        if ok and name and design is not None:
            fabrics = self.controller.fabrics.fabrics()
            self.controller.set_value(
                ("zones", name.strip()), fabrics[0].fabric_id if fabrics else ""
            )

    def _remove_zone(self) -> None:
        rows = self.zones.selectionModel().selectedRows() or self.zones.selectedIndexes()
        session = self.controller.session
        if not rows or session is None:
            return
        cell = self.zones.item(rows[0].row(), 0)
        if cell is None:
            return
        zone = cell.text()

        def mutate(design: dict[str, object], _patterns: dict[str, object]) -> None:
            zones = design["zones"]
            assert isinstance(zones, dict)
            zones.pop(zone, None)

        self.controller.attempt(session.edit, f"Remove zone {zone}", mutate)
