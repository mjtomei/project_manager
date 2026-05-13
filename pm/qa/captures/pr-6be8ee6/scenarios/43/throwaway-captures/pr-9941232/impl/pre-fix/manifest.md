---
pr: pr-9941232
workdir: /home/pm/.pm/workdirs/pm-test-1778679491-bca6d7c8/pm-pr-9941232-fix-defect-da44b97a
captured_at: 2026-05-13
recipe: pm/qa/artifacts/cli-recording.md
---

## Commands

```
python3 buggy.py
```

## What this demonstrates

Pre-fix repro: running `python3 buggy.py` raises `AssertionError: add(2,3) returned -1`
because `add` does subtraction instead of addition. This is the failing state
the bug-fix PR exists to repair.

## Files

- `recording.cast` — asciinema replay of `python3 buggy.py` failing
- `transcript.log` — plain-text capture of the same run
