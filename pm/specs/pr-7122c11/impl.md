# Implementation Spec: Refine Watcher INPUT_REQUIRED to Distinguish Project-wide vs Branch-specific Issues

## 1. Requirements

### 1.1 Core Behavior Change in `generate_watcher_prompt`
**File**: `pm_core/prompt_gen.py`, function `generate_watcher_prompt` (~lines 512–729)

The watcher prompt currently says:
> Use the **INPUT_REQUIRED** verdict for anything you can't figure out yourself.

This must be refined to distinguish two categories:

**A. Project-wide blockers (use INPUT_REQUIRED):**
- Broken base branch affecting all downstream work
- Plan contradictions or fundamental architectural issues
- Infrastructure failures (e.g., git remote unreachable, disk full)
- Issues on an `in_progress` branch that has no active review loop and is genuinely stuck

**B. Branch-specific blockers already handled (use READY instead):**
- A branch currently `in_review` whose review loop has emitted `INPUT_REQUIRED`
- The review loop already pauses that branch and notifies the user; the watcher adding its own `INPUT_REQUIRED` would block all other branches unnecessarily

### 1.2 Guidance for Checking Review Loop State
The watcher must be told how to determine whether a branch is already paused by its review loop's `INPUT_REQUIRED`. At runtime the watcher can:
- Inspect the relevant tmux panes for review loop output ending in `INPUT_REQUIRED`
- Use `pm pr list` to see which PRs are `in_review`; then check whether those review panes are waiting for human input

### 1.3 Refined "Abnormal States" List
The existing "Abnormal states that DO need attention" list in the prompt (lines 638–643) conflates states that should trigger `INPUT_REQUIRED` with states the watcher should just note. It must be updated to:
- Keep: `in_progress` with dead pane, broken dep chains, implementation crashes
- Add clarification: `in_review` with a review loop `INPUT_REQUIRED` is **not** a watcher `INPUT_REQUIRED` — it is already handled

### 1.4 Refined Iteration Protocol / Verdict Description
The verdict description section (lines 723–725) must be updated to clarify:
- `INPUT_REQUIRED` is for **project-wide** blockers or branches with **no active review loop handling the issue**
- `READY` is appropriate even when some branches are individually paused by their own review loops

### 1.5 Associated Documentation
Per the task description, any references to watcher INPUT_REQUIRED behavior in:
- The `generate_watcher_prompt` docstring (`pm_core/prompt_gen.py` line ~516)
- The plan file `pm/plans/watchers.md` manual testing notes (line 173)

must be updated to reflect the refined behavior.

---

## 2. Implicit Requirements

- **No changes to verdict parsing or TUI logic**: The watcher still emits `READY` or `INPUT_REQUIRED`; the distinction is only in *when* the watcher chooses each. No changes to `watcher_ui.py`, `watcher_base.py`, `review_loop_ui.py`, or test verdict-parsing code are needed.
- **No new data passed to the prompt**: The watcher does not receive structured state about which review loops are `input_required`. It must infer this by inspecting tmux panes, which it is already instructed to do in Section 1 of its responsibilities. The guidance tells it *what to look for*, not *how to do the lookup* (it already knows how to use `tmux capture-pane`).
- **Backward-compatible prompt**: The new guidance is purely additive/clarifying. Existing watcher behavior for project-wide issues is unchanged.
- **Section numbering consistency**: The watcher prompt uses `### N.` headings; new guidance should be inserted without renumbering unrelated sections or restructuring the document.

---

## 3. Ambiguities

### 3.1 Where to insert the new guidance
**Ambiguity**: The task says "around lines 600–675", which spans the lifecycle stages, normal/abnormal states, and the five responsibility sections. The most logical insertion point is the "### 3. Surface Issues Needing Human Input" section (currently a one-liner at line 655–656), expanding it with the project-wide vs branch-specific distinction.

**Proposed resolution**: Expand Section 3 in the prompt with the distinction. Also update the "Abnormal states" list and the Iteration Protocol verdict description to be consistent.

### 3.2 How specific to be about detecting review loop INPUT_REQUIRED
**Ambiguity**: Should the watcher be given a concrete `tmux capture-pane` recipe for detecting a review loop's `INPUT_REQUIRED`, or just the conceptual guidance?

**Proposed resolution**: Give conceptual guidance — "if the review pane for a branch ends with INPUT_REQUIRED, the review loop is already pausing it". The watcher already has instructions on how to use `tmux capture-pane` and it is a language model; it does not need a precise shell recipe.

### 3.3 What about QA loop INPUT_REQUIRED?
**Ambiguity**: The task only mentions review loops, but QA loops can also emit `INPUT_REQUIRED` (per `pm_core/cli/qa.py`).

**Proposed resolution**: Apply the same logic — if a branch's QA loop has emitted `INPUT_REQUIRED`, the watcher should note it but output `READY`. Include QA loops alongside review loops in the guidance.

### 3.4 Should `in_progress` branches with no review loop ever get watcher INPUT_REQUIRED?
**Ambiguity**: The task says "issues on a branch that is NOT already paused by a review loop (e.g., an `in_progress` implementation that is stuck but has no review loop watching it)" should still trigger `INPUT_REQUIRED`.

**Proposed resolution**: Yes — the prompt should preserve existing guidance that a genuinely stuck `in_progress` branch (idle/dead pane with no review loop, not just the normal 30-second transition window) warrants `INPUT_REQUIRED`.

---

## 4. Edge Cases

### 4.1 Branch transitions during watcher iteration
A branch may be `in_review` with an active INPUT_REQUIRED mid-watcher-iteration but transition to a follow-up verdict before the iteration ends. The guidance should say "at the time of observation" — the watcher should report what it sees, not predict future state.

### 4.2 Multiple branches paused simultaneously
If branches A, B, and C all have review loop `INPUT_REQUIRED`, the watcher should emit `READY` (since each loop is handling its own branch) and note all three in its summary. This is an important case to call out explicitly in the prompt.

### 4.3 Branch stuck in `in_review` with NO active review loop window
If a PR is `in_review` but has no review loop running (e.g., the loop crashed or was never started), this is an abnormal state the watcher should attempt to fix or escalate. This is distinct from "review loop is running but waiting for human input". The prompt already covers "PR in `in_review` with no active review loop" as an abnormal state (line 640) — this edge case does not require a change, but the new guidance should not accidentally suppress it.

### 4.4 docstring update scope
The `generate_watcher_prompt` docstring is brief (lines 516–531). It does not mention INPUT_REQUIRED semantics and does not need updating unless we want to document the behavior explicitly. Given the task says "any references to the watcher's INPUT_REQUIRED behavior in help text, docstrings, or other prompt templates", a brief addition to the docstring is appropriate.
