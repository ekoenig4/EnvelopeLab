"""Locate the CalculiX ``ccx`` executable and read its version."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

#: Environment variable that points at a specific ``ccx`` executable.
ENV_VAR = "ENVELOPELAB_CCX"
# Names the executable has: distribution packages (ccx, ccx_2.2x) and the Windows builds
# from the CalculiX site (ccx_static.exe, ccx_dynamic.exe). shutil.which adds ".exe" on
# Windows.
_CANDIDATES = (
    "ccx",
    "ccx_2.23",
    "ccx_2.22",
    "ccx_2.21",
    "ccx_2.20",
    "ccx_static",
    "ccx_dynamic",
    "ccx.exe",
)

SETUP_MESSAGE = """\
CalculiX (ccx) was not found, so verification solves cannot run.

EnvelopeLab runs CalculiX as a separate program; nothing else in EnvelopeLab needs it.
Install the CalculiX solver (version 2.20 or newer) and make `ccx` available:

  Debian/Ubuntu:  sudo apt-get install calculix-ccx
  Windows:        download calculix_2.23_4win.zip (or 2.22) from www.dhondt.de and
                  unzip it, e.g. to C:\\CalculiX
  conda (any OS): conda install -c conda-forge calculix

Then give EnvelopeLab the executable (ccx, ccx.exe or ccx_static.exe): in the app,
File > Preferences > CalculiX executable; or set ENVELOPELAB_CCX to its full path;
or put its folder on PATH. See docs/dev/calculix-installation.md for details."""


class CalculixNotFoundError(RuntimeError):
    """Raised when a verification solve is requested but ``ccx`` is unavailable."""


@dataclass(frozen=True)
class CalculixInstallation:
    """A usable ``ccx`` executable.

    Attributes
    ----------
    executable : Path
        Full path of ``ccx``.
    version : str
        Version reported by ``ccx -v`` (e.g. ``2.21``).
    """

    executable: Path
    version: str


def _version(executable: Path) -> str | None:
    try:
        result = subprocess.run(
            [str(executable), "-v"], capture_output=True, text=True, timeout=30, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r"Version\s+([0-9][0-9.]*)", result.stdout + result.stderr)
    return match.group(1) if match else None


def find_calculix(explicit: str | Path | None = None) -> CalculixInstallation | None:
    """Find ``ccx``: ``explicit`` path, then ``$ENVELOPELAB_CCX``, then ``PATH``.

    Parameters
    ----------
    explicit : str or Path, optional
        Executable to use.

    Returns
    -------
    CalculixInstallation or None
        None when no working ``ccx`` is found.
    """
    candidates: list[str] = []
    if explicit is not None:
        candidates.append(str(explicit))
    elif os.environ.get(ENV_VAR):
        candidates.append(os.environ[ENV_VAR])
    else:
        candidates += [p for name in _CANDIDATES if (p := shutil.which(name))]
    for candidate in candidates:
        path = Path(candidate)
        if not path.is_file():
            continue
        version = _version(path)
        if version is not None:
            return CalculixInstallation(path.resolve(), version)
    return None


def require_calculix(explicit: str | Path | None = None) -> CalculixInstallation:
    """Like :func:`find_calculix` but raise :class:`CalculixNotFoundError` with setup help."""
    found = find_calculix(explicit)
    if found is None:
        raise CalculixNotFoundError(SETUP_MESSAGE)
    return found
