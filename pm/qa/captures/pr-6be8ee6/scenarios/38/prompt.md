You are running QA scenario 38: "pm qa CLI surface across all three categories"

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

**Focus**: pm qa list/show/edit/add-instruction/add-regression/add-artifact/author-* command behavior, clobber protection, frontmatter resilience, and removal of the old pm qa add command

**Steps**:
## Setup (per tui-manual-test.md)

1. Set up an isolated pm install in a venv from the /workspace clone, and override PYTHONPATH so the editable install shadows the container's /opt/pm-src copy:
```
python3 -m venv /tmp/pm-venv && source /tmp/pm-venv/bin/activate
cd /workspace && pip install -e .
export PYTHONPATH=/workspace
pm which   # must print /workspace, not /opt/pm-src
```

2. Create a throwaway test project and `git init` it:
```
TEST_DIR=/tmp/pm-qa-cli-$(date +%s)
mkdir -p "$TEST_DIR" && cd "$TEST_DIR"
git init
pm init --backend local --no-import
pm pr add "Seed PR"   # only so the project is non-empty; not required for qa CLI tests
```
(A tmux session is not required for any step below — every command under test is a plain CLI invocation. Do NOT run `pm session` for this scenario; if you do, run subsequent commands inside a pane of that session per the instruction file.)

## Verify the old `pm qa add` is gone

3. Run `pm qa add foo` from inside `$TEST_DIR`. Expected: click prints a "No such command 'add'." usage error (with the Usage: line for `pm qa`), exit code != 0, and **no Python traceback**. Confirm by also running `pm qa --help` — the listed subcommands must include `add-instruction`, `add-regression`, `add-artifact`, `author-instruction`, `author-regression`, `author-artifact`, `list`, `show`, `edit`, `docs`, `regression`, `run`, `debug`, `launch`, `standalone`, `mocks`, but NOT a bare `add`.

## add-* commands create files with correct frontmatter

4. With `EDITOR=true` so the editor exits immediately, create one file per category:
```
EDITOR=true pm qa add-instruction my-inst
EDITOR=true pm qa add-regression my-reg
EDITOR=true pm qa add-artifact my-art
```
For each, confirm:
- stdout contains `Created: …/pm/qa/<category>/my-<x>.md`
- exit code 0
- The file exists at `pm/qa/instructions/my-inst.md`, `pm/qa/regression/my-reg.md`, `pm/qa/artifacts/my-art.md` respectively
- The frontmatter contains both `title: My Inst` (etc., title-cased from the slug) and a `description:` line (value will be empty, written by the template)
- The frontmatter does NOT contain a `tags:` field (the `_ADD_TEMPLATES` in `pm_core/cli/qa.py` intentionally omit it; only the `mocks add` template still emits `tags: []`)
- Each body has the category-appropriate section headers (instructions → `## Setup` / `## Test Steps` / `## Expected Behavior` / `## Reporting`; regression → `## Scenarios` / `## Reporting`; artifacts → `## When to use` / `## What this recipe produces` / `## Capture` / `## Manifest format`)

## Clobber protection on add-*

5. Re-run `EDITOR=true pm qa add-instruction my-inst`. Expected: stderr `Already exists: …/pm/qa/instructions/my-inst.md`, exit code 1, and the existing file's mtime and contents are unchanged (capture mtime with `stat -c %Y` before and after to confirm). Repeat the same check for `add-regression my-reg` and `add-artifact my-art`.

## `pm qa list`

6. Run `pm qa list` and confirm output contains three labeled sections **in this order**: `Instructions (N):`, `Regression Tests (N):`, `Artifact Recipes (N):` — each on its own line with a parenthesised count, followed by `  <id>: <Title> — <description>` rows (description segment omitted when empty). Verify the counts include the newly added items (≥1 each) and that `my-inst`, `my-reg`, `my-art` appear under their correct sections. Note: `mocks` is NOT shown by `pm qa list` (only the three categories above); do not assert a mocks section.

## `pm qa show` — auto-resolution and explicit category

7. Run each of these without `-c` and confirm exit 0 and that stdout starts with `# <Title>` then the path line `[<absolute path>]` then a blank line then the body:
```
pm qa show my-art
pm qa show my-reg
pm qa show my-inst
```
Then run `pm qa show -c artifacts my-art` and confirm identical output to step 7's `my-art` call. Finally run `pm qa show -c instructions my-art` and confirm it fails with `QA item not found: my-art` on stderr and exit code 1 (explicit wrong category should NOT fall back to auto-resolution).

## `pm qa edit`

8. Run `EDITOR=true pm qa edit my-art` and confirm exit code 0 and no traceback. Repeat once with explicit category: `EDITOR=true pm qa edit -c artifacts my-art`. Then run `EDITOR=true pm qa edit does-not-exist` and confirm exit 1 with `QA item not found: does-not-exist`.

## Frontmatter resilience

9. For each of the three variants below, edit `pm/qa/instructions/my-inst.md`, then run `pm qa list` and `pm qa show my-inst` and confirm: exit 0, no Python traceback, the row appears in the Instructions section with empty/fallback values where the field is missing, and `show` prints the body (everything after the closing `---`, or the whole file when there's no frontmatter). Use these variants in order, restoring or overwriting between each:

(a) **No frontmatter delimiters at all** — overwrite the file so it contains only `## Setup\n\nsome body text\n`. Expected: `list` row shows `my-inst: My Inst` (title falls back to slug-titlecased per `_parse_frontmatter` returning `{}`), no description after `—`. `show` prints `# My Inst` then `[<path>]` and the raw body.

(b) **Legacy `tags: [foo]` field present** — write a valid frontmatter block with `title: My Inst`, `description: desc`, AND `tags: [foo]`. Expected: row reads `my-inst: My Inst — desc`; `show` does not error and does not print the tags (the CLI's `show` does not render tags).

(c) **Missing `description:` line** — write a frontmatter block with only `title: Custom Title` and no description key. Expected: row reads `my-inst: Custom Title` with no `— …` suffix; `show` prints `# Custom Title`, then immediately the path line (no description line), then body.

Also exercise one malformed-YAML case: write `---\ntitle: : :\n---\nbody\n`. Expected: `_parse_frontmatter` catches the YAMLError, treats meta as empty, so `list` and `show` still succeed with slug-derived title.

## `pm qa author-*` — path resolution, prompt embedding, refuse-clobber

10. Confirm the resolved target path before launch. With `another-inst` not yet existing, run:
```
pm qa author-instruction another-inst &
AUTHOR_PID=$!
sleep 2
```
Then capture the launched claude command's argv from `/proc` (the launcher passes the full prompt as the final argv to `claude`):
```
# find the claude child of AUTHOR_PID
pgrep -P $AUTHOR_PID -a
# then for the claude pid:
tr '\0' '\n' < /proc/<claude_pid>/cmdline > /tmp/claude-argv.txt
```
Verify in `/tmp/claude-argv.txt`:
- The final argv element (the prompt) contains the literal substring `pm/qa/instructions/another-inst.md` (the target path that `_author_path` resolves to — see `pm_core/cli/qa.py:179`).
- The prompt embeds the qa_library reference: it must contain the section header `## Reference: pm QA library` AND substantive content from `pm_core/docs/qa_library.md` (e.g. grep the argv file for a stable phrase that appears in `qa_library.md` such as `Frontmatter` or a category-section heading — first run `pm qa docs | head -40` in another shell to pick a stable phrase, then confirm it also appears in `/tmp/claude-argv.txt`).
- Argv also includes `--session-id <uuid>` (new session, not `--resume`).
Then kill the launcher: `kill $AUTHOR_PID; wait $AUTHOR_PID 2>/dev/null`. Confirm `pm/qa/instructions/another-inst.md` was NOT created (the authoring flow only writes when the Claude session writes it; killing before any response leaves nothing).

11. Refuse-clobber on author-*: create the file out-of-band so the path exists, then verify each author-* command refuses:
```
EDITOR=true pm qa add-instruction another-inst    # now the file exists
pm qa author-instruction another-inst
```
Expected: stderr `Already exists: …/pm/qa/instructions/another-inst.md`, exit code 1, and `claude` is NOT launched (verify with `pgrep -a claude` returning no new process spawned by the command). Repeat the same pattern for `author-regression` (after `add-regression another-reg`) and `author-artifact` (after `add-artifact another-art`).

## Final sanity sweep

12. Run `pm qa list` one more time and confirm all created files (`my-inst`, `my-reg`, `my-art`, `another-inst`, `another-reg`, `another-art`) appear under their correct sections with the counts incremented accordingly, and no stack traces appear anywhere in the transcript from steps 3–11.

## Reporting

For each numbered step report PASS/FAIL with one line of evidence (the exact command output or argv excerpt). End with an overall PASS/FAIL.

## Artifact Capture Recipe

Available at:
- `/scratch/qa-artifacts/cli-recording.md`

Read the recipe(s) and follow their capture commands to produce
evidence of this scenario's behavior. Save resulting captures under
`pm/qa/captures/pr-6be8ee6/scenarios/38/` (each recipe's
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
`pm/qa/captures/pr-6be8ee6/scenarios/38/pre-fix/` and the
post-fix recording under `.../post-fix/`. Cross-link the two in each
manifest's `## Files` section, and (per Incidental Bugs below) still
file a PR for the bug.

After producing each capture, commit it and push so it lands on the
PR branch:
- `git add pm/qa/captures/pr-6be8ee6/scenarios/38/`
- `git commit -m "qa: capture for scenario 38"`
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