"""Sign-off step — the dedicated lifecycle stage between ``qa`` and ``merged``.

Sign-off is a first-class PR step (status ``sign_off``) with its own tmux
window, mirroring the review/QA windows.  A Claude pane drives a *comprehensive*
review — walking every QA scenario and every step, aggregating evidence across
*all* stages (implementation repro/verify captures under ``impl/`` plus the
per-scenario captures under ``scenarios/<n>/``), reading the diff vs master, and
weighing the PR's scope.  It then emits a single **routing verdict** that pm
executes as the PR's next hop.

The router is *advisory + executor*: the Claude pane decides and writes a
self-contained ``report.html`` (the BDD behaviour report — the inspectable
audit surface; the dashboard reads its verdict meta tag), but it **never edits
code** — every fix happens in impl/qa so it re-passes review+qa.  pm reads the
emitted verdict (same transcript-polling mechanic as qa-finalize) and performs
the routed transition.

Sign-off **always gates at merge**: ``SIGNOFF_MERGE`` is a *recommendation*
(``ready_to_merge``) — sign-off never merges, and the autonomous-vs-gated merge
decision lives in the plan auto-start watcher (pr-ff9b728), not here.  On genuine
ambiguity the router emits ``SIGNOFF_BLOCKED`` and escalates rather than merging.

Sign-off **owns integration** (pr-ac10f03): the launch fetches the configured
base and computes the PR's merge with it in an isolated candidate
(:mod:`pm_core.integration`); the recorded verdict is bound to the PR HEAD,
target repo/branch, base revision and candidate tree, and ``pm pr merge``
publishes exactly that candidate or refuses and returns the PR here.  pm
routes a conflicted integration to implementation, and every bounce leaves a
``pr["signoff_return"]`` record (reason, revisions, integration context) for
the step it returns to.
"""

from __future__ import annotations

import contextlib
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from pm_core import store
from pm_core import tmux as tmux_mod
from pm_core import prompt_gen
from pm_core.cli.helpers import (
    _log,
    _pr_display_id,
    _record_status_timestamp,
)

# --- Routing verdicts ------------------------------------------------------
# The Claude pane emits exactly one of these on its own line.  pm polls the
# transcript for them (extract_verdict_from_transcript) and executes the hop.
SIGNOFF_MERGE = "SIGNOFF_MERGE"      # verified PASS -> merge (or human gate)
SIGNOFF_REQA = "SIGNOFF_REQA"        # PASS-unverified / misframed scenario -> re-qa
SIGNOFF_REVIEW = "SIGNOFF_REVIEW"    # a code change happened during QA -> review + qa
SIGNOFF_IMPL = "SIGNOFF_IMPL"        # real gap -> back to implementation
SIGNOFF_BLOCKED = "SIGNOFF_BLOCKED"  # ambiguity / out-of-scope / blocking PR -> escalate

SIGNOFF_VERDICTS = (
    SIGNOFF_MERGE,
    SIGNOFF_REQA,
    SIGNOFF_REVIEW,
    SIGNOFF_IMPL,
    SIGNOFF_BLOCKED,
)

# Distinct display markers per sign-off verdict (single source of truth for
# both the TUI tech tree and `pm pr list`).  Kept here (core, no TUI deps) so
# CLI and TUI render the recorded verdict identically.
SIGNOFF_VERDICT_ICONS = {
    SIGNOFF_MERGE: "▲",    # recommend merge (forward)
    SIGNOFF_REQA: "↻",     # re-qa
    SIGNOFF_REVIEW: "↩",   # back to review
    SIGNOFF_IMPL: "⇤",     # back to implementation
    SIGNOFF_BLOCKED: "⊘",  # escalate / hold
}

SIGNOFF_VERDICT_STYLES = {
    SIGNOFF_MERGE: "bold green",
    SIGNOFF_REQA: "bold magenta",
    SIGNOFF_REVIEW: "bold cyan",
    SIGNOFF_IMPL: "bold yellow",
    SIGNOFF_BLOCKED: "bold red",
}


def signoff_verdict_icon(verdict: str | None) -> str:
    """Return the display icon for a sign-off *verdict* (empty if unknown)."""
    return SIGNOFF_VERDICT_ICONS.get(verdict or "", "")


def display_signoff_verdict(pr: dict) -> str | None:
    """The sign-off verdict a PR row shows (CLI list and TUI tree alike).

    ``sign_off``: the latest valid recorded verdict.  A PR sign-off sent
    back (open return episode) shows that return verdict until its next
    sign-off decision.
    """
    status = (pr or {}).get("status")
    if status == "sign_off":
        return latest_signoff_verdict(pr)
    if status in ("in_progress", "in_review", "qa"):
        rec = open_return(pr)
        return rec.get("verdict") if rec else None
    return None


def signoff_window_name(pr_entry: dict) -> str:
    """The tmux window name for a PR's sign-off window (e.g. ``signoff-#42``)."""
    return f"signoff-{_pr_display_id(pr_entry)}"


# --- Verdict record + adoption --------------------------------------------
# A sign-off run records its routing verdict durably on the PR so a later
# auto-sequence tick can ADOPT it (no wasted re-run) instead of relaunching.
# The record is ``pr["signoff"] = {verdict, sha, ts, origin}`` where *sha* is
# the branch HEAD the verdict was computed against; a record is "fresh" when
# its sha matches the current HEAD (no code change since).

def head_sha(workdir: str | None) -> str | None:
    """Return the git HEAD sha of *workdir*, or None if unavailable."""
    if not workdir or not Path(workdir).exists():
        return None
    from pm_core import git_ops
    r = git_ops.run_git("rev-parse", "HEAD", cwd=workdir, check=False)
    sha = (r.stdout or "").strip()
    return sha or None


def record_signoff_verdict(root: Path, pr_id: str, verdict: str,
                           sha: str | None, origin: str,
                           report_hash: str | None = None,
                           integration: dict | None = None,
                           extra: dict | None = None) -> None:
    """Durably record a sign-off *verdict* on the PR (``pr['signoff']``).

    Single writer for the record. *origin* says who recorded it:
    ``"auto-sequence"`` (the driver reads the router pane's transcript
    verdict so a later tick can adopt it without a re-run), ``"manual"``
    (``pm pr signoff record`` — the reviewer's explicit approval after
    reading ``report.html``), or a future ``"watcher"`` (pr-ff9b728).

    Recording must be an explicit act, never a side effect of report
    (re)generation: ``pm pr signoff`` (the agent pass) records nothing —
    its report carries the verdict in the ``report.html`` meta tag.
    Recording is NOT acting — it never changes status; only
    :func:`apply_signoff_hop` (auto-sequence only) mutates state.

    *report_hash*, when given, is the sha256 of the approved
    ``report.html`` bytes; the merge gate re-hashes the on-disk report and
    refuses when it changed since approval. Records without it (the
    auto-sequence transcript path) skip that check.

    *integration* is the :func:`pm_core.integration.binding` of the
    integration check the verdict was computed against (target repo/branch,
    fetched base revision, candidate tree, status).  A SIGNOFF_MERGE
    without it is a legacy HEAD-only approval: neither adopted nor accepted
    by the merge gate.  *extra* carries provenance such as a coerced
    verdict's original keyword and reason.
    """
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).isoformat()

    def _apply(data):
        pr = store.get_pr(data, pr_id)
        if pr is not None:
            record = {
                "verdict": verdict, "sha": sha, "ts": ts, "origin": origin,
            }
            if report_hash:
                record["report_hash"] = report_hash
            if integration:
                record["integration"] = dict(integration)
            for k, v in (extra or {}).items():
                if v is not None:
                    record[k] = v
            record["evidence"] = _evidence_block(pr, sha, integration,
                                                 verdict=verdict)
            pr["signoff"] = record
            # A new sign-off decision closes the previous return episode.
            ret = pr.get("signoff_return")
            if isinstance(ret, dict) and not ret.get("resolved_at"):
                ret["resolved_at"] = ts
                ret["awaiting"] = None

    store.locked_update(root, _apply)


def signoff_launch_stamp(transcript) -> Path:
    """Sidecar of a router transcript holding the HEAD its run launched on.

    ``signoff-<pr>.jsonl`` -> ``signoff-<pr>.head``.  A transcript verdict is
    only bound to the revision the router was launched against: HEAD at
    verdict-*read* time can be a later, unreviewed commit.
    """
    return Path(transcript).with_suffix(".head")


def stamp_signoff_launch(transcript, sha: str | None,
                         base_sha: str | None = None) -> None:
    """Record *sha* as the revision the run writing *transcript* reviews.

    *base_sha* (second line) is the base revision of the integration check
    the run was launched with: its verdict may only bind to that check.
    """
    stamp = signoff_launch_stamp(transcript)
    try:
        if sha:
            stamp.parent.mkdir(parents=True, exist_ok=True)
            stamp.write_text(sha + "\n" + (base_sha + "\n" if base_sha else ""))
        elif stamp.exists():
            stamp.unlink()
    except OSError as e:
        _log.warning("sign-off launch stamp %s: %s", stamp, e)


def _launch_stamp_lines(tdir: Path, pr_id: str) -> list[str]:
    try:
        return signoff_launch_stamp(
            signoff_transcript(tdir, pr_id)).read_text().split()
    except OSError:
        return []


def signoff_launched_sha(tdir: Path, pr_id: str) -> str | None:
    """HEAD the driver's current sign-off run launched on, or None."""
    lines = _launch_stamp_lines(tdir, pr_id)
    return lines[0] if lines else None


def signoff_launched_base(tdir: Path, pr_id: str) -> str | None:
    """Base revision of the integration check the run launched with."""
    lines = _launch_stamp_lines(tdir, pr_id)
    return lines[1] if len(lines) > 1 else None


def is_legacy_approval(record: dict | None) -> bool:
    """A SIGNOFF_MERGE recorded without an integration binding (HEAD-only)."""
    record = record or {}
    return (record.get("verdict") == SIGNOFF_MERGE
            and not record.get("integration"))


def fresh_recorded_verdict(pr: dict, current_sha: str | None) -> str | None:
    """Return the recorded verdict if it is fresh (record sha == *current_sha*).

    Fresh means the verdict was computed against the current branch HEAD (no
    code change since), so auto-sequence can adopt it instead of relaunching.
    Returns None when there is no record, it carries no verdict, the sha is
    unknown, or the record is stale.  An approval the merge gate invalidated
    (the base moved — :func:`invalidate_signoff`) and a legacy HEAD-only
    SIGNOFF_MERGE (:func:`is_legacy_approval`) are never fresh: both need an
    integration-aware sign-off against the current base.
    """
    record = (pr or {}).get("signoff") or {}
    verdict = record.get("verdict")
    sha = record.get("sha")
    if record.get("invalidated") or is_legacy_approval(record):
        return None
    if verdict and sha and current_sha and sha == current_sha:
        return verdict
    return None


def latest_signoff_verdict(pr: dict) -> str | None:
    """Return the most recently recorded sign-off verdict, fresh or not.

    Used for display (icons / ``pm pr list``); does not consider HEAD
    staleness, but an invalidated record shows nothing — sign-off is about
    to re-run.
    """
    record = (pr or {}).get("signoff") or {}
    if record.get("invalidated"):
        return None
    return record.get("verdict") or None


def invalidate_signoff(root: Path, pr_id: str, reason: str) -> None:
    """Mark the PR's recorded sign-off as no longer valid (*reason*).

    Used by the merge gate when the approved base / candidate no longer
    matches: the record stays for provenance, but it is never adopted or
    accepted again, so the sign-off driver retires the run and re-runs
    sign-off against the current base ("return to sign-off").
    """
    from datetime import datetime, timezone

    def _apply(data):
        pr = store.get_pr(data, pr_id)
        rec = (pr or {}).get("signoff")
        if isinstance(rec, dict) and rec.get("verdict"):
            rec["invalidated"] = reason
            rec["invalidated_at"] = datetime.now(timezone.utc).isoformat()

    store.locked_update(root, _apply)


# --- Evidence provenance + explicit reuse ---------------------------------
# A resolved integration changes the commit the sign-off report reviews (the
# base is merged into the branch), so "the old review/QA evidence still
# covers this" must be an explicit, recorded judgment — not something pm
# invents by assuming the change was harmless.  PM records the revisions the
# available evidence was produced against and the agent's reuse statement;
# the merge gate refuses a resolved/behaviourally-changed approval that has
# none.

# The evidence block lands in project.yaml (rewritten on every sign-off
# record), so its lists are bounded; a total records what was left out.
_EVIDENCE_LIST_LIMIT = 20


def qa_evidence(pr_id: str) -> dict | None:
    """Latest QA evidence and the revision it exercised, when recorded."""
    import json
    from pm_core.paths import latest_qa_status_path
    path = latest_qa_status_path(pr_id)
    if path is None:
        return None
    error = None
    try:
        status = json.loads(path.read_text())
    except (OSError, ValueError):
        status, error = None, "unreadable"
    resume = None
    try:
        resume = json.loads((path.parent / "qa_resume.json").read_text())
    except (OSError, ValueError):
        resume = None
    # Malformed evidence must not crash the sign-off record write: record
    # what is readable and leave the rest empty.  A corrupt qa_status.json
    # still leaves qa_resume.json's revision usable evidence.
    if not isinstance(status, dict):
        status, error = {}, error or "malformed"
    if not isinstance(resume, dict):
        resume = {}
    changes = resume.get("planner_code_changes")
    # The revision is printed/sliced by the prompt and written to project.yaml:
    # a non-string value is malformed evidence, not a revision (slicing it
    # would raise out of the sign-off launch).
    planner_head = resume.get("planner_head")
    out = {
        "overall": status.get("overall"),
        "planner_head": planner_head if isinstance(planner_head, str) else None,
        "planner_code_changes": (
            changes if isinstance(changes, list) else []),
        "status_file": str(path),
    }
    if error:
        out["error"] = error
    return out


def _report_evidence(pr_id: str, reviewed_head: str | None) -> dict:
    """The reuse statement from a report written for *reviewed_head*.

    A statement is only attributed when the report names a HEAD that
    identifies this revision (the same 7-character minimum the manual record
    path enforces); a missing or short tag cannot tie the statement to the
    reviewed revision, and a report left by an earlier run must not have its
    words recorded as this decision's.
    """
    meta = report_meta(pr_id)
    meta_head = (meta.get("head") or "").strip()
    if not reviewed_head or len(meta_head) < 7 \
            or not reviewed_head.startswith(meta_head):
        meta = {}
        meta_head = ""
    reused = (meta.get("evidence") or "").strip()
    tokens = [x.strip() for x in re.split(r"[,\s]+", reused) if x.strip()]
    out = {
        "report_head": meta_head or None,
        "report_base": meta.get("base") or None,
        "report_candidate": meta.get("candidate") or None,
        "reused": tokens[:_EVIDENCE_LIST_LIMIT],
        "reason": meta.get("evidence-reason") or None,
        "checks": meta.get("checks") or None,
    }
    if len(tokens) > _EVIDENCE_LIST_LIMIT:
        out["reused_total"] = len(tokens)
    return out


_VERDICT_STAGE = {
    SIGNOFF_MERGE: "merge", SIGNOFF_REQA: "qa", SIGNOFF_REVIEW: "review",
    SIGNOFF_IMPL: "impl", SIGNOFF_BLOCKED: "blocked",
}


def _evidence_block(pr: dict, reviewed_head: str | None,
                    integration: dict | None,
                    verdict: str | None = None) -> dict:
    """The provenance recorded on ``pr["signoff"]["evidence"]``."""
    prior = pr.get("signoff") or {}
    prior_block = None
    if prior.get("verdict"):
        prior_block = {k: prior.get(k) for k in ("verdict", "sha", "ts",
                                                  "origin", "invalidated")}
        prior_block["integration"] = prior.get("integration")
    full = pr.get("integration") or {}
    if full.get("head") != reviewed_head:
        # The stored check describes another revision (the branch moved after
        # it ran, or it failed and recorded no HEAD).  Its candidate tree and
        # resolution are not this decision's: recording them beside the
        # reviewed HEAD would attribute provenance the decision never had.
        full = {}
    seen = integration or {}
    qa = qa_evidence(pr["id"])
    if qa:
        changes = list(qa.get("planner_code_changes") or [])
        if len(changes) > _EVIDENCE_LIST_LIMIT:
            qa = dict(qa,
                      planner_code_changes=changes[:_EVIDENCE_LIST_LIMIT],
                      planner_code_changes_total=len(changes))
    review_sha, review_note = None, (
        "pm does not record the revision the review ran on")
    if qa and qa.get("planner_head") and not qa.get("planner_code_changes"):
        # QA runs after review and records the revision it exercised.  When
        # QA committed nothing, review saw that same revision.
        review_sha = qa["planner_head"]
        review_note = ("inferred: QA exercised this revision and recorded no "
                       "code changes")
    return {
        "reviewed_head": reviewed_head,
        "required_return_stage": _VERDICT_STAGE.get(verdict, verdict),
        "candidate_tree": seen.get("candidate_tree")
        or full.get("candidate_tree"),
        "resolved_from": seen.get("resolved_from")
        or full.get("resolved_from"),
        "review": {
            "reviewed_at": pr.get("reviewed_at"),
            "sha": review_sha,
            "sha_source": "inferred-from-qa" if review_sha else None,
            "note": review_note,
        },
        "qa": qa,
        "prior_signoff": prior_block,
        **_report_evidence(pr["id"], reviewed_head),
    }


def approval_justification_problem(pr_id: str, integration: dict | None,
                                   head: str | None) -> str | None:
    """Why a MERGE lacks the explicit evidence statement it requires, or None.

    Applies only when the candidate carries a resolution, a base change that
    can alter behaviour, or a base summary pm could not compute: the report
    must name the candidate (resolved candidates) and state which existing
    evidence is reused and why, or which targeted checks were run.  This is
    the "explicit reuse" requirement; an unstated assumption never becomes an
    approval.

    An ``in_base`` record is exempt: the approved head is already published,
    so there is no candidate to name and the merge step only finalizes that
    merge (the same exemption :func:`merge_gate_refusal` applies to the
    candidate-tree check).
    """
    from pm_core import integration as integ
    rec = integration or {}
    if rec.get("status") == integ.IN_BASE:
        return None
    resolution = rec.get("resolution") or {}
    behavior = rec.get("base_behavior_changes") or []
    # A summary that failed (``base_behavior_error``) is not evidence that the
    # base is behaviour-neutral: requiring the statement keeps the failure from
    # silently granting the metadata exemption.
    error = rec.get("base_behavior_error")
    if not resolution and not behavior and not error:
        return None
    meta = report_meta(pr_id)
    meta_head = (meta.get("head") or "").strip()
    if len(meta_head) < 7:
        # Same minimum as the manual record path: a short tag cannot
        # identify a HEAD (and would match almost any sha as a prefix).
        return ("report.html has no usable pm-signoff-head tag; it cannot be "
                "tied to the reviewed HEAD")
    if not head or not head.startswith(meta_head):
        return (f"report.html reviewed HEAD {meta_head[:12]}, but sign-off "
                f"reviewed {(head or '?')[:12]}")
    if resolution:
        candidate = rec.get("candidate_tree") or ""
        if not candidate:
            # A failed or superseded re-check no longer names the tree the
            # approval was bound to; the merge must not be justified against
            # a candidate pm cannot confirm (a report tag cannot fix that).
            return ("the latest integration check does not record a candidate "
                    "tree (it may have failed or been superseded); re-run "
                    "`pm pr signoff integrate --record` or a fresh sign-off")
        named = (meta.get("candidate") or "").strip()
        if len(named) < 7:
            # Same minimum as the head tag: a short value can match almost
            # any tree as a prefix without identifying the approved one.
            return ("report.html has no usable pm-signoff-candidate tag; it "
                    "must name the approved candidate tree "
                    f"({candidate[:12] or '?'})")
        if not candidate.startswith(named):
            return ("report.html does not name the approved candidate tree "
                    f"(pm-signoff-candidate {candidate[:12] or '?'})")
        if not resolution.get("applied_merge_sha"):
            return ("the resolved candidate was not applied to the PR branch")
        if resolution.get("unresolved"):
            return "the integration resolution left unresolved conflicts"
    reused = (meta.get("evidence") or "").strip()
    reason = (meta.get("evidence-reason") or "").strip()
    checks = (meta.get("checks") or "").strip()
    if not checks and not (reused and reason):
        if error:
            return ("pm could not summarise the base's behaviour-relevant "
                    f"changes ({error}); report.html must state which existing "
                    "evidence is reused and why (pm-signoff-evidence + "
                    "pm-signoff-evidence-reason) or which targeted checks were "
                    "run (pm-signoff-checks)")
        return ("report.html must state which existing evidence is reused "
                "and why (pm-signoff-evidence + pm-signoff-evidence-reason) "
                "or which targeted checks were run (pm-signoff-checks)")
    return None


def effective_verdict(verdict: str | None, integration: dict | None,
                      head: str | None) -> tuple[str | None, str | None]:
    """Earliest-step routing pm enforces on a router verdict.

    Returns ``(verdict, coerced_reason)``; *coerced_reason* is None when the
    verdict stands.  A conflicted integration can only go back to
    implementation (reconciling the base is code work), so MERGE / REVIEW /
    REQA become IMPL.  A MERGE needs a mergeable integration check of the
    current HEAD; without one (check failed, never ran, other HEAD) it is
    BLOCKED — approving is impossible until sign-off can check the base.
    """
    from pm_core import integration as integ
    if not verdict:
        return verdict, None
    rec = integration or {}
    of_head = bool(head) and rec.get("head") == head
    if of_head and rec.get("status") == integ.CONFLICT \
            and verdict in (SIGNOFF_MERGE, SIGNOFF_REVIEW, SIGNOFF_REQA):
        return SIGNOFF_IMPL, (
            f"{verdict} coerced to {SIGNOFF_IMPL}: merging "
            f"{rec.get('base_branch')}@{(rec.get('base_sha') or '?')[:8]} "
            f"conflicts ({', '.join((rec.get('conflicts') or [])[:5])}); "
            "reconciling it is implementation work")
    if of_head and rec.get("status") == integ.RESOLVED:
        resolution = rec.get("resolution") or {}
        if resolution.get("unresolved") \
                and verdict in (SIGNOFF_MERGE, SIGNOFF_REVIEW, SIGNOFF_REQA):
            reasons = "; ".join(
                str(u.get("conflicts")) for u in resolution["unresolved"][:3])
            return SIGNOFF_IMPL, (
                f"{verdict} coerced to {SIGNOFF_IMPL}: pm could not resolve "
                f"the metadata conflict safely ({reasons})")
        if verdict == SIGNOFF_MERGE and not resolution.get("applied_merge_sha"):
            why = rec.get("apply_error") or "the workdir could not take the merge"
            return SIGNOFF_BLOCKED, (
                f"{SIGNOFF_MERGE} coerced to {SIGNOFF_BLOCKED}: the "
                f"metadata-only conflict was resolved in the isolated "
                f"candidate but could not be applied to the PR branch "
                f"({why}); clean the workdir and re-run sign-off")
    if verdict == SIGNOFF_MERGE and not integ.valid_for(rec, head):
        if not of_head:
            why = "no integration check of the current HEAD"
        else:
            why = integ.summary(rec)
        return SIGNOFF_BLOCKED, (
            f"{SIGNOFF_MERGE} coerced to {SIGNOFF_BLOCKED}: cannot approve "
            f"without a conflict-free integration check ({why}); re-run "
            f"sign-off once `pm pr signoff integrate` succeeds")
    return verdict, None


def merge_gate_refusal(pr: dict, current_sha: str | None,
                       base_branch: str | None = None) -> str | None:
    """Why the ``pm pr merge`` sign-off gate (#226) refuses *pr*, or None.

    Record-only (no network): merge requires a recorded SIGNOFF_MERGE whose
    sha matches *current_sha* and that is bound to a conflict-free
    integration check (target branch = *base_branch* when given) which the
    merge gate has not invalidated; legacy HEAD-only approvals are refused.
    A manual approval (``pm pr signoff record``) additionally pins the
    approved ``report.html`` content hash, so an edited report re-blocks.
    Auto-sequence records carry no hash (the transcript verdict is the
    approval) and skip that check.  Shared by the CLI gate and the TUI
    auto-merge so the TUI never attempts a merge the gate would refuse.
    ``pm pr merge`` then re-fetches the base and recomputes the candidate
    (:func:`pm_core.integration.compute_candidate`) before publishing.
    """
    from pm_core import integration as integ
    pr_id = pr.get("id")
    record = pr.get("signoff") or {}
    if record.get("invalidated"):
        return (f"PR {pr_id}: the sign-off approval is no longer valid "
                f"({record['invalidated']}). Sign-off must re-run against "
                f"the current base: `pm pr signoff --fresh {pr_id}` (the "
                f"auto-start / auto-sequence driver re-runs it itself).")
    if is_legacy_approval(record):
        return (f"PR {pr_id}: the recorded {SIGNOFF_MERGE} predates "
                f"integration-aware sign-off (bound to HEAD only). Run a "
                f"fresh sign-off: `pm pr signoff --fresh {pr_id}`.")
    fresh = fresh_recorded_verdict(pr, current_sha)
    if fresh != SIGNOFF_MERGE:
        recorded = latest_signoff_verdict(pr)
        if recorded == SIGNOFF_MERGE and fresh is None:
            return (f"PR {pr_id}: recorded sign-off verdict {recorded} is "
                    f"stale (HEAD moved since). Re-run `pm pr signoff "
                    f"{pr_id}` against current HEAD.")
        if recorded:
            return (f"PR {pr_id}: sign-off verdict is {recorded}, not "
                    f"{SIGNOFF_MERGE}. Run `pm pr signoff {pr_id}` to "
                    f"re-route.")
        return (f"PR {pr_id}: no sign-off verdict recorded yet. Run "
                f"`pm pr signoff {pr_id}` first.")
    bound = record.get("integration") or {}
    if bound.get("status") not in integ.MERGEABLE \
            or not bound.get("base_sha") or not bound.get("candidate_tree"):
        return (f"PR {pr_id}: the approval is not bound to a conflict-free "
                f"integration ({bound.get('status') or 'no check'}). Re-run "
                f"`pm pr signoff --fresh {pr_id}`.")
    if base_branch and bound.get("base_branch") != base_branch:
        return (f"PR {pr_id}: the approval targets "
                f"{bound.get('base_branch')!r}, but the project merges into "
                f"{base_branch!r}. Re-run `pm pr signoff --fresh {pr_id}`.")
    # The approval names the exact head/candidate it reviewed.  A re-check
    # that produced another candidate (a moved base, a changed resolution)
    # makes the approval stale even before the merge re-fetches anything.
    current = pr.get("integration") or {}
    if bound.get("head") and current.get("head") \
            and current["head"] != bound["head"]:
        return (f"PR {pr_id}: the integration was re-checked at another HEAD "
                f"({(current['head'] or '?')[:12]} != "
                f"{(bound['head'] or '?')[:12]}); the approval no longer "
                f"matches. Re-run `pm pr signoff --fresh {pr_id}`.")
    if bound.get("candidate_tree") and current.get("candidate_tree") \
            and current["candidate_tree"] != bound["candidate_tree"]:
        return (f"PR {pr_id}: the integration candidate changed since "
                f"sign-off ({current['candidate_tree'][:12]} != "
                f"{bound['candidate_tree'][:12]}); re-run `pm pr signoff "
                f"--fresh {pr_id}`.")
    bound_resolution = bound.get("resolution_digest")
    if bound_resolution:
        # Recompute the digest from the record instead of trusting the stored
        # value alone: a resolution that changed without its digest (a
        # partially applied update, a hand-edited state file) must not look
        # like the approved one.
        recomputed = integ._resolution_digest(current.get("resolution"))
        stored = current.get("resolution_digest")
        if stored and recomputed and stored != recomputed:
            return (f"PR {pr_id}: the recorded metadata resolution does not "
                    f"match its digest; re-run `pm pr signoff --fresh "
                    f"{pr_id}`.")
        current_digest = stored or recomputed
        if current_digest != bound_resolution:
            return (f"PR {pr_id}: the metadata resolution changed since "
                    f"sign-off; re-run `pm pr signoff --fresh {pr_id}`.")
        resolution = current.get("resolution") or {}
        if resolution.get("unresolved"):
            return (f"PR {pr_id}: the integration resolution left unresolved "
                    f"conflicts; the candidate is not conflict-free. Re-run "
                    f"`pm pr signoff --fresh {pr_id}`.")
        if not resolution.get("applied_merge_sha"):
            return (f"PR {pr_id}: the resolved candidate was not applied to "
                    f"the PR branch; clean the workdir and re-run "
                    f"`pm pr signoff --fresh {pr_id}`.")
        problem = approval_justification_problem(pr_id, current, current_sha)
        if problem:
            return (f"PR {pr_id}: cannot merge the resolved candidate — "
                    f"{problem}. Fix report.html and run `pm pr signoff "
                    f"record {pr_id}`, or re-run sign-off.")
    elif current.get("base_behavior_changes"):
        problem = approval_justification_problem(pr_id, current, current_sha)
        if problem:
            return (f"PR {pr_id}: the base brings behavioural changes and the "
                    f"report does not state the evidence/checks relied on — "
                    f"{problem}. Fix report.html and run `pm pr signoff "
                    f"record {pr_id}`, or re-run sign-off.")
    elif current.get("base_behavior_error"):
        # A summary pm could not compute is not an exemption: the base may
        # still change behaviour, so the same statement is required.
        problem = approval_justification_problem(pr_id, current, current_sha)
        if problem:
            return (f"PR {pr_id}: pm could not summarise the base's "
                    f"behavioural changes and the report does not state the "
                    f"evidence/checks relied on — {problem}. Fix report.html "
                    f"and run `pm pr signoff record {pr_id}`, or re-run "
                    f"sign-off.")
    if current and not current.get("candidate_tree") \
            and current.get("status") != integ.IN_BASE:
        # The approval names a candidate tree; a re-check that can no longer
        # record one (a failed fetch, an aborted merge) cannot justify it,
        # even when the record carries no resolution or behavioural changes.
        # An absent record is left to the bound approval (publication
        # revalidates it); a present-but-candidate-less one supersedes it.
        # ``in_base`` is exempt: the approved head is already published, and
        # the merge step's recovery path finalizes that merge instead.
        return (f"PR {pr_id}: the latest integration check does not record a "
                f"candidate tree (it may have failed or been superseded); "
                f"re-run `pm pr signoff --fresh {pr_id}`.")
    recorded_hash = (pr.get("signoff") or {}).get("report_hash")
    if recorded_hash:
        import hashlib
        from pm_core.paths import captures_root
        croot = captures_root()
        report = croot / pr_id / "report.html" if croot else None
        current_hash = (
            hashlib.sha256(report.read_bytes()).hexdigest()
            if report is not None and report.is_file() else None)
        if current_hash != recorded_hash:
            return (f"PR {pr_id}: report.html changed since the recorded "
                    f"approval; re-run `pm pr signoff record {pr_id}` "
                    f"after reviewing it.")
    return None


def launch_signoff_window(data: dict, pr_entry: dict, *, fresh: bool = False,
                          background: bool = False,
                          transcript: str | None = None,
                          session_name: str | None = None) -> None:
    """Launch a tmux sign-off window with a single Claude router pane.

    Mirrors ``pm_core.cli.pr._launch_review_window``: existing-window fast
    path (switch unless ``fresh``), capture watching sessions on a fresh
    rebuild, register the pane in the pane registry with role
    ``signoff-claude``, then switch watching sessions onto the new window.
    The sign-off agent reads captures and writes ``report.html`` itself —
    no separate shell evidence pane is needed.
    """
    # Imported lazily to avoid a heavy import cycle at module import time.
    from pm_core.cli.helpers import _get_pm_session, _ensure_workdir, state_root
    from pm_core.claude_launcher import build_claude_shell_cmd
    from pm_core import pane_registry, home_window
    from pm_core.model_config import (
        resolve_model_and_provider, get_pr_model_override,
    )

    if not tmux_mod.has_tmux() or not tmux_mod.in_tmux():
        print("Sign-off window requires tmux.")
        return

    pm_session = session_name or _get_pm_session()
    if not pm_session or not tmux_mod.session_exists(pm_session):
        print(f"Sign-off window: tmux session '{pm_session}' not found.")
        return

    workdir = pr_entry.get("workdir")
    if not workdir or not Path(workdir).exists():
        root = state_root()
        workdir = _ensure_workdir(data, pr_entry, root)
        if not workdir:
            print(f"Sign-off window: no workdir for {pr_entry['id']}. "
                  "Start the PR first.")
            return

    pr_id = pr_entry["id"]
    window_name = signoff_window_name(pr_entry)

    # Serialize concurrent launches of THIS PR's sign-off window.  There is
    # no other lock around the find-window -> create-window check-then-act, so
    # two `pm pr signoff` racing (after both provisioned the workdir) would
    # each find no window and each create one -> duplicate windows.  An
    # exclusive per-PR lock makes the loser wait, then take the existing-
    # window fast path below.
    import fcntl
    from pm_core.paths import workdirs_base
    _launch_lock_path = workdirs_base() / f".signoff-launch-{pm_session}-{pr_id}.lock"
    _launch_lock_f = open(_launch_lock_path, "w")
    try:
        fcntl.flock(_launch_lock_f.fileno(), fcntl.LOCK_EX)
        # Fast path: existing window + not fresh -> just switch.
        existing = tmux_mod.find_window_by_name(pm_session, window_name)
        sessions_on_signoff: list[str] = []
        if existing:
            if fresh:
                sessions_on_signoff = tmux_mod.sessions_on_window(
                    pm_session, existing["id"])
                home_window.park_if_on(pm_session, existing["id"])
                tmux_mod.kill_window(pm_session, existing["id"])
                print(f"Killed existing sign-off window '{window_name}'")
            else:
                tmux_mod.select_window(pm_session, existing["id"])
                print(f"Switched to existing sign-off window '{window_name}'")
                return

        # Integration check against the latest configured base (fetch +
        # isolated candidate), recorded on the PR before the prompt is built
        # so the router reviews — and its verdict binds to — that base.  A
        # metadata-only conflict is resolved in the isolated candidate and
        # applied to the branch, then re-checked: the router reviews the
        # integrated code and the report/verdict bind to that exact
        # candidate.
        from pm_core import integration
        root = state_root()
        rec: dict = {}
        try:
            rec = integration.prepare(root, pr_id)
            print(f"Integration: {integration.summary(rec)}")
            if rec.get("resolution"):
                unresolved = integration.unresolved_paths(rec)
                for entry in (rec["resolution"].get("paths") or []):
                    path = entry.get("path")
                    if path in unresolved:
                        print(f"  attempted {path} by record id "
                              "— NOT resolved")
                    else:
                        print(f"  resolved {path} by record id")
                if rec["resolution"].get("applied_merge_sha"):
                    print("  applied to the PR branch as "
                          f"{rec['resolution']['applied_merge_sha'][:12]}")
                if rec.get("apply_error"):
                    print(f"  not applied: {rec['apply_error']}")
            data = store.load(root)
        except Exception as e:  # never block the sign-off launch on it
            _log.warning("sign-off integration check for %s: %s", pr_id, e)
            print(f"Integration check failed: {e}")

        # Bind this run to the revision it reviews (and the base it was
        # checked against): the driver only records its transcript verdict
        # while HEAD still equals this stamp.  Only a newly created window
        # stamps; the fast path above reuses a run whose stamp is on disk.
        if transcript:
            stamp_signoff_launch(transcript, head_sha(workdir),
                                 rec.get("base_sha"))

        _resolution = resolve_model_and_provider(
            "signoff",
            pr_model=get_pr_model_override(pr_entry),
            project_data=data,
        )

        signoff_prompt = prompt_gen.generate_signoff_prompt(
            data, pr_id, session_name=pm_session)

        # Container cwd quirk mirrors review: Claude's cwd is /workspace inside a
        # container, so the transcript symlink + prompt file must target the
        # mounted host path via write_dir.
        from pm_core.container import (
            is_container_mode_enabled, _CONTAINER_WORKDIR,
            wrap_claude_cmd, ContainerError, remove_container, _make_container_name,
        )
        if is_container_mode_enabled():
            _claude_cwd = _CONTAINER_WORKDIR
            _claude_write_dir = workdir
        else:
            _claude_cwd = workdir
            _claude_write_dir = None

        claude_cmd = build_claude_shell_cmd(
            prompt=signoff_prompt,
            transcript=transcript,
            cwd=_claude_cwd,
            write_dir=_claude_write_dir,
            model=_resolution.model,
            provider=_resolution.provider,
            effort=_resolution.effort,
            session_type="signoff")

        branch = pr_entry.get("branch", "")
        if is_container_mode_enabled():
            remove_container(_make_container_name(f"signoff-{pr_id}"))
            _stag = pm_session.removeprefix("pm-") if pm_session else None
            try:
                claude_cmd, _cname = wrap_claude_cmd(
                    claude_cmd, workdir, label=f"signoff-{pr_id}",
                    allowed_push_branch=branch,
                    session_tag=_stag,
                    pr_id=pr_id)
            except ContainerError as e:
                print(str(e))
                return

        # background -> don't steal focus (auto-sequence); explicit switch below
        # moves exactly the sessions that were watching the old window.
        switch = not background

        try:
            # Single pane — the sign-off agent reads captures and writes
            # report.html directly; the report carries the diff inline and
            # the dashboard surfaces it. No separate evidence pane needed.
            claude_pane = tmux_mod.new_window_get_pane(
                pm_session, window_name, claude_cmd, workdir, switch=switch)
            if not claude_pane:
                print(f"Sign-off window: failed to create tmux window '{window_name}'.")
                return

            wid_result = subprocess.run(
                tmux_mod._tmux_cmd("display", "-t", claude_pane, "-p",
                                   "#{window_id}"),
                capture_output=True, text=True,
            )
            signoff_win_id = wid_result.stdout.strip()
            if signoff_win_id:
                tmux_mod.set_shared_window_size(pm_session, signoff_win_id)
                pane_registry.register_pane(
                    pm_session, signoff_win_id, claude_pane,
                    "signoff-claude", claude_cmd)

                def _reset_user_modified(raw):
                    d = pane_registry._prepare_registry_data(raw, pm_session)
                    wd = pane_registry.get_window_data(d, signoff_win_id)
                    wd["user_modified"] = False
                    return d

                pane_registry.locked_read_modify_write(
                    pane_registry.registry_path(pm_session), _reset_user_modified)

            if sessions_on_signoff:
                tmux_mod.switch_sessions_to_window(
                    sessions_on_signoff, pm_session, window_name)

            print(f"Opened sign-off window '{window_name}'")
        except Exception as e:
            _log.warning("Failed to launch sign-off window: %s", e)
            print(f"Sign-off window error: {e}")
    finally:
        _launch_lock_f.close()


# Hops that carry a state side-effect (a sign_off -> X status transition).
# ready_to_merge / blocked / unknown carry NO state change.
_BOUNCE_HOP_STATUS = {"qa": "qa", "review": "in_review", "impl": "in_progress"}


def decide_signoff_hop(verdict: str | None) -> str:
    """Pure DECISION half of sign-off routing — maps a verdict to a hop token.

    This function has **no side effects**: it never touches project state. It is
    safe to call from any context (including a manual / recommendation-only
    ``pm pr signoff``).  The state mutation lives in :func:`apply_signoff_hop`,
    which is invoked ONLY from the auto-sequence driver — so a sign-off verdict
    can cause an actual transition (for ANY hop, not just merge) only under
    auto-sequence.

    Sign-off **always gates at merge**: ``SIGNOFF_MERGE`` is always a
    *recommendation* (``"ready_to_merge"``) — sign-off never merges. The actual
    auto-merge-vs-hold decision belongs to the plan auto-start watcher
    (pr-ff9b728) per its per-plan config.

    Returns one of:

    * ``"ready_to_merge"`` — the router recommends merge; the PR stays in
      ``sign_off`` (pm/the watcher decides the merge).
    * ``"qa"`` / ``"review"`` / ``"impl"`` — a bounce (apply_signoff_hop will
      transition sign_off -> qa / in_review / in_progress).
    * ``"blocked"`` — escalate; the PR stays in ``sign_off``.
    * ``"unknown"`` — no recognized verdict (still running / no decision yet).
    """
    if verdict == SIGNOFF_MERGE:
        return "ready_to_merge"
    if verdict == SIGNOFF_BLOCKED:
        return "blocked"
    return {
        SIGNOFF_REQA: "qa",
        SIGNOFF_REVIEW: "review",
        SIGNOFF_IMPL: "impl",
    }.get(verdict or "", "unknown")


def apply_signoff_hop(root: Path, pr_id: str, hop: str,
                      return_record: dict | None = None) -> str:
    """SIDE-EFFECT half of sign-off routing — perform a bounce hop's transition.

    **Auto-sequence only.**  Keeping the mutation here (separate from the pure
    :func:`decide_signoff_hop`) enforces the invariant that a sign-off verdict
    only ever changes state under the auto-sequence driver; manual
    ``pm pr signoff`` decides/recommends but never mutates.

    For a bounce hop (``qa`` / ``review`` / ``impl``) this transitions
    ``sign_off -> qa / in_review / in_progress`` (guarded on the PR still being
    in ``sign_off`` so a concurrent sync isn't clobbered), returning the hop, or
    ``"unknown"`` if the PR already left ``sign_off``.  ``ready_to_merge`` /
    ``blocked`` / ``unknown`` carry no state change and are returned unchanged
    (the PR legitimately stays in ``sign_off`` — pm/the watcher owns the merge).

    *return_record* (a bounce's :func:`build_return_record`) is written to
    ``pr["signoff_return"]`` in the same locked update as the transition, so
    the routing reason and revisions never exist without the status change
    (or vice versa) — a restart resumes from both.
    """
    to_status = _BOUNCE_HOP_STATUS.get(hop)
    if to_status is None:
        return hop  # ready_to_merge / blocked / unknown: no state change

    transitioned = {"ok": False}

    def _apply(data):
        pr = store.get_pr(data, pr_id)
        if pr and pr.get("status") == "sign_off":
            pr["status"] = to_status
            _record_status_timestamp(pr, to_status)
            # Consume the recorded verdict: a bounce sends the PR back through a
            # step that may NOT change the branch HEAD (re-qa never commits), so
            # leaving the record in place would let a later sign_off re-entry
            # re-adopt the same (now spent) fresh verdict and loop forever.
            pr.pop("signoff", None)
            if return_record is not None:
                pr["signoff_return"] = return_record
            transitioned["ok"] = True

    store.locked_update(root, _apply)
    return hop if transitioned["ok"] else "unknown"


# --- Return records (sign-off -> earlier step) ---------------------------
# A bounce leaves ``pr["signoff_return"]`` behind: why sign-off sent the PR
# back, which revisions it reviewed, the integration context (base revision,
# conflicts, overlap) and whether pm merged the clean base into the branch.
# The routed step's prompt renders it; ``awaiting`` stays set until that
# step actually launches a fresh session, so a restart / idle event can't
# advance the PR on an older session or verdict.

def report_meta(pr_id: str) -> dict[str, str]:
    """``pm-signoff-*`` meta tags of the PR's ``report.html`` (or {})."""
    from pm_core.behavior_report import extract_signoff_meta
    from pm_core.paths import captures_root
    croot = captures_root()
    if not croot:
        return {}
    return extract_signoff_meta(croot / pr_id / "report.html")


def build_return_record(pr: dict, verdict: str, hop: str, *,
                        reviewed_head: str | None,
                        original_verdict: str | None = None,
                        coerced_reason: str | None = None,
                        applied: dict | None = None,
                        apply_error: str | None = None) -> dict:
    """The ``pr["signoff_return"]`` record for a bounce (see above)."""
    from datetime import datetime, timezone
    meta = report_meta(pr["id"])
    reason = None
    # Only a report written for this decision supplies the reason: its
    # verdict tag names the routed (or router's) verdict and, when present,
    # its head tag the reviewed HEAD — not a report left by an earlier run.
    meta_verdict = (meta.get("verdict") or "").upper()
    meta_head = meta.get("head") or ""
    if meta_verdict and meta_verdict in (verdict, original_verdict) \
            and (not meta_head or (len(meta_head) >= 7 and reviewed_head
                                   and reviewed_head.startswith(meta_head))):
        reason = meta.get("reason") or None
    rec = pr.get("integration") or {}
    integ = None
    if rec and (rec.get("head") == reviewed_head
                or (rec.get("resolution") or {}).get("applied_merge_sha")):
        integ = {k: rec.get(k) for k in (
            "target_repo", "base_branch", "base_sha", "merge_base", "status",
            "conflicts", "overlap", "error", "resolution",
            "base_behavior_changes")}
    now = datetime.now(timezone.utc).isoformat()
    out = {
        "verdict": verdict, "hop": hop,
        "reason": reason or coerced_reason or "see report.html and PR notes",
        "reviewed_head": reviewed_head, "integration": integ,
        "applied": applied, "awaiting": hop, "ts": now,
    }
    if hop in _CLAIMED_RETURN_HOPS:
        # The driver performing the hop owns the relaunch: the claim is
        # written in the same locked update as the transition, so no other
        # driver can take it in between (see claim_return_launch).
        out["launch_claim"] = {"hop": hop, "at": now}
    if original_verdict and original_verdict != verdict:
        out["original_verdict"] = original_verdict
    if coerced_reason:
        out["coerced_reason"] = coerced_reason
    if apply_error:
        out["apply_error"] = apply_error
    return out


def open_return(pr: dict | None) -> dict | None:
    """The PR's sign-off return record while that episode is open."""
    rec = (pr or {}).get("signoff_return")
    if isinstance(rec, dict) and rec.get("verdict") \
            and not rec.get("resolved_at"):
        return rec
    return None


def return_awaiting(pr: dict | None) -> str | None:
    """The hop a sign-off return still waits to launch (impl/review/qa)."""
    rec = (pr or {}).get("signoff_return") or {}
    return rec.get("awaiting") or None


def parse_ts(value):
    """An ISO timestamp as a datetime (Python 3.10 rejects a "Z" suffix).

    Raises TypeError / ValueError like :func:`datetime.fromisoformat`.
    """
    from datetime import datetime
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


RETURN_LAUNCH_CLAIM_SECONDS = 180
# Hops whose relaunch is ``--fresh`` (kills the window it finds) and so
# needs one launcher; a QA return is guarded by the QA loop's running check.
_CLAIMED_RETURN_HOPS = ("impl", "review")


def claim_return_launch(root: Path, pr_id: str, hop: str) -> bool:
    """Take the launch of the routed *hop*'s fresh session (one winner).

    Several drivers act on ``awaiting`` (the TUI routing a verdict or
    catching up after a restart, every ``pm pr auto-sequence`` tick).  The
    impl and review relaunches are ``--fresh`` — each kills the window it
    finds — so two concurrent launchers kill each other's session and leave
    duplicates behind.  The first caller records a claim
    and launches; later callers see it and leave the launch alone.  The
    driver that performs the hop holds the claim from the transition on
    (:func:`build_return_record`), so only catch-up paths (restart, an
    ``awaiting`` tick) call this.
    ``awaiting`` itself stays set until the session opens, and a claim
    whose launcher died expires after RETURN_LAUNCH_CLAIM_SECONDS.
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    won = {"ok": False}

    def _apply(data):
        pr = store.get_pr(data, pr_id)
        rec = (pr or {}).get("signoff_return")
        if not isinstance(rec, dict) or rec.get("awaiting") != hop:
            return
        claim = rec.get("launch_claim") or {}
        try:
            age = (now - parse_ts(claim.get("at"))).total_seconds()
        except (TypeError, ValueError):
            age = None
        if claim.get("hop") == hop and age is not None \
                and 0 <= age < RETURN_LAUNCH_CLAIM_SECONDS:
            return
        rec["launch_claim"] = {"hop": hop, "at": now.isoformat()}
        won["ok"] = True

    try:
        store.locked_update(root, _apply)
    except Exception as e:
        _log.warning("claim sign-off return launch for %s: %s", pr_id, e)
        return False
    return won["ok"]


def clear_return_awaiting(root: Path, pr_id: str, hop: str) -> None:
    """The routed *hop* launched a fresh session: stop forcing a relaunch."""
    def _apply(data):
        pr = store.get_pr(data, pr_id)
        rec = (pr or {}).get("signoff_return")
        if isinstance(rec, dict) and rec.get("awaiting") == hop:
            rec["awaiting"] = None
            rec.pop("launch_claim", None)

    try:
        data = store.load(root)
        if return_awaiting(store.get_pr(data, pr_id)) != hop:
            return
        store.locked_update(root, _apply)
    except Exception as e:
        _log.warning("clear sign-off return for %s: %s", pr_id, e)


def format_signoff_return(pr: dict, *, for_signoff: bool = False) -> str:
    """Prompt block for a PR sign-off sent back (empty when there is none)."""
    rec = open_return(pr)
    if not rec:
        return ""
    head = (rec.get("reviewed_head") or "?")[:12]
    lines = [
        "\n## Previous sign-off return" if for_signoff
        else "\n## Returned from sign-off",
        "",
        f"Sign-off routed this PR back with **{rec['verdict']}** "
        f"(to {rec.get('hop')}) after reviewing HEAD `{head}`.",
        f"Reason: {rec.get('reason')}",
    ]
    if rec.get("original_verdict"):
        lines.append(f"(The router chose {rec['original_verdict']}; pm "
                     f"routed it to the earliest affected step: "
                     f"{rec.get('coerced_reason')})")
    integ = rec.get("integration") or {}
    if integ:
        base = (f"`{integ.get('base_branch')}` @ "
                f"`{(integ.get('base_sha') or '?')[:12]}` from "
                f"`{integ.get('target_repo')}`")
        lines.append(f"Integration with {base}: **{integ.get('status')}**.")
        if integ.get("conflicts"):
            lines.append("Conflicting paths: "
                         + ", ".join(f"`{c}`" for c in integ["conflicts"]))
        if integ.get("overlap"):
            lines.append("Changed on both sides: "
                         + ", ".join(f"`{c}`" for c in integ["overlap"]))
        resolution = integ.get("resolution") or {}
        if resolution:
            paths = [p.get("path") for p in resolution.get("paths") or []
                     if p.get("path")]
            paths_text = ", ".join(f"`{p}`" for p in paths or ["project.yaml"])
            unresolved = resolution.get("unresolved") or []
            if unresolved:
                # A failed attempt is retained on the record (never applied).
                # Say so: claiming a resolution here would mislead the step
                # that has to reconcile the conflict by hand.
                lines.append(
                    "pm could not resolve the metadata conflict by record id "
                    f"in {paths_text} — real field, deletion and ambiguity "
                    "conflicts are never auto-resolved:")
                for entry in unresolved[:5]:
                    lines.append(f"- `{entry.get('path')}`: "
                                 f"{entry.get('conflicts')}")
            else:
                lines.append(
                    "pm resolved the metadata conflict by record id in "
                    f"{paths_text} (both sides' independent records are kept; "
                    "real field, deletion and ambiguity conflicts are never "
                    "auto-resolved).")
            resolved_from = resolution.get("resolved_from") or {}
            if resolved_from.get("head"):
                lines.append(
                    f"Resolved from PR HEAD `{resolved_from['head'][:12]}` "
                    f"against base `{(resolved_from.get('base_sha') or '?')[:12]}`.")
            if resolution.get("applied_merge_sha"):
                lines.append(
                    f"pm applied that resolution and merged the base into the "
                    f"branch as `{resolution['applied_merge_sha'][:12]}` — "
                    "review/verify the integrated result, not only the PR's "
                    "own diff.")
                # The launch apply (prepare) leaves no ``applied`` block on
                # the return record, so the routed step would otherwise use
                # its usual ``<base>...HEAD`` diff against a stale base ref
                # and see the merged base commits as PR changes.
                if not (rec.get("applied") or {}).get("merge_sha"):
                    applied_base = (resolved_from.get("base_sha")
                                    or integ.get("base_sha"))
                    if applied_base:
                        lines.append(
                            f"The PR's changes on top of that base: `git diff "
                            f"{applied_base[:12]} HEAD` (your usual diff "
                            "against "
                            f"`{integ.get('base_branch') or 'the base'}` may "
                            "be stale and include the merged base commits).")
        if integ.get("base_behavior_changes"):
            lines.append(
                "The new base also changes behaviour-relevant configuration: "
                + "; ".join(str(b) for b in integ["base_behavior_changes"][:10])
                + ". Assess whether the evidence still covers it.")
    applied = rec.get("applied") or {}
    if applied.get("merge_sha"):
        lines.append(
            f"pm merged the base revision into the PR branch as "
            f"`{applied['merge_sha'][:12]}` — review/verify the integrated "
            "result, not only the PR's own diff.")
        if applied.get("base_sha"):
            # The workdir's own base refs (origin/<base>, <base>) are not
            # updated by pm, so a usual `<base>...HEAD` diff would list the
            # merged base commits as PR changes.
            lines.append(
                f"The PR's changes on top of that base: `git diff "
                f"{applied['base_sha'][:12]} HEAD` (your usual diff against "
                f"`{integ.get('base_branch') or 'the base'}` may be stale and "
                "include the merged base commits).")
    elif rec.get("apply_error"):
        lines.append(f"pm did not merge the base into the branch: "
                     f"{rec['apply_error']}.")
    if not for_signoff and integ.get("status") == "conflict":
        sha = integ.get("base_sha") or ""
        lines.append(
            f"\nReconcile it in this branch: `git fetch` the base and "
            f"`git merge {sha[:12] or integ.get('base_branch')}` (or a newer "
            f"base), resolve the conflicts preserving both sides' intent, run "
            "the tests, commit and push the PR branch. Never push or merge "
            "into the base branch yourself — the merge step publishes only a "
            "freshly signed-off candidate.")
    if for_signoff:
        lines.append(
            f"\nProvenance: `git log {head}..HEAD` shows what changed since "
            "that sign-off. Decide explicitly whether earlier review/QA "
            "evidence still covers the current HEAD; code changes cannot be "
            "approved on stale evidence.")
    else:
        lines.append("\nWhen this step completes, the PR goes back through "
                     "the remaining steps and a fresh sign-off.")
    return "\n".join(lines) + "\n"


# --- Driver step (shared by `pm pr auto-sequence` and the TUI scheduler) ---
# Both auto-sequence drivers run the SAME sign-off state machine; only how they
# launch windows (click invoke vs TUI subprocess / TUI loops) differs.  The
# step below owns every sign-off state side effect; launching stays with the
# caller.

def signoff_transcript(tdir: Path, pr_id: str) -> Path:
    """The sign-off router's transcript symlink under a driver's *tdir*."""
    return tdir / f"signoff-{pr_id}.jsonl"


def signoff_transcript_verdict(tdir: Path, pr_id: str) -> str | None:
    """Return the routing verdict in *tdir*'s sign-off transcript, or None."""
    from pm_core.verdict_transcript import extract_verdict_from_transcript

    transcript = signoff_transcript(tdir, pr_id)
    if not (transcript.is_file() or transcript.is_symlink()):
        return None
    return extract_verdict_from_transcript(str(transcript), SIGNOFF_VERDICTS)


def signoff_window_pane(session: str, pr_entry: dict) -> str | None:
    """Return the first pane id of the PR's sign-off tmux window, or None."""
    win = tmux_mod.find_window_by_name(session, signoff_window_name(pr_entry))
    if not win:
        return None
    panes = tmux_mod.get_pane_indices(session, win["index"])
    return panes[0][0] if panes else None


def retire_signoff_run(session: str, pr_entry: dict, tdir: Path) -> None:
    """Tear down a PR's sign-off window + transcript when bouncing out of sign_off.

    A bounce hop (re-qa / review / impl) moves the PR out of ``sign_off`` while
    the router's window and its single ``signoff-<id>.jsonl`` transcript live on
    (the QA loop only sweeps ``qa-*`` windows).  Unlike review's
    iteration-numbered transcripts, sign-off reuses one transcript path, so on
    re-entry the existing-window fast path would switch to the stale window and
    the transcript check would replay the *old* verdict — re-bouncing forever
    (a re-qa never changes HEAD, so the consumed record can't guard it).
    Retiring both forces a genuine fresh router run on the next sign_off entry.
    Captures / ``report.html`` are left alone.
    """
    from pm_core import home_window
    win = tmux_mod.find_window_by_name(session, signoff_window_name(pr_entry))
    if win:
        home_window.park_if_on(session, win["id"])
        tmux_mod.kill_window(session, win["id"])
    transcript = signoff_transcript(tdir, pr_entry["id"])
    for f in (transcript, signoff_launch_stamp(transcript)):
        try:
            if f.is_symlink() or f.exists():
                f.unlink()
        except OSError:
            pass


@dataclass(frozen=True)
class SignoffStep:
    """Outcome of one :func:`step_signoff` tick.

    *action* is ``"launch"`` (caller must launch a fresh router window),
    ``"running"`` (router still working — nothing to do) or ``"hop"`` (a
    verdict was acted on; *hop* is :func:`apply_signoff_hop`'s result).
    *stale* is True when a launch follows retiring an outdated run, and
    *reason* says why (HEAD moved, base moved, legacy approval).
    *sha* is the branch HEAD the step evaluated against.  *coerced* is pm's
    reason when it routed the router's verdict to an earlier step.
    """

    action: str
    hop: str | None = None
    verdict: str | None = None
    stale: bool = False
    sha: str | None = None
    reason: str | None = None
    coerced: str | None = None


def stale_reason(record: dict) -> str:
    """Why a recorded sign-off verdict is not fresh (display / logs)."""
    if record.get("invalidated"):
        return str(record["invalidated"])
    if is_legacy_approval(record):
        return "legacy HEAD-only approval"
    return "HEAD moved"


def _record_applied_integration(root: Path, pr_id: str, rec: dict,
                                reviewed: str | None,
                                merge_sha: str) -> None:
    """Persist the resolved candidate a bounce applied to the branch.

    The branch now contains the base, so the record becomes ``up_to_date`` at
    the merge commit and keeps its resolution (with ``applied_merge_sha``);
    a later check then carries the provenance forward.  Guarded on the
    reviewed head: a concurrent check that already recorded another revision
    wins — except for a bare up-to-date check of the merge this call just
    made.  That check describes the same revision but cannot know about the
    apply (the stored record it carried from still said ``resolved``, with
    no ``applied_merge_sha``), so letting it stand would silently drop the
    provenance and, with it, the explicit-reuse requirement for this
    candidate.
    """
    from pm_core import integration as integ
    updated = dict(rec, head=merge_sha, status=integ.UP_TO_DATE)
    # The apply that this call records succeeded: an earlier "could not apply"
    # (e.g. a dirty workdir at sign-off launch) no longer describes the record.
    updated.pop("apply_error", None)
    resolution = updated.get("resolution") or {}
    if resolution.get("resolved_from"):
        # Keep the revisions the resolution combined visible at the top
        # level, where the evidence block and the prompt read them.
        updated["resolved_from"] = resolution["resolved_from"]
    updated["resolution_digest"] = integ._resolution_digest(
        updated.get("resolution"))
    compact = integ.compact(updated)

    def _apply(d):
        p = store.get_pr(d, pr_id)
        if p is None:
            return
        cur = p.get("integration") or {}
        if reviewed and cur.get("head") and cur["head"] != reviewed:
            # A concurrent actor moved the branch (or already recorded another
            # revision): its record describes what the branch now is.
            bare_merge_check = (
                cur["head"] == merge_sha
                and cur.get("status") == integ.UP_TO_DATE
                and not cur.get("resolution"))
            if not bare_merge_check:
                return
        p["integration"] = compact
    try:
        store.locked_update(root, _apply)
    except Exception as e:  # provenance is best-effort; the bounce goes on
        _log.warning("sign-off %s: could not record the applied resolution: "
                     "%s", pr_id, e)


def _prepare_bounce(root: Path, pr_id: str, verdict: str, hop: str,
                    sha: str | None, original: str | None,
                    coerced: str | None) -> dict:
    """Integrate a clean, moved base into the PR branch, then build the
    return record.  The revalidating step must see the integrated code; a
    conflicted base is left for implementation (no half-merge)."""
    from pm_core import integration as integ
    try:
        pr = store.get_pr(store.load(root), pr_id) or {"id": pr_id}
    except Exception:
        pr = {"id": pr_id}
    applied, apply_error = None, None
    rec = pr.get("integration") or {}
    if pr.get("status") == "sign_off" and rec.get("head") == sha \
            and rec.get("status") in (integ.CLEAN, integ.RESOLVED):
        reviewed = rec.get("head")
        merge_sha, apply_error = integ.apply_integration(root, pr_id, rec)
        if merge_sha:
            applied = {"from_head": sha, "merge_sha": merge_sha,
                       "base_sha": rec.get("base_sha")}
            # The return record's integration snapshot must show the applied
            # resolution: the next stage is looking at the integrated branch.
            rec = dict(rec)
            resolution = dict(rec.get("resolution") or {})
            if resolution:
                resolution["applied_merge_sha"] = merge_sha
                # The record this bounce applied may be a fresh (unapplied)
                # RESOLVED check, which carries no resolved_from yet; the next
                # stage must still see the revisions the resolution combined.
                resolution.setdefault("resolved_from", {
                    "head": sha, "base_sha": rec.get("base_sha"),
                    "merge_base": rec.get("merge_base"),
                    "status": rec.get("status")})
                rec["resolution"] = resolution
            pr = dict(pr, integration=rec)
            if resolution:
                # Record that the branch now carries the resolved candidate.
                # ``prepare`` normally applies at sign-off launch; a bounce is
                # the first successful apply when the launch could not touch a
                # dirty workdir.  Without this, the next check sees an
                # up-to-date branch but no ``applied_merge_sha`` and drops the
                # provenance — losing the explicit-reuse requirement.
                _record_applied_integration(root, pr_id, rec, reviewed,
                                            merge_sha)
            _log.info("sign-off %s: integrated %s@%s into the branch as %s",
                      pr_id, rec.get("base_branch"),
                      (rec.get("base_sha") or "")[:8], merge_sha[:8])
    return build_return_record(
        pr, verdict, hop, reviewed_head=sha, original_verdict=original,
        coerced_reason=coerced, applied=applied, apply_error=apply_error)


def step_signoff(root: Path, pr_entry: dict, *, session: str, tdir: Path,
                 read_verdict=None, window_pane=None,
                 retire=None) -> SignoffStep:
    """Advance a ``sign_off`` PR one auto-sequence tick (state side only).

    1. ADOPT a fresh recorded verdict (record sha == current HEAD, not
       invalidated by the merge gate, not a legacy HEAD-only approval) —
       picks up a hand-recorded approval without a wasted re-run.
    2. A STALE record (HEAD moved since it ran, the merge gate found the
       base moved, or a legacy approval) is never trusted: retire that run
       (window + transcript), clear the record -> ``launch``.
    3. No record: a run launched on another revision than the current HEAD
       (see :func:`stamp_signoff_launch`; unstamped counts as unknown) is
       retired before its verdict can count -> ``launch`` (stale).  Otherwise
       read this driver's transcript; a verdict there goes through
       :func:`effective_verdict` (a conflicted integration routes to IMPL; a
       MERGE without a conflict-free check of this HEAD is BLOCKED) and is
       recorded (origin ``auto-sequence``, sha = the launched HEAD, bound to
       the PR's integration check of that HEAD) so later ticks adopt it.
    4. Still nothing: ``launch`` if the window is gone, else ``running``.
    5. Verdict: pure :func:`decide_signoff_hop`; a bounce first merges a
       clean moved base into the PR branch and builds the return record,
       then the auto-sequence-only :func:`apply_signoff_hop` transitions and
       persists it; a bounce also retires the run so re-entry starts a
       genuine fresh router.

    *read_verdict* / *window_pane* / *retire* default to this module's
    helpers; the CLI passes its own module-level names so existing patch
    points keep working.
    """
    read_verdict = read_verdict or signoff_transcript_verdict
    window_pane = window_pane or signoff_window_pane
    retire = retire or retire_signoff_run
    with _step_lock(pr_entry["id"]) as locked:
        if not locked:
            # Another driver is mid-step on this PR; it acts on the verdict
            # and the next tick re-evaluates whatever it left behind.
            return SignoffStep("running")
        # Re-read under the lock: the caller's entry may predate another
        # driver's step (the TUI and every auto-sequence tick act on the same
        # verdict).  A bounce merges the clean base into the branch before it
        # transitions, so a driver acting on the old snapshot would see "HEAD
        # moved", retire the run and relaunch sign-off for a PR that already
        # left it.
        try:
            disk_pr = store.get_pr(store.load(root), pr_entry["id"])
        except Exception:
            disk_pr = None
        if disk_pr is not None:
            if disk_pr.get("status") != "sign_off":
                return SignoffStep("running")
            pr_entry = disk_pr
        return _step_signoff_locked(root, pr_entry, session=session,
                                    tdir=tdir, read_verdict=read_verdict,
                                    window_pane=window_pane, retire=retire)


# A step holds the lock for a few git/tmux calls; the TUI takes it on its
# event loop, so a busy lock is waited on only briefly, never indefinitely.
_STEP_LOCK_WAIT = 2.0


@contextlib.contextmanager
def _step_lock(pr_id: str):
    """Per-PR lock serializing :func:`step_signoff` across drivers.

    Yields False when another driver still holds it after _STEP_LOCK_WAIT.
    """
    from pm_core.paths import workdirs_base
    with store.bounded_flock(workdirs_base() / f".signoff-step-{pr_id}.lock",
                             _STEP_LOCK_WAIT) as held:
        yield held


def _step_signoff_locked(root: Path, pr_entry: dict, *, session: str,
                         tdir: Path, read_verdict, window_pane,
                         retire) -> SignoffStep:
    from pm_core import integration as integ
    pr_id = pr_entry["id"]
    current_sha = head_sha(pr_entry.get("workdir"))
    record = pr_entry.get("signoff") or {}

    verdict = fresh_recorded_verdict(pr_entry, current_sha)
    original, coerced = record.get("original_verdict"), \
        record.get("coerced_reason")

    if verdict is None and record.get("verdict"):
        reason = stale_reason(record)
        retire(session, pr_entry, tdir)

        def _clear(d):
            p = store.get_pr(d, pr_id)
            if p:
                p.pop("signoff", None)
        store.locked_update(root, _clear)
        return SignoffStep("launch", stale=True, sha=current_sha,
                           reason=reason)

    if verdict is None:
        tverdict = read_verdict(tdir, pr_id)
        launched = signoff_launched_sha(tdir, pr_id)
        if current_sha and (launched or tverdict is not None) \
                and launched != current_sha:
            # HEAD moved while the router ran (or the run carries no launch
            # revision): its verdict reviewed other code.  Retire it before
            # it is recorded against the new HEAD.
            retire(session, pr_entry, tdir)
            return SignoffStep("launch", stale=True, sha=current_sha,
                               reason="HEAD moved")
        irec = pr_entry.get("integration") or {}
        launched_base = signoff_launched_base(tdir, pr_id)
        if tverdict is not None and launched_base \
                and irec.get("base_sha") != launched_base:
            # The integration was re-recorded against another base while the
            # router ran: its verdict assessed the launch-time base.
            retire(session, pr_entry, tdir)
            return SignoffStep("launch", stale=True, sha=current_sha,
                               reason="integration re-checked during the run")
        if tverdict is not None:
            # launched == current_sha here (or HEAD is unknown).
            verdict, coerced = effective_verdict(tverdict, irec, current_sha)
            if verdict == SIGNOFF_MERGE:
                problem = approval_justification_problem(
                    pr_id, irec, current_sha)
                if problem:
                    verdict, coerced = SIGNOFF_BLOCKED, (
                        f"{SIGNOFF_MERGE} coerced to {SIGNOFF_BLOCKED}: "
                        f"{problem}")
            original = tverdict if coerced else None
            bound = integ.binding(irec) if (
                current_sha and irec.get("head") == current_sha) else None
            record_signoff_verdict(
                root, pr_id, verdict, current_sha, origin="auto-sequence",
                integration=bound,
                extra={"original_verdict": original,
                       "coerced_reason": coerced})

    if verdict is None:
        if window_pane(session, pr_entry) is None:
            return SignoffStep("launch", sha=current_sha)
        return SignoffStep("running", sha=current_sha)

    hop = decide_signoff_hop(verdict)
    return_record = None
    if hop in _BOUNCE_HOP_STATUS:
        return_record = _prepare_bounce(root, pr_id, verdict, hop,
                                        current_sha, original, coerced)
    hop = apply_signoff_hop(root, pr_id, hop, return_record=return_record)
    if hop in _BOUNCE_HOP_STATUS:
        retire(session, pr_entry, tdir)
    return SignoffStep("hop", hop=hop, verdict=verdict, sha=current_sha,
                       coerced=coerced)
