You are running QA scenario 22: "pm qa regression replaces pm tui test, with unified filing addendum for bugs + improvements"

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

**Focus**: Verify the runner finds a test by id, exits 1 on unknown ids, requires a running pm tmux session, and that the assembled prompt includes the unified filing addendum (covering BOTH --plan bugs and --plan

**Steps**:
1. **Per tui-manual-test.md, set up a throwaway pm project.**
- Create venv & install pm:
```
python3 -m venv /tmp/pm-venv && source /tmp/pm-venv/bin/activate
cd /workspace && pip install -e .
export PYTHONPATH=/workspace
pm which   # should print /workspace, not /opt/pm-src
```
- Make a throwaway project:
```
TEST_DIR=/tmp/pm-test-$(date +%s)
mkdir -p "$TEST_DIR" && cd "$TEST_DIR" && git init
pm init --backend local --no-import
pm pr add "Add login feature"
```
- Start the pm session (ignore the attach error — the session is still created):
```
cd "$TEST_DIR" && pm session 2>/dev/null || true
tmux ls   # confirm a session whose name starts with "pm-" exists
```

2. **Confirm `pm tui test` is not a real subcommand.** Run `pm tui test --list`; expect exit non-zero and a Click "No such command 'test'." error on stderr. (This justifies why the regression runner is the replacement surface.)

3. **Create the regression fixture.** From `$TEST_DIR`, write `pm/qa/regression/smoke.md` directly (don't use `pm qa add-regression`, which opens `$EDITOR`):
```
mkdir -p pm/qa/regression
cat > pm/qa/regression/smoke.md <<'EOF'
---
title: Smoke
description: Trivial smoke check for the regression runner
---
Bring up TUI and report PASS.
EOF
```
Verify the test is discoverable: `pm qa list` should show it under `Regression Tests` as `smoke: Smoke`.

4. **Install the launch-claude-stub shim** so we can inspect the assembled prompt without actually invoking Claude. `launch_claude` calls `shutil.which("claude")` and execs `claude [flags...] <prompt>` (prompt is the last positional argv). Shim by putting a fake `claude` first on `PATH`:
```
STUB_DIR=$(mktemp -d)
PROMPTS_DIR="$STUB_DIR/prompts"
mkdir -p "$PROMPTS_DIR"
cat > "$STUB_DIR/claude" <<'EOF'
#!/usr/bin/env bash
# launch-claude-stub: record argv (prompt is the last arg) and exit 0
ts=$(date +%s%N)
printf '%s\n' "$@" > "$PROMPTS_DIR/argv-$ts.txt"
# The prompt is the final positional arg
eval "last=\${$#}"
printf '%s' "$last" > "$PROMPTS_DIR/prompt-$ts.txt"
exit 0
EOF
chmod +x "$STUB_DIR/claude"
export PATH="$STUB_DIR:$PATH"
command -v claude   # confirm it resolves to $STUB_DIR/claude
```
Sanity-check capture: `claude --foo bar 'hello world'` and confirm `$PROMPTS_DIR/prompt-*.txt` contains exactly `hello world`. This shim must NOT short-circuit the runner's early-exit paths (unknown id / no tmux session) — those `raise SystemExit(1)` before `launch_claude` ever runs, so they don't touch the stub.

5. **Happy path (no flag).** From `$TEST_DIR`:
```
rm -f "$PROMPTS_DIR"/*.txt
pm qa regression smoke
echo "exit=$?"
ls "$PROMPTS_DIR"
cat "$PROMPTS_DIR"/prompt-*.txt
```
Expect exit 0 and the captured prompt to contain:
- a `## Session Context` section naming the pm tmux session (`pm-...`)
- a `## Captures` section that names `pm/qa/captures/regression/<test-id>/<timestamp>/` literally (the path is a template the agent fills in, not interpolated)
- a `## QA Regression Test: Smoke` heading followed by the body `Bring up TUI and report PASS.`
- **no** `## Filing Findings` section.

6. **`--file-prs` adds the unified addendum.**
```
rm -f "$PROMPTS_DIR"/*.txt
pm qa regression smoke --file-prs
PROMPT_PRS=$(cat "$PROMPTS_DIR"/prompt-*.txt)
echo "$PROMPT_PRS"
```
Confirm the prompt now has a `## Filing Findings` section AND that this section contains BOTH `pm pr add` with `--plan bugs` and `pm pr add` with `--plan improvements`, plus the de-dup guidance referencing `pm pr list --plan bugs` / `--plan improvements`. Save the file as `prompt-file-prs.txt` for the next step.

7. **`--file-bugs` (hidden alias) produces a byte-identical prompt.**
```
cp "$PROMPTS_DIR"/prompt-*.txt /tmp/prompt-file-prs.txt
rm -f "$PROMPTS_DIR"/*.txt
pm qa regression smoke --file-bugs
cp "$PROMPTS_DIR"/prompt-*.txt /tmp/prompt-file-bugs.txt
diff -u /tmp/prompt-file-prs.txt /tmp/prompt-file-bugs.txt && echo "IDENTICAL"
```
Expect exit 0 from both and `diff` to print nothing (`IDENTICAL`). This proves the alias is unified — not bugs-only — because both flags set the same `file_prs` Click dest. Also confirm `pm qa regression --help` does NOT mention `--file-bugs` (it's `hidden=True`).

8. **Unknown id exits non-zero before launching Claude.**
```
rm -f "$PROMPTS_DIR"/*.txt
pm qa regression no-such-test
echo "exit=$?"
ls "$PROMPTS_DIR"   # must be empty — stub was never called
```
Expect exit 1, stderr containing `Unknown regression test: no-such-test`, and stdout containing `Run 'pm qa list' to see available tests.` No prompt file should have been written.

9. **Missing tmux session exits non-zero before launching Claude.** Stop the pm session, then re-run:
```
tmux kill-server 2>/dev/null || true
rm -f "$PROMPTS_DIR"/*.txt
pm qa regression smoke
echo "exit=$?"
ls "$PROMPTS_DIR"   # must still be empty
```
Expect exit 1 and stderr containing `No pm tmux session found. Start one with 'pm session'.` No prompt file written.

10. **Record evidence per cli-recording.md** under `pm/qa/captures/pr-6be8ee6/scenarios/22/`:
- asciinema recording of steps 5–9 (`asciinema rec scenario-22.cast`)
- a transcript with the diff output, the two prompt files (`prompt-file-prs.txt`, `prompt-file-bugs.txt`), and the `pm qa list` output
- `git add` / `commit` the captures from the project repo (`/workspace`), not from `$TEST_DIR`.

## Artifact Capture Recipe

Available at:
- `/scratch/qa-artifacts/cli-recording.md`

Read the recipe(s) and follow their capture commands to produce
evidence of this scenario's behavior. Save resulting captures under
`pm/qa/captures/pr-6be8ee6/scenarios/22/` (each recipe's
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
`pm/qa/captures/pr-6be8ee6/scenarios/22/pre-fix/` and the
post-fix recording under `.../post-fix/`. Cross-link the two in each
manifest's `## Files` section, and (per Incidental Bugs below) still
file a PR for the bug.

After producing each capture, commit it and push so it lands on the
PR branch:
- `git add pm/qa/captures/pr-6be8ee6/scenarios/22/`
- `git commit -m "qa: capture for scenario 22"`
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