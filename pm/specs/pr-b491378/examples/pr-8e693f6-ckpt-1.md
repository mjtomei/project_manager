---
checkpoint: ckpt-1
pr: pr-8e693f6
reviewed_head: "(not recoverable from pre-feature history; a live checkpoint records the full SHA)"
base: "master@(not recoverable; a live checkpoint records the full SHA)"
covers_qa_runs: [47b30e4a8869f42d, bb8854012f0ad8f2]
covers_requests: []
outcomes: [spec_change_proposal]
human_question: blocking
followups: []
---
<!-- ILLUSTRATIVE EXAMPLE for the pr-b491378 spec (misleading spec assumption).
     Written by the spec author over real records only: registry notes, commit
     subjects and the implementation spec as committed in 54c36ad6, as they
     stood at 2026-05-26T13:25Z when the second counted run completed. It is
     not ground truth and not an externally sourced reference. What actually
     happened later is recorded in ../trigger-behavior.md as hindsight.
     STATE: this is the draft at the INPUT_REQUIRED point. The session ends
     INPUT_REQUIRED and asks the question below; pm rejects completion while
     `human_question: blocking`. After the owner answers in the pane, the
     agent records the answer, sets `human_question: answered`, commits and
     ends CHECKPOINT_COMPLETE. No answer is invented here. -->
# Checkpoint ckpt-1 — pr-8e693f6

## Summary
Both rounds failed on the same design point: the dashboard has two sources for
a PR's sign-off verdict — the `report.json` sidecar the spec makes "the only
contract" and the recorded `pr['signoff']` verdict that QA fix 769d009e now
reads when the sidecar is absent. That is a conflict inside the spec, not an
implementation bug. Removing the duplication changes the owner's clarification
(note-537e1a0 asks for "a small report.json sidecar"), so only the owner can
decide; the next round's work depends on the answer.

## What was considered
- Ordinary robustness bugs — evidence: run 47b30e4a8869f42d (note-596f78b) failed "Robustness — garbage sidecar, partial sidecar, and HTML-injection-safe titles" and "No session tag — dashboard fails clearly" — conclusion: the session-tag failure is a local bug and passed in the next run (note-083c051); the sidecar failures belong with the next item.
- Duplicated verdict source — evidence: spec 54c36ad6 says the dashboard "globs the per-PR `report.json` sidecars … the sidecar is the only contract" and calls `report.json` "a strict, frozen schema (the dashboard's only contract)" with `verdict`, `status`, `tally`; it also requires "Single sources of truth — match the TUI tech tree + `pm pr list`"; QA commit 769d009e "dashboard signoff marker reads pr['signoff'] verdict when sidecar absent"; run bb8854012f0ad8f2 (note-083c051) then failed exactly "Dashboard sign-off marker is sourced from pr['signoff'] when no sidecar is present" — conclusion: held. The sidecar copies data that already has a home (the recorded verdict from pr-2d5f712's note-511d725, which the spec cites; status in project.yaml; QA status), so every round has to reconcile two copies.
- Drop the owner's other dashboard features to simplify (filtering, plan grouping, tallies, loop badges) — conclusion: ruled out; they are in the description and no evidence shows they are wrong. Not proposed.

## Current-PR corrections
None until the owner answers; whichever source the owner keeps, the next iteration makes the dashboard read only that source and drops the fallback added by 769d009e.

## Specification
- "the sidecar is the only contract" together with "Single sources of truth" — conflicting: the verdict the sidecar carries is also recorded on the PR — proposed: the dashboard reads the verdict from the PR's recorded sign-off verdict (or a marker inside `report.html`) and status from project.yaml; `report.json` is dropped or reduced to fields with no other source — requirement change (it alters the owner's clarification note-537e1a0), needs owner approval.

## Follow-up work
None.

## Breakup
Not recommended: the report and the dashboard share the generator and the verdict contract the question is about.

## Expected benefit and tradeoffs
One verdict source removes a whole class of consistency failures, and QA can test the contract instead of sidecar repair paths. Cost: changing a clarified requirement and rewriting the sidecar-reading code and its scenarios.

## Questions for the owner
- Keep `report.json` as the dashboard's contract, or make the recorded sign-off verdict (or a marker in `report.html`) the single source and drop or shrink the sidecar? — blocking: the next iteration either hardens sidecar repair or removes it.
