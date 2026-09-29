"""New-design wizard: standard gore from targets, special shape from a mesh, measurements."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from envelopelab.design.model import DesignDocument
from envelopelab.materials.repository import FabricLibraryRepository
from envelopelab.project.gore_design import standard_gore_design
from envelopelab.project.templates import (
    MEASUREMENTS_NOT_IMPLEMENTED,
    special_design_from_mesh,
)


def _spin(value: float, low: float, high: float, suffix: str, decimals: int = 2) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(low, high)
    box.setDecimals(decimals)
    box.setValue(value)
    box.setSuffix(suffix)
    return box


class NewDesignWizard(QDialog):
    """Dialog that produces a new :class:`DesignDocument` (``self.design``)."""

    def __init__(self, fabrics: FabricLibraryRepository, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("New design")
        self.design: DesignDocument | None = None
        self.tabs = QTabWidget()

        gore = QWidget()
        form = QFormLayout(gore)
        self.name = QLineEdit("New envelope")
        self.volume = _spin(2200.0, 1.0, 1e6, " m³", 1)
        self.target_height = _spin(17.0, 0.5, 200.0, " m")
        self.target_width = _spin(16.0, 0.5, 200.0, " m")
        self.gores = QSpinBox()
        self.gores.setRange(3, 200)
        self.gores.setValue(12)
        self.rows = QSpinBox()
        self.rows.setRange(1, 26)
        self.rows.setValue(5)
        self.mouth = _spin(0.30, 0.05, 0.95, " × width")
        self.top = _spin(0.25, 0.05, 0.95, " × width")
        self.fabric = QComboBox()
        self.fabric.addItems([f.fabric_id for f in fabrics.fabrics()])
        self.allowance = _spin(25.0, 0.0, 200.0, " mm", 1)
        self.internal = _spin(100.0, -50.0, 200.0, " °C", 1)
        self.ambient = _spin(15.0, -60.0, 60.0, " °C", 1)
        for label, widget in (
            ("Name", self.name),
            ("Target volume", self.volume),
            ("Target height (mouth to top opening)", self.target_height),
            ("Target maximum diameter", self.target_width),
            ("Gores N", self.gores),
            ("Panel rows", self.rows),
            ("Mouth diameter", self.mouth),
            ("Top opening diameter", self.top),
            ("Fabric", self.fabric),
            ("Seam allowance", self.allowance),
            ("Internal temperature", self.internal),
            ("Ambient temperature", self.ambient),
        ):
            form.addRow(label, widget)
        self.tabs.addTab(gore, "Standard gore")

        special = QWidget()
        sform = QFormLayout(special)
        self.special_name = QLineEdit("Special shape")
        self.mesh_path = QLineEdit()
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.mesh_path)
        row.addWidget(browse)
        sform.addRow("Name", self.special_name)
        sform.addRow("Mesh (OBJ, STL, PLY in m)", row)
        sform.addRow(
            QLabel("The mesh is referenced by the design; seams and panels are added later.")
        )
        self.tabs.addTab(special, "Special shape from mesh")

        measure = QWidget()
        mlayout = QVBoxLayout(measure)
        note = QLabel(MEASUREMENTS_NOT_IMPLEMENTED)
        note.setWordWrap(True)
        mlayout.addWidget(note)
        mlayout.addStretch(1)
        self.tabs.addTab(measure, "From measurements (planned)")
        self.tabs.currentChanged.connect(self._tab_changed)

        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #b00020;")
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.create_design)
        self.buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)
        layout.addWidget(self.error)
        layout.addWidget(self.buttons)

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Reference mesh", "", "Meshes (*.obj *.stl *.ply)"
        )
        if path:
            self.mesh_path.setText(path)

    def _tab_changed(self, index: int) -> None:
        ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setEnabled(index != 2)
        self.error.setText("")

    def create_design(self) -> None:
        """Build the design from the current tab; errors are shown in the dialog."""
        try:
            if self.tabs.currentIndex() == 0:
                w = self.target_width.value()
                self.design = standard_gore_design(
                    name=self.name.text().strip() or "New envelope",
                    target_volume=self.volume.value(),
                    target_height=self.target_height.value(),
                    target_width=w,
                    gore_count=self.gores.value(),
                    row_count=self.rows.value(),
                    mouth_diameter=self.mouth.value() * w,
                    top_diameter=self.top.value() * w,
                    fabric_id=self.fabric.currentText() or "ripstop_nylon",
                    seam_allowance=self.allowance.value() / 1000.0,
                    internal_temperature=self.internal.value() + 273.15,
                    ambient_temperature=self.ambient.value() + 273.15,
                )
            elif self.tabs.currentIndex() == 1:
                self.design = special_design_from_mesh(
                    self.special_name.text().strip() or "Special shape",
                    self.mesh_path.text().strip(),
                    fabric_id=self.fabric.currentText() or "ripstop_nylon",
                    seam_allowance=self.allowance.value() / 1000.0,
                )
            else:
                self.error.setText(MEASUREMENTS_NOT_IMPLEMENTED)
                return
        except (ValueError, OSError) as exc:
            self.error.setText(str(exc))
            return
        self.accept()
