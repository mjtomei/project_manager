You are running QA scenario 35: "End-to-end integration — bug-fix session produces pre/post captures and QA scenarios save under new layout"

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

**Focus**: Checkpoints 1 & 2 of the integration block — drive a tiny bug PR through the bug-fix flow and a QA scenario run; confirm pm/qa/captures/<pr-id>/impl/{pre-fix,post-fix}/ and …/scenarios/<n>/ populate with

**Steps**:
**Setup (per pm/qa/instructions/tui-manual-test.md)**

1. Install pm into an isolated venv and override PYTHONPATH so the editable clone wins over the container's `/opt/pm-src`:
```
python3 -m venv /tmp/pm-venv && source /tmp/pm-venv/bin/activate
pip install -e /workspace
export PYTHONPATH=/workspace
pm which   # MUST print /workspace/pm_core, not /opt/pm-src
```

2. Create a throwaway test project in the workdir and init git:
```
TEST_DIR=/workspace/pm-test-$(date +%s)
mkdir -p "$TEST_DIR" && cd "$TEST_DIR" && git init
git config user.email qa@example.com && git config user.name "QA Bot"
```

3. Add a trivial Python module with a deterministic off-by-one bug and commit on the parent branch (so the bug exists in the pre-fix tree):
```
cat > buggy.py <<'PY'
def last_index(xs):
# off-by-one: returns len(xs) instead of len(xs)-1
return len(xs)
PY
git add buggy.py && git commit -m "introduce buggy.py with off-by-one"
```

4. Initialize pm in the test dir and add a `plan == bugs` PR describing the defect. Use `pm pr add … --plan bugs` (the bug-fix flow triggers on `plan=="bugs"` per `pm_core/bug_fix_prompts.py:13-20`):
```
pm init --backend local --no-import
pm pr add "Fix last_index off-by-one" --plan bugs
# note the printed PR id, e.g. pr-XXXXXXX — call it $BUG_PR
```
If `pm pr add` does not accept `--plan`, use `pm pr add "Fix last_index off-by-one"` then edit `pm/project.yaml` in the throwaway project ONCE to set `plan: bugs` on that PR (this is the bootstrap exception called out in tui-manual-test.md). Confirm with `pm pr show $BUG_PR` (or `grep -A2 "$BUG_PR" pm/project.yaml`) that `plan: bugs` is set.

5. (Optional but recommended) Sanity-check that the bug-fix flow block is emitted for this PR by running:
```
python3 -c "from pm_core.bug_fix_prompts import _is_bug_pr, _bug_fix_flow_block; \
pr={'id':'$BUG_PR','plan':'bugs'}; \
assert _is_bug_pr(pr); print(_bug_fix_flow_block(pr))"
```
Expect to see the 5 numbered steps and `pm/qa/captures/$BUG_PR/impl/{pre-fix,post-fix}/` interpolated verbatim.

6. Start a pm tmux session from the test dir (attach fails without a TTY — ignore):
```
cd "$TEST_DIR" && pm session 2>/dev/null || true
```

**Checkpoint 1 — manual 5-step bug-fix flow (interpolate `$BUG_PR`, not pr-6be8ee6)**

7. Pre-fix repro + capture. The bug already lives in HEAD, so write a tiny repro driver and record it via the **cli-recording.md** recipe (no TUI involved). Use the no-TTY tmux-wrapped form documented in cli-recording.md §"No-TTY environments":
```
CAPDIR_PRE="$TEST_DIR/pm/qa/captures/$BUG_PR/impl/pre-fix"
mkdir -p "$CAPDIR_PRE"
cat > /tmp/repro.py <<'PY'
from buggy import last_index
xs=[10,20,30]
print("last_index([10,20,30]) =", last_index(xs))
print("xs[last_index(xs)] =", xs[last_index(xs)])   # IndexError on buggy code
PY
# Prefer asciinema if present; otherwise fall back to tee per the recipe.
if command -v asciinema >/dev/null; then
tmux -L scaffold new-session -d -s rec -x 100 -y 30
tmux -L scaffold send-keys -t rec:0.0 \
"asciinema rec --quiet --overwrite $CAPDIR_PRE/recording.cast \
-c 'bash -c \"set -x; python3 /tmp/repro.py\"' \
|& tee $CAPDIR_PRE/transcript.log" Enter
# wait for asciinema to exit, then: tmux -L scaffold kill-server
else
{ set -x; python3 /tmp/repro.py; } 2>&1 | tee "$CAPDIR_PRE/transcript.log" || true
# note the asciinema fallback in the manifest
fi
```
Then write `$CAPDIR_PRE/manifest.md` using the frontmatter template from cli-recording.md §"Manifest format" — fill `pr: $BUG_PR`, `recipe: pm/qa/artifacts/cli-recording.md`, the exact command(s), a `## What this demonstrates` paragraph naming the IndexError as the pre-fix symptom, and a `## Files` section.

8. Write a failing test that codifies the repro:
```
cat > test_buggy.py <<'PY'
from buggy import last_index
def test_last_index_returns_final_index():
assert last_index([10,20,30]) == 2
PY
python3 -m pytest test_buggy.py -x   # MUST fail with assertion 3 == 2
```

9. Apply the fix and commit:
```
sed -i 's/return len(xs)/return len(xs) - 1/' buggy.py
git add buggy.py test_buggy.py && git commit -m "fix off-by-one in last_index + test"
```

10. Verify with the test:
```
python3 -m pytest test_buggy.py -v   # MUST pass
```

11. Post-fix manual re-verify + capture under `…/impl/post-fix/`. Repeat the cli-recording.md capture from step 7, this time pointing at `CAPDIR_POST="$TEST_DIR/pm/qa/captures/$BUG_PR/impl/post-fix"`, running the same `/tmp/repro.py`. Expected: prints `last_index([10,20,30]) = 2` and `xs[...] = 30`, no IndexError. Write the corresponding `manifest.md`.

12. Checkpoint-1 assertions — verify directly:
```
ls "$TEST_DIR/pm/qa/captures/$BUG_PR/impl/pre-fix/"
ls "$TEST_DIR/pm/qa/captures/$BUG_PR/impl/post-fix/"
# both MUST contain manifest.md AND a recording artifact
# (recording.cast if asciinema available, otherwise transcript.log only — manifest must note the fallback)
grep -E "^recipe:|^pr:" "$TEST_DIR/pm/qa/captures/$BUG_PR/impl/pre-fix/manifest.md"
grep -E "^recipe:|^pr:" "$TEST_DIR/pm/qa/captures/$BUG_PR/impl/post-fix/manifest.md"
# Each manifest's ## Files section MUST reference a file that actually exists in the same dir.
```

**Checkpoint 2 — QA scenario saves under `scenarios/<n>/` layout**

13. List the available QA instructions/regression tests so you can pick a real entry point:
```
pm qa list
```
Pick an instruction id that can run against the throwaway project (e.g. `tui-manual-test`, or any item under the Instructions section).

14. Drive a QA scenario against the fixed PR using a real `pm qa` entry point. Per `pm_core/cli/qa.py:310-332`, `pm qa run <instruction-id> --pr <pr-id>` creates a boilerplate single-scenario QA plan and runs it through the same child-session infra as auto-start, which routes captures through `_write_scenario_capture_file` (pm_core/qa_loop.py:1111-1130) into `pm/qa/captures/<pr-id>/scenarios/<n>/`:
```
cd "$TEST_DIR"
pm qa run <chosen-instruction-id> --pr "$BUG_PR"
```
If `pm qa run` requires the PR to be in a specific status (e.g. `in_review`/`qa`), advance it first via `pm pr status "$BUG_PR" <status>` (use `pm pr --help` to discover the exact subcommand). If `pm qa run` cannot be driven to completion non-interactively in this environment, fall back to `pm qa regression <regression-id>` from inside a pane of the throwaway tmux session (see `pm_core/cli/qa.py:253-307`) — note in the manifest which entry point you used and why.

15. Checkpoint-2 assertions — verify the scenario captures landed in the new layout:
```
ls "$TEST_DIR/pm/qa/captures/$BUG_PR/scenarios/"
# expect at least one numbered subdir, e.g. scenarios/1/
N=$(ls "$TEST_DIR/pm/qa/captures/$BUG_PR/scenarios/" | head -1)
ls "$TEST_DIR/pm/qa/captures/$BUG_PR/scenarios/$N/"
# MUST contain: manifest.md (or manifest.yaml) AND a recording (recording.cast)
#               AND transcript.log — per tmux-screen-recording.md / cli-recording.md
```
If only `prompt.md` / `verdict.md` appear (i.e. the worker recorded no artifacts), the checkpoint FAILS — record that as the observed outcome and continue.

**Capture the orchestration evidence under scenario 35's dir**

16. Save the orchestration trace for this scenario under the *real* PR's scenario 35 dir (this is the artifact downstream review will read):
```
SC35=/workspace/pm/qa/captures/pr-6be8ee6/scenarios/35
mkdir -p "$SC35"
```
Produce, at minimum:
- `transcript.log` — a tee'd log of every command run during steps 1–15 (or a `script -q -c` recording of the whole session).
- `recording.cast` — asciinema recording of the same session if asciinema is available (note the fallback in the manifest if not).
- `manifest.md` — frontmatter per cli-recording.md (`pr: pr-6be8ee6`, `recipe: pm/qa/artifacts/cli-recording.md`, `workdir: /workspace`, `test_project: $TEST_DIR`, `captured_at: <ISO date>`), a `## Commands` block with the actual pasted commands, a `## What this demonstrates` paragraph naming checkpoints 1 and 2 from pm/specs/pr-6be8ee6/qa.md §"End-to-end QA + bug-fix flow integration", a `## Findings` section recording PASS/FAIL for each assertion in steps 12 and 15 with the throwaway `$BUG_PR` id quoted, and a `## Files` section listing every file in `$SC35`.
- A copy (or tarball) of `$TEST_DIR/pm/qa/captures/$BUG_PR/` placed at `$SC35/throwaway-captures/` so a reviewer can inspect the pre-fix/post-fix/scenarios artifacts without re-running the scenario.

17. Final verdict line in `$SC35/manifest.md`: PASS iff every assertion in steps 12 and 15 held; otherwise FAIL with a one-line reason quoting the failed assertion.

## Artifact Capture Recipes

Available at:
- `/scratch/qa-artifacts/tmux-screen-recording.md`
- `/scratch/qa-artifacts/cli-recording.md`

Read the recipe(s) and follow their capture commands to produce
evidence of this scenario's behavior. Save resulting captures under
`pm/qa/captures/pr-6be8ee6/scenarios/35/` (each recipe's
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
`pm/qa/captures/pr-6be8ee6/scenarios/35/pre-fix/` and the
post-fix recording under `.../post-fix/`. Cross-link the two in each
manifest's `## Files` section, and (per Incidental Bugs below) still
file a PR for the bug.

After producing each capture, commit it and push so it lands on the
PR branch:
- `git add pm/qa/captures/pr-6be8ee6/scenarios/35/`
- `git commit -m "qa: capture for scenario 35"`
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