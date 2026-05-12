---
pr: pr-6be8ee6
workdir: /workspace
captured_at: 2026-05-12
---

## Commands

```
# Pre-fix state: app.py + sync.py checked out at HEAD~1 (parent of 08e1a64).
git checkout HEAD~1 -- pm_core/tui/app.py pm_core/tui/sync.py

pm session >/dev/null 2>&1 || true
TARGET=pm-pm-test-1778622684-804f99b4
tmux pipe-pane -t "$TARGET:0.0" -o "cat >> .../transcript.log"
tmux new-session -d -s pm-recorder -x 200 -y 50 \
    "asciinema rec --quiet .../recording.cast -c 'tmux attach -t $TARGET'"

pm tui send q -s $TARGET           # QA pane shows 2 item(s) initially
# add pm/qa/artifacts/foo-art.md on disk
pm tui send r -s $TARGET           # refresh
pm tui view > step7-broken-status-bar.txt
```

## What this demonstrates

The bug fixed by commit 08e1a64: pressing `r` (refresh) while the QA
pane is visible reverts the status bar from `QA  N item(s)` back to
the project status line (`Project: ...  N PRs  repo: ...  up to date`),
even though the QA pane body re-renders correctly with the new
`Artifact Recipes (1)` count.

See `step7-broken-status-bar.txt` for the captured framebuffer: the body
shows the three QA sections with correct counts, but the top status bar
is the project bar, not `QA  3 item(s)`.

Compare with `../post-fix/transcript.log` and the post-fix manifest:
after the fix, the status bar reads `QA  3 item(s) ...` immediately
after the refresh, matching the body counts.

## Files

- `transcript.log` — full scrollback during the pre-fix run.
- `recording.cast` — asciinema replay (200x50).
- `step7-broken-status-bar.txt` — `pm tui view` snapshot showing the
  project status bar where the QA bar should be.
- `manifest.md` — this file.

Cross-link: post-fix capture at `../post-fix/`.
