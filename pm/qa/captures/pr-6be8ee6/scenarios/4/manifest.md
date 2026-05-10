---
pr: pr-6be8ee6
workdir: /workspace
captured_at: 2026-05-10
scenario: 4
---

## Commands

```
# venv + editable install
python3 -m venv /tmp/pm-venv && source /tmp/pm-venv/bin/activate
pip install -e /workspace
export PYTHONPATH=/workspace

# throwaway pm project
TEST_DIR=/tmp/pm-test-$(date +%s)
mkdir -p "$TEST_DIR" && cd "$TEST_DIR" && git init -q
pm init --backend local --no-import
pm pr add "Sample PR for QA pane test"
pm qa add-instruction sample-instruction
pm qa add-regression  sample-regression
pm qa add-artifact    sample-artifact

# tmux pm session (no-TTY in this env, ignore the attach error)
cd "$TEST_DIR" && pm session 2>/dev/null || true
SESSION=pm-pm-test-1778437815-87492253

# QA pane (3 sections + counts)
pm tui send q -s $SESSION
pm tui view -s $SESSION
tmux capture-pane -p -t $SESSION:0.0 > qa-pane-three-sections.log

# empty artifacts state
mv $TEST_DIR/pm/qa/artifacts/sample-artifact.md $TEST_DIR/sample-artifact.md.bak
pm tui send q -s $SESSION; pm tui send q -s $SESSION
tmux capture-pane -p -t '%0' > qa-pane-empty-artifacts.log
mv $TEST_DIR/sample-artifact.md.bak $TEST_DIR/pm/qa/artifacts/sample-artifact.md

# QACreatePickerScreen modal (a key) and Escape cancel
pm tui send a -s $SESSION
tmux capture-pane -p -t '%0' > qa-create-picker-modal.log
pm tui send Escape -s $SESSION

# Enter on regression item launches build_regression_test_prompt session
pm tui send Enter -s $SESSION   # with sample-regression highlighted
tmux capture-pane -p -t '%5' -S -500 > launched-regression-pane.log

# canonical prompt for diff
python3 -c "
from pathlib import Path
from pm_core import qa_instructions
from pm_core.regression_prompts import build_regression_test_prompt
item = qa_instructions.get_instruction(Path('$TEST_DIR/pm'), 'sample-regression', category='regression')
print(build_regression_test_prompt(session='$SESSION', pane_id=None, title=item['title'], body=item['body'], file_findings=True))
" > canonical-regression-prompt.txt

# pytest
cd /workspace && pytest tests/test_qa_pane.py tests/test_popup_picker.py -q
# -> 93 passed
```

## What this demonstrates

Scenario 4 — the QA pane (`q`) renders three sections (Instructions /
Regression Tests / Artifact Recipes) with `(N)` counts and dividers;
empty sections still render their header and divider; the `a` key
opens `QACreatePickerScreen` with a Name input and a 6-row Kind list
(3 categories × 2 modes); Escape cancels without executing any
`pm qa add-*` / `pm qa author-*` command; Enter on a regression
item launches a new pane running Claude whose prompt matches
`build_regression_test_prompt(...)`; pytest suite for `test_qa_pane`
and `test_popup_picker` is green (93 passed).

## Pre-fix vs post-fix

Post-fix only — this is a non-regression QA against the PR branch
(no fix produced in this scenario).

## Files

- `qa-pane-three-sections.log` — QA pane with all 3 sections populated; status bar visible at top
- `qa-pane-empty-artifacts.log` — `Artifact Recipes (0)` with header + divider, no items
- `qa-create-picker-modal.log` — modal showing 6 kind+mode rows
- `launched-regression-pane.log` — Claude session launched on Enter, rendering the regression-test prompt
- `canonical-regression-prompt.txt` — `build_regression_test_prompt` output for comparison
- `launched-pane-vs-canonical-diff.md` — equivalence notes (claude render vs generator output)
- `status-bar-observed.txt` — verbatim status-bar text observed
- `recording.cast` — asciinema replay of the four key pane states (small synthetic cast; see Note below)

## Status-bar discrepancy (flagged per scenario step 7)

Observed status bar (top of TUI when wide enough):

```
  Project: pm-test-1778437815    1 PRs    repo: /tmp/pm-test-1778437815    up
```

`StatusBar.update_status` (`pm_core/tui/widgets.py:39-50`) renders
`pr_count` only ("N PRs"). It does **not** include a QA artifacts
counter. The scenario's "status-bar counter includes artifacts"
expectation is unmet by the StatusBar widget. The QA pane's own header
(`QA    3 item(s)`) is the in-pane counter that includes artifacts —
this is what the per-section `(N)` counts feed into. Treating the
scenario expectation as referring to that in-pane counter, the
behavior matches; treating it literally (StatusBar widget), it does
not. Calling out as documented in the scenario step.

## Note on recording.cast

The straightforward `asciinema rec -c 'tmux attach -t <session>'`
no-TTY-workaround run produced a 15 MB cast (nested-tmux escape spam).
Replaced with a small synthetic cast that plays the four captured
transcripts back, since the transcripts are the primary evidence and
the cast is supplementary. `transcript.log` files in this directory
are the load-bearing artifacts.
