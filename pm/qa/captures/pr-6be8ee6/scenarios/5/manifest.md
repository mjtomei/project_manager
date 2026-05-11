---
pr: pr-6be8ee6
workdir: /workspace
captured_at: 2026-05-11
recipe: pm/qa/artifacts/cli-recording.md
---

## Commands

```
python3 -c '...' # _is_bug_pr re-export + classification
python3 -c '...' # _bug_fix_flow_block: 5 steps, captures paths, instructions/artifacts pointers, reuse/skip language, no Reconcile
python3 -c '...' # _bug_fix_review_block: INPUT_REQUIRED present; missing-capture clause not NEEDS_WORK
python3 -c '...' # generate_prompt / generate_review_prompt: bug PR gets Bug Fix Flow + Review Checklist; non-bug does not
```

## What this demonstrates

Scenario 5 verification of pm_core/bug_fix_prompts.py and prompt_gen
integration. All four assertion blocks print `OK ...`, confirming
classifier re-export, flow-block structure (5 numbered steps with the
expected labels, captures path scoped under pm/qa/captures/<pr-id>/impl/,
instruction + artifact pointers, reuse/skip semantics, no leftover
"Reconcile" step), review-block INPUT_REQUIRED-only missing-capture
clause, and conditional inclusion in generate_prompt /
generate_review_prompt for bug vs non-bug PRs (bug pr-e29dda7 vs
non-bug pr-001).

## Files

- `recording.cast` — asciinema replay of the four python3 -c verification blocks
- `transcript.log` — plain-text capture of the same run (set -x echo + stdout)
- `manifest.md` — this file
