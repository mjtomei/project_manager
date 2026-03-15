---
title: "State Management: project.yaml Round-Trip"
description: "Test project.yaml read/write integrity and git-based state sync"
tags: [core, local, vanilla, github, containerized, uncontainerized]
---

## Setup

Work in the current directory which has an initialized pm project.

## Test Steps

### 1. Snapshot current state
```bash
cat pm/project.yaml
```
Save the full contents for comparison.

### 2. Verify YAML structure
Check that project.yaml contains required keys:
- `project.name`
- `project.repo`
- `project.base_branch`
- `project.backend`
- `prs` (list)

### 3. Check status command reads state correctly
```bash
pm status
```
Verify the output matches project.yaml content (project name, backend, PR count).

### 4. Make a state change via CLI
```bash
pm pr add "State roundtrip test PR"
```
Note the PR ID.

### 5. Verify state persisted
```bash
cat pm/project.yaml
```
Verify the new PR appears in the `prs` list with correct title and pending status.

### 6. Verify timestamps
Check that the new PR has `created_at` and `updated_at` timestamps in ISO format.

### 7. Revert state change
```bash
pm pr close <pr-id> --force
```

### 8. Verify state reverted
```bash
cat pm/project.yaml
```
Verify the test PR is removed.

### 9. Check git state sync
```bash
pm push 2>/dev/null || echo "pm push not available or no changes"
```
Verify pm's state directory can be committed.

## Expected Behavior

- project.yaml maintains valid YAML through read/write cycles
- CLI changes are immediately reflected in project.yaml
- Timestamps are auto-generated in ISO format
- Closing a PR removes it from state cleanly

## Reporting

```
TEST RESULTS
============
yaml structure:    [PASS/FAIL] - Required keys present
status read:       [PASS/FAIL] - pm status matches yaml
add persists:      [PASS/FAIL] - New PR appears in yaml after add
timestamps:        [PASS/FAIL] - ISO timestamps generated
close removes:     [PASS/FAIL] - PR removed from yaml after close
roundtrip:         [PASS/FAIL] - yaml not corrupted through write cycle

OVERALL: [PASS/FAIL]
```
