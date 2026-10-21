"""``pm pr merge`` publishes only the signed-off candidate (pr-ac10f03).

Real git repositories throughout: sign-off's integration check records the
candidate (PR HEAD merged with the fetched base), the approval binds to it,
and the merge re-fetches, recomputes and publishes it with a
compare-and-swap on the base revision.  Anything that moved refuses the
merge, invalidates the approval (back to sign-off) and leaves the base
untouched; no conflict-resolution window is ever opened.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
from click.testing import CliRunner

from pm_core import integration, signoff, store
from pm_core.cli import pr as pr_mod

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
    with mock.patch("pm_core.paths.captures_root", return_value=croot), \
         mock.patch.object(pr_mod, "trigger_tui_refresh"), \
         mock.patch.object(pr_mod, "trigger_tui_restart"):
        yield


def _state(tmp_path, project: dict, pr: dict) -> Path:
    pm_dir = tmp_path / "pmstate"
    pm_dir.mkdir(exist_ok=True)
    store.save({"project": {"name": "proj", "base_branch": "master",
                            **project},
                "prs": [{"id": PR, "title": "PR one", "branch": BRANCH,
                         "status": "sign_off", **pr}],
                "plans": []}, pm_dir)
    return pm_dir


def approve(w) -> dict:
    """What sign-off does: integration check, then a bound SIGNOFF_MERGE."""
    rec = integration.check_integration(w.pm_dir, PR)
    assert rec["status"] in integration.MERGEABLE, rec
    signoff.record_signoff_verdict(
        w.pm_dir, PR, signoff.SIGNOFF_MERGE, rec["head"], "auto-sequence",
        integration=integration.binding(rec))
    return rec


def merge(w, *extra):
    """Run ``pm pr merge``; return (result, merge-window calls, finalized)."""
    with mock.patch.object(pr_mod, "state_root", return_value=w.pm_dir), \
         mock.patch.object(pr_mod, "_launch_merge_window") as launch, \
         mock.patch.object(pr_mod, "_finalize_merge") as finalize:
        result = CliRunner().invoke(pr_mod.pr, ["merge", *extra, PR])
    return result, launch.call_args_list, finalize.called


def pr_entry(w) -> dict:
    return store.get_pr(store.load(w.pm_dir), PR)


# --- local backend ---------------------------------------------------------

@pytest.fixture
def local(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "master")
    commit(repo, "shared.txt", "base\n", "init")
    wd = tmp_path / "home" / ".pm" / "workdirs" / "proj" / PR
    git(tmp_path, "clone", "-q", str(repo), str(wd))
    git(wd, "checkout", "-q", "-b", BRANCH)
    head = commit(wd, "feature.txt", "feature\n", "feature")
    pm_dir = _state(tmp_path, {"repo": str(repo), "backend": "local"},
                    {"workdir": str(wd)})
    return SimpleNamespace(repo=repo, wd=wd, pm_dir=pm_dir, head=head,
                           tmp=tmp_path)


def test_local_publishes_the_approved_candidate(local):
    rec = approve(local)
    result, windows, finalized = merge(local)
    assert result.exit_code == 0, result.output
    assert finalized and windows == []
    tip = git(local.repo, "rev-parse", "master")
    parents = git(local.repo, "rev-list", "--parents", "-n1", tip).split()[1:]
    assert parents == [rec["base_sha"], local.head]
    assert git(local.repo, "rev-parse", "master^{tree}") == rec["candidate_tree"]
    # The PR worktree stays on its branch, untouched.
    assert git(local.wd, "rev-parse", "--abbrev-ref", "HEAD") == BRANCH
    assert git(local.wd, "rev-parse", "HEAD") == local.head


def test_local_moved_base_integrates_without_changing_the_pr_head(local):
    """Unchanged PR HEAD + moved base: sign-off approves the separate
    candidate; merge publishes exactly it."""
    other = commit(local.repo, "other.txt", "other\n", "other PR merged")
    rec = approve(local)
    assert rec["status"] == integration.CLEAN
    assert rec["base_sha"] == other
    result, windows, finalized = merge(local)
    assert result.exit_code == 0, result.output
    assert finalized and windows == []
    assert git(local.repo, "rev-parse", "master^{tree}") == rec["candidate_tree"]
    assert (local.repo / "feature.txt").exists()
    assert (local.repo / "other.txt").exists()
    assert git(local.wd, "rev-parse", "HEAD") == local.head


def test_local_base_moved_after_approval_returns_to_signoff(local):
    approve(local)
    moved = commit(local.repo, "other.txt", "other\n", "merged after sign-off")
    result, windows, finalized = merge(local)
    assert result.exit_code != 0
    assert "moved since sign-off" in result.output
    assert "returned to sign-off" in result.output
    assert windows == [] and not finalized
    assert git(local.repo, "rev-parse", "master") == moved   # untouched
    rec = pr_entry(local)["signoff"]
    assert rec["invalidated"]
    assert signoff.fresh_recorded_verdict(pr_entry(local), local.head) is None
    # A retry is refused by the record gate itself.
    result, _, _ = merge(local)
    assert result.exit_code != 0 and "no longer valid" in result.output


def test_local_base_moving_during_publication_is_refused(local):
    """The base moves between validation and the final update (another
    publisher won the race): the compare-and-swap refuses."""
    approve(local)
    real = integration.build_merge_commit
    racing = {}

    def build_then_race(*a, **kw):
        out = real(*a, **kw)
        racing["sha"] = commit(local.repo, "race.txt", "race\n", "racing merge")
        return out

    with mock.patch.object(integration, "build_merge_commit", build_then_race):
        result, windows, finalized = merge(local)
    assert result.exit_code != 0
    assert "moved during the merge" in result.output
    assert windows == [] and not finalized
    assert git(local.repo, "rev-parse", "master") == racing["sha"]
    assert pr_entry(local)["signoff"]["invalidated"]


def test_local_base_moving_before_fast_forward_is_refused(local):
    """The checked-out base moves after the CAS check, right before the
    fast-forward: the failed ff returns the PR to sign-off (not "re-run")."""
    approve(local)
    real = pr_mod.git_ops.run_git
    racing = {}

    def run_git(*args, **kw):
        if args[:2] == ("merge", "--ff-only") and not racing:
            racing["sha"] = commit(local.repo, "race.txt", "race\n", "race")
        return real(*args, **kw)

    with mock.patch.object(pr_mod.git_ops, "run_git", run_git):
        result, windows, finalized = merge(local)
    assert result.exit_code != 0
    assert "moved during the merge" in result.output
    assert windows == [] and not finalized
    assert git(local.repo, "rev-parse", "master") == racing["sha"]
    assert pr_entry(local)["signoff"]["invalidated"]


def test_local_main_repo_on_other_branch_updates_ref(local):
    git(local.repo, "checkout", "-q", "-b", "user-work")
    rec = approve(local)
    result, _, finalized = merge(local)
    assert result.exit_code == 0, result.output
    assert finalized
    assert git(local.repo, "rev-parse", "--abbrev-ref", "HEAD") == "user-work"
    assert git(local.repo, "rev-parse", "master^{tree}") == rec["candidate_tree"]


def test_local_dirty_main_repo_is_preserved(local):
    (local.repo / "shared.txt").write_text("user edit\n")
    approve(local)
    result, _, finalized = merge(local)
    assert result.exit_code == 0, result.output
    assert finalized
    assert (local.repo / "shared.txt").read_text() == "user edit\n"
    assert (local.repo / "feature.txt").exists()


def test_head_moved_after_approval_is_stale(local):
    approve(local)
    commit(local.wd, "late.txt", "late\n", "unreviewed commit")
    result, windows, _ = merge(local)
    assert result.exit_code != 0
    assert "stale" in result.output
    assert windows == []


def test_conflicting_integration_never_publishes(local):
    commit(local.wd, "shared.txt", "pr side\n", "pr edits shared")
    commit(local.repo, "shared.txt", "base side\n", "base edits shared")
    rec = integration.check_integration(local.pm_dir, PR)
    assert rec["status"] == integration.CONFLICT
    assert rec["conflicts"] == ["shared.txt"]
    # The PR worktree was never touched by the check.
    assert git(local.wd, "status", "--porcelain") == ""
    assert subprocess.run(["git", "rev-parse", "-q", "--verify", "MERGE_HEAD"],
                          cwd=local.wd).returncode != 0
    assert git(local.wd, "worktree", "list").count("\n") == 0
    # Even a (forged) MERGE bound to it is refused.
    signoff.record_signoff_verdict(
        local.pm_dir, PR, signoff.SIGNOFF_MERGE, rec["head"], "manual",
        integration=integration.binding(rec))
    before = git(local.repo, "rev-parse", "master")
    result, windows, _ = merge(local)
    assert result.exit_code != 0
    assert "conflict-free" in result.output
    assert windows == []
    assert git(local.repo, "rev-parse", "master") == before


def test_legacy_approval_is_refused(local):
    signoff.record_signoff_verdict(local.pm_dir, PR, signoff.SIGNOFF_MERGE,
                                   local.head, "auto-sequence")
    result, _, _ = merge(local)
    assert result.exit_code != 0
    assert "predates integration-aware sign-off" in result.output


def test_no_signoff_check_only_recovers(local):
    before = git(local.repo, "rev-parse", "master")
    result, _, finalized = merge(local, "--no-signoff-check")
    assert result.exit_code != 0
    assert "only recover an already-completed merge" in result.output
    assert not finalized
    assert git(local.repo, "rev-parse", "master") == before
    # After a real publish (finalize interrupted), recovery finalizes.
    approve(local)
    result, _, _ = merge(local)
    assert result.exit_code == 0, result.output
    for flag in ("--no-signoff-check", "--propagation-only"):
        result, _, finalized = merge(local, flag)
        assert result.exit_code == 0, result.output
        assert "already in master" in result.output and finalized


# --- vanilla backend (bare remote, atomic lease) --------------------------

@pytest.fixture
def vanilla(tmp_path):
    upstream = tmp_path / "upstream.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "master", str(upstream))
    seed = tmp_path / "seed"
    git(tmp_path, "clone", "-q", str(upstream), str(seed))
    git(seed, "checkout", "-q", "-b", "master")
    commit(seed, "shared.txt", "base\n", "init")
    git(seed, "push", "-q", "origin", "master")
    main = tmp_path / "main"
    git(tmp_path, "clone", "-q", str(upstream), str(main))
    wd = tmp_path / "home" / ".pm" / "workdirs" / "proj" / PR
    git(tmp_path, "clone", "-q", str(upstream), str(wd))
    git(wd, "checkout", "-q", "-b", BRANCH)
    head = commit(wd, "feature.txt", "feature\n", "feature")
    pm_dir = _state(tmp_path, {"repo": str(main), "backend": "vanilla"},
                    {"workdir": str(wd)})
    return SimpleNamespace(upstream=upstream, seed=seed, main=main, wd=wd,
                           pm_dir=pm_dir, head=head)


def test_vanilla_pushes_candidate_and_updates_main_repo(vanilla):
    rec = approve(vanilla)
    assert rec["target_repo"] == str(vanilla.upstream)
    result, windows, finalized = merge(vanilla)
    assert result.exit_code == 0, result.output
    assert finalized and windows == []
    tip = git(vanilla.upstream, "rev-parse", "master")
    assert git(vanilla.upstream, "rev-parse", "master^{tree}") == rec["candidate_tree"]
    assert git(vanilla.main, "rev-parse", "master") == tip


def test_vanilla_base_moving_during_push_is_refused(vanilla):
    approve(vanilla)
    real = integration.build_merge_commit
    racing = {}

    def build_then_race(*a, **kw):
        out = real(*a, **kw)
        racing["sha"] = commit(vanilla.seed, "race.txt", "race\n", "race")
        git(vanilla.seed, "push", "-q", "origin", "master")
        return out

    with mock.patch.object(integration, "build_merge_commit", build_then_race):
        result, windows, finalized = merge(vanilla)
    assert result.exit_code != 0
    assert "moved during the merge" in result.output
    assert windows == [] and not finalized
    assert git(vanilla.upstream, "rev-parse", "master") == racing["sha"]
    assert pr_entry(vanilla)["signoff"]["invalidated"]


def test_vanilla_base_moved_after_approval_is_refused(vanilla):
    approve(vanilla)
    moved = commit(vanilla.seed, "other.txt", "o\n", "other")
    git(vanilla.seed, "push", "-q", "origin", "master")
    result, windows, _ = merge(vanilla)
    assert result.exit_code != 0
    assert "moved since sign-off" in result.output
    assert windows == []
    assert git(vanilla.upstream, "rev-parse", "master") == moved


def test_vanilla_post_publish_pull_failure_opens_recovery_window_only(vanilla):
    """Updating the main checkout after publication is recovery: its
    window may open, but the publication already happened exactly once."""
    commit(vanilla.main, "local.txt", "x\n", "unpushed local master commit")
    rec = approve(vanilla)
    result, windows, finalized = merge(vanilla, "--resolve-window")
    assert result.exit_code == 0, result.output
    assert not finalized
    assert len(windows) == 1
    assert windows[0].kwargs["cwd"] == str(vanilla.main)
    assert git(vanilla.upstream, "rev-parse", "master^{tree}") == rec["candidate_tree"]


# --- github backend (git-backed fake) -------------------------------------

@pytest.fixture
def github(tmp_path, fake_github_repo):
    remote = Path(fake_github_repo.git_repo.path)
    wd = tmp_path / "home" / ".pm" / "workdirs" / "proj" / PR
    git(tmp_path, "clone", "-q", str(remote), str(wd))
    git(wd, "checkout", "-q", "-b", BRANCH)
    head = commit(wd, "feature.txt", "feature\n", "feature")
    git(wd, "push", "-q", "origin", f"{BRANCH}:refs/heads/{BRANCH}")
    gh_pr = fake_github_repo.add_pr(title="PR one", head=BRANCH)
    main = tmp_path / "main"
    git(tmp_path, "clone", "-q", str(remote), str(main))
    pm_dir = _state(tmp_path, {"repo": str(main), "backend": "github"},
                    {"workdir": str(wd), "gh_pr_number": gh_pr.number})
    with mock.patch("pm_core.paths.fake_github_active", return_value=True):
        yield SimpleNamespace(fake=fake_github_repo, remote=remote, wd=wd,
                              main=main, pm_dir=pm_dir, head=head, pr=gh_pr)


def _gh_merge_calls(fake):
    return [c for c in fake.calls if c[:2] == ["pr", "merge"]]


def test_github_merges_pinned_to_the_approved_head(github):
    rec = approve(github)
    result, windows, finalized = merge(github)
    assert result.exit_code == 0, result.output
    assert finalized and windows == []
    assert github.pr.state == "MERGED"
    calls = _gh_merge_calls(github.fake)
    assert calls and "--match-head-commit" in calls[-1]
    assert calls[-1][calls[-1].index("--match-head-commit") + 1] == github.head
    assert git(github.remote, "rev-parse", "master^{tree}") == rec["candidate_tree"]
    assert "merge_integrity" not in pr_entry(github)
    assert git(github.main, "rev-parse", "master") == \
        git(github.remote, "rev-parse", "master")


def test_github_pushes_unpushed_approved_head_first(github):
    head = commit(github.wd, "more.txt", "more\n", "approved, not pushed")
    approve(github)
    result, _, finalized = merge(github)
    assert result.exit_code == 0, result.output
    assert finalized
    assert git(github.remote, "merge-base", "--is-ancestor", head,
               "master") == ""


def test_github_unapproved_remote_commits_are_refused(github):
    approve(github)
    other = github.wd.parent / "other-clone"
    git(github.wd.parent, "clone", "-q", "-b", BRANCH, str(github.remote),
        str(other))
    commit(other, "sneak.txt", "x\n", "pushed after sign-off")
    git(other, "push", "-q", "origin", BRANCH)
    result, _, _ = merge(github)
    assert result.exit_code != 0
    assert "not signed off" in result.output
    assert github.pr.state == "OPEN"
    assert _gh_merge_calls(github.fake) == []


def test_github_base_moved_after_approval_is_refused(github):
    approve(github)
    other = github.wd.parent / "base-clone"
    git(github.wd.parent, "clone", "-q", str(github.remote), str(other))
    # The fake remote is a non-bare repo with master checked out, so move
    # its base in place (as another GitHub merge would).
    commit(github.remote, "base2.txt", "b\n", "another PR merged")
    result, windows, _ = merge(github)
    assert result.exit_code != 0
    assert "moved since sign-off" in result.output
    assert windows == []
    assert github.pr.state == "OPEN"
    assert _gh_merge_calls(github.fake) == []


def test_github_unreadable_base_keeps_the_approval(github):
    """A failed ls-remote of the base is "unknown", not "moved": nothing is
    merged and the approval stays valid for a retry."""
    approve(github)
    real = integration.remote_ref

    def flaky(workdir, target, ref):
        return None if ref == "refs/heads/master" else real(workdir, target, ref)

    with mock.patch.object(integration, "remote_ref", side_effect=flaky):
        result, windows, finalized = merge(github)
    assert result.exit_code != 0
    assert "cannot read master" in result.output
    assert not finalized and windows == []
    assert _gh_merge_calls(github.fake) == []
    assert not pr_entry(github)["signoff"].get("invalidated")


def test_github_merge_onto_a_moved_base_is_recorded(github):
    """GitHub has no base precondition: a merge that landed on another base
    is detected afterwards and recorded on ``merge_integrity``."""
    from pm_core import gh_ops
    rec = approve(github)
    orig = gh_ops.merge_pr

    def merge_after_base_moves(workdir, number, **kw):
        commit(github.remote, "late.txt", "l\n", "landed during the merge")
        return orig(workdir, number, **kw)

    with mock.patch.object(gh_ops, "merge_pr", side_effect=merge_after_base_moves):
        result, _, _ = merge(github)
    assert result.exit_code == 0, result.output
    integrity = pr_entry(github).get("merge_integrity")
    assert integrity and "not the signed-off base" in integrity["problem"]
    assert rec["base_sha"][:12] in integrity["problem"]


def test_two_overlapping_prs_second_needs_integration(local, tmp_path):
    """Merging the first PR makes the second's approval stale; its fresh
    integration check finds the conflict (-> implementation), and after the
    branch reconciles the base a new approval publishes cleanly."""
    # PR 1 (this fixture's PR) and PR 2 both edit shared.txt.
    commit(local.wd, "shared.txt", "pr1\n", "pr1 edits shared")
    wd2 = tmp_path / "home" / ".pm" / "workdirs" / "proj" / "pr-002"
    git(tmp_path, "clone", "-q", str(local.repo), str(wd2))
    git(wd2, "checkout", "-q", "-b", "pm/pr-002")
    commit(wd2, "shared.txt", "pr2\n", "pr2 edits shared")

    def _add_pr2(d):
        d["prs"].append({"id": "pr-002", "title": "PR two",
                         "branch": "pm/pr-002", "status": "sign_off",
                         "workdir": str(wd2)})
    store.locked_update(local.pm_dir, _add_pr2)

    def approve2():
        rec = integration.check_integration(local.pm_dir, "pr-002")
        if rec["status"] in integration.MERGEABLE:
            signoff.record_signoff_verdict(
                local.pm_dir, "pr-002", signoff.SIGNOFF_MERGE, rec["head"],
                "auto-sequence", integration=integration.binding(rec))
        return rec

    assert approve2()["status"] == integration.UP_TO_DATE
    approve(local)
    result, _, _ = merge(local)                 # PR 1 lands
    assert result.exit_code == 0, result.output

    def merge2():
        with mock.patch.object(pr_mod, "state_root", return_value=local.pm_dir), \
             mock.patch.object(pr_mod, "_launch_merge_window") as launch, \
             mock.patch.object(pr_mod, "_finalize_merge"):
            r = CliRunner().invoke(pr_mod.pr, ["merge", "pr-002"])
        return r, launch.call_args_list

    result, windows = merge2()                  # stale: base moved
    assert result.exit_code != 0 and "moved since sign-off" in result.output
    assert windows == []
    rec = approve2()                            # fresh sign-off check
    assert rec["status"] == integration.CONFLICT
    verdict, why = signoff.effective_verdict(signoff.SIGNOFF_MERGE, rec,
                                             rec["head"])
    assert verdict == signoff.SIGNOFF_IMPL and "conflicts" in why
    # Implementation reconciles the base in the PR branch.
    git(wd2, "fetch", "-q", str(local.repo), "master")
    subprocess.run(["git", "merge", "-q", "FETCH_HEAD"], cwd=wd2,
                   capture_output=True)
    (wd2 / "shared.txt").write_text("pr1\npr2\n")
    git(wd2, "add", "shared.txt")
    git(wd2, "commit", "-q", "-m", "reconcile master")
    rec = approve2()
    assert rec["status"] == integration.UP_TO_DATE
    result, windows = merge2()
    assert result.exit_code == 0, result.output
    assert windows == []
    assert (local.repo / "shared.txt").read_text() == "pr1\npr2\n"
