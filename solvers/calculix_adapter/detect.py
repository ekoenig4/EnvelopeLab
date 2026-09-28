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
_CANDIDATES = ("ccx", "ccx_2.22", "ccx_2.21", "ccx_2.20", "ccx.exe")

SETUP_MESSAGE = """\
CalculiX (ccx) was not found, so verification solves cannot run.

EnvelopeLab runs CalculiX as a separate program; nothing else in EnvelopeLab needs it.
Install the CalculiX solver (version 2.20 or newer) and make `ccx` available:

  Debian/Ubuntu:  sudo apt-get install calculix-ccx
  conda (any OS): conda install -c conda-forge calculix
  Windows/macOS:  the conda-forge package, or a build from www.calculix.de

Then either put `ccx` on PATH or set ENVELOPELAB_CCX to the executable's full path.
See docs/dev/calculix-installation.md for details."""


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
