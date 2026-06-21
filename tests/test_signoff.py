"""Tests for the sign-off step module (pm_core/signoff.py)."""

from pathlib import Path
from unittest.mock import patch

from pm_core import signoff
from pm_core.signoff import (
    SIGNOFF_MERGE, SIGNOFF_REQA, SIGNOFF_REVIEW, SIGNOFF_IMPL, SIGNOFF_BLOCKED,
    SIGNOFF_VERDICTS, decide_signoff_hop, apply_signoff_hop,
    record_signoff_verdict, fresh_recorded_verdict, latest_signoff_verdict,
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

    def test_merge_always_recommendation(self):
        # Sign-off always gates at merge: SIGNOFF_MERGE -> recommendation only.
        assert decide_signoff_hop(SIGNOFF_MERGE) == "ready_to_merge"

    def test_blocked(self):
        assert decide_signoff_hop(SIGNOFF_BLOCKED) == "blocked"

    def test_bounce_hops(self):
        assert decide_signoff_hop(SIGNOFF_REQA) == "qa"
        assert decide_signoff_hop(SIGNOFF_REVIEW) == "review"
        assert decide_signoff_hop(SIGNOFF_IMPL) == "impl"

    def test_unknown_verdict(self):
        assert decide_signoff_hop(None) == "unknown"
        assert decide_signoff_hop("GARBAGE") == "unknown"

    def test_decision_is_side_effect_free(self):
        """decide must not call into the store at all."""
        with patch("pm_core.signoff.store.locked_update") as lu:
            decide_signoff_hop(SIGNOFF_REQA)
            decide_signoff_hop(SIGNOFF_MERGE)
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

    def test_ready_to_merge_blocked_no_state_change(self):
        """Non-bounce hops never touch the store (sign-off owns no merge)."""
        with patch("pm_core.signoff.store.locked_update") as lu:
            for hop in ("ready_to_merge", "blocked", "unknown"):
                assert apply_signoff_hop(Path("/x"), "pr-001", hop) == hop
        lu.assert_not_called()

    def test_guard_pr_not_in_sign_off(self):
        """If the PR already left sign_off (e.g. concurrent sync), no clobber."""
        data = _data("merged")
        with _patch_locked_update(data):
            hop = apply_signoff_hop(Path("/x"), "pr-001", "qa")
        assert hop == "unknown"
        assert data["prs"][0]["status"] == "merged"

    def test_bounce_consumes_recorded_verdict(self):
        """A bounce must clear pr['signoff'] so it can't be re-adopted forever.

        Re-qa never commits, so the branch HEAD is unchanged on re-entry to
        sign_off; without consuming the record the same fresh verdict would be
        adopted again and loop qa <-> sign_off indefinitely.
        """
        data = _data("sign_off")
        data["prs"][0]["signoff"] = {
            "verdict": SIGNOFF_REQA, "sha": "abc", "origin": "manual"}
        with _patch_locked_update(data):
            assert apply_signoff_hop(Path("/x"), "pr-001", "qa") == "qa"
        assert data["prs"][0]["status"] == "qa"
        assert "signoff" not in data["prs"][0]  # record consumed

    def test_non_bounce_keeps_recorded_verdict(self):
        """ready_to_merge/blocked stay in sign_off, so the record is preserved
        (used for display + idempotent re-reporting; no loop)."""
        data = _data("sign_off")
        data["prs"][0]["signoff"] = {
            "verdict": SIGNOFF_BLOCKED, "sha": "abc", "origin": "manual"}
        with patch("pm_core.signoff.store.locked_update") as lu:
            assert apply_signoff_hop(Path("/x"), "pr-001", "blocked") == "blocked"
        lu.assert_not_called()
        assert data["prs"][0]["signoff"]["verdict"] == SIGNOFF_BLOCKED


class TestVerdictRecordAdoption:
    def test_record_writes_signoff_dict(self):
        data = _data("sign_off")
        with _patch_locked_update(data):
            record_signoff_verdict(
                Path("/x"), "pr-001", SIGNOFF_MERGE, "abc123", "manual")
        rec = data["prs"][0]["signoff"]
        assert rec["verdict"] == SIGNOFF_MERGE
        assert rec["sha"] == "abc123"
        assert rec["origin"] == "manual"
        assert rec["ts"]

    def test_fresh_when_sha_matches(self):
        pr = {"signoff": {"verdict": SIGNOFF_REQA, "sha": "abc"}}
        assert fresh_recorded_verdict(pr, "abc") == SIGNOFF_REQA

    def test_stale_when_sha_differs(self):
        pr = {"signoff": {"verdict": SIGNOFF_REQA, "sha": "abc"}}
        assert fresh_recorded_verdict(pr, "def") is None

    def test_absent_record_or_unknown_sha(self):
        assert fresh_recorded_verdict({}, "abc") is None
        # current sha unknown -> can't establish freshness
        assert fresh_recorded_verdict(
            {"signoff": {"verdict": SIGNOFF_REQA, "sha": "abc"}}, None) is None

    def test_latest_verdict_ignores_staleness(self):
        pr = {"signoff": {"verdict": SIGNOFF_IMPL, "sha": "old"}}
        assert latest_signoff_verdict(pr) == SIGNOFF_IMPL
        assert latest_signoff_verdict({}) is None


class TestVerdictIcons:
    def test_each_verdict_has_distinct_icon(self):
        from pm_core.signoff import SIGNOFF_VERDICT_ICONS
        icons = [SIGNOFF_VERDICT_ICONS[v] for v in SIGNOFF_VERDICTS]
        assert len(set(icons)) == len(SIGNOFF_VERDICTS)  # all distinct
        for v in SIGNOFF_VERDICTS:
            assert v in SIGNOFF_VERDICT_ICONS

    def test_signoff_verdict_icon_helper(self):
        assert signoff.signoff_verdict_icon(SIGNOFF_MERGE) == \
            signoff.SIGNOFF_VERDICT_ICONS[SIGNOFF_MERGE]
        assert signoff.signoff_verdict_icon(None) == ""
        assert signoff.signoff_verdict_icon("GARBAGE") == ""

    def test_tech_tree_reexports_same_maps(self):
        from pm_core.tui import tech_tree
        assert tech_tree.SIGNOFF_VERDICT_ICONS is signoff.SIGNOFF_VERDICT_ICONS
        assert tech_tree.SIGNOFF_VERDICT_STYLES is signoff.SIGNOFF_VERDICT_STYLES


class TestPrListLine:
    def test_sign_off_without_verdict(self):
        from pm_core.cli.helpers import format_pr_line
        line = format_pr_line({"id": "pr-001", "title": "T", "status": "sign_off"})
        assert "[sign_off]" in line

    def test_sign_off_with_verdict_icon(self):
        from pm_core.cli.helpers import format_pr_line
        line = format_pr_line({"id": "pr-001", "title": "T", "status": "sign_off",
                               "signoff": {"verdict": SIGNOFF_IMPL}})
        assert signoff.signoff_verdict_icon(SIGNOFF_IMPL) in line
        assert "[sign_off " in line  # icon appended inside the status bracket

    def test_non_sign_off_unaffected(self):
        from pm_core.cli.helpers import format_pr_line
        line = format_pr_line({"id": "pr-001", "title": "T", "status": "qa"})
        assert "[qa]" in line


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


class TestWindowLaunchWorkdir:
    """The router (Claude) pane must start in the PR workdir.

    Regression for the original QA finding: the router pane was created
    in the wrong cwd (the server's start dir, not the workdir clone), so
    ``git diff {base}...HEAD`` and ``pm qa captures-path`` — both
    cwd-relative — saw the wrong repo. The sign-off window is now a
    single pane, so we assert ``new_window_get_pane`` is called with the
    workdir directly.
    """

    def test_window_creation_uses_workdir_cwd(self, tmp_path):
        from types import SimpleNamespace
        from contextlib import ExitStack
        from unittest.mock import MagicMock

        workdir = tmp_path / "wd"
        workdir.mkdir()
        wdirs = tmp_path / "workdirs"
        wdirs.mkdir()

        data = {"project": {"base_branch": "master", "backend": "local"},
                "prs": []}
        pr_entry = {"id": "pr-001", "title": "T", "status": "sign_off",
                    "branch": "pm/pr-001", "workdir": str(workdir)}

        new_window = MagicMock(return_value="cl_pane")
        with ExitStack() as es:
            p = es.enter_context
            p(patch("pm_core.tmux.has_tmux", return_value=True))
            p(patch("pm_core.tmux.in_tmux", return_value=True))
            p(patch("pm_core.cli.helpers._get_pm_session", return_value="pm-x"))
            p(patch("pm_core.tmux.session_exists", return_value=True))
            p(patch("pm_core.tmux.find_window_by_name", return_value=None))
            p(patch("pm_core.paths.workdirs_base", return_value=wdirs))
            p(patch("pm_core.model_config.resolve_model_and_provider",
                    return_value=SimpleNamespace(model=None, provider=None,
                                                 effort=None)))
            p(patch("pm_core.model_config.get_pr_model_override",
                    return_value=None))
            p(patch("pm_core.prompt_gen.generate_signoff_prompt",
                    return_value="PROMPT"))
            p(patch("pm_core.claude_launcher.build_claude_shell_cmd",
                    return_value="CLAUDE_CMD"))
            p(patch("pm_core.container.is_container_mode_enabled",
                    return_value=False))
            p(patch("pm_core.tmux.new_window_get_pane", new_window))
            p(patch("pm_core.tmux.set_shared_window_size"))
            p(patch("pm_core.tmux.switch_sessions_to_window"))
            p(patch("pm_core.signoff.subprocess.run",
                    return_value=SimpleNamespace(stdout="@9\n")))
            p(patch("pm_core.pane_registry.register_pane"))
            p(patch("pm_core.pane_registry.registry_path", return_value=tmp_path))
            p(patch("pm_core.pane_registry.locked_read_modify_write"))

            signoff.launch_signoff_window(
                data, pr_entry, background=True, transcript=None)

        new_window.assert_called_once()
        # new_window_get_pane(session, name, cmd, workdir, switch=...): workdir is 4th positional arg.
        args = new_window.call_args
        # workdir lands as the 4th positional argument.
        assert args.args[3] == str(workdir)


class TestLatestQaStatusPath:
    """The shared QA-status locator used by both the auto-sequence gate and the
    sign-off prompt (single source of truth for the glob)."""

    def test_none_when_no_qa_dir(self, tmp_path):
        from pm_core import paths
        with patch("pm_core.paths.workdirs_base", return_value=tmp_path):
            assert paths.latest_qa_status_path("pr-001") is None

    def test_picks_newest_mtime(self, tmp_path):
        import os
        from pm_core import paths
        qa = tmp_path / "qa"
        old = qa / "pr-001-aaaa"
        new = qa / "pr-001-bbbb"
        old.mkdir(parents=True)
        new.mkdir(parents=True)
        (old / "qa_status.json").write_text("{}")
        newp = new / "qa_status.json"
        newp.write_text("{}")
        # Make `new` strictly newer than `old`.
        os.utime(old / "qa_status.json", (1000, 1000))
        os.utime(newp, (2000, 2000))
        with patch("pm_core.paths.workdirs_base", return_value=tmp_path):
            assert paths.latest_qa_status_path("pr-001") == newp

    def test_other_pr_ignored(self, tmp_path):
        from pm_core import paths
        qa = tmp_path / "qa"
        (qa / "pr-999-aaaa").mkdir(parents=True)
        (qa / "pr-999-aaaa" / "qa_status.json").write_text("{}")
        with patch("pm_core.paths.workdirs_base", return_value=tmp_path):
            assert paths.latest_qa_status_path("pr-001") is None


class TestPrompt:
    def test_prompt_contains_router_contract_and_verdicts(self):
        from pm_core import prompt_gen
        data = _data("sign_off")
        p = prompt_gen.generate_signoff_prompt(data, "pr-001")
        # all five routing verdicts are documented
        for v in SIGNOFF_VERDICTS:
            assert v in p
        # cross-stage evidence aggregation
        assert "captures-path pr-001" in p
        assert "impl/" in p
        assert "scenarios/" in p
        # audit-trail note instruction
        assert "pm pr note add pr-001" in p
        # per-step acceptance criteria (R7): folded into the routing
        # section — each lifecycle step is named alongside its routing verdict.
        for token in ("Implementation", "Review", "QA"):
            assert token in p
        assert "acceptance criteria" in p
        # merge is always a recommendation now (no autonomy/hardcoded gate)
        assert "never merges" in p.lower()

class TestTuiKeybinding:
    def test_signoff_binding_present_and_shown(self):
        from pm_core.tui.app import ProjectManagerApp
        b = next((x for x in ProjectManagerApp.BINDINGS
                  if getattr(x, "action", None) == "signoff_pr"), None)
        assert b is not None, "no signoff_pr Binding"
        assert b.key == "i"
        assert b.show is True
        assert hasattr(ProjectManagerApp, "action_signoff_pr")

    def test_help_modal_lists_signoff(self):
        from pm_core.tui import screens
        src = Path(screens.__file__).read_text()
        assert "Sign-off" in src

    def test_pr_view_exposes_signoff_pr(self):
        from pm_core.tui import pr_view
        assert callable(getattr(pr_view, "signoff_pr", None))


class TestPromptCaptureLanguage:
    def test_no_capture_gate_language(self):
        """The deterministic capture gate was removed (display moved to #226)."""
        from pm_core import prompt_gen
        data = _data("sign_off")
        data["prs"][0]["plan"] = "bugs"
        p = prompt_gen.generate_signoff_prompt(data, "pr-001")
        assert "CAPTURE GATE FAILED" not in p
        assert "capture gate" not in p.lower()
        # but bug repro/verify evidence is still part of the review
        assert "pre-fix" in p and "post-fix" in p
