# QA spec — pr-c3bf868

Bug: stale TUI pidfile lets picker / reload IPC silently target a dead or
wrong process.

The pidfile `~/.pm/tui-<session>.pid` drives two IPC paths — SIGUSR1
(reload) and SIGUSR2 (command queue) — both of which used to read a bare
PID and `os.kill` it. The fix makes the pidfile a versioned JSON
descriptor (`{version,pid,session,started_at,starttime,caps}`), adds a
capability gate, adds exclusive TUI-side takeover of the pidfile, and adds
caller-side process-identity validation plus a spinner abort. See
`pm/specs/pr-c3bf868/impl.md` for the implementation map.

## Surfaces a user actually touches

- `pm session` / the TUI pane (`pm _tui`) — writes and claims the pidfile,
  installs the SIGUSR1/SIGUSR2 handlers, drains the command queue.
- Any `pm pr …` mutation run from another pane (`pm pr add`, `pm pr edit`,
  …) — SIGUSR1 reload (`trigger_tui_reload`).
- `pm autostart add|remove|clear|list|status` — SIGUSR2 command queue
  (`submit_tui_command`).
- The action picker (prefix+P popup) — actions routed as `tui:` commands
  go through the same queue, then the `queued…` spinner
  (`_wait_for_tui_command`).
- On-disk state the user can inspect: `~/.pm/tui-<session>.pid` (now
  JSON), `~/.pm/tui-<session>.cmd-queue`, `~/.pm/debug/<tag>.log`.

## Requirements

### R1 — A healthy TUI advertises itself with a versioned descriptor

- **GIVEN** a pm session with the TUI running
- **WHEN** the user inspects the session's pidfile
- **THEN** it is a JSON object naming the TUI's pid, the session, a
  `started_at`, a `starttime`, and `caps` containing both `sigusr1` and
  `sigusr2` — not a bare number
- **THEN** the TUI log records that both handlers were installed

### R2 — Reload from a CLI mutation still reaches the TUI

- **GIVEN** a running TUI showing a project's PRs
- **WHEN** the user adds (or edits) a PR with `pm pr …` from another pane
  in the same session
- **THEN** the TUI reflects the change without the user pressing the
  refresh key
- **THEN** the TUI process is the same process afterwards (same pid, no
  restart, no crash)

### R3 — A queued command from the CLI is applied by the TUI

- **GIVEN** a running TUI
- **WHEN** the user runs `pm autostart list` (or `add`/`remove`/`clear`)
  from a pane in the session
- **THEN** the command reports the TUI's answer (targets, changes, …)
  rather than an owner/signal error
- **THEN** the session's command-queue file is drained (no command left
  pending)

### R4 — A picker action routed through the TUI completes

- **GIVEN** a running TUI with at least one PR that has an action
- **WHEN** the user opens the action picker (prefix+P) and picks an action
  that is routed through the TUI
- **THEN** the picker shows progress for that action and then resolves
  (state change and/or the target window appearing) — it does not sit on
  "queued…" indefinitely
- **THEN** the TUI applied the action (the corresponding state/window
  appears)

### R5 — A dead TUI's pidfile produces a message, not a hang (caller side)

- **GIVEN** a TUI that was killed hard (SIGKILL) so its pidfile still
  names a now-dead pid
- **WHEN** the user routes a command to the TUI (`pm autostart …`, or a
  picker action)
- **THEN** the command exits non-zero with a readable "the TUI … is not
  running / restart the TUI" message — no traceback, no spinner
- **THEN** the stale pidfile is removed

### R6 — A dead TUI's pidfile is taken over at startup (TUI side)

- **GIVEN** the same stale pidfile (dead pid) left behind by a killed TUI
- **WHEN** the user starts a TUI for that session
- **THEN** the TUI starts normally and `pm tui view` shows a working UI
- **THEN** the pidfile now names the new TUI's pid with both capabilities
- **THEN** a subsequent TUI-routed command succeeds

### R7 — Version skew: a TUI without the command capability is never killed

- **GIVEN** a live TUI that advertises only `sigusr1` — either a TUI from
  the pre-upgrade code (bare-number pidfile) or a JSON descriptor whose
  `caps` lack `sigusr2`
- **WHEN** the user routes a command to it (`pm autostart …` or a picker
  action)
- **THEN** the TUI is still running afterwards (`pm tui view` works, the
  pane is alive)
- **THEN** the user sees a message that the TUI predates the command-queue
  feature (or does not advertise it) and should be restarted with Ctrl+R
- **THEN** the command is not applied, and the pidfile is not deleted
- **WHEN** the same user instead performs a CLI mutation (reload path)
- **THEN** the legacy TUI still reloads (a bare-number pidfile implies
  `sigusr1` support)

### R8 — PID reuse: an unrelated process is never signalled

- **GIVEN** a pidfile whose pid now belongs to a live process that is not
  a pm TUI (e.g. a recycled pid, or a pidfile written by hand for a
  `sleep`)
- **WHEN** the user routes a command and performs a CLI mutation
- **THEN** that unrelated process is still running afterwards (it was
  never sent SIGUSR1/SIGUSR2)
- **THEN** the user sees a "not available / stale" style message (command
  path) and the pidfile is removed

### R9 — A second TUI for the same session is refused

- **GIVEN** a TUI already running for a session
- **WHEN** the user starts a second TUI for the same session
- **THEN** the second one prints a message naming the owning pid and the
  pidfile path and exits non-zero
- **THEN** the first TUI keeps working and still owns the pidfile
  (unchanged content, unchanged pid)
- **WHEN** the user quits the first TUI normally
- **THEN** the pidfile is removed and a fresh TUI starts without complaint

### R10 — The spinner aborts when the TUI dies mid-flight

- **GIVEN** a picker action dispatched to a healthy TUI, still in flight
- **WHEN** the TUI is killed before it applies the command
- **THEN** within a few seconds the spinner aborts with a message that the
  TUI is no longer running and the command may not have been applied
- **THEN** restarting the TUI does **not** apply the failed command later
  (it was rolled back out of the queue)

### R11 — A restart while the spinner spins is not a false abort

- **GIVEN** a picker action dispatched to a healthy TUI
- **WHEN** the user restarts the TUI (Ctrl+R / `pm tui restart`) while the
  spinner is running
- **THEN** the spinner does not abort with a "TUI is gone" error and the
  command is still applied after the restart

### R12 — A corrupt pidfile never crashes the TUI or the CLI

- **GIVEN** a pidfile holding junk (binary bytes, whitespace only, an
  absurdly large pid, a bare-word value)
- **WHEN** the user starts a TUI for that session and, separately, routes
  a command to it
- **THEN** no traceback appears in the pane or the CLI output
- **THEN** the TUI starts and takes the file over; the CLI reports a
  readable "unreadable/stale pidfile" message and removes it
- **GIVEN** a zero-length pidfile
- **WHEN** the user routes a command
- **THEN** the message says the TUI has not finished starting up (and
  names the Ctrl+R restart fix), and the empty file is **not** deleted

### R13 — Session key correctness with more than one pm session

- **GIVEN** two pm sessions running (two projects, or a second client
  attached to another session)
- **WHEN** the user runs CLI commands in each session's context
- **THEN** each session's pidfile names that session's own TUI
- **THEN** a mutation in one project reloads only that project's TUI; the
  other TUI is untouched

### R14 — Concurrent dispatch loses and duplicates nothing

- **GIVEN** a healthy TUI
- **WHEN** two panes dispatch a TUI-routed command at the same time
- **THEN** both commands are applied exactly once and both callers get an
  answer (neither hangs, neither reports a failure it did not have)

### R15 — `pm autostart` surfaces the specific reason

- **GIVEN** a live TUI that lacks the command capability (version skew)
- **WHEN** the user runs `pm autostart add <pr>`
- **THEN** the error message names the missing capability / "restart the
  TUI (Ctrl+R)" rather than a generic "could not signal the TUI", and the
  command exits with the owner-unavailable status (2)

### R16 — The original failure does not reproduce end to end

- **GIVEN** a TUI started from the pre-fix code (a checkout of `master`
  used via `PYTHONPATH`), which writes a bare-number pidfile and has no
  SIGUSR2 handler
- **WHEN** the user routes a command to that session from the fixed CLI
- **THEN** the old TUI is still alive and the user is told it predates the
  command-queue feature
- **THEN** the same action driven by the *pre-fix* CLI kills that TUI
  (demonstrating the bug the fix closes) — the A/B pair is the evidence
- **THEN** the new test file's reproduction cases (`tests/test_tui_pidfile.py`:
  legacy capability refusal, dead-pid cleanup, claim takeover/refusal,
  no-op signal guard) pass against the fixed code

## Setup

All scenarios start from the TUI manual-testing setup: an editable pm
install in a venv with `PYTHONPATH` pointing at the scenario clone, a
throwaway git project initialised with `pm init --backend local`, a few
PRs, and a session created with `pm session` (attach failure is expected
and ignorable). Scenarios that need a second actor run commands in extra
panes of the same tmux session, never in the harness shell.

Recording: use the tmux screen-recording recipe for anything observed in
the session (pane transcript + cast + mp4), and the CLI recording recipe
for standalone CLI output. Save every capture under the per-PR captures
directory the scenario prompt names.

When a scenario needs a "pre-upgrade TUI", obtain one without touching the
scenario clone's working tree: `git worktree add <scratch>/master master`
and launch `PYTHONPATH=<scratch>/master pm _tui` in a pane (or install
that worktree into a second venv). Never edit `pm_core/` in place to
simulate old behaviour.

When a scenario needs a stale/foreign pidfile, write it as the user's
environment would have it (`~/.pm/tui-<session>.pid`) — that file is user
state, not source code.

## Edge cases

- **E1 Zombie owner.** A pidfile naming an exited-but-unreaped TUI reads as
  dead: the CLI reports stale and removes it; the TUI startup takes over.
- **E2 TUI still starting.** A descriptor with `caps: []` makes the command
  path refuse with "has not advertised its signal handlers yet" and keeps
  the file; the TUI finishes starting and the same command then works.
- **E3 Permission denied.** A pidfile naming a process the user may not
  signal yields a "could not signal" message, and the pidfile is **not**
  removed (the process is alive, just not ours).
- **E4 Command with line-break characters.** A command containing `\r` or a
  Unicode line separator is still one queue line: it is applied once, and
  a failed dispatch rolls it back whole.
- **E5 Unwritable state.** If `~/.pm` or the queue is not writable, the TUI
  still starts (no external IPC) and the CLI reports a write error instead
  of claiming success.
- **E6 Duplicate dispatch.** Submitting the same command twice applies it
  twice (both callers are answered); a rollback removes at most one copy.
- **E7 Kill between validation and signal.** A TUI killed just as a command
  is dispatched produces "the TUI … is not running (process disappeared)"
  and a rolled-back queue line, not a phantom success.
- **E8 Restart reuses the pid.** Ctrl+R / exec restart keeps the same pid;
  the pidfile is refreshed, not refused, and IPC keeps working across it.
- **E9 Two TUIs racing to start.** Exactly one wins the pidfile; the other
  refuses (or waits out the winner's mid-claim window) — never two TUIs
  publishing descriptors over each other.

## Pass/Fail criteria

A scenario passes when every THEN clause is observed on the real surface
(pane render, CLI stdout/exit status, file on disk) and no traceback,
hang, or unexpected process death occurs. It fails on: an old/foreign TUI
being killed, a caller signalling a process it did not identify as a pm
TUI, a stale pidfile that is neither reported nor cleaned, an indefinite
"queued…" spinner, two TUIs running for one session, a corrupt pidfile
crashing any surface, or a healthy TUI losing IPC after this change.
Partial passes must name the failing THEN clause and attach the evidence.

## Ambiguities

- **A1 (resolved) — how to obtain a "pre-upgrade TUI".** A git worktree of
  `master` launched via `PYTHONPATH` gives a real old TUI with a
  bare-number pidfile and no SIGUSR2 handler; rewriting a live TUI's
  pidfile to a bare number is an acceptable lighter-weight substitute
  (same descriptor shape, same capability gap) when a second checkout is
  impractical. Both are recorded in the scenario steps.
- **A2 (resolved) — driving the picker headlessly.** The picker is an fzf
  popup bound to prefix+P. Drive it by sending the prefix key into the
  session, or by running its popup body in a pane of the session; either
  way the observable is the picker UI plus the `queued…` spinner, not an
  internal call.
- **A3 (resolved) — startup-refusal visibility.** The real pm session has
  no `remain-on-exit`, so a refused second TUI's pane can vanish. Run the
  second `pm _tui` in an existing shell pane of the session so the message
  and the non-zero exit stay in the scrollback, and/or read
  `~/.pm/debug/<tag>.log`.
- **A4 (resolved) — what "the TUI is still alive" means.** Use both the
  process check (pid from the pidfile still exists) and the user surface
  (`pm tui view` renders, keypresses still work). A surviving process with
  a wedged UI is a failure.
