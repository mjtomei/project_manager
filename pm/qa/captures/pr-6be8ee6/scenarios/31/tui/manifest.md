---
pr: pr-6be8ee6
workdir: /tmp/pm-test-1778625633
captured_at: 2026-05-12
recipe: pm/qa/artifacts/tmux-screen-recording.md
---

## Commands

Target session created via `pm session` (attach error swallowed — no TTY in
the driving shell). Pane scrollback piped to `transcript.log`. Recorder
session opened on a separate tmux socket (`-L scaffold`) running asciinema
that wraps `tmux attach -t <target>`.

Keys driven on the target's TUI pane:

```
q          # open QA overlay
Down       # advance selection through the three artifact rows
Down
q          # close QA overlay, return to home
```

## What this demonstrates

Frontmatter resilience for the TUI surface. The QA overlay renders an
"Artifact Recipes (3)" section with all three rows:

- `legacy-tags: Legacy Tags Artifact` + description sub-line
- `missing-desc: Missing Description Artifact` (no description)
- `no-frontmatter: No Frontmatter` (id-derived title, no description)

The pane does not crash and does not show an error overlay. Arrow-down
through the rows is selectable for each. Pressing `q` returns to the
normal home view. See `qa-pane-snapshot.txt` for a clean post-state
text snapshot of the QA overlay (caret on `no-frontmatter`).

## Files

- `recording.cast` — asciinema replay produced by the recorder session.
- `transcript.log` — raw pipe-pane stream from the target session
  (includes ANSI escape sequences — load-bearing for grep on rendered
  text after stripping codes).
- `qa-pane-snapshot.txt` — clean text snapshot from `tmux capture-pane -p`
  showing the rendered QA overlay with all three Artifact Recipes rows.

Cross-link: paired CLI capture for the same scenario lives at
`../cli/`.
