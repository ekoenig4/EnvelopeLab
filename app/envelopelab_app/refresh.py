"""Refresh scheduling: each panel redraws at most once per change, and not while hidden.

One user edit makes the controller emit several signals in a row (``stateChanged``,
``artifactsChanged``, ``fileChanged``, ...). Panels used to redraw on each of them, and
panels in other workflow modes redrew although nobody could see them. A
:class:`Refresher` wraps a panel's refresh method:

* the controller numbers every burst of signals (``WorkspaceController.revision``); a
  refresh already done for the current revision is skipped;
* a hidden widget is only marked dirty and refreshes when it is shown again (in the
  interactive application; see ``WorkspaceController.defer_hidden``).

The refresh still runs synchronously for a visible widget, so what a panel shows is
current as soon as the edit returns.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from PySide6.QtCore import QEvent, QObject, SignalInstance
from PySide6.QtWidgets import QWidget


class Refresher(QObject):
    """Deduplicated, visibility-aware refresh of one widget.

    Parameters
    ----------
    widget : QWidget
        The widget whose visibility decides whether to refresh now.
    action : callable
        The refresh method.
    revision : callable
        Current change number of the data source (the controller's ``revision``).
    signals : iterable of SignalInstance
        Signals that request a refresh.
    defer_hidden : bool or callable
        Postpone the refresh of a hidden widget until it is shown (a callable is asked
        on every request; the interactive application defers, scripted windows whose
        callers read hidden panels directly do not).
    """

    def __init__(
        self,
        widget: QWidget,
        action: Callable[[], Any],
        revision: Callable[[], int],
        signals: Iterable[SignalInstance] = (),
        defer_hidden: bool | Callable[[], bool] = True,
    ) -> None:
        super().__init__(widget)
        self.widget = widget
        self.action = action
        self.revision = revision
        self.defer_hidden = defer_hidden
        self.done: int | None = None
        self.dirty = False
        #: Refreshes run and requests skipped (for profiling and tests).
        self.runs = 0
        self.skipped = 0
        for signal in signals:
            signal.connect(self.request)
        widget.installEventFilter(self)

    def request(self, *_: Any) -> None:
        """A source changed: refresh now, later or not at all (module docstring)."""
        rev = self.revision()
        if self.done == rev and not self.dirty:
            self.skipped += 1
            return
        defer = self.defer_hidden() if callable(self.defer_hidden) else self.defer_hidden
        if defer and not self.widget.isVisible():
            self.dirty = True
            self.skipped += 1
            return
        self.run()

    def run(self) -> None:
        """Refresh now."""
        self.dirty = False
        self.done = self.revision()
        self.runs += 1
        self.action()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 (Qt API)
        if watched is self.widget and event.type() == QEvent.Type.Show and self.dirty:
            self.run()
        return False
