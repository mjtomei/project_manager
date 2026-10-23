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


def test_poll_qa_state_drops_keys_of_a_replaced_run(tmp_path, tracker):
    """z t over a mid-turn run: the old run's scenario keys are never
    polled or unregistered again, so the node spun forever after the
    new run finished (S30)."""
    from pm_core.tui.qa_loop_ui import poll_qa_state
    from pm_core.tui.tech_tree import qa_pane_state
    old = _make_transcript(tmp_path, "old.jsonl")
    tracker.register("qa:pr-x:s3", "%32", str(old))   # superseded, mid-turn
    tracker.register("qa:pr-y:s3", "%40", str(old))   # another PR's run
    app = _FakeApp(tracker)
    # The fresh run, still planning: no scenario panes yet.
    app._qa_loops["pr-x"] = _make_state("pr-x", [])
    app._qa_loops["pr-y"] = _make_state(
        "pr-y", [_make_scenario(3, "%40", str(old))])

    with patch("pm_core.tmux.pane_exists", return_value=True), \
         patch("pm_core.hook_events.read_event", return_value=None):
        poll_qa_state(app)

    assert not tracker.is_tracked("qa:pr-x:s3")
    assert qa_pane_state(tracker, "pr-x") == "idle"
    assert tracker.is_tracked("qa:pr-y:s3")


def test_pruned_planning_run_reads_like_a_first_run_in_the_picker(
        tmp_path, tracker, monkeypatch):
    """Pruning the last old subkey while the fresh run is still planning
    clears the qa runtime action: the picker shows no stale badge (a first
    run in planning has none either), not the old run's dead panes."""
    from pm_core import hook_events
    from pm_core import runtime_state as rs
    # The picker badge reads hook events: no event yet means [working].
    monkeypatch.setattr(hook_events, "_HOOKS_BASE", tmp_path / "hooks")
    from pm_core.cli.session import _format_action_status
    from pm_core.tui.qa_loop_ui import poll_qa_state
    old = _make_transcript(tmp_path, "old.jsonl")
    tracker.register("qa:pr-x:s3", "%32", str(old))
    tracker.register("qa:pr-y:s3", "%40", str(old))
    assert _format_action_status("pr-x", "qa") == " [working]"
    app = _FakeApp(tracker)
    app._qa_loops["pr-x"] = _make_state("pr-x", [])          # planning
    app._qa_loops["pr-y"] = _make_state(
        "pr-y", [_make_scenario(3, "%40", str(old))])

    with patch("pm_core.tmux.pane_exists", return_value=True), \
         patch("pm_core.hook_events.read_event", return_value=None):
        poll_qa_state(app)

    assert rs.get_action_state("pr-x", "qa") == {}
    assert _format_action_status("pr-x", "qa") == ""
    assert set(rs.get_action_state("pr-y", "qa")["panes"]) == {"s3"}
    assert _format_action_status("pr-y", "qa") == " [working]"


def test_prune_keeps_the_current_runs_panes(tmp_path, tracker):
    from pm_core import runtime_state as rs
    from pm_core.tui.qa_loop_ui import poll_qa_state
    old = _make_transcript(tmp_path, "old.jsonl")
    tracker.register("qa:pr-x:s3", "%32", str(old))
    app = _FakeApp(tracker)
    app._qa_loops["pr-x"] = _make_state(
        "pr-x", [_make_scenario(5, "%50", str(old))])

    with patch("pm_core.tmux.pane_exists", return_value=True), \
         patch("pm_core.hook_events.read_event", return_value=None):
        poll_qa_state(app)

    assert not tracker.is_tracked("qa:pr-x:s3")
    assert tracker.is_tracked("qa:pr-x:s5")
    entry = rs.get_action_state("pr-x", "qa")
    assert entry["state"] == "running"
    assert set(entry["panes"]) == {"s5"}
