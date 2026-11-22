"""A colour picker in the style of office and image-editing programs (Colours mode).

From the top:

* the **current colour**: a large swatch, its ``#rrggbb`` code (type a code and press
  Enter to use it) and **No colour** (painting then clears panels);
* **Theme colours**: ten base colours, each with lighter tints and darker shades below
  it (:func:`theme_columns`);
* **Standard colours**: ten saturated colours;
* **Recent colours**: the last colours used (newest first; kept in the application
  settings by the Colours panel);
* **Colours in this design**: every colour on the balloon, most used first. A right
  click on one offers to replace it everywhere with the current colour, or to clear it;
* **More colours…**: the full colour dialog (hue/saturation wheel and value, RGB, HSV and
  HTML code, and its own *Pick screen colour* eyedropper).

Colours are sRGB ``#rrggbb`` strings throughout (:mod:`envelopelab.project.colours`); this
module only chooses them.
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QColorDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from envelopelab.project.colours import normalise_colour

#: Base theme colours, one column each (white, black, then eight hues).
THEME_BASE: tuple[str, ...] = (
    "#ffffff",
    "#000000",
    "#e7e6e6",
    "#44546a",
    "#4472c4",
    "#ed7d31",
    "#a5a5a5",
    "#ffc000",
    "#5b9bd5",
    "#70ad47",
)
#: Saturated standard colours.
STANDARD: tuple[str, ...] = (
    "#c00000",
    "#ff0000",
    "#ffc000",
    "#ffff00",
    "#92d050",
    "#00b050",
    "#00b0f0",
    "#0070c0",
    "#002060",
    "#7030a0",
)
#: Names shown in the tooltips of the standard colours.
STANDARD_NAMES: dict[str, str] = dict(
    zip(
        STANDARD,
        (
            "Dark red",
            "Red",
            "Orange",
            "Yellow",
            "Light green",
            "Green",
            "Light blue",
            "Blue",
            "Dark blue",
            "Purple",
        ),
        strict=True,
    )
)
#: Most colours kept in the recent row.
MAX_RECENT = 10
#: Side of a palette swatch, px.
SWATCH = 18


def _mix(colour: str, towards: str, amount: float) -> str:
    """``colour`` moved ``amount`` (0-1) of the way to ``towards`` in sRGB."""
    a, b = QColor(colour), QColor(towards)
    r = round(a.red() + (b.red() - a.red()) * amount)
    g = round(a.green() + (b.green() - a.green()) * amount)
    bl = round(a.blue() + (b.blue() - a.blue()) * amount)
    return f"#{r:02x}{g:02x}{bl:02x}"


def theme_columns() -> list[list[str]]:
    """Every theme column: the base colour, then three tints and two shades (light base
    colours get darker shades only, dark ones lighter tints only)."""
    columns = []
    for base in THEME_BASE:
        lightness = QColor(base).lightnessF()
        if lightness > 0.85:
            steps = [_mix(base, "#000000", f) for f in (0.05, 0.15, 0.25, 0.35, 0.5)]
        elif lightness < 0.15:
            steps = [_mix(base, "#ffffff", f) for f in (0.5, 0.35, 0.25, 0.15, 0.05)]
        else:
            steps = [_mix(base, "#ffffff", f) for f in (0.8, 0.6, 0.4)]
            steps += [_mix(base, "#000000", f) for f in (0.25, 0.5)]
        columns.append([base, *steps])
    return columns


def with_recent(recent: Sequence[str], colour: str) -> list[str]:
    """``recent`` with ``colour`` first (moved there if present), at most
    :data:`MAX_RECENT` long."""
    colour = normalise_colour(colour)
    return [colour, *[c for c in recent if c != colour]][:MAX_RECENT]


class Swatch(QWidget):
    """One clickable colour square (``None``: no colour, drawn crossed out)."""

    #: Left click: the colour (``""`` for no colour).
    picked = Signal(str)
    #: Right click: the colour and the global position.
    menuRequested = Signal(str, QPoint)  # noqa: N815 (Qt naming)

    def __init__(self, colour: str | None, tip: str = "", size: int = SWATCH) -> None:
        super().__init__()
        self.colour = colour
        self.selected = False
        self.setFixedSize(QSize(size, size))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(tip or (colour or "No colour"))
        self.setObjectName("colourSwatch")

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 (Qt API)
        p = QPainter(self)
        rect = self.rect().adjusted(1, 1, -2, -2)
        if self.colour is None:
            p.fillRect(rect, QColor("white"))
            p.setPen(QPen(QColor("#d00000"), 1.5))
            p.drawLine(rect.bottomLeft(), rect.topRight())
        else:
            p.fillRect(rect, QColor(self.colour))
        p.setPen(
            QPen(
                QColor("#e8590c") if self.selected else QColor("#8a8f98"), 2 if self.selected else 1
            )
        )
        p.drawRect(rect)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt API)
        if event.button() == Qt.MouseButton.LeftButton:
            self.picked.emit(self.colour or "")
        elif event.button() == Qt.MouseButton.RightButton:
            self.menuRequested.emit(self.colour or "", event.globalPosition().toPoint())


class SwatchRow(QWidget):
    """A row of swatches that can be refilled (recent colours, colours in the design)."""

    picked = Signal(str)
    menuRequested = Signal(str, QPoint)  # noqa: N815 (Qt naming)

    def __init__(self, empty_text: str) -> None:
        super().__init__()
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(2)
        self.empty = QLabel(empty_text)
        self.empty.setObjectName("hint")
        self._layout.addWidget(self.empty)
        self._layout.addStretch(1)
        self.swatches: list[Swatch] = []

    def set_colours(self, colours: Sequence[str], tips: Sequence[str] = ()) -> None:
        """Show ``colours`` (the first ``2 * MAX_RECENT``) with their tooltips."""
        for s in self.swatches:
            self._layout.removeWidget(s)
            s.deleteLater()
        self.swatches = []
        shown = list(colours)[: MAX_RECENT * 2]
        for i, colour in enumerate(shown):
            tip = tips[i] if i < len(tips) else colour
            s = Swatch(colour, tip)
            s.picked.connect(self.picked)
            s.menuRequested.connect(self.menuRequested)
            self._layout.insertWidget(i, s)
            self.swatches.append(s)
        self.empty.setVisible(not shown)


class ColourPicker(QWidget):
    """See module docstring.

    Signals
    -------
    colourChanged(str)
        The current colour changed (``#rrggbb``; ``""``: no colour).
    replaceRequested(str, str)
        Replace a design colour (first) with another (second; ``""``: clear it).
    """

    colourChanged = Signal(str)  # noqa: N815 (Qt naming)
    replaceRequested = Signal(str, str)  # noqa: N815 (Qt naming)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("colourPicker")
        self._colour: str | None = THEME_BASE[4]
        self.recent: list[str] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        top = QHBoxLayout()
        self.preview = Swatch(self._colour, "Current colour", size=40)
        self.preview.setCursor(Qt.CursorShape.ArrowCursor)
        self.hex_edit = QLineEdit()
        self.hex_edit.setObjectName("colourHex")
        self.hex_edit.setPlaceholderText("#rrggbb")
        self.hex_edit.setMaxLength(7)
        self.hex_edit.setToolTip("Colour code (sRGB hex, e.g. #4472c4); Enter to use it")
        self.hex_edit.editingFinished.connect(self._typed)
        self.none_button = QPushButton("No colour")
        self.none_button.setObjectName("noColour")
        self.none_button.setCheckable(True)
        self.none_button.setToolTip("Paint with no colour: clears the panels you click")
        self.none_button.clicked.connect(lambda _c=False: self.set_colour(None))
        side = QVBoxLayout()
        side.addWidget(self.hex_edit)
        side.addWidget(self.none_button)
        top.addWidget(self.preview)
        top.addLayout(side, 1)
        layout.addLayout(top)

        layout.addWidget(self._heading("Theme colours"))
        grid = QGridLayout()
        grid.setSpacing(2)
        self.theme_swatches: list[Swatch] = []
        for col, column in enumerate(theme_columns()):
            for row, colour in enumerate(column):
                s = Swatch(colour, self._tip(colour, row))
                s.picked.connect(self._picked)
                # The base row stands apart from its tints and shades, as in office suites.
                grid.addWidget(s, row + (1 if row else 0), col)
                self.theme_swatches.append(s)
        grid.setRowMinimumHeight(1, 4)
        grid_box = QWidget()
        grid_box.setLayout(grid)
        grid_box.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        layout.addWidget(grid_box)

        layout.addWidget(self._heading("Standard colours"))
        standard = QHBoxLayout()
        standard.setSpacing(2)
        self.standard_swatches = []
        for colour in STANDARD:
            s = Swatch(colour, f"{STANDARD_NAMES[colour]} {colour}")
            s.picked.connect(self._picked)
            standard.addWidget(s)
            self.standard_swatches.append(s)
        standard.addStretch(1)
        layout.addLayout(standard)

        layout.addWidget(self._heading("Recent colours"))
        self.recent_row = SwatchRow("none yet")
        self.recent_row.picked.connect(self._picked)
        layout.addWidget(self.recent_row)

        layout.addWidget(self._heading("Colours in this design"))
        self.design_row = SwatchRow("no panel coloured yet")
        self.design_row.setToolTip(
            "Every colour on the balloon. Right click one to replace it everywhere"
        )
        self.design_row.picked.connect(self._picked)
        self.design_row.menuRequested.connect(self._design_menu)
        layout.addWidget(self.design_row)

        more = QPushButton("More colours…")
        more.setObjectName("moreColours")
        more.setToolTip("Any colour: colour wheel, RGB, HSV, HTML code or a colour from the screen")
        more.clicked.connect(self.more_colours)
        layout.addWidget(more)
        layout.addStretch(1)
        self._show()

    @staticmethod
    def _heading(text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet("font-weight: bold;")
        return label

    @staticmethod
    def _tip(colour: str, row: int) -> str:
        if row == 0:
            return colour
        kind = ("lighter or darker", "lighter 80 %", "lighter 60 %", "lighter 40 %")
        return f"{colour} ({kind[row] if row < 4 else 'darker'})"

    # -- state ------------------------------------------------------------------------

    @property
    def colour(self) -> str | None:
        """Current colour (``#rrggbb``; None: no colour)."""
        return self._colour

    def set_colour(self, colour: str | None) -> None:
        """Make ``colour`` current (None: no colour); emits ``colourChanged``."""
        value = None if not colour else normalise_colour(colour)
        changed = value != self._colour
        self._colour = value
        self._show()
        if changed:
            self.colourChanged.emit(value or "")

    def set_recent(self, colours: Sequence[str]) -> None:
        """Show the recent colours (newest first)."""
        self.recent = [normalise_colour(c) for c in colours][:MAX_RECENT]
        self.recent_row.set_colours(self.recent)

    def remember(self, colour: str) -> None:
        """Put ``colour`` first in the recent colours."""
        self.set_recent(with_recent(self.recent, colour))

    def set_design_colours(self, colours: Sequence[str], counts: Sequence[int] = ()) -> None:
        """Show the colours on the balloon (most used first) and how many panels each."""
        tips = [
            f"{c}: {counts[i]} panel{'s' if counts[i] != 1 else ''} (right click: replace)"
            if i < len(counts)
            else c
            for i, c in enumerate(colours)
        ]
        self.design_row.set_colours(colours, tips)

    def _show(self) -> None:
        self.preview.colour = self._colour
        self.preview.update()
        self.hex_edit.setText(self._colour or "")
        self.none_button.setChecked(self._colour is None)
        for s in [*self.theme_swatches, *self.standard_swatches]:
            s.selected = s.colour == self._colour
            s.update()

    def _picked(self, colour: str) -> None:
        self.set_colour(colour or None)

    def _typed(self) -> None:
        text = self.hex_edit.text().strip()
        if not text:
            return
        try:
            self.set_colour(text)
        except ValueError:
            self.hex_edit.setStyleSheet("color: #b00020;")
            self.hex_edit.setToolTip(f"Not a colour: {text!r}. Use #rrggbb, e.g. #4472c4")
            return
        self.hex_edit.setStyleSheet("")

    def more_colours(self) -> None:
        """Choose any colour in the full colour dialog."""
        start = QColor(self._colour or "#ffffff")
        chosen = QColorDialog.getColor(start, self, "More colours")
        if chosen.isValid():
            self.set_colour(chosen.name())

    def _design_menu(self, colour: str, at: QPoint) -> None:
        from PySide6.QtWidgets import QMenu

        if not colour:
            return
        menu = QMenu(self)
        current = self._colour
        replace = menu.addAction(f"Replace {colour} everywhere with {current or 'no colour'}")
        replace.setEnabled(current != colour)
        clear = menu.addAction(f"Clear {colour} everywhere")
        use = menu.addAction(f"Use {colour}")
        action = menu.exec(at)
        if action is replace:
            self.replaceRequested.emit(colour, current or "")
        elif action is clear:
            self.replaceRequested.emit(colour, "")
        elif action is use:
            self.set_colour(colour)


__all__ = [
    "MAX_RECENT",
    "STANDARD",
    "THEME_BASE",
    "ColourPicker",
    "Swatch",
    "SwatchRow",
    "theme_columns",
    "with_recent",
]
