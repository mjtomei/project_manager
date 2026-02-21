"""Shared helpers for the pm CLI package.

Contains utility classes and functions used across multiple CLI submodules:
HelpGroup, state management, PR ID resolution, TUI refresh, and session helpers.
"""

import os
import subprocess
from pathlib import Path

import click

from pm_core import store, git_ops
from pm_core.paths import configure_logger
from pm_core import tmux as tmux_mod
from pm_core import pane_layout
from pm_core import pane_registry

_log = configure_logger("pm.cli")


# Module-level state set by the cli() group callback via set_project_override()
_project_override: Path | None = None

# Shared Click settings: make -h and --help both work everywhere
CONTEXT_SETTINGS = dict(help_option_names=["-h", "--help"])


def set_project_override(path: Path | None) -> None:
    """Set the project directory override (called by the cli group callback)."""
    global _project_override
    _project_override = path


class HelpGroup(click.Group):
    """Click Group that treats 'help' as an alias for --help everywhere.

    Applied to the top-level group and auto-inherited by all child groups
    via ``group_class = type`` (Click uses ``type(self)`` as default cls).

    Handles two cases:
    - ``pm pr help`` — 'help' as the command name on a group
    - ``pm tui test help`` — 'help' as an arg to a leaf command
    """

    group_class = type  # auto-propagate HelpGroup to child groups

    def resolve_command(self, ctx, args):
        if args and args[0] == "help":
            # If there's a real 'help' command registered, let it run
            if super().get_command(ctx, "help") is not None:
                return super().resolve_command(ctx, args)
            # Otherwise replace 'help' with '--help'
            args = ["--help"] + args[1:]
        cmd_name, cmd, remaining = super().resolve_command(ctx, args)
        # Also handle 'help' as first arg to a leaf command:
        # e.g. 'pm tui test help' → 'pm tui test --help'
        if (remaining and remaining[0] == "help"
                and cmd is not None and not isinstance(cmd, click.MultiCommand)):
            remaining = ["--help"] + remaining[1:]
        return cmd_name, cmd, remaining


def _normalize_repo_url(url: str) -> str:
    """Normalize git remote URL for comparison.

    git@github.com:org/repo.git -> github.com/org/repo
    https://github.com/org/repo.git -> github.com/org/repo
    """
    url = url.strip().rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]
    # SSH format: git@host:path
    if ":" in url and "@" in url.split(":")[0]:
        _, rest = url.split(":", 1)
        host = url.split("@")[1].split(":")[0]
        return f"{host}/{rest}"
    # HTTPS format
    for prefix in ("https://", "http://"):
        if url.startswith(prefix):
            return url[len(prefix):]
    return url


def _verify_pm_repo_matches_cwd(pm_root: Path) -> None:
    """Warn if the PM repo targets a different repo than the current git repo."""
    cwd = Path.cwd()
    if not git_ops.is_git_repo(cwd):
        return
    cwd_remote = git_ops.run_git("remote", "get-url", "origin", cwd=cwd, check=False)
    if cwd_remote.returncode != 0 or not cwd_remote.stdout.strip():
        return
    try:
        data = store.load(pm_root)
    except Exception:
        return
    pm_target = data.get("project", {}).get("repo", "")
    if not pm_target:
        return
    # If pm_target is a local path, check if cwd is that path
    pm_target_path = Path(pm_target)
    if pm_target_path.is_absolute() and pm_target_path.exists():
        try:
            if cwd.resolve() == pm_target_path.resolve():
                return
        except OSError:
            pass
    if _normalize_repo_url(cwd_remote.stdout.strip()) != _normalize_repo_url(pm_target):
        click.echo(
            f"Warning: PM repo targets {pm_target}\n"
            f"         but you're in a repo with remote {cwd_remote.stdout.strip()}\n",
            err=True,
        )


def state_root() -> Path:
    """Get the project root containing project.yaml."""
    if _project_override:
        _verify_pm_repo_matches_cwd(_project_override)
        return _project_override
    return store.find_project_root()


def _pr_id_sort_key(pr_id: str) -> tuple[int, str]:
    """Sort key for PR IDs. Numeric pr-NNN sorts by number, hash IDs sort after."""
    # pr-001 → (1, ""), pr-a3f2b1c → (0, "a3f2b1c")
    parts = pr_id.split("-", 1)
    if len(parts) == 2:
        try:
            return (int(parts[1]), "")
        except ValueError:
            return (0, parts[1])
    return (0, pr_id)


def _pr_display_id(pr: dict) -> str:
    """Display ID for a PR: prefer GitHub #N, fall back to local pr-NNN."""
    gh = pr.get("gh_pr_number")
    return f"#{gh}" if gh else pr["id"]


def _resolve_pr_id(data: dict, identifier: str) -> dict | None:
    """Resolve a PR by pm ID (pr-NNN), GitHub PR number (#N or bare integer).

    Accepts: 'pr-001', '42', '#42'.
    """
    # Exact pm ID match first
    pr = store.get_pr(data, identifier)
    if pr:
        return pr
    # Strip leading '#' for GitHub-style references
    cleaned = identifier.lstrip("#")
    try:
        num = int(cleaned)
    except ValueError:
        return None
    for pr in data.get("prs") or []:
        if pr.get("gh_pr_number") == num:
            return pr
    return None


def _require_pr(data: dict, pr_id: str) -> dict:
    """Get a PR by pm ID or GitHub PR number, or exit with an error.

    Accepts: 'pr-001', '42', '#42'.
    """
    pr_entry = _resolve_pr_id(data, pr_id)
    if pr_entry:
        return pr_entry
    prs = data.get("prs") or []
    click.echo(f"PR '{pr_id}' not found.", err=True)
    if prs:
        ids = []
        for p in prs:
            ids.append(_pr_display_id(p))
        click.echo(f"Available PRs: {', '.join(ids)}", err=True)
    raise SystemExit(1)


def _require_plan(data: dict, plan_id: str) -> dict:
    """Get a plan by ID or exit with an error listing available plans."""
    plan_entry = store.get_plan(data, plan_id)
    if plan_entry:
        return plan_entry
    plans = data.get("plans") or []
    click.echo(f"Plan {plan_id} not found.", err=True)
    if plans:
        click.echo(f"Available plans: {', '.join(p['id'] for p in plans)}", err=True)
    raise SystemExit(1)


def _auto_select_plan(data: dict, plan_id: str | None) -> str:
    """Auto-select a plan ID when not specified, or exit with an error."""
    if plan_id is not None:
        return plan_id
    plans = data.get("plans") or []
    if len(plans) == 1:
        return plans[0]["id"]
    if len(plans) == 0:
        click.echo("No plans. Create one with: pm plan add <name>", err=True)
        raise SystemExit(1)
    click.echo("Multiple plans. Specify one:", err=True)
    for p in plans:
        click.echo(f"  {p['id']}: {p['name']}", err=True)
    raise SystemExit(1)


def _make_pr_entry(
    pr_id: str,
    title: str,
    branch: str,
    *,
    plan: str | None = None,
    status: str = "pending",
    depends_on: list[str] | None = None,
    description: str = "",
    gh_pr: str | None = None,
    gh_pr_number: int | None = None,
) -> dict:
    """Create a standard PR entry dict with all required keys."""
    return {
        "id": pr_id,
        "plan": plan,
        "title": title,
        "branch": branch,
        "status": status,
        "depends_on": depends_on or [],
        "description": description,
        "agent_machine": None,
        "gh_pr": gh_pr,
        "gh_pr_number": gh_pr_number,
    }


def save_and_push(data: dict, root: Path, message: str = "pm: update state") -> None:
    """Save state. Use 'pm push' to commit and share changes."""
    store.save(data, root)


def trigger_tui_refresh() -> None:
    """Send reload key to TUI pane in the pm session for the current directory.

    Sends 'R' (reload) which reloads state from disk without triggering
    an expensive PR sync. Use 'r' (refresh) for full sync with GitHub.
    """
    try:
        if not tmux_mod.has_tmux():
            return
        tui_pane, session = _find_tui_pane()
        if tui_pane and session:
            tmux_mod.send_keys_literal(tui_pane, "R")
            _log.debug("Sent reload to TUI pane %s in session %s", tui_pane, session)
    except Exception as e:
        _log.debug("Could not trigger TUI refresh: %s", e)


def _resolve_repo_dir(root: Path, data: dict) -> Path:
    """Determine the target repo directory from pm state.

    Used when a command needs to run tools (like ``gh``) against the
    target repo.  Returns the parent of an internal pm/ dir, otherwise
    falls back to the repo URL (if it's a local path) or cwd.
    """
    if store.is_internal_pm_dir(root):
        return root.parent
    repo_url = data.get("project", {}).get("repo", "")
    if repo_url and Path(repo_url).is_dir():
        return Path(repo_url)
    return Path.cwd()


def _gh_state_to_status(state: str, is_draft: bool) -> str:
    """Map a GitHub PR state string to a local pm status."""
    if state == "MERGED":
        return "merged"
    if state == "CLOSED":
        return "closed"
    if state == "OPEN":
        return "in_progress" if is_draft else "in_review"
    return "pending"


def _workdirs_dir(data: dict) -> Path:
    """Return the workdirs base path for this project.

    Uses <name>-<repo_id[:8]> to avoid collisions between projects
    with the same name. repo_id is the root commit hash of the target
    repo, cached in project.yaml on first pr start.
    """
    project = data.get("project", {})
    name = project.get("name", "unknown")
    repo_id = project.get("repo_id")
    from pm_core.paths import workdirs_base
    base = workdirs_base()
    if repo_id:
        return base / f"{name}-{repo_id[:8]}"
    return base / name


def _resolve_repo_id(data: dict, workdir: Path, root: Path) -> None:
    """Resolve and cache the target repo's root commit hash."""
    if data.get("project", {}).get("repo_id"):
        return
    result = git_ops.run_git("rev-list", "--max-parents=0", "HEAD", cwd=workdir, check=False)
    lines = result.stdout.strip().splitlines() if result.returncode == 0 else []
    if lines:
        data["project"]["repo_id"] = lines[0]
        save_and_push(data, root, "pm: cache repo_id")


def _infer_pr_id(data: dict, status_filter: tuple[str, ...] | None = None) -> str | None:
    """Try to infer a PR ID from context.

    1. If cwd matches a PR's workdir, use that PR.
    2. If there's an active PR (and it matches the status filter if given), use that.
    3. If exactly one PR matches the status filter, use that.
    """
    cwd = str(Path.cwd().resolve())
    prs = data.get("prs") or []

    # Check if cwd is inside a PR's workdir
    for pr in prs:
        wd = pr.get("workdir")
        if wd and cwd.startswith(str(Path(wd).resolve())):
            return pr["id"]

    # Check active PR
    active = data.get("project", {}).get("active_pr")
    if active:
        pr_entry = store.get_pr(data, active)
        if pr_entry:
            if status_filter is None or pr_entry.get("status") in status_filter:
                return active

    # Fall back to single-match on status
    if status_filter:
        matches = [p for p in prs if p.get("status") in status_filter]
        if len(matches) == 1:
            return matches[0]["id"]

    return None


# ---------------------------------------------------------------------------
# Session / TUI helpers used by multiple submodules
# ---------------------------------------------------------------------------

def _set_share_mode_env(share_global: bool, share_group: str | None) -> None:
    """Set PM_SHARE_MODE env var from CLI flags so get_session_tag mixes it into the hash."""
    if share_global:
        os.environ["PM_SHARE_MODE"] = "global"
    elif share_group:
        os.environ["PM_SHARE_MODE"] = f"group:{share_group}"
    else:
        os.environ.pop("PM_SHARE_MODE", None)


def _get_session_name_for_cwd() -> str:
    """Generate the expected pm session name for the current working directory.

    Computes the name from the git root so it's deterministic regardless
    of which tmux session the caller is in.  Used by ``pm session`` to
    create/attach sessions and by ``pm pr start`` to find the session.

    When the caller is already inside the target pm session (e.g. TUI
    subprocesses), the computed name may not match the actual session
    (workdir clones have a different git-root hash).  Use
    ``_get_current_pm_session()`` in those cases.
    """
    from pm_core.paths import get_session_tag
    tag = get_session_tag()
    if tag:
        return f"pm-{tag}"

    # Fallback if not in a git repo
    return f"pm-{Path.cwd().name}-00000000"


def _get_current_pm_session() -> str | None:
    """Return the base pm session name when running inside one.

    Reads the actual session from $TMUX_PANE and strips any grouped-session
    ~N suffix.  Returns None if not inside tmux or not in a pm- session.
    """
    if not tmux_mod.in_tmux():
        return None
    name = tmux_mod.get_session_name()
    # Strip grouped session suffix
    if "~" in name:
        name = name.rsplit("~", 1)[0]
    if name.startswith("pm-"):
        return name
    return None


def _get_pm_session() -> str | None:
    """Get the pm tmux session name if running inside one."""
    if not tmux_mod.has_tmux():
        return None
    return _get_current_pm_session() or _get_session_name_for_cwd()


def _find_tui_pane(session: str | None = None) -> tuple[str | None, str | None]:
    """Find the TUI pane in a pm session.

    Returns (pane_id, session_name) or (None, None) if not found.

    If session is provided, uses that. Otherwise:
    - If in a pm- tmux session, uses current session
    - Otherwise, tries to find session matching current directory
    - Falls back to searching for any pm- session with a TUI pane
    """
    # If session specified, use it
    if session:
        data = pane_registry.load_registry(session)
        for _, pane in pane_registry._iter_all_panes(data):
            if pane.get("role") == "tui":
                return pane.get("id"), session
        return None, None

    # If in a pm session, use current
    if tmux_mod.in_tmux():
        current_session = tmux_mod.get_session_name()
        if current_session.startswith("pm-"):
            data = pane_registry.load_registry(current_session)
            for _, pane in pane_registry._iter_all_panes(data):
                if pane.get("role") == "tui":
                    return pane.get("id"), current_session

    # Try to find session matching current directory first
    expected_session = _get_session_name_for_cwd()
    if tmux_mod.session_exists(expected_session):
        data = pane_registry.load_registry(expected_session)
        for _, pane in pane_registry._iter_all_panes(data):
            if pane.get("role") == "tui":
                return pane.get("id"), expected_session

    # Fall back to searching for any pm session with a TUI
    result = subprocess.run(
        tmux_mod._tmux_cmd("list-sessions", "-F", "#{session_name}"),
        capture_output=True, text=True
    )
    if result.returncode != 0:
        return None, None

    for sess in result.stdout.strip().splitlines():
        if sess.startswith("pm-") and "~" not in sess:
            data = pane_registry.load_registry(sess)
            for _, pane in pane_registry._iter_all_panes(data):
                if pane.get("role") == "tui":
                    return pane.get("id"), sess

    # Last resort: search tmux directly for a pane running 'pm _tui'.
    # This handles cases where the TUI pane was removed from the registry
    # (e.g. during heal testing) but is still alive in tmux.
    result = subprocess.run(
        tmux_mod._tmux_cmd("list-panes", "-a",
                           "-F", "#{pane_id} #{session_name} #{pane_current_command} #{pane_start_command}"),
        capture_output=True, text=True
    )
    if result.returncode == 0:
        for line in result.stdout.strip().splitlines():
            parts = line.split(None, 3)
            if len(parts) >= 3 and parts[1].startswith("pm-"):
                # Check if command contains 'pm _tui' or 'pm-tui'
                cmd_text = " ".join(parts[2:])
                if "_tui" in cmd_text:
                    return parts[0], parts[1]

    return None, None
