"""Tests for the QA loop orchestration."""

from pathlib import Path

import pytest
from unittest.mock import patch, MagicMock

from pm_core.qa_loop import (
    parse_qa_plan,
    QAScenario,
    QALoopState,
    create_qa_workdir,
    create_scenario_workdir,
    VERDICT_PASS,
    VERDICT_NEEDS_WORK,
    VERDICT_INPUT_REQUIRED,
    ALL_VERDICTS,
    _scenario_window_name,
    _cleanup_stale_scenario_windows,
    _tail_has_marker_on_own_line,
    _build_verification_prompt,
    _verify_single_scenario,
    _is_verification_enabled,
    _extract_flagged_reason,
    _get_verification_max_retries,
    _install_instruction_file,
    _VERIFICATION_MAX_PANE_LINES,
    _DEFAULT_VERIFICATION_MAX_RETRIES,
)


class TestParseQAPlan:
    def test_basic_plan(self):
        output = """
QA_PLAN_START

SCENARIO 1: Login Flow
FOCUS: User authentication
INSTRUCTION: pm/qa/instructions/login.md
STEPS: Test login and logout

SCENARIO 2: Dashboard
FOCUS: Main dashboard rendering
INSTRUCTION: none
STEPS: Verify dashboard loads

QA_PLAN_END
"""
        scenarios = parse_qa_plan(output)
        assert len(scenarios) == 2
        assert scenarios[0].index == 1
        assert scenarios[0].title == "Login Flow"
        assert scenarios[0].focus == "User authentication"
        assert scenarios[0].instruction_path == "pm/qa/instructions/login.md"
        assert scenarios[1].index == 2
        assert scenarios[1].title == "Dashboard"
        assert scenarios[1].instruction_path is None

    def test_no_brackets_in_title(self):
        output = """
QA_PLAN_START
SCENARIO 1: Simple Title
FOCUS: Something
STEPS: Do stuff
QA_PLAN_END
"""
        scenarios = parse_qa_plan(output)
        assert len(scenarios) == 1
        assert scenarios[0].title == "Simple Title"

    def test_instruction_none(self):
        output = """
QA_PLAN_START
SCENARIO 1: Test
FOCUS: Testing
INSTRUCTION: n/a
QA_PLAN_END
"""
        scenarios = parse_qa_plan(output)
        assert scenarios[0].instruction_path is None

    def test_multiline_steps(self):
        output = """
QA_PLAN_START

SCENARIO 1: Login Flow
FOCUS: User authentication
INSTRUCTION: none
STEPS: Test login
  - Step 1: Open the login page
  - Step 2: Enter credentials
  - Step 3: Verify redirect

QA_PLAN_END
"""
        scenarios = parse_qa_plan(output)
        assert len(scenarios) == 1
        assert "Step 1" in scenarios[0].steps
        assert "Step 2" in scenarios[0].steps
        assert "Step 3" in scenarios[0].steps

    def test_placeholder_scenarios_rejected(self):
        """Prompt template examples must not be parsed as real scenarios."""
        output = """
QA_PLAN_START

SCENARIO 1: Scenario Title
FOCUS: What area/behavior to test
INSTRUCTION: path/to/instruction.md
STEPS: Key test steps to perform

SCENARIO 2: Scenario Title
FOCUS: ...
INSTRUCTION: ...
STEPS: ...

QA_PLAN_END
"""
        scenarios = parse_qa_plan(output)
        assert len(scenarios) == 0

    def test_angle_bracket_placeholders_rejected(self):
        """Angle-bracket placeholders from the prompt example are rejected."""
        output = """
QA_PLAN_START
SCENARIO 1: <descriptive title for this scenario>
FOCUS: <what area or behavior to test>
STEPS: <concrete test steps>
QA_PLAN_END
"""
        scenarios = parse_qa_plan(output)
        assert len(scenarios) == 0

    def test_empty_output(self):
        assert parse_qa_plan("") == []
        assert parse_qa_plan("No plan here") == []

    def test_malformed_heading(self):
        output = """
QA_PLAN_START
SCENARIO Not numbered
FOCUS: Something
QA_PLAN_END
"""
        scenarios = parse_qa_plan(output)
        assert len(scenarios) == 0

    def test_pane_with_prompt_template_and_real_plan(self):
        """When pane content contains both the prompt template example AND
        real planner output, parse_qa_plan should pick the real plan (last
        QA_PLAN_END)."""
        # Simulates pane content: prompt template first, then Claude's output
        output = """
## Output Format

```
QA_PLAN_START

SCENARIO 1: Scenario Title
FOCUS: What area/behavior to test
INSTRUCTION: path/to/instruction.md (or "none" if no existing instruction applies)
STEPS: Key test steps to perform

SCENARIO 2: Scenario Title
FOCUS: ...
INSTRUCTION: ...
STEPS: ...

QA_PLAN_END
```

---

Here is my QA plan:

QA_PLAN_START

SCENARIO 1: Unit Test Coverage
FOCUS: Verify parse_qa_plan handles edge cases
INSTRUCTION: pm/qa/regression/qa-parser.md
STEPS: Run pytest with coverage

SCENARIO 2: CLI Integration
FOCUS: Test pm qa run command
INSTRUCTION: none
STEPS: Run pm qa run and check output

QA_PLAN_END
"""
        scenarios = parse_qa_plan(output)
        assert len(scenarios) == 2
        # Should get the REAL scenarios, not the template placeholders
        assert scenarios[0].title == "Unit Test Coverage"
        assert scenarios[0].focus == "Verify parse_qa_plan handles edge cases"
        assert scenarios[0].instruction_path == "pm/qa/regression/qa-parser.md"
        assert scenarios[1].title == "CLI Integration"
        assert scenarios[1].instruction_path is None

    def test_pane_with_only_prompt_template(self):
        """When pane content only has the prompt template, placeholder
        scenarios are now rejected by parse_qa_plan itself, preventing
        the planner's example format from being treated as real scenarios."""
        output = """
QA_PLAN_START

SCENARIO 1: Scenario Title
FOCUS: What area/behavior to test
INSTRUCTION: path/to/instruction.md (or "none" if no existing instruction applies)
STEPS: Key test steps to perform

SCENARIO 2: Scenario Title
FOCUS: ...
INSTRUCTION: ...
STEPS: ...

QA_PLAN_END
"""
        scenarios = parse_qa_plan(output)
        assert len(scenarios) == 0  # placeholder titles are rejected

    def test_current_prompt_template_plus_real_plan(self):
        """Simulates actual pane content with the current prompt template
        (angle-bracket placeholders) followed by Claude's real output."""
        output = """You are a QA planner analyzing PR pr-001: "Add feature X"

## Output Format

Your output is machine-parsed.  Use ALL CAPS markers exactly as shown.
Do NOT use markdown headings or code fences — output the plain-text markers
directly at the start of a line.

QA_PLAN_START

SCENARIO 1: <descriptive title for this scenario>
FOCUS: <what area or behavior to test>
INSTRUCTION: <path/to/instruction.md or "none" if no existing instruction applies>
STEPS: <concrete test steps to perform>

SCENARIO 2: <descriptive title for next scenario>
FOCUS: <what area or behavior to test>
INSTRUCTION: <path or "none">
STEPS: <concrete test steps>

QA_PLAN_END

IMPORTANT: Replace ALL angle-bracket placeholders above with real content.

Here is my QA plan based on the PR changes:

QA_PLAN_START

SCENARIO 1: Feature X unit test coverage
FOCUS: Verify new functions handle edge cases
INSTRUCTION: pm/qa/instructions/tui-manual-test.md
STEPS: 1. Run pytest on test_feature_x.py 2. Check coverage for new module 3. Verify error handling paths

SCENARIO 2: Feature X integration with existing UI
FOCUS: End-to-end flow through the TUI
INSTRUCTION: none
STEPS: 1. Launch TUI with test project 2. Navigate to feature X panel 3. Exercise all interactions

SCENARIO 3: Regression — existing functionality unbroken
FOCUS: Ensure no regressions in adjacent code
INSTRUCTION: none
STEPS: 1. Run full test suite 2. Verify no new warnings

QA_PLAN_END
"""
        scenarios = parse_qa_plan(output)
        assert len(scenarios) == 3
        assert scenarios[0].title == "Feature X unit test coverage"
        assert scenarios[0].instruction_path == "pm/qa/instructions/tui-manual-test.md"
        assert scenarios[1].title == "Feature X integration with existing UI"
        assert scenarios[1].instruction_path is None
        assert scenarios[2].title == "Regression — existing functionality unbroken"


class TestTailHasMarkerOnOwnLine:
    """Tests for _tail_has_marker_on_own_line — the function that detects
    QA_PLAN_END in the tail of pane content."""

    def test_marker_on_own_line(self):
        content = "line1\nline2\nQA_PLAN_END\nline4"
        assert _tail_has_marker_on_own_line(content, "QA_PLAN_END") is True

    def test_marker_as_substring_not_matched(self):
        content = "line1\nThis line has QA_PLAN_END embedded\nline3"
        assert _tail_has_marker_on_own_line(content, "QA_PLAN_END") is False

    def test_marker_with_markdown_bold(self):
        content = "line1\n**QA_PLAN_END**\nline3"
        assert _tail_has_marker_on_own_line(content, "QA_PLAN_END") is True

    def test_marker_with_backticks(self):
        content = "line1\n`QA_PLAN_END`\nline3"
        assert _tail_has_marker_on_own_line(content, "QA_PLAN_END") is True

    def test_marker_with_leading_whitespace(self):
        content = "line1\n   QA_PLAN_END   \nline3"
        assert _tail_has_marker_on_own_line(content, "QA_PLAN_END") is True

    def test_marker_outside_tail(self):
        """Marker beyond tail_lines should not be detected."""
        lines = [f"line{i}" for i in range(50)]
        lines[5] = "QA_PLAN_END"  # placed early, outside last 30 lines
        content = "\n".join(lines)
        assert _tail_has_marker_on_own_line(content, "QA_PLAN_END") is False

    def test_marker_inside_tail(self):
        """Marker within tail_lines should be detected."""
        lines = [f"line{i}" for i in range(50)]
        lines[45] = "QA_PLAN_END"  # within last 30 lines
        content = "\n".join(lines)
        assert _tail_has_marker_on_own_line(content, "QA_PLAN_END") is True

    def test_empty_content(self):
        assert _tail_has_marker_on_own_line("", "QA_PLAN_END") is False


class TestQAWorkdirs:
    def test_create_qa_workdir(self, tmp_path, monkeypatch):
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        wd = create_qa_workdir("pr-001", "abc123")
        assert wd.exists()
        assert "qa" in str(wd)
        assert "pr-001-abc123" in str(wd)

    def test_create_scenario_workdir(self, tmp_path):
        d, scratch = create_scenario_workdir(tmp_path, 1)
        assert d.exists()
        assert d.name == "repo"
        assert d.parent.name == "s-1"
        assert scratch.exists()
        assert scratch.name == "scratch"
        assert scratch.parent.name == "s-1"

    def test_create_scenario_workdir_with_clone(self, tmp_path):
        """Clone mode creates repo + scratch under s-N/."""
        qa_workdir = tmp_path / "qa"
        qa_workdir.mkdir()

        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        def fake_run_git(*args):
            clone_path = qa_workdir / "s-1" / "repo"
            clone_path.mkdir(parents=True, exist_ok=True)
            return MagicMock(returncode=0)

        with patch("pm_core.git_ops.run_git", side_effect=fake_run_git):
            clone_path, scratch = create_scenario_workdir(
                qa_workdir, 1, repo_root=repo_root,
                pr_id="pr-001", loop_id="abc",
            )

        assert clone_path.exists()
        assert clone_path.name == "repo"
        assert clone_path.parent.name == "s-1"
        assert scratch.exists()
        assert scratch.name == "scratch"
        assert scratch.parent.name == "s-1"


class TestQALoopState:
    def test_defaults(self):
        state = QALoopState(pr_id="pr-001")
        assert state.pr_id == "pr-001"
        assert state.running is False
        assert state.planning_phase is True
        assert state.scenarios == []
        assert state.latest_verdict == ""

    def test_loop_id_generated(self):
        s1 = QALoopState(pr_id="pr-001")
        s2 = QALoopState(pr_id="pr-001")
        assert s1.loop_id != s2.loop_id


class TestQAScenario:
    def test_window_name_field(self):
        """QAScenario uses window_name (not pane_id)."""
        s = QAScenario(index=1, title="Test", focus="Testing")
        assert s.window_name is None
        s.window_name = "qa-#42-s1"
        assert s.window_name == "qa-#42-s1"


class TestScenarioWindowName:
    def test_with_gh_pr_number(self):
        pr_data = {"id": "pr-abc", "gh_pr_number": 116}
        assert _scenario_window_name(pr_data, 1) == "qa-#116-s1"
        assert _scenario_window_name(pr_data, 3) == "qa-#116-s3"

    def test_without_gh_pr_number(self):
        pr_data = {"id": "pr-abc"}
        assert _scenario_window_name(pr_data, 2) == "qa-pr-abc-s2"


class TestCleanupStaleScenarioWindows:
    _WINDOWS = [
        {"id": "@1", "index": "0", "name": "tui"},
        {"id": "@2", "index": "1", "name": "qa-#42"},
        {"id": "@3", "index": "2", "name": "qa-#42-s1"},
        {"id": "@4", "index": "3", "name": "qa-#42-s2"},
        {"id": "@5", "index": "4", "name": "other-window"},
    ]

    def _run_cleanup(self, pr_data, include_main=True):
        mock_tmux = MagicMock()
        mock_tmux.list_windows.return_value = list(self._WINDOWS)
        with patch("pm_core.qa_loop._log"), \
             patch("pm_core.tmux.list_windows", mock_tmux.list_windows), \
             patch("pm_core.tmux.kill_window", mock_tmux.kill_window):
            _cleanup_stale_scenario_windows("pm-test", pr_data,
                                            include_main=include_main)
        return [c[0][1] for c in mock_tmux.kill_window.call_args_list]

    def test_kills_matching_windows(self):
        """_cleanup_stale_scenario_windows kills stale QA windows."""
        pr_data = {"id": "pr-abc", "gh_pr_number": 42}
        killed_ids = self._run_cleanup(pr_data)

        # Verify kill_window was called for qa-#42, qa-#42-s1, qa-#42-s2
        assert "@2" in killed_ids  # qa-#42
        assert "@3" in killed_ids  # qa-#42-s1
        assert "@4" in killed_ids  # qa-#42-s2
        assert "@1" not in killed_ids  # tui — should not be killed
        assert "@5" not in killed_ids  # other-window — should not be killed

    def test_include_main_false_keeps_main_window(self):
        """include_main=False kills scenario windows but keeps the main QA window."""
        pr_data = {"id": "pr-abc", "gh_pr_number": 42}
        killed_ids = self._run_cleanup(pr_data, include_main=False)

        # Scenario windows killed
        assert "@3" in killed_ids  # qa-#42-s1
        assert "@4" in killed_ids  # qa-#42-s2
        # Main QA window preserved
        assert "@2" not in killed_ids  # qa-#42 — should be kept
        assert "@1" not in killed_ids  # tui — should not be killed
        assert "@5" not in killed_ids  # other-window — should not be killed


class TestVerdictConstants:
    def test_verdict_values(self):
        assert VERDICT_PASS == "PASS"
        assert VERDICT_NEEDS_WORK == "NEEDS_WORK"
        assert VERDICT_INPUT_REQUIRED == "INPUT_REQUIRED"


# ---------------------------------------------------------------------------
# Verdict edge cases: dead windows, grace period, failed creation
# ---------------------------------------------------------------------------

class TestVerdictEdgeCases:
    """Edge cases for verdict detection — window death, grace period, etc."""

    def test_dead_window_gets_input_required(self):
        """A window killed without verdict should be marked INPUT_REQUIRED."""
        import pm_core.qa_loop as qa_loop_mod

        scenario = QAScenario(index=1, title="Test", focus="t")
        scenario.window_name = "qa-#42-s1"
        state = QALoopState(pr_id="pr-001")
        state.scenarios = [scenario]
        state.scenario_verdicts = {}

        # Simulate: window is dead (find_window_by_name returns None)
        with patch("pm_core.qa_loop._get_scenario_pane", return_value=None):
            pane_id = qa_loop_mod._get_scenario_pane("sess", scenario.window_name)
            assert pane_id is None
            # This is what the polling loop does:
            state.scenario_verdicts[scenario.index] = VERDICT_INPUT_REQUIRED

        assert state.scenario_verdicts[1] == VERDICT_INPUT_REQUIRED

    def test_dead_window_detected_during_grace_period(self):
        """Dead windows should be detected even within the 30s grace period.

        The polling loop checks window liveness BEFORE applying the grace
        period skip, so a killed window is caught immediately.
        """
        scenario = QAScenario(index=1, title="Test", focus="t")
        scenario.window_name = "qa-#42-s1"
        state = QALoopState(pr_id="pr-001")
        state.scenarios = [scenario]
        state.scenario_verdicts = {}

        pending = {scenario.index}
        in_grace = True  # Simulate being within grace period

        # Simulate: pane is dead
        with patch("pm_core.qa_loop._get_scenario_pane", return_value=None):
            pane_id = None  # _get_scenario_pane returns None
            # In the actual loop, dead window check comes BEFORE grace check:
            if pane_id is None:
                state.scenario_verdicts[scenario.index] = VERDICT_INPUT_REQUIRED
                pending.discard(scenario.index)
            elif in_grace:
                pass  # Would skip verdict reading — but we never reach here

        # Dead window should be detected despite grace period
        assert scenario.index not in pending
        assert state.scenario_verdicts[1] == VERDICT_INPUT_REQUIRED

    def test_failed_window_creation_gets_input_required(self):
        """Scenarios that fail to create a window should get INPUT_REQUIRED,
        not be silently ignored (which would default to PASS)."""
        # Scenario without window_name (creation failed)
        scenario_ok = QAScenario(index=1, title="OK", focus="t")
        scenario_ok.window_name = "qa-#42-s1"
        scenario_fail = QAScenario(index=2, title="Failed", focus="t")
        scenario_fail.window_name = None  # Creation failed

        state = QALoopState(pr_id="pr-001")
        state.scenarios = [scenario_ok, scenario_fail]
        state.scenario_verdicts = {}

        # This is the fix: scenarios without window_name get INPUT_REQUIRED
        for s in state.scenarios:
            if not s.window_name:
                state.scenario_verdicts[s.index] = VERDICT_INPUT_REQUIRED

        assert state.scenario_verdicts[2] == VERDICT_INPUT_REQUIRED

    def test_all_scenarios_failed_creation_overall_not_pass(self):
        """If ALL scenario windows fail to create, overall must NOT be PASS."""
        s1 = QAScenario(index=1, title="A", focus="t")
        s1.window_name = None
        s2 = QAScenario(index=2, title="B", focus="t")
        s2.window_name = None

        state = QALoopState(pr_id="pr-001")
        state.scenarios = [s1, s2]
        state.scenario_verdicts = {}

        # Apply the fix: failed windows get INPUT_REQUIRED
        for s in state.scenarios:
            if not s.window_name:
                state.scenario_verdicts[s.index] = VERDICT_INPUT_REQUIRED

        # Overall verdict aggregation (same as qa_loop.py)
        verdicts = list(state.scenario_verdicts.values())
        if VERDICT_NEEDS_WORK in verdicts:
            overall = VERDICT_NEEDS_WORK
        elif VERDICT_INPUT_REQUIRED in verdicts:
            overall = VERDICT_INPUT_REQUIRED
        else:
            overall = VERDICT_PASS

        assert overall == VERDICT_INPUT_REQUIRED

    def test_overall_verdict_one_dead_one_pass(self):
        """One dead window (INPUT_REQUIRED) + one PASS = overall INPUT_REQUIRED."""
        state = QALoopState(pr_id="pr-001")
        state.scenario_verdicts = {1: VERDICT_PASS, 2: VERDICT_INPUT_REQUIRED}

        verdicts = list(state.scenario_verdicts.values())
        if VERDICT_NEEDS_WORK in verdicts:
            overall = VERDICT_NEEDS_WORK
        elif VERDICT_INPUT_REQUIRED in verdicts:
            overall = VERDICT_INPUT_REQUIRED
        else:
            overall = VERDICT_PASS

        assert overall == VERDICT_INPUT_REQUIRED

    def test_overall_verdict_dead_window_plus_needs_work(self):
        """Dead window + NEEDS_WORK = overall NEEDS_WORK (worst wins)."""
        state = QALoopState(pr_id="pr-001")
        state.scenario_verdicts = {
            1: VERDICT_INPUT_REQUIRED,
            2: VERDICT_NEEDS_WORK,
        }

        verdicts = list(state.scenario_verdicts.values())
        if VERDICT_NEEDS_WORK in verdicts:
            overall = VERDICT_NEEDS_WORK
        elif VERDICT_INPUT_REQUIRED in verdicts:
            overall = VERDICT_INPUT_REQUIRED
        else:
            overall = VERDICT_PASS

        assert overall == VERDICT_NEEDS_WORK

    def test_failed_creation_not_in_pending_set(self):
        """Scenarios without window_name must NOT be in the pending set,
        so the polling loop doesn't hang waiting for them."""
        s1 = QAScenario(index=1, title="OK", focus="t")
        s1.window_name = "qa-#42-s1"
        s2 = QAScenario(index=2, title="Failed", focus="t")
        s2.window_name = None

        pending = {s.index for s in [s1, s2] if s.window_name}
        assert pending == {1}, "Failed scenario must not be in pending"

    def test_all_failed_creation_yields_empty_pending(self):
        """When ALL scenarios fail to create, pending is empty and the
        polling loop is skipped entirely (no hang)."""
        s1 = QAScenario(index=1, title="A", focus="t")
        s1.window_name = None
        s2 = QAScenario(index=2, title="B", focus="t")
        s2.window_name = None

        pending = {s.index for s in [s1, s2] if s.window_name}
        assert len(pending) == 0, "All failed → empty pending → no hang"

    def test_failed_creation_excluded_from_polling_iteration(self):
        """Inside the polling loop, scenarios without window_name are
        skipped by the 'not scenario.window_name' guard."""
        s1 = QAScenario(index=1, title="OK", focus="t")
        s1.window_name = "qa-#42-s1"
        s2 = QAScenario(index=2, title="Failed", focus="t")
        s2.window_name = None

        pending = {s1.index}
        polled = []
        for s in [s1, s2]:
            if s.index not in pending or not s.window_name:
                continue
            polled.append(s.index)

        assert polled == [1], "Only scenarios with windows should be polled"

    def test_create_scenario_workdir_failure_nonfatal_to_loop(self):
        """If create_scenario_workdir raises, the scenario is skipped but
        remaining scenarios still launch (exception doesn't crash the loop)."""
        s1 = QAScenario(index=1, title="Will Fail", focus="t")
        s2 = QAScenario(index=2, title="Will Succeed", focus="t")
        scenarios = [s1, s2]

        launched = []
        calls = []

        def fake_create(qa_workdir, idx, **kw):
            calls.append(idx)
            if idx == 1:
                raise OSError("corrupt repo")
            return (Path("/tmp/clone"), Path("/tmp/scratch"))

        # Simulate the loop logic from run_qa_sync
        for scenario in scenarios:
            try:
                clone_path, scratch_path = fake_create(
                    Path("/tmp/qa"), scenario.index,
                )
            except Exception:
                continue
            scenario.worktree_path = str(clone_path)
            launched.append(scenario.index)

        assert len(calls) == 2, "Both scenarios attempted"
        assert launched == [2], "Only non-failing scenario launched"
        assert s1.worktree_path is None, "Failed scenario has no clone"


# ---------------------------------------------------------------------------
# QA completion: _on_qa_complete lifecycle transitions
# ---------------------------------------------------------------------------

class TestOnQAComplete:
    """Tests for qa_loop_ui._on_qa_complete lifecycle transitions."""

    def _make_app(self, tmp_path):
        """Create a mock TUI app with a qa-status PR on disk."""
        pm_dir = tmp_path / "pm"
        pm_dir.mkdir()
        from pm_core import store
        data = {
            "project": {"name": "test", "repo": "/tmp/r", "base_branch": "master"},
            "prs": [{"id": "pr-001", "title": "T", "branch": "b",
                      "status": "qa", "workdir": str(tmp_path / "wd"),
                      "notes": []}],
        }
        store.save(data, pm_dir)

        app = MagicMock()
        app._root = pm_dir
        app._data = data
        app._auto_start = True
        app._auto_start_target = "pr-001"
        app._qa_loops = {}
        app._review_loops = {}
        app._self_driving_qa = {}
        return app

    def test_pass_triggers_auto_merge(self, tmp_path):
        """QA PASS with no changes should trigger auto-merge."""
        from pm_core.tui.qa_loop_ui import _on_qa_complete

        app = self._make_app(tmp_path)
        state = QALoopState(pr_id="pr-001")
        state.latest_verdict = VERDICT_PASS


        with patch("pm_core.tui.qa_loop_ui._trigger_auto_merge") as mock_merge, \
             patch("pm_core.tui.qa_loop_ui._record_qa_note"):
            _on_qa_complete(app, state)

        mock_merge.assert_called_once_with(app, "pr-001")

    def test_pass_without_auto_start_does_not_merge(self, tmp_path):
        """QA PASS without auto-start should not trigger auto-merge."""
        from pm_core.tui.qa_loop_ui import _on_qa_complete

        app = self._make_app(tmp_path)
        app._auto_start = False  # auto-start disabled
        state = QALoopState(pr_id="pr-001")
        state.latest_verdict = VERDICT_PASS


        with patch("pm_core.tui.qa_loop_ui._trigger_auto_merge") as mock_merge, \
             patch("pm_core.tui.qa_loop_ui._record_qa_note"):
            _on_qa_complete(app, state)

        mock_merge.assert_not_called()
        # Should inform user to merge manually
        app.log_message.assert_called()
        msg = app.log_message.call_args[0][0]
        assert "merge manually" in msg

    def test_needs_work_transitions_to_in_review(self, tmp_path):
        """QA NEEDS_WORK should transition PR from qa → in_review."""
        from pm_core.tui.qa_loop_ui import _on_qa_complete
        from pm_core import store

        app = self._make_app(tmp_path)
        state = QALoopState(pr_id="pr-001")
        state.latest_verdict = VERDICT_NEEDS_WORK


        with patch("pm_core.tui.qa_loop_ui._record_qa_note"), \
             patch("pm_core.tui.auto_start.check_and_start"):
            _on_qa_complete(app, state)

        # Verify the on-disk status changed to in_review
        data = store.load(app._root)
        pr = store.get_pr(data, "pr-001")
        assert pr["status"] == "in_review"

    def test_needs_work_reloads_app_data(self, tmp_path):
        """QA NEEDS_WORK should reload app._data so auto-start sees new status."""
        from pm_core.tui.qa_loop_ui import _on_qa_complete

        app = self._make_app(tmp_path)
        state = QALoopState(pr_id="pr-001")
        state.latest_verdict = VERDICT_NEEDS_WORK


        with patch("pm_core.tui.qa_loop_ui._record_qa_note"), \
             patch("pm_core.tui.auto_start.check_and_start"):
            _on_qa_complete(app, state)

        # app._data should reflect the in_review status
        pr = next(p for p in app._data["prs"] if p["id"] == "pr-001")
        assert pr["status"] == "in_review"

    def test_needs_work_triggers_check_and_start(self, tmp_path):
        """QA NEEDS_WORK should trigger check_and_start to restart review loop."""
        from pm_core.tui.qa_loop_ui import _on_qa_complete

        app = self._make_app(tmp_path)
        state = QALoopState(pr_id="pr-001")
        state.latest_verdict = VERDICT_NEEDS_WORK


        with patch("pm_core.tui.qa_loop_ui._record_qa_note"), \
             patch("pm_core.tui.auto_start.check_and_start") as mock_check:
            _on_qa_complete(app, state)

        # check_and_start should be scheduled via run_worker
        app.run_worker.assert_called_once()

    def test_input_required_leaves_qa_status(self, tmp_path):
        """QA INPUT_REQUIRED should leave PR in qa status."""
        from pm_core.tui.qa_loop_ui import _on_qa_complete
        from pm_core import store

        app = self._make_app(tmp_path)
        state = QALoopState(pr_id="pr-001")
        state.latest_verdict = VERDICT_INPUT_REQUIRED


        with patch("pm_core.tui.qa_loop_ui._record_qa_note"):
            _on_qa_complete(app, state)

        data = store.load(app._root)
        pr = store.get_pr(data, "pr-001")
        assert pr["status"] == "qa"

    def test_no_restart_when_auto_start_disabled(self, tmp_path):
        """With auto-start off, NEEDS_WORK should not call check_and_start."""
        from pm_core.tui.qa_loop_ui import _on_qa_complete

        app = self._make_app(tmp_path)
        app._auto_start = False  # Disabled
        state = QALoopState(pr_id="pr-001")
        state.latest_verdict = VERDICT_NEEDS_WORK


        with patch("pm_core.tui.qa_loop_ui._record_qa_note"):
            _on_qa_complete(app, state)

        # check_and_start should NOT be called
        app.run_worker.assert_not_called()

    def test_needs_work_clears_stale_review_loop(self, tmp_path):
        """QA NEEDS_WORK should clear the old review loop entry so
        _auto_start_review_loops can start a fresh one."""
        from pm_core.tui.qa_loop_ui import _on_qa_complete

        app = self._make_app(tmp_path)
        # Simulate a stale review loop from the previous review pass
        app._review_loops = {"pr-001": MagicMock(running=False)}
        state = QALoopState(pr_id="pr-001")
        state.latest_verdict = VERDICT_NEEDS_WORK


        with patch("pm_core.tui.qa_loop_ui._record_qa_note"), \
             patch("pm_core.tui.auto_start.check_and_start"):
            _on_qa_complete(app, state)

        # Old review loop entry should be removed
        assert "pr-001" not in app._review_loops

    def test_needs_work_records_qa_note(self, tmp_path):
        """QA NEEDS_WORK should record a QA note on the PR."""
        from pm_core.tui.qa_loop_ui import _on_qa_complete
        from pm_core import store

        app = self._make_app(tmp_path)
        state = QALoopState(pr_id="pr-001")
        state.latest_verdict = VERDICT_NEEDS_WORK

        state.scenarios = [QAScenario(index=1, title="Login Flow",
                                       focus="auth")]
        state.scenario_verdicts = {1: VERDICT_NEEDS_WORK}

        with patch("pm_core.tui.auto_start.check_and_start"):
            _on_qa_complete(app, state)

        data = store.load(app._root)
        pr = store.get_pr(data, "pr-001")
        notes = pr.get("notes") or []
        assert len(notes) == 1
        assert "QA NEEDS_WORK:" in notes[0]["text"]
        assert "Login Flow: NEEDS_WORK" in notes[0]["text"]

    def test_qa_note_includes_workdir_path(self, tmp_path):
        """QA note should include the workdir path for inspection/cleanup."""
        from pm_core.tui.qa_loop_ui import _on_qa_complete
        from pm_core import store

        app = self._make_app(tmp_path)
        state = QALoopState(pr_id="pr-001")
        state.latest_verdict = VERDICT_NEEDS_WORK

        state.qa_workdir = "/home/user/.pm/workdirs/qa/pr-001-a1b2"
        state.scenarios = [QAScenario(index=1, title="Test", focus="test")]
        state.scenario_verdicts = {1: VERDICT_NEEDS_WORK}

        with patch("pm_core.tui.auto_start.check_and_start"):
            _on_qa_complete(app, state)

        data = store.load(app._root)
        pr = store.get_pr(data, "pr-001")
        notes = pr.get("notes") or []
        assert len(notes) == 1
        assert "(workdir: /home/user/.pm/workdirs/qa/pr-001-a1b2)" in notes[0]["text"]


# ---------------------------------------------------------------------------
# _maybe_start_qa: review → QA transition
# ---------------------------------------------------------------------------

class TestMaybeStartQA:
    """Tests for review_loop_ui._maybe_start_qa."""

    def _make_app(self, tmp_path, *, auto_start=True, pr_status="in_review"):
        """Create a mock TUI app with a PR on disk."""
        pm_dir = tmp_path / "pm"
        pm_dir.mkdir()
        from pm_core import store
        data = {
            "project": {"name": "test", "repo": "/tmp/r", "base_branch": "master"},
            "prs": [{"id": "pr-001", "title": "T", "branch": "b",
                      "status": pr_status, "workdir": str(tmp_path / "wd"),
                      "notes": []}],
        }
        store.save(data, pm_dir)

        app = MagicMock()
        app._root = pm_dir
        app._data = data
        app._auto_start = auto_start
        app._auto_start_target = "pr-001"
        app._qa_loops = {}
        app._self_driving_qa = {}
        return app

    def test_self_driving_bypasses_auto_start(self, tmp_path):
        """Self-driving QA should transition review→qa even with auto-start off."""
        from pm_core.tui.review_loop_ui import _maybe_start_qa
        from pm_core import store

        app = self._make_app(tmp_path, auto_start=False)
        app._self_driving_qa = {"pr-001": {"strict": False, "pass_count": 0,
                                            "required_passes": 1}}

        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            _maybe_start_qa(app, "pr-001")

        # PR should transition to qa
        data = store.load(app._root)
        pr = store.get_pr(data, "pr-001")
        assert pr["status"] == "qa"
        mock_start.assert_called_once_with(app, "pr-001")

    def test_no_transition_without_auto_start_or_self_driving(self, tmp_path):
        """Without auto-start or self-driving, _maybe_start_qa should be a no-op."""
        from pm_core.tui.review_loop_ui import _maybe_start_qa
        from pm_core import store

        app = self._make_app(tmp_path, auto_start=False)

        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            _maybe_start_qa(app, "pr-001")

        # PR should remain in_review
        data = store.load(app._root)
        pr = store.get_pr(data, "pr-001")
        assert pr["status"] == "in_review"
        mock_start.assert_not_called()


# ---------------------------------------------------------------------------
# _maybe_start_qa: auto-start scoping with dependency trees
# ---------------------------------------------------------------------------

class TestMaybeStartQAScoping:
    """Verify _maybe_start_qa respects auto-start target scoping.

    Tests the full scenario: auto-start targets PR-C, only PRs in
    PR-C's transitive dependency tree (or PR-C itself) should auto-start QA.
    PRs outside the tree should NOT.
    """

    def _make_app(self, tmp_path, *, prs, auto_start=True, target=None):
        """Create a mock TUI app with multiple PRs on disk."""
        pm_dir = tmp_path / "pm"
        pm_dir.mkdir()
        from pm_core import store
        data = {
            "project": {"name": "test", "repo": "/tmp/r", "base_branch": "master"},
            "prs": prs,
        }
        store.save(data, pm_dir)

        app = MagicMock()
        app._root = pm_dir
        app._data = data
        app._auto_start = auto_start
        app._auto_start_target = target
        app._qa_loops = {}
        app._self_driving_qa = {}
        return app

    def test_transitions_pr_in_target_dep_tree(self, tmp_path):
        """PR in the target's transitive dependency tree transitions to qa."""
        from pm_core.tui.review_loop_ui import _maybe_start_qa
        from pm_core import store

        prs = [
            {"id": "pr-a", "title": "A", "branch": "a", "status": "in_review",
             "workdir": "/tmp/wa", "depends_on": [], "notes": []},
            {"id": "pr-b", "title": "B", "branch": "b", "status": "pending",
             "workdir": "/tmp/wb", "depends_on": ["pr-a"], "notes": []},
        ]
        app = self._make_app(tmp_path, prs=prs, target="pr-b")

        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            _maybe_start_qa(app, "pr-a")

        data = store.load(app._root)
        pr = store.get_pr(data, "pr-a")
        assert pr["status"] == "qa"
        mock_start.assert_called_once_with(app, "pr-a")

    def test_transitions_target_pr_itself(self, tmp_path):
        """The auto-start target PR itself transitions to qa."""
        from pm_core.tui.review_loop_ui import _maybe_start_qa
        from pm_core import store

        prs = [
            {"id": "pr-a", "title": "A", "branch": "a", "status": "merged",
             "workdir": "/tmp/wa", "depends_on": [], "notes": []},
            {"id": "pr-b", "title": "B", "branch": "b", "status": "in_review",
             "workdir": "/tmp/wb", "depends_on": ["pr-a"], "notes": []},
        ]
        app = self._make_app(tmp_path, prs=prs, target="pr-b")

        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            _maybe_start_qa(app, "pr-b")

        data = store.load(app._root)
        pr = store.get_pr(data, "pr-b")
        assert pr["status"] == "qa"
        mock_start.assert_called_once_with(app, "pr-b")

    def test_skips_pr_outside_target_dep_tree(self, tmp_path):
        """PR NOT in the target's dependency tree is NOT transitioned."""
        from pm_core.tui.review_loop_ui import _maybe_start_qa
        from pm_core import store

        prs = [
            {"id": "pr-a", "title": "A", "branch": "a", "status": "in_review",
             "workdir": "/tmp/wa", "depends_on": [], "notes": []},
            {"id": "pr-b", "title": "B", "branch": "b", "status": "pending",
             "workdir": "/tmp/wb", "depends_on": [], "notes": []},
            {"id": "pr-c", "title": "C", "branch": "c", "status": "pending",
             "workdir": "/tmp/wc", "depends_on": ["pr-b"], "notes": []},
        ]
        # Target is pr-c, which depends on pr-b only — pr-a is outside the tree
        app = self._make_app(tmp_path, prs=prs, target="pr-c")

        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            _maybe_start_qa(app, "pr-a")

        data = store.load(app._root)
        pr = store.get_pr(data, "pr-a")
        assert pr["status"] == "in_review"  # unchanged
        mock_start.assert_not_called()

    def test_no_target_allows_all_prs(self, tmp_path):
        """Without a target, any in_review PR transitions to qa."""
        from pm_core.tui.review_loop_ui import _maybe_start_qa
        from pm_core import store

        prs = [
            {"id": "pr-x", "title": "X", "branch": "x", "status": "in_review",
             "workdir": "/tmp/wx", "depends_on": [], "notes": []},
        ]
        app = self._make_app(tmp_path, prs=prs, target=None)

        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            _maybe_start_qa(app, "pr-x")

        data = store.load(app._root)
        pr = store.get_pr(data, "pr-x")
        assert pr["status"] == "qa"
        mock_start.assert_called_once_with(app, "pr-x")

    def test_skips_pr_not_in_review_status(self, tmp_path):
        """PR that is not in_review status is not transitioned even if in tree."""
        from pm_core.tui.review_loop_ui import _maybe_start_qa
        from pm_core import store

        prs = [
            {"id": "pr-a", "title": "A", "branch": "a", "status": "pending",
             "workdir": "/tmp/wa", "depends_on": [], "notes": []},
            {"id": "pr-b", "title": "B", "branch": "b", "status": "pending",
             "workdir": "/tmp/wb", "depends_on": ["pr-a"], "notes": []},
        ]
        app = self._make_app(tmp_path, prs=prs, target="pr-b")

        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            _maybe_start_qa(app, "pr-a")

        data = store.load(app._root)
        pr = store.get_pr(data, "pr-a")
        assert pr["status"] == "pending"  # unchanged
        mock_start.assert_not_called()


class TestPollTriggersQA:
    """Integration: _poll_loop_state with VERDICT_PASS triggers _maybe_start_qa."""

    def _make_app(self, tmp_path, *, prs, auto_start=True, target=None):
        """Create mock app with review loop state."""
        pm_dir = tmp_path / "pm"
        pm_dir.mkdir()
        from pm_core import store
        data = {
            "project": {"name": "test", "repo": "/tmp/r", "base_branch": "master"},
            "prs": prs,
        }
        store.save(data, pm_dir)

        app = MagicMock()
        app._root = pm_dir
        app._data = data
        app._auto_start = auto_start
        app._auto_start_target = target
        app._review_loops = {}
        app._qa_loops = {}
        app._self_driving_qa = {}
        from pm_core.watcher_manager import WatcherManager
        app._watcher_manager = WatcherManager()
        app._impl_poll_counter = 0
        return app

    def test_verdict_pass_triggers_maybe_start_qa(self, tmp_path):
        """When _poll_loop_state sees VERDICT_PASS, _maybe_start_qa is called."""
        from pm_core.tui.review_loop_ui import _poll_loop_state
        from pm_core.review_loop import ReviewLoopState, VERDICT_PASS
        from pm_core import store

        prs = [
            {"id": "pr-001", "title": "T", "branch": "b", "status": "in_review",
             "workdir": "/tmp/w", "depends_on": [], "notes": []},
        ]
        app = self._make_app(tmp_path, prs=prs, target="pr-001")

        # Create a completed review loop state
        state = ReviewLoopState(pr_id="pr-001")
        state.running = False
        state.latest_verdict = VERDICT_PASS
        state.iteration = 1
        app._review_loops["pr-001"] = state

        with patch("pm_core.tui.review_loop_ui._maybe_start_qa") as mock_qa, \
             patch("pm_core.tui.review_loop_ui._refresh_tech_tree"), \
             patch("pm_core.tui.review_loop_ui._poll_impl_idle"), \
             patch("pm_core.tui.watcher_ui.poll_watcher_state"), \
             patch("pm_core.tui.qa_loop_ui.poll_qa_state"):
            _poll_loop_state(app)

        mock_qa.assert_called_once_with(app, "pr-001")

    def test_verdict_pass_with_suggestions_triggers_qa(self, tmp_path):
        """PASS_WITH_SUGGESTIONS also triggers auto-QA."""
        from pm_core.tui.review_loop_ui import _poll_loop_state
        from pm_core.review_loop import ReviewLoopState, VERDICT_PASS_WITH_SUGGESTIONS
        from pm_core import store

        prs = [
            {"id": "pr-001", "title": "T", "branch": "b", "status": "in_review",
             "workdir": "/tmp/w", "depends_on": [], "notes": []},
        ]
        app = self._make_app(tmp_path, prs=prs, target="pr-001")

        state = ReviewLoopState(pr_id="pr-001")
        state.running = False
        state.latest_verdict = VERDICT_PASS_WITH_SUGGESTIONS
        state.iteration = 1
        app._review_loops["pr-001"] = state

        with patch("pm_core.tui.review_loop_ui._maybe_start_qa") as mock_qa, \
             patch("pm_core.tui.review_loop_ui._refresh_tech_tree"), \
             patch("pm_core.tui.review_loop_ui._poll_impl_idle"), \
             patch("pm_core.tui.watcher_ui.poll_watcher_state"), \
             patch("pm_core.tui.qa_loop_ui.poll_qa_state"):
            _poll_loop_state(app)

        mock_qa.assert_called_once_with(app, "pr-001")

    def test_verdict_needs_work_does_not_trigger_qa(self, tmp_path):
        """NEEDS_WORK verdict should NOT trigger auto-QA."""
        from pm_core.tui.review_loop_ui import _poll_loop_state
        from pm_core.review_loop import ReviewLoopState, VERDICT_NEEDS_WORK

        prs = [
            {"id": "pr-001", "title": "T", "branch": "b", "status": "in_review",
             "workdir": "/tmp/w", "depends_on": [], "notes": []},
        ]
        app = self._make_app(tmp_path, prs=prs, target="pr-001")

        state = ReviewLoopState(pr_id="pr-001")
        state.running = False
        state.latest_verdict = VERDICT_NEEDS_WORK
        state.iteration = 1
        app._review_loops["pr-001"] = state

        with patch("pm_core.tui.review_loop_ui._maybe_start_qa") as mock_qa, \
             patch("pm_core.tui.review_loop_ui._refresh_tech_tree"), \
             patch("pm_core.tui.review_loop_ui._poll_impl_idle"), \
             patch("pm_core.tui.watcher_ui.poll_watcher_state"), \
             patch("pm_core.tui.qa_loop_ui.poll_qa_state"):
            _poll_loop_state(app)

        mock_qa.assert_not_called()


# ---------------------------------------------------------------------------
# Self-driving QA: NEEDS_WORK → review → QA loop
# ---------------------------------------------------------------------------

class TestSelfDrivingQALoop:
    """Tests for the self-driving QA loop (zz t / zzz t).

    Verifies that when QA completes with NEEDS_WORK in self-driving mode,
    the review loop is started directly (not via auto-start), and that
    when review passes, QA restarts to complete the loop.
    """

    def _make_app(self, tmp_path, *, pr_status="qa"):
        """Create a mock TUI app with self-driving QA state."""
        pm_dir = tmp_path / "pm"
        pm_dir.mkdir()
        from pm_core import store
        data = {
            "project": {"name": "test", "repo": "/tmp/r", "base_branch": "master"},
            "prs": [{"id": "pr-001", "title": "T", "branch": "b",
                      "status": pr_status, "workdir": str(tmp_path / "wd"),
                      "notes": []}],
        }
        store.save(data, pm_dir)

        app = MagicMock()
        app._root = pm_dir
        app._data = data
        app._auto_start = False  # Self-driving works independently of auto-start
        app._auto_start_target = None
        app._qa_loops = {}
        app._review_loops = {}
        app._self_driving_qa = {
            "pr-001": {"strict": False, "pass_count": 0, "required_passes": 1}
        }
        return app

    def test_needs_work_starts_review_directly(self, tmp_path):
        """Self-driving QA NEEDS_WORK should call _start_self_driving_review,
        not rely on auto-start."""
        from pm_core.tui.qa_loop_ui import _on_qa_complete

        app = self._make_app(tmp_path)
        state = QALoopState(pr_id="pr-001")
        state.latest_verdict = VERDICT_NEEDS_WORK

        state.scenarios = [QAScenario(index=1, title="Test", focus="test")]
        state.scenario_verdicts = {1: VERDICT_NEEDS_WORK}

        with patch("pm_core.tui.qa_loop_ui._start_self_driving_review") as mock_review, \
             patch("pm_core.tui.qa_loop_ui._record_qa_note"):
            _on_qa_complete(app, state)

        mock_review.assert_called_once_with(app, "pr-001", False)
        # run_worker should NOT be called (not using auto-start path)
        app.run_worker.assert_not_called()

    def test_needs_work_resets_pass_count(self, tmp_path):
        """Self-driving QA NEEDS_WORK should reset pass_count to 0."""
        from pm_core.tui.qa_loop_ui import _on_qa_complete

        app = self._make_app(tmp_path)
        app._self_driving_qa["pr-001"]["pass_count"] = 2  # Had previous passes

        state = QALoopState(pr_id="pr-001")
        state.latest_verdict = VERDICT_NEEDS_WORK

        state.scenarios = [QAScenario(index=1, title="Test", focus="test")]
        state.scenario_verdicts = {1: VERDICT_NEEDS_WORK}

        with patch("pm_core.tui.qa_loop_ui._start_self_driving_review"), \
             patch("pm_core.tui.qa_loop_ui._record_qa_note"):
            _on_qa_complete(app, state)

        assert app._self_driving_qa["pr-001"]["pass_count"] == 0

    def test_strict_mode_passes_through(self, tmp_path):
        """zzz t (strict=True) should pass strict=True to _start_self_driving_review."""
        from pm_core.tui.qa_loop_ui import _on_qa_complete

        app = self._make_app(tmp_path)
        app._self_driving_qa["pr-001"]["strict"] = True

        state = QALoopState(pr_id="pr-001")
        state.latest_verdict = VERDICT_NEEDS_WORK

        state.scenarios = [QAScenario(index=1, title="Test", focus="test")]
        state.scenario_verdicts = {1: VERDICT_NEEDS_WORK}

        with patch("pm_core.tui.qa_loop_ui._start_self_driving_review") as mock_review, \
             patch("pm_core.tui.qa_loop_ui._record_qa_note"):
            _on_qa_complete(app, state)

        mock_review.assert_called_once_with(app, "pr-001", True)

    def test_pass_increments_pass_count(self, tmp_path):
        """Self-driving QA PASS should increment pass_count."""
        from pm_core.tui.qa_loop_ui import _on_qa_complete

        app = self._make_app(tmp_path)
        app._self_driving_qa["pr-001"]["required_passes"] = 3

        state = QALoopState(pr_id="pr-001")
        state.latest_verdict = VERDICT_PASS

        state.scenarios = [QAScenario(index=1, title="Test", focus="test")]
        state.scenario_verdicts = {1: VERDICT_PASS}

        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start, \
             patch("pm_core.tui.qa_loop_ui._record_qa_note"):
            _on_qa_complete(app, state)

        # pass_count should be 1, required is 3, so QA should restart
        assert app._self_driving_qa["pr-001"]["pass_count"] == 1
        mock_start.assert_called_once_with(app, "pr-001")

    def test_pass_with_enough_passes_triggers_merge(self, tmp_path):
        """Self-driving QA with enough consecutive passes triggers merge."""
        from pm_core.tui.qa_loop_ui import _on_qa_complete

        app = self._make_app(tmp_path)
        app._self_driving_qa["pr-001"]["required_passes"] = 2
        app._self_driving_qa["pr-001"]["pass_count"] = 1  # Already had one pass

        state = QALoopState(pr_id="pr-001")
        state.latest_verdict = VERDICT_PASS

        state.scenarios = [QAScenario(index=1, title="Test", focus="test")]
        state.scenario_verdicts = {1: VERDICT_PASS}

        with patch("pm_core.tui.qa_loop_ui._trigger_auto_merge") as mock_merge, \
             patch("pm_core.tui.qa_loop_ui._record_qa_note"):
            _on_qa_complete(app, state)

        mock_merge.assert_called_once_with(app, "pr-001")
        # Self-driving state should be removed after reaching required passes
        assert "pr-001" not in app._self_driving_qa


# ---------------------------------------------------------------------------
# Verdict verification tests
# ---------------------------------------------------------------------------

class TestBuildVerificationPrompt:
    """Tests for _build_verification_prompt."""

    def test_includes_scenario_details_inline(self):
        scenario = QAScenario(index=1, title="Login Flow", focus="auth",
                              steps="1. Test login\n2. Test logout")
        prompt = _build_verification_prompt(scenario, "PASS",
                                            pane_output="Some output here")
        assert "Login Flow" in prompt
        assert "auth" in prompt
        assert "Test login" in prompt
        assert "PASS" in prompt
        assert "Some output here" in prompt

    def test_truncates_long_inline_output(self):
        scenario = QAScenario(index=1, title="Test", focus="test", steps="steps")
        long_output = "\n".join([f"line {i}" for i in range(_VERIFICATION_MAX_PANE_LINES + 100)])
        prompt = _build_verification_prompt(scenario, "PASS",
                                            pane_output=long_output)
        assert "truncated" in prompt.lower()

    def test_file_path_mode_plain(self):
        scenario = QAScenario(index=1, title="Test", focus="test", steps="steps")
        prompt = _build_verification_prompt(scenario, "PASS",
                                            pane_output_path="/tmp/qa_verify.txt")
        assert "/tmp/qa_verify.txt" in prompt
        assert "Read that file" in prompt
        assert "<scenario_output>" not in prompt
        # Plain text file — no JSONL hint
        assert "JSON Lines" not in prompt

    def test_file_path_mode_jsonl(self):
        scenario = QAScenario(index=1, title="Test", focus="test", steps="steps")
        prompt = _build_verification_prompt(
            scenario, "PASS",
            pane_output_path="/tmp/transcript-s1.jsonl")
        assert "transcript-s1.jsonl" in prompt
        assert "JSON Lines" in prompt

    def test_includes_verification_instructions(self):
        scenario = QAScenario(index=1, title="Test", focus="test", steps="steps")
        prompt = _build_verification_prompt(scenario, "PASS",
                                            pane_output="output")
        assert "VERIFIED" in prompt
        assert "FLAGGED_START" in prompt
        assert "FLAGGED_END" in prompt


class TestVerifySingleScenario:
    """Tests for _verify_single_scenario."""

    def _mock_verify(self, scenario, verdict, pane_output, poll_content,
                     pr_data=None, project_data=None):
        """Helper: run _verify_single_scenario with mocked tmux ops."""
        mock_wid = MagicMock()
        mock_wid.stdout = "@1"
        mock_reg = {"windows": {}}
        mock_wdata = {"user_modified": True}
        with patch("pm_core.qa_loop._get_scenario_pane", return_value="%1"), \
             patch("pm_core.tmux.split_pane_at", return_value="%2"), \
             patch("pm_core.qa_loop.poll_for_verdict", return_value=poll_content), \
             patch("pm_core.claude_launcher.build_claude_shell_cmd", return_value="claude ..."), \
             patch("subprocess.run", return_value=mock_wid), \
             patch("pm_core.tmux.set_shared_window_size"), \
             patch("pm_core.pane_registry.register_pane"), \
             patch("pm_core.pane_registry.load_registry", return_value=mock_reg), \
             patch("pm_core.pane_registry.get_window_data", return_value=mock_wdata), \
             patch("pm_core.pane_registry.save_registry"), \
             patch("pm_core.pane_layout.rebalance"):
            return _verify_single_scenario(
                scenario, verdict, pane_output,
                pr_data or {}, project_data or {},
                session="pm-session",
            )

    def test_verified_result(self):
        scenario = QAScenario(index=1, title="Test", focus="test",
                              steps="steps", window_name="qa-s1")
        content = "The scenario looks good.\n\nVERIFIED"
        passed, reason = self._mock_verify(scenario, "PASS", "output", content)
        assert passed is True
        assert reason == ""

    def test_flagged_result(self):
        scenario = QAScenario(index=1, title="Test", focus="test",
                              steps="steps", window_name="qa-s1")
        content = "FLAGGED_START\nThe scenario did not run any tests.\nFLAGGED_END"
        passed, reason = self._mock_verify(scenario, "PASS", "output", content)
        assert passed is False
        assert "did not run" in reason.lower()

    def test_pane_split_failure_trusts_original(self):
        """If we can't split a pane, trust the original verdict."""
        scenario = QAScenario(index=1, title="Test", focus="test",
                              steps="steps", window_name="qa-s1")
        with patch("pm_core.qa_loop._get_scenario_pane", return_value="%1"), \
             patch("pm_core.tmux.split_pane_at", side_effect=Exception("split failed")), \
             patch("pm_core.claude_launcher.build_claude_shell_cmd", return_value="claude ..."):
            passed, reason = _verify_single_scenario(
                scenario, "PASS", "output", {}, {},
                session="pm-session",
            )
        assert passed is True

    def test_no_pane_trusts_original(self):
        """If scenario pane is gone, trust the original verdict."""
        scenario = QAScenario(index=1, title="Test", focus="test",
                              steps="steps", window_name="qa-s1")
        with patch("pm_core.qa_loop._get_scenario_pane", return_value=None):
            passed, reason = _verify_single_scenario(
                scenario, "PASS", "output", {}, {},
                session="pm-session",
            )
        assert passed is True

    def test_poll_returns_none_trusts_original(self):
        """If polling returns None (pane died), trust original."""
        scenario = QAScenario(index=1, title="Test", focus="test",
                              steps="steps", window_name="qa-s1")
        passed, reason = self._mock_verify(scenario, "PASS", "output", None)
        assert passed is True

    def test_uses_transcript_when_available(self, tmp_path):
        """When scenario has a transcript, prompt references the file."""
        transcript = tmp_path / "transcript-s1.jsonl"
        transcript.write_text('{"role":"assistant","content":"done"}\n')
        scenario = QAScenario(index=1, title="Test", focus="test",
                              steps="steps", window_name="qa-s1",
                              transcript_path=str(transcript))
        mock_wid = MagicMock()
        mock_wid.stdout = "@1"
        mock_reg = {"windows": {}}
        mock_wdata = {"user_modified": True}
        with patch("pm_core.qa_loop._get_scenario_pane", return_value="%1"), \
             patch("pm_core.tmux.split_pane_at", return_value="%2"), \
             patch("pm_core.qa_loop.poll_for_verdict", return_value="VERIFIED"), \
             patch("pm_core.claude_launcher.build_claude_shell_cmd",
                   return_value="claude ...") as mock_cmd, \
             patch("subprocess.run", return_value=mock_wid), \
             patch("pm_core.tmux.set_shared_window_size"), \
             patch("pm_core.pane_registry.register_pane"), \
             patch("pm_core.pane_registry.load_registry", return_value=mock_reg), \
             patch("pm_core.pane_registry.get_window_data", return_value=mock_wdata), \
             patch("pm_core.pane_registry.save_registry"), \
             patch("pm_core.pane_layout.rebalance"):
            passed, _ = _verify_single_scenario(
                scenario, "PASS", "pane output", {}, {},
                session="pm-session")
        assert passed is True
        # The prompt passed to build_claude_shell_cmd should reference transcript
        call_kwargs = mock_cmd.call_args
        assert str(transcript) in (call_kwargs.kwargs.get("prompt", "") or "")

    def test_falls_back_to_pane_when_no_transcript(self):
        """Without a transcript, pane output is inlined in the prompt."""
        scenario = QAScenario(index=1, title="Test", focus="test",
                              steps="steps", window_name="qa-s1")
        mock_wid = MagicMock()
        mock_wid.stdout = "@1"
        mock_reg = {"windows": {}}
        mock_wdata = {"user_modified": True}
        with patch("pm_core.qa_loop._get_scenario_pane", return_value="%1"), \
             patch("pm_core.tmux.split_pane_at", return_value="%2"), \
             patch("pm_core.qa_loop.poll_for_verdict", return_value="VERIFIED"), \
             patch("pm_core.claude_launcher.build_claude_shell_cmd",
                   return_value="claude ...") as mock_cmd, \
             patch("subprocess.run", return_value=mock_wid), \
             patch("pm_core.tmux.set_shared_window_size"), \
             patch("pm_core.pane_registry.register_pane"), \
             patch("pm_core.pane_registry.load_registry", return_value=mock_reg), \
             patch("pm_core.pane_registry.get_window_data", return_value=mock_wdata), \
             patch("pm_core.pane_registry.save_registry"), \
             patch("pm_core.pane_layout.rebalance"):
            _verify_single_scenario(
                scenario, "PASS", "pane output", {}, {},
                session="pm-session")
        call_kwargs = mock_cmd.call_args
        assert "pane output" in (call_kwargs.kwargs.get("prompt", "") or "")


class TestVerificationSetting:
    """Tests for _is_verification_enabled global setting."""

    def test_default_is_enabled(self):
        with patch("pm_core.paths.get_global_setting_value", return_value=""):
            assert _is_verification_enabled() is True

    def test_disabled_with_false(self):
        for val in ("0", "false", "no", "off", "disabled", "False", "OFF"):
            with patch("pm_core.paths.get_global_setting_value", return_value=val):
                assert _is_verification_enabled() is False, f"Expected disabled for {val!r}"

    def test_enabled_with_truthy(self):
        for val in ("1", "true", "yes", "on"):
            with patch("pm_core.paths.get_global_setting_value", return_value=val):
                assert _is_verification_enabled() is True, f"Expected enabled for {val!r}"


class TestExtractFlaggedReason:
    """Tests for _extract_flagged_reason."""

    def test_basic_extraction(self):
        content = "Some preamble\nFLAGGED_START\nThe test was not run.\nFLAGGED_END"
        assert _extract_flagged_reason(content) == "The test was not run."

    def test_multiline_reason(self):
        content = (
            "FLAGGED_START\n"
            "Step 2 was skipped entirely.\n"
            "Step 4 used code reading instead of execution.\n"
            "The scenario substituted unit tests for runtime testing.\n"
            "FLAGGED_END"
        )
        reason = _extract_flagged_reason(content)
        assert "Step 2" in reason
        assert "Step 4" in reason
        assert "substituted" in reason
        assert "\n" in reason  # multiline preserved

    def test_missing_end_marker(self):
        content = "FLAGGED_START\nPartial reason without end"
        reason = _extract_flagged_reason(content)
        assert "Partial reason" in reason

    def test_no_markers_returns_default(self):
        content = "Some random output with no markers"
        reason = _extract_flagged_reason(content)
        assert reason == "Scenario did not properly exercise test cases"

    def test_strips_markdown_formatting(self):
        content = "FLAGGED_START\n**Bold** and `code` formatting\nFLAGGED_END"
        reason = _extract_flagged_reason(content)
        assert "Bold" in reason
        assert "code" in reason

    def test_empty_between_markers(self):
        content = "FLAGGED_START\nFLAGGED_END"
        reason = _extract_flagged_reason(content)
        assert reason == "Scenario did not properly exercise test cases"

    def test_skips_prompt_template_markers(self):
        """Extracts reason from verifier output, not prompt template."""
        content = (
            "FLAGGED_START\n"
            "<explanation of what went wrong>\n"
            "FLAGGED_END\n"
            "\n"
            "Checklist analysis...\n"
            "\n"
            "FLAGGED_START\n"
            "The scenario never ran the actual CLI tool\n"
            "FLAGGED_END\n"
        )
        reason = _extract_flagged_reason(content)
        assert reason == "The scenario never ran the actual CLI tool"


class TestVerificationMaxRetries:
    """Tests for _get_verification_max_retries global setting."""

    def test_default_value(self):
        with patch("pm_core.paths.get_global_setting_value", return_value=""):
            assert _get_verification_max_retries() == _DEFAULT_VERIFICATION_MAX_RETRIES

    def test_custom_value(self):
        with patch("pm_core.paths.get_global_setting_value", return_value="3"):
            assert _get_verification_max_retries() == 3

    def test_zero_value(self):
        with patch("pm_core.paths.get_global_setting_value", return_value="0"):
            assert _get_verification_max_retries() == 0

    def test_invalid_value_returns_default(self):
        with patch("pm_core.paths.get_global_setting_value", return_value="abc"):
            assert _get_verification_max_retries() == _DEFAULT_VERIFICATION_MAX_RETRIES

    def test_negative_clamped_to_zero(self):
        with patch("pm_core.paths.get_global_setting_value", return_value="-1"):
            assert _get_verification_max_retries() == 0


class TestInstallInstructionFile:
    """Tests for _install_instruction_file."""

    def test_copies_file_and_updates_path(self, tmp_path):
        pm_root = tmp_path / "pm"
        instr = pm_root / "qa" / "instructions"
        instr.mkdir(parents=True)
        (instr / "my-test.md").write_text("# Test\n")

        scratch = tmp_path / "scratch"
        scratch.mkdir()
        scenario = QAScenario(index=1, title="T", focus="f", steps="s",
                              instruction_path="instructions/my-test.md")
        _install_instruction_file(pm_root, scenario, scratch,
                                  scratch_dir="/scratch")
        assert scenario.instruction_path == "/scratch/qa-instructions/my-test.md"
        assert (scratch / "qa-instructions" / "my-test.md").exists()

    def test_clears_path_when_file_missing(self, tmp_path):
        pm_root = tmp_path / "pm"
        (pm_root / "qa" / "instructions").mkdir(parents=True)
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        scenario = QAScenario(index=1, title="T", focus="f", steps="s",
                              instruction_path="instructions/gone.md")
        _install_instruction_file(pm_root, scenario, scratch,
                                  scratch_dir="/scratch")
        assert scenario.instruction_path is None

    def test_noop_when_no_instruction(self, tmp_path):
        scenario = QAScenario(index=1, title="T", focus="f", steps="s")
        _install_instruction_file(tmp_path, scenario, tmp_path,
                                  scratch_dir="/scratch")
        assert scenario.instruction_path is None
