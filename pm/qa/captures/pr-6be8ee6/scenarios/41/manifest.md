---
title: Scenario 41 capture — TUI QA pane sections, picker modal, regression Enter
description: Transcripts from driving the TUI QA pane through three-section render, the create-picker modal, and the regression-item Enter routing
---

## Workdir

`/tmp/pm-test-1778679488` (throwaway pm project)

## Setup

- `pm init --backend local --no-import` + `pm pr add "Smoke PR"`
- Seeded one real + one empty-frontmatter file per category
  (`pm/qa/{instructions,regression,artifacts}/{i1,r1,a1}.md` and
  `empty.md`).
- Started canonical session with `pm session` (attach error
  ignored — no TTY).

## What the transcripts demonstrate

- `transcript-qa-view.log` — QA pane after pressing `q`. Confirms
  status bar `QA    6 item(s)    Enter=run  e=edit  d=debug  a=add  q=back`
  and three headers `Instructions (2)`, `Regression Tests (2)`,
  `Artifact Recipes (2)`. Counts include the empty-frontmatter
  fixtures, confirming the loader tolerates them.
- `transcript-picker-modal.log` — `QACreatePickerScreen` opened from
  the QA pane. Shows `Create QA file` title, `Name` input
  (placeholder `e.g. login-flow-setup`), and exactly three `Kind`
  options: `Instruction`, `Regression test`, `Artifact recipe`. The
  planner draft mentioned "6 options × 2 modes"; the picker only
  exposes the `author` mode, which is intentional per
  `pm_core/tui/screens.py:457-465`.
- `transcript-picker-post-input.log` — same modal with `test-name`
  typed and selection moved to `Regression test`, showing the input
  binding to the `Name` field and arrow-key navigation working.
- `transcript-regression-pane.log` — the pane spawned by pressing
  Enter on `r1` under `Regression Tests`. The launched command was
  `claude '## Session Context ...'` (truncated by the terminal),
  but the registered cmd in
  `~/.pm/pane-registry/<session>.json` confirms role `qa-item` and
  a prompt produced by `build_regression_test_prompt` containing
  the literal `pm/qa/captures/regression/<test-id>/<timestamp>/`.

## Non-default files

- empty-name Enter on the picker keeps the modal open and spawns
  no pane (verified by `tmux list-panes` count).
- Esc on the picker closes it cleanly.
- Submitting `picker-art` with `Artifact recipe` launched
  `pm qa author-artifact picker-art` in role `qa-author`
  (registry-confirmed).
- Submitting `picker-ins` with default `Instruction` launched
  `pm qa author-instruction picker-ins` in role `qa-author`.

## Notes

- The CLI surface in this checkout does not support `--no-launch`
  on `pm qa add-*`; the scenario's fallback (run with `EDITOR=true`
  so the scaffold writes without blocking) was used. Worth filing
  as an incidental gap if the spec really requires `--no-launch`.
- `pane_ops.launch_pane` registers panes with a `role` in the
  pane-registry; it does not create a new tmux window. The
  scenario draft's "in a qa-author window" wording is loose — the
  pane shares the TUI's window, the role is what's load-bearing.
  Verified via `/home/pm/.pm/pane-registry/<session>.json`.

## Files

- `transcript-qa-view.log` — QA pane three-section render.
- `transcript-picker-modal.log` — picker just after `a`.
- `transcript-picker-post-input.log` — picker with name+selection.
- `transcript-regression-pane.log` — launched regression pane.
- `prompt.md` — scenario prompt as received.
