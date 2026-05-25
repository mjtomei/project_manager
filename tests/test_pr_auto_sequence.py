"""Tests for ``pm pr auto-sequence`` CLI dispatch logic.

Each invocation of the command examines the PR's current state and
advances it by at most one phase.  Tests mock store / per-phase commands
and confirm the right dispatch happens on each branch.
"""

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner

from pm_core.cli.pr import pr_auto_sequence


def _pr(status: str, **extra) -> dict:
    pr = {"id": "pr-001", "title": "T", "status": status, "branch": "pm/pr-001"}
    pr.update(extra)
    return pr


def _data_with(pr: dict) -> dict:
    return {"project": {"active_pr": pr["id"]}, "prs": [pr]}


def _locked_update_runs(data: dict):
    """side_effect for store.locked_update that runs the apply fn on *data*.

    ``signoff.act_on_signoff_verdict`` performs its status transition inside
    ``store.locked_update`` and only returns a routing hop when the apply
    callback actually flips the status, so tests must execute the callback.
    """
    def _side(root, fn):
        fn(data)
        return data
    return _side


@pytest.fixture
def runner():
    return CliRunner()


class TestPending:
    def test_pending_invokes_pr_start_background(self, runner, tmp_path):
        pr = _pr("pending")
        with patch("pm_core.cli.pr.state_root", return_value=tmp_path), \
             patch("pm_core.cli.pr.store.load", return_value=_data_with(pr)), \
             patch("pm_core.cli.pr._get_pm_session", return_value="pm-test"), \
             patch("pm_core.cli.pr.pr_start") as mock_start:
            mock_start.callback = MagicMock()
            result = runner.invoke(pr_auto_sequence, ["pr-001"])
        assert result.exit_code == 0, result.output
        assert "started" in result.output


class TestMerged:
    def test_merged_just_reports(self, runner, tmp_path):
        pr = _pr("merged")
        with patch("pm_core.cli.pr.state_root", return_value=tmp_path), \
             patch("pm_core.cli.pr.store.load", return_value=_data_with(pr)):
            result = runner.invoke(pr_auto_sequence, ["pr-001"])
        assert result.exit_code == 0
        assert result.output.strip() == "merged"


class TestInProgress:
    def test_spec_pending_pauses(self, runner, tmp_path):
        pr = _pr("in_progress", spec_pending={"phase": "impl"})
        with patch("pm_core.cli.pr.state_root", return_value=tmp_path), \
             patch("pm_core.cli.pr.store.load", return_value=_data_with(pr)), \
             patch("pm_core.cli.pr._get_pm_session", return_value="pm-test"):
            result = runner.invoke(pr_auto_sequence, ["pr-001"])
        assert result.exit_code == 0
        assert "paused: spec_pending" in result.output

    def test_no_session_pauses(self, runner, tmp_path):
        pr = _pr("in_progress")
        with patch("pm_core.cli.pr.state_root", return_value=tmp_path), \
             patch("pm_core.cli.pr.store.load", return_value=_data_with(pr)), \
             patch("pm_core.cli.pr._get_pm_session", return_value=None):
            result = runner.invoke(pr_auto_sequence, ["pr-001"])
        assert result.exit_code == 0
        assert "no pm tmux session" in result.output

    def test_running_when_not_idle(self, runner, tmp_path):
        pr = _pr("in_progress")
        with patch("pm_core.cli.pr.state_root", return_value=tmp_path), \
             patch("pm_core.cli.pr.store.load", return_value=_data_with(pr)), \
             patch("pm_core.cli.pr._get_pm_session", return_value="pm-test"), \
             patch("pm_core.cli.pr._check_impl_idle", return_value=(False, False)):
            result = runner.invoke(pr_auto_sequence, ["pr-001"])
        assert result.exit_code == 0
        assert "running: implementation" in result.output

    def test_idle_advances_to_review(self, runner, tmp_path):
        pr = _pr("in_progress")
        with patch("pm_core.cli.pr.state_root", return_value=tmp_path), \
             patch("pm_core.cli.pr.store.load", return_value=_data_with(pr)), \
             patch("pm_core.cli.pr._get_pm_session", return_value="pm-test"), \
             patch("pm_core.cli.pr._check_impl_idle", return_value=(True, False)), \
             patch("pm_core.cli.pr.pr_review") as mock_review:
            mock_review.callback = MagicMock()
            result = runner.invoke(pr_auto_sequence, ["pr-001"])
        assert result.exit_code == 0
        assert "advanced: in_review" in result.output

    def test_gone_window_relaunches(self, runner, tmp_path):
        pr = _pr("in_progress")
        with patch("pm_core.cli.pr.state_root", return_value=tmp_path), \
             patch("pm_core.cli.pr.store.load", return_value=_data_with(pr)), \
             patch("pm_core.cli.pr._get_pm_session", return_value="pm-test"), \
             patch("pm_core.cli.pr._check_impl_idle", return_value=(False, True)), \
             patch("pm_core.cli.pr.pr_start") as mock_start:
            mock_start.callback = MagicMock()
            result = runner.invoke(pr_auto_sequence, ["pr-001"])
        assert result.exit_code == 0
        assert "restarted" in result.output


class TestInReview:
    def _ctx(self, pr, **mocks):
        from contextlib import ExitStack
        stack = ExitStack()
        stack.enter_context(patch("pm_core.cli.pr.state_root",
                                  return_value=Path("/tmp/pm-test")))
        stack.enter_context(patch("pm_core.cli.pr.store.load",
                                  return_value=_data_with(pr)))
        stack.enter_context(patch("pm_core.cli.pr._get_pm_session",
                                  return_value="pm-test"))
        for name, value in mocks.items():
            stack.enter_context(patch(f"pm_core.cli.pr.{name}",
                                      return_value=value))
        return stack

    def test_pass_advances_to_qa(self, runner):
        pr = _pr("in_review")
        with self._ctx(pr, _check_review_verdict=("PASS", 1)), \
             patch("pm_core.cli.pr.store.locked_update"), \
             patch("pm_core.cli.pr._launch_qa_detached") as mock_qa:
            result = runner.invoke(pr_auto_sequence, ["pr-001"])
        assert result.exit_code == 0
        assert "advanced: qa" in result.output
        mock_qa.assert_called_once()

    def test_pass_skip_qa_stops(self, runner):
        pr = _pr("in_review")
        data = _data_with(pr)
        data["project"]["skip_qa"] = True
        with patch("pm_core.cli.pr.state_root",
                   return_value=Path("/tmp/pm-test")), \
             patch("pm_core.cli.pr.store.load", return_value=data), \
             patch("pm_core.cli.pr._get_pm_session", return_value="pm-test"), \
             patch("pm_core.cli.pr._check_review_verdict",
                   return_value=("PASS", 1)):
            result = runner.invoke(pr_auto_sequence, ["pr-001"])
        assert result.exit_code == 0
        assert "ready_to_merge" in result.output

    def test_input_required_pauses(self, runner):
        pr = _pr("in_review")
        with self._ctx(pr, _check_review_verdict=("INPUT_REQUIRED", 2)):
            result = runner.invoke(pr_auto_sequence, ["pr-001"])
        assert result.exit_code == 0
        assert "paused: input_required" in result.output

    def test_needs_work_relaunches_review(self, runner):
        pr = _pr("in_review")
        with self._ctx(pr, _check_review_verdict=("NEEDS_WORK", 1)), \
             patch("pm_core.cli.pr.pr_review") as mock_review:
            mock_review.callback = MagicMock()
            result = runner.invoke(pr_auto_sequence, ["pr-001"])
        assert result.exit_code == 0
        assert "needs_work" in result.output
        assert "iteration 2" in result.output

    def test_no_verdict_no_window_launches(self, runner):
        pr = _pr("in_review")
        with self._ctx(pr,
                       _check_review_verdict=(None, 0),
                       _review_window_pane=None), \
             patch("pm_core.cli.pr.pr_review") as mock_review:
            mock_review.callback = MagicMock()
            result = runner.invoke(pr_auto_sequence, ["pr-001"])
        assert result.exit_code == 0
        assert "review_relaunched" in result.output

    def test_no_verdict_with_window_running(self, runner):
        pr = _pr("in_review")
        with self._ctx(pr,
                       _check_review_verdict=(None, 0),
                       _review_window_pane="%5"):
            result = runner.invoke(pr_auto_sequence, ["pr-001"])
        assert result.exit_code == 0
        assert "running: review" in result.output


class TestQA:
    def test_pass_advances_to_sign_off(self, runner, tmp_path):
        pr = _pr("qa")
        with patch("pm_core.cli.pr.state_root", return_value=tmp_path), \
             patch("pm_core.cli.pr.store.load", return_value=_data_with(pr)), \
             patch("pm_core.cli.pr._get_pm_session", return_value="pm-test"), \
             patch("pm_core.cli.pr._qa_status_for",
                   return_value=("PASS", Path("/tmp/qa.json"))), \
             patch("pm_core.cli.pr.store.locked_update"), \
             patch("pm_core.cli.pr.pr_signoff") as mock_signoff:
            mock_signoff.callback = MagicMock()
            result = runner.invoke(pr_auto_sequence, ["pr-001"])
        assert result.exit_code == 0, result.output
        assert "advanced: sign_off" in result.output
        mock_signoff.assert_called_once()

    def test_input_required_pauses(self, runner, tmp_path):
        pr = _pr("qa")
        with patch("pm_core.cli.pr.state_root", return_value=tmp_path), \
             patch("pm_core.cli.pr.store.load", return_value=_data_with(pr)), \
             patch("pm_core.cli.pr._get_pm_session", return_value="pm-test"), \
             patch("pm_core.cli.pr._qa_status_for",
                   return_value=("INPUT_REQUIRED", Path("/tmp/qa.json"))):
            result = runner.invoke(pr_auto_sequence, ["pr-001"])
        assert result.exit_code == 0
        assert "paused: input_required" in result.output

    def test_needs_work_relaunches_review(self, runner, tmp_path):
        pr = _pr("qa")
        with patch("pm_core.cli.pr.state_root", return_value=tmp_path), \
             patch("pm_core.cli.pr.store.load", return_value=_data_with(pr)), \
             patch("pm_core.cli.pr._get_pm_session", return_value="pm-test"), \
             patch("pm_core.cli.pr._qa_status_for",
                   return_value=("NEEDS_WORK", Path("/tmp/qa.json"))), \
             patch("pm_core.cli.pr._check_review_verdict",
                   return_value=("PASS", 1)), \
             patch("pm_core.cli.pr.store.locked_update"), \
             patch("pm_core.cli.pr.pr_review") as mock_review:
            mock_review.callback = MagicMock()
            result = runner.invoke(pr_auto_sequence, ["pr-001"])
        assert result.exit_code == 0
        assert "qa: needs_work" in result.output
        assert "iteration 2" in result.output

    def test_no_status_no_window_launches_qa(self, runner, tmp_path):
        pr = _pr("qa")
        with patch("pm_core.cli.pr.state_root", return_value=tmp_path), \
             patch("pm_core.cli.pr.store.load", return_value=_data_with(pr)), \
             patch("pm_core.cli.pr._get_pm_session", return_value="pm-test"), \
             patch("pm_core.cli.pr._qa_status_for",
                   return_value=(None, None)), \
             patch("pm_core.cli.pr.tmux_mod.find_window_by_name",
                   return_value=None), \
             patch("pm_core.cli.pr._launch_qa_detached") as mock_qa:
            result = runner.invoke(pr_auto_sequence, ["pr-001"])
        assert result.exit_code == 0
        assert "running: qa (launched)" in result.output
        mock_qa.assert_called_once()

    def test_no_status_with_window_does_not_relaunch(self, runner, tmp_path):
        """Race guard: if the qa tmux window exists, treat as still starting."""
        pr = _pr("qa")
        with patch("pm_core.cli.pr.state_root", return_value=tmp_path), \
             patch("pm_core.cli.pr.store.load", return_value=_data_with(pr)), \
             patch("pm_core.cli.pr._get_pm_session", return_value="pm-test"), \
             patch("pm_core.cli.pr._qa_status_for",
                   return_value=(None, None)), \
             patch("pm_core.cli.pr.tmux_mod.find_window_by_name",
                   return_value={"id": "@7", "index": "3"}), \
             patch("pm_core.cli.pr._launch_qa_detached") as mock_qa:
            result = runner.invoke(pr_auto_sequence, ["pr-001"])
        assert result.exit_code == 0
        assert result.output.strip() == "running: qa"
        mock_qa.assert_not_called()


class TestSignOff:
    def test_no_verdict_window_present_running(self, runner, tmp_path):
        pr = _pr("sign_off")
        with patch("pm_core.cli.pr.state_root", return_value=tmp_path), \
             patch("pm_core.cli.pr.store.load", return_value=_data_with(pr)), \
             patch("pm_core.cli.pr._get_pm_session", return_value="pm-test"), \
             patch("pm_core.cli.pr._check_signoff_verdict", return_value=None), \
             patch("pm_core.cli.pr._signoff_window_pane", return_value="%9"):
            result = runner.invoke(pr_auto_sequence, ["pr-001"])
        assert result.exit_code == 0, result.output
        assert result.output.strip() == "running: sign_off"

    def test_no_verdict_no_window_relaunches(self, runner, tmp_path):
        pr = _pr("sign_off")
        with patch("pm_core.cli.pr.state_root", return_value=tmp_path), \
             patch("pm_core.cli.pr.store.load", return_value=_data_with(pr)), \
             patch("pm_core.cli.pr._get_pm_session", return_value="pm-test"), \
             patch("pm_core.cli.pr._check_signoff_verdict", return_value=None), \
             patch("pm_core.cli.pr._signoff_window_pane", return_value=None), \
             patch("pm_core.cli.pr.pr_signoff") as mock_signoff:
            mock_signoff.callback = MagicMock()
            result = runner.invoke(pr_auto_sequence, ["pr-001"])
        assert result.exit_code == 0, result.output
        assert "advanced: sign_off_relaunched" in result.output

    def test_merge_autonomous_reports_ready(self, runner, tmp_path):
        pr = _pr("sign_off")
        data = _data_with(pr)
        data["project"]["sign_off_autonomous"] = True
        with patch("pm_core.cli.pr.state_root", return_value=tmp_path), \
             patch("pm_core.cli.pr.store.load", return_value=data), \
             patch("pm_core.cli.pr._get_pm_session", return_value="pm-test"), \
             patch("pm_core.cli.pr._check_signoff_verdict",
                   return_value="SIGNOFF_MERGE"):
            result = runner.invoke(pr_auto_sequence, ["pr-001"])
        assert result.exit_code == 0, result.output
        assert "ready_to_merge" in result.output

    def test_merge_gated_holds(self, runner, tmp_path):
        pr = _pr("sign_off")  # default gated (no sign_off_autonomous)
        with patch("pm_core.cli.pr.state_root", return_value=tmp_path), \
             patch("pm_core.cli.pr.store.load", return_value=_data_with(pr)), \
             patch("pm_core.cli.pr._get_pm_session", return_value="pm-test"), \
             patch("pm_core.cli.pr._check_signoff_verdict",
                   return_value="SIGNOFF_MERGE"):
            result = runner.invoke(pr_auto_sequence, ["pr-001"])
        assert result.exit_code == 0, result.output
        assert "held: sign_off_gated" in result.output

    def test_blocked_pauses(self, runner, tmp_path):
        pr = _pr("sign_off")
        with patch("pm_core.cli.pr.state_root", return_value=tmp_path), \
             patch("pm_core.cli.pr.store.load", return_value=_data_with(pr)), \
             patch("pm_core.cli.pr._get_pm_session", return_value="pm-test"), \
             patch("pm_core.cli.pr._check_signoff_verdict",
                   return_value="SIGNOFF_BLOCKED"):
            result = runner.invoke(pr_auto_sequence, ["pr-001"])
        assert result.exit_code == 0, result.output
        assert "paused: sign_off_blocked" in result.output

    def test_reqa_relaunches_qa(self, runner, tmp_path):
        pr = _pr("sign_off")
        data = _data_with(pr)
        with patch("pm_core.cli.pr.state_root", return_value=tmp_path), \
             patch("pm_core.cli.pr.store.load", return_value=data), \
             patch("pm_core.cli.pr._get_pm_session", return_value="pm-test"), \
             patch("pm_core.cli.pr._check_signoff_verdict",
                   return_value="SIGNOFF_REQA"), \
             patch("pm_core.cli.pr.store.locked_update",
                   side_effect=_locked_update_runs(data)), \
             patch("pm_core.cli.pr._launch_qa_detached") as mock_qa:
            result = runner.invoke(pr_auto_sequence, ["pr-001"])
        assert result.exit_code == 0, result.output
        assert "sign_off: re-qa" in result.output
        assert pr["status"] == "qa"
        mock_qa.assert_called_once()

    def test_review_relaunches_review(self, runner, tmp_path):
        pr = _pr("sign_off")
        data = _data_with(pr)
        with patch("pm_core.cli.pr.state_root", return_value=tmp_path), \
             patch("pm_core.cli.pr.store.load", return_value=data), \
             patch("pm_core.cli.pr._get_pm_session", return_value="pm-test"), \
             patch("pm_core.cli.pr._check_signoff_verdict",
                   return_value="SIGNOFF_REVIEW"), \
             patch("pm_core.cli.pr.store.locked_update",
                   side_effect=_locked_update_runs(data)), \
             patch("pm_core.cli.pr._check_review_verdict",
                   return_value=("PASS", 2)), \
             patch("pm_core.cli.pr.pr_review") as mock_review:
            mock_review.callback = MagicMock()
            result = runner.invoke(pr_auto_sequence, ["pr-001"])
        assert result.exit_code == 0, result.output
        assert "sign_off: returning to review (iteration 3)" in result.output
        assert pr["status"] == "in_review"

    def test_impl_relaunches_impl(self, runner, tmp_path):
        pr = _pr("sign_off")
        data = _data_with(pr)
        with patch("pm_core.cli.pr.state_root", return_value=tmp_path), \
             patch("pm_core.cli.pr.store.load", return_value=data), \
             patch("pm_core.cli.pr._get_pm_session", return_value="pm-test"), \
             patch("pm_core.cli.pr._check_signoff_verdict",
                   return_value="SIGNOFF_IMPL"), \
             patch("pm_core.cli.pr.store.locked_update",
                   side_effect=_locked_update_runs(data)), \
             patch("pm_core.cli.pr.pr_start") as mock_start:
            mock_start.callback = MagicMock()
            result = runner.invoke(pr_auto_sequence, ["pr-001"])
        assert result.exit_code == 0, result.output
        assert "sign_off: returning to impl" in result.output
        assert pr["status"] == "in_progress"

    def test_bug_pr_missing_captures_blocks_merge(self, runner, tmp_path):
        """A bug PR missing captures: MERGE verdict is overridden to an impl bounce."""
        pr = _pr("sign_off", plan="bugs")
        data = _data_with(pr)
        data["project"]["sign_off_autonomous"] = True
        with patch("pm_core.cli.pr.state_root", return_value=tmp_path), \
             patch("pm_core.cli.pr.store.load", return_value=data), \
             patch("pm_core.cli.pr._get_pm_session", return_value="pm-test"), \
             patch("pm_core.cli.pr._check_signoff_verdict",
                   return_value="SIGNOFF_MERGE"), \
             patch("pm_core.signoff.bug_fix_capture_status",
                   return_value=(False, True)), \
             patch("pm_core.cli.pr.store.locked_update",
                   side_effect=_locked_update_runs(data)), \
             patch("pm_core.cli.pr.pr_start") as mock_start:
            mock_start.callback = MagicMock()
            result = runner.invoke(pr_auto_sequence, ["pr-001"])
        assert result.exit_code == 0, result.output
        assert "sign_off: returning to impl" in result.output
        assert "ready_to_merge" not in result.output
        assert pr["status"] == "in_progress"
