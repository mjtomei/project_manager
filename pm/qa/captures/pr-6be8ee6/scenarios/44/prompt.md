You are running QA scenario 44: "Review-loop INPUT_REQUIRED gate, qa_finalize close-out, and duplicate-verifier guard (e8fe399)"

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

**Focus**: Review loop returns INPUT_REQUIRED (not NEEDS_WORK) for missing captures and flips to PASS once added; qa_finalize exits cleanly; verifier is not double-spawned after a follow-up to a PASS scenario pane

**Steps**:
1. **Set up isolated pm install.** Create venv and editable-install pm:
```
python3 -m venv /tmp/pm-venv && source /tmp/pm-venv/bin/activate
cd /workspace && pip install -e .
export PYTHONPATH=/workspace   # shadow container's /opt/pm-src master
pm which                       # confirm it prints /workspace, NOT /opt/pm-src
```

2. **Create throwaway pm project with a bug PR.**
```
TEST_DIR=/workspace/pm-test-$(date +%s)
mkdir -p "$TEST_DIR" && cd "$TEST_DIR"
git init -q && git commit --allow-empty -m "init" -q
pm init --backend local --no-import
pm pr add "Pagination off-by-one bug" --plan bugs
```
Capture the printed PR id (e.g. `pr-xxxxxxx`); call it `$BUG_PR`.

3. **Start the pm tmux session** (attach fails under Bash; ignore it):
```
cd "$TEST_DIR" && pm session 2>/dev/null || true
# find the session name:
SESS=$(tmux ls 2>/dev/null | awk -F: '/pm-/{print $1; exit}')
```

4. **Author a substantive bug fixture and commit the fix WITHOUT captures.** Scenario 36 found a dummy `# fix` commit causes the reviewer to flag many gaps beyond captures, preventing PASS in step 8. So commit a real-looking bug + fix:
```
cd "$TEST_DIR"
pm pr start "$BUG_PR" 2>/dev/null || true     # creates workdir (in_progress)
# Get the workdir for the PR:
WD=$(pm pr show "$BUG_PR" | awk '/workdir/{print $2}')
cd "$WD"
cat > paginate.py <<'EOF'
def page(items, page_num, per_page):
start = (page_num - 1) * per_page
return items[start:start + per_page]
EOF
cat > test_paginate.py <<'EOF'
from paginate import page
def test_first_page():
assert page([1,2,3,4,5], 1, 2) == [1,2]
def test_second_page():
assert page([1,2,3,4,5], 2, 2) == [3,4]
EOF
git add -A && git commit -q -m "fix: pagination off-by-one in page()"
# Promote to in_review so review-loop will accept it:
pm pr review "$BUG_PR" --background 2>/dev/null || pm pr set-status "$BUG_PR" in_review
```
Verify `pm/qa/captures/$BUG_PR/impl/{pre-fix,post-fix}/` do **NOT** exist.

5. **Checkpoint 3a — trigger review loop with captures missing.** Use the CLI inside the pm tmux session (don't run from your own shell):
```
tmux send-keys -t "$SESS:0" "pm pr review $BUG_PR --review-loop --review-loop-id manual-$(date +%s)" Enter
```
Wait ~3-5 min for iteration 1 to finish. Inspect the review pane:
```
tmux list-panes -a -F '#{session_name}:#{window_index}.#{pane_index} #{pane_title}'
tmux capture-pane -p -t <review-pane-id> -S -200
```
**Expected:** the verdict block at the bottom prints `INPUT_REQUIRED` (not `NEEDS_WORK`), and one of the cited reasons explicitly mentions missing `pm/qa/captures/$BUG_PR/impl/pre-fix/` or `…/post-fix/` per `pm_core/bug_fix_prompts.py:76-79`. Also confirm `pm tui view` shows the PR badge transition to `⏸<n>` (input_required), not `⟳<n>◓` indefinitely. Note: if the badge stays running, check the verdict transcript fallback in commit 6829b6a — a session-id slug mismatch will leave the orchestrator stuck even though the pane shows the verdict.

6. **Checkpoint 3b — add minimal valid captures and re-run.**
```
cd "$WD"
mkdir -p pm/qa/captures/$BUG_PR/impl/pre-fix pm/qa/captures/$BUG_PR/impl/post-fix
for D in pre-fix post-fix; do
cat > pm/qa/captures/$BUG_PR/impl/$D/manifest.md <<EOF
---
recipe: cli-recording
pr: $BUG_PR
phase: impl/$D
---
## Repro
pytest -xvs test_paginate.py
EOF
echo "pytest output for $D" > pm/qa/captures/$BUG_PR/impl/$D/transcript.log
done
git add -A && git commit -q -m "qa: add pre/post-fix captures"
```
Re-fire the review loop in the pm session:
```
tmux send-keys -t "$SESS:0" "pm pr review $BUG_PR --review-loop --fresh --review-loop-id manual-$(date +%s)" Enter
```
**Expected:** iteration 1 (or 2 if previous iteration_count carried) prints `PASS`. The PR badge advances to PASS / merge-eligible state; no infinite loop. If the reviewer still flags non-capture gaps, accept the failure mode but confirm the captures-specific INPUT_REQUIRED reason from step 5 is gone.

7. **Checkpoint 4 — qa_finalize close-out.** `qa_finalize_prompt.py` is invoked automatically by `pm_core/qa_loop.py:2926` (`_run_qa_finalize_pane`) at the end of the QA loop after all scenario verdicts are PASS + verified. To exercise it, start the QA loop on the now-PASS PR from inside the tmux session:
```
tmux send-keys -t "$SESS:0" "pm pr qa $BUG_PR" Enter
```
Wait for the planner pane + scenario panes to spawn and all scenarios to verify PASS. Then a `qa-finalize` pane appears (registered via `pane_layout` with label `qa-finalize`).
```
tmux list-panes -a -F '#{pane_id} #{pane_title}' | grep -i finalize
tmux capture-pane -p -t <finalize-pane> -S -200
```
**Expected:** the pane emits `FINALIZE_DONE` (or `FINALIZE_BLOCKED` with a clear reason), exits cleanly, no Python stack trace anywhere in the pane or in `pm-debug.log`. The QA loop state shows `state.finalize_verdict` set. Note: if planner produces zero scenarios on this tiny fixture, qa_finalize won't run — in that case stub a single trivial regression scenario into `pm/qa/regression/` before launching `pm pr qa`.

8. **Checkpoint 5 — duplicate-verifier guard (commit e8fe399).** Drive a scenario pane to PASS in the same QA window (reuse step 7's run, or pick any scenario whose verifier has emitted PASS).
- Locate the scenario pane and its verifier pane:
```
tmux list-panes -a -F '#{pane_id} #{pane_title}' | grep -E 'scenario|verif'
```
Note pane ids, and count current verifier panes for this scenario index.
- Send a follow-up question into the scenario's Claude pane (NOT the verifier pane):
```
tmux send-keys -t <scenario-pane> "What was the most surprising thing you found?" Enter
```
- Watch `pm-debug.log` (under `$WD/.pm/logs/` or wherever `_log` writes — `find $WD -name 'pm-debug.log'`) for ~60 seconds:
```
find / -name 'pm-debug.log' 2>/dev/null
tail -F <path-to-pm-debug.log> | grep -iE 'verif|hook_ts|idle_prompt'
```
**Expected:** the log shows `_last_scenario_hook_ts[<idx>] = <ts>` stamped to a fresh `time.time()` *after* the follow-up is sent (per `pm_core/qa_loop.py:1996`), NOT `pop(...)`. No new verifier pane spawns on the stale idle_prompt from the original PASS turn. A second verifier may legitimately spawn ONLY after the scenario actually responds to the follow-up and emits a *new* idle_prompt (gated by `ev_ts > last_ts` at `qa_loop.py:2071-2078`). Re-list panes to confirm exactly the expected verifier count.

9. **Capture evidence per `pm/qa/artifacts/tmux-screen-recording.md` and `cli-recording.md`.** For each checkpoint, save under `pm/qa/captures/$QA_PR_ID/scenarios/44/run-<timestamp>/`:
- `review-pane-input-required.txt` — `tmux capture-pane -p -S -` of the review pane in step 5.
- `review-pane-pass.txt` — same for step 6.
- `finalize-pane.txt` — capture of qa-finalize pane in step 7.
- `duplicate-guard.log` — relevant `pm-debug.log` slice from step 8 showing the post-follow-up timestamp stamp and absence of a duplicate verifier launch.
- `tui-main.txt` — `pm tui view` snapshots at each checkpoint showing PR status badges.
- A `MANIFEST.md` summarizing what each file shows and the overall verdict per checkpoint.

## Artifact Capture Recipes

Available at:
- `/scratch/qa-artifacts/tmux-screen-recording.md`
- `/scratch/qa-artifacts/cli-recording.md`

Read the recipe(s) and follow their capture commands to produce
evidence of this scenario's behavior. Save resulting captures under
`pm/qa/captures/pr-6be8ee6/scenarios/44/` (each recipe's
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
`pm/qa/captures/pr-6be8ee6/scenarios/44/pre-fix/` and the
post-fix recording under `.../post-fix/`. Cross-link the two in each
manifest's `## Files` section, and (per Incidental Bugs below) still
file a PR for the bug.

After producing each capture, commit it and push so it lands on the
PR branch:
- `git add pm/qa/captures/pr-6be8ee6/scenarios/44/`
- `git commit -m "qa: capture for scenario 44"`
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