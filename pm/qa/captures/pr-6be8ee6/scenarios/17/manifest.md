---
pr: pr-6be8ee6
workdir: /workspace
captured_at: 2026-05-11
recipe: pm/qa/artifacts/cli-recording.md
---

## Commands

```
python3 -m venv /tmp/pm-pkg-venv
source /tmp/pm-pkg-venv/bin/activate
pip install /workspace
cd /tmp
pm qa docs | tee pm-qa-docs.log
python3 -c "import importlib.resources, pm_core; p = importlib.resources.files('pm_core').joinpath('docs/qa_library.md'); print(p.read_text()[:200])"
python3 -c "import pm_core, pathlib; print(pathlib.Path(pm_core.__file__).parent / 'docs/qa_library.md')"
diff <(pm qa docs) /workspace/pm_core/docs/qa_library.md
```

The recording wraps these in `bash -c "set -x; ..."` via asciinema inside
a headless tmux scaffold (no-TTY workaround from cli-recording.md).

## What this demonstrates

After a clean `pip install` of the source tree into a venv outside the
source tree:

- `which pm` resolves to `/tmp/pm-pkg-venv/bin/pm` (installed entry point).
- `pm qa docs`, run from `/tmp`, prints the packaged QA library reference.
  First non-empty line is `# pm QA library`; section headings
  `## The four directories`, `## Authoring`, and
  `## File format (instructions / regression / artifacts)` all appear.
- `importlib.resources.files('pm_core').joinpath('docs/qa_library.md')`
  resolves and reads the file, confirming `package-data` shipped it in
  the wheel.
- `pm_core.__file__`'s sibling `docs/qa_library.md` is under
  `/tmp/pm-pkg-venv/lib/python3.*/site-packages/pm_core/docs/qa_library.md`
  (not the source tree).
- Content parity: `diff <(pm qa docs) pm_core/docs/qa_library.md` shows
  only a single trailing blank line in `pm qa docs` output. That comes
  from `click.echo` appending `\n` to content that already ends in `\n`;
  the doc body is byte-for-byte identical. Not a packaging defect.

## Files

- `recording.cast` — asciinema replay of the install + verification run.
- `pm-qa-docs.log` — full `pm qa docs` stdout teed during the run
  (343 lines; source file is 342 lines, delta is one trailing blank).
- `manifest.md` — this file.
- `prompt.md` — original scenario prompt (pre-existing).
