#!/usr/bin/env python3
"""Integration test: fallback (no upstream) path — monkey-patches
resolve_real_origin to None to force the legacy fetch-into-target branch."""
import os, subprocess, sys, tempfile, time
from pathlib import Path
from unittest import mock

sys.path.insert(0, "/workspace")
import pm_core.push_proxy as pp
from pm_core.push_proxy import PushProxy

GIT = "/usr/bin/git"


def run(cmd, cwd=None, check=True):
    if cmd and cmd[0] == "git":
        cmd = [GIT] + cmd[1:]
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if check and r.returncode != 0:
        print("FAIL:", cmd, r.stderr)
        sys.exit(1)
    return r.stdout.strip()


def main():
    base = Path(tempfile.mkdtemp(prefix=f"proxy-it-fb-{int(time.time())}-"))
    print(f"== base: {base}")

    pr_workdir = base / "pr-workdir-nolocal"
    caller = base / "caller2"
    branch = "pm/pr-test-feature"

    # Init pr-workdir as a non-bare repo, no origin remote.
    run(["git", "init", "-b", "master", str(pr_workdir)])
    (pr_workdir / "init.txt").write_text("init\n")
    run(["git", "add", "init.txt"], cwd=pr_workdir)
    run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit",
         "-m", "init"], cwd=pr_workdir)
    run(["git", "checkout", "-b", branch], cwd=pr_workdir)
    (pr_workdir / "feat.txt").write_text("feat\n")
    run(["git", "add", "feat.txt"], cwd=pr_workdir)
    run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit",
         "-m", "feat init"], cwd=pr_workdir)
    # Move HEAD off feature branch so fetch --update-head-ok isn't blocked.
    run(["git", "checkout", "master"], cwd=pr_workdir)

    run(["git", "clone", str(pr_workdir), str(caller)])
    run(["git", "checkout", branch], cwd=caller)
    (caller / "caller-new.txt").write_text("from caller\n")
    run(["git", "add", "caller-new.txt"], cwd=caller)
    run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit",
         "-m", "caller commit"], cwd=caller)
    caller_sha = run(["git", "rev-parse", "HEAD"], cwd=caller)

    print(f"== caller new commit sha: {caller_sha}")

    sock = base / "proxy.sock"
    proxy = PushProxy(socket_path=str(sock), workdir=str(pr_workdir),
                      allowed_branch=branch)

    orig_path = os.environ["PATH"]
    os.environ["PATH"] = "/usr/bin:" + orig_path
    try:
        with mock.patch.object(pp, "resolve_real_origin", return_value=None):
            result = proxy._local_push(
                target_repo=str(pr_workdir), branch=branch,
                caller_workdir=str(caller),
            )
    finally:
        os.environ["PATH"] = orig_path

    print(f"== _local_push result: {result}")
    pr_branch_sha = run(["git", "rev-parse", f"refs/heads/{branch}"],
                        cwd=pr_workdir)
    status = run(["git", "status", "--porcelain"], cwd=pr_workdir, check=False)
    print(f"== pr_workdir branch sha (fallback path): {pr_branch_sha}")
    print(f"== pr_workdir status (worktree stale is OK): {status!r}")

    assert result["exit_code"] == 0, f"exit_code != 0: {result}"
    assert pr_branch_sha == caller_sha, (
        f"fallback should have updated branch ref: {pr_branch_sha} vs {caller_sha}")
    print("== FALLBACK ASSERTIONS PASSED ==")


if __name__ == "__main__":
    main()
