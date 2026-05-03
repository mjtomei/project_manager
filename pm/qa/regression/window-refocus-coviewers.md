---
title: Window refocus across co-viewing sessions
description: Verify that any refocus action switches all sessions co-viewing the same window, and that async TUI commands refocus the originating session even if the user has moved.
---
You are testing the unified window-refocus behaviour introduced in pr-1735d44.

## Background

Previously the TUI used `tmux.select_window` for most refocus paths, which
only switched the caller's terminal — leaving any grouped/attached session
that was watching the same window behind. A separate
`tmux.switch_sessions_to_window` was used for review/watcher/qa flows but
not for ordinary refocuses. They are now consolidated into
`tmux.focus_window`, which:

  1. Detects every session in the group currently viewing the same window
     as the *originating* session.
  2. Switches all of those sessions to the target window together.
  3. Uses an explicit originating-session arg (or `$PM_ORIGIN_SESSION`
     env var set by the TUI at command-launch time) so async commands
     refocus the user who initiated them, not whoever the TUI happens to
     be focused on later.

## Available Tools

- `pm tui view` / `pm tui send <keys>` — drive the TUI.
- `tmux attach -t <session>~N` — attach a second client to a grouped
  session for co-viewing tests (use a second terminal pane).
- `tmux display-message -t <session> -p '#{window_name}'` — inspect
  the active window for a given session.

## Scenarios

### S1: co-viewing sessions follow the switch

1. Have two attached sessions in the same pm group (base + base~1).
   Both should currently be on the same window (e.g. the TUI window).
2. From the TUI, press `s` on a PR that already has a window — the
   "switch to existing window" fast path runs.
3. Verify both sessions are now on the PR's window via `tmux
   display-message`.

PASS criteria: both sessions show the new window name. FAIL: the second
session is still on the TUI window.

### S2: sessions on different windows are unaffected

1. Two attached sessions in the group; manually move base~1 to a
   different window (e.g. via tmux key bindings).
2. From base, press `s` on a PR whose window exists.
3. Verify base switched to the PR window. Verify base~1 stayed where
   it was.

PASS: only base moved. FAIL: base~1 was dragged along.

### S3: async command refocuses originating session

This covers the bug from PR note 3 (2026-05-03).

1. Two attached sessions: base (on TUI window) and base~1 (on TUI
   window).
2. From base, press `s` on a PR that does NOT yet have a window —
   triggers the async `pr start` flow.
3. Immediately switch base manually to a different window (e.g.
   another PR) so it is no longer on the TUI window.
4. Wait for the async command to complete and the new PR window to
   appear.

PASS: base stays where the user moved it; base~1 switches to the new
PR window (it was on the TUI window when the command was launched).

FAIL (pre-fix behaviour): the new PR window is opened in base (which
the user has moved away from), or focus follows whichever session
happens to be active at refocus time rather than the originating one.

### S4: review --fresh kill+recreate preserves co-viewers

1. Two sessions, both viewing a PR's review window.
2. From the TUI, trigger `d` (review, --fresh equivalent) on that PR
   to kill and recreate the review window.
3. Verify both sessions land on the new review window after creation.

PASS: both follow. FAIL: only one moves.

## Reporting

For each scenario, report PASS/FAIL with a short note on what each
session's active window was before/after.
