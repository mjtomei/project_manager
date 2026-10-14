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
  with an "incomplete … not consumed" error that tells the user to re-emit,
  and the QA note / completion line carry that reason (not an empty
  "INPUT_REQUIRED — "; 02805ddf).
- Pane fallback with real Claude Code display bullets (0d9c2969): when the
  transcript is missing or holds no plan and the pane holds a COMPLETE plan
  whose markers render as "● QA_PLAN_START" / "⏺ QA_PLAN_END", the plan is
  accepted from the pane. Before 0d9c2969 it stalled with "no QA_PLAN_START
  line before QA_PLAN_END" or paired with the template's closed START.
  fake-claude `display_bullet` draws the bullet in the pane only.

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
- Bare stale START variant (0d9c2969): the template's headers and END have
  been redrawn away, leaving only a stale START, then some text, then
  SCENARIO 2..4 + END at scenario_start=2. This is rejected with "text
  between QA_PLAN_START and SCENARIO 2 … (plan truncated)". Before 0d9c2969
  QA PASSed live over 3 of 4. Residual (not waived, tracked in pr-8efa789):
  a stale START *directly* followed by a 2..4 suffix cannot be told apart
  from a fresh offset plan in the pane. The transcript stays authoritative.

R5. Legitimate offset-numbered plans still work.
- Given QA round 2 (scenario_start = 2).
- When the planner emits a complete plan numbered 2..4, or a complete plan
  numbered 1..3.
- Then the plan is accepted. 2..4 is kept as-is and 1..3 is renumbered to
  2..4. Every scenario launches.
- Transcript offset plan with prose after START (review a6b3 i1, 83f36913):
  in a later round, a complete TRANSCRIPT plan whose QA_PLAN_START is
  followed by prose ("Round three:") before its first header is accepted
  and launches every scenario. The START-adjacency check applies only to
  pane text. At 0d9c2969 this was rejected and the loop stalled.

R6. Template markers never count.
- Given a planner that only echoes the prompt template (placeholders) and
  whose latest assistant text has no plan.
- When it goes idle.
- Then nothing is accepted and the loop keeps waiting. No placeholder
  scenarios launch.
- Narrow-pane wrap (a6b3 i1/i2, 83f36913, 5b74c7e2): when the planner pane
  is narrow enough that template headers wrap ("SCENARIO 1: <descriptive
  title for" or just "SCENARIO 1: <descriptive"), the echoed template still
  never parses as a plan. Pre-fix 0d9c2969 / 83f36913 could treat it as a
  2-scenario plan.
- Real titles that start with "<" ("<Enter> key submits", "<Esc>/<q> close
  the popup", "<Enter>") are real scenarios. They launch with those titles
  and are not dropped as placeholders.

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
1. The R4 fix (4ffcd694) and the later app-code changes (0d9c2969, 02805ddf,
   264f6d01, 254402e8, ae077932, e8e6b5ea) were re-reviewed in a6b3 i1/i2.
   Those reviews themselves changed qa_plan_problem/_is_placeholder_title
   (83f36913, 5b74c7e2). Those are the only app changes since QA round 2, and
   no live QA has exercised them yet. Reading older transcript turns stays in
   pr-8efa789.
2. The planner makes no application edits during this planning pass.
3. Whether the host controller has adopted this PR is unconfirmed, so the
   supervisor's compact-index workaround still applies (note-111b7bb). The
   emitted plan is ≤10 lines: START, then SCENARIO, INSTRUCTION, ARTIFACT and
   a one-line STEPS for each of two scenarios, then END. FOCUS and detail
   live here. Each worker reads its whole section below plus Setup from this
   file in its clone. Workers must check that both scenarios 5 and 6 were
   launched. If one is missing, record that in a PR note (silent intake loss).
4. QA round 2 (scenarios 3/4, workdir pr-b8561ac-9d4327…) drove R1–R11
   live. Both workers ended NEEDS_WORK only because they committed fixes.
   Their captures (scenarios/3, scenarios/4) are pre-review evidence, not a
   sign-off. Round 3 re-tests R1–R11 at the latest branch head (≥ 5b74c7e2)
   and adds the a6b3 cases (R5 transcript prose, R6 narrow-pane wrap). Record
   the tested sha. This is supervised validation, not unattended
   qualification.
5. R11 "returns to review" only applies when the PR is in_review before QA.
   QA on an in_progress PR leaves it in_progress (note from QA S4). Set the
   throwaway PR to in_review first.

## Scenarios (QA round 3; the driver numbers them 5/6)

Scenario 5 — Extraction and complete coverage (R1–R7 + edge cases).
Run every story live with fake-claude in the TUI (tmux recording). Use a
later QA round (scenario_start>1) wherever the story is about offsets.
- Bug repro first, as a CLI recording:
  - `pytest tests/test_qa_planner_handoff.py tests/test_qa_loop.py
    tests/test_qa_note_recording.py tests/test_fake_claude.py` passes on
    HEAD.
  - The pane-truncation regressions fail against master's
    `pm_core/qa_loop.py` (swap the file in a scratch worktree).
- R1/R2: history-limit 0, 80x24 pane, a long 4-scenario plan with a large
  scenario 1.
  - The first idle launches all 4 with their original titles and order.
  - The log says "accepted 4 scenario(s) from transcript".
  - No second idle is needed.
  - Repeat with a pane that keeps only SCENARIO 2..4 + END.
- R3: missing or non-plan transcript plus a truncated pane.
  - Status says "Planner plan incomplete (…)".
  - On planner exit, QA ends INPUT_REQUIRED with "not consumed … re-emit",
    and the QA note carries that reason.
  - Separately, a COMPLETE pane plan with "●"/"⏺" bullet markers and no
    transcript plan is accepted from the pane.
- R4: round 1 with one scenario, then round 2.
  - The pane shows a template block, then a real SCENARIO 2..4 + END.
  - On cd0432c0 the plan is accepted as 2..4 (keep this failed repro).
  - On HEAD it is rejected and nothing launches.
  - Bare stale START + text + 2..4 suffix is rejected on HEAD.
  - An untitled header is rejected, and so are gaps such as 1,2,4.
- R5: in a later round:
  - A complete plan numbered from scenario_start is kept.
  - A plan numbered 1..3 is renumbered.
  - Markdown-wrapped markers are accepted.
  - NEW: a transcript plan with prose between START and the first header is
    accepted from the transcript. Pre-fix 0d9c2969 stalls.
- R6:
  - A template-only echo with no plan in the latest turn is not accepted.
  - NEW: a narrow planner pane (e.g. 30–40 cols) that wraps the template
    headers is still not a plan. Pre-fix 83f36913 shows the
    "<descriptive"-only wrap.
  - NEW: a plan whose titles start with "<Enter>" / "<Esc>/<q>" launches
    every scenario with those titles.
- R7: after a rejection with no new idle, nothing is re-read or consumed. A
  re-emitted complete plan with a fresh idle is accepted.
- Edge: a plan followed by a tool call falls back to the gated pane.
- Concurrent: a second tmux client attaches, resizes and redraws the planner
  window during emission. Extraction still comes from the JSONL.

Scenario 6 — Published revision and review routing (R8–R11).
Use a file:// upstream per Setup. Record TUI runs with tmux recording and
git checks with CLI recording.
- R8: the planner commits pm/ docs without pushing.
  - Before fan-out, the branch is fast-forward pushed (never forced).
  - Every s-N (N≥1) clone HEAD equals the published sha.
  - `git pull --rebase` inside a scenario keeps the planner commits.
- R9: a second clone pushes to the PR branch during planning.
  - A never-fetched, strictly-behind workdir gives "is behind … Pull".
  - A diverged workdir gives "diverged … Reconcile" and names both shas.
  - Either way, no scenario launches and QA is INPUT_REQUIRED.
  - The QA note names the failure, not "?" (264f6d01).
  - The upstream is unchanged.
- R10: with concurrency cap 1, move the PR workdir head while a scenario is
  queued. That scenario becomes INPUT_REQUIRED with "refusing to test a
  different tree" (not "window never created").
- R11: an in_review PR whose planner commits a change outside pm/, and all
  scenarios PASS.
  - The verdict is NEEDS_WORK.
  - The latest output and the PR note say "planner edited application code
    (…); review required before sign-off".
  - The PR returns to in_review.
  - The NEEDS_WORK survives a QA resume.
  - With pm/-only edits the verdict is PASS.
- Stop/fresh start (254402e8): stopping QA mid-run does not relaunch a
  killed scenario window after its retry backoff. Unverdicted scenarios
  aggregate to INPUT_REQUIRED, not PASS.
- Concurrent: two PRs run QA at once in one session, one with app edits and
  one pm/-only.
  - Each gets its own verdict and transcript plan.
  - Both notes land in project.yaml.
  - TUI log lines keep the "[pr-id]" / "[finalize: …]" prefixes (ae077932).
- Edge: on a local-only project publishing is a no-op. Dirty tracked changes
  produce a warning and QA proceeds.
