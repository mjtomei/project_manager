You are running QA scenario 1: "Smoke"

## Context

- **PR**: pr-9941232 — "fix-defect"
- **Branch**: pm/pr-9941232-fix-defect
- **Base branch**: master
- **Your workdir** (isolated clone): /home/pm/.pm/workdirs/qa/pr-9941232-cli-pr-9941232/s-1/repo
- **Scratch dir** (throwaway test projects): /home/pm/.pm/workdirs/qa/pr-9941232-cli-pr-9941232/s-1/scratch
- **PR workdir** (canonical source): /home/pm/.pm/workdirs/pm-test-1778679491-bca6d7c8/pm-pr-9941232-fix-defect-da44b97a

## Bug Fix Note

This PR is a bug fix. Your scenario may be exercising the original bug's
reproduction path — focus on whether the reported symptom still occurs
against the fixed code, not just whether code paths execute. If the diff
contains a reproduction test, running that test is a fast way to confirm
the fix.

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

**Focus**: Trivial smoke test — verify python3 buggy.py prints OK

**Steps**:
1. cd into the PR workdir: `cd /home/pm/.pm/workdirs/qa/pr-9941232-cli-pr-9941232/s-1/repo`.
2. Run `python3 buggy.py` and capture stdout and exit code (e.g., `python3 buggy.py; echo "exit=$?"`).
3. Confirm stdout contains `OK` and the exit code is `0`.

Verdict: PASS if step 3 holds; otherwise FAIL.

## Execution

1. Execute the test steps described above
2. If you find issues and can fix them:
   - Implement the fix in your workdir (your current directory)
   - Commit with message prefix `qa: `
   - Push: `git push origin pm/pr-9941232-fix-defect`
   - If push fails (another scenario pushed first), pull and retry:
     `git pull --rebase origin pm/pr-9941232-fix-defect && git push origin pm/pr-9941232-fix-defect`
3. End with a verdict on its own line — one of:
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