"""TUI auto-sequence: QA PASS -> sign_off -> recorded approval -> O stops / A merges.

pr-488ac6d: ``qa_loop_ui._on_qa_complete`` used to call ``_maybe_auto_merge``
directly on a QA PASS, which logged "ready to merge" for O (registry still
``qa``, ``signoff=None``) or ran ``pm pr merge`` for A — refused by the #226
sign-off gate and then mis-tracked as a merge conflict.  These tests drive a
real project.yaml through the TUI callbacks with only the process / tmux
edges faked (``pr_view.run_command`` — the sign-off launcher is routed
through it as a command string — the sign-off window lookup, HEAD).
"""

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from pm_core import store
from pm_core import autostart_state as st
from pm_core.qa_loop import QALoopState, VERDICT_PASS
from pm_core.tui import auto_start, qa_loop_ui, review_loop_ui

PR = "pr-aaa1111"


class App:
    """Plain stand-in for the TUI app (real attributes, real project.yaml)."""

    def __init__(self, root: Path, *, stop: bool, skip_qa: bool = False,
                 status: str = "qa", targets=(PR,)):
        self._root = root
        data = {
            "project": {"name": "t", "repo": "/r", "base_branch": "master",
                        "backend": "local"},
            "prs": [{"id": PR, "title": "T", "branch": "pm/x",
                     "status": status, "workdir": str(root / "wd"),
                     "depends_on": [], "notes": []},
                    {"id": "pr-out", "title": "O", "branch": "pm/o",
                     "status": "sign_off", "workdir": str(root / "wd"),
                     "depends_on": [], "notes": []}],
        }
        if skip_qa:
            data["project"]["skip_qa"] = True
        store.save(data, root)
        self._data = store.load(root)
        self._auto_start = True
        self._auto_start_targets = {t: st.make_target_record("test")
                                    for t in targets}
        self._auto_start_all = False
        self._auto_start_run_id = "run"
        self._auto_start_launching = set()
        self._stop_before_merge = {PR} if stop else set()
        self._review_loops = {}
        self._qa_loops = {}
        self._self_driving_qa = {}
        self._pending_merge_prs = set()
        self._merge_input_required_prs = set()
        self._merge_propagation_phase = set()
        self._session_name = "pm-test"
        self.logs: list[str] = []
        self.workers: list = []

    def log_message(self, msg, **kw):
        self.logs.append(msg)

    def run_worker(self, coro):
        self.workers.append(coro)
        if asyncio.iscoroutine(coro):
            coro.close()

    def _load_state(self):
        self._data = store.load(self._root)

    # helpers
    def pr(self, pr_id=PR):
        return store.get_pr(store.load(self._root), pr_id)


class World:
    """Faked process/tmux edges, with a ``pm pr merge`` that enforces the
    real sign-off gate against the on-disk record."""

    def __init__(self, app: App):
        self.app = app
        self.head = "c0ffee" * 6 + "abcd"
        self.window = False
        self.commands: list[str] = []
        self.tdir = app._root / "transcripts" / "run"

    def run_command(self, app, cmd, *a, **kw):
        self.commands.append(cmd)
        if cmd.startswith("pr signoff"):
            self.window = True
        elif cmd.startswith("pr merge"):
            from pm_core import signoff as so
            pr = self.app.pr()
            if so.merge_gate_refusal(pr, self.head):
                return  # gate refuses (exit 1); status unchanged

            def apply(d):
                store.get_pr(d, PR)["status"] = "merged"
            store.locked_update(self.app._root, apply)

    def launch_quiet(self, app, pr_id, transcript):
        """Stand-in for ``signoff_ui._launch_quiet`` (a worker coroutine in
        the TUI): records the command via the patchable ``run_command``."""
        from pm_core.tui import pr_view
        pr_view.run_command(
            app, f"pr signoff --background --transcript {transcript} {pr_id}")

    def emit(self, verdict: str) -> None:
        """The router pane prints its verdict into the TUI's transcript."""
        self.tdir.mkdir(parents=True, exist_ok=True)
        lines = [
            {"type": "user", "message": {"content": "go"}},
            {"type": "assistant", "message": {"content": [
                {"type": "text", "text": f"Report written.\n\n{verdict}"}]}},
        ]
        (self.tdir / f"signoff-{PR}.jsonl").write_text(
            "\n".join(json.dumps(x) for x in lines) + "\n")

    def merges(self):
        return [c for c in self.commands if c.startswith("pr merge")]

    def launches(self):
        return [c for c in self.commands if c.startswith("pr signoff")]


@pytest.fixture
def world_factory(tmp_path):
    patches = []

    def make(**kw):
        app = App(tmp_path, **kw)
        w = World(app)
        ps = [
            patch("pm_core.tui.pr_view.run_command", w.run_command),
            patch("pm_core.tui.signoff_ui._launch_quiet", w.launch_quiet),
            patch("pm_core.signoff.head_sha", lambda wd: w.head),
            patch("pm_core.signoff.signoff_window_pane",
                  lambda s, pr: "%9" if w.window else None, create=True),
            patch("pm_core.tmux.find_window_by_name",
                  lambda s, n: ({"id": "@9", "index": 9, "name": n}
                                if w.window and n.startswith("signoff-")
                                else None)),
            patch("pm_core.tmux.kill_window",
                  lambda s, wid: setattr(w, "window", False)),
            patch("pm_core.home_window.park_if_on", lambda *a: None),
            patch("pm_core.tui.qa_loop_ui._record_qa_note"),
            patch("pm_core.tui.auto_start.recorded_qa_verdict",
                  lambda pr_id: None),
        ]
        for p in ps:
            p.start()
            patches.append(p)
        return app, w

    yield make
    for p in reversed(patches):
        p.stop()


def _qa_pass(app):
    state = QALoopState(pr_id=PR)
    state.latest_verdict = VERDICT_PASS
    qa_loop_ui._on_qa_complete(app, state)


def _poll(app, n=1):
    from pm_core.tui import signoff_ui
    for _ in range(n):
        signoff_ui.advance_all(app)


@pytest.mark.parametrize("stop", [True, False], ids=["O", "A"])
def test_qa_pass_hands_off_to_signoff_not_merge(world_factory, stop):
    app, w = world_factory(stop=stop)
    _qa_pass(app)

    pr = app.pr()
    assert pr["status"] == "sign_off"
    assert pr.get("signoff") is None
    # Router launched in the background with the TUI transcript.
    assert w.launches() == [
        f"pr signoff --background --transcript "
        f"{w.tdir / f'signoff-{PR}.jsonl'} {PR}"]
    assert w.merges() == []
    assert not any("ready to merge" in m for m in app.logs)
    assert any("handing off to sign-off" in m for m in app.logs)
    assert app._pending_merge_prs == set()

    # Router still working: polls do nothing.
    _poll(app, 3)
    assert len(w.launches()) == 1 and w.merges() == []


def test_O_stops_only_after_fresh_signoff_merge(world_factory):
    app, w = world_factory(stop=True)
    _qa_pass(app)
    w.emit("SIGNOFF_MERGE")
    _poll(app)

    rec = app.pr()["signoff"]
    assert rec["verdict"] == "SIGNOFF_MERGE"
    assert rec["sha"] == w.head            # recorded against current HEAD
    assert rec["origin"] == "auto-sequence"
    assert app.pr()["status"] == "sign_off"
    assert w.merges() == []                # O never merges
    ready = [m for m in app.logs if "ready to merge" in m]
    assert len(ready) == 1 and "signed off" in ready[0]

    _poll(app, 3)                          # no repeat of the ready line
    assert len([m for m in app.logs if "ready to merge" in m]) == 1

    # Policy flip O -> A on the signed-off PR: now it merges.
    app._stop_before_merge.clear()
    _poll(app)
    assert len(w.merges()) == 1
    assert app.pr()["status"] == "merged"


def test_A_merges_only_after_recorded_current_head_approval(world_factory):
    app, w = world_factory(stop=False)
    _qa_pass(app)
    _poll(app, 2)
    assert w.merges() == []                # no approval yet -> no merge

    w.emit("SIGNOFF_MERGE")
    _poll(app)
    assert len(w.merges()) == 1
    assert app.pr()["status"] == "merged"  # the real gate let it through
    assert app._pending_merge_prs == set()


def test_head_moved_after_approval_reruns_signoff(world_factory):
    app, w = world_factory(stop=True)
    _qa_pass(app)
    w.emit("SIGNOFF_MERGE")
    _poll(app)
    assert app.pr()["signoff"]["sha"] == w.head

    w.head = "f" * 40                      # new commit on the branch
    _poll(app)
    assert app.pr().get("signoff") is None  # stale record cleared
    assert not (w.tdir / f"signoff-{PR}.jsonl").exists()  # transcript retired
    assert len(w.launches()) == 2           # fresh router against new HEAD
    assert w.merges() == []


def test_gate_refusal_is_not_tracked_as_conflict(world_factory):
    """A merge refused by the sign-off gate must not land in
    _pending_merge_prs (it was the #226 misclassification)."""
    app, w = world_factory(stop=False)
    _qa_pass(app)
    w.emit("SIGNOFF_MERGE")

    real_run = w.run_command

    def move_head_then_merge(a, cmd, *x, **kw):
        if cmd.startswith("pr merge"):
            w.head = "e" * 40              # HEAD moves under the merge
        real_run(a, cmd, *x, **kw)

    w.run_command = move_head_then_merge
    with patch("pm_core.tui.pr_view.run_command", move_head_then_merge):
        _poll(app)
    assert app.pr()["status"] == "sign_off"
    assert app._pending_merge_prs == set()
    assert any("refused by the sign-off gate" in m for m in app.logs)


def test_reqa_route_restarts_tui_qa(world_factory):
    app, w = world_factory(stop=True)
    _qa_pass(app)
    w.emit("SIGNOFF_REQA")
    with patch("pm_core.tui.qa_loop_ui.start_qa") as sq, \
         patch("pm_core.runtime_state.set_action_state") as rs:
        _poll(app)
    assert app.pr()["status"] == "qa"
    assert app.pr().get("signoff") is None
    sq.assert_called_once_with(app, PR)
    rs.assert_any_call(PR, "qa", None)     # stale PASS record dropped
    assert not w.window                    # router window retired
    assert w.merges() == []


def test_review_route_restarts_review_loop(world_factory):
    app, w = world_factory(stop=True)
    _qa_pass(app)
    app._review_loops[PR] = object()       # stale finished loop
    w.emit("SIGNOFF_REVIEW")
    with patch("pm_core.tui.review_loop_ui._start_loop") as sl:
        _poll(app)
    assert app.pr()["status"] == "in_review"
    sl.assert_called_once()
    assert sl.call_args.args[1] == PR
    assert sl.call_args.kwargs["transcript_dir"] == str(w.tdir)
    assert w.merges() == []


def test_impl_route_relaunches_impl_fresh(world_factory):
    app, w = world_factory(stop=True)
    _qa_pass(app)
    w.emit("SIGNOFF_IMPL")
    calls = []

    async def fake_start(_app, pr_id, fresh=False):
        calls.append((pr_id, fresh))

    def run_worker(coro):
        asyncio.run(coro)

    app.run_worker = run_worker
    with patch.object(auto_start, "_start_pr_quiet", fake_start):
        _poll(app)
    assert app.pr()["status"] == "in_progress"
    assert calls == [(PR, True)]
    assert w.merges() == []


def test_blocked_route_waits_for_human(world_factory):
    app, w = world_factory(stop=False)
    _qa_pass(app)
    w.emit("SIGNOFF_BLOCKED")
    _poll(app, 3)
    assert app.pr()["status"] == "sign_off"
    assert app.pr()["signoff"]["verdict"] == "SIGNOFF_BLOCKED"
    assert w.merges() == []
    assert len([m for m in app.logs if "BLOCKED" in m]) == 1


def test_out_of_scope_signoff_pr_untouched(world_factory):
    app, w = world_factory(stop=False)
    _poll(app, 2)   # pr-out is sign_off but not in any target closure
    assert app.pr("pr-out")["status"] == "sign_off"
    assert not any(PR not in c and "pr-out" in c for c in w.commands)


def test_manual_qa_pass_without_autostart_no_handoff(world_factory):
    app, w = world_factory(stop=True)
    app._auto_start = False
    app._auto_start_targets = {}
    _qa_pass(app)
    assert app.pr()["status"] == "qa"
    assert w.commands == []
    assert any("press i to sign off" in m for m in app.logs)


def test_restart_catch_up_hands_off_recorded_pass(world_factory):
    """QA finished PASS before a restart: no _qa_loops entry, recorded PASS
    in runtime_state -> the scheduler pass hands it to sign-off."""
    app, w = world_factory(stop=True)
    with patch("pm_core.tui.auto_start.recorded_qa_verdict",
               lambda pr_id: "PASS"), \
         patch.object(auto_start, "_start_pr_quiet"):
        asyncio.run(auto_start.check_and_start(app))
    assert app.pr()["status"] == "sign_off"
    assert len(w.launches()) == 1


def test_skip_qa_review_pass_goes_to_signoff(world_factory):
    app, w = world_factory(stop=True, skip_qa=True, status="in_review")
    with patch("pm_core.tui.qa_loop_ui.start_qa") as sq:
        review_loop_ui._maybe_start_qa(app, PR)
    sq.assert_not_called()
    assert app.pr()["status"] == "sign_off"
    assert len(w.launches()) == 1
    assert w.merges() == []
    assert not any("ready to merge" in m for m in app.logs)


def test_adopts_existing_fresh_manual_approval(world_factory):
    """A reviewer-recorded approval at current HEAD is adopted without
    launching another router."""
    app, w = world_factory(stop=True)
    from pm_core import signoff as so
    so.record_signoff_verdict(app._root, PR, "SIGNOFF_MERGE", w.head, "manual")
    _qa_pass(app)
    assert w.launches() == []
    assert any("ready to merge" in m for m in app.logs)
    assert w.merges() == []


def test_dead_window_relaunch_is_throttled(world_factory):
    """A launch that never produces a window is not retried every poll."""
    app, w = world_factory(stop=True)

    def no_window(a, cmd, *x, **kw):
        w.commands.append(cmd)     # launch "fails": window never appears

    with patch("pm_core.tui.pr_view.run_command", no_window):
        _qa_pass(app)
        _poll(app, 4)
    assert len(w.launches()) == 1
    # After the backoff the dead window is relaunched.
    for k in list(app._signoff_launched_at):
        app._signoff_launched_at[k] -= signoff_backoff()
    with patch("pm_core.tui.pr_view.run_command", no_window):
        _poll(app)
    assert len(w.launches()) == 2


def signoff_backoff():
    from pm_core.tui import signoff_ui
    return signoff_ui.RELAUNCH_BACKOFF_SECONDS


def test_manual_approval_with_changed_report_is_not_merged(world_factory,
                                                           tmp_path):
    """A manual approval pins report.html's hash; once the report changes the
    real gate refuses, so A must not call ``pm pr merge`` (which would be
    tracked as a conflict) and says why instead."""
    import hashlib
    app, w = world_factory(stop=False)
    croot = tmp_path / "captures"
    (croot / PR).mkdir(parents=True)
    report = croot / PR / "report.html"
    report.write_text("<html>v1</html>")
    from pm_core import signoff as so
    so.record_signoff_verdict(
        app._root, PR, "SIGNOFF_MERGE", w.head, "manual",
        report_hash=hashlib.sha256(report.read_bytes()).hexdigest())
    report.write_text("<html>v2 edited</html>")
    with patch("pm_core.paths.captures_root", return_value=croot):
        _qa_pass(app)
        _poll(app, 3)
    assert w.merges() == []
    assert app._pending_merge_prs == set()
    refused = [m for m in app.logs if "report.html changed" in m]
    assert len(refused) == 1                # once, not every poll


def test_launch_quiet_runs_signoff_off_the_event_loop(tmp_path):
    """The real launcher: argv list (no shlex of the transcript path), async
    subprocess, failure surfaced in the log."""
    from pm_core.tui import signoff_ui
    app = App(tmp_path, stop=True)
    seen = {}

    class Proc:
        returncode = 1

        async def communicate(self):
            return b"", b"boom\nPR pr-aaa1111 is merged"

    async def fake_shell(cmd, **kw):
        seen["cmd"] = cmd
        return Proc()

    transcript = tmp_path / "a dir" / f"signoff-{PR}.jsonl"
    with patch("pm_core.tui._shell._run_shell_async", fake_shell):
        asyncio.run(signoff_ui._launch_quiet(app, PR, transcript))
    assert seen["cmd"][-5:] == ["signoff", "--background", "--transcript",
                                str(transcript), PR]
    assert any("Sign-off launch failed" in m and "is merged" in m
               for m in app.logs)
