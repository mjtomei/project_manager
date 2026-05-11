---
pr: pr-6be8ee6
workdir: /workspace
captured_at: 2026-05-11
recipe: pm/qa/artifacts/cli-recording.md
---

## Commands

```
pm which
pm qa list                          # in /workspace (library) and in empty $TEST_DIR
pm qa show tui-manual-test
pm qa show tmux-screen-recording --category artifacts
pm qa show does-not-exist
EDITOR=true pm qa add-instruction foo / add-regression bar / add-artifact baz
EDITOR=true pm qa add-* <existing>          # already-exists error path
pm qa author-instruction|regression|artifact <existing>  # refusal-before-launch
pm qa docs | head -1; pm qa docs | wc -l
pm qa regression does-not-exist
pm qa regression help-keybindings --file-prs   # captured against a real pm session
pm qa regression help-keybindings --file-bugs
pm tui --help; pm tui test
```

## What this demonstrates

End-to-end coverage of scenario 15: the three-section `pm qa list`
ordering and per-section counts (including the `(0): (none)` rendering
on an empty project), `pm qa show` auto-detect ordering for
instructions vs explicit `--category artifacts`, scaffold templates
for `add-instruction|add-regression|add-artifact` (including the
`Already exists` exit-1 path), refusal-before-launch by the `author-*`
trio when the target file already exists, the packaged
`pm qa docs` output, and the `pm qa regression` filing-addendum
content for both `--file-prs` and the hidden `--file-bugs` alias.
Also confirms removal of `pm tui test` and absence of `test` in
`pm tui --help`.

The `--file-prs` / `--file-bugs` runs used a fake `claude` shim on
PATH (`/tmp/fakebin/claude`) that captures the prompt instead of
launching a real Claude session — this lets us verify the prompt
body contains the `## Filing Findings` addendum and both
`--plan bugs` / `--plan improvements` lines without burning credits.
The captured prompts are saved alongside the cast.

## Files

- `recording.cast` — asciinema replay of `/tmp/qa15_script.sh`
- `transcript.log` — plain-text capture of the same run (re-execution of the script)
- `regression-file-prs.txt` — stdout from `pm qa regression help-keybindings --file-prs`
- `regression-file-prs-prompt.txt` — full prompt the fake claude received (contains `## Filing Findings` + `--plan bugs` + `--plan improvements`)
- `regression-file-bugs.txt` — stdout from `pm qa regression help-keybindings --file-bugs`
- `regression-file-bugs-prompt.txt` — full prompt for the hidden `--file-bugs` alias
- `transcript.md` — per-step verdict summary for the scenario
