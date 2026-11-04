"""Shared look of the desktop application: colour tokens, the style sheet and status widgets.

Every window takes its colours from :data:`TOKENS` and shows the state of a result with
the same :class:`StatusBanner` and :class:`StatusChip`, so a stale, unconverged or failing
result looks the same wherever it appears. A status is never told by colour alone: each
one has its own symbol and its own words (the banner title and the chip text).

The style sheet (:func:`stylesheet`) is applied once to the whole application by
:func:`apply_theme`. It only styles object names and properties it sets itself
(``statusBanner``, ``statusChip``, ``toolRail``, ``sidePanel``, ``card``), plus plain
neutral defaults, so widgets that set their own style sheet keep it.

The same look on every platform: :func:`apply_theme` also selects Qt's Fusion style and a
light palette built from :data:`TOKENS` (so a dark system theme or the platform's native
style cannot leave the style sheet's light colours on dark controls). Where the system
font is only a generic fallback (DejaVu Sans, as under WSL without a desktop), it picks the
first installed font of :data:`PREFERRED_FONTS`; under WSL it first loads Segoe UI from the
Windows installation, so the application reads as it does on Windows. A status symbol that
no installed font can draw is replaced by an ASCII one (:data:`ASCII_SYMBOLS`), so a
status is never shown as an empty box.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontInfo, QFontMetrics, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStyleFactory,
    QWidget,
)

from envelopelab_app.graphics import is_wsl

#: Colour tokens by role (hex). Text on each background has a contrast of at least 4.5:1.
TOKENS = {
    "ink": "#1f2933",
    "muted": "#4b5563",
    "surface": "#ffffff",
    "panel": "#f7f8fa",
    "viewport": "#eef1f4",
    "border": "#cfd5dc",
    "control_border": "#c5ccd5",
    "hover": "#eef2f6",
    "accent": "#1d5fb4",
    "accent_text": "#ffffff",
    "selected": "#e3edf8",
}


@dataclass(frozen=True)
class StatusStyle:
    """Look of one result status.

    Attributes
    ----------
    symbol : str
        Symbol shown before the text (so the status does not rely on colour).
    background, border, text : str
        Banner colours (hex).
    chip_background, chip_text : str
        Chip colours (hex).
    """

    symbol: str
    background: str
    border: str
    text: str
    chip_background: str
    chip_text: str


#: Result statuses, worst last: ``ok`` (current and converged, verified), ``info``
#: (current and converged, not yet verified), ``stale`` (from another design state),
#: ``fail`` (a limit exceeded: factor of safety, temperature) and ``error`` (not converged:
#: values are not final).
STATUS_STYLES = {
    "ok": StatusStyle("✓", "#e9f2fb", "#1d5fb4", "#0f2f57", "#dcebdc", "#14532d"),
    "info": StatusStyle("i", "#e9f2fb", "#1d5fb4", "#0f2f57", "#dcebdc", "#14532d"),
    "stale": StatusStyle("◷", "#eceff3", "#6b7280", "#1f2933", "#e5e7eb", "#374151"),
    "fail": StatusStyle("▲", "#fff1e6", "#d9480f", "#6b2504", "#fde4d3", "#7c2d12"),
    "error": StatusStyle("✕", "#fdecec", "#b42318", "#6e1610", "#fbd5d2", "#7a1a12"),
}
#: Status symbols used when no installed font can draw the usual one (one per status, so a
#: status is still not told by colour alone).
ASCII_SYMBOLS = {"ok": "+", "info": "i", "stale": "~", "fail": "!", "error": "x"}
#: Order of severity (a list of statuses shows the worst first).
STATUS_ORDER = ("ok", "info", "stale", "fail", "error")
#: Colour of values below a limit (factor of safety, temperature) in the 3D view.
FAIL_COLOR = "#e8590c"


def worst(kinds: list[str]) -> str | None:
    """The most severe status of ``kinds`` (None for an empty list)."""
    known = [k for k in kinds if k in STATUS_STYLES]
    return max(known, key=STATUS_ORDER.index) if known else None


def stylesheet() -> str:
    """The application style sheet (see the module docstring for what it covers)."""
    t = TOKENS
    parts = [
        f"QWidget#sidePanel {{ background: {t['panel']}; }}",
        f"QFrame#card {{ background: {t['surface']}; border: 1px solid {t['border']};"
        " border-radius: 8px; }",
        "QLabel#cardTitle { font-weight: 600; }",
        f"QLabel[role='muted'] {{ color: {t['muted']}; }}",
        f"QWidget#toolRail {{ background: {t['surface']}; border: 1px solid {t['border']};"
        " border-radius: 8px; }",
        # A visible frame: without the platform's button look, words alone do not read
        # as buttons (WSL screenshot).
        f"QWidget#toolRail QToolButton {{ min-width: 40px; min-height: 40px;"
        f" background: {t['surface']}; border: 1px solid {t['control_border']};"
        " border-radius: 6px; padding: 2px 6px; }",
        f"QWidget#toolRail QToolButton:hover {{ background: {t['hover']}; }}",
        f"QWidget#toolRail QToolButton:checked {{ background: {t['accent']};"
        f" color: {t['accent_text']}; }}",
        f"QWidget#panelToolbar {{ background: {t['panel']};"
        f" border-bottom: 1px solid {t['border']}; }}",
        f"QPushButton#primaryAction {{ background: {t['accent']}; color: {t['accent_text']};"
        f" border: 1px solid {t['accent']}; border-radius: 4px; padding: 3px 12px;"
        " font-weight: 600; }",
        "QPushButton#primaryAction:disabled { background: #9db6d6; border-color: #9db6d6; }",
        f"QLabel#emptyState {{ color: {t['muted']}; padding: 24px; }}",
        f"QWidget#sidePanel QGroupBox {{ background: {t['surface']};"
        f" border: 1px solid {t['border']}; border-radius: 8px; margin-top: 14px;"
        " padding: 8px 6px 6px 6px; }",
        "QWidget#sidePanel QGroupBox::title { subcontrol-origin: margin; left: 10px;"
        " padding: 0 4px; font-weight: 600; }",
        f"QLabel[role='figure'] {{ color: {t['ink']}; padding: 0 6px; }}",
        f"QWidget#panelToolbar QToolButton:unchecked {{ background: {t['surface']};"
        f" border: 1px solid {t['control_border']}; border-radius: 4px; padding: 2px 8px;"
        f" color: {t['muted']}; }}",
        f"QWidget#panelToolbar QToolButton:checked {{ background: {t['selected']};"
        f" border: 1px solid {t['accent']}; border-radius: 4px; padding: 2px 8px;"
        f" color: {t['ink']}; font-weight: 600; }}",
        f"QWidget#cameraBar {{ background: {t['panel']}; border-top: 1px solid {t['border']}; }}",
    ]
    for kind, s in STATUS_STYLES.items():
        parts.append(
            f"QFrame#statusBanner[status='{kind}'] {{ background: {s.background};"
            f" border-bottom: 2px solid {s.border}; }}"
            f" QFrame#statusBanner[status='{kind}'] QLabel {{ color: {s.text}; }}"
        )
        parts.append(
            f"QLabel#statusChip[status='{kind}'] {{ background: {s.chip_background};"
            f" color: {s.chip_text}; border-radius: 8px; padding: 1px 8px;"
            " font-size: 11px; font-weight: 600; }"
        )
    return "\n".join(parts)


def text_style(kind: str) -> str:
    """Style sheet for a plain label stating ``kind`` (a key of :data:`STATUS_STYLES`):
    the status's text colour, semibold. Empty for ``ok`` and ``info``."""
    if kind in ("ok", "info"):
        return ""
    return f"color: {STATUS_STYLES[kind].chip_text}; font-weight: 600;"


#: Qt style used on every platform (the style sheet is written for it).
STYLE = "Fusion"
#: Interface fonts in order of preference, used where the system font is a generic fallback.
PREFERRED_FONTS = ("Segoe UI", "Noto Sans", "Inter", "Cantarell", "Ubuntu")
#: System fonts that mean "no interface font was configured" (WSL, bare X servers).
GENERIC_FONTS = ("Sans Serif", "DejaVu Sans", "Bitstream Vera Sans")
#: Fonts directory of the Windows installation as WSL mounts it.
WINDOWS_FONT_DIR = Path("/mnt/c/Windows/Fonts")
#: Segoe UI files loaded under WSL (regular, bold, semibold, symbols).
WINDOWS_FONT_FILES = ("segoeui.ttf", "segoeuib.ttf", "seguisb.ttf", "seguisym.ttf")


def palette() -> QPalette:
    """The light palette of the shared look, built from :data:`TOKENS`."""
    t = TOKENS
    pal = QPalette()
    roles = {
        QPalette.ColorRole.Window: t["panel"],
        QPalette.ColorRole.WindowText: t["ink"],
        QPalette.ColorRole.Base: t["surface"],
        QPalette.ColorRole.AlternateBase: t["panel"],
        QPalette.ColorRole.Text: t["ink"],
        QPalette.ColorRole.PlaceholderText: t["muted"],
        QPalette.ColorRole.Button: "#f3f5f8",
        QPalette.ColorRole.ButtonText: t["ink"],
        QPalette.ColorRole.BrightText: t["accent_text"],
        QPalette.ColorRole.Highlight: t["accent"],
        QPalette.ColorRole.HighlightedText: t["accent_text"],
        QPalette.ColorRole.ToolTipBase: t["surface"],
        QPalette.ColorRole.ToolTipText: t["ink"],
        QPalette.ColorRole.Link: t["accent"],
        QPalette.ColorRole.Light: t["surface"],
        QPalette.ColorRole.Midlight: t["hover"],
        QPalette.ColorRole.Mid: t["control_border"],
        QPalette.ColorRole.Dark: "#8a949f",
        QPalette.ColorRole.Shadow: "#5b6470",
    }
    for role, colour in roles.items():
        pal.setColor(role, QColor(colour))
    disabled = QPalette.ColorGroup.Disabled
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        pal.setColor(disabled, role, QColor("#9aa3ad"))
    pal.setColor(disabled, QPalette.ColorRole.Highlight, QColor("#9db6d6"))
    return pal


def load_windows_fonts(font_dir: Path = WINDOWS_FONT_DIR) -> list[str]:
    """Load Segoe UI from a Windows installation (under WSL) for this process only.

    The fonts are read from the user's own Windows installation and registered with Qt
    for this run; nothing is copied or installed.

    Parameters
    ----------
    font_dir : Path
        The Windows fonts directory (default as WSL mounts drive C:).

    Returns
    -------
    list of str
        The font families that were loaded (empty when none were found).
    """
    families: list[str] = []
    for name in WINDOWS_FONT_FILES:
        path = font_dir / name
        if not path.is_file():
            continue
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id >= 0:
            families += QFontDatabase.applicationFontFamilies(font_id)
    return sorted(set(families))


def choose_font(
    current: QFont, available: Iterable[str], preferred: Iterable[str] = PREFERRED_FONTS
) -> QFont | None:
    """The interface font to use instead of a generic system fallback.

    Parameters
    ----------
    current : QFont
        The application's font as the platform set it.
    available : iterable of str
        Installed font families.
    preferred : iterable of str
        Families in order of preference.

    Returns
    -------
    QFont or None
        ``current`` with the first available preferred family (same point size), or None
        when the system font is a real choice (not one of :data:`GENERIC_FONTS`) or no
        preferred family is installed.
    """
    resolved = QFontInfo(current).family()
    if current.family() not in GENERIC_FONTS and resolved not in GENERIC_FONTS:
        return None
    installed = set(available)
    for family in preferred:
        if family in installed:
            font = QFont(current)
            font.setFamily(family)
            return font
    return None


def drawable(text: str, font: QFont, families: Iterable[str]) -> bool:
    """True when ``font``, or else one of ``families``, has a glyph for every character."""
    chars = [ord(c) for c in text]
    if all(QFontMetrics(font).inFontUcs4(c) for c in chars):
        return True
    for family in families:
        metrics = QFontMetrics(QFont(family))
        if all(metrics.inFontUcs4(c) for c in chars):
            return True
    return False


def fit_status_symbols(
    font: QFont, families: Iterable[str], styles: dict[str, StatusStyle] = STATUS_STYLES
) -> list[str]:
    """Replace each status symbol that no installed font can draw with its ASCII symbol.

    Parameters
    ----------
    font : QFont
        The application font.
    families : iterable of str
        Installed font families (Qt falls back to these for a missing glyph).
    styles : dict
        The status styles to update in place (default :data:`STATUS_STYLES`).

    Returns
    -------
    list of str
        The statuses whose symbol was replaced.
    """
    names = list(families)
    replaced = []
    for kind, style in styles.items():
        if not drawable(style.symbol, font, names):
            styles[kind] = replace(style, symbol=ASCII_SYMBOLS[kind])
            replaced.append(kind)
    return replaced


def apply_theme(
    app: QApplication,
    environ: Mapping[str, str] | None = None,
    platform: str = sys.platform,
) -> None:
    """Apply the shared look to the whole application (see the module docstring).

    Parameters
    ----------
    app : QApplication
        The application.
    environ : mapping, optional
        Process environment, to tell WSL (default ``os.environ``).
    platform : str
        ``sys.platform``.
    """
    env = dict(os.environ if environ is None else environ)
    style = QStyleFactory.create(STYLE)
    if style is not None:  # Fusion is built into Qt; keep the platform style otherwise
        app.setStyle(style)
        # The style sheet wraps the style, which then reports no name: keep it for --diagnose.
        app.setProperty("envelopelabStyle", style.name())
    app.setPalette(palette())
    if platform.startswith("linux"):
        if is_wsl(env):
            load_windows_fonts()
        font = choose_font(app.font(), QFontDatabase.families())
        if font is not None:
            app.setFont(font)
    fit_status_symbols(app.font(), QFontDatabase.families())
    app.setStyleSheet(stylesheet())


def look_report(app: QApplication) -> str:
    """The Qt style, font and status symbols in use, one ``name: value`` per line."""
    font = app.font()
    return "\n".join(
        [
            f"Qt style: {app.property('envelopelabStyle') or app.style().name() or '(platform)'}",
            f"font: {QFontInfo(font).family()} {font.pointSizeF():g} pt",
            f"logical DPI: {app.primaryScreen().logicalDotsPerInch():g}"
            if app.primaryScreen() is not None
            else "logical DPI: (no screen)",
            "status symbols: " + " ".join(s.symbol for s in STATUS_STYLES.values()),
        ]
    )


def _restyle(widget: QWidget) -> None:
    """Re-evaluate the style sheet after a dynamic property changed."""
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


class StatusChip(QLabel):
    """A small rounded label naming a status (e.g. "Current", "Stale", "Not converged")."""

    def __init__(self, kind: str = "ok", text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("statusChip")
        self.kind = kind
        self.set_status(kind, text)

    def set_status(self, kind: str, text: str) -> None:
        """Show ``text`` with the look of ``kind`` (a key of :data:`STATUS_STYLES`)."""
        if kind not in STATUS_STYLES:
            raise ValueError(f"unknown status {kind!r}")
        self.kind = kind
        self.setText(f"{STATUS_STYLES[kind].symbol} {text}" if text else "")
        self.setProperty("status", kind)
        self.setVisible(bool(text))
        _restyle(self)


class StatusBanner(QFrame):
    """A full-width banner stating the status of what a view shows.

    It is hidden while no status is set (:meth:`clear`). The optional action button emits
    :attr:`actionTriggered`. The banner cannot be closed by the user: it goes away only
    when the state it reports goes away.
    """

    actionTriggered = Signal()  # noqa: N815 (Qt naming)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("statusBanner")
        self.kind: str | None = None
        self.symbol = QLabel()
        self.symbol.setObjectName("statusSymbol")
        self.symbol.setStyleSheet("font-size: 16px; font-weight: 700;")
        self.title = QLabel()
        self.title.setObjectName("statusTitle")
        self.title.setStyleSheet("font-weight: 700;")
        self.message = QLabel()
        self.message.setObjectName("statusMessage")
        self.message.setWordWrap(True)
        self.message.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.action = QPushButton()
        self.action.setObjectName("statusAction")
        self.action.clicked.connect(self.actionTriggered)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(8)
        layout.addWidget(self.symbol)
        layout.addWidget(self.title)
        layout.addWidget(self.message, 1)
        layout.addWidget(self.action)
        self.clear()

    def set_status(self, kind: str, title: str, message: str = "", action: str = "") -> None:
        """Show a status.

        Parameters
        ----------
        kind : str
            A key of :data:`STATUS_STYLES`.
        title : str
            Short statement, e.g. "Not converged — values are not final."
        message : str
            Details (iterations, residual, what changed, ...).
        action : str
            Text of the action button; empty hides it.
        """
        if kind not in STATUS_STYLES:
            raise ValueError(f"unknown status {kind!r}")
        self.kind = kind
        self.symbol.setText(STATUS_STYLES[kind].symbol)
        self.title.setText(title)
        self.message.setText(message)
        self.action.setText(action)
        self.action.setVisible(bool(action))
        self.setProperty("status", kind)
        self.setAccessibleName(f"{title} {message}".strip())
        self.show()
        _restyle(self)

    def clear(self) -> None:
        """Hide the banner."""
        self.kind = None
        self.title.clear()
        self.message.clear()
        self.setProperty("status", "")
        self.hide()

    def text(self) -> str:
        """Title and message as shown (empty while hidden)."""
        return f"{self.title.text()} {self.message.text()}".strip() if self.kind else ""
