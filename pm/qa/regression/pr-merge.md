---
title: "PR Merge: Status Transitions and Dependency Updates"
description: "Test pm pr merge status changes, dependency unblocking, and cleanup"
tags: [core, local, vanilla, github, containerized, uncontainerized]
---

## Setup

Work in the current directory which has an initialized pm project.

## Test Steps

### 1. Create a dependency chain for testing
```bash
pm pr add "Merge test base PR"
```
Record as PR_A.
```bash
pm pr add "Merge test dependent PR" --depends-on <PR_A>
```
Record as PR_B.

### 2. Verify dependency blocks readiness
```bash
pm pr ready
```
Confirm PR_A is listed as ready but PR_B is NOT (depends on unmerged PR_A).

### 3. Check merge --help
```bash
pm pr merge --help
```
Confirm it lists: `--resolve-window`, `--background`, `--transcript`,
`--companion`, `--propagation-only`.

### 4. Verify merge changes PR status
```bash
pm pr edit <PR_A> --status merged
pm pr list
```
Confirm PR_A shows as merged.

### 5. Check dependent PR is now unblocked
```bash
pm pr ready
```
PR_B should now appear as ready since its dependency (PR_A) is merged.

### 6. Verify graph reflects merged state
```bash
pm pr graph
```
Merged PRs should be indicated differently from pending ones.

### 7. Clean up
```bash
pm pr close <PR_B>
pm pr close <PR_A>
```

## Expected Behavior

- Merging a PR transitions its status to `merged`
- Dependent PRs become ready when their dependencies are merged
- `pm pr graph` reflects merged status visually
- `pm pr ready` correctly filters based on dependency status

## Reporting

```
TEST RESULTS
============
dep chain create:  [PASS/FAIL] - Two PRs with dependency created
readiness block:   [PASS/FAIL] - Dependent PR blocked before merge
merge --help:      [PASS/FAIL] - Help shows expected options
status change:     [PASS/FAIL] - PR status changed to merged
dep unblock:       [PASS/FAIL] - Dependent PR now ready
graph update:      [PASS/FAIL] - Graph shows merged state
cleanup:           [PASS/FAIL] - Test PRs removed

OVERALL: [PASS/FAIL]
```
