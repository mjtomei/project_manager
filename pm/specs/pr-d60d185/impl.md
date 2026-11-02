# Spec: End-to-end QA review and auto-start command for the regression loop (pr-d60d185)

## Requirements

1. **Auto-start command** that launches all three regression-loop watchers in
   one invocation, with sensible defaults.

   Implemented as a special `WATCHER_TYPE` value `regression-loop` in
   `pm watcher start <TYPE>` (`pm_core/cli/watcher.py:watcher_start`). When
   given that argument, the CLI must:

   - Verify tmux is available and we're inside a tmux session (same guard as
     today).
   - Construct one of each: `DiscoverySupervisorWatcher`,
     `BugFixImplWatcher`, `ImprovementFixImplWatcher`.
   - Register all three with a `WatcherManager` instance and call
     `manager.start(...)` for each one (each runs in its own background
     thread, each manages its own tmux window via `_create_watcher_window`).
   - Block in the foreground, printing per-iteration verdicts from each
     watcher (prefix lines with the watcher's display name so output from
     three concurrent loops is distinguishable).
   - On `Ctrl+C`, request graceful stop on all watchers via
     `manager.stop_all()` and wait for threads to exit (or report after a
     reasonable timeout).
   - The `--wait` option, if present, applies to all three watchers (overrides
     each watcher's `DEFAULT_INTERVAL`). If absent, each watcher uses its own
     default.

2. **Discoverability**: update `watcher_start`'s docstring (`pm_core/cli/watcher.py:142`)
   to document `regression-loop` as a meta-type that starts all three. The
   per-watcher types remain available as before.

3. **End-to-end QA evidence**. Per the PR notes, the QA review must record
   confirmation of three integration paths flagged during pr-e58459b that
   unit tests could not fully cover:

   - (a) The `O` keypress (queue-merge) flow end-to-end including the
     `_stop_before_merge` short-circuit in `_maybe_auto_merge`
     against a live session.
   - (b) `_check_impl_idle` in `pm_core/cli/pr.py` against a real
     `PaneIdleTracker` — verify a fresh CLI invocation against an existing
     transcript correctly resolves `session_id_from_transcript` and picks up
     an existing `idle_prompt` event from `hook_events`.
   - (c) `_launch_qa_detached` running `run_qa_sync` from a fresh detached
     process — verify `pm_session` env vars and signal handlers behave
     correctly outside the TUI thread context.

   Captured in `pm/qa/pr-d60d185.md` as a written checklist that records the
   manual scenario, the observed behavior, and any defects found.

4. **Tests** (unit-level only — full E2E is necessarily manual):
   - A test that verifies `pm watcher start regression-loop` registers three
     watchers (discovery, bug-fix-impl, improvement-fix-impl) on a stub
     `WatcherManager`. (Stub the `tmux` checks and `manager.start` to avoid
     spawning real loops.)
   - A test that verifies an unknown sub-type still produces the existing
     "Unknown watcher type" error path and lists `regression-loop` in the
     types list.
   - Verify the `--wait` override is propagated to each watcher's
     `state.iteration_wait`.

## Implicit Requirements

- `regression-loop` must *not* be added to `WATCHER_REGISTRY` — it is a CLI
  meta-type, not a `BaseWatcher` subclass. Adding it to the registry would
  break `_create_watcher_window` and `watcher_list` semantics. Instead the
  CLI handles it as a special-case before consulting the registry.
- The blocking CLI loop must not hold the `WatcherManager` lock; it polls
  `manager.is_any_running()` periodically.
- Per-watcher kwargs (`auto_start_target`, `meta_pm_root`) are not relevant
  to the three regression-loop watchers — none of them require a target PR.
- All three watchers each create their own tmux window
  (`watcher`/`discovery`/`bug-fix-impl`/`improvement-fix-impl`); since
  watcher windows are distinct, there is no conflict.

## Ambiguities

- **Resolved — meta-type vs new flag.** Considered `pm watcher start --regression-loop`
  vs `pm watcher start regression-loop`. The latter fits the existing
  `start [TYPE]` shape with no new flag, and reads naturally; chose it.
- **Resolved — separate command vs reuse `start`.** Considered a new
  `pm watcher start-regression-loop` command. Reuse of `start` with a
  meta-type keeps the surface small and matches the description "single
  command (`pm watcher start regression-loop` or similar)".
- **Resolved — should QA actually run?** A full live E2E pass requires
  the three upstream watchers operating against real PRs over many hours
  and is not reproducible from this session. The QA artifact captures the
  scenarios, the *intended* observation criteria, and any gaps surfaced via
  static review of the integration points listed in the PR notes; the
  manual run is performed by the operator following the checklist.

## Edge Cases

- **Already running.** If any of the three watchers is already registered
  and running on the global manager (e.g. user previously started one via
  the TUI), `regression-loop` should detect this and skip starting that
  one rather than registering a duplicate. (CLI-level: we use a fresh
  `WatcherManager` per invocation, so duplication only matters if the
  user runs two `pm watcher start regression-loop` in parallel — that
  results in duplicate tmux windows because `_create_watcher_window` kills
  the existing window. Acceptable; documented behavior matches per-watcher
  start.)
- **Ctrl+C during startup.** If interrupt arrives before all three are
  started, `stop_all()` covers whatever was registered.
- **tmux missing.** Same single-watcher error path applies.
