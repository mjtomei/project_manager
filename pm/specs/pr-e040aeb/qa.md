# pr-e040aeb — QA spec: bounded retry of a failed review-iteration launch

Source of truth for behaviour: `pm/specs/pr-e040aeb/impl.md` (1,156 lines, incl.
every review iteration). This spec turns it into user-visible stories.

## What the user experiences

A review loop runs iterations. When an iteration produces `NEEDS_WORK`, the loop
launches the next iteration: it closes the historical review window, then
removes/re-creates the review container and starts a new Claude session. If that
launch fails (teardown error, container setup error, route down, timeout), the
old code ended the loop with a terminal `ERROR` and the auto-start target sat
stopped until a human sent `review-loop start` — the bug.

Now: the same iteration is retried up to 3 times with a 5 s then 10 s backoff,
rediscovering before each attempt; the failure is reported as an explicit
`LAUNCH_FAILED` (retryable) with a full launch artifact; auto-start re-arms the
target after a 60 s cooldown (max 5 episodes); and the retry never fabricates a
verdict, never duplicates another driver's launch, and never survives a
cancellation.

## Setup (cross-cutting)

Each scenario builds its own throwaway project (see `tui-manual-test.md`), with:

- `pm init --backend local --no-import`, 1–2 PRs, `pm pr start <id>` so each PR
  has a workdir and a branch.
- A **fake-claude** config for the session so review iterations produce
  deterministic verdicts without a real model:
  `pm fake-claude config set '{"_all": {}, "review": {"verdicts": ["NEEDS_WORK", "PASS"]}}'`
  (scripted per iteration; `delay` is supported per entry, e.g.
  `[{"verdict": "NEEDS_WORK", "delay": 20}, "PASS"]`, which the scenarios use to
  have time to break and repair the launch environment between iterations).
- The TUI started from the test project (`pm session`), auto-start target added
  where the scenario needs it (`pm autostart add <pr>`). New targets default to
  `--wait-for-merge`; the pre-integration `--stop-before-merge` flag is now a
  deprecated alias for it (status prints `[wait-for-merge]`, not
  `[stop-before-merge]`).
- The local-backend scaffold must be pushed and synced before `pm pr start`
  (`pm push` then `git merge pm/sync-*` in the main repo), or start fails with
  "not committed on master yet".
- The fake-claude stand-in and any broken runtime shim must be on the session
  PATH when `pm session` starts (the panes inherit it).
- Auto-start targets are TUI-process state, not project.yaml records: a *plain*
  TUI restart loses them, so re-add after restart when the scenario needs one.
  A `--breadcrumb` restart is supposed to preserve them (master's
  `targets_from_breadcrumb` migration plus this PR's resume-before-scheduler
  ordering), which is itself worth asserting.
- Launch artifacts live under `<project>/pm/transcripts/<run_id>/launch-artifacts/`
  (the `pm/` segment matters).
- `pm autostart status --json` emits `run_id`, `targets` and `runs` at the TOP
  level — read `.runs[0].review` and `.targets[0].state`, not `.status.*`.
- Backoff is 5 s then 10 s between the three attempts; the cooldown before
  auto-start re-arms is 60 s.
- **Restarting the TUI while preserving loop/auto-start state** is
  `pm tui restart --breadcrumb` (it writes the merge-restart marker, so the
  restart saves and then consumes the breadcrumb). A plain restart
  (`ctrl+r` without the marker, or killing the TUI) deliberately loses
  auto-start targets and review-loop state, so it cannot be used to exercise
  the resume path.
- The TUI's own log is the surface for notices: `pm log show` /
  `pm log grep <re>`, plus the on-screen log line (sticky for ~15 s). The
  window-replacement notices (`Killed existing review window '<name>'`) are
  mirrored into that log by the launch child.

### Failure injection (user-level, no source edits)

The launch failure is induced the way a user's host would fail, not by mocking.

- **Primary — container runtime failure** (matches the reported symptom
  "fails while removing/replacing its container"): put a small `podman` (or
  `docker`) shim early on `PATH` that answers `info` with exit 0 (so
  `pm container enable` accepts it) and fails `run`/`create`; then
  `pm container enable`. Because container mode is a global setting read on
  every launch, `pm container disable` repairs the environment mid-backoff, and
  the very next attempt runs Claude on the host with fake-claude.
- **Classification text does NOT come from the shim's run/create stderr**: pm
  wraps any container-creation exception in a generic `ContainerError`
  ("Failed to create container … Is podman running?"), so a shim cannot select
  the wording the loop classifies. To inject classification text, give the shim
  an `image inspect` that exits 1 and set the image name via the normal surface:
  `pm container set image <text>`. The launch child then exits 1 with
  `Image <text> not found in podman. …`, which the loop does classify:
  - `permission denied:latest` → retryable (3 attempts);
  - `process 403 exited` → retryable (3 attempts);
  - `unauthorized:latest` → non-retryable (1 attempt).
- **HOLD — live-inducible** (the earlier spec said it was not): clear the
  fake-claude config, put a `claude` stand-in on the session PATH that prints
  the workspace-trust dialog and blocks, set
  `pm set trust-prompt-grace-seconds 10`, and disable container mode during the
  first backoff (watch `pm log` for "launch attempt 1/3 failed"). The retry
  then launches the stand-in and the loop reports a hold.
- **Alternative — workdir unavailable**: move the PR's workdir aside before the
  next iteration launches (the child cannot create the review window and the
  loop raises "review window … not found after launch", also retryable).

## Requirements

### R1 — A failed next-iteration launch is retried, not terminal

GIVEN a review loop running iteration 1 of a PR (a review window is live and
iteration 1 has produced `NEEDS_WORK`), and the host's container runtime cannot
create a container.
WHEN the loop launches iteration 2,
THEN the launch fails after the historical window has been closed,
  the loop keeps the iteration number at 2,
  it logs a bounded retry (`attempt 1/3 failed … retrying in 5s`),
  and it does not end the loop with a terminal error.

GIVEN the same failure, and the runtime repaired before the next attempt,
WHEN the retry fires,
THEN a fresh review window is created for iteration 2,
  it runs the original complete review task on the assigned provider,
  collects its own verdict (e.g. `PASS`),
  and the loop finishes with that verdict and the PR advances to QA.

GIVEN the retry succeeded,
WHEN the user inspects the loop's history and iteration count,
THEN the history holds only the iterations that actually produced verdicts
  (iteration 1 `NEEDS_WORK`, iteration 2 `PASS`) — the failed launch adds no
  entry and no fabricated `PASS`/`NEEDS_WORK` for an iteration that never ran.

### R2 — The failed attempt is fully preserved in an artifact

GIVEN an attempt failed,
WHEN the user opens the artifact the UI names,
THEN it lives under `<project>/pm/transcripts/<run_id>/launch-artifacts/`,
  and contains timestamp, PR, iteration, loop id, attempt number, return code,
  the exact launch command, the complete (untruncated) stderr and stdout,
  and a copy of the failed attempt's prompt when one exists (skipped, with a
  reason, when the transcript symlink still names a previous run's session).

GIVEN the same failure,
WHEN the user looks at the TUI log / status surfaces,
THEN the message is a concise single-line error (last actionable line, ~300
  chars) plus the artifact path — not the full dump.

### R3 — Exhaustion is an explicit, retryable failure — never a verdict

GIVEN the launch keeps failing for a whole episode (3 attempts, 5 s then 10 s),
WHEN the last attempt fails,
THEN the loop ends with an explicit failed-launch outcome (`LAUNCH_FAILED`,
  retryable) and the PR stays in review (no QA started, no `PASS`/`NEEDS_WORK`
  recorded for that iteration),
  and the loop history gains no entry for it,
  and the TUI announces the failure with the error, the artifact path, and a
  statement about whether an automatic retry will happen.

### R4 — Status surfaces name the failure and the evidence

GIVEN the exhausted failure above,
WHEN the user runs `pm autostart status` (and `--json`) or opens the runs popup
  (`a`),
THEN the target is shown as failed (`phase: failed`, `state: review`) with
  `review launch failed (retryable): …` plus the artifact path exactly once
  (the concise error already names it; the status must not append it again),
  and the JSON entry carries retryable/attempts/error/artifact (top-level
  `runs[0].review`),
  and the session/action picker's review row shows a `[failed; retryable]` badge.

### R5 — Auto-start re-arms the target instead of stranding it

GIVEN an auto-start target whose review launch exhausted its retries,
WHEN the 60 s cooldown elapses with no human action,
THEN auto-start re-arms the same loop (resuming history and the un-completed
  iteration), a new review launch runs, and the target is no longer stopped;
  this repeats for at most 5 episodes and then the explicit failure stays.

GIVEN the same failure on a *manual* loop (or a PR outside the auto-start set),
WHEN the user waits past the cooldown,
THEN nothing re-arms it, and the notice says to run `review-loop start` rather
  than promising an automatic retry.

### R6 — Cancellation wins over the retry

GIVEN a loop backing off after a failed attempt,
WHEN the user cancels it from the review action's fresh mode (`z d`, which
  stops the loop and opens a fresh one-off review) or supersedes it with a new
  loop (`zz d`, the stop-then-start loop action),
THEN the old loop ends `KILLED` (not `LAUNCH_FAILED`), performs no further
  attempt, is not re-armed, and the new review window (fresh review or new
  loop) is the only one and survives.
  After the stop, `pm autostart status` reports `review loop ended KILLED`
  with no retry evidence: `retryable` false, `attempts` 0, empty `error` and
  `artifact` (a cancelled loop is not retryable).

### R7 — Concurrent drivers never duplicate or kill each other's launch

GIVEN a review loop owns the PR's launch (running or backing off),
WHEN `pm pr auto-sequence <pr>` is invoked repeatedly from another pane,
THEN it reports `running: review (owned by loop:…)`, launches nothing, and does
  not kill the loop's review window; the loop still produces exactly one verdict.

GIVEN two PRs with review loops, one failing and retrying,
WHEN both run concurrently,
THEN the healthy PR's review is unaffected and completes normally, and the two
  targets' statuses are reported independently.

### R8 — A TUI restart mid-episode preserves the episode

GIVEN a loop backing off (attempt 1 failed, ~10 s to go) and an auto-start
  breadcrumb written,
WHEN the TUI restarts,
THEN the loop resumes at the same iteration with its remaining attempt budget
  and deadline (it does not restart the 3-attempt budget, does not burn an
  episode, and is not re-armed as a fresh episode),
  and the retry then completes normally; history and the artifact path survive.

### R9 — Classification: transient retries, auth/trust does not

GIVEN a launch fails with a transient container/route error (including a
  "permission denied" teardown message),
WHEN the loop retries,
THEN it retries up to the budget and the target can still be re-armed.

GIVEN a launch fails with an auth symptom (`unauthorized`, `401 unauthorized`,
  `not logged in`, `invalid api key`) on either stream,
WHEN the loop handles it,
THEN it stops after one attempt, reports a non-retryable failure ("needs
  attention"), never re-arms, and still writes the artifact.

GIVEN a review pane sits at a workspace-trust/permission prompt,
WHEN the loop observes it,
THEN the outcome is a hold (`HOLD`) — not a launch failure, not retried — and
  the status reports `review held at a permission prompt: <prompt>` rather than
  an earlier attempt's launch error, with no stale artifact attached (neither
  in `pm autostart status` nor in the TUI's "Review loop done" notice), and the
  target is not re-armed after the cooldown.

## Edge cases

- Failure *before* any pane is created (container setup fails immediately):
  same retry, same artifact, same iteration number.
- Old window removed, then setup fails: the retry must create a fresh window
  and succeed (the R1 story).
- A route/native recovery or another driver's launch starts while a retry is
  scheduled: the retry discovers and adopts it (polls it) rather than launching
  a duplicate `--fresh` window.
- A failed launch leaves the previous iteration's window/transcript live: the
  retry must replace it and must never adopt its older verdict.
- A merge/close during the backoff stops the loop with an explicit closed
  outcome (not a retryable launch failure).
- PR merged while waiting out another loop's launch lease: closed, not failed.
- Exhaustion at the episode cap: the explicit retryable failure stays for a
  human, and nothing is scheduled.
- A second TUI on the same project must not launch a duplicate; it stands down
  and reports that another loop owns the launch.
- A sign-off REVIEW return pending at re-arm time: the re-arm yields so two
  `--fresh` launchers cannot kill each other.

## Pass / fail criteria

Pass = every THEN above is observable on the surface named, on the integrated
PR tree (HEAD after the master@89e3c501 merge); the reproduction test
(`tests/test_review_loop.py::test_failed_launch_is_retried_not_terminal`, which
fails on a clean origin/master worktree) passes and genuinely makes two launch
attempts; the pinned verdict-reader test
(`tests/test_review_launch_retry.py::test_verdict_reader_survives_a_later_wakeup_postscript`)
passes; and the targeted suites (`tests/test_review_launch_retry.py`,
`tests/test_review_loop.py`, `tests/test_breadcrumb_review_loop.py`,
`tests/test_verdict_transcript.py`) pass.

Fail = a failed launch ends the loop with `ERROR`/a fabricated verdict; the
target stays stopped with no re-arm and no explanation; a retry adopts a
previous run's verdict or a previous window; the artifact is missing/truncated;
a cancellation is reported as a launch failure; two drivers produce two review
windows; or a healthy unrelated review is disturbed.

## Post-QA fixes to verify (f076 i1–i3, after the first QA run)

The first QA pass (scenarios 1–6) produced these fixes; scenarios must verify
them on the live surfaces, not just in tests:

1. The TUI retry notice for attempt N now reads
   `Review launch retry for <pr> (attempt N; attempt N-1 failed: …)` — the error
   is labelled as the previous attempt's, and no notice fires for attempt 1.
2. A TUI restart mid-retry no longer re-announces the persisted notice
   (`_ui_notified_retry` round-trips through the breadcrumb; cleared only at an
   episode boundary or an auto-start re-arm).
3. `pm autostart status` prints the artifact path once, not twice.
4. A HOLD's completion notice shows the trust/permission prompt and no
   `Artifact:` line; status says `review held at a permission prompt`.
5. A re-armed retry that is running shows `review iteration N`, not
   `review iteration N (last LAUNCH_FAILED)`.
6. A cancelled (KILLED) loop reports no retry evidence (`retryable`,
   `attempts`, `error`, `artifact` all cleared) — this was the one NEEDS_WORK
   finding of the first QA pass.
7. A retryable per-attempt `launch failed (rc=…)` logs at WARNING while the
   loop keeps retrying; ERROR is reserved for auth failures and for giving up.
8. The `pm session` review row's `[failed; retryable]` badge (previously
   untested).

## Ambiguities resolved

1. **"Automatic retry" wording** — the notice promises an automatic retry only
   where auto-start will actually re-arm (in-scope target, enabled, under the
   episode cap); otherwise it points at `review-loop start`. Asserted as R5.
2. **How to induce the failure** — the low-level teardown exception is
   unconfirmed in the bug report, so scenarios induce a *symptom* (broken
   container runtime / unavailable workdir), which is exactly how the code
   classifies failures.
3. **HOLD reproduction** — superseded by QA scenario 6: a hold IS live-inducible
   (see "HOLD — live-inducible" under Failure injection). The fake-claude
   stand-in never renders the trust dialog, so the scenario swaps in a `claude`
   stand-in for the retry attempt. If a worker still cannot induce it, it must
   cite `tests/test_workspace_trust.py` and the status-rendering tests rather
   than fail the story.
4. **"Another loop owns the launch"** — a second TUI is expected to report a
   non-retryable stand-down (documented residual), not to adopt the first
   loop's review. Scenarios assert the first loop is unharmed; the second TUI's
   own message is recorded as evidence, not asserted as a pass condition.

## Post-QA fixes to verify (1fc4 i1–i2, after the second QA run)

The second QA pass (scenarios 7–11) produced these fixes; scenarios must verify
them on the live surfaces, not just in tests:

1. **Child stderr is escaped before it enters a Rich-markup log line.** The TUI
   retry notice and the failed-completion notice interpolate the launch child's
   own stderr into a Rich-markup log line. A bracketed token (`[podman]`) was
   swallowed and an unbalanced tag (`[/tmp/pm-review]`) raised `MarkupError`,
   which `log_message` drops — so the concise error silently vanished exactly
   when the child's text was interesting. Both notices now escape the stderr
   and the artifact path; the text must render verbatim and the artifact must
   keep the exact stderr.
2. **A resume that cannot start must not strand the target.** After a
   breadcrumb restart, `consume_breadcrumb` restores the saved loop and calls
   `_start_loop`, which returns False when it cannot start (missing workdir, no
   tmux, unusable transcript dir). The resume used to announce "Review loop
   resumed …" anyway and leave a non-running loop entry, and
   `_auto_start_review_loops` skips a PR whose entry is non-running and not a
   retryable launch failure — the stranded target this PR removes, reached
   through a failed resume. The resume now logs honestly, drops the restored
   entry so the scheduler starts a fresh loop, and treats a raising starter the
   same way (it must not take the TUI mount down).
3. **A lease claimed after a stop is handed straight back.** The lease
   keepalive checked `stop_requested` before claiming but the claim is not
   atomic with that check; a supersede (`z d` / `zz d`) landing in between let
   the old loop re-take the lease the replacement needs, and the new loop's
   bounded claim wait expired into a non-retryable `LAUNCH_FAILED`. The
   keepalive now releases the lease when a stop landed during the claim.

New regression tests (fail on the pre-fix tree):
`tests/test_breadcrumb_review_loop.py::test_a_resume_that_cannot_start_drops_the_phantom_loop`,
`tests/test_breadcrumb_review_loop.py::test_a_raising_resume_is_treated_like_a_refusal`,
`tests/test_review_launch_retry.py::test_lease_keepalive_releases_a_lease_claimed_after_a_stop`,
`tests/test_review_launch_retry.py::test_retry_notice_shows_bracketed_child_stderr_verbatim`,
`tests/test_review_launch_retry.py::test_launch_failed_notice_shows_an_unbalanced_tag_in_stderr`.

Also re-verify on the live surface the earlier `f076 i1` item 2: a TUI restart
mid-retry must not re-announce a retry notice the user already saw
(`_ui_notified_retry` round-trips through the breadcrumb).

## Post-QA fixes to verify (scenario 8–9, from the second QA pass)

The second QA pass produced these behaviour/log fixes; scenarios must verify
them on the live surfaces.

1. **Every retry attempt is announced, including the final one.** The retry
   notice is keyed on the *upcoming* attempt while the loop waits out its
   backoff (`next_retry_at` in the future), so an attempt that starts and dies
   inside one poll tick is still announced; each attempt is announced exactly
   once across restarts and across re-armed episodes. A retryable per-attempt
   failure logs `launch failed (rc=…)` at WARNING; ERROR is reserved for an
   auth failure or for giving up.
2. **The auto-start re-arm is visible.** `Auto-start: retrying review launch
   for <pr>` is held long enough not to be replaced in the same tick by
   `Review loop resumed …` (which `_start_loop` logs right after).
3. **The review-window replacement is visible in the log.** On the loop path
   the replacement happens inside the launch child (`pm pr review --fresh`),
   whose stdout is discarded on success; the child's `Killed existing review
   window '<name>'` / `Switched to existing review window '<name>'` notices
   are mirrored into the debug log, so `pm log show` contains the line. It
   appears just *after* `Review loop started`, not before.

Note for test runs:
`tests/test_review_launch_retry.py::test_old_window_then_container_failure_retries_the_same_command`
patches the process-wide `subprocess.run`; run the suites from a shell that is
not inside a tmux pane, or an ambient `tmux display-message` lookup can consume
the "first call fails" slot.

## Third QA pass focus (scenarios 19+, after 1fc4 i1–i2)

The first two QA passes verified R1–R9 broadly. The fixes landed after them are
**not yet exercised on the live surfaces** and are the focus of this pass:

1. **Markup-hostile child stderr (1fc4 i1).** The retry notice and the
   failed-completion notice are Rich markup; the launch child's own stderr is
   now escaped. Live induction: with container mode enabled and a podman shim
   whose `image inspect` exits 1, set the image to a markup-hostile name via
   `pm container set image '<text>'` — the child then exits 1 with
   `Image '<text>' not found in podman. …` and the loop classifies that stderr.
   `[podman]` (bracketed token) must render verbatim; `[/tmp/pm-review]`
   (unbalanced closing tag) previously raised `MarkupError` and the whole
   notice vanished. The artifact must keep the exact stderr either way.
2. **Every retry attempt is announced (7f38066a).** Attempts that start and die
   inside one ~1 s poll tick must still be announced — including the final
   attempt — by announcing the *upcoming* attempt during the backoff. Each
   attempt is announced exactly once, across restarts and across re-armed
   episodes.
3. **The auto-start re-arm is visible (7f38066a).** `Auto-start: retrying
   review launch for <pr>` must survive the `Review loop resumed …` line
   `_start_loop` logs in the same tick (held like the `targets +=`
   confirmation). While the re-armed retry runs, `pm autostart status` reads
   `review iteration N` with no `(last LAUNCH_FAILED)`.
4. **A restart that cannot resume must not strand the target (1fc4 i2).** A
   saved loop whose launch environment refuses to start (unusable transcript
   dir) must not leave a non-running phantom entry that the scheduler skips:
   the TUI says it could not resume, drops the entry, and the scheduler starts
   a fresh loop.
5. **A lease claimed after a stop is handed back (1fc4 i2).** A supersede
   (`z d` / `zz d`) landing between the keepalive's stop check and its claim
   must not leave the replacement waiting out the claim and expiring into a
   non-retryable `LAUNCH_FAILED`. Repeated supersedes during a backoff must
   always produce exactly one working replacement loop.
6. **A restart mid-retry does not re-announce (f076 i1 item 2, re-verify).**
   Scenario 5 observed the duplicate pre-fix; `_ui_notified_retry` now
   round-trips through the breadcrumb.
7. **A PR that leaves review during the backoff.** Merged/closed (terminal)
   must stop the retry with a closed outcome, not a retryable launch failure,
   and must not launch another review.

Shared resources to exercise concurrently: the per-PR launch lease in
`~/.pm/runtime/<pr>.json`, the review window name (`review-<pr>`), the
per-run transcript dir and `launch-artifacts/` dir, and the single
`~/.pm/autostart-resume.json` breadcrumb.

## Post-integration changes to verify (merge of master@89e3c501 + c945 i1–i2)

The branch now merges master@89e3c501 (HEAD after 7541411f and the c945
review fixes). The merge is not itself a user-facing change, but it changes
what a scenario must assert:

1. **The verdict reader is master's `find_verdict_turn`.** `_verdict_output_if_present`
   is the single reader behind retry discovery, the restart-handoff adopt path
   and `_landed_verdict`; the merge moved master's pr-8efa789 fix into it. A
   review transcript whose verdict turn is followed by a later `/loop` wakeup
   turn must still yield the *verdict turn's* verdict. The pre-merge reader
   (`read_latest_assistant_text`) returns the postscript and
   `parse_review_verdict` fabricates `NEEDS_WORK` for a PASS review. Pinned by
   `tests/test_review_launch_retry.py::test_verdict_reader_survives_a_later_wakeup_postscript`
   (which fails with the old reader). Live induction needs a `claude` stand-in
   that writes a native JSONL transcript with [user turn, assistant verdict
   turn, assistant wakeup/postscript turn]; the loop's adopt/retry path must
   record the verdict turn's verdict and finish, not launch another iteration.
2. **A HOLD reports no retry attempt count** (c945 i2). `review_progress_input`
   now drops `attempts` for a HOLD (the runtime_state mirror already did), so
   `pm autostart status` / `--json` show `verdict: HOLD`, `retryable: false`,
   `attempts: 0`, `artifact: ""`, and `error` = the trust/permission prompt.
   The earlier live run (scenario 8) observed `attempts: 2` — that is the
   pre-c945-i2 behaviour and must not be accepted now.
3. **The reproduction test genuinely exercises the retry** (c945 i1).
   `tests/test_review_loop.py::test_failed_launch_is_retried_not_terminal` now
   counts only `--review-loop` launches, so an ambient `tmux display-message`
   probe cannot consume the "first call fails" slot. Run it (and
   `tests/test_review_launch_retry.py::test_old_window_then_container_failure_retries_the_same_command`)
   from a shell that is not inside a tmux pane.
4. **The merge-restart ordering survives.** `consume_breadcrumb` keeps master's
   `targets_from_breadcrumb(data, prs)` migration *and* this PR's ordering
   (resume restored loops before the auto-start scheduler pass), so a
   breadcrumb restart must not start a second fresh loop for a PR whose saved
   loop resumes.

## Fourth QA pass focus (scenarios 24+)

Earlier passes verified R1–R9 broadly. This pass targets the integration and
the fixes landed after the last live run:

1. **Adopt paths read the verdict turn, not a later wakeup turn** (integration
   item 1): retry discovery adopting a user-started review, and the restart
   handoff adopting a live review, both with a verdict-turn + wakeup-postscript
   transcript.
2. **A HOLD carries no retry evidence on any status surface** (c945 i2).
3. **A retry never adopts the window/transcript that predates the episode**
   (385e i1/i3/i10): a previous run's `review-<pr>-i<N>.jsonl` in the shared
   transcript dir, or a review window already live when the episode started,
   must not supply this iteration's verdict; the retry launches fresh. The
   contrast (a review the user starts *during* the backoff is adopted, not
   duplicated) is the boundary and must still hold.
4. **A breadcrumb restart mid-episode on the integrated tree** resumes the same
   iteration with its remaining attempt budget, preserves the auto-start target
   and its policy, starts no second loop, and keeps the failed attempt's
   artifact; a resume that cannot start still drops the phantom entry so the
   scheduler starts a fresh loop.
5. **The reproduction test and targeted suites** pass on the integrated tree,
   and the reproduction test fails on a clean origin/master worktree.

## Known residuals (record as evidence, do not fail a scenario)

- A second TUI on the same project stands down as a non-retryable
  `LAUNCH_FAILED` ("needs attention") rather than adopting the first loop's
  review; the first loop must be unharmed.
- A merge restart during the post-exhaustion re-arm *cooldown* does not persist
  the loop (`save_breadcrumb` saves only running loops): auto-start starts a
  fresh loop instead. The review still runs and no verdict is fabricated; only
  loop history/iteration numbering restarts.
- A stop (`z d` / `zz d`) landing inside the launch child subprocess is not
  noticed until the child returns; the old loop then bows out at its next
  checkpoint (its lease is already released).
- Discovery may adopt a transcript verdict without an idle hook event
  (documented design choice).
