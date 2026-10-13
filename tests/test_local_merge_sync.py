"""Local-backend ``pm pr merge`` against real git repos (pr-e835d8f, pr-a75da60).

The PR workdir's base branch goes stale as soon as another PR merges into
the main repo.  Before the fix the merge was made onto that stale copy, so
the fast-forward into the main repo failed and pm opened the conflict
resolution window in the main repo — a directory pm does not trust for
unattended sessions, where Claude sat at the workspace-trust prompt.  Now
the workdir's base is refreshed from the main repo first, so independent
PRs merge cleanly and real conflicts are resolved in the PR workdir.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
from click.testing import CliRunner

from pm_core import store
from pm_core.cli import pr as pr_mod


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


def commit(cwd: Path, name: str, text: str, msg: str) -> None:
    (cwd / name).write_text(text)
    git(cwd, "add", name)
    git(cwd, "commit", "-q", "-m", msg)


@pytest.fixture
def project(tmp_path, monkeypatch):
    """Main repo + two PR workdirs cloned from it (local backend)."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    for k, v in {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                 "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}.items():
        monkeypatch.setenv(k, v)
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "master")
    commit(repo, "shared.txt", "base\n", "init")

    workdirs = tmp_path / "home" / ".pm" / "workdirs" / "proj"
    workdirs.mkdir(parents=True)
    prs = []
    for n in (1, 2):
        wd = workdirs / f"pr-00{n}"
        git(tmp_path, "clone", "-q", str(repo), str(wd))
        git(wd, "checkout", "-q", "-b", f"pm/pr-00{n}")
        prs.append({"id": f"pr-00{n}", "title": f"PR {n}",
                    "branch": f"pm/pr-00{n}", "status": "in_review",
                    "workdir": str(wd)})
    pm_dir = tmp_path / "pmstate"
    pm_dir.mkdir()
    store.save({"project": {"name": "proj", "repo": str(repo),
                            "base_branch": "master", "backend": "local"},
                "prs": prs, "plans": []}, pm_dir)
    return SimpleNamespace(repo=repo, pm_dir=pm_dir,
                           wd1=Path(prs[0]["workdir"]),
                           wd2=Path(prs[1]["workdir"]))


def merge(project, pr_id, *extra):
    """Run ``pm pr merge`` and return (result, merge-window calls, finalized)."""
    with mock.patch.object(pr_mod, "state_root", return_value=project.pm_dir), \
         mock.patch.object(pr_mod, "_launch_merge_window") as launch, \
         mock.patch.object(pr_mod, "_finalize_merge") as finalize:
        result = CliRunner().invoke(
            pr_mod.pr, ["merge", "--no-signoff-check", *extra, pr_id])
    return result, launch.call_args_list, finalize.called


def window_cwd(call, project, pr_id) -> str:
    """Directory the merge window would run in (None means the PR workdir)."""
    pr = store.get_pr(store.load(project.pm_dir), pr_id)
    return call.kwargs.get("cwd") or pr["workdir"]


def test_second_independent_pr_merges_without_a_window(project):
    """pr-a75da60: two independent PRs; the second merge used to fail the
    fast-forward and open a resolution window for a trivially mergeable PR."""
    commit(project.wd1, "one.txt", "1\n", "pr1")
    commit(project.wd2, "two.txt", "2\n", "pr2")

    r1, w1, f1 = merge(project, "pr-001", "--resolve-window")
    assert r1.exit_code == 0 and f1 and not w1, r1.output
    r2, w2, f2 = merge(project, "pr-002", "--resolve-window")
    assert r2.exit_code == 0, r2.output
    assert not w2, f"opened a merge window: {w2}"
    assert f2
    assert (project.repo / "one.txt").exists()
    assert (project.repo / "two.txt").exists()


def test_conflict_resolves_in_pr_workdir_not_main_repo(project):
    """pr-e835d8f: a real conflict opens the window in the PR workdir (a
    pm workdir that pm trusts), never in the main repo, and leaves the main
    repo — including the user's uncommitted work — untouched."""
    commit(project.wd1, "shared.txt", "one\n", "pr1")
    commit(project.wd2, "shared.txt", "two\n", "pr2")
    r1, _, _ = merge(project, "pr-001")
    assert r1.exit_code == 0, r1.output
    (project.repo / "notes.txt").write_text("user's own work\n")
    head_before = git(project.repo, "rev-parse", "HEAD")

    r2, windows, finalized = merge(project, "pr-002", "--resolve-window")
    assert r2.exit_code == 0, r2.output
    assert len(windows) == 1
    assert window_cwd(windows[0], project, "pr-002") == str(project.wd2)
    assert "CONFLICT" in windows[0].args[2]
    assert not finalized
    assert git(project.repo, "rev-parse", "HEAD") == head_before
    assert (project.repo / "notes.txt").read_text() == "user's own work\n"
    # The failed merge was aborted: the workdir is clean for Claude.
    assert git(project.wd2, "status", "--porcelain") == ""


def test_resolved_workdir_merge_propagates(project):
    """After the conflict is resolved in the workdir, propagation
    fast-forwards the main repo to the resolved merge."""
    commit(project.wd1, "shared.txt", "one\n", "pr1")
    commit(project.wd2, "shared.txt", "two\n", "pr2")
    merge(project, "pr-001")
    merge(project, "pr-002", "--resolve-window")
    # What the resolution session does in the PR workdir:
    wd = project.wd2
    git(wd, "fetch", "-q", str(project.repo), "master")
    subprocess.run(["git", "merge", "FETCH_HEAD"], cwd=wd, capture_output=True)
    subprocess.run(["git", "merge", "pm/pr-002"], cwd=wd, capture_output=True)
    (wd / "shared.txt").write_text("one\ntwo\n")
    git(wd, "commit", "-qam", "resolve")

    r, windows, finalized = merge(project, "pr-002", "--propagation-only",
                                  "--resolve-window")
    assert r.exit_code == 0, r.output
    assert not windows and finalized
    assert (project.repo / "shared.txt").read_text() == "one\ntwo\n"


def test_main_repo_moving_after_workdir_merge_is_integrated(project):
    """The main repo's master gains a commit between the workdir merge and
    propagation: it is merged into the workdir and the fast-forward retried,
    instead of opening a window in the main repo."""
    commit(project.wd2, "two.txt", "2\n", "pr2")
    git(project.wd2, "checkout", "-q", "master")
    git(project.wd2, "merge", "-q", "--no-ff", "pm/pr-002", "-m", "merge pr2")
    commit(project.repo, "user.txt", "u\n", "user commit on master")

    r, windows, finalized = merge(project, "pr-002", "--propagation-only",
                                  "--resolve-window")
    assert r.exit_code == 0, r.output
    assert not windows and finalized
    assert (project.repo / "two.txt").exists()
    assert (project.repo / "user.txt").exists()


def test_main_repo_moving_with_conflict_resolves_in_workdir(project):
    commit(project.wd2, "shared.txt", "two\n", "pr2")
    git(project.wd2, "checkout", "-q", "master")
    git(project.wd2, "merge", "-q", "--no-ff", "pm/pr-002", "-m", "merge pr2")
    commit(project.repo, "shared.txt", "user\n", "user commit on master")
    head_before = git(project.repo, "rev-parse", "HEAD")

    r, windows, finalized = merge(project, "pr-002", "--propagation-only",
                                  "--resolve-window")
    assert r.exit_code == 0, r.output
    assert len(windows) == 1
    assert window_cwd(windows[0], project, "pr-002") == str(project.wd2)
    assert not finalized
    assert git(project.repo, "rev-parse", "HEAD") == head_before


def test_main_repo_on_other_branch_with_moved_master(project):
    """User is on a feature branch in the main repo: master is updated as a
    ref only, after integrating its new commits in the workdir."""
    commit(project.wd2, "two.txt", "2\n", "pr2")
    commit(project.repo, "user.txt", "u\n", "user commit on master")
    git(project.repo, "checkout", "-q", "-b", "feature")
    (project.repo / "wip.txt").write_text("wip\n")

    r, windows, finalized = merge(project, "pr-002", "--resolve-window")
    assert r.exit_code == 0, r.output
    assert not windows and finalized
    assert git(project.repo, "rev-parse", "--abbrev-ref", "HEAD") == "feature"
    assert (project.repo / "wip.txt").read_text() == "wip\n"
    tree = git(project.repo, "ls-tree", "--name-only", "master")
    assert "two.txt" in tree and "user.txt" in tree


def test_local_merge_prompt_names_main_repo_sync(project):
    """The resolution prompt tells Claude its result must also contain the
    main repo's base (or the fast-forward fails again) and to leave the
    main repo alone."""
    from pm_core import prompt_gen
    data = store.load(project.pm_dir)
    prompt = prompt_gen.generate_merge_prompt(
        data, "pr-002", "CONFLICT (content)", main_repo=str(project.repo))
    assert f"git fetch {project.repo} master && git merge FETCH_HEAD" in prompt
    assert "Do not change the main repo directory" in prompt
