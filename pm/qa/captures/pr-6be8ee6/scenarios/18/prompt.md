You are running QA scenario 18: "Fresh-install user installs pm into a clean venv and reads the packaged QA library doc"

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

**Focus**: A user with no prior pm install runs pip install against this branch, then runs pm qa docs from a directory outside the source tree and reads

**Steps**:
1. Confirm capture dir does not yet exist, then create it: `mkdir -p pm/qa/captures/pr-6be8ee6/scenarios/18`. Workdir for the rest of the scenario is `/workspace` unless noted.

2. Sanitize the shell to neutralize any host pm install. From `/workspace`, drop into a clean env: `env -i HOME=$HOME TERM=xterm-256color PATH=/usr/bin:/bin bash`. Inside, verify:
- `command -v pm` prints nothing (exit 1 is fine).
- `cd /tmp && python3 -c "import pm_core"` raises `ModuleNotFoundError: No module named 'pm_core'`.
This proves the host's `/opt/pm-src` and `/usr/local/bin/pm` are not shadowing the test. Then `exit` back to the normal shell (we'll re-enter the sanitized env inside the recording for evidence).

3. Create a clean venv outside the source tree and activate it:
- `python3 -m venv /tmp/pm-pkg-venv`
- `source /tmp/pm-pkg-venv/bin/activate`
- Verify `command -v pm` is still empty (the venv was just created, nothing installed).

4. Start an asciinema recording per `pm/qa/artifacts/cli-recording.md`. We have a TTY here (interactive shell), so use the scripted `bash -c "set -x; ..."` form so each command is echoed before its output. Note `asciinema` is at `/usr/bin/asciinema`. Drive the whole install + verification inside the sanitized env so the recording is the load-bearing artifact:
```
asciinema rec pm/qa/captures/pr-6be8ee6/scenarios/18/recording.cast \
-c 'env -i HOME=$HOME TERM=xterm-256color PATH=/tmp/pm-pkg-venv/bin:/usr/bin:/bin VIRTUAL_ENV=/tmp/pm-pkg-venv bash -c "
set -x
command -v pm || echo NO_PM_YET
pip install /workspace
command -v pm
pip show pm | head -5
cd /tmp
pm qa docs | tee /tmp/pm-pkg-venv/pm-qa-docs.log | head -40
python3 -c \"import pm_core, pathlib; p = pathlib.Path(pm_core.__file__).parent / 'docs/qa_library.md'; print(p); print('EXISTS:', p.exists())\"
python3 -c \"import importlib.resources, pm_core; print(importlib.resources.files('pm_core').joinpath('docs/qa_library.md').read_text()[:120])\"
diff <(pm qa docs) /workspace/pm_core/docs/qa_library.md && echo PARITY_OK || echo PARITY_FAIL
"'
```
Also save a plain `transcript.log` (required by the recipe) — easiest: replay `asciinema cat recording.cast > pm/qa/captures/pr-6be8ee6/scenarios/18/transcript.log` after the recording stops, OR re-run the same `bash -c` body outside asciinema piped to `tee transcript.log`.

5. After the recording exits, copy the `pm-qa-docs.log` it produced inside the venv to the capture dir: `cp /tmp/pm-pkg-venv/pm-qa-docs.log pm/qa/captures/pr-6be8ee6/scenarios/18/pm-qa-docs.log`.

6. Assertions on `pm-qa-docs.log` (grep, no eyeballing):
- First non-empty line is `# pm QA library`: `awk 'NF{print; exit}' pm/qa/captures/pr-6be8ee6/scenarios/18/pm-qa-docs.log` returns exactly that.
- Section headings present: `grep -E '^## (The four directories|Authoring|File format)' pm/qa/captures/pr-6be8ee6/scenarios/18/pm-qa-docs.log` shows all three (note the real heading is `## File format` followed by sub-bullets — confirm by `grep -n '^## ' pm_core/docs/qa_library.md` first; adjust the assertion to match the actual heading text).
- The CAUTION callout for pr-7d5d036 is intact: `grep -n '\[!CAUTION\]' pm/qa/captures/pr-6be8ee6/scenarios/18/pm-qa-docs.log` and `grep -n 'pr-7d5d036' pm/qa/captures/pr-6be8ee6/scenarios/18/pm-qa-docs.log` both hit.
- No stack-trace text: `! grep -E 'Traceback|Error: ' pm/qa/captures/pr-6be8ee6/scenarios/18/pm-qa-docs.log`.

7. Parity assertion (the bug scenario 17 originally failed on): `diff <(pm qa docs) /workspace/pm_core/docs/qa_library.md` from inside the activated venv must be empty. The recording's inline diff line should already say `PARITY_OK`; also re-run it explicitly outside the recording and capture exit 0. This is the regression bar — `nl=False` in `pm_core/cli/qa.py:230` is what makes it pass without a trailing newline mismatch.

8. Confirm the doc path is served from the installed wheel, not the source tree: the `pathlib.Path(pm_core.__file__).parent / 'docs/qa_library.md'` line in the recording must print a path under `/tmp/pm-pkg-venv/lib/python*/site-packages/pm_core/docs/qa_library.md` and `EXISTS: True`. The `importlib.resources` call must print the doc's first 120 chars (starts with `# pm QA library`). Together these prove `[tool.setuptools.package-data] pm_core = ["docs/*.md"]` actually shipped the file in the wheel.

9. Write `pm/qa/captures/pr-6be8ee6/scenarios/18/manifest.md` per the cli-recording recipe (frontmatter with `pr: pr-6be8ee6`, `workdir: /workspace`, `captured_at:` today, `recipe: pm/qa/artifacts/cli-recording.md`). Body must include:
- `## Commands` — the exact `asciinema rec ...` invocation and the inner `bash -c` body.
- `## What this demonstrates` — a fresh-install user can `pip install` the branch into a clean venv and `pm qa docs` prints the packaged `qa_library.md` byte-for-byte; the wheel ships `pm_core/docs/qa_library.md` via package-data; parity diff is clean (regression bar from scenario 17).
- `## Files` — `recording.cast`, `transcript.log`, `pm-qa-docs.log`, `manifest.md`.

10. `deactivate`, then `rm -rf /tmp/pm-pkg-venv` to leave no host residue. Commit and push the capture dir per the prompt's git instructions.

11. Verdict: if the parity diff is non-empty, `pm qa docs` errors, the packaged path isn't under `site-packages`, or the CAUTION callout / pr-7d5d036 reference is missing → INPUT_REQUIRED (unless the fix is trivial and clearly inside this PR's scope, e.g. a one-line tweak to `pm_core/cli/qa.py` or `pyproject.toml` package-data). Otherwise PASS.

## Artifact Capture Recipe

Available at:
- `/scratch/qa-artifacts/cli-recording.md`

Read the recipe(s) and follow their capture commands to produce
evidence of this scenario's behavior. Save resulting captures under
`pm/qa/captures/pr-6be8ee6/scenarios/18/` (each recipe's
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
`pm/qa/captures/pr-6be8ee6/scenarios/18/pre-fix/` and the
post-fix recording under `.../post-fix/`. Cross-link the two in each
manifest's `## Files` section, and (per Incidental Bugs below) still
file a PR for the bug.

After producing each capture, commit it and push so it lands on the
PR branch:
- `git add pm/qa/captures/pr-6be8ee6/scenarios/18/`
- `git commit -m "qa: capture for scenario 18"`
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