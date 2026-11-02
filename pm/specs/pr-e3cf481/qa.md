# QA Spec: File-locked read-modify-write helper for pane registry

## Requirements

1. **`locked_read_modify_write` helper** (`pane_registry.py:41-100`): Acquires `fcntl.flock(LOCK_EX|LOCK_NB)` on a sidecar `{path}.lock` file, reads the JSON data file, calls `modifier_fn(data)`, and atomically writes the result (temp + fsync + rename) if `modifier_fn` returns a dict. Returns `None` to skip the write. Uses a retry loop with 50ms sleep and configurable timeout (default 5s). Raises `TimeoutError` on lock acquisition failure. Lock is always released via `finally` block closing the fd.

2. **Atomic `save_registry`** (`pane_registry.py:153-168`): Converted from bare `path.write_text()` to atomic temp-file + `os.fsync` + `os.rename` pattern. Concurrent readers never see truncated files.

3. **`_prepare_registry_data` helper** (`pane_registry.py:118-133`): Extracted format-migration logic (old flat format to multi-window) into a standalone function, used by both `load_registry` and the modifier closures inside `register_pane`, `unregister_pane`, and `_reconcile_registry`.

4. **`register_pane` uses locked helper** (`pane_registry.py:171-189`): Wraps the load-append-save cycle in `locked_read_modify_write`. The modifier closure calls `_prepare_registry_data`, appends the new pane, returns the data dict.

5. **`unregister_pane` uses locked helper** (`pane_registry.py:192-209`): Wraps the load-filter-save cycle in `locked_read_modify_write`. Searches all windows for the pane ID.

6. **`_reconcile_registry` uses locked helper** (`pane_registry.py:261-320`): Tmux subprocess calls (`get_pane_indices`, `session_exists`) happen BEFORE acquiring the lock. The modifier closure uses captured tmux state. Returns `None` to skip write when no changes or session is gone. The `removed` list is populated via closure side-effect.

7. **`kill_and_unregister` inherits locking** (`pane_registry.py:212-216`): Delegates to `unregister_pane`, so it gets locking for free. No direct changes needed.

8. **`find_live_pane_by_role` stays unlocked** (`pane_registry.py:219-258`): Read-only function. Atomic writes (requirement 2) ensure it always sees consistent data.

9. **TUI respawn fallback fix** (`session.py:247-256`): When TUI role is missing from registry and the fallback window lookup runs, it now targets `find_window_by_name(session, "main")` first, then falls back to `list_windows()[0]` (first/index-0 window), instead of the old `get_window_id()` which returned the *active* window (which could be a QA or work window).

## Setup

- Unit tests run via `python -m pytest tests/test_pane_registry.py -x -q` from the project root (`/home/mjtomei/project_manager`).
- The `registry_dir` fixture patches `pane_registry.registry_dir` to use `tmp_path`, so tests operate on isolated temp directories.
- The `locked_read_modify_write` tests use raw `tmp_path` paths (no registry fixture needed).
- TUI respawn fallback (session.py) requires a live tmux session for manual verification or mocking `tmux_mod.find_window_by_name` / `tmux_mod.list_windows` for unit tests.
- For manual/integration testing of the concurrency fix, the `tui-manual-test.md` instruction provides a throwaway project setup with tmux.

## Edge Cases

1. **Missing registry file**: `locked_read_modify_write` passes `None` to modifier; `_prepare_registry_data` constructs a default empty registry. `register_pane` on a fresh session creates the file atomically.
2. **Corrupt JSON file**: `locked_read_modify_write` catches `json.JSONDecodeError`/`ValueError` and passes `None` to modifier. Same recovery path as missing file.
3. **Modifier returns `None`**: File is not written. Used by `_reconcile_registry` when no panes were removed or session is gone.
4. **Lock timeout**: `TimeoutError` raised with descriptive message after configurable timeout. Retry interval is 50ms.
5. **Modifier raises exception**: Lock is released via `finally` block. Exception propagates to caller. Subsequent lock acquisitions succeed immediately.
6. **Concurrent `register_pane` calls**: Serialized by the lock. Each call reads the latest state, so no data loss (the primary bug this PR fixes).
7. **Concurrent `register_pane` + `unregister_pane`**: Also serialized. The second caller sees the first's writes.
8. **Process death while holding lock**: `fcntl.flock` is released when the fd is closed (including on process death). Lock file remains but is immediately reusable.
9. **Old-format registry file**: `_prepare_registry_data` migrates flat format inside the lock, so migration is also race-free.
10. **Atomic write with `rename()`**: If the process dies between `write_text` and `rename`, only the `.tmp` file is left; the original data file is untouched.
11. **TUI respawn targets wrong window**: Before fix, `get_window_id()` returned the active window. After fix, targets window named "main" or falls back to first window by index.
12. **No windows in session during TUI respawn**: `list_windows` returns empty list; `tui_window` stays `None`; warning is logged and user is told to kill session manually.
13. **External callers still unlocked** (`pane_ops.py:heal_registry`, `pane_ops.py:rebalance`, `pane_layout.py` various, `session.py` mobile/rebalance, `pr.py:1209-1212`): These still do bare `load_registry`/`save_registry` and could race. Out of scope for this PR but noted as a known gap.

## Pass/Fail Criteria

**Pass**:
- All 33 tests in `tests/test_pane_registry.py` pass, including the 7 new `TestLockedReadModifyWrite` tests and 3 updated `TestReconcileRegistry` tests.
- `test_concurrent_writers_no_data_loss`: 10 threads x 20 increments = final count of 200. No data loss.
- `test_timeout_raises`: `TimeoutError` raised within ~150ms when lock is held.
- `test_lock_released_after_modifier_exception`: Subsequent lock acquisition succeeds after modifier raises.
- `register_pane`, `unregister_pane`, `_reconcile_registry` all use `locked_read_modify_write` (not bare load/save).
- `save_registry` uses atomic write (temp + fsync + rename), not bare `write_text`.
- TUI respawn fallback targets window named "main" or first window, not active window.

**Fail**:
- Any test failure in `test_pane_registry.py`.
- Data loss in concurrent writer test (final count < expected).
- Lock not released after modifier exception (subsequent call times out).
- `save_registry` still using bare `write_text` (non-atomic).
- TUI respawn fallback still using `get_window_id()`.
- Regression in existing `TestLoadRegistry`, `TestSaveRegistry`, `TestRegisterPane`, `TestUnregisterPane`, `TestFindLivePaneByRole` tests.

## Ambiguities

1. **Should `find_live_pane_by_role` use locking?**
   - Resolution: No. It's read-only. With atomic writes, readers always see consistent data. Advisory locking is only needed for read-modify-write cycles.

2. **Where does `_prepare_registry_data` belong vs inline migration?**
   - Resolution: Extracted as a module-level helper so it can be called both from `load_registry` (for unlocked reads) and from modifier closures (inside the lock). This avoids code duplication.

3. **Should `_reconcile_registry` hold the lock during tmux subprocess calls?**
   - Resolution: No. Tmux calls happen before lock acquisition. The captured state (live_ids, session_alive) is used inside the modifier closure. This avoids holding the lock during potentially slow I/O.

4. **Is there a TOCTOU between tmux state capture and locked registry modification in `_reconcile_registry`?**
   - Resolution: Acceptable. The window between tmux query and lock acquisition is small. If a pane is created after the query but before the write, it won't be in the registry yet anyway (registration is a separate call). If a pane dies in that window, the next reconcile cycle will catch it.

5. **Should the TUI respawn fallback use window index 0 or the first window returned by `list_windows`?**
   - Resolution: Uses `list_windows()[0]` which returns windows sorted by index. This is effectively window index 0 in most cases, but handles edge cases where window 0 was destroyed and renumbered.

## Mocks

### Unit tests (test_pane_registry.py)
- **`registry_dir` fixture**: Patches `pane_registry.registry_dir` to return `tmp_path`. All registry file operations go to temp directory. No real `~/.pm/pane-registry/` is touched.
- **`pm_core.tmux.get_pane_indices`**: Mocked via `@patch` in `TestReconcileRegistry`. Returns scripted list of `(pane_id, index)` tuples representing live tmux panes.
- **`pm_core.tmux.session_exists`**: Mocked via `@patch` in `test_skips_when_no_live_panes_and_session_gone`. Returns `False` to simulate a dead session.
- **`subprocess.run` and `pm_core.tmux._tmux_cmd`**: Mocked in `TestKillAndUnregister` to avoid real tmux calls.
- **Unmocked**: `locked_read_modify_write`, `_prepare_registry_data`, `load_registry`, `save_registry`, `register_pane`, `unregister_pane` all operate on real files in `tmp_path`. `fcntl.flock` operates on real file descriptors. `threading` uses real OS threads.

### Manual/integration testing (TUI respawn fallback)
- **`tmux_mod.find_window_by_name`**: Real tmux call. For manual testing, requires a live tmux session with a window named "main".
- **`tmux_mod.list_windows`**: Real tmux call. Returns actual window list.
- No mocks needed for manual testing — the TUI instruction sets up a real tmux session.
