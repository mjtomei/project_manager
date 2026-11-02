"""Each CLI producer hands the launcher its own identity (pr-ec5bc84).

The collectors read exactly the session a launch recorded, so the producer
side must name the phase, driver run and (for review-loop attempts) the
loop, iteration, attempt and the caller's pre-generated session id.  The
sign-off launch also binds the router to the HEAD/base it reviews.  A launch
that does not open a window (an existing merge window) records nothing: an
unlaunched session would otherwise become the run's current merge session
and the live window would stop being tracked.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

import pytest

from pm_core import session_log, signoff
from pm_core.cli import pr as pr_mod
from pm_core.session_log import SessionLaunch

PR = "pr-001"
SID = "11111111-2222-4333-8444-555555555555"
HEAD = "a" * 40
BASE = "b" * 40


class _Built(Exception):
    """Raised by the stubbed launcher once the command was built."""


@pytest.fixture
def built():
    seen: list[dict] = []

    def fake_build(**kw):
        seen.append(kw)
        raise _Built()
    return seen, fake_build


@pytest.fixture
def tmux_up(monkeypatch):
    t = pr_mod.tmux_mod
    monkeypatch.setattr(t, "has_tmux", lambda: True)
    monkeypatch.setattr(t, "in_tmux", lambda: True)
    monkeypatch.setattr(t, "session_exists", lambda *a, **k: True)
    monkeypatch.setattr(pr_mod, "_get_pm_session", lambda: "pm-test")
    import pm_core.container as container_mod
    monkeypatch.setattr(container_mod, "is_container_mode_enabled",
                        lambda: False)


def _pr(tmp_path, status="in_review"):
    wd = tmp_path / "wd"
    wd.mkdir(exist_ok=True)
    return {"id": PR, "title": "T", "branch": "pm/pr-001", "status": status,
            "workdir": str(wd)}


DATA = {"project": {"name": "demo", "base_branch": "master",
                    "backend": "vanilla"}, "prs": [], "plans": []}


@pytest.mark.parametrize("kwargs, launch, sid", [
    # A review-loop attempt: the loop waits on exactly this session.
    (dict(review_loop=True, review_iteration=3, review_loop_id="abcd1234",
          run_id="autostart-x", session_id=SID, attempt=2),
     SessionLaunch(subject=PR, phase="review", run_id="autostart-x",
                   loop_id="abcd1234", iteration=3, attempt=2), SID),
    # A manual review of a TUI run: no loop, no iteration.
    (dict(run_id="manual-abc"),
     SessionLaunch(subject=PR, phase="review", run_id="manual-abc"), None),
])
def test_review_window_records_its_attempt(tmp_path, monkeypatch, tmux_up,
                                           built, kwargs, launch, sid):
    seen, fake_build = built
    monkeypatch.setattr(pr_mod.tmux_mod, "find_window_by_name",
                        lambda *a, **k: None)
    monkeypatch.setattr(pr_mod.prompt_gen, "generate_review_prompt",
                        lambda *a, **k: "prompt")
    monkeypatch.setattr(pr_mod, "build_claude_shell_cmd", fake_build)
    with pytest.raises(_Built):
        pr_mod._launch_review_window(DATA, _pr(tmp_path), fresh=True,
                                     background=True, **kwargs)
    (kw,) = seen
    assert kw["launch"] == launch
    assert kw["session_id"] == sid


def test_merge_window_records_its_run(tmp_path, monkeypatch, tmux_up, built):
    seen, fake_build = built
    monkeypatch.setattr(pr_mod.tmux_mod, "find_window_by_name",
                        lambda *a, **k: None)
    monkeypatch.setattr(pr_mod.prompt_gen, "generate_merge_prompt",
                        lambda *a, **k: "prompt")
    monkeypatch.setattr(pr_mod, "build_claude_shell_cmd", fake_build)
    with pytest.raises(_Built):
        pr_mod._launch_merge_window(DATA, _pr(tmp_path), "conflict",
                                    background=True, run_id="autostart-x")
    (kw,) = seen
    assert kw["launch"] == SessionLaunch(subject=PR, phase="merge",
                                         run_id="autostart-x")


@pytest.mark.parametrize("background", [True, False])
def test_existing_merge_window_records_no_session(tmp_path, monkeypatch,
                                                  tmux_up, background):
    """A merge window is already running: the no-op launch must not record
    a session that never runs (it would become the run's current merge
    session and the live window's MERGED would go unseen)."""
    monkeypatch.setattr(pr_mod.tmux_mod, "find_window_by_name",
                        lambda *a, **k: {"id": "@7"})
    monkeypatch.setattr(pr_mod.tmux_mod, "select_window", lambda *a: None)
    monkeypatch.setattr(pr_mod.prompt_gen, "generate_merge_prompt",
                        lambda *a, **k: "prompt")
    # The real launcher: it would append to the ledger if it ran.
    pr_mod._launch_merge_window(DATA, _pr(tmp_path), "conflict",
                                background=background, run_id="autostart-x")
    assert session_log.records(PR) == []


def test_signoff_window_binds_its_head_and_base(tmp_path, monkeypatch,
                                                tmux_up, built):
    seen, fake_build = built
    from pm_core import integration, model_config, paths
    from pm_core import claude_launcher
    from pm_core.cli import helpers
    monkeypatch.setattr(helpers, "state_root", lambda: tmp_path)
    monkeypatch.setattr(paths, "workdirs_base", lambda: tmp_path)
    monkeypatch.setattr(signoff.tmux_mod, "find_window_by_name",
                        lambda *a, **k: None)
    monkeypatch.setattr(integration, "check_integration",
                        lambda root, pr_id: {"base_sha": BASE})
    monkeypatch.setattr(integration, "summary", lambda rec: "clean")
    monkeypatch.setattr(signoff.store, "load", lambda root: DATA)
    monkeypatch.setattr(signoff, "head_sha", lambda wd: HEAD)
    monkeypatch.setattr(model_config, "resolve_model_and_provider",
                        lambda *a, **k: SimpleNamespace(
                            model=None, provider=None, effort=None))
    monkeypatch.setattr(signoff.prompt_gen, "generate_signoff_prompt",
                        lambda *a, **k: "prompt")
    monkeypatch.setattr(claude_launcher, "build_claude_shell_cmd", fake_build)
    with pytest.raises(_Built):
        signoff.launch_signoff_window(DATA, _pr(tmp_path, "sign_off"),
                                      background=True, run_id="autostart-x",
                                      session_name="pm-test")
    (kw,) = seen
    assert kw["launch"] == SessionLaunch(subject=PR, phase="signoff",
                                         run_id="autostart-x",
                                         head=HEAD, base=BASE)


def test_impl_start_records_its_run(tmp_path, monkeypatch, tmux_up):
    """``pm pr start --run-id``: the impl launch is recorded under the
    driver's run, which is how the TUI / auto-sequence recognise its pane."""
    import yaml
    from click.testing import CliRunner
    from pm_core import git_ops, store

    pm_dir = tmp_path / "pm"
    pm_dir.mkdir()
    pr = _pr(tmp_path, "in_progress")
    data = {"project": {"name": "demo", "repo": str(tmp_path),
                        "base_branch": "master", "backend": "local"},
            "prs": [pr], "plans": []}
    store.save(data, pm_dir)
    seen: list[dict] = []
    monkeypatch.setattr(pr_mod, "state_root", lambda: pm_dir)
    monkeypatch.setattr(pr_mod.tmux_mod, "find_window_by_name",
                        lambda *a, **k: None)
    monkeypatch.setattr(pr_mod.tmux_mod, "new_window", lambda *a, **k: None)
    monkeypatch.setattr(pr_mod.tmux_mod, "set_shared_window_size",
                        lambda *a, **k: None)
    monkeypatch.setattr(pr_mod, "find_claude", lambda: "/usr/bin/claude")
    monkeypatch.setattr(pr_mod, "build_claude_shell_cmd",
                        lambda **kw: seen.append(kw) or "claude-cmd")
    import pm_core.container as container_mod
    monkeypatch.setattr(container_mod, "wrap_claude_cmd",
                        lambda cmd, wd, **kw: (cmd, ""))
    yaml_dump = yaml.safe_dump(data)
    monkeypatch.setattr(git_ops, "run_git", lambda *a, **k: mock.Mock(
        returncode=0, stdout=yaml_dump if a[:1] == ("show",) else "abc12345\n",
        stderr=""))
    monkeypatch.setattr(git_ops, "is_git_repo", lambda p: False)
    monkeypatch.setattr(git_ops, "checkout_branch", lambda *a, **k: None)

    result = CliRunner().invoke(
        pr_mod.pr, ["start", PR, "--background", "--run-id", "autostart-x"])
    assert result.exit_code == 0, result.output
    (kw,) = seen
    assert kw["launch"] == SessionLaunch(subject=PR, phase="impl",
                                         run_id="autostart-x")
