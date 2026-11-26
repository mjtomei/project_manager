You're working on PR pr-fixture: "Fixture bug: example handoff"

This session is managed by `pm`. Run `pm help` to see available commands.

## Context
Part of plan "Bugs" (bugs).


## Task
Fixture description used only to render the prompt. No real work is described here.

## How This Session Works

This session has two phases:

1. **Spec generation** — First, you will analyze the PR description and the
   codebase to produce a structured spec.  The spec grounds the requirements
   in actual code paths and surfaces implicit requirements.
2. **Implementation** — Then, working from the spec you generated, you will
   carry out the implementation work described in the Task section above.

Start with Step 0 below.  Once the spec is saved, proceed to the main task.

## Step 0: Generate Implementation Spec

Analyze the codebase to understand the relevant code, then write a spec covering:
1. **Requirements** — Restate each requirement grounded in the codebase (specific files, functions, modules)
2. **Implicit Requirements** — What must also be true for stated requirements to hold
3. **Ambiguities** — Identified ambiguities with your proposed resolutions
4. **Edge Cases** — Interactions with existing behavior not addressed in the description

Use your best judgement to resolve ambiguities where you can confidently do so.
If you encounter a genuinely unresolvable ambiguity — multiple valid
interpretations with materially different outcomes — include it in the spec's
"Ambiguities" section marked **[UNRESOLVED]** with a clear question.

Save the spec to `pm/specs/pr-fixture/impl.md`.

If the spec contains any **[UNRESOLVED]** ambiguities, present them to the
user and wait for their response before proceeding.  Update the spec with
their answers, re-save, then continue.  If there are no unresolved
ambiguities, proceed with the implementation work below.

---

## Bug Fix Flow

The captures directory for this PR is at `$(pm qa captures-path pr-fixture)`
on the host (`~/.pm/sessions/<session-tag>/captures/pr-fixture/`). It is
**not** part of the project repo — captures live there and never get
committed. Set `CAP=$(pm qa captures-path pr-fixture)` once and reference
`$CAP` below.

If artifacts from a prior session already satisfy a step (existing
pre-fix capture, failing test, fix, post-fix capture), reuse them and
skip that step. Re-do work only when this session's changes make the
prior artifact stale.

1. **Manual repro on pre-fix code** — If `$CAP/impl/pre-fix/` already
   has a valid capture, reuse it and skip this step. Otherwise,
   reproduce the bug by hand against pre-fix code (stash uncommitted
   changes, or if the fix is already committed, check out the parent
   commit or revert fix files temporarily, capture, then restore). A
   repro is a concrete sequence of steps. If reproduction doesn't
   work, check in with the user before continuing.
   - `pm/qa/instructions/` may have env-setup recipes worth checking.
   - Use a recipe from `pm/qa/artifacts/` to capture; save under
     `$CAP/impl/pre-fix/`. If the phase needs more than one capture,
     give each a named subdirectory there.

2. **Write a failing test** — Codify the repro as a test that fails
   on pre-fix code for the same reason. For bugs that aren't testable
   in code, note that in a PR note instead.

3. **Fix** — Change that addresses the root cause. If a working fix
   already exists and this session has no reason to change it (e.g.
   no new PR notes asking for changes), skip.

4. **Verify with the test** — Confirm it passes; run related suites
   for regressions.

5. **Verify manually** — Re-run the step-1 repro against post-fix
   code and confirm the symptom is gone. Capture the post-fix behavior
   under `$CAP/impl/post-fix/` if no valid capture is there yet, or if
   this session changed the fix. If a valid post-fix capture is
   already there and the fix is unchanged, reuse it.

## PR Notes — Handoff Channel

`pm pr note add <pr-id> '<text>'` is the canonical way to hand off context
between sessions. A note persists on the target PR (in project.yaml) and is
injected into the prompt of every future session for that PR (the `## PR
Notes` section). Prefer pm PR notes over GitHub PR comments or description
edits for any handoff — GitHub comments are for external review
communication, not internal handoff. When the user says "leave a note" /
"add a note" / "notes" without qualification, they mean a pm PR note.

- **Same-PR, next session** — to leave context for whoever resumes this PR,
  run `pm pr note add pr-fixture '<text>'`.
- **Cross-PR** — when leaving work or context for a *different* PR to pick
  up, add the note to that PR's id: `pm pr note add <other-pr-id> '<text>'`.
  It attaches to that PR and surfaces in its sessions. If incidental work
  belongs to a PR that already exists, prefer a note on that PR over opening
  a brand-new one (see the Incidental Bugs guidance for recording incidental
  fixes).

It is fine to run this from your own workdir, including a note targeting
another PR. The note is written to the git-tracked `project.yaml`; it
travels to master when your PR merges, and the target PR's sessions pick it
up the next time they clone or pull master. So a cross-PR note may surface
after your PR merges rather than instantly — that delay is expected, not a
reason to use a GitHub comment instead.

## Tips
- This session may be resuming after a restart. Check `git status` and `git log` to see if previous work exists on this branch — if so, continue from there. The directory may contain uncommitted implementation work from a previous session.
- Before referencing existing code (imports, function calls, class usage), read the source to verify the interface.
- This workdir is a clone managed by pm. The base pm state (project.yaml, PR status) lives in a separate directory and is not automatically synced with this clone. PR-state commands like `pm pr start` run from the base pm directory, not here — your session for pr-fixture is already running, and PM handles the transition to review.
- Pull `pm/pr-fixture-bug-fixture-example-handoff` from the remote before starting work so you pick up changes from other sessions or machines. Resolve any merge conflicts before continuing.
- Pull the latest `master` and merge it into your branch so you're building on up-to-date code. Resolve any conflicts before continuing.

## Workflow
- You're on branch `pm/pr-fixture-bug-fixture-example-handoff`
- Commit and push as you go: `git push origin pm/pr-fixture-bug-fixture-example-handoff`
- When implementation is complete, report completion and wait. PM handles the transition to review.
- Merging happens after sign-off (`pm pr merge pr-fixture` from the base pm directory publishes only a signed-off candidate); never push or merge into `master` yourself

## Interacting with the TUI

The base pm tmux session is `pm-project_manager-00000000`. Use `-s pm-project_manager-00000000` with pm tui commands so they target the correct session even from workdir clones:
- `pm tui view -s pm-project_manager-00000000` — capture and view the current TUI screen
- `pm tui send <keys> -s pm-project_manager-00000000` — send keystrokes to the TUI (e.g. `pm tui send j` to move down)

**Do not** run commands that spawn new Claude sessions yourself (e.g. `pm pr start`, `pm pr done`, `pm plan add`, `pm plan breakdown`, `pm plan review`). These must be triggered through the TUI so panes are managed correctly. Use `pm tui send` to press the appropriate key in the TUI instead.

**Do not start the review yourself.** Don't press `d`, don't use `pm tui send`
to start a review, and don't run `pm pr review`. When implementation is
complete, report completion and wait. PM handles the transition to review.
