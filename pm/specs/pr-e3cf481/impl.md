# Implementation Spec: File-locked read-modify-write helper for pane registry

## Requirements

### R1: Generic `locked_read_modify_write` helper
Add a `locked_read_modify_write(path, modifier_fn, *, timeout)` function to `pm_core/pane_registry.py` that:
- Acquires an exclusive `fcntl.flock` on a sidecar lock file (`{path}.lock`) before reading
- Reads the JSON file at `path` (returning `None` to `modifier_fn` if missing or corrupt)
- Calls `modifier_fn(data)` — if it returns a `dict`, writes atomically (temp + fsync + rename); if `None`, skips the write
- Returns whatever `modifier_fn` returns
- Uses `LOCK_NB` with a retry loop to implement a configurable timeout (default 5s); raises `TimeoutError` on failure
- Releases the lock (via `finally` block closing the fd) after write completes

### R2: Atomic `save_registry`
Convert `save_registry` (`pm_core/pane_registry.py:78-80`) from bare `path.write_text()` to the atomic temp-file + `os.fsync` + `os.rename` pattern already used by `store.py:save` (lines 136-142). This ensures unlocked readers (e.g., `find_live_pane_by_role`, external callers in `pane_ops.py`) never see a truncated file. The `locked_read_modify_write` helper also uses this same atomic write internally.

### R3: Convert mutating functions to use locked helper
Replace the bare `load_registry` → modify → `save_registry` sequences in these functions with calls to `locked_read_modify_write`:

| Function | File:Line | Current pattern |
|---|---|---|
| `register_pane` | `pane_registry.py:83-97` | `load_registry` → append pane → `save_registry` |
| `unregister_pane` | `pane_registry.py:100-113` | `load_registry` → filter panes → `save_registry` |
| `_reconcile_registry` | `pane_registry.py:165-215` | `load_registry` → filter dead → conditional `save_registry` |

`kill_and_unregister` (line 116-120) delegates to `unregister_pane`, so it inherits locking automatically — no change needed.

### R4: Tests for locking helper
Add tests in `tests/test_pane_registry.py`:
- **Concurrent writers**: Multiple threads calling `locked_read_modify_write` simultaneously; verify no data loss (all writes are reflected in final state)
- **Timeout behavior**: One thread holds the lock; a second thread attempts to acquire with a short timeout; verify `TimeoutError` is raised
- **Modifier returning None**: Verify the file is not written when modifier returns `None`
- **Missing/corrupt file**: Verify modifier receives `None` for missing or corrupt JSON files

## Implicit Requirements

1. **Format migration inside the lock**: `load_registry` performs old-format migration (flat → multi-window, line 66-73). The modifier functions inside `locked_read_modify_write` must apply this same migration logic so the correct format is always written. Extract migration into a private `_migrate_registry_format(raw_data, session)` helper.

2. **Tmux calls outside the lock**: `_reconcile_registry` calls `tmux_mod.get_pane_indices` and `tmux_mod.session_exists` (subprocess calls). These must be called **before** acquiring the lock to avoid holding the lock during I/O. The results are captured in the closure.

3. **Backward-compatible function signatures**: `register_pane`, `unregister_pane`, `_reconcile_registry`, `kill_and_unregister` keep their existing signatures — callers in `pane_ops.py`, `session.py`, `pane_layout.py`, etc. must not need changes.

4. **Lock file cleanup**: Lock files are small (empty) and harmless if left behind. No active cleanup needed — they live in `~/.pm/pane-registry/` alongside the data files.

5. **External callers remain unlocked for now**: `pane_ops.py:heal_registry`, `pane_ops.py:rebalance`, `session.py` mobile/rebalance commands also do bare load→modify→save. These are out of scope for this PR but should be migrated later. The `locked_read_modify_write` function is public so they can adopt it.

## Ambiguities

### A1: Where to place the helper
**Options**: (a) In `pane_registry.py`, (b) In a new `file_utils.py` module
**Resolution**: Place in `pane_registry.py`. It's the only consumer right now. The function is public so it can be imported by other modules or moved later if needed.

### A2: Lock file location
**Options**: (a) `{path}.lock` sidecar file, (b) Lock the data file directly
**Resolution**: Use `{path}.lock` sidecar. We can't lock the data file itself because atomic write replaces it via `rename()`, which would invalidate the lock. The sidecar approach is standard for this pattern.

### A3: Timeout default
**Options**: (a) 2 seconds (per plan-003.md), (b) 5 seconds, (c) No timeout (blocking)
**Resolution**: Default to 5 seconds. Registry operations are very fast (<1ms) so 5s is generous enough to handle transient contention without being long enough to hang. Callers can override. Retry interval: 50ms.

### A4: Should `find_live_pane_by_role` use locking?
**Resolution**: No. It's read-only. With atomic writes (R2), readers always see a complete, consistent file. Advisory locking is only needed for the read-modify-write cycle.

### A5: Return value of `locked_read_modify_write`
**Resolution**: Return whatever `modifier_fn` returns. This allows `_reconcile_registry` to use a closure to capture side outputs (removed IDs) while returning the modified data (or `None` to skip write).

### A6: How `_reconcile_registry` signals "no changes"
**Resolution**: The modifier returns `None` to skip the write (same as the current `if removed:` guard). The outer function returns the `removed` list captured via closure.

## Edge Cases

### E1: Concurrent `register_pane` + `unregister_pane`
With locking, these serialize correctly. Without locking (current code), if `register_pane` reads, then `unregister_pane` reads, then both write, one set of changes is lost. This is the primary bug being fixed.

### E2: Registry file deleted while lock is held
If another process deletes the registry file between lock acquisition and read, `modifier_fn` receives `None` (file missing). The modifier should construct a fresh default and proceed. This matches the existing `load_registry` behavior.

### E3: Process dies while holding lock
`fcntl.flock` locks are automatically released when the file descriptor is closed (including process death). The lock file remains but is immediately available for the next caller.

### E4: `heal_registry` and `rebalance` (external callers)
These are not migrated in this PR. They could still race with the now-locked functions. However, the atomic write (R2) ensures they at least read consistent data. Full migration is deferred to a follow-up.

### E5: NFS or networked filesystems
`fcntl.flock` is advisory and may not work on NFS. This is acceptable — `~/.pm/` is expected to be on a local filesystem.
