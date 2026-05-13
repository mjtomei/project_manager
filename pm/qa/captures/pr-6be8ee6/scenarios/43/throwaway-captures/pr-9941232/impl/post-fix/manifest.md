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

Post-fix verification: with `add` corrected to `a + b`, `python3 buggy.py`
prints `OK` and exits 0. Demonstrates the fix resolves the bug captured in
`../pre-fix/`.

## Files

- `recording.cast` — asciinema replay of `python3 buggy.py` succeeding
- `transcript.log` — plain-text capture of the same run
