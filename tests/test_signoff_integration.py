"""Sign-off owns integration and return routing (pr-ac10f03).

Real git + real project.yaml: the integration check, the verdict bound to
it, pm's earliest-step routing (conflicts -> implementation), the
``signoff_return`` record handed to the next step (and its clean-base
integration into the PR branch), and the ``awaiting`` flag that keeps a
restart / idle event from advancing a returned PR on an old session.
"""

from __future__ import annotations

import asyncio
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from unittest.mock import MagicMock, patch

import os
import pytest
from click.testing import CliRunner

from pm_core import integration, prompt_gen, signoff, store
from pm_core.signoff import (SIGNOFF_BLOCKED, SIGNOFF_IMPL, SIGNOFF_MERGE,
                             SIGNOFF_REQA, SIGNOFF_REVIEW)

PR = "pr-001"
BRANCH = "pm/pr-001"


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


def commit(cwd: Path, name: str, text: str, msg: str) -> str:
    (cwd / name).write_text(text)
    git(cwd, "add", name)
    git(cwd, "commit", "-q", "-m", msg)
    return git(cwd, "rev-parse", "HEAD")


@pytest.fixture
def w(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
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
    pm_dir = tmp_path / "pmstate"
    pm_dir.mkdir()
    store.save({"project": {"name": "p", "repo": str(repo),
                            "base_branch": "master", "backend": "local"},
                "prs": [{"id": PR, "title": "T", "branch": BRANCH,
                         "status": "sign_off", "workdir": str(wd)}],
                "plans": []}, pm_dir)
    croot = tmp_path / "captures"
    tdir = tmp_path / "tdir"
    tdir.mkdir()
    with patch("pm_core.paths.captures_root", return_value=croot):
        yield SimpleNamespace(repo=repo, wd=wd, pm_dir=pm_dir, head=head,
                              croot=croot, tdir=tdir)


def pr(w) -> dict:
    return store.get_pr(store.load(w.pm_dir), PR)


def step(w, verdict, *, launched=None, window="%1"):
    """One driver tick with *verdict* in the router transcript."""
    retired = []
    signoff.stamp_signoff_launch(signoff.signoff_transcript(w.tdir, PR),
                                 launched or git(w.wd, "rev-parse", "HEAD"))
    res = signoff.step_signoff(
        w.pm_dir, pr(w), session="s", tdir=w.tdir,
        read_verdict=lambda t, p: verdict,
        window_pane=lambda s, p: window,
        retire=lambda *a: retired.append(a))
    return res, retired


def write_report(w, verdict, reason=None):
    (w.croot / PR).mkdir(parents=True, exist_ok=True)
    extra = f'<meta name="pm-signoff-reason" content="{reason}">' if reason else ""
    (w.croot / PR / "report.html").write_text(
        f'<html><head><meta name="pm-signoff-verdict" content="{verdict}">'
        f'{extra}</head><body/></html>')


# --- verdict binding + earliest-step routing -------------------------------

def test_merge_verdict_binds_the_integration_check(w):
    rec = integration.check_integration(w.pm_dir, PR)
    res, _ = step(w, SIGNOFF_MERGE)
    assert res.hop == "ready_to_merge" and res.coerced is None
    bound = pr(w)["signoff"]["integration"]
    assert bound["base_sha"] == rec["base_sha"]
    assert bound["candidate_tree"] == rec["candidate_tree"]
    assert bound["status"] == integration.UP_TO_DATE
    assert signoff.merge_gate_refusal(pr(w), w.head, "master") is None


def test_tui_gate_checks_the_configured_base_branch(w):
    """The TUI auto-merge gate refuses what `pm pr merge` refuses: an
    approval for another base branch than the project merges into."""
    from pm_core.tui.review_loop_ui import _signoff_gate
    integration.check_integration(w.pm_dir, PR)
    step(w, SIGNOFF_MERGE)
    app = SimpleNamespace(_root=w.pm_dir, _data=None)
    assert _signoff_gate(app, PR)[1] is None

    def _retarget(d):
        d["project"]["base_branch"] = "develop"
    store.locked_update(w.pm_dir, _retarget)
    refusal = _signoff_gate(app, PR)[1]
    assert refusal and "'develop'" in refusal


def test_conflicted_integration_routes_merge_to_impl(w):
    commit(w.wd, "shared.txt", "pr\n", "pr edits shared")
    commit(w.repo, "shared.txt", "base\nmore\n", "base edits shared")
    rec = integration.check_integration(w.pm_dir, PR)
    head = git(w.wd, "rev-parse", "HEAD")
    write_report(w, SIGNOFF_MERGE)
    res, retired = step(w, SIGNOFF_MERGE)
    assert res.hop == "impl" and res.verdict == SIGNOFF_IMPL
    assert "conflicts" in res.coerced
    p = pr(w)
    assert p["status"] == "in_progress"
    ret = p["signoff_return"]
    assert ret["verdict"] == SIGNOFF_IMPL
    assert ret["original_verdict"] == SIGNOFF_MERGE
    assert ret["reviewed_head"] == head
    assert ret["integration"]["base_sha"] == rec["base_sha"]
    assert ret["integration"]["conflicts"] == ["shared.txt"]
    assert ret["awaiting"] == "impl"
    assert ret["applied"] is None                 # never a half-merge
    assert git(w.wd, "rev-parse", "HEAD") == head
    assert git(w.wd, "status", "--porcelain") == ""
    assert retired                                # run retired for re-entry


@pytest.mark.parametrize("verdict,hop", [(SIGNOFF_IMPL, "impl"),
                                         (SIGNOFF_REVIEW, "review")])
def test_hop_driver_holds_the_relaunch_claim(w, verdict, hop):
    """The hop writes the launch claim with the transition: a concurrent
    tick that sees ``awaiting`` right after it can't take the relaunch (and
    kill the hop driver's --fresh session)."""
    integration.check_integration(w.pm_dir, PR)
    res, _ = step(w, verdict)
    assert res.hop == hop
    assert pr(w)["signoff_return"]["launch_claim"]["hop"] == hop
    assert signoff.claim_return_launch(w.pm_dir, PR, hop) is False


@pytest.mark.parametrize("verdict,hop", [(SIGNOFF_IMPL, "impl"),
                                         (SIGNOFF_REVIEW, "review"),
                                         (SIGNOFF_REQA, "qa")])
def test_driver_on_a_pre_hop_snapshot_leaves_the_bounce_alone(w, verdict, hop):
    """The TUI and auto-sequence ticks act on the same verdict.  The bounce
    merges the clean base into the branch (HEAD moves) before it transitions,
    so a second driver holding a snapshot from before the hop must not read
    that as "HEAD moved" and retire + relaunch sign-off."""
    commit(w.repo, "other.txt", "other\n", "other PR merged")
    integration.check_integration(w.pm_dir, PR)
    snapshot = pr(w)                                # read before the hop
    res, _ = step(w, verdict)
    assert res.hop == hop
    ret = pr(w)["signoff_return"]
    retired = []
    late = signoff.step_signoff(
        w.pm_dir, snapshot, session="s", tdir=w.tdir,
        read_verdict=lambda t, p: verdict, window_pane=lambda s, p: None,
        retire=lambda *a: retired.append(a))
    assert late.action == "running"
    assert retired == []
    assert pr(w)["signoff_return"] == ret          # verdict/ts untouched
    assert git(w.wd, "rev-parse", "HEAD") == ret["applied"]["merge_sha"]


def test_reqa_hop_takes_no_launch_claim(w):
    integration.check_integration(w.pm_dir, PR)
    res, _ = step(w, SIGNOFF_REQA)
    assert res.hop == "qa"
    assert "launch_claim" not in pr(w)["signoff_return"]


@pytest.mark.parametrize("verdict", [SIGNOFF_REVIEW, SIGNOFF_REQA])
def test_conflict_coerces_review_and_reqa_to_impl(w, verdict):
    commit(w.wd, "shared.txt", "pr\n", "pr")
    commit(w.repo, "shared.txt", "other\n", "base")
    integration.check_integration(w.pm_dir, PR)
    res, _ = step(w, verdict)
    assert res.hop == "impl"
    assert pr(w)["signoff_return"]["original_verdict"] == verdict


def test_merge_without_integration_check_is_blocked(w):
    res, _ = step(w, SIGNOFF_MERGE)
    assert res.hop == "blocked" and res.verdict == SIGNOFF_BLOCKED
    assert "cannot approve" in res.coerced
    assert pr(w)["status"] == "sign_off"


def test_clean_moved_base_is_integrated_before_review(w):
    base = commit(w.repo, "other.txt", "other\n", "other PR merged")
    integration.check_integration(w.pm_dir, PR)
    write_report(w, SIGNOFF_REVIEW, reason="base reworked the parser")
    res, _ = step(w, SIGNOFF_REVIEW)
    assert res.hop == "review"
    p = pr(w)
    assert p["status"] == "in_review"
    ret = p["signoff_return"]
    assert ret["reason"] == "base reworked the parser"
    merged = ret["applied"]["merge_sha"]
    assert git(w.wd, "rev-parse", "HEAD") == merged
    parents = git(w.wd, "rev-list", "--parents", "-n1", merged).split()[1:]
    assert parents == [w.head, base]
    assert (w.wd / "other.txt").exists()
    assert git(w.wd, "rev-parse", "--abbrev-ref", "HEAD") == BRANCH
    # The base branch itself was never touched by sign-off.
    assert git(w.repo, "rev-parse", "master") == base


def test_dirty_workdir_is_not_integrated(w):
    commit(w.repo, "other.txt", "other\n", "other")
    integration.check_integration(w.pm_dir, PR)
    (w.wd / "feature.txt").write_text("uncommitted\n")
    res, _ = step(w, SIGNOFF_REQA)
    assert res.hop == "qa"
    ret = pr(w)["signoff_return"]
    assert ret["applied"] is None
    assert "uncommitted" in ret["apply_error"]
    assert (w.wd / "feature.txt").read_text() == "uncommitted\n"
    assert git(w.wd, "rev-parse", "HEAD") == w.head


def test_legacy_and_invalidated_records_relaunch(w):
    signoff.record_signoff_verdict(w.pm_dir, PR, SIGNOFF_MERGE, w.head,
                                   "manual")
    res, retired = step(w, None)
    assert (res.action, res.stale) == ("launch", True)
    assert res.reason == "legacy HEAD-only approval"
    assert retired and "signoff" not in pr(w)

    rec = integration.check_integration(w.pm_dir, PR)
    signoff.record_signoff_verdict(w.pm_dir, PR, SIGNOFF_MERGE, w.head,
                                   "auto-sequence",
                                   integration=integration.binding(rec))
    signoff.invalidate_signoff(w.pm_dir, PR, "master moved since sign-off")
    assert signoff.latest_signoff_verdict(pr(w)) is None   # display: spinner
    res, _ = step(w, None)
    assert res.stale and res.reason == "master moved since sign-off"


def test_next_signoff_decision_resolves_the_return(w):
    commit(w.wd, "shared.txt", "pr\n", "pr")
    commit(w.repo, "shared.txt", "other\n", "base")
    integration.check_integration(w.pm_dir, PR)
    step(w, SIGNOFF_IMPL)
    p = pr(w)
    assert signoff.return_awaiting(p) == "impl"
    assert "Returned from sign-off" in signoff.format_signoff_return(p)
    signoff.clear_return_awaiting(w.pm_dir, PR, "impl")
    assert signoff.return_awaiting(pr(w)) is None
    assert signoff.open_return(pr(w))                 # episode still open

    def _back(d):
        store.get_pr(d, PR)["status"] = "sign_off"
    store.locked_update(w.pm_dir, _back)
    signoff.record_signoff_verdict(w.pm_dir, PR, SIGNOFF_BLOCKED, w.head,
                                   "manual")
    assert signoff.open_return(pr(w)) is None
    assert signoff.format_signoff_return(pr(w)) == ""


# --- prompts + display -----------------------------------------------------

def test_next_agent_prompt_carries_the_return_context(w):
    commit(w.wd, "shared.txt", "pr\n", "pr")
    commit(w.repo, "shared.txt", "other\n", "base")
    integration.check_integration(w.pm_dir, PR)
    write_report(w, SIGNOFF_IMPL, reason="master reworked shared.txt")
    step(w, SIGNOFF_IMPL)
    data = store.load(w.pm_dir)
    with patch("pm_core.prompt_gen.store.find_project_root",
               side_effect=FileNotFoundError):
        impl = prompt_gen.generate_prompt(data, PR)
        review = prompt_gen.generate_review_prompt(data, PR)
    for text in (impl, review):
        assert "## Returned from sign-off" in text
        assert "master reworked shared.txt" in text
        assert "`shared.txt`" in text
    assert "Never push or merge into the base branch" in impl


def test_signoff_prompt_has_integration_section(w):
    commit(w.repo, "other.txt", "other\n", "other")
    integration.check_integration(w.pm_dir, PR)
    data = store.load(w.pm_dir)
    with patch("pm_core.prompt_gen.store.find_project_root",
               side_effect=FileNotFoundError):
        text = prompt_gen.generate_signoff_prompt(data, PR)
    assert "## Integration with the latest base" in text
    assert "merges cleanly with master@" in text
    assert f"pm pr signoff integrate {PR}" in text
    assert 'name="pm-signoff-base"' in text
    assert "Never merge the base into the branch" in text


def test_merge_prompt_is_recovery_only():
    data = {"project": {"repo": "/r", "base_branch": "master"},
            "prs": [{"id": PR, "title": "T", "branch": BRANCH}]}
    with patch("pm_core.prompt_gen.store.find_project_root",
               side_effect=FileNotFoundError):
        text = prompt_gen.generate_merge_prompt(data, PR, "ff failed")
    assert "already-completed merge" in text
    assert "Do NOT push" in text
    assert "gh pr merge" in text


def test_list_line_shows_return_marker():
    from pm_core.cli.helpers import format_pr_line
    p = {"id": PR, "title": "T", "status": "in_progress",
         "signoff_return": {"verdict": SIGNOFF_IMPL, "awaiting": None}}
    assert signoff.SIGNOFF_VERDICT_ICONS[SIGNOFF_IMPL] in format_pr_line(p)
    p["signoff_return"]["resolved_at"] = "now"
    assert signoff.SIGNOFF_VERDICT_ICONS[SIGNOFF_IMPL] not in format_pr_line(p)


# --- restart-safe resumption (CLI auto-sequence) --------------------------

def _seq(tmp_path, pr_entry, **patches):
    from pm_core.cli.pr import pr_auto_sequence
    data = {"project": {"active_pr": PR}, "prs": [pr_entry]}
    with patch("pm_core.cli.pr.state_root", return_value=tmp_path), \
         patch("pm_core.cli.pr.store.load", return_value=data), \
         patch("pm_core.cli.pr._get_pm_session", return_value="pm-test"), \
         patch("pm_core.cli.pr.pr_start") as start, \
         patch("pm_core.cli.pr.pr_review") as review, \
         patch("pm_core.cli.pr._launch_qa_detached") as qa, \
         patch("pm_core.cli.pr.trigger_tui_refresh"):
        start.callback = MagicMock()
        review.callback = MagicMock()
        ctx_patches = [patch(k, **v) for k, v in patches.items()]
        for c in ctx_patches:
            c.start()
        try:
            result = CliRunner().invoke(pr_auto_sequence, [PR])
        finally:
            for c in ctx_patches:
                c.stop()
    return result, start, review, qa


def _returned(status, hop, **extra):
    return {"id": PR, "title": "T", "branch": BRANCH, "status": status,
            "workdir": "/wd",
            "signoff_return": {"verdict": "X", "hop": hop, "awaiting": hop,
                               "ts": "2099-01-01T00:00:00+00:00", **extra}}


def test_cli_relaunches_impl_instead_of_advancing_idle_session(tmp_path):
    result, start, review, _ = _seq(
        tmp_path, _returned("in_progress", "impl"),
        **{"pm_core.cli.pr._check_impl_idle": {"return_value": (True, False)}})
    assert result.exit_code == 0, result.output
    assert "sign_off: returning to impl (relaunched)" in result.output
    assert start.call_count == 1 or "relaunched" in result.output
    review.assert_not_called()


def test_cli_relaunches_review_instead_of_adopting_old_pass(tmp_path):
    result, _, _, qa = _seq(
        tmp_path, _returned("in_review", "review"),
        **{"pm_core.cli.pr._check_review_verdict": {"return_value": ("PASS", 3)}})
    assert result.exit_code == 0, result.output
    assert "returning to review (iteration 4)" in result.output
    qa.assert_not_called()


def test_cli_ignores_qa_status_older_than_the_return(tmp_path):
    old = tmp_path / "qa_status.json"
    old.write_text("{}")
    result, _, _, qa = _seq(
        tmp_path, _returned("qa", "qa"),
        **{"pm_core.cli.pr._qa_status_for": {"return_value": ("PASS", old)},
           "pm_core.cli.pr.tmux_mod.find_window_by_name": {"return_value": None}})
    assert result.exit_code == 0, result.output
    assert "advanced: sign_off" not in result.output
    assert "running: qa (launched)" in result.output
    qa.assert_called_once()


def test_cli_qa_status_older_than_an_impl_return_does_not_advance(tmp_path):
    """Rework after an IMPL return must be re-verified, not signed off on
    the QA PASS sign-off already judged."""
    old = tmp_path / "qa_status.json"
    old.write_text("{}")
    result, _, _, qa = _seq(
        tmp_path, _returned("qa", "impl", awaiting=None),
        **{"pm_core.cli.pr._qa_status_for": {"return_value": ("PASS", old)},
           "pm_core.cli.pr.tmux_mod.find_window_by_name": {"return_value": None}})
    assert result.exit_code == 0, result.output
    assert "advanced: sign_off" not in result.output
    qa.assert_called_once()


def _qa_run_record(home, started_at, **extra):
    import json
    qa_wd = home / ".pm" / "workdirs" / "qa" / f"{PR}-{int(started_at)}"
    qa_wd.mkdir(parents=True)
    (qa_wd / "qa_run.json").write_text(json.dumps(
        {"pr_id": PR, "loop_id": "x", "started_at": started_at, **extra}))


@pytest.mark.parametrize("run_after_return, window, record, launched", [
    (True, "@7", {}, False), (True, "@7", {"session_tag": "test"}, False),
    (False, "@7", {}, True), (True, None, {}, True),
    (True, "@7", {"session_tag": "other-clone"}, True),
    (True, "@7", {"pr_id": f"{PR}x"}, True)])
def test_cli_qa_return_whose_rerun_started_is_left_to_it(
        tmp_path, monkeypatch, run_after_return, window, record, launched):
    """S87: the TUI started the REQA re-run while project.yaml was busy and
    its clear of ``awaiting`` is still pending.  A tick that got the lock at
    the release must not launch a second QA driver over that run; a qa
    window from a run that started before the return (the judged run) is
    still relaunched over, and so is a newer run record without a window
    (that run ended or died before opening one), or one another clone (or
    another PR) launched: nothing in this clone drives the re-run."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    ts = "2026-10-27T04:07:14+00:00"
    start = signoff.parse_ts(ts).timestamp() + (15 if run_after_return
                                                 else -120)
    _qa_run_record(tmp_path / "home", start, **record)
    claim = MagicMock(return_value=True)
    result, _, _, qa = _seq(
        tmp_path, _returned("qa", "qa", ts=ts),
        **{"pm_core.cli.pr._qa_status_for": {"return_value": (None, None)},
           "pm_core.cli.pr.tmux_mod.find_window_by_name":
               {"return_value": window},
           "pm_core.qa_loop.get_pm_session": {"return_value": "pm-test"},
           "pm_core.cli.pr._check_qa_launch": {"return_value": None},
           "pm_core.signoff.claim_return_launch": {"new": claim}})
    assert result.exit_code == 0, result.output
    if launched:
        assert result.output.strip() == "running: qa (launched)"
        qa.assert_called_once()
    else:
        assert result.output.strip() == "running: qa"
        qa.assert_not_called()
        claim.assert_not_called()


@pytest.mark.parametrize("awaiting, run_age, after_return, record, launched", [
    (None, 3, True, {}, False), ("qa", 3, True, {}, False),
    (None, 3, False, {}, True), ("qa", 3, False, {}, True),
    (None, 400, True, {}, True), ("qa", 400, True, {}, True),
    (None, 3, True, {"session_tag": "other-clone"}, True)])
def test_cli_qa_return_whose_rerun_is_still_starting_is_left_to_it(
        tmp_path, monkeypatch, awaiting, run_age, after_return, record,
        launched):
    """S91: the TUI's REQA hop started the re-run (no launch claim) and, with
    the lock free, cleared ``awaiting`` at once; for seconds its run kills
    the judged run's windows and plans before its own qa window exists.  A
    tick in that gap must not launch qa-run-bg (two ticks 2 s apart each
    did).  A run record from before the return, older than a claim's
    expiry, or another clone's still leaves the tick to launch."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    now = time.time()
    start = now - run_age
    ret = start + (-1 if after_return else 1)
    ts = datetime.fromtimestamp(ret, timezone.utc).isoformat()
    _qa_run_record(tmp_path / "home", start, **record)
    claim = MagicMock(return_value=True)
    entry = _returned("qa", "qa", ts=ts)
    entry["signoff_return"]["awaiting"] = awaiting
    result, _, _, qa = _seq(
        tmp_path, entry,
        **{"pm_core.cli.pr._qa_status_for": {"return_value": (None, None)},
           "pm_core.cli.pr.tmux_mod.find_window_by_name":
               {"return_value": None},
           "pm_core.qa_loop.get_pm_session": {"return_value": "pm-test"},
           "pm_core.cli.pr._check_qa_launch": {"return_value": None},
           "pm_core.signoff.claim_return_launch": {"new": claim}})
    assert result.exit_code == 0, result.output
    if launched:
        assert result.output.strip() == "running: qa (launched)"
        qa.assert_called_once()
    else:
        assert result.output.strip() == "running: qa"
        qa.assert_not_called()
        claim.assert_not_called()


@pytest.mark.parametrize("awaiting", ["qa", None])
@pytest.mark.parametrize("owner_alive, launched", [(True, False),
                                                    (False, True)])
def test_cli_qa_run_whose_window_was_closed_is_left_to_its_driver(
        tmp_path, monkeypatch, awaiting, owner_alive, launched):
    """S89: the user closed the re-run's qa window while its TUI driver was
    still running.  A tick must not start a second driver while the run's
    snapshot owner lives (awaiting still pending, or already cleared), and
    still relaunches once that driver is gone."""
    import json
    from pm_core import qa_loop
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    # Older than a launch claim's expiry: only the live owner counts.
    ret = time.time() - 600
    ts = datetime.fromtimestamp(ret, timezone.utc).isoformat()
    start = ret + 22
    _qa_run_record(tmp_path / "home", start)
    qa_wd = tmp_path / "home" / ".pm" / "workdirs" / "qa" / f"{PR}-{int(start)}"
    owner = os.getppid() if owner_alive else 2 ** 22 + 12345
    (qa_wd / "qa_resume.json").write_text(json.dumps(
        {"pr_id": PR, "loop_id": "x", "owner_pid": owner,
         "owner_start": qa_loop._proc_start_time(owner)}))
    result, _, _, qa = _seq(
        tmp_path, _returned("qa", "qa", ts=ts, awaiting=awaiting),
        **{"pm_core.cli.pr._qa_status_for": {"return_value": (None, None)},
           "pm_core.cli.pr.tmux_mod.find_window_by_name":
               {"return_value": None},
           "pm_core.qa_loop.get_pm_session": {"return_value": "pm-test"},
           "pm_core.cli.pr._check_qa_launch": {"return_value": None},
           "pm_core.signoff.claim_return_launch":
               {"new": MagicMock(return_value=True)}})
    assert result.exit_code == 0, result.output
    if launched:
        assert result.output.strip() == "running: qa (launched)"
        qa.assert_called_once()
    else:
        assert result.output.strip() == "running: qa"
        qa.assert_not_called()


def _review_transcripts(tmp_path, *iters):
    tdir = tmp_path / "transcripts" / "auto-sequence" / PR
    tdir.mkdir(parents=True)
    for i in iters:
        (tdir / f"review-{PR}-i{i}.jsonl").write_text("")
    return tdir


def test_cli_impl_rework_review_continues_iteration_numbering(tmp_path):
    """The idle rework advances to review as the NEXT iteration: the next
    tick reads the highest one, which must be the rework's review."""
    _review_transcripts(tmp_path, 1, 2, 3)
    result, _, review, _ = _seq(
        tmp_path, _returned("in_progress", "impl", awaiting=None),
        **{"pm_core.cli.pr._check_impl_idle": {"return_value": (True, False)}})
    assert result.exit_code == 0, result.output
    assert "advanced: in_review" in result.output
    kwargs = review.call_args.kwargs
    assert kwargs["review_iteration"] == 4
    assert kwargs["transcript"].endswith(f"review-{PR}-i4.jsonl")
    # The open window reviewed the pre-return code: replace, don't adopt.
    assert kwargs["fresh"] is True


def test_cli_impl_rework_review_replaces_window_of_tui_reviews(tmp_path):
    """QA S77: the TUI ran the earlier reviews (its own transcript dir), so
    this tick's dir has no iteration.  The rework's review still must not
    adopt the pre-return review window: the tick switched to it, whose
    verdict predates the return, and the PR sat in_review with no review."""
    result, _, review, _ = _seq(
        tmp_path, _returned("in_progress", "impl", awaiting=None),
        **{"pm_core.cli.pr._check_impl_idle": {"return_value": (True, False)}})
    assert result.exit_code == 0, result.output
    assert "advanced: in_review" in result.output
    kwargs = review.call_args.kwargs
    assert kwargs["review_iteration"] == 1
    assert kwargs["fresh"] is True

def test_cli_first_review_advance_keeps_existing_window(tmp_path):
    result, _, review, _ = _seq(
        tmp_path, {"id": PR, "title": "T", "branch": BRANCH,
                   "status": "in_progress", "workdir": "/wd"},
        **{"pm_core.cli.pr._check_impl_idle": {"return_value": (True, False)}})
    assert result.exit_code == 0, result.output
    kwargs = review.call_args.kwargs
    assert kwargs["review_iteration"] == 1
    assert kwargs["fresh"] is False


def test_cli_ignores_review_pass_older_than_an_impl_return(tmp_path):
    _review_transcripts(tmp_path, 3)
    result, _, _, qa = _seq(
        tmp_path, _returned("in_review", "impl", awaiting=None),
        **{"pm_core.cli.pr._check_review_verdict": {"return_value": ("PASS", 3)},
           "pm_core.cli.pr._review_window_pane": {"return_value": "%1"}})
    assert result.exit_code == 0, result.output
    assert "advanced: qa" not in result.output
    assert "running: review" in result.output
    qa.assert_not_called()


# --- restart-safe resumption (TUI scheduler) -------------------------------

def test_tui_scheduler_relaunches_awaiting_impl_fresh(tmp_path):
    from pm_core import autostart_state as st
    from pm_core.tui import auto_start
    from tests.test_autostart_multi_target import FakeApp
    p = _returned("in_progress", "impl")
    p["depends_on"] = []
    app = FakeApp([p, {"id": "pr-002", "title": "U", "branch": "b2",
                       "status": "in_progress", "depends_on": []}],
                  root=tmp_path)
    app._auto_start = True
    app._auto_start_targets = {PR: st.make_target_record("t"),
                               "pr-002": st.make_target_record("t")}
    app._auto_start_run_id = "run"
    store.save(app._data, tmp_path)
    calls = []

    async def fake_start(_app, pr_id, fresh=False):
        calls.append((pr_id, fresh))

    with patch.object(auto_start, "_start_pr_quiet", fake_start), \
         patch("pm_core.tui.watcher_ui.is_running", return_value=False), \
         patch("pm_core.runtime_state.get_action_state", return_value={}), \
         patch("pm_core.tui.signoff_ui.advance_all"):
        asyncio.run(auto_start.check_and_start(app))
    assert sorted(calls) == [(PR, True), ("pr-002", False)]


def test_tui_scheduler_does_not_refresh_a_rework_launched_mid_pass(tmp_path):
    """The pass's PR snapshot predates its awaits: a rework launch that
    cleared ``awaiting`` meanwhile must not be killed by a second --fresh."""
    from pm_core import autostart_state as st
    from pm_core.tui import auto_start
    from tests.test_autostart_multi_target import FakeApp
    p = _returned("in_progress", "impl")
    p["depends_on"] = []
    app = FakeApp([dict(p)], root=tmp_path)
    app._auto_start = True
    app._auto_start_targets = {PR: st.make_target_record("t")}
    app._auto_start_run_id = "run"
    disk = {"project": app._data["project"],
            "prs": [dict(p, signoff_return=dict(p["signoff_return"],
                                                awaiting=None))]}
    store.save(disk, tmp_path)                  # the relaunch already ran
    calls = []

    async def fake_start(_app, pr_id, fresh=False):
        calls.append((pr_id, fresh))

    with patch.object(auto_start, "_start_pr_quiet", fake_start), \
         patch("pm_core.tui.watcher_ui.is_running", return_value=False), \
         patch("pm_core.runtime_state.get_action_state", return_value={}), \
         patch("pm_core.tui.signoff_ui.advance_all"):
        asyncio.run(auto_start.check_and_start(app))
    assert calls == [(PR, False)]


def test_tui_qa_pass_not_handed_to_signoff_while_reqa_awaits(tmp_path):
    from pm_core import autostart_state as st
    from pm_core.tui import auto_start, signoff_ui
    from tests.test_autostart_multi_target import FakeApp
    p = _returned("qa", "qa")
    p["depends_on"] = []
    app = FakeApp([p], root=tmp_path)
    store.save({"project": app._data["project"], "prs": [p]}, tmp_path)
    app._auto_start = True
    app._auto_start_targets = {PR: st.make_target_record("t")}
    app._auto_start_run_id = "run"
    with patch.object(auto_start, "recorded_qa_verdict", return_value="PASS"), \
         patch.object(signoff_ui, "start_signoff") as ss, \
         patch("pm_core.tui.qa_loop_ui.start_qa") as sq:
        signoff_ui.advance_all(app, [p])
        auto_start._auto_start_qa_loops(app, [p])
    ss.assert_not_called()
    sq.assert_called_once()                     # the REQA run starts instead


def test_verdict_from_run_launched_on_another_base_is_not_bound(w):
    """The launch stamp names the base its check used; a re-recorded check
    against another base mid-run makes the verdict stale (no rebinding)."""
    integration.check_integration(w.pm_dir, PR)
    launched_base = pr(w)["integration"]["base_sha"]
    signoff.stamp_signoff_launch(signoff.signoff_transcript(w.tdir, PR),
                                 w.head, launched_base)
    commit(w.repo, "other.txt", "o\n", "base moved mid-run")
    integration.check_integration(w.pm_dir, PR)       # e.g. --record
    res = signoff.step_signoff(
        w.pm_dir, pr(w), session="s", tdir=w.tdir,
        read_verdict=lambda t, p: SIGNOFF_MERGE,
        window_pane=lambda s, p: "%1", retire=lambda *a: None)
    assert res.action == "launch" and res.stale
    assert res.reason == "integration re-checked during the run"
    assert "signoff" not in pr(w)


def test_integrate_cli_is_read_only_by_default(w):
    from pm_core.cli.pr import pr_signoff_integrate
    commit(w.repo, "other.txt", "o\n", "base moved")
    with patch("pm_core.cli.pr.state_root", return_value=w.pm_dir), \
         patch("pm_core.cli.pr.trigger_tui_refresh"):
        r = CliRunner().invoke(pr_signoff_integrate, [PR])
        assert r.exit_code == 0, r.output
        assert "merges cleanly with master@" in r.output
        assert "integration" not in pr(w)            # nothing recorded
        r = CliRunner().invoke(pr_signoff_integrate, [PR, "--record"])
        assert r.exit_code == 0, r.output
        assert pr(w)["integration"]["status"] == integration.CLEAN
        r = CliRunner().invoke(pr_signoff_integrate, [PR, "--apply"])
        assert r.exit_code == 0, r.output
        assert "into the PR branch" in r.output
    assert (w.wd / "other.txt").exists()
    assert git(w.wd, "rev-parse", "--abbrev-ref", "HEAD") == BRANCH


# --- review-loop additions -------------------------------------------------

def test_stale_report_reason_is_not_reused(w):
    """A report left by an earlier run (other HEAD) doesn't supply the reason."""
    commit(w.wd, "shared.txt", "pr\n", "pr")
    commit(w.repo, "shared.txt", "other\n", "base")
    integration.check_integration(w.pm_dir, PR)
    (w.croot / PR).mkdir(parents=True, exist_ok=True)
    (w.croot / PR / "report.html").write_text(
        '<html><head><meta name="pm-signoff-verdict" content="SIGNOFF_IMPL">'
        '<meta name="pm-signoff-head" content="0123456789abcdef">'
        '<meta name="pm-signoff-reason" content="old run reason">'
        '</head><body/></html>')
    step(w, SIGNOFF_IMPL)
    ret = pr(w)["signoff_return"]
    assert ret["reason"] != "old run reason"
    assert ret["reason"]          # falls back to the coerced/default reason


def test_report_without_verdict_tag_supplies_no_reason(w):
    (w.croot / PR).mkdir(parents=True, exist_ok=True)
    (w.croot / PR / "report.html").write_text(
        '<html><head><meta name="pm-signoff-reason" content="untagged">'
        '</head><body/></html>')
    integration.check_integration(w.pm_dir, PR)
    step(w, SIGNOFF_REVIEW)
    assert pr(w)["signoff_return"]["reason"] == "see report.html and PR notes"


def _completed(rc, out="", err=""):
    return subprocess.CompletedProcess([], rc, out, err)


def test_merge_tree_output_parsing():
    """The git >= 2.38 in-memory path (not exercised by this git)."""
    with patch.object(integration, "_git",
                      return_value=_completed(0, "abc123\n")):
        assert integration._merge_tree("wd", "h", "b") == ("abc123", [], None)
    out = "def456\na.txt\nb.txt\na.txt\n"
    with patch.object(integration, "_git", return_value=_completed(1, out)):
        assert integration._merge_tree("wd", "h", "b") == (
            None, ["a.txt", "b.txt"], None)
    with patch.object(integration, "_git",
                      return_value=_completed(128, "", "fatal: bad")):
        tree, conflicts, err = integration._merge_tree("wd", "h", "b")
        assert (tree, conflicts) == (None, []) and "fatal: bad" in err


def test_compute_candidate_uses_merge_tree_on_new_git(w):
    commit(w.repo, "other.txt", "other\n", "other")
    base_sha, err = integration.fetch_base(str(w.wd), str(w.repo), "master")
    assert err is None
    with patch.object(integration, "_git_version", return_value=(2, 45)), \
            patch.object(integration, "_merge_tree",
                         return_value=("cafe", [], None)) as mt:
        out = integration.compute_candidate(str(w.wd), w.head, base_sha)
    mt.assert_called_once()
    assert (out["status"], out["candidate_tree"]) == (integration.CLEAN, "cafe")


def test_merge_refuses_clearly_without_workdir(w):
    from pm_core.cli import cli
    rec = integration.check_integration(w.pm_dir, PR)
    signoff.record_signoff_verdict(w.pm_dir, PR, SIGNOFF_MERGE, w.head,
                                   "auto-sequence",
                                   integration=integration.binding(rec))

    def _gone(d):
        store.get_pr(d, PR)["workdir"] = str(w.wd) + "-missing"
    store.locked_update(w.pm_dir, _gone)
    with patch("pm_core.cli.pr.state_root", return_value=w.pm_dir), \
            patch("pm_core.cli.helpers.state_root", return_value=w.pm_dir):
        r = CliRunner().invoke(cli, ["pr", "merge", "--no-resolve-window", PR])
    assert r.exit_code == 1
    assert "workdir not found" in r.output
    assert "stale" not in r.output


def test_head_equal_to_base_is_in_base_not_mergeable(w):
    """A PR with no commits of its own has nothing to publish: without
    this, commit-tree would drop the duplicate parent and publish an empty
    single-parent commit onto the base."""
    base_sha, err = integration.fetch_base(str(w.wd), str(w.repo), "master")
    assert err is None
    out = integration.compute_candidate(str(w.wd), base_sha, base_sha)
    assert out["status"] == integration.IN_BASE
    assert out["candidate_tree"] is None


def test_recheck_from_own_checkout_resolves_remote_target(w, monkeypatch):
    """In a container the recorded host workdir is absent: the re-check uses
    the current checkout of the PR branch and takes the target from its
    origin (remote backends), instead of failing with no target."""
    data = store.load(w.pm_dir)
    data["project"]["backend"] = "vanilla"
    p = store.get_pr(data, PR)
    p["workdir"] = str(w.wd.parent / "host-only-path")
    monkeypatch.chdir(w.wd)
    rec = integration.run_check(data, p, w.pm_dir)
    assert rec["status"] == integration.UP_TO_DATE, rec
    assert rec["target_repo"] == str(w.repo)
    assert rec["head"] == w.head


def test_local_target_from_pr_workdir_is_the_main_repo(w):
    """Run from a PR workdir (its own pm/ state), the local target is the
    main repo the workdir was cloned from: the clone's own master is stale,
    so checking against it reports "up to date" after master moved."""
    from pm_core.paths import workdirs_base
    wd = workdirs_base() / "p-12345678" / "pm-pr-001"
    wd.parent.mkdir(parents=True)
    git(w.tdir, "clone", "-q", str(w.repo), str(wd))
    git(wd, "checkout", "-q", "-b", BRANCH)
    commit(wd, "feature.txt", "feature\n", "feature")
    (wd / "pm").mkdir()
    data = store.load(w.pm_dir)
    moved = commit(w.repo, "other.txt", "o\n", "base moved")
    assert integration.target_for(data, {}, wd / "pm") == (str(w.repo), "master")
    p = dict(store.get_pr(data, PR), workdir=str(wd))
    rec = integration.run_check(data, p, wd / "pm")
    assert rec["base_sha"] == moved, rec
    assert rec["status"] == integration.CLEAN, rec


def test_local_target_from_pr_workdir_with_unreachable_origin_errors(w):
    """A PR workdir whose origin is unreachable reports a fetch error naming
    the origin, not "up to date" against the clone's own stale master."""
    from pm_core.paths import workdirs_base
    wd = workdirs_base() / "p-12345678" / "pm-pr-001"
    wd.parent.mkdir(parents=True)
    git(w.tdir, "clone", "-q", str(w.repo), str(wd))
    git(wd, "checkout", "-q", "-b", BRANCH)
    commit(wd, "feature.txt", "feature\n", "feature")
    (wd / "pm").mkdir()
    data = store.load(w.pm_dir)
    commit(w.repo, "other.txt", "o\n", "base moved")
    git(wd, "remote", "set-url", "origin", "/nonexistent/repo")
    head = git(wd, "rev-parse", "HEAD")
    p = dict(store.get_pr(data, PR), workdir=str(wd))
    rec = integration.run_check(data, p, wd / "pm")
    assert rec["status"] == integration.ERROR, rec
    assert rec["target_repo"] == "/nonexistent/repo", rec
    assert "/nonexistent/repo" in rec["error"], rec
    assert rec["base_sha"] is None, rec
    assert git(wd, "rev-parse", "HEAD") == head


def test_concurrent_checks_do_not_race_on_the_base_ref(w):
    """Two checks on one workdir while the base moves: each fetch pins its
    own ref, so neither fails with "cannot lock ref" (compare-and-swap of
    the shared BASE_REF) and no per-call ref is left behind."""
    import threading
    for n in range(8):
        tip = commit(w.repo, "shared.txt", f"base {n}\n", f"base {n}")
        barrier = threading.Barrier(3)
        results = []

        def run():
            barrier.wait()
            results.append(integration.fetch_base(str(w.wd), str(w.repo), "master"))

        threads = [threading.Thread(target=run) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert results == [(tip, None)] * 3, results
    refs = git(w.wd, "for-each-ref", "--format=%(refname)", "refs/pm/").split()
    assert refs == [integration.BASE_REF]

def _check_in_child(wd, repo, head):
    with patch.object(integration, "_git_version", return_value=(2, 34)):
        base, err = integration.fetch_base(wd, repo, "master")
        cand = (integration.compute_candidate(wd, head, base)
                if base else {"status": err})
    return base, cand["status"], cand.get("error")


def test_concurrent_checks_do_not_race_on_candidate_worktrees(w):
    """git < 2.38: each check adds/removes a temp worktree in the shared
    repo.  Concurrent checks (separate processes, as CLI calls are) must
    not collide on its admin dir, prune each other's half-created
    worktree, or fail a fetch that walks worktree HEADs ("bad object
    worktrees/candidate1/HEAD")."""
    import multiprocessing
    ctx = multiprocessing.get_context("fork")
    with ctx.Pool(10) as pool:
        for n in range(5):
            tip = commit(w.repo, f"base{n}.txt", "x\n", f"base {n}")
            results = pool.starmap(_check_in_child,
                                   [(str(w.wd), str(w.repo), w.head)] * 10)
            assert results == [(tip, integration.CLEAN, None)] * 10, results
    assert len(git(w.wd, "worktree", "list").splitlines()) == 1


# --- one launcher per return (concurrent drivers) -------------------------

def test_claim_return_launch_has_one_winner_until_cleared(tmp_path):
    store.save({"project": {"name": "t", "repo": str(tmp_path),
                            "base_branch": "master", "backend": "local"},
                "prs": [_returned("in_review", "review")]}, tmp_path)
    assert signoff.claim_return_launch(tmp_path, PR, "review") is True
    assert signoff.claim_return_launch(tmp_path, PR, "review") is False
    assert signoff.claim_return_launch(tmp_path, PR, "qa") is False
    ret = store.get_pr(store.load(tmp_path), PR)["signoff_return"]
    assert ret["awaiting"] == "review"          # set until the window opens
    signoff.clear_return_awaiting(tmp_path, PR, "review")
    ret = store.get_pr(store.load(tmp_path), PR)["signoff_return"]
    assert ret["awaiting"] is None and "launch_claim" not in ret
    assert signoff.claim_return_launch(tmp_path, PR, "review") is False


@pytest.mark.parametrize("status,hop", [("in_review", "review"),
                                        ("in_progress", "impl")])
def test_clear_waits_out_a_lock_holder_past_its_timeout(tmp_path, status, hop):
    """QA S77: project.yaml's lock was held past the 2 s timeout as the
    relaunched session opened.  The clear gave up with a warning, so
    ``awaiting`` and the hop's claim outlived that session, and the first
    tick after the claim expired launched a second --fresh session."""
    now = datetime.now(timezone.utc).isoformat()
    store.save({"project": {"name": "t", "repo": str(tmp_path),
                            "base_branch": "master", "backend": "local"},
                "prs": [_returned(status, hop,
                                  launch_claim={"hop": hop, "at": now})]},
               tmp_path)
    held = threading.Event()

    def hold(seconds):
        with store._lock(tmp_path):
            held.set()
            time.sleep(seconds)

    # A caller that must not wait still gets False at once (it retries).
    t = threading.Thread(target=hold, args=(0.3,))
    t.start()
    held.wait()
    t0 = time.monotonic()
    assert signoff.clear_return_awaiting(
        tmp_path, PR, hop, timeout=store.NO_WAIT) is False
    assert time.monotonic() - t0 < 0.25
    t.join()
    assert signoff.return_awaiting(store.get_pr(store.load(tmp_path), PR)) == hop

    # A caller whose session did not open (the TUI's start_qa, on its main
    # thread) still gives up after its timeout, leaving ``awaiting`` set.
    held.clear()
    t = threading.Thread(target=hold, args=(0.6,))
    t.start()
    held.wait()
    t0 = time.monotonic()
    assert signoff.clear_return_awaiting(tmp_path, PR, hop, timeout=0.2) is None
    assert time.monotonic() - t0 < 0.5
    t.join()
    assert signoff.return_awaiting(store.get_pr(store.load(tmp_path), PR)) == hop

    held.clear()
    t = threading.Thread(target=hold, args=(0.6,))
    t.start()
    held.wait()
    assert signoff.clear_return_awaiting(tmp_path, PR, hop, timeout=0.2,
                                         session_opened=True) is True
    t.join()
    ret = store.get_pr(store.load(tmp_path), PR)["signoff_return"]
    assert ret["awaiting"] is None and "launch_claim" not in ret
    assert signoff.claim_return_launch(tmp_path, PR, hop) is False

def test_qa_launch_claim_outlives_awaiting(tmp_path):
    """QA S68: the qa driver clears ``awaiting`` before it replaces the
    judged run's qa window, so its claim must still say a run is starting
    (a tick in that gap launched a second driver)."""
    store.save({"project": {"name": "t", "repo": str(tmp_path),
                            "base_branch": "master", "backend": "local"},
                "prs": [_returned("qa", "qa")]}, tmp_path)
    assert signoff.claim_return_launch(tmp_path, PR, "qa") is True
    signoff.clear_return_awaiting(tmp_path, PR, "qa")
    p = store.get_pr(store.load(tmp_path), PR)
    assert p["signoff_return"]["awaiting"] is None
    assert signoff.return_launch_claimed(p, "qa") is True
    assert signoff.return_launch_claimed(p, "review") is False
    assert signoff.claim_return_launch(tmp_path, PR, "qa") is False
    p["signoff_return"]["launch_claim"]["at"] = "2000-01-01T00:00:00+00:00"
    assert signoff.return_launch_claimed(p, "qa") is False


def test_claim_waiting_on_the_lock_sees_a_claim_written_meanwhile(
        tmp_path, monkeypatch):
    """QA S71: the hop tick and a qa tick both waited on project.yaml's lock
    (an editor saving it).  The qa tick got it first and claimed; the hop
    tick, which had read the clock before waiting, saw that claim as from
    the future, took it over and launched a second driver."""
    store.save({"project": {"name": "t", "repo": str(tmp_path),
                            "base_branch": "master", "backend": "local"},
                "prs": [_returned("qa", "qa")]}, tmp_path)
    real = store.locked_update
    other = []

    def other_tick_first(root, fn, *a, **kw):
        if not other:
            other.append(None)
            time.sleep(0.01)
            other.append(signoff.claim_return_launch(root, PR, "qa"))
        return real(root, fn, *a, **kw)

    monkeypatch.setattr(store, "locked_update", other_tick_first)
    assert signoff.claim_return_launch(tmp_path, PR, "qa") is False
    assert other == [None, True]


def test_claim_return_launch_expires(tmp_path):
    p = _returned("in_review", "review",
                  launch_claim={"hop": "review",
                                "at": "2000-01-01T00:00:00+00:00"})
    store.save({"project": {"name": "t", "repo": str(tmp_path),
                            "base_branch": "master", "backend": "local"},
                "prs": [p]}, tmp_path)
    assert signoff.claim_return_launch(tmp_path, PR, "review") is True


def test_cli_leaves_a_claimed_review_return_launch_alone(tmp_path):
    """A second driver (concurrent tick, or the TUI that routed the
    verdict) is launching the return's review: relaunching --fresh would
    kill its window and leave two review windows behind."""
    result, _, review, qa = _seq(
        tmp_path, _returned("in_review", "review"),
        **{"pm_core.cli.pr._check_review_verdict": {"return_value": ("PASS", 3)},
           "pm_core.signoff.claim_return_launch": {"return_value": False}})
    assert result.exit_code == 0, result.output
    assert result.output.strip() == "running: review"
    review.callback.assert_not_called()
    qa.assert_not_called()


def test_cli_leaves_a_claimed_impl_return_launch_alone(tmp_path):
    """Same for an IMPL return: the TUI (hop or restart catch-up) is already
    relaunching the rework session; a second --fresh would kill it."""
    result, start, review, _ = _seq(
        tmp_path, _returned("in_progress", "impl"),
        **{"pm_core.cli.pr._check_impl_idle": {"return_value": (True, False)},
           "pm_core.signoff.claim_return_launch": {"return_value": False}})
    assert result.exit_code == 0, result.output
    assert result.output.strip() == "running: impl"
    start.callback.assert_not_called()
    review.callback.assert_not_called()


def test_tui_scheduler_leaves_a_claimed_impl_return_launch_alone(tmp_path):
    from pm_core import autostart_state as st
    from pm_core.tui import auto_start
    from tests.test_autostart_multi_target import FakeApp
    p = _returned("in_progress", "impl",
                  launch_claim={"hop": "impl", "at": datetime.now(
                      timezone.utc).isoformat()})
    p["depends_on"] = []
    app = FakeApp([p], root=tmp_path)
    app._auto_start = True
    app._auto_start_targets = {PR: st.make_target_record("t")}
    app._auto_start_run_id = "run"
    store.save(app._data, tmp_path)
    calls = []

    async def fake_start(_app, pr_id, fresh=False):
        calls.append((pr_id, fresh))

    with patch.object(auto_start, "_start_pr_quiet", fake_start), \
         patch("pm_core.tui.watcher_ui.is_running", return_value=False), \
         patch("pm_core.runtime_state.get_action_state", return_value={}), \
         patch("pm_core.tui.signoff_ui.advance_all"):
        asyncio.run(auto_start.check_and_start(app))
    assert calls == []


def test_tui_skipped_return_claim_schedules_one_recheck(tmp_path):
    """The claim's holder may have died before launching (TUI restart right
    after its hop) and the TUI has no periodic auto-start pass: a skipped
    claim schedules one scheduler pass for after the claim can expire."""
    from pm_core import autostart_state as st
    from pm_core.tui import auto_start
    from tests.test_autostart_multi_target import FakeApp
    now = datetime.now(timezone.utc).isoformat()
    impl = _returned("in_progress", "impl",
                     launch_claim={"hop": "impl", "at": now})
    impl["depends_on"] = []
    app = FakeApp([impl], root=tmp_path)
    app._auto_start = True
    app._auto_start_targets = {PR: st.make_target_record("t")}
    app._auto_start_run_id = "run"
    store.save(app._data, tmp_path)
    timers = []
    app.set_timer = lambda delay, cb: timers.append((delay, cb))

    async def fake_start(_app, pr_id, fresh=False):
        raise AssertionError("claimed launch must be left alone")

    with patch.object(auto_start, "_start_pr_quiet", fake_start), \
         patch("pm_core.tui.signoff_ui.advance_all"):
        asyncio.run(auto_start.check_and_start(app))
        asyncio.run(auto_start.check_and_start(app))
    assert len(timers) == 1                      # one pending re-check
    delay, fire = timers[0]
    assert delay > signoff.RETURN_LAUNCH_CLAIM_SECONDS
    fire()
    assert app._return_claim_recheck is False
    assert len(app.workers) == 1                 # the re-check pass

    # A REVIEW return's skipped claim schedules the same re-check.
    timers.clear()
    rev = _returned("in_review", "review",
                    launch_claim={"hop": "review", "at": now})
    rev["workdir"] = str(tmp_path)
    store.save({"project": app._data["project"], "prs": [rev]}, tmp_path)
    with patch("pm_core.tui.review_loop_ui._start_loop") as start:
        auto_start._auto_start_review_loops(app, [rev])
    start.assert_not_called()
    assert len(timers) == 1


@pytest.mark.parametrize("claimed", [True, False])
def test_tui_review_catch_up_takes_the_return_launch_claim(tmp_path, claimed):
    """After a TUI restart the review loop's --fresh launch for a REVIEW
    return is claim-guarded like the impl catch-up: a claimed launch (a
    concurrent auto-sequence tick) is left alone; otherwise the TUI takes
    the claim and starts the loop."""
    from pm_core import autostart_state as st
    from pm_core.tui import auto_start
    from tests.test_autostart_multi_target import FakeApp
    extra = ({"launch_claim": {"hop": "review", "at": datetime.now(
        timezone.utc).isoformat()}} if claimed else {})
    p = _returned("in_review", "review", **extra)
    p["depends_on"] = []
    app = FakeApp([p], root=tmp_path)
    app._auto_start = True
    app._auto_start_targets = {PR: st.make_target_record("t")}
    app._auto_start_run_id = "run"
    store.save(app._data, tmp_path)
    with patch("pm_core.tui.review_loop_ui._start_loop") as start, \
         patch.object(auto_start, "get_transcript_dir", return_value=tmp_path):
        auto_start._auto_start_review_loops(app, [p])
    assert start.called is not claimed
    if not claimed:
        rec = store.get_pr(store.load(tmp_path), PR)["signoff_return"]
        assert rec["launch_claim"]["hop"] == "review"


@pytest.mark.parametrize("case", ["finished", "running", "unannounced",
                                  "handoff_pending"])
def test_tui_review_return_written_behind_a_finished_loop_starts_it(
        tmp_path, case):
    """S83 story 3 E: the PR's review loop had finished (PASS) before QA and
    sign-off; `pm edit` then made the return a REVIEW one (in_review,
    ``awaiting: review``).  Every auto-start pass skipped the PR on its
    finished loop, so the return waited for good.  A finished loop gives
    way to a waiting return; a running one is never replaced, nor one whose
    PASS the poll tick has not yet announced and handed to QA (a pending
    hand-off would move the PR to qa under the new review)."""
    from pm_core.tui import review_loop_ui
    from pm_core import autostart_state as st
    from pm_core.review_loop import ReviewLoopState
    from pm_core.tui import auto_start
    from tests.test_autostart_multi_target import FakeApp
    p = _returned("in_review", "review")
    p["depends_on"] = []
    p["workdir"] = str(tmp_path)
    app = FakeApp([p], root=tmp_path)
    app._auto_start = True
    app._auto_start_targets = {PR: st.make_target_record("t")}
    app._auto_start_run_id = "run"
    old = ReviewLoopState(pr_id=PR)
    old.running = case == "running"
    old.latest_verdict = "" if old.running else "PASS"
    old._ui_notified_done = case in ("finished", "handoff_pending")
    if case == "handoff_pending":
        review_loop_ui._pending_auto_qa(app)[PR] = (
            "transition", store.LOCK_BUSY_REASON)
    app._review_loops[PR] = old
    store.save(app._data, tmp_path)
    with patch("pm_core.tui.review_loop_ui._start_loop") as start, \
         patch.object(auto_start, "get_transcript_dir", return_value=tmp_path):
        auto_start._auto_start_review_loops(app, [p])
    replaced = case == "finished"
    assert start.called is replaced
    assert (app._review_loops.get(PR) is old) is not replaced


def test_worktree_candidate_ignores_rerere_resolutions(w):
    """git < 2.38: the candidate merge must not replay a resolution the
    repository's (shared) rr-cache recorded — with rerere.autoUpdate that
    would stage the conflicted path and turn the conflict into an error."""
    git(w.wd, "config", "rerere.enabled", "true")
    git(w.wd, "config", "rerere.autoUpdate", "true")
    commit(w.repo, "shared.txt", "base side\n", "base edits shared")
    head = commit(w.wd, "shared.txt", "pr side\n", "pr edits shared")
    base, err = integration.fetch_base(str(w.wd), str(w.repo), "master")
    assert err is None
    # Record a resolution of exactly this conflict in the PR worktree.
    subprocess.run(["git", "merge", "-q", base], cwd=w.wd,
                   capture_output=True)
    (w.wd / "shared.txt").write_text("resolved\n")
    git(w.wd, "add", "shared.txt")
    git(w.wd, "commit", "-q", "--no-edit")
    git(w.wd, "reset", "-q", "--hard", head)

    with patch.object(integration, "_git_version", return_value=(2, 34)):
        cand = integration.compute_candidate(str(w.wd), head, base)
    assert cand["status"] == integration.CONFLICT, cand
    assert cand["conflicts"] == ["shared.txt"]


def test_busy_step_lock_reports_running_instead_of_blocking(w):
    """Another driver mid-step holds the per-PR lock: the TUI (event loop)
    must not wait on it indefinitely — the step reports "running" and the
    next tick re-evaluates."""
    import fcntl
    from pm_core.paths import workdirs_base
    with open(workdirs_base() / f".signoff-step-{PR}.lock", "w") as held, \
            patch.object(signoff, "_STEP_LOCK_WAIT", 0.1):
        fcntl.flock(held.fileno(), fcntl.LOCK_EX)
        res, retired = step(w, SIGNOFF_REVIEW)
    assert res.action == "running" and not retired
    assert pr(w)["status"] == "sign_off" and "signoff" not in pr(w)
    res, _ = step(w, SIGNOFF_REVIEW)                 # lock free again
    assert res.action == "hop" and res.hop == "review"
