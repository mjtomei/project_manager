"""Architecture-awareness prompt block (``pm/architecture.md``).

:func:`architecture_section` turns the project's Axiomatic Design document
into the block plan, implementation and review prompts carry: role-specific
guidance for using its FRs/DPs/Design Matrix, a bounded excerpt of the
document, and the "File Structural Debt, Don't Just Comment It" rule.

The document itself is pm state, read through ``pm_core.notes``
(``load_architecture`` / ``architecture_pointer``), the same way session notes
are; this module holds only the prompt text around it.  It lives next to
``bug_fix_prompts`` / ``regression_prompts`` rather than in ``notes`` so that
rewording a role's guidance doesn't touch the state module.
"""

from pathlib import Path

from pm_core import notes
from pm_core.prompt_bounds import ARCHITECTURE_BUDGET, bounded_text


#: Role-specific guidance, keyed by prompt type.  Formatted with
#: ``pointer`` (how the session names the document) and ``this_pr`` (the PR
#: id, or a ``<pr-id>`` placeholder).
_ROLE_GUIDANCE: dict[str, str] = {
    "plan": """\
While planning:
- Map each proposed PR to the DP(s) it changes, and name them in the PR's
  description when the files don't make it obvious.
- Order PRs so dependencies flow down the matrix. Don't plan work that adds
  upward coupling or a hidden shared-state cycle.
- If the plan legitimately introduces a new FR/DP, or moves a module from one
  DP to another, say so explicitly in the plan file — what it is, where it
  sits in the matrix order, and why — so `{pointer}` can be updated.""",
    "impl": """\
While implementing:
- Before designing, find the DP(s) this PR's task touches and keep the
  change inside them.
- If this PR legitimately introduces a new FR/DP, or moves a module from one
  DP to another, record it:
  `pm pr note add {this_pr} 'architecture: <new FR/DP or remap, where it sits in the matrix order, why>'`
  Edit `{pointer}` itself only when this PR's task asks you to —
  otherwise the note is how the change reaches it.""",
    "review": """\
While reviewing, treat the document as the baseline and check the diff for:
- New upward `*` coupling — a module in a lower-order DP importing or calling
  into a higher-order one, including a lazy import added inside a function to
  sidestep a cycle.
- New hidden shared state across DPs — module globals, shared files, or
  object attributes used as an undeclared channel between them.
- New modules that map to no DP, or changes that blur two DPs into one.
- A legitimately new FR/DP or module remap the PR doesn't record (in a PR
  note, or in the PR's own edit to `{pointer}`).

New upward coupling is **NEEDS_WORK**. A contested FR/DP boundary change
that needs human judgment is **INPUT_REQUIRED**.""",
}


#: Role-specific text appended after the structural-debt rule.  Every role in
#: ``_ROLE_GUIDANCE`` needs an entry (``""`` when the rule stands alone).
_STRUCTURAL_DEBT_ROLE_ADDENDUM: dict[str, str] = {
    "plan": """
This applies to plans too: when a plan accepts a workaround, or leaves
coupling debt in place as out of scope, file or append the improvements PR as
above and cite its id in the plan instead of leaving the debt as prose.
""",
    "impl": "",
    "review": """
Check the diff for workarounds that skipped this: one whose comment cites no
improvements PR id is **NEEDS_WORK**. In review-loop mode, follow the rule
yourself for any workaround you add while fixing.
""",
}


#: Roles :func:`architecture_section` has guidance for — one source of truth,
#: so a new role (e.g. sign-off) can't silently fall through to another
#: role's text.  Bug-fix PRs use the impl/review blocks.
PROMPT_TYPES = tuple(_ROLE_GUIDANCE)


_STRUCTURAL_DEBT_RULE = """
## File Structural Debt, Don't Just Comment It

Whenever you must add an out-of-scope workaround — a defensive guard, a lazy
import to sidestep an import cycle, a duplicated invariant check, or any
other patch around coupling this work isn't fixing — file the debt instead of
only commenting it:

1. Look for an existing PR on the same structural problem:
   `pm pr list --plan improvements`
2. If one exists, append a note so recurring pain self-prioritizes:
   `pm pr note add <pr-id> '<where you hit it and the workaround you added>'`
3. Otherwise file one:
   `pm pr add '<title>' --plan improvements --description '<the underlying coupling, where it bites, the workaround added, the proper fix>'`
4. Cite that PR id in the code comment beside the workaround — e.g.
   `<why this workaround exists>; tracked in <pr-id>` — instead of an orphan
   historical tag (a bare scenario number, a date, "temporary hack") that no
   one can follow up on.
"""


def architecture_section(root: Path, prompt_type: str, *,
                         pr_id: str | None = None,
                         max_bytes: int = ARCHITECTURE_BUDGET) -> str:
    """Return the architecture-awareness block for a prompt.

    Mirrors :func:`pm_core.notes.notes_section`: ``""`` when the project has
    no ``architecture.md`` (or it is empty or unreadable), so prompts for such
    projects are unchanged.  Otherwise the block holds, in order:
    role-specific guidance for using the FRs/DPs/matrix, an excerpt of the
    document, and the "File Structural Debt, Don't Just Comment It" rule.

    Only the excerpt is bounded (``prompt_bounds.bounded_text``, head + tail,
    marker naming the file): the document is a reference the session can read
    in full.  The guidance and the rule are instructions and are inlined
    whole.

    Args:
        root: The pm root directory.
        prompt_type: One of :data:`PROMPT_TYPES`.  An unknown type raises
            ``ValueError`` even without a document, so a typo can't silently
            drop the guidance.
        pr_id: Substituted into the impl guidance's ``pm pr note add``
            command; a placeholder is used when omitted.
        max_bytes: Budget for the document excerpt.
    """
    if prompt_type not in PROMPT_TYPES:
        raise ValueError(
            f"unknown architecture prompt type {prompt_type!r}; expected one "
            f"of {', '.join(PROMPT_TYPES)}")
    content = notes.load_architecture(root)
    if not content:
        return ""

    pointer = notes.architecture_pointer(root)
    excerpt = bounded_text(content, max_bytes=max_bytes,
                           pointer=f"`{pointer}`",
                           label="architecture document")
    guidance = _ROLE_GUIDANCE[prompt_type].format(
        pointer=pointer, this_pr=pr_id or "<pr-id>")
    rule = _STRUCTURAL_DEBT_RULE + _STRUCTURAL_DEBT_ROLE_ADDENDUM[prompt_type]
    return f"""
## Project Architecture (`{pointer}`)

This project keeps its MIT Axiomatic Design analysis in `{pointer}`:
functional requirements (FRs), the disjoint design parameters (DPs) that
satisfy them (mapped to modules and directories), the Design Matrix [A],
known coupling debt, and an FR/DP change log. Use it as the map of the
codebase — work from the FRs/DPs/matrix below instead of re-deriving the
architecture yourself, and read the file for the full text when the copy
below is abbreviated.

The matrix is ordered so dependencies flow down: a DP may depend on DPs at
or below its own order, and a `*` above the diagonal is upward coupling.
- Keep changes inside the DP(s) they belong to.
- Don't add upward `*` coupling: a lower-order DP depending on a higher-order
  one, including through a lazy (function-level) import.
- Don't add hidden shared-state cycles: module globals, shared files, or
  object attributes written by one DP and read by another as an undeclared
  channel.

{guidance}

--- begin {pointer} ---
{excerpt}
--- end {pointer} ---
{rule}"""
