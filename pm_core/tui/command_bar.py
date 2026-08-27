"""Bottom command input widget for the TUI."""

from textual.widget import Widget
from textual.widgets import Input
from textual.message import Message

from pm_core import paths
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
        self._history: list[str] = []
        # Cursor into history. Equal to len(_history) means "at the new
        # line being typed" (no recall active).
        self._history_pos: int = 0

    def _refresh_history(self) -> None:
        try:
            self._history = paths.read_command_history(limit=500)
        except Exception:
            self._history = []
        self._history_pos = len(self._history)

    def on_focus(self) -> None:
        _log.debug("CommandBar: got focus, has_focus=%s", self.has_focus)
        self.placeholder = self.FOCUSED_PLACEHOLDER
        self._refresh_history()
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

    def on_key(self, event) -> None:
        _log.debug("CommandBar on_key: key=%r char=%r value=%r",
                    event.key, event.character, self.value)
        if event.key == "up":
            if self._history and self._history_pos > 0:
                self._history_pos -= 1
                self.value = self._history[self._history_pos]
                self.cursor_position = len(self.value)
            event.stop()
            event.prevent_default()
        elif event.key == "down":
            if self._history and self._history_pos < len(self._history) - 1:
                self._history_pos += 1
                self.value = self._history[self._history_pos]
                self.cursor_position = len(self.value)
            elif self._history_pos < len(self._history):
                self._history_pos = len(self._history)
                self.value = ""
            event.stop()
            event.prevent_default()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        _log.info("CommandBar submitted: %r", event.value)
        command = event.value.strip()
        if command:
            try:
                paths.append_command_history(command)
            except Exception:
                pass
            self.post_message(CommandSubmitted(command))
        self.value = ""
        self._refresh_history()
