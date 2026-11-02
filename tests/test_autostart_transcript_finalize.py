"""Disabling auto-start never freezes, copies or moves a session log.

S31 (pr-592e4bd): ``A`` removing the last target disables auto-start, and the
old ``_finalize_all_transcripts`` replaced every transcript symlink in the run
dir with a copy -- including the post-merge repo-update window's, which the
idle tracker (``merge:<pr>``) still reads.  The window's later MERGED never
reached the copy, so the TUI kept reporting INPUT_REQUIRED forever.  Deciding
which sessions were "finished" was the guess that went wrong (and, in #241,
let an obsolete completion freeze a newer loop's live file).

Every collector now reads its exact session's native log, recorded in the
session ledger at launch; there is nothing to finalize.  Disabling must leave
native logs, the ledger, and any pre-upgrade ``pm/transcripts`` content (which
may be the only remaining evidence) exactly as they were.
"""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from pm_core import session_log
from pm_core.pane_idle import PaneIdleTracker
from pm_core.tui import auto_start
from pm_core.verdict_transcript import extract_verdict_from_transcript

from tests.test_autostart_multi_target import FakeApp, _pr

SID_MERGE = "11111111-2222-4333-8444-555555555555"
SID_DONE = "66666666-7777-4888-9999-000000000000"


def _assistant(text):
    return json.dumps({"type": "assistant", "message": {
        "role": "assistant", "content": [{"type": "text", "text": text}]}}) + "\n"


def _user(text):
    return json.dumps({"type": "user", "message": {
        "role": "user", "content": text}}) + "\n"


@pytest.fixture(autouse=True)
def _no_runtime_mirror():
    with patch("pm_core.pane_idle._runtime_mirror_register"), \
         patch("pm_core.pane_idle._runtime_mirror_clear"):
        yield


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    a = FakeApp([_pr("pr-m", "in_review")], root=tmp_path / "pm")
    a._auto_start = True
    a._auto_start_run_id = "autostart-pr-m-abc"
    a._auto_start_targets = {"pr-m": {}}
    a._pane_idle_tracker = PaneIdleTracker()
    a._update_display = lambda: None
    return a


def _launch(phase, sid, run, wd):
    rec = session_log.register(
        session_log.SessionLaunch(subject="pr-m", phase=phase, run_id=run),
        sid, str(wd))
    log = Path(rec.log)
    log.parent.mkdir(parents=True, exist_ok=True)
    return rec, log


def _tree(root: Path) -> dict:
    """Every file under *root* with its type, inode and content."""
    out = {}
    for p in sorted(root.rglob("*")):
        st = os.lstat(p)
        out[str(p.relative_to(root))] = (
            "link" if p.is_symlink() else "file" if p.is_file() else "dir",
            st.st_ino,
            os.readlink(p) if p.is_symlink()
            else p.read_bytes() if p.is_file() else None)
    return out


def test_disable_keeps_live_merge_session_so_merged_is_detected(app,
                                                                 tmp_path):
    run = auto_start.get_run_id(app)
    rec, live = _launch("merge", SID_MERGE, run, tmp_path / "wd")
    live.write_text(_user("update the repo") + _assistant("blocked\nINPUT_REQUIRED"))
    _, done = _launch("signoff", SID_DONE, run, tmp_path / "wd")
    done.write_text(_user("sign off") + _assistant("SIGNOFF_MERGE"))
    tracker = app._pane_idle_tracker
    tracker.register("merge:pr-m", "%24", str(session_log.log_path(rec)))
    assert extract_verdict_from_transcript(
        tracker.get_transcript_path("merge:pr-m"),
        ("MERGED", "INPUT_REQUIRED")) == "INPUT_REQUIRED"
    claude = tmp_path / "home" / ".claude"
    before = _tree(claude)
    ledger_before = session_log.ledger_path("pr-m").read_bytes()

    auto_start._disable(app)

    assert _tree(claude) == before                   # no log touched
    assert session_log.ledger_path("pr-m").read_bytes() == ledger_before
    assert not (app._root / "transcripts").exists()  # no tree recreated
    # The user answers in the merge window; Claude ends with MERGED.
    with live.open("a") as f:
        f.write(_user("The checkout is fixed, please finish")
                + _assistant("updated\nMERGED"))
    assert extract_verdict_from_transcript(
        tracker.get_transcript_path("merge:pr-m"),
        ("MERGED", "INPUT_REQUIRED")) == "MERGED"


def test_disable_leaves_pre_upgrade_transcripts_untouched(app, tmp_path):
    """Legacy run dirs (links and frozen copies) are evidence: never
    finalized, rewritten or deleted after the upgrade."""
    tdir = app._root / "transcripts" / auto_start.get_run_id(app)
    tdir.mkdir(parents=True)
    native = tmp_path / "home" / ".claude" / "projects" / "-x" / f"{SID_MERGE}.jsonl"
    native.parent.mkdir(parents=True)
    native.write_text(_assistant("INPUT_REQUIRED"))
    (tdir / "merge-pr-m.jsonl").symlink_to(native)
    (tdir / "signoff-pr-m.jsonl").write_text(
        json.dumps({"type": "assistant", "sessionId": SID_DONE}) + "\n")
    (tdir / "signoff-pr-m.head").write_text("abc\n")
    before = _tree(app._root / "transcripts")

    auto_start._disable(app)

    assert _tree(app._root / "transcripts") == before
