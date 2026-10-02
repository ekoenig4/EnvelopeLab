"""New-design wizard: standard gore from targets, from a shape file, special shape from a
mesh, measurements."""

from __future__ import annotations

from PySide6.QtCore import QSettings
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
from envelopelab_app.settings import (
    WizardDefaults,
    load_wizard_defaults,
    reset_wizard_defaults,
    save_wizard_defaults,
)
from envelopelab_app.shape_tab import ShapeFileTab


def _spin(value: float, low: float, high: float, suffix: str, decimals: int = 2) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(low, high)
    box.setDecimals(decimals)
    box.setValue(value)
    box.setSuffix(suffix)
    return box


#: Mouth-fabric choice for a design without a separate mouth row.
NO_MOUTH_ROW = "(no separate mouth row)"


class NewDesignWizard(QDialog):
    """Dialog that produces a new :class:`DesignDocument` (``self.design``)."""

    def __init__(
        self,
        fabrics: FabricLibraryRepository,
        parent: QWidget | None = None,
        settings: QSettings | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
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
        ids = [f.fabric_id for f in fabrics.fabrics()]
        self.fabric = QComboBox()
        self.fabric.addItems(ids)
        if "ripstop_nylon" in ids:
            self.fabric.setCurrentText("ripstop_nylon")
        self.mouth_fabric = QComboBox()
        self.mouth_fabric.addItems([NO_MOUTH_ROW, *ids])
        if "nomex" in ids:
            self.mouth_fabric.setCurrentText("nomex")
        self.mouth_height = _spin(0.0, 0.0, 100.0, " m")
        self.mouth_height.setSpecialValueText("same as the body rows")
        self.allowance = _spin(25.0, 0.0, 200.0, " mm", 1)
        self.internal = _spin(100.0, -50.0, 200.0, " °C", 1)
        self.ambient = _spin(15.0, -60.0, 60.0, " °C", 1)
        for label, widget in (
            ("Name", self.name),
            ("Target volume", self.volume),
            ("Target height (mouth to top opening)", self.target_height),
            ("Target maximum diameter", self.target_width),
            ("Gores N", self.gores),
            ("Mouth row fabric (next to the burner)", self.mouth_fabric),
            ("Mouth row height", self.mouth_height),
            ("Body panel rows (above the mouth row)", self.rows),
            ("Mouth diameter", self.mouth),
            ("Top opening diameter", self.top),
            ("Body and parachute fabric", self.fabric),
            ("Seam allowance", self.allowance),
            ("Internal temperature", self.internal),
            ("Ambient temperature", self.ambient),
        ):
            form.addRow(label, widget)
        self.save_defaults = QPushButton("Save as my defaults")
        self.save_defaults.setToolTip("Open the wizard with these values next time")
        self.save_defaults.clicked.connect(self.store_defaults)
        self.reset_defaults = QPushButton("Reset to built-in defaults")
        self.reset_defaults.clicked.connect(self.restore_builtin_defaults)
        defaults_row = QHBoxLayout()
        defaults_row.addWidget(self.save_defaults)
        defaults_row.addWidget(self.reset_defaults)
        form.addRow(defaults_row)
        self.defaults_note = QLabel()
        form.addRow(self.defaults_note)
        for button in (self.save_defaults, self.reset_defaults):
            button.setEnabled(settings is not None)
        self.apply_defaults(
            load_wizard_defaults(settings) if settings is not None else WizardDefaults()
        )
        self.tabs.addTab(gore, "Standard gore")

        self.shape_tab = ShapeFileTab([f.fabric_id for f in fabrics.fabrics()])
        self.tabs.addTab(self.shape_tab, "From shape file")

        special = QWidget()
        self.special_tab = special
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
        self.measure_tab = measure
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

    # -- defaults -----------------------------------------------------------------------

    def apply_defaults(self, d: WizardDefaults) -> None:
        """Show ``d`` in the standard-gore fields (unknown fabrics keep the current one)."""
        self.name.setText(d.name)
        self.volume.setValue(d.volume)
        self.target_height.setValue(d.height)
        self.target_width.setValue(d.width)
        self.gores.setValue(d.gores)
        self.rows.setValue(d.rows)
        self.mouth.setValue(d.mouth_fraction)
        self.top.setValue(d.top_fraction)
        if self.fabric.findText(d.fabric) >= 0:
            self.fabric.setCurrentText(d.fabric)
        mouth = d.mouth_fabric or NO_MOUTH_ROW
        if self.mouth_fabric.findText(mouth) >= 0:
            self.mouth_fabric.setCurrentText(mouth)
        self.mouth_height.setValue(d.mouth_height)
        self.allowance.setValue(d.allowance_mm)
        self.internal.setValue(d.internal_c)
        self.ambient.setValue(d.ambient_c)

    def current_defaults(self) -> WizardDefaults:
        """The standard-gore fields as wizard defaults."""
        mouth = self.mouth_fabric.currentText()
        return WizardDefaults(
            name=self.name.text().strip() or "New envelope",
            volume=self.volume.value(),
            height=self.target_height.value(),
            width=self.target_width.value(),
            gores=self.gores.value(),
            rows=self.rows.value(),
            mouth_fraction=self.mouth.value(),
            top_fraction=self.top.value(),
            fabric=self.fabric.currentText(),
            mouth_fabric="" if mouth == NO_MOUTH_ROW else mouth,
            mouth_height=self.mouth_height.value(),
            allowance_mm=self.allowance.value(),
            internal_c=self.internal.value(),
            ambient_c=self.ambient.value(),
        )

    def store_defaults(self) -> None:
        """Save the current fields as the user's defaults."""
        if self.settings is None:
            return
        save_wizard_defaults(self.settings, self.current_defaults())
        self.defaults_note.setText("Saved: the wizard opens with these values next time.")

    def restore_builtin_defaults(self) -> None:
        """Forget the user's defaults and show the built-in values."""
        if self.settings is not None:
            reset_wizard_defaults(self.settings)
        self.apply_defaults(WizardDefaults())
        self.defaults_note.setText("Built-in defaults restored.")

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Reference mesh", "", "Meshes (*.obj *.stl *.ply)"
        )
        if path:
            self.mesh_path.setText(path)

    def _tab_changed(self, index: int) -> None:
        ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setEnabled(self.tabs.widget(index) is not self.measure_tab)
        self.error.setText("")

    def create_design(self) -> None:
        """Build the design from the current tab; errors are shown in the dialog."""
        current = self.tabs.currentWidget()
        try:
            if self.tabs.currentIndex() == 0:
                w = self.target_width.value()
                mouth = self.mouth_fabric.currentText()
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
                    mouth_fabric_id=None if mouth == NO_MOUTH_ROW else mouth,
                    mouth_row_height=self.mouth_height.value() or None,
                )
            elif current is self.shape_tab:
                self.design = self.shape_tab.design()
            elif current is not self.measure_tab:
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
