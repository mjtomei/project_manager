You are running QA scenario 43: "End-to-end bug-fix flow produces pre/post captures and QA scenarios save under new layout"

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

**Focus**: Bug-fix session writes impl/pre-fix/ and impl/post-fix/ with manifests; QA scenarios for that PR land under scenarios/<n>/ with manifest+recording+transcript per artifact recipes

**Steps**:
## Setup

1. Install pm into a venv (the container's `/opt/pm-src` shadows editable installs via `PYTHONPATH`, so override):
```
python3 -m venv /tmp/pm-venv && source /tmp/pm-venv/bin/activate
cd /workspace && pip install -e .
export PYTHONPATH=/workspace
pm which   # must print /workspace, NOT /opt/pm-src
```

2. Create a throwaway test project (use your workdir if you have one, else `/tmp`):
```
TEST_DIR=/tmp/pm-test-$(date +%s)
mkdir -p "$TEST_DIR" && cd "$TEST_DIR"
git init -q && git commit --allow-empty -m "init" -q
```

3. Initialize pm in the throwaway project:
```
pm init --backend local --no-import
```

4. Introduce a tiny deterministic defect on a new git branch in the throwaway project. Example:
```
git checkout -b fix-defect
cat > buggy.py <<'EOF'
def add(a, b):
return a - b   # BUG: should be +
if __name__ == "__main__":
assert add(2, 3) == 5, f"add(2,3) returned {add(2,3)}"
print("OK")
EOF
git add buggy.py && git commit -q -m "introduce defect"
# Confirm the repro fails:
python3 buggy.py   # should raise AssertionError
```

5. File a bug PR for the defect (note the `pr-XXXXXXX` ID printed):
```
pm pr add 'fix-defect' --plan bugs \
--description 'Run `python3 buggy.py` in the repo root; AssertionError "add(2,3) returned -1" — should print OK.'
P=$(pm pr list --plan bugs --json 2>/dev/null | python3 -c 'import json,sys;print(json.load(sys.stdin)[-1]["id"])' \
|| pm pr list --plan bugs | tail -1 | awk '{print $1}')
echo "Bug PR: $P"
```

## Drive the bug-fix flow (the real user-facing surface)

6. Start the pm tmux session from the throwaway project (attach will fail under Claude's Bash with no TTY — that is expected; the session still exists):
```
cd "$TEST_DIR" && pm session 2>/dev/null || true
tmux ls   # confirm the pm-<...> session exists
```

7. The bug-fix flow is driven by the `bug-fix-impl` watcher, which must run *inside* the pm tmux session (it requires `in_tmux()`). Launch it via a new pane inside the test session — do not run it in your own terminal:
```
PM_SESSION=$(tmux ls -F '#{session_name}' | grep '^pm-' | head -1)
tmux send-keys -t "$PM_SESSION":0 \
"cd $TEST_DIR && export PYTHONPATH=/workspace && pm watcher start bug-fix-impl" Enter
```
The watcher generates the 5-step bug-fix prompt (`pm_core/bug_fix_prompts.py`) into a child Claude window: manual pre-fix repro → write failing test → fix → post-fix repro → verify. If no Claude is wired, simulate by performing each step yourself in a pane inside the pm session (do NOT `cd` out of the test dir).

8. As you (or Claude) execute each step, the prompt directs captures to `pm/qa/captures/<P>/impl/pre-fix/` and `…/impl/post-fix/`. Each capture should follow the artifact recipes in `pm/qa/artifacts/cli-recording.md` / `tmux-screen-recording.md` (manifest.md + recording.cast and/or transcript.log + screens/).

## Verify bug-fix outputs

9. After the watcher reports done (or your manual run completes), inspect on disk inside `$TEST_DIR`:
```
tree pm/qa/captures/$P/impl/   # or: find pm/qa/captures/$P/impl -maxdepth 3
```
Expect:
- `pm/qa/captures/$P/impl/pre-fix/manifest.md` plus at least one capture artifact (recording.cast or transcript.log) showing the AssertionError.
- `pm/qa/captures/$P/impl/post-fix/manifest.md` plus an artifact showing `python3 buggy.py` printing `OK`.
- Each `manifest.md` references the schemas from `pm/qa/artifacts/`.

10. Confirm the fix is actually committed on the PR branch and the defect is gone:
```
git log --oneline -5
python3 buggy.py    # must print OK, exit 0
```

## Drive a QA scenario against the same PR

11. From a new pane inside the pm tmux session, run a single QA scenario against the bug-fix PR using the real user-facing surface `pm qa run`:
```
pm qa list                                # see available instruction IDs
tmux send-keys -t "$PM_SESSION":0 \
"cd $TEST_DIR && pm qa run <instruction_id> --pr $P" Enter
```
(Pick any small instruction; if none exists, create one with `pm qa add-instruction smoke` and fill in trivial steps before running.) `pm qa run` builds a single-scenario plan and dispatches via the same `qa_loop` worker code path (`pm_core/cli/qa.py:310`, `pm_core/qa_loop.py`).

12. After the run finishes (`Result: PASS/FAIL/...` printed), verify the scenario captures landed at the documented layout — the writer is `_write_scenario_capture_file` in `pm_core/qa_loop.py:1114`:
```
ls pm/qa/captures/$P/scenarios/
ls pm/qa/captures/$P/scenarios/1/
```
Expect at minimum `manifest.md`, the scenario `prompt.md`, a `verdict*.md`/transcript file, and a `recording.cast` (or equivalent transcript) matching `pm/qa/artifacts/tmux-screen-recording.md` / `cli-recording.md` schemas.

## Save evidence

13. Copy the throwaway capture tree into THIS scenario's captures dir as evidence:
```
EVIDENCE=/workspace/pm/qa/captures/pr-6be8ee6/scenarios/43/throwaway-captures
mkdir -p "$EVIDENCE"
cp -a "$TEST_DIR/pm/qa/captures/$P" "$EVIDENCE/"
ls -R "$EVIDENCE" | head -60
```
Also record the verdict in `pm/qa/captures/pr-6be8ee6/scenarios/43/manifest.md` (pass iff steps 9, 10, and 12 all succeed; fail otherwise with the failing assertion noted).

## Artifact Capture Recipes

Available at:
- `/scratch/qa-artifacts/tmux-screen-recording.md`
- `/scratch/qa-artifacts/cli-recording.md`

Read the recipe(s) and follow their capture commands to produce
evidence of this scenario's behavior. Save resulting captures under
`pm/qa/captures/pr-6be8ee6/scenarios/43/` (each recipe's
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
`pm/qa/captures/pr-6be8ee6/scenarios/43/pre-fix/` and the
post-fix recording under `.../post-fix/`. Cross-link the two in each
manifest's `## Files` section, and (per Incidental Bugs below) still
file a PR for the bug.

After producing each capture, commit it and push so it lands on the
PR branch:
- `git add pm/qa/captures/pr-6be8ee6/scenarios/43/`
- `git commit -m "qa: capture for scenario 43"`
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