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


#: Windows exit code of a program that cannot start because a DLL it needs is missing
#: (STATUS_DLL_NOT_FOUND, 0xC0000135).
_DLL_NOT_FOUND = 0xC0000135


@dataclass(frozen=True)
class CalculixCheck:
    """One place EnvelopeLab looked for ``ccx``, and what it found there.

    Attributes
    ----------
    source : str
        Where the path came from, e.g. ``"ENVELOPELAB_CCX"`` or ``"PATH (ccx)"``.
    path : str
        Path as given (before cleaning).
    executable : Path or None
        The program that was run, None when there was none to run.
    version : str or None
        Version it reported; None when it was not accepted.
    reason : str
        Why it was not accepted (empty when it was).
    """

    source: str
    path: str
    executable: Path | None
    version: str | None
    reason: str = ""


def _run_version(executable: Path) -> tuple[str | None, str]:
    """(version, reason): ``ccx -v`` must print "Version x.y"."""
    try:
        result = subprocess.run(
            [str(executable), "-v"], capture_output=True, text=True, timeout=30, check=False
        )
    except subprocess.TimeoutExpired:
        return None, "did not finish 'ccx -v' within 30 s"
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"could not be started: {exc}"
    output = (result.stdout + result.stderr).strip()
    match = re.search(r"Version\s+([0-9][0-9.]*)", output)
    if match:
        return match.group(1), ""
    code = result.returncode
    reason = f"ran but printed no version (exit code {code}"
    if code & 0xFFFFFFFF == _DLL_NOT_FOUND:
        reason += ": a DLL it needs is missing; use ccx_static.exe or keep its DLLs beside it"
    reason += ")"
    if output:
        reason += f"; it said: {output.splitlines()[0][:200]}"
    return None, reason


def _version(executable: Path) -> str | None:
    return _run_version(executable)[0]


def _clean(value: str) -> str:
    """A path as typed by a person: surrounding quotes and spaces removed, ``~`` and
    environment variables expanded (``%ProgramFiles%`` on Windows, ``$HOME``)."""
    value = value.strip().strip('"').strip("'").strip()
    return os.path.expanduser(os.path.expandvars(value))


def _check(source: str, value: str) -> CalculixCheck:
    path = Path(_clean(value))
    if path.is_dir():
        inside = [path / f"{name}{suffix}" for name in _CANDIDATES for suffix in ("", ".exe")]
        found = next((p for p in inside if p.is_file()), None)
        if found is None:
            return CalculixCheck(source, value, None, None, "is a folder without a ccx program")
        path = found
    if not path.is_file():
        reason = "does not exist"
        if not path.is_absolute():
            reason += " (a relative path: give the full path, e.g. C:\\CalculiX\\ccx_static.exe)"
        return CalculixCheck(source, value, None, None, reason)
    version, reason = _run_version(path)
    return CalculixCheck(source, value, path.resolve(), version, reason)


def check_calculix(explicit: str | Path | None = None) -> list[CalculixCheck]:
    """Every place EnvelopeLab looks for ``ccx``, in order, with the result for each.

    The order is ``explicit`` (the app's preference), ``$ENVELOPELAB_CCX``, then the names
    in ``_CANDIDATES`` on ``PATH``. A path may be quoted, use ``~`` or environment
    variables, or name the folder that holds the program.
    """
    checks: list[CalculixCheck] = []
    if explicit is not None and str(explicit).strip():
        checks.append(_check("preference / explicit path", str(explicit)))
    if os.environ.get(ENV_VAR, "").strip():
        checks.append(_check(ENV_VAR, os.environ[ENV_VAR]))
    seen: set[Path | None] = {c.executable for c in checks if c.executable is not None}
    for name in _CANDIDATES:
        found = shutil.which(name)
        if found and Path(found).resolve() not in seen:
            check = _check(f"PATH ({name})", found)
            seen.add(check.executable)
            checks.append(check)
    if not any(c.source.startswith("PATH") for c in checks):
        checks.append(CalculixCheck("PATH", "", None, None, "no ccx program on PATH"))
    return checks


def find_calculix(explicit: str | Path | None = None) -> CalculixInstallation | None:
    """Find ``ccx``: ``explicit`` path, then ``$ENVELOPELAB_CCX``, then ``PATH``.

    The first program that reports its version is used. A path that does not work does
    not stop the search: :func:`calculix_report` says why it was passed over.

    Parameters
    ----------
    explicit : str or Path, optional
        Executable (or the folder that holds it) to try first.

    Returns
    -------
    CalculixInstallation or None
        None when no working ``ccx`` is found.
    """
    for check in check_calculix(explicit):
        if check.version is not None and check.executable is not None:
            return CalculixInstallation(check.executable, check.version)
    return None


def calculix_report(explicit: str | Path | None = None) -> str:
    """Plain-text report of where ``ccx`` was looked for and why each place failed."""
    lines = ["Where EnvelopeLab looked for CalculiX (ccx), in order:"]
    used = False
    for check in check_calculix(explicit):
        where = f"  {check.source}: {check.path}" if check.path else f"  {check.source}"
        if check.version is not None and not used:
            used = True
            lines.append(f"{where}\n    -> CalculiX {check.version}, used")
        elif check.version is not None:
            lines.append(f"{where}\n    -> CalculiX {check.version} (not used: found earlier)")
        else:
            lines.append(f"{where}\n    -> {check.reason}")
    if not used:
        lines.append("No working ccx was found.")
    return "\n".join(lines)


def require_calculix(explicit: str | Path | None = None) -> CalculixInstallation:
    """Like :func:`find_calculix` but raise :class:`CalculixNotFoundError` with setup help."""
    found = find_calculix(explicit)
    if found is None:
        raise CalculixNotFoundError(SETUP_MESSAGE)
    return found
