"""Tests for pm_core.workdirs — recovering a PR's stale workdir record.

Real git repositories in a temp HOME stand in for a project's workdirs dir:
the identity checks (own repo, root commit, checked-out branch) are what
keep the recovery from adopting the wrong clone, so they are not mocked.
"""

import os
import subprocess
from pathlib import Path
from unittest import mock

import pytest
import yaml
from click.testing import CliRunner

from pm_core import store, workdirs, git_ops
from pm_core.cli import helpers
from pm_core.cli import pr as pr_mod

BRANCH = "pm/pr-6aa74c6-fuzzy-select-for-pr-and-plan-command-ab"
SLUG = store.slugify(BRANCH.replace("/", "-"))
PR_ID = "pr-6aa74c6"


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd), check=True,
                          capture_output=True, text=True).stdout.strip()


def _snapshot(path: Path) -> dict:
    """Everything recovery must leave untouched in a workdir."""
    return {
        "status": git(path, "status", "--porcelain=v1", "--untracked-files=all"),
        "stash": git(path, "stash", "list"),
        "head": git(path, "rev-parse", "HEAD"),
        "branch": git(path, "symbolic-ref", "-q", "HEAD"),
        "files": sorted(str(p.relative_to(path)) for p in path.rglob("*")
                        if ".git" not in p.parts),
    }


def _other_pr_registry(env, other: Path, other_branch: str):
    """Give *other* (a clone of another PR) a tracked pm/project.yaml
    listing that PR, committed, as a PR clone's registry is; return
    ``(registry dir, its data, this PR's entry in it)``."""
    inner = other / "pm"
    inner.mkdir()
    data, _ = env.fresh()
    data["prs"].append({"id": "pr-c000001", "title": "Other",
                        "branch": other_branch, "status": "in_progress"})
    store.save(data, inner)
    git(other, "add", "pm")
    git(other, "commit", "-q", "-m", "registry")
    data = store.load(inner)
    return inner, data, store.get_pr(data, PR_ID)


@pytest.fixture
def env(tmp_path, monkeypatch):
    """An origin repo, a pm project recorded with a stale workdir, and an
    empty project workdirs dir under a temp HOME."""
    monkeypatch.setenv("GIT_AUTHOR_NAME", "t")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "t@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "t")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "t@example.com")
    origin = tmp_path / "origin"
    origin.mkdir()
    git(origin, "init", "-q", "-b", "master")
    (origin / "README").write_text("hi\n")
    git(origin, "add", "README")
    git(origin, "commit", "-q", "-m", "root")
    repo_id = git(origin, "rev-list", "--max-parents=0", "HEAD")

    base = tmp_path / "home" / ".pm" / "workdirs"
    base.mkdir(parents=True)
    monkeypatch.setattr("pm_core.paths.workdirs_base", lambda: base)

    stale = ("/home/someone-else/.pm/workdirs/project-manager-"
             f"{repo_id[:8]}/{SLUG}-ab512a43")
    data = {
        "project": {"name": "project-manager", "repo": str(origin),
                    "repo_id": repo_id, "base_branch": "master",
                    "backend": "vanilla"},
        "plans": [],
        "prs": [{"id": PR_ID, "title": "Fuzzy select", "branch": BRANCH,
                 "status": "in_progress", "workdir": stale}],
    }
    root = tmp_path / "pm"
    root.mkdir()
    store.save(data, root)
    project_dir = base / f"project-manager-{repo_id[:8]}"

    def clone(name, branch=BRANCH, src=origin):
        dest = project_dir / name
        project_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "-q", str(src), str(dest)],
                       check=True, capture_output=True)
        if branch:
            git(dest, "checkout", "-q", "-b", branch)
        return dest

    def fresh():
        d = store.load(root)
        return d, store.get_pr(d, PR_ID)

    return type("Env", (), dict(origin=origin, repo_id=repo_id, base=base,
                                project_dir=project_dir, root=root,
                                stale=stale, clone=staticmethod(clone),
                                fresh=staticmethod(fresh)))


class TestFastPath:
    def test_existing_record_returned_without_git_or_scan(self, env,
                                                          tmp_path):
        wd = tmp_path / "recorded"
        wd.mkdir()
        env.clone(f"{SLUG}-10e74920")  # would match, must not be looked at
        data, pr = env.fresh()
        pr["workdir"] = str(wd)
        with mock.patch.object(workdirs, "_git",
                               side_effect=AssertionError("git ran")), \
             mock.patch.object(workdirs, "_name_matches",
                               side_effect=AssertionError("scanned")), \
             mock.patch.object(workdirs, "workdir_lock",
                               side_effect=AssertionError("locked")):
            res = workdirs.resolve_workdir(data, pr, env.root)
        assert (res.status, res.path) == (workdirs.RECORDED, str(wd))
        assert workdirs.get_workdir(data, pr, env.root) == str(wd)


class TestRecovery:
    def test_stale_record_relinks_clone_with_other_hash(self, env):
        """The pr-6aa74c6 incident: recorded under another HOME with suffix
        ab512a43, the intact clone here has suffix 10e74920."""
        clone = env.clone(f"{SLUG}-10e74920")
        data, pr = env.fresh()
        res = workdirs.resolve_workdir(data, pr, env.root)
        assert res.status == workdirs.RECOVERED
        assert res.path == str(clone)
        assert res.recorded == env.stale
        assert pr["workdir"] == str(clone)
        # persisted, so the next access takes the fast path
        assert env.fresh()[1]["workdir"] == str(clone)
        assert "re-linked" in res.describe()

    def test_missing_field_is_recovered_too(self, env):
        clone = env.clone(f"{SLUG}-10e74920")
        data, pr = env.fresh()
        pr["workdir"] = None
        assert workdirs.get_workdir(data, pr) == str(clone)
        # no root -> in-memory only
        assert env.fresh()[1]["workdir"] == env.stale

    def test_persist_false_writes_nothing(self, env):
        env.clone(f"{SLUG}-10e74920")
        data, pr = env.fresh()
        workdirs.resolve_workdir(data, pr, env.root, persist=False)
        assert env.fresh()[1]["workdir"] == env.stale

    def test_bare_slug_name_without_hash(self, env):
        clone = env.clone(SLUG)
        data, pr = env.fresh()
        assert workdirs.get_workdir(data, pr, env.root) == str(clone)

    def test_truncated_slug_ending_in_hyphen(self, env):
        """slugify truncates to 50 chars after stripping, so a slug can end
        in '-' and the clone name has '--' before the hash."""
        branch = "pm/pr-1234567-" + "a" * 35 + "-tail"
        assert workdirs.branch_slug(branch).endswith("-")
        clone = env.clone(workdirs.workdir_name(branch, "10e74920"),
                          branch=branch)
        assert "--10e74920" in clone.name
        data, pr = env.fresh()
        pr["branch"] = branch
        assert workdirs.get_workdir(data, pr) == str(clone)

    def test_dirty_index_untracked_stash_and_evidence_untouched(self, env):
        clone = env.clone(f"{SLUG}-10e74920")
        (clone / "clean.txt").write_text("clean\n")
        git(clone, "add", "clean.txt")
        git(clone, "commit", "-q", "-m", "pr work")
        (clone / "stashed.txt").write_text("s\n")
        git(clone, "add", "stashed.txt")
        git(clone, "stash", "push", "-q", "-m", "keep me")
        (clone / "README").write_text("modified\n")          # dirty
        (clone / "staged.txt").write_text("staged\n")
        git(clone, "add", "staged.txt")                       # index
        (clone / "notes.tmp").write_text("untracked\n")       # untracked
        (clone / "pm" / "qa" / "evidence").mkdir(parents=True)
        (clone / "pm" / "qa" / "evidence" / "run.cast").write_text("{}\n")
        before = _snapshot(clone)
        # A clean file with a changed mtime: any index refresh (git status,
        # diff, add) during recovery would rewrite .git/index.
        os.utime(clone / "clean.txt", ns=(10**18, 10**18))
        index = clone / ".git" / "index"
        index_before = (index.read_bytes(), index.stat().st_mtime_ns)

        data, pr = env.fresh()
        assert workdirs.get_workdir(data, pr, env.root) == str(clone)
        assert (index.read_bytes(), index.stat().st_mtime_ns) == index_before
        assert not (clone / ".git" / "index.lock").exists()
        after = _snapshot(clone)
        for key in ("status", "stash", "head", "branch", "files"):
            assert after[key] == before[key], key
        assert "keep me" in after["stash"]
        assert "pm/qa/evidence/run.cast" in after["files"]

    def test_recovery_runs_no_index_writing_git(self, env):
        env.clone(f"{SLUG}-10e74920")
        data, pr = env.fresh()
        seen = []
        real = workdirs._git

        def spy(cwd, *args):
            seen.append(args)
            return real(cwd, *args)

        with mock.patch.object(workdirs, "_git", side_effect=spy):
            workdirs.get_workdir(data, pr, env.root)
        verbs = {a[0] for a in seen}
        assert verbs <= {"rev-parse", "cat-file", "symbolic-ref", "config"}

    def test_mid_rebase_detached_head_is_accepted(self, env):
        clone = env.clone(f"{SLUG}-10e74920")
        git(clone, "checkout", "-q", "--detach")
        (clone / ".git" / "rebase-merge").mkdir()
        (clone / ".git" / "rebase-merge" / "head-name").write_text(
            f"refs/heads/{BRANCH}\n")
        data, pr = env.fresh()
        assert workdirs.get_workdir(data, pr, env.root) == str(clone)

    def test_symlink_alias_is_not_ambiguous(self, env):
        clone = env.clone(f"{SLUG}-10e74920")
        # The alias sorts first; the real directory is still what's recorded.
        (env.project_dir / f"{SLUG}-0000aaaa").symlink_to(clone)
        data, pr = env.fresh()
        res = workdirs.resolve_workdir(data, pr, env.root)
        assert (res.status, res.path) == (workdirs.RECOVERED, str(clone))
        assert env.fresh()[1]["workdir"] == str(clone)

    def test_origin_url_identity_when_repo_id_unknown(self, env):
        data, pr = env.fresh()
        del data["project"]["repo_id"]
        project_dir = workdirs.project_workdirs_dir(data)
        project_dir.mkdir(parents=True)
        clone = project_dir / f"{SLUG}-10e74920"
        subprocess.run(["git", "clone", "-q", str(env.origin), str(clone)],
                       check=True, capture_output=True)
        git(clone, "checkout", "-q", "-b", BRANCH)
        assert workdirs.get_workdir(data, pr) == str(clone)
        git(clone, "remote", "set-url", "origin", "https://example.com/x.git")
        pr["workdir"] = env.stale
        res = workdirs.resolve_workdir(data, pr)
        assert res.status == workdirs.MISSING
        assert "different repository" in res.rejected[0][1]

    def test_origin_url_identity_ignores_ssh_vs_https_spelling(self, env):
        """project.repo and the clone's origin can spell one GitHub repo as
        SSH and HTTPS; a different repo on the same host still differs."""
        data, pr = env.fresh()
        del data["project"]["repo_id"]
        data["project"]["repo"] = "git@github.com:org/project.git"
        project_dir = workdirs.project_workdirs_dir(data)
        project_dir.mkdir(parents=True)
        clone = project_dir / f"{SLUG}-10e74920"
        subprocess.run(["git", "clone", "-q", str(env.origin), str(clone)],
                       check=True, capture_output=True)
        git(clone, "checkout", "-q", "-b", BRANCH)
        git(clone, "remote", "set-url", "origin",
            "https://github.com/org/project/")
        assert workdirs.get_workdir(data, pr) == str(clone)
        git(clone, "remote", "set-url", "origin",
            "https://github.com/org/other.git")
        pr["workdir"] = env.stale
        res = workdirs.resolve_workdir(data, pr)
        assert res.status == workdirs.MISSING
        assert "different repository" in res.rejected[0][1]

    def test_persist_is_compare_and_set(self, env, tmp_path):
        clone = env.clone(f"{SLUG}-10e74920")
        # On-disk record still the stale path: the recovered path is written.
        assert workdirs._persist(env.root, PR_ID, str(clone)) == (
            str(clone), None)
        assert env.fresh()[1]["workdir"] == str(clone)
        # Another writer recorded an existing path meanwhile: it wins and is
        # not overwritten.
        other = tmp_path / "relinked-elsewhere"
        other.mkdir()
        store.locked_update(env.root, lambda d: store.get_pr(d, PR_ID)
                            .__setitem__("workdir", str(other)))
        assert workdirs._persist(env.root, PR_ID, str(clone)) == (
            str(other), None)
        assert env.fresh()[1]["workdir"] == str(other)

    def test_run_from_inside_the_clone_does_not_write_its_project_yaml(
            self, env):
        """pm run from a shell in the PR worktree finds that clone's own
        tracked pm/project.yaml as its root: the clone is used, but the
        re-link is not written there (it would dirty the PR's tree)."""
        clone = env.clone(f"{SLUG}-10e74920")
        inner = clone / "pm"
        inner.mkdir()
        data, pr = env.fresh()
        store.save(data, inner)
        git(clone, "add", "pm")
        git(clone, "commit", "-q", "-m", "registry")
        res = workdirs.resolve_workdir(data, pr, inner)
        assert (res.status, res.path) == (workdirs.RECOVERED, str(clone))
        assert pr["workdir"] == str(clone)
        assert store.get_pr(store.load(inner), PR_ID)["workdir"] == env.stale
        assert git(clone, "status", "--porcelain") == ""
        # Nothing was recorded, so it says "using", not "re-linked".
        text = res.describe()
        assert "using the existing clone" in text, text
        assert "re-linked" not in text
        assert "this clone's own tracked" in text

    def test_run_from_another_prs_clone_does_not_write_its_project_yaml(
            self, env):
        """pm run from a shell in ANOTHER PR's clone (QA S11 story 3):
        that clone's tracked pm/project.yaml is the root.  The clone found
        is used, but the re-link is written into neither clone — it would
        dirty the other PR's tree and block its integrate --apply."""
        clone = env.clone(f"{SLUG}-10e74920")
        other_branch = "pm/pr-c000001-other"
        other = env.clone("pm-pr-c000001-other-10e74920", branch=other_branch)
        inner, data, pr = _other_pr_registry(env, other, other_branch)
        res = workdirs.resolve_workdir(data, pr, inner)
        assert (res.status, res.path) == (workdirs.RECOVERED, str(clone))
        assert pr["workdir"] == str(clone)
        text = res.describe()
        assert "using the existing clone" in text, text
        assert "re-linked" not in text
        assert f"tracked in the clone {other}" in text
        assert store.get_pr(store.load(inner), PR_ID)["workdir"] == env.stale
        assert git(other, "status", "--porcelain") == ""
        assert git(clone, "status", "--porcelain") == ""

    def test_pr_clone_outside_the_workdirs_dir_is_recognised_by_branch(
            self, env, tmp_path):
        """A PR clone mounted elsewhere (a container's /workspace) is not
        under the workdirs dir; its checked-out PR branch gives it away."""
        clone = env.clone(f"{SLUG}-10e74920")
        other_branch = "pm/pr-c000001-other"
        ws = tmp_path / "workspace"
        subprocess.run(["git", "clone", "-q", str(env.origin), str(ws)],
                       check=True, capture_output=True)
        git(ws, "checkout", "-q", "-b", other_branch)
        inner, data, pr = _other_pr_registry(env, ws, other_branch)
        res = workdirs.resolve_workdir(data, pr, inner)
        assert (res.status, res.path) == (workdirs.RECOVERED, str(clone))
        assert os.path.realpath(ws) in res.not_recorded
        assert store.get_pr(store.load(inner), PR_ID)["workdir"] == env.stale
        assert git(ws, "status", "--porcelain") == ""

    def test_main_registry_inside_a_git_repo_is_written(self, env, tmp_path):
        """The main repository (on its base branch, outside the workdirs
        dir) is not a PR clone: the re-link is recorded there."""
        clone = env.clone(f"{SLUG}-10e74920")
        main = tmp_path / "main"
        subprocess.run(["git", "clone", "-q", str(env.origin), str(main)],
                       check=True, capture_output=True)
        inner = main / "pm"
        inner.mkdir()
        data, _ = env.fresh()
        store.save(data, inner)
        data = store.load(inner)
        pr = store.get_pr(data, PR_ID)
        res = workdirs.resolve_workdir(data, pr, inner)
        assert (res.status, res.not_recorded) == (workdirs.RECOVERED, None)
        assert "re-linked" in res.describe()
        assert store.get_pr(store.load(inner), PR_ID)["workdir"] == str(clone)

    def test_failed_write_says_using_not_re_linked(self, env):
        clone = env.clone(f"{SLUG}-10e74920")
        data, pr = env.fresh()
        with mock.patch.object(workdirs.store, "locked_update",
                               side_effect=store.StoreLockTimeout("busy")):
            res = workdirs.resolve_workdir(data, pr, env.root)
        assert (res.status, res.path) == (workdirs.RECOVERED, str(clone))
        assert "could not write" in res.not_recorded
        assert "using the existing clone" in res.describe()
        assert env.fresh()[1]["workdir"] == env.stale

    def test_stale_path_reappearing_before_the_write_wins(self, env,
                                                          tmp_path):
        # The recorded path was missing when resolution started, then came
        # back (a remount) before the record was written: it now exists, so
        # it is kept — re-checked under the lock, and again in the write.
        clone = env.clone(f"{SLUG}-10e74920")
        gone = tmp_path / "remounted" / "wd"
        store.locked_update(env.root, lambda d: store.get_pr(d, PR_ID)
                            .__setitem__("workdir", str(gone)))
        data, pr = env.fresh()
        gone.mkdir(parents=True)
        assert workdirs._persist(env.root, PR_ID, str(clone)) == (
            str(gone), None)
        assert env.fresh()[1]["workdir"] == str(gone)
        with mock.patch.object(workdirs, "_persist") as persist:
            res = workdirs._resolve_matches(
                data, pr, env.root,
                workdirs.WorkdirResolution(
                    PR_ID, workdirs.MISSING, recorded=str(gone),
                    branch=BRANCH, project_dir=str(env.project_dir)),
                persist=True, reread=True)
        persist.assert_not_called()
        assert (res.status, res.path) == (workdirs.RECORDED, str(gone))
        assert pr["workdir"] == str(gone)

    def test_record_persisted_by_a_concurrent_caller_wins(self, env, tmp_path):
        env.clone(f"{SLUG}-10e74920")
        other = tmp_path / "relinked-elsewhere"
        other.mkdir()
        data, pr = env.fresh()  # in-memory copy still holds the stale path
        store.locked_update(env.root, lambda d: store.get_pr(d, PR_ID)
                            .__setitem__("workdir", str(other)))
        res = workdirs.resolve_workdir(data, pr, env.root)
        assert (res.status, res.path) == (workdirs.RECORDED, str(other))
        assert pr["workdir"] == str(other)


class TestRejectionAndAmbiguity:
    def test_two_verified_clones_are_ambiguous_and_nothing_written(self, env):
        a = env.clone(f"{SLUG}-10e74920")
        b = env.clone(f"{SLUG}-ab512a43")
        data, pr = env.fresh()
        res = workdirs.resolve_workdir(data, pr, env.root)
        assert res.status == workdirs.AMBIGUOUS
        assert res.path is None
        assert res.candidates == [str(a), str(b)]
        assert pr["workdir"] == env.stale
        assert env.fresh()[1]["workdir"] == env.stale
        text = res.describe()
        assert str(a) in text and str(b) in text and "Not choosing" in text

    def test_moving_the_extra_clone_aside_resolves_it(self, env, tmp_path):
        keep = env.clone(f"{SLUG}-10e74920")
        extra = env.clone(f"{SLUG}-ab512a43")
        data, pr = env.fresh()
        assert workdirs.get_workdir(data, pr, env.root) is None
        extra.rename(tmp_path / "set-aside")
        assert workdirs.get_workdir(data, pr, env.root) == str(keep)
        assert env.fresh()[1]["workdir"] == str(keep)

    def test_same_slug_on_another_branch_is_rejected(self, env):
        env.clone(f"{SLUG}-10e74920", branch=None)  # still on master
        data, pr = env.fresh()
        res = workdirs.resolve_workdir(data, pr, env.root)
        assert res.status == workdirs.MISSING
        assert res.rejected[0][1] == f"on branch master, not {BRANCH}"

    def test_plain_detached_head_is_rejected(self, env):
        clone = env.clone(f"{SLUG}-10e74920")
        git(clone, "checkout", "-q", "--detach")
        data, pr = env.fresh()
        res = workdirs.resolve_workdir(data, pr, env.root)
        assert res.status == workdirs.MISSING
        assert res.rejected[0][1] == "HEAD is detached"

    def test_different_repository_is_rejected(self, env, tmp_path):
        other = tmp_path / "other-origin"
        other.mkdir()
        git(other, "init", "-q", "-b", "master")
        (other / "x").write_text("x\n")
        git(other, "add", "x")
        git(other, "commit", "-q", "-m", "unrelated root")
        env.clone(f"{SLUG}-10e74920", src=other)
        data, pr = env.fresh()
        res = workdirs.resolve_workdir(data, pr, env.root)
        assert res.status == workdirs.MISSING
        assert "different repository" in res.rejected[0][1]

    def test_inherited_git_dir_does_not_verify_a_plain_dir(self, env,
                                                          tmp_path,
                                                          monkeypatch):
        """pm run with GIT_DIR set (e.g. from a git hook) must still inspect
        each candidate itself, not the inherited repository."""
        elsewhere = tmp_path / "elsewhere"
        subprocess.run(["git", "clone", "-q", str(env.origin),
                        str(elsewhere)], check=True, capture_output=True)
        git(elsewhere, "checkout", "-q", "-b", BRANCH)
        (env.project_dir / f"{SLUG}-10e74920").mkdir(parents=True)
        data, pr = env.fresh()
        monkeypatch.setenv("GIT_DIR", str(elsewhere / ".git"))
        res = workdirs.resolve_workdir(data, pr, env.root)
        assert res.status == workdirs.MISSING
        assert "not a git repository" in res.rejected[0][1]

    def test_non_repo_dir_is_rejected(self, env):
        (env.project_dir / f"{SLUG}-10e74920").mkdir(parents=True)
        data, pr = env.fresh()
        res = workdirs.resolve_workdir(data, pr, env.root)
        assert res.status == workdirs.MISSING
        assert res.rejected and "repository" in res.rejected[0][1]

    def test_unrelated_names_tmp_and_qa_clones_are_never_candidates(self, env):
        env.clone(f".tmp-{PR_ID}")
        env.clone(f"{SLUG}-extra-10e74920")       # longer slug, other branch
        env.clone(f"{SLUG}10e74920")              # no separator
        qa = env.base / "qa" / f"{PR_ID}-abc" / "scenario-1"
        qa.mkdir(parents=True)
        subprocess.run(["git", "clone", "-q", str(env.origin),
                        str(qa / "repo")], check=True, capture_output=True)
        git(qa / "repo", "checkout", "-q", "-b", BRANCH)
        data, pr = env.fresh()
        res = workdirs.resolve_workdir(data, pr, env.root)
        assert res.status == workdirs.MISSING
        assert res.rejected == [] and res.candidates == []

    def test_absent_project_dir_is_not_created(self, env):
        data, pr = env.fresh()
        res = workdirs.resolve_workdir(data, pr, env.root)
        assert res.status == workdirs.MISSING
        assert not env.project_dir.exists()

    def test_no_branch_means_no_discovery(self, env):
        env.clone(f"{SLUG}-10e74920")
        data, pr = env.fresh()
        pr["branch"] = None
        with mock.patch.object(workdirs, "_name_matches",
                               side_effect=AssertionError("scanned")):
            assert workdirs.resolve_workdir(data, pr).status == workdirs.MISSING

    def test_too_many_name_matches_are_reported_unverified(self, env,
                                                           monkeypatch):
        monkeypatch.setattr(workdirs, "MAX_CANDIDATES", 1)
        env.project_dir.mkdir(parents=True)
        for h in ("10e74920", "ab512a43"):
            (env.project_dir / f"{SLUG}-{h}").mkdir()
        data, pr = env.fresh()
        with mock.patch.object(workdirs, "verify_candidate",
                               side_effect=AssertionError("verified")):
            res = workdirs.resolve_workdir(data, pr, env.root)
        assert res.status == workdirs.AMBIGUOUS and res.unverified
        # Name matches only: not claimed to be clones of the branch.
        text = res.describe()
        assert "none verified" in text and "match branch" not in text


class TestCloneDestination:
    """Where a fresh clone is moved: never over a directory discovery
    skipped."""

    def _tmp_clone(self, env):
        return env.clone(f".tmp-{PR_ID}", branch=None)

    def test_free_name(self, env):
        tmp = self._tmp_clone(env)
        assert workdirs.clone_destination(
            env.fresh()[0], env.project_dir, BRANCH, "10e74920", tmp
        ) == env.project_dir / f"{SLUG}-10e74920"

    def test_this_prs_clone_already_there_is_reused(self, env):
        tmp = self._tmp_clone(env)
        there = env.clone(f"{SLUG}-10e74920")
        assert workdirs.clone_destination(
            env.fresh()[0], env.project_dir, BRANCH, "10e74920", tmp) == there

    def test_dangling_symlink_counts_as_taken(self, env):
        tmp = self._tmp_clone(env)
        full = git(tmp, "rev-parse", "HEAD")
        (env.project_dir / f"{SLUG}-10e74920").symlink_to(env.base / "gone")
        assert workdirs.clone_destination(
            env.fresh()[0], env.project_dir, BRANCH, "10e74920", tmp
        ) == env.project_dir / f"{SLUG}-{full}"


class TestEnsureWorkdir:
    """``_ensure_workdir`` (review/QA/sign-off/done/merge launches)."""

    def test_relinks_instead_of_cloning(self, env, capsys):
        clone = env.clone(f"{SLUG}-10e74920")
        data, pr = env.fresh()
        with mock.patch.object(helpers, "_clone_workdir",
                               side_effect=AssertionError("cloned")):
            assert helpers._ensure_workdir(data, pr, env.root) == str(clone)
        assert env.fresh()[1]["workdir"] == str(clone)
        assert "re-linked" in capsys.readouterr().out

    def test_ambiguity_reports_and_does_not_clone(self, env, capsys):
        env.clone(f"{SLUG}-10e74920")
        env.clone(f"{SLUG}-ab512a43")
        data, pr = env.fresh()
        with mock.patch.object(helpers, "_clone_workdir",
                               side_effect=AssertionError("cloned")):
            assert helpers._ensure_workdir(data, pr, env.root) is None
        assert "Not choosing" in capsys.readouterr().err
        assert env.fresh()[1]["workdir"] == env.stale

    def test_falls_back_to_clone_when_nothing_verifies(self, env):
        env.clone(f"{SLUG}-10e74920", branch=None)
        data, pr = env.fresh()
        with mock.patch.object(helpers, "_clone_workdir",
                               return_value="/cloned") as clone:
            assert helpers._ensure_workdir(data, pr, env.root) == "/cloned"
        clone.assert_called_once()

    def test_skipped_clones_are_explained_before_cloning(self, env, capsys):
        env.clone(f"{SLUG}-10e74920", branch=None)  # same name, on master
        data, pr = env.fresh()
        with mock.patch.object(helpers, "_clone_workdir",
                               return_value="/cloned"):
            assert helpers._ensure_workdir(data, pr, env.root) == "/cloned"
        err = capsys.readouterr().err
        assert f"skipped {env.project_dir / f'{SLUG}-10e74920'}" in err
        assert f"on branch master, not {BRANCH}" in err

    def test_clone_made_by_pm_is_recovered_later(self, env, capsys):
        """Round trip: the clone ``_clone_workdir`` names and checks out is
        the one recovery finds once the record goes stale again."""
        data, pr = env.fresh()
        made = helpers._ensure_workdir(data, pr, env.root)
        assert made and Path(made).parent == env.project_dir
        assert "cloning" in capsys.readouterr().out
        store.locked_update(env.root, lambda d: store.get_pr(d, PR_ID)
                            .update(workdir=env.stale))
        data, pr = env.fresh()
        with mock.patch.object(helpers, "_clone_workdir",
                               side_effect=AssertionError("cloned")):
            assert helpers._ensure_workdir(data, pr, env.root) == made
        assert env.fresh()[1]["workdir"] == made

    def test_clone_never_takes_over_a_skipped_same_named_dir(self, env,
                                                             capsys):
        """The fresh clone's name is held by the user's clone, skipped for
        being on master: it is neither adopted nor checked out; the new
        clone takes the full base hash and is the one recovered later."""
        short = git(env.origin, "rev-parse", "--short=8", "HEAD")
        full = git(env.origin, "rev-parse", "HEAD")
        old = env.clone(f"{SLUG}-{short}", branch=None)
        (old / "README").write_text("user edit\n")
        before = _snapshot(old)
        data, pr = env.fresh()
        made = helpers._ensure_workdir(data, pr, env.root)
        assert made == str(env.project_dir / f"{SLUG}-{full}")
        assert git(made, "symbolic-ref", "-q", "HEAD") == f"refs/heads/{BRANCH}"
        assert _snapshot(old) == before
        assert f"on branch master, not {BRANCH}" in capsys.readouterr().err
        assert env.fresh()[1]["workdir"] == made
        store.locked_update(env.root, lambda d: store.get_pr(d, PR_ID)
                            .update(workdir=env.stale))
        res = workdirs.resolve_workdir(*env.fresh(), env.root)
        assert (res.status, res.path) == (workdirs.RECOVERED, made)

    def test_no_free_clone_name_clones_nothing(self, env, capsys):
        short = git(env.origin, "rev-parse", "--short=8", "HEAD")
        full = git(env.origin, "rev-parse", "HEAD")
        old = env.clone(f"{SLUG}-{short}", branch=None)
        (env.project_dir / f"{SLUG}-{full}").mkdir()
        before = _snapshot(old)
        data, pr = env.fresh()
        assert helpers._ensure_workdir(data, pr, env.root) is None
        assert "Not cloning" in capsys.readouterr().err
        assert _snapshot(old) == before
        assert not (env.project_dir / f".tmp-{PR_ID}").exists()
        assert env.fresh()[1]["workdir"] == env.stale

    def test_lock_is_held_while_recovering(self, env):
        """Recovery runs inside the per-PR provisioning lock (not a second,
        re-entrant acquisition, which would deadlock on flock)."""
        import fcntl
        env.clone(f"{SLUG}-10e74920")
        data, pr = env.fresh()
        lock = env.project_dir / f".workdir-{PR_ID}.lock"
        held = []
        real = workdirs.verify_candidate

        def probe(*a, **k):
            fd = os.open(str(lock), os.O_RDWR)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                held.append(False)
                fcntl.flock(fd, fcntl.LOCK_UN)
            except BlockingIOError:
                held.append(True)
            finally:
                os.close(fd)
            return real(*a, **k)

        with mock.patch.object(workdirs, "verify_candidate", side_effect=probe):
            helpers._ensure_workdir(data, pr, env.root)
        assert held == [True]


def _pr_start_mocks(env):
    yaml_dump = yaml.safe_dump(store.load(env.root))

    def run_git(*args, **kwargs):
        if args[:1] == ("show",):
            return mock.Mock(returncode=0, stdout=yaml_dump, stderr="")
        return mock.Mock(returncode=0, stdout="", stderr="")

    return mock.patch.multiple(
        git_ops, clone=mock.DEFAULT, checkout_branch=mock.DEFAULT,
        pull_rebase=mock.DEFAULT, run_git=mock.Mock(side_effect=run_git))


class TestPrStart:
    def _invoke(self, env, *args):
        runner = CliRunner()
        with mock.patch.object(pr_mod, "state_root", return_value=env.root), \
             mock.patch.object(pr_mod, "find_claude", return_value=None), \
             mock.patch.object(pr_mod.tmux_mod, "has_tmux",
                               return_value=False), \
             mock.patch.object(pr_mod, "_get_pm_session", return_value=None), \
             _pr_start_mocks(env) as gm:
            result = runner.invoke(pr_mod.pr, ["start", PR_ID, *args])
        return result, gm

    def test_in_progress_reuses_recovered_workdir(self, env):
        clone = env.clone(f"{SLUG}-10e74920")
        result, gm = self._invoke(env)
        assert result.exit_code == 0, result.output
        assert "recovered workdir" in result.output
        assert "creating a new one" not in result.output
        gm["clone"].assert_not_called()
        assert env.fresh()[1]["workdir"] == str(clone)

    def test_pending_start_reuses_clone_instead_of_cloning(self, env):
        clone = env.clone(f"{SLUG}-10e74920")
        store.locked_update(env.root, lambda d: store.get_pr(d, PR_ID)
                            .update(status="pending", workdir=None))
        result, gm = self._invoke(env)
        assert result.exit_code == 0, result.output
        assert "re-linked" in result.output
        gm["clone"].assert_not_called()
        _, pr = env.fresh()
        assert (pr["workdir"], pr["status"]) == (str(clone), "in_progress")

    def test_ambiguity_refuses_to_clone(self, env):
        env.clone(f"{SLUG}-10e74920")
        env.clone(f"{SLUG}-ab512a43")
        result, gm = self._invoke(env)
        assert result.exit_code == 1
        assert "Not choosing" in result.output
        assert "Not creating another workdir" in result.output
        gm["clone"].assert_not_called()
        assert env.fresh()[1]["workdir"] == env.stale

    def test_clone_does_not_take_over_a_skipped_same_named_dir(self, env):
        # run_git is stubbed, so the fresh clone gets the bare slug — the
        # name the user's clone (on master, skipped) already holds — and no
        # full hash to fall back to.
        old = env.clone(SLUG, branch=None)
        before = _snapshot(old)
        store.locked_update(env.root, lambda d: store.get_pr(d, PR_ID)
                            .update(status="pending", workdir=None))
        result, gm = self._invoke(env)
        assert result.exit_code == 1, result.output
        assert f"on branch master, not {BRANCH}" in result.output
        assert "Not creating a workdir" in result.output
        gm["checkout_branch"].assert_not_called()
        gm["pull_rebase"].assert_not_called()
        assert _snapshot(old) == before
        assert env.fresh()[1]["workdir"] is None

    def test_explicit_workdir_skips_discovery(self, env, tmp_path):
        env.clone(f"{SLUG}-10e74920")
        explicit = tmp_path / "explicit"
        explicit.mkdir()
        with mock.patch.object(pr_mod.workdirs_mod, "resolve_workdir",
                               side_effect=AssertionError("discovered")):
            result, _ = self._invoke(env, "--workdir", str(explicit))
        assert result.exit_code == 0, result.output
        assert "creating a new one" not in result.output
        assert env.fresh()[1]["workdir"] == str(explicit)


class TestPrCd:
    def test_cd_recovers_stale_record(self, env):
        clone = env.clone(f"{SLUG}-10e74920")
        runner = CliRunner()
        with mock.patch.object(pr_mod, "state_root", return_value=env.root), \
             mock.patch.object(pr_mod.os, "chdir") as chdir, \
             mock.patch.object(pr_mod.os, "execvp") as execvp:
            result = runner.invoke(pr_mod.pr, ["cd", PR_ID])
        assert result.exit_code == 0, result.output
        chdir.assert_called_once_with(str(clone))
        execvp.assert_called_once()

    def test_cd_explains_skipped_clone(self, env):
        env.clone(f"{SLUG}-10e74920", branch=None)  # same name, on master
        runner = CliRunner()
        with mock.patch.object(pr_mod, "state_root", return_value=env.root), \
             mock.patch.object(pr_mod.os, "execvp") as execvp:
            result = runner.invoke(pr_mod.pr, ["cd", PR_ID])
        assert result.exit_code == 1
        assert f"recorded path {env.stale} is missing" in result.output
        assert f"on branch master, not {BRANCH}" in result.output
        execvp.assert_not_called()

    def test_cd_from_another_prs_clone_leaves_its_registry_clean(self, env):
        """`pm pr cd <B>` run inside PR C's clone enters B's clone and says
        "using" — the re-link isn't written into C's tracked yaml (QA S11
        story 3, which then refused C's integrate --apply as dirty)."""
        clone = env.clone(f"{SLUG}-10e74920")
        other_branch = "pm/pr-c000001-other"
        other = env.clone("pm-pr-c000001-other-10e74920", branch=other_branch)
        inner, _, _ = _other_pr_registry(env, other, other_branch)
        runner = CliRunner()
        with mock.patch.object(pr_mod, "state_root", return_value=inner), \
             mock.patch.object(pr_mod.os, "chdir") as chdir, \
             mock.patch.object(pr_mod.os, "execvp") as execvp:
            result = runner.invoke(pr_mod.pr, ["cd", PR_ID])
        assert result.exit_code == 0, result.output
        assert "using the existing clone" in result.output
        assert "re-linked" not in result.output
        chdir.assert_called_once_with(str(clone))
        execvp.assert_called_once()
        assert git(other, "status", "--porcelain") == ""

    def test_cd_reports_ambiguity(self, env):
        env.clone(f"{SLUG}-10e74920")
        env.clone(f"{SLUG}-ab512a43")
        runner = CliRunner()
        with mock.patch.object(pr_mod, "state_root", return_value=env.root), \
             mock.patch.object(pr_mod.os, "execvp") as execvp:
            result = runner.invoke(pr_mod.pr, ["cd", PR_ID])
        assert result.exit_code == 1
        assert "Not choosing" in result.output
        execvp.assert_not_called()


class TestQaLaunch:
    """The QA launch runs in the TUI, where ``_ensure_workdir``'s stderr
    report is never seen: its status line must name the ambiguity."""

    def _run(self, env):
        from pm_core import qa_loop
        data, pr = env.fresh()
        pr["status"] = "qa"
        store.save(data, env.root)
        state = qa_loop.QALoopState(pr_id=PR_ID)
        with mock.patch.object(qa_loop, "get_pm_session",
                               return_value="pm-test"), \
             mock.patch.object(qa_loop, "_resolve_qa_model"), \
             mock.patch.object(qa_loop, "create_qa_workdir",
                               side_effect=AssertionError("QA started")):
            return qa_loop.run_qa_sync(state, env.root, pr)

    def test_ambiguity_is_named_not_reported_as_missing(self, env):
        env.clone(f"{SLUG}-10e74920")
        env.clone(f"{SLUG}-ab512a43")
        state = self._run(env)
        assert state.latest_verdict == "ERROR"
        assert "2 clones" in state.latest_output
        assert "not choosing one" in state.latest_output
        assert "does not exist" not in state.latest_output
        assert env.fresh()[1]["workdir"] == env.stale

    def test_failed_clone_still_reports_missing(self, env):
        with mock.patch.object(helpers, "_clone_workdir", return_value=None):
            state = self._run(env)
        assert state.latest_verdict == "ERROR"
        assert "does not exist on this machine" in state.latest_output


class TestLaunchWindowMessages:
    """Review and sign-off windows end with one line the user sees (the
    TUI shows only a launch's last stdout line, never ``_ensure_workdir``'s
    stderr listing): an ambiguity must be named there, not "Start the PR
    first" — a start would only be refused for the same ambiguity."""

    @pytest.fixture
    def tmux(self, env, monkeypatch):
        from pm_core import signoff
        for mod in (pr_mod.tmux_mod, signoff.tmux_mod):
            monkeypatch.setattr(mod, "has_tmux", lambda: True)
            monkeypatch.setattr(mod, "in_tmux", lambda: True)
            monkeypatch.setattr(mod, "session_exists", lambda s: True)
        monkeypatch.setattr(pr_mod, "_get_pm_session", lambda: "pm-test")
        monkeypatch.setattr(pr_mod, "state_root", lambda: env.root)
        monkeypatch.setattr(helpers, "state_root", lambda: env.root)
        return signoff

    def _review(self, env, capsys):
        data, pr = env.fresh()
        pr_mod._launch_review_window(data, pr, background=True)
        return capsys.readouterr().out.strip().splitlines()[-1]

    def _signoff(self, env, signoff, capsys):
        data, pr = env.fresh()
        signoff.launch_signoff_window(data, pr, background=True,
                                      session_name="pm-test")
        return capsys.readouterr().out.strip().splitlines()[-1]

    def test_review_window_names_the_ambiguity(self, env, tmux, capsys):
        env.clone(f"{SLUG}-10e74920")
        env.clone(f"{SLUG}-ab512a43")
        last = self._review(env, capsys)
        assert last.startswith(f"Review window: no workdir for {PR_ID}.")
        assert f"2 clones of {BRANCH} in {env.project_dir}" in last
        assert "move the extra clone(s) aside" in last
        assert "Start the PR first" not in last
        assert env.fresh()[1]["workdir"] == env.stale

    def test_signoff_window_names_the_ambiguity(self, env, tmux, capsys):
        env.clone(f"{SLUG}-10e74920")
        env.clone(f"{SLUG}-ab512a43")
        last = self._signoff(env, tmux, capsys)
        assert last.startswith(f"Sign-off window: no workdir for {PR_ID}.")
        assert "2 clones of" in last and "not choosing one" in last
        assert "Start the PR first" not in last

    def test_no_clone_at_all_still_says_start_the_pr(self, env, tmux,
                                                      capsys):
        with mock.patch.object(helpers, "_clone_workdir", return_value=None):
            assert self._review(env, capsys) == (
                f"Review window: no workdir for {PR_ID}. Start the PR first.")
            assert self._signoff(env, tmux, capsys) == (
                f"Sign-off window: no workdir for {PR_ID}. "
                "Start the PR first.")
