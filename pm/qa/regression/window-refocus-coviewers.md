---
title: Window refocus targets the originating client only
description: Verify that refocus switches only the tmux client that ran the command, except for loop kill-and-recreate flows which switch sessions watching the old loop window.
---
You are testing the unified window-refocus behaviour from pr-1735d44.

## Rule

Refocus must switch only:
  (a) the attached tmux client that ran the command, OR
  (b) sessions that were already viewing a window owned by a loop
      that is being killed and recreated (review / watcher / qa).

Sessions that happen to be on the same window for unrelated reasons
must NOT be dragged along. A TUI respawn must not move any client.

## Background

The TUI is one Python process. With multiple grouped sessions
attached (base, base~1, ...), every keystroke arrives in the same
TUI process regardless of which client typed it. Identifying the
"originating client" requires asking tmux for the most-recently-
active client (`#{client_activity}`) at command-launch time and
passing that session through to subprocesses via
`PM_ORIGIN_SESSION`.

For loop windows that get killed and recreated (review/watcher/qa),
the flow snapshots the sessions watching the old window before
killing it, then switches them to the new window. They get moved
because the window they were watching no longer exists.

## Available tools
- `pm tui view` / `pm tui send <keys>` — drive the TUI.
- Attach a second client: `tmux attach -t <base>~1` from a separate
  terminal.
- `tmux display-message -t <session> -p '#{window_name}'` — inspect
  the active window for a given session.

## Scenarios

### S1: only the originating client switches

1. Two attached sessions in the group (base + base~1). Both on the
   TUI window.
2. From base, press `s` on a PR that already has a window —
   "switch to existing window" fast path runs.
3. Verify base switched to the PR window; verify base~1 stayed on
   the TUI window.

PASS: only base moved. FAIL: base~1 was dragged along.

### S2: typing client identification works across both attached clients

1. Two attached sessions. Press `s` from base~1 (different
   client). The TUI receives the same key but the originator should
   be base~1.
2. Verify base~1 switched to the PR window; base stayed on TUI.

PASS: base~1 moved, base did not. FAIL: base moved instead, or
both moved.

### S3: sessions on different windows are unaffected

1. Two attached sessions; manually move base~1 to a different
   window.
2. From base, press `s` on a PR.
3. Verify base switched, base~1 stayed where it was.

### S4: async command refocuses the originating client

Covers PR notes 1 & 3.

1. Two sessions on the TUI window. From base, press `s` on a PR
   that does NOT yet have a window — async `pr start`.
2. Immediately move base manually to a different window.
3. Wait for the new PR window to appear.

PASS: the new PR window opens in base (the originating client),
even though base has moved. base~1 is unaffected. FAIL: focus
follows whichever client is currently active, or moves base~1.

### S5: review --fresh kill+recreate moves prior watchers

1. Two sessions, both viewing a PR's review window.
2. From the TUI, trigger `d` with --fresh on that PR — kills and
   recreates the review window.
3. Verify both sessions land on the new review window.

PASS: both follow. FAIL: only one moves.

### S6: TUI respawn does not move any client

1. Two attached sessions, both on different windows (neither on
   the TUI).
2. Trigger a TUI respawn (e.g. by killing the TUI pane such that
   `_respawn_tui` runs and creates a fresh TUI window).
3. Verify NEITHER session was switched to the new TUI window. The
   TUI exists in the background; the user reaches it manually.

PASS: both sessions stayed where they were. FAIL: one or both
were yanked to the new TUI window.

## Reporting
For each scenario, report PASS/FAIL with a short note on each
session's active window before/after.
