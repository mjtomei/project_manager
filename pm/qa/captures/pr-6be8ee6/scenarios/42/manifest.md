---
pr: pr-6be8ee6
workdir: /workspace
captured_at: 2026-05-13
recipe: pm/qa/artifacts/cli-recording.md
---

## Commands

```
unset PYTHONPATH
python3 -m venv /tmp/pm-pkg-venv
/tmp/pm-pkg-venv/bin/pip install /workspace   # non-editable wheel
cd /tmp
/tmp/pm-pkg-venv/bin/pm which
/tmp/pm-pkg-venv/bin/pm qa docs > /tmp/qa-docs.out
grep -c '^# pm QA library' /tmp/qa-docs.out
grep -c '^## Instructions' /tmp/qa-docs.out
grep -c '^## Regression tests' /tmp/qa-docs.out
grep -c '^## Artifact recipes' /tmp/qa-docs.out
diff /tmp/qa-docs.out /workspace/pm_core/docs/qa_library.md
```

## What this demonstrates

`qa_library.md` is shipped as package-data (declared under
`[tool.setuptools.package-data]` in `pyproject.toml`) and `pm qa docs`
resolves it from the installed wheel. The recording shows:

- `pm which` → `/tmp/pm-pkg-venv/lib/python3.10/site-packages/pm_core`
  (real packaged install, not an editable shadow on /workspace).
- `pm qa docs` prints 342 lines of doc; first 20 lines visible in the
  cast / transcript.
- All four expected headers present (top-level title and three section
  headers, each exactly once).
- `diff` against the source file is empty — the bundled output equals
  the source-of-truth byte-for-byte.

A separate run inside a fresh `pm init`-ed throwaway project produced
identical output (captured as `qa-docs-project.out`), confirming no
project-specific override path is consulted.

### Note on install.sh

`install.sh --local` performs an *editable* install
(`pip install -e`), so `pm which` from any cwd would return
`/workspace/pm_core`. To exercise the actual packaging contract
(package-data shipped in a wheel) this capture uses a true
non-editable `pip install /workspace` into a throwaway venv. The
editable install would not catch a missing `package-data` entry; the
wheel install does.

## Files

- `recording.cast` — asciinema replay of the verification script.
- `transcript.log` — plain-text stdout/stderr of the same run.
- `qa-docs-tmp.out` — `pm qa docs` output captured from `/tmp` (no
  project).
- `qa-docs-project.out` — `pm qa docs` output captured from inside a
  freshly `pm init`-ed throwaway project. Identical to
  `qa-docs-tmp.out`.
