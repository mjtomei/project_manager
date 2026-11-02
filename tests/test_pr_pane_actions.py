"""`pm pr shell` / `pm pr view-spec` / `pm pr view-diff` (pr-cfe24ea).

The prefix+P picker's c/o/u/y keys and a prefix+M command dispatch these
same CLI commands, so this file covers the shared behaviour: PR id forms,
the in-session pane path (the caller's window, role registration, split
direction, exit trap) versus printing to stdout elsewhere, the read-only
spec pager fall-through, and the diff pane staying byte-identical to the
review window's.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from unittest import mock

import pytest
from click.testing import CliRunner

from pm_core import store
from pm_core.cli import pr as pr_mod

PR_ID = "pr-f5b7eef"
BRANCH = "pm/pr-f5b7eef-feature"
TITLE = "Picker panes: it's a test"
IMPL_TEXT = "# Impl spec\n\nIMPL SPEC BODY marker\n"
QA_TEXT = "# QA spec\n\nQA SPEC BODY marker\n"


def _git(cwd, *args):
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t",
         "-c", "init.defaultBranch=master", *args],
        cwd=cwd, check=True, capture_output=True, text=True).stdout


def _make_project(tmp_path: Path, *, workdir: bool = True,
                  branch_in_repo: bool = False,
                  impl_spec: str | None = IMPL_TEXT,
                  backend: str = "github") -> dict:
    """A project repo (internal pm/ dir) with origin, plus a PR workdir."""
    origin = tmp_path / "origin.git"
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "README").write_text("base\n")
    _git(repo, "add", "README")
    _git(repo, "commit", "-qm", "base")
    _git(tmp_path, "clone", "-q", "--bare", str(repo), str(origin))
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "fetch", "-q", "origin")

    wd = tmp_path / "work dir"   # a space: paths must be quoted
    if workdir or branch_in_repo:
        _git(tmp_path, "clone", "-q", str(origin), str(wd))
        _git(wd, "checkout", "-qb", BRANCH)
        (wd / "feature.txt").write_text("feature line\n")
        _git(wd, "add", "feature.txt")
        _git(wd, "commit", "-qm", "feature")
        if branch_in_repo:
            _git(wd, "push", "-q", "origin", BRANCH)
            _git(repo, "fetch", "-q", "origin")
            shutil.rmtree(wd)

    pm_dir = repo / "pm"
    pm_dir.mkdir()
    pr = {"id": PR_ID, "title": TITLE, "branch": BRANCH,
          "status": "in_progress" if workdir else "pending",
          "gh_pr_number": 193,
          "workdir": str(wd) if workdir else None}
    store.save({"project": {"name": "pane-test", "repo": str(origin),
                            "base_branch": "master", "backend": backend},
                "prs": [pr], "plans": []}, pm_dir)
    if impl_spec is not None:
        spec = pm_dir / "specs" / PR_ID / "impl.md"
        spec.parent.mkdir(parents=True)
        spec.write_text(impl_spec)
    return {"pm_dir": pm_dir, "repo": repo, "workdir": wd, "pr": pr}


def _invoke(pm_dir: Path, *args: str):
    with mock.patch.object(pr_mod, "state_root", return_value=pm_dir):
        return CliRunner().invoke(pr_mod.pr, list(args))


@pytest.fixture
def outside_tmux(monkeypatch):
    for var in ("TMUX", "TMUX_PANE", "PM_POPUP_SESSION"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def in_pm_session(monkeypatch):
    """Inside pm session ``pm-x``, window ``@5``; the pane opener is mocked."""
    opened = mock.MagicMock(return_value="%9")
    monkeypatch.setattr(pr_mod, "_get_current_pm_session", lambda: "pm-x")
    monkeypatch.setattr(pr_mod, "_caller_window_id", lambda: "@5")
    monkeypatch.setattr(pr_mod, "_open_pane_for_pr", opened)
    return opened


# --- PR id forms --------------------------------------------------------------

@pytest.mark.parametrize("ident", [PR_ID, "#193", "193"])
def test_every_pr_id_form_resolves_to_the_same_pr(tmp_path, outside_tmux, ident):
    p = _make_project(tmp_path)
    r = _invoke(p["pm_dir"], "view-spec", ident)
    assert r.exit_code == 0, r.output
    assert r.output == IMPL_TEXT


def test_unknown_pr_id_uses_require_pr_error(tmp_path, outside_tmux):
    p = _make_project(tmp_path)
    r = _invoke(p["pm_dir"], "view-diff", "#999")
    assert r.exit_code == 1
    assert "PR '#999' not found." in r.output


def test_commands_listed_in_pr_help():
    r = CliRunner().invoke(pr_mod.pr, ["--help"])
    for name in ("shell", "view-spec", "view-diff"):
        assert f"  {name} " in r.output


# --- outside a pm session: print to stdout -------------------------------------

def test_view_spec_qa_prints_spec(tmp_path, outside_tmux):
    p = _make_project(tmp_path)
    qa = p["pm_dir"] / "specs" / PR_ID / "qa.md"
    qa.write_text(QA_TEXT)
    r = _invoke(p["pm_dir"], "view-spec", "193", "--kind", "qa")
    assert (r.exit_code, r.output) == (0, QA_TEXT)


def test_view_spec_prefers_workdir_copy(tmp_path, outside_tmux):
    p = _make_project(tmp_path)
    wd_spec = p["workdir"] / "pm" / "specs" / PR_ID / "impl.md"
    wd_spec.parent.mkdir(parents=True)
    wd_spec.write_text("in-flight workdir copy\n")
    r = _invoke(p["pm_dir"], "view-spec", PR_ID)
    assert r.output == "in-flight workdir copy\n"


@pytest.mark.parametrize("content", [None, "  \n"])
def test_missing_or_empty_spec_is_a_clear_error(tmp_path, outside_tmux,
                                                content):
    p = _make_project(tmp_path, impl_spec=content)
    r = _invoke(p["pm_dir"], "view-spec", "#193")
    assert r.exit_code == 1
    assert (f"No impl spec for {PR_ID} — run 'pm pr spec {PR_ID} impl' first."
            in r.output)


def test_view_diff_prints_review_pane_content(tmp_path, outside_tmux):
    p = _make_project(tmp_path)
    r = _invoke(p["pm_dir"], "view-diff", "#193")
    # Click's runner captures only Python-level output; the bash child
    # writes to the real stdout, so check the command instead.
    assert r.exit_code == 0, r.output
    with mock.patch.object(pr_mod.subprocess, "run",
                           return_value=mock.Mock(returncode=0)) as run:
        r = _invoke(p["pm_dir"], "view-diff", "#193")
    argv = run.call_args.args[0]
    assert argv[:2] == ["bash", "-c"]
    assert argv[2] == pr_mod._build_diff_cmd(
        str(p["workdir"]), "#193", TITLE, "master", "github",
        pipe_to_less=False, keep_pane_open=False)


def test_view_diff_stdout_output(tmp_path, outside_tmux):
    p = _make_project(tmp_path)
    data = store.load(p["pm_dir"])
    cmd = pr_mod._diff_cmd_for_pr(p["pr"], data, p["pm_dir"],
                                  pipe_to_less=False, keep_pane_open=False)
    out = subprocess.run(["bash", "-c", cmd], capture_output=True,
                         text=True, check=True).stdout
    assert out.startswith(f"=== Review: #193 — {TITLE} ===\n")
    assert f"On branch {BRANCH}" in out          # git status block
    assert "--- Change summary ---" in out
    assert "feature.txt" in out
    assert "+feature line" in out


def test_view_diff_failure_exit_status_propagates(tmp_path, outside_tmux):
    p = _make_project(tmp_path)
    with mock.patch.object(pr_mod.subprocess, "run",
                           return_value=mock.Mock(returncode=128)):
        r = _invoke(p["pm_dir"], "view-diff", PR_ID)
    assert r.exit_code == 128


def test_view_diff_without_workdir_diffs_branch_in_project_repo(
        tmp_path, outside_tmux):
    p = _make_project(tmp_path, workdir=False, branch_in_repo=True)
    data = store.load(p["pm_dir"])
    entry = store.get_pr(data, PR_ID)
    cmd = pr_mod._diff_cmd_for_pr(entry, data, p["pm_dir"],
                                  pipe_to_less=False, keep_pane_open=False)
    assert f"refs/remotes/origin/{BRANCH}" in cmd
    assert "git status" not in cmd   # would describe the project repo
    out = subprocess.run(["bash", "-c", cmd], capture_output=True,
                         text=True, check=True).stdout
    assert "+feature line" in out


def test_view_diff_without_workdir_or_branch_errors(tmp_path, outside_tmux):
    p = _make_project(tmp_path, workdir=False)
    r = _invoke(p["pm_dir"], "view-diff", "193")
    assert r.exit_code == 1
    assert f"No diff for {PR_ID}: it has no workdir and branch '{BRANCH}'" \
        in r.output


def test_shell_outside_session_execs_shell_in_workdir(tmp_path, outside_tmux,
                                                      monkeypatch):
    p = _make_project(tmp_path)
    monkeypatch.setenv("SHELL", "/bin/zsh")
    with mock.patch.object(pr_mod.os, "chdir") as chdir, \
         mock.patch.object(pr_mod.os, "execvp") as execvp:
        r = _invoke(p["pm_dir"], "shell", "#193")
    assert r.exit_code == 0, r.output
    chdir.assert_called_once_with(str(p["workdir"]))
    execvp.assert_called_once_with("/bin/zsh", ["/bin/zsh"])


def test_shell_without_workdir_errors(tmp_path, outside_tmux):
    p = _make_project(tmp_path, workdir=False)
    r = _invoke(p["pm_dir"], "shell", PR_ID)
    assert r.exit_code == 1
    assert f"PR {PR_ID} has no workdir; start it first." in r.output


def test_non_pm_tmux_session_prints_instead_of_splitting(tmp_path, monkeypatch):
    """A typed command in someone's own tmux session is not a pm session."""
    p = _make_project(tmp_path)
    monkeypatch.setattr(pr_mod, "_get_current_pm_session", lambda: None)
    opened = mock.MagicMock()
    monkeypatch.setattr(pr_mod, "_open_pane_for_pr", opened)
    r = _invoke(p["pm_dir"], "view-spec", PR_ID)
    assert r.output == IMPL_TEXT
    opened.assert_not_called()


# --- inside a pm session: open a pane in the caller's window -------------------

def test_shell_in_session_opens_pane_at_workdir(tmp_path, in_pm_session):
    p = _make_project(tmp_path)
    r = _invoke(p["pm_dir"], "shell", "193")
    assert r.exit_code == 0, r.output
    assert r.output == "Opened shell pane for #193.\n"
    in_pm_session.assert_called_once_with(
        "pm-x", "@5", "shell",
        pr_mod._build_shell_at_workdir_cmd(str(p["workdir"])),
        cwd=str(p["workdir"]))


@pytest.mark.parametrize("kind", ["impl", "qa"])
def test_view_spec_in_session_opens_viewer_pane(tmp_path, in_pm_session, kind):
    p = _make_project(tmp_path)
    (p["pm_dir"] / "specs" / PR_ID / "qa.md").write_text(QA_TEXT)
    r = _invoke(p["pm_dir"], "view-spec", "#193", "--kind", kind)
    assert r.exit_code == 0, r.output
    spec = p["pm_dir"] / "specs" / PR_ID / f"{kind}.md"
    in_pm_session.assert_called_once_with(
        "pm-x", "@5", f"{kind}-spec", pr_mod._build_spec_viewer_cmd(spec),
        cwd=None)


def test_view_diff_in_session_uses_review_diff_command(tmp_path, in_pm_session):
    p = _make_project(tmp_path)
    r = _invoke(p["pm_dir"], "view-diff", PR_ID)
    assert r.exit_code == 0, r.output
    in_pm_session.assert_called_once_with(
        "pm-x", "@5", "diff",
        pr_mod._build_diff_cmd(str(p["workdir"]), "#193", TITLE, "master",
                               "github"),
        cwd=None)


def test_missing_spec_in_session_opens_no_pane(tmp_path, in_pm_session):
    p = _make_project(tmp_path, impl_spec=None)
    r = _invoke(p["pm_dir"], "view-spec", PR_ID)
    assert r.exit_code == 1
    assert "No impl spec" in r.output
    in_pm_session.assert_not_called()


def test_unresolved_window_is_an_error(tmp_path, in_pm_session, monkeypatch):
    p = _make_project(tmp_path)
    monkeypatch.setattr(pr_mod, "_caller_window_id", lambda: None)
    r = _invoke(p["pm_dir"], "view-spec", PR_ID)
    assert r.exit_code == 1
    assert "Could not find the current tmux window." in r.output
    in_pm_session.assert_not_called()


# --- caller window resolution ---------------------------------------------------

def test_caller_window_from_own_pane(monkeypatch):
    monkeypatch.setenv("TMUX_PANE", "%3")
    with mock.patch.object(pr_mod.tmux_mod, "pane_window_id",
                           return_value="@2") as pwi:
        assert pr_mod._caller_window_id() == "@2"
    pwi.assert_called_once_with("%3")


def test_caller_window_from_popup_uses_opening_clients_session(monkeypatch):
    """A popup has no pane: target the opening client's session (exported
    as PM_POPUP_SESSION) by exact name, so its current window is used."""
    monkeypatch.delenv("TMUX_PANE", raising=False)
    with mock.patch.object(pr_mod.tmux_mod, "get_session_name",
                           return_value="pm-x~2"), \
         mock.patch.object(pr_mod.tmux_mod, "pane_window_id",
                           return_value="@8") as pwi:
        assert pr_mod._caller_window_id() == "@8"
    pwi.assert_called_once_with("=pm-x~2:")


# --- the shared pane opener ------------------------------------------------------

def _opener(monkeypatch, geometry: str, user_modified: bool = False,
            split_error: Exception | None = None):
    calls = {}
    monkeypatch.setattr(
        pr_mod.subprocess, "run",
        lambda *a, **k: mock.Mock(returncode=0 if geometry else 1,
                                  stdout=geometry, stderr=""))
    monkeypatch.setattr(pr_mod.pane_registry, "pm_session_name",
                        lambda s: s.split("~")[0])
    monkeypatch.setattr(
        pr_mod.pane_registry, "load_registry",
        lambda s: {"generation": "g7",
                   "windows": {"@5": {"panes": [],
                                      "user_modified": user_modified}}})

    def split(pane, direction, cmd, background=False, cwd=None, env=None):
        if split_error:
            raise split_error
        calls["split"] = (pane, direction, cmd, cwd)
        return "%9"
    monkeypatch.setattr(pr_mod.tmux_mod, "split_pane_at", split)
    calls["register"] = mock.MagicMock()
    calls["rebalance"] = mock.MagicMock()
    monkeypatch.setattr(pr_mod.pane_registry, "register_pane",
                        calls["register"])
    monkeypatch.setattr(pr_mod.pane_layout, "register_and_rebalance",
                        calls["rebalance"])
    return calls


@pytest.mark.parametrize("geometry, direction", [
    ("%1 200 50", "h"),   # physically wider than tall: side by side
    ("%1 80 50", "v"),    # 80 cols x 50 rows is physically tall: stacked
])
def test_split_direction_follows_active_pane_shape(monkeypatch, geometry,
                                                   direction):
    calls = _opener(monkeypatch, geometry)
    assert pr_mod._open_pane_for_pr("pm-x~2", "@5", "impl-spec", "CMD") == "%9"
    pane, got, _, _ = calls["split"]
    assert (pane, got) == ("%1", direction)


def test_pane_registered_under_role_with_exit_trap(monkeypatch):
    calls = _opener(monkeypatch, "%1 200 50")
    pr_mod._open_pane_for_pr("pm-x~2", "@5", "diff", "echo hi; exec bash",
                             cwd="/wd")
    _, _, wrapped, cwd = calls["split"]
    assert cwd == "/wd"
    assert "pm _pane-exited pm-x @5 g7 $TMUX_PANE" in wrapped
    calls["rebalance"].assert_called_once_with(
        "pm-x", "@5", [("%9", "pr-diff", "echo hi; exec bash")])
    calls["register"].assert_not_called()


def test_hand_arranged_window_is_registered_not_rebalanced(monkeypatch):
    calls = _opener(monkeypatch, "%1 200 50", user_modified=True)
    pr_mod._open_pane_for_pr("pm-x", "@5", "shell", "CMD")
    calls["register"].assert_called_once_with("pm-x", "@5", "%9", "pr-shell",
                                              "CMD")
    calls["rebalance"].assert_not_called()


def test_missing_window_raises(monkeypatch):
    _opener(monkeypatch, "")
    with pytest.raises(pr_mod._PaneActionError, match="window @5 not found"):
        pr_mod._open_pane_for_pr("pm-x", "@5", "shell", "CMD")


def test_split_failure_raises(monkeypatch):
    err = pr_mod.tmux_mod.TmuxCommandError(1, ["tmux"], "",
                                           "no space for new pane")
    _opener(monkeypatch, "%1 20 5", split_error=err)
    with pytest.raises(pr_mod._PaneActionError, match="no space for new pane"):
        pr_mod._open_pane_for_pr("pm-x", "@5", "shell", "CMD")


def test_exit_trap_survives_exec_in_pane_command(tmp_path):
    """The shell and diff panes end in ``exec``; the trap must still fire."""
    log = tmp_path / "log"
    stub = tmp_path / "bin"
    stub.mkdir()
    (stub / "pm").write_text(f'#!/bin/sh\necho "$@" >> {log}\n')
    (stub / "pm").chmod(0o755)
    wrapped = pr_mod._pane_exit_trap_cmd("pm-x", "@5", "g7",
                                         "echo inner; exec true")
    env = dict(os.environ, PATH=f"{stub}:{os.environ['PATH']}",
               TMUX_PANE="%42")
    out = subprocess.run(["sh", "-c", wrapped], env=env, capture_output=True,
                         text=True, check=True).stdout
    assert out == "inner\n"
    assert log.read_text() == "_pane-exited pm-x @5 g7 %42\n"


# --- read-only spec viewer --------------------------------------------------------

def _viewer_env(tmp_path, tools: dict[str, str]) -> dict:
    """PATH holding only cat plus the given stub tools."""
    bin_dir = tmp_path / "vbin"
    bin_dir.mkdir()
    os.symlink(shutil.which("cat"), bin_dir / "cat")
    for name, body in tools.items():
        (bin_dir / name).write_text(f"#!/bin/sh\n{body}\n")
        (bin_dir / name).chmod(0o755)
    return dict(os.environ, PATH=str(bin_dir))


def _spec(tmp_path) -> Path:
    spec = tmp_path / "it's a spec dir" / "impl.md"
    spec.parent.mkdir()
    spec.write_text(IMPL_TEXT)
    return spec


def _run_viewer(spec, env, stdin=""):
    return subprocess.run([shutil.which("bash"), "-c",
                           pr_mod._build_spec_viewer_cmd(spec)],
                          env=env, input=stdin, capture_output=True,
                          text=True).stdout


def test_viewer_prefers_glow_pager(tmp_path):
    env = _viewer_env(tmp_path, {
        "glow": 'echo "glow $1 [$2] LESSSECURE=$LESSSECURE"',
        "less": 'echo "less $@"'})
    spec = _spec(tmp_path)
    assert _run_viewer(spec, env) == f"glow -p [{spec}] LESSSECURE=1\n"


def test_viewer_falls_back_to_secure_less(tmp_path):
    env = _viewer_env(tmp_path, {
        "less": 'echo "less $1 [$2] LESSSECURE=$LESSSECURE"'})
    spec = _spec(tmp_path)
    assert _run_viewer(spec, env) == f"less -R [{spec}] LESSSECURE=1\n"


def test_viewer_falls_back_to_cat_and_waits_for_a_key(tmp_path):
    spec = _spec(tmp_path)
    out = _run_viewer(spec, _viewer_env(tmp_path, {}), stdin="x")
    assert out == IMPL_TEXT + "\n[press any key to close]"


# --- diff pane parity with the review window --------------------------------------

def _master_review_diff_cmd(workdir, display_id, title, base_branch,
                            backend_name, shell):
    """The review window's inline diff pipeline as on master@81e5d7f4."""
    from pm_core.shell import shell_quote
    header = f"=== Review: {display_id} — {title} ==="
    diff_ref = base_branch if backend_name == "local" else f"origin/{base_branch}"
    return (
        f"cd {shell_quote(workdir)}"
        f" && {{ echo {shell_quote(header)}"
        f" && echo ''"
        f" && git status"
        f" && echo ''"
        f" && echo '--- Change summary ---'"
        f" && git --no-pager diff --stat {diff_ref}...HEAD"
        f" && echo ''"
        f" && echo '--- Full diff ---'"
        f" && git --no-pager diff {diff_ref}...HEAD"
        f"; }} | if command -v less >/dev/null 2>&1;"
        f" then less -R; else cat; echo; echo; fi"
        f"; exec {shell}"
    )


@pytest.mark.parametrize("backend", ["github", "vanilla", "local"])
def test_diff_command_is_byte_identical_to_review_pipeline(backend):
    args = ("/w d/x", "#193", TITLE, "main", backend)
    assert pr_mod._build_diff_cmd(*args, shell="/bin/zsh") == \
        _master_review_diff_cmd(*args, shell="/bin/zsh")


# --- real tmux server (isolated socket and HOME) ----------------------------------

needs_tmux = pytest.mark.skipif(shutil.which("tmux") is None,
                                reason="needs tmux")


@pytest.fixture
def tmux_env(tmp_path, monkeypatch):
    """A private tmux server whose panes see a stub ``pm`` and no pager.

    tmux gives a new pane the PATH of the client that ran split-window —
    this test process — so PATH is narrowed here, not just for the server.
    """
    home = tmp_path / "home"
    home.mkdir()
    bin_dir = tmp_path / "tbin"
    bin_dir.mkdir()
    log = tmp_path / "pm-calls.log"
    (bin_dir / "pm").write_text(f'#!/bin/sh\necho "$@" >> {log}\n')
    (bin_dir / "pm").chmod(0o755)
    for tool in ("bash", "sh", "cat", "git", "sleep", "env", "tmux"):
        os.symlink(shutil.which(tool), bin_dir / tool)
    sock = str(tmp_path / "tmux.sock")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setenv("PM_TMUX_SOCKET", sock)
    monkeypatch.setenv("SHELL", str(bin_dir / "bash"))
    server_env = dict(os.environ)
    tmux = str(bin_dir / "tmux")

    def t(*args):
        return subprocess.run([tmux, "-S", sock, *args], check=True,
                              capture_output=True, text=True,
                              env=server_env).stdout.strip()
    t.log = log
    yield t
    subprocess.run([tmux, "-S", sock, "kill-server"], capture_output=True)


def _wait_for(pred, timeout=8.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = pred()
        if value:
            return value
        time.sleep(0.1)
    return pred()


def _panes(t, window):
    rows = t("list-panes", "-t", window, "-F",
             "#{pane_id} #{pane_left} #{pane_top} #{pane_current_path}")
    return [r.split(" ", 3) for r in rows.splitlines()]


def _start_session(t, monkeypatch, size=("200", "50")):
    from pm_core import pane_registry
    t("new-session", "-d", "-s", "pm-pt", "-x", size[0], "-y", size[1],
      "sleep 600")
    pane = t("display-message", "-p", "-t", "=pm-pt:", "#{pane_id}")
    wid = t("display-message", "-p", "-t", "=pm-pt:", "#{window_id}")
    pane_registry.registry_path("pm-pt").write_text(json.dumps(
        {"session": "pm-pt", "generation": "g1",
         "windows": {wid: {"panes": [{"id": pane, "role": "main",
                                      "order": 0, "cmd": "sleep"}],
                           "user_modified": False}}}))
    monkeypatch.setenv("TMUX", "/x,1,0")
    return pane, wid


@needs_tmux
def test_real_shell_pane_lands_in_workdir_and_is_registered(
        tmp_path, tmux_env, monkeypatch):
    from pm_core import pane_registry
    t = tmux_env
    p = _make_project(tmp_path)
    pane, wid = _start_session(t, monkeypatch)
    monkeypatch.setenv("TMUX_PANE", pane)

    r = _invoke(p["pm_dir"], "shell", "#193")
    assert r.exit_code == 0, r.output

    rows = _wait_for(lambda: [row for row in _panes(t, wid)
                              if row[0] != pane
                              and row[3] == str(p["workdir"])])
    assert rows, _panes(t, wid)
    new_pane, left, top, _ = rows[0]
    assert int(left) > 0 and top == "0"          # 200x50: side by side
    roles = {e["id"]: e["role"] for e in
             pane_registry.load_registry("pm-pt")["windows"][wid]["panes"]}
    assert roles[new_pane] == "pr-shell"

    # Wait for the shell's prompt before typing, or `exit` races its startup.
    assert _wait_for(lambda: "$" in t("capture-pane", "-p", "-t", new_pane))
    t("send-keys", "-t", new_pane, "exit", "Enter")
    assert _wait_for(lambda: t.log.exists() and
                     f"_pane-exited pm-pt {wid} g1 {new_pane}"
                     in t.log.read_text())


@needs_tmux
def test_real_spec_pane_shows_spec_and_closes_on_a_key(
        tmp_path, tmux_env, monkeypatch):
    t = tmux_env
    p = _make_project(tmp_path)
    # 120x70 is physically taller than wide (cells are ~2x taller), and
    # wide enough to stay out of mobile mode (which zooms the new pane).
    pane, wid = _start_session(t, monkeypatch, size=("120", "70"))
    monkeypatch.setenv("TMUX_PANE", pane)

    r = _invoke(p["pm_dir"], "view-spec", "193")
    assert r.exit_code == 0, r.output
    new_pane = _wait_for(lambda: [row[0] for row in _panes(t, wid)
                                  if row[0] != pane])[0]
    geometry = {row[0]: row[1:3] for row in _panes(t, wid)}
    assert geometry[pane] == ["0", "0"]          # stacked: new pane below
    assert geometry[new_pane][0] == "0" and int(geometry[new_pane][1]) > 0

    # No glow/less on the pane's PATH: the cat fallback holds the pane open.
    screen = _wait_for(lambda: (s := t("capture-pane", "-p", "-t", new_pane))
                       and "[press any key to close]" in s and s)
    assert "IMPL SPEC BODY marker" in screen
    t("send-keys", "-t", new_pane, "x")
    assert _wait_for(lambda: new_pane not in [row[0]
                                              for row in _panes(t, wid)])
    assert _wait_for(lambda: t.log.exists() and
                     f"_pane-exited pm-pt {wid} g1 {new_pane}"
                     in t.log.read_text())


@needs_tmux
def test_real_popup_opens_pane_in_the_opening_clients_window(
        tmp_path, tmux_env, monkeypatch):
    """prefix+P / prefix+M: no pane, PM_POPUP_SESSION names the client's
    (grouped) session; the pane lands in *its* current window, not the
    base session's."""
    t = tmux_env
    p = _make_project(tmp_path)
    base_pane, base_wid = _start_session(t, monkeypatch)
    t("new-session", "-d", "-t", "pm-pt", "-s", "pm-pt~2")
    t("new-window", "-t", "=pm-pt~2:", "-n", "other", "sleep 600")
    view_wid = t("display-message", "-p", "-t", "=pm-pt~2:", "#{window_id}")
    view_pane = t("display-message", "-p", "-t", "=pm-pt~2:", "#{pane_id}")
    assert view_wid != base_wid
    monkeypatch.delenv("TMUX_PANE", raising=False)
    monkeypatch.setenv("PM_POPUP_SESSION", "pm-pt~2")

    r = _invoke(p["pm_dir"], "view-diff", "#193")
    assert r.exit_code == 0, r.output
    assert _wait_for(lambda: len(_panes(t, view_wid)) == 2)
    assert len(_panes(t, base_wid)) == 1
    new_pane = next(row[0] for row in _panes(t, view_wid)
                    if row[0] != view_pane)
    screen = _wait_for(lambda: (s := t("capture-pane", "-p", "-J", "-S", "-",
                                       "-t", new_pane))
                       and "+feature line" in s and s)
    assert f"=== Review: #193 — {TITLE} ===" in screen
    assert "--- Change summary ---" in screen
