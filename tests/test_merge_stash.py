"""Tests for pr-ca6981c: a merge's auto-stash must not corrupt project.yaml.

Using git's *text* stash/pop to carry pm's live registry (``pm/project.yaml``)
across a fast-forward of the main repo wrote conflict markers into it, leaked
``pm: auto-stash for merge`` entries, and raced concurrent pm writers (#253
S74).  The fix keeps the registry out of every text stash: it is pre-merged
with ``store.merge_3way`` and swapped in atomically, its index entry is set to
the incoming blob so the fast-forward leaves the file alone, and the registry
lock is held across the whole fast-forward.

Real-git tests drive :func:`pr_mod._ff_with_autostash`, the helper both
production call sites (``_publish_local`` and ``_pull_after_merge``) use.
"""

import re
import subprocess
import threading
import time
from pathlib import Path
from unittest import mock

import pytest

from pm_core import store
from pm_core.cli import pr as pr_mod


def _git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                          text=True)


def _init_repo(tmp_path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", "-q", "-b", "master", cwd=repo)
    _git("config", "user.email", "t@t", cwd=repo)
    _git("config", "user.name", "t", cwd=repo)
    return repo


def _seed_project(repo) -> Path:
    pm = repo / "pm"
    pm.mkdir()
    store.save(
        {"project": {"name": "x", "base_branch": "master", "backend": "local"},
         "prs": [{"id": "pr-001", "title": "one", "status": "in_review",
                  "updated_at": "2026-01-01T00:00:00"},
                 {"id": "pr-002", "title": "two", "status": "pending"}],
         "plans": []},
        pm,
    )
    (repo / ".gitignore").write_text("pm/project.yaml.lock\n")
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "base", cwd=repo)
    return pm


def _edit(pm, fn):
    d = store.load(pm)
    fn(d)
    store.save(d, pm)


def _pr(d, pr_id):
    return store.get_pr(d, pr_id)


def _incoming(repo, pm, fn=None, files=None):
    """Commit an `incoming` branch one commit ahead of master (ff-able)."""
    _git("checkout", "-q", "-b", "incoming", cwd=repo)
    if fn:
        _edit(pm, fn)
    for name, text in (files or {}).items():
        (repo / name).write_text(text)
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "incoming", cwd=repo)
    _git("checkout", "-q", "master", cwd=repo)


def _stash_list(repo):
    return _git("stash", "list", cwd=repo).stdout


def _with_code_overlap(repo, pm, fn):
    """`incoming` changes the registry (*fn*) and code.txt; code.txt is
    dirty locally too, so the first fast-forward stops on the overlap."""
    (repo / "code.txt").write_text("v1\n")
    _git("add", "code.txt", cwd=repo)
    _git("commit", "-q", "-m", "code", cwd=repo)
    _incoming(repo, pm, fn, files={"code.txt": "v2\n"})
    (repo / "code.txt").write_text("v1 local\n")


def _failing_retry():
    """A run_git that fails the second ``git merge`` (the retry after the
    stash), i.e. the update fails after the registry was swapped in."""
    real = pr_mod.git_ops.run_git
    merges = []

    def run_git(*args, **kw):
        if args[0] == "merge":
            merges.append(args)
            if len(merges) == 2:
                return subprocess.CompletedProcess(args, 1, "",
                                                   "simulated failure")
        return real(*args, **kw)
    return mock.patch.object(pr_mod.git_ops, "run_git", side_effect=run_git)


def _spy_restore():
    return mock.patch.object(pr_mod, "_restore_registry",
                             wraps=pr_mod._restore_registry)


def _add_note(note_id, text, ts="2026-05-05T05:05:05"):
    def fn(d):
        pr = _pr(d, "pr-001")
        pr.setdefault("notes", []).append(
            {"id": note_id, "text": text, "created_at": ts,
             "last_edited": ts})
        pr["updated_at"] = ts
    return fn


# ---------------------------------------------------------------------------
# store.find_conflict_markers / load() guard
# ---------------------------------------------------------------------------

class TestConflictMarkerGuard:
    def test_find_markers_detects_all_forms(self):
        text = (
            "a: 1\n"
            "<<<<<<< Updated upstream\n"
            "b: 2\n"
            "||||||| base\n"
            "b: 0\n"
            "=======\n"
            "b: 3\n"
            ">>>>>>> Stashed changes\n"
        )
        hits = store.find_conflict_markers(text)
        assert [n for n, _ in hits] == [2, 4, 6, 8]

    def test_benign_equals_in_value_not_flagged(self):
        # A value containing '===' or trailing equals must not trip the check,
        # nor marker text quoted inside an (indented) note.
        text = ("key: 'a======='\ntoken: ab==\nbar: '======= not a marker'\n"
                "notes:\n  - text: '<<<<<<< Updated upstream\n    ======='\n")
        assert store.find_conflict_markers(text) == []

    def test_load_raises_clear_error_on_markers(self, tmp_path):
        root = tmp_path / "pm"
        root.mkdir()
        (root / "project.yaml").write_text(
            "project:\n"
            "  name: x\n"
            "prs:\n"
            "  - id: pr-001\n"
            "<<<<<<< Updated upstream\n"
            "    updated_at: '2026-01-01'\n"
            "=======\n"
            "    updated_at: '2026-02-02'\n"
            ">>>>>>> Stashed changes\n"
        )
        with pytest.raises(store.ProjectYamlParseError) as exc:
            store.load(root)
        msg = str(exc.value)
        assert "conflict markers" in msg
        assert "line 5" in msg  # the <<<<<<< line
        # Remediation works from any cwd and says what a checkout loses.
        assert f"git checkout -- {root / 'project.yaml'}" in msg
        assert "discards pm's uncommitted state" in msg

    def test_missing_file_is_still_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            store.load(tmp_path)
        with pytest.raises(store.ProjectYamlMissingError):
            store.load(tmp_path)


# ---------------------------------------------------------------------------
# _dirty_file_paths
# ---------------------------------------------------------------------------

class TestDirtyFilePaths:
    def test_worktree_only_change_path_intact(self, tmp_path):
        repo = _init_repo(tmp_path)
        pm = _seed_project(repo)
        # Worktree-only modification → porcelain " M pm/project.yaml"
        _edit(pm, lambda d: d["project"].update(x=1))
        assert pr_mod._dirty_file_paths(repo) == ["pm/project.yaml"]

    def test_untracked_pm_dir_never_stashes_the_registry(self, tmp_path):
        """An uncommitted pm/ shows as one `?? pm/` entry; the stashable
        paths expand it and leave the registry and its lock out."""
        repo = _init_repo(tmp_path)
        (repo / "a.txt").write_text("a\n")
        _git("add", "-A", cwd=repo)
        _git("commit", "-q", "-m", "a", cwd=repo)
        pm = repo / "pm"
        pm.mkdir()
        store.save({"project": {}, "prs": [], "plans": []}, pm)
        (pm / "project.yaml.lock").write_text("")
        (pm / "notes.txt").write_text("n\n")
        dirty = pr_mod._dirty_file_paths(repo)
        assert dirty == ["pm/"]
        assert pr_mod._stashable_paths(repo, dirty) == ["pm/notes.txt"]

    def test_raw_paths_and_renames(self, tmp_path):
        repo = _init_repo(tmp_path)
        _seed_project(repo)
        (repo / "old name.txt").write_text("x\n")
        _git("add", "-A", cwd=repo)
        _git("commit", "-q", "-m", "f", cwd=repo)
        _git("mv", "old name.txt", "new name.txt", cwd=repo)
        (repo / "café \"q\".txt").write_text("u\n")
        paths = pr_mod._dirty_file_paths(repo)
        # Not C-quoted, rename gives the new path only.
        assert sorted(paths) == ["café \"q\".txt", "new name.txt"]

    def test_untracked_listed_despite_user_status_config(self, tmp_path):
        """A user's ``status.showUntrackedFiles=no`` hid untracked files from
        the porcelain status, so one blocking the fast-forward was never
        stashed (the stash names its paths)."""
        repo = _init_repo(tmp_path)
        _seed_project(repo)
        _git("config", "status.showUntrackedFiles", "no", cwd=repo)
        (repo / "new.txt").write_text("u\n")
        assert pr_mod._dirty_file_paths(repo) == ["new.txt"]


# ---------------------------------------------------------------------------
# pr start: persist a created GitHub PR with backoff (#210 class)
# ---------------------------------------------------------------------------

class TestPersistWithBackoff:
    def test_succeeds_after_transient_timeout(self, tmp_path):
        root = tmp_path / "pm"
        root.mkdir()
        store.save({"project": {}, "prs": [{"id": "pr-001"}], "plans": []},
                   root)
        calls = {"n": 0}
        real = store.locked_update

        def flaky(r, fn, **kw):
            calls["n"] += 1
            if calls["n"] < 3:
                raise store.StoreLockTimeout("contended")
            return real(r, fn, **kw)

        with mock.patch.object(store, "locked_update", side_effect=flaky), \
             mock.patch.object(pr_mod.time, "sleep"):
            out = pr_mod._persist_with_backoff(
                root, lambda d: d["prs"][0].__setitem__("gh_pr_number", 210))
        assert calls["n"] == 3
        assert out["prs"][0]["gh_pr_number"] == 210
        assert store.load(root)["prs"][0]["gh_pr_number"] == 210

    def test_raises_after_exhausting_attempts(self, tmp_path):
        root = tmp_path / "pm"
        root.mkdir()
        with mock.patch.object(store, "locked_update",
                               side_effect=store.StoreLockTimeout("x")), \
             mock.patch.object(pr_mod.time, "sleep"):
            with pytest.raises(store.StoreLockTimeout):
                pr_mod._persist_with_backoff(root, lambda d: None, attempts=3)


# ---------------------------------------------------------------------------
# _ff_with_autostash: registry reconciliation across a fast-forward
# ---------------------------------------------------------------------------

class TestRegistryAcrossFastForward:
    def test_overlapping_registry_edits_reconcile_without_markers(
            self, tmp_path):
        """The pr-ca6981c repro: incoming and local both change pr-001's
        updated_at (a text conflict), plus disjoint edits on each side."""
        repo = _init_repo(tmp_path)
        pm = _seed_project(repo)

        def incoming(d):
            _add_note("note-in", "from the branch",
                      "2026-02-02T02:02:02")(d)
            _pr(d, "pr-002")["description"] = "branch edit"
        _incoming(repo, pm, incoming)

        def local(d):
            _pr(d, "pr-001")["updated_at"] = "2026-03-03T03:03:03"
            _pr(d, "pr-001")["status"] = "sign_off"
            _pr(d, "pr-002")["title"] = "local title"
        _edit(pm, local)

        r = pr_mod._ff_with_autostash(repo, "incoming")
        assert r.returncode == 0, r.stderr

        text = (pm / "project.yaml").read_text()
        assert store.find_conflict_markers(text) == []     # no markers
        d = store.load(pm)                                  # valid YAML
        one, two = _pr(d, "pr-001"), _pr(d, "pr-002")
        assert [n["id"] for n in one["notes"]] == ["note-in"]  # merged in
        assert two["description"] == "branch edit"            # merged in
        assert one["updated_at"] == "2026-03-03T03:03:03"     # live wins
        assert one["status"] == "sign_off"                    # live kept
        assert two["title"] == "local title"                  # live kept
        assert _stash_list(repo) == ""                        # no stash
        assert _git("rev-parse", "HEAD", cwd=repo).stdout == \
            _git("rev-parse", "incoming", cwd=repo).stdout
        # The live delta is uncommitted again, not staged.
        assert _git("diff", "--cached", "--name-only",
                    cwd=repo).stdout == ""

    def test_merged_pr_finalizes_after_reconcile(self, tmp_path):
        """(d) The finalize after the update succeeds: status=merged and
        merged_at set (a marker-corrupted file used to make it raise)."""
        repo = _init_repo(tmp_path)
        pm = _seed_project(repo)
        _incoming(repo, pm, _add_note("note-in", "x", "2026-02-02T02:02:02"))
        _edit(pm, lambda d: _pr(d, "pr-001").update(
            updated_at="2026-03-03T03:03:03"))

        assert pr_mod._ff_with_autostash(repo, "incoming").returncode == 0
        pr_entry = store.get_pr(store.load(pm), "pr-001")
        with mock.patch.object(pr_mod, "trigger_tui_refresh"), \
             mock.patch("pm_core.cli.helpers._find_tui_pane",
                        return_value=(None, None)):
            pr_mod._finalize_merge(pm, pr_entry, "pr-001")
        final = store.get_pr(store.load(pm), "pr-001")
        assert final["status"] == "merged"
        assert final.get("merged_at")

    def test_other_dirty_files_stashed_and_restored(self, tmp_path):
        """code.txt blocks the fast-forward, so every dirty file but the
        registry (an untracked one with a space in its name too) goes
        through the stash and comes back with the clean pop."""
        repo = _init_repo(tmp_path)
        pm = _seed_project(repo)
        (repo / "code.txt").write_text("a\nb\nc\nd\ne\n")
        _git("add", "code.txt", cwd=repo)
        _git("commit", "-q", "-m", "code", cwd=repo)
        _incoming(repo, pm, _add_note("note-in", "x"),
                  files={"code.txt": "A\nb\nc\nd\ne\n"})
        _edit(pm, lambda d: _pr(d, "pr-001").update(updated_at="local"))
        (repo / "code.txt").write_text("a\nb\nc\nd\nE\n")
        (repo / "scratch file.txt").write_text("untracked\n")

        stashed = []
        real_stash = pr_mod._stash_for_merge

        def stash(*args, **kw):
            stashed.append(real_stash(*args, **kw))
            return stashed[-1]

        with mock.patch.object(pr_mod, "_stash_for_merge", side_effect=stash):
            r = pr_mod._ff_with_autostash(repo, "incoming")
        assert r.returncode == 0, r.stderr
        assert [s and s["count"] for s in stashed] == [2]   # the stash path
        assert (repo / "code.txt").read_text() == "A\nb\nc\nd\nE\n"
        assert (repo / "scratch file.txt").read_text() == "untracked\n"
        d = store.load(pm)
        assert _pr(d, "pr-001")["updated_at"] == "local"
        assert [n["id"] for n in _pr(d, "pr-001")["notes"]] == ["note-in"]
        assert _stash_list(repo) == ""

    def test_failed_ff_restores_exact_local_registry(self, tmp_path):
        """A fast-forward that still fails after the merged registry was
        swapped in and the other files stashed leaves the registry
        byte-identical, nothing staged and the other files restored."""
        repo = _init_repo(tmp_path)
        pm = _seed_project(repo)
        _with_code_overlap(repo, pm, _add_note("note-in", "x"))
        _edit(pm, lambda d: _pr(d, "pr-001").update(updated_at="local"))
        before = (pm / "project.yaml").read_bytes()
        head = _git("rev-parse", "HEAD", cwd=repo).stdout

        with _failing_retry(), _spy_restore() as restore:
            r = pr_mod._ff_with_autostash(repo, "incoming")
        assert r.returncode != 0
        restore.assert_called_once()          # the swap really was undone
        assert (pm / "project.yaml").read_bytes() == before
        assert (repo / "code.txt").read_text() == "v1 local\n"
        assert _git("rev-parse", "HEAD", cwd=repo).stdout == head
        assert _stash_list(repo) == ""
        assert _git("diff", "--cached", "--name-only", cwd=repo).stdout == ""

    def test_unrestorable_index_entry_is_reported(self, tmp_path, capsys):
        """Another git process holding index.lock fails the fast-forward and
        the index restore alike.  The incoming blob then stays staged on the
        old HEAD (a later commit would commit it), so the warning gives the
        command that puts the original entry back."""
        repo = _init_repo(tmp_path)
        pm = _seed_project(repo)
        _incoming(repo, pm, _add_note("note-in", "x"))
        _edit(pm, lambda d: _pr(d, "pr-001").update(updated_at="local"))
        before = (pm / "project.yaml").read_bytes()
        index_lock = repo / ".git" / "index.lock"
        real_apply = pr_mod._apply_registry

        def apply_then_lock(*args):
            ok = real_apply(*args)
            index_lock.write_text("")
            return ok

        with mock.patch.object(pr_mod, "_apply_registry", apply_then_lock):
            r = pr_mod._ff_with_autostash(repo, "incoming")
        index_lock.unlink()
        assert r.returncode != 0
        assert (pm / "project.yaml").read_bytes() == before
        staged = _git("diff", "--cached", "--name-only", cwd=repo).stdout
        assert staged == "pm/project.yaml\n"
        err = capsys.readouterr().err
        cmd = re.search(r"`git (update-index --cacheinfo [^`]+)`", err)
        assert cmd, err
        assert _git(*cmd.group(1).split(), cwd=repo).returncode == 0
        assert _git("diff", "--cached", "--name-only", cwd=repo).stdout == ""

    def test_stash_failure_restores_registry(self, tmp_path):
        repo = _init_repo(tmp_path)
        pm = _seed_project(repo)
        (repo / "code.txt").write_text("v1\n")
        _git("add", "code.txt", cwd=repo)
        _git("commit", "-q", "-m", "code", cwd=repo)
        _incoming(repo, pm, _add_note("note-in", "x"),
                  files={"code.txt": "v2\n"})
        _edit(pm, lambda d: _pr(d, "pr-001").update(updated_at="local"))
        (repo / "code.txt").write_text("v1 local\n")   # blocks the ff
        before = (pm / "project.yaml").read_bytes()
        real = pr_mod.git_ops.run_git

        def run_git(*args, **kw):
            if args[:2] == ("stash", "push"):
                return subprocess.CompletedProcess(args, 1, "", "boom")
            return real(*args, **kw)

        with mock.patch.object(pr_mod.git_ops, "run_git",
                               side_effect=run_git):
            r = pr_mod._ff_with_autostash(repo, "incoming")
        assert r.returncode != 0
        assert (pm / "project.yaml").read_bytes() == before

    def test_empty_stash_push_never_pops_someone_elses_stash(self, tmp_path):
        """`stash push` can exit 0 having saved nothing; stash@{0} is then
        the user's own stash and must not be popped as pm's."""
        repo = _init_repo(tmp_path)
        pm = _seed_project(repo)
        (repo / "mine.txt").write_text("base\n")
        _git("add", "mine.txt", cwd=repo)
        _git("commit", "-q", "-m", "mine", cwd=repo)
        (repo / "mine.txt").write_text("user work\n")
        _git("stash", "push", "-m", "user stash", cwd=repo)
        user = _git("rev-parse", "stash@{0}", cwd=repo).stdout
        _incoming(repo, pm, _add_note("note-in", "x"),
                  files={"mine.txt": "incoming\n"})
        _edit(pm, lambda d: _pr(d, "pr-001").update(updated_at="local"))
        (repo / "mine.txt").write_text("local\n")       # blocks the ff
        before = (pm / "project.yaml").read_bytes()
        real = pr_mod.git_ops.run_git

        def run_git(*args, **kw):
            if args[:2] == ("stash", "push"):
                return subprocess.CompletedProcess(
                    args, 0, "No local changes to save\n", "")
            return real(*args, **kw)

        with mock.patch.object(pr_mod.git_ops, "run_git",
                               side_effect=run_git):
            r = pr_mod._ff_with_autostash(repo, "incoming")
        assert r.returncode != 0
        assert _git("rev-parse", "stash@{0}", cwd=repo).stdout == user
        assert (repo / "mine.txt").read_text() == "local\n"
        assert (pm / "project.yaml").read_bytes() == before

    def test_git_never_rewrites_the_live_registry(self, tmp_path):
        """git's checkout unlinks and recreates a file, so lock-free readers
        (a writer's pre-lock load, the TUI) could see it missing or partial.
        pm swaps the merged registry in with one rename and stages the
        incoming blob, so the fast-forward keeps the file as it is."""
        repo = _init_repo(tmp_path)
        pm = _seed_project(repo)
        (repo / "code.txt").write_text("a\nb\nc\nd\ne\n")
        _git("add", "code.txt", cwd=repo)
        _git("commit", "-q", "-m", "code", cwd=repo)
        _incoming(repo, pm, _add_note("note-in", "x"),
                  files={"code.txt": "A\nb\nc\nd\ne\n"})
        _edit(pm, lambda d: _pr(d, "pr-001").update(updated_at="local"))
        # Blocks the fast-forward (stash path), pops cleanly afterwards.
        (repo / "code.txt").write_text("a\nb\nc\nd\nE\n")
        inodes = []
        real = pr_mod.git_ops.run_git

        def run_git(*args, **kw):
            watch = args[0] == "merge" or args[:2] in (("stash", "push"),
                                                       ("stash", "pop"))
            # (inode, mtime): a freed inode number is reused at once, so an
            # unlink + recreate can keep the same st_ino.
            st = (pm / "project.yaml").stat
            if watch:
                inodes.append((st().st_ino, st().st_mtime_ns))
            r = real(*args, **kw)
            if watch:
                inodes.append((st().st_ino, st().st_mtime_ns))
            return r

        with mock.patch.object(pr_mod.git_ops, "run_git",
                               side_effect=run_git):
            assert pr_mod._ff_with_autostash(repo, "incoming").returncode == 0
        assert len(inodes) >= 4 and len(set(inodes)) == 1, inodes
        d = store.load(pm)
        assert _pr(d, "pr-001")["updated_at"] == "local"
        assert [n["id"] for n in _pr(d, "pr-001")["notes"]] == ["note-in"]
        assert (repo / "code.txt").read_text() == "A\nb\nc\nd\nE\n"
        assert _stash_list(repo) == ""

    def test_user_merge_autostash_config_never_text_stashes_registry(
            self, tmp_path):
        """A user's ``merge.autoStash=true`` made the fast-forward itself
        text-stash the swapped-in registry and pop it back over the incoming
        one: conflict markers and a leaked ``autostash`` entry, rc 0."""
        repo = _init_repo(tmp_path)
        pm = _seed_project(repo)
        _git("config", "merge.autoStash", "true", cwd=repo)
        _incoming(repo, pm, _add_note("note-in", "x", "2026-02-02T02:02:02"))
        _edit(pm, lambda d: _pr(d, "pr-001").update(
            updated_at="2026-03-03T03:03:03"))

        r = pr_mod._ff_with_autostash(repo, "incoming")
        assert r.returncode == 0, r.stderr
        assert "autostash" not in r.stdout + r.stderr
        assert store.find_conflict_markers(
            (pm / "project.yaml").read_text()) == []
        d = store.load(pm)
        assert _pr(d, "pr-001")["updated_at"] == "2026-03-03T03:03:03"
        assert [n["id"] for n in _pr(d, "pr-001")["notes"]] == ["note-in"]
        assert _stash_list(repo) == ""

    @pytest.mark.parametrize("version, flag", [
        ((2, 25), False), ((2, 27), True), ((2, 45), True), ((0, 0), True)])
    def test_no_autostash_only_where_git_has_it(self, version, flag):
        """git < 2.27 rejects the unknown option (every fast-forward would
        fail) and has no autostash to turn off."""
        from pm_core import integration
        with mock.patch.object(integration, "_git_version",
                               return_value=version):
            assert pr_mod._no_autostash() == (
                ("--no-autostash",) if flag else ())

    def test_live_change_after_planning_is_merged_under_the_lock(
            self, tmp_path):
        """A writer saving between the plan and the lock: its change, the
        local edit and the merged-in note all survive, and the re-merge
        under the lock parses only the live text (HEAD's and the target's
        registries were parsed while planning)."""
        repo = _init_repo(tmp_path)
        pm = _seed_project(repo)
        _incoming(repo, pm, _add_note("note-in", "x", "2026-02-02T02:02:02"))
        _edit(pm, lambda d: _pr(d, "pr-001").update(updated_at="local"))
        real_plan, real_parse = pr_mod._plan_registry, pr_mod._parse_registry
        parsed_after_plan = []

        def plan_then_write(repo_, target):
            p = real_plan(repo_, target)
            _edit(pm, lambda d: _pr(d, "pr-002").update(title="writer"))
            parsed_after_plan.clear()
            return p

        def parse(text):
            parsed_after_plan.append(text)
            return real_parse(text)

        with mock.patch.object(pr_mod, "_plan_registry",
                               side_effect=plan_then_write), \
             mock.patch.object(pr_mod, "_parse_registry", side_effect=parse):
            r = pr_mod._ff_with_autostash(repo, "incoming")
        assert r.returncode == 0, r.stderr
        d = store.load(pm)
        assert _pr(d, "pr-002")["title"] == "writer"
        assert _pr(d, "pr-001")["updated_at"] == "local"
        assert [n["id"] for n in _pr(d, "pr-001")["notes"]] == ["note-in"]
        assert len(parsed_after_plan) == 1
        assert "writer" in parsed_after_plan[0]

    def test_clean_registry_updated_without_a_dirty_tree(self, tmp_path):
        repo = _init_repo(tmp_path)
        pm = _seed_project(repo)
        _incoming(repo, pm, _add_note("note-in", "x"))
        assert pr_mod._ff_with_autostash(repo, "incoming").returncode == 0
        assert _git("status", "--porcelain", cwd=repo).stdout == ""
        assert (pm / "project.yaml").read_text() == _git(
            "show", "incoming:pm/project.yaml", cwd=repo).stdout

    def test_failed_update_keeps_a_staged_registry_hunk(self, tmp_path):
        """The swap stages the incoming blob and the stash is taken against
        HEAD's entry; a failed update puts the user's staged hunk back."""
        repo = _init_repo(tmp_path)
        pm = _seed_project(repo)
        _with_code_overlap(repo, pm, _add_note("note-in", "x"))
        _edit(pm, lambda d: _pr(d, "pr-002").update(title="staged"))
        _git("add", "pm/project.yaml", cwd=repo)
        _edit(pm, lambda d: _pr(d, "pr-001").update(updated_at="unstaged"))
        staged = _git("ls-files", "-s", "pm/project.yaml", cwd=repo).stdout
        before = (pm / "project.yaml").read_bytes()

        with _failing_retry(), _spy_restore() as restore:
            r = pr_mod._ff_with_autostash(repo, "incoming")
        assert r.returncode != 0
        restore.assert_called_once()
        assert _git("ls-files", "-s", "pm/project.yaml",
                    cwd=repo).stdout == staged
        assert (pm / "project.yaml").read_bytes() == before
        assert (repo / "code.txt").read_text() == "v1 local\n"
        assert _stash_list(repo) == ""

    def test_writer_redirty_never_enters_text_stash(self, tmp_path,
                                                     monkeypatch):
        """Even a write that re-dirties the registry after pm swapped the
        merged one in cannot reach the text stash: the auto-stash names its
        paths and leaves the registry out."""
        repo = _init_repo(tmp_path)
        pm = _seed_project(repo)
        (repo / "code.txt").write_text("base\n")
        _git("add", "code.txt", cwd=repo)
        _git("commit", "-q", "-m", "code", cwd=repo)
        _incoming(repo, pm, _add_note("note-in", "x"),
                  files={"code.txt": "base\nincoming\n"})
        _edit(pm, lambda d: _pr(d, "pr-001").update(updated_at="local"))
        (repo / "code.txt").write_text("local change\n")
        real_apply = pr_mod._apply_registry
        stashed = []

        def racing(repo_, plan):
            ok = real_apply(repo_, plan)
            py = pm / "project.yaml"
            py.chmod(0o644)
            py.write_text(py.read_text() + "# writer re-dirty\n")
            return ok

        real_git = pr_mod.git_ops.run_git

        def run_git(*args, **kw):
            r = real_git(*args, **kw)
            if args[:2] == ("stash", "push"):
                stashed.append(real_git(
                    "stash", "show", "--include-untracked", "--name-only",
                    cwd=repo).stdout)
            return r

        monkeypatch.setattr(pr_mod, "_apply_registry", racing)
        with mock.patch.object(pr_mod.git_ops, "run_git",
                               side_effect=run_git):
            pr_mod._ff_with_autostash(repo, "incoming")
        assert stashed and "code.txt" in stashed[0]
        assert "project.yaml" not in stashed[0]
        assert store.find_conflict_markers(
            (pm / "project.yaml").read_text()) == []

    def test_target_ref_moving_while_planning_is_ignored(self, tmp_path):
        """The plan runs before the lock and can take seconds on a large
        registry; a concurrent fetch moving ``origin/<base>`` meanwhile must
        not make the fast-forward go to a commit whose registry the index
        was not staged with."""
        repo = _init_repo(tmp_path)
        pm = _seed_project(repo)
        _incoming(repo, pm, _add_note("note-in", "x"))
        planned = _git("rev-parse", "incoming", cwd=repo).stdout.strip()
        _git("checkout", "-q", "incoming", cwd=repo)
        _edit(pm, lambda d: _pr(d, "pr-002").update(description="newer"))
        _git("commit", "-qam", "newer", cwd=repo)
        newer = _git("rev-parse", "HEAD", cwd=repo).stdout.strip()
        _git("checkout", "-q", "master", cwd=repo)
        _git("update-ref", "refs/heads/incoming", planned, cwd=repo)
        _edit(pm, lambda d: _pr(d, "pr-002").update(title="local"))
        real_plan = pr_mod._plan_registry

        def plan_then_fetch(repo_, target):
            p = real_plan(repo_, target)
            _git("update-ref", "refs/heads/incoming", newer, cwd=repo)
            return p

        with mock.patch.object(pr_mod, "_plan_registry",
                               side_effect=plan_then_fetch):
            r = pr_mod._ff_with_autostash(repo, "incoming")
        assert r.returncode == 0, r.stderr
        assert _git("rev-parse", "HEAD", cwd=repo).stdout.strip() == planned
        d = store.load(pm)
        assert [n["id"] for n in _pr(d, "pr-001")["notes"]] == ["note-in"]
        assert _pr(d, "pr-002")["title"] == "local"
        assert _git("diff", "--cached", "--name-only", cwd=repo).stdout == ""

    def test_replans_when_another_update_moves_head_first(self, tmp_path):
        """Another update (a second merge) can fast-forward HEAD between this
        one's plan and its lock.  The stash must still be taken against the
        *current* HEAD's registry entry, or it carries a registry change and
        its pop is refused (the user's other files left unrestored)."""
        repo = _init_repo(tmp_path)
        pm = _seed_project(repo)
        (repo / "code.txt").write_text("a\nb\nc\nd\ne\n")
        _git("add", "code.txt", cwd=repo)
        _git("commit", "-q", "-m", "code", cwd=repo)
        _git("checkout", "-q", "-b", "incoming", cwd=repo)
        _edit(pm, _add_note("note-1", "first merge"))
        _git("commit", "-qam", "c1", cwd=repo)
        c1 = _git("rev-parse", "HEAD", cwd=repo).stdout.strip()
        _edit(pm, lambda d: _pr(d, "pr-002").update(description="c2"))
        (repo / "code.txt").write_text("A\nb\nc\nd\ne\n")
        _git("commit", "-qam", "c2", cwd=repo)
        _git("checkout", "-q", "master", cwd=repo)
        _edit(pm, lambda d: _pr(d, "pr-002").update(title="local"))
        (repo / "code.txt").write_text("a\nb\nc\nd\nE\n")   # stash path
        real_plan = pr_mod._plan_registry
        other = []

        def plan_then_other_update(repo_, target):
            p = real_plan(repo_, target)
            if not other:
                other.append(None)          # the other update plans too
                other[0] = pr_mod._ff_with_autostash(repo, c1)
            return p

        with mock.patch.object(pr_mod, "_plan_registry",
                               side_effect=plan_then_other_update):
            r = pr_mod._ff_with_autostash(repo, "incoming")
        assert other[0].returncode == 0, other[0].stderr
        assert r.returncode == 0, r.stderr
        assert (repo / "code.txt").read_text() == "A\nb\nc\nd\nE\n"
        assert _stash_list(repo) == ""
        d = store.load(pm)
        assert [n["id"] for n in _pr(d, "pr-001")["notes"]] == ["note-1"]
        assert _pr(d, "pr-002")["description"] == "c2"
        assert _pr(d, "pr-002")["title"] == "local"
        assert store.find_conflict_markers(
            (pm / "project.yaml").read_text()) == []

    def test_target_already_in_head_leaves_registry_alone(self, tmp_path):
        """An update to a commit HEAD already contains is a no-op ("Already
        up to date").  Merging toward that commit's older registry reverted
        the newer committed changes in the live state and staged the old
        blob (review c6a2 i3)."""
        repo = _init_repo(tmp_path)
        pm = _seed_project(repo)
        old = _git("rev-parse", "HEAD", cwd=repo).stdout.strip()
        _edit(pm, _add_note("note-1", "committed after old"))
        _git("commit", "-qam", "c1", cwd=repo)
        _edit(pm, lambda d: _pr(d, "pr-002").update(title="local"))
        before = (pm / "project.yaml").read_text()

        r = pr_mod._ff_with_autostash(repo, old)
        assert r.returncode == 0, r.stderr
        assert (pm / "project.yaml").read_text() == before
        assert _git("diff", "--cached", "--name-only", cwd=repo).stdout == ""

    def test_other_update_moving_head_past_the_target_reverts_nothing(
            self, tmp_path):
        """Two concurrent updates: the other one fast-forwards HEAD *past*
        this one's pinned target while this one plans.  Re-planning under the
        lock must not merge toward the older target (that reverted the newer
        commit's registry changes and staged the older blob)."""
        repo = _init_repo(tmp_path)
        pm = _seed_project(repo)
        _git("checkout", "-q", "-b", "incoming", cwd=repo)
        _edit(pm, _add_note("note-1", "first merge"))
        _git("commit", "-qam", "c1", cwd=repo)
        c1 = _git("rev-parse", "HEAD", cwd=repo).stdout.strip()
        _edit(pm, lambda d: _pr(d, "pr-002").update(description="c2"))
        _git("commit", "-qam", "c2", cwd=repo)
        c2 = _git("rev-parse", "HEAD", cwd=repo).stdout.strip()
        _git("checkout", "-q", "master", cwd=repo)
        _edit(pm, lambda d: _pr(d, "pr-002").update(title="local"))
        real_plan = pr_mod._plan_registry
        other = []

        def plan_then_other_update(repo_, target):
            p = real_plan(repo_, target)
            if not other:
                other.append(None)
                other[0] = pr_mod._ff_with_autostash(repo, c2)
            return p

        with mock.patch.object(pr_mod, "_plan_registry",
                               side_effect=plan_then_other_update):
            r = pr_mod._ff_with_autostash(repo, c1)
        assert other[0].returncode == 0, other[0].stderr
        assert r.returncode == 0, r.stderr
        assert _git("rev-parse", "HEAD", cwd=repo).stdout.strip() == c2
        d = store.load(pm)
        assert [n["id"] for n in _pr(d, "pr-001")["notes"]] == ["note-1"]
        assert _pr(d, "pr-002")["description"] == "c2"
        assert _pr(d, "pr-002")["title"] == "local"
        assert _git("diff", "--cached", "--name-only", cwd=repo).stdout == ""


# ---------------------------------------------------------------------------
# Locking: concurrent writers serialize against the whole fast-forward
# ---------------------------------------------------------------------------

class TestRegistryLock:
    def test_lock_held_during_every_git_step(self, tmp_path):
        """Held during the first fast-forward too (no overlap needed): a
        writer that loaded before git rewrote the registry must not save over
        the merged file."""
        repo = _init_repo(tmp_path)
        pm = _seed_project(repo)
        _incoming(repo, pm, _add_note("note-in", "x"))
        _edit(pm, lambda d: _pr(d, "pr-002").update(title="local"))
        probes = []
        real = pr_mod.git_ops.run_git

        def run_git(*args, **kw):
            # Every step that rewrites files (reaping: see
            # test_reaping_runs_under_the_lock).
            if args[0] in ("merge", "checkout", "update-index") or \
                    args[:2] in (("stash", "push"), ("stash", "pop")):
                try:
                    with store._lock(pm, timeout=0):
                        probes.append((args[:2], "free"))
                except store.StoreLockTimeout:
                    probes.append((args[:2], "held"))
            return real(*args, **kw)

        with mock.patch.object(pr_mod.git_ops, "run_git",
                               side_effect=run_git):
            assert pr_mod._ff_with_autostash(repo, "incoming").returncode == 0
        assert probes and all(state == "held" for _, state in probes), probes
        with store._lock(pm, timeout=0):
            pass                                  # released afterwards

    def test_reaping_runs_under_the_lock(self, tmp_path):
        """Every pm auto-stash push and pop happens under the registry lock.
        A reaper running outside it could take another update's in-flight
        auto-stash (stored, files not yet reverted) for an applied leftover
        and drop it, or drop by a position that update's pop then reuses."""
        repo = _init_repo(tmp_path)
        pm = _seed_project(repo)
        (repo / "a.txt").write_text("base\n")
        _git("add", "a.txt", cwd=repo)
        _git("commit", "-q", "-m", "a", cwd=repo)
        (repo / "a.txt").write_text("applied\n")
        _git("stash", "push", "-m", "pm: auto-stash for merge", cwd=repo)
        (repo / "a.txt").write_text("applied\n")          # leaked, applied
        _incoming(repo, pm, _add_note("note-in", "x"))
        probes = []
        real = pr_mod.git_ops.run_git

        def run_git(*args, **kw):
            if args[:2] in (("stash", "list"), ("stash", "drop")):
                try:
                    with store._lock(pm, timeout=0):
                        probes.append((args[:2], "free"))
                except store.StoreLockTimeout:
                    probes.append((args[:2], "held"))
            return real(*args, **kw)

        with mock.patch.object(pr_mod.git_ops, "run_git",
                               side_effect=run_git):
            assert pr_mod._ff_with_autostash(repo, "incoming").returncode == 0
        assert (("stash", "drop"), "held") in probes, probes
        assert all(state == "held" for _, state in probes), probes
        assert _stash_list(repo) == ""

    def test_no_reaping_without_the_registry_lock(self, tmp_path):
        """A repo without pm's registry (a standalone pm dir) has no lock
        serializing pm's auto-stash pushes and pops, so the reaper could
        race another update's in-flight auto-stash there: it does not run,
        and a leaked one stays for the user."""
        repo = _init_repo(tmp_path)
        (repo / "a.txt").write_text("base\n")
        _git("add", "a.txt", cwd=repo)
        _git("commit", "-q", "-m", "a", cwd=repo)
        (repo / "a.txt").write_text("applied\n")
        _git("stash", "push", "-m", "pm: auto-stash for merge", cwd=repo)
        (repo / "a.txt").write_text("applied\n")
        _incoming(repo, None)                  # commits a.txt = "applied"

        assert pr_mod._ff_with_autostash(repo, "incoming").returncode == 0
        assert (repo / "a.txt").read_text() == "applied\n"    # applied...
        assert "pm: auto-stash for merge" in _stash_list(repo)  # ...kept

    def test_project_set_writes_under_the_lock(self, tmp_path):
        """``pm project set`` did an unlocked load + save, so it could save a
        registry loaded before a merge over the merged one."""
        from pm_core.cli import project as project_mod
        pm = _seed_project(_init_repo(tmp_path))
        with mock.patch.object(project_mod, "state_root", return_value=pm):
            with store._lock(pm), \
                 pytest.raises(store.StoreLockTimeout):
                project_mod._set_project_bool("skip-qa", True)
            project_mod._set_project_bool("skip-qa", True)
        assert store.load(pm)["project"]["skip_qa"] is True

    def test_busy_lock_leaves_checkout_untouched(self, tmp_path, capsys):
        repo = _init_repo(tmp_path)
        pm = _seed_project(repo)
        _incoming(repo, pm, _add_note("note-in", "x"))
        _edit(pm, lambda d: _pr(d, "pr-001").update(updated_at="local"))
        before = (pm / "project.yaml").read_bytes()
        head = _git("rev-parse", "HEAD", cwd=repo).stdout

        with store._lock(pm), \
             mock.patch.object(pr_mod, "_MERGE_STASH_LOCK_TIMEOUT", 0.2):
            r = pr_mod._ff_with_autostash(repo, "incoming")
        assert r.returncode != 0
        assert isinstance(r, pr_mod._RegistryLockBusy)
        assert "Could not acquire lock" in r.stderr
        assert (pm / "project.yaml").read_bytes() == before
        assert _git("rev-parse", "HEAD", cwd=repo).stdout == head
        assert _stash_list(repo) == ""

    def test_concurrent_writer_notes_all_survive(self, tmp_path):
        """#253 S74 / QA S3 shape: a pm writer adding notes in a loop while
        the merge reconciles.  Every note survives, the merged-in note too,
        and no marker or stash is ever left."""
        for attempt in range(3):
            base = tmp_path / f"run{attempt}"
            base.mkdir()
            repo = _init_repo(base)
            pm = _seed_project(repo)
            (repo / "code.txt").write_text("v1\n")
            _git("add", "code.txt", cwd=repo)
            _git("commit", "-q", "-m", "code", cwd=repo)
            _incoming(repo, pm, _add_note("note-in", "branch"))
            _edit(pm, lambda d: _pr(d, "pr-001").update(updated_at="local"))
            (repo / "code.txt").write_text("v1\nlocal\n")
            stop = threading.Event()
            written, errors = [], []

            def writer():
                i = 0
                while not stop.is_set() or i < 5:
                    nid = f"note-w{i}"

                    def fn(d, nid=nid):
                        _pr(d, "pr-002").setdefault("notes", []).append(
                            {"id": nid, "text": nid})
                    try:
                        store.locked_update(pm, fn, timeout=10)
                        written.append(nid)
                    except Exception as e:      # pragma: no cover
                        errors.append(e)
                    i += 1
                    # Real writers are separate `pm` processes; a thread that
                    # re-takes the lock instantly would starve the merge's
                    # polling acquire (it then fails safe after 10 s).
                    time.sleep(0.02)

            t = threading.Thread(target=writer)
            t.start()
            try:
                r = pr_mod._ff_with_autostash(repo, "incoming")
            finally:
                stop.set()
                t.join(30)
            assert r.returncode == 0, r.stderr
            assert not errors
            d = store.load(pm)
            ids = [n["id"] for n in _pr(d, "pr-002").get("notes", [])]
            assert ids == written
            assert [n["id"] for n in _pr(d, "pr-001")["notes"]] == ["note-in"]
            assert store.find_conflict_markers(
                (pm / "project.yaml").read_text()) == []
            assert (repo / "code.txt").read_text() == "v1\nlocal\n"
            assert _stash_list(repo) == ""


# ---------------------------------------------------------------------------
# Stash restore failures and leaked-stash reaping
# ---------------------------------------------------------------------------

class TestStashRestoreAndReap:
    def test_conflicted_pop_keeps_stash_and_registry_valid(self, tmp_path,
                                                           capsys):
        repo = _init_repo(tmp_path)
        pm = _seed_project(repo)
        (repo / "my code.txt").write_text("base\n")
        _git("add", "my code.txt", cwd=repo)
        _git("commit", "-q", "-m", "code", cwd=repo)
        _incoming(repo, pm, _add_note("note-in", "x"),
                  files={"my code.txt": "incoming edit\n"})
        _edit(pm, lambda d: _pr(d, "pr-001").update(updated_at="local"))
        (repo / "my code.txt").write_text("local edit\n")

        with mock.patch.object(pr_mod, "_launch_merge_window") as launch:
            r = pr_mod._ff_with_autostash(repo, "incoming")
        assert r.returncode == 0                  # the update itself landed
        launch.assert_not_called()                # no merge-time session
        err = capsys.readouterr().err
        assert "conflicted in: my code.txt." in err   # raw path, not split
        assert "git stash drop stash@{0}" in err
        assert "auto-stash for merge" in _stash_list(repo)   # kept
        d = store.load(pm)
        assert _pr(d, "pr-001")["updated_at"] == "local"
        assert [n["id"] for n in _pr(d, "pr-001")["notes"]] == ["note-in"]

    @pytest.mark.parametrize("show_untracked", [None, "no"])
    def test_refused_pop_keeps_stash_intact(self, tmp_path, capsys,
                                            show_untracked):
        """git refuses the pop outright (an untracked stashed file now exists
        from the merge): nothing applied, nothing lost, stash kept.  A user's
        ``status.showUntrackedFiles=no`` does not stop the stash either."""
        repo = _init_repo(tmp_path)
        pm = _seed_project(repo)
        if show_untracked:
            _git("config", "status.showUntrackedFiles", show_untracked,
                 cwd=repo)
        _incoming(repo, pm, files={"new.txt": "from the branch\n"})
        (repo / "new.txt").write_text("mine\n")

        r = pr_mod._ff_with_autostash(repo, "incoming")
        assert r.returncode == 0
        err = capsys.readouterr().err
        assert "Nothing was lost" in err
        assert "auto-stash for merge" in _stash_list(repo)
        shown = _git("show", "stash@{0}^3:new.txt", cwd=repo).stdout
        assert shown == "mine\n"

    @staticmethod
    def _assert_partial_restore_hint(err):
        """A second pop would refuse on what is already restored: say so,
        and finish with a drop after restoring the rest by hand."""
        assert "may have restored part of them already" in err
        assert "`git stash pop stash@{0}` then refuses again" in err
        assert "`git show stash@{0}^3:<path>`" in err
        assert err.rstrip().endswith("`git stash drop stash@{0}`.")

    def test_partly_refused_pop_does_not_suggest_popping_again(
            self, tmp_path, capsys):
        """git >= 2.34 restores a stash's tracked changes before it refuses
        an untracked file that now exists, so a second `git stash pop` would
        refuse on code.txt (seen on 2.34)."""
        repo = _init_repo(tmp_path)
        pm = _seed_project(repo)
        (repo / "code.txt").write_text("v1\n")
        _git("add", "code.txt", cwd=repo)
        _git("commit", "-q", "-m", "code", cwd=repo)
        _incoming(repo, pm, files={"new.txt": "from the branch\n"})
        (repo / "code.txt").write_text("v1 local\n")      # stashed too
        (repo / "new.txt").write_text("mine\n")

        r = pr_mod._ff_with_autostash(repo, "incoming")
        assert r.returncode == 0
        assert "auto-stash for merge" in _stash_list(repo)
        self._assert_partial_restore_hint(capsys.readouterr().err)

    def test_pop_whose_drop_fails_does_not_suggest_popping_again(
            self, tmp_path, capsys):
        """`git stash pop` is apply + drop: when only the drop fails (e.g.
        another stash command holds refs/stash.lock) every change is back
        and the stash is kept."""
        repo = _init_repo(tmp_path)
        pm = _seed_project(repo)
        (repo / "code.txt").write_text("a\nb\nc\nd\ne\n")
        _git("add", "code.txt", cwd=repo)
        _git("commit", "-q", "-m", "code", cwd=repo)
        _incoming(repo, pm, files={"code.txt": "A\nb\nc\nd\ne\n"})
        (repo / "code.txt").write_text("a\nb\nc\nd\nE\n")
        real = pr_mod.git_ops.run_git

        def run_git(*args, **kw):
            if args[:2] == ("stash", "pop"):
                real("stash", "apply", *args[2:], **kw)
                return subprocess.CompletedProcess(
                    args, 1, "", "error: cannot lock ref 'refs/stash'")
            return real(*args, **kw)

        with mock.patch.object(pr_mod.git_ops, "run_git",
                               side_effect=run_git):
            r = pr_mod._ff_with_autostash(repo, "incoming")
        assert r.returncode == 0
        assert (repo / "code.txt").read_text() == "A\nb\nc\nd\nE\n"
        assert "auto-stash for merge" in _stash_list(repo)
        self._assert_partial_restore_hint(capsys.readouterr().err)

    def test_leaked_auto_stashes_reaped_only_when_already_applied(
            self, tmp_path, capsys):
        repo = _init_repo(tmp_path)
        pm = _seed_project(repo)
        for name in ("a.txt", "b.txt"):
            (repo / name).write_text("base\n")
        _git("add", "-A", cwd=repo)
        _git("commit", "-q", "-m", "files", cwd=repo)
        msg = "pm: auto-stash for merge"
        # Unrelated WIP stash: never touched.
        (repo / "a.txt").write_text("wip\n")
        _git("stash", "push", "-m", "important WIP refactor", cwd=repo)
        # Leaked auto-stash whose change was applied since → reaped.
        (repo / "a.txt").write_text("applied\n")
        _git("stash", "push", "-m", msg, cwd=repo)
        (repo / "a.txt").write_text("applied\n")
        _git("commit", "-qam", "applied by hand", cwd=repo)
        # Leaked auto-stash whose change is NOT in the tree → kept.
        (repo / "b.txt").write_text("never restored\n")
        _git("stash", "push", "-m", msg, cwd=repo)
        lost = _git("rev-parse", "stash@{0}", cwd=repo).stdout.strip()
        # Leaked auto-stash holding a registry note that is in the live
        # registry now (with newer bookkeeping) → reaped structurally.
        _edit(pm, _add_note("note-old", "x", "2026-02-02T00:00:00"))
        _git("stash", "push", "-m", msg, cwd=repo)
        _edit(pm, _add_note("note-old", "x", "2026-02-02T00:00:00"))
        _edit(pm, lambda d: _pr(d, "pr-001").update(updated_at="newer"))
        _git("commit", "-qam", "registry", cwd=repo)
        _incoming(repo, pm, files={"c.txt": "c\n"})

        r = pr_mod._ff_with_autostash(repo, "incoming")
        assert r.returncode == 0
        listing = _stash_list(repo)
        assert listing.count(msg) == 1
        assert "important WIP refactor" in listing
        assert _git("rev-parse", "stash@{0}", cwd=repo).stdout.strip() == lost
        out = capsys.readouterr()
        assert "Dropped 2 leaked pm auto-stash" in out.out
        assert "stash@{0}" in out.err

    def test_leaked_rename_kept_until_the_old_path_is_gone(self, tmp_path):
        """A stashed rename removes the old path too.  Rename detection
        listed only the new one, so a tree holding the new file next to the
        old one counted as applied."""
        repo = _init_repo(tmp_path)
        pm = _seed_project(repo)
        (repo / "old.txt").write_text("a\nb\nc\n")
        _git("add", "-A", cwd=repo)
        _git("commit", "-q", "-m", "old", cwd=repo)
        _git("mv", "old.txt", "new.txt", cwd=repo)
        _git("stash", "push", "-m", "pm: auto-stash for merge", cwd=repo)
        (repo / "new.txt").write_text("a\nb\nc\n")   # old.txt still there
        _incoming(repo, pm, files={"c.txt": "c\n"})

        assert pr_mod._ff_with_autostash(repo, "incoming").returncode == 0
        assert "pm: auto-stash for merge" in _stash_list(repo)   # kept

        (repo / "old.txt").unlink()                   # now fully applied
        _git("checkout", "-q", "-b", "next", cwd=repo)
        (repo / "d.txt").write_text("d\n")
        _git("add", "d.txt", cwd=repo)
        _git("commit", "-q", "-m", "d", cwd=repo)
        _git("checkout", "-q", "master", cwd=repo)
        assert pr_mod._ff_with_autostash(repo, "next").returncode == 0
        assert _stash_list(repo) == ""                # reaped


# ---------------------------------------------------------------------------
# _resolve_project_yaml_pop (registry reached a text stash some other way)
# ---------------------------------------------------------------------------

class TestResolveProjectYamlPop:
    def test_resolves_registry_conflict_from_a_text_stash(self, tmp_path):
        repo = _init_repo(tmp_path)
        pm = _seed_project(repo)
        _edit(pm, lambda d: _pr(d, "pr-001").update(updated_at="live"))
        _git("stash", "push", "-m", "user stash", cwd=repo)
        _edit(pm, _add_note("note-c", "committed", "2026-02-02T00:00:00"))
        _git("commit", "-qam", "committed", cwd=repo)
        assert _git("stash", "pop", cwd=repo).returncode != 0

        assert pr_mod._resolve_project_yaml_pop(repo) is True
        d = store.load(pm)
        assert _pr(d, "pr-001")["updated_at"] == "live"
        assert [n["id"] for n in _pr(d, "pr-001")["notes"]] == ["note-c"]
        assert _stash_list(repo) == ""

    def test_leaves_a_non_registry_project_yaml_alone(self, tmp_path):
        repo = _init_repo(tmp_path)
        _seed_project(repo)
        cfg = repo / "docs" / "project.yaml"
        cfg.parent.mkdir()
        cfg.write_text("name: base\n")
        _git("add", "-A", cwd=repo)
        _git("commit", "-q", "-m", "cfg", cwd=repo)
        cfg.write_text("name: mine\n")
        _git("stash", "push", cwd=repo)
        cfg.write_text("name: theirs\n")
        _git("commit", "-qam", "theirs", cwd=repo)
        assert _git("stash", "pop", cwd=repo).returncode != 0

        assert pr_mod._resolve_project_yaml_pop(repo) is False
        assert "<<<<<<<" in cfg.read_text()        # left for the user
        assert _stash_list(repo) != ""
