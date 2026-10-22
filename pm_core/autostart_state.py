"""Shared auto-start target/status helpers (no TUI imports).

Auto-start is owned by the TUI's session scheduler (``pm_core.tui.auto_start``).
This module holds the pure pieces that the scheduler, the CLI
(``pm autostart``), the runs popup and the watcher prompt all share:

- dependency closures over an explicit *collection* of targets
  (:func:`closure`, :func:`managed_ids`, :func:`needed_by`);
- target records and breadcrumb (de)serialisation, including migration of
  the legacy single-``target`` breadcrumb (:func:`targets_from_breadcrumb`);
- the single structured status builder (:func:`build_status`, schema
  ``pm.autostart.status/1``) and a row flattener (:func:`status_rows`) used by
  both the CLI text output and the TUI popup.

``build_status`` is a pure function of an *inputs* dict gathered by the TUI
(``auto_start.collect_status_inputs``) from live scheduler, worker, tmux and
recorded-verdict state — it never infers "running" or "ready to merge" from a
registry status alone.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

SCHEMA = "pm.autostart.status/1"

POLICY_STOP = "stop_before_merge"
POLICY_AUTO = "auto_merge"
# Target-level: hold the target *and its whole dependency closure* for a
# manual merge.  Stored on the target record (``WAIT_KEY``), never copied
# into the explicit per-PR stop set, so removing the target or changing its
# policy releases exactly the holds it caused.
POLICY_WAIT = "wait_for_merge"
WAIT_KEY = "wait_for_merge"
POLICIES = (POLICY_STOP, POLICY_AUTO, POLICY_WAIT)
# The command-line flag selecting each policy (CLI + command bar).
POLICY_FLAGS = {POLICY_STOP: "--stop-before-merge",
                POLICY_AUTO: "--auto-merge",
                POLICY_WAIT: "--wait-for-merge"}

PHASES = ("pending", "implementation", "review", "qa", "sign_off", "merge", "done")
STATES = ("queued", "running", "waiting", "paused", "failed", "completed")

_STATUS_PHASE = {
    "pending": "pending",
    "in_progress": "implementation",
    "in_review": "review",
    "qa": "qa",
    "sign_off": "sign_off",
    "merged": "done",
    "closed": "done",
}

TERMINAL_STATUSES = ("merged", "closed")

# ``pm_home()`` subdirectory where the TUI writes ``pm autostart`` replies
# (``<reply_id>.json``) and the CLI polls for them.
REPLY_DIR = "autostart-replies"

# Review-loop verdicts that mean "review passed" (mirrors review_loop).
_REVIEW_PASS = ("PASS", "PASS_WITH_SUGGESTIONS")


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Dependency closures
# ---------------------------------------------------------------------------

def transitive_deps(prs: list[dict], target_id: str) -> set[str]:
    """Return the set of all PR IDs that ``target_id`` transitively depends on."""
    pr_map = {pr["id"]: pr for pr in prs}
    deps: set[str] = set()
    stack = [target_id]
    while stack:
        pr_id = stack.pop()
        pr = pr_map.get(pr_id)
        if not pr:
            continue
        for dep_id in pr.get("depends_on") or []:
            if dep_id not in deps:
                deps.add(dep_id)
                stack.append(dep_id)
    return deps


def closure(prs: list[dict], target_id: str) -> set[str]:
    """``target_id`` plus everything it transitively depends on."""
    return transitive_deps(prs, target_id) | {target_id}


def managed_ids(prs: list[dict], targets) -> set[str]:
    """Union of the dependency closures of every target."""
    out: set[str] = set()
    for t in targets:
        out |= closure(prs, t)
    return out


def needed_by(prs: list[dict], targets) -> dict[str, list[str]]:
    """Map each managed PR id to the (ordered) targets whose closure has it."""
    out: dict[str, list[str]] = {}
    for t in targets:
        for pr_id in sorted(closure(prs, t)):
            out.setdefault(pr_id, []).append(t)
    return out


# ---------------------------------------------------------------------------
# Merge holds (the single policy path)
# ---------------------------------------------------------------------------

def is_wait_target(record) -> bool:
    return isinstance(record, dict) and bool(record.get(WAIT_KEY))


def target_policy(pr_id: str, record, stop) -> str:
    """A target's own configured policy (not what holds it)."""
    if is_wait_target(record):
        return POLICY_WAIT
    return POLICY_STOP if pr_id in (stop or ()) else POLICY_AUTO


def merge_holds(prs: list[dict], targets: dict, stop) -> dict[str, dict]:
    """Every held PR → ``{"explicit": bool, "targets": [wait target ids]}``.

    A PR is held for a manual merge when it carries an explicit per-PR mark
    (*stop*, the ``_stop_before_merge`` set) or lies in the dependency
    closure (target included) of an active ``wait_for_merge`` target.
    Derived on every call from the current graph, so newly added
    dependencies are held and removed targets/edges release theirs.
    Merged/closed closure members are not held (nothing left to merge, and
    they would otherwise show up as "released" when the target goes).
    """
    status = {pr["id"]: pr.get("status") for pr in prs}
    holds: dict[str, dict] = {}
    for pr_id in stop or ():
        holds[pr_id] = {"explicit": True, "targets": []}
    for t, rec in (targets or {}).items():
        if not is_wait_target(rec):
            continue
        for pr_id in sorted(closure(prs, t)):
            if status.get(pr_id) in TERMINAL_STATUSES:
                continue
            h = holds.setdefault(pr_id, {"explicit": False, "targets": []})
            h["targets"].append(t)
    return holds


def effective_policy(pr_id: str, holds: dict) -> str:
    """Merge policy actually applied to *pr_id* (an explicit stop names it
    first; a wait-target hold next; otherwise auto-merge)."""
    h = holds.get(pr_id)
    if not h:
        return POLICY_AUTO
    return POLICY_STOP if h.get("explicit") else POLICY_WAIT


def held_by_text(h: dict | None) -> str:
    """Short cause of a hold, e.g. ``"stop-before-merge"`` or
    ``"wait-for-merge ← pr-final"``."""
    if not h:
        return ""
    parts = []
    if h.get("explicit"):
        parts.append("stop-before-merge")
    if h.get("targets"):
        parts.append("wait-for-merge ← " + ", ".join(h["targets"]))
    return "; ".join(parts)


# ---------------------------------------------------------------------------
# Target records + breadcrumb
# ---------------------------------------------------------------------------

def make_target_record(source: str, added_at: str | None = None) -> dict:
    return {"added_at": added_at or now_iso(), "source": source}


def targets_to_breadcrumb(targets: dict[str, dict]) -> list[dict]:
    """Serialise an ordered ``{pr_id: record}`` map for the breadcrumb."""
    return [{"pr_id": pr_id, **(rec or {})} for pr_id, rec in targets.items()]


def targets_from_breadcrumb(data: dict) -> tuple[dict[str, dict], bool, bool]:
    """Read ``(targets, all_mode, migrated)`` from a breadcrumb dict.

    Current format: ``targets`` (list of records) + ``all_mode``.
    Legacy format (single-target TUI): ``target: X`` → ``[X]``; legacy
    ``auto_start`` with no target was the explicit "all ready PRs" mode and
    maps to ``all_mode``.  *migrated* is True when the legacy shape was read.
    """
    targets: dict[str, dict] = {}
    raw = data.get("targets")
    if isinstance(raw, list):
        for entry in raw:
            if isinstance(entry, str):
                targets.setdefault(entry, make_target_record("breadcrumb"))
            elif isinstance(entry, dict) and entry.get("pr_id"):
                rec = {k: v for k, v in entry.items() if k != "pr_id"}
                rec.setdefault("added_at", now_iso())
                rec.setdefault("source", "breadcrumb")
                targets.setdefault(entry["pr_id"], rec)
        return targets, bool(data.get("all_mode")), False

    # Legacy single-target breadcrumb.  Older breadcrumbs always implied
    # auto-start; treat presence of target/run_id as enabled.
    had_auto = data.get("auto_start", bool(data.get("target") or data.get("run_id")))
    if not had_auto:
        return {}, False, False
    legacy = data.get("target")
    if legacy:
        targets[legacy] = make_target_record("legacy-breadcrumb")
        return targets, False, True
    return {}, True, True


# ---------------------------------------------------------------------------
# Structured status
# ---------------------------------------------------------------------------

def _display_id(pr: dict) -> str:
    gh = pr.get("gh_pr_number")
    return f"#{gh}" if gh else pr.get("id", "?")


def _window_names(pr: dict) -> dict[str, str]:
    d = _display_id(pr)
    return {
        "implementation": d,
        "review": f"review-{d}",
        "qa": f"qa-{d}",
        "sign_off": f"signoff-{d}",
        "merge": f"merge-{d}",
    }


def _find_window(windows: dict[str, str], pr: dict, phase: str) -> dict | None:
    """The phase's own window if live, else any qa scenario window (for QA),
    else the implementation window.  None when nothing is live."""
    names = _window_names(pr)
    order = [phase] if phase in names else []
    order.append("implementation")
    for kind in order:
        name = names[kind]
        if name in windows:
            return {"name": name, "id": windows[name], "kind": kind}
        if kind == "qa":
            prefix = f"{name}-s"
            for wname in sorted(windows):
                if wname.startswith(prefix):
                    return {"name": wname, "id": windows[wname], "kind": "qa"}
    return None


def _signed_off_reason(pr_id: str, holds: dict) -> str:
    h = holds.get(pr_id)
    if h and h.get("explicit"):
        return "signed off (fresh SIGNOFF_MERGE); stop-before-merge — press g"
    if h:
        return ("signed off (fresh SIGNOFF_MERGE); waiting for manual merge "
                f"(held by {', '.join(h['targets'])}) — press g")
    return "signed off (fresh SIGNOFF_MERGE); auto-merge pending"


def _awaiting_signoff_reason(pr_id: str, inp: dict, holds: dict,
                             passed: str) -> str:
    """Reason for a PR whose last gate (*passed*) is done and that now
    needs sign-off before it can merge."""
    signoff = (inp.get("signoff") or {}).get(pr_id) or {}
    if signoff.get("fresh") and signoff.get("verdict") == "SIGNOFF_MERGE":
        return _signed_off_reason(pr_id, holds)
    return (f"{passed}; awaiting sign-off (hand-off on next scheduler "
            "pass)")


def _derive(pr: dict, inp: dict, pr_map: dict,
            holds: dict) -> tuple[str, str, str]:
    """Return ``(phase, state, reason)`` for one PR from live evidence.

    *holds* is :func:`merge_holds` for the active targets."""
    pr_id = pr["id"]
    status = pr.get("status") or "pending"
    phase = _STATUS_PHASE.get(status, "pending")
    review = (inp.get("review_loops") or {}).get(pr_id)
    qa = (inp.get("qa_loops") or {}).get(pr_id)
    windows = inp.get("windows") or {}
    names = _window_names(pr)
    win_live = lambda kind: names[kind] in windows  # noqa: E731

    if status == "merged":
        return "done", "completed", "merged"
    if status == "closed":
        return "done", "completed", "closed"

    # Merge overlays — the merge step is live regardless of registry status.
    if pr_id in (inp.get("merge_input_required") or set()):
        return "merge", "waiting", "merge INPUT_REQUIRED — answer in merge window"
    if pr_id in (inp.get("pending_merge") or set()):
        if win_live("merge"):
            return "merge", "running", "updating the main repo after the merge"
        signoff = (inp.get("signoff") or {}).get(pr_id) or {}
        if not (signoff.get("fresh") and signoff.get("verdict") == "SIGNOFF_MERGE"):
            return (phase, "waiting",
                    "merge blocked by sign-off gate (no fresh SIGNOFF_MERGE)")
        return "merge", "failed", "merge attempt failed; no merge window"

    if status == "pending":
        deps = pr.get("depends_on") or []
        blocking = []
        for d in deps:
            dpr = pr_map.get(d)
            dstatus = (dpr or {}).get("status", "missing")
            if dstatus == "merged":
                continue
            tag = f"{d} ({dstatus}"
            if d in holds:
                tag += ", " + held_by_text(holds[d])
            blocking.append(tag + ")")
        if blocking:
            return "pending", "waiting", "blocked on " + ", ".join(blocking)
        if pr_id in (inp.get("launching") or set()):
            return "implementation", "running", "launching implementation"
        return "pending", "queued", "ready; starts on next scheduler pass"

    if status == "in_progress":
        if pr.get("spec_pending"):
            return phase, "waiting", "spec generation awaiting input"
        if pr_id in (inp.get("launching") or set()):
            return phase, "running", "launching implementation"
        if not win_live("implementation"):
            return phase, "paused", "no implementation window"
        idle = (inp.get("impl_idle") or {}).get(pr_id)
        if idle == "waiting":
            return phase, "waiting", "permission prompt in implementation window"
        if idle == "idle":
            return phase, "running", "impl idle; review transition pending"
        return phase, "running", "implementing"

    if status == "in_review":
        if review:
            it = review.get("iteration") or 0
            last = review.get("verdict") or ""
            if review.get("input_required"):
                return phase, "waiting", f"review INPUT_REQUIRED (iteration {it})"
            if review.get("running"):
                reason = f"review iteration {it}"
                if last:
                    reason += f" (last {last})"
                return phase, "running", reason
            if last in _REVIEW_PASS:
                if inp.get("skip_qa"):
                    # No QA will run: the next step is sign-off/merge.
                    return (phase, "waiting", _awaiting_signoff_reason(
                        pr_id, inp, holds, "review passed; QA skipped (skip_qa)"))
                return phase, "waiting", "review passed; QA transition pending"
            if last in ("KILLED", "ERROR"):
                return phase, "failed", f"review loop ended {last}"
            if last:
                return phase, "paused", f"review loop stopped (last {last})"
        if win_live("review"):
            return phase, "running", "review window open (no loop)"
        return phase, "queued", "review loop starts on next scheduler pass"

    if status == "qa":
        if qa:
            if qa.get("error"):
                return phase, "failed", f"QA error: {qa['error']}"
            verdict = qa.get("verdict") or ""
            total = qa.get("total") or 0
            done = qa.get("done") or 0
            if qa.get("running"):
                if qa.get("planning"):
                    return phase, "running", "planning scenarios"
                return phase, "running", f"scenario {done}/{total} done"
            if verdict == "INPUT_REQUIRED":
                if qa.get("recorded"):
                    return (phase, "waiting",
                            "last QA run ended INPUT_REQUIRED (see QA note); "
                            "press t / z t to re-run QA")
                return phase, "waiting", "QA INPUT_REQUIRED — answer in QA window"
            if verdict == "PASS":
                return (phase, "waiting",
                        _awaiting_signoff_reason(pr_id, inp, holds, "QA passed"))
            if verdict == "NEEDS_WORK":
                return phase, "waiting", "QA NEEDS_WORK; returning to review"
            if verdict:
                return phase, "paused", f"QA ended {verdict}"
        if inp.get("skip_qa"):
            return (phase, "waiting",
                    "skip_qa set; sign-off follows the review PASS")
        return phase, "queued", "QA starts on next scheduler pass"

    if status == "sign_off":
        signoff = (inp.get("signoff") or {}).get(pr_id) or {}
        verdict = signoff.get("verdict")
        if not verdict:
            if win_live("sign_off"):
                return phase, "running", "sign-off review running"
            return (phase, "queued", "no sign-off window; relaunches on next "
                    "scheduler pass")
        if not signoff.get("fresh"):
            why = signoff.get("stale_reason") or "HEAD moved"
            if why == "HEAD moved":
                return (phase, "waiting", f"{verdict} stale (HEAD moved); "
                        "sign-off relaunches against current HEAD")
            return (phase, "waiting", f"{verdict} stale ({why}); sign-off "
                    "re-runs against the current base")
        if verdict == "SIGNOFF_MERGE":
            return phase, "waiting", _signed_off_reason(pr_id, holds)
        if verdict == "SIGNOFF_BLOCKED":
            return phase, "paused", "sign-off BLOCKED — needs human decision"
        return phase, "waiting", f"routed {verdict}"

    return phase, "queued", f"status {status}"


def build_status(inp: dict) -> dict:
    """Build the ``pm.autostart.status/1`` dict from gathered inputs.

    *inp* keys (all optional except ``prs``): ``prs``, ``targets`` (ordered
    ``{pr_id: record}``), ``all_mode``, ``enabled``, ``run_id``, ``owner``,
    ``stop_before_merge``, ``review_loops``, ``qa_loops``, ``pending_merge``,
    ``merge_input_required``, ``launching``,
    ``impl_idle``, ``windows`` (``{name: id}``), ``signoff``
    (``{pr_id: {verdict, fresh, stale_reason?}}``), ``skip_qa``, ``generated_at``.
    """
    prs = inp.get("prs") or []
    pr_map = {p["id"]: p for p in prs if p.get("id")}
    targets: dict[str, dict] = inp.get("targets") or {}
    all_mode = bool(inp.get("all_mode"))
    enabled = bool(inp.get("enabled", bool(targets) or all_mode))
    stop = set(inp.get("stop_before_merge") or ())
    windows = inp.get("windows") or {}
    # Only active targets hold their closures (off → explicit marks only).
    holds = merge_holds(prs, targets if enabled else {}, stop)

    if not enabled:
        mode = "off"
    elif all_mode:
        mode = "all"
    else:
        mode = "targets"

    target_ids = list(targets) if enabled else []
    nb = needed_by(prs, target_ids)

    def run_entry(pr: dict) -> dict:
        pr_id = pr["id"]
        phase, state, reason = _derive(pr, inp, pr_map, holds)
        win = _find_window(windows, pr, phase)
        review = (inp.get("review_loops") or {}).get(pr_id)
        qa = (inp.get("qa_loops") or {}).get(pr_id)
        signoff = (inp.get("signoff") or {}).get(pr_id)
        return {
            "pr_id": pr_id,
            "display_id": _display_id(pr),
            "title": pr.get("title", ""),
            "status": pr.get("status") or "pending",
            "phase": phase,
            "state": state,
            "reason": reason,
            "is_target": pr_id in targets,
            "needed_by": nb.get(pr_id, []),
            "depends_on": list(pr.get("depends_on") or []),
            "policy": effective_policy(pr_id, holds),
            "held_by": list((holds.get(pr_id) or {}).get("targets") or []),
            "explicit_hold": bool((holds.get(pr_id) or {}).get("explicit")),
            "window": ({"name": win["name"], "id": win["id"]} if win else None),
            "review": ({
                "iteration": review.get("iteration") or 0,
                "verdict": review.get("verdict") or "",
                "running": bool(review.get("running")),
                "input_required": bool(review.get("input_required")),
            } if review else None),
            "qa": ({
                "planning": bool(qa.get("planning")),
                "total": qa.get("total") or 0,
                "done": qa.get("done") or 0,
                "counts": dict(qa.get("counts") or {}),
                "running": bool(qa.get("running")),
                "verdict": qa.get("verdict") or "",
                "error": qa.get("error") or "",
                "recorded": bool(qa.get("recorded")),
            } if qa else None),
            "signoff": ({
                "verdict": signoff.get("verdict"),
                "fresh": bool(signoff.get("fresh")),
            } if signoff else None),
        }

    # Which PRs appear in ``runs``
    if mode == "targets":
        ids = set(nb)
        run_ids = [i for i in ids
                   if i in pr_map and (i in targets or
                                       pr_map[i].get("status") not in TERMINAL_STATUSES)]
    elif mode == "all":
        merged = {p["id"] for p in prs if p.get("status") == "merged"}
        run_ids = []
        for p in prs:
            st = p.get("status") or "pending"
            if st in ("in_progress", "in_review", "qa", "sign_off"):
                run_ids.append(p["id"])
            elif st == "pending" and all(d in merged for d in (p.get("depends_on") or [])):
                run_ids.append(p["id"])
    else:
        run_ids = []

    runs_by_id = {i: run_entry(pr_map[i]) for i in run_ids}
    # Stable order: targets first (insertion order), then by closure order.
    order: list[str] = []
    for t in target_ids:
        if t in runs_by_id and t not in order:
            order.append(t)
    for i in sorted(runs_by_id):
        if i not in order:
            order.append(i)
    runs = [runs_by_id[i] for i in order]

    targets_out = []
    for t in target_ids:
        rec = targets.get(t) or {}
        pr = pr_map.get(t)
        run = runs_by_id.get(t)
        cl = closure(prs, t) - {t}
        pending = sorted(
            d for d in cl
            if (pr_map.get(d) or {}).get("status") not in TERMINAL_STATUSES)
        targets_out.append({
            "pr_id": t,
            "title": (pr or {}).get("title", ""),
            "policy": target_policy(t, rec, stop),
            "effective_policy": effective_policy(t, holds),
            "held_by": list((holds.get(t) or {}).get("targets") or []),
            "added_at": rec.get("added_at"),
            "source": rec.get("source"),
            "state": run["state"] if run else ("failed" if pr is None else "completed"),
            "phase": run["phase"] if run else "done",
            "reason": run["reason"] if run else ("PR not found" if pr is None else ""),
            "pending": pending,
        })

    return {
        "schema": SCHEMA,
        "generated_at": inp.get("generated_at") or now_iso(),
        "owner": inp.get("owner") or {},
        "enabled": enabled,
        "mode": mode,
        "run_id": inp.get("run_id"),
        "targets": targets_out,
        "runs": runs,
    }


# ---------------------------------------------------------------------------
# Row flattening (shared by CLI text output and the TUI popup)
# ---------------------------------------------------------------------------

def _progress(run: dict) -> str:
    qa = run.get("qa")
    if qa and qa.get("total"):
        counts = qa.get("counts") or {}
        tally = " ".join(f"{k}:{v}" for k, v in sorted(counts.items()))
        return f"qa {qa.get('done', 0)}/{qa['total']}" + (f" {tally}" if tally else "")
    # QA without a scenario count (still planning, or finished and its
    # scenario list cleared) must not fall back to the stale review iteration.
    if qa and qa.get("planning"):
        return "qa planning"
    if qa and qa.get("verdict"):
        return f"qa {qa['verdict']}"
    rv = run.get("review")
    if rv and rv.get("iteration"):
        return f"review #{rv['iteration']}"
    return ""


def status_rows(status: dict) -> list[dict]:
    """Flatten a status dict into display rows grouped by target.

    Each row: ``{pr_id, depth, kind, run}`` where *kind* is ``target`` (a
    target header, depth 0) or ``dep`` (an unmerged closure PR, depth 1),
    plus ``also`` (other targets that share this dep) and ``progress``.
    In ``all`` mode every run is a depth-0 row.  A shared dependency
    appears under each target that needs it (with ``also`` naming the
    others) but is one entry in ``runs`` — i.e. one worker.
    """
    runs = {r["pr_id"]: r for r in status.get("runs") or []}
    rows: list[dict] = []
    if status.get("mode") == "all":
        for r in status.get("runs") or []:
            rows.append({"pr_id": r["pr_id"], "depth": 0, "kind": "run",
                         "run": r, "also": [], "progress": _progress(r)})
        return rows
    for t in status.get("targets") or []:
        tid = t["pr_id"]
        run = runs.get(tid) or {
            "pr_id": tid, "display_id": tid, "title": t.get("title", ""),
            "phase": t.get("phase"), "state": t.get("state"),
            "reason": t.get("reason"),
            "policy": t.get("effective_policy") or t.get("policy"),
            "held_by": list(t.get("held_by") or []),
            "window": None, "needed_by": [tid],
        }
        rows.append({"pr_id": tid, "depth": 0, "kind": "target", "run": run,
                     "also": [], "progress": _progress(run),
                     "policy": t.get("policy")})
        for dep in t.get("pending") or []:
            r = runs.get(dep)
            if not r:
                continue
            also = [x for x in r.get("needed_by") or [] if x not in (tid, dep)]
            rows.append({"pr_id": dep, "depth": 1, "kind": "dep", "run": r,
                         "also": also, "progress": _progress(r)})
    return rows


def policy_labels(row: dict) -> list[tuple[str, str]]:
    """``[(label, kind)]`` naming a status row's effective merge policy and
    what causes a hold — shared by ``format_text`` and the runs popup.

    *kind* is ``stop`` / ``wait`` / ``auto``.  A wait target names its own
    policy (``wait-for-merge``); a PR held by other wait targets names them
    (``wait-for-merge ← T``).  Target rows always name a policy; an
    auto-merge target that a hold overrides says so.
    """
    run = row.get("run") or {}
    pr_id = run.get("pr_id") or row.get("pr_id")
    held_by = list(run.get("held_by") or [])
    out: list[tuple[str, str]] = []
    if run.get("explicit_hold") or run.get("policy") == POLICY_STOP:
        out.append(("stop-before-merge", "stop"))
    # A target's own wait policy, even once nothing is left to hold (a
    # completed target's closure is merged, so it is in no ``held_by``).
    if pr_id in held_by or (row.get("kind") == "target"
                            and row.get("policy") == POLICY_WAIT):
        out.append(("wait-for-merge", "wait"))
    others = [t for t in held_by if t != pr_id]
    if others:
        out.append(("wait-for-merge ← " + ", ".join(others), "wait"))
    if row.get("kind") == "target" and row.get("policy") == POLICY_AUTO:
        out.insert(0, ("auto-merge, held" if out else "auto-merge", "auto"))
    return out


def format_text(status: dict) -> str:
    """Human-readable rendering of a status dict (CLI ``status`` output)."""
    mode = status.get("mode")
    lines = []
    owner = status.get("owner") or {}
    head = f"Auto-start: {mode}"
    if mode == "targets":
        head += f" ({len(status.get('targets') or [])} target(s))"
    if status.get("run_id"):
        head += f"  run={status['run_id']}"
    if owner.get("session"):
        head += f"  owner={owner['session']}"
    lines.append(head)
    if mode == "off":
        lines.append("No auto-start targets (auto-start off).")
        return "\n".join(lines)
    for row in status_rows(status):
        r = row["run"]
        indent = "  " * row["depth"]
        mark = "◎ " if row["kind"] == "target" else "└ "
        if row["kind"] == "run":
            mark = ""
        # The default policy goes unlabelled in text (only holds show).
        labels = [lbl for lbl, _ in policy_labels(row) if lbl != "auto-merge"]
        pol = f" [{'; '.join(labels)}]" if labels else ""
        prog = f" {row['progress']}" if row.get("progress") else ""
        win = f"  win={r['window']['name']}" if r.get("window") else ""
        also = f"  also needed by {', '.join(row['also'])}" if row.get("also") else ""
        lines.append(
            f"{indent}{mark}{r['pr_id']}{pol} {r.get('state')}/{r.get('phase')}"
            f"{prog} — {r.get('reason') or ''}{win}{also}")
        title = r.get("title") or ""
        if title:
            lines.append(f"{indent}    {title[:70]}")
    return "\n".join(lines)


def qa_progress_input(state) -> dict:
    """Summarise a QALoopState-like object into a ``qa_loops`` input entry."""
    verdicts = dict(getattr(state, "scenario_verdicts", {}) or {})
    return {
        "running": bool(getattr(state, "running", False)),
        "planning": bool(getattr(state, "planning_phase", False)),
        "total": len(getattr(state, "scenarios", []) or []),
        "done": len(verdicts),
        "counts": dict(Counter(v for v in verdicts.values() if v)),
        "verdict": getattr(state, "latest_verdict", "") or "",
        "error": getattr(state, "_error", "") or "",
    }


def review_progress_input(state) -> dict:
    """Summarise a ReviewLoopState-like object into a ``review_loops`` entry."""
    return {
        "running": bool(getattr(state, "running", False)),
        "iteration": getattr(state, "iteration", 0) or 0,
        "verdict": getattr(state, "latest_verdict", "") or "",
        "input_required": bool(getattr(state, "input_required", False)),
    }
