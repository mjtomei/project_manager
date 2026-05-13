You are running QA scenario 51: "Frontmatter resilience across CLI and TUI"

## Context

- **PR**: pr-6be8ee6 — "Bug-fix flow: surface TUI QA repro instructions in session prompt"
- **Branch**: pm/pr-6be8ee6-bug-fix-flow-surface-tui-qa-repro-instructions-in-
- **Base branch**: master
- **Your workdir** (isolated clone): /workspace
- **Scratch dir** (throwaway test projects): /scratch
- **PR workdir** (canonical source): /home/matt/.pm/workdirs/project-manager-828c8d0a/pm-pr-6be8ee6-bug-fix-flow-surface-tui-qa-repro-in-e802a472

## PR Notes
- scope: extended to add pm/qa/artifacts/ category (recipes for capturing TUI/tmux screen recordings + command logs) and integrate it into both the bug-fix flow prompt and QA scenario prompts. Bug fix: surface pm/qa/instructions/ as a place to look for env-setup recipes when reproducing, and pm/qa/artifacts/ for capture recipes when an automated test is not feasible. QA: surface artifact recipes alongside mocks/instructions so QA sessions know how to produce reviewable evidence. (2026-05-05T12:42:08Z)
- QA notes for things added beyond the original description:

## CLI surface changes

- New: `pm qa add-instruction|add-regression|add-artifact <name>` (scaffold + $EDITOR), `pm qa author-instruction|author-regression|author-artifact <name>` (Claude-driven), `pm qa docs` (prints the packaged reference doc).
- Removed: `pm qa add` (replaced by the three add-* commands). Also removed: `pm tui test --fix-bugs` flag (regression tests are read-only-ish; fixes belong in a bug-fix PR session).
- Extended: `pm qa list / show / edit` now cover the new artifacts category alongside instructions and regression.
- Behavior change: `pm tui test --file-bugs` now files BOTH bugs (`--plan bugs`) and improvements (`--plan ux`), not just bugs. The flag name is unchanged for now but the addendum is unified.

## TUI changes

- The QA pane (`q` key) renders a third section "Artifact Recipes" sourced from pm/qa/artifacts/. Status-bar counter includes artifacts.
- The `a` key in the QA pane no longer hardcodes `pm qa add-instruction new-instruction`. It now opens a small modal picker (QACreatePickerScreen) asking for name + kind (instruction/regression/artifact) + mode (guided author-* vs scaffold add-*).
- TUI Enter on a regression item still launches via `launch_qa_item` but now goes through `build_regression_test_prompt`; behavior should match prior runs except that the filing addendum is the unified one.

## New on-disk surfaces

- `pm/qa/artifacts/` — new directory category. Two recipes ship: `tmux-screen-recording.md`, `cli-recording.md`.
- `pm/qa/captures/<pr-id>/impl/{pre-fix,post-fix}/` and `pm/qa/captures/<pr-id>/scenarios/<n>/` — capture layout consumed by the bug-fix flow and QA scenario prompts.
- `pm/qa/captures/regression/<test-id>/<timestamp>/` — capture layout for regression tests (no PR scope).
- `pm_core/docs/qa_library.md` — packaged reference doc shipped via setuptools.package-data; readable by `pm qa docs` regardless of the project pm is run against.

## Bug-fix flow prompt: behavior changes

- Restructured from 3 steps to 5: manual repro on pre-fix → failing test → fix → verify with test → verify manually. Steps now reuse prior-session artifacts when valid, skip re-implementing fixes that are already committed, and only produce a fresh post-fix capture when this session changed the fix.
- Step 1 now handles already-committed fixes: stash uncommitted, or checkout parent / revert files temporarily for committed fixes.
- Bug-fix review checklist now flags missing captures as INPUT_REQUIRED (not NEEDS_WORK) to avoid infinite review loops.

## Forward-looking docs

- Regression tests section in `pm_core/docs/qa_library.md` carries a `> [!CAUTION]` callout flagging that the section describes post-pr-7d5d036 behavior. Until that PR lands, the runner still hardcodes "testing against pm tmux session". A note on pr-7d5d036 reminds the implementer to drop the callout when their fix lands.
- Containment model for the runner rewrite is pinned in pr-7d5d036 (note-a870561): captures and bug PRs leak to master; everything else stays in the ephemeral env.

## Cross-PR notes filed

- pr-7d5d036: bug PR for runner isolation (containment model spec; doc-callout-removal reminder).
- pr-f4dc8a2: QA library auditor feature (depends on this PR + pr-7d5d036).
- pr-abcf70f (FakeClaudeSession, in_review): note urging that PR to establish a real code-level mock library and retire `pm/qa/mocks/` markdown contracts + the `pm qa mocks` CLI group.

## Captures committed in this PR

- `pm/qa/captures/pr-6be8ee6/impl/tui-walkthrough/` and `…/tui-walkthrough-v3/` are real captures of dogfooding the artifact recipes against a throwaway pm test project. v3 is a real asciinema .cast file produced via the no-TTY workaround documented in `tmux-screen-recording.md`. Worth a manual eyeball to confirm the manifest format and replay the cast.

## Things to watch for in QA

- Frontmatter schema enforcement: doc declares `title` and `description` required; `tags` is not used and was removed from the schema. Loader still tolerates missing values (no validation step in this PR) — manifest behavior should still resolve, but worth confirming nothing surfaces a stack trace on a frontmatter-less file.
- The packaged doc must be present after `pip install`. `pyproject.toml` lists `pm_core/docs/*.md` under `[tool.setuptools.package-data]`. Worth a sanity install + `pm qa docs` to confirm.
- `_pr_path_segment`-style resolution against gh_pr_number was tried and reverted; captures dir uses the local pr id only. project.yaml propagation issues that motivated the revert may still surface. (2026-05-08T20:29:05Z)
- Removed the old bug-fix Reconcile step (confirmed-overlap / noticed-overlap notes) intentionally. Audit found the discovery supervisor prompt (generate_discovery_supervisor_prompt) never instructed the watcher to file notes in that format — its step 5 just says "merge useful detail with pm pr note" in generic prose. So the Reconcile step was reading a note shape nothing was guaranteed to produce. Dedup falls out naturally from the new step 1 (manual repro on pre-fix code): if the bug is already fixed upstream, the session fails to reproduce and checks in with the user, which surfaces the duplicate. Note-based reconciliation was a fragile substitute for that. (2026-05-08T23:01:57Z)
- QA INPUT_REQUIRED:  (workdir: /home/matt/.pm/workdirs/qa/pr-6be8ee6-bbce993ad40dfe10) (2026-05-09T12:24:47Z)
- Fixed duplicate-verification bug: when the verifier FLAGGED a PASS and we sent a follow-up to the scenario pane, _last_scenario_hook_ts was popped, so the poll gate accepted the stale idle_prompt from the original verdict and re-extracted the unchanged PASS turn — spawning a second verifier before the scenario had responded. Now stamp it to time.time() after the follow-up so only events fired after the follow-up pass the gate. See commit e8fe399. (2026-05-12T12:58:19Z)
- QA INPUT_REQUIRED:  (workdir: /home/matt/.pm/workdirs/qa/pr-6be8ee6-6a87858569a89e07) (2026-05-12T14:06:46Z)
- QA INPUT_REQUIRED:  (workdir: /home/matt/.pm/workdirs/qa/pr-6be8ee6-cb4de4c7f7048cd2) (2026-05-12T15:25:54Z)
- QA NEEDS_WORK: Bug-fix flow prompt rewrites for a bugs PR (impl + review): PASS; pm qa CLI surface for the artifacts category and the rest of the new commands: INPUT_REQUIRED; TUI QA pane shows three sections and the create-picker modal routes correctly: NEEDS_WORK; pm qa regression replaces pm tui test, with unified filing addendum for bugs + improvements: PASS; Packaged qa_library.md survives pip install and pm qa docs works from any cwd: PASS; Frontmatter resilience — loader and CLI/TUI surfaces tolerate missing or legacy fields: PASS (workdir: /home/matt/.pm/workdirs/qa/pr-6be8ee6-4b86c9cea69d568c) (2026-05-12T22:06:18Z)
- QA INPUT_REQUIRED: Bug-fix flow prompt is restructured for a bug PR and absent for non-bug PRs: PASS; pm qa CLI surface — add-, author-, list/show/edit, docs, regression: PASS; TUI QA pane shows three sections and the create-picker modal routes correctly: PASS; End-to-end integration — bug-fix session produces pre/post captures and QA scenarios save under new layout: INPUT_REQUIRED; Review-loop INPUT_REQUIRED gate and duplicate-verifier guard: INPUT_REQUIRED; Packaging — qa_library.md survives pip install; frontmatter resilience across CLI and TUI: INPUT_REQUIRED (workdir: /home/matt/.pm/workdirs/qa/pr-6be8ee6-ba760724d2c7b159) (2026-05-12T23:28:10Z)

## How QA Works

You are in one of several QA scenarios running in parallel, each in its own
isolated clone.  An orchestrator is monitoring your tmux pane for your
final verdict.

## Important: When to use each verdict

- **PASS** — You executed the test steps AND they succeeded.  A PASS is
  only valid when you have **runtime evidence** (command output, observed
  behavior, test results) that the feature works.
- **NEEDS_WORK** — You executed the test steps and found concrete bugs or
  issues.
- **INPUT_REQUIRED** — You **could not execute** one or more test steps
  because of missing tools, unavailable commands, environment limitations,
  or ambiguity in the instructions.  **This is the correct verdict when
  your environment prevents you from testing** — do NOT substitute code
  reading or unit tests and claim PASS.  Explain what blocked you.

## Scenario

**Focus**: QA files with missing, legacy, or absent frontmatter render across pm qa list, pm qa show, and

**Steps**:
GIVEN: A throwaway pm project initialized inside a venv-installed pm clone. Setup:
- `python3 -m venv /tmp/pm-venv && source /tmp/pm-venv/bin/activate`
- `pip install -e .` from the project_manager clone
- `export PYTHONPATH=/workspace` (override container's `/opt/pm-src` shadow); confirm with `pm which`
- `TEST_DIR=<workdir>/pm-test-$(date +%s); mkdir -p "$TEST_DIR" && cd "$TEST_DIR" && git init`
- `pm init --backend local --no-import`
- `pm pr add "Add login feature"` (one PR is enough to exercise the surfaces)
Then under `$TEST_DIR/pm/qa/instructions/` (created on demand by `pm qa` helpers; `mkdir -p` if absent), hand-place exactly three `.md` files:
- `complete.md` — full frontmatter: `---\ntitle: Complete Instruction\ndescription: A complete instruction with title and description\n---\nBody text for complete file.`
- `legacy.md` — legacy frontmatter with `tags:` and no description: `---\ntitle: Legacy Instruction\ntags: [legacy, smoke]\n---\nBody text for legacy file.`
- `bare.md` — plain markdown, no `---` delimiters at all: `# Bare Heading\n\nNo frontmatter here, just body content.`
WHEN: From `$TEST_DIR`, the user runs `pm qa list`.
THEN:
- The command exits 0 with no traceback.
- Under the `Instructions (3):` header, all three rows appear (in sorted filename order: `bare`, `complete`, `legacy`).
- `complete: Complete Instruction — A complete instruction with title and description` is printed.
- `legacy: Legacy Instruction` is printed with no `— description` suffix (empty description rendered as blank, not `None`).
- `bare: Bare` is printed (title falls back to the filename stem title-cased), with no description suffix.

GIVEN: The same throwaway project with the three instruction files in place.
WHEN: The user runs `pm qa show complete`, `pm qa show legacy`, and `pm qa show bare` (auto-detect resolves them under the `instructions` category).
THEN: For each invocation, exit code 0 with no traceback, and:
- `complete`: prints `# Complete Instruction`, the description line, the `[<path>]` line, then `Body text for complete file.`
- `legacy`: prints `# Legacy Instruction`, no description line (blank skipped), the path line, then `Body text for legacy file.`
- `bare`: prints `# Bare` (title derived from id), no description line, the path line, then the full file contents `# Bare Heading\n\nNo frontmatter here, just body content.` as the body (since no `---` was found, the whole file is treated as body).

GIVEN: A pm tmux session running against `$TEST_DIR` with the same three files in place. Launch it with `cd "$TEST_DIR" && pm session 2>/dev/null || true` (the attach error is expected under Bash; the session is still created). Inspect the TUI via `pm tui view` / `tmux capture-pane -p`; send keys via `tmux send-keys`.
WHEN: The user sends the `q` key to the TUI pane to toggle the QA view open.
THEN:
- The QA pane renders without crashing (no Python traceback in `tmux capture-pane`).
- The `Instructions (3)` section header appears, followed by rows for `bare`, `complete`, and `legacy`.
- The `complete` row shows `complete: Complete Instruction` with its description on the indented line below.
- The `legacy` row shows `legacy: Legacy Instruction` with no description line beneath (missing description rendered as blank, not as the string `None` and not raising).
- The `bare` row shows `bare: Bare` with no description line beneath.

The steps are framed as one or more Given / When / Then user
stories. A scenario may bundle several triples that share a focus;
drive each triple in turn. For each:

- Establish the **Given** state by driving the user-facing surface
  (start a session, set up a project, open a pane) — not by
  hand-editing files or monkeypatching internals. If a later triple
  needs a different starting state, reset to its Given before
  performing the When.
- Perform the **When** action the way a real user would (run the
  command, press the key, submit the form). Use whatever driver
  gets the action to the right place — the mechanic is yours to
  choose, but the action itself must be the real user action.
- Check the **Then** by observing the surface, not by inspecting
  source or asserting strings in generated output. If the Then is
  about something visible on screen, confirm by viewing it; if it's
  about a file or command output, confirm by reading that file or
  command output — not by reading the code that produces it.

If you can't drive the user surface in this environment, report
INPUT_REQUIRED with a specific blocker instead of substituting a
different methodology.

## Artifact Capture Recipes (drive the WHEN, capture the THEN)

Available at:
- `/scratch/qa-artifacts/cli-recording.md`
- `/scratch/qa-artifacts/tmux-screen-recording.md`

These recipes are the basis for performing the scenario's **When**
action — the recipe describes how to drive the surface — and for
capturing the **Then** evidence (transcripts, recordings,
screenshots, logs). Read the recipe(s) and follow their driver +
capture commands. Save resulting captures
under `pm/qa/captures/pr-6be8ee6/scenarios/51/` (each
recipe's manifest format applies; if more than one recipe is listed,
use a named subdirectory per capture). Captures are how reviewers
confirm what the test demonstrated, so produce one even if the
scenario itself passes.

Aim for the capture to look as close as possible to a user actually
exercising the feature. A couple of things to watch out for: status
strings that read like real results but don't depend on one (printed
unconditionally rather than derived from the command), and narration
of steps in place of driving them. If a step is hard to reproduce,
note that in the manifest rather than working around it in the
recording.

**If you identify and fix a bug during this scenario, capture both
states.** Save the pre-fix recording under
`pm/qa/captures/pr-6be8ee6/scenarios/51/pre-fix/` and the
post-fix recording under `.../post-fix/`. Cross-link the two in each
manifest's `## Files` section, and (per Incidental Bugs below) still
file a PR for the bug.

After producing each capture, commit it and push so it lands on the
PR branch:
- `git add pm/qa/captures/pr-6be8ee6/scenarios/51/`
- `git commit -m "qa: capture for scenario 51"`
- `git push origin pm/pr-6be8ee6-bug-fix-flow-surface-tui-qa-repro-instructions-in-`

If the push is rejected (another scenario raced you), `git pull --rebase
origin pm/pr-6be8ee6-bug-fix-flow-surface-tui-qa-repro-instructions-in- && git push origin pm/pr-6be8ee6-bug-fix-flow-surface-tui-qa-repro-instructions-in-`.

## Execution

1. Pull the latest changes for `pm/pr-6be8ee6-bug-fix-flow-surface-tui-qa-repro-instructions-in-` from the remote. Resolve any merge conflicts before continuing.
2. Execute the test steps described above
3. If you find issues and can fix them:
   - Implement the fix in your workdir (your current directory)
   - Commit with message prefix `qa: `
   - Push: `git push origin pm/pr-6be8ee6-bug-fix-flow-surface-tui-qa-repro-instructions-in-`
   - If push fails (another scenario pushed first), pull and retry:
     `git pull --rebase origin pm/pr-6be8ee6-bug-fix-flow-surface-tui-qa-repro-instructions-in- && git push origin pm/pr-6be8ee6-bug-fix-flow-surface-tui-qa-repro-instructions-in-`
4. End with a verdict on its own line — one of:
   - **PASS** — Scenario passed, no issues found
   - **NEEDS_WORK** — Issues found and fixed (the fix is committed and pushed)
   - **INPUT_REQUIRED** — Issues found that you could not fix, or genuine ambiguity requiring human judgment

## Incidental Bugs

If you spot a bug or quality issue that isn't part of this PR's stated
scope, try to fix it if the fix doesn't require separate planning or user
input. If you do decide to fix it, then record what you did with:
  ```
  pm pr note add <pr-id> '<short summary of the incidental fix>'
  ```

If you don't, file a separate bug PR so it doesn't get lost:
  ```
  pm pr add '<title>' --plan bugs --description '<location, repro>'
  ```
  Skim `pm pr list --plan bugs` first to avoid duplicates.

IMPORTANT: Always end your response with the verdict keyword on its own line.