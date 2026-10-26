# pr-f094946 — Auto-started QA must not select its new window

## Requirements

1. **Background QA launches are focus-safe.** `pm_core/qa_loop.py::run_qa_sync`
   (planning phase, first-time creation of the `qa-<pr>` window — the
   `elif not existing_win:` branch after `tmux_mod.new_window(..., switch=False)`)
   previously called `tmux_mod.select_window(session, window_name)` unless
   `runtime_state.consume_suppress_switch(pr_id, "qa")` returned True.
   `tmux.select_window` targets `current_or_base_session(session)`, i.e. the
   attached client's (possibly grouped `$SESS~N`) session, so every
   scheduler-driven QA start yanks that client off the TUI window.
   For launches no user asked for, the select must not happen at all — same
   as `_start_pr_quiet` (`pr start --background`) and review loops
   (`new_window(..., switch=False)`).

2. **User-initiated QA starts keep their current behaviour.** `t`
   (`qa_loop_ui.focus_or_start_qa`), `z t` (`fresh_start_qa`), `zz t`
   (`start_or_stop_qa_loop`) — reached from `app.action_start_qa_on_pr`,
   `pr_view` command handling and the popup/command bar — still select the
   new window on first-time creation, still honour the popup
   `suppress_switch` flag.

3. **Preserve the incidental fixes added during QA and review rounds.** These
   extend the original focus-only scope and are required by the PR notes
   and QA spec (R3, R10–R14):
   * The first `zz t` on an `in_review` PR transitions it to `qa`, using
     the same locked status-update helper as `start_qa`. If the update
     fails, do not launch QA.
   * Both QA start paths arm the existing shared 1 s poll timer, even if
     no workdir existed at the last refresh. Reuse the review-loop timer
     helper rather than creating a separate timer per QA run. Publish the
     background run's active state before starting its worker, so a slow
     initial model/state load cannot let the first poll stop the timer.
     Reset that state if thread startup fails.
   * A plain-`t` NEEDS_WORK result repaints the tree after reloading the
     `in_review` status, without requiring a manual refresh. Flush pending
     navigation writes before this reload, as `_load_state` does, without
     invoking that method's scheduler hook a second time.
   * The self-driving PASS-count/restart message and the NEEDS_WORK
     return-to-review message use `force=True` and `CONFIRM_HOLD_SECONDS`,
     so existing sticky lines and same-frame start messages do not hide
     them. The latter applies to both
     self-driving and auto-start bounces. A displayed forced hold replaces
     obsolete sticky protection, allowing deferred progress to appear when
     the approximately 3 s hold expires rather than waiting for the prior
     sticky deadline.
   * The initial `zz t` confirmation, including its required pass count,
     uses `force=True` with `sticky=3` so an existing setup confirmation
     cannot hide it.
   * Pane-launch/focus confirmations use the existing `force=True`
     convention so user-key replies are visible over a sticky message,
     including launches into a new per-plan window.
   * Register the live planner as `qa-planner` in its own QA window before
     polling its result. An early `L` must leave the log pane registered in
     the TUI window and the planner identifiable while planning continues.
     Status-pane setup ensures the main pane is registered for execution-only
     runs or recreated windows, without registering the same planner twice.
     Registration/layout failures are logged rather than aborting healthy
     planning; status-pane setup retries missing early registration.

## Design

* New `QALoopState.focus_on_create: bool = False`. `run_qa_sync` only enters
  the select/consume-suppress branch when it is True. Default False so any
  new/internal caller is focus-safe by default.
* `qa_loop_ui.start_qa(app, pr_id, *, focus=False)` sets
  `state.focus_on_create = focus`. `focus_or_start_qa` and `fresh_start_qa`
  pass `focus=True`; `start_or_stop_qa_loop` sets it on its own state.
* Background callers stay on the default (no call-site change needed):
  `auto_start._auto_start_qa_loops`, `review_loop_ui._maybe_start_qa`
  (review PASS → QA), `signoff_ui` SIGNOFF_REQA hop, self-driving QA restart
  in `qa_loop_ui._on_qa_complete`-path (`start_qa` after a PASS short of the
  required count), and `pm pr qa-run-bg` (auto-sequence detached driver,
  which builds a bare `QALoopState`).

## Implicit Requirements

* The "replacement window" path (`sessions_on_qa` non-empty →
  `switch_sessions_to_window`) is unchanged for both kinds of launch: it only
  moves clients that were *already viewing* the old `qa-<pr>` window, so it
  is focus-preserving, not focus-stealing.
* Fixing the select also fixes the PR-note follow-on: with the client left on
  the TUI window, `L` resolves the TUI window and its log pane is no longer
  created inside the QA window / registered as `qa-planner`.
* Scenario windows already use `switch=False`; nothing else in `qa_loop.py`
  selects windows (`grep select_window` → only this site).

## Ambiguities (resolved)

* **Suppress-switch flag on background launches** — the popup dismissal flag
  belongs to the user's queued request. A background launch skips the
  whole branch and does *not* consume it, so it is still there for the
  user-initiated start it was meant for.
* **Self-driving (`zz t`) follow-up runs** (restart after PASS, review→QA
  after a NEEDS_WORK bounce) are treated as background: only the user's
  initial `zz t` selects the window. Follow-ups normally reuse an existing
  window (replacement path) anyway.
* **`pm qa run` CLI** (`cli/qa.py`) uses `planning_phase=False`, never
  reaching the branch — no change.
* **User `zz t` over a leftover QA window** remains the unchanged
  replacement-window behavior, tracked separately by pr-064fe5b. The
  first-start focus requirement applies when no QA window exists; do not
  broaden this fix to change replacement-window selection.

## Edge Cases

* Existing `qa-<pr>` window + background restart: clients already on the old
  QA window follow to the replacement (unchanged); clients elsewhere stay.
* Grouped view sessions (`$SESS~N`): background first-time creation does
  not select any session. On replacement, only sessions viewing the old
  QA window follow it; unrelated windows remain selected.
* A user start selects a session, not an individual client. All clients
  attached to that same session share its current window; use separate
  grouped sessions to assert independent focus.
* Tests that patch `qa_loop_ui.start_qa` and assert `(app, pr_id)` keep
  passing since background call sites are unchanged.
