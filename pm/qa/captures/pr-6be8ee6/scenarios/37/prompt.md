You are running QA scenario 37: "Packaging — qa_library.md survives pip install; frontmatter resilience across CLI and TUI"

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

**Focus**: Fresh ./install.sh --local install ships pm_core/docs/qa_library.md; pm qa docs works from arbitrary cwd; loader tolerates missing/no/legacy-tags: frontmatter without crashing in list, show, and TUI QA

**Steps**:
## Setup (fresh install verification — step 1 of the scenario)

1. In a fresh shell, create a clean venv and install pm from the workspace clone using `./install.sh --local`:
```
cd /workspace
./install.sh --local
```
The `--local` flag should install the current checkout into a venv. Note the venv path that the installer prints (e.g. `~/.local/share/pm/venv` or similar — read `install.sh` to confirm before running if unsure).

2. From an unrelated cwd (e.g. `cd /tmp`), run `pm qa docs` and confirm:
- Exit code is 0 (`echo $?`).
- Output contains the qa_library.md body (look for the title line / a recognizable header from `pm_core/docs/qa_library.md`).

3. Locate the venv's site-packages and confirm the packaged doc shipped:
```
python -c "import pm_core, pathlib; print(pathlib.Path(pm_core.__file__).parent / 'docs' / 'qa_library.md')"
test -f "$(python -c "import pm_core, pathlib; print(pathlib.Path(pm_core.__file__).parent / 'docs' / 'qa_library.md')")" && echo OK
```
The file must exist inside the installed package (not just the source tree).

## Setup (throwaway project for frontmatter edge cases)

4. Override PYTHONPATH if running in the standard container (so the editable clone shadows `/opt/pm-src`), then create a throwaway project:
```
export PYTHONPATH=/workspace
pm which   # should print the /workspace clone
TEST_DIR=/tmp/pm-test-$(date +%s)
mkdir -p "$TEST_DIR" && cd "$TEST_DIR"
git init
pm init --backend local --no-import
```

5. Add at least one PR so the TUI has something to render:
```
pm pr add "Seed PR for QA scenario 37"
```

## Frontmatter edge cases

6. Create three QA files exercising the edge cases (paths verified against `pm_core/qa_instructions.py` — `instructions_dir`, `regression_dir`, `artifacts_dir` resolve to `pm/qa/<category>/`):

a. Instruction with NO `---` delimiters at all (pure body) — write to `pm/qa/instructions/no-frontmatter.md`:
```
mkdir -p pm/qa/instructions pm/qa/regression pm/qa/artifacts
cat > pm/qa/instructions/no-frontmatter.md <<'EOF'
# Plain body, no frontmatter

Just markdown content without any YAML header.
EOF
```

b. Regression with the obsolete `tags: [foo]` field — write to `pm/qa/regression/legacy-tags.md`:
```
cat > pm/qa/regression/legacy-tags.md <<'EOF'
---
title: Legacy tags regression
description: Has obsolete tags field
tags: [foo, bar]
---
Body of the legacy-tags regression test.
EOF
```

c. Artifact whose frontmatter omits `description:` — write to `pm/qa/artifacts/no-description.md`:
```
cat > pm/qa/artifacts/no-description.md <<'EOF'
---
title: Artifact without description
---
Capture recipe body.
EOF
```

## CLI verification

7. Run `pm qa list` from `$TEST_DIR` and confirm:
- Exit code 0, no traceback.
- All three files appear under their respective sections (Instructions, Regression Tests, Artifact Recipes). The no-frontmatter entry will render a titleized filename (`No Frontmatter`) and empty description — that is acceptable.

8. Run `pm qa show` for each file and confirm exit 0 plus body content prints:
```
pm qa show no-frontmatter
pm qa show legacy-tags
pm qa show no-description
```
(Note: `qa_show` resolves across categories without `--category` per `pm_core/cli/qa.py:25`.)

## TUI verification

9. Launch the TUI inside a tmux session (CC's Bash has no TTY; the `pm session` attach will fail but the session is created — ignore the error):
```
cd "$TEST_DIR" && pm session 2>/dev/null || true
```
Then in a new pane inside that tmux session run `pm tui`. After it starts, press `q` to toggle the QA instructions pane.

10. Capture the framebuffer with `pm tui view` (or `tmux capture-pane -p -t <session>:<window>.<pane> -S -`) and confirm:
- The three test files render in their proper sections (Instructions / Regression Tests / Artifact Recipes).
- No Python traceback appears anywhere in the pane history.
- Quit the TUI cleanly (`q` again or whatever closes the pane), and confirm the underlying pm process exited 0.

## Checkpoint 4 — qa_finalize_prompt path

11. Inside the same container (do NOT reuse scenario 35's filesystem), replicate scenario 35's bug-PR-with-valid-impl-and-scenario-captures setup: create a bug-fix PR, run its QA loop far enough to produce at least one scenario worktree with a verdict and capture (refer to scenario 35's setup section for the exact commands; reproduce them here). The goal is to land in a state where `pm_core/qa_loop.py`'s finalize step (which calls `build_qa_finalize_prompt`, see `pm_core/qa_loop.py:414`) will fire.

12. Trigger the surface that invokes `qa_finalize_prompt`: either let the TUI QA loop reach the finalize pane, or invoke the CLI equivalent that drives `qa_loop` to completion (check `pm qa --help` for the loop-runner subcommand; if only the TUI surface exists, drive it through the TUI). Confirm:
- The finalize pane/process starts without raising (no traceback in framebuffer or stderr).
- The finalize Claude prompt is built successfully (you can grep for the `"You are the post-QA finalize check"` header string in the pane).
- The pane closes out (exits 0 or completes its short Claude session) without a Python error.

## Capture

13. Save captures (tmux pane dumps, `pm qa list` output, `pm qa show` outputs, the venv site-packages `ls` proof, the finalize-pane framebuffer) under the scenario 37 captures directory for this PR. Include one file per checkpoint and a short README noting which step each file corresponds to.

## Artifact Capture Recipes

Available at:
- `/scratch/qa-artifacts/cli-recording.md`
- `/scratch/qa-artifacts/tmux-screen-recording.md`

Read the recipe(s) and follow their capture commands to produce
evidence of this scenario's behavior. Save resulting captures under
`pm/qa/captures/pr-6be8ee6/scenarios/37/` (each recipe's
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
`pm/qa/captures/pr-6be8ee6/scenarios/37/pre-fix/` and the
post-fix recording under `.../post-fix/`. Cross-link the two in each
manifest's `## Files` section, and (per Incidental Bugs below) still
file a PR for the bug.

After producing each capture, commit it and push so it lands on the
PR branch:
- `git add pm/qa/captures/pr-6be8ee6/scenarios/37/`
- `git commit -m "qa: capture for scenario 37"`
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