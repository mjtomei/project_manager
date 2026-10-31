"""Versioned TUI pidfile: capability gating, identity checks, takeover.

Covers pr-c3bf868: a stale pidfile used to let picker / reload IPC signal a
dead, recycled, or handler-less process.  The pidfile now carries
capabilities and a process start time; callers validate both before
signaling, and the TUI claims the file exclusively at startup.
"""

import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from pm_core import tui_pidfile as tpf
from pm_core.cli import helpers
from pm_core.cli import session as sess_mod
from pm_core.tui.app import ProjectManagerApp

SESSION = "pm-test"
DEAD_PID = 2 ** 30 - 1  # far above /proc/sys/kernel/pid_max

# A stand-in TUI: argv is ``<interpreter> …/bin/pm _tui`` so the cmdline
# marker matches, and handlers are opt-in to model an older TUI.
FAKE_TUI_SRC = '''#!/usr/bin/env python3
import os, signal, time
marker = os.environ.get("FAKE_TUI_MARKER", "")

def _note(name):
    def _h(*_a):
        if marker:
            with open(marker, "a") as f:
                f.write(name + "\\n")
    return _h

if os.environ.get("FAKE_TUI_USR1", "1") == "1":
    signal.signal(signal.SIGUSR1, _note("sigusr1"))
if os.environ.get("FAKE_TUI_USR2", "1") == "1":
    signal.signal(signal.SIGUSR2, _note("sigusr2"))
print("ready", flush=True)
while True:
    time.sleep(0.2)
'''


@pytest.fixture
def ipc_paths(tmp_path, monkeypatch):
    """Redirect the helpers' pidfile/queue paths into tmp_path."""
    pidfile = tmp_path / "tui-pm-test.pid"
    queue = tmp_path / "tui-pm-test.cmd-queue"
    monkeypatch.setattr(helpers, "_tui_pidfile_for_session",
                        lambda session: pidfile)
    monkeypatch.setattr(helpers, "_tui_command_queue_for_session",
                        lambda session: queue)
    return pidfile, queue


@pytest.fixture
def procs():
    started = []
    yield started
    for proc in started:
        try:
            proc.kill()
            proc.wait(timeout=5)
        except Exception:
            pass


@pytest.fixture
def start_fake_tui(tmp_path, procs):
    """Spawn a live stand-in TUI and return its Popen."""

    def _start(usr1=True, usr2=True, marker=None):
        bindir = tmp_path / "fakebin"
        bindir.mkdir(exist_ok=True)
        script = bindir / "pm"
        if not script.exists():
            script.write_text(FAKE_TUI_SRC)
            script.chmod(0o755)
        env = dict(os.environ)
        env["FAKE_TUI_USR1"] = "1" if usr1 else "0"
        env["FAKE_TUI_USR2"] = "1" if usr2 else "0"
        if marker is not None:
            env["FAKE_TUI_MARKER"] = str(marker)
        proc = subprocess.Popen([str(script), "_tui"],
                                stdout=subprocess.PIPE, text=True, env=env)
        procs.append(proc)
        assert proc.stdout.readline().strip() == "ready"
        return proc

    return _start


def _write_legacy(path, pid):
    path.write_text(str(pid))


def _write_json(path, pid, caps, starttime="live", session=SESSION):
    if starttime == "live":
        starttime = tpf.proc_starttime(pid)
    path.write_text(json.dumps({
        "version": 1, "pid": pid, "session": session,
        "started_at": "2026-10-27T00:00:00+00:00",
        "starttime": starttime, "caps": list(caps),
    }))


def _marker_lines(path):
    if not path.exists():
        return []
    return path.read_text().split()


def _wait_for(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def _failing_append_open(real_open, *, concurrent=None):
    """An ``open`` stand-in whose ``ab`` writes 5 bytes then fails.

    Models a full disk (ENOSPC), which the kernel is allowed to do as a
    *short* write.  *concurrent*, when given, is a line another caller
    appends to the queue after our handle is opened but before we take
    the queue lock — the interleaving that makes a stream position
    captured at open time stale.
    """

    class _ShortWrite:
        """Writes a prefix of the line, then fails like a full disk."""

        def __init__(self, real):
            self._real = real

        def write(self, data):
            self._real.write(data[:5])
            self._real.flush()
            raise OSError(28, "No space left on device")

        def __getattr__(self, name):  # truncate/flush/fileno/tell/close
            return getattr(self._real, name)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self._real.close()
            return False

    def fake_open(path, mode="r", *args, **kwargs):
        f = real_open(path, mode, *args, **kwargs)
        if mode != "ab":
            return f
        if concurrent is not None:
            with real_open(path, "ab") as other:
                other.write(concurrent)
        return _ShortWrite(f)

    return fake_open


def _flush_failing_append_open(real_open, *, short=5):
    """An ``open`` stand-in that fails at the *raw* layer, after bytes land.

    ``_failing_append_open`` raises out of ``write`` before any byte
    reaches Python's buffer, so it never exercises a buffered writer's
    flush — the path a full disk actually takes.  Here the kernel accepts
    ``short`` bytes and then reports ENOSPC forever, and ``buffering`` is
    honoured the way the builtin does, so the same fake models both the
    old buffered append and the unbuffered one.  With a buffered writer
    the failure surfaces from ``flush``/``close`` and the writer *keeps*
    the unwritten remainder, which makes a ``truncate`` rollback re-raise
    from its own flush instead of cutting the partial line off.
    """
    import io

    class _RawShort:
        def __init__(self, real):
            self._real = real
            self._accepting = True

        def write(self, data):
            if self._accepting:
                self._accepting = False
                return self._real.write(bytes(data[:short]))
            raise OSError(28, "No space left on device")

        def __getattr__(self, name):
            return getattr(self._real, name)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self._real.close()
            return False

    def fake_open(path, mode="r", *args, **kwargs):
        if mode != "ab":
            return real_open(path, mode, *args, **kwargs)
        raw = _RawShort(real_open(path, "ab", buffering=0))
        if kwargs.get("buffering", -1) == 0:
            return raw
        return io.BufferedWriter(raw, 8192)

    return fake_open


def _short_then_ok_append_open(real_open, *, short=5):
    """An ``open`` stand-in whose first raw write is short, then succeeds.

    A raw write is allowed to return fewer bytes than asked; the append
    must finish the line rather than report a failure that would leave
    the command unqueued (and, worse, half-written).
    """
    import io

    class _RawShortThenOk:
        def __init__(self, real):
            self._real = real
            self._calls = 0

        def write(self, data):
            self._calls += 1
            if self._calls == 1:
                return self._real.write(bytes(data[:short]))
            return self._real.write(bytes(data))

        def __getattr__(self, name):
            return getattr(self._real, name)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self._real.close()
            return False

    def fake_open(path, mode="r", *args, **kwargs):
        if mode != "ab":
            return real_open(path, mode, *args, **kwargs)
        raw = _RawShortThenOk(real_open(path, "ab", buffering=0))
        if kwargs.get("buffering", -1) == 0:
            return raw
        return io.BufferedWriter(raw, 8192)

    return fake_open


# ---------------------------------------------------------------------------
# Parsing


class TestParsePidfile:
    def test_legacy_number_infers_sigusr1_only(self):
        desc = tpf.parse_pidfile("1234\n")
        assert desc.pid == 1234
        assert desc.legacy is True
        assert desc.caps == {tpf.CAP_RELOAD}
        assert desc.starttime is None

    def test_json_descriptor(self):
        desc = tpf.parse_pidfile(json.dumps({
            "version": 1, "pid": 42, "started_at": "x",
            "starttime": 99, "caps": ["sigusr1", "sigusr2"],
            "session": "pm-x",
        }))
        assert desc.pid == 42
        assert desc.legacy is False
        assert desc.starttime == 99
        assert desc.caps == {tpf.CAP_RELOAD, tpf.CAP_COMMAND}
        assert desc.session == "pm-x"

    @pytest.mark.parametrize("text", ["", "  \n", "not-a-pid", "{}",
                                      '{"pid": "x"}', '{"pid": 0}',
                                      "[1,2,3]", '{"pid": -5}',
                                      # bool/float/null must not coerce to a
                                      # live PID via int().
                                      '{"pid": true}', '{"pid": 1.5}',
                                      '{"pid": null}', '{"pid": "1.5"}',
                                      # Corrupt values that must be reported
                                      # as unreadable rather than raising
                                      # (E3): a superscript digit is
                                      # str.isdigit() but not int()-parseable,
                                      # and a PID outside pid_t range would
                                      # raise OverflowError at os.kill time.
                                      '{"pid": "²"}', '{"pid": "²³"}',
                                      '{"pid": 2147483648}',
                                      '{"pid": "100000000000000000000"}',
                                      "2147483648",
                                      "100000000000000000000"])
    def test_corrupt_is_none(self, text):
        assert tpf.parse_pidfile(text) is None

    def test_non_decimal_starttime_is_ignored(self):
        """A corrupt starttime drops to None; it must not raise."""
        desc = tpf.parse_pidfile('{"pid": 42, "starttime": "²"}')
        assert desc is not None and desc.pid == 42
        assert desc.starttime is None

    def test_string_pid_is_accepted(self):
        assert tpf.parse_pidfile('{"pid": "42"}').pid == 42

    def test_missing_file_is_none(self, tmp_path):
        assert tpf.read_pidfile(tmp_path / "nope.pid") is None

    def test_undecodable_bytes_are_none(self, tmp_path):
        """A half-written/binary pidfile must not raise."""
        path = tmp_path / "tui-pm-test.pid"
        path.write_bytes(b"\xff\xfe\x00garbage")
        assert tpf.read_pidfile_text(path) is None
        assert tpf.read_pidfile(path) is None


class TestCmdline:
    @pytest.mark.parametrize("argv", [
        ["/usr/bin/python3", "/home/u/.local/bin/pm", "_tui"],
        ["/home/u/.local/share/pm/venv/bin/pm", "_tui"],
        ["python3", "-m", "pm_core.wrapper", "_tui"],
        ["python3", "-m", "pm_core", "_tui"],
        ["python3", "-m", "pm_core.cli", "_tui"],
        # Any pm_core module counts, so a future entry-point rename
        # (the planned wrapper.py -> bootstrap.py) cannot make callers
        # treat a live TUI as a foreign process.
        ["python3", "-m", "pm_core.bootstrap", "_tui"],
    ])
    def test_accepts_pm_tui_shapes(self, argv):
        assert tpf.cmdline_is_tui(argv)

    @pytest.mark.parametrize("argv", [
        ["sleep", "300"],
        ["/usr/bin/python3", "-c", "import time; time.sleep(9)", "_tui"],
        ["pm", "pr", "list"],
        ["claude", "--prompt", "run pm _tui please"],
        ["python3", "-m", "pm_core.wrapper", "pr", "list"],
        # Not a pm_core module: the module match is not a prefix free-for-all.
        ["python3", "-m", "pm_core_other", "_tui"],
    ])
    def test_rejects_other_processes(self, argv):
        assert not tpf.cmdline_is_tui(argv)


def _empty_cmdline_for(monkeypatch, pid):
    """Make ``/proc/<pid>/cmdline`` read as empty, as a kernel thread's does.

    Only that one file is faked, so the real :func:`tpf.proc_cmdline` and
    :func:`tpf.identity_problem` run; a kernel thread has ``mm == NULL``,
    so the kernel serves a zero-length cmdline for it.
    """
    real = tpf.Path
    target = f"/proc/{pid}/cmdline"

    class _Path:
        def __init__(self, raw):
            self._inner = real(raw)

        def read_bytes(self):
            if str(self._inner) == target:
                return b""
            return self._inner.read_bytes()

        def read_text(self, *args, **kwargs):
            return self._inner.read_text(*args, **kwargs)

        def __getattr__(self, name):
            return getattr(self._inner, name)

    monkeypatch.setattr(tpf, "Path", _Path)


class TestEmptyCmdline:
    """An empty argv is a *known* non-TUI, not "cannot tell".

    Kernel threads (and zombies) have an empty ``/proc/<pid>/cmdline``.
    Reporting that as ``None`` ("unknown") made ``identity_problem`` skip
    the cmdline check, so a stale pidfile whose recycled PID happened to
    name such a process looked like a live TUI: ``pm _tui`` refused to
    start — the failure this module exists to prevent — and callers would
    have signaled it.
    """

    @pytest.mark.skipif(not Path("/proc/self/cmdline").exists(),
                        reason="needs procfs")
    def test_empty_cmdline_reads_as_an_empty_argv(self):
        pid = os.fork()
        if pid == 0:  # pragma: no cover - the child exits immediately
            os._exit(0)
        try:
            # A not-yet-reaped child is a zombie, whose cmdline is empty.
            assert _wait_for(lambda: tpf.is_zombie(pid))
            assert tpf.proc_cmdline(pid) == []
        finally:
            os.waitpid(pid, 0)

    def test_identity_problem_rejects_an_empty_argv(self, monkeypatch):
        _empty_cmdline_for(monkeypatch, os.getpid())
        desc = tpf.TuiPidfile(pid=os.getpid(),
                              caps=frozenset({tpf.CAP_RELOAD}))
        assert (tpf.identity_problem(desc)
                == "pid belongs to a different program")

    def test_claim_takes_over_a_pidfile_naming_an_empty_argv_process(
            self, tmp_path, procs, monkeypatch):
        other = subprocess.Popen(["sleep", "300"])
        procs.append(other)
        path = tmp_path / "tui-pm-test.pid"
        _write_legacy(path, other.pid)
        _empty_cmdline_for(monkeypatch, other.pid)

        claim = tpf.claim_tui_pidfile(path, SESSION)
        try:
            assert tpf.read_pidfile(path).pid == os.getpid()
        finally:
            claim.release()
        assert other.poll() is None

    def test_submit_reports_stale_and_removes_the_pidfile(
            self, ipc_paths, procs, monkeypatch):
        other = subprocess.Popen(["sleep", "300"])
        procs.append(other)
        pidfile, queue = ipc_paths
        # The starttime matches, so only the cmdline check can catch it —
        # without the fix this signals SIGUSR2 to the unrelated process.
        _write_json(pidfile, other.pid, [tpf.CAP_RELOAD, tpf.CAP_COMMAND])
        _empty_cmdline_for(monkeypatch, other.pid)

        result = helpers.submit_tui_command(SESSION, "pr list")

        assert not result.ok and result.reason == "stale_pidfile"
        assert not pidfile.exists()
        assert not queue.exists()
        assert other.poll() is None


class TestExecWindow:
    """A re-exec'ing TUI keeps its PID but briefly has an empty argv.

    ``execve`` serves a zero-length ``/proc/<pid>/cmdline`` for the few
    hundred microseconds before the new argv is installed (measured
    0.2-3.6 ms).  ``restart_app`` re-execs the TUI *in place*, so a caller
    that validated the pidfile during a Ctrl+R restart would otherwise
    classify the live TUI as "a different program": it would delete the
    pidfile and report "restart the TUI", and the startup claim would let
    a second TUI take the session over while the restarting one is still
    coming up (that one then refuses to start and its pane dies).  An
    empty read is therefore re-polled briefly before it is believed.
    """

    @staticmethod
    def _empty_once_then(real):
        """A ``proc_cmdline`` stand-in: empty on the first read, then *real*."""
        reads = []

        def fake(pid):
            reads.append(pid)
            if len(reads) == 1:
                return []  # inside execve: the new argv is not installed yet
            return real(pid)

        return fake, reads

    def test_identity_problem_survives_the_exec_window(self, monkeypatch):
        fake, reads = self._empty_once_then(tpf.proc_cmdline)
        monkeypatch.setattr(tpf, "proc_cmdline", fake)
        monkeypatch.setattr(tpf, "_EMPTY_CMDLINE_GRACE_S", 0.5)
        monkeypatch.setattr(tpf, "_EMPTY_CMDLINE_POLL_S", 0.005)
        pid = os.getpid()
        desc = tpf.TuiPidfile(pid=pid, caps=frozenset({tpf.CAP_RELOAD}),
                              starttime=tpf.proc_starttime(pid))

        # The test process is not a TUI, so the *settled* read still
        # reports a foreign program — but it must be the settled read that
        # decides, i.e. the empty window alone never decides.
        assert tpf.identity_problem(desc) == "pid belongs to a different program"
        assert len(reads) >= 2

    def test_claim_refuses_a_tui_that_is_mid_exec(self, tmp_path,
                                                  start_fake_tui, monkeypatch):
        proc = start_fake_tui()
        path = tmp_path / "tui-pm-test.pid"
        _write_json(path, proc.pid, [tpf.CAP_RELOAD, tpf.CAP_COMMAND])
        fake, reads = self._empty_once_then(tpf.proc_cmdline)
        monkeypatch.setattr(tpf, "proc_cmdline", fake)
        monkeypatch.setattr(tpf, "_EMPTY_CMDLINE_GRACE_S", 0.5)
        monkeypatch.setattr(tpf, "_EMPTY_CMDLINE_POLL_S", 0.005)

        with pytest.raises(tpf.TuiPidfileConflict):
            tpf.claim_tui_pidfile(path, SESSION)

        assert len(reads) >= 2
        assert tpf.read_pidfile(path).pid == proc.pid

    def test_submit_keeps_the_pidfile_of_a_tui_that_is_mid_exec(
            self, ipc_paths, start_fake_tui, monkeypatch):
        proc = start_fake_tui()
        pidfile, queue = ipc_paths
        _write_json(pidfile, proc.pid, [tpf.CAP_RELOAD, tpf.CAP_COMMAND])
        fake, reads = self._empty_once_then(tpf.proc_cmdline)
        monkeypatch.setattr(tpf, "proc_cmdline", fake)
        monkeypatch.setattr(tpf, "_EMPTY_CMDLINE_GRACE_S", 0.5)
        monkeypatch.setattr(tpf, "_EMPTY_CMDLINE_POLL_S", 0.005)

        result = helpers.submit_tui_command(SESSION, "pr list")

        assert result.ok, result.message
        assert len(reads) >= 2
        assert pidfile.exists(), "a live TUI's pidfile must not be removed"
        assert proc.poll() is None

    def test_a_permanently_empty_argv_is_still_rejected(self, monkeypatch):
        """The grace is bounded: a kernel thread's argv never fills in."""
        monkeypatch.setattr(tpf, "proc_cmdline", lambda pid: [])
        monkeypatch.setattr(tpf, "_EMPTY_CMDLINE_GRACE_S", 0.05)
        monkeypatch.setattr(tpf, "_EMPTY_CMDLINE_POLL_S", 0.005)
        pid = os.getpid()
        desc = tpf.TuiPidfile(pid=pid, starttime=tpf.proc_starttime(pid))

        started = time.monotonic()
        assert (tpf.identity_problem(desc)
                == "pid belongs to a different program")
        assert time.monotonic() - started < 2.0


# ---------------------------------------------------------------------------
# Startup claim


class TestClaim:
    def test_takes_over_dead_pid(self, tmp_path):
        path = tmp_path / "tui-pm-test.pid"
        _write_legacy(path, DEAD_PID)
        claim = tpf.claim_tui_pidfile(path, SESSION)
        try:
            desc = tpf.read_pidfile(path)
            assert desc.pid == os.getpid()
            assert desc.legacy is False
            assert desc.caps == frozenset()  # not published yet
            assert desc.starttime == tpf.proc_starttime(os.getpid())
        finally:
            claim.release()

    def test_refuses_live_sibling_tui(self, tmp_path, start_fake_tui):
        path = tmp_path / "tui-pm-test.pid"
        sibling = start_fake_tui()
        _write_json(path, sibling.pid, [tpf.CAP_RELOAD, tpf.CAP_COMMAND])
        with pytest.raises(tpf.TuiPidfileConflict) as exc:
            tpf.claim_tui_pidfile(path, SESSION)
        assert str(sibling.pid) in str(exc.value)
        # Name the file: on a platform without procfs the identity check
        # degrades to liveness, so a recycled PID refuses startup and the
        # user needs the path to get unstuck.
        assert str(path) in str(exc.value)
        # The sibling's descriptor is untouched.
        assert tpf.read_pidfile(path).pid == sibling.pid
        assert sibling.poll() is None

    def test_takes_over_recycled_pid(self, tmp_path, procs):
        """A live PID whose cmdline is not a TUI is a recycled PID."""
        path = tmp_path / "tui-pm-test.pid"
        other = subprocess.Popen(["sleep", "300"])
        procs.append(other)
        _write_json(path, other.pid, [tpf.CAP_RELOAD, tpf.CAP_COMMAND])
        claim = tpf.claim_tui_pidfile(path, SESSION)
        try:
            assert tpf.read_pidfile(path).pid == os.getpid()
            assert other.poll() is None
        finally:
            claim.release()

    def test_allows_same_process_on_exec_restart(self, tmp_path):
        path = tmp_path / "tui-pm-test.pid"
        _write_json(path, os.getpid(), [tpf.CAP_RELOAD, tpf.CAP_COMMAND])
        claim = tpf.claim_tui_pidfile(path, SESSION)
        try:
            desc = tpf.read_pidfile(path)
            assert desc.pid == os.getpid()
            assert desc.caps == frozenset()  # caps reset until republished
        finally:
            claim.release()

    def test_takes_over_corrupt_file(self, tmp_path):
        path = tmp_path / "tui-pm-test.pid"
        path.write_text("garbage")
        claim = tpf.claim_tui_pidfile(path, SESSION)
        try:
            assert tpf.read_pidfile(path).pid == os.getpid()
        finally:
            claim.release()

    def test_takes_over_out_of_range_pid(self, tmp_path):
        """A huge PID is stale, not an OverflowError out of the claim.

        ``os.kill`` refuses a pid outside C ``int`` range, so a corrupt
        pidfile holding one used to crash ``pm _tui`` at startup instead
        of being taken over (E3).
        """
        path = tmp_path / "tui-pm-test.pid"
        path.write_text(str(10 ** 20))
        claim = tpf.claim_tui_pidfile(path, SESSION)
        try:
            assert claim.pid == os.getpid()
            assert tpf.read_pidfile(path).pid == os.getpid()
        finally:
            claim.release()

    def test_takes_over_stale_empty_file(self, tmp_path):
        """An empty file nobody is writing is stale, not a peer mid-claim."""
        path = tmp_path / "tui-pm-test.pid"
        path.write_text("")
        claim = tpf.claim_tui_pidfile(path, SESSION)
        try:
            assert tpf.read_pidfile(path).pid == os.getpid()
        finally:
            claim.release()

    def test_does_not_steal_empty_file_mid_claim(self, tmp_path,
                                                 start_fake_tui):
        """A peer between O_EXCL create and its first write must win."""
        import threading
        path = tmp_path / "tui-pm-test.pid"
        sibling = start_fake_tui()
        path.write_text("")  # peer created the file, has not written yet

        def _publish():
            time.sleep(0.01)
            _write_json(path, sibling.pid, [tpf.CAP_RELOAD, tpf.CAP_COMMAND])

        writer = threading.Thread(target=_publish)
        writer.start()
        try:
            with pytest.raises(tpf.TuiPidfileConflict):
                tpf.claim_tui_pidfile(path, SESSION)
        finally:
            writer.join()
        # The peer's descriptor survived; we did not take the session.
        assert tpf.read_pidfile(path).pid == sibling.pid
        assert sibling.poll() is None

    def test_empty_file_waits_even_after_stale_rounds(self, tmp_path,
                                                      monkeypatch,
                                                      start_fake_tui):
        """The mid-claim wait is keyed on the file being empty, not on the
        attempt number.

        Two earlier unlink rounds must not eat the budget that gives a
        peer's just-created (still empty) pidfile its chance to be
        published; otherwise this process unlinks the peer's file and
        both TUIs run, each ``publish`` clobbering the other.
        """
        path = tmp_path / "tui-pm-test.pid"
        path.write_text("garbage")  # keeps O_EXCL failing all the way
        sibling = start_fake_tui()
        peer = json.dumps({
            "version": 1, "pid": sibling.pid, "session": SESSION,
            "started_at": "x", "starttime": tpf.proc_starttime(sibling.pid),
            "caps": [tpf.CAP_RELOAD, tpf.CAP_COMMAND],
        })
        # Two stale (non-empty) rounds, then the peer's empty file, then
        # the peer's published descriptor.
        scripted = iter(["garbage", "garbage", "", peer])
        monkeypatch.setattr(tpf, "read_pidfile_text",
                            lambda p: next(scripted, peer))
        unlinked = []
        monkeypatch.setattr(tpf, "unlink_if_unchanged",
                            lambda p, raw: unlinked.append(raw) or False)
        slept = []
        monkeypatch.setattr(tpf.time, "sleep", lambda s: slept.append(s))

        with pytest.raises(tpf.TuiPidfileConflict):
            tpf.claim_tui_pidfile(path, SESSION)

        assert unlinked == ["garbage", "garbage"]  # the empty file was kept
        assert slept == [tpf._CLAIM_RETRY_S]       # and waited for

    def test_takes_over_binary_file(self, tmp_path):
        """Undecodable bytes must not crash the startup claim."""
        path = tmp_path / "tui-pm-test.pid"
        path.write_bytes(b"\xff\xfe\x00garbage")
        claim = tpf.claim_tui_pidfile(path, SESSION)
        try:
            assert tpf.read_pidfile(path).pid == os.getpid()
        finally:
            claim.release()

    def test_write_failure_leaves_no_pidfile(self, tmp_path, monkeypatch):
        """A descriptor we could not write must not strand callers.

        The O_EXCL create happens before the write; leaving the resulting
        empty file behind would make every caller report "has not finished
        starting up" for as long as this TUI runs.
        """
        path = tmp_path / "tui-pm-test.pid"

        def boom(fd, data):
            raise OSError("disk full")

        monkeypatch.setattr(tpf, "_write_all", boom)
        with pytest.raises(OSError):
            tpf.claim_tui_pidfile(path, SESSION)
        assert not path.exists()

    def test_short_writes_are_retried(self, tmp_path, monkeypatch):
        """A partial ``os.write`` must not leave a truncated descriptor."""
        path = tmp_path / "descriptor"
        real_write = os.write
        chunks = []

        def short(fd, data):
            chunk = bytes(data)[:3]
            chunks.append(len(chunk))
            return real_write(fd, chunk)

        with open(path, "wb") as f:
            with monkeypatch.context() as m:
                m.setattr(tpf.os, "write", short)
                tpf._write_all(f.fileno(), b"abcdefgh")
        assert path.read_bytes() == b"abcdefgh"
        assert chunks == [3, 3, 2]

    def test_unremovable_stale_file_degrades_instead_of_refusing(
            self, tmp_path, monkeypatch):
        """A stale file we cannot unlink must not take the TUI down.

        Exhausting the claim rounds on a file that never named a live TUI
        (an unwritable ``~/.pm``, a file owned by someone else) is not a
        conflict: refusing to start would kill the whole TUI over a
        pidfile problem (spec E13).  It is an ``OSError``, which the
        launcher and ``_install_reload_signal`` log before continuing
        without external IPC.
        """
        path = tmp_path / "tui-pm-test.pid"
        path.write_text("garbage")
        monkeypatch.setattr(tpf, "unlink_if_unchanged", lambda p, raw: False)
        with pytest.raises(tpf.TuiPidfileUnavailable) as exc:
            tpf.claim_tui_pidfile(path, SESSION)
        assert isinstance(exc.value, OSError)
        assert not isinstance(exc.value, tpf.TuiPidfileConflict)
        assert str(path) in str(exc.value)

    def test_publish_updates_caps(self, tmp_path):
        path = tmp_path / "tui-pm-test.pid"
        claim = tpf.claim_tui_pidfile(path, SESSION)
        try:
            assert tpf.read_pidfile(path).caps == frozenset()
            claim.publish([tpf.CAP_RELOAD, tpf.CAP_COMMAND])
            assert tpf.read_pidfile(path).caps == {
                tpf.CAP_RELOAD, tpf.CAP_COMMAND}
        finally:
            claim.release()

    def test_release_leaves_successor_descriptor(self, tmp_path):
        path = tmp_path / "tui-pm-test.pid"
        claim = tpf.claim_tui_pidfile(path, SESSION)
        # Simulate a successor taking over the file.
        _write_json(path, DEAD_PID, [tpf.CAP_RELOAD])
        claim.release()
        assert path.exists()
        assert tpf.read_pidfile(path).pid == DEAD_PID

    def test_successor_mid_claim_counts_as_owned_by_other(self, tmp_path):
        """A successor's empty O_EXCL file must not read as "nobody owns it".

        The dying TUI uses ``owned_by_other`` to decide whether the shared
        command queue now belongs to a successor; an empty file is that
        successor between its create and its first write, so the queue
        must be left alone (and ``release`` must not unlink the file).
        """
        path = tmp_path / "tui-pm-test.pid"
        claim = tpf.claim_tui_pidfile(path, SESSION)
        path.write_text("")  # successor created it, has not written yet
        assert claim.owned_by_other() is True
        claim.release()
        assert path.exists()
        # Our own descriptor is not "someone else".
        _write_json(path, os.getpid(), [tpf.CAP_RELOAD])
        assert claim.owned_by_other() is False


# ---------------------------------------------------------------------------
# Caller side: command queue


class TestSubmitCommand:
    def test_no_pidfile(self, ipc_paths):
        pidfile, queue = ipc_paths
        res = helpers.submit_tui_command(SESSION, "review-loop pr-1")
        assert res.ok is False
        assert res.reason == "no_pidfile"
        assert not queue.exists()

    def test_dead_pid_removes_pidfile(self, ipc_paths):
        pidfile, queue = ipc_paths
        _write_json(pidfile, DEAD_PID, [tpf.CAP_RELOAD, tpf.CAP_COMMAND])
        res = helpers.submit_tui_command(SESSION, "review-loop pr-1")
        assert res.ok is False
        assert res.reason == "stale_pidfile"
        assert "is not running" in res.message
        # The popup must not read "is not running (process is not running)".
        assert "(process is not running)" not in res.message
        assert not pidfile.exists()
        assert not queue.exists()

    def test_undecodable_pidfile_is_stale(self, ipc_paths):
        pidfile, queue = ipc_paths
        pidfile.write_bytes(b"\xff\xfe\x00garbage")
        res = helpers.submit_tui_command(SESSION, "review-loop pr-1")
        assert res.ok is False
        assert res.reason == "stale_pidfile"
        assert not pidfile.exists()
        assert not queue.exists()

    def test_out_of_range_pid_is_stale_not_a_crash(self, ipc_paths):
        """A corrupt huge PID must not raise out of the picker path.

        The number parses as an int but ``os.kill`` refuses it with
        ``OverflowError``; the caller must see a clean "unreadable
        pidfile" instead of a traceback (E3).
        """
        pidfile, queue = ipc_paths
        pidfile.write_text(str(10 ** 20))
        assert helpers.tui_owner_problem(SESSION) == "unreadable pidfile"
        res = helpers.submit_tui_command(SESSION, "review-loop pr-1")
        assert res.ok is False
        assert res.reason == "stale_pidfile"
        assert "unreadable" in res.message
        assert not pidfile.exists()
        assert not queue.exists()

    def test_recycled_pid_starttime_mismatch(self, ipc_paths, procs):
        pidfile, queue = ipc_paths
        other = subprocess.Popen(["sleep", "300"])
        procs.append(other)
        _write_json(pidfile, other.pid, [tpf.CAP_RELOAD, tpf.CAP_COMMAND],
                    starttime=1)
        res = helpers.submit_tui_command(SESSION, "review-loop pr-1")
        assert res.ok is False
        assert "reused" in res.message
        assert not pidfile.exists()
        assert not queue.exists()
        time.sleep(0.2)
        assert other.poll() is None  # never signaled

    def test_wrong_cmdline(self, ipc_paths, procs):
        pidfile, queue = ipc_paths
        other = subprocess.Popen(["sleep", "300"])
        procs.append(other)
        _write_json(pidfile, other.pid, [tpf.CAP_RELOAD, tpf.CAP_COMMAND])
        res = helpers.submit_tui_command(SESSION, "review-loop pr-1")
        assert res.ok is False
        assert "different program" in res.message
        assert not pidfile.exists()
        assert not queue.exists()
        time.sleep(0.2)
        assert other.poll() is None

    def test_legacy_tui_lacks_command_capability(self, ipc_paths,
                                                 start_fake_tui):
        pidfile, queue = ipc_paths
        tui = start_fake_tui(usr1=True, usr2=False)
        _write_legacy(pidfile, tui.pid)
        res = helpers.submit_tui_command(SESSION, "review-loop pr-1")
        assert res.ok is False
        assert res.reason == "missing_capability"
        assert "predates the command-queue feature" in res.message
        assert "restart the TUI" in res.message
        assert not queue.exists()          # nothing queued
        assert pidfile.exists()            # live TUI: keep the file
        time.sleep(0.3)
        assert tui.poll() is None          # and never signaled

    def test_starting_tui_has_no_caps_yet(self, ipc_paths, start_fake_tui):
        pidfile, queue = ipc_paths
        tui = start_fake_tui(usr1=True, usr2=True)
        _write_json(pidfile, tui.pid, [])
        res = helpers.submit_tui_command(SESSION, "review-loop pr-1")
        assert res.ok is False
        assert res.reason == "starting"
        assert "still starting up" in res.message
        # A claim that never publishes (handler install failed) must still
        # point the user at the one action that fixes it.
        assert "restart the TUI" in res.message
        assert not queue.exists()

    def test_partial_caps_tui_is_not_signaled(self, ipc_paths,
                                              start_fake_tui):
        pidfile, queue = ipc_paths
        tui = start_fake_tui(usr1=True, usr2=True)
        _write_json(pidfile, tui.pid, [tpf.CAP_RELOAD])
        res = helpers.submit_tui_command(SESSION, "review-loop pr-1")
        assert res.ok is False
        assert res.reason == "missing_capability"
        assert "does not advertise the command-queue capability" in res.message
        assert not queue.exists()
        time.sleep(0.3)
        assert tui.poll() is None

    def test_success_queues_and_signals(self, ipc_paths, start_fake_tui,
                                        tmp_path):
        pidfile, queue = ipc_paths
        marker = tmp_path / "marker.txt"
        tui = start_fake_tui(usr1=True, usr2=True, marker=marker)
        _write_json(pidfile, tui.pid, [tpf.CAP_RELOAD, tpf.CAP_COMMAND])
        res = helpers.submit_tui_command(SESSION, "review-loop pr-1")
        assert res.ok is True
        assert queue.read_text() == "review-loop pr-1\n"
        assert _wait_for(lambda: _marker_lines(marker) == ["sigusr2"])
        assert tui.poll() is None

    def test_append_reaches_the_file_before_the_lock_is_released(
            self, ipc_paths, start_fake_tui, monkeypatch):
        """The queued line must be on disk *under* the append lock.

        The TUI's drain reads and truncates the queue under the same
        flock.  A ``write`` still sitting in Python's buffer when the
        lock is released would land in the file after a concurrent drain
        truncated it, so the command would be silently dropped — and
        because the TUI is perfectly healthy the spinner's owner check
        would never abort, leaving "queued…" forever.
        """
        import fcntl as _fcntl

        pidfile, queue = ipc_paths
        tui = start_fake_tui()
        _write_json(pidfile, tui.pid, [tpf.CAP_RELOAD, tpf.CAP_COMMAND])

        seen_at_unlock = []
        real_flock = _fcntl.flock

        def spy(fd, op):
            if op == _fcntl.LOCK_UN:
                seen_at_unlock.append(queue.read_bytes())
            return real_flock(fd, op)

        monkeypatch.setattr(_fcntl, "flock", spy)
        res = helpers.submit_tui_command(SESSION, "review-loop pr-1")

        assert res.ok is True
        # Verified to fail before the ``f.flush()``: the file was still
        # empty at LOCK_UN and only gained the line when the ``with``
        # block closed the file afterwards.
        assert seen_at_unlock == [b"review-loop pr-1\n"]

    def test_trigger_tui_command_is_boolean(self, ipc_paths):
        res = helpers.trigger_tui_command(SESSION, "review-loop pr-1")
        assert res is False

    def test_permission_denied_keeps_pidfile(self, ipc_paths, start_fake_tui,
                                             monkeypatch):
        """EPERM means a live process we don't own: never delete its file."""
        pidfile, queue = ipc_paths
        tui = start_fake_tui()
        _write_json(pidfile, tui.pid, [tpf.CAP_RELOAD, tpf.CAP_COMMAND])
        monkeypatch.setattr(helpers, "_signal_tui",
                            lambda *a, **k: "permission denied")

        res = helpers.submit_tui_command(SESSION, "review-loop pr-1")

        assert res.ok is False
        assert res.reason == "signal_error"
        assert "permission denied" in res.message
        assert pidfile.exists()
        assert tui.poll() is None

    def test_failed_signal_takes_the_command_back(self, ipc_paths,
                                                  start_fake_tui,
                                                  monkeypatch):
        """A reported failure must not linger in the queue for a later drain.

        Otherwise the picker says "could not signal" and some later SIGUSR2
        (or the next startup within the staleness window) runs the command
        anyway.
        """
        pidfile, queue = ipc_paths
        tui = start_fake_tui()
        _write_json(pidfile, tui.pid, [tpf.CAP_RELOAD, tpf.CAP_COMMAND])
        queue.write_text("earlier command\n")
        monkeypatch.setattr(helpers, "_signal_tui",
                            lambda *a, **k: "permission denied")

        res = helpers.submit_tui_command(SESSION, "review-loop pr-1")

        assert res.ok is False
        assert queue.read_text() == "earlier command\n"

    def test_zombie_after_validation_is_stale(self, ipc_paths, start_fake_tui,
                                              monkeypatch):
        """A TUI that dies between validation and the signal is a zombie.

        Both os.kill and pidfd_send_signal "succeed" against an unreaped
        process and discard the signal, so the delivery must not be
        reported as ok — the pidfile is stale and the line is rolled back.
        """
        pidfile, queue = ipc_paths
        tui = start_fake_tui()
        _write_json(pidfile, tui.pid, [tpf.CAP_RELOAD, tpf.CAP_COMMAND])
        monkeypatch.setattr(helpers, "_signal_tui",
                            lambda *a, **k: "process is a zombie")

        res = helpers.submit_tui_command(SESSION, "review-loop pr-1")

        assert res.ok is False
        assert res.reason == "stale_pidfile"
        assert not pidfile.exists()
        assert queue.read_text() == ""

    def test_queue_write_failure(self, ipc_paths, start_fake_tui):
        """An unwritable queue is reported, and the TUI is not signaled."""
        pidfile, queue = ipc_paths
        tui = start_fake_tui()
        _write_json(pidfile, tui.pid, [tpf.CAP_RELOAD, tpf.CAP_COMMAND])
        queue.mkdir()  # open(queue, "a") -> IsADirectoryError

        res = helpers.submit_tui_command(SESSION, "review-loop pr-1")

        assert res.ok is False
        assert res.reason == "queue_error"
        assert "command queue" in res.message
        assert pidfile.exists()  # live TUI: keep its descriptor
        time.sleep(0.2)
        assert tui.poll() is None  # and never signaled

    def test_partial_queue_write_is_cut_off(self, ipc_paths, start_fake_tui,
                                            monkeypatch):
        """A short write must not leave half a command behind.

        ``_unqueue_line`` matches whole lines, so it cannot take back a
        *partial* line.  A later drain would then run a truncated command
        the caller was told was not applied (``pr qa fresh pr-1`` cut to
        ``pr qa``), so the append truncates back to its pre-write size
        under the same lock.
        """
        pidfile, queue = ipc_paths
        tui = start_fake_tui()
        _write_json(pidfile, tui.pid, [tpf.CAP_RELOAD, tpf.CAP_COMMAND])
        queue.write_bytes(b"pr qa fresh pr-9\n")
        before = queue.read_bytes()

        monkeypatch.setattr(helpers, "open", _failing_append_open(open),
                            raising=False)
        res = helpers.submit_tui_command(SESSION, "review-loop pr-1")

        assert res.ok is False
        assert res.reason == "queue_error"
        assert queue.read_bytes() == before, "partial line must be removed"
        assert pidfile.exists()
        assert tui.poll() is None  # never signaled

    def test_partial_write_keeps_a_concurrent_callers_line(
            self, ipc_paths, start_fake_tui, monkeypatch):
        """The rollback target is the size *under* the lock, not at open.

        ``open(..., "ab")`` pins the stream position when the file is
        opened, so a line another caller appends between our open and our
        flock is not reflected in ``tell()``.  Truncating back to that
        stale offset on a failed write would delete a command the other
        caller was told was queued (and would extend the file with NULs
        if a drain had shrunk it in the meantime).
        """
        pidfile, queue = ipc_paths
        tui = start_fake_tui()
        _write_json(pidfile, tui.pid, [tpf.CAP_RELOAD, tpf.CAP_COMMAND])
        queue.write_bytes(b"pr qa fresh pr-9\n")

        monkeypatch.setattr(
            helpers, "open",
            _failing_append_open(open, concurrent=b"review-loop pr-2\n"),
            raising=False)
        res = helpers.submit_tui_command(SESSION, "review-loop pr-1")

        assert res.ok is False
        assert res.reason == "queue_error"
        assert queue.read_bytes() == (b"pr qa fresh pr-9\n"
                                      b"review-loop pr-2\n"), (
            "the concurrent caller's line must survive our rollback")
        assert tui.poll() is None  # never signaled

    def test_flush_failure_still_cuts_the_partial_line(
            self, ipc_paths, start_fake_tui, monkeypatch):
        """A full disk fails the *flush*, not ``write`` — roll back anyway.

        ``_failing_append_open`` raises out of ``write`` before any byte
        is buffered, so it never reached the path a real short write
        takes.  Here the kernel accepts five bytes and then reports
        ENOSPC, so a buffered append fails from ``flush`` and keeps the
        unwritten remainder in its buffer: ``truncate`` then re-raises
        from its own flush and the half-line survives (verified: the
        queue ended up holding ``b'pr qa fresh pr-9\\nrevie'``).  The
        append must be unbuffered so the rollback is a plain
        ``ftruncate``.
        """
        pidfile, queue = ipc_paths
        tui = start_fake_tui()
        _write_json(pidfile, tui.pid, [tpf.CAP_RELOAD, tpf.CAP_COMMAND])
        queue.write_bytes(b"pr qa fresh pr-9\n")
        before = queue.read_bytes()

        monkeypatch.setattr(
            helpers, "open",
            _flush_failing_append_open(open), raising=False)
        res = helpers.submit_tui_command(SESSION, "review-loop pr-1")

        assert res.ok is False
        assert res.reason == "queue_error"
        assert queue.read_bytes() == before, "partial line must be removed"
        assert pidfile.exists()
        assert tui.poll() is None  # never signaled

    def test_short_write_is_finished(self, ipc_paths, start_fake_tui,
                                     monkeypatch):
        """A short raw write must be completed, not reported as failure."""
        pidfile, queue = ipc_paths
        tui = start_fake_tui()
        _write_json(pidfile, tui.pid, [tpf.CAP_RELOAD, tpf.CAP_COMMAND])

        monkeypatch.setattr(
            helpers, "open",
            _short_then_ok_append_open(open), raising=False)
        res = helpers.submit_tui_command(SESSION, "review-loop pr-1")

        assert res.ok is True
        assert queue.read_bytes() == b"review-loop pr-1\n"

    def test_empty_pidfile_is_starting_not_stale(self, ipc_paths):
        """A peer mid-claim must keep its file: deleting it reopens the race.

        The claim side waits out an empty file before treating it as stale
        (A2); the caller side must not delete it out from under that peer.
        """
        pidfile, queue = ipc_paths
        pidfile.write_text("")
        res = helpers.submit_tui_command(SESSION, "review-loop pr-1")
        assert res.ok is False
        assert res.reason == "starting"
        assert "starting up" in res.message
        # A TUI killed between O_EXCL create and its first write leaves an
        # empty file forever; the message must name the way out.
        assert "restart the TUI (Ctrl+R)" in res.message
        assert pidfile.exists()
        assert pidfile.read_text() == ""
        assert not queue.exists()
        assert helpers.tui_owner_problem(SESSION) == "empty pidfile"

    def test_whitespace_only_pidfile_is_unreadable_not_starting(self, ipc_paths):
        """Only a *zero-length* file is the mid-claim window (A2/E3).

        ``claim_tui_pidfile`` writes the whole JSON descriptor in one go,
        so whitespace-only content is corruption, not a peer mid-claim;
        the claim side unlinks it immediately and the caller side must
        agree instead of reporting "starting up" for the life of the file.
        """
        pidfile, queue = ipc_paths
        pidfile.write_text(" \n\t")
        assert helpers.tui_owner_problem(SESSION) == "unreadable pidfile"
        res = helpers.submit_tui_command(SESSION, "review-loop pr-1")
        assert res.ok is False
        assert res.reason == "stale_pidfile"
        assert not pidfile.exists()
        assert not queue.exists()

    def test_command_is_written_as_one_line(self, ipc_paths, start_fake_tui):
        """A line break inside a command must not split it in the drain.

        The TUI drains with ``str.splitlines`` while ``_unqueue_line``
        splits on ``b"\\n"``; if a ``\\r``/``\\x0b``/U+2028 survived in the
        command, the drain would see two commands and a failed submission
        could never be rolled back (it would be applied by a later drain).
        """
        pidfile, queue = ipc_paths
        tui = start_fake_tui()
        _write_json(pidfile, tui.pid, [tpf.CAP_RELOAD, tpf.CAP_COMMAND])

        res = helpers.submit_tui_command(
            SESSION, "qa pr-1\rpm pr done\x0bX\u2028Y")
        assert res.ok is True

        raw = queue.read_bytes()
        assert raw.count(b"\n") == 1
        assert raw.endswith(b"\n")
        # What the drain would see, and what the rollback splits on, agree.
        assert len(raw.decode("utf-8").splitlines()) == 1
        assert raw.decode("utf-8").rstrip("\n") == "qa pr-1 pm pr done X Y"

    def test_non_ascii_command_is_rolled_back(self, ipc_paths,
                                              start_fake_tui, monkeypatch):
        """Writer and rollback must agree byte-for-byte under any locale."""
        pidfile, queue = ipc_paths
        tui = start_fake_tui()
        _write_json(pidfile, tui.pid, [tpf.CAP_RELOAD, tpf.CAP_COMMAND])
        monkeypatch.setattr(helpers, "_signal_tui",
                            lambda *a, **k: "permission denied")

        res = helpers.submit_tui_command(SESSION, "qa pr-1 — naïve ✓")

        assert res.ok is False
        assert res.reason == "signal_error"
        assert queue.read_bytes() == b""


class TestUnqueue:
    """Rolling back a queued line after the signal fails."""

    def test_removes_only_our_trailing_line(self, tmp_path):
        queue = tmp_path / "q"
        queue.write_text("earlier\nours\n")
        helpers._unqueue_line(queue, "ours\n")
        assert queue.read_text() == "earlier\n"

    def test_removes_our_line_when_a_later_one_follows(self, tmp_path):
        """A later caller's line must not keep our failed command queued.

        The signal for our line failed, so the user was told it was not
        applied; a concurrent caller appending after us must not resurrect
        it by pinning it into the middle of the queue.
        """
        queue = tmp_path / "q"
        queue.write_text("ours\ntheirs\n")
        helpers._unqueue_line(queue, "ours\n")
        assert queue.read_text() == "theirs\n"

    def test_removes_our_line_and_keeps_a_later_longer_one(self, tmp_path):
        """Whole-line matching: our line goes, a longer one stays intact.

        Command lines are arbitrary text, so a later caller's command can
        end with ours (``pm qa pr-1`` ends with ``qa pr-1``).  A suffix
        match is not our line: ours is removed by value and the longer
        line is kept byte-for-byte.
        """
        queue = tmp_path / "q"
        queue.write_text("ours\npm ours\n")
        helpers._unqueue_line(queue, "ours\n")
        assert queue.read_text() == "pm ours\n"

    def test_leaves_a_line_that_only_ends_with_ours(self, tmp_path):
        """A suffix of a longer line is not our line: never slice it."""
        queue = tmp_path / "q"
        queue.write_text("pm ours\n")
        helpers._unqueue_line(queue, "ours\n")
        assert queue.read_text() == "pm ours\n"

    def test_already_drained_line_is_a_noop(self, tmp_path):
        """The TUI drained our line before the rollback: nothing to do."""
        queue = tmp_path / "q"
        queue.write_text("")
        helpers._unqueue_line(queue, "ours\n")
        assert queue.read_text() == ""

    def test_missing_queue_is_swallowed(self, tmp_path):
        helpers._unqueue_line(tmp_path / "nope", "ours\n")  # no exception


# ---------------------------------------------------------------------------
# Caller side: reload


class TestReload:
    def test_legacy_tui_still_reloads(self, ipc_paths, start_fake_tui,
                                      tmp_path):
        """A numeric pidfile proves SIGUSR1 support (same commit)."""
        pidfile, _queue = ipc_paths
        marker = tmp_path / "marker.txt"
        tui = start_fake_tui(usr1=True, usr2=True, marker=marker)
        _write_legacy(pidfile, tui.pid)
        assert helpers.trigger_tui_reload(SESSION) is True
        assert _wait_for(lambda: _marker_lines(marker) == ["sigusr1"])
        assert tui.poll() is None

    def test_tui_without_reload_capability_is_not_signaled(self, ipc_paths,
                                                           start_fake_tui,
                                                           tmp_path):
        pidfile, _queue = ipc_paths
        marker = tmp_path / "marker.txt"
        tui = start_fake_tui(usr1=True, usr2=True, marker=marker)
        _write_json(pidfile, tui.pid, [tpf.CAP_COMMAND])
        assert helpers.trigger_tui_reload(SESSION) is False
        time.sleep(0.3)
        assert _marker_lines(marker) == []
        assert tui.poll() is None
        assert pidfile.exists()  # live TUI: never remove its descriptor

    def test_reload_is_refused_while_starting(self, ipc_paths,
                                              start_fake_tui):
        """caps=[] means claimed but not published: never signal."""
        pidfile, _queue = ipc_paths
        tui = start_fake_tui()
        _write_json(pidfile, tui.pid, [])
        assert helpers.trigger_tui_reload(SESSION) is False
        assert pidfile.exists()
        time.sleep(0.3)
        assert tui.poll() is None

    def test_dead_pid_removes_pidfile(self, ipc_paths):
        pidfile, _queue = ipc_paths
        _write_json(pidfile, DEAD_PID, [tpf.CAP_RELOAD])
        assert helpers.trigger_tui_reload(SESSION) is False
        assert not pidfile.exists()

    def test_missing_pidfile_is_false(self, ipc_paths):
        pidfile, _queue = ipc_paths
        assert helpers.trigger_tui_reload(SESSION) is False
        assert not pidfile.exists()

    def test_owner_problem_reports_staleness(self, ipc_paths, procs):
        pidfile, _queue = ipc_paths
        assert helpers.tui_owner_problem(SESSION) == "no pidfile"
        other = subprocess.Popen(["sleep", "300"])
        procs.append(other)
        _write_json(pidfile, other.pid, [tpf.CAP_RELOAD])
        assert helpers.tui_owner_problem(SESSION) == (
            "pid belongs to a different program")

    def test_owner_problem_distinguishes_unreadable(self, ipc_paths):
        pidfile, _queue = ipc_paths
        pidfile.write_bytes(b"\xff\xfe\x00garbage")
        assert helpers.tui_owner_problem(SESSION) == "unreadable pidfile"


class TestIdentity:
    def test_zombie_owner_is_not_live(self):
        """kill(pid, 0) succeeds for a zombie; it must not look like a TUI."""
        proc = subprocess.Popen(["true"])
        try:
            assert _wait_for(lambda: tpf.is_zombie(proc.pid))
            desc = tpf.TuiPidfile(
                pid=proc.pid, caps=frozenset({tpf.CAP_RELOAD}),
                starttime=tpf.proc_starttime(proc.pid))
            assert tpf.identity_problem(desc) == "process is a zombie"
        finally:
            proc.wait(timeout=5)

    def test_pid_alive_is_total_for_out_of_range_pids(self):
        """os.kill raises OverflowError, not OSError, past C int range."""
        assert tpf.pid_alive(2 ** 40) is False
        assert tpf.identity_problem(tpf.TuiPidfile(pid=2 ** 40)) == (
            "process is not running")

    def test_owner_reaped_mid_check_is_not_a_live_tui(self, monkeypatch):
        """A process that exits mid-check must not look like a live TUI.

        ``/proc/<pid>`` vanishes once the process is reaped, so the
        cmdline read returns ``None`` ("cannot tell") — the same value
        that means "no procfs".  Concluding "live TUI" there would make
        ``claim_tui_pidfile`` refuse to start against a dead owner.
        """
        alive_calls = []

        def flaky_alive(pid):
            alive_calls.append(pid)
            return len(alive_calls) == 1

        monkeypatch.setattr(tpf, "pid_alive", flaky_alive)
        monkeypatch.setattr(tpf, "proc_cmdline", lambda pid: None)
        desc = tpf.TuiPidfile(pid=DEAD_PID)

        assert tpf.identity_problem(desc) == "process is not running"
        assert len(alive_calls) == 2

    def test_claim_takes_over_an_owner_that_was_reaped_mid_check(
            self, tmp_path, monkeypatch):
        """The claim must not refuse to start over a vanished owner.

        Pre-fix ``identity_problem`` returned ``None`` here (the cmdline
        check was skipped on a "cannot tell" read), so the claim raised
        ``TuiPidfileConflict`` and ``pm _tui`` could not start until the
        stale file was deleted by hand.
        """
        path = tmp_path / "tui-pm-test.pid"
        _write_json(path, DEAD_PID, [tpf.CAP_RELOAD, tpf.CAP_COMMAND])
        alive_calls = []

        def flaky_alive(pid):
            alive_calls.append(pid)
            return len(alive_calls) == 1

        monkeypatch.setattr(tpf, "pid_alive", flaky_alive)
        monkeypatch.setattr(tpf, "proc_cmdline", lambda pid: None)

        claim = tpf.claim_tui_pidfile(path, SESSION)
        try:
            assert tpf.read_pidfile(path).pid == os.getpid()
        finally:
            claim.release()

    def test_cannot_tell_cmdline_of_a_live_process_still_degrades(
            self, monkeypatch):
        """Off-procfs ("cannot tell") keeps degrading to liveness."""
        monkeypatch.setattr(tpf, "proc_cmdline", lambda pid: None)
        desc = tpf.TuiPidfile(pid=os.getpid())

        assert tpf.identity_problem(desc) is None


class TestNonUtf8ProcStat:
    """A recycled PID may belong to a process with a non-UTF-8 ``comm``.

    ``/proc/<pid>/stat`` carries the 16-byte process name chosen by the
    process itself, so a strict ``read_text`` raises
    ``UnicodeDecodeError`` — which escaped ``proc_starttime`` /
    ``is_zombie`` and therefore the startup claim (``pm _tui`` crashed
    with a traceback instead of taking the stale pidfile over), the
    picker and autostart (tracebacks instead of a message).  Same class
    as the undecodable-pidfile case in E3: identity checks must never
    raise.
    """

    @staticmethod
    def _stat_bytes(state="S", starttime=98765):
        # state (field 3) then fields 4..21, with starttime at field 22
        # (index 19 after the comm).
        fields = [state] + ["1"] * 18 + [str(starttime)]
        return b"1234 (\xff\xfe\x80bad) " + " ".join(fields).encode()

    @staticmethod
    def _fake_procfs(monkeypatch, stat):
        real_path = Path

        class _FakePath:
            def __init__(self, raw):
                self._raw = str(raw)

            def read_text(self, encoding=None, errors=None):
                if self._raw.endswith("/stat"):
                    # Model the real strict-decode failure of the pre-fix
                    # implementation: refuse invalid bytes unless the
                    # caller asked for replacement.
                    return stat.decode("utf-8", errors or "strict")
                return real_path(self._raw).read_text()

            def read_bytes(self):
                if self._raw.endswith("/stat"):
                    return stat
                return real_path(self._raw).read_bytes()

        monkeypatch.setattr(tpf, "Path", _FakePath)

    def test_proc_starttime_and_zombie_survive_non_utf8_comm(
            self, monkeypatch):
        self._fake_procfs(monkeypatch, self._stat_bytes())
        assert tpf.proc_starttime(1234) == 98765
        assert tpf.is_zombie(1234) is False
        self._fake_procfs(monkeypatch, self._stat_bytes(state="Z"))
        assert tpf.is_zombie(1234) is True

    def test_identity_problem_reports_a_reason_instead_of_raising(
            self, monkeypatch):
        self._fake_procfs(monkeypatch, self._stat_bytes())
        # Our own live PID: liveness passes, the (fake) start time matches
        # the descriptor, so the check falls through to the real cmdline —
        # which is pytest, not a TUI.  A reason, never an exception.
        desc = tpf.TuiPidfile(
            pid=os.getpid(), caps=frozenset({tpf.CAP_RELOAD}),
            starttime=98765)
        assert tpf.identity_problem(desc) == (
            "pid belongs to a different program")

    def test_claim_takes_over_a_pidfile_naming_a_non_utf8_process(
            self, tmp_path, monkeypatch):
        """pm _tui must take the stale file over, not crash at startup."""
        path = tmp_path / "tui-pm-test.pid"
        _write_json(path, 1234, [tpf.CAP_RELOAD], starttime=1)
        self._fake_procfs(monkeypatch, self._stat_bytes())
        # pid 1234 is alive for the claim's purposes (monkeypatched
        # liveness below); its start time does not match the descriptor,
        # so it is stale and may be taken over.
        monkeypatch.setattr(tpf, "pid_alive", lambda pid: True)
        claim = tpf.claim_tui_pidfile(path, SESSION)
        try:
            assert tpf.read_pidfile(path).pid == os.getpid()
        finally:
            claim.release()

    def test_submit_tui_command_reports_stale_instead_of_raising(
            self, ipc_paths, monkeypatch):
        pidfile, queue = ipc_paths
        _write_json(pidfile, os.getpid(), [tpf.CAP_RELOAD, tpf.CAP_COMMAND],
                    starttime=98765)
        self._fake_procfs(monkeypatch, self._stat_bytes())
        result = helpers.submit_tui_command(SESSION, "pr list")
        assert result.ok is False
        assert result.reason == "stale_pidfile"
        assert not pidfile.exists()
        assert not queue.exists()


# ---------------------------------------------------------------------------
# Signal guards + app wiring


class TestSignalGuards:
    def test_noop_guards_survive_sigusr2(self):
        """Both signals must be survivable before the real handlers exist.

        Runs in a child process: if the guard regresses, the default
        terminate action kills *that* process and the test fails cleanly,
        instead of taking the whole pytest run down with it.
        """
        code = (
            "import os, signal, time\n"
            "from pm_core.tui_pidfile import install_signal_guards\n"
            "install_signal_guards()\n"
            "os.kill(os.getpid(), signal.SIGUSR1)\n"
            "os.kill(os.getpid(), signal.SIGUSR2)\n"
            "time.sleep(0.1)\n"
            "print('alive')\n"
        )
        # Make pm_core importable in the child regardless of pytest's cwd.
        root = str(Path(tpf.__file__).resolve().parent.parent)
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(
            filter(None, [root, env.get("PYTHONPATH")]))
        res = subprocess.run([sys.executable, "-c", code],
                             capture_output=True, text=True, timeout=30,
                             env=env)
        assert res.returncode == 0, res.stderr
        assert "alive" in res.stdout

    def test_caps_published_only_after_handlers(self, tmp_path, monkeypatch):
        pidfile = tmp_path / "tui-pm-test.pid"
        queue = tmp_path / "tui-pm-test.cmd-queue"
        monkeypatch.setattr(tpf, "pidfile_path", lambda session: pidfile)
        monkeypatch.setattr(tpf, "command_queue_path", lambda session: queue)

        seen = []

        class FakeLoop:
            def add_signal_handler(self, sig, callback):
                # Capture the visible state at handler-install time: caps
                # must still be empty (R3) *and* the queue must already
                # exist (I3) so a caller that sees sigusr2 can never race
                # a missing queue.
                seen.append((sig, tpf.read_pidfile(pidfile).caps,
                             queue.exists()))

        monkeypatch.setattr("asyncio.get_event_loop", lambda: FakeLoop())
        app = ProjectManagerApp.__new__(ProjectManagerApp)
        app._session_name = SESSION
        app._pidfile_claim = None
        app._startup_error = None
        app.action_reload = lambda: None
        app._drain_command_queue = lambda *a, **k: None

        app._install_reload_signal()

        assert app._startup_error is None
        # Both handlers installed while caps were still empty.
        assert [sig for sig, _, _ in seen] == [signal.SIGUSR1, signal.SIGUSR2]
        assert all(caps == frozenset() for _, caps, _ in seen)
        # The queue must exist before any capability is advertised.
        assert all(exists for _, _, exists in seen)
        desc = tpf.read_pidfile(pidfile)
        assert desc.caps == {tpf.CAP_RELOAD, tpf.CAP_COMMAND}
        assert queue.exists()

    def test_claim_io_error_continues_without_ipc(self, tmp_path, monkeypatch):
        pidfile = tmp_path / "tui-pm-test.pid"
        queue = tmp_path / "tui-pm-test.cmd-queue"
        monkeypatch.setattr(tpf, "pidfile_path", lambda session: pidfile)
        monkeypatch.setattr(tpf, "command_queue_path", lambda session: queue)

        def boom(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(tpf, "claim_tui_pidfile", boom)
        app = ProjectManagerApp.__new__(ProjectManagerApp)
        app._session_name = SESSION
        app._pidfile_claim = None
        app._startup_error = None

        app._install_reload_signal()

        assert app._startup_error is None
        assert app._pidfile_claim is None
        assert not pidfile.exists()

    def test_claim_conflict_sets_startup_error_and_exits(self, tmp_path,
                                                         monkeypatch):
        """A live sibling is surfaced and the app exits non-zero."""
        pidfile = tmp_path / "tui-pm-test.pid"
        queue = tmp_path / "tui-pm-test.cmd-queue"
        monkeypatch.setattr(tpf, "pidfile_path", lambda session: pidfile)
        monkeypatch.setattr(tpf, "command_queue_path", lambda session: queue)

        def conflict(*args, **kwargs):
            raise tpf.TuiPidfileConflict(
                f"another TUI (pid 7) already owns session {SESSION!r}; "
                f"refusing to start a second TUI")

        monkeypatch.setattr(tpf, "claim_tui_pidfile", conflict)
        app = ProjectManagerApp.__new__(ProjectManagerApp)
        app._session_name = SESSION
        app._pidfile_claim = None
        app._startup_error = None
        exits = []
        app.exit = lambda **kw: exits.append(kw)

        app._install_reload_signal()

        assert "already owns" in (app._startup_error or "")
        assert exits and exits[0].get("return_code") == 2
        # We never owned the file, so nothing is published or released.
        assert app._pidfile_claim is None
        assert not pidfile.exists()

    def test_unmount_removes_own_pidfile_and_queue(self, tmp_path,
                                                   monkeypatch):
        pidfile = tmp_path / "tui-pm-test.pid"
        queue = tmp_path / "tui-pm-test.cmd-queue"
        monkeypatch.setattr(tpf, "pidfile_path", lambda session: pidfile)
        monkeypatch.setattr(tpf, "command_queue_path", lambda session: queue)
        claim = tpf.claim_tui_pidfile(pidfile, SESSION)
        queue.write_text("pending command\n")

        app = ProjectManagerApp.__new__(ProjectManagerApp)
        app._session_name = SESSION
        app._pidfile_claim = claim
        app._write_queue = None

        app.on_unmount()

        assert not pidfile.exists()
        assert not queue.exists()

    def test_unmount_keeps_successor_queue(self, tmp_path, monkeypatch):
        """A successor owns the shared queue; do not delete it on exit."""
        pidfile = tmp_path / "tui-pm-test.pid"
        queue = tmp_path / "tui-pm-test.cmd-queue"
        monkeypatch.setattr(tpf, "pidfile_path", lambda session: pidfile)
        monkeypatch.setattr(tpf, "command_queue_path", lambda session: queue)
        claim = tpf.claim_tui_pidfile(pidfile, SESSION)
        queue.write_text("successor command\n")
        # A successor took the session over (our descriptor looked stale).
        _write_json(pidfile, DEAD_PID, [tpf.CAP_RELOAD, tpf.CAP_COMMAND])

        app = ProjectManagerApp.__new__(ProjectManagerApp)
        app._session_name = SESSION
        app._pidfile_claim = claim
        app._write_queue = None

        app.on_unmount()

        assert tpf.read_pidfile(pidfile).pid == DEAD_PID
        assert queue.read_text() == "successor command\n"

    def test_unmount_keeps_queue_while_successor_claims(self, tmp_path,
                                                        monkeypatch):
        """A successor mid-claim (empty pidfile) owns the shared queue."""
        pidfile = tmp_path / "tui-pm-test.pid"
        queue = tmp_path / "tui-pm-test.cmd-queue"
        monkeypatch.setattr(tpf, "pidfile_path", lambda session: pidfile)
        monkeypatch.setattr(tpf, "command_queue_path", lambda session: queue)
        claim = tpf.claim_tui_pidfile(pidfile, SESSION)
        queue.write_text("successor command\n")
        # The successor created the file with O_EXCL and has not written
        # its descriptor yet.
        pidfile.write_text("")

        app = ProjectManagerApp.__new__(ProjectManagerApp)
        app._session_name = SESSION
        app._pidfile_claim = claim
        app._write_queue = None

        app.on_unmount()

        assert pidfile.exists()
        assert queue.read_text() == "successor command\n"

    def test_unmount_does_not_delete_unclaimed_pidfile(self, tmp_path,
                                                      monkeypatch):
        """A TUI refused at startup must not delete the sibling's file."""
        pidfile = tmp_path / "tui-pm-test.pid"
        queue = tmp_path / "tui-pm-test.cmd-queue"
        monkeypatch.setattr(tpf, "pidfile_path", lambda session: pidfile)
        monkeypatch.setattr(tpf, "command_queue_path", lambda session: queue)
        _write_json(pidfile, DEAD_PID, [tpf.CAP_RELOAD, tpf.CAP_COMMAND])
        queue.write_text("pending command\n")

        app = ProjectManagerApp.__new__(ProjectManagerApp)
        app._session_name = SESSION
        app._pidfile_claim = None
        app._write_queue = None

        app.on_unmount()

        assert pidfile.exists()
        assert queue.exists()

    def test_failed_handler_install_publishes_partial_caps(
            self, tmp_path, monkeypatch):
        pidfile = tmp_path / "tui-pm-test.pid"
        queue = tmp_path / "tui-pm-test.cmd-queue"
        monkeypatch.setattr(tpf, "pidfile_path", lambda session: pidfile)
        monkeypatch.setattr(tpf, "command_queue_path", lambda session: queue)

        class FakeLoop:
            def add_signal_handler(self, sig, callback):
                if sig == signal.SIGUSR2:
                    raise RuntimeError("no sigusr2 here")

        monkeypatch.setattr("asyncio.get_event_loop", lambda: FakeLoop())
        app = ProjectManagerApp.__new__(ProjectManagerApp)
        app._session_name = SESSION
        app._pidfile_claim = None
        app._startup_error = None
        app.action_reload = lambda: None
        app._drain_command_queue = lambda *a, **k: None

        app._install_reload_signal()

        assert tpf.read_pidfile(pidfile).caps == {tpf.CAP_RELOAD}


class TestDeferredStartupArmsQueue:
    """A failing restore must not disable external IPC.

    ``_cmd_queue_ready`` is only ever set in ``_deferred_startup``, and
    while it is False every queued command is deferred.  If a startup chore
    or the breadcrumb restore raised first, the TUI stayed healthy but
    never drained the queue — the picker spun on ``queued…`` forever and
    its owner check never aborted it (the pidfile was valid).  Both steps
    are therefore logged-and-continued.
    """

    @staticmethod
    def _app(drained, sync_error=None):
        app = ProjectManagerApp.__new__(ProjectManagerApp)
        app._cmd_queue_ready = False

        def _sync():
            if sync_error is not None:
                raise sync_error

        app._deferred_startup_sync = _sync
        app._drain_command_queue = (
            lambda startup=False: drained.append(startup))
        app.run_worker = lambda *a, **k: None
        app._capture_frame = lambda *a, **k: None
        return app

    def test_queue_is_armed_when_the_restore_raises(self, monkeypatch):
        drained = []
        app = self._app(drained)

        async def boom(_app):
            raise RuntimeError("corrupt breadcrumb")

        monkeypatch.setattr("pm_core.tui.auto_start.consume_breadcrumb", boom)
        monkeypatch.setattr("pm_core.tui.sync.startup_github_sync",
                            lambda app: None)

        asyncio.run(app._deferred_startup())

        assert app._cmd_queue_ready is True
        assert drained == [True]

    def test_queue_is_armed_when_a_startup_chore_raises(self, monkeypatch):
        drained = []
        app = self._app(drained, sync_error=RuntimeError("heal failed"))
        restored = []

        async def ok(_app):
            restored.append(True)

        monkeypatch.setattr("pm_core.tui.auto_start.consume_breadcrumb", ok)
        monkeypatch.setattr("pm_core.tui.sync.startup_github_sync",
                            lambda app: None)

        asyncio.run(app._deferred_startup())

        # The restore still runs after a failed chore, then the queue arms.
        assert restored == [True]
        assert app._cmd_queue_ready is True
        assert drained == [True]

    def test_pending_fresh_attempts_are_resumed(self, monkeypatch):
        # A fresh-autostart attempt is a user request that must survive a
        # plain TUI restart; ``_deferred_startup`` is the only place that
        # re-arms its target from the PR marker.
        drained = []
        app = self._app(drained)
        resumed = []

        async def ok(_app):
            pass

        monkeypatch.setattr("pm_core.tui.auto_start.consume_breadcrumb", ok)
        monkeypatch.setattr("pm_core.tui.sync.startup_github_sync",
                            lambda app: None)
        monkeypatch.setattr("pm_core.tui.autostart_fresh.resume_pending",
                            lambda a: resumed.append(a) or [])

        asyncio.run(app._deferred_startup())

        assert resumed == [app]
        assert app._cmd_queue_ready is True
        assert drained == [True]

    def test_a_failing_resume_does_not_disable_the_queue(self, monkeypatch):
        # Same contract as the restore above: a failing resume must leave the
        # TUI on defaults, not with every externally queued command deferred.
        drained = []
        app = self._app(drained)

        async def ok(_app):
            pass

        def boom(_app):
            raise RuntimeError("resume failed")

        monkeypatch.setattr("pm_core.tui.auto_start.consume_breadcrumb", ok)
        monkeypatch.setattr("pm_core.tui.sync.startup_github_sync",
                            lambda app: None)
        monkeypatch.setattr("pm_core.tui.autostart_fresh.resume_pending", boom)

        asyncio.run(app._deferred_startup())

        assert app._cmd_queue_ready is True
        assert drained == [True]


class TestSignalDelivery:
    """``_signal_tui`` prefers a pidfd so a recycled PID can't be hit."""

    def test_uses_pidfd_send_signal(self, monkeypatch):
        calls = []
        monkeypatch.setattr(tpf, "open_pidfd", lambda pid: 4242)
        monkeypatch.setattr(tpf, "proc_starttime", lambda pid: 777)
        monkeypatch.setattr(signal, "pidfd_send_signal",
                            lambda fd, sig: calls.append((fd, sig)))
        monkeypatch.setattr(os, "kill",
                            lambda *a: pytest.fail("os.kill used"))

        assert helpers._signal_tui(1234, signal.SIGUSR2, 777) is None
        assert calls == [(4242, signal.SIGUSR2)]

    def test_refuses_when_pid_recycled_after_pidfd_open(self, monkeypatch):
        calls = []
        monkeypatch.setattr(tpf, "open_pidfd", lambda pid: 4242)
        monkeypatch.setattr(tpf, "proc_starttime", lambda pid: 999)
        monkeypatch.setattr(signal, "pidfd_send_signal",
                            lambda fd, sig: calls.append((fd, sig)))
        monkeypatch.setattr(os, "kill",
                            lambda *a: pytest.fail("os.kill used"))

        assert helpers._signal_tui(1234, signal.SIGUSR2, 777) == (
            "pid was reused by another process")
        assert calls == []

    def test_zombie_target_is_not_signaled(self, monkeypatch):
        """An unreaped process can't handle the signal; report it as dead."""
        proc = subprocess.Popen(["true"])
        try:
            assert _wait_for(lambda: tpf.is_zombie(proc.pid))
            monkeypatch.setattr(os, "kill",
                                lambda *a: pytest.fail("os.kill used"))
            monkeypatch.setattr(signal, "pidfd_send_signal",
                                lambda *a: pytest.fail("signal sent to zombie"))
            assert helpers._signal_tui(proc.pid, signal.SIGUSR2) == (
                "process is a zombie")
        finally:
            proc.wait(timeout=5)

    def test_falls_back_to_kill_without_pidfd(self, monkeypatch):
        killed = []
        monkeypatch.setattr(tpf, "open_pidfd", lambda pid: None)
        monkeypatch.setattr(os, "kill",
                            lambda pid, sig: killed.append((pid, sig)))

        assert helpers._signal_tui(1234, signal.SIGUSR1) is None
        assert killed == [(1234, signal.SIGUSR1)]

    def test_pidfd_send_signal_process_gone(self, monkeypatch):
        def gone(fd, sig):
            raise ProcessLookupError()

        monkeypatch.setattr(tpf, "open_pidfd", lambda pid: 4242)
        monkeypatch.setattr(signal, "pidfd_send_signal", gone)

        assert helpers._signal_tui(1234, signal.SIGUSR1) == (
            "process is not running")


# ---------------------------------------------------------------------------
# Picker / spinner


class TestPicker:
    def test_failure_message_and_no_spinner(self, monkeypatch):
        result = helpers.TuiIpcResult(
            False, "stale_pidfile",
            "The TUI for session pm-test is not running "
            "(pid belongs to a different program); restart the TUI.")
        monkeypatch.setattr(helpers, "submit_tui_command",
                            lambda session, cmd: result)
        echoed = []
        monkeypatch.setattr(sess_mod.click, "echo",
                            lambda *a, **k: echoed.append(a[0] if a else ""))
        monkeypatch.setattr(sess_mod, "_wait_dismiss", lambda *a, **k: None)
        spun = []
        monkeypatch.setattr(sess_mod, "_wait_for_tui_command",
                            lambda *a, **k: spun.append(a))

        sess_mod._run_picker_command("tui:review-loop pr-1", "pm-test")

        assert "restart the TUI" in " ".join(echoed)
        assert spun == []

    def test_spinner_aborts_when_tui_disappears(self, monkeypatch, capsys):
        read_fd, write_fd = os.pipe()
        stdin = os.fdopen(read_fd)
        monkeypatch.setattr(sys, "stdin", stdin)
        monkeypatch.setattr(sess_mod, "_TUI_GONE_GRACE_S", 0.05)
        monkeypatch.setattr(sess_mod, "_TUI_OWNER_CHECK_INTERVAL_S", 0.01)
        monkeypatch.setattr(sess_mod, "_wait_dismiss", lambda *a, **k: None)
        monkeypatch.setattr("pm_core.cli.helpers.tui_owner_problem",
                            lambda session: "process is not running")
        try:
            started = time.monotonic()
            sess_mod._wait_for_tui_command(
                SESSION, "review-loop pr-c3bf868-unittest", tick_s=0.01)
            elapsed = time.monotonic() - started
        finally:
            os.close(write_fd)
            stdin.close()
        assert elapsed < 2.0
        out = capsys.readouterr().out
        assert "no longer running" in out
        assert "may not have been applied" in out


# ---------------------------------------------------------------------------
# ``pm _tui`` launcher wiring


class TestTuiLauncher:
    """``pm _tui`` claims the pidfile before the app starts (R4/A3).

    The claim lives in the launcher (not in ``on_mount``) so a refused
    second TUI prints its message on the pane — ``pm _tui`` redirects
    stderr to ``tui-stderr.log``, where nobody would see it.
    """

    @pytest.fixture
    def launcher(self, tmp_path, monkeypatch):
        import logging
        import threading

        from pm_core.cli import tui as tui_mod

        monkeypatch.setattr(tui_mod, "debug_dir", lambda: tmp_path)
        monkeypatch.setattr("pm_core.paths.configure_logger",
                            lambda name: logging.getLogger(name))
        monkeypatch.setattr(tpf, "install_signal_guards", lambda: None)
        monkeypatch.setattr("pm_core.hook_install.ensure_hooks_installed",
                            lambda: None)
        monkeypatch.setattr("pm_core.tui.app.current_session_name",
                            lambda: SESSION)
        monkeypatch.setattr(tpf, "pidfile_path",
                            lambda session: tmp_path / "tui-pm-test.pid")

        apps: list = []

        class FakeApp:
            startup_error = None

            def __init__(self, pidfile_claim=None):
                self._pidfile_claim = pidfile_claim
                self._startup_error = type(self).startup_error
                self.ran = False
                apps.append(self)

            def run(self):
                self.ran = True

        monkeypatch.setattr("pm_core.tui.app.ProjectManagerApp", FakeApp)

        # ``tui_cmd`` rebinds sys.stderr to a file (and then to
        # sys.__stderr__) and permanently replaces threading.excepthook;
        # restore both so pytest's capture keeps working.
        orig_hook = threading.excepthook
        orig_stderr = sys.stderr
        yield tui_mod, apps, FakeApp
        threading.excepthook = orig_hook
        sys.stderr = orig_stderr

    def test_conflict_is_printed_and_exits_2(self, launcher, monkeypatch,
                                             capsys):
        tui_mod, apps, _ = launcher

        def conflict(path, session):
            raise tpf.TuiPidfileConflict(
                "another TUI (pid 7) already owns session 'pm-test' "
                "(/home/pm/.pm/tui-pm-test.pid); refusing to start a "
                "second TUI")

        monkeypatch.setattr(tpf, "claim_tui_pidfile", conflict)

        with pytest.raises(SystemExit) as exc:
            tui_mod.tui_cmd.callback()

        assert exc.value.code == 2
        assert apps == []  # never even constructed
        assert "already owns" in capsys.readouterr().out

    def test_claim_is_handed_to_the_app(self, launcher, monkeypatch):
        tui_mod, apps, _ = launcher
        claim = object()
        monkeypatch.setattr(tpf, "claim_tui_pidfile",
                            lambda path, session: claim)

        tui_mod.tui_cmd.callback()

        assert len(apps) == 1
        assert apps[0]._pidfile_claim is claim
        assert apps[0].ran

    def test_claim_io_error_still_starts_the_app(self, launcher, monkeypatch):
        tui_mod, apps, _ = launcher

        def boom(path, session):
            raise OSError("disk full")

        monkeypatch.setattr(tpf, "claim_tui_pidfile", boom)

        tui_mod.tui_cmd.callback()

        assert len(apps) == 1
        assert apps[0]._pidfile_claim is None
        assert apps[0].ran

    def test_startup_error_is_reprinted_and_exits_2(self, launcher, monkeypatch,
                                                    capsys):
        """A conflict detected inside on_mount is surfaced on the pane."""
        tui_mod, apps, FakeApp = launcher
        monkeypatch.setattr(FakeApp, "startup_error",
                            "another TUI (pid 7) already owns session")
        monkeypatch.setattr(tpf, "claim_tui_pidfile",
                            lambda path, session: object())

        with pytest.raises(SystemExit) as exc:
            tui_mod.tui_cmd.callback()

        assert exc.value.code == 2
        assert "already owns" in capsys.readouterr().out


class TestSessionName:
    """on_mount must publish to the session the launcher actually claimed."""

    def test_prefers_the_claims_session(self, monkeypatch):
        from pm_core.tui import app as app_mod

        claim = tpf.TuiPidfileClaim(
            path=Path("/tmp/tui-pm-test.pid"), session=SESSION,
            pid=os.getpid(), started_at="2026-10-27T00:00:00+00:00",
            starttime=None)

        monkeypatch.setattr(app_mod, "current_session_name",
                            lambda: "pm-renamed")
        assert app_mod._session_for_claim(claim) == SESSION
        # Without a claim (app constructed directly) tmux is the source.
        assert app_mod._session_for_claim(None) == "pm-renamed"

    def test_uses_the_pane_targeted_lookup(self, monkeypatch):
        """The pidfile key must be *our* pane's session, not tmux's client.

        ``display-message -p`` without ``-t`` resolves against the most
        recently active client, so with a second attached client the TUI
        would claim another session's pidfile and every caller looking up
        our real session would find no pidfile (IPC silently dead).
        """
        from pm_core.tui import app as app_mod

        monkeypatch.setattr(app_mod.tmux_mod, "in_tmux", lambda: True)
        monkeypatch.setattr(app_mod.tmux_mod, "get_session_name",
                            lambda: "pm-demo-c5a1006b~3")
        # The group lookup (S118) asks about that session by name, not the
        # current client.
        monkeypatch.setattr(app_mod.tmux_mod, "session_group",
                            lambda name: "")

        def _no_bare_query(*a, **k):  # pragma: no cover - must not run
            raise AssertionError("current_session_name must target the pane")

        monkeypatch.setattr(app_mod.tmux_mod, "_tmux_cmd", _no_bare_query)

        assert app_mod.current_session_name() == "pm-demo-c5a1006b"

    def test_none_outside_tmux(self, monkeypatch):
        from pm_core.tui import app as app_mod

        monkeypatch.setattr(app_mod.tmux_mod, "in_tmux", lambda: False)
        assert app_mod.current_session_name() is None

    def test_none_when_tmux_lookup_fails(self, monkeypatch):
        from pm_core.tui import app as app_mod

        def _boom():
            raise RuntimeError("no server")

        monkeypatch.setattr(app_mod.tmux_mod, "in_tmux", lambda: True)
        monkeypatch.setattr(app_mod.tmux_mod, "get_session_name", _boom)
        assert app_mod.current_session_name() is None

