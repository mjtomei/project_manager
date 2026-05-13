---
pr: pr-6be8ee6
workdir: /tmp/pm-fm-test-xQRU
captured_at: 2026-05-13
recipe: pm/qa/artifacts/tmux-screen-recording.md
---

## Driver

```
cd /tmp/pm-fm-test-xQRU
pm session   # creates tmux session pm-pm-fm-test-xQRU-d13fe829 (attach fails in headless bash, session itself runs fine)
tmux send-keys -t pm-pm-fm-test-xQRU-d13fe829:0.0 q   # opens the QA pane
tmux capture-pane -t pm-pm-fm-test-xQRU-d13fe829:0.0 -p > screen.txt
```

## What this demonstrates

The TUI QA pane (toggled by `q`) renders three Instructions rows
sourced from the three hand-authored instruction files in
`pm/qa/instructions/`:

- `legacy-tags: Legacy Tags` with truncated description.
- `missing-description: Missing…` — no description line below the
  title row (renderer correctly omits it when description is empty).
- `no-frontmatter: No Frontmatt…` — prettified stem used as the
  title (loader returns `{}` for the missing frontmatter, and
  `_list_dir` falls back to the prettified file stem).

The status bar shows `3 item(s)`. The pane also lists empty
`Regression Tests (0)` and `Artifact Recipes (0)` sections,
confirming the three-section layout this PR adds. No Textual error
banner, no traceback overlay, no crash.

## Files

- `screen.txt` — `tmux capture-pane` output of pane 0.0 after sending
  the `q` keypress, showing the QA pane content.

## Cross-references

See `../cli-qa-list-show/` for the same three instruction files
viewed via `pm qa list` and `pm qa show`.
