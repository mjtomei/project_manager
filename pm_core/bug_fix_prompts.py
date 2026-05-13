"""Bug-fix flow prompt blocks.

Detection (`_is_bug_pr`) plus the two prompt blocks that get appended
to impl prompts (`_bug_fix_flow_block`) and review prompts
(`_bug_fix_review_block`) when a PR is a bug fix.

Lives outside `prompt_gen.py` to keep that file from accumulating one
more prompt-block per category. Imported and used by `prompt_gen` and
re-exported from there for backward compatibility.
"""


def _is_bug_pr(pr: dict) -> bool:
    """Return True when this PR should follow the bug-fix flow.

    Triggers on `plan == "bugs"` (today's signal) or `type == "bug"`
    (forward-looking schema). Keeps detection in one place so impl/review/QA
    prompts stay in sync.
    """
    return pr.get("plan") == "bugs" or pr.get("type") == "bug"


def _bug_fix_flow_block(pr: dict) -> str:
    """Bug-fix flow prompt block, with the captures dir interpolated to
    the PR's local id."""
    seg = pr["id"]
    return f"""
## Bug Fix Flow

The captures directory for this PR is at `$(pm qa captures-path {seg})`
on the host (`~/.pm/sessions/<session-tag>/captures/{seg}/`). It is
**not** part of the project repo — captures live there and never get
committed. Use `$CAP=$(pm qa captures-path {seg})` to refer to it
below.

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
"""


def _bug_fix_review_block(pr: dict) -> str:
    """Bug-fix review checklist, with the captures dir resolved via
    `pm qa captures-path <pr-id>`."""
    seg = pr["id"]
    return f"""

## Bug Fix Review Checklist

- Pre-fix and post-fix captures under
  `$(pm qa captures-path {seg})/impl/` are the primary evidence the
  fix addresses the reported bug. If they're missing or unconvincing,
  surface it as **INPUT_REQUIRED** — the user decides whether to
  require capture or accept the fix without one.
- A failing-then-passing test accompanies the fix, unless skipped via
  a PR note.
- The test fails for the right reason — would have caught the original
  bug, not any change in the area.
- Scope is the bug; flag drive-by refactors.
"""
