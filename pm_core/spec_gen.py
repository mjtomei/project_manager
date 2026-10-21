"""Spec generation for PR phases.

Generates phase-specific specs (impl, qa) that bridge the gap between
the user's natural-language PR description and each downstream agent.
Each spec restates requirements in terms grounded in the actual codebase,
surfaces implicit requirements, and resolves ambiguities.

Spec generation modes (global setting ``spec-mode``):
  auto   — Generate spec, use best judgement for ambiguities,
           proceed immediately.  Resolved ambiguities are documented in
           the spec for later review.
  review — Generate spec, pause for user approval before proceeding.
  prompt — (default) Generate spec and proceed unless the PR has
           ``review_spec: true`` or Claude flags an unresolvable ambiguity.

Specs are stored as markdown files under ``<pm-root>/specs/<pr-id>/``.
The file path is recorded in project.yaml so specs survive across sessions
and the naming scheme can evolve without breaking existing references.
"""

from datetime import datetime, timezone
from pathlib import Path

import click

from pm_core import store
from pm_core.autostart_state import pending_spec_phase
from pm_core.claude_launcher import launch_claude_print
from pm_core.paths import configure_logger, get_global_setting_value

_log = configure_logger("pm.spec_gen")

# Phase names that have specs
PHASES = ("impl", "qa")



def get_spec_mode() -> str:
    """Return the global spec generation mode: auto, review, or prompt.

    Defaults to ``prompt`` — generates spec and proceeds unless the PR
    has ``review_spec: true`` or Claude flags an unresolvable ambiguity.
    """
    val = get_global_setting_value("spec-mode", "prompt").lower()
    if val in ("auto", "review", "prompt"):
        return val
    return "prompt"


def pr_spec_mode(pr: dict, review: bool = False) -> str:
    """Return the effective spec mode for a specific PR.

    Per-PR ``review_spec: true`` overrides to ``review`` mode, as does
    *review* — the auto-start spec-review gate (``pm autostart add
    --review-specs``), which applies review mode without touching either
    the global setting or the PR's own ``review_spec``.
    """
    mode = get_spec_mode()
    if review or pr.get("review_spec"):
        return "review"
    return mode


def spec_dir(root: Path, pr_id: str) -> Path:
    """Return the spec directory for a PR: ``<pm-root>/specs/<pr-id>/``."""
    d = root / "specs" / pr_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def spec_file_path(root: Path, pr_id: str, phase: str) -> Path:
    """Return the canonical spec file path for a PR phase."""
    return spec_dir(root, pr_id) / f"{phase}.md"


def _workdir_spec_path(pr: dict, phase: str) -> Path | None:
    workdir = pr.get("workdir")
    if not workdir:
        return None
    return Path(workdir) / "pm" / "specs" / pr.get("id", "") / f"{phase}.md"


def spec_location(pr: dict, phase: str) -> Path | None:
    """The file :func:`get_spec` reads for *phase*, or None if none exists.

    Lookup order:
    1. The PR's workdir pm/specs/ — the impl session writes specs here and
       it has the most up-to-date copy while the PR is being worked on.
    2. The local pm/specs/ (cwd-resolved root) — where specs live after
       the PR branch is merged back to the base repo.
    """
    if phase not in PHASES:
        return None

    # 1. Workdir — most up-to-date copy while the PR is in flight.
    p = _workdir_spec_path(pr, phase)
    if p is not None and p.exists():
        return p

    # 2. Local pm directory — spec lives here after the branch is merged.
    try:
        root = store.find_project_root()
    except FileNotFoundError:
        return None
    # Not spec_file_path(): a lookup must not create the spec directory.
    canonical = root / "specs" / pr.get("id", "") / f"{phase}.md"
    if canonical.exists():
        return canonical
    return None


def get_spec(pr: dict, phase: str) -> str | None:
    """Get the spec content for a phase, reading from the spec file.

    Returns None if no spec exists or the file is empty.  The file is the
    one :func:`spec_location` finds (workdir copy first, then local pm/).
    """
    p = spec_location(pr, phase)
    if p is None:
        return None
    content = p.read_text().strip()
    return content if content else None


def set_spec(pr: dict, phase: str, spec: str,
             root: Path | None = None) -> Path | None:
    """Write spec content to file and store the path in the PR entry.

    *root* is the pm project directory containing project.yaml.
    If not provided, tries to find it via ``store.find_project_root()``.

    Returns the path written, or None for invalid phases.
    """
    if phase not in PHASES:
        return None

    if root is None:
        try:
            root = store.find_project_root()
        except FileNotFoundError:
            _log.warning("spec_gen: cannot find project root for set_spec")
            return None

    # Write where get_spec reads: an inline session's spec lives in the
    # PR workdir, and an approve-with-edits / reject regeneration written
    # only under <root> would be shadowed by that stale workdir copy.
    path = _workdir_spec_path(pr, phase)
    if path is None or not path.exists():
        path = spec_file_path(root, pr.get("id", "unknown"), phase)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(spec)
    _log.info("spec_gen: wrote %s spec to %s (%d chars)", phase, path, len(spec))
    return path


def _build_spec_prompt(data: dict, pr: dict, phase: str,
                       review: bool = False) -> str:
    """Build the Claude prompt for generating a phase spec."""
    title = pr.get("title", "")
    description = pr.get("description", "").strip()
    base_branch = data.get("project", {}).get("base_branch", "master")
    workdir = pr.get("workdir", "")

    # Gather prior specs for context
    prior_specs = ""
    if phase == "qa":
        impl_spec = get_spec(pr, "impl")
        if impl_spec:
            prior_specs += f"""
## Implementation Spec (spec_impl)

{impl_spec}
"""

    # Phase-specific instructions
    phase_instructions = {
        "impl": """Generate an **implementation spec** (spec_impl).

State what needs to be implemented in terms of specific code changes:
- Which files, functions, classes, and modules to modify or create
- What invariants must be maintained
- What existing behavior must not break
- Implicit requirements that the description assumes but doesn't state
- Edge cases and interactions with existing code""",

        "qa": """Generate a **QA spec** (spec_qa).

Describe what to test in terms of **user-facing behaviors** — what a
user does and what they observe. Each requirement should read like a
user story with a Given / When / Then acceptance criterion:

  **Given** <starting state the user is in>
  **When** <single concrete action the user takes>
  **Then** <observable outcome from the user's surface>

That structure forces three things the spec must answer: who is the
user, what action triggers the behavior, and what should they see as
a result. One requirement may bundle several Given/When/Then triples
when the stories share a focus — downstream scenarios can batch
related triples together for efficiency. Each triple still keeps its
own Given, When, and Then.

- All user flows the PR's changes affect, each captured as one or
  more Given/When/Then behaviors. Frame the Then in user-observable
  terms — what appears on screen, what gets printed, what file is
  created — rather than function-level claims.
- Setup the user needs to reach each behavior — described as user
  steps, not as fixtures. This belongs in each behavior's Given,
  and downstream scenarios will lean on QA *instructions* (under
  `pm/qa/instructions/`) to perform that setup; if the spec implies
  a Given that no existing instruction covers, note it so a new
  instruction can be authored.
- Edge cases and failure modes from the user's perspective: what
  inputs / states cause surprising or wrong behavior. Each becomes
  its own Given/When/Then.
- Surface coverage: which user-facing surfaces exist as alternatives
  to exercise the same behavior, and how expectations differ across
  them. All supported surfaces should be exercised.
- Pass/Fail criteria from the user's point of view — the Then clauses
  effectively answer this; restate any cross-cutting ones explicitly.

Downstream scenarios will use *artifact recipes* (under
`pm/qa/artifacts/`) to drive each When and capture each Then's
evidence. If a behavior implies a surface no existing recipe covers,
note it so a new recipe can be authored.

If a behavior is only checkable at the function level with no
user-observable surface, leave it to the unit test suite and don't
include it in the QA spec.""",
    }

    diff_instruction = ""
    if phase == "qa" and workdir:
        diff_instruction = f"""
Run `git diff {base_branch}...HEAD` in the workdir to see what changed.
Read source files as needed to understand the implementation.
"""

    mode = pr_spec_mode(pr, review)
    ambiguity_instruction = ""
    if mode == "prompt":
        ambiguity_instruction = """
## Ambiguity Handling

If you encounter ambiguities that you can confidently resolve using your
understanding of the codebase and common patterns, resolve them and note
your resolution.  If you encounter an ambiguity that genuinely requires
human input (multiple valid interpretations with materially different
outcomes), mark it with AMBIGUITY_FLAG on its own line followed by the
question.  This will pause execution for user review.
"""
    elif mode == "review":
        ambiguity_instruction = """
## Ambiguity Handling

This spec will be reviewed by the user before the phase proceeds.
Identify all ambiguities and present your proposed resolution for each.
The user will confirm, correct, or expand on your proposals.
"""

    prompt = f"""You are generating a spec for PR: "{title}"

## PR Description

{description}
{prior_specs}
## Instructions

{phase_instructions[phase]}
{diff_instruction}{ambiguity_instruction}
## Output Format

Write a clear, structured spec.  Use markdown.  Be specific — for an
implementation spec that means concrete code paths, function names,
and file locations; for a QA spec that means concrete user actions
(exact commands, key sequences, observable outputs) rather than
internal function references.
Do NOT include preamble or meta-commentary — output only the spec content.

The spec should contain:
1. **Requirements** — Restatement of each requirement grounded in the codebase
2. **Implicit Requirements** — What must also be true for stated requirements to hold
3. **Ambiguities** — Identified ambiguities with proposed resolutions
4. **Edge Cases** — Interactions with existing behavior not addressed in the description
"""
    return prompt.strip()


def generate_spec(data: dict, pr_id: str, phase: str,
                  root: Path | None = None,
                  force: bool = False,
                  review: bool = False) -> tuple[str, bool]:
    """Generate a spec for a PR phase.

    Args:
        data: Project data dict.
        pr_id: PR identifier.
        phase: One of "impl", "qa".
        root: Project root (for saving).
        force: If True, regenerate even if spec already exists.
        review: Force review mode (auto-start spec-review gate): the
            result is always left pending for approval.

    Returns:
        (spec_text, needs_review) — the generated spec and whether
        it requires user review before proceeding.
    """
    pr = store.get_pr(data, pr_id)
    if not pr:
        raise ValueError(f"PR {pr_id} not found")

    if phase not in PHASES:
        raise ValueError(f"Invalid phase: {phase}. Must be one of {PHASES}")

    # Check if spec already exists
    existing = get_spec(pr, phase)
    if existing and not force:
        _log.info("spec_gen: using existing %s spec for %s", phase, pr_id)
        return existing, False

    mode = pr_spec_mode(pr, review)
    _log.info("spec_gen: generating %s spec for %s (mode=%s)", phase, pr_id, mode)

    prompt = _build_spec_prompt(data, pr, phase, review=review)
    workdir = pr.get("workdir")

    click.echo(f"Generating {phase} spec for {pr_id}...")
    spec_text = launch_claude_print(prompt, cwd=workdir,
                                    message=f"Generating {phase} spec")

    spec_text = spec_text.strip()
    if not spec_text:
        _log.warning("spec_gen: empty spec generated for %s/%s", pr_id, phase)
        return "", False

    # Determine if review is needed
    needs_review = False
    if mode == "review":
        needs_review = True
    elif mode == "prompt":
        if "AMBIGUITY_FLAG" in spec_text:
            needs_review = True
            _log.info("spec_gen: ambiguity detected in %s spec for %s, "
                      "pausing for review", phase, pr_id)

    # Write spec file (safe outside lock — file writes are independent of YAML)
    set_spec(pr, phase, spec_text, root=root)

    # Build pending value for both in-memory and on-disk use
    pending_value = None
    if needs_review:
        pending_value = {
            "phase": phase,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        if review:
            pending_value["review"] = True

    # Apply all state mutations atomically via locked_update
    if root:
        def apply(fresh_data):
            fresh_pr = store.get_pr(fresh_data, pr_id)
            if not fresh_pr:
                return
            # Set or clear spec_pending
            if pending_value:
                fresh_pr["spec_pending"] = pending_value
            else:
                fresh_pr.pop("spec_pending", None)
            # New content: an approval of the previous spec no longer
            # applies (the auto-start review gate asks again).
            _clear_approval(fresh_pr, phase)

        store.locked_update(root, apply)
        _log.info("spec_gen: saved %s spec for %s (%d chars, needs_review=%s)",
                  phase, pr_id, len(spec_text), needs_review)

    # Keep caller's in-memory pr in sync
    if pending_value:
        pr["spec_pending"] = pending_value
    else:
        pr.pop("spec_pending", None)
    _clear_approval(pr, phase)

    return spec_text, needs_review


def _record_approval(pr: dict, phase: str, approved_at: str) -> None:
    rec = pr.get("spec_approved")
    if not isinstance(rec, dict):
        rec = {}
    rec[phase] = approved_at
    pr["spec_approved"] = rec


def _clear_approval(pr: dict, phase: str) -> None:
    rec = pr.get("spec_approved")
    if isinstance(rec, dict) and phase in rec:
        del rec[phase]
        if not rec:
            del pr["spec_approved"]


def is_spec_approved(pr: dict, phase: str) -> bool:
    """Whether *phase*'s spec was approved through ``approve_spec``."""
    rec = pr.get("spec_approved")
    return isinstance(rec, dict) and bool(rec.get(phase))


def needs_spec_approval(pr: dict, phase: str) -> bool:
    """A spec for *phase* exists, was never approved and nothing is pending.

    Specs from before approvals were recorded count as unapproved (the
    "already-present spec" case of the auto-start review gate).
    """
    if has_pending_spec(pr) or is_spec_approved(pr, phase):
        return False
    return get_spec(pr, phase) is not None


def mark_spec_pending(root: Path, pr_id: str, phase: str,
                      source: str = "autostart",
                      pr: dict | None = None) -> bool:
    """Hold *phase*'s existing spec for review (sets ``spec_pending``).

    Used by the auto-start spec-review gate to connect an inline-generated
    (or already present) spec to the normal approval flow
    (``pm pr spec-approve`` / ``V``).  Never replaces a pending spec.
    Returns True when it set one.  *pr* (the caller's in-memory entry) is
    updated too.
    """
    value = {
        "phase": phase,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "review": True,
        "source": source,
    }
    marked = False

    def apply(fresh_data):
        nonlocal marked
        fresh_pr = store.get_pr(fresh_data, pr_id)
        if not fresh_pr or fresh_pr.get("spec_pending"):
            return
        fresh_pr["spec_pending"] = dict(value)
        marked = True

    store.locked_update(root, apply)
    if marked:
        if pr is not None:
            pr["spec_pending"] = dict(value)
        _log.info("spec_gen: %s spec for %s held for review (%s)",
                  phase, pr_id, source)
    return marked


PHASE_LABELS = {"impl": "implementation", "qa": "QA"}


def approval_message(pr: dict, phase: str, edited: bool = False) -> str:
    """The message sent to the waiting agent once its spec is approved."""
    pr_id = pr.get("id", "???")
    label = PHASE_LABELS.get(phase, phase)
    path = f"pm/specs/{pr_id}/{phase}.md"
    how = "approved with edits" if edited else "approved"
    msg = (f"The {label} spec ({path}) was {how} via pm. Re-read it and "
           f"proceed with the {label} work based on the approved spec.")
    if phase == "qa":
        msg += (" Emit (or re-emit) the complete QA plan "
                "(QA_PLAN_START ... QA_PLAN_END) reflecting the approved spec.")
    return msg


def notify_spec_approved(pr: dict, phase: str, edited: bool = False,
                         session: str | None = None) -> bool:
    """Tell the agent waiting on *phase*'s spec that it was approved.

    The implementation agent lives in the PR window (display id), the QA
    planner in the first pane of ``qa-<display id>``.  No-op (False) when
    there is no pm session or the window is gone.
    """
    from pm_core import tmux as tmux_mod
    from pm_core.cli.helpers import _pr_display_id
    from pm_core.loop_shared import find_claude_pane, get_pm_session
    from pm_core.qa_loop import _compute_qa_window_name

    session = session or get_pm_session()
    if not session:
        return False
    window = (_pr_display_id(pr) if phase == "impl"
              else _compute_qa_window_name(pr))
    try:
        pane = find_claude_pane(session, window)
        if not pane:
            return False
        tmux_mod.send_keys(pane, approval_message(pr, phase, edited))
        # Claude's prompt may take the first Enter as a newline in a
        # pasted block; a second one submits (qa_loop follow-up pattern).
        tmux_mod.send_keys(pane, "")
    except Exception:
        _log.warning("spec_gen: could not notify %s pane for %s",
                     window, pr.get("id"), exc_info=True)
        return False
    _log.info("spec_gen: notified %s (%s) of %s spec approval",
              window, pr.get("id"), phase)
    return True


def has_pending_spec(pr: dict) -> bool:
    """Check if a PR has a spec waiting for user review."""
    return bool(pr.get("spec_pending"))


def get_pending_spec_phase(pr: dict) -> str | None:
    """Return the phase name of the pending spec, or None."""
    # One implementation, kept in the import-light autostart_state so the
    # tree and picker can use it without pulling in spec_gen.
    return pending_spec_phase(pr)


def approve_spec(data: dict, pr_id: str, root: Path | None = None,
                 edited_text: str | None = None) -> str | None:
    """Approve a pending spec, optionally with edits.

    Clears ``spec_pending`` and saves.  If *edited_text* is provided,
    updates the spec content.

    Returns the phase that was approved, or None if no pending spec.
    """
    pr = store.get_pr(data, pr_id)
    if not pr:
        return None

    pending = pr.get("spec_pending")
    if not pending or not isinstance(pending, dict):
        return None

    phase = pending.get("phase")
    if not phase:
        return None

    # Write edited spec file (safe outside lock)
    if edited_text is not None:
        set_spec(pr, phase, edited_text.strip(), root=root)

    # Also update in-memory data for caller
    del pr["spec_pending"]
    approved_at = datetime.now(timezone.utc).isoformat()
    _record_approval(pr, phase, approved_at)

    if root:
        def apply(fresh_data):
            fresh_pr = store.get_pr(fresh_data, pr_id)
            if not fresh_pr:
                return
            fresh_pr.pop("spec_pending", None)
            _record_approval(fresh_pr, phase, approved_at)

        store.locked_update(root, apply)

    _log.info("spec_gen: approved %s spec for %s", phase, pr_id)
    return phase


def reject_spec(data: dict, pr_id: str, feedback: str | None = None,
                root: Path | None = None) -> str | None:
    """Reject a pending spec and regenerate it, optionally incorporating feedback.

    After regeneration, ``spec_pending`` may or may not remain set:
    in ``review`` mode it is always re-set; in ``prompt`` mode it is
    cleared if the regenerated spec has no ambiguity flags (allowing the
    phase to proceed automatically).

    If *feedback* is provided, it is appended to the PR description for
    context during regeneration, then removed afterward.

    Returns the phase that was rejected, or None if no pending spec.
    """
    pr = store.get_pr(data, pr_id)
    if not pr:
        return None

    pending = pr.get("spec_pending")
    if not pending or not isinstance(pending, dict):
        return None

    phase = pending.get("phase")
    if not phase:
        return None

    _log.info("spec_gen: rejecting %s spec for %s (feedback=%r)", phase, pr_id, feedback)

    # Temporarily append feedback to description for regeneration context
    original_desc = pr.get("description", "")
    if feedback:
        pr["description"] = (
            original_desc.rstrip() + f"\n\n[Spec review feedback]: {feedback}"
        )
        if root:
            def apply_feedback(fresh_data):
                fresh_pr = store.get_pr(fresh_data, pr_id)
                if fresh_pr:
                    fresh_pr["description"] = pr["description"]

            store.locked_update(root, apply_feedback)

    # A spec held by the review gate stays held: regenerate in review
    # mode so rejecting never lets the phase proceed unapproved.
    review = bool(pending.get("review"))
    try:
        generate_spec(data, pr_id, phase, root=root, force=True,
                      review=review)
    finally:
        # Restore original description
        if feedback:
            pr["description"] = original_desc
            if root:
                def restore_desc(fresh_data):
                    fresh_pr = store.get_pr(fresh_data, pr_id)
                    if fresh_pr:
                        fresh_pr["description"] = original_desc

                store.locked_update(root, restore_desc)

    _log.info("spec_gen: regenerated %s spec for %s after rejection", phase, pr_id)
    return phase


def oldest_pending_spec_pr(data: dict) -> str | None:
    """Return the PR ID with the oldest pending spec review, or None."""
    oldest_pr_id = None
    oldest_time = None
    for pr in data.get("prs") or []:
        pending = pr.get("spec_pending")
        if not pending or not isinstance(pending, dict):
            continue
        gen_at = pending.get("generated_at", "")
        if oldest_time is None or gen_at < oldest_time:
            oldest_time = gen_at
            oldest_pr_id = pr["id"]
    return oldest_pr_id


def spec_generation_preamble(pr: dict, phase: str,
                             root: Path | None = None,
                             review_gate: bool = False) -> str:
    """Build a prompt preamble for inline spec generation in the main session.

    Returns an empty string if a spec already exists for this phase.
    Otherwise returns a "Step 0" block that tells Claude to generate the
    spec, write it to a file, and register it — all within the same session.

    The guidance varies by mode:
      auto   — resolve ambiguities, save, proceed immediately.
      prompt — resolve ambiguities, save, proceed unless genuinely
               unresolvable (present flagged questions to user first).
      review — save, present spec summary to user, wait for approval.

    *review_gate* (auto-start spec review) forces review mode and says
    approval comes only through ``pm pr spec-approve`` / ``V``.

    *root* is the pm project directory (containing project.yaml).
    """
    # If spec already exists, nothing to generate
    if get_spec(pr, phase):
        return ""

    mode = pr_spec_mode(pr, review_gate)
    pr_id = pr.get("id", "???")
    label = PHASE_LABELS.get(phase, phase)

    # Derive the spec file path — use a relative path so the prompt works
    # inside containers where the workdir is mounted at /workspace rather
    # than the host's absolute path.
    if root is None:
        try:
            root = store.find_project_root()
        except FileNotFoundError:
            root = Path("pm")  # fallback
    file_path = spec_file_path(root, pr_id, phase)
    try:
        file_path = file_path.relative_to(root.parent)
    except ValueError:
        pass  # already relative or different mount — use as-is

    # Determine what kind of spec to generate
    spec_instructions = {
        "impl": """\
Analyze the codebase to understand the relevant code, then write a spec covering:
1. **Requirements** — Restate each requirement grounded in the codebase (specific files, functions, modules)
2. **Implicit Requirements** — What must also be true for stated requirements to hold
3. **Ambiguities** — Identified ambiguities with your proposed resolutions
4. **Edge Cases** — Interactions with existing behavior not addressed in the description""",

        "qa": """\
Review the implementation (run `git diff` and read source files), then write a spec covering:
1. **Requirements** — Each user-facing behavior framed as a Given /
   When / Then user story. Given = starting state, When = single user
   action, Then = observable outcome from the user's surface. Split
   multi-action behaviors into separate requirements.
2. **Setup** — Setup requirements for testing, described as user
   steps (this folds into each requirement's Given but cross-cutting
   setup goes here).
3. **Edge Cases** — Edge cases and failure modes framed the same way
   (Given / When / Then).
4. **Pass/Fail Criteria** — What constitutes a passing vs failing
   test; the Then clauses largely answer this.
5. **Ambiguities** — Any ambiguities you resolved and how""",
    }

    instructions = spec_instructions.get(phase, spec_instructions["impl"])

    # For the QA phase: after saving the spec, commit and push it so that
    # scenario clones (created after the planner runs) have access to it.
    # The QA planner is the first step that modifies the repo; before specs,
    # it was read-only, so scenario clones were fine without a push.
    branch = pr.get("branch", "")
    commit_step = ""
    if phase == "qa" and branch:
        commit_step = f"""
Then commit and push the spec so QA scenario clones can access it:
  `git add pm/specs/{pr_id}/qa.md && git commit -m "pm: qa spec for {pr_id}" && git push origin {branch}`
"""

    # Mode-specific guidance for ambiguity handling and what to do after saving
    if mode == "auto":
        post_save = f"""\
Use your best judgement to resolve any ambiguities based on your understanding
of the codebase and common patterns.  Document all resolved ambiguities and
your reasoning in the spec's "Ambiguities" section.

Save the spec to `{file_path}`.
{commit_step}
Then proceed with the {label} work below."""

    elif mode == "prompt":
        post_save = f"""\
Use your best judgement to resolve ambiguities where you can confidently do so.
If you encounter a genuinely unresolvable ambiguity — multiple valid
interpretations with materially different outcomes — include it in the spec's
"Ambiguities" section marked **[UNRESOLVED]** with a clear question.

Save the spec to `{file_path}`.
{commit_step}
If the spec contains any **[UNRESOLVED]** ambiguities, present them to the
user and wait for their response before proceeding.  Update the spec with
their answers, re-save, then continue.  If there are no unresolved
ambiguities, proceed with the {label} work below."""

    else:  # review
        post_save = f"""\
Identify all ambiguities and present your proposed resolution for each in the
spec's "Ambiguities" section.

Save the spec to `{file_path}`.
{commit_step}
Then present a brief summary of the spec to the user and ask whether they
approve or want changes.  If they request changes, update the spec file,
re-save, and ask again.  Once approved, proceed with the {label} work below."""
        if review_gate:
            post_save += f"""

Approval is recorded only through pm: the user approves with
`pm pr spec-approve {pr_id}` (or `V` in the TUI), which may also edit the
spec file.  You will receive a message saying the spec was approved — do not
start the {label} work before that message, even if approval is given in
this chat; wait for it."""

    return f"""
## How This Session Works

This session has two phases:

1. **Spec generation** — First, you will analyze the PR description and the
   codebase to produce a structured spec.  The spec grounds the requirements
   in actual code paths and surfaces implicit requirements.
2. **{label.title()}** — Then, working from the spec you generated, you will
   carry out the {label} work described in the Task section above.

Start with Step 0 below.  Once the spec is saved, proceed to the main task.

## Step 0: Generate {label.title()} Spec

{instructions}

{post_save}

---
"""


def get_spec_mocks_section(pr: dict) -> str:
    """Return the Mocks block for injection into QA scenario prompts.

    Reads shared mock definitions from pm/qa/mocks/ (the authoritative
    library).  If the library is empty, falls back to extracting a Mocks
    section from the QA spec (legacy behaviour for PRs that generated mocks
    inline before the library existed).

    Returns a formatted markdown block, or empty string if no mocks are found.
    """
    from pm_core import qa_instructions

    # Prefer the shared library in pm/qa/mocks/
    try:
        root = store.find_project_root()
        library_block = qa_instructions.mocks_for_prompt(root)
    except FileNotFoundError:
        library_block = ""

    if library_block:
        return library_block

    # Fallback: extract from the QA spec's embedded Mocks section
    spec = get_spec(pr, "qa")
    if not spec:
        return ""

    # Look for a ## Mocks heading (case-insensitive) and extract to next heading
    lines = spec.splitlines()
    in_mocks = False
    mocks_lines: list[str] = []
    for line in lines:
        if not in_mocks:
            if (line.strip().lower().startswith("## mocks")
                    or line.strip().lower().startswith("**mocks**")):
                in_mocks = True
                mocks_lines.append(line)
        else:
            # Stop at the next ## heading
            if line.startswith("## ") and mocks_lines:
                break
            mocks_lines.append(line)

    if not mocks_lines:
        return ""

    # Skip the heading line itself — we supply our own heading below
    body_lines = mocks_lines[1:] if mocks_lines else []
    content = "\n".join(body_lines).strip()
    if not content:
        return ""
    return f"""
## Mocks

The QA spec defines the mocking strategy for this PR's test scenarios.
Use the contracts and scripted responses below — do not devise your own.

{content}
"""


def format_spec_for_prompt(pr: dict, phase: str) -> str:
    """Format a spec for inclusion in a Claude prompt.

    Returns a markdown section with the spec, or empty string if no spec.
    """
    spec = get_spec(pr, phase)
    if not spec:
        return ""

    phase_labels = {
        "impl": "Implementation Spec",
        "qa": "QA Spec",
    }
    label = phase_labels.get(phase, f"{phase} Spec")

    mode = pr_spec_mode(pr)
    pr_id = pr.get("id", "???")
    try:
        root = store.find_project_root()
    except FileNotFoundError:
        root = Path("pm")
    file_path = spec_file_path(root, pr_id, phase)
    try:
        file_path = file_path.relative_to(root.parent)
    except ValueError:
        pass  # already relative or different mount — use as-is

    staleness_note = (
        "Also check whether the spec is still consistent with the current code "
        "and PR notes — the code or notes may have changed since the spec was "
        "generated. If you find requirements that no longer match the "
        "implementation, or PR notes that contradict or extend the spec, update "
        f"the spec in `{file_path}`."
    )

    if mode == "auto":
        review_note = (
            "Before proceeding, check the spec's Ambiguities section for any open "
            "questions left unanswered (the session that generated it may have exited "
            "before resolving them). If you find any, resolve them using your best "
            "judgment, document the resolution in the spec, and re-save to "
            f"`{file_path}` before continuing. "
            + staleness_note
        )
    elif mode == "prompt":
        review_note = (
            "Before proceeding, check the spec's Ambiguities section for any items "
            "marked **[UNRESOLVED]** (the session that generated it may have exited "
            "before resolving them). Resolve any you can confidently handle based on "
            f"the codebase and document them in the spec. Re-save to `{file_path}`. "
            "If any remain genuinely unresolvable, present them to the user and wait "
            "for their response before proceeding. "
            + staleness_note
        )
    else:  # review
        review_note = (
            "Before proceeding, check the spec's Ambiguities section for any open "
            "questions left unanswered (the session that generated it may have exited "
            "before resolving them). If you find any, present them to the user along "
            "with your proposed resolutions. Update the spec with their answers, "
            f"re-save to `{file_path}`, "
            "and ask for approval before continuing. "
            + staleness_note
        )

    return f"""
## {label}

The following spec was generated to guide this phase. Work from this spec rather than interpreting the raw PR description directly.

{review_note}

{spec}
"""
