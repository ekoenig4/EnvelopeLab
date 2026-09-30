"""Application preferences and recent projects, stored with QSettings."""

from __future__ import annotations

import os
from dataclasses import dataclass, fields
from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths

MAX_RECENT = 10


@dataclass
class Preferences:
    """User preferences (units noted per field; boundary values, not engineering data).

    Attributes
    ----------
    autosave_minutes : float
        Autosave interval, min (0 disables autosave).
    preview_mesh_mm : float
        Target mesh edge length of preview solves, mm.
    calculix_mesh_mm : float
        Target mesh edge length of CalculiX solves, mm.
    ccx_path : str
        CalculiX executable; empty: ``$ENVELOPELAB_CCX`` or ``PATH``.
    auto_regenerate_patterns : bool
        Regenerate the flat patterns after every edit (otherwise they are marked stale
        until *Regenerate* is pressed).
    keep_rows_fitted : bool
        Rescale the panel rows to the meridian after profile edits.
    enable_3d : bool
        Use the PyVista 3D view (needs OpenGL; takes effect at the next start).
    recovery_dir : str
        Directory for autosave files; empty: the platform's application data folder.
    material_library : str
        Fabric library file shared by all designs; empty: ``$ENVELOPELAB_MATERIAL_LIBRARY``
        or ``materials.sqlite`` in the application data folder (takes effect at the next
        start).
    """

    autosave_minutes: float = 2.0
    preview_mesh_mm: float = 800.0
    calculix_mesh_mm: float = 800.0
    ccx_path: str = ""
    auto_regenerate_patterns: bool = False
    keep_rows_fitted: bool = True
    enable_3d: bool = True
    recovery_dir: str = ""
    material_library: str = ""

    def resolved_recovery_dir(self) -> Path:
        """Autosave directory."""
        if self.recovery_dir:
            return Path(self.recovery_dir)
        env = os.environ.get("ENVELOPELAB_RECOVERY_DIR")
        if env:
            return Path(env)
        return app_data_dir() / "recovery"

    def resolved_material_library(self) -> Path:
        """Fabric library file shared by all designs."""
        if self.material_library:
            return Path(self.material_library)
        env = os.environ.get("ENVELOPELAB_MATERIAL_LIBRARY")
        if env:
            return Path(env)
        return app_data_dir() / "materials.sqlite"


def app_data_dir() -> Path:
    """The platform's application data folder (``~/.envelopelab`` if Qt knows none)."""
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    return Path(base or Path.home() / ".envelopelab")


def _to_bool(value: object) -> bool:
    if isinstance(value, str):
        return value.lower() in ("1", "true", "yes")
    return bool(value)


def load_preferences(settings: QSettings) -> Preferences:
    """Preferences stored in ``settings`` (defaults for missing keys)."""
    prefs = Preferences()
    for f in fields(Preferences):
        key = f"preferences/{f.name}"
        if not settings.contains(key):
            continue
        raw = settings.value(key)
        default = getattr(prefs, f.name)
        if isinstance(default, bool):
            setattr(prefs, f.name, _to_bool(raw))
        elif isinstance(default, float):
            setattr(prefs, f.name, float(str(raw)))
        else:
            setattr(prefs, f.name, str(raw))
    return prefs


def save_preferences(settings: QSettings, prefs: Preferences) -> None:
    """Store ``prefs``."""
    for f in fields(Preferences):
        settings.setValue(f"preferences/{f.name}", getattr(prefs, f.name))
    settings.sync()


def recent_projects(settings: QSettings) -> list[Path]:
    """Recently opened project files, newest first."""
    raw = settings.value("recent/projects", [])
    if isinstance(raw, str):
        items: list[object] = [raw]
    elif isinstance(raw, (list, tuple)):
        items = list(raw)
    else:
        items = []
    return [Path(str(p)) for p in items if str(p)]


def add_recent_project(settings: QSettings, path: Path) -> list[Path]:
    """Move ``path`` to the top of the recent list."""
    resolved = path.resolve()
    items = [p for p in recent_projects(settings) if p.resolve() != resolved]
    items.insert(0, resolved)
    items = items[:MAX_RECENT]
    settings.setValue("recent/projects", [str(p) for p in items])
    settings.sync()
    return items
