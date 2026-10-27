# Implementation Spec — pr-22ea6a2

## Resume autostart after user feedback in an existing implementation session

### Problem (reproduction #250)

A PR that reached review has a retained implementation session.  The user
stops the review loop, resumes the *existing* implementation pane to give
feedback, and then asks auto-start to take the changed PR through sign-off
again.  Today this cannot work:

* `pm autostart add` only adds a target; it never moves the PR out of
  `in_review`, never retires the stopped review-loop object, and never
  retires the old QA/sign-off evidence.
* `_auto_start_review_loops` (`pm_core/tui/auto_start.py:891`) and
  `_auto_review_idle_prs` (`pm_core/tui/review_loop_ui.py:1160`) both skip a
  PR whenever **any** `ReviewLoopState` object exists for it, including a
  stopped/completed one.  Even manually restoring `in_progress` can leave the
  new implementation completion unable to start a fresh review.
* Prior `PASS` evidence survives in `runtime_state` (QA), `pr["signoff"]`,
  `pr["signoff_return"]` and review-loop transcripts, so a stale result can
  advance the new attempt or suppress a needed QA/sign-off run.
* The existing sign-off `impl` bounce uses `pr start --fresh`, which kills the
  user's live session.  This feature must do the opposite.

### User-requested interface

An explicit **fresh autostart** action is the signal that a later-stage PR is
returning to implementation after human feedback:

* TUI: **`z O`** and **`z A`** — the fresh variants of the two existing
  auto-start enable keys (`O` = stop-before-merge / auto-sequence,
  `A` = auto-merge target).  Plain `O`/`A` keep their continuation semantics
  and plain `a` keeps opening the runs popup.  (An earlier draft of the task
  said `z a`; that was a mistake — `z A`/`z O` are the autostart enable
  keys.)
* CLI: **`pm autostart fresh PR_ID...`** (and the command-bar form
  `autostart fresh PR_ID...`), reached through the existing SIGUSR2 command
  queue exactly like `pm autostart add/remove`.
* Explicitly **not** `pm pr start --fresh`; this is a workflow reset, not a
  fresh implementation client.

## Requirements

### R1 — Explicit reset to implementation (CLI + TUI)

`z O` uses the stop-before-merge policy (matching plain `O`); `z A` uses
the auto-merge policy (matching plain `A`).  Both are always a reset — they
never toggle a target off.

`pm autostart fresh ID...` / `z O` / `z A` must, for each selected PR:

1. Validate all ids up front (all-or-nothing): unknown ids, terminal
   (`merged`/`closed`) PRs, PRs without a `workdir`, and PRs with a merge in
   flight are rejected before anything changes.
2. In **one atomic `store.locked_update`**:
   * set `pr["status"] = "in_progress"` and record the status timestamp
     (`_record_status_timestamp`, `pm_core/cli/helpers.py:446`);
   * write a `pr["fresh_autostart"]` marker (`FRESH_KEY`) with
     `requested_at`, `from_status`, `source`, an incremented `attempt`, the
     effective `policy` (so a TUI restart can restore the target), and
     `awaiting_handoff: True`;
   * close any open `signoff_return` episode (`resolved_at`, `awaiting=None`,
     `superseded_by_fresh_autostart`) so `return_awaiting()` can never force a
     `--fresh` relaunch of the live session;
   * mark the recorded `signoff` verdict invalidated (the existing
     `invalidate_signoff` semantics) and append the prior record to
     `pr["signoff_history"]` before invalidating it, so
     `fresh_recorded_verdict` / `latest_signoff_verdict` /
     `merge_gate_refusal` can never adopt it.
3. Be **idempotent** for repeated calls: a second fresh request while the PR
   is already `in_progress` with `awaiting_handoff` returns
   `already_waiting` and changes nothing.  A fresh request while the PR is in
   a later stage (`in_review`/`qa`/`sign_off`) starts a new attempt.
4. Leave plain `autostart add` / `A` / `O` untouched: they remain a
   continuation from the current phase and never rewind a PR.

### R2 — Adopt the existing implementation session

Fresh autostart must **never** launch or kill the implementation session:

* Do not call `pr start` with `--fresh`; do not send keys to the pane.
* Register/adopt the live implementation pane in `PaneIdleTracker` using the
  pane's own transcript (`pane_transcript_path`, falling back to the run-dir
  `impl-<pr>.jsonl` symlink) so it is trackable after a TUI restart.  The
  registration happens in `review_loop_ui._poll_impl_idle`'s existing lazy
  path: when the run-dir symlink is unavailable (a restarted TUI's run dir is
  new) a fresh-marked PR recovers the pane's native transcript from its start
  command instead of only trust-watching it.  The handoff check itself always
  prefers the pane's native transcript (`autostart_fresh._impl_transcript`),
  so the tracker registration only feeds hook/idle state.
* The scheduler pass that follows only runs `pr start --background`, whose
  existing-window fast path is a no-op (`pm_core/cli/pr.py:955-965`).  If the
  window genuinely does not exist, that is the existing in-progress relaunch
  path (no duplicate is created while one exists).
* Source, workdir, transcript, context and unsent drafts are preserved
  because the pane and its Claude session are untouched.

### R3 — Wait for the completed implementation handoff, exactly once

A fresh attempt in `in_progress` must wait until the current implementation
turn is complete before advancing, and then start **one** fresh review:

* Detect the handoff with `autostart_fresh.handoff_ready()`:
  1. a **new** `idle_prompt`/`Stop` hook event with a timestamp **after**
     `fresh_autostart.requested_at` (old Stop/idle events cannot count), or
  2. the latest transcript turn is structurally complete
     (`latest_turn_state == "complete"`: newest record is an assistant
     message with no pending tool).  This is the authoritative signal and
     does **not** additionally require the hook tracker's idle flag, which
     can be stale or miss the event when `Stop` is written after
     `idle_prompt`.  It covers "already completed before autostart was
     enabled" and a restarted TUI.
* `_poll_impl_idle` routes fresh-marker PRs through this explicit check
  instead of the generic `became_idle()` one-shot, so a stale idle flag
  cannot advance early and a later turn cannot be missed.
* On completion, call the existing `_auto_review_idle_prs`, which transitions
  `in_progress → in_review` via `pr review --no-window` and starts exactly one
  `ReviewLoopState` (the loop object now guards against duplicates).
  `_auto_review_idle_prs` consumes the marker
  (`awaiting_handoff=False`, `handoff_at`, `review_started_at`).
* If the turn is complete at reset time, advance immediately (there is
  nothing to wait for).

### R4 — Retire obsolete loop / QA / sign-off state (preserve evidence)

Before/around the reset, retire the old attempt's live and in-memory state:

* Running review loop: set `stop_requested`, park/kill its review window
  (same as `zz d` supersede), and pop `app._review_loops[pr_id]` so neither
  `_auto_start_review_loops` nor `_auto_review_idle_prs` sees a stale loop.
  Mirror a terminal `runtime_state` sentinel with a new `loop_id` so late
  callbacks from the old thread bow out (`_is_active_loop`).
* Running QA: set `stop_requested`, pop `app._qa_loops[pr_id]` and
  `app._self_driving_qa[pr_id]`; mirror a `qa` runtime record with verdict
  `SUPERSEDED` (and the old verdict under `previous_verdict`) so
  `recorded_qa_verdict` cannot suppress the new QA.
* Sign-off: `signoff.retire_signoff_run()` (window + transcript + launch
  stamp), clear `signoff_ui._signoff_acted` and its launch timestamp; the
  recorded verdict was invalidated in R1.
* Clear `app._pending_merge_prs` / `_merge_input_required_prs` (only after
  refusing an actually-in-flight merge).
* Historical evidence is kept: `signoff_history`, the QA note already on the
  PR, `report.html` / captures, and the underlying Claude JSONL transcripts
  are not deleted.  Only driver-side symlinks/launch stamps are retired, as
  the existing bounce path already does.

### R5 — Stale evidence must not advance the new attempt

* QA: `recorded_qa_verdict(pr_id, pr)` ignores a `runtime_state` `qa` record
  whose `updated_at` predates `fresh_autostart.requested_at` (in addition to
  the existing open-return check).
* Sign-off: `fresh_recorded_verdict` ignores a record whose `ts` predates
  `fresh_autostart.requested_at`; the reset also invalidates the current
  record and archives it.
* Review: the old loop object is removed and late callbacks are fenced by
  the runtime sentinel; the fresh loop overwrites the `i1` transcript
  symlink when it launches.
* Old `Stop`/`idle_prompt` events before `requested_at` never satisfy the
  handoff (R3's timestamp baseline).

### R6 — Clear status in CLI and TUI

While a fresh attempt is waiting, the PR row must say so and why:

* `autostart_state._derive` (used by both `pm autostart status` and the `a`
  runs popup) returns, for `in_progress` + `awaiting_handoff`:
  * missing impl window → `waiting`: "fresh autostart: implementation window
    missing; relaunching";
  * `impl_idle == "waiting"` → "fresh autostart: permission prompt in
    implementation window";
  * `impl_idle == "idle"` → "fresh autostart: implementation turn complete;
    starting fresh review";
  * otherwise → "fresh autostart: waiting for the current implementation
    turn after feedback".
* The CLI prints the reset outcome and the status row (`_print_changes`
  understands the new `fresh_reset` / `already_waiting` actions).
* The TUI log line names the reset and the wait reason.

### R7 — Downstream flow unchanged

After the fresh review PASS, the existing scheduler runs the necessary QA
(`_maybe_start_qa` / `_auto_start_qa_loops`), then sign-off
(`signoff_ui.start_signoff` → `step_signoff`), and stops at the target's
merge policy.  A new target defaults to `stop_before_merge` (manual merge);
an existing target keeps its policy.  Model assignments, spec-review gates,
and the manual merge gate are untouched.

### R8 — Explicit and safe with active later-stage work

If a merge is actually in flight (pending-merge set, merge INPUT_REQUIRED
set, or a live `merge-<display>` window), refuse the fresh request with
`merge_in_progress` rather than resetting underneath it.  Review/QA/sign-off
work is stopped/retired as in R4.  The status transition is one atomic YAML
update; in-memory retirement and window teardown follow and are best-effort.

## Implicit Requirements

* **Store discipline**: flush the TUI write queue before the locked update;
  reload `app._data` afterwards; never call `_load_state()` (it triggers an
  extra scheduler pass) — use `store.load` + `_update_display`.
* **Target registration**: the PR must be an auto-start target so
  `in_scope` is true for `_auto_review_idle_prs`, QA and sign-off.  Use
  `add_targets` (additive, idempotent, policy-preserving) after the reset.
* **Ordering**: reset first (so completion callbacks guarded by
  `from_status` become no-ops), then retire live work, then add the target
  and prepare the handoff.  This avoids `check_and_start` starting a review
  on the still-`in_review` PR.
* **Timer**: arm the shared 1 s poll timer after the reset so handoff
  detection runs even if the old loop was the only thing keeping it alive.
* **Restart safety**: all marker state lives in `project.yaml`; the
  transcript is resolved from the pane command (`pane_transcript_path`), so a
  restarted TUI re-adopts the same session and continues waiting.  Because a
  plain TUI restart drops the in-memory target set, `_deferred_startup`
  re-adds every in-progress, still-awaiting PR as a target using the policy
  recorded on the marker (`resume_pending`).
* **No harness hooks required**: the action is user/agent-invoked; the
  handoff detection reads hook events only as one of two signals and works
  from the transcript when hooks are unavailable.

## Ambiguities (resolved)

1. **CLI verb name** — chose `pm autostart fresh PR_ID...` (minimal, mirrors
   the existing verb set; `add --fresh` would blur the continuation semantics
   of `add`).
2. **PR already `in_progress` without a fresh marker** — reject with
   `not_later_stage` ("use autostart add"); fresh autostart is for returning
   a reviewed PR to implementation, not for starting one.
3. **Repeated fresh request while already waiting** — no-op
   (`already_waiting`), never a second reset or a duplicate review.
4. **Fresh request after the new review already started** (PR back in
   `in_review`/`qa`/`sign_off`) — treated as a new attempt (the user has had
   more feedback since).
5. **Missing implementation window** — allowed; the reset still happens and
   the scheduler's existing in-progress relaunch creates the session.  There
   is no live session to preserve, so no duplicate risk.
6. **Policy of a new target** — `stop_before_merge` (manual merge), matching
   `autostart add` and the acceptance criterion; an existing target keeps its
   configured policy.

## Edge Cases

* **Busy turn at reset**: transcript says `in_progress`; wait for the turn's
  end (new hook event or transcript completion).  No early review.
* **Already-completed turn**: transcript says `complete`; start the review
  immediately.
* **TUI restarted while waiting**: marker is on disk; the impl pane is
  re-adopted via its pane command/transcript; waiting resumes.
* **Old stopped review loop object**: popped; the fresh review starts.
* **Old QA `PASS` / sign-off `SIGNOFF_MERGE`**: predate `requested_at` →
  ignored/refused; the new QA and sign-off run.
* **Late old loop callback**: runtime `loop_id` sentinel makes it bow out.
* **Merge in flight**: refused, nothing changed.
* **Spec pending**: reset is allowed but the handoff wait respects the
  existing `spec_pending` gate (the scheduler will not advance until the
  spec is approved).
* **Multiple PRs in one call**: validate all, reset each, add each target;
  unrelated targets and their policies are untouched.
* **`z O` / `z A` with no selection**: log "No PR selected" and do nothing;
  plain `O`/`A` keep their continuation behaviour and plain `a` still opens
  the runs popup.
* **Auto-start off**: fresh autostart enables it by adding the target.

## Files to change

* `pm_core/autostart_state.py` — `FRESH_KEY`, `fresh_awaiting`,
  `fresh_requested_at`, status reason in `_derive`.
* `pm_core/tui/autostart_fresh.py` (new) — reset, validation, retirement,
  handoff detection, marker consumption.
* `pm_core/tui/auto_start.py` — `fresh` verb in `handle_command` /
  `_dispatch` / `USAGE`.
* `pm_core/tui/review_loop_ui.py` — fresh handoff routing in
  `_poll_impl_idle`; consume the marker in `_auto_review_idle_prs`;
  stale-QA guard in `recorded_qa_verdict`.
* `pm_core/pane_idle.py` — re-arm `idle_notified` on a new `idle_prompt`
  (second-turn detection for the ordinary path).
* `pm_core/verdict_transcript.py` — `latest_turn_state()` tail reader.
* `pm_core/tui/app.py` — `z O` in `action_auto_sequence_pr`, `z A` in
  `action_toggle_auto_start` (policy `stop_before_merge` / `auto_merge`);
  `_deferred_startup` re-arms pending attempts via
  `autostart_fresh.resume_pending`.
* `pm_core/tui/screens.py` — help text.
* `pm_core/cli/autostart.py` — `fresh` command + output.
* `pm_core/signoff.py` — timestamp guard in `fresh_recorded_verdict`
  (fresh-marker aware).
* `tests/test_autostart_fresh.py` (new) — reset/handoff/retirement/resume,
  stale QA and status coverage.
* `tests/test_verdict_transcript.py` — direct `latest_turn_state()` cases
  (tool_use blocks/stop_reason, meta records, pending user turn, oversized
  final record).

## Review-iteration notes (i1)

Implemented as specified, with these refinements from the first review pass:

* **Status accuracy while waiting** — a resumed turn fires no hook at its
  start, so `PaneIdleTracker` still holds the *previous* turn's `idle` flag.
  `retire_in_memory` now calls `tracker.mark_active(pr_id)` when that flag is
  set, so `_derive` reports "waiting for the current implementation turn
  after feedback" instead of the (wrong) "turn complete; starting fresh
  review" for the whole wait (a live permission prompt keeps its own
  reason).  The transcript stays authoritative for the handoff itself.
* **The retirement sentinel is not a QA verdict** — `recorded_qa_verdict`
  ignores a `runtime_state` `qa` record whose verdict is `SUPERSEDED`, so the
  status row cannot say "QA ended SUPERSEDED" and no hold is inferred from it.
* **`consume_handoff` is only written for fresh attempts** — the ordinary
  auto-review path no longer performs a locked project.yaml write it has no
  marker for.
* **Tail reader grows its window** — `latest_turn_state` retries with larger
  tail windows when the smallest one cannot see a turn boundary, so a final
  assistant record larger than 256 KiB (e.g. a big `Write` tool_use) cannot
  read as `unknown` and stall the handoff forever.
* **Repeated `fresh` records an explicit policy** — a second `z O`/`z A`
  while already waiting keeps the same attempt (`requested_at`, `attempt`)
  but updates the marker's `policy`, so a TUI restart re-arms the target the
  user last asked for.
* **No duplicate sign-off history** — an already-invalidated sign-off record
  is not re-archived by a later attempt.
* **Partial failures are surfaced** — the CLI prints `failed:` lines for
  PRs whose reset failed after validation.

## Review-iteration notes (i2)

* **The transcript now really is authoritative** — R3 described the
  transcript as authoritative but the code checked the hook event first.
  A previous turn's `idle_prompt` (newer than `requested_at`) could then
  advance the handoff while the user had already started a follow-up turn,
  launching the review over in-flight work — contradicting the "Busy turn at
  reset: ... No early review" edge case.  `handoff_ready` now reads the
  transcript first: `complete` advances, `in_progress` waits, and the hook
  event is only consulted when the transcript is missing/unreadable (so the
  hook still covers a session whose transcript cannot be resolved).
* **Local-command/meta user records are not a pending turn** — Claude Code
  appends slash-command output (`<command-name>`, `<local-command-stdout>`,
  ...), `isMeta` context and background-task notifications
  (`<task-notification>`) as `type: "user"` records.  `latest_turn_state` now
  skips them, so a `/model` (or a task completing) left at the end of the
  transcript cannot read as `in_progress` and stall the handoff forever.
* **Second-turn idle detection is tested** — `PaneIdleTracker`'s re-arm on a
  new `idle_prompt` (the i1 change) now has a direct regression test.
* **A stale `z` prefix cannot arm the destructive variant** — `z O`/`z A`
  rewind a reviewed PR, so the App-level prefix handler now cancels a pending
  `z` when the next key is not one of the z-actions (`d`/`t`/`s`/`O`/`A`).
  Previously `z`, then navigation, then `A` would have run the fresh reset on
  the newly selected PR instead of a plain auto-merge toggle.

## Review-iteration notes (i3)

* **The z-prefix cancellation covers every z action, and expires on its
  own** — the i2 set (`d`/`t`/`s`/`O`/`A`) omitted the other keys whose
  handlers call `_consume_z()` (`S` start-with-companion, `e`/`v` plan
  panes, `n`/`L`/`m`/`H`/`c` views).  `App.on_key` runs before a binding
  action, so `z e`/`z v`/`z c` ... silently lost their "kill existing before
  next" behaviour.  The set now matches the `_consume_z()` callers (and the
  `check_action` shortcut list).  Navigation keys (`j`/`k`/arrows) are
  stopped by the focused tech tree before `App.on_key` sees them, so the set
  could never cancel a `z` followed by navigation; the prefix now also
  expires after the same 2 s chord window the `w`/`y` prefixes use, which
  closes that gap (a `z`, navigate, `A` chord typed inside 2 s still arms
  the fresh variant — the same window `w`/`y` already accept).

Known limitation (documented, not changed): removing the auto-start target
while an attempt is still waiting does not clear the marker, so
`resume_pending` re-adds the target after a plain TUI restart.  Re-remove it
to stop driving the PR; the PR itself stays in implementation either way.

Second known limitation: the stale-QA fence is timestamp-based
(`runtime_state` `qa.updated_at` vs `requested_at`) and the SUPERSEDED
sentinel covers TUI-owned runs.  An **out-of-process** QA driver launched
before the reset (e.g. `pm pr qa` from a CLI auto-sequence) that finishes
after it would write a `done PASS` record with a post-reset `updated_at`;
that record is indistinguishable from a legitimate new run under the current
schema, so it could still hold the new QA.  The TUI-driven flow (the one this
feature targets) is fenced by popping `app._qa_loops` and by
`_resume_incomplete_qa` refusing to resume a PR that is no longer in `qa`
status.  A fully robust fence needs a per-run id in the QA runtime record.

## Review-iteration notes (i4)

* **Coverage for the two fences that had none** — the sign-off timestamp
  guard (`fresh_recorded_verdict` ignores a pre-`requested_at` record even
  when a racing write never set `invalidated`) and the review-loop
  `SUPERSEDED` sentinel's fresh `loop_id` (the value `_is_active_loop`
  compares, so a late callback from the old thread bows out) are now tested
  directly.
* **Partial reset failures are pinned by a test** — validation reads the
  TUI's in-memory rows while `reset_pr` re-reads disk under the lock, so a
  PR that changed underneath fails its own reset; the test asserts the
  others are still reset and the failure is reported in `failed` for the
  CLI's `failed:` lines.
* **`resume_pending` policy fallback is tested** — an unknown/hand-edited
  marker policy re-arms the target as `stop_before_merge` (manual merge)
  rather than an unrecognised policy.
* **No duplicated resume log line** — `resume_pending` already logs each
  resumed PR through `add_targets`'s confirmation, so `_deferred_startup`
  no longer logs a second, near-identical aggregate line.
* **R2 clarified** — the pane adoption is the existing lazy registration in
  `_poll_impl_idle` (with a fresh-attempt native-transcript recovery), not a
  separate step in `fresh_start`.
