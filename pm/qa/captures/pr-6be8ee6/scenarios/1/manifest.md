---
pr: pr-6be8ee6
workdir: /workspace
captured_at: 2026-05-10
recipe: pm/qa/artifacts/cli-recording.md
---

## Commands

```
# Detector unit check
python3 -c "from pm_core.bug_fix_prompts import _is_bug_pr; print(_is_bug_pr({'plan':'bugs'}), _is_bug_pr({'type':'bug'}), _is_bug_pr({'plan':'improvements'}), _is_bug_pr({}))"

# Re-export check
python3 -c "from pm_core.prompt_gen import _is_bug_pr, _bug_fix_flow_block, _bug_fix_review_block; print('re-export ok')"

# Impl prompt for a bug PR — verify headings, 5-step structure, captures paths, instructions/artifacts refs, reuse + pre-fix repro language
# Review prompt for a bug PR — verify checklist heading, INPUT_REQUIRED on missing captures, captures path, failing-then-passing + drive-by/scope
# Local-id-only captures path (gh_pr_number=190 must NOT appear in captures dir)
# Negative: improvements PR omits bug-fix flow + review checklist
# Review-loop inheritance: both checklist and Review Loop Mode present
python3 -m pytest tests/test_bug_fix_flow_prompts.py -q
```

Full driver script: see asciinema cast.

## What this demonstrates

Scenario 1 of QA for PR pr-6be8ee6: validates the bug-fix flow prompt
generator (`pm_core/bug_fix_prompts.py`) and its integration into
`pm_core/prompt_gen.py`.

Specifically the cast shows:

- `_is_bug_pr` returns `True True False False` for `plan=bugs`,
  `type=bug`, `plan=improvements`, empty (gating is correct).
- `_is_bug_pr`, `_bug_fix_flow_block`, `_bug_fix_review_block` are
  re-exported from `pm_core.prompt_gen` (backward compat).
- For a bug PR, `generate_prompt` emits `## Bug Fix Flow` with five
  numbered steps in order (Manual repro on pre-fix → failing test →
  Fix → Verify with test → Verify manually), captures paths under
  `pm/qa/captures/pr-XYZ/impl/{pre-fix,post-fix}/`, and references to
  both `pm/qa/instructions/` and `pm/qa/artifacts/`, plus language
  about reusing prior artifacts and reproducing on pre-fix code
  (`stash uncommitted`, `parent commit`).
- For a bug PR, `generate_review_prompt` emits the `## Bug Fix Review
  Checklist`, uses `INPUT_REQUIRED` (not `NEEDS_WORK`) for missing
  captures, references the captures dir, and mentions the
  failing-then-passing test requirement plus a drive-by/scope flag.
- Captures dir uses the local pr id (`pr-XYZ`) even when
  `gh_pr_number=190` is provided — no `pr-190/` paths appear.
- For a non-bug (improvements) PR, neither the bug-fix flow block nor
  the review checklist appears.
- In review-loop mode (review_loop=True), both the bug-fix checklist
  and the Review Loop Mode block are present.
- `tests/test_bug_fix_flow_prompts.py`: 13 passed.

## Pre-fix vs post-fix

N/A — this scenario validates the head-of-branch prompt generators,
not a bug fix. Single capture from current PR head.
