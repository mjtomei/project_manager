"""Tests for guide step resolution in pm_core.guide."""

import json
from pathlib import Path

import pytest

from pm_core.guide import (
    resolve_guide_step,
    detect_state,
    get_completed_step,
    get_started_step,
    mark_step_completed,
    mark_step_started,
    GUIDE_STATE_FILE,
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


class TestGetStartedStep:
    def test_returns_none_when_no_state_file(self, tmp_pm_root):
        assert get_started_step(tmp_pm_root) is None

    def test_returns_started_step(self, tmp_pm_root):
        state_file = tmp_pm_root / GUIDE_STATE_FILE
        state_file.write_text(json.dumps({"started_step": "no_project"}))
        assert get_started_step(tmp_pm_root) == "no_project"

    def test_returns_none_on_corrupted_json(self, tmp_pm_root):
        state_file = tmp_pm_root / GUIDE_STATE_FILE
        state_file.write_text("not json")
        assert get_started_step(tmp_pm_root) is None


class TestGetCompletedStep:
    def test_returns_none_when_no_state_file(self, tmp_pm_root):
        assert get_completed_step(tmp_pm_root) is None

    def test_returns_completed_step(self, tmp_pm_root):
        state_file = tmp_pm_root / GUIDE_STATE_FILE
        state_file.write_text(json.dumps({"completed_step": "initialized"}))
        assert get_completed_step(tmp_pm_root) == "initialized"


class TestMarkStepStarted:
    def test_creates_state_file(self, tmp_pm_root):
        mark_step_started(tmp_pm_root, "no_project")
        state_file = tmp_pm_root / GUIDE_STATE_FILE
        assert state_file.exists()
        data = json.loads(state_file.read_text())
        assert data["started_step"] == "no_project"

    def test_preserves_completed_step(self, tmp_pm_root):
        state_file = tmp_pm_root / GUIDE_STATE_FILE
        state_file.write_text(json.dumps({"completed_step": "no_project"}))

        mark_step_started(tmp_pm_root, "initialized")

        data = json.loads(state_file.read_text())
        assert data["started_step"] == "initialized"
        assert data["completed_step"] == "no_project"


class TestMarkStepCompleted:
    def test_creates_state_file(self, tmp_pm_root):
        mark_step_completed(tmp_pm_root, "no_project")
        state_file = tmp_pm_root / GUIDE_STATE_FILE
        assert state_file.exists()
        data = json.loads(state_file.read_text())
        assert data["completed_step"] == "no_project"

    def test_adds_to_gitignore(self, tmp_pm_root):
        mark_step_completed(tmp_pm_root, "no_project")
        gitignore = tmp_pm_root / ".gitignore"
        content = gitignore.read_text()
        assert GUIDE_STATE_FILE in content
        assert ".pm-sessions.json" in content


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

    def test_needs_deps_review_when_prs_exist_without_plans(self, tmp_pm_root):
        """PRs imported during init (no plans) should skip to deps review."""
        (tmp_pm_root / "project.yaml").write_text(
            "project:\n  name: test\n  repo: /tmp/test\n  base_branch: master\n"
            "plans: []\n"
            "prs:\n"
            "  - id: pr-001\n    title: First PR\n    status: pending\n"
            "  - id: pr-002\n    title: Second PR\n    status: pending\n"
        )
        state, ctx = detect_state(tmp_pm_root)
        assert state == "needs_deps_review"

    def test_ready_to_work_when_prs_without_plans_deps_reviewed(self, tmp_pm_root):
        """PRs with deps already reviewed should reach ready_to_work."""
        (tmp_pm_root / "project.yaml").write_text(
            "project:\n  name: test\n  repo: /tmp/test\n  base_branch: master\n"
            "  guide_deps_reviewed: true\n"
            "plans: []\n"
            "prs:\n"
            "  - id: pr-001\n    title: First PR\n    status: pending\n"
        )
        state, ctx = detect_state(tmp_pm_root)
        assert state == "ready_to_work"


class TestResolveGuideStep:
    def test_returns_detected_when_root_is_none(self):
        state, ctx = resolve_guide_step(None)
        assert state == "no_project"

    def test_returns_detected_when_no_tracking(self, tmp_pm_root):
        # No .guide-state file
        state, ctx = resolve_guide_step(tmp_pm_root)
        assert state == "initialized"  # detected from project.yaml

    def test_stays_on_started_step_when_detection_jumps_ahead(self, pm_root_with_plan):
        """If started on step 1 but artifacts suggest step 3, stay on step 1."""
        # Mark step 1 as started (but not completed)
        mark_step_started(pm_root_with_plan, "no_project")

        # Detection would return has_plan_draft (step 3) based on artifacts
        detected, _ = detect_state(pm_root_with_plan)
        assert detected == "has_plan_draft"

        # But resolution should stay on started step
        state, ctx = resolve_guide_step(pm_root_with_plan)
        assert state == "no_project"

    def test_allows_forward_when_detection_matches_started(self, tmp_pm_root):
        """If detection matches started step, use it."""
        mark_step_started(tmp_pm_root, "initialized")

        state, ctx = resolve_guide_step(tmp_pm_root)
        assert state == "initialized"

    def test_stays_on_next_step_after_completed(self, pm_root_with_plan):
        """After completing step 1, stay on step 2 even if artifacts suggest step 3."""
        mark_step_completed(pm_root_with_plan, "no_project")

        # Detection returns has_plan_draft (step 3)
        detected, _ = detect_state(pm_root_with_plan)
        assert detected == "has_plan_draft"

        # Resolution should return step 2 (initialized)
        state, ctx = resolve_guide_step(pm_root_with_plan)
        assert state == "initialized"

    def test_allows_normal_progression(self, pm_root_with_plan):
        """Normal case: completed step N, detection shows step N+1."""
        # Complete step 2 (initialized)
        mark_step_completed(pm_root_with_plan, "initialized")

        # Detection returns has_plan_draft (step 3) - correct next step
        state, ctx = resolve_guide_step(pm_root_with_plan)
        assert state == "has_plan_draft"

    def test_complex_scenario_started_no_project_detected_has_plan_prs(self, pm_root_with_plan_prs):
        """
        Scenario: User ran pm guide step 1 (no_project), pm init created project + plan,
        then user killed the pane. Artifacts show has_plan_prs but should stay on no_project.
        """
        mark_step_started(pm_root_with_plan_prs, "no_project")

        state, ctx = resolve_guide_step(pm_root_with_plan_prs)
        assert state == "no_project"

    def test_complex_scenario_completed_initialized_detected_needs_deps(self, tmp_pm_root):
        """
        Scenario: Completed through step 2, but detection jumped to step 5.
        Should stay on step 3.
        """
        # Set up project.yaml with PRs loaded (which would trigger needs_deps_review)
        (tmp_pm_root / "project.yaml").write_text(
            "project:\n  name: test\n  repo: /tmp/test\n  base_branch: master\n"
            "plans:\n  - id: plan-001\n    name: Test\n    file: plans/plan-001.md\n    status: draft\n"
            "prs:\n  - id: pr-001\n    title: First PR\n    status: pending\n"
        )
        plans_dir = tmp_pm_root / "plans"
        plans_dir.mkdir(exist_ok=True)
        (plans_dir / "plan-001.md").write_text("# Plan\n\n## PRs\n\n### PR: First PR\n")

        mark_step_completed(tmp_pm_root, "initialized")

        # Detection would show needs_deps_review (step 5)
        detected, _ = detect_state(tmp_pm_root)
        assert detected == "needs_deps_review"

        # Resolution should show has_plan_draft (step 3, next after initialized)
        state, ctx = resolve_guide_step(tmp_pm_root)
        assert state == "has_plan_draft"


class TestStepOrder:
    def test_step_order_is_correct(self):
        """Verify the expected step order."""
        assert STEP_ORDER == [
            "no_project",
            "initialized",
            "has_plan_draft",
            "has_plan_prs",
            "needs_deps_review",
            "ready_to_work",
            "all_in_progress",
            "all_done",
        ]

    def test_all_steps_have_index(self):
        """All steps should be findable in STEP_ORDER."""
        for step in STEP_ORDER:
            assert STEP_ORDER.index(step) >= 0
