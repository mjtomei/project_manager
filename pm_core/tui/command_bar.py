"""Bottom command input widget for the TUI."""

from textual.widget import Widget
from textual.widgets import Input
from textual.message import Message

from pm_core.paths import configure_logger

_log = configure_logger("pm.tui.command_bar")


class CommandSubmitted(Message):
    """Fired when a command is submitted."""
    def __init__(self, command: str) -> None:
        self.command = command
        super().__init__()


class CommandBar(Input):
    """Command input bar at the bottom of the TUI."""

    UNFOCUSED_PLACEHOLDER = "press / to type a command"
    FOCUSED_PLACEHOLDER = "Type command (e.g. pr start pr-001)..."

    def __init__(self, **kwargs):
        super().__init__(placeholder=self.UNFOCUSED_PLACEHOLDER, **kwargs)

    def on_focus(self) -> None:
        _log.debug("CommandBar: got focus, has_focus=%s", self.has_focus)
        self.placeholder = self.FOCUSED_PLACEHOLDER
        # Replay any keystrokes buffered between / press and focus
        app = self.app
        if getattr(app, "_command_pending", False):
            buffered = "".join(app._command_buffer)
            app._command_pending = False
            app._command_buffer.clear()
            if buffered:
                _log.debug("CommandBar: replaying buffered input: %r", buffered)
                self.value = buffered
                self.cursor_position = len(buffered)

    def on_blur(self) -> None:
        _log.debug("CommandBar: lost focus")
        self.placeholder = self.UNFOCUSED_PLACEHOLDER
        # Clear command pending state and buffer when losing focus
        app = self.app
        if getattr(app, "_command_pending", False):
            _log.debug("CommandBar: clearing command pending state on blur")
            app._command_pending = False
            app._command_buffer.clear()

    def on_key(self, event) -> None:
        _log.debug("CommandBar on_key: key=%r char=%r value=%r",
                    event.key, event.character, self.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        _log.info("CommandBar submitted: %r", event.value)
        command = event.value.strip()
        if command:
            self.post_message(CommandSubmitted(command))
        self.value = ""
