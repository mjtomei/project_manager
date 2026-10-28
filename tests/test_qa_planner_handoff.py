"""Regression tests for the QA planner -> scenario handoff (pr-b8561ac).

Two live failures motivated these:

* The planner emitted a complete four-scenario plan, but Claude Code's
  redraw left only the tail of it in the tmux scrollback.  The driver
  scraped the pane after ``idle_prompt``, found ``QA_PLAN_END`` with no
  parseable scenarios, consumed the only idle event and stalled.  A
  variant capture held a valid suffix (SCENARIO 2..4) that was accepted
  without noticing scenario 1 was gone.
* The planner committed but did not push before ``QA_PLAN_END``.  The
  scenario clone (``git clone --local`` + origin swapped to the real
  upstream) then dropped the unpublished commits on ``pull --rebase``.
"""

import json
import os
import re
import subprocess
import time
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# run_qa_sync lazily imports pm_core.cli, whose modules bind
# ``build_claude_shell_cmd`` by name.  Import it here, before
# _run_planning patches that function, or pm_core.cli.guide would keep
# the harness mock for every later test in the session.
import pm_core.cli  # noqa: F401
from pm_core import qa_loop
from pm_core.claude_launcher import transcript_path_for
from pm_core.qa_loop import QALoopState, parse_qa_plan


PLANNER_UUID = "43dbdcf5-0253-40fa-a8bf-7231055d7643"


def _scenario(n: int, title: str) -> str:
    steps = "\n".join(
        f"    - step {n}.{i}: the user does a long thing and observes another "
        f"long thing on the surface"
        for i in range(1, 12)
    )
    return (
        f"SCENARIO {n}: {title}\n"
        f"FOCUS: behaviour {n}\n"
        f"INSTRUCTION: none\n"
        f"STEPS:\n"
        f"  GIVEN: a project in state {n}\n"
        f"  WHEN: the user acts {n}\n"
        f"  THEN:\n{steps}\n"
    )


TITLES = [
    "No-less review pane shows diff",
    "Pager unchanged when less exists",
    "All launch paths get fallback",
    "Concurrent review launches",
]

FULL_PLAN = (
    "The plan has four scenarios:\n\n"
    "1. **The bug no longer reproduces.** Short summary.\n"
    "2. Pager unchanged.\n\n"
    "QA_PLAN_START\n\n"
    + "\n".join(_scenario(i + 1, t) for i, t in enumerate(TITLES))
    + "\nQA_PLAN_END\n"
)

# What the pane held in the live failure: only the tail of the final
# scenario plus the end marker (no SCENARIO header at all).
PANE_TAIL_ONLY = "    - " + FULL_PLAN[FULL_PLAN.index("step 4.3"):]
assert "SCENARIO" not in PANE_TAIL_ONLY and "QA_PLAN_END" in PANE_TAIL_ONLY

# A truncation that happens to leave a *valid suffix* of scenario headers.
PANE_SUFFIX = FULL_PLAN[FULL_PLAN.index("SCENARIO 2:"):]

TEMPLATE_PROMPT = """You are a QA planner.

QA_PLAN_START

SCENARIO 1: <descriptive title for this scenario>
FOCUS: <what area or behavior to test>
INSTRUCTION: <filename from the library above, or "none">
STEPS:
  GIVEN: <starting state the user is in>
  WHEN: <user action>
  THEN: <observable outcome(s)>

SCENARIO 2: <descriptive title for next scenario>
FOCUS: <what area or behavior to test>
INSTRUCTION: <filename or "none">
STEPS:
  GIVEN: <starting state>
  WHEN: <user action>
  THEN: <observable outcome(s)>

QA_PLAN_END
"""


def _write_transcript(path: Path, turns: list[tuple[str, str]]) -> None:
    """Write a Claude-format JSONL transcript of (role, text) turns."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for role, text in turns:
        if role == "user":
            msg = {"role": "user", "content": text}
        else:
            msg = {"role": "assistant",
                   "content": [{"type": "text", "text": text}]}
        lines.append(json.dumps({"type": role, "sessionId": PLANNER_UUID,
                                 "message": msg}))
    path.write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# run_qa_sync planning phase harness
# ---------------------------------------------------------------------------

def _run_planning(tmp_path, monkeypatch, *, pane_content: str,
                  transcript_turns: list[tuple[str, str]] | None,
                  idle_events: int = 1, grace: float | None = 0,
                  extra_patches: tuple = (),
                  settle_transcript_turns: list[tuple[str, str]] | None = None,
                  plan_after_nudge_turns: list[tuple[str, str]] | None = None,
                  end_with_stop: bool = False,
                  state_hook=None):
    """Drive run_qa_sync's planning phase with a fake tmux + hook layer.

    Returns the final state.  The PR has no QA spec, so when a plan is
    accepted run_qa_sync returns at the spec gate right after planning —
    before any scenario launch — leaving ``state.scenarios`` as the
    accepted plan.  When no plan is accepted the spec gate is skipped and
    the harness stops at the first Phase 2 tmux call.

    Once the scripted idle events run out the poll loop is ended by its
    planner deadline (a fake qa_loop-local clock), i.e. the way a planner
    that never produces a plan really ends.  ``end_with_stop=True`` ends it
    with ``stop_requested`` instead, for tests that need the teardown path
    (which skips the final gated read) rather than a timeout.

    *settle_transcript_turns*, when given, is written to the planner's
    transcript during the recovery settle wait (the "the plan landed just
    after the idle hook" race) and the wait reports no newer event.

    *plan_after_nudge_turns*, when given, is written to the planner's
    transcript on the first idle event *after* a recovery nudge was sent
    (the "the planner answered the nudge" path), so a test can assert the
    retry is accepted instead of being counted as another missing output.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    if grace is not None:
        monkeypatch.setattr(qa_loop, "_PLANNER_GRACE", grace)

    workdir = tmp_path / "workdir"
    workdir.mkdir()
    pr = {"id": "pr-001", "title": "t", "branch": "pm/pr-001",
          "status": "qa", "workdir": str(workdir)}
    data = {"project": {"name": "p"}, "prs": [pr]}
    state = QALoopState(pr_id="pr-001")
    state.qa_workdir = str(tmp_path / "qa")
    if state_hook is not None:
        # Let a test reach the state mid-run (e.g. to simulate a stop that
        # lands while recovery is deciding).
        state_hook(state)

    transcript_paths: dict[str, Path] = {}

    def fake_build_cmd(**kw):
        path = transcript_path_for(kw["cwd"], kw["session_id"])
        transcript_paths["planner"] = path
        if transcript_turns is not None:
            _write_transcript(path, transcript_turns)
        return "planner-cmd"

    calls = {"n": 0}
    settle_writes = {"pending": settle_transcript_turns}
    after_nudge = {"pending": plan_after_nudge_turns}

    def fake_wait_for_event(session_id, **kw):
        calls["n"] += 1
        if calls["n"] <= idle_events:
            return {"event_type": "idle_prompt", "timestamp": time.time()}
        if settle_writes["pending"] is not None:
            # The transcript write trails the idle hook: the plan lands
            # while recovery is settling, with no newer event.
            _write_transcript(transcript_paths["planner"],
                              settle_writes["pending"])
            settle_writes["pending"] = None
            return None
        if (after_nudge["pending"] is not None
                and calls["n"] > idle_events + 1):
            # The recovery nudge landed (the settle wait above — the call
            # right after the last scripted idle — reported no newer event,
            # so ``handle`` sent one).  The planner answers with its
            # complete plan on a new turn.
            _write_transcript(transcript_paths["planner"],
                              after_nudge["pending"])
            after_nudge["pending"] = None
            return {"event_type": "idle_prompt",
                    "timestamp": time.time() + 1}
        if end_with_stop:
            state.stop_requested = True
        return None

    class _FakeClock:
        """qa_loop-local clock: each monotonic() call advances one second.

        Replacing ``pm_core.qa_loop.time`` (not the stdlib module) lets the
        planner deadline pass after the scripted idle events without a
        stop, while the recovery layer keeps real time.
        """

        def __init__(self):
            self.now = 1000.0

        def monotonic(self):
            self.now += 1.0
            return self.now

        def time(self):
            return 1_700_000_000.0

        def sleep(self, _secs):
            pass

    class _StopHarness(Exception):
        pass

    resolution = MagicMock(model=None, provider=None, effort=None)
    patches = [
        patch("pm_core.qa_loop.get_pm_session", return_value="pm-test"),
        patch("pm_core.store.load", return_value=data),
        patch("pm_core.qa_loop._resolve_qa_model", return_value=resolution),
        patch("pm_core.qa_loop._next_scenario_offset", return_value=0),
        patch("pm_core.qa_loop._launch_scenario_0", return_value=None),
        patch("pm_core.qa_loop._write_status_file"),
        patch("pm_core.container.is_container_mode_enabled",
              return_value=False),
        patch("pm_core.prompt_gen.generate_qa_planner_prompt",
              return_value=TEMPLATE_PROMPT),
        patch("pm_core.claude_launcher.build_claude_shell_cmd",
              side_effect=fake_build_cmd),
        patch("pm_core.tmux.find_window_by_name", return_value=None),
        patch("pm_core.tmux.new_window"),
        patch("pm_core.tmux.select_window"),
        patch("pm_core.runtime_state.consume_suppress_switch",
              return_value=True),
        patch("pm_core.qa_loop.find_claude_pane", return_value="%1"),
        patch("pm_core.tmux.pane_exists", return_value=True),
        patch("pm_core.tmux.capture_pane", return_value=pane_content),
        patch("pm_core.hook_events.wait_for_event",
              side_effect=fake_wait_for_event),
        patch("pm_core.tmux.new_window_get_pane", side_effect=_StopHarness),
        patch("pm_core.tmux.send_keys"),
        patch("pm_core.qa_loop.time", _FakeClock()),
        patch.object(qa_loop, "_PLANNER_TIMEOUT", 3.0),
        *extra_patches,
    ]
    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        try:
            qa_loop.run_qa_sync(state, tmp_path / "pm", pr)
        except _StopHarness:
            pass  # reached Phase 2 (no plan accepted) — stop here
    return state


class TestPlannerReadsTranscript:
    def test_truncated_pane_tail_uses_full_transcript_plan(
            self, tmp_path, monkeypatch):
        """Live failure: pane holds only the plan tail, JSONL holds all 4."""
        state = _run_planning(
            tmp_path, monkeypatch, pane_content=PANE_TAIL_ONLY,
            transcript_turns=[("user", TEMPLATE_PROMPT),
                              ("assistant", FULL_PLAN)])
        assert [s.index for s in state.scenarios] == [1, 2, 3, 4]
        assert [s.title for s in state.scenarios] == TITLES
        assert "QA_PLAN_START" in state.plan_output

    def test_valid_suffix_in_pane_does_not_drop_scenario_1(
            self, tmp_path, monkeypatch):
        """A pane suffix (SCENARIO 2..4) must not replace the full plan."""
        state = _run_planning(
            tmp_path, monkeypatch, pane_content=PANE_SUFFIX,
            transcript_turns=[("user", TEMPLATE_PROMPT),
                              ("assistant", FULL_PLAN)])
        assert [s.title for s in state.scenarios] == TITLES

    def test_plan_accepted_on_first_idle_inside_grace(
            self, tmp_path, monkeypatch):
        """A fast planner whose only idle lands inside the pane-scrape grace
        must still be accepted from the transcript (no stall)."""
        monkeypatch.setattr(qa_loop, "_PLANNER_GRACE", 3600)
        state = _run_planning(
            tmp_path, monkeypatch, pane_content=PANE_TAIL_ONLY,
            transcript_turns=[("user", TEMPLATE_PROMPT),
                              ("assistant", FULL_PLAN)],
            grace=None)
        assert [s.title for s in state.scenarios] == TITLES

    def test_prompt_template_markers_do_not_count(
            self, tmp_path, monkeypatch):
        """The template lives in the user prompt; it never yields a plan,
        from the transcript or from a pane that echoes it."""
        state = _run_planning(
            tmp_path, monkeypatch, pane_content=TEMPLATE_PROMPT,
            transcript_turns=[("user", TEMPLATE_PROMPT),
                              ("assistant", "Still reading the diff...")])
        assert state.scenarios == []
        assert state.latest_verdict == qa_loop.VERDICT_INPUT_REQUIRED

    def test_suffix_only_everywhere_is_rejected_not_accepted(
            self, tmp_path, monkeypatch):
        """No transcript, pane holds only SCENARIO 2..4: the truncated plan
        must be rejected as incomplete rather than silently dropping 1."""
        state = _run_planning(
            tmp_path, monkeypatch, pane_content=PANE_SUFFIX,
            transcript_turns=None)
        assert state.scenarios == []
        assert state.latest_verdict == qa_loop.VERDICT_INPUT_REQUIRED
        assert "incomplete" in state._error.lower()
        # The reason stays on screen (not replaced by "Plan: 0 scenario(s)").
        assert state.latest_output.startswith(
            "Planner plan incomplete — not consumed: pane:")

    def test_outcome_detail_explains_no_scenarios(self):
        state = QALoopState(pr_id="pr-001")
        state._error = ("The QA planner's plan was incomplete and was not "
                        "consumed.\n\npane: x\n\nAsk the planner to re-emit")
        assert qa_loop.qa_outcome_detail(state) == (
            "The QA planner's plan was incomplete and was not consumed. "
            "pane: x Ask the planner to re-emit")
        state.scenarios = [qa_loop.QAScenario(index=1, title="One", focus="f")]
        state.scenario_verdicts = {1: "PASS"}
        assert qa_loop.qa_outcome_detail(state) == "One: PASS"

    def test_stale_turn_not_reparsed_without_fresh_idle(
            self, tmp_path, monkeypatch):
        """Freshness: without an idle_prompt event nothing is read.

        The run is ended by a stop so the timeout's final gated read (which
        deliberately does re-read a completed transcript) does not apply:
        this test is about the *poll* read being event-gated.
        """
        with patch("pm_core.qa_loop.read_latest_assistant_text"
                   ) as read_text:
            state = _run_planning(
                tmp_path, monkeypatch, pane_content=PANE_TAIL_ONLY,
                transcript_turns=[("user", TEMPLATE_PROMPT),
                                  ("assistant", FULL_PLAN)],
                idle_events=0, end_with_stop=True)
        read_text.assert_not_called()
        assert state.scenarios == []

    def test_inline_start_mention_in_scenario_does_not_cut_plan(
            self, tmp_path, monkeypatch):
        """A scenario that talks about the markers (this PR's own round-1
        plan did: "The pane shows a template block (QA_PLAN_START, ...)")
        must not move the plan start past scenarios 1..k.  Before the fix
        the parse kept only the later scenarios and the completeness gate
        rejected the complete plan, stalling QA."""
        plan = FULL_PLAN.replace(
            "  WHEN: the user acts 2\n",
            "  WHEN: the pane shows a template block (QA_PLAN_START, a "
            "placeholder SCENARIO 1, QA_PLAN_END)\n"
            '  AND: the first line is "● QA_PLAN_START"\n')
        assert plan != FULL_PLAN
        scenarios = parse_qa_plan(plan)
        assert [s.index for s in scenarios] == [1, 2, 3, 4]
        assert qa_loop.qa_plan_problem(plan, scenarios, 1) is None
        state = _run_planning(
            tmp_path, monkeypatch, pane_content=PANE_TAIL_ONLY,
            transcript_turns=[("user", TEMPLATE_PROMPT),
                              ("assistant", plan)])
        assert [s.title for s in state.scenarios] == TITLES

    def test_trailing_end_mention_does_not_extend_last_scenario(self):
        """Prose after the plan that mentions QA_PLAN_END must not move the
        parse end past the real END line, or the last scenario's STEPS
        (sent to its worker) swallow the END line and the prose."""
        plan = (FULL_PLAN + "\nThat plan is wrapped in QA_PLAN_START and "
                "QA_PLAN_END markers.\n")
        scenarios = parse_qa_plan(plan)
        assert [s.index for s in scenarios] == [1, 2, 3, 4]
        assert scenarios[-1].steps == parse_qa_plan(FULL_PLAN)[-1].steps
        assert "QA_PLAN_END" not in scenarios[-1].steps
        assert qa_loop.qa_plan_problem(
            plan, scenarios, 1, start_may_be_stale=False) is None

    def test_transcript_without_pane_capture(self, tmp_path, monkeypatch):
        """Pane capture empty (e.g. alternate screen): transcript suffices."""
        state = _run_planning(
            tmp_path, monkeypatch, pane_content="",
            transcript_turns=[("user", TEMPLATE_PROMPT),
                              ("assistant", FULL_PLAN)])
        assert [s.index for s in state.scenarios] == [1, 2, 3, 4]


class TestRunQaSyncHandoff:
    def test_handoff_failure_stops_before_fan_out(self, tmp_path, monkeypatch):
        """A plan that can't be published never reaches scenario launch."""
        err = qa_loop.PlannerHandoffError("PR branch pm/pr-001 diverged: x")
        state = _run_planning(
            tmp_path, monkeypatch, pane_content="",
            transcript_turns=[("user", TEMPLATE_PROMPT),
                              ("assistant", FULL_PLAN)],
            extra_patches=(
                patch("pm_core.qa_loop._get_qa_spec", return_value="spec"),
                patch("pm_core.qa_loop._publish_planner_head",
                      side_effect=err),
                patch("pm_core.qa_loop._launch_scenarios_in_tmux",
                      side_effect=AssertionError("launched")),
            ))
        assert state.latest_verdict == qa_loop.VERDICT_INPUT_REQUIRED
        assert "diverged" in state._error
        assert state.running is False

    def test_published_head_and_code_changes_recorded(
            self, tmp_path, monkeypatch):
        launched = {}

        def fake_launch(state, *a, **kw):
            launched["head"] = state.planner_head
            launched["changes"] = list(state.planner_code_changes)
            raise _Launched

        class _Launched(Exception):
            pass

        with pytest.raises(_Launched):
            _run_planning(
                tmp_path, monkeypatch, pane_content="",
                transcript_turns=[("user", TEMPLATE_PROMPT),
                                  ("assistant", FULL_PLAN)],
                extra_patches=(
                    patch("pm_core.qa_loop._get_qa_spec",
                          return_value="spec"),
                    patch("pm_core.qa_loop._rev_parse", return_value="a" * 40),
                    patch("pm_core.qa_loop._publish_planner_head",
                          return_value="c" * 40),
                    patch("pm_core.qa_loop._planner_code_changes",
                          return_value=["app.py"]),
                    patch("pm_core.tmux.new_window_get_pane",
                          return_value="%2"),
                    patch("pm_core.tmux.split_pane_at", return_value="%3"),
                    patch("pm_core.tmux.pane_window_id", return_value=None),
                    patch("pm_core.qa_loop._launch_scenarios_in_tmux",
                          side_effect=fake_launch),
                ))
        assert launched["head"] == "c" * 40
        assert launched["changes"] == ["app.py"]


class TestQAPlanProblem:
    def test_complete_plan_ok(self):
        sc = parse_qa_plan(FULL_PLAN)
        assert qa_loop.qa_plan_problem(FULL_PLAN, sc, 1) is None

    def test_suffix_without_start_rejected(self):
        sc = parse_qa_plan(PANE_SUFFIX)
        assert [s.index for s in sc] == [2, 3, 4]  # parser alone accepts it
        assert qa_loop.qa_plan_problem(PANE_SUFFIX, sc, 1)

    def test_suffix_after_template_start_rejected(self):
        """Template START earlier in the pane does not legitimise a suffix."""
        text = TEMPLATE_PROMPT + "\n...redraw...\n" + PANE_SUFFIX
        sc = parse_qa_plan(text)
        assert sc  # parser picks up the suffix
        assert qa_loop.qa_plan_problem(text, sc, 1)

    def test_gap_in_numbering_rejected(self):
        text = FULL_PLAN.replace(_scenario(2, TITLES[1]), "")
        sc = parse_qa_plan(text)
        assert [s.index for s in sc] == [1, 3, 4]
        assert "contiguous" in qa_loop.qa_plan_problem(text, sc, 1)

    def test_scenario_start_numbering_ok(self):
        text = FULL_PLAN
        for i in range(4, 0, -1):
            text = text.replace(f"SCENARIO {i}:", f"SCENARIO {i + 4}:")
        sc = parse_qa_plan(text)
        assert [s.index for s in sc] == [5, 6, 7, 8]
        assert qa_loop.qa_plan_problem(text, sc, 5) is None
        # ...but starting at 6 for scenario_start=5 is a dropped scenario.
        text2 = (text[:text.index("SCENARIO 5:")]
                 + text[text.index("SCENARIO 6:"):])
        sc2 = parse_qa_plan(text2)
        assert [s.index for s in sc2] == [6, 7, 8]
        assert "leading scenarios missing" in qa_loop.qa_plan_problem(
            text2, sc2, 5)

    def test_markdown_wrapped_markers_ok(self):
        text = FULL_PLAN.replace("QA_PLAN_START", "**QA_PLAN_START**")
        text = text.replace("QA_PLAN_END", "`QA_PLAN_END`")
        sc = parse_qa_plan(text)
        assert qa_loop.qa_plan_problem(text, sc, 1) is None

    def test_titleless_header_is_a_dropped_scenario(self):
        """A bare ``SCENARIO N:`` line is skipped by parse_qa_plan; that is a
        lost scenario, so the plan is rejected (and the check must not
        borrow the next line as the header's title)."""
        text = FULL_PLAN.replace("SCENARIO 4: Concurrent review launches",
                                 "SCENARIO 4:")
        scenarios = parse_qa_plan(text)
        assert [s.index for s in scenarios] == [1, 2, 3]
        problem = qa_loop.qa_plan_problem(text, scenarios)
        assert problem and "[1, 2, 3, 4]" in problem

    @pytest.mark.parametrize("scenario_start", [1, 2, 3])
    def test_template_start_plus_suffix_rejected_at_any_offset(
            self, scenario_start):
        """Supervisor repro: template START..END, redraw, then a SCENARIO
        2..4 suffix + END.  With scenario_start=2 the numbering looks like
        a whole plan, so provenance (not numbering) must reject it."""
        text = TEMPLATE_PROMPT + "\n...redraw...\n" + PANE_SUFFIX
        sc = parse_qa_plan(text)
        assert [s.index for s in sc] == [2, 3, 4]
        assert "earlier" in qa_loop.qa_plan_problem(text, sc, scenario_start)

    def test_template_start_with_clipped_end_plus_suffix_rejected(self):
        """Even if the template's own END was lost, a block that holds the
        template's example headers is not this plan's START."""
        clipped = TEMPLATE_PROMPT[:TEMPLATE_PROMPT.rindex("QA_PLAN_END")]
        text = clipped + "\n...redraw...\n" + PANE_SUFFIX
        sc = parse_qa_plan(text)
        assert [s.index for s in sc] == [2, 3, 4]
        assert "template" in qa_loop.qa_plan_problem(text, sc, 2)

    def test_fresh_plan_at_offset_after_template_ok(self):
        """A whole plan numbered from scenario_start=2, after the echoed
        template, is still accepted."""
        plan = FULL_PLAN
        for i in range(4, 0, -1):
            plan = plan.replace(f"SCENARIO {i}:", f"SCENARIO {i + 1}:")
        text = TEMPLATE_PROMPT + "\n" + plan
        sc = parse_qa_plan(text)
        assert [s.index for s in sc] == [2, 3, 4, 5]
        assert qa_loop.qa_plan_problem(text, sc, 2) is None


class TestPlannerRecovery:
    def test_recovery_exhaustion_surfaces_input_required(
            self, tmp_path, monkeypatch):
        """A planner that never emits a complete plan must fail bounded.

        The poll loop must stop with an actionable INPUT_REQUIRED instead of
        waiting out the full one-hour planner timeout.
        """

        class _Exhausted:
            enabled = True

            def __init__(self, *args, **kwargs):
                pass

            def handle(self, *args, **kwargs):
                raise qa_loop.VerdictRecoveryExhausted(
                    "planner produced no complete QA_PLAN block",
                    attempts=3)

            def check_response(self):
                pass

        monkeypatch.setattr(qa_loop, "MissingOutputRecovery", _Exhausted)
        state = _run_planning(
            tmp_path, monkeypatch, pane_content=TEMPLATE_PROMPT,
            transcript_turns=[("user", TEMPLATE_PROMPT),
                              ("assistant", "Still reading the diff...")],
            extra_patches=(
                patch("pm_core.qa_loop._add_status_pane"),
            ))

        assert state.scenarios == []
        assert state.latest_verdict == qa_loop.VERDICT_INPUT_REQUIRED
        assert "complete QA_PLAN block" in state._error
        assert state.planning_phase is False
        assert state.running is False

    def test_exhaustion_names_the_rejected_plan_problem(
            self, tmp_path, monkeypatch):
        """A malformed plan's specific rejection survives into the error.

        A planner that DID emit a QA_PLAN block which the validator rejected
        (here: non-contiguous numbering) must not be reported as merely "no
        complete plan": the validator's reason is the actionable part, and
        the non-exhaustion "plan incomplete" surface already names it.
        """

        class _Exhausted:
            enabled = True

            def __init__(self, *args, **kwargs):
                pass

            def handle(self, *args, **kwargs):
                raise qa_loop.VerdictRecoveryExhausted(
                    "planner produced no complete QA_PLAN block",
                    attempts=3)

            def check_response(self):
                pass

        # Drop scenario 2 so the plan's numbering is not contiguous.
        malformed = FULL_PLAN.replace(_scenario(2, TITLES[1]), "")
        assert "contiguous" in qa_loop.qa_plan_problem(
            malformed, parse_qa_plan(malformed), 1)

        monkeypatch.setattr(qa_loop, "MissingOutputRecovery", _Exhausted)
        state = _run_planning(
            tmp_path, monkeypatch, pane_content=TEMPLATE_PROMPT,
            transcript_turns=[("user", TEMPLATE_PROMPT),
                              ("assistant", malformed)],
            extra_patches=(
                patch("pm_core.qa_loop._add_status_pane"),
            ))

        assert state.latest_verdict == qa_loop.VERDICT_INPUT_REQUIRED
        assert "contiguous" in state._error

    def test_recovery_nudge_names_the_rejected_plan_problem(
            self, tmp_path, monkeypatch):
        """The recovery request tells the planner what was wrong.

        A generic "re-emit your completed result" invites the same malformed
        block again, so a plan the validator refused (here: non-contiguous
        numbering) must be named in the nudge.  The request still asks only
        for the planner's own block — no plan is supplied or inferred — and
        it must stay a single tmux line.
        """
        # Drop scenario 2 so the plan's numbering is not contiguous.
        malformed = FULL_PLAN.replace(_scenario(2, TITLES[1]), "")
        assert "contiguous" in qa_loop.qa_plan_problem(
            malformed, parse_qa_plan(malformed), 1)

        sent: list[str] = []
        state = _run_planning(
            tmp_path, monkeypatch, pane_content=TEMPLATE_PROMPT,
            transcript_turns=[("user", TEMPLATE_PROMPT),
                              ("assistant", malformed)],
            idle_events=1,
            extra_patches=(
                patch("pm_core.qa_loop._add_status_pane"),
                patch("pm_core.tmux.send_keys",
                      side_effect=lambda _p, msg: sent.append(msg)),
            ))

        assert sent, "the planner was never nudged for its malformed block"
        assert "contiguous" in sent[0]
        assert "QA_PLAN_START" in sent[0]
        assert "\n" not in sent[0]
        # The rejected plan was never consumed, and the run stays bounded.
        assert state.scenarios == []
        assert state.latest_verdict == qa_loop.VERDICT_INPUT_REQUIRED

    def test_plan_landing_during_settle_is_accepted_not_renudged(
            self, tmp_path, monkeypatch):
        """A plan written after the idle hook (the transcript-write race) is
        accepted from the settle re-read instead of being asked for again.

        ``MissingOutputRecovery.handle`` returns ``"completed"`` when the
        outcome appears while it settles; the planner must re-read and use
        that plan rather than waiting for another idle turn that may never
        come.
        """
        state = _run_planning(
            tmp_path, monkeypatch, pane_content=TEMPLATE_PROMPT,
            transcript_turns=[("user", TEMPLATE_PROMPT),
                              ("assistant", "Still reading the diff...")],
            settle_transcript_turns=[("user", TEMPLATE_PROMPT),
                                     ("assistant", FULL_PLAN)])

        assert [s.title for s in state.scenarios] == TITLES
        assert "QA_PLAN_START" in state.plan_output

    def test_nudged_planner_plan_is_accepted_on_the_next_turn(
            self, tmp_path, monkeypatch):
        """A planner that answers the recovery nudge is not nudged again.

        The nudge asks the planner to re-emit its own QA_PLAN block.  When
        it does so on the following turn the loop must accept that plan and
        move on — the "retried, then succeeded" half of the acceptance
        criteria.  Without this the retry could look bounded while a
        recovered plan was silently ignored.
        """
        sent: list[str] = []
        state = _run_planning(
            tmp_path, monkeypatch, pane_content=TEMPLATE_PROMPT,
            transcript_turns=[("user", TEMPLATE_PROMPT),
                              ("assistant", "Still reading the diff...")],
            idle_events=1,
            plan_after_nudge_turns=[("user", TEMPLATE_PROMPT),
                                    ("assistant", FULL_PLAN)],
            extra_patches=(
                patch("pm_core.qa_loop._add_status_pane"),
                # The harness clock advances 1 s per monotonic() call, so the
                # default 3 s planner deadline would end the loop before the
                # answered turn arrives.
                patch.object(qa_loop, "_PLANNER_TIMEOUT", 20.0),
                patch("pm_core.tmux.send_keys",
                      side_effect=lambda _p, msg: sent.append(msg)),
            ))

        assert sent, "the planner was never nudged for its missing plan"
        assert len(sent) == 1, f"planner re-nudged after answering: {sent}"
        assert [s.title for s in state.scenarios] == TITLES
        assert "QA_PLAN_START" in state.plan_output

    def test_stop_during_recovery_is_a_clean_teardown(
            self, tmp_path, monkeypatch):
        """A stop that lands while recovery is deciding must not be reported
        as a missing plan.

        ``MissingOutputRecovery.handle`` checks its deferral bound *before*
        its own ``stop_check``, so a stop set from the TUI thread can surface
        as ``VerdictRecoveryExhausted``.  Treating that as a real exhaustion
        would end a user-stopped run with INPUT_REQUIRED (and record a QA
        note), the same bug the non-recovery stop path fixed.
        """
        state_holder: dict = {}

        class _ExhaustedWhileStopping:
            enabled = True

            def __init__(self, *args, **kwargs):
                pass

            def handle(self, *args, **kwargs):
                state_holder["state"].stop_requested = True
                raise qa_loop.VerdictRecoveryExhausted(
                    "the session re-announced its idle turn 11 time(s)",
                    attempts=0, reason="no_progress")

            def check_response(self):
                pass

        monkeypatch.setattr(qa_loop, "MissingOutputRecovery",
                            _ExhaustedWhileStopping)
        state = _run_planning(
            tmp_path, monkeypatch, pane_content=TEMPLATE_PROMPT,
            transcript_turns=[("user", TEMPLATE_PROMPT),
                              ("assistant", "Still reading the diff...")],
            extra_patches=(patch("pm_core.qa_loop._add_status_pane"),),
            state_hook=lambda s: state_holder.__setitem__("state", s))

        assert state.latest_verdict == qa_loop.VERDICT_STOPPED
        assert state.latest_verdict != qa_loop.VERDICT_INPUT_REQUIRED
        assert state._error == ""
        assert state.latest_output == "QA stopped during planning"

    def test_stop_during_response_timeout_is_a_clean_teardown(
            self, tmp_path, monkeypatch):
        """The same guard on the ``check_response`` exhaustion path.

        No idle event ever arrives, so the planner sits in the post-nudge
        response deadline; a stop set just before it fires must not surface
        INPUT_REQUIRED either.
        """
        state_holder: dict = {}

        class _ResponseTimeoutWhileStopping:
            enabled = True

            def __init__(self, *args, **kwargs):
                pass

            def handle(self, *args, **kwargs):
                raise AssertionError("no idle event should reach handle()")

            def check_response(self):
                state_holder["state"].stop_requested = True
                raise qa_loop.VerdictRecoveryExhausted(
                    "no new turn arrived within 3600s", attempts=1,
                    reason="no_response")

        monkeypatch.setattr(qa_loop, "MissingOutputRecovery",
                            _ResponseTimeoutWhileStopping)
        state = _run_planning(
            tmp_path, monkeypatch, pane_content=TEMPLATE_PROMPT,
            transcript_turns=[("user", TEMPLATE_PROMPT),
                              ("assistant", "Still reading the diff...")],
            idle_events=0,
            extra_patches=(patch("pm_core.qa_loop._add_status_pane"),),
            state_hook=lambda s: state_holder.__setitem__("state", s))

        assert state.latest_verdict == qa_loop.VERDICT_STOPPED
        assert state._error == ""


TEMPLATE_PLUS_SUFFIX = TEMPLATE_PROMPT + "\n...redraw...\n" + PANE_SUFFIX


class TestReadPlannerPlanPaneFallback:
    """_read_planner_plan when the latest assistant turn has no plan and the
    pane holds the echoed template followed by a truncated suffix."""

    @pytest.mark.parametrize("latest", [None, "Let me check one more thing."])
    @pytest.mark.parametrize("scenario_start", [1, 2])
    def test_template_start_plus_suffix_not_accepted(
            self, tmp_path, latest, scenario_start):
        transcript = None
        if latest is not None:
            transcript = tmp_path / "t.jsonl"
            _write_transcript(transcript, [("user", TEMPLATE_PROMPT),
                                           ("assistant", latest)])
        plan = qa_loop._read_planner_plan(
            str(transcript) if transcript else None,
            lambda: TEMPLATE_PLUS_SUFFIX, None, scenario_start)
        assert plan.scenarios == []
        assert plan.problems and plan.problems[0].startswith("pane:")

    def test_complete_pane_plan_at_offset_accepted(self, tmp_path):
        plan_text = FULL_PLAN
        for i in range(4, 0, -1):
            plan_text = plan_text.replace(f"SCENARIO {i}:",
                                          f"SCENARIO {i + 1}:")
        plan = qa_loop._read_planner_plan(
            None, lambda: TEMPLATE_PROMPT + "\n" + plan_text, None, 2)
        assert [s.index for s in plan.scenarios] == [2, 3, 4, 5]
        assert plan.source == "pane"

    def test_run_qa_sync_does_not_consume_template_plus_suffix(
            self, tmp_path, monkeypatch):
        state = _run_planning(
            tmp_path, monkeypatch, pane_content=TEMPLATE_PLUS_SUFFIX,
            transcript_turns=[("user", TEMPLATE_PROMPT),
                              ("assistant", "Still reading the diff...")],
            extra_patches=(patch("pm_core.qa_loop._next_scenario_offset",
                                 return_value=1),))
        assert state.scenarios == []
        assert state.latest_verdict == qa_loop.VERDICT_INPUT_REQUIRED
        assert "incomplete" in state._error.lower()

    def test_no_scenarios(self):
        assert qa_loop.qa_plan_problem(TEMPLATE_PROMPT, [], 1)


def _bullet_pane(plan_text: str, bullet: str = "\u25cf") -> str:
    """Render *plan_text* (START..END) the way a real Claude Code pane does:
    the message's first line carries the display bullet and every following
    line is indented two columns (shape of the live QA0 captures
    qa-round-2-interactive-pane-qa-#231/#232)."""
    lines = plan_text[plan_text.index("QA_PLAN_START"):].rstrip("\n").split("\n")
    return "\n".join([f"{bullet} {lines[0]}"]
                     + [f"  {line}" if line else "" for line in lines[1:]]) + "\n"


def _renumbered(plan_text: str, offset: int) -> str:
    for i in range(4, 0, -1):
        plan_text = plan_text.replace(f"SCENARIO {i}:", f"SCENARIO {i + offset}:")
    return plan_text


# A real pane: an earlier block's END is still on screen above the fresh
# bullet-prefixed plan (qa-#232).
REAL_PANE_BULLET_PLAN = (
    "  STEPS: Execute an earlier plan's last scenario.\n"
    "  QA_PLAN_END\n\n" + _bullet_pane(FULL_PLAN)
    + "\n\u273b Cooked for 4s\n\u276f \n")


class TestDisplayBulletMarkers:
    """Claude Code renders a message's first line with a "\u25cf"/"\u23fa"
    bullet, so a planner message that opens with the marker shows
    "\u25cf QA_PLAN_START" in the pane.  With no usable transcript the pane
    fallback must still accept that complete plan (the original stall)."""

    @pytest.mark.parametrize("bullet", ["\u25cf", "\u23fa"])
    def test_bullet_start_and_end_are_markers(self, bullet):
        assert qa_loop._marker_line_offsets(f"{bullet} QA_PLAN_START\n",
                                            "QA_PLAN_START") == [0]
        assert qa_loop._tail_has_marker_on_own_line(
            f"x\n{bullet} QA_PLAN_END\n", "QA_PLAN_END")
        # Still whole-line: a bullet line with other text is no marker.
        assert not qa_loop._marker_line_offsets(
            f"{bullet} QA_PLAN_START follows\n", "QA_PLAN_START")

    @pytest.mark.parametrize("latest", [None, "Let me check one more thing."])
    def test_reader_accepts_complete_bullet_pane_plan(self, tmp_path, latest):
        transcript = None
        if latest is not None:
            transcript = tmp_path / "t.jsonl"
            _write_transcript(transcript, [("user", TEMPLATE_PROMPT),
                                           ("assistant", latest)])
        plan = qa_loop._read_planner_plan(
            str(transcript) if transcript else None,
            lambda: REAL_PANE_BULLET_PLAN, None, 1)
        assert [s.title for s in plan.scenarios] == TITLES
        assert plan.source == "pane"

    @pytest.mark.parametrize("bullet", ["\u25cf", "\u23fa"])
    def test_bullet_plan_after_echoed_template_accepted(self, bullet):
        """With the prompt still in scrollback the closed template START
        must not be chosen over the bullet-prefixed real one."""
        plan = qa_loop._read_planner_plan(
            None, lambda: TEMPLATE_PROMPT + "\n" + _bullet_pane(FULL_PLAN,
                                                                bullet),
            None, 1)
        assert [s.index for s in plan.scenarios] == [1, 2, 3, 4]

    def test_bullet_plan_at_offset_accepted(self):
        text = TEMPLATE_PROMPT + "\n" + _bullet_pane(_renumbered(FULL_PLAN, 1))
        plan = qa_loop._read_planner_plan(None, lambda: text, None, 2)
        assert [s.index for s in plan.scenarios] == [2, 3, 4, 5]

    @pytest.mark.parametrize("scenario_start", [1, 2])
    def test_bullet_template_plus_suffix_still_rejected(self, scenario_start):
        text = (TEMPLATE_PROMPT.replace("\nQA_PLAN_START",
                                        "\n\u25cf QA_PLAN_START")
                + "\n...redraw...\n" + PANE_SUFFIX)
        plan = qa_loop._read_planner_plan(None, lambda: text, None,
                                          scenario_start)
        assert plan.scenarios == []
        assert "earlier" in plan.problems[0]

    def test_run_qa_sync_accepts_bullet_pane_without_transcript(
            self, tmp_path, monkeypatch):
        state = _run_planning(
            tmp_path, monkeypatch, pane_content=REAL_PANE_BULLET_PLAN,
            transcript_turns=None)
        assert [s.title for s in state.scenarios] == TITLES


# The template's START survived a redraw but its headers and END did not.
BARE_STALE_START_PLUS_SUFFIX = (
    "QA_PLAN_START\n\n...redraw wiped lines...\n" + PANE_SUFFIX)


class TestBareStaleStart:
    def test_bare_stale_start_plus_suffix_rejected_at_offset(self):
        sc = parse_qa_plan(BARE_STALE_START_PLUS_SUFFIX)
        assert [s.index for s in sc] == [2, 3, 4]
        problem = qa_loop.qa_plan_problem(BARE_STALE_START_PLUS_SUFFIX, sc, 2)
        assert problem and "earlier block" in problem

    @pytest.mark.parametrize("latest", [None, "Let me check one more thing."])
    def test_reader_rejects_bare_stale_start_plus_suffix(self, tmp_path,
                                                         latest):
        transcript = None
        if latest is not None:
            transcript = tmp_path / "t.jsonl"
            _write_transcript(transcript, [("user", TEMPLATE_PROMPT),
                                           ("assistant", latest)])
        plan = qa_loop._read_planner_plan(
            str(transcript) if transcript else None,
            lambda: BARE_STALE_START_PLUS_SUFFIX, None, 2)
        assert plan.scenarios == []
        assert plan.problems and plan.problems[0].startswith("pane:")

    def test_transcript_offset_plan_with_prose_after_start_ok(self, tmp_path):
        """Every START in the planner's own turn is fresh, so prose between
        it and SCENARIO 2 must not reject a transcript plan; the same text
        in the pane is rejected (its START may be stale)."""
        text = "QA_PLAN_START\n\nRound two:\n\n" + _renumbered(
            FULL_PLAN[FULL_PLAN.index("SCENARIO 1:"):], 1)
        transcript = tmp_path / "t.jsonl"
        _write_transcript(transcript, [("user", TEMPLATE_PROMPT),
                                       ("assistant", text)])
        plan = qa_loop._read_planner_plan(str(transcript), None, None, 2)
        assert [s.index for s in plan.scenarios] == [2, 3, 4, 5]
        assert plan.source == "transcript"
        plan = qa_loop._read_planner_plan(None, lambda: text, None, 2)
        assert plan.scenarios == []
        assert "earlier block" in plan.problems[0]

    @pytest.mark.parametrize("sep", ["\n", "\n\n", "\n**\n"])
    def test_fresh_offset_plan_with_only_blank_lines_after_start_ok(self, sep):
        text = "QA_PLAN_START" + sep + _renumbered(
            FULL_PLAN[FULL_PLAN.index("SCENARIO 1:"):], 1)
        sc = parse_qa_plan(text)
        assert qa_loop.qa_plan_problem(text, sc, 2) is None


class TestAngleBracketTitles:
    def test_real_title_starting_with_angle_bracket_kept(self):
        text = FULL_PLAN.replace("SCENARIO 3: All launch paths get fallback",
                                 "SCENARIO 3: <Enter> key: all launch paths")
        sc = parse_qa_plan(text)
        assert [s.index for s in sc] == [1, 2, 3, 4]
        assert sc[2].title == "<Enter> key: all launch paths"
        assert qa_loop.qa_plan_problem(text, sc, 1) is None

    @pytest.mark.parametrize("title", [
        "<descriptive title for this scenario>",
        "<descriptive title for next scenario>",
        # wrapped by a narrow pane
        "<descriptive title for", "<descriptive",
        "Scenario Title", "..."])
    def test_template_placeholders_still_detected(self, title):
        assert qa_loop._is_placeholder_title(title)

    @pytest.mark.parametrize("title", ["<Enter>", "<Enter> key submits",
                                       "<Esc>/<q> close the popup"])
    def test_closed_leading_token_is_a_real_title(self, title):
        assert not qa_loop._is_placeholder_title(title)

    def test_template_wrapped_after_first_word_is_not_a_plan(self):
        """A pane narrow enough to wrap the template's header right after
        ``<descriptive`` must not turn the echoed template into a plan."""
        text = re.sub(r'(SCENARIO \d+: <descriptive) ', r'\1\n', TEMPLATE_PROMPT)
        assert "SCENARIO 1: <descriptive\n" in text
        sc = parse_qa_plan(text)
        assert sc == [] or qa_loop.qa_plan_problem(text, sc, 1) is not None


# ---------------------------------------------------------------------------
# Planner head publication before remote-backed fan-out
# ---------------------------------------------------------------------------

def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def remote_setup(tmp_path, monkeypatch):
    """bare 'GitHub' remote + PR workdir whose branch is published at A.

    The planner then commits B (application code) and C (QA spec) locally
    without pushing.  Returns a dict of paths and shas.
    """
    # Bypass any sandbox git push-proxy shim so pushes reach the bare repo.
    monkeypatch.setenv("PATH", os.pathsep.join(
        d for d in os.environ.get("PATH", "").split(os.pathsep)
        if not d.endswith("/.local/bin")))
    env_git = ["-c", "user.email=t@t", "-c", "user.name=t"]
    remote = tmp_path / "remote.git"
    _git(tmp_path, "init", "--bare", "-b", "master", str(remote))
    workdir = tmp_path / "workdir"
    _git(tmp_path, "init", "-b", "master", str(workdir))
    (workdir / "app.py").write_text("v = 1\n")
    _git(workdir, "add", ".")
    _git(workdir, *env_git, "commit", "-m", "base")
    _git(workdir, "checkout", "-b", "pm/pr-001")
    _git(workdir, "remote", "add", "origin", str(remote))
    _git(workdir, "push", "origin", "master", "pm/pr-001")
    a = _git(workdir, "rev-parse", "HEAD")
    (workdir / "app.py").write_text("v = 2  # planner fix\n")
    _git(workdir, *env_git, "commit", "-am", "planner fix")
    b = _git(workdir, "rev-parse", "HEAD")
    (workdir / "pm" / "qa" / "instructions").mkdir(parents=True)
    (workdir / "pm" / "qa" / "instructions" / "s6.md").write_text("S6\n")
    _git(workdir, "add", ".")
    _git(workdir, *env_git, "commit", "-m", "planner qa instructions")
    c = _git(workdir, "rev-parse", "HEAD")
    return {"tmp": tmp_path, "remote": remote, "workdir": workdir,
            "a": a, "b": b, "c": c, "env_git": env_git,
            "real_url": f"file://{remote}"}


def _clone_and_pull(s, expected_head=None):
    """Scenario workdir clone + the worker's ``pull --rebase``."""
    qa_wd = s["tmp"] / "qa"
    qa_wd.mkdir(exist_ok=True)
    kwargs = {}
    if expected_head is not None:
        kwargs["expected_head"] = expected_head
    with patch("pm_core.push_proxy.resolve_real_origin",
               return_value=s["real_url"]):
        clone, _ = qa_loop.create_scenario_workdir(
            qa_wd, 1, repo_root=s["workdir"], branch="pm/pr-001", **kwargs)
    subprocess.run(["git", *s["env_git"], "pull", "--rebase", "origin",
                    "pm/pr-001"], cwd=clone, capture_output=True, text=True)
    return clone


class TestPlannerHeadPublication:
    def test_unpublished_planner_head_is_lost_without_publish(
            self, remote_setup):
        """Documents the #229 mechanism: clone + origin swap + pull --rebase
        silently rewinds to the published (stale) head."""
        s = remote_setup
        clone = _clone_and_pull(s)
        assert _git(clone, "rev-parse", "HEAD") == s["a"]

    def test_publish_then_clone_keeps_planner_commits(self, remote_setup):
        s = remote_setup
        with patch("pm_core.push_proxy.resolve_real_origin",
                   return_value=s["real_url"]):
            head = qa_loop._publish_planner_head(str(s["workdir"]),
                                                 "pm/pr-001")
        assert head == s["c"]
        assert _git(s["remote"], "rev-parse", "pm/pr-001") == s["c"]
        clone = _clone_and_pull(s, expected_head=head)
        assert _git(clone, "rev-parse", "HEAD") == s["c"]
        assert (clone / "pm" / "qa" / "instructions" / "s6.md").exists()
        assert "planner fix" in (clone / "app.py").read_text()

    def test_publish_noop_when_already_published(self, remote_setup):
        s = remote_setup
        _git(s["workdir"], "push", "origin", "pm/pr-001")
        with patch("pm_core.push_proxy.resolve_real_origin",
                   return_value=s["real_url"]), \
             patch("pm_core.qa_loop.subprocess.run",
                   wraps=subprocess.run) as run:
            head = qa_loop._publish_planner_head(str(s["workdir"]),
                                                 "pm/pr-001")
        assert head == s["c"]
        assert not any("push" in c.args[0] for c in run.call_args_list)

    def test_diverged_remote_fails_clearly(self, remote_setup):
        s = remote_setup
        other = s["tmp"] / "other"
        _git(s["tmp"], "clone", "-b", "pm/pr-001", str(s["remote"]),
             str(other))
        (other / "x.txt").write_text("x\n")
        _git(other, "add", ".")
        _git(other, *s["env_git"], "commit", "-m", "someone else")
        _git(other, "push", "origin", "pm/pr-001")
        with patch("pm_core.push_proxy.resolve_real_origin",
                   return_value=s["real_url"]):
            with pytest.raises(qa_loop.PlannerHandoffError) as ei:
                qa_loop._publish_planner_head(str(s["workdir"]), "pm/pr-001")
        msg = str(ei.value)
        assert s["c"][:8] in msg and "diverged" in msg
        # Never force-pushed over someone else's commit.
        assert _git(s["remote"], "rev-parse", "pm/pr-001") != s["c"]

    @pytest.mark.parametrize("fetched", [True, False],
                             ids=["fetched", "never-fetched"])
    def test_behind_remote_says_behind_not_diverged(self, remote_setup,
                                                    fetched):
        # The upstream already has the planner head plus a later commit
        # (e.g. a previous QA worker's pushed fix the workdir never pulled).
        # Usually nobody fetched in the PR workdir, so the upstream commit
        # is not even in its object store — still "behind", not diverged.
        s = remote_setup
        _git(s["workdir"], "push", "origin", "pm/pr-001")
        other = s["tmp"] / "other"
        _git(s["tmp"], "clone", "-b", "pm/pr-001", str(s["remote"]),
             str(other))
        (other / "x.txt").write_text("x\n")
        _git(other, "add", ".")
        _git(other, *s["env_git"], "commit", "-m", "qa: worker fix")
        _git(other, "push", "origin", "pm/pr-001")
        if fetched:
            _git(s["workdir"], "fetch", "origin")
        with patch("pm_core.push_proxy.resolve_real_origin",
                   return_value=s["real_url"]):
            with pytest.raises(qa_loop.PlannerHandoffError) as ei:
                qa_loop._publish_planner_head(str(s["workdir"]), "pm/pr-001")
        msg = str(ei.value)
        assert "is behind upstream" in msg and "diverged" not in msg
        assert "Pull the PR branch" in msg
        # Classifying must not move the workdir's branch.
        assert _git(s["workdir"], "rev-parse", "pm/pr-001") == s["c"]

    def test_origin_not_pushing_upstream_falls_back_to_direct_push(
            self, remote_setup):
        """origin = local main repo that itself tracks the upstream: the
        origin push never reaches the upstream, so push there directly."""
        s = remote_setup
        main = s["tmp"] / "main.git"
        _git(s["tmp"], "init", "--bare", str(main))
        _git(s["workdir"], "remote", "set-url", "--push", "origin", str(main))
        with patch("pm_core.push_proxy.resolve_real_origin",
                   return_value=s["real_url"]):
            head = qa_loop._publish_planner_head(str(s["workdir"]),
                                                 "pm/pr-001")
        assert head == s["c"]
        assert _git(s["remote"], "rev-parse", "pm/pr-001") == s["c"]
        assert _git(main, "rev-parse", "pm/pr-001") == s["c"]

    def test_push_that_never_reaches_upstream_fails_clearly(
            self, remote_setup):
        s = remote_setup
        # origin pushes elsewhere and the upstream rejects direct pushes.
        elsewhere = s["tmp"] / "elsewhere.git"
        _git(s["tmp"], "init", "--bare", str(elsewhere))
        _git(s["workdir"], "remote", "set-url", "--push", "origin",
             str(elsewhere))
        hook = s["remote"] / "hooks" / "pre-receive"
        hook.write_text("#!/bin/sh\necho 'denied by upstream' >&2\nexit 1\n")
        hook.chmod(0o755)
        with patch("pm_core.push_proxy.resolve_real_origin",
                   return_value=s["real_url"]):
            with pytest.raises(qa_loop.PlannerHandoffError) as ei:
                qa_loop._publish_planner_head(str(s["workdir"]), "pm/pr-001")
        msg = str(ei.value)
        assert "could not publish" in msg
        assert s["a"][:12] in msg and "denied by upstream" in msg

    def test_local_only_returns_local_head(self, remote_setup):
        s = remote_setup
        with patch("pm_core.push_proxy.resolve_real_origin",
                   return_value=None):
            head = qa_loop._publish_planner_head(str(s["workdir"]),
                                                 "pm/pr-001")
        assert head == s["c"]

    def test_clone_head_mismatch_raises(self, remote_setup):
        s = remote_setup
        with pytest.raises(RuntimeError) as ei:
            _clone_and_pull(s, expected_head=s["a"])
        assert s["a"][:8] in str(ei.value) and s["c"][:8] in str(ei.value)

    def test_planner_code_changes_excludes_pm_metadata(self, remote_setup):
        s = remote_setup
        changed = qa_loop._planner_code_changes(
            str(s["workdir"]), s["a"], s["c"])
        assert changed == ["app.py"]
        assert qa_loop._planner_code_changes(
            str(s["workdir"]), s["b"], s["c"]) == []
        assert qa_loop._planner_code_changes(
            str(s["workdir"]), s["c"], s["c"]) == []


class TestLaunchFailureReason:
    def test_clone_mismatch_reason_reaches_scenario_verdict(self, tmp_path):
        """A refused clone (head mismatch) is reported as the scenario's
        reason, not hidden behind a generic launch failure."""
        state = QALoopState(pr_id="pr-001")
        state.qa_workdir = str(tmp_path / "qa")
        state.scenarios = parse_qa_plan(FULL_PLAN)[:1]
        state.planner_head = "c" * 40
        err = RuntimeError("scenario 1 clone of b is at aaaa but the "
                           "published planner head is cccc")
        with patch("pm_core.qa_loop._resolve_qa_model"), \
             patch("pm_core.qa_loop.create_scenario_workdir",
                   side_effect=err) as create:
            qa_loop._launch_scenarios_in_tmux(
                state, {}, {"branch": "b"}, "pm-test", tmp_path,
                str(tmp_path))
        assert create.call_args.kwargs["expected_head"] == "c" * 40
        assert "published planner head" in state.scenario_verdict_reasons[1]
        assert state.scenarios[0].window_name is None


class TestPlannerCodeChangesForceReview:
    def _finalize(self, state, tmp_path):
        with patch("pm_core.qa_loop._poll_tmux_verdicts"), \
             patch("pm_core.qa_loop._write_status_file"), \
             patch("pm_core.qa_loop._write_resume_file"), \
             patch("pm_core.qa_loop._persist_scenario_verdicts"), \
             patch("pm_core.qa_loop._run_qa_finalize_pane",
                   return_value="FINALIZE_DONE"):
            return qa_loop._execute_and_finalize(
                state, tmp_path, {"branch": "b"}, {}, "pm-test", "qa-w",
                str(tmp_path), tmp_path / "status.json", None,
                use_containers=False, concurrency_cap=0,
                queued_scenarios=[], notify=lambda: None)

    def test_all_pass_with_planner_code_edit_needs_work(self, tmp_path):
        state = QALoopState(pr_id="pr-001")
        state.scenarios = parse_qa_plan(FULL_PLAN)
        state.scenario_verdicts = {s.index: "PASS" for s in state.scenarios}
        state.planner_code_changes = ["app.py"]
        self._finalize(state, tmp_path)
        assert state.latest_verdict == qa_loop.VERDICT_NEEDS_WORK
        assert "app.py" in state.latest_output
        assert "review" in state.latest_output

    def test_all_pass_without_planner_code_edit_passes(self, tmp_path):
        state = QALoopState(pr_id="pr-001")
        state.scenarios = parse_qa_plan(FULL_PLAN)
        state.scenario_verdicts = {s.index: "PASS" for s in state.scenarios}
        self._finalize(state, tmp_path)
        assert state.latest_verdict == qa_loop.VERDICT_PASS

    def test_planner_code_changes_survive_resume_file(self, tmp_path):
        state = QALoopState(pr_id="pr-001")
        state.qa_workdir = str(tmp_path)
        state.scenarios = parse_qa_plan(FULL_PLAN)
        state.planner_code_changes = ["app.py"]
        qa_loop._write_resume_file(state, False, 0, set())
        data = qa_loop._load_resume_file(tmp_path)
        rebuilt = qa_loop.build_resume_state(data)
        assert rebuilt.planner_code_changes == ["app.py"]

    def test_qa_note_explains_planner_code_edit(self, tmp_path):
        # The PR note is what the next review session sees; an all-PASS
        # NEEDS_WORK must say the planner's code edit is why.
        from pm_core import store
        from pm_core.tui import qa_loop_ui
        state = QALoopState(pr_id="pr-001")
        state.scenarios = parse_qa_plan(FULL_PLAN)
        state.scenario_verdicts = {s.index: "PASS" for s in state.scenarios}
        state.latest_verdict = qa_loop.VERDICT_NEEDS_WORK
        state.planner_code_changes = ["app.py"]
        data = {"prs": [{"id": "pr-001", "notes": []}]}
        app = MagicMock(_root=tmp_path)
        with patch.object(store, "locked_update",
                          side_effect=lambda root, fn: fn(data)):
            qa_loop_ui._record_qa_note(app, state)
        note = data["prs"][0]["notes"][0]["text"]
        assert note.startswith("QA NEEDS_WORK:")
        assert "planner edited application code (app.py)" in note
