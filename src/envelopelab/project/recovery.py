"""Autosave files and crash recovery.

While a project has unsaved changes the application writes an *autosave file* to a
recovery directory every few minutes (format ``envelopelab.autosave`` version 1: the
project data plus where it came from). A clean exit or an explicit save removes it, so an
autosave file that is still there at the next start belongs to a session that ended
without saving (a crash or a killed process) and is offered for recovery.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from envelopelab.project.model import (
    Project,
    dump_project,
    load_project_text,
    utc_now,
)

AUTOSAVE_FORMAT = "envelopelab.autosave"
AUTOSAVE_SUFFIX = ".elautosave"


@dataclass(frozen=True)
class RecoveryItem:
    """An autosave file left by a session that did not end cleanly.

    Attributes
    ----------
    autosave_path : Path
        The autosave file.
    original_path : Path, optional
        Project file it belongs to (None for a never-saved project).
    saved : datetime
        When it was written (UTC).
    name : str
        Design name.
    pid : int
        Process that wrote it.
    """

    autosave_path: Path
    original_path: Path | None
    saved: datetime
    name: str
    pid: int


def autosave_file(recovery_dir: str | Path, session_id: str) -> Path:
    """Autosave file of one application session."""
    return Path(recovery_dir) / f"{session_id}{AUTOSAVE_SUFFIX}"


def write_autosave(project: Project, target: str | Path, original_path: str | Path | None) -> Path:
    """Write an autosave file atomically.

    Parameters
    ----------
    project : Project
        Project to save.
    target : str or Path
        Autosave file (see :func:`autosave_file`).
    original_path : str or Path, optional
        Project file the autosave belongs to.

    Returns
    -------
    Path
        ``target``.
    """
    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    wrapper = {
        "format": AUTOSAVE_FORMAT,
        "format_version": 1,
        "saved": utc_now().isoformat(),
        "pid": os.getpid(),
        "original_path": None if original_path is None else str(original_path),
        "project": json.loads(dump_project(project)),
    }
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(wrapper, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(path)
    return path


def read_autosave(path: str | Path) -> tuple[Project, Path | None]:
    """Project and original path stored in an autosave file."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if raw.get("format") != AUTOSAVE_FORMAT:
        raise ValueError(f"{path}: not an EnvelopeLab autosave file")
    original = raw.get("original_path")
    project = load_project_text(json.dumps(raw["project"]))
    return project, None if original is None else Path(original)


def find_recoverable(recovery_dir: str | Path, exclude: Path | None = None) -> list[RecoveryItem]:
    """Autosave files in ``recovery_dir`` (newest first), except ``exclude``.

    Unreadable files are skipped (they are reported by :func:`read_autosave` when opened).
    """
    folder = Path(recovery_dir)
    if not folder.is_dir():
        return []
    items: list[RecoveryItem] = []
    for path in folder.glob(f"*{AUTOSAVE_SUFFIX}"):
        if exclude is not None and path.resolve() == exclude.resolve():
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if raw.get("format") != AUTOSAVE_FORMAT:
                continue
            original = raw.get("original_path")
            items.append(
                RecoveryItem(
                    autosave_path=path,
                    original_path=None if original is None else Path(original),
                    saved=datetime.fromisoformat(raw["saved"]),
                    name=str(raw["project"]["state"]["design"]["meta"]["name"]),
                    pid=int(raw.get("pid", 0)),
                )
            )
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return sorted(items, key=lambda item: item.saved, reverse=True)


def discard(path: str | Path) -> None:
    """Remove an autosave file (missing files are ignored)."""
    Path(path).unlink(missing_ok=True)
