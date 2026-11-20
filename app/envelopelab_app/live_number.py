"""Change a number in real time: the mouse wheel or the arrow keys step a numeric field.

Every number of the design can be typed (and committed with Enter), and also *scrubbed*:
with the pointer over a number field, the mouse wheel steps it; with the field focused, the
Up and Down arrow keys do. Each step is applied at once through
:meth:`~envelopelab_app.controller.WorkspaceController.edit_live`, so the drawings follow
the value while it moves, the newest value wins when steps come faster than the views
redraw, and a run of steps is one undo step.

The step is one unit of the value's second significant digit (0.1 for 2.35, 0.01 for
0.15; at least :data:`MIN_STEP`); Shift steps ten times further, Ctrl a tenth as far.
"""

from __future__ import annotations

import math
from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QKeyEvent, QWheelEvent
from PySide6.QtWidgets import QLineEdit

#: Smallest step of a scrubbed value (in the field's unit; 0.1 mm for metres).
MIN_STEP = 1e-4


def step_size(value: float, integer: bool = False) -> float:
    """The step of :mod:`live_number` for ``value``: a unit of its second significant
    digit (``integer``: 1)."""
    if integer:
        return 1.0
    magnitude = abs(value)
    if magnitude < MIN_STEP:
        return MIN_STEP * 10.0
    return max(10.0 ** (math.floor(math.log10(magnitude)) - 1), MIN_STEP)


def stepped(value: float, steps: float, integer: bool = False) -> float:
    """``value`` moved by ``steps`` steps, rounded to the step (no binary noise)."""
    size = step_size(value, integer)
    out = value + steps * size
    digits = max(0, -int(math.floor(math.log10(size))) + 1)
    return float(round(out)) if integer else round(out, digits)


class LiveNumber(QObject):
    """Scrub a numeric line edit (module docstring).

    Parameters
    ----------
    editor : QLineEdit
        The number field.
    apply : callable
        ``apply(value)``: commit the new value (through the controller's live edits).
    integer : bool
        The value is a whole number.
    """

    def __init__(
        self, editor: QLineEdit, apply: Callable[[float], object], integer: bool = False
    ) -> None:
        super().__init__(editor)
        self.editor = editor
        self.apply = apply
        self.integer = integer
        editor.installEventFilter(self)
        tip = editor.toolTip()
        hint = "Wheel or ↑/↓: change it in real time (Shift ×10, Ctrl ×0.1)"
        editor.setToolTip(f"{tip}\n{hint}" if tip else hint)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 (Qt API)
        if watched is not self.editor or self.editor.isReadOnly() or not self.editor.isEnabled():
            return False
        steps = 0.0
        modifiers = Qt.KeyboardModifier.NoModifier
        if event.type() == QEvent.Type.Wheel:
            assert isinstance(event, QWheelEvent)
            steps = event.angleDelta().y() / 120.0
            modifiers = event.modifiers()
        elif event.type() == QEvent.Type.KeyPress:
            assert isinstance(event, QKeyEvent)
            if event.key() == Qt.Key.Key_Up:
                steps = 1.0
            elif event.key() == Qt.Key.Key_Down:
                steps = -1.0
            modifiers = event.modifiers()
        if not steps:
            return False
        try:
            value = float(self.editor.text().replace(",", ".").strip())
        except ValueError:
            return False
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            steps *= 10.0
        if modifiers & Qt.KeyboardModifier.ControlModifier and not self.integer:
            steps *= 0.1
        new = stepped(value, steps, self.integer)
        text = str(int(new)) if self.integer else repr(new)
        self.editor.setText(text)
        self.editor.setModified(False)
        self.apply(new)
        event.accept()
        return True
