# QA Spec — pr-6be8ee6

## 1. Requirements (key behaviors to exercise)

### Bug-fix flow & review prompts
- `pm_core.bug_fix_prompts._is_bug_pr` returns True for `plan == "bugs"` or
  `type == "bug"`; re-exported from `prompt_gen`.
- `_bug_fix_flow_block(pr)` interpolates `pr["id"]` into the captures path
  (`pm/qa/captures/<pr-id>/impl/{pre-fix,post-fix}/`), renders 5 numbered
  steps in order, names `pm/qa/instructions/` and `pm/qa/artifacts/`, and
  describes reuse semantics (skip steps with valid prior artifacts).
- `_bug_fix_review_block(pr)` flags missing captures as **INPUT_REQUIRED**
  (not NEEDS_WORK) and references the same captures path.
- `generate_prompt`/`generate_review_prompt` include the blocks only when
  `_is_bug_pr` is True.

### QA planner & scenarios
- `generate_qa_planner_prompt` adds an "Artifact Recipes" block and an
  `ARTIFACT:` field in the scenario template **only** when at least one
  recipe exists in `pm/qa/artifacts/`.
- `parse_qa_plan` extracts the `ARTIFACT` field, splits on commas, resolves
  via `qa_instructions.resolve_instruction_ref`, stores each as
  `artifacts/<file>.md` in `scenario.artifact_paths`. Unknown / non-artifact
  references are dropped with a warning.  `none/n/a/-` ⇒ empty list.
- `_install_artifact_files` copies each referenced recipe into
  `<scratch>/qa-artifacts/`, rewrites `scenario.artifact_paths` to the
  agent-visible absolute paths, and drops missing files.
- `generate_qa_child_prompt` renders the `## Artifact Recipe(s)` section,
  bulleted list of paths, captures dir
  (`pm/qa/captures/<pr-id>/scenarios/<n>/`), and the explicit
  `git add/commit/push` + rebase-on-conflict block.

### qa-finalize pane (synchronous)
- `build_qa_finalize_prompt` includes pr_id, branch, pr_workdir, scenario
  worktree triples, overall verdict, and demands `FINALIZE_DONE` /
  `FINALIZE_BLOCKED` on its own line.
- `_run_qa_finalize_pane` returns `None` when `workdir_path` is falsy or
  the named window is missing.
- `run_qa_sync` calls `_run_qa_finalize_pane` after scenarios and stores
  the result in `state.finalize_verdict`. `state.latest_output` includes
  `[finalize: <verdict>]` when set.
- `QALoopState.finalize_verdict` defaults to `None`.

### CLI surface
- `pm qa list` shows three sections: Instructions, Regression Tests,
  Artifact Recipes.
- `pm qa show <id>` resolves across all three categories; `--category` works.
- `pm qa add-instruction|add-regression|add-artifact <name>` scaffolds in
  the right directory using the right template (instruction has Setup/Test
  Steps; regression has Scenarios/Reporting; artifact has When to use /
  Manifest format) and opens `$EDITOR`. Errors when file exists.
- `pm qa author-instruction|-regression|-artifact` builds an authoring
  prompt and launches Claude (don't need to actually run the session — just
  verify command exists and refuses on existing file).
- `pm qa docs` prints the packaged `pm_core/docs/qa_library.md` content.
- `pm qa regression <id>` runs a regression test through `launch_claude`,
  surfaces "Unknown regression test" on missing id; `--file-prs` /
  `--file-bugs` (hidden alias) include the filing addendum in the prompt.
- `pm tui test` is **gone** — `pm tui --help` no longer mentions it; the
  command is unknown.

### TUI integration
- QA pane (`q` key) renders three labeled sections (Instructions, Regression
  Tests, Artifact Recipes) — even when one category is empty (header still
  shows count).
- Status-bar QA counter includes artifacts.
- `a` key in the QA pane pushes `QACreatePickerScreen` (modal) — does NOT
  hardcode `pm qa add-instruction new-instruction`.
- TUI Enter on a regression item launches via `build_regression_test_prompt`.

### Packaging
- `pyproject.toml` includes `pm_core/docs/*.md` under
  `[tool.setuptools.package-data]`. After `pip install`, `pm qa docs`
  prints the doc content from the installed package.

## 2. Setup

- A throwaway pm project (per `tui-manual-test.md`) is the standard vehicle
  for CLI- and TUI-driven scenarios.
- Pure-Python scenarios (prompt generation, parse_qa_plan, finalize wiring)
  can run from the workdir clone with `python3 -c …` and pytest, no project
  needed beyond the source tree.
- `./install.sh --local` if `pm` is missing in the container.

## 3. Edge cases

- Bug-fix prompt: PR with `plan == "improvements"` does **not** get the
  block (negative test).
- `parse_qa_plan`: ARTIFACT line with mixed valid + bogus filenames keeps
  the valid ones, drops bogus with a warning. Multiple recipes via comma.
  ARTIFACT pointing at an `instructions/` filename (wrong category) is
  ignored. ARTIFACT in scenario steps' free text doesn't get re-parsed.
- `_install_artifact_files`: when a recipe path resolves to a file that
  doesn't exist on disk, it's dropped silently without raising.
- Finalize: `_run_qa_finalize_pane` returns None for empty workdir; the
  exception path is swallowed in `run_qa_sync` and doesn't break the loop.
- `pm qa show <id>` with a name that exists in two categories (artifact +
  instruction with same stem) — auto-detect picks the first match in
  `_QA_LIST_CATEGORIES` order (instructions wins).
- `pm qa list` with empty `pm/qa/artifacts/` still renders the section
  header with `(0)` count (mkdir-on-demand via `artifacts_dir`).

## 4. Pass/Fail criteria

- **PASS**: every behavior in §1 demonstrably matches expectations on a
  real run / real prompt output.
- **FAIL**: any of:
  - Bug-fix prompt missing a step, missing the artifacts/instructions
    pointer, or wrong captures path.
  - QA planner prompt missing the artifact block when recipes exist, or
    showing it when none exist.
  - `parse_qa_plan` mis-parsing ARTIFACT (e.g. swallows STEPS).
  - `pm qa list/show/docs/add-*/regression` raises or prints wrong content.
  - `pm tui test` still works.
  - QA pane missing the artifacts section, or `a` launching the old
    hardcoded command.
  - `state.finalize_verdict` not populated (or `latest_output` lacks the
    suffix) on a sync run.

## 5. Ambiguities (resolved)

- **Captures committed to git in this PR**: yes — repo already has them
  under `pm/qa/captures/pr-6be8ee6/impl/`. No special handling needed in QA.
- **Auto-detect ordering for `pm qa show`**: instructions → regression →
  artifacts (per `_QA_LIST_CATEGORIES`). Documented.
- **Finalize pane when running with `run_in_background`**: PR notes only
  guarantee `run_qa_sync` blocks. Async path (`run_qa`) is out of scope —
  spec covers sync only.
- **Real Claude session for finalize / authoring tests**: scenarios verify
  the prompt-builder and wiring, not the Claude conversation. Exercising
  the actual session is out of scope (would require live Anthropic
  credentials and minutes of runtime per scenario).

## 6. Mocks

No external dependencies need mocking beyond what each scenario sets up
itself:

- **Claude session launches** (`launch_claude`, `_run_qa_finalize_pane`)
  are not exercised end-to-end. Scenarios verify prompt content + wiring
  by calling builders directly or by running `pm qa regression` /
  `pm qa author-*` and observing that they reach the launch step (then
  killing the resulting pane / process). Do **not** wait for a Claude
  verdict.
- **tmux** is used for the TUI scenario; that's a real tmux session
  inside the throwaway project, no mock.
- **git push** in worker prompts is *describe-only* (we verify the prompt
  text contains the right `git add/commit/push` lines); no real network.
- **`asciinema` / capture tooling** is not invoked by these tests.
