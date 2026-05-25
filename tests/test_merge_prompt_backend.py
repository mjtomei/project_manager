"""Tests for backend-specific merge-conflict resolution prompts.

Regression coverage for pr-8d8b360: on the GitHub backend the merge-resolution
prompt must keep GitHub as the merger (merge master into the PR branch, push the
branch, re-run `gh pr merge`) and must NOT instruct a local `git push origin
master`, which bypasses GitHub.
"""

from pm_core import prompt_gen


def _data(backend: str) -> dict:
    return {
        "project": {
            "base_branch": "master",
            "backend": backend,
            "repo": "https://github.com/x/y" if backend == "github" else "/tmp/origin",
        },
        "prs": [{
            "id": "pr-test",
            "title": "Some change",
            "branch": "pm/pr-test",
            "workdir": "/tmp/wd",
            "gh_pr_number": 212,
        }],
    }


def test_github_merge_prompt_merges_master_into_branch_and_reruns_gh():
    p = prompt_gen.generate_merge_prompt(_data("github"), "pr-test", "not mergeable")
    # Merge direction: master INTO the PR branch.
    assert "INTO the PR branch" in p
    assert "pm/pr-test" in p
    # Push the branch (not master).
    assert "Push the PR branch" in p
    # Re-run the GitHub merge with the PR number.
    assert "gh pr merge 212 --merge" in p


def test_github_merge_prompt_fast_forwards_main_repo_itself():
    # pm's post-MERGED propagation re-attempt can be killed by a concurrent
    # sync (pr-6bf587b), so the agent fast-forwards the main repo itself.
    p = prompt_gen.generate_merge_prompt(_data("github"), "pr-test", "not mergeable")
    # The two directories are spelled out distinctly.
    assert "PR-branch workdir" in p
    assert "Main repo checkout" in p
    # Fast-forward only — never a local merge commit on master, never a push.
    assert "merge --ff-only origin/master" in p
    assert "fetch origin" in p
    # The fast-forward targets the main repo checkout, not the workdir.
    assert "main repo checkout" in p.lower()


def test_github_merge_prompt_two_directories_are_different(monkeypatch):
    # The workdir (agent cwd) and the resolved main repo dir must be distinct,
    # so the agent can't confuse them.
    from pm_core.cli import helpers
    monkeypatch.setattr(helpers, "_resolve_repo_dir", lambda root, data: __import__("pathlib").Path("/main/repo"))
    p = prompt_gen.generate_merge_prompt(_data("github"), "pr-test", "not mergeable")
    assert "/tmp/wd" in p          # the PR-branch workdir
    assert "/main/repo" in p       # the main repo checkout
    assert "git -C /main/repo merge --ff-only origin/master" in p


def test_github_merge_prompt_does_not_push_master():
    p = prompt_gen.generate_merge_prompt(_data("github"), "pr-test", "not mergeable")
    # No positive instruction to push the merged master to origin.
    assert "push the merged `master` to origin" not in p.lower()
    assert "Push the merged `master`" not in p
    # Pushing master directly is explicitly prohibited.
    assert "do NOT `git push origin master`" in p
    # The only "push origin master" mention is the prohibition, never a step.
    assert "git push origin master" not in p.replace(
        "do NOT `git push origin master`", "")


def test_local_merge_prompt_unchanged_no_push():
    p = prompt_gen.generate_merge_prompt(_data("local"), "pr-test", "conflict")
    assert "local backend" in p.lower()
    assert "commit the merge on `master` in this workdir" in p
    # Local backend never instructs a push to origin.
    assert "push the merged" not in p.lower()
    assert "git push origin" not in p
    # No gh pr merge on local.
    assert "gh pr merge" not in p


def test_vanilla_merge_prompt_still_pushes_master():
    p = prompt_gen.generate_merge_prompt(_data("vanilla"), "pr-test", "conflict")
    # Vanilla legitimately pushes the merged master to origin.
    assert "push the merged `master` to origin" in p.lower()
    assert "gh pr merge" not in p
