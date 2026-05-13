You are running QA scenario 41: "TUI QA pane shows three sections, picker modal launches the right command, regression Enter routes through unified prompt"

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

**Focus**: TUI q pane sections + counts, a picker modal (6 options × name input), regression-item Enter behavior

**Steps**:
## Setup

1. Install pm into an isolated venv and shadow the container's master:
```
python3 -m venv /tmp/pm-venv && source /tmp/pm-venv/bin/activate
pip install -e /workspace
export PYTHONPATH=/workspace
pm which   # must print /workspace, not /opt/pm-src
```

2. Create a throwaway pm project:
```
TEST_DIR=/tmp/pm-test-$(date +%s)
mkdir -p "$TEST_DIR" && cd "$TEST_DIR"
git init
pm init --backend local --no-import
pm pr add "Smoke PR"
```

3. Seed at least one QA item per category via the CLI (use scaffold mode so they don't block on Claude):
```
pm qa add-instruction i1 --no-launch || pm qa add-instruction i1
pm qa add-regression r1 --no-launch || pm qa add-regression r1
pm qa add-artifact a1 --no-launch || pm qa add-artifact a1
```
If `--no-launch` is not supported, kill the launched author panes immediately; the scaffold file should already exist on disk.
Verify the files exist:
```
ls pm/qa/instructions/i1.md pm/qa/regression/r1.md pm/qa/artifacts/a1.md
```

4. Drop a resilience fixture — an empty-frontmatter file — into each directory to confirm the loader doesn't choke:
```
printf -- '---\n---\n' > pm/qa/instructions/empty.md
printf -- '---\n---\n' > pm/qa/regression/empty.md
printf -- '---\n---\n' > pm/qa/artifacts/empty.md
```

5. Start the TUI session (ignore the attach error — no TTY):
```
cd "$TEST_DIR" && pm session 2>/dev/null || true
```
Identify the session/window/pane with `tmux list-panes -a -F '#{session_name}:#{window_index}.#{pane_index} #{pane_current_command}'`. Use `pm tui send` / `pm tui view` or `tmux send-keys` / `tmux capture-pane -p` against that pane for the rest of the steps. Run all `pm` commands inside new panes of the test session, never in the controller shell.

## Section / count assertions

6. Send `q` to open the QA pane. Capture the framebuffer and assert it shows three labeled headers in order: `Instructions (2)`, `Regression Tests (2)`, `Artifact Recipes (2)` (count = 1 real + 1 empty-frontmatter fixture per category). Source of truth: `pm_core/tui/qa_pane.py:46-48,104`.

7. Assert the status bar reads ` QA    6 item(s)    Enter=run  e=edit  d=debug  a=add  q=back ` (total = sum of three sections). Source: `pm_core/tui/app.py:1229-1239`.

8. Empty-section rendering: in a second pane, delete the artifacts directory contents (`rm pm/qa/artifacts/*.md`), then in the TUI press `q` again (or whatever refresh path applies — re-entering the QA view calls `_refresh_qa_pane`). Confirm the `Artifact Recipes (0)` header still renders and the status bar updates to `4 item(s)`. Restore `a1.md` and `empty.md` afterward.

## Picker modal

9. With the QA pane focused, press `a`. Capture framebuffer and confirm `QACreatePickerScreen` opens with: a `Create QA file` title, a `Name` input (placeholder `e.g. login-flow-setup`), and a `Kind` list with exactly THREE options — `Instruction`, `Regression test`, `Artifact recipe`. NOTE: the draft says "6 options × 2 modes"; the real picker only exposes `author` mode (see `screens.py:501-505` and the docstring at `screens.py:457-465`). Record this as a planner-vs-reality correction; do not fail the scenario over it.

10. Empty-name submit: with the Name input empty, press Enter. Confirm the modal stays open, no pane launches (check `tmux list-panes` count unchanged), and there is no crash in the TUI framebuffer. Source: `screens.py:549-553` returns early when name is blank.

11. Press Esc. Confirm the modal closes, focus returns to the QA pane, and no new pane was created.

12. Reopen picker (`a`). Type `picker-art`, leave selection on `Artifact recipe` (3rd option — send `down down` to move selection), press Enter. Confirm:
- A new pane is launched in a `qa-author` window (per `app.py:1342` — `pane_ops.launch_pane(self, cmd, "qa-author")`).
- The pane is running `pm qa author-artifact picker-art` (capture-pane the new pane and grep for that command). NOTE: planner draft said `pm qa add-artifact …` — corrected to `author-artifact` because the picker only triggers author mode.
- Eventually (or after killing the Claude session) the file lands at `pm/qa/artifacts/picker-art.md`. If `author-artifact` requires Claude to write the file, kill the pane and instead assert that the launched command string is correct via capture-pane; do not require the file to exist.

13. Reopen picker, type `picker-ins`, keep default selection (`Instruction`, index 0), press Enter. Confirm a `qa-author` pane launches running `pm qa author-instruction picker-ins`. Kill the pane before Claude responds.

## Regression Enter routing

14. Back in the QA pane, navigate down (`j` or `down`) until selection lands on the `r1` row under `Regression Tests` (verify by capture-pane: the `▸` marker should be on the line `r1: …`). Press `Enter`.

15. Confirm:
- A new pane is launched in a `qa-item` window (per `pane_ops.py:511`).
- The launched Claude prompt contains the substring `pm/qa/captures/regression/` (from `regression_prompts.py:18,61`). Verify by `tmux capture-pane -p` on the new pane — the Claude REPL echoes the prompt or you can inspect via `ps -eo args | grep claude` for the prompt argument. The literal placeholder is `pm/qa/captures/regression/<test-id>/<timestamp>/`; matching the prefix `pm/qa/captures/regression/` is sufficient.
- The prompt was built via `build_regression_test_prompt` (this is the only code path producing that substring; presence proves the branch at `pane_ops.py:484-492` fired).

16. Kill the qa-item pane.

## Cleanup / artifacts

17. Save `tmux capture-pane -p -S -` for each pane visited (QA view, picker modal, picker post-submit, regression Enter target) into the scenario's artifacts directory.

18. Tear down: kill the tmux session and remove `$TEST_DIR`.

## Artifact Capture Recipe

Available at:
- `/scratch/qa-artifacts/tmux-screen-recording.md`

Read the recipe(s) and follow their capture commands to produce
evidence of this scenario's behavior. Save resulting captures under
`pm/qa/captures/pr-6be8ee6/scenarios/41/` (each recipe's
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
`pm/qa/captures/pr-6be8ee6/scenarios/41/pre-fix/` and the
post-fix recording under `.../post-fix/`. Cross-link the two in each
manifest's `## Files` section, and (per Incidental Bugs below) still
file a PR for the bug.

After producing each capture, commit it and push so it lands on the
PR branch:
- `git add pm/qa/captures/pr-6be8ee6/scenarios/41/`
- `git commit -m "qa: capture for scenario 41"`
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