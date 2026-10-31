"""Auto-commit a single PR's project.yaml row directly onto base_branch.

Used by `pm pr start` so users don't have to run `pm push` manually just to
land the new PR row before the start command will accept it.

The commit is built via git plumbing (hash-object, update-index in a
temp index, commit-tree, update-ref) so the working tree is never
checked out or modified beyond an optional real-index refresh when HEAD
happens to be on base_branch.
"""

from __future__ import annotations

import errno
import fcntl
import os
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

import yaml

from pm_core import git_ops
from pm_core.paths import session_dir
from pm_core.store import _YAML_HEADER


_LOCK_TIMEOUT_SECONDS = 30.0


@contextmanager
def _yaml_commit_lock(timeout: float = _LOCK_TIMEOUT_SECONDS):
    """Process-wide blocking flock on ~/.pm/sessions/<tag>/yaml-commit.lock.

    Yields the open fd. Raises TimeoutError if the lock can't be acquired
    within *timeout* seconds. If no session can be derived (no git root),
    falls back to a path under /tmp keyed on cwd so concurrent calls in
    the same process tree still serialize.
    """
    sd = session_dir()
    if sd is None:
        sd = Path(tempfile.gettempdir()) / "pm-yaml-commit-fallback"
        sd.mkdir(parents=True, exist_ok=True)
    lock_path = sd / "yaml-commit.lock"
    deadline = time.monotonic() + timeout
    fd = open(lock_path, "a")
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as e:
                if e.errno not in (errno.EACCES, errno.EAGAIN):
                    raise
                if time.monotonic() >= deadline:
                    fd.close()
                    raise TimeoutError(
                        f"timed out waiting on yaml-commit lock after {timeout}s"
                    ) from None
                time.sleep(0.1)
        yield fd
    finally:
        if not fd.closed:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
            fd.close()


def _serialize_yaml(data: dict) -> str:
    return _YAML_HEADER + yaml.dump(
        data, default_flow_style=False, sort_keys=False, allow_unicode=True
    )


def _load_committed(repo_root: str, base_branch: str, yaml_path: str) -> Optional[dict]:
    res = git_ops.run_git(
        "show", f"{base_branch}:{yaml_path}", cwd=repo_root, check=False
    )
    if res.returncode != 0:
        return None
    try:
        data = yaml.safe_load(res.stdout) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    return data


def _find_pr(data: dict, pr_id: str) -> Optional[dict]:
    for pr in data.get("prs") or []:
        if isinstance(pr, dict) and pr.get("id") == pr_id:
            return pr
    return None


def _verify_only_added_pr(committed: dict, synthetic: dict, pr_entry: dict) -> bool:
    """True iff `synthetic` differs from `committed` by exactly appending
    `pr_entry` to the `prs` list. No other key may change."""
    committed_keys = set(committed.keys()) | {"prs"}
    synthetic_keys = set(synthetic.keys()) | {"prs"}
    if committed_keys != synthetic_keys:
        return False
    for k in committed_keys:
        if k == "prs":
            continue
        if committed.get(k) != synthetic.get(k):
            return False
    old_prs = committed.get("prs") or []
    new_prs = synthetic.get("prs") or []
    if len(new_prs) != len(old_prs) + 1:
        return False
    if new_prs[:-1] != old_prs:
        return False
    if new_prs[-1] is not pr_entry and new_prs[-1] != pr_entry:
        return False
    return True


def commit_pr_entry_on_base(
    repo_root: str | Path,
    yaml_path: str,
    base_branch: str,
    pr_id: str,
    backend: str,
) -> tuple[bool, Optional[str]]:
    """Commit just `pr_id`'s project.yaml row onto `base_branch` and push.

    Returns (success, error_reason). On success, base_branch's tip on
    both local and (unless backend == "local") remote contains a single
    fast-forward commit adding the one PR entry. Working tree is never
    rewritten (a real-index refresh happens only if HEAD == base_branch
    so `git status` stays clean).
    """
    repo_root = str(repo_root)

    if not git_ops.is_git_repo(Path(repo_root)):
        return False, f"not a git repo: {repo_root}"

    # Read working yaml first (cheap, outside the lock) just to find the entry.
    workdir_yaml_path = Path(repo_root) / yaml_path
    try:
        with open(workdir_yaml_path) as f:
            working_data = yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError) as e:
        return False, f"could not read working {yaml_path}: {e}"
    if not isinstance(working_data, dict):
        return False, f"working {yaml_path} is not a mapping"
    pr_entry = _find_pr(working_data, pr_id)
    if pr_entry is None:
        return False, f"PR {pr_id} not found in working {yaml_path}"

    try:
        with _yaml_commit_lock():
            return _commit_locked(
                repo_root, yaml_path, base_branch, pr_id, pr_entry, backend
            )
    except TimeoutError as e:
        return False, str(e)


def _commit_locked(
    repo_root: str,
    yaml_path: str,
    base_branch: str,
    pr_id: str,
    pr_entry: dict,
    backend: str,
) -> tuple[bool, Optional[str]]:
    # If we have a remote, fetch base so we don't try to push a non-FF.
    if backend != "local":
        fetch = git_ops.run_git(
            "fetch", "origin", base_branch, cwd=repo_root, check=False
        )
        if fetch.returncode == 0:
            # Fast-forward local base_branch to remote if remote is ahead and
            # the user isn't currently on base_branch (avoid touching worktree).
            head = git_ops.run_git(
                "rev-parse", "--abbrev-ref", "HEAD", cwd=repo_root, check=False
            ).stdout.strip()
            if head != base_branch:
                local = git_ops.run_git(
                    "rev-parse", base_branch, cwd=repo_root, check=False
                ).stdout.strip()
                remote = git_ops.run_git(
                    "rev-parse", f"origin/{base_branch}", cwd=repo_root, check=False
                ).stdout.strip()
                if local and remote and local != remote:
                    # Is local an ancestor of remote? If so, FF.
                    is_anc = git_ops.run_git(
                        "merge-base", "--is-ancestor", local, remote,
                        cwd=repo_root, check=False,
                    )
                    if is_anc.returncode == 0:
                        ff = git_ops.run_git(
                            "update-ref", f"refs/heads/{base_branch}",
                            remote, local, cwd=repo_root, check=False,
                        )
                        if ff.returncode != 0:
                            return False, "could not fast-forward local base"

    committed = _load_committed(repo_root, base_branch, yaml_path)
    if committed is None:
        return False, f"could not read {yaml_path} on {base_branch}"

    # Already there — caller can proceed.
    if _find_pr(committed, pr_id) is not None:
        return True, None

    # Plan reference must already be committed.
    plan_id = pr_entry.get("plan")
    if plan_id:
        committed_plan_ids = {
            (p.get("id") if isinstance(p, dict) else None)
            for p in (committed.get("plans") or [])
        }
        if plan_id not in committed_plan_ids:
            return (
                False,
                f"plan {plan_id} is not committed on {base_branch}; "
                f"run `pm push` to land it together with the PR row",
            )

    # Build synthetic content.
    synthetic = dict(committed)
    new_prs = list(committed.get("prs") or [])
    new_prs.append(pr_entry)
    synthetic["prs"] = new_prs

    if not _verify_only_added_pr(committed, synthetic, pr_entry):
        return False, "synthetic diff is not exactly one new PR row"

    new_yaml_text = _serialize_yaml(synthetic)

    base_commit = git_ops.run_git(
        "rev-parse", base_branch, cwd=repo_root, check=False
    ).stdout.strip()
    if not base_commit:
        return False, f"could not resolve {base_branch}"

    # Hash the new yaml as a blob.
    blob_proc = subprocess.run(
        ["git", "hash-object", "-w", "--stdin", "--path", yaml_path],
        cwd=repo_root, input=new_yaml_text, text=True, capture_output=True,
    )
    if blob_proc.returncode != 0:
        return False, f"hash-object failed: {blob_proc.stderr.strip()}"
    blob = blob_proc.stdout.strip()

    # Build the new tree in a temp index.
    with tempfile.NamedTemporaryFile(
        prefix="pm-yaml-idx-", delete=False
    ) as tf:
        temp_index = tf.name
    try:
        env = os.environ.copy()
        env["GIT_INDEX_FILE"] = temp_index
        rt = subprocess.run(
            ["git", "read-tree", base_commit],
            cwd=repo_root, env=env, capture_output=True, text=True,
        )
        if rt.returncode != 0:
            return False, f"read-tree failed: {rt.stderr.strip()}"
        ui = subprocess.run(
            ["git", "update-index", "--cacheinfo", f"100644,{blob},{yaml_path}"],
            cwd=repo_root, env=env, capture_output=True, text=True,
        )
        if ui.returncode != 0:
            return False, f"update-index failed: {ui.stderr.strip()}"
        wt = subprocess.run(
            ["git", "write-tree"],
            cwd=repo_root, env=env, capture_output=True, text=True,
        )
        if wt.returncode != 0:
            return False, f"write-tree failed: {wt.stderr.strip()}"
        tree = wt.stdout.strip()
    finally:
        try:
            os.unlink(temp_index)
        except OSError:
            pass

    msg = f"pm: add {pr_id} entry on {base_branch}"
    ct = git_ops.run_git(
        "commit-tree", tree, "-p", base_commit, "-m", msg,
        cwd=repo_root, check=False,
    )
    if ct.returncode != 0:
        return False, f"commit-tree failed: {ct.stderr.strip()}"
    new_commit = ct.stdout.strip()

    # Atomically advance base_branch only if it still points at base_commit.
    ur = git_ops.run_git(
        "update-ref", f"refs/heads/{base_branch}", new_commit, base_commit,
        cwd=repo_root, check=False,
    )
    if ur.returncode != 0:
        return False, f"base advanced under us: {ur.stderr.strip()}"

    # If HEAD is on base_branch, refresh the real index so `git status`
    # doesn't show the new PR row as missing.
    head = git_ops.run_git(
        "rev-parse", "--abbrev-ref", "HEAD", cwd=repo_root, check=False
    ).stdout.strip()
    head_was_base = head == base_branch
    if head_was_base:
        git_ops.run_git(
            "update-index", "--cacheinfo", f"100644,{blob},{yaml_path}",
            cwd=repo_root, check=False,
        )

    if backend == "local":
        return True, None

    push = git_ops.run_git(
        "push", "origin", f"{base_branch}:{base_branch}",
        cwd=repo_root, check=False,
    )
    if push.returncode != 0:
        # Roll back local ref and (if applied) real-index update.
        git_ops.run_git(
            "update-ref", f"refs/heads/{base_branch}", base_commit, new_commit,
            cwd=repo_root, check=False,
        )
        if head_was_base:
            old_blob = git_ops.run_git(
                "rev-parse", f"{base_commit}:{yaml_path}",
                cwd=repo_root, check=False,
            ).stdout.strip()
            if old_blob:
                git_ops.run_git(
                    "update-index", "--cacheinfo",
                    f"100644,{old_blob},{yaml_path}",
                    cwd=repo_root, check=False,
                )
        return False, f"push rejected: {push.stderr.strip()}"

    return True, None
