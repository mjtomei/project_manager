# pr-b8561ac — QA planner handoff: transcript-sourced plan + published head

## Requirements

### R1. Source the planner's plan from the JSONL transcript, not the pane
`pm_core/qa_loop.py::run_qa_sync` (Phase 1 polling loop) currently waits for a
fresh `idle_prompt` hook event for `planner_session_id`, then calls
`tmux.capture_pane(planner_pane, full_scrollback=True)` and parses that.
Claude Code redraws its final message in place, so scrollback can hold only the
tail of a long plan (observed: 1729 of 9409 chars). The single idle event is
consumed, `parse_qa_plan` yields nothing ("has_end but 0 scenarios, likely
prompt template") and the driver waits until the next idle or the 60-minute
`_PLANNER_TIMEOUT`.

Fix: after each fresh idle event, read the planner's latest assistant turn via
`verdict_transcript.read_latest_assistant_text(transcript_path_for(workdir_path,
planner_session_id))` (same as `loop_shared.poll_for_verdict`), and parse that.
`_read_transcript_text`'s session-id glob fallback covers cwd-slug mismatches.
Verified against the real evidence transcript
(`43dbdcf5-….jsonl` truncated to the 16:38 idle): `read_latest_assistant_text`
returns the 9409-char text and `parse_qa_plan` yields all four scenarios.

### R2. Keep the freshness and placeholder guards
- Freshness: the plan is read only after an `idle_prompt` event newer than the
  previous baseline (unchanged `wait_for_event(..., newer_than=...)` gate).
- Placeholders: `parse_qa_plan` still drops `<…>` / `Scenario Title` / `...`
  titles. Prompt-template markers never reach the transcript text, because the
  prompt is a `user` record and `read_latest_assistant_text` only collects
  `assistant` text blocks. A test asserts that a transcript holding only the
  template (as the user prompt) produces no plan.

### R3. Reject incomplete plans, don't accept a truncated suffix
PR note: a pane capture holding SCENARIO 2–4 was accepted by `parse_qa_plan`
without noticing SCENARIO 1 was missing. Add
`qa_plan_problem(text, scenarios, scenario_start) -> str | None` that the driver
applies to any plan before accepting it:
1. A `QA_PLAN_START` line must precede the last `QA_PLAN_END` line.
2. The real (non-placeholder) `SCENARIO N:` headers between that last
   START/END pair must be the parsed scenarios, in the same order.
3. Indices must be contiguous ascending and start at `1` or `scenario_start`
   (the driver already renumbers a plan that started at 1).
An incomplete plan is not consumed. The driver logs the reason, sets
`state.latest_output` to a visible "planner plan incomplete: …" message, and
keeps waiting for the next idle. That is a clear failure, not a silent stall.

### R4. Planner head is published before remote-backed fan-out
PR note (#229 round 2): the planner committed a fix and QA specs but didn't
push. `create_scenario_workdir` `git clone --local`s the PR workdir (so it gets
the unpublished head), then swaps `origin` to GitHub, where the branch is
older. A later `git pull --rebase origin <branch>` in a worker treats the
unpublished head as the old upstream fork point (remote-tracking reflog) and
drops those commits, so the worker silently tests a different tree.

Fix: new `_publish_planner_head(workdir_path, branch) -> str` runs after the plan
is accepted and the spec gate passes, before mock generation and fan-out:
- `head = rev-parse refs/heads/<branch>` in the PR workdir.
- `real_url = push_proxy.resolve_real_origin(workdir)`. If `None` (local-only),
  return `head`; clones track the local workdir directly and nothing can lag.
- `ls-remote real_url refs/heads/<branch>`: if it equals `head`, return it.
- If remote is absent or is an ancestor of `head`: `git push origin
  <branch>:<branch>` (the workdir's dual push URL; never `--force`), then
  re-verify with `ls-remote`.
- Otherwise (remote has commits that aren't in `head`, push failed, or the
  re-verify mismatched): raise `PlannerHandoffError` with a specific message.

`run_qa_sync` turns `PlannerHandoffError` into `INPUT_REQUIRED` +
`state._error` + `latest_output`, and returns without launching scenarios (same
shape as the spec gate).

### R5. Worker revision consistency
`create_scenario_workdir(..., expected_head=sha)` checks that the clone's
`HEAD` equals the published planner head. A mismatch raises with both shas.
`_prepare_scenario` (tmux and container launchers) records the exception text
as the scenario's verdict reason. `_poll_tmux_verdicts` keeps that specific
reason instead of the generic "worker window never created" when it marks the
scenario `INPUT_REQUIRED`. This includes the queued-launch (dequeue) path, where
a late clone is most likely to see a moved head. The check stays strict
equality, not "contains the planner head". An unpublished commit on top of the
published head would bring back the #229 `pull --rebase` loss.

### R6. Planner application-code edits invalidate review
Record the PR workdir's `HEAD` before launching the planner. After publish,
`git diff --name-only <pre>..<published>`. Any path outside `pm/` (pm metadata:
specs, qa instructions, project.yaml) is application code. Store it as
`state.planner_code_changes` and persist it in `qa_resume.json`. In
`_execute_and_finalize`, a non-empty list forces the overall verdict to
`NEEDS_WORK`, with a reason in `latest_output`. `qa_loop_ui` already routes
`NEEDS_WORK` to `in_review` and a new review, so sign-off can't happen without
re-review.

## Implicit Requirements
- The transcript path is `claude_launcher.transcript_path_for(workdir_path,
  planner_session_id)`. `build_claude_shell_cmd` is launched with `cwd=workdir_path`.
- fake-claude (`pm_core/fake_claude.py`) already writes a Claude-format JSONL
  for `qa_planning` and emits `idle_prompt`, so fake-driven QA keeps working.
- `_PLANNER_GRACE` (15 s) existed so pane scraping wouldn't accept the prompt
  template echoed into the pane. Transcript text can't contain the template, so
  the grace applies only to the pane fallback. Otherwise a fast planner (fake)
  whose only idle lands inside the grace would stall.
- The resume path (`resume_qa_sync`) skips planning and publishing, but must
  restore `planner_code_changes` so the verdict override survives a restart.
- Local-only test setups (no real origin) must still work. Publishing is a no-op
  there.

## Ambiguities (resolved)
1. **Pane fallback?** Keep `capture_pane` only as a fallback when the
   transcript yields no complete plan (transcript missing/unreadable). It goes
   through the same completeness gate (R3) and keeps `_PLANNER_GRACE`.
   Transcript-first is the fix. The fallback only preserves behaviour where no
   transcript exists.
2. **Push vs. fail when the planner head is unpublished?** Push (fast-forward
   only). The note asks to "ensure required committed artifacts are
   published". Fail clearly only when a fast-forward push isn't possible or
   doesn't verify.
3. **"Application code"** = any changed path not under `pm/`. Standalone PM
   repos have no `pm/` in the target repo, so every file there counts as app
   code, which is correct.
4. **How to "invalidate review"**: force the QA overall verdict to `NEEDS_WORK`.
   That reuses the existing QA → `in_review` → review-loop route rather than
   adding a new review-state flag.
5. **Uncommitted planner edits** are not published (only commits are). Log a
   warning if the workdir has uncommitted tracked changes. Not a failure.

## Edge Cases
- Plan text after a tool call: `read_latest_assistant_text` returns only text
  after the last tool_result. If the planner emitted the plan and then ran a
  tool, the latest turn lacks the plan. The pane fallback (still gated) and
  the next idle cover this, and the incomplete/no-plan message is visible.
- Supervisor-requested re-emission: the latest turn is the re-emission, so it
  is parsed (desired).
- `scenario_start > 1`: the planner numbers from `scenario_start`. Both 1-based
  and `scenario_start`-based numbering pass R3 (the driver renumbers).
- Push races: a worker push after publish only adds commits on top. The
  ancestor check happens before fan-out, so it doesn't apply.
- Container mode clones use the same `create_scenario_workdir`, so R5 covers
  both launchers.
