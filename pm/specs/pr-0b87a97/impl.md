# pr-0b87a97 — Multiple auto-start targets, CLI controls, live runs popup

## 1. Requirements (grounded in code)

### R1 — Target collection replaces the single target
Today `TechTreeApp.__init__` (`pm_core/tui/app.py`) holds one
`_auto_start_target: str | None`; `auto_start.toggle()` /
`auto_sequence_for_pr()` / `set_target()` (`pm_core/tui/auto_start.py`)
overwrite it, and every scoping site recomputes
`_transitive_deps(prs, get_target(app)) | {target}`:
`check_and_start`, `_auto_start_review_loops`, `_auto_start_qa_loops`
(auto_start.py), `_maybe_start_qa`, `_maybe_auto_merge`,
`_auto_review_idle_prs` (`pm_core/tui/review_loop_ui.py`), the ◎ marker
and layout signature in `pm_core/tui/tech_tree.py`, and the watcher
(`watcher_ui.start_watcher` → `AutoStartWatcher.auto_start_target` →
`pm watcher --auto-start-target` → `prompt_gen.generate_watcher_prompt`).

Change:
- New pure module `pm_core/autostart_state.py` (no TUI imports) holding the
  shared helpers: `transitive_deps`, `closure(prs, target)` (deps ∪ target),
  `managed_ids(prs, targets)` (union of closures), target-record helpers,
  breadcrumb (de)serialisation incl. legacy migration, and
  `build_status(inputs) -> dict` (R3).
- App state: `app._auto_start_targets: dict[str, dict]` (insertion-ordered;
  record = `{"added_at", "source"}`) and `app._auto_start_all: bool`
  (explicit backlog mode). `app._auto_start` stays as the derived "enabled"
  flag (`bool(targets) or all_mode`), recomputed by every mutation helper.
  `_auto_start_target` is removed.
- `auto_start` API: `get_targets(app) -> list[str]`, `managed_ids(app) ->
  set | None` (None only in explicit all-mode), `in_scope(app, pr_id)`,
  `add_targets(app, ids, policy=None, source=...)`,
  `remove_targets(app, ids)`, `clear_targets(app)`, `enable_all(app)`.
  All scoping sites call `in_scope` / `managed_ids` instead of
  recomputing from one target.
- Add is additive and idempotent; never replaces another target and never
  turns on all-mode. Removing the last target (or completion of the last
  target) disables auto-start (`_disable`) — it never falls back to all-mode.
- `check_and_start` schedules the union of closures: one pass over
  `graph.ready_prs` + restartable `in_progress` PRs filtered by
  `managed_ids`; the old "break once the target starts" is removed (it would
  starve other targets). Each PR is launched at most once per pass, and a new
  `app._auto_start_launching: set[str]` guard prevents concurrent
  `check_and_start` workers (sync/merge/QA callbacks all `run_worker` it)
  from launching the same shared dependency twice. Scope is re-checked after
  every `await` so a CLI removal that lands mid-pass takes effect.
- Completion: each target whose PR is `merged` (or `closed`) is removed with a
  log line naming it; other targets are untouched. Only when no target
  remains (and all-mode is off) does auto-start disable.
- Per-target merge policy: the single source of truth stays
  `app._stop_before_merge` (already per-PR, already persisted, already read by
  `_maybe_auto_merge`). Target policy = `stop_before_merge` if the PR id is in
  that set, else `auto_merge`.
  - `O` (`auto_sequence_for_pr`): add target (additive) + add to
    `_stop_before_merge`; repeating `O` re-arms and nudges, discarding nothing.
  - `A` (`toggle`): per-PR toggle — selected PR not a target → add with
    auto-merge (existing explicit A semantics; does not clear an existing
    stop mark); selected PR already a target → remove it.
  - CLI `add` default for *new* targets is `stop_before_merge`; `--auto-merge`
    is the explicit opt-in (and removes the stop mark); re-adding without a
    policy flag keeps the current policy.
  - A dependency that is itself stop-before-merge is never auto-merged even
    when another (auto-merge) target needs it — explicit stop wins and the
    dependent shows `waiting` with that reason.

### R2 — Real CLI commands over the existing IPC
New `pm autostart` group (`pm_core/cli/autostart.py`, registered in
`pm_core/cli/__init__.py`):
- `pm autostart add PR_ID... [--stop-before-merge|--auto-merge]`
- `pm autostart remove PR_ID...`
- `pm autostart clear` (remove all targets → off)
- `pm autostart list [--json]` (targets + policies)
- `pm autostart status [--json]` (full structured status, R3)
- common: `-s/--session`, `--timeout` (default 10s).

Transport: reuse `helpers.trigger_tui_command` (SIGUSR2 + per-session
`tui-<session>.cmd-queue`, drained by `TechTreeApp._drain_command_queue` →
`pr_view.handle_command_submitted`). The CLI sends
`autostart <verb> <args> --reply <req_id>`; the TUI performs the mutation on
its event loop (same scheduler, no new loop) and writes the reply JSON
atomically to `pm_home()/autostart-replies/<req_id>.json`
(`{"ok", "error", "changes", "status"}`); the CLI polls for that file and
deletes it. The same command-bar verbs work when typed in the TUI (without
`--reply`, results go to the log line).

Validation before state change: the CLI resolves every id against
project.yaml (`helpers._resolve_pr_id`, accepts `pr-x`, `#N`, `N`) and
rejects unknown ids, and adding merged/closed PRs, without sending anything.
The TUI re-validates all-or-nothing against its own data (authoritative —
project.yaml can change in between). Owner availability: no pidfile, dead
pid, or failed signal → `owner_unavailable` error (exit 2, JSON when
`--json`); no reply within timeout → `owner_timeout` (exit 2). Validation
errors exit 1. Removal never kills windows/loops.

Compatibility / migration (documented in help + `pm tui keys`):
- `autostart` (bare, command bar): when on → off (unchanged). When off it no
  longer silently enables the whole backlog; it prints usage. The backlog
  mode is now explicit: `autostart all`.
- `autostart target X` → alias of `autostart add X` (additive, not replace).
  `autostart target` with no id → usage error (previously "clear target",
  which implied all-mode).
- `A` with no selected PR → "No PR selected" (previously all-mode).

### R3 — Shared structured status + TUI popup
`autostart_state.build_status(inputs)` is the only status builder; the TUI
gathers inputs via `auto_start.collect_status_inputs(app)` (PR data,
targets, stop set, `_review_loops`, `_qa_loops`, pending/propagation/
input-required merge sets, launching set, impl idle tracker, one
`tmux list-windows` call, hook-derived waiting state via
`runtime_state.derive_action_status`, sign-off freshness via
`signoff.head_sha` + `fresh_recorded_verdict` for `sign_off` PRs only).
Both the popup and the CLI reply carry the dict from `build_status`.

Schema `pm.autostart.status/1`:
```
{schema, generated_at, owner:{session,pid}, enabled, mode: off|targets|all,
 run_id, targets:[{pr_id,title,policy,added_at,source,state,phase,reason,
                   pending:[closure ids not yet merged]}],
 runs:[{pr_id,display_id,title,status,phase,state,reason,is_target,
        needed_by:[target ids],depends_on,policy,
        window:{name,id}|null,
        review:{iteration,verdict,running,input_required}|null,
        qa:{planning,total,done,counts:{PASS:n..},running,verdict,error}|null,
        signoff:{verdict,fresh}|null}]}
```
`phase` ∈ pending | implementation | review | qa | sign_off | merge | done.
`state` ∈ queued | running | waiting | paused | failed | completed.
Derivation uses live evidence, never status alone:
- pending: deps unmerged → waiting ("blocked on …", noting stop-before-merge
  deps); all merged → queued ("ready; starts on next scheduler pass"), or
  running "launching" while in `_auto_start_launching`.
- in_progress: impl window alive → running (hook `waiting` → waiting
  "permission prompt"; idle tracker idle → running "impl idle; review
  transition pending"); no window → paused "no implementation window".
- in_review: review loop running → running "review iteration N (last V)";
  input_required → waiting; loop ended PASS → waiting "review passed; QA
  transition pending"; KILLED/ERROR → failed; no loop → queued.
- qa: loop planning → running "planning scenarios"; running → "scenario k/N
  done"; `_error` → failed; INPUT_REQUIRED → waiting; PASS → waiting "QA
  passed; awaiting sign-off (press i — automatic sign-off hand-off not yet
  implemented)"; merge attempted and refused → waiting "merge blocked by
  sign-off gate". No loop → queued (or "skip_qa").
- sign_off: no verdict + window → running; no verdict, no window → paused;
  fresh SIGNOFF_MERGE → waiting "signed off; stop-before-merge — press g" or
  "signed off; merge not automated from sign-off — press g"; stale →
  waiting "SIGNOFF_MERGE stale (HEAD moved)"; BLOCKED → paused; other →
  waiting "routed <verdict>".
- merge overlays (`_merge_input_required_prs` → waiting, `_pending_merge_prs`
  + merge window → running "resolving conflict", without window → waiting/
  failed, `_merge_propagation_phase` → running).
- merged → completed; closed → completed "closed".

Popup `AutoRunsScreen` (ModalScreen in `pm_core/tui/screens.py`), opened by
new key `a` (shown in footer as "Runs"), by command-bar `autostart status`,
listed in `?` help and `pm tui keys`. Rows grouped by target (target header
with policy + state, then unmerged closure PRs, shared deps shown once per
target with "also needed by"). Keys: j/k/↑/↓ select, Enter/f focus the
selected run's window (dismiss, then `tmux select-window`), r refresh, Esc/q/a
close. Auto-refresh every 2s while open (timer stopped on dismiss). Empty set
shows "No auto-start targets (auto-start off)" — never the backlog.

### R4 — Restart persistence + adoption + consistency
- `save_breadcrumb` writes `targets` (records), `all_mode`, `run_id`, and the
  existing `stop_before_merge`/review-loop/watcher data. `consume_breadcrumb`
  reads `targets`; legacy `target: X` → `[X]`; legacy `auto_start` with no
  target → all-mode (that was the user's explicit legacy mode — logged).
- Adoption: impl uses `pm pr start --background` which no-ops when the window
  exists; review loops are restored by the breadcrumb before
  `check_and_start`; QA — `_auto_start_qa_loops` first runs
  `qa_loop_ui._resume_incomplete_qa(app)` so an in-flight run with a
  `qa_resume.json` is adopted into `app._qa_loops` instead of `start_qa`
  launching a duplicate (the resume scan otherwise only runs on the poll
  timer, after the breadcrumb-triggered `check_and_start`).
- Consistency: all target mutations happen on the TUI event loop (queue drain
  runs on the loop; loop callbacks use `call_from_thread`), so mutations are
  serial; `check_and_start` re-reads scope after awaits; the launching guard
  covers the shared-dep race.

## 2. Implicit requirements
- Watcher: `AutoStartWatcher` takes `auto_start_targets: list[str]`;
  `pm watcher --auto-start-target` becomes `multiple=True`;
  `generate_watcher_prompt(auto_start_targets=...)` lists all targets and the
  union managed set (single-string kwarg kept as alias).
- Tech tree ◎ marks every target; `_auto_start_sig` → `(enabled,
  tuple(targets))`.
- Status bar shows target count when >1 (`AUTO ×N`).
- Transcript run dir: one per enablement (`autostart-<first>-<hex>` /
  `autostart-all-<hex>`), shared across targets; created on first enable,
  kept while any target remains.
- Existing tests constructing MagicMock apps with `_auto_start_target` must
  move to `_auto_start_targets`; `auto_start.in_scope` must treat a
  non-dict attribute as "no targets" defensively.
- Reply dir cleanup: replies older than 10 min are pruned when writing.
- Sign-off merge gate untouched: no code path here passes
  `--no-signoff-check`; auto-merge still goes through `pm pr merge`.

## 3. Ambiguities (resolved)
1. *Default policy for CLI-added targets* → stop-before-merge (merge must be
   explicitly enabled; mirrors `O`). `--auto-merge` opts in.
2. *Removing a stop-before-merge target* → its stop mark is kept (never
   accidentally auto-merge something a user stopped); re-add with
   `--auto-merge` to change.
3. *Target already merged/closed on add* → rejected with a reason.
4. *Remove of a valid PR that isn't a target* → ok, reported as `not_target`
   (idempotent); unknown id → error, nothing changes.
5. *Backlog (all) mode* → retained only as explicit `autostart all`;
   empty targets never mean all.
6. *What restart path is "supported"* → the merge-restart breadcrumb
   (merge-triggered restarts and `pm tui restart --breadcrumb`); a plain
   Ctrl+R remains a clean restart, as before.
7. *Sign-off*: status reports sign-off state from recorded verdicts; the
   qa→sign_off hand-off stays manual (pr-488ac6d).

## 4. Edge cases
- Target A depends on target B: B is in A's closure and is also a target; B's
  own policy governs B's merge; A shows waiting on B.
- Shared dep D in two closures: listed once in `runs` with
  `needed_by=[A,B]`; launched once (launch guard + window no-op).
- Removing target A while D is running and needed by B: D keeps running and
  stays scheduled; A-only PRs stop advancing (no kill).
- Removing a target whose review/QA loop is mid-run: the loop is not killed;
  its follow-on transitions are no longer triggered because `in_scope` fails.
- CLI add during an in-flight `check_and_start` await: next scope check
  includes the new target; the add also kicks `check_and_start`.
- TUI not running / restarting: CLI reports `owner_unavailable` /
  `owner_timeout`; nothing is persisted outside the owner.
- Unknown ids mixed with valid ones → whole command rejected.
- `skip_qa` projects: review PASS → merge path unchanged, scoped per target.
- Self-driving QA (`zz t`) still independent of targets.

## 5. Implementation notes (as built; supersedes §1–4 where they differ)

Files: `pm_core/autostart_state.py` (pure helpers + `build_status` +
`status_rows`/`format_text`), `pm_core/tui/auto_start.py` (target API,
scheduler, breadcrumb, `handle_command`, `collect_status_inputs`,
`write_reply`), `pm_core/cli/autostart.py` (`pm autostart`),
`AutoRunsScreen` in `pm_core/tui/screens.py`, key `a` in `app.py`.

Additions found necessary during live verification (fake-Claude/tmux run,
captures under `impl/post-fix/`):

1. **Finished QA is not relaunched by the scheduler.** A completed QA run
   leaves `app._qa_loops` one poll tick after completion; its verdict
   persists only in `runtime_state` (`qa` action `done`). The catch-up path
   `_auto_start_qa_loops` used to treat that as "no loop" and re-run QA on
   every later `check_and_start` and on every breadcrumb restart — far more
   frequent with several targets. It now skips a `qa` PR whose recorded QA
   verdict is PASS (awaiting sign-off) or INPUT_REQUIRED (awaiting a human)
   (`auto_start.recorded_qa_verdict`, `QA_HOLD_VERDICTS`). Any real QA start
   (review→qa via `_maybe_start_qa`, `t`, `z t`) overwrites the record, so
   normal flows are unaffected. `test_after_poll_cleanup_*` in
   `tests/test_auto_start_qa.py` was updated to this semantics.
2. **Merges seen only via reload kick the scheduler.** `TechTreeApp._load_state`
   calls `auto_start.on_state_loaded(app, old_statuses)`; when an in-scope PR
   newly became merged/closed (manual `g`, CLI merge, other session) it runs
   one `check_and_start` pass, which prunes completed targets and starts newly
   unblocked dependents. Previously this only happened on sync-detected merges
   or the auto-merge path, so the normal end of a stop-before-merge target
   (manual `g`) left it in the set and its dependents unstarted.
3. **The popup passes Ctrl+R through** (`AutoRunsScreen` binds `ctrl+r` →
   close + `app.action_restart`); otherwise an open popup swallowed the key that
   `pm tui restart` and merge-triggered restarts send.
4. **Status uses recorded verdicts.** `collect_status_inputs` adds the
   `runtime_state` QA verdict (`qa.recorded: true`) for `qa` PRs without a live
   loop, and the sign-off record freshness (`git rev-parse` only for QA-passed,
   `sign_off` or pending-merge PRs). A QA-passed PR with a fresh
   `SIGNOFF_MERGE` record reports "signed off (fresh SIGNOFF_MERGE); … press g".
   `pending_merge` without a merge window and without a fresh SIGNOFF_MERGE
   reports "merge blocked by sign-off gate".
5. `_prune_completed_targets` refreshes the display (◎ / `AUTO ×N`) when
   targets remain.
6. Test hygiene: `tests/conftest.py` isolates `runtime_state._runtime_dir`
   per test (autouse), since scheduling now reads it; `consume_breadcrumb`
   tests patch `_adopt_live_qa` so they never scan the real
   `~/.pm/workdirs/qa`.

7. *(review i1)* `A` with no selected PR turns auto-start off when it is on
   (the pre-existing `A` toggle-off behaviour, documented in `pm tui keys`)
   and prints "No PR selected" when off — it never enables the backlog.
   This supersedes the R2 compatibility bullet for `A`.
8. *(review i1)* `handle_command` writes an `{"ok": false, "error":
   "internal"}` reply if a verb raises, so the CLI exits 1 with the cause
   instead of waiting out its timeout as `owner_timeout`; command-bar
   `autostart list` logs the targets + policies; the unknown-id reload in
   `_resolve_ids` flushes the write queue before re-reading project.yaml.

9. *(review i2)* `REPLY_DIR` lives in `autostart_state` (shared by the CLI
   poller and the TUI writer); `pm autostart list --json` carries the owner's
   `error`/`message` when the reply is not ok; `_prune_completed_targets`
   does nothing when the PR list is empty (unloaded data is not "every target
   vanished").

10. *(review i3)* `pm autostart status|list` treat an ok reply without a
    status dict (owner-side `build_status` failure) as `status_unavailable`
    (exit 1) instead of printing `{}` / "no targets" with exit 0, and
    `status --json` carries the owner's `error`/`message` when the reply is
    not ok.

11. *(review 15ef i2)* The runs popup renders a failed status refresh as plain
    `Text`, not markup — an exception message containing `[...]` raised
    `MarkupError` and took the popup down instead of showing the error.

12. *(review 15ef i3)* `pm autostart add|remove --json` run outside a pm
    project reports `{"ok": false, "error": "no_project"}` (exit 1) instead
    of a plain-text error, keeping the machine-readable contract.

13. *(review 15ef i4)* The runs popup's scroll container is not focusable
    and the selected row is scrolled into view after each render: once the
    rows overflowed the popup, the focused `VerticalScroll` claimed ↑/↓ for
    scrolling (selection stuck) and j/k could move the selection off-screen,
    so Enter focused a row the user could not see.

Fixes made during QA (recorded in the PR notes; listed here so the spec
matches the code):

14. *(QA s5, e7e8abdc)* **Review-loop adoption on restart.** A resumed loop
    whose iteration counter is ahead of its history (an iteration was in
    flight at the breadcrumb restart) polls the live review pane for that
    iteration (`review_loop._adopt_in_flight_review`, using the saved
    `_transcript_dir`) instead of relaunching N+1 with `--fresh`, which
    killed the in-flight window. When there's no live pane or transcript to
    adopt, the same iteration reruns. The "Auto-start: resumed after merge
    restart" summary is logged last so it is painted.
15. *(QA s5, 71ca9067)* **CLI commands during a restart.** External
    commands are not dispatched until `consume_breadcrumb` has restored
    state (`_cmd_queue_ready`). The startup drain then applies queued lines,
    unless the queue file was last written more than
    `_STARTUP_QUEUE_MAX_AGE` (60s) before the process started. Such a queue
    was left by a dead TUI and is discarded, so it can't be replayed later.
    `restart_app` sets SIGUSR1/SIGUSR2 to SIG_IGN across `execvp`, so a
    signal arriving before the new handlers exist doesn't kill the TUI.
16. *(QA s1, 29f37c17)* `_auto_review_idle_prs` runs the hidden
    `pm pr review --no-window` (status transition only), because the review
    loop launches iteration 1's window itself. Before this, a throwaway
    Claude session was launched and immediately killed. The popup's QA
    progress shows "qa planning" or "qa <verdict>", never a stale review
    iteration.
17. *(QA s3/s2, f4e89681, f9358d7c)* `log_message(force=)` shows
    auto-start confirmations (targets +=, removed, OFF) even while a sticky
    message is up. `log_message(hold=)` keeps "targets +=" / "ON (all …)"
    readable against the scheduler messages it triggers in the same frame.
    Held messages are deferred, and the latest one shows when the hold ends.
    Closing a runs popup that was opened from the command bar returns focus
    to the tree.
18. *(QA s4, b336ee34, b62f797b)* The tree cursor follows `active_pr` only
    when it changes, and not for the scheduler's own background
    `pr start` (`_quiet_activations`). A tree reorder keeps the selection on
    the same PR. Otherwise O/A could hit the wrong PR. Every log-line
    message is also written to the `L` command log as `log: …`. A skip-qa
    review PASS reports "QA skipped (skip_qa); awaiting sign-off".
19. *(QA, 41451898)* The tmux `set-hook window-resized` stderr is captured
    and logged, because tmux < 3.3 rejects the hook and its error was
    painting over the TUI pane.

Known, intentionally unchanged (out of scope):
- QA PASS leaves the PR in `qa`; the automatic qa→sign_off hand-off is
  pr-488ac6d. Until then the status says "QA passed; awaiting sign-off (press i
  …)" and auto-merge after QA is refused by the sign-off gate for PRs without a
  fresh SIGNOFF_MERGE.
- `_pending_merge_prs` is not persisted across restarts (pre-existing).
