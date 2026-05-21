"""FastAPI single-file walker server for the augmented adversarial-review cycle.

Reads ``project.yaml``'s ``reviews:`` list to enumerate reviews, resolves each
review's markdown surfaces under ``<pm-root>/docs/adversarial-review/reviews/<id>/``,
watches them with ``watchdog`` and pushes filesystem changes to clients over a
single ``/events?review=<id>`` SSE endpoint.

Self-contained: PR 1 (``paths.py`` / ``registry.py``) is not a dependency, so the
path/registry helpers live here under the names PR 1 will eventually own.

Lock state: editable controls (accept / edit / bulk-accept / skip / reopen) and the
Apply button are live only in ``awaiting-human-review`` on the *current* cycle.
Apply additionally requires this process to hold the per-review leader lock
(see :class:`LeaderLock`) and a non-``auto-run`` mode. Viewing in-progress
current-cycle artifacts is always allowed — the lock governs modification, not
visibility.
"""

from __future__ import annotations

import asyncio
import contextlib
import fcntl
import json
import os
import re
import statistics
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sse_starlette.sse import EventSourceResponse
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from pm_core.review import md_parser, md_writer

_HERE = Path(__file__).parent
TEMPLATES_DIR = _HERE / "templates"
STATIC_DIR = _HERE / "static"

REVIEWS_SUBDIR = Path("docs/adversarial-review/reviews")

# Phases in which a stage is actively running — the activity indicator animates.
RUNNING_PHASES = frozenset({"review", "audit", "response", "applying"})
# Walker filter dimensions (also the response-block field names they match on).
FILTER_KEYS = ("provenance", "target-section", "suggested-verdict", "status")
# Filenames the walker watches, classified into SSE event types.
_RESPONSE_RE = re.compile(r"^REVIEW_RESPONSE_CYCLE_(\d+)\.md$")
_AUDIT_RE = re.compile(r"^CITATION_AUDIT_CYCLE_(\d+)\.md$")
_REVIEW_RE = re.compile(r"^REVIEW_CYCLE_(\d+)\.md$")


# ---------------------------------------------------------------------------
# Path + registry resolution (PR 1 will lift these into paths.py / registry.py)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReviewPaths:
    """Per-review file resolution rooted at the pm directory."""

    pm_root: Path
    review_id: str

    @property
    def dir(self) -> Path:
        return self.pm_root / REVIEWS_SUBDIR / self.review_id

    @property
    def state(self) -> Path:
        return self.dir / "STATE.md"

    @property
    def focus(self) -> Path:
        return self.dir / "UI_FOCUS.md"

    @property
    def notes(self) -> Path:
        return self.dir / "NOTES.md"

    @property
    def leader_lock(self) -> Path:
        return self.dir / "STATE.md.leader"

    def review_cycle(self, n: int) -> Path:
        return self.dir / f"REVIEW_CYCLE_{n}.md"

    def audit_cycle(self, n: int) -> Path:
        return self.dir / f"CITATION_AUDIT_CYCLE_{n}.md"

    def response_cycle(self, n: int) -> Path:
        return self.dir / f"REVIEW_RESPONSE_CYCLE_{n}.md"


def load_project(pm_root: Path) -> dict[str, Any]:
    """Read ``project.yaml`` directly (read-only, no store validation/locking)."""
    p = Path(pm_root) / "project.yaml"
    if not p.exists():
        return {}
    try:
        return yaml.safe_load(p.read_text()) or {}
    except yaml.YAMLError:
        return {}


def list_reviews(pm_root: Path) -> list[dict[str, Any]]:
    data = load_project(pm_root)
    reviews = data.get("reviews")
    return list(reviews) if isinstance(reviews, list) else []


def get_review(pm_root: Path, review_id: str) -> dict[str, Any] | None:
    for r in list_reviews(pm_root):
        if r.get("id") == review_id:
            return r
    return None


# ---------------------------------------------------------------------------
# Reading the markdown surfaces into plain (JSON-friendly) dicts
# ---------------------------------------------------------------------------


def read_state(paths: ReviewPaths) -> dict[str, Any] | None:
    """Parse ``STATE.md`` into a dict, or ``None`` when no cycle has started."""
    if not paths.state.exists():
        return None
    sf = md_parser.parse_state(paths.state.read_text())
    return {
        "current-cycle": sf.current_cycle,
        "current-phase": sf.current_phase,
        "mode": sf.mode,
        "last-transition": sf.last_transition,
    }


def read_focus(paths: ReviewPaths) -> dict[str, Any] | None:
    if not paths.focus.exists():
        return None
    fc = md_parser.parse_focus(paths.focus.read_text())
    return {
        "view": fc.view,
        "cycle": fc.cycle,
        "target": fc.target,
        "timestamp": fc.timestamp,
    }


def count_audit_entries(paths: ReviewPaths, cycle: int) -> int:
    p = paths.audit_cycle(cycle)
    if not p.exists():
        return 0
    return len(md_parser.parse_audit_doc(p.read_text()).entries)


def available_cycles(paths: ReviewPaths, current: int | None) -> list[int]:
    """Cycle numbers present on disk plus the current cycle, latest first."""
    found: set[int] = set()
    if paths.dir.exists():
        for f in paths.dir.iterdir():
            for rx in (_RESPONSE_RE, _AUDIT_RE, _REVIEW_RE):
                m = rx.match(f.name)
                if m:
                    found.add(int(m.group(1)))
    if isinstance(current, int):
        found.add(current)
    return sorted(found, reverse=True)


def _block_view(b: md_parser.ResponseBlock) -> dict[str, Any]:
    f = b.fields
    return {
        "id": b.id,
        "provenance": b.provenance,
        "source-anchor": f.get("source-anchor", ""),
        "target-section": f.get("target-section", ""),
        "before": f.get("before", ""),
        "after": f.get("after", ""),
        "suggested-verdict": f.get("suggested-verdict", ""),
        "suggested-rationale": f.get("suggested-rationale", ""),
        "human-verdict": f.get("human-verdict") or "",
        "human-rationale": f.get("human-rationale") or "",
        "human-commentary": f.get("human-commentary") or "",
        "status": f.get("status", "pending"),
        "interactions": b.interactions,
    }


def _block_matches(view: dict[str, Any], filters: dict[str, str]) -> bool:
    for key in FILTER_KEYS:
        want = filters.get(key)
        if want and view.get(key) != want:
            return False
    return True


def breadcrumb(cycle: Any, phase: str | None, is_current: bool, audited: int = 0) -> str:
    if not is_current:
        # A prior cycle is finished history; `phase` here is the *review's* live
        # phase (cycle-global), which is unrelated to this superseded cycle, so
        # surfacing it would mislead (e.g. "Cycle 2 · audit" while cycle 3 audits).
        return f"Cycle {cycle} · read-only"
    table = {
        "review": f"Cycle {cycle} · review in progress",
        "audit": f"Cycle {cycle} · audit loop running · {audited} citations audited",
        "response": f"Cycle {cycle} · response in progress",
        "awaiting-human-review": f"Cycle {cycle} · ready for your review · editable",
        "applying": f"Cycle {cycle} · applying accepted changes",
        "complete": f"Cycle {cycle} · complete · read-only",
    }
    return table.get(phase or "", f"Cycle {cycle} · {phase}")


def human_action_hint(phase: str | None, is_current: bool) -> str:
    if not is_current:
        return "Browsing prior cycle history (read-only)."
    # Every running phase says the same thing; only the actionable phases differ.
    return {
        "awaiting-human-review": "Walk the proposed changes; click Apply when done.",
        "complete": "Browse this cycle's history, or move to the next cycle.",
    }.get(phase or "", "Wait or browse prior cycles.")


def engagement_signals(blocks: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Best-effort bulk-accept ratio, median view-time, suggester-confidence dist."""
    acted = 0
    bulk = 0
    view_times: list[float] = []
    confidence: dict[str, int] = {}
    for b in blocks:
        for ev in b.get("interactions", []):
            action = ev.get("action")
            if action == "bulk-accept":
                bulk += 1
            if action in {"accept-as-suggested", "bulk-accept", "edit", "skip", "auto-accepted"}:
                acted += 1
            if action == "viewed":
                dur = ev.get("duration-ms")
                if isinstance(dur, (int, float)):
                    view_times.append(float(dur))
        sv = b.get("suggested-verdict") or "—"
        confidence[sv] = confidence.get(sv, 0) + 1
    return {
        "bulk-accept-ratio": round(bulk / acted, 2) if acted else None,
        "median-view-ms": int(statistics.median(view_times)) if view_times else None,
        "suggester-confidence": confidence,
        "acted": acted,
    }


def _convergence_from_preamble(preamble: str) -> str | None:
    """The audit doc's convergence line (e.g. 'Convergence reached in 2 rounds.')."""
    m = re.search(r"(Convergence[^\n.]*\.?)", preamble, re.IGNORECASE)
    return m.group(1).strip() if m else None


# ---------------------------------------------------------------------------
# View-model assembly shared by the page route, the status API and SSE refresh
# ---------------------------------------------------------------------------


def _select_body(
    paths: ReviewPaths, rendered_cycle: int, is_current: bool, phase: str | None,
    filters: dict[str, str],
) -> dict[str, Any]:
    """Pick the body to render and parse each underlying file at most once.

    Response file wins (the editable/historical walker); otherwise the current
    cycle's in-progress review/audit artifact streams read-only. The audit doc
    is parsed once and reused for entries, the audited count, and convergence.
    """
    out: dict[str, Any] = {
        "body_mode": "empty", "blocks": [], "all_blocks": [], "review_md": "",
        "audit_entries": [], "audited": 0, "convergence": None,
    }

    audit_doc: md_parser.AuditDoc | None = None

    def get_audit() -> md_parser.AuditDoc | None:
        nonlocal audit_doc
        if audit_doc is None and paths.audit_cycle(rendered_cycle).exists():
            audit_doc = md_parser.parse_audit_doc(paths.audit_cycle(rendered_cycle).read_text())
        return audit_doc

    if paths.response_cycle(rendered_cycle).exists():
        out["body_mode"] = "changes"
        doc = md_parser.parse_response_doc(paths.response_cycle(rendered_cycle).read_text())
        # `all_blocks` feeds the engagement signals (which are over the whole
        # cycle per R4); `blocks` is the filtered subset the walker renders.
        all_blocks = [_block_view(x) for x in doc.blocks]
        out["all_blocks"] = all_blocks
        out["blocks"] = [b for b in all_blocks if _block_matches(b, filters)]
    elif is_current and phase == "review" and paths.review_cycle(rendered_cycle).exists():
        out["body_mode"] = "review"
        out["review_md"] = paths.review_cycle(rendered_cycle).read_text()
    elif is_current and phase == "audit" and (ad := get_audit()) is not None:
        out["body_mode"] = "audit"
        out["audit_entries"] = ad.entries
        out["audited"] = len(ad.entries)
    elif is_current and phase == "response":
        out["body_mode"] = "response-pending"

    # Convergence is only shown on the walker and audit views; derive it from the
    # one parse rather than re-reading the audit file.
    if out["body_mode"] in ("changes", "audit") and (ad := get_audit()) is not None:
        out["convergence"] = _convergence_from_preamble(ad.preamble)
    return out


def build_review_context(
    pm_root: Path,
    review_id: str,
    *,
    cycle: int | None = None,
    filters: dict[str, str] | None = None,
    is_leader: bool = True,
    review: dict[str, Any] | None = None,
) -> dict[str, Any]:
    filters = filters or {}
    paths = ReviewPaths(pm_root, review_id)
    review = review or get_review(pm_root, review_id) or {"id": review_id}
    state = read_state(paths)
    focus = read_focus(paths)

    # No cycles yet: STATE.md absent, or present with a null current-cycle (the
    # initial state PR 1 writes at review creation).
    if state is None or state.get("current-cycle") is None:
        return {
            "review": review,
            "review_id": review_id,
            "no_cycles": True,
            "breadcrumb": "no cycles yet",
            "hint": (
                "Run `pm review <target>` or `pm plan literature-review <plan>` "
                "to start the first cycle."
            ),
            "cycles": [],
            "rendered_cycle": None,
            "phase": None,
            "mode": None,
            "editable": False,
            "can_apply": False,
            "is_leader": is_leader,
            "animating": False,
            "audited": 0,
            "body_mode": "none",
            "blocks": [],
            "filters": filters,
            "focus": focus,
        }

    current_cycle = state["current-cycle"]
    phase = state["current-phase"]
    mode = state["mode"]
    cycles = available_cycles(paths, current_cycle)
    rendered_cycle = cycle if cycle is not None else current_cycle
    is_current = rendered_cycle == current_cycle

    editable = phase == "awaiting-human-review" and is_current
    can_apply = editable and mode != "auto-run" and is_leader
    animating = is_current and phase in RUNNING_PHASES

    body = _select_body(paths, rendered_cycle, is_current, phase, filters)
    audited = body["audited"]

    return {
        "review": review,
        "review_id": review_id,
        "no_cycles": False,
        "current_cycle": current_cycle,
        "rendered_cycle": rendered_cycle,
        "is_current": is_current,
        "phase": phase,
        "mode": mode,
        "cycles": cycles,
        "editable": editable,
        "can_apply": can_apply,
        "is_leader": is_leader,
        "animating": animating,
        "audited": audited,
        "breadcrumb": breadcrumb(rendered_cycle, phase, is_current, audited),
        "hint": human_action_hint(phase, is_current),
        "convergence": body["convergence"],
        "engagement": engagement_signals(body["all_blocks"]),
        "body_mode": body["body_mode"],
        "blocks": body["blocks"],
        "review_md": body["review_md"],
        "audit_entries": body["audit_entries"],
        "filters": filters,
        "focus": focus,
    }


# ---------------------------------------------------------------------------
# Leader lock — only one process may write STATE.md (the Apply transition)
# ---------------------------------------------------------------------------


class LeaderLock:
    """Per-review state-writer election via ``flock`` on a stable lockfile.

    The holder of the exclusive flock is the single process allowed to write
    ``STATE.md``. ``flock`` conflicts across distinct ``open()`` file
    descriptions (even within one process), and the OS releases it on process
    death, so a follower's later :meth:`acquire` succeeds automatically once the
    leader exits — no stale-PID heartbeat to reap.
    """

    def __init__(self, lock_path: Path | str):
        self.lock_path = Path(lock_path)
        self._fd: int | None = None
        self.is_leader = False

    def acquire(self) -> bool:
        if self.is_leader:
            return True
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        if self._fd is None:
            self._fd = os.open(str(self.lock_path), os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.is_leader = True
        except OSError:
            self.is_leader = False
        return self.is_leader

    def release(self) -> None:
        if self._fd is not None:
            try:
                if self.is_leader:
                    fcntl.flock(self._fd, fcntl.LOCK_UN)
            finally:
                os.close(self._fd)
                self._fd = None
                self.is_leader = False


# ---------------------------------------------------------------------------
# Watcher manager: watchdog observer → per-review SSE subscriber queues
# ---------------------------------------------------------------------------


class _ReviewEventHandler(FileSystemEventHandler):
    """Forwards directory events for one review to the manager's classifier."""

    def __init__(self, review_id: str, on_change):
        self.review_id = review_id
        self._on_change = on_change

    def _emit(self, path: str | bytes | None) -> None:
        if path:
            self._on_change(self.review_id, os.path.basename(os.fsdecode(path)))

    def on_created(self, event):
        if not event.is_directory:
            self._emit(event.src_path)

    def on_modified(self, event):
        if not event.is_directory:
            self._emit(event.src_path)

    def on_moved(self, event):
        if not event.is_directory:
            self._emit(event.dest_path)


class WatcherManager:
    """Owns the watchdog observer, per-review subscriber queues and leader locks.

    Watches the review *directory* (not file inodes) because ``md_writer`` writes
    atomically via temp-file + ``os.replace``: the canonical file's inode changes
    on every write, so a per-file watch would go stale after the first write.
    """

    def __init__(self, pm_root: Path, leader_interval: float = 2.0):
        self.pm_root = Path(pm_root)
        self.leader_interval = leader_interval
        self._observer: Observer | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._subs: dict[str, set[asyncio.Queue]] = {}
        self._watches: dict[str, Any] = {}
        self._leaders: dict[str, LeaderLock] = {}
        # subscribe()/unsubscribe() mutate _subs/_watches from the event-loop
        # thread while the watchdog thread iterates _subs in _broadcast(); guard
        # both so a concurrent add/discard can't trip "set changed size during
        # iteration" (and drop an SSE event) on the watcher thread.
        self._subs_guard = threading.Lock()
        # leader_for() runs in the sync-route threadpool; serialize its
        # get-or-create so two concurrent first-touches for the same review
        # can't each build a LeaderLock (the second's flock would fail and
        # clobber the real holder, wedging Apply off for its own session).
        self._leaders_guard = threading.Lock()

    # -- lifecycle --
    def start(self) -> None:
        if self._observer is None:
            self._observer = Observer()
            self._observer.start()

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def stop(self) -> None:
        if self._observer is not None:
            self._observer.stop()
            with contextlib.suppress(Exception):
                self._observer.join(timeout=2)
            self._observer = None
        for lock in self._leaders.values():
            lock.release()
        self._leaders.clear()

    # -- leadership --
    def peek_leader(self, review_id: str) -> bool:
        """Report current leadership *without* creating or acquiring a lock.

        Read-only status views (the dashboard's SSE-driven ``/api/status``
        refresh) must not claim write-leadership just by polling status — doing
        so would block Apply from any other concurrent UI, even for reviews the
        dashboard user never opens. Acquisition is reserved for the walker page
        (``GET …/changes``) and Apply; those routes call :meth:`leader_for`.
        Returns ``False`` when no lock has been built for this review yet.
        """
        lock = self._leaders.get(review_id)
        return bool(lock and lock.is_leader)

    def leader_for(self, review_id: str) -> LeaderLock:
        lock = self._leaders.get(review_id)
        if lock is not None:
            return lock
        with self._leaders_guard:
            lock = self._leaders.get(review_id)
            if lock is None:
                lock = LeaderLock(ReviewPaths(self.pm_root, review_id).leader_lock)
                lock.acquire()
                self._leaders[review_id] = lock
            return lock

    async def leader_loop(self) -> None:
        """Followers retry the flock periodically; on takeover, push a leader event."""
        while True:
            await asyncio.sleep(self.leader_interval)
            # A transient error acquiring one review's lock (e.g. an OSError from
            # the lockfile's mkdir/open) must not kill the periodic failover retry
            # for every other review; swallow it and keep looping. CancelledError
            # comes from asyncio.sleep above and propagates for clean shutdown.
            try:
                for review_id, lock in list(self._leaders.items()):
                    if not lock.is_leader and lock.acquire():
                        self._broadcast(review_id, {"type": "leader", "data": {"is_leader": True}})
            except Exception:
                continue

    # -- subscriptions --
    def subscribe(self, review_id: str, queue: asyncio.Queue) -> None:
        with self._subs_guard:
            subs = self._subs.setdefault(review_id, set())
            subs.add(queue)
            if review_id not in self._watches and self._observer is not None:
                d = ReviewPaths(self.pm_root, review_id).dir
                d.mkdir(parents=True, exist_ok=True)
                handler = _ReviewEventHandler(review_id, self._on_change)
                self._watches[review_id] = self._observer.schedule(handler, str(d), recursive=False)

    def unsubscribe(self, review_id: str, queue: asyncio.Queue) -> None:
        with self._subs_guard:
            subs = self._subs.get(review_id)
            if subs is None:
                return
            subs.discard(queue)
            if not subs:
                self._subs.pop(review_id, None)
                watch = self._watches.pop(review_id, None)
                if watch is not None and self._observer is not None:
                    with contextlib.suppress(Exception):
                        self._observer.unschedule(watch)

    # -- event classification + broadcast (runs in watchdog thread) --
    def _on_change(self, review_id: str, basename: str) -> None:
        event = self._classify(review_id, basename)
        if event is not None:
            self._broadcast(review_id, event)

    def _classify(self, review_id: str, basename: str) -> dict[str, Any] | None:
        paths = ReviewPaths(self.pm_root, review_id)
        if basename == "STATE.md":
            return {"type": "state", "data": read_state(paths) or {}}
        if basename == "UI_FOCUS.md":
            return {"type": "focus", "data": read_focus(paths) or {}}
        m = _RESPONSE_RE.match(basename)
        if m:
            return {"type": "response", "data": {"cycle": int(m.group(1))}}
        m = _AUDIT_RE.match(basename)
        if m:
            n = int(m.group(1))
            return {"type": "audit", "data": {"cycle": n, "audited": count_audit_entries(paths, n)}}
        m = _REVIEW_RE.match(basename)
        if m:
            return {"type": "review", "data": {"cycle": int(m.group(1))}}
        return None

    def _broadcast(self, review_id: str, event: dict[str, Any]) -> None:
        loop = self._loop
        if loop is None:
            return
        # Snapshot under the guard so a concurrent (un)subscribe can't mutate the
        # set mid-iteration; schedule the puts outside it to keep the lock brief.
        with self._subs_guard:
            queues = list(self._subs.get(review_id, ()))
        for q in queues:
            loop.call_soon_threadsafe(q.put_nowait, event)


# ---------------------------------------------------------------------------
# Mutating helpers (lock-state enforced server-side)
# ---------------------------------------------------------------------------


def _require_editable(pm_root: Path, review_id: str) -> tuple[ReviewPaths, dict[str, Any]]:
    paths = ReviewPaths(pm_root, review_id)
    state = read_state(paths)
    if state is None:
        raise HTTPException(status_code=404, detail="no cycles yet")
    if state["current-phase"] != "awaiting-human-review":
        raise HTTPException(status_code=409, detail="not in awaiting-human-review")
    return paths, state


def _apply_change(paths: ReviewPaths, cycle: int, change_id: str, action: str, payload: dict[str, Any]) -> dict[str, Any]:
    resp = paths.response_cycle(cycle)
    if action == "accept":
        blocks = md_parser.parse_response_blocks(resp.read_text())
        target = next((b for b in blocks if b.id == change_id), None)
        verdict = target.fields.get("suggested-verdict") if target else ""
        md_writer.update_response_block(
            resp, change_id, {"human-verdict": verdict, "status": "accepted-as-suggested"}
        )
        md_writer.append_interaction(resp, change_id, {"action": "accept-as-suggested"})
        return {"status": "accepted-as-suggested", "human-verdict": verdict}
    if action == "edit":
        updates: dict[str, Any] = {"status": "edited"}
        fields_changed: list[str] = []
        for key in ("after", "human-verdict", "human-rationale", "human-commentary"):
            if key in payload and payload[key] is not None:
                updates[key] = payload[key]
                fields_changed.append(key)
        if "human-verdict" not in updates:
            updates["human-verdict"] = "modify"
        md_writer.update_response_block(resp, change_id, updates)
        md_writer.append_interaction(resp, change_id, {"action": "edit", "fields": fields_changed})
        if payload.get("human-commentary"):
            md_writer.append_interaction(resp, change_id, {"action": "comment-added"})
        return {"status": "edited"}
    if action == "skip":
        md_writer.update_response_block(resp, change_id, {"status": "skipped"})
        md_writer.append_interaction(resp, change_id, {"action": "skip"})
        return {"status": "skipped"}
    if action == "viewed":
        # View-time telemetry only — append the interaction (so engagement
        # signals have data) without touching the block's verdict/status.
        dur = payload.get("duration-ms")
        event: dict[str, Any] = {"action": "viewed"}
        if isinstance(dur, (int, float)):
            event["duration-ms"] = dur
        md_writer.append_interaction(resp, change_id, event)
        return {"status": "viewed"}
    if action == "reopen":
        md_writer.update_response_block(resp, change_id, {"status": "pending"})
        md_writer.append_interaction(resp, change_id, {"action": "reopen"})
        return {"status": "pending"}
    raise HTTPException(status_code=400, detail=f"unknown action {action!r}")


def _bulk_accept(paths: ReviewPaths, cycle: int, filters: dict[str, str], scope: str) -> int:
    """Accept every pending block matching ``filters``; return the count accepted."""
    resp = paths.response_cycle(cycle)
    blocks = [_block_view(b) for b in md_parser.parse_response_blocks(resp.read_text())]
    accepted = 0
    for b in blocks:
        if b["status"] != "pending":
            continue
        if not _block_matches(b, filters):
            continue
        md_writer.update_response_block(
            resp, b["id"],
            {"human-verdict": b["suggested-verdict"], "status": "accepted-as-suggested"},
        )
        md_writer.append_interaction(resp, b["id"], {"action": "bulk-accept", "scope": scope})
        accepted += 1
    return accepted


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def build_app(pm_root: Path | str | None = None) -> FastAPI:
    if pm_root is None:
        from pm_core import store

        pm_root = store.find_project_root()
    pm_root = Path(pm_root)

    manager = WatcherManager(pm_root)
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI):
        manager.start()
        manager.set_loop(asyncio.get_running_loop())
        leader_task = asyncio.create_task(manager.leader_loop())
        try:
            yield
        finally:
            leader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await leader_task
            manager.stop()

    app = FastAPI(lifespan=lifespan)
    app.state.pm_root = pm_root
    app.state.manager = manager
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    def _is_leader(review_id: str) -> bool:
        return manager.leader_for(review_id).is_leader

    def _require_known_review(review_id: str) -> None:
        """404 for ids absent from the registry, so a typo'd or crafted id can't
        spin up a watch / leader lock against an arbitrary on-disk directory."""
        if get_review(pm_root, review_id) is None:
            raise HTTPException(status_code=404, detail=f"unknown review {review_id!r}")

    # -- dashboard --
    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request):
        rows = []
        for r in list_reviews(pm_root):
            rid = r.get("id", "")
            # The dashboard is read-only — it never renders Apply, so it must not
            # call _is_leader (which acquires the per-review leader flock for the
            # process lifetime). Claiming write-leadership for every listed review
            # just to render a status page would block Apply from any other
            # concurrent UI, even for reviews this user never opens. Leadership is
            # claimed lazily when a walker/status/apply route actually touches a
            # specific review.
            ctx = build_review_context(pm_root, rid, is_leader=False, review=r)
            rows.append({"review": r, "ctx": ctx})
        active = [row for row in rows if row["review"].get("status") != "archived"]
        archived = [row for row in rows if row["review"].get("status") == "archived"]
        return templates.TemplateResponse(
            request, "dashboard.html", {"active": active, "archived": archived}
        )

    # -- per-review walker page --
    @app.get("/review/{review_id}/changes", response_class=HTMLResponse)
    def changes(request: Request, review_id: str, cycle: int | None = None):
        _require_known_review(review_id)
        # Query params use snake_case (form field names); filter keys use dashes.
        qp = request.query_params
        raw_filters = {k: qp.get(k.replace("-", "_"), "") for k in FILTER_KEYS}
        ctx = build_review_context(
            pm_root, review_id, cycle=cycle,
            filters={k: v for k, v in raw_filters.items() if v},
            is_leader=_is_leader(review_id),
        )
        ctx["raw_filters"] = raw_filters
        return templates.TemplateResponse(request, "changes.html", ctx)

    # -- JSON status (SSE-driven breadcrumb / lock / activity refresh) --
    @app.get("/review/{review_id}/api/status")
    def api_status(review_id: str, cycle: int | None = None):
        _require_known_review(review_id)
        # Peek at leadership rather than acquiring it: this endpoint is polled by
        # the read-only dashboard's SSE refresh, which must never claim the leader
        # lock. The walker page (GET …/changes) acquires it on load, so a real
        # walker client already holds it before its first status poll.
        ctx = build_review_context(
            pm_root, review_id, cycle=cycle, is_leader=manager.peek_leader(review_id)
        )
        keys = (
            "no_cycles", "current_cycle", "rendered_cycle", "is_current", "phase",
            "mode", "cycles", "editable", "can_apply", "is_leader", "animating",
            "audited", "breadcrumb", "hint", "convergence", "engagement",
            "body_mode", "focus",
        )
        return JSONResponse({k: ctx.get(k) for k in keys})

    # -- Apply: the only UI → session signal --
    @app.post("/review/{review_id}/apply")
    def apply(review_id: str):
        _require_known_review(review_id)
        paths, state = _require_editable(pm_root, review_id)
        if state["mode"] == "auto-run":
            raise HTTPException(status_code=409, detail="auto-run mode: apply not available")
        if not manager.leader_for(review_id).is_leader:
            raise HTTPException(status_code=409, detail="another UI owns this session")
        # Re-read the raw doc so any fields beyond the parsed view (which PR 1 may
        # add to STATE.md's schema) survive the round-trip — R8's full-state write,
        # not a 4-field patch.
        new_state = dict(md_parser.parse_state(paths.state.read_text()).raw)
        new_state["current-phase"] = "applying"
        new_state.pop("last-transition", None)  # let md_writer re-stamp
        md_writer.update_state(paths.state, new_state)
        return {"ok": True, "current-phase": "applying"}

    # -- per-entry action --
    @app.post("/review/{review_id}/change/{change_id}")
    async def change_action(review_id: str, change_id: str, request: Request):
        _require_known_review(review_id)
        paths, state = _require_editable(pm_root, review_id)
        payload = await _json_body(request)
        action = payload.get("action", "")
        # md_writer takes a blocking flock + fsync; run it off the event loop so a
        # contended write can't stall SSE delivery to every other client.
        try:
            result = await run_in_threadpool(
                _apply_change, paths, state["current-cycle"], change_id, action, payload
            )
        except KeyError:
            raise HTTPException(status_code=404, detail=f"no change {change_id!r}")
        return {"ok": True, **result}

    # -- page-level bulk-accept (default scope = current filter) --
    @app.post("/review/{review_id}/bulk-accept")
    async def bulk_accept(review_id: str, request: Request):
        _require_known_review(review_id)
        paths, state = _require_editable(pm_root, review_id)
        payload = await _json_body(request)
        filters = {k: payload.get(k) for k in FILTER_KEYS if payload.get(k)}
        # Log scope as a single string label so the interaction record is uniform.
        scope = payload.get("scope") or (
            ", ".join(f"{k}={v}" for k, v in filters.items()) if filters else "all"
        )
        # Offload the blocking flock/fsync writes (one pair per accepted block) so
        # a bulk accept can't stall the event loop's SSE delivery.
        accepted = await run_in_threadpool(
            _bulk_accept, paths, state["current-cycle"], filters, scope
        )
        return {"ok": True, "accepted": accepted}

    # -- SSE --
    @app.get("/events")
    async def events(request: Request, review: str):
        _require_known_review(review)
        queue: asyncio.Queue = asyncio.Queue()
        manager.set_loop(asyncio.get_running_loop())
        manager.subscribe(review, queue)

        async def gen():
            try:
                yield {"event": "ping", "data": "{}"}
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=15)
                    except asyncio.TimeoutError:
                        yield {"event": "keepalive", "data": "{}"}
                        continue
                    yield {"event": event["type"], "data": json.dumps(event["data"])}
            finally:
                manager.unsubscribe(review, queue)

        return EventSourceResponse(gen())

    return app


async def _json_body(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}
