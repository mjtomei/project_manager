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

1. **Manual repro on pre-fix code** — Reproduce the bug by hand against
   the pre-fix code (stash in-progress changes first). This confirms
   the bug exists and that you understand its surface; a failing test
   alone can mislead, since it's easy to write a test that fails for
   a different reason than the reported symptom. A repro is a sequence
   of steps that produces the symptom — not a theory about what's wrong.
   - Look in `pm/qa/instructions/` for env-setup recipes that may help
     bring up a reproduction environment.
   - Follow a recipe from `pm/qa/artifacts/` to capture replayable
     artifacts. Save under `pm/qa/captures/{seg}/impl/pre-fix/` — single
     capture's files can go directly there, or use sub-subdirs
     (`pre-fix/<short-name>/`) when you need more than one capture for
     this phase. Each capture must contain its recording plus a
     `manifest.md` with copy-pasteable commands, the workdir and commit
     they ran in, and one paragraph on what the recording demonstrates.
   - If you can't reproduce, stop and ask the user — don't write a fix
     on top of an unreproduced bug.

2. **Write a failing test** — Codify the manual repro as a test that
   fails on pre-fix code for the same reason as the manual repro. If
   the bug is genuinely untestable in code (e.g. a visual rendering
   regression), skip this step and note it in a PR note — the
   step-1 capture is your reproduction artifact.

3. **Fix** — Change that addresses the root cause.

4. **Verify with the test** — Confirm the failing test now passes.
   Run any related suite to check for regressions.

5. **Verify manually** — Re-run the step-1 repro against the post-fix
   code and confirm the symptom is gone. Capture under
   `pm/qa/captures/{seg}/impl/post-fix/` (sub-subdirs allowed if you
   need more than one capture, mirroring the pre-fix layout). A passing
   test is not sufficient on its own.
"""


def _bug_fix_review_block(pr: dict) -> str:
    """Bug-fix review checklist, with the captures dir interpolated to
    the PR's local id."""
    seg = pr["id"]
    return f"""

## Bug Fix Review Checklist

- Pre-fix and post-fix manual-repro captures exist under
  `pm/qa/captures/{seg}/impl/` (or a PR-note explanation if the bug
  is genuinely uncapturable). No pre-fix capture = **NEEDS_WORK**.
- A failing-then-passing test accompanies the fix unless the bug is
  genuinely untestable in code (and that's noted in a PR note).
- The test fails for the right reason — it would have caught the
  original bug, not just any change in the area.
- Scope is the bug; flag drive-by refactors.
"""
