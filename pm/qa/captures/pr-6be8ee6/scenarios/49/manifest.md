---
title: Scenario 49 — TUI QA pane sections, status counter, and create-picker modal
description: Capture of the QA pane rendering three sections, the status-bar counter, and the create-picker modal driving an author-* flow
---

## Workdir

- Recorded from a throwaway pm project at `/scratch/pm-test-cap-1778699051` against pm installed editable from `/workspace` (venv at `/tmp/pm-venv`).
- Captures saved to `pm/qa/captures/pr-6be8ee6/scenarios/49/` in the PR workdir `/workspace`.

## What this demonstrates

Six Given/When/Then triples, all PASS:

1. After `q`, the QA pane shows `Instructions (1)`, `Regression Tests (1)`, and `Artifact Recipes (1)` headers, each with a divider and one seeded item, and the status bar reads `QA    3 item(s)    Enter=run  e=edit  d=debug  a=add  q=back`.
2. With the cursor on the regression item, `Enter` launches a new pane whose prompt (built by `build_regression_test_prompt`) contains the literal `pm/qa/captures/regression/<test-id>/<timestamp>/` (verified via `tmux capture-pane`, the path wraps across rendered lines but is contiguous in the prompt source).
3. `a` opens a centered `Create QA file` modal with a `Name` input, a `Kind` list of exactly `Instruction`, `Regression test`, `Artifact recipe`, the hint `↑↓ change kind · Enter create · Esc cancel`, and `▸` defaulting to `Instruction`.
4. Typing `picker-test`, two `Down`s onto `Artifact recipe`, then `Enter` dismisses the modal and launches a pane running `pm qa author-artifact picker-test` (guided author flow output visible in the new pane).
5. Reopening the picker and pressing `Enter` with an empty `Name` does not launch a new pane (pane count unchanged); the modal remains open.
6. `Escape` on the picker closes it (QA pane visible again) and launches no new pane.

## Driver commands (abridged)

```bash
TARGET=$(pm session name)
tmux pipe-pane -t "$TARGET:0.0" -o "cat >> .../transcript.log"
tmux new-session -d -s pm-recorder -x 200 -y 50 \
    "asciinema rec --quiet .../recording.cast -c 'tmux attach -t $TARGET'"
pm tui send q -s "$TARGET"
pm tui send a -s "$TARGET"
pm tui send picker-test -s "$TARGET"
pm tui send Down -s "$TARGET"; pm tui send Down -s "$TARGET"
pm tui send Escape -s "$TARGET"
pm tui send q -s "$TARGET"
tmux send-keys -t pm-recorder C-b d
tmux pipe-pane -t "$TARGET:0.0"
```

## Notes

- The recorder session uses `asciinema rec` inside a separate tmux session attaching the pm session, per `tmux-screen-recording.md`. This is the no-TTY workaround.
- Triples 2 and 4 launch real subpanes (regression test claude pane, author-artifact pane). The cast does not press Enter on the regression item — that triple was validated separately via `tmux capture-pane` grep for the captures path in the live launched pane, since launching a long-running claude session inside the recording would dominate the cast.

## Files

- `transcript.log` — `tmux pipe-pane` stream of pane 0.0 covering the recorded session.
- `recording.cast` — asciinema replay of the recorder client attached to the pm session.
- `manifest.md` — this file.
- `prompt.md` — this scenario's prompt (pre-existing, committed at scenario start).
