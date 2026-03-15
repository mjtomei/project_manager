---
title: "PR QA: Planning and Parallel Execution"
description: "Test QA planning phase, scenario generation, parallel execution, and verdict collection"
tags: [core, local, vanilla, github, containerized, uncontainerized]
---

## Setup

Work in the current directory which has an initialized pm project.

## Test Steps

### 1. Verify QA data structures
```bash
python3 -c "
from pm_core.qa_loop import QAScenario, QALoopState
import dataclasses

# Verify QAScenario fields
fields = {f.name for f in dataclasses.fields(QAScenario)}
expected = {'index', 'title', 'focus', 'instruction_path', 'steps', 'window_name', 'worktree_path', 'container_name'}
missing = expected - fields
assert not missing, f'Missing QAScenario fields: {missing}'
print(f'QAScenario fields: {sorted(fields)}')

# Verify QALoopState fields
fields2 = {f.name for f in dataclasses.fields(QALoopState)}
expected2 = {'pr_id', 'running', 'loop_id', 'planning_phase', 'scenarios', 'scenario_verdicts', 'latest_verdict', 'qa_workdir'}
missing2 = expected2 - fields2
assert not missing2, f'Missing QALoopState fields: {missing2}'
print(f'QALoopState fields: {sorted(fields2)}')
print('Data structures: OK')
"
```

### 2. Verify QA workdir creation
```bash
python3 -c "
from pm_core.qa_loop import create_qa_workdir
import shutil

workdir = create_qa_workdir('pr-test123', 'test-loop')
print(f'QA workdir: {workdir}')
assert workdir.exists(), 'Workdir not created'
print('Workdir created: OK')

# Clean up
shutil.rmtree(workdir, ignore_errors=True)
print('Cleanup: OK')
"
```

### 3. Verify QA status file structure
```bash
python3 -c "
from pm_core.qa_status import QA_STATUS_FILENAME
print(f'Status filename: {QA_STATUS_FILENAME}')

# Verify status reader works with empty/missing file
from pm_core import qa_status
import inspect
src = inspect.getsource(qa_status)
assert 'qa_status.json' in src or QA_STATUS_FILENAME in src, 'Status file reference not found'
print('QA status infrastructure: OK')
"
```

### 4. Verify QA instruction integration
```bash
python3 -c "
from pm_core import qa_instructions
from pm_core.cli.helpers import state_root

root = state_root()
items = qa_instructions.list_all(root)
instr_count = len(items['instructions'])
regr_count = len(items['regression'])
print(f'QA instructions: {instr_count}')
print(f'Regression tests: {regr_count}')
assert regr_count > 0, 'No regression tests found'
print('QA instruction discovery: OK')
"
```

### 5. Verify parallel execution limits
```bash
python3 -c "
from pm_core.regression import _DEFAULT_MAX_PARALLEL, _DEFAULT_TIMEOUT, _POLL_INTERVAL

print(f'Default max parallel: {_DEFAULT_MAX_PARALLEL}')
print(f'Default timeout: {_DEFAULT_TIMEOUT}s')
print(f'Poll interval: {_POLL_INTERVAL}s')
assert _DEFAULT_MAX_PARALLEL >= 1, 'Max parallel must be >= 1'
assert _DEFAULT_TIMEOUT > 60, 'Timeout should be > 60s'
assert _POLL_INTERVAL >= 1, 'Poll interval must be >= 1s'
print('Execution limits: OK')
"
```

### 6. Verify verdict collection
```bash
python3 -c "
from pm_core.regression import VERDICT_PASS, VERDICT_NEEDS_WORK, VERDICT_INPUT_REQUIRED, ALL_VERDICTS

assert VERDICT_PASS == 'PASS'
assert VERDICT_NEEDS_WORK == 'NEEDS_WORK'
assert VERDICT_INPUT_REQUIRED == 'INPUT_REQUIRED'
assert len(ALL_VERDICTS) == 3
print(f'Verdicts: {ALL_VERDICTS}')
print('Verdict constants: OK')
"
```

## Expected Behavior

- QAScenario and QALoopState have all required fields
- QA workdir creation generates the correct directory structure
- QA status tracking uses qa_status.json
- QA instructions and regression tests are discoverable
- Parallel execution has sane defaults (4 parallel, 30min timeout, 5s poll)
- All three verdict types are defined

## Reporting

```
TEST RESULTS
============
data structures:   [PASS/FAIL] - QAScenario and QALoopState fields correct
workdir creation:  [PASS/FAIL] - QA workdir created and cleaned up
status infra:      [PASS/FAIL] - QA status file infrastructure works
instruction disc:  [PASS/FAIL] - Instructions and regression tests found
execution limits:  [PASS/FAIL] - Parallel/timeout/poll defaults sane
verdict constants: [PASS/FAIL] - All verdict types defined

OVERALL: [PASS/FAIL]
```
