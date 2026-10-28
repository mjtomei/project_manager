"""Tests for ``pm pr auto-sequence`` CLI dispatch logic.

Each invocation of the command examines the PR's current state and
advances it by at most one phase.  Tests mock store / per-phase commands
and confirm the right dispatch happens on each branch.
"""

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner

from pm_core.cli.pr import pr_auto_sequence, pr_qa_run_bg
from pm_core.qa_loop import write_launch_record as _REAL_WRITE_LAUNCH_RECORD


def _pr(status: str, **extra) -> dict:
    pr = {"id": "pr-001", "title": "T", "status": status, "branch": "pm/pr-001"}
    pr.update(extra)
    return pr


# What the launch-time integration check records for HEAD "abc".
_INTEG = {"head": "abc", "status": "up_to_date", "base_branch": "master",
          "target_repo": "/repo", "base_sha": "base", "candidate_tree": "tree"}


def _signoff_pr() -> dict:
    """A sign_off PR at HEAD "abc" with a clean integration check of it."""
    return _pr("sign_off", workdir="/wd", integration=dict(_INTEG))


def _data_with(pr: dict) -> dict:
    return {"project": {"active_pr": pr["id"]}, "prs": [pr]}


def _locked_update_runs(data: dict):
    """side_effect for store.locked_update that runs the apply fn on *data*.

    ``signoff.apply_signoff_hop`` performs its status transition inside
    ``store.locked_update`` and only returns the bounce hop when the apply
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


    def _stopped_run(self, tmp_path):
        """A qa_status.json that record_setup_stop marked (S94)."""
        import json
        status = tmp_path / "pr-001-x" / "qa_status.json"
        status.parent.mkdir()
        status.write_text(json.dumps({"pr_id": "pr-001", "scenarios": [],
                                      "overall": "", "stopped": "boom"}))
        return status

    def test_stopped_run_with_window_relaunches(self, runner, tmp_path):
        """S94: a run a provider setup error ended keeps its qa window but
        has no driver: the tick relaunches it instead of `running: qa`."""
        pr = _pr("qa")
        status = self._stopped_run(tmp_path)
        with patch("pm_core.cli.pr.state_root", return_value=tmp_path), \
             patch("pm_core.cli.pr.store.load", return_value=_data_with(pr)), \
             patch("pm_core.cli.pr._get_pm_session", return_value="pm-test"), \
             patch("pm_core.cli.pr._qa_status_for",
                   return_value=(None, status)), \
             patch("pm_core.cli.pr.tmux_mod.find_window_by_name",
                   return_value={"id": "@7", "index": "3"}), \
             patch("pm_core.qa_loop.own_run_started_since",
                   return_value=False), \
             patch("pm_core.cli.pr._qa_run_driven", return_value=False), \
             patch("pm_core.cli.pr._launch_qa_detached") as mock_qa:
            result = runner.invoke(pr_auto_sequence, ["pr-001"])
        assert result.exit_code == 0, result.output
        assert result.output.strip() == "running: qa (relaunched)"
        mock_qa.assert_called_once()

    @pytest.mark.parametrize("newer,driven", [(True, False), (False, True)])
    def test_stopped_run_replaced_or_driven_is_left_alone(
            self, runner, tmp_path, newer, driven):
        """A run started after the stop (a TUI t), or a live driver, owns
        the PR's QA: no second driver."""
        pr = _pr("qa")
        status = self._stopped_run(tmp_path)
        with patch("pm_core.cli.pr.state_root", return_value=tmp_path), \
             patch("pm_core.cli.pr.store.load", return_value=_data_with(pr)), \
             patch("pm_core.cli.pr._get_pm_session", return_value="pm-test"), \
             patch("pm_core.cli.pr._qa_status_for",
                   return_value=(None, status)), \
             patch("pm_core.cli.pr.tmux_mod.find_window_by_name",
                   return_value={"id": "@7", "index": "3"}), \
             patch("pm_core.qa_loop.own_run_started_since",
                   return_value=newer), \
             patch("pm_core.cli.pr._qa_run_driven", return_value=driven), \
             patch("pm_core.cli.pr._launch_qa_detached") as mock_qa:
            result = runner.invoke(pr_auto_sequence, ["pr-001"])
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

    def test_merge_always_reports_ready(self, runner, tmp_path):
        """Sign-off always gates: SIGNOFF_MERGE -> ready_to_merge recommendation."""
        pr = _signoff_pr()
        data = _data_with(pr)
        with patch("pm_core.cli.pr.state_root", return_value=tmp_path), \
             patch("pm_core.signoff.head_sha", return_value="abc"), \
             patch("pm_core.signoff.signoff_launched_sha", return_value="abc"), \
             patch("pm_core.cli.pr.store.load", return_value=data), \
             patch("pm_core.cli.pr._get_pm_session", return_value="pm-test"), \
             patch("pm_core.cli.pr._check_signoff_verdict",
                   return_value="SIGNOFF_MERGE"), \
             patch("pm_core.cli.pr.store.locked_update",
                   side_effect=_locked_update_runs(data)):
            result = runner.invoke(pr_auto_sequence, ["pr-001"])
        assert result.exit_code == 0, result.output
        assert "ready_to_merge" in result.output
        # PR stays in sign_off (sign-off never merges)
        assert pr["status"] == "sign_off"

    def test_blocked_pauses(self, runner, tmp_path):
        pr = _pr("sign_off")
        data = _data_with(pr)
        with patch("pm_core.cli.pr.state_root", return_value=tmp_path), \
             patch("pm_core.cli.pr.store.load", return_value=data), \
             patch("pm_core.cli.pr._get_pm_session", return_value="pm-test"), \
             patch("pm_core.cli.pr._check_signoff_verdict",
                   return_value="SIGNOFF_BLOCKED"), \
             patch("pm_core.cli.pr.store.locked_update",
                   side_effect=_locked_update_runs(data)):
            result = runner.invoke(pr_auto_sequence, ["pr-001"])
        assert result.exit_code == 0, result.output
        assert "paused: sign_off_blocked" in result.output

    def test_adopts_fresh_recorded_verdict(self, runner, tmp_path):
        """A fresh record (sha == HEAD) is adopted without relaunch or transcript."""
        pr = _pr("sign_off")
        pr["signoff"] = {"verdict": "SIGNOFF_REQA", "sha": "abc", "origin": "manual"}
        data = _data_with(pr)
        with patch("pm_core.cli.pr.state_root", return_value=tmp_path), \
             patch("pm_core.cli.pr.store.load", return_value=data), \
             patch("pm_core.cli.pr._get_pm_session", return_value="pm-test"), \
             patch("pm_core.signoff.head_sha", return_value="abc"), \
             patch("pm_core.cli.pr._check_signoff_verdict") as mock_tx, \
             patch("pm_core.cli.pr.store.locked_update",
                   side_effect=_locked_update_runs(data)), \
             patch("pm_core.cli.pr._launch_qa_detached") as mock_qa:
            result = runner.invoke(pr_auto_sequence, ["pr-001"])
        assert result.exit_code == 0, result.output
        assert "sign_off: re-qa" in result.output
        assert pr["status"] == "qa"
        mock_tx.assert_not_called()        # adopted record, didn't read transcript
        mock_qa.assert_called_once()
        # The adopted bounce verdict is consumed so a later sign_off re-entry
        # (re-qa never changes HEAD) can't re-adopt it and loop forever.
        assert "signoff" not in pr

    def test_stale_record_retires_and_relaunches(self, runner, tmp_path):
        """A stale record (sha != HEAD) is an outdated run: retire it + relaunch
        a fresh router instead of replaying its verdict/transcript (R11)."""
        pr = _pr("sign_off")
        pr["signoff"] = {"verdict": "SIGNOFF_BLOCKED", "sha": "old",
                         "origin": "auto-sequence"}
        data = _data_with(pr)
        with patch("pm_core.cli.pr.state_root", return_value=tmp_path), \
             patch("pm_core.cli.pr.store.load", return_value=data), \
             patch("pm_core.cli.pr._get_pm_session", return_value="pm-test"), \
             patch("pm_core.signoff.head_sha", return_value="new"), \
             patch("pm_core.cli.pr.store.locked_update",
                   side_effect=_locked_update_runs(data)), \
             patch("pm_core.cli.pr._retire_signoff_window") as mock_retire, \
             patch("pm_core.cli.pr._check_signoff_verdict") as mock_tx, \
             patch("pm_core.cli.pr.pr_signoff") as mock_signoff:
            mock_signoff.callback = MagicMock()
            result = runner.invoke(pr_auto_sequence, ["pr-001"])
        assert result.exit_code == 0, result.output
        assert "advanced: sign_off_relaunched" in result.output
        mock_retire.assert_called_once()
        mock_tx.assert_not_called()        # stale run is not replayed
        assert "signoff" not in pr         # stale record cleared

    def test_records_transcript_verdict_when_no_fresh_record(self, runner, tmp_path):
        pr = _pr("sign_off")
        data = _data_with(pr)
        with patch("pm_core.cli.pr.state_root", return_value=tmp_path), \
             patch("pm_core.cli.pr.store.load", return_value=data), \
             patch("pm_core.cli.pr._get_pm_session", return_value="pm-test"), \
             patch("pm_core.signoff.head_sha", return_value="abc"), \
             patch("pm_core.signoff.signoff_launched_sha", return_value="abc"), \
             patch("pm_core.cli.pr._check_signoff_verdict",
                   return_value="SIGNOFF_BLOCKED"), \
             patch("pm_core.cli.pr.store.locked_update",
                   side_effect=_locked_update_runs(data)):
            result = runner.invoke(pr_auto_sequence, ["pr-001"])
        assert result.exit_code == 0, result.output
        assert "paused: sign_off_blocked" in result.output
        # the transcript verdict was recorded (origin auto-sequence) for adoption
        assert pr["signoff"]["verdict"] == "SIGNOFF_BLOCKED"
        assert pr["signoff"]["origin"] == "auto-sequence"
        assert pr["signoff"]["sha"] == "abc"

    def test_verdict_of_run_launched_on_old_head_not_recorded(self, runner,
                                                               tmp_path):
        """HEAD moved while the router ran: its verdict reviewed the launched
        HEAD, not the current one -> retire + relaunch, record nothing."""
        pr = _pr("sign_off")
        data = _data_with(pr)
        with patch("pm_core.cli.pr.state_root", return_value=tmp_path), \
             patch("pm_core.cli.pr.store.load", return_value=data), \
             patch("pm_core.cli.pr._get_pm_session", return_value="pm-test"), \
             patch("pm_core.signoff.head_sha", return_value="new"), \
             patch("pm_core.signoff.signoff_launched_sha", return_value="old"), \
             patch("pm_core.cli.pr._check_signoff_verdict",
                   return_value="SIGNOFF_MERGE"), \
             patch("pm_core.cli.pr.store.locked_update",
                   side_effect=_locked_update_runs(data)), \
             patch("pm_core.cli.pr._retire_signoff_window") as mock_retire, \
             patch("pm_core.cli.pr.pr_signoff") as mock_signoff:
            mock_signoff.callback = MagicMock()
            result = runner.invoke(pr_auto_sequence, ["pr-001"])
        assert result.exit_code == 0, result.output
        assert "advanced: sign_off_relaunched" in result.output
        assert "ready_to_merge" not in result.output
        mock_retire.assert_called_once()
        assert "signoff" not in pr

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
             patch("pm_core.cli.pr._retire_signoff_window") as mock_retire, \
             patch("pm_core.cli.pr._launch_qa_detached") as mock_qa:
            result = runner.invoke(pr_auto_sequence, ["pr-001"])
        assert result.exit_code == 0, result.output
        assert "sign_off: re-qa" in result.output
        assert pr["status"] == "qa"
        mock_qa.assert_called_once()
        # The stale sign-off window + transcript are retired so the next
        # sign_off entry runs a fresh router (no stale-verdict replay loop).
        mock_retire.assert_called_once()

    def test_reqa_leaves_a_run_driven_elsewhere_to_finish(self, runner,
                                                         tmp_path):
        """S120: the user's ``pm qa run`` still runs when sign-off says
        REQA.  The hop tick must not launch qa-run-bg over it (that kills
        its windows as stale and runs a second loop beside it): the return
        stays awaiting qa, and a later qa tick launches once it ends."""
        pr = _pr("sign_off")
        data = _data_with(pr)
        with patch("pm_core.cli.pr.state_root", return_value=tmp_path), \
             patch("pm_core.cli.pr.store.load", return_value=data), \
             patch("pm_core.cli.pr._get_pm_session", return_value="pm-test"), \
             patch("pm_core.cli.pr._check_signoff_verdict",
                   return_value="SIGNOFF_REQA"), \
             patch("pm_core.cli.pr.store.locked_update",
                   side_effect=_locked_update_runs(data)), \
             patch("pm_core.cli.pr._retire_signoff_window"), \
             patch("pm_core.cli.pr._qa_run_driven", return_value=True), \
             patch("pm_core.cli.pr._launch_qa_detached") as mock_qa:
            result = runner.invoke(pr_auto_sequence, ["pr-001"])
        assert result.exit_code == 0, result.output
        assert result.output.strip() == "sign_off: re-qa"
        assert pr["status"] == "qa"
        assert pr["signoff_return"]["awaiting"] == "qa"
        assert "launch_claim" not in pr["signoff_return"]
        mock_qa.assert_not_called()

    def test_bounce_retires_window_but_recommendation_does_not(self, runner, tmp_path):
        """A bounce retires the sign-off window; ready_to_merge/blocked don't
        (the PR legitimately stays in sign_off, so its window/verdict persist)."""
        for verdict, hop_echo in (("SIGNOFF_MERGE", "ready_to_merge"),
                                  ("SIGNOFF_BLOCKED", "paused: sign_off_blocked")):
            pr = _signoff_pr()
            data = _data_with(pr)
            with patch("pm_core.cli.pr.state_root", return_value=tmp_path), \
                 patch("pm_core.signoff.head_sha", return_value="abc"), \
                 patch("pm_core.signoff.signoff_launched_sha", return_value="abc"), \
                 patch("pm_core.cli.pr.store.load", return_value=data), \
                 patch("pm_core.cli.pr._get_pm_session", return_value="pm-test"), \
                 patch("pm_core.cli.pr._check_signoff_verdict",
                       return_value=verdict), \
                 patch("pm_core.cli.pr.store.locked_update",
                       side_effect=_locked_update_runs(data)), \
                 patch("pm_core.cli.pr._retire_signoff_window") as mock_retire:
                result = runner.invoke(pr_auto_sequence, ["pr-001"])
            assert result.exit_code == 0, result.output
            assert hop_echo in result.output
            mock_retire.assert_not_called()

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

    def test_retire_signoff_window_kills_and_unlinks(self, tmp_path):
        from pm_core.cli.pr import _retire_signoff_window
        pr = _pr("sign_off")
        transcript = tmp_path / "signoff-pr-001.jsonl"
        transcript.write_text("{}")
        with patch("pm_core.tmux.find_window_by_name",
                   return_value={"id": "@7", "index": 3, "name": "signoff-pr-001"}), \
             patch("pm_core.home_window.park_if_on") as mock_park, \
             patch("pm_core.tmux.kill_window") as mock_kill:
            _retire_signoff_window("pm-test", pr, tmp_path)
        mock_park.assert_called_once_with("pm-test", "@7")
        mock_kill.assert_called_once_with("pm-test", "@7")
        assert not transcript.exists()  # stale transcript removed

    def test_retire_signoff_window_no_window_is_safe(self, tmp_path):
        from pm_core.cli.pr import _retire_signoff_window
        pr = _pr("sign_off")
        with patch("pm_core.tmux.find_window_by_name", return_value=None), \
             patch("pm_core.tmux.kill_window") as mock_kill:
            _retire_signoff_window("pm-test", pr, tmp_path)  # no transcript, no window
        mock_kill.assert_not_called()

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
        # A bounce must RELAUNCH the impl agent (fresh=True): with fresh=False
        # an existing idle impl window short-circuits pr_start's background
        # fast path and no rework ever runs.
        mock_start.assert_called_once()
        assert mock_start.call_args.kwargs["fresh"] is True


class TestTuiRefresh:
    """QA s8 (pr-0b87a97): auto-sequence wrote ``sign_off`` + the SIGNOFF_MERGE
    record without signalling the TUI, so its auto-start rows kept saying
    "awaiting sign-off (press i …)" / "no fresh SIGNOFF_MERGE" until some
    unrelated reload."""

    def test_qa_pass_to_sign_off_refreshes_tui(self, runner, tmp_path):
        pr = _pr("qa")
        with patch("pm_core.cli.pr.state_root", return_value=tmp_path), \
             patch("pm_core.cli.pr.store.load", return_value=_data_with(pr)), \
             patch("pm_core.cli.pr._get_pm_session", return_value="pm-test"), \
             patch("pm_core.cli.pr._qa_status_for",
                   return_value=("PASS", Path("/tmp/qa.json"))), \
             patch("pm_core.cli.pr.store.locked_update"), \
             patch("pm_core.cli.pr.trigger_tui_refresh") as mock_refresh, \
             patch("pm_core.cli.pr.pr_signoff") as mock_signoff:
            mock_signoff.callback = MagicMock()
            result = runner.invoke(pr_auto_sequence, ["pr-001"])
        assert result.exit_code == 0, result.output
        mock_refresh.assert_called()

    def test_recorded_signoff_refreshes_tui(self, runner, tmp_path):
        pr = _signoff_pr()
        data = _data_with(pr)
        with patch("pm_core.cli.pr.state_root", return_value=tmp_path), \
             patch("pm_core.signoff.head_sha", return_value="abc"), \
             patch("pm_core.signoff.signoff_launched_sha", return_value="abc"), \
             patch("pm_core.cli.pr.store.load", return_value=data), \
             patch("pm_core.cli.pr._get_pm_session", return_value="pm-test"), \
             patch("pm_core.cli.pr._check_signoff_verdict",
                   return_value="SIGNOFF_MERGE"), \
             patch("pm_core.cli.pr.store.locked_update",
                   side_effect=_locked_update_runs(data)), \
             patch("pm_core.cli.pr.trigger_tui_refresh") as mock_refresh:
            result = runner.invoke(pr_auto_sequence, ["pr-001"])
        assert "ready_to_merge" in result.output
        mock_refresh.assert_called()


class TestQaRunBgGuard:
    """The detached QA driver must not run against an out-of-band merged PR.

    A concurrent merge (e.g. a GitHub sync) can land between the
    auto-sequence sign_off->qa bounce that spawns ``pr qa-run-bg`` and that
    subprocess starting.  ``apply_signoff_hop``'s lock only guards the status
    transition, so without a guard the detached driver opens a qa-<id> window
    and runs a full QA loop against an already-merged PR.
    """

    def test_skips_qa_when_pr_merged(self, runner, tmp_path):
        pr = _pr("merged")
        data = _data_with(pr)
        with patch("pm_core.cli.pr.state_root", return_value=tmp_path), \
             patch("pm_core.cli.pr.store.load", return_value=data), \
             patch("pm_core.cli.pr.store.locked_update",
                   side_effect=_locked_update_runs(data)), \
             patch("pm_core.qa_loop.run_qa_sync") as mock_run:
            result = runner.invoke(pr_qa_run_bg, ["pr-001"])
        assert result.exit_code == 0, result.output
        # run_qa_sync creates the qa-<id> window; it must never be reached.
        mock_run.assert_not_called()
        assert pr["status"] == "merged"

    def test_skips_qa_when_pr_closed(self, runner, tmp_path):
        pr = _pr("closed")
        data = _data_with(pr)
        with patch("pm_core.cli.pr.state_root", return_value=tmp_path), \
             patch("pm_core.cli.pr.store.load", return_value=data), \
             patch("pm_core.cli.pr.store.locked_update",
                   side_effect=_locked_update_runs(data)), \
             patch("pm_core.qa_loop.run_qa_sync") as mock_run:
            result = runner.invoke(pr_qa_run_bg, ["pr-001"])
        assert result.exit_code == 0, result.output
        mock_run.assert_not_called()

    def test_runs_qa_when_pr_in_qa(self, runner, tmp_path):
        pr = _pr("qa")
        data = _data_with(pr)
        with patch("pm_core.cli.pr.state_root", return_value=tmp_path), \
             patch("pm_core.cli.pr.store.load", return_value=data), \
             patch("pm_core.cli.pr.store.locked_update",
                   side_effect=_locked_update_runs(data)), \
             patch("pm_core.qa_loop.run_qa_sync") as mock_run:
            result = runner.invoke(pr_qa_run_bg, ["pr-001"])
        assert result.exit_code == 0, result.output
        # A genuinely qa-eligible PR still drives the loop.
        mock_run.assert_called_once()


class TestQaRunBgRuntimeState:
    """The CLI QA driver must mirror its run into the shared runtime state.

    Only TUI-owned loops mirror themselves, so a run launched by
    ``pr auto-sequence`` used to leave no ``~/.pm/runtime/<id>.json``: the
    popup picker could not show its progress and auto-start's
    ``recorded_qa_verdict`` could not see its verdict (so a concurrent
    scheduler could relaunch QA for a PR this driver already took to PASS).
    """

    def test_records_running_then_done_verdict(self, runner, tmp_path):
        from pm_core import runtime_state
        pr = _pr("qa")
        data = _data_with(pr)
        seen: list[str | None] = []

        def _run(state, *a, **kw):
            seen.append(runtime_state.get_action_state("pr-001", "qa").get("state"))
            state.latest_verdict = "PASS"

        rt = tmp_path / "runtime"
        rt.mkdir()
        with patch("pm_core.runtime_state._runtime_dir", return_value=rt), \
             patch("pm_core.cli.pr.state_root", return_value=tmp_path), \
             patch("pm_core.cli.pr.store.load", return_value=data), \
             patch("pm_core.cli.pr.store.locked_update",
                   side_effect=_locked_update_runs(data)), \
             patch("pm_core.signoff.clear_return_awaiting"), \
             patch("pm_core.qa_loop.run_qa_sync", side_effect=_run):
            result = runner.invoke(pr_qa_run_bg, ["pr-001"])

            assert result.exit_code == 0, result.output
            # The run was observable in the shared state while it ran ...
            assert seen == ["running"]
            # ... and its verdict survives for the popup picker and auto-start.
            rec = runtime_state.get_action_state("pr-001", "qa")
            assert rec.get("state") == "done"
            assert rec.get("verdict") == "PASS"
            assert (rt / "pr-001.json").exists()

    def test_keeps_pending_suppress_switch(self, runner, tmp_path):
        from pm_core import runtime_state
        pr = _pr("qa")
        data = _data_with(pr)
        rt = tmp_path / "runtime"
        rt.mkdir()
        with patch("pm_core.runtime_state._runtime_dir", return_value=rt), \
             patch("pm_core.cli.pr.state_root", return_value=tmp_path), \
             patch("pm_core.cli.pr.store.load", return_value=data), \
             patch("pm_core.cli.pr.store.locked_update",
                   side_effect=_locked_update_runs(data)), \
             patch("pm_core.signoff.clear_return_awaiting"), \
             patch("pm_core.qa_loop.run_qa_sync"):
            runtime_state.request_suppress_switch("pr-001", "qa")
            result = runner.invoke(pr_qa_run_bg, ["pr-001"])

            assert result.exit_code == 0, result.output
            rec = runtime_state.get_action_state("pr-001", "qa")
            # The finished run leaves no [working] entry behind ...
            assert rec.get("state") is None
            # ... but the flag belongs to the user's start for this PR, not
            # to this driver, so it survives.
            assert rec.get("suppress_switch") is True

    def test_no_verdict_leaves_no_running_entry(self, runner, tmp_path):
        """A run that aborts without a verdict (the PR merged mid-run) must
        not leave the picker and home window showing a live QA run."""
        from pm_core import runtime_state
        pr = _pr("qa")
        data = _data_with(pr)
        rt = tmp_path / "runtime"
        rt.mkdir()
        with patch("pm_core.runtime_state._runtime_dir", return_value=rt), \
             patch("pm_core.cli.pr.state_root", return_value=tmp_path), \
             patch("pm_core.cli.pr.store.load", return_value=data), \
             patch("pm_core.cli.pr.store.locked_update",
                   side_effect=_locked_update_runs(data)), \
             patch("pm_core.signoff.clear_return_awaiting"), \
             patch("pm_core.qa_loop.run_qa_sync"):
            result = runner.invoke(pr_qa_run_bg, ["pr-001"])

            assert result.exit_code == 0, result.output
            assert runtime_state.get_action_state("pr-001", "qa") == {}

    def test_failure_marks_action_failed(self, runner, tmp_path):
        from pm_core import runtime_state
        pr = _pr("qa")
        data = _data_with(pr)
        rt = tmp_path / "runtime"
        rt.mkdir()
        with patch("pm_core.runtime_state._runtime_dir", return_value=rt), \
             patch("pm_core.cli.pr.state_root", return_value=tmp_path), \
             patch("pm_core.cli.pr.store.load", return_value=data), \
             patch("pm_core.cli.pr.store.locked_update",
                   side_effect=_locked_update_runs(data)), \
             patch("pm_core.signoff.clear_return_awaiting"), \
             patch("pm_core.qa_loop.run_qa_sync",
                   side_effect=RuntimeError("boom")):
            result = runner.invoke(pr_qa_run_bg, ["pr-001"])

            assert result.exit_code == 1
            rec = runtime_state.get_action_state("pr-001", "qa")
            assert rec.get("state") == "failed"

    def test_setup_error_marks_run_stopped(self, runner, tmp_path):
        """S94: a provider setup error marks the run's status file stopped
        and drops its snapshot, so a later tick relaunches QA."""
        import json
        from pm_core.providers import ProviderNotFoundError
        pr = _pr("qa")
        data = _data_with(pr)
        rt = tmp_path / "runtime"
        rt.mkdir()
        wd = tmp_path / "qa-wd"
        wd.mkdir()
        (wd / "qa_resume.json").write_text("{}")

        def _run(state, *a, **kw):
            state.qa_workdir = str(wd)
            raise ProviderNotFoundError("provider 'x' is not configured")
        with patch("pm_core.runtime_state._runtime_dir", return_value=rt), \
             patch("pm_core.cli.pr.state_root", return_value=tmp_path), \
             patch("pm_core.cli.pr.store.load", return_value=data), \
             patch("pm_core.cli.pr.store.locked_update",
                   side_effect=_locked_update_runs(data)), \
             patch("pm_core.signoff.clear_return_awaiting"), \
             patch("pm_core.qa_loop.run_qa_sync", side_effect=_run):
            result = runner.invoke(pr_qa_run_bg, ["pr-001"])
        assert result.exit_code == 1
        status = json.loads((wd / "qa_status.json").read_text())
        assert status["overall"] == ""
        assert "not configured" in status["stopped"]
        assert not (wd / "qa_resume.json").exists()


class TestQaLaunchRecord:
    """S111: a TUI auto-start pass between the review-PASS tick moving a PR
    to qa and its ``pm pr qa-run-bg`` driver writing ``qa_run.json`` (later
    still while another pm command held project.yaml) saw no driver and
    started a second QA loop, whose windows the driver killed as stale."""

    @pytest.fixture
    def records(self, tmp_path, monkeypatch):
        from pm_core import qa_loop
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setattr(qa_loop, "get_pm_session", lambda: "pm-own")
        monkeypatch.setattr(qa_loop, "write_launch_record",
                            _REAL_WRITE_LAUNCH_RECORD)
        return tmp_path / ".pm" / "workdirs" / "qa"

    def test_review_pass_tick_names_the_driver_before_moving_to_qa(
            self, runner, records):
        import json, os
        pr = _pr("in_review")
        data = _data_with(pr)
        seen = []

        def _locked(root, fn, **kw):
            # The PR is not in qa yet, and a record already names this tick.
            recs = [json.loads(p.read_text())
                    for p in records.glob("pr-001-*/qa_run.json")]
            seen.append((pr["status"], recs))
            fn(data)
        with patch("pm_core.cli.pr.state_root", return_value=Path("/tmp/x")), \
             patch("pm_core.cli.pr.store.load", return_value=data), \
             patch("pm_core.cli.pr._get_pm_session", return_value="pm-own"), \
             patch("pm_core.cli.pr._check_review_verdict",
                   return_value=("PASS", 1)), \
             patch("pm_core.cli.pr._check_qa_launch"), \
             patch("pm_core.cli.pr.trigger_tui_refresh"), \
             patch("pm_core.cli.pr.store.locked_update", side_effect=_locked), \
             patch("pm_core.cli.pr._launch_qa_detached") as launch:
            result = runner.invoke(pr_auto_sequence, ["pr-001"])
        assert result.exit_code == 0, result.output
        assert "advanced: qa" in result.output
        (status, recs), = seen
        assert status == "in_review"
        assert [(r["owner_pid"], r["launch"], r["session_tag"])
                for r in recs] == [(os.getpid(), True, "own")]
        assert launch.call_args.kwargs["loop_id"] == recs[0]["loop_id"]
        assert pr["status"] == "qa"

    def test_review_pass_tick_drops_its_record_when_the_move_fails(
            self, runner, records):
        from pm_core import store
        pr = _pr("in_review")
        with patch("pm_core.cli.pr.state_root", return_value=Path("/tmp/x")), \
             patch("pm_core.cli.pr.store.load", return_value=_data_with(pr)), \
             patch("pm_core.cli.pr._get_pm_session", return_value="pm-own"), \
             patch("pm_core.cli.pr._check_review_verdict",
                   return_value=("PASS", 1)), \
             patch("pm_core.cli.pr._check_qa_launch"), \
             patch("pm_core.cli.pr.store.locked_update",
                   side_effect=store.StoreLockTimeout("busy")), \
             patch("pm_core.cli.pr._launch_qa_detached") as launch:
            result = runner.invoke(pr_auto_sequence, ["pr-001"])
        assert isinstance(result.exception, store.StoreLockTimeout)
        launch.assert_not_called()
        assert not list(records.glob("pr-001-*"))

    def test_launch_names_the_spawned_driver(self, records):
        import json, subprocess
        from pm_core.cli import pr as pr_cli
        from pm_core.qa_loop import _proc_start_time, run_driven_elsewhere
        child = subprocess.Popen(["sleep", "30"])
        try:
            with patch.object(pr_cli, "_check_qa_launch"), \
                 patch.object(pr_cli.subprocess, "Popen",
                              return_value=child) as popen:
                pr_cli._launch_qa_detached(Path("/tmp/x"), "pr-001",
                                           loop_id="abc")
            argv = popen.call_args.args[0]
            assert argv[-4:] == ["qa-run-bg", "pr-001", "--loop-id", "abc"]
            rec = json.loads((records / "pr-001-abc" / "qa_run.json")
                             .read_text())
            assert (rec["owner_pid"], rec["owner_start"], rec["launch"]) == (
                child.pid, _proc_start_time(child.pid), True)
            # What a TUI auto-start pass checks before starting its own loop.
            assert run_driven_elsewhere("pr-001")
        finally:
            child.kill()
            child.wait()
        assert not run_driven_elsewhere("pr-001")

    @pytest.mark.parametrize("failing", ["check", "spawn"])
    def test_launch_drops_its_record_when_no_driver_spawns(self, records,
                                                           failing):
        """A record naming the exiting tick would read as a run starting
        (``_qa_run_starting``) until the launch claim expired."""
        import click
        from pm_core.cli import pr as pr_cli
        from pm_core.qa_loop import write_launch_record
        # The review-PASS tick wrote one before moving the PR to qa.
        write_launch_record("pr-001", "abc", 1)
        err = (click.ClickException("bad provider") if failing == "check"
               else OSError("no exec"))
        with patch.object(pr_cli, "_check_qa_launch",
                          side_effect=err if failing == "check" else None), \
             patch.object(pr_cli.subprocess, "Popen",
                          side_effect=err if failing == "spawn" else None):
            with pytest.raises(type(err)):
                pr_cli._launch_qa_detached(Path("/tmp/x"), "pr-001",
                                           loop_id="abc")
        assert not (records / "pr-001-abc").exists()

    def test_driver_record_replaces_the_launch_record_only(self, records):
        import json, os
        from pm_core import qa_loop
        qa_loop.write_launch_record("pr-001", "abc", 1)
        state = qa_loop.QALoopState(pr_id="pr-001", loop_id="abc",
                                    qa_workdir=str(records / "pr-001-abc"),
                                    session_tag="own")
        qa_loop.write_run_record(state)
        path = records / "pr-001-abc" / "qa_run.json"
        rec = json.loads(path.read_text())
        assert rec["owner_pid"] == os.getpid() and "launch" not in rec
        # Kept from then on: a late launch write never replaces it.
        qa_loop.write_launch_record("pr-001", "abc", 1)
        assert json.loads(path.read_text()) == rec


class TestQaRunBgLock:
    """S111: the driver's first project.yaml write waited the plain 2 s lock
    timeout and was not caught, so a `pm edit` held a little longer killed
    it silently before its run started."""

    def test_driver_skips_the_lock_when_the_pr_is_in_qa(self, runner,
                                                       tmp_path):
        pr = _pr("qa")
        with patch("pm_core.cli.pr.state_root", return_value=tmp_path), \
             patch("pm_core.cli.pr.store.load", return_value=_data_with(pr)), \
             patch("pm_core.cli.pr.store.locked_update") as locked, \
             patch("pm_core.qa_loop.run_qa_sync") as run:
            result = runner.invoke(pr_qa_run_bg, ["pr-001", "--loop-id", "abc"])
        assert result.exit_code == 0, result.output
        locked.assert_not_called()
        assert run.call_args.args[0].loop_id == "abc"

    def test_driver_waits_out_a_busy_lock(self, runner, tmp_path):
        from pm_core import store
        from pm_core.signoff import RETURN_CLEAR_WAIT_SECONDS
        pr = _pr("in_review")
        data = _data_with(pr)
        calls = []

        def _locked(root, fn, timeout=store.LOCK_TIMEOUT_SECONDS):
            calls.append(timeout)
            if len(calls) == 1:
                raise store.StoreLockTimeout("busy")
            fn(data)
        with patch("pm_core.cli.pr.state_root", return_value=tmp_path), \
             patch("pm_core.cli.pr.store.load", return_value=data), \
             patch("pm_core.cli.pr.store.locked_update", side_effect=_locked), \
             patch("pm_core.qa_loop.run_qa_sync") as run:
            result = runner.invoke(pr_qa_run_bg, ["pr-001"])
        assert result.exit_code == 0, result.output
        assert calls == [store.LOCK_TIMEOUT_SECONDS, RETURN_CLEAR_WAIT_SECONDS]
        assert pr["status"] == "qa"
        run.assert_called_once()
