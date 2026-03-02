# Bugs

Bugs discovered by the autonomous monitor.

## PRs

### PR: Fix dependency code not propagated to new workdir masters
- **description**: When `pm pr start` creates a new workdir for a PR with merged dependencies, it clones from the main repo's master branch. However, merged PRs only update the master branch within their own workdir — the main repo's master is never updated. This means new workdirs start without any dependency code. Observed with pr-ee57619 (Mobile Amazon login screen): its workdir had no `mobile/` or `backend/` directories despite depending on 9 merged PRs that created those directories. The implementation Claude session had to merge dependency branches manually (for branches that existed in origin) and recreate code from scratch (for branches that were never pushed to origin). This will cause merge conflicts and inconsistencies when the PR is later integrated with the accumulated codebase.
- **tests**: Create a workdir for a PR whose dependencies are all merged. Verify the workdir's master branch includes all dependency merge commits. Verify the workdir contains all files from merged dependency PRs.
- **files**: The workdir creation logic in `pm pr start` — needs to merge all transitive dependency branches into the new workdir's master before creating the implementation branch. Also, `pm pr merge` should push the updated master back to the main repo (or at minimum push the PR branch so downstream workdirs can access it).

### PR: Fix merged PR branches not pushed to main repo origin
- **description**: When PRs are merged via `pm pr merge`, the merge commit goes into the workdir's local master but the PR branch is never pushed to the main repo. This means downstream PRs in new workdirs cannot access the code via `git fetch origin`. Observed: branches for pr-f1dfab0, pr-981a205, pr-c9e9a2c, pr-a8d9758, pr-50b3380 (the entire mobile track) don't exist in the main repo, while branches for pr-0804bb2, pr-72421ed, pr-79c1ed6, pr-9942e24 do exist (likely because they were pushed during implementation). This inconsistency means some dependency code is accessible and some is not.
- **tests**: After `pm pr merge`, verify the merged master is pushed back to the main repo. Or verify the PR branch remains available in origin for downstream consumers.
- **files**: `pm pr merge` logic — should push updated master to origin after merge, or at minimum ensure PR branches remain accessible.

### PR: Fix trust prompt blocking implementation sessions
- **description**: When `pm pr start` launches a Claude Code session in a new workdir, the session hits the "Is this a project you created or one you trust?" prompt and stalls. The TUI correctly detects this (`impl_idle: pr-ee57619 idle but showing interactive prompt, resetting`) but cannot auto-accept it. This requires manual intervention (sending Enter to the pane). The existing `--dangerously-skip-permissions` flag is too broad. The fix should either pre-accept the trust prompt via Claude Code settings/flags or have the TUI auto-send Enter when it detects the trust prompt pattern.
- **tests**: Start a PR implementation in a new workdir. Verify the Claude Code session starts without stalling at the trust prompt.
- **files**: Either the Claude Code launch command (add `--trust` flag or equivalent), or TUI logic to detect and auto-accept the prompt, or pre-configure `.claude/settings.json` in the workdir.

### PR: Fix auto-start not re-scanning after manual status changes
- **description**: Auto-start only scans for ready PRs on startup and after merge events. When PR statuses are manually changed (e.g., resetting broken in_progress PRs to pending), auto-start doesn't detect the newly-ready PRs until the next merge triggers a scan. This means manually-fixed PRs sit idle until something else happens.
- **tests**: Enable auto-start. Reset a PR with merged deps from in_progress to pending. Verify auto-start detects and starts it within a reasonable time (e.g., 30 seconds).
- **files**: Auto-start scan trigger logic — should watch for project.yaml file changes or run periodic scans.

### PR: Fix merge propagation overwriting project.yaml with stale PR branch data
- **description**: When `pm pr merge` merges a PR branch into master, the PR branch's project.yaml contains stale status data from when the branch was created. The merge commit overwrites master's project.yaml, reverting previously-merged PRs back to `in_review`. Observed with pr-a8d9758: its merge commit (4ccc687) reverted pr-981a205, pr-c9e9a2c, pr-72421ed, pr-9942e24 from `merged` back to `in_review`, and incorrectly set several `pending` PRs (pr-50b3380, pr-5b288df, pr-7673557, pr-7f73e7e) to `in_review`. The `pm pr merge --propagation-only` command only fixed the merged PR's own status, not the other corrupted entries. Fix should either: exclude project.yaml from PR branch merges (treat it as a merge-ignored file), always take master's version during merge conflicts on project.yaml, or have propagation verify all PR statuses against git history after merge.
- **tests**: Merge a PR whose branch has stale project.yaml (other PRs merged since branch creation). Verify all PR statuses in project.yaml remain correct after merge. Verify `--propagation-only` restores all corrupted statuses, not just the merged PR.
- **files**: `pm pr merge` logic — needs to handle project.yaml specially during merges. Also `--propagation-only` should validate/restore all PR statuses.
