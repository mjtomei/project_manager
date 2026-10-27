# pr-e040aeb — native retry of a failed authorized review launch

Bug: after a verdict is collected, the native review loop launches the next
iteration.  That launch first closes the historical review window and then
removes/re-creates the review container.  If the teardown/setup fails, the
`pm pr review` child exits non-zero before the new session produces a
transcript.  `run_review_loop_sync` treats that as a terminal `ERROR`, and the
auto-start scheduler then skips the PR forever because `app._review_loops` still
holds a (non-running) entry.  The target stays stopped until a shepherd sends
`review-loop start` by hand.

This change gives the native loop a bounded, observable, serialized retry of a
*genuinely failed authorized review launch*, preserving loop history and every
piece of surrounding state, and leaves an explicit retryable failure (never a
fabricated agent verdict) when retries are exhausted.

## Requirements (grounded in code)

1. **Classify launch failures instead of ending the loop immediately**
   (`pm_core/review_loop.py`).
   - `_launch_review_window` (the parent-side subprocess runner) already raises
     `RuntimeError` on a non-zero `pm pr review` child.  Introduce
     `ReviewLaunchError(RuntimeError)` carrying `returncode`, `stderr`,
     `stdout`, `artifact`, `retryable`, `reason`; raise it for:
     - child exit non-zero (container teardown/setup failure, route down, …),
     - `subprocess.TimeoutExpired` (the 120 s launch timeout),
     - "review window not found after launch",
     - "transcript symlink exists but no session id / no transcript produced".
   - Do **not** retry a `PaneKilledError` (cancellation / window closure), a
     real agent verdict, or a workspace-trust/permission hold.
   - `ReviewHoldError` classifies a trust/permission/auth hold; `ReviewClosedError`
     classifies a PR that merged/closed while retrying.

2. **Bounded retry inside the loop** (`run_review_loop_sync`).
   - Before *every* attempt (including the first after a failure) run
     `_discover_iteration(...)`.
   - Retry the *same* iteration number (`state.iteration` is not advanced again)
     with exponential backoff `5 s` then `10 s` (`REVIEW_LAUNCH_BACKOFF_BASE`
     doubled per attempt, capped at 60 s), up to
     `REVIEW_LAUNCH_MAX_ATTEMPTS = 3` attempts.  The sleep is chunked
     (≤0.25 s) and checks `state.stop_requested` and PR terminal status, so
     cancellation is prompt and the TUI event loop is never blocked (the retry
     runs on the loop's existing background thread).
   - The attempt budget and next-retry deadline persist on `ReviewLoopState`
     (`launch_attempts`, `retry_iteration`, `next_retry_at`,
     `last_launch_error`, `last_launch_artifact`, `launch_retryable`) so a
     merge-restart resume continues the same episode instead of restarting it.

3. **Rediscover before each retry** (`_discover_iteration`).
   - Recover this iteration's transcript symlink and session id, and look for
     the live review window/pane (prefer the pane whose start command carries a
     `--session-id`, via `pane_transcript_path`, falling back to the shared
     first-pane helper).
   - Outcomes:
     - `verdict` — the failed attempt recovered (or another driver finished):
       adopt the transcript's verdict, do not launch.
     - `adopt` — a live pane whose session matches this iteration, or another
       driver's live review session (no other *loop* owner): poll it instead of
       launching a duplicate.
     - `other_owner` — another native loop (different `loop_id`) holds the
       launch lease: bow out rather than duplicate/supersede it.
     - `pending` — a pane exists but has not exposed its session yet: bounded
       grace, then re-discover.
     - `launch` — nothing live (or only the historical window): launch
       `--fresh` as today.
   - A pane matching the *historical* iteration's session (`state.last_session_id`
     or a lower-numbered transcript) is not adopted; it is replaced by the fresh
     launch, preserving the existing semantics.
   - Another driver's live session is adopted (and its landed verdict read)
     only once *this* loop has launched the iteration (`allow_recovery`); on
     the first attempt an unknown pane is the historical window and is
     replaced.
   - There is no `hold` discovery kind: a workspace-trust/permission prompt is
     detected while polling (`WorkspacePromptWatch` → `WorkspaceTrustBlocked`)
     and converted to `ReviewHoldError` → `HOLD` on both the launch and adopt
     paths.  (Review 385e i2 removed the never-produced kind and its dead
     handlers.)

4. **Serialize retry ownership across drivers and restarts**
   (`pm_core/runtime_state.py`, `pm_core/cli/pr.py`).
   - Add an owner lease to the existing per-PR `runtime_state` action
     (`claim_action_lease` / `release_action_lease` / `get_action_lease`), using
     the same flock-protected read-modify-write.
   - The native loop claims `owner = "loop:<loop_id>"` before each launch and
     refreshes it (every ~30 s) while polling, so a long review keeps ownership.
     A loop whose claim is lost (superseded by `zz d` / another loop) stops
     instead of relaunching over the new owner.  The lease is released when the
     loop completes.
   - `pm pr auto-sequence` checks the lease before launching a review iteration
     in its `in_review` branch; a live `loop:` lease means the native loop owns
     the launch, so the tick reports `running: review` and does not start a
     duplicate.  A dead TUI leaves the lease to expire (TTL 180 s); the TUI
     mount sweep (`sweep_stale_states`) clears it on restart.

5. **Observability: artifact + concise UI error**
   - Write a complete launch artifact for every failed attempt under
     `<transcript_dir>/launch-artifacts/`:
     timestamp, PR/iteration/loop id/attempt, exact command, return code, full
     stdout and **full stderr** (no truncation), plus a copy of the failed
     attempt's prompt file (`<workdir>/pm/prompts/pm_prompt_<sid>.txt`) when it
     exists.  The artifact path is included in the error and persisted.
   - Keep the UI error concise (last meaningful stderr line, capped ~300 chars)
     and include the artifact path.  `runtime_state` records `verdict`,
     `retryable`, `attempts`, `error`, `artifact`, `retry_ready_at`; the TUI log
     announces each retry and the terminal failure; `pm autostart status` /
     the runs popup show `review launch failed (retryable): … [artifact: …]`.
   - New loop outcomes (never agent verdicts): `LAUNCH_FAILED`, `HOLD`,
     `CLOSED`.  `history` gains **no** entry for a failed launch.

6. **Do not strand an auto-start target after exhaustion**
   (`pm_core/tui/auto_start.py`, `pm_core/tui/review_loop_ui.py`).
   - `_auto_start_review_loops` may re-arm a non-running loop whose last outcome
     was a *retryable* launch failure, after `retry_ready_at` (60 s), by calling
     `_start_loop(..., resume_state=state)` — history and iteration numbering
     are preserved and only the un-completed iteration is retried.
   - Cap consecutive re-arm episodes (5); after that the explicit retryable
     failure stays (manual `review-loop start` or a new loop resets it).
     Cancellation (`KILLED`), holds, closures and non-retryable errors never
     re-arm.  Re-arming only happens for a PR in auto-start scope: a loop for
     a PR outside the target set (e.g. a manual loop on an unscoped PR) keeps
     its explicit failure for the user.
   - `_poll_loop_state_inner` schedules one timer for the cooldown so the
     re-arm happens without waiting for an unrelated event.

7. **Preserve everything the retry must not disturb.**
   - The retry reuses the same `pm pr review --fresh --review-loop
     --review-iteration N --review-loop-id L --transcript T` command, so the
     complete prompt, source snapshot, dirty metadata, stashes, captures mount,
     and assigned provider/model/effort are exactly what the child computes for
     the PR; the retry never runs `git clean`/`stash` and never touches
     `stop_before_merge` / merge holds.  It only replaces the PR's own review
     window (never QA/discussion windows) and never re-runs a completed
     iteration.

## Implicit requirements

- `ReviewLoopState` is the unit of persistence; the breadcrumb
  (`autostart-resume.json`) must round-trip the new retry fields and the last
  adopted pane/session so a merge-restart resume both continues the bounded
  budget and can tell the historical window from a live attempt.
- `_adopt_in_flight_review` (restart handoff) must share the discovery logic so
  a resumed loop never polls the wrong session (today it polls its own symlink
  even when another owner's pane is live).
- `set_action_state` must keep merging (not clobber) the lease; the lease helper
  must be atomic and tolerant of a missing/corrupt runtime file.
- The TUI poll (1 s) is the only main-thread place that can log/schedule; retry
  notices and the re-arm timer go there, not in the loop thread.
- Status derivation must treat the new outcomes as failures with actionable
  reasons, not as `PASS`/`NEEDS_WORK`, and `_progress` must not show a stale
  iteration as if it succeeded.
- Existing tests that mock `_run_claude_review`, `_find_claude_pane`,
  `_launch_review_window` and `subprocess.run` must keep working: new
  parameters need defaults; discovery must fall back to `_find_claude_pane`
  when no window can be found.

## Ambiguities and resolutions

1. **Retry budget scope** — per failed launch episode (3 attempts) rather than a
   lifetime cap.  Persisted so a restart mid-backoff continues it.  Auto-start
   may open a new episode after a cooldown (bounded to 5 episodes); a manual
   loop gets one episode and an explicit retryable failure.
2. **Artifact location** — the per-run transcript dir (survives via the
   breadcrumb and is unique per auto-start/manual run), not the QA captures
   tree (captures are planner-only evidence).  Path is surfaced in the UI.
3. **Another driver's live review** — adopt its verdict/pane rather than kill
   it, unless another *native loop* owns the lease; this covers a sign-off route
   or `pm pr auto-sequence` racing a scheduled retry without duplicating work.
4. **Auth/route failures** — a workspace-trust/permission prompt is a hold (no
   retry); an API/auth error (`unauthorized`, `401`, `not logged in`) is
   non-retryable; a transient route/container failure is retryable.  The exact
   low-level teardown exception is unknown (the launch log was truncated), so
   classification is by symptom, not by a single exception type.
5. **Historical window identification** — use the last adopted pane/session id
   plus lower-numbered iteration transcripts; unknown panes fall back to today's
   `--fresh` replacement semantics.

No [UNRESOLVED] ambiguities.

## Edge cases / regressions to cover

- Failure before pane creation (container setup fails immediately).
- Old window removed, then container setup fails; retry must create a fresh
  window and succeed.
- A route/native recovery launches while a retry is scheduled: retry discovers
  and adopts, never launches a duplicate.
- TUI merge-restart during backoff: resumed loop continues the same budget and
  deadline, preserves history, and only retries the un-completed iteration.
- A healthy unrelated review continues unaffected (per-PR state only).
- Cancellation (`stop_requested`, `z d`, `zz d`) during backoff prevents the
  retry; the loop ends `KILLED`.
- Successful replacement executes the original complete task on the assigned
  provider and collects its own verdict (same iteration, loop id, transcript).
- PR merged/closed during backoff stops with an explicit `CLOSED` outcome.
- Trust/permission hold stops with `HOLD` (no retry).
- Exhaustion leaves `LAUNCH_FAILED` with `retryable=True`, full artifact, and no
  fabricated verdict / no history entry.
- Auto-start target is re-armed after the cooldown (not stranded), up to the
  episode cap; manual loops and `KILLED`/`HOLD` are not re-armed.
- `pm pr auto-sequence` does not launch over a live native-loop lease.

## Review iteration 1 (385e) — refinements

Findings from the first review pass, applied on top of the implementation:

1. **Stale transcript adoption (correctness fix).** Requirement 3's "recover
   this iteration's transcript symlink and session id" was unconditional, but
   the transcript dir outlives a loop (`manual-<token>` lives for the whole TUI
   session, and an auto-start run dir is reused across re-arms).  A *new* loop
   on the same PR therefore rediscovered the previous run's
   `review-<pr>-i<N>.jsonl` and adopted its verdict — a `PASS` from a run that
   had already finished — launching no review at all.  `_discover_iteration`
   now takes `allow_recovery`, and `_run_iteration_with_retry` passes it False
   until *this* loop has launched the iteration (`ReviewLoopState.iteration_attempted`,
   persisted in the breadcrumb; `launch_attempts > 0` also enables it for
   pre-existing breadcrumbs).  Recovery/adoption is unchanged after a genuine
   failed attempt, including across a re-arm.
2. **Retry notice gated on a real retry.** `launch_attempts` is 1 for a normal
   first launch, so the poll tick announced "Review launch retry … (attempt 1)"
   on every loop start (and again after each iteration whose attempt count had
   climbed).  The notice now requires `attempts > 1` *and* a recorded
   `last_launch_error`.
3. **Trust hold on the adopt path.** The adopt branch polls the pane directly,
   so a `WorkspaceTrustBlocked` there surfaced as `ERROR`; it is now converted
   to `ReviewHoldError` → `HOLD`, matching `_run_claude_review`.
4. **Re-arm cannot silently disarm.** `_start_loop` returns False when it bails
   (missing PR/workdir, no tmux, unusable transcript dir).  Auto-start clears
   the retry episode *before* starting the thread (it must not resume the spent
   budget), so it now restores the saved episode fields when the start does not
   happen, keeping the failure retryable instead of stranding the target.
5. **Cooldown timer is self-healing.** `_schedule_retry_rearm` was armed once;
   if that single timer fired before `retry_ready_at` (or the pass found the
   PR still cooling), nothing re-armed it and the target waited for an
   unrelated TUI event.  `_auto_start_review_loops` now keeps a timer armed for
   as long as the cooldown is running (never at the episode cap).
6. **Claim "fail open" is real.** `claim_action_lease` returns False both for
   "another loop owns it" and for "the runtime file could not be written"; the
   loop stood down for either, stranding the target on an unwritable state
   dir.  `_claim_launch` now stands down only when another live loop actually
   owns the lease.
7. **Failure artifacts carry the command.** The post-launch failures ("window
   not found", "no transcript session id") wrote `cmd: []`; they now record
   the launch command `_launch_review_window` returned, and `returncode: None`
   since no child exited non-zero.

## Review iteration 2 (385e) — refinements

Findings from the second review pass, applied on top of iteration 1:

1. **Another driver's live review is adopted on a retry (correctness fix).**
   Iteration 1's `allow_recovery` gate made the *first* attempt replace an
   unknown pane (correct), but it also left the retry path replacing one:
   after a launch failed *before* creating a transcript, `our_sid` is None and
   `_discover_iteration` fell through to `launch` even though this loop had
   launched the iteration — so a sign-off route (or another non-loop driver)
   racing a scheduled retry had its live review killed by the retry's
   `--fresh`.  When `allow_recovery` is true and a live pane's session is not
   historical, discovery now reads its verdict or adopts it for polling
   (regression "route/native recovery racing a scheduled retry").  The
   historical-window check is now meaningful instead of both branches
   returning `launch`.
2. **No `hold` discovery kind.** `AttemptDiscovery("hold")` was never produced,
   leaving three unreachable handlers.  Trust/permission holds are detected by
   the poller (`WorkspacePromptWatch` → `ReviewHoldError`) on both the launch
   and adopt paths; the dead kind and handlers were removed.
3. **Progress label is not a retry on the first attempt (UI fix).**
   `_progress` printed `review #N (launch retry 1)` for every running review
   because `launch_attempts` is 1 after a normal launch.  It now requires
   `attempts > 1`, matching the TUI notice's gate.
4. **Lease kept alive through INPUT_REQUIRED.** The follow-up wait could
   outlast the 180 s lease TTL, letting another driver treat the loop as dead.
   `_wait_for_follow_up_verdict` now refreshes the lease too, and a stopping
   loop (`stop_requested`) never refreshes it, so a superseding loop's claim
   cannot be stolen back by the loop it replaced.
5. **Trust hold on the restart handoff.** `_adopt_in_flight_review` (the
   breadcrumb-resume handoff) polls the pane directly, so a
   `WorkspaceTrustBlocked` there surfaced as a terminal `ERROR` (no re-arm).
   It now converts to `ReviewHoldError` → `HOLD`, matching every other adopt
   path.

## Review iteration 3 (385e) — refinements

Findings from the third review pass, applied on top of iteration 2:

1. **A failed launch must not adopt a previous run's transcript
   (correctness fix).** Iteration 1 gated transcript recovery on
   `allow_recovery`, but that flag turns on *after* this loop's first
   attempt fails — and a launch that fails before the child writes the
   symlink leaves the shared transcript dir's older
   `review-<pr>-i<N>.jsonl` in place.  The retry then read that earlier
   run's verdict (a `PASS`, for instance) and recorded it for an iteration
   that never ran: exactly the fabricated verdict requirement 1 forbids.
   `ReviewLoopState.stale_session_id` now snapshots the symlink's session
   id when the iteration's episode starts (persisted in the breadcrumb);
   `_discover_iteration` only treats the symlink as this attempt's when its
   session id differs, and `_is_historical_session` treats the stale id as
   historical so a live pane running it is replaced, not adopted.
   `tests/test_review_launch_retry.py::test_retry_never_adopts_a_previous_runs_transcript`
   covers it; `test_retry_adopts_a_verdict_that_landed_after_the_failure`
   now models a transcript created *by* the failed attempt.
2. **The retry notice is keyed per episode.** `_ui_notified_retry` was
   only reset when a loop (re)started, so a later iteration's attempt 2
   was swallowed as already-announced.  `_reset_launch_retry` (run after
   every successful iteration) clears it.
3. **Dead parameter removed.** `_retry_rearm_blocked(app, loop)` ignored
   `app`; it is now `_retry_rearm_blocked(loop)`.

Note (not changed): a child auth failure (`_looks_like_auth_failure`) is a
non-retryable `LAUNCH_FAILED`, not `HOLD`.  `HOLD` stays reserved for a
pane sitting at a workspace-trust/permission prompt (the launch succeeded);
an auth-rejected child never launched a session.

## Review iteration 4 (385e) — refinements

Findings from the fourth review pass, applied on top of iteration 3:

1. **A container "permission denied" is a retryable launch failure, not an
   auth hold.** `_AUTH_FAILURE_RE` matched `permission denied`, so a
   teardown/mount failure that reports it (a realistic podman/docker
   symptom) was classified non-retryable: the loop stopped after one attempt
   and auto-start did not re-arm — re-creating the stranded target this PR
   exists to fix.  The pattern now covers only real auth/trust symptoms
   (`unauthorized`, `not logged in`, `authentication failed`, `invalid api
   key`, `401`, `403`, `workspace trust`, `trust prompt`).
2. **A starting pane is not killed by a retry.** In the no-own-transcript
   branch, discovery only handled a pane that had already exposed a session
   id; a live pane with no session id yet (a just-started recovery or
   another driver's launch racing the retry) fell through to `launch` and
   was replaced by `--fresh`.  When `allow_recovery` is set it now returns
   `pending`, so the bounded grace applies here too; the first attempt of an
   iteration this loop has not launched still replaces the window.
3. **`_start_loop` marks the loop running synchronously.** The 1 s poll (and
   a second starter — the breadcrumb resume running right after
   `check_and_start` re-armed the same loop) could observe a non-running
   loop between `_start_loop` and the thread body, re-announcing a stale
   terminal verdict or starting a duplicate loop thread.  `state.running` is
   set before `start_review_loop_background`.
4. **Stale retry evidence is cleared on completion.** A loop that succeeded
   after a re-armed failure left the previous episode's `retryable` /
   `error` / `artifact` / `attempts` / `retry_ready_at` in `runtime_state`;
   the completion mirror now drops them for non-failure outcomes.
5. **CLOSED while waiting for another loop's lease.** If the PR merged while
   the loop waited out another loop's lease, it reported a non-retryable
   `LAUNCH_FAILED`; it now re-checks terminal status and reports `CLOSED`.
6. **`_reset_launch_retry` clears `retry_ready_at`** so a spent re-arm
   deadline cannot leak into the next episode (or the breadcrumb).
7. **A raising re-arm starter also restores the episode.** `_start_loop`
   returns False for its own bail-outs, but a raise (e.g. a missing project
   root) escaped with the retry episode already cleared, silently disarming
   the failure.  `_auto_start_review_loops` now treats a raise like a False
   return and restores the saved episode fields.

## Review iteration 5 (385e) — refinements

Findings from the fifth review pass, applied on top of iteration 4:

1. **A failed launch must not adopt the *historical pane's* verdict
   (correctness fix).** Iterations 1 and 3 stopped rediscovery from adopting
   a stale transcript *symlink*, but the same fabrication was still reachable
   through the live pane.  `build_claude_shell_cmd` writes the iteration's
   transcript symlink *before* the child removes the historical window and
   creates the new one, so a launch that fails after the symlink is written
   but before the window is replaced leaves a live pane running the
   *previous* iteration's session.  In the `our_sid` branch (our symlink is
   new, so `our_sid != stale_session_id`) `_discover_iteration` treated any
   other live session as "another driver's review" and returned its verdict —
   i.e. iteration N's `NEEDS_WORK`/`PASS` was recorded for iteration N+1,
   which never ran.  It now consults `_is_historical_session` there too and
   returns `launch`, replacing the stale window exactly as the no-`our_sid`
   branch already did.  Covered by
   `test_discovery_never_adopts_a_historical_pane_after_a_failed_attempt`
   and `test_retry_never_adopts_a_historical_panes_verdict` (both fail
   pre-fix).
2. **The `pending` grace is observable.** `AttemptDiscovery.reason` was set
   but never read; the retry's pending branch now logs it (and the
   "pane never exposed a session" replacement) instead of sleeping silently.
3. **A bare `401`/`403` token is not an auth failure.** `_AUTH_FAILURE_RE`
   still matched the HTTP codes anywhere in the child's stderr, so a 3-digit
   pid, id or port in a container teardown error (e.g. `process 403 exited`,
   `container pm-review-401 not found`) classified a transient failure as a
   non-retryable auth hold — the same re-stranding failure mode iteration 4
   fixed for `permission denied`.  The codes now only count with auth/HTTP
   context (`http`/`api`/`auth`/`status`/`response` within 20 chars, or
   `401 unauthorized` / `403 forbidden`); `forbidden` is matched directly.
   `test_bare_http_code_lookalikes_stay_retryable` covers both directions.
4. **Dead local removed.** `_start_loop`'s unused `mode_label` (pre-existing)
   is gone.

## Review iteration 6 (385e) — refinements

Findings from the sixth review pass, applied on top of iteration 5:

1. **The restart handoff shares the fabrication guard (correctness fix).**
   `_adopt_in_flight_review` called `_discover_iteration` with the default
   `allow_recovery=True`, bypassing iterations 1/3's gate.  A merge restart
   landing in the window between the iteration counter bump and the first
   launch attempt persists `iteration_attempted=False`; on resume the handoff
   could then adopt a previous run's `review-<pr>-i<N>.jsonl` verdict for an
   iteration this loop never ran.  It now passes
   `allow_recovery=iteration_attempted or launch_attempts > 0`, matching
   `_run_iteration_with_retry`.  Covered by
   `test_restart_handoff_does_not_adopt_a_transcript_this_loop_never_launched`.
2. **The handoff falls back to a relaunch when the transcript has no session
   id.** The iteration-2 refactor dropped the old `if not session_id: return
   None` guard, so an adopted transcript whose session id could not be
   recovered went on to `poll_for_verdict`, which raises — turning a
   recoverable race into a terminal `ERROR`.  It returns `None` (the loop
   relaunches) again.  Covered by
   `test_restart_handoff_relaunches_when_the_transcript_has_no_session`.
3. **The retry's adopt path re-reads a just-landed verdict.** The poller only
   wakes on idle events *newer* than its own start, so a verdict that landed
   between discovery and `_poll_for_verdict` would be waited on until the
   pane died.  Both adopt paths now share `_landed_verdict()` (idle event +
   transcript read) before polling; the restart handoff used to inline the
   same check.  Covered by
   `test_retry_adopt_reads_a_verdict_that_landed_before_the_poll`.
4. **Auth classification reads both streams.** `stderr or stdout` ignored a
   real auth error printed on stdout whenever stderr carried any warning, so
   an auth failure was retried (and re-armed) as transient.  The classifier
   now sees `stderr + "\n" + stdout`.  Covered by
   `test_auth_failure_reported_on_stdout_is_not_retryable`.
5. **`_wait_for_claim` claims the iteration it is retrying.** It used
   `state.iteration`; it now takes the iteration explicitly (the only caller
   passes the same value, but the lease metadata must name the iteration
   being launched, not whatever the shared state holds).
6. **A failed thread start no longer leaves the loop "running".**
   `_start_loop` set `state.running = True` before
   `start_review_loop_background`; if the thread could not start, the poller
   and the auto-start scheduler treated the dead loop as live forever.  The
   flag is cleared on the exception path.  Covered by
   `test_start_loop_clears_running_when_the_thread_cannot_start`.
7. **`_review_retry_timer` is declared on the app** (`App.__init__`), like
   `_review_loop_timer`, instead of being created lazily by `getattr`.
8. **An adopted session is remembered as historical (correctness fix).**
   `AttemptDiscovery` now carries the `session_id` its verdict/pane came from,
   and both callers record it on `ReviewLoopState.last_session_id`.  Without
   it, an iteration that adopted another driver's still-live pane (a sign-off
   route racing a retry) left the next iteration rediscovering the same idle
   pane: `_is_historical_session` did not know it, so the loop either adopted
   the same verdict again or waited on an idle event that would never come.
   Covered by `test_adopted_verdict_records_the_session_as_historical` and
   `test_discovery_treats_the_last_adopted_session_as_historical`.

Not changed (documented residuals): `review_loop.py` is ~1360 lines; two
lease mechanisms coexist (`signoff.claim_return_launch` in project.yaml vs
`runtime_state.claim_action_lease`); the retry re-arm's `_progress` label can
show the previous episode's attempt count while the resumed loop runs.
