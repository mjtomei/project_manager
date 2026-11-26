# Example checkpoint assessments (illustrative)

These three files show the assessment format from `../impl.md` §1.1 applied to
**real** accumulated evidence in this repository's registry and history. The
spec author wrote them over that evidence; they are **not** ground truth, not
model outputs from a real checkpoint run, and not externally sourced
references. They are not used to grade a model. The planned tests use the
cited records as *inputs* to the checkpoint prompt (`../impl.md` §9).

| File | Evidence class | Trigger point (2nd counted run) | Outcome shown |
|---|---|---|---|
| [pr-f38005f-ckpt-1.md](pr-f38005f-ckpt-1.md) | shared architectural cause | 2026-04-09T18:18Z (runs d8d59509…, bdca2401…) | corrections + QA-spec clarification |
| [pr-8e693f6-ckpt-1.md](pr-8e693f6-ckpt-1.md) | misleading / internally conflicting spec assumption | 2026-05-26T13:25Z (runs 47b30e4a…, bb885401…) | spec change proposal; blocking owner question (draft at the INPUT_REQUIRED point — no owner answer is invented) |
| [pr-2d5f712-ckpt-1.md](pr-2d5f712-ckpt-1.md) | productive local fixes, no redesign | 2026-05-26T01:29Z (runs ad009382…, a9534901…) | keep + follow-ups reusing existing PRs |

Rules followed:
- Every factual statement cites a registry note id, commit, or spec revision that existed at the trigger time. Statements about code beyond those records are marked as hypotheses for a live checkpoint to confirm in the diff.
- Values pre-feature history never recorded (the reviewed HEAD and base SHAs) are shown as not recoverable, not guessed.
- What happened after the trigger time is kept out of the assessments. `../trigger-behavior.md` §5 reports it separately as hindsight.
- The pr-2d5f712 example names a follow-up that a live checkpoint would file. It was **not** filed for this illustration.
