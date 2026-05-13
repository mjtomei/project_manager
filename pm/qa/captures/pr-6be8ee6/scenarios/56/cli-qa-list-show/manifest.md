---
pr: pr-6be8ee6
workdir: /tmp/pm-fm-test-xQRU
captured_at: 2026-05-13
recipe: pm/qa/artifacts/cli-recording.md
---

## Commands

```
pm qa list
pm qa show no-frontmatter
pm qa show legacy-tags
pm qa show missing-description
```

## What this demonstrates

Frontmatter resilience across `pm qa list` and `pm qa show` in a fresh
pm project containing three hand-authored instruction files:

- `no-frontmatter.md` — body only, no `---` delimiters.
- `legacy-tags.md` — full frontmatter including the no-longer-surfaced
  `tags: [foo, bar]` legacy field.
- `missing-description.md` — frontmatter with only `title:`.

`pm qa list` shows three Instructions rows. `no-frontmatter` falls
back to the prettified file-stem title `No Frontmatter` with no
`— <description>` suffix (since `_parse_frontmatter` returns `{}`
when the file doesn't start with `---`). `missing-description` shows
its title with no description suffix. `legacy-tags` shows
`Legacy Tags — An instruction with legacy tags field` (the `tags`
field is read but silently ignored — no warning, no traceback).

`pm qa show` on each prints `# <title>`, an optional description
line, the `[<path>]` line, and the body. For `no-frontmatter` the
body equals the raw file contents in full (the parser short-circuits
on missing delimiters). No `yaml.YAMLError`, no `FileNotFoundError`,
no traceback in any invocation; all exit 0.

## Files

- `recording.cast` — asciinema replay of the four commands above.
- `transcript.log` — plain-text capture of stdout for the same commands.

## Cross-references

See `../cli-qa-docs/` for the `pm qa docs` packaging capture, and
`../tui-qa-pane/` for the TUI rendering of these same files.
