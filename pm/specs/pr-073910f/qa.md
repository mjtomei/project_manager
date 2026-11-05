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
  working, untouched, until the user kills them;
- a user who has joined someone else's shared session can reattach to it
  with a plain `pm session` from inside that session, while a plain shell
  outside it still starts their own session (review-loop 43f6 i1).

The implementation also tightens a second class of hazard in the same
code: the socket directory is world-writable, so sockets owned by another
user, symlinks planted at a session's socket path or at the directory
itself, a non-sticky
world-writable directory, and a sticky directory that is not
world-writable must fail closed rather than be used. Discovery with no
session context of its own never auto-selects *another user's* server.
A user's own tmux view grouped under a pm session — under any name, even
one that looks like a different pm session — resolves to the pm session
it is grouped with for discovery, driving and detaching.  A view may also
be named with a leading or trailing space (tmux stores a session name as
given), and a window may be named with edge spaces or with no name at
all; every readback keeps such a name verbatim.

The same "a name or path is data, never shell syntax" rule now extends to
the remaining command builders a session runs: the `pm-home` PR-list
window, the QA status dashboard pane, `pm guide`'s setup command, the
`pm cluster explore --bridged` bridge pane, and the window listing a
rebalance and a name lookup read (review-loop 1346 i1; the QA status
command in 9d4c i2).  The global pane hooks fire on the whole server, so
a plain (non-pm) session a user creates beside the pm one must be ignored
by all of them, even when a stale registry from an older pm still lists
panes there (QA S58, commit fc99e992; review-loop 9d4c i1).

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
   per session, keyed by the *base* session name, guarded by a sidecar
   `.lock` file; written by the TUI (its heal on mount) and by
   `pm session` when it adopts a running TUI the registry does not list,
   read by every discovery path.  A second sidecar,
   `<session>.json.respawn.lock`, is taken by the `after-kill-pane` hook
   (`pm _pane-closed`, once per pane-close event, however many pm
   windows the session has — QA S47, commit b89aa9a4) and by every
   `pm session` attach to a running session, so only one of them starts
   a missing TUI (QA S42, commit 698cbb97).  The hook is invoked with the
   session it fired in (`run-shell 'pm _pane-closed #{q:session_name}'`,
   QA S54, commit bb80cd1a): its `$TMUX_PANE` can be empty or name a pane
   on another server, so the name, not the inherited pane id, selects the
   registry.  Both files live
   in the *user's own* `~/.pm`: a joiner of a shared session takes their
   own lock, never the owner's (review ad65 i1).  Under that lock the
   hook also starts a TUI when the registry lists none and no live
   `pm _tui` pane runs, whoever dropped the entry (QA S50, commit
   664df245), so the registry can be emptied by a reconcile the hook did
   not do.
6a. **The session's start directory (`#{session_path}`)** — the
   directory the base session was created in.  Every TUI respawn (hook
   split, new-window fallback, `pm session` attach) now starts there,
   instead of in the cwd of whichever client ran the command.
6b. **Each grouped session's current window** — every client of a pm
   session (each `~N`, a user's own view, a joiner's `~N`) has its own
   current window.  A `pm session` attach that respawns the TUI selects
   the TUI's window only in the grouped session it attaches, never in
   another client's (QA S45, commit f162a71c); the `after-kill-pane`
   hook's new-window fallback still selects through
   `current_or_base_session` (unchanged).
7. **tmux pane ids (`%N`)** — now only unique *within* one server, while
   `pm tui send` delivers keys to a bare pane id.
8. **Per-server tmux state** — hooks (`set-hook -g`), global environment,
   windows, grouped sessions. Two servers must never share any of it.
   The hooks are global on the server, so they also fire for a plain
   session a user creates there; each handler resolves the session
   through its tmux group and ignores it unless the resolved name is a
   pm one, so a non-pm session gets no registry, no rebalance and no
   respawned TUI even when a stale registry from an older pm lists panes
   in it (QA S58, commit fc99e992; review-loop 9d4c i1).
9. **Session-keyed artifacts** — TUI pidfile and command queue,
   frame/history files, the home-window refresh sentinel, the mobile
   flag, containers and push proxies cleaned up by `pm session kill`.
   All are keyed by the *base* session name.
10. **Verbatim names tmux stores as given** — a session name (a user's
    own view, or a repo directory ending in a space) and a window name
    (edge spaces, or empty) round-trip through every listing readback:
    `display-message -p`, `list-sessions`, `list-clients`, `list-windows`
    and the pane query.  A trimmed name no longer names the session or
    window it came from, so group resolution, detaching, the pane-switch
    gate, the dashboard switch and rebalance all miss it (review-loop
    9d4c i2/i3/i4, 1346 i1).

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
- **GIVEN** a repo whose directory name contains a Unicode line separator
  — `U+0085` (NEL), `U+2028` (LINE SEPARATOR) or `U+2029` (PARAGRAPH
  SEPARATOR),
  **WHEN** the user runs `pm session` from a plain shell, and then again,
  **THEN** the first run creates a session whose printed name is exactly
  the name tmux lists (the separator becomes `_`, e.g.
  `pm-qa-line_sep-<hash>`), with no "Failed to detect TUI pane after
  session creation."; the second run attaches to it; `pm session list`
  shows exactly one row with that full name and its own socket, from a
  plain shell and from inside its pane; `pm tui view`/`send` and
  `pm session --print-connect` find it; panes open in the repo's real
  path with its literal characters; `pm session kill` removes it and its
  socket.  The `_` matters because tmux stores the separator unchanged
  while pm reads every tmux listing back with `str.splitlines()`, which
  treats it as a record boundary — before this fix a live session
  vanished from `pm session list` and from the cross-server TUI scan
  (review-loop 1237 i2, commit 9037574f).  A *legacy* session or a
  user's own view created before this change with such a character in
  its name is not renamed and still cannot be parsed back (documented
  residual; ambiguity 18).
- **GIVEN** such a dotted-name project for which an *older* pm (before
  this change) ran `pm session`: it printed "Failed to detect TUI pane
  after session creation." but left `pm-next_js-<hash>` running its TUI
  on the default server,
  **WHEN** the user runs `pm session` with this build,
  **THEN** the leftover is adopted as a legacy session (R10: attached, with
  the one-line rollout note; no private twin is created), and after
  `pm session kill` the next `pm session` starts it on its private socket
  (QA planning 2026-11-02, from the S28 tag change).
- **GIVEN** a running session whose pane registry does not list its
  running TUI — the registry file was removed or emptied, the TUI pane is
  not in window index 0 (the user's tmux config sets `base-index 1`, or
  the TUI was respawned into a new window after its own window closed),
  or a joining user's `HOME` has no registry for the session at all —
  **WHEN** the user runs `pm session`,
  **THEN** the running TUI is adopted.  The attach proceeds with no "TUI
  pane missing — respawning..." line, no second TUI pane appears even
  briefly, the TUI keeps its pid, and the registry lists that pane as its
  window's TUI exactly once.  That holds also when several `pm session`
  runs and a TUI restart (the TUI re-registers itself when it mounts)
  write the registry at the same moment.  Only the session's own server
  is read, so another session's identical pane id is never recorded (QA
  S35, commit 7a32e665; review e661 i1).
- **GIVEN** the TUI is really gone (its process crashed, or its window
  was closed) while other panes of the session still run, or its pane is
  dead but kept by `remain-on-exit` and the registry does not list it
  (with the dead pane still registered, pm attaches to it without a
  respawn, as master does; that case is out of scope), including in a
  session whose name
  contains `_tui` because the repo directory does (`rich_tui`), so every
  pane pm launches carries that text in its command line,
  **WHEN** the user runs `pm session`,
  **THEN** it prints "TUI pane missing — respawning..." and starts a
  fresh TUI.  A notes, agent or shell pane, or a dead pane, is never
  recorded as the TUI, and `pm tui view`/`send` afterwards drive the new
  TUI.  Before the respawn, `pm tui view`/`send` report that no TUI pane
  was found rather than capturing or typing into another pane.  A pane
  is the TUI only when its start command, split into shell words, runs a
  pm entry point with the exact `_tui` argument — the same test the
  pidfile applies to a TUI's argv; a substring `_tui` in a session name,
  an EXIT-trap wrapper or a workdir path never counts (QA S38 found the
  substring match adopting the notes and review-diff panes in `rich_tui`;
  fixed in a337a168 and verified live post-fix).
- **GIVEN** a TUI that pm started any of the ways it starts one — a
  fresh `pm session` (the command carries a quoted `PM_TMUX_SOCKET=`
  prefix, plus `PM_SHARE_MODE=` for a shared session), a respawn split
  into the TUI's window or into a new window, a respawn by the
  `after-kill-pane` hook, an in-place Ctrl+R restart, or a legacy session
  an older pm started on the default server — in a session whose name
  contains a space, a quote, a double quote, a backtick, a `$` followed by
  a digit, a `~`, a `|` or multi-byte characters, or whose long name
  gives it a hashed socket,
  **WHEN** the pane registry no longer lists it and the user runs
  `pm session` or `pm tui view`/`send`,
  **THEN** the exact-match test still recognises that pane as the TUI:
  it is adopted (no "TUI pane missing — respawning...", no second TUI,
  same pid) and driven (QA planning 2026-11-02 pass 3: tmux reports such
  a command as one double-quoted word with `\"` escapes; a throwaway
  tmux 3.4 probe round-tripped all of these names, and QA S41 confirmed
  them live on tmux 3.2a).
- **GIVEN** a user kills the TUI pane with tmux (the `after-kill-pane`
  hook, `pm _pane-closed`, respawns a registered TUI),
  **WHEN** another terminal runs `pm session` for that session at the
  same moment,
  **THEN** the session ends with exactly one live TUI, the registry lists
  that one pane once (no entry for a pane that has exited), and the
  attach completes without a traceback.  No second TUI pane appears,
  not even for a moment, and no TuiPidfileConflict is logged: the hook
  and the attach decide and respawn under one per-session lock, the hook
  leaves the session alone when a live `pm _tui` pane is already
  running, and a pane already listed is not listed again (QA S42, commit
  698cbb97; master gives two live TUIs for 0.1–0.6 s in every round of
  this race, and the branch before the fix listed one TUI twice).  The
  attach may print "TUI pane missing — respawning..." when it is the one
  that starts the only TUI (ambiguity 13).
- **GIVEN** a running session whose TUI was just killed and whose registry
  entry for it is already gone — another `rebalance()` reconciled the dead
  entry away before the `after-kill-pane` hook read the registry: the
  background rebalance a `pm session` attach schedules about 0.6 s after
  its Enter, the `window-resized` hook, or a pane's EXIT trap (so the
  hook's own snapshot may not list the TUI either),
  **WHEN** the user closes a pane of that session (which fires the
  `after-kill-pane` hook),
  **THEN** the hook starts exactly one TUI, in the window the registry
  listed it in when the event was read, else `main`, else the first
  window; the registry lists the new pane as its window's TUI once, and no
  terminal shows a traceback.  A round that ends with no TUI at all is a
  defect: every reconcile that can drop the entry runs without the
  respawn lock, so the hook must not depend on its own reconcile having
  removed the entry (QA S50, commit 664df245; before it, 2 of 4 rounds
  with the attach's Enter 0.60–0.65 s before the kill, 5 of 8 for the
  refiner, left the session with no TUI).  The hook does this only when it
  actually holds the respawn lock, so two hooks that both went ahead past
  a stuck holder cannot both start one; when the lock is stuck or
  unusable, the session is recovered by the next `pm session` attach
  (ambiguity 17).  Repeat the race several times and report each round.
- **GIVEN** a session whose TUI is missing and whose registry does not
  say which window it was in (the entry was removed, the registry file
  was lost), or does say (the TUI lived in a review/notes window, not
  `main`),
  **WHEN** the TUI is started again — by a `pm session` attach, or by the
  `after-kill-pane` hook after a pane close,
  **THEN** both paths use one rule: the window the registry (or the
  hook's snapshot of it) listed the TUI in, else the window named `main`,
  else the first window — never the active window, which may be a QA or
  work window.  A TUI that the registry still places in a non-`main`
  window comes back in that window from either path; with no record of
  its window it comes back in `main` from either path, so the two paths
  never put a respawned TUI in different windows (review-loop 1237 i1,
  `pane_layout.tui_respawn_window`).  If the hook's snapshot did not list
  the TUI at all, `main` is the accepted answer even for a TUI that had
  lived elsewhere (ambiguity 19).
- **GIVEN** a *shared* session (`--global`/`--group`) with a joined
  second user, **WHEN** the TUI pane is killed with tmux (by either
  user's client) while the joiner runs `pm session --global --dir <the
  owner's project>` at the same moment,
  **THEN** the session ends with exactly one live TUI running the
  owner's project, the joiner's attach completes, and no user's terminal
  shows a traceback.  The joiner takes their own respawn lock, not the
  owner's, so this race is *not* serialised; its only guard against a
  second TUI is the TUI pidfile, as before the lock (documented in review
  ad65 i1; verified live in QA S45: one TUI after every one of 12
  rounds, and the refiner saw one round with a second TUI for a moment
  that exited on the pidfile guard with a TuiPidfileConflict and settled
  to one).  A second TUI that appears for a moment
  and exits on the pidfile guard is that documented trade-off: report how
  often it happens and what it leaves behind (ambiguity 14).  It fails
  the scenario if two TUIs keep running, if a pane is left running
  something other than the TUI (the pm guide, Claude), or if the owner's
  registry still lists an exited pane, or lists the TUI twice, after the
  next pane close or `pm session` attach has reconciled it.
- **GIVEN** a running session whose TUI is killed or gone,
  **WHEN** the TUI is respawned — by the `after-kill-pane` hook after a
  `tmux kill-pane` typed in *another project's* directory, in `/tmp` or
  `$HOME`, or in a subdirectory or PR workdir clone of this project; by
  that hook from a client attached through a user's own view that was
  created in another directory; by the hook's new-window fallback when
  the TUI was the last pane of its window; or by a `pm session` attach
  run from a subdirectory, or a joiner's `pm session --global --dir`
  run from the joiner's own home —
  **THEN** the new TUI starts in the directory the session was created
  in (the project's repo directory) and shows *this* project.  It never
  loads the other project (whose pidfile and registry it would take
  over), never starts the pm guide or a Claude pane, and the other
  project's session, TUI, registry and pidfile are untouched.  A repo
  path with a space, a quote, a `$`, multi-byte characters or a
  `#(cmd)` is used literally, and the `#(cmd)` is never run (QA S42,
  commit 698cbb97: before it, the respawn split had no `-c`, so tmux
  started the TUI in the cwd of the client that ran the command; this
  was pre-existing on master; verified live from every one of these
  places in QA S46).  The same holds for a legacy session on the default
  server once the user runs this build: its hook then runs this build's
  respawn.
- **GIVEN** a running session with two or more clients — another
  terminal of the same user on `~1`, a shared session's owner while a
  joiner attaches, or a client on a user's own view — each looking at a
  window of their own (a shell, notes or review window), and the TUI is
  gone (its window was closed with `kill-window`/`C-b &`, or its process
  crashed beside other panes),
  **WHEN** a further terminal runs `pm session` (or a joiner runs
  `pm session --global --dir …`), reusing an unattached `~N` or
  creating a new one,
  **THEN** the TUI is respawned once, and only the client of *this*
  attach lands on the TUI's window — the new window, or the old TUI
  window the TUI was split back into (a reattach that respawns always
  shows the TUI; master never selected the split case, and the change is
  intended).  Every other client stays on the window and pane it was
  using, with what it was typing intact (QA S45, commit f162a71c: before
  it, the respawn selected through the first *attached* grouped session,
  so a shared session's owner was moved off its shell window while the
  joiner reattached to that shell window; pre-existing on master).  A
  `pm session` that finds the TUI running selects nothing.  The
  `after-kill-pane` hook's new-window fallback is unchanged by this: it
  still switches a client through `current_or_base_session` (the killing
  client when one typed the kill; ambiguity 16 covers a kill typed with
  no client).
- **GIVEN** another pm process holds the session's pane-registry lock
  (a stuck command), **WHEN** the user runs `pm session` while the
  registry lacks the running TUI, **THEN** the attach still completes
  after the lock wait, with no traceback and no second TUI; a later
  attach records the entry once the lock is free (review e661 i1).
- **GIVEN** another pm process holds the session's *TUI-respawn* lock (a
  stuck command), **WHEN** the user closes a pane of the session (any
  pane, in a session with one or several pm windows), kills the TUI
  pane, or runs `pm session` from another terminal,
  **THEN** each of them goes ahead after at most one lock wait (about
  10 s), logging that the lock was still held: the TUI is respawned
  exactly once, the attach completes, no terminal shows a traceback, and
  the layout rebalances.  A pane close or TUI kill takes the lock once
  per event, however many pm windows (main, review, QA) the session has,
  and lays out the windows after releasing it, so the closing client is
  frozen for one wait at most: a wait that grows with the number of the
  session's windows fails (QA S47 measured 30.2 s with three windows,
  one 10 s wait per window; fixed in b89aa9a4, verified live at
  ~10.2 s; ambiguity 15).  Another session's pane closes and attaches do
  not wait at all (the lock is per session).  When the lock cannot be
  taken at all (its file cannot be opened or locked, as on a filesystem
  without working locks, or a directory sits at the lock path), the hook
  and the attach go ahead at once, with no wait, and log one "cannot
  lock" line per event (review ad65 i1; before it, every pane close and
  attach waited the full 10 s there).
- **GIVEN** a running session whose repo directory name contains a space
  (so the session name does), with the `pm-home` window beside the TUI,
  **WHEN** the user adds a PR and looks at that window (it refreshes on
  its own poll),
  **THEN** it shows the PR list — the table of PRs with their status —
  and not an argparse usage line, and the list includes the new PR.
  The window's command quotes the interpreter path and the session name
  as single shell words (review-loop 1346 i1: before it, the space split
  the name into extra argv entries and the window showed its usage
  line).
- **GIVEN** a pm project directory that is not a git repository — its
  `.git` was removed (or the project was copied without history) after
  `pm init` — **WHEN** the user runs `pm session` there from a plain
  shell, **THEN** it starts the private session under the directory's
  fallback name (`pm-<dir>-00000000`) on its own socket, `pm session
  list` shows it, and a later `pm session` attaches to it; `pm session
  --global`/`--group` refuses ("Cannot determine session tag (not in a
  git repo?)") and creates no server.  The fallback name carries a hash
  of the share mode when one is set, so the private name and a shared
  invocation's name differ (review-loop 9d4c i4).
- **GIVEN** that non-git project, **WHEN** the user runs `pm session`,
  `pm session name`, `pm session --print-connect` or `pm session kill`
  from a *subdirectory* of it, **THEN** each resolves the project's own
  fallback name (the directory holding `pm/project.yaml`, or the legacy
  standalone layout's root-level `project.yaml`, not the subdirectory's
  basename): `pm session` attaches to the project's session instead of
  starting a second one on a second socket, and kill/list/connect name
  that same session.  The walk-up prefers any ancestor with
  `pm/project.yaml`; only when there is none does it use the nearest
  ancestor with a root-level `project.yaml`, so a target repo's own
  `pm/` subdirectory anchors on that repo rather than on an outer
  standalone project (QA S62, commit 50cbdef7; review-loop 3d42 i1).

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
    so a `~` in the tag must not be truncated (review-loop b48f i11);
  - a session whose name contains East-Asian wide characters (a repo
    directory named `日本語`, which `tmux_safe_name` keeps as-is) is
    listed with its full name and its own socket, and the SESSION,
    CLIENTS and SOCKET columns line up with the header on every row:
    the column is padded by terminal cells, not by code points, so a
    wide name does not push the later columns right (review-loop 43f6
    i2, commit ed48339b).
- **GIVEN** a running pm session A also open through the user's own tmux
  view named with a leading or trailing space (e.g. ` lead view`,
  `trail view `), or through a view named like one of A's grouped
  sessions (` pm-x~1`), with a client attached through it,
  **WHEN** the user runs `pm session list` from a plain shell and from
  inside that view,
  **THEN** A appears exactly once with its own socket, the view gets no
  row of its own, and a client on the view is not counted as one of A's
  grouped-session clients (`tmux list-clients` is authoritative).  The
  view named ` pm-x~1` is not reported as a real grouped session, and
  running the list from inside it does not list it a second time
  (review-loop 9d4c i2/i3/i4).
- **GIVEN** `/tmp/pm-sessions` is a directory owned by another user
  (e.g. root) with mode `1733` — sticky and world-writable, so `pm
  session` accepts it and creates sockets there, but not readable by
  others, so its entries cannot be enumerated —
  **WHEN** the user, with a private session running, runs `pm session
  list`,
  **THEN** it never prints a bare "No pm sessions found." as if nothing
  were running, and never crashes (exit 0).  It lists the sessions it can
  still reach: the cwd project's session through its deterministic socket
  (also from a subdirectory, and through a long name's hashed socket),
  plus any legacy session on the default server.  On stderr it says the
  socket directory cannot be read, so other sessions may be running; run
  from outside any project, it adds that running it from a project
  directory checks that project's session (QA S34, commit 43b35445).  Run
  from *inside* a pm pane, whose cwd may be a PR workdir clone, a
  subdirectory or a directory outside any repo, it also lists the session
  the pane belongs to (the same-set rule above; ambiguity 12; QA S40,
  commit 99deef53).  That session is found through `$PM_TMUX_SOCKET`,
  else the socket `$TMUX` names, and only when that socket is an entry of
  `/tmp/pm-sessions`; it goes through the same `lstat` check as the scan
  (a symlink or non-socket entry is skipped), and a dead or stale one is
  not listed.  The stderr
  warning names what was checked: this project's session, the session
  this command runs in, or both.  A legacy pane's default server is
  listed as always and is not probed a second time.  A plain shell's
  output is unchanged by this.  `pm
  session`, `--print-connect`, `pm tui view` and `pm session kill` in the
  project's directory still find the session through its deterministic
  socket path (`list` applies `paths.shared_socket_dir_is_usable`,
  review-loop 68bd i4).

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
  (review-loop b48f i4).  That holds when a grouped session's or a
  view's name contains a leading or trailing space: the client listing
  keeps the name verbatim, so the group match does not drop it
  (review-loop 9d4c i2).
- **GIVEN** the session is open through a view named with a leading or
  trailing space (` lead view`, `trail view `), **WHEN** a client on
  that view presses the quit key, **THEN** exactly that client detaches,
  the TUI keeps running, and no other client of any pm session is
  touched: the pane's session name is read verbatim, the group lookup
  finds A, and the detach targets that client (review-loop 9d4c i3).
- **GIVEN** a view whose name looks like a grouped session of A but has
  an edge space (` pm-x~1`, `pm-x~1 `), **WHEN** the user runs
  `pm session` for A, kills A, presses the quit key, or A sizes its
  layout, **THEN** that view is not treated as one of A's grouped
  sessions — the user is not attached to it, it is not counted, killed
  or detached, and its client's size does not constrain A's window.
  Only a name tmux reports verbatim, with an all-digit remainder after
  `<base>~`, is a grouped session (review-loop 9d4c i4).

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
- **GIVEN** a regression test exists in the project's QA library,
  **WHEN** the user runs `pm qa regression <id>` while the project's pm
  session runs on its own server (see R13), **THEN** it starts an
  isolated clone run and never targets, drives or captures the user's
  live session; `--session` is ignored with a note.  (Master's #284
  regression-run rework, merged in `c3bac6ce`, supersedes the old
  live-pane runner: the run has no session of its own to find, so the
  "no TUI pane found" refusal is obsolete.)
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
- **GIVEN** a client attached through a view named with a leading or
  trailing space, **WHEN** the user presses the pane-switch prefix keys,
  runs `pm tui view`/`pm tui send` with no `--session`, opens a
  plan-step review (its background pane opens beside the TUI), or opens
  the prefix+M popup from a repo directory whose name ends with a space,
  **THEN** each resolves the pm session it is grouped with and acts on
  it: the mobile-aware switch runs, the TUI is driven, the review pane
  opens, and the popup starts in the real repo directory — none of them
  silently no-ops on a trimmed name (review-loop 9d4c i3/i4).
- **GIVEN** a repo directory whose path contains a single quote, with a
  pm project and no PRs (the guide's setup mode), **WHEN** the user runs
  `pm guide` from inside the project's pm session, **THEN** the guide
  starts in that pane (the fake or real Claude runs with the setup
  prompt) and the guide session is recorded; there is no bash parse
  error and no traceback (review-loop 1346 i1: the root was
  interpolated in literal quotes).
- **GIVEN** the same quoted path, **WHEN** the user runs `pm cluster
  explore --bridged` from inside a pm session, **THEN** it prints
  `Bridge socket: <path>`, the socket file appears, and the bridge pane
  stays alive running the bridge with the repo as its cwd — it does not
  die on a shell parse error (review-loop 1346 i1: `--cwd` was
  interpolated in literal quotes).
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
  (`pm qa launch`, CLI or TUI), `pm meta`, or any
  prompt carrying the TUI section — **THEN** every copyable command in
  that prompt (`pm tui view -s …`, `pm tui send … -s …`, the
  `~/.pm/pane-registry/<session>.json` path, the discovery watcher's
  `tmux list-panes -t <session>:discovery`) quotes the name as one shell
  word, so pasting it runs against the right session; ordinary names stay
  unquoted (review-loop b48f i18/i19).  When the QA run is launched from
  a user's own view or a `~N` grouped session, the prompt names the base
  pm session, not the view (review-loop b48f i4).
- **GIVEN** the same space-named project, **WHEN** the user runs
  `pm qa regression <id>` from inside its pm session, **THEN** the run's
  own prompt names only the run's isolated clone/scratch paths and its
  own session (reachable through `pm session --print-connect`), never the
  user's live session; every path in it is quoted as one shell word, and
  the prompt file is written under the run's captures directory
  (`…/regression/<test-id>/<run-id>/prompt.md`).

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
- **GIVEN** a non-git project directory with its private session running
  under the fallback name (`pm-<dir>-00000000`), **WHEN** the user runs
  `pm session kill --global` (or `--group`) from inside that session or
  from a plain shell there, **THEN** it reports no session and kills
  nothing — in particular not the private session, its panes, clients or
  socket; a plain `pm session kill` still kills it (review-loop 9d4c i4:
  the fallback name ignored the share mode, so the shared name equalled
  the private one).
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
  A's windows.  No second TUI is started in A's window, not even
  briefly: the joiner's empty pane registry adopts A's running TUI (R2),
  and A's TUI keeps its pid.  The same holds when two users join at the
  same moment.
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
- **GIVEN** a directory that is not a git repository, **WHEN** the user
  runs `pm session --global`/`--group` there, **THEN** it refuses with
  "Cannot determine session tag (not in a git repo?)" and creates no
  server or socket; the private fallback session that directory may
  have is not a shared target (review-loop 9d4c i4).
- **GIVEN** that same non-git directory and a plain shell (not inside any
  pm session), **WHEN** the user asks for the
  connect command with the share flag (`pm session --global --print-connect`),
  **THEN** it refuses the same way and prints no
  attach command: the share-mode-hashed fallback name it would otherwise
  advertise can never exist, because `pm session --global` refuses to
  create it.  A plain `pm session --print-connect` (no share flag) still
  prints the private fallback session's socket-addressed command (QA
  planning 2026-11-03; the printed command must name a session
  `pm session` would actually use).- **GIVEN** a shared session, **WHEN** its owner runs a plain `pm session`
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
- **GIVEN** a shared session owned by another user, which the joining
  user has already attached to once with
  `pm session --global --dir <the owner's project>` (so the joiner's own
  `HOME` now has that session's pane registry),
  **WHEN** the joiner runs a plain `pm session` (no `--global`/`--group`)
  from a shell pane *inside* the shared session,
  **THEN** it reattaches to the same shared session on the owner's
  socket: no "Refusing to use tmux socket … owned by uid N, not you",
  no second server, no second TUI, and the owner's client is not moved.
  A grouped session it creates gets the shared `smallest` window size
  (read from the session environment).  A plain invocation drops
  `PM_SHARE_MODE` (`_set_share_mode_env`), so the private-socket
  ownership check must exempt the server this process is already
  attached to (R12; review-loop 43f6 i1, commit b36d5173).  The same
  joiner from a *plain shell* outside tmux still starts their own
  private twin on its own socket, as the previous bullet says.
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
  starting in its project — another terminal killed it between the rollout
  lookup and the first re-check, or later, after that re-check said "still
  running", while the start waited on the TUI-respawn lock or ran its TUI
  check, **WHEN** the start completes, **THEN** the session is created on
  the project's *private* socket — never as a second session on the
  default server, which the next `pm session` would keep treating as
  legacy — and the rollout note is not printed for the session that
  vanished.  The note is printed only inside the attach branch, after the
  session is confirmed still there, so it never describes a session that
  is not being attached (review-loop 8d4e i1; the TUI-check window and
  the note placement in 60a8 i2).  A start whose legacy session survives
  still attaches it and prints the note exactly once.
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
- **GIVEN** a pm session A running on its private server, and a plain
  (non-pm) session the user creates beside it on that same server (a
  scratch shell session),
  **WHEN** the user splits a pane in the scratch session, closes one,
  and resizes its client,
  **THEN** nothing of pm's runs there: no pane registry file is created
  for it, no layout is rebalanced, no `pm _tui` pane (or pm guide, or
  Claude) is started, and A's panes, layout and registry are unchanged;
  the close and resize print no traceback.  The same holds when a stale
  registry file from an older pm still lists panes in the scratch
  session — the resize hook ignores it too (QA S58, commit fc99e992;
  review-loop 9d4c i1).  A pane split, close and resize in A still
  register and rebalance.
- **GIVEN** a session whose windows include one named with a leading or
  trailing space and one with an empty name (tmux accepts both),
  **WHEN** the user attaches, resizes, or opens/closes a pane (a
  rebalance runs),
  **THEN** those windows are included: their panes are laid out to the
  session's shared size like every other window, and a name-based lookup
  still finds them; no window is dropped or treated as unnamed because
  its name was trimmed (review-loop 1346 i1).
- **GIVEN** a QA run in a session whose repo directory name contains a
  space,
  **WHEN** the run creates its status pane (the dashboard beside the
  planner),
  **THEN** the pane shows the dashboard — scenario rows and status — and
  not the `qa_status` usage line (review-loop 9d4c i2: the command's
  arguments were not quoted).  When the dashboard is opened from a
  client attached through a view named with an edge space, its Enter
  switch moves that client to the pm session's window, not to a name
  that does not exist (review-loop 9d4c i3).
- **GIVEN** a pm session whose tmux server was started from a shell
  inside another tmux session (a harness, or any ambient tmux), so the
  server's environment carries that tmux's `$TMUX`/`$TMUX_PANE` — a pane
  id that does not exist on the pm server, and `$TMUX_PANE` may be empty
  for a `run-shell` hook,
  **WHEN** the user kills a pane of the pm session (the
  `after-kill-pane` hook fires),
  **THEN** the hook handles the session it fired in: a killed TUI is
  respawned in that session (in the window the registry listed it in,
  else `main`), never reported as "no registry for " with an empty
  session name, and nothing is respawned in the ambient session.  The
  installed hook passes `#{q:session_name}` to `pm _pane-closed` and
  falls back to `$TMUX_PANE` only when the name is empty (QA S54, commit
  bb80cd1a).
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
  **WHEN** a client next attaches to the session through `pm session`
  (the attach rebalances every window, including the ones the registry
  still lists but tmux no longer has) — also when that `pm session` runs
  from a pane of a *different* pm session, whose server may still have a
  live window with the same `@N` id —
  **THEN** the killed window's entry is dropped from the session's pane
  registry (judged against the session's own server), the other
  session's registry is untouched, and later pane launches and layouts
  in the surviving windows are unaffected (QA S28).

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
- **GIVEN** the session the command runs inside is attached to another
  user's shared socket (a joiner), **WHEN** that user runs a plain
  `pm session` from a pane of it, **THEN** the ownership check is
  skipped for that server only, and the start reattaches (R9).  The same
  user from a plain shell (not attached), or a pane of a *different*
  session, still refuses another user's socket at the target's path.
  The exemption is "the server this process is already attached to",
  never "any socket that answers": a planted server under a project's
  deterministic name is still refused when the command is not running on
  it, and a legacy default-server socket never equals the deterministic
  path, so it is never exempt (review-loop 43f6 i1/i2).
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

### R13 — Regression runs are isolated from every live pm session

Master's #284 regression runner supersedes the live-pane runner this
branch started from (merge of `c3bac6ce`, 2026-11-04).  A regression run
clones the base branch and drives a disposable project of its own; it
never drives, captures or types into the user's session.  Because every
pm session now has its own server, the run's environment scrubs
`PM_TMUX_SOCKET` along with `TMUX`, `TMUX_PANE`, `PM_PROJECT`,
`PM_SESSION` and `PM_SHARE_MODE` (`cli.qa._REGRESSION_SCRUBBED_ENV`):
keeping the user's live socket would hand the run an ambient address for
a session it must never reach.

- **GIVEN** a pm project with a regression test in `pm/qa/regression/`
  and its session running on its own socket, **WHEN** the user runs
  `pm qa regression <id>` from a shell inside that session (or from a
  plain shell in the project directory), **THEN** it prints
  "Running regression: <title>", the base-branch target with its commit,
  "Runs in: host (container mode is off)" (or the container name), and a
  captures path under
  `~/.pm/sessions/<tag>/captures/regression/<test-id>/<run-id>/`; the
  run starts in a clone of the base branch and the user's panes, TUI and
  registry are not touched by it.  `--session` is ignored with a note
  ("a regression run never targets a pm session").
- **GIVEN** the same run in host mode, **WHEN** the run's shell (or a
  user reproducing it) runs a plain `tmux` command and a `pm` command
  from the clone, **THEN** the plain `tmux` reaches the default server
  (the run's `$TMUX` is unset and `PM_TMUX_SOCKET` is absent), the `pm`
  command resolves the run's own session/socket, and the prompt says to
  obtain that socket with `pm session --print-connect` rather than
  naming the user's live socket.
- **GIVEN** the run is started with `--file-prs`, **WHEN** it files a
  finding with `pm -C <registry> pr add …` from the clone, **THEN** the
  user's registry gains the PR and the user's TUI (and pm-home) reloads
  — the run reaches the session that owns the registry, not another pm
  session and not the disposable test project's own TUI.
- **GIVEN** a repo path with a space or a single quote, **WHEN** the
  user runs `pm qa regression` from inside its session, **THEN** the run
  launches normally (no empty prompt, no shell parse error), the prompt
  file is written under the run's captures dir, and the target paths in
  the prompt are quoted as one shell word.
- **GIVEN** two `pm qa regression` runs started at the same moment (the
  same test twice, or two different tests), **WHEN** both are launched,
  **THEN** each gets its own run id, workdir and captures directory,
  neither run addresses the other's session, and findings filed by both
  land in the registry without a lost update.

### R14 — A command's project resolves across every pm server

`-C <pm dir>` (or `PM_PROJECT`) names the project a command works on.
Because each session has its own server, the lookup must resolve the
project's session wherever it runs, and inside a pm session the ambient
session stays the answer for TUI-driving commands.

- **GIVEN** pm sessions A and B running on their own sockets and a plain
  shell outside both projects, **WHEN** the user runs `pm tui view -C
  <B's pm dir>`, `pm tui send <key> -C <B's pm dir>`, `pm pr list -C
  <B's pm dir>` or `pm session home -C <B's pm dir>` (or the same with
  `PM_PROJECT` set), **THEN** the command acts on B's session/server,
  never A's, and it finds B even though the default server hosts no pm
  session.
- **GIVEN** the same setup with only B running, **WHEN** the user runs
  `pm tui view -C <B>` from a PR workdir clone (a directory that names
  no session), **THEN** it drives B's TUI.
- **GIVEN** a shell inside A's pane, **WHEN** the user runs `pm tui view
  -C <B>`, **THEN** the ambient session A is the answer: keys are not
  redirected out of the session the user is in.
- **GIVEN** another user planted a socket at B's deterministic name in
  `/tmp/pm-sessions` and the user has no share context, **WHEN** the
  user runs an implicit `-C` lookup for B, **THEN** the planted server is
  never probed or adopted (the lookup falls back to the default server
  and reports no TUI / lists only what it can reach), while a legacy
  session of that name this user owns on the default server is still
  found (review-loop 879b i2).
- **GIVEN** `-C` naming a directory that is not a pm project, **WHEN**
  the user runs a command, **THEN** it reports the usual no-project
  message (or falls back to the cwd's project) without a traceback and
  without adopting another user's socket.

### R15 — QA launch and QA resume resolve the right session after the merge

- **GIVEN** a pm session open through a user's own view (`myview`) or a
  grouped `~1`, **WHEN** the user runs `pm qa launch <id>` (CLI or TUI)
  from that client, **THEN** the prompt names the *base* pm session in
  every copyable command and in the `~/.pm/pane-registry/<session>.json`
  path, so pasting them drives the right session.
- **GIVEN** a QA run started from another clone of the project whose
  session is still alive on that clone's own server, **WHEN** this
  clone's TUI restarts and scans for resumable runs, **THEN** it leaves
  that run alone — no resume, no scenario relaunch, no bogus verdict —
  and a run whose session is gone (or whose name is only a foreign
  planted socket) is resumed here (R7).
- **GIVEN** the QA status dashboard in a space-named session, **WHEN**
  the run creates it, **THEN** it shows the scenario rows and status,
  not the `qa_status` usage line (R11).

### R16 — The merged registry keeps every PR, plan and note

- **GIVEN** the project registry after the master merge, **WHEN** the
  user runs `pm pr list`, `pm plan list`, `pm pr show pr-073910f` and
  `pm pr note list pr-073910f`, **THEN** no PR id appears twice, every
  PR that exists on master exists here, every plan id is intact, and
  both master's notes and this branch's notes are still attached to
  their PRs; the TUI tree lists the same set.
- **GIVEN** two terminals running `pm pr add` / `pm pr note add` at the
  same moment, **WHEN** both complete, **THEN** both records are present
  (the store lock serialises them) and no note is lost.

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
- Repo directory names containing a Unicode line separator (`U+0085`,
  `U+2028`, `U+2029`), which tmux keeps but `str.splitlines()` splits on
  (two such projects side by side; the name with `_` everywhere the tag is
  used), and a legacy session or user view created before this change
  with one (not renamed; still unparsable — residual).
- A killed TUI whose registry entry was already reconciled away by
  another rebalance (the attach's background rebalance ~0.6 s after
  Enter, the `window-resized` hook, a pane's EXIT trap) when the
  `after-kill-pane` hook runs — repeated several times; also with the
  respawn lock stuck or unusable, where the hook leaves the respawn to
  the next `pm session`.
- A TUI that lived in a non-`main` window and whose registry entry is
  gone: both the attach and the hook must put it back in the same window
  (the listed one, else `main`, else the first).
- A socket directory pm can write but not read (`1733`, owned by another
  user).
- `pm meta` run in a shared session and in its private twin at the same
  time; plain `pm` commands in each resolve their own override.
- `pm session kill` typed inside the session it kills; a non-pm session
  hand-made on a pm session's private server.
- A window killed outside pm whose `@N` id is still live on another pm
  session's server.
- Command-bar and popup lines with unbalanced quotes.
- A pane registry that has lost track of a running TUI: the file was
  removed, the TUI is outside window index 0 (`base-index 1`, or a
  respawn into a new window), or a joiner's `HOME` has no registry.  Also
  a registry lock held by a stuck pm process.
- A TUI that is really gone in a session whose name contains `_tui`, or
  whose pane is dead under `remain-on-exit`.
- `pm session list` on an unreadable socket directory, run from inside a
  pm pane whose cwd is a PR workdir clone or outside any repo.
- The same, from a joiner's pane of another user's shared session, a
  legacy session's pane, a non-pm tmux session's pane, the prefix+M
  command prompt, a shell with only `$TMUX` (no `PM_TMUX_SOCKET`), and a
  plain shell that still exports the `PM_TMUX_SOCKET` of a session that
  has since been killed.
- A TUI found only by its start command (registry lost) after each of
  pm's start paths — fresh, shared, respawn split, respawn into a new
  window, `after-kill-pane` respawn, Ctrl+R, legacy — in sessions whose
  names contain quotes, `$`, `~`, multi-byte characters or `_tui`, or
  that use a hashed socket.
- Two legacy sessions on the default server, one with a crashed TUI
  and a lost registry: recovery and `pm tui` discovery never pick the
  other legacy session's TUI.
- A legacy session killed while `pm session` is starting it, at each
  point of the start: between the rollout lookup and the first re-check,
  and after that re-check while the start holds or waits for the
  TUI-respawn lock (a stuck holder widens that window).  The replacement
  must land on the private socket, the rollout note must not print for
  the vanished session, and two terminals starting the same legacy
  project at once must converge on one private session (R10, review-loop
  8d4e i1 / 60a8 i2).
- An `after-kill-pane` TUI respawn racing a `pm session` attach — in a
  private session, and in a shared session where the joiner's attach is
  not serialised with the owner's hook.
- A TUI pane killed from a shell in another project, in `/tmp`, in a
  subdirectory or PR workdir clone, or from a user's view created
  elsewhere; a killed TUI that was the last pane of its window; a repo
  path with a space, a quote, `$`, multi-byte characters or `#(cmd)`.
- The TUI-respawn lock held by a stuck process (one wait, not one per
  window) or impossible to take (no wait at all); several pane closes in
  different pm windows from different clients at the same moment,
  with and without a stuck holder.
- A `pm session` attach that respawns the TUI while other clients of
  the same session (another terminal's `~N`, a user's own view, a shared
  session's owner) are working in other windows; two such attaches at
  once; a reused unattached `~N`; `--disconnect-others`.  Only the
  attaching client is moved to the TUI window.
- A TUI that was alone in its window killed from a plain shell (no
  client typed it) while two clients look at different windows
  (ambiguity 16).
- A plain (non-pm) session created on a pm session's private server:
  split, close and resize there must leave it untouched (no registry, no
  rebalance, no TUI), including with a stale registry from an older pm,
  while the pm session's own hooks still work — and with both firing at
  once (QA S58, review-loop 9d4c i1).
- A user's own view named with a leading or trailing space (and one
  named like a grouped session, ` pm-x~1`): quit, pane switch, TUI
  driving, `pm session list`, `--disconnect-others`, plan-step review and
  dashboard Enter from it.
- A repo directory ending with a space (the popup's start directory,
  session name) and a repo path containing a single quote (`pm guide`,
  `pm cluster explore --bridged`).
- Windows named with leading/trailing spaces or with an empty name: a
  rebalance and a name lookup must include them.
- A space-named repo's `pm-home` window and QA status dashboard.
- A non-git project directory: the private fallback session, the
  `--global` refusal, and `pm session kill --global` not killing the
  private session (review-loop 9d4c i4); the same project run from a
  deep subdirectory, under both the modern (`pm/project.yaml`) and
  legacy standalone (root-level `project.yaml`) layouts, and a target
  repo's own `pm/project.yaml` beside an outer root-level
  `project.yaml` (QA S62, review-loop 3d42 i1).
- Two or more projects whose session names exercise `pm session list`'s
  column sizing and group-suffix parsing: a short CJK name (readable
  socket), a name long enough in *bytes* to hash the socket, and two
  names containing `~` beside a genuine grouped `~1` (review-loop 43f6
  i2, b48f i11/i21).

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
3. **A joining user's plain `pm session`** — from a *plain shell*
   outside tmux, the joiner starts their own private session (a twin on
   its own socket): there is no ambient session to adopt, and that is
   the fail-safe trade-off, not a failure.  From a shell pane *inside*
   the shared session, the ambient session is adopted; once the joiner
   has attached with `--global --dir` their own `HOME` has that
   session's registry, so a plain `pm session` reattaches to it and must
   not be refused (review-loop 43f6 i1).  The joining path is exercised
   through the documented forms: repeating `--global`/`--group`, or
   `--dir`.
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
11. **What a fresh `pm session` prints** — the create path prints
   "Creating tmux session '<name>'..." and attaches its `~1` without an
   "Attaching to session '<name>~1'..." line.  It does the same on
   master, and QA S1 passed on exactly that.  The extra line QA S35's L3
   story expected was a drafting error, not a requirement (resolved by
   the 2026-11-02 second planning pass).
12. **`pm session list` on an unreadable socket directory from inside a
   pm pane** — added by the 2026-11-02 second planning pass.  At that
   time the implementation probed only the cwd project's socket.  QA S40
   found the failure, and `99deef53` fixed it: the list now also probes
   the socket of the session the command runs in.  A pane's cwd can
   be a PR workdir clone, which has a different tag, or a directory
   outside any repo, while the session the pane belongs to is reachable
   through the pane's own socket.  Resolved by judgement from R3's
   same-set rule: not listing the session the command runs in is a
   failure, even with the "cannot read" warning printed.
13. **"TUI pane missing — respawning..." during a killed-TUI race** —
   added by the 2026-11-02 fourth planning pass, from the QA S42 note.
   After 698cbb97, an attach that takes the respawn lock before the hook
   finds the TUI gone, prints the line and starts the only TUI; the hook
   then sees it running and leaves the session alone (6 of 10 rounds in
   S42).  Resolved by judgement: the line is truthful (the TUI was gone
   when the attach looked), so it is allowed.  The requirement is one
   TUI, listed once, with no second TUI even briefly.
14. **A shared-session joiner's attach racing the owner's TUI-respawn
   hook** — added by the 2026-11-02 fourth planning pass, from review
   ad65 i1.  The lock is in each user's own `~/.pm`, and a lock both
   users can take would need a world-writable file in `/tmp/pm-sessions`,
   so the race is left to the TUI pidfile guard.  Resolved by judgement:
   a second TUI that appears for a moment and exits on the pidfile guard
   is the documented trade-off, reported but not failed by itself.
   Lasting damage fails: two running TUIs, a non-TUI process started in
   the session, a traceback on a user's terminal, or registries that
   stay inconsistent after the next reconcile.
15. **How long a held TUI-respawn lock may block a pane close** — added
   by the 2026-11-02 fourth planning pass.  `tui_respawn_lock` gives up
   after 10 s and goes ahead.  But the `after-kill-pane` hook takes it
   once per registered window, in a synchronous `run-shell`, so the
   client that closed the pane may stop responding for 10 s times the
   number of the session's pm windows.  Resolved by judgement: the
   documented bound is one wait per event.  A pane close that blocks
   for one wait per window fails, and the scenario reports the measured
   delay with one and with several windows.  Confirmed live by QA S47
   on c326fb31 (a review-pane close froze its client 30.20 s and a TUI
   kill 30.34 s with main + two review windows) and fixed in b89aa9a4:
   the hook takes the lock once around the whole reconcile and respawn
   pass and lays the windows out after releasing it (post-fix ~10.2 s,
   one "still held" line; an unusable lock logs one "cannot lock" line
   per event).  Several pane closes from different clients at the same
   moment are separate events: each waits on its own, so a stuck holder
   still freezes each closing client for one wait, not one per window
   or one per queued event.
16. **Which client the hook's new-window fallback switches when no
   client typed the kill** — added by the 2026-11-02 fifth planning
   pass, from QA S45 and commit f162a71c.  That commit stopped a
   `pm session` attach from switching another client to a respawned TUI
   window, but left the `after-kill-pane` hook's new-window fallback
   alone: it still selects through `current_or_base_session`.  When a
   client typed the kill (C-b x, a `tmux kill-pane` in a pane), that is
   the killing client (QA S46, S48).  When nothing typed it (a
   `tmux kill-pane` from a plain shell, a script), there is no killing
   client: the hook's `run-shell` has no `$TMUX_PANE`, so the session it
   resolves is whatever tmux reports for an unattached command (its best
   or most recently active session), which may be the grouped session of
   a client working in another window.  Resolved by
   judgement: a client whose window vanished with the TUI may be shown
   the new TUI window, but a client that was working in a *different*
   window must not be moved off it: its next keystrokes would land in
   the TUI, where single letters start PR actions.  A move of such a
   client is a finding; report which client moved and whether master
   does the same (the hook path is pre-existing).
17. **A killed TUI whose registry entry another reconcile removed, under
   a stuck or unusable respawn lock** — added by the 2026-11-02 sixth
   planning pass, from the QA S50 fix 664df245.  Under the lock the
   `after-kill-pane` hook starts a TUI when the registry lists none and no
   `pm _tui` pane runs, so a reconcile the hook did not do cannot leave
   the session without a TUI.  But it does so only when it really holds
   the lock: when the lock is stuck (10 s wait) or cannot be taken at all
   and the hook goes ahead anyway, it leaves the unlisted-TUI respawn
   alone, because two hooks past the same stuck holder would both start
   one.  Resolved by judgement: in that state the session may sit without
   a TUI until the next `pm session` attach, which starts exactly one.
   A scenario reports that outcome; the attach recovering it is what must
   pass.  A hook that starts a second TUI beside a live one fails.
18. **A legacy session or user view whose name contains a Unicode line
   separator** — added by the 2026-11-02 sixth planning pass, from
   review-loop 1237 i2 (commit 9037574f).  New sessions replace
   `U+0085`/`U+2028`/`U+2029` with `_` because pm parses tmux listings
   line by line, but a session or view created *before* this change keeps
   the character: tmux stores it, pm reads it back as two records, and it
   is not renamed (renaming a running session would break the user's
   attachments and its grouped sessions).  Resolved by judgement: such a
   pre-existing name staying unparsable is a documented residual, not a
   failure of this PR; a *new* session whose name still contains one is a
   failure.
19. **Where a respawned TUI goes when the record of its window is gone** —
   added by the 2026-11-02 sixth planning pass, from the QA S50 fix and
   review-loop 1237 i1.  The shared rule is "the window the registry (or
   the hook's snapshot) listed it in, else `main`, else the first
   window".  When another reconcile removed the entry before the hook
   read the registry, the hook's snapshot does not list it either, so a
   TUI that had lived in a review window comes back in `main`.
   Resolved by judgement: accepted — there is no record of where it was,
   and `main` is the deliberate default (never the active window, which
   may be a QA or work window).  The attach and the hook must agree, and
   neither may use the active window.
20. **The private-socket ownership check and the server a process is
   already on** — added 2026-11-02 from review-loop 43f6 i1/i2.  A plain
   `pm session` inside a shared session drops `PM_SHARE_MODE`, so
   `is_shared` is false while the socket belongs to the sharing user.
   Resolved by judgement: the ownership check and its probe are skipped
   only for the socket this process is attached to
   (`_attached_to_session_socket`), exactly as `kill`/`mobile` already
   do; every other implicit target — a plain shell, a pane of a different
   session, a legacy session on the default server — still requires
   ownership.  Both sides are asserted, so the exemption cannot widen
   into "adopt any socket that answers".
21. **Column alignment in `pm session list`** — added 2026-11-02 from
   review-loop 43f6 i2.  `tmux_safe_name` keeps valid non-ASCII text, so
   the SESSION column must be measured in terminal cells
   (`paths.display_width`), not code points.  Resolved by judgement: a
   CJK-named project's row must line its CLIENTS/SOCKET columns up with
   the header and every other row; padding by `len()` shifts them right
   and fails.
22. **Non-pm sessions on a pm server and the global hooks** — added
   2026-11-03 from QA S58 (commit fc99e992) and review-loop 9d4c i1.
   The pane hooks are global on the session's server, so they also fire
   for a plain session a user creates beside the pm one.  Resolved by
   judgement: every handler resolves the hook's session through its tmux
   group and ignores it unless the resolved name is a pm one — no
   registry, no rebalance, no respawned TUI — including when a stale
   registry from an older pm (exactly the file the S58 bug left) still
   lists panes there.  A user's own grouped view of a pm session still
   resolves to the base and is handled.  An unresolved (empty) session
   keeps logging `no registry for ` as before; a failure is a pm TUI
   started in the scratch session, a registry created for it, or a
   rebalance of it.
23. **Edge spaces in view and window names** — added 2026-11-03 from
   review-loop 9d4c i2/i3/i4 and 1346 i1.  tmux stores a session name
   and a window name as given, so a user's own view may be named
   ` lead view` / `trail view ` and a window may be named with edge
   spaces or with no name at all.  Resolved by judgement: every readback
   keeps such a name verbatim (`rstrip("\n")` on a single-line query,
   `splitlines()` with no `strip()` on a listing), and a view named
   ` pm-x~1` is a view, not a grouped session — only a verbatim name
   with an all-digit remainder after `<base>~` is a grouped session.  A
   repo directory ending with a space is a real path and is used
   verbatim for the popup's start directory.
24. **The remaining command builders are in scope** — added 2026-11-03
   from review-loop 1346 i1 and 9d4c i2.  The `pm-home` PR-list command,
   the QA status dashboard command, `pm guide`'s setup command and the
   `pm cluster explore --bridged` bridge command each interpolate a
   session name or a repo path into a shell command.  Resolved by
   judgement: they are part of this PR's "a name or path is data" class
   (1346 i1 item 3 records `guide.py` as incidental but fixed), and a
   user hitting one in an awkward-named project must get the normal
   surface — the PR list, the dashboard, the guide, a live bridge — not
   a usage line or a shell parse error.
25. **A non-git project directory's fallback name and the share mode** —
   added 2026-11-03 from review-loop 9d4c i4.  A pm project directory
   that is not a git repository gets the fallback session name
   `pm-<dir>-00000000`; with a share mode set the fallback now ends in a
   hash of the mode.  Resolved by judgement: the private session must
   not be reachable as a shared target, so `pm session kill --global` in
   that directory reports no session and kills nothing, and
   `pm session --global` refuses (a shared session needs a git tag).  A
   plain `pm session`/`pm session kill` still works there.
   `pm session --global --print-connect` refuses too rather than
   advertising the share-mode-hashed fallback name, which can never
   exist (QA planning pass 8, 2026-11-03; the code's own stated contract
   is that a printed command names a session `pm session` would use).
26. **Which directory anchors a non-git project's fallback name** —
   added 2026-11-03 from QA S62 (commit 50cbdef7) and review-loop 3d42
   i1.  With no git root to hash, the name is taken from the project
   directory found by walking up from the cwd: the nearest ancestor with
   `pm/project.yaml`; only when there is none, the nearest with a
   root-level `project.yaml` (pm's legacy standalone layout, which
   `store.find_project_root` still accepts); only when neither exists,
   the cwd itself.  Resolved by judgement: every session-keyed command
   (`pm session`, `name`, `--print-connect`, `list`, `kill`, `mobile`,
   TUI discovery) must agree on that anchored name, so running any of
   them from a subdirectory reaches the project's session instead of
   starting or targeting a second one.  Any ancestor with
   `pm/project.yaml` outranks every root-level `project.yaml`, so a
   target repo's own `pm/` subdirectory is never mistaken for an outer
   standalone project.
27. **`pm qa regression` no longer drives the live TUI** — added
    2026-11-04 with the master integration (`c3bac6ce`).  Master's #284
    regression runner (an isolated clone, optionally a container)
    supersedes the live-pane runner this branch started from; the merge
    keeps master's runner and the branch's session-name quoting in
    `qa launch` and `pane_ops`.  Resolved by judgement: `--session` is
    ignored with a note, and R7's old "no TUI pane found" refusal is
    obsolete — the run has no session of its own to find, and a scenario
    that expects the refusal is wrong.
28. **`-C`/`PM_PROJECT` versus the ambient session** — added
    2026-11-04.  Outside a pm session the project override names the
    session a command works on (a PR workdir clone names no session by
    cwd); inside a pm session the ambient session is the answer for
    TUI-driving commands, so keys are never redirected out of the
    session the user is in.  Resolved by judgement from the code order
    (`_find_tui_pane`: in-tmux branch, then `_project_sessions`, then
    cwd) and the ownership rule every implicit lookup passes.
29. **A host-mode regression run's `PM_TMUX_SOCKET`** — added
    2026-11-04.  The user's live socket is scrubbed from the run's
    environment along with `TMUX`/`PM_PROJECT`/`PM_SESSION`/
    `PM_SHARE_MODE`, because under per-session servers it names a server
    the run must never drive.  Resolved by judgement: the run's own `pm`
    resolves each session's socket, the prompt points at
    `pm session --print-connect`, and filing (`pm -C <registry> pr add`)
    still reaches the user's TUI through `_project_sessions`.

## Known pre-existing issues (not failures of this PR)

These were found during QA and review on this branch, filed as separate
bug PRs, and are deliberately out of scope here.  A scenario that meets
one records it and continues; it does not fail the scenario.

- **pr-50e6077** — a repo directory name near the 255-byte `NAME_MAX`
  makes the tag push `~/.pm/pane-registry/<base>.json`, the pidfile, the
  command queue and `~/.pm/sessions/<tag>/` past `NAME_MAX`, so
  `pm session` dies with an uncaught `OSError` before creating anything.
  Pre-existing on master; this PR hashes only the *socket* path.  Use a
  moderately long name (tens of characters), not a ~240-character one,
  when exercising the hashed-socket rule.
- **pr-939ea27** — a TUI killed from outside tmux (no client typed the
  kill) may have the `after-kill-pane` respawn switch a client that was
  working in another window (ambiguity 16; the hook path is pre-existing).
- **pr-48f359f** — after `C-b &` closes the TUI's window, the respawn's
  new-window fallback picks the first surviving window rather than a new
  one or the remembered TUI window.  Pre-existing; the choice needs a
  design decision.
- **pr-07541e7** — `pm session` prints a raw `TmuxCommandError` traceback
  when its attached client's terminal goes away during the attach.
- **pr-3121cc8** — the `after-kill-pane` hook's respawn log lines are
  written to the wrong place under some conditions.
