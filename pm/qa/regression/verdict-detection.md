---
title: "Verdict Detection and Stability"
description: "Test verdict extraction, prompt filtering, and stability tracking"
tags: [core, local, vanilla, github, containerized, uncontainerized]
---

## Setup

Work in the current directory which has an initialized pm project.

## Test Steps

### 1. Test verdict extraction from clean output
```bash
python3 -c "
from pm_core.loop_shared import extract_verdict_from_content

# Simple PASS at end
content = '''I've completed all the checks.
Everything looks good.

PASS'''
v = extract_verdict_from_content(content, ('PASS', 'NEEDS_WORK', 'INPUT_REQUIRED'),
                                  ('PASS', 'NEEDS_WORK', 'INPUT_REQUIRED'))
assert v == 'PASS', f'Expected PASS, got {v}'
print('Clean PASS: OK')

# NEEDS_WORK with markdown
content2 = '''Found some issues.

**NEEDS_WORK**'''
v2 = extract_verdict_from_content(content2, ('PASS', 'NEEDS_WORK', 'INPUT_REQUIRED'),
                                   ('PASS', 'NEEDS_WORK', 'INPUT_REQUIRED'))
assert v2 == 'NEEDS_WORK', f'Expected NEEDS_WORK, got {v2}'
print('Markdown NEEDS_WORK: OK')
"
```

### 2. Test prompt line filtering
```bash
python3 -c "
from pm_core.loop_shared import build_prompt_verdict_lines, is_prompt_line

prompt = '''End with a verdict:
- PASS if everything looks good
- NEEDS_WORK if there are issues'''

keywords = ('PASS', 'NEEDS_WORK', 'INPUT_REQUIRED')
prompt_lines = build_prompt_verdict_lines(prompt, keywords)
print(f'Prompt verdict lines: {len(prompt_lines)}')

# These should be recognized as prompt lines
assert is_prompt_line('- PASS if everything looks good', prompt_lines, keywords)
print('Prompt line detection: OK')

# But a standalone PASS should NOT be a prompt line
assert not is_prompt_line('PASS', prompt_lines, keywords)
print('Standalone verdict not prompt line: OK')
"
```

### 3. Test stability tracker
```bash
python3 -c "
from pm_core.loop_shared import VerdictStabilityTracker, STABILITY_POLLS

tracker = VerdictStabilityTracker()

# update() returns bool: True when stable, False otherwise

# First poll: not stable yet
result = tracker.update('test-key', 'PASS')
assert result is False, 'Should not be stable after 1 poll'
print(f'After 1 poll: not stable (need {STABILITY_POLLS})')

# Second poll with same verdict: should be stable
result = tracker.update('test-key', 'PASS')
assert result is True, f'Should be stable after {STABILITY_POLLS} polls'
print(f'After {STABILITY_POLLS} polls: stable PASS')

# Change verdict: resets
result = tracker.update('test-key', 'NEEDS_WORK')
assert result is False, 'Changing verdict should reset stability'
print('Verdict change resets stability: OK')
"
```

### 4. Test edge cases
```bash
python3 -c "
from pm_core.loop_shared import extract_verdict_from_content

# Empty content
v = extract_verdict_from_content('', ('PASS',), ('PASS',))
assert v is None, f'Empty content should return None, got {v}'
print('Empty content: OK')

# Verdict only in middle (not tail) — function uses internal VERDICT_TAIL_LINES
from pm_core.loop_shared import VERDICT_TAIL_LINES
lines = ['line'] * 50 + ['PASS'] + ['line'] * (VERDICT_TAIL_LINES + 10)
content = '\n'.join(lines)
v = extract_verdict_from_content(content, ('PASS',), ('PASS',))
assert v is None, 'Verdict outside tail should not be found'
print(f'Verdict outside tail (VERDICT_TAIL_LINES={VERDICT_TAIL_LINES}): OK')

# Multiple verdicts — last one wins
content = 'NEEDS_WORK\nsome text\nPASS'
v = extract_verdict_from_content(content, ('PASS', 'NEEDS_WORK'), ('PASS', 'NEEDS_WORK'))
print(f'Multiple verdicts, last found: {v}')
"
```

## Expected Behavior

- Clean verdicts on their own line are detected
- Markdown-wrapped verdicts (bold, backtick) are detected
- Prompt instruction lines are filtered out to avoid false positives
- Stability requires consecutive matching polls
- Edge cases handled gracefully

## Reporting

```
TEST RESULTS
============
clean extraction:  [PASS/FAIL] - PASS and NEEDS_WORK detected
prompt filtering:  [PASS/FAIL] - Prompt lines excluded
stability:         [PASS/FAIL] - Tracker requires consecutive polls
edge cases:        [PASS/FAIL] - Empty, out-of-tail, multiple handled

OVERALL: [PASS/FAIL]
```
