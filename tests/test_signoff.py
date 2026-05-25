"""Tests for the sign-off step module (pm_core/signoff.py)."""

from pathlib import Path
from unittest.mock import patch

from pm_core import signoff
from pm_core.signoff import (
    SIGNOFF_MERGE, SIGNOFF_REQA, SIGNOFF_REVIEW, SIGNOFF_IMPL, SIGNOFF_BLOCKED,
    SIGNOFF_VERDICTS, decide_signoff_hop, apply_signoff_hop,
    is_signoff_autonomous, signoff_window_name,
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

    def test_per_plan_override_wins(self):
        # Forward seam for pr-ff9b728: per-plan map overrides project default.
        data = {"project": {
            "sign_off_autonomous": False,
            "plan_sign_off_autonomous": {"bugs": True, "ux": False},
        }}
        assert is_signoff_autonomous(data, {"plan": "bugs"}) is True
        assert is_signoff_autonomous(data, {"plan": "ux"}) is False
        # plan not in the map -> project-level default
        assert is_signoff_autonomous(data, {"plan": "other"}) is False
        # no pr -> project-level default
        assert is_signoff_autonomous(data) is False

    def test_per_plan_falls_back_to_project(self):
        data = {"project": {"sign_off_autonomous": True}}
        assert is_signoff_autonomous(data, {"plan": "bugs"}) is True

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


class TestDecideHop:
    """The DECISION half is pure — never touches the store (no patch needed)."""

    def test_merge_autonomous(self):
        assert decide_signoff_hop(SIGNOFF_MERGE, autonomous=True) == "merge"

    def test_merge_gated(self):
        assert decide_signoff_hop(SIGNOFF_MERGE, autonomous=False) == "held"

    def test_blocked(self):
        assert decide_signoff_hop(SIGNOFF_BLOCKED, autonomous=True) == "blocked"

    def test_bounce_hops(self):
        assert decide_signoff_hop(SIGNOFF_REQA, autonomous=False) == "qa"
        assert decide_signoff_hop(SIGNOFF_REVIEW, autonomous=False) == "review"
        assert decide_signoff_hop(SIGNOFF_IMPL, autonomous=False) == "impl"

    def test_unknown_verdict(self):
        assert decide_signoff_hop(None, autonomous=True) == "unknown"
        assert decide_signoff_hop("GARBAGE", autonomous=True) == "unknown"

    def test_decision_is_side_effect_free(self):
        """decide must not call into the store at all."""
        with patch("pm_core.signoff.store.locked_update") as lu:
            decide_signoff_hop(SIGNOFF_REQA, autonomous=False)
            decide_signoff_hop(SIGNOFF_MERGE, autonomous=True)
        lu.assert_not_called()


class TestApplyHop:
    """The SIDE-EFFECT half — transitions only bounce hops, guarded on sign_off."""

    def test_qa_transition(self):
        data = _data("sign_off")
        with _patch_locked_update(data):
            assert apply_signoff_hop(Path("/x"), "pr-001", "qa") == "qa"
        assert data["prs"][0]["status"] == "qa"

    def test_review_transition(self):
        data = _data("sign_off")
        with _patch_locked_update(data):
            assert apply_signoff_hop(Path("/x"), "pr-001", "review") == "review"
        assert data["prs"][0]["status"] == "in_review"

    def test_impl_transition(self):
        data = _data("sign_off")
        with _patch_locked_update(data):
            assert apply_signoff_hop(Path("/x"), "pr-001", "impl") == "impl"
        assert data["prs"][0]["status"] == "in_progress"

    def test_merge_held_blocked_no_state_change(self):
        """Non-bounce hops never touch the store."""
        with patch("pm_core.signoff.store.locked_update") as lu:
            for hop in ("merge", "held", "blocked", "unknown"):
                assert apply_signoff_hop(Path("/x"), "pr-001", hop) == hop
        lu.assert_not_called()

    def test_guard_pr_not_in_sign_off(self):
        """If the PR already left sign_off (e.g. concurrent sync), no clobber."""
        data = _data("merged")
        with _patch_locked_update(data):
            hop = apply_signoff_hop(Path("/x"), "pr-001", "qa")
        assert hop == "unknown"
        assert data["prs"][0]["status"] == "merged"


class TestBugCaptureGate:
    def test_missing_captures_override_merge_to_impl(self):
        # The gate lives in the pure decision: a missing-capture bug PR's MERGE
        # is downgraded to an impl bounce before any side-effect.
        assert decide_signoff_hop(
            SIGNOFF_MERGE, autonomous=True, bug_captures_ok=False) == "impl"

    def test_present_captures_allow_merge(self):
        assert decide_signoff_hop(
            SIGNOFF_MERGE, autonomous=True, bug_captures_ok=True) == "merge"

    def test_non_bug_pr_not_gated(self):
        assert decide_signoff_hop(
            SIGNOFF_MERGE, autonomous=True, bug_captures_ok=None) == "merge"

    def test_capture_status_reads_impl_dirs(self, tmp_path):
        cap = tmp_path / "captures" / "pr-001"
        (cap / "impl" / "pre-fix").mkdir(parents=True)
        (cap / "impl" / "pre-fix" / "repro.cast").write_text("x")
        # post-fix dir exists but is empty -> counts as missing
        (cap / "impl" / "post-fix").mkdir(parents=True)
        with patch("pm_core.paths.captures_dir", return_value=cap):
            has_pre, has_post = signoff.bug_fix_capture_status("pr-001")
        assert has_pre is True
        assert has_post is False

    def test_capture_status_both_present(self, tmp_path):
        cap = tmp_path / "captures" / "pr-001"
        for sub in ("pre-fix", "post-fix"):
            (cap / "impl" / sub).mkdir(parents=True)
            (cap / "impl" / sub / "cap.txt").write_text("x")
        with patch("pm_core.paths.captures_dir", return_value=cap):
            assert signoff.bug_fix_capture_status("pr-001") == (True, True)


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

    def test_merged_rejected(self, tmp_path):
        pr = {"id": "pr-001", "title": "T", "status": "merged",
              "branch": "pm/pr-001"}
        result, mock_launch, data = self._invoke(tmp_path, pr)
        assert result.exit_code != 0
        assert "already merged" in result.output
        mock_launch.assert_not_called()


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
        # per-step acceptance criteria (R7): each lifecycle step named
        assert "Per-step acceptance criteria" in p
        for token in ("Implementation (impl)", "Review", "QA"):
            assert token in p

    def test_bug_pr_capture_gate_shown_when_missing(self, tmp_path):
        from pm_core import prompt_gen
        data = _data("sign_off")
        data["prs"][0]["plan"] = "bugs"  # mark as bug PR
        with patch("pm_core.signoff.bug_fix_capture_status",
                   return_value=(False, False)):
            p = prompt_gen.generate_signoff_prompt(data, "pr-001")
        assert "Bug-fix capture gate" in p
        assert "CAPTURE GATE FAILED" in p
        assert "**MISSING**" in p

    def test_bug_pr_capture_gate_passes_when_present(self):
        from pm_core import prompt_gen
        data = _data("sign_off")
        data["prs"][0]["plan"] = "bugs"
        with patch("pm_core.signoff.bug_fix_capture_status",
                   return_value=(True, True)):
            p = prompt_gen.generate_signoff_prompt(data, "pr-001")
        assert "Bug-fix capture gate" in p
        assert "CAPTURE GATE FAILED" not in p
