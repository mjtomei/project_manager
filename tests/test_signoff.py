"""Tests for the sign-off step module (pm_core/signoff.py)."""

from pathlib import Path
from unittest.mock import patch

from pm_core import signoff
from pm_core.signoff import (
    SIGNOFF_MERGE, SIGNOFF_REQA, SIGNOFF_REVIEW, SIGNOFF_IMPL, SIGNOFF_BLOCKED,
    SIGNOFF_VERDICTS, act_on_signoff_verdict, is_signoff_autonomous,
    signoff_window_name,
)


def _data(pr_status: str = "sign_off"):
    return {
        "project": {"base_branch": "master", "backend": "local"},
        "prs": [{"id": "pr-001", "title": "T", "status": pr_status,
                 "branch": "pm/pr-001"}],
    }


def _patch_locked_update(data: dict):
    """Patch store.locked_update so the apply callback runs against *data*."""
    def _side(root, fn):
        fn(data)
        return data
    return patch("pm_core.signoff.store.locked_update", side_effect=_side)


class TestConfigFlag:
    def test_default_gated(self):
        assert is_signoff_autonomous({}) is False
        assert is_signoff_autonomous({"project": {}}) is False

    def test_autonomous_true(self):
        assert is_signoff_autonomous(
            {"project": {"sign_off_autonomous": True}}) is True

    def test_autonomous_false(self):
        assert is_signoff_autonomous(
            {"project": {"sign_off_autonomous": False}}) is False


class TestWindowName:
    def test_local_id(self):
        assert signoff_window_name({"id": "pr-001"}) == "signoff-pr-001"

    def test_github_id(self):
        assert signoff_window_name(
            {"id": "pr-001", "gh_pr_number": 42}) == "signoff-#42"


class TestVerdictVocab:
    def test_all_verdicts_distinct(self):
        assert len(set(SIGNOFF_VERDICTS)) == 5
        for v in (SIGNOFF_MERGE, SIGNOFF_REQA, SIGNOFF_REVIEW,
                  SIGNOFF_IMPL, SIGNOFF_BLOCKED):
            assert v in SIGNOFF_VERDICTS


class TestActOnVerdict:
    def test_merge_autonomous(self):
        assert act_on_signoff_verdict(
            Path("/x"), "pr-001", SIGNOFF_MERGE, autonomous=True) == "merge"

    def test_merge_gated(self):
        assert act_on_signoff_verdict(
            Path("/x"), "pr-001", SIGNOFF_MERGE, autonomous=False) == "held"

    def test_blocked(self):
        assert act_on_signoff_verdict(
            Path("/x"), "pr-001", SIGNOFF_BLOCKED, autonomous=True) == "blocked"

    def test_unknown_verdict(self):
        assert act_on_signoff_verdict(
            Path("/x"), "pr-001", None, autonomous=True) == "unknown"
        assert act_on_signoff_verdict(
            Path("/x"), "pr-001", "GARBAGE", autonomous=True) == "unknown"

    def test_reqa_transitions_to_qa(self):
        data = _data("sign_off")
        with _patch_locked_update(data):
            hop = act_on_signoff_verdict(
                Path("/x"), "pr-001", SIGNOFF_REQA, autonomous=False)
        assert hop == "qa"
        assert data["prs"][0]["status"] == "qa"

    def test_review_transitions_to_in_review(self):
        data = _data("sign_off")
        with _patch_locked_update(data):
            hop = act_on_signoff_verdict(
                Path("/x"), "pr-001", SIGNOFF_REVIEW, autonomous=False)
        assert hop == "review"
        assert data["prs"][0]["status"] == "in_review"

    def test_impl_transitions_to_in_progress(self):
        data = _data("sign_off")
        with _patch_locked_update(data):
            hop = act_on_signoff_verdict(
                Path("/x"), "pr-001", SIGNOFF_IMPL, autonomous=False)
        assert hop == "impl"
        assert data["prs"][0]["status"] == "in_progress"

    def test_guard_pr_not_in_sign_off(self):
        """If the PR already left sign_off (e.g. concurrent sync), no clobber."""
        data = _data("merged")
        with _patch_locked_update(data):
            hop = act_on_signoff_verdict(
                Path("/x"), "pr-001", SIGNOFF_REQA, autonomous=False)
        assert hop == "unknown"
        assert data["prs"][0]["status"] == "merged"


class TestSignoffCommand:
    def _invoke(self, tmp_path, pr):
        from click.testing import CliRunner
        from pm_core.cli.pr import pr_signoff
        data = {"project": {"active_pr": pr["id"], "base_branch": "master",
                            "backend": "local"}, "prs": [pr]}
        with patch("pm_core.cli.pr.state_root", return_value=tmp_path), \
             patch("pm_core.cli.pr.store.load", return_value=data), \
             patch("pm_core.cli.pr.store.locked_update",
                   side_effect=_patch_locked_update_fn(data)), \
             patch("pm_core.cli.pr.trigger_tui_refresh"), \
             patch("pm_core.signoff.launch_signoff_window") as mock_launch:
            result = CliRunner().invoke(pr_signoff, [pr["id"]])
        return result, mock_launch, data

    def test_wrong_status_rejected(self, tmp_path):
        pr = {"id": "pr-001", "title": "T", "status": "in_progress",
              "branch": "pm/pr-001"}
        result, mock_launch, _ = self._invoke(tmp_path, pr)
        assert result.exit_code != 0
        assert "sign-off runs after QA" in result.output
        mock_launch.assert_not_called()

    def test_qa_transitions_to_sign_off_and_launches(self, tmp_path):
        pr = {"id": "pr-001", "title": "T", "status": "qa",
              "branch": "pm/pr-001"}
        result, mock_launch, data = self._invoke(tmp_path, pr)
        assert result.exit_code == 0, result.output
        assert data["prs"][0]["status"] == "sign_off"
        mock_launch.assert_called_once()

    def test_already_sign_off_just_launches(self, tmp_path):
        pr = {"id": "pr-001", "title": "T", "status": "sign_off",
              "branch": "pm/pr-001"}
        result, mock_launch, data = self._invoke(tmp_path, pr)
        assert result.exit_code == 0, result.output
        assert data["prs"][0]["status"] == "sign_off"
        mock_launch.assert_called_once()


def _patch_locked_update_fn(data: dict):
    def _side(root, fn):
        fn(data)
        return data
    return _side


class TestPrompt:
    def test_prompt_contains_router_contract_and_verdicts(self):
        from pm_core import prompt_gen
        data = _data("sign_off")
        p = prompt_gen.generate_signoff_prompt(data, "pr-001")
        # router-only contract
        assert "router only" in p.lower()
        assert "NEVER edit code" in p or "never edit code" in p.lower()
        # all five routing verdicts are documented
        for v in SIGNOFF_VERDICTS:
            assert v in p
        # cross-stage evidence aggregation
        assert "captures-path pr-001" in p
        assert "impl/" in p
        assert "scenarios/" in p
        # audit-trail note instruction
        assert "pm pr note add pr-001" in p
