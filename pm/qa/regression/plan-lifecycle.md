---
title: "Plan Lifecycle: Add, List, Load"
description: "Test plan management commands and plan-to-PR relationship"
tags: [core, local, vanilla, github, containerized, uncontainerized]
---

## Setup

Work in the current directory which has an initialized pm project.

## Test Steps

### 1. List existing plans
```bash
pm plan list
```
Record current plan count.

### 2. Check plan file structure
```bash
ls pm/plans/ 2>/dev/null || echo "No plans directory"
```

### 3. Verify plan-PR relationships
For each plan shown by `pm plan list`, check whether its associated PRs
exist in `pm pr list`. Verify the plan ID referenced by each PR matches.

### 4. Check plan deps
```bash
pm plan deps 2>/dev/null || echo "No plan deps command or no plans"
```
Verify it reports any dependency issues or confirms deps are clean.

### 5. List plans with details
```bash
pm plan list
```
Verify each plan shows: id, name, status, and associated PR count.

## Expected Behavior

- `pm plan list` shows all plans with status
- Plan files exist in pm/plans/ as markdown
- PRs reference their parent plan correctly
- `pm plan deps` validates dependency consistency

## Reporting

```
TEST RESULTS
============
plan list:         [PASS/FAIL] - Plans listed with correct info
plan files:        [PASS/FAIL] - Plan files exist in pm/plans/
plan-pr link:      [PASS/FAIL] - PRs correctly reference their plans
plan deps:         [PASS/FAIL] - Dependency check runs cleanly

OVERALL: [PASS/FAIL]
```
