"""Bottom command input widget for the TUI."""

from textual.widget import Widget
from textual.widgets import Input
from textual.message import Message

from pm_core import command_history
from pm_core.paths import configure_logger

_log = configure_logger("pm.tui.command_bar")

# Completion candidates shown in the log line before "(+N more)".
_MAX_SHOWN_MATCHES = 12


class CommandSubmitted(Message):
    """Fired when a command is submitted."""
    def __init__(self, command: str) -> None:
        self.command = command
        super().__init__()


class CommandBar(Input):
    """Command input bar at the bottom of the TUI.

    Submitted commands go into the session's shared command history,
    which the prefix+M popup also reads and writes (see
    :mod:`pm_core.command_history`).  Up/Down walk that history: the
    half-typed line is kept and Down past the newest entry restores it.
    Tab completes subcommands, PR IDs and plan IDs with the popup's
    completer.  The first Tab inserts the candidates' common prefix and
    lists them in the log line; further Tabs (Shift-Tab: backwards) cycle
    through them.
    """

    # The bottom hint doubles as the TUI's footer (no Footer widget, so no
    # extra row): it advertises the auto-start runs popup key (R18).
    UNFOCUSED_PLACEHOLDER = "press / to type a command · a Runs"
    FOCUSED_PLACEHOLDER = "Type command (e.g. pr start pr-001)..."

    def __init__(self, **kwargs):
        # Focus comes back to the bar programmatically (e.g. after a queued
        # ``pm autostart`` command refocuses the tree mid-typing); Input's
        # default select-on-focus would then select the half-typed command
        # so the next keystroke replaces it.
        kwargs.setdefault("select_on_focus", False)
        super().__init__(placeholder=self.UNFOCUSED_PLACEHOLDER, **kwargs)
        self._history: list[str] = []
        self._history_sig: object = None
        # Index of the recalled entry; None while editing the draft line.
        self._history_pos: int | None = None
        self._draft = ""
        # Commands kept in memory only (no session tag, or a write failed).
        self._unsaved: list[str] = []
        self._completer = None
        # (line, cursor) after the last completion step, and the cycle.
        self._tab_state: dict | None = None

    # --- history ----------------------------------------------------------

    def _history_tag(self) -> str | None:
        """The pm session tag, from the app's tmux session name.

        Not derived from the cwd, so only this session's popup shares the
        history.  None outside a pm tmux session (history stays in memory).
        """
        return command_history.tag_for_session(
            getattr(self.app, "_session_name", None))

    def _sync_history(self) -> None:
        tag = self._history_tag()
        sig = (tag, command_history.file_signature(command_history.history_path(tag)),
               len(self._unsaved))
        if sig == self._history_sig:
            return
        self._history_sig = sig
        self._history = command_history.read_history(tag) + self._unsaved

    def _recall(self, step: int) -> None:
        if self._history_pos is None:
            if step > 0:
                return
            self._sync_history()
            if not self._history:
                return
            self._draft = self.value
            pos = len(self._history) - 1
        else:
            pos = self._history_pos + step
            if pos < 0:
                return
            if pos >= len(self._history):
                self._history_pos = None
                self._set_line(self._draft)
                return
        self._history_pos = pos
        self._set_line(self._history[pos])

    def _set_line(self, text: str, cursor: int | None = None) -> None:
        self.value = text
        self.cursor_position = len(text) if cursor is None else cursor

    def _remember(self, command: str) -> None:
        if not command_history.append_history(command, self._history_tag()):
            line = command_history.normalize_command(command)
            if line:
                self._unsaved.append(line)

    # --- completion -------------------------------------------------------

    def _get_completer(self):
        if self._completer is None:
            from pm_core.cli.completion import PmCompleter
            self._completer = PmCompleter(getattr(self.app, "_root", None))
        return self._completer

    def _complete(self, step: int) -> None:
        state = self._tab_state
        if (state is not None and state["applied"] == (self.value, self.cursor_position)
                and state["matches"]):
            # Repeated Tab: cycle through the candidates.
            n = len(state["matches"])
            state["index"] = ((state["index"] + step) % n if state["index"] >= 0
                              else (0 if step > 0 else n - 1))
            word = state["matches"][state["index"]]
            self._apply_word(state, word)
            return
        from pm_core.cli.completion import common_prefix
        line = self.value[:self.cursor_position]
        start, matches = self._get_completer().complete_line(line)
        self._tab_state = None
        if not matches:
            self.app.bell()
            return
        state = {"start": start, "rest": self.value[self.cursor_position:],
                 "before": self.value[:start], "matches": matches, "index": -1}
        if len(matches) == 1:
            self._apply_word(state, matches[0] + " ")
            self._tab_state = None
            return
        self._apply_word(state, common_prefix(matches))
        self._tab_state = state
        shown = "  ".join(matches[:_MAX_SHOWN_MATCHES])
        more = len(matches) - _MAX_SHOWN_MATCHES
        if more > 0:
            shown += f"  (+{more} more)"
        log = getattr(self.app, "log_message", None)
        if callable(log):
            log(f"Tab: {shown}")

    def _apply_word(self, state: dict, word: str) -> None:
        head = state["before"] + word
        self._set_line(head + state["rest"], len(head))
        state["applied"] = (self.value, self.cursor_position)

    # --- events -----------------------------------------------------------

    def on_focus(self) -> None:
        _log.debug("CommandBar: got focus, has_focus=%s", self.has_focus)
        self.placeholder = self.FOCUSED_PLACEHOLDER
        self._sync_history()
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
        self._history_pos = None
        self._tab_state = None

    def on_key(self, event) -> None:
        _log.debug("CommandBar on_key: key=%r char=%r value=%r",
                    event.key, event.character, self.value)
        # Stopping the event here also keeps it from the app's bindings
        # (Tab would otherwise move focus out of the bar).
        if event.key in ("up", "down"):
            event.stop()
            event.prevent_default()
            self._tab_state = None
            self._recall(-1 if event.key == "up" else 1)
        elif event.key in ("tab", "shift+tab"):
            event.stop()
            event.prevent_default()
            self._complete(1 if event.key == "tab" else -1)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        _log.info("CommandBar submitted: %r", event.value)
        command = event.value.strip()
        self._history_pos = None
        self._draft = ""
        self._tab_state = None
        if command:
            self._remember(command)
            self.post_message(CommandSubmitted(command))
        self.value = ""
