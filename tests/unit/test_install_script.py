"""The environment install script and the installation guide list the same packages."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "install_env.sh"
GUIDE = ROOT / "docs" / "user" / "installation.md"
MANAGERS = ("APT", "DNF", "PACMAN", "ZYPPER")
GROUPS = ("GMSH", "QT", "CALCULIX", "XVFB")


def script_lists() -> dict[str, list[str]]:
    text = SCRIPT.read_text(encoding="utf-8")
    return {
        m.group(1): m.group(2).split()
        for m in re.finditer(r'^([A-Z]+_[A-Z]+)="([^"]*)"', text, flags=re.MULTILINE)
    }


def test_every_package_manager_has_every_group() -> None:
    lists = script_lists()
    for manager in MANAGERS:
        for group in (*GROUPS, "PYTHON", "REGISTRATION"):
            assert f"{manager}_{group}" in lists, f"{manager}_{group} missing"


def test_guide_lists_the_same_packages_as_the_script() -> None:
    guide = GUIDE.read_text(encoding="utf-8")
    lists = script_lists()
    for manager in MANAGERS:
        for group in GROUPS:
            packages = lists[f"{manager}_{group}"]
            if packages:
                assert f"`{' '.join(packages)}`" in guide, (manager, group)
    assert f"`{' '.join(lists['APT_PYTHON'])}`" in guide


def test_dry_run_prints_the_install_commands() -> None:
    if os.name != "posix":  # the script targets Linux containers (bash); checked on POSIX
        return
    out = subprocess.run(
        [
            "bash",
            str(SCRIPT),
            "--dry-run",
            "--package-manager",
            "apt",
            "--venv",
            "/tmp/envelopelab-test-venv",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    qt = " ".join(script_lists()["APT_QT"])
    assert f"apt-get install -y --no-install-recommends {qt}" in out
    assert "calculix-ccx" in out and "xvfb" in out
    assert "-m pip install -e .[dev,docs,gui,fast]" in out
    minimal = subprocess.run(
        ["bash", str(SCRIPT), "--dry-run", "--no-system", "--extras", "gui", "--venv", "none"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "apt-get" not in minimal and "-m pip install -e .[gui]" in minimal


WINDOWS_SCRIPT = ROOT / "scripts" / "install_env.ps1"
WINDOWS_WRAPPER = ROOT / "scripts" / "install_env.cmd"


def test_windows_wrapper_bypasses_the_execution_policy_for_the_script() -> None:
    wrapper = WINDOWS_WRAPPER.read_text(encoding="utf-8")
    assert "-ExecutionPolicy Bypass" in wrapper and "install_env.ps1" in wrapper


def test_windows_script_dry_run_prints_the_install_commands(tmp_path: Path) -> None:
    pwsh = shutil.which("pwsh") or shutil.which("powershell")
    if pwsh is None:
        pytest.skip("PowerShell is not installed")
    venv = tmp_path / "venv"
    out = subprocess.run(
        [pwsh, "-NoProfile", "-File", str(WINDOWS_SCRIPT), "-DryRun", "-Venv", str(venv)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert f"-m venv {venv}" in out
    assert "-m pip install -e .[gui,fast]" in out
    dev = subprocess.run(
        [pwsh, "-NoProfile", "-File", str(WINDOWS_SCRIPT), "-DryRun", "-Dev", "-Venv", str(venv)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "-m pip install -e .[dev,docs,gui,fast]" in dev
