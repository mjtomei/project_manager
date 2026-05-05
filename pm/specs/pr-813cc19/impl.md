# Spec: pr-813cc19 — structured observability for window/pane/spinner/wrapper

## Requirements (grounded in code)

1. **`pm_core/tmux.py:kill_window` (line 126)** — currently no log. Add `_log.info("kill_window: session=%s window=%s", session, window)` at entry.
2. **`pm_core/tmux.py:select_window` (line 397)** and **`select_window_in_session` (line 409)** — no log. Add INFO with target + rc.
3. **`pm_core/tmux.py:new_window` (line 133)** and **`new_window_get_pane` (line 160)** — partial logging. Add post-creation INFO logging the resolved window id/index/name.
4. **`pm_core/cli/helpers.py:kill_pr_windows` (line 301)** — silent. Add INFO entry with PR id + windows considered, INFO exit with killed list. Module already has `_log = configure_logger("pm.cli")`.
5. **`pm_core/home_window/__init__.py:park_if_on` (line 106)** — silent on success. Add INFO when `watching` is non-empty: target window id, watching sessions, parked-to home name.
6. **`ensure_home_window` (line 81)** — add INFO including provider name, ensured window name. (No "created=<bool>" available without changing the provider Protocol — use the resolved name only and note this in ambiguities.)
7. **Popup spinner `_wait_for_tui_command` (`pm_core/cli/session.py:1217`)** — transition-only INFO + `PM_SPINNER_TRACE=1` per-tick:
   - Entry: pr, action, fresh, target_window, initial_window_ids, initial_state.
   - Transition INFO when `cur_state` flips, `window_open` flips, `saw_disappear` flips, keypress arrives, exit reason. Track previous values across loop iterations.
   - INFO `select_window` attempt + rc (the spinner currently calls `tmux_mod.select_window` swallowing the result — capture its bool).
   - INFO `consume_suppress_switch` result (only when True, to match runtime_state policy below).
   - INFO keypress received (q/Q/Esc).
   - INFO exit reason: `window_open`, `terminal_state`, `keypress`, `kbinterrupt`, plus `edit_skip` short-circuit at line 1242 and `not_pr_or_action`.
   - DEBUG cbreak setup outcome.
   - Per-tick verbose under `PM_SPINNER_TRACE=1`: tick i, cur_state, cur_window_ids, saw_disappear, window_open.
8. **`pm_core/runtime_state.py:set_action_state` (line 112)** — silent on transitions. INFO when state actually changes (`prior_state != state` and `state` is not None). Skip no-op writes (state unchanged, no extras change). Include pr_id, action, from, to, verdict (from extras if present, else current).
9. **`pm_core/runtime_state.py:consume_suppress_switch` (line 254)** — INFO only when consumed=True (avoid noise from picker false reads).
10. **`pm_core/wrapper.py:main` (line 142)** — single INFO once per invocation: argv0, selected_root, chosen_via (`override`|`pm_root`|`cwd_walk`|`installed`), is_ipc. Wrapper currently has no logger; configure one via `pm_core.paths.configure_logger`. **Note:** the wrapper imports `pm_core.git_ops` lazily and may run before `pm_core` is on sys.path — but `configure_logger` lives in `pm_core.paths`, which is also imported lazily inside `main()`. The wrapper itself is the *outer* `pm_core.wrapper` already on the import path. Verify `pm_core.paths` is importable before sys.path mutation (it is — `pm_core` is the wrapper's own package).
11. **TUI mount/unmount** (`pm_core/tui/app.py:399 on_mount` and `1045 on_unmount`):
    - `on_mount` already logs `"TUI mounted (cwd=...)"` (line 400). Augment with pid, session_name, trigger (initial vs. restart marker present). The merge-restart breadcrumb at `pm_core/tui/auto_start.py:_MERGE_RESTART_MARKER` provides one trigger source.
    - `on_unmount` (line 1045) — add INFO with reason if discoverable; else generic "unmount".
    - `pane_ops.restart_app` (line 711) — already logs `"restart_app"` (line 720); enrich with the caller's reason where the call is made (e.g., merge-restart marker present).
12. **Container** (`pm_core/container.py`):
    - `wrap_claude_cmd` (line 900) — add INFO entry with label, workdir, container name decision (pre-create) — note line 983 already logs after creation. Add the container-name decision before `create_container`. (Lock acquisition note from spec is gated on pr-fc6db6a's flock landing — out of scope until then.)
    - `remove_container` (line 873) — add INFO entry with name.
13. **`pm_core/review_loop.py:_launch_review_window` (line 117)** — already has INFO `"launching review window: %s"`. Extend entry with pr_id, iteration, loop_id explicitly. Add INFO on successful exit (rc=0, elapsed seconds).
14. **`pm_core/tui/app.py:_drain_command_queue` (line 1004)** — line 1039 already logs `"dispatching queued TUI command"` at INFO. Augment with result on success, failure on exception.
15. **`pm_core/cli/session.py:_run_picker_command` (line 1530)** — silent on dispatch. Add INFO at entry: cmd, route (`tui` or `direct`).

## Implicit requirements

- All new logs must use existing `_log` instances from `configure_logger(...)`. Do not introduce new logger names except `pm.wrapper`.
- Format strings stay grep-friendly (key=value pairs, single line).
- Logs must not raise — every site must tolerate missing fields. `runtime_state.set_action_state` runs on every action transition; a logging error there could mask the actual write. Use defensive `.get()` access.
- `PM_SPINNER_TRACE=1` is read once at function entry; not re-read each tick.
- Spinner transition tracking adds local prev-state vars; do not change loop semantics.
- Container detection of "is_ipc" already lives in `_is_session_ipc_command`; reuse rather than duplicate.

## Ambiguities (resolved)

- **Wrapper logging before `selected_root` is mutated:** call `configure_logger` after `_mark_tmux_session` but before sys.path mutation. `pm_core.paths` is part of the same package as `wrapper.py`, so it's importable regardless of which pm_core variant gets selected later.
- **`ensure_home_window` "created=<bool>":** the provider Protocol's `ensure_window` doesn't return that signal. Resolution: log `provider=<name> name=<window>` only; "created" is out of scope.
- **`set_action_state` no-op detection:** define no-op as `state == prior_state` AND extras is empty/all unchanged. To stay simple, only suppress logs when `state == prior_state` and no extras provided. Extras with same value still log (avoids missed transitions).
- **`consume_suppress_switch` in spinner:** spec says log result; combined with the runtime_state-side rule (only log True), the spinner only logs when True. Net behavior matches.
- **TUI on_unmount reason:** no caller-provided reason exists in current code. Resolution: log generic "unmount" and rely on the existing `restart_app` log to provide the cause when the unmount is from a restart.

No **[UNRESOLVED]** items — proceeding to implementation.

## Edge cases

- Spinner runs in a popup process — its logger must hit the session-tag log file. `configure_logger` from `pm_core.paths` already routes there for the popup subprocess (it's how existing `_log.info("popup-picker invoked: ...")` at session.py:1605 works).
- `runtime_state.set_action_state` is called from many writers, including under flock. Logging happens *outside* the flock window in our implementation? Actually we'll log inside the with-block to capture the *committed* transition; logging is fast and the lock is per-PR-file, so contention is minimal.
- `kill_window` is called from many callsites, including QA cleanup loops. Logging adds one line per kill — bounded by the number of windows.
- `wrapper` runs in many contexts (popup, TUI, CLI). One log line per invocation is fine.
