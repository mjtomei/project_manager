"""Tests for the QA loop orchestration."""

import pytest

from pm_core.qa_loop import (
    parse_qa_plan,
    QAScenario,
    QALoopState,
    create_qa_workdir,
    create_scenario_workdir,
    VERDICT_PASS,
    VERDICT_NEEDS_WORK,
    VERDICT_INPUT_REQUIRED,
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
        d = create_scenario_workdir(tmp_path, 1)
        assert d.exists()
        assert d.name == "scenario-1"


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


class TestVerdictConstants:
    def test_verdict_values(self):
        assert VERDICT_PASS == "PASS"
        assert VERDICT_NEEDS_WORK == "NEEDS_WORK"
        assert VERDICT_INPUT_REQUIRED == "INPUT_REQUIRED"
