---
title: "QA Instruction Library: List, Show, Add"
description: "Test QA instruction management commands"
tags: [core, local, vanilla, github, containerized, uncontainerized]
---

## Setup

Work in the current directory which has an initialized pm project.

## Test Steps

### 1. List all QA items
```bash
pm qa list
```
Verify it shows two categories: Instructions and Regression Tests.
Record the counts.

### 2. Show an instruction
Pick any instruction ID from the list and run:
```bash
pm qa show <instruction-id>
```
Verify it displays the title, description, path, and full body content.

### 3. Show a regression test
Pick any regression test ID from the list and run:
```bash
pm qa show <regression-id>
```
Verify it displays correctly with the category auto-detected.

### 4. Show with explicit category
```bash
pm qa show <regression-id> -c regression
```
Verify same result as auto-detection.

### 5. Show non-existent instruction
```bash
pm qa show nonexistent-id 2>&1
```
Verify it prints an error message and exits with non-zero status.

### 6. Verify instruction file format
Read one instruction file directly:
```bash
head -20 pm/qa/instructions/*.md 2>/dev/null || echo "No instructions"
head -20 pm/qa/regression/*.md 2>/dev/null | head -30
```
Verify files have YAML frontmatter with title, description, tags.

## Expected Behavior

- `pm qa list` categorizes instructions vs regression tests
- `pm qa show` auto-detects category when not specified
- Non-existent IDs produce clear error messages
- Instruction files follow the frontmatter format

## Reporting

```
TEST RESULTS
============
qa list:           [PASS/FAIL] - Both categories shown with correct counts
qa show (instr):   [PASS/FAIL] - Instruction displayed correctly
qa show (regr):    [PASS/FAIL] - Regression test displayed correctly
qa show (explicit):[PASS/FAIL] - Explicit category works
qa show (missing): [PASS/FAIL] - Error for non-existent ID
file format:       [PASS/FAIL] - Frontmatter format correct

OVERALL: [PASS/FAIL]
```
