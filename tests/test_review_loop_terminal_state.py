"""Regression tests for pr-b423bfd: ERROR/KILLED verdicts must produce
state="failed" so the popup spinner can distinguish them from clean
completions ("done")."""

from unittest.mock import MagicMock, patch

from pm_core import runtime_state
from pm_core.review_loop import ReviewLoopState
from pm_core.tui.review_loop_ui import _on_complete_from_thread


def _stub_active(monkeypatch):
    """Make _is_active_loop return True without needing real runtime state."""
    monkeypatch.setattr(
        "pm_core.tui.review_loop_ui._is_active_loop", lambda s: True
    )


def _make_state(pr_id: str, verdict: str) -> ReviewLoopState:
    s = ReviewLoopState(pr_id=pr_id)
    s.iteration = 2
    s.latest_verdict = verdict
    s._transcript_dir = None
    return s


def test_error_verdict_writes_failed_state(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_state, "_runtime_dir", lambda: tmp_path)
    _stub_active(monkeypatch)
    state = _make_state("pr-err1", "ERROR")

    _on_complete_from_thread(MagicMock(), state)

    entry = runtime_state.get_action_state("pr-err1", "review-loop")
    assert entry["state"] == "failed"
    assert entry["verdict"] == "ERROR"


def test_killed_verdict_writes_failed_state(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_state, "_runtime_dir", lambda: tmp_path)
    _stub_active(monkeypatch)
    state = _make_state("pr-kill1", "KILLED")

    _on_complete_from_thread(MagicMock(), state)

    entry = runtime_state.get_action_state("pr-kill1", "review-loop")
    assert entry["state"] == "failed"
    assert entry["verdict"] == "KILLED"


def test_pass_verdict_writes_done_state(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_state, "_runtime_dir", lambda: tmp_path)
    _stub_active(monkeypatch)
    state = _make_state("pr-pass1", "PASS")

    _on_complete_from_thread(MagicMock(), state)

    entry = runtime_state.get_action_state("pr-pass1", "review-loop")
    assert entry["state"] == "done"
    assert entry["verdict"] == "PASS"


def test_needs_work_verdict_writes_done_state(tmp_path, monkeypatch):
    """NEEDS_WORK at terminal time = max-iterations or stop; clean termination."""
    monkeypatch.setattr(runtime_state, "_runtime_dir", lambda: tmp_path)
    _stub_active(monkeypatch)
    state = _make_state("pr-nw1", "NEEDS_WORK")

    _on_complete_from_thread(MagicMock(), state)

    entry = runtime_state.get_action_state("pr-nw1", "review-loop")
    assert entry["state"] == "done"


def test_empty_verdict_writes_done_state(tmp_path, monkeypatch):
    """Stop requested before any iteration completed: latest_verdict is empty."""
    monkeypatch.setattr(runtime_state, "_runtime_dir", lambda: tmp_path)
    _stub_active(monkeypatch)
    state = _make_state("pr-stop1", "")

    _on_complete_from_thread(MagicMock(), state)

    entry = runtime_state.get_action_state("pr-stop1", "review-loop")
    assert entry["state"] == "done"


# ---------------------------------------------------------------------------
# Transcript finalization vs. a superseding loop
# ---------------------------------------------------------------------------

def _loop_with_transcript(tmp_path, pr_id, loop_id):
    """A loop state whose run dir holds its own iteration symlink."""
    native = tmp_path / f"{pr_id}-native.jsonl"
    native.write_text("{}\n")
    link = tmp_path / f"review-{pr_id}-i1.jsonl"
    link.symlink_to(native)
    state = ReviewLoopState(pr_id=pr_id)
    state.loop_id = loop_id
    state.iteration = 1
    state.latest_verdict = "PASS"
    state._transcript_dir = str(tmp_path)
    return state, link


def test_superseded_loop_does_not_finalize_the_successors_transcript(
        tmp_path, monkeypatch):
    """A late completion must not freeze the *new* loop's live transcript.

    The successor shares the run dir and reuses ``review-<pr>-i<n>.jsonl``,
    so finalizing here would replace the new loop's symlink with a snapshot
    its verdict poller would never see updated.
    """
    monkeypatch.setattr(runtime_state, "_runtime_dir", lambda: tmp_path)
    state, link = _loop_with_transcript(tmp_path, "pr-sup", "old")
    runtime_state.set_action_state("pr-sup", "review-loop", "running",
                                   loop_id="new")
    finalized = []
    monkeypatch.setattr("pm_core.claude_launcher.finalize_transcript",
                        lambda p: finalized.append(p))

    _on_complete_from_thread(MagicMock(), state)

    assert finalized == []
    assert link.is_symlink()
    # The successor's runtime entry is untouched.
    assert runtime_state.get_action_state(
        "pr-sup", "review-loop")["loop_id"] == "new"


def test_active_loop_still_finalizes_its_transcripts(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_state, "_runtime_dir", lambda: tmp_path)
    state, link = _loop_with_transcript(tmp_path, "pr-act", "mine")
    runtime_state.set_action_state("pr-act", "review-loop", "running",
                                   loop_id="mine")
    finalized = []
    monkeypatch.setattr("pm_core.claude_launcher.finalize_transcript",
                        lambda p: finalized.append(p))

    _on_complete_from_thread(MagicMock(), state)

    assert finalized == [link]
    assert runtime_state.get_action_state(
        "pr-act", "review-loop")["state"] == "done"


def test_error_line_shows_the_remedy_as_text_not_markup():
    """Review 0f64 i1: the review loop's ERROR line put the failed launch's
    stderr (RQ40: the route remedy) into log-line markup unescaped, like
    S53's TUI keys.  An expired sign-in remedy naming
    "/tmp/s53/creds[work]/..." lost "[work]" on the line and in L, and a
    "[/...]" made the line refuse the whole message."""
    from types import SimpleNamespace
    from rich.text import Text
    from pm_core.tui import review_loop_ui
    logs = []
    app = SimpleNamespace(log_message=lambda msg, **kw: logs.append(msg))
    for reason in ("so /tmp/s53/creds[work]/work-creds.json holds a valid "
                   "session", "see [/tmp] for details"):
        state = SimpleNamespace(
            pr_id="pr-x", latest_verdict="ERROR", iteration=1,
            latest_output=f"Review window launch failed (rc=1): {reason}")
        review_loop_ui._announce_loop_done(app, state)
        assert reason in Text.from_markup(logs[-1]).plain
