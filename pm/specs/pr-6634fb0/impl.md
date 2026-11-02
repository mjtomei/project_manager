# Implementation Spec: Convert all pane registry callers to locked_read_modify_write

## Requirements

### R1: Convert `register_and_rebalance` (pane_layout.py:340-343)
After calling `register_pane` (already locked), the function does an unlocked `load_registry` + modify `user_modified` + `save_registry`. This races with concurrent `register_pane`/`unregister_pane` calls. Convert the post-registration `user_modified` reset to use `locked_read_modify_write`.

### R2: Convert `check_user_modified` (pane_layout.py:469-489)
Reads registry, checks geometry, then conditionally sets `user_modified=True` and saves. The read-check-write is unlocked. Convert the write path to `locked_read_modify_write`. The initial read for the early-return (`user_modified` already true) can remain unlocked since it's a read-only fast path.

### R3: Convert `_respawn_tui` (pane_layout.py:607-620)
Reads registry, inserts a new TUI pane entry, sets `user_modified=False`, saves. This races with concurrent pane registrations. Convert to `locked_read_modify_write`.

### R4: Convert `handle_pane_opened` (pane_layout.py:690-697)
Reads registry, checks if pane is known, conditionally sets `user_modified=True` and saves. Convert to `locked_read_modify_write`.

### R5: Convert session creation (cli/session.py:319)
Overwrites the entire registry with a fresh `{session, windows: {}, generation}` dict. This is a full reset, not a read-modify-write. Convert to `locked_read_modify_write` where the modifier ignores the old data and returns the fresh dict. This prevents racing with any concurrent writer that might be operating on a stale session.

### R6: Convert mobile toggle (cli/session.py:572-575)
Reads registry, sets `user_modified=False` on all windows, saves. Convert to `locked_read_modify_write`.

### R7: Convert `rebalance_cmd` (cli/session.py:715-722)
Reads registry, checks for panes, sets `user_modified=False`, saves. The pane check can be done inside the modifier. Convert to `locked_read_modify_write`.

### R8: Convert `_window-resized` handler (cli/session.py:636)
Reads registry to check if panes exist in the window. This is read-only — no save. No conversion needed for locking (just reads). However, the current code reads outside any lock so it could see stale data. Since it's only used for an early-return check (skip if no panes), a stale read is harmless — worst case we run a rebalance that does nothing.

### R9: Convert PR merge cleanup (cli/pr.py:1237-1240)
After calling `register_pane` (already locked), does unlocked `load_registry` + set `user_modified=False` + `save_registry`. Same pattern as R1. Convert to `locked_read_modify_write`.

### R10: Convert `heal_registry` (tui/pane_ops.py:44-90)
Complex multi-step healing: iterates all windows, removes dead panes, ensures TUI pane is registered, saves. The entire modification block should be wrapped in `locked_read_modify_write`.

### R11: Convert `rebalance` wrapper (tui/pane_ops.py:160-163)
Reads registry, sets `user_modified=False`, saves. Convert to `locked_read_modify_write`.

### R12: Remove `save_registry` from public API
After all write callers are converted, `save_registry` should be removed from the public API. The only way to write should be through `locked_read_modify_write`. Options:
- Rename to `_save_registry` (private)
- Remove entirely if no internal unlocked callers remain
- Remove the re-export from `pane_layout.py`

### R13: Keep `load_registry` public for read-only access
`load_registry` remains public since many callers use it read-only (e.g., `find_live_pane_by_role`, `cli/helpers.py` TUI pane lookup, `rebalance` reading pane list, `handle_pane_exited` reading generation). These read-only uses are safe — atomic write in `locked_read_modify_write` ensures readers never see partial data.

## Implicit Requirements

### IR1: Modifier functions must use `_prepare_registry_data`
All modifier functions passed to `locked_read_modify_write` receive raw JSON (or `None`). They must call `_prepare_registry_data(raw, session)` to handle missing/corrupt files and old-format migration, just like the existing `register_pane` and `unregister_pane` modifiers do.

### IR2: Modifier functions that only sometimes write should return `None` to skip
`locked_read_modify_write` skips the write when the modifier returns `None`. Callers that conditionally modify (e.g., `check_user_modified`, `handle_pane_opened`) should return `None` when no change is needed.

### IR3: Avoid holding the lock during tmux subprocess calls
`_reconcile_registry` already demonstrates this pattern: query tmux state OUTSIDE the lock, then do the registry mutation inside. New conversions should follow this pattern where tmux queries are needed alongside registry modifications.

### IR4: `handle_pane_exited` reads are acceptable unlocked
`handle_pane_exited` (pane_layout.py:508,528) does unlocked reads to check generation and count panes before/after `unregister_pane`. These reads don't modify the registry — the actual mutations go through already-locked `unregister_pane` and `_reconcile_registry`. The reads may see slightly stale data but the logic is tolerant of this (worst case: an extra rebalance or a missed optimization).

### IR5: Update backward-compat re-exports in `pane_layout.py`
`pane_layout.py` re-exports `save_registry` from `pane_registry`. When `save_registry` is removed/privatized, the re-export must be updated or removed. Also export `locked_read_modify_write` and `_prepare_registry_data` for callers in other modules that need them.

### IR6: Tests must be updated
Tests in `test_pane_layout.py`, `test_pane_registry.py`, and `test_companion_pane.py` that mock or call `save_registry` directly may need updates.

## Ambiguities

### A1: Should `_window-resized` handler's read-only load be converted?
**Resolution:** No. The load at session.py:636 is read-only (checks if panes exist to short-circuit). No save follows. A stale read is harmless — it only skips a no-op rebalance. Converting would add unnecessary lock contention on a hot path (resize events are frequent during drag).

### A2: Should `handle_pane_exited` reads be converted?
**Resolution:** No. The reads at pane_layout.py:508 and 528 are for checking generation and pane counts. The actual mutations go through `unregister_pane` and `_reconcile_registry` which are already locked. Wrapping the reads in a lock would require holding the lock across tmux subprocess calls (the Popen for deferred rebalance), violating IR3.

### A3: Should `rebalance()` itself (pane_layout.py:370) be converted?
**Resolution:** No. `rebalance()` reads the registry to compute layout but never calls `save_registry`. It's read-only with respect to the registry. The tmux operations it performs (swap-pane, select-layout) are separate from registry state.

### A4: Should `launch_pane`'s read (tui/pane_ops.py:137) be converted?
**Resolution:** No. It reads the generation string for building the EXIT trap command. This is read-only and a stale generation is not dangerous — the pane-exited handler already validates generation against the registry.

### A5: Should `session_mobile` toggle's read-then-write span multiple windows?
**Resolution:** Yes, the modifier should iterate all windows and set `user_modified=False` on each, matching current behavior. The lock ensures no window's panes are modified concurrently.

### A6: Should `heal_registry` query tmux inside the lock?
**Resolution:** No. Following IR3, `heal_registry` should collect all tmux state (live panes per window, current window ID, TUI pane ID) BEFORE entering the lock, then use that snapshot inside the modifier. This avoids holding the lock during subprocess calls. The small window for state changes between tmux query and lock acquisition is acceptable — heal_registry runs on TUI startup, not a hot path.

### A7: How to handle `register_and_rebalance` and `cli/pr.py` which call `register_pane` (locked) then do a separate unlocked load/modify/save?
**Resolution:** Replace the separate load/modify/save with a single `locked_read_modify_write` call. The `register_pane` calls remain separate — they're already locked. The second locked call for `user_modified` reset is a separate atomic operation, which is correct.

### A8: What about `save_registry` call in session creation (cli/session.py:319)?
**Resolution:** Convert to `locked_read_modify_write` where the modifier ignores old data and returns the fresh dict. This serializes with any concurrent writer that might be running against the same registry file.

## Edge Cases

### E1: `heal_registry` tmux state changes between query and lock
Between querying tmux live panes and acquiring the lock, a pane could be created or destroyed. This is acceptable — heal_registry is best-effort and runs once on TUI startup. The next pane lifecycle event will correct any discrepancy.

### E2: `register_and_rebalance` two-step pattern
The function calls `register_pane` (locked) then separately resets `user_modified` (to be locked). Between the two operations, another caller could set `user_modified=True`. This is acceptable — the reset is intentional (we just created panes and want rebalance to run). If another caller sets `user_modified=True` in between, our reset will override it, which is the desired behavior for freshly-registered panes.

### E3: `check_user_modified` geometry check outside lock
The tmux geometry query happens outside the lock. Between the query and the lock-protected write, the layout could change. This is acceptable — worst case we set `user_modified` when the layout has already been corrected, which only prevents one auto-rebalance until the user manually rebalances.

### E4: `_respawn_tui` mixed tmux and registry operations
`_respawn_tui` creates tmux panes (split_pane/create_window) then registers them. The tmux operations must stay outside the lock. Only the registry update (inserting the TUI pane entry + resetting user_modified) goes inside the lock.

### E5: Existing read-only callers of `load_registry` after `save_registry` removal
`find_live_pane_by_role`, `cli/helpers.py`, `rebalance()`, and others use `load_registry` for read-only access. These remain unchanged. Atomic writes by `locked_read_modify_write` ensure they never see corrupt data.

### E6: Test mocking of `save_registry`
Tests that mock `pane_registry.save_registry` or `pane_layout.save_registry` will need updates. Check `test_pane_layout.py` and `test_companion_pane.py` for save_registry mocks that need to be converted to mock `locked_read_modify_write` or use the real implementation.
