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

Pre-fix: `last_index([10,20,30])` returns 3, which is out of bounds — should be 2.
The transcript shows the literal `IndexError (BUG)` marker emitted when
`idx >= len(xs)`. Cross-link: ../post-fix/manifest.md (post-fix capture
demonstrating the corrected return value).

## Files

- `recording.cast` — asciinema replay of the repro script.
- `transcript.log` — plain-text capture of the same run.
