"""Pre-flight base integration gate before review iterations and QA.

Real git + real project.yaml: a conflicting base returns the PR to
implementation before the downstream writer starts, records the exact
HEAD/base pair, hands off exactly once, and only lets the phase continue
once the rework genuinely reconciled the base.
"""

from __future__ import annotations

import subprocess
import threading
import time
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


def reconcile(w):
    """Merge the fixture's conflicting base into the PR branch."""
    subprocess.run(["/usr/bin/git", "merge", "--no-edit", "FETCH_HEAD"],
                   cwd=w.wd, capture_output=True, text=True)
    if git(w.wd, "status", "--porcelain"):
        (w.wd / "shared.txt").write_text("base\nmaster side\npr side\n")
        git(w.wd, "add", "shared.txt")
        git(w.wd, "commit", "-q", "-m", "merge base")


def completion(w, **kw):
    """``impl_completion`` with a genuine, settled idle turn.

    The idle event is stamped *now* (after the return's relaunch, which
    ``simulate_launch`` records) and the settle window is disabled so the
    call exercises the completion decision rather than the timing guards.
    """
    import time
    kw.setdefault("idle_since", time.time())
    with patch.object(base_check, "IDLE_SETTLE_SECONDS", 0.0):
        return base_check.impl_completion(w.pm_dir, PR, pr(w), **kw)


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


def test_conflict_before_a_later_review_iteration_records_the_stage(w):
    """The third transition point: a conflict before iteration N > 1.

    The return must name the stage it blocked (and which iteration) so the
    rework prompt and ``pm pr show`` say what was about to run.
    """
    with patch("pm_core.base_check.launch_impl",
               return_value=(True, "")) as launch:
        res = gate(w, base_check.STAGE_REVIEW_ITERATION, iteration=3)
    assert res.decision == base_check.CONFLICT
    assert res.returned and res.launched
    launch.assert_called_once()
    ret = pr(w)["base_return"]
    assert ret["stage"] == base_check.STAGE_REVIEW_ITERATION
    assert ret["iteration"] == 3
    assert ret["head"] == git(w.wd, "rev-parse", "HEAD")
    assert any("review iteration 3" in n["text"] for n in pr(w)["notes"])


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
            completion(w, transcript_dir=w.tdir)
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
    res = completion(w)
    assert not res.complete
    assert "has not launched" in res.reason
    simulate_launch(w)
    res = completion(w)
    assert not res.complete
    assert "unchanged" in res.reason


def test_successful_relaunch_clears_a_stale_apply_error(w):
    """A failed launch's error must not outlive the launch that worked.

    ``release_impl_claim`` records the failure while ``awaiting`` stays set;
    a later driver retries and succeeds.  Leaving ``apply_error`` on the
    record makes ``pm pr show`` report a failure that is no longer true for
    the rest of the episode.
    """
    with patch("pm_core.base_check.launch_impl", return_value=(True, "")):
        gate(w)
    set_pr(w, base_return={**pr(w)["base_return"],
                           "awaiting": "impl",
                           "apply_error": "spec pending"})
    base_check.clear_return_awaiting(w.pm_dir, PR)
    ret = pr(w)["base_return"]
    assert ret["awaiting"] is None
    assert "apply_error" not in ret


def test_share_impl_transcript_accepts_a_direct_path(w):
    """A direct JSONL path (not a symlink) is still a valid target."""
    import os
    other = w.pm_dir / "transcripts" / "run-b" / f"impl-{PR}.jsonl"
    other.parent.mkdir(parents=True)
    other.symlink_to("/nonexistent/old-session.jsonl")
    real = w.tdir / f"impl-{PR}.jsonl"
    real.write_text("{}")
    base_check.share_impl_transcript(w.pm_dir, PR, real)
    assert os.readlink(other) == str(real)
    # No transcript at all (a foreground launch) is a no-op.
    base_check.share_impl_transcript(w.pm_dir, PR, None)
    assert os.readlink(other) == str(real)


def test_share_impl_transcript_preserves_a_finalized_copy(w):
    """A finalized (real-file) transcript is evidence, not a stale link.

    ``finalize_transcript`` replaces a finished session's link with a copy of
    its JSONL.  Refreshing the link for a relaunch must not delete that copy —
    it is the self-contained record that survives Claude session pruning.
    """
    import os
    run = w.pm_dir / "transcripts" / "run-old"
    run.mkdir(parents=True)
    finalized = run / f"impl-{PR}.jsonl"
    finalized.write_text('{"old": "session"}\n')
    fresh = w.tdir / f"impl-{PR}.jsonl"
    new_target = "/tmp/new-session.jsonl"
    fresh.symlink_to(new_target)

    base_check.share_impl_transcript(w.pm_dir, PR, fresh)

    # The link follows the new session and the old copy survives beside it.
    assert os.readlink(finalized) == new_target
    kept = run / f"impl-{PR}.jsonl.finalized"
    assert kept.read_text() == '{"old": "session"}\n'
    # A second pass does not renumber/duplicate the kept copy.
    base_check.share_impl_transcript(w.pm_dir, PR, fresh)
    assert kept.read_text() == '{"old": "session"}\n'
    assert not (run / f"impl-{PR}.jsonl.finalized.1").exists()


def test_share_impl_transcript_does_not_move_the_transcript_itself(w, monkeypatch):
    """A relatively-spelled transcript must not be renamed to ``.finalized``.

    ``pm pr start --transcript transcripts/run-x/impl-pr.jsonl`` hands over a
    relative path while ``glob`` returns the absolute one, so the transcript
    itself looks like another driver's stale copy.  Renaming it would move the
    evidence and leave a broken link in its place.
    """
    run = w.pm_dir / "transcripts" / "run-x"
    run.mkdir(parents=True)
    real = run / f"impl-{PR}.jsonl"
    real.write_text('{"evidence": true}\n')
    monkeypatch.chdir(w.pm_dir)

    base_check.share_impl_transcript(
        w.pm_dir, PR, f"transcripts/run-x/impl-{PR}.jsonl")

    assert real.is_file() and not real.is_symlink()
    assert real.read_text() == '{"evidence": true}\n'
    assert not (run / f"impl-{PR}.jsonl.finalized").exists()


def test_completion_requires_idle_evidence(w):
    """No idle timestamp is no evidence: an idle notification alone never
    qualifies, so a caller that cannot read the pane's turn must not complete.

    Without this a missing timestamp silently skips both the settle window
    and the ``launched_at`` guard, letting a review start beside a rework
    session whose turn was never observed to end.
    """
    with patch("pm_core.base_check.launch_impl", return_value=(True, "")):
        gate(w)
    simulate_launch(w)
    reconcile(w)
    res = base_check.impl_completion(w.pm_dir, PR, pr(w))
    assert not res.complete
    assert "idle evidence" in res.reason
    # A real idle turn still completes.
    done = completion(w)
    assert done.complete, done.reason


def test_completion_tolerates_a_null_base_return(w):
    """A corrupt ``base_return: null`` must not stall the handoff.

    ``open_return`` already treats a non-dict as "no return"; the
    ``resume_loop`` read must not then raise (which the outer guard would
    report as a failed check on every poll, never completing).
    """
    set_pr(w, base_return=None)
    res = base_check.impl_completion(w.pm_dir, PR, pr(w),
                                     idle_since=time.time())
    assert res.complete, res.reason
    assert res.resume_loop is False


@pytest.mark.parametrize("corrupt", ["a string", ["a", "list"], 7])
def test_completion_tolerates_a_non_dict_base_return(w, corrupt):
    """A hand-edited ``base_return`` of any non-dict shape reads as no record.

    ``open_return`` already returns None for these; the ``resume_loop`` read
    in the "no open return" branch must not then raise, or the outer guard
    reports "completion check failed" on every poll and the handoff can never
    complete (the same stuck state the null case pins).
    """
    set_pr(w, base_return=corrupt)
    res = base_check.impl_completion(w.pm_dir, PR, pr(w),
                                     idle_since=time.time())
    assert res.complete, res.reason
    assert res.resume_loop is False


def test_completion_after_reconciled_base_resolves_the_return(w):
    with patch("pm_core.base_check.launch_impl", return_value=(True, "")):
        gate(w)
    simulate_launch(w)
    # Reconcile: merge the base and commit the resolution.
    reconcile(w)
    res = completion(w, transcript_dir=w.tdir)
    assert res.complete, res.reason
    p = pr(w)
    assert p["base_return"]["resolved_at"]
    assert p["base_return"]["awaiting"] is None
    assert base_check.open_return(p) is None
    # The clean verdict replaces the conflict/retry record, so `pm pr show`
    # and the next gate's retry suppression do not read a stale episode.
    assert p["base_check"]["decision"] == base_check.PROCEED
    assert p["base_check"]["retryable"] is False


def test_review_loop_bounce_records_and_reports_resume_loop(w):
    """A TUI review-loop bounce resumes the loop once the rework finishes.

    The marker travels gate -> ``base_return`` -> ``impl_completion``; the
    TUI scheduler reads it to restart the interrupted loop (a one-shot
    ``z d`` has no loop to resume).
    """
    with patch("pm_core.base_check.launch_impl", return_value=(True, "")):
        res = gate(w, base_check.STAGE_REVIEW, resume_loop=True)
    assert res.decision == base_check.CONFLICT
    assert pr(w)["base_return"].get("resume_loop") is True
    simulate_launch(w)
    reconcile(w)
    done = completion(w, transcript_dir=w.tdir)
    assert done.complete, done.reason
    assert done.resume_loop is True


def test_one_shot_bounce_does_not_resume_a_loop(w):
    with patch("pm_core.base_check.launch_impl", return_value=(True, "")):
        gate(w)
    assert "resume_loop" not in pr(w)["base_return"]
    simulate_launch(w)
    reconcile(w)
    done = completion(w, transcript_dir=w.tdir)
    assert done.complete, done.reason
    assert done.resume_loop is False


def test_moved_base_during_handoff_keeps_the_resume_loop_marker(w):
    """Superseding the episode must not drop the loop-resume intent."""
    with patch("pm_core.base_check.launch_impl", return_value=(True, "")):
        gate(w, base_check.STAGE_REVIEW, resume_loop=True)
    simulate_launch(w)
    commit(w.wd, "more.txt", "x\n", "more impl work")
    commit(w.repo, "shared.txt", "new master side\n", "master moves")
    res = completion(w, transcript_dir=w.tdir)
    assert not res.complete
    ret = pr(w)["base_return"]
    assert ret["attempt"] == 2
    assert ret.get("resume_loop") is True


def test_gate_supersede_keeps_the_loop_resume_marker(w):
    """A one-shot gate superseding a loop episode keeps its resume intent.

    The base moves during the rework and the new pair still conflicts, so a
    manual ``d`` (``resume_loop=False``) supersedes the episode through the
    gate.  The flag belongs to the bounce, not to the superseding driver: the
    interrupted review loop must still restart once the rework lands.
    """
    with patch("pm_core.base_check.launch_impl", return_value=(True, "")):
        gate(w, base_check.STAGE_REVIEW, resume_loop=True)
    simulate_launch(w)
    commit(w.wd, "more.txt", "x\n", "more impl work")
    commit(w.repo, "shared.txt", "new master side\n", "master moves")
    with patch("pm_core.base_check.launch_impl", return_value=(True, "")):
        res = gate(w, base_check.STAGE_REVIEW_ITERATION, iteration=2)
    assert res.decision == base_check.CONFLICT, res.reason
    ret = pr(w)["base_return"]
    assert ret["attempt"] == 2
    assert ret.get("resume_loop") is True


def test_completion_ignores_idle_evidence_from_before_the_relaunch(w):
    """The killed session's idle event is not the rework session's turn.

    A stale ``impl-<pr>.jsonl`` symlink keeps reporting the old session's
    ``idle_prompt``; without the relaunch guard its (already old) timestamp
    passes the settle window and an idle notification from before the rework
    would qualify as completion.
    """
    import time
    with patch("pm_core.base_check.launch_impl", return_value=(True, "")):
        gate(w)
    simulate_launch(w)          # records launched_at
    reconcile(w)
    stale = time.time() - 3600
    res = base_check.impl_completion(w.pm_dir, PR, pr(w), idle_since=stale,
                                     transcript_dir=w.tdir)
    assert not res.complete
    assert "no idle evidence" in res.reason
    # A genuine idle turn *after* the relaunch still completes.
    with patch.object(base_check, "IDLE_SETTLE_SECONDS", 0.0):
        res = base_check.impl_completion(w.pm_dir, PR, pr(w),
                                         idle_since=time.time(),
                                         transcript_dir=w.tdir)
    assert res.complete, res.reason


def test_dirty_workdir_blocks_completion_and_is_retained(w):
    with patch("pm_core.base_check.launch_impl", return_value=(True, "")):
        gate(w)
    simulate_launch(w)
    (w.wd / "fixture.txt").write_text("keep me\n")       # untracked
    (w.wd / "feature.txt").write_text("edited\n")         # tracked edit
    res = completion(w)
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


def test_pm_state_exemption_is_path_exact(w):
    """Only pm's own state paths are ignored, not any ``project.yaml``.

    The exemption exists for the host-written state file at the repo root or
    under ``pm/``.  A tracked file that merely happens to be named
    ``project.yaml`` in some other ``pm/`` directory is a real implementation
    edit and must block the handoff (a directory-name match would hide it).
    """
    assert base_check.tracked_dirty(str(w.wd)) is False

    nested = w.wd / "sub" / "pm"
    nested.mkdir(parents=True)
    (nested / "project.yaml").write_text("tracked\n")
    git(w.wd, "add", "sub/pm/project.yaml")
    git(w.wd, "commit", "-q", "-m", "track nested state file")
    (nested / "project.yaml").write_text("unfinished edit\n")
    assert base_check.tracked_dirty(str(w.wd)) is True

    # A dirty root project.yaml (the host's write) is exempt, as before.
    (w.wd / "project.yaml").write_text("host state\n")
    git(w.wd, "add", "project.yaml")
    git(w.wd, "commit", "-q", "-m", "track root state file")
    (w.wd / "project.yaml").write_text("host rewrite\n")
    git(w.wd, "checkout", "--", "sub/pm/project.yaml")
    assert base_check.tracked_dirty(str(w.wd)) is False


def test_moved_base_during_handoff_returns_again(w):
    with patch("pm_core.base_check.launch_impl", return_value=(True, "")):
        gate(w)
    simulate_launch(w)
    first = pr(w)["base_return"]
    # HEAD moved but the new base still conflicts.
    commit(w.wd, "more.txt", "x\n", "more impl work")
    commit(w.repo, "shared.txt", "new master side\n", "master moves")
    res = completion(w, transcript_dir=w.tdir)
    assert not res.complete
    ret = pr(w)["base_return"]
    assert ret["attempt"] == 2
    assert ret["base_sha"] != first["base_sha"]
    assert ret["awaiting"] == "impl"


def test_launch_impl_repairs_the_other_drivers_transcript(w):
    """A relaunch stays trackable from the dir the old session used.

    The TUI run dir and the auto-sequence dir each hold their own
    ``impl-<pr>.jsonl`` symlink; a relaunch that wrote only its own would
    leave the other drivers reading the killed session's hook events.
    """
    import os
    stale = w.pm_dir / "transcripts" / "run-a" / f"impl-{PR}.jsonl"
    stale.parent.mkdir(parents=True)
    stale.symlink_to("/nonexistent/old-session.jsonl")
    fresh = w.tdir / f"impl-{PR}.jsonl"
    new_target = "/tmp/new-session.jsonl"

    def fake_run(cmd, *a, **k):
        # ``pm pr start --transcript <path>`` creates the symlink.
        fresh.symlink_to(new_target)
        return subprocess.CompletedProcess(args=cmd, returncode=0,
                                           stdout="", stderr="")

    with patch("pm_core.base_check.subprocess.run", side_effect=fake_run):
        ok, detail = base_check.launch_impl(w.pm_dir, PR, w.tdir)
    assert ok, detail
    assert os.readlink(stale) == new_target


def test_large_conflict_list_is_bounded_in_the_return(w):
    """project.yaml keeps the record small; the totals keep it truthful."""
    paths = [f"dir/file{i}.txt" for i in range(120)]
    record = {"status": integration.CONFLICT, "head": "h" * 40,
              "base_sha": "b" * 40, "base_branch": "master",
              "target_repo": str(w.repo), "conflicts": paths,
              "overlap": paths[:60]}
    with patch("pm_core.base_check.launch_impl", return_value=(True, "")):
        rec = base_check.return_to_impl(w.pm_dir, PR, record,
                                        base_check.STAGE_REVIEW)
    assert rec is not None
    stored = pr(w)["base_return"]
    limit = integration._YAML_LIST_LIMIT
    assert len(stored["conflicts"]) == limit
    assert stored["conflicts_total"] == 120
    assert len(stored["overlap"]) == limit
    assert stored["overlap_total"] == 60


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


def test_losing_gate_reports_the_episode_that_landed(w):
    """A gate that loses the return race reports the winner's pair.

    ``return_to_impl`` returns ``None`` when another driver recorded the
    return between this gate's fetch and its write.  The WAIT result must
    then carry the episode that actually landed (HEAD/base/conflicts) rather
    than the empty pre-check snapshot this call started from: the caller and
    the log would otherwise describe a conflict with no pair at all.
    """
    real = base_check.return_to_impl

    def _lose(*a, **kw):
        real(*a, **kw)      # another driver records the return first
        return None         # ... and this gate is told it lost

    with patch.object(base_check, "return_to_impl", _lose):
        res = gate(w)
    assert res.decision == base_check.WAIT
    assert res.already_returned is True
    assert res.status == integration.CONFLICT
    assert res.head == pr(w)["base_return"]["head"]
    assert res.base_sha == pr(w)["base_return"]["base_sha"]
    assert res.conflicts == ["shared.txt"]


def test_stale_review_launch_is_refused_while_return_open(w):
    with patch("pm_core.base_check.launch_impl", return_value=(True, "")):
        gate(w)
    res = gate(w, base_check.STAGE_REVIEW_ITERATION, iteration=3)
    assert res.decision == base_check.WAIT


def test_non_dict_base_return_still_records_the_return(w):
    """A corrupt ``base_return`` (a string, a list) must not raise.

    The gate would otherwise report "the PR left the phase" and leave it in
    review with an unreconcilable base — the same failure mode the malformed
    ``attempt`` and null-record tests cover.
    """
    set_pr(w, base_return="hand-edited garbage")
    with patch("pm_core.base_check.launch_impl", return_value=(True, "")) as launch:
        res = gate(w)
    assert res.decision == base_check.CONFLICT, res.reason
    assert res.returned
    launch.assert_called_once()
    assert pr(w)["base_return"]["attempt"] == 1


def test_non_dict_base_check_does_not_disable_the_gate(w):
    """A corrupt ``base_check`` (a string, a list) must read as "no record".

    ``_retry_open`` runs on the gate's hot path and inside
    ``impl_completion``; raising there makes the gate fail open (no return is
    ever recorded) and the completion check report "failed" on every poll, so
    a hand-edited project.yaml would leave the PR with an open return nobody
    can resolve.
    """
    set_pr(w, base_check="hand-edited garbage")
    assert base_check._retry_open(pr(w), w.head) is False
    with patch("pm_core.base_check.launch_impl", return_value=(True, "")) as launch:
        res = gate(w)
    assert res.decision == base_check.CONFLICT, res.reason
    assert res.returned
    launch.assert_called_once()
    # ``return_to_impl`` replaced the corrupt record with a real one.
    assert pr(w)["base_return"]["attempt"] == 1
    assert pr(w)["base_check"]["decision"] == base_check.CONFLICT


def test_non_dict_base_check_still_records_a_probe_failure(w):
    """The error recorder must not raise on a corrupt previous record."""
    def _apply(d):
        d["project"]["repo"] = str(w.repo / "does-not-exist")
        store.get_pr(d, PR)["base_check"] = ["hand-edited"]
    store.locked_update(w.pm_dir, _apply)
    res = gate(w)
    assert res.decision == base_check.RETRY
    rec = pr(w)["base_check"]
    assert rec["retryable"] is True
    assert rec.get("retry_after")


def test_malformed_attempt_still_records_the_return(w):
    """A corrupt ``attempt`` must not turn the return into a silent no-op.

    ``return_to_impl`` raises inside the locked update when it cannot read
    the counter, and the gate then reports "the PR left the phase" instead
    of handing it to implementation — a hand-edited project.yaml would leave
    the PR in review with an unreconcilable base.
    """
    set_pr(w, base_return={"verdict": base_check.VERDICT_BASE_CONFLICT,
                           "head": "old", "base_sha": "old-base",
                           "attempt": "not-a-number",
                           "ts": "2026-01-01T00:00:00+00:00",
                           "resolved_at": "2026-01-01T00:00:00+00:00"})
    with patch("pm_core.base_check.launch_impl", return_value=(True, "")) as launch:
        res = gate(w)
    assert res.decision == base_check.CONFLICT, res.reason
    assert res.returned
    launch.assert_called_once()
    assert pr(w)["base_return"]["attempt"] == 1


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


# --- the `pm pr review` choke point ---------------------------------------

def test_pr_review_exits_3_without_writing_the_status(w):
    """The CLI choke point: a conflict never starts the reviewer.

    ``pm pr review`` must not write ``in_review`` or open a review window on
    a conflicting base — exit 3 is the contract ``review_loop`` maps to
    ``VERDICT_BASE_CONFLICT``.
    """
    from click.testing import CliRunner
    from pm_core.cli import pr as pr_mod

    runner = CliRunner()
    with patch.object(pr_mod, "state_root", return_value=w.pm_dir), \
         patch("pm_core.base_check.launch_impl", return_value=(True, "")) as launch, \
         patch.object(pr_mod, "_launch_review_window") as window:
        result = runner.invoke(
            pr_mod.pr, ["review", "--review-iteration", "2", PR])
    assert result.exit_code == 3, result.output
    assert "base_conflict" in result.output
    window.assert_not_called()
    launch.assert_called_once()
    p = pr(w)
    assert p["status"] == "in_progress"
    ret = p["base_return"]
    assert ret["stage"] == base_check.STAGE_REVIEW_ITERATION
    assert ret["iteration"] == 2
    assert ret["conflicts"] == ["shared.txt"]


def test_pr_review_clean_base_launches_the_reviewer(w):
    from click.testing import CliRunner
    from pm_core.cli import pr as pr_mod

    git(w.repo, "reset", "-q", "--hard", "HEAD~1")
    runner = CliRunner()
    with patch.object(pr_mod, "state_root", return_value=w.pm_dir), \
         patch.object(pr_mod, "_launch_review_window") as window:
        result = runner.invoke(pr_mod.pr, ["review", PR])
    assert result.exit_code == 0, result.output
    window.assert_called_once()
    assert pr(w)["status"] == "in_review"


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


def test_qa_run_sync_aborts_when_the_pr_merged_during_the_gate(w):
    """A merge landing inside the gate's fetch must not start QA.

    The gate is a network round-trip placed after the "as late as possible"
    merged/closed check; without a re-check a PR merged meanwhile would get a
    QA workdir and planner window against a finished PR.
    """
    from pm_core.qa_loop import QALoopState, run_qa_sync
    set_pr(w, status="qa")
    state = QALoopState(pr_id=PR)

    def _merged_during_gate(*_a, **_k):
        set_pr(w, status="merged")
        return base_check.GateResult(base_check.PROCEED, base_check.STAGE_QA)

    with patch("pm_core.qa_loop.get_pm_session", return_value="pm-test"), \
         patch("pm_core.base_check.gate", side_effect=_merged_during_gate), \
         patch("pm_core.qa_loop.create_qa_workdir") as mk:
        run_qa_sync(state, w.pm_dir, pr(w))
    mk.assert_not_called()
    assert state.running is False
    assert state.base_returned is False
    assert state.qa_workdir is None


def test_pr_review_does_not_demote_a_pr_merged_during_the_gate(w):
    """A merge landing inside the gate's fetch must not be undone.

    ``pm pr review`` reads the status, runs the base check (a network
    round-trip) and then writes in_review.  Without the guard a concurrent
    merge is overwritten in project.yaml and a reviewer starts against a
    finished PR.
    """
    from click.testing import CliRunner
    from pm_core.cli import pr as pr_mod

    set_pr(w, status="in_progress")

    def _merged_during_gate(*_a, **_k):
        set_pr(w, status="merged")
        return base_check.GateResult(base_check.PROCEED, base_check.STAGE_REVIEW)

    runner = CliRunner()
    with patch.object(pr_mod, "state_root", return_value=w.pm_dir), \
         patch("pm_core.base_check.gate", side_effect=_merged_during_gate), \
         patch.object(pr_mod, "_launch_review_window") as window:
        result = runner.invoke(pr_mod.pr, ["review", PR])
    assert result.exit_code == 1, result.output
    window.assert_not_called()
    assert pr(w)["status"] == "merged"


def _return_during_gate(w, stage):
    """A conflict return recorded by another driver inside the gate's fetch."""
    return base_check.return_to_impl(
        w.pm_dir, PR,
        {"head": w.head, "base_sha": "b" * 40, "base_branch": "master",
         "status": integration.CONFLICT, "conflicts": ["shared.txt"]},
        stage)


def test_pr_review_does_not_start_beside_a_return_recorded_during_the_gate(w):
    """A conflict recorded inside the gate's fetch owns the PR.

    The gate itself found the base clean, but another driver's check (the
    TUI completion handoff) recorded a return in the same network window.
    Writing in_review and launching a reviewer would then race the
    implementation rework the return just started.
    """
    from click.testing import CliRunner
    from pm_core.cli import pr as pr_mod

    set_pr(w, status="in_progress")

    def _returned_during_gate(*_a, **_k):
        _return_during_gate(w, base_check.STAGE_REVIEW)
        return base_check.GateResult(base_check.PROCEED, base_check.STAGE_REVIEW)

    runner = CliRunner()
    with patch.object(pr_mod, "state_root", return_value=w.pm_dir), \
         patch("pm_core.base_check.gate", side_effect=_returned_during_gate), \
         patch.object(pr_mod, "_launch_review_window") as window:
        result = runner.invoke(pr_mod.pr, ["review", PR])
    # Exit 3 (not 1): the PR was returned to implementation, which
    # review_loop maps to VERDICT_BASE_CONFLICT — routing, not a failure.
    assert result.exit_code == 3, result.output
    window.assert_not_called()
    assert pr(w)["status"] == "in_progress"
    assert base_check.open_return(pr(w)) is not None


def test_qa_run_sync_waits_when_a_return_lands_during_the_gate(w):
    """A conflict recorded inside the gate's fetch must not open a planner."""
    from pm_core.qa_loop import QALoopState, run_qa_sync
    set_pr(w, status="qa")
    state = QALoopState(pr_id=PR)

    def _returned_during_gate(*_a, **_k):
        _return_during_gate(w, base_check.STAGE_QA)
        return base_check.GateResult(base_check.PROCEED, base_check.STAGE_QA)

    with patch("pm_core.qa_loop.get_pm_session", return_value="pm-test"), \
         patch("pm_core.base_check.gate", side_effect=_returned_during_gate), \
         patch("pm_core.qa_loop.create_qa_workdir") as mk:
        # The guard must fire before the QA workdir/planner exists at all.
        mk.side_effect = AssertionError("QA workdir created beside the rework")
        run_qa_sync(state, w.pm_dir, pr(w))
    mk.assert_not_called()
    assert state.running is False
    assert state.base_returned is True
    assert "CONFLICTS" in state.base_return_reason
    assert state.qa_workdir is None
    assert pr(w)["status"] == "in_progress"


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
    res = completion(w)
    assert res.complete, res.reason


def test_qa_gate_waits_on_a_raced_status_with_open_return(w):
    with patch("pm_core.base_check.launch_impl", return_value=(True, "")):
        gate(w, base_check.STAGE_REVIEW)
    # The PR is in_progress now; a stale QA start must wait, not run QA.
    res = gate(w, base_check.STAGE_QA)
    assert res.decision == base_check.WAIT
    assert res.already_returned


def test_gate_self_heals_a_return_when_the_base_moves_clean(w):
    """A stale/manual gate call resolves the episode once the base is clean."""
    with patch("pm_core.base_check.launch_impl", return_value=(True, "")):
        gate(w)
    simulate_launch(w)
    git(w.repo, "reset", "-q", "--hard", "HEAD~1")
    commit(w.repo, "other.txt", "x\n", "clean base")
    res = gate(w)
    assert res.decision == base_check.PROCEED
    assert base_check.open_return(pr(w)) is None
    assert pr(w)["base_return"]["resolved_at"]


def test_gate_does_not_resolve_a_return_recorded_during_its_own_check(w):
    """A conflict another driver records inside the gate's fetch survives it.

    ``gate`` reuses the integration primitive, which fetches the base.  A
    concurrent check can record a conflict return inside that window (the base
    moved between the two fetches).  The clean path used to call
    ``resolve_return`` unconditionally and close it — the caller then saw no
    open return and launched a reviewer beside the rework.  The caller-level
    race tests patch ``gate`` itself, so they never exercised this path.
    """
    set_pr(w, status="in_progress")
    clean = {"status": integration.CLEAN, "head": w.head,
             "base_sha": "b" * 40, "base_branch": "master",
             "target_repo": str(w.repo), "conflicts": [], "overlap": [],
             "checked_at": "2026-01-01T00:00:00+00:00"}

    def _clean_but_returned(*_a, **_k):
        # This check's own fetch saw a clean base ...
        _return_during_gate(w, base_check.STAGE_REVIEW)
        return dict(clean)

    with patch("pm_core.base_check.evaluate", side_effect=_clean_but_returned):
        res = base_check.gate(w.pm_dir, PR, base_check.STAGE_REVIEW,
                              transcript=w.tdir / "r.jsonl")
    assert res.decision == base_check.WAIT
    assert res.already_returned
    assert base_check.open_return(pr(w)) is not None
    assert pr(w)["status"] == "in_progress"
    # No clean decision is stamped over the episode that owns the PR.
    assert pr(w)["base_check"]["decision"] == base_check.CONFLICT


def test_completion_does_not_resolve_a_return_recorded_during_its_check(w):
    """A superseding return recorded inside the completion check stays open.

    ``impl_completion`` re-fetches the base.  If another driver records a new
    conflict episode in that window (a moved base), resolving it would report
    the handoff complete and start a reviewer beside the new rework.
    """
    with patch("pm_core.base_check.launch_impl", return_value=(True, "")):
        gate(w)                       # open return; PR now in_progress
    simulate_launch(w)                # the rework session launched
    commit(w.wd, "rework.txt", "x\n", "rework")   # HEAD moved past the pair
    clean = {"status": integration.CLEAN, "head": git(w.wd, "rev-parse", "HEAD"),
             "base_sha": "b" * 40, "base_branch": "master",
             "target_repo": str(w.repo), "conflicts": [], "overlap": [],
             "checked_at": "2026-01-01T00:00:00+00:00"}

    def _clean_but_superseded(*_a, **_k):
        base_check.return_to_impl(
            w.pm_dir, PR,
            {"head": "c" * 40, "base_sha": "d" * 40, "base_branch": "master",
             "status": integration.CONFLICT, "conflicts": ["other.txt"]},
            base_check.STAGE_REVIEW, supersede=True)
        return dict(clean)

    with patch("pm_core.base_check.evaluate",
               side_effect=_clean_but_superseded):
        res = completion(w)
    assert not res.complete
    assert "recorded during" in res.reason
    assert base_check.open_return(pr(w)) is not None


def test_resolve_return_leaves_a_superseding_episode_open(w):
    """``expect_ts`` pins the resolve to the episode the check was based on."""
    with patch("pm_core.base_check.launch_impl", return_value=(True, "")):
        gate(w)
    first_ts = pr(w)["base_return"]["ts"]
    base_check.return_to_impl(
        w.pm_dir, PR,
        {"head": "c" * 40, "base_sha": "d" * 40, "base_branch": "master",
         "status": integration.CONFLICT, "conflicts": ["other.txt"]},
        base_check.STAGE_REVIEW, supersede=True)
    assert pr(w)["base_return"]["ts"] != first_ts
    assert base_check.resolve_return(w.pm_dir, PR, expect_ts=first_ts) is False
    assert base_check.open_return(pr(w)) is not None
    # The episode it names is still closable.
    assert base_check.resolve_return(
        w.pm_dir, PR, expect_ts=pr(w)["base_return"]["ts"]) is True
    assert base_check.open_return(pr(w)) is None


def test_capped_return_resumes_once_a_human_reconciles_the_base(w):
    """``needs_human`` stops auto-rework, not recovery.

    The note/``format_return`` text says a human must reconcile the base
    "before review/QA resumes" — so a reconciled (now clean) base must let
    the phase continue instead of leaving the PR permanently stuck.
    """
    with patch("pm_core.base_check.launch_impl", return_value=(True, "")):
        gate(w)
        for i in range(base_check.MAX_RETURNS_PER_BASE + 2):
            base_check.clear_return_awaiting(w.pm_dir, PR)
            commit(w.wd, f"f{i}.txt", "x\n", f"impl {i}")
            commit(w.repo, "shared.txt", f"base {i}\n", f"base {i}")
            completion(w, transcript_dir=w.tdir)
    ret = pr(w)["base_return"]
    assert ret.get("needs_human")
    # Still conflicting: the gate waits and never writes a new episode.
    before = pr(w)["base_return"]
    with patch("pm_core.base_check.launch_impl") as launch:
        still = gate(w)
    assert still.decision == base_check.WAIT
    launch.assert_not_called()
    assert pr(w)["base_return"] == before          # no new episode/note

    # A human reconciles the current base by hand; the gate resumes.
    subprocess.run(["/usr/bin/git", "fetch", str(w.repo), "master"],
                   cwd=w.wd, capture_output=True)
    subprocess.run(["/usr/bin/git", "merge", "--no-edit", "FETCH_HEAD"],
                   cwd=w.wd, capture_output=True, text=True)
    if git(w.wd, "status", "--porcelain"):
        (w.wd / "shared.txt").write_text("base\nmaster side\npr side\n")
        git(w.wd, "add", "shared.txt")
        git(w.wd, "commit", "-q", "-m", "merge base")
    with patch("pm_core.base_check.launch_impl") as launch:
        healed = gate(w)
    assert healed.decision == base_check.PROCEED
    launch.assert_not_called()
    assert base_check.open_return(pr(w)) is None
    assert pr(w)["base_return"]["resolved_at"]


def test_capped_return_resolves_from_the_previous_sessions_idle(w):
    """A capped return launches nothing, so it must not demand a *new* idle turn.

    ``needs_human`` clears ``awaiting``: no rework session is launched for the
    capped episode.  The idle evidence that matters is the last relaunch's —
    so the superseding record keeps ``launched_at``.  Without it the capped
    record falls back to its creation time, which always postdates the
    previous session's idle turn, and the TUI/CLI handoff waits forever even
    after a human reconciles the base.
    """
    from datetime import datetime

    with patch("pm_core.base_check.launch_impl", return_value=(True, "")):
        gate(w)
        for i in range(base_check.MAX_RETURNS_PER_BASE + 2):
            base_check.clear_return_awaiting(w.pm_dir, PR)
            commit(w.wd, f"f{i}.txt", "x\n", f"impl {i}")
            commit(w.repo, "shared.txt", f"base {i}\n", f"base {i}")
            completion(w, transcript_dir=w.tdir)
    ret = pr(w)["base_return"]
    assert ret.get("needs_human")
    assert ret.get("launched_at")          # carried across the supersede
    assert ret.get("awaiting") is None

    launched = datetime.fromisoformat(ret["launched_at"]).timestamp()
    capped_at = datetime.fromisoformat(ret["ts"]).timestamp()
    # The real hook event: the last rework session's idle turn, before the cap.
    idle_since = launched + (capped_at - launched) / 2
    assert launched < idle_since < capped_at

    # A human reconciles the current base by hand.
    subprocess.run(["/usr/bin/git", "fetch", str(w.repo), "master"],
                   cwd=w.wd, capture_output=True)
    subprocess.run(["/usr/bin/git", "merge", "--no-edit", "FETCH_HEAD"],
                   cwd=w.wd, capture_output=True, text=True)
    if git(w.wd, "status", "--porcelain"):
        (w.wd / "shared.txt").write_text("resolved\n")
        git(w.wd, "add", "shared.txt")
        git(w.wd, "commit", "-q", "-m", "merge base")

    # No new launch happens (the cap stopped automatic rework) ...
    with patch("pm_core.base_check.launch_impl") as launch:
        res = completion(w, idle_since=idle_since, transcript_dir=w.tdir)
    launch.assert_not_called()
    # ... and the handoff still advances on the reconciled base.
    assert res.complete, res.reason
    assert base_check.open_return(pr(w)) is None
    assert pr(w)["base_return"]["resolved_at"]


def test_share_impl_transcript_stores_an_absolute_target(w, monkeypatch):
    """A relatively-spelled transcript must not create a dangling link.

    ``pm pr start --transcript impl-<pr>.jsonl`` (or a relative symlink
    target) would otherwise be copied verbatim into another driver's
    directory, where it resolves against *that* directory and points nowhere.
    """
    import os

    other = w.pm_dir / "transcripts" / "run-b" / f"impl-{PR}.jsonl"
    other.parent.mkdir(parents=True)
    other.symlink_to("/nonexistent/old-session.jsonl")
    real = w.tdir / f"impl-{PR}.jsonl"
    real.write_text("{}")
    monkeypatch.chdir(w.tdir)

    base_check.share_impl_transcript(w.pm_dir, PR, f"impl-{PR}.jsonl")

    target = os.readlink(other)
    assert os.path.isabs(target)
    assert Path(target) == real


def test_pr_review_does_not_demote_a_pr_that_moved_on_during_the_gate(w):
    """A qa/sign_off transition inside the gate's fetch must win.

    The pre-review gate is a network round-trip between reading the status and
    writing ``in_review``; a PR that moved on to a later phase owns itself, so
    the write must be refused (exit 1, no window) rather than pulling it back
    and stranding the driver that is already running.
    """
    from click.testing import CliRunner
    from pm_core.cli import pr as pr_mod

    set_pr(w, status="in_progress")

    def _qa_during_gate(*_a, **_k):
        set_pr(w, status="qa")
        return base_check.GateResult(base_check.PROCEED, base_check.STAGE_REVIEW)

    runner = CliRunner()
    with patch.object(pr_mod, "state_root", return_value=w.pm_dir), \
         patch("pm_core.base_check.gate", side_effect=_qa_during_gate), \
         patch.object(pr_mod, "_launch_review_window") as window:
        result = runner.invoke(pr_mod.pr, ["review", PR])
    assert result.exit_code == 1, result.output
    window.assert_not_called()
    assert pr(w)["status"] == "qa"


def test_pr_review_iteration_does_not_start_beside_a_return_during_the_gate(w):
    """The in_review branch (review iterations >= 2) has the same race.

    ``review_loop`` launches iteration N on a PR whose status is already
    in_review, so this branch is the *normal* path for every later
    iteration.  A conflict return another driver records inside the gate's
    fetch must stop the reviewer just like it does on the first iteration.
    """
    from click.testing import CliRunner
    from pm_core.cli import pr as pr_mod

    set_pr(w, status="in_review")

    def _returned_during_gate(*_a, **_k):
        _return_during_gate(w, base_check.STAGE_REVIEW_ITERATION)
        return base_check.GateResult(base_check.PROCEED,
                                     base_check.STAGE_REVIEW_ITERATION)

    runner = CliRunner()
    with patch.object(pr_mod, "state_root", return_value=w.pm_dir), \
         patch("pm_core.base_check.gate", side_effect=_returned_during_gate), \
         patch.object(pr_mod, "_launch_review_window") as window:
        result = runner.invoke(pr_mod.pr, ["review", "--review-iteration", "2", PR])
    assert result.exit_code == 3, result.output
    window.assert_not_called()
    assert pr(w)["status"] == "in_progress"
    assert base_check.open_return(pr(w)) is not None


def test_pr_review_iteration_aborts_when_the_pr_is_removed_during_the_gate(w):
    """A PR removed inside the fetch must not get a reviewer on iteration N.

    The first-iteration path refuses an absent entry through its atomic
    ``in_review`` write; the already-``in_review`` branch writes no status, so
    its post-gate re-read has to classify "absent" the same way (as
    ``run_qa_sync``'s post-gate re-read already does) instead of letting the
    reviewer launch against a PR that no longer exists.
    """
    from click.testing import CliRunner
    from pm_core.cli import pr as pr_mod

    set_pr(w, status="in_review")

    def _removed_during_gate(*_a, **_k):
        def _drop(d):
            d["prs"] = [p for p in d.get("prs", []) if p.get("id") != PR]
        store.locked_update(w.pm_dir, _drop)
        return base_check.GateResult(base_check.PROCEED,
                                     base_check.STAGE_REVIEW_ITERATION)

    runner = CliRunner()
    with patch.object(pr_mod, "state_root", return_value=w.pm_dir), \
         patch("pm_core.base_check.gate", side_effect=_removed_during_gate), \
         patch.object(pr_mod, "_launch_review_window") as window:
        result = runner.invoke(pr_mod.pr, ["review", "--review-iteration", "2", PR])
    assert result.exit_code == 1, result.output
    window.assert_not_called()
    assert "removed from the project" in result.output
    assert store.get_pr(store.load(w.pm_dir), PR) is None


def test_resolve_and_status_repair_skip_the_write_when_nothing_changes(w):
    """The clean path must not rewrite project.yaml for a no-op.

    ``gate`` calls ``resolve_return`` on every clean review/QA gate and the
    TUI calls ``ensure_impl_status`` from the event loop.  Both used to take
    the project.yaml lock and rewrite the whole (large, git-tracked) file
    even when there was no open return to close / no raced status to repair.
    """
    set_pr(w, status="in_progress")
    with patch("pm_core.base_check.store.locked_update") as update:
        assert base_check.resolve_return(w.pm_dir, PR) is False
        base_check.ensure_impl_status(w.pm_dir, PR)
    update.assert_not_called()

    # With something to do, the update still runs (once each).
    set_pr(w, status="in_review",
           base_return={"verdict": base_check.VERDICT_BASE_CONFLICT,
                        "awaiting": "impl", "resolved_at": None})
    with patch("pm_core.base_check.store.locked_update") as update:
        base_check.ensure_impl_status(w.pm_dir, PR)
    assert update.call_count == 1
    # The mutation itself still happens when the update is not stubbed.
    base_check.ensure_impl_status(w.pm_dir, PR)
    assert pr(w)["status"] == "in_progress"
    with patch("pm_core.base_check.store.locked_update") as update:
        base_check.resolve_return(w.pm_dir, PR, reason="clean")
    assert update.call_count == 1
    assert base_check.resolve_return(w.pm_dir, PR, reason="clean") is True
    assert base_check.open_return(pr(w)) is None
    assert pr(w)["base_return"]["resolved_reason"] == "clean"
    # And once it is resolved, the next call is the cheap no-op again.
    with patch("pm_core.base_check.store.locked_update") as update:
        assert base_check.resolve_return(w.pm_dir, PR) is False
    update.assert_not_called()


def test_qa_run_sync_aborts_when_the_pr_is_removed_during_the_gate(w):
    """A PR removed inside the gate's fetch must not start QA.

    The pre-gate code aborts when the PR is not in the project data; the
    post-gate re-read used to treat ``None`` as "not merged/closed" and let a
    QA workdir/planner run against a PR that no longer exists.
    """
    from pm_core.qa_loop import QALoopState, run_qa_sync
    set_pr(w, status="qa")
    state = QALoopState(pr_id=PR)

    def _removed_during_gate(*_a, **_k):
        def _drop(d):
            d["prs"] = [p for p in d.get("prs", []) if p.get("id") != PR]
        store.locked_update(w.pm_dir, _drop)
        return base_check.GateResult(base_check.PROCEED, base_check.STAGE_QA)

    with patch("pm_core.qa_loop.get_pm_session", return_value="pm-test"), \
         patch("pm_core.base_check.gate", side_effect=_removed_during_gate), \
         patch("pm_core.qa_loop.create_qa_workdir") as mk:
        run_qa_sync(state, w.pm_dir, pr(w))
    mk.assert_not_called()
    assert state.running is False
    assert state.base_returned is False
    assert state.qa_workdir is None


def test_pr_review_skip_base_check_still_rechecks_for_a_return(w):
    """The auto-sequence path must not launch beside a return either.

    ``_launch_review_iteration`` runs the gate itself and passes
    ``--skip-base-check``; the in_review branch used to skip *both* the gate
    and the post-gate re-read, so a return another driver recorded after that
    gate's fetch was invisible and the reviewer launched beside the rework.
    """
    from click.testing import CliRunner
    from pm_core.cli import pr as pr_mod

    set_pr(w, status="in_review")
    clean = store.load(w.pm_dir)
    returned = store.load(w.pm_dir)
    store.get_pr(returned, PR)["base_return"] = {
        "verdict": base_check.VERDICT_BASE_CONFLICT, "head": "h",
        "base_sha": "b", "awaiting": "impl", "resolved_at": None}
    # The first load (``pr_review``'s own snapshot) is clean; every later one
    # (the post-gate re-read, and ``ensure_impl_status``'s pre-read) sees the
    # return another driver recorded meanwhile.
    seen = {"n": 0}

    def _load(_root, **_kw):
        seen["n"] += 1
        return clean if seen["n"] == 1 else returned

    runner = CliRunner()
    with patch.object(pr_mod, "state_root", return_value=w.pm_dir), \
         patch.object(pr_mod.store, "load", side_effect=_load), \
         patch.object(pr_mod, "_launch_review_window") as window:
        result = runner.invoke(pr_mod.pr, ["review", "--skip-base-check",
                                          "--review-iteration", "2", PR])
    window.assert_not_called()
    assert result.exit_code == 3
    assert pr(w)["status"] == "in_progress"
