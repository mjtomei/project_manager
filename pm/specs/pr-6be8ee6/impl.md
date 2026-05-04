# Implementation Spec — pr-6be8ee6

Surface the existing `pm/qa/instructions/tui-manual-test.md` repro recipe in
the bug-fix flow prompt, and add a "reproduce on pre-fix code" gate so
sessions stop writing speculative fixes for TUI bugs.

## Requirements

1. **Reorder priority for TUI bugs in `_BUG_FIX_FLOW_BLOCK`**
   (`pm_core/prompt_gen.py:20`) — the venv-install + `pm tui send` /
   `pm tui view` recipe is the *primary* repro path for TUI bugs, not a
   fallback. The block must reference `pm/qa/instructions/tui-manual-test.md`
   by name.

2. **"Reproduce on pre-fix code" gate** — before the "Fix" step, instruct
   the session to confirm the bug actually reproduces against the pre-fix
   code (e.g. `git stash` or `git checkout <parent> -- <files>`). If it
   does not reproduce, the session must say so and ask the user before
   continuing — no fix on top of an unreproduced bug.

3. **Conditional TUI pointer in the impl prompt** — when the PR is a bug
   PR (`_is_bug_pr(pr)`) AND it touches the TUI, inline a block that
   points at `pm/qa/instructions/tui-manual-test.md` with the concrete
   commands. Implemented in `generate_prompt`
   (`pm_core/prompt_gen.py:177`), interleaved next to `bug_fix_block`.

## Implicit Requirements

- A `_touches_tui(pr)` helper. The prompt is generated at session start, so
  no diff exists yet. Detect from PR metadata: case-insensitive substring
  match on `title + description` for `"tui"`, `"textual"`, or
  `"pm_core/tui"`. False positives (e.g. "intuitive") are a non-issue
  because the appended block is purely informational.
- Existing tests in `tests/test_bug_fix_flow_prompts.py` keep passing
  (substring assertions: `"Bug Fix Flow"`, `"Reproduce"`, `"Reconcile"`,
  `"confirmed-overlap"`). The reorder must not break those.
- The QA instruction file path stays unchanged
  (`pm/qa/instructions/tui-manual-test.md`).

## Ambiguities

- **TUI-detection heuristic** — proposed: text match on title + description
  for `tui` / `textual` / `pm_core/tui`. The description specifically said
  "When the touched files include `pm_core/tui/`" but at session-start time
  no files have been touched, so a metadata heuristic is the closest
  realizable proxy. Cheap and good enough; resolved.
- **Whether to also surface the pre-fix repro gate to non-TUI bugs** —
  Yes. The gate (don't fix what you haven't reproduced) is general-purpose
  and the recent symptom would have caught any speculative fix. Putting
  it in `_BUG_FIX_FLOW_BLOCK` itself, not the conditional TUI block.
- **Whether the review checklist (`_BUG_FIX_REVIEW_BLOCK`) should also
  call out the TUI repro recipe** — out of scope per the task ("only
  addresses surfacing in the right *prompt*"). Leave alone.

## Edge Cases

- **Non-bug PRs that touch TUI code** — no bug-flow block, no TUI block.
  Correct: feature TUI work has its own iteration loop.
- **Bug PRs whose description doesn't mention TUI but actually touch
  TUI** — the conditional block won't appear. Acceptable: the generic
  bug-flow block now mentions TUI manual repro by reference, and reviewers
  catch missed reproductions.
- **Workdir not yet present / git not initialized** — the prompt is text;
  no runtime check is performed. The session will discover the missing
  workdir when running `git stash` etc., which is fine.
