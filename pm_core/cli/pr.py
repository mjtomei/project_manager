"""PR commands for the pm CLI.

Registers the ``pr`` group and all subcommands on the top-level ``cli`` group.
"""

import os
import platform
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import click

from pm_core import store, graph, git_ops, prompt_gen
from pm_core import pr_sync as pr_sync_mod
from pm_core import tmux as tmux_mod
from pm_core import pane_layout
from pm_core import pane_registry
from pm_core.backend import get_backend
from pm_core.claude_launcher import find_claude, build_claude_shell_cmd, clear_session, launch_claude, finalize_transcript

from pm_core.cli import cli
from pm_core.cli.helpers import (
    _get_pm_session,
    _gh_state_to_status,
    _infer_pr_id,
    _log,
    _make_pr_entry,
    _pr_display_id,
    _pr_id_sort_key,
    _require_pr,
    _resolve_pr_id,
    _resolve_repo_dir,
    _resolve_repo_id,
    _workdirs_dir,
    kill_pr_windows,
    save_and_push,
    state_root,
    trigger_tui_refresh,
)


# --- PR commands ---

@cli.group()
def pr():
    """Manage PRs."""
    pass


@pr.command("add")
@click.argument("title")
@click.option("--plan", "plan_id", default=None, help="Associated plan ID")
@click.option("--depends-on", "depends_on", default=None, help="Comma-separated PR IDs")
@click.option("--description", "desc", default="", help="PR description")
def pr_add(title: str, plan_id: str, depends_on: str, desc: str):
    """Add a new PR to the project."""
    root = state_root()
    data = store.load(root)

    # Auto-select plan if there's exactly one
    if plan_id is None:
        plans = data.get("plans") or []
        if len(plans) == 1:
            plan_id = plans[0]["id"]

    existing_ids = {p["id"] for p in (data.get("prs") or [])}
    pr_id = store.generate_pr_id(title, desc, existing_ids)
    slug = store.slugify(title)
    branch = f"pm/{pr_id}-{slug}"

    deps = []
    if depends_on:
        deps = [d.strip() for d in depends_on.split(",")]
        existing_ids = {p["id"] for p in (data.get("prs") or [])}
        unknown = [d for d in deps if d not in existing_ids]
        if unknown:
            click.echo(f"Unknown PR IDs in --depends-on: {', '.join(unknown)}", err=True)
            if existing_ids:
                click.echo(f"Available PRs: {', '.join(sorted(existing_ids))}", err=True)
            raise SystemExit(1)

    entry = _make_pr_entry(pr_id, title, branch, plan=plan_id,
                           depends_on=deps, description=desc)

    if data.get("prs") is None:
        data["prs"] = []
    data["prs"].append(entry)
    data["project"]["active_pr"] = pr_id

    save_and_push(data, root, f"pm: add {pr_id}")
    click.echo(f"Created {_pr_display_id(entry)}: {title} (now active)")
    click.echo(f"  branch: {branch}")
    if deps:
        click.echo(f"  depends_on: {', '.join(deps)}")
    if entry.get("gh_pr"):
        click.echo(f"  draft PR: {entry['gh_pr']}")
    trigger_tui_refresh()


@pr.command("edit")
@click.argument("pr_id")
@click.option("--title", default=None, help="New title")
@click.option("--depends-on", "depends_on", default=None, help="Comma-separated PR IDs (replaces existing)")
@click.option("--description", "desc", default=None, help="New description")
@click.option("--status", default=None, type=click.Choice(["pending", "in_progress", "in_review", "merged", "closed"]),
              help="New status (pending, in_progress, in_review, merged, closed)")
def pr_edit(pr_id: str, title: str | None, depends_on: str | None, desc: str | None, status: str | None):
    """Edit an existing PR's title, description, dependencies, or status."""
    root = state_root()
    data = store.load(root)
    pr_entry = _require_pr(data, pr_id)
    pr_id = pr_entry["id"]

    changes = []
    if title is not None:
        pr_entry["title"] = title
        changes.append(f"title={title}")
    if desc is not None:
        pr_entry["description"] = desc
        changes.append("description updated")
    if status is not None:
        old_status = pr_entry.get("status", "pending")
        pr_entry["status"] = status
        changes.append(f"status: {old_status} → {status}")
    if depends_on is not None:
        if depends_on == "":
            pr_entry["depends_on"] = []
            changes.append("depends_on cleared")
        else:
            deps = [d.strip() for d in depends_on.split(",")]
            existing_ids = {p["id"] for p in (data.get("prs") or [])}
            unknown = [d for d in deps if d not in existing_ids]
            if unknown:
                click.echo(f"Unknown PR IDs: {', '.join(unknown)}", err=True)
                raise SystemExit(1)
            pr_entry["depends_on"] = deps
            changes.append(f"depends_on={', '.join(deps)}")

    if not changes:
        # No flags given — open in $EDITOR
        import tempfile
        editor = os.environ.get("EDITOR", os.environ.get("VISUAL", "vi"))
        current_title = pr_entry.get("title", "")
        current_desc = pr_entry.get("description", "")
        current_deps = ", ".join(pr_entry.get("depends_on") or [])
        current_status = pr_entry.get("status", "pending")

        current_notes = pr_entry.get("notes") or []
        notes_lines = ""
        if current_notes:
            for n in current_notes:
                ts = n.get("created_at", "")
                ts_suffix = f"  # {ts}" if ts else ""
                notes_lines += f"- {n['text']}{ts_suffix}\n"
        else:
            notes_lines = "# (no notes)\n"

        template = (
            f"# Editing {pr_id}\n"
            f"# Lines starting with # are ignored.\n"
            f"# Save and exit to apply changes. Exit without saving to cancel.\n"
            f"\n"
            f"title: {current_title}\n"
            f"status: {current_status}\n"
            f"depends_on: {current_deps}\n"
            f"\n"
            f"# Notes (bulleted list, one per line starting with '- '):\n"
            f"{notes_lines}"
            f"\n"
            f"# Description (everything below this line):\n"
            f"{current_desc}\n"
        )

        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
            f.write(template)
            tmp_path = f.name

        try:
            mtime_before = os.path.getmtime(tmp_path)
            ret = subprocess.call([editor, tmp_path])
            if ret != 0:
                click.echo("Editor exited with error. No changes made.", err=True)
                raise SystemExit(1)
            mtime_after = os.path.getmtime(tmp_path)
            if mtime_before == mtime_after:
                click.echo("No changes made.")
                raise SystemExit(0)

            with open(tmp_path) as f:
                raw = f.read()
        finally:
            os.unlink(tmp_path)

        # Parse the edited file — three sections:
        # 1. metadata fields (title:, status:, depends_on:)
        # 2. notes (between # Notes and # Description comments)
        # 3. description (after # Description comment)
        desc_lines = []
        note_lines = []
        in_desc = False
        in_notes = False
        new_title = current_title
        new_status = current_status
        new_deps_str = current_deps
        for line in raw.splitlines():
            if line.startswith("#"):
                if "description" in line.lower() and "below" in line.lower():
                    in_desc = True
                    in_notes = False
                elif "notes" in line.lower():
                    in_notes = True
                continue
            if in_desc:
                desc_lines.append(line)
            elif in_notes:
                stripped = line.strip()
                if stripped.startswith("- "):
                    text = stripped[2:]
                    # Strip trailing timestamp comment added by template
                    text = re.sub(r'\s+#\s+\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$', '', text)
                    note_lines.append(text)
                # skip blank lines and non-bulleted lines in notes section
            elif line.startswith("title:"):
                new_title = line[len("title:"):].strip()
            elif line.startswith("status:"):
                new_status = line[len("status:"):].strip()
            elif line.startswith("depends_on:"):
                new_deps_str = line[len("depends_on:"):].strip()

        new_desc = "\n".join(desc_lines).strip()

        if new_title != current_title:
            pr_entry["title"] = new_title
            changes.append(f"title={new_title}")
        if new_desc != current_desc.strip():
            pr_entry["description"] = new_desc
            changes.append("description updated")
        if new_status != current_status:
            valid = {"pending", "in_progress", "in_review", "merged", "closed"}
            if new_status not in valid:
                click.echo(f"Invalid status '{new_status}'. Must be one of: {', '.join(sorted(valid))}", err=True)
                raise SystemExit(1)
            pr_entry["status"] = new_status
            changes.append(f"status: {current_status} → {new_status}")
        if new_deps_str != current_deps:
            if not new_deps_str:
                pr_entry["depends_on"] = []
                changes.append("depends_on cleared")
            else:
                deps = [d.strip() for d in new_deps_str.split(",")]
                existing_ids = {p["id"] for p in (data.get("prs") or [])}
                unknown = [d for d in deps if d not in existing_ids]
                if unknown:
                    click.echo(f"Unknown PR IDs: {', '.join(unknown)}", err=True)
                    raise SystemExit(1)
                pr_entry["depends_on"] = deps
                changes.append(f"depends_on={', '.join(deps)}")

        # Reconcile notes: compare old text list with new text list
        # Edits are treated as delete + add (new hash ID)
        old_texts = [n["text"] for n in current_notes]
        if note_lines != old_texts:
            # Build new notes list: keep existing IDs for unchanged, generate new for added
            old_by_text = {}
            for n in current_notes:
                old_by_text.setdefault(n["text"], []).append(n)
            new_notes = []
            existing_note_ids = set()
            for text in note_lines:
                if text in old_by_text and old_by_text[text]:
                    # Reuse existing note entry
                    reused = old_by_text[text].pop(0)
                    new_notes.append(reused)
                    existing_note_ids.add(reused["id"])
                else:
                    # New or edited note — generate new ID and timestamp
                    note_id = store.generate_note_id(pr_id, text, existing_note_ids)
                    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    new_notes.append({"id": note_id, "text": text, "created_at": now, "last_edited": now})
                    existing_note_ids.add(note_id)
            # Sort by last_edited so most recently touched notes appear last
            new_notes.sort(key=lambda n: n.get("last_edited") or n.get("created_at", ""))
            pr_entry["notes"] = new_notes
            changes.append("notes updated")

        if not changes:
            click.echo("No changes made.")
            raise SystemExit(0)

    save_and_push(data, root, f"pm: edit {pr_id}")
    click.echo(f"Updated {pr_id}: {', '.join(changes)}")
    trigger_tui_refresh()


@pr.command("select")
@click.argument("pr_id")
def pr_select(pr_id: str):
    """Set the active PR.

    The active PR is used as the default when commands like pm pr start,
    pm pr review, pm prompt, etc. are run without specifying a PR ID.
    """
    root = state_root()
    data = store.load(root)
    pr_entry = _require_pr(data, pr_id)
    pr_id = pr_entry["id"]

    data["project"]["active_pr"] = pr_id
    save_and_push(data, root)
    click.echo(f"Active PR: {pr_id} ({pr_entry.get('title', '???')})")
    trigger_tui_refresh()


@pr.command("cd")
@click.argument("identifier")
def pr_cd(identifier: str):
    """Open a shell in a PR's workdir.

    IDENTIFIER can be a pm PR ID (e.g. pr-021) or a GitHub PR number (e.g. 42).
    Type 'exit' to return to your original directory.
    """
    root = state_root()
    data = store.load(root)
    pr_entry = _resolve_pr_id(data, identifier)
    if not pr_entry:
        click.echo(f"PR '{identifier}' not found.", err=True)
        raise SystemExit(1)
    workdir = pr_entry.get("workdir")
    if not workdir or not Path(workdir).is_dir():
        click.echo(f"Workdir for {pr_entry['id']} does not exist: {workdir}", err=True)
        raise SystemExit(1)
    shell = os.environ.get("SHELL", "/bin/sh")
    click.echo(f"Entering workdir for {pr_entry['id']} ({pr_entry.get('title', '???')})")
    click.echo(f"  {workdir}")
    click.echo(f"Type 'exit' to return.")
    os.chdir(workdir)
    os.execvp(shell, [shell])


@pr.command("list")
@click.option("--workdirs", is_flag=True, default=False, help="Show workdir paths and their git status")
def pr_list(workdirs: bool):
    """List all PRs with status."""
    root = state_root()
    data = store.load(root)

    prs = data.get("prs") or []
    if not prs:
        click.echo("No PRs.")
        return

    # Sort newest first (by gh_pr_number descending, then pr id descending)
    prs = sorted(prs, key=lambda p: (p.get("gh_pr_number") or _pr_id_sort_key(p["id"])[0], _pr_id_sort_key(p["id"])[1]), reverse=True)

    active_pr = data.get("project", {}).get("active_pr")
    status_icons = {
        "pending": "⏳",
        "in_progress": "🔨",
        "in_review": "👀",
        "merged": "✅",
        "blocked": "🚫",
    }
    for p in prs:
        icon = status_icons.get(p.get("status", "pending"), "?")
        deps = p.get("depends_on") or []
        dep_str = f" <- [{', '.join(deps)}]" if deps else ""
        machine = p.get("agent_machine")
        machine_str = f" ({machine})" if machine else ""
        active_str = " *" if p["id"] == active_pr else ""
        click.echo(f"  {icon} {_pr_display_id(p)}: {p.get('title', '???')} [{p.get('status', '?')}]{dep_str}{machine_str}{active_str}")
        if workdirs:
            wd = p.get("workdir")
            if wd and Path(wd).exists():
                dirty = _workdir_is_dirty(Path(wd))
                dirty_str = " (dirty)" if dirty else " (clean)"
                click.echo(f"      workdir: {wd}{dirty_str}")
            elif wd:
                click.echo(f"      workdir: {wd} (missing)")
            else:
                click.echo(f"      workdir: none")


@pr.command("graph")
def pr_graph():
    """Show static dependency graph."""
    root = state_root()
    data = store.load(root)

    prs = data.get("prs") or []
    click.echo(graph.render_static_graph(prs))


@pr.command("ready")
def pr_ready():
    """List PRs ready to start (all deps merged)."""
    root = state_root()
    data = store.load(root)

    prs = data.get("prs") or []
    ready = graph.ready_prs(prs)
    if not ready:
        click.echo("No PRs are ready to start.")
        return
    for p in ready:
        click.echo(f"  ⏳ {_pr_display_id(p)}: {p.get('title', '???')}")


@pr.command("start")
@click.argument("pr_id", default=None, required=False)
@click.option("--workdir", default=None, help="Custom work directory")
@click.option("--fresh", is_flag=True, default=False, help="Start a fresh session (don't resume)")
@click.option("--background", is_flag=True, default=False, hidden=True,
              help="Create tmux window without switching focus (used by auto-start)")
@click.option("--transcript", default=None, hidden=True,
              help="Path to save Claude transcript symlink (used by auto-start)")
def pr_start(pr_id: str | None, workdir: str, fresh: bool, background: bool, transcript: str | None):
    """Start working on a PR: clone, branch, print prompt.

    If PR_ID is omitted, uses the active PR if it's pending/ready, or
    auto-selects the next ready PR (when there's exactly one).
    """
    root = state_root()
    data = store.load(root)

    if pr_id is None:
        # Try active PR first
        active = data.get("project", {}).get("active_pr")
        if active:
            active_entry = store.get_pr(data, active)
            if active_entry and active_entry.get("status") == "pending":
                pr_id = active
                click.echo(f"Using active PR {_pr_display_id(active_entry)}: {active_entry.get('title', '???')}")

    if pr_id is None:
        prs = data.get("prs") or []
        ready = graph.ready_prs(prs)
        if len(ready) == 1:
            pr_id = ready[0]["id"]
            click.echo(f"Auto-selected {_pr_display_id(ready[0])}: {ready[0].get('title', '???')}")
        elif len(ready) == 0:
            click.echo("No PRs are ready to start.", err=True)
            raise SystemExit(1)
        else:
            click.echo("Multiple PRs are ready. Specify one:", err=True)
            for p in ready:
                click.echo(f"  {_pr_display_id(p)}: {p.get('title', '???')}", err=True)
            raise SystemExit(1)

    pr_entry = _require_pr(data, pr_id)
    pr_id = pr_entry["id"]

    if pr_entry.get("status") == "in_progress":
        # If already in_progress, reuse existing workdir if available
        existing_workdir = pr_entry.get("workdir")
        if existing_workdir and Path(existing_workdir).exists():
            click.echo(f"PR {pr_id} is already in_progress, reusing existing workdir.")
            workdir = existing_workdir  # Set workdir so it gets used below
        else:
            # Workdir was deleted — fall through to create a new one
            click.echo(f"PR {pr_id} workdir missing, creating a new one.")

    if pr_entry.get("status") == "merged":
        click.echo(f"PR {pr_id} is already merged.", err=True)
        raise SystemExit(1)

    # Determine tmux session name (used for fast-path check and later launch)
    pm_session = _get_pm_session()

    # Fast path: if window already exists, switch to it (or kill it if --fresh)
    if pm_session:
        if tmux_mod.session_exists(pm_session):
            window_name = _pr_display_id(pr_entry)
            existing = tmux_mod.find_window_by_name(pm_session, window_name)
            if existing:
                if fresh:
                    tmux_mod.kill_window(pm_session, existing["id"])
                    click.echo(f"Killed existing window '{window_name}'")
                elif background:
                    # Window already exists, nothing to do in background mode
                    click.echo(f"Window '{window_name}' already exists (background mode, no focus change)")
                    return
                else:
                    tmux_mod.select_window(pm_session, existing["id"])
                    click.echo(f"Switched to existing window '{window_name}' (session: {pm_session})")
                    return

    repo_url = data["project"]["repo"]
    base_branch = data["project"].get("base_branch", "master")
    branch = pr_entry.get("branch") or f"pm/{pr_id}"

    if workdir:
        work_path = Path(workdir).resolve()
    else:
        # Check if we already have a workdir for this PR
        existing_workdir = pr_entry.get("workdir")
        if existing_workdir and Path(existing_workdir).exists():
            work_path = Path(existing_workdir)
        else:
            # Need to clone first, then figure out the final path
            # Clone to a temp location under the project dir
            project_dir = _workdirs_dir(data)
            project_dir.mkdir(parents=True, exist_ok=True)
            tmp_path = project_dir / f".tmp-{pr_id}"
            if tmp_path.exists():
                shutil.rmtree(tmp_path)
            click.echo(f"Cloning {repo_url}...")
            git_ops.clone(repo_url, tmp_path, branch=base_branch)

            # Cache repo_id now that we have a clone
            _resolve_repo_id(data, tmp_path, root)

            # Get the base commit hash for the branch directory name
            base_hash = git_ops.run_git(
                "rev-parse", "--short=8", "HEAD", cwd=tmp_path, check=False
            ).stdout.strip()

            # Final path: <project_dir>/<branch_slug>-<base_hash>
            # Re-resolve project_dir since _resolve_repo_id may have updated data
            branch_slug = store.slugify(branch.replace("/", "-"))
            dir_name = f"{branch_slug}-{base_hash}" if base_hash else branch_slug
            final_project_dir = _workdirs_dir(data)
            final_project_dir.mkdir(parents=True, exist_ok=True)
            work_path = final_project_dir / dir_name

            if work_path.exists():
                shutil.rmtree(tmp_path)
            else:
                shutil.move(str(tmp_path), str(work_path))

    if work_path.exists() and git_ops.is_git_repo(work_path):
        click.echo(f"Updating {work_path}...")
        git_ops.pull_rebase(work_path)

    click.echo(f"Checking out branch {branch}...")
    git_ops.checkout_branch(work_path, branch, create=True)

    # For GitHub backend: push branch and create draft PR if not already set
    backend_name = data["project"].get("backend", "vanilla")
    if backend_name == "github" and not pr_entry.get("gh_pr_number"):
        base_branch = data["project"].get("base_branch", "master")
        title = pr_entry.get("title", pr_id)
        desc = pr_entry.get("description", "")

        # Create empty commit so the branch has something to push
        commit_msg = f"Start work on: {title}\n\nPR: {pr_id}"
        git_ops.run_git("commit", "--allow-empty", "-m", commit_msg, cwd=work_path)

        click.echo(f"Pushing branch {branch}...")
        push_result = git_ops.run_git("push", "-u", "origin", branch, cwd=work_path, check=False)
        if push_result.returncode != 0:
            click.echo(f"Warning: Failed to push branch: {push_result.stderr}", err=True)
        else:
            click.echo("Creating draft PR on GitHub...")
            from pm_core import gh_ops
            pr_info = gh_ops.create_draft_pr(str(work_path), title, base_branch, desc)
            if pr_info:
                pr_entry["gh_pr"] = pr_info["url"]
                pr_entry["gh_pr_number"] = pr_info["number"]
                click.echo(f"Draft PR created: {pr_info['url']}")
            else:
                click.echo("Warning: Failed to create draft PR.", err=True)

    # Update state — only advance from pending; don't regress in_review/merged
    if pr_entry.get("status") == "pending":
        pr_entry["status"] = "in_progress"
    pr_entry["agent_machine"] = platform.node()
    pr_entry["workdir"] = str(work_path)
    data["project"]["active_pr"] = pr_id
    save_and_push(data, root, f"pm: start {pr_id}")
    trigger_tui_refresh()

    click.echo(f"\nPR {_pr_display_id(pr_entry)} is now in_progress on {platform.node()}")
    click.echo(f"Work directory: {work_path}")

    prompt = prompt_gen.generate_prompt(data, pr_id, session_name=pm_session)

    claude = find_claude()
    if not claude:
        click.echo(f"\n{'='*60}")
        click.echo("CLAUDE PROMPT:")
        click.echo(f"{'='*60}\n")
        click.echo(prompt)
        return

    # Try to launch in the pm tmux session
    if pm_session:
        if tmux_mod.session_exists(pm_session):
            window_name = _pr_display_id(pr_entry)
            cmd = build_claude_shell_cmd(prompt=prompt,
                                         transcript=transcript, cwd=str(work_path))
            try:
                tmux_mod.new_window(pm_session, window_name, cmd, str(work_path),
                                    switch=not background)
                win = tmux_mod.find_window_by_name(pm_session, window_name)
                if win:
                    tmux_mod.set_shared_window_size(pm_session, win["id"])
                click.echo(f"Launched Claude in tmux window '{window_name}' (session: {pm_session})")
                return
            except Exception as e:
                click.echo(f"Failed to create tmux window: {e}", err=True)
                click.echo("Launching Claude in current terminal...")

    # Fall through: launch interactively in current terminal
    session_key = f"pr:start:{pr_id}"
    if fresh:
        clear_session(root, session_key)
    click.echo("Launching Claude...")
    launch_claude(prompt, cwd=str(work_path), session_key=session_key, pm_root=root, resume=not fresh)


def _launch_review_window(data: dict, pr_entry: dict, fresh: bool = False,
                          background: bool = False,
                          review_loop: bool = False, review_iteration: int = 0,
                          review_loop_id: str = "",
                          transcript: str | None = None) -> None:
    """Launch a tmux review window with Claude review + git diff shell."""
    if not tmux_mod.has_tmux() or not tmux_mod.in_tmux():
        click.echo("Review window requires tmux.")
        return

    pm_session = _get_pm_session()
    if not pm_session or not tmux_mod.session_exists(pm_session):
        click.echo(f"Review window: tmux session '{pm_session}' not found.")
        return

    workdir = pr_entry.get("workdir")
    if not workdir:
        click.echo(f"Review window: no workdir for {pr_entry['id']}. Start the PR first.")
        return

    # Review loop always forces a fresh window
    if review_loop:
        fresh = True

    pr_id = pr_entry["id"]
    display_id = _pr_display_id(pr_entry)
    title = pr_entry.get("title", "")
    base_branch = data.get("project", {}).get("base_branch", "master")

    # Generate review prompt and build Claude command
    review_prompt = prompt_gen.generate_review_prompt(data, pr_id, session_name=pm_session,
                                                      review_loop=review_loop,
                                                      review_iteration=review_iteration,
                                                      review_loop_id=review_loop_id)
    claude_cmd = build_claude_shell_cmd(prompt=review_prompt,
                                         transcript=transcript, cwd=workdir)

    window_name = f"review-{display_id}"

    # If review window already exists, kill it if fresh, otherwise switch to it
    existing = tmux_mod.find_window_by_name(pm_session, window_name)
    # Remember which grouped sessions were watching the review window —
    # after we kill and recreate it, those sessions should follow to the
    # new window.  Check ALL sessions in the group, not just the current one.
    sessions_on_review: list[str] = []
    if existing:
        if fresh:
            if review_loop:
                sessions_on_review = tmux_mod.sessions_on_window(
                    pm_session, existing["id"],
                )
            tmux_mod.kill_window(pm_session, existing["id"])
            click.echo(f"Killed existing review window '{window_name}'")
        else:
            tmux_mod.select_window(pm_session, existing["id"])
            click.echo(f"Switched to existing review window '{window_name}'")
            return

    # In review loop mode or background mode, create the window without
    # switching focus.  For review loops the explicit per-session switching
    # below handles moving exactly the sessions that were watching the old
    # window.  Background mode is used by auto-start to avoid stealing focus.
    switch = not review_loop and not background

    try:
        claude_pane = tmux_mod.new_window_get_pane(
            pm_session, window_name, claude_cmd, workdir,
            switch=switch,
        )
        if not claude_pane:
            click.echo(f"Review window: failed to create tmux window '{window_name}'.")
            return

        # Build shell command that shows PR info via a pager then drops
        # to an interactive shell in the workdir.  We use git --no-pager
        # and pipe through less ourselves so that quitting the pager
        # doesn't kill the pane (git's built-in pager can cause SIGPIPE
        # exit codes that break && chains).
        shell = os.environ.get("SHELL", "/bin/bash")
        header = f"Review: {display_id} — {title}"
        # Use backend-appropriate diff base:
        #   local:   merge-base between base_branch and HEAD (no remote)
        #   vanilla/github: origin/{base_branch}...HEAD
        backend_name = data.get("project", {}).get("backend", "vanilla")
        if backend_name == "local":
            diff_ref = base_branch
        else:
            diff_ref = f"origin/{base_branch}"
        diff_cmd = (
            f"cd '{workdir}'"
            f" && {{ echo '=== {header} ==='"
            f" && echo ''"
            f" && git status"
            f" && echo ''"
            f" && echo '--- Change summary ---'"
            f" && git --no-pager diff --stat {diff_ref}...HEAD"
            f" && echo ''"
            f" && echo '--- Full diff ---'"
            f" && git --no-pager diff {diff_ref}...HEAD"
            f"; }} | less -R"
            f"; exec {shell}"
        )
        diff_pane = tmux_mod.split_pane_at(claude_pane, "h", diff_cmd, background=True)

        # Register review panes under the review window (multi-window safe).
        # Derive window ID from the pane we just created rather than
        # searching by name, which is more robust.
        wid_result = subprocess.run(
            tmux_mod._tmux_cmd("display", "-t", claude_pane, "-p", "#{window_id}"),
            capture_output=True, text=True,
        )
        review_win_id = wid_result.stdout.strip()
        if review_win_id:
            tmux_mod.set_shared_window_size(pm_session, review_win_id)
            pane_registry.register_pane(pm_session, review_win_id, claude_pane, "review-claude", claude_cmd)
            if diff_pane:
                pane_registry.register_pane(pm_session, review_win_id, diff_pane, "review-diff", "diff-shell")

        # Reset user_modified so the registry is clean before rebalance.
        # This mirrors the same pattern used in pane_ops.launch_pane()
        # and pane_layout._respawn_tui() — any code path that creates
        # panes must reset user_modified (the after-split-window hook
        # sets it before panes are registered) and then rebalance.
        if review_win_id:
            reg = pane_registry.load_registry(pm_session)
            wdata = pane_registry.get_window_data(reg, review_win_id)
            wdata["user_modified"] = False
            pane_registry.save_registry(pm_session, reg)

        # Switch ALL grouped sessions that were watching the old review
        # window to the new one.  new_window_get_pane only switches one
        # session (via current_or_base_session), so we need to explicitly
        # switch any others that were also on the review window.
        #
        # select-window alone does NOT update tmux's client tracking.
        # switch-client to the same session is a visible no-op but
        # triggers tmux to recalculate the window size for the
        # correct display.
        if sessions_on_review:
            new_win = tmux_mod.find_window_by_name(pm_session, window_name)
            if new_win:
                # Map session names → client TTYs for switch-client.
                client_map: dict[str, str] = {}
                r = subprocess.run(
                    tmux_mod._tmux_cmd(
                        "list-clients", "-F",
                        "#{session_name} #{client_tty}",
                    ),
                    capture_output=True, text=True,
                )
                if r.returncode == 0:
                    for line in r.stdout.strip().splitlines():
                        parts = line.split(None, 1)
                        if len(parts) == 2:
                            client_map[parts[0]] = parts[1]

                for sess_name in sessions_on_review:
                    subprocess.run(
                        tmux_mod._tmux_cmd(
                            "select-window", "-t",
                            f"{sess_name}:{new_win['index']}",
                        ),
                        capture_output=True,
                    )
                    # Make this session's client the "latest" so tmux
                    # recalculates window size for its display.
                    client_tty = client_map.get(sess_name)
                    if client_tty:
                        subprocess.run(
                            tmux_mod._tmux_cmd(
                                "switch-client", "-t", sess_name,
                                "-c", client_tty,
                            ),
                            capture_output=True,
                        )

        # Rebalance AFTER session switches so get_reliable_window_size()
        # sees the correct dimensions.
        if review_win_id:
            pane_layout.rebalance(pm_session, review_win_id)

        click.echo(f"Opened review window '{window_name}'")
    except Exception as e:
        _log.warning("Failed to launch review window: %s", e)
        click.echo(f"Review window error: {e}")


@pr.command("review")
@click.argument("pr_id", default=None, required=False)
@click.option("--fresh", is_flag=True, default=False, help="Kill existing review window and create a new one")
@click.option("--background", is_flag=True, default=False, hidden=True,
              help="Create review window without switching focus (used by auto-start)")
@click.option("--review-loop", is_flag=True, default=False, help="Use review loop prompt (fix/commit/push)")
@click.option("--review-iteration", default=0, type=int, help="Review loop iteration number (for commit messages)")
@click.option("--review-loop-id", default="", help="Unique review loop identifier (for commit messages)")
@click.option("--transcript", default=None, hidden=True,
              help="Path to save Claude transcript symlink (used by auto-start)")
def pr_review(pr_id: str | None, fresh: bool, background: bool, review_loop: bool, review_iteration: int, review_loop_id: str, transcript: str | None):
    """Mark a PR as in_review and launch a review window.

    If PR_ID is omitted, infers from cwd (if inside a workdir) or
    auto-selects when there's exactly one in_progress PR.
    """
    root = state_root()
    data = store.load(root)

    if pr_id is None:
        pr_id = _infer_pr_id(data, status_filter=("in_progress",))
        if pr_id is None:
            prs = data.get("prs") or []
            in_progress = [p for p in prs if p.get("status") == "in_progress"]
            if len(in_progress) == 0:
                click.echo("No in_progress PRs to review.", err=True)
            else:
                click.echo("Multiple in_progress PRs. Specify one:", err=True)
                for p in in_progress:
                    click.echo(f"  {_pr_display_id(p)}: {p.get('title', '???')} ({p.get('agent_machine', '')})", err=True)
            raise SystemExit(1)
        click.echo(f"Auto-selected {pr_id}")

    pr_entry = _require_pr(data, pr_id)
    pr_id = pr_entry["id"]

    if pr_entry.get("status") == "merged":
        click.echo(f"PR {pr_id} is already merged.", err=True)
        raise SystemExit(1)
    if pr_entry.get("status") == "in_review":
        click.echo(f"PR {pr_id} is already in_review.")
        _launch_review_window(data, pr_entry, fresh=fresh, background=background,
                              review_loop=review_loop,
                              review_iteration=review_iteration,
                              review_loop_id=review_loop_id,
                              transcript=transcript)
        return
    if pr_entry.get("status") == "pending":
        click.echo(f"PR {pr_id} is pending — start it first with: pm pr start {pr_id}", err=True)
        raise SystemExit(1)

    # For GitHub backend: upgrade draft PR to ready for review
    backend_name = data["project"].get("backend", "vanilla")
    gh_pr_number = pr_entry.get("gh_pr_number")
    workdir = pr_entry.get("workdir")

    if backend_name == "github" and gh_pr_number and workdir:
        from pm_core import gh_ops
        click.echo(f"Marking PR #{gh_pr_number} as ready for review...")
        if gh_ops.mark_pr_ready(workdir, gh_pr_number):
            click.echo("Draft PR upgraded to ready for review.")
        else:
            click.echo("Warning: Failed to upgrade draft PR. It may already be ready or was closed.", err=True)

    pr_entry["status"] = "in_review"
    save_and_push(data, root, f"pm: review {pr_id}")
    click.echo(f"PR {_pr_display_id(pr_entry)} marked as in_review.")
    trigger_tui_refresh()
    _launch_review_window(data, pr_entry, fresh=fresh, background=background,
                          review_loop=review_loop,
                          review_iteration=review_iteration,
                          review_loop_id=review_loop_id,
                          transcript=transcript)


def _finalize_merge(data: dict, root, pr_entry: dict, pr_id: str,
                    transcript: str | None = None) -> None:
    """Mark PR as merged, kill tmux windows, and show newly ready PRs."""
    pr_entry["status"] = "merged"

    # Auto-start state is in-memory on the TUI — check_and_start()
    # detects target-merged and disables it there.

    save_and_push(data, root, f"pm: merge {pr_id}")
    click.echo(f"PR {_pr_display_id(pr_entry)} marked as merged.")
    trigger_tui_refresh()

    # Kill tmux windows for the merged PR (they're inaccessible from the TUI)
    try:
        from pm_core.cli.helpers import _find_tui_pane
        _, session = _find_tui_pane()
        if session:
            kill_pr_windows(session, pr_entry)
    except Exception:
        pass

    # Finalize merge transcript if provided
    if transcript:
        finalize_transcript(Path(transcript))

    # Show newly unblocked PRs
    prs = data.get("prs") or []
    ready = graph.ready_prs(prs)
    if ready:
        click.echo("\nNewly ready PRs:")
        for p in ready:
            click.echo(f"  ⏳ {_pr_display_id(p)}: {p.get('title', '???')}")


def _launch_merge_window(data: dict, pr_entry: dict, error_output: str,
                         background: bool = False,
                         transcript: str | None = None) -> None:
    """Launch a tmux window with Claude to resolve a merge conflict."""
    if not tmux_mod.has_tmux() or not tmux_mod.in_tmux():
        click.echo("Merge window requires tmux.")
        return

    pm_session = _get_pm_session()
    if not pm_session or not tmux_mod.session_exists(pm_session):
        click.echo(f"Merge window: tmux session '{pm_session}' not found.")
        return

    workdir = pr_entry.get("workdir")
    if not workdir:
        click.echo(f"Merge window: no workdir for {pr_entry['id']}.")
        return

    pr_id = pr_entry["id"]
    display_id = _pr_display_id(pr_entry)

    merge_prompt = prompt_gen.generate_merge_prompt(
        data, pr_id, error_output, session_name=pm_session,
    )
    claude_cmd = build_claude_shell_cmd(prompt=merge_prompt,
                                         transcript=transcript, cwd=workdir)
    window_name = f"merge-{display_id}"

    # Kill existing merge window if present
    existing = tmux_mod.find_window_by_name(pm_session, window_name)
    if existing:
        tmux_mod.kill_window(pm_session, existing["id"])

    try:
        tmux_mod.new_window(
            pm_session, window_name, claude_cmd, workdir,
            switch=not background,
        )
        click.echo(f"Opened merge resolution window '{window_name}'")
    except Exception as e:
        _log.warning("Failed to launch merge window: %s", e)
        click.echo(f"Merge window error: {e}")


def _pull_after_github_merge(data: dict, pr_entry: dict, workdir: str,
                             base_branch: str, resolve_window: bool,
                             background: bool,
                             transcript: str | None) -> bool:
    """Pull latest base branch after a GitHub merge, with stash/unstash.

    Fetches origin, checks out the base branch, and pulls.  If the workdir
    has uncommitted changes they are stashed first and re-applied afterwards.
    When the stash pop produces conflicts and *resolve_window* is set, a
    Claude merge-resolution window is launched.

    Returns True if the pull completed cleanly, False if a merge window was
    launched (caller should skip ``_finalize_merge``).
    """
    work_path = Path(workdir)
    stashed = False

    # Stash uncommitted changes if dirty
    if _workdir_is_dirty(work_path):
        click.echo("Stashing uncommitted changes before pull...")
        stash_result = git_ops.run_git("stash", cwd=workdir, check=False)
        if stash_result.returncode == 0 and "No local changes" not in stash_result.stdout:
            stashed = True
        else:
            click.echo("Warning: Could not stash changes.", err=True)

    # Fetch and checkout base branch to get the merge commit
    git_ops.run_git("fetch", "origin", cwd=workdir, check=False)
    checkout_result = git_ops.run_git("checkout", base_branch, cwd=workdir, check=False)
    if checkout_result.returncode != 0:
        click.echo(f"Warning: Could not checkout {base_branch}: "
                    f"{checkout_result.stderr.strip()}", err=True)
    else:
        pull_result = git_ops.pull_rebase(work_path)
        if pull_result.returncode != 0:
            click.echo(f"Warning: Pull failed: {pull_result.stderr.strip()}", err=True)
        else:
            click.echo(f"Pulled latest {base_branch}.")

    # Pop stash
    if stashed:
        pop_result = git_ops.run_git("stash", "pop", cwd=workdir, check=False)
        if pop_result.returncode != 0:
            error_detail = (pop_result.stdout.strip() + "\n"
                            + pop_result.stderr.strip()).strip()
            error_msg = (f"Conflict applying stashed changes after GitHub merge:"
                         f"\n{error_detail}")
            click.echo(error_msg, err=True)
            if resolve_window:
                _launch_merge_window(data, pr_entry, error_msg,
                                     background=background, transcript=transcript)
                return False
            click.echo("Resolve conflicts manually.", err=True)
            return False
        click.echo("Restored stashed changes.")

    return True


@pr.command("merge")
@click.argument("pr_id", default=None, required=False)
@click.option("--resolve-window", is_flag=True, default=False, hidden=True,
              help="On merge conflict, launch a Claude resolution window instead of exiting")
@click.option("--background", is_flag=True, default=False, hidden=True,
              help="Create merge window without switching focus (used by auto-start)")
@click.option("--transcript", default=None, hidden=True,
              help="Path to save Claude transcript symlink (used by auto-start)")
def pr_merge(pr_id: str | None, resolve_window: bool, background: bool, transcript: str | None):
    """Merge a PR's branch into the base branch.

    For local/vanilla backends, performs a local git merge.
    For GitHub backend, merges via gh CLI if available, otherwise
    directs the user to merge on GitHub manually.
    If PR_ID is omitted, infers from cwd or auto-selects.
    """
    root = state_root()
    data = store.load(root)

    if pr_id is None:
        pr_id = _infer_pr_id(data, status_filter=("in_review",))
        if pr_id is None:
            click.echo("No in_review PR to merge.", err=True)
            raise SystemExit(1)
        click.echo(f"Auto-selected {pr_id}")

    pr_entry = _require_pr(data, pr_id)
    pr_id = pr_entry["id"]

    if pr_entry.get("status") == "merged":
        click.echo(f"PR {pr_id} is already merged.", err=True)
        raise SystemExit(1)
    if pr_entry.get("status") == "pending":
        click.echo(f"PR {pr_id} is pending — start and review it first.", err=True)
        raise SystemExit(1)

    backend_name = data["project"].get("backend", "vanilla")
    base_branch = data["project"].get("base_branch", "master")
    branch = pr_entry.get("branch", "")

    if backend_name == "github":
        gh_pr_number = pr_entry.get("gh_pr_number")
        workdir = pr_entry.get("workdir")
        if gh_pr_number and workdir and Path(workdir).exists() and shutil.which("gh"):
            click.echo(f"Merging GitHub PR #{gh_pr_number} via gh CLI...")
            merge_result = subprocess.run(
                ["gh", "pr", "merge", str(gh_pr_number), "--merge"],
                cwd=workdir, capture_output=True, text=True,
            )
            gh_merged = merge_result.returncode == 0
            if gh_merged:
                click.echo(f"GitHub PR #{gh_pr_number} merged.")
            else:
                # Check if PR was already merged (e.g. re-attempt after conflict resolution)
                from pm_core import gh_ops
                if gh_ops.is_pr_merged(workdir, branch):
                    click.echo(f"GitHub PR #{gh_pr_number} is already merged.")
                    gh_merged = True
                else:
                    click.echo(f"gh pr merge failed: {merge_result.stderr.strip()}", err=True)
                    click.echo("Falling back to manual instructions.", err=True)

            if gh_merged:
                pull_ok = _pull_after_github_merge(
                    data, pr_entry, workdir, base_branch,
                    resolve_window=resolve_window,
                    background=background,
                    transcript=transcript,
                )
                if pull_ok:
                    _finalize_merge(data, root, pr_entry, pr_id, transcript=transcript)
                # If not pull_ok and resolve_window, a merge window was launched.
                # The idle tracker will re-attempt and finalize after resolution.
                return

        # Fallback: direct user to merge manually
        gh_pr = pr_entry.get("gh_pr")
        if gh_pr:
            click.echo(f"GitHub PR: {gh_pr}")
            click.echo("Merge via GitHub, then run 'pm pr sync' to detect it.")
        else:
            click.echo("No GitHub PR URL found. Merge manually on GitHub, then run 'pm pr sync'.")
        return

    # For local/vanilla: merge in the PR's workdir (branch always exists there)
    workdir = pr_entry.get("workdir")
    if not workdir or not Path(workdir).exists():
        click.echo(f"PR {pr_id} workdir not found. Cannot merge without the branch.", err=True)
        raise SystemExit(1)

    work_path = Path(workdir)

    # Pre-merge check: abort if workdir has uncommitted changes
    if _workdir_is_dirty(work_path):
        error_msg = f"Workdir has uncommitted changes: {workdir}"
        click.echo(error_msg, err=True)
        click.echo("Commit or stash your changes before merging.", err=True)
        if resolve_window:
            _launch_merge_window(data, pr_entry, error_msg, background=background,
                                 transcript=transcript)
            return
        raise SystemExit(1)

    # Fetch latest from origin (important for vanilla backend where others may push)
    if backend_name == "vanilla":
        click.echo("Fetching latest from origin...")
        git_ops.run_git("fetch", "origin", cwd=workdir, check=False)

    # Capture the branch tip before merge for post-merge verification
    tip_result = git_ops.run_git("rev-parse", branch, cwd=workdir, check=False)
    branch_tip = tip_result.stdout.strip() if tip_result.returncode == 0 else None

    click.echo(f"Merging {branch} into {base_branch}...")
    result = git_ops.run_git("checkout", base_branch, cwd=workdir, check=False)
    if result.returncode != 0:
        error_msg = f"Failed to checkout {base_branch}: {result.stderr.strip()}"
        click.echo(error_msg, err=True)
        if resolve_window:
            _launch_merge_window(data, pr_entry, error_msg, background=background,
                                 transcript=transcript)
            return
        raise SystemExit(1)
    result = git_ops.run_git("merge", "--no-ff", branch, "-m",
                             f"Merge {branch}: {pr_entry.get('title', pr_id)}",
                             cwd=workdir, check=False)
    if result.returncode != 0:
        # Git sends conflict details to stdout, other errors to stderr
        error_detail = (result.stdout.strip() + "\n" + result.stderr.strip()).strip()
        error_msg = f"Merge failed:\n{error_detail}" if error_detail else "Merge failed"
        click.echo(error_msg, err=True)
        click.echo("Resolve conflicts manually, then run 'pm pr merge' again.", err=True)
        if resolve_window:
            _launch_merge_window(data, pr_entry, error_msg, background=background,
                                 transcript=transcript)
            return
        raise SystemExit(1)

    # Post-merge verification: confirm the branch tip is now an ancestor of HEAD
    if branch_tip:
        verify = git_ops.run_git(
            "merge-base", "--is-ancestor", branch_tip, "HEAD",
            cwd=workdir, check=False,
        )
        if verify.returncode != 0:
            click.echo(f"Warning: Post-merge verification failed — branch tip {branch_tip[:8]} "
                        f"is not an ancestor of {base_branch} HEAD.", err=True)
            click.echo("The merge commit exists but may not include all branch commits.", err=True)

    # Push the merged base_branch back to origin (works for both bare and
    # non-bare repos).  For local backend, origin is the original repo path.
    push_result = git_ops.run_git("push", "origin", base_branch, cwd=workdir, check=False)
    if push_result.returncode != 0:
        click.echo(f"Warning: Push failed: {push_result.stderr.strip()}", err=True)
        click.echo("The merge is in the workdir. Push or pull manually when ready.")
    else:
        click.echo(f"Pushed merged {base_branch} to origin.")

    _finalize_merge(data, root, pr_entry, pr_id, transcript=transcript)


@pr.command("sync")
def pr_sync():
    """Check for merged PRs and unblock dependents (GitHub backend only).

    For local/vanilla backends, use 'pm pr merge' instead.
    Needs at least one workdir to exist (created by 'pm pr start').
    """
    root = state_root()
    data = store.load(root)
    backend_name = data["project"].get("backend", "vanilla")
    base_branch = data["project"].get("base_branch", "master")
    prs = data.get("prs") or []
    updated = 0

    # Only the github backend can reliably auto-detect merges (via API).
    # Local/vanilla backends rely on `pm pr merge` for explicit tracking.
    if backend_name != "github":
        click.echo("Auto-merge detection is only available for the GitHub backend.")
        click.echo("Use 'pm pr merge <pr-id>' to merge local/vanilla PRs.")
        return

    backend = get_backend(data)

    # Find any existing workdir to check merge status from
    target_workdir = None
    for p in prs:
        wd = p.get("workdir")
        if wd and Path(wd).exists() and git_ops.is_git_repo(wd):
            target_workdir = wd
            break
    if not target_workdir:
        workdirs_base = _workdirs_dir(data)
        if workdirs_base.exists():
            for d in workdirs_base.iterdir():
                if d.is_dir() and git_ops.is_git_repo(d):
                    target_workdir = str(d)
                    break

    if not target_workdir:
        click.echo("No workdirs found. Run 'pm pr start' on a PR first.", err=True)
        raise SystemExit(1)

    for pr_entry in prs:
        if pr_entry.get("status") not in ("in_review", "in_progress"):
            continue
        branch = pr_entry.get("branch", "")
        # Prefer PR's own workdir if it exists
        wd = pr_entry.get("workdir")
        check_dir = wd if (wd and Path(wd).exists()) else target_workdir

        if backend.is_merged(str(check_dir), branch, base_branch):
            pr_entry["status"] = "merged"
            click.echo(f"  ✅ {_pr_display_id(pr_entry)}: merged")
            updated += 1

    if updated:
        save_and_push(data, root, f"pm: sync - {updated} PRs merged")
        trigger_tui_refresh()
    else:
        click.echo("No new merges detected.")

    # Show newly unblocked PRs
    ready = graph.ready_prs(prs)
    if ready:
        click.echo("\nNewly ready PRs:")
        for p in ready:
            click.echo(f"  ⏳ {_pr_display_id(p)}: {p.get('title', '???')}")


@pr.command("sync-github")
def pr_sync_github():
    """Fetch and update PR statuses from GitHub.

    For each PR with a GitHub PR number, fetches the current state
    from GitHub and updates the local status accordingly:
    - MERGED → merged
    - CLOSED → closed
    - OPEN + draft → in_progress
    - OPEN + ready → in_review
    """
    root = state_root()
    data = store.load(root)

    backend_name = data["project"].get("backend", "vanilla")
    if backend_name != "github":
        click.echo("This command only works with the GitHub backend.", err=True)
        raise SystemExit(1)

    # Use the shared sync function
    result = pr_sync_mod.sync_from_github(root, data, save_state=True)

    if result.error:
        click.echo(f"Error: {result.error}", err=True)
        raise SystemExit(1)

    if result.updated_count > 0:
        click.echo(f"Updated {result.updated_count} PR(s).")
        if result.merged_prs:
            click.echo(f"  Merged: {', '.join(result.merged_prs)}")
        if result.closed_prs:
            click.echo(f"  Closed: {', '.join(result.closed_prs)}")
        trigger_tui_refresh()
    else:
        click.echo("No status changes.")


@pr.command("import-github")
@click.option("--state", "gh_state", default="all", help="GitHub PR state to import: open, closed, merged, all")
def pr_import_github(gh_state: str):
    """Import existing GitHub PRs into the project yaml.

    Fetches PRs from GitHub and creates yaml entries for any not already
    tracked. Matches existing entries by branch name or GH PR number.
    Skips PRs that are already in the yaml.

    \b
    Examples:
      pm pr import-github              # import all PRs
      pm pr import-github --state open # only open PRs
    """
    root = state_root()
    data = store.load(root)

    backend_name = data["project"].get("backend", "vanilla")
    if backend_name != "github":
        click.echo("This command only works with the GitHub backend.", err=True)
        raise SystemExit(1)

    from pm_core import gh_ops

    repo_dir = str(_resolve_repo_dir(root, data))

    click.echo("Fetching PRs from GitHub...")
    gh_prs = gh_ops.list_prs(repo_dir, state=gh_state)
    if not gh_prs:
        click.echo("No PRs found on GitHub.")
        return

    # Build lookup of existing entries by branch and gh_pr_number
    existing_branches = {p.get("branch") for p in (data.get("prs") or [])}
    existing_gh_numbers = {p.get("gh_pr_number") for p in (data.get("prs") or []) if p.get("gh_pr_number")}

    if data.get("prs") is None:
        data["prs"] = []

    imported = 0
    skipped = 0
    for gh_pr in gh_prs:
        branch = gh_pr.get("headRefName", "")
        number = gh_pr.get("number")
        title = gh_pr.get("title", "")

        # Skip if already tracked
        if branch in existing_branches or number in existing_gh_numbers:
            skipped += 1
            continue

        status = _gh_state_to_status(gh_pr.get("state", "OPEN"), gh_pr.get("isDraft", False))

        # Generate a hash-based pr_id from title + body
        existing_ids = {p["id"] for p in data["prs"]}
        url = gh_pr.get("url", "")
        body = gh_pr.get("body", "") or ""
        pr_id = store.generate_pr_id(title, body, existing_ids)

        entry = _make_pr_entry(pr_id, title, branch, status=status,
                               description=body, gh_pr=url,
                               gh_pr_number=number)
        data["prs"].append(entry)
        existing_ids.add(pr_id)
        existing_branches.add(branch)
        existing_gh_numbers.add(number)
        imported += 1
        click.echo(f"  + {pr_id}: {title} [{status}] (#{number})")

    if imported:
        save_and_push(data, root, "pm: import github PRs")
        click.echo(f"\nImported {imported} PR(s), skipped {skipped} already tracked.")
        trigger_tui_refresh()
    else:
        click.echo(f"No new PRs to import ({skipped} already tracked).")


def _workdir_is_dirty(work_path: Path) -> bool:
    """Check if a workdir has uncommitted changes."""
    result = git_ops.run_git("status", "--porcelain", cwd=work_path, check=False)
    return bool(result.stdout.strip())


def _cleanup_pr(pr_entry: dict, data: dict, root: Path, force: bool) -> bool:
    """Clean up a single PR's workdir. Returns True if cleaned."""
    pr_id = pr_entry["id"]
    work_path = Path(pr_entry["workdir"]) if pr_entry.get("workdir") else None

    if not work_path or not work_path.exists():
        click.echo(f"  {pr_id}: no workdir to clean up")
        return False

    if not force and _workdir_is_dirty(work_path):
        click.echo(f"  {pr_id}: skipped (uncommitted changes in {work_path})")
        click.echo(f"    Use --force to remove anyway")
        return False

    shutil.rmtree(work_path)
    click.echo(f"  {pr_id}: removed {work_path}")
    pr_entry["workdir"] = None
    return True


@pr.command("cleanup")
@click.argument("pr_id", default=None, required=False)
@click.option("--force", is_flag=True, default=False, help="Remove even if workdir has uncommitted changes")
@click.option("--all", "cleanup_all", is_flag=True, default=False, help="Clean up all PR workdirs")
@click.option("--prune", is_flag=True, default=False, help="Clear workdir references for paths that no longer exist")
def pr_cleanup(pr_id: str | None, force: bool, cleanup_all: bool, prune: bool):
    """Remove work directory for a PR.

    Refuses to delete workdirs with uncommitted changes unless --force is given.
    Use --all to clean up all PR workdirs at once.
    Use --prune to clear stale workdir references from project.yaml.
    """
    root = state_root()
    data = store.load(root)

    if prune:
        prs = data.get("prs") or []
        pruned = 0
        for p in prs:
            wd = p.get("workdir")
            if wd and not Path(wd).exists():
                click.echo(f"  {p['id']}: cleared missing workdir {wd}")
                p["workdir"] = None
                pruned += 1
        if pruned:
            save_and_push(data, root, f"pm: prune {pruned} missing workdirs")
            trigger_tui_refresh()
            click.echo(f"Pruned {pruned} stale workdir reference(s).")
        else:
            click.echo("No stale workdir references found.")
        if not cleanup_all and not pr_id:
            return

    if cleanup_all:
        prs = data.get("prs") or []
        with_workdir = [p for p in prs if p.get("workdir") and Path(p["workdir"]).exists()]
        if not with_workdir:
            click.echo("No PR workdirs to clean up.")
            return
        click.echo(f"Cleaning up {len(with_workdir)} workdir(s)...")
        cleaned = 0
        for pr_entry in with_workdir:
            if _cleanup_pr(pr_entry, data, root, force):
                cleaned += 1
        if cleaned:
            save_and_push(data, root, f"pm: cleanup {cleaned} workdirs")
            trigger_tui_refresh()
        click.echo(f"Cleaned {cleaned}/{len(with_workdir)} workdirs.")
        return

    if pr_id is None:
        prs = data.get("prs") or []
        with_workdir = [p for p in prs if p.get("status") == "merged" and p.get("workdir")
                        and Path(p["workdir"]).exists()]
        if len(with_workdir) == 1:
            pr_id = with_workdir[0]["id"]
            click.echo(f"Auto-selected {pr_id}")
        elif len(with_workdir) == 0:
            click.echo("No merged PRs with workdirs to clean up.", err=True)
            raise SystemExit(1)
        else:
            click.echo("Multiple merged PRs have workdirs. Specify one:", err=True)
            for p in with_workdir:
                click.echo(f"  {_pr_display_id(p)}: {p.get('title', '???')}", err=True)
            raise SystemExit(1)

    pr_entry = _resolve_pr_id(data, pr_id)
    if not pr_entry:
        click.echo(f"PR '{pr_id}' not found.", err=True)
        raise SystemExit(1)

    if pr_entry.get("status") not in ("merged", "in_review"):
        click.echo(f"Warning: {pr_id} status is '{pr_entry.get('status')}' (not merged).", err=True)
        click.echo("Cleaning up anyway.", err=True)

    if _cleanup_pr(pr_entry, data, root, force):
        save_and_push(data, root, f"pm: cleanup {pr_entry['id']}")
        trigger_tui_refresh()


@pr.group("note")
def pr_note():
    """Manage notes on a PR."""
    pass


@pr_note.command("add")
@click.argument("pr_id")
@click.argument("text")
def pr_note_add(pr_id: str, text: str):
    """Add a note to a PR.

    TEXT is the note content. Use quotes for multi-word notes.
    """
    root = state_root()
    data = store.load(root)
    pr_entry = _require_pr(data, pr_id)
    pr_id = pr_entry["id"]

    notes = pr_entry.get("notes") or []
    existing_ids = {n["id"] for n in notes}
    note_id = store.generate_note_id(pr_id, text, existing_ids)
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    notes.append({"id": note_id, "text": text, "created_at": created_at, "last_edited": created_at})
    pr_entry["notes"] = notes

    save_and_push(data, root, f"pm: note on {pr_id}")
    click.echo(f"Added note {note_id} to {_pr_display_id(pr_entry)}")
    trigger_tui_refresh()


@pr_note.command("edit")
@click.argument("pr_id")
@click.argument("note_id")
@click.argument("text")
def pr_note_edit(pr_id: str, note_id: str, text: str):
    """Edit the text of an existing note.

    NOTE_ID is the ID of the note to edit (e.g. note-a3f2b1c).
    TEXT is the new note content. Use quotes for multi-word notes.
    """
    root = state_root()
    data = store.load(root)
    pr_entry = _require_pr(data, pr_id)
    pr_id = pr_entry["id"]

    notes = pr_entry.get("notes") or []
    target = None
    for n in notes:
        if n["id"] == note_id:
            target = n
            break

    if target is None:
        click.echo(f"Note '{note_id}' not found on {_pr_display_id(pr_entry)}.", err=True)
        if notes:
            click.echo("Available notes:", err=True)
            for n in notes:
                click.echo(f"  {n['id']}: {n['text']}", err=True)
        raise SystemExit(1)

    # Update text and regenerate ID (hash is based on text)
    existing_ids = {n["id"] for n in notes if n["id"] != note_id}
    new_id = store.generate_note_id(pr_id, text, existing_ids)
    target["id"] = new_id
    target["text"] = text
    target["last_edited"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    save_and_push(data, root, f"pm: edit note on {pr_id}")
    click.echo(f"Updated note {note_id} → {new_id} on {_pr_display_id(pr_entry)}")
    trigger_tui_refresh()


@pr_note.command("list")
@click.argument("pr_id")
def pr_note_list(pr_id: str):
    """List notes on a PR."""
    root = state_root()
    data = store.load(root)
    pr_entry = _require_pr(data, pr_id)

    notes = pr_entry.get("notes") or []
    if not notes:
        click.echo(f"No notes on {_pr_display_id(pr_entry)}.")
        return
    for n in notes:
        ts = n.get("created_at", "")
        ts_str = f" ({ts})" if ts else ""
        click.echo(f"  {n['id']}{ts_str}: {n['text']}")


@pr_note.command("delete")
@click.argument("pr_id")
@click.argument("note_id")
def pr_note_delete(pr_id: str, note_id: str):
    """Delete a note from a PR by its note ID."""
    root = state_root()
    data = store.load(root)
    pr_entry = _require_pr(data, pr_id)
    pr_id = pr_entry["id"]

    notes = pr_entry.get("notes") or []
    original_len = len(notes)
    pr_entry["notes"] = [n for n in notes if n["id"] != note_id]

    if len(pr_entry["notes"]) == original_len:
        click.echo(f"Note '{note_id}' not found on {_pr_display_id(pr_entry)}.", err=True)
        if notes:
            click.echo("Available notes:", err=True)
            for n in notes:
                click.echo(f"  {n['id']}: {n['text']}", err=True)
        raise SystemExit(1)

    save_and_push(data, root, f"pm: delete note on {pr_id}")
    click.echo(f"Deleted note {note_id} from {_pr_display_id(pr_entry)}")
    trigger_tui_refresh()


@pr.command("close")
@click.argument("pr_id", default=None, required=False)
@click.option("--keep-github", is_flag=True, help="Don't close the GitHub PR")
@click.option("--keep-branch", is_flag=True, help="Don't delete the remote branch")
def pr_close(pr_id: str | None, keep_github: bool, keep_branch: bool):
    """Close and remove a PR from the project.

    Removes the PR entry from project.yaml. By default also closes the
    GitHub PR and deletes the remote branch if they exist.

    If PR_ID is omitted, uses the active PR.
    """
    root = state_root()
    data = store.load(root)

    if pr_id is None:
        pr_id = data.get("project", {}).get("active_pr")
        if not pr_id:
            click.echo("No active PR. Specify a PR ID.", err=True)
            raise SystemExit(1)
        click.echo(f"Using active PR: {pr_id}")

    pr_entry = _require_pr(data, pr_id)
    pr_id = pr_entry["id"]

    # Close GitHub PR if exists
    gh_pr_number = pr_entry.get("gh_pr_number")
    if gh_pr_number and not keep_github:
        click.echo(f"Closing GitHub PR #{gh_pr_number}...")
        try:
            delete_flag = [] if keep_branch else ["--delete-branch"]
            result = subprocess.run(
                ["gh", "pr", "close", str(gh_pr_number), *delete_flag],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                click.echo(f"GitHub PR #{gh_pr_number} closed.")
            else:
                click.echo(f"Warning: Could not close GitHub PR: {result.stderr.strip()}", err=True)
        except Exception as e:
            click.echo(f"Warning: Could not close GitHub PR: {e}", err=True)

    # Remove workdir if exists
    workdir = pr_entry.get("workdir")
    if workdir and Path(workdir).exists():
        shutil.rmtree(workdir)
        click.echo(f"Removed workdir: {workdir}")

    # Remove PR from list
    prs = data.get("prs") or []
    data["prs"] = [p for p in prs if p["id"] != pr_id]

    # Update active_pr if needed
    if data.get("project", {}).get("active_pr") == pr_id:
        remaining = data.get("prs") or []
        data["project"]["active_pr"] = remaining[0]["id"] if remaining else None

    save_and_push(data, root, f"pm: close {pr_id}")
    click.echo(f"Removed {pr_id}: {pr_entry.get('title', '???')}")
    trigger_tui_refresh()
