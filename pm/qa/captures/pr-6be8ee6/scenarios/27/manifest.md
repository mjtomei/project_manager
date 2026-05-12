---
title: QA scenario 27 — author-* prompt assembly and refuse-to-clobber
description: CLI recording of pm qa author-instruction/regression/artifact verifying packaged qa_library.md embedding, target path resolution, and refusal to clobber an existing artifact
---

## Workdir

Throwaway pm project at `/tmp/pm-test-qa27-1778625636` with an editable
install of `/workspace` (`pm which → /workspace/pm_core`). A `claude`
shim on `PATH` captured each invocation's argv and prompt to
`$TEST_DIR/.captures-replay/`.

## Commands recorded

`/tmp/qa27-script.sh` runs:

- `pm which` and `command -v claude` (sanity)
- `pm qa author-instruction new-repro`
- `pm qa author-regression  new-check`
- `pm qa author-artifact    new-recipe`
- grep checks that all 3 captured prompts embed the distinctive
  `qa_library.md` sentence and the correct absolute target path for
  each category
- `pm qa author-artifact dup` against a pre-existing
  `pm/qa/artifacts/dup.md` to verify exit 1 + "Already exists:" stderr
  + no new shim invocation

## What this demonstrates

- `author-instruction` → `pm/qa/instructions/new-repro.md`,
  `author-regression` → `pm/qa/regression/new-check.md`,
  `author-artifact` → `pm/qa/artifacts/new-recipe.md` (target paths
  appear verbatim in the assembled prompt).
- All three prompts contain the `qa_library.md` sentence
  `"Every project that uses pm gets a pm/qa/ directory"`.
- `author-*` does not create the target file on disk — that's the
  Claude session's job.
- Running `author-artifact dup` on an existing file exits 1, prints
  `Already exists: <abs path>`, and does not launch claude (capture
  count unchanged).

## Files

- `recording.cast` — asciinema replay of `/tmp/qa27-script.sh`.
- `transcript.log` — plain-text run of the same script captured via
  `script(1)`. Load-bearing artifact for grep/diff.
- `prompt.md` — scenario prompt left by the orchestrator (not a
  capture output; ignore).

## Notes

`transcript.log`'s "captures before/after" reads 12 because the
`script(1)` run reused the same `$TEST_DIR` after `asciinema rec` had
already produced 6 captures; the invariant that matters
(`before == after`) holds within each run.

## Verdict

PASS.
