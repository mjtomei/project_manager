"""Methodology-context loader shared by the session-launching commands.

Builds the prompt handed to the launched Claude session: a framing instruction,
the shared methodology docs, the review's ``STATE.md`` (on resume), and a
target preamble.  Missing methodology files are skipped with a note rather than
erroring — not all three exist in the repo yet.
"""

from pathlib import Path

from pm_core.review import paths

# Keep the whole assembled prompt under the argv size limit of the foreground
# launch path: ``claude_launcher.launch_claude`` passes the prompt as a single
# argv argument, and Linux caps one argv string at ~128 KB (MAX_ARG_STRLEN).
# Mirrors ``plan._PROMPT_ARG_LIMIT``; kept local to avoid importing the CLI
# layer from this leaf module.
_PROMPT_BYTE_LIMIT = 120_000
# Never inline a target larger than this even when the byte budget would allow
# it — keeps one huge artifact from dominating the prompt. The methodology docs
# are prepended ahead of the target, so the *effective* inline cap is the
# smaller of this and the budget left over after them (see ``build_context``).
_MAX_INLINE_BYTES = 80_000


_PARALLEL_WORKFLOWS_CLAUSE = """\
## Parallel workflows

Use the workflow skill (if available) to parallelize these phases — it handles
fan-out and reduction, so just give it the per-phase unit of work:

- **audit phase** — one sub-stream per citation per pass.
- **review phase** — one sub-stream per prompt block (substance / structure /
  accessibility / prose).
- **response phase** — one sub-stream per proposed change or comment.

Run the apply phase sequentially — don't parallelize it.
"""


def _framing(review_dir: Path) -> str:
    return (
        "You are running the augmented adversarial-review cycle on the target "
        "below. Produce REVIEW_CYCLE_N.md, then the citation audit loop, then "
        "REVIEW_RESPONSE_CYCLE_N.md, per the methodology files included below.\n"
        f"State lives in your review's directory at {review_dir}/ — write "
        "STATE.md at every phase transition and keep all cycle files there."
    )


def _target_preamble(root: Path, target: str, target_type: str,
                     *, max_inline: int = _MAX_INLINE_BYTES) -> str:
    """Describe the artifact under review.

    For file/plan targets, inline the file contents when readable and under
    ``max_inline`` bytes so the session has the artifact in hand; otherwise
    point at the path.
    """
    lines = [f"Target ({target_type}): {target}"]
    if target_type not in ("file", "plan"):
        lines.append("This is a from-topic review with no starting file.")
        return "\n".join(lines)

    path = root / target if not Path(target).is_absolute() else Path(target)
    if not path.exists():
        # target may be repo-relative rather than pm-root-relative
        alt = Path.cwd() / target
        if alt.exists():
            path = alt
    if not path.exists():
        lines.append(f"(file not found at {path}; locate and read it yourself)")
        return "\n".join(lines)

    try:
        # Stat before reading so a huge target isn't slurped into memory just to
        # be rejected for inlining. UnicodeDecodeError (e.g. a PDF/binary target)
        # is non-fatal — point the session at the file instead of crashing.
        if path.stat().st_size > max_inline:
            lines.append(
                f"(target at {path} is large — read it yourself rather "
                "than relying on an inlined copy)")
        else:
            lines.append(f"\n--- contents of {target} ---\n{path.read_text()}")
    except (OSError, UnicodeDecodeError):
        lines.append(f"(could not read {path}; read it yourself)")
    return "\n".join(lines)


def build_context(root: Path, review_id: str, target: str,
                  target_type: str) -> str:
    """Return the full session prompt for a review against ``target``.

    Read-only: the review directory is referenced for the framing text but not
    created here (``run_review`` creates it before calling this).
    """
    review_dir = paths.dir_for(root, review_id, create=False)
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

    # Workflows-aware parallelization (note-0970084). Unconditional — the
    # phase fan-out directives apply to every review regardless of target type.
    sections.append(_PARALLEL_WORKFLOWS_CLAUSE)

    # Budget the inlined target against everything already assembled so the
    # whole prompt stays under the foreground argv limit. The methodology docs
    # alone are ~65 KB, so the fixed 80 KB target cap is not enough on its own.
    used = len("\n\n".join(sections).encode())
    inline_budget = min(_MAX_INLINE_BYTES, max(0, _PROMPT_BYTE_LIMIT - used))
    sections.append(
        f"## Target\n\n"
        f"{_target_preamble(root, target, target_type, max_inline=inline_budget)}")

    return "\n\n".join(sections)
