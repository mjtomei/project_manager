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


def approved_candidate(pr_entry: dict) -> tuple[str, dict] | None:
    """``(head, integration_binding)`` when the PR holds a bound approval.

    A ``SIGNOFF_MERGE`` without an integration binding is a legacy HEAD-only
    approval: there is no base revision or candidate tree to compare against,
    so it cannot be verified (and the merge gate never accepts it anyway).
    """
    approved = pr_entry.get("signoff") or {}
    bound = approved.get("integration") or {}
    if (approved.get("verdict") == signoff.SIGNOFF_MERGE
            and approved.get("sha") and bound.get("base_sha")):
        return approved["sha"], bound
    return None


def git_detail(result) -> str:
    """stdout+stderr of a failed git call, for an error message."""
    return ((result.stdout or "").strip() + "\n"
            + (result.stderr or "").strip()).strip()


def verify_github_merge(pr_id: str, workdir: str, target_repo: str,
                        base_branch: str, base_sha: str, head: str,
                        bound: dict) -> MergeVerification:
    """Check GitHub's merge commit of *head* on *base_branch*.

    Fetch the base, find the merge commit carrying the approved head, and
    compare its first parent to *base_sha* and its tree to
    ``bound["candidate_tree"]``.  This is the check ``pm pr merge`` runs
    after publication, shared with every sync path that discovers a merge.
    """
    tip, err = integration.fetch_base(workdir, target_repo, base_branch)
    if err or not tip:
        return MergeVerification(error=err or "no base revision")
    log = git_ops.run_git("log", "--merges", "--format=%H %P %T",
                          f"{base_sha}..{tip}", cwd=workdir, check=False)
    if log.returncode != 0:
        # The signed-off base is not readable here: unknown, not a mismatch.
        return MergeVerification(error=git_detail(log))

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
            problem = (f"GitHub merged {pr_id} at {published[1][:12]}, not "
                       f"the approved head {head[:12]} (its branch had "
                       f"commits that were not signed off); merge "
                       f"{merge_sha[:12]} on {base_branch}")
        else:
            problem = (f"no merge commit of the approved head {head[:12]} on "
                       f"{base_branch} {tip[:12]}; GitHub did not publish the "
                       f"signed-off candidate")
    else:
        merge_sha, first_parent, tree = found[0], found[1], found[-1]
        if first_parent == base_sha and tree == bound.get("candidate_tree"):
            return MergeVerification()
        if first_parent != base_sha:
            problem = (f"GitHub merged {pr_id} onto {first_parent[:12]}, not "
                       f"the signed-off base {base_sha[:12]} (the base moved "
                       f"during publication)")
        else:
            problem = (f"GitHub merged {pr_id} onto the signed-off base "
                       f"{base_sha[:12]}, but its merge result differs from "
                       f"the approved candidate")
        problem += (f"; published tree {tree[:12]}, approved "
                    f"{(bound.get('candidate_tree') or '?')[:12]}")

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


def apply_to_pr(pr: dict, problem: str, merge_sha: str | None) -> None:
    """Record *problem* on *pr* and note it once (mutates *pr*).

    Called inside the caller's ``store.locked_update`` — the publisher's or
    the TUI main thread's — never from a sync worker thread.
    """
    pr["merge_integrity"] = {"problem": problem, "merge_sha": merge_sha}
    text = f"Merge integrity: {problem}."
    notes = pr.get("notes")
    if not isinstance(notes, list):
        notes = []
    if any(isinstance(n, dict) and n.get("text") == text for n in notes):
        return
    created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    note_id = store.generate_note_id(
        pr.get("id", ""), text,
        {n.get("id") for n in notes if isinstance(n, dict)})
    pr["notes"] = notes + [{"id": note_id, "text": text,
                            "created_at": created, "last_edited": created}]
