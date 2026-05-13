---
title: Scenario 40 — Bug-fix flow prompt content for bug vs non-bug PRs
description: Captures of impl + review prompts for a bug PR and a feature PR; assertion checks for 5-step structure, captures-path interpolation, and conditional bug-fix block.
---

## Workdir

Throwaway pm test project: `/tmp/pm-test-scen40-1778679559` (backend=local).

- `BUG_ID=pr-61c2679` (plan: bugs, title "demo-bug")
- `FEAT_ID=pr-e96508e` (plan: features, title "demo-feature")

## What this demonstrates

- Bug PR impl prompt (`pm pr start pr-61c2679` with claude stripped from PATH so `find_claude()` returns None and the prompt is dumped to stdout) contains the `## Bug Fix Flow` block with the 5 numbered steps in order, `pm/qa/instructions/` and `pm/qa/artifacts/` references, and the captures path interpolated to `pm/qa/captures/pr-61c2679/impl/{pre-fix,post-fix}/`. Step 1 mentions stash / parent commit / revert fix files and "check in with the user" if reproduction fails.
- Feature PR impl prompt contains no `Bug Fix Flow` block and no `pm/qa/captures/pr-e96508e/impl/` references.
- Bug PR review prompt (built by calling `pm_core.prompt_gen.generate_review_prompt` directly — `pm pr review` requires being inside tmux, so a Python invocation substitutes for the CLI path while exercising the same generator) contains the `Bug Fix Review Checklist`, references `pm/qa/captures/pr-61c2679/impl/`, and surfaces missing captures as `INPUT_REQUIRED` (not `NEEDS_WORK`).
- Feature PR review prompt contains no `Bug Fix Review Checklist`.

## Steps

1. `python3 -m venv /tmp/pm-venv-scen40 && pip install -e /workspace` (pm resolves to `/workspace/pm_core`).
2. Create throwaway project under `/tmp/pm-test-scen40-…`, `pm init --backend local --no-import`.
3. `pm pr add 'demo-bug' --plan bugs --description 'repro: foo'` → `BUG_ID`.
4. `pm pr add 'demo-feature' --plan features --description 'add foo'` → `FEAT_ID`.
5. `pm push && git merge pm/sync-…` so `pm pr start` sees the PRs committed on master.
6. Run `pm pr start "$BUG_ID"` with `PATH` stripped of every dir containing a `claude` binary (`find_claude()` → None triggers the `CLAUDE PROMPT:` stdout dump in `pm_core/cli/pr.py:993`). Tee to `bug-impl-prompt.txt`.
7. Same for `pm pr start "$FEAT_ID"` → `feat-impl-prompt.txt`.
8. `pm pr review` requires being inside tmux; instead invoke `pm_core.prompt_gen.generate_review_prompt(data, pr_id)` directly for each PR → `bug-review-prompt.txt`, `feat-review-prompt.txt`. This exercises the same conditional that `pm pr review` would (see `prompt_gen.py:308`).
9. Run `transcript.log` / `recording.cast` to record the assertion checks.

## Result

All 6 assertion groups returned the expected match counts (see `transcript.log`). Bug-fix block present and correctly interpolated on the bug PR; absent on the feature PR for both impl and review prompts.

## Caveats

- `pm pr review` was not driven via the real CLI because the QA harness runs outside tmux and `_launch_review_window` short-circuits with `"Review window requires tmux."` (see `pm_core/cli/pr.py:1112`). Calling `generate_review_prompt` directly exercises the same prompt-assembly path and is equivalent for what this scenario verifies (content of the review prompt for bug vs non-bug PRs).
- The claude-shim approach from the scenario instructions for capturing the review prompt could not be used for the same reason — the tmux path is gated before claude is even spawned.

## Files

- `bug-impl-prompt.txt` — stdout from `pm pr start pr-61c2679` with claude removed from PATH; contains the full impl prompt including the 5-step Bug Fix Flow block.
- `feat-impl-prompt.txt` — stdout from `pm pr start pr-e96508e`; same generator, no Bug Fix Flow block.
- `bug-review-prompt.txt` — output of `generate_review_prompt(data, pr-61c2679)`; ends with the Bug Fix Review Checklist.
- `feat-review-prompt.txt` — output of `generate_review_prompt(data, pr-e96508e)`; no Bug Fix Review Checklist.
- `recording.cast` — asciinema replay of `scen40-verify.sh` running every assertion grep against the four prompt files.
- `transcript.log` — plain-text counterpart to `recording.cast`; load-bearing for grep/diff.
