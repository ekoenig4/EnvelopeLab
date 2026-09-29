"""The environment install script and the installation guide list the same packages."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

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
    assert "-m pip install -e .[dev,docs,gui]" in out
    minimal = subprocess.run(
        ["bash", str(SCRIPT), "--dry-run", "--no-system", "--extras", "gui", "--venv", "none"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "apt-get" not in minimal and "-m pip install -e .[gui]" in minimal
