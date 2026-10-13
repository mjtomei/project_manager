# pr-b8561ac — QA spec: transcript-sourced planner plan + planner handoff

Code under test: `pm_core/qa_loop.py` (`_read_planner_plan`, `qa_plan_problem`,
`run_qa_sync` Phase 1 / 1.25, `_publish_planner_head`,
`create_scenario_workdir(expected_head=)`, `_poll_tmux_verdicts`,
`_execute_and_finalize`), `pm_core/tui/qa_loop_ui.py` (QA note suffix).
User surface: the pm TUI QA loop (start QA on a PR, planner pane, scenario
windows, status line, QA verdict, PR notes), driven with fake-claude.

## Requirements

R1. Complete plan, truncated pane (the original bug).
- Given a PR whose fake QA planner emits a long 4-scenario plan, the full plan
  is in the planner's JSONL transcript, and the planner pane keeps only the
  tail (tmux history-limit 0, 80x24).
- When the user starts QA on the PR.
- Then the first idle accepts all 4 scenarios from the transcript ("accepted 4
  scenario(s) from transcript" in the debug log), four scenario windows open
  with no renumbering, and QA reaches a verdict with no stall.

R2. Valid-suffix truncation does not lose scenario 1.
- Given the same setup, but the pane tail holds only well-formed SCENARIO 2..4
  plus QA_PLAN_END.
- When QA runs.
- Then the large scenario 1 is launched along with 2..4. Overall PASS needs
  all four.

R3. An incomplete plan is reported, not consumed.
- Given a planner whose transcript has no complete plan (missing, unreadable,
  or holding no plan) and whose pane holds only a truncated suffix.
- When the planner goes idle after the 15 s grace period.
- Then no scenarios launch, and the status/latest output says "Planner plan
  incomplete (…)" with a reason. If the planner exits, QA ends INPUT_REQUIRED
  with an "incomplete … not consumed" error that tells the user to re-emit.

R4. Stale template START + truncated suffix + offset numbering (supervisor
note-455012c; shepherd-20261013/qa-fallback-coverage-gap.json).
- Given a second QA round on a PR (an earlier round used scenario 1, so
  scenario_start = 2), a planner transcript that is missing or has no plan,
  and a pane that shows a template block (QA_PLAN_START, placeholder SCENARIO
  1, QA_PLAN_END) followed by a truncated real suffix (SCENARIO 2..4,
  QA_PLAN_END).
- When the planner idles after the grace period.
- Then the plan is rejected as incomplete. A START that is separated from the
  final END by an intervening END must never pair with it. No scenarios
  launch. On HEAD cd0432c0 this case is wrongly accepted (repro:
  `qa_plan_problem(TEMPLATE_PROMPT+"\n...redraw...\n"+PANE_SUFFIX, [2,3,4],
  2) is None`), so the code must be fixed. Regressions must cover both the
  validator and `_read_planner_plan` with a missing or non-plan transcript.

R5. Legitimate offset-numbered plans still work.
- Given QA round 2 (scenario_start = 2).
- When the planner emits a complete plan numbered 2..4, or a complete plan
  numbered 1..3.
- Then the plan is accepted. 2..4 is kept as-is and 1..3 is renumbered to
  2..4. Every scenario launches.

R6. Template markers never count.
- Given a planner that only echoes the prompt template (placeholders) and
  whose latest assistant text has no plan.
- When it goes idle.
- Then nothing is accepted and the loop keeps waiting. No placeholder
  scenarios launch.

R7. Freshness.
- Given that a plan was already read and rejected.
- When no new idle_prompt event arrives.
- Then the transcript is not re-read and not consumed. A later re-emission
  that arrives with a fresh idle is accepted.

R8. The planner head is published before fan-out (remote-backed project).
- Given a PR workdir whose origin reaches a real (non-local) upstream, and a
  planner that commits pm/ docs without pushing.
- When the plan is accepted.
- Then the PR branch is fast-forward pushed to the upstream (never forced)
  before any scenario launches. Every scenario clone starts at that exact
  head, and a scenario `git pull --rebase` keeps the planner's commits.

R9. The handoff fails clearly.
- Given that the upstream branch has commits the planner head lacks (the
  branch is behind or has diverged).
- When the plan is accepted.
- Then no scenarios launch, QA is INPUT_REQUIRED, and the message says
  "behind" (pull) or "diverged" (reconcile) and names both shas.

R10. Worker revision consistency.
- Given a scenario whose clone is not at the published planner head (e.g. the
  PR workdir head moved while that scenario was queued).
- When it launches or dequeues.
- Then the scenario is INPUT_REQUIRED with a "refusing to test a different
  tree" reason, not the generic "window never created".

R11. Planner app-code edits force review.
- Given a planner that commits a change outside pm/.
- When every scenario PASSes.
- Then the overall verdict is NEEDS_WORK. The latest output and the QA PR note
  say "planner edited application code (…); review required before sign-off".
  The PR goes back to review, and the NEEDS_WORK survives a QA resume. If the
  planner edits only pm/, the verdict stays PASS.

## Setup
- Follow `pm/qa/instructions/tui-manual-test.md`: venv with this branch,
  `PYTHONPATH=<clone>`, throwaway project, `pm session`, and fake-claude
  config per session type (qa_planning `body`/`preamble`/`preamble_delay`
  control the plan; qa_scenario/verification/finalize verdicts are PASS,
  VERIFIED and FINALIZE_DONE).
- Pane truncation: set tmux `history-limit 0` and use an 80x24 planner pane.
  The impl captures under `impl/{pre,post}-fix/{stall,suffix}` show the
  shape (run from /tmp).
- Missing transcript: stop fake-claude from writing it, e.g. by making the
  `~/.claude/projects/<mangled-cwd>` path non-writable or a file. The fake
  ignores OSError.
- The template-then-suffix pane: a qa_planning body that starts with a
  placeholder SCENARIO 1 and a QA_PLAN_END line, then has SCENARIO 2..4.
  The fake wraps it in START/END.
- scenario_start = 2: run one earlier QA round on the same PR with a single
  scenario (`~/.pm/workdirs/qa/<pr>-*/s-1` exists).
- Real upstream: `resolve_real_origin` needs a non-local URL, e.g. a git
  daemon or ssh on localhost serving a bare repo.

## Edge cases
- The transcript plan is followed by a tool call. The latest turn then has no
  plan, so the loop falls back to the pane (gated) and reports any problem.
- Gaps in numbering (1, 2, 4) are rejected.
- Markdown-wrapped markers (`**QA_PLAN_END**`) are accepted.
- Publishing is a no-op on a local-only project.
- The PR workdir has uncommitted tracked changes. The log warns and QA still
  proceeds.

## Pass/Fail
Pass: every Then above is observable in the TUI, logs, qa_status, tmux
windows or PR notes. Fail: any stall with a complete plan available, any plan
missing leading scenarios that is consumed, any scenario testing a tree other
than the published head, or an all-PASS sign-off after planner app edits.

## Ambiguities (resolved)
1. R4 requires a code fix. Per the supervisor, fix it in this PR through a QA
   scenario, not in planning. Narrow fix: the START used must be the last
   START after the previous END (structural provenance). Older-transcript-turn
   reading stays in pr-8efa789. Any fix is application code and must get
   review afterwards. The fixing scenario reports NEEDS_WORK.
2. The planner makes no application edits during this planning pass.
