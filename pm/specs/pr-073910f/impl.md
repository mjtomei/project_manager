# Implementation Spec — Per-session tmux server isolation (pr-073910f)

## Problem

Every pm session currently shares the user's default tmux server (socket
`/tmp/tmux-<uid>/default`) unless `--global`/`--group` was passed. A command
that targets "the current client" or "the server" rather than a specific
pane/session can therefore act on an unrelated pm session. Confirmed incident
(#263 QA S25, 2026-10-28): `quit_app()` in `pm_core/tui/pane_ops.py` ran bare
`tmux detach-client`, which detached the user from a *different* pm session
(#249) on the shared server. Key delivery was targeted correctly; the
subsequent client operation was not.

The partial infrastructure already exists:

- `pm_core/tmux.py::_tmux_cmd()` prepends `-S <socket>` when an explicit
  `socket_path` is given or `PM_TMUX_SOCKET` is set.
- `pm_core/paths.py::shared_socket_path(tag)` returns
  `/tmp/pm-sessions/pm-<tag>` and `ensure_shared_socket_dir()` creates the
  1777 directory.
- `pm_core/cli/session.py::_session_start()` computes that socket only when
  `--global`/`--group` is used, and only then sets `PM_TMUX_SOCKET` in the
  process, the TUI command, and the tmux session environment.

## Requirements (grounded in code)

### R1 — Every pm session gets a dedicated tmux server

`pm_core/cli/session.py::_session_start()` must, for **all** sessions
(shared or not):

1. Compute the session name first (`_get_current_pm_session()` /
   `_get_session_name_for_cwd()` / `--dir` tag), then derive the session tag
   from that name (`session_name.removeprefix("pm-")`).
   "Strip the grouped suffix" always means `paths.base_session_name()`, which
   removes only a **numeric** `~N`: a session name is derived from the repo
   directory name, which may contain `~` itself, and splitting at the first
   `~` gave two unrelated projects the same socket (review-loop b48f i11).
2. Compute `socket_path = str(paths.session_socket_path(tag))`, i.e.
   `/tmp/pm-sessions/pm-<tag>`. `paths.session_socket_path()` is the new
   canonical name; `paths.shared_socket_path()` remains as an alias.
3. `ensure_socket_dir()` (existing `ensure_shared_socket_dir` renamed with an
   alias) before first use.
4. Set `os.environ["PM_TMUX_SOCKET"] = socket_path` immediately, so every
   subsequent `tmux_mod` call (`create_session`, `split_pane`,
   `create_grouped_session`, `pane_layout.rebalance`, …) targets the private
   server without threading the argument through every call site.
5. Pass `PM_TMUX_SOCKET` in the TUI command prefix (`PM_TMUX_SOCKET=... pm
   _tui`) and via `tmux set-environment` for the session, exactly as the
   shared path does today.
6. Also `set-environment -g PM_TMUX_SOCKET <path>` on the private server so
   server-level `run-shell` hooks and popups see it explicitly (tmux 3.4
   already exposes `$TMUX` there; the global env is belt-and-braces and is
   the documented propagation contract).

Because `PM_SHARE_MODE` is mixed into `get_session_tag()`, shared and private
sessions already hash to different tags and therefore different sockets; no
extra branching is required beyond keeping the existing shared setup
(`ensure_socket_dir`, permission/ACL grants, `window-size=smallest`).

### R2 — Grouped sessions keep working on the private server

`create_grouped_session()` (`tmux new-session -d -t base -s base~N`) and the
group helpers (`list_grouped_sessions`, `find_unattached_grouped_session`,
`next_grouped_session_name`, `list_clients_in_group`, `detach_client`,
`session_group`) must all run against the same socket. They take
`socket_path` and otherwise fall back to `PM_TMUX_SOCKET`; R1 makes that
variable always present. (`current_or_base_session()` takes no
`socket_path` — it resolves the current pane through the ambient server, so
it is only correct from a process whose `PM_TMUX_SOCKET` is already
selected; every caller is.) `_session_start()` must pass the computed
`socket_path` explicitly on the create/attach path (as it does for shared
sessions today).

### R3 — Locate sessions by socket (attach/list/discovery)

1. `pm session` (attach) uses the deterministic socket for the target tag; no
   ambient-state guessing. `--print-connect` prints `tmux -S <socket> attach`
   for private sessions too (not only shared ones).
2. `pm session kill` targets the server that hosts the session (private
   socket preferred, legacy default server as fallback), kills every session
   in the session *group* — the `base~N` grouped sessions and a user's own
   view however it is named (`sessions_in_group()`; review-loop 2caf i7) —
   then the base, and unlinks the socket file **only when no server
   answers on it** (`server_alive()`; tmux leaves the file behind after
   `kill-server` / last-session exit — verified — but a live server can
   outlive its base session, and unlinking its socket would strand the
   clients still attached to it).  The probe and the unlink are refused
   outright for the hostile states the rest of the socket handling
   refuses: a symbolic link (or any non-directory) at the socket
   directory, a symbolic link at the socket path, and a socket another
   user owns — a planted directory link would otherwise have
   `server_alive()` (and the unlink) act on a path inside a directory pm
   does not trust (review-loop b48f i10).  Session selection
   tries the cwd-derived name first and the ambient session second, choosing
   the first that is actually running — so a workdir clone kills the session
   hosting it, while a different project's ambient session is never preferred
   over the cwd's live one.  The destructive lookup matches the session name
   **exactly** (`find_exact_session_server`, target `=name`): a bare tmux
   target is a prefix match, so a surviving grouped session `pm-x~1` must not
   make `pm-x` look alive to kill (QA scenario 6; discovery keeps prefix
   matching on purpose — see `find_session_server`).
3. New `pm session list` enumerates pm sessions across **all** pm servers:
   every `pm-*` socket in `/tmp/pm-sessions/` plus the default server
   (legacy). It reports base session name, socket, attached client count,
   and marks shared sessions. Stale/foreign sockets are skipped, not fatal.
   A user's own view of a session (`tmux new-session -t base -s myview`,
   S118/S121/S124) is not a session of its own: it is skipped whatever its
   name — including a name that looks like a pm session, e.g. `pm-laptop` —
   so one session is one row (review-loop 2caf i4).
4. `pm_core/cli/helpers.py::_find_tui_pane()` (used by every `pm tui`
   subcommand) resolves the server for an explicit `--session`, the current
   pane, the cwd-derived session, and finally scans pm servers for a live
   TUI pane. It selects `PM_TMUX_SOCKET` for the found session before
   returning, so callers' `tmux_mod` calls hit the right server. The cwd
   lookup only applies when the process is *not* inside a pm session: there
   the ambient session wins, because a running session derived from the cwd
   would otherwise be resolved from inside a different pm session (review
   loop 7af7 i3). When one of the two branches above identified a session,
   the final scan is scoped to *that* session's server, because pane ids
   are per server and `pm tui send` delivers keys unscoped (review-loop
   7af7 i1).  With no session identified (a plain shell), the scan runs
   across this user's servers only (`_server_owned_by_us`): `/tmp/pm-sessions`
   is world-writable and `--global` sockets are world-accessible, so an
   unfiltered scan could resolve to another user's live TUI and hand its
   pane to `pm tui send` (review-loop 703c i4); such a session stays
   reachable with an explicit `-s` and from inside it.  When the
   identified session came from either branch (the ambient one or the
   cwd-derived one), its server is scanned even if
   `list_pm_sessions()` does not report it — that function enumerates
   socket *files*, and a live server can outlive an unlinked socket
   (review-loop 3cc7 i1; the cwd branch, review-loop 703c i6).  The
   current-pane branch resolves the ambient
   name through `pane_registry.pm_session_name()` rather than a raw `pm-`
   prefix test, so a user's own grouped view of a pm session
   (S118/S121/S124, whose name need not be `pm-*`) still identifies that
   session instead of falling through to the unscoped scan
   (review-loop 703c i1).  Every pane→session comparison in the lookup
   (the recorded-pane liveness check, the live-`pm _tui` fallback and the
   last-resort scan) resolves the name tmux reports through the session
   *group* (`_pm_session_of`): `list-panes -a` lists a shared pane once per
   session in its group, so tmux may report it under a user's own view's
   name (review-loop 2caf i4).
5. `pm_core/tmux.py` gains `list_pm_sessions()` and
   `socket_path_from_tmux_env()`; `pm_core/paths.py` gains
   `session_socket_path()` / `ensure_socket_dir()`.
6. `pm_core/cli/helpers.py::_get_pm_session()` also selects the server that
   hosts the resolved session.  Commands that address a session by name
   (`pm pr start`, `pm pr review`, `pm meta`, `pm container build`,
   `pm session home`, `home_window.refresh_home`, …) resolve the session
   outside tmux as well, where there is no ambient `PM_TMUX_SOCKET`/`$TMUX`;
   without this they would query the default server and silently conclude a
   live private session is gone.  The lookup is skipped when the process is
   already inside a pm session, so the common in-pane path pays nothing.

### R4 — Explicit propagation to subprocesses, hooks and popups

1. `pm_core/wrapper.py::main()` and `main_for_session()` resolve the ambient
   socket at process start: `PM_TMUX_SOCKET` if set, else the socket in
   `$TMUX` **when it lives under `/tmp/pm-sessions/`**, and export it. This
   covers `run-shell` hooks (`pm _pane-closed`, `_pane-opened`,
   `_window-resized`, `_pane-exited`, `_pane-switch`) and `display-popup`
   bodies (`pm _popup-show`, `_popup-picker`, `_popup-cmd`), which inherit
   `$TMUX` but not `PM_TMUX_SOCKET` (verified on tmux 3.4).
2. `pm_core/cli/__init__.py::main()` does the same for `python -m pm_core`.
3. `_tmux_cmd()` gains a `use_env=False` switch so callers can explicitly
   address the **default** server (legacy detection, `pm session list`).
   `session_exists()` forwards it.
   **`use_env=False` alone is not enough**: the tmux *binary* falls back to
   the socket named by `$TMUX` whenever no `-S` is given (verified on tmux
   3.4), so a process running inside a pm pane still reaches the private
   server.  `pm_core/paths.py::default_socket_path()`
   (`$TMUX_TMPDIR`/`/tmp` + `tmux-<uid>/default`) is therefore passed as
   `-S` wherever the default server is meant: `session_exists(use_env=False)`,
   `list_pm_sessions()`'s default-server pass, `session_kill`'s legacy
   branch, and `helpers._use_tmux_socket(None)`.  Without this,
   `pm session list` run from inside a pm pane listed the current private
   server a second time as "(default server)", and legacy detection, legacy
   kill and `pm tui -s <legacy>` from inside another pm session could
   address the wrong server.  (A user who runs tmux with `-L <name>` keeps
   the default server unused; those legacy sessions are not found — the
   same as before this change.)
4. Fix `pm_core/qa_status.py::_find_attached_session()` / `_switch_to_window()`
   to address the session's own server instead of a bare `tmux`, so QA panes
   on a private server switch the right client.  The module runs as a
   standalone script (`python3 …/qa_status.py`) and deliberately does not
   import `pm_core`, so the argv comes from its local `_tmux_argv()` helper
   (`PM_TMUX_SOCKET`, else a `$TMUX` value under `/tmp/pm-sessions/`) rather
   than `tmux_mod._tmux_cmd()`; the socket-directory literal is duplicated
   there by design (review-loop d1c0 i2).  The pane→session step also
   resolves the pane's session through its tmux session *group* (the same
   test `tmux.current_or_base_session` applies), so a user's own view of
   the session — however it is named — is the session whose window gets
   switched (review-loop 2caf i6).  The fallback session list is
   `:`-separated for the same reason the tmux helpers are: a session name
   — derived from the repo directory name — may contain a space or `|`,
   while tmux forbids `:` in names (review-loop b48f i10).
5. Do not rely on `display-popup` propagating `PM_TMUX_SOCKET` (existing QA
   note pr-2d0588a); the `$TMUX` resolver in (1) is the contract.

### R5 — Fix the actual detach bug

`pm_core/tui/pane_ops.py::quit_app()` must never run bare `detach-client`.
New `tmux_mod.detach_current_client()`:

1. Read `$TMUX_PANE`, resolve its window (`pane_window_id`).
2. Resolve the pm base through `session_group()` (a user's own view of the
   session need not be named `base~N`; see 703c i3), falling back to the
   `~` split for an ungrouped session.  Enumerate the candidates with
   `sessions_in_group()` — every session in tmux's session *group*, so the
   base, its `base~N` views **and a user's own view however it is named**
   (S118/S121/S124) all count (review-loop 2caf i2; a name-prefix test
   missed such a view, so Ctrl-Q pressed while viewing the TUI through one
   detached nothing, or a different client of the same session).
   `list-clients` on the session's server; keep clients whose
   `client_session` is in the group **and** whose session's active window
   equals the TUI pane's window.
3. Detach the most recently active candidate by TTY
   (`detach-client -t <tty>`). Ties are resolved by `client_created`.
4. If no candidate matches (no client's session is viewing the TUI's
   window), fall back to the group's most recently active client and
   detach that single TTY.  Never `detach-client -s
   <session>`: it detaches *every* client attached to the session, so one
   Ctrl-Q dropped all of them (QA scenario 10, fixed 2026-11-01).  If the
   group has no client either, do nothing.
5. Return whether a client was detached; `quit_app()` still calls `app.exit()`
   when not in tmux.

This keeps a multi-client attach within one pm session working and, combined
with the private server, cannot reach another pm session.

### R5b — Never adopt an ambient session this HOME does not know

`_known_ambient_session()` returns the ambient `$TMUX_PANE` session only
when that session's pane registry exists in the **current** HOME.
`_session_start()` resolves its target through
`_resolve_start_session_name()` (ambient or cwd-derived); `pm session
kill`/`mobile` include the ambient session as a fallback candidate only
when it is known.  Otherwise the cwd-derived name is used.  Without this guard, a
process running under a different HOME (tests, tooling, a temporary sandbox)
that inherits `$TMUX`/`$TMUX_PANE` adopts a foreign session, sees an empty
registry, concludes the TUI is missing, and respawns a TUI into the live
session.  Regression tests cover both branches.

### R6 — Rollout safety (existing live sessions)

New sessions get private servers. Existing sessions on the default server
must be left untouched:

1. If the private socket has no session **and** a session with the same name
   exists on the default server, `_session_start()` attaches to the legacy
   session and prints a one-line note that `pm session kill` + `pm session`
   migrates it. No migration, no detach, no restart, no kill is performed
   automatically. `_resolve_session_socket()` returns `None` so nothing is
   propagated into the session, but it exports
   `PM_TMUX_SOCKET=str(default_socket_path())`: *clearing* the variable is
   not enough, because with no `-S` the tmux binary follows `$TMUX`, which
   from inside another pm pane names that session's private server — the
   legacy session would look missing and the create path would duplicate it
   on the wrong server (same failure mode as R4.3).
2. `pm session kill` is the only command that removes the legacy session, and
   only when the user explicitly runs it.
3. Never call `kill-server`; use `kill-session` for the base/grouped sessions
   and unlink the socket file afterwards.
4. No destructive QA/tests against the user's live server: every fixture uses
   its own disposable socket under a temp dir (or `/tmp` when the pytest
   path would exceed the ~108-byte Unix socket limit).

### R7 — Long paths and stale sockets

1. Unix socket paths are limited (~108 bytes). If
   `/tmp/pm-sessions/pm-<tag>` is too long, `session_socket_path()` falls back
   to `/tmp/pm-sessions/pm-<md5(tag)>` (deterministic, 35 chars). Discovery is
   unaffected because session names are read from the server, not the
   filename.
2. A stale socket file (server SIGKILLed) is left on disk; `has-session`
   returns non-zero and tmux reuses the path on the next `new-session`
   (verified). `session_exists()` therefore remains the liveness check.
3. Private sockets are created by tmux with mode 0600 (verified); shared
   sessions keep the existing chmod/`server-access` path.  Because the
   socket directory is world-writable, private sessions refuse to use an
   existing socket file owned by another UID (shared sessions skip that
   check — the sharing user owns the socket by design).  Every *implicit*
   lookup (cwd discovery, `_get_pm_session`, `pm session
   --print-connect`/`kill`/`mobile`, the TUI connect screen) refuses to
   adopt or advertise such a socket too — a real socket is not a link, so
   the entry-type check does not cover it, and tmux < 3.3 has no
   `server-access` ACL (review-loop b48f i9).  Explicit `-s` lookups and
   shared/joiner contexts are exempt: reaching another user's
   `--global`/`--group` socket is the documented sharing flow.  A
   *symbolic link* at a session's socket path is refused in both modes,
   before any probe or export: a real socket is never a link, and a tmux
   *client* follows one when it connects, so a shared start — which skips
   the uid check — would otherwise attach to, and create the session on,
   whatever server the link names (review-loop b48f i7).  The start path
   never binds at the link's target: tmux unlinks the entry and binds at
   the socket path itself, or fails under the directory's sticky bit (see
   the b48f i8 correction below).  The directory itself must be a real
   1777 directory: a sticky bit is required, and a symbolic link at
   `/tmp/pm-sessions` is refused even when it resolves to such a directory
   (review-loop 2caf i8 — its
   target's owner can unlink our sockets; the sticky bit does not protect
   a file from the directory's owner).

### R8 — Destructive and concurrent session operations are exact and convergent

Formalises the exact-match and concurrent-start rules introduced by the
QA scenario 6 fixes (those were not new *user-facing* requirements, which is
why that section says "no requirement changes"); the code comments in
`find_exact_session_server` and `session_kill` refer to them as R8, which is
also the number of the matching user story in `qa.md` ("Killing a session
tears down only that session").

1. `pm session kill` resolves the session with an **exact** name match
   (`find_exact_session_server`, tmux target `=name`) **and kills with exact
   targets** (`kill_session(..., exact=True)`, i.e. `kill-session -t =name`,
   for the base and for every group member).  A bare tmux target is a
   *prefix* match, so `has-session -t pm-x` also succeeds for a surviving
   grouped session `pm-x~1`; treating that as "running" killed the grouped
   session (detaching its client) and unlinked a live server's socket.  The
   same prefix rule applies to `kill-session`: with the base already gone,
   `kill-session -t pm-x` kills whichever remaining session starts with
   `pm-x` (verified on tmux 3.2a: `pm-xyz`), so the resolution being exact
   is not enough — a base that vanishes between the lookup and the kill
   could still tear down a different session (on the legacy default
   server, another pm session's TUI).  When nothing matches exactly, the
   command reports `No session '<name>' found.` and leaves the server alone
   (it unlinks the socket file only when `server_alive()` says nothing
   answers on it).  Discovery (`pm tui …`) keeps prefix matching on
   purpose, so `pm tui view -s pm-x` still reaches the group's TUI after
   the base was killed elsewhere.
2. Paired simultaneous `pm session` starts converge.  Both invocations pass
   the caller's `session_exists` check and then race into `new-session`; the
   loser gets "duplicate session".  `create_session` /
   `create_grouped_session` treat that as a lost race only when the exact
   name exists afterwards (`has-session -t =name`) and converge on the
   winner's session; any other failure is still re-raised.

## Implicit requirements

- **Session-name ↔ tag invariant**: `_session_tag_from_name()` and
  `_get_session_name_for_cwd()` already assume `pm-<tag>`; the socket must be
  derived from the final session name (not re-derived from cwd) so workdir
  clones and `--dir` joins resolve the same server.
- **No double sessions during rollout**: a private session and a legacy
  session with the same name must not both be created. Legacy detection runs
  before the create path.
- **Hooks are per server**: `_register_tmux_bindings()` installs bindings and
  hooks through `_tmux_cmd`, so R1 automatically scopes them. It must run
  after `PM_TMUX_SOCKET` is set (it does — called from `_session_start`).
- **Pane registry keys stay `pm-<tag>`**: registry files, capture dirs,
  runtime state, and session configs are keyed by the session name, which is
  unchanged. Only the tmux server changes.
- **`pm session --print-connect` / TUI "connect" screen** must show the
  socket command for private sessions too (`pane_ops.show_connect`).
- **`pm session mobile`** must resolve the private socket when run outside
  the session (it calls `session_exists`/`list_windows` by name).
- **Existing tests** that assert `_tmux_cmd` output must keep passing: the
  `$TMUX` fallback lives in the CLI/wrapper entry points, not in
  `_tmux_cmd`, and is gated to sockets under the pm socket directory.

## Ambiguities and resolutions

1. **"Update pm session attach/list commands"** — there is no `pm session
   list` command today; `pm session` itself is the attach command. Resolution:
   make `pm session` (attach), `--print-connect`, `kill`, `mobile`, and the
   `pm tui` discovery path socket-aware, and add a new `pm session list`
   across servers. This is the smallest interpretation that satisfies
   "locate sessions by their sockets".
2. **Socket directory for private sessions** — the task suggests
   `/tmp/pm-sessions/pm-{tag}`, which is the existing shared dir (1777).
   Resolution: keep that path (as instructed). tmux creates private sockets
   mode 0600, and shared sessions retain their explicit chmod/ACL path, so
   private servers are not connectable by other users on tmux 3.4. A future
   per-uid directory is noted as a hardening option, not implemented here.
3. **Legacy session handling** — "preserve existing live sessions … do not
   migrate" could mean (a) attach to the legacy session or (b) start a
   duplicate private session and leave the legacy one running. Resolution:
   (a). It preserves the live controller exactly, avoids two servers owning
   the same pane-registry keys, and the user retires the legacy session
   explicitly via `pm session kill`.
4. **Global environment propagation** — set `set-environment -g` on the
   private server *and* resolve from `$TMUX` at entry. Resolution: both.
   `$TMUX` is the verified mechanism for popups/hooks on tmux 3.4; the
   global env documents intent and helps subprocesses that sanitize env.
5. **Detaching with multiple clients on the same grouped session** — a pane
   cannot identify which client pressed the key. Resolution: prefer the
   client viewing the TUI's window with the most recent activity; ties fall
   back to creation order. Still scoped to one pm session/server.

No **[UNRESOLVED]** ambiguities.

## Edge cases

- `pm session` from inside another pm session for a different repo: the
  ambient session name wins (existing behavior), and the socket is derived
  from that name, not the ambient `PM_TMUX_SOCKET`.
- `pm session --dir` for a shared session: tag includes `PM_SHARE_MODE`
  (set by `--global`/`--group`), so the shared socket is computed.
- `pm session kill` with a stale socket file and no server: reports "no
  session" and unlinks the stale file.
- `pm session list` when `/tmp/pm-sessions` does not exist: lists legacy
  default-server pm sessions only.
- A socket owned by another user / unreadable: `list-sessions` fails, row is
  skipped with a debug log; never raises.
- Very long repo names: hashed socket filename (R7).
- `pm tui send -s pm-<tag>` from outside tmux: `_find_tui_pane` selects the
  private socket and verifies the pane still exists before returning it.
- TUI `q` pressed while the session is unattached: no client to detach; the
  TUI logs and continues rather than issuing a server-wide detach.
- `--global`/`--group` still set `window-size=smallest` on base + grouped
  sessions and still grant `server-access` on the private/shared socket.
- Non-git directory: session name falls back to `pm-<dir>-00000000`; the tag
  is taken from that name, so a deterministic socket still exists.

## Incident during implementation (recorded honestly)

While validating `_session_start`, an unisolated smoke script inherited the
live session's `TMUX`/`TMUX_PANE` and ran under a temporary HOME.  It adopted
the live session `pm-project_manager-5b29c418`, found an empty pane registry
(temp HOME), and split a stray `pm _tui` pane (`%2639`) into the live `@333`
main window; the stray TUI also wrote itself into the real pane registry and
removed the live TUI pidfile.

Before the stop instruction, cleanup killed the stray pane, killed grouped
session `pm-project_manager-5b29c418~2` (the shepherd reports `~2` pre-existed,
so this was an unauthorized kill of an unattached grouped session), removed
the `%2639` registry entry, and rewrote the live pidfile with controller pid
3432234.  No client was detached; the base session, `~1`, controller
`%580`/3432234 and user client 2379769 were not touched.  A guide pane
`%2640` remains under shepherd review.  All further live-session actions
stopped on instruction.

R5b is the root-cause guard.  Every destructive fixture must clear
`TMUX`, `TMUX_PANE`, `PM_TMUX_SOCKET`, `PM_SHARE_MODE`, `PM_IN_TMUX_SESSION`
and `PM_PROJECT` **before importing pm_core**, use a disposable HOME and
socket directory, and bind every mutation to that socket.  The preserved
smoke script is preserved at `pm/specs/pr-073910f/session_start_smoke.py`,
was rewritten accordingly, and passes without touching the live server.

## Acceptance

1. Unit tests: socket path derivation (deterministic, prefix, long-path
   hash), `$TMUX` parsing/eligibility, `use_env=False`, precise detach
   selection, `list_pm_sessions` parsing, `_find_tui_pane` socket scan.
2. Integration tests with **disposable sockets** (never the live server):
   two servers, each with a session, panes, hooks and an attached client.
   Running `quit_app`/`detach_current_client` and `pm session kill`-style
   cleanup on server A leaves server B's client attached and its sessions,
   panes and hooks intact. Hooks set with `set-hook -g` on A are absent on B.
3. `pm session` in a fresh repo creates `/tmp/pm-sessions/pm-<tag>`, sets
   `PM_TMUX_SOCKET` in panes, and `pm session list` shows it.
4. A legacy default-server session is attached without being migrated or
   killed, with an explanatory note.

## Review iteration (2026-10-28, review-loop b972 i1)

Two gaps found reviewing the first implementation:

1. **`use_env=False` did not reach the default server.** The tmux binary
   honours `$TMUX` when no `-S` is given, so from inside a pm pane
   `pm session list` listed the current private server a second time as
   "(default server)", and legacy detection / `pm session kill`'s legacy
   branch / `pm tui -s <legacy>` could address the wrong server.  Fixed by
   adding `paths.default_socket_path()` and passing it as `-S` wherever the
   default server is meant (`session_exists(use_env=False)`,
   `list_pm_sessions()`, `session_kill`, `helpers._use_tmux_socket(None)`).
   Regression tests added.  Also added the `shared` flag to
   `list_pm_sessions()` rows / `pm session list` (R3.3).
2. **Commands that address a session by name stopped finding private
   sessions outside tmux.** `pm meta`, `pm container build`,
   `pm session home`, `pm pr start`/`review`/`merge` and
   `home_window.refresh_home` resolve the session through
   `_get_pm_session()`; with no ambient `PM_TMUX_SOCKET`/`$TMUX` they
   queried the default server and silently degraded.  `_get_pm_session()`
   now selects the hosting server for the cwd-derived session (skipped
   when already inside a pm session, so the in-pane path is unchanged).

Also made two pre-existing `tests/test_shared_sessions.py` assertions
independent of an ambient `PM_TMUX_SOCKET`: every pm pane now exports it,
so those tests failed when run from inside a pm session.

## Review iteration (2026-10-28, review-loop b972 i2)

The i1 lesson (R4.3: `use_env=False` alone does not reach the default
server) had not been applied to the legacy rollout path, and two smaller
gaps surfaced:

1. **The legacy branch still relied on `$TMUX`.** `_resolve_session_socket()`
   *cleared* `PM_TMUX_SOCKET` for a legacy session, so every later
   `_tmux_cmd()` ran without `-S` and the tmux binary followed `$TMUX`.  Run
   from inside another pm pane that names that session's private server, so
   the legacy session looked missing and `_session_start()` would create a
   duplicate session on the wrong server (reachable when the ambient session
   is not known to this HOME, i.e. exactly the R5b scenario).  It now exports
   `PM_TMUX_SOCKET=str(default_socket_path())`; the returned `socket_path`
   stays `None` so nothing is propagated into the session (R6.1).
2. **`pm session --print-connect` skipped the R5b guard.** It used
   `_get_current_pm_session()` directly while `pm session` used
   `_resolve_start_session_name()`, so the printed command could name a
   foreign session that `pm session` would refuse to adopt.  Both now use
   `_resolve_start_session_name()`.
3. **`pm qa regression -s <session>` accepted a session with no TUI pane.**
   `_find_tui_pane()` deliberately returns the session name when the pane is
   gone (history/frames read files keyed by the session), but the QA runner
   drives that pane, so it now requires a live `pane_id` and errors with the
   session name instead of launching a runner that cannot interact.
4. The private-socket ownership refusal now names the remedy (the socket's
   owner must remove a stale file; a 1777 directory's sticky bit prevents
   anyone else from doing it).

## Review iteration (2026-10-28, review-loop b972 i3)

Three quality/robustness items, no requirement changes:

1. **One source of truth for "which server hosts this session".** The
   private-socket-then-default-server lookup was implemented four times
   (`session._pick_existing_session`, `session_kill`,
   `pm session --print-connect`, `helpers._select_session_socket`) and had
   already diverged once across i1/i2.  New
   `tmux.find_session_server(name) -> (socket_path, is_private)` (R4.3
   semantics: the private socket is probed first, the default server is
   returned by its *explicit* path, `(None, False)` when neither has the
   session) is now the only implementation; all four call sites use it.
   `_resolve_session_socket()`'s legacy detection uses it too, so "no
   private session but one on the default server" is expressed once.
2. **`_find_tui_pane()` no longer leaks env mutations on failure.**  The
   cross-server scan re-points `PM_TMUX_SOCKET` at each server in turn; when
   nothing is found it now restores the ambient value, so a failed lookup
   cannot leave the process addressing an unrelated server.
3. **Integration fixtures respect the AF_UNIX path limit.**  The two
   disposable-server tests now take a `short_sock_dir` fixture that falls back to
   a short `/tmp` directory when the pytest `tmp_path` would exceed the
   ~108-byte socket-path limit (the contract R6.4 already documented).

New tests: `find_session_server` (private wins / explicit default / missing
/ non-pm names never map to a pm socket), `pm session kill` targeting the
private socket, the legacy default socket, and the not-found stale-socket
cleanup, plus the `_find_tui_pane` env-restoration case.

## Review iteration (2026-10-28, review-loop b972 i4)

Verification pass over the whole change set plus test-coverage gaps; no
requirement changes.

1. **The grouped-session detach path had no integration coverage.**  The
   existing disposable-server test attaches its client to the *base*
   session, but `pm session` always attaches to a grouped session
   (`base~N`), so the production shape (TUI pane in the base session,
   client attached to `~1`) was only covered by a mock.  New
   `test_detach_targets_client_of_grouped_session` builds a real
   base + `~1` pair on a disposable socket, attaches a real client to
   `~1`, and asserts `detach_current_client()` removes that client while
   leaving both sessions alive.  Verified manually first; it passes.
2. **`pm session --print-connect`, `pm session list` and the TUI connect
   screen had no tests** (R3.1 / R3.3 / implicit requirement).  Added
   `TestPrintConnect` (private socket command vs. legacy plain attach),
   `TestSessionListCommand` (header, private row, `(default server)`,
   `(shared)` marker, empty listing) and `TestShowConnect` (socket
   command, legacy plain attach, no-session message).
3. **`pm session list` column width is computed from the data** instead of
   a fixed 40 columns, so long session names no longer misalign the
   client count and socket.
4. Removed a dead `try/except (OSError, ValueError)` around a `Path`
   comparison in `socket_path_from_tmux_env` (a `$TMUX` value cannot
   contain a NUL byte) and corrected the `ConnectScreen` docstring, which
   still said "for shared sessions".

Full suite: 4139 passed / 1 skipped.

## Review iteration (2026-10-28, review-loop b972 i5)

Robustness and truthfulness of the detach result; no requirement changes.

1. **`detach_current_client()` claimed a detach that did not happen.**  Both
   the precise (`detach-client -t <tty>`) and the session-level fallback
   (`detach-client -s <session>`) branches discarded the command's exit
   status and returned `True` unconditionally.  `quit_app()` uses the return
   value to decide what to log, so a failed detach was reported as success.
   Both branches now return `False` and log a warning when tmux rejects the
   command (the common real cause is the client disappearing between
   `list-clients` and `detach-client`).
2. **The session-level detach fallback had no unit test.**  Added
   `test_falls_back_to_session_detach` (client attached to a grouped session
   viewing a *different* window, so the per-window match finds nothing) and
   `test_failed_detach_is_not_reported_as_success`.
3. **`list_pm_sessions()` now debug-logs skipped servers**, matching the
   documented edge case ("row is skipped with a debug log"): stale sockets
   (server exited), sockets owned by another user, non-socket entries and
   unreadable entries in the shared socket directory.

Full suite: 4141 passed / 1 skipped.

## Review iteration (2026-10-28, review-loop b972 i6)

Verification pass plus small clarity/coverage fixes; no requirement changes.

1. **The legacy rollout note said "shared default tmux server".**  In pm,
   "shared" means `--global`/`--group`; the legacy session is private and is
   only on the default server because it predates per-session servers.
   Reworded to "was started before per-session tmux servers and still runs
   on the default tmux server", with a comment so the word does not creep
   back.
2. **`pm session kill`'s ambient-candidate wiring had no test.**  The
   `_known_ambient_session()` guard (R5b) and `_pick_existing_session()`
   (R3.2) are unit-tested individually, but nothing asserted the two-line
   wiring in `session_kill`.  Added
   `test_kills_the_ambient_session_when_the_cwd_one_is_absent` (a workdir
   clone kills the session hosting it, on that session's socket) and
   `test_ignores_an_ambient_session_this_home_does_not_know` (a foreign
   HOME's inherited session is never killed).  `_invoke` gained optional
   `ambient` / `hosting_for` knobs for the per-name case.
3. **`list_pm_sessions()` import tidy:** `default_socket_path` is imported
   once beside `SHARED_SOCKET_DIR` instead of inside the `collect()`
   closure on every server.

Also re-verified the full `_session_start` path end-to-end with
`pm/specs/pr-073910f/session_start_smoke.py` on a disposable socket (private
server, session env, global env and hooks all correct; the default server
untouched).

Full suite: 4143 passed / 1 skipped.

## Master integration (2026-10-29)

`origin/master` @ `4a74d88085edffcc300cb21f31777a798d647782` (merge base
`89e3c501`) was merged into this branch, 215 commits.  No textual conflicts.
One **semantic** conflict that a clean auto-merge could not catch:

1. **`_find_tui_pane()` gained a second owner while this PR was open.**
   Master added `_find_live_tui_pane()` / `_live_panes_and_tuis()` and a test
   asserting that `_find_tui_pane("pm-test")` still returns the recorded pane
   even when it is dead, because `pm autostart` reports a stale pidfile from
   it.  This PR had made `_find_tui_pane()` liveness-aware (i2) and required
   the session to exist.  Reconciled by responsibility:
   - explicit-session branch: returns the **recorded** pane with no
     `session_exists`/`pane_exists` gate (new `_recorded_tui_pane()`), so
     master's autostart contract and the i2 "return the session name even
     when it is gone" rule both hold;
   - in-tmux, cwd and cross-server branches: keep the liveness check
     (`_registry_tui_pane()`), because there the answer decides *which
     server* is being addressed;
   - `pm qa regression` was the one pane-*driving* caller still using
     `_find_tui_pane()`; it now uses `_find_live_tui_pane()`, which is
     master's sanctioned live-pane filter.  The i2 requirement (the runner
     drives the pane, so it must be alive) is unchanged — only the mechanism
     moved to the shared helper.
2. **Discovery must degrade when tmux cannot run.**
   `tmux.find_session_server()` now returns `(None, False)` on `OSError`
   (tmux missing/unexecutable) instead of propagating out of
   `_select_session_socket()` and `_find_tui_pane()`.  Master's
   `test_tmux_unavailable_degrades_to_no_live_tui` documents the contract.
3. The preserved smoke script's default-server probe now passes
   `-S str(paths.default_socket_path())` instead of relying on a bare
   `tmux` (the R4.3 lesson: the binary follows `$TMUX` when no `-S` is
   given).

Also committed on top of the merge: the interrupted working tree from the
2026-10-29 test-session-leak restart (shared `_resolve_target_session()` for
`pm session kill`/`mobile`, flag validation before `--print-connect` prints
a command, and their tests).  It was verified byte-identical to the
shepherd's preserved `pr-278/dirty.patch` before being committed.

Validation on the integrated head:
- full suite: **4557 passed / 1 skipped**;
- `pm/specs/pr-073910f/session_start_smoke.py` re-run end-to-end on a
  disposable socket (private server, session env, global env and hooks
  correct; default server untouched).

## Review iteration (2026-10-29, review-loop d1c0 i1)

Verification pass over the integrated head; one user-visible fix, one
consistency tidy, one new test, plus a documented limitation.  No
requirement changes.

1. **The printed connect command for a *legacy* session still depended on
   ambient `$TMUX`.**  Both `pm session --print-connect` and the TUI
   "connect" screen emitted `tmux attach -t <session>` when the session
   lives on the default server.  That is correct from a plain shell and
   from inside the same legacy session, but pasted into another pm pane a
   bare `tmux` follows `$TMUX` and attaches to *that* pane's private
   server — the exact R4.3 failure mode this PR removes everywhere else.
   Both now print `tmux -S <default_socket_path()> attach -t <session>`,
   which is correct from any context (and names the session, because one
   default server can host several legacy pm sessions).  The TUI screen
   now resolves the hosting server through `tmux.find_session_server()`
   instead of probing the private socket itself, so the two surfaces share
   one implementation.  Tests: `TestPrintConnect` and `TestShowConnect`
   updated, plus a new "private session without `PM_TMUX_SOCKET`" case.
2. **`_find_live_tui_pane()` derived the base session name with
   `rsplit("~", 1)`** while every other call site uses
   `pane_registry.base_session_name()` (`split("~")[0]`).  Switched to the
   shared helper for one definition of "grouped session base".
3. **`find_session_server()`'s `OSError` contract had no direct test.**
   The master-integration note relies on it degrading to `(None, False)`
   when tmux cannot run; added `test_tmux_unavailable_degrades_to_none`.
4. **`pm session kill` unlinked the socket of a *live* server.**  When the
   session name is not found (`find_session_server()` → `None`) the branch
   assumed the socket file was stale and removed it.  A live server whose
   base session was killed elsewhere can still host grouped sessions
   (`pm-x~1`), and unlinking its socket strands every client attached to
   it (new clients create a fresh server at the same path).  New
   `tmux.server_alive(socket_path)` (`list-sessions` on that socket, True
   when tmux cannot be run so nothing is deleted on a guess) gates the
   unlink.  Tests: `test_missing_session_keeps_a_live_socket` (mock) and
   `test_server_alive_distinguishes_stale_from_live` (disposable socket).

Known limitation (documented, not fixed — fail-safe by design): R5b's
guard accepts an ambient session only when
`~/.pm/pane-registry/<session>.json` exists in the *current* HOME.  A user
who joined someone else's `--global`/`--group` session has no registry
file in their own HOME, so a plain `pm session` started inside that
session never re-joins it — from a **workdir clone** *or* from the repo
directory itself — and instead creates a separate private session for that
user.  (d1c0 i10 correction: the earlier claim that "from the repo
directory the cwd-derived tag equals the shared tag" was wrong.  The share
mode is part of the tag hash, and `_session_start` clears `PM_SHARE_MODE`
when no `--global`/`--group` flag is passed, so the plain tag is the
*private* one — verified directly: `get_session_tag` for one repo returns
a different hash with and without `PM_SHARE_MODE`.  Re-joining does work
when the joiner repeats the flag — `pm session --global` from the repo
directory recomputes the shared tag and attaches to the shared socket —
and always works via the documented
`pm session --global --dir <owner's repo>/pm`.)  This is the same
trade-off as the i5 note (deleting the registry file while a session is
live makes `pm session` create a separate session); adopting the ambient
session without proof of local ownership is what caused the 2026-10-28
incident.

## Review iteration (2026-10-29, review-loop d1c0 i2)

Verification pass over the integrated head; two robustness fixes of the
same class the previous iterations addressed.  No requirement changes.

1. **Discovery crashed instead of degrading when tmux cannot be run.**
   `find_session_server()` already returns `(None, False)` on `OSError`
   (master's `test_tmux_unavailable_degrades_to_no_live_tui` documents
   the contract), but the rest of the same scan still propagated the
   error: `_find_tui_pane()` called `session_exists()`/`pane_exists()`
   unguarded and `list_pm_sessions()` called `_run()` unguarded, so
   `_find_tui_pane()` and `_find_live_tui_pane()` (no explicit session)
   raised `OSError` on a machine without an executable tmux.  All three
   now degrade — "no session" / "no server" — instead of crashing, which
   is what every caller (`pm autostart`, `pm tui view`, `trigger_tui_reload`,
   `pm pr merge`'s window cleanup) already assumes.
   Test: `test_no_tmux_degrades_to_no_session`.
2. **`pm session kill` could unlink a live server's socket on the legacy
   path.**  d1c0 i1 gated the "session not found" unlink on
   `server_alive()`, but the legacy branch (session killed on the
   *default* server, `on_private` False) still unlinked the private
   socket path whenever *any* file existed there.  A file at that path
   can belong to a live server hosting only grouped sessions of another
   name; unlinking it strands their clients.  The unlink is now
   `on_private or (exists and not server_alive(...))`: the private kill
   still removes the file it just emptied, the legacy kill only removes
   a socket nothing answers on.
   Tests: `test_legacy_kill_keeps_a_live_private_socket`,
   `test_legacy_kill_removes_a_stale_private_socket`.

Re-verified end to end with `pm/specs/pr-073910f/session_start_smoke.py`
on a disposable socket (private server, session env, global env and hooks
correct; default server untouched).

Residual notes unchanged and still non-blocking: the uid ownership check
exists only on `pm session` start (other paths fail closed — a 0600 socket
owned by another user cannot be connected to, so discovery falls back to
the default server); the `/tmp/pm-sessions` literal stays duplicated in
`wrapper._mark_tmux_socket` and `qa_status._tmux_argv` by design (no early
`pm_core` import); pane IDs are no longer globally unique across servers
but every consumer resolves a pane together with its session/socket; R5b
relies on the pane registry file, so deleting it while a session is live
makes `pm session` create a separate session rather than adopt the live
one (fail-safe); the TUI connect screen keeps a bare
`tmux attach -t <name>` as a last resort when no server hosts the session
*and* `PM_TMUX_SOCKET` is unset (unreachable for a live session: every
private session exports the variable and legacy sessions are found by
`find_session_server`).

## Review iteration (2026-10-29, review-loop d1c0 i3)

Verification pass over the integrated head; one reuse cleanup and one
robustness fix in `detach_current_client` (R5).  No requirement changes.

1. **`detach_current_client()` re-implemented two existing helpers.**
   It issued its own `display -t <pane> -p "#{window_id}"` (exactly
   `tmux.pane_window_id`) and its own per-client "is this client's session
   viewing the TUI's window" query (exactly `tmux.sessions_on_window`,
   already used by the review loop, sign-off, watcher and home window).
   Two implementations of "which sessions are looking at this window" is
   the divergence risk the i3 note fixed for
   `_pick_existing_session`/`find_session_server`.  Both helpers now take
   an optional `socket_path` (positional signature unchanged) and
   `detach_current_client` uses them: one window query for the pane, one
   per *session* in the group instead of one per client.  Behaviour is
   unchanged, including the "no resolvable pane window → any session in
   the group counts" fallback.
2. **A non-numeric `client_activity`/`client_created` crashed the quit
   path.**  `int(activity or 0)` raised `ValueError` out of the TUI's
   Ctrl-Q handler.  tmux always prints integers, but `list_pm_sessions()`
   already parses the same kind of field defensively
   (`attached.isdigit()`), so both now share a small `_int_or_zero()`
   helper.

New tests: `test_explicit_socket_is_used_for_every_call` (every tmux
query carries `-S <socket>` when the caller passes `socket_path=`, not
just the detach) and `test_tolerates_non_numeric_client_timestamps`.

Incidental fix (outside this PR's scope, noted on the PR): three
`tests/test_tui_pidfile.py::TestSignalDelivery` tests used PID 1234 as a
stand-in for a live TUI and assumed it was not a zombie.  In a container
where PID 1 does not reap, an unreaped child can land on that PID (it did
here, after tmux panes' `sleep` children were killed), so the tests failed
with "process is a zombie" on an unmodified tree.  They now pin
`is_zombie` to False; zombie handling keeps its own real-process test.

Residual notes unchanged and still non-blocking: the uid ownership check
exists only on `pm session` start (other paths fail closed — a 0600 socket
owned by another user cannot be connected to, so discovery falls back to
the default server); the `/tmp/pm-sessions` literal stays duplicated in
`wrapper._mark_tmux_socket` and `qa_status._tmux_argv` by design (no early
`pm_core` import); pane IDs are no longer globally unique across servers
but every consumer resolves a pane together with its session/socket; R5b
relies on the pane registry file, so deleting it while a session is live
makes `pm session` create a separate session rather than adopt the live
one (fail-safe); the TUI connect screen keeps a bare
`tmux attach -t <name>` as a last resort when no server hosts the session
*and* `PM_TMUX_SOCKET` is unset (unreachable for a live session).

## Review iteration (2026-10-29, review-loop d1c0 i4)

Verification pass over the integrated head; one cross-server correctness
fix, no requirement changes.

1. **`_find_live_tui_pane()` could match a pane id against the wrong
   server.**  Pane ids are only unique *within* one tmux server, and every
   pm session now has its own.  When an explicit `--session` was not found
   on any server (`find_session_server()` → `(None, False)`: a stale
   registry left by a killed session, or a wrong `--session` typed from
   inside another pm session), `_find_tui_pane()` still returned the
   registry's recorded pane id while `PM_TMUX_SOCKET` kept naming the
   *current* session's server.  `_find_live_tui_pane()` then checked that
   id against `list-panes -a` on the wrong server, and because ids restart
   per server (`%5` exists on every one) `pm tui send` / `pm tui view -s
   <stale>` could drive an unrelated pane of another session — the class
   of cross-session damage this PR exists to prevent.
   `_live_panes_and_tuis()` now returns a `pane_id → session_name` map
   instead of a bare id set, and the recorded pane is accepted only when
   the pane's own session (grouped suffix normalised through
   `pane_registry.base_session_name`) is the session being resolved.
   Everything else is unchanged: a live pane in a grouped session still
   counts, and the "fall back to a live `pm _tui` pane in the same
   session" path is untouched.

New tests: `test_pane_id_reused_on_another_server_is_not_returned` and
`test_live_pane_in_a_grouped_session_still_counts`.

Validation: full suite **4567 passed / 1 skipped / 1 failed** (the run
used a scratch `pytest<9` + `markdown` on `PYTHONPATH`, `PATH` without the
push-proxy `git`, and `TMUX`/`TMUX_PANE`/`PM_*` cleared).  The single
failure is environment-only:
`tests/test_hook_events.py::test_installer_writes_standalone_receiver`
returns early because `PM_HOST_HOME` (`/home/matt`) differs from `HOME`
(`/home/pm`); `hook_install.py` is untouched by this PR and that file
passes 20/20 with `PM_HOST_HOME` unset.

Residual notes unchanged and still non-blocking (see the i3 section).

## Review iteration (2026-10-29, review-loop d1c0 i5)

Verification pass over the integrated head; no requirement changes.  The
whole change set was re-read against R1–R7, the suite re-run, and the
preserved smoke script re-executed.

1. **`server_alive()`'s "cannot probe" contract had no test.**  The
   docstring promises that an unprobeable socket (tmux missing or not
   executable) counts as *alive* so `pm session kill` never unlinks on a
   guess — the one branch where being wrong destroys state.  Added
   `TestServerAlive`: `test_live_and_stale_sockets` (returncode 0 vs 1)
   and `test_unprobeable_socket_counts_as_alive` (`_run` raising
   `OSError`).  The disposable-socket integration test still covers the
   real-server case.
2. **The call-time `SHARED_SOCKET_DIR` import in
   `tmux.socket_path_from_tmux_env()` looked like an oversight.**  It is
   load-bearing: a module-level `from … import` would freeze the original
   `Path`, so re-pointing `paths.SHARED_SOCKET_DIR` (tests, and the smoke
   script's disposable socket directory) would no longer be seen.  Now
   commented.
3. **`detach_current_client()`'s failure comment described a caller that
   does not exist** ("…and to decide whether to keep the TUI running
   unattached"); `quit_app` uses the return value only for logging.  The
   comment now names the real cause (the client disappearing between
   `list-clients` and `detach-client`).
4. **The private-socket ownership refusal intentionally precedes legacy
   detection.**  A squatted socket at the private path therefore refuses
   `pm session` even when the user's own session lives on the default
   server and would never connect to that socket.  Kept (fail closed on a
   hostile condition rather than routing around it) and now says so in a
   comment, so it does not read as an ordering accident.

Validation on the integrated head: full suite **4570 passed / 1 skipped**
(`PM_HOST_HOME` unset, so the environment-only `test_installer_writes_standalone_receiver`
early return noted in i4 does not apply; scratch `pytest<9`, `PATH`
without the push-proxy `git`, `TMUX`/`TMUX_PANE`/`PM_*` cleared).
`pm/specs/pr-073910f/session_start_smoke.py` re-run end to end on a
disposable socket: private server created, `PM_TMUX_SOCKET` in the
session env, the global env and the hooks, default server untouched.
No live session, server or shared host configuration was touched.

Residual notes unchanged and still non-blocking (see the i3 section).

## Review iteration (2026-10-29, review-loop d1c0 i6)

Verification pass over the integrated head; no requirement changes.  Three
reuse/coverage items in the TUI-pane discovery code, all in
`pm_core/cli/helpers.py`:

1. **`_find_tui_pane()`'s last-resort scan re-implemented the tmux query
   that `_live_panes_and_tuis()` already performs.**  It ran its own
   `list-panes -a` with a different format string
   (`pane_current_command` *and* `pane_start_command`) and decided "is this
   a TUI pane" by substring-matching the concatenation, while
   `_find_live_tui_pane()` uses `_live_panes_and_tuis()` and its
   `pane_start_command`-only rule.  Two definitions of "a pane running the
   TUI" is the divergence risk the i3 note removed elsewhere.  The scan now
   iterates `_live_panes_and_tuis()` per server, so the rule lives in one
   place.  (The `pane_current_command` half could not match a real
   `pm _tui` pane anyway: the foreground process is `pm`/`python`, not
   `_tui`.)  This also closes a "degrade, never crash" gap: the old call
   was an unguarded `subprocess.run`, so an `OSError` raised after
   `list_pm_sessions()` had succeeded would have escaped `_find_tui_pane()`
   — the contract i2 established for the rest of the scan.
2. **`_recorded_tui_pane()` and `_registry_tui_pane()` each walked the
   registry looking for `role="tui"`.**  Both now share
   `_iter_registry_tui_panes()`; the liveness filter stays only in
   `_registry_tui_pane()`.
3. **`_canonical_session()` was a third copy of "strip the `~N` suffix"**
   (`_canonical_session`, `pane_registry.base_session_name`, and the inline
   `split("~", 1)` in `find_session_server`).  It now delegates to
   `base_session_name()`, matching the i1 change to `_find_live_tui_pane()`.

Also documented (docstring only): `_find_tui_pane()` always returns the
*base* session name, normalising a grouped `pm-x~2` — the registry, pidfile
and history/frames files are all keyed by the base name, so this is what
makes `pm tui frames -s pm-x~2` read the file the TUI actually wrote.

New tests: `test_last_resort_finds_an_unregistered_tui_pane` (the direct
scan's success path, previously untested — only its failure path was) and
`TestSessionMobileServerSelection::test_status_queries_the_hosting_server`
(`pm session mobile`'s `_select_session_socket()` wiring, previously
untested; without it the status query hits the default server and reports a
live private session as "not running").

Validation on the integrated head: full suite **4572 passed / 1 skipped**
(scratch `pytest<9` + `markdown`, `PATH` without the push-proxy `git`,
`TMUX`/`TMUX_PANE`/`PM_*`/`PM_HOST_HOME` cleared).
`pm/specs/pr-073910f/session_start_smoke.py` re-run end to end on a
disposable socket: private server created, `PM_TMUX_SOCKET` in the session
env, the global env and the hooks, default server untouched.

Residual notes unchanged and still non-blocking (see the i3 section).

## Review iteration (2026-10-29, review-loop d1c0 i7)

Verification pass over the integrated head; one correctness fix in session
selection.  No requirement changes.  Share mode is mixed into the session
tag (`get_session_tag`), so a `--global`/`--group` session and the private
session for the same repo are different sessions on different sockets.
Two paths ignored that when reusing the ambient session:

1. **`pm session --global` run from inside a private session attached to
   the private session and shared nothing.**  `_resolve_start_session_name()`
   preferred the ambient session (whose pane registry proves it belongs to
   this HOME) over the share-mode-tagged cwd name, so
   `_resolve_session_socket()` derived the *private* socket, found the
   private session running, and took the attach path — where no
   `set_shared_socket_permissions`/`server-access` grant is made (they only
   run on the create path).  The socket stayed 0600, so nobody could join,
   and the private session was additionally given `window-size=smallest`
   for its group.  Verified end to end on a disposable socket before the
   fix: `pm session --global` created nothing and printed
   `Attaching to session 'pm-…~1'`; after the fix it creates the
   shared-tag session on its own socket and prints
   `Session shared with all users.`
2. **`pm session kill --global` run from inside a private session killed
   the private session.**  `_resolve_target_session()` tried the cwd name
   (share-mode tag, not running) and then the ambient session, which is
   private — so the first *running* candidate was the private session and
   it was killed.  Verified end to end on a disposable socket before the
   fix (`Killed session 'pm-…'`, private server gone); after the fix it
   reports `No session 'pm-…<shared tag>' found` and leaves the private
   session running.

Fix: the ambient session is now only reused when it was created with the
same share mode.  New `tmux.get_session_environment(session, key)` reads a
session variable (``None`` when unset, marked-for-removal, or tmux cannot
be queried); `session._ambient_share_mode()` uses it for `PM_SHARE_MODE`,
which shared sessions record in their session environment at creation —
names cannot be compared for workdir clones, whose git-root hash never
matches the session hosting them.  `_ambient_session_for_share_mode(wanted)`
keeps the ambient candidate only on a same-name fast path or a matching
recorded mode, and both call sites use it:

- `_resolve_start_session_name(shared)` — with `--global`/`--group` the
  ambient must match; without them the ambient session is adopted as it
  is, whatever mode it has, so a plain `pm session` inside a shared
  session still reattaches to it rather than creating a private twin.
  `pm session --print-connect` passes the same flag so the printed command
  names the session that would actually be attached.
- `_resolve_target_session()` — `kill`/`mobile` filter the ambient fallback
  by the mode they run under (`PM_SHARE_MODE`, inherited from the pane when
  no flags are given).  The workdir-clone fallback (R3.2) still works,
  including inside a shared session.

Known limitation (safe direction): a shared session created by an old pm
that did not record `PM_SHARE_MODE` in its session environment is read as
private, so `pm session kill` from a workdir clone inside it reports "no
session" instead of killing it; passing `--global`/`--group` (which uses
the tag-derived cwd name) or running from the repo directory is unaffected.

New tests: `TestGetSessionEnvironment` (value / unset / marked-for-removal
/ tmux missing), an integration check that the variable is read from the
named server, `TestStartSessionName::test_shared_start_never_adopts_a_private_ambient_session`
and `::test_shared_start_reuses_a_shared_ambient_session`,
`TestSessionKillServerSelection::test_shared_kill_never_falls_back_to_a_private_ambient`
and `::test_shared_kill_still_falls_back_to_a_shared_ambient`,
`TestResolveTargetSession::test_ambient_session_with_a_different_share_mode_is_ignored`
and `::test_ambient_share_mode_reads_the_session_environment`.  The kill
unit tests now pin `_ambient_share_mode` so no unit test can query a real
tmux server.

Validation: see the PR note for this iteration (full suite + disposable
smoke test, no live session or server touched).

## Review iteration (2026-10-29, review-loop d1c0 i8)

Verification pass over the integrated head; no requirement changes.  Two
correctness/cleanup items, both of the class the earlier iterations fixed:

1. **`pm session kill` unlinked a live private server's socket.**  d1c0 i1
   gated the *not-found* unlink on `server_alive()` and i2 applied the same
   rule to the *legacy* branch, but the branch that kills a session found
   on its own private socket still unlinked unconditionally
   (`on_private or …`).  The kill removes this session's base + grouped
   sessions, but the server can survive it — a session on that socket that
   is not part of the group (a stray or hand-made one) or a `kill-session`
   that failed — and unlinking a live server's socket strands every client
   attached to it.  The unlink now follows the same rule in all branches:
   remove the file only when no server answers on it.  The normal case is
   unchanged (the server exits with its last session, the file is left
   behind and removed).  Tests:
   `test_private_kill_keeps_a_socket_a_server_still_answers_on` and
   `test_private_kill_removes_the_emptied_socket`.
2. **Dead branch in `_find_live_tui_pane()`.**  The master-integration
   reconciliation left a `sess = session` fallback with a comment saying
   `_find_tui_pane` "only consults the registry when a session is given"
   and returns `(None, None)` for a session with no `tui` entry.  That has
   not been true since the same change made the explicit-session branch
   return the base name unconditionally, so the fallback was unreachable
   and the comment misleading.  Removed; the live-pane scan below it is
   what resolves an explicit session with no recorded pane, and the stale
   test docstring that repeated the claim is corrected.
3. Corrected the `_resolve_start_session_name()` docstring (and the i7
   section above): a plain `pm session` inside a shared session reattaches
   because the ambient *session* is adopted as-is, not because its share
   mode is inherited (`_session_start` clears `PM_SHARE_MODE`).
4. Coverage for R4.4, which was only checked as a source literal: new
   `TestQaStatusSocketRouting` imports `qa_status` (with
   `logging.basicConfig` patched out, since importing it installs a file
   logger) and asserts `_switch_to_window`/`_find_attached_session` build
   `tmux -S <PM_TMUX_SOCKET>` argv, fall back to a `$TMUX` value only when
   it names a pm socket, and leave an ordinary tmux session alone.

Residual notes unchanged and still non-blocking (see the i3 section).  One
more, inert today: `_session_start`'s `is_shared` comes from the flags, so
an ambient shared session adopted by a plain `pm session` is still treated
as private for the socket-ownership check.  That is currently unreachable
for a joining user (R5b requires a local pane registry, which a joiner
does not have, so they never adopt the shared session) and harmless for
the owner (they own the socket), so the guard is left as it is.

## Review iteration (2026-10-29, review-loop d1c0 i9)

Verification pass over the integrated head; no requirement changes.  One
test gap in the PR's central requirement, one stale user-facing string, one
"degrade, never crash" hole in discovery, one import tidy.

1. **R1 had no automated coverage of the create path.**  Everything in the
   suite asserted pieces (`_resolve_session_socket` exports the path,
   `set_environment`/`set_global_environment` are called, …); nothing ran
   `_session_start` and checked the result.  The end-to-end check lived
   only in `pm/specs/pr-073910f/session_start_smoke.py`, which is not run
   by the suite.  New `TestSessionStartCreatesPrivateServer` runs
   `_session_start` against a disposable socket with an isolated `HOME`
   (patched `SHARED_SOCKET_DIR` and `default_socket_path`, hooks install
   and `attach` stubbed, the TUI pane replaced by `sleep`), then asserts:
   the session and its `~1` grouped session exist on the deterministic
   private socket; `create_session` received that socket and a
   `PM_TMUX_SOCKET=<socket> pm _tui` command; the variable is exported in
   the process, in the session environment and in the server's global
   environment; the `after-kill-pane` hook is installed there; the client
   attaches to `pm-…~1` on that socket; and nothing was created on the
   default server (which is itself a disposable path, never the real one).
2. **`_find_tui_pane()`'s in-tmux branch was the last unguarded probe.**
   d1c0 i2 made the rest of the scan degrade when tmux cannot be run, but
   `tmux_mod.get_session_name()` still raised `OSError` out of
   `pm tui view` / `pm autostart` when `$TMUX` was set and no tmux binary
   was available (a forwarded pane environment, or a container without
   tmux).  It now falls through to the cwd/cross-server branches.  Test:
   `test_tmux_missing_inside_a_pane_degrades_to_no_session`.
3. **The TUI help still said "Show shared connect command"** although the
   `C` screen now shows the connect command for every session (the i4
   iteration fixed the docstring but not this user-facing row).
4. `pm session mobile`'s `_select_session_socket` import moved from inside
   the command to the module-level `pm_core.cli.helpers` import block,
   matching the rest of the module (no circular-import constraint).

Validation: full suite re-run after these edits; no live session, server
or shared host configuration was touched (every fixture used a disposable
socket and an isolated `HOME`).

Residual notes unchanged and still non-blocking (see the i3 section).

## Review iteration (2026-10-29, review-loop d1c0 i10)

Verification pass over the integrated head; no requirement changes.  One
fail-closed hardening in the private-socket ownership check and one
documentation correction.

1. **The private-socket ownership check followed symlinks.**  The socket
   directory is world-writable (1777, sticky), so another local user can
   create `pm-<tag>` there.  `Path(socket_path).stat()` resolves a link, so
   a *dangling* symlink raised `OSError`, the check fell back to
   `owner = os.getuid()`, and the squatted path was accepted — tmux would
   then bind a server socket at the attacker-chosen target path *(b48f i8
   correction: it does not — see the review-loop b48f i8 section; the
   refusal is still right, for the connect-time reason recorded there)*.
   The check now uses `lstat()`, i.e. it inspects the directory entry
   itself: a link
   planted by another user reports *their* uid and is refused.  A real
   socket owned by us behaves exactly as before.  Test:
   `test_refuses_a_symlink_planted_at_the_socket_path` (verified to fail
   with `stat()` and pass with `lstat()`).
2. **The documented joiner limitation was wrong about the repo
   directory.**  The i1 section claimed a collaborator who joined a
   `--global`/`--group` session can still re-join from the repo directory
   because "the cwd-derived tag equals the shared tag".  It does not: the
   share mode is mixed into the tag hash, and `_session_start` clears
   `PM_SHARE_MODE` when no `--global`/`--group` flag is passed, so the
   plain tag is the *private* one (verified directly: `get_session_tag`
   for one repo returns a different hash with and without
   `PM_SHARE_MODE`).  A plain `pm session` therefore starts a separate
   private session for the joiner from any directory; re-joining works
   when the joiner repeats the flag (`pm session --global`, which
   recomputes the shared tag) or uses the documented `--dir` form.  The
   behaviour is unchanged and remains the fail-safe trade-off; only the
   claim was corrected.

Validation on the integrated head: full suite **4591 passed / 1 skipped**
after these edits (4590 + the new symlink test; scratch `pytest<9` +
`markdown` on `PYTHONPATH`, `PATH` without the push-proxy `git`,
`TMUX`/`TMUX_PANE`/`PM_*`/`PM_HOST_HOME` cleared).  The new test was
checked in both directions (fails with `stat()`, passes with `lstat()`),
and `pm/specs/pr-073910f/session_start_smoke.py` was re-run after the
edits (disposable socket, isolated `HOME`, `TMUX_TMPDIR` on a scratch
dir): private server created, `PM_TMUX_SOCKET` in the session env, the
global env and the hooks, default server untouched.  `pm session list` was
also re-verified end to end against disposable private/shared/legacy
servers (private + `(shared)` + `(default server)` rows, stale non-socket
entry skipped).  No live session, server or shared host configuration was
touched.

Residual notes unchanged and still non-blocking (see the i3 section).

## Review iteration (2026-10-29, review-loop d1c0 i11)

Verification pass over the integrated head; no requirement changes.  Two
"degrade, never crash" / truthful-state fixes, both in code that runs on
the paths this PR exists to protect:

1. **`_find_tui_pane()`'s failure restore used a value it had already
   overwritten.**  The cross-server scan re-points `PM_TMUX_SOCKET` at
   each server it probes and restores the "ambient" value when nothing is
   found — but that value was read *after* the cwd branch had already
   called `_select_session_socket()`, so when the cwd session was running
   with no live TUI pane the "restore" put the process back on the cwd
   session's server rather than the one it came in with.  The value is
   now captured on entry, before any branch can select a server, so the
   documented contract ("a failed lookup leaves the process where it
   was") actually holds.  Test:
   `test_failed_lookup_restores_the_original_socket` (verified to fail
   with the late capture: it restored the cwd session's socket).
2. **`detach_current_client()` could raise out of the TUI's quit
   handler.**  Every other tmux probe in this change degrades when tmux
   cannot be run (i2/i6/i9), but `detach_current_client()` called
   `pane_window_id()`/`_run()` unguarded, so an `OSError` from a missing
   or unexecutable tmux (a container, or a forwarded `$TMUX` without the
   binary) propagated into `quit_app()`.  The body moved to
   `_detach_current_client()` and the public function now logs a warning
   and returns `False`, i.e. "nothing to detach".  Test:
   `test_tmux_missing_does_not_crash_the_quit_path` (verified to fail
   with the guard removed).

Validation on the integrated head: full suite re-run after these edits
(see the PR note for this iteration).  No live session, server or shared
host configuration was touched; both new tests are unit-level and touch no
tmux server.

Residual notes unchanged and still non-blocking (see the i3 section).

## Review iteration (2026-10-29, review-loop d1c0 i12)

Verification pass over the integrated head; no requirement changes.  Three
fail-closed/consistency items, all in code that guards the isolation
boundary:

1. **`ensure_socket_dir()` could accept a socket directory that is not
   sticky.**  The d1c0-era `try: chmod(0o1777) except OSError: pass` was
   added so a directory another user already created (the normal 1777
   case) is usable, but it swallowed *every* failure.  If the directory is
   world-writable without the sticky bit, any local user can unlink or
   replace another user's socket — and the uid check in `pm session` start
   cannot prevent that, because it runs once, before tmux binds the
   socket.  The failure path now re-checks the mode and raises unless the
   sticky bit is set, restoring the fail-closed behaviour of the original
   unconditional `chmod` while still allowing a legitimate 1777 directory
   owned by someone else.  Tests:
   `test_tolerates_a_sticky_dir_it_does_not_own` and
   `test_refuses_a_non_sticky_dir_it_cannot_fix`.
2. **The TUI connect screen lost the `-t <session>` for a legacy session
   whose socket was already in the environment.**  d1c0 i1 made
   `show_connect()` name the session when it lives on the default server,
   but only on the branch where `PM_TMUX_SOCKET` is unset.  The rollout
   path (`_resolve_session_socket`'s legacy branch) exports the *default*
   server's socket, so a TUI restarted into a legacy session takes the
   other branch and printed `tmux -S /tmp/tmux-<uid>/default attach` with
   no `-t` — ambiguous whenever more than one legacy pm session is on that
   server.  The env path now applies the same rule.  Test:
   `test_legacy_session_with_the_default_socket_in_the_env`.
3. **`list_pm_sessions()` followed symlinks in the world-writable socket
   directory.**  It used `Path.is_socket()` (a `stat`, so symlinks are
   resolved) and `Path.stat()` for the shared/private mode probe, while
   d1c0 i10 hardened the `pm session` ownership check to `lstat` for
   exactly this reason.  A link another user plants at `pm-<tag>` could
   therefore be listed as one of our servers, with its target's mode
   reported.  Both now use `lstat`, so a link is skipped like any other
   non-socket entry.  Test:
   `test_skips_a_symlink_planted_in_the_socket_dir` (verified to fail with
   `is_socket()`: the planted link was listed).

Validation on the integrated head: full suite **4597 passed / 1 skipped**
(4593 + the four new tests; scratch `pytest<9` + `markdown` on
`PYTHONPATH`, `PATH` without the push-proxy `git`,
`TMUX`/`TMUX_PANE`/`PM_*`/`PM_HOST_HOME` cleared).
`pm/specs/pr-073910f/session_start_smoke.py` re-run end to end on a
disposable socket with `TMUX_TMPDIR` on a scratch dir: private server
created, `PM_TMUX_SOCKET` in the session env, the global env and the
hooks, default server untouched.  No live session, server or shared host
configuration was touched.

Residual notes unchanged and still non-blocking (see the i3 section).

## Review iteration (2026-10-29, review-loop 7af7 i1)

Verification pass over the integrated head; no requirement changes.  One
cross-session hazard in TUI-pane discovery — the failure mode this PR
exists to remove, reintroduced by the R3.4 fallback:

1. **The cross-server fallback in `_find_tui_pane()` could resolve to a
   *different* pm session's TUI.**  R3.4 says the scan falls back to "all
   pm servers for a live TUI pane", and that is right for a plain shell
   (`pm tui view` with no session anywhere).  But the scan was unconditional,
   so when the process *was* inside a pm session whose registered TUI pane
   was gone (heal testing, a respawn that did not update the registry), the
   loop walked `/tmp/pm-sessions` in sorted order and returned the first
   server's live `pm _tui` pane.  Pane ids are only unique per server and
   `pm tui send` delivers keys unscoped, so `pm tui send g` from inside
   `pm-a` could drive `pm-b`'s TUI — the cross-session damage this change
   exists to prevent.  Before this PR the same fallback ran `list-panes -a`
   on the *ambient* server, so it could only ever find the current
   session's pane; scanning per-socket servers silently widened it.
   `_find_tui_pane()` now records the session its branches identified (the
   in-tmux pm session, else a running cwd-derived session) and scopes both
   the registry scan and the last-resort `pm _tui` scan to that session's
   server.  With no session identified (a plain shell) every server is
   still scanned, so `pm tui view` from outside pm keeps working.  (703c i4
   later narrowed that to the servers the current user owns; see R3.4.)
   Test:
   `test_fallback_never_crosses_to_another_pm_session` (verified to fail
   without the scope: it returned `pm-b`'s pane).

Validation on the integrated head: full suite re-run after the edit (see
the PR note for this iteration).  No live session, server or shared host
configuration was touched; the new test is unit-level.

Residual notes unchanged and still non-blocking (see the i3 section).

## Review iteration (2026-10-29, review-loop 7af7 i2)

Verification pass over the integrated head; no requirement changes.  Three
items, all of the class the previous iterations fixed:

1. **The i1 scope was per *server*, but a server is not a session.**  The
   last-resort `pm _tui` scan in `_find_tui_pane()` was scoped to the
   identified session's server, and then returned the first `pm _tui` pane
   it found there.  That is exact for a private server (one session per
   server), but the legacy default server hosts *every* pre-isolation pm
   session: from inside legacy `pm-a` with its registry entry gone, the
   scan could return `pm-b`'s live TUI, and `pm tui send` delivers keys
   unscoped — the same cross-session damage i1 removed, one level down.
   The pane's base session is now compared with the row's session
   (`info["name"]`), which is exact in both cases (with no session
   identified, every row is one base session).  Test:
   `test_last_resort_never_crosses_sessions_on_one_server` (verified to
   fail without the comparison: it returned `pm-b`'s pane).
2. **`ensure_socket_dir()`'s fail-closed refusal surfaced as a traceback.**
   The d1c0 i12 guard raises when the shared directory is world-writable
   without the sticky bit (another user could unlink our socket, which the
   uid check cannot prevent because it runs once, before tmux binds).
   `_resolve_session_socket()` now reports it as an actionable message
   (which directory, and that it must be owned by the user or be 1777)
   instead of letting the `OSError` escape.  Test:
   `test_unusable_socket_dir_reports_the_fix`.
3. **`_get_current_pm_session()` crashed when tmux cannot be run.**  Every
   other probe in the module degrades (d1c0 i2/i6/i9/i11), but this one
   called `get_session_name()` unguarded; with `$TMUX` set and no tmux
   binary (a forwarded pane environment, or a container without tmux) it
   raised `OSError` out of `pm session mobile` and `pm session
   --print-connect` (both of which now reach it through the ambient
   session lookup).  It returns `None` ("not inside a pm session") now,
   and uses `pane_registry.base_session_name()` for the `~N` strip, like
   the other call sites i6 unified.  Test:
   `test_tmux_missing_inside_a_pane_degrades_to_no_session`.

Validation on the integrated head: full suite re-run after these edits
(see the PR note for this iteration); `pm/specs/pr-073910f/session_start_smoke.py`
re-run end to end on a disposable socket (`TMUX_TMPDIR` on a scratch dir):
private server created, `PM_TMUX_SOCKET` in the session env, the global
env and the hooks, default server untouched; `pm session list` re-verified
end to end against disposable private/shared servers (private row,
`(shared)` marker, grouped `~1` collapsed, non-socket/stale entries
skipped).  No live session, server or shared host configuration was
touched.

Residual notes unchanged and still non-blocking (see the i3 section).

## Review iteration (2026-10-29, review-loop 7af7 i3)

Verification pass over the integrated head; no requirement changes.  One
cross-session hazard in TUI-pane discovery — the same failure mode i1/i2
closed for the fallback scan, still open one branch earlier:

1. **`_find_tui_pane()`'s cwd branch could resolve to a *different* pm
   session.**  The branch "try the session matching the current directory"
   ran unconditionally, and its result was returned even when the in-tmux
   branch had already identified the ambient pm session.  From inside
   `pm-a` with its TUI pane unregistered (heal testing, a respawn that did
   not update the registry), a cwd inside another project whose session
   `pm-b` was running resolved to *`pm-b`'s* pane and re-pointed
   `PM_TMUX_SOCKET` at `pm-b`'s server.  `pm tui send`/`view`/`restart`
   deliver keys to a bare pane id and `pm pr merge` kills windows by
   session name, so the consequence is the cross-session damage this
   change exists to prevent.  The cwd lookup now runs only when nothing
   identified a session, i.e. from a plain shell — which is what it was
   for (`pm tui view` from outside a pm session keeps working, and a pm
   pane whose cwd is the session's own repo is unaffected because the
   ambient branch already answered).  Test:
   `test_cwd_session_does_not_override_the_ambient_one` (verified to fail
   without the guard: it returned `pm-b`'s `%9` and selected
   `/tmp/pm-sessions/pm-b`).
2. Corrected the `_find_tui_pane()` docstring, which claimed it returns
   `(None, None)` only "when no session can be identified at all": the
   implicit path also returns `(None, None)` when a session was identified
   but no live TUI pane was found (the explicit-`--session` path is the one
   that always returns the name).

Validation on the integrated head: full suite re-run after these edits
(see the PR note for this iteration); `pm/specs/pr-073910f/session_start_smoke.py`
re-run end to end on a disposable socket (`TMUX_TMPDIR` on a scratch dir):
private server created, `PM_TMUX_SOCKET` in the session env, the global
env and the hooks, default server untouched.  No live session, server or
shared host configuration was touched; the new test is unit-level and
binds no tmux server.

Residual notes unchanged and still non-blocking (see the i3 section of this
document).

## Review iteration (2026-10-29, review-loop 0e4c i1)

Verification pass over the integrated head; no requirement changes.  The
change set was re-read against R1–R7, the suite re-run, and the review
looked specifically for behaviour the suite does not assert.

1. **`pm qa regression`'s dead-pane guard had no test.**  The b972 i2
   change made the runner require a *live* TUI pane (`_find_live_tui_pane`
   reports the session name even when the recorded pane is gone, because
   history/frames callers need that), but nothing asserted either the
   refusal or the launch path.  Added to `tests/test_cli_qa.py`:
   `test_qa_regression_reports_a_missing_session`,
   `test_qa_regression_requires_a_live_tui_pane` (verified to fail with
   the guard removed: the command launched a runner against a dead pane)
   and `test_qa_regression_launches_with_the_live_pane` (the prompt names
   the session and the pane the runner must drive).

Nothing else surfaced: the socket derivation, the default-server
addressing rule (R4.3), the discovery scoping fixes (7af7 i1–i3), the
detach selection (R5), the rollout path (R6) and the fail-closed socket
directory/ownership checks (d1c0 i10/i12) all match the spec, and every
other new helper already has direct coverage.

Cross-PR, out of scope here: `pane_registry.base_session_name()` (now the
single "grouped session base" definition, which this PR switched three
more call sites to) truncates at the first `~`, so a repo directory whose
name contains `~` yields a session name the registry/pidfile/capture
lookups then disagree on.  Pre-existing (the previous `rsplit` call site
was wrong for base-session panes too) and filed as **pr-6de8207**; the fix
belongs in `get_session_tag()` (sanitise the tag), not in the callers.

Validation on the integrated head: full suite re-run after the edit (see
the PR note for this iteration).  No live session, server or shared host
configuration was touched; the new tests are unit-level and bind no tmux
server.

Residual notes unchanged and still non-blocking (see the i3 section of this
document).

## QA scenario 6 fixes (2026-10-29)

QA scenario 6 ("Concurrent starts, kills, lists and attaches") found two
defects against its THEN bullets; both are fixed in the same commit as this
section (`qa: converge concurrent session starts and make session kill
match exactly`).  No requirement changes.

1. **Paired simultaneous `pm session` starts crashed the loser.**  Both
   invocations pass the caller's `session_exists` check and then race into
   `new-session`; the loser gets "duplicate session" and died with an
   unhandled `CalledProcessError` *before* the attach (the grouped session
   `new-session -t pm-x -s pm-x~1` has the same race on the attach path).
   `create_session` / `create_grouped_session` now treat the failure as a
   lost race only when the exact name exists afterwards
   (`has-session -t =name`) and converge on the winner's session; any other
   failure is still re-raised.  Tests: `TestConcurrentCreate` (converge and
   re-raise for both create paths).
2. **`pm session kill` destroyed a live grouped session.**  tmux resolves a
   bare `-t pm-x` as a *prefix*, so `has-session -t pm-x` also matched a
   surviving `pm-x~1`: with the base already killed elsewhere, the kill
   reported "Killed session 'pm-x'.", killed the grouped session (detaching
   its client) and unlinked the live server's socket.  New
   `tmux.find_exact_session_server()` (target `=name`) is used by the
   destructive path only; `find_session_server` keeps prefix matching, so
   `pm tui view -s pm-x` still reaches the group's TUI after the base is
   gone (verified both ways at runtime).  Tests: the prefix/exact cases in
   `TestFindSessionServer`, plus
   `TestSessionKillServerSelection::test_kill_uses_the_exact_matcher_not_prefix`
   — the other kill tests stub both resolvers identically, so they cannot
   catch a revert of the kill path to prefix matching.

Residual, filed as **pr-ea98f71** and out of scope here: a concurrent start
can still false-positive the "TUI pane missing — respawning..." heal path,
because the create path clears the pane registry before `new-session`; the
final state still converges.

Validation: full suite 4612 passed / 1 skipped on the QA-fix commit
(before the review-loop edits below).

## Review iteration (2026-10-29, review-loop 3cc7 i1)

Verification pass over the QA scenario 6 fix commit; no requirement
changes.  One test gap in that fix, one documentation gap, and one
discovery robustness gap of the class the earlier iterations closed.

1. **The kill path's exact-match wiring had no test.**  The QA fix made
   `pm session kill` resolve the session through
   `find_exact_session_server`, but
   `TestSessionKillServerSelection._invoke` stubs `find_session_server`
   and `find_exact_session_server` with the *same* resolver, so a revert
   to prefix matching would have passed every kill test.  New
   `test_kill_uses_the_exact_matcher_not_prefix` makes the two disagree
   the way tmux does (prefix finds the surviving `pm-x~1`, exact finds
   nothing) and asserts `No session ... found.`, no `kill-session` calls
   and the live server's socket left in place; verified to fail with
   `session_kill` reverted to `find_session_server`.
2. **`impl.md` had no record of the QA scenario 6 fixes.**  Added the
   "QA scenario 6 fixes" section above and extended R3.2 with the
   exact-match rule.
3. **The last-resort TUI scan could not see a server whose socket file is
   gone.**  `_find_tui_pane` scopes the scan to the identified session's
   server through `list_pm_sessions()`, which enumerates socket *files*.
   A live server can outlive an unlinked socket (an old pm's kill, or a
   cleaned `/tmp/pm-sessions`), and when that session's registry entry is
   also gone — the one case the last-resort scan exists for — discovery
   returned `(None, None)` although `pm tui view` from inside the session
   used to find the pane (the pre-change scan ran on the ambient server).
   The in-tmux branch now records `resolve_ambient_socket()` and, when
   `list_pm_sessions()` does not report the identified session, scans that
   server directly.  Test:
   `test_last_resort_scans_the_ambient_server_without_a_socket_file`
   (verified to fail without the fallback).

Validation on the integrated head: full suite **4614 passed / 1 skipped**
(4612 + the two new tests).  `pm/specs/pr-073910f/session_start_smoke.py`
was re-run end to end on a disposable socket with `TMUX_TMPDIR` on a
scratch dir (private server, session env, global env and hooks correct;
default server untouched).  No live session, server or shared host
configuration was touched; every new test is unit-level and binds no tmux
server.

## Master integration (2026-10-31, origin/master eaf3372e / #249)

The PR conflicted with master (GitHub reported the conflict once #249
merged).  `origin/master` @ `eaf3372e` (merge base `4a74d880`, 544 commits,
113 files) was merged into this branch.  Three files conflicted:

1. **`pm/project.yaml`** — resolved with pm's own `store.merge_3way` over
   the index stages, master as *ours* and the branch as *theirs* (theirs
   wins true conflicts, so the branch's PR entry and notes win where both
   changed while master's newer state wins everywhere the branch left it
   alone).  Validated with `store.load(validate=True)` plus an id/notes
   superset check: every PR/plan id from either side appears exactly once
   and all of `pr-073910f`'s notes are present.
2. **`pm_core/tmux.py`** — both sides added different helpers at the same
   two spots.  Kept both: master's `TmuxCommandError` and `session_group`
   (the S118/S121/S124 group resolution) alongside the branch's
   `socket_path_from_tmux_env` / `resolve_ambient_socket` /
   `export_ambient_socket`, `server_alive`,
   `find_session_server` / `find_exact_session_server` and the
   `use_env=False` default-server addressing (R4.3).
3. **`pm_core/cli/helpers.py`** — semantic reconciliation:
   - `_get_current_pm_session()` keeps the branch's `OSError` degrade
     (tmux missing while `$TMUX` is set → "not inside a pm session") but
     resolves the session through master's
     `pane_registry.pm_session_name()` instead of a local `~` strip, so a
     user's own grouped view under any name (S118/S121/S124) still
     resolves to its pm session.
   - `_get_pm_session()` keeps master's `-C`/`PM_PROJECT` project override
     **and** the branch's hosting-server selection on both paths: the
     override-derived session also gets `_select_session_socket()`,
     because a command run outside tmux must address the private server
     or it concludes a live session is gone (R3.6).

Also reconciled: master's new
`tests/test_cli_helpers.py::TestPmSessionOutsidePmTmux` stubbed
`session_exists` without `use_env`, while `find_session_server()` probes
the default server with `session_exists(target, use_env=False)`; the
merged tree raised `TypeError` instead of resolving the session.  The stub
now accepts `use_env`.

No other semantic conflict surfaced.  Master's `pm_session_name` rollouts
in `session.py` (hooks, popups, pickers) and in
`tmux.current_or_base_session` are independent of the socket-isolation
code, and the branch's `_find_tui_pane` rewrite replaced master's older
version in full (master did not touch that function).

Validation on the integrated head (`21ab6ddc`):
- full suite **5325 passed / 1 skipped / 0 failed / 0 errors** (437 s;
  scratch `pytest<9` + `markdown`, `PATH` without the push-proxy `git`,
  `TMUX`/`TMUX_PANE`/`PM_*`/`PM_HOST_HOME` cleared); log at
  `/pm-captures/pr-073910f-integration-eaf3372e/full-suite.log`;
- `pm/specs/pr-073910f/session_start_smoke.py` re-run end to end on a
  disposable socket with `TMUX_TMPDIR` on a scratch dir: private server
  created, `PM_TMUX_SOCKET` in the session env, the global env and the
  hooks, default server untouched;
- `pm session list` in this container (read-only): "No pm sessions
  found.", no socket directory created.

Every earlier QA PASS result predates this merge and is **stale**; this PR
needs a fresh review/QA/sign-off sequence.

## Review iteration (2026-10-31, review-loop 703c i1)

First review pass over the integrated head after the `eaf3372e` (#249)
merge.  No requirement changes.  One cross-session hazard in TUI-pane
discovery, of exactly the class this change exists to remove:

1. **`_find_tui_pane()`'s current-pane branch missed a user's own grouped
   view of a pm session.**  The branch took `tmux_mod.get_session_name()`
   and accepted it only when the raw name started with `pm-`.  But tmux
   reports the *view's* name for a pane in a shared window while that
   view's client is the most recently active one (verified on tmux 3.4:
   after `tmux new-session -d -t pm-base -s myview`,
   `display-message -t %0 -p '#{session_name}'` returns `myview`, while
   `#{session_group}` for that view is `pm-base`), and S118/S121/S124
   explicitly allow such a view to be named anything — including
   `pm-laptop`, which is *not* the session.  With the raw test, the
   ambient session was not identified and the lookup fell through to the
   cwd branch (useless from a workdir clone) and then to the *unscoped*
   cross-server scan, which returns the first server's live registered TUI
   pane: `pm tui send` / `view` / `restart` from inside pm-a could drive
   pm-b's TUI — the cross-session damage 7af7 i1/i2/i3 closed for the
   other branches, still open here.  The branch now resolves through
   `pane_registry.pm_session_name()` (the same resolution
   `_get_current_pm_session()` uses), so a view — whatever its name —
   identifies its pm session, and a view named `pm-laptop` no longer
   shadows a different session of that name.  Non-pm tmux sessions are
   unchanged (`session_group` is empty, the name still fails the `pm-`
   test) and the `OSError` degrade still covers a missing tmux (the
   `session_group` query is inside the same `try`).  Test:
   `test_own_grouped_view_resolves_the_ambient_session` (verified to fail
   without the resolution: it returned pm-b's `%1`).

Also checked and left alone: `pm_core/cli/guide.py::_in_pm_tmux_session()`
has the same raw `pm-` prefix test, but it only decides whether `pm guide`
runs the guided flow, never which server or pane is addressed, so it is
not a cross-session hazard (pre-existing, out of scope).

Validation on the integrated head: full suite re-run after the edit (see
the PR note for this iteration); no live session, server or shared host
configuration was touched, and the new test is unit-level (it binds no
tmux server).

## Review iteration (2026-10-31, review-loop 703c i2)

Verification pass over the integrated head; no requirement changes.  One
gap in the fail-closed socket-directory guard (d1c0 i12) — the only
finding this iteration:

1. **`ensure_socket_dir()` accepted a sticky directory it cannot write
   to.**  The d1c0 i12 hardening re-checked the mode after a failed
   `chmod`, but only for the *sticky* bit, while its own comment says the
   directory "is fine only when it already has the mode we need" (1777).
   A root-owned `1755 /tmp/pm-sessions` — sticky, but not world-writable —
   therefore passed the guard, and the failure surfaced much later as an
   opaque "couldn't create socket" from tmux instead of the actionable
   message `pm session` prints for this refusal.  The re-check now
   requires `S_ISVTX` **and** `S_IWOTH`, matching the contract: without
   the sticky bit another user can unlink our socket, and without
   world-write we cannot create one.  Test:
   `test_refuses_a_sticky_dir_it_cannot_write` (verified to fail without
   the world-write test).  The existing 1777-and-0777 cases are
   unchanged.

Nothing else surfaced.  The i1 grouped-view resolution in
`_find_tui_pane()`, the socket derivation and default-server addressing
(R4.3), the discovery scoping (7af7 i1–i3, 3cc7 i1), the precise detach
(R5), the rollout path (R6) and the socket-directory/ownership checks
(d1c0 i10/i12) all match the spec, and every new helper has direct
coverage.

Re-checked and left alone (unchanged from i1's documented call):
`pm_core/cli/guide.py::_in_pm_tmux_session()` keeps its raw ``pm-``
prefix test.  It only decides whether `pm guide` execs in place or
launches a new pane; it never selects a server or a pane, so a user's
own grouped view there costs a spare pane, not cross-session damage.

Validation on the integrated head: full suite re-run after the edit (see
the PR note for this iteration); no live session, server or shared host
configuration was touched, and the new test is unit-level (it binds no
tmux server).

## Review iteration (2026-10-31, review-loop 703c i3)

Verification pass over the integrated head; no requirement changes.  One
gap in the precise-detach resolution (R5.2), plus a spec correction:

1. **`detach_current_client()` derived the base session by splitting the
   name at `~`, which a user's own grouped view defeats.**  tmux reports
   the most recently active view's name for a pane in a shared window
   (verified on this machine: with `pm-x`, `pm-x~1` and `myview` all
   grouped, `display-message -t <base pane> '#{session_name}'` returned
   `myview` while `'#{session_group}'` returned `pm-x`), and S118/S121/S124
   let that view be named anything.  `session.split("~", 1)[0]` therefore
   took `myview` for the base, so `list_grouped_sessions()` returned
   nothing and `sessions_on_window()` covered only the view itself: the
   candidate set collapsed to the view's client, and Ctrl-Q could detach
   a *different* client of the same pm session than the one that pressed
   it (the client attached to `pm-x~1` and viewing the TUI window stayed
   attached while the view's client was dropped).  This is the same
   resolution 703c i1 fixed in `_find_tui_pane()` and the one
   `pane_registry.pm_session_name()`/`current_or_base_session()` already
   use.  `tmux.session_group()` now takes an optional `socket_path` (the
   rest of the group helpers already did) and `_detach_current_client()`
   derives the base through it, falling back to the `~` split when the
   session is ungrouped (or the query fails).  The candidate set is then
   the base + `base~N` that R5.2 defines.  Test:
   `test_resolves_the_pm_base_through_the_session_group` (verified to fail
   without the fix: it detached the view's client `/dev/pts/9` instead of
   `/dev/pts/1`).  A user view's client is still not a *candidate* unless
   the view is named `base~N`; that matches R5.2 and the ambiguity #5
   resolution (a pane cannot identify which client pressed the key).
2. **The spec claimed `current_or_base_session()` accepts `socket_path`.**
   It does not (it resolves the current pane through the ambient server),
   so R2 now says so and records why that is still correct: every caller
   runs with `PM_TMUX_SOCKET` already selected.  `session_group()` was
   added to R2's list of group helpers that do take it.

Nothing else surfaced.  The socket derivation and default-server
addressing (R4.3), discovery scoping (7af7 i1–i3, 3cc7 i1, 703c i1), the
rollout path (R6) and the socket-directory/ownership checks (d1c0
i10/i12, 703c i2) all match the spec, and every new helper has direct
coverage.

Validation on the integrated head: full suite re-run after the edit (see
the PR note for this iteration); `pm/specs/pr-073910f/session_start_smoke.py`
re-run end to end on a disposable socket; no live session, server or
shared host configuration was touched, and the new test is unit-level (it
binds no tmux server).

## Review iteration (2026-10-31, review-loop 703c i4)

Verification pass over the integrated head; no requirement changes.  One
cross-*user* hazard in TUI-pane discovery — the same class of damage the
earlier iterations closed between sessions, one level up:

1. **The unscoped scan could resolve to *another user's* TUI.**
   `/tmp/pm-sessions` is 1777 and `--global` sessions chmod their socket
   0777 (group mode 0770 + group chown), so `list_pm_sessions()` legitimately
   reports other users' servers.  When neither the in-tmux nor the cwd
   branch identified a session (a plain shell), `_find_tui_pane()` scanned
   *every* row and returned the first live `pm _tui` pane whose session name
   matched — including a stranger's.  `pm tui send` delivers keys to a bare
   pane id, so `pm tui view` / `send` / `restart` run from a plain shell
   with no pm session of its own could drive another user's TUI.  Before
   this change the fallback ran on the *ambient* server, which is
   per-uid (`/tmp/tmux-<uid>/default`), so this surface is new.  The scan is
   now filtered by `_server_owned_by_us()` (the row's socket is absent, the
   per-uid default server, or `lstat`-owned by the current uid; an
   unreadable entry counts as ours so a race cannot hide the user's own
   session).  A shared session another user owns stays reachable with an
   explicit `-s` (the explicit branch resolves it by path, without the
   ownership filter) and from inside it (the in-tmux branch).  The
   identified-session branches are deliberately *not* filtered: there the
   answer is the session this process is attached to, which for a joining
   user belongs to the owner.  Tests:
   `TestServerOwnedByUs` (own/default/missing vs another uid) and
   `test_unscoped_scan_skips_another_users_server` (verified to fail
   without the filter: it returned the other user's `%1`).

Nothing else surfaced.  The socket derivation and default-server
addressing (R4.3), discovery scoping (7af7 i1–i3, 3cc7 i1, 703c i1/i4),
the precise detach (R5, 703c i3), the rollout path (R6) and the
socket-directory/ownership checks (d1c0 i10/i12, 703c i2) all match the
spec, and every new helper has direct coverage.

Validation on the integrated head: full suite re-run after the edit (see
the PR note for this iteration); `pm/specs/pr-073910f/session_start_smoke.py`
re-run end to end on a disposable socket; no live session, server or
shared host configuration was touched, and the new tests are unit-level
(they bind no tmux server).

## Review iteration (2026-10-31, review-loop 703c i5)

Verification pass over the integrated head; no requirement changes.  One
misleading API contract, two stale docs, one pre-existing README error.
(Recorded here retroactively: the i5 session left this in the PR note only.)

1. **`_select_session_socket()` returned None for a session that lives on
   the *default* server** even though it had just selected that server (it
   points `PM_TMUX_SOCKET` at the default socket's explicit path).  A
   future caller reading the return value as "session not found" would be
   wrong exactly for legacy sessions.  It now returns the socket in effect
   (private path, or the default server path) and None only when nothing
   was found and the ambient setting was left untouched; no caller used the
   value, so behaviour is unchanged.  Tests:
   `TestSelectSessionSocketReturnValue`.
2. **`_register_tmux_bindings()` docstring** still said bindings "survive
   across sessions (tmux bindings are global)"; with per-session servers
   they are per server and a fresh server starts empty, so the call on
   create *and* reattach is required rather than an optimisation.
3. **`impl.md` R3.2** still said `pm session kill` "unlinks the socket
   file" unconditionally (i8 gated it on `server_alive()`), and both
   `find_exact_session_server()` and `session_kill` referred to a
   requirement "R8" that existed only in `qa.md`; R8 is now recorded in
   this document and R3.2 points at `server_alive()`.
4. Incidental, pre-existing: the README shared-session join example
   `pm session --dir <owner repo>` omitted the flag the command requires;
   fixed to `pm session --global --dir ...`.

## Review iteration (2026-10-31, review-loop 703c i6)

Verification pass over the integrated head; no requirement changes.  One
discovery gap of the class 3cc7 i1 closed for the ambient branch, plus two
spec corrections:

1. **`_find_tui_pane()`'s cwd branch did not record the server it
   selected.**  3cc7 i1 made the last-resort scan able to reach the
   identified session's server when `list_pm_sessions()` does not report it
   (that function enumerates socket *files*, so a live server whose socket
   was unlinked is invisible to it) — but only for the branch that
   identified the session *from inside tmux*.  From a plain shell whose cwd
   names a live private session, `_select_session_socket()` found the
   server, yet the scan list stayed empty and the lookup returned
   `(None, None)` for a TUI whose registry entry was also gone (heal
   testing) — the exact case the last-resort scan exists for.  The branch
   now records the socket it selected (variable renamed
   `identified_server`, since it is no longer only the ambient server).
   Test: `test_last_resort_scans_the_cwd_server_without_a_socket_file`
   (verified to fail without the change: it returned `(None, None)`).
2. **`impl.md` R5** listed the detach steps without the base resolution
   703c i3 added (a user's own grouped view need not be named `base~N`, so
   the base comes from `session_group()`); the requirement body now says
   so, and R3.4 notes that either branch's server is scanned, not only the
   ambient one.
3. The 703c i5 iteration had no section in this document (only a PR note);
   added above so the requirement/decision log stays complete.

Validation on the integrated head: full suite re-run after the edit (see
the PR note for this iteration); `pm/specs/pr-073910f/session_start_smoke.py`
re-run end to end on a disposable socket with `TMUX_TMPDIR` on a scratch
dir (private server created, `PM_TMUX_SOCKET` in the session env, the
global env and the hooks, default server untouched); `pm session list`
re-checked read-only in this container.  No live session, server or shared
host configuration was touched; the new test is unit-level and binds no
tmux server.

## Review iteration (2026-10-31, review-loop 703c i7)

Verification pass over the integrated head; no requirement changes.  One
test gap in the rollout path (R6.1 / acceptance 4):

1. **The legacy attach path had no end-to-end coverage.**  Every existing
   test asserted a piece of it — `_resolve_session_socket` returns
   `(None, True)` and exports the default server's socket, `pm session
   --print-connect` prints the legacy form, `pm session kill` targets the
   default server — but nothing ran `_session_start` itself against a
   pre-isolation session.  The two user-visible guarantees of R6.1 were
   therefore never asserted together: no private server/socket is created,
   and the legacy session plus the grouped session it attaches to stay on
   the default server (nothing is killed or migrated), while the process
   addresses that server *explicitly* (`PM_TMUX_SOCKET` = the default
   socket, not whatever `$TMUX` names).  New
   `TestSessionStartAttachesToLegacySession::test_attaches_to_the_legacy_session_without_creating_a_private_one`
   builds a real pre-isolation session on a disposable default socket with
   its TUI pane registered (so the "TUI missing" heal path does not fire),
   runs `_session_start`, and asserts the rollout note, the exported default
   socket, the `pm-iso-legacy~1` attach target on the default server, the
   absence of the private socket, and that neither the session environment
   nor the server's global environment received a `PM_TMUX_SOCKET`.
   Verified to fail with the legacy branch disabled: it created a private
   session instead of attaching.

Nothing else surfaced.  The socket derivation and default-server addressing
(R4.3), discovery scoping (7af7 i1–i3, 3cc7 i1, 703c i1/i4/i6), the precise
detach (R5, 703c i3), the kill/unlink rules (R3.2, R8), the socket-directory
and ownership checks (d1c0 i10/i12, 703c i2) and the shared-session
share-mode handling (d1c0 i7) all match the spec, and every new helper has
direct coverage.

Validation on the integrated head: full suite re-run after the edit (see the
PR note for this iteration); no live session, server or shared host
configuration was touched, and the new test binds only disposable sockets.

## Review iteration (2026-10-31, review-loop 703c i8)

Verification pass over the integrated head; no requirement changes.  One
shared-session consistency fix in the session-start path:

1. **A plain `pm session` that adopted a shared ambient session lost
   `window-size=smallest`.**  `_session_start()` calls
   `_set_share_mode_env(share_global, share_group)`, which *pops*
   `PM_SHARE_MODE` when no `--global`/`--group` was passed.  Since the
   d1c0 i7 change, a plain `pm session` run from inside an already-shared
   session adopts that ambient session instead of creating a private twin
   — but `_register_tmux_bindings()` and the two grouped-session
   `set_session_option(..., "window-size", "smallest")` gates keyed off the
   *process* `PM_SHARE_MODE`, so none of them fired.  The new grouped
   session (and any grouped session the bindings pass would have healed)
   kept tmux's default `window-size=latest`, so with clients of different
   sizes the smallest one sees a clipped layout — the exact condition
   `window-size=smallest` exists for.  The mode the session was *created*
   with is recorded in its session environment, so a new
   `session._session_is_shared(session_name)` returns true when either the
   process variable is set or the session environment records
   `PM_SHARE_MODE`; all three gates now use it.  The process variable is
   still the only signal on the create path (it is set before any of these
   run), and a private session records nothing, so its behaviour is
   unchanged.  Tests: `TestSessionIsShared` (explicit flag short-circuits
   the query; the session environment is read by name; a private session
   is not shared) plus the wiring (`_register_tmux_bindings` applies
   `window-size=smallest` to base + grouped from the session environment,
   and leaves a private session alone).

Also checked and left alone: the d1c0 i8 residual — `is_shared` is still
flag-derived for the private-socket ownership check, so an adopted shared
session is checked as private, which is harmless for the owner, who owns
the socket.  This fix deliberately does not touch that: the ownership
check keeps using the flag, and only the window-size/bindings gate
consults the session environment.

Nothing else surfaced.  The socket derivation and default-server addressing
(R4.3), discovery scoping (7af7 i1–i3, 3cc7 i1, 703c i1/i4/i6), the precise
detach (R5, 703c i3), the kill/unlink rules (R3.2, R8), the socket-directory
and ownership checks (d1c0 i10/i12, 703c i2) and the shared-session
share-mode handling (d1c0 i7, 703c i8) all match the spec, and every new
helper has direct coverage.

Validation on the integrated head: full suite re-run after the edit (see the
PR note for this iteration); no live session, server or shared host
configuration was touched.

## QA-driven fixes (2026-11-01)

Two user-visible defects were found by QA scenarios after the last review
iteration and fixed in `qa:` commits; no requirement changes.

1. **One Ctrl-Q detached every client of the session** (QA scenario 10
   re-run, commit `64249843d`).  R5's precise branch only considers
   clients whose session's active window is the TUI window; when none
   does (the base session's current window is a shell or review window)
   the old fallback ran `detach-client -s <session>`, which drops *all*
   clients attached to that session.  With two clients on the base
   session, one press left both at a prompt.  The fallback now picks the
   group's most recently active single TTY (`detach-client -t`), exactly
   like the precise branch, and R5 step 4 above records it.  Tests:
   `test_falls_back_to_one_group_client` (asserts `-t /dev/pts/1`, not
   `-s`) and `test_two_clients_on_the_base_lose_only_one`.
2. **The TUI connect popup clipped the socket-addressed command** (QA
   scenario 12, commit `57dfdca02`).  `ConnectScreen`'s
   `#connect-container` was a fixed 70 cells wide, so `tmux -S
   /tmp/pm-sessions/pm-<tag> attach` lost its last characters at the
   border — the popup did not show the command it tells the user to run
   (the legacy `-t <session>` form clips more).  The container now sizes
   to its content (`width: auto; min-width: 70; max-width: 100%`) and the
   command label wraps, so a short command keeps the historical width, an
   ordinary socket-addressed command is shown in full, and a path longer
   than the terminal wraps.  Tests: `TestConnectScreenLayout` renders the
   modal headlessly at 80 and 60 columns and asserts the command's box
   fits inside the container and the text is complete.

Also recorded: the `qa.md` scenario spec now states the requirements
these QA runs exercised (grouped-view resolution for discovery, driving
and detaching; another user's server never auto-selected; sticky but
non-world-writable socket directory refused; regular files/symlinks
planted at a socket path skipped by `pm session list`; a plain reattach
to a shared session keeps `window-size=smallest` from the recorded share
mode).

## Review iteration (2026-11-01, review-loop 2caf i1)

Verification pass over the head after the two QA-driven fixes; no
requirement changes.  One small consolidation and the spec/doc updates
above:

1. **`session_socket_path(session_name.removeprefix("pm-"))` was copied
   in three places** (`_resolve_session_socket`, `pm session
   --print-connect`, `session kill`) and a fourth variant lived inline in
   `tmux._find_session_server`.  New `tmux.session_socket_for(session_name)`
   (strips a grouped `~N` suffix, derives the tag, hashes a long path) is
   the single definition; all four use it, matching the i3 principle that
   "which server hosts this session" has one implementation.  Tests:
   `TestSessionSocketFor` (tag derivation, grouped-suffix normalisation,
   long-name hash).
2. **`impl.md` R5 step 4 was stale** — it still described the
   `detach-client -s` fallback replaced by the QA fix.  Corrected, and the
   QA-driven fixes recorded in their own section.
3. **The printed connect command was not shell-quoted.**  A session tag is
   derived from the repo directory name, which may contain a space, so
   `pm session --print-connect` (and the TUI `C` screen, which shows the
   same command to copy) printed `tmux -S /tmp/pm-sessions/pm-my repo-…`
   — pasting it split the path.  Both surfaces now `shlex.quote` the
   socket path and the session name; ordinary paths are unchanged
   (`shlex.quote` leaves them bare), so every existing exact-output
   assertion still holds.  Tests:
   `TestPrintConnect::test_command_is_shell_quoted` and
   `TestShowConnect::test_command_is_shell_quoted`.
4. Incidental, pre-existing and out of scope: `pm session` run from a
   shell pane inside any tmux session dies with an unhandled
   `TmuxCommandError` ("sessions should be nested with care") instead of
   a clear message.  Filed as **pr-e848481**.

Nothing else surfaced: the socket derivation and default-server
addressing (R4.3), discovery scoping (7af7 i1–i3, 3cc7 i1, 703c
i1/i4/i6), the precise detach (R5, 703c i3 + the QA fix), the kill/unlink
rules (R3.2, R8), the socket-directory and ownership checks (d1c0
i10/i12, 703c i2) and the shared-session share-mode handling (d1c0 i7,
703c i8) all match the spec, and every new helper has direct coverage.

Validation on the integrated head: full suite re-run after the edit (see
the PR note for this iteration); no live session, server or shared host
configuration was touched.

## Review iteration (2026-11-01, review-loop 2caf i2)

Verification pass over the head after the i1 consolidation; no requirement
changes.  Two user-visible defects on the surfaces this PR exists to make
trustworthy — the command the TUI tells the user to paste, and the quit key:

1. **The connect popup silently mangled the command it displayed.**
   `ConnectScreen` yielded the command through a Textual `Label`, which
   renders *markup* by default, so a `[` in the command was parsed as a
   style tag.  A session tag is derived from the repo directory name, so a
   repo named `my[repo]` (session `pm-my[repo]-<hash>`) displayed
   `tmux -S /tmp/pm-sessions/pm-my-repo-<hash> attach` — a command naming a
   different session, which for a missing socket *creates* a stray server.
   The copy key (`c`) copied the correct text, so only what the user saw
   (and would retype or copy with the mouse) was wrong.  The label now
   renders with `markup=False`.  Test:
   `TestConnectScreenLayout::test_shows_brackets_in_the_command_verbatim`
   (verified to fail with markup on: the rendered line lost `[repo]`).
2. **Ctrl-Q did nothing — or detached the wrong client — in a user's own
   grouped view.**  R5's candidate set was "base + `base~N`", enumerated
   by name, so a view created with `tmux new-session -t pm-x -s myview`
   (S118/S121/S124) was not a candidate even though it shares the windows
   and its client is the one viewing the TUI.  Verified live on a
   disposable socket: with a single client attached to `myview` and
   viewing the TUI window, `detach_current_client()` returned False and
   the client stayed attached; with a `~1` client also present it
   detached that client instead.  New
   `tmux.sessions_in_group()` enumerates membership through tmux's
   `#{session_group}` (union'd with the `base~N` names so an old or
   unqueryable server still yields them), and
   `sessions_on_window(..., members=...)` lets the detach path use it
   without changing the review-loop/sign-off/watcher/home-window callers.
   R5 step 2 above now states the group-based candidate set.  Tests:
   `TestSessionsInGroup` (view included, ungrouped alone, failed group
   query keeps `base~N`, tmux missing) and
   `TestDetachCurrentClient::test_detaches_a_client_viewing_through_the_users_own_view`
   / `::test_view_client_viewing_the_tui_wins_over_other_group_clients`
   (both verified to fail with the name-prefix candidate set: the first
   detached nothing, the second detached `/dev/pts/1` instead of the
   view's client).

3. **An exported empty `PM_SHARE_MODE` hid the ambient session.**
   `_ambient_session_for_share_mode()` compared the recorded share mode
   against `os.environ.get("PM_SHARE_MODE")` *raw*, while every other
   reader tests the variable for truthiness (`_set_share_mode_env` pops it
   when no flag is given).  With `PM_SHARE_MODE=` exported, `None != ""`,
   so `pm session kill` / `mobile` in a workdir clone dropped the ambient
   candidate and reported "No session … found" for a live session.  The
   comparison now normalises the wanted mode with `or None` (found by the
   full suite, which ran with the variable set to the empty string).
   Test: `TestResolveTargetSession::test_an_empty_share_mode_counts_as_unset`
   (verified to fail without the normalisation); `TestSessionKillServerSelection._invoke`
   also unsets the variable so the fixture no longer depends on the
   caller's environment.

Also checked and unchanged: the `pm session list` CLIENTS column still
counts only `pm-`-named base/`~N` sessions (a view's client is not
counted; QA scenario 9 recorded this and uses `tmux list-clients` as the
authoritative check), and the connect screen's last-resort bare
`tmux attach -t <name>` is still unreachable for a live session.

Validation on the integrated head: full suite re-run after the edits (see
the PR note for this iteration); no live session, server or shared host
configuration was touched — every fixture used a disposable socket.

## Review iteration (2026-11-01, review-loop 2caf i3)

Verification pass over the head after the i2 fixes; no requirement
changes.  No defect surfaced in the code; this iteration closes coverage
gaps in the PR's central discovery/connect paths and corrects two
`qa.md` requirements that no longer matched the implemented behaviour.

1. **The cwd discovery branch's success return had no test.**  Every
   existing `_find_tui_pane` test either had no cwd session running or a
   registry without a live TUI pane, so the everyday path — a plain
   shell in the project directory whose session runs on its own server
   with a registered TUI pane — was never asserted end to end (it was
   the only uncovered branch of the new lookup).  New
   `TestFindTuiPaneAcrossServers::test_cwd_session_with_a_registered_tui_pane_is_resolved`
   runs the real `_select_session_socket`, asserts the pane and base
   session are returned and that `PM_TMUX_SOCKET` now names the cwd
   session's server; verified to be the only test covering that return
   (coverage line 1525).
2. **`pm session --print-connect --dir` was untested.**  The `--dir`
   branch computes the tag from the target directory (with the share mode
   mixed in) and never ran under test.  New
   `TestPrintConnect::test_dir_with_share_flags_prints_the_shared_socket`
   asserts the printed command, that the tag came from the `--dir`
   directory, and that `PM_SHARE_MODE` was set for the tag computation.
3. **Two small CLI branches had no coverage:** `--global` + `--group`
   mutual exclusion (nothing must be printed) and `pm session list`
   without tmux ("tmux is not installed.", exit 1).  New tests in
   `TestPrintConnect` and `TestSessionListCommand`.
4. **The i2 detach fix had only unit coverage.**  New
   `TestServerIsolationIntegration::test_detach_through_the_users_own_view`
   builds a real base + `myview` group on a disposable socket, attaches
   a real client to the view, and asserts one `detach_current_client()`
   removes exactly that client while both sessions survive — the
   production shape of R5's view bullet, previously verified only by
   mocks and manually.
5. **`qa.md` R3** said the CLIENTS count "covers the whole session
   group".  Since R5/`sessions_in_group` define the group to include a
   user's own view, the wording contradicted the deliberate behaviour
   recorded in the i2 section (only `pm-`-named base/`~N` sessions are
   counted; QA scenario 9 uses `tmux list-clients` as authoritative).
   R3 now states exactly that and cross-references R5.
6. **`qa.md` R9**'s plain-reattach bullet said a plain `pm session`
   reattaches a shared session "from the project directory".  From a
   *plain shell* there is no ambient session to adopt, so the command
   starts the directory's private session (a twin beside the shared one,
   the fail-safe documented for R5b and observed in QA scenario 10); the
   `smallest` sizing behaviour applies when the plain `pm session` runs
   from a shell pane *inside* the shared session (703c i8).  The bullet
   now says so and states the plain-shell outcome explicitly.

Validation on the integrated head: full suite re-run after the edits (see
the PR note for this iteration); no live session, server or shared host
configuration was touched — every fixture used a disposable socket.

## Review iteration (2026-11-01, review-loop 2caf i4)

Verification pass over the head after the i3 coverage work.  Two defects,
both instances of one rule: **a user's own view of a pm session is not a
session of its own** (S118/S121/S124).  The detach path (2caf i2) and the
in-tmux discovery branch (703c i1) already resolve views through the
session group; these two paths still used the view's name.

1. **`_find_live_tui_pane()` rejected a live recorded TUI pane reported
   under a view's name.**  `list-panes -a` lists a shared pane once per
   session in its group, so `_live_panes_and_tuis()`'s
   `pane_id → session_name` map keeps whichever name tmux emits last
   (verified: the lexicographically greatest session name wins).  With a
   view named e.g. `zview` — after the pm base `pm-x` — the recorded pane
   `%0` looked like `zview`'s, `base_session_name("zview") != "pm-x"`, and
   the recorded-pane check fell through.  The live-`pm _tui` fallback
   normally rescues that case, but it also compares names, so a TUI whose
   `pane_start_command` does not contain `_tui` (the documented
   hand-started TUI, or a pane respawned with a shell) was reported as
   "No TUI pane found" although it was running.  Reproduced against a real
   disposable server (base `pm-x` + view `zview`, pane registered):
   `_find_live_tui_pane("pm-x")` returned `(None, "pm-x")`; with the fix it
   returns `("%0", "pm-x")`.  New `_pm_session_of()` resolves a tmux
   session name through `pane_registry.pm_session_name()` (the group),
   degrading to the plain base name when tmux cannot be queried, and both
   comparisons in `_find_live_tui_pane()` use it.
2. **`_find_tui_pane()`'s last-resort scan had the same comparison**, so a
   live `pm _tui` pane reported only under the view's name was not found
   when the base session was killed elsewhere (the case R3.2 keeps prefix
   matching for).  It now compares through `_pm_session_of()` too.
3. **`pm session list` showed a phantom session for a pm-named view.**
   `list_pm_sessions()` grouped rows by `name.split("~")[0]`, so a user's
   view named `pm-laptop` (grouped with `pm-x`) was listed as a second
   session on the same socket, violating R3's "one row per session"
   (verified live on a disposable server).  It now reads
   `#{session_group}` as well and skips a session whose group is a
   different base and whose name is not `group~N` — a view, whatever it is
   called; the view's clients stay uncounted, as R3 says.

Tests: `TestFindLiveTuiPane::test_live_pane_reported_under_the_users_view_is_returned`
and `::test_fallback_finds_a_live_tui_reported_under_the_users_view`,
`TestFindTuiPaneAcrossServers::test_last_resort_resolves_a_pane_reported_under_a_view`,
`TestListPmSessions::test_skips_a_users_view_of_a_pm_session` — all four
verified to fail with the pre-fix code.  The existing
`TestListPmSessions` fixtures gained the `#{session_group}` column.

Validation: targeted suites (`test_cli_helpers`, `test_session_socket_isolation`,
`test_tmux`, `test_shared_sessions`, `test_cli_qa`) 382 passed; full suite
**5367 passed / 1 skipped** (409 s; log
`/pm-captures/review-2caf-i4/full-suite-final.log`), and
`pm/specs/pr-073910f/session_start_smoke.py` re-ran clean on a disposable
socket (private server, session env, global env and hooks correct; default
server untouched).  Both defects were also verified end to end against
disposable real-tmux servers; no live session, server or shared host
configuration was touched.

Residual (non-blocking): a user's own view that *survives* its base
session (the base killed **by hand**, e.g. `tmux kill-session`, while the
view's client stays attached) is not discoverable from a plain shell —
`list_pm_sessions()` reports pm-named sessions only, and
`find_session_server()` cannot match a non-pm-named view by the base
name.  From *inside* the view discovery resolves it through the group
(above), and a direct `tmux -S <socket> attach` still reaches it; only
the plain-shell auto-discovery of a view-only server is absent, and it
previously worked only by listing the view under a non-session name.
Not a supported R3/R7 shape (a view is not a session).  `pm session kill`
no longer produces this state: it tears down the whole group, views
included (review-loop 2caf i7).

## Review iteration (2026-11-01, review-loop 2caf i5)

Verification pass over the head after the i4 fixes; no requirement
changes.  One user-visible defect and one listing defect, both from
parsing tmux format output with a separator that can appear in a session
name:

1. **`pm tui view` / `send` / `restart` and `pm qa regression` reported
   "No TUI pane found" for a session whose repo directory name contains a
   space.**  `_live_panes_and_tuis()` queried
   `"#{pane_id} #{session_name} #{pane_start_command}"` and split on
   whitespace, so a session name like `pm-my repo-abc` was read as its
   first word.  Since the d1c0 i4 change the recorded pane is accepted
   only when the session tmux reports for it is the session being
   resolved (`_pm_session_of(live_panes[pane_id]) == base`), so the
   truncated name made a live registered pane look like another session's
   — every pane-driving command failed while the TUI was running.
   (Before that change the check was a bare pane-id set membership, so
   this is a regression introduced by the PR's cross-server guard, not a
   pre-existing behaviour.)  The query now uses `:` as the field
   separator — tmux rewrites `:` and `.` in session names to `_`, so a
   session name can never contain it, while spaces and `|` are legal —
   and the start command stays last (`maxsplit=2`) so its own separators
   are preserved.
2. **`pm session list` silently dropped a session whose name contains
   `|`.**  The new `list_pm_sessions()` query used
   `"#{session_name}|#{session_group}|#{session_attached}"`; the group is
   the base session's own name, so `rsplit("|", 2)` still split the name
   at its own `|` and the row was discarded (the comment claimed the
   `rsplit` handled a `|` in the name — it only did when the group had
   none, which cannot happen for a grouped session).  Same fix:
   `:`-separated fields.  `sessions_in_group()`'s group query had the
   same `|` limitation (a view whose name contains `|` was not a detach
   candidate); it now uses `:` too.

Tests: `TestFindLiveTuiPane::test_live_tui_in_a_session_whose_name_contains_a_space`
(verified to fail with the space-separated query: it returned
`(None, "pm-my repo-abc")` for a live `%0`),
`TestListPmSessions::test_lists_a_session_whose_name_contains_a_pipe`
(verified to return no rows with the old format), and
`TestSessionsInGroup::test_includes_a_view_whose_name_contains_the_old_separator`.
The existing `_panes()`/`list-sessions` fixtures were updated to the
`:`-separated format.  Both defects were also reproduced and re-verified
end to end against disposable real-tmux servers (a session named
`pm-my repo-abc` and one named `pm-my|repo-abc`): the pre-fix tree
returned `(None, "pm-my repo-abc")` from `_find_live_tui_pane` while the
fixed tree returns `("%0", "pm-my repo-abc")`, and
`list_pm_sessions()` reports both sessions.

Also corrected in this document: R4.4 said `qa_status` builds its argv
with `tmux_mod._tmux_cmd()`; it uses its own `_tmux_argv()` (the module
must not import `pm_core`), which is what the d1c0 i2 residual already
documented.

Residual (non-blocking, pre-existing and outside this change):
`tmux.attached_group_active_windows()` uses the same `|` format with the
session name last; a base session name containing `|` shifts its group
field, so the popup picker's collaborator display loses those rows.
`tmux.switch_sessions_to_window()` parses
`"#{session_name} #{client_tty}"` with the name first, so the same
space-name truncation applies to its client map.  Both functions predate
this PR (their formats are asserted by their own tests); only the
new/changed parsers are covered by the fix above.  *(Closed in
review-loop 2caf i10 — see that iteration below.)*

Validation: targeted suites (`test_cli_helpers`, `test_session_socket_isolation`,
`test_tmux`, `test_shared_sessions`, `test_cli_qa`) 385 passed; full suite
re-run after the edits (see the PR note); no live session, server or
shared host configuration was touched — every fixture used a disposable
socket and the real-tmux repros used disposable sockets and a temporary
HOME.

## Review iteration (2026-11-01, review-loop 2caf i6)

Verification pass over the head after the i5 fixes.  One user-visible
defect: the last name-based pane→session resolution on a path this PR
changed (the QA status pane's window switch).

1. **The QA status pane could not switch the window of a user viewing
   through their own view.**  `qa_status._find_attached_session()`
   (priority 1) read the pane's `#{session_name}` and accepted it only
   when it was `base` or `base~N`.  tmux names the most recently active
   session of a shared window, and S118/S121/S124 let a user's own view
   be named anything, so with the user attached through `tmux
   new-session -t pm-x -s zview` the pane reported `zview`, the test
   failed, and the function fell back to the base session.  `select-window
   -t pm-x:<window>` then switched the *base* session's current window,
   which the user's client does not follow (each session in a group keeps
   its own current window — verified live on tmux 3.2a: the base moved to
   `qa` while `zview` stayed on `main`), so the QA pane silently failed to
   bring its window forward.  The query now returns
   `#{session_name}:#{session_group}` in one call (`:` cannot occur in a
   tmux session name; a name may contain spaces or `|`) and accepts the
   pane's session when it belongs to `base`'s group.  This is the same
   test `tmux.current_or_base_session` applies, which the function's
   docstring already claims to mirror; the module stays standalone (no
   `pm_core` import).  Verified live on a disposable socket: with a client
   attached to `zview`, `_find_attached_session("pm-x")` returns `zview`
   and `_switch_to_window` moves `zview` to `qa` (the base stays on
   `main`).  Tests: `TestQaStatusSocketRouting::test_switches_the_users_own_view`
   and `::test_ignores_a_pane_in_another_sessions_group`.

Checked and left alone (deliberate, documented scope): priority 2 keeps
its `base`/`base~N` name match, exactly like `current_or_base_session`'s
fallback; `tmux.list_clients_in_group()` (`pm session -d`) and
`sessions_on_window()`'s default candidate set also stay name-based —
2caf i2 scoped the view-aware candidate set to the detach path only, and
those callers predate this PR.  Residuals from i5 (the `|`/space formats
in `attached_group_active_windows` and `switch_sessions_to_window`) are
unchanged.

Validation: targeted suites (`test_session_socket_isolation`,
`test_tmux`, `test_cli_helpers`, `test_shared_sessions`, `test_cli_qa`)
pass; full suite re-run after the edit (see the PR note); every fixture
used a disposable socket and a temporary HOME — no live session, server
or shared host configuration was touched.

## Review iteration (2026-11-01, review-loop 2caf i7)

Verification pass over the head after the i6 fix; one destructive-path
gap, the same "a user's own view is part of the session group" rule the
detach (i2), discovery (703c i1, 2caf i4) and QA-status (i6) fixes
applied elsewhere:

1. **`pm session kill` left a user's own view (and its client) alive.**
   The kill enumerated the group with `list_grouped_sessions()`, which
   matches `base~N` by *name*, so a view created with `tmux new-session -t
   base -s myview` (S118/S121/S124) survived: its client stayed attached,
   the shared windows — and therefore the old `pm _tui` pane — stayed
   alive, the server kept running, and the socket file could not be
   removed (`server_alive()` correctly refused to unlink it).  `pm session
   list` shows nothing for that server (a view is not a session), and a
   later `pm session` starts a second base with the same name on the same
   server — two TUIs for one session name.  The kill now enumerates
   `sessions_in_group()` (tmux's `#{session_group}` plus the `base~N`
   names) and kills every member, then the base; the group is gone, the
   server exits, and the socket is unlinked.  Tests:
   `TestSessionKillServerSelection::test_kill_also_tears_down_a_users_view`
   (verified to fail with the name-prefix list: only the base was killed)
   and the disposable-server
   `TestServerIsolationIntegration::test_kill_tears_down_the_whole_group_including_a_view`
   (a real base + `~1` + `myview`; `sessions_in_group()` returns all
   three, killing them exits the server).

Nothing else surfaced.  The socket derivation and default-server
addressing (R4.3), discovery scoping (7af7 i1–i3, 3cc7 i1, 703c
i1/i4/i6, 2caf i4/i5), the precise detach (R5, 703c i3, 2caf i2), the
kill/unlink rules (R3.2, R8), the socket-directory and ownership checks
(d1c0 i10/i12, 703c i2) and the shared-session share-mode handling (d1c0
i7, 703c i8) all match the spec, and every new helper has direct
coverage.  The i4 residual is narrowed accordingly: the view-only state
now arises only from a manual `tmux kill-session` of the base.

Validation: targeted suites (`test_session_socket_isolation`,
`test_tmux`, `test_cli_helpers`, `test_shared_sessions`, `test_cli_qa`)
389 passed; full suite re-run after the edit (see the PR note); every
fixture used a disposable socket and a temporary HOME — no live session,
server or shared host configuration was touched.

## Review iteration (2026-11-01, review-loop 2caf i8)

Verification pass over the head after the i7 kill fix; no requirement
changes.  One fail-closed gap in the socket-directory guard, the same
class as the per-socket checks (d1c0 i10/i12, 703c i2) but one level up:

1. **`ensure_socket_dir()` accepted a *symlinked* `/tmp/pm-sessions`.**
   `/tmp` is world-writable, so another local user can create the
   well-known path as a symlink to a directory they own before pm ever
   runs.  `mkdir(exist_ok=True)` succeeds through the link, our `chmod`
   then fails (we are not the target's owner), and the d1c0 i12 fallback
   used `stat()` — the *target's* mode — so a 1777 target passed the
   guard and every socket pm bound lived in a directory whose owner can
   unlink it (the sticky bit protects a file from users *other* than the
   directory's owner), allowing the socket to be replaced by an
   attacker-run server that pm would then connect to.  The guard now
   refuses a symbolic link at the path outright — pm always creates a
   real directory, so a link is never ours, even when its target is —
   and the mode fallback inspects the entry with `lstat` (defence in
   depth for a link planted between the two checks).  `pm session`
   reports it with the same actionable message as the other unusable
   directory states.  Tests: `TestSessionSocketPath::
   test_refuses_a_symlinked_socket_dir` and
   `TestResolveSessionSocket::test_refuses_a_symlinked_socket_dir`, both
   verified to fail with the pre-fix guard (no exception was raised).

Nothing else surfaced.  The socket derivation and default-server
addressing (R4.3), discovery scoping (7af7 i1–i3, 3cc7 i1, 703c
i1/i4/i6, 2caf i4/i5), the precise detach (R5, 703c i3, 2caf i2), the
kill/unlink rules (R3.2, R8, 2caf i7), the socket-file and
socket-directory ownership checks (d1c0 i10/i12, 703c i2, above) and the
shared-session share-mode handling (d1c0 i7, 703c i8) all match the
spec, and every new helper has direct coverage.

Validation: targeted suites (`test_session_socket_isolation`,
`test_tmux`, `test_cli_helpers`, `test_shared_sessions`, `test_cli_qa`)
pass; full suite re-run after the edit (see the PR note); every fixture
used a disposable socket and a temporary HOME — no live session, server
or shared host configuration was touched.

## Review iteration (2026-11-01, review-loop 8d4e i1)

Verification pass over the head after the 2caf i8 fixes; no requirement
changes.  One rollout-path gap, of the class R1/R6 define:

1. **A vanished legacy session still sent the create path to the default
   server.**  `_resolve_session_socket()` decides "legacy" from a
   `find_session_server()` snapshot and exports the *default* server's
   socket; `_session_start()` then asked, a moment later, whether the
   session was running.  A concurrent `pm session kill` (or any other
   removal) between the two probes made that answer "no" while the
   process was still pointed at the default server, so the create path
   below created a brand-new session there — outside its own server
   (R1) — and every later `pm session` saw it as legacy again, making the
   state self-perpetuating.  The existence check is now taken once; when
   it says the legacy session is gone, `_session_start()` re-resolves the
   socket (which then yields the deterministic private path) and re-checks
   before the rollout note is printed, so the note never describes a
   session that is not being attached.  Test:
   `TestSessionStartAttachesToLegacySession::
   test_a_vanished_legacy_session_is_created_on_its_private_socket`
   (verified to fail with the old order: it created with
   `socket_path=None` on the default server and printed the note).

Nothing else surfaced.  The socket derivation and default-server
addressing (R4.3), discovery scoping (7af7 i1–i3, 3cc7 i1, 703c
i1/i4/i6, 2caf i4/i5), the precise detach (R5, 703c i3, 2caf i2), the
kill/unlink rules (R3.2, R8, 2caf i7), the socket-file and
socket-directory ownership checks (d1c0 i10/i12, 703c i2, 2caf i8) and
the shared-session share-mode handling (d1c0 i7, 703c i8) all match the
spec, and every new helper has direct coverage.

Cross-PR residual (recorded on pr-6de8207, not fixed here): a repo
directory whose name contains `.` or `:` yields a tag tmux rewrites to
`_` when it creates the session, so the session name no longer matches
the tag-derived socket: `pm session`'s duplicate convergence cannot find
the session (`has-session -t` fails on the original name), and `pm session
kill` / `pm tui … -s <the name list reports>` derive a different socket.
Pre-existing (master's `create_session` re-raises the duplicate the same
way) and the same root cause as the `~` case: `get_session_tag()` uses the
repository directory name unsanitised.

Validation: targeted suites (`test_session_socket_isolation`,
`test_tmux`, `test_cli_helpers`, `test_shared_sessions`, `test_cli_qa`)
394 passed; full suite re-run after the edit (see the PR note);
`pm/specs/pr-073910f/session_start_smoke.py` re-run on a disposable socket
(private server, session env, global env and hooks correct; default server
untouched); `pm session list` read-only ("No pm sessions found.", no
socket directory created).  No live session, server or shared host
configuration was touched — every fixture used a disposable socket and a
temporary HOME.

## Review iteration (2026-11-01, review-loop 2caf i10)

Verification pass over the head after the 8d4e i1 fix; no requirement
changes.  One fail-closed gap in the new listing code, one order-dependent
test module, and the two tmux parsers the i5 iteration had left as
residuals:

1. **`list_pm_sessions()` followed a symlinked socket directory.**
   `/tmp` is world-writable, so another local user can create
   `/tmp/pm-sessions` as a symlink to a directory they own.  `pm session`
   refuses that path outright (`paths.ensure_socket_dir`; review-loop 2caf
   i8), but the *read* path did not: `Path.glob` resolves the link, so
   `pm session list` enumerated the target directory and reported its
   servers as pm sessions (verified live: a planted directory's socket was
   listed), and discovery scanned it.  The target's owner would decide
   which sessions appear as ours — the same hazard the per-entry `lstat`
   hardening (d1c0 i12) and the directory refusal (2caf i8) close one
   level down.  The scan now `lstat`s the directory and skips a path that
   is not a real directory (a missing directory stays the normal
   first-run state), logging a warning; the default-server pass is
   unaffected, so legacy sessions are still listed.  `qa.md` R12 gained
   the read-path bullet.  Test:
   `TestListPmSessions::test_does_not_follow_a_symlinked_socket_dir`
   (verified to fail pre-fix: the planted socket was probed and listed).

2. **This module's tests leaked `PM_TMUX_SOCKET` into later tests.**  The
   code under test deliberately exports the variable into the process
   environment (`helpers._use_tmux_socket`), and `monkeypatch.delenv`
   records *nothing* for a variable that is already absent — so a test
   that cleared it and then let pm set it left the value behind for the
   rest of the run.  Demonstrated: `tests/test_tmux.py`'s new
   `TestSwitchSessionsToWindow` assertions failed only when run after
   `test_session_socket_isolation.py`, with a stray `-S <tmp socket>` in
   the command (the same order-dependence the b972 i1 note removed from
   `test_shared_sessions.py`, from the other side).  A module-local
   autouse fixture now snapshots and restores `os.environ`; the two new
   `test_tmux.py` tests also pin the variable to `""` so their exact
   command assertions do not depend on the caller's environment.

3. **The two residual parsers from 2caf i5 now use `:`-separated
   fields.**  `attached_group_active_windows()` used a `|` format whose
   *group* field repeats the base session's name, so a base name
   containing `|` shifted every following field and the collaborator row
   was dropped from the popup picker.
   `switch_sessions_to_window()` parsed
   `"#{session_name} #{client_tty}"`, so a session name containing a
   space was truncated, its client was never found, and the
   `switch-client` that moves it to a replacement window was skipped
   (sign-off, QA-loop, watcher and merge paths).  Both now use `:`, which
   tmux forbids in session names (it rewrites `:` and `.` to `_`) while a
   name may contain `|` or spaces — the rule the i5 fix applied to
   `_live_panes_and_tuis`, `list_pm_sessions` and `sessions_in_group`.
   Tests: `TestAttachedGroupActiveWindows::
   test_group_name_may_contain_the_old_separator` and the new
   `TestSwitchSessionsToWindow` (`test_session_name_may_contain_a_space`,
   `test_unknown_client_still_selects_the_window`); the existing
   `attached_group_active_windows` fixtures moved to the `:` format.

Validation: targeted suites (`test_session_socket_isolation`,
`test_tmux`, `test_cli_helpers`, `test_shared_sessions`, `test_cli_qa`,
`test_popup_picker`, `test_qa_background_focus`, `test_signoff`,
`test_tui_pidfile`) 907 passed; full suite re-run after the edits (see the
PR note).  Every new test was verified to fail with the pre-fix code.  No
live session, server or shared host configuration was touched — every
fixture used a disposable socket and a temporary HOME.

## Review iteration (2026-11-01, review-loop 2caf i11)

Verification pass over the head after the 2caf i10 fixes; no requirement
changes.  Two gaps, both left by the 703c i8 shared-session consistency
fix: the per-window half of its window-size gate, and the ambient-session
adoption for the commands it did not touch.

1. **`set_shared_window_size()` still gated on the process environment.**
   The 703c i8 fix taught `_register_tmux_bindings()` to ask the session
   for its share mode, but the per-window option kept the old
   `os.environ.get("PM_SHARE_MODE")` test.  That variable is absent in
   the contexts that respawn a shared session's TUI:
   - a `run-shell` command from a *global* hook sees the server's global
     environment (verified on tmux 3.2a: a global `after-kill-pane` hook
     knows `#{session_name}` but not the *session's* variables).  That
     global environment normally carries `PM_SHARE_MODE` because the
     server was started by the `pm session --global` process, but it does
     not when the variable was missing from the client that started the
     server (a joiner's plain `tmux -S … attach` after the owner's server
     exited) — then `pm _pane-closed` (`pane_layout._respawn_tui`) ran
     without it; and
   - a plain `pm session` that adopted an already-shared ambient session
     clears it in its own environment (`_set_share_mode_env(False,
     None)`, the 703c i8 case), so its `_respawn_tui` path lost the
     option too.

   *(b48f i2 correction: the first bullet originally claimed the hook
   always ran without the variable.  The server global environment
   normally propagates it from the creating `pm session --global`
   process — verified 2026-11-01: a pane and a `run-shell` command on a
   server started with `PM_SHARE_MODE=global` both see it — so the
   fallback covers the contexts where that did not happen, not every
   hook.)*
   A window recreated in either path kept tmux's default
   `window-size=latest`, which overrides the session-level `smallest`
   (the helper's own docstring says so), so the smallest connected client
   saw a clipped layout.  New `tmux.session_is_shared()` is the single
   definition — process variable when set, else the session's own
   environment — `set_shared_window_size()` uses it (and gained the
   `socket_path` pass-through its callers already have in effect), and
   `cli/session._session_is_shared()` now delegates to it so the bindings
   gate and the window option cannot drift apart.
   Tests: `TestSetSharedWindowSize` (process flag short-circuits the
   session query; session environment consulted when the process has
   none; private session is a no-op; `-S` forwarded to both queries).
   Run against the pre-fix module: the session-environment case fails
   with no `set-window-option` issued and the socket case fails on the
   missing pass-through; the other two describe behavior that is
   unchanged.

2. **`pm session kill` / `mobile` could not find a shared session from a
   shell pane in its grouped session.**  `_ambient_session_for_share_mode`
   treated "no `--global`/`--group` requested" as "private wanted", so an
   ambient session whose recorded mode was `global` was rejected.  A
   grouped session (`base~N`) has an empty *session* environment (tmux
   copies no session environment into a grouped session — verified on
   tmux 3.2a), so its panes fall back to the server's *global*
   environment.  That normally still carries `PM_SHARE_MODE` (the
   creating `pm session --global` process exported it), but not when the
   shell that started the server did not — the case the no-mode rule must
   handle — and the command then reported "No session found" for the very
   session hosting it.  A plain `pm session` already adopts a shared
   ambient session whatever its mode (`_resolve_start_session_name`), so
   the two commands now agree: no mode requested means "the session I am
   in".  A *requested* mode still
   rejects a mismatched ambient (the guard R9 depends on).
   *(b48f i2 correction: the original text said the shell pane "has no
   `PM_SHARE_MODE`".  It has none in its *session* environment, but a
   pane normally inherits the server global value — see the b48f i2
   section, which also records the residual for the genuinely-absent
   case: with a private twin of the same project running, the cwd
   candidate still wins.)*
   Tests: `TestResolveTargetSession::
   test_no_flag_targets_a_shared_ambient_session` (fails with the old
   comparison: only the cwd candidate is offered) and
   `::test_a_requested_share_mode_still_rejects_a_mismatched_ambient`.
   `qa.md` R9 gained the two corresponding bullets.

3. **The suite could still leak `PM_TMUX_SOCKET` across tests.**
   `tests/test_review_launch_retry.py::test_old_window_then_container_
   failure_retries_the_same_command` stubs the process-wide
   `subprocess.run`, so every `session_exists` probe succeeds and
   `_select_session_socket` exports the cwd-derived socket
   (`/tmp/pm-sessions/pm-project_manager-eab0d61a` when pytest runs in
   `/workspace`); nothing restored it.  The new `test_tmux.py` command
   assertion failed only in a full run (the same class the 2caf i10 note
   fixed inside `test_session_socket_isolation.py`, which is why that
   module carried its own snapshot fixture).  A new autouse
   `_restore_environment` in `tests/conftest.py` snapshots and restores
   the process environment around every test, so the class is closed
   suite-wide instead of one module at a time; the module-local copy in
   `test_session_socket_isolation.py` is removed.  The `test_tmux.py`
   cases also pin `PM_TMUX_SOCKET` to `""`, so their exact command
   assertions stay independent of a caller that runs the suite inside a
   pm pane.

Residual (pre-existing, unchanged here): a grouped session (`base~N`)
does not inherit the base session's environment at all, so a shell pane
the user opens in `~N` carries none of the session's variables.  The
layout paths now fall back to the base session's environment, and the
share-mode-dependent commands resolve the ambient session without it;
commands run in such a pane that key files by `get_session_tag()`
(e.g. `paths.session_dir()` with no tag) still compute the private tag.

Validation: targeted suites (`test_session_socket_isolation`,
`test_tmux`, `test_shared_sessions`, `test_cli_helpers`, `test_cli_qa`)
404 passed; full suite **5389 passed / 1 skipped** (419 s, log
`/pm-captures/review-2caf-i11/full-suite-final.log`; the run before the
conftest fixture failed exactly one case — the order-dependent
`test_tmux.py` assertion described in item 3).  The three behaviour tests
fail against the pre-fix module (checked in a worktree); the other new
cases describe behavior that is unchanged.
`pm/specs/pr-073910f/session_start_smoke.py` re-ran clean on a disposable
socket (private server, session env, global env and hooks correct; default
server untouched), and `pm session list` read-only ("No pm sessions
found.").
No live session, server or shared host configuration was touched — every
fixture used a disposable socket and a temporary HOME.

## Review iteration (2026-11-01, review-loop b48f i1)

First review pass over the head after the QA S14–S19 runs and the QA S17
fix (`6d6bb9e1d`).  No requirement changes.  Three fixes: one of the
"a user's own view is not a session of its own" class the earlier
iterations closed in discovery/detach/kill/QA-status, and two small
fail-loudly gaps on CLI surfaces this PR made socket-aware.

1. **TUI pane launches and rebalances were keyed by a view's name.**
   `pane_ops.get_session_and_window()` used the raw
   `tmux.get_session_name()` for the registry key, the EXIT-trap session
   and the window lookup.  tmux reports the most recently created session
   of a shared window for a pane (verified on this machine: with
   `pm-base` and `myview` grouped, `display-message -t <base pane>
   '#{session_name}'` returns `myview` while `'#{session_group}'` is
   `pm-base`), so while a user's own view exists (S118/S121/S124) — or a
   `pm-x~N` grouped session was created — the raw name is not the pm
   session.  `registry_path()` strips only the `~N` suffix, so a pane
   launched from such a TUI was registered in a phantom `myview.json`;
   the base registry never saw it (duplicate notes panes, and a TUI
   restart's `heal_registry` unaware of the live pane).  `pm-x~N` was
   harmless only because its suffix is stripped.  New
   `pane_ops._pm_session_for(app)` prefers `app._session_name` — the
   canonical base that `_session_for_claim` derives from
   `current_session_name()`, which already resolves the group — and falls
   back to `pane_registry.pm_session_name()` when the app has no session.
   `get_session_and_window()` keeps the *viewing* session's current window
   (`get_window_id(raw)`) so a new pane still opens where the user is
   looking, while the registry key, `launch_pane`'s dedup, the EXIT trap
   and `rebalance` all use the base.  `_launch_in_plans_window()` and
   `_focus_plans_window()` (same raw-name use, same phantom registry)
   take the base too; `select_window()` can then resolve the attached
   client's grouped session from the group instead of switching a view
   the client does not follow.  Tests:
   `TestPaneOpsSessionResolution` (four cases, all verified to fail on
   the pre-fix module: the raw `myview` was returned/registered/selected).
2. **`pm session mobile` without tmux** raised `FileNotFoundError` out of
   `session_exists` and surfaced as the generic
   `Error: [Errno 2] No such file or directory: 'tmux'`, unlike
   `pm session list` / `kill`, which print `tmux is not installed.` and
   exit 1.  It now does the same (`has_tmux()` guard).  Test:
   `TestSessionMobileServerSelection::test_requires_tmux`.
3. **`pm session kill --dir <dir>` fell back to the caller's cwd session**
   when the given directory has no session tag (not a git repo), so a
   mistyped `--dir` could kill a *different* project's session.  It now
   refuses with the same message `pm session --print-connect --dir` uses
   ("Cannot determine session from directory …").  `--dir` is the only
   caller of the destructive command that names its target explicitly, so
   there is no fallback to make.  Test:
   `TestSessionKillServerSelection::test_dir_without_a_session_tag_is_refused`
   (verified to kill the cwd-named session on the pre-fix code).

Validation: targeted suites (`test_session_socket_isolation`,
`test_tmux`, `test_cli_helpers`, `test_shared_sessions`, `test_cli_qa`,
`test_log_message_force`, `test_plans_window_per_plan`,
`test_plans_pane`, `test_log_pane_backlog`, `test_tui_imports`,
`test_tui_own_session_name`, `test_popup_session_code`,
`test_session_registry`, `test_pm_in_tmux_session`) 570 passed; full
suite **5397 passed / 1 skipped** (414 s, log
`/pm-captures/review-b48f-i1/full-suite-final.log`).  No
live session, server or shared host configuration was touched — every
fixture used a disposable socket or a temporary HOME, and the one live
tmux check used a throwaway socket under `/tmp`.

## Review iteration (2026-11-01, review-loop b48f i2)

Verification pass over the head after the b48f i1 fixes; no requirement
changes.  One vacuous test in the detach path, two small coverage gaps on
CLI error branches, and a factual correction to the shared-session
propagation notes this spec and `qa.md` carried.

1. **`test_failed_detach_is_not_reported_as_success` never reached the
   branch it is named for.**  Its fake resolved `#{session_group}` through
   the generic fallback (`"0"`), so the detach base became `0`, the
   attached client `pm-x` was not a candidate, and
   `detach_current_client()` returned `False` from the *"no attached
   client"* path — the test passed whether or not a rejected
   `detach-client` was reported as success.  Coverage of this test showed
   the whole detach attempt *and* the failure return missed; running the
   class showed the failure branch (`_log.warning(...); return False`,
   b972 i5) is executed by no test at all.  The fake now resolves the
   group to `pm-x` and the test asserts the detach was attempted on
   `/dev/pts/1`; verified to fail when the branch is changed to
   `return True`, and the branch is now covered.

2. **`pm session kill`'s no-tmux guard had no test** (unlike `list` and
   `mobile`, whose guards are tested).  New
   `TestSessionKillServerSelection::test_requires_tmux`: it asserts the
   `tmux is not installed.` message, exit 1, and that the session lookup
   is never attempted.

3. **`pm session --print-connect --dir <non-git dir>`'s refusal had no
   test** while `pm session kill --dir`'s (b48f i1) did.  New
   `TestPrintConnect::test_dir_without_a_session_tag_is_rejected` asserts
   the refusal and that no command is printed.

4. **Corrected the shared-session propagation claims in this document,
   `qa.md` and `tmux.session_is_shared()`'s docstring.**  The 2caf i11
   notes said a `run-shell` hook and a grouped-session pane have no
   `PM_SHARE_MODE`.  Verified on tmux 3.2a: the server *global*
   environment inherits it from the creating `pm session --global`
   process, so panes and `run-shell` commands normally do see it (a
   session's own environment is still empty for a grouped session, and
   `set-environment -g -u` really does remove it from a hook's
   environment).  The `session_is_shared()` session-environment fallback
   is still the right behaviour — it covers the contexts where the global
   environment lacks the variable (a server started by a client without
   it) and the process environment was cleared (`_set_share_mode_env`) —
   only the explanation was wrong.  `qa.md` R9's two bullets now say how
   to reach the fallback (unset it in the shell / remove it from the
   global environment) so the scenarios exercise it instead of passing
   through the process variable; the kill bullet also states the
   no-private-twin condition that the cwd-first rule (R3.2/R8) requires.

Nothing else surfaced.  The socket derivation and default-server
addressing (R4.3), discovery scoping (7af7 i1–i3, 3cc7 i1, 703c
i1/i4/i6, 2caf i4/i5), the precise detach (R5, 703c i3, 2caf i2), the
kill/unlink rules (R3.2, R8, 2caf i7), the socket-file and
socket-directory ownership checks (d1c0 i10/i12, 703c i2, 2caf i8,
QA S17) and the shared-session share-mode handling (d1c0 i7, 703c i8,
2caf i11) all match the spec, and every new helper has direct coverage.

Validation: targeted suites (`test_session_socket_isolation`,
`test_tmux`, `test_cli_helpers`, `test_shared_sessions`, `test_cli_qa`)
414 passed; full suite **5399 passed / 1 skipped** (419.8 s, log
`/pm-captures/review-b48f-i2/full-suite-final.log`).  The corrected
detach test was verified to fail when the failure branch returns `True`;
the two new tests exercise CLI error branches that existed before this
iteration.  `pm/specs/pr-073910f/session_start_smoke.py` re-ran
clean on a disposable socket (private server, session env, global env
and hooks correct; default server untouched).  No live session, server
or shared host configuration was touched — every fixture used a
disposable socket and a temporary HOME.

## Review iteration (2026-11-01, review-loop b48f i3)

Verification pass over the head after the b48f i2 fixes; no requirement
changes.  One destructive-path gap of the class R8 defines, plus coverage
for three "degrade, never crash" branches added by the recent iterations.

1. **`pm session kill` resolved the session exactly but killed by
   prefix.**  `find_exact_session_server` decided *whether* the session
   exists with tmux's `=name` target, but the kill itself was
   `kill-session -t <bare name>`.  A bare target is a *prefix* match:
   verified on tmux 3.2a that with only `pm-xyz` running,
   `kill-session -t pm-x` kills `pm-xyz` (the same rule that made
   `has-session -t pm-x` match a surviving `pm-x~1`, QA scenario 6).  The
   resolution is exact, but a base — or a group member — that vanishes
   between the lookup and the kill (a concurrent `pm session kill`, a
   manual `tmux kill-session`) leaves a bare target that tmux then
   resolves to whichever remaining session starts with the name.  On the
   legacy default server, which hosts every pre-isolation pm session,
   that can be another pm session's TUI — the cross-session damage this
   change exists to prevent.  `tmux.kill_session()` gained
   `exact=True` (tmux target `=name`) and `session_kill` passes it for
   the base and for every group member; the normal case is unchanged
   (the exact name always matches).  R8.1 above records the rule.
   Tests: `TestKillSession` (`test_bare_target_by_default`,
   `test_exact_target_uses_tmux_exact_syntax`) and
   `TestSessionKillServerSelection::test_kill_targets_are_exact` (every
   kill of the group + base carries `exact=True`); the two tests that
   assert the fix were verified to fail on the pre-fix tree in a
   worktree (`test_kill_targets_are_exact` recorded `False` for every
   kill).

2. **Coverage for the "degrade, never crash" branches in the newest
   discovery helpers** (the contract every earlier iteration established,
   but untested in these two functions):
   - `helpers._pm_session_of()`'s `OSError` fallback to the plain base
     name: `TestFindLiveTuiPane::
     test_group_resolution_degrades_when_tmux_cannot_be_queried`.
   - `helpers._registry_tui_pane()`'s `OSError` → no live pane:
     `TestFindTuiPaneAcrossServers::
     test_recorded_pane_probe_degrades_when_tmux_cannot_be_run`.
   - `pane_ops._pm_session_for()`'s two degrades (no session resolvable
     when tmux cannot be queried; base name when the group query fails):
     `TestPaneOpsSessionResolution::
     test_session_resolution_degrades_when_tmux_cannot_be_queried` and
     `::test_session_resolution_falls_back_to_the_base_name`.
   These document behaviour that is already correct; they passed on the
   pre-fix tree too (they close gaps, they do not fix a defect).

Nothing else surfaced.  The socket derivation and default-server
addressing (R4.3), discovery scoping (7af7 i1–i3, 3cc7 i1, 703c
i1/i4/i6, 2caf i4/i5), the precise detach (R5, 703c i3, 2caf i2), the
kill/unlink rules (R3.2, R8, 2caf i7, above), the socket-file and
socket-directory ownership checks (d1c0 i10/i12, 703c i2, 2caf i8,
QA S17) and the shared-session share-mode handling (d1c0 i7, 703c i8,
2caf i11) all match the spec, and every new helper has direct coverage.

Validation: targeted suites (`test_session_socket_isolation`,
`test_tmux`, `test_cli_helpers`, `test_shared_sessions`, `test_cli_qa`)
930 passed; full suite **5406 passed / 1 skipped / 0 failed / 0 errors**
(422 s, log `/pm-captures/review-b48f-i3/full-suite-final.log`).  Every
new test was checked in both directions where it asserts a fix (the two
exact-kill tests fail on the pre-fix tree in a worktree).
`pm/specs/pr-073910f/session_start_smoke.py` re-ran clean on a disposable
socket with `TMUX_TMPDIR` on a scratch dir (private server, session env,
global env and hooks correct; default server untouched).  No live
session, server or shared host configuration was touched — every
fixture used a disposable socket and a temporary HOME.

## Review iteration (2026-11-01, review-loop b48f i4)

Verification pass over the head after the b48f i3 fixes; no requirement
changes.  Two view-resolution gaps of the class the earlier iterations
closed elsewhere — both surfaces enumerate or name a session without
resolving it through its tmux session *group*, so a pane in a shared
window (tmux reports the most recently created session of that window:
`pm-base~1` in the normal case, a user's own view when one exists —
verified on tmux 3.2a) leaks the grouped/view name:

1. **`pm qa launch` named the pane's session in the QA prompt.**
   `tmux.get_session_name()` returns the grouped session (normally
   `pm-base~1`, or a user's view `myview`) for a pane in the base
   session's window.  The generated "Session Context" block tells the QA
   worker to run `pm tui view -s <session>` and to read
   `~/.pm/pane-registry/<session>.json`; both are keyed by the base pm
   session, so the registry path never existed and, with a view, `pm tui
   view -s myview` failed outright (the explicit-`-s` branch normalises
   only `~N`).  It now resolves through `pane_registry.pm_session_name`
   (the same resolution as `_get_current_pm_session`, with the usual
   `OSError` -> base-name degrade).  Tests:
   `test_qa_launch_names_the_base_pm_session[pm-base~1]` and `[myview]`.

2. **`list_clients_in_group()` could not see a user's own view.**
   It built the group as `{base} | list_grouped_sessions(base)`, i.e. only
   `base~N` by name, so `pm session --disconnect-others` left a client
   attached through a view (S118/S121/S124) connected — and that client
   still constrains the shared window's size, which is exactly what the
   flag exists to reclaim.  It now uses `sessions_in_group()`, the
   existing "every session in the group, by any name" helper the detach
   and kill paths already use.  Test:
   `TestListClientsInGroup::test_includes_a_users_own_view`.

Both new tests fail on the pre-fix tree (verified in a worktree at
7e9f072da: the prompt named `myview` / `pm-base~1`, and the view's client
was not listed).  Recorded as an incidental fix on the PR.

Validation: targeted suites (`test_session_socket_isolation`,
`test_tmux`, `test_cli_helpers`, `test_shared_sessions`, `test_cli_qa`,
`test_tui_imports`, `test_tui_pidfile`) 676 passed; full suite recorded
in the PR note for this iteration.  No live session, server or shared
host configuration was touched — every fixture used a disposable socket
and a temporary HOME.

## Review iteration (2026-11-01, review-loop b48f i5)

Verification pass over the head after the b48f i4 fixes; no requirement
changes.  One cross-server scoping gap in `_find_tui_pane()`'s fallback
scan — the same "a server is not a session" class earlier iterations
closed inside one server (2caf i4, 703c i6, 3cc7 i1), one level up:

1. **The fallback scan was scoped by session *name*, not by server.**
   When one of the discovery branches identified a session, the scan
   filtered `list_pm_sessions()` rows with `info["name"] == identified`
   and then scanned *every* matching row.  Two servers can host a
   session with the same name: an older pm binary run from a plain shell
   (where bare tmux follows the default server) creates a legacy twin of
   a session this build runs privately — it cannot see the private
   server — and both sessions share the pane-registry key.  Pane ids are
   only unique per server, so a stale recorded id can name a live,
   unrelated pane in the twin, and the scan handed that pane back to
   `pm tui send` (keys are delivered unscoped): the cross-server
   confusion this change exists to remove.  The scan is now scoped to
   `identified_server` — the server the identified session was actually
   found on — and still scans that server directly when
   `list_pm_sessions()` does not report it (its socket file was
   unlinked, or it is a legacy session whose rows carry `socket=None`
   while the selected server is the default server's explicit path).
   When the ambient socket cannot be resolved at all (no
   `PM_TMUX_SOCKET` and no pm socket in `$TMUX`), the name filter
   remains the only available scoping and is kept.  (b48f i6: for the
   in-tmux branch that last case is no longer reachable — `$TMUX` names
   the pane's server even when it is not a pm socket, so a legacy
   session's default server is resolved and the name filter is not
   used.  The name filter now only serves the cwd branch's
   prefix-match-without-a-host case.)  Test:
   `TestFindTuiPaneAcrossServers::
   test_scan_stays_on_the_identified_sessions_server`, verified to fail
   on the pre-fix tree at `0d88df775` (it returned the twin's `%9`).

Nothing else surfaced.  The socket derivation and default-server
addressing (R4.3), discovery scoping (7af7 i1–i3, 3cc7 i1, 703c
i1/i4/i6, 2caf i4/i5, above), the precise detach (R5, 703c i3, 2caf i2),
the kill/unlink rules (R3.2, R8, 2caf i7, b48f i3), the socket-file and
socket-directory ownership checks (d1c0 i10/i12, 703c i2, 2caf i8,
QA S17) and the shared-session share-mode handling (d1c0 i7, 703c i8,
2caf i11, b48f i2) all match the spec, and every new helper has direct
coverage.

Validation: targeted suites (`test_session_socket_isolation`,
`test_tmux`, `test_cli_helpers`, `test_shared_sessions`, `test_cli_qa`,
`test_tui_imports`, `test_tui_pidfile`, `test_tui_own_session_name`,
`test_plans_window_per_plan`, `test_plans_pane`, `test_log_pane_backlog`,
`test_session_registry`, `test_pm_in_tmux_session`,
`test_log_message_force`, `test_popup_session_code`) 715 passed; full
suite **5410 passed / 1 skipped** (427.7 s, log
`/pm-captures/review-b48f-i5/full-suite-final.log`).
`pm/specs/pr-073910f/session_start_smoke.py` re-ran clean on a disposable
socket (private server, session env, global env and hooks correct;
default server untouched).  No live session, server or shared host
configuration was touched — every fixture used a disposable socket and a
temporary HOME.

## Review iteration (2026-11-01, review-loop b48f i6)

Verification pass over the head after the b48f i5 fix; no requirement
changes.  One cross-server scoping gap, the mirror image of the case i5
closed:

1. **Inside a legacy session, discovery still scoped the scan by name.**
   A pre-isolation session lives on the default server and, by R6.1,
   nothing is propagated into its panes — so its panes carry no
   `PM_TMUX_SOCKET`, and `resolve_ambient_socket()` returned `None` even
   though `$TMUX` names the server the identified session is on.  The
   in-tmux branch therefore left `identified_server` unset and the
   fallback scan fell back to filtering `list_pm_sessions()` rows by
   *name*.  A private twin of the same session (an older pm binary, run
   from a plain shell where bare tmux follows the default server, creates
   one; it cannot see the private server) shares the pane-registry key,
   and pane ids restart per server — `%0` exists on both — so the scan
   could hand the twin's live pane back to `pm tui send`, the
   cross-session damage this change exists to remove.  i5 closed the
   direction "private session reached from outside scans a legacy twin";
   this closes "legacy session reached from inside scans a private
   twin".
   Fix: `tmux.socket_path_from_tmux_env()` and `resolve_ambient_socket()`
   gained `pm_only` (default `True`, so the startup export and every
   existing caller are unchanged).  The in-tmux branch resolves
   `identified_server` with `pm_only=False`: once the pane's session has
   been identified *as a pm session* (a legacy one is one), the server
   `$TMUX` names is by definition the server to scope the scan to — the
   default server, or a `tmux -L` server, by its own path.  The name
   filter is now only reachable from the cwd branch's
   prefix-match-without-a-host case (where it cannot cross servers: a
   row of the exact name on a private socket would have been found by
   `_select_session_socket` first).
   Test: `TestFindTuiPaneAcrossServers::
   test_legacy_ambient_session_scopes_the_scan_to_the_default_server`,
   verified to fail on the pre-fix tree at `cb7ea1bb5` (it returned the
   twin's `%0` instead of the legacy session's unregistered `%7`).

Nothing else surfaced.  The socket derivation and default-server
addressing (R4.3), discovery scoping (7af7 i1–i3, 3cc7 i1, 703c
i1/i4/i6, 2caf i4/i5, b48f i5, above), the precise detach (R5, 703c i3,
2caf i2), the kill/unlink rules (R3.2, R8, 2caf i7, b48f i3), the
socket-file and socket-directory ownership checks (d1c0 i10/i12, 703c
i2, 2caf i8, QA S17) and the shared-session share-mode handling (d1c0
i7, 703c i8, 2caf i11, b48f i2) all match the spec, and every new
helper has direct coverage.

Validation: targeted suites (`test_session_socket_isolation`,
`test_tmux`, `test_cli_helpers`, `test_shared_sessions`, `test_cli_qa`,
`test_tui_imports`, `test_tui_pidfile`, `test_tui_own_session_name`,
`test_plans_window_per_plan`, `test_plans_pane`, `test_log_pane_backlog`,
`test_session_registry`, `test_pm_in_tmux_session`,
`test_log_message_force`, `test_popup_session_code`) 716 passed; full
suite **5413 passed / 1 skipped** (411.4 s, log
`/pm-captures/review-b48f-i6/full-suite-final.log`).
`pm/specs/pr-073910f/session_start_smoke.py` re-ran clean on a disposable
socket (private server, session env, global env and hooks correct;
default server untouched).  No live session, server or shared host
configuration was touched — every fixture used a disposable socket and a
temporary HOME.

## Review iteration (2026-11-01, review-loop b48f i7)

Verification pass over the head after the b48f i6 fix; no requirement
changes.  Three fail-closed gaps in the socket-path/entry handling (the
shared-session start path, the single-entry read probe, and the default
server's `$TMUX_TMPDIR` resolution), plus one piece of dead code.

1. **A shared session's start followed a symlink planted at its socket
   path.**  `_resolve_session_socket()` refuses a socket *file* owned by
   another user, but only for private sessions — the check is skipped for
   `--global`/`--group` because a joiner does not own the sharing user's
   socket, and a uid check would refuse the joiner.  That left the shared
   path with no guard at all on the directory *entry*: `/tmp/pm-sessions`
   is world-writable, so another local user can create
   `pm-<shared-tag>` as a symlink to a server they run before pm ever
   does.  `tmux -S <path>` follows the link, so `pm session --global` (or
   a joiner running `--global --dir`) attached to that server, which then
   receives every keystroke typed into the session; a dangling link would
   have had pm bind its server socket at the attacker-chosen target
   *(b48f i8 correction: a tmux client follows the link when it
   *connects*, which is the hazard — the start path unlinks the entry and
   binds at the socket path, or fails under the sticky bit; see the
   review-loop b48f i8 section)*.
   A real socket is never a symlink — tmux binds a socket file — so the
   entry is now refused outright in **both** modes, before any probe or
   export, with a message naming the path (R12's scope sentence already
   required "symlinks planted at a session's socket path … must fail
   closed").  The private ownership check now reuses the same `lstat`
   result, so its dangling-link rationale still holds.
   Tests: `TestResolveSessionSocket::
   test_refuses_a_symlink_at_a_shared_socket_path` (new; fails on the
   pre-fix tree with "DID NOT RAISE" and, without the guard, exports the
   path and probes the link) and
   `::test_refuses_a_symlink_planted_at_the_socket_path`, rewritten to
   exercise the new guard rather than the uid check (it no longer fakes
   `getuid`, and asserts nothing is exported; also fails pre-fix).  The
   "socket owned by another user" test still covers the ownership check
   itself.

2. **`list_pm_sessions()` carried an unreachable de-duplication set.**
   `seen` keyed on `(socket_path, base)` could never hit: `groups` is a
   dict keyed by base within one `collect()` call, `glob("pm-*")` yields
   each socket path once, and the default server is collected once with
   `socket_path=None`.  Removed (the comment records why one row per
   session is structural).  No behaviour change; the existing listing
   tests cover the output.

An independent review of the change set then surfaced two more gaps in
the same fail-closed area:

3. **The *read* path still probed a symlink at the socket path.**
   `_find_session_server()` asked `session_exists(..., socket_path=<the
   deterministic path>)` without inspecting the entry.  `/tmp/pm-sessions`
   is 1777, so another user can create that path as a symlink to a server
   they run before ours exists; `tmux -S <link>` follows it, so
   `pm tui send/view -s <session>`, `pm session --print-connect`, the TUI
   connect popup and `pm session kill` all resolved to (and would drive or
   tear down) the attacker's server.  This is the same hazard the start
   path now refuses, one function earlier — `list_pm_sessions()` already
   skipped non-socket entries, but the single-entry probe did not.  It now
   `lstat`s the entry and probes only a real socket (or nothing, the
   normal before-the-first-start state); a link or any other entry is
   skipped, so the lookup falls through to the default server as it does
   for any absent private session.  Test:
   `TestFindSessionServer::test_does_not_probe_a_symlink_at_the_socket_path`,
   verified to fail on the pre-fix tree at `60b8ee116` (returned the
   symlink as a private server).
4. **`default_socket_path()` did not mirror tmux's `$TMUX_TMPDIR`
   fallback.**  tmux uses `$TMUX_TMPDIR` only when it is an absolute path
   to an *existing* directory; a missing or relative value makes it put
   the default server at `/tmp/tmux-<uid>/default` (verified on tmux
   3.2a: with `TMUX_TMPDIR=/tmp/nonexistent` the server landed at
   `/tmp/tmux-1000/default`, and a relative value behaved the same).
   `default_socket_path()` computed `<TMUX_TMPDIR>/tmux-<uid>/default`
   verbatim, so in that environment every legacy-session probe addressed a
   path no server uses: `pm session` started a duplicate private session
   beside the running legacy one (R6.1's "no private session alongside
   it"), and `pm session kill` / `list` did not see it.  Fail-closed, but a
   regression versus master, which let tmux resolve its own default.  The
   helper now mirrors the fallback (absolute + `isdir`, else `/tmp`).
   Tests: `TestDefaultSocketPath` (existing absolute dir, missing dir,
   relative value, unset/empty); the missing-dir and relative cases fail on
   the pre-fix tree, the other two describe unchanged behaviour.

Nothing else surfaced.  The socket derivation and default-server
addressing (R4.3), discovery scoping (7af7 i1–i3, 3cc7 i1, 703c
i1/i4/i6, 2caf i4/i5, b48f i5/i6), the precise detach (R5, 703c i3, 2caf
i2), the kill/unlink rules (R3.2, R8, 2caf i7, b48f i3), the socket-file
and socket-directory ownership checks (d1c0 i10/i12, 703c i2, 2caf i8,
QA S17, above) and the shared-session share-mode handling (d1c0 i7, 703c
i8, 2caf i11, b48f i2) all match the spec, and every new helper has
direct coverage.

Validation: targeted suites (`test_session_socket_isolation`,
`test_tmux`, `test_cli_helpers`, `test_shared_sessions`, `test_cli_qa`)
434 passed; full suite recorded in the PR note for this iteration.  The
start-path tests (item 1) were verified to fail on the pre-fix tree at
`670f2f08c`, the read-path and `TMUX_TMPDIR` tests (items 3-4) at
`60b8ee116`.
`pm/specs/pr-073910f/session_start_smoke.py` re-ran clean on a disposable
socket (private server, session env, global env and hooks correct;
default server untouched).  No live session, server or shared host
configuration was touched — every fixture used a disposable socket and a
temporary HOME.

Residual (pre-existing, non-blocking, unchanged here): the prefix
pane-switch bindings (`prefix` + arrow / `o`) are gated by an `if-shell`
test on `~/.pm/pane-registry/<#{session_name}>.json`.  A user's own view
(S118/S121/S124) has no registry file of its own, so the gate falls back
to tmux's plain `select-pane` and pm's mobile-aware zoom is not applied
when the user drives the session through such a view.  The key still
switches panes correctly, and this predates the per-session-server work;
fixing it means teaching the shell-side gate (and `_pane-switch`'s own
session argument) to resolve the group, which is a key-binding change
outside this PR's scope, so it is left as a known limitation rather than
changed here.

Also recorded (pre-existing root cause, filed as pr-6de8207): the
`~`-truncation residual noted in review-loop 0e4c i1 now also reaches the
socket derivation — `session_socket_for()` strips a grouped `~N` suffix
with the same first-`~` rule as `base_session_name()`, so two repo
directories whose names share the prefix before a `~` (`proj~a`,
`proj~b`) derive the same socket *and* the same registry key, as well as
the same truncated session name.  The fix belongs in `get_session_tag()`
(sanitise the tag), where that residual already points; changing the
socket derivation alone would not separate the registries (and would have
to distinguish a grouped suffix from a `~` in the repo name, which is the
same ambiguity).

## Review iteration (2026-11-01, review-loop b48f i8)

Verification pass over the head after the b48f i7 follow-up; no
requirement changes.  One factual correction to the symlink rationale
and one test gap in the fail-closed socket-directory guard.

1. **The dangling-symlink rationale was wrong about the start path.**
   R7.3 and the b48f i7 / d1c0 i10 sections said a dangling link planted
   at a session's socket path "would have pm bind its socket at the
   attacker-chosen target".  Verified on tmux 3.2a (tmux has unlinked the
   path before binding for a long time): the hazard is that a tmux
   *client* follows the link when it connects — `tmux -S <link>
   new-session` created the session on the linked live server, verified —
   which is exactly what the both-modes refusal prevents.  The start path
   never binds at the link's target: tmux unlinks the entry and binds at
   the socket path itself, and in the threat-model case (another user's
   link in the sticky 1777 directory) the unlink fails and `new-session`
   exits with "error connecting to … (Permission denied)" — verified with
   a root-owned dangling link — so nothing is created anywhere.  R7.3 now
   says "attach to, and create the session on" instead of "attach to (or
   bind at)", with correction notes on the two earlier passages.  The
   refusal is unchanged and still required.
2. **`paths.shared_socket_dir_is_usable()`'s refusal branch had no
   test.**  It is the read-path counterpart of `ensure_socket_dir`'s
   directory refusal (2caf i8): discovery, `--print-connect` and
   `pm session kill` must not probe through a symlinked (or otherwise
   non-directory) `/tmp/pm-sessions`, or another user's server there
   would be adopted (QA scenario 17).  Nothing in the suite asserted it:
   `TestFindSessionServer`'s symlink test covers the per-*entry* check
   with a real directory, and the listing/directory tests cover other
   callers.  Added `TestSharedSocketDirIsUsable` (missing = the normal
   first-run state, real directory, symlink to a directory, regular
   file) and
   `TestFindSessionServer::test_symlinked_socket_dir_is_not_probed`,
   which plants a *real* socket inside the link's target (so only the
   directory guard can stop the probe — a plain file would be skipped by
   the per-entry check too) and asserts the private path is never probed
   and the default server is the answer.  Verified non-vacuous: with
   `shared_socket_dir_is_usable()` forced to True the probe list becomes
   `[<link>/pm-repo-abc, None]`.

Nothing else surfaced.  The socket derivation and default-server
addressing (R4.3), discovery scoping (7af7 i1–i3, 3cc7 i1, 703c
i1/i4/i6, 2caf i4/i5, b48f i5/i6), the precise detach (R5, 703c i3, 2caf
i2), the kill/unlink rules (R3.2, R8, 2caf i7, b48f i3), the socket-file
and socket-directory ownership checks (d1c0 i10/i12, 703c i2, 2caf i8,
QA S17, b48f i7, above) and the shared-session share-mode handling (d1c0
i7, 703c i8, 2caf i11, b48f i2) all match the spec, and every new helper
has direct coverage.

Validation: targeted suites (`test_session_socket_isolation`,
`test_tmux`, `test_cli_helpers`, `test_shared_sessions`, `test_cli_qa`)
439 passed; full suite **5424 passed / 1 skipped** (423 s, log
`/pm-captures/review-b48f-i8/full-suite-final.log`).  No live session,
server or shared host configuration was touched — every fixture used a
disposable socket and a temporary HOME; the tmux behaviour checks above
used disposable sockets under a scratch directory.

## Review iteration (2026-11-01, review-loop b48f i9)

Verification pass over the head after the b48f i8 fixes; no requirement
changes.  One resolution bug in `default_socket_path()`, one cross-user
hole in the implicit socket lookups (the PR's own residual note about it
was factually wrong), and two doc/test tidies.

1. **`default_socket_path()` ignored an existing *relative*
   `$TMUX_TMPDIR`.**  tmux `realpath()`s the value — so a relative value
   is resolved against the client's cwd — and uses the result when it is
   an existing directory.  Verified on tmux 3.2a: from `/tmp/proj` with
   `TMUX_TMPDIR=reltmp` (existing) the default server binds at
   `/tmp/proj/reltmp/tmux-<uid>/default`.  The b48f i7 check used a
   *missing* relative path, where `realpath` fails and `/tmp` is right,
   so its "relative behaves like missing" note was one case too broad.
   The helper now resolves first (`Path(base).resolve()`; an unreadable
   value or a symlink loop counts as unusable) and answers `/tmp` only
   when the result is not a directory.  A legacy session in such an
   environment was invisible: `pm session` created a duplicate private
   session beside it (R6.1/R10), `pm session list` omitted it and
   `pm session kill` reported "No session found".
   Tests: `TestDefaultSocketPath::test_uses_an_existing_relative_value`
   (fails on the pre-fix tree at `df064decb`) and the missing-relative
   case renamed to pin the fallback.

2. **The socket-ownership guard did not cover the read/discovery
   path.**  `_resolve_session_socket()` refuses a private socket owned by
   another user, but `tmux._find_session_server()` — the resolver behind
   every read path — checked only that the entry was a socket (the b48f
   i7 symlink guard).  `/tmp/pm-sessions` is 1777 and the deterministic
   name is derivable (or visible in the listing), so another user can run
   a server there under the session's own name and chmod its socket
   0777; tmux < 3.3 has no `server-access` ACL, so a victim's lookup
   connects and adopts it.  Concrete damage: `pm tui view` / `pm tui
   send` from a plain shell drive the attacker's TUI (the victim's keys
   go to it); `pm pr start`, `pm meta`, `pm container build` and
   `pm session home` create windows and run commands on the attacker's
   server; `pm session kill` tears the planted session down instead of
   the user's own legacy one.  The residual note above claimed other
   paths fail closed because "a 0600 socket owned by another user cannot
   be connected to" — wrong: the attacker owns the socket and chmods it.
   `find_session_server()` / `find_exact_session_server()` gained
   `owned_only`: the private probe runs only for a socket this user owns,
   and an absent entry is not probed either (an attacker could create it
   between the `lstat` and the connect, and a running private server
   always has its socket bound).  Implicit lookups pass it —
   `_select_session_socket` from the cwd branch of `_find_tui_pane` and
   from `_get_pm_session`, the private start path, the TUI connect screen,
   and (via `session._owned_only_for_target`) `pm session --print-connect`
   / `kill` / `mobile`, including candidate selection and the exact
   destructive lookup.  The gate is `helpers._private_session_context()`
   (`PM_SHARE_MODE` unset), so `--global`/`--group` invocations and panes
   of a shared session keep reaching the sharing user's socket (the
   documented joiner flow); `_owned_only_for_target` additionally exempts
   the session the process is running inside, because a pane of a
   *grouped* session carries no `PM_SHARE_MODE` (tmux copies no session
   environment into a grouped session) and a joiner is already attached to
   that server.  Explicit `-s` lookups are unchanged.  The name-only
   fallback scan in `_find_tui_pane` (reached only when the identified
   session's server cannot be resolved) is ownership-filtered in a
   private context too, so a same-named planted row is not scanned.
   `--print-connect` additionally
   refuses to print a command that would attach through a planted entry
   when no server of ours was found: a symlink (in both modes — a real
   socket is never a link) and, in a private context, a socket another
   user owns; an absent or stale entry still prints the deterministic
   command (the normal before-the-first-start state).  Tests:
   `TestFindSessionServer` (owned socket probed, foreign socket skipped,
   absent entry not probed, explicit lookup still probes), the cwd-branch
   and `_get_pm_session` wiring, the kill and `--print-connect` wiring
   for private vs shared contexts, and the two print refusals.  The
   fixtures bind real AF_UNIX sockets in `tmp_path`; no live session,
   server or shared host configuration was touched.

   Residual (pre-existing, unchanged): the *shared* start path skips the
   uid check by design (a joiner does not own the sharing user's socket),
   so a planted real socket at a shared tag's path is indistinguishable
   from the owner's; this exposure predates the PR (`shared_socket_path`
   already used the same world-writable directory) and closing it would
   break joining.

3. **Doc/tidy.**  qa.md R12 listed the "symlink at a session's socket
   path -> `pm session list`" story twice (the earlier bullet already
   covers regular files *and* symlinks); the duplicate is removed.
   `paths.shared_socket_dir_is_usable()`'s unreadable-entry branch (fail
   closed) had no test; added one.  qa.md R10/R12 and R7.3 record the
   `$TMUX_TMPDIR` resolution and the read-path ownership rule.

Validation: targeted suites (`test_session_socket_isolation`,
`test_tmux`, `test_cli_helpers`, `test_shared_sessions`, `test_cli_qa`)
457 passed; full suite **5442 passed / 1 skipped** (423 s, log
`/pm-captures/review-b48f-i9/full-suite-final.log`; +18 tests).  On a
worktree of the pre-fix head `df064decb`, the new tests that assert the
fix fail (the relative-`$TMUX_TMPDIR` assertion; the owned-only ones with
`TypeError: find_session_server() got an unexpected keyword argument
'owned_only'`; the two print refusals with exit code 0), while the tests
that pin *unchanged* behaviour (explicit `-s`, a shared context, a kill
from inside the session, the not-yet-started print) pass on both trees.
A direct comparison script on the two trees shows the pre-fix
`default_socket_path()` answering `/tmp/tmux-<uid>/default` for an
existing relative `$TMUX_TMPDIR` and `find_session_server()` returning
the planted socket, against the resolved path and `(None, False)` after
the fix.  `pm/specs/pr-073910f/session_start_smoke.py` re-ran clean on a
disposable socket.  No live session, server or shared host configuration
was touched.

## Review iteration (2026-11-01, review-loop b48f i10)

Verification pass over the head after the b48f i9 fixes; no requirement
changes.  Two gaps: the destructive path's socket cleanup still traversed
a planted socket directory, and the QA status pane's fallback session
list truncated a session name containing a space.

1. **`pm session kill` probed and unlinked through a planted socket
   directory.**  The b48f i9 rule is that the socket directory must be a
   real directory (a link or a file planted in world-writable `/tmp` is
   refused by the create path and by every read path), but the kill's
   cleanup still ran `server_alive(socket_path)` — `tmux -S` follows the
   link — and then `Path(socket_path).unlink()`, which deletes a file
   *inside* the link's target.  Verified live on a disposable directory
   standing in for `/tmp/pm-sessions`: a file at the deterministic name
   inside the link's target, `pm session kill` reported "No session
   found" and removed that file.
   The same branch also probed a planted *symlink at the socket path*
   (the b48f i7 rule discovery follows), and both branches would have
   touched a socket another user owns.  New
   `session._removable_private_socket()` applies the three checks once
   (real socket directory via `shared_socket_dir_is_usable()`, no
   symbolic link at the entry, the entry is a socket or plain file owned
   by this user); both unlink sites use it, so a hostile entry is neither
   probed nor removed.  The normal states are unchanged: a stale socket
   we own is removed once no server answers on it, and a live one is
   kept.  Tests:
   `TestSessionKillServerSelection::test_missing_session_does_not_touch_through_a_symlinked_socket_dir`,
   `::test_missing_session_does_not_probe_a_planted_symlink` and
   `::test_missing_session_does_not_touch_another_users_socket` (all
   verified to fail on the pre-fix head: the file was removed and
   `server_alive` was probed).

2. **The QA status pane could not find a grouped session whose name
   contains a space.**  `qa_status._find_attached_session()`'s priority 2
   parsed `list-sessions` with a space separator, so
   `pm-my repo-abc~1 1` was read as `pm-my`: the attached grouped session
   was never matched and the *base* session's window was switched
   instead — which the user's client does not follow (each session in a
   group keeps its own current window), so the status pane silently
   failed to bring its window forward.  This is the parser class the tmux
   helpers were fixed for (2caf i5/i10): the fields are now
   `:`-separated, which tmux forbids in session names.  Test:
   `TestQaStatusSocketRouting::test_finds_a_grouped_session_whose_name_has_a_space`
   (verified to fail on the pre-fix head: it returned the base name).

Validation: targeted suites (`test_session_socket_isolation`,
`test_tmux`, `test_cli_helpers`, `test_shared_sessions`, `test_cli_qa`,
`test_qa_background_focus`, `test_qa_resume`) 571 passed; full suite
**5446 passed / 1 skipped** (422.7 s, log
`/pm-captures/review-b48f-i10/full-suite-final.log`; +4 tests).  The kill
cleanup was verified end to end against a disposable symlinked socket
directory (the pre-fix tree removed the file inside the link's target;
the fixed tree leaves it and probes nothing), and the normal kill path
against a real disposable server (group killed, server exits, socket
file removed); the planted-link and qa_status cases are unit-level.  No
live session, server or shared host configuration was touched — every
fixture used a disposable socket directory or a temporary HOME.

## Review iteration (2026-11-01, review-loop b48f i11)

Verification pass over the head after the b48f i10 fixes; one
cross-project defect, the same "a session name is not a tag prefix"
class earlier iterations closed for spaces, pipes and user views.

1. **A `~` in the session tag collapsed two projects onto one tmux
   server.**  `~` separates grouped sessions (`base~N`), and every
   "strip the grouped suffix" site split at the *first* `~`.  A session
   name is `pm-<repo name>-<hash>`, and the repo directory name may
   contain `~` (`pm-my~repo-abc123`), so:
   - `tmux.session_socket_for()` derived `/tmp/pm-sessions/pm-my` for
     both `pm-my~repo-abc123` and `pm-my~other-def456` — two unrelated
     projects sharing one server, which R1 forbids (verified live: one
     socket, four sessions);
   - `pane_registry.registry_path()`, the TUI pidfile/command queue, the
     TUI history file, the layout file and the merge-restart marker were
     all keyed by the truncated `pm-my`, so two live TUIs shared one
     registry file;
   - `pm session list` reported one row named `pm-my` for both sessions
     (R3.3: one row per session, named correctly);
   - `list_grouped_sessions()`'s ordering and
     `next_grouped_session_name()` read `repo` for a number, so the
     grouped-session counter never advanced past `~1`;
   - `wrapper._ipc_session_tag()` resolved `~/.pm/sessions/<tag>/` from
     the truncated tag for hook/popup invocations.

   New `paths.base_session_name()` is the single definition — only a
   numeric `~N` suffix is stripped, so it is idempotent and a `~` in the
   tag is data.  `pane_registry.base_session_name()` delegates to it,
   and every site above uses it (the wrapper repeats the two-line rule
   inline because it runs before `pm_core` is imported, and the copy is
   pinned by a test).  `tmux._grouped_suffix()` reads the part after the
   *last* `~` for the ordering/next-name helpers.

   Verified live on tmux 3.2a with two disposable `~` repos: two
   distinct sockets, one row each under its full name, `~N` numbering
   advancing to `~3`, and `pm session kill` tearing down only its own
   group and socket.  New tests: `TestBaseSessionName` (suffix rule,
   idempotence, registry keys stay distinct),
   `TestSessionSocketFor::test_a_tilde_in_the_tag_is_not_a_grouped_suffix`,
   `TestListPmSessions::test_lists_two_sessions_whose_tags_contain_a_tilde`,
   `TestListGroupedSessions::test_base_name_may_contain_a_tilde`,
   `TestNextGroupedSessionName` (two cases),
   `TestWrapperIpcSessionTag` (three cases) and
   `TestMergeRestartMarkerSessionScope::test_tilde_in_the_tag_is_not_a_grouped_suffix`;
   all of them fail on the pre-fix head (verified in a worktree of
   `12c46553a`, the only passes being the unchanged-behaviour cases).

Residual (incidental, filed as pr-bebe64b — not this PR's scope): tmux
rewrites `:` and `.` to `_` in session names, so a repo whose name
contains either produces a session pm cannot address by its computed
name (`pm session` crashes with "duplicate session" on every re-run,
`pm session kill` reports "no session", and `pm session list` shows the
rewritten name).  Pre-existing and unrelated to the socket scheme, but
the deterministic socket is derived from the same name, so a naming
policy (sanitize or reject) is needed; that is a separate decision.
