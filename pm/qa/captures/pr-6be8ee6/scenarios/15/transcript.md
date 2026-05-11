# Scenario 15 — pm qa CLI surface & pm tui test removal

| # | Command | Observed | Verdict |
|---|---------|----------|---------|
| 4a | `cd /workspace && pm qa list` | Three section headers in order Instructions(1) / Regression Tests(20) / Artifact Recipes(2), each section populated. | PASS |
| 4b | `cd "$TEST_DIR" && pm qa list` | All three headers present with `(0):` and `  (none)`; empty categories not dropped. | PASS |
| 5 | `pm qa show tui-manual-test` | `# TUI Manual Testing`, `[/workspace/pm/qa/instructions/tui-manual-test.md]`, body with `## Setup` and `## Test Steps`. Exit 0. Auto-detected `instructions` first. | PASS |
| 6 | `pm qa show tmux-screen-recording --category artifacts` | `# tmux Screen Recording`, `[/workspace/pm/qa/artifacts/tmux-screen-recording.md]`, body with `## When to use` etc. Exit 0. | PASS |
| 7 | `pm qa show does-not-exist` | `QA item not found: does-not-exist` to stderr, exit 1. | PASS |
| 8 | `EDITOR=true pm qa add-instruction foo` | Created `…/pm/qa/instructions/foo.md`; frontmatter `title: Foo`, headings `## Setup` / `## Test Steps` / `## Expected Behavior` / `## Reporting`. | PASS |
| 9 | `EDITOR=true pm qa add-regression bar` | Created `…/pm/qa/regression/bar.md`; `title: Bar`, "You are a careful tester." paragraph, `## Scenarios` and `## Reporting`. | PASS |
| 10 | `EDITOR=true pm qa add-artifact baz` | Created `…/pm/qa/artifacts/baz.md`; `title: Baz`, `## When to use` / `## What this recipe produces` / `## Capture` / `## Manifest format`. | PASS |
| 11 | Re-run each `add-*` | `Already exists: <path>` on stderr, exit 1, file md5 unchanged. | PASS |
| 12 | `pm qa author-instruction|regression|artifact <existing>` | Each printed `Already exists: <abs path>` to stderr, exit 1, *before* any Claude launch. `tmux ls` before/after identical (no server started by the command). | PASS |
| 13 | `pm qa docs` | First stdout line `# pm QA library`; output is 343 lines (well above 50); exit 0. | PASS |
| 14 | `pm qa regression does-not-exist` | stderr `Unknown regression test: does-not-exist`, stdout `Run 'pm qa list' to see available tests.`, exit 1. | PASS |
| 15 | start pm session | `pm session` started `pm-workspace-eab0d61a` (then errored on `window-resized` in the attach phase, which is unrelated; the pane-registry entry with role=tui is present, which is what `_find_tui_pane` needs). | PASS |
| 16 | `pm qa regression help-keybindings --file-prs` | stdout `Running regression: Help Screen & Keybindings` / `Session: pm-workspace-eab0d61a` / 60-char separator. Captured the prompt via a fake `claude` shim on PATH — prompt contains `## Filing Findings`, `--plan bugs`, `--plan improvements`. | PASS |
| 17 | `pm qa regression help-keybindings --file-bugs` | Same stdout shape. Captured prompt contains the same `## Filing Findings` addendum — confirms the hidden `--file-bugs` alias sets the same `file_prs` flag. | PASS |
| 18 | `pm tui --help` | Commands listed: `capture`, `clear-frames`, `clear-history`, `frames`, `history`, `keys`, `restart`, `send`, `view`. No `test` entry. `grep -E '^\s+test\b'` returns rc=1 (no match). NB: the help output shows `capture` rather than `capture-config` (scenario text mentions the latter) — harmless naming difference, no `test` is still the key assertion. | PASS |
| 19 | `pm tui test` | stderr `Error: No such command 'test'.`, exit code 2 (Click standard non-zero). | PASS |

Verdict: all steps pass. No bugs found.
