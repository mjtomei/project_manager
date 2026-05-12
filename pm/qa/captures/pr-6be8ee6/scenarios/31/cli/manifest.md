---
pr: pr-6be8ee6
workdir: /tmp/pm-test-1778625633
captured_at: 2026-05-12
recipe: pm/qa/artifacts/cli-recording.md
---

## Commands

```
pm qa list
pm qa show no-frontmatter
pm qa show legacy-tags
pm qa show missing-desc
```

## What this demonstrates

Frontmatter resilience for the CLI surface. The throwaway pm project has
three hand-authored artifact files under `pm/qa/artifacts/`:

- `no-frontmatter.md` — body only, no `---` delimiters.
- `legacy-tags.md` — full frontmatter including the legacy `tags:` field.
- `missing-desc.md` — frontmatter with `title:` only, no `description:`.

`pm qa list` renders all three under "Artifact Recipes" — `no-frontmatter`
has an id-derived title and no description suffix, `legacy-tags` shows
title + description (the `tags:` field is silently ignored), `missing-desc`
shows only the title. `pm qa show` for each prints the `# <title>` header,
the `[path]` line, and the body. No tracebacks, no YAMLError, no KeyError.

## Files

- `recording.cast` — asciinema replay of the four commands run under `set -x`.
- `transcript.log` — plain-text transcript of the same run.

Cross-link: paired TUI capture for the same scenario lives at `../tui/`.
