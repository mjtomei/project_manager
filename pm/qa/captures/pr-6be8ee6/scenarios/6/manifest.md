---
scenario: 6
pr: pr-6be8ee6
recipe: cli-recording.md
---

# QA scenario 6 capture

Verification of generate_qa_planner_prompt artifact block gating,
parse_qa_plan ARTIFACT extraction, _install_artifact_files copy/rewrite/miss,
and generate_qa_child_prompt rendering (singular/plural heading).

## Files
- `verify.cast` — asciinema recording of `python3 /tmp/qa_test.py` exercising all 6 steps.

## Result
All assertions pass:
- STEP 2 (planner block present when artifacts dir non-empty)
- STEP 3 (block + ARTIFACT template line dropped when dir empty)
- STEP 4 (5 synthetic scenarios parsed; unknown + non-artifact warnings emitted on logger `pm.qa_loop`; STEPS-embedded `ARTIFACT:` mention not parsed)
- STEP 5 (artifact copied to scratch/qa-artifacts, path rewritten to `/agent/scratch/...`, missing entry dropped with warning)
- STEP 6 (child prompt renders singular "Artifact Capture Recipe" for 1 path, plural for 2; bullet, captures path, git add/commit/push lines, rebase guidance all present)

## Note
The QA scenario doc says the planner logger is `pm_core.qa_loop`, but the
actual logger name is `pm.qa_loop` (qa_loop.py:39:
`_log = configure_logger("pm.qa_loop")`). Adjusted in the test.
