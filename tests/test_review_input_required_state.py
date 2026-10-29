"""Review-loop INPUT_REQUIRED wait state (pr-a80bde5).

The wait state lives on ``ReviewLoopState.input_required`` and drives
``pm autostart status`` (via ``review_progress_input`` → ``build_status``),
the TUI runs view and the tech-tree marker.  These tests drive the real
follow-up waiter against real JSONL transcripts and hook event files —
only the tmux pane lookup and the review launch are stubbed — and check
both the state and the displayed reason:

  INPUT_REQUIRED → user answers → follow-up running → NEEDS_WORK →
  next iteration running; repeated genuine INPUT_REQUIRED; restart
  adoption; tool output never counts as an answer.
"""

import json
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from pm_core import autostart_state, hook_events, loop_shared
from pm_core import review_loop as rl
from pm_core.review_loop import (
    ReviewIteration,
    ReviewLoopState,
    run_review_loop_sync,
)
from pm_core.verdict_transcript import HumanResponseWatch, is_human_prompt_record

PR_ID = "pr-001"
PR = {"id": PR_ID, "title": "T", "status": "in_review", "workdir": "/tmp/wd"}


# ---------------------------------------------------------------------------
# A fake review pane: Claude-format JSONL records + idle_prompt hook events
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z")


class Pane:
    """One review iteration's Claude session (transcript symlink + hooks)."""

    def __init__(self, tdir: Path, iteration: int):
        self.sid = str(uuid.uuid4())
        native = tdir / "native"
        native.mkdir(exist_ok=True)
        self.native = native / f"{self.sid}.jsonl"
        self.native.touch()
        self.link = tdir / f"review-{PR_ID}-i{iteration}.jsonl"
        if self.link.is_symlink() or self.link.exists():
            self.link.unlink()
        self.link.symlink_to(self.native)
        self.k = 0
        self.user("<review prompt>")

    def _rec(self, rec: dict) -> None:
        rec.setdefault("timestamp", _now_iso())
        rec.setdefault("sessionId", self.sid)
        with self.native.open("a") as f:
            f.write(json.dumps(rec) + "\n")

    def user(self, text: str) -> None:
        """The human submits a prompt in the pane."""
        # Record timestamps are millisecond ISO strings; keep the answer
        # strictly after a preceding idle event, as a human's would be.
        time.sleep(0.01)
        self._rec({"type": "user", "message": {"role": "user", "content": text}})

    def harness(self, text: str) -> None:
        """The harness injects a ``type: "user"`` record (not a human)."""
        time.sleep(0.01)
        self._rec({"type": "user", "message": {"role": "user", "content": text}})

    def say(self, text: str) -> None:
        self._rec({"type": "assistant", "message": {
            "role": "assistant", "content": [{"type": "text", "text": text}]}})

    def tool(self, output: str, command: str = "pytest -q") -> None:
        """Claude runs a tool; its output is a ``type: user`` tool_result."""
        self.k += 1
        tid = f"toolu_{self.k}"
        self._rec({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": tid, "name": "Bash",
             "input": {"command": command}}]}})
        self._rec({"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": tid, "content": output}]}})

    def idle(self) -> None:
        """Claude finished its turn (the idle_prompt hook fired)."""
        time.sleep(0.01)  # idle strictly after the turn's records
        path = hook_events.event_path(self.sid)
        path.write_text(json.dumps({"event_type": "idle_prompt",
                                    "timestamp": time.time(),
                                    "session_id": self.sid}))

    def verdict(self, v: str, body: str = "Done.") -> str:
        text = f"{body}\n\n**{v}**"
        self.say(text)
        self.idle()
        return text


@pytest.fixture(autouse=True)
def isolated_hooks(tmp_path, monkeypatch):
    """Give every test its own hook-event directory.

    ``hook_events._HOOKS_BASE`` is frozen from ``$HOME`` at import time, and in
    a full-suite run that import can happen inside another test's patched
    ``HOME`` — the ambient value is another test's (deleted) tmp_path.  Every
    test here writes hook events, so point it at this test's ``tmp_path``.
    """
    hooks = tmp_path / "hooks"
    hooks.mkdir(exist_ok=True)
    monkeypatch.setattr(hook_events, "_HOOKS_BASE", hooks)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(rl, "_FOLLOW_UP_POLL", 0.05, raising=False)
    monkeypatch.setattr(rl, "_get_pm_session", lambda: "pm-test")
    pane_alive = {"alive": True}
    find_pane = lambda s, w: "%1" if pane_alive["alive"] else None  # noqa: E731
    monkeypatch.setattr(rl, "_find_claude_pane", find_pane)
    monkeypatch.setattr(loop_shared, "find_claude_pane", find_pane)
    # The failed-launch retry layer (pr-e040aeb) is covered by
    # test_review_launch_retry.py.  Here it would only put a launch lease and
    # a discovery pass around the stubbed launch; neutralise it so these
    # tests keep exercising the wait state itself.
    monkeypatch.setattr(rl, "_claim_launch", lambda *a, **k: True)
    monkeypatch.setattr(rl, "_pr_is_terminal", lambda *a, **k: False)
    monkeypatch.setattr(rl, "_DISCOVERY_GRACE", 0.0)
    tdir = tmp_path / "transcripts"
    tdir.mkdir()
    return tdir, pane_alive


def _until(cond, timeout=5.0, what="condition"):
    """Wait for an observable state change (bounded; not a fixed sleep)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return
        time.sleep(0.01)
    raise AssertionError(f"timed out waiting for {what}")


def _status(state) -> tuple[str, str, dict]:
    """(state, reason, review) as ``pm autostart status --json`` reports it."""
    st = autostart_state.build_status({
        "prs": [PR], "targets": {PR_ID: {}}, "enabled": True,
        "review_loops": {PR_ID: autostart_state.review_progress_input(state)},
    })
    run = next(r for r in st["runs"] if r["pr_id"] == PR_ID)
    return run["state"], run["reason"], run["review"]


def _start(state, tdir, launches, on_iteration=None):
    """Run the loop in a thread; ``launches`` maps iteration → callable
    returning the review output (it may block to keep the iteration live)."""
    def fake_review(pr_id, pm_root, pr_data, transcript, iteration=0,
                    loop_id="", **_kw):
        return launches[iteration]()
    p = patch.object(rl, "_run_claude_review", side_effect=fake_review)
    mock = p.start()
    t = threading.Thread(target=run_review_loop_sync,
                         args=(state, "/tmp", PR, str(tdir)),
                         kwargs={"on_iteration": on_iteration}, daemon=True)
    t.start()
    return t, mock, p


# ---------------------------------------------------------------------------
# What counts as a human answer
# ---------------------------------------------------------------------------

class TestHumanPromptRecord:
    def test_string_prompt(self):
        assert is_human_prompt_record(
            {"type": "user", "message": {"content": "use option A"}})

    def test_text_block_prompt(self):
        assert is_human_prompt_record({"type": "user", "message": {
            "content": [{"type": "text", "text": "yes"}]}})

    def test_tool_result_is_not_an_answer(self):
        assert not is_human_prompt_record({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t", "content": "yes\nPASS"}]}})

    def test_meta_and_local_commands_are_not_answers(self):
        assert not is_human_prompt_record(
            {"type": "user", "isMeta": True, "message": {"content": "Caveat: ..."}})
        assert not is_human_prompt_record({"type": "user", "message": {
            "content": "<command-name>/cost</command-name>"}})
        assert not is_human_prompt_record({"type": "user", "message": {
            "content": "<local-command-stdout>$0.12</local-command-stdout>"}})

    def test_assistant_is_not_an_answer(self):
        assert not is_human_prompt_record(
            {"type": "assistant", "message": {"content": "yes"}})

    def test_harness_records_are_not_answers(self):
        """Claude Code and pm's own loops write ``type: "user"`` records that
        are not human input.  Counting one would clear a wait nobody
        answered."""
        for text in (
            "<system-reminder>\nThe user opened the file a.py.\n</system-reminder>",
            "<system-reminder>\nNotice one.\n</system-reminder>\n"
            "<system-reminder>\nNotice two.\n</system-reminder>",
            "<task-notification>\n<task-id>t1</task-id>\n</task-notification>",
            "# /loop tick\ncontinue",
            "# Autonomous loop check",
            "[SCHEDULED TASK - AUTOMATED FIRING OF A CONFIGURED PROMPT]",
            "[Request interrupted by user]",
            "[Request interrupted by user for tool use]",
            "Reminder: your verdict must appear alone on its line",
            "<<autonomous-loop>>",
            "   ",
        ):
            assert not is_human_prompt_record(
                {"type": "user", "message": {"content": text}}), text

    def test_prompt_with_appended_reminder_is_an_answer(self):
        """A real answer carrying a reminder is still the human's answer."""
        assert is_human_prompt_record({"type": "user", "message": {"content": (
            "use option A\n\n<system-reminder>ide notice</system-reminder>")}})

    def test_record_with_no_text_is_not_an_answer(self):
        """A ``type:"user"`` record whose only content is an empty/whitespace
        text block carries nothing: it must not clear a wait (the false-answer
        mirror of the bug this PR fixes), and it agrees with the shared
        task-boundary predicate the verdict scan uses."""
        from pm_core.verdict_transcript import _user_record_is_non_task
        for content in ([{"type": "text", "text": ""}],
                        [{"type": "text", "text": None}],
                        [{"type": "text", "text": "   "}],
                        [{"type": "tool_result", "content": "x"},
                         {"type": "image", "source": {}}]):
            rec = {"type": "user", "message": {"content": content}}
            assert _user_record_is_non_task(rec), content
            assert not is_human_prompt_record(rec), content

    def test_pasted_image_is_an_answer(self):
        """Content with no text at all is still a human prompt."""
        for content in ([{"type": "image", "source": {}}],
                        [{"type": "image", "source": {}},
                         {"type": "text", "text": ""}]):
            assert is_human_prompt_record(
                {"type": "user", "message": {"content": content}}), content

    def test_agrees_with_the_shared_task_boundary_predicate(self):
        """Built on ``_user_record_is_non_task``, so the answer predicate and
        the task-scoped verdict scan can never disagree about which records
        are transparent to a task."""
        from pm_core.verdict_transcript import _user_record_is_non_task
        for text in (
            "<system-reminder>ide notice</system-reminder>",
            "<task-notification>x</task-notification>",
            "# /loop tick\ncontinue",
            "[Request interrupted by user]",
            "Reminder: your verdict must appear alone on its line",
            "<command-name>/model</command-name>",
            "<local-command-stdout>$0.12</local-command-stdout>",
        ):
            rec = {"type": "user", "message": {"content": text}}
            assert _user_record_is_non_task(rec), text
            assert not is_human_prompt_record(rec), text


class TestHumanResponseWatch:
    def test_unanswered_then_answered(self, tmp_path):
        pane = Pane(tmp_path, 1)
        pane.verdict("INPUT_REQUIRED", "Option A or B?")
        w = HumanResponseWatch(pane.link, "INPUT_REQUIRED")
        assert w.answered_at is None
        pane.tool("1 passed\nyes\nPASS")
        assert w.poll() is None, "tool output must not count as an answer"
        pane.user("use option A")
        assert w.poll() is not None

    def test_answer_before_watch_found_by_back_scan(self, tmp_path):
        """A restart after the user answered: the answer is already there."""
        pane = Pane(tmp_path, 1)
        pane.verdict("INPUT_REQUIRED")
        pane.user("use option A")
        pane.tool("ran", command="grep -n INPUT_REQUIRED pm_core/review_loop.py")
        assert HumanResponseWatch(pane.link, "INPUT_REQUIRED").answered_at is not None

    def test_back_scan_stops_at_question(self, tmp_path):
        """The initial review prompt (before the question) is not an answer."""
        pane = Pane(tmp_path, 1)
        pane.tool("x")
        pane.verdict("INPUT_REQUIRED")
        assert HumanResponseWatch(pane.link, "INPUT_REQUIRED").answered_at is None

    def test_back_scan_without_question_record_stays_unanswered(self, tmp_path):
        """Question record not found (verdict not on its own line): the
        review prompt must not be mistaken for an answer."""
        pane = Pane(tmp_path, 1)
        pane.say("Verdict: INPUT_REQUIRED")
        assert HumanResponseWatch(pane.link, "INPUT_REQUIRED").answered_at is None

    def test_rearm(self, tmp_path):
        pane = Pane(tmp_path, 1)
        pane.verdict("INPUT_REQUIRED")
        w = HumanResponseWatch(pane.link, "INPUT_REQUIRED")
        pane.user("a")
        assert w.poll() is not None
        w.rearm()
        assert w.poll() is None
        pane.user("b")
        assert w.poll() is not None

    def test_assistant_after_answer_tracks_new_turns(self, tmp_path):
        """An answer followed by no assistant record is the turn just
        answered; Claude speaking again starts a new turn."""
        pane = Pane(tmp_path, 1)
        pane.verdict("INPUT_REQUIRED")
        w = HumanResponseWatch(pane.link, "INPUT_REQUIRED")
        assert w.answered_at is None and w.assistant_after_answer is False
        pane.user("use option A")
        assert w.poll() is not None and w.assistant_after_answer is False
        pane.say("Working on it.")
        w.poll()
        assert w.assistant_after_answer is True
        pane.user("and the other file")
        w.poll()
        assert w.assistant_after_answer is False

    def test_assistant_after_answer_found_by_back_scan(self, tmp_path):
        """After a restart the answer and Claude's next turn are both
        already in the transcript."""
        pane = Pane(tmp_path, 1)
        pane.verdict("INPUT_REQUIRED")
        pane.user("use option A")
        pane.say("Working on it.")
        w = HumanResponseWatch(pane.link, "INPUT_REQUIRED")
        assert w.answered_at is not None and w.assistant_after_answer is True

    def test_back_scan_answer_with_no_new_turn(self, tmp_path):
        pane = Pane(tmp_path, 1)
        pane.verdict("INPUT_REQUIRED")
        pane.user("use option A")
        w = HumanResponseWatch(pane.link, "INPUT_REQUIRED")
        assert w.answered_at is not None and w.assistant_after_answer is False

    def test_wakeup_turn_tracking(self, tmp_path):
        """A harness wakeup starts a turn of its own; a human prompt, or a
        tool result (part of the assistant's turn), does not."""
        pane = Pane(tmp_path, 1)
        pane.verdict("INPUT_REQUIRED")
        w = HumanResponseWatch(pane.link, "INPUT_REQUIRED")
        assert w.wakeup_turn is False
        pane.user("use option A")
        w.poll()
        assert w.wakeup_turn is False
        pane.tool("ran the tests")
        w.poll()
        assert w.wakeup_turn is False, "a tool result does not start a turn"
        pane.harness("# /loop tick\ncontinue")
        w.poll()
        assert w.wakeup_turn is True
        pane.user("and the other file")
        w.poll()
        assert w.wakeup_turn is False

    def test_wakeup_turn_found_by_back_scan(self, tmp_path):
        """After a restart: answer -> wakeup turn -> assistant reply with no
        verdict.  The turn is the wakeup's, not a question to the human."""
        pane = Pane(tmp_path, 1)
        pane.verdict("INPUT_REQUIRED")
        pane.user("use option A")
        pane.harness("# /loop tick\ncontinue")
        pane.say("Nothing new to do.")
        w = HumanResponseWatch(pane.link, "INPUT_REQUIRED")
        assert w.answered_at is not None and w.assistant_after_answer is True
        assert w.wakeup_turn is True

    def test_wakeup_turn_survives_transparent_records(self, tmp_path):
        """Transparent records are injected around a turn, not a turn of
        their own: a reminder or a local-command echo landing after the
        wakeup must not make the turn look human-started (its idle would
        then be read as a prose question and re-arm a wait nobody asked)."""
        pane = Pane(tmp_path, 1)
        pane.verdict("INPUT_REQUIRED")
        w = HumanResponseWatch(pane.link, "INPUT_REQUIRED")
        pane.user("use option A")
        pane.harness("# /loop tick\ncontinue")
        w.poll()
        assert w.wakeup_turn is True
        for text in (
            "<system-reminder>\nThe user opened the file a.py.\n"
            "</system-reminder>",
            "<local-command-stdout>$0.12</local-command-stdout>",
            "<command-name>/model</command-name>",
        ):
            pane.harness(text)
            w.poll()
            assert w.wakeup_turn is True, (
                f"a transparent record ({text.splitlines()[0]}) changed the "
                "turn ownership")
        # A turn the human starts still ends the wakeup's turn.
        pane.user("and the other file")
        w.poll()
        assert w.wakeup_turn is False

    def test_wakeup_turn_survives_transparent_records_in_back_scan(self,
                                                                   tmp_path):
        """Same rule after a restart, where the watch back-scans the file."""
        pane = Pane(tmp_path, 1)
        pane.verdict("INPUT_REQUIRED")
        pane.user("use option A")
        pane.harness("# /loop tick\ncontinue")
        pane.harness("<system-reminder>\nOpened a.py.\n</system-reminder>")
        pane.say("Nothing new to do.")
        w = HumanResponseWatch(pane.link, "INPUT_REQUIRED")
        assert w.answered_at is not None and w.assistant_after_answer is True
        assert w.wakeup_turn is True

    def test_interrupt_marker_keeps_the_turn_the_humans(self, tmp_path):
        """Esc is the human stopping their own turn: it is not a wakeup, so
        an idle after it still re-arms the wait (the human acted, and nobody
        else can move the loop on)."""
        pane = Pane(tmp_path, 1)
        pane.verdict("INPUT_REQUIRED")
        w = HumanResponseWatch(pane.link, "INPUT_REQUIRED")
        pane.user("use option A")
        pane.harness("# /loop tick\ncontinue")
        w.poll()
        assert w.wakeup_turn is True
        pane.harness("[Request interrupted by user]")
        w.poll()
        assert w.wakeup_turn is False


# ---------------------------------------------------------------------------
# Live loop: INPUT_REQUIRED → answer → follow-up → NEEDS_WORK → next iteration
# ---------------------------------------------------------------------------

class TestLiveFlow:
    def test_answered_follow_up_then_next_iteration(self, env):
        tdir, _ = env
        panes = {}
        release2 = threading.Event()

        def it1():
            panes[1] = Pane(tdir, 1)
            panes[1].tool("10 passed")
            return panes[1].verdict("INPUT_REQUIRED", "Option A or B?")

        def it2():
            panes[2] = Pane(tdir, 2)
            panes[2].tool("347 passed")
            release2.wait(10)
            return panes[2].verdict("PASS")

        state = ReviewLoopState(pr_id=PR_ID)
        t, mock, p = _start(state, tdir, {1: it1, 2: it2})
        try:
            # Genuine wait: visible as waiting, even while idle hooks repeat
            # for the same unanswered turn and tool output says "yes/PASS".
            _until(lambda: state.input_required, what="INPUT_REQUIRED wait")
            assert _status(state)[:2] == ("waiting", "review INPUT_REQUIRED (iteration 1)")
            panes[1].idle()
            panes[1].idle()
            time.sleep(0.2)
            assert state.input_required and t.is_alive()
            assert mock.call_count == 1, "stale idle re-read must not relaunch"

            # The user answers; Claude works on the follow-up.
            panes[1].user("use option A")
            _until(lambda: not state.input_required, what="answer to clear wait")
            panes[1].tool("200 passed\nPASS")
            s, reason, review = _status(state)
            assert s == "running"
            assert reason == ("review iteration 1 "
                              "(INPUT_REQUIRED answered; follow-up running)")
            assert review["input_required"] is False and review["follow_up"] is True

            # Follow-up NEEDS_WORK → iteration 2 owns the work.
            panes[1].verdict("NEEDS_WORK", "Fixed it.")
            _until(lambda: state.iteration == 2 and 2 in panes, what="iteration 2")
            s, reason, review = _status(state)
            assert (s, reason) == ("running", "review iteration 2 (last NEEDS_WORK)")
            assert review["input_required"] is False and review["follow_up"] is False
            assert state.history[0].verdict == "NEEDS_WORK"

            release2.set()
            t.join(5)
            assert not t.is_alive()
            assert state.latest_verdict == "PASS" and state.input_required is False
        finally:
            release2.set()
            p.stop()

    def test_repeated_genuine_input_required_stays_visible(self, env):
        tdir, _ = env
        panes = {}

        def it1():
            panes[1] = Pane(tdir, 1)
            return panes[1].verdict("INPUT_REQUIRED", "First question?")

        state = ReviewLoopState(pr_id=PR_ID)
        notified = []
        state_cb = lambda s: notified.append(s.latest_verdict)  # noqa: E731
        with patch.object(rl, "_run_claude_review",
                          side_effect=lambda *a, **k: it1()) as mock:
            t = threading.Thread(target=run_review_loop_sync,
                                 args=(state, "/tmp", PR, str(tdir)),
                                 kwargs={"on_iteration": state_cb}, daemon=True)
            t.start()
            _until(lambda: state.input_required, what="first wait")
            panes[1].user("A")
            _until(lambda: not state.input_required, what="first answer")
            panes[1].tool("checked")
            panes[1].verdict("INPUT_REQUIRED", "Second question?")
            # A new question: waiting again, same pane, no relaunch.
            _until(lambda: state.input_required, what="second wait")
            assert _status(state)[:2] == ("waiting", "review INPUT_REQUIRED (iteration 1)")
            assert state._ui_notified_input is False  # notification re-armed
            assert notified[-1] == "INPUT_REQUIRED"
            time.sleep(0.2)
            assert mock.call_count == 1 and t.is_alive()
            # Exactly one round per question: no re-recording of the same
            # turn while the human has not answered it.
            assert notified == ["INPUT_REQUIRED", "INPUT_REQUIRED"]

            panes[1].user("B")
            _until(lambda: not state.input_required, what="second answer")
            panes[1].verdict("PASS")
            t.join(5)
        assert state.latest_verdict == "PASS"
        assert [h.verdict for h in state.history] == ["PASS"]

    def test_idle_without_verdict_after_answer_is_waiting(self, env):
        tdir, _ = env
        panes = {}

        def it1():
            panes[1] = Pane(tdir, 1)
            return panes[1].verdict("INPUT_REQUIRED")

        state = ReviewLoopState(pr_id=PR_ID)
        t, mock, p = _start(state, tdir, {1: it1})
        try:
            _until(lambda: state.input_required)
            panes[1].user("A")
            _until(lambda: not state.input_required)
            panes[1].say("Do you mean option A for both files?")
            panes[1].idle()
            _until(lambda: state.input_required, what="prose question waits")
            panes[1].user("yes, both")
            _until(lambda: not state.input_required)
            panes[1].verdict("PASS")
            t.join(5)
            assert state.latest_verdict == "PASS"
        finally:
            state.stop_requested = True
            p.stop()

    def test_repeated_idle_after_answer_is_not_a_new_question(self, env):
        """A refreshed idle_prompt for the turn the human just answered
        (fake-claude re-emits it every ~2 s) is a stale re-read: it must
        not re-record INPUT_REQUIRED, re-arm the notification or clear the
        answered state."""
        tdir, _ = env
        panes = {}

        def it1():
            panes[1] = Pane(tdir, 1)
            return panes[1].verdict("INPUT_REQUIRED", "Option A or B?")

        state = ReviewLoopState(pr_id=PR_ID)
        recorded = []
        t, mock, p = _start(state, tdir, {1: it1},
                            on_iteration=lambda s: recorded.append(
                                s.latest_verdict))
        try:
            _until(lambda: state.input_required, what="INPUT_REQUIRED wait")
            panes[1].user("use option A")
            _until(lambda: not state.input_required, what="answer clears wait")
            for _ in range(5):
                panes[1].idle()
                time.sleep(0.05)
            assert recorded == ["INPUT_REQUIRED"], (
                "a refreshed idle for the answered turn was re-recorded")
            assert state.input_required is False
            assert _status(state)[:2] == (
                "running",
                "review iteration 1 (INPUT_REQUIRED answered; follow-up running)")
            panes[1].verdict("PASS")
            t.join(5)
            assert state.latest_verdict == "PASS"
        finally:
            state.stop_requested = True
            p.stop()

    def test_follow_up_pass_survives_a_loop_tick_turn(self, env):
        """Answer → PASS → ``/loop`` wakeup turn is still a PASS.

        The waiter must return the *verdict turn*, not the transcript tail:
        a ``/loop`` tick (a non-task wakeup) that Claude answers without a
        verdict sits after the PASS, and parsing that reply would record
        NEEDS_WORK and launch another iteration (pr-a80bde5 sign-off).
        """
        tdir, _ = env
        panes = {}

        def it1():
            panes[1] = Pane(tdir, 1)
            return panes[1].verdict("INPUT_REQUIRED", "Option A or B?")

        state = ReviewLoopState(pr_id=PR_ID)
        t, mock, p = _start(state, tdir, {1: it1})
        try:
            _until(lambda: state.input_required, what="INPUT_REQUIRED wait")
            panes[1].user("use option A")
            _until(lambda: not state.input_required, what="answer clears wait")

            # The follow-up verdict, then a /loop wakeup whose reply carries
            # no verdict, then one idle for the whole turn.
            panes[1].say("All good.\n\n**PASS**")
            panes[1].harness("# /loop tick\ncontinue")
            panes[1].say("Nothing new to do.")
            panes[1].idle()

            t.join(5)
            assert not t.is_alive(), "a PASS follow-up must stop the loop"
            assert mock.call_count == 1, "a PASS follow-up must not relaunch"
            assert state.latest_verdict == "PASS"
            assert [h.verdict for h in state.history] == ["PASS"]
            assert state.input_required is False
        finally:
            state.stop_requested = True
            p.stop()

    def test_repeated_idle_after_answering_a_prose_question(self, env):
        """Same stale re-read, but the question was prose (no verdict):
        the answered turn must not flip the state back to waiting."""
        tdir, _ = env
        panes = {}

        def it1():
            panes[1] = Pane(tdir, 1)
            return panes[1].verdict("INPUT_REQUIRED", "Option A or B?")

        state = ReviewLoopState(pr_id=PR_ID)
        t, mock, p = _start(state, tdir, {1: it1})
        try:
            _until(lambda: state.input_required, what="INPUT_REQUIRED wait")
            panes[1].user("A")
            _until(lambda: not state.input_required, what="first answer")
            panes[1].say("Do you mean option A for both files?")
            panes[1].idle()
            _until(lambda: state.input_required, what="prose question waits")
            panes[1].user("yes, both")
            _until(lambda: not state.input_required, what="prose answer clears")
            for _ in range(5):
                panes[1].idle()
                time.sleep(0.05)
            assert state.input_required is False, (
                "a refreshed idle for the answered prose turn re-armed the wait")
            panes[1].verdict("PASS")
            t.join(5)
            assert state.latest_verdict == "PASS"
        finally:
            state.stop_requested = True
            p.stop()

    def test_wakeup_turn_after_the_answer_does_not_rearm_the_wait(self, env):
        """A non-task wakeup turn that ends before the follow-up verdict is
        not a question: the wait must not re-arm for its idle.

        A ``/loop`` tick (or task notification) starts an assistant turn of
        its own.  Answering, then letting such a turn idle with no verdict,
        used to flip the status back to ``waiting / review INPUT_REQUIRED``
        — a wait nobody asked for.
        """
        tdir, _ = env
        panes = {}

        def it1():
            panes[1] = Pane(tdir, 1)
            return panes[1].verdict("INPUT_REQUIRED", "Option A or B?")

        state = ReviewLoopState(pr_id=PR_ID)
        t, mock, p = _start(state, tdir, {1: it1})
        try:
            _until(lambda: state.input_required, what="INPUT_REQUIRED wait")
            panes[1].user("use option A")
            _until(lambda: not state.input_required, what="answer clears wait")
            panes[1].harness("# /loop tick\ncontinue")
            panes[1].say("Nothing new to do.")
            panes[1].idle()
            time.sleep(0.3)
            assert state.input_required is False, (
                "a wakeup turn's idle re-armed the wait")
            assert _status(state)[:2] == (
                "running",
                "review iteration 1 (INPUT_REQUIRED answered; follow-up running)")
            assert mock.call_count == 1
            panes[1].verdict("PASS")
            t.join(5)
            assert state.latest_verdict == "PASS"
        finally:
            state.stop_requested = True
            p.stop()

    def test_transparent_records_do_not_rearm_a_wakeup_turn(self, env):
        """A reminder or local-command echo landing between a wakeup turn and
        its idle is injected around the turn, not a turn of its own: the idle
        must not be read as a prose question and re-arm the wait."""
        tdir, _ = env
        panes = {}

        def it1():
            panes[1] = Pane(tdir, 1)
            return panes[1].verdict("INPUT_REQUIRED", "Option A or B?")

        state = ReviewLoopState(pr_id=PR_ID)
        t, mock, p = _start(state, tdir, {1: it1})
        try:
            _until(lambda: state.input_required, what="INPUT_REQUIRED wait")
            panes[1].user("use option A")
            _until(lambda: not state.input_required, what="answer clears wait")
            panes[1].harness("# /loop tick\ncontinue")
            panes[1].say("Nothing new to do.")
            panes[1].harness(
                "<system-reminder>\nThe user opened a.py.\n</system-reminder>")
            panes[1].harness(
                "<local-command-stdout>$0.12</local-command-stdout>")
            panes[1].idle()
            time.sleep(0.3)
            assert state.input_required is False, (
                "a transparent record turned the wakeup turn into a question")
            assert _status(state)[:2] == (
                "running",
                "review iteration 1 (INPUT_REQUIRED answered; follow-up running)")
            assert mock.call_count == 1
            panes[1].verdict("PASS")
            t.join(5)
            assert state.latest_verdict == "PASS"
        finally:
            state.stop_requested = True
            p.stop()

    def test_harness_record_does_not_answer_the_question(self, env):
        """A system reminder / task notification / loop tick is a
        ``type: "user"`` record but not a human answer: the wait must stay."""
        tdir, _ = env
        panes = {}

        def it1():
            panes[1] = Pane(tdir, 1)
            return panes[1].verdict("INPUT_REQUIRED", "Option A or B?")

        state = ReviewLoopState(pr_id=PR_ID)
        t, mock, p = _start(state, tdir, {1: it1})
        try:
            _until(lambda: state.input_required, what="INPUT_REQUIRED wait")
            for text in (
                "<system-reminder>\nThe user opened the file a.py.\n"
                "</system-reminder>",
                "<task-notification>\n<task-id>t1</task-id>\n</task-notification>",
                "# /loop tick\ncontinue",
                "[Request interrupted by user]",
            ):
                panes[1].harness(text)
            time.sleep(0.3)
            assert state.input_required, "harness record cleared the wait"
            assert _status(state)[:2] == (
                "waiting", "review INPUT_REQUIRED (iteration 1)")
            assert mock.call_count == 1

            panes[1].user("option A")
            _until(lambda: not state.input_required, what="real answer clears")
            panes[1].verdict("PASS")
            t.join(5)
            assert state.latest_verdict == "PASS"
        finally:
            state.stop_requested = True
            p.stop()


# ---------------------------------------------------------------------------
# Restart / adoption (breadcrumb-restored state)
# ---------------------------------------------------------------------------

def _restored(tdir, iteration, verdicts, input_required=True):
    """State as ``consume_breadcrumb`` rebuilds it.

    ``iteration_attempted`` is what the breadcrumb persists for a loop that
    had already launched the in-flight iteration; without it the restart
    handoff's fabrication guard correctly refuses to adopt the transcript
    (pr-e040aeb), and the resumed loop relaunches instead.
    """
    st = ReviewLoopState(pr_id=PR_ID, iteration=iteration,
                         latest_verdict=verdicts[-1],
                         input_required=input_required,
                         iteration_attempted=True,
                         _transcript_dir=str(tdir))
    for i, v in enumerate(verdicts, start=1):
        st.history.append(ReviewIteration(iteration=i, verdict=v, output=""))
    return st


class TestRestartAdoption:
    def test_restart_during_wait_adopts_pane_without_relaunch(self, env):
        tdir, _ = env
        pane2 = Pane(tdir, 2)
        pane2.verdict("INPUT_REQUIRED", "Which option?")
        panes = {}
        release3 = threading.Event()

        def it3():
            panes[3] = Pane(tdir, 3)
            panes[3].tool("347 passed")
            release3.wait(10)
            return panes[3].verdict("PASS")

        state = _restored(tdir, 2, ["NEEDS_WORK", "INPUT_REQUIRED"])
        t, mock, p = _start(state, tdir, {3: it3})
        try:
            time.sleep(0.2)
            # Still the genuine, unanswered question — visible, not relaunched.
            assert state.input_required and mock.call_count == 0
            assert _status(state)[:2] == ("waiting", "review INPUT_REQUIRED (iteration 2)")

            pane2.user("option B")
            _until(lambda: not state.input_required, what="answer after restart")
            assert _status(state)[0] == "running"
            pane2.verdict("NEEDS_WORK")
            _until(lambda: state.iteration == 3 and 3 in panes, what="iteration 3")
            s, reason, review = _status(state)
            assert (s, reason) == ("running", "review iteration 3 (last NEEDS_WORK)")
            assert review["input_required"] is False
            release3.set()
            t.join(5)
            assert state.latest_verdict == "PASS"
        finally:
            release3.set()
            p.stop()

    def test_adopting_wait_is_not_reported_as_an_answered_follow_up(self):
        """A restored wait whose adopt check has not run is neither live nor
        answered: status must not claim "INPUT_REQUIRED answered"."""
        st = ReviewLoopState(pr_id=PR_ID, iteration=2,
                             latest_verdict="INPUT_REQUIRED",
                             running=True, input_required=False)
        st.history.append(ReviewIteration(iteration=2, verdict="INPUT_REQUIRED",
                                          output=""))
        st._adopting_wait = True
        review = autostart_state.review_progress_input(st)
        assert review["resuming"] is True
        assert review["follow_up"] is False
        state, reason, published = _status(st)
        assert (state, reason) == ("running", "review resuming (iteration 2)")
        # The adopt check is published as its own flag, not only as the
        # reason text: a status reader must not have to parse the string.
        assert published["resuming"] is True
        assert published["follow_up"] is False
        # Once the check is over and the pane adopted, the wait is live.
        st._adopting_wait = False
        review = autostart_state.review_progress_input(st)
        assert review["resuming"] is False
        assert review["follow_up"] is True
        _, _, published = _status(st)
        assert published["resuming"] is False and published["follow_up"] is True

    def test_restart_adopt_check_never_reads_as_follow_up_running(self, env):
        """The sub-second adopt check after a restart must not publish
        "INPUT_REQUIRED answered; follow-up running" — nobody has answered
        the restored question yet."""
        tdir, _ = env
        pane2 = Pane(tdir, 2)
        pane2.verdict("INPUT_REQUIRED", "Which option?")
        state = _restored(tdir, 2, ["NEEDS_WORK", "INPUT_REQUIRED"])
        entered = threading.Event()
        release = threading.Event()
        real = rl._adoptable_wait_transcript

        def slow_adopt(*a, **kw):
            entered.set()
            release.wait(10)
            return real(*a, **kw)

        with patch.object(rl, "_adoptable_wait_transcript", side_effect=slow_adopt):
            t, mock, p = _start(state, tdir, {})
        try:
            assert entered.wait(5), "adopt check never started"
            # The check is parked: sample it like an external status reader.
            for _ in range(20):
                s, reason, review = _status(state)
                assert s == "running"
                assert "follow-up running" not in reason
                assert review["follow_up"] is False
                assert review["input_required"] is False
                time.sleep(0.01)
            assert _status(state)[:2] == (
                "running", "review resuming (iteration 2)")
            release.set()
            _until(lambda: state.input_required, what="adopted wait")
            assert _status(state)[:2] == (
                "waiting", "review INPUT_REQUIRED (iteration 2)")
        finally:
            release.set()
            state.stop_requested = True
            p.stop()

    def test_adopt_decision_never_reads_as_an_answered_follow_up(self, env):
        """The adopted wait is published *before* the resuming flag clears.

        Sampling at the adopt decision's own log line (the widest point of
        the window between the two writes) must already show the live wait:
        clearing the flag first left running + no wait + the recorded
        INPUT_REQUIRED history, i.e. "INPUT_REQUIRED answered; follow-up
        running" for a question nobody has answered yet.
        """
        tdir, _ = env
        pane = Pane(tdir, 1)
        pane.verdict("INPUT_REQUIRED", "Which option?")
        state = _restored(tdir, 1, ["INPUT_REQUIRED"])
        seen = []
        real_info = rl._log.info

        def spy(msg, *args, **kwargs):
            if msg.startswith("review_loop: adopting INPUT_REQUIRED wait"):
                review = autostart_state.review_progress_input(state)
                seen.append((review["input_required"], review["follow_up"],
                             review["resuming"]))
            return real_info(msg, *args, **kwargs)

        with patch.object(rl._log, "info", side_effect=spy):
            t, mock, p = _start(state, tdir, {})
            try:
                _until(lambda: state.input_required, what="adopted wait")
            finally:
                state.stop_requested = True
                p.stop()
        assert seen, "the adopt decision was never logged"
        for ir, follow_up, resuming in seen:
            assert ir is True, "the adopted wait was not published yet"
            assert follow_up is False, (
                "the adopt decision published an answered follow-up")
            assert resuming is False

    def test_adopt_decision_of_an_answered_wait_never_reads_as_waiting(self, env):
        """A wait the human answered before the restart must not be published
        as a live wait at the adopt decision.

        R2: the resumed wait's initial waiting/answered state comes from the
        transcript, not from the recorded INPUT_REQUIRED history.  Assuming
        the wait first and reading the transcript after showed a phantom
        ``waiting / review INPUT_REQUIRED (iteration N)`` for a question
        nobody is waiting on — the false-wait class this PR fixes — for the
        whole (file-I/O) adopt decision.
        """
        tdir, _ = env
        pane = Pane(tdir, 1)
        pane.verdict("INPUT_REQUIRED", "Which option?")
        pane.user("option B")
        pane.tool("working")
        state = _restored(tdir, 1, ["INPUT_REQUIRED"])
        seen = []
        real_info = rl._log.info

        def spy(msg, *args, **kwargs):
            if msg.startswith("review_loop: adopting INPUT_REQUIRED wait"):
                review = autostart_state.review_progress_input(state)
                seen.append((review["input_required"], review["follow_up"],
                             review["resuming"]))
            return real_info(msg, *args, **kwargs)

        with patch.object(rl._log, "info", side_effect=spy):
            t, mock, p = _start(state, tdir, {})
            try:
                # Wait for the adopt decision itself, not a timer: the spy
                # fires at its log line.
                _until(lambda: bool(seen), what="the adopt decision")
                assert mock.call_count == 0
                assert _status(state)[:2] == (
                    "running",
                    "review iteration 1 (INPUT_REQUIRED answered; follow-up running)")
            finally:
                state.stop_requested = True
                p.stop()
        assert seen, "the adopt decision was never logged"
        for ir, follow_up, resuming in seen:
            assert ir is False, (
                "an answered wait was published as a live human request")
            assert follow_up is True
            assert resuming is False

    def test_restart_after_answer_shows_follow_up_running(self, env):
        tdir, _ = env
        pane2 = Pane(tdir, 2)
        pane2.verdict("INPUT_REQUIRED")
        pane2.user("option B")
        pane2.tool("working")
        state = _restored(tdir, 2, ["NEEDS_WORK", "INPUT_REQUIRED"])
        t, mock, p = _start(state, tdir, {})
        try:
            _until(lambda: state.running and not state.input_required,
                   what="restored answered wait to clear")
            time.sleep(0.1)
            assert not state.input_required and mock.call_count == 0
            assert _status(state)[:2] == (
                "running", "review iteration 2 (INPUT_REQUIRED answered; follow-up running)")
            pane2.verdict("PASS")
            t.join(5)
            assert state.latest_verdict == "PASS"
        finally:
            state.stop_requested = True
            p.stop()

    def test_follow_up_verdict_landed_during_restart_gap(self, env):
        """Answer + follow-up verdict both landed while the TUI restarted:
        the idle event predates the resumed waiter but follows the answer."""
        tdir, _ = env
        pane2 = Pane(tdir, 2)
        pane2.verdict("INPUT_REQUIRED")
        pane2.user("option B")
        pane2.verdict("NEEDS_WORK")
        release3 = threading.Event()
        panes = {}

        def it3():
            panes[3] = Pane(tdir, 3)
            release3.wait(10)
            return panes[3].verdict("PASS")

        state = _restored(tdir, 2, ["NEEDS_WORK", "INPUT_REQUIRED"])
        t, mock, p = _start(state, tdir, {3: it3})
        try:
            _until(lambda: 3 in panes, what="iteration 3 after gap verdict")
            assert state.history[1].verdict == "NEEDS_WORK"
            assert state.input_required is False
            release3.set()
            t.join(5)
            assert state.latest_verdict == "PASS"
        finally:
            release3.set()
            state.stop_requested = True
            p.stop()

    def test_follow_up_verdict_resolves_without_a_hook_event(self, env):
        """A verdict already in the transcript must not depend on an idle
        hook event: after a restart the event file may hold another event (or
        none at all) while the follow-up verdict has already landed.  Without
        the pre-wait transcript read the resumed loop blocks forever on an
        idle that will never come."""
        tdir, _ = env
        pane2 = Pane(tdir, 2)
        pane2.verdict("INPUT_REQUIRED")
        pane2.user("option B")
        pane2.say("Fixed it.\n\n**NEEDS_WORK**")  # no idle: the event is gone
        hook_events.event_path(pane2.sid).unlink()
        release3 = threading.Event()
        panes = {}

        def it3():
            panes[3] = Pane(tdir, 3)
            release3.wait(10)
            return panes[3].verdict("PASS")

        state = _restored(tdir, 2, ["NEEDS_WORK", "INPUT_REQUIRED"])
        t, mock, p = _start(state, tdir, {3: it3})
        try:
            _until(lambda: 3 in panes, what="iteration 3 after gap verdict")
            assert state.history[1].verdict == "NEEDS_WORK"
            assert state.input_required is False
            release3.set()
            t.join(5)
            assert state.latest_verdict == "PASS"
        finally:
            release3.set()
            state.stop_requested = True
            p.stop()

    def test_follow_up_verdict_survives_a_local_slash_command(self, env):
        """A local slash-command echo (``/model``, ``/cost``) after the
        verdict is not a task: the follow-up verdict is still read from the
        transcript.

        Pre-fix the echo stopped the task-scoped scan, so the waiter saw no
        verdict, re-armed a wait nobody was asked and (with no further idle
        event) blocked forever — the false-wait class this loop prevents.
        """
        tdir, _ = env
        pane2 = Pane(tdir, 2)
        pane2.verdict("INPUT_REQUIRED")
        pane2.user("option B")
        pane2.say("Fixed it.\n\n**NEEDS_WORK**")  # no idle: the event is gone
        pane2.harness("<command-name>/model</command-name>\n"
                      "<command-message>model</command-message>")
        hook_events.event_path(pane2.sid).unlink()
        release3 = threading.Event()
        panes = {}

        def it3():
            panes[3] = Pane(tdir, 3)
            release3.wait(10)
            return panes[3].verdict("PASS")

        state = _restored(tdir, 2, ["NEEDS_WORK", "INPUT_REQUIRED"])
        t, mock, p = _start(state, tdir, {3: it3})
        try:
            _until(lambda: 3 in panes, what="iteration 3 after the echo")
            assert state.history[1].verdict == "NEEDS_WORK"
            assert state.input_required is False
            release3.set()
            t.join(5)
            assert state.latest_verdict == "PASS"
        finally:
            release3.set()
            state.stop_requested = True
            p.stop()

    def test_restart_with_no_live_pane_clears_wait(self, env):
        """The question's pane is gone: the next iteration owns the work."""
        tdir, pane_alive = env
        pane_alive["alive"] = False
        release = threading.Event()
        panes = {}

        def it3():
            panes[3] = Pane(tdir, 3)
            release.wait(10)
            return panes[3].verdict("PASS")

        state = _restored(tdir, 2, ["NEEDS_WORK", "INPUT_REQUIRED"])
        t, mock, p = _start(state, tdir, {3: it3})
        try:
            _until(lambda: 3 in panes, what="iteration 3 launch")
            assert state.input_required is False
            s, reason, review = _status(state)
            assert s == "running" and reason.startswith("review iteration 3")
            assert review["input_required"] is False and review["follow_up"] is False
            release.set()
            t.join(5)
        finally:
            release.set()
            p.stop()

    def test_restored_wait_is_not_published_before_the_adopt_check(self, env,
                                                                   monkeypatch):
        """The breadcrumb's ``input_required`` flag must not read as a live
        human request while the resume is still deciding whether the wait can
        be adopted.

        QA S9 story 5: a plain restart with a restored iteration-6 wait whose
        pane and transcript were already gone reported
        ``waiting/review review #6 — review INPUT_REQUIRED (iteration 6)``
        from the mount until the loop thread reached its adopt check (~1 s).
        """
        tdir, _ = env
        gate = threading.Event()
        real = rl._adoptable_wait_transcript

        def blocked_adopt(state, pr_data, transcript_dir):
            gate.wait(5)
            return real(state, pr_data, transcript_dir)

        monkeypatch.setattr(rl, "_adoptable_wait_transcript", blocked_adopt)
        release7 = threading.Event()

        def it7():
            release7.wait(10)
            return "**PASS**"

        # Iteration 6 ended INPUT_REQUIRED; no pane/transcript for it.
        state = _restored(tdir, 6, ["NEEDS_WORK"] * 5 + ["INPUT_REQUIRED"])
        assert state.input_required is True
        t, mock, p = _start(state, tdir, {7: it7})
        try:
            _until(lambda: state.running, what="resume started")
            time.sleep(0.2)  # the adopt check is still blocked here
            assert state.input_required is False
            assert _status(state)[0] != "waiting"
            gate.set()
            _until(lambda: state.iteration == 7, what="iteration 7")
            s, reason, review = _status(state)
            assert s == "running" and reason.startswith("review iteration 7")
            assert review["input_required"] is False
        finally:
            gate.set()
            release7.set()
            t.join(5)
            p.stop()

    def test_restart_wait_with_no_recoverable_session_clears(self, env):
        """The pane is alive but its transcript yields no session_id, so there
        is no hook stream to wait on: nobody can answer.  Clear the wait and
        launch the next iteration instead of failing it and ending KILLED."""
        tdir, _ = env
        release = threading.Event()
        panes = {}

        def it3():
            panes[3] = Pane(tdir, 3)
            release.wait(10)
            return panes[3].verdict("PASS")

        # A plain file, not a symlink to a <session-id>.jsonl: the wait's
        # session_id recovery fails while lexists()/pane lookups succeed.
        (tdir / f"review-{PR_ID}-i2.jsonl").write_text("")
        state = _restored(tdir, 2, ["NEEDS_WORK", "INPUT_REQUIRED"])
        t, mock, p = _start(state, tdir, {3: it3})
        try:
            _until(lambda: 3 in panes, what="iteration 3 launch")
            assert state.input_required is False
            s, reason, review = _status(state)
            assert s == "running" and reason.startswith("review iteration 3")
            assert review["input_required"] is False
            release.set()
            t.join(5)
        finally:
            release.set()
            p.stop()

    def test_stale_restored_flag_cleared_on_next_iteration(self, env):
        """An old breadcrumb latched input_required with a finished history."""
        tdir, _ = env
        release = threading.Event()

        def it3():
            Pane(tdir, 3)
            release.wait(10)
            return "**PASS**"

        state = _restored(tdir, 2, ["NEEDS_WORK", "NEEDS_WORK"], input_required=True)
        t, mock, p = _start(state, tdir, {3: it3})
        try:
            _until(lambda: mock.call_count == 1, what="iteration 3 launch")
            assert state.input_required is False
            assert _status(state)[0] == "running"
            release.set()
            t.join(5)
        finally:
            release.set()
            p.stop()

    def test_adopted_in_flight_input_required_waits_on_saved_transcript(self, env):
        """An iteration in flight at the restart ends INPUT_REQUIRED: the
        follow-up wait reads the transcript it was launched under, even
        when the resumed loop got a new transcript dir (manual loops)."""
        tdir, _ = env
        old_dir = tdir / "manual-old"
        old_dir.mkdir()
        new_dir = tdir / "manual-new"
        new_dir.mkdir()
        pane3 = Pane(old_dir, 3)
        pane3.verdict("INPUT_REQUIRED", "Which option?")
        release4 = threading.Event()
        panes = {}

        def it4():
            panes[4] = Pane(new_dir, 4)
            release4.wait(10)
            return panes[4].verdict("PASS")

        # Counter bumped to 3, no history entry yet: iteration 3 in flight.
        state = _restored(old_dir, 3, ["NEEDS_WORK", "NEEDS_WORK"],
                          input_required=False)
        t, mock, p = _start(state, new_dir, {4: it4})
        try:
            _until(lambda: state.input_required, what="adopted question waiting")
            assert mock.call_count == 0 and state.running
            assert _status(state)[:2] == ("waiting", "review INPUT_REQUIRED (iteration 3)")
            pane3.user("option B")
            _until(lambda: not state.input_required, what="answer on adopted pane")
            pane3.verdict("NEEDS_WORK")
            _until(lambda: 4 in panes, what="iteration 4 launch")
            assert state.history[2].verdict == "NEEDS_WORK"
            assert mock.call_args.kwargs["transcript"].startswith(str(new_dir))
            release4.set()
            t.join(5)
            assert state.latest_verdict == "PASS"
        finally:
            release4.set()
            state.stop_requested = True
            p.stop()

