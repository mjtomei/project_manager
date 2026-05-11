You are running QA scenario 16: "TUI QA pane — three sections, status counter, a picker, regression Enter (end-to-end user flow)"

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

**Focus**: q-key pane renders three labeled sections (Instructions/Regression Tests/Artifact Recipes), status bar QA counter includes artifacts, a launches

**Steps**:
**Setup (from instruction file)**

1. Set up pm in a virtualenv if not already done:
```
python3 -m venv /tmp/pm-venv && source /tmp/pm-venv/bin/activate
cd /workspace && pip install -e .
export PYTHONPATH=/workspace
pm which   # must print /workspace, not /opt/pm-src
```

2. Create a throwaway test project (use workdir if available, else /tmp):
```
TEST_DIR=/tmp/pm-test-$(date +%s)
mkdir -p "$TEST_DIR" && cd "$TEST_DIR" && git init
pm init --backend local --no-import
pm pr add "Add login feature"
# capture the id printed (pr-XXXXXXX); use it for --depends-on
pm pr add "Fix database migration" --depends-on <id1>
pm pr add "Refactor auth module" --depends-on <id1>,<id2>
pm pr add "Add unit tests"
```

3. Start the tmux session from the test directory (attach will fail, that's fine):
```
cd "$TEST_DIR" && pm session 2>/dev/null || true
```
Determine the session name (`tmux ls`) — it's typically the basename of TEST_DIR. Export it: `SESS=<name>`.

4. Start asciinema recording per `pm/qa/artifacts/cli-recording.md`:
```
mkdir -p "$TEST_DIR/scenarios/16"
asciinema rec --overwrite "$TEST_DIR/scenarios/16/session.cast" \
-c "tmux attach -t $SESS" &
```
(Or run asciinema separately if attaching interactively is not feasible — the key requirement is that a `.cast` file is produced under `scenarios/16/`.)

**Test steps**

5. Capture the TUI home screen and verify the status-bar QA counter:
```
pm tui view -s $SESS > scenarios/16/01-home.txt
```
The status bar should read something like `QA  N item(s)` where N is the **sum** of instructions + regression + artifacts. Verify:
```
INST=$(ls "$TEST_DIR/pm/qa/instructions" 2>/dev/null | wc -l)
REG=$(ls "$TEST_DIR/pm/qa/regression" 2>/dev/null | wc -l)
ART=$(ls "$TEST_DIR/pm/qa/artifacts" 2>/dev/null | wc -l)
echo "expected total = $((INST+REG+ART))"
```
Note: in a fresh throwaway project these dirs typically don't exist, so the home-screen counter will be 0. The "includes artifacts" assertion is verified more meaningfully in step 6 below (the section header explicitly shows the artifact count). To exercise non-zero counts, optionally copy a couple of files from the main repo's `pm/qa/{instructions,regression,artifacts}/` into the test project before this step and re-check the counter.

6. Open the QA pane and assert the three section headers:
```
pm tui send q -s $SESS
sleep 0.3
pm tui view -s $SESS > scenarios/16/02-qa-pane.txt
```
Assert all three headers are present, each rendered as bold/underlined `<Label> (<count>)`:
- `Instructions (N)`  (note: literal "Instructions", NOT "QA Instructions")
- `Regression Tests (N)`
- `Artifact Recipes (N)`
Also assert the status bar now reads `QA  <total> item(s)   Enter=run  e=edit  d=debug  a=add  q=back`.

7. Send `a` and verify the QACreatePickerScreen modal opens (does NOT exec `pm qa add-instruction`):
```
pm tui send a -s $SESS
sleep 0.3
pm tui view -s $SESS > scenarios/16/03-create-picker.txt
```
Assert the modal shows:
- Title `Create QA file`
- `Name` label with an Input (placeholder `e.g. login-flow-setup`)
- `Kind` label followed by 6 options (instructions/regression/artifacts × author/add), with `▸` pointer on one
- Footer hint `↑↓ change kind · Enter create · Esc cancel`
The scenario's mention of a "mode field" is loose — `mode` (author vs add) is folded into the Kind options list, not a separate field. Dismiss with Escape:
```
pm tui send Escape -s $SESS
```

8. Navigate to a regression item and press Enter. First make sure at least one regression test exists in the test project — if `pm/qa/regression/` is empty, copy one in from `/workspace/pm/qa/regression/` (e.g. `pr-interaction.md`) and re-open the QA pane (`pm tui send q` to leave, `q` to re-enter) so it picks up the new file. Then:
```
pm tui send Down -s $SESS    # move off "Instructions" header into Regression section
# repeat Down until ▸ is on a regression item (verify with pm tui view)
pm tui send Enter -s $SESS
sleep 1
tmux list-panes -t $SESS -F '#{pane_id} #{pane_current_command}'
```
A new pane should appear running `claude` (or similar). Capture its contents and assert the prompt body contains distinctive strings from `build_regression_test_prompt`:
```
NEWPANE=<pane id from list-panes above>
tmux capture-pane -p -t $NEWPANE -S - > scenarios/16/04-regression-launch.txt
```
Grep for:
- `## Session Context`
- `You are testing against tmux session: <SESS>`
- `## Captures`
- `pm/qa/captures/regression/`
- `## QA Regression Test: <title of the regression item>`
- `## Filing Findings` (since `file_findings=True` in `pane_ops.py:491`)
Do NOT wait for Claude output. Kill the launched pane: `tmux kill-pane -t $NEWPANE`.

9. Save artifacts:
```
tmux capture-pane -p -t $SESS -S - > scenarios/16/tmux-transcript.txt
```
Stop asciinema (`kill %1` or Ctrl-D in the recording shell). Verify `scenarios/16/` contains: `session.cast`, `01-home.txt`, `02-qa-pane.txt`, `03-create-picker.txt`, `04-regression-launch.txt`, `tmux-transcript.txt`.

## Artifact Capture Recipe

Available at:
- `/scratch/qa-artifacts/tmux-screen-recording.md`

Read the recipe(s) and follow their capture commands to produce
evidence of this scenario's behavior. Save resulting captures under
`pm/qa/captures/pr-6be8ee6/scenarios/16/` (each recipe's
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
`pm/qa/captures/pr-6be8ee6/scenarios/16/pre-fix/` and the
post-fix recording under `.../post-fix/`. Cross-link the two in each
manifest's `## Files` section, and (per Incidental Bugs below) still
file a PR for the bug.

After producing each capture, commit it and push so it lands on the
PR branch:
- `git add pm/qa/captures/pr-6be8ee6/scenarios/16/`
- `git commit -m "qa: capture for scenario 16"`
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