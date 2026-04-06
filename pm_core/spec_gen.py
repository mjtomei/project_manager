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
from pm_core.claude_launcher import launch_claude_print
from pm_core.paths import configure_logger, get_global_setting_value

_log = configure_logger("pm.spec_gen")

# Phase names that have specs
PHASES = ("impl", "qa")

_SPEC_FIELD = {
    "impl": "spec_impl",
    "qa": "spec_qa",
}


def get_spec_mode() -> str:
    """Return the global spec generation mode: auto, review, or prompt.

    Defaults to ``prompt`` — generates spec and proceeds unless the PR
    has ``review_spec: true`` or Claude flags an unresolvable ambiguity.
    """
    val = get_global_setting_value("spec-mode", "prompt").lower()
    if val in ("auto", "review", "prompt"):
        return val
    return "prompt"


def pr_spec_mode(pr: dict) -> str:
    """Return the effective spec mode for a specific PR.

    Per-PR ``review_spec: true`` overrides to ``review`` mode.
    """
    mode = get_spec_mode()
    if pr.get("review_spec"):
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


def get_spec(pr: dict, phase: str) -> str | None:
    """Get the spec content for a phase, reading from the spec file.

    Returns None if no spec exists or the file is empty.

    Lookup order:
    1. The PR's workdir pm/specs/ — the impl session writes specs here and
       it has the most up-to-date copy while the PR is being worked on.
    2. The local pm/specs/ (cwd-resolved root) — where specs live after
       the PR branch is merged back to the base repo.
    """
    field = _SPEC_FIELD.get(phase)
    if not field:
        return None

    pr_id = pr.get("id", "")

    # 1. Workdir — most up-to-date copy while the PR is in flight.
    workdir = pr.get("workdir")
    if workdir:
        p = Path(workdir) / "pm" / "specs" / pr_id / f"{phase}.md"
        if p.exists():
            content = p.read_text().strip()
            return content if content else None

    # 2. Local pm directory — spec lives here after the branch is merged.
    try:
        root = store.find_project_root()
    except FileNotFoundError:
        return None
    canonical = spec_file_path(root, pr_id, phase)
    if canonical.exists():
        content = canonical.read_text().strip()
        return content if content else None
    return None


def set_spec(pr: dict, phase: str, spec: str,
             root: Path | None = None) -> Path | None:
    """Write spec content to file and store the path in the PR entry.

    *root* is the pm project directory containing project.yaml.
    If not provided, tries to find it via ``store.find_project_root()``.

    Returns the path written, or None for invalid phases.
    """
    field = _SPEC_FIELD.get(phase)
    if not field:
        return None

    if root is None:
        try:
            root = store.find_project_root()
        except FileNotFoundError:
            _log.warning("spec_gen: cannot find project root for set_spec")
            return None

    path = spec_file_path(root, pr.get("id", "unknown"), phase)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(spec)
    pr[field] = str(path)
    _log.info("spec_gen: wrote %s spec to %s (%d chars)", phase, path, len(spec))
    return path


def _build_spec_prompt(data: dict, pr: dict, phase: str) -> str:
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

State what to test and how, grounded in the actual implementation and
the system's runtime behavior:
- Key behaviors to exercise and expected outcomes
- Setup requirements for testing
- Edge cases and failure modes to probe
- Integration points with other system components
- What constitutes a passing vs failing test
- Mocks: what external dependencies need mocking (e.g. Claude sessions, git
  operations, tmux), the contract for each mock (what it simulates), and
  what scripted responses they should return — this prevents each scenario
  agent from independently deciding how to mock, which leads to
  inconsistency""",
    }

    diff_instruction = ""
    if phase == "qa" and workdir:
        diff_instruction = f"""
Run `git diff {base_branch}...HEAD` in the workdir to see what changed.
Read source files as needed to understand the implementation.
"""

    # QA spec gets an extra section for mocks planning
    mocks_section = ""
    if phase == "qa":
        mocks_section = """5. **Mocks** — For each external dependency that scenarios should mock \
(e.g. Claude sessions, git operations, tmux): the contract (what it \
simulates), the scripted responses it should return, and what remains \
unmocked (uses the real implementation).  This section is included in \
every scenario prompt so agents know exactly what is and isn't simulated.\n"""

    mode = pr_spec_mode(pr)
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

Write a clear, structured spec.  Use markdown.  Be specific — reference
actual code paths, function names, and file locations where possible.
Do NOT include preamble or meta-commentary — output only the spec content.

The spec should contain:
1. **Requirements** — Restatement of each requirement grounded in the codebase
2. **Implicit Requirements** — What must also be true for stated requirements to hold
3. **Ambiguities** — Identified ambiguities with proposed resolutions
4. **Edge Cases** — Interactions with existing behavior not addressed in the description
{mocks_section}"""
    return prompt.strip()


def generate_spec(data: dict, pr_id: str, phase: str,
                  root: Path | None = None,
                  force: bool = False) -> tuple[str, bool]:
    """Generate a spec for a PR phase.

    Args:
        data: Project data dict.
        pr_id: PR identifier.
        phase: One of "impl", "qa".
        root: Project root (for saving).
        force: If True, regenerate even if spec already exists.

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

    mode = pr_spec_mode(pr)
    _log.info("spec_gen: generating %s spec for %s (mode=%s)", phase, pr_id, mode)

    prompt = _build_spec_prompt(data, pr, phase)
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

    # Apply all state mutations atomically via locked_update
    if root:
        def apply(fresh_data):
            fresh_pr = store.get_pr(fresh_data, pr_id)
            if not fresh_pr:
                return
            # Record the spec file path
            field = _SPEC_FIELD.get(phase)
            if field and pr.get(field):
                fresh_pr[field] = pr[field]
            # Set or clear spec_pending
            if pending_value:
                fresh_pr["spec_pending"] = pending_value
            else:
                fresh_pr.pop("spec_pending", None)

        store.locked_update(root, apply)
        _log.info("spec_gen: saved %s spec for %s (%d chars, needs_review=%s)",
                  phase, pr_id, len(spec_text), needs_review)

    # Keep caller's in-memory pr in sync
    if pending_value:
        pr["spec_pending"] = pending_value
    else:
        pr.pop("spec_pending", None)

    return spec_text, needs_review


def has_pending_spec(pr: dict) -> bool:
    """Check if a PR has a spec waiting for user review."""
    return bool(pr.get("spec_pending"))


def get_pending_spec_phase(pr: dict) -> str | None:
    """Return the phase name of the pending spec, or None."""
    pending = pr.get("spec_pending")
    if pending and isinstance(pending, dict):
        return pending.get("phase")
    return None


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

    if root:
        spec_path = pr.get(_SPEC_FIELD.get(phase, ""))

        def apply(fresh_data):
            fresh_pr = store.get_pr(fresh_data, pr_id)
            if not fresh_pr:
                return
            if edited_text is not None and spec_path:
                fresh_pr[_SPEC_FIELD[phase]] = spec_path
            fresh_pr.pop("spec_pending", None)

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

    try:
        generate_spec(data, pr_id, phase, root=root, force=True)
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
                             root: Path | None = None) -> str:
    """Build a prompt preamble for inline spec generation in the main session.

    Returns an empty string if a spec already exists for this phase.
    Otherwise returns a "Step 0" block that tells Claude to generate the
    spec, write it to a file, and register it — all within the same session.

    The guidance varies by mode:
      auto   — resolve ambiguities, save, proceed immediately.
      prompt — resolve ambiguities, save, proceed unless genuinely
               unresolvable (present flagged questions to user first).
      review — save, present spec summary to user, wait for approval.

    *root* is the pm project directory (containing project.yaml).
    """
    # If spec already exists, nothing to generate
    if get_spec(pr, phase):
        return ""

    mode = pr_spec_mode(pr)
    pr_id = pr.get("id", "???")
    phase_labels = {"impl": "implementation", "qa": "QA"}
    label = phase_labels.get(phase, phase)

    # Derive the spec file path
    if root is None:
        try:
            root = store.find_project_root()
        except FileNotFoundError:
            root = Path("pm")  # fallback
    file_path = spec_file_path(root, pr_id, phase)

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
1. **Requirements** — Key behaviors to exercise and expected outcomes
2. **Setup** — Setup requirements for testing
3. **Edge Cases** — Edge cases and failure modes to probe
4. **Pass/Fail Criteria** — What constitutes a passing vs failing test
5. **Ambiguities** — Any ambiguities you resolved and how
6. **Mocks** — For each external dependency that scenarios should mock \
(e.g. Claude sessions, git operations, tmux): the contract (what it simulates), \
the scripted responses it should return, and what remains unmocked. \
This section is included in every scenario prompt so all agents share the \
same mocking strategy.""",
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

Save the spec to `{file_path}` and then run:
  `pm pr spec-save {pr_id} {phase}`
{commit_step}
Then proceed with the {label} work below."""

    elif mode == "prompt":
        post_save = f"""\
Use your best judgement to resolve ambiguities where you can confidently do so.
If you encounter a genuinely unresolvable ambiguity — multiple valid
interpretations with materially different outcomes — include it in the spec's
"Ambiguities" section marked **[UNRESOLVED]** with a clear question.

Save the spec to `{file_path}` and then run:
  `pm pr spec-save {pr_id} {phase}`
{commit_step}
If the spec contains any **[UNRESOLVED]** ambiguities, present them to the
user and wait for their response before proceeding.  Update the spec with
their answers, re-save, then continue.  If there are no unresolved
ambiguities, proceed with the {label} work below."""

    else:  # review
        post_save = f"""\
Identify all ambiguities and present your proposed resolution for each in the
spec's "Ambiguities" section.

Save the spec to `{file_path}` and then run:
  `pm pr spec-save {pr_id} {phase}`
{commit_step}
Then present a brief summary of the spec to the user and ask whether they
approve or want changes.  If they request changes, update the spec file,
re-save, and ask again.  Once approved, proceed with the {label} work below."""

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

    if mode == "auto":
        review_note = (
            "Before proceeding, check the spec's Ambiguities section for any open "
            "questions left unanswered (the session that generated it may have exited "
            "before resolving them). If you find any, resolve them using your best "
            "judgment, document the resolution in the spec, re-save to "
            f"`{file_path}`, and run `pm pr spec-save {pr_id} {phase}` before continuing."
        )
    elif mode == "prompt":
        review_note = (
            "Before proceeding, check the spec's Ambiguities section for any items "
            "marked **[UNRESOLVED]** (the session that generated it may have exited "
            "before resolving them). Resolve any you can confidently handle based on "
            f"the codebase and document them in the spec. Re-save to `{file_path}` "
            f"and run `pm pr spec-save {pr_id} {phase}`. "
            "If any remain genuinely unresolvable, present them to the user and wait "
            "for their response before proceeding."
        )
    else:  # review
        review_note = (
            "Before proceeding, check the spec's Ambiguities section for any open "
            "questions left unanswered (the session that generated it may have exited "
            "before resolving them). If you find any, present them to the user along "
            "with your proposed resolutions. Update the spec with their answers, "
            f"re-save to `{file_path}`, run `pm pr spec-save {pr_id} {phase}`, "
            "and ask for approval before continuing."
        )

    return f"""
## {label}

The following spec was generated to guide this phase. Work from this spec rather than interpreting the raw PR description directly.

{review_note}

{spec}
"""
