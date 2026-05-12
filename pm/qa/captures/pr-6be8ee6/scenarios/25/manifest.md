---
pr: pr-6be8ee6
workdir: /workspace
captured_at: 2026-05-12
recipe: pm/qa/artifacts/cli-recording.md
scenario: 25
---

## Commands

```
# Setup (run before recording, see transcript header)
python3 -m venv /tmp/pm-venv && source /tmp/pm-venv/bin/activate
pip install -e /workspace && export PYTHONPATH=/workspace
TEST_DIR=/tmp/pm-test-$(date +%s); mkdir -p "$TEST_DIR" && cd "$TEST_DIR"
git init && pm init --backend local --no-import
pm pr add "Fix crash on save" --description "repro: open editor, hit save crash"
pm pr add "Add export button" --description "add an export button to the toolbar"
# bootstrap-edit pm/project.yaml: set bug PR plan to literal "bugs"
pm prompt <bug-pr-id> > /tmp/bug-impl-prompt.txt
pm prompt <feat-pr-id> > /tmp/feat-impl-prompt.txt
python -c "from pm_core import store, prompt_gen; from pathlib import Path; \
    d=store.load(Path('$TEST_DIR/pm')); print(prompt_gen.generate_review_prompt(d, '<bug-pr-id>'))" \
    > /tmp/bug-review-prompt.txt
# (same for feature PR -> /tmp/feat-review-prompt.txt)

# Recorded run (see recording.cast / transcript.log): runs greps over the four
# rendered prompt files. Concrete IDs from this run: bug=pr-538a3a0, feat=pr-d53a332.
bash /tmp/qa25-script.sh
```

## What this demonstrates

Scenario 25 verifies prompt-generation behavior for bug-tagged vs
non-bug PRs:

- Bug PR impl prompt contains `## Bug Fix Flow`, five numbered steps in
  the required order (Manual repro → failing test → Fix → Verify with
  test → Verify manually), and step 1 references reusing pre-fix
  captures, stashing / parent-commit checkout / file revert, calls out
  "check in with the user" if repro fails, and mentions both
  `pm/qa/instructions/` and `pm/qa/artifacts/`. Captures path is the
  literal `pm/qa/captures/pr-538a3a0/impl/{pre,post}-fix/`; no `<seg>`
  placeholder appears.
- Feature PR impl prompt contains zero occurrences of "Bug Fix Flow".
- Bug PR review prompt contains `## Bug Fix Review Checklist` with the
  captures bullet pointing to `pm/qa/captures/pr-538a3a0/impl/`, flags
  missing captures as **INPUT_REQUIRED** (zero NEEDS_WORK in that
  block), and calls out the failing-then-passing-test, right-reason,
  and scope-limited-to-bug bullets.
- Feature PR review prompt contains zero occurrences of "Bug Fix Review
  Checklist".

All assertions PASS in the recorded run — see grep counts in the
transcript (0 for negative cases, 2 for INPUT_REQUIRED, 0 for
NEEDS_WORK in the checklist block).

## Files

- `recording.cast` — asciinema replay of the verification script.
- `transcript.log` — tmux-pane scrollback of the same run (load-bearing
  evidence for grep/diff).
- `manifest.md` — this file.
