"""Undoable commands and the command stack.

Every edit of a design is a :class:`Command`; the :class:`CommandStack` executes it, keeps
the full undo and redo history and notifies listeners after every change, so a user
interface can show the history, jump to any point in it and mark unsaved changes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable


class Command(ABC):
    @abstractmethod
    def execute(self) -> None:
        """Apply the command."""

    @abstractmethod
    def undo(self) -> None:
        """Revert the command."""

    @property
    def description(self) -> str:
        """Short human-readable description for the history list."""
        return type(self).__name__


Listener = Callable[[], None]


class CommandStack:
    def __init__(self) -> None:
        self._undo_stack: list[Command] = []
        self._redo_stack: list[Command] = []
        self._clean_index: int | None = 0
        self._listeners: list[Listener] = []

    # -- listeners ----------------------------------------------------------------------

    def add_listener(self, listener: Listener) -> None:
        """Call ``listener()`` after every do, undo, redo, clear or clean-state change."""
        self._listeners.append(listener)

    def remove_listener(self, listener: Listener) -> None:
        """Stop notifying ``listener``."""
        self._listeners.remove(listener)

    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    # -- editing ------------------------------------------------------------------------

    def do(self, command: Command) -> None:
        command.execute()
        if self._clean_index is not None and self._clean_index > len(self._undo_stack):
            self._clean_index = None  # the saved state was in the discarded redo history
        self._undo_stack.append(command)
        self._redo_stack.clear()
        self._notify()

    def undo(self) -> bool:
        if not self._undo_stack:
            return False
        command = self._undo_stack.pop()
        command.undo()
        self._redo_stack.append(command)
        self._notify()
        return True

    def redo(self) -> bool:
        if not self._redo_stack:
            return False
        command = self._redo_stack.pop()
        command.execute()
        self._undo_stack.append(command)
        self._notify()
        return True

    def go_to(self, index: int) -> None:
        """Undo or redo until ``index`` commands are applied (0: the initial state)."""
        if not 0 <= index <= len(self._undo_stack) + len(self._redo_stack):
            raise IndexError(f"history index {index} out of range")
        while len(self._undo_stack) > index:
            self.undo()
        while len(self._undo_stack) < index:
            self.redo()

    def clear(self) -> None:
        """Forget the whole history (the current state becomes the clean state)."""
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._clean_index = 0
        self._notify()

    # -- state --------------------------------------------------------------------------

    @property
    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo_stack)

    @property
    def index(self) -> int:
        """Number of applied commands."""
        return len(self._undo_stack)

    def history(self) -> list[str]:
        """Descriptions of every command, oldest first (applied, then undone)."""
        applied = [c.description for c in self._undo_stack]
        return applied + [c.description for c in reversed(self._redo_stack)]

    def undo_text(self) -> str | None:
        """Description of the command :meth:`undo` would revert."""
        return self._undo_stack[-1].description if self._undo_stack else None

    def redo_text(self) -> str | None:
        """Description of the command :meth:`redo` would apply."""
        return self._redo_stack[-1].description if self._redo_stack else None

    def set_clean(self) -> None:
        """Mark the current state as saved."""
        self._clean_index = len(self._undo_stack)
        self._notify()

    @property
    def is_clean(self) -> bool:
        """True when the applied commands are those of the last :meth:`set_clean`."""
        return self._clean_index == len(self._undo_stack)
