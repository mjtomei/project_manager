"""Regression launch surfaces (pr-7d5d036).

A regression test runs in an isolated QA run: a fresh clone + scratch dir
made with the QA scenario helpers, inside a QA container when container mode
is enabled (fail closed), driving a disposable project built from the
project's setup recipes.  It never targets the user's pm session, and it no
longer needs one.  The TUI and ``pm qa launch`` run ``pm qa regression`` in
a pane, so all three surfaces share one launcher.  An empty library is
reported as such, never run.
"""

import asyncio
import subprocess
import threading
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

import pm_core.container as container_mod
from pm_core.cli.qa import qa as qa_group
from pm_core.regression_prompts import regression_launch_cmd


PROJECT_YAML = """\
project:
  name: demo
  repo: {repo}
  base_branch: master
  backend: local
prs: []
plans: []
"""


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    return h


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def project(tmp_path):
    """A real git repo with a pm dir, one regression test and recipes."""
    repo = tmp_path / "proj"
    pm = repo / "pm"
    (pm / "qa" / "regression").mkdir(parents=True)
    (pm / "qa" / "instructions").mkdir()
    (pm / "qa" / "artifacts").mkdir()
    (pm / "project.yaml").write_text(PROJECT_YAML.format(repo=repo))
    (pm / "qa" / "regression" / "demo.md").write_text(
        "---\ntitle: Demo flow\ndescription: d\n---\nDrive the demo flow.\n")
    (pm / "qa" / "instructions" / "setup.md").write_text(
        "---\ntitle: Throwaway project\n---\n## Setup\n")
    (pm / "qa" / "artifacts" / "cap.md").write_text(
        "---\ntitle: CLI recording\n---\n## Capture\n")
    subprocess.run(["git", "init", "-q", "-b", "master", str(repo)],
                   check=True)
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-q", "-m", "init")
    return SimpleNamespace(repo=repo, root=pm.resolve(),
                           head=_git(repo, "rev-parse", "HEAD"))


def _run_regression(project, args, *, container_enabled: bool,
                    runtime_ok: bool = True, create=None,
                    extra_patches=()):
    """Invoke ``pm qa regression`` with exec/chdir and the claude command
    builder replaced by spies.  Returns (result, spies)."""
    spies = SimpleNamespace(
        execvpe=MagicMock(),
        chdir=MagicMock(),
        build=MagicMock(return_value="CLAUDE-CMD"),
        exec_cmd=MagicMock(return_value="EXEC-CMD"),
        create=create or MagicMock(),
        remove=MagicMock(),
    )
    with ExitStack() as stack:
        stack.enter_context(patch("pm_core.cli.qa.state_root",
                                  return_value=project.root))
        # Not inside a pm tmux session: a regression run must not need one.
        stack.enter_context(patch("pm_core.qa_loop.own_session_tag",
                                  return_value=None))
        stack.enter_context(patch.object(container_mod,
                                         "is_container_mode_enabled",
                                         return_value=container_enabled))
        stack.enter_context(patch.object(
            container_mod, "_runtime_status",
            return_value=(runtime_ok, "" if runtime_ok else "runtime down")))
        stack.enter_context(patch.object(container_mod, "create_qa_container",
                                         spies.create))
        stack.enter_context(patch.object(container_mod, "remove_container",
                                         spies.remove))
        stack.enter_context(patch.object(container_mod, "build_exec_cmd",
                                         spies.exec_cmd))
        stack.enter_context(patch.object(container_mod,
                                         "load_container_config",
                                         return_value=MagicMock()))
        stack.enter_context(patch(
            "pm_core.claude_launcher.build_claude_shell_cmd", spies.build))
        stack.enter_context(patch("pm_core.cli.qa.os.execvpe",
                                  spies.execvpe))
        stack.enter_context(patch("pm_core.cli.qa.os.chdir", spies.chdir))
        for p in extra_patches:
            stack.enter_context(p)
        result = CliRunner().invoke(qa_group, ["regression", *args])
    return result, spies


def _qa_workdirs(home: Path) -> list[Path]:
    d = home / ".pm" / "workdirs" / "qa"
    return sorted(d.iterdir()) if d.is_dir() else []


def _run_captures(home: Path) -> list[Path]:
    return sorted((home / ".pm" / "sessions").rglob("prompt.md"))


def _clone_overrides(home: Path) -> list[Path]:
    """The pm_core override files written for run clones."""
    return sorted((home / ".pm" / "sessions").rglob("override"))


# ---------------------------------------------------------------------------
# pm qa regression
# ---------------------------------------------------------------------------

def test_host_run_is_isolated_and_needs_no_pm_session(project, home,
                                                      monkeypatch):
    """Container mode off: the session runs on the host in a fresh clone,
    never in the user's project, and without a pm session."""
    monkeypatch.setenv("PM_PROJECT", str(project.root))
    monkeypatch.setenv("PM_SESSION", "pm-live-session")
    # Launched from a pane of the user's live pm session (TUI Enter, pm qa
    # launch): pm in the run must not resolve that session (QA S12, R28).
    monkeypatch.setenv("TMUX", "/tmp/tmux-1000/default,123,0")
    monkeypatch.setenv("TMUX_PANE", "%7")
    monkeypatch.setenv("PM_POPUP_SESSION", "pm-live-session")
    monkeypatch.setenv("PM_IN_TMUX_SESSION", "1")
    monkeypatch.setenv("PM_TMUX_SOCKET", "/tmp/shared.sock")
    # A pm session --global session: pm in the run hashing it into session
    # tags would make the test project's pm tui view find the user's TUI
    # (QA S16, R7/R34).
    monkeypatch.setenv("PM_SHARE_MODE", "global")
    result, spies = _run_regression(project, ["demo"],
                                    container_enabled=False)
    assert result.exit_code == 0, result.output

    (workdir,) = _qa_workdirs(home)
    assert workdir.name.startswith("regression-demo-")
    clone = workdir / "s-0" / "repo"
    scratch = workdir / "s-0" / "scratch"
    # A real clone of the project's base branch at its current commit.
    assert _git(clone, "rev-parse", "HEAD") == project.head
    assert _git(clone, "rev-parse", "--abbrev-ref", "HEAD") == "master"
    # The library's recipes were copied into the scratch dir.
    assert (scratch / "qa-instructions" / "setup.md").is_file()
    assert (scratch / "qa-artifacts" / "cap.md").is_file()

    kw = spies.build.call_args.kwargs
    assert kw["cwd"] == str(clone)
    assert kw["session_type"] == "qa_regression"
    prompt = kw["prompt"]
    assert "on the host (container mode is off)" in prompt
    assert f"`{clone}`" in prompt and f"`{scratch}`" in prompt
    assert f"`{project.head[:12]}`" in prompt
    assert f"`{scratch}/qa-instructions/setup.md`: Throwaway project" in prompt
    assert f"`{scratch}/qa-artifacts/cap.md`: CLI recording" in prompt
    assert "Drive the demo flow." in prompt
    assert "pm-live-session" not in prompt
    assert "testing against tmux session" not in prompt
    assert "Filing Findings" not in prompt

    # The run's captures dir exists, outside the repo, with the prompt.
    captures = [p for p in (home / ".pm" / "sessions").rglob("prompt.md")]
    assert len(captures) == 1
    assert captures[0].parent.parent.name == "demo"
    assert captures[0].parent.parent.parent.name == "regression"
    assert captures[0].read_text() == prompt
    assert str(captures[0].parent) in prompt

    # Runs in the clone, never the user's project; pm-targeting env dropped.
    spies.chdir.assert_called_once_with(str(clone))
    args = spies.execvpe.call_args.args
    assert args[:2] == ("bash", ["bash", "-c", "CLAUDE-CMD"])
    assert "PM_PROJECT" not in args[2] and "PM_SESSION" not in args[2]
    for var in ("TMUX", "TMUX_PANE", "PM_POPUP_SESSION",
                "PM_IN_TMUX_SESSION", "PM_SHARE_MODE"):
        assert var not in args[2], var
    # Host mode still shares the user's tmux server.  With TMUX gone a
    # plain tmux command would miss it, so the prompt names the socket.
    assert args[2]["PM_TMUX_SOCKET"] == "/tmp/shared.sock"
    assert "`tmux -S /tmp/shared.sock …`" in prompt
    spies.create.assert_not_called()
    # pm run from the clone uses this pm_core, as in QA scenarios.
    (override,) = _clone_overrides(home)
    import pm_core
    assert override.read_text().strip() == str(
        Path(pm_core.__file__).parent.parent)
    # The user's project is untouched.
    assert _git(project.repo, "status", "--porcelain") == ""


def test_host_run_clone_cannot_push(project, home):
    """On the host the clone's origin is reachable with the user's
    credentials (here: the project repo itself), so the runner disables
    origin's push URL.  Fetching still works."""
    result, _ = _run_regression(project, ["demo"], container_enabled=False)
    assert result.exit_code == 0, result.output
    (workdir,) = _qa_workdirs(home)
    clone = workdir / "s-0" / "repo"
    _git(clone, "fetch", "-q", "origin")
    push = subprocess.run(
        ["git", "-C", str(clone), "push", "origin", "HEAD:refs/heads/leak"],
        capture_output=True, text=True)
    assert push.returncode != 0
    assert "regression-runs-never-push" in push.stderr
    refs = _git(project.repo, "for-each-ref", "--format=%(refname)")
    assert "refs/heads/leak" not in refs.split()


def test_host_run_files_findings_into_the_project_registry(project, home):
    result, spies = _run_regression(project, ["demo", "--file-prs"],
                                    container_enabled=False)
    assert result.exit_code == 0, result.output
    prompt = spies.build.call_args.kwargs["prompt"]
    assert f"pm -C {project.root} pr add '<title>' --plan bugs" in prompt


def test_container_run_uses_a_qa_container(project, home, monkeypatch):
    """Container mode on and healthy: the session runs inside its QA
    container via exec; no push proxy; the registry is not mounted
    unless findings are filed."""
    # The host's tmux server is not reachable from the container.
    monkeypatch.setenv("PM_TMUX_SOCKET", "/tmp/shared.sock")
    result, spies = _run_regression(project, ["demo"],
                                    container_enabled=True)
    assert result.exit_code == 0, result.output

    (workdir,) = _qa_workdirs(home)
    run_id = workdir.name.removeprefix("regression-demo-")
    kw = spies.create.call_args.kwargs
    assert kw["workdir"] == workdir / "s-0" / "repo"
    assert kw["scratch_path"] == workdir / "s-0" / "scratch"
    # Mounts only this run's captures dir, never captures/regression/.
    assert kw["pr_id"] == f"regression/demo/{run_id}"
    assert kw["allowed_push_branch"] is None
    # Not on a router: no route bridge mount.
    assert kw["route_mounts"] is None
    assert kw["extra_rw_mounts"] is None
    assert kw["extra_ro_mounts"] is None
    assert "-qa-regression-demo-" in kw["name"]

    build = spies.build.call_args.kwargs
    assert build["cwd"] == container_mod._CONTAINER_WORKDIR
    assert build["container"] is True
    prompt = build["prompt"]
    assert "inside a pm QA container" in prompt
    assert "`/scratch/qa-instructions/setup.md`" in prompt
    assert "\n    /pm-captures\n" in prompt
    assert "/pm-captures/demo" not in prompt
    assert "/tmp/shared.sock" not in prompt
    (captures,) = _run_captures(home)
    assert captures.parent.name == run_id

    exec_args = spies.exec_cmd.call_args
    assert exec_args.args[:2] == (kw["name"], "CLAUDE-CMD")
    assert exec_args.kwargs["cleanup"] is True
    assert spies.execvpe.call_args.args[1] == ["bash", "-c", "EXEC-CMD"]


def test_container_run_mounts_registry_only_for_filing(project, home):
    """Filing mounts the pm dir read-write for the registry, with every
    other entry (here the QA library) overlaid read-only."""
    result, spies = _run_regression(project, ["demo", "--file-prs"],
                                    container_enabled=True)
    assert result.exit_code == 0, result.output
    kw = spies.create.call_args.kwargs
    assert kw["extra_rw_mounts"] == {project.root: "/pm-project"}
    assert kw["extra_ro_mounts"] == {project.root / "qa": "/pm-project/qa"}
    prompt = spies.build.call_args.kwargs["prompt"]
    assert "pm -C /pm-project pr add '<title>' --plan bugs" in prompt


def _router_default(home: Path, monkeypatch, *, via_env: bool = False,
                    **entry) -> None:
    """Configure router provider r-ctr as the run's provider: the
    providers.yaml default, or (*via_env*) selected with PM_PROVIDER."""
    import yaml
    monkeypatch.delenv("PM_PROVIDER", raising=False)
    cfg = {"type": "router", "api_base": "http://127.0.0.1:18428",
           "model": "r-ctr-model", **entry}
    providers = {"providers": {"r-ctr": cfg}}
    if via_env:
        monkeypatch.setenv("PM_PROVIDER", "r-ctr")
    else:
        providers["default"] = "r-ctr"
    (home / ".pm").mkdir(exist_ok=True)
    (home / ".pm" / "providers.yaml").write_text(yaml.safe_dump(providers))


def _bridge_patches(sock: Path, ensure=None):
    """Stand in for the host route bridge at *sock*."""
    return [patch("pm_core.router_route.ensure_host_bridge",
                  ensure or MagicMock(return_value=sock)),
            patch("pm_core.route_bridge.unix_connectable",
                  return_value=True)]


@pytest.mark.parametrize("via_env", [False, True])
def test_container_run_on_a_router_mounts_the_route_bridge(
        project, home, tmp_path, monkeypatch, via_env):
    """A router default provider (or PM_PROVIDER) launches through the
    in-container bridge step, so the container gets the host bridge's
    socket dir at /run/pm-route, as a QA scenario container on the route
    does (R41).  Without it the session died at the bridge step."""
    _router_default(home, monkeypatch, via_env=via_env)
    sock = tmp_path / "route-bridge" / "r-ctr" / "router.sock"
    ensure = MagicMock(return_value=sock)
    result, spies = _run_regression(
        project, ["demo", "--file-prs"], container_enabled=True,
        extra_patches=_bridge_patches(sock, ensure))
    assert result.exit_code == 0, result.output
    assert ensure.call_args.args[0].name == "r-ctr"
    kw = spies.create.call_args.kwargs
    assert kw["route_mounts"] == {sock.parent: "/run/pm-route"}
    # Filing still mounts the registry alongside the route.
    assert kw["extra_rw_mounts"] == {project.root: "/pm-project"}
    assert spies.build.call_args.kwargs["container"] is True
    spies.execvpe.assert_called_once()


def test_faked_router_run_needs_no_route_bridge(project, home, tmp_path,
                                                monkeypatch):
    """A faked regression session has no bridge step: no host bridge is
    started and nothing is mounted for the route."""
    _router_default(home, monkeypatch)
    sock = tmp_path / "route-bridge" / "r-ctr" / "router.sock"
    ensure = MagicMock(return_value=sock)
    result, spies = _run_regression(
        project, ["demo"], container_enabled=True,
        extra_patches=[*_bridge_patches(sock, ensure),
                       patch("pm_core.paths.fake_claude_config_for_type",
                             return_value={"verdicts": ["PASS"]})])
    assert result.exit_code == 0, result.output
    ensure.assert_not_called()
    assert spies.create.call_args.kwargs["route_mounts"] is None


@pytest.mark.parametrize("problem, expect", [
    ({"model": ""}, "provider 'r-ctr': no model configured. Remedy: "),
    ({"bridge": OSError("bind failed")},
     "provider 'r-ctr': cannot set up the host route bridge: bind failed. "
     "Remedy: run 'pm provider test r-ctr --container'"),
])
def test_container_run_on_a_router_that_cannot_launch_creates_nothing(
        project, home, tmp_path, monkeypatch, problem, expect):
    """A router whose settings cannot launch, or whose host bridge cannot
    start, stops the run before any container exists (R42): the
    provider's error and remedy, exit 1, nothing left behind."""
    bridge_error = problem.pop("bridge", None)
    _router_default(home, monkeypatch, **problem)
    sock = tmp_path / "route-bridge" / "r-ctr" / "router.sock"
    ensure = MagicMock(side_effect=bridge_error, return_value=sock)
    result, spies = _run_regression(
        project, ["demo"], container_enabled=True,
        extra_patches=_bridge_patches(sock, ensure))
    assert result.exit_code == 1
    assert expect in result.output
    assert "No session was launched on the host" in result.output
    # A provider problem, not a container one: no runtime/disable advice.
    assert "provider cannot launch it" in result.output
    assert "pm container status" not in result.output
    assert "pm container disable" not in result.output
    if bridge_error is None:
        ensure.assert_not_called()
    spies.create.assert_not_called()
    # No container was named, so there is none to release.
    spies.remove.assert_not_called()
    spies.build.assert_not_called()
    spies.execvpe.assert_not_called()
    assert _qa_workdirs(home) == []
    assert _run_captures(home) == []
    assert _clone_overrides(home) == []


def test_registry_mounts_leave_only_the_registry_writable(tmp_path):
    from pm_core.regression_prompts import registry_mounts
    root = tmp_path / "pm"
    for d in ("qa/regression", "specs", "plans", ".git"):
        (root / d).mkdir(parents=True)
    for f in ("project.yaml", "project.yaml.lock", "project.yaml.tmp",
              "notes.txt"):
        (root / f).write_text("x")
    (root / "link").symlink_to(tmp_path)
    rw, ro = registry_mounts(root)
    assert rw == {root: "/pm-project"}
    assert ro == {root / n: f"/pm-project/{n}"
                  for n in (".git", "notes.txt", "plans", "qa", "specs")}


def test_recipe_copy_failure_leaves_no_run(project, home):
    """Copying the recipes happens before launch: a failure there is a run
    that never launched, so its workdir and captures are dropped."""
    result, spies = _run_regression(
        project, ["demo"], container_enabled=False,
        extra_patches=[patch("shutil.copy2",
                             side_effect=PermissionError("denied"))])
    assert result.exit_code == 1
    assert "Could not build the regression session" in result.output
    assert "denied" in result.output
    assert _qa_workdirs(home) == []
    assert _run_captures(home) == []
    assert _clone_overrides(home) == []
    spies.execvpe.assert_not_called()


def test_container_setup_failure_before_create_is_not_a_runtime_problem(
        project, home):
    """A failure before any container exists that is neither the runtime
    nor the provider (here the registry mount listing) reports the error
    without the container retry advice, releases no container and leaves
    nothing behind."""
    result, spies = _run_regression(
        project, ["demo", "--file-prs"], container_enabled=True,
        extra_patches=[patch("pm_core.regression_prompts.registry_mounts",
                             side_effect=PermissionError("pm dir denied"))])
    assert result.exit_code == 1
    assert "Could not build the regression session: pm dir denied" \
        in result.output
    assert "pm container status" not in result.output
    assert "pm container disable" not in result.output
    spies.create.assert_not_called()
    spies.remove.assert_not_called()
    spies.execvpe.assert_not_called()
    assert _qa_workdirs(home) == []
    assert _run_captures(home) == []
    assert _clone_overrides(home) == []


def test_container_run_fails_closed_when_runtime_unavailable(project, home):
    result, spies = _run_regression(project, ["demo"],
                                    container_enabled=True, runtime_ok=False)
    assert result.exit_code == 1
    assert "no agent was launched on the host" in result.output
    # Nothing was prepared and nothing ran.
    assert _qa_workdirs(home) == []
    spies.build.assert_not_called()
    spies.execvpe.assert_not_called()


def test_container_setup_failure_drops_the_mounted_captures_dir(project,
                                                               home):
    """Container creation makes the run's captures dir for its mount; a
    failure after that leaves no empty run (or test) dir behind, and keeps
    other runs' evidence."""
    from pm_core.paths import captures_dir, get_session_tag
    # The tag the runner uses outside a pm session.
    tag = get_session_tag(start_path=project.repo)
    earlier = captures_dir("regression", session_tag=tag) / "other" / "r0"
    earlier.mkdir(parents=True)
    (earlier / "manifest.md").write_text("kept")

    def create(**kw):
        captures_dir(kw["pr_id"], session_tag=kw["session_tag"]).mkdir(
            parents=True, exist_ok=True)
        return "cid"

    build = MagicMock(side_effect=RuntimeError("bridge down"))
    result, spies = _run_regression(
        project, ["demo"], container_enabled=True,
        create=MagicMock(side_effect=create),
        extra_patches=[patch("pm_core.claude_launcher.build_claude_shell_cmd",
                             build)])
    assert result.exit_code == 1
    assert "bridge down" in result.output
    regression = earlier.parent.parent
    assert not (regression / "demo").exists()
    assert (earlier / "manifest.md").read_text() == "kept"
    spies.execvpe.assert_not_called()


def test_nested_run_in_a_regression_container_gets_no_mount(tmp_path, home,
                                                            monkeypatch):
    """Inside a regression container, /pm-captures belongs to that run
    only: a nested regression run's captures fail closed instead of
    landing in the enclosing run's evidence."""
    import pm_core.paths as paths
    mount = tmp_path / "pm-captures"
    mount.mkdir()
    monkeypatch.setattr(paths, "CONTAINER_CAPTURES_MOUNT", str(mount))
    monkeypatch.setenv(paths.CAPTURES_PR_ENV, "regression/outer/r1")
    # The container's ~/.pm has no captures for the run's own key, so the
    # run itself resolves to the mount; nothing else does.
    assert paths.captures_dir("regression/outer/r1", session_tag="t") == mount
    assert paths.captures_dir("regression", session_tag="t") != mount
    assert paths.captures_dir("regression/inner/r2", session_tag="t") != mount


def test_container_create_failure_launches_nothing(project, home):
    create = MagicMock(side_effect=OSError("podman vanished"))
    result, spies = _run_regression(project, ["demo"],
                                    container_enabled=True, create=create)
    assert result.exit_code == 1
    assert "podman vanished" in result.output
    assert "regression container could not be set up" in result.output
    assert "No session was launched on the host" in result.output
    # A container problem: the runtime fix and the explicit opt-out.
    assert "pm container status" in result.output
    assert "pm container disable" in result.output
    spies.remove.assert_called_once_with(create.call_args.kwargs["name"])
    spies.build.assert_not_called()
    spies.execvpe.assert_not_called()
    # A run that never launched leaves no evidence of one: no captures dir
    # with a prompt, and this run's own workdir/clone is gone.
    assert _run_captures(home) == []
    assert _qa_workdirs(home) == []
    assert _clone_overrides(home) == []


def test_empty_library_is_reported_not_run(project, home):
    (project.root / "qa" / "regression" / "demo.md").unlink()
    result, spies = _run_regression(project, ["init-empty"],
                                    container_enabled=False)
    assert result.exit_code == 1
    assert "No regression tests in the library" in result.output
    assert _qa_workdirs(home) == []
    spies.execvpe.assert_not_called()


def test_unknown_id_with_a_library(project, home):
    result, spies = _run_regression(project, ["nope"],
                                    container_enabled=False)
    assert result.exit_code == 1
    assert "Unknown regression test: nope" in result.output
    spies.execvpe.assert_not_called()


def test_standalone_pm_repo_clones_the_code_repo(tmp_path, home):
    """A standalone pm repo (``pm init --dir``) holds only pm state: the run
    clones the code checkout project.repo names, not the pm dir's parent."""
    code = tmp_path / "app"
    code.mkdir()
    (code / "app.py").write_text("print('app')\n")
    subprocess.run(["git", "init", "-q", "-b", "master", str(code)],
                   check=True)
    _git(code, "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
    _git(code, "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-q", "-m", "app")
    pm = tmp_path / "app-pm"
    (pm / "qa" / "regression").mkdir(parents=True)
    (pm / "project.yaml").write_text(PROJECT_YAML.format(repo=code))
    (pm / "qa" / "regression" / "demo.md").write_text(
        "---\ntitle: Demo flow\n---\nDrive the demo flow.\n")
    subprocess.run(["git", "init", "-q", "-b", "master", str(pm)],
                   check=True)
    _git(pm, "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
    _git(pm, "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-q", "-m", "pm")
    standalone = SimpleNamespace(root=pm.resolve())

    result, spies = _run_regression(standalone, ["demo"],
                                    container_enabled=False)
    assert result.exit_code == 0, result.output
    (workdir,) = _qa_workdirs(home)
    clone = workdir / "s-0" / "repo"
    assert (clone / "app.py").is_file()
    assert _git(clone, "rev-parse", "HEAD") == _git(code, "rev-parse", "HEAD")


def test_missing_branch_is_a_clean_error(project, home):
    result, spies = _run_regression(project, ["demo", "--branch", "nope"],
                                    container_enabled=False)
    assert result.exit_code == 1
    assert "Could not clone 'nope'" in result.output
    spies.execvpe.assert_not_called()
    assert _qa_workdirs(home) == []
    assert _run_captures(home) == []


# ---------------------------------------------------------------------------
# pm qa launch regression:<id> / TUI launch
# ---------------------------------------------------------------------------

def _tmux_patches(split):
    return [
        patch("pm_core.tmux.has_tmux", return_value=True),
        patch("pm_core.tmux.in_tmux", return_value=True),
        patch("pm_core.tmux.get_session_name", return_value="pm-live"),
        patch("pm_core.tmux.find_window_by_name",
              return_value={"id": "@7"}),
        patch("pm_core.tmux.split_pane", split),
        patch("pm_core.tmux.new_window", MagicMock()),
    ]


def _invoke_launch(project, args, *, runtime_ok=True, container=False):
    split = MagicMock(return_value="%9")
    build = MagicMock(return_value="CLAUDE")
    with ExitStack() as stack:
        stack.enter_context(patch("pm_core.cli.qa.state_root",
                                  return_value=project.root))
        stack.enter_context(patch.object(container_mod,
                                         "is_container_mode_enabled",
                                         return_value=container))
        stack.enter_context(patch.object(
            container_mod, "_runtime_status",
            return_value=(runtime_ok, "" if runtime_ok else "runtime down")))
        stack.enter_context(patch(
            "pm_core.claude_launcher.build_claude_shell_cmd", build))
        for p in _tmux_patches(split):
            stack.enter_context(p)
        result = CliRunner().invoke(qa_group, ["launch", *args])
    return result, split, build


def test_qa_launch_runs_the_shared_regression_command(project):
    result, split, build = _invoke_launch(
        project, ["regression:demo", "--target-window", "discovery"])
    assert result.exit_code == 0, result.output
    cmd = split.call_args.args[2]
    assert cmd == regression_launch_cmd(project.root, "demo")
    assert cmd.endswith("qa regression demo --file-prs")
    assert split.call_args.kwargs["window"] == "@7"
    # No prompt aimed at the live session is built for the pane.
    build.assert_not_called()


def test_qa_launch_of_an_instruction_still_targets_this_session(
        project, monkeypatch):
    # The instruction path is unchanged: a Claude pane aimed at the session.
    monkeypatch.delenv("PM_SESSION", raising=False)
    result, split, build = _invoke_launch(
        project, ["instructions:setup", "--target-window", "discovery"])
    assert result.exit_code == 0, result.output
    prompt = build.call_args.kwargs["prompt"]
    assert "against tmux session: pm-live" in prompt
    assert "## QA Instruction: Throwaway project" in prompt
    assert build.call_args.kwargs["session_type"] == "qa_author"
    assert split.call_args.args[2] == "CLAUDE"


def test_qa_launch_reports_empty_library_before_spawning(project):
    (project.root / "qa" / "regression" / "demo.md").unlink()
    result, split, _ = _invoke_launch(project, ["regression:init-empty"])
    assert result.exit_code == 1
    assert "No regression tests in the library" in result.output
    split.assert_not_called()


def test_qa_launch_reports_unusable_runtime_before_spawning(project):
    result, split, _ = _invoke_launch(
        project, ["regression:demo", "--target-window", "discovery"],
        container=True, runtime_ok=False)
    assert result.exit_code == 1
    assert "no agent was launched on the host" in result.output
    split.assert_not_called()


def _tui_app(project):
    """A stand-in TUI app whose ``run_worker`` runs the coroutine to the
    end, the way Textual's worker would on the event loop."""
    return SimpleNamespace(
        _root=project.root, log_message=MagicMock(), _session_name="pm-live",
        run_worker=MagicMock(side_effect=lambda coro, **kw: asyncio.run(coro)))


def test_tui_regression_item_runs_the_shared_command(project):
    from pm_core.tui import pane_ops
    app = _tui_app(project)
    with patch.object(pane_ops, "launch_pane") as launch, \
            patch.object(container_mod, "is_container_mode_enabled",
                         return_value=False):
        pane_ops.launch_qa_item(app, "regression:demo", target_window="w")
    launch.assert_called_once_with(
        app, regression_launch_cmd(project.root, "demo"), "qa-item",
        target_window="w")


def test_tui_regression_check_runs_off_the_event_loop(project):
    """The pre-launch check can run ``<runtime> info`` (up to 10 s): it
    must not run on the TUI's event-loop thread."""
    from pm_core.tui import pane_ops
    app = _tui_app(project)
    seen = []

    def problem(root, test_id):
        seen.append(threading.current_thread())
        return None

    with patch.object(pane_ops, "launch_pane") as launch, \
            patch("pm_core.regression_prompts.regression_launch_problem",
                  problem):
        pane_ops.launch_qa_item(app, "regression:demo")
    assert app.run_worker.call_count == 1
    assert seen and seen[0] is not threading.main_thread()
    launch.assert_called_once()


def test_tui_regression_item_with_empty_library_logs(project):
    from pm_core.tui import pane_ops
    (project.root / "qa" / "regression" / "demo.md").unlink()
    app = _tui_app(project)
    with patch.object(pane_ops, "launch_pane") as launch:
        pane_ops.launch_qa_item(app, "regression:init-empty")
    launch.assert_not_called()
    assert "No regression tests in the library" in (
        app.log_message.call_args.args[0])


def _command_bar(project, cmd):
    """Submit *cmd* in the TUI command bar; returns (app, launch_pane,
    run_command) spies."""
    from pm_core.tui import pane_ops, pr_view
    app = MagicMock()
    app._root = project.root
    app._plans_visible = False
    app.run_worker = MagicMock(side_effect=lambda coro, **kw: asyncio.run(coro))
    with patch.object(pane_ops, "launch_pane") as launch, \
            patch.object(pr_view, "run_command") as run_cmd, \
            patch.object(container_mod, "is_container_mode_enabled",
                         return_value=False):
        pr_view.handle_command_submitted(app, cmd)
    return app, launch, run_cmd


def test_command_bar_runs_a_regression_in_a_pane(project):
    """The run is an interactive foreground session: never the command
    bar's captured 30 s subprocess, which would kill it."""
    app, launch, run_cmd = _command_bar(
        project, "qa regression --branch dev demo --file-prs")
    run_cmd.assert_not_called()
    launch.assert_called_once_with(
        app, f"pm -C {project.root} qa regression --branch dev demo "
             "--file-prs", "qa-item", target_window=None)


def test_command_bar_regression_checks_the_test_id_first(project):
    app, launch, run_cmd = _command_bar(project, "qa regression nope")
    launch.assert_not_called()
    run_cmd.assert_not_called()
    assert "Unknown regression test: nope" in (
        app.log_message.call_args.args[0])

    # Malformed commands are reported by the command's own parser, never
    # handed to a pane that would exit at once.
    for cmd, why in (
            ("qa regression --file-prs", "Missing argument 'TEST_ID'"),
            ("qa regression demo --branch", "'--branch' requires an argument"),
            ("qa regression demo --bogus", "No such option '--bogus'"),
            ("qa regression demo extra", "unexpected extra argument"),
            # No help text printed to the TUI's stdout.
            ("qa regression --help", "No such option '--help'")):
        app, launch, run_cmd = _command_bar(project, cmd)
        launch.assert_not_called()
        run_cmd.assert_not_called()
        msg = app.log_message.call_args.args[0]
        assert why in msg and "Usage: qa regression" in msg, (cmd, msg)


def test_command_bar_finds_the_test_id_after_value_options(project):
    for cmd in ("qa regression -b dev demo", "qa regression --branch=dev demo",
                "qa regression -s old demo --file-prs"):
        app, launch, _ = _command_bar(project, cmd)
        launch.assert_called_once()
        assert launch.call_args.args[1].startswith(
            f"pm -C {project.root} qa regression "), cmd


# ---------------------------------------------------------------------------
# Other surfaces
# ---------------------------------------------------------------------------

def test_standalone_refuses_regression_tests(project):
    with patch("pm_core.cli.qa.state_root", return_value=project.root):
        result = CliRunner().invoke(qa_group, ["standalone", "demo"])
    assert result.exit_code == 1
    assert "pm qa regression demo" in result.output


def test_qa_list_shows_an_empty_regression_library(project):
    (project.root / "qa" / "regression" / "demo.md").unlink()
    with patch("pm_core.cli.qa.state_root", return_value=project.root):
        result = CliRunner().invoke(qa_group, ["list"])
    assert result.exit_code == 0
    assert "Regression Tests (0):" in result.output
    assert "pm qa author-regression" in result.output
    # Retained recipes are still listed.
    assert "setup: Throwaway project" in result.output
    assert "cap: CLI recording" in result.output


def test_discovery_prompt_handles_an_empty_library():
    from pm_core.prompt_gen import generate_discovery_supervisor_prompt
    out = generate_discovery_supervisor_prompt(
        {"project": {"name": "demo"}}, session_name="pm-s")
    assert "ls pm/qa/regression/*.md 2>/dev/null" in out
    assert "regression library empty, nothing scheduled" in out
    assert "pm qa launch regression:<id> --target-window discovery" in out
    assert "isolated QA" in out
    # In-flight panes are identified by what they started, not by the
    # current command (in container mode that is the runtime's exec).
    assert "#{pane_start_command}" in out
    assert "qa regression <id>" in out
    # A pane that exits during setup (clone, container build) is not a run:
    # only a run dir with prompt.md shows the session started.
    assert ("ls -t ~/.pm/sessions/*/captures/regression/<id>/*/prompt.md"
            in out)
    assert "never as a run with no findings" in out


def test_regression_container_argv_mounts_only_scratch_captures_registry(
        tmp_path, home):
    """The real ``podman run`` argv ``create_qa_container`` builds for a
    filing regression run: clone, scratch, this run's captures dir and the
    project pm dir (rw, with its other entries ro), with no push proxy."""
    from pm_core.push_proxy import _CONTAINER_SOCKET_DIR
    from pm_core.regression_prompts import registry_mounts
    clone, scratch, registry = (tmp_path / "clone", tmp_path / "scratch",
                                tmp_path / "proj" / "pm")
    for d in (clone, scratch, registry / "specs"):
        d.mkdir(parents=True)
    (registry / "project.yaml").write_text("x")
    reg_rw, reg_ro = registry_mounts(registry)
    runtime = MagicMock(return_value=MagicMock(stdout="id\n", returncode=0))
    with patch.object(container_mod, "container_is_running",
                      return_value=False), \
            patch.object(container_mod, "_get_runtime",
                         return_value="podman"), \
            patch.object(container_mod, "image_exists", return_value=True), \
            patch.object(container_mod, "remove_container"), \
            patch.object(container_mod, "_nested_podman_enabled",
                         return_value=False), \
            patch.object(container_mod, "_run_runtime", runtime), \
            patch("pm_core.push_proxy.start_push_proxy") as proxy:
        container_mod.create_qa_container(
            name="pm-tag-qa-regression-demo-r1-s0",
            config=container_mod.ContainerConfig(),
            workdir=clone, scratch_path=scratch,
            allowed_push_branch=None, session_tag="tag",
            pr_id="regression/demo/r1",
            extra_rw_mounts=reg_rw, extra_ro_mounts=reg_ro,
        )
    args = runtime.call_args_list[0].args
    assert args[0] == "run"
    mounts = [args[i + 1] for i, a in enumerate(args) if a == "-v"]
    captures = home / ".pm" / "sessions" / "tag" / "captures" / "regression"
    assert f"{clone}:/workspace" in mounts
    assert f"{scratch}:/scratch" in mounts
    # Only this run's captures dir, created for the mount.
    assert f"{captures / 'demo' / 'r1'}:/pm-captures" in mounts
    assert (captures / "demo" / "r1").is_dir()
    assert not any(m.startswith(f"{captures}:") for m in mounts)
    assert f"{registry}:/pm-project" in mounts
    assert f"{registry / 'specs'}:/pm-project/specs:ro" in mounts
    assert not any("project.yaml" in m for m in mounts)
    assert "PM_CAPTURES_PR=regression/demo/r1" in args
    assert not any(_CONTAINER_SOCKET_DIR in m for m in mounts)
    proxy.assert_not_called()
