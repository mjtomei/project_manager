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
