---
title: Scenario 51 — CLI surface frontmatter resilience
description: pm qa list and pm qa show against three instruction files (complete/legacy/bare frontmatter)
---

## Workdir

Throwaway project at `/scratch/pm-test-1778698926` (pm installed editable from `/workspace` into `/tmp/pm-venv`, `PYTHONPATH=/workspace`). Three files hand-placed under `pm/qa/instructions/`:

- `complete.md` — full title + description frontmatter.
- `legacy.md` — title + legacy `tags:` field, no description.
- `bare.md` — plain markdown, no `---` delimiters.

## Commands recorded

```
pm qa list
pm qa show complete
pm qa show legacy
pm qa show bare
```

Wrapped under `bash -c 'set -x; ...'` so each command is echoed before its output (asciinema run inside a scratch tmux socket because the shell driving this scenario has no tty).

## What this demonstrates

- `pm qa list` exits 0, shows `Instructions (3):` and the three rows in sorted order (`bare`, `complete`, `legacy`). `complete` row carries the `— description` suffix; `legacy` and `bare` render without it (no `None`, no traceback).
- `pm qa show complete` prints the title heading, description line, path, then body.
- `pm qa show legacy` skips the empty description line entirely.
- `pm qa show bare` derives the heading from the id (`# Bare`), skips the description, and emits the whole file as body since no frontmatter delimiter was found.

## Files

- `recording.cast` — asciinema replay of the four commands.
- `transcript.log` — pane scrollback of the same run (load-bearing artifact).
