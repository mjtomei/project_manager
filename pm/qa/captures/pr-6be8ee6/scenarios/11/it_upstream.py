#!/usr/bin/env python3
"""Integration test: upstream-present path."""
import os, subprocess, sys, tempfile, time
from pathlib import Path

sys.path.insert(0, "/workspace")
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
    base = Path(tempfile.mkdtemp(prefix=f"proxy-it-up-{int(time.time())}-"))
    print(f"== base: {base}")

    real_upstream = base / "real-upstream.git"  # represents github
    upstream = base / "upstream.git"            # local mirror
    pr_workdir = base / "pr-workdir"
    caller = base / "caller"

    run(["git", "init", "--bare", "-b", "master", str(real_upstream)])
    run(["git", "init", "--bare", "-b", "master", str(upstream)])
    # Give upstream.git a "real" remote via file:// URL so resolve_real_origin
    # treats it as terminal (has "://", not a local path).
    run(["git", "-C", str(upstream), "remote", "add", "origin",
         f"file://{real_upstream}"])

    # Seed an initial commit on master via a temp clone, then push to upstream.
    seed = base / "seed"
    run(["git", "clone", str(upstream), str(seed)])
    run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit",
         "--allow-empty", "-m", "init"], cwd=seed)
    run(["git", "push", "origin", "master"], cwd=seed)

    # Create the PR workdir, branch off feature.
    run(["git", "clone", str(upstream), str(pr_workdir)])
    branch = "pm/pr-test-feature"
    run(["git", "checkout", "-b", branch], cwd=pr_workdir)
    (pr_workdir / "base.txt").write_text("base\n")
    run(["git", "add", "base.txt"], cwd=pr_workdir)
    run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit",
         "-m", "feature init"], cwd=pr_workdir)
    run(["git", "push", "-u", "origin", branch], cwd=pr_workdir)

    # Caller clones pr-workdir (so its origin is local pr-workdir, mimicking scenario clone).
    run(["git", "clone", str(pr_workdir), str(caller)])
    run(["git", "checkout", branch], cwd=caller)
    (caller / "new-file.txt").write_text("from caller\n")
    run(["git", "add", "new-file.txt"], cwd=caller)
    run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit",
         "-m", "caller commit"], cwd=caller)

    caller_sha = run(["git", "rev-parse", "HEAD"], cwd=caller)
    pre_pr_sha = run(["git", "rev-parse", "HEAD"], cwd=pr_workdir)
    pre_status = run(["git", "status", "--porcelain"], cwd=pr_workdir, check=False)

    print(f"== pre pr_workdir HEAD: {pre_pr_sha}")
    print(f"== pre pr_workdir status (should be empty): {pre_status!r}")
    print(f"== caller new commit sha: {caller_sha}")

    sock = base / "proxy.sock"
    proxy = PushProxy(socket_path=str(sock), workdir=str(pr_workdir),
                      allowed_branch=branch)
    # Make subprocess "git" calls inside _local_push hit real git, not the
    # outer push-proxy wrapper that fronts QA scenarios.
    orig_path = os.environ["PATH"]
    os.environ["PATH"] = "/usr/bin:" + orig_path
    try:
        result = proxy._local_push(
            target_repo=str(pr_workdir), branch=branch, caller_workdir=str(caller),
        )
    finally:
        os.environ["PATH"] = orig_path
    print(f"== _local_push result: {result}")

    post_pr_sha = run(["git", "rev-parse", "HEAD"], cwd=pr_workdir)
    post_status = run(["git", "status", "--porcelain"], cwd=pr_workdir, check=False)
    # Push lands on real_upstream (the terminal real URL), not upstream.git.
    upstream_branch_sha = run(["git", "rev-parse", f"refs/heads/{branch}"], cwd=real_upstream)

    print(f"== post pr_workdir HEAD: {post_pr_sha}")
    print(f"== post pr_workdir status: {post_status!r}")
    print(f"== upstream branch sha: {upstream_branch_sha}")

    assert result["exit_code"] == 0, f"exit_code != 0: {result}"
    assert post_status == "", f"phantom changes in pr_workdir: {post_status}"
    assert post_pr_sha == pre_pr_sha, f"pr_workdir HEAD mutated: {pre_pr_sha} -> {post_pr_sha}"
    assert upstream_branch_sha == caller_sha, f"upstream not updated: {upstream_branch_sha} vs {caller_sha}"

    print("== ALL ASSERTIONS PASSED ==")


if __name__ == "__main__":
    main()
