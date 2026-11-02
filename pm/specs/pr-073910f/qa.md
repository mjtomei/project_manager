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
user, symlinks planted at a session's socket path or at the directory
itself, a non-sticky
world-writable directory, and a sticky directory that is not
world-writable must fail closed rather than be used. Discovery with no
session context of its own never auto-selects *another user's* server.
A user's own tmux view grouped under a pm session — under any name, even
one that looks like a different pm session — resolves to the pm session
it is grouped with for discovery, driving and detaching.

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
6. **The pane registry** (`~/.pm/pane-registry/<session>.json`) — one file
   per session, keyed by the *base* session name; written by the TUI, read
   by every discovery path.
7. **tmux pane ids (`%N`)** — now only unique *within* one server, while
   `pm tui send` delivers keys to a bare pane id.
8. **Per-server tmux state** — hooks (`set-hook -g`), global environment,
   windows, grouped sessions. Two servers must never share any of it.
9. **Session-keyed artifacts** — TUI pidfile and command queue,
   frame/history files, the home-window refresh sentinel, the mobile
   flag, containers and push proxies cleaned up by `pm session kill`.
   All are keyed by the *base* session name.

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
- **GIVEN** a repo whose directory name contains characters tmux rewrites
  in a session name — a `.` (`next.js`), a `:`, a `#`, a backslash, or a
  `$` followed by a letter (`my $HOME repo`) —
  **WHEN** the user runs `pm session` from a plain shell, and then again,
  **THEN** the first run creates a session whose printed name is exactly
  the name tmux lists (each such character becomes `_`, e.g.
  `pm-next_js-<hash>`), with no "Failed to detect TUI pane after session
  creation."; the second run attaches to it (no "duplicate session"
  traceback); panes open in the repo's real path with its literal
  characters, and a `#(cmd)` in the path is never run (QA S28, commit
  78b7b2fa).  Everything keyed by the session tag — `~/.pm/sessions/<tag>/`
  (pm_root, session override, fake-claude config), the pane registry, the
  mobile flag, `pm session list`, `--print-connect`, `pm tui -s` — uses
  that same tmux-safe name.
- **GIVEN** such a dotted-name project for which an *older* pm (before
  this change) ran `pm session`: it printed "Failed to detect TUI pane
  after session creation." but left `pm-next_js-<hash>` running its TUI
  on the default server,
  **WHEN** the user runs `pm session` with this build,
  **THEN** the leftover is adopted as a legacy session (R10: attached, with
  the one-line rollout note; no private twin is created), and after
  `pm session kill` the next `pm session` starts it on its private socket
  (QA planning 2026-11-02, from the S28 tag change).

### R3 — `pm session list` enumerates every pm session across servers

- **GIVEN** several pm sessions are running: at least one modern private
  session with an attached client, one with two attached clients, and one
  legacy session on the default server,
  **WHEN** the user runs `pm session list` from a plain shell,
  **THEN**
  - there is exactly one row per session (base name, not one per grouped
    session); a user's own view of a session (R5) is not a session of its
    own and gets no row, whatever it is called — including a name that
    looks like a pm session (e.g. a view named `pm-laptop` grouped with
    `pm-x`);
  - the client count covers the base session and its `~N` grouped
    sessions (a client attached through a user's own tmux view of the
    session — R5 — is not counted; `tmux list-clients` is authoritative
    there);
  - each row names the socket that hosts it, and the legacy row is marked
    as living on the default server;
  - running the same command from *inside* a pm pane lists the same set —
    in particular the current session is not listed a second time as a
    default-server session;
  - a session whose name contains a space or a `|` (both legal in a repo
    directory name, and in a tmux session name) is listed with its full
    name and its own socket — never dropped, truncated or split
    (review-loop 2caf i5);
  - two projects whose names contain `~` (e.g. `my~repo`, `my~other`)
    are listed as two rows, each under its own full name and its own
    socket.  `~N` is a *grouped-session* suffix only when it is numeric,
    so a `~` in the tag must not be truncated (review-loop b48f i11).
- **GIVEN** `/tmp/pm-sessions` is a directory owned by another user
  (e.g. root) with mode `1733` — sticky and world-writable, so `pm
  session` accepts it and creates sockets there, but not readable by
  others, so its entries cannot be enumerated —
  **WHEN** the user, with a private session running, runs `pm session
  list`,
  **THEN** it does not silently report "No pm sessions found." as if
  nothing were running: it either lists the sessions it can still reach
  or says that the socket directory cannot be read; it never crashes, and
  `pm session`, `--print-connect`, `pm tui view` and `pm session kill` in
  the project's directory still find the session through its
  deterministic socket path (QA planning 2026-11-02; `list` now applies
  `paths.shared_socket_dir_is_usable`, review-loop 68bd i4).

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
- **GIVEN** a session (private or legacy) whose name contains a space,
  **WHEN** the user asks for the connect command from the CLI or the TUI
  popup, **THEN** the printed command quotes the socket path and the
  session name so the whole command pastes and runs as one shell command
  (review-loop 2caf i1).

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
- **GIVEN** the session is also open through the user's own tmux view
  grouped with it under an arbitrary name (e.g. `myview`, or `pm-laptop`
  which is not the session), **WHEN** any client of that pm session
  presses the quit key, **THEN** exactly one client of *that* pm session
  detaches; the view's name never narrows the candidate set to a single
  client, and no other pm session's client is touched.
- **GIVEN** the same session viewed through that user's own view, with
  the *only* attached client on the view and viewing the TUI's window,
  **WHEN** it presses the quit key, **THEN** that client detaches (a
  view's client is a member of the pm session's group, not only
  `base~N`), the TUI keeps running, and no other pm session is touched.
- **GIVEN** the legacy default server also hosts an *unrelated* pm
  session whose name merely starts with this session's name plus `~` (a
  repo directory may contain `~`, so the project `x~foo` runs
  `pm-x~foo-<hash>`) and that other session has an attached client,
  **WHEN** a window operation for `pm-x` runs (a new window created with
  switch, a window selection, or the layout sizing), **THEN** it targets
  `pm-x`'s own group: the unrelated session's client is not moved and its
  window size does not constrain the layout (membership is tmux's session
  group, never a name prefix).
- **GIVEN** that unrelated `pm-x~foo-<hash>` session also has a grouped
  session of its own (`pm-x~foo-<hash>~1`, created when a second client
  attached to it), **WHEN** the user runs `pm session` for `pm-x`, kills
  `pm-x`, presses the quit key in `pm-x`, or `pm-x` sizes its layout,
  **THEN** that grouped session is not treated as one of `pm-x`'s: the
  user is never attached to it, it is not killed or detached, and its
  client's size does not constrain `pm-x`'s window; and once the other
  project's base is gone, its surviving `~1` does not make discovery
  adopt the default server for `pm-x`.  Only a remainder that is *all*
  ASCII digits after `<base>~` is a grouped suffix (review-loop b48f
  i19).
- **GIVEN** the TUI is being viewed through a user's own view of the
  session (any name, e.g. `myview`), **WHEN** the user opens a TUI pane
  from it (e.g. the notes pane) and then asks for the same pane again,
  **THEN** the pane is registered in the *base* session's registry (no
  registry file named after the view appears), the second request
  focuses the existing pane instead of opening a duplicate, and the
  layout rebalances for the base (review-loop b48f i1).
- **GIVEN** a session with clients on `base~N` and on a user's own view,
  **WHEN** the user runs `pm session --disconnect-others` (`-d`) to take
  the session over, **THEN** every other client — including the view's —
  is detached, so none of them keeps constraining the shared window size
  (review-loop b48f i4).

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
- **GIVEN** a user's own tmux view of session A, grouped with A under an
  arbitrary name (not `pm-A~N`, e.g. `myview`, or `pm-laptop` while a
  different session named `pm-laptop` also runs), **WHEN** the user runs
  `pm tui view` / `pm tui send` with no `--session` from inside that view,
  **THEN** it drives A's TUI and never the other session's.
- **GIVEN** a live TUI pane that is recorded in A's registry but that
  `tmux list-panes -a` reports under a view's name (the group's
  lexicographically last member), **WHEN** the user runs `pm tui view -s
  A` or `pm tui send -s A`, **THEN** it drives that pane rather than
  reporting "No TUI pane found".
- **GIVEN** another user's live server socket under `/tmp/pm-sessions`
  (world-accessible `--global`/`--group` socket) while this user has no pm
  session of their own, **WHEN** they run `pm tui view` / `pm tui send`
  with no `--session` from a plain shell, **THEN** it reports no TUI found
  rather than driving the other user's TUI; naming that session
  explicitly with `--session` still reaches it.
- **GIVEN** a pm session whose repo directory name contains a space (so
  the session name does too), **WHEN** the user runs `pm tui view` /
  `pm tui send` / `pm tui frames` from a plain shell in that directory,
  and again from a shell inside that session's own pane, **THEN** it finds
  and drives that session's live TUI rather than reporting "No TUI pane
  found" (review-loop 2caf i5).
- **GIVEN** a legacy (pre-isolation) session L running on the default
  server — its panes carry no `PM_TMUX_SOCKET` — and a *private* session
  with the same name running on its own socket (an older pm binary
  creates such a twin from a plain shell), **WHEN** the user runs
  `pm tui view` / `pm tui send` from a shell inside L (or from L's TUI
  with no `--session`), **THEN** it drives L's own TUI on the default
  server and never the twin's pane, even though both sessions share the
  pane-registry key and both servers can use the same pane id
  (review-loop b48f i6).
- **GIVEN** a pm session whose repo directory name contains a space or a
  `~` (so the session name does), or a client attached through a user's
  own view of that session (any name), **WHEN** the user presses the
  pane-switch prefix keys (`prefix+o`, prefix+arrows) in it, **THEN** pm's
  mobile-aware pane switch runs (the pane zooms/unzooms as the session's
  mobile state requires) rather than the plain tmux `select-pane`
  fallback: the gate that decides this resolves the base session through
  tmux's session group and quotes the name (review-loop b48f i15).
- **GIVEN** a pm session whose repo directory name contains a space, a
  quote, a backtick or a `$` (so the session name does too), **WHEN** the
  user presses the pane-switch prefix keys, or a pane opens, closes or
  resizes in it, **THEN** the name reaches `pm _pane-switch` /
  `pm _pane-opened` / `pm _window-resized` / `pm _pane-exited` as one
  argument and no part of it is executed by the shell: the bindings and
  hooks quote it with tmux's `#{q:...}` modifier, and the pane EXIT trap
  quotes it for each of its shell layers (review-loop b48f i17).  That
  includes the condition that gates the pane-switch binding: a name with
  a single quote still gets pm's mobile-aware switch (not the plain
  `select-pane` fallback), and a backtick in it runs nothing (QA S23,
  commit 87b2d1d1).
- **GIVEN** a pm project whose directory name contains a space, a quote,
  a backtick or a `$` (so the agent's working directory — the repo, its
  workdir clone under `~/.pm/workdirs/`, or the meta workdir — does too),
  **WHEN** pm starts any agent with a prompt (`pm pr start`, a review, a
  QA run, `pm meta`, a plan or guide session, from the CLI or the TUI),
  **THEN** the agent receives the whole prompt as one argument (never an
  empty prompt), no part of the path is executed by the shell, and the
  temporary prompt file under `pm/prompts/` is removed afterwards.
  Ordinary paths behave exactly as before, including container mode,
  whose launch rewrites the prompt path to the container's workdir
  (pre-existing on master; fixed in this PR by QA S23, commit 87b2d1d1).
- **GIVEN** a QA run launched from another clone's pm session (recorded in
  its `qa_resume.json` session tag) whose session is still alive on that
  clone's own server, **WHEN** this clone's TUI restarts and scans for
  resumable runs, **THEN** it leaves that run to the clone hosting the
  session — it does not resume the run in its own session (which would
  poll windows that are not there and end the other run with a bogus
  result) — and a run whose session is gone is still resumed here
  (review-loop b48f i15).  A server *another user* planted at that
  session's deterministic socket name does not count as the run's
  session: the run is resumed here (review-loop b48f i20).
- **GIVEN** a pm session whose name contains a space, **WHEN** pm starts
  an agent whose prompt tells it how to drive the TUI — a QA run
  (`pm qa launch`, CLI or TUI), `pm qa regression`, `pm meta`, or any
  prompt carrying the TUI section — **THEN** every copyable command in
  that prompt (`pm tui view -s …`, `pm tui send … -s …`, the
  `~/.pm/pane-registry/<session>.json` path, the discovery watcher's
  `tmux list-panes -t <session>:discovery`) quotes the name as one shell
  word, so pasting it runs against the right session; ordinary names stay
  unquoted (review-loop b48f i18/i19).  When the QA run is launched from
  a user's own view or a `~N` grouped session, the prompt names the base
  pm session, not the view (review-loop b48f i4).

### R8 — Killing a session tears down only that session

- **GIVEN** pm sessions A and B are running, each with an attached client
  and live panes,
  **WHEN** the user runs `pm session kill` in project A,
  **THEN** A's grouped sessions and base session are gone, A's socket file
  is removed, and B's session, server, clients, panes and TUI are
  untouched.
- **GIVEN** session A is also open through a user's own tmux view grouped
  with it under an arbitrary name (R5, e.g. `myview`),
  **WHEN** the user runs `pm session kill` in project A,
  **THEN** the view is torn down with the base and its `~N` sessions (its
  client is detached, the old TUI pane is gone), the server exits, A's
  socket file is removed, and nothing of the session is left behind — a
  later `pm session` starts a fresh base on a fresh server.
- **GIVEN** a session whose base session was killed elsewhere but whose
  grouped session still has a client,
  **WHEN** the user runs `pm session kill` (which reports no session for
  that name), **THEN** the live server's socket file is *not* removed and
  the client is not stranded.
- **GIVEN** the legacy default server also hosts an *unrelated* pm
  session whose name merely starts with the target's name plus `~` — a
  repo directory may contain `~`, so the project `x~foo` runs
  `pm-x~foo-<hash>` — **WHEN** the user runs `pm session kill` for
  `pm-x`, **THEN** only `pm-x`'s group (base, `~N`, views) is torn down;
  the other project's session, its panes and its clients are untouched
  (group membership is tmux's session group, never a name prefix).
- **GIVEN** a directory that is not a git repository (a mistyped
  `--dir`), **WHEN** the user runs `pm session kill --dir <that dir>` from
  inside another project, **THEN** it refuses with the same message as
  `pm session --print-connect --dir` and kills nothing — in particular
  not the cwd's session (review-loop b48f i1).
- **GIVEN** a stale socket file left behind by a dead server,
  **WHEN** the user runs `pm session kill`, **THEN** it reports no session
  and removes the stale file; a later `pm session` starts a fresh server
  at the same path.
- **GIVEN** a shell window *inside* session A (or a terminal that is
  closed while the kill runs),
  **WHEN** the user runs `pm session kill` there — its own terminal dies
  with the server it is tearing down —
  **THEN** the teardown still completes: A's base, grouped sessions and
  views are gone, A's containers and push proxies are cleaned up, and its
  socket file is removed; no traceback is left anywhere, and `pm session
  list` from another terminal shows A gone (QA S30, commit 7deab88e).
- **GIVEN** A's private server also hosts a session that is not part of
  A's group (a hand-made `tmux -S <A's socket> new-session -s scratch`),
  **WHEN** the user runs `pm session kill` for A,
  **THEN** A's group is killed and reported, but the server stays up for
  `scratch`, so its socket file is kept and `scratch`'s client stays
  attached; a later `pm session` in A's project starts A again on that
  socket and leaves `scratch` alone (review-loop 68bd i4 folded both
  kill branches into one stale-socket rule).
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
- **GIVEN** a shared session, **WHEN** its owner runs a plain `pm session`
  (no `--global`/`--group` flag) from a shell pane *inside* that session
  (the ambient session is adopted, and its recorded share mode is read
  from the session environment), **THEN** the reattach creates/uses a
  grouped session whose window sizing is the shared `smallest` (base and
  grouped both), so the smallest connected client still sees the full
  layout: the share mode recorded by the session, not the missing process
  flag, decides this.
- **GIVEN** the same shared session, **WHEN** the owner runs a plain `pm
  session` from a *plain shell* outside tmux, **THEN** there is no ambient
  session to adopt, so it starts the directory's *private* session (a twin
  beside the shared one) rather than guessing the shared tag; re-joining
  needs the flag (see R9's join bullet and the README).
- **GIVEN** a shared session whose owner is attached through a grouped
  session (`~1`) and opens a shell pane *in that grouped session* (its
  *session* environment is empty — tmux copies no session environment
  into a grouped session — and the pane normally inherits
  `PM_SHARE_MODE` from the server's global environment, so the shell must
  `unset PM_SHARE_MODE` to exercise the no-mode rule), and the project
  has **no private twin session** running, **WHEN** the owner runs a
  plain `pm session kill` (no `--global`/`--group`) from that pane,
  **THEN** it kills that shared session (no mode requested means "the
  session I am in", whatever mode it was created with) and touches no
  other session.  (With a private twin running, the cwd-derived name is
  tried first and the twin is the one killed — the cwd-first rule of
  R8/R3; that is the documented trade-off, not part of this bullet.)
- **GIVEN** a shared session whose TUI pane was killed so that its window
  was recreated by the `after-kill-pane` hook (`pm _pane-closed`), with
  `PM_SHARE_MODE` removed from the server's global environment (`tmux
  set-environment -g -u PM_SHARE_MODE`) so the hook's `run-shell` command
  does not inherit it — the server global environment normally does carry
  it from the creating `pm session --global` process, so removing it is
  what exercises the session-environment fallback — **WHEN** the TUI is
  respawned, **THEN** the new window carries `window-size=smallest` (read
  from the session environment), so the smallest connected client still
  sees the full layout.
- **GIVEN** a `--global` (or `--group`) session for project P in which
  the owner ran `pm meta` from a shell pane (it prints "Set session
  override: ~/.pm/sessions/<tag>/override" with the *shared* session's
  tag and opens a meta window on the shared server),
  **WHEN** the owner runs a plain `pm` command (`pm which`, `pm pr list`)
  from a shell pane of that shared session in P's directory,
  **THEN** it runs the meta workdir's pm (`pm which` names
  `<meta workdir>/pm_core`), the same code the session's prefix+M popup
  runs; the same holds for a session whose project is a pm source
  checkout (its persisted pm_root).  A private twin session of P, and a
  plain shell outside tmux, keep their own resolution: the shared
  session's override never applies to them, and a twin's own `pm meta`
  override never applies to the shared session.  Closing the meta window
  removes only its own override (review-loop 68bd i1/i2: the wrapper
  derived the tag without `PM_SHARE_MODE` and missed both files).

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
- **GIVEN** a legacy session that disappears while `pm session` is
  starting in its project (another terminal killed it between the lookup
  and the create), **WHEN** the start completes, **THEN** the session is
  created on the project's *private* socket — never as a second session on
  the default server — and the rollout note is not printed for the session
  that vanished (review-loop 8d4e i1).
- **GIVEN** `$TMUX_TMPDIR` set to a path that does not exist, or to a
  relative path that does not resolve to a directory, so tmux itself
  keeps its default server at `/tmp/tmux-<uid>/default`, **WHEN** the
  user runs `pm session`, `pm session list` or `pm session kill` in a
  legacy project's directory, **THEN** the legacy session is still found
  (attached, listed, killed; no duplicate private session) — pm's
  default-server path mirrors tmux's fallback (review-loop b48f i7).
- **GIVEN** `$TMUX_TMPDIR` set to an existing *relative* path, which tmux
  resolves against the client's cwd, **WHEN** the user runs those
  commands in a legacy project's directory, **THEN** the legacy session
  is still found at `<resolved>/tmux-<uid>/default` (review-loop b48f
  i9).
- **GIVEN** the legacy default server hosts only an *unrelated* session
  whose name merely starts with the target's name plus `~` — a repo
  directory may contain `~`, so the project `x~foo` runs
  `pm-x~foo-<hash>` — **WHEN** the user runs `pm session` or
  `pm session --print-connect` for `pm-x`, **THEN** the unrelated session
  is not adopted: `pm session` creates/attaches `pm-x` on its own private
  socket and the printed command names that socket, leaving the other
  project's session, panes and clients untouched.  A prefix match is
  confirmed through the exact name or tmux's session *group*, never a
  bare name prefix (review-loop b48f i16).

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
- **GIVEN** a running TUI (its pane is the session's lifeline: if the
  TUI exits, the window and possibly the session and server go with it),
  **WHEN** the user submits a command-bar line with an unbalanced quote —
  a plain command (`pr note add <id> don't forget`) or a PR action
  (`pr start <id> "oops`) —
  **THEN** the TUI logs "Error: cannot parse command: …" and keeps
  running; nothing is launched or recorded; the next valid PR action is
  accepted, not refused as already in flight; and the prefix+M popup
  answers the same line with "Invalid command syntax".  The TUI's own
  launches (`s`, `d`, auto-merge) quote their transcript path, so a
  project path with an apostrophe launches normally (review-loop 68bd
  i1; QA S28).
- **GIVEN** a session window killed outside pm (`C-b &`, `tmux
  kill-window`), which fires no pm hook,
  **WHEN** the session next rebalances (a pane opens or closes, a client
  attaches),
  **THEN** the killed window's entry is dropped from the session's pane
  registry, and later pane launches and layouts in the surviving windows
  are unaffected (QA S28).

### R12 — The socket directory fails closed

- **GIVEN** `/tmp/pm-sessions` exists but is world-writable *without* the
  sticky bit,
  **WHEN** the user runs `pm session`,
  **THEN** it refuses with a message naming the directory and the fix
  (owned by the user, or 1777) and creates no server.
- **GIVEN** `/tmp/pm-sessions` is sticky but *not* world-writable (e.g. a
  root-owned `1755` directory),
  **WHEN** the user runs `pm session`,
  **THEN** it refuses with the same actionable message (owned by the user,
  or 1777) and creates no server, rather than surfacing an opaque
  "couldn't create socket" from tmux.
- **GIVEN** `/tmp/pm-sessions` is a symbolic link (e.g. planted by another
  user before pm first ran, pointing at a 1777 directory they own),
  **WHEN** the user runs `pm session`,
  **THEN** it refuses with a message saying the path is a symlink and
  creates no server or socket anywhere through the link — the link's
  target owner could otherwise unlink (and replace) every socket pm binds
  there, sticky bit or not.
- **GIVEN** that same symlinked `/tmp/pm-sessions` holds a running server
  in its target directory, **WHEN** the user runs `pm session list` (or
  `pm tui view` with no `--session` from a plain shell), **THEN** the
  target's sessions are not listed or driven — the read path refuses the
  link exactly like `pm session` does — while any legacy session on the
  default server is still listed.
- **GIVEN** that same symlinked `/tmp/pm-sessions` and a file or server at
  a session's deterministic name inside the link's target, **WHEN** the
  user runs `pm session kill` for that session, **THEN** it reports no
  session, does not probe (`tmux -S` follows the link) and does not
  remove anything inside the target, and the target's file or server is
  left untouched (review-loop b48f i10).
- **GIVEN** a regular file or a symlink planted at a session's socket
  path, **WHEN** the user runs `pm session list`, **THEN** the entry is
  skipped (not reported as one of the user's sessions) and nothing is
  followed or crashed on.
- **GIVEN** a symlink planted at a session's socket path (pointing at a
  server another user runs, or dangling), **WHEN** the user runs
  `pm session` for that session — private *or* `--global`/`--group` (the
  ownership check is private-only, so a shared start is the case the
  link would otherwise be followed in) — **THEN** it refuses with a
  message naming the socket and saying it is a symbolic link, exports no
  `PM_TMUX_SOCKET`, and neither connects to nor creates a server there
  (review-loop b48f i7).
- **GIVEN** that same symlink at a session's socket path pointing at a
  live server another user runs (with a session of that name), **WHEN**
  the user runs `pm tui view` / `pm tui send -s <session>`,
  `pm session --print-connect`, opens the TUI connect popup, or runs
  `pm session kill` for that session, **THEN** the lookup does not follow
  the link or act on the server behind it — it reports no TUI pane / no
  session (and `pm session --print-connect` refuses with a message
  naming the link instead of printing a command through it), and that
  server, its session and its clients are untouched (review-loop b48f
  i7/i9).
- **GIVEN** the directory is 1777 and owned by another user,
  **WHEN** the user runs `pm session`,
  **THEN** it proceeds normally.
- **GIVEN** a socket file at the session's path is owned by a different
  user,
  **WHEN** the user runs `pm session` for that session,
  **THEN** it refuses with a message naming the socket and its owner, and
  creates no server.
- **GIVEN** a *real* socket at a private session's path owned by another
  user (a planted server — a real socket is not a symlink, so the entry
  check passes, and tmux < 3.3 has no `server-access` ACL, so a 0777
  socket is connectable), **WHEN** the user runs an implicit lookup —
  `pm tui view` / `pm tui send` with no `--session` from a plain shell in
  the project, `pm pr start`, `pm meta`, `pm container build`,
  `pm session home`, `pm session kill`, `pm session mobile`,
  `pm session --print-connect`, the TUI connect screen, or the TUI's
  QA-resume scan on restart — **THEN** the
  planted server is not adopted or advertised: the lookup falls through
  to the default server (or reports no session, or refuses to print a
  command naming the entry), and the planted server, its session and its
  clients are untouched.  An explicit `-s` and a `--global`/`--group`
  context may still reach another user's socket — that is the documented
  shared-session flow (review-loop b48f i9).
- **GIVEN** a repository whose tag would make the socket path exceed the
  Unix socket limit, **WHEN** the user starts a session, **THEN** a
  deterministic hashed socket name is used and list/kill still work.
  The limit is measured in *bytes*: a repo directory name of roughly 27
  or more multi-byte characters (e.g. Japanese) is under 100 characters
  but over the limit, and must also get the hashed name rather than fail
  with tmux's "File name too long"; a short non-ASCII name keeps its
  readable socket name (review-loop b48f i21).
- **GIVEN** tmux is not installed (or not executable) on `PATH`,
  **WHEN** the user runs `pm session list`, `pm session kill`,
  `pm session mobile`, `pm tui view`, or the TUI's quit key is pressed in an environment with
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
- `/tmp/pm-sessions` exists but is not sticky, or is sticky but not
  world-writable, or is owned by another user.
- A socket file at the session's path is a symlink, a regular file, or
  owned by another uid.
- Another user's live (shared) server under `/tmp/pm-sessions` while this
  user has no pm session — discovery must not auto-select it.
- A user's own tmux view grouped with a pm session under an arbitrary
  name, including a name that collides with another pm session.
- A shared session reattached with a plain `pm session` (no share flag).
- A stale socket file left by a killed server, with no server behind it.
- A live server whose base session was killed but whose grouped session
  still has a client.
- Two `pm session` invocations racing on the same project.
- A `pm session list` running while sessions are being created and killed.
- A `pm session kill` running while a client is attached to that session
  and while another session is being driven.
- Very long repo name (hashed socket), a repo name of multi-byte
  characters that is short in characters but long in bytes, and a
  directory that is not a git repository (including a mistyped
  `kill --dir`).
- Repo directory names containing `~`, a space, a backtick or a quote —
  each reaches tmux targets, hooks, key bindings, EXIT traps, agent
  prompts and the agent launch command's prompt-file path as data, never
  as a group suffix or shell syntax.
- Two sessions' popups (prefix+P picker, prefix+M command prompt) opened
  at the same moment, and commands queued from them into each session's
  TUI command queue.
- Container-mode agent launches in two sessions, and `pm session kill`
  removing only the killed session's containers and push proxies.
- Two unrelated legacy sessions on the default server where one's name
  starts with the other's name plus `~` (including that one's own `~1`).
- tmux missing from `PATH` while `$TMUX` is set.
- `pm session` run inside another pm session for a different project.
- `pm session --global` / `kill --global` run inside a private session.
- A grouped-session suffix (`~N`) passed to a session-keyed command.
- A second `HOME` inheriting a foreign `$TMUX`/`$TMUX_PANE` (the guard that
  keeps tooling from adopting a live session).
- Repo directory names tmux rewrites in a session name (`.`, `:`, `#`,
  `\`, `$` + letter), including a leftover default-server session that an
  older pm half-started for such a name.
- A socket directory pm can write but not read (`1733`, owned by another
  user).
- `pm meta` run in a shared session and in its private twin at the same
  time; plain `pm` commands in each resolve their own override.
- `pm session kill` typed inside the session it kills; a non-pm session
  hand-made on a pm session's private server.
- Command-bar and popup lines with unbalanced quotes.

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
6. **What "the current session" means when a pane is viewed through a
   user's own grouped view** — resolved through tmux's session *group*:
   a view named anything (even `pm-laptop`, colliding with another pm
   session) identifies the pm session it is grouped with. The test asserts
   discovery/driving/detaching target the pm session, not the view's name.
7. **How another user's shared session is reached from outside it** —
   only explicitly (`--session pm-<tag>`, or from inside it). A plain
   discovery with no session context never auto-selects another user's
   server; that is fail-safe, not a missing feature. A joining user's own
   private session remains the default for plain `pm session`.
8. **Sticky but non-world-writable socket directory** — treated as a
   refusal (the user cannot create a socket there), not as "owned by
   another user is fine"; R12's 1777-owned-by-another-user case is the
   only cross-owner case that proceeds.
9. **A socket directory pm can write but not read (`1733`)** — added by
   the 2026-11-02 planning pass. `ensure_socket_dir` accepts it (sticky +
   world-writable), but `pm session list` cannot enumerate it. Resolved by
   judgement: silently printing "No pm sessions found." while the user's
   own session runs is a failure; listing what is reachable, or a clear
   "cannot read" message, passes.
10. **Which pm a shared session's pane runs** — the share-mode tag's own
   session override / pm_root, exactly as that session's popups resolve
   it (review-loop 68bd i1/i2). A private twin of the same project is a
   different session with its own tag and its own override.
