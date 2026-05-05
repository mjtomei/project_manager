# pr-6f542a2 — picker action pane silent during runs

## Requirements

### R1. Picker-dispatched actions write runtime_state lifecycle transitions
Add `set_action_state(pr_id, <action>, "running")` on entry and a terminal
write (`"done"` / `"failed"` with verdict) on exit for each picker-dispatched
CLI handler so the popup spinner has something to label.

- `pr_start` (`pm_core/cli/pr.py:722`) — action `"start"`
- `pr_review` (`pm_core/cli/pr.py:1332`) — action `"review"`
- `pr_merge` (`pm_core/cli/pr.py:1781`) — action `"merge"`
- `pr_qa` (`pm_core/cli/pr.py:1708`) — out of scope: this CLI entry just
  prints a "use the TUI" message, the actual qa flow is driven by the TUI's
  `qa_loop_ui` which already writes runtime_state.

Implementation: add a `contextmanager` helper `_action_state(pr_id, action)`
in `pr.py` that wraps the body, writing `running` on enter, `failed` on
non-zero `SystemExit` / unhandled exception, `done` on clean exit. Helper
lives in `pr.py` (not `runtime_state.py`) because it uses click conventions
and is CLI-handler specific.

### R2. Picker direct-subprocess branch shows the spinner
`_run_picker_command`'s else-branch (`pm_core/cli/session.py:1606`) currently
captures stdout/stderr and only emits them after the subprocess exits — the
popup pane stays blank during the run. Show the same runtime_state-driven
spinner used for `tui:` route by:

1. Parsing `(pr_id, action, fresh)` from the picker `cmd` template (e.g.
   `pr start {pr_id}` → `("pr-...", "start", False)`,
   `pr review --fresh {pr_id}` → `("pr-...", "review", True)`,
   `pr merge --resolve-window {pr_id}` → `("pr-...", "merge", False)`).
2. Spawning the subprocess via `subprocess.Popen` with PIPEs.
3. Running the action spinner against runtime_state in the foreground while
   the subprocess runs.
4. Exiting the spinner when window appears, when terminal state is reached,
   *or* when the subprocess exits.
5. On subprocess exit (only path that returns control here), emit stdout/
   stderr like today, with `_wait_dismiss` on error.

The spinner core (`_wait_for_tui_command`) is refactored to accept
`(pr_id, action, fresh)` directly plus an optional `proc_done` callable; the
existing tui-route call site continues to extract from `tui_cmd` and call
the refactored function.

## Implicit Requirements

- The `running` write on `pr_start` entry must not clobber `session_id` /
  `pane_id` set by `pane_idle._runtime_mirror_register` if a stale value is
  already present. `set_action_state` merges extras, so writing
  `running` with no extras preserves them — matches existing behavior.
- `done` writes from the context manager will be overwritten by
  `pane_idle`'s register/heartbeat writes when the action's pane registers.
  This is fine: derive_action_status defers to live hook events on
  `session_id`, so no UI regression.
- Each handler has multiple early-`SystemExit(1)` paths (e.g. PR not found,
  status preconditions) — the wrapper must catch `SystemExit` and inspect
  `.code` to record `failed`.
- For `pr_start` paths that simply switch to an existing window without
  doing real work, marking `done` on exit is acceptable — the spinner will
  detect window_open before reading the terminal state and exit through the
  window_open branch anyway.
- The picker template parser must tolerate `--fresh`, `--resolve-window`,
  and any future flags. Strategy: skip flags (`tok.startswith("--")`); the
  PR id is the first non-flag positional after the subcommand.

## Ambiguities (resolved)

- **Streaming vs. capture for direct subprocess**: spec mentions verifying
  whether display-popup raw-mode TTY mangling is still relevant. Out of
  scope for this PR — keep capture, rely on spinner for liveness. The
  spinner satisfies the user-visible "something is happening" need.
- **`pr review` writing 'done' even though the launched window's reviewer
  is still running**: pane_idle's mirror_register will overwrite the `done`
  with `running` once the review pane registers, so the picker badge stays
  correct. The spinner only sees `done` briefly, but by that point the
  review window has typically opened and the spinner exits via window_open.
- **`pr merge` clean-merge path opens no window**: this is exactly the
  case `done` is most useful for — the spinner exits via terminal-state
  short-circuit and shows `✓ merge: done`.

## Edge cases

- **`pr start` on an already-in_progress PR with existing window**: handler
  returns early after `select_window`. Wrapper writes `done`. Spinner sees
  window_open immediately and exits through that branch. ✓
- **`pr merge --resolve-window` on a conflict**: handler calls
  `_launch_merge_window` (creates a window) and returns successfully.
  Wrapper writes `done`. Spinner sees `merge-{display_id}` window appear,
  switches to it. ✓
- **User dismisses popup with q/Esc mid-run**: spinner already calls
  `request_suppress_switch`. The CLI subprocess keeps running detached;
  any later `done` write doesn't matter for popup UX. The next picker
  invocation that observes the entry will see the latest state. ✓
- **`set_action_state` write race with `pane_idle.mirror_register`**: both
  use file-locked read-modify-write (`fcntl.flock(LOCK_EX)`). No corruption.
- **Multiple early-return success paths in `pr_start`** (line 817, 821, 825):
  each returns success → wrapper writes `done`. Window-open spinner short-
  circuit handles the user-visible flow.

## No-claude-print audit

Required by spec. Verified by grep:

```
grep -rn "launch_claude_print" /workspace/pm_core/ --include="*.py"
```

Expected callers: `review.py`, `spec_gen.py`, `qa_loop.py`. None on
merge/start/review picker action paths. Will verify and report in a
comment.

## Out of scope

- Streaming stdout from direct subprocess (raw-mode TTY question).
- Auditing every conflict path of `_launch_merge_window` for completeness.
  All current call sites (1596, 1645, 1664, 1691, 1847, 1926, 1945, 1995)
  already invoke it; no silent-echo branches identified in this read.
- pr-c1f8086 (stale workdir yaml in `_wait_for_tui_command`) — separate PR.
