"""The interactive loop behind the prefix+M popup (``pm _popup-cmd``).

The popup stays open across commands until the user dismisses it with
Esc, Ctrl-D, ``exit`` or ``quit``.  It is a pm command surface, not a
general shell: each line is dispatched as a pm command by the *dispatch*
callback, which ``pm_core.cli.session`` supplies.  This module owns
everything around that call:

- line editing through stdlib ``readline``: Up/Down history, Ctrl-R
  reverse search, and Tab completion (:mod:`pm_core.cli.completion`).
  Tab lists the candidates and inserts their common prefix, further Tabs
  cycle through them, and Shift-Tab cycles back;
- history shared with the TUI command bar through
  :mod:`pm_core.command_history`.  The file is re-read before a prompt
  whenever it changed, so a command just typed in the TUI bar is
  recallable here without reopening the popup;
- scrollback.  tmux popups keep no history of their own (no copy-mode),
  so the popup records each command and its output in a bounded
  per-session transcript.  The tail is re-rendered when the popup opens,
  and PgUp (or ``:scrollback``) pages through all of it in ``less``, or
  in a small built-in pager when ``less`` is not installed.
"""

from __future__ import annotations

import ctypes
import os
import re
import select
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import click

from pm_core import command_history as ch
from pm_core.cli.completion import PmCompleter
from pm_core.paths import configure_logger

_log = configure_logger("pm.cli.popup_shell")

PROMPT = "pm> "
BANNER = ("pm popup · ↑/↓ history · Ctrl-R search · Tab complete · "
          "PgUp scrollback · Esc/Ctrl-D close")
EXIT_WORDS = {"exit", "quit"}
SCROLLBACK_CMD = ":scrollback"
CLEAR_CMD = ":clear"

# The PgUp binding appends this byte (Ctrl-_) to the line and submits it,
# so the loop can open the scrollback and then restore the half-typed text.
# Python's readline cannot bind a key to a Python callable directly.
SCROLLBACK_SENTINEL = "\x1f"

_READLINE_BINDINGS = (
    # Our keys go in the emacs keymap only, so a vi-mode ~/.inputrc keeps
    # its own Esc (readline re-selects the vi keymap at each prompt).
    "set keymap emacs",
    "set show-all-if-ambiguous on",
    "set menu-complete-display-prefix on",
    r'"\t": menu-complete',
    r'"\e[Z": menu-complete-backward',
    r'"\e[5~": "\C-e\C-v\C-_\C-m"',
    r'"\e[6~": end-of-history',
    # Esc then Enter typed quickly would otherwise be M-C-m, which
    # switches readline to vi editing mode.
    r'"\e\C-m": accept-line',
    r'"\e\C-j": accept-line',
)

_SGR_RE = re.compile(r"\x1b\[[0-9;:]*m")

# readline.h: a multi-key sequence (e.g. one starting with Esc) is pending.
_RL_STATE_MULTIKEY = 0x0200000


@dataclass
class DispatchResult:
    """What a dispatched popup command produced.

    *status* is shown after the command and stored in the transcript
    (``exit 2``, ``aborted``, ``sent to the TUI``; None for plain
    success).  *output* is the captured output kept for scrollback.
    """
    status: str | None = None
    output: str = ""


Dispatch = Callable[[str, list], DispatchResult]


class _Dismiss(Exception):
    """A lone Esc at the prompt: close the popup."""


class _LoneEscWatcher:
    """Turn a lone Esc at the ``pm>`` prompt into a dismissal.

    Esc is also the first byte of arrow-key and Alt sequences.  Python
    runs readline in callback mode, where readline's own ``keyseq-timeout``
    does not apply, so a bare Esc would wait forever for a second byte.
    While ``input()`` runs, a 50 ms SIGALRM tick reads readline's state
    through ctypes.  When only Esc bytes have been pending for 100 ms and
    no further input is waiting, the handler raises :class:`_Dismiss`.
    Python's readline loop runs signal handlers when ``select`` returns
    EINTR, and it cleans up the line state before ``input()`` re-raises.
    A real escape sequence arrives in one burst, so it is never mistaken
    for a lone Esc.

    Best effort: None from :meth:`create` (no ctypes symbols, libedit, not
    the main thread) leaves Ctrl-D, ``exit`` and ``quit`` to close the
    popup.
    """

    TICK = 0.05
    HOLD = 0.1

    def __init__(self, readline_mod) -> None:
        lib = ctypes.CDLL(readline_mod.__file__)
        self._state = ctypes.c_ulong.in_dll(lib, "rl_readline_state")
        self._klen = ctypes.c_int.in_dll(lib, "rl_key_sequence_length")
        self._kseq = ctypes.c_void_p.in_dll(lib, "rl_executing_keyseq")
        self._since: float | None = None

    @classmethod
    def create(cls, readline_mod) -> "_LoneEscWatcher | None":
        if (not hasattr(signal, "setitimer")
                or threading.current_thread() is not threading.main_thread()
                or "libedit" in (readline_mod.__doc__ or "")):
            return None
        try:
            return cls(readline_mod)
        except (OSError, ValueError, AttributeError, TypeError) as e:
            _log.info("popup: lone-Esc dismiss unavailable: %s", e)
            return None

    def _esc_pending(self) -> bool:
        if not self._state.value & _RL_STATE_MULTIKEY:
            return False
        n, p = self._klen.value, self._kseq.value
        if not p or not 1 <= n <= 8:
            return False
        return set(ctypes.string_at(p, n)) == {0x1b}

    def _on_tick(self, signum, frame) -> None:
        if self._esc_pending() and not _input_ready(sys.stdin.fileno()):
            now = time.monotonic()
            if self._since is None:
                self._since = now
            elif now - self._since >= self.HOLD:
                self._since = None
                raise _Dismiss()
        else:
            self._since = None

    @contextmanager
    def watching(self):
        self._since = None
        prev = signal.signal(signal.SIGALRM, self._on_tick)
        # Restart interrupted reads/writes; select() still returns EINTR,
        # which is where Python's readline loop runs the handler.
        signal.siginterrupt(signal.SIGALRM, False)
        signal.setitimer(signal.ITIMER_REAL, self.TICK, self.TICK)
        try:
            yield
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, prev)


def _input_ready(fd: int) -> bool:
    try:
        return bool(select.select([fd], [], [], 0)[0])
    except (OSError, ValueError):
        return False


def render_transcript(entries: list[dict]) -> list[str]:
    """Screen lines for transcript *entries*: the prompt and command, the
    output, then a dim ``(status)`` line when there is one."""
    lines: list[str] = []
    for e in entries:
        lines.append(click.style(PROMPT + str(e.get("cmd", "")), bold=True))
        out = str(e.get("output") or "")
        if out.strip():
            lines.extend(out.rstrip("\n").split("\n"))
        if e.get("status"):
            lines.append(click.style(f"({e['status']})", dim=True))
    return lines


class PopupShell:
    """The prefix+M popup loop for one pm session.

    *tag* keys the shared history and the transcript (None: keep both in
    memory for this popup only).  *root* is the session's pm root for
    completion data.  ``dispatch(cmd, parts)`` runs one command.
    """

    def __init__(self, tag: str | None, root: Path | None, dispatch: Dispatch,
                 *, interactive: bool | None = None) -> None:
        self.tag = tag
        self.dispatch = dispatch
        self.completer = PmCompleter(root)
        if interactive is None:
            interactive = sys.stdin.isatty() and sys.stdout.isatty()
        self.interactive = interactive
        self._readline = None
        self._esc: _LoneEscWatcher | None = None
        self._history_sig: object = None
        # Commands/entries that could not be persisted (no tag, I/O error).
        self._unsaved_history: list[str] = []
        self._unsaved_entries: list[dict] = []
        self._restore_text = ""

    # --- loop -------------------------------------------------------------

    def run(self) -> None:
        if self.interactive:
            self._setup_readline()
        self._render_screen()
        while True:
            line = self._read_line()
            if line is None:
                click.echo()
                return
            if line.endswith(SCROLLBACK_SENTINEL):
                self._restore_text = line[:-len(SCROLLBACK_SENTINEL)]
                self.show_scrollback()
                continue
            cmd = line.strip()
            if not cmd:
                continue
            if cmd in EXIT_WORDS:
                return
            if cmd == SCROLLBACK_CMD:
                self.show_scrollback()
                continue
            if cmd == CLEAR_CMD:
                ch.clear_transcript(self.tag)
                self._unsaved_entries.clear()
                click.echo(click.style("(scrollback cleared)", dim=True))
                continue
            self._remember(cmd)
            try:
                parts = shlex.split(cmd)
            except ValueError as e:
                msg = f"Invalid command syntax: {e}"
                click.echo(msg)
                self._record(cmd, msg + "\n", "invalid syntax")
                continue
            if not parts:
                continue
            try:
                result = self.dispatch(cmd, parts)
            except Exception as e:  # keep the popup alive
                _log.exception("popup dispatch failed: %r", cmd)
                result = DispatchResult(status="error", output=f"pm popup: {e}\n")
                click.echo(result.output, nl=False)
            if result.status:
                click.echo(click.style(f"({result.status})", dim=True))
            self._record(cmd, result.output, result.status)

    def _read_line(self) -> str | None:
        """The next submitted line, or None when the user dismisses."""
        rl = self._readline
        if rl is not None:
            self._sync_history()
            if self._restore_text:
                text, self._restore_text = self._restore_text, ""

                def _restore() -> None:
                    rl.insert_text(text)
                    rl.set_startup_hook(None)
                rl.set_startup_hook(_restore)
        watch = self._esc.watching() if self._esc is not None else nullcontext()
        try:
            with watch:
                return input(PROMPT)
        except (EOFError, _Dismiss):
            return None
        except KeyboardInterrupt:
            click.echo("^C")
            return ""

    # --- readline + history -------------------------------------------------

    def _setup_readline(self) -> None:
        try:
            import readline
        except ImportError:
            return
        self._readline = readline
        try:
            readline.set_auto_history(False)  # we add (and persist) lines
        except AttributeError:
            pass
        readline.set_completer(self.completer.readline_complete)
        readline.set_completer_delims(" \t\n")
        if "libedit" in (readline.__doc__ or ""):
            readline.parse_and_bind("bind ^I rl_complete")
            return
        for binding in _READLINE_BINDINGS:
            readline.parse_and_bind(binding)
        self._esc = _LoneEscWatcher.create(readline)

    def _remember(self, cmd: str) -> None:
        if not ch.append_history(cmd, self.tag):
            line = ch.normalize_command(cmd)
            if line:
                self._unsaved_history.append(line)

    def _sync_history(self) -> None:
        """Reload readline's history when the shared file (or our unsaved
        list) changed since the last prompt."""
        rl = self._readline
        sig = (ch.file_signature(ch.history_path(self.tag)),
               len(self._unsaved_history))
        if sig == self._history_sig:
            return
        self._history_sig = sig
        rl.clear_history()
        for line in ch.read_history(self.tag) + self._unsaved_history:
            rl.add_history(line)

    # --- transcript / scrollback ---------------------------------------------

    def _record(self, cmd: str, output: str, status: str | None) -> None:
        entry = ch.make_entry(cmd, output, status)
        if not ch.append_transcript(entry, self.tag):
            self._unsaved_entries.append(entry)
            del self._unsaved_entries[:-ch.TRANSCRIPT_MAX_ENTRIES]

    def _entries(self) -> list[dict]:
        return ch.read_transcript(self.tag) + self._unsaved_entries

    def _render_screen(self) -> None:
        """Banner plus as much of the transcript tail as fits."""
        lines = render_transcript(self._entries())
        rows = shutil.get_terminal_size((80, 24)).lines
        room = max(rows - 3, 0)  # hint, banner, prompt
        tail = lines[-room:] if room else []
        hidden = len(lines) - len(tail)
        if hidden:
            click.echo(click.style(
                f"... {hidden} earlier lines (PgUp to scroll back)", dim=True))
        for ln in tail:
            click.echo(ln)
        click.echo(click.style(BANNER, dim=True))

    def show_scrollback(self) -> None:
        lines = render_transcript(self._entries())
        if not lines:
            click.echo(click.style("(scrollback is empty)", dim=True))
            return
        if not self.interactive:
            click.echo("\n".join(lines))
            return
        less = _find_less()
        shown = False
        if less:
            env = {k: v for k, v in os.environ.items()
                   if k not in ("LESS", "LESSOPEN", "LESSCLOSE")}
            try:
                subprocess.run(
                    [less, "-R", "+G", "-K",
                     "-Pspm scrollback  PgUp/PgDn scroll  /pattern search  q returns"],
                    input="\n".join(lines) + "\n", text=True, env=env)
                shown = True
            except OSError as e:
                _log.info("popup: less failed: %s", e)
        if not shown:
            _builtin_pager(lines)
        click.clear()
        self._render_screen()


def _find_less() -> str | None:
    return shutil.which("less")


_PAGER_KEYS = {
    b"\x1b[5~": "pgup", b"b": "pgup", b"\x02": "pgup",
    b"\x1b[6~": "pgdn", b" ": "pgdn", b"\x06": "pgdn",
    b"\x1b[A": "up", b"\x1bOA": "up", b"k": "up",
    b"\x1b[B": "down", b"\x1bOB": "down", b"j": "down", b"\r": "down",
    b"\x1b[H": "home", b"\x1b[1~": "home", b"g": "home",
    b"\x1b[F": "end", b"\x1b[4~": "end", b"G": "end",
}


def _builtin_pager(lines: list[str]) -> None:
    """Minimal PgUp/PgDn pager for when ``less`` is not installed."""
    import termios
    import tty

    cols, rows = shutil.get_terminal_size((80, 24))
    cols = max(cols, 10)
    page = max(rows - 1, 1)
    wrapped: list[str] = []
    for ln in lines:
        plain = _SGR_RE.sub("", ln).expandtabs()
        wrapped.extend([plain[i:i + cols] for i in range(0, len(plain), cols)]
                       or [""])
    last_top = max(len(wrapped) - page, 0)
    top = last_top
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    out = sys.stdout
    try:
        tty.setcbreak(fd)
        while True:
            body = "\n".join(wrapped[top:top + page])
            status = (f" scrollback {top + 1}-{min(top + page, len(wrapped))}"
                      f"/{len(wrapped)}  PgUp/PgDn/↑/↓ scroll  q returns ")
            out.write("\x1b[H\x1b[2J" + body + f"\x1b[{rows};1H"
                      + click.style(status[:cols], reverse=True))
            out.flush()
            key = os.read(fd, 16)
            if not key or key in (b"q", b"Q", b"\x1b", b"\x03", b"\x04"):
                break
            action = _PAGER_KEYS.get(key)
            if action == "pgup":
                top -= page
            elif action == "pgdn":
                top += page
            elif action == "up":
                top -= 1
            elif action == "down":
                top += 1
            elif action == "home":
                top = 0
            elif action == "end":
                top = last_top
            top = min(max(top, 0), last_top)
    except KeyboardInterrupt:
        pass
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
