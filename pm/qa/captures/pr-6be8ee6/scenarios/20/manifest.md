---
pr: pr-6be8ee6
workdir: /workspace
captured_at: 2026-05-12
recipe: pm/qa/artifacts/cli-recording.md
---

## Commands

```
# Recorded as a single scripted bash run via:
#   tmux -L scaffold20 (no-TTY workaround)
#   asciinema rec --quiet -c 'bash /tmp/qa20-script.sh'
# Inside the script (working dir: a throwaway pm-initialized project):

pm qa add foo                                 # step 4 — removed legacy command
EDITOR=true pm qa add-instruction login-setup # step 5a
EDITOR=true pm qa add-regression nav-smoke    # step 5b
EDITOR=true pm qa add-artifact thing-record   # step 5c
cat pm/qa/instructions/login-setup.md         # step 6a
cat pm/qa/regression/nav-smoke.md             # step 6b
cat pm/qa/artifacts/thing-record.md           # step 6c
EDITOR=true pm qa add-instruction login-setup # step 7 — refuse-clobber
pm qa list                                    # step 8
pm qa show thing-record                       # step 9a — auto-detect
diff <(pm qa show thing-record) <(pm qa show thing-record -c artifacts) # 9b
EDITOR=true pm qa edit thing-record           # step 10
pm qa docs | head -1                          # step 11
pm qa docs | wc -l
```

## What this demonstrates

End-to-end exercise of the new `pm qa` CLI surface in PR pr-6be8ee6:

- The legacy `pm qa add` command is gone (Click exits 2 with
  "No such command 'add'.").
- The three new scaffold commands (`add-instruction`,
  `add-regression`, `add-artifact`) each create a file at the
  correct path, print `Created: <abs-path>`, and exit 0.
- The scaffolded frontmatter is exactly `title: <Title Cased>` +
  `description:` (no `tags:` field), and each body matches the
  category-specific template (instructions → Setup/Test
  Steps/Expected Behavior/Reporting; regression → "careful
  tester" preamble + Scenarios + Reporting; artifacts → When to
  use / What this recipe produces / Capture / Manifest format).
- Re-running an `add-*` command for an existing slug prints
  `Already exists: <path>` and exits 1.
- `pm qa list` shows all three categories in order (`Instructions`,
  `Regression Tests`, `Artifact Recipes`) with the correct entries
  and titles.
- `pm qa show` auto-detects the category for an artifact slug and
  produces byte-identical output to `pm qa show -c artifacts`.
- `pm qa edit` resolves the slug across categories (exit 0).
- `pm qa docs` prints the packaged reference doc (first line is
  `# pm QA library`, 342 lines total).

Captured via the no-TTY workaround documented in
`pm/qa/artifacts/cli-recording.md` (asciinema inside a tmux
scaffold socket); replay with `asciinema play recording.cast`.

## Files

- `recording.cast` — asciinema replay of the scripted bash run that
  exercises every CLI step in this scenario.
- `transcript.log` — plain-text capture (stdout+stderr) of the same
  run, suitable for grep/diff.
- `prompt.md` — original scenario prompt (already present).
