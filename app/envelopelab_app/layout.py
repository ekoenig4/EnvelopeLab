"""Main-window layout: workflow modes, splitter sizes, and saving/restoring them.

The window shows one workflow mode at a time (a page of the mode stack) between an
always-visible sidebar (design tree, properties) and an always-visible Validation /
Warnings strip, so safety warnings are never hidden by the layout. Every resizable divider
is a named ``QSplitter``; the layout is the current mode plus each splitter's state, kept
in ``QSettings`` under ``layout/<slot>/``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QByteArray, QSettings
from PySide6.QtWidgets import QSplitter, QWidget

#: Bumped when the splitter structure changes, so older stored layouts are ignored.
LAYOUT_VERSION = 1

#: Settings slot written on close and read at start.
LAST_SLOT = "last"
#: Settings slot of View ▸ Save layout / Load saved layout.
SAVED_SLOT = "saved"

#: Workflow modes, in tab order: (key, tab label).
MODES: tuple[tuple[str, str], ...] = (
    ("shape", "Shape"),
    ("patterns", "Patterns"),
    ("rigging", "Rigging"),
    ("shapes", "Special shapes"),
    ("simulate", "3D / Simulation"),
    ("history", "History"),
)
MODE_KEYS = tuple(key for key, _ in MODES)

#: Default sizes of every named splitter, px. Qt scales them to the space available, so
#: only their ratios matter.
DEFAULT_SIZES: dict[str, tuple[int, ...]] = {
    "outerSplitter": (800, 140),  # workspace above the Validation / Warnings strip
    "sideSplitter": (340, 1100),  # sidebar beside the mode pages
    "sidebarSplitter": (260, 540),  # design tree above properties
    "goreEditorSplitter": (600, 400),  # profile canvas beside its tables
    "patternsModeSplitter": (850, 350),  # pattern view beside materials
    "patternPanelSplitter": (700, 250),  # pattern drawing above its row form
    "simulateSplitter": (620, 220),  # 3D view above the runs table
    "shapesSplitter": (520, 560),  # shape list and parameters beside checks and pieces
}


@dataclass
class LayoutState:
    """A stored layout.

    Attributes
    ----------
    mode : str
        Key of the visible workflow mode (one of ``MODE_KEYS``).
    splitters : dict of str to QByteArray
        ``QSplitter.saveState()`` of each named splitter.
    geometry : QByteArray
        ``QMainWindow.saveGeometry()`` (window size and position); empty if not stored.
    """

    mode: str = MODE_KEYS[0]
    splitters: dict[str, QByteArray] = field(default_factory=dict)
    geometry: QByteArray = field(default_factory=QByteArray)


def named_splitters(root: QWidget) -> dict[str, QSplitter]:
    """The splitters under ``root`` that take part in the layout."""
    found = {s.objectName(): s for s in root.findChildren(QSplitter)}
    return {name: found[name] for name in DEFAULT_SIZES if name in found}


def capture(root: QWidget, mode: str, geometry: QByteArray | None = None) -> LayoutState:
    """The current layout of the window ``root``."""
    splitters = {name: s.saveState() for name, s in named_splitters(root).items()}
    return LayoutState(mode, splitters, geometry if geometry is not None else QByteArray())


def apply_splitters(root: QWidget, state: LayoutState) -> None:
    """Restore the stored splitter states; splitters without one keep their sizes."""
    for name, splitter in named_splitters(root).items():
        data = state.splitters.get(name)
        if data is not None and not data.isEmpty():
            splitter.restoreState(data)


def apply_defaults(root: QWidget) -> None:
    """Set every named splitter to its default sizes."""
    for name, splitter in named_splitters(root).items():
        splitter.setSizes(list(DEFAULT_SIZES[name]))


def store(settings: QSettings, slot: str, state: LayoutState) -> None:
    """Write ``state`` to ``settings`` under ``layout/<slot>/``."""
    settings.remove(f"layout/{slot}")
    settings.beginGroup(f"layout/{slot}")
    settings.setValue("version", LAYOUT_VERSION)
    settings.setValue("mode", state.mode)
    settings.setValue("geometry", state.geometry)
    for name, data in state.splitters.items():
        settings.setValue(f"splitters/{name}", data)
    settings.endGroup()
    settings.sync()


def load(settings: QSettings, slot: str) -> LayoutState | None:
    """The layout stored under ``layout/<slot>/``, or None if absent, of an older layout
    version or unreadable."""
    settings.beginGroup(f"layout/{slot}")
    try:
        try:
            version = int(str(settings.value("version", -1)))
        except ValueError:
            return None
        if version != LAYOUT_VERSION:
            return None
        mode = str(settings.value("mode", MODE_KEYS[0]))
        geometry = settings.value("geometry")
        splitters: dict[str, QByteArray] = {}
        for name in DEFAULT_SIZES:
            data = settings.value(f"splitters/{name}")
            if isinstance(data, QByteArray):
                splitters[name] = data
    finally:
        settings.endGroup()
    return LayoutState(
        mode if mode in MODE_KEYS else MODE_KEYS[0],
        splitters,
        geometry if isinstance(geometry, QByteArray) else QByteArray(),
    )


__all__ = [
    "DEFAULT_SIZES",
    "LAST_SLOT",
    "LAYOUT_VERSION",
    "MODES",
    "MODE_KEYS",
    "SAVED_SLOT",
    "LayoutState",
    "apply_defaults",
    "apply_splitters",
    "capture",
    "load",
    "named_splitters",
    "store",
]
