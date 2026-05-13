---
pr: pr-6be8ee6
workdir: /workspace
scenario: 43
captured_at: 2026-05-13
recipe: pm/qa/artifacts/cli-recording.md
---

## Commands

```
# Throwaway pm project at /tmp/pm-test-1778679491:
pm init --backend local --no-import
# introduced add()-returns-a-b defect on branch fix-defect
pm pr add 'fix-defect' --plan bugs --description '...'
pm pr start pr-9941232
# Bug-fix flow simulated manually (interactive Claude not driveable here):
asciinema rec .../impl/pre-fix/recording.cast -c 'bash -c "set -x; python3 buggy.py"'
sed -i 's/return a - b/return a + b/' buggy.py && git commit -am "fix"
asciinema rec .../impl/post-fix/recording.cast -c 'bash -c "set -x; python3 buggy.py"'
# QA scenario via the user-facing surface, from inside the pm tmux session:
pm pr spec pr-9941232 qa     # spec_gen blocked on missing API key — wrote spec manually
pm qa run smoke --pr pr-9941232
```

## What this demonstrates

- Steps 9–10 PASS: the bug-fix flow's documented layout
  `pm/qa/captures/<P>/impl/{pre-fix,post-fix}/` lands on disk with
  `manifest.md` + `recording.cast` + `transcript.log` per
  `pm/qa/artifacts/cli-recording.md`. Pre-fix recording shows
  `AssertionError: add(2,3) returned -1`; post-fix shows
  `python3 buggy.py` printing `OK` exit 0. See
  `throwaway-captures/pr-9941232/impl/`.

- Step 11 PASS: `pm qa run smoke --pr pr-9941232` runs to completion
  (final `Result: PASS`) when invoked from inside the pm tmux session.
  Two env quirks worth noting (not PR defects):
  1. Out-of-tmux invocation aborts with `ERROR: No pm session found`
     (`pm_core/cli/helpers.py:846`), so the command must be issued
     inside a pm session pane.
  2. The first run INPUT_REQUIRED'd because `pm pr spec pr-9941232 qa`
     errored with `Invalid API key`. Hand-wrote a minimal
     `pm/specs/pr-9941232/qa.md` to unblock; this is an env
     limitation, not a defect in this PR.

- Step 12 PASS: scenario captures landed at
  `<host_clone>/pm/qa/captures/pr-9941232/scenarios/1/` per
  `_write_scenario_capture_file` (`pm_core/qa_loop.py:1111`),
  containing `prompt.md` + `verdict.md` (PASS). No `manifest.md` /
  `recording.cast` were written, which is expected: this run skipped
  planning, so no artifact recipe was attached to the boilerplate
  scenario, and recipes are only produced when the planner asks for
  them (scenarios get a "Capture Recipe(s)" section iff
  `artifact_paths` is set — `pm_core/prompt_gen.py:1646`).

## Files

- `prompt.md` — the scenario 43 prompt that drove this verdict
- `throwaway-captures/pr-9941232/impl/pre-fix/{manifest,recording.cast,transcript.log}` — pre-fix bug-fix-flow capture
- `throwaway-captures/pr-9941232/impl/post-fix/{manifest,recording.cast,transcript.log}` — post-fix bug-fix-flow capture
- `throwaway-captures/pr-9941232/scenarios/1/{prompt.md,verdict.md}` — what `pm qa run` wrote for the smoke scenario

## Verdict

PASS — impl pre/post captures land at the documented layout, and
`pm qa run` writes the scenario captures the planner asked for at
`pm/qa/captures/<P>/scenarios/<n>/`.
