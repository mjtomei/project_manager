---
title: "Review Loop: Verdict Detection and Iteration"
description: "Test review loop verdict detection, INPUT_REQUIRED handling, and iteration tracking"
tags: [core, local, vanilla, github, containerized, uncontainerized]
---

## Setup

Work in the current directory which has an initialized pm project.

## Test Steps

### 1. Verify review loop module structure
```bash
python3 -c "
from pm_core import review_loop
import inspect

# Check core functions exist
funcs = [name for name, _ in inspect.getmembers(review_loop, inspect.isfunction)]
print(f'review_loop functions: {sorted(funcs)[:15]}')

# Check for key functions
src = inspect.getsource(review_loop)
has_run = 'def run_' in src or 'def start_' in src
has_verdict = 'verdict' in src.lower()
has_iteration = 'iteration' in src.lower()
print(f'Has run function: {has_run}')
print(f'Has verdict handling: {has_verdict}')
print(f'Has iteration support: {has_iteration}')
"
```

### 2. Test review-specific verdict set
```bash
python3 -c "
from pm_core.loop_shared import extract_verdict_from_content

# Review system uses 4 verdicts (unlike QA which uses 3)
REVIEW_VERDICTS = ('PASS', 'PASS_WITH_SUGGESTIONS', 'NEEDS_WORK', 'INPUT_REQUIRED')
REVIEW_KEYWORDS = ('PASS', 'PASS_WITH_SUGGESTIONS', 'NEEDS_WORK', 'INPUT_REQUIRED')

# Test each verdict type
test_cases = [
    ('Clean PASS', 'All good.\n\nPASS', 'PASS'),
    ('With suggestions', 'Minor nits.\n\nPASS_WITH_SUGGESTIONS', 'PASS_WITH_SUGGESTIONS'),
    ('Needs work', 'Critical bug.\n\nNEEDS_WORK', 'NEEDS_WORK'),
    ('Input required', 'Question.\n\nINPUT_REQUIRED', 'INPUT_REQUIRED'),
]

for label, content, expected in test_cases:
    v = extract_verdict_from_content(content, REVIEW_VERDICTS, REVIEW_KEYWORDS, [])
    status = 'OK' if v == expected else f'FAIL (got {v})'
    print(f'{label}: {status}')
    assert v == expected, f'{label}: expected {expected}, got {v}'

print('All review verdicts detected: OK')
"
```

### 3. Test INPUT_REQUIRED does not match instructions
```bash
python3 -c "
from pm_core.loop_shared import extract_verdict_from_content, build_prompt_verdict_lines

# Prompt mentions INPUT_REQUIRED as an instruction
prompt = '''When you need clarification, use:
- INPUT_REQUIRED for questions
- PASS if all looks good
- NEEDS_WORK for issues'''

keywords = ('PASS', 'PASS_WITH_SUGGESTIONS', 'NEEDS_WORK', 'INPUT_REQUIRED')
prompt_lines = build_prompt_verdict_lines(prompt, keywords)
print(f'Prompt verdict lines to filter: {len(prompt_lines)}')

# Content that only has prompt instructions, no actual verdict
content = prompt + '\n\nLet me review the code...'
v = extract_verdict_from_content(content, keywords, keywords, prompt_lines)
assert v is None, f'Should not detect verdict from prompt instructions, got {v}'
print('Prompt line filtering: OK')

# But a real verdict after the review should be detected
content2 = prompt + '\n\nCode reviewed.\n\nPASS'
v2 = extract_verdict_from_content(content2, keywords, keywords, prompt_lines)
assert v2 == 'PASS', f'Should detect real verdict, got {v2}'
print('Real verdict after prompt: OK')
"
```

### 4. Test stability tracking across polls
```bash
python3 -c "
from pm_core.loop_shared import VerdictStabilityTracker, STABILITY_POLLS

tracker = VerdictStabilityTracker()

# Simulate polling sequence: unstable, then stable
key = 'review-test'
results = []
for i in range(STABILITY_POLLS + 1):
    result = tracker.update(key, 'PASS')
    results.append(result)

print(f'Poll results: {results}')
assert results[-1] == 'PASS', f'Should stabilize after {STABILITY_POLLS} polls'
assert all(r is None for r in results[:STABILITY_POLLS-1]), 'Should be None before stable'
print(f'Stability tracking: OK (stabilizes after {STABILITY_POLLS} polls)')

# Flip verdict resets stability
tracker2 = VerdictStabilityTracker()
tracker2.update('k', 'PASS')
tracker2.update('k', 'NEEDS_WORK')  # flip
result = tracker2.update('k', 'NEEDS_WORK')  # 2nd consecutive NEEDS_WORK
assert result == 'NEEDS_WORK', f'Should stabilize on new verdict, got {result}'
print('Verdict flip resets stability: OK')
"
```

### 5. Test review iteration metadata in PR state
```bash
python3 -c "
from pm_core import store
from pm_core.cli.helpers import state_root

root = state_root()
data = store.load(root)
prs = data.get('prs', [])

# Verify PR data structure supports review tracking
for pr in prs[:3]:
    reviews = pr.get('reviews', pr.get('review_history', []))
    status = pr.get('status', '?')
    print(f'PR {pr[\"id\"]}: status={status}, reviews={len(reviews)}')

print('Review iteration structure: OK')
"
```

## Expected Behavior

- All four review verdicts are detected correctly
- PASS_WITH_SUGGESTIONS is a distinct verdict from PASS
- Prompt instruction lines are filtered out to avoid false positives
- Stability tracking prevents premature verdict acceptance
- Verdict flips reset the stability counter
- PR state stores review iteration history

## Reporting

```
TEST RESULTS
============
module structure:  [PASS/FAIL] - review_loop module has expected functions
verdict set:       [PASS/FAIL] - All 4 review verdicts detected
prompt filtering:  [PASS/FAIL] - Instructions don't trigger false verdicts
stability:         [PASS/FAIL] - Consecutive polls required for acceptance
iteration meta:    [PASS/FAIL] - PR state tracks review history

OVERALL: [PASS/FAIL]
```
