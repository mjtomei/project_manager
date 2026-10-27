# Implementation Spec: Workdir-keyed push proxies

## Context and root cause (grounded in code)

`pm_core/push_proxy.py:start_push_proxy()` keys live shared proxies by
`(session_tag, pr_id)` only (`_shared_proxy_key`, `_shared_sock_dir_path`,
`_shared_sock_dir`).  The socket lives at
`/tmp/pm-push-proxy-{session_tag}-{pr_id}/push.sock`, and every container
for that PR bind-mounts the same *directory* at `/run/pm-push-proxy`
(`pm_core/container.py:817-818`).

Containers on one PR have **different** host workdirs:

- implementation / review / sign-off containers mount the PR workdir
  (`pm_core/cli/pr.py:1179`, `:1372`, `pm_core/signoff.py:530`);
- each QA scenario mounts its own clone
  `…/qa/…/s-{N}/repo` (`pm_core/qa_loop.py:2250`, `:2295-2303`).

The lifecycle assumes one proxy per key is enough:

- If the socket is alive, `start_push_proxy` reuses it and ignores the
  caller's `workdir` (`push_proxy.py:627-633`).
- If the socket is missing or transiently dead, it `os.unlink`s whatever
  is there and spawns a new daemon with the *new* caller's workdir
  (`push_proxy.py:635-654`).

So the second caller wins the proxy's default workdir.  The request
protocol already carries `"workdir"` per request and the proxy routes
push/fetch/pull to it (`push_proxy.py:230-246`, `:311`, `:339`, `:374`),
which papers over the routing problem for callers that send it — but the
lifecycle still lets one container replace/unlink another container's
socket and socket directory.  The PR notes record two concrete failures:

1. PR 2d0588a: a QA launch re-spawned the proxy with QA scenario
   workdirs; the impl container's pushes then ran from a QA clone.
2. S18 / pr-592e4bd: `z t` swept QA containers in the TUI process, the
   process dropped its last refs, and the shared socket **directory** was
   removed while the impl container still bind-mounted it.  Recreating the
   daemon in a recreated directory did not heal the impl container's
   mount (`git-proxy: cannot connect: [Errno 2]`).

The #249 symptom (mounted `/run/pm-push-proxy` had no usable socket) is a
different, not-established cause; this change must not claim it was the
workdir collision.  It does, however, require the same lifecycle to
include socket/mount/readiness checks and recovery.

## Requirements

### R1 — Include the workdir in the shared proxy key

`_shared_proxy_key(session_tag, pr_id, workdir_token)` must return
`"{session_tag}\0{pr_id}\0{workdir_token}"`, where `workdir_token` is a
short hash of the **realpath** of the requested workdir.  Realpath makes
symlinked/relative spellings of the same clone share one proxy; the hash
keeps the socket path short and filesystem-safe.

Consequence: impl/review/sign-off (same PR workdir) keep sharing one
proxy; each QA scenario clone gets its own proxy.  The proxy's default
workdir is therefore always correct for its own container.

### R2 — Per-workdir socket directory

`_shared_sock_dir_path(session_tag, pr_id, workdir_token)` and
`_shared_sock_dir(...)` derive the readable directory name
`{session_tag}-{pr_id}-{workdir_token}` and fall back to a hashed
`/tmp/pm-push-proxy-<sha16>` when the readable path would exceed the
107-byte Unix socket limit.  The long-name symlink continues to be
created for discoverability/cleanup.  No filesystem side effects in the
`_path` variant (existing contract).

### R3 — Refuse to replace a live proxy serving a different workdir/branch

Before spawning, `start_push_proxy` must check an existing live socket:

- Read a small sidecar `<sock_dir>/proxy.json` written by the daemon
  (`{"workdir": <realpath>, "allowed_branch": ..., "pid": ...}`).
- If the recorded workdir (realpath) or allowed branch differs from the
  request, raise a new `PushProxyConflict` error.  Do **not** unlink or
  replace a live proxy.
- If metadata is absent (older daemon), reuse the live proxy (backward
  compatible); the workdir is already encoded in the key.

The daemon itself must never steal a live socket: `PushProxy.start()`
returns without binding if `proxy_is_alive(self.socket_path)` is true,
and `PushProxy.stop()` must not unlink a socket it does not own.

### R4 — Validate each request's workdir; never silently serve another clone

In `PushProxy._handle_connection`:

- `workdir` remains optional for legacy wrappers; when absent the proxy
  uses `self.workdir` (now guaranteed to be that container's workdir).
- When present, its realpath must equal the proxy's configured
  `self.workdir` realpath, and the directory must exist.  Otherwise
  return `exit_code=1` with an explicit `git-proxy: rejected — …`
  message naming both paths.  Do not fall back to `self.workdir`.

This also closes a hole where a container could name an arbitrary host
path in the request and have the proxy run git there.

### R5 — Readiness check and explicit startup failure

`_start_proxy_subprocess` must report whether the socket became
connectable within the wait window (extend to ~5 s).  On failure,
`start_push_proxy` raises `PushProxyError` naming the socket and workdir
instead of returning a path to a dead proxy.  Container creation then
fails loudly rather than producing a container whose pushes silently
fail.

### R6 — Keep the socket directory across shared-proxy stop; clean at teardown

`stop_push_proxy` for a **shared** proxy removes the socket and metadata
but leaves the directory in place, so a container that still bind-mounts
it is never left pointing at a deleted inode; a later start recreates the
socket in the same directory and heals the mount.  Legacy per-container
proxies keep the current remove-directory behaviour.

`stop_session_proxies` and `stop_all_proxies` remove leftover directories
(and long-name symlinks / lock files) once the session/process is gone.

### R7 — Cross-process start lock

Serialize check-and-spawn per socket directory with `fcntl.flock` on a
lock file next to the directory (`<sock_dir>.lock`, outside the mount).
This prevents two processes from racing unlink→bind and killing each
other's live proxy.  The daemon records its socket inode and exits its
serve loop when the path is replaced (different inode) or removed, so an
orphaned daemon cannot linger.

### R8 — Update path lookup and lifecycle bookkeeping for 3-part keys

- `get_proxy_socket_path(container_name, session_tag=None, pr_id=None,
  workdir=None)` computes the per-workdir path when all four are known,
  then falls back to the in-memory registry (`_container_to_proxy_key`,
  now storing 3-part keys), then the legacy per-container path.
- `stop_push_proxy` parses 3-part keys.
- `pm_core/container.py` callers pass `workdir` (and session/pr) so the
  lookup is correct after a restart.
- `_container_to_proxy_key` remains the in-process source of truth for
  refcounting; cross-process cleanup stays the responsibility of
  `stop_session_proxies`/`stop_all_proxies` and container ownership
  (active #241), which this change does not duplicate.

### R9 — Tests

Add/update tests in `tests/test_push_proxy.py` (and `tests/test_container.py`
where call signatures change) covering:

1. impl workdir + two QA workdirs on the same `(session_tag, pr_id)` get
   three distinct proxies; each push runs `git -C <its own workdir>`.
2. Stopping one workdir's proxy leaves the others alive (socket still
   connectable, same path).
3. Reuse when alive; respawn when the socket is missing or stale; the
   socket directory is preserved across a shared stop.
4. A live proxy with a different workdir/branch is refused, not replaced.
5. A request naming a different/nonexistent workdir is rejected with an
   explicit message and never runs git in another clone.
6. Readiness failure raises `PushProxyError`.

## Implicit requirements

- Container bind-mount stability: never delete a socket directory that a
  live container may have mounted (R6).
- Refcount semantics within a process unchanged: last `stop_push_proxy`
  for a key stops the daemon; other refs keep it alive.
- `stop_session_proxies(session_tag)` still finds every proxy for the
  session (glob matches `{tag}-*`).
- Allowed-branch enforcement and dangerous-flag rejection unchanged.
- Legacy wrappers/requests without `workdir` keep working.
- No host credentials enter the container: still only the socket dir is
  mounted.
- Do not reimplement container ownership/cleanup (#241).

## Ambiguities and resolutions

1. **Keep or reject a request whose `workdir` differs from the proxy's?**
   Resolved: reject.  R1 guarantees each proxy owns exactly one workdir;
   allowing a second would reintroduce the cross-clone push.  Existing
   caller-workdir tests are rewritten to assert per-workdir proxies.
2. **Include `allowed_branch` in the key?**  Resolved: no.  It is stable
   per PR, and a metadata-based refusal (R3) covers a rare mismatch
   without multiplying proxies.
3. **Keep the socket dir on stop?**  Resolved: keep for shared proxies
   (R6) — this is the explicit S18 requirement; remove at session
   teardown.  Empty dirs in `/tmp` are tiny and bounded by session
   lifetime.
4. **Raise or warn when the daemon is not ready?**  Resolved: raise
   `PushProxyError` (R5); silent success creates a broken container.
5. **Backward compatibility with the old 2-part socket path?**  Resolved:
   none.  The pm process and its containers are created together in a
   session; an old container from a previous pm build is not expected to
   survive an upgrade mid-session.

## Edge cases

- Two workdirs whose realpaths differ only by trailing slash / symlink →
  same token, same proxy.
- Hash collision → metadata check (R3) refuses the mismatch.
- Socket file present but not a live socket (stale) → unlink and respawn
  in the same directory.
- Socket directory deleted externally → recreated at the same path; the
  container's old mount cannot be healed from the host, so R6 prevents
  this from happening in normal operation.  Readiness/`proxy_is_alive`
  checks in `create_container`'s reuse path still restart a dead proxy.
- Concurrent `start_push_proxy` for the same key from two processes →
  serialized by R7; the loser reuses the winner's live socket.
- QA loop workdirs deleted after a run → their proxies are stopped by
  container cleanup; a stale directory is harmless and swept at session
  end.
- Request `workdir` is a file, not a directory, or missing → explicit
  rejection (R4).
- Daemon orphaned after its socket path is replaced → inode check makes
  it exit.

## Review iteration 1 refinements

Added during code review (all consistent with R1–R9; no requirement
changed):

- **R3 completed on the daemon side.** `PushProxy.stop()` now checks the
  socket inode before unlinking: a daemon whose path was rebound by
  another daemon leaves the replacement's socket and metadata alone
  (`_owns_socket_path`).  Previously only the "start() returned False"
  case was guarded.
- **Teardown cannot delete a foreign directory.** `/tmp` is
  world-writable, so `_remove_proxy_dirs` now refuses to `rmtree` a path
  that does not resolve to a proxy socket directory directly under the
  glob's parent (`_is_proxy_dir`).  A planted
  `/tmp/pm-push-proxy-…` symlink is unlinked while its target is left
  intact.
- **R4 input validation.** A non-string `workdir` in a request is
  rejected with an explicit message instead of raising `TypeError` and
  dropping the connection without a response.
- **Test hygiene.** An autouse fixture sweeps `/tmp/pm-push-proxy-*`
  entries a test creates and resets the in-memory registries, since R6
  makes shared stops leave their directories behind.

Known, explicitly out of scope (unchanged by this PR): refcounts are
in-process only, so a same-workdir container owned by another process can
still have its proxy stopped when this process drops its last reference.
Cross-process cleanup/restart stays with #241 / pr-ac12b47.

## Review iteration 2 refinements

Added during the second review pass (again consistent with R1–R9; no
requirement changed):

- **The daemon *process* now exits, not just its serve thread.** The
  "Daemon orphaned after its socket path is replaced" edge case above was
  only half-satisfied: `_serve_loop` noticed the rebind, but the
  `__main__` wait loop still tested `os.path.exists(_sock)`, so a daemon
  whose path was unlinked and rebound within one 2 s tick kept running
  forever holding no socket. Reproduced at afeaa283 (old daemon alive
  8 s after a new one rebound its path); the wait loop is now
  `_wait_for_socket_exit()`, which uses the same
  `PushProxy.socket_is_current()` check as the serve loop.
- **Existence fallback restored.** `_serve_loop` skipped the socket check
  entirely when `_sock_ino` was `None` (stat failed at bind time), so such
  a daemon never noticed its socket being removed. `socket_is_current()`
  falls back to `os.path.exists` in that case.
- **Teardown cannot delete another user's directory.** `/tmp` is
  world-writable, so `_remove_proxy_dirs` now also skips a real directory
  whose `st_uid` is not ours, completing iteration 1's symlink-target
  guard (`_is_proxy_dir`).

## Review iteration 3 refinements

Added during the third review pass (consistent with R6/R7; no requirement
changed):

- **Teardown cannot delete a live proxy directory.** `_remove_proxy_dirs`
  now takes the per-directory start lock (non-blocking) and re-checks
  `proxy_is_alive` before `rmtree`. Previously a `stop_session_proxies`
  sweep that raced a container start could delete the directory that a
  just-started proxy — and the container bind-mounted to it — depends on,
  i.e. the S18 failure through a different door. A directory whose start
  is in flight, or whose socket answers, is now left for the next
  teardown.
- **Cleanup no longer deletes a lock file another process holds.**
  `_clear_lock_file()` probes with `LOCK_NB` before unlinking, so teardown
  cannot break the R7 serialisation by removing a lock a start is using.
  `_kill_proxy_socket(lock_held=True)` unlinks directly when the caller
  owns the lock; `stop_session_proxies`'s kill loop now takes that lock
  and skips a directory whose start is in flight.
- **R7 has a test.** `test_concurrent_starts_spawn_one_daemon` drives
  three threads through `start_push_proxy` for one workdir and asserts
  exactly one spawn; with `_start_lock` stubbed out it observes three
  spawns (one of them failing to bind), so the assertion would catch a
  regression.

## Review iteration 4 refinements

Added during the fourth review pass (consistent with R3/R4/R6/R7; no
requirement changed):

- **Refcounts survive a respawn.** `start_push_proxy`'s spawn path used
  `_proxy_refs[key] = {container_name}`, which *replaced* the set. If two
  containers shared a workdir and the socket died, the first one to
  restart dropped the other's reference, so stopping it later killed a
  proxy the sibling container still used. Both paths now go through
  `_add_proxy_ref()`, which adds to the set (and drops a stale reference
  if the same container name is re-registered under a different key).
- **R4 covers falsy non-strings.** `request.get("workdir") or None` turned
  `[]`, `0` and `false` into "field absent" before the type check, so
  they silently fell back to `self.workdir`. The type check now runs on
  the raw value; only the empty string is still treated as absent.
- **`_kill_proxy_socket` gets the teardown guards `_remove_proxy_dirs`
  already had.** Its callers include `stop_all_proxies` /
  `stop_session_proxies`, which build paths from a `/tmp` glob, so a
  planted `/tmp/pm-push-proxy-…` symlink could make teardown unlink
  `push.sock`/`proxy.json` inside an arbitrary directory. It now requires
  the path to resolve to a proxy directory directly under the glob's
  parent, and skips a directory owned by another user (whose unlink would
  raise `EPERM` and abort the whole sweep).
- **A proxy failure names the proxy.** `wrap_claude_cmd` caught
  `PushProxyError` in its generic handler and re-raised
  `ContainerError("… Is docker running?")`, hiding the real cause (R5's
  "fail loudly"). It now reports `push proxy unavailable — <reason>`.
- **Teardown survives a directory at the socket path.** `_kill_proxy_socket`
  only caught `FileNotFoundError`, but docker creates a *directory* where a
  bind-mounted socket file should be (older pm versions mounted the file
  itself), which the start path already handled. A leftover of that shape
  would have raised `IsADirectoryError` out of `stop_push_proxy` /
  `stop_session_proxies` / `stop_all_proxies`; it is now removed instead.

## Review iteration 5 refinements

Added during the fifth review pass (consistent with R3/R6/R7/R8; no
requirement changed):

- **`stop()` cannot unlink a socket it never bound.** `PushProxy.start()`
  sets `_server_socket` *before* `bind()`, so a `start()` that raised
  (e.g. `EADDRINUSE`) left `_sock_ino` unset; `_owns_socket_path()` then
  returned True on the "no inode recorded" fallback and `stop()` unlinked
  whatever another daemon had bound at that path. The instance now records
  `_bound` after a successful bind and `stop()` returns before the unlink
  when it never bound (R3's "never unlink a socket you do not own").
- **Per-container shared stops take the start lock too.** `stop_push_proxy`
  unlinked the socket after dropping the last reference without holding
  the per-directory start lock, so a concurrent `start_push_proxy` that
  reused (and re-referenced) the socket in that window could have it
  unlinked underneath it — the S18 failure through the per-container path
  rather than the sweep. The kill now goes through
  `_stop_shared_proxy_socket()`, which takes `_start_lock` (non-blocking)
  and re-checks `_proxy_refs` before unlinking; a busy lock or a
  re-appeared reference leaves the proxy for session teardown, exactly
  like any other unreferenced proxy. Lock order is unchanged
  (`_start_lock` → `_proxy_lock`, the same order `start_push_proxy` uses).
  The legacy per-container stop gets the same guard (re-check
  `_container_to_proxy_key`, which a concurrent start would repopulate)
  and passes `lock_held=True` so the start-lock file is removed while it
  holds the lock — otherwise `_clear_lock_file`'s `LOCK_NB` probe would
  see our own lock and leak the file on every legacy stop.
- **Session teardown also uses the in-process registry.** `stop_session_proxies`
  killed only sockets matched by the `/tmp/pm-push-proxy-{tag}-*/push.sock`
  glob. When a long session tag forces the hashed socket directory, the
  glob reaches it only through the long-name symlink; if that symlink is
  missing (creation failed, or it was removed), the proxy and its hashed
  directory survived teardown. Candidate sockets now come from the glob
  *and* from `_shared_sock_dir_path()` for this process's keys.
- **A non-object request gets a reply.** Valid JSON that is not an object
  (e.g. `["origin"]`) used to raise `AttributeError` inside the handler,
  which `_serve_loop` swallowed: the connection was dropped with no
  response and the container wrapper failed with a bare traceback. It is
  now rejected explicitly (`request must be a JSON object`), matching
  R4's other input validation.
- **Socket-file removal is one helper.** The "`os.unlink`, but tolerate
  the directory docker leaves behind" block was duplicated at four sites
  (`PushProxy.start`, both `start_push_proxy` paths, `_kill_proxy_socket`),
  and `PushProxy.stop()` unlinked the same path catching only
  `FileNotFoundError`. It is now `_unlink_socket_file()` (module-level
  `import shutil`) at all five sites, so a future call site cannot
  silently lose the `IsADirectoryError` branch.

Tests: `test_stop_does_not_unlink_a_socket_it_never_bound`,
`test_shared_stop_kills_an_unreferenced_socket`,
`test_shared_stop_skips_a_socket_re_referenced_mid_stop`,
`test_shared_stop_skips_when_a_start_holds_the_lock`,
`test_stop_session_finds_hashed_dir_without_long_symlink`,
`test_legacy_stop_clears_its_start_lock`,
`test_rejects_non_object_request`. The `never_bound` and `hashed_dir`
tests fail at 6941c923 for the right reason (the socket is unlinked;
`stop_session_proxies` returns 0).

## Review iteration 6 refinements

Added during the sixth review pass (consistent with R6/R7/R8; no
requirement changed):

- **The legacy start registers under the start lock.** `start_push_proxy`'s
  legacy (no session tag) path spawned the daemon under `_start_lock` but
  registered `_container_to_proxy_key` *after* releasing it.
  `stop_push_proxy` re-checks that registry under the same lock before
  killing the socket, so a stop that slipped into the spawn→register window
  could unlink a socket the restart had just created, leaving the caller
  with a dead proxy (the shared path already registered under the lock).
  Registration now happens inside the lock, through a new `_drop_old_ref()`
  helper shared with `_add_proxy_ref()` so a container that changes keys
  does not pin its old proxy.
- **A lock file replaced in the open→flock window is re-acquired.**
  `flock` locks the inode, not the name. `_clear_lock_file` already
  probed with `LOCK_NB` before unlinking, but a teardown that unlinked the
  file between a start's `open()` and `flock()` left that start holding a
  lock no other process could see; a third process could then create a
  fresh file and enter the check-and-spawn section concurrently (R7's
  failure through the lock file itself). `_start_lock` now verifies with
  `_fd_is_path_file()` that the file it locked is still the one at the
  lock path (inode+device) and retries otherwise; `_clear_lock_file`
  refuses to unlink a file that was replaced in the same window. Blocking
  acquisition raises `PushProxyError` after a bounded number of retries;
  the non-blocking form yields `False`, so teardown still skips a busy
  directory.
- **A failed discovery symlink no longer fails the start.** `_shared_sock_dir`
  creates the long-name symlink for discoverability only, but an
  `OSError` (name too long, unwritable `/tmp`) propagated out of
  `start_push_proxy` and surfaced as a misleading container error.
  Creation is now best-effort; teardown still finds hashed directories
  through the in-process registry (iteration 5).

Tests: `test_legacy_registration_happens_under_the_start_lock`,
`test_start_lock_retries_when_the_lock_file_is_replaced`,
`test_clear_lock_file_keeps_a_replacement`,
`test_discovery_symlink_failure_does_not_break_start`. All four fail at
848ab98c for the right reason (registration observed after lock release;
lock path missing after a racing unlink; a replacement lock file deleted;
`OSError` escaping `start_push_proxy`).

## Review iteration 7 refinements

Added during the seventh review pass (consistent with R5/R6/R7; no
requirement changed):

- **Teardown resolves the glob's parent.** `_remove_proxy_dirs` compared
  the resolved entry path (`os.path.realpath(path)`) against the *literal*
  glob parent (`os.path.dirname(glob_pattern)`). Where `/tmp` is a symlink
  (macOS: `/tmp -> /private/tmp`) the two never match, so every legitimate
  proxy directory was refused as "non-proxy" and session teardown leaked
  them. `_kill_proxy_socket` already resolved both sides; the sweep now
  does too.
- **An unusable start-lock file no longer escapes as a bare `OSError`.**
  `/tmp` is world-writable, so another user can plant
  `pm-push-proxy-*.lock` with a mode we cannot open. `_start_lock` let
  `os.open()`/`fcntl.flock()` raise `PermissionError`, which aborted a
  whole teardown sweep and, on the start path, surfaced through
  `wrap_claude_cmd` as the misleading "Is docker running?" message. The
  non-blocking form now treats "cannot open/lock" like "busy" (yields
  `False`, the directory is skipped); the blocking form raises
  `PushProxyError` naming the lock path.
- **The discovery-symlink replacement cannot delete another user's
  directory.** `_shared_sock_dir` `shutil.rmtree`s a *real* directory
  squatting on the long name before linking to the hashed directory. It
  now only does so when the directory is ours, matching the `st_uid`
  guard the sweep and `_kill_proxy_socket` got in iterations 1–2.
- **A busy proxy is no longer mistaken for a dead one.** The daemon
  serves one request at a time (a push can run 120 s) and
  `proxy_is_alive` probes connect without sending. With `listen(1)` a
  single queued probe made the next connect block until its 2 s timeout,
  so a live-but-busy proxy looked dead and callers replaced it — the
  failure mode R3 exists to prevent. The backlog is now 16.
- **The legacy in-pane cleanup removes the metadata sidecar.** For a
  non-shared proxy, `build_exec_cmd`'s EXIT trap removed `push.sock` and
  then `rmdir`'d the directory, but the daemon's `proxy.json` sidecar
  (new in this change) kept it non-empty, so the `rmdir` failed and the
  directory leaked. The trap now removes the sidecar first.

Tests: `test_unopenable_lock_file_is_skipped_by_teardown`,
`test_sweep_resolves_a_symlinked_parent`,
`test_shared_sock_dir_keeps_a_foreign_directory`, and an extended
`test_cleanup_removes_proxy_socket` (metadata sidecar in the EXIT trap).
The first three fail at 23b21cc0 for the right reason (a `PermissionError`
escapes both lock modes; the sweep leaves the directory; the foreign
directory is `rmtree`d).
