"""End-to-end tests for the in-container git wrapper + host push proxy.

Regression for the 2026-10-27 incident: a review subagent ran ``git push
origin --mir`` in a throwaway repo under a temp dir; the container's git
wrapper forwarded it to the host proxy regardless of cwd, and the proxy
(which only matched the exact spelling ``--mirror``) replayed it in the PR
workdir against GitHub — force-rewinding master and deleting branches.

Everything here is sandboxed: the wrapper is generated from the source tree
pointing at a temp socket and a stand-in workdir, ``PushProxy`` runs
in-process from the source tree, and every remote is a local bare repo.
The real git binary is forced first on PATH so neither the test nor the
proxy can reach an installed ``~/.local/bin/git`` wrapper (and through it the
live host proxy).
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from pm_core.container import _build_git_wrapper_script
from pm_core.push_proxy import PushProxy

ALLOWED = "pm/pr-x"

# The commands the incident subagent ran (transcript 14a2d740 /
# agent-a42e1db1aa3bd6a93, 2026-10-27T16:15:30Z), in order.
INCIDENT_COMMANDS = [
    ["push", "origin", "--mir"],
    ["push", "origin", "--branches"],
    ["push", "origin", "--a"],
    ["fetch", "--upl=/bin/false", "origin"],
]

# Other spellings git resolves to a broad push.
BROAD_SPELLINGS = ["--mirror", "--mirr", "--mirror=1", "--all", "--al",
                   "--br", "--tags", "--ta"]


def _find_real_git() -> str | None:
    """First ``git`` on PATH that is a binary, not a (pm) shell wrapper."""
    for d in os.environ.get("PATH", "").split(os.pathsep) + ["/usr/bin"]:
        cand = Path(d) / "git"
        try:
            with open(cand, "rb") as f:
                if f.read(2) != b"#!":
                    return str(cand)
        except OSError:
            continue
    return None


REAL_GIT = _find_real_git()
pytestmark = pytest.mark.skipif(REAL_GIT is None, reason="no real git binary")


@pytest.fixture(autouse=True)
def _real_git_env(tmp_path, monkeypatch):
    """Real git first on PATH and an isolated HOME for every git process."""
    bindir = tmp_path / "realbin"
    bindir.mkdir()
    (bindir / "git").symlink_to(REAL_GIT)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}/usr/bin{os.pathsep}/bin")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR"):
        monkeypatch.delenv(k, raising=False)
    for k, v in (("GIT_AUTHOR_NAME", "t"), ("GIT_AUTHOR_EMAIL", "t@t"),
                 ("GIT_COMMITTER_NAME", "t"), ("GIT_COMMITTER_EMAIL", "t@t")):
        monkeypatch.setenv(k, v)
    resolved = shutil.which("git")
    assert resolved and Path(resolved).read_bytes()[:2] != b"#!", (
        f"git on PATH is a wrapper ({resolved}); refusing to run")


def _git(*args, cwd=None, check=True) -> str:
    return subprocess.run([REAL_GIT, *args], cwd=cwd, check=check,
                          capture_output=True, text=True).stdout.strip()


def _refs(repo: Path) -> dict[str, str]:
    out = _git("-C", str(repo), "for-each-ref",
               "--format=%(refname) %(objectname)")
    return dict(line.split(" ", 1) for line in out.splitlines())


@pytest.fixture
def sandbox(tmp_path):
    """Stand-in "GitHub" remote, "/workspace" clone, and an unrelated scratch repo.

    - ``remote``: bare, with master, two other PR branches and a tag.  The
      workspace addresses it as ``file://`` so the proxy treats it like a
      real upstream (a plain local path is refused by the proxy).
    - ``workspace``: on the allowed branch with two unpushed commits; its
      local master is behind the remote's (a mirror push would rewind it).
    - ``scratch``: the incident's throwaway layout — ``work`` with branches
      b1/b2 and ``origin`` = local bare ``remote.git``.
    """
    remote = tmp_path / "remote.git"
    _git("init", "-q", "--bare", "-b", "master", str(remote))
    seed = tmp_path / "seed"
    _git("clone", "-q", str(remote), str(seed))
    _git("commit", "-q", "--allow-empty", "-m", "base", cwd=seed)
    _git("push", "-q", "origin", "master", "master:pm/pr-a",
         "master:pm/pr-b", cwd=seed)
    _git("tag", "v1", cwd=seed)
    _git("push", "-q", "origin", "v1", cwd=seed)
    _git("commit", "-q", "--allow-empty", "-m", "upstream-ahead", cwd=seed)
    _git("push", "-q", "origin", "master", cwd=seed)

    ws = tmp_path / "workspace"
    _git("clone", "-q", f"file://{remote}", str(ws))
    _git("checkout", "-q", "-b", ALLOWED, "HEAD~1", cwd=ws)
    _git("commit", "-q", "--allow-empty", "-m", "unpushed 1", cwd=ws)
    _git("commit", "-q", "--allow-empty", "-m", "unpushed 2", cwd=ws)
    _git("branch", "-f", "master", "HEAD~2", cwd=ws)

    scratch_remote = tmp_path / "scratch" / "remote.git"
    _git("init", "-q", "--bare", "-b", "master", str(scratch_remote))
    scratch = tmp_path / "scratch" / "work"
    _git("init", "-q", "-b", "master", str(scratch))
    _git("commit", "-q", "--allow-empty", "-m", "one", cwd=scratch)
    _git("branch", "b1", cwd=scratch)
    _git("branch", "b2", cwd=scratch)
    _git("remote", "add", "origin", str(scratch_remote), cwd=scratch)

    # Unix socket paths are length-limited; tmp_path can be too long.
    sock_dir = tempfile.mkdtemp(prefix="gpx-", dir="/tmp")
    sock = os.path.join(sock_dir, "push.sock")
    proxy = PushProxy(sock, str(ws), ALLOWED)
    calls: list[int] = []
    handle = proxy._handle_connection

    def _recording_handle(conn):
        calls.append(1)
        return handle(conn)

    proxy._handle_connection = _recording_handle
    proxy.start()

    wrapper = tmp_path / "wrapperbin" / "git"
    wrapper.parent.mkdir()
    wrapper.write_text(_build_git_wrapper_script(
        str(ws), socket_path=sock, container_workdir=str(ws),
        real_git=REAL_GIT))
    wrapper.chmod(0o755)

    def run(*args, cwd, env=None):
        return subprocess.run([str(wrapper), *args], cwd=cwd,
                              capture_output=True, text=True, timeout=60,
                              env={**os.environ, **(env or {})})

    yield {"remote": remote, "ws": ws, "scratch": scratch,
           "scratch_remote": scratch_remote, "run": run, "calls": calls}
    proxy.stop()
    shutil.rmtree(sock_dir, ignore_errors=True)


def _assert_only_allowed_changed(before: dict, after: dict) -> None:
    key = f"refs/heads/{ALLOWED}"
    strip = lambda refs: {k: v for k, v in refs.items() if k != key}  # noqa: E731
    assert strip(after) == strip(before), (
        f"remote refs other than {key} changed:\n"
        f"before={strip(before)}\nafter={strip(after)}")


class TestIncidentReplay:
    def test_incident_commands_from_scratch_repo_leave_remote_untouched(
            self, sandbox):
        """The incident as it happened: issued from a throwaway repo."""
        before = _refs(sandbox["remote"])
        for cmd in INCIDENT_COMMANDS:
            sandbox["run"](*cmd, cwd=sandbox["scratch"])
            assert _refs(sandbox["remote"]) == before, (
                f"`git {' '.join(cmd)}` in a scratch repo changed the "
                "workspace's remote")
        assert sandbox["calls"] == [], "scratch-repo commands reached the proxy"

    @pytest.mark.parametrize("cmd", INCIDENT_COMMANDS + [
        ["push", "origin", flag] for flag in BROAD_SPELLINGS])
    def test_incident_commands_from_workspace_rejected_by_proxy(
            self, cmd, sandbox):
        """Same commands issued where they *are* forwarded: the proxy refuses."""
        before = _refs(sandbox["remote"])
        r = sandbox["run"](*cmd, cwd=sandbox["ws"])
        assert sandbox["calls"], "workspace command should reach the proxy"
        if cmd[0] == "push":
            assert r.returncode != 0
            assert "rejected" in r.stderr
        _assert_only_allowed_changed(before, _refs(sandbox["remote"]))

    def test_allowed_branch_push_still_lands(self, sandbox):
        """Positive control: the snapshot check sees a real allowed push."""
        before = _refs(sandbox["remote"])
        r = sandbox["run"]("push", "origin", ALLOWED, cwd=sandbox["ws"])
        assert r.returncode == 0, r.stderr
        after = _refs(sandbox["remote"])
        assert after[f"refs/heads/{ALLOWED}"] == _git(
            "-C", str(sandbox["ws"]), "rev-parse", "HEAD")
        _assert_only_allowed_changed(before, after)
        assert len(sandbox["calls"]) == 1


class TestWrapperRepositoryScope:
    def test_scratch_repo_remote_commands_use_its_own_remote(self, sandbox):
        run, scratch, ws = sandbox["run"], sandbox["scratch"], sandbox["ws"]
        remote_before = _refs(sandbox["remote"])
        ws_head = _git("-C", str(ws), "rev-parse", "HEAD")
        ws_reflog = _git("-C", str(ws), "reflog")

        r = run("push", "origin", "master", cwd=scratch)
        assert r.returncode == 0, r.stderr
        scratch_master = _git("-C", str(scratch), "rev-parse", "master")
        assert _refs(sandbox["scratch_remote"])["refs/heads/master"] == \
            scratch_master
        r = run("ls-remote", "origin", cwd=scratch)
        assert r.returncode == 0 and scratch_master in r.stdout, r.stderr
        r = run("fetch", "origin", cwd=scratch)
        assert r.returncode == 0, r.stderr
        r = run("pull", "--rebase", "origin", "master", cwd=scratch)
        assert r.returncode == 0, r.stderr
        # -C into the scratch repo from inside the workspace stays local too.
        r = run("-C", str(scratch), "push", "origin", "b1", cwd=ws)
        assert r.returncode == 0, r.stderr
        assert "refs/heads/b1" in _refs(sandbox["scratch_remote"])

        assert sandbox["calls"] == []
        assert _refs(sandbox["remote"]) == remote_before
        assert _git("-C", str(ws), "rev-parse", "HEAD") == ws_head
        assert _git("-C", str(ws), "reflog") == ws_reflog

    def test_nested_project_pull_rebase_keeps_workspace_commits(
            self, sandbox, tmp_path):
        """Original report: a nested pm project's ``git pull --rebase`` (pm pr
        start → git_ops.pull_rebase, run with cwd= its own clone) rebased the
        scenario /workspace instead, dropping unpushed commits."""
        proj_remote = tmp_path / "proj.git"
        _git("init", "-q", "--bare", "-b", "master", str(proj_remote))
        proj = tmp_path / "proj"
        _git("clone", "-q", str(proj_remote), str(proj))
        _git("commit", "-q", "--allow-empty", "-m", "p1", cwd=proj)
        _git("push", "-q", "origin", "master", cwd=proj)
        ws = sandbox["ws"]
        ws_head = _git("-C", str(ws), "rev-parse", "HEAD")

        r = sandbox["run"]("pull", "--rebase=merges", cwd=proj)
        assert r.returncode == 0, r.stderr
        assert _git("-C", str(ws), "rev-parse", "HEAD") == ws_head
        assert not any(
            subject.startswith("pull")
            for subject in _git("-C", str(ws), "reflog",
                                "--format=%gs").splitlines())
        assert "unpushed 2" in _git("-C", str(ws), "log", "-1", "--format=%s")
        assert sandbox["calls"] == []

    def test_git_dir_env_pointing_elsewhere_stays_local(self, sandbox):
        """GIT_DIR naming another repo, from inside the workspace, is that repo."""
        before = _refs(sandbox["remote"])
        r = sandbox["run"]("push", "origin", "b2", cwd=sandbox["ws"],
                           env={"GIT_DIR": str(sandbox["scratch"] / ".git")})
        assert r.returncode == 0, r.stderr
        assert "refs/heads/b2" in _refs(sandbox["scratch_remote"])
        assert _refs(sandbox["remote"]) == before
        assert sandbox["calls"] == []

    def test_workspace_commands_reach_proxy(self, sandbox):
        """Subdirectories and ``-C <workspace>`` are the workspace's repo."""
        ws = sandbox["ws"]
        sub = ws / "sub"
        sub.mkdir()
        r = sandbox["run"]("fetch", "origin", cwd=sub)
        assert r.returncode == 0, r.stderr
        assert len(sandbox["calls"]) == 1
        r = sandbox["run"]("-C", str(ws), "push", "origin", ALLOWED,
                           cwd=sandbox["scratch"])
        assert r.returncode == 0, r.stderr
        assert len(sandbox["calls"]) == 2
        assert _refs(sandbox["remote"])[f"refs/heads/{ALLOWED}"] == _git(
            "-C", str(ws), "rev-parse", "HEAD")

    def test_other_global_options_run_locally(self, sandbox):
        """``-c`` can't be replayed by the proxy (and must never reach the
        host), so the command runs with the real git in the container."""
        r = sandbox["run"]("-c", "pm.test=1", "ls-remote", "origin",
                           cwd=sandbox["ws"])
        assert r.returncode == 0, r.stderr
        assert sandbox["calls"] == []
