---
title: Scenario 28 — pm qa regression unified filing addendum
description: CLI recording verifying pm qa regression resolves a test, launches the unified prompt, and that --file-prs / --file-bugs append identical filing addenda covering bugs + improvements.
---

## Workdir

`/workspace` (PR branch `pm/pr-6be8ee6-bug-fix-flow-surface-tui-qa-repro-instructions-in-`).
Recording was driven from a throwaway test project (`/tmp/pm-test-rec2-…`) and a venv at `/tmp/pm-venv` with editable install of `/workspace` and `PYTHONPATH=/workspace`.

`pm_core.claude_launcher.launch_claude` was shimmed via a `claude` stub on `PATH` that writes the final argv (the prompt) under `$PROMPTS_DIR` and exits 0, so the regression runner's prompt assembly is observed without invoking real Claude.

## Command(s) recorded

`/tmp/run_scenario2.sh` — non-interactive scripted run of scenario steps 4–11 with `set -x`.
The pm tmux session and test project (step 3) were created outside the recording because `pm session` attaches to a TTY when one is present (asciinema provides one), which would have hijacked the cast.

## What this demonstrates

| Step | Result |
| --- | --- |
| 4. `pm tui test` removed | `Error: No such command 'test'`, exit=2; `pm tui --help` shows no `test` subcommand |
| 5. `pm qa add-regression smoke-check` scaffolds + `pm qa list` shows it under Regression Tests |
| 7. Happy path — prompt has `## Session Context`, `## Captures` (template `pm/qa/captures/regression/<test-id>/<timestamp>/`), `## QA Regression Test: Smoke Check` with body, and **no** `## Filing Findings` |
| 8. `--file-prs` adds `## Filing Findings` (count=1) containing `--plan bugs` (count=2), `--plan improvements` (count=2), and the line "Filing is independent of your verdict for the test." |
| 9. `--file-bugs` is hidden from `--help` and produces a byte-identical prompt to `--file-prs` (`diff … && echo IDENTICAL`) |
| 10. Unknown id → exit=1, stderr "Unknown regression test: does-not-exist", stdout "Run 'pm qa list' to see available tests.", no file in `$PROMPTS_DIR` |
| 11. No pm tmux session → exit=1, stderr "No pm tmux session found. Start one with 'pm session'.", stub never invoked |

All steps PASS; no fixes required.

## Files

- `recording.cast` — asciinema cast of the full scenario script (`asciinema play recording.cast`).
- `transcript.log` — plain-text decode of the cast for grep/diff. **Load-bearing.**
- `prompt-file-prs.txt` — captured prompt produced by `pm qa regression smoke-check --file-prs` (saved during initial Bash-tool run before recording).
- `prompt-file-bugs.txt` — captured prompt produced by `pm qa regression smoke-check --file-bugs`; byte-identical to `prompt-file-prs.txt`.
- `manifest.md` — this file.

## Notes

The recorded run uses a different ephemeral test project than the prompt-*.txt files (those came from the pre-recording validation pass); both invocations exercised the same code path. The transcript shows in-recording counts (Filing Findings=1, --plan bugs=2, --plan improvements=2) and the IDENTICAL marker for the in-recording `--file-prs` vs `--file-bugs` diff.
