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
`current_or_base_session`) must all run against the same socket. They already
accept `socket_path` and otherwise fall back to `PM_TMUX_SOCKET`; R1 makes
that variable always present. `_session_start()` must pass the computed
`socket_path` explicitly on the create/attach path (as it does for shared
sessions today).

### R3 — Locate sessions by socket (attach/list/discovery)

1. `pm session` (attach) uses the deterministic socket for the target tag; no
   ambient-state guessing. `--print-connect` prints `tmux -S <socket> attach`
   for private sessions too (not only shared ones).
2. `pm session kill` targets the same socket, kills grouped sessions then the
   base, unlinks the socket file (tmux leaves it behind after `kill-server` /
   last-session exit — verified), and also cleans up a legacy default-server
   session with the same name if present.  Session selection tries the
   cwd-derived name first and the ambient session second, choosing the first
   that is actually running — so a workdir clone kills the session hosting it,
   while a different project's ambient session is never preferred over the
   cwd's live one.
3. New `pm session list` enumerates pm sessions across **all** pm servers:
   every `pm-*` socket in `/tmp/pm-sessions/` plus the default server
   (legacy). It reports base session name, socket, attached client count,
   and marks shared sessions. Stale/foreign sockets are skipped, not fatal.
4. `pm_core/cli/helpers.py::_find_tui_pane()` (used by every `pm tui`
   subcommand) resolves the server for an explicit `--session`, the current
   pane, the cwd-derived session, and finally scans all pm servers for a
   live TUI pane. It selects `PM_TMUX_SOCKET` for the found session before
   returning, so callers' `tmux_mod` calls hit the right server.
5. `pm_core/tmux.py` gains `list_pm_sessions()` and
   `socket_path_from_tmux_env()`; `pm_core/paths.py` gains
   `session_socket_path()` / `ensure_socket_dir()`.

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
4. Fix `pm_core/qa_status.py::_find_attached_session()` / `_switch_to_window()`
   to build tmux argv with `tmux_mod._tmux_cmd(...)` instead of bare `tmux`,
   so QA panes on a private server switch the right client.
5. Do not rely on `display-popup` propagating `PM_TMUX_SOCKET` (existing QA
   note pr-2d0588a); the `$TMUX` resolver in (1) is the contract.

### R5 — Fix the actual detach bug

`pm_core/tui/pane_ops.py::quit_app()` must never run bare `detach-client`.
New `tmux_mod.detach_current_client()`:

1. Read `$TMUX_PANE`, resolve its window (`pane_window_id`).
2. `list-clients` on the session's server; keep clients whose
   `client_session` is the base session or a `base~N` grouped session **and**
   whose session's active window equals the TUI pane's window.
3. Detach the most recently active candidate by TTY
   (`detach-client -t <tty>`). Ties are resolved by `client_created`.
4. If no candidate matches, fall back to `detach-client -s <session>` for the
   first attached session in the group; if none, do nothing.
5. Return whether a client was detached; `quit_app()` still calls `app.exit()`
   when not in tmux.

This keeps a multi-client attach within one pm session working and, combined
with the private server, cannot reach another pm session.

### R6 — Rollout safety (existing live sessions)

New sessions get private servers. Existing sessions on the default server
must be left untouched:

1. If the private socket has no session **and** a session with the same name
   exists on the default server, `_session_start()` attaches to the legacy
   session (env `PM_TMUX_SOCKET` cleared) and prints a one-line note that
   `pm session kill` + `pm session` migrates it. No migration, no detach, no
   restart, no kill is performed automatically.
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
   existing socket file owned by another UID (shared sessions skip this
   check — the sharing user owns the socket by design).

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
