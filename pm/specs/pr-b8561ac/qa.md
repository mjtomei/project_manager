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
  launch. The status says "Planner plan incomplete (QA_PLAN_START belongs to
  an earlier, already-closed block …)" or "(… prompt-template example
  headers …)". History: HEAD cd0432c0 wrongly accepted this case (repro:
  `qa_plan_problem(TEMPLATE_PROMPT+"\n...redraw...\n"+PANE_SUFFIX, [2,3,4],
  2) is None`). It was fixed in 4ffcd694 (review 78b2 i1). QA must show it
  live on HEAD and keep the failed repro (check out cd0432c0 → accepted;
  HEAD → rejected). An untitled `SCENARIO N:` header inside the block also
  rejects the plan.

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
- Real upstream: `resolve_real_origin` needs a non-local URL. A file:// bare
  repo works because "://" counts as non-local, and pm init auto-detects the
  vanilla backend. Prepend a dir to PATH that symlinks `git` to
  /usr/bin/git, because the ~/.local/bin git proxy forwards ls-remote/push to
  the host. Seed and push `pm/specs/<pr>/qa.md` on the PR branch, or the spec
  gate stops QA before the handoff. s-0 is cloned before planning, so it is
  not pinned (note-51506a2).
- Install: `./install.sh --local` from the clone if pm is missing.
- Artifacts (the emitted plan carries no ARTIFACT lines; read the recipes
  from the clone):
  - `pm/qa/artifacts/tmux-screen-recording.md`: every TUI/QA-loop story
    (pane transcript + asciinema).
  - `pm/qa/artifacts/cli-recording.md`: pytest runs, git/upstream checks, and
    the pre-/post-fix repro commands.
  - Per story, also save to the per-PR captures dir: the pm debug log,
    qa_status JSON, the planner pane capture, the planner JSONL transcript,
    the tmux window list, and `pm pr note` output.
- Instruction: `pm/qa/instructions/tui-manual-test.md` for both scenarios.
- Live pre-/post-fix for R4: make a second worktree at cd0432c0 (the
  reviewed pre-fix code) and run the same R4 setup there with that
  worktree's pm (PYTHONPATH) and with the branch head. Record the head sha
  you test; it must be the latest branch head (≥ 4ffcd694).

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
1. R4 is fixed in 4ffcd694 (structural START/END provenance). That is
   application code edited after the last review, so it must be reviewed
   again before sign-off. QA re-exercises it live (S4). Reading older
   transcript turns stays in pr-8efa789.
2. The planner makes no application edits during this planning pass.
3. The host controller is still 6cfd047e. It reads the plan from the pane,
   and a redraw drops leading headers (note-111b7bb). Per the supervisor, the
   emitted plan is a 6-line index (START, two SCENARIO/STEPS pairs, END)
   with no FOCUS/INSTRUCTION/ARTIFACT lines. Each worker reads its whole
   section below plus Setup from this file in its clone.
4. Prior rounds have no independently VERIFIED scenarios: both round-1
   workers ended NEEDS_WORK. Their findings (e8e6b5ea, ae077932) are fixes,
   not qualified coverage. This round re-tests every requirement R1–R11 at
   the latest branch head. If the current code passes, no further
   application edit is needed. This is supervised validation, not unattended
   qualification.

## Scenarios (QA round 2; the driver renumbers 1/2 to its offset)

Scenario 1 — Extraction and complete coverage (R1–R7 + edge cases).
Run every story live with fake-claude in the TUI (tmux recording).
- Bug repro first, as a CLI recording:
  - `pytest tests/test_qa_planner_handoff.py` passes on HEAD.
  - The pane-truncation regressions fail against master's
    `pm_core/qa_loop.py` (swap the file in a scratch worktree).
- R1: history-limit 0, 80x24 pane, a long 4-scenario plan with a large
  scenario 1.
  - The first idle launches all 4 scenarios with their original titles and
    order.
  - The log says "accepted 4 scenario(s) from transcript".
  - QA reaches a verdict with no second idle.
- R2: the pane keeps only SCENARIO 2..4 + END. All four scenarios still
  launch.
- R3: missing or non-plan transcript plus a truncated pane.
  - Status says "Planner plan incomplete (…)".
  - On planner exit, QA ends INPUT_REQUIRED with "not consumed … re-emit".
- R4 (offset fallback):
  - Setup: round 1 with one scenario, then round 2 (scenario_start=2). The
    transcript is missing or holds non-plan text. The pane shows a template
    block (START, placeholder SCENARIO 1, END) then a real SCENARIO 2..4 +
    END.
  - On cd0432c0 the plan is accepted as 2..4 (keep this failed repro).
  - On HEAD it is rejected as incomplete and nothing launches.
- Header checks: an untitled `SCENARIO N:` header inside the block is
  rejected. Gaps such as 1,2,4 are rejected.
- R5 (valid later-round plans): in round 2, a complete plan numbered 2..4 is
  kept, and one numbered 1..3 is renumbered to 2..4. All scenarios launch.
  Markdown-wrapped markers are accepted.
- R6: a template-only echo with no plan in the latest turn. Nothing is
  accepted and the loop keeps waiting.
- R7: after a rejection with no new idle, nothing is re-read or consumed. A
  re-emitted complete plan with a fresh idle is accepted.
- Edge: a plan followed by a tool call falls back to the gated pane.
- Concurrent: a second tmux client attaches and redraws the planner window
  during emission. Extraction still comes from the JSONL.

Scenario 2 — Published revision and review routing (R8–R11).
Use a file:// upstream per Setup. Record TUI runs with tmux recording and
git checks with CLI recording.
- R8: the planner commits pm/ docs without pushing.
  - Before fan-out, the branch is fast-forward pushed (never forced).
  - Every s-N (N≥1) clone HEAD equals the published sha.
  - `git pull --rebase` inside a scenario keeps the planner commits.
- R9: a second clone pushes to the PR branch during planning.
  - A strictly-behind, never-fetched workdir gives "is behind … Pull".
  - A diverged workdir gives "diverged … Reconcile" and names both shas.
  - Either way, no scenario launches, QA is INPUT_REQUIRED, and the upstream
    is unchanged.
- R10: with concurrency cap 1, move the PR workdir head while a scenario is
  queued. That scenario becomes INPUT_REQUIRED with "refusing to test a
  different tree" (not "window never created").
- R11: the planner commits a change outside pm/ and all scenarios PASS.
  - The verdict is NEEDS_WORK.
  - The latest output and the PR note say "planner edited application code
    (…); review required before sign-off", and the PR returns to review.
  - The NEEDS_WORK survives a QA resume.
  - With pm/-only edits the verdict is PASS.
- Concurrent: two PRs run QA at once in one session, one with app edits and
  one pm/-only. Each gets its own verdict and transcript plan, both notes land
  in project.yaml, and TUI log lines keep the "[pr-id]" prefix.
- Edge: on a local-only project publishing is a no-op. Dirty tracked changes
  produce a warning and QA proceeds.
