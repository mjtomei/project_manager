---
title: Scenario 32 — Bug-fix flow prompt restructured for bugs, absent for non-bugs
description: Verifies pm prompt emits the new 5-step Bug Fix Flow for plan=bugs PRs (with pm/qa/captures, instructions, artifacts references and the pre-fix reproduce gate) and omits it for non-bug PRs; review prompt classifies missing captures as INPUT_REQUIRED.
---

## What this demonstrates

`pm prompt <bug-pr>` emits a `## Bug Fix Flow` block with the new 5-step
structure (Manual repro on pre-fix code → Write a failing test → Fix →
Verify with the test → Verify manually), references to
`pm/qa/captures/<pr-id>/impl/{pre-fix,post-fix}/`, `pm/qa/instructions/`,
`pm/qa/artifacts/`, and the pre-fix reproduce gate (stash / check out
the parent, plus check-in-with-user-on-failed-reproduction). The
non-bug PR prompt omits the block entirely. The review prompt for the
bug PR contains a `## Bug Fix Review Checklist` and routes missing /
unconvincing captures to `INPUT_REQUIRED` rather than `NEEDS_WORK`;
the non-bug review prompt has no such section.

## Setup

- venv: `/tmp/pm-venv`, `pip install -e /workspace`, `PYTHONPATH=/workspace`
- test project: `/tmp/pm-test-1778627474` (`pm init --backend local --no-import`)
- PRs: BUG_ID=`pr-01511b4` (plan=bugs), FEAT_ID=`pr-08d1fdc` (plan=features)

## Commands recorded

`recording.cast` captures the live `pm prompt <BUG_ID>` / `pm prompt
<FEAT_ID>` runs plus the `## Bug Fix Flow` grep counts (1 for the bug
PR, 0 for the feature PR). `transcript.log` is the same run as a plain
text trace.

The four prompt dumps (`bug-impl-prompt.txt`, `feat-impl-prompt.txt`,
`bug-review-prompt.txt`, `feat-review-prompt.txt`) are the actual
artifacts the grep assertions in steps 6–9 ran against.

## Result

All grep assertions in steps 6, 7, 8, 9 passed. The "check in with the
user" string is present but split across two lines in the rendered
prompt (`reproduction doesn't work,\n  check in with the user`), so a
literal `grep -F` misses it — confirmed by joining the file and
re-greping. Treated as a wrapping artifact, not a content gap.

## Files

- `recording.cast` — asciinema replay of `pm prompt $BUG_ID` and `pm prompt $FEAT_ID` plus the bug-flow grep counts.
- `transcript.log` — plain-text trace of the same commands.
- `bug-impl-prompt.txt` — `pm prompt pr-01511b4` output (bug PR impl prompt). Contains the 5-step Bug Fix Flow.
- `feat-impl-prompt.txt` — `pm prompt pr-08d1fdc` output (feature PR impl prompt). No Bug Fix Flow.
- `bug-review-prompt.txt` — `prompt_gen.generate_review_prompt(data, BUG_ID)` output. Contains the Bug Fix Review Checklist with INPUT_REQUIRED routing.
- `feat-review-prompt.txt` — same generator on the feature PR. No Bug Fix Review Checklist.
- `notes.md` — recorded `BUG_ID` / `FEAT_ID` for reproducibility.
