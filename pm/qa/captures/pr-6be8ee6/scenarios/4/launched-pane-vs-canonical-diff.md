# Launched Regression Pane vs Canonical Prompt

The pm tui Enter key was pressed on `sample-regression`. A new pane
was spawned running `claude` with a prompt produced by
`pm_core.regression_prompts.build_regression_test_prompt`.

After dismissing the trust prompt, claude rendered its conversation
view with the prompt text. Because claude soft-wraps and prefixes lines
with `  ` and `>` markers, the rendered view is not byte-identical to
the canonical generator output, but textually equivalent.

## Evidence of equivalence

Phrases unique to `build_regression_test_prompt` (regression_prompts.py)
that appear in the launched pane capture (`launched-regression-pane.log`):

- "## Filing Findings"  (regression_prompts.py only — instructions branch
  emits a different "## QA Instruction:" heading)
- "**Bug**: `pm pr add '<title>' --plan bugs --description ..."
- "**Improvement**: `pm pr add '<title>' --plan improvements ..."
- "If a capture under `pm/qa/captures/regression/...`"
- "`pm pr note add <pr-id> '<short observation>; capture: <path>'`"
- "Filing is independent of your verdict for the test."

These all appear verbatim in `canonical-regression-prompt.txt` (the
generator output) and in `launched-regression-pane.log` (claude's
render of the launched pane).

## Code path

`pm_core/tui/pane_ops.py:485-491` — `launch_qa_item` branches on
`category == "regression"` and calls
`build_regression_test_prompt(session, pane_id, title, body,
file_findings=True)`. The non-regression branch produces a
"## QA Instruction:" prompt, which does NOT appear in the capture.

## Conclusion

The TUI Enter key on a regression item launches a Claude session whose
prompt is `build_regression_test_prompt(...)` output, matching the
expected codepath.
