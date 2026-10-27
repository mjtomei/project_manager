"""Sync-detected GitHub merges are verified against the bound SIGNOFF_MERGE.

pr-2e06289: the TUI's 5-minute background sync (``do_normal_sync`` →
``pr_sync.sync_prs``) and the startup/``pm pr sync-github`` path
(``sync_from_github``) marked a PR merged as soon as GitHub reported it,
without the sign-off integrity check ``pm pr merge`` performs.  A merge
published by someone else from a branch that carried unreviewed commits was
finalized silently — no ``merge_integrity``, no note.

Real git repositories + the in-process fake GitHub backend throughout; the
approval is produced exactly as sign-off produces it (integration check →
bound SIGNOFF_MERGE).
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
from click.testing import CliRunner

from pm_core import integration, merge_integrity, pr_sync, signoff, store
from pm_core.cli import pr as pr_mod
from pm_core.tui import sync as tui_sync

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


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    for k, v in {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                 "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}.items():
        monkeypatch.setenv(k, v)
    croot = tmp_path / "captures"
    with mock.patch("pm_core.paths.captures_root", return_value=croot):
        yield


@pytest.fixture
def sync_github(tmp_path, fake_github_repo):
    """A github-backend PR with a bound SIGNOFF_MERGE, not yet merged."""
    remote = Path(fake_github_repo.git_repo.path)
    wd = tmp_path / "home" / ".pm" / "workdirs" / "proj" / PR
    git(tmp_path, "clone", "-q", str(remote), str(wd))
    git(wd, "checkout", "-q", "-b", BRANCH)
    head = commit(wd, "feature.txt", "feature\n", "feature")
    git(wd, "push", "-q", "origin", f"{BRANCH}:refs/heads/{BRANCH}")
    gh_pr = fake_github_repo.add_pr(title="PR one", head=BRANCH)
    main = tmp_path / "main"
    git(tmp_path, "clone", "-q", str(remote), str(main))
    pm_dir = tmp_path / "pmstate"
    pm_dir.mkdir()
    store.save({
        "project": {"name": "proj", "base_branch": "master",
                    "repo": str(main), "backend": "github"},
        "prs": [{"id": PR, "title": "PR one", "branch": BRANCH,
                 "status": "sign_off", "workdir": str(wd),
                 "gh_pr_number": gh_pr.number}],
        "plans": [],
    }, pm_dir)
    rec = integration.check_integration(pm_dir, PR)
    assert rec["status"] in integration.MERGEABLE, rec
    signoff.record_signoff_verdict(
        pm_dir, PR, signoff.SIGNOFF_MERGE, rec["head"], "auto-sequence",
        integration=integration.binding(rec))
    return SimpleNamespace(fake=fake_github_repo, remote=remote, wd=wd,
                           main=main, pm_dir=pm_dir, head=head, pr=gh_pr,
                           tmp=tmp_path)


def merge_on_remote(w, *, extra: bool) -> str:
    """Someone merges the PR on GitHub (optionally after an unreviewed
    commit pushed to its branch).  Returns the new base tip."""
    if extra:
        other = w.tmp / "teammate"
        git(w.tmp, "clone", "-q", "-b", BRANCH, str(w.remote), str(other))
        commit(other, "unreviewed.txt", "u\n", "unreviewed")
        git(other, "push", "-q", "origin", BRANCH)
    git(w.remote, "merge", "-q", "--no-ff", "-m", "merged on GitHub", BRANCH)
    tip = git(w.remote, "rev-parse", "master")
    w.pr.state = "MERGED"
    w.pr.merged_at = "2026-01-01T00:00:00Z"
    return tip


def pr_entry(w) -> dict:
    return store.get_pr(store.load(w.pm_dir), PR)


def set_signoff(w, signoff_record: dict | None) -> None:
    """Replace (or drop) the PR's approval record."""
    def _apply(d):
        pr = store.get_pr(d, PR)
        if signoff_record is None:
            pr.pop("signoff", None)
        else:
            pr["signoff"] = signoff_record
    store.locked_update(w.pm_dir, _apply)


def integrity_notes(w) -> list[str]:
    return [n["text"] for n in pr_entry(w).get("notes") or []
            if str(n.get("text", "")).startswith("Merge integrity:")]


class _FakeApp:
    _qa_visible = False
    _plans_visible = False
    _current_guide_step = None
    _session_name = None
    _auto_start = False

    def __init__(self, root):
        self._root = root
        self._data = store.load(root)
        self.messages = []
        self.log_kwargs = []
        self.status_calls = []

    def _update_status_bar(self, sync_state="synced"):
        self.status_calls.append(sync_state)

    def _update_display(self):
        pass

    def log_message(self, msg, **kw):
        self.messages.append(msg)
        self.log_kwargs.append(kw)
        return len(self.messages)

    def clear_log_message_later(self, delay, seq=None):
        pass


def integrity_log_lines(app) -> list[tuple[str, dict]]:
    """The ``Merge integrity:`` lines the TUI logged, with their kwargs."""
    return [(m, kw) for m, kw in zip(app.messages, app.log_kwargs)
            if m.startswith("Merge integrity:")]


# --- pr_sync.sync_prs (the TUI background path) ---------------------------

def test_sync_prs_records_integrity_for_unapproved_merge(sync_github):
    """A GitHub merge that published unreviewed commits is flagged by sync."""
    tip = merge_on_remote(sync_github, extra=True)

    result = pr_sync.sync_prs(sync_github.pm_dir, force=True, save_state=False)

    assert PR in result.merged_prs
    v = result.merge_integrity.get(PR)
    assert v is not None and v.problem
    assert sync_github.head[:12] in v.problem
    assert "not the approved head" in v.problem
    assert v.merge_sha == tip
    # save_state=False (the TUI worker thread): the check returns the
    # evidence, it does not write project.yaml.
    assert "merge_integrity" not in pr_entry(sync_github)


def test_sync_prs_persists_integrity_and_note(sync_github):
    merge_on_remote(sync_github, extra=True)

    pr_sync.sync_prs(sync_github.pm_dir, force=True)

    pr = pr_entry(sync_github)
    assert pr["status"] == "merged"
    integrity = pr.get("merge_integrity")
    assert integrity and "not the approved head" in integrity["problem"]
    assert len(integrity_notes(sync_github)) == 1


def test_sync_prs_approved_merge_records_nothing(sync_github):
    """A merge of the signed-off candidate is not flagged."""
    merge_on_remote(sync_github, extra=False)

    result = pr_sync.sync_prs(sync_github.pm_dir, force=True)

    assert PR in result.merged_prs
    assert result.merge_integrity == {}
    assert "merge_integrity" not in pr_entry(sync_github)
    assert integrity_notes(sync_github) == []


def test_sync_prs_repeated_detection_notes_once(sync_github):
    merge_on_remote(sync_github, extra=True)
    pr_sync.sync_prs(sync_github.pm_dir, force=True)

    def _reset(d):
        store.get_pr(d, PR)["status"] = "sign_off"
    store.locked_update(sync_github.pm_dir, _reset)
    pr_sync.sync_prs(sync_github.pm_dir, force=True)

    assert len(integrity_notes(sync_github)) == 1


def test_sync_prs_unverifiable_merge_still_finalizes(sync_github):
    """A failed base fetch is "unknown": logged, not recorded, merge kept."""
    merge_on_remote(sync_github, extra=True)
    with mock.patch.object(integration, "fetch_base",
                           return_value=(None, "boom")):
        result = pr_sync.sync_prs(sync_github.pm_dir, force=True)

    assert PR in result.merged_prs
    assert result.merge_integrity[PR].error == "boom"
    assert "merge_integrity" not in pr_entry(sync_github)
    assert pr_entry(sync_github)["status"] == "merged"


def test_sync_prs_verification_crash_still_finalizes(sync_github):
    """An unexpected error in the check must not stop merge detection."""
    merge_on_remote(sync_github, extra=True)
    with mock.patch.object(merge_integrity, "verify_github_merge",
                           side_effect=RuntimeError("boom")):
        result = pr_sync.sync_prs(sync_github.pm_dir, force=True)

    assert PR in result.merged_prs
    assert result.merge_integrity[PR].error == "boom"
    assert "merge_integrity" not in pr_entry(sync_github)
    assert pr_entry(sync_github)["status"] == "merged"


def test_sync_prs_no_approval_records_nothing(sync_github):
    """A PR merged on GitHub without any sign-off has nothing to verify."""
    merge_on_remote(sync_github, extra=True)
    set_signoff(sync_github, None)

    result = pr_sync.sync_prs(sync_github.pm_dir, force=True)

    assert PR in result.merged_prs
    assert result.merge_integrity == {}
    assert "merge_integrity" not in pr_entry(sync_github)
    assert integrity_notes(sync_github) == []


def test_sync_prs_legacy_unbound_approval_records_nothing(sync_github):
    """A HEAD-only SIGNOFF_MERGE has no base/tree to compare against."""
    merge_on_remote(sync_github, extra=True)
    set_signoff(sync_github, {"verdict": signoff.SIGNOFF_MERGE,
                              "sha": sync_github.head})

    result = pr_sync.sync_prs(sync_github.pm_dir, force=True)

    assert PR in result.merged_prs
    assert result.merge_integrity == {}
    assert "merge_integrity" not in pr_entry(sync_github)


def test_sync_prs_workdir_gone_verifies_from_the_sync_workdir(sync_github):
    """With the PR's workdir gone, the check runs in the workdir sync used.

    `sync_prs` reads merge status from another PR's workdir when the PR's own
    is gone; verification must use that same directory (and the project repo,
    which has been pulled) instead of skipping the check.
    """
    merge_on_remote(sync_github, extra=True)
    other = sync_github.tmp / "home" / ".pm" / "workdirs" / "proj" / "other"
    git(sync_github.tmp, "clone", "-q", str(sync_github.remote), str(other))
    # The project repo (the fallback fetch source) has since pulled the merge.
    git(sync_github.main, "fetch", "-q", "origin")
    git(sync_github.main, "merge", "-q", "--ff-only", "origin/master")
    shutil.rmtree(sync_github.wd)

    result = pr_sync.sync_prs(sync_github.pm_dir, force=True)

    assert PR in result.merged_prs
    v = result.merge_integrity.get(PR)
    assert v is not None and "not the approved head" in v.problem
    assert "merge_integrity" in pr_entry(sync_github)


# --- pr_sync.sync_from_github (startup / pm pr sync-github) ----------------

def test_sync_from_github_records_integrity_for_unapproved_merge(sync_github):
    tip = merge_on_remote(sync_github, extra=True)

    result = pr_sync.sync_from_github(sync_github.pm_dir)

    assert PR in result.merged_prs
    v = result.merge_integrity.get(PR)
    assert v is not None and "not the approved head" in v.problem
    assert v.merge_sha == tip
    assert pr_entry(sync_github)["merge_integrity"]["merge_sha"] == tip


def test_sync_from_github_workdir_gone_falls_back_to_project_repo(sync_github):
    """A merge is still verified when the PR's workdir no longer exists.

    The check falls back to the project repo, exactly as `pm pr merge`'s
    recovery path does — losing the workdir must not turn a mismatch into a
    silent finalize.  The project repo has no PR branch, so the check cannot
    name the merge that published it (``is_ancestor`` needs the head object)
    and reports the general "did not publish the signed-off candidate".
    """
    merge_on_remote(sync_github, extra=True)
    shutil.rmtree(sync_github.wd)

    result = pr_sync.sync_from_github(sync_github.pm_dir)

    assert PR in result.merged_prs
    v = result.merge_integrity.get(PR)
    assert v is not None and v.problem
    assert "did not publish the signed-off candidate" in v.problem
    assert sync_github.head[:12] in v.problem
    assert "merge_integrity" in pr_entry(sync_github)


# --- TUI sync entry points -------------------------------------------------

def test_tui_normal_sync_applies_integrity(sync_github):
    merge_on_remote(sync_github, extra=True)
    app = _FakeApp(sync_github.pm_dir)

    asyncio.run(tui_sync.do_normal_sync(app, is_manual=False))

    pr = store.get_pr(app._data, PR)
    assert pr["status"] == "merged"
    assert "not the approved head" in pr["merge_integrity"]["problem"]
    lines = integrity_log_lines(app)
    assert len(lines) == 1 and "not the approved head" in lines[0][0]
    # Held so the tick's "Synced: N PR(s) merged" line does not paint over it.
    assert lines[0][1].get("force") is True
    assert lines[0][1].get("hold") == tui_sync._INTEGRITY_HOLD_SECONDS


def test_tui_startup_github_sync_applies_integrity(sync_github):
    merge_on_remote(sync_github, extra=True)
    app = _FakeApp(sync_github.pm_dir)

    asyncio.run(tui_sync.startup_github_sync(app))

    pr = store.get_pr(app._data, PR)
    assert pr["status"] == "merged"
    assert "not the approved head" in pr["merge_integrity"]["problem"]
    lines = integrity_log_lines(app)
    assert len(lines) == 1 and "not the approved head" in lines[0][0]
    assert lines[0][1].get("force") is True
    assert lines[0][1].get("hold") == tui_sync._INTEGRITY_HOLD_SECONDS


# --- CLI pm pr sync --------------------------------------------------------

def test_cli_pr_sync_records_integrity(sync_github):
    merge_on_remote(sync_github, extra=True)

    with mock.patch.object(pr_mod, "state_root",
                           return_value=sync_github.pm_dir), \
         mock.patch.object(pr_mod, "trigger_tui_refresh"):
        result = CliRunner().invoke(pr_mod.pr, ["sync"])

    assert result.exit_code == 0, result.output
    pr = pr_entry(sync_github)
    assert pr["status"] == "merged"
    assert "not the approved head" in pr["merge_integrity"]["problem"]
    assert len(integrity_notes(sync_github)) == 1
    assert "WARNING:" in result.output
    assert "not the approved head" in result.output


def test_cli_pr_sync_unverifiable_merge_warns_and_records_nothing(sync_github):
    """`pm pr sync` says it could not verify; it does not invent a problem."""
    merge_on_remote(sync_github, extra=True)
    with mock.patch.object(integration, "fetch_base",
                           return_value=(None, "boom")), \
         mock.patch.object(pr_mod, "state_root",
                           return_value=sync_github.pm_dir), \
         mock.patch.object(pr_mod, "trigger_tui_refresh"):
        result = CliRunner().invoke(pr_mod.pr, ["sync"])

    assert result.exit_code == 0, result.output
    assert pr_entry(sync_github)["status"] == "merged"
    assert "merge_integrity" not in pr_entry(sync_github)
    assert "could not verify" in result.output
    assert "boom" in result.output


def test_cli_pr_sync_github_reports_integrity(sync_github):
    """`pm pr sync-github` says so too, not only the PR record + log file."""
    merge_on_remote(sync_github, extra=True)

    with mock.patch.object(pr_mod, "state_root",
                           return_value=sync_github.pm_dir), \
         mock.patch.object(pr_mod, "trigger_tui_refresh"):
        result = CliRunner().invoke(pr_mod.pr, ["sync-github"])

    assert result.exit_code == 0, result.output
    assert "not the approved head" in pr_entry(sync_github)[
        "merge_integrity"]["problem"]
    assert "WARNING:" in result.output
    assert "not the approved head" in result.output
