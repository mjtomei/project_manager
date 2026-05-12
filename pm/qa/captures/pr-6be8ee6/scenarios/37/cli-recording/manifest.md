---
title: Scenario 37 CLI recording — packaging + frontmatter resilience
description: pm qa docs from arbitrary cwd; pm qa list/show on three frontmatter edge-case files
---

## Workdir

Recording shell ran in `/tmp/pm-test-1778627455` (throwaway pm project
seeded with one PR). The asciinema cast and transcript both exercise
the same script: `pm qa list`, three `pm qa show` invocations against
files exercising frontmatter edge cases (no frontmatter at all,
legacy `tags:` field, frontmatter omitting `description:`), and a
final `pm qa docs | head -5` run from `/tmp` to prove the packaged
reference doc resolves from an unrelated cwd after `./install.sh --local`.

## What this demonstrates

- `pm qa list` exits 0 and renders all three sections (Instructions,
  Regression Tests, Artifact Recipes) including the no-frontmatter
  file (rendered as a titleized filename).
- `pm qa show <name>` resolves across categories without `--category`
  and prints the body for each edge-case file with no traceback.
- `pm qa docs` from `/tmp` (no pm project there) still prints the
  packaged `pm_core/docs/qa_library.md` — proving the doc was shipped
  alongside the installed package, not looked up via cwd.

## Files

- `recording.cast` — asciinema replay of the script
- `transcript.log` — plain-text run of the same script (load-bearing
  parseable artifact)
