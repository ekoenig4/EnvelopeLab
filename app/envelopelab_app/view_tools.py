"""Shared navigation tools of the 2D views: a Fit button in the view's corner.

Every 2D drawing (gore map, envelope panels, cut pieces, patterns) pans with a left drag
on empty space or a middle or right drag, zooms with the wheel, and resets with a double
click or this button.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QToolButton, QWidget

#: Distance of the Fit button from the view's top-right corner, px.
FIT_INSET = 6


class FitButton(QToolButton):
    """A small **Fit** button kept in the top-right corner of ``view``; clicking it calls
    ``fit`` (show the whole drawing again)."""

    def __init__(self, view: QWidget, fit: Callable[[], object], tip: str = "") -> None:
        super().__init__(view)
        self.setObjectName("fitView")
        self.setText("⤢ Fit")
        self.setToolTip(tip or "Show the whole drawing again (or double click the view)")
        self.setAutoRaise(False)
        self.clicked.connect(lambda _checked=False: fit())
        view.installEventFilter(self)
        self._place()
        self.show()

    def _place(self) -> None:
        view = self.parentWidget()
        if view is None:
            return
        self.adjustSize()
        self.move(view.width() - self.width() - FIT_INSET, FIT_INSET)
        self.raise_()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 (Qt API)
        if watched is self.parentWidget() and event.type() in (
            QEvent.Type.Resize,
            QEvent.Type.Show,
        ):
            self._place()
        return super().eventFilter(watched, event)
