"""Bounded native retry of a failed authorized review launch (pr-e040aeb).

The native review loop used to end with ERROR the moment the next
iteration's ``pm pr review --fresh --review-loop`` child exited non-zero
(e.g. the old window was removed and container setup then failed), and the
auto-start scheduler then skipped the PR forever because its (non-running)
loop entry remained.  These tests cover the bounded retry, the pre-retry
rediscovery/adoption, the serialized launch lease, the retained artifact,
and the explicit retryable failure on exhaustion.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pm_core import review_loop
from pm_core.review_loop import (
    AttemptDiscovery,
    ReviewHoldError,
    ReviewIteration,
    ReviewLaunchError,
    ReviewLoopState,
    VERDICT_CLOSED,
    VERDICT_HOLD,
    VERDICT_KILLED,
    VERDICT_LAUNCH_FAILED,
    VERDICT_NEEDS_WORK,
    VERDICT_PASS,
    run_review_loop_sync,
)

PR = "pr-001"

# Captured before the autouse fixture replaces it for the retry tests.
_ORIG_DISCOVER = review_loop._discover_iteration
_ORIG_CLAIM = review_loop._claim_launch


def _pr(tmp_path) -> dict:
    wd = tmp_path / "wd"
    wd.mkdir(exist_ok=True)
    return {"id": PR, "title": "T", "branch": "pm/pr-001",
            "status": "in_review", "workdir": str(wd)}


@pytest.fixture(autouse=True)
def _fast_retry(monkeypatch):
    """Keep retries instant in tests; production values are seconds."""
    monkeypatch.setattr(review_loop, "REVIEW_LAUNCH_BACKOFF_BASE", 0.0)
    monkeypatch.setattr(review_loop, "REVIEW_LAUNCH_BACKOFF_MAX", 0.0)
    monkeypatch.setattr(review_loop, "REVIEW_LAUNCH_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(review_loop, "REVIEW_LAUNCH_CLAIM_WAIT", 0.0)
    monkeypatch.setattr(review_loop, "_WINDOW_WAIT", 0.0)
    monkeypatch.setattr(review_loop, "_VERDICT_GRACE_PERIOD", 0)
    # No real tmux/terminal checks unless a test opts in.
    monkeypatch.setattr(review_loop, "_discover_iteration",
                        lambda *a, **k: AttemptDiscovery("launch"))
    monkeypatch.setattr(review_loop, "_pr_is_terminal",
                        lambda *a, **k: False)
    monkeypatch.setattr(review_loop, "_claim_launch", lambda *a, **k: True)


def _run(state, tmp_path, **kw):
    return run_review_loop_sync(state, str(tmp_path), _pr(tmp_path),
                                transcript_dir=str(tmp_path), **kw)


# ---------------------------------------------------------------------------
# Bounded retry
# ---------------------------------------------------------------------------

def test_launch_failure_retries_same_iteration_and_collects_verdict(tmp_path):
    state = ReviewLoopState(pr_id=PR)
    err = ReviewLaunchError("container setup failed", retryable=True,
                            artifact=str(tmp_path / "a.log"))
    with patch.object(review_loop, "_run_claude_review",
                      side_effect=[err, "All good.\n\n**PASS**"]) as run:
        result = _run(state, tmp_path)
    assert result.latest_verdict == VERDICT_PASS
    assert result.iteration == 1
    assert [h.iteration for h in result.history] == [1]
    calls = run.call_args_list
    assert len(calls) == 2
    assert [c.kwargs["iteration"] for c in calls] == [1, 1]
    assert [c.kwargs["attempt"] for c in calls] == [1, 2]
    assert [c.kwargs["loop_id"] for c in calls] == [state.loop_id] * 2
    # A success clears the episode metadata.
    assert result.launch_attempts == 0
    assert result.launch_retryable is False


def test_exhaustion_is_an_explicit_retryable_failure_not_a_verdict(tmp_path):
    state = ReviewLoopState(pr_id=PR)
    err = ReviewLaunchError("container setup failed", retryable=True,
                            artifact=str(tmp_path / "a.log"))
    with patch.object(review_loop, "_run_claude_review", side_effect=err) as run:
        result = _run(state, tmp_path)
    assert run.call_count == 3
    assert result.latest_verdict == VERDICT_LAUNCH_FAILED
    assert result.latest_verdict not in ("PASS", "NEEDS_WORK")
    assert result.history == []
    assert result.launch_retryable is True
    assert result.launch_attempts == 3
    assert result.last_launch_artifact == str(tmp_path / "a.log")
    assert "container setup failed" in result.latest_output
    assert result.retry_ready_at > 0


def test_non_retryable_failure_stops_after_one_attempt(tmp_path):
    state = ReviewLoopState(pr_id=PR)
    err = ReviewLaunchError("401 unauthorized", retryable=False, reason="auth")
    with patch.object(review_loop, "_run_claude_review", side_effect=err) as run:
        result = _run(state, tmp_path)
    assert run.call_count == 1
    assert result.latest_verdict == VERDICT_LAUNCH_FAILED
    assert result.launch_retryable is False


def test_stopping_loop_does_not_claim_the_launch_lease(monkeypatch):
    """A loop that has been stopped/superseded must not take (or re-take)
    the launch lease: the superseding loop claims it right after setting
    ``stop_requested``, and losing that race would make the new loop wait
    out its bounded claim and then fail with a non-retryable
    LAUNCH_FAILED — re-stranding the target."""
    monkeypatch.setattr(review_loop, "_claim_launch", _ORIG_CLAIM)
    state = ReviewLoopState(pr_id=PR)
    state.stop_requested = True
    claims = []
    monkeypatch.setattr("pm_core.runtime_state.claim_action_lease",
                        lambda *a, **k: claims.append(a) or True)
    assert review_loop._claim_launch(state, 1, 1) is False
    assert not claims, "a stopping loop must not write a lease"


def test_stop_between_claim_and_launch_does_not_launch(tmp_path, monkeypatch):
    """The stop can land after the loop-top check, while the claim or
    discovery runs; the loop must not create a review window the user just
    asked to replace."""
    state = ReviewLoopState(pr_id=PR)

    def discover_and_cancel(*_a, **_k):
        state.stop_requested = True
        return AttemptDiscovery("launch")

    monkeypatch.setattr(review_loop, "_discover_iteration", discover_and_cancel)
    with patch.object(review_loop, "_run_claude_review") as run:
        result = _run(state, tmp_path)
    run.assert_not_called()
    assert result.latest_verdict == VERDICT_KILLED


def test_stop_landing_before_the_thread_body_prevents_the_launch(
        tmp_path, monkeypatch):
    """A stop issued between ``_start_loop`` (which marks the loop running
    before the thread exists) and this thread's first line must not be
    discarded: the user is told the loop is stopping, so it must not create
    a review window (and a container) anyway."""
    state = ReviewLoopState(pr_id=PR)
    state.stop_requested = True
    with patch.object(review_loop, "_run_claude_review") as run:
        result = _run(state, tmp_path)
    run.assert_not_called()
    assert result.running is False
    assert result.latest_verdict != VERDICT_PASS


def test_cancellation_during_backoff_prevents_retry(tmp_path, monkeypatch):
    state = ReviewLoopState(pr_id=PR)
    err = ReviewLaunchError("boom", retryable=True)

    def sleep_and_cancel(*_a, **_k):
        state.stop_requested = True

    monkeypatch.setattr(review_loop, "_interruptible_sleep", sleep_and_cancel)
    with patch.object(review_loop, "_run_claude_review", side_effect=err) as run:
        result = _run(state, tmp_path)
    assert run.call_count == 1
    assert result.latest_verdict == VERDICT_KILLED


def test_pr_closed_during_retry_stops_without_relaunch(tmp_path, monkeypatch):
    state = ReviewLoopState(pr_id=PR)
    err = ReviewLaunchError("boom", retryable=True)
    # loop-top checks: first iteration False, second (after the failure) True
    checks = iter([False, True])
    monkeypatch.setattr(review_loop, "_pr_is_terminal",
                        lambda *a, **k: next(checks, True))
    with patch.object(review_loop, "_run_claude_review", side_effect=err) as run:
        result = _run(state, tmp_path)
    assert run.call_count == 1
    assert result.latest_verdict == VERDICT_CLOSED


def test_trust_hold_stops_without_retry(tmp_path):
    state = ReviewLoopState(pr_id=PR)
    with patch.object(review_loop, "_run_claude_review",
                      side_effect=ReviewHoldError("stuck at workspace trust")):
        result = _run(state, tmp_path)
    assert result.latest_verdict == VERDICT_HOLD
    assert result.launch_retryable is False
    assert "workspace trust" in result.latest_output


def test_restart_handoff_converts_a_trust_hold_to_HOLD(tmp_path, monkeypatch):
    """The handoff adopt path polls directly; a trust prompt there must be a
    HOLD, not a terminal ERROR."""
    from pm_core.claude_launcher import WorkspaceTrustBlocked
    state = ReviewLoopState(pr_id=PR, iteration=1)
    transcript = tmp_path / f"{uuid.uuid4()}.jsonl"
    transcript.write_text("")
    monkeypatch.setattr(review_loop, "_discover_iteration", lambda *a, **k:
                        AttemptDiscovery("adopt", pane_id="%9",
                                         transcript=str(transcript)))
    monkeypatch.setattr(review_loop, "_poll_for_verdict",
                        MagicMock(side_effect=WorkspaceTrustBlocked("trust")))
    with pytest.raises(ReviewHoldError):
        review_loop._adopt_in_flight_review(state, _pr(tmp_path),
                                            str(tmp_path))


def test_restart_handoff_does_not_adopt_a_transcript_this_loop_never_launched(
        tmp_path, monkeypatch):
    """The handoff shares discovery's fabrication guard: a loop that never
    launched its iteration must not adopt an earlier run's transcript for the
    same iteration number (the manual-<token> dir outlives a loop)."""
    seen: dict = {}

    def fake_discover(state, pr_data, tdir, iteration, *, allow_recovery=True):
        seen["allow_recovery"] = allow_recovery
        return AttemptDiscovery("launch")

    monkeypatch.setattr(review_loop, "_discover_iteration", fake_discover)
    state = ReviewLoopState(pr_id=PR, iteration=1)
    assert review_loop._adopt_in_flight_review(
        state, _pr(tmp_path), str(tmp_path)) is None
    assert seen["allow_recovery"] is False

    # Once this loop has launched the iteration (or a resumed breadcrumb
    # recorded an attempt), recovery is allowed again.
    for state in (ReviewLoopState(pr_id=PR, iteration=1,
                                  iteration_attempted=True),
                  ReviewLoopState(pr_id=PR, iteration=1, launch_attempts=1)):
        review_loop._adopt_in_flight_review(state, _pr(tmp_path),
                                            str(tmp_path))
        assert seen["allow_recovery"] is True


def test_restart_handoff_relaunches_when_the_transcript_has_no_session(
        tmp_path, monkeypatch):
    """A transcript whose session id cannot be recovered must fall back to a
    relaunch, not raise a terminal error from inside the poller."""
    state = ReviewLoopState(pr_id=PR, iteration=1)
    monkeypatch.setattr(review_loop, "_discover_iteration", lambda *a, **k:
                        AttemptDiscovery("adopt", pane_id="%9",
                                         transcript=str(tmp_path / "t.jsonl")))
    poll = MagicMock()
    monkeypatch.setattr(review_loop, "_poll_for_verdict", poll)
    assert review_loop._adopt_in_flight_review(state, _pr(tmp_path),
                                               str(tmp_path)) is None
    poll.assert_not_called()


def test_restart_between_iterations_does_not_adopt_the_old_run(
        tmp_path, monkeypatch):
    """A completed iteration clears ``iteration_attempted``.

    ``run_review_loop_sync`` bumps the iteration counter *before*
    ``_run_iteration_with_retry`` re-snapshots the episode, so a merge
    restart landing in that window persists whatever the finished iteration
    left behind.  If that is still ``True``, the restart handoff allows
    recovery and adopts an earlier run's ``review-<pr>-i<N>.jsonl`` verdict
    for an iteration this loop never launched — the fabrication guard's
    blind spot for N >= 2 (iteration 6 only covered the loop's first
    iteration, where the flag starts out ``False``).
    """
    monkeypatch.setattr(review_loop, "_discover_iteration", _ORIG_DISCOVER)
    monkeypatch.setattr(review_loop, "_get_pm_session", lambda: None)

    # An earlier run of this PR already produced iteration 2 with a PASS.
    old_sid = str(uuid.uuid4())
    _make_symlink(tmp_path, "review-pr-001-i2.jsonl", old_sid)
    (tmp_path / f"{old_sid}.jsonl").write_text(json.dumps({
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": "old\n\n**PASS**"}]},
    }) + "\n")

    # The state a merge restart would persist right after each bump.
    at_bump: list[tuple[int, bool]] = []
    orig = review_loop._run_iteration_with_retry

    def spy(state, *args, **kwargs):
        at_bump.append((state.iteration, state.iteration_attempted))
        return orig(state, *args, **kwargs)

    state = ReviewLoopState(pr_id=PR)
    with patch.object(review_loop, "_run_iteration_with_retry",
                      side_effect=spy), \
         patch.object(review_loop, "_run_claude_review",
                      side_effect=["nope\n\n**NEEDS_WORK**",
                                   "fresh\n\n**PASS**"]) as run:
        result = _run(state, tmp_path, max_iterations=2)
    assert run.call_count == 2, "iteration 2 must run its own review"
    assert result.latest_verdict == VERDICT_PASS
    assert at_bump == [(1, False), (2, False)]

    # Resuming on that persisted state must relaunch, not adopt the old
    # iteration-2 transcript.
    resumed = ReviewLoopState(pr_id=PR, iteration=2, retry_iteration=1,
                              iteration_attempted=at_bump[-1][1])
    resumed.history.append(ReviewIteration(iteration=1,
                                           verdict=VERDICT_NEEDS_WORK,
                                           output=""))
    assert review_loop._adopt_in_flight_review(
        resumed, _pr(tmp_path), str(tmp_path)) is None


def test_restart_after_an_adopted_iteration_does_not_adopt_the_old_run(
        tmp_path, monkeypatch):
    """An adopted iteration clears ``iteration_attempted`` too.

    The restart handoff adopts the in-flight iteration, then
    ``run_review_loop_sync`` bumps the counter and only inside
    ``_run_iteration_with_retry`` re-snapshots the next episode.  A merge
    restart landing in that window persisted the adopted iteration's
    ``True`` for the *next* iteration number, so the resumed handoff
    allowed recovery and adopted an earlier run's
    ``review-<pr>-i<N>.jsonl`` verdict (e.g. ``PASS``) for an iteration this
    loop never launched — the same fabrication the completion-path reset
    closes for a normally finished iteration.
    """
    monkeypatch.setattr(review_loop, "_discover_iteration", _ORIG_DISCOVER)
    monkeypatch.setattr(review_loop, "_get_pm_session", lambda: None)

    # An earlier run of this PR already produced iteration 3 with a PASS.
    old_sid = str(uuid.uuid4())
    _make_symlink(tmp_path, "review-pr-001-i3.jsonl", old_sid)
    (tmp_path / f"{old_sid}.jsonl").write_text(json.dumps({
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": "old\n\n**PASS**"}]},
    }) + "\n")

    # The state a merge restart would persist right after the bump.
    at_bump: list[tuple[int, bool]] = []
    orig = review_loop._run_iteration_with_retry

    def spy(state, *args, **kwargs):
        at_bump.append((state.iteration, state.iteration_attempted))
        return orig(state, *args, **kwargs)

    # The loop resumes with iteration 2 in flight (launched before restart).
    state = ReviewLoopState(
        pr_id=PR, iteration=2, retry_iteration=2, launch_attempts=1,
        iteration_attempted=True, _transcript_dir=str(tmp_path),
        history=[ReviewIteration(iteration=1, verdict=VERDICT_NEEDS_WORK,
                                 output="")])
    with patch.object(review_loop, "_run_iteration_with_retry",
                      side_effect=spy), \
         patch.object(review_loop, "_adopt_in_flight_review",
                      return_value="ok\n\n**NEEDS_WORK**"), \
         patch.object(review_loop, "_run_claude_review",
                      return_value="fresh\n\n**PASS**") as run:
        result = _run(state, tmp_path, max_iterations=3)
    assert run.call_count == 1, "iteration 3 must run its own review"
    assert result.latest_verdict == VERDICT_PASS
    assert at_bump == [(3, False)]

    # Resuming on that persisted state must relaunch, not adopt the old
    # iteration-3 transcript.
    resumed = ReviewLoopState(pr_id=PR, iteration=3, retry_iteration=2,
                              iteration_attempted=at_bump[-1][1])
    resumed.history.extend([
        ReviewIteration(iteration=1, verdict=VERDICT_NEEDS_WORK, output=""),
        ReviewIteration(iteration=2, verdict=VERDICT_NEEDS_WORK, output=""),
    ])
    assert review_loop._adopt_in_flight_review(
        resumed, _pr(tmp_path), str(tmp_path)) is None


def test_whitespace_only_stderr_falls_back_to_stdout():
    """A child that prints only whitespace to stderr must still surface the
    real error it wrote to stdout."""
    assert review_loop._concise_launch_detail("  \n\t\n", "real failure\n") \
        == "real failure"


def test_recovered_attempt_is_adopted_not_relaunched(tmp_path, monkeypatch):
    state = ReviewLoopState(pr_id=PR)
    err = ReviewLaunchError("boom", retryable=True)
    discoveries = iter([
        AttemptDiscovery("launch"),
        AttemptDiscovery("verdict", output="Recovered.\n\n**PASS**"),
    ])
    monkeypatch.setattr(review_loop, "_discover_iteration",
                        lambda *a, **k: next(discoveries, AttemptDiscovery("launch")))
    with patch.object(review_loop, "_run_claude_review", side_effect=err) as run:
        result = _run(state, tmp_path)
    assert run.call_count == 1
    assert result.latest_verdict == VERDICT_PASS
    assert [h.iteration for h in result.history] == [1]


def test_new_owner_pane_is_adopted(tmp_path, monkeypatch):
    state = ReviewLoopState(pr_id=PR)
    monkeypatch.setattr(review_loop, "_discover_iteration", lambda *a, **k:
                        AttemptDiscovery("adopt", pane_id="%9",
                                         transcript=str(tmp_path / "other.jsonl")))
    with patch.object(review_loop, "_run_claude_review") as run, \
            patch.object(review_loop, "_poll_for_verdict",
                         return_value="Other driver.\n\n**PASS**"):
        result = _run(state, tmp_path)
    run.assert_not_called()
    assert result.latest_verdict == VERDICT_PASS


def test_retry_adopt_polls_without_the_startup_grace(tmp_path, monkeypatch):
    """An adopted session was launched before the poll, so the
    startup-false-positive grace must not be applied: an idle event inside
    it is discarded and an idle session never emits a second one, so the
    loop would hang until the pane died."""
    state = ReviewLoopState(pr_id=PR)
    monkeypatch.setattr(review_loop, "_discover_iteration", lambda *a, **k:
                        AttemptDiscovery("adopt", pane_id="%9",
                                         transcript=str(tmp_path / "other.jsonl"),
                                         session_id="sid-other"))
    seen = {}

    def fake_poll(pane_id, transcript, **kw):
        seen.update(kw)
        return "Other driver.\n\n**PASS**"

    monkeypatch.setattr(review_loop, "_poll_for_verdict", fake_poll)
    result = _run(state, tmp_path)
    assert "grace_period" not in seen
    assert result.latest_verdict == VERDICT_PASS


def test_retry_adopt_reads_a_verdict_that_landed_before_the_poll(
        tmp_path, monkeypatch):
    """A verdict that lands between discovery and the poll must be read, not
    waited for: the poller only wakes on idle events newer than its start, so
    it would hang until the pane died."""
    from pm_core import hook_events

    sid = str(uuid.uuid4())
    transcript = tmp_path / f"{sid}.jsonl"
    transcript.write_text(json.dumps({
        "type": "assistant",
        "message": {"content": [{"type": "text",
                                 "text": "Looks good.\n\n**PASS**"}]},
    }) + "\n")
    monkeypatch.setattr(hook_events, "read_event",
                        lambda _sid: {"event_type": "idle_prompt"})
    monkeypatch.setattr(review_loop, "_discover_iteration", lambda *a, **k:
                        AttemptDiscovery("adopt", pane_id="%9",
                                         transcript=str(transcript)))
    state = ReviewLoopState(pr_id=PR)
    with patch.object(review_loop, "_poll_for_verdict") as poll:
        result = _run(state, tmp_path)
    poll.assert_not_called()
    assert result.latest_verdict == VERDICT_PASS
    assert [h.iteration for h in result.history] == [1]


def test_another_loop_owner_stands_down(tmp_path, monkeypatch):
    state = ReviewLoopState(pr_id=PR)
    monkeypatch.setattr(review_loop, "_discover_iteration", lambda *a, **k:
                        AttemptDiscovery("other_owner", owner="loop:other"))
    with patch.object(review_loop, "_run_claude_review") as run:
        result = _run(state, tmp_path)
    run.assert_not_called()
    assert result.latest_verdict == VERDICT_LAUNCH_FAILED
    assert result.launch_retryable is False


def test_history_is_preserved_across_a_retry(tmp_path):
    state = ReviewLoopState(pr_id=PR, iteration=2)
    state.history = [ReviewIteration(1, "NEEDS_WORK", "")]
    err = ReviewLaunchError("boom", retryable=True)
    with patch.object(review_loop, "_run_claude_review",
                      side_effect=[err, "Fixed.\n\n**PASS**"]) as run:
        result = _run(state, tmp_path)
    assert [h.iteration for h in result.history] == [1, 2]
    assert [c.kwargs["iteration"] for c in run.call_args_list] == [2, 2]
    assert result.iteration == 2


def test_restart_mid_backoff_continues_the_budget(tmp_path, monkeypatch):
    state = ReviewLoopState(
        pr_id=PR, iteration=1, retry_iteration=1, launch_attempts=1,
        next_retry_at=time.time() + 0.05)
    slept = []

    def fake_sleep(seconds, *_a, **_k):
        slept.append(seconds)

    monkeypatch.setattr(review_loop, "_interruptible_sleep", fake_sleep)
    with patch.object(review_loop, "_run_claude_review",
                      return_value="**PASS**") as run:
        result = _run(state, tmp_path)
    assert slept, "the remaining backoff should be honoured after a restart"
    assert run.call_args.kwargs["attempt"] == 2
    assert result.latest_verdict == VERDICT_PASS


# ---------------------------------------------------------------------------
# Artifact + classification
# ---------------------------------------------------------------------------

def test_launch_artifact_retains_complete_stderr(tmp_path):
    transcript = tmp_path / "review-pr-001-i1.jsonl"
    big = "container setup failed\n" + ("x" * 10000) + "\nlast actionable line"
    with patch.object(review_loop.subprocess, "run",
                      return_value=MagicMock(returncode=1, stdout="out",
                                             stderr=big)):
        with pytest.raises(ReviewLaunchError) as ei:
            review_loop._launch_review_window(
                PR, str(tmp_path), iteration=1, transcript=str(transcript),
                attempt=2, workdir=str(tmp_path / "wd"))
    err = ei.value
    assert err.retryable is True
    assert err.artifact and Path(err.artifact).exists()
    body = Path(err.artifact).read_text()
    assert "x" * 10000 in body
    assert "last actionable line" in body
    assert "--- stdout" in body and "out" in body
    assert "attempt: 2" in body
    # The UI error is concise and names the artifact.
    assert len(str(err)) < 500
    assert "artifact" in str(err)
    assert "last actionable line" in str(err)


def test_artifact_copies_the_failed_attempts_complete_prompt(tmp_path):
    wd = tmp_path / "wd"
    (wd / "pm" / "prompts").mkdir(parents=True)
    sid = str(uuid.uuid4())
    transcript = tmp_path / "review-pr-001-i1.jsonl"
    transcript.symlink_to(tmp_path / f"{sid}.jsonl")
    prompt = "REVIEW THIS\n" + ("instruction line\n" * 5000)
    (wd / "pm" / "prompts" / f"pm_prompt_{sid}.txt").write_text(prompt)
    with patch.object(review_loop.subprocess, "run",
                      return_value=MagicMock(returncode=1, stdout="",
                                             stderr="boom")):
        with pytest.raises(ReviewLaunchError) as ei:
            review_loop._launch_review_window(
                PR, str(tmp_path), iteration=1, transcript=str(transcript),
                workdir=str(wd))
    copies = list((tmp_path / "launch-artifacts").glob("*.prompt.txt"))
    assert len(copies) == 1
    assert copies[0].read_text() == prompt
    assert "prompt_copy" in Path(ei.value.artifact).read_text()


def test_artifact_does_not_copy_a_stale_sessions_prompt(tmp_path):
    """A launch that died before the child rewrote the iteration's symlink
    leaves the previous run's session in place.  Its prompt file is not this
    attempt's, so the artifact must say so instead of attaching it."""
    wd = tmp_path / "wd"
    (wd / "pm" / "prompts").mkdir(parents=True)
    stale = str(uuid.uuid4())
    transcript = tmp_path / "review-pr-001-i2.jsonl"
    transcript.symlink_to(tmp_path / f"{stale}.jsonl")
    (wd / "pm" / "prompts" / f"pm_prompt_{stale}.txt").write_text("old task")
    with patch.object(review_loop.subprocess, "run",
                      return_value=MagicMock(returncode=1, stdout="",
                                             stderr="boom")):
        with pytest.raises(ReviewLaunchError) as ei:
            review_loop._launch_review_window(
                PR, str(tmp_path), iteration=2, transcript=str(transcript),
                workdir=str(wd), stale_session_id=stale)
    assert not list((tmp_path / "launch-artifacts").glob("*.prompt.txt"))
    body = Path(ei.value.artifact).read_text()
    assert "prompt: (skipped" in body
    assert stale in body


def test_window_not_found_and_missing_transcript_are_retryable(tmp_path,
                                                               monkeypatch):
    from pm_core import tmux
    monkeypatch.setattr(review_loop, "_get_pm_session", lambda: "pm-s")
    monkeypatch.setattr(tmux, "session_exists", lambda _s: True)
    monkeypatch.setattr(review_loop, "_find_review_claude_pane",
                        lambda *a, **k: None)
    with patch.object(review_loop, "_launch_review_window"):
        with pytest.raises(ReviewLaunchError) as ei:
            review_loop._run_claude_review(PR, str(tmp_path), _pr(tmp_path),
                                           str(tmp_path / "i1.jsonl"))
    assert ei.value.retryable is True
    assert ei.value.reason == "window"
    assert Path(ei.value.artifact).exists()

    # Window found, but the child produced no transcript session id.
    monkeypatch.setattr(review_loop, "_find_review_claude_pane",
                        lambda *a, **k: "%9")
    with patch.object(review_loop, "_launch_review_window"):
        with pytest.raises(ReviewLaunchError) as ei:
            review_loop._run_claude_review(PR, str(tmp_path), _pr(tmp_path),
                                           str(tmp_path / "i1.jsonl"))
    assert ei.value.retryable is True
    assert ei.value.reason == "transcript"


def test_healthy_unrelated_review_continues_during_retry(tmp_path):
    """Two loops are independent: one retrying must not stall another."""
    import threading
    retrying = ReviewLoopState(pr_id="pr-bad")
    healthy = ReviewLoopState(pr_id="pr-good")
    err = ReviewLaunchError("boom", retryable=True)

    def fake_review(pr_id, *a, **k):
        if pr_id == "pr-bad":
            raise err
        return "**PASS**"

    def bad_pr():
        return {"id": "pr-bad", "title": "T", "branch": "pm/pr-bad",
                "status": "in_review", "workdir": str(tmp_path / "wd")}

    def good_pr():
        return {"id": "pr-good", "title": "T", "branch": "pm/pr-good",
                "status": "in_review", "workdir": str(tmp_path / "wd")}

    with patch.object(review_loop, "_run_claude_review", side_effect=fake_review), \
            patch.object(review_loop, "_discover_iteration",
                         lambda *a, **k: AttemptDiscovery("launch")), \
            patch.object(review_loop, "_pr_is_terminal", lambda *a, **k: False), \
            patch.object(review_loop, "_claim_launch", lambda *a, **k: True):
        t = threading.Thread(target=run_review_loop_sync,
                             args=(retrying, str(tmp_path), bad_pr()),
                             kwargs={"transcript_dir": str(tmp_path)})
        t.start()
        run_review_loop_sync(healthy, str(tmp_path), good_pr(),
                             transcript_dir=str(tmp_path))
        t.join(timeout=5)
    assert healthy.latest_verdict == VERDICT_PASS
    assert retrying.latest_verdict == VERDICT_LAUNCH_FAILED


def test_auth_failure_is_not_retryable(tmp_path):
    with patch.object(review_loop.subprocess, "run",
                      return_value=MagicMock(returncode=1, stdout="",
                                             stderr="401 unauthorized")):
        with pytest.raises(ReviewLaunchError) as ei:
            review_loop._launch_review_window(PR, str(tmp_path), iteration=1,
                                              transcript=str(tmp_path / "t.jsonl"))
    assert ei.value.retryable is False
    assert ei.value.reason == "auth"


def test_launch_timeout_is_retryable(tmp_path):
    import subprocess
    with patch.object(review_loop.subprocess, "run",
                      side_effect=subprocess.TimeoutExpired(["x"], 120,
                                                            stderr=b"slow")):
        with pytest.raises(ReviewLaunchError) as ei:
            review_loop._launch_review_window(PR, str(tmp_path), iteration=1,
                                              transcript=str(tmp_path / "t.jsonl"))
    assert ei.value.retryable is True
    assert ei.value.reason == "timeout"
    assert Path(ei.value.artifact).exists()


# ---------------------------------------------------------------------------
# Old-window removal + container setup failure (real subprocess boundary)
# ---------------------------------------------------------------------------

def test_old_window_then_container_failure_retries_the_same_command(tmp_path,
                                                                   monkeypatch):
    """The child killed the historical window and then container setup failed.

    The retry must issue the identical complete task (same iteration, loop
    id, transcript) and collect its verdict.
    """
    state = ReviewLoopState(pr_id=PR, loop_id="ab12")
    cmds = []

    def fake_run(cmd, **_kw):
        cmds.append(cmd)
        if len(cmds) == 1:
            return MagicMock(returncode=1, stdout="",
                             stderr="Failed to create container 'pm-review-pr-001'")
        return MagicMock(returncode=0, stdout="", stderr="")

    def fake_review(pr_id, pm_root, pr_data, *, iteration, loop_id,
                    transcript, attempt, **_kw):
        review_loop._launch_review_window(
            pr_id, pm_root, iteration=iteration, loop_id=loop_id,
            transcript=transcript, attempt=attempt,
            workdir=pr_data.get("workdir"))
        return "All good.\n\n**PASS**"

    monkeypatch.setattr(review_loop, "_run_claude_review", fake_review)
    with patch.object(review_loop.subprocess, "run", side_effect=fake_run):
        result = _run(state, tmp_path)
    assert len(cmds) == 2
    # Identical complete task on both attempts; only the attempt artifact
    # distinguishes them.
    assert cmds[0] == cmds[1]
    assert "--review-iteration" in cmds[0]
    assert cmds[0][cmds[0].index("--review-iteration") + 1] == "1"
    assert "--review-loop-id" in cmds[0]
    assert cmds[0][cmds[0].index("--review-loop-id") + 1] == "ab12"
    assert result.latest_verdict == VERDICT_PASS
    artifacts = list((tmp_path / "launch-artifacts").glob("*.log"))
    assert len(artifacts) == 1
    assert "Failed to create container" in artifacts[0].read_text()


# ---------------------------------------------------------------------------
# Real launch/recovery path: real transcript + hook + poller
# ---------------------------------------------------------------------------

def test_real_launch_recovery_collects_its_own_verdict(tmp_path, monkeypatch):
    """One real poller path: the retry's transcript + idle hook produce the
    verdict through the production hook/JSONL machinery."""
    from pm_core import hook_events, tmux

    hooks = tmp_path / "hooks"
    hooks.mkdir()
    monkeypatch.setattr(hook_events, "_HOOKS_BASE", hooks)
    monkeypatch.setattr(tmux, "pane_exists", lambda _p: True)
    monkeypatch.setattr(tmux, "capture_pane", lambda *_a, **_k: "")
    monkeypatch.setattr(tmux, "session_exists", lambda _s: True)
    monkeypatch.setattr(review_loop, "_get_pm_session", lambda: "pm-s")
    monkeypatch.setattr(review_loop, "_find_review_claude_pane",
                        lambda *a, **k: "%9")

    state = ReviewLoopState(pr_id=PR)
    sid = str(uuid.uuid4())
    native = tmp_path / f"{sid}.jsonl"
    attempts = []

    def fake_launch(pr_id, pm_root, *, iteration=0, loop_id="",
                    transcript=None, attempt=1, workdir=None,
                    stale_session_id=""):
        attempts.append(attempt)
        if attempt == 1:
            raise ReviewLaunchError("container setup failed", retryable=True,
                                    artifact=str(tmp_path / "a.log"))
        transcript_path = Path(transcript)
        transcript_path.symlink_to(native)
        native.write_text(json.dumps({
            "type": "assistant",
            "message": {"content": [{"type": "text",
                                     "text": "Looks good.\n\n**PASS**"}]},
        }) + "\n")
        (hooks / f"{sid}.json").write_text(json.dumps({
            "event_type": "idle_prompt",
            "timestamp": time.time() + 5,
        }))

    monkeypatch.setattr(review_loop, "_launch_review_window", fake_launch)
    result = _run(state, tmp_path)
    assert attempts == [1, 2]
    assert result.latest_verdict == VERDICT_PASS
    assert [h.iteration for h in result.history] == [1]


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def _make_symlink(tdir: Path, name: str, sid: str) -> Path:
    link = tdir / name
    link.symlink_to(tdir / f"{sid}.jsonl")
    return link


def test_discovery_without_a_window_launches(tmp_path, monkeypatch):
    monkeypatch.setattr(review_loop, "_discover_iteration", _ORIG_DISCOVER)
    monkeypatch.setattr(review_loop, "_get_pm_session", lambda: "pm-s")
    monkeypatch.setattr(review_loop, "_find_review_claude_pane",
                        lambda *a, **k: None)
    state = ReviewLoopState(pr_id=PR)
    disc = review_loop._discover_iteration(state, _pr(tmp_path),
                                           str(tmp_path), 1)
    assert disc.kind == "launch"


def test_discovery_adopts_our_failed_attempt(tmp_path, monkeypatch):
    monkeypatch.setattr(review_loop, "_discover_iteration", _ORIG_DISCOVER)
    sid = str(uuid.uuid4())
    _make_symlink(tmp_path, "review-pr-001-i1.jsonl", sid)
    monkeypatch.setattr(review_loop, "_get_pm_session", lambda: "pm-s")
    monkeypatch.setattr(review_loop, "_find_review_claude_pane",
                        lambda *a, **k: "%9")
    monkeypatch.setattr("pm_core.claude_launcher.pane_transcript_path",
                        lambda *_a, **_k: tmp_path / f"{sid}.jsonl")
    state = ReviewLoopState(pr_id=PR)
    disc = review_loop._discover_iteration(state, _pr(tmp_path),
                                           str(tmp_path), 1)
    assert disc.kind == "adopt"
    assert disc.transcript == str(tmp_path / "review-pr-001-i1.jsonl")


def test_discovery_adopts_another_drivers_live_session(tmp_path, monkeypatch):
    monkeypatch.setattr(review_loop, "_discover_iteration", _ORIG_DISCOVER)
    ours = str(uuid.uuid4())
    theirs = str(uuid.uuid4())
    _make_symlink(tmp_path, "review-pr-001-i1.jsonl", ours)
    monkeypatch.setattr(review_loop, "_get_pm_session", lambda: "pm-s")
    monkeypatch.setattr(review_loop, "_find_review_claude_pane",
                        lambda *a, **k: "%9")
    monkeypatch.setattr("pm_core.claude_launcher.pane_transcript_path",
                        lambda *_a, **_k: tmp_path / f"{theirs}.jsonl")
    state = ReviewLoopState(pr_id=PR)
    disc = review_loop._discover_iteration(state, _pr(tmp_path),
                                           str(tmp_path), 1)
    assert disc.kind == "adopt"
    assert disc.transcript == str(tmp_path / f"{theirs}.jsonl")


def test_discovery_treats_the_last_adopted_session_as_historical(
        tmp_path, monkeypatch):
    """An iteration whose verdict was adopted from another driver's session
    must remember it: the next iteration replaces that (still-live) pane
    instead of adopting its verdict a second time."""
    monkeypatch.setattr(review_loop, "_discover_iteration", _ORIG_DISCOVER)
    sid = str(uuid.uuid4())
    monkeypatch.setattr(review_loop, "_get_pm_session", lambda: "pm-s")
    monkeypatch.setattr(review_loop, "_find_review_claude_pane",
                        lambda *a, **k: "%9")
    monkeypatch.setattr("pm_core.claude_launcher.pane_transcript_path",
                        lambda *_a, **_k: tmp_path / f"{sid}.jsonl")
    state = ReviewLoopState(pr_id=PR, iteration=2, last_session_id=sid)
    disc = review_loop._discover_iteration(state, _pr(tmp_path),
                                           str(tmp_path), 2)
    assert disc.kind == "launch"


def test_adopted_verdict_records_the_session_as_historical(tmp_path,
                                                          monkeypatch):
    """A verdict adopted from another driver's pane — including one read by
    the pre-poll check — must be remembered as the iteration's session, or
    the next iteration adopts the same idle pane again."""
    from pm_core import hook_events

    sid = str(uuid.uuid4())
    transcript = tmp_path / f"{sid}.jsonl"
    transcript.write_text(json.dumps({
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": "**NEEDS_WORK**"}]},
    }) + "\n")
    monkeypatch.setattr(hook_events, "read_event",
                        lambda _sid: {"event_type": "idle_prompt"})
    monkeypatch.setattr(review_loop, "_discover_iteration", lambda *a, **k:
                        AttemptDiscovery("adopt", pane_id="%9",
                                         transcript=str(transcript),
                                         session_id=sid))
    state = ReviewLoopState(pr_id=PR)
    with patch.object(review_loop, "_poll_for_verdict") as poll:
        result = _run(state, tmp_path, max_iterations=1)
    poll.assert_not_called()
    assert result.last_session_id == sid
    assert [h.iteration for h in result.history] == [1]


def test_discovery_stands_down_for_another_loop(tmp_path, monkeypatch):
    monkeypatch.setattr(review_loop, "_discover_iteration", _ORIG_DISCOVER)
    theirs = str(uuid.uuid4())
    monkeypatch.setattr(review_loop, "_get_pm_session", lambda: "pm-s")
    monkeypatch.setattr(review_loop, "_find_review_claude_pane",
                        lambda *a, **k: "%9")
    monkeypatch.setattr("pm_core.claude_launcher.pane_transcript_path",
                        lambda *_a, **_k: tmp_path / f"{theirs}.jsonl")
    monkeypatch.setattr(review_loop, "_other_loop_owner",
                        lambda _s: "loop:other")
    state = ReviewLoopState(pr_id=PR)
    disc = review_loop._discover_iteration(state, _pr(tmp_path),
                                           str(tmp_path), 1)
    assert disc.kind == "other_owner"
    assert disc.owner == "loop:other"


def test_discovery_replaces_the_historical_window(tmp_path, monkeypatch):
    monkeypatch.setattr(review_loop, "_discover_iteration", _ORIG_DISCOVER)
    old = str(uuid.uuid4())
    _make_symlink(tmp_path, "review-pr-001-i1.jsonl", old)
    monkeypatch.setattr(review_loop, "_get_pm_session", lambda: "pm-s")
    monkeypatch.setattr(review_loop, "_find_review_claude_pane",
                        lambda *a, **k: "%9")
    monkeypatch.setattr("pm_core.claude_launcher.pane_transcript_path",
                        lambda *_a, **_k: tmp_path / f"{old}.jsonl")
    state = ReviewLoopState(pr_id=PR)
    # iteration 2: the live session belongs to iteration 1
    disc = review_loop._discover_iteration(state, _pr(tmp_path),
                                           str(tmp_path), 2)
    assert disc.kind == "launch"


def test_discovery_adopts_another_drivers_pane_after_our_attempt(tmp_path,
                                                                monkeypatch):
    """A route/native recovery racing a scheduled retry must be adopted, not
    killed by a second ``--fresh`` launch."""
    monkeypatch.setattr(review_loop, "_discover_iteration", _ORIG_DISCOVER)
    theirs = str(uuid.uuid4())
    monkeypatch.setattr(review_loop, "_get_pm_session", lambda: "pm-s")
    monkeypatch.setattr(review_loop, "_find_review_claude_pane",
                        lambda *a, **k: "%9")
    monkeypatch.setattr(review_loop, "_other_loop_owner", lambda _s: "")
    monkeypatch.setattr("pm_core.claude_launcher.pane_transcript_path",
                        lambda *_a, **_k: tmp_path / f"{theirs}.jsonl")
    pr = _pr(tmp_path)

    # Before this loop has launched the iteration, a live pane is the
    # historical window: a fresh launch replaces it.
    state = ReviewLoopState(pr_id=PR, iteration=2)
    disc = review_loop._discover_iteration(state, pr, str(tmp_path), 2,
                                           allow_recovery=False)
    assert disc.kind == "launch"

    # After this loop's own attempt failed without a transcript, a live
    # session is the recovery (or another driver's launch): adopt it.
    state = ReviewLoopState(pr_id=PR, iteration=2,
                            iteration_attempted=True, launch_attempts=1)
    disc = review_loop._discover_iteration(state, pr, str(tmp_path), 2,
                                           allow_recovery=True)
    assert disc.kind == "adopt"
    assert disc.pane_id == "%9"
    assert disc.transcript == str(tmp_path / f"{theirs}.jsonl")


def test_discovery_never_adopts_a_historical_pane_after_a_failed_attempt(
        tmp_path, monkeypatch):
    """A failed launch can write this iteration's symlink and still leave the
    previous iteration's window live (its removal failed).  That window runs
    an *earlier* iteration's session, so its verdict is not this iteration's:
    replace the window instead of recording a verdict for a review that never
    ran."""
    monkeypatch.setattr(review_loop, "_discover_iteration", _ORIG_DISCOVER)
    old = str(uuid.uuid4())    # iteration 1's live session (the stale window)
    ours = str(uuid.uuid4())   # iteration 2's symlink, written by the failure
    _make_symlink(tmp_path, "review-pr-001-i2.jsonl", ours)
    (tmp_path / f"{old}.jsonl").write_text(json.dumps({
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": "old\n\n**PASS**"}]},
    }) + "\n")
    monkeypatch.setattr(review_loop, "_get_pm_session", lambda: "pm-s")
    monkeypatch.setattr(review_loop, "_find_review_claude_pane",
                        lambda *a, **k: "%9")
    monkeypatch.setattr(review_loop, "_other_loop_owner", lambda _s: "")
    monkeypatch.setattr("pm_core.claude_launcher.pane_transcript_path",
                        lambda *_a, **_k: tmp_path / f"{old}.jsonl")
    state = ReviewLoopState(pr_id=PR, iteration=2, iteration_attempted=True,
                            launch_attempts=1, last_session_id=old)
    disc = review_loop._discover_iteration(state, _pr(tmp_path),
                                           str(tmp_path), 2,
                                           allow_recovery=True)
    assert disc.kind == "launch"


def test_retry_never_adopts_a_historical_panes_verdict(tmp_path, monkeypatch):
    """End-to-end form of the same hole: the retry must run its own review
    for the iteration, not inherit the stale window's verdict."""
    monkeypatch.setattr(review_loop, "_discover_iteration", _ORIG_DISCOVER)
    monkeypatch.setattr(review_loop, "_get_pm_session", lambda: "pm-s")
    monkeypatch.setattr(review_loop, "_find_review_claude_pane",
                        lambda *a, **k: "%9")
    monkeypatch.setattr(review_loop, "_other_loop_owner", lambda _s: "")
    old = str(uuid.uuid4())
    (tmp_path / f"{old}.jsonl").write_text(json.dumps({
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": "old\n\n**PASS**"}]},
    }) + "\n")
    monkeypatch.setattr("pm_core.claude_launcher.pane_transcript_path",
                        lambda *_a, **_k: tmp_path / f"{old}.jsonl")

    state = ReviewLoopState(pr_id=PR, iteration=1, last_session_id=old)
    state.history.append(ReviewIteration(iteration=1, verdict="NEEDS_WORK",
                                         output="iteration 1"))
    err = ReviewLaunchError("container setup failed", retryable=True)

    def fake_review(*_a, **kw):
        # The child wrote the iteration-2 symlink before the parent-side
        # launch failed, leaving the historical window live.
        link = tmp_path / "review-pr-001-i2.jsonl"
        if not link.is_symlink():
            _make_symlink(tmp_path, "review-pr-001-i2.jsonl",
                          str(uuid.uuid4()))
        raise err

    with patch.object(review_loop, "_run_claude_review",
                      side_effect=fake_review) as run:
        result = _run(state, tmp_path)
    assert run.call_count == 3, "the stale window's verdict must not be adopted"
    assert [(h.iteration, h.verdict) for h in result.history] == [
        (1, "NEEDS_WORK")]
    assert result.latest_verdict == VERDICT_LAUNCH_FAILED


def test_retry_never_adopts_the_window_that_was_live_at_episode_start(
        tmp_path, monkeypatch):
    """A review window already open when the episode started is the
    historical window, not this iteration's attempt.

    Iteration 1 of a fresh loop has no ``last_session_id`` and its (new)
    transcript dir holds no earlier symlink, so nothing identifies that
    pane as old.  A first attempt that fails *before* ``--fresh`` replaces
    the window (route down, workdir gone, a tmux error on the kill) then
    leaves it live; the retry must replace it rather than record its older
    review's verdict for an iteration that never ran.
    """
    monkeypatch.setattr(review_loop, "_discover_iteration", _ORIG_DISCOVER)
    monkeypatch.setattr(review_loop, "_get_pm_session", lambda: "pm-s")
    monkeypatch.setattr(review_loop, "_find_review_claude_pane",
                        lambda *a, **k: "%9")
    monkeypatch.setattr(review_loop, "_other_loop_owner", lambda _s: "")
    from pm_core import tmux
    monkeypatch.setattr(tmux, "session_exists", lambda _s: True)
    old = str(uuid.uuid4())  # a pre-existing review of older code
    (tmp_path / f"{old}.jsonl").write_text(json.dumps({
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": "old\n\n**PASS**"}]},
    }) + "\n")
    monkeypatch.setattr("pm_core.claude_launcher.pane_transcript_path",
                        lambda *_a, **_k: tmp_path / f"{old}.jsonl")
    launches = []

    def fake_launch(pr_id, pm_root, *, iteration=0, loop_id="",
                    transcript=None, attempt=1, workdir=None,
                    stale_session_id=""):
        launches.append(attempt)
        raise ReviewLaunchError("container setup failed", retryable=True)

    monkeypatch.setattr(review_loop, "_launch_review_window", fake_launch)
    state = ReviewLoopState(pr_id=PR)
    result = _run(state, tmp_path)
    assert launches == [1, 2, 3], (
        "the pre-existing window's verdict must not be adopted")
    assert result.history == []
    assert result.latest_verdict == VERDICT_LAUNCH_FAILED
    assert result.launch_retryable is True
    assert state.stale_pane_session_id == old


def test_discovery_replaces_the_window_that_was_live_at_episode_start(
        tmp_path, monkeypatch):
    """Discovery-level form of the same guard (breadcrumb-restored state)."""
    monkeypatch.setattr(review_loop, "_discover_iteration", _ORIG_DISCOVER)
    sid = str(uuid.uuid4())
    monkeypatch.setattr(review_loop, "_get_pm_session", lambda: "pm-s")
    monkeypatch.setattr(review_loop, "_find_review_claude_pane",
                        lambda *a, **k: "%9")
    monkeypatch.setattr(review_loop, "_other_loop_owner", lambda _s: "")
    monkeypatch.setattr("pm_core.claude_launcher.pane_transcript_path",
                        lambda *_a, **_k: tmp_path / f"{sid}.jsonl")
    state = ReviewLoopState(pr_id=PR, iteration=1,
                            iteration_attempted=True, launch_attempts=1,
                            stale_pane_session_id=sid)
    disc = review_loop._discover_iteration(state, _pr(tmp_path),
                                           str(tmp_path), 1,
                                           allow_recovery=True)
    assert disc.kind == "launch"


def test_discovery_still_adopts_a_session_started_after_the_stale_one(
        tmp_path, monkeypatch):
    """The stale-pane guard must not swallow the case it was traded against:
    a route/other driver launching the same iteration *after* the episode
    started is a new owner and is adopted, not killed."""
    monkeypatch.setattr(review_loop, "_discover_iteration", _ORIG_DISCOVER)
    old = str(uuid.uuid4())
    fresh = str(uuid.uuid4())
    monkeypatch.setattr(review_loop, "_get_pm_session", lambda: "pm-s")
    monkeypatch.setattr(review_loop, "_find_review_claude_pane",
                        lambda *a, **k: "%9")
    monkeypatch.setattr(review_loop, "_other_loop_owner", lambda _s: "")
    monkeypatch.setattr("pm_core.claude_launcher.pane_transcript_path",
                        lambda *_a, **_k: tmp_path / f"{fresh}.jsonl")
    state = ReviewLoopState(pr_id=PR, iteration=1,
                            iteration_attempted=True, launch_attempts=1,
                            stale_pane_session_id=old)
    disc = review_loop._discover_iteration(state, _pr(tmp_path),
                                           str(tmp_path), 1,
                                           allow_recovery=True)
    assert disc.kind == "adopt"
    assert disc.session_id == fresh


def test_episode_start_snapshots_the_live_review_window(tmp_path, monkeypatch):
    """The stale-pane guard's snapshot: the session running in the review
    window when the episode starts is what rediscovery must treat as the
    historical window.  A missing window/session is "nothing to exclude"."""
    sid = str(uuid.uuid4())
    monkeypatch.setattr(review_loop, "_get_pm_session", lambda: "pm-s")
    monkeypatch.setattr(review_loop, "_find_review_claude_pane",
                        lambda *a, **k: "%9")
    monkeypatch.setattr("pm_core.claude_launcher.pane_transcript_path",
                        lambda *_a, **_k: tmp_path / f"{sid}.jsonl")
    assert review_loop._live_review_pane_session(_pr(tmp_path)) == sid

    # No pm session / no review window / an unresolvable pane: total, "".
    monkeypatch.setattr(review_loop, "_get_pm_session", lambda: None)
    assert review_loop._live_review_pane_session(_pr(tmp_path)) == ""
    monkeypatch.setattr(review_loop, "_get_pm_session", lambda: "pm-s")
    monkeypatch.setattr(review_loop, "_find_review_claude_pane",
                        lambda *a, **k: None)
    assert review_loop._live_review_pane_session(_pr(tmp_path)) == ""
    monkeypatch.setattr(review_loop, "_find_review_claude_pane",
                        lambda *a, **k: "%9")
    monkeypatch.setattr("pm_core.claude_launcher.pane_transcript_path",
                        lambda *_a, **_k: None)
    assert review_loop._live_review_pane_session(_pr(tmp_path)) == ""


def test_discovery_reports_a_landed_verdict(tmp_path, monkeypatch):
    monkeypatch.setattr(review_loop, "_discover_iteration", _ORIG_DISCOVER)
    sid = str(uuid.uuid4())
    _make_symlink(tmp_path, "review-pr-001-i1.jsonl", sid)
    (tmp_path / f"{sid}.jsonl").write_text(json.dumps({
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": "**PASS**"}]},
    }) + "\n")
    monkeypatch.setattr(review_loop, "_get_pm_session", lambda: None)
    state = ReviewLoopState(pr_id=PR)
    disc = review_loop._discover_iteration(state, _pr(tmp_path),
                                           str(tmp_path), 1)
    assert disc.kind == "verdict"
    assert "PASS" in (disc.output or "")


def test_discovery_ignores_a_transcript_this_loop_never_launched(tmp_path,
                                                                 monkeypatch):
    """The transcript dir outlives a loop, so a symlink can be a previous
    run's iteration N.  Before this loop launches iteration N, that verdict
    is not ours to adopt."""
    monkeypatch.setattr(review_loop, "_discover_iteration", _ORIG_DISCOVER)
    sid = str(uuid.uuid4())
    _make_symlink(tmp_path, "review-pr-001-i1.jsonl", sid)
    (tmp_path / f"{sid}.jsonl").write_text(json.dumps({
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": "**PASS**"}]},
    }) + "\n")
    monkeypatch.setattr(review_loop, "_get_pm_session", lambda: None)
    state = ReviewLoopState(pr_id=PR)
    disc = review_loop._discover_iteration(state, _pr(tmp_path),
                                           str(tmp_path), 1,
                                           allow_recovery=False)
    assert disc.kind == "launch"


def test_fresh_loop_never_adopts_a_previous_runs_verdict(tmp_path, monkeypatch):
    """A new loop on the same PR (shared ``manual-<token>`` transcript dir)
    must run its own review, not inherit the last run's PASS."""
    monkeypatch.setattr(review_loop, "_discover_iteration", _ORIG_DISCOVER)
    sid = str(uuid.uuid4())
    _make_symlink(tmp_path, "review-pr-001-i1.jsonl", sid)
    (tmp_path / f"{sid}.jsonl").write_text(json.dumps({
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": "old\n\n**PASS**"}]},
    }) + "\n")
    monkeypatch.setattr(review_loop, "_get_pm_session", lambda: None)
    state = ReviewLoopState(pr_id=PR)
    with patch.object(review_loop, "_run_claude_review",
                      return_value="fresh\n\n**NEEDS_WORK**") as run:
        result = _run(state, tmp_path, max_iterations=1)
    assert run.call_count == 1
    assert result.latest_verdict == VERDICT_NEEDS_WORK
    assert [(h.iteration, h.verdict) for h in result.history] == [
        (1, "NEEDS_WORK")]


def test_retry_adopts_a_verdict_that_landed_after_the_failure(tmp_path,
                                                              monkeypatch):
    """After our own failed attempt, a transcript IT created IS adopted."""
    monkeypatch.setattr(review_loop, "_discover_iteration", _ORIG_DISCOVER)
    monkeypatch.setattr(review_loop, "_get_pm_session", lambda: None)
    sid = str(uuid.uuid4())
    link = tmp_path / "review-pr-001-i1.jsonl"
    state = ReviewLoopState(pr_id=PR)
    err = ReviewLaunchError("boom", retryable=True)

    def fake_review(*_a, **_kw):
        # The child wrote the transcript (Claude started) before the
        # parent-side launch failed, then the recovery landed a verdict.
        link.symlink_to(tmp_path / f"{sid}.jsonl")
        (tmp_path / f"{sid}.jsonl").write_text(json.dumps({
            "type": "assistant",
            "message": {"content": [{"type": "text",
                                     "text": "recovered\n\n**PASS**"}]},
        }) + "\n")
        raise err

    with patch.object(review_loop, "_run_claude_review",
                      side_effect=fake_review) as run:
        result = _run(state, tmp_path)
    assert run.call_count == 1
    assert result.latest_verdict == VERDICT_PASS
    assert [h.iteration for h in result.history] == [1]


def test_retry_never_adopts_a_previous_runs_transcript(tmp_path, monkeypatch):
    """A launch that fails *before* the child writes its transcript leaves
    the shared dir's older iteration-N symlink in place.  Its verdict is a
    previous run's, so it must not be recorded as this iteration's — the
    loop retries and then reports LAUNCH_FAILED, never a fabricated PASS."""
    monkeypatch.setattr(review_loop, "_discover_iteration", _ORIG_DISCOVER)
    monkeypatch.setattr(review_loop, "_get_pm_session", lambda: None)
    sid = str(uuid.uuid4())
    _make_symlink(tmp_path, "review-pr-001-i1.jsonl", sid)
    (tmp_path / f"{sid}.jsonl").write_text(json.dumps({
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": "old\n\n**PASS**"}]},
    }) + "\n")
    state = ReviewLoopState(pr_id=PR)
    err = ReviewLaunchError("container setup failed", retryable=True)
    with patch.object(review_loop, "_run_claude_review", side_effect=err) as run:
        result = _run(state, tmp_path)
    assert run.call_count == 3, "no verdict may be adopted from the old run"
    assert result.latest_verdict == VERDICT_LAUNCH_FAILED
    assert result.history == []


# ---------------------------------------------------------------------------
# Serialized launch lease (runtime_state)
# ---------------------------------------------------------------------------

def test_launch_lease_is_exclusive_and_expires():
    from pm_core import runtime_state as rs
    assert rs.claim_action_lease("pr-lease", "review-loop", "loop:a", 60)
    assert rs.claim_action_lease("pr-lease", "review-loop", "loop:a", 60)
    assert not rs.claim_action_lease("pr-lease", "review-loop", "loop:b", 60)
    assert rs.get_action_lease("pr-lease", "review-loop", 60)["owner"] == "loop:a"
    # An expired lease can be taken over.
    assert rs.claim_action_lease("pr-lease", "review-loop", "loop:b", 0)
    assert rs.get_action_lease("pr-lease", "review-loop", 60)["owner"] == "loop:b"
    rs.release_action_lease("pr-lease", "review-loop", "loop:a")
    assert rs.get_action_lease("pr-lease", "review-loop", 60)["owner"] == "loop:b"
    rs.release_action_lease("pr-lease", "review-loop", "loop:b")
    assert rs.get_action_lease("pr-lease", "review-loop", 60) is None


def test_release_without_a_matching_owner_leaves_no_stub_entry():
    """Releasing a lease this owner never held must not create a
    ``{updated_at}`` action stub (a phantom runs-popup entry)."""
    from pm_core import runtime_state as rs
    rs.release_action_lease("pr-stub", "review-loop", "loop:x")
    assert rs.get_action_state("pr-stub", "review-loop") == {}


def test_lease_keepalive_claims_on_the_first_check(monkeypatch):
    """The restart-handoff adopt path polls a live review without going
    through ``_claim_launch``; it must own the lease from the first check,
    not ``_LEASE_REFRESH_SECONDS`` later."""
    state = ReviewLoopState(pr_id=PR)
    claims: list = []
    monkeypatch.setattr("pm_core.runtime_state.claim_action_lease",
                        lambda *a, **k: claims.append(a) or True)
    check = review_loop._lease_keepalive(state)
    assert check() is False
    assert claims, "the adopt path must claim the launch lease immediately"


def test_review_loop_owns_launch_only_for_loop_leases():
    from pm_core import runtime_state as rs
    assert review_loop.review_loop_owns_launch("pr-own") == ""
    rs.claim_action_lease("pr-own", "review-loop", "auto-sequence:1", 60)
    assert review_loop.review_loop_owns_launch("pr-own") == ""
    rs.claim_action_lease("pr-loop", "review-loop", "loop:ab12", 60)
    assert review_loop.review_loop_owns_launch("pr-loop") == "loop:ab12"


def test_claim_launch_fails_open_only_without_a_live_loop_owner(monkeypatch):
    """A lease file that cannot be written must not strand the launch; a
    live *other loop* must still win."""
    state = ReviewLoopState(pr_id=PR)
    monkeypatch.setattr(review_loop, "_claim_launch", _ORIG_CLAIM)
    monkeypatch.setattr(review_loop, "_other_loop_owner", lambda _s: "")
    with patch("pm_core.runtime_state.claim_action_lease",
               return_value=False):
        assert review_loop._claim_launch(state, 1, 1) is True
    monkeypatch.setattr(review_loop, "_other_loop_owner",
                        lambda _s: "loop:other")
    with patch("pm_core.runtime_state.claim_action_lease",
               return_value=False):
        assert review_loop._claim_launch(state, 1, 1) is False


def test_claim_wait_stops_when_the_pr_closes(monkeypatch):
    """A merge/close during the bounded wait for another loop's lease must
    end the wait (the caller reports CLOSED) instead of claiming the freed
    lease and launching a review for a dead PR."""
    state = ReviewLoopState(pr_id=PR)
    monkeypatch.setattr(review_loop, "REVIEW_LAUNCH_CLAIM_WAIT", 30.0)
    claims: list = []
    sleeps: list = []
    monkeypatch.setattr(review_loop, "_claim_launch",
                        lambda *a, **k: claims.append(a) or False)
    monkeypatch.setattr(review_loop, "_pr_is_terminal", lambda *a, **k: True)

    def fake_sleep(*_a, **_k):
        sleeps.append(1)
        if len(sleeps) > 3:
            raise AssertionError("kept waiting after the PR closed")

    monkeypatch.setattr(review_loop, "_interruptible_sleep", fake_sleep)

    assert review_loop._wait_for_claim(state, "/root", 1) is False
    assert claims == []
    assert len(sleeps) == 1


def test_running_progress_only_names_a_retry_after_the_first_attempt():
    """``launch_attempts`` is 1 for a normal first launch; the runs popup
    must not label every running review a launch retry."""
    from pm_core import autostart_state as st
    first = ReviewLoopState(pr_id=PR, running=True, iteration=2,
                            launch_attempts=1)
    assert st._progress({"review": st.review_progress_input(first)}) == \
        "review #2"
    retry = ReviewLoopState(pr_id=PR, running=True, iteration=2,
                            launch_attempts=2,
                            last_launch_error="container setup failed")
    assert st._progress({"review": st.review_progress_input(retry)}) == \
        "review #2 (launch retry 2)"


def test_follow_up_wait_refreshes_the_launch_lease(tmp_path, monkeypatch):
    """An INPUT_REQUIRED wait can outlast the lease TTL; the loop must keep
    ownership (and stop refreshing once it is stopping)."""
    state = ReviewLoopState(pr_id=PR, iteration=1)
    state._transcript_dir = str(tmp_path)
    captured: dict = {}

    def fake_wait(session, window, transcript, **kw):
        captured["stop"] = kw["stop_check"]
        return None

    monkeypatch.setattr(review_loop, "_get_pm_session", lambda: "pm-s")
    monkeypatch.setattr(review_loop, "_wait_for_follow_up_shared", fake_wait)
    monkeypatch.setattr(review_loop, "_LEASE_REFRESH_SECONDS", 0.0)
    claims: list = []
    monkeypatch.setattr("pm_core.runtime_state.claim_action_lease",
                        lambda *a, **k: claims.append(a) or True)

    assert review_loop._wait_for_follow_up_verdict(_pr(tmp_path),
                                                   state) is None
    stop = captured["stop"]
    assert stop() is False
    assert claims, "the follow-up wait must keep the launch lease alive"

    state.stop_requested = True
    assert stop() is True
    n = len(claims)
    stop()
    assert len(claims) == n, "a stopping loop must not refresh the lease"


def test_action_status_badge_flags_a_retryable_launch_failure():
    """The ``pm session`` row must say a launch failure is retryable (it
    will be retried) instead of looking like a dead loop, and must not
    flag a HOLD as retryable."""
    from pm_core import runtime_state as rs
    from pm_core.cli.session import _format_action_status

    rs.set_action_state("pr-badge", "review-loop", "failed", iteration=2,
                        verdict=VERDICT_LAUNCH_FAILED, retryable=True,
                        attempts=3, error="container setup failed")
    assert _format_action_status("pr-badge", "review-loop") == \
        " [failed; retryable]"
    rs.set_action_state("pr-badge-hold", "review-loop", "failed",
                        iteration=2, verdict=VERDICT_HOLD)
    assert _format_action_status("pr-badge-hold", "review-loop") == " [failed]"


def test_autostart_status_shows_the_retryable_launch_failure():
    """`pm autostart status` must name the failure and its artifact, not
    report the PR as merely stopped."""
    from pm_core import autostart_state as st
    state = ReviewLoopState(
        pr_id=PR, running=False, iteration=2,
        latest_verdict=VERDICT_LAUNCH_FAILED, launch_retryable=True,
        launch_attempts=3, last_launch_error="container setup failed",
        last_launch_artifact="/tmp/a.log")
    status = st.build_status({
        "prs": [{"id": PR, "title": "T", "status": "in_review",
                 "workdir": "/tmp/wd"}],
        "targets": {PR: {}},
        "enabled": True,
        "review_loops": {PR: st.review_progress_input(state)},
    })
    run = next(r for r in status["runs"] if r["pr_id"] == PR)
    assert run["state"] == "failed"
    assert "review launch failed (retryable)" in run["reason"]
    assert "container setup failed" in run["reason"]
    assert "/tmp/a.log" in run["reason"]


def test_autostart_status_reports_the_hold_prompt_not_a_stale_launch_error():
    """The live status input must name the trust prompt a HOLD is sitting
    at, matching the runtime_state mirror — not an earlier attempt's launch
    error from the same episode."""
    from pm_core import autostart_state as st
    state = ReviewLoopState(
        pr_id=PR, running=False, iteration=2,
        latest_verdict=VERDICT_HOLD,
        latest_output="workspace trust prompt in review pane",
        last_launch_error="container setup failed",
        last_launch_artifact="/tmp/stale-attempt.log")
    status = st.build_status({
        "prs": [{"id": PR, "title": "T", "status": "in_review",
                 "workdir": "/tmp/wd"}],
        "targets": {PR: {}},
        "enabled": True,
        "review_loops": {PR: st.review_progress_input(state)},
    })
    run = next(r for r in status["runs"] if r["pr_id"] == PR)
    assert run["state"] == "failed"
    assert "trust prompt" in run["reason"]
    assert "container setup failed" not in run["reason"]
    # The artifact belongs to the failed attempt, not to the hold; the live
    # status input must not attach it (matching the runtime_state mirror).
    assert run["review"]["artifact"] == ""


def test_autostart_status_does_not_repeat_the_artifact_path():
    """The concise launch error already ends with "(artifact: …)"; the
    status reason must not append "[artifact: …]" a second time."""
    from pm_core import autostart_state as st
    state = ReviewLoopState(
        pr_id=PR, running=False, iteration=2,
        latest_verdict=VERDICT_LAUNCH_FAILED, launch_retryable=True,
        launch_attempts=3,
        last_launch_error=("Review window launch failed (rc=1): boom "
                           "(artifact: /tmp/run/launch-artifacts/a.log)"),
        last_launch_artifact="/tmp/run/launch-artifacts/a.log")
    status = st.build_status({
        "prs": [{"id": PR, "title": "T", "status": "in_review",
                 "workdir": "/tmp/wd"}],
        "targets": {PR: {}},
        "enabled": True,
        "review_loops": {PR: st.review_progress_input(state)},
    })
    run = next(r for r in status["runs"] if r["pr_id"] == PR)
    assert run["state"] == "failed"
    assert "review launch failed (retryable)" in run["reason"]
    assert run["reason"].count("/tmp/run/launch-artifacts/a.log") == 1
    # The JSON entry still carries the artifact on its own field.
    assert run["review"]["artifact"] == "/tmp/run/launch-artifacts/a.log"


def test_autostart_status_keeps_the_retry_evidence_while_the_retry_runs():
    """A loop sleeping out the backoff has no verdict yet; the retry episode
    must stay visible in the status input (this is the stranding state the
    retry exists to surface)."""
    from pm_core import autostart_state as st
    state = ReviewLoopState(
        pr_id=PR, running=True, iteration=1, latest_verdict="",
        launch_retryable=True, launch_attempts=2,
        last_launch_error="container setup failed",
        last_launch_artifact="/tmp/attempt2.log")
    entry = st.review_progress_input(state)
    assert entry["running"] is True
    assert entry["retryable"] is True
    assert entry["attempts"] == 2
    assert entry["error"] == "container setup failed"
    assert entry["artifact"] == "/tmp/attempt2.log"


def test_autostart_status_does_not_report_a_cancelled_loop_as_retryable():
    """A user stop during the retry backoff ends KILLED; auto-start never
    re-arms it, so `pm autostart status` must not keep the earlier attempts'
    retry evidence (a cancelled loop is not "retryable")."""
    from pm_core import autostart_state as st
    state = ReviewLoopState(
        pr_id=PR, running=False, iteration=1,
        latest_verdict=VERDICT_KILLED, launch_retryable=True,
        launch_attempts=2, last_launch_error="container setup failed",
        last_launch_artifact="/tmp/stale-attempt.log")
    status = st.build_status({
        "prs": [{"id": PR, "title": "T", "status": "in_review",
                 "workdir": "/tmp/wd"}],
        "targets": {PR: {}},
        "enabled": True,
        "review_loops": {PR: st.review_progress_input(state)},
    })
    run = next(r for r in status["runs"] if r["pr_id"] == PR)
    assert run["state"] == "failed"
    assert "review loop ended KILLED" in run["reason"]
    assert run["review"]["verdict"] == VERDICT_KILLED
    assert run["review"]["retryable"] is False
    assert run["review"]["artifact"] == ""
    assert run["review"]["error"] == ""


# ---------------------------------------------------------------------------
# Breadcrumb persistence of the retry episode
# ---------------------------------------------------------------------------

def test_breadcrumb_round_trips_retry_episode(tmp_path):
    from pm_core.tui import auto_start
    state = ReviewLoopState(
        pr_id=PR, running=True, iteration=2, loop_id="ab12",
        retry_iteration=2, launch_attempts=2,
        next_retry_at=time.time() + 30, last_launch_error="boom",
        last_launch_artifact="/tmp/a.log", launch_retryable=True,
        retry_episodes=1, retry_ready_at=time.time() + 60,
        last_session_id="sid-1",
        iteration_attempted=True,
        stale_session_id="sid-0",
        stale_pane_session_id="sid-pane-0",
        _transcript_dir=str(tmp_path),
    )
    app = MagicMock()
    app._auto_start = True
    app._auto_start_targets = {PR: {}}
    app._auto_start_all = False
    app._auto_start_run_id = "run"
    app._review_loops = {PR: state}
    app._root = tmp_path
    app._stop_before_merge = set()
    app._data = {"prs": []}
    from pm_core.watcher_manager import WatcherManager
    app._watcher_manager = WatcherManager()
    app._review_loop_timer = None
    (tmp_path / "merge-restart").touch()

    with patch("pm_core.tui.auto_start.pm_home", return_value=tmp_path), \
         patch("pm_core.tui.watcher_ui.is_running", return_value=False):
        auto_start.save_breadcrumb(app)
    data = json.loads((tmp_path / "autostart-resume.json").read_text())
    loop = data["review_loops"][PR]
    assert loop["launch_attempts"] == 2
    assert loop["retry_iteration"] == 2
    assert loop["launch_retryable"] is True
    assert loop["last_launch_artifact"] == "/tmp/a.log"
    assert loop["last_session_id"] == "sid-1"
    assert loop["iteration_attempted"] is True
    assert loop["stale_pane_session_id"] == "sid-pane-0"


# ---------------------------------------------------------------------------
# Auto-start re-arm (no stranded target)
# ---------------------------------------------------------------------------

def _auto_app(tmp_path, state):
    app = MagicMock()
    app._auto_start = True
    app._auto_start_targets = {PR: {}}
    app._auto_start_all = False
    app._auto_start_run_id = "run"
    app._review_loops = {PR: state}
    app._qa_loops = {}
    app._root = tmp_path
    app._data = {"prs": [{"id": PR, "status": "in_review",
                          "workdir": str(tmp_path)}],
                 "project": {}}
    app._stop_before_merge = set()
    app._session_name = "pm-test"
    app._review_retry_timer = None
    return app


def test_auto_start_rearms_retryable_failure(tmp_path):
    from pm_core.tui import auto_start
    state = ReviewLoopState(pr_id=PR, running=False,
                            latest_verdict=VERDICT_LAUNCH_FAILED,
                            launch_retryable=True, retry_ready_at=0,
                            retry_episodes=0, iteration=1,
                            _transcript_dir=str(tmp_path))
    app = _auto_app(tmp_path, state)
    with patch("pm_core.tui.review_loop_ui._start_loop") as start, \
            patch("pm_core.tmux.in_tmux", return_value=True):
        auto_start._auto_start_review_loops(app, app._data["prs"])
    start.assert_called_once()
    assert start.call_args.kwargs["resume_state"] is state
    assert state.launch_attempts == 0
    assert state.retry_episodes == 1


def test_auto_start_rearm_clears_the_retry_notice_key(tmp_path):
    """The re-arm starts a new retry episode, whose attempts restart at 1.
    The per-episode notice key must be cleared, or its attempt 2 would look
    already-announced (the previous episode announced attempt 2) and the
    user would never hear about the new episode's retry."""
    from pm_core.tui import auto_start
    state = ReviewLoopState(pr_id=PR, running=False,
                            latest_verdict=VERDICT_LAUNCH_FAILED,
                            launch_retryable=True, retry_ready_at=0,
                            retry_episodes=0, iteration=1,
                            launch_attempts=3, _ui_notified_retry=3,
                            _transcript_dir=str(tmp_path))
    app = _auto_app(tmp_path, state)
    with patch("pm_core.tui.review_loop_ui._start_loop") as start, \
            patch("pm_core.tmux.in_tmux", return_value=True):
        auto_start._auto_start_review_loops(app, app._data["prs"])
    start.assert_called_once()
    assert state._ui_notified_retry == 0


def test_auto_start_rearm_restores_the_notice_key_when_it_cannot_start(
        tmp_path):
    """A bail-out restores the whole episode, including the notice key, so
    the still-visible failure is not re-announced later."""
    from pm_core.tui import auto_start
    state = ReviewLoopState(pr_id=PR, running=False,
                            latest_verdict=VERDICT_LAUNCH_FAILED,
                            launch_retryable=True, retry_ready_at=0,
                            retry_episodes=1, iteration=1,
                            launch_attempts=3, _ui_notified_retry=3,
                            _transcript_dir=str(tmp_path))
    app = _auto_app(tmp_path, state)
    with patch("pm_core.tui.review_loop_ui._start_loop",
               return_value=False), \
            patch("pm_core.tmux.in_tmux", return_value=True):
        auto_start._auto_start_review_loops(app, app._data["prs"])
    assert state.retry_episodes == 1
    assert state.launch_retryable is True
    assert state._ui_notified_retry == 3


def test_auto_start_does_not_rearm_killed_or_cooldown(tmp_path):
    from pm_core.tui import auto_start
    killed = ReviewLoopState(pr_id=PR, running=False,
                             latest_verdict=VERDICT_KILLED)
    app = _auto_app(tmp_path, killed)
    with patch("pm_core.tui.review_loop_ui._start_loop") as start:
        auto_start._auto_start_review_loops(app, app._data["prs"])
    start.assert_not_called()

    cooling = ReviewLoopState(
        pr_id=PR, running=False, latest_verdict=VERDICT_LAUNCH_FAILED,
        launch_retryable=True, retry_ready_at=time.time() + 60)
    app = _auto_app(tmp_path, cooling)
    with patch("pm_core.tui.review_loop_ui._start_loop") as start, \
            patch("pm_core.tmux.in_tmux", return_value=True):
        auto_start._auto_start_review_loops(app, app._data["prs"])
    start.assert_not_called()
    # The cooldown keeps a timer armed so the re-arm does not depend on an
    # unrelated TUI event landing after it expires.
    app.set_timer.assert_called_once()


def test_auto_start_stops_after_episode_cap(tmp_path):
    from pm_core.tui import auto_start
    state = ReviewLoopState(
        pr_id=PR, running=False, latest_verdict=VERDICT_LAUNCH_FAILED,
        launch_retryable=True, retry_ready_at=0,
        retry_episodes=auto_start.MAX_REVIEW_LAUNCH_RETRY_EPISODES)
    app = _auto_app(tmp_path, state)
    with patch("pm_core.tui.review_loop_ui._start_loop") as start:
        auto_start._auto_start_review_loops(app, app._data["prs"])
    start.assert_not_called()


def test_auto_start_keeps_the_failure_retryable_when_rearm_cannot_start(
        tmp_path):
    """If the resumed loop cannot start (e.g. unusable transcript dir), the
    failure must stay retryable rather than be silently disarmed."""
    from pm_core.tui import auto_start
    state = ReviewLoopState(pr_id=PR, running=False,
                            latest_verdict=VERDICT_LAUNCH_FAILED,
                            launch_retryable=True, retry_ready_at=0,
                            retry_episodes=2, iteration=1,
                            _transcript_dir=str(tmp_path))
    app = _auto_app(tmp_path, state)
    with patch("pm_core.tui.review_loop_ui._start_loop",
               return_value=False), \
            patch("pm_core.tmux.in_tmux", return_value=True):
        auto_start._auto_start_review_loops(app, app._data["prs"])
    assert state.retry_episodes == 2
    assert state.launch_retryable is True


def test_auto_start_rearm_yields_to_a_pending_review_return(tmp_path):
    """A sign-off REVIEW return waiting for its launch is a second
    ``--fresh`` launcher for the same window, so the re-arm takes the
    return's launch claim (one launcher) instead of racing it."""
    from pm_core.tui import auto_start

    def _state():
        return ReviewLoopState(pr_id=PR, running=False,
                               latest_verdict=VERDICT_LAUNCH_FAILED,
                               launch_retryable=True, retry_ready_at=0,
                               retry_episodes=0, iteration=1,
                               _transcript_dir=str(tmp_path))

    # Another driver already owns the return's launch: do not re-arm, keep
    # the retryable failure, and re-check once the claim can expire.
    state = _state()
    app = _auto_app(tmp_path, state)
    app._return_claim_recheck = False
    with patch.object(auto_start, "_awaiting_on_disk", return_value=True), \
            patch("pm_core.signoff.claim_return_launch",
                  return_value=False) as claim, \
            patch("pm_core.tui.review_loop_ui._start_loop") as start, \
            patch("pm_core.tmux.in_tmux", return_value=True):
        auto_start._auto_start_review_loops(app, app._data["prs"])
    claim.assert_called_once_with(tmp_path, PR, "review")
    start.assert_not_called()
    assert state.launch_retryable is True
    assert state.retry_episodes == 0
    assert state.launch_attempts == 0
    app.set_timer.assert_called_once()

    # Nobody owns it: this pass takes the claim and re-arms the loop, which
    # performs the return's launch itself.
    state = _state()
    app = _auto_app(tmp_path, state)
    app._return_claim_recheck = False
    with patch.object(auto_start, "_awaiting_on_disk", return_value=True), \
            patch("pm_core.signoff.claim_return_launch",
                  return_value=True), \
            patch("pm_core.tui.review_loop_ui._start_loop",
                  return_value=True) as start, \
            patch("pm_core.tmux.in_tmux", return_value=True):
        auto_start._auto_start_review_loops(app, app._data["prs"])
    start.assert_called_once()
    assert state.retry_episodes == 1


# ---------------------------------------------------------------------------
# TUI retry notice
# ---------------------------------------------------------------------------

def test_retry_notice_is_only_for_a_real_retry(tmp_path):
    from pm_core.tui import review_loop_ui
    app = MagicMock()
    state = ReviewLoopState(pr_id=PR, running=True, iteration=1,
                            launch_attempts=1)
    app._review_loops = {PR: state}
    app._impl_poll_counter = 0
    app._qa_loops = {}
    app._data = {"prs": []}
    app._watcher_manager.is_any_running.return_value = False
    app._review_loop_timer = None
    with patch.object(review_loop_ui, "_refresh_tech_tree"), \
            patch("pm_core.tui.watcher_ui.poll_watcher_state"), \
            patch("pm_core.tui.qa_loop_ui.poll_qa_state"):
        # A normal first attempt is not a retry.
        review_loop_ui._poll_loop_state_inner(app)
        app.log_message.assert_not_called()
        # Attempt 2 after a recorded failure is announced exactly once.
        state.launch_attempts = 2
        state.last_launch_error = "container setup failed"
        state.last_launch_artifact = str(tmp_path / "a.log")
        review_loop_ui._poll_loop_state_inner(app)
        review_loop_ui._poll_loop_state_inner(app)
    assert app.log_message.call_count == 1
    msg = app.log_message.call_args[0][0]
    assert "Review launch retry" in msg
    assert "attempt 2" in msg
    # The recorded error is the *previous* attempt's failure; the wording
    # must not read as though the attempt now starting already failed.
    assert "attempt 1 failed" in msg
    assert "container setup failed" in msg
    assert str(tmp_path / "a.log") in msg


def test_retry_notice_is_announced_again_in_a_later_iteration(tmp_path):
    """The notice is keyed on the attempt number; a successful iteration
    must reset that key so the next iteration's attempt 2 is announced
    rather than swallowed as already-notified."""
    from pm_core.tui import review_loop_ui
    app = MagicMock()
    state = ReviewLoopState(pr_id=PR, running=True, iteration=1,
                            launch_attempts=2, last_launch_error="first")
    app._review_loops = {PR: state}
    app._impl_poll_counter = 0
    app._qa_loops = {}
    app._data = {"prs": []}
    app._watcher_manager.is_any_running.return_value = False
    app._review_loop_timer = None
    with patch.object(review_loop_ui, "_refresh_tech_tree"), \
            patch("pm_core.tui.watcher_ui.poll_watcher_state"), \
            patch("pm_core.tui.qa_loop_ui.poll_qa_state"):
        review_loop_ui._poll_loop_state_inner(app)
        assert app.log_message.call_count == 1
        # Iteration 1's launch eventually succeeded; iteration 2 then needs
        # a retry at the same attempt number.
        review_loop._reset_launch_retry(state)
        state.iteration = 2
        state.launch_attempts = 2
        state.last_launch_error = "second"
        review_loop_ui._poll_loop_state_inner(app)
    assert app.log_message.call_count == 2
    assert "second" in app.log_message.call_args[0][0]


def test_launch_failure_notice_does_not_promise_a_retry_outside_auto_start(
        tmp_path):
    """A manual loop (or a PR auto-start does not manage) keeps its failure
    for the user: nothing re-arms it, so the notice must not claim it will
    retry automatically."""
    from pm_core.tui import review_loop_ui
    app = MagicMock()
    app._auto_start = False
    app._auto_start_targets = {}
    app._auto_start_all = False
    state = ReviewLoopState(
        pr_id=PR, running=False, iteration=1,
        latest_verdict=VERDICT_LAUNCH_FAILED, launch_retryable=True,
        launch_attempts=3,
        latest_output="Review window launch failed (rc=1): boom",
        retry_ready_at=time.time() + 60)
    app._review_loops = {PR: state}
    app._impl_poll_counter = 0
    app._qa_loops = {}
    app._data = {"prs": [{"id": PR, "status": "in_review",
                          "workdir": str(tmp_path)}]}
    app._watcher_manager.is_any_running.return_value = False
    app._review_loop_timer = None
    with patch.object(review_loop_ui, "_refresh_tech_tree"), \
            patch("pm_core.tui.watcher_ui.poll_watcher_state"), \
            patch("pm_core.tui.qa_loop_ui.poll_qa_state"):
        review_loop_ui._poll_loop_state_inner(app)
    msg = app.log_message.call_args[0][0]
    assert "review-loop start" in msg
    assert "Will retry automatically" not in msg
    # ... and nothing was scheduled to re-arm it.
    app.set_timer.assert_not_called()


def test_launch_failure_notice_promises_the_retry_for_an_auto_start_target(
        tmp_path):
    from pm_core.tui import review_loop_ui
    app = MagicMock()
    app._auto_start = True
    app._auto_start_targets = {PR: {}}
    app._auto_start_all = False
    app._review_retry_timer = None
    state = ReviewLoopState(
        pr_id=PR, running=False, iteration=1,
        latest_verdict=VERDICT_LAUNCH_FAILED, launch_retryable=True,
        launch_attempts=3,
        latest_output="Review window launch failed (rc=1): boom",
        retry_ready_at=time.time() + 60)
    app._review_loops = {PR: state}
    app._impl_poll_counter = 0
    app._qa_loops = {}
    app._data = {"prs": [{"id": PR, "status": "in_review",
                          "workdir": str(tmp_path)}]}
    app._watcher_manager.is_any_running.return_value = False
    app._review_loop_timer = None
    with patch.object(review_loop_ui, "_refresh_tech_tree"), \
            patch("pm_core.tui.watcher_ui.poll_watcher_state"), \
            patch("pm_core.tui.qa_loop_ui.poll_qa_state"):
        review_loop_ui._poll_loop_state_inner(app)
    msg = app.log_message.call_args[0][0]
    assert "Will retry automatically" in msg
    app.set_timer.assert_called_once()


# ---------------------------------------------------------------------------
# pm pr auto-sequence yields to a live loop lease
# ---------------------------------------------------------------------------

def test_auto_sequence_does_not_launch_over_a_loop_lease(tmp_path, monkeypatch):
    from click.testing import CliRunner
    from pm_core import store, runtime_state as rs
    from pm_core.cli.pr import pr_auto_sequence

    store.save({"project": {"name": "p", "base_branch": "master",
                            "backend": "local"},
                "prs": [{"id": PR, "title": "T", "branch": "pm/pr-001",
                         "status": "in_review", "workdir": str(tmp_path)}],
                "plans": []}, tmp_path)
    rs.claim_action_lease(PR, "review-loop", "loop:ab12", 60)
    monkeypatch.setattr("pm_core.cli.pr.state_root", lambda: tmp_path)
    monkeypatch.setattr("pm_core.cli.pr._get_pm_session", lambda: "pm-s")
    with patch("pm_core.cli.pr._launch_review_iteration") as launch:
        result = CliRunner().invoke(pr_auto_sequence, [PR])
    assert result.exit_code == 0
    assert "owned by loop:ab12" in result.output
    launch.assert_not_called()


# ---------------------------------------------------------------------------
# Review 385e i4: classification, discovery grace, restart double-start
# ---------------------------------------------------------------------------

def test_container_permission_error_is_retryable_not_auth(tmp_path):
    """A container teardown/mount failure that says "permission denied" is
    the transient launch failure this fix recovers, not an auth hold.

    Classifying it as auth made the loop stop after one attempt and left the
    auto-start target stranded — the very bug this PR fixes."""
    with patch.object(review_loop.subprocess, "run",
                      return_value=MagicMock(
                          returncode=1, stdout="",
                          stderr="Error: removing container: permission denied")):
        with pytest.raises(ReviewLaunchError) as ei:
            review_loop._launch_review_window(
                PR, str(tmp_path), iteration=1,
                transcript=str(tmp_path / "t.jsonl"))
    assert ei.value.retryable is True
    assert ei.value.reason == "launch"


def test_bare_http_code_lookalikes_stay_retryable(tmp_path):
    """A 3-digit token in arbitrary child stderr (a pid, an id, a port) is
    not an HTTP 401/403.  Misclassifying it as auth stops the retry after one
    attempt and strands the target again."""
    assert not review_loop._looks_like_auth_failure(
        "error: process 403 exited while removing container")
    assert not review_loop._looks_like_auth_failure(
        "container pm-review-401 not found")
    assert not review_loop._looks_like_auth_failure("mount failed: 401")
    # Real auth symptoms still classify.
    assert review_loop._looks_like_auth_failure("HTTP 403 Forbidden")
    assert review_loop._looks_like_auth_failure("401 unauthorized")
    assert review_loop._looks_like_auth_failure("status code 403")


def test_auth_failure_reported_on_stdout_is_not_retryable(tmp_path):
    """A child can print the real error on stdout while stderr carries only
    warnings; classification must look at both streams."""
    with patch.object(review_loop.subprocess, "run",
                      return_value=MagicMock(
                          returncode=1,
                          stdout="Error: 401 Unauthorized — invalid api key",
                          stderr="warning: retrying connection")):
        with pytest.raises(ReviewLaunchError) as ei:
            review_loop._launch_review_window(
                PR, str(tmp_path), iteration=1,
                transcript=str(tmp_path / "t.jsonl"))
    assert ei.value.retryable is False
    assert ei.value.reason == "auth"


def test_discovery_waits_for_a_starting_pane_after_our_attempt(tmp_path,
                                                               monkeypatch):
    """After our own attempt failed, a live pane that has not exposed its
    session id yet may be a just-started recovery or another driver's
    launch: give it the bounded grace instead of a ``--fresh`` that kills
    it.  On the first attempt (nothing of ours yet) it is still replaced."""
    monkeypatch.setattr(review_loop, "_discover_iteration", _ORIG_DISCOVER)
    monkeypatch.setattr(review_loop, "_get_pm_session", lambda: "pm-s")
    monkeypatch.setattr(review_loop, "_find_review_claude_pane",
                        lambda *a, **k: "%9")
    monkeypatch.setattr("pm_core.claude_launcher.pane_transcript_path",
                        lambda *_a, **_k: None)
    monkeypatch.setattr(review_loop, "_other_loop_owner", lambda _s: "")

    state = ReviewLoopState(pr_id=PR, iteration=2,
                            iteration_attempted=True, launch_attempts=1)
    disc = review_loop._discover_iteration(state, _pr(tmp_path),
                                           str(tmp_path), 2,
                                           allow_recovery=True)
    assert disc.kind == "pending"

    state = ReviewLoopState(pr_id=PR, iteration=2)
    disc = review_loop._discover_iteration(state, _pr(tmp_path),
                                           str(tmp_path), 2,
                                           allow_recovery=False)
    assert disc.kind == "launch"


def test_pending_grace_is_per_launch_attempt(tmp_path, monkeypatch):
    """Every launch attempt gets its own bounded grace for a pane that has
    not exposed a session id yet.  A counter carried over from an earlier
    attempt would replace a just-started session at once."""
    state = ReviewLoopState(pr_id=PR)
    launches: list[int] = []
    discoveries: list[int] = []

    def fake_discover(*_a, **_k):
        discoveries.append(len(launches))
        if len(launches) >= 2:
            return AttemptDiscovery("launch")
        return AttemptDiscovery("pending", pane_id="%1",
                                transcript="t", reason="starting")

    def fake_review(*_a, **kw):
        launches.append(kw["attempt"])
        if len(launches) == 1:
            raise ReviewLaunchError("container setup failed", retryable=True)
        return "**PASS**"

    monkeypatch.setattr(review_loop, "_discover_iteration", fake_discover)
    monkeypatch.setattr(review_loop, "_DISCOVERY_GRACE", 0.0)
    with patch.object(review_loop, "_run_claude_review",
                      side_effect=fake_review):
        result = _run(state, tmp_path)
    assert result.latest_verdict == VERDICT_PASS
    assert launches == [1, 2]
    # Four pending checks (three waits + the replacement) per attempt.
    assert discoveries == [0, 0, 0, 0, 1, 1, 1, 1]


def test_start_loop_marks_running_before_the_thread_starts(tmp_path,
                                                           monkeypatch):
    """A second starter (the breadcrumb resume after `check_and_start`
    re-armed the same loop) and the 1 s poll must not see a non-running
    loop between `_start_loop` and the thread body."""
    from pm_core import runtime_state as rs
    from pm_core import tmux as tmux_mod
    from pm_core.tui import review_loop_ui

    monkeypatch.setattr(rs, "_runtime_dir", lambda: tmp_path)
    app = MagicMock()
    app._review_loops = {}
    app._review_loop_timer = None
    pr = {"id": PR, "workdir": str(tmp_path), "status": "in_review"}
    state = ReviewLoopState(pr_id=PR, iteration=3,
                            latest_verdict=VERDICT_LAUNCH_FAILED,
                            launch_retryable=True)
    seen: dict = {}

    def fake_bg(**kw):
        seen["running"] = kw["state"].running

    with patch.object(tmux_mod, "in_tmux", return_value=True), \
            patch("pm_core.tui.review_loop_ui.store") as store_mock, \
            patch("pm_core.tui.review_loop_ui.start_review_loop_background",
                  side_effect=fake_bg), \
            patch("pm_core.tui.review_loop_ui._ensure_poll_timer"):
        store_mock.find_project_root.return_value = Path("/tmp/pm")
        assert review_loop_ui._start_loop(
            app, PR, pr, transcript_dir=str(tmp_path), resume_state=state)
    assert seen["running"] is True
    assert state.running is True


def test_start_loop_clears_running_when_the_thread_cannot_start(tmp_path,
                                                                monkeypatch):
    """A failed thread start must not leave the loop marked running: the
    poller and the auto-start scheduler would then never retry the target."""
    from pm_core import runtime_state as rs
    from pm_core import tmux as tmux_mod
    from pm_core.tui import review_loop_ui

    monkeypatch.setattr(rs, "_runtime_dir", lambda: tmp_path)
    app = MagicMock()
    app._review_loops = {}
    app._review_loop_timer = None
    pr = {"id": PR, "workdir": str(tmp_path), "status": "in_review"}
    state = ReviewLoopState(pr_id=PR, iteration=1)
    with patch.object(tmux_mod, "in_tmux", return_value=True), \
            patch("pm_core.tui.review_loop_ui.store") as store_mock, \
            patch("pm_core.tui.review_loop_ui.start_review_loop_background",
                  side_effect=RuntimeError("can't start new thread")), \
            patch("pm_core.tui.review_loop_ui._ensure_poll_timer"):
        store_mock.find_project_root.return_value = Path("/tmp/pm")
        with pytest.raises(RuntimeError):
            review_loop_ui._start_loop(
                app, PR, pr, transcript_dir=str(tmp_path),
                resume_state=state)
    assert state.running is False


def test_completion_drops_a_previous_episodes_retry_evidence(tmp_path,
                                                             monkeypatch):
    """A loop that eventually succeeds after a re-armed retryable failure
    must not keep the old artifact/error in runtime_state."""
    from pm_core import runtime_state as rs
    from pm_core.tui import review_loop_ui

    monkeypatch.setattr(rs, "_runtime_dir", lambda: tmp_path)
    monkeypatch.setattr(review_loop_ui, "_is_active_loop", lambda _s: True)
    rs.set_action_state(PR, "review-loop", "failed",
                        verdict=VERDICT_LAUNCH_FAILED, retryable=True,
                        attempts=3, error="boom", artifact="/tmp/a.log",
                        retry_ready_at=time.time() + 60)

    state = ReviewLoopState(pr_id=PR, iteration=2,
                            latest_verdict=VERDICT_PASS)
    review_loop_ui._on_complete_from_thread(MagicMock(), state)

    entry = rs.get_action_state(PR, "review-loop")
    assert entry["state"] == "done"
    assert entry["verdict"] == VERDICT_PASS
    for stale in ("retryable", "attempts", "error", "artifact",
                  "retry_ready_at"):
        assert stale not in entry


def test_reset_launch_retry_clears_the_rearm_deadline():
    state = ReviewLoopState(pr_id=PR, launch_attempts=2,
                            retry_ready_at=time.time() + 60,
                            launch_retryable=True, retry_episodes=1)
    review_loop._reset_launch_retry(state)
    assert state.launch_attempts == 0
    assert state.launch_retryable is False
    assert state.retry_episodes == 0
    assert state.retry_ready_at == 0.0


def test_closed_pr_while_waiting_for_another_loops_lease_is_closed(
        tmp_path, monkeypatch):
    """A PR that merges while this loop is waiting for another loop's lease
    is CLOSED, not a non-retryable LAUNCH_FAILED."""
    state = ReviewLoopState(pr_id=PR)
    monkeypatch.setattr(review_loop, "_claim_launch", lambda *a, **k: False)
    monkeypatch.setattr(review_loop, "_wait_for_claim", lambda *a, **k: False)
    checks = iter([False, True])  # loop top: live; after the wait: terminal
    monkeypatch.setattr(review_loop, "_pr_is_terminal",
                        lambda *a, **k: next(checks, True))
    with patch.object(review_loop, "_run_claude_review") as run:
        result = _run(state, tmp_path)
    run.assert_not_called()
    assert result.latest_verdict == VERDICT_CLOSED


def test_cancellation_while_waiting_for_the_lease_is_killed(
        tmp_path, monkeypatch):
    """A user stop while waiting out another loop's launch lease is a
    cancellation, not a launch failure (LAUNCH_FAILED would tell the user
    the launch failed and would not read as KILLED)."""
    state = ReviewLoopState(pr_id=PR)

    def wait_and_cancel(*_a, **_k):
        state.stop_requested = True
        return False

    monkeypatch.setattr(review_loop, "_claim_launch", lambda *a, **k: False)
    monkeypatch.setattr(review_loop, "_wait_for_claim", wait_and_cancel)
    with patch.object(review_loop, "_run_claude_review") as run:
        result = _run(state, tmp_path)
    run.assert_not_called()
    assert result.latest_verdict == VERDICT_KILLED


def test_hold_records_the_hold_message_not_a_stale_launch_error(
        tmp_path, monkeypatch):
    """A HOLD after a retried launch must report the trust/permission prompt
    it is actually sitting at, not the earlier attempt's launch error."""
    from pm_core import runtime_state as rs
    from pm_core.tui import review_loop_ui

    monkeypatch.setattr(rs, "_runtime_dir", lambda: tmp_path)
    monkeypatch.setattr(review_loop_ui, "_is_active_loop", lambda _s: True)
    state = ReviewLoopState(
        pr_id=PR, iteration=2, latest_verdict=VERDICT_HOLD,
        latest_output="workspace trust prompt in review pane",
        last_launch_error="container setup failed",
        last_launch_artifact=str(tmp_path / "a.log"),
        retry_ready_at=time.time() + 60)
    review_loop_ui._on_complete_from_thread(MagicMock(), state)

    entry = rs.get_action_state(PR, "review-loop")
    assert entry["state"] == "failed"
    assert entry["verdict"] == VERDICT_HOLD
    assert entry["retryable"] is False
    assert "trust prompt" in entry["error"]
    assert "container setup failed" not in entry["error"]
    # The failed attempt's artifact/deadline are not the hold's evidence.
    assert "artifact" not in entry
    assert "retry_ready_at" not in entry


def test_auto_start_keeps_the_failure_retryable_when_rearm_raises(tmp_path):
    """A starter that raises must restore the retry episode too, not leave
    the target disarmed."""
    from pm_core.tui import auto_start
    state = ReviewLoopState(pr_id=PR, running=False,
                            latest_verdict=VERDICT_LAUNCH_FAILED,
                            launch_retryable=True, retry_ready_at=0,
                            retry_episodes=2, iteration=1,
                            _transcript_dir=str(tmp_path))
    app = _auto_app(tmp_path, state)
    with patch("pm_core.tui.review_loop_ui._start_loop",
               side_effect=RuntimeError("no project root")), \
            patch("pm_core.tmux.in_tmux", return_value=True):
        auto_start._auto_start_review_loops(app, app._data["prs"])
    assert state.retry_episodes == 2
    assert state.launch_retryable is True
