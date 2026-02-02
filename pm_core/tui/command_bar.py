"""Bottom command input widget for the TUI."""

import logging
from textual.widget import Widget
from textual.widgets import Input
from textual.message import Message

_log = logging.getLogger("pm.tui")


class CommandSubmitted(Message):
    """Fired when a command is submitted."""
    def __init__(self, command: str) -> None:
        self.command = command
        super().__init__()


class CommandBar(Input):
    """Command input bar at the bottom of the TUI."""

    def __init__(self, **kwargs):
        super().__init__(placeholder="Type command (e.g. pr start pr-001)...", **kwargs)

    def on_focus(self) -> None:
        _log.debug("CommandBar: got focus, has_focus=%s", self.has_focus)

    def on_blur(self) -> None:
        _log.debug("CommandBar: lost focus")

    def on_key(self, event) -> None:
        _log.debug("CommandBar on_key: key=%r char=%r value=%r",
                    event.key, event.character, self.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        _log.info("CommandBar submitted: %r", event.value)
        command = event.value.strip()
        if command:
            self.post_message(CommandSubmitted(command))
        self.value = ""
