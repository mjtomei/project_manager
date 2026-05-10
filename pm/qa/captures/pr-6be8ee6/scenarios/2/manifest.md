---
pr: pr-6be8ee6
workdir: /workspace
captured_at: 2026-05-10
recipe: pm/qa/artifacts/cli-recording.md
---

## Commands

```
ls /workspace/pm/qa/artifacts/
python3 -c '... generate_qa_planner_prompt with recipes ...'
python3 -c '... generate_qa_planner_prompt without recipes ...'
python3 -c '... parse_qa_plan happy multi-recipe ...'
python3 -c '... parse_qa_plan edges (mixed/wrong-cat/none) ...'
python3 -m pytest tests/test_qa_loop.py tests/test_qa_instructions.py tests/test_regression_prompts.py -q
```

Wrapped in `bash -c "set -x; ..."` and recorded via asciinema inside a
tmux pane (no-TTY workaround from the cli-recording recipe).

## What this demonstrates

End-to-end execution of QA scenario 2 (planner ARTIFACT block,
parse_qa_plan multi-recipe parsing & filtering, _install_artifact_files
copy + path rewrite, and the targeted pytest suite). The cast shows:

- Both artifact recipes present in `pm/qa/artifacts/`.
- The planner prompt **with** recipes contains the Artifact Recipes
  block, both recipe filenames, and the `ARTIFACT:` field directive.
- The planner prompt **without** recipes (post-fix) contains no
  `ARTIFACT:` template line and no Artifact Recipes block.
- `parse_qa_plan` resolves multi-recipe ARTIFACT, filters unknown
  filenames, rejects wrong-category names, and treats `none` as empty.
- 149 tests in the targeted suites pass.

## Pre-fix vs post-fix

Post-fix capture. This session fixed two issues in the QA pipeline
(committed as `qa: fix _run_qa_finalize_pane NameError + omit ARTIFACT
field when no recipes`):

1. `pm_core/qa_loop.py::_run_qa_finalize_pane` referenced `tmux_mod`
   without importing it — raised `NameError` instead of returning `None`
   for a missing window/session.
2. `pm_core/prompt_gen.py::generate_qa_planner_prompt` unconditionally
   emitted the `ARTIFACT:` field in the scenario template even when
   no artifact recipes existed; the recipes block doc said it should
   appear "only when at least one" recipe is in the library.

Both fixes are exercised in the cast above.
