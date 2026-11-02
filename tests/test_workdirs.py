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

    def test_persist_is_compare_and_set(self, env, tmp_path):
        clone = env.clone(f"{SLUG}-10e74920")
        # On-disk record still the stale path: the recovered path is written.
        assert workdirs._persist(env.root, PR_ID, env.stale,
                                 str(clone)) == str(clone)
        assert env.fresh()[1]["workdir"] == str(clone)
        # Another writer recorded an existing path meanwhile: it wins and is
        # not overwritten.
        other = tmp_path / "relinked-elsewhere"
        other.mkdir()
        store.locked_update(env.root, lambda d: store.get_pr(d, PR_ID)
                            .__setitem__("workdir", str(other)))
        assert workdirs._persist(env.root, PR_ID, env.stale,
                                 str(clone)) == str(other)
        assert env.fresh()[1]["workdir"] == str(other)

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
        assert res.status == workdirs.AMBIGUOUS


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

    def test_explicit_workdir_skips_discovery(self, env, tmp_path):
        env.clone(f"{SLUG}-10e74920")
        explicit = tmp_path / "explicit"
        explicit.mkdir()
        with mock.patch.object(pr_mod.workdirs_mod, "resolve_workdir",
                               side_effect=AssertionError("discovered")):
            result, _ = self._invoke(env, "--workdir", str(explicit))
        assert result.exit_code == 0, result.output
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
