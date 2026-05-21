"""Methodology-context loader shared by the session-launching commands.

Builds the prompt handed to the launched Claude session: a framing instruction,
the shared methodology docs, the review's ``STATE.md`` (on resume), and a
target preamble.  Missing methodology files are skipped with a note rather than
erroring — not all three exist in the repo yet.
"""

from pathlib import Path

from pm_core.review import paths


def _framing(review_dir: Path) -> str:
    return (
        "You are running the augmented adversarial-review cycle on the target "
        "below. Produce REVIEW_CYCLE_N.md, then the citation audit loop, then "
        "REVIEW_RESPONSE_CYCLE_N.md, per the methodology files included below.\n"
        f"State lives in your review's directory at {review_dir}/ — write "
        "STATE.md at every phase transition and keep all cycle files there."
    )


def _target_preamble(root: Path, target: str, target_type: str) -> str:
    """Describe the artifact under review.

    For file/plan targets, inline the file contents when readable so the
    session has the artifact in hand; otherwise point at the path.
    """
    lines = [f"Target ({target_type}): {target}"]
    if target_type in ("file", "plan"):
        path = root / target if not Path(target).is_absolute() else Path(target)
        if not path.exists():
            # target may be repo-relative rather than pm-root-relative
            alt = Path.cwd() / target
            if alt.exists():
                path = alt
        if path.exists():
            try:
                lines.append(f"\n--- contents of {target} ---\n{path.read_text()}")
            except OSError:
                lines.append(f"(could not read {path}; read it yourself)")
        else:
            lines.append(f"(file not found at {path}; locate and read it yourself)")
    else:
        lines.append("This is a from-topic review with no starting file.")
    return "\n".join(lines)


def build_context(root: Path, review_id: str, target: str,
                  target_type: str) -> str:
    """Return the full session prompt for a review against ``target``."""
    review_dir = paths.dir_for(root, review_id)
    sections: list[str] = [_framing(review_dir)]

    # Shared methodology docs (skip missing with a note).
    for path in paths.methodology_paths(root):
        header = f"## {path.name}"
        if path.exists():
            try:
                sections.append(f"{header}\n\n{path.read_text()}")
            except OSError:
                sections.append(f"{header}\n\n(could not read {path})")
        else:
            sections.append(f"{header}\n\n(not present at {path} — skipped)")

    # Existing STATE.md on resume.
    state = paths.state_path(root, review_id, create=False)
    if state.exists():
        try:
            sections.append(f"## STATE.md (current cycle state)\n\n{state.read_text()}")
        except OSError:
            pass

    sections.append(f"## Target\n\n{_target_preamble(root, target, target_type)}")

    return "\n\n".join(sections)
