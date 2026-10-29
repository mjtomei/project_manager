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
from contextlib import contextmanager, ExitStack
from pathlib import Path
from unittest import mock

from click.testing import CliRunner

from pm_core import container as container_mod
from pm_core import graph, pr_cleanup, store
from pm_core import pr_sync
from pm_core import tmux as tmux_mod
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

    # The output names the follow-up actions close deliberately leaves to the
    # user: reopen and the separate workdir cleanup.
    assert "Reopen: pm pr edit pr-001 --status pending" in result.output
    assert "Cleanup: pm pr cleanup pr-001" in result.output


def test_close_a_pending_pr_records_a_closure(tmp_path):
    """A PR that was never started is still closable: the lifecycle action is
    about the record, not about a workdir having existed."""
    project = _make_project(tmp_path, status="pending", workdir=False,
                            with_dependent=False)
    result = _run_close(project["pm_dir"], "pr-001")

    assert result.exit_code == 0, result.output
    entry = _load_entry(project["pm_dir"])
    assert entry["status"] == "closed"
    assert entry.get("closed_at")
    assert entry["workdir"] is None
    assert store.load(project["pm_dir"])["project"]["active_pr"] is None


def test_default_close_leaves_unrelated_records_and_settings_alone(tmp_path):
    """Close rewrites one PR's status and (at most) active_pr — every other
    record, plan, and project setting survives verbatim."""
    project = _make_project(tmp_path)
    before = store.load(project["pm_dir"])
    other_before = store.get_pr(before, "pr-002")
    with _fake_gh() as backend:
        backend.add_pr(head="pm/pr-001")
        result = _run_close(project["pm_dir"], "pr-001")

    assert result.exit_code == 0, result.output
    after = store.load(project["pm_dir"])
    # Unrelated PR record untouched (status, deps, title, timestamps).
    assert store.get_pr(after, "pr-002") == other_before
    # Project settings survive; only the active pointer may move.
    strip_active = lambda d: {k: v for k, v in d.items() if k != "active_pr"}
    assert strip_active(after["project"]) == strip_active(before["project"])
    assert after.get("plans") == before.get("plans")


def test_default_close_moves_active_pr_off_the_closed_entry(tmp_path):
    """A retained closed entry never stays active (A2): later id-less
    commands must not resolve a terminal record."""
    project = _make_project(tmp_path)
    assert store.load(project["pm_dir"])["project"]["active_pr"] == "pr-001"
    with _fake_gh() as backend:
        backend.add_pr(head="pm/pr-001")
        result = _run_close(project["pm_dir"], "pr-001")

    assert result.exit_code == 0, result.output
    data = store.load(project["pm_dir"])
    assert data["project"]["active_pr"] == "pr-002"
    # The closed entry itself survives — it just is not the active PR.
    assert store.get_pr(data, "pr-001")["status"] == "closed"


def test_default_close_clears_active_pr_when_nothing_remains(tmp_path):
    """With no non-terminal PR left, the pointer becomes None — the closed
    record must never be re-selected as active (A2)."""
    project = _make_project(tmp_path, with_dependent=False)
    with _fake_gh() as backend:
        backend.add_pr(head="pm/pr-001")
        result = _run_close(project["pm_dir"], "pr-001")

    assert result.exit_code == 0, result.output
    data = store.load(project["pm_dir"])
    assert data["project"]["active_pr"] is None
    assert store.get_pr(data, "pr-001")["status"] == "closed"


def test_default_close_leaves_a_foreign_active_pr_alone(tmp_path):
    """Closing one PR must not move an active pointer that names another."""
    project = _make_project(tmp_path)
    data = store.load(project["pm_dir"])
    data["project"]["active_pr"] = "pr-002"
    store.save(data, project["pm_dir"])
    with _fake_gh() as backend:
        backend.add_pr(head="pm/pr-001")
        result = _run_close(project["pm_dir"], "pr-001")

    assert result.exit_code == 0, result.output
    assert store.load(project["pm_dir"])["project"]["active_pr"] == "pr-002"


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


def _teardown_spies(calls: list[str]) -> list:
    """Patches for every live-resource teardown a close must never reach.

    Each target is the binding the close path would actually call through:
    ``pr.py`` imports ``kill_pr_windows`` by name, so patching only
    ``pm_core.cli.helpers.kill_pr_windows`` would miss a call made from the
    close command.  ``cleanup_pr_resources`` is the high-level entry the TUI
    and ``pm pr cleanup --resources`` use; the rest are its leaves.
    """
    return [
        mock.patch("pm_core.pr_cleanup.cleanup_pr_resources",
                   side_effect=lambda *a, **k: calls.append(
                       "cleanup_pr_resources")),
        mock.patch("pm_core.tmux.kill_window",
                   side_effect=lambda *a, **k: calls.append("kill_window")),
        mock.patch("pm_core.cli.pr.kill_pr_windows",
                   side_effect=lambda *a, **k: calls.append(
                       "kill_pr_windows")),
        mock.patch("pm_core.cli.helpers.kill_pr_windows",
                   side_effect=lambda *a, **k: calls.append(
                       "kill_pr_windows")),
        mock.patch("pm_core.container.cleanup_pr_containers",
                   side_effect=lambda *a, **k: calls.append(
                       "cleanup_pr_containers")),
    ]


def test_close_does_not_tear_down_live_resources(tmp_path):
    """A4/R4: close is a registry action.  It never kills tmux windows,
    containers or push-proxy sockets, and never clears runtime state — that
    is the separate, explicitly requested `pm pr cleanup --resources`.  The
    retained workdir means a closed PR's live window can still be used."""
    calls: list[str] = []
    project = _make_project(tmp_path)
    with _fake_gh() as backend, ExitStack() as stack:
        backend.add_pr(head="pm/pr-001")
        for spy in _teardown_spies(calls):
            stack.enter_context(spy)
        closed = _run_close(project["pm_dir"], "pr-001")
        removed = _run_close(project["pm_dir"], "pr-001", "--remove")
        # Neither the default close nor --remove reaches a teardown path.
        assert calls == [], calls
        # Positive control: the spies are wired to the real entry points (a
        # direct call through each binding fires them), so the empty list
        # above is a real guarantee, not a mis-targeted patch.
        pr_mod.kill_pr_windows("sess", {"id": "pr-001"})
        pr_cleanup.cleanup_pr_resources("sess", {"id": "pr-001"})
        tmux_mod.kill_window("sess", "win")
        container_mod.cleanup_pr_containers("sess", {"id": "pr-001"})
        assert set(calls) == {"kill_pr_windows", "cleanup_pr_resources",
                              "kill_window", "cleanup_pr_containers"}, calls

    assert closed.exit_code == 0, closed.output
    assert removed.exit_code == 0, removed.output
    assert _load_entry(project["pm_dir"]) is None
    assert project["workdir"].is_dir()


def test_close_preserves_merge_and_signoff_evidence(tmp_path):
    """The record keeps every piece of historical evidence — the sign-off
    approval it was retired with, merge-integrity findings, spec/QA state —
    not just the title, notes and dependencies."""
    signoff = {
        "verdict": "SIGNOFF_MERGE", "sha": "a" * 40, "ts": NOW,
        "origin": "manual", "report_hash": "b" * 64,
        "integration": {"base_branch": "master", "base_sha": "c" * 40,
                        "target_repo": "o/r", "status": "clean"},
    }
    integrity = {"problem": "published candidate differs from the approved "
                            "one", "merge_sha": "d" * 40}
    qa_state = {"done": 3, "total": 3, "verdict": "PASS"}
    project = _make_project(tmp_path, with_dependent=False)
    data = store.load(project["pm_dir"])
    entry = store.get_pr(data, "pr-001")
    entry["signoff"] = dict(signoff)
    entry["merge_integrity"] = dict(integrity)
    entry["spec_pending"] = True
    entry["qa"] = dict(qa_state)
    store.save(data, project["pm_dir"])

    with _fake_gh() as backend:
        backend.add_pr(head="pm/pr-001")
        result = _run_close(project["pm_dir"], "pr-001")

    assert result.exit_code == 0, result.output
    after = _load_entry(project["pm_dir"])
    assert after["status"] == "closed"
    assert after["signoff"] == signoff
    assert after["merge_integrity"] == integrity
    assert after["spec_pending"] is True
    assert after["qa"] == qa_state


def test_cleanup_remains_the_explicit_way_to_drop_a_closed_workdir(tmp_path):
    """Close keeps the workdir; removing it is the separate, explicit
    `pm pr cleanup` step (which close's help points at).  A closed status is
    normal for that step, so it must not be warned about as unexpected."""
    project = _make_project(tmp_path)
    with _fake_gh() as backend:
        backend.add_pr(head="pm/pr-001")
        assert _run_close(project["pm_dir"], "pr-001").exit_code == 0
    assert project["workdir"].is_dir()

    runner = CliRunner()
    with mock.patch.object(pr_mod, "state_root",
                           return_value=project["pm_dir"]), \
         mock.patch.object(pr_mod, "trigger_tui_refresh"):
        result = runner.invoke(pr_mod.pr, ["cleanup", "pr-001", "--force"])

    assert result.exit_code == 0, result.output
    assert "Warning:" not in result.output
    assert not project["workdir"].exists()
    entry = _load_entry(project["pm_dir"])
    assert entry is not None
    assert entry["status"] == "closed"      # the registry record is retained
    assert entry["workdir"] is None         # only the reference is cleared


def test_bare_cleanup_auto_selects_a_closed_workdir(tmp_path):
    """`pm pr cleanup` with no id is the step close's help points at, so a
    closed PR with a workdir must be selectable — the auto-select used to
    consider `merged` only and answered "No merged PRs with workdirs"."""
    project = _make_project(tmp_path, with_dependent=False)
    with _fake_gh() as backend:
        backend.add_pr(head="pm/pr-001")
        assert _run_close(project["pm_dir"], "pr-001").exit_code == 0
    assert project["workdir"].is_dir()

    runner = CliRunner()
    with mock.patch.object(pr_mod, "state_root",
                           return_value=project["pm_dir"]), \
         mock.patch.object(pr_mod, "trigger_tui_refresh"):
        result = runner.invoke(pr_mod.pr, ["cleanup", "--force"])

    assert result.exit_code == 0, result.output
    assert "Auto-selected pr-001" in result.output
    assert not project["workdir"].exists()
    entry = _load_entry(project["pm_dir"])
    assert entry["status"] == "closed"
    assert entry["workdir"] is None


def test_bare_cleanup_reports_when_nothing_terminal_has_a_workdir(tmp_path):
    """The no-match message names both terminal statuses, so a user who just
    closed a PR without a workdir is not sent chasing a merged-only cleanup."""
    project = _make_project(tmp_path, workdir=False, with_dependent=False)

    runner = CliRunner()
    with mock.patch.object(pr_mod, "state_root",
                           return_value=project["pm_dir"]), \
         mock.patch.object(pr_mod, "trigger_tui_refresh"):
        result = runner.invoke(pr_mod.pr, ["cleanup"])

    assert result.exit_code != 0
    assert "No merged or closed PRs with workdirs" in result.output


def _add_malformed_entry(project: dict, **fields) -> None:
    """Append a hand-edited registry entry with no usable ``id``."""
    data = store.load(project["pm_dir"])
    data["prs"].append({"title": "hand edited", "status": "pending", **fields})
    store.save(data, project["pm_dir"])


def test_cleanup_all_tolerates_a_malformed_entry(tmp_path):
    """`--all` walks every entry; an id-less hand-edited record must not raise
    inside the store lock (usable_prs, like the rest of the id-indexing code)."""
    project = _make_project(tmp_path)
    _add_malformed_entry(project)

    runner = CliRunner()
    with mock.patch.object(pr_mod, "state_root",
                           return_value=project["pm_dir"]), \
         mock.patch.object(pr_mod, "trigger_tui_refresh"):
        result = runner.invoke(pr_mod.pr, ["cleanup", "--all", "--force"])

    assert result.exit_code == 0, result.output
    assert result.exception is None, result.exception
    assert not project["workdir"].exists()
    entry = _load_entry(project["pm_dir"])
    assert entry["workdir"] is None          # reference cleared
    assert entry["status"] == "in_review"    # cleanup is not a status change
    # The malformed neighbour is left exactly as it was.
    titles = [p.get("title") for p in store.load(project["pm_dir"])["prs"]
              if not p.get("id")]
    assert titles == ["hand edited"]


def test_prune_tolerates_a_malformed_entry(tmp_path):
    """`--prune` reports stale workdir references by id; an id-less entry is
    skipped instead of raising KeyError."""
    project = _make_project(tmp_path)
    missing = tmp_path / "gone-workdir"
    _add_malformed_entry(project, workdir=str(missing))

    runner = CliRunner()
    with mock.patch.object(pr_mod, "state_root",
                           return_value=project["pm_dir"]), \
         mock.patch.object(pr_mod, "trigger_tui_refresh"):
        result = runner.invoke(pr_mod.pr, ["cleanup", "--prune"])

    assert result.exit_code == 0, result.output
    assert result.exception is None, result.exception
    assert "No stale workdir references found." in result.output
    # The entry is untouched: pm cannot identify it, so it is not rewritten.
    malformed = [p for p in store.load(project["pm_dir"])["prs"]
                 if not p.get("id")]
    assert malformed[0]["workdir"] == str(missing)


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
    assert (f"Leaving GitHub PR #{pr.number} unchanged (--keep-github)."
            in result.output)
    # Never promise "open": the GitHub PR may be closed or merged there.
    assert "open (--keep-github)" not in result.output
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
        first_entry = _load_entry(project["pm_dir"])
        second = _run_close(project["pm_dir"], "pr-001")

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    entry = _load_entry(project["pm_dir"])
    assert entry is not None
    assert entry["status"] == "closed"
    assert len(entry["notes"]) == 1
    # The first closure time is history; a repeat close only touches
    # updated_at (it re-attempts the GitHub close so a failed one can retry).
    assert entry["closed_at"] == first_entry["closed_at"]
    # ISO-8601 strings with the same UTC offset sort chronologically, so this
    # is a real "the record was touched" check, not a >= tautology.
    assert entry["updated_at"] > first_entry["updated_at"]
    assert _snapshot(project["workdir"]) == wd_before


def test_repeat_close_retries_the_github_close(tmp_path):
    """A6: a repeat close re-attempts the GitHub close (unless
    --keep-github), so a close whose `gh` call failed can be retried without
    rewriting the retained record."""
    with _fake_gh() as backend:
        pr = backend.add_pr(head="pm/pr-001")
        project = _make_project(tmp_path, gh_pr_number=pr.number)
        assert _run_close(project["pm_dir"], "pr-001").exit_code == 0
        # The remote is still OPEN (as after a failed `gh pr close`).
        backend.prs[pr.number].state = "OPEN"
        first_entry = _load_entry(project["pm_dir"])
        result = _run_close(project["pm_dir"], "pr-001")

    assert result.exit_code == 0, result.output
    assert _close_calls(backend) == [["pr", "close", str(pr.number)]] * 2
    assert backend.prs[pr.number].state == "CLOSED"
    after = _load_entry(project["pm_dir"])
    assert after["status"] == "closed"
    assert after["closed_at"] == first_entry["closed_at"]


def test_repeat_close_does_not_invent_a_closure_time(tmp_path):
    """An entry already `closed` before `closed_at` existed keeps no
    timestamp: a repeat close must not stamp "now" as its closure time (only
    a fresh closure records one, A6)."""
    project = _make_project(tmp_path, status="closed", with_dependent=False)
    wd_before = _snapshot(project["workdir"])
    before = _load_entry(project["pm_dir"])
    assert "closed_at" not in before

    with _fake_gh() as backend:
        backend.add_pr(head="pm/pr-001")
        result = _run_close(project["pm_dir"], "pr-001")

    assert result.exit_code == 0, result.output
    after = _load_entry(project["pm_dir"])
    assert after["status"] == "closed"
    assert "closed_at" not in after
    # updated_at still moves: the record was touched, not rewritten.
    assert after["updated_at"] > before["updated_at"]
    assert _snapshot(project["workdir"]) == wd_before


def test_reopening_a_closed_pr_drops_the_closure_time(tmp_path):
    """`closed_at` names a closure; the deliberate reopen
    (`pm pr edit --status pending`) clears it, and a later close records a
    fresh one instead of resurrecting the old time."""
    project = _make_project(tmp_path, status="closed", with_dependent=False)
    data = store.load(project["pm_dir"])
    store.get_pr(data, "pr-001")["closed_at"] = "2026-09-01T00:00:00+00:00"
    store.save(data, project["pm_dir"])

    runner = CliRunner()
    with mock.patch.object(pr_mod, "state_root",
                           return_value=project["pm_dir"]), \
         mock.patch.object(pr_mod, "trigger_tui_refresh"):
        reopened = runner.invoke(pr_mod.pr, ["edit", "pr-001",
                                             "--status", "pending"])

    assert reopened.exit_code == 0, reopened.output
    entry = _load_entry(project["pm_dir"])
    assert entry["status"] == "pending"
    assert "closed_at" not in entry

    with _fake_gh() as backend:
        backend.add_pr(head="pm/pr-001")
        result = _run_close(project["pm_dir"], "pr-001")

    assert result.exit_code == 0, result.output
    entry = _load_entry(project["pm_dir"])
    assert entry["status"] == "closed"
    assert entry["closed_at"] != "2026-09-01T00:00:00+00:00"


def test_editor_reopen_drops_the_closure_time(tmp_path):
    """`pm pr edit <id>` with no flags edits through $EDITOR, a second code
    path (`_apply_pr_edit`): reopening there must drop `closed_at` too, so the
    field never names a status the PR is not in."""
    project = _make_project(tmp_path, status="closed", with_dependent=False)
    data = store.load(project["pm_dir"])
    store.get_pr(data, "pr-001")["closed_at"] = "2026-09-01T00:00:00+00:00"
    store.save(data, project["pm_dir"])

    changes = pr_mod._apply_pr_edit(project["pm_dir"], "pr-001", {
        "title": None, "status": "pending", "depends_on_str": None,
        "note_texts": [n["text"] for n in data["prs"][0]["notes"]],
        "description": data["prs"][0]["description"],
    })

    assert changes == ["status: closed → pending"], changes
    entry = _load_entry(project["pm_dir"])
    assert entry["status"] == "pending"
    assert "closed_at" not in entry


def test_restating_closed_keeps_the_closure_time(tmp_path):
    """`pm pr edit --status closed` on an already-closed record is not a fresh
    closure: it must not rewrite the closure history (same rule as repeat
    close, A6)."""
    project = _make_project(tmp_path, status="closed", with_dependent=False)
    data = store.load(project["pm_dir"])
    store.get_pr(data, "pr-001")["closed_at"] = "2026-09-01T00:00:00+00:00"
    store.save(data, project["pm_dir"])

    runner = CliRunner()
    with mock.patch.object(pr_mod, "state_root",
                           return_value=project["pm_dir"]), \
         mock.patch.object(pr_mod, "trigger_tui_refresh"):
        result = runner.invoke(pr_mod.pr, ["edit", "pr-001",
                                           "--status", "closed"])

    assert result.exit_code == 0, result.output
    entry = _load_entry(project["pm_dir"])
    assert entry["status"] == "closed"
    assert entry["closed_at"] == "2026-09-01T00:00:00+00:00"


def test_merge_discovered_after_close_drops_the_closure_time(tmp_path):
    """A closed record that GitHub reports as merged finalizes as `merged`;
    the stale `closed_at` must not survive to name a status the PR left."""
    project = _make_project(tmp_path, status="in_progress",
                            with_dependent=False)
    with _fake_gh() as backend:
        pr = backend.add_pr(head="pm/pr-001", state="MERGED")
        data = store.load(project["pm_dir"])
        data["prs"][0]["gh_pr_number"] = pr.number
        store.save(data, project["pm_dir"])
        stale = store.load(project["pm_dir"])

        def _mark_closed(d):
            entry = store.get_pr(d, "pr-001")
            entry["status"] = "closed"
            entry["closed_at"] = "2026-09-01T00:00:00+00:00"
        store.locked_update(project["pm_dir"], _mark_closed)

        pr_sync.sync_from_github(project["pm_dir"], data=stale)

    entry = _load_entry(project["pm_dir"])
    assert entry["status"] == "merged"
    assert "closed_at" not in entry


def test_close_does_not_overwrite_a_concurrent_merge(tmp_path):
    """A merge landing between load and the store lock must not become closed."""
    project = _make_project(tmp_path)
    real_locked_update = store.locked_update

    def racing_update(root, fn, **kwargs):
        # Another process (e.g. `pm pr merge` / a sync) merges the PR after
        # this command loaded its snapshot but before it takes the lock.
        data = store.load(root)
        store.get_pr(data, "pr-001")["status"] = "merged"
        store.save(data, root)
        return real_locked_update(root, fn, **kwargs)

    with _fake_gh() as backend:
        backend.add_pr(head="pm/pr-001")
        with mock.patch.object(pr_mod.store, "locked_update", racing_update):
            result = _run_close(project["pm_dir"], "pr-001")

    assert result.exit_code != 0
    assert "merged" in result.output
    entry = _load_entry(project["pm_dir"])
    assert entry["status"] == "merged"          # merge record preserved
    assert "closed_at" not in entry


def test_close_noops_when_entry_removed_concurrently(tmp_path):
    """A concurrent `--remove` between load and lock must not raise or
    resurrect the entry."""
    project = _make_project(tmp_path)
    real_locked_update = store.locked_update

    def racing_update(root, fn, **kwargs):
        data = store.load(root)
        data["prs"] = [p for p in data["prs"] if p["id"] != "pr-001"]
        store.save(data, root)
        return real_locked_update(root, fn, **kwargs)

    with _fake_gh() as backend:
        backend.add_pr(head="pm/pr-001")
        with mock.patch.object(pr_mod.store, "locked_update", racing_update):
            result = _run_close(project["pm_dir"], "pr-001")

    assert result.exit_code == 0, result.output
    assert "removed concurrently" in result.output
    assert _load_entry(project["pm_dir"]) is None
    assert project["workdir"].is_dir()


def test_remove_noops_when_entry_removed_concurrently(tmp_path):
    """A concurrent `--remove` must not make this one claim it removed a
    record that was already gone (and must not raise)."""
    project = _make_project(tmp_path)
    real_locked_update = store.locked_update

    def racing_update(root, fn, **kwargs):
        data = store.load(root)
        data["prs"] = [p for p in data["prs"] if p["id"] != "pr-001"]
        store.save(data, root)
        return real_locked_update(root, fn, **kwargs)

    with _fake_gh() as backend:
        backend.add_pr(head="pm/pr-001")
        with mock.patch.object(pr_mod.store, "locked_update", racing_update):
            result = _run_close(project["pm_dir"], "pr-001", "--remove")

    assert result.exit_code == 0, result.output
    assert "removed concurrently" in result.output
    assert "nothing to remove" in result.output
    assert "Removed registry entry" not in result.output
    assert _load_entry(project["pm_dir"]) is None
    assert project["workdir"].is_dir()


def test_add_hints_when_a_closed_record_is_the_duplicate(tmp_path):
    """Retained closed entries now match `pr add`'s duplicate check; the
    message must say how to reuse the record instead of silently refusing."""
    project = _make_project(tmp_path, status="closed", with_dependent=False)
    entry = _load_entry(project["pm_dir"])
    runner = CliRunner()
    with mock.patch.object(pr_mod, "state_root",
                           return_value=project["pm_dir"]), \
         mock.patch.object(pr_mod, "trigger_tui_refresh"):
        result = runner.invoke(pr_mod.pr, [
            "add", entry["title"], "--description", entry["description"]])

    assert result.exit_code == 0, result.output
    assert "already exists" in result.output
    assert "It is closed" in result.output
    assert f"pm pr edit {entry['id']} --status pending" in result.output


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
    # The output names what survived, and warns that the retained workdir is
    # no longer reachable through pm (`pm pr cleanup` resolves the entry).
    assert f"Kept: branch 'pm/pr-001', workdir '{project['workdir']}'" \
        in result.output
    assert "no longer tracked by pm" in result.output
    # active_pr moves off the removed entry.
    data = store.load(project["pm_dir"])
    assert data["project"]["active_pr"] == "pr-002"


def test_remove_without_a_workdir_claims_only_the_branch(tmp_path):
    """--remove must not claim it kept a workdir the PR never had — but it
    must still say that live tmux windows/containers are now unreachable."""
    project = _make_project(tmp_path, workdir=False, with_dependent=False)
    result = _run_close(project["pm_dir"], "pr-001", "--remove")

    assert result.exit_code == 0, result.output
    assert "Kept: branch 'pm/pr-001'" in result.output
    assert "workdir" not in result.output
    assert "tmux windows/containers" in result.output
    assert "no longer tracked by pm" in result.output


def test_remove_says_live_resources_are_no_longer_reachable(tmp_path):
    """`pm pr cleanup` and `--resources` both resolve the registry entry, so
    after --remove the retained workdir *and* any tmux window/container are
    orphans with no pointer — the output must name both (review e89f i2)."""
    project = _make_project(tmp_path, with_dependent=False)
    result = _run_close(project["pm_dir"], "pr-001", "--remove")

    assert result.exit_code == 0, result.output
    assert "that workdir and any tmux windows/containers" in result.output
    assert "no longer tracked by pm" in result.output


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
    # Only `merged` satisfies a dependency, so the block is permanent until
    # the user acts: the warning says which way out exists.
    assert "reopen the closed PR" in result.output
    assert "depends-on" in result.output

    data = store.load(project["pm_dir"])
    dependent = store.get_pr(data, "pr-002")
    assert dependent["status"] == "pending"          # never auto-started
    assert dependent["depends_on"] == ["pr-001"]     # never auto-satisfied
    # The closed dependency does not satisfy the graph.
    assert [p["id"] for p in graph.ready_prs(data["prs"])] == []
    # Nor is the closed PR itself ready to start.
    assert "pr-001" not in [p["id"] for p in graph.ready_prs(data["prs"])]


def test_remove_warns_dependents_reference_the_removed_record(tmp_path):
    """With --remove the dependency names a record that no longer exists;
    the warning must not imply a `closed` status is the blocker."""
    project = _make_project(tmp_path)
    with _fake_gh() as backend:
        backend.add_pr(head="pm/pr-001")
        result = _run_close(project["pm_dir"], "pr-001", "--remove")

    assert result.exit_code == 0, result.output
    assert "depend on the removed" in result.output
    assert "remain blocked by" not in result.output
    # The record is gone, so the only way out is dropping the dependency.
    assert "drop it from the dependents' depends_on" in result.output
    data = store.load(project["pm_dir"])
    dependent = store.get_pr(data, "pr-002")
    assert dependent["status"] == "pending"
    assert dependent["depends_on"] == ["pr-001"]
    assert [p["id"] for p in graph.ready_prs(data["prs"])] == []


def test_malformed_dependent_entry_does_not_break_close(tmp_path):
    """A hand-edited registry entry without an ``id`` that depends on the
    closed PR must not crash the dependent warning.

    The warning runs *after* the status write, so a ``KeyError: 'id'`` here
    would turn a successful close into a traceback (and a non-zero exit) even
    though the closure was already persisted.  Everything that indexes PRs by
    id skips such entries via ``usable_prs``; the dependents scan must too.
    """
    project = _make_project(tmp_path, with_dependent=False)
    data = store.load(project["pm_dir"])
    # No "id": exactly the partial shape a hand-edited project.yaml can hold.
    data["prs"].append({"title": "hand edited", "status": "pending",
                        "depends_on": ["pr-001"]})
    store.save(data, project["pm_dir"])

    with _fake_gh() as backend:
        backend.add_pr(head="pm/pr-001")
        result = _run_close(project["pm_dir"], "pr-001")

    assert result.exit_code == 0, result.output
    assert result.exception is None, result.exception
    # store.get_pr is not id-less tolerant (pr-77c4f91), so read the entry
    # without indexing the malformed neighbour.
    entries = [p for p in store.load(project["pm_dir"])["prs"]
               if p.get("id") == "pr-001"]
    assert [p["status"] for p in entries] == ["closed"]
    # The malformed entry is neither rewritten nor reported as a dependent.
    assert "hand edited" not in result.output


def test_malformed_dependent_entry_does_not_break_remove(tmp_path):
    """Same guard on the --remove path (its warning formats the same names)."""
    project = _make_project(tmp_path, with_dependent=False)
    data = store.load(project["pm_dir"])
    data["prs"].append({"title": "hand edited", "status": "pending",
                        "depends_on": ["pr-001"]})
    store.save(data, project["pm_dir"])

    with _fake_gh() as backend:
        backend.add_pr(head="pm/pr-001")
        result = _run_close(project["pm_dir"], "pr-001", "--remove")

    assert result.exit_code == 0, result.output
    assert result.exception is None, result.exception
    ids = [p.get("id") for p in store.load(project["pm_dir"])["prs"]]
    assert "pr-001" not in ids
    assert "hand edited" not in result.output


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


def _racing_close(pm_dir: Path, pr_id: str = "pr-001",
                  closed_at: str = "2026-09-01T00:00:00+00:00"):
    """A ``store.locked_update`` stand-in that closes *pr_id* on the way in.

    The launch commands check their pre-lock snapshot, then do real work
    (clone/push, draft-PR upgrade) before writing the transition under the
    store lock — the window a concurrent `pm pr close` lands in.
    """
    real_locked_update = store.locked_update

    def racing_update(root, fn, **kwargs):
        data = store.load(root)
        entry = store.get_pr(data, pr_id)
        entry["status"] = "closed"
        entry["closed_at"] = closed_at
        store.save(data, root)
        return real_locked_update(root, fn, **kwargs)

    return racing_update


def test_start_does_not_record_a_start_on_a_concurrently_closed_pr(tmp_path):
    """`pm pr start` clones and pushes before it writes the start under the
    lock; a close landing in that window must win — the terminal record keeps
    its closed_at and must not become the active PR again (pr-62ad13d)."""
    project = _make_project(tmp_path, status="in_progress")
    # pr_start verifies the PR is committed on the base branch.
    repo = project["pm_dir"]
    _git(repo, "init", "-q", "-b", "master")
    _git(repo, "config", "user.email", "close@example.com")
    _git(repo, "config", "user.name", "Close Test")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "project state")
    # The active pointer names another PR, so a start that leaked through
    # would be visible as it claiming the pointer.
    data = store.load(repo)
    data["project"]["active_pr"] = "pr-002"
    store.save(data, repo)

    racing = _racing_close(repo)
    runner = CliRunner()
    with _fake_gh(), \
         mock.patch.object(pr_mod, "state_root", return_value=repo), \
         mock.patch.object(pr_mod, "trigger_tui_refresh"), \
         mock.patch.object(pr_mod.store, "locked_update", racing), \
         mock.patch.object(pr_mod, "_get_pm_session", return_value=None):
        result = runner.invoke(pr_mod.pr, ["start", "pr-001"])

    assert result.exit_code != 0, result.output
    assert "closed" in result.output.lower()
    after = store.load(repo)
    entry = store.get_pr(after, "pr-001")
    assert entry["status"] == "closed"
    assert entry["closed_at"] == "2026-09-01T00:00:00+00:00"
    assert after["project"]["active_pr"] == "pr-002"


def test_review_does_not_resurrect_a_concurrently_closed_pr(tmp_path):
    """`pm pr review` upgrades the draft PR and resolves the workdir outside
    the lock; a close landing meanwhile must win — a closed record must not be
    moved back to in_review, and no review window may be opened."""
    project = _make_project(tmp_path, status="in_progress",
                            with_dependent=False)
    racing = _racing_close(project["pm_dir"])
    runner = CliRunner()
    with mock.patch.object(pr_mod, "state_root",
                           return_value=project["pm_dir"]), \
         mock.patch.object(pr_mod, "trigger_tui_refresh"), \
         mock.patch.object(pr_mod.store, "locked_update", racing), \
         mock.patch.object(pr_mod, "_launch_review_window") as launch:
        result = runner.invoke(pr_mod.pr, ["review", "pr-001"])

    assert result.exit_code != 0, result.output
    assert "closed" in result.output.lower()
    assert not launch.called
    entry = _load_entry(project["pm_dir"])
    assert entry["status"] == "closed"
    assert entry["closed_at"] == "2026-09-01T00:00:00+00:00"


def test_auto_sequence_reports_a_closed_pr_without_advancing_it(tmp_path):
    """`closed` is terminal exactly like `merged` for the auto-sequence
    driver: it reports the status (exit 0) instead of "unknown status"
    (exit 2), and never launches another phase."""
    project = _make_project(tmp_path, status="closed", with_dependent=False)
    runner = CliRunner()
    with mock.patch.object(pr_mod, "state_root",
                           return_value=project["pm_dir"]), \
         mock.patch.object(pr_mod, "trigger_tui_refresh"), \
         mock.patch.object(pr_mod, "_get_pm_session", return_value=None), \
         mock.patch.object(pr_mod, "pr_start") as start:
        result = runner.invoke(pr_mod.pr, ["auto-sequence", "pr-001"])

    assert result.exit_code == 0, result.output
    assert result.output.strip() == "closed"
    assert not start.called
    assert _load_entry(project["pm_dir"])["status"] == "closed"


def test_signoff_refuses_a_closed_pr_and_names_the_reopen(tmp_path):
    """The sign-off guard names the way out (like start/merge) instead of the
    generic "sign-off runs after QA" complaint about a retained closed
    record."""
    project = _make_project(tmp_path, status="closed", with_dependent=False)
    runner = CliRunner()
    with mock.patch.object(pr_mod, "state_root",
                           return_value=project["pm_dir"]), \
         mock.patch.object(pr_mod, "trigger_tui_refresh"):
        result = runner.invoke(pr_mod.pr, ["signoff", "pr-001"])

    assert result.exit_code != 0
    assert "closed" in result.output.lower()
    assert "pm pr edit pr-001 --status pending" in result.output
    assert _load_entry(project["pm_dir"])["status"] == "closed"


def test_review_refuses_a_closed_pr_and_names_the_reopen(tmp_path):
    """The review guard names the way out too (R10): start, signoff and merge
    all print the concrete reopen command, so a bare "already closed" left
    review as the one lifecycle command with no route back."""
    project = _make_project(tmp_path, status="closed", with_dependent=False)
    runner = CliRunner()
    with mock.patch.object(pr_mod, "state_root",
                           return_value=project["pm_dir"]), \
         mock.patch.object(pr_mod, "trigger_tui_refresh"), \
         mock.patch.object(pr_mod, "_launch_review_window") as launch:
        result = runner.invoke(pr_mod.pr, ["review", "pr-001"])

    assert result.exit_code != 0
    assert "closed" in result.output.lower()
    assert "pm pr edit pr-001 --status pending" in result.output
    assert not launch.called
    assert _load_entry(project["pm_dir"])["status"] == "closed"


def _run_merge(pm_dir: Path, tmp_path: Path, *args: str):
    """Invoke `pm pr merge` with the per-PR lock kept out of ~/.pm."""
    lock_dir = tmp_path / "workdirs"
    lock_dir.mkdir(exist_ok=True)
    runner = CliRunner()
    with mock.patch.object(pr_mod, "state_root", return_value=pm_dir), \
         mock.patch.object(pr_mod, "trigger_tui_refresh"), \
         mock.patch("pm_core.paths.workdirs_base", return_value=lock_dir):
        return runner.invoke(pr_mod.pr, ["merge", *args])


def test_closed_pr_cannot_be_merged(tmp_path):
    """A closed PR is terminal: merging would rewrite the closure to `merged`."""
    project = _make_project(tmp_path, status="closed", with_dependent=False)
    with mock.patch.object(pr_mod, "_publish_approved") as publish:
        result = _run_merge(project["pm_dir"], tmp_path, "pr-001")

    assert result.exit_code != 0
    assert "closed" in result.output.lower()
    assert "reopen" in result.output.lower()   # the terminal-status guard
    assert not publish.called
    assert _load_entry(project["pm_dir"])["status"] == "closed"
    assert project["workdir"].is_dir()


def test_closed_pr_is_not_auto_selected_for_merge(tmp_path):
    """The retained workdir means `_infer_pr_id` resolves a closed PR from
    its cwd (that step ignores the status filter), so an id-less
    `pm pr merge` run inside it must still be refused by the command."""
    project = _make_project(tmp_path, status="closed", with_dependent=False)
    with mock.patch.object(pr_mod, "_publish_approved") as publish, \
         mock.patch.object(Path, "cwd", return_value=project["workdir"]):
        result = _run_merge(project["pm_dir"], tmp_path)

    assert result.exit_code != 0
    assert "closed" in result.output.lower()
    assert not publish.called


def test_merge_recovery_still_allowed_for_closed_pr(tmp_path):
    """--propagation-only finalizes an already-published merge; a local
    `closed` record must not block that recovery."""
    project = _make_project(tmp_path, status="closed", with_dependent=False)
    with mock.patch.object(pr_mod, "_recover_completed_merge") as recover:
        result = _run_merge(project["pm_dir"], tmp_path, "pr-001",
                            "--propagation-only")

    assert result.exit_code == 0, result.output
    assert recover.called


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
    # No gh call is made (a merged GitHub PR cannot be closed).  The message
    # reports the LOCAL record — the GitHub PR is never called "open", and is
    # not claimed to be merged either: a hand-set status or a local-backend
    # merge can leave it open, and no gh call verified it.
    assert (f"GitHub PR #{pr.number} left unchanged (the PR is recorded as "
            f"merged)." in result.output)
    assert "Leaving GitHub PR" not in result.output
    assert "open" not in result.output.lower()


def test_remove_merged_with_keep_github_reports_unchanged(tmp_path):
    """--keep-github wins over the merged wording: it always means "leave the
    GitHub PR alone", whatever the local status is."""
    with _fake_gh() as backend:
        pr = backend.add_pr(head="pm/pr-001", state="MERGED")
        project = _make_project(tmp_path, status="merged",
                                gh_pr_number=pr.number)
        result = _run_close(project["pm_dir"], "pr-001", "--remove",
                            "--keep-github")

    assert result.exit_code == 0, result.output
    assert _load_entry(project["pm_dir"]) is None
    assert _close_calls(backend) == []
    assert (f"Leaving GitHub PR #{pr.number} unchanged (--keep-github)."
            in result.output)
    assert "recorded as merged" not in result.output


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


def test_sync_from_github_does_not_reopen_a_concurrently_closed_pr(tmp_path):
    """sync-github computes its updates from a pre-lock snapshot; a close
    landing during the GitHub round-trip must not be overwritten (R9)."""
    project = _make_project(tmp_path, status="in_progress",
                            with_dependent=False)
    with _fake_gh() as backend:
        pr = backend.add_pr(head="pm/pr-001", state="OPEN")
        data = store.load(project["pm_dir"])
        data["prs"][0]["gh_pr_number"] = pr.number
        store.save(data, project["pm_dir"])
        # The snapshot the sync starts from says in_progress (GitHub OPEN +
        # ready would move it to in_review)...
        stale = store.load(project["pm_dir"])

        # ...and `pm pr close` lands before the sync takes the store lock.
        def _mark_closed(d):
            store.get_pr(d, "pr-001")["status"] = "closed"
        store.locked_update(project["pm_dir"], _mark_closed)

        result = pr_sync.sync_from_github(project["pm_dir"], data=stale)

    assert result.synced is True
    assert store.get_pr(store.load(project["pm_dir"]),
                        "pr-001")["status"] == "closed"


def test_sync_from_github_finalizes_a_merge_over_a_closed_record(tmp_path):
    """The closed-is-terminal guard is narrow: a merge discovered on GitHub is
    authoritative and still finalizes (a PR closed just as GitHub merged it
    ends up merged, not closed)."""
    project = _make_project(tmp_path, status="in_progress",
                            with_dependent=False)
    with _fake_gh() as backend:
        pr = backend.add_pr(head="pm/pr-001", state="MERGED")
        data = store.load(project["pm_dir"])
        data["prs"][0]["gh_pr_number"] = pr.number
        store.save(data, project["pm_dir"])
        stale = store.load(project["pm_dir"])

        # `pm pr close` lands before the sync takes the store lock.
        def _mark_closed(d):
            store.get_pr(d, "pr-001")["status"] = "closed"
        store.locked_update(project["pm_dir"], _mark_closed)

        result = pr_sync.sync_from_github(project["pm_dir"], data=stale)

    assert result.status_updates.get("pr-001") == "merged"
    assert store.get_pr(store.load(project["pm_dir"]),
                        "pr-001")["status"] == "merged"


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


def test_sync_from_github_does_not_reopen_a_merged_pr(tmp_path):
    """A local merge record is terminal too: GitHub OPEN (the merge landed
    outside GitHub) must not rewrite `merged` back to an active status — that
    would erase merged_at/merge evidence and re-block dependents."""
    project = _make_project(tmp_path, status="merged", with_dependent=False)
    with _fake_gh() as backend:
        pr = backend.add_pr(head="pm/pr-001", state="OPEN")
        data = store.load(project["pm_dir"])
        data["prs"][0]["gh_pr_number"] = pr.number
        store.save(data, project["pm_dir"])

        result = pr_sync.sync_from_github(project["pm_dir"], save_state=False)

    assert "pr-001" not in result.status_updates
    assert store.get_pr(store.load(project["pm_dir"]),
                        "pr-001")["status"] == "merged"


def test_sync_from_github_does_not_close_a_merged_pr(tmp_path):
    """GitHub CLOSED does not undo a local merge record either (the evidence
    lives in the registry, not on GitHub)."""
    project = _make_project(tmp_path, status="merged", with_dependent=False)
    with _fake_gh() as backend:
        pr = backend.add_pr(head="pm/pr-001", state="CLOSED")
        data = store.load(project["pm_dir"])
        data["prs"][0]["gh_pr_number"] = pr.number
        store.save(data, project["pm_dir"])

        result = pr_sync.sync_from_github(project["pm_dir"], save_state=False)

    assert "pr-001" not in result.closed_prs
    assert store.get_pr(store.load(project["pm_dir"]),
                        "pr-001")["status"] == "merged"


def test_sync_from_github_keeps_a_concurrently_merged_pr(tmp_path):
    """The apply guard covers `merged` as well: a merge landing between the
    GitHub round-trip and the store lock is not rewritten to in_review."""
    project = _make_project(tmp_path, status="in_progress",
                            with_dependent=False)
    with _fake_gh() as backend:
        pr = backend.add_pr(head="pm/pr-001", state="OPEN")
        data = store.load(project["pm_dir"])
        data["prs"][0]["gh_pr_number"] = pr.number
        store.save(data, project["pm_dir"])
        stale = store.load(project["pm_dir"])

        # `pm pr merge` finalizes before the sync takes the store lock.
        def _mark_merged(d):
            store.get_pr(d, "pr-001")["status"] = "merged"
        store.locked_update(project["pm_dir"], _mark_merged)

        pr_sync.sync_from_github(project["pm_dir"], data=stale)

    assert store.get_pr(store.load(project["pm_dir"]),
                        "pr-001")["status"] == "merged"
