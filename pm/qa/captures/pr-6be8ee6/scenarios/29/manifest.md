---
pr: pr-6be8ee6
workdir: /workspace
captured_at: 2026-05-12
recipe: pm/qa/artifacts/cli-recording.md
---

## Commands

```
# install (editable, via install.sh --local --force) and verify pm location
which pm; pm which

# fresh throwaway pm project
mkdir -p /tmp/pm-test-cap-<ts>; cd /tmp/pm-test-cap-<ts>
git init -q
pm init --backend local --no-import
pm pr add "Test PR for scenario 29 capture"

# scaffold one item per category
EDITOR=true pm qa add-instruction inst-a
EDITOR=true pm qa add-regression reg-a
EDITOR=true pm qa add-artifact art-a
ls pm/qa/instructions pm/qa/regression pm/qa/artifacts

# list shows three labeled sections with counts
pm qa list

# show auto-detects across all three categories
pm qa show inst-a
pm qa show reg-a
pm qa show art-a
pm qa show does-not-exist   # exits 1, stderr "QA item not found"

# edit auto-detects across all three categories (EDITOR=true is a no-op)
EDITOR=true pm qa edit inst-a
EDITOR=true pm qa edit reg-a
EDITOR=true pm qa edit art-a
EDITOR=true pm qa edit does-not-exist   # exits 1

# packaged docs work from a directory with no pm project
cd /tmp
pm qa docs > /tmp/qa-docs-out2.md
diff -q /tmp/qa-docs-out2.md /workspace/pm_core/docs/qa_library.md
grep -E '^# pm QA library$|^## The four directories$|^## File format' /tmp/qa-docs-out2.md
```

## What this demonstrates

Scenario 29 end-to-end: `pm qa add-instruction|add-regression|add-artifact`
each scaffold a file into the correct directory; `pm qa list` renders the
three labeled sections (`Instructions (N):`, `Regression Tests (N):`,
`Artifact Recipes (N):`) with counts; `pm qa show` and `pm qa edit`
auto-detect each id across all three categories without `-c`, returning 0
on hits and 1 on misses (with `QA item not found:` on stderr); and
`pm qa docs` run from `/tmp` (no pm project) emits a copy that is
byte-identical to the source-tree `pm_core/docs/qa_library.md`. The recipe
fallback was avoided — asciinema was available, so the `recording.cast`
plus `transcript.log` are both present.

## Caveats

- `install.sh --local --force` installs in **editable** mode
  (`pip install -e`), so the literal step-3 `ls site-packages/pm_core/docs/`
  check would not find the doc inside the venv — the editable install
  resolves the package data back to `/workspace/pm_core/docs/qa_library.md`
  via importlib. The substantive contract (`pm qa docs` reads the doc
  through `importlib.resources` and works from any cwd) is exercised by
  the recording. A non-editable repackaged install was not tested in this
  scenario; install.sh has no flag to do so.

## Files

- `recording.cast` — asciinema replay of the full scripted run
  (`asciinema play recording.cast`).
- `transcript.log` — `set -x` transcript of the same run; load-bearing
  artifact for grep/diff (search for `Created:`, `Instructions (`, etc.).
