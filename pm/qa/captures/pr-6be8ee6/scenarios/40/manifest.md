---
title: Scenario 40 — Bug-fix flow prompt content for bug vs non-bug PRs
description: Captures of impl + review prompts for a bug PR and a feature PR; assertion checks for 5-step structure, captures-path interpolation, and conditional bug-fix block. All four prompts captured by driving the real pm CLI (impl via stdout fallback, review via tmux + claude shim).
---

## Workdir

Throwaway pm test project: `/tmp/pm-test-scen40-1778679559` (backend=local).

- `BUG_ID=pr-61c2679` (plan: bugs, title "demo-bug")
- `FEAT_ID=pr-e96508e` (plan: features, title "demo-feature")

## What this demonstrates

- Bug PR impl prompt (`pm pr start pr-61c2679` with claude stripped from PATH so `find_claude()` returns None and the prompt is dumped to stdout per `pm_core/cli/pr.py:993`) contains the `## Bug Fix Flow` block with the 5 numbered steps in order, `pm/qa/instructions/` and `pm/qa/artifacts/` references, and captures path interpolated to `pm/qa/captures/pr-61c2679/impl/{pre-fix,post-fix}/`. Step 1 mentions stash / parent commit / revert fix files and "check in with the user" if reproduction fails.
- Feature PR impl prompt contains no `Bug Fix Flow` block and no `pm/qa/captures/pr-e96508e/impl/` references.
- Bug PR review prompt (`pm pr review pr-61c2679` run from inside a tmux session named `pm-pm-test-scen40-1778679559-14956796` with the claude shim from `/tmp/scen40-bin/claude` on PATH — the shim records argv to `/tmp/scen40-prompts/last.txt` before tmux's trailing `rm -f` cleans up the temp prompt file) contains the `Bug Fix Review Checklist`, references `pm/qa/captures/pr-61c2679/impl/`, and surfaces missing captures as `**INPUT_REQUIRED**` (verified by `awk` slicing the post-`## Bug Fix Review Checklist` region; the unsliced `! grep -q "NEEDS_WORK"` from the scenario hits the generic verdict block, not the bug-fix block, so the sliced check is the meaningful one).
- Feature PR review prompt contains no `Bug Fix Review Checklist`.

## Steps

1. `python3 -m venv /tmp/pm-venv-scen40 && pip install -e /workspace` (pm resolves to `/workspace/pm_core`).
2. Create throwaway project under `/tmp/pm-test-scen40-…`, `pm init --backend local --no-import`.
3. Install claude shim at `/tmp/scen40-bin/claude` that writes its last argv to `/tmp/scen40-prompts/last.txt` then sleeps 2s.
4. `pm pr add 'demo-bug' --plan bugs --description 'repro: foo'` → `BUG_ID=pr-61c2679`.
5. `pm pr add 'demo-feature' --plan features --description 'add foo'` → `FEAT_ID=pr-e96508e`.
6. `pm push && git merge pm/sync-…` so `pm pr start` sees the PRs committed on master.
7. Run `pm pr start "$BUG_ID"` with `PATH` stripped of every dir containing a `claude` binary so `find_claude()` returns None and the impl prompt is dumped to stdout. Tee to `/tmp/scen40-bug-impl.txt`.
8. Same for `pm pr start "$FEAT_ID"` → `/tmp/scen40-feat-impl.txt`.
9. Start the expected pm tmux session: `tmux new-session -d -s pm-pm-test-scen40-1778679559-14956796 -c /tmp/pm-test-scen40-1778679559 bash` (session name from `_get_session_name_for_cwd`).
10. From inside that tmux session (`tmux send-keys`), run `pm pr review $BUG_ID` and `pm pr review $FEAT_ID` with the shim on PATH. The shim captures argv from each launched claude window; copy `/tmp/scen40-prompts/last.txt` after each call to `/tmp/scen40-bug-review.txt` and `/tmp/scen40-feat-review.txt`.
11. Run `scen40-verify.sh` against the four prompt files; record with asciinema and dump plain output to `transcript.log`.

## Result

All 6 assertion groups returned the expected match counts (see `transcript.log`). Bug-fix block present and correctly interpolated on the bug PR's impl + review prompts; absent on the feature PR's impl + review prompts. Both review prompts were captured via the real `pm pr review` CLI inside tmux (not by importing the prompt generator).

## Files

- `bug-impl-prompt.txt` — stdout from `pm pr start pr-61c2679` with claude removed from PATH; contains the full impl prompt including the 5-step Bug Fix Flow block.
- `feat-impl-prompt.txt` — stdout from `pm pr start pr-e96508e`; same generator, no Bug Fix Flow block.
- `bug-review-prompt.txt` — the exact prompt argv passed to claude by `pm pr review pr-61c2679`, captured by the shim. Ends with the Bug Fix Review Checklist.
- `feat-review-prompt.txt` — same path for the feature PR; no Bug Fix Review Checklist.
- `recording.cast` — asciinema replay of `scen40-verify.sh` running every assertion grep against the four prompt files.
- `transcript.log` — plain-text counterpart to `recording.cast`; load-bearing for grep/diff.
