"""Tests for bounded missing-output recovery in verdict pollers.

Covers the shared machinery in ``pm_core.loop_shared`` and its wiring in
the review loop, watcher loop, and QA pollers (pr-6566901).
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from pm_core import loop_shared
from pm_core.loop_shared import (
    MissingOutputRecovery,
    VerdictRecoveryExhausted,
    VERDICT_NO_VERDICT,
    build_block_outcome_request,
    build_block_resume_request,
    build_outcome_request,
    build_resume_request,
)


# ---------------------------------------------------------------------------
# Transcript helpers
# ---------------------------------------------------------------------------

def _hit(verdict: str):
    """Wrap a verdict string as the ``VerdictHit`` a transcript scan returns.

    The QA tick loop scans with :func:`find_verdict_turn` (task-scoped, see
    pr-8efa789), so the fake scans below patch that helper rather than the
    string-returning wrapper.  ``text`` is the verdict itself: it carries no
    ``Reason:`` line, so no reason is recorded.
    """
    from pm_core.verdict_transcript import VerdictHit

    return VerdictHit(verdict=verdict, text=verdict, turn_id="turn-1",
                      timestamp="2026-01-01T00:00:00Z", line_index=0)


def _as_hits(fake_scan):
    """Adapt a verdict-string fake to ``find_verdict_turn``'s hit/None."""
    def _wrapped(_path, _verdicts):
        verdict = fake_scan(_path, _verdicts)
        return _hit(verdict) if verdict else None
    return _wrapped


def _write_transcript(path: Path, turns: list[tuple[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for role, text in turns:
        if role == "user":
            msg = {"role": "user", "content": text}
        else:
            msg = {"role": "assistant",
                   "content": [{"type": "text", "text": text}]}
        lines.append(json.dumps({"type": role, "message": msg}))
    path.write_text("\n".join(lines) + "\n")


def _transcript_with_assistant(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "t.jsonl"
    _write_transcript(p, [("user", "do the task"), ("assistant", text)])
    return p


def _transcript_without_assistant(tmp_path: Path) -> Path:
    p = tmp_path / "t.jsonl"
    _write_transcript(p, [("user", "do the task")])
    return p


def _recovery(tmp_path, *, max_attempts=3, settle=0.0,
              response_timeout=3600.0, **kw):
    sent: list[str] = []
    rec = MissingOutputRecovery(
        session_id="sid-1",
        pane_id="%1",
        verdicts=("PASS", "NEEDS_WORK", "INPUT_REQUIRED"),
        send=sent.append,
        max_attempts=max_attempts,
        settle_seconds=settle,
        response_timeout=response_timeout,
        log_prefix="test",
        **kw,
    )
    return rec, sent


# ---------------------------------------------------------------------------
# Message builders
# ---------------------------------------------------------------------------

class TestRecoveryMessages:
    def test_outcome_request_lists_outcomes_but_asserts_none(self):
        msg = build_outcome_request(("PASS", "NEEDS_WORK", "INPUT_REQUIRED"))
        assert "PASS" in msg and "NEEDS_WORK" in msg
        assert "alone on its own line" in msg
        # It must not assert a specific verdict itself.
        assert not msg.rstrip().endswith("PASS")
        assert "Do not redo work" in msg

    def test_resume_request_preserves_work(self):
        msg = build_resume_request()
        assert "Resume the same task" in msg
        assert "partial edits" in msg
        assert "do not restart completed work" in msg

    def test_block_outcome_request_names_both_blocks(self):
        msg = build_block_outcome_request((
            ("REFINED_STEPS_START", "REFINED_STEPS_END"),
            ("REFINER_REJECT_START", "REFINER_REJECT_END"),
        ))
        assert "REFINED_STEPS_START ... REFINED_STEPS_END" in msg
        assert "REFINER_REJECT_START ... REFINER_REJECT_END" in msg

    def test_block_resume_request_names_blocks(self):
        msg = build_block_resume_request((("QA_PLAN_START", "QA_PLAN_END"),))
        assert "Resume the same task" in msg
        assert "QA_PLAN_START ... QA_PLAN_END" in msg
        assert "partial edits" in msg

    def test_every_recovery_request_is_a_single_line(self):
        """Every built request must fit one ``tmux send-keys`` line.

        A newline in a recovery message would submit partial input: the
        first line goes to the session, the rest sits in its input buffer
        as queued text.  The spec documents this constraint, so guard the
        builders (and the role-specific verifier requests) against a future
        edit that wraps them.
        """
        from pm_core.qa_loop import (
            _VERIFIER_OUTCOME_REQUEST,
            _VERIFIER_RESUME_REQUEST,
        )

        requests = {
            "outcome": build_outcome_request(
                ("PASS", "NEEDS_WORK", "INPUT_REQUIRED")),
            "resume": build_resume_request(),
            "block_outcome": build_block_outcome_request((
                ("REFINED_STEPS_START", "REFINED_STEPS_END"),
                ("REFINER_REJECT_START", "REFINER_REJECT_END"),
            )),
            "block_resume": build_block_resume_request(
                (("QA_PLAN_START", "QA_PLAN_END"),)),
            "verifier_outcome": _VERIFIER_OUTCOME_REQUEST,
            "verifier_resume": _VERIFIER_RESUME_REQUEST,
        }
        for name, msg in requests.items():
            assert msg, name
            assert "\n" not in msg and "\r" not in msg, name
            assert msg == msg.strip(), name


# ---------------------------------------------------------------------------
# MissingOutputRecovery
# ---------------------------------------------------------------------------

class TestMissingOutputRecovery:
    def test_completed_turn_without_verdict_asks_for_outcome(self, tmp_path):
        rec, sent = _recovery(tmp_path, max_attempts=2)
        transcript = _transcript_with_assistant(
            tmp_path, "NEEDS_WORK — explanation instead of a keyword")

        result = rec.handle(str(transcript), ev_ts=1.0)

        assert result.status == "nudged"
        assert rec.attempts == 1
        assert rec.last_kind == "no_verdict"
        assert len(sent) == 1
        # Only the agent's own outcome is requested; the explanation is
        # never turned into a verdict.
        assert "standalone outcome" in sent[0]
        assert "NEEDS_WORK — explanation" not in sent[0]

    def test_empty_turn_resumes_same_task(self, tmp_path):
        rec, sent = _recovery(tmp_path)
        transcript = _transcript_without_assistant(tmp_path)

        result = rec.handle(str(transcript), ev_ts=1.0)

        assert result.status == "nudged"
        assert rec.last_kind == "no_output"
        assert "Resume the same task" in sent[0]

    @pytest.mark.parametrize("error", [
        "API Error: Connection lost",
        "Request failed: network error",
        "Error: socket hang up",
    ])
    def test_provider_error_resumes_instead_of_asking_for_outcome(
            self, tmp_path, error):
        """A transport failure is resumed, not asked to re-emit an outcome."""
        rec, sent = _recovery(tmp_path)
        transcript = _transcript_with_assistant(tmp_path, error)

        result = rec.handle(str(transcript), ev_ts=1.0)

        assert result.status == "nudged"
        assert rec.last_kind == "no_output"
        assert "Resume the same task" in sent[0]

    def test_review_discussing_network_errors_is_not_a_provider_error(
            self, tmp_path):
        """Line-leading matching must not swallow legitimate review prose."""
        rec, sent = _recovery(tmp_path)
        transcript = _transcript_with_assistant(
            tmp_path,
            "The retry logic mishandles a dropped socket.\n"
            "Please fix the connection reset handling before merging.")

        rec.handle(str(transcript), ev_ts=1.0)

        assert rec.last_kind == "no_verdict"
        assert "standalone outcome" in sent[0]

    def test_quoted_provider_error_among_findings_is_not_no_output(
            self, tmp_path):
        """Only a turn that *ended on* the error is a transport failure.

        A completed review that quotes a log excerpt is asking for its own
        outcome, not to resume work it already finished.
        """
        rec, sent = _recovery(tmp_path)
        transcript = _transcript_with_assistant(
            tmp_path,
            "The worker crashed with:\n"
            "API Error: Connection lost\n"
            "so the retry path never ran. Please handle this case.")

        rec.handle(str(transcript), ev_ts=1.0)

        assert rec.last_kind == "no_verdict"
        assert "standalone outcome" in sent[0]

    def test_retry_prompt_overrides_resume_request(self, tmp_path):
        rec, sent = _recovery(tmp_path, resume_request="ORIGINAL PROMPT")
        transcript = _transcript_without_assistant(tmp_path)

        rec.handle(str(transcript), ev_ts=1.0)

        assert sent == ["ORIGINAL PROMPT"]

    def test_multi_line_retry_prompt_is_collapsed_to_one_line(self, tmp_path):
        """The ``retry_prompt`` knob accepts the original prompt verbatim.

        Original prompts are multi-line, and a request is delivered through
        ``tmux send-keys`` — which submits on a newline.  Sending it
        unchanged would deliver only the first line and leave the rest as
        typed input in the session, so the tracker collapses it.
        """
        rec, sent = _recovery(
            tmp_path,
            resume_request="Review this PR.\n\nRun the tests.\n  Then stop.",
        )
        transcript = _transcript_without_assistant(tmp_path)

        rec.handle(str(transcript), ev_ts=1.0)

        assert sent == ["Review this PR. Run the tests. Then stop."]

    def test_empty_request_falls_back_to_the_default_wording(self, tmp_path):
        """An empty request would press Enter on a queued user draft."""
        rec, sent = _recovery(tmp_path, outcome_request="")
        transcript = _transcript_with_assistant(tmp_path, "still thinking")

        rec.handle(str(transcript), ev_ts=1.0)

        assert len(sent) == 1
        assert "standalone outcome" in sent[0]

    def test_exhausts_after_max_attempts(self, tmp_path):
        rec, sent = _recovery(tmp_path, max_attempts=2)
        transcript = _transcript_with_assistant(tmp_path, "still thinking")

        assert rec.handle(str(transcript), ev_ts=1.0).status == "nudged"
        assert rec.handle(str(transcript), ev_ts=2.0).status == "nudged"
        with pytest.raises(VerdictRecoveryExhausted) as exc:
            rec.handle(str(transcript), ev_ts=3.0)

        assert exc.value.attempts == 2
        assert exc.value.reason == "no_verdict"
        assert len(sent) == 2
        assert "produced no expected outcome" in str(exc.value)

    def test_newer_turn_defers_and_resets(self, tmp_path):
        """A genuinely new turn during settle defers and resets the budget."""
        rec, sent = _recovery(tmp_path, max_attempts=2, settle=5.0)
        transcript = _transcript_with_assistant(tmp_path, "still thinking")
        newer = {"event_type": "idle_prompt", "timestamp": 9.0}

        def wait_and_advance(_timeout, _ts):
            # The provider-native retry produced a new (still verdictless)
            # turn while we waited.
            _write_transcript(transcript, [("user", "review"),
                                           ("assistant", "retried, no verdict")])
            return newer

        result = rec.handle(str(transcript), ev_ts=1.0,
                            wait_for_newer=wait_and_advance)

        assert result.status == "deferred"
        assert result.event is newer
        assert rec.attempts == 0
        assert rec.deferrals == 0
        assert sent == []

        # A turn with no newer event afterwards is nudged normally.
        result = rec.handle(str(transcript), ev_ts=9.0,
                            wait_for_newer=lambda t, ts: None)
        assert result.status == "nudged"
        assert rec.attempts == 1

    def test_hook_refresh_does_not_reset_the_budget(self, tmp_path):
        """A re-announced idle event for the *same* turn is not new activity.

        FakeClaude refreshes ``idle_prompt`` every couple of seconds while
        held open.  Treating that as a native retry would defer forever and
        reintroduce the hang this machinery exists to prevent.
        """
        rec, sent = _recovery(tmp_path, max_attempts=2, settle=5.0)
        transcript = _transcript_with_assistant(tmp_path, "still thinking")
        newer = {"event_type": "idle_prompt", "timestamp": 9.0}

        result = rec.handle(str(transcript), ev_ts=1.0,
                            wait_for_newer=lambda t, ts: newer)

        assert result.status == "deferred"
        assert rec.deferrals == 1
        assert sent == []

    def test_refresh_after_a_new_turn_does_not_reset_the_budget(self, tmp_path):
        """A refresh must not reset the budget just because the poller moved on.

        The poller hands ``handle`` a turn recovery has not seen before, so
        the transcript is newer than recovery's previous decision.  If a hook
        refresh of *that* turn lands during the settle, resetting here would
        zero both the nudge budget and the deferral count and let the loop
        defer forever without ever nudging or exhausting.
        """
        rec, sent = _recovery(tmp_path, max_attempts=3, settle=5.0)
        transcript = _transcript_with_assistant(tmp_path, "turn one")
        assert rec.handle(str(transcript), ev_ts=1.0,
                          wait_for_newer=lambda t, ts: None).status == "nudged"
        assert rec.attempts == 1
        # The session answers with a new (still verdictless) turn, which the
        # poller is now deciding about ...
        _write_transcript(transcript, [("user", "review"),
                                       ("assistant", "turn two")])
        newer = {"event_type": "idle_prompt", "timestamp": 9.0}

        # ... and a hook refresh of that turn lands during the settle.
        result = rec.handle(str(transcript), ev_ts=2.0,
                            wait_for_newer=lambda t, ts: newer)

        assert result.status == "deferred"
        assert rec.attempts == 1, "a refresh must not reset the nudge budget"
        assert rec.deferrals == 1
        assert len(sent) == 1  # only the nudge from the first handle

    def test_repeated_hook_refresh_exhausts_without_nudging(self, tmp_path):
        """An endlessly refreshing session is bounded, not hung."""
        rec, sent = _recovery(tmp_path, max_attempts=3, settle=5.0,
                              max_deferrals=2)
        transcript = _transcript_with_assistant(tmp_path, "still thinking")

        def always_newer(_timeout, ts):
            return {"event_type": "idle_prompt", "timestamp": ts + 1}

        assert rec.handle(str(transcript), ev_ts=1.0,
                          wait_for_newer=always_newer).status == "deferred"
        assert rec.handle(str(transcript), ev_ts=2.0,
                          wait_for_newer=always_newer).status == "deferred"
        with pytest.raises(VerdictRecoveryExhausted) as exc:
            rec.handle(str(transcript), ev_ts=3.0,
                       wait_for_newer=always_newer)

        assert exc.value.reason == "no_progress"
        # The session was never nudged — it is alive but not making progress.
        assert sent == []

    def test_deferral_budget_is_consecutive_not_lifetime(self, tmp_path):
        """A nudge restarts the deferral budget.

        ``max_deferrals`` bounds *consecutive* hook refreshes of one turn.
        Accumulating the count over the tracker's lifetime would retire a
        session that answered every earlier nudge with ``no_progress`` for a
        handful of refreshes spread across many turns.
        """
        rec, sent = _recovery(tmp_path, max_attempts=3, settle=5.0,
                              max_deferrals=2)
        transcript = _transcript_with_assistant(tmp_path, "still thinking")

        def always_newer(_timeout, ts):
            return {"event_type": "idle_prompt", "timestamp": ts + 1}

        assert rec.handle(str(transcript), ev_ts=1.0,
                          wait_for_newer=always_newer).status == "deferred"
        assert rec.handle(str(transcript), ev_ts=2.0,
                          wait_for_newer=always_newer).status == "deferred"
        assert rec.deferrals == 2

        # A settle window with no newer turn nudges the session ...
        assert rec.handle(str(transcript), ev_ts=3.0,
                          wait_for_newer=lambda t, ts: None).status == "nudged"
        assert rec.attempts == 1
        assert rec.deferrals == 0, "a nudge must start a fresh deferral budget"

        # ... so later refreshes are tolerated again instead of exhausting
        # with no_progress on the very next one.
        assert rec.handle(str(transcript), ev_ts=4.0,
                          wait_for_newer=always_newer).status == "deferred"
        assert rec.handle(str(transcript), ev_ts=5.0,
                          wait_for_newer=always_newer).status == "deferred"
        assert len(sent) == 1

    def test_newer_non_idle_event_is_not_a_new_turn(
            self, tmp_path, monkeypatch):
        """A Stop/permission write must not look like a newer turn.

        The hook file holds only the latest event, so a ``Stop`` write for
        the same turn makes the non-blocking read see a newer event.  It is
        not a turn boundary: recovery must nudge (matching the blocking
        ``wait_for_event(event_types={"idle_prompt"})`` path) rather than
        defer, since the tick loop only re-opens a no-verdict episode on a
        fresh ``idle_prompt``.
        """
        from pm_core import hook_events

        rec, sent = _recovery(tmp_path, max_attempts=2, settle=5.0)
        transcript = _transcript_with_assistant(tmp_path, "still thinking")
        monkeypatch.setattr(hook_events, "read_event", lambda _sid: {
            "event_type": "Stop", "timestamp": 99.0, "session_id": "sid-1",
        })

        result = rec.handle(str(transcript), ev_ts=1.0)

        assert result.status == "nudged"
        assert rec.attempts == 1
        assert rec.deferrals == 0
        assert len(sent) == 1

    def test_newer_idle_event_is_a_new_turn(self, tmp_path, monkeypatch):
        """The non-blocking read still defers on a genuinely newer idle."""
        from pm_core import hook_events

        rec, sent = _recovery(tmp_path, max_attempts=2, settle=5.0)
        transcript = _transcript_with_assistant(tmp_path, "still thinking")
        newer = {"event_type": "idle_prompt", "timestamp": 99.0,
                 "session_id": "sid-1"}
        monkeypatch.setattr(hook_events, "read_event", lambda _sid: newer)

        result = rec.handle(str(transcript), ev_ts=1.0)

        assert result.status == "deferred"
        assert result.event is newer
        assert sent == []

    def test_stop_check_during_settle_does_not_nudge(self, tmp_path):
        """A stop requested while waiting for a newer turn must not nudge."""
        rec, sent = _recovery(tmp_path, max_attempts=3, settle=5.0)
        transcript = _transcript_with_assistant(tmp_path, "still thinking")

        result = rec.handle(str(transcript), ev_ts=1.0,
                            wait_for_newer=lambda t, ts: None,
                            stop_check=lambda: True)

        assert result.status == "stopped"
        assert sent == []
        assert rec.attempts == 0

    def test_send_failure_is_logged_not_raised(self, tmp_path):
        def boom(_msg):
            raise RuntimeError("pane gone")

        rec = MissingOutputRecovery(
            session_id="sid", pane_id="%1", verdicts=("PASS",),
            send=boom, max_attempts=1, settle_seconds=0,
            response_timeout=0,
        )
        transcript = _transcript_with_assistant(tmp_path, "no verdict")
        assert rec.handle(str(transcript), ev_ts=1.0).status == "nudged"
        assert rec.attempts == 1

    def test_completed_outcome_during_settle_is_not_nudged(self, tmp_path):
        """A verdict flushed after the idle hook fired is never nudged.

        The caller's verdict scan runs at the idle event, but the transcript
        write can land during the settle window.  Recovery must re-check
        before sending an outcome request, or it would ask a completed
        session to re-emit work it already finished.
        """
        rec, sent = _recovery(tmp_path, max_attempts=2, settle=5.0)
        transcript = _transcript_with_assistant(tmp_path, "still thinking")
        found = {"v": False}

        def wait_and_complete(_timeout, _ts):
            _write_transcript(transcript, [("user", "review"),
                                           ("assistant", "PASS")])
            found["v"] = True
            return None

        result = rec.handle(str(transcript), ev_ts=1.0,
                            wait_for_newer=wait_and_complete,
                            verdict_check=lambda: found["v"])

        assert result.status == "completed"
        assert sent == []
        assert rec.attempts == 0

    def test_check_response_raises_after_timeout(self, tmp_path):
        rec, _ = _recovery(tmp_path, response_timeout=0.01)
        transcript = _transcript_with_assistant(tmp_path, "no verdict")
        rec.handle(str(transcript), ev_ts=1.0)
        rec._last_nudge_ts = time.monotonic() - 1
        with pytest.raises(VerdictRecoveryExhausted) as exc:
            rec.check_response()
        assert exc.value.reason == "no_response"

    def test_check_response_disabled_with_zero(self, tmp_path):
        rec, _ = _recovery(tmp_path, response_timeout=0)
        transcript = _transcript_with_assistant(tmp_path, "no verdict")
        rec.handle(str(transcript), ev_ts=1.0)
        rec._last_nudge_ts = time.monotonic() - 10_000
        rec.check_response()  # no raise


# ---------------------------------------------------------------------------
# poll_for_verdict integration
# ---------------------------------------------------------------------------

def _uuid_transcript(tmp_path: Path) -> tuple[Path, Path]:
    """Create a UUID-named target + symlink, like a real transcript link."""
    sid = str(uuid.uuid4())
    target = tmp_path / f"{sid}.jsonl"
    link = tmp_path / "t.jsonl"
    link.symlink_to(target)
    return link, target


def _patch_poll_env(monkeypatch, wait_script):
    """Patch tmux/hook layers for poll_for_verdict tests.

    *wait_script* is a list of values returned by successive
    ``hook_events.wait_for_event`` calls (``None`` = timeout).  Once
    exhausted, it keeps returning ``None``.
    """
    from pm_core import hook_events, tmux

    calls = {"n": 0}

    def fake_wait(*_a, **_kw):
        i = calls["n"]
        calls["n"] += 1
        return wait_script[i] if i < len(wait_script) else None

    monkeypatch.setattr(hook_events, "wait_for_event", fake_wait)
    monkeypatch.setattr(tmux, "pane_exists", lambda _p: True)
    monkeypatch.setattr(loop_shared, "recovery_settle_seconds", lambda: 5.0)
    monkeypatch.setattr(loop_shared, "recovery_max_attempts", lambda: 2)
    monkeypatch.setattr(loop_shared, "recovery_response_timeout", lambda: 3600.0)
    return calls


def _idle(ts: float) -> dict:
    return {"event_type": "idle_prompt", "timestamp": ts}


class TestPollForVerdictRecovery:
    def test_recovers_after_outcome_request(self, tmp_path, monkeypatch):
        link, target = _uuid_transcript(tmp_path)
        _write_transcript(target, [("user", "review"),
                                   ("assistant", "NEEDS_WORK — see notes")])
        # idle, settle-timeout, idle (now with the repaired verdict)
        _patch_poll_env(monkeypatch, [_idle(1), None, _idle(2)])
        sent: list[str] = []

        def send(msg: str) -> None:
            sent.append(msg)
            _write_transcript(target, [("user", "review"),
                                       ("assistant", "NEEDS_WORK")])

        content = loop_shared.poll_for_verdict(
            "%1", str(link), ("PASS", "NEEDS_WORK", "INPUT_REQUIRED"),
            grace_period=0, wait_timeout=0.01, send=send,
            log_prefix="test",
        )
        assert "NEEDS_WORK" in content
        assert len(sent) == 1

    def test_retry_prompt_is_sent_instead_of_the_resume_request(
            self, tmp_path, monkeypatch):
        """``retry_prompt`` is the configurable "re-send the original prompt" knob.

        It must reach the session through the poller, not only through the
        tracker: re-sending the original prompt is an acceptance criterion.
        """
        link, target = _uuid_transcript(tmp_path)
        # An empty turn (no assistant text) classifies as no_output.
        _write_transcript(target, [("user", "review")])
        _patch_poll_env(monkeypatch, [_idle(1), None, _idle(2)])
        sent: list[str] = []

        def send(msg: str) -> None:
            sent.append(msg)
            _write_transcript(target, [("user", "review"),
                                       ("assistant", "PASS")])

        content = loop_shared.poll_for_verdict(
            "%1", str(link), ("PASS",),
            grace_period=0, wait_timeout=0.01, send=send,
            retry_prompt="ORIGINAL PROMPT", log_prefix="test",
        )
        assert "PASS" in content
        assert sent == ["ORIGINAL PROMPT"]

    def test_exhausts_without_verdict(self, tmp_path, monkeypatch):
        link, target = _uuid_transcript(tmp_path)
        _write_transcript(target, [("user", "review"),
                                   ("assistant", "still reading")])
        # Two nudges, then the third idle exceeds max_missing.
        _patch_poll_env(monkeypatch,
                        [_idle(1), None, _idle(2), None, _idle(3)])
        sent: list[str] = []

        with pytest.raises(VerdictRecoveryExhausted) as exc:
            loop_shared.poll_for_verdict(
                "%1", str(link), ("PASS",),
                grace_period=0, wait_timeout=0.01, send=sent.append,
                log_prefix="test",
            )
        assert exc.value.attempts == 2
        assert len(sent) == 2

    def test_repeated_idle_refresh_exhausts_instead_of_hanging(
            self, tmp_path, monkeypatch):
        """A session that keeps refreshing idle_prompt cannot defer forever.

        This is the FakeClaude shape (hook re-emitted every couple of
        seconds for the same turn): without a deferral bound the poller
        would spin forever — the original bug.
        """
        link, target = _uuid_transcript(tmp_path)
        _write_transcript(target, [("user", "review"),
                                   ("assistant", "still reading")])
        clock = {"ts": 1.0}
        calls = {"n": 0}

        def always_fresh(*_a, **_kw):
            calls["n"] += 1
            assert calls["n"] < 200, "poll deferred without bound"
            clock["ts"] += 2.0
            return _idle(clock["ts"])

        from pm_core import hook_events, tmux
        monkeypatch.setattr(hook_events, "wait_for_event", always_fresh)
        monkeypatch.setattr(tmux, "pane_exists", lambda _p: True)
        monkeypatch.setattr(loop_shared, "recovery_settle_seconds",
                            lambda: 5.0)
        monkeypatch.setattr(loop_shared, "recovery_max_attempts", lambda: 3)
        monkeypatch.setattr(loop_shared, "recovery_response_timeout",
                            lambda: 3600.0)
        sent: list[str] = []

        with pytest.raises(VerdictRecoveryExhausted) as exc:
            loop_shared.poll_for_verdict(
                "%1", str(link), ("PASS",),
                grace_period=0, wait_timeout=0.01, send=sent.append,
                log_prefix="test",
            )
        assert exc.value.reason == "no_progress"
        assert sent == []

    def test_verdict_flushed_during_settle_is_returned(self, tmp_path,
                                                       monkeypatch):
        """A verdict written during the settle window is returned, not nudged.

        Guards the idle-hook/transcript-write race: the first scan runs at
        the hook event and can miss a verdict that lands a moment later.
        """
        link, target = _uuid_transcript(tmp_path)
        _write_transcript(target, [("user", "review"),
                                   ("assistant", "still reading")])
        calls = {"n": 0}

        def fake_wait(*_a, **_kw):
            calls["n"] += 1
            if calls["n"] == 1:
                return _idle(1)
            # The transcript write lands while recovery settles.
            _write_transcript(target, [("user", "review"),
                                       ("assistant", "PASS")])
            return None

        from pm_core import hook_events, tmux
        monkeypatch.setattr(hook_events, "wait_for_event", fake_wait)
        monkeypatch.setattr(tmux, "pane_exists", lambda _p: True)
        monkeypatch.setattr(loop_shared, "recovery_settle_seconds",
                            lambda: 5.0)
        monkeypatch.setattr(loop_shared, "recovery_max_attempts", lambda: 2)
        monkeypatch.setattr(loop_shared, "recovery_response_timeout",
                            lambda: 3600.0)
        sent: list[str] = []

        content = loop_shared.poll_for_verdict(
            "%1", str(link), ("PASS",),
            grace_period=0, wait_timeout=0.01, send=sent.append,
            log_prefix="test",
        )
        assert "PASS" in content
        assert sent == []

    def test_overall_timeout_raises(self, tmp_path, monkeypatch):
        link, target = _uuid_transcript(tmp_path)
        _write_transcript(target, [("user", "review"),
                                   ("assistant", "still reading")])
        _patch_poll_env(monkeypatch, [None])

        with pytest.raises(VerdictRecoveryExhausted) as exc:
            loop_shared.poll_for_verdict(
                "%1", str(link), ("PASS",),
                grace_period=0, wait_timeout=0.0,
                overall_timeout=0.01, max_missing=0,
                send=lambda _m: None, log_prefix="test",
            )
        assert exc.value.reason == "overall_timeout"

    def test_verdict_landing_at_the_overall_deadline_is_returned(
            self, tmp_path, monkeypatch):
        """A verdict present when the poll deadline expires is returned.

        The deadline can expire on the tick the transcript is flushed (its
        idle hook may be missed, or predate the poller's baseline), so the
        poller must re-scan before reporting the outcome absent — the same
        last-chance scan the QA tick loop does in ``_retire_if_exhausted``.
        """
        link, target = _uuid_transcript(tmp_path)
        _write_transcript(target, [("user", "review"),
                                   ("assistant", "PASS")])
        _patch_poll_env(monkeypatch, [None])

        content = loop_shared.poll_for_verdict(
            "%1", str(link), ("PASS",),
            grace_period=0, wait_timeout=0.0,
            # Non-zero: 0 means "no overall deadline" (off), so a 0 here
            # would leave the poller unbounded.
            overall_timeout=0.001, max_missing=0,
            send=lambda _m: None, log_prefix="test",
        )
        assert "PASS" in content

    def test_verdict_landing_at_the_response_deadline_is_returned(
            self, tmp_path, monkeypatch):
        """A verdict flushed as the post-nudge deadline expires is recorded.

        Retiring the session as ``no_response`` while its outcome sits in the
        transcript is the "completed result treated as absent" failure this
        recovery exists to prevent.
        """
        link, target = _uuid_transcript(tmp_path)
        _write_transcript(target, [("user", "review"),
                                   ("assistant", "still reading")])
        calls = {"n": 0}

        def fake_wait(*_a, **_kw):
            calls["n"] += 1
            if calls["n"] == 1:
                return _idle(1)          # the turn that produced no verdict
            if calls["n"] == 2:
                return None              # settle window: no native retry
            # The answer to the nudge lands while the poller waits for it.
            _write_transcript(target, [("user", "review"),
                                       ("assistant", "PASS")])
            return None                  # ...but its idle event is never seen

        class _Clock:
            """Advances one second per read so the nudge deadline expires."""

            def __init__(self):
                self.now = 100.0

            def monotonic(self):
                self.now += 1.0
                return self.now

            def time(self):
                return 1_700_000_000.0

        from pm_core import hook_events, tmux
        monkeypatch.setattr(hook_events, "wait_for_event", fake_wait)
        monkeypatch.setattr(tmux, "pane_exists", lambda _p: True)
        monkeypatch.setattr(loop_shared, "recovery_settle_seconds",
                            lambda: 5.0)
        monkeypatch.setattr(loop_shared, "recovery_max_attempts", lambda: 2)
        monkeypatch.setattr(loop_shared, "recovery_response_timeout",
                            lambda: 1.0)
        monkeypatch.setattr(loop_shared, "time", _Clock())

        content = loop_shared.poll_for_verdict(
            "%1", str(link), ("PASS",),
            grace_period=0, wait_timeout=0.01,
            send=lambda _m: None, log_prefix="test",
        )
        assert "PASS" in content

    def test_idle_inside_grace_window_is_processed_not_dropped(
            self, tmp_path, monkeypatch):
        """An idle that lands inside the grace window must still be handled.

        A fast turn (a verdict produced in seconds, or an immediate provider
        error) emits its only idle inside the grace window.  Discarding that
        event leaves the poller waiting for a turn that never comes — the
        same unbounded hang bounded recovery exists to prevent — so the
        grace is waited out and the event processed instead.
        """
        link, target = _uuid_transcript(tmp_path)
        _write_transcript(target, [("user", "review"),
                                   ("assistant", "PASS")])
        calls = {"n": 0}

        def fake_wait(*_a, **_kw):
            calls["n"] += 1
            assert calls["n"] < 100, "poller hung after dropping the idle"
            return _idle(1) if calls["n"] == 1 else None

        from pm_core import hook_events, tmux
        monkeypatch.setattr(hook_events, "wait_for_event", fake_wait)
        monkeypatch.setattr(tmux, "pane_exists", lambda _p: True)

        content = loop_shared.poll_for_verdict(
            "%1", str(link), ("PASS",),
            grace_period=0.05, wait_timeout=0.01,
            send=lambda _m: pytest.fail("a completed turn must not be nudged"),
            log_prefix="test",
        )
        assert "PASS" in content

    def test_recovery_disabled_keeps_waiting(self, tmp_path, monkeypatch):
        """max_missing=0 preserves the legacy unbounded wait."""
        link, target = _uuid_transcript(tmp_path)
        _write_transcript(target, [("user", "review"),
                                   ("assistant", "still reading")])
        # First idle (no verdict), then a verdict appears on the next turn.
        _patch_poll_env(monkeypatch, [_idle(1), _idle(2)])
        calls = {"n": 0}

        def fake_wait(*_a, **_kw):
            calls["n"] += 1
            if calls["n"] == 2:
                _write_transcript(target, [("user", "review"),
                                           ("assistant", "PASS")])
                return _idle(2)
            return _idle(1)

        from pm_core import hook_events
        monkeypatch.setattr(hook_events, "wait_for_event", fake_wait)

        content = loop_shared.poll_for_verdict(
            "%1", str(link), ("PASS",),
            grace_period=0, wait_timeout=0.01, max_missing=0,
            send=lambda _m: pytest.fail("recovery must stay disabled"),
            log_prefix="test",
        )
        assert "PASS" in content

    def test_baseline_line_returns_a_verdict_already_in_the_transcript(
            self, tmp_path, monkeypatch):
        """A caller that prompted the pane must not hang on its answer.

        The verifier re-check sends its follow-up and only then starts
        polling.  If the verifier answers during the send/settle window its
        ``idle_prompt`` predates the poller's hook baseline, so the event
        loop would never see it and the poll would block until the response
        timeout — the hang bounded recovery exists to prevent.
        """
        link, target = _uuid_transcript(tmp_path)
        _write_transcript(target, [("user", "verify"),
                                   ("assistant", "VERIFIED")])
        # No hook event ever arrives: the answer predates the poll.
        _patch_poll_env(monkeypatch, [])

        content = loop_shared.poll_for_verdict(
            "%1", str(link), ("VERIFIED", "FLAGGED_END"),
            grace_period=0, wait_timeout=0.01, send=lambda _m: None,
            baseline_line=-1, log_prefix="test",
        )
        assert content == "VERIFIED"

    def test_baseline_line_ignores_the_prompting_verdict(
            self, tmp_path, monkeypatch):
        """The verdict that prompted the re-check is never the answer.

        ``find_verdict_turn`` is task-scoped; a follow-up the transcript does
        not record as a task boundary would otherwise let the prompting
        FLAGGED be returned as the re-checked verdict.  With ``baseline_line``
        the poll keeps waiting and exhausts instead.
        """
        link, target = _uuid_transcript(tmp_path)
        _write_transcript(target, [("user", "verify"),
                                   ("assistant", "FLAGGED_END")])
        # The prompting verdict is the last line of the transcript.
        from pm_core.verdict_transcript import find_verdict_turn
        prior = find_verdict_turn(str(target), ("VERIFIED", "FLAGGED_END"))
        assert prior is not None
        _patch_poll_env(monkeypatch,
                        [_idle(1), None, _idle(2), None, _idle(3)])

        with pytest.raises(VerdictRecoveryExhausted):
            loop_shared.poll_for_verdict(
                "%1", str(link), ("VERIFIED", "FLAGGED_END"),
                grace_period=0, wait_timeout=0.01, send=lambda _m: None,
                baseline_line=prior.line_index, log_prefix="test",
            )


# ---------------------------------------------------------------------------
# Review loop wiring
# ---------------------------------------------------------------------------

class TestReviewLoopRecovery:
    def test_exhaustion_sets_no_verdict(self):
        from pm_core.review_loop import (
            ReviewLoopState, run_review_loop_sync, VERDICT_NO_VERDICT,
        )
        state = ReviewLoopState(pr_id="pr-001")
        seen: list[str] = []

        with patch("pm_core.review_loop._run_claude_review",
                   side_effect=VerdictRecoveryExhausted(
                       "session never emitted a verdict", attempts=3)):
            run_review_loop_sync(
                state, "/tmp",
                {"id": "pr-001", "title": "t", "workdir": "/tmp"},
                transcript_dir="/tmp",
                on_iteration=lambda s: seen.append(s.latest_verdict),
            )

        assert state.latest_verdict == VERDICT_NO_VERDICT
        assert state.running is False
        assert len(state.history) == 1
        assert state.history[0].verdict == VERDICT_NO_VERDICT
        assert seen == [VERDICT_NO_VERDICT]

    def test_stop_during_recovery_is_not_a_no_verdict(self):
        """A stop that lands while recovery is deciding is teardown.

        ``handle``'s deferral bound runs before its own ``stop_check``, so a
        user stop can surface as ``VerdictRecoveryExhausted``.  Recording
        NO_VERDICT then would show a user-caused failure and a history entry
        for a loop the user stopped.
        """
        from pm_core.review_loop import (
            ReviewLoopState, run_review_loop_sync, VERDICT_NO_VERDICT,
        )
        state = ReviewLoopState(pr_id="pr-001")

        def _stop_then_exhaust(*_a, **_kw):
            state.stop_requested = True
            raise VerdictRecoveryExhausted("session never emitted a verdict",
                                           attempts=3, reason="no_progress")

        with patch("pm_core.review_loop._run_claude_review",
                   side_effect=_stop_then_exhaust):
            run_review_loop_sync(
                state, "/tmp",
                {"id": "pr-001", "title": "t", "workdir": "/tmp"},
                transcript_dir="/tmp",
            )

        assert state.latest_verdict != VERDICT_NO_VERDICT
        assert state.history == []
        assert state.running is False


# ---------------------------------------------------------------------------
# Watcher loop wiring
# ---------------------------------------------------------------------------

class TestWatcherLoopRecovery:
    def test_exhaustion_sets_no_verdict(self):
        from pm_core.watcher_base import (
            BaseWatcher, VERDICT_NO_VERDICT,
        )

        class W(BaseWatcher):
            WATCHER_TYPE = "test"
            DISPLAY_NAME = "Test"
            WINDOW_NAME = "test"

            def generate_prompt(self, iteration):
                return ""

            def build_launch_cmd(self, iteration, transcript=None):
                return ["echo"]

            def parse_verdict(self, output):
                return "READY"

        w = W("/tmp")
        with patch("pm_core.watcher_base.BaseWatcher._run_iteration",
                   side_effect=VerdictRecoveryExhausted(
                       "session never emitted a verdict", attempts=3)):
            result = w.run_sync(max_iterations=1)

        assert result.latest_verdict == VERDICT_NO_VERDICT
        assert result.running is False
        assert len(result.history) == 1
        assert result.history[0].verdict == VERDICT_NO_VERDICT
        assert "never emitted" in result.latest_summary

    def test_stop_during_recovery_is_a_clean_kill(self):
        """A stop that lands while recovery is deciding is teardown.

        Mirror the ``PaneKilledError`` stop convention (``KILLED``) instead
        of recording a NO_VERDICT failure for a user-stopped run.
        """
        from pm_core.watcher_base import (
            BaseWatcher, VERDICT_NO_VERDICT,
        )

        class W(BaseWatcher):
            WATCHER_TYPE = "test"
            DISPLAY_NAME = "Test"
            WINDOW_NAME = "test"

            def generate_prompt(self, iteration):
                return ""

            def build_launch_cmd(self, iteration, transcript=None):
                return ["echo"]

            def parse_verdict(self, output):
                return "READY"

        w = W("/tmp")

        def _stop_then_exhaust(*_a, **_kw):
            w.state.stop_requested = True
            raise VerdictRecoveryExhausted("session never emitted a verdict",
                                           attempts=3, reason="no_progress")

        with patch("pm_core.watcher_base.BaseWatcher._run_iteration",
                   side_effect=_stop_then_exhaust):
            result = w.run_sync(max_iterations=1)

        assert result.latest_verdict == "KILLED"
        assert result.latest_verdict != VERDICT_NO_VERDICT
        assert result.history == []
        assert result.running is False


# ---------------------------------------------------------------------------
# QA wiring
# ---------------------------------------------------------------------------

class TestQARecoveryWiring:
    def test_concretize_exhaustion_label(self, tmp_path):
        """A refiner that never emits its block is not called a rejection."""
        from pm_core import qa_loop

        scenario = qa_loop.QAScenario(index=1, title="S", focus="f")
        with patch("pm_core.qa_loop.poll_for_verdict",
                   side_effect=VerdictRecoveryExhausted(
                       "no refiner block", attempts=3)), \
             patch("pm_core.claude_launcher.transcript_path_for",
                   return_value=tmp_path / "x.jsonl"):
            refined, reason = qa_loop._concretize_scenario(
                scenario, {}, {}, "%1", str(uuid.uuid4()), str(tmp_path))

        assert refined is None
        assert reason.startswith(qa_loop._RECOVERY_EXHAUSTED_PREFIX)
        label = qa_loop._concretize_failure_label(reason)
        assert label == reason
        assert "refiner rejected" not in label

    def test_concretize_stop_during_recovery_is_not_a_refiner_failure(
            self, tmp_path):
        """A user stop must not record a per-scenario INPUT_REQUIRED reason.

        ``handle`` checks its deferral bound before its own ``stop_check``,
        so a stop that lands while the concretizer's recovery is deciding
        surfaces as an exhaustion.  Recording it would turn a cancelled run
        into a missing-outcome failure (and a QA note), the same class the
        planner / tick loop / finalize / review / watcher paths guard.
        """
        from pm_core import qa_loop

        scenario = qa_loop.QAScenario(index=1, title="S", focus="f")
        with patch("pm_core.qa_loop.poll_for_verdict",
                   side_effect=VerdictRecoveryExhausted(
                       "no refiner block", attempts=3)) as polled, \
             patch("pm_core.claude_launcher.transcript_path_for",
                   return_value=tmp_path / "x.jsonl"):
            refined, reason = qa_loop._concretize_scenario(
                scenario, {}, {}, "%1", str(uuid.uuid4()), str(tmp_path),
                stop_check=lambda: True)

        assert (refined, reason) == (None, None)
        # The poll itself is bounded by the stop too, so a stopped run never
        # nudges the concretizer session.
        assert polled.call_args.kwargs["stop_check"] is not None
        assert polled.call_args.kwargs["stop_check"]() is True

    def test_finalize_exhaustion_returns_no_verdict(self, tmp_path):
        from pm_core import qa_loop
        from pm_core.qa_loop import QALoopState

        state = QALoopState(pr_id="pr-001")
        state.scenario_verdicts = {1: "PASS"}
        state.verified_scenarios = {1}
        scenario = qa_loop.QAScenario(index=1, title="S", focus="f",
                                      worktree_path=str(tmp_path))
        state.scenarios = [scenario]

        with patch("pm_core.tmux.find_window_by_name",
                   return_value={"index": "0"}), \
             patch("pm_core.tmux.get_pane_indices",
                   return_value=[("%1", 0)]), \
             patch("pm_core.tmux.split_pane_at", return_value="%2"), \
             patch("pm_core.pane_layout.register_and_rebalance"), \
             patch("pm_core.claude_launcher.build_claude_shell_cmd",
                   return_value="cmd"), \
             patch("pm_core.qa_loop.poll_for_verdict",
                   side_effect=VerdictRecoveryExhausted(
                       "no finalize outcome", attempts=3)):
            verdict = qa_loop._run_qa_finalize_pane(
                state, {"branch": "b", "title": "t"},
                "pm-test", "qa-window", str(tmp_path),
            )

        assert verdict == VERDICT_NO_VERDICT

    def test_finalize_stop_during_recovery_is_not_no_verdict(self, tmp_path):
        """A stop that lands while recovery decides is teardown, not failure.

        ``handle`` checks its deferral bound before its own ``stop_check``,
        so a user-stopped run could surface ``[finalize: NO_VERDICT]`` — a
        failure state — instead of the clean unfinalized result.
        """
        from pm_core import qa_loop
        from pm_core.qa_loop import QALoopState

        state = QALoopState(pr_id="pr-001")
        state.scenario_verdicts = {1: "PASS"}
        state.verified_scenarios = {1}
        scenario = qa_loop.QAScenario(index=1, title="S", focus="f",
                                      worktree_path=str(tmp_path))
        state.scenarios = [scenario]

        def stop_mid_recovery(*_a, **_kw):
            # Simulates the TUI thread setting stop_requested while
            # ``handle`` was deciding, then the exhaustion it surfaces.
            state.stop_requested = True
            raise VerdictRecoveryExhausted("no finalize outcome", attempts=3)

        with patch("pm_core.tmux.find_window_by_name",
                   return_value={"index": "0"}), \
             patch("pm_core.tmux.get_pane_indices",
                   return_value=[("%1", 0)]), \
             patch("pm_core.tmux.split_pane_at", return_value="%2"), \
             patch("pm_core.pane_layout.register_and_rebalance"), \
             patch("pm_core.claude_launcher.build_claude_shell_cmd",
                   return_value="cmd"), \
             patch("pm_core.qa_loop.poll_for_verdict",
                   side_effect=stop_mid_recovery):
            verdict = qa_loop._run_qa_finalize_pane(
                state, {"branch": "b", "title": "t"},
                "pm-test", "qa-window", str(tmp_path),
                stop_check=lambda: state.stop_requested,
            )

        assert verdict is None

    def test_verifier_exhaustion_returns_failure_reason(self, tmp_path):
        """A verifier that never emits VERIFIED/FLAGGED blocks finalize."""
        from pm_core import qa_loop

        scenario = qa_loop.QAScenario(index=1, title="S", focus="f",
                                      window_name="qa-s1", pane_id="%1")
        scenario.worktree_path = str(tmp_path)
        scenario.transcript_path = None

        with patch("pm_core.tmux.split_pane_at", return_value="%2"), \
             patch("pm_core.tmux.pane_window_id", return_value="@1"), \
             patch("pm_core.tmux.set_shared_window_size"), \
             patch("pm_core.pane_layout.register_and_rebalance"), \
             patch("pm_core.claude_launcher.build_claude_shell_cmd",
                   return_value="cmd"), \
             patch("pm_core.qa_loop.poll_for_verdict",
                   side_effect=VerdictRecoveryExhausted(
                       "no verifier verdict", attempts=3)):
            passed, reason, pane = qa_loop._verify_single_scenario(
                scenario, "PASS", "scenario output", {"id": "pr-1"},
                session="sess", qa_workdir=str(tmp_path),
                pr_workdir=str(tmp_path),
            )

        assert passed is False
        assert reason.startswith("verifier produced no verdict:")
        assert pane == "%2"

    def test_verifier_recheck_exhaustion_blocks_finalize(self, tmp_path):
        """The machine-driven re-check wait is bounded too.

        The re-verification follow-up asks the *existing* verifier pane for a
        new VERIFIED/FLAGGED outcome.  That wait used the unbounded
        ``wait_for_follow_up_verdict`` (the human INPUT_REQUIRED wait), so a
        verifier that idled without a verdict hung QA forever — the exact
        shape bounded recovery exists to prevent.
        """
        from pm_core import qa_loop

        scenario = qa_loop.QAScenario(index=1, title="S", focus="f",
                                      window_name="qa-s1", pane_id="%1")
        scenario.worktree_path = str(tmp_path)
        scenario.transcript_path = None
        # A live verifier pane from the first verification: the follow-up
        # reuses it instead of splitting a new one.
        scenario.verifier_pane_id = "%2"
        scenario.verifier_session_id = str(uuid.uuid4())
        scenario.verifier_cwd = str(tmp_path)
        scenario.verifier_transcript = str(tmp_path / "verify.jsonl")

        with patch("pm_core.tmux.pane_exists", return_value=True), \
             patch("pm_core.tmux.send_keys"), \
             patch("pm_core.qa_loop.time.sleep"), \
             patch("pm_core.qa_loop.poll_for_verdict",
                   side_effect=VerdictRecoveryExhausted(
                       "no re-checked verdict", attempts=3)) as polled:
            passed, reason, pane = qa_loop._verify_single_scenario(
                scenario, "PASS", "scenario output", {"id": "pr-1"},
                session="sess", qa_workdir=str(tmp_path),
                pr_workdir=str(tmp_path),
            )

        assert passed is False
        assert reason.startswith("verifier produced no verdict:")
        assert pane == "%2"
        # The shared poller (with recovery) was used, not the unbounded
        # human follow-up wait.
        assert polled.call_count == 1
        assert polled.call_args.kwargs["verdicts"] == (
            "VERIFIED", "FLAGGED_END")
        assert "FLAGGED_START" in polled.call_args.kwargs["outcome_request"]
        # The verdict that prompted the re-check is snapshotted before the
        # follow-up is sent, so the poller can return an answer that landed
        # during the send/settle window (its idle predates the poll) without
        # mistaking the prompting verdict for it.
        assert polled.call_args.kwargs["baseline_line"] == -1

    def test_scenario_worker_exhaustion_marks_input_required(
            self, tmp_path, monkeypatch):
        """A worker that idles without a verdict is bounded, not hung."""
        from pm_core import qa_loop
        from pm_core.qa_loop import QALoopState, QAScenario

        scenario = QAScenario(index=1, title="S", focus="f")
        scenario.window_name = "qa-s1"
        scenario.session_id = "sid-s1"
        scenario.pane_id = "%1"
        transcript = _transcript_with_assistant(tmp_path, "still testing")
        scenario.transcript_path = str(transcript)

        state = QALoopState(pr_id="pr-001")
        state.scenarios = [scenario]
        state.scenario_verdicts = {}
        state.qa_workdir = None

        events = {"ts": 100.0}

        def fake_read_event(_sid):
            events["ts"] += 1.0
            return {"event_type": "idle_prompt",
                    "timestamp": events["ts"],
                    "session_id": "sid-s1"}

        sent: list[str] = []
        notified: list[str] = []
        monkeypatch.setattr(qa_loop, "_VERDICT_GRACE_PERIOD", 0)
        monkeypatch.setattr(qa_loop, "recovery_max_attempts", lambda: 1)
        monkeypatch.setattr(qa_loop, "recovery_settle_seconds", lambda: 0.0)
        monkeypatch.setattr(qa_loop, "recovery_response_timeout", lambda: 0.0)
        monkeypatch.setattr(qa_loop, "_is_verification_enabled",
                            lambda: False)
        monkeypatch.setattr(qa_loop, "_get_verdict_reminder_timeout",
                            lambda: None)

        with patch("pm_core.hook_events.read_event", side_effect=fake_read_event), \
             patch("pm_core.qa_loop._get_scenario_pane", return_value="%1"), \
             patch("pm_core.qa_loop.find_verdict_turn",
                   return_value=None), \
             patch("pm_core.qa_loop._write_status_file"), \
             patch("pm_core.qa_loop.time.sleep"), \
             patch("pm_core.qa_loop.time.monotonic", return_value=1000.0), \
             patch("pm_core.tmux.send_keys",
                   side_effect=lambda _p, m: sent.append(m)), \
             patch("pm_core.tmux.pane_exists", return_value=True):
            qa_loop._poll_tmux_verdicts(
                state, {}, {}, "sess", str(tmp_path),
                tmp_path / "status.json",
                lambda: notified.append(state.latest_output),
            )

        assert state.scenario_verdicts[1] == "INPUT_REQUIRED"
        reason = state.scenario_verdict_reasons[1]
        assert "no verdict" in reason and "recovery" in reason
        # The retirement is surfaced to the TUI like every other
        # INPUT_REQUIRED transition in this loop (status pane + log line).
        assert "INPUT_REQUIRED" in state.latest_output
        assert any("INPUT_REQUIRED" in m for m in notified if m)

    def test_scenario_worker_hook_refresh_is_bounded(
            self, tmp_path, monkeypatch):
        """A worker whose idle_prompt keeps refreshing must not hang QA.

        The settle window is measured from when the no-verdict episode
        began, so a hook refresh cannot push it forward forever (the
        FakeClaude shape that motivated pr-6566901).
        """
        from pm_core import qa_loop
        from pm_core.qa_loop import QALoopState, QAScenario

        scenario = QAScenario(index=1, title="S", focus="f")
        scenario.window_name = "qa-s1"
        scenario.session_id = "sid-s1"
        scenario.pane_id = "%1"
        transcript = _transcript_with_assistant(tmp_path, "still testing")
        scenario.transcript_path = str(transcript)

        state = QALoopState(pr_id="pr-001")
        state.scenarios = [scenario]
        state.scenario_verdicts = {}
        state.qa_workdir = None

        clock = {"t": 1000.0}

        def fake_time():
            clock["t"] += 1.0
            return clock["t"]

        def fake_read_event(_sid):
            clock["t"] += 1.0
            return {"event_type": "idle_prompt",
                    "timestamp": clock["t"],
                    "session_id": "sid-s1"}

        monkeypatch.setattr(qa_loop, "_VERDICT_GRACE_PERIOD", 0)
        monkeypatch.setattr(qa_loop, "recovery_max_attempts", lambda: 2)
        monkeypatch.setattr(qa_loop, "recovery_settle_seconds", lambda: 5.0)
        monkeypatch.setattr(qa_loop, "recovery_response_timeout", lambda: 0.0)
        monkeypatch.setattr(qa_loop, "_is_verification_enabled",
                            lambda: False)
        monkeypatch.setattr(qa_loop, "_get_verdict_reminder_timeout",
                            lambda: None)

        with patch("pm_core.hook_events.read_event", side_effect=fake_read_event), \
             patch("pm_core.qa_loop._get_scenario_pane", return_value="%1"), \
             patch("pm_core.qa_loop.find_verdict_turn",
                   return_value=None), \
             patch("pm_core.qa_loop._write_status_file"), \
             patch("pm_core.qa_loop.time.sleep"), \
             patch("pm_core.qa_loop.time.time", side_effect=fake_time), \
             patch("pm_core.qa_loop.time.monotonic", return_value=1000.0), \
             patch("pm_core.tmux.send_keys"), \
             patch("pm_core.tmux.pane_exists", return_value=True):
            qa_loop._poll_tmux_verdicts(
                state, {}, {}, "sess", str(tmp_path),
                tmp_path / "status.json", lambda *a: None,
            )

        assert state.scenario_verdicts[1] == "INPUT_REQUIRED"
        assert "no_progress" in state.scenario_verdict_reasons[1]

    def test_scenario_worker_refresh_between_ticks_is_no_progress(
            self, tmp_path, monkeypatch):
        """A refresh that lands between ticks is a refresh, not a new turn.

        Production shape: the hook file's timestamp advances every ~2s while
        the tick loop polls every 5s, so a second ``read_event`` within one
        tick returns the same event.  Recovery must hand the tracker the
        event it has already accounted for, otherwise every refresh looks
        like "no new event" and the worker is nudged (closing a FakeClaude's
        stdin) instead of exhausting with ``no_progress``.
        """
        from pm_core import loop_shared, qa_loop
        from pm_core.qa_loop import QALoopState, QAScenario

        scenario = QAScenario(index=1, title="S", focus="f")
        scenario.window_name = "qa-s1"
        scenario.session_id = "sid-s1"
        scenario.pane_id = "%1"
        scenario.transcript_path = str(
            _transcript_with_assistant(tmp_path, "still testing"))

        state = QALoopState(pr_id="pr-001")
        state.scenarios = [scenario]
        state.scenario_verdicts = {}
        state.qa_workdir = None

        clock = {"t": 1000.0, "ev": 100.0}
        ticks = {"n": 0}

        def fake_sleep(_seconds):
            # One tick: the wall clock and the hook timestamp advance, and
            # the hook stays stable for the rest of the tick.
            ticks["n"] += 1
            assert ticks["n"] <= 200, "QA tick loop hung: no recovery"
            clock["t"] += 5.0
            clock["ev"] += 2.0

        def fake_read_event(_sid):
            return {"event_type": "idle_prompt",
                    "timestamp": clock["ev"],
                    "session_id": "sid-s1"}

        sent: list[str] = []

        monkeypatch.setattr(qa_loop, "_VERDICT_GRACE_PERIOD", 0)
        monkeypatch.setattr(qa_loop, "recovery_max_attempts", lambda: 2)
        monkeypatch.setattr(qa_loop, "recovery_settle_seconds", lambda: 5.0)
        monkeypatch.setattr(qa_loop, "recovery_response_timeout", lambda: 0.0)
        monkeypatch.setattr(qa_loop, "_is_verification_enabled",
                            lambda: False)
        monkeypatch.setattr(qa_loop, "_get_verdict_reminder_timeout",
                            lambda: None)
        monkeypatch.setattr(loop_shared.time, "monotonic",
                            lambda: clock["t"])

        with patch("pm_core.hook_events.read_event",
                   side_effect=fake_read_event), \
             patch("pm_core.qa_loop._get_scenario_pane", return_value="%1"), \
             patch("pm_core.qa_loop.find_verdict_turn",
                   return_value=None), \
             patch("pm_core.qa_loop._write_status_file"), \
             patch("pm_core.qa_loop.time.sleep", side_effect=fake_sleep), \
             patch("pm_core.qa_loop.time.time",
                   side_effect=lambda: clock["t"]), \
             patch("pm_core.tmux.send_keys",
                   side_effect=lambda _p, m: sent.append(m)), \
             patch("pm_core.tmux.pane_exists", return_value=True):
            qa_loop._poll_tmux_verdicts(
                state, {}, {}, "sess", str(tmp_path),
                tmp_path / "status.json", lambda *a: None,
            )

        assert state.scenario_verdicts[1] == "INPUT_REQUIRED"
        assert "no_progress" in state.scenario_verdict_reasons[1]
        assert not sent, "a refresh-only worker must not be nudged"

    def test_scenario_worker_single_idle_then_silent_is_bounded(
            self, tmp_path, monkeypatch):
        """A worker that emits ONE no-verdict idle then goes silent must not
        hang QA.

        The realistic shape is a single idle_prompt per turn: the worker
        ends its turn without a verdict and then waits for input, so no
        newer event ever arrives.  Recovery must still nudge it (once the
        settle window elapses) and retire it when it never responds —
        previously the nudge was only evaluated when a *fresh* event passed
        the turn-boundary gate, so a silent worker was never nudged at all.
        """
        from pm_core import loop_shared, qa_loop
        from pm_core.qa_loop import QALoopState, QAScenario

        scenario = QAScenario(index=1, title="S", focus="f")
        scenario.window_name = "qa-s1"
        scenario.session_id = "sid-s1"
        scenario.pane_id = "%1"
        transcript = _transcript_with_assistant(tmp_path, "still testing")
        scenario.transcript_path = str(transcript)

        state = QALoopState(pr_id="pr-001")
        state.scenarios = [scenario]
        state.scenario_verdicts = {}
        state.qa_workdir = None

        clock = {"t": 1000.0}

        def fake_time():
            clock["t"] += 1.0
            return clock["t"]

        def fake_monotonic():
            clock["t"] += 1.0
            return clock["t"]

        # One idle_prompt whose timestamp never advances: the worker has
        # gone silent and will never produce a fresh turn.
        def fake_read_event(_sid):
            return {"event_type": "idle_prompt",
                    "timestamp": 100.0,
                    "session_id": "sid-s1"}

        sent: list[str] = []
        ticks = {"n": 0}

        def fake_sleep(_seconds):
            ticks["n"] += 1
            assert ticks["n"] <= 500, "QA tick loop hung: no recovery"

        monkeypatch.setattr(qa_loop, "_VERDICT_GRACE_PERIOD", 0)
        monkeypatch.setattr(qa_loop, "recovery_max_attempts", lambda: 1)
        monkeypatch.setattr(qa_loop, "recovery_settle_seconds", lambda: 5.0)
        monkeypatch.setattr(qa_loop, "recovery_response_timeout", lambda: 50.0)
        monkeypatch.setattr(qa_loop, "_is_verification_enabled",
                            lambda: False)
        monkeypatch.setattr(qa_loop, "_get_verdict_reminder_timeout",
                            lambda: None)
        # The tracker's response clock lives in loop_shared; qa_loop.time is
        # the same module, so this advances both.
        monkeypatch.setattr(loop_shared.time, "monotonic", fake_monotonic)

        with patch("pm_core.hook_events.read_event", side_effect=fake_read_event), \
             patch("pm_core.qa_loop._get_scenario_pane", return_value="%1"), \
             patch("pm_core.qa_loop.find_verdict_turn",
                   return_value=None), \
             patch("pm_core.qa_loop._write_status_file"), \
             patch("pm_core.qa_loop.time.sleep", side_effect=fake_sleep), \
             patch("pm_core.qa_loop.time.time", side_effect=fake_time), \
             patch("pm_core.tmux.send_keys",
                   side_effect=lambda _p, m: sent.append(m)), \
             patch("pm_core.tmux.pane_exists", return_value=True):
            qa_loop._poll_tmux_verdicts(
                state, {}, {}, "sess", str(tmp_path),
                tmp_path / "status.json", lambda *a: None,
            )

        assert sent, "silent worker was never nudged"
        assert state.scenario_verdicts[1] == "INPUT_REQUIRED"
        assert "no_response" in state.scenario_verdict_reasons[1]

    def test_reminder_timeout_overrides_the_settle_interval(
            self, tmp_path, monkeypatch):
        """``qa-verdict-reminder-timeout`` still tunes the settle interval.

        The setting is retained for compatibility: when set it overrides
        ``verdict-recovery-settle-seconds`` for QA scenario workers.  With a
        100 s shared settle and a 1 s override, a worker that idles without a
        verdict must be nudged within a couple of ticks instead of waiting
        out the shared window.
        """
        from pm_core import loop_shared, qa_loop
        from pm_core.qa_loop import QALoopState, QAScenario

        scenario = QAScenario(index=1, title="S", focus="f")
        scenario.window_name = "qa-s1"
        scenario.session_id = "sid-s1"
        scenario.pane_id = "%1"
        scenario.transcript_path = str(
            _transcript_with_assistant(tmp_path, "still testing"))

        state = QALoopState(pr_id="pr-001")
        state.scenarios = [scenario]
        state.scenario_verdicts = {}
        state.qa_workdir = None

        clock = {"t": 1000.0}

        def fake_time():
            clock["t"] += 1.0
            return clock["t"]

        def fake_monotonic():
            clock["t"] += 1.0
            return clock["t"]

        def fake_read_event(_sid):
            return {"event_type": "idle_prompt",
                    "timestamp": 100.0,
                    "session_id": "sid-s1"}

        sent: list[str] = []
        sent_at = {"tick": None}
        ticks = {"n": 0}

        def fake_sleep(_seconds):
            ticks["n"] += 1
            assert ticks["n"] <= 500, "QA tick loop hung: no recovery"

        def fake_send(_pane, msg):
            sent.append(msg)
            if sent_at["tick"] is None:
                sent_at["tick"] = ticks["n"]

        monkeypatch.setattr(qa_loop, "_VERDICT_GRACE_PERIOD", 0)
        monkeypatch.setattr(qa_loop, "recovery_max_attempts", lambda: 1)
        # The shared settle is deliberately far larger than the run: only
        # the retained setting can make the nudge happen this early.
        monkeypatch.setattr(qa_loop, "recovery_settle_seconds",
                            lambda: 100.0)
        monkeypatch.setattr(qa_loop, "recovery_response_timeout",
                            lambda: 50.0)
        monkeypatch.setattr(qa_loop, "_is_verification_enabled",
                            lambda: False)
        monkeypatch.setattr(qa_loop, "_get_verdict_reminder_timeout",
                            lambda: 1)
        monkeypatch.setattr(loop_shared.time, "monotonic", fake_monotonic)

        with patch("pm_core.hook_events.read_event",
                   side_effect=fake_read_event), \
             patch("pm_core.qa_loop._get_scenario_pane", return_value="%1"), \
             patch("pm_core.qa_loop.find_verdict_turn",
                   return_value=None), \
             patch("pm_core.qa_loop._write_status_file"), \
             patch("pm_core.qa_loop.time.sleep", side_effect=fake_sleep), \
             patch("pm_core.qa_loop.time.time", side_effect=fake_time), \
             patch("pm_core.tmux.send_keys", side_effect=fake_send), \
             patch("pm_core.tmux.pane_exists", return_value=True):
            qa_loop._poll_tmux_verdicts(
                state, {}, {}, "sess", str(tmp_path),
                tmp_path / "status.json", lambda *a: None,
            )

        assert sent, "worker was never nudged"
        assert sent_at["tick"] is not None and sent_at["tick"] <= 5, (
            "the qa-verdict-reminder-timeout override did not shorten the "
            f"settle window (nudged on tick {sent_at['tick']})")
        # The nudge is the scenario-worker outcome request, not a legacy
        # format reminder.
        assert "standalone outcome" in sent[0]

    def test_verdict_landing_on_the_response_timeout_tick_is_recorded(
            self, tmp_path, monkeypatch):
        """A verdict that lands as the nudge deadline expires must win.

        The response-timeout check ran before the fresh-event gate, so a
        worker whose verdict landed in the same tick as its deadline was
        retired as ``no_response`` even though its outcome was already in
        the transcript — the "completed result treated as absent" failure
        this recovery exists to prevent.
        """
        from pm_core import qa_loop
        from pm_core.qa_loop import QALoopState, QAScenario

        scenario = QAScenario(index=1, title="S", focus="f")
        scenario.window_name = "qa-s1"
        scenario.session_id = "sid-s1"
        scenario.pane_id = "%1"
        transcript = _transcript_with_assistant(tmp_path, "still testing")
        scenario.transcript_path = str(transcript)

        state = QALoopState(pr_id="pr-001")
        state.scenarios = [scenario]
        state.scenario_verdicts = {}
        state.qa_workdir = None

        clock = {"t": 1000.0}

        def fake_time():
            clock["t"] += 1.0
            return clock["t"]

        nudged = {"sent": False}

        def fake_send(_pane, _msg):
            nudged["sent"] = True

        # Once nudged, the worker answers on a *new* turn that carries the
        # verdict — landing in the same tick the deadline expires.
        def fake_read_event(_sid):
            return {"event_type": "idle_prompt",
                    "timestamp": 200.0 if nudged["sent"] else 100.0,
                    "session_id": "sid-s1"}

        def fake_extract(*_a, **_kw):
            return "PASS" if nudged["sent"] else None

        monkeypatch.setattr(qa_loop, "_VERDICT_GRACE_PERIOD", 0)
        monkeypatch.setattr(qa_loop, "recovery_max_attempts", lambda: 3)
        monkeypatch.setattr(qa_loop, "recovery_settle_seconds", lambda: 5.0)
        # Expired by the tick after the nudge.
        monkeypatch.setattr(qa_loop, "recovery_response_timeout", lambda: 1.0)
        monkeypatch.setattr(qa_loop, "_is_verification_enabled",
                            lambda: False)
        monkeypatch.setattr(qa_loop, "_get_verdict_reminder_timeout",
                            lambda: None)

        with patch("pm_core.hook_events.read_event",
                   side_effect=fake_read_event), \
             patch("pm_core.qa_loop._get_scenario_pane", return_value="%1"), \
             patch("pm_core.qa_loop.find_verdict_turn",
                   side_effect=_as_hits(fake_extract)), \
             patch("pm_core.qa_loop._write_status_file"), \
             patch("pm_core.qa_loop.time.sleep"), \
             patch("pm_core.qa_loop.time.time", side_effect=fake_time), \
             patch("pm_core.qa_loop.time.monotonic", side_effect=fake_time), \
             patch("pm_core.tmux.send_keys", side_effect=fake_send), \
             patch("pm_core.tmux.pane_exists", return_value=True):
            qa_loop._poll_tmux_verdicts(
                state, {}, {}, "sess", str(tmp_path),
                tmp_path / "status.json", lambda *a: None,
            )

        assert nudged["sent"], "worker was never nudged"
        assert state.scenario_verdicts[1] == "PASS"
        assert 1 not in state.scenario_verdict_reasons

    def test_verdict_landing_after_the_response_timeout_scan_is_recorded(
            self, tmp_path, monkeypatch):
        """A verdict written just after the deadline tick's scan still wins.

        The scan runs at the idle hook, which can precede the transcript
        write; the response deadline can expire on that very tick.  Retiring
        there would report ``no_response`` for a worker whose outcome is
        already on disk (the "completed result treated as absent" failure),
        so exhaustion re-scans before marking the scenario INPUT_REQUIRED.
        """
        from pm_core import qa_loop
        from pm_core.qa_loop import QALoopState, QAScenario

        scenario = QAScenario(index=1, title="S", focus="f")
        scenario.window_name = "qa-s1"
        scenario.session_id = "sid-s1"
        scenario.pane_id = "%1"
        scenario.transcript_path = str(
            _transcript_with_assistant(tmp_path, "still testing"))

        state = QALoopState(pr_id="pr-001")
        state.scenarios = [scenario]
        state.scenario_verdicts = {}
        state.qa_workdir = None

        clock = {"t": 1000.0}

        def fake_time():
            clock["t"] += 1.0
            return clock["t"]

        nudged = {"sent": False}
        post_nudge_scans = {"n": 0}

        def fake_send(_pane, _msg):
            nudged["sent"] = True

        def fake_read_event(_sid):
            # One idle before the nudge, then a fresh one for the answer.
            return {"event_type": "idle_prompt",
                    "timestamp": 200.0 if nudged["sent"] else 100.0,
                    "session_id": "sid-s1"}

        def fake_extract(*_a, **_kw):
            if not nudged["sent"]:
                return None
            post_nudge_scans["n"] += 1
            # The scan at the answer's idle event races the transcript
            # write; the re-scan inside the exhaustion handler sees it.
            return None if post_nudge_scans["n"] == 1 else "PASS"

        monkeypatch.setattr(qa_loop, "_VERDICT_GRACE_PERIOD", 0)
        monkeypatch.setattr(qa_loop, "recovery_max_attempts", lambda: 3)
        monkeypatch.setattr(qa_loop, "recovery_settle_seconds", lambda: 5.0)
        # Expired by the tick that reads the answer's idle event.
        monkeypatch.setattr(qa_loop, "recovery_response_timeout", lambda: 1.0)
        monkeypatch.setattr(qa_loop, "_is_verification_enabled",
                            lambda: False)
        monkeypatch.setattr(qa_loop, "_get_verdict_reminder_timeout",
                            lambda: None)

        with patch("pm_core.hook_events.read_event",
                   side_effect=fake_read_event), \
             patch("pm_core.qa_loop._get_scenario_pane", return_value="%1"), \
             patch("pm_core.qa_loop.find_verdict_turn",
                   side_effect=_as_hits(fake_extract)), \
             patch("pm_core.qa_loop._write_status_file"), \
             patch("pm_core.qa_loop.time.sleep"), \
             patch("pm_core.qa_loop.time.time", side_effect=fake_time), \
             patch("pm_core.qa_loop.time.monotonic", side_effect=fake_time), \
             patch("pm_core.tmux.send_keys", side_effect=fake_send), \
             patch("pm_core.tmux.pane_exists", return_value=True):
            qa_loop._poll_tmux_verdicts(
                state, {}, {}, "sess", str(tmp_path),
                tmp_path / "status.json", lambda *a: None,
            )

        assert nudged["sent"], "worker was never nudged"
        assert post_nudge_scans["n"] >= 2, "the exhaustion path never re-scanned"
        assert state.scenario_verdicts[1] == "PASS"
        assert 1 not in state.scenario_verdict_reasons

    def test_scenario_worker_verdict_flushed_after_idle_is_recorded(
            self, tmp_path, monkeypatch):
        """A verdict that lands after the idle hook is recorded, not nudged.

        The tick loop's verdict scan runs at the idle event; if the
        transcript write trails it, recovery must re-check before nudging so
        a completed worker is never asked to re-emit its outcome.
        """
        from pm_core import qa_loop
        from pm_core.qa_loop import QALoopState, QAScenario

        scenario = QAScenario(index=1, title="S", focus="f")
        scenario.window_name = "qa-s1"
        scenario.session_id = "sid-s1"
        scenario.pane_id = "%1"
        scenario.transcript_path = str(
            _transcript_with_assistant(tmp_path, "still testing"))

        state = QALoopState(pr_id="pr-001")
        state.scenarios = [scenario]
        state.scenario_verdicts = {}
        state.qa_workdir = None

        clock = {"t": 1000.0}

        def fake_time():
            clock["t"] += 1.0
            return clock["t"]

        def fake_read_event(_sid):
            # One idle_prompt, then silence: the transcript gains the
            # verdict but no newer hook event ever arrives.
            return {"event_type": "idle_prompt", "timestamp": 100.0,
                    "session_id": "sid-s1"}

        calls = {"n": 0}

        def fake_extract(_path, _verdicts):
            calls["n"] += 1
            # The scan at the idle event races the transcript write; every
            # later scan sees the completed verdict.
            return None if calls["n"] == 1 else "PASS"

        sent: list[str] = []

        monkeypatch.setattr(qa_loop, "_VERDICT_GRACE_PERIOD", 0)
        monkeypatch.setattr(qa_loop, "recovery_max_attempts", lambda: 2)
        monkeypatch.setattr(qa_loop, "recovery_settle_seconds", lambda: 5.0)
        monkeypatch.setattr(qa_loop, "recovery_response_timeout", lambda: 0.0)
        monkeypatch.setattr(qa_loop, "_is_verification_enabled",
                            lambda: False)
        monkeypatch.setattr(qa_loop, "_get_verdict_reminder_timeout",
                            lambda: None)

        with patch("pm_core.hook_events.read_event",
                   side_effect=fake_read_event), \
             patch("pm_core.qa_loop._get_scenario_pane", return_value="%1"), \
             patch("pm_core.qa_loop.find_verdict_turn",
                   side_effect=_as_hits(fake_extract)), \
             patch("pm_core.qa_loop._write_status_file"), \
             patch("pm_core.qa_loop.time.sleep"), \
             patch("pm_core.qa_loop.time.time", side_effect=fake_time), \
             patch("pm_core.qa_loop.time.monotonic", return_value=1000.0), \
             patch("pm_core.tmux.send_keys",
                   side_effect=lambda _p, m: sent.append(m)), \
             patch("pm_core.tmux.pane_exists", return_value=True):
            qa_loop._poll_tmux_verdicts(
                state, {}, {}, "sess", str(tmp_path),
                tmp_path / "status.json", lambda *a: None,
            )

        assert state.scenario_verdicts[1] == "PASS"
        assert sent == []

    def test_nudged_scenario_worker_verdict_on_the_next_turn_is_recorded(
            self, tmp_path, monkeypatch):
        """A worker that answers the recovery nudge is recorded, not retired.

        The nudge asks the worker for its own standalone outcome.  A worker
        that then emits its verdict on a new turn must have it recorded (and
        its recovery tracker dropped) instead of the answered turn being
        counted as another missing output — the "retried, then succeeded"
        half of the acceptance criteria for the tick loop.
        """
        from pm_core import loop_shared, qa_loop
        from pm_core.qa_loop import QALoopState, QAScenario

        scenario = QAScenario(index=1, title="S", focus="f")
        scenario.window_name = "qa-s1"
        scenario.session_id = "sid-s1"
        scenario.pane_id = "%1"
        scenario.transcript_path = str(
            _transcript_with_assistant(tmp_path, "still testing"))

        state = QALoopState(pr_id="pr-001")
        state.scenarios = [scenario]
        state.scenario_verdicts = {}
        state.qa_workdir = None

        clock = {"t": 1000.0}

        def fake_time():
            clock["t"] += 1.0
            return clock["t"]

        def fake_monotonic():
            clock["t"] += 1.0
            return clock["t"]

        sent: list[str] = []

        def fake_read_event(_sid):
            # The same idle turn (the worker waits for input) until the
            # nudge is answered, then a genuinely new turn.
            return {"event_type": "idle_prompt",
                    "timestamp": 200.0 if sent else 100.0,
                    "session_id": "sid-s1"}

        def fake_extract(_path, _verdicts):
            return "PASS" if sent else None

        ticks = {"n": 0}

        def fake_sleep(_seconds):
            ticks["n"] += 1
            assert ticks["n"] <= 500, "QA tick loop hung: no recovery"

        monkeypatch.setattr(qa_loop, "_VERDICT_GRACE_PERIOD", 0)
        monkeypatch.setattr(qa_loop, "recovery_max_attempts", lambda: 3)
        monkeypatch.setattr(qa_loop, "recovery_settle_seconds", lambda: 5.0)
        monkeypatch.setattr(qa_loop, "recovery_response_timeout", lambda: 0.0)
        monkeypatch.setattr(qa_loop, "_is_verification_enabled",
                            lambda: False)
        monkeypatch.setattr(qa_loop, "_get_verdict_reminder_timeout",
                            lambda: None)
        monkeypatch.setattr(loop_shared.time, "monotonic", fake_monotonic)

        with patch("pm_core.hook_events.read_event",
                   side_effect=fake_read_event), \
             patch("pm_core.qa_loop._get_scenario_pane", return_value="%1"), \
             patch("pm_core.qa_loop.find_verdict_turn",
                   side_effect=_as_hits(fake_extract)), \
             patch("pm_core.qa_loop._write_status_file"), \
             patch("pm_core.qa_loop.time.sleep", side_effect=fake_sleep), \
             patch("pm_core.qa_loop.time.time", side_effect=fake_time), \
             patch("pm_core.tmux.send_keys",
                   side_effect=lambda _p, m: sent.append(m)), \
             patch("pm_core.tmux.pane_exists", return_value=True):
            qa_loop._poll_tmux_verdicts(
                state, {}, {}, "sess", str(tmp_path),
                tmp_path / "status.json", lambda *a: None,
            )

        assert len(sent) == 1, f"expected exactly one nudge, got {sent}"
        assert state.scenario_verdicts[1] == "PASS"

    def test_scenario_worker_stop_event_does_not_strand_recovery(
            self, tmp_path, monkeypatch):
        """A Stop hook overwriting the idle event must not strand a worker.

        The hook file holds only the latest event, so a ``Stop`` write for
        the same turn makes ``read_event`` return a newer *non-idle* event.
        That is not a new turn: recovery must still nudge (and then retire
        on ``no_response``) instead of closing the no-verdict episode —
        only a fresh ``idle_prompt`` re-opens one.
        """
        from pm_core import loop_shared, qa_loop
        from pm_core.qa_loop import QALoopState, QAScenario

        scenario = QAScenario(index=1, title="S", focus="f")
        scenario.window_name = "qa-s1"
        scenario.session_id = "sid-s1"
        scenario.pane_id = "%1"
        scenario.transcript_path = str(
            _transcript_with_assistant(tmp_path, "still testing"))

        state = QALoopState(pr_id="pr-001")
        state.scenarios = [scenario]
        state.scenario_verdicts = {}
        state.qa_workdir = None

        clock = {"t": 1000.0}

        def fake_time():
            clock["t"] += 1.0
            return clock["t"]

        def fake_monotonic():
            clock["t"] += 1.0
            return clock["t"]

        reads = {"n": 0}

        def fake_read_event(_sid):
            # The worker's idle turn is visible for a couple of ticks; the
            # Stop hook for that same turn then overwrites the event file
            # with a newer timestamp and it never changes again.
            reads["n"] += 1
            if reads["n"] <= 4:
                return {"event_type": "idle_prompt", "timestamp": 100.0,
                        "session_id": "sid-s1"}
            return {"event_type": "Stop", "timestamp": 101.0,
                    "session_id": "sid-s1"}

        sent: list[str] = []
        ticks = {"n": 0}

        def fake_sleep(_seconds):
            ticks["n"] += 1
            assert ticks["n"] <= 500, "QA tick loop hung: no recovery"

        monkeypatch.setattr(qa_loop, "_VERDICT_GRACE_PERIOD", 0)
        monkeypatch.setattr(qa_loop, "recovery_max_attempts", lambda: 2)
        monkeypatch.setattr(qa_loop, "recovery_settle_seconds", lambda: 5.0)
        monkeypatch.setattr(qa_loop, "recovery_response_timeout", lambda: 50.0)
        monkeypatch.setattr(qa_loop, "_is_verification_enabled",
                            lambda: False)
        monkeypatch.setattr(qa_loop, "_get_verdict_reminder_timeout",
                            lambda: None)
        monkeypatch.setattr(loop_shared.time, "monotonic", fake_monotonic)

        with patch("pm_core.hook_events.read_event",
                   side_effect=fake_read_event), \
             patch("pm_core.qa_loop._get_scenario_pane", return_value="%1"), \
             patch("pm_core.qa_loop.find_verdict_turn",
                   return_value=None), \
             patch("pm_core.qa_loop._write_status_file"), \
             patch("pm_core.qa_loop.time.sleep", side_effect=fake_sleep), \
             patch("pm_core.qa_loop.time.time", side_effect=fake_time), \
             patch("pm_core.tmux.send_keys",
                   side_effect=lambda _p, m: sent.append(m)), \
             patch("pm_core.tmux.pane_exists", return_value=True):
            qa_loop._poll_tmux_verdicts(
                state, {}, {}, "sess", str(tmp_path),
                tmp_path / "status.json", lambda *a: None,
            )

        assert sent, "worker was never nudged after its idle turn"
        assert state.scenario_verdicts[1] == "INPUT_REQUIRED"
        assert "no_response" in state.scenario_verdict_reasons[1]

    def test_scenario_worker_stop_does_not_surface_a_spurious_exhaustion(
            self, tmp_path, monkeypatch):
        """A stop arriving mid-tick must not retire a worker as no_response.

        ``state.stop_requested`` is set by the TUI thread, so it can land
        between two ticks — after the ``while`` condition was evaluated.
        The post-nudge ``check_response()`` would then retire a worker that
        never answered a nudge as INPUT_REQUIRED even though the run is
        being torn down (and the reason would be persisted into the resume
        snapshot).  The planner honours stop_requested the same way before
        its own check_response.
        """
        from pm_core import loop_shared, qa_loop
        from pm_core.qa_loop import QALoopState, QAScenario

        scenario = QAScenario(index=1, title="S", focus="f")
        scenario.window_name = "qa-s1"
        scenario.session_id = "sid-s1"
        scenario.pane_id = "%1"
        scenario.transcript_path = str(
            _transcript_with_assistant(tmp_path, "still testing"))

        state = QALoopState(pr_id="pr-001")
        state.scenarios = [scenario]
        state.scenario_verdicts = {}
        state.qa_workdir = None

        clock = {"t": 1000.0}

        def fake_monotonic():
            clock["t"] += 1.0
            return clock["t"]

        sent: list[str] = []

        def fake_sleep(_seconds):
            # The user stops the run between ticks, after the nudge landed.
            if sent:
                state.stop_requested = True

        monkeypatch.setattr(qa_loop, "_VERDICT_GRACE_PERIOD", 0)
        monkeypatch.setattr(qa_loop, "recovery_max_attempts", lambda: 3)
        monkeypatch.setattr(qa_loop, "recovery_settle_seconds", lambda: 0.0)
        # Expired by the tick after the nudge, so check_response would fire.
        monkeypatch.setattr(qa_loop, "recovery_response_timeout", lambda: 1.0)
        monkeypatch.setattr(qa_loop, "_is_verification_enabled",
                            lambda: False)
        monkeypatch.setattr(qa_loop, "_get_verdict_reminder_timeout",
                            lambda: None)
        monkeypatch.setattr(loop_shared.time, "monotonic", fake_monotonic)

        with patch("pm_core.hook_events.read_event",
                   return_value={"event_type": "idle_prompt",
                                 "timestamp": 100.0,
                                 "session_id": "sid-s1"}), \
             patch("pm_core.qa_loop._get_scenario_pane", return_value="%1"), \
             patch("pm_core.qa_loop.find_verdict_turn",
                   return_value=None), \
             patch("pm_core.qa_loop._write_status_file"), \
             patch("pm_core.qa_loop.time.sleep", side_effect=fake_sleep), \
             patch("pm_core.tmux.send_keys",
                   side_effect=lambda _p, m: sent.append(m)), \
             patch("pm_core.tmux.pane_exists", return_value=True):
            qa_loop._poll_tmux_verdicts(
                state, {}, {}, "sess", str(tmp_path),
                tmp_path / "status.json", lambda *a: None,
            )

        assert sent, "worker was never nudged"
        assert 1 not in state.scenario_verdicts, (
            "a worker was retired during teardown")
        assert 1 not in state.scenario_verdict_reasons

    def test_scenario_worker_stop_during_handle_does_not_retire(
            self, tmp_path, monkeypatch):
        """A stop set *inside* ``handle`` must not persist a retirement.

        ``handle``'s attempt bound is checked before its own ``stop_check``
        and the tick loop's settle read is non-blocking, so a stop that lands
        between the ``stopping`` snapshot and the bound can surface as
        exhaustion.  Teardown is not a verdict: the worker must stay pending,
        not be recorded as INPUT_REQUIRED (whose reason is persisted into the
        resume snapshot).
        """
        from pm_core import qa_loop
        from pm_core.qa_loop import QALoopState, QAScenario

        scenario = QAScenario(index=1, title="S", focus="f")
        scenario.window_name = "qa-s1"
        scenario.session_id = "sid-s1"
        scenario.pane_id = "%1"
        scenario.transcript_path = str(
            _transcript_with_assistant(tmp_path, "still testing"))

        state = QALoopState(pr_id="pr-001")
        state.scenarios = [scenario]
        state.scenario_verdicts = {}
        state.qa_workdir = None

        clock = {"t": 1000.0}

        def fake_time():
            clock["t"] += 1.0
            return clock["t"]

        def fake_read_event(_sid):
            clock["t"] += 1.0
            return {"event_type": "idle_prompt",
                    "timestamp": clock["t"],
                    "session_id": "sid-s1"}

        calls = {"n": 0}

        def fake_extract(*_a, **_kw):
            calls["n"] += 1
            # Call 1 = first episode's turn scan, call 2 = its
            # verdict_check, call 3 = second episode's turn scan, call 4 =
            # its verdict_check.  The user stops the run while ``handle`` is
            # deciding the second turn.
            if calls["n"] == 4:
                state.stop_requested = True
            return None

        monkeypatch.setattr(qa_loop, "_VERDICT_GRACE_PERIOD", 0)
        monkeypatch.setattr(qa_loop, "recovery_max_attempts", lambda: 1)
        monkeypatch.setattr(qa_loop, "recovery_settle_seconds", lambda: 0.0)
        monkeypatch.setattr(qa_loop, "recovery_response_timeout", lambda: 0.0)
        monkeypatch.setattr(qa_loop, "_is_verification_enabled",
                            lambda: False)
        monkeypatch.setattr(qa_loop, "_get_verdict_reminder_timeout",
                            lambda: None)

        sent: list[str] = []

        with patch("pm_core.hook_events.read_event",
                   side_effect=fake_read_event), \
             patch("pm_core.qa_loop._get_scenario_pane", return_value="%1"), \
             patch("pm_core.qa_loop.find_verdict_turn",
                   side_effect=_as_hits(fake_extract)), \
             patch("pm_core.qa_loop._write_status_file"), \
             patch("pm_core.qa_loop.time.sleep"), \
             patch("pm_core.qa_loop.time.time", side_effect=fake_time), \
             patch("pm_core.qa_loop.time.monotonic", return_value=1000.0), \
             patch("pm_core.tmux.send_keys",
                   side_effect=lambda _p, m: sent.append(m)), \
             patch("pm_core.tmux.pane_exists", return_value=True):
            qa_loop._poll_tmux_verdicts(
                state, {}, {}, "sess", str(tmp_path),
                tmp_path / "status.json", lambda *a: None,
            )

        assert sent, "worker was never nudged"
        assert 1 not in state.scenario_verdicts, (
            "a worker was retired during teardown")
        assert 1 not in state.scenario_verdict_reasons


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@pytest.fixture
def pm_home(tmp_path, monkeypatch):
    """Isolated HOME so global settings never touch the real ``~/.pm``."""
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    return h


class TestRecoverySettings:
    def test_defaults_when_unset(self, pm_home):
        assert (loop_shared.recovery_max_attempts()
                == loop_shared.DEFAULT_MAX_MISSING)
        assert (loop_shared.recovery_settle_seconds()
                == loop_shared.DEFAULT_SETTLE_SECONDS)
        assert (loop_shared.recovery_response_timeout()
                == loop_shared.DEFAULT_RESPONSE_TIMEOUT)

    def test_pm_set_accepts_int_and_sub_second_float_values(self, pm_home):
        """The new keys are settable/listed, and floats accept ``0.5``."""
        from click.testing import CliRunner
        from pm_core.cli import cli

        runner = CliRunner()
        for setting, value in (
            ("verdict-recovery-max-attempts", "5"),
            ("verdict-recovery-settle-seconds", "0.5"),
            ("verdict-recovery-response-timeout", "120"),
        ):
            result = runner.invoke(cli, ["set", setting, value])
            assert result.exit_code == 0, result.output

        assert loop_shared.recovery_max_attempts() == 5
        assert loop_shared.recovery_settle_seconds() == 0.5
        assert loop_shared.recovery_response_timeout() == 120.0

        listed = runner.invoke(cli, ["set", "list"]).output
        for name in ("verdict-recovery-max-attempts",
                     "verdict-recovery-settle-seconds",
                     "verdict-recovery-response-timeout"):
            assert name in listed

    def test_pm_set_rejects_non_numeric_values(self, pm_home):
        from click.testing import CliRunner
        from pm_core.cli import cli

        runner = CliRunner()
        assert runner.invoke(
            cli, ["set", "verdict-recovery-max-attempts", "3"]).exit_code == 0
        bad = runner.invoke(
            cli, ["set", "verdict-recovery-max-attempts", "lots"])
        assert bad.exit_code != 0
        assert loop_shared.recovery_max_attempts() == 3

        bad = runner.invoke(
            cli, ["set", "verdict-recovery-settle-seconds", "soon"])
        assert bad.exit_code != 0
        assert (loop_shared.recovery_settle_seconds()
                == loop_shared.DEFAULT_SETTLE_SECONDS)

    def test_negative_settle_is_clamped_to_zero(self, pm_home):
        """A negative settle must not make ``handle`` wait a negative time."""
        from pm_core.paths import set_global_setting_value
        set_global_setting_value("verdict-recovery-settle-seconds", "-5")
        assert loop_shared.recovery_settle_seconds() == 0.0

    def test_corrupt_stored_values_fall_back_to_defaults(self, pm_home):
        """A hand-edited settings file must not crash the pollers."""
        from pm_core.paths import set_global_setting_value
        set_global_setting_value("verdict-recovery-max-attempts", "three")
        set_global_setting_value("verdict-recovery-settle-seconds", "soon")
        set_global_setting_value("verdict-recovery-response-timeout", "later")

        assert (loop_shared.recovery_max_attempts()
                == loop_shared.DEFAULT_MAX_MISSING)
        assert (loop_shared.recovery_settle_seconds()
                == loop_shared.DEFAULT_SETTLE_SECONDS)
        assert (loop_shared.recovery_response_timeout()
                == loop_shared.DEFAULT_RESPONSE_TIMEOUT)

    def test_non_finite_seconds_are_rejected(self, pm_home):
        """``float()`` accepts nan/inf; as a duration neither is meaningful.

        ``inf`` is the dangerous one: it would make the settle window
        unbounded, which is the hang this recovery exists to prevent.
        """
        from click.testing import CliRunner
        from pm_core.cli import cli
        from pm_core.paths import set_global_setting_value

        runner = CliRunner()
        for bad in ("nan", "inf"):
            result = runner.invoke(
                cli, ["set", "verdict-recovery-settle-seconds", bad])
            assert result.exit_code != 0, (bad, result.output)
        assert (loop_shared.recovery_settle_seconds()
                == loop_shared.DEFAULT_SETTLE_SECONDS)

        # A hand-edited settings file falls back the same way.
        set_global_setting_value("verdict-recovery-settle-seconds", "inf")
        assert (loop_shared.recovery_settle_seconds()
                == loop_shared.DEFAULT_SETTLE_SECONDS)
        set_global_setting_value("verdict-recovery-response-timeout", "nan")
        assert (loop_shared.recovery_response_timeout()
                == loop_shared.DEFAULT_RESPONSE_TIMEOUT)
