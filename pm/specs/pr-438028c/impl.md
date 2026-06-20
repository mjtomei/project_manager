# pr-438028c — Implementation Spec

## Goal (recap)

Delete `popup_cmd_cmd`'s special-case routing of `pr qa …` and
`review-loop start …` to the TUI (pm_core/cli/session.py:1903-1907) by
giving those commands proper CLI-level tmux window management, the way
`pr start` / `pr review` / `pr merge` / `meta` already do.

## Requirements (grounded)

### R1. `pm pr qa <pr_id>` becomes self-sufficient
Today's handler (pm_core/cli/pr.py:1725-1774) prints "use the TUI command
bar" and exits 1. Replace with a real implementation that:
- Resolves a target tmux session: explicit `--session <name>` flag → env
  `PM_SESSION` → `_get_pm_session()` (helpers.py:814) → error.
- Looks up the existing `qa-<display_id>` window via
  `tmux_mod.find_window_by_name` (matching the pattern used in
  `qa_loop_ui.focus_or_start_qa` at qa_loop_ui.py:84-96) and switches to
  it if present.
- Otherwise launches QA: this is `qa_loop_ui.start_qa` minus the
  `app`-coupled bits — needs to call `start_qa_background`
  (qa_loop.py:2596) with a state object, an `on_update` callback that no
  longer calls `app.call_from_thread`, and persistence of completion
  state via `runtime_state.set_action_state(..., "qa", ...)` (already
  used by `qa_loop_ui.poll_qa_state` at qa_loop_ui.py:312-315).

### R2. `pr qa fresh <pr_id>` parity
Mirror `qa_loop_ui.fresh_start_qa` (qa_loop_ui.py:161-198): kill
existing scenario windows (`qa-<id>-s*` plus the main `qa-<id>` —
`_cleanup_stale_scenario_windows` at qa_loop.py:311-336 already does
this), then start QA fresh.

### R3. `pr qa loop <pr_id>` parity
Mirror `qa_loop_ui.start_or_stop_qa_loop` (qa_loop_ui.py:205-260):
register self-driving state and start QA. Self-driving state today
lives on `app._self_driving_qa` — externalize to runtime_state so a CLI
handler can write it.

### R4. `pm pr review-loop start <pr_id>` (new)
No CLI surface exists today; the chord `zz d` calls
`review_loop_ui.start_or_stop_loop` directly (review_loop_ui.py:98). The
`tui:review-loop start {pr_id}` form (session.py:909) is the popup's
current route. Add:
- `pm pr review-loop start <pr_id> [--session <name>]` — handler does
  what `_start_loop` (review_loop_ui.py:153-248) does, minus
  `app.set_interval` polling and `app.log_message` UI calls. Persist
  state to `runtime_state` (already partially done — see
  review_loop_ui.py:235-238).

### R5. Shared session resolver
New helper, e.g. `pm_core/cli/_session_target.py::resolve_target_session`,
ordering: `--session` flag → `PM_SESSION` env → `_get_pm_session()` →
`SystemExit(1)` with a clear message. Use in R1-R4.

### R6. Delete the carve-out
Remove session.py:1903-1907.

### R7. Update picker / chord tables
Change `_ALL_ACTIONS` (session.py:894-900) and `_MODIFIED_ACTION_CMDS`
(session.py:906-912) to drop the `tui:` prefix on `pr qa …` and
`review-loop start …` entries. Keep the `tui:` branch in
`_run_picker_command` (session.py:1472+).

## Implicit Requirements

### IR1. Background-thread lifetime
`start_qa_background` (qa_loop.py:2596) and
`start_review_loop_background` start daemon threads. A short-lived CLI
subprocess that exits right after kicking off the thread will kill the
thread with it. **For CLI invocation to actually run QA / review-loop,
the CLI handler must either (a) block until completion, or (b) detach
into a long-lived child process** (e.g. `os.fork()` + `setsid()` + run
the loop in the child, parent exits after window setup).
This is not optional — without it, "pr qa" from the popup would create
a window and immediately abandon it.

### IR2. Externalization of `app._qa_loops` / `app._self_driving_qa` /
`app._review_loops`
The TUI consumes these dicts (qa_loop_ui.poll_qa_state at qa_loop_ui.py:281,
review_loop_ui._poll_loop_state_inner at review_loop_ui.py:387). For
CLI-launched loops:
- `runtime_state` already mirrors loop state for review-loop (set in
  review_loop_ui.py:235). The CLI handler must do the same.
- The TUI's polling currently reads from in-memory dicts. A loop
  started by the CLI populates `runtime_state` but NOT `app._qa_loops`.
  The TUI's spinner / verdict-handling logic for loops it didn't start
  needs to fall back to runtime_state.

### IR3. TUI command-bar parity
`pr_view.py:629-676` intercepts `pr qa …` typed in the TUI command bar
and routes to `qa_loop_ui` directly (in-process). After R1-R3 the CLI
form works headlessly, but the in-TUI form continues to use the
in-process `qa_loop_ui` (no need to subprocess out). This carve-out in
pr_view.py is **not** in scope to remove.

### IR4. Concurrency safety on review-loop launch
pr-fc6db6a / #156 introduces a per-container-name lock around
`_launch_review_window` for concurrent invocation. The CLI handler
must hold that lock in the same way (and the lock itself must be
filesystem-backed since CLI and TUI are separate processes).

### IR5. `_pr_display_id` for window names
QA windows are `qa-<display_id>` (qa_loop.py:295). Display id resolved
via `_pr_display_id` (helpers.py). CLI handler must use the same.

## Resolved decisions (from user)

- **A1 → Option B (daemonize).** CLI handlers double-fork detached
  subprocesses that own the QA / review-loop coordinator. Loops drive
  via runtime_state; TUI is an observer.
- **A2 → wait for pr-fcaa434 before merging**, but proceed with
  implementation now using `pr start`/`pr review` as reference.
- **A5 → completion policy stays TUI-side.** CLI-launched loops record
  verdicts in runtime_state; the TUI's existing pollers handle
  NEEDS_WORK → review, PASS → merge, etc.

## Daemonized loop lifecycle (R8 — added)

### R8.1 Pidfile layout
`~/.pm/sessions/<session-tag>/loops/<pr-id>-<action>.pid` where
`<session-tag>` strips the `pm-` prefix from the session name and
`<action>` is one of `qa`, `review-loop`. Pidfile contents:

```
<pid>
<loop_id>
<started_at_iso>
```

Plain text, line-delimited.

### R8.2 Spawn
CLI handler:
1. Resolve target session (R5).
2. Acquire per-PR-action lock (filesystem flock on
   `~/.pm/sessions/<tag>/loops/<pr-id>-<action>.lock`) so concurrent
   spawns serialize.
3. If pidfile exists and PID is alive, refuse with a clear message
   (or honor `--force` semantics — out of scope for v1; just refuse).
4. Window setup (kill stale windows for `fresh`, etc.) happens in the
   parent so it can report errors.
5. `os.fork()`; child calls `os.setsid()`, redirects stdio to
   `~/.pm/sessions/<tag>/loops/<pr-id>-<action>.log`, writes pidfile,
   runs the loop, on exit removes pidfile.
6. Parent releases the lock and exits, leaving the daemon running.

### R8.3 Stop semantics
A `pm pr <action> stop <pr_id>` command (out of scope for v1 — task
says "write only `start` first") would: read pidfile, send `SIGTERM`,
wait up to 10s for graceful drain (loops check
`stop_requested`-equivalent via signal handler), then `SIGKILL` if
still alive. v1 scope is start only; document the contract for the
follow-up.

### R8.4 Stale-pidfile sweep
On every CLI handler invocation (and on TUI mount via a small helper):
walk `~/.pm/sessions/<tag>/loops/`; for each `*.pid`, `os.kill(pid, 0)`
to test liveness; if dead, remove the pidfile and call
`runtime_state.clear_action(pr_id, action)` so the picker doesn't show
a phantom running loop.

### R8.5 Terminal-state cleanup
The daemon's main coroutine wraps the loop in a `try/finally` that:
- Sets the runtime_state to `done` (with verdict) or `failed`.
- Removes its pidfile.
- Closes the log file.

Crashes covered by the parent's atexit handler? — no, the parent has
already exited. The child's signal handlers (SIGTERM, SIGINT) install
the same finally cleanup. SIGKILL is uncoverable; the next sweep
catches it.

## Restart restoration (R9 — added)

### R9.1 TUI on mount: discover daemon-driven loops
`runtime_state.sweep_stale_states` (runtime_state.py:195) currently
clears any in-flight states on mount because "a fresh TUI process
can't own panes or loops recorded by a previous one." With
daemonization that assumption flips: in-flight `review-loop` / `qa`
entries may belong to a *still-alive* daemon. Modify the sweep to:
1. For each in-flight entry, if a corresponding pidfile exists and its
   PID is alive, **leave the entry alone** (or mark a flag indicating
   "owned-by-daemon").
2. Otherwise (no pidfile, or dead PID), clear as today.

### R9.2 TUI rebinds UI surfaces to runtime_state
Today `_poll_loop_state_inner` (review_loop_ui.py:387) iterates
`app._review_loops` to drive spinners + sticky log lines, and
`poll_qa_state` (qa_loop_ui.py:281) does likewise for QA. After
daemonization an externally-owned loop doesn't appear in those
in-memory dicts. The pollers must additionally enumerate
`runtime_state.get_pr_actions(pr_id)` for each PR and synthesize the
spinner/badge state from there when no in-memory state exists.

Concretely:
- The picker badge path (already runtime_state-driven —
  `runtime_state.derive_action_status`) keeps working unchanged.
- The TechTree spinner needs a "PR has an in-flight runtime_state
  entry for review-loop or qa" check parallel to the existing
  `app._review_loops` / `app._qa_loops` checks.
- Sticky log notifications on completion: after restart the TUI
  missed the start announcement, so re-emit a "review loop in
  progress for {pr_id} (resumed from prior session)" sticky on mount
  for any live daemon entry. On terminal-state transition (done /
  failed) the TUI emits the usual completion log line.

### R9.3 Verdict completion handoff
The daemon writes runtime_state terminal states. The TUI's existing
hook-driven verdict pollers (review_loop_ui.py:_poll_impl_idle and
peers) already consume verdicts from transcripts and runtime_state.
The new wiring: when the TUI sees a runtime_state entry transition
in_flight → terminal for review-loop or qa, run the same completion
follow-through (`_maybe_start_qa`, `_maybe_auto_merge`, etc.) it would
have run if the loop had been TUI-internal. This is a small adapter
that calls into the existing code paths.

### R9.4 Self-driving QA state externalization
`app._self_driving_qa[pr_id] = {"pass_count": …, "required_passes": …}`
must move to runtime_state under the `qa` action's extras (e.g.
`self_driving={"pass_count": …, "required_passes": …}`). The
daemon updates pass_count after each scenario completion; the TUI
reads it for follow-through decisions in `_on_qa_complete`. This
preserves "completion policy stays TUI-side" while letting the
daemon survive without losing self-driving accounting.

## Ambiguities

### A1. ~~**[UNRESOLVED]** Background-thread hosting model~~ (resolved → B)
The task says "give the underlying CLI commands their own tmux-aware
launchers, the same way `pr start`, `pr review`, `pr merge`, and `meta`
already do." But those commands launch a tmux window running an
interactive Claude session and exit — no Python-side background
thread is required after launch. The pane lives in tmux; verdict
detection is hook-driven (transcripts read by the TUI).

QA and review-loop are different: they have a Python-side coordinator
thread (`run_qa_sync` / `start_review_loop_background`) that drives
multiple panes, retries dead scenarios, polls verdicts, transitions
status, etc. That thread today runs inside the TUI process so it can
mutate `app._data`, call `app.call_from_thread(...)`, and use textual
log helpers.

If the CLI handler is to launch these without the TUI:
- **Option A**: CLI blocks (foreground) until the loop completes. Bad
  fit for the popup — the popup pane is meant to dismiss when its
  command returns.
- **Option B**: CLI double-forks a detached daemon (setsid, redirect
  stdio to log) that runs the loop. Loop writes runtime_state for
  external observers; TUI polls runtime_state instead of in-memory
  dicts when the originating PID isn't its own.
- **Option C**: Keep in-process loop but add a tiny RPC: CLI signals
  TUI via a different (non-popup) mechanism. This *is* the carve-out;
  keeping it under another name doesn't satisfy R6.
- **Option D**: Run the loop synchronously in the CLI process but
  return early (background thread continues until the parent exits —
  effectively kills it). **This is silently broken.**

→ **Question for user**: which hosting model? Option B (daemonize) is
the only one that genuinely removes the carve-out. It is a
non-trivial refactor of `qa_loop.py` and `review_loop.py`
(decoupling from `app.*` callbacks, replacing TUI logging with file
logging, polling runtime_state from the TUI). Estimate: this PR
becomes ~1500-2500 LOC across many files, plus test updates. Confirm
before proceeding.

### A2. **[UNRESOLVED]** Dependency `pr-fcaa434` is PENDING
The task summary lists `pr-fcaa434 (plan-subcommand window management)`
as "PENDING" and "lays groundwork." Without that PR landed, there is
no reference pattern to crib from for plan-subcommand-style window
management. Should we:
- (i) Wait for pr-fcaa434 before starting?
- (ii) Implement this PR first using `pr start` / `pr review` as the
  reference pattern (despite the note)?
- (iii) Implement the dependency inline as part of this PR?

→ **Question for user**: which?

### A3. Naming of `pr review-loop start`
The task says add `pm pr review-loop start <pr_id>`. Click groups
typically use snake or kebab; existing groups use kebab (e.g.
`pr_id` argument names). Confirm group name `review-loop` (kebab) vs
`review_loop`. Proposed: `@pr.group("review-loop")` with subcommand
`start`. (Resolvable — proceeding with kebab.)

### A4. `--session` resolution when run from inside another pm session
If a user is in tmux session `pm-foo` and runs
`pm pr qa pr-X --session pm-bar`, do we honor `pm-bar`? Or refuse?
Proposed: honor it; the explicit flag wins over auto-detection. The
flag is "for callers outside" but there's no harm in letting an
inside-caller override.

### A5. Self-driving state externalization scope
`app._self_driving_qa` carries `pass_count` / `required_passes` and is
read in `qa_loop_ui._on_qa_complete` (qa_loop_ui.py:355-433) which lives
in the TUI process. If a CLI-launched QA loop completes, the
completion handler must run somewhere that can read self-driving
state, transition status, kick off review loops on NEEDS_WORK, etc.
Scope question: do we move the entire `_on_qa_complete` policy into
runtime_state-driven code, or keep the policy TUI-side and have the
CLI loop only handle the QA scenarios + verdict-record? The latter
means a CLI-launched QA loop with no TUI running has no NEEDS_WORK
follow-through. Probably acceptable for the popup case (TUI is up
when the popup runs), but should be confirmed.

→ **Question for user**: keep `_on_qa_complete` policy TUI-side,
right? (i.e. CLI handler delegates back to the TUI for completion
policy via runtime_state + an existing TUI poller that picks up
non-`app._qa_loops` finished loops.)

## Edge Cases

### EC1. Picker `[done VERDICT]` mirroring
qa_loop_ui.py:312-315 records `runtime_state.set_action_state(..., "qa",
"done", verdict=…)` after a loop completes. CLI handler must do the
same so the picker's `[done VERDICT]` annotation still appears.

### EC2. Suppress-switch flag
`runtime_state.consume_suppress_switch` is honored by the TUI side
(qa_loop_ui.py:89). CLI handler must honor it too — when the user
dismisses the popup spinner with q/Esc the launched window must not
steal focus. Mirror the consume call before any `select_window`.

### EC3. Container removal race
review_loop_ui.py and pr.py:1221-1226 remove any pre-existing container
synchronously before `wrap_claude_cmd`. CLI handler must too.

### EC4. `pr review-loop start` from outside tmux
With `--session` pointing at a session that exists, the CLI handler
operates on it without needing to be inside tmux. Same for `pr qa`.
Today `_launch_review_window` exits early if `not tmux_mod.in_tmux()`
(pr.py:1132). The new path replaces that check with: tmux is required
(`has_tmux`), session must exist (`session_exists`), but caller need
not be inside it.

### EC5. Picker `_MODIFIED_ACTION_CMDS` template substitution
`{pr_id}` substitution currently produces e.g. `pr qa fresh pr-X`.
After the carve-out is gone, `popup_cmd_cmd` runs that string via
`pm_core.wrapper`, hitting `pr_qa fresh <pr_id>` — which means
`pr qa` must accept `fresh` and `loop` as a positional first arg.
Today `pr qa` takes a single `pr_id` arg. Need to add subcommands
`pr qa fresh` / `pr qa loop` (Click subgroup) **or** make `pr qa`'s
first arg optionally one of `fresh`/`loop` with `pr_id` second.
Proposed: subgroup approach, mirroring `pr review-loop start`
structure for consistency:
```
pm pr qa <pr_id>
pm pr qa fresh <pr_id>
pm pr qa loop <pr_id>
```
Implementation-wise that's three Click commands sharing a helper.

### EC6. Picker uses `tui:` route for `pr qa fresh` / `loop` modifiers
After R7 these become `pr qa fresh {pr_id}` / `pr qa loop {pr_id}`.
Verify that `_MODIFIED_ACTION_CMDS` consumers in
`_run_picker_command` work with non-`tui:` strings — they should
(falling through to the wrapper subprocess path, same as `pr start`).

### EC7. Tests
- Existing tests for the popup carve-out that assert SIGUSR2 routing
  for `pr qa` / `review-loop start` need to be updated.
- New tests for `pr qa` window-management modes.
- New tests for `pr review-loop start`.
- Tests for `resolve_target_session` precedence.

## Implementation phases

1. **Foundation**
   - `pm_core/cli/_session_target.py` with `resolve_target_session`
     (R5).
   - `pm_core/loop_daemon.py` with: pidfile read/write, double-fork
     spawn, signal-based stop, stale-pidfile sweep (R8).
2. **Runtime-state extensions**
   - Self-driving QA fields under the `qa` action (R9.4).
   - `sweep_stale_states` daemon-aware refinement (R9.1).
3. **CLI handlers**
   - Replace `pr_qa` body (pr.py:1725) with daemonized launcher;
     add `pr qa fresh` / `pr qa loop` subcommands.
   - Add `pr review-loop start` (new group + subcommand).
4. **Loop refactors**
   - Decouple `qa_loop.run_qa_sync` and review_loop coordinator from
     `app.*` callbacks. Replace `app.call_from_thread(...)` with
     pure on_update callbacks; replace `app.log_message` with
     file-logging. The existing functions already take
     `on_update: Callable[[QALoopState], None]` so the surgery is
     mostly removing the TUI-only wrappers.
5. **TUI rehydration**
   - Pollers enumerate runtime_state for daemon-owned loops
     (R9.2).
   - Mount-time sticky-log re-announcement for live daemons (R9.2).
   - Completion follow-through adapter on terminal-state transitions
     (R9.3).
6. **Picker / chord cleanup**
   - Remove popup carve-out (R6).
   - Update `_ALL_ACTIONS` / `_MODIFIED_ACTION_CMDS` (R7).
7. **Tests**
   - `_session_target` precedence.
   - Daemon spawn / pidfile / sweep.
   - QA / review-loop CLI commands.
   - TUI rehydration on mount with a live pidfile + runtime_state
     entry.

## Status

**Foundation landed; integration work remains before merge.**
Will not merge until pr-fcaa434 also lands (per A2).

### Done in this commit
- `_session_target.resolve_target_session` (R5).
- `loop_daemon` module: pidfile layout, double-fork spawn (pipe-based
  PID handoff), `request_stop` (SIGTERM → 10s drain → SIGKILL),
  `sweep_stale_pidfiles`, transcript-dir helper (R8).
- `runtime_state.sweep_stale_states` accepts
  `protect_alive_for_session=`; TUI mount passes its session so
  daemon-owned in-flight entries survive restart (R9.1).
- `pm pr qa` rewritten to a daemonized launcher with `default` /
  `fresh` / `loop` modes (R1, R2, R3).
- `pm pr review-loop start` added as a new subgroup, daemonized
  (R4).
- Popup carve-out at session.py:1903-1907 deleted (R6).
- `_ALL_ACTIONS` / `_MODIFIED_ACTION_CMDS` updated to direct-CLI
  routes (R7).
- Tests: `test_loop_daemon.py`, `test_session_target.py`;
  `test_popup_picker.py` updated.

### Remaining (must land before merge)

1. **TUI rehydration of in-memory surfaces (R9.2).** TechTree spinner
   and sticky-log paths still read from `app._review_loops` /
   `app._qa_loops`. Add a check that consults runtime_state for
   in-flight `review-loop` / `qa` entries owned by a live pidfile,
   so daemon-driven loops also animate after a TUI restart and after
   any CLI-initiated launch.
2. **Completion follow-through adapter (R9.3).** When a daemon's
   runtime_state entry transitions to a terminal state, the TUI's
   pollers must run the same NEEDS_WORK → review / PASS → merge
   policy currently gated on the in-memory `_qa_loops` /
   `_review_loops` dicts. Concretely: extend
   `qa_loop_ui.poll_qa_state` and `review_loop_ui._poll_loop_state_inner`
   to enumerate runtime_state in addition to the in-memory dicts.
3. **Self-driving QA relaunch (R9.4).** With a daemon doing one QA
   pass and writing terminal state, the TUI must re-spawn the daemon
   on PASS-but-not-enough-passes by invoking `pm pr qa loop <pr_id>`
   via `pr_view.run_command` (or by calling the CLI handler in-process
   if more direct). Self-driving accounting (`pass_count`,
   `required_passes`) lives under the `qa` action's
   `self_driving={...}` extras in runtime_state — the CLI handler
   already seeds it; the TUI poller increments and decides.
4. **Sticky-log re-announcement on mount.** For each live daemon
   entry found at mount, emit a "[review loop|QA loop] resumed for
   {pr_id}" sticky note so the user knows what's still running.
5. **Container-name lock for review-loop CLI launcher (IR4).** The
   TUI-side `_launch_review_window` may have a per-container lock to
   prevent `wrap_claude_cmd` races. When the daemon launches via the
   CLI surface, the same lock must apply across processes.
6. **Tests.**
   - End-to-end: spawn a fake review-loop daemon and assert TUI
     spinner state reflects it after a simulated TUI restart.
   - `pr qa loop` self-driving accounting in runtime_state.
   - `request_stop` SIGTERM / SIGKILL escalation against a live
     subprocess.

These are the next iteration's work. The current commit removes the
popup carve-out cleanly, and the daemon layer + CLI commands are
testable in isolation.
