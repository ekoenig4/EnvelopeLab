"""Crash log and environment report, so a crash can be diagnosed from one file.

A crash in Qt, VTK or the OpenGL driver ends the process without a Python traceback. At
start-up the launcher enables :mod:`faulthandler` into a crash log, so a segmentation fault
or abort leaves the Python stack of every thread there, and writes the environment the
application started in (versions, display, OpenGL and Qt platform settings) above it.
Unhandled Python exceptions are written there too. ``envelopelab --diagnose`` prints the
same report and creates an OpenGL context to name the renderer.
"""

from __future__ import annotations

import faulthandler
import os
import platform as platform_module
import sys
import traceback
from collections.abc import Mapping
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from types import TracebackType
from typing import IO, Any

from envelopelab_app.graphics import QT_PLATFORM, SOFTWARE_GL, is_wsl

#: Environment variables that decide how the window and OpenGL are set up.
DISPLAY_VARIABLES = (
    "DISPLAY",
    "WAYLAND_DISPLAY",
    "XDG_SESSION_TYPE",
    QT_PLATFORM,
    SOFTWARE_GL,
    "GALLIUM_DRIVER",
    "MESA_D3D12_DEFAULT_ADAPTER_NAME",
    "WSL_DISTRO_NAME",
)
PACKAGES = ("envelopelab", "PySide6", "vtk", "pyvista", "pyvistaqt", "numpy", "gmsh")
#: Keeps the crash log open for faulthandler (it writes to the file descriptor).
_LOG: IO[str] | None = None


def crash_log_path(environ: Mapping[str, str] = os.environ, platform: str = sys.platform) -> Path:
    """Where the crash log is written: the user's local application-state folder.

    Linux and WSL: ``$XDG_STATE_HOME/envelopelab/crash.log`` (default
    ``~/.local/state``); Windows: ``%LOCALAPPDATA%\\EnvelopeLab\\crash.log``; macOS:
    ``~/Library/Logs/EnvelopeLab/crash.log``.
    """
    home = Path(environ.get("HOME") or Path.home())
    if platform.startswith("win"):
        base = Path(environ.get("LOCALAPPDATA") or home / "AppData" / "Local") / "EnvelopeLab"
    elif platform == "darwin":
        base = home / "Library" / "Logs" / "EnvelopeLab"
    else:
        base = Path(environ.get("XDG_STATE_HOME") or home / ".local" / "state") / "envelopelab"
    return base / "crash.log"


def _version(package: str) -> str:
    try:
        return metadata.version(package)
    except metadata.PackageNotFoundError:
        return "not installed"


def environment_report(environ: Mapping[str, str] = os.environ) -> str:
    """Versions, operating system and display settings, one ``name: value`` per line."""
    lines = [
        f"python: {sys.version.split()[0]} ({sys.executable})",
        f"system: {platform_module.platform()}",
        f"WSL: {'yes' if sys.platform.startswith('linux') and is_wsl(dict(environ)) else 'no'}",
    ]
    lines += [f"{name}: {_version(name)}" for name in PACKAGES]
    lines += [f"{name}: {environ.get(name, '(not set)')}" for name in DISPLAY_VARIABLES]
    return "\n".join(lines)


def _excepthook(kind: type[BaseException], value: BaseException, tb: TracebackType | None) -> None:
    if _LOG is not None:
        _LOG.write(f"\n--- unhandled exception {datetime.now(UTC).isoformat()} ---\n")
        _LOG.write("".join(traceback.format_exception(kind, value, tb)))
        _LOG.flush()
    sys.__excepthook__(kind, value, tb)


def install_crash_log(path: Path | None = None, argv: list[str] | None = None) -> Path | None:
    """Start writing the crash log; returns its path (None when it cannot be written).

    The log keeps the last run only: it is started afresh with the environment report,
    then a segmentation fault or abort adds the Python stack of every thread and an
    unhandled exception its traceback.
    """
    global _LOG
    path = path or crash_log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        log = path.open("w", encoding="utf-8")
    except OSError:
        return None
    log.write(f"EnvelopeLab started {datetime.now(UTC).isoformat()}\n")
    log.write(f"arguments: {' '.join(argv or sys.argv)}\n")
    log.write(environment_report() + "\n")
    log.write("--- a crash below this line is the last thing EnvelopeLab did ---\n")
    log.flush()
    _LOG = log
    faulthandler.enable(file=log, all_threads=True)
    sys.excepthook = _excepthook
    return path


def opengl_report() -> str:
    """Create an OpenGL context the way the application does and name its renderer.

    Needs a QApplication. Returns one line per property, or why no context was made.
    """
    from PySide6.QtGui import QOffscreenSurface, QOpenGLContext

    context = QOpenGLContext()
    if not context.create():
        return "OpenGL: no context could be created"
    surface = QOffscreenSurface()
    surface.setFormat(context.format())
    surface.create()
    if not context.makeCurrent(surface):
        return "OpenGL: a context was created but could not be made current"
    functions: Any = context.functions()
    names = {"vendor": 0x1F00, "renderer": 0x1F01, "version": 0x1F02}
    lines = [f"OpenGL {key}: {functions.glGetString(code)}" for key, code in names.items()]
    context.doneCurrent()
    return "\n".join(lines)
