"""Pre-flight base integration gate before review iterations and QA.

Sign-off owns integration (:mod:`pm_core.integration`): it fetches the
configured base, computes the merge with the PR HEAD in an isolated
candidate, and routes a conflicted candidate back to implementation.  That
check is *last*, so a base conflict discovered there throws away a completed
review + QA cycle.

This module runs the same check **before a downstream writer starts**:

* before review (first iteration and every later iteration), and
* before QA planning.

The integration primitive is reused unchanged: it fetches into pm-owned
refs and computes the candidate without touching the PR worktree, its
index, branch or stashes.  A conflict does not launch the reviewer/planner;
it records the exact HEAD/base pair, the conflicting paths and the stage the
PR was headed to on ``pr["base_return"]``, transitions the PR back to
implementation once (a launch claim makes the owner unique) and hands it the
rework instructions.  A clean integration simply continues the intended
phase.  A failed fetch/probe is a **retryable** failure — never a conflict
and never an approval; at a writer launch the phase proceeds (the gate is a
waste-avoidance pre-check, sign-off remains the authority), while after a
return it means "not proven complete" and the handoff waits.

The return record is deliberately separate from ``pr["signoff_return"]``:
that record drives sign-off-only hops (``signoff.apply_signoff_hop`` guards
``status == "sign_off"``) and must not be consumed by a pre-review check.
The claim/awaiting handshake mirrors
:func:`pm_core.signoff.claim_return_launch` / ``clear_return_awaiting`` so a
restart, a stale callback or a concurrent driver cannot start a second
implementation writer.
"""

from __future__ import annotations

import glob
import os
import secrets
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from pm_core import git_ops, integration, store
from pm_core.paths import configure_logger

_log = configure_logger("pm.base_check")

# Stages a writer is about to start.
STAGE_REVIEW = "review"
STAGE_REVIEW_ITERATION = "review_iteration"
STAGE_QA = "qa"

# Gate decisions.
PROCEED = "proceed"   # check ran; mergeable — continue the intended phase
CONFLICT = "conflict"  # conflicts; returned to implementation (this call)
WAIT = "wait"          # an identical unresolved pair is already returned
RETRY = "retry"        # fetch/probe failed; retryable, not a conflict
SKIPPED = "skipped"    # not applicable (phase/status/sign-off owns it)

# A returned PR that keeps conflicting on newly moved heads is capped so a
# pathological loop cannot spin forever.  The unchanged-pair case is already
# deduplicated (WAIT), which is the endless loop the task calls out.
MAX_RETURNS_PER_BASE = 5

# How long an impl pane must have been idle before its turn counts as
# finished work.  A background test/edit started just before the idle turn
# surfaces (dirty tree / moved HEAD / moved base) inside this window; a
# wake-up turn also refreshes the hook timestamp.
IDLE_SETTLE_SECONDS = 5.0

# Claim lifetime for the one implementation relaunch (mirrors sign-off).
RETURN_LAUNCH_CLAIM_SECONDS = 180

# Backoff for a failed fetch/probe so the TUI's completion poll does not
# hammer the network; the writer-launch gate fails open regardless.
RETRY_MIN_SECONDS = 30.0
RETRY_MAX_SECONDS = 600.0

# Return verdict recorded on pr["base_return"].
VERDICT_BASE_CONFLICT = "BASE_CONFLICT"


@dataclass
class GateResult:
    """Outcome of :func:`gate`."""

    decision: str
    stage: str
    status: str | None = None
    head: str | None = None
    base_sha: str | None = None
    conflicts: list[str] = field(default_factory=list)
    error: str | None = None
    returned: bool = False
    already_returned: bool = False
    launched: bool = False
    reason: str = ""
    record: dict = field(default_factory=dict)


@dataclass
class CompletionResult:
    """Outcome of :func:`impl_completion`."""

    complete: bool
    reason: str
    resume_loop: bool = False


# --- small git helpers -----------------------------------------------------

def _git(*args: str, cwd) -> subprocess.CompletedProcess:
    return git_ops.run_git(*args, cwd=cwd, check=False)


def _out(r: subprocess.CompletedProcess) -> str:
    return (r.stdout or "").strip()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_ts(value) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def head_sha(workdir: str | None) -> str | None:
    """HEAD of *workdir*, or None when it is not a readable checkout."""
    if not workdir or not Path(workdir).is_dir():
        return None
    return _out(_git("rev-parse", "HEAD", cwd=workdir)) or None


def git_op_in_progress(workdir: str) -> str | None:
    """Name of an in-progress merge/rebase/cherry-pick/revert, or None."""
    for ref, label in (
        ("MERGE_HEAD", "merge"),
        ("CHERRY_PICK_HEAD", "cherry-pick"),
        ("REVERT_HEAD", "revert"),
    ):
        if _git("rev-parse", "-q", "--verify", ref, cwd=workdir).returncode == 0:
            return label
    git_dir = _out(_git("rev-parse", "--absolute-git-dir", cwd=workdir))
    if git_dir:
        for d in ("rebase-merge", "rebase-apply"):
            if (Path(git_dir) / d).exists():
                return "rebase"
    return None


# pm's own state file is written by the host in a PR workdir; it is never
# the implementation's unfinished edit and must not block the handoff.  Match
# the exact repo-root-relative paths: a file that merely happens to be named
# ``project.yaml`` in some other ``pm/`` directory is a real edit.
_PM_STATE_PATHS = frozenset({
    "project.yaml", "project.yaml.lock",
    "pm/project.yaml", "pm/project.yaml.lock",
})


def tracked_dirty(workdir: str) -> bool:
    """Uncommitted changes to tracked files (untracked files do not count).

    pm's state files (``project.yaml`` / its lock at the repo root or under
    ``pm/``) are ignored: the host writes them into a PR workdir and they
    are not implementation edits.  Fixtures, drafts and other untracked
    files never count.
    """
    out = _out(_git("status", "--porcelain", "--untracked-files=no",
                    cwd=workdir))
    for line in out.splitlines():
        # ``_out`` strips leading whitespace from the first line, so take the
        # path after the two status columns rather than after the space.
        path = line[2:].strip()
        if " -> " in path:  # porcelain rename: "old -> new"
            path = path.split(" -> ", 1)[1].strip().strip('"')
        if Path(path).as_posix() in _PM_STATE_PATHS:
            continue
        return True
    return False


def _base_ref(base_branch: str) -> str:
    return f"refs/heads/{base_branch}"


def _stamp(pr: dict, status: str) -> None:
    """Record ``updated_at`` / the status timestamp (cli.helpers' rule)."""
    # Reuse the canonical transition rule rather than re-stating it here: a
    # status write that drifts from ``pm``'s own transitions (a missing
    # ``started_at``, a new status-specific timestamp) is invisible until a
    # reader keys off it.
    from pm_core.cli.helpers import _record_status_timestamp
    _record_status_timestamp(pr, status)


def _int_or(value, default: int) -> int:
    """*value* as an int, or *default* when it is missing or malformed.

    A hand-edited/corrupt ``project.yaml`` must not make the return raise
    inside the locked update: the gate would then report "the PR left the
    phase" instead of returning it to implementation.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# --- return record helpers -------------------------------------------------

def open_return(pr: dict | None) -> dict | None:
    """The PR's base return record while the episode is open."""
    rec = (pr or {}).get("base_return")
    if isinstance(rec, dict) and rec.get("verdict") and not rec.get("resolved_at"):
        return rec
    return None


def last_return(pr: dict | None) -> dict | None:
    """The latest base return record, open or resolved (display/history)."""
    rec = (pr or {}).get("base_return")
    return rec if isinstance(rec, dict) and rec.get("verdict") else None


def has_open_return(pr: dict | None) -> bool:
    return open_return(pr) is not None


def return_awaiting(pr: dict | None) -> str | None:
    """The hop an open base return still waits to launch (``impl``)."""
    rec = open_return(pr) or {}
    return rec.get("awaiting") or None


def _signoff_owns(pr: dict) -> bool:
    """Whether sign-off's return currently owns the PR's integration."""
    try:
        from pm_core.signoff import open_return as _signoff_open
        return _signoff_open(pr) is not None
    except Exception:  # pragma: no cover - defensive
        return False


def _stage_label(stage: str, iteration: int | None = None) -> str:
    if stage == STAGE_REVIEW_ITERATION:
        return f"review iteration {iteration}" if iteration else "the next review iteration"
    if stage == STAGE_QA:
        return "starting QA"
    return "starting review"


# --- notes -----------------------------------------------------------------

def _note_text(pr_id: str, record: dict, stage: str,
               iteration: int | None, attempt: int) -> str:
    head = (record.get("head") or "?")[:12]
    base = (record.get("base_sha") or "?")[:12]
    branch = record.get("base_branch") or "base"
    conflicts = list(record.get("conflicts") or [])
    shown = conflicts[:10]
    # ``integration.omitted_path_count`` is the shared rule for "how many of
    # the real paths does this abbreviation hide" (the stored list is already
    # bounded by ``integration.compact``); re-deriving it here drifted from
    # the prompt's rendering of the same record.
    omitted = integration.omitted_path_count(
        conflicts, record.get("conflicts_total"), len(conflicts) - len(shown))
    total = len(shown) + omitted
    more = f" (+{omitted} more)" if omitted else ""
    paths = ", ".join(shown) + more if shown else "(none listed)"
    pointer = integration.integration_pointer(pr_id)
    return (
        f"Base integration conflict before {_stage_label(stage, iteration)}: "
        f"HEAD {head} vs {branch}@{base} conflicts in {total} path(s): "
        f"{paths}. Returned to implementation (attempt {attempt}); "
        f"full record: {pointer}.")


def _add_note(pr: dict, text: str) -> None:
    """Append *text* once (notes are the durable bounce history)."""
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


# --- the return ------------------------------------------------------------

def _new_return(record: dict, stage: str, iteration: int | None,
                attempt: int, *, resume_loop: bool) -> dict:
    # project.yaml is git-tracked, so keep the stored path lists bounded the
    # way ``integration.compact`` bounds ``pr["integration"]`` and record the
    # real length beside each one; the full list stays in integration.json.
    compact = integration.compact(record)
    conflicts = list(compact.get("conflicts") or [])
    overlap = list(compact.get("overlap") or [])
    rec = {
        "verdict": VERDICT_BASE_CONFLICT,
        "stage": stage,
        "iteration": iteration,
        "head": record.get("head"),
        "base_sha": record.get("base_sha"),
        "base_branch": record.get("base_branch"),
        "target_repo": record.get("target_repo"),
        "status": record.get("status"),
        "conflicts": conflicts,
        "conflicts_total": compact.get("conflicts_total", len(conflicts)),
        "overlap": overlap,
        "overlap_total": compact.get("overlap_total", len(overlap)),
        "reason": integration.summary(record),
        "attempt": attempt,
        "ts": _now(),
        "awaiting": "impl",
        "launch_claim": {"hop": "impl", "at": _now()},
        "resolved_at": None,
    }
    if resume_loop:
        rec["resume_loop"] = True
    return rec


def return_to_impl(root: Path, pr_id: str, record: dict, stage: str,
                   *, iteration: int | None = None,
                   resume_loop: bool = False,
                   supersede: bool = False) -> dict | None:
    """Record a conflict return and transition the PR to implementation.

    Returns the written record when this call created/replaced the open
    episode (the caller owns the impl relaunch), or ``None`` when another
    driver already returned the PR (or the PR left the eligible statuses).
    Idempotent: an unchanged unresolved ``(head, base_sha)`` pair never
    produces a second return.

    *supersede* is used by the completion check: the base moved during the
    rework and the new pair still conflicts, so the open episode is updated
    in place (one episode, one claim) instead of being duplicated.
    """
    won: dict = {"rec": None}

    def _apply(d):
        pr = store.get_pr(d, pr_id)
        if not pr:
            return
        status = pr.get("status")
        if status not in ("in_progress", "in_review", "qa"):
            return
        if _signoff_owns(pr):
            return
        existing = open_return(pr)
        pair = (record.get("head"), record.get("base_sha"))
        prev = pr.get("base_return")
        if not isinstance(prev, dict):
            # A hand-edited/corrupt ``base_return`` (a string, a list) must
            # not raise here: the exception would surface as "the PR left the
            # phase" and leave it in review with an unreconcilable base.
            prev = {}
        same_base = bool(prev.get("verdict")) \
            and prev.get("base_sha") == record.get("base_sha")
        attempt = (_int_or(prev.get("attempt"), 0) + 1) if same_base else 1
        if existing is not None:
            old_pair = (existing.get("head"), existing.get("base_sha"))
            if old_pair == pair or not supersede:
                return
            attempt = _int_or(existing.get("attempt"), 1) + 1
        needs_human = attempt > MAX_RETURNS_PER_BASE
        rec = _new_return(record, stage, iteration, attempt,
                          resume_loop=resume_loop)
        if existing is not None and existing.get("launched_at"):
            # The superseded episode's rework session is the one that did the
            # work: keep its relaunch time so the completion guard ("idle
            # evidence must postdate the relaunch") compares against the
            # session that actually ran.  Without it a capped (``needs_human``)
            # record — which launches nothing, so it has no ``launched_at`` of
            # its own — falls back to its creation time, and the previous
            # session's idle turn (always older) can never satisfy the guard:
            # a human who reconciles the base would leave the PR stuck in the
            # TUI/auto-sequence handoff with no way to resume.  A fresh launch
            # overwrites it (``clear_return_awaiting``).
            rec["launched_at"] = existing["launched_at"]
        if existing is not None and existing.get("resume_loop"):
            # The resume intent belongs to the bounce episode, not to whichever
            # driver superseded it.  A one-shot gate (a manual ``d``) passing
            # ``resume_loop=False`` must not cancel the review loop the
            # original return was going to restart once the rework lands.
            rec["resume_loop"] = True
        if needs_human:
            # Stop automatic rework: no launch is awaited (a human must
            # reconcile the base), so no driver keeps relaunching impl.
            rec.pop("launch_claim", None)
            rec["awaiting"] = None
            rec["needs_human"] = True
        if status != "in_progress":
            pr["status"] = "in_progress"
            _stamp(pr, "in_progress")
        pr["base_return"] = rec
        pr["base_check"] = _compact_check(record, stage, CONFLICT,
                                          retryable=False)
        _add_note(pr, _note_text(pr_id, record, stage, iteration, attempt))
        if needs_human:
            _add_note(pr, (
                f"Base integration still conflicts after {attempt - 1} "
                f"returns for {record.get('base_branch') or 'the base'}; "
                "automatic rework stopped — a human must reconcile the base."))
        won["rec"] = rec

    try:
        store.locked_update(root, _apply)
    except Exception as e:
        _log.warning("base_check: return for %s failed: %s", pr_id, e)
        return None
    return won["rec"]


def _status_needs_repair(pr: dict | None) -> bool:
    """Whether a PR with an open return was left in a downstream phase."""
    return (pr is not None and open_return(pr) is not None
            and pr.get("status") in ("in_review", "qa"))


def ensure_impl_status(root: Path, pr_id: str) -> None:
    """Keep a PR with an open return in ``in_progress``.

    Closes the race where a writer had already transitioned the PR to
    ``in_review``/``qa`` when the gate found the open return: the return owns
    the PR, and the impl poll only watches ``in_progress``.
    """
    def _apply(d):
        pr = store.get_pr(d, pr_id)
        if _status_needs_repair(pr):
            pr["status"] = "in_progress"
            _stamp(pr, "in_progress")

    try:
        # Pre-read: the common case is a PR already in_progress, and a
        # ``locked_update`` takes the project.yaml lock and rewrites the whole
        # (large, git-tracked) file for nothing.  This runs from the TUI event
        # loop and from every gate, so the no-op must stay cheap.
        if not _status_needs_repair(store.get_pr(store.load(root), pr_id)):
            return
        store.locked_update(root, _apply)
    except Exception as e:  # pragma: no cover - best effort
        _log.warning("base_check: status fix for %s failed: %s", pr_id, e)


def resolve_return(root: Path, pr_id: str, reason: str = "",
                   *, expect_ts: str | None = None) -> bool:
    """Close an open base return (integration is clean again).

    *expect_ts* names the episode the caller's check was based on.  A check is
    a network round-trip, so another driver can record a **new** conflict
    episode (a base that moved between the two fetches) inside it; closing
    that one would clear a return nobody reconciled and let the caller start a
    reviewer/planner beside the rework it just launched.  With *expect_ts* set,
    only that exact episode (``base_return["ts"]``) is resolved — a superseding
    record is left open for the caller to see.  ``None`` keeps the old
    "resolve whatever is open" behaviour (hand-built records with no ``ts``
    cannot be told apart anyway).
    """
    closed = {"ok": False}

    def _apply(d):
        pr = store.get_pr(d, pr_id)
        rec = open_return(pr)
        if rec is None:
            return
        if expect_ts is not None and rec.get("ts") != expect_ts:
            return  # a newer episode owns the PR now
        rec["resolved_at"] = _now()
        rec["awaiting"] = None
        rec.pop("launch_claim", None)
        if reason:
            rec["resolved_reason"] = reason
        closed["ok"] = True

    try:
        # Pre-read (same rule as ``ensure_impl_status``): the clean path calls
        # this on every review/QA gate, and there is usually no open return to
        # close — a locked_update would take the lock and rewrite the whole
        # file for nothing.  ``clear_return_awaiting`` above already guards
        # its update this way.
        pre = open_return(store.get_pr(store.load(root), pr_id))
        if pre is None:
            return False
        if expect_ts is not None and pre.get("ts") != expect_ts:
            return False
        store.locked_update(root, _apply)
    except Exception as e:
        _log.warning("base_check: resolve for %s failed: %s", pr_id, e)
        return False
    return closed["ok"]


def _claim_held(rec: dict, now: datetime) -> bool:
    """Whether *rec* carries a live impl launch claim another driver holds."""
    claim = rec.get("launch_claim") or {}
    at = _parse_ts(claim.get("at"))
    age = (now - at).total_seconds() if at else None
    return (claim.get("hop") == "impl" and age is not None
            and 0 <= age < RETURN_LAUNCH_CLAIM_SECONDS)


def _claimable(rec: dict | None, now: datetime) -> bool:
    """Whether the ``awaiting`` impl launch of *rec* may be claimed now."""
    if not rec or rec.get("awaiting") != "impl" or rec.get("needs_human"):
        return False
    return not _claim_held(rec, now)


def claim_impl_launch(root: Path, pr_id: str) -> bool:
    """Take the one impl relaunch for an ``awaiting`` base return.

    Mirrors :func:`pm_core.signoff.claim_return_launch`: the driver that
    created the return already holds the claim; this is the catch-up path
    (restart, an ``awaiting`` tick).  A claim whose launcher died expires.
    """
    now = datetime.now(timezone.utc)
    won = {"ok": False}

    def _apply(d):
        pr = store.get_pr(d, pr_id)
        rec = open_return(pr)
        if not _claimable(rec, now):
            return
        rec["launch_claim"] = {"hop": "impl", "at": now.isoformat()}
        won["ok"] = True

    try:
        # Pre-read (same rule as ``resolve_return`` / ``ensure_impl_status``):
        # the TUI catch-up retries this every ``BASE_LAUNCH_RETRY_SECONDS``
        # while a return awaits its launch, and a handshake that keeps failing
        # (a pending spec, a broken workdir) awaits for a long time.  A
        # ``locked_update`` takes the global lock and rewrites the whole large,
        # git-tracked project.yaml even when ``_apply`` changes nothing, so the
        # no-op must stay cheap.
        pre = open_return(store.get_pr(store.load(root), pr_id))
        if not _claimable(pre, now):
            return False
        store.locked_update(root, _apply)
    except Exception as e:
        _log.warning("base_check: claim for %s failed: %s", pr_id, e)
        return False
    return won["ok"]


def clear_return_awaiting(root: Path, pr_id: str) -> None:
    """The impl session launched: stop forcing a relaunch.

    ``launched_at`` marks the moment the rework session started: the
    completion check only trusts idle evidence from after it, so the killed
    session's last ``idle_prompt`` (still visible through a stale transcript
    symlink) can never pass for the new session's turn.
    """
    def _apply(d):
        pr = store.get_pr(d, pr_id)
        rec = open_return(pr)
        if rec and rec.get("awaiting") == "impl":
            rec["awaiting"] = None
            rec.pop("launch_claim", None)
            # The failed attempt's error is history now that a launch worked;
            # leaving it on the record makes `pm pr show` report a stale
            # failure for the rest of the episode.
            rec.pop("apply_error", None)
            rec["launched_at"] = _now()

    try:
        data = store.load(root)
        rec = open_return(store.get_pr(data, pr_id))
        if not rec or rec.get("awaiting") != "impl":
            return
        store.locked_update(root, _apply)
    except Exception as e:
        _log.warning("base_check: clear awaiting for %s failed: %s", pr_id, e)


def release_impl_claim(root: Path, pr_id: str, error: str) -> None:
    """A launch attempt failed: let the next driver retry, keep ``awaiting``."""
    def _apply(d):
        pr = store.get_pr(d, pr_id)
        rec = open_return(pr)
        if not rec:
            return
        rec.pop("launch_claim", None)
        rec["apply_error"] = error

    try:
        store.locked_update(root, _apply)
    except Exception as e:
        _log.warning("base_check: release claim for %s failed: %s", pr_id, e)


def launch_impl(root: Path, pr_id: str, transcript_dir: str | Path | None) -> tuple[bool, str]:
    """Relaunch the implementation session for a returned PR (one owner).

    ``pm pr start --fresh --background`` reuses the existing workdir (a
    dirty tree is left alone), kills an idle/stale impl window, resolves the
    PR's model override and honors ``spec_pending`` (a pending spec makes
    the launch fail; the return stays awaiting for a later retry).  The
    transcript keeps the TUI/CLI idle tracking pointed at the new session.

    Refused without a live pm tmux session: ``pm pr start`` falls back to a
    foreground ``claude`` in that case (no window, no transcript symlink) and
    returns 0, so this call would report a launch nothing can track while
    ``clear_return_awaiting`` marked the handshake satisfied — the rework
    handoff waits on idle evidence that can never arrive.  Keep ``awaiting``
    for the next driver (a TUI/CLI pass with a session) instead.
    """
    from pm_core import tmux as tmux_mod
    from pm_core.cli.helpers import _get_pm_session

    try:
        session = _get_pm_session()
        has_session = bool(session) and tmux_mod.session_exists(session)
    except Exception:  # pragma: no cover - best effort
        has_session = False
    if not has_session:
        detail = "no pm tmux session to relaunch implementation into"
        release_impl_claim(root, pr_id, detail)
        _log.info("base_check: impl relaunch for %s deferred: %s", pr_id, detail)
        return False, detail
    tdir = Path(transcript_dir) if transcript_dir else (
        root / "transcripts" / f"manual-{secrets.token_hex(3)}")
    try:
        tdir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        release_impl_claim(root, pr_id, f"transcript dir: {e}")
        return False, str(e)
    cmd = [sys.executable, "-m", "pm_core.wrapper",
           "pr", "start", "--fresh", "--background",
           "--transcript", str(tdir / f"impl-{pr_id}.jsonl"), pr_id]
    _log.info("base_check: relaunching impl for %s", pr_id)
    try:
        r = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True,
                           timeout=300)
    except (OSError, subprocess.SubprocessError) as e:
        release_impl_claim(root, pr_id, str(e))
        return False, str(e)
    if r.returncode != 0:
        detail = ((r.stderr or "").strip() or (r.stdout or "").strip())[:500]
        release_impl_claim(root, pr_id, detail or f"rc={r.returncode}")
        _log.warning("base_check: impl relaunch for %s failed: %s",
                     pr_id, detail)
        return False, detail or f"pm pr start exited {r.returncode}"
    # pr_start clears awaiting on its successful launch path; make it
    # unconditional so a fast-path return cannot strand the handshake.
    clear_return_awaiting(root, pr_id)
    share_impl_transcript(root, pr_id, tdir / f"impl-{pr_id}.jsonl")
    return True, ""


def impl_transcript_links(root: Path | str, pr_id: str) -> list[Path]:
    """Every driver's ``impl-<pr>.jsonl`` link under ``transcripts/``.

    Every pm transcript dir is ``transcripts/<run>/`` (TUI run dir) or
    ``transcripts/auto-sequence/<pr>/`` (CLI driver).  Scan those two depths
    explicitly: no unbounded recursion (and no symlink-loop risk), and
    ``glob`` matches a link whose target is gone where ``rglob`` (which only
    yields files) would skip it.

    Shared by :func:`share_impl_transcript` (re-point them all) and the TUI's
    restart catch-up (watch the newest one), so both drivers agree on where a
    PR's implementation session may be tracked from.
    """
    base = Path(root) / "transcripts"
    if not base.is_dir():
        return []
    name = f"impl-{pr_id}.jsonl"
    links: list[Path] = []
    for pattern in (f"*/{name}", f"*/*/{name}"):
        try:
            links.extend(Path(p) for p in glob.glob(str(base / pattern)))
        except OSError:  # pragma: no cover - best effort
            continue
    return links


def share_impl_transcript(root: Path, pr_id: str,
                          transcript: str | Path | None) -> None:
    """Point every driver's ``impl-<pr>.jsonl`` at the session just launched.

    A relaunch writes its transcript symlink into one directory.  Other
    drivers that were watching the *killed* session (the TUI run dir, the
    auto-sequence dir) keep their own symlink, so they would read that
    session's last ``idle_prompt`` as if the rework session were idle — and
    never see the new session's events at all.  Refreshing them keeps the
    relaunch trackable by whichever driver resumes the handoff.

    ``pm pr start`` (the single implementation launcher) and
    :func:`launch_impl` call this, so a relaunch started from any driver
    (TUI auto-start catch-up, a manual ``pm pr start``, the review gate)
    stays trackable from every transcript dir.  Best effort: never raises.
    """
    if not transcript:
        return
    transcript = Path(transcript)
    try:
        target = os.readlink(transcript)
        if not os.path.isabs(target):
            # A relative link target resolves against *this* link's directory;
            # re-created under another driver's dir it would dangle.  Store
            # the absolute target so every refreshed link resolves.
            target = os.path.normpath(
                os.path.join(os.path.dirname(os.path.abspath(transcript)),
                             target))
    except OSError:
        # A direct JSONL path (not a symlink) is the target itself.
        if not transcript.exists():
            return
        target = os.path.abspath(transcript)
    for p in impl_transcript_links(root, pr_id):
        # Compare resolved paths as well: a caller may spell the transcript
        # relatively (``pm pr start --transcript transcripts/run/impl-x.jsonl``),
        # and renaming the transcript itself to ``.finalized`` would move the
        # evidence the caller just handed us.
        if p == transcript or os.path.realpath(p) == os.path.realpath(transcript):
            continue
        try:
            if p.is_symlink():
                if os.readlink(p) == target:
                    continue
                p.unlink()
            elif p.exists():
                # ``finalize_transcript`` turns a finished session's link into
                # a real file (a copy that survives Claude pruning) when a run
                # is finalized.  That copy is evidence, not a stale link: keep
                # it beside the refreshed link instead of deleting it.  The
                # suffix falls outside the ``impl-<pr>.jsonl`` pattern, so a
                # later pass never picks it up again.
                kept = p.with_name(p.name + ".finalized")
                n = 1
                while kept.exists() or kept.is_symlink():
                    kept = p.with_name(f"{p.name}.finalized.{n}")
                    n += 1
                p.rename(kept)
                _log.info("base_check: kept finalized transcript %s as %s",
                          p, kept)
            p.symlink_to(target)
        except OSError as e:  # pragma: no cover - best effort
            _log.debug("base_check: refreshing %s failed: %s", p, e)


# --- the check -------------------------------------------------------------

def _compact_check(record: dict, stage: str, decision: str,
                   *, retryable: bool) -> dict:
    out = {
        "stage": stage,
        "decision": decision,
        "status": record.get("status"),
        "head": record.get("head"),
        "base_sha": record.get("base_sha"),
        "base_branch": record.get("base_branch"),
        "checked_at": record.get("checked_at") or _now(),
        "retryable": bool(retryable),
    }
    if record.get("error"):
        out["error"] = record["error"]
    return out


def _check_record(pr: dict | None) -> dict:
    """``pr["base_check"]`` as a dict.

    ``project.yaml`` is git-tracked and hand-editable: a ``base_check`` that
    is a string or a list (or a null) must read as "no record" rather than
    raise.  An exception here disables the gate (``gate`` catches it and
    fails open) and leaves ``impl_completion`` reporting "completion check
    failed" forever — the PR would sit with an open return nobody can
    resolve.  Same class of corruption ``base_return`` is already guarded
    against (``open_return``/``last_return``).
    """
    rec = (pr or {}).get("base_check")
    return rec if isinstance(rec, dict) else {}


def _retry_after(record: dict, pr: dict) -> str:
    prev = _check_record(pr)
    prev_attempts = 1
    if (prev.get("retryable") and prev.get("head") == record.get("head")):
        try:
            prev_attempts = max(1, int(prev.get("attempts") or 1) + 1)
        except (TypeError, ValueError):
            prev_attempts = 2
    # ``attempts`` is read from the git-tracked project.yaml, so a hand-edited
    # value (10**7) makes ``2 ** n`` an int too large to multiply into a float
    # (OverflowError — the failure is then never recorded, so ``_retry_open``
    # keeps reading the stale record and the backoff never advances) and a
    # much larger one allocates for a long time before that.  The delay
    # saturates at RETRY_MAX_SECONDS by attempt 5, so clamp the exponent
    # before the shift rather than exponentiating an unbounded counter.
    exp = max(0, min(prev_attempts - 1, 8))
    delay = min(RETRY_MAX_SECONDS, RETRY_MIN_SECONDS * (2 ** exp))
    return datetime.fromtimestamp(time.time() + delay, timezone.utc).isoformat()


def _retry_open(pr: dict, head: str | None) -> bool:
    """Whether a recorded retryable failure still suppresses a re-fetch."""
    rec = _check_record(pr)
    if not rec.get("retryable"):
        return False
    if head and rec.get("head") and rec.get("head") != head:
        return False  # HEAD moved: the pair changed, re-check now
    at = _parse_ts(rec.get("retry_after"))
    return bool(at and datetime.now(timezone.utc) < at)


def _record_error(root: Path, pr_id: str, record: dict, stage: str) -> None:
    """Record a retryable probe failure (no bounce, no approval)."""
    def _apply(d):
        p = store.get_pr(d, pr_id)
        if p is None:
            return
        compact = _compact_check(record, stage, RETRY, retryable=True)
        prev = _check_record(p)
        try:
            compact["attempts"] = (int(prev.get("attempts") or 0) + 1
                                   if prev.get("head") == record.get("head")
                                   else 1)
        except (TypeError, ValueError):
            compact["attempts"] = 1
        compact["retry_after"] = _retry_after(record, p)
        p["base_check"] = compact

    try:
        store.locked_update(root, _apply)
    except Exception as e:  # pragma: no cover - best effort
        _log.warning("base_check: recording error for %s failed: %s", pr_id, e)


def evaluate(root: Path, pr_id: str, pr: dict, *,
             data: dict | None = None) -> dict:
    """Run the integration check and record it; never raises.

    Returns the full integration record (``status`` is ``error`` when the
    check could not run).
    """
    try:
        return integration.check_integration(root, pr_id, data=data)
    except Exception as e:
        _log.warning("base_check: integration check for %s failed: %s",
                     pr_id, e)
        return {"status": integration.ERROR, "error": str(e),
                "checked_at": _now(), "head": head_sha(pr.get("workdir")),
                "conflicts": [], "overlap": []}


def gate(root: Path, pr_id: str, stage: str, *,
         data: dict | None = None, iteration: int | None = None,
         transcript: str | Path | None = None,
         resume_loop: bool = False) -> GateResult:
    """Pre-flight integration gate for a writer about to start.

    Never raises.  On a conflict (or an already-open return) it does not
    launch the downstream writer; when it creates the return it also
    relaunches implementation (one owner).
    """
    try:
        if data is None:
            data = store.load(root)
        pr = store.get_pr(data, pr_id)
        if pr is None:
            return GateResult(SKIPPED, stage, reason=f"PR {pr_id} not found")

        status = pr.get("status")
        if _signoff_owns(pr):
            return GateResult(SKIPPED, stage, reason="sign-off owns integration")

        # An open return blocks every downstream writer.  The gate may still
        # SELF-HEAL (a stale callback, a manual `d` after a hand
        # reconciliation): it re-checks, and only proceeds when no rework
        # launch is pending and the workdir is quiescent — so an
        # implementation that is still editing cannot race a review/QA
        # writer.  A capped (``needs_human``) return is re-checked too, so a
        # human who reconciled the base resumes instead of being stuck.
        open_rec = open_return(pr)
        workdir = pr.get("workdir")
        head = head_sha(workdir)

        def _wait(reason: str, episode: dict | None = None) -> GateResult:
            # ``episode`` overrides the pre-check snapshot: a gate that lost
            # the return race (another driver recorded it inside this gate's
            # fetch) must report the episode that actually landed, not the
            # empty snapshot this call started from.
            ep = open_rec if episode is None else episode
            return GateResult(
                WAIT, stage, status=(ep or {}).get("status"),
                head=(ep or {}).get("head"), base_sha=(ep or {}).get("base_sha"),
                conflicts=list((ep or {}).get("conflicts") or []),
                already_returned=True, reason=reason)

        if stage == STAGE_QA:
            if status != "qa":
                # A raced transition away from qa while a return is open
                # must not start QA against the rework.
                if open_rec is not None:
                    return _wait(f"status is {status}; base rework pending")
                return GateResult(SKIPPED, stage,
                                  reason=f"status is {status}, not qa")
        elif status not in ("in_progress", "in_review"):
            return GateResult(SKIPPED, stage, reason=f"status is {status}")

        if open_rec is not None:
            if open_rec.get("awaiting") == "impl":
                return _wait("returned to implementation; rework has not launched")
            if not head:
                return _wait("returned to implementation; no readable HEAD")
            if git_op_in_progress(workdir or ""):
                return _wait("returned to implementation; a git operation "
                             "is still in progress")
            if tracked_dirty(workdir or ""):
                return _wait("returned to implementation; uncommitted edits "
                             "remain")
            if _retry_open(pr, head):
                return _wait("returned to implementation; retrying the base "
                             "check after a probe failure")

        if not head:
            record = {"status": integration.ERROR,
                      "error": "PR workdir has no readable HEAD",
                      "checked_at": _now(), "head": None,
                      "conflicts": [], "overlap": []}
            _record_error(root, pr_id, record, stage)
            return GateResult(RETRY, stage, status=integration.ERROR,
                              error=record["error"], record=record,
                              reason=record["error"])
        if open_rec is None and _retry_open(pr, head):
            rec = _check_record(pr)
            return GateResult(
                RETRY, stage, status=rec.get("status"), head=head,
                error=rec.get("error"),
                reason=(f"recent base check failed ({rec.get('error') or 'unknown'}); "
                        f"retrying after {rec.get('retry_after')}"))

        record = evaluate(root, pr_id, pr, data=data)
        record.setdefault("head", head)
        st = record.get("status")
        if st == integration.ERROR:
            _record_error(root, pr_id, record, stage)
            if open_rec is not None:
                return _wait(f"returned to implementation; base check failed "
                             f"(retryable): {record.get('error') or 'unknown'}")
            return GateResult(RETRY, stage, status=st, head=head,
                              error=record.get("error"), record=record,
                              reason=record.get("error") or "base check failed")

        if st == integration.CONFLICT:
            pair = (record.get("head"), record.get("base_sha"))
            if open_rec is not None and open_rec.get("needs_human"):
                # The automatic loop is capped: never write another episode
                # (or spam a note) while it still conflicts.  The clean path
                # below is still reachable — a human who reconciled the base
                # resumes the phase instead of leaving the PR stuck forever.
                return _wait("base conflict still needs a human decision")
            if open_rec is not None and \
                    pair == (open_rec.get("head"), open_rec.get("base_sha")):
                # The unchanged unresolved pair never bounces again.
                return _wait("still conflicts with the same HEAD/base pair; "
                             "rework pending")
            rec = return_to_impl(
                root, pr_id, record, stage, iteration=iteration,
                resume_loop=resume_loop, supersede=open_rec is not None)
            if rec is None:
                # Either another driver won the return or the PR left the
                # phase between the check and the write.  Refuse the writer
                # either way, but say which so the log is not misleading.
                try:
                    now_pr = store.get_pr(store.load(root), pr_id)
                except Exception:  # pragma: no cover - best effort
                    now_pr = None
                landed = open_return(now_pr)
                if landed is not None:
                    return _wait("base integration return already recorded",
                                 landed)
                return _wait("the PR left the review/QA phase before the "
                             "return was recorded")
            launched = False
            if not rec.get("needs_human"):
                launched, _detail = launch_impl(
                    root, pr_id, _transcript_dir(transcript, root))
            return GateResult(
                CONFLICT, stage, status=st, head=record.get("head"),
                base_sha=record.get("base_sha"),
                conflicts=list(record.get("conflicts") or []),
                returned=True, launched=launched, record=record,
                reason=integration.summary(record))

        # clean / up_to_date / in_base: continue the intended phase.
        # Resolve only the episode this check was based on: the fetch above is
        # a network round-trip, and another driver's check can record a *new*
        # conflict inside it (a base that moved between the two fetches).
        # Closing that one would clear a return nobody reconciled, and the
        # caller would then start a reviewer/planner beside the rework the
        # return just launched (the caller's post-gate re-read only sees an
        # *open* return).
        if open_rec is not None:
            resolve_return(root, pr_id, reason=integration.summary(record),
                           expect_ts=open_rec.get("ts"))
        # Re-read: whatever is still open now was recorded inside this check
        # (or superseded the episode we based on) and owns the PR.  Without
        # this the gate would report PROCEED — and record a clean decision —
        # while the return it was about to be blocked by is live.
        still_open = open_return(store.get_pr(store.load(root), pr_id))
        if still_open is not None:
            return GateResult(
                WAIT, stage, status=still_open.get("status"),
                head=still_open.get("head"),
                base_sha=still_open.get("base_sha"),
                conflicts=list(still_open.get("conflicts") or []),
                already_returned=True,
                reason="a base integration return was recorded during the "
                       "base check")
        _record_decision(root, pr_id, record, stage, PROCEED)
        return GateResult(PROCEED, stage, status=st,
                          head=record.get("head"),
                          base_sha=record.get("base_sha"),
                          conflicts=list(record.get("conflicts") or []),
                          record=record, reason=integration.summary(record))
    except Exception as e:  # the gate must never block a caller
        _log.exception("base_check: gate for %s failed", pr_id)
        return GateResult(RETRY, stage, error=str(e),
                          reason=f"base check failed: {e}")


def _record_decision(root: Path, pr_id: str, record: dict, stage: str,
                     decision: str) -> None:
    def _apply(d):
        p = store.get_pr(d, pr_id)
        if p is not None:
            p["base_check"] = _compact_check(record, stage, decision,
                                             retryable=False)
    try:
        store.locked_update(root, _apply)
    except Exception:  # pragma: no cover - best effort
        pass


def _transcript_dir(transcript: str | Path | None, root: Path) -> Path:
    if transcript:
        return Path(transcript).parent
    return root / "transcripts" / f"manual-{secrets.token_hex(3)}"


# --- implementation completion --------------------------------------------

def impl_completion(root: Path, pr_id: str, pr: dict | None = None,
                    *, idle_since: float | None = None,
                    transcript_dir: str | Path | None = None) -> CompletionResult:
    """Whether a returned PR's implementation genuinely finished.

    An idle notification alone is not completion.  Requires: the fresh
    session launched (``awaiting`` cleared), a readable idle timestamp
    (``idle_since`` — no timestamp is no evidence) at least
    :data:`IDLE_SETTLE_SECONDS` old and later than the relaunch, no
    in-progress merge/rebase/cherry-pick, no uncommitted tracked edits, and
    a fresh integration check that is no longer a conflict.  A moved base
    that still conflicts produces one new return (bounded); a clean
    integration resolves the episode.
    """
    try:
        data = store.load(root)
        fresh = store.get_pr(data, pr_id)
        if fresh is not None:
            pr = fresh
        rec = open_return(pr)
        if rec is None:
            # ``base_return`` may be null — or, in a hand-edited/corrupt
            # project.yaml, a string or a list.  Read every non-dict as "no
            # record": ``open_return`` already does, and the ``resume_loop``
            # read here must not raise either.  An exception surfaces through
            # the outer guard as "completion check failed" on every poll,
            # which is the permanently stuck handoff that guard exists to
            # prevent.
            last = (pr or {}).get("base_return")
            if not isinstance(last, dict):
                last = {}
            return CompletionResult(True, "no open base return",
                                    bool(last.get("resume_loop")))
        resume_loop = bool(rec.get("resume_loop"))
        if rec.get("awaiting") == "impl":
            return CompletionResult(False, "rework session has not launched")
        workdir = pr.get("workdir")
        if not workdir or not Path(workdir).is_dir():
            return CompletionResult(False, "no PR workdir")
        if idle_since is None:
            # No idle turn was observed, so there is nothing that says the
            # rework session's work is finished.  Treating a missing
            # timestamp as satisfied would skip both the settle window and
            # the ``launched_at`` guard below — an idle notification alone
            # never qualifies as completion.
            return CompletionResult(
                False, "no idle evidence from the rework session yet")
        launched = _parse_ts(rec.get("launched_at") or rec.get("ts"))
        if launched is not None and float(idle_since) < launched.timestamp():
            # The idle event predates the relaunch: it belongs to the session
            # this return killed (a stale transcript symlink still points at
            # it), so it says nothing about the rework.  Without this an
            # idle notification from before the rework qualifies as
            # completion and a reviewer could start beside the new writer.
            return CompletionResult(
                False, "no idle evidence from the rework session yet")
        if time.time() - float(idle_since) < IDLE_SETTLE_SECONDS:
            return CompletionResult(
                False, "implementation just went idle; letting it settle")
        op = git_op_in_progress(workdir)
        if op:
            return CompletionResult(False, f"{op} still in progress")
        if tracked_dirty(workdir):
            return CompletionResult(False, "uncommitted edits remain")

        head = head_sha(workdir)
        if not head:
            return CompletionResult(False, "PR workdir has no HEAD")
        if _retry_open(pr, head):
            return CompletionResult(
                False, "recent base check failed; retrying after the backoff")
        try:
            target_repo, base_branch = integration.target_for(
                data, pr, root)
        except Exception:
            target_repo, base_branch = "", rec.get("base_branch") or ""
        base_now = None
        if target_repo and base_branch:
            base_now = integration.remote_ref(
                workdir, target_repo, _base_ref(base_branch))
        if base_now and head == rec.get("head") \
                and base_now == rec.get("base_sha"):
            return CompletionResult(
                False, "HEAD and base unchanged since the return")

        record = evaluate(root, pr_id, pr, data=data)
        st = record.get("status")
        if st == integration.ERROR:
            _record_error(root, pr_id, record,
                          rec.get("stage") or STAGE_REVIEW)
            return CompletionResult(
                False, f"base check failed (retryable): "
                       f"{record.get('error') or 'unknown'}")
        if st == integration.CONFLICT:
            pair = (record.get("head"), record.get("base_sha"))
            old_pair = (rec.get("head"), rec.get("base_sha"))
            if pair == old_pair:
                return CompletionResult(
                    False, "still conflicts with the same HEAD/base pair")
            if rec.get("needs_human"):
                # The cap already fired: no new episode, no note spam.  A
                # human who reconciles the base reaches the clean path below.
                return CompletionResult(
                    False, "base conflict still needs a human decision")
            new = return_to_impl(
                root, pr_id, record, rec.get("stage") or STAGE_REVIEW,
                iteration=rec.get("iteration"), resume_loop=resume_loop,
                supersede=True)
            if new is not None and not new.get("needs_human"):
                launch_impl(root, pr_id,
                            transcript_dir or _default_transcript_dir(root, pr_id))
                return CompletionResult(
                    False, "still conflicts with the moved base; returned "
                           "again")
            return CompletionResult(
                False, "still conflicts with the moved base")

        # Resolve only the episode this check was based on, then confirm it is
        # really gone: the integration check is a network round-trip, so
        # another driver can record a *new* conflict inside it (a base that
        # moved between the two fetches).  Closing that one would let this
        # handoff start a reviewer beside the rework the return just launched.
        resolve_return(root, pr_id, reason=integration.summary(record),
                       expect_ts=rec.get("ts"))
        if open_return(store.get_pr(store.load(root), pr_id)) is not None:
            return CompletionResult(
                False, "a base integration return was recorded during the "
                       "check")
        # Record the clean verdict like the writer-launch gate does: without
        # it the PR keeps the last *failed* (retryable) ``base_check`` record
        # after a successful completion, so ``_retry_open`` keeps suppressing
        # the next gate's fetch until that record's backoff expires, and a
        # reader of the stored record (project.yaml / ``pm autostart status``
        # diagnostics) still sees a probe failure for an episode that is over.
        _record_decision(root, pr_id, record,
                         rec.get("stage") or STAGE_REVIEW, PROCEED)
        return CompletionResult(True, integration.summary(record), resume_loop)
    except Exception as e:
        _log.exception("base_check: completion check for %s failed", pr_id)
        return CompletionResult(False, f"completion check failed: {e}")


def _default_transcript_dir(root: Path, pr_id: str) -> Path:
    """Deterministic auto-sequence transcript dir (CLI-driven PRs).

    TUI callers pass their own run dir so the idle tracker keeps watching
    the relaunched session; this fallback matches
    ``cli.pr._auto_seq_transcript_dir``.
    """
    return root / "transcripts" / "auto-sequence" / pr_id


# --- prompt / display ------------------------------------------------------

def format_return(pr: dict) -> str:
    """Prompt block for a PR returned to implementation for a base conflict.

    Empty when there is no open return.  Mirrors
    :func:`pm_core.signoff.format_signoff_return`'s role: the operative
    handoff instructions for the step the PR was routed to.
    """
    rec = open_return(pr)
    if not rec:
        return ""
    pr_id = pr.get("id", "???")
    head = (rec.get("head") or "?")[:12]
    base_sha = (rec.get("base_sha") or "?")[:12]
    branch = rec.get("base_branch") or "the base"
    target = rec.get("target_repo") or "the target repository"
    lines = [
        "\n## Returned to implementation: base integration conflict",
        "",
        f"Before {_stage_label(rec.get('stage') or STAGE_REVIEW, rec.get('iteration'))}, "
        f"pm checked HEAD `{head}` against the latest `{branch}` "
        f"(`{base_sha}`) from `{target}`: **conflict**.",
    ]
    conflicts = list(rec.get("conflicts") or [])
    if conflicts:
        shown_paths = conflicts[:10]
        # Same shared abbreviation rule as the note (see _note_text): the
        # stored list is already bounded, so counting only what this render
        # drops would under-report a large conflict set.
        omitted = integration.omitted_path_count(
            conflicts, rec.get("conflicts_total"),
            len(conflicts) - len(shown_paths))
        shown = ", ".join(f"`{c}`" for c in shown_paths)
        more = f" (+{omitted} more)" if omitted else ""
        lines.append(f"Conflicting paths: {shown}{more}")
        lines.append(
            f"Full record: {integration.integration_pointer(pr_id)}")
    if rec.get("needs_human"):
        lines.append(
            "\nAutomatic rework has been stopped: this conflict persisted "
            "across repeated returns. A human must reconcile the base "
            "before review/QA resumes.")
    lines.append(
        f"\nReconcile it in this branch: fetch the latest `{branch}` from "
        f"`{target}` (`git fetch <target> {branch}`), merge it "
        f"(`git merge {base_sha}` or `git merge FETCH_HEAD`), resolve the "
        "conflicts preserving both sides' intent, run the tests, commit and "
        "push the PR branch. Never push or merge into the base branch "
        "yourself — the merge step publishes only a freshly signed-off "
        "candidate.")
    lines.append(
        "When this step completes, pm re-checks the base and only then "
        "resumes review/QA.")
    return "\n".join(lines) + "\n"
