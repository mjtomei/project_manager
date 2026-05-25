"""QA status dashboard — runs inside a tmux status pane.

Reads qa_status.json and displays a live ANSI-rendered table showing
each scenario's index, title, and verdict with color coding.

Navigation (raw terminal input via termios):
  j / Down   — highlight next scenario
  k / Up     — highlight previous scenario
  Enter      — switch to the highlighted scenario's tmux window
  q          — quit

Refresh: re-reads qa_status.json every 2 seconds using select() with
timeout to handle both keyboard input and periodic refresh.

Invocation:
  python3 /path/to/pm_core/qa_status.py /path/to/qa_status.json <session>
"""

import json
import logging
import os
import re
import select
import subprocess
import sys
import time
from pathlib import Path

logging.basicConfig(
    filename="/tmp/qa_status_debug.log",
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)-5s [qa_status] %(message)s",
    datefmt="%H:%M:%S",
)
_log = logging.getLogger("pm.qa_status")


# ANSI color codes
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_RED = "\033[31m"
_DIM = "\033[2m"
_BOLD = "\033[1m"
_REVERSE = "\033[7m"
_RESET = "\033[0m"
_HIDE_CURSOR = "\033[?25l"
_SHOW_CURSOR = "\033[?25h"
_CLEAR_SCREEN = "\033[H\033[2J"

_VERDICT_COLORS = {
    "PASS": _GREEN,
    "NEEDS_WORK": _YELLOW,
    "INPUT_REQUIRED": _RED,
    "interactive": _DIM,
    "queued": _DIM,
}

_REFRESH_INTERVAL = 1.0  # seconds
_SPINNER_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")


def _load_status(path: Path) -> dict | None:
    """Load qa_status.json, returning None if missing or invalid."""
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _truncate(text: str, width: int) -> str:
    """Truncate text to width, adding ellipsis if needed."""
    if len(text) <= width:
        return text
    return text[:width - 1] + "\u2026"


def _pad_line(text: str, cols: int) -> str:
    """Pad a line with spaces to exactly *cols* visible characters.

    Counts only visible characters (strips ANSI escape sequences for
    length calculation) so the padding clears any leftover content from
    a previous render cycle.
    """
    import re as _re
    visible_len = len(_re.sub(r'\033\[[0-9;]*m', '', text))
    if visible_len < cols:
        return text + " " * (cols - visible_len)
    return text


def _render(status: dict | None, selected: int, rows: int, cols: int,
            tick: int = 0) -> str:
    """Render the status dashboard as an ANSI string."""
    lines: list[str] = []

    if status is None:
        lines.append(f"{_DIM}Waiting for qa_status.json...{_RESET}")
        return _CLEAR_SCREEN + "\n".join(
            _pad_line(l, cols) for l in lines)

    pr_id = status.get("pr_id", "?")
    scenarios = status.get("scenarios", [])
    overall = status.get("overall", "")
    error = status.get("error", "")

    lines.append(f"{_BOLD}QA Status: {pr_id}{_RESET}")
    lines.append("")

    # Show error block if present (spec missing, no scenarios, etc.)
    if error:
        lines.append(f"  {_RED}{_BOLD}ERROR{_RESET}")
        lines.append("")
        for err_line in error.split("\n"):
            lines.append(f"  {_RED}{err_line}{_RESET}")
        lines.append("")
        lines.append(f"{_DIM}  q: quit{_RESET}")
        padded = [_pad_line(l, cols) for l in lines]
        while len(padded) < rows:
            padded.append(" " * cols)
        return _CLEAR_SCREEN + "\n".join(padded)

    # Fixed columns: prefix(2) + idx(3) + gap(2) + gap(2) + verdict(14) = 23
    title_width = max(cols - 28, 10)
    lines.append(f"  {'#':>3}  {'Scenario':<{title_width}}  {'Verdict'}")
    lines.append(f"  {'---':>3}  {'-' * title_width}  {'-' * 14}")

    spinner = _SPINNER_FRAMES[tick % len(_SPINNER_FRAMES)]

    for i, sc in enumerate(scenarios):
        idx = sc.get("index", "?")
        title = _truncate(sc.get("title", ""), title_width)
        verdict = sc.get("verdict", "")
        verdict_reason = sc.get("verdict_reason", "")

        if "(verifying" in verdict:
            # Animated spinner for verdicts being verified
            # Format: "PASS (verifying)" or "PASS (verifying:2)"
            m = re.search(r'\(verifying(?::(\d+))?\)', verdict)
            fails = int(m.group(1)) if m and m.group(1) else 0
            fail_hint = f" {_RED}({fails}){_RESET}" if fails else ""
            verdict_display = (
                f"{_YELLOW}{spinner} verifying{_RESET}{fail_hint}"
            )
        elif "(retrying" in verdict:
            # Back to pending after verification flagged — show retry count
            m = re.search(r'\(retrying:(\d+)\)', verdict)
            fails = int(m.group(1)) if m else 0
            verdict_display = (
                f"{_DIM}pending{_RESET} "
                f"{_RED}({fails}){_RESET}"
            )
        elif verdict:
            color = _VERDICT_COLORS.get(verdict, _DIM)
            verdict_display = f"{color}{verdict}{_RESET}"
        else:
            verdict_display = f"{_DIM}pending{_RESET}"

        prefix = "  "
        suffix = ""
        if i == selected:
            prefix = f"{_REVERSE}  "
            suffix = _RESET

        lines.append(f"{prefix}{idx:>3}  {title:<{title_width}}  {verdict_display}{suffix}")
        if verdict_reason:
            # Render the reason on a continuation line, indented to align
            # under the title column and dimmed so it doesn't compete with
            # the verdict colour above.
            reason_indent = " " * (2 + 3 + 2)  # prefix + idx col + gap
            reason_text = _truncate(verdict_reason,
                                    max(cols - len(reason_indent) - 4, 10))
            lines.append(f"{reason_indent}{_DIM}↳ {reason_text}{_RESET}")

    lines.append("")

    if overall:
        color = _VERDICT_COLORS.get(overall, "")
        lines.append(f"  Overall: {color}{_BOLD}{overall}{_RESET}")
    else:
        done = sum(1 for s in scenarios
                   if s.get("verdict") and s.get("verdict") not in ("interactive", "queued")
                   and "(retrying" not in s.get("verdict", "")
                   and "(verifying" not in s.get("verdict", ""))
        total = sum(1 for s in scenarios if s.get("verdict") != "interactive")
        queued = sum(1 for s in scenarios if s.get("verdict") == "queued")
        verifying = sum(1 for s in scenarios if "(verifying" in s.get("verdict", ""))
        progress = f"  {_DIM}Progress: {done}/{total} scenarios complete"
        if verifying:
            progress += f" ({verifying} verifying)"
        if queued:
            progress += f" ({queued} queued)"
        progress += f"{_RESET}"
        lines.append(progress)

    lines.append("")
    lines.append(f"{_DIM}  j/k: navigate  Enter: go to window  q: quit{_RESET}")

    # Pad each line to full width to clear stale content from previous renders
    padded = [_pad_line(l, cols) for l in lines]
    # Fill remaining rows with blank lines to clear any old content below
    while len(padded) < rows:
        padded.append(" " * cols)

    return _CLEAR_SCREEN + "\n".join(padded)


def _caller_switch_target(base: str) -> str | None:
    """Return the caller's OWN grouped session for a focus-mutating switch.

    Standalone mirror of ``pm_core.tmux.caller_switch_target`` (this script
    runs by path and deliberately avoids importing the tmux module).  Uses
    ``$TMUX_PANE`` to identify the pane's session; returns it only when it is
    *base* or one of its grouped sessions (``base~N``), else ``None``.

    Crucially there is NO "first attached grouped session" fallback: a
    focus-mutating ``select-window`` must never hijack an *arbitrary* attached
    grouped session that happens to be viewing something else (the bug fixed
    in pr-0b4e1a9).  No attached-client check is needed — the caller is by
    construction in this pane's session, so switching it steals nobody's
    focus.

    The caller's session is resolved from ``$TMUX`` (its session id is fixed
    at pane-spawn time, so it deterministically names the session the pane
    *belongs to*).  ``display-message -t <pane>`` is only a fallback: for a
    window shared across grouped sessions it resolves to the most-recently-
    *attached* grouped session, which may be an unrelated one — using it
    alone could hijack that session's focus.
    """
    current = _caller_session_from_env() or _session_name_for_pane()
    if current and (current == base or current.startswith(base + "~")):
        return current
    return None


def _caller_session_from_env() -> str | None:
    """Resolve the caller pane's OWN session name from ``$TMUX``.

    ``$TMUX`` is ``socket_path,server_pid,session_id``; the session id is
    set when the pane process is spawned, so it names the session the pane
    belongs to even for a window shared across grouped sessions.
    """
    tmux_env = os.environ.get("TMUX", "")
    parts = tmux_env.split(",")
    if len(parts) < 3 or not parts[-1].strip():
        return None
    session_id = "$" + parts[-1].strip()
    try:
        result = subprocess.run(
            ["tmux", "display-message", "-p", "-t", session_id, "#{session_name}"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None
    except Exception:
        return None


def _session_name_for_pane() -> str | None:
    """Fallback caller-session resolution via ``$TMUX_PANE`` (activity-based)."""
    pane = os.environ.get("TMUX_PANE")
    if not pane:
        return None
    try:
        result = subprocess.run(
            ["tmux", "display-message", "-p", "-t", pane, "#{session_name}"],
            capture_output=True, text=True,
        )
        return result.stdout.strip() or None
    except Exception:
        return None


def _switch_to_window(session: str, window_name: str) -> None:
    """Switch tmux to the given window.

    Targets only the caller's OWN client's session (the pane this mirror runs
    in), so a focus change never leaks onto an unrelated grouped session.
    When the caller can't be identified, no switch is issued.
    """
    try:
        target = _caller_switch_target(session)
        if target is None:
            _log.info("switch_to_window: no identifiable caller client; "
                      "skipping switch for %s:%s", session, window_name)
            return
        result = subprocess.run(
            ["tmux", "select-window", "-t", f"{target}:{window_name}"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            _log.warning("select-window failed: %s", result.stderr.strip())
    except Exception:
        _log.warning("switch_to_window error", exc_info=True)


def _get_terminal_size() -> tuple[int, int]:
    """Return (rows, cols) of the terminal."""
    try:
        size = os.get_terminal_size()
        return size.lines, size.columns
    except OSError:
        return 24, 80


def _read_key(fd: int) -> str | None:
    """Read a single keypress, handling escape sequences."""
    ch = os.read(fd, 1)
    if not ch:
        return None
    if ch == b"\x1b":
        # Possible escape sequence
        ready, _, _ = select.select([fd], [], [], 0.05)
        if ready:
            seq = os.read(fd, 2)
            if seq == b"[A":
                return "up"
            elif seq == b"[B":
                return "down"
            # Consume any remaining bytes
            while True:
                ready2, _, _ = select.select([fd], [], [], 0.01)
                if ready2:
                    os.read(fd, 1)
                else:
                    break
        return "escape"
    return ch.decode("utf-8", errors="replace")


def _run_interactive(path: Path, session: str) -> None:
    """Interactive mode with keyboard navigation (requires TTY)."""
    import termios
    import tty

    selected = 0
    tick = 0
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)

    try:
        tty.setcbreak(fd)
        sys.stdout.write(_HIDE_CURSOR)
        sys.stdout.flush()

        while True:
            status = _load_status(path)
            rows, cols = _get_terminal_size()
            num_scenarios = len(status.get("scenarios", [])) if status else 0

            # Clamp selection
            if num_scenarios > 0:
                selected = max(0, min(selected, num_scenarios - 1))

            sys.stdout.write(_render(status, selected, rows, cols, tick=tick))
            sys.stdout.flush()
            tick += 1

            # Wait for input or timeout
            ready, _, _ = select.select([fd], [], [], _REFRESH_INTERVAL)
            if not ready:
                continue  # timeout — just refresh

            key = _read_key(fd)
            if key is None:
                continue

            if key in ("q", "\x03"):  # q or Ctrl-C
                break
            elif key in ("j", "down"):
                if num_scenarios > 0:
                    selected = min(selected + 1, num_scenarios - 1)
            elif key in ("k", "up"):
                if num_scenarios > 0:
                    selected = max(selected - 1, 0)
            elif key in ("\r", "\n"):
                if status and num_scenarios > 0:
                    sc = status["scenarios"][selected]
                    wn = sc.get("window_name", "")
                    _log.info("Enter pressed: selected=%d wn=%r session=%r",
                              selected, wn, session)
                    if wn:
                        _switch_to_window(session, wn)

    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        sys.stdout.write(_SHOW_CURSOR + _CLEAR_SCREEN)
        sys.stdout.flush()


def _run_passive(path: Path) -> None:
    """Passive mode: just refresh the display, no keyboard input."""
    tick = 0
    while True:
        status = _load_status(path)
        rows, cols = _get_terminal_size()

        sys.stdout.write(_render(status, -1, rows, cols, tick=tick))
        sys.stdout.flush()
        tick += 1

        # Exit when overall verdict is set (QA complete)
        if status and status.get("overall"):
            break

        time.sleep(_REFRESH_INTERVAL)


def main(status_path: str, session: str) -> None:
    """Main loop: display status, handle input, refresh periodically."""
    path = Path(status_path)

    # Use interactive mode if stdin is a TTY, passive mode otherwise
    if sys.stdin.isatty():
        _run_interactive(path, session)
    else:
        _run_passive(path)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Usage: python3 {__file__} <status_json_path> <session>",
              file=sys.stderr)
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])
