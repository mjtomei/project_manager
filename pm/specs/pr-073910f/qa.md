# QA spec — pr-073910f: Per-session tmux server isolation

## Scope

Every pm session now gets its own tmux server (a socket at
`/tmp/pm-sessions/pm-<tag>`) instead of sharing the user's default server.
The user-visible consequences are:

- a pm session is no longer reachable through a bare `tmux attach`;
- session discovery, connect commands, kill, mobile and TUI-driving
  commands must find a session by its socket;
- nothing a session does (driving the TUI, quitting, hooks, popups,
  killing the session) may reach a pane, client or server belonging to a
  different pm session;
- pre-existing sessions that still live on the default server keep
  working, untouched, until the user kills them.

The implementation also tightens a second class of hazard in the same
code: the socket directory is world-writable, so sockets owned by another
user, symlinks planted at a session's socket path, and a non-sticky
world-writable directory must fail closed rather than be used.

## Shared resources touched by this change

These are the single-name resources multiple actors reach at once; every
one of them must be exercised by a scenario where two or more actors act
simultaneously.

1. **`/tmp/pm-sessions/`** — created, chmod'd and scanned by every
   `pm session` start, `pm session list` and `pm session kill`. World
   writable (1777). Contents are created by different processes and by
   different users.
2. **`/tmp/pm-sessions/pm-<tag>`** — the socket file for one session. One
   tmux server binds it; CLI processes, panes, hooks and popups all
   connect to it; `pm session kill` may unlink it.
3. **The default tmux server** (`$TMUX_TMPDIR`/`/tmp` + `tmux-<uid>/default`)
   — hosts legacy pre-isolation pm sessions and any unrelated tmux
   sessions the user has. Isolation code must never mutate it implicitly.
4. **`PM_TMUX_SOCKET`** — written into the process environment, into the
   tmux session environment, and into the server's global environment;
   read by every tmux call. Multiple writers, many readers.
5. **`$TMUX`** — inherited by panes, `run-shell` hooks and
   `display-popup` bodies; resolved into `PM_TMUX_SOCKET` at entry.
6. **The pane registry** (`~/.pm/sessions/<tag>/…`) — one file per
   session, keyed by the *base* session name; written by the TUI, read by
   every discovery path.
7. **tmux pane ids (`%N`)** — now only unique *within* one server, while
   `pm tui send` delivers keys to a bare pane id.
8. **Per-server tmux state** — hooks (`set-hook -g`), global environment,
   windows, grouped sessions. Two servers must never share any of it.
9. **Session-keyed artifacts** — TUI pidfile, frame/history files,
   containers and push proxies cleaned up by `pm session kill`.

## Requirements

Each requirement is a Given/When/Then user story. "User" means a person
at a terminal driving pm; "plain shell" means a shell not inside any tmux
pane unless stated otherwise.

### R1 — Each pm session runs on its own tmux server

- **GIVEN** two independent pm projects (each initialised with `pm init`)
  and no pm session running for either,
  **WHEN** the user starts `pm session` in project A and then in project B
  from a plain shell,
  **THEN**
  - two distinct tmux servers are running, one per session;
  - each has a socket file under `/tmp/pm-sessions/` whose name contains
    the session's tag;
  - the user's default tmux server gained no pm session;
  - each session's panes carry the session's own socket in their
    environment.

### R2 — `pm session` is idempotent and never duplicates a session

- **GIVEN** project A's pm session is already running on its private
  server,
  **WHEN** the user runs `pm session` again from a plain shell in A's
  directory, and then runs it again from a shell inside one of A's panes,
  **THEN** both invocations attach to the existing session on the existing
  server; no second session, no second server, and no second TUI appear;
  `pm session list` still shows exactly one row for A.

### R3 — `pm session list` enumerates every pm session across servers

- **GIVEN** several pm sessions are running: at least one modern private
  session with an attached client, one with two attached clients, and one
  legacy session on the default server,
  **WHEN** the user runs `pm session list` from a plain shell,
  **THEN**
  - there is exactly one row per session (base name, not one per grouped
    session);
  - the client count covers the whole session group;
  - each row names the socket that hosts it, and the legacy row is marked
    as living on the default server;
  - running the same command from *inside* a pm pane lists the same set —
    in particular the current session is not listed a second time as a
    default-server session.

### R4 — Connect commands name the right server

- **GIVEN** a running private pm session for project A,
  **WHEN** the user runs `pm session --print-connect` from a plain shell in
  A's directory (and again from inside A's own pane),
  **THEN** it prints a `tmux -S <A's socket> attach` command that, pasted
  into a plain shell, attaches to A's session.
- **GIVEN** the same session, **WHEN** the user presses the TUI's connect
  key, **THEN** the popup shows the same socket-addressed command.
- **GIVEN** a legacy session on the default server, **WHEN** the user asks
  for the connect command either way, **THEN** the printed command names
  the default server's socket *and* the session (`… attach -t <session>`),
  so it still works when pasted inside another pm pane.

### R5 — Grouped sessions keep working on the private server

- **GIVEN** project A's pm session is running and attached,
  **WHEN** a second terminal attaches to the same session,
  **THEN** the second client is placed in a grouped session (`~1`) on the
  same private server, sees the same windows and panes, and the session's
  layout is rebalanced for both clients.
- **GIVEN** that two-client session, **WHEN** the user toggles mobile mode
  or switches windows,
  **THEN** both grouped sessions follow; `pm session list` still shows one
  row with two clients.
- **GIVEN** the same, **WHEN** one client presses the TUI quit key,
  **THEN** only that client detaches; the other client stays attached and
  the TUI keeps running.

### R6 — Quitting a TUI never detaches anyone else

- **GIVEN** two different pm sessions (A and B) each have an attached
  client,
  **WHEN** the user presses the TUI quit key in session A,
  **THEN**
  - A's client detaches and A's session keeps running (panes and TUI
    intact);
  - B's client remains attached, B's TUI keeps rendering, and B's windows
    and panes are unchanged.
- **GIVEN** one session with two attached clients,
  **WHEN** one of them quits,
  **THEN** the other client stays attached (see R5).
- **GIVEN** an unattached session whose TUI is still running,
  **WHEN** the quit key is pressed from a client that is not attached to
  it (or no client at all),
  **THEN** nothing is detached server-wide; the TUI reports that there was
  nothing to detach and stays usable.

### R7 — TUI discovery and driving stay inside one session

- **GIVEN** pm sessions A and B are running, each with a live TUI,
  **WHEN** the user runs `pm tui view` / `pm tui send <key>` / `pm tui
  frames` from a plain shell,
  **THEN** the command addresses a session that exists and reports which
  session and pane it used; it never errors out because the session lives
  on a private server.
- **GIVEN** the same two sessions, **WHEN** the user runs `pm tui send
  <key> -s pm-B` from inside session A's pane,
  **THEN** the key lands in B's TUI and A's TUI does not react.
- **GIVEN** the user types a session name that is not running (a stale or
  mistyped `--session`), **WHEN** they run `pm tui send` or `pm tui view`,
  **THEN** it reports that no TUI pane was found instead of driving a pane
  of whatever session happens to be current.
- **GIVEN** a grouped session name (e.g. `pm-x~2`) is passed to a
  session-keyed command, **WHEN** the user runs `pm tui frames -s
  pm-x~2`, **THEN** it reads the base session's frames (the files the TUI
  actually wrote) rather than reporting nothing.
- **GIVEN** a regression test exists and its session's TUI pane is gone,
  **WHEN** the user runs `pm qa regression <id>`, **THEN** it refuses with
  a "no TUI pane found" style message and launches nothing.

### R8 — Killing a session tears down only that session

- **GIVEN** pm sessions A and B are running, each with an attached client
  and live panes,
  **WHEN** the user runs `pm session kill` in project A,
  **THEN** A's grouped sessions and base session are gone, A's socket file
  is removed, and B's session, server, clients, panes and TUI are
  untouched.
- **GIVEN** a session whose base session was killed elsewhere but whose
  grouped session still has a client,
  **WHEN** the user runs `pm session kill` (which reports no session for
  that name), **THEN** the live server's socket file is *not* removed and
  the client is not stranded.
- **GIVEN** a stale socket file left behind by a dead server,
  **WHEN** the user runs `pm session kill`, **THEN** it reports no session
  and removes the stale file; a later `pm session` starts a fresh server
  at the same path.
- **GIVEN** any of the above, **WHEN** the kill completes,
  **THEN** the default tmux server and any unrelated non-pm tmux sessions
  are unaffected.

### R9 — Shared (`--global` / `--group`) sessions still work

- **GIVEN** user A creates a session with `pm session --global` in a
  project,
  **WHEN** A asks for the connect command and lists sessions,
  **THEN** the command names the shared session's socket, the session
  appears in the list marked as shared, and its socket is accessible to
  other users.
- **GIVEN** that shared session, **WHEN** a second user joins with `pm
  session --global --dir <A's project>`,
  **THEN** they attach to the *same* session on the same server and see
  A's windows.
- **GIVEN** A also has a private session for a different project,
  **WHEN** A runs `pm session --global` from inside the private session,
  **THEN** it attaches to / creates the shared session, not the private
  one.
- **GIVEN** the same situation, **WHEN** A runs `pm session kill --global`
  from inside the private session, **THEN** the private session is not
  killed (the command targets only the shared session, or reports none).
- **GIVEN** a shared session and a private session are both running,
  **WHEN** the user lists sessions, **THEN** exactly the shared row
  carries the shared marker.

### R10 — Existing (legacy) sessions are preserved, not migrated

- **GIVEN** a pm session created before this change — a tmux session with
  the pm session's exact name running the pm TUI on the *default* server,
  with no private socket,
  **WHEN** the user runs `pm session` in that project's directory,
  **THEN** it attaches to the existing legacy session on the default
  server and prints a one-line note explaining that the session predates
  per-session servers and can be moved by killing and restarting it; no
  private session is created alongside it and the legacy session is not
  detached, restarted or killed.
- **GIVEN** that legacy session plus a modern private session for another
  project, **WHEN** the user runs `pm tui send <key> -s <legacy>` from
  inside the *private* session's pane, **THEN** the key reaches the legacy
  session's TUI and the private session's TUI does not react.
- **GIVEN** the same pair, **WHEN** the user runs `pm session kill` in the
  legacy project, **THEN** the legacy session is killed and its
  default-server entry disappears from `pm session list`, while the
  private session and its server are untouched.

### R11 — Panes, hooks and popups address their own server

- **GIVEN** pm sessions A and B are running,
  **WHEN** the user, from a shell inside one of A's panes, runs pm
  commands that address tmux by session name (e.g. `pm session name`,
  `pm session list`, `pm tui view` with no `--session`, `pm session
  mobile`),
  **THEN** they act on A's server and never on B's, and `pm session list`
  still reports the default server as empty of pm sessions.
- **GIVEN** the same, **WHEN** the user opens an extra pane in A and then
  closes it (the pane-opened / pane-closed hooks fire),
  **THEN** A's layout and registry update and B's panes, layout and
  registry are unchanged.
- **GIVEN** an ordinary (non-pm) tmux session the user also has,
  **WHEN** pm commands run inside it,
  **THEN** they are not redirected to any pm socket and that session is
  left alone.

### R12 — The socket directory fails closed

- **GIVEN** `/tmp/pm-sessions` exists but is world-writable *without* the
  sticky bit,
  **WHEN** the user runs `pm session`,
  **THEN** it refuses with a message naming the directory and the fix
  (owned by the user, or 1777) and creates no server.
- **GIVEN** the directory is 1777 and owned by another user,
  **WHEN** the user runs `pm session`,
  **THEN** it proceeds normally.
- **GIVEN** a socket file at the session's path is owned by a different
  user,
  **WHEN** the user runs `pm session` for that session,
  **THEN** it refuses with a message naming the socket and its owner, and
  creates no server.
- **GIVEN** a symlink planted at a session's socket path, **WHEN** the
  user runs `pm session list`, **THEN** the entry is skipped (not reported
  as one of the user's sessions).
- **GIVEN** a repository whose tag would make the socket path exceed the
  Unix socket limit, **WHEN** the user starts a session, **THEN** a
  deterministic hashed socket name is used and list/kill still work.
- **GIVEN** tmux is not installed (or not executable) on `PATH`,
  **WHEN** the user runs `pm session list`, `pm session kill`,
  `pm tui view`, or the TUI's quit key is pressed in an environment with
  `$TMUX` set but no tmux binary,
  **THEN** the command reports a clear message and does not traceback.

## Setup (user steps)

These are shared by all scenarios; each scenario's GIVEN narrows them.

1. Install pm from this branch (`./install.sh --local`, or an editable
   install with `PYTHONPATH` pointed at the workdir) and confirm `pm
   which` names the workdir copy.
2. For each project used by a scenario: create a throwaway directory, `git
   init`, `pm init --backend local --no-import`, and add a few PRs so the
   TUI has content.
3. Start a session with `pm session` (it will fail to *attach* without a
   tty — that is expected; the session is created). Drive the TUI through
   tmux (`pm tui send`, `pm tui view`) or through a real attach client
   started inside a separate tmux pane.
4. Every scenario runs in its own container. Use a disposable `HOME` and a
   disposable tmux temp dir (`TMUX_TMPDIR`) where a scenario needs to
   simulate another user or a clean machine, and clean up the tmux servers
   it starts before finishing.
5. When a scenario needs "a second user", create one in the container
   (`useradd`, or use an existing account such as `nobody` via `su`), or
   run the joining side in a nested container as a different uid. If
   neither is possible, say so in the report and drive the joining path
   with a separate `HOME` instead, noting which permission checks could
   not be observed.

## Edge cases

All framed as Given/When/Then above or below; the plan's scenarios cover
them.

- `/tmp/pm-sessions` does not exist yet (first ever pm session).
- `/tmp/pm-sessions` exists but is not sticky, or is owned by another user.
- A socket file at the session's path is a symlink, a regular file, or
  owned by another uid.
- A stale socket file left by a killed server, with no server behind it.
- A live server whose base session was killed but whose grouped session
  still has a client.
- Two `pm session` invocations racing on the same project.
- A `pm session list` running while sessions are being created and killed.
- A `pm session kill` running while a client is attached to that session
  and while another session is being driven.
- Very long repo name (hashed socket), and a directory that is not a git
  repository.
- tmux missing from `PATH` while `$TMUX` is set.
- `pm session` run inside another pm session for a different project.
- `pm session --global` / `kill --global` run inside a private session.
- A grouped-session suffix (`~N`) passed to a session-keyed command.
- A second `HOME` inheriting a foreign `$TMUX`/`$TMUX_PANE` (the guard that
  keeps tooling from adopting a live session).

## Pass / fail criteria

A scenario passes when every Then clause is observed on the user's
surface — command output, pane render, file/socket existence, client
attachment — and no clause in another session is disturbed as a side
effect. Specifically:

- **Fail** if any action taken in session A changes session B's clients,
  panes, windows, TUI output, registry, pidfile or socket, or the default
  tmux server.
- **Fail** if a command crashes with a traceback where the requirement
  says it must report a message or degrade.
- **Fail** if a private socket, session or client is left behind after a
  kill, or if a live server's socket is unlinked.
- **Fail** if a legacy session is duplicated, migrated, detached or killed
  without the user explicitly running `pm session kill`.
- **Fail** if `pm session list` shows a dead, foreign or symlinked entry
  as a live session, or shows one session twice.
- **Pass** includes clean refusal messages for hostile directory states:
  refusing to run is correct behaviour there, not a failure.

## Ambiguities

Resolved by judgement (no **[UNRESOLVED]** items):

1. **"Update pm session attach/list commands"** — there was no `pm session
   list` before; the spec adds one and makes attach/`--print-connect`/
   `kill`/`mobile`/TUI discovery socket-aware. Tests treat the new list
   command as the listing surface.
2. **Private and shared sessions share the `/tmp/pm-sessions` directory**
   — accepted as designed. A future per-uid directory is noted as
   hardening, not part of this change; tests assert the failure modes
   (ownership refusal, symlink skipping, sticky-bit refusal) that make the
   shared directory safe.
3. **A joining user's session is not re-adopted by a plain `pm session`**
   — the documented, fail-safe trade-off (the joiner has no local pane
   registry, so pm starts a separate private session rather than risk
   touching the shared one). The joining path is exercised through the
   documented forms: repeating `--global`/`--group`, or `--dir`. A plain
   `pm session` from a joined session's directory starting a separate
   private session is *expected* behaviour, not a failure.
4. **Which client detaches when two clients share one session** — the
   most recently active client viewing the TUI's window. The test asserts
   that exactly one detaches and the other stays, not which one.
5. **Testing multi-user permission checks in a single-uid container** —
   use a second account (or nested container) where possible; otherwise
   observe the socket mode/ownership and record the gap in the report.
