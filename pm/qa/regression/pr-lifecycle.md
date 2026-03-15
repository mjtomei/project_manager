---
title: "PR Lifecycle: Add, Edit, List, Graph"
description: "Test core PR management commands: add, edit, select, list, graph, ready"
tags: [core, local, vanilla, github, containerized, uncontainerized]
---

## Setup

You are testing pm's core PR management commands. Work in the current directory
which has an initialized pm project.

## Test Steps

### 1. List PRs
```bash
pm pr list
```
Record the current PR count and statuses.

### 2. Add a PR
```bash
pm pr add "Test regression PR alpha"
```
Verify it prints a new PR ID (pr-XXXXXXX format).

### 3. Add another PR with dependencies
```bash
pm pr add "Test regression PR beta"
```
Note the second PR ID.

### 4. Edit the second PR to depend on the first
```bash
pm pr edit <second-pr-id> --depends-on <first-pr-id>
```
Verify the edit succeeds.

### 5. List PRs again
```bash
pm pr list
```
Verify both new PRs appear with correct titles and statuses (pending).

### 6. View dependency graph
```bash
pm pr graph
```
Verify the graph shows the dependency arrow from beta to alpha.

### 7. Check ready PRs
```bash
pm pr ready
```
Verify alpha is listed as ready (no unmet dependencies) and beta is NOT
listed (depends on alpha which is still pending).

### 8. Select a PR
```bash
pm pr select <first-pr-id>
```
Verify the active PR changed.

### 9. Clean up — close test PRs
```bash
pm pr close <second-pr-id> --force
pm pr close <first-pr-id> --force
```

## Expected Behavior

- `pm pr add` creates a PR with a unique ID and pending status
- `pm pr edit --depends-on` sets up dependency correctly
- `pm pr list` shows all PRs with titles and statuses
- `pm pr graph` renders a dependency tree
- `pm pr ready` filters to PRs with all dependencies met
- `pm pr select` changes the active PR cursor
- `pm pr close --force` removes PRs cleanly

## Reporting

```
TEST RESULTS
============
pr add (first):      [PASS/FAIL] - PR created with valid ID
pr add (second):     [PASS/FAIL] - Second PR created
pr edit deps:        [PASS/FAIL] - Dependency set correctly
pr list:             [PASS/FAIL] - Both PRs visible with correct info
pr graph:            [PASS/FAIL] - Dependency arrow rendered
pr ready:            [PASS/FAIL] - Only independent PR shown as ready
pr select:           [PASS/FAIL] - Active PR changed
pr close:            [PASS/FAIL] - Both PRs removed cleanly

OVERALL: [PASS/FAIL]
```
