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


# --- out-of-process session fake (CLI-installable, run_gh config gate) ------

@pytest.fixture
def session_fake(monkeypatch, tmp_path):
    """Point the session-dir machinery at tmp_path with a fixed tag.

    Yields the tag. With this active, paths.fake_github_active()/dir() resolve
    under tmp_path, so install_session + the gh_ops.run_gh gate can be driven
    without a real pm session — and crucially WITHOUT installing an in-process
    runner, so the out-of-process path is what's exercised.
    """
    tag = "proj-deadbeef"
    monkeypatch.setattr("pm_core.paths.sessions_dir", lambda: tmp_path)
    monkeypatch.setattr("pm_core.paths.get_session_tag", lambda **kw: tag)
    # Ensure no in-process runner leaks in from elsewhere.
    assert gh_ops._GH_RUNNER is None
    yield tag


def test_session_install_active_clear(session_fake):
    from pm_core import fake_github, paths

    assert paths.fake_github_active() is False
    fake_github.install_session({"prs": [{"head": "feat-x", "draft": True}]})
    assert paths.fake_github_active() is True

    paths.clear_fake_github()
    assert paths.fake_github_active() is False


def test_session_run_gh_dispatches_to_fake(session_fake):
    """A run_gh call with no in-process runner is served by the session fake."""
    from pm_core import fake_github

    fake_github.install_session({
        "git_backed": False,
        "prs": [{"head": "feat-x", "title": "Feature X", "draft": True}],
    })

    info = gh_ops.get_pr_status("/tmp/repo", "feat-x")
    assert info is not None and info["state"] == "OPEN" and info["number"] == 1


def test_session_state_persists_across_run_gh_calls(session_fake):
    """State mutates on disk: a PR created by one call is seen by the next."""
    from pm_core import fake_github

    fake_github.install_session({"git_backed": False})

    created = gh_ops.create_draft_pr("/tmp/repo", "My PR", "master", "body")
    assert created["number"] == 1
    # A separate run_gh call (fresh load from disk) sees the new PR.
    info = gh_ops.get_pr_state(created["number"])
    assert info == {"state": "OPEN", "isDraft": True, "mergedAt": None}


def test_session_scripted_failure(session_fake):
    from pm_core import fake_github

    fake_github.install_session({
        "git_backed": False,
        "prs": [{"head": "feat-x"}],
        "scripts": [{"match": "pr view", "returncode": 1,
                     "stderr": "gh: rate limit (HTTP 403)"}],
    })
    assert gh_ops.get_pr_status("/tmp/repo", "feat-x") is None  # scripted 403
    assert gh_ops.get_pr_status("/tmp/repo", "feat-x") is not None  # consumed


def test_session_git_backed_merge_persists(session_fake):
    """gh pr merge through the session path advances the on-disk backing repo."""
    from pm_core import fake_github

    fake_github.install_session({"prs": [{"head": "feat-x", "draft": True}]})

    result = gh_ops.merge_pr("/tmp/repo", 1)
    assert result.returncode == 0

    reloaded = fake_github.load_session()
    assert reloaded.prs[1].state == "MERGED"
    assert reloaded.git_repo.is_merged("feat-x") is True


def test_session_seed_merged_then_open_conflicts(session_fake):
    """A seeded list whose earlier PR is MERGED still lets a later, conflicting
    OPEN PR conflict.

    Regression: install_session used to apply MERGED transitions inline while
    building branches, so a later head branch forked off the *advanced* base and
    a conflict meant to exist silently dissolved into a clean modify. Branches
    must fork from the original base (real PRs branch at open-time, independent
    of one another's later merges); merges are applied only after every branch
    exists.
    """
    from pm_core import fake_github

    fake_github.install_session({
        "prs": [
            {"head": "feat-a", "state": "MERGED", "files": {"conflict.txt": "A\n"}},
            {"head": "feat-b", "state": "OPEN", "files": {"conflict.txt": "B\n"}},
        ],
    })

    # feat-a landed at seed time; feat-b is forked from the original base and
    # still conflicts against the advanced master.
    reloaded = fake_github.load_session()
    assert reloaded.prs[1].state == "MERGED"
    assert reloaded.git_repo.is_merged("feat-a") is True
    assert reloaded.git_repo.is_merged("feat-b") is False

    result = gh_ops.merge_pr("/tmp/repo", 2)
    assert result.returncode == 1
    assert "conflict" in result.stderr.lower()

    # base unchanged, PR stays OPEN, no dangling merge state.
    after = fake_github.load_session()
    assert after.prs[2].state == "OPEN"
    assert after.git_repo.is_merged("feat-b") is False
    git_dir = Path(after.git_repo.path) / ".git"
    assert not (git_dir / "MERGE_HEAD").exists()
    assert not (git_dir / "index.lock").exists()


def test_session_inactive_returns_none(session_fake):
    """The gate returns None (→ real gh) when no fake is installed."""
    assert gh_ops._maybe_dispatch_session_fake(("pr", "list"), None) is None


def test_in_process_runner_takes_precedence_over_session(session_fake, tmp_path):
    """An installed in-process runner wins over the session fake."""
    from pm_core import fake_github

    fake_github.install_session({"git_backed": False,
                                 "prs": [{"head": "disk-pr"}]})
    inproc = FakeGitHubBackend()  # empty, in-process
    inproc.add_pr(head="mem-pr")
    with inproc.installed():
        prs = gh_ops.list_prs("/tmp/repo")
    assert [p["headRefName"] for p in prs] == ["mem-pr"]  # not disk-pr


# --- pm fake-github CLI -----------------------------------------------------

def test_cli_config_set_show_clear(session_fake):
    import json as _json
    from click.testing import CliRunner
    from pm_core.cli.fake_github import (
        config_clear_cmd, config_set_cmd, config_show_cmd,
    )
    from pm_core import paths

    runner = CliRunner()
    cfg = _json.dumps({"git_backed": False,
                       "prs": [{"head": "feat-x", "draft": True}]})

    r = runner.invoke(config_set_cmd, [cfg])
    assert r.exit_code == 0, r.output
    assert "Installed fake-github" in r.output
    assert paths.fake_github_active() is True

    r = runner.invoke(config_show_cmd, [])
    assert r.exit_code == 0 and "feat-x" in r.output

    r = runner.invoke(config_clear_cmd, [])
    assert r.exit_code == 0
    assert paths.fake_github_active() is False


def test_cli_config_set_rejects_bad_json(session_fake):
    from click.testing import CliRunner
    from pm_core.cli.fake_github import config_set_cmd

    r = CliRunner().invoke(config_set_cmd, ["{not json"])
    assert r.exit_code != 0
    assert "Invalid JSON" in r.output


# --- concurrency: regression coverage for the QA-scenario-6 fixes -----------
#
# These guard the concurrency-safety code added to fix QA scenario 6: the
# per-repo RLock + _cleanup_worktree in FakeGitHubRepo (merges into the single
# backing worktree were colliding on .git/index.lock, losing non-conflicting
# merges and leaking dangling MERGE_HEAD/index.lock), and the gh_ops depth
# counter that forces _GH_RUNNER back to the None baseline after interleaved
# install/restore cycles (the transport-pointer leak). Previously these were
# only exercised by throwaway QA capture drivers, not committed tests.

import threading  # noqa: E402


def _no_dangling_merge_state(repo) -> None:
    git_dir = Path(repo.path, ".git")
    assert not (git_dir / "MERGE_HEAD").exists(), "dangling MERGE_HEAD left behind"
    assert not (git_dir / "index.lock").exists(), "stale index.lock left behind"


def test_concurrent_merges_all_land_no_dangling_state(tmp_path):
    """Concurrent non-conflicting merges serialize: every one lands and the
    backing repo is left clean (per-repo RLock + _cleanup_worktree)."""
    backend = FakeGitHubBackend.with_git_repo(tmp_path / "gh")
    n = 6
    prs = [backend.add_pr(head=f"feat-{i}", files={f"f{i}.txt": f"{i}\n"})
           for i in range(n)]

    barrier = threading.Barrier(n)
    results: dict[int, int] = {}
    results_lock = threading.Lock()

    def worker(pr):
        barrier.wait()  # maximize the collision window
        res = gh_ops.merge_pr("/tmp/repo", pr.number)
        with results_lock:
            results[pr.number] = res.returncode

    with backend.installed():
        threads = [threading.Thread(target=worker, args=(pr,)) for pr in prs]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    assert all(rc == 0 for rc in results.values()), results
    for pr in prs:
        assert backend.git_repo.is_merged(pr.head) is True
    _no_dangling_merge_state(backend.git_repo)


def test_concurrent_conflicting_merges_yield_one_winner(tmp_path):
    """Two PRs touching the same file merged concurrently → exactly one winner
    plus one conflict-shaped rc=1, base reflects only the winner, no dangling
    merge state."""
    backend = FakeGitHubBackend.with_git_repo(tmp_path / "gh")
    a = backend.add_pr(head="feat-a", files={"shared.txt": "from A\n"})
    b = backend.add_pr(head="feat-b", files={"shared.txt": "from B\n"})

    barrier = threading.Barrier(2)
    results: dict[int, subprocess.CompletedProcess] = {}
    results_lock = threading.Lock()

    def worker(pr):
        barrier.wait()
        res = gh_ops.merge_pr("/tmp/repo", pr.number)
        with results_lock:
            results[pr.number] = res

    with backend.installed():
        threads = [threading.Thread(target=worker, args=(p,)) for p in (a, b)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    codes = sorted(r.returncode for r in results.values())
    assert codes == [0, 1], {n: r.returncode for n, r in results.items()}
    loser = next(r for r in results.values() if r.returncode == 1)
    assert "conflict" in loser.stderr.lower()
    # exactly one of the two is merged into base; the other stays OPEN
    merged = [pr for pr in (a, b) if backend.git_repo.is_merged(pr.head)]
    assert len(merged) == 1
    _no_dangling_merge_state(backend.git_repo)


def test_concurrent_installs_restore_to_none_baseline():
    """An interleaved enter(T1)/enter(T2)/exit(T1)/exit(T2) across threads must
    leave the global transport at the None baseline.

    This is the exact save/restore race the depth counter fixes: with a naive
    ``finally: _GH_RUNNER = prev`` the last exit (T2) would reinstate T1's
    already-departed runner and leak it past join. The events below pin the
    interleaving so the regression is caught deterministically, not by luck.
    """
    assert gh_ops._GH_RUNNER is None
    r1 = lambda argv, cwd: _completed_stub()
    r2 = lambda argv, cwd: _completed_stub()
    t1_entered = threading.Event()
    t2_entered = threading.Event()
    t1_may_exit = threading.Event()
    t1_exited = threading.Event()

    def t1():
        with gh_ops.gh_runner(r1):
            t1_entered.set()
            t2_entered.wait()      # T2 enters while T1 still holds (nested)
            t1_may_exit.wait()
        t1_exited.set()            # T1 has restored

    def t2():
        t1_entered.wait()          # enter strictly after T1
        with gh_ops.gh_runner(r2):
            t2_entered.set()
            t1_may_exit.set()      # let T1 exit first (the interleave)
            t1_exited.wait()       # T2 exits only after T1 has

    th1, th2 = threading.Thread(target=t1), threading.Thread(target=t2)
    th1.start()
    th2.start()
    th1.join()
    th2.join()

    assert gh_ops._GH_RUNNER is None
    assert gh_ops._GH_RUNNER_DEPTH == 0


def _completed_stub():
    return subprocess.CompletedProcess(["gh"], 0, "", "")
