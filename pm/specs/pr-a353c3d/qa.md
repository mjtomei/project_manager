# QA Spec: Launch plan pane actions in a dedicated plans window

## Requirements

1. **Plan-pane actions launch into a dedicated `plans` tmux window**, not the TUI's main window. In scope:
   - `plan add` (role `plan-add`)
   - `plan breakdown` (role `plan-breakdown`)
   - `plan review` (role `plan-review`)
   - `plan edit` (role `plan-edit`) — opens `$EDITOR <plan-file>`
   - `plan deps` (role `plan-deps`)
   - plan activation via Enter (role `plan`) — `less <plan-file>`
2. The first such action must auto-create a tmux window named `plans` (with a `bash -l` placeholder pane, cwd = project root) if it does not yet exist.
3. After launching the pane, focus must switch to the `plans` window so the user sees the new pane immediately.
4. **`plan load`** is unaffected — it runs in-process via `_run_command`, not in a pane.
5. **Cross-action parallelism** works: e.g. `plan-add` for one plan and `plan-breakdown` for another can run as separate panes simultaneously in the plans window.
6. **Same-role dedup is preserved**: invoking the same role twice (e.g. two `plan-add` actions) focuses the existing pane (per QA caveat in PR notes). This is the documented limitation.
7. **Non-tmux fallback / failures**: if `_ensure_plans_window` returns None (not in tmux, lookup failure), `launch_pane` is called with `target_window=None` and behavior is unchanged (no crash).
8. **Plans window resilience**: if the plans window is killed mid-session, the next plan action recreates it.
9. The TUI main window is not split or cluttered by plan actions any more.

## Setup

Use `tui-manual-test.md` to bootstrap a test project with `pm init`, a couple of PRs, and one or more plans. Plans can be added via `pm plan add <name>` from the TUI (which is itself one of the actions under test) or via the CLI ahead of time. Start `pm session` so a tmux session exists; drive the TUI with `tmux send-keys`.

## Edge Cases

- Plans window doesn't exist on first action → must be created with placeholder.
- Plans window already exists from prior actions → reused, no duplicate.
- Plans window killed by user → recreated next time.
- Two same-role launches → second focuses the first (dedup); verify no crash.
- Two different-role launches in quick succession → both panes coexist in plans window.
- Plan activation (`Enter` on plan row) → opens `less` in plans window, not main.
- Main TUI window remains uncluttered after multiple plan actions (only original main pane(s)).

## Pass/Fail Criteria

**Pass**:
- After any plan-pane action, a tmux window named `plans` exists in the session.
- The newly-launched command pane is in the `plans` window (verify via `tmux list-panes -t <session>:plans -F '#{pane_id} #{pane_current_command}'` or window contents).
- TUI main window is not split with plan-action panes.
- Focus switches to `plans` window after launch (active window check via `tmux display-message -p '#W'` or list-windows with `#{?window_active,*,}`).
- Cross-action panes coexist; same-role launches dedup to one pane.
- Non-fatal: errors in `_ensure_plans_window` log but don't crash the TUI.

**Fail**:
- Plan action splits the main window.
- Plans window not created or focus not switched.
- Crash / unhandled exception when plans window cannot be created.
- Same-role second invocation creates a duplicate pane (would indicate dedup regression).

## Ambiguities

None unresolved — see `impl.md` A1/A2 for the inclusion of `deps` and plan activation.

## Mocks

No mocks needed. The actions launch real subprocesses (`pm plan add`, `pm plan review`, `less`, `$EDITOR`), but for QA purposes we only care that:
- The pane is opened in the right window.
- The command in the pane is the expected one (verify via `tmux list-panes -F '#{pane_current_command}'` or `capture-pane`).

The `pm plan add` / `breakdown` / `review` Claude-driven workers don't need to actually complete; we just need to confirm the pane was launched with the right command in the right window. We can let the placeholder shell sit, or kill the launched pane after observation.
