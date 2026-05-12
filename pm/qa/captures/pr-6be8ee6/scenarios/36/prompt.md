You are running QA scenario 36: "Review-loop INPUT_REQUIRED gate and duplicate-verifier guard"

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

**Focus**: Checkpoint 3 (missing captures → INPUT_REQUIRED, not NEEDS_WORK; flips to PASS once added without infinite loop) and checkpoint 5 (commit e8fe399: follow-up after PASS does not spawn a second verifier on

**Steps**:
## Setup

1. Install pm into a virtual environment from the editable clone, and make sure the editable install is what is being exercised (the container ships pm at `/opt/pm-src` via `PYTHONPATH`, which shadows pip's editable install):
```
python3 -m venv /tmp/pm-venv && source /tmp/pm-venv/bin/activate
pip install -e /workspace
export PYTHONPATH=/workspace
pm which   # must print /workspace, not /opt/pm-src
```

2. Create a throwaway test project and initialize pm:
```
TEST_DIR=/tmp/pm-test-$(date +%s)
mkdir -p "$TEST_DIR" && cd "$TEST_DIR"
git init
pm init --backend local --no-import
```

3. Create a `bugs` plan (the bug-fix flow is gated on `pr.plan == "bugs"` per `pm_core/bug_fix_prompts.py:20`) and add a PR inside it. Use `pm plan add` / `pm pr add --plan bugs`:
```
pm plan add bugs           # or whatever creates a plan with id "bugs"
pm pr add "Fix off-by-one in pagination" --plan bugs
# capture the printed pr-id (e.g. pr-xxxxxxx) for later as $PR_ID
```
If `pm plan add` chooses a different slug, edit `pm/project.yaml` once so the PR entry has `plan: bugs` and that plan exists — this is fixture-only bootstrapping per the instruction file caveat.

4. Inside the test project, simulate a committed fix on the PR's branch (any tiny code change + commit). Do NOT create `pm/qa/captures/$PR_ID/impl/pre-fix/` or `.../impl/post-fix/`. Confirm those directories do not exist:
```
test ! -d pm/qa/captures/$PR_ID/impl/pre-fix
test ! -d pm/qa/captures/$PR_ID/impl/post-fix
```

5. Start the throwaway tmux session from the test directory (ignore the attach error — Bash has no TTY):
```
cd "$TEST_DIR" && pm session 2>/dev/null || true
```
From outside, inspect with `pm tui view`, `tmux capture-pane -p -t <session>:<window>.<pane> -S -`, and drive input via `tmux send-keys`. Do not run pm commands from your shell — run them in a new pane inside the test tmux session.

## Checkpoint 3 — Missing captures must yield INPUT_REQUIRED, then PASS once added

6. In the TUI, focus the PR and invoke the review action (the user-facing entry, equivalent to `pm pr review --review-loop` — see `pm_core/cli/pr.py:1332`). Confirm the review pane spawns and a review_loop iteration runs.

7. Wait for the first verdict. Capture the review pane (`tmux capture-pane -p`). Expected: verdict is **INPUT_REQUIRED**, and the body cites missing `pm/qa/captures/<PR_ID>/impl/pre-fix/` and/or `impl/post-fix/` captures (per the bug-fix review checklist in `pm_core/bug_fix_prompts.py:76-79`). It must NOT be NEEDS_WORK.

8. While paused on INPUT_REQUIRED, confirm the TUI marks the PR with the red INPUT_REQUIRED status (`pm_core/tui/app.py:880`) and that the review loop is still alive (not exited) — `state.input_required = True` and the pane is polling for follow-up (`review_loop.py:317-324`).

9. From a tmux pane inside the test session, populate plausible pre/post-fix captures so the next review iteration sees them:
```
mkdir -p pm/qa/captures/$PR_ID/impl/pre-fix pm/qa/captures/$PR_ID/impl/post-fix
printf 'pre-fix repro transcript\n' > pm/qa/captures/$PR_ID/impl/pre-fix/repro.txt
printf 'post-fix verification transcript\n' > pm/qa/captures/$PR_ID/impl/post-fix/verify.txt
git add pm/qa/captures && git commit -m "qa: add pre/post-fix captures"
```

10. In the still-open review pane, send a follow-up nudge to the reviewer (e.g. `tmux send-keys ... "Captures are now under pm/qa/captures/$PR_ID/impl/; re-evaluate." Enter`). This satisfies the INPUT_REQUIRED follow-up path (`review_loop._wait_for_follow_up_verdict`).

11. Watch the review_loop iterate. Expected: a follow-up verdict of **PASS** within a small bounded number of iterations (max is 10 — see `review_loop.py:363`). Confirm:
- `state.iteration` does not hit the cap;
- the loop exits cleanly with PASS (not stuck re-INPUT_REQUIRED, which would be coerced to NEEDS_WORK per `review_loop.py:337-338`);
- no infinite loop — record the iteration count in the transcript.

## Checkpoint 5 — Duplicate-verifier guard (commit e8fe399)

This guards `pm_core/qa_loop.py:1981-1996`: after a verifier **FLAGS** a PASS, qa_loop itself sends a follow-up into the scenario pane and must stamp `_last_scenario_hook_ts` to `time.time()` so the stale pre-follow-up `idle_prompt` does not re-trigger `extract_verdict_from_transcript` and spawn a second verifier.

12. In the same TUI session, drive a QA scenario via `pm qa run` / the TUI QA pane against a scenario that the scenario agent is likely to PASS without actually executing steps (e.g. a scenario that requires running commands but where the agent will just read code). The goal is to coax a PASS that the verifier will FLAG (per `qa_loop.py:2248` — SKIPPED/SUBSTITUTED triggers FLAGGED).

13. Wait until: (a) the scenario pane emits its first PASS verdict, (b) the verifier pane runs and emits a FLAGGED_START…FLAGGED_END block, (c) qa_loop sends the auto-follow-up message into the scenario pane (look for the log line "Sent follow-up message to scenario N pane" in pm logs, or scrape the scenario pane for the "Your verdict was reviewed and flagged" string from `qa_loop.py:1965`).

14. Immediately capture the verifier pane and the pm-run logs covering the next ~30s. Expected behavior:
- The verifier worker pane is **idle / not re-launched** until the scenario agent emits a *new* assistant turn after the follow-up;
- `_last_scenario_hook_ts[scenario_idx]` was set to a timestamp at follow-up time (the bug being that the previous code popped it, causing the stale `idle_prompt` to slip through);
- No second `verify_scenario` invocation appears in logs while the scenario pane is still keying the follow-up.

15. Pre-fix regression check (informational, optional): `git stash` the e8fe399 change locally (or grep that line 1996 reads `time.time()`, not `pop`) — confirm the guard is the current behavior.

16. Let the scenario produce its actual second verdict. Confirm exactly one new verifier run kicks off per genuinely new verdict (count "starting verifier" log lines vs. number of distinct scenario-pane verdicts).

## Capture transcripts

17. Save tmux transcripts of both legs under `pm/qa/captures/<scenario-36-id>/impl/`:
- Review-loop leg: review pane scrollback covering iterations 1 (INPUT_REQUIRED) and 2 (PASS), plus `pm/qa/captures/$PR_ID/impl/` listing.
- Verifier leg: scenario pane + verifier pane scrollbacks plus the pm-run log slice showing one verifier launch per real verdict.
```
tmux capture-pane -p -t <session>:<window>.<pane> -S - > review-loop.txt
tmux capture-pane -p -t <session>:<window>.<pane> -S - > scenario-pane.txt
tmux capture-pane -p -t <session>:<window>.<pane> -S - > verifier-pane.txt
```

18. Final verdict: PASS only if (a) checkpoint 3 produced INPUT_REQUIRED → PASS within bounded iterations citing the missing-then-present captures, and (b) checkpoint 5 shows no second verifier launch on the stale `idle_prompt` after the auto-follow-up. Otherwise NEEDS_WORK with the captured transcripts attached.

## Artifact Capture Recipe

Available at:
- `/scratch/qa-artifacts/tmux-screen-recording.md`

Read the recipe(s) and follow their capture commands to produce
evidence of this scenario's behavior. Save resulting captures under
`pm/qa/captures/pr-6be8ee6/scenarios/36/` (each recipe's
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
`pm/qa/captures/pr-6be8ee6/scenarios/36/pre-fix/` and the
post-fix recording under `.../post-fix/`. Cross-link the two in each
manifest's `## Files` section, and (per Incidental Bugs below) still
file a PR for the bug.

After producing each capture, commit it and push so it lands on the
PR branch:
- `git add pm/qa/captures/pr-6be8ee6/scenarios/36/`
- `git commit -m "qa: capture for scenario 36"`
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