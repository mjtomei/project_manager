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

1. **Manual repro on pre-fix code** — Reproduce by hand against
   pre-fix code (stash in-progress changes first). A repro is a
   concrete sequence of steps. If reproduction doesn't work, check in
   with the user before continuing.
   - `pm/qa/instructions/` may have env-setup recipes worth checking.
   - Use a recipe from `pm/qa/artifacts/` to capture; save under
     `pm/qa/captures/{seg}/impl/pre-fix/` (sub-subdirs for multiple
     captures).

2. **Write a failing test** — Codify the repro as a test that fails
   on pre-fix code for the same reason. For bugs that aren't testable
   in code, note that in a PR note instead.

3. **Fix** — Change that addresses the root cause.

4. **Verify with the test** — Confirm it passes; run related suites
   for regressions.

5. **Verify manually** — Re-run the step-1 repro against post-fix
   code and confirm the symptom is gone. Capture under
   `pm/qa/captures/{seg}/impl/post-fix/`.
"""


def _bug_fix_review_block(pr: dict) -> str:
    """Bug-fix review checklist, with the captures dir interpolated to
    the PR's local id."""
    seg = pr["id"]
    return f"""

## Bug Fix Review Checklist

- Pre-fix and post-fix captures exist under `pm/qa/captures/{seg}/impl/`.
  No pre-fix capture = **NEEDS_WORK**.
- A failing-then-passing test accompanies the fix, unless skipped via
  a PR note.
- The test fails for the right reason — would have caught the original
  bug, not any change in the area.
- Scope is the bug; flag drive-by refactors.
"""
