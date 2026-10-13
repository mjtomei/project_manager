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
import subprocess
import time
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

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
                  extra_patches: tuple = ()):
    """Drive run_qa_sync's planning phase with a fake tmux + hook layer.

    Returns the final state.  The PR has no QA spec, so when a plan is
    accepted run_qa_sync returns at the spec gate right after planning —
    before any scenario launch — leaving ``state.scenarios`` as the
    accepted plan.  When no plan is accepted the spec gate is skipped and
    the harness stops at the first Phase 2 tmux call.
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

    def fake_build_cmd(**kw):
        if transcript_turns is not None:
            _write_transcript(
                transcript_path_for(kw["cwd"], kw["session_id"]),
                transcript_turns)
        return "planner-cmd"

    calls = {"n": 0}

    def fake_wait_for_event(session_id, **kw):
        calls["n"] += 1
        if calls["n"] <= idle_events:
            return {"event_type": "idle_prompt", "timestamp": time.time()}
        state.stop_requested = True
        return None

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
        patch("pm_core.qa_loop.time.sleep"),
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

    def test_stale_turn_not_reparsed_without_fresh_idle(
            self, tmp_path, monkeypatch):
        """Freshness: without an idle_prompt event nothing is read."""
        with patch("pm_core.qa_loop.read_latest_assistant_text"
                   ) as read_text:
            state = _run_planning(
                tmp_path, monkeypatch, pane_content=PANE_TAIL_ONLY,
                transcript_turns=[("user", TEMPLATE_PROMPT),
                                  ("assistant", FULL_PLAN)],
                idle_events=0)
        read_text.assert_not_called()
        assert state.scenarios == []

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
