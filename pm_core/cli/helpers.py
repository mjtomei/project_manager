"""Shared helpers for the pm CLI package.

Contains utility classes and functions used across multiple CLI submodules:
HelpGroup, state management, PR ID resolution, TUI refresh, and session helpers.
"""

import os
import shutil
import subprocess
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path

import click

from pm_core import store, git_ops
from pm_core.paths import configure_logger
from pm_core import tmux as tmux_mod
from pm_core import pane_layout
from pm_core import pane_registry

_log = configure_logger("pm.cli")


# Tokens at which record wrapping prefers to break a too-wide line, in
# priority order.  Each token marks a natural visual boundary in pm's
# record-style CLI output.  The leading space is stripped on continuation
# so the tail starts cleanly with the token itself.
_RECORD_BREAK_TOKENS = (" <- ", " (", " [")


def _cell_aware_fill(
    text: str, width: int, *,
    initial_indent: str = "", subsequent_indent: str = "",
) -> str:
    """Wrap ``text`` to visual ``width`` based on ``rich.cells.cell_len``.

    Same shape as ``textwrap.fill`` but counts cells, not codepoints.  Wide
    characters (emoji, CJK) consume the right number of columns.  Splits
    on whitespace only; never splits a word.  Long words that exceed the
    width go on their own line and overflow rather than being broken.
    """
    from rich.cells import cell_len
    words = text.split()
    if not words:
        return initial_indent
    lines = [initial_indent + words[0]]
    for word in words[1:]:
        candidate = lines[-1] + " " + word
        if cell_len(candidate) <= width:
            lines[-1] = candidate
        else:
            lines.append(subsequent_indent + word)
    return "\n".join(lines)


def _wrap_record_to_width(line: str, width: int, indent: str) -> str:
    """Return ``line`` possibly with embedded newlines so it fits in ``width``.

    Prefers breaking at the first record boundary token (``" <- "``,
    ``" ("``, ``" ["``).  If the indented tail still overflows, falls
    back to whitespace wrapping on the tail.  If no boundary token gives
    a head that fits, falls back to whitespace wrapping on the full line.

    Uses ``rich.cells.cell_len`` for visual width so wide characters
    (emoji status icons like ⏳ 👀 🧪 ✅, CJK, etc.) are counted as the
    two columns they actually occupy in a terminal.  ``len()`` would
    miscount them and let visually-overflowing lines slip through.
    """
    from rich.cells import cell_len
    if cell_len(line) <= width:
        return line
    for tok in _RECORD_BREAK_TOKENS:
        idx = line.find(tok)
        if idx <= 0:
            continue
        head = line[:idx]
        # Require the head (everything up to the leading space) to fit.
        if cell_len(head) > width:
            continue
        tail = line[idx + 1:]  # drop leading space, keep token onward
        indented_tail = indent + tail
        if cell_len(indented_tail) <= width:
            return head + "\n" + indented_tail
        return head + "\n" + _cell_aware_fill(
            tail, width,
            initial_indent=indent, subsequent_indent=indent,
        )
    # No break token gave a fitting head — fall back to whitespace wrapping
    # on the full line.  Preserve the line's own leading whitespace as the
    # initial indent so the first output line starts in the same column as
    # the original (e.g. ``"  ⏳ pr-..."`` keeps its two-space gutter).
    stripped = line.lstrip()
    leading = line[:len(line) - len(stripped)]
    return _cell_aware_fill(
        stripped, width,
        initial_indent=leading, subsequent_indent=indent,
    )


def echo_record(line: str, *, indent: str = "      ") -> None:
    """Echo one record-style line, wrapping at terminal width on a TTY.

    When stdout is *not* a TTY (e.g. piped into ``grep`` / ``jq``), the
    line is echoed as-is so consumers keep one-record-per-line semantics.
    Use ``emit_paged`` for listing commands that should also auto-page.
    """
    if not sys.stdout.isatty():
        click.echo(line)
        return
    width = shutil.get_terminal_size((80, 24)).columns
    click.echo(_wrap_record_to_width(line, width, indent))


def emit_paged(lines, *, indent: str = "      ") -> None:
    """Emit a sequence of record-style lines, auto-paging on a TTY.

    Mirrors the ``git log`` / ``man`` / ``journalctl`` pattern: when
    stdout is a TTY, collect all output, wrap each line at the terminal
    width (with the same record-boundary preferences as ``echo_record``),
    and pipe through ``$PAGER``.  ``less -FRX`` (the typical default)
    auto-quits when the output fits on one screen, so short listings
    don't feel paged at all.

    When stdout is piped (``grep`` / ``jq`` / a file), each line is
    emitted as-is, one per record, with no wrapping.
    """
    if not sys.stdout.isatty():
        for line in lines:
            click.echo(line)
        return
    width = shutil.get_terminal_size((80, 24)).columns
    wrapped = "\n".join(_wrap_record_to_width(line, width, indent) for line in lines)
    click.echo_via_pager(wrapped)


# Module-level state set by the cli() group callback via set_project_override()
_project_override: Path | None = None

# Shared Click settings: make -h and --help both work everywhere
CONTEXT_SETTINGS = dict(help_option_names=["-h", "--help"])


def set_project_override(path: Path | None) -> None:
    """Set the project directory override (called by the cli group callback)."""
    global _project_override
    _project_override = path


class HelpGroup(click.Group):
    """Click Group that treats 'help' as an alias for --help everywhere,
    and 'l'/'ls' as aliases for 'list' everywhere.

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
        # Alias l/ls to list when the group has a list subcommand
        if args and args[0] in ("l", "ls") and super().get_command(ctx, "list") is not None:
            args = ["list"] + args[1:]
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


def _pr_path_segment(pr: dict) -> str:
    """Filesystem-safe PR segment.

    Same resolution as ``_pr_display_id`` (prefer GitHub PR number when
    set), but renders ``pr-<num>`` instead of ``#<num>`` so it's safe in
    filesystem paths and shell commands.
    """
    gh = pr.get("gh_pr_number")
    return f"pr-{gh}" if gh else pr["id"]


def kill_pr_windows(session: str, pr: dict) -> list[str]:
    """Kill tmux work, review, merge, and QA windows for a PR.

    Returns a list of window names that were killed.
    """
    from pm_core import tmux as tmux_mod

    killed = []
    display_id = _pr_display_id(pr)
    for win_name in (display_id, f"review-{display_id}", f"merge-{display_id}",
                     f"qa-{display_id}"):
        win = tmux_mod.find_window_by_name(session, win_name)
        if win:
            tmux_mod.kill_window(session, win["id"])
            killed.append(win_name)

    # Also kill any QA scenario windows (qa-{display_id}-s1, etc.)
    qa_prefix = f"qa-{display_id}-s"
    for win in tmux_mod.list_windows(session):
        if win.get("name", "").startswith(qa_prefix):
            tmux_mod.kill_window(session, win["id"])
            killed.append(win["name"])

    return killed


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
    now = datetime.now(timezone.utc).isoformat()
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
        "created_at": now,
        "updated_at": now,
        "started_at": None,
        "reviewed_at": None,
        "merged_at": None,
        "notes": [],
    }


def _record_status_timestamp(pr_entry: dict, status: str | None = None) -> None:
    """Record timestamps on *pr_entry*.

    Always sets ``updated_at``.  When *status* is provided, also sets
    the status-specific timestamp:

    * ``started_at`` — set once on the first transition to ``in_progress``.
    * ``reviewed_at`` — updated each time the PR enters ``in_review``.
    * ``merged_at`` — set when the PR is ``merged``.
    """
    now = datetime.now(timezone.utc).isoformat()
    pr_entry["updated_at"] = now
    if status == "in_progress" and not pr_entry.get("started_at"):
        pr_entry["started_at"] = now
    elif status == "in_review":
        pr_entry["reviewed_at"] = now
    elif status == "merged":
        pr_entry["merged_at"] = now


def _tui_pidfile_for_session(session: str) -> Path:
    """Path to the pidfile a TUI in ``session`` writes at startup."""
    from pm_core.paths import pm_home
    return pm_home() / f"tui-{session}.pid"


def trigger_tui_reload(session: str | None = None) -> None:
    """Ask the TUI to reload state from disk via SIGUSR1.

    The TUI registers a SIGUSR1 handler at startup that runs
    ``action_reload`` (state-only reload, no GitHub sync). This is
    focus-independent — unlike send-keys, it can't be eaten by the
    command input or any other focused widget.

    Resolves the target TUI by session: if ``session`` is given it is
    used directly, otherwise we look up the TUI for the current
    cwd/tmux context (same logic as ``_find_tui_pane``).
    """
    import signal
    try:
        if session is None:
            _, session = _find_tui_pane()
        if not session:
            return
        pidfile = _tui_pidfile_for_session(session)
        if not pidfile.exists():
            _log.debug("No TUI pidfile for session %s", session)
            return
        try:
            pid = int(pidfile.read_text().strip())
        except (ValueError, OSError) as e:
            _log.debug("Could not read TUI pidfile %s: %s", pidfile, e)
            return
        try:
            os.kill(pid, signal.SIGUSR1)
            _log.debug("Sent SIGUSR1 to TUI pid %d (session %s)", pid, session)
        except ProcessLookupError:
            _log.debug("TUI pid %d gone, removing stale pidfile", pid)
            pidfile.unlink(missing_ok=True)
        except PermissionError as e:
            _log.debug("Cannot signal TUI pid %d: %s", pid, e)
    except Exception as e:
        _log.debug("Could not trigger TUI reload: %s", e)


# Backwards-compatible alias for existing callers.
trigger_tui_refresh = trigger_tui_reload


def _tui_command_queue_for_session(session: str) -> Path:
    """Path to the per-session TUI command queue file."""
    from pm_core.paths import pm_home
    return pm_home() / f"tui-{session}.cmd-queue"


def trigger_tui_command(session: str, cmd: str) -> bool:
    """Submit ``cmd`` to the TUI's command bar via SIGUSR2 + queue file.

    The TUI registers a SIGUSR2 handler at startup that drains the
    per-session queue file and dispatches each line through the same
    code path as a typed-and-submitted command bar entry.  This is
    focus-independent — unlike send-keys, it can't be eaten by the
    command input or get its literal text dispatched as TUI key
    bindings while waiting for the Input widget to focus.

    Multiple callers can append in any order; appends use ``flock`` to
    serialize and a SIGUSR2 fires per call, so racing writes are
    drained in the same handler invocation or the next one.

    Returns True if the signal was sent, False otherwise.
    """
    import fcntl
    import signal
    pidfile = _tui_pidfile_for_session(session)
    if not pidfile.exists():
        _log.debug("No TUI pidfile for session %s", session)
        return False
    try:
        pid = int(pidfile.read_text().strip())
    except (ValueError, OSError) as e:
        _log.debug("Could not read TUI pidfile %s: %s", pidfile, e)
        return False
    queue = _tui_command_queue_for_session(session)
    line = cmd.strip().replace("\n", " ") + "\n"
    try:
        with open(queue, "a") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                f.write(line)
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except OSError as e:
        _log.debug("Could not append to TUI command queue %s: %s", queue, e)
        return False
    try:
        os.kill(pid, signal.SIGUSR2)
        _log.debug("Queued command %r and sent SIGUSR2 to TUI pid %d (%s)",
                   cmd, pid, session)
        return True
    except ProcessLookupError:
        _log.debug("TUI pid %d gone, removing stale pidfile", pid)
        pidfile.unlink(missing_ok=True)
        return False
    except PermissionError as e:
        _log.debug("Cannot signal TUI pid %d: %s", pid, e)
        return False


def trigger_tui_restart() -> None:
    """Send Ctrl+R to the TUI pane to restart it.

    Used after pulling new code so the TUI picks up the latest version.
    Writes a merge-restart marker so the TUI can distinguish this from
    a user-initiated Ctrl+R and preserve auto-start state.
    """
    try:
        if not tmux_mod.has_tmux():
            return
        tui_pane, session = _find_tui_pane()
        if tui_pane and session:
            from pm_core.paths import pm_home
            marker = pm_home() / "merge-restart"
            marker.touch()
            _log.debug("Wrote merge-restart marker %s", marker)
            tmux_mod.send_keys_literal(tui_pane, "C-r")
            _log.debug("Sent restart to TUI pane %s in session %s", tui_pane, session)
    except Exception as e:
        _log.debug("Could not trigger TUI restart: %s", e)


def trigger_tui_merge_lock(pr_display_id: str) -> None:
    """Write merge-lock marker and signal TUI to show overlay.

    Called before stashing pm/ files during merge so the TUI pauses
    reads/writes while the files are temporarily reverted.
    """
    try:
        from pm_core.paths import pm_home
        lock = pm_home() / "merge-lock"
        lock.write_text(pr_display_id)
        _log.debug("Wrote merge-lock marker for %s", pr_display_id)
        # Signal TUI to reload — it will see the lock and show overlay
        trigger_tui_reload()
    except Exception as e:
        _log.debug("Could not set merge lock: %s", e)


def trigger_tui_merge_unlock() -> None:
    """Remove merge-lock marker.

    The TUI's MergeLockScreen polls for this file and auto-dismisses
    when it disappears, then reloads state.
    """
    try:
        from pm_core.paths import pm_home
        lock = pm_home() / "merge-lock"
        lock.unlink(missing_ok=True)
        _log.debug("Removed merge-lock marker")
    except Exception as e:
        _log.debug("Could not remove merge lock: %s", e)


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


def _ensure_workdir(data: dict, pr_entry: dict, root: Path) -> str | None:
    """Ensure the PR's workdir exists locally, cloning if necessary.

    When a PR was started on a different machine the recorded workdir path
    won't exist.  This helper recreates it by cloning the repo and checking
    out the PR branch, mirroring the logic in ``pr_start``.

    Returns the workdir path (str) on success, or *None* on failure.
    Updates *pr_entry["workdir"]* and persists the change when a new
    clone is created.
    """
    import shutil

    workdir = pr_entry.get("workdir")
    if workdir and Path(workdir).exists():
        return workdir

    branch = pr_entry.get("branch")
    if not branch:
        _log.warning("Cannot ensure workdir: PR %s has no branch", pr_entry.get("id"))
        return None

    repo_url = data.get("project", {}).get("repo", "")
    base_branch = data.get("project", {}).get("base_branch", "master")
    pr_id = pr_entry["id"]

    project_dir = _workdirs_dir(data)
    project_dir.mkdir(parents=True, exist_ok=True)

    # Determine clone source: prefer a local repo dir for speed.
    repo_dir = _resolve_repo_dir(root, data)
    if repo_dir and repo_dir.is_dir() and git_ops.is_git_repo(repo_dir):
        clone_source = str(repo_dir)
    elif repo_url:
        clone_source = repo_url
    else:
        _log.warning("Cannot ensure workdir: no repo source for PR %s", pr_id)
        return None

    tmp_path = project_dir / f".tmp-{pr_id}"
    if tmp_path.exists():
        shutil.rmtree(tmp_path)

    click.echo(f"Workdir missing — cloning for {pr_id}...")
    try:
        git_ops.clone(clone_source, tmp_path, branch=base_branch)
    except Exception as exc:
        _log.warning("Failed to clone for PR %s: %s", pr_id, exc)
        click.echo(f"Failed to clone: {exc}", err=True)
        if tmp_path.exists():
            shutil.rmtree(tmp_path, ignore_errors=True)
        return None

    # Set up remote URLs when cloned from a local repo:
    # - fetch from GitHub (so we can find PR branches from other machines)
    # - push to both local and GitHub
    if clone_source == str(repo_dir) and repo_url:
        git_ops.run_git("remote", "set-url", "origin", repo_url, cwd=tmp_path)
        git_ops.run_git("remote", "set-url", "--push",
                        "origin", clone_source, cwd=tmp_path)
        git_ops.run_git("remote", "set-url", "--add", "--push",
                        "origin", repo_url, cwd=tmp_path)

    # Resolve repo_id if not cached yet
    _resolve_repo_id(data, tmp_path, root)

    # Compute final directory name (same convention as pr_start)
    base_hash = git_ops.run_git(
        "rev-parse", "--short=8", "HEAD", cwd=tmp_path, check=False
    ).stdout.strip()
    branch_slug = store.slugify(branch.replace("/", "-"))
    dir_name = f"{branch_slug}-{base_hash}" if base_hash else branch_slug
    final_project_dir = _workdirs_dir(data)
    final_project_dir.mkdir(parents=True, exist_ok=True)
    work_path = final_project_dir / dir_name

    if work_path.exists():
        shutil.rmtree(tmp_path)
    else:
        shutil.move(str(tmp_path), str(work_path))

    # Checkout the PR branch
    git_ops.checkout_branch(work_path, branch, create=True)

    # Update and persist the new workdir path atomically
    workdir_str = str(work_path)
    pr_entry["workdir"] = workdir_str

    def apply(fresh_data):
        for pr in fresh_data.get("prs") or []:
            if pr["id"] == pr_id:
                pr["workdir"] = workdir_str
                break

    store.locked_update(root, apply)
    click.echo(f"Workdir created at {work_path}")
    return workdir_str


def _resolve_repo_id(data: dict, workdir: Path, root: Path) -> None:
    """Resolve and cache the target repo's root commit hash."""
    if data.get("project", {}).get("repo_id"):
        return
    result = git_ops.run_git("rev-list", "--max-parents=0", "HEAD", cwd=workdir, check=False)
    lines = result.stdout.strip().splitlines() if result.returncode == 0 else []
    if lines:
        repo_id = lines[0]
        data["project"]["repo_id"] = repo_id

        def apply(d):
            d.setdefault("project", {})["repo_id"] = repo_id

        store.locked_update(root, apply)


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
