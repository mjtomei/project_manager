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


@pytest.fixture
def env(tmp_path, monkeypatch):
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    monkeypatch.setattr(hook_events, "_HOOKS_BASE", hooks)
    monkeypatch.setattr(rl, "_FOLLOW_UP_POLL", 0.05, raising=False)
    monkeypatch.setattr(rl, "_get_pm_session", lambda: "pm-test")
    pane_alive = {"alive": True}
    find_pane = lambda s, w: "%1" if pane_alive["alive"] else None  # noqa: E731
    monkeypatch.setattr(rl, "_find_claude_pane", find_pane)
    monkeypatch.setattr(loop_shared, "find_claude_pane", find_pane)
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


def _start(state, tdir, launches):
    """Run the loop in a thread; ``launches`` maps iteration → callable
    returning the review output (it may block to keep the iteration live)."""
    def fake_review(pr_id, pm_root, pr_data, transcript, iteration=0, loop_id=""):
        return launches[iteration]()
    p = patch.object(rl, "_run_claude_review", side_effect=fake_review)
    mock = p.start()
    t = threading.Thread(target=run_review_loop_sync,
                         args=(state, "/tmp", PR, str(tdir)), daemon=True)
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


# ---------------------------------------------------------------------------
# Restart / adoption (breadcrumb-restored state)
# ---------------------------------------------------------------------------

def _restored(tdir, iteration, verdicts, input_required=True):
    """State as ``consume_breadcrumb`` rebuilds it."""
    st = ReviewLoopState(pr_id=PR_ID, iteration=iteration,
                         latest_verdict=verdicts[-1],
                         input_required=input_required,
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
