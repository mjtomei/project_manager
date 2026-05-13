---
pr: pr-9279294
workdir: /scratch/pm-test-1778707340
captured_at: 2026-05-13
recipe: pm/qa/artifacts/cli-recording.md
---

## Commands

```
python3 -c "from helper import last_index; xs=[10,20,30]; idx=last_index(xs); print(f'xs={xs}'); print(f'last_index returned: {idx}'); print(f'xs[idx]:', xs[idx] if idx < len(xs) else 'IndexError (BUG)')"
```

## What this demonstrates

Post-fix: `last_index([10,20,30])` returns 2, and `xs[2] == 30` resolves
without IndexError. Pair this with the pre-fix capture in
../pre-fix/manifest.md (which shows the IndexError marker).

## Files

- `recording.cast` — asciinema replay of the same repro script on the fixed code.
- `transcript.log` — plain-text capture.
