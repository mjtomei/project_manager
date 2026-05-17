# QA Spec: Refine Watcher INPUT_REQUIRED to Distinguish Project-wide vs Branch-specific Issues

## 1. Requirements

### 1.1 Core Behavior: Watcher Prompt Distinguishes Two Categories of INPUT_REQUIRED

The watcher prompt (`pm_core/prompt_gen.py:generate_watcher_prompt`) has been updated to guide the watcher Claude session to distinguish between:

**A. Project-wide blockers (watcher should emit INPUT_REQUIRED):**
- Broken base branch affecting all downstream work
- Plan contradictions or fundamental architectural issues
- Infrastructure failures (git remote unreachable, disk full, etc.)
- An `in_progress` branch genuinely stuck (idle/dead pane for several minutes) with no active review or QA loop handling it

**B. Branch-specific issues already handled by loops (watcher should emit READY):**
- A PR in `in_review` or `qa` whose review/QA loop pane ends with `INPUT_REQUIRED`
- The loop already pauses that branch and notifies the user
- The watcher should note the situation in its summary but NOT escalate to INPUT_REQUIRED
- This applies even when multiple branches are simultaneously paused by their own loops

### 1.2 Prompt Structure Changes

The following sections of the generated watcher prompt were modified:

1. **Docstring** (line ~522-528): Added INPUT_REQUIRED semantics documentation
2. **"States that are handled and do NOT need watcher INPUT_REQUIRED"** block (line ~653-660): New subsection under "Your Responsibilities" listing states the watcher should NOT escalate
3. **Section 3: "Surface Issues Needing Human Input"** (line ~672-692): Expanded from a one-liner to detailed guidance with two sub-lists (project-wide blockers vs branch-specific handled)
4. **Iteration Protocol verdict descriptions** (line ~760-761): Updated READY and INPUT_REQUIRED descriptions to reflect the refined semantics

### 1.3 Documentation Updates

- `pm/plans/watchers.md` line 173: Updated the manual testing note for pr-7122c11 to describe the refined behavior
- `generate_watcher_prompt` docstring: Added INPUT_REQUIRED semantics paragraph

### 1.4 No Code Logic Changes

This PR is purely a prompt engineering change. No changes to:
- Verdict parsing (`watcher_base.py`, `review_loop.py`)
- TUI watcher UI (`watcher_ui.py`)
- Review loop logic (`review_loop.py`, `review_loop_ui.py`)
- Any Python control flow or data structures

The behavioral change is in *how the Claude watcher session decides* which verdict to emit, not in how the system processes those verdicts.

## 2. Setup

### 2.1 Environment
- A working pm installation (`pip install -e .` from the project_manager clone)
- A test project initialized with `pm init` containing multiple PRs with dependencies
- A tmux session created via `pm session`

### 2.2 Test Fixture Requirements
To exercise the watcher's new behavior, the test project needs:
- At least 3-4 PRs with a dependency chain
- Ability to set PR statuses to `in_progress`, `in_review`, `qa` via `project.yaml` editing
- Simulated tmux windows that look like review/QA loop panes (with `INPUT_REQUIRED` at the end)

### 2.3 Prompt Inspection Approach
Since this is a prompt-only change, the primary verification method is:
1. Generate the watcher prompt via `generate_watcher_prompt()` with various project states
2. Verify the prompt text contains the correct guidance
3. For behavioral testing: run the watcher against a project with specific branch states and verify the verdict

## 3. Edge Cases

### 3.1 Multiple Branches Paused Simultaneously
If branches A, B, and C all have review/QA loop `INPUT_REQUIRED`, the watcher should emit READY and note all three in its summary. The prompt explicitly calls this out.

### 3.2 Branch in `in_review` with NO Active Review Loop
A PR that is `in_review` but has no review loop window (loop crashed or never started) is an abnormal state that SHOULD trigger watcher INPUT_REQUIRED. The prompt includes an explicit exception for this case.

### 3.3 Branch Transitions During Watcher Iteration
A branch may transition from `INPUT_REQUIRED` to a follow-up verdict while the watcher is observing. The prompt says "at the time of observation" — the watcher reports what it sees.

### 3.4 `in_progress` Branch Stuck with No Loop
An `in_progress` branch with a dead/idle pane and no review/QA loop should still trigger INPUT_REQUIRED. This is preserved from the original behavior and explicitly listed under project-wide blockers.

### 3.5 QA Loop INPUT_REQUIRED
The prompt treats QA loop `INPUT_REQUIRED` the same as review loop `INPUT_REQUIRED` — both are branch-specific and already handled. The watcher should emit READY for both.

### 3.6 Auto-Start Scope Interaction
When `auto_start_target` is set, the watcher only manages PRs in the target's dependency fan-in. The new INPUT_REQUIRED guidance applies within that scope — unmanaged PRs are already excluded from corrective action.

## 4. Pass/Fail Criteria

### 4.1 Prompt Content (Static Verification)
**Pass** if the generated watcher prompt:
- Contains the "States that are handled and do NOT need watcher INPUT_REQUIRED" section
- Contains the expanded Section 3 with "Use INPUT_REQUIRED for project-wide blockers" and "Use READY (not INPUT_REQUIRED) when a branch-specific issue is already handled"
- Contains updated READY verdict description mentioning review/QA loops
- Contains updated INPUT_REQUIRED verdict description mentioning "project-wide blocker"
- Contains the exception clause about `in_review` with no active review loop window
- Docstring includes INPUT_REQUIRED semantics paragraph

**Fail** if any of the above sections are missing, inconsistent, or contradict each other.

### 4.2 Documentation Consistency
**Pass** if `pm/plans/watchers.md` line 173 matches the refined behavior description.
**Fail** if the plan file still has the old description.

### 4.3 Behavioral (Manual/Live Testing)
**Pass** if:
- Watcher emits READY when observing a project where one branch's review loop has `INPUT_REQUIRED` but other branches are progressing normally
- Watcher emits INPUT_REQUIRED for a genuinely stuck `in_progress` branch with no active loop
- Watcher emits INPUT_REQUIRED for a project-wide blocker (e.g., broken base branch)
- Watcher's summary mentions the paused branch even when emitting READY

**Fail** if:
- Watcher emits INPUT_REQUIRED solely because a branch's review/QA loop is waiting for input
- Watcher fails to mention the paused branch in its summary when emitting READY
- Watcher emits READY when a project-wide blocker is present

## 5. Ambiguities

### 5.1 "Ends with INPUT_REQUIRED" — How Strict?
**Ambiguity**: Does the review/QA loop pane need to literally end with the exact string "INPUT_REQUIRED" on the last line, or is it sufficient for `INPUT_REQUIRED` to appear in the last few lines of output?

**Resolution**: The prompt says "last meaningful output ends with `INPUT_REQUIRED`". In practice, the review loop emits `INPUT_REQUIRED` as the last verdict keyword on its own line (per the review loop protocol). The watcher captures the pane with `tmux capture-pane` which may have trailing blank lines. The guidance is conceptual — the watcher Claude session can interpret "ends with" reasonably. No exact string matching is required.

### 5.2 QA Loop Parity
**Ambiguity**: The PR description only mentions review loops, but the implementation also covers QA loops.

**Resolution**: The implementation correctly extends the logic to QA loops. The spec from `impl.md` explicitly resolved this (ambiguity 3.3). Both review and QA loop INPUT_REQUIRED are treated the same way.

### 5.3 Behavioral Testing Feasibility
**Ambiguity**: Since this is a prompt-only change, behavioral testing requires running the watcher with a real Claude session. Can we meaningfully test the behavior without incurring API costs?

**Resolution**: Static prompt verification (checking the generated prompt text) is the primary testing method. Behavioral testing is manual — set up a multi-branch project, simulate specific states, run the watcher, and observe its verdict. The TUI manual test instruction applies for setting up the environment.

## 6. Mocks

### 6.1 External Dependencies

**Claude API / watcher session**: The watcher prompt is sent to a Claude session that runs in a tmux pane. For static prompt verification, no Claude session is needed — we call `generate_watcher_prompt()` directly and inspect the output string. For behavioral testing, a real Claude session is required (the watcher's verdict decision is made by the LLM, not by code).

**tmux**: For static prompt verification, tmux is not needed. For behavioral/manual testing, tmux is required and should be real (not mocked) since the watcher inspects live panes.

**git**: Not directly relevant to this PR's changes. The watcher prompt mentions git operations but the changes don't modify any git-related behavior.

### 6.2 Mock Strategy
For automated QA scenarios:
- **Unmocked**: `generate_watcher_prompt()` function call — this is pure Python string generation with no external dependencies
- **Unmocked**: File reads of `pm/plans/watchers.md` for documentation verification
- **Not needed**: Claude API, tmux, git — static prompt verification doesn't require them

For manual behavioral testing (not automatable):
- **Unmocked**: Everything — real tmux session, real Claude session, real project state
