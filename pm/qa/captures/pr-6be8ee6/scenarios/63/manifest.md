---
title: Scenario 63 — TUI QA pane sections, status counter, create-picker modal
description: Capture demonstrating the three-section QA pane render, status counter sum, and the create-picker modal routing for author-artifact
---

## Scope

Drives a subset of scenario 63's triples — the populated-project render
(triple 1) and the create-picker `author-artifact demo` route (triple 3)
— end-to-end through the TUI. Triples 2 (empty artifacts), 4 (empty-name
guard), 5 (Esc cancel), and 6 (regression Enter) were exercised
in-session against `/scratch/proj63a` and `/scratch/proj63b` and passed;
this recording focuses on the two triples that most directly demonstrate
the section-header layout + counter sum + picker routing.

## Workdir

Capture project: `/scratch/proj63c` (throwaway: `pm init --backend local`
+ one `pm pr add` + three QA fixtures under
`pm/qa/{instructions,regression,artifacts}/`).

## How it was produced

```
# session
( pm session >/dev/null 2>&1 ) &
TARGET=$(pm session name)        # pm-proj63c-becae664

# transcript pipe
tmux pipe-pane -t "$TARGET:0.0" -o "cat >> recording transcript.log"

# recorder
tmux new-session -d -s pm-recorder63 -x 200 -y 50 \
  "asciinema rec --quiet recording.cast -c 'tmux attach -t $TARGET'"

# drive
pm tui send q -s "$TARGET"               # open QA pane
pm tui send a -s "$TARGET"               # open create-picker
for c in d e m o; do pm tui send "$c" -s "$TARGET"; done
pm tui send down -s "$TARGET"            # Kind: Regression test
pm tui send down -s "$TARGET"            # Kind: Artifact recipe
pm tui send enter -s "$TARGET"           # launch pm qa author-artifact demo
```

## What the capture shows

- QA pane renders three section headers with horizontal rules and per-section
  counts: `Instructions (1)`, `Regression Tests (1)`, `Artifact Recipes (1)`.
- Status bar shows ` QA    3 item(s)    Enter=run  e=edit  d=debug  a=add  q=back`.
- Pressing `a` opens the `QACreatePickerScreen` modal with Name input and a
  three-option Kind list (Instruction / Regression test / Artifact recipe).
- After typing `demo` and pressing `down` twice, the Artifact recipe row
  shows the `▸` selection marker.
- Submitting launches a second pane whose `bash -c` command runs
  `pm qa author-artifact demo` (verified by `ps` on the pane pid during
  the in-session run on /scratch/proj63a).

## Files

- `transcript.log` — pipe-pane scrollback of the pm-proj63c TUI pane.
  38 occurrences of the QA item titles (Inst One / Reg One / Art One)
  and `demo` confirm the render + typed name reached the pane.
- `recording.cast` — asciinema replay of the same drive (~73KB).
- `prompt.md` — Claude prompt artifact (planner-generated, unrelated
  to this capture but present in the directory).

## Notes

- This is not a pre-fix / post-fix split because no bug was found
  during scenario 63; no separate states exist to compare.
- The regression-launch triple (6) was confirmed by inspecting the
  `bash -c` command of the launched pane (PID 918, `claude '...'`)
  during the in-session run; the inline prompt contained the
  `~/.pm/sessions/<session-tag>/captures/regression/<test-id>/<timestamp>/`
  template line, the `## QA Regression Test: Reg One` header, the
  `body`, and the `## Filing Findings` addendum. No on-disk
  `pm/prompts/qa-item-*.md` file is written — the prompt is passed
  inline as the `claude` argv — but the scenario's "(if applicable)"
  qualifier accommodates this.
