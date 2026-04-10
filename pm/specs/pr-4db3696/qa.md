# QA Spec for PR pr-4db3696: Add pm pr split command for breaking large PRs into smaller pieces

## Requirements

### 1. `pm pr split <pr_id>` CLI command (`pm_core/cli/pr.py`)
- Accepts optional `pr_id` (auto-selects active PR if omitted)
- Accepts `--fresh` flag to force a new session (kills existing tmux window or clears saved session)
- Validates the PR exists via `_require_pr(data, pr_id)`
- Requires a workdir to exist for the PR (errors with helpful message if missing)
- Generates a split-specific prompt via `prompt_gen.generate_split_prompt()`
- Launches Claude in the PR's workdir via tmux window (window name `split-<display_id>`)
- Falls back to terminal launch if tmux is unavailable
- If Claude CLI not found, prints the prompt to stdout
- Resumes existing tmux window if one exists (unless `--fresh`)

### 2. Split prompt generation (`pm_core/prompt_gen.py:generate_split_prompt()`)
- Includes PR title, description, and diff command
- Includes plan context if the PR belongs to a plan
- Includes impl spec context if one exists
- Includes dependency context for the PR
- Includes PR notes (addendums)
- Instructs Claude to write a split manifest at `pm/specs/<pr_id>/split.md`
- Uses backend-appropriate refs (`origin/<base>` for vanilla/GitHub, `<base>` for local)
- Instructs the user to run `split-load` from the project root (not the workdir)

### 3. Split manifest parsing (`pm_core/plan_parser.py:parse_split_prs()`)
- Parses `## Child PRs` section with `### PR:` blocks
- Extracts `title`, `description`, `branch`, `depends_on` fields
- Returns empty list for missing section or empty input
- Missing fields default to empty string

### 4. `pm pr split-load <pr_id>` CLI command (`pm_core/cli/pr.py`)
- Reads manifest from the workdir's `pm/specs/<pr_id>/split.md` (not project root)
- Parses child PRs via `parse_split_prs()`
- Pre-computes all PR IDs before creating entries (for dependency resolution)
- For each child PR:
  - Pushes branch from workdir (skips push for local backend)
  - Generates PR ID via `store.generate_pr_id()`
  - Resolves `depends_on` titles to PR IDs
  - Creates PR entry and appends to project data
- Skips child PRs whose titles already exist in project.yaml
- Inherits `plan` field from parent PR
- Saves state and triggers TUI refresh
- Generates fallback branch name if manifest branch is empty

### 5. TUI keybinding (`pm_core/tui/app.py`)
- `a` keybinding bound to `action_split_pr()`
- Action is blocked when command bar is focused, in guide mode, or when no PRs exist
- Added to both `check_action` guard sets

### 6. TUI action delegate (`pm_core/tui/pr_view.py:split_pr()`)
- Gets selected PR from tech tree
- Checks for existing split manifest in workdir
- If manifest exists (and not fresh): runs `pm pr split-load` instead of split session
- If no manifest (or fresh): launches `pm pr split` session
- Uses `_consume_z()` for the `--fresh` modifier
- Guarded by `guard_pr_action()` for concurrent action protection
- `"pr split"` added to `PR_ACTION_PREFIXES` for in-flight tracking

## Setup

Testing requires:
1. A project initialized with `pm init --backend local --no-import`
2. At least one PR added with `pm pr add` that has been started (has a workdir)
3. For split-load testing: a pre-written split manifest at the correct path in the workdir
4. Python environment with pm installed (`pip install -e .`)
5. For TUI testing: a tmux session via `pm session`
6. For backend tests: separate projects with local and vanilla backends

## Edge Cases

1. **No PR specified, no active PR** -- `pm pr split` with no argument and no active PR should error with "No PR specified and no active PR."
2. **PR without workdir** -- Should error with message suggesting `pm pr start` first
3. **Missing manifest** -- `pm pr split-load` when no manifest file exists should error "Split manifest not found"
4. **Empty manifest** -- Manifest with `## Child PRs` section but no `### PR:` blocks should error "No child PRs found"
5. **Manifest with no `## Child PRs` section** -- `parse_split_prs()` returns `[]`, split-load errors
6. **Duplicate child PR title** -- If a child title matches an existing PR, it's skipped with "already exists"
7. **Branch push failure** -- For non-local backends, a failed push logs a warning but continues creating the PR entry
8. **Unknown dependency title** -- `depends_on` referencing a nonexistent child title logs a warning
9. **Manifest in workdir vs project root** -- Manifest is read from the workdir's pm/specs/ path, not the main project root
10. **`--fresh` flag** -- Kills existing tmux window or clears session state before starting
11. **Existing tmux window without `--fresh`** -- Switches to existing window instead of creating new one
12. **Local backend** -- Skips `git push` for child branches (no remote)
13. **Plan inheritance** -- Child PRs inherit the parent's `plan` field; standalone PRs get `plan=None`
14. **z-prefix in TUI** -- `z a` triggers fresh split, plain `a` triggers normal split
15. **TUI manifest detection** -- `split_pr()` checks workdir for existing manifest, runs split-load if found

## Pass/Fail Criteria

### Pass
- `parse_split_prs()` correctly parses valid manifests (verified by existing unit tests)
- `pm pr split` generates a prompt containing the PR title, diff command, manifest path, and branch naming convention
- `pm pr split` errors gracefully when PR has no workdir
- `pm pr split-load` creates correct PR entries in project.yaml with proper IDs, branches, dependencies, and plan inheritance
- `pm pr split-load` skips push for local backend
- `pm pr split-load` skips already-existing PRs
- TUI `a` keybinding dispatches correctly (split or split-load depending on manifest existence)
- TUI action guards block split during other in-flight actions

### Fail
- Manifest parsing returns wrong fields or wrong number of entries
- `split-load` reads manifest from project root instead of workdir
- `split-load` attempts to push branches on local backend
- Dependency resolution fails (title-to-ID mapping broken)
- TUI `a` keybinding fires during command bar input or guide mode
- `--fresh` flag doesn't clear existing session/window

## Ambiguities

1. **Where does split-load read the manifest from?**
   Resolution: The workdir's pm/specs/ directory, found via `store.find_project_root(start=workdir)`. The split agent writes the manifest inside the workdir (which has its own pm/ directory), not the main project root. This was fixed in commit a6c6aa0.

2. **Should split-load push branches for local backend?**
   Resolution: No. The code explicitly checks `backend_name != "local"` before pushing. Local backend has no remote.

3. **What happens when TUI detects an existing manifest?**
   Resolution: If a manifest exists and the user didn't press `z` first, the TUI runs `split-load` directly instead of launching a new split session. This is a convenience shortcut so the user doesn't need to manually run split-load.

4. **How does the z-prefix interact with manifest detection?**
   Resolution: `z a` sets `fresh=True`, which bypasses the manifest check and always launches a new split session. This allows re-splitting even when a manifest already exists.

5. **Should `split-load` error or silently succeed when all children already exist?**
   Resolution: It skips each existing child with a "Skipped" message but still prints a summary. If no new children are created, `created == 0` so no save/push happens.

## Mocks

### Claude CLI / Session
- **Contract**: The `find_claude()` function returns the path to the Claude CLI binary or `None`. The `launch_claude()` function starts an interactive session. The `build_claude_shell_cmd()` function produces a shell command string.
- **Scripted responses**: For unit/integration tests, mock `find_claude()` to return `None` so the prompt is printed to stdout (testable). For TUI tests, mock the entire launch path. No actual Claude sessions should be started.
- **Unmocked**: `generate_split_prompt()` and `parse_split_prs()` — these are pure functions that can be tested directly.

### tmux
- **Contract**: `tmux_mod.session_exists()`, `tmux_mod.find_window_by_name()`, `tmux_mod.new_window()`, `tmux_mod.select_window()`, `tmux_mod.kill_window()`.
- **Scripted responses**: For CLI tests, mock `_get_pm_session()` to return `None` so the terminal fallback path is taken. For TUI integration, the session setup handles tmux naturally.
- **Unmocked**: TUI manual testing uses real tmux.

### git operations
- **Contract**: `git_ops.run_git("push", "-u", "origin", branch, cwd=workdir, check=False)` returns a `CompletedProcess` with `returncode` and `stderr`.
- **Scripted responses**: For local backend tests, push is skipped entirely. For unit tests of split-load, mock `git_ops.run_git` to return success or simulate push failures.
- **Unmocked**: Branch creation (done by the split agent, not tested here) and the real git state in manual TUI tests.

### store / project state
- **Contract**: `store.load()`, `store.get_pr()`, `store.generate_pr_id()`, `save_and_push()`.
- **Scripted responses**: For unit tests, construct project data dicts directly. For integration tests, use a real `pm init --backend local` project.
- **Unmocked**: All store operations in integration and manual tests use real project.yaml.
