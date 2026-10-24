"""A QA run survives project.yaml becoming unloadable during planning (RQ37).

A pull can leave conflict markers, a clean merge can leave plans that do
not validate, and a checkout or rebase removes the file for a moment.
Live (S45, pre-fix 4d8f968a): a run sitting in planning ended "QA thread
crashed" 9 s after a conflicting pull, because the mid-planning merge
guard's ``store.load`` raised out of ``run_qa_sync``.  The merge guards now
skip a round while the file cannot be loaded, and the loads the run needs
(start, the spec gate after planning, resume) wait until it loads again.
"""

from unittest.mock import patch

import pytest

from pm_core import qa_loop, store
from tests.test_qa_planner_handoff import FULL_PLAN, TEMPLATE_PROMPT, _run_planning

FAILURES = {
    "conflict_markers": lambda: store.ProjectYamlParseError(
        "project.yaml is not valid YAML: while scanning a simple key"),
    "invalid_plans": lambda: store.PlanValidationError(
        "Plan plan-child references non-existent parent 'plan-base'"),
    "missing_file": lambda: store.ProjectYamlMissingError(
        2, "No such file or directory", "/x/pm/project.yaml"),
}

# store.load calls of a planning run in the harness, in order.
START, START2, GUARD_PRE, GUARD_POST, GUARD_MID, SPEC_GATE = range(6)


def _data(tmp_path):
    return {"project": {"name": "p"},
            "prs": [{"id": "pr-001", "title": "t", "branch": "pm/pr-001",
                     "status": "qa", "workdir": str(tmp_path / "workdir")}]}


def _plan(tmp_path, monkeypatch, failing: dict[int, int], kind: str):
    """Run the planning harness with ``store.load`` call *i* failing
    ``failing[i]`` times (each retry is a new call) before it loads."""
    data = _data(tmp_path)
    calls = []
    left = dict(failing)

    def load(*a, **kw):
        i = len([c for c in calls if c == "ok"])  # index of the logical load
        if left.get(i, 0) > 0:
            left[i] -= 1
            calls.append("fail")
            raise FAILURES[kind]()
        calls.append("ok")
        return data

    state = _run_planning(
        tmp_path, monkeypatch, pane_content="",
        transcript_turns=[("user", TEMPLATE_PROMPT), ("assistant", FULL_PLAN)],
        extra_patches=(patch("pm_core.store.load", side_effect=load),))
    return state, calls


def _consumed_plan_and_reached_spec_gate(state):
    assert [s.index for s in state.scenarios] == [1, 2, 3, 4]
    # The harness PR has no QA spec, so a run that got past planning stops
    # at the spec gate: proof the gate ran rather than the thread dying.
    assert "QA spec was not generated" in state._error
    assert state.latest_output != "QA thread crashed"


@pytest.mark.parametrize("kind", sorted(FAILURES))
@pytest.mark.parametrize("guard", [GUARD_PRE, GUARD_POST, GUARD_MID])
def test_merge_guard_skips_a_round_while_project_yaml_cannot_load(
        tmp_path, monkeypatch, kind, guard):
    state, calls = _plan(tmp_path, monkeypatch, {guard: 1}, kind)
    _consumed_plan_and_reached_spec_gate(state)
    assert calls.count("fail") == 1


@pytest.mark.parametrize("kind", sorted(FAILURES))
def test_spec_gate_waits_until_project_yaml_loads_again(
        tmp_path, monkeypatch, kind):
    state, calls = _plan(tmp_path, monkeypatch, {SPEC_GATE: 3}, kind)
    _consumed_plan_and_reached_spec_gate(state)
    # three failed attempts, then the load the gate uses
    assert calls[-4:] == ["fail", "fail", "fail", "ok"]


@pytest.mark.parametrize("kind", sorted(FAILURES))
def test_start_waits_until_project_yaml_loads_again(tmp_path, monkeypatch, kind):
    state, calls = _plan(tmp_path, monkeypatch, {START: 2, START2: 1}, kind)
    _consumed_plan_and_reached_spec_gate(state)
    assert calls.count("fail") == 3


def test_a_stop_ends_the_wait_without_a_verdict(tmp_path, monkeypatch):
    state = qa_loop.QALoopState(pr_id="pr-001")

    def load(*a, **kw):
        state.stop_requested = True
        raise FAILURES["missing_file"]()

    with patch("pm_core.store.load", side_effect=load), \
            patch("pm_core.qa_loop.time.sleep"):
        assert qa_loop._load_project_waiting(tmp_path, state, "QA start") is None
    assert state.latest_verdict == ""


def test_waiting_is_shown_once_per_reason(tmp_path, monkeypatch):
    state = qa_loop.QALoopState(pr_id="pr-001")
    updates = []
    seq = [FAILURES["conflict_markers"](), FAILURES["conflict_markers"](),
           FAILURES["invalid_plans"](), {"prs": []}]

    def load(*a, **kw):
        r = seq.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    with patch("pm_core.store.load", side_effect=load), \
            patch("pm_core.qa_loop.time.sleep"):
        assert qa_loop._load_project_waiting(
            tmp_path, state, "the spec check",
            on_update=lambda s: updates.append(s.latest_output)) == {"prs": []}
    assert len(updates) == 2
    assert "not valid YAML" in updates[0] and "plan-child" in updates[1]
