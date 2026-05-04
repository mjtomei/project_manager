"""pr-list home-window provider — runs `pm pr list -t --open` on a poll.

The window runs a small in-process Python loop (no `watch` shell dep),
re-rendering every ~5 seconds and on demand via a sentinel file.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from pm_core import tmux as tmux_mod
from pm_core.paths import pm_home


WINDOW_NAME = "pm-home"
POLL_SECONDS = 5.0


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

        # Resolve project root now (in the pm-side process) so we can pass
        # it via cwd to the home-window loop — the loop runs detached and
        # can't reliably re-derive it from $PWD if the session was started
        # from a workdir clone.
        from pm_core import store
        try:
            project_root = store.find_project_root()
        except FileNotFoundError:
            project_root = Path.cwd()

        # Build the loop command.  Use the same Python interpreter pm
        # itself runs under so containerized installs hit the right venv.
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

def _render_once() -> str:
    """Return the rendered PR list text, or an error line on failure."""
    from datetime import datetime

    from pm_core import store
    from pm_core.cli.helpers import _pr_display_id

    try:
        root = store.find_project_root()
        data = store.load(root)
    except Exception as e:
        return f"pm pr list (home): error loading project: {e}"

    prs = data.get("prs") or []
    prs = [p for p in prs if p.get("status") not in ("closed", "merged")]
    prs = sorted(
        prs,
        key=lambda p: p.get("updated_at") or p.get("created_at") or "",
        reverse=True,
    )

    status_icons = {
        "pending": "⏳",
        "in_progress": "🔨",
        "in_review": "👀",
        "qa": "🧪",
        "merged": "✅",
        "closed": "🚫",
        "blocked": "🚫",
    }
    active_pr = data.get("project", {}).get("active_pr")
    lines: list[str] = []
    header = (
        f"pm pr list -t --open    "
        f"(updated {datetime.now().strftime('%H:%M:%S')})"
    )
    lines.append(header)
    lines.append("=" * len(header))
    if not prs:
        lines.append("No open PRs.")
    for p in prs:
        icon = status_icons.get(p.get("status", "pending"), "?")
        deps = p.get("depends_on") or []
        dep_str = f" <- [{', '.join(deps)}]" if deps else ""
        machine = p.get("agent_machine")
        machine_str = f" ({machine})" if machine else ""
        active_str = " *" if p["id"] == active_pr else ""
        ts = p.get("updated_at") or p.get("created_at") or ""
        ts_str = ""
        if ts:
            try:
                dt = datetime.fromisoformat(ts).astimezone()
                ts_str = f" [{dt.strftime('%Y-%m-%d %H:%M')}]"
            except ValueError:
                ts_str = f" [{ts}]"
        lines.append(
            f"  {icon} {_pr_display_id(p)}: {p.get('title', '???')} "
            f"[{p.get('status', '?')}]{dep_str}{machine_str}{active_str}{ts_str}"
        )
    return "\n".join(lines)


def _loop_main(session: str) -> None:
    sentinel = _refresh_sentinel(session)
    # Seed last_mtime from any existing sentinel so we don't double-render
    # on startup if a stale sentinel is already on disk.
    try:
        last_mtime: float = sentinel.stat().st_mtime
    except FileNotFoundError:
        last_mtime = 0.0
    while True:
        # Clear screen and render. Catch all render errors so a transient
        # bug doesn't kill the long-lived window.
        sys.stdout.write("\033[2J\033[H")
        try:
            body = _render_once()
        except Exception as e:
            body = f"pm pr list (home): render error: {e}"
        sys.stdout.write(body)
        sys.stdout.write("\n")
        sys.stdout.flush()

        # Sleep up to POLL_SECONDS, but wake immediately on sentinel touch.
        deadline = time.monotonic() + POLL_SECONDS
        while True:
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
            time.sleep(min(0.25, remaining))


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
