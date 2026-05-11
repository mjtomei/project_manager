You are running QA scenario 17: "Packaging — pm_core/docs ships and pm qa docs works from an installed package"

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
- QA-time finding (out of original PR scope but related to QA flow correctness):

The push proxy's `_local_push` was routing scenario pushes through the PR workdir — `git fetch --update-head-ok <scenario> refs/heads/X:refs/heads/X` into the PR workdir, then `git push origin X` from there. The fetch silently fast-forwarded the PR workdir's branch ref without touching its index/worktree, leaving `git status` showing phantom staged deletions (files added in the new commits) and phantom modifications (files changed in the new commits). The finalize-merge step was effectively short-circuited: by the time finalize ran, the local branch ref had already been mutated by the proxy, so `git pull` was a no-op and real divergence (e.g. a user commit on the PR branch during QA) was indistinguishable from the proxy's writes.

Fix (commit ba57e94): `_local_push` now resolves the real upstream up front via `resolve_real_origin(target_repo)` and pushes the source ref directly there from the caller's clone, bypassing the PR workdir entirely. The old fetch-into-target path is kept only as a fallback for repos with no real upstream. PR workdir's branch ref, index, and worktree stay synchronized; the finalize session's `git fetch origin && git merge origin/<branch>` is now a real merge with proper conflict detection.

Added unit test `test_local_push_with_upstream_bypasses_pr_workdir` pinning the new behavior. Full proxy test suite passes (49/49, modulo one pre-existing unrelated stdin failure). (2026-05-11T12:42:43Z)
- QA PASS: Push proxy bypasses PR workdir on direct upstream push: PASS (workdir: /home/matt/.pm/workdirs/qa/pr-6be8ee6-6af41a6b3c4e4514) (2026-05-11T18:04:11Z)

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

**Focus**: pyproject.toml package-data includes pm_core/docs/*.md; after a clean pip install, pm qa docs prints the packaged doc content regardless of cwd

**Steps**:
1. From /workspace, build/locate the source tree path: `WORKDIR=$(pwd)`. Create a fresh venv outside the source tree: `python3 -m venv /tmp/pm-pkg-venv && source /tmp/pm-pkg-venv/bin/activate`. Verify `which pm` is empty before install.
2. Start asciinema recording into the scenario dir: `mkdir -p "$WORKDIR/pm/qa/captures/pr-6be8ee6/scenarios/17" && asciinema rec -q "$WORKDIR/pm/qa/captures/pr-6be8ee6/scenarios/17/recording.cast"` (run the remaining steps inside the recorded shell).
3. Inside the recorded shell, install from the source tree: `pip install "$WORKDIR"`. Confirm install succeeded and `which pm` now points inside /tmp/pm-pkg-venv.
4. `cd /tmp` to move away from the source tree. Run `pm qa docs | tee "$WORKDIR/pm/qa/captures/pr-6be8ee6/scenarios/17/pm-qa-docs.log"`. Assert: output is non-empty, the first non-empty line is `# pm QA library`, and at least one section heading from the packaged file appears (e.g., `## The four directories`, `## Authoring`, `## File format (instructions / regression / artifacts)`).
5. Still in /tmp, run: `python3 -c "import importlib.resources, pm_core; p = importlib.resources.files('pm_core').joinpath('docs/qa_library.md'); print(p.read_text()[:200])"`. Assert non-empty output starting with `# pm QA library` (confirms `[tool.setuptools.package-data] pm_core = ["docs/*.md"]` actually shipped the file in the wheel/site-packages).
6. Verify the doc lives under site-packages, not the source tree: `python3 -c "import pm_core, pathlib; print(pathlib.Path(pm_core.__file__).parent / 'docs/qa_library.md')"` — assert the printed path is under /tmp/pm-pkg-venv/lib/.../site-packages/pm_core/docs/qa_library.md and that file exists.
7. Cross-check parity: `diff <(pm qa docs) "$WORKDIR/pm_core/docs/qa_library.md"` should show no differences (installed copy matches source).
8. Stop asciinema (exit the recorded shell). Confirm `scenarios/17/recording.cast` and `scenarios/17/pm-qa-docs.log` exist and are non-empty. Deactivate the venv: `deactivate`. Optionally clean up: `rm -rf /tmp/pm-pkg-venv`.

## Artifact Capture Recipe

Available at:
- `/scratch/qa-artifacts/cli-recording.md`

Read the recipe(s) and follow their capture commands to produce
evidence of this scenario's behavior. Save resulting captures under
`pm/qa/captures/pr-6be8ee6/scenarios/17/` (each recipe's
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
`pm/qa/captures/pr-6be8ee6/scenarios/17/pre-fix/` and the
post-fix recording under `.../post-fix/`. Cross-link the two in each
manifest's `## Files` section, and (per Incidental Bugs below) still
file a PR for the bug.

After producing each capture, commit it and push so it lands on the
PR branch:
- `git add pm/qa/captures/pr-6be8ee6/scenarios/17/`
- `git commit -m "qa: capture for scenario 17"`
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