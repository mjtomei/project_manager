# QA Spec: pr-6be8ee6 — Bug-fix flow surfaces TUI QA repro instructions

## Scope (what actually shipped)

What started as "reference `tui-manual-test.md` from the bug-fix prompt"
grew into a broader restructure of the pm QA library. The user-facing
behaviors that scenarios need to exercise:

1. **Rewritten bug-fix flow prompt** — `pm_core/bug_fix_prompts.py` now
   produces a 5-step flow (manual repro on pre-fix → failing test → fix
   → verify with test → verify manually). It interpolates the PR's
   local id into `pm/qa/captures/<pr-id>/impl/{pre-fix,post-fix}/` and
   tells the session to look at `pm/qa/instructions/` for env-setup
   recipes and `pm/qa/artifacts/` for capture recipes. The review
   checklist flags missing captures as **INPUT_REQUIRED** (not
   NEEDS_WORK).
2. **New `artifacts` category** — `pm/qa/artifacts/` joins
   `instructions/`, `regression/`, `mocks/` as a first-class QA dir.
   Ships with `tmux-screen-recording.md` and `cli-recording.md`.
3. **CLI rework on `pm qa`** —
   - `pm qa add` removed.
   - New: `pm qa add-instruction|add-regression|add-artifact <name>`
     (scaffold stub + `$EDITOR`).
   - New: `pm qa author-instruction|author-regression|author-artifact <name>`
     (launches a Claude session with `qa_library.md` as reference).
   - New: `pm qa docs` (prints the packaged reference doc).
   - New: `pm qa regression <test-id>` (replaces the removed
     `pm tui test`). Flag renamed to `--file-prs` (with hidden
     `--file-bugs` alias), and now files BOTH `--plan bugs` AND
     `--plan improvements`, not just bugs.
   - `pm qa list / show / edit` extended to the artifacts category.
4. **TUI changes** —
   - The QA pane (`q` key) renders three sections: Instructions,
     Regression Tests, Artifact Recipes. Status-bar counter sums all
     three.
   - The `a` key opens `QACreatePickerScreen` — a modal with a name
     input and a 6-option list (3 categories × 2 modes:
     author/scaffold). On submit, it launches the matching
     `pm qa {mode}-{category-suffix} <name>` in a pane.
   - Enter on a regression item launches via
     `build_regression_test_prompt` (unified prompt shared with
     `pm qa regression`).
5. **Frontmatter schema** — `qa_library.md` declares `title` and
   `description` required; `tags` is removed. The loader still
   tolerates missing values (no validation).
6. **Packaged reference doc** — `pm_core/docs/qa_library.md` is
   shipped via `pyproject.toml [tool.setuptools.package-data]` so
   `pm qa docs` works from any cwd after `pip install`.
7. **End-to-end QA + bug-fix flow integration** — the new captures
   layout (`pm/qa/captures/<pr-id>/{impl,scenarios}/...`), the
   restructured `qa_loop.py` (~640 lines changed, including the
   duplicate-verification fix in commit e8fe399 and the
   INPUT_REQUIRED-vs-NEEDS_WORK review-loop change), the
   `qa_finalize_prompt.py` wiring, and the new 5-step bug-fix flow
   are all designed to compose into one user-visible workflow:
   author a bug PR → bug-fix session produces pre-fix and post-fix
   captures → QA scenarios run against the fix and save under
   `scenarios/<n>/` → review loop accepts INPUT_REQUIRED when
   captures are missing → `qa_finalize` closes out. This integration
   needs at least one scenario that runs the whole pipeline against
   a tiny throwaway PR.

Out of scope (not exercised by these scenarios): none. Earlier
drafts of this spec carved off "the QA scenario runner internals,
the review-loop verifier, and `qa_finalize` wiring" as covered
elsewhere — but those are exactly the pieces this PR rewrote, and
their integration with the new captures layout and bug-fix prompt
is only exercised by an end-to-end dogfood run (see requirement 7
and the corresponding scenario below).

## Requirements (key behaviors)

### Bug-fix flow prompt (impl + review)
- For any PR with `plan == "bugs"` or `type == "bug"`, the impl prompt
  must include a "Bug Fix Flow" section with five numbered steps in
  the new order.
- Captures path must interpolate the PR's local id verbatim:
  `pm/qa/captures/<that-pr's-local-id>/impl/{pre-fix,post-fix}/`.
- Step 1 must instruct: reuse a valid pre-fix capture if present;
  otherwise reproduce against pre-fix code (mentions `git stash` /
  parent commit checkout); if it doesn't reproduce, check in with
  the user before continuing.
- Body must reference both `pm/qa/instructions/` (env-setup recipes)
  and `pm/qa/artifacts/` (capture recipes).
- Review prompt must include the review checklist that flags missing
  captures as **INPUT_REQUIRED**.

### CLI: `pm qa` family
- `pm qa add` is gone (CLI rejects it).
- `pm qa add-instruction X` / `add-regression X` / `add-artifact X`
  each create a file under the matching directory with a
  category-appropriate template, then open `$EDITOR`. Schema written:
  `title` and `description` only — no `tags:` field.
- `pm qa author-{instruction,regression,artifact} X` launches a Claude
  session (don't need to verify the session completes — just that the
  command resolves the target path, refuses to clobber, and the prompt
  embeds the packaged `qa_library.md`).
- `pm qa list` shows three sections: Instructions, Regression Tests,
  Artifact Recipes — each with counts.
- `pm qa show <id>` and `pm qa edit <id>` auto-detect across all
  three categories (and `-c artifacts` works explicitly).
- `pm qa docs` prints the packaged reference, works from a cwd
  outside the source tree, and exits 0.
- `pm qa regression <id>`:
  - exits non-zero with a sensible message if the id isn't found;
  - without `--file-prs`, the launched prompt has no filing addendum;
  - with `--file-prs` (or the hidden `--file-bugs` alias), the
    addendum tells the session to file under both `--plan bugs` and
    `--plan improvements`.

### CLI: removed surfaces
- `pm tui test` (and `--list`, `--file-bugs`, `--fix-bugs`) no longer
  exist. Running it surfaces a clear click error rather than executing.

### TUI: QA pane
- Pressing `q` opens a pane with three labeled sections:
  Instructions, Regression Tests, Artifact Recipes — even when one
  is empty (the section header still shows with `(0)`).
- The status-bar counter for the QA pane sums all three.
- Pressing `a` opens a modal that takes a name input and lets the
  user pick one of 6 (kind × mode) options. Submitting with a
  non-empty name launches the matching `pm qa {mode}-{kind} <name>`
  command in a pane (mode = `author` or `add`; kind suffix maps
  instructions→instruction, regression→regression,
  artifacts→artifact). Esc cancels with no side effect.
- Enter on a regression-section item launches a pane that runs the
  regression prompt (built via `build_regression_test_prompt`)
  including the captures section that points at
  `pm/qa/captures/regression/<test-id>/<timestamp>/`.

### Packaging
- After installing pm into a fresh venv (`./install.sh --local` from
  the pm repo), running `pm qa docs` from an unrelated directory
  prints the `qa_library.md` content with no missing-file error.

### End-to-end QA + bug-fix flow integration
- The next QA run MUST cover the whole pipeline against a throwaway
  pm project, exercising the integration between the pieces this PR
  rewrote. The planner MAY express this as one large scenario OR
  split it into several independent scenarios that can run in
  parallel — whichever fits the scenario-timeout budget better.
  Splitting is encouraged for parallelism; the only hard rule is
  that every checkpoint below is covered by *some* scenario in the
  next run.
- Required checkpoints (group as the planner sees fit; each group
  must be self-contained — every scenario sets up its own
  throwaway project, bug PR, and any precondition captures from
  scratch, no cross-scenario state):
  1. **Bug-fix session produces pre-fix + post-fix captures.**
     Create a `plan == bugs` PR with a deterministic, reproducible
     defect; drive the bug-fix flow (real `pm pr session <id>` or
     by manually following the 5-step prompt) until
     `pm/qa/captures/<pr-id>/impl/pre-fix/` and
     `…/impl/post-fix/` both exist with valid manifests + the
     committed fix passes its own failing test.
  2. **QA scenarios save under the new captures layout.** Run at
     least one `pm qa` scenario against the fix from checkpoint 1
     (or a freshly minted equivalent) and confirm captures land
     under `pm/qa/captures/<pr-id>/scenarios/<n>/` with manifest +
     recording + transcript per `tmux-screen-recording.md` /
     `cli-recording.md`.
  3. **Review-loop INPUT_REQUIRED gate.** Trigger the review loop
     on a bug PR with deliberately missing captures and confirm
     the verdict is **INPUT_REQUIRED** (not NEEDS_WORK); add the
     captures, re-run, and confirm it flips to PASS without an
     infinite review loop.
  4. **`qa_finalize` closes out cleanly.** Invoke whatever surface
     runs `qa_finalize_prompt.py` against a PR with valid captures
     and confirm it closes out without error.
  5. **Duplicate-verifier guard (e8fe399).** Drive a scenario to
     PASS, send a follow-up question to the scenario pane, and
     confirm the verifier is NOT spawned a second time on the
     stale idle prompt (i.e. `_last_scenario_hook_ts` is stamped
     after the follow-up).
- If the planner splits these checkpoints across scenarios, each
  scenario's STEPS must include the setup it needs (no implicit
  dependence on another scenario's captures or PR). Checkpoints 1
  and 2 share enough setup that bundling them is reasonable;
  checkpoints 3, 4, and 5 can each stand alone.
- These checkpoints are the integration test for everything else
  in this PR and must not be skipped on size grounds — split for
  parallelism rather than dropping any of them.

### Frontmatter resilience
- A QA file with no frontmatter, with the obsolete `tags:` field
  present, or with missing `description` does not crash:
  - `pm qa list` lists it (with empty values where missing);
  - `pm qa show <id>` prints the body;
  - the TUI QA pane renders the row.

## Setup

Most scenarios need a throwaway pm project. The shared shape:
- Follow `pm/qa/instructions/tui-manual-test.md` to set up a scratch
  project where `pm` is installed in an isolated venv.
- Edit `pm/project.yaml` (or use `pm pr add`) to create the PRs and
  plans each scenario needs.

The packaging scenario explicitly installs `pm` into a fresh venv via
`./install.sh --local` from the pm source checkout.

## Edge Cases / Failure Modes to Probe

- `pm qa add-instruction <name>` when the file already exists →
  exits 1 with "Already exists" (no clobber).
- `pm qa show <id>` for an id that lives in `artifacts/` →
  resolves without `-c artifacts`.
- `pm qa regression <id>` with no running pm tmux session →
  exits 1 with the "No pm tmux session" message.
- TUI `a` picker with empty name → submit is a no-op (modal stays
  open or quietly does nothing) rather than crashing.
- Bug-fix prompt for a non-bug PR (e.g. `plan == "features"`) →
  the Bug Fix Flow block is absent.
- `pm qa docs` after pip install but with no working directory pm
  project → still prints the doc.
- Frontmatter file with no `---` delimiters at all → loader treats
  whole file as body, doesn't raise.

## Pass/Fail Criteria

A scenario PASSES when every requirement listed in its STEPS produces
the documented behavior, the artifact capture is saved under
`pm/qa/captures/pr-6be8ee6/scenarios/<n>/`, and the captured evidence
visibly demonstrates the assertion (the agent didn't just claim
success). It FAILS if any step's observed behavior differs from the
spec, or if a stack trace, click "No such command", or `FileNotFoundError`
surfaces on a documented user action.

## Ambiguities (resolved)

- **`tags:` frontmatter** — qa_library.md says it's removed and not
  used, but the loader doesn't validate. Treat as: loader must
  tolerate it (no crash), but `pm qa add-*` templates must not
  write it. Scenarios assert both.
- **`--file-bugs` vs `--file-prs`** — the PR keeps `--file-bugs` as
  a hidden alias. Scenarios verify both flag names map to the same
  addendum (filing both bugs + improvements).
- **TUI picker on empty name** — the screen code has
  `if not name: return` in `on_input_submitted`. Treat "no-op,
  no crash" as the expected behavior; scenarios shouldn't insist on
  any particular feedback.

No **[UNRESOLVED]** items.

## Mocks

- **No Claude session mock needed for most scenarios.** The
  `pm qa author-*` commands launch Claude; scenarios should verify
  the *pre-launch* behavior (target path resolution, refuse-clobber,
  prompt construction by inspecting the launched command line or
  by mocking `pm_core.claude_launcher.launch_claude` to capture its
  prompt argument). Scenarios should NOT depend on a live Claude
  response.
- **`pm qa regression`** — same pattern: don't run Claude to
  completion. Either capture the assembled prompt (e.g. by setting
  up the regression to be launched in a pane and reading the pane
  scrollback) or have the launched session exit immediately (e.g.
  via a minimal regression file whose body is "echo done; exit"
  style — the assertion is about the runner's prompt assembly and
  exit handling, not Claude's behavior).
- **tmux** — scenarios that exercise the TUI use real tmux per
  `tui-manual-test.md`. No mocking.

If a scenario truly needs to mock `launch_claude`, declare it inline.
