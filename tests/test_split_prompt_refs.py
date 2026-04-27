import subprocess
from pathlib import Path

import yaml
from click.testing import CliRunner

from pm_core.cli import cli
from pm_core import prompt_gen, store


def _run_git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def test_generate_split_prompt_uses_origin_refs_for_vanilla(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _run_git(repo, "init")
    _run_git(repo, "config", "user.email", "test@test.com")
    _run_git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("hello\n")
    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-m", "Initial commit")
    _run_git(repo, "remote", "add", "origin", "git@gitlab.com:org/myapp.git")

    monkeypatch.chdir(repo)

    runner = CliRunner()
    result = runner.invoke(cli, ["init", "--no-import", "--backend", "vanilla"])
    assert result.exit_code == 0, result.output

    project_yaml = repo / "pm" / "project.yaml"
    data = yaml.safe_load(project_yaml.read_text())
    assert data["project"]["backend"] == "vanilla"
    base = data["project"]["base_branch"]

    result = runner.invoke(cli, ["pr", "add", "Test PR for split"])
    assert result.exit_code == 0, result.output

    data = store.load(repo / "pm")
    pr_id = data["prs"][0]["id"]

    prompt = prompt_gen.generate_split_prompt(data, pr_id)

    assert f"git diff origin/{base}...HEAD" in prompt
    assert f"origin/{base}" in prompt
    # No bare-ref diff line (using leading space to avoid origin/{base} match)
    assert f" {base}...HEAD" not in prompt.replace(f"origin/{base}...HEAD", "")
    assert f"git checkout -b pm/split-{pr_id}-" in prompt
    # checkout line uses origin ref
    checkout_line = next(
        line for line in prompt.splitlines()
        if f"git checkout -b pm/split-{pr_id}-" in line
    )
    assert f"origin/{base}" in checkout_line
    assert prompt.count(f"origin/{base}") >= 2
