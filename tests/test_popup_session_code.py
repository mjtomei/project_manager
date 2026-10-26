"""Popup-dispatched pm commands run the tmux session's pm_core.

The prefix+P picker (direct route) and the prefix+M runner spawn their
child pm command in the popup's cwd, which is often a PR workdir clone
whose pm_core differs from the session's.  The child must run the
session's code (resolved from ~/.pm/sessions/<tag>/pm_root), never the
workdir's — while the same command typed in a shell in that workdir
still cwd-walks to the workdir's pm_core.
"""

import subprocess
import sys
from pathlib import Path

from click.testing import CliRunner

import pm_core
from pm_core.cli.session import _run_picker_command, popup_cmd_cmd

REPO_ROOT = Path(pm_core.__file__).resolve().parent.parent
TAG = "demo-c5a1006b"
SESSION = f"pm-{TAG}"

DECOY_WRAPPER = (
    "import sys\n"
    "def main():\n"
    "    print('DECOY-WRAPPER ran')\n"
    "    return 0\n"
    "if __name__ == '__main__':\n"
    "    sys.exit(main())\n"
)
DECOY_CLI = (
    "def main():\n"
    "    print('DECOY-CLI ran')\n"
    "    return 0\n"
)


def _setup(tmp_path, monkeypatch):
    """Fake pm session + a PR-workdir decoy; chdir into the decoy."""
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("TMUX", raising=False)
    # popup_cmd_cmd exports PM_POPUP_SESSION; setenv so it is removed after.
    monkeypatch.setenv("PM_POPUP_SESSION", "")

    # Session root: <root>/pm is pm_root, <root>/pm_core is the session's
    # code (a symlink to the code under test).
    session_root = tmp_path / "main"
    (session_root / "pm").mkdir(parents=True)
    (session_root / "pm_core").symlink_to(REPO_ROOT / "pm_core")
    (session_root / "pm" / "project.yaml").write_text(
        "project: {name: demo, repo: %s, base_branch: master, backend: local}\n"
        "prs:\n"
        "- {id: pr-0000001, title: demo PR, branch: pm/pr-0000001-demo, "
        "status: in_progress}\n" % session_root
    )
    sd = home / ".pm" / "sessions" / TAG
    sd.mkdir(parents=True)
    (sd / "pm_root").write_text(f"{session_root / 'pm'}\n")
    reg = home / ".pm" / "pane-registry"
    reg.mkdir(parents=True)
    (reg / f"{SESSION}.json").write_text('{"windows": {}}')

    # Decoy PR workdir: its own git repo (so it hashes to a different
    # session tag) carrying a pm_core that announces itself.
    workdir = tmp_path / "workdir"
    (workdir / "pm_core" / "cli").mkdir(parents=True)
    (workdir / "pm_core" / "__init__.py").write_text("")
    (workdir / "pm_core" / "wrapper.py").write_text(DECOY_WRAPPER)
    (workdir / "pm_core" / "cli" / "__init__.py").write_text(DECOY_CLI)
    subprocess.run(["git", "init", "-q", str(workdir)], check=True)

    monkeypatch.setenv("PM_PROJECT", str(session_root / "pm"))
    monkeypatch.chdir(workdir)
    return home, session_root


def _wrapper_log(home: Path) -> str:
    return "".join(p.read_text() for p in (home / ".pm" / "debug").glob("*.log"))


def test_picker_direct_route_runs_session_code(tmp_path, monkeypatch, capsys):
    home, session_root = _setup(tmp_path, monkeypatch)

    _run_picker_command("pr list", SESSION)

    out = capsys.readouterr()
    assert "DECOY" not in out.out + out.err
    assert "pr-0000001" in out.out
    log = _wrapper_log(home)
    assert f"selected_root={session_root} chosen_via=pm_root" in log
    assert f"session_tag={TAG}" in log


def test_popup_cmd_runs_session_code(tmp_path, monkeypatch, capfd):
    home, session_root = _setup(tmp_path, monkeypatch)

    result = CliRunner().invoke(popup_cmd_cmd, [SESSION], input="pr list\n")

    assert result.exit_code == 0, result.output
    # The child inherits the real fds (non-tty path of _run_with_abort_keys).
    out = capfd.readouterr()
    assert "DECOY" not in out.out + out.err + result.output
    assert "pr-0000001" in out.out
    assert f"selected_root={session_root} chosen_via=pm_root" in _wrapper_log(home)


def test_popup_config_uses_base_session_not_workdir(tmp_path, monkeypatch, capfd):
    import json

    home, _ = _setup(tmp_path, monkeypatch)
    monkeypatch.setenv("TMUX", "isolated-test-server,1,0")
    config = {"_all": {}, "impl": {"display_bullet": "SESSION-IMPL "}}
    (home / ".pm" / "sessions" / TAG / "fake-claude").write_text(json.dumps(config))

    for session in (SESSION, f"{SESSION}~s19b"):
        result = CliRunner().invoke(popup_cmd_cmd, [session],
                                    input="fake-claude config show\n")
        assert result.exit_code == 0, result.output
        out = capfd.readouterr()
        assert '"display_bullet": "SESSION-IMPL "' in out.out
        assert "No fake-claude config" not in out.out


def test_direct_shell_invocation_still_cwd_walks(tmp_path, monkeypatch):
    """Control: plain wrapper.main from the workdir keeps cwd_walk."""
    home, _ = _setup(tmp_path, monkeypatch)

    code = (
        "import sys; sys.path.insert(0, %r); sys.argv = ['pm', 'pr', 'list'];"
        "from pm_core.wrapper import main; sys.exit(main())" % str(REPO_ROOT)
    )
    r = subprocess.run([sys.executable, "-c", code],
                       capture_output=True, text=True)

    assert "DECOY-CLI ran" in r.stdout, r.stderr
    assert "chosen_via=cwd_walk" in _wrapper_log(home)


def _fake_pm_source(root: Path) -> Path:
    (root / "pm_core" / "cli").mkdir(parents=True)
    return root


def _resolve_for_session(monkeypatch, tag):
    """Run wrapper.main_for_session(tag) with _run_cli stubbed out."""
    from pm_core import wrapper
    seen = {}
    monkeypatch.setattr(wrapper, "_run_cli",
                        lambda root, front=False: seen.update(root=root, front=front) or 0)
    wrapper.main_for_session(tag)
    return seen


def test_main_for_session_override_beats_pm_root(tmp_path, monkeypatch):
    home, session_root = _setup(tmp_path, monkeypatch)
    meta = _fake_pm_source(tmp_path / "meta")
    (home / ".pm" / "sessions" / TAG / "override").write_text(f"{meta}\n")

    assert _resolve_for_session(monkeypatch, TAG) == {"root": str(meta), "front": True}


def test_main_for_session_never_cwd_walks(tmp_path, monkeypatch):
    """No override/pm_root for the tag (or no tag at all): keep the
    dispatcher's code rather than falling back to the cwd's pm_core."""
    home, _ = _setup(tmp_path, monkeypatch)
    (home / ".pm" / "sessions" / TAG / "pm_root").unlink()

    for tag in (TAG, ""):
        assert _resolve_for_session(monkeypatch, tag)["root"] is None


def test_session_pm_argv_tag_from_grouped_session():
    from pm_core.cli.session import _session_pm_argv
    argv = _session_pm_argv(f"{SESSION}~2", ["pr", "list"])
    assert argv[1] == "-c"
    # The dispatcher's import root as loaded (not resolved through symlinks).
    assert argv[3:] == [str(Path(pm_core.__file__).parent.parent), TAG,
                        "pr", "list"]
    assert _session_pm_argv("not-a-pm-session", [])[4] == ""
