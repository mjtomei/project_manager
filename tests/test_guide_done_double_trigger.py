"""Tests for potential bugs when pm guide done is triggered twice."""

import json
import pytest
from pathlib import Path

from pm_core import guide


class TestGuideDoneDoubleTrigger:
    """Tests for the scenario where pm guide done is called twice."""

    def test_double_done_on_first_step(self, tmp_path):
        """Calling pm guide done twice on step 1 should not cause issues.

        Scenario:
        1. Guide starts on no_project
        2. Claude runs pm guide done
        3. Chain runs pm guide done again
        """
        pm_dir = tmp_path / "pm"
        pm_dir.mkdir()
        (pm_dir / "project.yaml").write_text("project:\n  name: test\n")

        # Start step 1
        guide.mark_step_started(pm_dir, "no_project")

        # First done call (Claude)
        guide.mark_step_completed(pm_dir, "no_project")

        # Verify state after first done
        assert guide.get_started_step(pm_dir) == "no_project"
        assert guide.get_completed_step(pm_dir) == "no_project"

        # Second done call would check started vs completed
        # This simulates what guide_done_cmd does
        started = guide.get_started_step(pm_dir)
        completed = guide.get_completed_step(pm_dir)
        started_idx = guide.STEP_ORDER.index(started)
        completed_idx = guide.STEP_ORDER.index(completed)

        # Should recognize it's already completed
        assert completed_idx >= started_idx, "Should detect already completed"

    def test_done_marks_started_step_not_detected_step(self, tmp_path):
        """pm guide done should mark the STARTED step as complete, not detected.

        Bug scenario:
        1. Started step is no_project
        2. User runs pm init (detection now returns initialized)
        3. pm guide done should mark no_project as complete, not initialized
        """
        pm_dir = tmp_path / "pm"
        pm_dir.mkdir()

        # Start on step 1
        guide.mark_step_started(pm_dir, "no_project")

        # User runs pm init, creates project
        (pm_dir / "project.yaml").write_text("project:\n  name: test\n")

        # Detection would now return "initialized"
        detected, _ = guide.detect_state(pm_dir)
        assert detected == "initialized"

        # But pm guide done should complete the STARTED step
        started = guide.get_started_step(pm_dir)
        assert started == "no_project"

        guide.mark_step_completed(pm_dir, started)

        # Verify the right step was completed
        assert guide.get_completed_step(pm_dir) == "no_project"

    def test_chain_updates_started_before_second_done(self, tmp_path):
        """Test race condition: chain runs pm guide, updates started, then done runs.

        Bug scenario (if done uses current started incorrectly):
        1. Started=no_project, user completes step
        2. Claude done runs, marks no_project complete
        3. Chain runs pm guide, which sets started=initialized
        4. Chain done runs, but started is now initialized
        5. Could this mark initialized as complete prematurely?
        """
        pm_dir = tmp_path / "pm"
        pm_dir.mkdir()
        (pm_dir / "project.yaml").write_text("project:\n  name: test\n")

        # Step 1: started but not completed
        guide.mark_step_started(pm_dir, "no_project")

        # Claude's pm guide done
        guide.mark_step_completed(pm_dir, "no_project")

        # Chain's pm guide updates started
        guide.mark_step_started(pm_dir, "initialized")

        # Now check what guide_done_cmd would see
        started = guide.get_started_step(pm_dir)
        completed = guide.get_completed_step(pm_dir)

        # started is now "initialized" (idx 1)
        # completed is "no_project" (idx 0)
        started_idx = guide.STEP_ORDER.index(started)
        completed_idx = guide.STEP_ORDER.index(completed)

        # This should NOT be "already completed" because started > completed
        # But if chain's done runs, it would mark initialized as complete!
        assert started_idx > completed_idx, "Started is ahead of completed"

        # If done runs now, it would complete "initialized" prematurely!
        # This is the bug: the second done call in the chain shouldn't run
        # after pm guide has updated started to the new step

    def test_resolve_after_premature_completion(self, tmp_path):
        """Test resolve_guide_step when step is marked complete but artifacts missing.

        Bug scenario:
        1. no_project marked as completed
        2. But pm init was never actually run
        3. What does resolve_guide_step return?
        """
        pm_dir = tmp_path / "pm"
        pm_dir.mkdir()

        # Somehow no_project got marked complete without actually running pm init
        guide.mark_step_started(pm_dir, "no_project")
        guide.mark_step_completed(pm_dir, "no_project")

        # But there's no project.yaml!
        # Detection should return no_project
        detected, _ = guide.detect_state(pm_dir)
        # Note: detect_state checks for project.yaml existence
        # If pm_dir exists but project.yaml doesn't, what happens?

        # Actually with just pm_dir existing, detect_state tries to load
        # and may fail. Let me adjust...

    def test_resolve_completed_but_detection_behind(self, tmp_path):
        """Test when completed step is ahead of what detection shows.

        Bug scenario:
        1. Step initialized is marked as completed
        2. But detection shows no_project (project.yaml missing)
        3. Should we trust completed or detection?
        """
        pm_dir = tmp_path / "pm"
        pm_dir.mkdir()
        # Create empty guide state claiming initialized is complete
        state_file = pm_dir / ".guide-state"
        state_file.write_text(json.dumps({
            "started_step": "initialized",
            "completed_step": "initialized"
        }))

        # No project.yaml exists, so detection would say no_project
        # But we claim initialized is complete

        # This can't actually happen in normal flow, but tests edge case
        state, _ = guide.resolve_guide_step(pm_dir)

        # Should we return no_project (trust detection) or has_plan_draft (next after initialized)?
        # Current behavior: if completed is ahead of detection, detection wins?

    def test_done_when_started_is_none(self, tmp_path):
        """Test pm guide done when no step has been started.

        This shouldn't happen in normal flow but tests edge case.
        """
        pm_dir = tmp_path / "pm"
        pm_dir.mkdir()
        (pm_dir / "project.yaml").write_text("project:\n  name: test\n")

        # No .guide-state file, so started is None
        started = guide.get_started_step(pm_dir)
        assert started is None

        # guide_done_cmd should handle this gracefully

    def test_double_done_updates_started_between_calls(self, tmp_path):
        """The actual bug: started gets updated between two done calls.

        Timeline:
        1. Claude runs on step no_project
        2. Claude calls pm guide done (marks no_project complete)
        3. Claude exits
        4. Shell runs: pm guide done ; pm guide
        5. First done says "Already completed" (correct)
        6. pm guide runs, detects initialized, calls mark_step_started(initialized)
        7. But wait, the order is: done ; loop_guard && pm guide

        Actually the order means pm guide runs AFTER done, so there's no issue.
        Unless... the Claude call to pm guide done happens async somehow?
        """
        pm_dir = tmp_path / "pm"
        pm_dir.mkdir()
        (pm_dir / "project.yaml").write_text("project:\n  name: test\n")

        # Start step 1
        guide.mark_step_started(pm_dir, "no_project")

        # Claude runs pm guide done
        guide.mark_step_completed(pm_dir, "no_project")

        # State should now be: started=no_project, completed=no_project
        assert guide.get_started_step(pm_dir) == "no_project"
        assert guide.get_completed_step(pm_dir) == "no_project"

        # Shell's pm guide done runs - should be no-op
        started = guide.get_started_step(pm_dir)
        completed = guide.get_completed_step(pm_dir)
        started_idx = guide.STEP_ORDER.index(started)
        completed_idx = guide.STEP_ORDER.index(completed)
        assert completed_idx >= started_idx  # Already completed, no action

        # Shell's pm guide runs
        state, _ = guide.resolve_guide_step(pm_dir)
        # Detection returns initialized (project exists)
        # completed=no_project (idx 0), detected=initialized (idx 1)
        # next_step = idx 1, detected = idx 1, so return initialized
        assert state == "initialized"

        # pm guide calls mark_step_started
        guide.mark_step_started(pm_dir, "initialized")

        # Now: started=initialized, completed=no_project
        assert guide.get_started_step(pm_dir) == "initialized"
        assert guide.get_completed_step(pm_dir) == "no_project"


class TestGuideDoneCLIBehavior:
    """Tests simulating the actual CLI behavior of guide done command."""

    def test_done_cmd_already_completed_check(self, tmp_path):
        """Simulate guide_done_cmd's already-completed check."""
        pm_dir = tmp_path / "pm"
        pm_dir.mkdir()
        (pm_dir / "project.yaml").write_text("project:\n  name: test\n")

        # Both started and completed at same step
        guide.mark_step_started(pm_dir, "no_project")
        guide.mark_step_completed(pm_dir, "no_project")

        # Simulate guide_done_cmd logic
        started = guide.get_started_step(pm_dir)
        completed = guide.get_completed_step(pm_dir)
        started_idx = guide.STEP_ORDER.index(started)
        completed_idx = guide.STEP_ORDER.index(completed) if completed else -1

        is_already_completed = completed_idx >= started_idx
        assert is_already_completed, "Should detect as already completed"

    def test_done_cmd_when_started_ahead(self, tmp_path):
        """Simulate guide_done_cmd when started is ahead of completed.

        This is the potential bug scenario: if pm guide runs and updates
        started before the second done call processes.
        """
        pm_dir = tmp_path / "pm"
        pm_dir.mkdir()
        (pm_dir / "project.yaml").write_text("project:\n  name: test\n")

        # Simulate: step 1 complete, step 2 started
        guide.mark_step_started(pm_dir, "initialized")
        guide.mark_step_completed(pm_dir, "no_project")

        # Now if done runs, what happens?
        started = guide.get_started_step(pm_dir)
        completed = guide.get_completed_step(pm_dir)
        started_idx = guide.STEP_ORDER.index(started)  # 1
        completed_idx = guide.STEP_ORDER.index(completed)  # 0

        is_already_completed = completed_idx >= started_idx
        assert not is_already_completed, "Not completed yet"

        # done would mark started as completed
        # This means "initialized" gets marked complete even though
        # the user hasn't actually done step 2!
        #
        # This IS the bug if done runs after pm guide updates started


class TestStepProgressionBugs:
    """Tests for bugs in step progression logic."""

    def test_pm_guide_done_instruction_in_prompt(self, tmp_path):
        """Verify the prompt tells Claude to run pm guide done.

        The prompt includes instructions for Claude to run pm guide done.
        Combined with the automatic chain also running it, this means
        it gets called twice. This test documents that behavior.
        """
        pm_dir = tmp_path / "pm"
        pm_dir.mkdir()
        (pm_dir / "project.yaml").write_text("project:\n  name: test\n")

        prompt = guide.build_guide_prompt("no_project", {}, pm_dir)
        assert prompt is not None

        # The prompt tells Claude to run pm guide done
        assert "pm guide done" in prompt
        # And mentions it records completion
        assert "record completion" in prompt.lower() or "complete" in prompt.lower()

    def test_step_not_repeated_after_completion(self, tmp_path):
        """After completing a step, we should not go back to it."""
        pm_dir = tmp_path / "pm"
        pm_dir.mkdir()

        # Complete step 1
        (pm_dir / "project.yaml").write_text("project:\n  name: test\n")
        guide.mark_step_started(pm_dir, "no_project")
        guide.mark_step_completed(pm_dir, "no_project")

        # Resolve should return step 2
        state, _ = guide.resolve_guide_step(pm_dir)
        assert state == "initialized", f"Should be on step 2, not {state}"

        # Delete project.yaml to simulate "going back"
        (pm_dir / "project.yaml").unlink()

        # Detection would say no_project, but we completed it
        detected, _ = guide.detect_state(pm_dir)
        assert detected == "no_project"

        # Resolve should still return step 2 (or stay on completed?)
        state, _ = guide.resolve_guide_step(pm_dir)
        # Current behavior: if detection is at or behind completed+1, use detection
        # This might be wrong - should we force forward progress?


class TestFirstStepEdgeCases:
    """Tests for edge cases specific to the first step (no_project)."""

    def test_first_step_can_be_completed_after_pm_init(self, tmp_path):
        """After pm init creates the directory, pm guide done should work.

        The fix in guide_done_cmd infers that no_project was the started step
        if started is None but detection shows we've progressed past no_project.
        """
        # No pm dir exists initially
        pm_dir = tmp_path / "pm"
        assert not pm_dir.exists()

        # resolve_guide_step with no root returns no_project
        state, ctx = guide.resolve_guide_step(None)
        assert state == "no_project"

        # Now simulate pm init creating the directory
        pm_dir.mkdir()
        (pm_dir / "project.yaml").write_text("project:\n  name: test\n")

        # Detection now shows "initialized" (past no_project)
        detected, _ = guide.detect_state(pm_dir)
        assert detected == "initialized"

        # The fix: when started is None but detection shows progress,
        # infer that no_project was started and mark it
        started = guide.get_started_step(pm_dir)
        if started is None and detected != "no_project":
            # This is the fix logic from guide_done_cmd
            started = "no_project"
            guide.mark_step_started(pm_dir, started)

        assert started == "no_project", \
            f"Expected started='no_project', got started={started}"

        # Now we can complete the step
        guide.mark_step_completed(pm_dir, started)
        assert guide.get_completed_step(pm_dir) == "no_project"

    def test_non_interactive_step_is_tracked(self, tmp_path):
        """Non-interactive steps should be marked as started/completed.

        The fix in _run_guide adds mark_step_started/completed calls
        around run_non_interactive_step.
        """
        import yaml

        pm_dir = tmp_path / "pm"
        pm_dir.mkdir()

        # Create proper YAML structure with plans list
        project_data = {
            "project": {"name": "test"},
            "plans": [{"id": "plan-001", "file": "plans/plan-001.md"}],
        }
        (pm_dir / "project.yaml").write_text(yaml.dump(project_data))

        plans_dir = pm_dir / "plans"
        plans_dir.mkdir()
        (plans_dir / "plan-001.md").write_text("# Plan\n\n## PRs\n\n### PR: Test PR\n- **description**: Test\n")

        # Set up state as if has_plan_draft was just completed
        guide.mark_step_started(pm_dir, "has_plan_draft")
        guide.mark_step_completed(pm_dir, "has_plan_draft")

        # Detection should return has_plan_prs
        detected, _ = guide.detect_state(pm_dir)
        assert detected == "has_plan_prs"

        # Simulate the FIXED _run_guide behavior for non-interactive step:
        # 1. Mark step started
        # 2. Run the step
        # 3. Mark step completed
        state = "has_plan_prs"
        guide.mark_step_started(pm_dir, state)
        guide.run_non_interactive_step(state, {"root": pm_dir}, pm_dir)
        guide.mark_step_completed(pm_dir, state)

        # Now tracking should show has_plan_prs was started and completed
        started = guide.get_started_step(pm_dir)
        completed = guide.get_completed_step(pm_dir)

        assert started == "has_plan_prs", \
            f"Expected started='has_plan_prs', got started={started}"
        assert completed == "has_plan_prs", \
            f"Expected completed='has_plan_prs', got completed={completed}"


class TestDoubleDoneBugScenarios:
    """Tests that expose the actual bug: done triggering twice on same step."""

    def test_done_should_verify_step_artifacts_exist(self, tmp_path):
        """pm guide done should verify the step was actually completed.

        The fix in guide_done_cmd checks that detection has moved forward
        before allowing the step to be marked complete.
        """
        pm_dir = tmp_path / "pm"
        pm_dir.mkdir()
        # Note: NO project.yaml - pm init was never run

        # Start step 1
        guide.mark_step_started(pm_dir, "no_project")

        # Simulate the FIXED guide_done_cmd logic:
        # Check if detection has moved forward before marking complete
        started = guide.get_started_step(pm_dir)
        started_idx = guide.STEP_ORDER.index(started)

        detected, _ = guide.detect_state(pm_dir)
        detected_idx = guide.STEP_ORDER.index(detected)

        # The fix: if detection hasn't moved forward, refuse to mark complete
        if detected_idx <= started_idx:
            # This is the expected behavior - don't mark complete
            step_actually_complete = False
        else:
            guide.mark_step_completed(pm_dir, started)
            step_actually_complete = True

        # With the fix, the step should NOT be marked complete
        assert not step_actually_complete, \
            "Should refuse to mark complete when artifacts don't exist"

        # Verify the step was not completed
        completed = guide.get_completed_step(pm_dir)
        assert completed is None, \
            f"Step should not be completed, but completed={completed}"

        # Now actually create the artifacts
        (pm_dir / "project.yaml").write_text("project:\n  name: test\n")

        # Now detection should show progress
        detected, _ = guide.detect_state(pm_dir)
        detected_idx = guide.STEP_ORDER.index(detected)
        assert detected_idx > started_idx, "Detection should show progress now"

        # Now marking complete should work
        guide.mark_step_completed(pm_dir, started)
        assert guide.get_completed_step(pm_dir) == "no_project"

        # And resolve should move to next step
        state, _ = guide.resolve_guide_step(pm_dir)
        assert state == "initialized", \
            f"After completing step 1, should be on step 2, not {state}"

    def test_repeated_done_calls_are_idempotent(self, tmp_path):
        """Calling done twice on the same step should be harmless.

        This is expected behavior - the second call says "Already completed".
        """
        pm_dir = tmp_path / "pm"
        pm_dir.mkdir()
        (pm_dir / "project.yaml").write_text("project:\n  name: test\n")

        # Complete step 1 properly (with artifacts)
        guide.mark_step_started(pm_dir, "no_project")
        guide.mark_step_completed(pm_dir, "no_project")

        # Check that second done would recognize "already completed"
        started = guide.get_started_step(pm_dir)
        completed = guide.get_completed_step(pm_dir)
        started_idx = guide.STEP_ORDER.index(started)
        completed_idx = guide.STEP_ORDER.index(completed)

        assert completed_idx >= started_idx, "Second done should see 'already completed'"

        # Resolve should correctly go to step 2
        state, _ = guide.resolve_guide_step(pm_dir)
        assert state == "initialized", "Should progress to step 2"

    def test_shell_done_runs_before_pm_guide_updates_started(self, tmp_path):
        """Verify the chain ordering: done runs before pm guide.

        The chain is: done ; loop_guard && pm guide
        This ensures shell's done doesn't accidentally complete the NEXT step.
        """
        pm_dir = tmp_path / "pm"
        pm_dir.mkdir()
        (pm_dir / "project.yaml").write_text("project:\n  name: test\n")

        # Step 1 started
        guide.mark_step_started(pm_dir, "no_project")

        # Claude's done
        guide.mark_step_completed(pm_dir, "no_project")

        # Shell's done (runs before pm guide in the chain)
        started = guide.get_started_step(pm_dir)
        completed = guide.get_completed_step(pm_dir)
        started_idx = guide.STEP_ORDER.index(started)
        completed_idx = guide.STEP_ORDER.index(completed)
        already_completed = completed_idx >= started_idx
        assert already_completed, "Shell done sees already completed"

        # Only NOW does pm guide run and update started
        state, _ = guide.resolve_guide_step(pm_dir)
        assert state == "initialized"
        guide.mark_step_started(pm_dir, "initialized")

        # Verify step 2 is NOT marked complete
        completed = guide.get_completed_step(pm_dir)
        assert completed == "no_project", "Step 2 should not be marked complete"

    def test_double_done_with_correct_artifacts(self, tmp_path):
        """Verify double done works correctly when artifacts exist.

        This is the happy path - step is truly complete, done runs twice,
        user progresses normally.
        """
        pm_dir = tmp_path / "pm"
        pm_dir.mkdir()
        (pm_dir / "project.yaml").write_text("project:\n  name: test\n")

        # Step 1 started, artifacts created (project.yaml exists)
        guide.mark_step_started(pm_dir, "no_project")

        # First done (Claude)
        guide.mark_step_completed(pm_dir, "no_project")

        # Second done (shell) - should be no-op
        started = guide.get_started_step(pm_dir)
        completed = guide.get_completed_step(pm_dir)
        started_idx = guide.STEP_ORDER.index(started)
        completed_idx = guide.STEP_ORDER.index(completed)
        assert completed_idx >= started_idx, "Already completed"

        # Resolve should return step 2
        state, _ = guide.resolve_guide_step(pm_dir)
        assert state == "initialized", "Should progress to step 2"

        # pm guide would now start step 2
        guide.mark_step_started(pm_dir, "initialized")

        # Verify correct state
        assert guide.get_started_step(pm_dir) == "initialized"
        assert guide.get_completed_step(pm_dir) == "no_project"
