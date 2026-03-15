---
title: "PR Notes: Add, Edit, List, Delete"
description: "Test PR notes CRUD operations"
tags: [core, local, vanilla, github, containerized, uncontainerized]
---

## Setup

Work in the current directory which has an initialized pm project.

## Test Steps

### 1. Create a test PR
```bash
pm pr add "Notes test PR"
```
Note the PR ID.

### 2. Add a note
```bash
pm pr note add <pr-id> "First note for testing"
```
Verify it prints confirmation with a note ID.

### 3. Add a second note
```bash
pm pr note add <pr-id> "Second note with more detail"
```

### 4. List notes
```bash
pm pr note list <pr-id>
```
Verify both notes appear with correct text and timestamps.

### 5. Edit a note
```bash
pm pr note edit <pr-id> 1 "Updated first note"
```
Verify the edit succeeds.

### 6. List again to verify edit
```bash
pm pr note list <pr-id>
```
Verify note 1 now shows "Updated first note".

### 7. Delete a note
```bash
pm pr note delete <pr-id> 2
```

### 8. Verify deletion
```bash
pm pr note list <pr-id>
```
Verify only one note remains.

### 9. Clean up
```bash
pm pr close <pr-id> --force
```

## Reporting

```
TEST RESULTS
============
note add:    [PASS/FAIL] - Notes created with IDs
note list:   [PASS/FAIL] - Notes listed correctly
note edit:   [PASS/FAIL] - Note text updated
note delete: [PASS/FAIL] - Note removed cleanly

OVERALL: [PASS/FAIL]
```
