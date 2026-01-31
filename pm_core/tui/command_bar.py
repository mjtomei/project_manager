"""Bottom command input widget for the TUI."""

from textual.widget import Widget
from textual.widgets import Input
from textual.message import Message


class CommandSubmitted(Message):
    """Fired when a command is submitted."""
    def __init__(self, command: str) -> None:
        self.command = command
        super().__init__()


class CommandBar(Input):
    """Command input bar at the bottom of the TUI."""

    def __init__(self, **kwargs):
        super().__init__(placeholder="Type command (e.g. pr start pr-001)...", **kwargs)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        command = event.value.strip()
        if command:
            self.post_message(CommandSubmitted(command))
        self.value = ""
