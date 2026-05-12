---
pr: pr-6be8ee6
workdir: /workspace
captured_at: 2026-05-12
recipe: pm/qa/artifacts/cli-recording.md
---

## Commands

```
# All steps run inside a single bash -c via asciinema for one clean cast.
# See /scratch/run-scenario-23.sh for the exact script. Highlights:
python3 -m venv /tmp/pm-pkg-venv && source /tmp/pm-pkg-venv/bin/activate
unset PYTHONPATH
cd /workspace && pip install .
which pm; pm which
python -c "import pm_core, pathlib; p = pathlib.Path(pm_core.__file__).parent/'docs'/'qa_library.md'; print(p, p.exists(), p.stat().st_size)"
cd /tmp && pm qa docs | head -5
cd /tmp && pm qa docs | grep -c '^## The four directories'
cd /tmp && pm qa docs | wc -l
DOC=$(python -c "import pm_core, pathlib; print(pathlib.Path(pm_core.__file__).parent/'docs'/'qa_library.md')")
rm "$DOC"
cd /tmp && pm qa docs; echo "exit=$?"
cp /workspace/pm_core/docs/qa_library.md "$DOC"
```

## What this demonstrates

Validates scenario 23: that `pm_core/docs/qa_library.md` ships in the
built wheel via `[tool.setuptools.package-data]` and that `pm qa docs`
prints it from any cwd.

Findings in the transcript:
- Install from `pip install .` into `/tmp/pm-pkg-venv` succeeded; the
  packaged doc landed at
  `/tmp/pm-pkg-venv/lib/python3.10/site-packages/pm_core/docs/qa_library.md`
  with size 13236 bytes.
- From `/tmp` (no pm/ tree present) `pm qa docs` exits 0, the first
  stdout line is `# pm QA library`, and the body contains the H2
  `## The four directories` (the doc renders it followed by a real
  markdown table — both the heading and table are present).
- Piped output works (342 lines, well over the 50-line threshold).
- Negative control: deleting the installed doc causes `pm qa docs`
  to surface a bare `FileNotFoundError` traceback and exit 1, which
  matches the source at `pm_core/qa_authoring.py:15` doing an
  un-guarded `_DOC_PATH.read_text()`. Captured verbatim; flagged as
  a follow-up bug PR target rather than fixed in this scenario.
- Restore succeeded and `pm qa docs` returned to clean output.

Observation worth flagging (not a bug, just an instruction mismatch):
`pm which` was run from /workspace per the steps and reported
`/workspace/pm_core` rather than the site-packages path. This is by
design — `pm_core/wrapper.py:54-69` deliberately prefers a local
`pm_core/` when cwd contains one, ahead of the installed copy. The
scenario's expectation that `pm which` would report the installed
path is at odds with that behavior. The load-bearing packaging
assertions (steps 4–6) all use cwd=/tmp and exercise the installed
copy correctly, so this doesn't undermine the verdict.

## Files

- `recording.cast` — asciinema cast of the end-to-end run (steps 3–8).
- `transcript.log` — plain-text dump of the same run (load-bearing).
- `manifest.md` — this file.
