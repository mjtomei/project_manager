# QA Spec: Convert all pane registry callers to locked_read_modify_write

## Requirements

### Functional Requirements

1. **All 10 unlocked call sites converted** — Every call site listed in the PR description (pane_layout.py: `register_and_rebalance`, `check_user_modified`, `_respawn_tui`, `handle_pane_opened`; cli/session.py: session creation, mobile toggle, `rebalance_cmd`; cli/pr.py: PR merge cleanup; tui/pane_ops.py: `heal_registry`, `rebalance` wrapper) must use `locked_read_modify_write` instead of bare `load_registry` + `save_registry`.

2. **`save_registry` privatized** — Renamed to `_save_registry` (underscore prefix). Removed from pane_layout.py re-exports. No production code calls the old public `save_registry`. Tests that called it now use `_save_registry` directly.

3. **`locked_read_modify_write` and `_prepare_registry_data` exported** — `pane_layout.py` re-exports these from `pane_registry` for backward-compat access by other modules.

4. **`load_registry` remains public** — Read-only callers (`find_live_pane_by_role`, `rebalance()`, `handle_pane_exited`, `cli/helpers.py`) continue to use `load_registry` for read-only access without locking.

5. **Modifier functions use `_prepare_registry_data`** — Every modifier closure passed to `locked_read_modify_write` calls `_prepare_registry_data(raw, session)` to handle None/corrupt/old-format input.

6. **Conditional modifiers return `None` to skip writes** — `handle_pane_opened` (pane already known) and `heal_registry` (no changes found) return `None` from modifier to skip the atomic write.

7. **Tmux subprocess calls stay outside the lock** — `check_user_modified` queries geometries before locking; `heal_registry` queries all tmux state before locking; `_respawn_tui` creates tmux panes before locking. No modifier closure calls tmux subprocesses.

8. **Existing unit tests pass** — All tests in `test_pane_registry.py`, `test_pane_layout.py`, `test_companion_pane.py`, and `test_qa_loop.py` pass with updated mocks (mocking `locked_read_modify_write` instead of `save_registry`).

### Behavioral Requirements

9. **Registry mutations are serialized** — Under concurrent writes (e.g., 20+ panes spawning simultaneously), no registry mutations are silently lost to stale-load overwrites.

10. **Session creation resets registry atomically** — `_session_start` uses `locked_read_modify_write` with a modifier that ignores old data, preventing races with concurrent writers.

11. **Mobile toggle resets all windows atomically** — `session_mobile` modifier iterates all windows to set `user_modified=False` in a single locked operation.

12. **heal_registry is best-effort** — Queries tmux state outside lock, applies healing inside lock. Small window for state drift between query and lock acquisition is acceptable.

## Setup

### For unit tests (automated)
- Run `pytest tests/test_pane_registry.py tests/test_pane_layout.py tests/test_companion_pane.py tests/test_qa_loop.py -x`
- Uses the existing `mock_registry` / `registry_dir` fixtures that create temp dirs for registry files

### For integration / manual TUI tests
- Use the `tui-manual-test.md` instruction: install pm in venv, create throwaway project, start session
- Verify pane operations (open, close, rebalance, heal) work correctly via tmux in the test session
- Inspect registry file on disk after operations to verify locking correctness

## Edge Cases

1. **Concurrent pane registration** — Multiple `register_pane` + `_reset_user_modified` sequences racing. The two-step pattern (register under lock, then reset user_modified under a separate lock) means another caller could set `user_modified=True` between the two steps. This is acceptable per the impl spec.

2. **heal_registry with stale tmux snapshot** — Between the tmux query and lock acquisition, a pane could die or spawn. Acceptable because heal runs once at TUI startup and the next lifecycle event corrects any discrepancy.

3. **check_user_modified geometry drift** — Tmux geometry queried outside lock, write inside lock. Layout could change between query and write. Worst case: sets `user_modified` unnecessarily, preventing one auto-rebalance.

4. **_respawn_tui mixed operations** — Creates tmux panes (split_pane/create_window) then registers under lock. If registration fails after tmux pane creation, the pane exists in tmux but not in registry. Next heal_registry or lifecycle event would catch this.

5. **Modifier exception** — If a modifier throws inside `locked_read_modify_write`, the lock is released (finally block) and no write occurs. The registry is unchanged.

6. **Missing/corrupt registry file** — `locked_read_modify_write` passes `None` to modifier; `_prepare_registry_data` constructs a default empty registry.

7. **Lock timeout** — If the lock cannot be acquired within 5s (default), `TimeoutError` is raised. Callers must handle or propagate this.

8. **handle_pane_opened with known pane** — Modifier returns `None`, write is skipped. No unnecessary I/O for already-known panes.

## Pass/Fail Criteria

### Pass
- All 127+ existing unit tests pass (`pytest` exit code 0)
- No production code references public `save_registry` (only `_save_registry`)
- Every write-path call site listed in the PR uses `locked_read_modify_write`
- `pane_layout.py` re-exports `locked_read_modify_write` and `_prepare_registry_data` but NOT `save_registry`
- TUI session starts, panes can be opened/closed, rebalance works, heal_registry runs without errors
- Registry file on disk reflects correct state after concurrent operations

### Fail
- Any unit test failure
- Any production code calling public `save_registry`
- Any write-path call site doing bare `load_registry` + `save_registry` instead of `locked_read_modify_write`
- Modifier closures not calling `_prepare_registry_data`
- Tmux subprocess calls inside a lock (violating IR3)
- Registry data loss under concurrent operations

## Ambiguities

1. **Should read-only callers of `load_registry` be tested for lock safety?**
   Resolution: No. Read-only callers (`find_live_pane_by_role`, `rebalance()`, `handle_pane_exited`) are explicitly safe because `locked_read_modify_write` uses atomic writes (temp+fsync+rename). Readers never see partial data. Testing would require complex multi-process setups for minimal benefit.

2. **Should `_save_registry` (now private) be tested directly?**
   Resolution: Yes, but only in unit tests that need to set up test fixtures (pre-populate a registry file). The tests already do this — they just import `_save_registry` instead of `save_registry`.

3. **Should we test lock contention / timeout behavior?**
   Resolution: The `locked_read_modify_write` function was introduced in the previous PR (pr-e3cf481) and already has dedicated concurrency tests in `test_pane_registry.py`. This PR's QA focuses on verifying that callers correctly use the locking API, not re-testing the lock primitive itself.

4. **How to verify "no stale overwrites" without full concurrency stress tests?**
   Resolution: Code inspection (grep for bare `save_registry` / `load_registry`+save patterns) combined with unit tests that verify modifier functions are called correctly. Full concurrency stress testing is deferred to the TUI manual test scenario.

## Mocks

### For unit tests (existing test infrastructure)
- **tmux subprocess calls**: Already mocked via `@patch("pm_core.tmux.*")` in existing tests. Tests mock `get_pane_indices`, `get_pane_geometries`, `split_pane`, `session_exists`, etc.
- **Registry file I/O**: Uses `mock_registry` pytest fixture that redirects `registry_dir()` to a `tmp_path` subdirectory. Real file I/O occurs but in a temp directory.
- **`locked_read_modify_write`**: In `test_qa_loop.py`, mocked entirely since QA loop tests don't need real registry locking. In `test_pane_registry.py` and `test_pane_layout.py`, uses real implementation against temp files.

### For TUI manual tests
- **Unmocked**: Everything runs against a real tmux session, real filesystem, real locks. This is the integration test path.
- The test project is throwaway (created in the workdir), so no risk to real data.
