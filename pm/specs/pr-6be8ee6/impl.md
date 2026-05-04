# Implementation Spec — pr-6be8ee6

The bug-fix flow prompt was letting sessions write speculative fixes when
the bug was visual/TUI. Tighten the prompt itself — generically, no
project-specific paths, no detection logic.

## Requirements

1. **"Reproduce on pre-fix code" gate in `_BUG_FIX_FLOW_BLOCK`**
   (`pm_core/prompt_gen.py:20`) — before the Fix step, instruct the session
   to verify the reproduction actually fails on pre-fix code (`git stash`
   or `git checkout <parent> -- <files>`); if not, stop and ask the user.

2. **Strengthen the "manual repro" wording in the Reproduce step** —
   make explicit that a manual repro is a concrete sequence of steps that
   produces the symptom, not a theory about internal mechanics. This is
   what was missing on pr-177dec0: two sessions wrote fixes based on
   plausible-but-unverified theories about Textual reactives.

## Non-Requirements (explicitly cut)

- No detection helper for whether a PR touches the TUI. The prompt is
  generic.
- No reference to `pm/qa/instructions/tui-manual-test.md`. That file
  only exists in the project_manager repo; the prompt has to work for
  any project that uses pm.
- No new conditional block. One generic edit to `_BUG_FIX_FLOW_BLOCK`.

## Implicit Requirements

- Existing tests in `tests/test_bug_fix_flow_prompts.py` keep passing
  (substring assertions on `"Bug Fix Flow"`, `"Reproduce"`,
  `"Reconcile"`, `"confirmed-overlap"`).
- Existing references in the block to `FakeClaudeSession` /
  `pm/qa/regression/` stay (they predate this PR; the user's "no
  project-internal paths" rule was about my new additions).

## Edge Cases

- **Non-bug PRs** — no bug-flow block, unchanged.
- **Sessions on a fresh branch with no parent commits to stash from** —
  `git stash` is a no-op when there's nothing to stash, which is fine;
  the gate is about verifying the symptom, not mechanically requiring
  a stash.
