"""Concurrent ``pm pr start`` of the same PR is serialized (QA S9).

Two starts that begin in the same instant used to share the ``.tmp-<id>``
clone path: one could ``shutil.rmtree`` the other's in-progress clone
(``OSError: Directory not empty``) and both could record the start / open
duplicate windows.  A per-PR start lock makes the loser wait, re-load the
record and take the already-in_progress reuse path, so exactly one clone,
one workdir and one window are produced.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace

import yaml

from pm_core import store
from pm_core.cli import pr as pr_mod

PR = "pr-001"


def test_two_starts_of_the_same_pr_clone_once(tmp_path, monkeypatch):
    root = tmp_path / "pm"
    root.mkdir()
    data = {
        "project": {
            "name": "t",
            "repo": str(tmp_path / "repo"),
            "base_branch": "master",
            "backend": "vanilla",
            "repo_id": "abc12345def",
            "active_pr": None,
        },
        "plans": [],
        "prs": [{
            "id": PR,
            "title": "T",
            "branch": "pm/pr-001",
            "status": "pending",
            "depends_on": [],
            "workdir": None,
            "description": "",
            "gh_pr": None,
            "gh_pr_number": None,
        }],
    }
    store.save(data, root)
    yaml_dump = yaml.safe_dump(data)

    workdirs = tmp_path / "workdirs"
    workdirs.mkdir()

    clone_calls: list[str] = []
    first_clone_entered = threading.Event()

    def fake_clone(src, dest, branch=None):
        clone_calls.append(str(dest))
        if len(clone_calls) == 1:
            # Hold the first start inside the clone window so the second
            # start has time to reach (and block on) the per-PR lock.
            first_clone_entered.set()
            time.sleep(0.5)
        dest.mkdir(parents=True, exist_ok=True)

    def fake_run_git(*args, **kwargs):
        if args[:1] == ("show",):
            return SimpleNamespace(returncode=0, stdout=yaml_dump, stderr="")
        return SimpleNamespace(returncode=0, stdout="abcd1234\n", stderr="")

    monkeypatch.setattr(pr_mod, "state_root", lambda: root)
    monkeypatch.setattr(pr_mod, "trigger_tui_refresh", lambda: None)
    monkeypatch.setattr(pr_mod, "_get_pm_session", lambda: None)
    monkeypatch.setattr(pr_mod, "_resolve_repo_id", lambda *a, **k: None)
    monkeypatch.setattr(pr_mod, "find_claude", lambda: None)
    monkeypatch.setattr(pr_mod.prompt_gen, "generate_prompt",
                        lambda *a, **k: "prompt")
    monkeypatch.setattr("pm_core.paths.workdirs_base", lambda: workdirs)
    monkeypatch.setattr("pm_core.paths.get_global_setting",
                        lambda *a, **k: False)
    monkeypatch.setattr(
        "pm_core.model_config.resolve_model_and_provider",
        lambda *a, **k: SimpleNamespace(model=None, provider=None,
                                        effort=None))
    monkeypatch.setattr(pr_mod.git_ops, "clone", fake_clone)
    monkeypatch.setattr(pr_mod.git_ops, "configure_dual_remote",
                        lambda *a, **k: None)
    monkeypatch.setattr(pr_mod.git_ops, "is_git_repo", lambda *a, **k: False)
    monkeypatch.setattr(pr_mod.git_ops, "checkout_branch",
                        lambda *a, **k: None)
    monkeypatch.setattr(pr_mod.git_ops, "run_git", fake_run_git)

    results: dict[str, str] = {}

    def run(tag: str) -> None:
        try:
            pr_mod.pr_start.callback(
                pr_id=PR, workdir=None, fresh=False, background=False,
                transcript=None, companion=False)
            results[tag] = "ok"
        except SystemExit as exc:  # pragma: no cover - asserted below
            results[tag] = f"exit {exc.code}"
        except Exception as exc:  # pragma: no cover - asserted below
            results[tag] = f"error {type(exc).__name__}: {exc}"

    first = threading.Thread(target=run, args=("first",))
    first.start()
    assert first_clone_entered.wait(10), "first start never reached the clone"
    second = threading.Thread(target=run, args=("second",))
    second.start()
    first.join(20)
    second.join(20)

    assert results == {"first": "ok", "second": "ok"}
    # The loser waited on the per-PR start lock and reused the winner's
    # workdir instead of cloning into the shared `.tmp-<id>` path again.
    assert len(clone_calls) == 1, clone_calls

    reloaded = store.get_pr(store.load(root), PR)
    assert reloaded["status"] == "in_progress"
    assert reloaded["workdir"]
    assert Path(reloaded["workdir"]).is_dir()
