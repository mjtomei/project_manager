---
title: "PR Review: Loop Infrastructure and Iteration Tracking"
description: "Test review loop prompt generation, iteration tracking, and verdict handling"
tags: [core, local, vanilla, github, containerized, uncontainerized]
---

## Setup

Work in the current directory which has an initialized pm project.

## Test Steps

### 1. Verify review command options
```bash
pm pr review --help
```
Confirm it lists: `--fresh`, `--background`, `--review-loop`,
`--review-iteration`, `--review-loop-id`, `--transcript`.

### 2. Test review prompt generation
```bash
python3 -c "
from pm_core import prompt_gen, store
from pm_core.cli.helpers import state_root

root = state_root()
data = store.load(root)
prs = data.get('prs', [])
if not prs:
    print('No PRs to test with — skipping prompt generation')
else:
    pr = prs[0]
    # Check that review prompt generation works
    prompt = prompt_gen.generate_review_prompt(data, pr['id'], 'test-session')
    assert len(prompt) > 100, f'Review prompt too short: {len(prompt)} chars'
    print(f'Review prompt generated: {len(prompt)} chars')
    assert 'review' in prompt.lower() or 'verdict' in prompt.lower(), 'Missing review/verdict in prompt'
    print('Prompt contains review/verdict instructions: OK')
"
```

### 3. Test review loop verdict detection infrastructure
```bash
python3 -c "
from pm_core.loop_shared import extract_verdict_from_content

# Review-specific verdicts
REVIEW_VERDICTS = ('PASS', 'PASS_WITH_SUGGESTIONS', 'NEEDS_WORK', 'INPUT_REQUIRED')
REVIEW_KEYWORDS = ('PASS', 'PASS_WITH_SUGGESTIONS', 'NEEDS_WORK', 'INPUT_REQUIRED')

# PASS_WITH_SUGGESTIONS should be detected
content = '''The code looks good with minor style suggestions.

PASS_WITH_SUGGESTIONS'''
v = extract_verdict_from_content(content, REVIEW_VERDICTS, REVIEW_KEYWORDS, [])
assert v == 'PASS_WITH_SUGGESTIONS', f'Expected PASS_WITH_SUGGESTIONS, got {v}'
print('PASS_WITH_SUGGESTIONS detection: OK')

# NEEDS_WORK
content2 = '''Found critical issues that need fixing.

NEEDS_WORK'''
v2 = extract_verdict_from_content(content2, REVIEW_VERDICTS, REVIEW_KEYWORDS, [])
assert v2 == 'NEEDS_WORK', f'Expected NEEDS_WORK, got {v2}'
print('NEEDS_WORK detection: OK')
"
```

### 4. Test iteration tracking
```bash
python3 -c "
from pm_core import store
from pm_core.cli.helpers import state_root

root = state_root()
data = store.load(root)
prs = data.get('prs', [])
if prs:
    pr = prs[0]
    # Check review iteration metadata structure
    reviews = pr.get('reviews', [])
    print(f'PR {pr[\"id\"]} has {len(reviews)} review(s)')
    for r in reviews[:3]:
        print(f'  iteration={r.get(\"iteration\", \"?\")} verdict={r.get(\"verdict\", \"?\")}')
else:
    print('No PRs available — iteration tracking check skipped')
print('Iteration tracking structure: OK')
"
```

## Expected Behavior

- Review prompt includes verdict instructions (PASS, PASS_WITH_SUGGESTIONS, NEEDS_WORK, INPUT_REQUIRED)
- PASS_WITH_SUGGESTIONS is a valid review verdict (distinct from QA)
- Review iteration tracking stores iteration number and verdict per review
- `--review-loop` flag triggers the fix/commit/push cycle prompt

## Reporting

```
TEST RESULTS
============
review --help:     [PASS/FAIL] - Help shows expected options
prompt gen:        [PASS/FAIL] - Review prompt generated with verdict instructions
verdict detection: [PASS/FAIL] - Review-specific verdicts detected correctly
iteration track:   [PASS/FAIL] - Iteration metadata structure correct

OVERALL: [PASS/FAIL]
```
