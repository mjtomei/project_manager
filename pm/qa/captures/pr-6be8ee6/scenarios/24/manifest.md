---
title: Scenario 24 — Frontmatter resilience
description: Capture of loader/TUI tolerance for missing or legacy frontmatter fields
---

## Workdir

Test project: `/tmp/pm-test-1778622679` (throwaway, isolated venv at `/tmp/pm-venv`,
`PYTHONPATH=/workspace`, `pm which` -> `/workspace/pm_core`).

## What was exercised

Three edge-case QA files written directly to disk in the test project (bypassing
`pm qa add-*`, which would emit the new schema):

1. `pm/qa/instructions/no-frontmatter.md` — body only, no `---` block.
2. `pm/qa/instructions/legacy-tags.md` — `title`, `description`, plus legacy
   `tags: [foo, bar]`.
3. `pm/qa/artifacts/no-description.md` — `title` only, `description` missing.

## Observed behavior

### `pm qa list` (exit 0)

```
Instructions (2):
  legacy-tags: Legacy Tags — Has a legacy tags field
  no-frontmatter: No Frontmatter

Regression Tests (0):
  (none)

Artifact Recipes (1):
  no-description: No Description
```

All three files surface under the correct section. `no-frontmatter` gets a
fallback title derived from the slug ("No Frontmatter") and no description
suffix. `no-description` shows title with no description suffix. `legacy-tags`
shows title + description; the legacy `tags:` line is silently ignored.

### `pm qa show <name>` (exit 0 for all three)

- `no-frontmatter` — prints fallback title header `# No Frontmatter`, file
  path, then the entire file body (loader treats whole file as body when no
  opening `---` is present).
- `legacy-tags` — prints title, description, file path, then body. `tags:` not
  rendered.
- `no-description` — prints title header, file path, body. No description line.

No Python traceback on any command.

### TUI `q` pane

The QA pane renders three sections (Instructions, Regression Tests, Artifact
Recipes). Status-bar reads `3 item(s)` — sum across all sections. All three
edge-case rows visible.

### TUI Enter on legacy-tags

Enter launched a new pane (`Launched qa-item pane` status line). The launched
pane started Claude Code cleanly (folder-trust prompt visible). No traceback in
either the TUI pane or the launched pane.

## Files

- `transcript.log` — full scrollback of the pm TUI pane (`tmux pipe-pane`)
  covering the QA-pane render and the Enter action. Required.
- `recording.cast` — asciinema replay of a fresh recorder session attached to
  the pm tmux session while `q` / Down / Up were driven from outside. Replay
  with `asciinema play recording.cast`.
- `prompt.md` — the QA scenario prompt as launched (pre-existing, included for
  reference).
- `manifest.md` — this file.

## Verdict

PASS. Loader is tolerant of missing frontmatter, missing description, and
legacy `tags:` field across both CLI (`pm qa list`/`pm qa show`) and TUI (`q`
pane render and Enter action).
