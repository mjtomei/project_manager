---
pr: pr-6be8ee6
workdir: /workspace
captured_at: 2026-05-12
recipe: pm/qa/artifacts/cli-recording.md
---

# Scenario 18 — fresh-install `pm qa docs`

## Commands

Outer recording command:

```
asciinema rec pm/qa/captures/pr-6be8ee6/scenarios/18/recording.cast --overwrite \
  -c 'env -i HOME=$HOME TERM=xterm-256color \
        PATH=/tmp/pm-pkg-venv/bin:/usr/bin:/bin \
        VIRTUAL_ENV=/tmp/pm-pkg-venv \
        bash /tmp/scenario18_inner.sh'
```

Inner script (`/tmp/scenario18_inner.sh`), driven inside a `set -x` shell so
each command is echoed before its output:

```bash
#!/bin/bash
set -x
command -v pm || echo NO_PM_YET
pip install /workspace
command -v pm
pip show pm | head -5
cd /tmp
pm qa docs | tee /tmp/pm-pkg-venv/pm-qa-docs.log | head -40
python3 -c 'import pm_core, pathlib; p = pathlib.Path(pm_core.__file__).parent / "docs/qa_library.md"; print(p); print("EXISTS:", p.exists())'
python3 -c 'import importlib.resources, pm_core; print(importlib.resources.files("pm_core").joinpath("docs/qa_library.md").read_text()[:120])'
diff <(pm qa docs) /workspace/pm_core/docs/qa_library.md && echo PARITY_OK || echo PARITY_FAIL
```

Pre-recording sanity (separate shell, not in cast) confirmed the host pm
install was invisible under `env -i ... PATH=/usr/bin:/bin`:
`command -v pm` printed nothing (exit 1) and
`python3 -c "import pm_core"` raised `ModuleNotFoundError`. The recording
was then driven inside a clean venv at `/tmp/pm-pkg-venv` created with
`python3 -m venv`.

## What this demonstrates

A user with no prior `pm` install can `pip install /workspace` (this
branch) into a fresh venv and immediately run `pm qa docs` from a
directory outside the source tree (`/tmp`). The packaged
`pm_core/docs/qa_library.md` is shipped via `pyproject.toml`'s
`[tool.setuptools.package-data] pm_core = ["docs/*.md"]` — confirmed in
two ways inside the recording:

- `pathlib.Path(pm_core.__file__).parent / "docs/qa_library.md"` resolves
  to `/tmp/pm-pkg-venv/lib/python3.10/site-packages/pm_core/docs/qa_library.md`
  with `EXISTS: True`, proving the file lives in the installed wheel and
  not the source tree.
- `importlib.resources.files("pm_core").joinpath("docs/qa_library.md").read_text()`
  begins with `# pm QA library`, proving the resource is readable via the
  packaging API.

Byte-for-byte parity holds:
`diff <(pm qa docs) /workspace/pm_core/docs/qa_library.md` exits 0 inside
the recording (line prints `PARITY_OK`) and re-running it outside the
recording also exits 0. This is the regression bar from scenario 17 —
`nl=False` on the `click.echo` in `pm_core/cli/qa.py:230` keeps the
output free of a trailing-newline mismatch.

Content assertions on `pm-qa-docs.log` (the `tee`'d full output) all hold:

- First non-empty line is `# pm QA library`.
- Section headings `## The four directories`, `## Authoring`, and
  `## File format (instructions / regression / artifacts)` are all
  present (the real heading text matches what `grep -n '^## '` reports
  against the source file).
- The `> [!CAUTION]` callout and the `pr-7d5d036` references in the
  forward-looking regression-tests section are intact.
- No `Traceback` or `Error:` text in the output.

## Files

- `recording.cast` — asciinema recording of the full install + verification
  driven via `set -x` so each step is echoed.
- `transcript.log` — plain re-run of the same inner script captured as
  text (`asciinema cat` could not be used here because it requires
  `/dev/tty`; the transcript was produced by running the identical
  `bash /tmp/scenario18_inner.sh` outside asciinema with the same `env -i`
  prefix).
- `pm-qa-docs.log` — full stdout of `pm qa docs` from inside the venv,
  copied out of `/tmp/pm-pkg-venv/pm-qa-docs.log` before teardown.
- `manifest.md` — this file.
