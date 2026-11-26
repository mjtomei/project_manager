# QA Spec: Session Cleanup for Stale Containers and Push Proxies (pr-ac12b47)

## Requirements

### R1 — Stale Container Cleanup (`cleanup_stale_containers`)
- Lists all containers matching `pm-{session_tag}-*` via `docker ps -a --filter name=...`
- For each container, uses `docker top -o comm` to check if only idle processes (`sleep`, `bash`) are running
- Removes idle containers via `remove_container()` (which also stops their push proxy)
- Returns count of containers removed
- Containers with any process beyond `sleep`/`bash` (e.g. `claude`, `python3`) are considered active and kept

### R2 — Stale Proxy Directory Cleanup (`cleanup_stale_proxy_dirs`)
- Scans `/tmp/pm-push-proxy-{session_tag}-*` (both real dirs and symlinks)
- For each directory, checks `push.sock` liveness via `proxy_is_alive()`
- Removes dead entries via `_kill_proxy_socket()` which handles symlinks (resolves to real dir)
- Returns count of proxy directories cleaned

### R2a — Dead Proxy Restart (`restart_dead_proxies`)
- Lists running containers matching `pm-{session_tag}-*`
- For each, inspects bind mounts to find proxy socket dir (`/run/pm-push-proxy`) and workdir (`/workspace`)
- If proxy socket is dead, derives branch from `git rev-parse` in workdir and pr_id from container label
- Restarts proxy via `start_push_proxy()`
- Skips containers without proxy mount, with live proxies, or where branch cannot be determined
- Returns count of proxies restarted

### R3 — TUI Startup Integration
- In `_deferred_startup_sync()`, after `heal_registry()`, calls:
  - `cleanup_stale_containers(session_name, session_tag)`
  - `cleanup_stale_proxy_dirs(session_tag)`
  - `restart_dead_proxies(session_name, session_tag)`
- Wrapped in try/except so startup is not blocked by cleanup failures
- Only runs if `self._session_name` is set and session_tag is non-empty

### R4 — CLI Command: `pm session cleanup`
- Derives session name via `_get_session_name_for_cwd()`
- Does NOT require active tmux session (EC5) -- only needs Docker and filesystem
- Calls all three cleanup functions (R1, R2, R2a)
- Prints human-readable summary: counts of containers removed, proxies cleaned, proxies restarted
- Prints "No stale containers or proxies found." when nothing to clean

### R5 — tmux Session-Closed Hook (`pm _session-closed`)
- Registered as global tmux hook: `set-hook -g session-closed "run-shell 'pm _session-closed \"#{hook_session_name}\"'"`
- Hidden CLI command receives session name argument
- Strips `~N` suffix for grouped sessions, checks base starts with `pm-`
- If base session still exists (grouped session closing), does nothing
- If base session is gone, does FULL teardown: `cleanup_session_containers()` + `stop_session_proxies()` + `cleanup_stale_proxy_dirs()`
- No-ops silently for non-pm sessions (IR5)

### Additional Changes
- `remove_container()` now polls with `docker inspect` until container is fully gone (up to 10s)
- `build_exec_cmd()` wraps cleanup in `bash -c 'trap ... EXIT; ...'` instead of `;`-chaining (survives SIGHUP)
- Container setup timeout increased from ~5s to 30s with explicit error on timeout
- Git wrapper installed to `~/.local/bin/git` instead of `/usr/local/bin/git` (no root needed)
- User creation commands tolerant of existing users (`|| true`)

## Setup

### For unit/CLI testing (no Docker required)
- Python venv with `pip install -e .` from project_manager clone
- All Docker, tmux, and filesystem interactions can be mocked via `unittest.mock.patch`
- Existing test suite runs via `pytest tests/`

### For integration testing (Docker required)
- Docker daemon running and accessible
- Create idle test containers: `docker run -d --name pm-test-impl-pr-1 ubuntu sleep infinity`
- Create proxy socket directories in `/tmp/pm-push-proxy-test-*`
- tmux available for hook registration tests

## Edge Cases

### EC1 — Concurrent Cleanup and Container Start
A freshly created container still running setup script shows extra processes, so it's not classified as idle. But once setup completes and only `sleep` remains, a race is possible before `docker exec` attaches. Mitigation: cleanup only runs at startup or session close, not during normal operation.

### EC2 — Shared Proxies After Crash
After crash, in-memory `_proxy_refs` is empty. `stop_push_proxy` via `remove_container` is a no-op for unknown containers. Proxy cleanup is handled by `cleanup_stale_proxy_dirs` scanning filesystem. `restart_dead_proxies` restarts proxies killed during cleanup that live containers still need.

### EC3 — Non-Container Environments
When Docker is not installed or container mode disabled, `docker ps` returns non-zero. All cleanup functions return 0 gracefully (check=False).

### EC4 — tmux Hook Already Registered
Re-registering the session-closed hook is idempotent (same command string).

### EC5 — `pm session cleanup` Outside tmux
CLI works from plain terminal. Does not call `tmux_mod.session_exists`. Only needs Docker and filesystem.

### EC6 — Proxy Restart Branch Derivation Failure
If `git rev-parse` fails in the workdir (detached HEAD, missing repo), proxy restart is skipped with a warning. Container's `git push` fails but subsequent cleanup retry will try again.

### EC7 — Grouped Sessions (`pm-tag~2`)
`_session-closed` strips `~N` suffix, checks if base `pm-tag` still exists. If yes, no cleanup (just a grouped session detaching). Only cleans up when the base session is fully gone.

### EC8 — Empty Session Tag
`pm _session-closed "pm-"` yields empty session_tag and returns immediately (no cleanup attempted).

### EC9 — docker top Output Variations
The `_container_is_idle` function handles: header-only output (idle), only `sleep` (idle), `sleep`+`bash` (idle), any other process name (not idle), docker failure (treated as idle for cleanup).

### EC10 — Symlinked Proxy Dirs (Hashed Names)
Long container names produce hashed proxy dir names with symlinks. `cleanup_stale_proxy_dirs` globs both, `_kill_proxy_socket` resolves symlinks via `os.path.realpath`, removing both symlink and underlying dir.

### EC11 — remove_container Race (Concurrent Removal)
If another `docker rm -f` is in flight (e.g. EXIT trap from previous session), `remove_container` polls until the container is fully gone (up to 10s), ensuring the caller can safely create a new container with the same name.

## Pass/Fail Criteria

### Pass
- `pm session cleanup` correctly identifies and removes idle containers (only `sleep`/`bash` running)
- `pm session cleanup` correctly identifies and removes dead proxy socket dirs
- `pm session cleanup` correctly restarts proxies for live containers with dead sockets
- `pm session cleanup` reports accurate counts in output
- `pm session cleanup` works from a plain terminal (no tmux required)
- `pm _session-closed` performs full teardown when base session is gone
- `pm _session-closed` is a no-op for grouped sessions, non-pm sessions, and empty tags
- TUI startup calls cleanup without blocking on failures
- Active containers (with `claude` or other processes) are never removed
- Live proxy sockets are never removed
- All 154 existing tests pass
- EXIT trap in `build_exec_cmd` ensures cleanup runs even on SIGHUP

### Fail
- Active container removed during cleanup (data loss)
- Live proxy killed during cleanup (breaks `git push` in running container)
- `pm session cleanup` crashes when Docker is unavailable
- `pm _session-closed` runs cleanup for non-pm sessions
- `pm _session-closed` runs cleanup for grouped session when base still exists
- TUI startup blocked/crashed by cleanup failure
- `pm session cleanup` requires tmux session to be active (EC5 regression)
- `remove_container` returns before container is fully gone (race with re-creation)

## Ambiguities

### A1 — "Stale" Definition: Process-Based vs Window-Based (Resolved)
The original PR description mentioned checking if "the tmux window it was launched from no longer exists." The implementation uses `docker top` to check process state instead. This is correct per the impl spec -- process-based detection is more reliable and doesn't require store lookups or tmux window name mapping. QA tests the implemented behavior (`docker top`), not the original description.

### A2 — Session-Closed Hook: Full Teardown vs Selective Cleanup (Resolved)
The hook uses `cleanup_session_containers()` (removes ALL session containers) and `stop_session_proxies()` (kills ALL session proxies), not the stale-only variants. This is correct because when the session is gone, all containers are orphaned. QA verifies the hook calls the full-teardown functions.

### A3 — `pm session cleanup` vs `pm _session-closed` Cleanup Scope (Resolved)
`pm session cleanup` (R4) uses selective cleanup: only removes idle containers, only removes dead proxy dirs, restarts needed proxies. `pm _session-closed` (R5) uses full teardown: removes all session containers, kills all session proxies. QA verifies both paths call the correct functions.

### A4 — QA Container PR ID Extraction (Resolved)
`restart_dead_proxies` extracts `pr_id` from QA container names (`qa-{pr_id}-{loop_id}-s{N}`) by parsing the first 10 characters after `qa-` (format: `pr-XXXXXXX`). This is tested explicitly in `test_extracts_qa_pr_id`.

## Mocks

### Docker Operations
**Contract**: All Docker CLI interactions go through `pm_core.container._run_docker()`.
**What to mock**: `pm_core.container._run_docker` — returns `MagicMock(returncode=N, stdout="...")`.
**Scripted responses**:
- `docker ps -a --filter name=pm-{tag}-* --format {{.Names}}` → newline-separated container names, or empty string
- `docker top <name> -o comm` → "COMMAND\nsleep\n" (idle) or "COMMAND\nsleep\nbash\nclaude\n" (active)
- `docker inspect <name>` → returncode=0 (exists) or returncode=1 (gone)
- `docker inspect -f {{range .Mounts}}...{{end}} <name>` → "source:dest\n" mount lines
- `docker rm -f <name>` → returncode=0
**Unmocked**: Actual Docker daemon operations for integration-level TUI manual tests.

### tmux Operations
**Contract**: tmux interactions go through `pm_core.tmux` module functions.
**What to mock**: `pm_core.tmux.session_exists(session_name)` → True/False.
**Scripted responses**: True when base session still alive (grouped session test), False when gone.
**Unmocked**: Hook registration in TUI manual tests.

### Filesystem / Proxy Sockets
**Contract**: Proxy socket dirs at `/tmp/pm-push-proxy-{session_tag}-*`.
**What to mock**: `tempfile.gettempdir()` → `str(tmp_path)` for isolated testing.
**Scripted responses**: Create dirs with/without `push.sock`, with/without live socket servers.
**Unmocked**: Real socket operations in `proxy_is_alive()` tests (using `socket.AF_UNIX`).

### Git Operations
**Contract**: `subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=workdir)`.
**What to mock**: `subprocess.run` — returns `MagicMock(returncode=N, stdout="branch-name\n")`.
**Scripted responses**: returncode=0 with branch name (success) or returncode=1 (failure).
**Unmocked**: None for cleanup scenarios.

### Session Name Resolution
**Contract**: `pm_core.cli.session._get_session_name_for_cwd()` derives session from CWD.
**What to mock**: `pm_core.cli.session._get_session_name_for_cwd` → `"pm-repo-abc123"`.
**Unmocked**: TUI manual tests derive session name from actual project directory.
