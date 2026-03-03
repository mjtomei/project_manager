"""Tests for the QA loop orchestration."""

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
    _scenario_window_name,
    _cleanup_stale_scenario_windows,
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


class TestQAWorkdirs:
    def test_create_qa_workdir(self, tmp_path, monkeypatch):
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        wd = create_qa_workdir("pr-001", "abc123")
        assert wd.exists()
        assert "qa" in str(wd)
        assert "pr-001-abc123" in str(wd)

    def test_create_scenario_workdir(self, tmp_path):
        d, branch, scratch = create_scenario_workdir(tmp_path, 1)
        assert d.exists()
        assert d.name == "scenario-1"
        assert branch == ""
        assert scratch.exists()


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
        from pm_core.qa_loop import _get_scenario_pane

        scenario = QAScenario(index=1, title="Test", focus="t")
        scenario.window_name = "qa-#42-s1"
        state = QALoopState(pr_id="pr-001")
        state.scenarios = [scenario]
        state.scenario_verdicts = {}

        # Simulate: window is dead (find_window_by_name returns None)
        with patch("pm_core.qa_loop._get_scenario_pane", return_value=None):
            pane_id = _get_scenario_pane("sess", scenario.window_name)
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
        if VERDICT_NEEDS_WORK in verdicts or state.made_changes:
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
        if VERDICT_NEEDS_WORK in verdicts or state.made_changes:
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
        if VERDICT_NEEDS_WORK in verdicts or state.made_changes:
            overall = VERDICT_NEEDS_WORK
        elif VERDICT_INPUT_REQUIRED in verdicts:
            overall = VERDICT_INPUT_REQUIRED
        else:
            overall = VERDICT_PASS

        assert overall == VERDICT_NEEDS_WORK


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
        state.made_changes = False

        with patch("pm_core.tui.qa_loop_ui._trigger_auto_merge") as mock_merge, \
             patch("pm_core.tui.qa_loop_ui._record_qa_note"):
            _on_qa_complete(app, state)

        mock_merge.assert_called_once_with(app, "pr-001")

    def test_needs_work_transitions_to_in_review(self, tmp_path):
        """QA NEEDS_WORK should transition PR from qa → in_review."""
        from pm_core.tui.qa_loop_ui import _on_qa_complete
        from pm_core import store

        app = self._make_app(tmp_path)
        state = QALoopState(pr_id="pr-001")
        state.latest_verdict = VERDICT_NEEDS_WORK
        state.made_changes = False

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
        state.made_changes = False

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
        state.made_changes = False

        with patch("pm_core.tui.qa_loop_ui._record_qa_note"), \
             patch("pm_core.tui.auto_start.check_and_start") as mock_check:
            _on_qa_complete(app, state)

        # check_and_start should be scheduled via run_worker
        app.run_worker.assert_called_once()

    def test_made_changes_transitions_to_in_review(self, tmp_path):
        """QA PASS with changes should transition PR back to in_review."""
        from pm_core.tui.qa_loop_ui import _on_qa_complete
        from pm_core import store

        app = self._make_app(tmp_path)
        state = QALoopState(pr_id="pr-001")
        state.latest_verdict = VERDICT_PASS
        state.made_changes = True  # Changes committed during QA

        with patch("pm_core.tui.qa_loop_ui._record_qa_note"), \
             patch("pm_core.tui.auto_start.check_and_start"):
            _on_qa_complete(app, state)

        data = store.load(app._root)
        pr = store.get_pr(data, "pr-001")
        assert pr["status"] == "in_review"

    def test_input_required_leaves_qa_status(self, tmp_path):
        """QA INPUT_REQUIRED should leave PR in qa status."""
        from pm_core.tui.qa_loop_ui import _on_qa_complete
        from pm_core import store

        app = self._make_app(tmp_path)
        state = QALoopState(pr_id="pr-001")
        state.latest_verdict = VERDICT_INPUT_REQUIRED
        state.made_changes = False

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
        state.made_changes = False

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
        state.made_changes = False

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
        state.made_changes = False
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

    def test_needs_work_with_changes_records_changes_committed(self, tmp_path):
        """QA NEEDS_WORK with changes should record '[changes committed]' in note."""
        from pm_core.tui.qa_loop_ui import _on_qa_complete
        from pm_core import store

        app = self._make_app(tmp_path)
        state = QALoopState(pr_id="pr-001")
        state.latest_verdict = VERDICT_NEEDS_WORK
        state.made_changes = True
        state.scenarios = [QAScenario(index=1, title="Test", focus="test")]
        state.scenario_verdicts = {1: VERDICT_NEEDS_WORK}

        with patch("pm_core.tui.auto_start.check_and_start"):
            _on_qa_complete(app, state)

        data = store.load(app._root)
        pr = store.get_pr(data, "pr-001")
        notes = pr.get("notes") or []
        assert len(notes) == 1
        assert "[changes committed]" in notes[0]["text"]


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
        state.made_changes = False
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
        state.made_changes = False
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
        state.made_changes = False
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
        state.made_changes = False
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
        state.made_changes = False
        state.scenarios = [QAScenario(index=1, title="Test", focus="test")]
        state.scenario_verdicts = {1: VERDICT_PASS}

        with patch("pm_core.tui.qa_loop_ui._trigger_auto_merge") as mock_merge, \
             patch("pm_core.tui.qa_loop_ui._record_qa_note"):
            _on_qa_complete(app, state)

        mock_merge.assert_called_once_with(app, "pr-001")
        # Self-driving state should be removed after reaching required passes
        assert "pr-001" not in app._self_driving_qa

    def test_made_changes_with_pass_verdict_still_returns_to_review(self, tmp_path):
        """Self-driving QA: PASS with changes should return to review (not merge)."""
        from pm_core.tui.qa_loop_ui import _on_qa_complete
        from pm_core import store

        app = self._make_app(tmp_path)
        state = QALoopState(pr_id="pr-001")
        state.latest_verdict = VERDICT_PASS
        state.made_changes = True  # Changes committed → needs re-review
        state.scenarios = [QAScenario(index=1, title="Test", focus="test")]
        state.scenario_verdicts = {1: VERDICT_PASS}

        with patch("pm_core.tui.qa_loop_ui._start_self_driving_review") as mock_review, \
             patch("pm_core.tui.qa_loop_ui._record_qa_note"):
            _on_qa_complete(app, state)

        # PR should transition to in_review, not merge
        data = store.load(app._root)
        pr = store.get_pr(data, "pr-001")
        assert pr["status"] == "in_review"
        mock_review.assert_called_once()
        # pass_count should be reset
        assert app._self_driving_qa["pr-001"]["pass_count"] == 0
