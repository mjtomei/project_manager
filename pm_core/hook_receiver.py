"""Claude Code hook receiver.

Invoked by Claude Code hooks configured in ~/.claude/settings.json.
Reads a JSON payload on stdin (session_id, transcript_path, cwd, ...),
plus an event type argv[1] (e.g. "idle_prompt", "Stop"), and writes an
event record to ~/.pm/hooks/{session_id}.json atomically so pm can
observe turn boundaries without polling.

Kept intentionally tiny — no pm_core imports beyond stdlib so it starts
fast (Claude blocks on hook execution).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path


def _hooks_dir() -> Path:
    return Path.home() / ".pm" / "hooks"


def _write_event(session_id: str, record: dict) -> None:
    d = _hooks_dir()
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

        record = {
            "event_type": event_type,
            "timestamp": time.time(),
            "session_id": session_id,
            "matcher": payload.get("matcher") or payload.get("hook_event_name") or "",
            "cwd": payload.get("cwd") or "",
        }
        _write_event(session_id, record)
    except Exception:
        # Never block Claude on hook failures
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
