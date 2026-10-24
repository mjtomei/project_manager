"""Tests for pr-7f90572: meta window override cleanup.

The ``pm meta`` pane command must clear the session override via a shell
trap (so ``tmux kill-window`` / SIGHUP also cleans up, not just a normal
Claude exit), and must remove only the override file it owns — never the
whole shared session dir (``rm -rf ~/.pm/sessions/<tag>`` deleted
fake-claude config, debug markers and captures/ evidence on normal exit).
"""

import os
import pathlib
import signal
import subprocess
import time

import pytest

from pm_core.cli.meta import _build_meta_pane_cmd
from pm_core.shell import shell_quote

TAG = "repro-tag"
META_WORKDIR = "/tmp/fake-meta-workdir"


def _seed_session_dir(home: pathlib.Path) -> dict:
    """Seed a shared session dir the way real sessions look."""
    sd = home / ".pm" / "sessions" / TAG
    (sd / "captures" / "pr-999999").mkdir(parents=True, exist_ok=True)
    (sd / "override").write_text(META_WORKDIR + "\n")
    (sd / "debug").write_text("true\n")
    (sd / "fake-claude").write_text('{"script": "x"}\n')
    (sd / "captures" / "pr-999999" / "NOTE.md").write_text("qa evidence\n")
    return {
        "override": sd / "override",
        "debug": sd / "debug",
        "fake-claude": sd / "fake-claude",
        "captures": sd / "captures",
    }


@pytest.fixture
def pane_cmd(tmp_path, monkeypatch):
    """Build the meta pane command with HOME pointed at a temp dir."""
    monkeypatch.setenv("HOME", str(tmp_path))
    built = _build_meta_pane_cmd("true", TAG, pathlib.Path(META_WORKDIR))
    # Keep HOME for the subprocess too: the built command uses absolute
    # paths, but tests below reseed the session dir per case.
    return built, tmp_path


def test_cmd_has_trap_covering_hup(pane_cmd):
    built, _ = pane_cmd
    assert "trap pm_meta_clear_override EXIT HUP INT TERM" in built


def test_cmd_removes_only_override_file(pane_cmd):
    built, home = pane_cmd
    # Targeted rm -f of the override file, with ownership guard
    override_q = shell_quote(str(home / ".pm" / "sessions" / TAG / "override"))
    assert f"rm -f {override_q}" in built
    # Guard compares content to this meta workdir
    assert shell_quote(META_WORKDIR) in built
    # Never wipes the shared session dir
    assert "rm -rf" not in built


def test_normal_exit_removes_only_override(pane_cmd):
    built, home = pane_cmd
    state = _seed_session_dir(home)
    subprocess.run(["/bin/sh", "-c", built], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    assert not state["override"].exists()
    assert state["debug"].exists()
    assert state["fake-claude"].exists()
    assert state["captures"].exists()
    assert (state["captures"] / "pr-999999" / "NOTE.md").exists()


def test_kill_window_sighup_removes_override(pane_cmd):
    _, home = pane_cmd
    state = _seed_session_dir(home)
    # Fake claude that stays alive until the "kill-window" HUP arrives.
    # Build the command directly rather than .replace()ing the fixture's
    # claude_cmd: "true" also occurs in the handler's `|| true`, so a
    # positional replace would rewrite the handler body instead.
    cmd = _build_meta_pane_cmd("sleep 60", TAG, pathlib.Path(META_WORKDIR))
    proc = subprocess.Popen(
        ["/bin/sh", "-c", cmd], start_new_session=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.5)
    # Pane genuinely mid-flight: nothing has cleaned up yet
    assert state["override"].exists()
    # tmux kill-window: SIGHUP to the pane's process group (shell + claude)
    os.killpg(proc.pid, signal.SIGHUP)
    proc.wait(timeout=15)
    assert not state["override"].exists()
    assert state["debug"].exists()
    assert state["fake-claude"].exists()
    assert state["captures"].exists()


def test_foreign_override_survives_cleanup(pane_cmd):
    built, home = pane_cmd
    state = _seed_session_dir(home)
    # qa_loop._setup_clone_override points the override at another workdir
    state["override"].write_text("/tmp/other-clone-root\n")
    subprocess.run(["/bin/sh", "-c", built], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    assert state["override"].exists()
    assert state["override"].read_text().strip() == "/tmp/other-clone-root"


def test_missing_override_is_noop(pane_cmd):
    built, home = pane_cmd
    subprocess.run(["/bin/sh", "-c", built], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    assert not (home / ".pm" / "sessions" / TAG).exists() or \
        not (home / ".pm" / "sessions" / TAG / "override").exists()
