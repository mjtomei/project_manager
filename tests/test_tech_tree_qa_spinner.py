"""Tests for the QA-status spinner aggregation in the tech tree."""

from pathlib import Path
from unittest.mock import patch

import pytest

from pm_core.pane_idle import PaneIdleTracker
from pm_core.tui.tech_tree import qa_pane_state


def _make_transcript(tmp_path: Path, name: str = "t.jsonl") -> Path:
    sid = "12345678-1234-1234-1234-123456789abc"
    target = tmp_path / f"{sid}.jsonl"
    if not target.exists():
        target.write_text("")
    link = tmp_path / name
    link.symlink_to(target)
    return link


@pytest.fixture
def tracker():
    return PaneIdleTracker()


def test_no_qa_panes_tracked_returns_idle(tracker):
    assert qa_pane_state(tracker, "pr-abc") == "idle"


def test_only_other_pr_keys_does_not_leak(tracker, tmp_path):
    t = _make_transcript(tmp_path)
    tracker.register("qa:pr-other:s0", "%0", str(t))
    tracker.register("pr-abc", "%1", str(_make_transcript(tmp_path, "t2.jsonl")))
    assert qa_pane_state(tracker, "pr-abc") == "idle"


def test_active_qa_pane_returns_active(tracker, tmp_path):
    t = _make_transcript(tmp_path)
    tracker.register("qa:pr-abc:s0", "%0", str(t))
    # Newly registered: idle=False, waiting=False → active.
    assert qa_pane_state(tracker, "pr-abc") == "active"


def test_idle_qa_pane_returns_idle(tracker, tmp_path):
    t = _make_transcript(tmp_path)
    tracker.register("qa:pr-abc:s0", "%0", str(t))
    # Force idle.
    with tracker._lock:
        tracker._states["qa:pr-abc:s0"].idle = True
    assert qa_pane_state(tracker, "pr-abc") == "idle"


def test_waiting_takes_priority_over_active(tracker, tmp_path):
    t1 = _make_transcript(tmp_path, "a.jsonl")
    t2 = _make_transcript(tmp_path, "b.jsonl")
    tracker.register("qa:pr-abc:s0", "%0", str(t1))
    tracker.register("qa:pr-abc:s1", "%1", str(t2))
    with tracker._lock:
        tracker._states["qa:pr-abc:s1"].waiting_for_input = True
    assert qa_pane_state(tracker, "pr-abc") == "waiting"


def test_mixed_idle_and_active_returns_active(tracker, tmp_path):
    t1 = _make_transcript(tmp_path, "a.jsonl")
    t2 = _make_transcript(tmp_path, "b.jsonl")
    tracker.register("qa:pr-abc:s0", "%0", str(t1))
    tracker.register("qa:pr-abc:s1", "%1", str(t2))
    with tracker._lock:
        tracker._states["qa:pr-abc:s0"].idle = True
    # s1 is still active
    assert qa_pane_state(tracker, "pr-abc") == "active"


# ---------------------------------------------------------------------------
# poll_qa_state registration wiring
# ---------------------------------------------------------------------------


class _FakeApp:
    def __init__(self, tracker):
        self._pane_idle_tracker = tracker
        self._qa_loops: dict = {}
        self._self_driving_qa: dict = {}
        self._root = None
        self.logged: list[str] = []

    def log_message(self, msg, **kwargs):
        self.logged.append(msg)


def _make_state(pr_id, scenarios):
    from pm_core.qa_loop import QALoopState
    state = QALoopState(pr_id=pr_id)
    state.scenarios = scenarios
    state.running = True
    return state


def _make_scenario(index, pane_id, transcript_path):
    from pm_core.qa_loop import QAScenario
    return QAScenario(
        index=index, title=f"s{index}", focus="",
        pane_id=pane_id, transcript_path=transcript_path,
    )


def test_poll_qa_state_registers_scenarios(tmp_path, tracker):
    from pm_core.tui.qa_loop_ui import poll_qa_state
    t = _make_transcript(tmp_path)
    sc = _make_scenario(0, "%5", str(t))
    app = _FakeApp(tracker)
    app._qa_loops["pr-x"] = _make_state("pr-x", [sc])

    with patch("pm_core.tmux.pane_exists", return_value=True), \
         patch("pm_core.hook_events.read_event", return_value=None):
        poll_qa_state(app)

    assert tracker.is_tracked("qa:pr-x:s0")


def test_poll_qa_state_skips_scenarios_without_pane(tmp_path, tracker):
    from pm_core.tui.qa_loop_ui import poll_qa_state
    sc = _make_scenario(0, None, None)
    app = _FakeApp(tracker)
    app._qa_loops["pr-x"] = _make_state("pr-x", [sc])

    poll_qa_state(app)

    assert not tracker.is_tracked("qa:pr-x:s0")


def test_poll_qa_state_unregisters_on_completion(tmp_path, tracker):
    from pm_core.tui.qa_loop_ui import poll_qa_state
    t = _make_transcript(tmp_path)
    sc = _make_scenario(0, "%5", str(t))
    tracker.register("qa:pr-x:s0", "%5", str(t))

    app = _FakeApp(tracker)
    state = _make_state("pr-x", [sc])
    state.running = False
    state.latest_verdict = "PASS"
    state._ui_complete_notified = True  # second tick
    app._qa_loops["pr-x"] = state

    with patch("pm_core.tui.qa_loop_ui._on_qa_complete"):
        poll_qa_state(app)

    assert not tracker.is_tracked("qa:pr-x:s0")
    assert "pr-x" not in app._qa_loops
