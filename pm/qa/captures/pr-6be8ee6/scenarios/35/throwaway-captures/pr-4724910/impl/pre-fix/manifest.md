---
pr: pr-4724910
recipe: pm/qa/artifacts/cli-recording.md
captured_at: 2026-05-12T23:12:28+00:00
title: Pre-fix repro of last_index off-by-one
description: Shows IndexError when xs[last_index(xs)] is evaluated on pre-fix code
---

## Commands

```
PYTHONPATH=/workspace/pm-test-1778627512 python3 /tmp/repro.py
```

(Driver script /tmp/repro.py imports buggy.last_index and indexes xs with it.)

## What this demonstrates

Pre-fix `last_index([10,20,30])` returns 3 (len of list), so `xs[3]`
raises IndexError — the deterministic off-by-one symptom that this PR fixes.

## Files

- recording.cast — asciinema cast of the command above
- transcript.log — tee'd stdout/stderr of the same run
