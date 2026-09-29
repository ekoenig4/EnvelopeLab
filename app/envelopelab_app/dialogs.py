"""Preferences dialog."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLineEdit,
    QVBoxLayout,
    QWidget,
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
        self.stack_rows = QCheckBox("Stack pattern rows vertically as sewn (mouth at the bottom)")
        self.stack_rows.setChecked(prefs.stack_pattern_rows)
        self.enable_3d = QCheckBox("Use the PyVista 3D view (next start)")
        self.enable_3d.setChecked(prefs.enable_3d)
        self.recovery = QLineEdit(prefs.recovery_dir)
        self.recovery.setPlaceholderText("application data folder")
        form = QFormLayout()
        form.addRow("Autosave every", self.autosave)
        form.addRow("Preview mesh edge length", self.preview_mesh)
        form.addRow("CalculiX mesh edge length", self.calculix_mesh)
        form.addRow("CalculiX executable", self.ccx)
        form.addRow(self.auto_patterns)
        form.addRow(self.keep_rows)
        form.addRow(self.stack_rows)
        form.addRow(self.enable_3d)
        form.addRow("Recovery folder", self.recovery)
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
            stack_pattern_rows=self.stack_rows.isChecked(),
            enable_3d=self.enable_3d.isChecked(),
            recovery_dir=self.recovery.text().strip(),
        )
