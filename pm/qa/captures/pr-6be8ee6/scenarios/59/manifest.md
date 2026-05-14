---
pr: pr-6be8ee6
workdir: /workspace
captured_at: 2026-05-14
recipe: pm/qa/artifacts/cli-recording.md
---

## Commands

```
pm prompt pr-60b149d                # bug PR impl prompt
pm prompt pr-3433875                # feature PR impl prompt
pm qa captures-path pr-60b149d      # interpolated captures path
grep -A 10 "Bug Fix Review Checklist" <workdir>/pm/prompts/pm_prompt_*.txt
```

## What this demonstrates

Scenario 59: the 5-step `## Bug Fix Flow` appears only in the bug PR's
impl prompt, contains the five numbered steps in order (Manual repro on
pre-fix code → Write a failing test → Fix → Verify with the test →
Verify manually), references `pm/qa/instructions/` and
`pm/qa/artifacts/`, and interpolates `$(pm qa captures-path <BUG_ID>)`
with `/impl/pre-fix/` and `/impl/post-fix/` subpaths. The feature PR's
impl prompt has zero "Bug Fix Flow" occurrences. The review prompt for
the bug PR (launched via `pm pr review --background`) contains
`## Bug Fix Review Checklist`, references
`$(pm qa captures-path pr-60b149d)/impl/`, and explicitly states that
missing/unconvincing captures must be surfaced as **INPUT_REQUIRED**.

## Files

- `recording.cast` — asciinema replay of the verification script
- `transcript.log` — plain-text capture of the same run (load-bearing)
