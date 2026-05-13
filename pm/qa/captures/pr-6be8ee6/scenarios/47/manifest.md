---
pr: pr-6be8ee6
workdir: /tmp/empty-dir-47
captured_at: 2026-05-13
recipe: pm/qa/artifacts/cli-recording.md
---

## Commands

```
./install.sh --local --force                # in /workspace (pre-capture setup)
cd /tmp/empty-dir-47                        # empty dir: no pm/, no pyproject.toml, no git
unset PYTHONPATH                            # so the install (not /opt/pm-src) is exercised
which pm                                    # -> /home/pm/.local/bin/pm
pm qa docs | tee transcript.log             # render packaged qa_library.md
echo EXIT=$?                                # -> 0
```

## What this demonstrates

Scenario 47: the packaged `pm_core/docs/qa_library.md` is bundled with
the install and `pm qa docs` resolves it from an unrelated cwd.

Setup performed `./install.sh --local --force` from `/workspace`, which
created `~/.local/share/pm/venv`, installed `pm` into it (via
`pip install -e .[test]`), and symlinked `~/.local/bin/pm`. The
`pm_core = ["docs/*.md"]` entry in `pyproject.toml`'s
`[tool.setuptools.package-data]` makes the doc discoverable through
`importlib.resources` regardless of cwd.

The recording shows `pm qa docs` invoked from `/tmp/empty-dir-47` (no
`pm/`, no `pyproject.toml`, no git). Stdout is the rendered
`# pm QA library` doc, including the table that names
`pm/qa/instructions/`, `pm/qa/regression/`, and `pm/qa/artifacts/`.
Exit code is 0, stderr is empty, no traceback or FileNotFoundError.

Note on install mode: `install.sh --local` uses `pip install -e`, so the
package resolves to the source tree at `/workspace/pm_core/`. The
scenario step about unsetting `PYTHONPATH` (which was pointing at
`/opt/pm-src`) is what proves the install on PATH — not an unrelated
checkout — is what served the doc. A non-editable wheel install would
exercise the same `importlib.resources` lookup against site-packages,
but install.sh does not currently offer that mode.

## Files

- `recording.cast` — asciinema replay of the full session (`set -x` shows
  each command, including `which pm`, `pm qa docs | tee transcript.log`,
  and the final `EXIT=0`).
- `transcript.log` — captured stdout of `pm qa docs` only (the
  load-bearing artifact for grep/diff; contains the `# pm QA library`
  header and the subdirectory table).
- `manifest.md` — this file.
