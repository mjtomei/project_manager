---
title: "Container Isolation: Status and Config"
description: "Test container status, enable/disable, and configuration commands"
tags: [containers, local, vanilla, github, containerized]
---

## Setup

Work in the current directory which has an initialized pm project.

## Test Steps

### 1. Check container status
```bash
pm container status
```
Verify it shows whether container mode is enabled/disabled, current config
(image, memory limit, CPU limit).

### 2. Check current setting
Record whether containers are currently enabled or disabled.

### 3. If containers disabled, test enable
```bash
pm container enable
pm container status
```
Verify status now shows enabled.

### 4. If containers were enabled, test disable/re-enable cycle
```bash
pm container disable
pm container status
pm container enable
pm container status
```
Verify status toggles correctly.

### 5. Check container config settings
```bash
pm container set memory_limit 4g
pm container status
```
Verify memory limit shows 4g.

### 6. Restore original memory limit
```bash
pm container set memory_limit 8g
```

### 7. Test cleanup command
```bash
pm container cleanup
```
Verify it runs without error (may report 0 containers cleaned).

### 8. Restore original container state
If containers were originally disabled:
```bash
pm container disable
```

## Expected Behavior

- `pm container status` shows current mode and config
- `pm container enable/disable` toggles mode
- `pm container set` updates specific config values
- `pm container cleanup` handles empty state gracefully

## Reporting

```
TEST RESULTS
============
container status:  [PASS/FAIL] - Status displayed correctly
enable/disable:    [PASS/FAIL] - Mode toggles correctly
config set:        [PASS/FAIL] - Config values updated
cleanup:           [PASS/FAIL] - Cleanup runs cleanly

OVERALL: [PASS/FAIL]
```
