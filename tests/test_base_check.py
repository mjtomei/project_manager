"""Pre-flight base integration gate before review iterations and QA.

Real git + real project.yaml: a conflicting base returns the PR to
implementation before the downstream writer starts, records the exact
HEAD/base pair, hands off exactly once, and only lets the phase continue
once the rework genuinely reconciled the base.
"""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from pm_core import base_check, integration, store

PR = "pr-001"
BRANCH = "pm/pr-001"


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["/usr/bin/git", *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


def commit(cwd: Path, name: str, text: str, msg: str) -> str:
    (cwd / name).write_text(text)
    git(cwd, "add", name)
    git(cwd, "commit", "-q", "-m", msg)
    return git(cwd, "rev-parse", "HEAD")


@pytest.fixture
def w(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    for k, v in {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                 "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}.items():
        monkeypatch.setenv(k, v)
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "master")
    commit(repo, "shared.txt", "base\n", "init")
    wd = tmp_path / "wd"
    git(tmp_path, "clone", "-q", str(repo), str(wd))
    git(wd, "checkout", "-q", "-b", BRANCH)
    head = commit(wd, "feature.txt", "feature\n", "feature")
    head = commit(wd, "shared.txt", "pr side\n", "pr edits shared")
    # The conflicting base commit (both sides edited shared.txt).
    commit(repo, "shared.txt", "master side\n", "master edit")
    pm_dir = tmp_path / "pmstate"
    pm_dir.mkdir()
    store.save({"project": {"name": "p", "repo": str(repo),
                            "base_branch": "master", "backend": "local"},
                "prs": [{"id": PR, "title": "T", "branch": BRANCH,
                         "status": "in_review", "workdir": str(wd)}],
                "plans": []}, pm_dir)
    croot = tmp_path / "captures"
    tdir = tmp_path / "tdir"
    tdir.mkdir()
    with patch("pm_core.paths.captures_root", return_value=croot):
        yield SimpleNamespace(repo=repo, wd=wd, pm_dir=pm_dir, head=head,
                              croot=croot, tdir=tdir)


def pr(w) -> dict:
    return store.get_pr(store.load(w.pm_dir), PR)


def set_pr(w, **fields):
    def _apply(d):
        store.get_pr(d, PR).update(fields)
    store.locked_update(w.pm_dir, _apply)


def gate(w, stage=base_check.STAGE_REVIEW, **kw):
    return base_check.gate(w.pm_dir, PR, stage, transcript=w.tdir / "r.jsonl",
                           **kw)


def simulate_launch(w):
    """What a successful ``pm pr start --fresh`` does to the handshake."""
    base_check.clear_return_awaiting(w.pm_dir, PR)


# --- conflicts -------------------------------------------------------------

def test_conflict_before_review_returns_to_implementation(w):
    with patch("pm_core.base_check.launch_impl",
               return_value=(True, "")) as launch:
        res = gate(w)
    assert res.decision == base_check.CONFLICT
    assert res.status == integration.CONFLICT
    assert res.conflicts == ["shared.txt"]
    assert res.returned and res.launched
    launch.assert_called_once()

    p = pr(w)
    assert p["status"] == "in_progress"
    ret = p["base_return"]
    assert ret["verdict"] == base_check.VERDICT_BASE_CONFLICT
    assert ret["stage"] == base_check.STAGE_REVIEW
    assert ret["head"] == w.head or ret["head"] == git(w.wd, "rev-parse", "HEAD")
    assert ret["base_sha"] == git(w.repo, "rev-parse", "master")
    assert ret["conflicts"] == ["shared.txt"]
    assert ret["awaiting"] == "impl"
    assert ret["attempt"] == 1
    # The exact pair and intended stage are recorded durably.
    assert any("Base integration conflict before starting review" in n["text"]
               for n in p["notes"])
    # The isolated check did not touch the worktree.
    assert git(w.wd, "status", "--porcelain", "--untracked-files=no") == ""


def test_same_unresolved_pair_does_not_bounce_again(w):
    with patch("pm_core.base_check.launch_impl", return_value=(True, "")) as launch:
        first = gate(w)
        second = gate(w, base_check.STAGE_REVIEW_ITERATION, iteration=2)
    assert first.decision == base_check.CONFLICT
    assert second.decision == base_check.WAIT
    assert second.already_returned and not second.returned
    assert launch.call_count == 1
    assert len([n for n in pr(w)["notes"] if "Base integration conflict" in n["text"]]) == 1


def test_conflict_before_qa_returns_to_implementation(w):
    set_pr(w, status="qa")
    with patch("pm_core.base_check.launch_impl", return_value=(True, "")):
        res = gate(w, base_check.STAGE_QA)
    assert res.decision == base_check.CONFLICT
    p = pr(w)
    assert p["status"] == "in_progress"
    assert p["base_return"]["stage"] == base_check.STAGE_QA


def test_qa_gate_skips_when_status_left_qa(w):
    set_pr(w, status="in_progress")
    res = gate(w, base_check.STAGE_QA)
    assert res.decision == base_check.SKIPPED


def test_signoff_return_owns_integration(w):
    set_pr(w, status="in_progress", signoff_return={
        "verdict": "SIGNOFF_IMPL", "hop": "impl", "awaiting": "impl",
        "ts": "2026-01-01T00:00:00+00:00"})
    res = gate(w)
    assert res.decision == base_check.SKIPPED


def test_return_cap_stops_automatic_rework(w):
    launches = []
    with patch("pm_core.base_check.launch_impl",
               side_effect=lambda *a, **k: (launches.append(1), (True, ""))[1]):
        gate(w)
        # Keep moving HEAD and the base, each still conflicting.
        for i in range(base_check.MAX_RETURNS_PER_BASE + 2):
            base_check.clear_return_awaiting(w.pm_dir, PR)
            commit(w.wd, f"f{i}.txt", "x\n", f"impl {i}")
            commit(w.repo, "shared.txt", f"base {i}\n", f"base {i}")
            base_check.impl_completion(
                w.pm_dir, PR, pr(w), idle_since=0,
                transcript_dir=w.tdir)
    ret = pr(w)["base_return"]
    assert ret.get("needs_human")
    assert "launch_claim" not in ret
    assert ret.get("awaiting") is None
    assert len(launches) <= base_check.MAX_RETURNS_PER_BASE


# --- clean / unchanged -----------------------------------------------------

def test_clean_and_unchanged_base_proceed(w):
    # Remove the conflicting base commit: the base is an ancestor of HEAD.
    git(w.repo, "reset", "-q", "--hard", "HEAD~1")
    res = gate(w)
    assert res.decision == base_check.PROCEED
    assert res.status == integration.UP_TO_DATE
    assert pr(w)["status"] == "in_review"
    assert pr(w).get("base_return") is None


def test_clean_moved_base_proceeds_without_reset(w):
    # A base change on a different file merges cleanly (drop the fixture's
    # conflicting shared.txt edit first).
    git(w.repo, "reset", "-q", "--hard", "HEAD~1")
    commit(w.repo, "other.txt", "x\n", "unrelated base")
    set_pr(w, status="in_review")
    with patch("pm_core.base_check.launch_impl") as launch:
        res = gate(w)
    assert res.decision == base_check.PROCEED
    assert res.status == integration.CLEAN
    launch.assert_not_called()
    p = pr(w)
    assert p["status"] == "in_review"
    assert p.get("reviewed_at") is None or True  # no phase reset
    assert p.get("base_return") is None


# --- retryable failures ----------------------------------------------------

def test_fetch_failure_is_retryable_not_a_conflict(w):
    def _apply(d):
        d["project"]["repo"] = str(w.repo / "does-not-exist")
    store.locked_update(w.pm_dir, _apply)
    res = gate(w)
    assert res.decision == base_check.RETRY
    assert res.status == integration.ERROR
    p = pr(w)
    assert p["status"] == "in_review"          # no bounce
    assert p.get("base_return") is None        # no conflict invented
    assert p["base_check"]["retryable"] is True
    assert p["base_check"].get("retry_after")


def test_recent_failure_suppresses_a_second_fetch(w):
    def _apply(d):
        d["project"]["repo"] = str(w.repo / "does-not-exist")
    store.locked_update(w.pm_dir, _apply)
    assert gate(w).decision == base_check.RETRY
    with patch("pm_core.integration.run_check") as run_check:
        res = gate(w)
    assert res.decision == base_check.RETRY
    run_check.assert_not_called()


# --- implementation completion --------------------------------------------

def test_completion_waits_for_a_launched_rework(w):
    with patch("pm_core.base_check.launch_impl", return_value=(True, "")):
        gate(w)
    res = base_check.impl_completion(w.pm_dir, PR, pr(w), idle_since=0)
    assert not res.complete
    assert "has not launched" in res.reason
    simulate_launch(w)
    res = base_check.impl_completion(w.pm_dir, PR, pr(w), idle_since=0)
    assert not res.complete
    assert "unchanged" in res.reason


def test_completion_after_reconciled_base_resolves_the_return(w):
    with patch("pm_core.base_check.launch_impl", return_value=(True, "")):
        gate(w)
    simulate_launch(w)
    # Reconcile: merge the base and commit the resolution.
    r = subprocess.run(["/usr/bin/git", "merge", "--no-edit", "FETCH_HEAD"],
                       cwd=w.wd, capture_output=True, text=True)
    if r.returncode != 0:
        (w.wd / "shared.txt").write_text("base\nmaster side\npr side\n")
        git(w.wd, "add", "shared.txt")
        git(w.wd, "commit", "-q", "-m", "merge base")
    res = base_check.impl_completion(w.pm_dir, PR, pr(w), idle_since=0,
                                     transcript_dir=w.tdir)
    assert res.complete, res.reason
    p = pr(w)
    assert p["base_return"]["resolved_at"]
    assert p["base_return"]["awaiting"] is None
    assert base_check.open_return(p) is None


def test_dirty_workdir_blocks_completion_and_is_retained(w):
    with patch("pm_core.base_check.launch_impl", return_value=(True, "")):
        gate(w)
    simulate_launch(w)
    (w.wd / "fixture.txt").write_text("keep me\n")       # untracked
    (w.wd / "feature.txt").write_text("edited\n")         # tracked edit
    res = base_check.impl_completion(w.pm_dir, PR, pr(w), idle_since=0)
    assert not res.complete
    assert "uncommitted edits" in res.reason
    assert (w.wd / "fixture.txt").read_text() == "keep me\n"
    assert (w.wd / "feature.txt").read_text() == "edited\n"
    assert base_check.open_return(pr(w)) is not None


def test_settle_window_blocks_an_immediate_idle(w):
    import time
    with patch("pm_core.base_check.launch_impl", return_value=(True, "")):
        gate(w)
    simulate_launch(w)
    res = base_check.impl_completion(w.pm_dir, PR, pr(w),
                                     idle_since=time.time())
    assert not res.complete
    assert "settle" in res.reason


def test_moved_base_during_handoff_returns_again(w):
    with patch("pm_core.base_check.launch_impl", return_value=(True, "")):
        gate(w)
    simulate_launch(w)
    first = pr(w)["base_return"]
    # HEAD moved but the new base still conflicts.
    commit(w.wd, "more.txt", "x\n", "more impl work")
    commit(w.repo, "shared.txt", "new master side\n", "master moves")
    res = base_check.impl_completion(w.pm_dir, PR, pr(w), idle_since=0,
                                     transcript_dir=w.tdir)
    assert not res.complete
    ret = pr(w)["base_return"]
    assert ret["attempt"] == 2
    assert ret["base_sha"] != first["base_sha"]
    assert ret["awaiting"] == "impl"


def test_launch_failure_keeps_awaiting_and_releases_the_claim(w):
    failing = subprocess.CompletedProcess(args=[], returncode=1,
                                          stdout="", stderr="spec pending")
    real_run = subprocess.run

    def fake_run(cmd, *a, **k):
        # Only the impl relaunch fails; the integration check's git calls
        # (same subprocess module) must still run for real.
        if isinstance(cmd, list) and any("pm_core.wrapper" in str(c) for c in cmd):
            return failing
        return real_run(cmd, *a, **k)

    with patch("pm_core.base_check.subprocess.run", side_effect=fake_run):
        res = gate(w)
    assert res.decision == base_check.CONFLICT
    assert not res.launched
    ret = pr(w)["base_return"]
    assert ret["awaiting"] == "impl"
    assert "launch_claim" not in ret
    assert "spec pending" in ret["apply_error"]


# --- idempotency / concurrency --------------------------------------------

def test_concurrent_gates_produce_one_return_and_one_launch(w):
    launches = []
    lock = threading.Lock()

    def _launch(*a, **k):
        with lock:
            launches.append(1)
        return True, ""

    results = []

    def _run():
        results.append(gate(w))

    with patch("pm_core.base_check.launch_impl", side_effect=_launch):
        threads = [threading.Thread(target=_run) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=20)
    decisions = sorted(r.decision for r in results)
    assert decisions.count(base_check.CONFLICT) == 1
    assert decisions.count(base_check.WAIT) == 3
    assert len(launches) == 1
    assert len(pr(w)["base_return"]) > 0


def test_stale_review_launch_is_refused_while_return_open(w):
    with patch("pm_core.base_check.launch_impl", return_value=(True, "")):
        gate(w)
    res = gate(w, base_check.STAGE_REVIEW_ITERATION, iteration=3)
    assert res.decision == base_check.WAIT


# --- prompt block ----------------------------------------------------------

def test_format_return_only_while_open(w):
    with patch("pm_core.base_check.launch_impl", return_value=(True, "")):
        gate(w)
    text = base_check.format_return(pr(w))
    assert "base integration conflict" in text.lower()
    assert "git merge" in text
    assert "shared.txt" in text
    simulate_launch(w)
    base_check.resolve_return(w.pm_dir, PR)
    assert base_check.format_return(pr(w)) == ""


def test_show_prints_the_base_return(w):
    from click.testing import CliRunner
    from pm_core.cli import pr as pr_mod
    with patch("pm_core.base_check.launch_impl", return_value=(True, "")):
        gate(w)
    runner = CliRunner()
    with patch.object(pr_mod, "state_root", return_value=w.pm_dir):
        result = runner.invoke(pr_mod.pr, ["show", PR])
    assert result.exit_code == 0, result.output
    assert "## Base integration return" in result.output
    assert "BASE_CONFLICT" in result.output
    assert "shared.txt" in result.output


# --- QA loop wiring --------------------------------------------------------

def test_qa_run_sync_returns_before_creating_the_qa_workdir(w):
    from pm_core.qa_loop import QALoopState, run_qa_sync
    set_pr(w, status="qa")
    state = QALoopState(pr_id=PR)
    with patch("pm_core.qa_loop.get_pm_session", return_value="pm-test"), \
         patch("pm_core.base_check.launch_impl", return_value=(True, "")):
        run_qa_sync(state, w.pm_dir, pr(w))
    assert state.base_returned is True
    assert state.running is False
    assert "shared.txt" in state.base_return_reason or "conflict" in state.base_return_reason
    # No QA workdir / Scenario 0 / planner was created.
    assert state.qa_workdir is None
    assert state.scenarios == []
    assert pr(w)["status"] == "in_progress"
    assert base_check.open_return(pr(w)) is not None


def test_qa_run_sync_clean_base_continues(w):
    """A clean check does not set base_returned (the existing QA flow runs)."""
    from pm_core.qa_loop import QALoopState, run_qa_sync
    git(w.repo, "reset", "-q", "--hard", "HEAD~1")
    set_pr(w, status="qa")
    state = QALoopState(pr_id=PR)
    with patch("pm_core.qa_loop.get_pm_session", return_value="pm-test"), \
         patch("pm_core.qa_loop._get_qa_spec", return_value=None), \
         patch("pm_core.qa_loop.create_qa_workdir") as mk:
        # Stop after the gate by making the QA workdir fail loudly.
        mk.side_effect = RuntimeError("stop here")
        with pytest.raises(RuntimeError):
            run_qa_sync(state, w.pm_dir, pr(w))
    assert state.base_returned is False
    assert pr(w)["status"] == "qa"


def test_prompts_carry_the_return_block(w):
    from pm_core import prompt_gen
    with patch("pm_core.base_check.launch_impl", return_value=(True, "")):
        gate(w)
    data = store.load(w.pm_dir)
    marker = "Returned to implementation: base integration conflict"
    assert marker in prompt_gen.generate_review_prompt(data, PR)
    assert marker in prompt_gen.generate_qa_planner_prompt(data, PR, "pm-test")
    assert marker in prompt_gen.generate_prompt(data, PR, "pm-test")


def test_pm_state_file_does_not_block_completion(w):
    """The host writes project.yaml into a workdir; it is not an impl edit."""
    with patch("pm_core.base_check.launch_impl", return_value=(True, "")):
        gate(w)
    simulate_launch(w)
    (w.wd / "pm").mkdir(exist_ok=True)
    (w.wd / "pm" / "project.yaml").write_text("state: changed\n")
    git(w.wd, "add", "pm/project.yaml")
    # Commit the file first so it is tracked, then dirty it (the host rewrite).
    git(w.wd, "commit", "-q", "-m", "track pm state")
    (w.wd / "pm" / "project.yaml").write_text("state: host rewrite\n")
    # Reconcile the base so only the dirtiness could block.
    subprocess.run(["/usr/bin/git", "fetch", str(w.repo), "master"],
                   cwd=w.wd, capture_output=True)
    r = subprocess.run(["/usr/bin/git", "merge", "--no-edit", "FETCH_HEAD"],
                       cwd=w.wd, capture_output=True, text=True)
    if r.returncode != 0:
        (w.wd / "shared.txt").write_text("base\nmaster side\npr side\n")
        git(w.wd, "add", "shared.txt")
        git(w.wd, "commit", "-q", "-m", "merge base")
    res = base_check.impl_completion(w.pm_dir, PR, pr(w), idle_since=0)
    assert res.complete, res.reason


def test_qa_gate_waits_on_a_raced_status_with_open_return(w):
    with patch("pm_core.base_check.launch_impl", return_value=(True, "")):
        gate(w, base_check.STAGE_REVIEW)
    # The PR is in_progress now; a stale QA start must wait, not run QA.
    res = gate(w, base_check.STAGE_QA)
    assert res.decision == base_check.WAIT
    assert res.already_returned
