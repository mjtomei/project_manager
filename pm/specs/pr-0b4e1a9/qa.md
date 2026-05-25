# QA Spec: pr-0b4e1a9 — `pr start` window-switch hijacks an arbitrary attached grouped session

## Background

A single tmux server hosts a pm project's sessions. The first attached
client lands on the **base** session (`pm-<proj>`); each additional client
gets its own **grouped** session (`pm-<proj>~N`) so it can view a different
window independently. The shared resource here is that tmux server / socket
and the set of attached clients — a focus change issued for one client must
not leak onto another client's window.

Window-launching commands (`pm pr start`, the review/merge windows, `pm
container build`, `pm meta`) and the QA-status mirror all switch a tmux
client to a window. Before this fix they resolved *which session to switch*
through `current_or_base_session`, whose fallback grabs the **first attached
grouped session** when the caller's own client can't be identified. For a
read-only query that is harmless; for a focus-mutating `select-window` it
**hijacks whatever that arbitrary session was viewing** — observed live as a
mid-review-loop session being yanked onto a freshly-started PR window.

The fix introduces a focus-safe resolver (`caller_switch_target`) that
returns the caller's own grouped session only, or "none" when the caller's
client can't be identified — in which case the window is created **detached**
and no session's focus moves. The QA-status mirror (`qa_status.py`) carried a
private duplicate of the hazardous fallback and was fixed the same way.

## Requirements (Given / When / Then)

### R1 — CLI-shell `pr start` must not hijack another attached session
**Given** a pm project whose tmux server has two attached clients — session A
on the home window and session B parked on a different, long-running window
(e.g. a review loop) — and a separate plain shell that is **not** inside any
tmux session,
**When** the user runs `pm pr start <new-pr>` from that plain shell,
**Then** session B's active window does not change (it is still on its
long-running window), session A's active window does not change, the new PR
window exists but is detached, and the command's output does not claim to
have switched any terminal.

### R2 — Caller's own client still switches (in-tmux)
**Given** the user is inside their own pm grouped session (session A),
viewing the home window, while session B is parked elsewhere,
**When** the user runs `pm pr start <new-pr>` from a pane in session A,
**Then** session A's active window becomes the new PR window, and session B's
active window is unchanged.

### R3 — Switching to an already-existing window is focus-safe and honest
**Given** a PR window already exists, with session B parked on another window
and a plain non-tmux shell available,
**When** the user runs `pm pr start <that-pr>` again from the non-tmux shell,
**Then** no session's active window changes (B is untouched) and the output
reports the window is open but there was no terminal to switch (it does not
falsely report "Switched").
**Given** the same existing window,
**When** the user runs `pm pr start <that-pr>` from a pane in their own
session A,
**Then** session A switches to that window and the output reports it switched.

### R4 — Caller in a *different* project's tmux session does not hijack
**Given** the user is attached to a *different* project's tmux session, and
the target project has an attached grouped session B parked on a busy window,
**When** the user runs `pm pr start <new-pr>` for the target project from
inside the unrelated session,
**Then** the target project's session B is not pulled onto the new window
(the caller is not in the target base's group, so no switch is issued).

### R5 — QA-status mirror "go to window" is focus-safe
**Given** a container-mode QA loop is running and its status mirror is
displayed in a pane, listing the scenario windows, with another attached
client parked on a different window,
**When** the user highlights a scenario and presses Enter ("go to window"),
**Then** the mirror's own client switches to that scenario's window and the
other attached client's active window is unchanged.

## Setup

- Build a throwaway pm project per `tui-manual-test.md` (venv, `PYTHONPATH`
  override to the editable clone, `pm init`, add PRs).
- Establish two attached clients on the pm tmux server so a base session and
  at least one grouped session (`~N`) exist. Achieve "attached" by running
  `tmux attach -t <session>` inside tmux panes (panes have ptys), as in the
  `tmux-screen-recording.md` recipe. Park session B on a non-home window
  (start a second PR window, or use the review/merge window) and leave it
  there.
- Keep a plain (non-tmux) shell available in the container for the
  "unidentifiable caller" cases (just don't run from inside the tmux server's
  client).
- Use `fake-claude` (`pm fake-claude config set`) to drive any loop session
  deterministically so a window stays "busy" without a real model.
- Observe each client's current window with
  `tmux display-message -p -t <session> '#{window_name}'` /
  `tmux list-windows`, and capture renders with the recording recipes.

## Edge Cases

- **Caller's own session is detached** (a background process inside tmux):
  `caller_switch_target` still returns the caller's session; issuing
  `select-window` on a clientless session is harmless and changes nobody
  else's focus.
- **Re-running `pr start` in background mode** on an existing window: prints
  the background no-op message and never switches (independent of this fix,
  but should still not hijack).
- **No other attached grouped session exists** when running from a CLI shell:
  the window is simply created detached; nothing to hijack, no error.
- **`select_window` return value**: when it intentionally skips (no
  identifiable caller) it returns false; callers print the "open, no terminal
  to switch" message rather than treating it as an error.
- **Park-on-kill**: killing the user's focused window and parking on the home
  window only moves the caller's own client, never another attached client.

## Pass/Fail Criteria

**Pass**: In every multi-client scenario, the un-involved attached client's
active window is identical before and after the action. The caller's own
client switches only when it is identifiable (in-tmux, in the base's group).
CLI-shell invocations create/leave windows detached and print honest "no
terminal to switch" messaging; in-tmux invocations switch the caller and
print "Switched". The repro from R1 fails on master-base and passes on this
branch.

**Fail**: Any attached client other than the caller has its active window
changed by the action (the hijack). A CLI-shell invocation reports it
"Switched" a terminal when none was switched. The caller's own client fails
to switch when it is identifiable.

## Ambiguities

- *How to make a client "attached" in a headless container.* Resolved: use
  `tmux attach` inside tmux panes (the `tmux-screen-recording.md` recipe
  pattern) to create real attached clients and thereby real grouped
  sessions.
- *Driving the QA-status mirror (R5) as a user.* Resolved: reach it through a
  container-mode QA loop (the mirror is launched by the loop), then drive
  Enter via `tmux send-keys`. This is heavier setup; if a full container-mode
  loop is impractical in the scenario, drive the mirror against a prepared
  status file in a pm session and assert the same focus-safety invariant
  (caller switches, other client untouched). The user-visible invariant is
  identical either way.
- *Known unrelated failure*: `tests/test_hook_events.py::
  test_installer_writes_standalone_receiver` fails on this branch **and** on
  master-base (hook-receiver install, not this PR) — not a regression.

No **[UNRESOLVED]** ambiguities.
