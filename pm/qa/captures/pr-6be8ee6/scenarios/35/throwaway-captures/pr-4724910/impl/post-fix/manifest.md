---
pr: pr-4724910
recipe: pm/qa/artifacts/cli-recording.md
captured_at: 2026-05-12T23:12:47+00:00
title: Post-fix verification of last_index
description: Shows last_index returns 2 and xs[2]==30, no IndexError
---

## Commands

```
PYTHONPATH=/workspace/pm-test-1778627512 python3 /tmp/repro.py
```

## What this demonstrates

Post-fix `last_index([10,20,30])` returns 2 and `xs[2]` evaluates to 30
with no IndexError — the off-by-one symptom is gone.

## Files

- recording.cast — asciinema cast
- transcript.log — tee'd stdout/stderr
