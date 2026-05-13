---
pr: pr-6be8ee6
workdir: /tmp/pm-fm-test-xQRU
captured_at: 2026-05-13
recipe: pm/qa/artifacts/cli-recording.md
---

## Commands

```
pm qa docs | head -20
pm qa docs | wc -l
diff <(pm qa docs) /workspace/pm_core/docs/qa_library.md && echo DIFF_OK
```

## What this demonstrates

`pm qa docs` from an unrelated tmpdir (no `pm/project.yaml` in scope)
prints the packaged `qa_library.md` exactly. The diff against the
on-disk packaged file produces no output and we print `DIFF_OK`,
confirming byte-for-byte equality. Exit codes are 0; nothing is
emitted to stderr.

The `pm` binary under test is the `./install.sh --local` install at
`~/.local/bin/pm` (editable install pointing at `/workspace/pm_core`,
so the packaged doc resolves to
`/workspace/pm_core/docs/qa_library.md`).

## Files

- `recording.cast` — asciinema replay of the three commands above.
- `transcript.log` — plain-text capture of stdout for the same commands.
