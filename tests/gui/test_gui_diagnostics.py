"""Crash log and environment report (envelopelab --diagnose)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from envelopelab_app.diagnostics import crash_log_path, environment_report


def test_crash_log_lives_in_the_users_state_folder() -> None:
    linux = crash_log_path({"HOME": "/home/u"}, platform="linux")
    assert linux == Path("/home/u/.local/state/envelopelab/crash.log")
    xdg = crash_log_path({"HOME": "/home/u", "XDG_STATE_HOME": "/s"}, platform="linux")
    assert xdg == Path("/s/envelopelab/crash.log")
    win = crash_log_path({"LOCALAPPDATA": "C:/Users/u/AppData/Local"}, platform="win32")
    assert win == Path("C:/Users/u/AppData/Local/EnvelopeLab/crash.log")
    mac = crash_log_path({"HOME": "/Users/u"}, platform="darwin")
    assert mac == Path("/Users/u/Library/Logs/EnvelopeLab/crash.log")


def test_report_names_versions_and_display_settings() -> None:
    report = environment_report({"WAYLAND_DISPLAY": "wayland-0", "DISPLAY": ":0"})
    for line in ("PySide6: ", "vtk: ", "WAYLAND_DISPLAY: wayland-0", "DISPLAY: :0"):
        assert line in report
    assert "LIBGL_ALWAYS_SOFTWARE: (not set)" in report


@pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX segmentation fault signal")
def test_a_segmentation_fault_leaves_the_python_stack_in_the_log(tmp_path: Path) -> None:
    log = tmp_path / "crash.log"
    code = (
        "import ctypes, pathlib\n"
        "from envelopelab_app.diagnostics import install_crash_log\n"
        f"install_crash_log(pathlib.Path({str(log)!r}), ['envelopelab'])\n"
        "def crash_here():\n"
        "    ctypes.string_at(0)\n"
        "crash_here()\n"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, check=False)
    assert done.returncode != 0
    text = log.read_text(encoding="utf-8")
    assert "PySide6: " in text and "Segmentation fault" in text and "crash_here" in text


def test_an_unhandled_exception_is_logged(tmp_path: Path) -> None:
    log = tmp_path / "crash.log"
    code = (
        "import pathlib\n"
        "from envelopelab_app.diagnostics import install_crash_log\n"
        f"install_crash_log(pathlib.Path({str(log)!r}), ['envelopelab'])\n"
        "raise RuntimeError('boom in a slot')\n"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, check=False)
    assert done.returncode != 0
    text = log.read_text(encoding="utf-8")
    assert "unhandled exception" in text and "boom in a slot" in text
