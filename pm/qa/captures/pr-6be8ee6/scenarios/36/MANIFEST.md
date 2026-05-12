---
title: Scenario 36 — Review-loop INPUT_REQUIRED gate + duplicate-verifier guard
description: Partial capture of checkpoint 3 (review-loop INPUT_REQUIRED on missing bug-fix captures) and code-level verification of checkpoint 5 (qa_loop duplicate-verifier guard e8fe399).
---

## Files

- `review-pane.txt` — tmux scrollback of the review-loop Claude pane (%7) showing iteration 1. The verdict block at the bottom is **INPUT_REQUIRED** with item 4 explicitly citing "No pre/post-fix captures under pm/qa/captures/pr-561aa6c/impl/" (alongside other reviewer concerns about the deliberately thin fixture fix).
- `tui-main.txt` — TUI scrollback at the time the loop was running. Status badge `⟳1◓` (running, iteration 1); the TUI never advanced to `⏸1` (input_required) because the orchestrator was blocked on the issue below.
- `pm-debug.log` — pm runtime log slice showing `loop_shared review_loop: poll_for_verdict (hook+jsonl)` armed against transcript symlink `…/pm/transcripts/manual-6104c6/review-pr-561aa6c-i1.jsonl → /home/pm/.claude/projects/-home-pm--pm-workdirs-…/3eeb6e11….jsonl`, which never came into existence — see below.
- `prompt.md` — scenario prompt as fired.

## What the capture shows

Checkpoint 3 (PR-scope behavior): the bug-fix review block from
`pm_core/bug_fix_prompts.py:76-79` is doing its job — the reviewer's
output surfaces missing captures as **INPUT_REQUIRED**, not
NEEDS_WORK, exactly as the checklist instructs. That part of the
PR's contract is verified at the Claude-output level (see
`review-pane.txt` final block).

Checkpoint 5 (e8fe399): not exercised end-to-end. Verified
at the code level only — `pm_core/qa_loop.py:1996` reads
`_last_scenario_hook_ts[scenario_idx] = time.time()` (i.e. the
post-fix stamp), not `.pop(...)`.

## What blocked end-to-end PASS

Orchestrator did not advance iteration 1 to a verdict pickup:

- The review pane's Claude session JSONL was written to
  `/home/pm/.claude/projects/-tmp-pm-test-1778627480-pm/<sid>.jsonl`
  (slug of `/tmp/pm-test-1778627480/pm` — the cwd the Claude pane
  actually has, per `tmux list-panes`).
- `pm pr review --review-loop` symlinked the expected transcript at
  `/home/pm/.claude/projects/-home-pm--pm-workdirs-pm-test-1778627480-…-c8b85d39/<sid>.jsonl`
  (slug of the workdir).
- The two paths don't match, so `loop_shared.poll_for_verdict`'s
  jsonl tail never sees the verdict and the loop stays in iteration 1
  even though the pane's text clearly shows `INPUT_REQUIRED`.

This is a real bug but it is not in this PR's scope (the PR only
edits prompt/markdown surfaces under `pm_core/bug_fix_prompts.py`,
`pm_core/qa_*` prompt generators, and the QA pane TUI). The pane
cwd / transcript-slug mismatch sits in the launcher path. Filing
it would be a separate bug PR.

## Reproduction caveat (per scenario step 4)

The instruction "any tiny code change + commit" understates what
the reviewer needs to PASS once captures are added. With the dummy
`# fix` content the reviewer also flags four other gaps (no
pagination code, no spec, no test, suspicious commit message), so
even if the orchestrator had advanced and the captures had been
added, iteration 2 would still likely produce INPUT_REQUIRED on
those grounds — the scenario as written cannot deterministically
flip to PASS without a more substantial fixture commit.

## Verdict path

Reporting **INPUT_REQUIRED** on the scenario: the PR-level
behavior I am here to test is verified at the visible-output
level, but the end-to-end orchestrator iteration that the scenario
script requires is blocked by a separate launcher cwd issue I
could not address in scope.
