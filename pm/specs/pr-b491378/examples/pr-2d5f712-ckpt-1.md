---
checkpoint: ckpt-1
pr: pr-2d5f712
reviewed_head: "(not recoverable from pre-feature history; a live checkpoint records the full SHA)"
base: "master@(not recoverable; a live checkpoint records the full SHA)"
covers_qa_runs: [ad009382b7b0e6d6, a953490cbd95dbd7]
covers_requests: []
outcomes: [keep, follow_up]
human_question: none
followups: [pr-3f85ad7, pr-71e9ec7]
---
<!-- ILLUSTRATIVE EXAMPLE for the pr-b491378 spec (productive local fixes,
     no redesign). Written by the spec author over real registry notes as
     they stood at 2026-05-26T01:29Z when the second counted run completed.
     It is not ground truth and not an externally sourced reference. -->
# Checkpoint ckpt-1 — pr-2d5f712

## Summary
Keep the current approach. The rounds found separate local defects in
different surfaces, each fixed with a test or a verified pre/post capture, and
none came back. The router design itself — one routing verdict, decision
decoupled from side effects, always-gated merge per the owner's decision — was
not implicated by any failure. Three out-of-scope look-alikes in the review
window are tracked or should be.

## What was considered
- A shared cause across the failures — evidence: the fixes are unrelated: `less` dependency and dead "(no captures found)" fallback in `_evidence_pane_cmd` (note-0a62884), an unlocked fixed `.tmp-{pr_id}` clone path and an unlocked find/create window (note-e928d8e), a bounce relaunched with `fresh=False` (note-c1799e2), the router pane split without `cwd` (note-7ca15a1, note-4e29587: one defect reported by two scenarios), and an `&&` chain that blanked the evidence pane (note-e411a86) — conclusion: ruled out; no symptom recurred after its fix.
- Accumulating special cases in `_evidence_pane_cmd` — evidence: three fixes touched it (note-0a62884 ×2, note-e411a86); the last made each section degrade independently — conclusion: ruled out as a design issue; confirm in the diff that every section now has its own fallback.
- The router design itself — evidence: "a manual verdict is adopted by a later auto-sequence run, manual never mutates: PASS" (note-094efa5); the owner's decisions note-942fa37 (remove autonomy and the capture gate) and note-511d725 (adoption + explicit verdict record) are implemented as decided — conclusion: no change; those decisions stand.

## Current-PR corrections
None.

## Specification
No problems found with the spec.

## Follow-up work
- pr-3f85ad7 (reused) — `_launch_review_window` unlocked find/create race; same race fixed here for sign-off (note-5757682).
- pr-71e9ec7 (reused) — review diff pane `| less -R` without fallback (note-5757682).
- New pending bug (a live checkpoint files it with `pm pr add` and lists its id above; not filed for this illustration), after `pm pr list --plan bugs` showed no match — the review-loop window's split pane is created without `cwd` (note-4e29587 points at `_launch_review_window`); out of scope here because it is the review window, not sign-off.

## Breakup
Not recommended: the fixes are incidental and belong with the surfaces this PR adds.

## Expected benefit and tradeoffs
No redesign cost. The next round fixes the remaining scenario failures as usual; the follow-ups keep the look-alike defects from being lost.

## Questions for the owner
None.
