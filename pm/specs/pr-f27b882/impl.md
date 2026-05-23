# Spec: pr-f27b882 — picker spinner exits early on stale terminal state

## Requirements

1. **Snapshot state at popup start** — In `_wait_for_tui_command` at
   `pm_core/cli/session.py` (around the `initial_window_ids` snapshot at lines
   1272-1274), capture the initial action state from
   `_rs.get_action_state(pr_id, action)` for `fresh`-mode invocations.

2. **Track state transitions during the spin** — Inside the `while True:` loop
   (line 1313), once `cur_state` is read, set a `saw_state_change` flag when
   `fresh` and `cur_state != initial_state`.

3. **Gate the terminal-state short-circuit** — At lines 1345-1364, the existing
   short-circuit (`cur_state in ("done","failed") and not window_open`) must
   only fire when the terminal state is genuinely from this invocation. For
   `fresh` mode, require `saw_state_change` (or `initial_state` not in
   terminal states) before short-circuiting; otherwise keep spinning so the
   launcher's `queued/launching → running → done` transition is observed and
   the new window-id branch (lines 1317-1334) eventually fires the auto-switch.

4. **Preserve non-fresh behavior** — Non-`fresh` actions (no state snapshot)
   continue to short-circuit on terminal state exactly as today.

## Implicit requirements

- The launcher will eventually transition state away from the stale terminal
  value. If it does not (launcher crashes before writing state), the spinner
  must still be cancellable via the existing q/Esc/timeout paths — no new
  hang. The existing keypress poll lower in the loop covers this.
- Stale terminal state where the loop already produced a window must still
  switch focus correctly: when `fresh` finds initial_window_ids non-empty and
  cur_state is stale-terminal, we keep waiting; the kill+recreate cycle
  populates `new_ids`, the `window_open` branch fires and switches focus.

## Ambiguities

- **What counts as "terminal" for `initial_state`?** Resolved: treat
  `('done','failed')` symmetrically with the existing short-circuit. If
  initial_state is already terminal, we require an observed change before
  exiting. If initial_state is None or non-terminal, the existing logic is
  fine (saw_state_change isn't required because the short-circuit already
  represents a genuine transition from the snapshot).

- **Is the `saw_state_change` flag sticky?** Resolved: yes, set once and never
  cleared. The launcher may rapidly transition queued→running→done within a
  single poll interval; we just need to know that *some* change occurred since
  popup start.

## Edge cases

- **Launcher writes a fresh terminal state quickly** (e.g. action errors out
  immediately). saw_state_change becomes True after the first poll that
  observes the new state — but the new state value happens to equal the stale
  one (`'done' == 'done'`). To handle this, also consider the `started_at`
  timestamp or a monotonic counter. **Simplest:** compare the whole entry
  dict, not just `state`, so e.g. an updated `verdict`, `started_at`, or
  iteration counter trips the flag. Use entry identity by checking
  `(state, started_at)` tuple if available, falling back to `state` alone.

- **`get_action_state` returns None initially, then a populated entry** — a
  None→non-None transition counts as state change for fresh.

- **Non-fresh modes** — `initial_state` stays None; saw_state_change logic is
  skipped; behavior unchanged.
