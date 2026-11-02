"""The long-lived prefix+M popup (pm_core.cli.popup_shell + session wiring).

Unit tests drive the loop non-interactively with a fake dispatcher; the
pty tests run the real ``pm _popup-cmd`` against a disposable session
(temp HOME, throwaway project, private TMUX_TMPDIR) and send keystrokes:
Esc to dismiss, Up to recall, Tab to complete, PgUp for scrollback.
"""

from __future__ import annotations

import io
import os
import pty
import re
import select
import struct
import subprocess
import sys
import time
from pathlib import Path
from unittest import mock

import pytest
from click.testing import CliRunner

import pm_core
from pm_core import command_history as ch
from pm_core.cli import popup_shell, session as session_mod
from pm_core.cli.popup_shell import DispatchResult, PopupShell

REPO_ROOT = Path(pm_core.__file__).resolve().parent.parent
TAG = "demo-c5a1006b"
SESSION = f"pm-{TAG}"

PROJECT_YAML = """\
project: {name: demo, repo: %s, base_branch: master, backend: local}
plans:
- {id: plan-001, name: Alpha, status: active}
prs:
- {id: pr-0000001, title: demo PR, branch: pm/pr-0000001-demo, status: in_progress, gh_pr_number: 193}
- {id: pr-0000002, title: second, branch: pm/pr-0000002-x, status: pending, gh_pr_number: 195}
- {id: pr-abc1234, title: third, branch: pm/pr-abc1234-y, status: pending}
"""


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    return h


class FakeDispatch:
    def __init__(self, results=None):
        self.calls: list[tuple[str, list]] = []
        self.results = results or {}

    def __call__(self, cmd, parts):
        self.calls.append((cmd, parts))
        r = self.results.get(cmd, DispatchResult(output=f"ran {cmd}\n"))
        if isinstance(r, Exception):
            raise r
        return r


def _run_shell(monkeypatch, lines: str, dispatch, tag=TAG, root=None):
    monkeypatch.setattr(sys, "stdin", io.StringIO(lines))
    PopupShell(tag, root, dispatch, interactive=False).run()


# --- loop (non-interactive) --------------------------------------------------

def test_loop_runs_commands_until_eof(home, monkeypatch, capsys):
    d = FakeDispatch({"pr show x": DispatchResult(status="exit 1", output="nope\n")})
    _run_shell(monkeypatch, "pr list\n\n   \npr show x\n", d)
    assert d.calls == [("pr list", ["pr", "list"]), ("pr show x", ["pr", "show", "x"])]
    out = capsys.readouterr().out
    assert "(exit 1)" in out
    assert ch.read_history(TAG) == ["pr list", "pr show x"]
    entries = ch.read_transcript(TAG)
    assert [(e["cmd"], e["output"], e["status"]) for e in entries] == [
        ("pr list", "ran pr list\n", None), ("pr show x", "nope\n", "exit 1")]


@pytest.mark.parametrize("word", ["exit", "quit"])
def test_exit_words_close_without_dispatch_or_history(home, monkeypatch, word):
    d = FakeDispatch()
    _run_shell(monkeypatch, f"pr list\n{word}\npr never\n", d)
    assert [c for c, _ in d.calls] == ["pr list"]
    assert ch.read_history(TAG) == ["pr list"]


def test_invalid_syntax_is_recorded_not_dispatched(home, monkeypatch, capsys):
    d = FakeDispatch()
    _run_shell(monkeypatch, "pr note add pr-1 'oops\n", d)
    assert d.calls == []
    assert "Invalid command syntax" in capsys.readouterr().out
    assert ch.read_history(TAG) == ["pr note add pr-1 'oops"]
    assert ch.read_transcript(TAG)[0]["status"] == "invalid syntax"


def test_dispatch_exception_keeps_loop_alive(home, monkeypatch, capsys):
    d = FakeDispatch({"pr boom": RuntimeError("kaput")})
    _run_shell(monkeypatch, "pr boom\npr list\n", d)
    assert [c for c, _ in d.calls] == ["pr boom", "pr list"]
    assert "kaput" in capsys.readouterr().out
    assert ch.read_transcript(TAG)[0]["status"] == "error"


def test_entry_renders_prior_transcript_and_banner(home, monkeypatch, capsys):
    ch.append_transcript(ch.make_entry("pr list", "row-1\nrow-2\n"), TAG)
    ch.append_transcript(ch.make_entry("pr show x", "nope\n", "exit 1"), TAG)
    _run_shell(monkeypatch, "", FakeDispatch())
    out = capsys.readouterr().out
    assert out.index("pm> pr list") < out.index("row-2") < out.index("(exit 1)")
    assert out.index("(exit 1)") < out.index(popup_shell.BANNER)


def test_entry_shows_only_tail_that_fits(home, monkeypatch, capsys):
    ch.append_transcript(ch.make_entry("pr list", "".join(f"r{i}\n" for i in range(50))), TAG)
    monkeypatch.setattr(popup_shell.shutil, "get_terminal_size",
                        lambda fallback=None: os.terminal_size((80, 10)))
    _run_shell(monkeypatch, "", FakeDispatch())
    out = capsys.readouterr().out
    assert "r49" in out and "r40" not in out
    assert "earlier lines (PgUp to scroll back)" in out


def test_scrollback_and_clear_commands(home, monkeypatch, capsys):
    ch.append_transcript(ch.make_entry("pr list", "row-1\n"), TAG)
    d = FakeDispatch()
    _run_shell(monkeypatch, ":scrollback\n:clear\n:scrollback\n", d)
    out = capsys.readouterr().out
    assert d.calls == []
    assert "(scrollback cleared)" in out
    assert "(scrollback is empty)" in out
    assert ch.read_transcript(TAG) == []
    assert ch.read_history(TAG) == []  # popup-only commands stay out of shared history


def test_no_tag_keeps_everything_in_memory(home, monkeypatch, capsys):
    d = FakeDispatch()
    _run_shell(monkeypatch, "pr list\n:scrollback\n", d, tag=None)
    assert [c for c, _ in d.calls] == ["pr list"]
    assert "ran pr list" in capsys.readouterr().out
    assert not (home / ".pm" / "sessions").exists() or not any(
        (home / ".pm" / "sessions").rglob("command_history"))


# --- session wiring ----------------------------------------------------------------

def _fake_session(home: Path, tmp_path: Path) -> Path:
    root = tmp_path / "main"
    (root / "pm").mkdir(parents=True)
    (root / "pm_core").symlink_to(REPO_ROOT / "pm_core")
    (root / "pm" / "project.yaml").write_text(PROJECT_YAML % root)
    sd = home / ".pm" / "sessions" / TAG
    sd.mkdir(parents=True)
    (sd / "pm_root").write_text(f"{root / 'pm'}\n")
    reg = home / ".pm" / "pane-registry"
    reg.mkdir(parents=True)
    (reg / f"{SESSION}.json").write_text('{"windows": {}}')
    return root


def test_popup_cmd_keys_history_by_session_not_cwd(home, tmp_path, monkeypatch):
    """The popup's cwd (here a different git repo) must not pick the tag."""
    _fake_session(home, tmp_path)
    other = tmp_path / "workdir"
    other.mkdir()
    subprocess.run(["git", "init", "-q", str(other)], check=True)
    monkeypatch.chdir(other)
    monkeypatch.setenv("PM_POPUP_SESSION", "")
    monkeypatch.setenv("PM_PROJECT", "")
    seen = []
    monkeypatch.setattr(session_mod, "_popup_dispatch",
                        lambda s, cmd, parts: seen.append((s, cmd)) or DispatchResult())
    result = CliRunner().invoke(session_mod.popup_cmd_cmd, [f"{SESSION}~2"],
                                input="pr list\n")
    assert result.exit_code == 0, result.output
    assert seen == [(f"{SESSION}~2", "pr list")]
    assert ch.read_history(TAG) == ["pr list"]
    sessions = home / ".pm" / "sessions"
    assert [p.parent.name for p in sessions.rglob("command_history")] == [TAG]


def test_dispatch_routes_tui_commands_without_waiting(monkeypatch):
    calls = []
    monkeypatch.setattr(session_mod, "_run_picker_command",
                        lambda cmd, s, wait_on_error=True: calls.append(
                            (cmd, s, wait_on_error)) or True)
    monkeypatch.setattr(session_mod, "_run_with_abort_keys",
                        lambda *a, **k: pytest.fail("must not run directly"))
    r1 = session_mod._popup_dispatch(SESSION, "review loop start pr-1",
                                     ["review", "loop", "start", "pr-1"])
    r2 = session_mod._popup_dispatch(SESSION, "pr qa pr-1", ["pr", "qa", "pr-1"])
    assert calls == [("tui:review-loop start pr-1", SESSION, False),
                     ("tui:pr qa pr-1", SESSION, False)]
    assert r1.status == r2.status == "sent to the TUI"
    monkeypatch.setattr(session_mod, "_run_picker_command",
                        lambda cmd, s, wait_on_error=True: False)
    assert session_mod._popup_dispatch(SESSION, "pr qa", ["pr", "qa"]).status == (
        "TUI not reached")


@pytest.mark.parametrize("rc,status", [
    (0, None), (2, "exit 2"), (session_mod._ABORTED_BY_USER, "aborted")])
def test_dispatch_direct_runs_session_pm_with_capture(monkeypatch, rc, status):
    seen = {}

    def fake_run(cmd, capture=None):
        seen["cmd"] = cmd
        capture.extend([b"hello \xe2\x9c", b"\x93\r\n"])
        return rc
    monkeypatch.setattr(session_mod, "_run_with_abort_keys", fake_run)
    r = session_mod._popup_dispatch(SESSION, "pr list", ["pr", "list"])
    assert seen["cmd"] == session_mod._session_pm_argv(SESSION, ["pr", "list"])
    assert r.status == status
    assert r.output == "hello ✓\r\n"


def test_picker_command_wait_on_error_flag(monkeypatch):
    waits = []
    monkeypatch.setattr(session_mod, "_wait_dismiss", lambda *a: waits.append(1))
    failed = subprocess.CompletedProcess([], 1, stdout="", stderr="boom")
    with mock.patch.object(session_mod.subprocess, "run", return_value=failed):
        assert session_mod._run_picker_command("pr x", SESSION, wait_on_error=False) is False
        assert waits == []
        assert session_mod._run_picker_command("pr x", SESSION) is False
        assert waits == [1]
    ok = subprocess.CompletedProcess([], 0, stdout="fine\n", stderr="")
    with mock.patch.object(session_mod.subprocess, "run", return_value=ok):
        assert session_mod._run_picker_command("pr x", SESSION) is True


# --- pty: output capture --------------------------------------------------------------

def _spawn(argv, env, cwd=None, rows=24, cols=100):
    pid, fd = pty.fork()
    if pid == 0:
        try:
            import fcntl
            import termios
            fcntl.ioctl(0, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
            if cwd:
                os.chdir(cwd)
            os.execve(argv[0], argv, env)
        finally:
            os._exit(127)
    return Term(pid, fd)


class Term:
    def __init__(self, pid, fd):
        self.pid, self.fd, self.out = pid, fd, b""
        self.status = None

    def pump(self, t=0.2):
        end = time.monotonic() + t
        while time.monotonic() < end:
            r, _, _ = select.select([self.fd], [], [], 0.05)
            if r:
                try:
                    data = os.read(self.fd, 65536)
                except OSError:
                    return False
                if not data:
                    return False
                self.out += data
        return True

    def text(self):
        return self.out.decode("utf-8", "replace")

    def wait_for(self, pattern, timeout=15):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if re.search(pattern, self.text()):
                return True
            if not self.pump(0.1):
                break
        return bool(re.search(pattern, self.text()))

    def send(self, data, settle=0.3):
        os.write(self.fd, data)
        self.pump(settle)

    def wait_exit(self, timeout=10):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            pid, st = os.waitpid(self.pid, os.WNOHANG)
            if pid:
                self.status = os.waitstatus_to_exitcode(st)
                return self.status
            self.pump(0.1)
        return None

    def close(self):
        if self.status is None:
            try:
                os.kill(self.pid, 9)
                os.waitpid(self.pid, 0)
            except (ProcessLookupError, ChildProcessError):
                pass
        try:
            os.close(self.fd)
        except OSError:
            pass


def _env(home: Path, tmp_path: Path) -> dict:
    env = {k: v for k, v in os.environ.items()
           if k not in ("TMUX", "TMUX_PANE", "PM_PROJECT", "PM_POPUP_SESSION")}
    tmux_dir = tmp_path / "tmux"
    tmux_dir.mkdir(exist_ok=True)
    env.update(HOME=str(home), TERM="xterm-256color", TMUX_TMPDIR=str(tmux_dir),
               PYTHONPATH=str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", ""))
    return env


CAPTURE_HARNESS = (
    "import sys;"
    "from pm_core.cli.session import _run_with_abort_keys, _ABORTED_BY_USER;"
    "cap = [];"
    "rc = _run_with_abort_keys([sys.executable, '-c', sys.argv[1]], capture=cap);"
    "data = b''.join(cap).decode();"
    "print('RC=' + ('ABORT' if rc == _ABORTED_BY_USER else str(rc)));"
    "print('CAPTURED=' + repr(data));"
    "import os; print('TTY=' + str(os.isatty(1)))"
)


def test_capture_relays_and_records_child_output(home, tmp_path):
    child = ("import sys, os; print('out-line'); "
             "print('err-line', file=sys.stderr); "
             "print('child-tty=' + str(os.isatty(1))); sys.exit(3)")
    t = _spawn([sys.executable, "-c", CAPTURE_HARNESS, child], _env(home, tmp_path))
    try:
        assert t.wait_exit(20) == 0, t.text()
        t.pump(0.2)
        text = t.text()
        assert "RC=3" in text
        captured = re.search(r"CAPTURED=(.*)", text).group(1)
        assert "out-line" in captured and "err-line" in captured
        assert "child-tty=True" in captured  # the child still sees a terminal
        # Relayed live, before the harness printed its summary.
        assert text.index("out-line") < text.index("RC=3")
    finally:
        t.close()


def test_capture_abort_keeps_partial_output(home, tmp_path):
    child = ("import sys, time; print('ready', flush=True); time.sleep(60)")
    t = _spawn([sys.executable, "-c", CAPTURE_HARNESS, child], _env(home, tmp_path))
    try:
        assert t.wait_for("ready"), t.text()
        t.send(b"\x1b", 0.1)
        assert t.wait_exit(20) == 0, t.text()
        t.pump(0.2)
        assert "RC=ABORT" in t.text()
        assert "ready" in re.search(r"CAPTURED=(.*)", t.text()).group(1)
    finally:
        t.close()


# --- pty: the real popup ------------------------------------------------------------

POPUP_HARNESS = (
    "import sys;"
    "import pm_core.cli.popup_shell as ps;"
    "ps._find_less = lambda: None;"  # exercise the built-in pager
    "from pm_core.cli import cli;"
    f"sys.argv = ['pm', '_popup-cmd', {SESSION!r}];"
    "cli()"
)


@pytest.fixture
def popup(home, tmp_path):
    root = _fake_session(home, tmp_path)
    terms = []

    def start(rows=24):
        t = _spawn([sys.executable, "-c", POPUP_HARNESS], _env(home, tmp_path),
                   cwd=str(root), rows=rows)
        terms.append(t)
        assert t.wait_for(r"Esc/Ctrl-D close[\s\S]*pm> $", 30), t.text()
        return t
    yield start
    for t in terms:
        t.close()


def test_popup_runs_commands_and_closes_on_lone_esc(popup, home):
    t = popup()
    t.send(b"pr list\r", 0.1)
    assert t.wait_for(r"pr-abc1234[\s\S]*pm> $", 30), t.text()
    t.send(b"pr show nope\r", 0.1)
    assert t.wait_for(r"\(exit 1\)[\s\S]*pm> $", 30), t.text()
    t.send(b"\x1b", 0.1)  # a single Esc at the prompt
    assert t.wait_exit(10) == 0, t.text()
    assert ch.read_history(TAG) == ["pr list", "pr show nope"]
    entries = ch.read_transcript(TAG)
    assert [e["cmd"] for e in entries] == ["pr list", "pr show nope"]
    assert "pr-abc1234" in entries[0]["output"]
    assert entries[1]["status"] == "exit 1"


def test_popup_reopen_recalls_shared_history_and_scrollback(popup, home):
    ch.append_history("pr show pr-0000001", TAG)   # typed in the popup earlier
    ch.append_transcript(ch.make_entry("pr show pr-0000001", "Title: demo PR\n"), TAG)
    ch.append_history("plan list", TAG)            # typed in the TUI bar
    t = popup()
    assert "Title: demo PR" in t.text()             # prior buffer on entry
    t.send(b"\x1b[A", 0.4)
    assert t.text().endswith("plan list"), repr(t.text()[-60:])
    t.send(b"\x1b[A", 0.4)                          # older entry
    t.send(b"\x1b[B", 0.4)                          # back down
    t.send(b"\x1b[A", 0.4)
    t.out = b""
    t.send(b"\r", 0.1)                              # re-run the recalled command
    assert t.wait_for(r"Title: demo PR[\s\S]*pm> $", 30), t.text()
    assert ch.read_history(TAG)[-1] == "pr show pr-0000001"
    assert [e["cmd"] for e in ch.read_transcript(TAG)][-1] == "pr show pr-0000001"
    t.send(b"\x04", 0.1)                            # Ctrl-D on an empty line closes
    assert t.wait_exit(10) == 0


def test_popup_tab_completes_pr_ids(popup):
    t = popup()
    t.send(b"pr edit ", 0.2)
    t.out = b""
    t.send(b"\t", 0.6)
    listing = t.text()
    for word in ("#193", "#195", "pr-0000001", "pr-abc1234"):
        assert word in listing, listing
    t.send(b"\x05\x15pr show #19\t", 0.6)
    assert re.search(r"#193\s+#195", t.text()), t.text()
    t.send(b"\t", 0.4)  # second Tab cycles to the first candidate
    t.send(b"\r", 0.1)
    assert t.wait_for(r"Title: demo PR[\s\S]*pm> $", 30), t.text()


def test_popup_pgup_pages_scrollback_and_restores_typed_text(popup, home):
    ch.append_transcript(
        ch.make_entry("pr list", "".join(f"row-{i:02d}\n" for i in range(40))), TAG)
    t = popup(rows=12)
    assert "row-39" in t.text() and "row-05" not in t.text()
    t.send(b"pr show pr-abc", 0.2)
    t.out = b""
    t.send(b"\x1b[5~", 0.8)                 # PgUp at the prompt
    assert t.wait_for(r"scrollback \d+-\d+/\d+", 10), t.text()
    t.out = b""
    t.send(b"g", 0.5)                       # top of the buffer
    assert "row-00" in t.text(), t.text()
    t.send(b"q", 0.8)                       # back to the prompt
    assert t.wait_for(r"pm> pr show pr-abc$", 10), repr(t.text()[-80:])
    t.send(b"1234\r", 0.1)
    assert t.wait_for(r"Title: third[\s\S]*pm> $", 30), t.text()


def test_popup_ctrl_c_at_prompt_keeps_popup_open(popup):
    t = popup()
    t.send(b"half typed\x03", 0.4)
    assert t.wait_for(r"\^C\r?\npm> $", 5), repr(t.text()[-40:])
    t.send(b"exit\r", 0.1)
    assert t.wait_exit(10) == 0
