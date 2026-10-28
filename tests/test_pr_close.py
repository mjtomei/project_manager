"""Regression tests for `pm pr close` (pr-62ad13d).

Closing a PR is a lifecycle action, not a delete: the registry entry, its
notes/dependencies/description, the remote branch, and the local workdir (with
every tracked, dirty, untracked, ignored file and capture) must survive.

All tests run against disposable tmp projects and the fake GitHub transport
(``FakeGitHubBackend``); nothing here touches a real GitHub PR, branch, or
workdir.
"""

from __future__ import annotations

import hashlib
import subprocess
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from click.testing import CliRunner

from pm_core import graph, store
from pm_core import pr_sync
from pm_core.cli import pr as pr_mod
from pm_core.fake_github import REAL_GIT, FakeGitHubBackend

NOW = "2026-10-01T00:00:00+00:00"
LIFECYCLE_KEYS = {"status", "updated_at", "closed_at"}


# ---------------------------------------------------------------------------
# fixtures / helpers
# ---------------------------------------------------------------------------

def _git(path: Path, *args: str) -> None:
    subprocess.run([REAL_GIT, *args], cwd=path, check=True,
                   capture_output=True, text=True)


def _make_workdir(path: Path) -> None:
    """A dirty git workdir: tracked edit, untracked, ignored, captures."""
    path.mkdir(parents=True)
    _git(path, "init", "-q", "-b", "master")
    _git(path, "config", "user.email", "close@example.com")
    _git(path, "config", "user.name", "Close Test")
    _git(path, "config", "commit.gpgsign", "false")
    (path / "tracked.txt").write_text("original\n")
    (path / ".gitignore").write_text(".cache/\n")
    _git(path, "add", "-A")
    _git(path, "commit", "-qm", "init")
    # tracked modification
    (path / "tracked.txt").write_text("original\nlocal edit\n")
    # untracked
    (path / "untracked.txt").write_text("untracked work\n")
    # ignored
    (path / ".cache").mkdir()
    (path / ".cache" / "blob.bin").write_bytes(b"\x00\x01\x02")
    # evidence / captures
    (path / "captures" / "qa").mkdir(parents=True)
    (path / "captures" / "qa" / "log.txt").write_text("evidence\n")


def _snapshot(root: Path) -> dict[str, str]:
    """sha256 of every file under *root* (including .git), by relpath."""
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def _entry(pr_id: str, **overrides) -> dict:
    entry = {
        "id": pr_id,
        "plan": None,
        "title": f"Title of {pr_id}",
        "branch": f"pm/{pr_id}",
        "status": "in_review",
        "depends_on": [],
        "description": f"Description of {pr_id} that must survive.",
        "agent_machine": None,
        "gh_pr": None,
        "gh_pr_number": None,
        "created_at": NOW,
        "updated_at": NOW,
        "started_at": NOW,
        "reviewed_at": NOW,
        "merged_at": None,
        "workdir": None,
        "notes": [{"id": "n1", "text": "Superseded by #167; keep me.",
                   "created_at": NOW}],
    }
    entry.update(overrides)
    return entry


def _make_project(tmp_path: Path, *, workdir: bool = True,
                  gh_pr_number: int | None = None,
                  status: str = "in_review",
                  with_dependent: bool = True,
                  extra_prs: list[dict] | None = None) -> dict:
    pm_dir = tmp_path / "pm"
    pm_dir.mkdir()
    wd_path = tmp_path / "workdir"
    if workdir:
        _make_workdir(wd_path)
    pr = _entry("pr-001", status=status, workdir=str(wd_path) if workdir else None,
                gh_pr_number=gh_pr_number,
                gh_pr=(f"https://github.com/o/r/pull/{gh_pr_number}"
                       if gh_pr_number else None))
    prs = [pr]
    if with_dependent:
        prs.append(_entry("pr-002", title="Dependent work", status="pending",
                          branch="pm/pr-002", depends_on=["pr-001"],
                          notes=[], workdir=None))
    prs.extend(extra_prs or [])
    store.save({
        "project": {"name": "close-test", "repo": str(tmp_path),
                    "base_branch": "master", "backend": "github",
                    "active_pr": "pr-001"},
        "prs": prs,
        "plans": [],
    }, pm_dir)
    return {"pm_dir": pm_dir, "workdir": wd_path, "entry": pr}


@contextmanager
def _fake_gh(backend: FakeGitHubBackend | None = None):
    backend = backend or FakeGitHubBackend()
    with backend.installed():
        yield backend


def _run_close(pm_dir: Path, *args: str):
    runner = CliRunner()
    with mock.patch.object(pr_mod, "state_root", return_value=pm_dir), \
         mock.patch.object(pr_mod, "trigger_tui_refresh"):
        return runner.invoke(pr_mod.pr, ["close", *args])


def _load_entry(pm_dir: Path, pr_id: str = "pr-001") -> dict | None:
    return store.get_pr(store.load(pm_dir), pr_id)


def _close_calls(backend: FakeGitHubBackend) -> list[list[str]]:
    return [c for c in backend.calls if c[:2] == ["pr", "close"]]


# ---------------------------------------------------------------------------
# default close: retain everything
# ---------------------------------------------------------------------------

def test_default_close_retains_entry_and_lifecycle_fields(tmp_path):
    project = _make_project(tmp_path)
    before = _load_entry(project["pm_dir"])
    with _fake_gh() as backend:
        backend.add_pr(head="pm/pr-001")
        result = _run_close(project["pm_dir"], "pr-001")

    assert result.exit_code == 0, result.output
    after = _load_entry(project["pm_dir"])
    assert after is not None, "close must keep the registry entry"
    assert after["status"] == "closed"
    assert after.get("closed_at")
    assert after["updated_at"] != before["updated_at"]

    # Everything except the intended lifecycle fields is identical.
    strip = lambda d: {k: v for k, v in d.items() if k not in LIFECYCLE_KEYS}
    assert strip(after) == strip(before)
    assert after["notes"] == before["notes"]
    assert after["depends_on"] == before["depends_on"]
    assert after["description"] == before["description"]
    assert after["branch"] == before["branch"]
    assert after["workdir"] == before["workdir"]


def test_close_closes_github_pr_without_delete_branch(tmp_path):
    with _fake_gh() as backend:
        pr = backend.add_pr(head="pm/pr-001")
        project = _make_project(tmp_path, gh_pr_number=pr.number)
        result = _run_close(project["pm_dir"], "pr-001")

    assert result.exit_code == 0, result.output
    calls = _close_calls(backend)
    assert calls == [["pr", "close", str(pr.number)]]
    assert not any("--delete-branch" in c for c in backend.calls)
    assert backend.prs[pr.number].state == "CLOSED"


def test_remote_branch_still_exists_after_close(tmp_path):
    backend = FakeGitHubBackend.with_git_repo(tmp_path / "fake-gh")
    with _fake_gh(backend):
        pr = backend.add_pr(head="pm/pr-001")
        project = _make_project(tmp_path, gh_pr_number=pr.number)
        assert backend.git_repo.branch_exists("pm/pr-001")
        result = _run_close(project["pm_dir"], "pr-001")

    assert result.exit_code == 0, result.output
    assert _close_calls(backend) == [["pr", "close", str(pr.number)]]
    assert backend.git_repo.branch_exists("pm/pr-001")
    assert not any("--delete-branch" in c for c in backend.calls)


def test_workdir_is_byte_identical_after_close(tmp_path):
    project = _make_project(tmp_path)
    wd = project["workdir"]
    before = _snapshot(wd)
    with _fake_gh() as backend:
        backend.add_pr(head="pm/pr-001")
        result = _run_close(project["pm_dir"], "pr-001")

    assert result.exit_code == 0, result.output
    assert wd.is_dir()
    assert _snapshot(wd) == before
    assert (wd / "captures" / "qa" / "log.txt").read_text() == "evidence\n"
    assert (wd / "untracked.txt").read_text() == "untracked work\n"
    assert (wd / ".cache" / "blob.bin").read_bytes() == b"\x00\x01\x02"
    # The tracked modification is still a modification.
    status = subprocess.run([REAL_GIT, "status", "--porcelain"], cwd=wd,
                            capture_output=True, text=True, check=True).stdout
    assert "M tracked.txt" in status


# ---------------------------------------------------------------------------
# flags
# ---------------------------------------------------------------------------

def test_keep_github_leaves_github_untouched(tmp_path):
    with _fake_gh() as backend:
        pr = backend.add_pr(head="pm/pr-001")
        project = _make_project(tmp_path, gh_pr_number=pr.number)
        result = _run_close(project["pm_dir"], "pr-001", "--keep-github")

    assert result.exit_code == 0, result.output
    assert _close_calls(backend) == []
    assert backend.prs[pr.number].state == "OPEN"
    assert _load_entry(project["pm_dir"])["status"] == "closed"


def test_keep_branch_is_accepted_noop(tmp_path):
    with _fake_gh() as backend:
        pr = backend.add_pr(head="pm/pr-001")
        project = _make_project(tmp_path, gh_pr_number=pr.number)
        before = _load_entry(project["pm_dir"])
        result = _run_close(project["pm_dir"], "pr-001", "--keep-branch")

    assert result.exit_code == 0, result.output
    assert _close_calls(backend) == [["pr", "close", str(pr.number)]]
    assert not any("--delete-branch" in c for c in backend.calls)
    after = _load_entry(project["pm_dir"])
    assert after["status"] == "closed"
    assert after["branch"] == before["branch"]


def test_no_github_pr_makes_no_gh_call(tmp_path):
    project = _make_project(tmp_path, gh_pr_number=None)
    with _fake_gh() as backend:
        result = _run_close(project["pm_dir"], "pr-001")

    assert result.exit_code == 0, result.output
    assert backend.calls == []
    assert _load_entry(project["pm_dir"])["status"] == "closed"


def test_absent_workdir_path_is_preserved(tmp_path):
    project = _make_project(tmp_path, workdir=False)
    missing = tmp_path / "gone-workdir"
    data = store.load(project["pm_dir"])
    data["prs"][0]["workdir"] = str(missing)
    store.save(data, project["pm_dir"])

    with _fake_gh() as backend:
        backend.add_pr(head="pm/pr-001")
        result = _run_close(project["pm_dir"], "pr-001")

    assert result.exit_code == 0, result.output
    assert _load_entry(project["pm_dir"])["workdir"] == str(missing)


def test_repeat_close_is_idempotent(tmp_path):
    project = _make_project(tmp_path)
    wd_before = _snapshot(project["workdir"])
    with _fake_gh() as backend:
        backend.add_pr(head="pm/pr-001")
        first = _run_close(project["pm_dir"], "pr-001")
        second = _run_close(project["pm_dir"], "pr-001")

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    entry = _load_entry(project["pm_dir"])
    assert entry is not None
    assert entry["status"] == "closed"
    assert len(entry["notes"]) == 1
    assert _snapshot(project["workdir"]) == wd_before


# ---------------------------------------------------------------------------
# explicit registry-only removal
# ---------------------------------------------------------------------------

def test_remove_deletes_only_the_registry_entry(tmp_path):
    backend = FakeGitHubBackend.with_git_repo(tmp_path / "fake-gh")
    with _fake_gh(backend):
        pr = backend.add_pr(head="pm/pr-001")
        project = _make_project(tmp_path, gh_pr_number=pr.number)
        wd_before = _snapshot(project["workdir"])
        result = _run_close(project["pm_dir"], "pr-001", "--remove")

    assert result.exit_code == 0, result.output
    assert _load_entry(project["pm_dir"]) is None
    assert project["workdir"].is_dir()
    assert _snapshot(project["workdir"]) == wd_before
    assert backend.git_repo.branch_exists("pm/pr-001")
    # The GitHub PR is still closed per the default (registry is the only
    # local thing removed); no branch deletion is requested.
    assert _close_calls(backend) == [["pr", "close", str(pr.number)]]
    assert not any("--delete-branch" in c for c in backend.calls)
    # active_pr moves off the removed entry.
    data = store.load(project["pm_dir"])
    assert data["project"]["active_pr"] == "pr-002"


def test_remove_with_keep_github_touches_nothing_remote(tmp_path):
    with _fake_gh() as backend:
        pr = backend.add_pr(head="pm/pr-001")
        project = _make_project(tmp_path, gh_pr_number=pr.number)
        result = _run_close(project["pm_dir"], "pr-001", "--remove",
                            "--keep-github")

    assert result.exit_code == 0, result.output
    assert _load_entry(project["pm_dir"]) is None
    assert _close_calls(backend) == []
    assert backend.prs[pr.number].state == "OPEN"
    assert project["workdir"].is_dir()


# ---------------------------------------------------------------------------
# dependents
# ---------------------------------------------------------------------------

def test_dependents_are_warned_but_not_unblocked(tmp_path):
    project = _make_project(tmp_path)
    with _fake_gh() as backend:
        backend.add_pr(head="pm/pr-001")
        result = _run_close(project["pm_dir"], "pr-001")

    assert result.exit_code == 0, result.output
    assert "pr-002" in result.output
    assert "blocked" in result.output.lower()

    data = store.load(project["pm_dir"])
    dependent = store.get_pr(data, "pr-002")
    assert dependent["status"] == "pending"          # never auto-started
    assert dependent["depends_on"] == ["pr-001"]     # never auto-satisfied
    # The closed dependency does not satisfy the graph.
    assert [p["id"] for p in graph.ready_prs(data["prs"])] == []
    # Nor is the closed PR itself ready to start.
    assert "pr-001" not in [p["id"] for p in graph.ready_prs(data["prs"])]


def test_closed_pr_cannot_be_started(tmp_path):
    project = _make_project(tmp_path)
    with _fake_gh() as backend:
        backend.add_pr(head="pm/pr-001")
        close = _run_close(project["pm_dir"], "pr-001")
        assert close.exit_code == 0, close.output

        runner = CliRunner()
        with mock.patch.object(pr_mod, "state_root",
                               return_value=project["pm_dir"]), \
             mock.patch.object(pr_mod, "trigger_tui_refresh"):
            start = runner.invoke(pr_mod.pr, ["start", "pr-001"])

    assert start.exit_code != 0
    assert "closed" in start.output.lower()


# ---------------------------------------------------------------------------
# failure handling
# ---------------------------------------------------------------------------

def test_github_close_failure_keeps_local_state(tmp_path):
    with _fake_gh() as backend:
        pr = backend.add_pr(head="pm/pr-001")
        project = _make_project(tmp_path, gh_pr_number=pr.number)
        wd_before = _snapshot(project["workdir"])
        backend.simulate_rate_limit("pr close")
        result = _run_close(project["pm_dir"], "pr-001")

    assert result.exit_code == 0, result.output
    assert "Warning: Could not close GitHub PR" in result.output
    assert _load_entry(project["pm_dir"])["status"] == "closed"
    assert _snapshot(project["workdir"]) == wd_before
    assert backend.prs[pr.number].state == "OPEN"


def test_gh_unavailable_keeps_local_state(tmp_path):
    with _fake_gh() as backend:
        pr = backend.add_pr(head="pm/pr-001")
        project = _make_project(tmp_path, gh_pr_number=pr.number)
    wd_before = _snapshot(project["workdir"])
    with mock.patch("pm_core.gh_ops.close_pr", side_effect=SystemExit(1)):
        result = _run_close(project["pm_dir"], "pr-001")

    assert result.exit_code == 0, result.output
    assert "Warning: Could not close GitHub PR" in result.output
    assert _load_entry(project["pm_dir"])["status"] == "closed"
    assert _snapshot(project["workdir"]) == wd_before


# ---------------------------------------------------------------------------
# merged PRs are history, not closable
# ---------------------------------------------------------------------------

def test_close_refuses_merged_without_remove(tmp_path):
    with _fake_gh() as backend:
        pr = backend.add_pr(head="pm/pr-001", state="MERGED")
        project = _make_project(tmp_path, status="merged",
                                gh_pr_number=pr.number)
        result = _run_close(project["pm_dir"], "pr-001")

    assert result.exit_code != 0
    entry = _load_entry(project["pm_dir"])
    assert entry["status"] == "merged"
    assert _close_calls(backend) == []
    assert project["workdir"].is_dir()


def test_remove_merged_is_registry_only(tmp_path):
    with _fake_gh() as backend:
        pr = backend.add_pr(head="pm/pr-001", state="MERGED")
        project = _make_project(tmp_path, status="merged",
                                gh_pr_number=pr.number)
        result = _run_close(project["pm_dir"], "pr-001", "--remove")

    assert result.exit_code == 0, result.output
    assert _load_entry(project["pm_dir"]) is None
    assert _close_calls(backend) == []
    assert project["workdir"].is_dir()


# ---------------------------------------------------------------------------
# closed status is durable across GitHub sync
# ---------------------------------------------------------------------------

def test_sync_from_github_does_not_reopen_closed_pr(tmp_path):
    project = _make_project(tmp_path, status="closed", with_dependent=False)
    with _fake_gh() as backend:
        pr = backend.add_pr(head="pm/pr-001", state="OPEN")
        data = store.load(project["pm_dir"])
        data["prs"][0]["gh_pr_number"] = pr.number
        store.save(data, project["pm_dir"])

        result = pr_sync.sync_from_github(project["pm_dir"], save_state=False)

    assert result.synced is True
    assert "pr-001" not in result.status_updates
    assert store.get_pr(store.load(project["pm_dir"]), "pr-001")["status"] == "closed"


def test_sync_from_github_still_closes_open_prs(tmp_path):
    """The sticky-closed rule is narrow: an open PR still syncs normally."""
    project = _make_project(tmp_path, status="in_progress",
                            with_dependent=False)
    with _fake_gh() as backend:
        pr = backend.add_pr(head="pm/pr-001", state="OPEN")
        data = store.load(project["pm_dir"])
        data["prs"][0]["gh_pr_number"] = pr.number
        store.save(data, project["pm_dir"])

        result = pr_sync.sync_from_github(project["pm_dir"], save_state=False)

    assert result.status_updates.get("pr-001") == "in_review"
