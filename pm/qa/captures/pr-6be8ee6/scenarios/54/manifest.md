---
pr: pr-6be8ee6
workdir: /workspace/pm-test-rec-1778707848
captured_at: 2026-05-13
recipe: pm/qa/artifacts/cli-recording.md
---

## Commands

```
pm qa regression no-such-test
PATH=/tmp/shimbin:$PATH pm qa regression sample-check
PATH=/tmp/shimbin:$PATH pm qa regression sample-check --file-prs
PATH=/tmp/shimbin:$PATH pm qa regression sample-check --file-bugs
# after `tmux kill-session` for all pm- sessions:
pm qa regression sample-check
```

`/tmp/shimbin/claude` is a tiny stub that writes its argv to `$CLAUDE_SHIM_OUT`
then exits 0, so the prompt `pm qa regression` hands to `claude` is captured.

## What this demonstrates

Four triples from scenario 54 (regression test runner — id resolution,
filing flags, removed surface), driven end-to-end:

- Triple 1 — `pm qa regression no-such-test` exits non-zero and prints
  `Unknown regression test: no-such-test` plus `Run 'pm qa list' to see
  available tests.`
- Triple 2 — `pm qa regression sample-check` (no flag) launches Claude; the
  captured prompt contains the test body, `## Session Context`, `## Captures`,
  and `## QA Regression Test: Sample Check` headings, and does NOT contain
  `## Filing Findings`.
- Triple 3 — `--file-prs` and the hidden `--file-bugs` alias both inject a
  `## Filing Findings` addendum; the addenda are byte-identical (diff prints
  nothing and `ADDENDA IDENTICAL` is echoed) and contain both
  `pm pr add '<title>' --plan bugs` and `--plan improvements` instructions.
- Triple 4 — with all pm- tmux sessions killed,
  `pm qa regression sample-check` exits non-zero and prints
  `No pm tmux session found. Start one with 'pm session'.`

## Files

- `recording.cast` — asciinema replay of the driver script run inside a tmux pane.
- `transcript.log` — plain-text decode of the cast (load-bearing artifact).
- `prompt.md` — scenario brief (planner-supplied).
