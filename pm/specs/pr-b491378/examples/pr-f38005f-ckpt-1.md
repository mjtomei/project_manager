---
checkpoint: ckpt-1
pr: pr-f38005f
reviewed_head: "(not recoverable from pre-feature history; a live checkpoint records the full SHA)"
base: "master@(not recoverable; a live checkpoint records the full SHA)"
covers_qa_runs: [d8d59509902b0358, bdca24011d0bf8cd]
covers_requests: []
outcomes: [corrections, spec_clarification]
human_question: none
followups: []
---
<!-- ILLUSTRATIVE EXAMPLE for the pr-b491378 spec (shared architectural cause).
     Written by the spec author over real records only: registry notes, commit
     subjects and the QA spec, as they stood at 2026-04-09T18:18Z when the
     second counted run completed. Statements about code beyond those records
     are labelled as hypotheses for a live checkpoint to confirm in the diff.
     It is not ground truth and not an externally sourced reference. -->
# Checkpoint ckpt-1 — pr-f38005f

## Summary
Keep `store.locked_update` as the mechanism: no round failed inside it. The two
counted runs, the review notes and the commit history point to one shared
cause — callers are converted to locking, and given its error handling, one
call site at a time, so each round finds the next unconverted or unguarded
caller. The next review iteration should finish the conversion as one audited
pass and give the TUI one shared error path.

## What was considered
- The locking primitive is wrong — evidence: run d8d59509902b0358 (note-60be829) passed "Atomic write — file never truncated", "Exception in mutation function — lock released, data unsaved" and "StoreLockTimeout — CLI error message"; its one failure, "Concurrent pm pr add — no lost writes", was fixed in pr_add's duplicate check (4addcec0) — conclusion: ruled out.
- Piecemeal adoption is the repeated cause — evidence: commits 25ae82fb (03-01) "migrate remaining save_and_push/store.save call sites to locked_update", 9bc45bce (03-07) "Migrate qa_loop_ui and review_loop_ui store.save calls", d1311737 (03-26) "catch StoreLockTimeout in all TUI call sites", 323cc7af (04-06) "Migrate remaining store.save call sites", 6b306d22 (04-09) "restore ProjectYamlParseError handling in do_normal_sync"; note-181f05d: review_loop_ui, qa_loop_ui and auto_start "also do store.load()/store.save() and modify app._data" — conclusion: held.
- Error handling is duplicated per caller — evidence: run bdca24011d0bf8cd (note-ed85f13) failed "Exception in mutation function — lock released, data unsaved", which round 1 passed; StoreLockTimeout and ProjectYamlParseError handling were each added site by site (d1311737, 6b306d22) — conclusion: held as a hypothesis; confirm in the diff that TUI callers each wrap `locked_update` in their own try/except.
- The rounds were only productive local fixes — evidence: the pr_add fix stayed fixed (round 2: "Concurrent duplicate-title prevention in pr_add: PASS") — conclusion: true for that fix, but the other failures share the cause above.

## Current-PR corrections
- Audit every `store.load(`, `store.save(` and `locked_update(` caller under `pm_core/` in one pass, convert the remaining load-modify-save sequences, and record the audited list in a PR note — why: piecemeal conversion is the repeated cause — verify by: the QA audit scenario as clarified below.
- Give TUI callers one helper that applies the shared StoreLockTimeout / ProjectYamlParseError / mutation-exception handling, replacing per-site try/except — where: the TUI modules named in note-181f05d — why: the same handling keeps being added one site at a time — verify by: unit tests of the helper for lock timeout, parse error and an exception in the mutation; existing scenarios unchanged.

## Specification
- No implementation spec exists (`pm/specs/pr-f38005f/impl.md`). The description states the goal and the QA spec (32f1f681) supplies the checks; no implementation spec is needed for this PR's size.
- QA spec, scenario "Code audit — no bare store.save() in CLI or TUI modules" — ambiguous: a bare `store.load()` that mutates `app._data` and is saved later is also a read-modify-write — proposed: "no read-modify-write of project.yaml outside `locked_update`, including load-then-save sequences" — clarification (it strengthens the check and changes no requirement in the description).

## Follow-up work
None.

## Breakup
Not recommended: the remaining work is the same conversion across shared call sites; a split would duplicate review and QA of the same code.

## Expected benefit and tradeoffs
One audited pass should end the one-site-per-round pattern, and QA then checks the cause rather than each symptom. Cost: a larger next iteration, and every TUI write must go through the helper.

## Questions for the owner
None.
