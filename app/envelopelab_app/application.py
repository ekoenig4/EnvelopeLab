"""Application entry point: ``envelopelab`` (or ``python -m envelopelab_app``)."""

from __future__ import annotations

import argparse
import os
import sys

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from envelopelab_app.graphics import configure_graphics
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
    gl = parser.add_mutually_exclusive_group()
    gl.add_argument(
        "--software-gl",
        action="store_true",
        help="render with software OpenGL (default under WSL, where the GPU driver draws "
        "the window black)",
    )
    gl.add_argument(
        "--hardware-gl", action="store_true", help="use the GPU OpenGL driver even under WSL"
    )
    options, qt_args = parser.parse_known_args(args[1:])
    # Before any OpenGL context exists: Mesa reads the variable when the first one is made.
    reason = configure_graphics(os.environ, options.software_gl, options.hardware_gl)
    if reason:
        print(f"envelopelab: {reason}", file=sys.stderr)
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
