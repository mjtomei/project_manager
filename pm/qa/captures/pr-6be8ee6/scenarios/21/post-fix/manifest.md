---
pr: pr-6be8ee6
workdir: /workspace
captured_at: 2026-05-12
---

## Commands

```
# Recording driver (abridged):
pm session >/dev/null 2>&1 || true
TARGET=pm-pm-test-1778622684-804f99b4
tmux pipe-pane -t "$TARGET:0.0" -o "cat >> .../transcript.log"
tmux new-session -d -s pm-recorder -x 200 -y 50 \
    "asciinema rec --quiet .../recording.cast -c 'tmux attach -t $TARGET'"

pm tui send q -s $TARGET                # toggle QA pane (3 sections, artifacts empty)
# add pm/qa/artifacts/foo-art.md on disk
pm tui send r -s $TARGET                # refresh — status bar must update to 3 item(s)
pm tui send a -s $TARGET                # open QACreatePickerScreen
pm tui send Enter -s $TARGET            # empty name — modal stays open
pm tui send my-new-recipe -s $TARGET
pm tui send Down -s $TARGET (x5)        # row 6 = Artifact recipe (scaffold)
pm tui send Enter -s $TARGET            # spawns `pm qa add-artifact my-new-recipe`
pm tui send a -s $TARGET                # reopen modal
pm tui send cancel-me -s $TARGET
pm tui send Escape -s $TARGET           # cancel — no file, no pane
```

## What this demonstrates

End-to-end exercise of the QA pane (`q`) and the create-picker modal (`a`):
- Three labeled sections render (`Instructions (1)`, `Regression Tests (1)`,
  `Artifact Recipes (0)`), and the empty Artifact Recipes section still
  renders its header.
- Status bar reads `QA  2 item(s)` initially; sums across all three
  categories.
- After adding `pm/qa/artifacts/foo-art.md` on disk and pressing `r`,
  the body updates to `Artifact Recipes (1)` AND the status bar updates
  to `QA  3 item(s)` — this is the post-fix behavior. The pre-fix bar
  reverted to the project status line after refresh; commit 08e1a64
  fixed that.
- `QACreatePickerScreen` opens with the six expected `Kind` rows.
- Empty-name `Enter` keeps the modal open.
- Typing `my-new-recipe`, arrowing down to row 6, and pressing `Enter`
  spawns `pm qa add-artifact my-new-recipe`; the file appears on disk.
- Pressing `a` then `Escape` dismisses the modal with no side effects
  (no spawned pane, no `cancel-me*` file).

## Files

- `transcript.log` — full scrollback of the TUI pane during the run.
- `recording.cast` — asciinema replay (200x50) of the same run.
- `manifest.md` — this file.

Cross-link: pre-fix capture at `../pre-fix/` shows the broken status
bar before commit 08e1a64.
