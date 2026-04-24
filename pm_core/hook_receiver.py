"""Claude Code hook receiver.

Invoked by Claude Code hooks configured in ~/.claude/settings.json.
Reads a JSON payload on stdin (session_id, transcript_path, cwd, ...),
plus an event type argv[1] (e.g. "idle_prompt", "Stop"), and writes an
event record to ~/.pm/hooks/{session_tag}/{session_id}.json atomically
so pm can observe turn boundaries without polling.

The session_tag is derived from the Claude process's cwd so events are
scoped to the pm session that owns the directory.  This keeps one pm
session's event files out of another's reader sweep.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path


def _session_tag_from_cwd(cwd: str) -> str | None:
    """Mirror pm_core.paths.get_session_tag() but without importing pm_core."""
    try:
        from pm_core.paths import get_session_tag
        return get_session_tag(start_path=Path(cwd) if cwd else None,
                               use_github_name=False)
    except Exception:
        return None


def _hooks_dir(session_tag: str | None) -> Path:
    base = Path.home() / ".pm" / "hooks"
    return base / session_tag if session_tag else base / "_notag"


def _write_event(session_id: str, record: dict, session_tag: str | None) -> None:
    d = _hooks_dir(session_tag)
    d.mkdir(parents=True, exist_ok=True)
    target = d / f"{session_id}.json"
    fd, tmp = tempfile.mkstemp(dir=d, prefix=f".{session_id}-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(record, f)
        os.replace(tmp, target)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def main(argv: list[str]) -> int:
    try:
        event_type = argv[1] if len(argv) > 1 else "unknown"
        try:
            raw = sys.stdin.read()
            payload = json.loads(raw) if raw.strip() else {}
        except (ValueError, OSError):
            payload = {}

        session_id = payload.get("session_id") or ""
        if not session_id:
            return 0

        cwd = payload.get("cwd") or os.getcwd()
        session_tag = _session_tag_from_cwd(cwd)

        record = {
            "event_type": event_type,
            "timestamp": time.time(),
            "session_id": session_id,
            "session_tag": session_tag or "",
            "matcher": payload.get("matcher") or payload.get("hook_event_name") or "",
            "cwd": cwd,
        }
        _write_event(session_id, record, session_tag)
    except Exception:
        # Never block Claude on hook failures
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
