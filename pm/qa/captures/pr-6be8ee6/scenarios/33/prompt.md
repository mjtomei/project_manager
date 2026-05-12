You are running QA scenario 33: "pm qa CLI surface — add-, author-, list/show/edit, docs, regression"

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

## Mocks

The QA spec defines the mocking strategy for this PR's test scenarios.
Use the contracts and scripted responses below — do not devise your own.

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

**Focus**: All three new category commands work end-to-end; pm qa add is gone; templates omit tags:; list/show/edit cover artifacts; pm qa docs works from outside the source tree; pm qa regression has correct exit

**Steps**:
## Setup

1. Make sure the editable clone is the active `pm`:
```
python3 -m venv /tmp/pm-venv && source /tmp/pm-venv/bin/activate
cd /workspace && pip install -e .
export PYTHONPATH=/workspace
pm which   # must print /workspace, not /opt/pm-src
```

2. Create a throwaway pm project and initialize it (this scenario does **not** need a tmux session, except for step 9/10 where regression launches require it):
```
TEST_DIR=/tmp/pm-test-$(date +%s)
mkdir -p "$TEST_DIR" && cd "$TEST_DIR"
git init -q
pm init --backend local --no-import
pm pr add "Login feature"
pm pr add "DB migration"
```
Start a tmux session so `pm qa regression` has a pane to bind to (used later):
```
cd "$TEST_DIR" && pm session 2>/dev/null || true
```

## Test Steps

3. **add-* commands create files with correct frontmatter, no `tags:`**. With `EDITOR=true` (no-op editor):
```
cd "$TEST_DIR"
EDITOR=true pm qa add-instruction my-inst
EDITOR=true pm qa add-regression my-reg
EDITOR=true pm qa add-artifact my-art
```
Verify:
- `pm/qa/instructions/my-inst.md` exists; `pm/qa/regression/my-reg.md` exists; `pm/qa/artifacts/my-art.md` exists.
- Each frontmatter has `title:` and `description:` (description value empty is OK) and **no** `tags:` line. Confirm with `grep -E '^(title|description|tags):' pm/qa/{instructions/my-inst,regression/my-reg,artifacts/my-art}.md` — expect 6 lines total (2 per file), zero `tags:`.
- Each template's body matches the file's category (instruction template has `## Setup / ## Test Steps / ## Expected Behavior / ## Reporting`; regression has `## Scenarios / ## Reporting` plus the "careful tester" preamble; artifact has `## When to use / ## What this recipe produces / ## Capture / ## Manifest format`).

4. **Re-running an add-* command refuses to clobber**:
```
EDITOR=true pm qa add-instruction my-inst ; echo "rc=$?"
```
Expect `rc=1` and a stderr message containing `Already exists:` followed by the file path. Confirm the file's mtime is unchanged (`stat -c %Y pm/qa/instructions/my-inst.md` before/after).

5. **`pm qa add` (no suffix) is rejected**:
```
pm qa add foo 2>&1 ; echo "rc=$?"
```
Expect non-zero exit and a Click-style `Error: No such command 'add'` (or `Usage:` + error). There should be no `add-` action taken.

6. **`pm qa list` shows three labeled sections with the new files**:
```
pm qa list
```
Expect three section headers exactly: `Instructions (N):`, `Regression Tests (N):`, `Artifact Recipes (N):` — each with N ≥ 1. The newly created `my-inst`, `my-reg`, `my-art` IDs appear under their respective sections.

7. **`pm qa show` and `pm qa edit` auto-resolve across categories** (no `-c`):
```
pm qa show my-art
EDITOR=true pm qa edit my-art ; echo "rc=$?"
```
For `show`: stdout has `# My Art` title line, the `[<path>]` line pointing at `pm/qa/artifacts/my-art.md`, and the template body. For `edit`: `rc=0` (EDITOR=true exits cleanly). Repeat both with `my-reg` to confirm resolution into the regression category works too.

8. **`pm qa docs` works from outside the source tree**:
```
mkdir -p /tmp/qa-docs-x && cd /tmp/qa-docs-x
pm qa docs > out.txt ; echo "rc=$?"
```
Expect `rc=0`. Verify `out.txt` begins with `# pm QA library` and contains the headers `## The four directories`, `## Authoring`, `## File format (instructions / regression / artifacts)`, `## Regression tests`. Then `cd "$TEST_DIR"` again.

9. **`pm qa regression` with unknown id exits non-zero**:
```
pm qa regression nonexistent-id 2>&1 ; echo "rc=$?"
```
Expect non-zero and stderr line `Unknown regression test: nonexistent-id` plus `Run 'pm qa list' to see available tests.`

10. **`pm qa regression` prompt: filing addendum is gated by `--file-prs` / `--file-bugs`**.  Create a minimal regression body:
```
cat > pm/qa/regression/demo.md <<'EOF'
---
title: Demo
description: sanity
---
Verify the dashboard renders.

## Scenarios
- Scenario 1: open it
## Reporting
PASS/FAIL.
EOF
```
There is **no** dry-run flag on `pm qa regression`, so inspect the launched pane's first prompt. For each of the three invocations below, in a new pane in the test tmux session run the command, then immediately `tmux capture-pane -p -t <session>:0.<new-pane> -S -` to grab the prompt buffered for Claude, then kill that pane.
- `pm qa regression demo` → captured prompt contains the regression body ("Verify the dashboard renders.") and **does not** contain `--plan bugs` / `--plan improvements` filing addendum.
- `pm qa regression demo --file-prs` → prompt **does** contain both `pm pr add '<title>' --plan bugs` and `--plan improvements` filing lines.
- `pm qa regression demo --file-bugs` → identical addendum to `--file-prs` (it's a hidden alias for the same flag).

11. **`pm qa author-*` embeds qa_library.md and resolves target path; refuses to clobber**:
```
pm qa author-instruction new-x
```
Same capture technique as step 10 (kill the pane after grabbing). Verify the prompt:
- includes the `# pm QA library` doc content (look for `## File format` header from `pm_core/docs/qa_library.md`).
- references the resolved target path `pm/qa/instructions/new-x.md`.
Then create the target so the second call must refuse:
```
touch pm/qa/instructions/new-x.md
pm qa author-instruction new-x 2>&1 ; echo "rc=$?"
```
Expect `rc=1` and `Already exists: .../pm/qa/instructions/new-x.md`. Repeat author-resolution check briefly for `author-regression` and `author-artifact` to confirm all three are wired.

12. **`pm tui test` is removed**:
```
pm tui test 2>&1 ; echo "rc=$?"
pm tui test --file-bugs 2>&1 ; echo "rc=$?"
```
Expect non-zero `rc` for both and Click `Error: No such command 'test'.` (or `Usage:` block followed by that error). Confirm `pm tui --help` does not list a `test` subcommand.

13. **Capture**. Re-run the whole transcript inside `asciinema rec` and save the cast under `pm/qa/captures/pr-6be8ee6/scenarios/33/<timestamp>/cast.cast` along with a short `manifest.md` listing the commands and observed results per step.

## Artifact Capture Recipe

Available at:
- `/scratch/qa-artifacts/cli-recording.md`

Read the recipe(s) and follow their capture commands to produce
evidence of this scenario's behavior. Save resulting captures under
`pm/qa/captures/pr-6be8ee6/scenarios/33/` (each recipe's
manifest format applies; if more than one recipe is listed, use a
named subdirectory per capture). Captures are how reviewers confirm
what the test demonstrated, so produce one even if the scenario itself
passes.

Aim for the capture to look as close as possible to a user actually
exercising the feature. A couple of things to watch out for: status
strings that read like real results but don't depend on one (printed
unconditionally rather than derived from the command), and narration
of steps in place of driving them. If a step is hard to reproduce,
note that in the manifest rather than working around it in the
recording.

**If you identify and fix a bug during this scenario, capture both
states.** Save the pre-fix recording under
`pm/qa/captures/pr-6be8ee6/scenarios/33/pre-fix/` and the
post-fix recording under `.../post-fix/`. Cross-link the two in each
manifest's `## Files` section, and (per Incidental Bugs below) still
file a PR for the bug.

After producing each capture, commit it and push so it lands on the
PR branch:
- `git add pm/qa/captures/pr-6be8ee6/scenarios/33/`
- `git commit -m "qa: capture for scenario 33"`
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