"""pr-list home-window provider — runs `pm pr list -t --open` on a poll.

The window runs a small in-process Python loop (no `watch` shell dep).
The loop wakes on a short tick, on sentinel touch, or on SIGWINCH —
each is just a *check* trigger; whether to actually repaint is
decided by hashing the rendered output and comparing to the last
written hash. A quiet pm produces a quiet pm-home: no flicker, no
wasted clears.
"""

from __future__ import annotations

import hashlib
import os
import signal
import sys
import time
from pathlib import Path

from pm_core import tmux as tmux_mod
from pm_core.paths import pm_home


WINDOW_NAME = "pm-home"
TICK_SECONDS = 0.75
DEFAULT_SIZE = (80, 24)


def _refresh_sentinel(session: str) -> Path:
    """Per-base-session sentinel file: touched by refresh(), polled by the loop."""
    base = session.split("~")[0]
    runtime = pm_home() / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    return runtime / f"home-refresh-{base}"


class PrListProvider:
    name = "pr-list"
    window_name = WINDOW_NAME

    def ensure_window(self, session: str) -> str:
        existing = tmux_mod.find_window_by_name(session, WINDOW_NAME)
        if existing:
            return WINDOW_NAME

        from pm_core import store
        try:
            project_root = store.find_project_root()
        except FileNotFoundError:
            project_root = Path.cwd()

        py = sys.executable or "python3"
        cmd = (
            f"{py} -m pm_core.home_window.pr_list "
            f"--session {session}"
        )
        tmux_mod.new_window(
            session, WINDOW_NAME, cmd, str(project_root), switch=False,
        )
        new_win = tmux_mod.find_window_by_name(session, WINDOW_NAME)
        if new_win:
            tmux_mod.set_shared_window_size(session, new_win["id"])
        return WINDOW_NAME

    def refresh(self, session: str) -> None:
        sentinel = _refresh_sentinel(session)
        try:
            sentinel.touch()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Loop entrypoint: python -m pm_core.home_window.pr_list --session <name>
# ---------------------------------------------------------------------------

def _terminal_size() -> tuple[int, int]:
    try:
        ts = os.get_terminal_size()
        return (ts.columns, ts.lines)
    except OSError:
        return DEFAULT_SIZE


def _truncate(line: str, width: int) -> str:
    if width <= 0:
        return ""
    if len(line) <= width:
        return line
    if width == 1:
        return "…"
    return line[: width - 1] + "…"


def _format_relative(seconds: float) -> str:
    s = int(seconds)
    if s < 60:
        return f"{s}s ago"
    m = s // 60
    if m < 60:
        return f"{m}m ago"
    h = m // 60
    return f"{h}h ago"


def _render_content(width: int, height: int) -> tuple[str, int]:
    """Render the size-fitted content body, *without* the staleness suffix.

    Returns (body, header_width) — the caller composes the header with
    the relative-time string and concatenates with the body. Splitting
    this out lets us hash the size+content separately from the
    staleness phrasing so we can reset the 'last changed' clock only on
    real content changes.
    """
    from pm_core import store
    from pm_core.cli.helpers import format_pr_line

    try:
        root = store.find_project_root()
        data = store.load(root)
    except Exception as e:
        msg = _truncate(f"pm pr list (home): error loading project: {e}",
                        width)
        return msg, len(msg)

    prs = data.get("prs") or []
    prs = [p for p in prs if p.get("status") not in ("closed", "merged")]
    prs = sorted(
        prs,
        key=lambda p: p.get("updated_at") or p.get("created_at") or "",
        reverse=True,
    )

    active_pr = data.get("project", {}).get("active_pr")
    body_lines: list[str] = []

    if not prs:
        body_lines.append(_truncate("No open PRs.", width))
    else:
        # Reserve: 2 header rows (title + ruler), and 1 footer row when
        # the list overflows the visible area.
        rows_for_prs = max(height - 2, 0)
        overflow = len(prs) > rows_for_prs
        visible_n = max(rows_for_prs - 1, 0) if overflow else rows_for_prs

        for p in prs[:visible_n]:
            body_lines.append(_truncate(
                format_pr_line(p, active_pr=active_pr, with_timestamp=True),
                width,
            ))
        if overflow:
            more = len(prs) - visible_n
            body_lines.append(_truncate(f"(… and {more} more)", width))

    return "\n".join(body_lines), 0


def _compose(header_text: str, body: str, width: int, height: int) -> str:
    head = _truncate(header_text, width)
    ruler = _truncate("=" * len(head), width)
    parts = [head, ruler]
    if body:
        parts.append(body)
    # Cap to height rows.
    return "\n".join(parts[: max(height, 1)] if height < len(parts)
                     else parts)


def _hash(*parts: str) -> str:
    h = hashlib.blake2b(digest_size=16)
    for p in parts:
        h.update(p.encode("utf-8", "replace"))
        h.update(b"\0")
    return h.hexdigest()


def _loop_main(session: str) -> None:
    sentinel = _refresh_sentinel(session)
    try:
        last_mtime: float = sentinel.stat().st_mtime
    except FileNotFoundError:
        last_mtime = 0.0

    winch_flag = {"set": False}

    def _on_winch(signum, frame):  # pragma: no cover - signal path
        winch_flag["set"] = True

    try:
        signal.signal(signal.SIGWINCH, _on_winch)
    except (ValueError, OSError):
        pass

    last_paint_hash: str | None = None
    last_content_hash: str | None = None
    last_change_mono: float = time.monotonic()

    while True:
        width, height = _terminal_size()

        try:
            body, _ = _render_content(width, height)
        except Exception as e:
            body = f"pm pr list (home): render error: {e}"

        content_hash = _hash(f"{width}x{height}", body)
        if content_hash != last_content_hash:
            last_change_mono = time.monotonic()
            last_content_hash = content_hash

        age = time.monotonic() - last_change_mono
        header = f"pm pr list -t --open  (updated {_format_relative(age)})"
        screen = _compose(header, body, width, height)

        # Paint hash includes the bucketed staleness so we repaint when
        # the bucket flips (Ns -> N+1s, Nm -> N+1m), without burning a
        # repaint every sub-second tick when content hasn't changed.
        paint_hash = _hash(content_hash, _format_relative(age))
        if paint_hash != last_paint_hash:
            sys.stdout.write("\033[2J\033[H")
            sys.stdout.write(screen)
            sys.stdout.write("\n")
            sys.stdout.flush()
            last_paint_hash = paint_hash

        deadline = time.monotonic() + TICK_SECONDS
        while True:
            if winch_flag["set"]:
                winch_flag["set"] = False
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                mtime = sentinel.stat().st_mtime
            except FileNotFoundError:
                mtime = 0.0
            if mtime > last_mtime:
                last_mtime = mtime
                break
            time.sleep(min(0.1, remaining))


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--session", required=True)
    args = parser.parse_args(argv)

    try:
        _loop_main(args.session)
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
