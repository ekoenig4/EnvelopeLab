"""Materials panel: the shared fabric library (with source tags) and the zone-to-fabric map.

The library is one file per user, shared by every design (see
:meth:`~envelopelab_app.settings.Preferences.resolved_material_library`). Fabrics created
here can be chosen in any design; example fabrics are read-only and can be duplicated.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from envelopelab.materials.repository import Fabric
from envelopelab_app.controller import WorkspaceController
from envelopelab_app.dialogs import FabricDialog, FabricDialogMode
from envelopelab_app.refresh import Refresher

LIBRARY_COLUMNS = (
    "id",
    "name",
    "kind",
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
        self.library.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.library.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.library.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.library.itemSelectionChanged.connect(self._update_buttons)
        self.library.cellDoubleClicked.connect(lambda _r, _c: self.edit_selected())
        self.new_button = QPushButton("New fabric…")
        self.new_button.clicked.connect(self.new_fabric)
        self.duplicate_button = QPushButton("Duplicate…")
        self.duplicate_button.clicked.connect(self.duplicate_selected)
        self.edit_button = QPushButton("Edit…")
        self.edit_button.clicked.connect(self.edit_selected)
        self.delete_button = QPushButton("Delete")
        self.delete_button.clicked.connect(self.delete_selected)
        library_buttons = QHBoxLayout()
        for button in (self.new_button, self.duplicate_button, self.edit_button):
            library_buttons.addWidget(button)
        library_buttons.addWidget(self.delete_button)
        self.library_label = QLabel()
        self.library_label.setWordWrap(True)
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
        layout.addWidget(QLabel("Fabric library, shared by all designs (values with source tags)"))
        layout.addWidget(self.library_label)
        layout.addWidget(self.library)
        layout.addLayout(library_buttons)
        layout.addWidget(QLabel("Material zones of this design"))
        layout.addWidget(self.zones)
        layout.addLayout(buttons)
        self.refresher = Refresher(
            self,
            self.refresh,
            lambda: controller.revision,
            (controller.stateChanged, controller.sessionChanged, controller.libraryChanged),
            defer_hidden=lambda: controller.defer_hidden,
        )
        self.refresh()

    def refresh(self) -> None:
        """Show the library and the design's zones."""
        library = self.controller.fabrics
        if self.controller.library_error is not None:
            self.library_label.setText(f"<b>Warning:</b> {self.controller.library_error}")
        elif library.path is not None:
            self.library_label.setText(f"Library file: {library.path}")
        else:
            self.library_label.setText("Temporary library: fabrics created now are not saved.")
        selected = self.selected_fabric_id()
        fabrics = library.fabrics()
        self.library.setRowCount(len(fabrics))
        for i, f in enumerate(fabrics):
            cells = (
                f.fabric_id,
                f.name,
                "user" if library.is_editable(f.fabric_id) else "example (read-only)",
                f"{f.areal_mass.value:g}",
                f"{f.max_service_temperature.value:g}",
                f"{f.roll_width.value:g}",
                f.areal_mass.source,
            )
            for j, text in enumerate(cells):
                self.library.setItem(i, j, QTableWidgetItem(text))
        if selected is not None:
            self.select_fabric(selected)
        design = self.controller.design
        zones = {} if design is None else dict(design.zones)
        self.zones.setRowCount(len(zones))
        ids = [f.fabric_id for f in fabrics]
        for i, (zone, fabric_id) in enumerate(zones.items()):
            self.zones.setItem(i, 0, QTableWidgetItem(zone))
            combo = QComboBox()
            missing = fabric_id not in ids
            combo.addItems([*ids, fabric_id] if missing else ids)
            combo.setCurrentText(fabric_id)
            if missing:
                combo.setToolTip(f"{fabric_id!r} is not in your fabric library")
            combo.activated.connect(
                lambda _i, z=zone, c=combo: self._fabric_chosen(z, c.currentText())
            )
            self.zones.setCellWidget(i, 1, combo)
        self._update_buttons()

    # -- library --------------------------------------------------------------------------

    def selected_fabric_id(self) -> str | None:
        """Id of the selected library row (None: nothing selected)."""
        rows = self.library.selectionModel().selectedRows()
        if not rows:
            return None
        item = self.library.item(rows[0].row(), 0)
        return None if item is None else item.text()

    def select_fabric(self, fabric_id: str) -> None:
        """Select the library row of ``fabric_id``."""
        for row in range(self.library.rowCount()):
            item = self.library.item(row, 0)
            if item is not None and item.text() == fabric_id:
                self.library.selectRow(row)
                return

    def _selected_fabric(self) -> Fabric | None:
        fabric_id = self.selected_fabric_id()
        return None if fabric_id is None else self.controller.fabrics.fabric(fabric_id)

    def _update_buttons(self) -> None:
        fabric_id = self.selected_fabric_id()
        editable = fabric_id is not None and self.controller.fabrics.is_editable(fabric_id)
        self.duplicate_button.setEnabled(fabric_id is not None)
        self.edit_button.setEnabled(editable)
        self.delete_button.setEnabled(editable)
        if fabric_id is not None and not editable:
            self.edit_button.setToolTip("Example fabrics are read-only; duplicate to change one")
        else:
            self.edit_button.setToolTip("")

    def make_dialog(self, mode: FabricDialogMode, fabric: Fabric | None = None) -> FabricDialog:
        """The fabric form for ``mode``."""
        return FabricDialog(mode, fabric, self.controller.fabrics.known_fabric_ids(), self)

    def run_dialog(self, dialog: FabricDialog) -> Fabric | None:
        """Show ``dialog`` modally; the accepted fabric or None."""
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return dialog.result_fabric()

    def new_fabric(self) -> bool:
        """Create a fabric from an empty form."""
        fabric = self.run_dialog(self.make_dialog("new"))
        return fabric is not None and self._created(fabric)

    def duplicate_selected(self) -> bool:
        """Create a fabric from a copy of the selected one."""
        source = self._selected_fabric()
        if source is None:
            return False
        fabric = self.run_dialog(self.make_dialog("duplicate", source))
        return fabric is not None and self._created(fabric)

    def _created(self, fabric: Fabric) -> bool:
        if not self.controller.add_fabric(fabric):
            return False
        self.select_fabric(fabric.fabric_id)
        self.controller.message.emit(f"Fabric {fabric.fabric_id} added to the shared library")
        return True

    def edit_selected(self) -> bool:
        """Edit the selected user fabric."""
        current = self._selected_fabric()
        if current is None or not self.controller.fabrics.is_editable(current.fabric_id):
            return False
        fabric = self.run_dialog(self.make_dialog("edit", current))
        if fabric is None or fabric == current:
            return False
        users = self.controller.zones_using(fabric.fabric_id)
        if not self.controller.update_fabric(fabric):
            return False
        self.select_fabric(fabric.fabric_id)
        note = " Results built from it are now stale." if users else ""
        self.controller.message.emit(f"Fabric {fabric.fabric_id} updated in every design.{note}")
        return True

    def confirm(self, title: str, text: str) -> bool:
        """Ask a yes/no question."""
        answer = QMessageBox.question(self, title, text)
        return answer == QMessageBox.StandardButton.Yes

    def delete_selected(self) -> bool:
        """Delete the selected user fabric after confirmation."""
        fabric_id = self.selected_fabric_id()
        if fabric_id is None or not self.controller.fabrics.is_editable(fabric_id):
            return False
        users = self.controller.zones_using(fabric_id)
        text = (
            f"Delete fabric {fabric_id!r} from the shared library? Other designs that use it "
            "will show it as missing."
        )
        if users:
            text += f"\n\nThis design uses it in zone(s): {', '.join(users)}."
        if not self.confirm("Delete fabric", text):
            return False
        return self.controller.delete_fabric(fabric_id)

    # -- zones ----------------------------------------------------------------------------

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
