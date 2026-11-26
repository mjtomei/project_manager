# QA Spec: Workdir-keyed push proxies (pr-748e708)

## What changed

The host-side push proxy that lets containerised Claude sessions push to the
PR branch was keyed by `(session_tag, pr_id)` only.  Implementation, review
and sign-off containers on a PR share one host workdir, but every QA scenario
container has its own clone workdir, so the second container to call the
start path could replace the first container's proxy (and its socket) with one
serving a different clone.  The impl container's pushes then ran `git push`
from a QA clone.

The change keys a shared proxy by `(session_tag, pr_id, hash(realpath(workdir)))`:

- impl / review / sign-off on the PR workdir share one proxy;
- each QA scenario clone gets its own proxy and socket directory;
- a request names the caller's host workdir and is rejected unless it matches
  the proxy's own workdir (never falls back to another clone);
- a live proxy is never replaced by a request for a different workdir/branch;
- a proxy that does not become ready fails container creation loudly;
- stopping a shared proxy keeps its socket *directory* (a running container
  may still bind-mount it); session teardown removes directories, metadata,
  lock files and discovery links.

## Requirements (Given / When / Then)

### R1 — Impl and QA containers on one PR get independent proxies
- **Given** a container-mode project with an implementation session running
  for PR `P` (impl container bound to the PR workdir), **When** a QA scenario
  for `P` starts in container mode, **Then** two distinct proxy socket
  directories exist for the same session and PR, one recording the PR workdir
  and one recording the QA scenario clone, and each container can reach its
  own socket at the mounted `/run/pm-push-proxy/push.sock`.
- **Given** the same state, **Then** the impl container's socket path is the
  same path it had before the QA start — the QA start neither moved nor
  replaced it.

### R2 — Each container pushes its own commits (no cross-clone push)
- **Given** impl and QA containers on `P`, each with its own proxy, **When**
  the user commits in the impl container and pushes the PR branch, **Then**
  the push succeeds and the upstream branch tip is the impl commit, and the
  QA clone's branch is not the source of that push.
- **Given** the same state, **When** the QA scenario container commits its
  own change and pushes, **Then** its push succeeds and lands the QA commit,
  and a later impl commit+push still succeeds and lands the impl commit.
- **Then** neither container's commits appear in the other clone's history
  as a side effect of the other's push.

### R3 — Reuse for the same workdir
- **Given** an impl container on the PR workdir, **When** the review session
  for `P` starts (same PR workdir), **Then** both use the same socket path and
  one proxy daemon serves both.
- **Given** two containers sharing that proxy, **When** one of them is
  stopped, **Then** the proxy stays alive and the other container's pushes
  still work.

### R4 — Concurrent starts do not kill each other
- **Given** a PR with no live proxy, **When** two sessions on the same workdir
  start at nearly the same time, **Then** exactly one proxy exists for that
  workdir, both containers use it, and both can push.
- **Given** an impl session running, **When** several QA scenario containers
  start in parallel for the same PR, **Then** exactly one proxy exists per
  distinct workdir (impl + one per scenario), all are alive, and the impl
  container's push still works afterwards.

### R5 — A failed push is explicit, never silently another clone
- **Given** a running container whose proxy socket has disappeared (daemon
  gone, socket removed), **When** the user pushes from inside the container,
  **Then** the push fails with an explicit proxy/connection error and nothing
  is pushed anywhere; no commit from another clone reaches the upstream.
- **Given** a live proxy for workdir A / branch B, **When** a client asks it
  to push from a different workdir, or to a different branch, or with
  `--all`/`--mirror`/`--tags`/`--upload-pack`, **Then** the request is refused
  with a message naming what was rejected, and nothing is pushed.

### R6 — Recovery heals the existing container's mount
- **Given** a running container whose proxy socket was lost, **When** the
  user relaunches/reopens the session so the start path runs again, **Then** a
  new socket appears at the same mounted path and the existing container's
  push now succeeds — without recreating the container.
- **Given** a stale (not live) socket file at the proxy path, **When** the
  session starts, **Then** the stale entry is replaced and a working proxy is
  started in the same directory.

### R7 — Stopping one actor leaves the others intact
- **Given** impl + two QA containers on one PR, each with a proxy, **When**
  the user closes/stops one QA scenario (its container is removed), **Then**
  that proxy stops and its socket is gone, while the impl and the other QA
  proxies remain alive, their pushes still work, and the impl socket directory
  still exists.

### R8 — Session teardown removes every trace
- **Given** a session with proxies across several workdirs, **When** the user
  kills the session (or removes all pm containers), **Then** every proxy of
  that session is stopped and its socket directory, metadata sidecar, lock
  file and discovery link are gone from `/tmp`, with no proxy daemon left.
- **Given** a second session/project running on the same host, **When** the
  first session is killed, **Then** the second session's proxies and socket
  directories remain intact.

### R9 — Startup failures are reported as proxy failures
- **Given** container mode enabled and the proxy's socket location unusable
  (an entry that cannot be removed, an unwritable location, or a daemon that
  never becomes ready), **When** the user launches an impl/review/QA session,
  **Then** the launch aborts with a message that names the push proxy and the
  socket/workdir rather than blaming the container runtime, and no broken
  container is left running.

### R10 — Existing push restrictions preserved
- **Given** a container with allowed branch B, **When** the user pushes
  another branch, a broad flag, or from a clone whose `origin` is a plain
  local path, **Then** each is refused explicitly and nothing is pushed.

## Setup (user steps)

Use `tui-manual-test.md` (venv + editable install, `PYTHONPATH=/workspace`,
`pm which` check, throwaway project, `pm session`).  Additional setup shared by
most scenarios:

1. Give the throwaway project a real-looking remote: create a bare repo
   outside the project, clone it, and set the clone's `origin` to the bare
   repo **via a `file://` URL**.  A bare repo addressed by a plain filesystem
   path is treated as a local-path origin and pushes are refused by design;
   the `file://` form is the offline stand-in for GitHub.
2. `pm init` (it records the `file://` origin), `pm pr add ...`, `pm push` so
   the PR exists on the base branch, then `pm pr start` for the PR.
3. `pm container enable`; opt the test project into nested podman
   (`project: nested_podman: true`) per the instruction, so a container-mode
   QA loop can launch scenario containers from inside the QA worker.
4. Configure fake-claude (`pm fake-claude config set ...`) so QA/review loops
   reach a verdict without a real model.
5. A QA scenario can be produced with `pm qa run <instruction> --pr <id>` in
   container mode, or through the TUI QA loop.

## Edge cases and failure modes

- Two containers on the same workdir start simultaneously → one daemon, not
  two fighting over the socket.
- A QA start lands while the impl proxy is momentarily dead/stale → the impl
  socket is still not stolen (it is replaced in place, for the impl workdir).
- A session teardown races a container start → the start either wins or is
  retried; the user does not see an "unusable directory" failure for a race
  they did not cause.
- A container leaves an entry inside the bind-mounted socket directory →
  teardown keeps the directory and its discovery link for a later sweep
  instead of deleting a live container's mount or leaking the directory.
- A long session tag / long project path forces the hashed socket directory →
  the long-name discovery link still lets a later session find and clean it.
- A project directory whose name contains glob characters (e.g. `repo[1]`) →
  session teardown removes only that session's proxies, not a sibling's.
- A daemon whose socket path is removed or rebound exits instead of lingering.
- Two spellings of the same workdir (symlink) share one proxy.

## Pass/Fail criteria

- **Pass**: every Given/When/Then above is observable on the user surface —
  distinct socket directories per workdir, pushes landing the right commit
  upstream, explicit refusal messages for foreign workdir/branch/flags, the
  existing container recovering after a proxy restart, and teardown leaving no
  `/tmp/pm-push-proxy-*` residue for the session while other sessions are
  untouched.  The reproduction test
  (`tests/test_push_proxy.py::TestWorkdirKeyedProxies::test_impl_and_qa_get_distinct_proxies`)
  fails at base `74462d76` and passes at the PR head.
- **Fail**: any push succeeds against a clone the user did not intend; a QA
  start stops/re-points the impl proxy; a dead socket yields a silent success;
  a proxy failure surfaces as a container-runtime error; teardown deletes a
  live container's socket directory or leaks directories/locks/links; another
  session's proxies are removed.

## Ambiguities resolved

1. **Cross-process refcounting / cleanup** is explicitly out of scope here
   (owned by #241 / pr-ac12b47).  Teardown is verified through the session and
   container lifecycle and the resulting filesystem state, not by requiring a
   second pm process's in-memory registry to know about a first process's
   proxies.
2. **#249's missing-socket symptom**: the PR description says its root cause is
   not established, so scenarios assert only that a missing/unusable socket
   produces an explicit failure and that restarting heals the existing
   container's mount.  They must not assert that the workdir-key collision
   caused it.
3. **Demonstrating a successful push offline**: pushes from a plain local-path
   origin are refused by design, so scenarios use a bare repo referenced by a
   `file://` URL as the upstream.
4. **Review and sign-off share the impl proxy** because they use the PR
   workdir; this is verified by the shared socket path rather than by a
   separate key.
