"""File ▸ Export build pack…: where to write the pack, the roll width and its documents."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from envelopelab.export.build_pack import DEFAULT_ROLL_WIDTH
from envelopelab.export.documents import DOCUMENTS

#: Check-box text per document, in the order shown.
DOCUMENT_TEXT = {
    "viewer": "3D view (HTML, opens offline in a browser)",
    "cover": "Cover and index (PDF)",
    "spec": "Spec summary (PDF + JSON)",
    "cut_list": "Cut list (PDF + CSV)",
    "rigging": "Rigging sheet (PDF + CSV)",
    "sewing": "Sewing schedule (PDF + CSV)",
}
INCH = 0.0254  # m


class ExportPackDialog(QDialog):
    """Choose the folder, the fabric roll width and the documents of a build pack.

    The 1:1 templates and ``cad/`` (one DXF per piece and ``index.json``) are always
    written; the documents are optional.
    """

    def __init__(self, parent: QWidget | None = None, folder: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle("Export build pack")
        self.folder = QLineEdit(folder)
        self.folder.setObjectName("packFolder")
        self.folder.setPlaceholderText("Folder for the pack (created if needed)")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.folder, 1)
        row.addWidget(browse)
        self.roll = QDoubleSpinBox()
        self.roll.setObjectName("rollWidth")
        self.roll.setRange(10.0, 200.0)
        self.roll.setDecimals(1)
        self.roll.setSuffix(" in")
        self.roll.setValue(DEFAULT_ROLL_WIDTH / INCH)
        self.roll.setToolTip("Fabric roll width: one side of every 1:1 page is no longer")
        form = QFormLayout()
        form.addRow("Folder", row)
        form.addRow("Roll width", self.roll)
        self.checks: dict[str, QCheckBox] = {}
        docs = QVBoxLayout()
        always = QLabel(
            "Always: the 1:1 panel and piece templates (PDF), cad/ (one DXF per piece, index.json)"
        )
        always.setProperty("role", "muted")
        docs.addWidget(always)
        for key in DOCUMENTS:
            box = QCheckBox(DOCUMENT_TEXT.get(key, key))
            box.setObjectName(f"pack_{key}")
            box.setChecked(True)
            box.setToolTip(DOCUMENTS[key][1])
            self.checks[key] = box
            docs.addWidget(box)
        form.addRow("Include", docs)
        note = QLabel(
            "The 3D view shows the run chosen in the 3D view, with its status; a stale or "
            "unconverged run is never coloured as a result."
        )
        note.setWordWrap(True)
        note.setProperty("role", "muted")
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Export")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addWidget(buttons)

    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Build pack folder", self.folder.text())
        if path:
            self.folder.setText(path)

    def _accept(self) -> None:
        if self.folder.text().strip():
            self.accept()

    def include(self) -> frozenset[str]:
        """The documents checked."""
        return frozenset(k for k, box in self.checks.items() if box.isChecked())

    def roll_width(self) -> float:
        """The roll width, m."""
        return float(self.roll.value()) * INCH

    def path(self) -> Path:
        """The pack folder."""
        return Path(self.folder.text().strip())
