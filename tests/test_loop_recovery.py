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

    def test_retry_prompt_overrides_resume_request(self, tmp_path):
        rec, sent = _recovery(tmp_path, resume_request="ORIGINAL PROMPT")
        transcript = _transcript_without_assistant(tmp_path)

        rec.handle(str(transcript), ev_ts=1.0)

        assert sent == ["ORIGINAL PROMPT"]

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
             patch("pm_core.qa_loop.extract_verdict_from_transcript",
                   return_value=None), \
             patch("pm_core.qa_loop._write_status_file"), \
             patch("pm_core.qa_loop.time.sleep"), \
             patch("pm_core.qa_loop.time.monotonic", return_value=1000.0), \
             patch("pm_core.tmux.send_keys",
                   side_effect=lambda _p, m: sent.append(m)), \
             patch("pm_core.tmux.pane_exists", return_value=True):
            qa_loop._poll_tmux_verdicts(
                state, {}, {}, "sess", str(tmp_path),
                tmp_path / "status.json", lambda *a: None,
            )

        assert state.scenario_verdicts[1] == "INPUT_REQUIRED"
        reason = state.scenario_verdict_reasons[1]
        assert "no verdict" in reason and "recovery" in reason

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
             patch("pm_core.qa_loop.extract_verdict_from_transcript",
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
             patch("pm_core.qa_loop.extract_verdict_from_transcript",
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
