---
title: Scenario 48 — pm qa regression id resolution, filing addendum, removed pm tui test
description: CLI recording demonstrating all five Given/When/Then triples for pm qa regression
---

## Workdir

- Project under test: `/workspace/pm-test-1778698936` (throwaway pm-init'd repo).
- pm install: editable from `/workspace` into `/tmp/pm-venv` with `PYTHONPATH=/workspace`.
- pm tmux session: `pm-pm-test-1778698936-9cc76270` (registry has a `tui` pane `%0`).
- Stub `claude` on PATH at `/tmp/stubs/claude` (writes argv + stdin to `$CLAUDE_STUB_CAPTURE`). Real `claude` is invoked via `shutil.which("claude")` inside `pm_core.claude_launcher.launch_claude`, so a PATH stub is the legitimate boundary for observing what pm hands to claude.

## Commands recorded

The script `/tmp/qa-script.sh` runs the five triples back to back. The asciinema cast was produced via the no-TTY workaround from `cli-recording.md` (asciinema run inside a `tmux -L scaffold48` pane).

1. `pm qa regression nonexistent-id`
2. `pm qa regression echo-smoke`
3. `pm qa regression echo-smoke --file-prs`
4. `pm qa regression echo-smoke --file-bugs`
5. `pm tui test --list`

Between triples the script clears `/tmp/claude-capture.txt` and then `grep`s the new capture for filing-addendum strings.

## What the recording demonstrates

- **Triple 1**: pm exits 1 and prints `Unknown regression test: nonexistent-id` (stderr) followed by `Run 'pm qa list' to see available tests.`. Id resolution happens before the tmux-session check (no "No pm tmux session found" path is hit).
- **Triple 2**: `Running regression: Echo Smoke` + session label, exit 0. The capture contains the regression body (`Run \`echo hello\` ...`) and *no* `--plan bugs`/`--plan improvements` strings — confirmed by the `(no filing addendum)` line.
- **Triple 3**: `--file-prs` makes the capture include filing-findings text mentioning both `pm pr add ... --plan bugs ...` and `pm pr add ... --plan improvements ...`.
- **Triple 4**: `--file-bugs` (hidden legacy alias) produces the same filing-findings text as `--file-prs` — confirming the alias maps onto the same `file_prs=True` flag.
- **Triple 5**: `pm tui test --list` exits 2 with click's `Error: No such command 'test'.` — the `pm tui test` subcommand has been removed.

## Files

- `recording.cast` — asciinema replay of the full script (5 triples). Run with `asciinema play recording.cast`. Recorded inside a tmux scaffold pane because the agent shell has no TTY.
- `transcript.log` — plain-text dump of the same script (`bash /tmp/qa-script.sh`). Load-bearing artifact for grep/diff; mirrors the cast.
- `manifest.md` — this file.

## Caveats

- Both lines of the Triple 1 error message are printed, but the first lands on stderr and the second on stdout (the THEN reads "on stderr followed by ..."). The transcript merges both streams so this is not visible in the cast/log alone; verified separately with `2>/tmp/err 1>/tmp/out` redirection. Not blocking — both lines are emitted and exit code is 1 as required.
- `pm session` emits a benign `invalid option: window-resized` tmux compatibility warning during startup; the session is still created and the TUI pane lands in the registry, so the regression command resolves the session correctly.
