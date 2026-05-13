---
pr: pr-6be8ee6
workdir: /scratch/qa52/proj
captured_at: 2026-05-13
recipe: pm/qa/artifacts/cli-recording.md
---

## Commands

```
pm prompt <BUG_PR>     # bug-plan PR — expect ## Bug Fix Flow with 5 numbered items
pm prompt <FEAT_PR>    # non-bug PR  — expect no ## Bug Fix Flow
pm pr review <BUG_PR>  # writes review prompt to pm/prompts/<uuid>.txt before launching claude
```

## What this demonstrates

Verifies that `_BUG_FIX_FLOW_BLOCK` only appears for PRs whose plan is
`bugs`, that the block has the expected 5-step structure with the
correct bold headings (Manual repro on pre-fix code / Write a failing
test / Fix / Verify with the test / Verify manually), interpolates the
bug PR id into the captures path, references both
`pm/qa/instructions/` and `pm/qa/artifacts/`, and that step 1 mentions
stashing/checking out parent/reverting fix files for already-committed
fixes. Also verifies the review prompt contains
`## Bug Fix Review Checklist` whose pre/post-fix captures bullet says
missing/unconvincing captures should surface as `INPUT_REQUIRED`.

The review prompt was inspected via the on-disk prompt file written by
`build_claude_shell_cmd` (pm/prompts/pm_prompt_<uuid>.txt) before
claude reads and deletes it — driving `pm pr review` only got as far
as launching claude (no API key available in this env), so the prompt
text was captured from the file rather than from claude's UI. Section
content shown matches what was passed via `"$(cat …)"`.

## Files

- `recording.cast` — asciinema cast: pm prompt for bug PR vs non-bug PR (set -x form)
- `transcript.log` — bug Bug Fix Flow section, non-bug count, review checklist body
- `prompt.md` — pre-existing scenario brief (left in place, not produced by this run)
