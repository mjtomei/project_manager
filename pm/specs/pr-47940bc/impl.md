# Spec: Regression test sessions file bugs and improvements into correct plans

Pattern mirror of merged sibling PR `pr-539110b` (`pm_core/prompt_gen.py`
out-of-scope bugs block), applied to the existing Claude-based regression
tests at `pm/qa/regression/*.md`.

## Requirements
1. Extend the wrapper prompt built in `launch_qa_item()`
   (`pm_core/tui/pane_ops.py:390`) so regression-launched Claude sessions
   include an addendum instructing them where to file findings:
   - Bugs (failing assertion, incorrect behavior, regression):
     `pm pr add '<title>' --plan bugs --description '<details>'`
   - Improvements (UX/quality issue surfaced incidentally):
     `pm pr add '<title>' --plan ux --description '<details>'`
2. The verdict (PASS / NEEDS_WORK / INPUT_REQUIRED) for the regression test
   itself is unchanged. Filing is a side effect.
3. No changes to individual regression markdown files in
   `pm/qa/regression/*.md`.
4. No new prompt generator or worker — the addendum is appended inline by
   the same wrapper that already prepends the "Session Context" / "QA
   Instruction" headers.

## Implicit Requirements
- Addendum should only apply to the regression category, not the
  general `instructions:` category, since the task scopes this to
  regression tests. We branch on `category == "regression"`.
- Agents launched via this path already run with permissive shell access
  (existing wrapper text shows `pm tui send`, `tmux list-panes`, etc.),
  so `pm pr add` will work without tool-allowlist changes. Same as the
  sibling PR's reasoning.
- Encourage `pm pr list --plan bugs` / `--plan ux` skim to avoid
  duplicates (matches sibling block style; the discovery supervisor
  also dedups, but cheap dedup at filing time is still useful).

## Ambiguities (resolved)
- *Which plan id for improvements?* The task and `pm/plans/plan-regression.md`
  both say `--plan ux`. `pm/project.yaml` currently has plans `bugs`,
  `improvements`, and `tui-ux` — no plan literally named `ux`. Resolution:
  use `--plan ux` exactly as the task specifies. If the plan doesn't yet
  exist in a given repo, the command fails with a friendly error and the
  test session moves on (same fallback as the sibling PR's `--plan bugs`
  handling). The discovery/supervisor work in this plan is expected to
  reconcile the plan id.
- *Should the addendum apply to `instructions:` QA items too?* No — task
  scopes this to regression tests. `instructions:` items are interactive
  manual QA and the user is present to triage incidental findings (mirrors
  the sibling-PR decision to skip the interactive scenario-0 prompt).

## Edge Cases
- A regression test can both fail (NEEDS_WORK) AND file an out-of-scope
  bug — the addendum makes clear filing is independent of the verdict.
- Duplicate filings — addendum tells the session to skim
  `pm pr list --plan bugs|ux` first.
- The wrapper currently uses an f-string with literal `{{` for tmux
  format. The addendum is plain text so no brace escaping is needed,
  but it must be appended after the existing block to avoid disturbing
  the existing escapes.
