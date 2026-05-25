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
        pr = _pr("sign_off")
        data = _data_with(pr)
        with patch("pm_core.cli.pr.state_root", return_value=tmp_path), \
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

    def test_bounce_retires_window_but_recommendation_does_not(self, runner, tmp_path):
        """A bounce retires the sign-off window; ready_to_merge/blocked don't
        (the PR legitimately stays in sign_off, so its window/verdict persist)."""
        for verdict, hop_echo in (("SIGNOFF_MERGE", "ready_to_merge"),
                                  ("SIGNOFF_BLOCKED", "paused: sign_off_blocked")):
            pr = _pr("sign_off")
            data = _data_with(pr)
            with patch("pm_core.cli.pr.state_root", return_value=tmp_path), \
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
