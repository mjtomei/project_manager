"""Supervisor feedback logging.

Provides structured logging for supervisor watcher feedback — every piece
of feedback a supervisor gives to a target session is recorded to a
persistent JSONL file for post-hoc review.

Log files live at ``~/.pm/logs/supervisor/<supervisor-id>.jsonl``.
"""

import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

from pm_core.paths import configure_logger

_log = configure_logger("pm.supervisor_feedback")

SUPERVISOR_LOG_DIR = Path.home() / ".pm" / "logs" / "supervisor"


@dataclass
class FeedbackEntry:
    """A single piece of supervisor feedback."""
    timestamp: str
    supervisor_id: str
    target_window: str
    target_pane: str
    observation: str
    feedback: str
    injected: bool


def _ensure_log_dir() -> Path:
    """Create the supervisor log directory if it doesn't exist."""
    SUPERVISOR_LOG_DIR.mkdir(parents=True, exist_ok=True)
    return SUPERVISOR_LOG_DIR


def log_feedback(entry: FeedbackEntry) -> Path:
    """Append a feedback entry to the supervisor's JSONL log file.

    Returns the path to the log file.
    """
    log_dir = _ensure_log_dir()
    log_file = log_dir / f"{entry.supervisor_id}.jsonl"
    with open(log_file, "a") as f:
        f.write(json.dumps(asdict(entry)) + "\n")
    _log.info("supervisor_feedback: logged feedback to %s (target=%s)",
              log_file, entry.target_window)
    return log_file


def read_feedback_log(
    supervisor_id: str | None = None,
    target_filter: str | None = None,
    limit: int = 50,
) -> list[FeedbackEntry]:
    """Read feedback entries from log files.

    Args:
        supervisor_id: If set, only read from this supervisor's log.
        target_filter: If set, only return entries whose target_window
            contains this substring.
        limit: Maximum number of entries to return (most recent first).

    Returns:
        List of FeedbackEntry objects, most recent first.
    """
    log_dir = SUPERVISOR_LOG_DIR
    if not log_dir.is_dir():
        return []

    entries: list[FeedbackEntry] = []

    if supervisor_id:
        files = [log_dir / f"{supervisor_id}.jsonl"]
    else:
        files = sorted(log_dir.glob("*.jsonl"), key=os.path.getmtime, reverse=True)

    for log_file in files:
        if not log_file.exists():
            continue
        try:
            lines = log_file.read_text().strip().splitlines()
        except OSError:
            continue
        for line in reversed(lines):
            try:
                data = json.loads(line)
                entry = FeedbackEntry(**data)
                if target_filter and target_filter not in entry.target_window:
                    continue
                entries.append(entry)
                if len(entries) >= limit:
                    break
            except (json.JSONDecodeError, TypeError):
                continue
        if len(entries) >= limit:
            break

    return entries[:limit]


def format_feedback_log(entries: list[FeedbackEntry]) -> str:
    """Format feedback entries for display."""
    if not entries:
        return "No supervisor feedback found."

    lines = []
    for entry in entries:
        ts = entry.timestamp[:19]  # trim to seconds
        injected = "yes" if entry.injected else "no"
        lines.append(
            f"[{ts}] {entry.supervisor_id} -> {entry.target_window}\n"
            f"  Observed: {entry.observation[:200]}\n"
            f"  Feedback: {entry.feedback[:200]}\n"
            f"  Injected: {injected}\n"
        )
    return "\n".join(lines)
