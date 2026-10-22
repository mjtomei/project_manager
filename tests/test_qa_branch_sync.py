"""Regression tests: QA synchronizes the PR workdir before planning (pr-62fdd54).

Live failure (#234): a QA worker pushed a fix to the upstream PR branch,
the run ended INPUT_REQUIRED so the finalize pane never pulled it into the
PR workdir, and the next QA run planned against the stale local head.  The
planner handoff then refused ("is behind" / "diverged"), after a full
planning session, and restarting QA repeated it.

Git, the upstream and the scenario clone pin are real here; only tmux and
Claude are faked.
"""

import json
import os
import subprocess
import time
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import pm_core.cli  # noqa: F401  (see test_qa_planner_handoff)
from pm_core import qa_loop
from pm_core.claude_launcher import transcript_path_for
from pm_core.qa_loop import QALoopState

BRANCH = "pm/pr-001"
GIT_ID = ["-c", "user.email=t@t", "-c", "user.name=t"]


def _git(cwd, *args, check=True):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                       text=True, check=check)
    return r.stdout.strip()


def _commit(repo, rel, text, msg):
    path = Path(repo, rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    _git(repo, "add", rel)
    _git(repo, *GIT_ID, "commit", "-m", msg)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repos(tmp_path, monkeypatch):
    """Bare upstream + PR workdir at L + an old QA worker clone."""
    # Bypass any sandbox git push-proxy shim so pushes reach the bare repo.
    monkeypatch.setenv("PATH", os.pathsep.join(
        d for d in os.environ.get("PATH", "").split(os.pathsep)
        if not d.endswith("/.local/bin")))
    remote = tmp_path / "remote.git"
    _git(tmp_path, "init", "--bare", "-b", "master", str(remote))
    wd = tmp_path / "workdir"
    _git(tmp_path, "init", "-b", "master", str(wd))
    _commit(wd, "app.py", "v = 1\n", "base")
    _git(wd, "checkout", "-b", BRANCH)
    _git(wd, "remote", "add", "origin", str(remote))
    _git(wd, "push", "origin", "master", BRANCH)
    worker = tmp_path / "worker"
    _git(tmp_path, "clone", "-b", BRANCH, str(remote), str(worker))
    url = f"file://{remote}"
    with patch("pm_core.push_proxy.resolve_real_origin", return_value=url):
        yield {"tmp": tmp_path, "remote": remote, "wd": wd,
               "worker": worker, "url": url,
               "L": _git(wd, "rev-parse", "HEAD")}


def _worker_push(s, rel="app.py", text="v = 2  # qa: worker fix\n"):
    """A previous QA round's worker pushes straight to the upstream."""
    _git(s["worker"], "pull", "--quiet", "origin", BRANCH)
    sha = _commit(s["worker"], rel, text, "qa: worker fix")
    _git(s["worker"], "push", "origin", BRANCH)
    return sha


def _head(s):
    return _git(s["wd"], "rev-parse", BRANCH)


def _upstream(s):
    return _git(s["remote"], "rev-parse", BRANCH)


# ---------------------------------------------------------------------------
# _sync_pr_branch
# ---------------------------------------------------------------------------

class TestSyncPrBranch:
    def test_behind_fast_forwards_and_reports_app_code(self, repos):
        s = repos
        u = _worker_push(s)
        sync = qa_loop._sync_pr_branch(str(s["wd"]), BRANCH)
        assert sync.outcome == "fast_forwarded"
        assert (sync.local, sync.upstream) == (s["L"], u)
        assert sync.code_changes == ["app.py"]
        assert _head(s) == u and _git(s["wd"], "rev-parse", "HEAD") == u
        assert "worker fix" in (s["wd"] / "app.py").read_text()

    def test_behind_pm_only_has_no_code_changes(self, repos):
        s = repos
        u = _worker_push(s, "pm/qa/notes.md", "note\n")
        sync = qa_loop._sync_pr_branch(str(s["wd"]), BRANCH)
        assert sync.outcome == "fast_forwarded" and sync.code_changes == []
        assert _head(s) == u

    def test_up_to_date_and_local_ahead_unchanged(self, repos):
        s = repos
        assert qa_loop._sync_pr_branch(str(s["wd"]), BRANCH).outcome \
            == "unchanged"
        # Unpublished planner-only commits: left for the handoff to push.
        c = _commit(s["wd"], "pm/qa/instructions/s1.md", "S1\n", "planner")
        sync = qa_loop._sync_pr_branch(str(s["wd"]), BRANCH)
        assert sync.outcome == "unchanged"
        assert _head(s) == c and _upstream(s) == s["L"]

    def test_local_only_repo_unchanged(self, repos):
        s = repos
        _worker_push(s)
        with patch("pm_core.push_proxy.resolve_real_origin",
                   return_value=None):
            sync = qa_loop._sync_pr_branch(str(s["wd"]), BRANCH)
        assert sync.outcome == "unchanged" and _head(s) == s["L"]

    def test_planner_commits_plus_upstream_fix_diverged_untouched(
            self, repos):
        s = repos
        c = _commit(s["wd"], "pm/qa/instructions/s1.md", "S1\n", "planner")
        u = _worker_push(s)
        sync = qa_loop._sync_pr_branch(str(s["wd"]), BRANCH)
        assert sync.outcome == "diverged"
        assert "1 local-only, 1 upstream-only" in sync.detail
        assert "never force-push" in sync.detail
        # No merge, reset or push by pm.
        assert _head(s) == c and _upstream(s) == u
        assert _git(s["wd"], "status", "--porcelain") == ""

    def test_conflicting_divergence_leaves_no_merge_state(self, repos):
        s = repos
        c = _commit(s["wd"], "app.py", "v = 3  # local\n", "local fix")
        _worker_push(s)
        sync = qa_loop._sync_pr_branch(str(s["wd"]), BRANCH)
        assert sync.outcome == "diverged"
        assert _head(s) == c
        assert (s["wd"] / "app.py").read_text() == "v = 3  # local\n"
        assert not (s["wd"] / ".git" / "MERGE_HEAD").exists()

    def test_dirty_file_preserved_across_fast_forward(self, repos):
        s = repos
        (s["wd"] / "pm").mkdir()
        (s["wd"] / "other.txt").write_text("tracked\n")
        _git(s["wd"], "add", "other.txt")
        _git(s["wd"], *GIT_ID, "commit", "-m", "other")
        _git(s["wd"], "push", "origin", BRANCH)
        (s["wd"] / "other.txt").write_text("my uncommitted edit\n")
        u = _worker_push(s)
        sync = qa_loop._sync_pr_branch(str(s["wd"]), BRANCH)
        assert sync.outcome == "fast_forwarded" and _head(s) == u
        assert (s["wd"] / "other.txt").read_text() == "my uncommitted edit\n"

    def test_dirty_overlap_holds_without_changing_anything(self, repos):
        s = repos
        (s["wd"] / "app.py").write_text("my uncommitted edit\n")
        _worker_push(s)
        sync = qa_loop._sync_pr_branch(str(s["wd"]), BRANCH)
        assert sync.outcome == "hold"
        assert "fast-forward was refused" in sync.detail
        assert "app.py" in sync.detail
        assert _head(s) == s["L"]
        assert (s["wd"] / "app.py").read_text() == "my uncommitted edit\n"

    def test_dirty_divergence_holds(self, repos):
        s = repos
        _commit(s["wd"], "pm/x.md", "x\n", "planner")
        (s["wd"] / "app.py").write_text("wip\n")
        _worker_push(s, "b.py", "b\n")
        sync = qa_loop._sync_pr_branch(str(s["wd"]), BRANCH)
        assert sync.outcome == "hold"
        assert "uncommitted changes (app.py)" in sync.detail
        assert (s["wd"] / "app.py").read_text() == "wip\n"

    def test_other_branch_checked_out_holds(self, repos):
        s = repos
        _worker_push(s)
        _git(s["wd"], "checkout", "--quiet", "master")
        sync = qa_loop._sync_pr_branch(str(s["wd"]), BRANCH)
        assert sync.outcome == "hold" and "refs/heads/master" in sync.detail
        assert _head(s) == s["L"]

    def test_missing_local_branch_left_to_handoff_guard(self, repos):
        s = repos
        sync = qa_loop._sync_pr_branch(str(s["wd"]), "pm/no-such-branch")
        assert sync.outcome == "unchanged"

    def test_unreachable_upstream_holds(self, repos):
        s = repos
        with patch("pm_core.push_proxy.resolve_real_origin",
                   return_value=f"file://{s['tmp']}/missing.git"):
            sync = qa_loop._sync_pr_branch(str(s["wd"]), BRANCH)
        assert sync.outcome == "hold"
        assert "Could not refresh the upstream" in sync.detail


# ---------------------------------------------------------------------------
# run_qa_sync end to end (fake tmux / Claude, real git)
# ---------------------------------------------------------------------------

PLAN = ("QA_PLAN_START\n\nSCENARIO 1: smoke\nFOCUS: f\nINSTRUCTION: none\n"
        "STEPS:\n  GIVEN: g\n  WHEN: w\n  THEN: t\n\nQA_PLAN_END\n")


class _Launched(Exception):
    pass


def _run_qa(s, *, signoff=None, sync_record=None, during_planning=None):
    """Run one QA round; returns (state, seen, pr) where *seen* records the
    revision the planner pane started on and what workers were pinned to."""
    seen = {}
    pr = {"id": "pr-001", "title": "t", "branch": BRANCH, "status": "qa",
          "workdir": str(s["wd"])}
    if signoff:
        pr["signoff"] = signoff
    if sync_record:
        pr["qa_branch_sync"] = sync_record
    data = {"project": {"name": "p"}, "prs": [pr]}
    state = QALoopState(pr_id="pr-001")
    qa_wd = s["tmp"] / f"qa-{time.monotonic_ns()}"
    qa_wd.mkdir()
    state.qa_workdir = str(qa_wd)

    def fake_cmd(**kw):
        p = transcript_path_for(kw["cwd"], kw["session_id"])
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"type": "assistant", "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": PLAN}]}}) + "\n")
        return "planner"

    def fake_new_window(session, name, cmd, cwd=None, **kw):
        seen["planner_reads"] = _git(cwd, "rev-parse", "HEAD")

    def fake_wait(*a, **kw):
        if "idle" in seen:
            state.stop_requested = True
            return None
        seen["idle"] = True
        if during_planning:
            during_planning()
        return {"event_type": "idle_prompt", "timestamp": time.time()}

    def fake_launch(st, *a, **kw):
        seen["pinned"] = st.planner_head
        clone, _ = qa_loop.create_scenario_workdir(
            qa_wd, 1, repo_root=s["wd"], branch=BRANCH,
            expected_head=st.planner_head)
        seen["worker_tests"] = _git(clone, "rev-parse", "HEAD")
        raise _Launched

    patches = [
        patch("pm_core.qa_loop.get_pm_session", return_value="pm-test"),
        patch("pm_core.store.load", return_value=data),
        patch("pm_core.store.locked_update",
              side_effect=lambda root, fn: fn(data)),
        patch("pm_core.qa_loop._resolve_qa_model",
              return_value=MagicMock(model=None, provider=None, effort=None)),
        patch("pm_core.qa_loop._next_scenario_offset", return_value=0),
        patch("pm_core.qa_loop._launch_scenario_0", return_value=None),
        patch("pm_core.qa_loop._get_qa_spec", return_value="spec"),
        patch("pm_core.container.is_container_mode_enabled",
              return_value=False),
        patch("pm_core.prompt_gen.generate_qa_planner_prompt",
              return_value="plan"),
        patch("pm_core.claude_launcher.build_claude_shell_cmd",
              side_effect=fake_cmd),
        patch("pm_core.tmux.find_window_by_name", return_value=None),
        patch("pm_core.tmux.new_window", side_effect=fake_new_window),
        patch("pm_core.tmux.select_window"),
        patch("pm_core.runtime_state.consume_suppress_switch",
              return_value=True),
        patch("pm_core.qa_loop.find_claude_pane", return_value="%1"),
        patch("pm_core.tmux.pane_exists", return_value=True),
        patch("pm_core.tmux.capture_pane", return_value=""),
        patch("pm_core.hook_events.wait_for_event", side_effect=fake_wait),
        patch("pm_core.tmux.new_window_get_pane", return_value="%2"),
        patch("pm_core.tmux.split_pane_at", return_value="%3"),
        patch("pm_core.tmux.pane_window_id", return_value=None),
        patch("pm_core.qa_loop._launch_scenarios_in_tmux",
              side_effect=fake_launch),
        patch("pm_core.qa_loop.time.sleep"),
    ]
    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        try:
            qa_loop.run_qa_sync(state, s["tmp"] / "pm", pr)
        except _Launched:
            pass
    return state, seen, pr


def _overall(state):
    path = Path(state.qa_workdir) / "qa_status.json"
    return json.loads(path.read_text()).get("overall") if path.exists() \
        else None


class TestRunQaSyncBranchSync:
    def test_interrupted_round_worker_fix_returns_to_review(self, repos):
        """#234: worker fix pushed, finalizer skipped, new QA starts."""
        s = repos
        u = _worker_push(s)
        state, seen, pr = _run_qa(
            s, signoff={"verdict": "SIGNOFF_MERGE", "sha": s["L"]})
        # The stale tree is never planned against, nothing is launched.
        assert "planner_reads" not in seen and "pinned" not in seen
        assert _head(s) == u and _upstream(s) == u
        assert state.latest_verdict == qa_loop.VERDICT_NEEDS_WORK
        assert _overall(state) == qa_loop.VERDICT_NEEDS_WORK
        assert "app.py" in state._error and "review" in state._error
        # Old sign-off evidence cannot be adopted for the imported code.
        assert pr["signoff"]["invalidated"].startswith("QA sync:")
        assert "app.py" in qa_loop.qa_outcome_detail(state)
        assert state.running is False

    def test_next_round_after_review_plans_and_pins_upstream(self, repos):
        """pm/-only upstream commits: plan and test the refreshed head."""
        s = repos
        u = _worker_push(s, "pm/qa/notes.md", "note\n")
        state, seen, _pr = _run_qa(s)
        assert seen["planner_reads"] == u
        assert state.planning_base == u
        assert seen["pinned"] == u and seen["worker_tests"] == u

    def test_upstream_moves_during_planning_refuses_handoff(self, repos):
        s = repos
        moved = {}

        def push_while_planning():
            moved["sha"] = _worker_push(s, "late.py", "late\n")

        state, seen, _pr = _run_qa(s, during_planning=push_while_planning)
        assert seen["planner_reads"] == s["L"]
        assert "pinned" not in seen
        assert state.latest_verdict == qa_loop.VERDICT_INPUT_REQUIRED
        assert _overall(state) == qa_loop.VERDICT_INPUT_REQUIRED
        assert "Restart QA: it fast-forwards" in state._error
        assert _upstream(s) == moved["sha"]  # never overwritten
        # Restarting QA re-syncs instead of re-planning the stale tree.
        state2, seen2, _ = _run_qa(s)
        assert "planner_reads" not in seen2
        assert _head(s) == moved["sha"]
        assert state2.latest_verdict == qa_loop.VERDICT_NEEDS_WORK

    def test_divergence_routes_to_review_once_then_holds(self, repos):
        s = repos
        c = _commit(s["wd"], "pm/qa/instructions/s1.md", "S1\n", "planner")
        u = _worker_push(s)
        state, seen, pr = _run_qa(
            s, signoff={"verdict": "SIGNOFF_REQA", "sha": c})
        assert "planner_reads" not in seen
        assert state.latest_verdict == qa_loop.VERDICT_NEEDS_WORK
        assert _overall(state) == qa_loop.VERDICT_NEEDS_WORK
        assert "diverged" in state._error
        assert pr["signoff"].get("invalidated")
        record = pr["qa_branch_sync"]
        assert (record["local"], record["upstream"]) == (c, u)
        assert _head(s) == c and _upstream(s) == u
        # Review did not reconcile: same heads again -> hold, no loop.
        state2, seen2, _ = _run_qa(s, sync_record=record)
        assert "planner_reads" not in seen2
        assert state2.latest_verdict == qa_loop.VERDICT_INPUT_REQUIRED
        assert "still diverged" in state2._error

    def test_hold_writes_input_required(self, repos):
        s = repos
        (s["wd"] / "app.py").write_text("wip\n")
        _worker_push(s)
        state, seen, _pr = _run_qa(s)
        assert "planner_reads" not in seen
        assert state.latest_verdict == qa_loop.VERDICT_INPUT_REQUIRED
        assert _overall(state) == qa_loop.VERDICT_INPUT_REQUIRED
        assert "fast-forward was refused" in state._error
        assert (s["wd"] / "app.py").read_text() == "wip\n"

    def test_reconciled_branch_clears_sync_record(self, repos):
        s = repos
        state, seen, pr = _run_qa(
            s, sync_record={"local": "a" * 40, "upstream": "b" * 40})
        assert seen["planner_reads"] == s["L"]
        assert "qa_branch_sync" not in pr
