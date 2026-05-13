---
pr: pr-6be8ee6
workdir: /workspace
captured_at: 2026-05-13
recipe: pm/qa/artifacts/cli-recording.md
---

## Commands

```
# Setup (run in /scratch/pm-test-1778699038, pm installed in /tmp/pm-venv, PYTHONPATH=/workspace):
#   pm pr add "Fix login crash on empty password" --plan bugs ...        -> pr-57b2811 (BUG_ID)
#   pm pr add "Refactor settings panel layout" --plan improvements ...   -> pr-fd4906a (FEAT_ID)
#   pm pr start pr-57b2811 --background
#   pm pr review pr-57b2811 --background

# Recorded:
pm prompt pr-57b2811 | sed -n '/## Bug Fix Flow/,/## Tips/p'
pm prompt pr-fd4906a | grep -c "Bug Fix Flow"
sed -n '/## Bug Fix Review Checklist/,/^## /p' <bug-workdir>/pm/prompts/pm_prompt_*.txt | head -20
```

## What this demonstrates

Three observations against a throwaway pm project that exercises the local
project_manager clone via PYTHONPATH=/workspace:

1. **Bug PR impl prompt** (`pm prompt pr-57b2811`, plan=bugs): the rendered
   prompt contains a `## Bug Fix Flow` section with five numbered steps —
   (1) Manual repro on pre-fix code, (2) Write a failing test, (3) Fix,
   (4) Verify with the test, (5) Verify manually. Step 1 explicitly covers
   reusing an existing pre-fix capture, falling back to stashing changes or
   checking out the parent commit / reverting fix files temporarily, and
   checking in with the user if reproduction fails. It names
   `pm/qa/instructions/` (env-setup recipes) and `pm/qa/artifacts/` (capture
   recipes). The captures paths are literally
   `pm/qa/captures/pr-57b2811/impl/pre-fix/` and
   `pm/qa/captures/pr-57b2811/impl/post-fix/` — interpolated with the actual
   BUG_ID, not a placeholder.

2. **Feature PR impl prompt** (`pm prompt pr-fd4906a`, plan=improvements):
   `grep -c "Bug Fix Flow"` returns `0`. No five-step flow, no pre-fix /
   post-fix mentions.

3. **Bug PR review prompt** (`pm pr review pr-57b2811 --background`, prompt
   file read from the workdir): the prompt contains a `## Bug Fix Review
   Checklist` whose first bullet states that missing or unconvincing
   pre/post-fix captures under `pm/qa/captures/pr-57b2811/impl/` should be
   surfaced as **INPUT_REQUIRED** (explicitly INPUT_REQUIRED, not
   NEEDS_WORK), leaving the accept-without-capture decision to the user.

All three THEN clauses for scenario 45 pass.

## Files

- `recording.cast` — asciinema replay of `bash /tmp/qa45-script.sh`.
- `transcript.log` — plain-text version of the same run; load-bearing.
- `prompt.md` — copy of this scenario's prompt as received (pre-existing).
- `manifest.md` — this file.
