---
pr: pr-6be8ee6
workdir: /workspace
captured_at: 2026-05-13
recipe: pm/qa/artifacts/cli-recording.md
---

## Commands

Two recordings cover the 11 scenario steps. The first hung on a `pm session`
nested-tmux invocation inside the recording's tmux scaffold pane (step 10's
restart), so step 10–11 were re-recorded separately after restarting the
session from the outer shell. The hang was an artifact of running `pm
session` inside the recording pane — the feature itself works (steps 9 and
10 verified manually pre/post-recording).

Scripts driven:

```
# scen39-script.sh — steps 5,7,8,9 (recording.cast / transcript.log)
pm tui test ; pm tui test --file-bugs ; pm tui test --fix-bugs
pm qa regression nonexistent-id
pm qa regression demo-reg                       # no addendum
tmux kill-session ... ; pm qa regression demo-reg   # missing-tmux error

# scen39-finish.sh — steps 10–11 (recording-step10-11.cast / transcript-step10-11.log)
pm qa regression demo-reg --file-prs            # addendum present
pm qa regression demo-reg --file-bugs           # alias, byte-identical
diff /tmp/prompt-prs.txt /tmp/pm-qa-regression-prompt.txt
pm qa regression --help | grep --file-bugs      # hidden
pm qa regression --help | grep --file-prs       # documented
```

A claude-stub at the head of `$PATH` writes the prompt the launcher would
have handed to Claude to `/tmp/pm-qa-regression-prompt.txt`, so the
recordings include grep/diff probes against that captured prompt.

## What this demonstrates

- `pm tui test [--file-bugs|--fix-bugs]` is gone — click prints
  `Error: No such command 'test'` and exits rc=2 (no traceback).
- `pm qa regression nonexistent-id` exits rc=1 with the friendly
  "Unknown regression test" message and the `pm qa list` hint.
- The bare `pm qa regression demo-reg` prompt contains the regression
  scaffold (`## Session Context`, `## Captures`, captures path, title,
  body) but no filing addendum.
- With no pm tmux session, `pm qa regression demo-reg` exits rc=1 with
  `No pm tmux session found. Start one with 'pm session'.` (no traceback).
- Both `--file-prs` and the hidden `--file-bugs` alias produce a single
  unified filing addendum that names BOTH `--plan bugs` and
  `--plan improvements`. The two captured prompts are byte-identical
  (`diff` produced no output). `--file-bugs` is absent from `--help`;
  `--file-prs` is documented.

## Files

- `recording.cast` — asciinema cast of steps 5,7,8,9 driven by
  `/tmp/scen39-script.sh`. Replays via `asciinema play recording.cast`.
- `transcript.log` — `set -x` plain-text transcript for steps 5,7,8,9.
- `recording-step10-11.cast` — asciinema cast of steps 10–11 driven by
  `/tmp/scen39-finish.sh`.
- `transcript-step10-11.log` — plain-text transcript for steps 10–11,
  including the byte-identical `diff` and the `--help` hidden-flag check.
- `prompt.md` — original scenario prompt the orchestrator dropped in.
