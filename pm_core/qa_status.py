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
import select
import subprocess
import sys
import time
from pathlib import Path

logging.basicConfig(
    filename="/tmp/qa_status_debug.log",
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(message)s",
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
}

_REFRESH_INTERVAL = 2.0  # seconds


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


def _render(status: dict | None, selected: int, rows: int, cols: int) -> str:
    """Render the status dashboard as an ANSI string."""
    lines: list[str] = []

    if status is None:
        lines.append(f"{_DIM}Waiting for qa_status.json...{_RESET}")
        return _CLEAR_SCREEN + "\n".join(
            _pad_line(l, cols) for l in lines)

    pr_id = status.get("pr_id", "?")
    scenarios = status.get("scenarios", [])
    overall = status.get("overall", "")

    lines.append(f"{_BOLD}QA Status: {pr_id}{_RESET}")
    lines.append("")

    # Fixed columns: prefix(2) + idx(3) + gap(2) + gap(2) + verdict(14) = 23
    title_width = max(cols - 28, 10)
    lines.append(f"  {'#':>3}  {'Scenario':<{title_width}}  {'Verdict'}")
    lines.append(f"  {'---':>3}  {'-' * title_width}  {'-' * 14}")

    for i, sc in enumerate(scenarios):
        idx = sc.get("index", "?")
        title = _truncate(sc.get("title", ""), title_width)
        verdict = sc.get("verdict", "")

        color = _VERDICT_COLORS.get(verdict, _DIM)
        verdict_display = verdict if verdict else f"{_DIM}pending{_RESET}"
        if verdict:
            verdict_display = f"{color}{verdict}{_RESET}"

        prefix = "  "
        suffix = ""
        if i == selected:
            prefix = f"{_REVERSE}  "
            suffix = _RESET

        lines.append(f"{prefix}{idx:>3}  {title:<{title_width}}  {verdict_display}{suffix}")

    lines.append("")

    if overall:
        color = _VERDICT_COLORS.get(overall, "")
        lines.append(f"  Overall: {color}{_BOLD}{overall}{_RESET}")
    else:
        done = sum(1 for s in scenarios
                   if s.get("verdict") and s.get("verdict") != "interactive")
        total = sum(1 for s in scenarios if s.get("verdict") != "interactive")
        lines.append(f"  {_DIM}Progress: {done}/{total} scenarios complete{_RESET}")

    lines.append("")
    lines.append(f"{_DIM}  j/k: navigate  Enter: go to window  q: quit{_RESET}")

    # Pad each line to full width to clear stale content from previous renders
    padded = [_pad_line(l, cols) for l in lines]
    # Fill remaining rows with blank lines to clear any old content below
    while len(padded) < rows:
        padded.append(" " * cols)

    return _CLEAR_SCREEN + "\n".join(padded)


def _find_attached_session(base: str) -> str:
    """Find the attached grouped session for the base session.

    Returns the first grouped session with attached clients, or the base
    session as fallback.  This avoids importing pm_core (which may not be
    on PYTHONPATH when this script runs standalone).
    """
    try:
        result = subprocess.run(
            ["tmux", "list-sessions", "-F", "#{session_name} #{session_attached}"],
            capture_output=True, text=True,
        )
        for line in result.stdout.strip().splitlines():
            parts = line.rsplit(" ", 1)
            if len(parts) == 2:
                name, attached = parts
                if (name == base or name.startswith(base + "~")) and attached != "0":
                    return name
    except Exception:
        pass
    return base


def _switch_to_window(session: str, window_name: str) -> None:
    """Switch tmux to the given window.

    Uses the attached grouped session (not the base session) so only the
    current terminal switches windows.
    """
    try:
        target = _find_attached_session(session)
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

            sys.stdout.write(_render(status, selected, rows, cols))
            sys.stdout.flush()

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
    while True:
        status = _load_status(path)
        rows, cols = _get_terminal_size()

        sys.stdout.write(_render(status, -1, rows, cols))
        sys.stdout.flush()

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
