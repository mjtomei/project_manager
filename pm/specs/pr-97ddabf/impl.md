# Spec: Watcher-target window for regression test launches

## Requirements

1. **Add optional `target_window` parameter to `launch_qa_item()`** — `pm_core/tui/pane_ops.py:416`. When set, the QA-item Claude session is opened as a split inside that tmux window instead of the TUI's current window. When omitted, behavior is identical to today (split inside the current window via `get_session_and_window`).

2. **Thread the parameter through `launch_pane()`** — `pm_core/tui/pane_ops.py:153`. `launch_qa_item` calls `launch_pane(app, cmd, "qa-item")`; the underlying tmux split is performed there. Add `target_window: str | None = None` to `launch_pane` and use it in place of `get_session_and_window`'s window when provided.

3. **Underlying tmux call** — `tmux_mod.split_pane(session, direction, wrap)` in `pm_core/tmux.py:77` currently uses `-t <session>` which targets the active pane of the active window. Extend it to optionally target `session:window` so the split lands in the requested window. Add `window: str | None = None` parameter; when set, target `f"{session}:{window}"`.

4. **Pane registry / layout uses the target window** — `pane_registry.find_live_pane_by_role(session, role, window=window)` and `pane_layout.preferred_split_direction(session, window)` / `register_and_rebalance(session, window, ...)` already accept a window argument. Pass the target window to these so dedup, registry, and rebalance operate on the correct window.

5. **TUI Enter-key path is unchanged** — `app.py:1117` invokes `pane_ops.launch_qa_item(self, message.item_id)` with no extra arg. With `target_window` defaulted to `None`, current behavior is preserved.

## Implicit Requirements

- `launch_pane`'s "focus existing pane" branch (`tmux_mod.select_pane_smart(existing_pane, session, window)`) must use the target window, not the TUI's current window, so dedup happens scoped to the supervisor's window when called by the supervisor.
- `app.log_message(...)` calls remain valid — they don't depend on a window.
- The `get_session_and_window(app)` call still runs (we still need the session name and the TUI's `in_tmux` guard). When `target_window` is provided, only the window is overridden; the session name still comes from the TUI's tmux env.

## Ambiguities

- **Should the new pane steal focus?** `launch_pane` currently calls `tmux_mod.select_pane_smart` after splitting. For watcher-launched tests, focusing the new pane could yank the user away from wherever they are. **Resolution:** keep focus behavior unchanged for now — the supervisor itself runs in a non-foreground window and `select-pane` only selects within that window. Selecting the new pane within the supervisor's own window is fine and even desirable (so when the user switches to that window, the test pane is active). If this turns out wrong, follow-up can swap to `split_pane_background`.

- **Should `target_window` accept either a tmux window id (`@N`) or window name?** **Resolution:** accept whatever string the caller provides — tmux's `-t session:window` resolves both.

## Edge Cases

- **`target_window` doesn't exist** — tmux split-window will fail; the existing `try/except` in `launch_pane` logs and surfaces the error via `app.log_message`. No special handling needed.
- **Multiple QA items launched into the same supervisor window** — the existing role="qa-item" dedup logic will focus the prior pane unless `fresh=True`. With per-window dedup (fix above), launches in different windows don't collide; launches into the same supervisor window for different regression tests will share the "qa-item" role and dedup. This may or may not be desired but matches current single-launch semantics — leave as-is for this PR.
- **Caller not in tmux** — `get_session_and_window` already returns `None` and logs; behavior preserved regardless of `target_window`.
