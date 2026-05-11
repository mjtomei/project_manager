---
title: Scenario 10 — qa_library.md ships in wheel, pm qa docs reads from site-packages
description: Build pm-0.1.0 wheel, install into a fresh venv, confirm pm_core/docs/qa_library.md is packaged and that pm qa docs reads it from site-packages.
---

## Verdict

PASS — all 5 functional steps succeeded.

## Workdir / environment

- Source: /workspace (PR branch pm/pr-6be8ee6-bug-fix-flow-surface-tui-qa-repro-instructions-in-)
- Venv: /tmp/pm-wheel-venv (Python 3.10.12)
- Wheel: /tmp/wheels/pm-0.1.0-py3-none-any.whl
- All steps run with `PYTHONPATH` unset so the system /opt/pm-src checkout cannot shadow the installed wheel.

## What this recording demonstrates

A single bash script (`/tmp/scenario-10-replay.sh`, contents preserved in
`transcript.log`) reproduces steps 2–5 end-to-end inside the venv:

1. `python -m zipfile -l …pm-0.1.0…whl | grep qa_library.md` →
   `pm_core/docs/qa_library.md` line present.
2. `pm qa docs | head` and 4× `grep -F` for `# pm QA library`,
   `Artifact Recipes`, `[!CAUTION]`, `pr-7d5d036` — all match.
3. `python -c "import pm_core; …"` resolves
   `/tmp/pm-wheel-venv/lib/python3.10/site-packages/pm_core/docs/qa_library.md`
   and prints the first 120 chars.
4. Isolation check: no `workspace`-rooted entries on `sys.path`;
   `pm_core.__file__` lives under site-packages.

Step 1 (venv creation + `pip wheel` + `pip install`) was done before the
recording started — the wheel artifact `/tmp/wheels/pm-0.1.0-py3-none-any.whl`
is documented by `wheel-contents.log`.

## Key assertions confirmed

- `pyproject.toml [tool.setuptools.package-data] pm_core = ["docs/*.md"]` ships
  `qa_library.md` in the wheel.
- `pm qa docs` (entry point installed at `/tmp/pm-wheel-venv/bin/pm`) prints
  the packaged doc with all expected headings.
- The doc path resolves under site-packages, not the workdir — matches
  `pm_core/qa_authoring.py:10` (`Path(__file__).parent / "docs" / "qa_library.md"`).

## Files

- `recording.cast` — asciinema replay of the 5-step verification script
  (`asciinema play recording.cast`). Recorded inside a tmux pane to provide
  a TTY for asciinema.
- `transcript.log` — plain-text run of the same script (`set -x` traced),
  load-bearing artifact for grep/diff.
- `wheel-contents.log` — `python -m zipfile -l` output filtered to the
  `qa_library.md` line proving package-data shipped.
- `pm-qa-docs.log` — full stdout of `pm qa docs` run from `/tmp` (343 lines).
- `pm-core-file-path.log` — output of the `import pm_core …` resolver,
  confirming the site-packages path.

## Notes

- Did not modify `pm_core/` or `pyproject.toml`.
- Venv and `/tmp/wheels` are cleaned up after this commit lands.
