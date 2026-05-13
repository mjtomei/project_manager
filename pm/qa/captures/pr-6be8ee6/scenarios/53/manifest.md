---
pr: pr-6be8ee6
workdir: /scratch/cap53
captured_at: 2026-05-13
recipe: pm/qa/artifacts/cli-recording.md
---

## Commands

```
# fresh project
git init -q && git commit --allow-empty -q -m init && pm init

# three add-* commands
EDITOR=true pm qa add-instruction demo-inst
EDITOR=true pm qa add-regression  demo-reg
EDITOR=true pm qa add-artifact    demo-art

# frontmatter sanity (title present, description present, no tags)
head -5 pm/qa/instructions/demo-inst.md pm/qa/regression/demo-reg.md pm/qa/artifacts/demo-art.md

# refuse-clobber
EDITOR=true pm qa add-instruction demo-inst   # -> Already exists, exit 1

# list (three labeled sections, in order)
pm qa list

# show with category auto-detect (no -c)
pm qa show demo-art

# author-artifact end-to-end via a claude shim on PATH
PATH=/scratch/cap53/shimbin:$PATH EDITOR=true pm qa author-artifact demo-art-2
# refuse-clobber for author-* after manual create (shim NOT invoked second time)
echo manual > pm/qa/artifacts/demo-art-2.md
PATH=/scratch/cap53/shimbin:$PATH EDITOR=true pm qa author-artifact demo-art-2

# legacy commands removed
pm qa add        # -> click: Error: No such command 'add'.   exit 2
pm tui test      # -> click: Error: No such command 'test'.  exit 2
```

## What this demonstrates

End-to-end exercise of the new pm qa CLI surface for the three
categories (instructions / regression / artifacts):

- `add-instruction|add-regression|add-artifact` each scaffold the
  right file under `pm/qa/<category>/`, print `Created: <path>`, and
  the scaffolded file's YAML frontmatter has `title:` + `description:`
  with **no** `tags:` line.
- Re-running `add-*` against an existing file exits non-zero with
  `Already exists: <path>` and does not mutate the file.
- `pm qa list` renders three labeled sections in the expected order:
  `Instructions (N):`, `Regression Tests (N):`, `Artifact Recipes (N):`.
- `pm qa show demo-art` resolves the category automatically (no `-c`)
  and prints `# Demo Art`, the `[<path>/pm/qa/artifacts/demo-art.md]`
  line, then the body.
- `pm qa author-artifact` drives the real `launch_claude` codepath
  (the shim's PATH wins over the system `claude`) and feeds it the
  prompt produced by `qa_authoring.build_authoring_prompt`. The
  separate `claude-shim.log` capture in the scenario workdir (not
  committed; ephemeral to the run) showed the prompt began with
  `Work with the user to author a new artifact recipe …` targeting
  `pm/qa/artifacts/demo-art-2.md` and embedded the packaged QA
  library doc (heading `## Reference: pm QA library` present, body
  of `pm_core/docs/qa_library.md` follows).
- After manually creating `demo-art-2.md`, the second
  `author-artifact` invocation exits non-zero with `Already exists:`
  and does not invoke the Claude shim again (shim log absent).
- The legacy `pm qa add` and `pm tui test` commands are unregistered
  — click reports `No such command 'add'.` and `No such command
  'test'.` respectively.

## Files

- `recording.cast` — asciinema replay of the full driver script
  (`bash /scratch/scenario-53-capture.sh`), recorded via the no-TTY
  tmux scaffold workaround.
- `transcript.log` — plain-text capture of the same pane; matches
  the cast and is the grep-friendly artifact for reviewers without
  asciinema.
- `manifest.md` — this file.
