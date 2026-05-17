"""Tests for the FakeGitHubBackend transport (pm_core/fake_github.py)."""

import json
import subprocess
from pathlib import Path

import pytest

from pm_core import gh_ops, pr_sync
from pm_core.fake_github import (
    REAL_GIT,
    FakeGitHubBackend,
    create_draft_on_start,
    merge_with_pull,
    sync_mid_flow,
    upgrade_on_done,
)


# --- transport wiring -------------------------------------------------------

def test_runner_install_and_restore():
    """installed() installs the fake and restores the previous transport."""
    assert gh_ops._GH_RUNNER is None
    backend = FakeGitHubBackend()
    with backend.installed():
        assert gh_ops._GH_RUNNER == backend.run
    assert gh_ops._GH_RUNNER is None


def test_runner_nests():
    """Nested installs restore the outer transport on exit."""
    outer, inner = FakeGitHubBackend(), FakeGitHubBackend()
    with outer.installed():
        with inner.installed():
            assert gh_ops._GH_RUNNER == inner.run
        assert gh_ops._GH_RUNNER == outer.run


# --- gh_ops surface against the fake ---------------------------------------

def test_create_draft_pr(fake_github):
    result = gh_ops.create_draft_pr("/tmp/repo", "My PR", "master", "body")
    assert result is not None
    assert result["url"].endswith("/pull/1")
    assert result["number"] == 1
    pr = fake_github.prs[1]
    assert pr.is_draft and pr.title == "My PR" and pr.body == "body"


def test_create_pr_non_draft(fake_github):
    url = gh_ops.create_pr("/tmp/repo", "Ready PR", "master", "body")
    assert url and url.endswith("/pull/1")
    assert fake_github.prs[1].is_draft is False


def test_get_pr_status_by_branch(fake_github):
    fake_github.add_pr(title="T", head="feature-x")
    info = gh_ops.get_pr_status("/tmp/repo", "feature-x")
    assert info["state"] == "OPEN"
    assert info["number"] == 1
    assert set(info) == {"state", "url", "number", "title", "mergedAt"}


def test_get_pr_status_unknown_branch(fake_github):
    assert gh_ops.get_pr_status("/tmp/repo", "no-such-branch") is None


def test_mark_pr_ready(fake_github):
    pr = fake_github.create_draft("feature-x")
    assert gh_ops.mark_pr_ready("/tmp/repo", pr.number) is True
    assert fake_github.prs[pr.number].is_draft is False


def test_is_pr_merged(fake_github):
    pr = fake_github.add_pr(head="feature-x")
    assert gh_ops.is_pr_merged("/tmp/repo", "feature-x") is False
    fake_github.merge(pr)
    assert gh_ops.is_pr_merged("/tmp/repo", "feature-x") is True


def test_list_prs_filters_by_state(fake_github):
    fake_github.add_pr(head="open-1")
    fake_github.add_pr(head="closed-1", state="CLOSED")
    open_prs = gh_ops.list_prs("/tmp/repo", state="open")
    assert [p["headRefName"] for p in open_prs] == ["open-1"]
    all_prs = gh_ops.list_prs("/tmp/repo", state="all")
    assert len(all_prs) == 2


def test_merge_pr(fake_github):
    pr = fake_github.add_pr(head="feature-x")
    result = gh_ops.merge_pr("/tmp/repo", pr.number)
    assert result.returncode == 0
    assert fake_github.prs[pr.number].state == "MERGED"


def test_merge_already_merged_fails(fake_github):
    """merged-elsewhere: a second merge exits non-zero like real gh."""
    pr = fake_github.add_pr(head="feature-x", state="MERGED")
    result = gh_ops.merge_pr("/tmp/repo", pr.number)
    assert result.returncode == 1
    assert "already merged" in result.stderr


def test_close_pr(fake_github):
    pr = fake_github.add_pr(head="feature-x")
    result = gh_ops.close_pr(pr.number, delete_branch=True)
    assert result.returncode == 0
    assert fake_github.prs[pr.number].state == "CLOSED"


def test_pr_create_head_without_base(fake_github):
    """The git_ops state-sync form: `gh pr create --head X` (no --base)."""
    result = gh_ops.run_gh(
        "pr", "create",
        "--title", "pm: update project state",
        "--body", "Automated pm state sync.",
        "--head", "pm-state-sync",
        check=False,
    )
    assert result.returncode == 0
    pr = fake_github.prs[1]
    assert pr.head == "pm-state-sync"
    assert pr.base == fake_github.default_branch  # defaulted


def test_get_pr_state(fake_github):
    pr = fake_github.add_pr(head="feature-x", is_draft=True)
    info = gh_ops.get_pr_state(pr.number)
    assert info == {"state": "OPEN", "isDraft": True, "mergedAt": None}


def test_auth_status_ok(fake_github):
    result = gh_ops.run_gh("auth", "status", check=False)
    assert result.returncode == 0


# --- scripted responses -----------------------------------------------------

def test_simulate_rate_limit(fake_github):
    fake_github.add_pr(head="feature-x")
    fake_github.simulate_rate_limit("pr view")
    assert gh_ops.get_pr_status("/tmp/repo", "feature-x") is None  # 403
    # exhausted after one use -> next call succeeds
    assert gh_ops.get_pr_status("/tmp/repo", "feature-x") is not None


def test_simulate_conflict_on_merge(fake_github):
    pr = fake_github.add_pr(head="feature-x")
    fake_github.simulate_conflict("pr merge")
    result = gh_ops.merge_pr("/tmp/repo", pr.number)
    assert result.returncode == 1 and "conflict" in result.stderr.lower()
    assert fake_github.prs[pr.number].state == "OPEN"  # not merged


def test_simulate_server_error_repeats(fake_github):
    fake_github.add_pr(head="feature-x")
    fake_github.simulate_server_error("pr view", times=2)
    assert gh_ops.get_pr_status("/tmp/repo", "feature-x") is None
    assert gh_ops.get_pr_status("/tmp/repo", "feature-x") is None
    assert gh_ops.get_pr_status("/tmp/repo", "feature-x") is not None


def test_scripted_failure_with_check_raises(fake_github):
    """check=True surfaces a scripted failure as CalledProcessError."""
    fake_github.simulate_server_error("pr list")
    with pytest.raises(subprocess.CalledProcessError):
        gh_ops.run_gh("pr", "list", check=True)


def test_queue_response_predicate(fake_github):
    fake_github.queue_response(
        lambda argv: argv[:2] == ["pr", "ready"],
        returncode=1, stderr="boom",
    )
    assert gh_ops.mark_pr_ready("/tmp/repo", 1) is False


def test_calls_are_recorded(fake_github):
    gh_ops.list_prs("/tmp/repo")
    assert ["pr", "list"] == fake_github.calls[-1][:2]


# --- scenario helpers -------------------------------------------------------

def test_scenario_create_and_upgrade(fake_github):
    pr = create_draft_on_start(fake_github, "feature-x", title="Feature X")
    assert pr.is_draft and pr.title == "Feature X"
    upgrade_on_done(fake_github, pr)
    assert fake_github.prs[pr.number].is_draft is False


def test_scenario_merge_with_pull(fake_github):
    pr = create_draft_on_start(fake_github, "feature-x")
    merge_with_pull(fake_github, pr)
    assert gh_ops.is_pr_merged("/tmp/repo", "feature-x") is True


# --- integration: github status polling path drives the fake ---------------

def _github_root(tmp_path, gh_pr_number=1):
    root = tmp_path / "pm"
    root.mkdir()
    (root / "project.yaml").write_text(
        "project:\n"
        "  name: test-project\n"
        "  repo: /tmp/test-repo\n"
        "  base_branch: master\n"
        "  backend: github\n"
        "prs:\n"
        "  - id: pr-001\n"
        "    title: Feature\n"
        "    branch: feature-x\n"
        "    status: in_progress\n"
        f"    gh_pr_number: {gh_pr_number}\n"
    )
    return root


def test_sync_from_github_detects_merge(fake_github, tmp_path):
    """sync-mid-flow: advancing fake state is observed by sync_from_github."""
    root = _github_root(tmp_path)
    pr = fake_github.add_pr(head="feature-x", is_draft=True)  # number 1

    result = pr_sync.sync_from_github(root, save_state=False)
    assert result.status_updates == {}  # still draft -> in_progress, unchanged

    sync_mid_flow(fake_github, pr, state="MERGED")
    result = pr_sync.sync_from_github(root, save_state=False)
    assert result.merged_prs == ["pr-001"]


def test_sync_from_github_draft_to_ready(fake_github, tmp_path):
    root = _github_root(tmp_path)
    pr = fake_github.add_pr(head="feature-x", is_draft=True)
    pr.is_draft = False  # upgrade-on-done happened remotely

    result = pr_sync.sync_from_github(root, save_state=False)
    assert result.status_updates == {"pr-001": "in_review"}


# --- git-backed fake: real git state behind git-affecting operations -------

def _git(*args, cwd):
    # Real git binary — bypasses the pm push-proxy wrapper so `fetch` from a
    # consumer clone reaches the local FakeGitHubRepo remote.
    return subprocess.run([REAL_GIT, *args], cwd=str(cwd),
                          capture_output=True, text=True)


def test_with_git_repo_builds_backing_repo(tmp_path):
    backend = FakeGitHubBackend.with_git_repo(tmp_path / "gh")
    assert backend.git_repo is not None
    assert backend.git_repo.branch_exists("master")


def test_git_backed_pr_create_creates_branch(fake_github_repo):
    """`gh pr create --head X` registers X as a real branch on the remote."""
    gh_ops.create_draft_pr("/tmp/repo", "Feature", "master", "body")
    branch = fake_github_repo.prs[1].head
    assert fake_github_repo.git_repo.branch_exists(branch)


def test_git_backed_merge_advances_base(fake_github_repo):
    pr = fake_github_repo.add_pr(head="feature-x")
    assert fake_github_repo.git_repo.is_merged("feature-x") is False
    result = gh_ops.merge_pr("/tmp/repo", pr.number)
    assert result.returncode == 0
    assert fake_github_repo.git_repo.is_merged("feature-x") is True


def test_git_backed_merge_with_pull(fake_github_repo, tmp_path):
    """The full merge-with-pull path: gh merge then a consumer ff-only pull."""
    consumer = fake_github_repo.git_repo.clone(tmp_path / "consumer")

    pr = fake_github_repo.create_draft("feature-x")  # real branch on remote
    assert gh_ops.merge_pr("/tmp/repo", pr.number).returncode == 0

    # The consumer workdir pulls base exactly as `_pull_after_merge` does.
    assert _git("fetch", "origin", cwd=consumer).returncode == 0
    ff = _git("merge", "--ff-only", "origin/master", cwd=consumer)
    assert ff.returncode == 0, ff.stderr
    assert (Path(consumer) / ".pr-feature-x").exists()


def test_git_backed_merge_conflict(fake_github_repo):
    """A real git conflict surfaces as a conflict-shaped `gh` failure."""
    a = fake_github_repo.add_pr(head="feat-a", files={"shared.txt": "from A\n"})
    b = fake_github_repo.add_pr(head="feat-b", files={"shared.txt": "from B\n"})

    assert gh_ops.merge_pr("/tmp/repo", a.number).returncode == 0
    result = gh_ops.merge_pr("/tmp/repo", b.number)
    assert result.returncode == 1
    assert "conflict" in result.stderr.lower()
    # base unchanged for the conflicting PR; state stays OPEN
    assert fake_github_repo.prs[b.number].state == "OPEN"
    assert fake_github_repo.git_repo.is_merged("feat-b") is False


def test_git_backed_merge_already_merged(fake_github_repo):
    """merged-elsewhere on a git-backed fake still reports already-merged."""
    pr = fake_github_repo.add_pr(head="feature-x")
    fake_github_repo.merge(pr)
    result = gh_ops.merge_pr("/tmp/repo", pr.number)
    assert result.returncode == 1
    assert "already merged" in result.stderr


def test_git_backed_seed_merged_state(fake_github_repo):
    """add_pr(state='MERGED') performs a real merge on the backing repo."""
    pr = fake_github_repo.add_pr(head="feature-x", state="MERGED")
    assert pr.state == "MERGED"
    assert fake_github_repo.git_repo.is_merged("feature-x") is True
