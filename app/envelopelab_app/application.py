"""Application entry point: ``envelopelab`` (or ``python -m envelopelab_app``)."""

from __future__ import annotations

import argparse
import sys

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from envelopelab_app.main_window import MainWindow

ORGANIZATION = "EnvelopeLab"
APPLICATION = "EnvelopeLab"


def create_application(argv: list[str]) -> QApplication:
    """The QApplication (created once per process)."""
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        return existing
    app = QApplication(argv)
    app.setOrganizationName(ORGANIZATION)
    app.setApplicationName(APPLICATION)
    return app


def main(argv: list[str] | None = None) -> int:
    """Start the desktop application; an optional argument opens a project file."""
    args = sys.argv if argv is None else argv
    parser = argparse.ArgumentParser(
        prog="envelopelab", description="EnvelopeLab desktop application"
    )
    parser.add_argument("project", nargs="?", help="project file to open (.elproj)")
    parser.add_argument("--no-3d", action="store_true", help="start without the PyVista 3D view")
    options, qt_args = parser.parse_known_args(args[1:])
    app = create_application([args[0], *qt_args])
    window = MainWindow(
        QSettings(ORGANIZATION, APPLICATION), enable_3d=False if options.no_3d else None
    )
    if options.project:
        window.open_project(options.project)
    window.show()
    return int(app.exec())


if __name__ == "__main__":
    sys.exit(main())
