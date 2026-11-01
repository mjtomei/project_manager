"""Disabling auto-start must not freeze a transcript anything still reads.

S31 (pr-592e4bd): removing the last target disables auto-start, and
``_finalize_all_transcripts`` replaced every transcript symlink in the run
dir with a copy -- including the post-merge repo-update window's, which the
idle tracker (``merge:<pr>``) still reads.  The window's later MERGED never
reached the copy, so the TUI kept reporting INPUT_REQUIRED forever.

pr-9ee4d64 removed the guess rather than refining it: a bulk sweep no
longer freezes *canonical* links at all.  A canonical name
(``impl-<pr>.jsonl``, ``merge-<pr>.jsonl``, ``signoff-<pr>.jsonl``, …)
points at the attempt that is live now, and every reader -- the idle
tracker, a running review loop, the sign-off driver, a repo-update window
-- keeps seeing the native JSONL grow, because the link is never replaced
behind their back.  A canonical is replaced, and the outgoing session
archived under ``archive/<stem>.<sid>.jsonl``, only when a new attempt
launches on the same path.  Those archive entries are what the sweep
freezes: they are superseded snapshots that nothing polls, and the copy
keeps them alive across Claude transcript pruning.
"""

import json
import os
import shutil
import subprocess
import tempfile
import time
from unittest.mock import patch

import pytest

from pm_core.pane_idle import PaneIdleTracker
from pm_core.tui import auto_start
from pm_core.verdict_transcript import extract_verdict_from_transcript

from tests.test_autostart_multi_target import FakeApp, _pr

SID_MERGE = "11111111-2222-3333-4444-555555555555"
SID_DONE = "66666666-7777-8888-9999-000000000000"


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


def _setup(tmp_path):
    claude_dir = tmp_path / "claude-projects"
    claude_dir.mkdir()
    app = FakeApp([_pr("pr-m", "in_review")], root=tmp_path)
    app._auto_start = True
    app._auto_start_run_id = "autostart-pr-m-abc"
    app._auto_start_targets = {"pr-m": {}}
    app._pane_idle_tracker = PaneIdleTracker()
    tdir = auto_start.get_transcript_dir(app)
    tdir.mkdir(parents=True)
    live = claude_dir / f"{SID_MERGE}.jsonl"
    live.write_text(_user("update the repo") + _assistant("blocked\nINPUT_REQUIRED"))
    done = claude_dir / f"{SID_DONE}.jsonl"
    done.write_text(_user("sign off") + _assistant("SIGNOFF_MERGE"))
    merge_link = tdir / "merge-pr-m.jsonl"
    merge_link.symlink_to(live)
    done_link = tdir / "signoff-pr-m.jsonl"
    done_link.symlink_to(done)
    return app, live, merge_link, done_link


def test_disable_keeps_live_merge_transcript_so_merged_is_detected(tmp_path):
    app, live, merge_link, done_link = _setup(tmp_path)
    tracker = app._pane_idle_tracker
    tracker.register("merge:pr-m", "%24", str(merge_link))
    assert extract_verdict_from_transcript(
        tracker.get_transcript_path("merge:pr-m"),
        ("MERGED", "INPUT_REQUIRED")) == "INPUT_REQUIRED"

    auto_start._disable(app)

    # Every canonical link survives: the live merge window still reads its
    # own transcript, and the finished sign-off's is left live too.
    assert merge_link.is_symlink()
    assert done_link.is_symlink()
    # The user answers in the merge window; Claude ends with MERGED.
    with live.open("a") as f:
        f.write(_user("The checkout is fixed, please finish")
                + _assistant("updated\nMERGED"))
    assert extract_verdict_from_transcript(
        tracker.get_transcript_path("merge:pr-m"),
        ("MERGED", "INPUT_REQUIRED")) == "MERGED"


def test_disable_keeps_a_gone_tracked_panes_transcript_live(tmp_path):
    """A dead pane is still not a licence to freeze: the driver, a later
    restart or an external reader may still poll the canonical."""
    app, live, merge_link, _ = _setup(tmp_path)
    tracker = app._pane_idle_tracker
    tracker.register("merge:pr-m", "%24", str(merge_link))
    tracker._states["merge:pr-m"].gone = True

    auto_start._disable(app)

    assert merge_link.is_symlink()
    with live.open("a") as f:
        f.write(_assistant("MERGED"))
    assert "MERGED" in merge_link.read_text()


SID_REVIEW = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
SID_DEAD = "12345678-1234-1234-1234-123456789abc"


@pytest.fixture
def tmux_session(monkeypatch):
    """A private tmux server with session "sess"; yields a pane starter."""
    if not shutil.which("tmux"):
        pytest.skip("tmux not installed")
    d = tempfile.mkdtemp(prefix="pmtf", dir="/tmp")
    sock = os.path.join(d, "s")
    monkeypatch.setenv("PM_TMUX_SOCKET", sock)
    t = ["tmux", "-S", sock]

    def tm(*a):
        return subprocess.run(t + list(a), check=True, capture_output=True,
                              text=True).stdout.strip()

    def pane(name, session_id):
        # A Claude-like start command: pm launches with --session-id <uuid>.
        return tm("new-window", "-d", "-P", "-F", "#{pane_id}", "-t", "sess:",
                  "-n", name, f"sleep 60; : claude --session-id {session_id}")
    try:
        tm("new-session", "-d", "-s", "sess", "-n", "main", "sleep 60")
        yield tm, pane
    finally:
        subprocess.run(t + ["kill-server"], capture_output=True)
        shutil.rmtree(d, ignore_errors=True)


def test_disable_keeps_running_review_loop_and_unregistered_merge_transcripts(
        tmp_path, tmux_session):
    from pm_core.review_loop import ReviewLoopState
    tm, pane = tmux_session
    app, live, merge_link, done_link = _setup(tmp_path)
    app._session_name = "sess"
    tdir = auto_start.get_transcript_dir(app)
    review = tmp_path / "claude-projects" / f"{SID_REVIEW}.jsonl"
    review.write_text(_user("review pr-m"))
    review_link = tdir / "review-pr-m-i1.jsonl"
    review_link.symlink_to(review)
    # A running review loop polls review_link itself (no tracker entry:
    # _poll_impl_idle skips PRs with running loops).
    loop = ReviewLoopState(pr_id="pr-m")
    loop.running = True
    loop.iteration = 1
    loop._transcript_dir = str(tdir)
    app._review_loops["pr-m"] = loop
    # The merge window was just opened: not registered in the tracker yet.
    pane("merge-pr-m", SID_MERGE)
    # The finished sign-off's pane is still open.
    pane("signoff-pr-m", SID_DONE)
    assert app._pane_idle_tracker.tracked_keys() == []

    auto_start._disable(app)

    assert review_link.is_symlink() and merge_link.is_symlink()
    assert done_link.is_symlink()
    with review.open("a") as f:
        f.write(_assistant("looks good\nPASS"))
    with live.open("a") as f:
        f.write(_user("fixed") + _assistant("done\nMERGED"))
    assert extract_verdict_from_transcript(str(review_link), ("PASS",)) == "PASS"
    assert extract_verdict_from_transcript(
        str(merge_link), ("MERGED", "INPUT_REQUIRED")) == "MERGED"


def test_disable_leaves_a_finished_review_loop_iteration_live(
        tmp_path, tmux_session):
    """A finished loop's iteration link stays live: the pane may still be
    open, and a frozen copy would hide a verdict it appends afterwards."""
    from pm_core.review_loop import ReviewLoopState
    tm, pane = tmux_session
    app, _, _, _ = _setup(tmp_path)
    app._session_name = "sess"
    tdir = auto_start.get_transcript_dir(app)
    review = tmp_path / "claude-projects" / f"{SID_REVIEW}.jsonl"
    review.write_text(_user("review"))
    link = tdir / "review-pr-m-i1.jsonl"
    link.symlink_to(review)
    loop = ReviewLoopState(pr_id="pr-m")
    loop.iteration = 1
    loop._transcript_dir = str(tdir)
    app._review_loops["pr-m"] = loop   # finished (running False)
    pane("review-pr-m", SID_REVIEW)    # its pane is still open

    auto_start._disable(app)

    assert link.is_symlink()
    with review.open("a") as f:
        f.write(_assistant("looks good\nPASS"))
    assert extract_verdict_from_transcript(str(link), ("PASS",)) == "PASS"


def test_disable_freezes_archive_entries_but_leaves_canonicals_live(
        tmp_path, tmux_session):
    tm, pane = tmux_session
    app, live, merge_link, done_link = _setup(tmp_path)
    app._session_name = "sess"
    dead = tmp_path / "claude-projects" / f"{SID_DEAD}.jsonl"
    dead.write_text(_user("impl") + _assistant("done"))
    tdir = auto_start.get_transcript_dir(app)
    dead_link = tdir / "impl-pr-m.jsonl"
    dead_link.symlink_to(dead)
    archived = tdir / "archive" / f"impl-pr-m.{SID_DONE}.jsonl"
    archived.parent.mkdir()
    archived.symlink_to(done_link.resolve())
    tm("set-option", "-g", "remain-on-exit", "on")
    tm("new-window", "-d", "-t", "sess:", "-n", "pr-m",
       f"true; : claude --session-id {SID_DEAD}")
    for _ in range(50):
        if "1" in tm("list-panes", "-t", "sess:pr-m", "-F", "#{pane_dead}"):
            break
        time.sleep(0.1)

    auto_start._disable(app)

    # Canonicals stay live whatever the pane state (alive, dead, absent);
    # the archived snapshot is frozen so it survives Claude pruning.
    for link in (merge_link, done_link, dead_link):
        assert link.is_symlink(), link
    assert "done" in dead_link.read_text()
    assert archived.is_file() and not archived.is_symlink()
    assert "SIGNOFF_MERGE" in archived.read_text()
