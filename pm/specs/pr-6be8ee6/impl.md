# Implementation Spec — pr-6be8ee6

Original PR title: surface TUI QA repro instructions in bug-fix flow prompt.
Scope was extended (see PR note `note-a3ed531`) to add a generic
artifact-recipe category to `pm/qa/` and integrate it into both the
bug-fix flow and QA scenario prompts.

## Requirements

### A. Bug-fix flow prompt (the original ask, generalized)

1. **"Reproduce on pre-fix code" gate** — already in `_BUG_FIX_FLOW_BLOCK`
   from earlier commits. Keep.
2. **Surface `pm/qa/instructions/`** — sessions reproducing a bug should
   know that env-setup recipes (e.g. how to spin up a throwaway test
   environment for the project under test) may live there. One line,
   not project-specific.
3. **Surface `pm/qa/artifacts/`** — when an automated test isn't
   feasible, sessions should know to look here for recipes on capturing
   demonstrative artifacts (TUI/tmux recordings, command logs).

### B. New `pm/qa/artifacts/` category

The pm QA system already has three categories of markdown-with-frontmatter
files: `instructions/`, `regression/`, `mocks/`
(`pm_core/qa_instructions.py:25-43`). Add a fourth: `artifacts/`.

Files in `pm/qa/artifacts/` are *recipes* for capturing reviewable
evidence. Examples a project might write:
- `tmux-screen-recording.md` — `tmux pipe-pane` to a `.log`, plus
  `asciinema rec` for replay.
- `command-log.md` — `script(1)` wrapping a session.
- `before-after-screenshots.md` — for visual regressions.

The actual captures go in `pm/qa/captures/<pr-id>/` (convention the
recipes reference). A recipe must produce:
- The capture file(s) (recording, screenshot, log).
- A short manifest noting the workdir path the capture came from,
  the command(s) run, and the pre-fix/post-fix state.

### C. `qa_instructions.py` extensions

- `artifacts_dir(pm_root)` — mirrors existing `instructions_dir` etc.
- `list_artifacts(pm_root)` — mirrors `list_instructions`.
- `list_all` — include `"artifacts"` key.
- `instruction_summary_for_prompt` — render an `### Artifact Recipes`
  subsection alongside `### Instructions` when artifacts exist.
- `resolve_instruction_ref` — extend lookup to include the artifacts
  category so QA sessions can reference recipes by filename.

### D. QA scenario prompt integration

`instruction_summary_for_prompt` is called from `prompt_gen.py:1376`
and `:1550` for QA prompts. Extending the helper auto-surfaces the new
category. Add one prose sentence to the QA prompt body itself: "If a
scenario produces evidence a human reviewer will want to look at
(screen recording, command log), pick a matching recipe from Artifact
Recipes above and write the capture under `pm/qa/captures/<pr-id>/`."

### E. Starter recipe

Ship one starter recipe at `pm/qa/artifacts/tmux-screen-recording.md`
covering `tmux pipe-pane` for transcript capture and `asciinema rec`
for replayable recordings. The recipe is generic across projects (no
references to project-internal code paths).

## Implicit Requirements

- `artifacts_dir` should auto-create the directory like the others do.
- `list_all` consumers other than the prompt helper must keep working
  — check `qa_loop.py:467,581` and `cli/qa.py` callers.
- `resolve_instruction_ref` returning `("artifacts", filename)` must
  not break callers that switch on the category. Audit
  `qa_loop.py:467` for the call site behavior.
- Tests in `tests/` for any of the touched helpers must still pass.
- `pm/qa/captures/` is created on demand by recipes; no infra change
  needed in this PR.

## Ambiguities

- **Should artifacts also be referenced from `_BUG_FIX_REVIEW_BLOCK`?**
  Resolved: yes, one line — "if the PR has captures under
  `pm/qa/captures/<pr-id>/`, look at them as part of the review."
  Cheap and useful for outside reviewers.
- **Should the bug-fix prompt enumerate available artifact recipes
  inline (like the QA prompt does), or just point at the directory?**
  Resolved: just point at the directory. The bug-fix flow runs in
  `generate_prompt` which doesn't currently load QA library content,
  and adding that plumbing is more weight than the value justifies
  for a session that may or may not need a recipe at all.

## Edge Cases

- **No `pm/qa/artifacts/` directory yet** — `list_artifacts` returns
  `[]`; the prompt helper renders nothing for that subsection;
  bug-fix prompt still mentions the directory by path (it's a generic
  pointer, OK if empty).
- **Recipe references a tool not installed (e.g. asciinema)** — recipe
  responsibility, not framework responsibility. Recipes should note
  install commands.
- **Captures directory growing large in git** — out of scope here. A
  follow-up could add a `.gitattributes` LFS rule or a retention
  policy. Document the concern, don't solve it.
