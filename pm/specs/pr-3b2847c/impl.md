# Spec: QA planner — consolidate related assertions into fewer scenarios

## Requirements

1. Update the QA planner prompt in `pm_core/prompt_gen.py::generate_qa_planner_prompt`
   (around lines 827–950) to instruct the planner to group related checks
   into single scenarios where they share setup/context, instead of producing
   one scenario per assertion.
2. No changes to `pm_core/qa_loop.py` execution machinery — this is prompt-only.

## Implicit requirements

- The current "Output Format" already permits multi-step `STEPS` in a single
  scenario. Guidance must reinforce that a scenario can validate multiple
  related assertions, not just one.
- The instruction must not contradict the existing guidance to "Include as
  many scenarios as required to fully exercise the functionality" — instead
  it should reframe it: prefer grouping when checks share setup, but don't
  combine unrelated areas.
- Existing tests in `tests/test_pr_notes.py` only check that
  `generate_qa_planner_prompt` returns a string referencing PR notes; they
  should continue to pass.

## Ambiguities

- How aggressively to consolidate: chosen resolution is to give heuristics
  (shared setup, related flags of one command, related edge cases of one
  function) rather than a hard cap. The execution layer already enforces
  `qa-max-scenarios`.

## Edge cases

- Planner must still produce ≥1 scenario for tiny PRs.
- Wholly independent areas (e.g. CLI flag + unrelated TUI behavior) must
  remain separate scenarios so failures isolate cleanly.
