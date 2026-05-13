---
pr: pr-6be8ee6
workdir: /workspace
captured_at: 2026-05-13
recipe: pm/qa/artifacts/cli-recording.md
---

## Commands

```
pm init --backend local --no-import
pm qa add-instruction sample-inst
pm qa add-regression sample-reg
pm qa add-artifact sample-art
pm qa add-instruction sample-inst   # duplicate → exit 1
pm qa list
pm qa show sample-art
pm qa edit sample-art
pm qa author-instruction draft-one  # claude shim records prompt
pm qa author-instruction draft-one  # after touch → exit 1
pm qa add foo                       # removed → exit 2
```

## What this demonstrates

End-to-end exercise of the new `pm qa` surface on a freshly-initialized
throwaway project (no prior instructions/regression/artifacts on disk),
covering all eight Given/When/Then triples in scenario 46:

1. `add-instruction`, `add-regression`, `add-artifact` each scaffold a
   file under the matching `pm/qa/<category>/` dir and print
   `Created: <path>`.
2. Re-running `add-instruction sample-inst` prints `Already exists:` to
   stderr and exits 1 without altering the existing file (verified
   independently with sha256sum — see verdict notes).
3. `pm qa list` prints three labeled sections (`Instructions (1):`,
   `Regression Tests (1):`, `Artifact Recipes (1):`) with the items
   formatted as `  <id>: <title>`.
4. `pm qa show sample-art` (no `-c`) auto-detects the artifact, prints
   the `# Sample Art` title, the bracketed absolute path, then the body.
5. `pm qa edit sample-art` with `EDITOR=true` exits 0 with no output —
   the resolver finds the artifact across categories and runs `$EDITOR`.
6. `pm qa author-instruction draft-one` invokes the on-PATH `claude`
   shim, which writes its final positional arg to
   `/tmp/captured-prompt.txt`. The transcript greps the recorded prompt
   for `The four directories` (a section header from
   `pm_core/docs/qa_library.md`) → `1`, and for the literal target path
   `pm/qa/instructions/draft-one.md` → `1`.
7. After `touch pm/qa/instructions/draft-one.md`, re-running
   `pm qa author-instruction draft-one` prints `Already exists:` and
   exits 1 before invoking the shim.
8. `pm qa add foo` (removed command) prints Click's
   `Error: No such command 'add'.` and exits 2; no file is created.

To replay: `asciinema play recording.cast`.

## Files

- `recording.cast` — asciinema recording of the scripted bash run inside
  a tmux-hosted pane (no-TTY workaround per the recipe).
- `transcript.log` — `set -x` shell trace + stdout/stderr of every
  command; the load-bearing artifact for grep/diff review.
- `prompt.md` — the scenario prompt this capture was produced under
  (auto-saved by the QA harness).
