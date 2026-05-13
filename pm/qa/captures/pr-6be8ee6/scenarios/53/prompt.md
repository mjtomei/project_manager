You are running QA scenario 53: "pm qa add-/author-/list/show/edit across three categories"

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
- QA INPUT_REQUIRED: Bug-fix flow prompt structure for a bug PR vs non-bug PR: PASS; pm qa CLI — add/author/list/show/edit/docs across three categories: PASS; pm qa docs from outside the source tree (packaging): PASS; pm qa regression — id resolution, filing addendum, and removed pm tui test: PASS; TUI QA pane — three sections, status counter, and create-picker modal routing: PASS; End-to-end bug-fix + QA captures pipeline: INPUT_REQUIRED; Frontmatter resilience across CLI and TUI: PASS (workdir: /home/matt/.pm/workdirs/qa/pr-6be8ee6-60f01be41a9734aa) (2026-05-13T20:51:35Z)

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

**Focus**: CLI surface for the new artifacts category alongside instructions and regression, including refuse-clobber and category auto-detect

**Steps**:
GIVEN: a throwaway directory initialized as a pm project (run `pm init` so that `state_root()`/`store.find_project_root()` resolves to a `pm/` state dir), with the `pm` CLI installed in an isolated venv and `EDITOR=true` (or another no-op editor) so the post-create `subprocess.run([editor, ...])` returns immediately
WHEN: the user runs `pm qa add-instruction demo-inst`, then `pm qa add-regression demo-reg`, then `pm qa add-artifact demo-art`
THEN:
- exit code 0 for each, and each prints `Created: <path>`
- `pm/qa/instructions/demo-inst.md`, `pm/qa/regression/demo-reg.md`, and `pm/qa/artifacts/demo-art.md` exist
- each file's YAML frontmatter contains `title: Demo Inst` / `Demo Reg` / `Demo Art` and a `description:` key, and contains no `tags:` line (unlike the `pm qa mocks add` template, the three add-* templates omit tags)
WHEN: the user re-runs `pm qa add-instruction demo-inst` against the existing file
THEN: the command exits non-zero, stderr contains `Already exists: <path to demo-inst.md>`, and the file's mtime/contents are unchanged
WHEN: the user runs `pm qa list`
THEN: stdout contains three labeled sections in order — `Instructions (N):`, `Regression Tests (N):`, `Artifact Recipes (N):` — and each section includes a line for the corresponding `demo-*` id with its title
WHEN: the user runs `pm qa show demo-art` (no `-c`)
THEN: exit 0, output begins with `# Demo Art`, includes a `[<path>/pm/qa/artifacts/demo-art.md]` line, and prints the body (category was auto-resolved by iterating instructions → regression → artifacts)
WHEN: the user runs `pm qa author-artifact demo-art-2` with `CLAUDE` (and any backing `claude` binary) overridden by a shim on PATH that records argv/stdin into a file and exits 0 — driving the real `launch_claude` codepath end-to-end
THEN:
- the recorded prompt (the value `qa_authoring.build_authoring_prompt` produced and `launch_claude` passed to the shim) begins with `Work with the user to author a new artifact recipe …` referencing the resolved target `pm/qa/artifacts/demo-art-2.md`, and embeds the packaged QA library doc (it contains the `## Reference: pm QA library` heading followed by the body of `pm_core/docs/qa_library.md`)
- re-running the same command after manually creating `pm/qa/artifacts/demo-art-2.md` exits non-zero with `Already exists: …/pm/qa/artifacts/demo-art-2.md` and does not invoke the Claude shim a second time
WHEN: the user runs `pm qa add` (the un-suffixed legacy form) and `pm tui test`
THEN: each exits non-zero with a click "No such command" error (`Error: No such command 'add'.` / `Error: No such command 'test'.`) — neither subcommand is registered on the `qa` group or the `tui` group

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

## Artifact Capture Recipe (drive the WHEN, capture the THEN)

Available at:
- `/scratch/qa-artifacts/cli-recording.md`

These recipes are the basis for performing the scenario's **When**
action — the recipe describes how to drive the surface — and for
capturing the **Then** evidence (transcripts, recordings,
screenshots, logs). Read the recipe(s) and follow their driver +
capture commands. Save resulting captures
under `pm/qa/captures/pr-6be8ee6/scenarios/53/` (each
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
`pm/qa/captures/pr-6be8ee6/scenarios/53/pre-fix/` and the
post-fix recording under `.../post-fix/`. Cross-link the two in each
manifest's `## Files` section, and (per Incidental Bugs below) still
file a PR for the bug.

After producing each capture, commit it and push so it lands on the
PR branch:
- `git add pm/qa/captures/pr-6be8ee6/scenarios/53/`
- `git commit -m "qa: capture for scenario 53"`
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