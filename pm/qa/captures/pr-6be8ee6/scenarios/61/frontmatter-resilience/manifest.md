---
pr: pr-6be8ee6
workdir: /tmp/fmproj
captured_at: 2026-05-14
recipe: pm/qa/artifacts/cli-recording.md
---

## Commands

```
pm qa list
pm qa show legacy
pm qa show nodesc
pm qa show nofrontmatter
```

## What this demonstrates

Three hand-crafted instruction files exercise the frontmatter parser:
`legacy.md` (full frontmatter with obsolete `tags`), `nodesc.md`
(frontmatter with `title:` but no `description:`), and
`nofrontmatter.md` (plain markdown body, no `---` delimiters at all).

- `pm qa list` shows all three under Instructions; `nodesc` and
  `nofrontmatter` print with no `—` description suffix; `nofrontmatter`
  falls back to the title-cased filename stem `Nofrontmatter`.
- `pm qa show legacy` prints title, description, path, body (tags
  field is silently ignored).
- `pm qa show nodesc` and `pm qa show nofrontmatter` print the title
  line, then the `[<path>]` line, then the body — no blank or `None`
  description line.
- No Python traceback on stderr from any of the four commands.

## Files

- `recording.cast` — asciinema replay of the four `pm qa` invocations
- `transcript.log` — plain-text dump of the cast
