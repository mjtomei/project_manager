"""Scenario 75: split-load vanilla backend pushes branches, tolerates failure."""

import os
import subprocess

import pytest
import yaml
from click.testing import CliRunner

from pm_core import store
from pm_core.cli import cli
from pm_core.cli.helpers import _make_pr_entry


def _git(*args, cwd, check=True):
    return subprocess.run(
        ["/usr/bin/git", *args], cwd=str(cwd), check=check,
        capture_output=True, text=True,
    )


@pytest.fixture
def runner():
    return CliRunner()


def _setup(tmp_path, runner, monkeypatch):
    # Bypass the pm git wrapper (push-proxy) — use the real git binary so
    # pushes to the local bare remote actually go through.
    monkeypatch.setenv("PATH", "/usr/bin:" + os.environ.get("PATH", ""))
    bare = tmp_path / "remote.git"
    bare.mkdir()
    _git("init", "--bare", "-b", "main", cwd=bare)

    repo = tmp_path / "work"
    repo.mkdir()
    _git("init", "-b", "main", cwd=repo)
    _git("config", "user.email", "t@t.com", cwd=repo)
    _git("config", "user.name", "T", cwd=repo)
    _git("commit", "--allow-empty", "-m", "init", cwd=repo)
    _git("remote", "add", "origin", str(bare), cwd=repo)
    _git("push", "-u", "origin", "main", cwd=repo)

    monkeypatch.chdir(repo)
    result = runner.invoke(cli, ["init", "--no-import", "--backend", "vanilla"])
    assert result.exit_code == 0, result.output
    data = yaml.safe_load((repo / "pm" / "project.yaml").read_text())
    assert data["project"]["backend"] == "vanilla"

    # Add parent PR with workdir=repo
    data = store.load(repo / "pm")
    parent = _make_pr_entry("pr-parent01", "Parent PR",
                            "pm/pr-parent01-parent", plan=None)
    parent["workdir"] = str(repo)
    data.setdefault("prs", []).append(parent)
    store.save(data, repo / "pm")

    # Create two child branches
    for name in ("pm/split-pr-parent01-child-a", "pm/split-pr-parent01-child-b"):
        _git("checkout", "-b", name, cwd=repo)
        _git("commit", "--allow-empty", "-m", f"child {name}", cwd=repo)
        _git("checkout", "main", cwd=repo)

    # Write the split manifest under workdir/pm/specs/pr-parent01/split.md
    specs_dir = repo / "pm" / "specs" / "pr-parent01"
    specs_dir.mkdir(parents=True, exist_ok=True)
    manifest = """## Child PRs

### PR: Child A
- **description**: first child
- **branch**: pm/split-pr-parent01-child-a
- **depends_on**:

---

### PR: Child B
- **description**: second child
- **branch**: pm/split-pr-parent01-child-b
- **depends_on**: Child A
"""
    (specs_dir / "split.md").write_text(manifest)
    return bare, repo


def test_split_load_vanilla_success_and_failure(tmp_path, runner, monkeypatch):
    bare, repo = _setup(tmp_path, runner, monkeypatch)

    # --- Success path
    result = runner.invoke(cli, ["pr", "split-load", "pr-parent01"])
    assert result.exit_code == 0, result.output
    assert "Pushing branch pm/split-pr-parent01-child-a" in result.output
    assert "Created" in result.output
    assert "Loaded 2 child PRs" in result.output

    # Bare remote now has both branches
    for br in ("pm/split-pr-parent01-child-a", "pm/split-pr-parent01-child-b"):
        r = _git("--git-dir", str(bare), "show-ref", "--verify",
                 f"refs/heads/{br}", cwd=repo, check=False)
        assert r.returncode == 0, f"{br} missing on remote: {r.stderr}"

    data = store.load(repo / "pm")
    titles = {p["title"]: p for p in data["prs"]}
    assert "Child A" in titles and "Child B" in titles
    assert titles["Child A"]["branch"] == "pm/split-pr-parent01-child-a"
    assert titles["Child B"]["branch"] == "pm/split-pr-parent01-child-b"
    assert titles["Child B"]["depends_on"] == [titles["Child A"]["id"]]

    # --- Failure path: remove child entries, rewrite manifest with single child
    data["prs"] = [p for p in data["prs"] if p["title"] not in ("Child A", "Child B")]
    store.save(data, repo / "pm")

    manifest2 = """## Child PRs

### PR: Child Fail
- **description**: will not push
- **branch**: pm/split-pr-parent01-child-fail
- **depends_on**:
"""
    (repo / "pm" / "specs" / "pr-parent01" / "split.md").write_text(manifest2)

    from pm_core.cli import pr as pr_mod
    real_run_git = pr_mod.git_ops.run_git

    def fake_run_git(*args, **kwargs):
        if args[:1] == ("push",):
            return subprocess.CompletedProcess(
                args=list(args), returncode=1, stdout="",
                stderr="simulated push failure",
            )
        return real_run_git(*args, **kwargs)

    monkeypatch.setattr(pr_mod.git_ops, "run_git", fake_run_git)

    result = runner.invoke(cli, ["pr", "split-load", "pr-parent01"])
    assert result.exit_code == 0, result.output
    combined = result.output + (result.stderr if hasattr(result, "stderr_bytes") and result.stderr_bytes else "")
    assert "Warning: failed to push pm/split-pr-parent01-child-fail: simulated push failure" in combined
    assert "Created" in combined
    assert "Loaded 1 child PRs" in combined

    data = store.load(repo / "pm")
    titles = {p["title"]: p for p in data["prs"]}
    assert "Child Fail" in titles
    assert titles["Child Fail"]["branch"] == "pm/split-pr-parent01-child-fail"

    r = _git("--git-dir", str(bare), "show-ref", "--verify",
             "refs/heads/pm/split-pr-parent01-child-fail", cwd=repo, check=False)
    assert r.returncode != 0, "branch should NOT have been pushed to remote"
