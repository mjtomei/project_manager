"""`pm pr review` phase-regression tests (pr-1cb6e15).

Opening a PR's review after the review step has passed (``qa`` / ``sign_off``)
is an inspection: it must focus the existing review window and leave the PR
exactly as it was.  Before the fix the command fell through to the status
write and silently demoted the PR to ``in_review``, which stranded a running
QA loop / sign-off router (the sign-off driver refuses to collect its verdict
unless the PR is still ``sign_off``).
"""

from __future__ import annotations

import contextlib
from unittest import mock

import pytest
from click.testing import CliRunner

from pm_core import store
from pm_core import tmux as tmux_mod
from pm_core.cli import pr as pr_mod

PR = "pr-001"


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_project(tmp_path, status="qa", backend="vanilla", extra=None):
    """A throwaway pm root with one PR in *status* and a real workdir."""
    root = tmp_path / "pm"
    root.mkdir()
    wd = tmp_path / "wd"
    wd.mkdir()
    pr = {
        "id": PR,
        "title": "T",
        "branch": "pm/pr-001",
        "status": status,
        "workdir": str(wd),
        "gh_pr_number": 42,
    }
    if extra:
        pr.update(extra)
    store.save({
        "project": {"name": "t", "repo": "/r", "base_branch": "master",
                    "backend": backend},
        "prs": [pr],
        "plans": [],
    }, root)
    return root, wd


def _invoke(root, *args):
    runner = CliRunner()
    with mock.patch.object(pr_mod, "state_root", return_value=root), \
         mock.patch.object(pr_mod, "trigger_tui_refresh"):
        return runner.invoke(pr_mod.pr, ["review", *args])


def _pr(root):
    return store.get_pr(store.load(root), PR)


@contextlib.contextmanager
def _review_window(name="review-#42", exists=True):
    """Fake the tmux edges the inspection helper touches."""
    found = {"id": "@3", "index": 3, "name": name} if exists else None
    with mock.patch.object(pr_mod, "_get_pm_session", return_value="pm-test"), \
         mock.patch.object(tmux_mod, "has_tmux", return_value=True), \
         mock.patch.object(tmux_mod, "in_tmux", return_value=True), \
         mock.patch.object(tmux_mod, "session_exists", return_value=True), \
         mock.patch.object(tmux_mod, "find_window_by_name",
                           return_value=found), \
         mock.patch.object(tmux_mod, "select_window") as select:
        yield select


# ---------------------------------------------------------------------------
# qa / sign_off: inspection, never a phase transition
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("status,phase", [("qa", "QA"),
                                          ("sign_off", "sign-off")])
def test_review_after_review_step_leaves_status_unchanged(tmp_path, status,
                                                          phase):
    root, _ = _make_project(tmp_path, status=status)
    before = _pr(root)

    with _review_window() as select, \
         mock.patch.object(pr_mod, "_launch_review_window") as launch:
        result = _invoke(root, PR)

    assert result.exit_code == 0, result.output
    after = _pr(root)
    assert after["status"] == status
    assert after.get("reviewed_at") == before.get("reviewed_at")
    assert after == before
    launch.assert_not_called()
    select.assert_called_once_with("pm-test", "@3")
    assert phase in result.output
    assert "without changing status" in result.output


@pytest.mark.parametrize("exists", [True, False], ids=["focused", "no-window"])
def test_inspection_output_is_one_line_for_the_tui_log(tmp_path, exists):
    """The TUI's spawned-command log keeps only the last stdout line.

    `pr_view._run_command_async` logs ``stdout.split("\\n")[-1]``, so the
    inspection notice must be a single line for the TUI 'd' path to show it.
    """
    root, _ = _make_project(tmp_path, status="qa")

    with _review_window(exists=exists), \
         mock.patch.object(pr_mod, "_launch_review_window"):
        result = _invoke(root, PR)

    assert result.exit_code == 0, result.output
    lines = result.output.strip().splitlines()
    assert len(lines) == 1, lines
    assert "in QA" in lines[0] and "status" in lines[0]


def test_review_inspection_preserves_signoff_and_return_records(tmp_path):
    """Inspection must not touch approval/return/claim state."""
    signoff = {"verdict": "SIGNOFF_MERGE", "sha": "abc123", "ts": "t",
               "origin": "auto-sequence"}
    ret = {"verdict": "SIGNOFF_REQA", "hop": "qa", "awaiting": "qa",
           "launch_claim": {"hop": "qa", "at": "t"}, "ts": "t"}
    integration = {"head": "abc123", "status": "up_to_date",
                   "base_branch": "master"}
    root, _ = _make_project(
        tmp_path, status="sign_off",
        extra={"signoff": signoff, "signoff_return": ret,
               "integration": integration})

    with _review_window(), \
         mock.patch.object(pr_mod, "_launch_review_window"):
        result = _invoke(root, PR)

    assert result.exit_code == 0, result.output
    after = _pr(root)
    assert after["status"] == "sign_off"
    assert after["signoff"] == signoff
    assert after["signoff_return"] == ret
    assert after["integration"] == integration


@pytest.mark.parametrize("status", ["qa", "sign_off"])
def test_inspection_does_not_trigger_tui_refresh(tmp_path, status):
    """Nothing on disk changed, so no reload signal may be sent.

    A spurious refresh makes the TUI reload project.yaml and can race a
    concurrent QA-loop / sign-off write — the exact state churn this fix
    exists to avoid.
    """
    root, _ = _make_project(tmp_path, status=status)
    runner = CliRunner()

    with _review_window(), \
         mock.patch.object(pr_mod, "state_root", return_value=root), \
         mock.patch.object(pr_mod, "_launch_review_window"), \
         mock.patch.object(pr_mod, "trigger_tui_refresh") as refresh:
        result = runner.invoke(pr_mod.pr, ["review", PR])

    assert result.exit_code == 0, result.output
    refresh.assert_not_called()


@pytest.mark.parametrize("status", ["qa", "sign_off"])
def test_review_without_review_window_starts_nothing(tmp_path, status):
    root, _ = _make_project(tmp_path, status=status)

    with _review_window(exists=False) as select, \
         mock.patch.object(pr_mod, "_launch_review_window") as launch:
        result = _invoke(root, PR)

    assert result.exit_code == 0, result.output
    assert _pr(root)["status"] == status
    launch.assert_not_called()
    select.assert_not_called()
    assert "no review window" in result.output
    assert "no new review started" in result.output


@pytest.mark.parametrize("status", ["qa", "sign_off"])
def test_fresh_review_after_review_step_is_refused(tmp_path, status):
    root, _ = _make_project(tmp_path, status=status)

    with _review_window() as select, \
         mock.patch.object(pr_mod, "_launch_review_window") as launch:
        result = _invoke(root, "--fresh", PR)

    assert result.exit_code != 0
    assert _pr(root)["status"] == status
    launch.assert_not_called()
    select.assert_not_called()
    assert "refused" in result.output


def test_review_loop_after_review_step_is_refused(tmp_path):
    root, _ = _make_project(tmp_path, status="sign_off")

    with _review_window(), \
         mock.patch.object(pr_mod, "_launch_review_window") as launch:
        result = _invoke(root, "--review-loop", PR)

    assert result.exit_code != 0
    assert _pr(root)["status"] == "sign_off"
    launch.assert_not_called()


@pytest.mark.parametrize("status", ["qa", "sign_off"])
def test_no_window_on_later_phase_is_a_noop(tmp_path, status):
    root, _ = _make_project(tmp_path, status=status)

    with _review_window() as select, \
         mock.patch.object(pr_mod, "_launch_review_window") as launch:
        result = _invoke(root, "--no-window", PR)

    assert result.exit_code == 0, result.output
    assert _pr(root)["status"] == status
    launch.assert_not_called()
    select.assert_not_called()
    assert "status unchanged" in result.output


def test_qa_inspection_skips_github_draft_upgrade(tmp_path):
    """The qa/sign_off branch returns before the mark-ready step."""
    root, _ = _make_project(tmp_path, status="qa", backend="github")

    with _review_window(), \
         mock.patch.object(pr_mod, "_launch_review_window"), \
         mock.patch("pm_core.gh_ops.mark_pr_ready") as mark_ready:
        result = _invoke(root, PR)

    assert result.exit_code == 0, result.output
    mark_ready.assert_not_called()


# ---------------------------------------------------------------------------
# Terminal statuses
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("status", ["merged", "closed"])
def test_terminal_pr_review_is_refused(tmp_path, status):
    root, _ = _make_project(tmp_path, status=status)

    with mock.patch.object(pr_mod, "_launch_review_window") as launch:
        result = _invoke(root, PR)

    assert result.exit_code != 0
    assert _pr(root)["status"] == status
    launch.assert_not_called()
    assert status in result.output


# ---------------------------------------------------------------------------
# Existing phases still transition / launch
# ---------------------------------------------------------------------------

def test_in_review_still_launches_without_status_change(tmp_path):
    root, _ = _make_project(tmp_path, status="in_review")

    with mock.patch.object(pr_mod, "_launch_review_window") as launch:
        result = _invoke(root, PR)

    assert result.exit_code == 0, result.output
    assert _pr(root)["status"] == "in_review"
    launch.assert_called_once()


def test_in_progress_still_moves_to_in_review_and_launches(tmp_path):
    root, _ = _make_project(tmp_path, status="in_progress")

    with mock.patch.object(pr_mod, "_launch_review_window") as launch:
        result = _invoke(root, PR)

    assert result.exit_code == 0, result.output
    assert _pr(root)["status"] == "in_review"
    launch.assert_called_once()


def test_in_progress_github_still_upgrades_draft(tmp_path):
    root, _ = _make_project(tmp_path, status="in_progress", backend="github")

    with mock.patch.object(pr_mod, "_launch_review_window"), \
         mock.patch("pm_core.gh_ops.mark_pr_ready",
                    return_value=True) as mark_ready:
        result = _invoke(root, PR)

    assert result.exit_code == 0, result.output
    assert _pr(root)["status"] == "in_review"
    mark_ready.assert_called_once()


# ---------------------------------------------------------------------------
# _focus_review_window itself
# ---------------------------------------------------------------------------

def test_focus_review_window_selects_existing(tmp_path):
    root, _ = _make_project(tmp_path, status="qa")
    pr = _pr(root)
    focus = getattr(pr_mod, "_focus_review_window")

    with _review_window("review-#42") as select:
        name = focus(pr)

    assert name == "review-#42"
    select.assert_called_once_with("pm-test", "@3")


def test_focus_review_window_never_creates_a_window(tmp_path):
    root, _ = _make_project(tmp_path, status="qa")
    pr = _pr(root)
    focus = getattr(pr_mod, "_focus_review_window")

    with _review_window(exists=False) as select, \
         mock.patch.object(tmux_mod, "new_window") as new_window, \
         mock.patch.object(tmux_mod, "new_window_get_pane") as new_pane:
        name = focus(pr)

    assert name is None
    select.assert_not_called()
    new_window.assert_not_called()
    new_pane.assert_not_called()


def test_focus_review_window_reports_failure_to_switch(tmp_path):
    root, _ = _make_project(tmp_path, status="qa")
    pr = _pr(root)
    focus = getattr(pr_mod, "_focus_review_window")

    with _review_window() as select:
        select.return_value = False
        assert focus(pr) is None


def test_focus_review_window_outside_tmux_is_a_noop(tmp_path):
    root, _ = _make_project(tmp_path, status="qa")
    pr = _pr(root)
    focus = getattr(pr_mod, "_focus_review_window")

    with mock.patch.object(tmux_mod, "in_tmux", return_value=False), \
         mock.patch.object(tmux_mod, "find_window_by_name") as find:
        assert focus(pr) is None

    find.assert_not_called()
