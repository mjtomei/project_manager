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
    monkeypatch.setattr(review_loop, "_discover_iteration", lambda *a, **k:
                        AttemptDiscovery("adopt", pane_id="%9",
                                         transcript=str(tmp_path / "t.jsonl")))
    monkeypatch.setattr(review_loop, "_poll_for_verdict",
                        MagicMock(side_effect=WorkspaceTrustBlocked("trust")))
    with pytest.raises(ReviewHoldError):
        review_loop._adopt_in_flight_review(state, _pr(tmp_path),
                                            str(tmp_path))


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
    assert result.last_pane_id == "%9"


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
                    transcript=None, attempt=1, workdir=None):
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
    """After our own failed attempt, a recovered transcript IS adopted."""
    monkeypatch.setattr(review_loop, "_discover_iteration", _ORIG_DISCOVER)
    sid = str(uuid.uuid4())
    _make_symlink(tmp_path, "review-pr-001-i1.jsonl", sid)
    (tmp_path / f"{sid}.jsonl").write_text(json.dumps({
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": "recovered\n\n**PASS**"}]},
    }) + "\n")
    monkeypatch.setattr(review_loop, "_get_pm_session", lambda: None)
    state = ReviewLoopState(pr_id=PR)
    err = ReviewLaunchError("boom", retryable=True)
    with patch.object(review_loop, "_run_claude_review", side_effect=err) as run:
        result = _run(state, tmp_path)
    assert run.call_count == 1
    assert result.latest_verdict == VERDICT_PASS
    assert [h.iteration for h in result.history] == [1]


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
        last_pane_id="%9", last_session_id="sid-1",
        iteration_attempted=True,
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
    assert "container setup failed" in msg
    assert str(tmp_path / "a.log") in msg


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
