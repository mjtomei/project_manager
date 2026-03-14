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


def get_spec(pr: dict, phase: str, data: dict | None = None) -> str | None:
    """Get the spec content for a phase, reading from the spec file.

    Returns None if no spec exists.  The *data* arg is used to derive
    the file path when it isn't stored in the PR entry.
    """
    field = _SPEC_FIELD.get(phase)
    if not field:
        return None

    path_str = pr.get(field)
    if path_str:
        p = Path(path_str)
        if p.exists():
            content = p.read_text().strip()
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
- What constitutes a passing vs failing test""",
    }

    diff_instruction = ""
    if phase == "qa" and workdir:
        diff_instruction = f"""
Run `git diff {base_branch}...HEAD` in the workdir to see what changed.
Read source files as needed to understand the implementation.
"""

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
"""
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

    # Save spec to file and update PR entry
    set_spec(pr, phase, spec_text, root=root)
    if root:
        store.save(data, root)
        _log.info("spec_gen: saved %s spec for %s (%d chars)",
                  phase, pr_id, len(spec_text))

    # Determine if review is needed
    needs_review = False
    if mode == "review":
        needs_review = True
    elif mode == "prompt":
        # Check for ambiguity flags
        if "AMBIGUITY_FLAG" in spec_text:
            needs_review = True
            _log.info("spec_gen: ambiguity detected in %s spec for %s, "
                      "pausing for review", phase, pr_id)

    # Set spec_pending if review is needed
    if needs_review:
        pr["spec_pending"] = {
            "phase": phase,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        if root:
            store.save(data, root)
        _log.info("spec_gen: marked spec_pending for %s/%s", pr_id, phase)

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

    if edited_text is not None:
        set_spec(pr, phase, edited_text.strip(), root=root)

    del pr["spec_pending"]
    if root:
        store.save(data, root)
    _log.info("spec_gen: approved %s spec for %s", phase, pr_id)
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
5. **Ambiguities** — Any ambiguities you resolved and how""",
    }

    instructions = spec_instructions.get(phase, spec_instructions["impl"])

    # Mode-specific guidance for ambiguity handling and what to do after saving
    if mode == "auto":
        post_save = f"""\
Use your best judgement to resolve any ambiguities based on your understanding
of the codebase and common patterns.  Document all resolved ambiguities and
your reasoning in the spec's "Ambiguities" section.

Save the spec to `{file_path}` and then run:
  `pm pr spec-save {pr_id} {phase}`

Then proceed with the {label} work below."""

    elif mode == "prompt":
        post_save = f"""\
Use your best judgement to resolve ambiguities where you can confidently do so.
If you encounter a genuinely unresolvable ambiguity — multiple valid
interpretations with materially different outcomes — include it in the spec's
"Ambiguities" section marked **[UNRESOLVED]** with a clear question.

Save the spec to `{file_path}` and then run:
  `pm pr spec-save {pr_id} {phase}`

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

    return f"""
## {label}

The following spec was generated to guide this phase. Work from this spec
rather than interpreting the raw PR description directly.

{spec}
"""
