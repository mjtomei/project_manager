---
pr: pr-6be8ee6
workdir: /workspace
captured_at: 2026-05-12
recipe: pm/qa/artifacts/cli-recording.md
---

## Commands

```
bash /tmp/scenario26-repro.sh
```

The repro script (saved at /tmp/scenario26-repro.sh during the run)
exercises the full scenario in one pass:

1. Activate /tmp/pm-venv with editable /workspace install (PYTHONPATH=/workspace).
2. `mkdir` a throwaway TEST_DIR, `git init`, `pm init --backend local --no-import`.
3. `EDITOR=true` then run `pm qa add-instruction repro-foo`,
   `pm qa add-regression check-bar`, `pm qa add-artifact capture-baz`.
4. Print each scaffolded file's head + assert title/description present,
   tags absent.
5. Swap EDITOR to a logging shim (`/tmp/myeditor.sh`) and run
   `pm qa add-instruction edit-probe`; cat `/tmp/editor.log` to prove
   the subprocess invocation happened.
6. Re-run each of the three add commands with the existing name —
   assert exit=1 and `Already exists:` on stderr; sha256 of the
   instruction file unchanged.
7. `pm qa add` — assert click prints `No such command 'add'.` and exits 2.

## What this demonstrates

Scenario 26 verifies the `pm qa add-{instruction,regression,artifact}`
scaffolds. Playback shows:

- Each `Created:` line points to the correct category directory
  (`pm/qa/instructions/`, `pm/qa/regression/`, `pm/qa/artifacts/`).
- Each scaffolded file's frontmatter contains `title:` (built from
  the name via `replace("-", " ").title()`) and `description:` and
  has no `tags:` key. The OK-title / OK-description / OK-no-tags
  echoes are the assertions.
- `EDITOR_INVOKED:` line in the transcript proves
  `subprocess.run([editor, filepath])` ran the shim with the new
  file path as argv[1].
- Three `Already exists:` lines followed by `exit=1` for each category
  prove the clobber refusal on all three add-* commands. The
  OK-content-unchanged echo confirms sha256 is byte-identical
  pre and post failed clobber.
- `Error: No such command 'add'.` followed by `exit=2` proves the bare
  `pm qa add` is not a click command (replaced by the three add-*
  variants).

## Files

- `recording.cast` — asciinema replay of the repro script run inside
  a scaffold tmux pane (no-TTY workaround per cli-recording.md).
- `transcript.log` — plain-text run of the same script (`set -x`
  echoes each command; load-bearing artifact for grep/diff).
- `manifest.md` — this file.
