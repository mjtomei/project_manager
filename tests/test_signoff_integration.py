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
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from unittest.mock import MagicMock, patch

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
    calls = []

    async def fake_start(_app, pr_id, fresh=False):
        calls.append((pr_id, fresh))

    with patch.object(auto_start, "_start_pr_quiet", fake_start), \
         patch("pm_core.tui.watcher_ui.is_running", return_value=False), \
         patch("pm_core.runtime_state.get_action_state", return_value={}), \
         patch("pm_core.tui.signoff_ui.advance_all"):
        asyncio.run(auto_start.check_and_start(app))
    assert sorted(calls) == [(PR, True), ("pr-002", False)]


def test_tui_qa_pass_not_handed_to_signoff_while_reqa_awaits(tmp_path):
    from pm_core import autostart_state as st
    from pm_core.tui import auto_start, signoff_ui
    from tests.test_autostart_multi_target import FakeApp
    p = _returned("qa", "qa")
    p["depends_on"] = []
    app = FakeApp([p], root=tmp_path)
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
