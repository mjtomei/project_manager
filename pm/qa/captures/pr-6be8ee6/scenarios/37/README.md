# Scenario 37 captures

Scenario focus: packaged `qa_library.md` survives `./install.sh --local`;
`pm qa docs` works from arbitrary cwd; loader tolerates missing/no/legacy
frontmatter without crashing in `pm qa list`, `pm qa show`, and the TUI
QA pane.

## Files

- `step2-pm-qa-docs.txt` — `pm qa docs` run from `/tmp` (exit 0, doc body)
- `step3-package-data.txt` — proof the packaged `qa_library.md` is
  reachable via `import pm_core` (editable install: resolves to the
  source tree under `/workspace/pm_core/docs/`)
- `step7-qa-list.txt` — `pm qa list` exit 0, three sections render
- `step8-qa-show.txt` — `pm qa show` for each of the three edge-case
  files (no frontmatter / legacy `tags:` / missing `description:`)
- `step10-tui-qa-pane.txt` — `pm tui view` of the TUI QA pane showing
  all three sections populated, no traceback
- `step12-finalize-prompt-smoke.txt` — direct invocation of
  `build_qa_finalize_prompt` confirms the prompt builder runs without
  error (a full bug-PR QA-loop reproduction to drive the finalize pane
  end-to-end was out of scope for this scenario's packaging+frontmatter
  focus)
- `cli-recording/` — asciinema cast + transcript + manifest exercising
  the CLI surfaces above
