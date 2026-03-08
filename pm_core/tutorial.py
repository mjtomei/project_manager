"""Interactive tutorial system for pm.

Provides three guided tutorial modules:
1. tmux basics — pane/window management with live hook-based detection
2. TUI navigation — exploring the pm tech tree and keybindings
3. git fundamentals — version control concepts with hands-on exercises

Progress is tracked in ~/.pm/tutorial/progress.json and persists across sessions.
"""

import json
import subprocess
from pathlib import Path

from pm_core.paths import pm_home


# ---------------------------------------------------------------------------
# Progress state management
# ---------------------------------------------------------------------------

TUTORIAL_DIR = pm_home() / "tutorial"
PROGRESS_FILE = TUTORIAL_DIR / "progress.json"

MODULES = ("tmux", "tui", "git")

# Steps for each module
TMUX_STEPS = [
    "switch_pane",
    "resize_pane",
    "create_window",
    "switch_window",
    "scroll_history",
    "split_pane",
]

TUI_STEPS = [
    "navigate_tree",
    "view_pr_details",
    "use_keybindings",
    "command_bar",
    "filter_sort",
    "explore_statuses",
]

GIT_STEPS = [
    "init_repo",
    "make_commit",
    "create_branch",
    "merge_branch",
    "understand_remotes",
    "resolve_conflict",
]

MODULE_STEPS = {
    "tmux": TMUX_STEPS,
    "tui": TUI_STEPS,
    "git": GIT_STEPS,
}


def _ensure_dir():
    TUTORIAL_DIR.mkdir(parents=True, exist_ok=True)


def load_progress() -> dict:
    """Load tutorial progress from disk."""
    _ensure_dir()
    if PROGRESS_FILE.exists():
        try:
            return json.loads(PROGRESS_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"modules": {}}


def save_progress(progress: dict) -> None:
    """Save tutorial progress to disk."""
    _ensure_dir()
    PROGRESS_FILE.write_text(json.dumps(progress, indent=2) + "\n")


def mark_step_complete(module: str, step: str) -> None:
    """Mark a tutorial step as complete."""
    valid_steps = MODULE_STEPS.get(module, [])
    if valid_steps and step not in valid_steps:
        return  # Ignore invalid step names silently
    progress = load_progress()
    modules = progress.setdefault("modules", {})
    mod_data = modules.setdefault(module, {"completed_steps": [], "current_step": None})
    if step not in mod_data["completed_steps"]:
        mod_data["completed_steps"].append(step)
    # Advance current step
    steps = MODULE_STEPS.get(module, [])
    completed = set(mod_data["completed_steps"])
    mod_data["current_step"] = None
    for s in steps:
        if s not in completed:
            mod_data["current_step"] = s
            break
    save_progress(progress)


def get_current_step(module: str) -> str | None:
    """Get the current (next incomplete) step for a module."""
    progress = load_progress()
    mod_data = progress.get("modules", {}).get(module, {})
    completed = set(mod_data.get("completed_steps", []))
    for step in MODULE_STEPS.get(module, []):
        if step not in completed:
            return step
    return None  # All done


def is_module_complete(module: str) -> bool:
    """Check if all steps in a module are complete."""
    return get_current_step(module) is None


def reset_progress(module: str | None = None) -> None:
    """Reset progress for a module or all modules."""
    progress = load_progress()
    if module:
        progress.get("modules", {}).pop(module, None)
    else:
        progress["modules"] = {}
    save_progress(progress)


def get_completion_summary() -> dict[str, tuple[int, int]]:
    """Get (completed, total) counts for each module."""
    progress = load_progress()
    result = {}
    for mod, steps in MODULE_STEPS.items():
        mod_data = progress.get("modules", {}).get(mod, {})
        completed = len(mod_data.get("completed_steps", []))
        result[mod] = (completed, len(steps))
    return result


# ---------------------------------------------------------------------------
# Hook script for tmux module — written to a temp file and executed by hooks
# ---------------------------------------------------------------------------

def write_hook_script() -> Path:
    """Write the hook helper script that tmux hooks call to update progress."""
    script = TUTORIAL_DIR / "hook_helper.sh"
    _ensure_dir()
    # This script is called by tmux hooks with the step name as $1.
    # Validate the step name against a whitelist to avoid injection.
    valid_steps = " ".join(TMUX_STEPS)
    script.write_text(f"""\
#!/usr/bin/env bash
# Called by tmux hooks to mark tutorial steps complete
STEP="$1"
VALID_STEPS="{valid_steps}"
# Validate step name against whitelist
for s in $VALID_STEPS; do
    if [ "$STEP" = "$s" ]; then
        python3 -c "
import sys
from pm_core.tutorial import mark_step_complete
mark_step_complete('tmux', sys.argv[1])
" "$STEP" 2>/dev/null
        exit 0
    fi
done
""")
    script.chmod(0o755)
    return script


# ---------------------------------------------------------------------------
# Tmux module setup
# ---------------------------------------------------------------------------

def setup_tmux_session() -> str:
    """Create a fresh tmux session for the tmux tutorial module.

    Returns the socket path. Uses a dedicated socket to avoid
    interfering with existing pm sessions.
    """
    session_name = "pm-tutorial-tmux"
    socket_path = str(TUTORIAL_DIR / "tutorial.sock")

    # Kill existing tutorial session if any
    subprocess.run(
        ["tmux", "-S", socket_path, "kill-session", "-t", session_name],
        capture_output=True,
    )

    # Create session with two panes (horizontal split)
    subprocess.run(
        ["tmux", "-S", socket_path, "new-session", "-d", "-s", session_name,
         "-n", "tutorial", "-x", "200", "-y", "50"],
        check=True,
    )

    # Enable mouse mode
    subprocess.run(
        ["tmux", "-S", socket_path, "set-option", "-t", session_name,
         "mouse", "on"],
        check=True,
    )

    # Split horizontally: left = Claude guidance, right = playground
    subprocess.run(
        ["tmux", "-S", socket_path, "split-window", "-h", "-t",
         f"{session_name}:tutorial"],
        check=True,
    )

    # Write hook script
    hook_script = write_hook_script()

    # Register tmux hooks to detect user actions
    hooks = {
        "after-select-pane": "switch_pane",
        "after-resize-pane": "resize_pane",
        "after-select-window": "switch_window",
        "window-linked": "create_window",
        "after-split-window": "split_pane",
    }
    for hook, step in hooks.items():
        subprocess.run(
            ["tmux", "-S", socket_path, "set-hook", "-t", session_name,
             hook, f'run-shell "{hook_script} {step}"'],
            capture_output=True,
        )

    # Create a second window so user can practice switching
    subprocess.run(
        ["tmux", "-S", socket_path, "new-window", "-t", f"{session_name}:",
         "-n", "practice"],
        check=True,
    )
    # Go back to tutorial window
    subprocess.run(
        ["tmux", "-S", socket_path, "select-window", "-t",
         f"{session_name}:tutorial"],
        capture_output=True,
    )

    return socket_path


# ---------------------------------------------------------------------------
# TUI module setup — creates example project data
# ---------------------------------------------------------------------------

def setup_tui_project() -> Path:
    """Create a temporary project directory with example PRs for the TUI tutorial.

    Returns the path to the temporary pm directory.
    """
    from pm_core import store

    tui_dir = TUTORIAL_DIR / "tui-project"
    tui_dir.mkdir(parents=True, exist_ok=True)

    # Initialize a minimal project
    if not (tui_dir / "project.yaml").exists():
        store.init_project(tui_dir, "tutorial-project",
                           str(tui_dir), "main", backend="local")

    data = store.load(tui_dir)

    # Only create example PRs if none exist
    if not data.get("prs"):
        example_prs = [
            {"id": "pr-001", "title": "Add user authentication",
             "status": "merged", "depends_on": [], "branch": "feat/auth",
             "description": "Implement basic user authentication with JWT tokens"},
            {"id": "pr-002", "title": "Create database schema",
             "status": "merged", "depends_on": [], "branch": "feat/db-schema",
             "description": "Set up PostgreSQL schema with migrations"},
            {"id": "pr-003", "title": "Build REST API endpoints",
             "status": "in_review", "depends_on": ["pr-001", "pr-002"],
             "branch": "feat/api",
             "description": "REST API for CRUD operations on all entities"},
            {"id": "pr-004", "title": "Frontend dashboard",
             "status": "in_progress", "depends_on": ["pr-003"],
             "branch": "feat/dashboard",
             "description": "React dashboard with charts and data tables"},
            {"id": "pr-005", "title": "Add CI/CD pipeline",
             "status": "pending", "depends_on": ["pr-003"],
             "branch": "feat/cicd",
             "description": "GitHub Actions workflow for testing and deployment"},
            {"id": "pr-006", "title": "Write API documentation",
             "status": "pending", "depends_on": ["pr-003"],
             "branch": "feat/docs",
             "description": "OpenAPI/Swagger documentation for all endpoints"},
            {"id": "pr-007", "title": "Performance optimization",
             "status": "qa", "depends_on": ["pr-004"],
             "branch": "feat/perf",
             "description": "Database query optimization and caching layer"},
            {"id": "pr-008", "title": "Mobile responsive design",
             "status": "closed", "depends_on": ["pr-004"],
             "branch": "feat/mobile",
             "description": "Responsive CSS for mobile devices (descoped)"},
        ]

        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        prs = []
        for pr in example_prs:
            prs.append({
                "id": pr["id"],
                "plan": "plan-001",
                "title": pr["title"],
                "branch": pr["branch"],
                "status": pr["status"],
                "depends_on": pr["depends_on"],
                "description": pr["description"],
                "agent_machine": None,
                "gh_pr": None,
                "gh_pr_number": None,
                "created_at": now,
                "updated_at": now,
                "started_at": now if pr["status"] != "pending" else None,
                "reviewed_at": now if pr["status"] == "in_review" else None,
                "merged_at": now if pr["status"] == "merged" else None,
                "notes": [],
            })

        data["prs"] = prs
        data["plans"] = [{
            "id": "plan-001",
            "name": "Build a web application",
            "file": "plans/web-app.md",
            "status": "active",
        }]

        # Create plan file
        plans_dir = tui_dir / "plans"
        plans_dir.mkdir(exist_ok=True)
        (plans_dir / "web-app.md").write_text(
            "# Build a Web Application\n\n"
            "Full-stack web application with authentication, REST API, "
            "and a React frontend dashboard.\n\n"
            "## PRs\n"
            "- pr-001: Add user authentication\n"
            "- pr-002: Create database schema\n"
            "- pr-003: Build REST API endpoints\n"
            "- pr-004: Frontend dashboard\n"
            "- pr-005: Add CI/CD pipeline\n"
            "- pr-006: Write API documentation\n"
            "- pr-007: Performance optimization\n"
            "- pr-008: Mobile responsive design (descoped)\n"
        )

        store.save(data, tui_dir)

    return tui_dir


# ---------------------------------------------------------------------------
# Git module setup — creates a practice repo
# ---------------------------------------------------------------------------

def setup_git_practice_repo() -> Path:
    """Create a disposable git practice repository.

    Returns the path to the practice repo.
    """
    repo_dir = TUTORIAL_DIR / "git-practice"
    if repo_dir.exists():
        import shutil
        shutil.rmtree(repo_dir)
    repo_dir.mkdir(parents=True, exist_ok=True)

    subprocess.run(["git", "init", str(repo_dir)], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(repo_dir), "config", "user.email", "tutorial@pm.local"],
        capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo_dir), "config", "user.name", "Tutorial User"],
        capture_output=True, check=True,
    )

    # Create initial file
    readme = repo_dir / "README.md"
    readme.write_text("# Git Practice Repo\n\nThis is your practice repository for the git tutorial.\n")
    subprocess.run(["git", "-C", str(repo_dir), "add", "README.md"],
                   capture_output=True, check=True)
    subprocess.run(["git", "-C", str(repo_dir), "commit", "-m", "Initial commit"],
                   capture_output=True, check=True)

    return repo_dir


# ---------------------------------------------------------------------------
# Claude prompt builders
# ---------------------------------------------------------------------------

def build_tmux_claude_prompt() -> str:
    """Build the Claude prompt for the tmux tutorial module."""
    return f"""\
You are a friendly, interactive tmux tutorial guide. You're helping the user learn tmux basics step by step.

## Your Role
- Watch the progress file at {PROGRESS_FILE} for changes
- Guide the user through each step, explaining concepts clearly
- Congratulate them when they complete a step
- Provide helpful tips and keyboard shortcuts

## Progress Tracking
The progress file is a JSON file. Check it periodically (every few seconds) to see which steps are completed.
Use the `cat` command to read it.

## Tutorial Steps (in order)

1. **switch_pane** — Switch between panes
   - Explain: tmux splits the terminal into panes. The prefix key is Ctrl+b by default.
   - Teach: Press Ctrl+b then arrow keys to switch panes, or click with mouse (mouse mode is enabled)
   - The hook will detect when they switch panes

2. **resize_pane** — Resize a pane
   - Teach: Hold Ctrl+b then press and hold arrow keys, or drag pane borders with mouse
   - The hook detects resize events

3. **create_window** — Create a new window
   - Teach: Press Ctrl+b then c to create a new window
   - The hook detects new windows

4. **switch_window** — Switch between windows
   - Teach: Press Ctrl+b then n (next) or p (previous), or Ctrl+b then window number
   - Note: there's already a 'practice' window they can switch to
   - The hook detects window switches

5. **scroll_history** — Scroll through terminal history
   - Teach: Press Ctrl+b then [ to enter copy mode, then use arrow keys or Page Up/Down
   - Press q to exit copy mode
   - For this step, have the user run `seq 1 100` first to create scrollable content
   - This step has no hook — after they practice scrolling, have them mark it complete:
     `python3 -c "from pm_core.tutorial import mark_step_complete; mark_step_complete('tmux', 'scroll_history')"`

6. **split_pane** — Split a pane
   - Teach: Ctrl+b then % for vertical split, Ctrl+b then " for horizontal split
   - The after-split-window hook will detect this automatically

## Important Notes
- This is running on a dedicated tmux socket, separate from any pm sessions
- Mouse mode is enabled so users can click to switch panes and drag to resize
- Be encouraging and patient — this may be the user's first time with tmux
- After all steps are complete, congratulate them and suggest trying the TUI module next
- Keep responses concise — you're in a tmux pane with limited width

## Checking Progress
Run this periodically to check their progress:
```
cat {PROGRESS_FILE}
```

Start by introducing yourself and explaining step 1 (switching panes).\
"""


def build_tui_claude_prompt(project_dir: Path) -> str:
    """Build the Claude prompt for the TUI tutorial module."""
    return f"""\
You are a friendly, interactive tutorial guide for the pm TUI (Terminal User Interface).
You're helping the user learn to navigate the pm tech tree and use TUI features.

## Your Role
- Watch the progress file at {PROGRESS_FILE} for changes
- Guide the user through each exploration task
- Explain what each UI element means as they discover it

## Progress Tracking
Check {PROGRESS_FILE} periodically to see completed steps.

## The Example Project
An example project has been set up at {project_dir} with 8 PRs in various states:
- pr-001, pr-002: merged (completed)
- pr-003: in_review (being reviewed)
- pr-004: in_progress (actively being worked on)
- pr-005, pr-006: pending (waiting for dependencies)
- pr-007: qa (quality assurance testing)
- pr-008: closed (descoped)

These PRs have dependencies forming a realistic tech tree.

## Tutorial Steps (in order)

1. **navigate_tree** — Navigate the tech tree
   - Explain the tech tree shows PRs as nodes with dependency arrows
   - Teach: j/k to move up/down, Enter to select
   - Color coding: green=merged, yellow=in_progress, blue=in_review, gray=pending
   - After they've moved around, mark complete: they should press a specific key sequence

2. **view_pr_details** — View PR details
   - Teach: Press Enter or v on a selected PR to view its details
   - Explain the detail view shows description, status, dependencies, notes

3. **use_keybindings** — Use TUI keybindings
   - Teach: Press ? to see the help screen with all keybindings
   - Key bindings: s=start PR, d=review, g=merge, p=plans, n=notes
   - Explain this is how you drive pm workflows

4. **command_bar** — Use the command bar
   - Teach: Press : to open the command bar
   - They can type commands, search PRs, or filter
   - Press Escape to close

5. **filter_sort** — Filter and sort PRs
   - Teach: Press f to cycle through status filters
   - Press o to change sort order
   - Explain how filtering helps focus on what matters

6. **explore_statuses** — Explore PR statuses
   - Walk through the PR lifecycle: pending → in_progress → in_review → qa → merged
   - Explain what each status means in the pm workflow
   - closed means descoped/cancelled

## Important
- The TUI is running with the example project data, NOT the user's real project
- Guide them step by step, waiting for each step to complete
- Keep responses concise for the pane width
- After all steps, suggest trying the git module next

To mark steps complete (since TUI doesn't have hooks), instruct the user to run
this command in their shell pane after each task:
```
python3 -c "from pm_core.tutorial import mark_step_complete; mark_step_complete('tui', 'STEP_NAME')"
```

Start by welcoming them and explaining the tech tree layout.\
"""


def build_git_claude_prompt(repo_dir: Path) -> str:
    """Build the Claude prompt for the git fundamentals module."""
    return f"""\
You are a friendly, interactive git tutorial guide. You're helping the user learn
git fundamentals through hands-on exercises in a practice repository.

## Your Role
- Guide the user through git concepts with clear explanations
- Provide hands-on exercises in the practice repo at {repo_dir}
- Verify their work and mark steps complete
- Watch {PROGRESS_FILE} for progress

## The Practice Repository
A fresh git repo has been set up at {repo_dir} with an initial commit.
The user should run all git commands in that directory.

## Tutorial Steps (in order)

1. **init_repo** — Understanding repositories
   - Explain what a git repository is (the .git directory, working tree, staging area)
   - Have them explore: `ls -la {repo_dir}/.git/`
   - Explain HEAD, refs, objects briefly
   - Mark complete when they understand: run
     `python3 -c "from pm_core.tutorial import mark_step_complete; mark_step_complete('git', 'init_repo')"`

2. **make_commit** — Making commits
   - Explain the staging area (index) concept
   - Exercise: Create a new file, `git add` it, `git commit` it
   - Show `git log` to see the commit history
   - Explain commit messages, SHA hashes
   - Mark complete after they make a commit

3. **create_branch** — Working with branches
   - Explain what branches are (pointers to commits)
   - Exercise: `git branch feature`, `git checkout feature` (or `git switch feature`)
   - Make a commit on the branch, show how branches diverge
   - Show `git log --oneline --graph --all`
   - Mark complete after creating and committing on a branch

4. **merge_branch** — Merging branches
   - Explain fast-forward vs three-way merges
   - Exercise: Switch back to main/master, merge the feature branch
   - Show the result with `git log --oneline --graph`
   - Mark complete after a successful merge

5. **understand_remotes** — Remotes and collaboration
   - Explain what remotes are (other copies of the repo)
   - Explain origin, fetch, pull, push conceptually
   - Create a bare repo to simulate a remote:
     `git init --bare {TUTORIAL_DIR}/git-remote.git`
     `cd {repo_dir} && git remote add origin {TUTORIAL_DIR}/git-remote.git`
     `git push -u origin master` (or main)
   - Show `git remote -v`
   - Mark complete after pushing

6. **resolve_conflict** — Resolving merge conflicts
   - Explain what conflicts are and when they happen
   - Exercise: Create a conflict scenario
     - Create branch, modify same line in same file on both branches
     - Attempt merge, see conflict markers
     - Resolve by editing the file, then `git add` and `git commit`
   - Mark complete after resolving a conflict

## Step Completion
For each step, after the user has done the exercise, mark it complete:
```
python3 -c "from pm_core.tutorial import mark_step_complete; mark_step_complete('git', 'STEP_NAME')"
```

## Important
- This is a disposable practice repo — encourage experimentation
- Explain concepts simply, avoid jargon unless defining it
- Use analogies (branches = parallel timelines, commits = save points)
- After all steps, congratulate them and summarize what they learned
- Keep responses concise for the pane width

Start by welcoming them and introducing git with step 1.\
"""
