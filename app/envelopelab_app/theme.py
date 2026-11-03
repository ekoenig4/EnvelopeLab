"""Shared look of the desktop application: colour tokens, the style sheet and status widgets.

Every window takes its colours from :data:`TOKENS` and shows the state of a result with
the same :class:`StatusBanner` and :class:`StatusChip`, so a stale, unconverged or failing
result looks the same wherever it appears. A status is never told by colour alone: each
one has its own symbol and its own words (the banner title and the chip text).

The style sheet (:func:`stylesheet`) is applied once to the whole application by
:func:`apply_theme`. It only styles object names and properties it sets itself
(``statusBanner``, ``statusChip``, ``toolRail``, ``sidePanel``, ``card``), plus plain
neutral defaults, so widgets that set their own style sheet keep it.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

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
        "QWidget#toolRail QToolButton { min-width: 40px; min-height: 40px;"
        " border: 1px solid transparent; border-radius: 6px; }",
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


def apply_theme(app: QApplication) -> None:
    """Apply the shared style sheet to the whole application."""
    app.setStyleSheet(stylesheet())


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
