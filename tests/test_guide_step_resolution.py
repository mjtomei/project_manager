"""Tests for guide state detection in pm_core.guide."""

from pathlib import Path

import pytest

from pm_core.guide import (
    detect_state,
    is_setup_state,
    STEP_ORDER,
)


@pytest.fixture
def tmp_pm_root(tmp_path):
    """Create a minimal PM root with project.yaml."""
    root = tmp_path / "pm"
    root.mkdir()
    (root / "project.yaml").write_text("project:\n  name: test\n  repo: /tmp/test\n  base_branch: master\n")
    return root


@pytest.fixture
def pm_root_with_plan(tmp_pm_root):
    """PM root with a plan file (no PRs section)."""
    plans_dir = tmp_pm_root / "plans"
    plans_dir.mkdir()
    (plans_dir / "plan-001.md").write_text("# Test Plan\n\nSome content.\n")

    # Update project.yaml to include plan
    (tmp_pm_root / "project.yaml").write_text(
        "project:\n  name: test\n  repo: /tmp/test\n  base_branch: master\n"
        "plans:\n  - id: plan-001\n    name: Test Plan\n    file: plans/plan-001.md\n    status: draft\n"
    )
    return tmp_pm_root


@pytest.fixture
def pm_root_with_plan_prs(tmp_pm_root):
    """PM root with a plan file containing ## PRs section."""
    plans_dir = tmp_pm_root / "plans"
    plans_dir.mkdir()
    (plans_dir / "plan-001.md").write_text(
        "# Test Plan\n\n## PRs\n\n### PR: First PR\n- **description**: Do something\n"
    )

    (tmp_pm_root / "project.yaml").write_text(
        "project:\n  name: test\n  repo: /tmp/test\n  base_branch: master\n"
        "plans:\n  - id: plan-001\n    name: Test Plan\n    file: plans/plan-001.md\n    status: draft\n"
    )
    return tmp_pm_root


class TestDetectState:
    def test_no_project_when_root_is_none(self):
        state, ctx = detect_state(None)
        assert state == "no_project"
        assert ctx == {}

    def test_initialized_when_no_plans(self, tmp_pm_root):
        state, ctx = detect_state(tmp_pm_root)
        assert state == "initialized"
        assert "data" in ctx
        assert "root" in ctx

    def test_has_plan_draft_when_plan_exists_without_prs(self, pm_root_with_plan):
        state, ctx = detect_state(pm_root_with_plan)
        assert state == "has_plan_draft"
        assert "plan" in ctx

    def test_has_plan_prs_when_plan_has_prs_section(self, pm_root_with_plan_prs):
        state, ctx = detect_state(pm_root_with_plan_prs)
        assert state == "has_plan_prs"

    def test_ready_to_work_when_prs_exist_without_plans(self, tmp_pm_root):
        """PRs imported during init (no plans) should go straight to ready_to_work."""
        (tmp_pm_root / "project.yaml").write_text(
            "project:\n  name: test\n  repo: /tmp/test\n  base_branch: master\n"
            "plans: []\n"
            "prs:\n"
            "  - id: pr-001\n    title: First PR\n    status: pending\n"
            "  - id: pr-002\n    title: Second PR\n    status: pending\n"
        )
        state, ctx = detect_state(tmp_pm_root)
        assert state == "ready_to_work"


class TestIsSetupState:
    def test_setup_states(self):
        assert is_setup_state("no_project") is True
        assert is_setup_state("initialized") is True
        assert is_setup_state("has_plan_draft") is True
        assert is_setup_state("has_plan_prs") is True

    def test_non_setup_states(self):
        assert is_setup_state("ready_to_work") is False
        assert is_setup_state("all_in_progress") is False
        assert is_setup_state("all_done") is False

    def test_unknown_state(self):
        assert is_setup_state("unknown") is False


class TestStepOrder:
    def test_step_order_is_correct(self):
        """Verify the expected step order."""
        assert STEP_ORDER == [
            "no_project",
            "initialized",
            "has_plan_draft",
            "has_plan_prs",
            "ready_to_work",
            "all_in_progress",
            "all_done",
        ]

    def test_all_steps_have_index(self):
        """All steps should be findable in STEP_ORDER."""
        for step in STEP_ORDER:
            assert STEP_ORDER.index(step) >= 0
