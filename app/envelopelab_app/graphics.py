"""OpenGL set-up before the first window is created.

Under WSL (WSLg) the GPU-accelerated OpenGL driver draws the application window black,
while Mesa's software renderer (llvmpipe) draws it correctly. The launcher therefore
selects software OpenGL (``LIBGL_ALWAYS_SOFTWARE=1``) under WSL, unless the user set that
variable already or asked for hardware rendering (``--hardware-gl``). ``--software-gl``
selects it anywhere. Mesa reads the variable when the first OpenGL context is created, so
this must run before the QApplication and the 3D view exist.

The 3D view (VTK through pyvistaqt) renders into an X11 window on Linux. In a Wayland
session (WSLg is one) Qt 6 picks its Wayland platform, and the VTK render window then
crashes the application. The launcher therefore selects Qt's X11 platform (``xcb``,
through XWayland) when both a Wayland and an X server are present, unless the user chose a
platform (``QT_QPA_PLATFORM``).
"""

from __future__ import annotations

import sys
from collections.abc import MutableMapping
from pathlib import Path

SOFTWARE_GL = "LIBGL_ALWAYS_SOFTWARE"
QT_PLATFORM = "QT_QPA_PLATFORM"
PROC_VERSION = Path("/proc/version")


def is_wsl(environ: MutableMapping[str, str], proc_version: str | None = None) -> bool:
    """True inside the Windows Subsystem for Linux.

    Parameters
    ----------
    environ : mapping
        Process environment (``WSL_DISTRO_NAME`` / ``WSL_INTEROP`` are set by WSL).
    proc_version : str, optional
        Kernel version text; default the content of ``/proc/version``.
    """
    if environ.get("WSL_DISTRO_NAME") or environ.get("WSL_INTEROP"):
        return True
    if proc_version is None:
        try:
            proc_version = PROC_VERSION.read_text(encoding="utf-8", errors="replace")
        except OSError:
            proc_version = ""
    return "microsoft" in proc_version.lower()


def configure_graphics(
    environ: MutableMapping[str, str],
    software: bool = False,
    hardware: bool = False,
    platform: str = sys.platform,
    proc_version: str | None = None,
) -> str | None:
    """Select software OpenGL when requested or under WSL.

    Parameters
    ----------
    environ : mapping
        Environment to update (``os.environ`` in the launcher).
    software, hardware : bool
        The ``--software-gl`` / ``--hardware-gl`` options.
    platform : str
        ``sys.platform``.
    proc_version : str, optional
        Kernel version text (tests); default ``/proc/version``.

    Returns
    -------
    str or None
        Why software OpenGL was selected, or None when nothing was changed.
    """
    if SOFTWARE_GL in environ or hardware:
        return None
    if software:
        environ[SOFTWARE_GL] = "1"
        return "software OpenGL requested (--software-gl)"
    if platform.startswith("linux") and is_wsl(environ, proc_version):
        environ[SOFTWARE_GL] = "1"
        return (
            "WSL detected: using software OpenGL (the WSL GPU driver draws the window "
            "black); start with --hardware-gl to use the GPU"
        )
    return None


def select_qt_platform(
    environ: MutableMapping[str, str], platform: str = sys.platform
) -> str | None:
    """Select Qt's X11 platform in a Wayland session that also has an X server.

    Parameters
    ----------
    environ : mapping
        Environment to update (``os.environ`` in the launcher).
    platform : str
        ``sys.platform``.

    Returns
    -------
    str or None
        Why ``xcb`` was selected, or None when nothing was changed (a platform chosen by
        the user, no Wayland session, no X server, or not Linux).
    """
    if not platform.startswith("linux") or QT_PLATFORM in environ:
        return None
    if not environ.get("WAYLAND_DISPLAY") or not environ.get("DISPLAY"):
        return None
    environ[QT_PLATFORM] = "xcb"
    return (
        "Wayland session: using Qt's X11 platform (xcb), which the 3D view needs; set "
        "QT_QPA_PLATFORM to choose another"
    )
