"""Tests for pr-ca6981c: pm merge's stash/pop must not corrupt project.yaml.

Covers three symptoms of using git's *text* stash/pop to reconcile concurrent
project.yaml edits across a merge:

1. CORRUPTION — conflict markers written into project.yaml.
2. STASH LEAK — a conflicted pop leaves the auto-stash behind.
3. store.load giving a cryptic YAML traceback instead of a clear message.

Plus the structured-merge core (store.three_way_merge) and the
_dirty_file_paths path-mangling regression that the fix depends on.
"""

import subprocess
from pathlib import Path
from unittest import mock

import pytest

from pm_core import store
from pm_core.cli import pr as pr_mod


def _git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def _init_repo(tmp_path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", "-q", cwd=repo)
    _git("config", "user.email", "t@t", cwd=repo)
    _git("config", "user.name", "t", cwd=repo)
    return repo


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
        linenos = [n for n, _ in hits]
        assert linenos == [2, 4, 6, 8]

    def test_benign_equals_in_value_not_flagged(self):
        # A value containing '===' or trailing equals must not trip the check.
        text = "key: 'a======='\ntoken: ab==\nbar: '======= not a marker'\n"
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


# ---------------------------------------------------------------------------
# store.three_way_merge
# ---------------------------------------------------------------------------

class TestThreeWayMerge:
    def test_only_theirs_changed_takes_theirs(self):
        base = {"a": 1}
        ours = {"a": 1}
        theirs = {"a": 2}
        assert store.three_way_merge(base, ours, theirs) == {"a": 2}

    def test_only_ours_changed_takes_ours(self):
        base = {"a": 1}
        ours = {"a": 9}
        theirs = {"a": 1}
        assert store.three_way_merge(base, ours, theirs) == {"a": 9}

    def test_both_changed_prefers_ours(self):
        base = {"updated_at": "t0"}
        ours = {"updated_at": "t1"}
        theirs = {"updated_at": "t2"}
        assert store.three_way_merge(base, ours, theirs) == {"updated_at": "t1"}

    def test_prs_origin_only_pr_added(self):
        base = {"prs": [{"id": "pr-001", "status": "in_review"}]}
        # ours gained pr-002 (e.g. merged in from origin)
        ours = {"prs": [{"id": "pr-001", "status": "in_review"},
                        {"id": "pr-002", "status": "merged"}]}
        theirs = {"prs": [{"id": "pr-001", "status": "in_review"}]}
        merged = store.three_way_merge(base, ours, theirs)
        ids = {p["id"] for p in merged["prs"]}
        assert ids == {"pr-001", "pr-002"}

    def test_prs_local_only_pr_kept(self):
        base = {"prs": [{"id": "pr-001", "status": "in_review"}]}
        ours = {"prs": [{"id": "pr-001", "status": "in_review"}]}
        # theirs (local) started pr-003
        theirs = {"prs": [{"id": "pr-001", "status": "in_review"},
                          {"id": "pr-003", "status": "in_progress"}]}
        merged = store.three_way_merge(base, ours, theirs)
        ids = {p["id"] for p in merged["prs"]}
        assert ids == {"pr-001", "pr-003"}

    def test_same_pr_field_level_merge(self):
        # ours advanced status; theirs touched a different field.
        base = {"prs": [{"id": "pr-001", "status": "in_review", "note": "a"}]}
        ours = {"prs": [{"id": "pr-001", "status": "merged", "note": "a"}]}
        theirs = {"prs": [{"id": "pr-001", "status": "in_review", "note": "b"}]}
        merged = store.three_way_merge(base, ours, theirs)
        pr = merged["prs"][0]
        assert pr["status"] == "merged"  # only ours changed it
        assert pr["note"] == "b"         # only theirs changed it


# ---------------------------------------------------------------------------
# _dirty_file_paths regression (fix the off-by-one path mangling)
# ---------------------------------------------------------------------------

class TestDirtyFilePaths:
    def test_worktree_only_change_path_intact(self, tmp_path):
        repo = _init_repo(tmp_path)
        pm = repo / "pm"
        pm.mkdir()
        store.save({"project": {}, "prs": [], "plans": []}, pm)
        _git("add", "-A", cwd=repo)
        _git("commit", "-q", "-m", "base", cwd=repo)
        # Worktree-only modification → porcelain " M pm/project.yaml"
        store.save({"project": {"x": 1}, "prs": [], "plans": []}, pm)
        paths = pr_mod._dirty_file_paths(repo)
        assert paths == ["pm/project.yaml"]


# ---------------------------------------------------------------------------
# Real-git integration: stash reconciliation across a merge
# ---------------------------------------------------------------------------

def _seed_project(repo) -> Path:
    pm = repo / "pm"
    pm.mkdir()
    store.save(
        {"project": {"name": "x", "base_branch": "master", "backend": "local"},
         "prs": [{"id": "pr-001", "status": "in_review",
                  "updated_at": "2026-01-01T00:00:00"}],
         "plans": []},
        pm,
    )
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "base", cwd=repo)
    return pm


class TestPersistWithBackoff:
    """pr-d887f4c class: a transient lock timeout must not orphan a just-created
    GitHub PR (persist the gh_pr_number with backoff)."""

    def test_succeeds_after_transient_timeout(self, tmp_path):
        root = tmp_path / "pm"
        root.mkdir()
        store.save({"project": {}, "prs": [{"id": "pr-001"}], "plans": []}, root)
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


class TestStashReconciliation:
    def test_concurrent_edit_across_merge_no_corruption(self, tmp_path):
        """The core pr-ca6981c repro: concurrent project.yaml edits across a
        merge must not corrupt the file or leak a stash."""
        repo = _init_repo(tmp_path)
        pm = _seed_project(repo)

        # An "incoming" branch changes updated_at (simulates merged-in change).
        _git("checkout", "-q", "-b", "incoming", cwd=repo)
        d = store.load(pm)
        d["prs"][0]["updated_at"] = "2026-02-02T02:02:02"
        store.save(d, pm)
        _git("commit", "-qam", "incoming", cwd=repo)
        _git("checkout", "-q", "master", cwd=repo)

        # Local concurrent (uncommitted) edit with a DIFFERENT updated_at.
        d = store.load(pm)
        d["prs"][0]["updated_at"] = "2026-03-03T03:03:03"
        store.save(d, pm)

        info = pr_mod._stash_for_merge(repo, lock_tui=False)
        assert info is not None
        # project.yaml was reverted (clean) before merge — not text-stashed.
        assert info["py"] is not None
        assert info["stashed"] is False

        merge = _git("merge", "--no-ff", "incoming", "-m", "merge", cwd=repo)
        assert merge.returncode == 0

        clean = pr_mod._unstash_after_merge(repo, info)
        assert clean is True

        text = (pm / "project.yaml").read_text()
        assert "<<<<<<<" not in text           # (b) no conflict markers
        assert store.find_conflict_markers(text) == []
        data = store.load(pm)                   # (a) valid YAML
        assert data["prs"][0]["status"] == "in_review"
        stash_list = _git("stash", "list", cwd=repo).stdout
        assert stash_list.strip() == ""         # (c) no stash left behind

    def test_finalize_succeeds_after_reconciliation(self, tmp_path):
        """(d) After reconciliation the PR finalizes to status=merged with
        merged_at set — the load that previously died on conflict markers now
        succeeds."""
        repo = _init_repo(tmp_path)
        pm = _seed_project(repo)

        _git("checkout", "-q", "-b", "incoming", cwd=repo)
        d = store.load(pm)
        d["prs"][0]["updated_at"] = "2026-02-02T02:02:02"
        store.save(d, pm)
        _git("commit", "-qam", "incoming", cwd=repo)
        _git("checkout", "-q", "master", cwd=repo)

        d = store.load(pm)
        d["prs"][0]["updated_at"] = "2026-03-03T03:03:03"
        store.save(d, pm)

        info = pr_mod._stash_for_merge(repo, lock_tui=False)
        _git("merge", "--no-ff", "incoming", "-m", "merge", cwd=repo)
        pr_mod._unstash_after_merge(repo, info)

        pr_entry = store.load(pm)["prs"][0]
        with mock.patch.object(pr_mod, "trigger_tui_refresh"), \
             mock.patch("pm_core.cli.helpers._find_tui_pane",
                        return_value=(None, None)):
            pr_mod._finalize_merge(pm, pr_entry, "pr-001")

        final = store.load(pm)["prs"][0]
        assert final["status"] == "merged"
        assert final.get("merged_at")

    def test_leaked_auto_stash_reaped(self, tmp_path):
        """A previously-leaked 'pm: auto-stash for merge' is reaped; unrelated
        WIP stashes are left alone."""
        repo = _init_repo(tmp_path)
        pm = _seed_project(repo)

        # Pre-existing unrelated WIP stash.
        (repo / "wip.txt").write_text("wip")
        _git("add", "wip.txt", cwd=repo)
        _git("stash", "push", "-m", "important WIP refactor", cwd=repo)
        # A leaked auto-stash from a prior failed merge.
        (repo / "leak.txt").write_text("leak")
        _git("add", "leak.txt", cwd=repo)
        _git("stash", "push", "-m", "pm: auto-stash for merge", cwd=repo)

        # Run a clean reconciliation (only project.yaml dirty → no new stash).
        d = store.load(pm)
        d["prs"][0]["updated_at"] = "2026-04-04T04:04:04"
        store.save(d, pm)
        info = pr_mod._stash_for_merge(repo, lock_tui=False)
        pr_mod._unstash_after_merge(repo, info)

        listing = _git("stash", "list", cwd=repo).stdout
        assert "auto-stash for merge" not in listing  # reaped
        assert "important WIP refactor" in listing     # preserved

    def test_non_project_file_also_dirty_stashed_and_restored(self, tmp_path):
        """When a non-project.yaml file is also dirty it is stashed normally and
        restored, while project.yaml is reconciled structurally."""
        repo = _init_repo(tmp_path)
        pm = _seed_project(repo)
        (repo / "code.txt").write_text("v1\n")
        _git("add", "code.txt", cwd=repo)
        _git("commit", "-qam", "add code", cwd=repo)

        # incoming changes project.yaml only
        _git("checkout", "-q", "-b", "incoming", cwd=repo)
        d = store.load(pm)
        d["prs"][0]["updated_at"] = "2026-02-02T02:02:02"
        store.save(d, pm)
        _git("commit", "-qam", "incoming", cwd=repo)
        _git("checkout", "-q", "master", cwd=repo)

        # local: dirty project.yaml AND dirty code.txt (no overlap with merge)
        d = store.load(pm)
        d["prs"][0]["updated_at"] = "2026-03-03T03:03:03"
        store.save(d, pm)
        (repo / "code.txt").write_text("v1\nlocal change\n")

        info = pr_mod._stash_for_merge(repo, lock_tui=False)
        assert info["py"] is not None
        assert info["stashed"] is True

        _git("merge", "--no-ff", "incoming", "-m", "merge", cwd=repo)
        clean = pr_mod._unstash_after_merge(repo, info)
        assert clean is True

        assert "<<<<<<<" not in (pm / "project.yaml").read_text()
        assert (repo / "code.txt").read_text() == "v1\nlocal change\n"
        assert _git("stash", "list", cwd=repo).stdout.strip() == ""
