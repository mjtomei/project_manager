---
title: pm qa regression — unified filing addendum
description: Capture of scenario 62 driving pm qa regression in all four triples
---

## What this demonstrates

Scenario 62: `pm qa regression <id>` (the replacement for the removed
`pm tui test`) builds a unified prompt; `--file-prs` and the hidden
`--file-bugs` alias both produce the same bugs+improvements filing
addendum; the old `pm tui test` is gone from the CLI.

## Workdir

- Throwaway pm project: `/scratch/qa-rec-test2/` (init'd with
  `git init`, `pm init --backend local --no-import`, two PRs added,
  `pm session` started, `pm qa add-regression smoke` then body
  replaced with `Just echo "hello" and stop.`).
- PR clone under test: `/workspace`.

## Recorded command

```
asciinema rec --overwrite recording.cast -c "bash /tmp/run2.sh"
```

`run2.sh` drives all four triples sequentially. The first triple
invokes `pm qa regression smoke` three ways under `timeout 3` — claude
launches but is killed before doing anything; only the logged prompt
argument matters, which `launch_claude` writes via
`log_shell_command(cmd, prefix="claude")` before `subprocess.run`.

## What you should see in the cast / transcript

- Triple 1: three `INFO [claude] /home/.../claude --session-id … '## Session Context …'`
  log lines are extracted. Invocation #1 has **no** "Filing Findings"
  addendum; #2 (`--file-prs`) and #3 (`--file-bugs`) **do**. The
  addendum contains both `pm pr add … --plan bugs …` and
  `pm pr add … --plan improvements …`. `--file-bugs` produces no
  deprecation warning; pm prints the same "Running regression: Smoke"
  banner as `--file-prs` and exits via the same code path. The
  rendered diff in the transcript shows only a timestamp difference
  on the trailing WARN line (claude was killed at slightly different
  times) and trailing wrapper-log noise for the next invocation —
  the **prompt argument** itself is identical between #2 and #3
  (a cleaner extraction outside this recording confirmed
  byte-identical prompts modulo session-id; see Notes).
- Triple 2: `pm qa regression does-not-exist` → `exit=1`, prints
  `Unknown regression test: does-not-exist` (stderr) and
  `Run 'pm qa list' to see available tests.` (stdout). No traceback.
- Triple 3: tmux server killed, then `pm qa regression smoke` →
  `exit=1`, prints `No pm tmux session found. Start one with 'pm session'.`
  on stderr. No traceback.
- Triple 4: `pm tui test`, `pm tui test --list`, `pm tui test --file-bugs`,
  `pm tui test --fix-bugs` each → `exit=2` with Click usage error
  `No such command 'test'.` for the `pm tui` group. No traceback,
  no regression run.

## Notes

- The diff portion of the transcript in Triple 1 is noisier than
  ideal because the simple "split on next `[claude] /home` line"
  bound used in the recording also captured trailing wrapper / next
  `launch_claude` log lines between invocations. Reading the prompt
  content within the `[claude] /home...` regions of `~/.pm/debug/qa-rec-test2-cfb5925b.log`
  confirms the prompts are byte-identical modulo `--session-id`. The
  earlier dogfood (`pm-test-1778717648`, log
  `~/.pm/debug/pm-test-1778717648-ae54dfb3.log`, lines 88 and 135)
  shows the same result with the cleaner extraction (`diff` reports
  no differences).

## Files

- `recording.cast` — asciinema replay of the full run (`asciinema play recording.cast`).
- `transcript.log` — plain-text capture of the same run.
- `manifest.md` — this file.
