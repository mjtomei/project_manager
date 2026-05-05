"""Tests for pm_core.store_commit.commit_pr_entry_on_base."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest import mock

import yaml

from pm_core import store_commit


def _git(*args, cwd):
    return subprocess.run(
        ["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True
    )


def _init_repo(root: Path, committed_data: dict, yaml_filename: str = "project.yaml") -> None:
    root.mkdir(parents=True, exist_ok=True)
    _git("init", "-q", "-b", "master", cwd=root)
    _git("config", "user.email", "t@t", cwd=root)
    _git("config", "user.name", "t", cwd=root)
    (root / yaml_filename).write_text(
        store_commit._YAML_HEADER + yaml.dump(
            committed_data, default_flow_style=False, sort_keys=False, allow_unicode=True
        )
    )
    _git("add", yaml_filename, cwd=root)
    _git("commit", "-q", "-m", "init", cwd=root)


def _committed_yaml(root: Path, base: str, path: str) -> dict:
    out = subprocess.run(
        ["git", "show", f"{base}:{path}"],
        cwd=str(root), check=True, capture_output=True, text=True,
    ).stdout
    return yaml.safe_load(out) or {}


def test_autocommit_success_adds_one_pr_entry(tmp_path):
    root = tmp_path / "repo"
    base_data = {
        "project": {"name": "t", "repo": "x", "base_branch": "master"},
        "plans": [{"id": "plan-1", "title": "p"}],
        "prs": [],
    }
    _init_repo(root, base_data)
    # Working yaml has the committed state plus a new PR row referencing plan-1.
    working = dict(base_data)
    working["prs"] = [{"id": "pr-abc", "title": "new", "plan": "plan-1", "status": "pending"}]
    (root / "project.yaml").write_text(
        store_commit._YAML_HEADER + yaml.dump(
            working, default_flow_style=False, sort_keys=False, allow_unicode=True
        )
    )

    ok, reason = store_commit.commit_pr_entry_on_base(
        root, "project.yaml", "master", "pr-abc", backend="local"
    )
    assert ok, reason
    after = _committed_yaml(root, "master", "project.yaml")
    assert [pr["id"] for pr in after["prs"]] == ["pr-abc"]
    # base_branch advanced by exactly one commit
    log = subprocess.run(
        ["git", "log", "--oneline", "master"],
        cwd=str(root), check=True, capture_output=True, text=True,
    ).stdout.splitlines()
    assert len(log) == 2
    assert "pm: add pr-abc entry on master" in log[0]


def test_autocommit_falls_through_when_plan_not_committed(tmp_path):
    root = tmp_path / "repo"
    base_data = {
        "project": {"name": "t", "repo": "x", "base_branch": "master"},
        "plans": [],
        "prs": [],
    }
    _init_repo(root, base_data)
    working = {
        "project": {"name": "t", "repo": "x", "base_branch": "master"},
        "plans": [{"id": "plan-new", "title": "uncommitted"}],
        "prs": [{"id": "pr-abc", "title": "new", "plan": "plan-new"}],
    }
    (root / "project.yaml").write_text(
        store_commit._YAML_HEADER + yaml.dump(
            working, default_flow_style=False, sort_keys=False, allow_unicode=True
        )
    )

    ok, reason = store_commit.commit_pr_entry_on_base(
        root, "project.yaml", "master", "pr-abc", backend="local"
    )
    assert not ok
    assert "plan-new" in reason
    assert "pm push" in reason
    # No new commit on master
    log = subprocess.run(
        ["git", "log", "--oneline", "master"],
        cwd=str(root), check=True, capture_output=True, text=True,
    ).stdout.splitlines()
    assert len(log) == 1


def test_autocommit_no_plan_succeeds(tmp_path):
    root = tmp_path / "repo"
    base_data = {
        "project": {"name": "t", "repo": "x", "base_branch": "master"},
        "prs": [],
    }
    _init_repo(root, base_data)
    working = dict(base_data)
    working["prs"] = [{"id": "pr-free", "title": "free-floating"}]
    (root / "project.yaml").write_text(
        store_commit._YAML_HEADER + yaml.dump(
            working, default_flow_style=False, sort_keys=False, allow_unicode=True
        )
    )

    ok, reason = store_commit.commit_pr_entry_on_base(
        root, "project.yaml", "master", "pr-free", backend="local"
    )
    assert ok, reason


def test_autocommit_idempotent_when_already_committed(tmp_path):
    root = tmp_path / "repo"
    base_data = {
        "project": {"name": "t", "repo": "x", "base_branch": "master"},
        "prs": [{"id": "pr-already", "title": "x"}],
    }
    _init_repo(root, base_data)
    # Working == committed; helper should return True without making a new commit.
    (root / "project.yaml").write_text(
        store_commit._YAML_HEADER + yaml.dump(
            base_data, default_flow_style=False, sort_keys=False, allow_unicode=True
        )
    )

    ok, reason = store_commit.commit_pr_entry_on_base(
        root, "project.yaml", "master", "pr-already", backend="local"
    )
    assert ok, reason
    log = subprocess.run(
        ["git", "log", "--oneline", "master"],
        cwd=str(root), check=True, capture_output=True, text=True,
    ).stdout.splitlines()
    assert len(log) == 1


def test_autocommit_pr_missing_in_working_yaml(tmp_path):
    root = tmp_path / "repo"
    base_data = {
        "project": {"name": "t", "repo": "x", "base_branch": "master"},
        "prs": [],
    }
    _init_repo(root, base_data)
    (root / "project.yaml").write_text(
        store_commit._YAML_HEADER + yaml.dump(
            base_data, default_flow_style=False, sort_keys=False, allow_unicode=True
        )
    )
    ok, reason = store_commit.commit_pr_entry_on_base(
        root, "project.yaml", "master", "pr-ghost", backend="local"
    )
    assert not ok
    assert "pr-ghost" in reason


def test_lock_timeout_returns_error(tmp_path):
    """If the lock can't be acquired, the helper surfaces a timeout error
    rather than hanging."""
    root = tmp_path / "repo"
    base_data = {
        "project": {"name": "t", "repo": "x", "base_branch": "master"},
        "prs": [],
    }
    _init_repo(root, base_data)
    working = dict(base_data)
    working["prs"] = [{"id": "pr-x"}]
    (root / "project.yaml").write_text(
        store_commit._YAML_HEADER + yaml.dump(
            working, default_flow_style=False, sort_keys=False, allow_unicode=True
        )
    )

    # Stub the lock to time out immediately.
    from contextlib import contextmanager

    @contextmanager
    def fake_lock(timeout=30.0):
        raise TimeoutError(f"timed out waiting on yaml-commit lock after {timeout}s")
        yield  # pragma: no cover

    with mock.patch.object(store_commit, "_yaml_commit_lock", fake_lock):
        ok, reason = store_commit.commit_pr_entry_on_base(
            root, "project.yaml", "master", "pr-x", backend="local"
        )
    assert not ok
    assert "timed out" in reason
