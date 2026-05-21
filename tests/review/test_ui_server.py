"""Tests for the proposed-changes walker web server (PR 3).

Covers: dashboard rendering, edit round-trips in awaiting-human-review, read-only
badges + server-side lock enforcement in every other phase, current-cycle
in-progress artifact viewing, the Apply transition (and its hiding rules), cycle
navigation, SSE latency for STATE/FOCUS/RESPONSE/AUDIT changes, the activity
indicator, the 'no cycles yet' placeholder, and leader-lock election/failover.
"""

from __future__ import annotations

import json
import os
import socket
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn
import yaml
from fastapi.testclient import TestClient

from pm_core.review import md_parser
from pm_core.review.ui import server

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Fixture-building helpers
# ---------------------------------------------------------------------------


def _make_pm(tmp_path: Path, reviews: list[dict]) -> Path:
    pm = tmp_path / "pm"
    pm.mkdir()
    (pm / "project.yaml").write_text(yaml.safe_dump({"reviews": reviews}))
    return pm


def _review_dir(pm: Path, review_id: str) -> Path:
    d = pm / server.REVIEWS_SUBDIR / review_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _atomic_write(path: Path, text: str) -> None:
    """Write via temp-file + os.replace, mirroring md_writer's atomic writes.

    The directory watcher reads STATE.md on every filesystem event; a plain
    (truncate-then-write) write can be observed mid-write as an empty/partial
    file, surfacing a `state` SSE event with null fields. Production never does
    this — md_writer.update_state replaces the file atomically — so the fixtures
    must too, or the SSE tests race on a torn read.
    """
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def _write_state(d: Path, cycle: int, phase: str, mode: str = "human-reviewed") -> None:
    _atomic_write(
        d / "STATE.md",
        f"current-cycle: {cycle}\ncurrent-phase: {phase}\nmode: {mode}\n"
        "last-transition: 2026-05-20T14:32:00Z\n",
    )


def _seed_review(tmp_path, *, phase="awaiting-human-review", mode="human-reviewed",
                 cycle=3, review_id="reg", extra_cycles=(), with_response=True):
    """A registered review with a populated cycle from the shared fixtures.

    ``with_response=False`` omits the current cycle's response file so the
    in-progress (review/audit/response) body modes are exercised.
    """
    pm = _make_pm(tmp_path, [
        {"id": review_id, "name": "Regression review",
         "target": "pm/plans/plan-regression.md", "target-type": "plan", "status": "active"},
    ])
    d = _review_dir(pm, review_id)
    _write_state(d, cycle, phase, mode)
    (d / "UI_FOCUS.md").write_text((FIXTURES / "focus.md").read_text())
    if with_response:
        (d / f"REVIEW_RESPONSE_CYCLE_{cycle}.md").write_text(
            (FIXTURES / "response_cycle.md").read_text())
        (d / f"CITATION_AUDIT_CYCLE_{cycle}.md").write_text(
            (FIXTURES / "audit_cycle.md").read_text())
        (d / f"REVIEW_CYCLE_{cycle}.md").write_text("# Review cycle\n\nFindings in progress.\n")
    for c in extra_cycles:
        (d / f"REVIEW_RESPONSE_CYCLE_{c}.md").write_text(
            (FIXTURES / "response_cycle.md").read_text())
    return pm, d


def _client(pm: Path) -> TestClient:
    return TestClient(server.build_app(pm))


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _LiveServer:
    """Run the app under a real uvicorn server in a background thread.

    SSE needs a real ASGI server: ``TestClient`` buffers ``EventSourceResponse``
    and never yields incremental events, so the SSE/latency tests use this.
    """

    def __init__(self, pm: Path):
        self.port = _free_port()
        cfg = uvicorn.Config(server.build_app(pm), host="127.0.0.1",
                             port=self.port, log_level="error")
        self.server = uvicorn.Server(cfg)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def __enter__(self):
        self.thread.start()
        deadline = time.monotonic() + 10
        while not self.server.started:
            if time.monotonic() > deadline:
                raise RuntimeError("server did not start")
            time.sleep(0.02)
        return self

    def __exit__(self, *exc):
        self.server.should_exit = True
        self.thread.join(timeout=5)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


def test_dashboard_renders_multi_cycle_state(tmp_path):
    pm, _ = _seed_review(tmp_path, cycle=3, extra_cycles=(1, 2))
    with _client(pm) as c:
        r = c.get("/")
        assert r.status_code == 200
        assert "Regression review" in r.text
        assert "human-reviewed" in r.text  # mode tag
        assert "awaiting-human-review" in r.text  # phase
        assert "cycle 3" in r.text or "cycle\n" in r.text


def test_dashboard_exposes_sse_refresh_contract(tmp_path):
    # R9: the dashboard status panel updates via SSE on `state` events. The
    # client-side wiring targets a `.phase-text` span and the breadcrumb, and
    # refreshes them from /api/status, so anchor that contract server-side: the
    # markup must carry the targetable span + the SSE connect, and the status API
    # must return the breadcrumb the JS writes back into the panel.
    pm, _ = _seed_review(tmp_path, cycle=3)
    with _client(pm) as c:
        page = c.get("/").text
        assert 'class="phase-text"' in page
        assert "/events?review=" in page  # dashboard opens an EventSource
        assert "addEventListener('state'" in page
        s = c.get("/review/reg/api/status").json()
        assert s["breadcrumb"] and "Cycle 3" in s["breadcrumb"]


def test_dashboard_does_not_claim_leadership(tmp_path):
    # The read-only dashboard never renders Apply, so loading it must not acquire
    # the per-review leader flock: doing so would claim write-leadership for every
    # listed review for this process's lifetime, blocking Apply from any other
    # concurrent UI even on reviews this user never opens. Leadership is claimed
    # lazily when a walker/status/apply route touches a specific review.
    pm, _ = _seed_review(tmp_path, phase="awaiting-human-review")
    app = server.build_app(pm)
    with TestClient(app) as c:
        assert c.get("/").status_code == 200
        assert "reg" not in app.state.manager._leaders
        # An external process can still become the writer for a dashboard-only review.
        holder = server.LeaderLock(server.ReviewPaths(pm, "reg").leader_lock)
        try:
            assert holder.acquire() is True
        finally:
            holder.release()
    # Opening the walker page, by contrast, does claim leadership.
    app2 = server.build_app(pm)
    with TestClient(app2) as c:
        assert c.get("/review/reg/changes").status_code == 200
        assert "reg" in app2.state.manager._leaders

    # Polling /api/status (what the dashboard's SSE refresh does) must NOT claim
    # leadership: a read-only dashboard left open while a state event fires would
    # otherwise become the writer for every active review and block Apply on
    # walkers opened elsewhere. It only reports leadership the walker page claimed.
    app3 = server.build_app(pm)
    with TestClient(app3) as c:
        s = c.get("/review/reg/api/status").json()
        assert s["is_leader"] is False
        assert "reg" not in app3.state.manager._leaders
        # An external process can still win the writer role for that review.
        holder = server.LeaderLock(server.ReviewPaths(pm, "reg").leader_lock)
        try:
            assert holder.acquire() is True
        finally:
            holder.release()


def test_no_cycles_placeholder(tmp_path):
    pm = _make_pm(tmp_path, [
        {"id": "fresh", "name": "Fresh", "target": "x", "target-type": "topic", "status": "active"},
    ])
    _review_dir(pm, "fresh")  # dir exists, but no STATE.md
    with _client(pm) as c:
        assert "no cycles yet" in c.get("/").text
        page = c.get("/review/fresh/changes")
        assert "no cycles yet" in page.text
        assert "pm review" in page.text  # the hint


# ---------------------------------------------------------------------------
# Walker round-trip (editable) + lock enforcement (read-only)
# ---------------------------------------------------------------------------


def test_walker_round_trips_edit_when_awaiting(tmp_path):
    pm, d = _seed_review(tmp_path, phase="awaiting-human-review")
    with _client(pm) as c:
        page = c.get("/review/reg/changes")
        assert 'data-editable="true"' in page.text
        assert "Accept (a)" in page.text  # editable controls present

        r = c.post("/review/reg/change/change-1", json={"action": "accept"})
        assert r.status_code == 200
        assert r.json()["status"] == "accepted-as-suggested"

    blocks = md_parser.parse_response_blocks((d / "REVIEW_RESPONSE_CYCLE_3.md").read_text())
    b1 = next(b for b in blocks if b.id == "change-1")
    assert b1.fields["status"] == "accepted-as-suggested"
    assert b1.fields["human-verdict"] == "accept"  # the suggested verdict
    assert any(ev["action"] == "accept-as-suggested" for ev in b1.interactions)


def test_walker_edit_action_writes_fields_and_log(tmp_path):
    pm, d = _seed_review(tmp_path, phase="awaiting-human-review")
    with _client(pm) as c:
        r = c.post("/review/reg/change/change-2", json={
            "action": "edit", "after": "Revised text.",
            "human-verdict": "modify", "human-rationale": "narrower",
            "human-commentary": "see note",
        })
        assert r.status_code == 200
    blocks = md_parser.parse_response_blocks((d / "REVIEW_RESPONSE_CYCLE_3.md").read_text())
    b2 = next(b for b in blocks if b.id == "change-2")
    assert b2.fields["status"] == "edited"
    assert b2.fields["after"].strip() == "Revised text."
    assert b2.fields["human-rationale"] == "narrower"
    actions = [ev["action"] for ev in b2.interactions]
    assert "edit" in actions and "comment-added" in actions


def test_viewed_action_records_interaction_and_feeds_engagement(tmp_path):
    pm, d = _seed_review(tmp_path, phase="awaiting-human-review")
    with _client(pm) as c:
        r = c.post("/review/reg/change/change-1",
                   json={"action": "viewed", "duration-ms": 1500})
        assert r.status_code == 200
        # The view-time signal now has data to summarize.
        s = c.get("/review/reg/api/status").json()
        assert s["engagement"]["median-view-ms"] == 1500
    blocks = md_parser.parse_response_blocks((d / "REVIEW_RESPONSE_CYCLE_3.md").read_text())
    b1 = next(b for b in blocks if b.id == "change-1")
    viewed = [ev for ev in b1.interactions if ev["action"] == "viewed"]
    assert viewed and viewed[0]["duration-ms"] == 1500
    # Telemetry must not mutate the block's verdict/status.
    assert b1.fields["status"] == "pending"


def test_viewed_action_rejected_outside_awaiting(tmp_path):
    pm, _ = _seed_review(tmp_path, phase="review")
    with _client(pm) as c:
        r = c.post("/review/reg/change/change-1",
                   json={"action": "viewed", "duration-ms": 1500})
        assert r.status_code == 409


def test_reopen_action_resets_status_and_logs(tmp_path):
    # The Reopen button (rendered for any non-pending entry) round-trips a block
    # back to `pending` and logs a `reopen` interaction so a mistaken accept/skip
    # can be undone in-place.
    pm, d = _seed_review(tmp_path, phase="awaiting-human-review")
    with _client(pm) as c:
        assert c.post("/review/reg/change/change-1", json={"action": "accept"}).status_code == 200
        r = c.post("/review/reg/change/change-1", json={"action": "reopen"})
        assert r.status_code == 200
        assert r.json()["status"] == "pending"
    blocks = md_parser.parse_response_blocks((d / "REVIEW_RESPONSE_CYCLE_3.md").read_text())
    b1 = next(b for b in blocks if b.id == "change-1")
    assert b1.fields["status"] == "pending"
    actions = [ev["action"] for ev in b1.interactions]
    assert "accept-as-suggested" in actions and "reopen" in actions


@pytest.mark.parametrize("phase", ["review", "audit", "response", "applying", "complete"])
def test_walker_read_only_outside_awaiting(tmp_path, phase):
    pm, d = _seed_review(tmp_path, phase=phase)
    with _client(pm) as c:
        page = c.get("/review/reg/changes")
        assert 'data-editable="false"' in page.text
        # The mutating endpoint is rejected server-side (stale client can't bypass).
        r = c.post("/review/reg/change/change-1", json={"action": "accept"})
        assert r.status_code == 409
    # No write happened.
    blocks = md_parser.parse_response_blocks((d / "REVIEW_RESPONSE_CYCLE_3.md").read_text())
    assert all(b.fields["status"] == "pending" for b in blocks)


def test_prior_cycle_is_read_only_even_when_current_is_editable(tmp_path):
    pm, d = _seed_review(tmp_path, phase="awaiting-human-review", cycle=3, extra_cycles=(2,))
    with _client(pm) as c:
        page = c.get("/review/reg/changes?cycle=2")
        assert 'data-editable="false"' in page.text
        assert "read-only" in page.text
        # The breadcrumb names this prior cycle as read-only history, not the
        # review's live cycle-global phase (which is unrelated to cycle 2).
        assert "Cycle 2 · read-only" in page.text
        assert "Cycle 2 · awaiting-human-review" not in page.text


# ---------------------------------------------------------------------------
# In-progress current-cycle artifact viewing (read-only, always allowed)
# ---------------------------------------------------------------------------


def test_review_content_viewable_during_review_phase(tmp_path):
    pm, d = _seed_review(tmp_path, phase="review", cycle=4, with_response=False)
    (d / "REVIEW_CYCLE_4.md").write_text("# Review cycle 4\n\nLive findings here.\n")
    with _client(pm) as c:
        page = c.get("/review/reg/changes")
        assert "Live findings here." in page.text
        assert 'data-editable="false"' in page.text


def test_audit_content_viewable_during_audit_phase(tmp_path):
    pm, d = _seed_review(tmp_path, phase="audit", cycle=4, with_response=False)
    (d / "CITATION_AUDIT_CYCLE_4.md").write_text((FIXTURES / "audit_cycle.md").read_text())
    with _client(pm) as c:
        page = c.get("/review/reg/changes")
        assert "citations audited" in page.text
        assert "Andreas 2022" in page.text
        assert 'data-editable="false"' in page.text


def test_status_breadcrumb_tracks_live_audit_count(tmp_path):
    # R9: during the audit phase the breadcrumb embeds the live "K citations
    # audited" hint, and the client refreshes it from /api/status on each `audit`
    # SSE event. Anchor that contract server-side: the status breadcrumb must
    # report the count currently on disk, so it tracks the file as it grows.
    pm, d = _seed_review(tmp_path, phase="audit", cycle=4, with_response=False)
    audit = d / "CITATION_AUDIT_CYCLE_4.md"
    audit.write_text((FIXTURES / "audit_cycle.md").read_text())
    with _client(pm) as c:
        s = c.get("/review/reg/api/status").json()
        assert s["audited"] == 3
        assert "3 citations audited" in s["breadcrumb"]
        # Rewrite with a single entry; the next status read must reflect the drop,
        # proving the count is recomputed per request rather than cached.
        audit.write_text(
            "# Citation audit — cycle 4\n\n## I. §1\n\n"
            "### Solo 2024, \"Only One\"\n\n**Tier:** 1\n\n"
            "**Doc passage as currently written:**\n\n> x\n\n"
            "**What the source actually says:**\n\n> y\n\n"
            "**Verdict:** faithful\n\n"
            "**Substantive change proposed:** none required.\n"
        )
        assert len(md_parser.parse_audit_doc(audit.read_text()).entries) == 1
        s2 = c.get("/review/reg/api/status").json()
        assert s2["audited"] == 1
        assert "1 citations audited" in s2["breadcrumb"]


def test_response_in_progress_during_response_phase(tmp_path):
    pm, d = _seed_review(tmp_path, phase="response", cycle=4, with_response=False)
    # cycle 4 has no response file yet → "response in progress"
    with _client(pm) as c:
        page = c.get("/review/reg/changes")
        assert "Response in progress" in page.text


# ---------------------------------------------------------------------------
# Apply button + transition
# ---------------------------------------------------------------------------


def test_apply_writes_transition(tmp_path):
    pm, d = _seed_review(tmp_path, phase="awaiting-human-review", mode="human-reviewed")
    with _client(pm) as c:
        assert "apply-btn" in c.get("/review/reg/changes").text
        assert 'id="apply-btn" class="apply"' in c.get("/review/reg/changes").text  # visible
        r = c.post("/review/reg/apply")
        assert r.status_code == 200
    st = md_parser.parse_state((d / "STATE.md").read_text())
    assert st.current_phase == "applying"
    assert st.current_cycle == 3  # preserved
    assert st.mode == "human-reviewed"  # preserved


def test_apply_preserves_extra_state_fields(tmp_path):
    pm, d = _seed_review(tmp_path, phase="awaiting-human-review")
    # A field outside the 4-field parsed view (a shape PR 1 may add later).
    (d / "STATE.md").write_text(
        "current-cycle: 3\ncurrent-phase: awaiting-human-review\n"
        "mode: human-reviewed\naudit-round: 2\n"
        "last-transition: 2026-05-20T14:32:00Z\n"
    )
    with _client(pm) as c:
        assert c.post("/review/reg/apply").status_code == 200
    raw = md_parser.parse_state((d / "STATE.md").read_text()).raw
    assert raw["current-phase"] == "applying"
    assert raw["audit-round"] == 2  # not dropped


def test_apply_hidden_outside_awaiting(tmp_path):
    pm, _ = _seed_review(tmp_path, phase="review")
    with _client(pm) as c:
        page = c.get("/review/reg/changes")
        assert "apply hidden" in page.text or 'class="apply hidden"' in page.text
        assert c.post("/review/reg/apply").status_code == 409


def test_apply_hidden_in_auto_run_mode(tmp_path):
    pm, _ = _seed_review(tmp_path, phase="awaiting-human-review", mode="auto-run")
    with _client(pm) as c:
        page = c.get("/review/reg/changes")
        assert 'class="apply hidden"' in page.text
        assert c.post("/review/reg/apply").status_code == 409


# ---------------------------------------------------------------------------
# Cycle navigation
# ---------------------------------------------------------------------------


def test_cycle_selector_navigates(tmp_path):
    pm, d = _seed_review(tmp_path, cycle=3, extra_cycles=(2,))
    # Give cycle 2 a distinct change set.
    (d / "REVIEW_RESPONSE_CYCLE_2.md").write_text(
        "# cycle 2\n<!-- proposed-change\nid: change-c2\nprovenance: reviewer-comment\n"
        "before: |\n  old c2\nafter: |\n  new c2\nsuggested-verdict: accept\n"
        "status: pending\ninteractions: []\n-->\n"
    )
    with _client(pm) as c:
        page3 = c.get("/review/reg/changes?cycle=3")
        page2 = c.get("/review/reg/changes?cycle=2")
        assert "change-1" in page3.text and "change-c2" not in page3.text
        assert "change-c2" in page2.text and "change-1" not in page2.text
        # Selector lists both cycles.
        assert 'value="2"' in page3.text and 'value="3"' in page3.text


def test_status_api_reports_available_cycles(tmp_path):
    pm, _ = _seed_review(tmp_path, cycle=3, extra_cycles=(1, 2))
    with _client(pm) as c:
        # Load the walker page first (as a real client does) so this process
        # claims the leader lock; api_status only peeks at leadership.
        assert c.get("/review/reg/changes").status_code == 200
        s = c.get("/review/reg/api/status").json()
        assert s["cycles"] == [3, 2, 1]
        assert s["editable"] is True
        assert s["can_apply"] is True
        assert s["is_leader"] is True


# ---------------------------------------------------------------------------
# Filters + bulk-accept
# ---------------------------------------------------------------------------


def test_filter_by_provenance(tmp_path):
    pm, _ = _seed_review(tmp_path)
    with _client(pm) as c:
        page = c.get("/review/reg/changes?provenance=audit-entry")
        assert "change-2" in page.text and "change-1" not in page.text


def test_engagement_signals_span_whole_cycle_not_filtered_set(tmp_path):
    # Engagement is "across the rendered cycle's response blocks" (R4), so it must
    # reflect every block even when the displayed set is narrowed by a filter.
    pm, _ = _seed_review(tmp_path)
    ctx_all = server.build_review_context(pm, "reg")
    ctx_filtered = server.build_review_context(
        pm, "reg", filters={"provenance": "reviewer-comment"})
    # The filter narrows the rendered blocks…
    assert len(ctx_filtered["blocks"]) == 1
    assert len(ctx_all["blocks"]) == 2
    # …but the suggester-confidence distribution still covers both blocks.
    assert ctx_filtered["engagement"]["suggester-confidence"] == \
        ctx_all["engagement"]["suggester-confidence"]
    assert sum(ctx_filtered["engagement"]["suggester-confidence"].values()) == 2


def test_bulk_accept_current_filter(tmp_path):
    pm, d = _seed_review(tmp_path, phase="awaiting-human-review")
    with _client(pm) as c:
        r = c.post("/review/reg/bulk-accept", json={"provenance": "reviewer-comment"})
        assert r.json()["accepted"] == 1
    blocks = {b.id: b for b in md_parser.parse_response_blocks(
        (d / "REVIEW_RESPONSE_CYCLE_3.md").read_text())}
    assert blocks["change-1"].fields["status"] == "accepted-as-suggested"
    assert blocks["change-2"].fields["status"] == "pending"  # filtered out
    assert any(ev["action"] == "bulk-accept" for ev in blocks["change-1"].interactions)


# ---------------------------------------------------------------------------
# Activity indicator
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("phase,animating", [
    ("review", True), ("audit", True), ("response", True), ("applying", True),
    ("awaiting-human-review", False), ("complete", False),
])
def test_activity_indicator_state(tmp_path, phase, animating):
    pm, _ = _seed_review(tmp_path, phase=phase)
    with _client(pm) as c:
        s = c.get("/review/reg/api/status").json()
        assert s["animating"] is animating


# ---------------------------------------------------------------------------
# SSE latency
# ---------------------------------------------------------------------------


def _next_event(lines_iter, want_type, deadline):
    """Pull SSE lines until an event of `want_type` appears; return its data dict."""
    event = None
    for raw in lines_iter:
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out waiting for {want_type}")
        line = raw.decode() if isinstance(raw, bytes) else raw
        if line.startswith("event:"):
            event = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            data = line.split(":", 1)[1].strip()
            if event == want_type:
                return json.loads(data)
    raise AssertionError(f"stream ended before {want_type}")


@pytest.mark.parametrize("trigger,want", [
    ("state", "state"),
    ("focus", "focus"),
    ("response", "response"),
    ("audit", "audit"),
])
def test_sse_pushes_change_under_200ms(tmp_path, trigger, want):
    phase = {"response": "response", "audit": "audit"}.get(trigger, "awaiting-human-review")
    pm, d = _seed_review(tmp_path, phase=phase, cycle=3)
    with _LiveServer(pm) as srv:
        with httpx.stream("GET", f"{srv.base}/events?review=reg", timeout=10) as resp:
            lines = resp.iter_lines()
            # Drain the initial ping so the subscription + watch are live.
            _next_event(lines, "ping", time.monotonic() + 5)
            time.sleep(0.1)  # let the watchdog schedule settle

            t0 = time.monotonic()
            if trigger == "state":
                _write_state(d, 3, "applying")
            elif trigger == "focus":
                _atomic_write(
                    d / "UI_FOCUS.md",
                    "view: changes\ncycle: 3\ntarget: change-1\n"
                    "timestamp: 2026-05-20T16:00:00Z\n")
            elif trigger == "response":
                (d / "REVIEW_RESPONSE_CYCLE_3.md").write_text(
                    (FIXTURES / "response_cycle.md").read_text() + "\n<!-- extra -->\n")
            elif trigger == "audit":
                (d / "CITATION_AUDIT_CYCLE_3.md").write_text(
                    (FIXTURES / "audit_cycle.md").read_text())

            data = _next_event(lines, want, time.monotonic() + 5)
            elapsed = time.monotonic() - t0
            assert elapsed < 0.2, f"{want} took {elapsed*1000:.0f}ms"
            if want == "state":
                assert data["current-phase"] == "applying"
            if want == "audit":
                assert data["cycle"] == 3 and "audited" in data


# ---------------------------------------------------------------------------
# Leader lock — multi-UI state ownership + failover
# ---------------------------------------------------------------------------


def test_leader_lock_elects_one_writer(tmp_path):
    lockfile = tmp_path / "STATE.md.leader"
    a = server.LeaderLock(lockfile)
    b = server.LeaderLock(lockfile)
    assert a.acquire() is True
    assert b.acquire() is False  # second sees it owned → Apply disabled
    try:
        # Failover: when the leader releases, the follower's retry succeeds.
        a.release()
        assert b.acquire() is True
    finally:
        a.release()
        b.release()


def test_leader_event_pushed_on_takeover(tmp_path):
    # R10: when the leader exits, a follower's periodic flock retry succeeds and an
    # SSE `leader` event flips Apply on its clients. Drive that path end-to-end:
    # hold the lock externally so the server starts as a follower, then release it
    # and assert the server pushes the `leader` event over SSE within a couple of
    # leader_loop intervals (default 2s).
    pm, _ = _seed_review(tmp_path, phase="awaiting-human-review")
    holder = server.LeaderLock(server.ReviewPaths(pm, "reg").leader_lock)
    assert holder.acquire() is True
    try:
        with _LiveServer(pm) as srv:
            # Load the walker page so the server builds its (follower) LeaderLock
            # for "reg" — leader_loop only retries reviews it already tracks, and
            # api_status now only peeks (never acquires), so it wouldn't register
            # the lock on its own.
            assert httpx.get(f"{srv.base}/review/reg/changes").status_code == 200
            s = httpx.get(f"{srv.base}/review/reg/api/status").json()
            assert s["is_leader"] is False
            with httpx.stream("GET", f"{srv.base}/events?review=reg", timeout=10) as resp:
                lines = resp.iter_lines()
                _next_event(lines, "ping", time.monotonic() + 5)
                holder.release()  # leader exits → follower's next retry takes over
                data = _next_event(lines, "leader", time.monotonic() + 8)
                assert data["is_leader"] is True
    finally:
        holder.release()


def test_unknown_review_is_404(tmp_path):
    pm, _ = _seed_review(tmp_path)
    with _client(pm) as c:
        # Ids absent from the registry never reach a watch / leader lock.
        assert c.get("/review/nope/changes").status_code == 404
        assert c.get("/review/nope/api/status").status_code == 404
        assert c.post("/review/nope/apply").status_code == 404


def test_unknown_change_id_is_404(tmp_path):
    pm, _ = _seed_review(tmp_path, phase="awaiting-human-review")
    with _client(pm) as c:
        r = c.post("/review/reg/change/no-such-change", json={"action": "accept"})
        assert r.status_code == 404


def test_non_leader_cannot_apply(tmp_path):
    pm, d = _seed_review(tmp_path, phase="awaiting-human-review")
    # Hold the leader lock from outside so the server process is a follower.
    holder = server.LeaderLock(server.ReviewPaths(pm, "reg").leader_lock)
    assert holder.acquire() is True
    try:
        with _client(pm) as c:
            s = c.get("/review/reg/api/status").json()
            assert s["is_leader"] is False
            assert s["can_apply"] is False  # editable but not the writer
            assert c.post("/review/reg/apply").status_code == 409
    finally:
        holder.release()
