---
pr: pr-6be8ee6
workdir: /workspace
captured_at: 2026-05-12
recipe: pm/qa/artifacts/cli-recording.md
---

## Commands

The recording wraps the scenario script under asciinema with a fully
sanitized environment so the host's pre-existing `pm` install at
`/opt/pm-src` (exposed via `PYTHONPATH=/opt/pm-src`) and system entry
point at `/usr/local/bin/pm` cannot shadow the venv install:

```
env -i HOME=$HOME TERM=xterm-256color \
    PATH=/tmp/pm-pkg-venv/bin:/usr/bin:/bin \
    asciinema rec --quiet --overwrite \
        pm/qa/captures/pr-6be8ee6/scenarios/17/recording.cast \
        -c 'bash /tmp/scenario17.sh'
```

The script (`/tmp/scenario17.sh`, `set -x`) runs:

```
echo PYTHONPATH=${PYTHONPATH:-<unset>}
which pm                                   # must be empty
cd /tmp && python3 -c "import pm_core"     # must fail
pip install /workspace
which pm                                   # /tmp/pm-pkg-venv/bin/pm
pm qa docs | tee pm-qa-docs.log
python3 -c "import importlib.resources, pm_core; \
    print(importlib.resources.files('pm_core') \
        .joinpath('docs/qa_library.md').read_text()[:120])"
python3 -c "import pm_core, pathlib; \
    print(pathlib.Path(pm_core.__file__).parent / 'docs/qa_library.md')"
diff <(pm qa docs) /workspace/pm_core/docs/qa_library.md
```

## What this demonstrates

In a fully isolated venv (no `PYTHONPATH`, no system `pm` on `PATH`):

- **Step 1 precondition:** `which pm` is empty pre-install; `import
  pm_core` from `/tmp` raises `ModuleNotFoundError`. Both confirm the
  host's `/opt/pm-src` source tree and `/usr/local/bin/pm` are
  successfully neutralized for this test.
- **Step 3:** `pip install /workspace` installs `pm-0.1.0` and
  `which pm` resolves to `/tmp/pm-pkg-venv/bin/pm`.
- **Step 4:** `pm qa docs` run from `/tmp` prints the packaged doc.
  First non-empty line is `# pm QA library`; section headings
  `## The four directories`, `## Authoring`, and
  `## File format (instructions / regression / artifacts)` all appear
  in `pm-qa-docs.log`.
- **Step 5:** `importlib.resources.files('pm_core')
  .joinpath('docs/qa_library.md').read_text()` returns the doc text,
  proving the file shipped in the wheel via
  `[tool.setuptools.package-data] pm_core = ["docs/*.md"]`.
- **Step 6:** `pathlib.Path(pm_core.__file__).parent /
  'docs/qa_library.md'` prints
  `/tmp/pm-pkg-venv/lib/python3.10/site-packages/pm_core/docs/qa_library.md`
  — confirms the installed wheel is what's imported, not the source
  tree.
- **Step 7:** `diff <(pm qa docs) /workspace/pm_core/docs/qa_library.md`
  produces no differences (`DIFF_PARITY_OK`).

## Incidental fix in this scenario

The first pass of this scenario surfaced a small parity bug: `pm qa
docs` used `click.echo(qa_library_doc())`, which appended an extra
newline to content that already ended in `\n`, so `diff` reported a
trailing blank-line mismatch against the source file. Fixed in this
session by passing `nl=False` to `click.echo` in
`pm_core/cli/qa.py:230`. With that change, `diff` is clean and Step
7's "no differences" requirement is met without rationalization.

## Files

- `recording.cast` — asciinema replay of the install + verification run
  inside the sanitized env.
- `pm-qa-docs.log` — full `pm qa docs` stdout (342 lines, matching the
  source byte-for-byte after the `nl=False` fix).
- `manifest.md` — this file.
- `prompt.md` — original scenario prompt (pre-existing).
