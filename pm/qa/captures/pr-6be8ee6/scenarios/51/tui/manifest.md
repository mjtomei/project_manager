---
title: Scenario 51 — TUI QA pane frontmatter resilience
description: pm session TUI QA pane (key q) rendering three instruction files with mixed frontmatter
---

## Workdir

Same throwaway project at `/scratch/pm-test-1778698926` with the three instruction files (`complete.md`, `legacy.md`, `bare.md`) from the CLI capture in place.

## Commands recorded

```
pm session                    # in the project workdir, creates session pm-pm-test-1778698926-...
tmux send-keys -t <pm-sess> q # toggle QA view open
```

For the asciinema cast, the pm session is attached from a separate tmux scaffold socket (`-S /tmp/tmux-1000/default attach -t <pm-sess>`) so the recorder pane has a tty without recursing into the target session. `q` is delivered via `tmux send-keys` to the scaffold pane during recording.

## What this demonstrates

- The QA pane renders without crashing (no Python traceback).
- The `Instructions (3)` section header is followed by rows for `bare`, `complete`, and `legacy`.
- `complete` shows its title plus the description on the indented line below it.
- `legacy` shows its title and no description line beneath (missing description is blank — not `None`, no exception).
- `bare` shows `bare: Bare` (title derived from filename) with no description line.
- The two empty sections `Regression Tests (0)` and `Artifact Recipes (0)` also render normally; the status bar reports `3 item(s)`.

## Files

- `recording.cast` — asciinema replay of opening the QA pane.
- `transcript.log` — final pane scrollback of the QA pane (load-bearing artifact).

## Cross-links

- CLI surface for the same files: `../cli/manifest.md`.
