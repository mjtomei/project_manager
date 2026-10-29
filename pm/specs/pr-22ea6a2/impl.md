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

* TUI: **`z a`** is the generic fresh autostart (the shortcut the user asked
  for).  **`z O`** and **`z A`** are explicit-policy variants of the two
  existing auto-start enable keys (`O` = manual merge / auto-sequence,
  `A` = auto-merge target).  Plain `a` keeps opening the runs popup, and plain
  `O`/`A` keep their continuation semantics.

  Policy mapping: `z a` passes no explicit policy, so an existing target keeps
  its own policy — **including `wait_for_merge`, whose hold covers its whole
  dependency chain** (coordinated with sibling #261) — and a *new* target
  defaults to `wait_for_merge` (the single manual merge gate).  `z O` forces
  `wait_for_merge` and `z A` forces auto-merge.

  *(Superseded by the master merge of 2026-10-29: master removed
  `stop_before_merge` as a distinct policy.  There is now one manual policy,
  `wait_for_merge`, which holds the target **and its whole unmerged dependency
  closure**; `auto_merge` is the only other.  `--stop-before-merge` is accepted
  only as a deprecated alias for `--wait-for-merge`.  A fresh request's
  new-target default therefore became `wait_for_merge` — the same "manual merge
  gate" the acceptance criterion asks for, now with the dependency-wide hold.)*
* CLI: **`pm autostart fresh PR_ID...`** (and the command-bar form
  `autostart fresh PR_ID...`), reached through the existing SIGUSR2 command
  queue exactly like `pm autostart add/remove`.
* Explicitly **not** `pm pr start --fresh`; this is a workflow reset, not a
  fresh implementation client.

*(Correction, 2026-10-27: the recorded task and the implementation launch
prompt explicitly ask for lowercase `z a`; the earlier spec text that
dismissed it as a mistake was not a recorded user instruction.  `z a` is now
implemented alongside `z O`/`z A`.)*

## Requirements

### R1 — Explicit reset to implementation (CLI + TUI)

`z a` passes no explicit policy (preserve an existing target's policy,
default a new target to `wait_for_merge` — the manual merge gate); `z O` forces
`wait_for_merge` (matching plain `O`); `z A` forces the auto-merge policy
(matching plain `A`).  All three are always a reset — they never toggle a
target off.

`pm autostart fresh ID...` / `z a` / `z O` / `z A` must, for each selected PR:

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
   `already_waiting` and keeps the attempt (`requested_at`, `attempt`,
   handoff baseline) intact.  The one thing it may change is the marker's
   `policy`: an explicitly requested policy (`z O` / `z A` / a CLI flag)
   replaces the recorded one so a TUI restart re-arms the target the user
   last asked for.  A fresh request while the PR is in a later stage
   (`in_review`/`qa`/`sign_off`) starts a new attempt.
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
* An `[Request interrupted by user]` / `... for tool use` marker (Esc during
  a turn) also ends the turn, but only when its own timestamp predates
  `requested_at`: an abort written *after* the request may be followed by a
  retyped prompt, so it keeps waiting.  Without the pre-request case the
  handoff stalls forever with the pane sitting at the prompt.
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
  the existing open-return check), and treats the reset's `SUPERSEDED`
  retirement sentinel as "no verdict" so a discarded run can neither
  suppress the new QA nor appear as a result.
* Sign-off: `fresh_recorded_verdict` ignores a record whose `ts` predates
  `fresh_autostart.requested_at`; the reset also invalidates the current
  record and archives it.
* Review: the old loop object is removed and late callbacks are fenced by
  the runtime sentinel (a terminal `review-loop` record with `SUPERSEDED`
  and a fresh `loop_id`, which `_is_active_loop` compares against); the
  fresh loop overwrites the `i1` transcript symlink when it launches.
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
merge policy.  A new target defaults to `wait_for_merge` (the manual merge
gate); an existing target keeps its policy.  Model assignments, spec-review
gates, and the manual merge gate are untouched.

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
6. **Policy of a new target** — `wait_for_merge` (the manual merge gate),
   matching `autostart add`'s default and the acceptance criterion; an
   existing target keeps its configured policy.  (Before the 2026-10-29
   master merge this was the now-removed `stop_before_merge`, whose only
   difference was that it did not hold the dependency closure.)

## Edge Cases

* **Busy turn at reset**: transcript says `in_progress`; wait for the turn's
  end (new hook event or transcript completion).  No early review.
* **Already-completed turn**: transcript says `complete`; start the review
  immediately.
* **Interrupted turn**: an abort marker that predates the request ends the
  turn (review starts); one written after it keeps waiting.
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
* **`z a` / `z O` / `z A` with no selection**: log "No PR selected" and do
  nothing; plain `a` still opens the runs popup and plain `O`/`A` keep their
  continuation behaviour.
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
* `pm_core/tui/app.py` — `z a` in `action_show_auto_runs` (policy `None`:
  preserve the target's policy, default `wait_for_merge`), `z O` in
  `action_auto_sequence_pr` (policy `wait_for_merge`), `z A` in
  `action_toggle_auto_start` (policy `auto_merge`); plain `a` keeps opening
  the runs popup; `_deferred_startup` re-arms pending attempts via
  `autostart_fresh.resume_pending`.
* `pm_core/tui/screens.py` — help text.
* `pm_core/cli/autostart.py` — `fresh` command + output.
* `pm_core/cli/tui.py` — `pm tui keys` reference: the fresh chords and the
  `autostart fresh` verb.
* `pm_core/cli/__init__.py` — `pm`'s command list names `autostart fresh`.
* `README.md` — the auto-start section: `z a` / `pm autostart fresh`.
* `pm_core/signoff.py` — timestamp guard in `fresh_recorded_verdict`
  (fresh-marker aware).
* `tests/test_autostart_fresh.py` (new) — reset/handoff/retirement/resume,
  stale QA and status coverage.
* `tests/test_verdict_transcript.py` — direct `latest_turn_state()` cases
  (tool_use blocks/stop_reason, meta records, pending user turn, oversized
  final record).
* `tests/test_pane_idle.py` — the second-turn `idle_prompt` re-arm
  (`became_idle()` fires again for a resumed turn).
* `tests/test_review_loop_terminal_state.py` — a superseded loop must not
  finalize the successor's live `review-<pr>-i<n>.jsonl` symlink.

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

## Review-iteration notes (i5)

* **Lowercase `z a` implemented** — the recorded task and the implementation
  launch prompt explicitly ask for `z a`, and no recorded user instruction
  replaces it; the earlier spec text that dismissed it as a mistake was not a
  user correction.  `a` now consumes the `z` prefix: plain `a` still opens the
  runs popup, and `z a` calls `fresh_start(policy=None, source="key:za")`.
  `z O` / `z A` remain as the explicit stop-before-merge / auto-merge
  variants.  `"a"` was added to `_Z_PREFIX_KEYS` and the prefix hint, help
  screen, README and CLI/module docstrings now name `z a`.
* **`z a` is the policy-preserving mapping** — `policy=None` keeps an existing
  target's own policy, so a `wait_for_merge` target keeps its dependency-wide
  hold (coordinated with sibling #261) instead of being silently downgraded to
  a single stop mark; a new target still defaults to `stop_before_merge`
  (manual merge).  `z O`/`z A` force the policy as before.
* **Tests** — `z a` key wiring (policy `None`, `source="key:za"`), plain `a`
  opening the popup, `z a` with no selection, `"a"` in the z-prefix key set,
  and the policy mapping (new target → stop; existing `wait_for_merge` /
  `auto_merge` target preserved).

## Review-iteration notes (367f i4)

* **The remaining untested safety fences now have direct coverage** — the
  `return_awaiting(pr) == "impl"` guard in `handoff_ready` (a racing sign-off
  bounce still expecting a fresh impl launch must not let a complete *old*
  turn count as the handoff), and the live-merge-window branch of
  `_merge_in_progress` (a merge whose in-memory sets were lost across a
  restart still refuses the reset).
* **R2's restart recovery is pinned** — `_poll_impl_idle` recovering a fresh
  attempt's pane from its native transcript when the new run dir's
  `impl-<pr>.jsonl` symlink is missing is now tested (tracker registered,
  no trust-only fallback).
* **R4's teardown is pinned** — `retire_in_memory` parks + kills the old
  review window (matching the `z d` supersede path) and
  `retire_downstream` retires the sign-off run via
  `signoff.retire_signoff_run` (window + transcript + launch stamp).
* Test module docstring now names `z a` alongside `z O` / `z A`.

## Review-iteration notes (367f i5)

* **Every later stage is covered** — R1 allows a fresh request from
  `in_review`, `qa` *and* `sign_off`, but only the `in_review` source was
  tested.  `TestFreshStart::test_rewinds_from_every_later_stage` now runs the
  full `fresh_start` path from `qa` and `sign_off` (validated, reset,
  marker `from_status`, target added, no review started).
* **Repeated resume calls are pinned** — the acceptance list asks for
  "repeated resume calls"; `TestResume::test_resume_pending_is_idempotent`
  calls `resume_pending` twice and asserts the second scan returns `[]` and
  the target set is unchanged (the `pr_id in get_targets` guard).
* **`handoff_ready`'s hook fallback is documented accurately** — the hook
  event can only be consulted when the transcript *path* still resolves (its
  session id is how the event is found).  With no resolvable path nothing can
  advance; the scheduler's in-progress relaunch / the poll's pane re-adoption
  has to restore one first.  Docstring only; no behavior change.

## Review-iteration notes (2aac i1)

* **`!` shell-command records are not a pending turn** — Claude Code records
  ``!`` commands as non-meta `type: "user"` string records
  (`<bash-input>`, `<bash-stdout>`, `<bash-stderr>`, verified against real
  transcripts).  `latest_turn_state` treated them as a submitted prompt, so a
  `!git status` left at the end of the implementation transcript read as
  `in_progress` and stalled the fresh handoff until the user sent a real
  prompt.  Added to `_NON_PROMPT_USER_PREFIXES` with a direct test.
* **A late old-loop completion can no longer freeze the new loop's
  transcript** — `_on_complete_from_thread` finalized every
  `review-<pr>-i<n>.jsonl` symlink in the (shared) run dir *before* the
  supersede check.  A superseded loop can finish up to its 15 s verdict-poll
  timeout after the reset, i.e. after the fresh loop has created its own
  `review-<pr>-i1.jsonl` symlink — finalizing that would replace the live
  symlink with a snapshot the new loop's verdict poller never sees updated,
  so the fresh review could hang.  Finalization now happens only when the
  loop still owns its `runtime_state` entry; superseded loops leave their
  symlinks in place (the successor's completion and `_disable`'s
  `_finalize_all_transcripts` still finalize them, and the JSONLs are never
  deleted).  Pinned by two tests (superseded → no finalize; active →
  finalize).
* **Partial reset failures are visible in the TUI** — the CLI prints
  `failed:` lines from the reply payload, but the key path only shows the
  log line, which omitted them.  `fresh_start` now appends
  `— failed: <id> (<error>)` to the logged message (the returned `message`
  is unchanged, so the CLI output does not duplicate it).
* **One key handler for the three fresh chords** — `z a`/`z O`/`z A` were
  three near-identical 20-line blocks in `app.py`; they now call
  `_fresh_autostart_from_key(policy, source, no_selection)`.  No behavior
  change (the existing key-wiring tests still pin policy/source).

## Review-iteration notes (2aac i2)

* **Shared review-window teardown** — the ``z d`` path, the ``zz d`` supersede
  path and ``autostart_fresh`` each carried their own find-window → park →
  kill copy; they now share ``park_and_kill_review_window()`` in
  ``review_loop_ui`` (same park-by-id / kill-by-name behavior, only when the
  window is found, failures logged at debug).  No behavior change.

## Review-iteration notes (2aac i3)

* **A streamed thinking block is not a completed turn** — Claude Code writes
  a message's content blocks as separate records while it streams and only
  fills ``stop_reason`` in once the message is complete.  ``latest_turn_state``
  read a trailing ``stop_reason: null`` assistant record as ``complete`` even
  when it carried only a thinking block, so a fresh attempt could hand off to
  review while the implementation agent was still mid-turn (the thinking
  window measured 4–42 s in real transcripts, which the 5 s poll lands in).
  A ``stop_reason: null`` record with no answer ``text`` now reads as
  ``in_progress``; the answer text record — the last thing a turn writes —
  still ends it.  Verified against every transcript under
  ``~/.claude/projects`` (all 9 ``stop_reason: null`` thinking-only records
  are followed by another assistant record; the 7252 ``text`` ones are all
  followed by a user record or EOF).  Pinned by two direct tests.

## Review-iteration notes (2aac i4)

* **A compaction summary is not a submitted prompt** — when a session runs
  out of context, Claude Code writes the compaction summary ("This session is
  being continued from a previous conversation…") as a plain-string
  ``type: "user"`` record flagged ``isCompactSummary`` (with
  ``isVisibleInTranscriptOnly``).  ``latest_turn_state`` read it as a pending
  prompt, so a session that ended right after compacting read ``in_progress``
  and stalled the fresh handoff until the user typed something.  In the local
  corpus every such tail record (162 of 13,469 transcripts) is preceded by a
  completed ``end_turn`` assistant answer, so skipping it reads ``complete``
  — the right answer.  ``_is_non_prompt_user_record`` now skips the precise
  ``isCompactSummary`` flag (not the broader
  ``isVisibleInTranscriptOnly``): a false ``in_progress`` is recoverable,
  a false ``complete`` would start the review over in-flight work.  Two
  direct tests (summary after a completed turn → ``complete``; summary over
  an unanswered prompt → ``in_progress``).

## Review-iteration notes (2aac i5)

* **A failing handoff launch is no longer retried every poll tick** — R3's
  handoff check is cheap and idempotent, so ``_poll_impl_idle`` runs it every
  tick.  But the *launch* it triggers (``_auto_review_idle_prs`` →
  ``pr review --no-window``) leaves the PR in ``in_progress`` when it fails
  (store lock timeout, corrupt YAML, subprocess error), so the transcript
  still reads ``complete`` and the next ``_poll_impl_idle`` tick (every fifth
  1 s tick, ~5 s) ran the whole thing again — a subprocess plus two log
  lines, forever, on the TUI thread.
  ``autostart_fresh.handoff_attempt_due()`` now rate-limits the launch to one
  attempt per ``_HANDOFF_RETRY_SECONDS`` (15 s) per PR, recorded on the app
  (``_fresh_handoff_attempts``, so a restarted TUI retries at once).  It is
  evaluated *after* ``handoff_ready`` (short-circuit), so a waiting PR never
  burns its window and the first launch after the turn completes is
  immediate; ``fresh_start``'s explicit immediate handoff is unaffected.
  Pinned by a poll-routing test (two ticks inside the window → one launch,
  after the window → a second).

## Review-iteration notes (2aac i6)

* **The CLI twin of the help screen names the fresh chords too** — the
  in-TUI help screen (`?`), the README, `pm autostart --help`, the command
  bar's `USAGE` and `pm`'s command list all name `z a` / `z O` / `z A` and
  `autostart fresh`, but `pm tui keys` (the user-facing keybinding reference
  printed by the CLI) and the `auto_start` module docstring still listed only
  the old controls.  Both now name the fresh chords (and plain `a` keeps its
  runs-popup meaning), and `autostart fresh` is listed among the command-bar
  verbs.  Pinned by `TestCli::test_tui_keys_lists_the_fresh_chords`.

## Review-iteration notes (2aac i7)

* **The handoff's primary transcript path now has a direct test** — R2/R3 say
  the handoff reads the live implementation pane's *own* transcript (from its
  start command), because a run-dir ``impl-<pr>.jsonl`` symlink can have been
  finalized into a snapshot that stops tracking later turns.  Every existing
  ``handoff_ready`` test passed ``app=None`` and therefore exercised only the
  tracker fallback.  Two tests now pin both branches: the pane transcript
  wins over a stale tracked copy, and the tracked path is used when the pane
  cannot be resolved (restarted TUI).
* **The null-``stop_reason`` reasoning is stated accurately** — the i3 note's
  claim that "the 7252 ``text`` records are all followed by a user record or
  EOF" no longer holds over the full local corpus: re-measured, 6 of 8416
  ``stop_reason: null`` text records are followed by another assistant
  record, one of them ~1.4 s later (a mid-message flush).  The *behavior* is
  unchanged and still right — 8359 real transcripts end on a null
  ``stop_reason`` text record, so requiring a set ``stop_reason`` would stall
  the handoff on the majority of sessions — but the code comment (and this
  note) now describe the residual risk instead of claiming it cannot happen.

## Review-iteration notes (2aac i8)

* **Plain ``O`` has a continuation regression test** — the PR modifies
  ``action_auto_sequence_pr`` (``z O`` = fresh reset), but only plain ``A``
  was pinned as a continuation; nothing stopped a later change from making
  plain ``O`` rewind a PR too.  ``test_plain_upper_o_still_arms_the_sequence``
  now mirrors the plain-``A`` test.  ``test_plain_a_still_toggles`` was
  renamed to ``test_plain_upper_a_still_toggles`` (it exercises ``A``, not
  ``a``).
* **No functional change to the fresh flow** — the end-to-end paths were
  re-verified against the real (unmocked) helpers: the #250 reproduction
  (a stopped ``ReviewLoopState`` is retired, the fresh review starts exactly
  once, the marker is consumed), a busy turn holds the handoff across poll
  ticks, and a complete turn advances on the next tick without a duplicate.

## Review-iteration notes (2aac i9)

* **The handoff retry backoff is described against the real poll cadence** —
  the i5 note (and the comment it added) said the handoff launch would be
  retried on "the next 1 s tick".  ``_poll_impl_idle`` is not the 1 s timer:
  ``_poll_loop_state_inner`` runs it on every fifth tick (~5 s).  The
  backoff's behaviour is unchanged (15 s ≈ 3 implementation polls); only the
  comment, the ``handoff_attempt_due`` caller comment and the rate-limit
  test's docstring were corrected to say so.  A misleading "1 s" invites a
  future maintainer to shrink ``_HANDOFF_RETRY_SECONDS`` or to assume a
  per-second subprocess is being prevented.
* **The ``z`` key set is now derived, not just enumerated** —
  ``test_the_z_key_set_matches_the_consume_z_callers`` walks
  ``ProjectManagerApp.BINDINGS`` and every action's source (following
  ``pane_ops`` / ``pr_view`` / ``qa_loop_ui`` helpers) for
  ``_consume_z()``, then asserts the resulting key set equals
  ``_Z_PREFIX_KEYS``.  The explicit list in the sibling test had already
  drifted once (i2), so the invariant is now checked from the source rather
  than from another hand-maintained list.
* **Files list completed** — the spec's "Files to change" now names
  ``tests/test_pane_idle.py`` and ``tests/test_review_loop_terminal_state.py``,
  which the i1 work added but the list never mentioned.

## Review-iteration notes (2aac i10)

* **A corrupt marker cannot abort the reset** — ``reset_pr`` read the
  attempt counter with a bare ``int(marker.get("attempt") or 0)``, so a
  hand-edited/corrupted ``fresh_autostart.attempt`` raised ``ValueError`` out
  of the locked update.  The reset now falls back to ``attempt = 1``: the
  counter is provenance only and must never fail the workflow reset.
  Pinned by ``TestReset::test_corrupt_marker_attempt_does_not_abort_the_reset``.
* **A raising reset stays a per-PR failure** — ``fresh_start`` called
  ``reset_pr`` without a guard, so any unexpected exception (the case above,
  or a future store error outside the handled set) escaped the loop *after*
  earlier PRs in the same call had already been reset on disk: their changes
  were dropped from the reply, their old loop/QA/sign-off state was never
  retired and their target was never added (only ``resume_pending`` could
  recover them, and only after a TUI restart).  Each PR's reset is now
  wrapped: the exception is logged, recorded in ``failed`` for that PR, and
  the remaining PRs still reset.  Pinned by
  ``TestFreshStart::test_a_raising_reset_is_a_per_pr_failure``.
* **The i5 note's poll cadence is corrected in place** — it still said the
  failing handoff launch was retried on "the next 1 s tick ... every second";
  ``_poll_impl_idle`` runs on every fifth 1 s tick (~5 s), which is what the
  i9 note, the code comment and the test docstring already say.

## Review-iteration notes (4e99 i1)

* **A dead pane no longer hands off on a stale tracker entry** — the
  immediate handoff in ``fresh_start`` read the tracker without polling it,
  unlike ``_poll_impl_idle``.  A pane that died since the last 5 s poll still
  reads as live (``is_gone`` False), and its run-dir transcript — possibly
  already finalized into a snapshot — still ends in a completed turn, so the
  reset could start the fresh review over the old, unreworked code instead of
  waiting for the scheduler's in-progress relaunch (spec ambiguity 5).
  ``fresh_start`` now polls the PR's pane first, exactly as the poll path
  does.  Pinned by
  ``TestFreshStart::test_dead_pane_does_not_hand_off_immediately``.
* **Retiring a running QA loop drops its scenario tracker keys** —
  ``poll_qa_state`` unregisters a finished run's ``qa:<pr>:s<n>`` keys, but
  ``retire_in_memory`` pops the loop so that path never runs; the keys (and
  their runtime mirror) leaked until the next restart.  The retirement now
  unregisters them *before* writing the ``SUPERSEDED`` sentinel, because
  ``_runtime_mirror_clear`` would otherwise wipe the freshly written qa
  entry.  Pinned by
  ``TestRetirement::test_qa_scenario_tracker_keys_are_dropped``.

## Review-iteration notes (4e4d i1)

* **The wait status now survives a TUI restart** — R6's status row reads the
  idle tracker, and a restarted TUI re-registers the implementation pane
  fresh: its newest hook event is the *previous* turn's ``idle_prompt``, so
  the tracker reports ``idle`` while the user's feedback turn is still
  running.  ``retire_in_memory``'s reset only covers a pane that was already
  tracked at reset time, so for the whole wait the row said "fresh
  autostart: implementation turn complete; starting fresh review".  A
  genuinely complete turn hands off on that same tick (except behind the
  spec/return gates), so that reason is otherwise shown only when the
  transcript disagrees.  ``autostart_fresh.reconcile_idle_status`` now clears
  the stale flag when the transcript (the authoritative handoff signal) says
  ``in_progress``; it is called from ``_poll_impl_idle``'s fresh branch and
  after ``fresh_start``'s pre-handoff poll.  A gone pane is left alone
  (``mark_active`` would clear ``gone``) and a live permission prompt is
  never ``idle``.  Pinned by ``TestIdleStatusReconcile`` and
  ``TestPollRouting::test_a_stale_idle_flag_is_cleared_before_the_handoff_check``
  (the latter fails without the call site).

## Review-iteration notes (4e4d i2)

* **An ``[Request interrupted by user]`` tail no longer stalls the handoff** —
  Esc during a turn makes Claude Code append the aborted turn as a
  ``type: "user"`` record whose content is a **list** of text blocks
  (``[Request interrupted by user]`` / ``[Request interrupted by user for tool
  use]``), verified against the local corpus: 54 real transcripts end that
  way, and none of them match ``_is_non_prompt_user_record``'s string-only
  prefix check.  ``latest_turn_state`` therefore read ``in_progress`` forever
  and the fresh attempt never handed off — the same class of stall the i1
  (``!`` shell records) and i4 (compaction summaries) notes fixed.
  The abort marker now *ends* the turn, but only when its own ``timestamp``
  predates ``fresh_autostart.requested_at``: an interrupt written *after* the
  request may be followed by a retyped prompt, so that case keeps waiting
  (the spec's "a false ``complete`` is not recoverable" asymmetry).  The fence
  is threaded through ``latest_turn_state(..., interrupted_before=...)`` from
  both call sites (``handoff_ready`` and ``reconcile_idle_status``), so the
  status row agrees with the handoff.  Pinned by four ``latest_turn_state``
  cases (before/after the request, a tool-use abort, and no fence) and two
  ``handoff_ready`` / reconcile cases.

## Review-iteration notes (1149 i1)

* **Independent corpus re-validation of the handoff signal** — the fresh
  handoff's authority is `latest_turn_state`, so it was re-measured over every
  transcript under `~/.claude/projects` (15,164 files): 14,786 read
  `complete`, 321 `in_progress` (all genuine — a trailing `tool_result` or a
  submitted prompt), 43 `unknown` (transcripts whose only user/assistant
  records are injected/meta ones, e.g. a `/exit`-only session).  Real tails
  are now dominated by non-turn records (`system/turn_duration`, `cost-state`,
  `atis-latch`, `permission-mode`, `last-prompt`, ...); scanning back past
  them is what keeps those sessions reading `complete`.  No stall case found.
* **`pm autostart fresh --help` no longer shows reST markup** — the command
  docstring used double backticks (``in_progress``, ``pm autostart add``,
  ``fresh``), which Click prints literally; within `pm autostart` the group and
  `add` help use single backticks, so the new command body now matches (Python
  docstrings keep the double form, as elsewhere in the repo; two pre-existing
  top-level `pm --help` entries still use double backticks).
* **The `already waiting:` line no longer claims a turn state** — it said
  "(implementation turn in progress)", which is false when the turn already
  completed and the handoff is gated on spec/return state; it now names what
  is being waited for, matching the owner's log line.
* **The partial-failure CLI contract is pinned** — a reply can be `ok` (one PR
  reset) and still carry per-PR `failed` entries; `_print_changes` prints
  those as `failed: <id> (<error>): <message>` without failing the command.
  `TestCli::test_partial_failure_prints_a_failed_line` and
  `test_already_waiting_line_names_the_wait` now cover both lines.

## Review-iteration notes (1149 i2)

* **R3's marker consumption is pinned at its real call site** — the reset's
  handoff is consumed in ``_auto_review_idle_prs`` (``awaiting_handoff=False``,
  ``handoff_at``, ``review_started_at``), which is what stops the status row
  saying "waiting" and keeps a later ``in_progress`` bounce from being
  mistaken for this attempt.  Only ``consume_handoff`` itself was covered
  before; ``TestHandoffConsumption`` now drives the real helper (mocked
  ``pr_view.run_command`` + ``_start_loop``) and asserts both the consumed
  marker (provenance kept) and that an ordinary idle implementation start
  writes no marker at all (the i1 no-spurious-write contract).  Verified to
  fail with the call site disabled.
* **R1/R5 wording matches the code** — R1 item 3 no longer claims a repeated
  request "changes nothing": an explicitly requested policy replaces the
  marker's recorded one (the i1 refinement), while the attempt itself is
  kept.  R5 now names the ``SUPERSEDED`` QA sentinel and the review-loop
  sentinel's ``loop_id`` fence.
* **The all-already-waiting confirmation is grammatical for several PRs** —
  it said "pr-a, pr-b already waiting for its implementation turn"; it now
  says "their" when more than one PR is in the call (TUI log line only; the
  returned message is built per PR).

## Review-iteration notes (2649 i1)

* **A JSON record containing a Unicode line separator is no longer
  fragmented** — ``latest_turn_state`` (and the two pre-existing JSONL
  scanners in the same module) split the transcript with
  ``str.splitlines()``, which also splits on U+2028 / U+2029 / U+0085.  JSON
  leaves those characters *unescaped* inside a string and real transcripts
  contain them (7 of 15,764 local transcripts; one of them in a tail
  assistant record), so such a record was cut into pieces that failed
  ``json.loads`` and skipped, and the newest turn was read from an older
  record: a handoff that never advances when the final answer carries one,
  or — the dangerous direction — an early ``complete`` over a prompt that
  was just submitted.  All three JSONL scanners now split on ``"\n"`` only
  (the assistant-*content* scanner in ``extract_verdict_reason_from_transcript``
  keeps ``splitlines``: that text is not line-delimited JSON).  Pinned by
  three direct tests (answer with a separator → ``complete``; prompt with a
  separator → ``in_progress``; verdict extraction with a separator), each
  verified to fail without the fix.
* **``consume_handoff`` keeps ``app._data`` in step with disk** —
  ``_auto_review_idle_prs`` reloads ``app._data`` *before* consuming, so the
  in-memory marker kept ``awaiting_handoff=True``: the status row could keep
  reporting "waiting" (and ``handoff_ready`` could re-enter the fresh branch
  on a later ``in_progress`` bounce) until something else reloaded the file.
  The consume now also clears the in-memory marker, but only when the locked
  write succeeded (a failed write must not make memory claim a consumed
  handoff).  Pinned by
  ``test_consume_handoff_also_updates_the_in_memory_row``.

## Review-iteration notes (4a2b i1)

* **The duplicate retirement sentinels now share one helper** —
  ``retire_in_memory`` wrote the review-loop and QA ``SUPERSEDED``
  ``runtime_state`` records as two near-identical blocks (differing only in
  the ``loop_id`` fence the review loop needs).  Both now go through
  ``_retire_runtime_action(pr_id, action, state_obj, now, fence_loop=...)``;
  no behaviour change (the existing sentinel tests, including the
  ``loop_id`` fence and the "SUPERSEDED is not a QA verdict" cases, still
  pass unchanged).
* **The ``not_later_stage`` message derives its stage list** — it hard-coded
  "in_review / qa / sign_off" next to ``_LATER_STAGES``, so adding a later
  stage would have left the rejection message lying.  It is now built from
  ``_LATER_STAGES``.
* **``SUPERSEDED`` is one shared constant** — the writer
  (``autostart_fresh``) and the only reader that keys on the *verdict*
  (``auto_start.recorded_qa_verdict``) each carried their own copy of the
  literal, so renaming the sentinel would have silently disabled the
  "a discarded run is not a QA result" fence.  It now lives in
  ``autostart_state`` (next to ``FRESH_KEY``), which both modules already
  import; ``autostart_fresh.SUPERSEDED`` still resolves to it.
* No functional change to the fresh flow.  Full suite: 3924 passed, 1
  skipped, 0 failures (223 s).

## Review-iteration notes (8d61 i1)

* **An interrupt marker with no readable timestamp no longer ends the turn** —
  ``_turn_state_from_tail`` treated an ``[Request interrupted by user]``
  record whose own ``timestamp`` was missing/unparseable as predating the
  request (``_record_epoch`` returns ``0.0``), so the fresh handoff could
  start the review over aborted work — the exact false-``complete`` direction
  the fence exists to prevent.  The record now ends the turn only when its
  timestamp is readable **and** predates ``requested_at``; otherwise the
  conservative ``in_progress`` is returned, matching the module's stated
  asymmetry (a false ``in_progress`` ends with the user's next turn; a false
  ``complete`` is not recoverable).  Measured over the local corpus first: all
  54 real transcripts that end on an interrupt marker carry a valid
  timestamp, so the tightening cannot stall an observed session.  Pinned by
  ``test_turn_state_interrupt_with_an_unreadable_timestamp_is_in_progress``
  (verified to fail without the fix).
* **The Unicode-separator fixtures no longer contain literal invisible
  characters** — the three ``latest_turn_state`` / verdict tests pasted a raw
  U+2028 into the source, which an editor or formatter can silently strip (the
  test would then pass without exercising the ``split("\n")`` path).  They now
  build the separator from a named ``_U2028`` constant.
* **The prefix tests now exercise the real timer bodies** —
  ``_PrefixApp`` in ``tests/test_autostart_fresh.py`` re-stated
  ``_stop_z_timer`` / ``_cancel_z_mode`` instead of binding the
  production methods, so a regression in either (e.g. forgetting to stop
  the armed timer) would still pass.  The duck type now delegates to
  ``ProjectManagerApp``'s implementations.
* No functional change to the fresh flow.

## Master integration (2026-10-29)

Merged `origin/master` (4a74d880) into this branch on user authorization after
the test-session incident.  The merge base was 450a6362, so the branch was 362
commits behind.  Seven files conflicted; the resolutions and the one
behavioural adaptation are below.

* **Master removed `stop_before_merge` as a policy** (pr-1e9c117-era change).
  There is now exactly one manual policy, `wait_for_merge`, which holds the
  target *and its whole unmerged dependency closure*; `auto_merge` is the only
  other.  `--stop-before-merge` / the record value `stop_before_merge` survive
  only as deprecated aliases that map to `wait_for_merge`
  (`autostart_state.LEGACY_POLICY_FLAGS` / `LEGACY_POLICIES`), and
  `POLICY_STOP` no longer exists.  This PR's fresh-autostart code was adapted:
  * a fresh request's new-target default is now `wait_for_merge` (the same
    manual merge gate the acceptance criterion asks for, now with the
    dependency-wide hold);
  * `z O` / `pm autostart fresh --stop-before-merge` map to `wait_for_merge`;
    `z A` / `--auto-merge` are unchanged;
  * the marker's recorded `policy` and `resume_pending`'s fallback use
    `wait_for_merge`.
  The README, `pm tui keys`, the in-TUI help screen and the `pm autostart
  fresh --help` text now use the single-policy vocabulary.
* **`verdict_transcript.py`** — master rewrote the verdict scanner around
  `VerdictHit` / `find_verdict_turn` / `_turn_text`.  The merge keeps master's
  structure and re-applies this PR's additions on top: the
  `latest_turn_state()` tail reader (with `_resolve_transcript_file`,
  `_read_transcript_tail`, the non-prompt/interrupt classifiers) and the
  U+2028/U+2029/U+0085 fix, now applied to master's `find_verdict_turn` and
  `read_latest_assistant_text` (the assistant-*content* scanners keep
  `splitlines`, since that text is not line-delimited JSON).
* **`review_loop_ui.py`** — master added the cross-driver launch lease
  (`_release_lease`) and its own supersede guard in
  `_on_complete_from_thread`.  Both guards are kept; the earlier one (which
  prevents a superseded loop from finalizing the successor's live
  `review-<pr>-i<n>.jsonl` symlink) now also releases the old loop's lease
  before returning.
* **`app.py`** — both sides added module-level definitions at the same spot
  (`_Z_PREFIX_KEYS` / `_Z_PREFIX_TIMEOUT` here, `current_session_name` /
  `_session_for_claim` on master): both are kept.  `_deferred_startup` keeps
  master's guarded `consume_breadcrumb` and this PR's `resume_pending` call.
* **`auto_start.py`** — docstring/USAGE conflicts merged; master's
  `add_targets` already performs the legacy-alias mapping and defaults a new
  target to `wait_for_merge`, which is what `fresh_start` passes.
* **`tests/test_verdict_transcript.py`** — both sides appended a test block at
  the same place; both are kept (no helper-name overlap).
* **`tests/test_autostart_fresh.py`** — policy assertions moved to the
  single-policy model (`POLICY_WAIT`), the removed `app._stop_before_merge`
  set is no longer asserted, and the two CLI round-trip tests now patch
  `submit_tui_command` (master replaced `trigger_tui_command`) with a result
  object exposing `.ok`.

## Review-iteration notes (d9f2 i1)

* **A discarded QA run now goes through `discard_qa_state`** — R4's retirement
  popped `app._qa_loops[pr_id]` and only set `stop_requested` when
  `qa.running`.  A run that finalized with INPUT_REQUIRED is *held* with
  `running` False while it keeps polling its worker panes (the hold has no
  timeout of its own), so it was never stopped; and a still-winding-down
  thread could rewrite its `qa_resume.json`, which a later restart scan could
  resurrect once the PR is back in `qa` after the fresh review.
  `qa_loop_ui.discard_qa_state` — the one path the code documents for
  dropping a tracked run — also marks the run `superseded` and clears the
  resume snapshot, so the retirement now calls it (with the old
  `stop_requested` behaviour kept as a fallback).  Pinned by
  `TestRetirement::test_a_held_qa_run_is_discarded_not_just_stopped`
  (verified to fail without the fix).
* **One shared fresh-request timestamp helper** — the "did this predate the
  fresh request?" fence parsed the marker's `requested_at` in four places
  (`autostart_fresh._epoch`, `auto_start._predates_fresh_request`,
  `signoff.fresh_recorded_verdict`, plus the per-record parses).
  `autostart_state.fresh_requested_epoch(pr)` now does that conversion once,
  next to `fresh_marker` / `fresh_awaiting` / `fresh_requested_at`; no
  behaviour change (a missing/unparseable timestamp still means "no fence"
  for the handoff and "not predating" for the QA/sign-off guards).
* **Stale `stop-before-merge` vocabulary removed** — the master merge removed
  the policy but left it in the TUI's inline `z` prefix hint
  (`O=fresh-stop`) and throughout `pm/specs/pr-22ea6a2/qa.md`, whose
  scenarios would then assert a policy that no longer exists.  Both now say
  wait-for-merge (`--stop-before-merge` remains only the deprecated CLI
  alias).
* **Merge leftovers tidied** — the redundant `from pm_core import
  runtime_state as _rs` in `_on_complete_from_thread` (the merge's second
  supersede guard re-imported it) is gone, with the guard's race-window
  comment made explicit; one stray extra blank line before `@dataclass` in
  `verdict_transcript.py` is fixed.
