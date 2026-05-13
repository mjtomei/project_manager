---
pr: pr-6be8ee6
workdir: /workspace
scenario: 43
captured_at: 2026-05-13
recipe: pm/qa/artifacts/cli-recording.md
---

## Commands

```
# (driven end-to-end against a throwaway pm project at /tmp/pm-test-1778679491)
pm init --backend local --no-import
# introduced add()-returns-a-b defect on branch fix-defect
pm pr add 'fix-defect' --plan bugs --description '...'
pm pr start pr-9941232
# manual bug-fix flow (Claude is interactive — no automated drive available)
asciinema rec .../pre-fix/recording.cast -c 'bash -c "set -x; python3 buggy.py"'
sed -i 's/return a - b/return a + b/' buggy.py && git commit -am "fix"
asciinema rec .../post-fix/recording.cast -c 'bash -c "set -x; python3 buggy.py"'
# QA scenario via the user-facing surface
pm pr spec pr-9941232 qa     # spec_gen blocked on missing API key — wrote spec manually
pm qa run smoke --pr pr-9941232   # from inside the pm tmux session
```

## What this demonstrates

- Steps 9–10 PASS: the bug-fix flow's documented layout
  `pm/qa/captures/<P>/impl/{pre-fix,post-fix}/` lands on disk with
  `manifest.md` + `recording.cast` + `transcript.log` per
  `pm/qa/artifacts/cli-recording.md`. Pre-fix recording shows
  `AssertionError: add(2,3) returned -1`; post-fix recording shows
  `python3 buggy.py` printing `OK` exit 0. See
  `throwaway-captures/pr-9941232/impl/`.

- Step 11 PASS (with caveats): `pm qa run smoke --pr pr-9941232` ran
  through to completion when invoked from inside the pm tmux session
  (out-of-tmux invocation aborts with `ERROR: No pm session found`).
  It also INPUT_REQUIRED'd until I hand-wrote `pm/specs/pr-9941232/qa.md`
  because `pm pr spec ... qa` errored with `Invalid API key` — that's
  an env limitation, not a defect in this PR.

- Step 12 PARTIAL: scenario captures landed at
  `<host_clone>/pm/qa/captures/pr-9941232/scenarios/1/` as documented,
  but the writer only produced `prompt.md` + `verdict.md`. The expected
  layout also calls for `manifest.md` + `recording.cast` (or transcript)
  per the artifact recipes — neither was produced.

  Root cause: `pm qa run` skips planning, and the boilerplate
  `QAScenario` it builds at `pm_core/cli/qa.py:352` left
  `artifact_paths=[]`. With no artifact paths, `_install_artifact_files`
  is a no-op and the worker's "## Capture Recipe(s)" prompt section
  (`pm_core/prompt_gen.py:1646`) is empty, so the worker never gets told
  to produce a recording or manifest. The planner's "Every scenario
  should produce every applicable artifact" intent (PR notes /
  `pm_core/prompt_gen.py:1376–1391`) doesn't reach this path.

  Fix committed in this scenario: auto-attach every available artifact
  recipe to the `pm qa run` boilerplate scenario so the worker is told
  to capture evidence even without a planner pass. See `qa:` commit on
  this branch.

## Files

- `prompt.md` — the scenario 43 prompt that drove this verdict
- `throwaway-captures/pr-9941232/impl/pre-fix/{manifest,recording.cast,transcript.log}` — pre-fix bug-fix-flow capture from the throwaway project
- `throwaway-captures/pr-9941232/impl/post-fix/{manifest,recording.cast,transcript.log}` — post-fix bug-fix-flow capture from the throwaway project
- `throwaway-captures/pr-9941232/scenarios/1/{prompt.md,verdict.md}` — what `pm qa run` actually wrote (note: no manifest.md / recording.cast — see Step 12 above)

## Verdict

NEEDS_WORK — pre/post impl captures land at the documented layout
(steps 9–10 PASS), `pm qa run` reaches the documented scenario layout
(step 12 partially PASS), but the boilerplate scenario does not pull
in artifact recipes so workers don't produce `manifest.md` /
`recording.cast`. Fix committed.
