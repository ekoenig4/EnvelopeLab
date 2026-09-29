"""History panel: full undo history (click to jump), named snapshots, design versions and
the provenance log."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from envelopelab_app.controller import WorkspaceController


class HistoryPanel(QWidget):
    """See module docstring."""

    def __init__(self, controller: WorkspaceController) -> None:
        super().__init__()
        self.controller = controller
        self.history = QListWidget()
        self.history.itemClicked.connect(self._jump)
        self.snapshots = QListWidget()
        self.versions = QListWidget()
        self.provenance = QListWidget()
        take = QPushButton("Take snapshot…")
        take.clicked.connect(self._take)
        restore = QPushButton("Restore")
        restore.clicked.connect(self._restore)
        delete = QPushButton("Delete")
        delete.clicked.connect(self._delete)
        commit = QPushButton("Commit version…")
        commit.clicked.connect(self._commit)
        checkout = QPushButton("Check out")
        checkout.clicked.connect(self._checkout)

        snap_page = QWidget()
        snap_layout = QVBoxLayout(snap_page)
        snap_layout.addWidget(self.snapshots)
        row = QHBoxLayout()
        for b in (take, restore, delete):
            row.addWidget(b)
        snap_layout.addLayout(row)
        version_page = QWidget()
        version_layout = QVBoxLayout(version_page)
        version_layout.addWidget(self.versions)
        row2 = QHBoxLayout()
        row2.addWidget(commit)
        row2.addWidget(checkout)
        version_layout.addLayout(row2)
        tabs = QTabWidget()
        tabs.addTab(self.history, "Undo history")
        tabs.addTab(snap_page, "Snapshots")
        tabs.addTab(version_page, "Versions")
        tabs.addTab(self.provenance, "Provenance")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Click an entry to return to that state (undoable)."))
        layout.addWidget(tabs)
        for signal in (
            controller.stateChanged,
            controller.snapshotsChanged,
            controller.provenanceChanged,
            controller.sessionChanged,
            controller.fileChanged,
        ):
            signal.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        """Show the session's history lists."""
        for widget in (self.history, self.snapshots, self.versions, self.provenance):
            widget.clear()
        session = self.controller.session
        if session is None:
            return
        entries = ["(opened / created)", *session.stack.history()]
        current = session.stack.index
        for i, text in enumerate(entries):
            item = QListWidgetItem(("▶ " if i == current else "   ") + text)
            item.setData(Qt.ItemDataRole.UserRole, i)
            if i > current:
                item.setForeground(Qt.GlobalColor.gray)
            if i == current:
                font = QFont()
                font.setBold(True)
                item.setFont(font)
            self.history.addItem(item)
        for snap in session.project.snapshots:
            item = QListWidgetItem(
                f"{snap.name}  ({snap.created:%Y-%m-%d %H:%M}, {snap.content_hash[:10]})"
            )
            item.setData(Qt.ItemDataRole.UserRole, snap.name)
            self.snapshots.addItem(item)
        for version in session.project.versions:
            item = QListWidgetItem(
                f"{version.version_id} ← {version.parent_id}: {version.message} "
                f"({version.created:%Y-%m-%d %H:%M})"
            )
            item.setData(Qt.ItemDataRole.UserRole, version.version_id)
            self.versions.addItem(item)
        for entry in reversed(session.project.provenance):
            self.provenance.addItem(
                f"{entry.timestamp:%Y-%m-%d %H:%M:%S} {entry.action} [{entry.target}]: "
                f"{entry.detail}"
            )

    def _jump(self, item: QListWidgetItem) -> None:
        session = self.controller.session
        if session is not None:
            session.stack.go_to(int(item.data(Qt.ItemDataRole.UserRole)))

    def _selected(self, widget: QListWidget) -> str | None:
        item = widget.currentItem()
        return None if item is None else str(item.data(Qt.ItemDataRole.UserRole))

    def _take(self) -> None:
        session = self.controller.session
        if session is None:
            return
        name, ok = QInputDialog.getText(self, "Take snapshot", "Snapshot name:")
        if ok and name.strip():
            session.create_snapshot(name.strip())

    def _restore(self) -> None:
        name = self._selected(self.snapshots)
        if name is not None and self.controller.session is not None:
            self.controller.attempt(self.controller.session.restore_snapshot, name)

    def _delete(self) -> None:
        name = self._selected(self.snapshots)
        if name is not None and self.controller.session is not None:
            self.controller.session.delete_snapshot(name)

    def _commit(self) -> None:
        session = self.controller.session
        if session is None:
            return
        message, ok = QInputDialog.getText(self, "Commit version", "Version message:")
        if ok:
            session.commit_version(message.strip() or "(no message)")

    def _checkout(self) -> None:
        version = self._selected(self.versions)
        if version is not None and self.controller.session is not None:
            self.controller.attempt(self.controller.session.checkout_version, version)
