"""Verify that a GitHub-side merge published the signed-off candidate.

``pm pr merge`` (pr-ac10f03) merges on GitHub pinned to the approved head and
then checks what GitHub actually published: the merge commit of the approved
head must sit on the signed-off base and carry the approved candidate tree.
A mismatch (another head, a moved base, a different result) is recorded on
``pr["merge_integrity"]`` and noted on the PR.

The same check has to run when a merge is discovered rather than published by
pm: the TUI's background/startup GitHub sync and ``pm pr sync`` used to mark a
PR merged as soon as GitHub reported it, silently finalizing a merge of code
nobody signed off on (pr-2e06289).  This module is the single implementation
shared by the publisher and the sync paths.

Nothing here writes ``project.yaml`` or prints: :func:`verify_github_merge`
performs git reads only, so a TUI sync thread can run it on its copy of the
state and the main thread can apply the result under its own lock.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from pm_core import git_ops, integration, signoff, store


@dataclass(frozen=True)
class MergeVerification:
    """Outcome of checking a published merge against the approved candidate.

    Exactly one of *problem* / *error* is set when the merge could not be
    accepted: *problem* is a definite mismatch (record it), *error* means the
    check could not run (unknown — log it, record nothing).
    """

    problem: str | None = None
    merge_sha: str | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.problem is None and self.error is None


def _short(value) -> str:
    """*value* as a short revision/tree label, never sliced if not a string.

    The approval is hand-editable state: a non-string revision or candidate
    tree is rendered as ``"?"`` instead of raising ``TypeError`` out of the
    recovery path, which does not go through the merge gate.
    """
    return value[:12] if isinstance(value, str) and value else "?"


def approved_candidate(pr_entry: dict) -> tuple[str, dict] | None:
    """``(head, integration_binding)`` when the PR holds a bound approval.

    A ``SIGNOFF_MERGE`` without an integration binding is a legacy HEAD-only
    approval: there is no base revision or candidate tree to compare against,
    so it cannot be verified (and the merge gate never accepts it anyway).

    ``signoff``/``integration`` are hand-editable state: a value that is not a
    mapping is no record, and a revision that is not a string cannot name the
    candidate that was signed off, so it reads as absent — verification is
    skipped, not crashed.

    ``candidate_tree`` is deliberately *not* normalized here.  It is the value
    the published tree is compared against, not a revision to look up: a
    hand-edited (or absent) tree cannot confirm any merge, so
    :func:`verify_github_merge` records the mismatch (rendering the value
    through :func:`_short`) instead of skipping the check.  Skipping would let
    a hand-edited tree hide a genuinely different published result.
    """
    approved = pr_entry.get("signoff")
    approved = approved if isinstance(approved, dict) else {}
    bound = approved.get("integration")
    bound = bound if isinstance(bound, dict) else {}
    head = integration.revision_of(approved.get("sha"))
    base_sha = integration.revision_of(bound.get("base_sha"))
    if (approved.get("verdict") == signoff.SIGNOFF_MERGE
            and head and base_sha):
        return head, bound
    return None


def verify_github_merge(pr_id: str, workdir: str, target_repo: str,
                        base_branch: str, base_sha: str, head: str,
                        bound: dict) -> MergeVerification:
    """Check GitHub's merge commit of *head* on *base_branch*.

    Fetch the base, find the merge commit carrying the approved head, and
    compare its first parent to *base_sha* and its tree to
    ``bound["candidate_tree"]``.  This is the check ``pm pr merge`` runs
    after publication, shared with every sync path that discovers a merge.
    """
    # The approval is hand-editable state: a revision that is not a string is
    # no revision to verify, and one interpolated into the ``git log`` range
    # must be a real object name — both read as absent.
    base_sha = integration.revision_of(base_sha)
    head = integration.revision_of(head)
    bound = bound if isinstance(bound, dict) else {}
    if not base_sha or not head:
        return MergeVerification()
    tip, err = integration.fetch_base(workdir, target_repo, base_branch)
    if err or not tip:
        return MergeVerification(error=err or "no base revision")
    log = git_ops.run_git("log", "--merges", "--format=%H %P %T",
                          f"{base_sha}..{tip}", cwd=workdir, check=False)
    if log.returncode != 0:
        # The signed-off base is not readable here: unknown, not a mismatch.
        return MergeVerification(error=git_ops.git_detail(log))

    found = None
    for line in (log.stdout or "").splitlines():
        parts = line.split()
        if len(parts) >= 4 and head in parts[1:-1]:
            found = parts

    merge_sha = None
    if found is None:
        # No merge commit of the approved head on the base: GitHub merged
        # another head (or squashed/rebased) — not the approved candidate.
        # Name the merge that published the branch when one contains it.
        published = None
        for line in (log.stdout or "").splitlines():
            parts = line.split()
            for parent in parts[2:-1]:
                if integration.is_ancestor(workdir, head, parent):
                    published = (parts[0], parent)
        if published:
            merge_sha = published[0]
            problem = (f"GitHub merged {pr_id} at {_short(published[1])}, not "
                       f"the approved head {_short(head)} (its branch had "
                       f"commits that were not signed off); merge "
                       f"{_short(merge_sha)} on {base_branch}")
        else:
            # Names the PR: the sync paths log this line without the
            # "GitHub PR #N merged" context `pm pr merge` prints.
            problem = (f"no merge commit of the approved head {_short(head)} "
                       f"for {pr_id} on {base_branch} {_short(tip)}; GitHub "
                       f"did not publish the signed-off candidate")
    else:
        merge_sha, first_parent, tree = found[0], found[1], found[-1]
        if first_parent == base_sha and tree == bound.get("candidate_tree"):
            return MergeVerification()
        if first_parent != base_sha:
            problem = (f"GitHub merged {pr_id} onto {_short(first_parent)}, "
                       f"not the signed-off base {_short(base_sha)} (the base "
                       f"moved during publication)")
        else:
            problem = (f"GitHub merged {pr_id} onto the signed-off base "
                       f"{_short(base_sha)}, but its merge result differs "
                       f"from the approved candidate")
        problem += (f"; published tree {_short(tree)}, approved "
                    f"{_short(bound.get('candidate_tree'))}")

    return MergeVerification(problem=problem, merge_sha=merge_sha)


def verify_detected_merge(root, data: dict, pr_entry: dict, workdir: str,
                          base_branch: str) -> MergeVerification | None:
    """Verify a sync-detected merge; ``None`` when the PR has no bound approval.

    *workdir* is the directory the sync used to detect the merge (the PR's own
    workdir when it exists, else another workdir / the project repo).

    Never raises: a failed check must not stop merge detection (an unreadable
    base, a missing workdir or an unexpected error becomes ``error`` — the
    merge is still finalized, the mismatch is just unproven).
    """
    try:
        candidate = approved_candidate(pr_entry)
        if candidate is None:
            return None
        head, bound = candidate
        target_repo, _ = integration.target_for(data, pr_entry, root)
        return verify_github_merge(pr_entry["id"], workdir, target_repo,
                                   base_branch, bound["base_sha"], head, bound)
    except Exception as e:  # the merge is still finalized; the check is not
        return MergeVerification(error=str(e) or type(e).__name__)


def _notes_of(pr: dict) -> list:
    """A PR's ``notes`` as a list (hand-edited state may hold a scalar)."""
    notes = pr.get("notes")
    return notes if isinstance(notes, list) else []


def _note_id(n) -> str | None:
    """A note's ``id`` when it is a string (hand-edited members read absent).

    The ids are collected into a ``set`` for :func:`store.generate_note_id`, so
    a list/mapping id (an unhashable value) raised ``TypeError`` out of every
    check that recorded a mismatch — including the TUI sync paths.
    """
    value = n.get("id") if isinstance(n, dict) else None
    return value if isinstance(value, str) and value else None


def apply_to_pr(pr: dict, verification: MergeVerification | None) -> None:
    """Record a mismatch on *pr* and note it once (mutates *pr*).

    A ``None`` verification (no bound approval) or a non-mismatch (ok /
    could-not-verify) records nothing: only a definite problem is evidence.
    Called inside the caller's ``store.locked_update`` — the publisher's or
    the TUI main thread's — never from a sync worker thread.
    """
    if verification is None or not verification.problem:
        return
    problem = verification.problem
    pr["merge_integrity"] = {"problem": problem,
                             "merge_sha": verification.merge_sha}
    text = f"Merge integrity: {problem}."
    # Hand-edited state: a malformed member is not a note, so it neither
    # suppresses this warning nor contributes an id.
    notes = _notes_of(pr)
    if any(isinstance(n, dict) and n.get("text") == text for n in notes):
        return
    created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    note_id = store.generate_note_id(
        pr.get("id") or "", text,
        {i for i in (_note_id(n) for n in notes) if i})
    pr["notes"] = notes + [{"id": note_id, "text": text,
                            "created_at": created, "last_edited": created}]
