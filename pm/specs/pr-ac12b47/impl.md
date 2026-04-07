# Implementation Spec: Session Cleanup for Stale Containers and Push Proxies

## Requirements

### R1 — Stale Container Cleanup Function
Add `cleanup_stale_containers(session_name, session_tag)` to `pm_core/container.py`:
1. List all containers matching `pm-{session_tag}-*` via `docker ps -a --filter name=pm-{session_tag}-`.
2. For each container, check if it has any processes running beyond the
   `sleep infinity` entry point using `docker top`.  A container with only
   `sleep` is idle (no `docker exec` session attached, no claude process
   running).  A container with additional processes is still active and
   must be kept.
3. If the container is idle, call `remove_container(cname)` (which already
   calls `stop_push_proxy(cname)`).
4. Return the count of containers removed.

This approach replaces the original name-based tmux window matching
(container name → PR display ID → window name lookup) with a direct
container-state check via `docker top`.  Benefits:
- No dependency on the store or PR display ID mapping
- Works for any container label format (impl, review, qa, unknown)
- Correctly preserves containers where claude is still running even if
  the terminal is detached (e.g., SIGHUP race during tmux crash)
- Eliminates Ambiguities A1 and A2 entirely

### R2 — Stale Push Proxy Cleanup Function
Add `cleanup_stale_proxy_dirs(session_tag)` to `pm_core/push_proxy.py`:
1. Scan `/tmp/pm-push-proxy-{session_tag}-*` directories.
2. For each directory, check if `push.sock` is alive using the existing `proxy_is_alive(sock_path)`.
3. If the socket is dead (or absent), call `_kill_proxy_socket(sock_path)` to remove it.
4. Return count of proxy directories cleaned.

Note: The existing `stop_session_proxies(session_tag)` kills *all* session proxies indiscriminately. The new function is a surgical version that only removes dead ones.

### R2a — Push Proxy Restart for Live Containers
Add `restart_dead_proxies(session_name, session_tag)` to `pm_core/push_proxy.py`:

When a proxy dies but its container is still alive and needs it (host OOM,
proxy crash, manual socket removal), `git push/fetch/pull` inside the
container fails with "cannot connect".  This function detects and restarts
dead proxies for live containers.

1. List all running containers matching `pm-{session_tag}-*`.
2. For each container, check if it has a push proxy socket mounted
   (inspect the container's bind mounts for `/run/pm-push-proxy`).
3. If the container has a proxy mount but the socket is dead
   (`proxy_is_alive` returns False), derive the allowed branch and
   workdir from the container's configuration (via `docker inspect`
   — the allowed branch is in the proxy socket path convention, the
   workdir is the bind mount source for `/workspace`).
4. Restart the proxy via `start_push_proxy()`.
5. Return the count of proxies restarted.

Integration points:
- Called in `cleanup_stale_proxy_dirs` after removing dead proxy dirs,
  to restart any that are needed by live containers.
- Called during TUI startup (R3) alongside the other cleanup functions.
- Available implicitly via `pm session cleanup` (R4).

Key constraint: After a crash the in-memory proxy registry
(`_active_proxies`, `_proxy_refs`) is empty.  All information must come
from Docker inspect and the filesystem (deterministic socket paths).

### R3 — TUI Startup Integration
In `pm_core/tui/app.py`, `_deferred_startup_sync()`, add a call to cleanup helpers after `pane_ops.heal_registry(self._session_name)`:
```python
try:
    if self._session_name:
        session_tag = self._session_name.removeprefix("pm-")
        from pm_core.container import cleanup_stale_containers
        from pm_core.push_proxy import cleanup_stale_proxy_dirs, restart_dead_proxies
        cleanup_stale_containers(self._session_name, session_tag)
        cleanup_stale_proxy_dirs(session_tag)
        restart_dead_proxies(self._session_name, session_tag)
except Exception:
    _log.debug("Stale cleanup on startup failed", exc_info=True)
```

### R4 — CLI Command: `pm session cleanup`
Add a `cleanup` subcommand to the `session` group in `pm_core/cli/session.py`:
- Derives session name (and thus session tag) the same way other session subcommands do: via `_get_session_name_for_cwd()`.
- Does **not** require an active tmux session — only Docker and the filesystem (see EC5).
- Calls `cleanup_stale_containers`, `cleanup_stale_proxy_dirs`, and `restart_dead_proxies`.
- Prints a summary of what was removed/restarted.

### R5 — tmux Session-Closed Hook
In `pm_core/cli/session.py`, `_register_tmux_bindings(session_name)`, register a global hook:
```python
subprocess.run(tmux_mod._tmux_cmd(
    "set-hook", "-g", "session-closed",
    "run-shell 'pm _session-closed \"#{hook_session_name}\"'"
), check=False)
```
Add a hidden `_session-closed` CLI command that:
1. Checks if the base session (stripping `~N` suffix) starts with `pm-`
2. Checks if the base session still exists (grouped session closing, not base)
3. If the base session is gone, calls `cleanup_session_containers(session_tag)`
   and `stop_session_proxies(session_tag)` for full teardown

Uses `#{hook_session_name}` (not `#{session_name}`) so tmux resolves
the name of the session that triggered the hook.

---

## Implicit Requirements

### IR1 — Container Mode Guard
All cleanup functions must gracefully handle the case where Docker is not installed or container mode is disabled. Wrap `_run_docker` calls with `check=False` (already done in existing cleanup functions). Do not raise errors — log warnings.

### IR2 — Idempotency
Cleanup must be safe to run multiple times. `remove_container` already uses `docker rm -f` (no-op if container absent). `_kill_proxy_socket` uses `try/except FileNotFoundError`.

### IR3 — Session May Not Exist
On TUI startup, `self._session_name` may be `None` or the session may not yet exist in tmux. Guard with `if self._session_name`.

### IR4 — Proxy In-Memory State
`stop_push_proxy(container_name)` checks the in-memory `_container_to_proxy_key` dict. After a crash/restart, this dict is empty. The new `cleanup_stale_session_proxies` must work from filesystem state (`/tmp/pm-push-proxy-*`) rather than in-memory state.

### IR5 — Hook Fires for All Sessions
The `session-closed` hook is global and fires for every tmux session, not just pm sessions. The cleanup command should be a no-op (exit cleanly) when called with a non-pm session tag (no containers matching the prefix will be found).

### IR6 — Session Kill Already Handles Full Cleanup
`pm session kill` already calls `cleanup_session_containers` + `stop_session_proxies`. The new hook must not double-clean or error. Since both functions are idempotent, this is safe.

---

## Ambiguities

### A1 — Container Label → Window Name Mapping (RESOLVED — eliminated)

The `docker top` approach (R1) eliminates this ambiguity entirely.
Container staleness is determined by process state, not by mapping
container names back to tmux window names.  No store lookup, display ID
resolution, or label-format parsing is needed.

### A2 — Unknown Container Label Formats (RESOLVED — eliminated)

Also eliminated by the `docker top` approach.  All containers matching
the session prefix are checked uniformly via process state, regardless
of label format.

### A3 — Session-Closed Hook: Window Check Not Possible (RESOLVED)

**Problem:** When the `session-closed` hook fires, the tmux session is
already gone, so we cannot check container process state or windows.

**Resolution:** The hook calls a separate internal command
`pm _session-closed "#{hook_session_name}"` which does full teardown
(removes all containers + kills all proxies for the session tag) rather
than selective stale-only cleanup.  This is correct because the session
is definitively gone — all its containers are orphaned.  Uses
`#{hook_session_name}` (not `#{session_name}`) so tmux resolves the
name of the just-closed session, not the current session.

### A4 — Push Proxy Directories: Long Names vs Hashed Names

**Problem:** `_shared_sock_dir_path` may hash a long `{session_tag}-{pr_id}` to a short hex path, and creates a symlink from the long name to the short path. Cleanup needs to find both.

**Resolution:** `cleanup_stale_proxy_dirs` globs `f"/tmp/pm-push-proxy-{session_tag}-*"` to catch both real directories (short names) and symlinks (long names). `proxy_is_alive` works regardless of whether the path is a symlink. `_kill_proxy_socket` resolves symlinks internally (uses `os.path.realpath`) so both the symlink and the underlying hashed directory are cleaned up.

---

## Edge Cases

### EC1 — Concurrent Cleanup and Container Start
If a new container is being created while cleanup runs, the container may
be listed by Docker but have no exec session yet.  With the `docker top`
approach, a freshly created container running `sleep infinity` setup
script would show processes (the setup script itself), so it would be
kept alive.  Once setup completes and the container is idle (only `sleep`),
it could be classified as stale before the `docker exec` attaches.
Mitigation: cleanup only runs at startup (before PR work starts) or at
session close, not during normal operation.

### EC2 — Shared Proxies
A shared proxy (keyed `{session_tag}\0{pr_id}`) may serve multiple QA scenario containers. If some containers are stale (idle) but others are live:
- `remove_container(cname)` calls `stop_push_proxy(cname)`, which only stops the proxy when the last container referencing it is removed.
- However, after a crash the in-memory `_proxy_refs` is empty. `stop_push_proxy` will try to derive the socket path from the key and kill it unconditionally.
- This means the shared proxy gets killed even if other containers still need it.

**Resolution:** After a crash, `stop_push_proxy` is a no-op when the
in-memory dict has no entry for the container name, so the proxy is not
killed by `remove_container`.  Proxy cleanup is then handled separately
by `cleanup_stale_proxy_dirs` scanning `/tmp` for dead sockets.  If the
proxy was killed but live containers still need it,
`restart_dead_proxies` (R2a) will restart it.

### EC6 — Proxy Restart: Deriving Branch and Workdir
`restart_dead_proxies` needs the allowed branch and workdir to call
`start_push_proxy`.  These are derived from Docker inspect:
- Workdir: the bind mount source for `/workspace`
- Allowed branch: encoded in the proxy socket path convention or
  derivable from the container name (impl/review containers map to a
  single branch; QA containers share a proxy keyed by PR ID).
If either cannot be determined, skip the restart (log a warning).
The container's `git push` will fail, but a subsequent `pm session cleanup`
or TUI restart will retry.

### EC3 — Non-Container Environments
If container mode is disabled, `docker ps` will return no results (or fail). Cleanup runs but finds nothing to remove. Already handled by `check=False` in `_run_docker`.

### EC4 — tmux Hook Already Registered
`_register_tmux_bindings` is called on TUI startup and reattach. The `session-closed` hook gets re-registered each time, which is safe since it's idempotent (same command string).

### EC5 — `pm session cleanup` When Not in tmux
The CLI command works outside a tmux session (e.g., `pm session cleanup` from a plain terminal) since it only needs Docker and the filesystem, not an active tmux session. The tmux `session_exists` guard was removed so the command proceeds regardless of tmux state.
