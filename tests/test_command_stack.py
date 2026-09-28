from envelopelab.commands import Command, CommandStack


class IncrementCommand(Command):
    def __init__(self, state: dict[str, int]) -> None:
        self._state = state

    def execute(self) -> None:
        self._state["value"] += 1

    def undo(self) -> None:
        self._state["value"] -= 1


def test_command_stack_undo_redo_cycle() -> None:
    state = {"value": 0}
    stack = CommandStack()

    stack.do(IncrementCommand(state))
    assert state["value"] == 1
    assert stack.undo() is True
    assert state["value"] == 0
    assert stack.redo() is True
    assert state["value"] == 1
