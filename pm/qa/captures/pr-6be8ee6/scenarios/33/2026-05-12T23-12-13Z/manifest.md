---
pr: pr-6be8ee6
workdir: /workspace
captured_at: 2026-05-12T23:12:13Z
recipe: pm/qa/artifacts/cli-recording.md
---

## Commands

```
pm init --backend local --no-import
EDITOR=true pm qa add-instruction my-inst
EDITOR=true pm qa add-regression my-reg
EDITOR=true pm qa add-artifact my-art
grep -E '^(title|description|tags):' pm/qa/{instructions/my-inst,regression/my-reg,artifacts/my-art}.md
EDITOR=true pm qa add-instruction my-inst   # refuse-clobber → rc=1
pm qa add foo                                # removed → rc=2
pm qa list
pm qa show my-art
EDITOR=true pm qa edit my-art                # rc=0
(cd /tmp && pm qa docs | head -5)            # works outside source tree
pm qa regression nonexistent-id              # rc=1
pm tui test                                  # removed → rc=2
```

## What this demonstrates

Scenario 33 covers the pm qa CLI surface for the artifacts category and
the rest of the new commands. The recording shows, in order:
add-instruction / add-regression / add-artifact each scaffolding a file
with `title:` + `description:` only (no `tags:` field); refuse-clobber
behaviour on the second add-instruction; the bare `pm qa add` subcommand
returning a Click "No such command" error; `pm qa list` rendering the
three labelled sections (Instructions / Regression Tests / Artifact
Recipes); `pm qa show my-art` resolving across categories without `-c`
and printing the artifact template body; `pm qa edit my-art` exiting
cleanly with EDITOR=true; `pm qa docs` working from a directory unrelated
to the source tree; `pm qa regression nonexistent-id` exiting non-zero
with the expected error lines; and `pm tui test` returning a Click "No
such command" error confirming the subcommand was removed.

Steps 10 (regression filing-addendum gating) and 11 (author-* prompt
contents) were verified out-of-recording by calling
`build_regression_test_prompt` and `qa_authoring.build_authoring_prompt`
directly and inspecting the strings — these paths require an actual
tmux session and a Claude launch, which the recording does not perform.
Both passed: `--file-prs`/`--file-bugs` toggle the `--plan bugs` and
`--plan improvements` addendum lines, and the author prompts embed the
packaged `qa_library.md` plus the resolved target path.

## Files

- `recording.cast` — asciinema cast of the in-recording CLI sequence above.
- `transcript.log` — plain-text version of the same run (load-bearing artifact).
