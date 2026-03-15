---
title: "PR Dependencies and Topological Ordering"
description: "Test dependency resolution, cycle detection, and topological sort"
tags: [core, local, vanilla, github, containerized, uncontainerized]
---

## Setup

Work in the current directory which has an initialized pm project.

## Test Steps

### 1. Create a chain of PRs
```bash
pm pr add "Dep test: base layer"
pm pr add "Dep test: middle layer"
pm pr add "Dep test: top layer"
```
Record all three PR IDs (call them A, B, C).

### 2. Set up linear dependency chain
```bash
pm pr edit <B> --depends-on <A>
pm pr edit <C> --depends-on <B>
```

### 3. Verify graph shows chain
```bash
pm pr graph
```
Verify the graph shows C -> B -> A (or equivalent visual).

### 4. Check ready PRs
```bash
pm pr ready
```
Only A should be ready (B depends on A, C depends on B).

### 5. Test cycle detection — add circular dep
```bash
pm pr edit <A> --depends-on <C>
```
This should either be rejected with a cycle error, or if accepted, verify
that `pm pr graph` or `pm pr ready` detects the cycle.

### 6. Remove the cycle if it was accepted
```bash
pm pr edit <A> --depends-on ""
```

### 7. Create a diamond dependency
```bash
pm pr add "Dep test: branch"
pm pr edit <D> --depends-on <A>
pm pr edit <C> --depends-on <D>
```
Now C depends on both B and D, both depend on A.

### 8. Verify diamond in graph
```bash
pm pr graph
```

### 9. Clean up
```bash
pm pr close <C> --force
pm pr close <D> --force
pm pr close <B> --force
pm pr close <A> --force
```

## Reporting

```
TEST RESULTS
============
chain setup:       [PASS/FAIL] - Linear A->B->C deps created
graph render:      [PASS/FAIL] - Graph shows correct structure
ready filter:      [PASS/FAIL] - Only root PR shown as ready
cycle detection:   [PASS/FAIL] - Circular dependency handled
diamond deps:      [PASS/FAIL] - Diamond structure rendered correctly

OVERALL: [PASS/FAIL]
```
