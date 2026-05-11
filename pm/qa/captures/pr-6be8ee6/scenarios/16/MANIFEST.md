---
title: Scenario 16 — TUI QA pane three sections + picker + regression Enter
description: Captures verifying the q-key QA pane renders Instructions/Regression Tests/Artifact Recipes with a unified counter, the `a` key opens QACreatePickerScreen, and Enter on a regression item launches a Claude pane via build_regression_test_prompt.
---

## Summary

End-to-end exercise of the QA pane in a throwaway pm project. All assertions
in scenario 16 hold: three labeled sections render with `<Label> (N)` headers,
the status bar reads `QA  N item(s)   Enter=run  e=edit  d=debug  a=add  q=back`,
`a` opens the modal picker (not `pm qa add-instruction`), and Enter on a
regression item spawns a Claude pane whose prompt contains the distinctive
strings produced by `build_regression_test_prompt`.

## Files

- `01-home.txt` — TUI home (4 PR cards). Status bar does not surface QA counter
  here; the counter is shown in the QA pane itself.
- `02-qa-pane.txt` — QA pane with all three section headers and the unified
  status-bar counter (`QA  1 item(s)`) after copying in one regression file.
- `03-create-picker.txt` — QACreatePickerScreen modal: Name input
  (`e.g. login-flow-setup`), six Kind options (instructions/regression/
  artifacts × author/add), footer `↑↓ change kind · Enter create · Esc cancel`.
- `04-regression-launch.txt` — claude command line + pane capture from the
  spawned regression pane. Contains all distinctive strings:
  `## Session Context`, `You are testing against tmux session: <SESS>`,
  `## Captures`, `pm/qa/captures/regression/`, `## QA Regression Test:`,
  `## Filing Findings`.
- `tmux-transcript.txt` — final tmux pane content for the pm session.
- `session.cast` — asciinema capture (non-interactive recording of the final
  pane contents; full interactive asciinema-over-tmux-attach was not feasible
  in this non-tty environment, so the cast is short).

## Verdict

PASS — all assertions met.
