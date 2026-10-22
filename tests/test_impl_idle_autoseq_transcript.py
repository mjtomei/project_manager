"""Regression: an impl session launched by ``pm pr auto-sequence`` must be
idle-tracked by the TUI under its own session.

A sign-off IMPL return's rework launch can be taken by an auto-sequence tick
instead of the TUI.  The tick records its transcript symlink under
``transcripts/auto-sequence/<pr>/``; the auto-start run's own
``impl-<pr>.jsonl`` still names the killed pre-return session.  Pre-fix the
TUI re-registered the new pane under that dead session, never saw the rework
go idle, and the PR sat in ``in_progress`` for good.
"""

import os
import time
from unittest.mock import patch

from pm_core.tui import auto_start
from pm_core.tui import review_loop_ui

from tests.test_autostart_retarget_regression import _App

OLD = "0dba8b5a-24a4-4361-8fe8-c550aef8fed8"
NEW = "444e4358-b2eb-4173-ba74-4c18e0121d9e"


class _RecordingTracker:
    def __init__(self):
        self.registered = {}

    def is_tracked(self, key):
        return key in self.registered

    def is_gone(self, key):
        return False

    def register(self, key, pane_id, transcript_path):
        self.registered[key] = (pane_id, transcript_path)

    def poll(self, key):
        return False

    def became_idle(self, key):
        return False

    def tracked_keys(self):
        return []


def _link(path, sid, mtime):
    path.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(f"/nonexistent/projects/x/{sid}.jsonl", path)
    os.utime(path, (mtime, mtime), follow_symlinks=False)


def _register(tmp_path):
    prs = [{"id": "pr-r", "status": "in_progress", "depends_on": [],
            "workdir": "/w/r"}]
    app = _App(prs, tmp_path)
    app._session_name = "s"
    app._pending_merge_prs = set()
    app._auto_start_run_id = "autostart-run"
    app._pane_idle_tracker = _RecordingTracker()
    with patch.object(review_loop_ui, "_find_impl_pane", return_value="%15"), \
         patch.object(review_loop_ui, "_prune_untracked_trust"), \
         patch.object(auto_start, "hold_spec_if_due"):
        review_loop_ui._poll_impl_idle(app)
    pane_id, transcript = app._pane_idle_tracker.registered["pr-r"]
    return pane_id, os.readlink(transcript)


def test_rework_launched_by_auto_sequence_tracked_under_its_session(tmp_path):
    now = time.time()
    _link(tmp_path / "transcripts" / "autostart-run" / "impl-pr-r.jsonl",
          OLD, now - 400)
    _link(tmp_path / "transcripts" / "auto-sequence" / "pr-r"
          / "impl-pr-r.jsonl", NEW, now - 10)
    assert _register(tmp_path) == ("%15", f"/nonexistent/projects/x/{NEW}.jsonl")


def test_run_launch_newer_than_old_auto_sequence_link_wins(tmp_path):
    now = time.time()
    _link(tmp_path / "transcripts" / "auto-sequence" / "pr-r"
          / "impl-pr-r.jsonl", OLD, now - 400)
    _link(tmp_path / "transcripts" / "autostart-run" / "impl-pr-r.jsonl",
          NEW, now - 10)
    assert _register(tmp_path) == ("%15", f"/nonexistent/projects/x/{NEW}.jsonl")
