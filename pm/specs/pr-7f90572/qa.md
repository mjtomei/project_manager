# QA Spec: pr-7f90572 — meta window override cleanup (stale + overbroad)

## Background

`pm meta` (pm_core/cli/meta.py) launches Claude in a tmux window named `meta`
inside the current pm session, and writes a session override
(`~/.pm/sessions/<tag>/override` → `~/.pm/workdirs/meta-<tag>`). The wrapper
(pm_core/wrapper.py `_override_for_tag`) consults that file on every `pm`
invocation from the session, so all later `pm` commands run the meta clone's
`pm_core`.

The fix replaces the pane command's old trailing `; rm -rf ~/.pm/sessions/<tag>`
with a wrapper built by `_build_meta_pane_cmd()`:

- A `pm_meta_clear_override` shell function that removes **only** the override
  file, and only when its content still points at this meta workdir
  (`[ "$(cat <override>)" = <workdir> ] && rm -f <override> || true`).
- `trap pm_meta_clear_override EXIT HUP INT TERM`, so cleanup runs on a normal
  Claude exit **and** on pane death (`tmux kill-window` sends SIGHUP), Ctrl-C
  and SIGTERM.

Two bugs fixed:
1. **Stale override on abnormal exit** — kill-window left the override active;
   `pm which` kept resolving to the meta clone until removed by hand.
2. **Overbroad cleanup on normal exit** — the old `rm -rf ~/.pm/sessions/<tag>`
   wiped the whole shared session dir (debug marker, fake-claude config +
   scripted cursor, captures/<pr>/ QA evidence, per-session settings), so the
   next session component ran as real Claude (seen live in QA pr-592e4bd S50).

## Requirements (user stories)

### R1 — Closing the meta window clears the override

- **Given** a pm session running in tmux, with the meta window open (override
  active: `pm which` inside the session resolves to the meta workdir),
- **when** the user closes the meta window (`tmux kill-window` / prefix-&),
- **then** the override file `~/.pm/sessions/<tag>/override` is gone, and
  `pm which` run in a session pane no longer points at the meta workdir.

### R2 — A normal meta exit clears the override but nothing else

- **Given** a pm session whose session dir holds state other than the override
  (debug marker, fake-claude config, `captures/<pr>/` evidence files), with the
  meta window open,
- **when** the meta Claude session exits normally,
- **then** the override file is removed (so `pm which` resolves to the normal
  install again), and every other file in the session dir — debug marker,
  fake-claude config, captures — still exists.

### R3 — Cleanup removes only what the meta window owns

- **Given** a meta window open, and the shared override file has been rewritten
  by another component to point at a different install root (the way
  `qa_loop._setup_clone_override` points it at the running pm_core's parent),
- **when** the meta window is closed or its Claude exits,
- **then** the foreign override survives with its content unchanged, and
  `pm which` in the session still resolves through that foreign override.

### R4 — Relaunch after close works

- **Given** a meta window that was opened and then closed (override cleared),
- **when** the user runs `pm meta` again from a session pane,
- **then** a meta window opens again, the override is active once more, and
  `pm which` resolves to the meta workdir.

### R5 — Re-running `pm meta` with the window open only selects it

- **Given** a meta window already open with the override active,
- **when** the user runs `pm meta` again from a session pane,
- **then** pm switches to the existing `meta` window (one meta window, not
  two), the override file content is unchanged, and no cleanup fires that
  would disturb the running session.

### R6 — Interactive fallback cleans up on interrupt

- **Given** a directory with no active pm tmux session, where `pm meta` falls
  back to launching Claude interactively in the foreground,
- **when** the user interrupts the session (Ctrl-C, or the process receives
  SIGTERM),
- **then** the process exits and the override file is removed, leaving the rest
  of the session dir intact.

### R7 — Cleanup is a no-op when there is nothing to clean

- **Given** a meta pane command whose override file does not exist (or whose
  session dir is missing entirely) at exit time,
- **when** the pane's shell exits (any signal),
- **then** cleanup completes without an error surfacing to the user, and no
  partial session-dir state is created or destroyed.

## Setup

Each scenario runs in its own container and bootstraps a throwaway pm project
per `tui-manual-test.md`:

1. Install pm from the clone into a venv (`pip install -e .`), with
   `PYTHONPATH` pointing at the clone so `pm which` reports it.
2. Create a throwaway git project, `pm init --backend local --no-import`, add
   at least one PR, and start the pm session (`pm session`).
3. Make `pm meta` launchable without real Claude: write a fake-claude config
   for the session (`pm fake-claude config set '{"_all": {}}'` — the `meta`
   session type is a no-verdict interactive fake that stays open like real
   Claude), and ensure a `claude` binary exists on PATH (a shim is enough;
   `find_claude()` gates the launch). The fake-claude stand-in is on PATH via
   the installed package's `bin/`.
4. To seed non-override session state, create the debug marker
   (`touch ~/.pm/sessions/<tag>/debug`) and capture-evidence files under
   `~/.pm/sessions/<tag>/captures/<pr>/` before the meta window's exit path
   runs.

## Pass/Fail criteria

- **Pass** — after the trigger, the override file is present exactly when it
  should be (absent after this meta window's exit unless a foreign owner
  rewrote it; present while the window lives and after relaunch), `pm which`
  reflects that, and all non-override session state (debug, fake-claude
  config, captures) survives every exit path. Errors from cleanup do not
  surface in pane output.
- **Fail** — the override survives a kill-window (the original bug);
  the override or any sibling session state is deleted on normal exit; a
  foreign-owned override is deleted; `pm meta` relaunch fails or leaves two
  meta windows; cleanup errors abort the pane with a visible error.

## Edge cases

- Override content points at a foreign workdir → left intact (content-guard).
- Override file missing at cleanup → no-op, no error.
- Session dir missing entirely at cleanup → no-op.
- Multiple signals in flight (HUP then EXIT) → handler is idempotent; override
  removed once, no error.
- Window-already-exists path must not touch the override at all.
- Meta workdir itself is never deleted by cleanup — only the override file
  (workdir reuse/resume is a feature).

## Ambiguities

- **Trap vs `_pane-closed` teardown** — resolved: trap, per the implementation
  (self-contained in the pane command, covers the interactive fallback).
- **Late-trap vs relaunch race** — if the window is killed and `pm meta` is
  rerun before the dying shell's trap executes, the trap could delete a fresh
  override (same content, same workdir). Accepted risk per the PR note; the
  relaunch scenario asserts the steady state after both settle, not the
  microsecond window.
- **Driving the launch** — `find_claude()` requires a `claude` binary on PATH
  even when the fake-claude config will route to the fake; scenarios allow a
  PATH shim as setup. Not user-visible behavior under test.
