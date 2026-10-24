"""Tests for pm_core.model_config — per-session model targeting."""

import pytest
from unittest.mock import patch

from pm_core.model_config import (
    resolve_model,
    resolve_model_and_provider,
    ModelResolution,
    get_model_config_summary,
    get_pr_model_override,
    SESSION_TYPES,
)


class TestPassthrough:
    def test_bare_names_passed_through(self):
        """Bare model names like sonnet, opus are passed through as-is."""
        with patch.dict("os.environ", {"PM_MODEL": "sonnet"}):
            assert resolve_model("review") == "sonnet"
        with patch.dict("os.environ", {"PM_MODEL": "opus"}):
            assert resolve_model("review") == "opus"

    def test_full_model_id_passed_through(self):
        """Full model IDs are passed through as-is."""
        with patch.dict("os.environ", {"PM_MODEL": "claude-custom-model"}):
            result = resolve_model("review")
            assert result == "claude-custom-model"


class TestResolveModel:
    def test_defaults_are_none(self):
        """With no config, all session types return None (use CLI default)."""
        assert resolve_model("review") is None
        assert resolve_model("impl") is None
        assert resolve_model("qa") is None
        assert resolve_model("watcher") is None
        assert resolve_model("merge") is None

    def test_pr_override(self):
        assert resolve_model("impl", pr_model="opus") == "opus"

    def test_project_config(self):
        data = {"project": {"model_config": {"session_models": {"review": "sonnet"}}}}
        assert resolve_model("review", project_data=data) == "sonnet"

    def test_pr_beats_project(self):
        data = {"project": {"model_config": {"session_models": {"review": "haiku"}}}}
        assert resolve_model("review", pr_model="sonnet", project_data=data) == "sonnet"

    @patch("pm_core.model_config.get_global_setting_value", return_value="opus")
    def test_global_setting(self, mock_gsv):
        result = resolve_model("qa")
        assert result == "opus"

    @patch("pm_core.model_config.get_global_setting_value", return_value="opus")
    def test_project_beats_global(self, mock_gsv):
        data = {"project": {"model_config": {"session_models": {"qa": "haiku"}}}}
        assert resolve_model("qa", project_data=data) == "haiku"

    def test_unknown_session_type(self):
        assert resolve_model("unknown-type") is None

    def test_signoff_falls_back_to_review(self):
        # signoff inherits review's model when only review is configured.
        data = {"project": {"model_config": {"session_models": {"review": "sonnet"}}}}
        assert resolve_model("signoff", project_data=data) == "sonnet"

    def test_signoff_explicit_overrides_fallback(self):
        data = {"project": {"model_config": {
            "session_models": {"review": "sonnet", "signoff": "opus"}}}}
        assert resolve_model("signoff", project_data=data) == "opus"


class TestEffortResolution:
    def test_defaults_are_none(self):
        """With no config, effort is None (use CLI default)."""
        result = resolve_model_and_provider("review")
        assert result.effort is None
        result = resolve_model_and_provider("qa")
        assert result.effort is None
        result = resolve_model_and_provider("impl")
        assert result.effort is None

    def test_watcher_no_effort_by_default(self):
        """Watcher has no default effort."""
        result = resolve_model_and_provider("watcher")
        assert result.effort is None

    def test_haiku_suppresses_effort(self):
        """Even if effort is configured, it's suppressed for haiku."""
        with patch.dict("os.environ", {"PM_MODEL": "haiku", "PM_EFFORT": "high"}):
            result = resolve_model_and_provider("watcher")
            assert result.effort is None

    def test_haiku_explicit_suppresses_effort(self):
        """Setting model to haiku via env var suppresses effort."""
        with patch.dict("os.environ", {"PM_MODEL": "haiku", "PM_EFFORT": "high"}):
            result = resolve_model_and_provider("qa")
            assert result.effort is None

    def test_sonnet_keeps_effort(self):
        """Sonnet supports effort levels."""
        with patch.dict("os.environ", {"PM_MODEL": "sonnet", "PM_EFFORT": "low"}):
            result = resolve_model_and_provider("qa")
            assert result.effort == "low"

    def test_opus_keeps_effort(self):
        """Opus supports effort levels."""
        with patch.dict("os.environ", {"PM_EFFORT": "medium"}):
            result = resolve_model_and_provider("review")
            assert result.effort == "medium"

    def test_project_effort_config(self):
        data = {"project": {"model_config": {"session_effort": {"qa": "low"}}}}
        result = resolve_model_and_provider("qa", project_data=data)
        assert result.effort == "low"

    @patch("pm_core.model_config.get_global_setting_value")
    def test_global_effort_setting(self, mock_gsv):
        mock_gsv.side_effect = lambda key: "low" if key == "effort-qa" else ""
        result = resolve_model_and_provider("qa")
        assert result.effort == "low"


class TestEnvVarOverrides:
    def test_pm_model_env_var(self):
        with patch.dict("os.environ", {"PM_MODEL": "haiku"}):
            result = resolve_model("qa")
            assert result == "haiku"

    def test_pm_model_with_shortcut(self):
        with patch.dict("os.environ", {"PM_MODEL": "sonnet"}):
            result = resolve_model("review")
            assert result == "sonnet"

    def test_pm_model_beats_project(self):
        data = {"project": {"model_config": {"session_models": {"qa": "opus"}}}}
        with patch.dict("os.environ", {"PM_MODEL": "haiku"}):
            result = resolve_model("qa", project_data=data)
            assert result == "haiku"

    def test_pm_effort_env_var(self):
        with patch.dict("os.environ", {"PM_EFFORT": "low"}):
            result = resolve_model_and_provider("review")
            assert result.effort == "low"

    def test_pm_effort_beats_project(self):
        data = {"project": {"model_config": {"session_effort": {"qa": "low"}}}}
        with patch.dict("os.environ", {"PM_EFFORT": "high"}):
            result = resolve_model_and_provider("qa", project_data=data)
            assert result.effort == "high"

    def test_pm_model_provider_prefix(self):
        with patch.dict("os.environ", {"PM_MODEL": "provider:ollama"}):
            result = resolve_model_and_provider("qa")
            assert result.provider == "ollama"
            assert result.model is None


class TestGetModelConfigSummary:
    def test_no_config_shows_default(self):
        summary = get_model_config_summary()
        assert summary["review"] == "(default)"
        assert summary["watcher"] == "(default)"
        assert len(summary) == len(SESSION_TYPES)


class TestGetPrModelOverride:
    def test_present(self):
        assert get_pr_model_override({"model": "opus"}) == "opus"

    def test_absent(self):
        assert get_pr_model_override({}) is None

    def test_signoff_exception_keeps_other_roles_on_pr_model(self, monkeypatch):
        monkeypatch.delenv("PM_MODEL", raising=False)
        pr = {"model": "provider:deepseek-flash",
              "session_models": {"signoff": "provider:claude-work"}}
        for role in SESSION_TYPES:
            res = resolve_model_and_provider(
                role, pr_model=get_pr_model_override(pr, role))
            expected = "claude-work" if role == "signoff" else "deepseek-flash"
            assert res.provider == expected
        monkeypatch.setenv("PM_MODEL", "provider:environment")
        assert resolve_model_and_provider(
            "signoff", pr_model=get_pr_model_override(pr, "signoff")
        ).provider == "environment"

    def test_pr_role_inheritance_and_specific_precedence(self):
        pr = {"model": "opus", "session_models": {
            "review": "provider:claude-work", "qa": "sonnet",
            "qa_scenario": "provider:glm-flash"}}
        assert get_pr_model_override(pr, "signoff") == "provider:claude-work"
        assert get_pr_model_override(pr, "qa_planning") == "sonnet"
        assert get_pr_model_override(pr, "qa_scenario") == "provider:glm-flash"
        assert get_pr_model_override(pr, "impl") == "opus"

    def test_malformed_session_models_fall_back_to_the_pr_model(self):
        """A non-mapping value (hand-edited YAML) is ignored, never
        indexed: a string would otherwise match a role by substring."""
        for bad in ("provider:qa-route", ["qa"], 3):
            pr = {"model": "opus", "session_models": bad}
            assert get_pr_model_override(pr, "qa") == "opus"

    def test_blank_or_non_string_role_entries_count_as_absent(self,
                                                              monkeypatch):
        """``signoff:`` left blank must not drop the PR model (silently
        moving sign-off to the project default), and a non-string entry
        must not raise at every launch of the role."""
        monkeypatch.delenv("PM_MODEL", raising=False)
        for bad in (None, "", "  ", 5, {"model": "x"}):
            pr = {"model": "provider:deepseek-flash",
                  "session_models": {"signoff": bad}}
            assert get_pr_model_override(pr, "signoff") == \
                "provider:deepseek-flash"
            res = resolve_model_and_provider(
                "signoff", pr_model=get_pr_model_override(pr, "signoff"))
            assert res.provider == "deepseek-flash"
            # The parent role's entry still applies over the PR model.
            pr["session_models"]["review"] = "provider:claude-work"
            assert get_pr_model_override(pr, "signoff") == \
                "provider:claude-work"

    def test_qa_roles_resolve_their_pr_exception(self, monkeypatch):
        """QA launches resolve through qa_loop._resolve_qa_model.  A worker
        exception reaches only the worker: s0 (qa_interactive) and the
        planner keep the PR-wide model, and the refiner inherits ``qa``."""
        from pm_core import qa_loop
        monkeypatch.delenv("PM_MODEL", raising=False)
        pr = {"model": "opus", "session_models": {
            "qa_scenario": "provider:claude-work", "qa": "sonnet"}}
        got = {st: qa_loop._resolve_qa_model(pr, {}, session_type=st)
               for st in ("qa_scenario", "qa_concretize", "qa_planning")}
        assert got["qa_scenario"].provider == "claude-work"
        assert got["qa_concretize"].model == "sonnet"
        assert got["qa_planning"].model == "sonnet"
        s0 = qa_loop._resolve_interactive_model(pr, {})
        assert (s0.model, s0.provider) == ("sonnet", None)

    def test_plain_worker_exception_does_not_move_s0(self, monkeypatch):
        """The s0 legacy fallback (a plain-model ``qa_scenario`` from before
        ``qa_interactive``) is for project config: a PR's worker exception
        to a plain model leaves s0 on the project/default model."""
        from pm_core import qa_loop
        monkeypatch.delenv("PM_MODEL", raising=False)
        monkeypatch.setattr("pm_core.model_config.get_global_setting_value",
                            lambda *a, **k: "")
        pr = {"session_models": {"qa_scenario": "haiku"}}
        assert qa_loop._resolve_qa_model(
            pr, {}, session_type="qa_scenario").model == "haiku"
        s0 = qa_loop._resolve_interactive_model(pr, {})
        assert (s0.model, s0.provider) == (None, None)
        legacy = {"project": {"model_config": {
            "session_models": {"qa_scenario": "sonnet"}}}}
        assert qa_loop._resolve_interactive_model(pr, legacy).model == "sonnet"

    def test_merge_window_resolves_its_pr_exception(self, tmp_path,
                                                    monkeypatch):
        from types import SimpleNamespace
        from pm_core.cli import pr as pr_mod
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
        seen = []
        monkeypatch.setattr(
            "pm_core.model_config.resolve_model_and_provider",
            lambda st, **k: seen.append((st, k["pr_model"])) or
            SimpleNamespace(model=None, provider="claude-work", effort=None))
        pr = {"id": "pr-001", "model": "provider:deepseek-flash",
              "session_models": {"merge": "provider:claude-work"}}
        with patch.object(pr_mod, "tmux_mod") as tm, \
             patch.object(pr_mod, "prompt_gen"), \
             patch.object(pr_mod, "build_claude_shell_cmd",
                          return_value="claude") as build, \
             patch.object(pr_mod, "_get_pm_session", return_value="pm-s"), \
             patch("pm_core.paths.get_global_setting", return_value=False):
            tm.find_window_by_name.return_value = None
            pr_mod._launch_merge_window({"project": {}}, pr, "conflict",
                                         cwd=str(tmp_path))
        assert seen == [("merge", "provider:claude-work")]
        assert build.call_args.kwargs["provider"] == "claude-work"


class TestBuildClaudeShellCmd:
    def test_model_flag_included(self):
        from pm_core.claude_launcher import build_claude_shell_cmd
        cmd = build_claude_shell_cmd(prompt="test", model="sonnet")
        assert "--model" in cmd
        assert "sonnet" in cmd

    def test_no_model_flag_when_none(self):
        from pm_core.claude_launcher import build_claude_shell_cmd
        cmd = build_claude_shell_cmd(prompt="test")
        assert "--model" not in cmd

    def test_effort_flag_included(self):
        from pm_core.claude_launcher import build_claude_shell_cmd
        cmd = build_claude_shell_cmd(prompt="test", effort="low")
        assert "--effort low" in cmd

    def test_no_effort_flag_when_none(self):
        from pm_core.claude_launcher import build_claude_shell_cmd
        cmd = build_claude_shell_cmd(prompt="test")
        assert "--effort" not in cmd

    def test_model_and_effort_together(self):
        from pm_core.claude_launcher import build_claude_shell_cmd
        cmd = build_claude_shell_cmd(prompt="test", model="sonnet", effort="medium")
        assert "--model" in cmd
        assert "--effort medium" in cmd


class TestProviderResolution:
    def test_provider_prefix_via_env(self):
        with patch.dict("os.environ", {"PM_MODEL": "provider:ollama"}):
            result = resolve_model_and_provider("watcher")
            assert result.provider == "ollama"
            assert result.model is None

    def test_non_provider_returns_model(self):
        """With explicit config, non-provider values resolve to model string."""
        result = resolve_model_and_provider("review", pr_model="opus")
        assert result.model == "opus"
        assert result.provider is None

    def test_provider_in_project_config(self):
        data = {"project": {"model_config": {"session_models": {"watcher": "provider:ollama"}}}}
        result = resolve_model_and_provider("watcher", project_data=data)
        assert result.provider == "ollama"
        assert result.model is None

    def test_resolve_model_ignores_provider(self):
        with patch.dict("os.environ", {"PM_MODEL": "provider:ollama"}):
            assert resolve_model("watcher") is None

    def test_summary_shows_provider(self):
        data = {"project": {"model_config": {"session_models": {"watcher": "provider:ollama"}}}}
        summary = get_model_config_summary(data)
        assert summary["watcher"] == "provider:ollama"
        assert summary["review"] == "(default)"

    @patch("pm_core.model_config.get_global_setting_value", return_value="provider:vllm")
    def test_global_setting_provider(self, mock_gsv):
        result = resolve_model_and_provider("qa")
        assert result.provider == "vllm"
        assert result.model is None


class TestQaSubtypeFallback:
    def test_qa_planning_falls_back_to_qa(self):
        data = {"project": {"model_config": {"session_models": {"qa": "sonnet"}}}}
        result = resolve_model("qa_planning", project_data=data)
        assert result == "sonnet"

    def test_qa_scenario_falls_back_to_qa(self):
        data = {"project": {"model_config": {"session_models": {"qa": "haiku"}}}}
        result = resolve_model("qa_scenario", project_data=data)
        assert result == "haiku"

    def test_specific_beats_fallback(self):
        data = {"project": {"model_config": {"session_models": {
            "qa": "haiku",
            "qa_planning": "opus",
        }}}}
        assert resolve_model("qa_planning", project_data=data) == "opus"
        assert resolve_model("qa_scenario", project_data=data) == "haiku"

    def test_effort_fallback(self):
        data = {"project": {"model_config": {"session_effort": {"qa": "low"}}}}
        result = resolve_model_and_provider("qa_planning", project_data=data)
        assert result.effort == "low"

    def test_effort_specific_beats_fallback(self):
        data = {"project": {"model_config": {"session_effort": {
            "qa": "low",
            "qa_planning": "high",
        }}}}
        result = resolve_model_and_provider("qa_planning", project_data=data)
        assert result.effort == "high"
        result = resolve_model_and_provider("qa_scenario", project_data=data)
        assert result.effort == "low"

    def test_qa_concretize_falls_back_to_qa(self):
        data = {"project": {"model_config": {"session_models": {"qa": "sonnet"}}}}
        assert resolve_model("qa_concretize", project_data=data) == "sonnet"

    def test_qa_finalize_falls_back_to_qa(self):
        data = {"project": {"model_config": {"session_models": {"qa": "haiku"}}}}
        assert resolve_model("qa_finalize", project_data=data) == "haiku"

    def test_qa_concretize_and_finalize_independently_targetable(self):
        data = {"project": {"model_config": {"session_models": {
            "qa": "haiku",
            "qa_concretize": "opus",
            "qa_finalize": "sonnet",
        }}}}
        assert resolve_model("qa_concretize", project_data=data) == "opus"
        assert resolve_model("qa_finalize", project_data=data) == "sonnet"
        assert resolve_model("qa_scenario", project_data=data) == "haiku"


class TestSessionTypes:
    def test_new_qa_substeps_registered(self):
        assert "qa_concretize" in SESSION_TYPES
        assert "qa_finalize" in SESSION_TYPES


class TestValidateModelConfig:
    def test_valid_config_returns_no_errors(self):
        from pm_core.model_config import validate_model_config
        data = {"project": {"model_config": {
            "session_models": {"review": "opus", "qa_finalize": "sonnet"},
            "session_effort": {"review": "high"},
        }}}
        assert validate_model_config(data) == []

    def test_none_and_empty_are_valid(self):
        from pm_core.model_config import validate_model_config
        assert validate_model_config(None) == []
        assert validate_model_config({}) == []

    def test_unknown_session_type_in_models_flagged(self):
        from pm_core.model_config import validate_model_config
        data = {"project": {"model_config": {
            "session_models": {"qa_scenrio": "opus"},  # typo
        }}}
        errors = validate_model_config(data)
        assert errors and "qa_scenrio" in errors[0]

    def test_unknown_session_type_in_effort_flagged(self):
        from pm_core.model_config import validate_model_config
        data = {"project": {"model_config": {
            "session_effort": {"bogus": "high"},
        }}}
        errors = validate_model_config(data)
        assert any("bogus" in e for e in errors)

    def test_invalid_effort_level_flagged(self):
        from pm_core.model_config import validate_model_config
        data = {"project": {"model_config": {
            "session_effort": {"review": "extreme"},
        }}}
        errors = validate_model_config(data)
        assert any("extreme" in e for e in errors)

    def test_pr_session_models_problems_flagged(self):
        """A typo'd PR role would leave that role on the PR-wide model."""
        from pm_core.model_config import validate_model_config
        data = {"prs": [
            {"id": "pr-a", "model": "opus",
             "session_models": {"sign_off": "provider:claude-work"}},
            {"id": "pr-b", "session_models": "provider:claude-work"},
            {"id": "pr-c", "session_models": {"signoff": "sonnet"}},
            {"id": "pr-d", "model": "opus"},
        ]}
        errors = validate_model_config(data)
        assert len(errors) == 2
        assert "prs[pr-a].session_models" in errors[0] and "sign_off" in errors[0]
        assert errors[1] == "prs[pr-b].session_models must be a mapping"

    def test_pr_session_models_bad_values_flagged(self):
        """Blank or non-string role entries are ignored, so say so."""
        from pm_core.model_config import validate_model_config
        data = {"prs": [{"id": "pr-a", "session_models": {
            "signoff": None, "review": 5, "impl": "sonnet"}}]}
        errors = validate_model_config(data)
        assert len(errors) == 2
        assert errors[0].startswith("prs[pr-a].session_models['signoff']")
        assert "None is not a model name" in errors[0]
        assert errors[1].startswith("prs[pr-a].session_models['review']")

    def test_non_mapping_model_config_still_checks_prs(self):
        from pm_core.model_config import validate_model_config
        data = {"project": {"model_config": "opus"},
                "prs": [{"id": "pr-a", "session_models": {"bogus": "x"}}]}
        errors = validate_model_config(data)
        assert errors[0] == "model_config must be a mapping"
        assert any("prs[pr-a]" in e and "bogus" in e for e in errors)


def test_model_show_lists_pr_overrides_and_their_problems(tmp_path,
                                                          monkeypatch):
    from click.testing import CliRunner
    from pm_core import store
    from pm_core.cli import model as model_cli
    monkeypatch.delenv("PM_MODEL", raising=False)
    store.save({"project": {"name": "t", "repo": str(tmp_path),
                            "base_branch": "master"},
                "prs": [{"id": "pr-a", "model": "provider:deepseek-flash",
                         "session_models": {"signoff": "provider:claude-work",
                                            "sign_off": "opus"}},
                        {"id": "pr-b", "title": "no override"}]}, tmp_path)
    monkeypatch.setattr(model_cli, "state_root", lambda: tmp_path)
    out = CliRunner().invoke(model_cli.model, ["show"]).output
    assert "pr-a  model  -> provider:deepseek-flash" in out
    assert "pr-a  signoff model  -> provider:claude-work" in out
    assert "pr-b" not in out
    assert "Problems in project.yaml model settings" in out
    assert "prs[pr-a].session_models: unknown session type 'sign_off'" in out
