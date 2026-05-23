# Implementation Spec — pr-6be8ee6

## Scope

Original ask (PR description): surface the existing TUI QA repro
instructions in the bug-fix flow prompt and add a "did you reproduce
on pre-fix code?" gate. Scope grew during implementation (PR notes
`note-a3ed531`, `note-fd27d87`) into a broader QA-library overhaul.
This spec reflects what shipped.

## Requirements

### A. Bug-fix flow prompt

Restructured from 3 steps to 5 in `pm_core/bug_fix_prompts.py`
(extracted from `prompt_gen.py`):

1. Manual repro on pre-fix code (with already-committed-fix path:
   stash uncommitted, or check out parent / revert fix files
   temporarily, then capture).
2. Write a failing test (skipped with a PR note when genuinely
   untestable).
3. Fix (skipped if a working fix already exists and this session has
   no reason to change it).
4. Verify with the test.
5. Verify manually; produce a post-fix capture if none exists yet or
   if this session changed the fix.

Reuse semantics throughout: each step skips when a valid prior
artifact satisfies it.

Surfaces `pm/qa/instructions/` (env-setup recipes) and
`pm/qa/artifacts/` (capture recipes) by directory, with captures
landing under `pm/qa/captures/<pr-id>/impl/{pre-fix,post-fix}/[<short-name>/]`.

### B. Bug-fix review checklist

Pre-fix and post-fix captures expected. **Missing captures →
`INPUT_REQUIRED`, not `NEEDS_WORK`** — the review loop can't create
captures, so NEEDS_WORK would loop forever. Failing-then-passing test
also expected unless skipped via a PR note.

### C. New `pm/qa/artifacts/` category

Recipes for capturing concrete evidence. Files at
`pm/qa/artifacts/<id>.md`, same frontmatter schema as instructions.

`pm_core/qa_instructions.py` extended:
- `artifacts_dir`, `list_artifacts`, `list_all["artifacts"]`.
- `get_instruction(... category="artifacts")`.
- `resolve_instruction_ref` includes the artifacts category.
- `instruction_summary_for_prompt` renders an `### Artifact Recipes`
  subsection when recipes exist.

Two starter recipes ship in this repo:
- `tmux-screen-recording.md` — `tmux pipe-pane` transcript +
  `asciinema rec` cast, with a no-TTY workaround for environments
  without a live terminal (run asciinema inside a tmux pane via a
  separate socket).
- `cli-recording.md` — asciinema variants for one-off / manual /
  scripted CLI captures.

### D. Captures layout

```
pm/qa/captures/
├── <pr-id>/                  # captures bound to a PR
│   ├── impl/{pre-fix,post-fix}/[<short-name>/]
│   └── scenarios/<n>/
└── regression/               # captures from regression tests (no PR)
    └── <test-id>/<run-timestamp>/
```

Each capture dir holds a recording + (optional) transcript +
`manifest.md` (frontmatter: `pr` / `workdir` / `captured_at` /
`recipe`; body: `## Commands` and `## What this demonstrates`).
Captures are checked into git; large-file storage strategy (e.g.
`git-lfs`) is deferred.

### E. CLI surfaces

New under `pm qa`:
- `add-instruction` / `add-regression` / `add-artifact <name>` —
  scaffold a stub and open `$EDITOR`.
- `author-instruction` / `author-regression` / `author-artifact <name>` —
  launch a guided Claude session that loads the packaged reference
  doc and interviews the author. Implementation in
  `pm_core/qa_authoring.py`.
- `docs` — print the packaged reference doc.
- `regression <test-id>` — run a regression test (replaces the old
  `pm tui test`). Flags: `--session/-s`, `--file-prs` (hidden alias
  `--file-bugs`).

Extended:
- `list` / `show` / `edit` cover the artifacts category alongside
  instructions and regression.

Removed:
- `pm qa add` (replaced by the three `add-*` commands).
- `pm tui test` (moved to `pm qa regression`).
- `pm tui test --fix-bugs` (regression tests don't fix bugs;
  fixes go through a normal bug-fix PR session).

`--file-prs` files PRs for both bugs (`--plan bugs`) and improvements
(`--plan improvements`). Old `--file-bugs` kept as a hidden alias for
backward compat.

Top-level `pm` help (`pm_core/cli/__init__.py`) updated to list the
new commands.

### F. TUI integration

QA pane (`q` keybinding):
- Renders three categories inline: Instructions, Regression Tests,
  Artifact Recipes (sourced from `qa_instructions.list_all`). Mocks
  remain in their own surface via `pm qa mocks`.
- Status-bar counter includes artifact count.
- `a` keybinding now opens `QACreatePickerScreen`
  (`pm_core/tui/screens.py`) — a small modal asking for a name +
  picking kind (instruction/regression/artifact) and mode (guided
  author-* vs scaffold add-*). Replaces the prior hardcoded
  `pm qa add-instruction new-instruction`.

### G. Packaged reference doc

`pm_core/docs/qa_library.md` ships with the `pm` package via
`[tool.setuptools.package-data]` in `pyproject.toml`, so it's
available regardless of which project pm is run against. It documents:
- The four `pm/qa/*` directories and what each is for.
- Frontmatter schema (title and description required).
- Body conventions per category, with a minimal example each.
- Captures layout and manifest convention.
- Mocks (shared markdown contracts; CLI surface).
- Surface-by-surface table of where each thing is read.
- Authoring tips.

Authoring entry-point section near the top points at the six
`add-*` / `author-*` commands. Forward-looking `[!CAUTION]` callout
in the Regression tests section flags that the section describes
post-`pr-7d5d036` runner behavior.

README links to the doc as a feature bullet ("QA library").

### H. Regression runner unification

`pm_core/regression_prompts.py:build_regression_test_prompt(...)` is
the single source of truth for the regression-test prompt. Both
launch paths use it:
- `pm qa regression <id>` (CLI, in `cli/qa.py`).
- `pane_ops.launch_qa_item` (TUI Enter on a regression item).

Prompt structure: Session Context (drives the running pm session),
Captures (where artifacts go and that they should be committed), the
test body, optional Filing Findings addendum. Filing addendum covers
bugs (`--plan bugs`) and improvements (`--plan improvements`); allows
appending notes to existing PRs to dedup; carries the
"verdict-vs-filing" separation reminder.

### I. Prompt updates that surface the new pieces

- Bug-fix flow points sessions at `pm/qa/instructions/` and
  `pm/qa/artifacts/`.
- QA planner prompt: conditional artifact-recipes block when at least
  one recipe exists; defaults to producing a capture for any scenario
  whose value is showing behavior end-to-end.
- Scenario 0 prompt: kind-aware library prose ("instructions and
  artifact recipes" only when recipes exist).
- Bug-fix review checklist: surface for missing captures (INPUT_REQUIRED).

## Implicit Requirements

- `prompt_gen._is_bug_pr` is re-exported from `prompt_gen.py` so
  existing call sites and tests keep working after the move to
  `bug_fix_prompts.py`.
- The packaged `qa_library.md` is reachable after `pip install`
  (verified via `pm qa docs`).
- Both regression launch paths (CLI and TUI) produce identical
  prompts (covered by `tests/test_regression_prompts.py`).
- `qa_authoring.build_authoring_prompt` raises on unknown category
  (`instructions` / `regression` / `artifacts` only).

## Resolved ambiguities

- **GH PR number for capture dirs.** Tried briefly (would mirror tmux
  window naming); reverted because `gh_pr_number` propagation through
  `project.yaml` is unreliable. Captures use the local `pr["id"]`.
- **Markdown mocks library (`pm/qa/mocks/`).** Kept in place for this
  PR. Retirement plan: a code-level mock library lives where
  `FakeClaudeSession` is implemented (PR `pr-abcf70f`); the markdown
  contracts and the `pm qa mocks` CLI group are slated for removal as
  part of that PR. Note added to `pr-abcf70f`.
- **Containment model for the regression runner.** Pinned in a note
  on `pr-7d5d036` (`note-a870561`): bug PRs and captures are
  intentional outputs that escape the ephemeral env; everything else
  is contained. Network is allowed by default.
- **Reviewer-only framing for artifacts.** Dropped throughout. New
  framing: artifacts confirm behavior unequivocally, consumable by
  humans (replay/read) and downstream agents (parse/diff).
- **`--file-bugs` flag name.** Renamed to `--file-prs` (the addendum
  files improvements too); old name kept as a hidden Click alias.

## Captures committed in this PR

Two dogfooding artifacts under `pm/qa/captures/pr-6be8ee6/impl/`:
- `tui-walkthrough/` — transcript-only path (asciinema not installed
  when first run).
- `tui-walkthrough-v3/` — real asciinema cast via the no-TTY
  workaround the recipe documents (scaffold tmux on a separate
  socket, run `asciinema rec` inside a pane wrapping
  `tmux -L default attach -t <pm-session>`).

Names and layout fit the convention (`<pr-id>/impl/<short-name>/`)
even though neither phase is `pre-fix/`/`post-fix/` — these are
walkthroughs, not bug-fix evidence.

## Bug PRs filed during the work

- **`pr-7d5d036`** — regression runner hardcodes "testing against pm
  tmux session" and bails without a pm session. Wrong for containers
  and for tests that shouldn't pollute the user's live session.
  Containment-model note (`note-a870561`) and removal-reminder for
  the doc's `[!CAUTION]` callout (`note-7f64d92`).
- **`pr-3d1055c`** — older merged watcher prompts in `prompt_gen.py`
  (and `improvement_fix_impl_watcher.py`) reference `--plan ux`, but
  the project plan is named `improvements`. Improvement-fix pipeline
  silently broken. Mechanical search-and-replace.
- **`pr-f4dc8a2`** — QA library auditor: scan a project and suggest
  fills for missing instructions / regression tests / artifact
  recipes / mocks. Depends on this PR + `pr-7d5d036`.
- **`pr-abcf70f` (already in_review)** — note added urging that PR to
  establish a code-level mock library (housing FakeClaudeSession) and
  retire `pm/qa/mocks/` + the `pm qa mocks` CLI group.

## Edge Cases

- **No `pm/qa/artifacts/` recipes yet.** Prompt helper omits the
  subsection; QA planner prompt skips its artifact-recipes prose;
  bug-fix prompt still mentions the directory by path.
- **PR switched non-bug → bug after a fix is committed.** Step 1
  reverts the committed fix temporarily for the pre-fix capture; step
  5 captures post-fix when none exists yet, regardless of whether
  this session changed the fix.
- **Frontmatter missing `title` / `description`.** Loader tolerates
  (no validation step in this PR; doc declares them required).

## Out of scope (explicitly)

- Code-level mock library and retirement of `pm/qa/mocks/` (deferred
  to `pr-abcf70f`).
- Regression runner isolation rewrite (deferred to `pr-7d5d036`).
- `--plan ux` → `--plan improvements` renames in older watcher
  prompts (deferred to `pr-3d1055c`).
- QA library auditor feature (deferred to `pr-f4dc8a2`).
- GH PR number resolution for capture paths (tried, reverted).
- Capture pruning policies / `git-lfs` for large recordings.
- Network containment for the regression runner.
