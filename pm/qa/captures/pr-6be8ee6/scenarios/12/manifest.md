---
title: Scenario 12 — Bug-fix flow prompt rendering and gating
description: Verify generate_prompt emits the bug-fix block for plan="bugs" and type="bug", omits it for other PRs, interpolates PR-id into captures paths, surfaces instructions+artifacts pointers and the pre-fix repro gate, and that generate_review_prompt's missing-captures bullet uses INPUT_REQUIRED (not NEEDS_WORK). Also confirms _is_bug_pr / _bug_fix_flow_block / _bug_fix_review_block remain importable from pm_core.prompt_gen via the back-compat shim.
recipe: pm/qa/artifacts/cli-recording.md
pr: pr-6be8ee6
workdir: /workspace
captured_at: 2026-05-11
---

## Verdict

PASS — 20/20 assertions across all six scenario steps. See `transcript.log`.

## Environment

- Host: Linux 6.17.0-1014-nvidia
- Source: /workspace (PR branch pm/pr-6be8ee6-bug-fix-flow-surface-tui-qa-repro-instructions-in-)
- Commit under test: 8e14d5ae361d053784fe1bfe6bc9c823a6b41446
- python: Python 3.10.12

## Commands

```
bash /tmp/scen12_run.sh
```

The script (preserved inline in `recording.cast`) runs four
`python3 -c '…'` invocations:

1. `generate_prompt` with `{"plan": "bugs"}` → `scen12_impl_bugs.txt`
2. `generate_prompt` with `{"type": "bug"}` → `scen12_impl_typebug.txt`
3. `generate_prompt` with `{"plan": "improvements"}` → `scen12_impl_notbug.txt`
4. `generate_review_prompt` with `{"plan": "bugs"}` → `scen12_review_bugs.txt`

Plus a re-export sanity check importing `_is_bug_pr`,
`_bug_fix_flow_block`, `_bug_fix_review_block` from
`pm_core.prompt_gen`.

## What this demonstrates

- `generate_prompt` produces the `## Bug Fix Flow` block with the
  five numbered steps in order for both the legacy `plan: "bugs"`
  trigger and the new forward-looking `type: "bug"` trigger.
- The block omits cleanly when the PR is neither (e.g. `plan: "improvements"`).
- Captures paths are interpolated with the local PR id
  (`pm/qa/captures/pr-xyz/impl/{pre-fix,post-fix}/`).
- The block surfaces pointers to `pm/qa/instructions/` and
  `pm/qa/artifacts/`, the prior-session-artifact reuse language, and
  the pre-fix repro gate (stash-uncommitted / checkout parent /
  revert fix files) for already-committed fixes.
- `generate_review_prompt` produces the `## Bug Fix Review Checklist`
  with the pre/post-fix captures bullet, failing-then-passing test
  bullet, right-reason bullet, drive-by-scope bullet, and — critically
  — the missing-captures bullet flags **INPUT_REQUIRED** (not
  NEEDS_WORK), preventing infinite review loops.
- The `pm_core.bug_fix_prompts` → `pm_core.prompt_gen` re-export
  shim remains intact.

## Files

- `recording.cast` — asciinema replay of the four prompt-generation invocations + re-export check (recorded via tmux scaffold; no-TTY workaround).
- `transcript.log` — 20-assertion check log; all PASS.
- `scen12_impl_bugs.txt` — full impl prompt for `{"plan": "bugs"}`.
- `scen12_impl_typebug.txt` — full impl prompt for `{"type": "bug"}`.
- `scen12_impl_notbug.txt` — full impl prompt for `{"plan": "improvements"}` (no bug-fix block).
- `scen12_review_bugs.txt` — full review prompt for `{"plan": "bugs"}`.

## Notes

- Two initial assertion drafts ("reuse-prior-language" as a single
  substring, "pre-fix and post-fix" with case-sensitive search)
  reported FAIL on first run; both were false-negatives in the
  assertion logic, not in the prompt output. The transcript uses
  whitespace-normalized / case-insensitive checks that map cleanly to
  the prompt's actual wrapping/capitalization.
