"""Where a number acts: hints from the fields under the pointer or being edited.

Every widget that edits a number of the design carries the Qt property ``designHint``: a
hint key (:func:`envelopelab.project.highlight.hint_highlight`, or ``shape:<field>`` for
the selected special shape). One :class:`HintTracker` watches the whole application:
pointing at such a widget (or at anything inside a widget that carries one) shows its hint
in the 3D views, and giving it the keyboard focus (to type or scrub the value) also turns
the views to face it. When the pointer leaves, the focused field's hint (if any) shows
again.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication, QWidget

if TYPE_CHECKING:
    from envelopelab_app.controller import WorkspaceController

#: Name of the Qt property that carries a widget's hint key.
HINT_PROPERTY = "designHint"


def set_hint(widget: QWidget, key: str | None) -> None:
    """Give ``widget`` (and what is inside it) the hint ``key`` (None: none)."""
    widget.setProperty(HINT_PROPERTY, key)


def hint_of(widget: QObject | None) -> str | None:
    """The hint of ``widget`` or of the nearest widget round it that has one."""
    while widget is not None:
        key = widget.property(HINT_PROPERTY)
        if isinstance(key, str) and key:
            return key
        widget = widget.parent()
    return None


class HintTracker(QObject):
    """Shows the hint of the widget pointed at or focused (module docstring)."""

    def __init__(self, controller: WorkspaceController) -> None:
        super().__init__(controller)
        self.controller = controller
        self.hovered: str | None = None
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def _focused(self) -> str | None:
        return hint_of(QApplication.focusWidget())

    def _show(self) -> None:
        if self.hovered is not None:
            focused = self._focused()
            self.controller.set_hint(self.hovered, focused == self.hovered)
        else:
            focused = self._focused()
            self.controller.set_hint(focused, focused is not None)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 (Qt API)
        kind = event.type()
        if kind == QEvent.Type.Enter and isinstance(watched, QWidget):
            key = hint_of(watched)
            if key != self.hovered:
                self.hovered = key
                self._show()
        elif kind == QEvent.Type.Leave and isinstance(watched, QWidget):
            if hint_of(watched) == self.hovered:
                self.hovered = None
                self._show()
        elif kind in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            self._show()
        return False
