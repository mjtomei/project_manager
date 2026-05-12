---
pr: pr-6be8ee6
workdir: /workspace
captured_at: 2026-05-12
recipe: pm/qa/artifacts/cli-recording.md
---

## Commands

```
# steps 5-9 driven by /tmp/qa22-run.sh under asciinema:
asciinema rec --quiet --overwrite recording.cast -c 'bash /tmp/qa22-run.sh'

# Inside the script (each prefixed with `set -x`):
pm qa regression smoke                       # step 5 (no flag, exit 0)
pm qa regression smoke --file-prs            # step 6 (filing addendum)
pm qa regression smoke --file-bugs           # step 7 (hidden alias)
diff -u prompt-file-prs.txt prompt-file-bugs.txt   # step 7 (byte-identical)
pm qa regression --help | grep file-         # step 7 (--file-bugs hidden)
pm qa regression no-such-test                # step 8 (exit 1, no stub call)
tmux kill-server; pm qa regression smoke     # step 9 (exit 1, no stub call)
```

The `claude` binary on PATH was a stub (`/tmp/qa22-stub` →
`$STUB_DIR/claude`) that wrote each invocation's argv and last
positional (the assembled prompt) to `$PROMPTS_DIR`. The pm tmux
session used was `pm-pm-test-1778622668-29ae6d6e`, created from a
throwaway `pm init` project at `/tmp/pm-test-1778622668`.

## What this demonstrates

Scenario 22: the `pm qa regression` runner finds a test by id, exits
1 on unknown ids and when no pm tmux session is running, and the
assembled prompt carries the unified `## Filing Findings` addendum
when either `--file-prs` or the hidden `--file-bugs` alias is set.
The diff in the recording is empty (the script prints `IDENTICAL`),
confirming both flags emit a byte-identical prompt — the alias is
unified, not bugs-only. `pm qa regression --help` only surfaces
`--file-prs`; `--file-bugs` is `hidden=True`. The two early-exit
paths (unknown id, no tmux) print no prompt file and leave the stub
prompts dir empty (`stub-files-after:` lines emit nothing), proving
they `raise SystemExit(1)` before `launch_claude` runs.

The two captured prompts (`prompt-file-prs.txt`,
`prompt-file-bugs.txt`) are committed alongside the recording so a
reviewer can grep the `## Filing Findings` section directly and
re-run the byte diff without replaying the cast.

## Files

- `recording.cast` — asciinema recording of /tmp/qa22-run.sh driving steps 5–9.
- `transcript.log` — plain-text capture of the same run for grep/diff.
- `prompt-file-prs.txt` — prompt assembled by `pm qa regression smoke --file-prs`.
- `prompt-file-bugs.txt` — prompt assembled by `pm qa regression smoke --file-bugs`; byte-identical to the above.
- `pm-qa-list.txt` — `pm qa list` output from `$TEST_DIR` showing the smoke regression is discoverable.
- `prompt.md` — the scenario's QA prompt (left in place by the orchestrator; not produced by this capture).
