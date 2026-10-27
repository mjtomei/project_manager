# QA Spec: Add file locking to project.yaml read-modify-write operations (pr-f38005f)

## Requirements

### R1: `locked_update(root, fn)` — atomic read-modify-write
`store.locked_update()` acquires an exclusive `fcntl.flock` advisory lock on
`project.yaml.lock`, loads fresh state from disk, calls `fn(data)` to apply
in-place mutations, saves atomically (temp file + rename), and releases the lock.
Returns the updated data dict.

### R2: Lock timeout with clear error
If the lock cannot be acquired within `LOCK_TIMEOUT_SECONDS` (2s default, configurable
via `timeout` parameter), `StoreLockTimeout` is raised with a message including the
lock file path and remediation advice.

### R3: Lock never held across network calls
Operations that call GitHub API, git remote operations, or other external services
must do the external call first, then acquire the lock and apply results. This is
enforced by design: callers capture network results into closures, then call
`locked_update`.

### R4: All CLI read-modify-write call sites migrated
Every `save_and_push()` and bare `store.save()` call in `pm_core/cli/` has been
replaced with `locked_update()`. The `save_and_push` helper is removed entirely.
Affected modules: `cli/__init__.py`, `cli/cluster.py`, `cli/helpers.py`,
`cli/model.py`, `cli/plan.py`, `cli/pr.py`.

### R5: All TUI read-modify-write call sites migrated
TUI modules that do `store.load()` + mutation + `store.save()` are now using
`locked_update()`. Affected: `tui/pr_view.py`, `tui/qa_loop_ui.py`,
`tui/review_loop_ui.py`, `tui/sync.py`, `tui/watcher_ui.py`.

### R6: Background sync modules migrated
`pr_sync.py` sync functions (`sync_prs`, `sync_from_github`) now use
`locked_update` for persisting status changes and timestamps.

### R7: Spec generation migrated
`spec_gen.py` functions (`generate_spec`, `approve_spec`, `reject_spec`) now
use `locked_update` for persisting spec paths, pending state, and descriptions.

### R8: Atomic file writes with read-only permissions
`store.save()` uses atomic write (write to temp file + `os.fsync` + rename).
After writing, the file is set to read-only (`0o444`). Before writing, if the
file exists and is read-only, permissions are temporarily elevated.

### R9: YAML header on saved files
A warning header is prepended to every saved `project.yaml` advising users to
use `pm` commands and `pm edit` instead of manual edits.

### R10: `pm edit` command
New `pm edit` CLI command opens `project.yaml` in `$EDITOR` under the advisory
lock with a 30-second timeout, validates on save, restores read-only perms.

### R11: `StoreLockTimeout` caught at CLI top level
The `main()` function in `cli/__init__.py` catches `StoreLockTimeout` globally
and prints a user-friendly error.

### R12: TUI gracefully handles lock timeouts
TUI call sites in `qa_loop_ui.py`, `review_loop_ui.py`, `sync.py`, and
`watcher_ui.py` catch `StoreLockTimeout` and log warnings instead of crashing.

### R13: Concurrent-safe duplicate checks
Call sites that add new entries (PR add, plan load, GitHub import) re-check for
duplicates inside the `fn` callback against fresh data, preventing concurrent
double-adds.

## Setup

- Python environment with `pm_core` installed (`pip install -e .`)
- For unit tests: `pytest tests/test_store_locking.py tests/test_store.py -v`
- For integration/manual tests: follow `tui-manual-test.md` — create throwaway
  project, initialize with `pm init --backend local --no-import`, exercise CLI
  commands that write project.yaml
- For concurrency tests: run multiple `pm` CLI commands in parallel against the
  same project.yaml

## Edge Cases

1. **Lock held by dead process**: Lock file exists but holding process crashed.
   `fcntl.flock` automatically releases on process death, so the next caller
   should succeed. The lock file itself is never deleted (just unlocked).

2. **Exception in mutation function**: Lock must be released; data must NOT be
   saved. The `_lock` context manager uses try/finally; `locked_update` calls
   `fn(data)` before `save(data)`, so an exception skips the save.

3. **Read-only file from previous save**: `save()` calls `chmod` to add write
   permission before writing the temp file. `locked_update` re-reads fresh state
   on every call so stale read-only state from an in-memory copy is irrelevant.

4. **Concurrent adds of same PR**: `pr_add` re-checks ID uniqueness inside
   the `fn` callback against freshly loaded data, so two concurrent `pm pr add`
   calls with the same title won't create duplicates.

5. **Network call interleaving**: `pr_start` does the GitHub `create_draft_pr`
   call before acquiring the lock, captures the result (`gh_pr_info`), then
   applies it inside `locked_update` via a closure. Same pattern for `pr_review`
   (draft->ready upgrade), `pr_sync` (merge check), `pr_import_github` (list PRs).

6. **TUI background sync race**: `do_normal_sync` runs sync in a thread pool,
   then applies merged status changes via `locked_update` on the main thread.
   If lock times out, it falls back to a bare `store.load()` reload.

7. **`pm edit` with long-running editor**: `locked_edit` uses a 30-second
   timeout (vs 2s default). While the editor is open, all other pm processes
   that try to write will timeout with `StoreLockTimeout`.

8. **YAML parse error during load**: `ProjectYamlParseError` is raised if the
   file contains invalid YAML. TUI sync catches this and skips the sync cycle.

9. **Leftover .yaml.tmp file**: If a previous save crashed after writing the
   temp file but before rename, the temp file is orphaned. The next save
   overwrites it (same path: `project.yaml.tmp`).

10. **watcher_ui.py initial project creation**: One `store.save()` call remains
    in `watcher_ui.py` for creating a brand-new project.yaml when it doesn't
    exist. This is intentional — no lock needed for file creation.

## Pass/Fail Criteria

### Pass
- All 16 tests in `test_store_locking.py` pass
- All 17 tests in `test_store.py` pass
- All pre-existing tests continue to pass (`test_cli_helpers.py`,
  `test_pr_enhancements.py`, `test_spec_gen.py`, `test_plan_parser.py`)
- No `store.save()` calls remain in `pm_core/cli/` or `pm_core/tui/` outside
  of `store.py` itself (except the one intentional creation-time call in
  `watcher_ui.py`)
- `save_and_push` helper is fully removed from `cli/helpers.py` and all imports
- CLI commands that modify project.yaml (`pm pr add`, `pm pr edit`,
  `pm pr select`, `pm plan add`, `pm model set`, etc.) produce correct state
  on disk
- Two concurrent `pm pr add` commands do not produce lost writes
- `StoreLockTimeout` produces a helpful error message at the CLI level
- `pm edit` opens the editor, holds the lock, validates on save
- Atomic write: file is never truncated/corrupt even if process is killed mid-save

### Fail
- Any test failure in `test_store_locking.py` or `test_store.py`
- Lost writes under concurrent access (PR added by one process missing from
  final state)
- Lock not released after exception (subsequent operations timeout)
- Network calls made while lock is held (check by auditing the code paths)
- `save_and_push` still called anywhere
- Direct `store.save()` in CLI/TUI code (except the intentional exception)
- `project.yaml` left writable after save
- Missing YAML header after save

## Ambiguities

### A1: Should `locked_update` save even if `fn` makes no changes?
**Resolution**: Yes. `locked_update` always calls `save()` after `fn()`. The
overhead is minimal (one YAML dump + rename), and detecting "no change" would
require deep-comparing the data dict, which is more complex than the save itself.

### A2: Should the lock file be cleaned up after use?
**Resolution**: No. The lock file (`project.yaml.lock`) is left on disk after
unlock. It's a zero-byte file and removing it would create a TOCTOU race
between "check if file exists" and "create and lock". Leaving it is the standard
`fcntl.flock` pattern.

### A3: Should TUI crash on `StoreLockTimeout` or handle gracefully?
**Resolution**: Handle gracefully. TUI operations (sync, QA note, review loop
transition) catch `StoreLockTimeout` and log a warning. The TUI continues
running. CLI operations let it propagate to the top-level handler in `main()`.

### A4: What about the PR note in the description about review_loop_ui, qa_loop_ui, and auto_start?
**Resolution**: These have been migrated. `review_loop_ui.py` and `qa_loop_ui.py`
now use `locked_update` for status transitions and note recording. The `auto_start.py`
module was checked — it uses read-only access patterns that don't require locking.

### A5: Is the one remaining `store.save()` in `watcher_ui.py` a bug?
**Resolution**: No. It creates a brand-new project.yaml when the meta workdir
doesn't have one yet. This is a creation-time initialization, not a
read-modify-write, so locking is not needed.

## Mocks

No external dependencies require mocking for this PR's core functionality.
All changes are to in-process file I/O, locking primitives, and YAML
serialization. Tests use `tmp_path` fixtures with hand-written YAML files.

For unit tests:
- **Unmocked**: `fcntl.flock`, file I/O, `multiprocessing.Process` (for concurrency tests)
- **Unmocked**: YAML parsing, file permissions, atomic rename

For CLI integration scenarios:
- **Unmocked**: `pm pr add`, `pm pr edit`, `pm plan add`, `pm model set` — these
  exercise the full locked_update path through the CLI
- **Mocked (by existing test infrastructure)**: `git_ops`, `gh_ops`,
  `find_claude`, `trigger_tui_refresh` — these are mocked by existing test
  fixtures and unrelated to locking

For TUI scenarios:
- **Not needed**: Claude API, tmux, git — the locking behavior is exercised via
  the CLI and unit tests, not via live TUI interaction
