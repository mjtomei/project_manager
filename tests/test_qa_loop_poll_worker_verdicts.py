"""Test the _poll_worker_verdicts handshake end-to-end.

Covers PASS→advance, NEEDS_WORK→advance, INPUT_REQUIRED→block (no re-PROCEED),
and re-emitted verdict detection via count-based seen_verdicts tracking.
"""
from pathlib import Path
from unittest.mock import MagicMock

from pm_core import qa_loop
from pm_core.qa_loop import (
    QAScenario,
    QALoopState,
    _poll_worker_verdicts,
    _WorkerPanes,
    VERDICT_PASS,
    VERDICT_NEEDS_WORK,
    VERDICT_INPUT_REQUIRED,
)


def test_poll_worker_verdicts_batched_handshake(monkeypatch, tmp_path):
    # Three scenarios in one worker group.
    s1 = QAScenario(index=1, title="s1", focus="f", window_name="qa-test-w1",
                    pane_id="%99", group=1)
    s2 = QAScenario(index=2, title="s2", focus="f", window_name="qa-test-w1",
                    pane_id="%99", group=1)
    s3 = QAScenario(index=3, title="s3", focus="f", window_name="qa-test-w1",
                    pane_id="%99", group=1)
    worker_groups = {1: [s1, s2, s3]}

    # Pre-populate per-worker panes with cached refined steps so
    # _send_proceed doesn't block polling the concretizer.
    wp = _WorkerPanes(
        concretizer_pane="%98",
        evaluator_pane="%99",
        refined={1: "steps 1", 2: "steps 2", 3: "steps 3"},
    )
    worker_panes = {1: wp}

    state = QALoopState(pr_id="test")
    state.scenarios = [s1, s2, s3]

    # Speed the loop and disable verification.
    monkeypatch.setattr(qa_loop, "_POLL_INTERVAL", 0)
    monkeypatch.setattr(qa_loop, "_VERDICT_GRACE_PERIOD", 0)
    monkeypatch.setattr(qa_loop, "_is_verification_enabled", lambda: False)
    monkeypatch.setattr(qa_loop, "_write_status_file", lambda *a, **kw: None)
    monkeypatch.setattr(qa_loop.time, "sleep", lambda *a, **kw: None)

    tick_1 = "SCENARIO_1_VERDICT: PASS\n"
    tick_2 = tick_1 + "SCENARIO_2_VERDICT: NEEDS_WORK\n"
    tick_3 = tick_2 + "SCENARIO_3_VERDICT: INPUT_REQUIRED\n"
    tick_4 = tick_3  # same — confirms no re-PROCEED
    tick_5 = tick_3 + "SCENARIO_3_VERDICT: PASS\n"

    pane_content = ["", tick_1, tick_2, tick_3, tick_4, tick_5]

    # Patch tmux module used via `from pm_core import tmux as tmux_mod`.
    from pm_core import tmux as tmux_mod
    monkeypatch.setattr(tmux_mod, "pane_exists", lambda pid: True)

    send_keys = MagicMock()
    monkeypatch.setattr(tmux_mod, "send_keys", send_keys)

    # Checkpoints observed between ticks.
    observations = {}

    def _capture(pid, **kw):
        # Record state *before* this tick is consumed.
        tick_idx = 6 - len(pane_content)  # 0-based which tick we return now
        # At entry into this call, previous tick effects are already applied.
        if tick_idx == 2:
            # after tick_1 processed
            observations["after_1"] = {
                "verdict_1": state.scenario_verdicts.get(1),
                "proceeds": [
                    c for c in send_keys.call_args_list
                    if len(c.args) >= 2 and isinstance(c.args[1], str)
                    and c.args[1].startswith("PROCEED TO SCENARIO")
                ],
            }
        elif tick_idx == 3:
            observations["after_2"] = {
                "verdict_2": state.scenario_verdicts.get(2),
                "proceeds": [
                    c for c in send_keys.call_args_list
                    if len(c.args) >= 2 and isinstance(c.args[1], str)
                    and c.args[1].startswith("PROCEED TO SCENARIO")
                ],
            }
        elif tick_idx == 4:
            observations["after_3"] = {
                "verdict_3": state.scenario_verdicts.get(3),
                "proceed_count": sum(
                    1 for c in send_keys.call_args_list
                    if len(c.args) >= 2 and isinstance(c.args[1], str)
                    and c.args[1].startswith("PROCEED TO SCENARIO")
                ),
            }
        elif tick_idx == 5:
            observations["after_4_reemit_not_yet"] = {
                "verdict_3": state.scenario_verdicts.get(3),
                "proceed_count": sum(
                    1 for c in send_keys.call_args_list
                    if len(c.args) >= 2 and isinstance(c.args[1], str)
                    and c.args[1].startswith("PROCEED TO SCENARIO")
                ),
            }
        if pane_content:
            return pane_content.pop(0)
        return tick_5

    monkeypatch.setattr(tmux_mod, "capture_pane", MagicMock(side_effect=_capture))

    _poll_worker_verdicts(
        state,
        data={},
        pr_data={},
        session="s",
        workdir_path="/tmp/wd",
        status_path=tmp_path / "status.json",
        _notify=lambda: None,
        worker_groups=worker_groups,
        worker_panes=worker_panes,
        queued_workers=None,
        concurrency_cap=0,
    )

    proceed_calls = [
        c for c in send_keys.call_args_list
        if len(c.args) >= 2 and isinstance(c.args[1], str)
        and c.args[1].startswith("PROCEED TO SCENARIO")
    ]

    # Exactly 2 PROCEED messages total (s1→2, s2→3). No PROCEED after final s3.
    assert len(proceed_calls) == 2, proceed_calls
    assert proceed_calls[0].args[0] == "%99"
    assert proceed_calls[0].args[1].startswith("PROCEED TO SCENARIO 2")
    assert proceed_calls[1].args[0] == "%99"
    assert proceed_calls[1].args[1].startswith("PROCEED TO SCENARIO 3")

    # Intermediate-state checkpoints.
    assert observations["after_1"]["verdict_1"] == VERDICT_PASS
    assert len(observations["after_1"]["proceeds"]) == 1
    assert observations["after_1"]["proceeds"][0].args[1].startswith(
        "PROCEED TO SCENARIO 2")

    assert observations["after_2"]["verdict_2"] == VERDICT_NEEDS_WORK
    assert len(observations["after_2"]["proceeds"]) == 2
    assert observations["after_2"]["proceeds"][1].args[1].startswith(
        "PROCEED TO SCENARIO 3")

    assert observations["after_3"]["verdict_3"] == VERDICT_INPUT_REQUIRED
    assert observations["after_3"]["proceed_count"] == 2

    # Tick 4 (duplicate INPUT_REQUIRED): no new PROCEED, verdict unchanged,
    # seen_verdicts[3] count remained at 1 across the duplicate tick (i.e. the
    # loop did not re-process the same verdict line).
    assert observations["after_4_reemit_not_yet"]["verdict_3"] == VERDICT_INPUT_REQUIRED
    assert observations["after_4_reemit_not_yet"]["proceed_count"] == 2

    # Final state after tick 5: re-emitted PASS detected via count-based
    # tracking, worker advances off the final scenario (no PROCEED since last).
    assert state.scenario_verdicts[1] == VERDICT_PASS
    assert state.scenario_verdicts[2] == VERDICT_NEEDS_WORK
    assert state.scenario_verdicts[3] == VERDICT_PASS
