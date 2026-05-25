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


def test_github_merge_prompt_leaves_local_repo_pull_to_pm():
    # pm pulls master into the main repo via --propagation-only; the agent
    # (in the PR-branch workdir) must not touch the main checkout itself.
    p = prompt_gen.generate_merge_prompt(_data("github"), "pr-test", "not mergeable")
    assert "Do NOT touch the main repo" in p
    assert "pm pulls the merged `master` into it automatically" in p
    # No step instructing the agent to pull master into the local repo.
    assert "Pull `master` into the local repo" not in p


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
