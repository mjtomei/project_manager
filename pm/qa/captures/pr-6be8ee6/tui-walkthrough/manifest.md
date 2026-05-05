---
pr: pr-6be8ee6
workdir: /workspace
test_project: /workspace/pm-test-1777985423
tmux_session: pm-pm-test-1777985423-f08371ae
captured_at: 2026-05-05
recipe: pm/qa/artifacts/tmux-screen-recording.md
---

## Commands

Setup (per `pm/qa/instructions/tui-manual-test.md`):

```
python3 -m venv /tmp/pm-venv && source /tmp/pm-venv/bin/activate
pip install -e /workspace
export PYTHONPATH=/workspace
pm which   # /workspace/pm_core (confirms editable install is in use)

TEST_DIR=/workspace/pm-test-$(date +%s)
mkdir -p "$TEST_DIR" && cd "$TEST_DIR" && git init
pm init --backend local --no-import
pm pr add "Add login feature"                                  # -> pr-95325c4
pm pr add "Fix database migration" --depends-on pr-95325c4     # -> pr-6cd925d
pm pr add "Refactor auth module" --depends-on pr-95325c4,pr-6cd925d
pm pr add "Add unit tests"
pm session 2>/dev/null || true   # creates the tmux session, attach fails (no TTY)
```

Capture (per `pm/qa/artifacts/tmux-screen-recording.md`):

```
SESSION=pm-pm-test-1777985423-f08371ae
CAPDIR=pm/qa/captures/pr-6be8ee6/tui-walkthrough
mkdir -p "$CAPDIR/screens"

# transcript of the TUI pane
tmux pipe-pane -t "$SESSION":0.0 -o "cat >> $CAPDIR/transcript.log"

# drive the TUI and snapshot at decision points
pm tui view   -s "$SESSION" > "$CAPDIR/screens/00-startup.txt"
pm tui send j -s "$SESSION"; pm tui view -s "$SESSION" > "$CAPDIR/screens/01-after-j.txt"
pm tui send '?'      -s "$SESSION"; pm tui view -s "$SESSION" > "$CAPDIR/screens/02-help-overlay.txt"
pm tui send escape   -s "$SESSION"; pm tui view -s "$SESSION" > "$CAPDIR/screens/03-after-escape.txt"
pm tui send '/'      -s "$SESSION"; pm tui view -s "$SESSION" > "$CAPDIR/screens/04-command-mode.txt"
pm tui send escape   -s "$SESSION"
pm tui send j -s "$SESSION"; pm tui send j -s "$SESSION"
pm tui view  -s "$SESSION" > "$CAPDIR/screens/05-third-pr-selected.txt"

# split a shell pane and run a few CLI commands inside the test session
tmux split-window -t "$SESSION":0 -h
tmux pipe-pane -t "$SESSION":0.1 -o "cat >> $CAPDIR/cmd-pane.log"
tmux send-keys -t "$SESSION":0.1 "pm pr list" Enter
tmux send-keys -t "$SESSION":0.1 "pm pr note list pr-95325c4" Enter
tmux send-keys -t "$SESSION":0.1 "pm plan list" Enter
tmux capture-pane -t "$SESSION":0.1 -p -S - > "$CAPDIR/screens/06-cli-commands.txt"

tmux pipe-pane -t "$SESSION":0.0   # stop piping
tmux pipe-pane -t "$SESSION":0.1
```

## What this demonstrates

End-to-end exercise of both new instruction files in this PR:

1. **`pm/qa/instructions/tui-manual-test.md`** drives the test
   environment: a fresh venv with `pip install -e /workspace`,
   `PYTHONPATH=/workspace` to shadow the container's `/opt/pm-src`,
   a throwaway pm project with four PRs in a dependency chain, and
   `pm session` to spin up the tmux-hosted TUI.

2. **`pm/qa/artifacts/tmux-screen-recording.md`** captures the
   demonstration. `asciinema` is not installed in this environment,
   so the recipe's documented fallback (transcript-only via
   `tmux pipe-pane`) is what was used. Screens directory holds
   point-in-time `pm tui view` snapshots of the TUI pane plus a
   scrollback of the CLI pane.

The captured artifacts:

- `transcript.log` (351 lines) — raw byte stream from the TUI pane,
  shows the Textual app's redraw escape sequences as the user navigated.
- `cmd-pane.log` (65 lines) — raw byte stream from the split shell pane.
- `screens/00-startup.txt` — initial TUI: 4 PRs, dependency arrows,
  `pr-d17fe55` selected by default (Add unit tests).
- `screens/01-after-j.txt` — after pressing `j`: selection moved to
  `pr-95325c4`; selected box renders with double-line borders.
- `screens/02-help-overlay.txt` / `03-after-escape.txt` — `?` did not
  trigger a help overlay in this build; documented as observed.
- `screens/04-command-mode.txt` — `/` enters command-input mode (cursor
  appears in the prompt at the bottom).
- `screens/05-third-pr-selected.txt` — selection moved further down
  the dependency chain.
- `screens/06-cli-commands.txt` — output of `pm pr list`,
  `pm pr note list pr-95325c4` (showing the demo note added during
  the walkthrough), and `pm plan list` (empty).

## Pre-fix vs post-fix

This capture is from the **post-fix** code (this PR's branch:
`pm/pr-6be8ee6-bug-fix-flow-surface-tui-qa-repro-instructions-in-`).
The PR doesn't fix a regression — it adds prompt and QA-library
plumbing — so there is no pre-fix counterpart. The capture exists to
demonstrate the new artifact-recipe workflow end-to-end.

## Caveats / observed quirks

- `?` did not appear to open a help overlay in pane snapshots (could
  be a timing issue between `tui send` and `tui view`, or the
  keybinding may differ in this branch). Worth a follow-up check.
- `pm pr show <id>` is not a command in this build; `pm pr list` and
  `pm pr note list <id>` were used instead.
- The TUI pane is 24 rows; only 2–3 PR boxes fit on screen at once,
  so navigation scrolls rather than reveals.
