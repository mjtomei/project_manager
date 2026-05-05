"""PR commands for the pm CLI.

Registers the ``pr`` group and all subcommands on the top-level ``cli`` group.
"""

import os
import platform
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import click
import yaml

from pm_core import store, graph, git_ops, prompt_gen
from pm_core.shell import shell_quote
from pm_core import pr_sync as pr_sync_mod
from pm_core import tmux as tmux_mod
from pm_core import pane_layout
from pm_core import pane_registry
from pm_core import spec_gen
from pm_core.backend import get_backend
from pm_core.claude_launcher import find_claude, build_claude_shell_cmd, clear_session, launch_claude, finalize_transcript

from pm_core.cli import cli
from pm_core.cli.helpers import (
    _ensure_workdir,
    _get_pm_session,
    _gh_state_to_status,
    _infer_pr_id,
    _log,
    _make_pr_entry,
    _pr_display_id,
    _pr_id_sort_key,
    _record_status_timestamp,
    _require_pr,
    _resolve_pr_id,
    _resolve_repo_dir,
    _resolve_repo_id,
    _workdirs_dir,
    echo_record,
    emit_paged,
    kill_pr_windows,
    state_root,
    trigger_tui_merge_lock,
    trigger_tui_merge_unlock,
    trigger_tui_refresh,
    trigger_tui_restart,
)


# ---------------------------------------------------------------------------
# PR edit helpers (shared between interactive editor and flag-based paths)
# ---------------------------------------------------------------------------

# Replace unicode characters that cause vim rendering issues with
# long wrapped lines (em/en dashes, smart quotes, etc.) with ASCII
# equivalents.  They are restored when parsing.
_UNICODE_TO_ASCII = [
    ("\u2014", "--"),   # em dash
    ("\u2013", "-"),    # en dash
    ("\u2018", "'"),    # left single quote
    ("\u2019", "'"),    # right single quote
    ("\u201c", '"'),    # left double quote
    ("\u201d", '"'),    # right double quote
    ("\u2026", "..."),  # ellipsis
]


def _restore_unicode(text: str) -> str:
    """Restore unicode characters that were replaced for the editor.

    Only safe to call on content fields (title, description, note text).
    Must NOT be applied to raw template text because the en-dash
    restoration (``-`` → ``–``) corrupts structural elements like
    note bullet prefixes (``- ``) and YAML-style field values.
    """
    for uc, ascii_rep in _UNICODE_TO_ASCII:
        text = text.replace(ascii_rep, uc)
    return text


def _parse_pr_edit_raw(raw: str) -> dict:
    """Parse a PR edit template into structured fields.

    Returns a dict with keys: title, status, depends_on_str, note_texts,
    description.  Fields not found in the template are ``None``
    (except *note_texts* which defaults to ``[]`` and *description*
    which defaults to ``""``).

    Unicode restoration is applied per-field to title, description, and
    note texts after parsing, so structural syntax (``- `` prefixes,
    field names) is never corrupted.
    """
    desc_lines: list[str] = []
    note_lines: list[str] = []
    in_desc = False
    in_notes = False
    title = None
    status = None
    deps_str = None

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
                text = re.sub(
                    r'\s+#\s+\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$', '', text
                )
                note_lines.append(text)
        elif line.startswith("title:"):
            title = line[len("title:"):].strip()
        elif line.startswith("status:"):
            status = line[len("status:"):].strip()
        elif line.startswith("depends_on:"):
            deps_str = line[len("depends_on:"):].strip()

    # Restore unicode only in content fields — never in status or deps
    # which would corrupt values like "in_progress" or structural syntax.
    return {
        "title": _restore_unicode(title) if title is not None else None,
        "status": status,
        "depends_on_str": deps_str,
        "note_texts": [_restore_unicode(t) for t in note_lines],
        "description": _restore_unicode("\n".join(desc_lines).strip()),
    }


def _apply_pr_edit(root: Path, pr_id: str, parsed: dict) -> list[str]:
    """Apply parsed PR edit changes under the project.yaml lock.

    Returns a list of change description strings (empty if nothing
    changed).  Invalid status values and unknown dependency IDs are
    silently skipped so this is safe to call from a background watcher.
    """
    changes: list[str] = []

    def apply(data):
        pr_entry = store.get_pr(data, pr_id)
        if not pr_entry:
            return

        # Title
        if parsed["title"] is not None:
            if parsed["title"] != pr_entry.get("title", ""):
                pr_entry["title"] = parsed["title"]
                changes.append(f"title={parsed['title']}")

        # Description
        if parsed["description"] != pr_entry.get("description", "").strip():
            pr_entry["description"] = parsed["description"]
            changes.append("description updated")

        # Status (skip invalid values silently)
        valid_statuses = {"pending", "in_progress", "in_review", "qa", "merged", "closed"}
        if parsed["status"] is not None:
            current_status = pr_entry.get("status", "pending")
            if parsed["status"] != current_status and parsed["status"] in valid_statuses:
                pr_entry["status"] = parsed["status"]
                changes.append(f"status: {current_status} → {parsed['status']}")
                _record_status_timestamp(pr_entry, parsed["status"])

        # Dependencies (skip unknown IDs silently)
        if parsed["depends_on_str"] is not None:
            current_deps = ", ".join(pr_entry.get("depends_on") or [])
            if parsed["depends_on_str"] != current_deps:
                if not parsed["depends_on_str"]:
                    pr_entry["depends_on"] = []
                    changes.append("depends_on cleared")
                else:
                    deps = [d.strip() for d in parsed["depends_on_str"].split(",")]
                    existing_ids = {p["id"] for p in (data.get("prs") or [])}
                    unknown = [d for d in deps if d not in existing_ids]
                    if not unknown:
                        pr_entry["depends_on"] = deps
                        changes.append(f"depends_on={', '.join(deps)}")

        # Notes reconciliation
        current_notes = pr_entry.get("notes") or []
        old_texts = [n["text"] for n in current_notes]
        if parsed["note_texts"] != old_texts:
            old_by_text: dict[str, list] = {}
            for n in current_notes:
                old_by_text.setdefault(n["text"], []).append(n)
            new_notes = []
            existing_note_ids: set[str] = set()
            for text in parsed["note_texts"]:
                if text in old_by_text and old_by_text[text]:
                    reused = old_by_text[text].pop(0)
                    new_notes.append(reused)
                    existing_note_ids.add(reused["id"])
                else:
                    note_id = store.generate_note_id(pr_id, text, existing_note_ids)
                    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    new_notes.append({
                        "id": note_id, "text": text,
                        "created_at": now, "last_edited": now,
                    })
                    existing_note_ids.add(note_id)
            new_notes.sort(
                key=lambda n: n.get("last_edited") or n.get("created_at", "")
            )
            pr_entry["notes"] = new_notes
            changes.append("notes updated")

        if changes:
            _record_status_timestamp(pr_entry)

    store.locked_update(root, apply)

    if changes:
        trigger_tui_refresh()

    return changes


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

    # Use a mutable container so the apply callback can communicate
    # the created entry back to the outer scope for display.
    result = {}

    def apply(data):
        if data.get("prs") is None:
            data["prs"] = []
        # Check for duplicate title+description against fresh state
        # inside the lock. This catches concurrent adds with the same
        # title that would otherwise generate different IDs (because
        # generate_pr_id extends the hash to avoid collisions).
        for p in data["prs"]:
            if p["title"] == title and p.get("description", "") == (desc or ""):
                result["entry"] = p
                result["duplicate"] = True
                return
        fresh_ids = {p["id"] for p in data["prs"]}
        pr_id = store.generate_pr_id(title, desc, fresh_ids)
        slug = store.slugify(title)
        branch = f"pm/{pr_id}-{slug}"
        entry = _make_pr_entry(pr_id, title, branch, plan=plan_id,
                               depends_on=deps, description=desc)
        data["prs"].append(entry)
        data["project"]["active_pr"] = pr_id
        result["entry"] = entry
        result["duplicate"] = False

    store.locked_update(root, apply)
    entry = result["entry"]
    pr_id = entry["id"]
    branch = entry["branch"]
    if result.get("duplicate"):
        click.echo(f"PR already exists: {_pr_display_id(entry)}: {title}")
    else:
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
@click.option("--status", default=None, type=click.Choice(["pending", "in_progress", "in_review", "qa", "merged", "closed"]),
              help="New status (pending, in_progress, in_review, qa, merged, closed)")
@click.option("--plan", default=None, help="Associated plan ID")
def pr_edit(pr_id: str, title: str | None, depends_on: str | None, desc: str | None, status: str | None, plan: str | None):
    """Edit an existing PR's title, description, dependencies, or status."""
    root = state_root()
    data = store.load(root)
    pr_entry = _require_pr(data, pr_id)
    pr_id = pr_entry["id"]

    changes = []
    if plan is not None:
        pr_entry["plan"] = plan if plan else None
        changes.append(f"plan={plan or 'none'}")
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
        _record_status_timestamp(pr_entry, status)
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
        # No flags given — open in $EDITOR with live save
        from pm_core.editor import run_watched_editor

        # Capture original state for post-edit comparison
        orig_title = pr_entry.get("title", "")
        orig_desc = pr_entry.get("description", "").strip()
        orig_status = pr_entry.get("status", "pending")
        orig_deps = ", ".join(pr_entry.get("depends_on") or [])
        orig_notes = [n["text"] for n in (pr_entry.get("notes") or [])]

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
            f"# Changes are saved each time you write the file.\n"
            f"\n"
            f"title: {orig_title}\n"
            f"status: {orig_status}\n"
            f"depends_on: {orig_deps}\n"
            f"\n"
            f"# Notes (bulleted list, one per line starting with '- '):\n"
            f"{notes_lines}"
            f"\n"
            f"# Description (everything below this line):\n"
            f"{orig_desc}\n"
        )

        editor_template = template
        for uc, ascii_rep in _UNICODE_TO_ASCII:
            editor_template = editor_template.replace(uc, ascii_rep)

        def on_save(raw: str) -> None:
            _apply_pr_edit(root, pr_id, _parse_pr_edit_raw(raw))

        ret, modified = run_watched_editor(editor_template, on_save)
        if ret != 0:
            click.echo("Editor exited with error.", err=True)
            raise SystemExit(1)
        if not modified:
            click.echo("No changes made.")
            raise SystemExit(0)

        # Report cumulative changes (original → final state)
        data_final = store.load(root)
        pr_final = store.get_pr(data_final, pr_id)
        if pr_final.get("title", "") != orig_title:
            changes.append(f"title={pr_final['title']}")
        if pr_final.get("description", "").strip() != orig_desc:
            changes.append("description updated")
        if pr_final.get("status", "pending") != orig_status:
            changes.append(f"status: {orig_status} → {pr_final['status']}")
        final_deps = ", ".join(pr_final.get("depends_on") or [])
        if final_deps != orig_deps:
            changes.append(f"depends_on={final_deps}")
        final_notes = [n["text"] for n in (pr_final.get("notes") or [])]
        if final_notes != orig_notes:
            changes.append("notes updated")

        if changes:
            click.echo(f"Updated {pr_id}: {', '.join(changes)}")
        else:
            click.echo("No changes detected.")
        return

    # Apply flag-based changes under lock
    def apply(data):
        pr = store.get_pr(data, pr_id)
        if not pr:
            return
        if plan is not None:
            pr["plan"] = plan if plan else None
        if title is not None:
            pr["title"] = title
        if desc is not None:
            pr["description"] = desc
        if status is not None:
            pr["status"] = status
            _record_status_timestamp(pr, status)
        if depends_on is not None:
            if depends_on == "":
                pr["depends_on"] = []
            else:
                pr["depends_on"] = [d.strip() for d in depends_on.split(",")]
        _record_status_timestamp(pr)

    store.locked_update(root, apply)
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

    store.locked_update(root, lambda d: d["project"].__setitem__("active_pr", pr_id))
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
@click.option("-t", "--timestamps", is_flag=True, default=False, help="Show updated_at timestamp and sort by most recently updated")
@click.option("--open", "open_only", is_flag=True, default=False, help="Exclude closed and merged PRs")
@click.option("--status", "filter_status", default=None, help="Show only PRs with this status (e.g. in_progress, qa, merged)")
@click.option("--plan", "filter_plan", default=None, help="Show only PRs in this plan (use '_standalone' for PRs with no plan)")
def pr_list(workdirs: bool, timestamps: bool, open_only: bool, filter_status: str | None, filter_plan: str | None):
    """List all PRs with status."""
    root = state_root()
    data = store.load(root)

    prs = data.get("prs") or []
    if not prs:
        click.echo("No PRs.")
        return

    if open_only:
        prs = [p for p in prs if p.get("status") not in ("closed", "merged")]
    if filter_status:
        prs = [p for p in prs if p.get("status") == filter_status]
    if filter_plan:
        prs = [p for p in prs if (p.get("plan") or "_standalone") == filter_plan]

    if timestamps:
        prs = sorted(prs, key=lambda p: p.get("updated_at") or p.get("created_at") or "", reverse=True)
    else:
        # Sort newest first (by gh_pr_number descending, then pr id descending)
        prs = sorted(prs, key=lambda p: (p.get("gh_pr_number") or _pr_id_sort_key(p["id"])[0], _pr_id_sort_key(p["id"])[1]), reverse=True)

    active_pr = data.get("project", {}).get("active_pr")
    status_icons = {
        "pending": "⏳",
        "in_progress": "🔨",
        "in_review": "👀",
        "qa": "🧪",
        "merged": "✅",
        "closed": "🚫",
        "blocked": "🚫",
    }
    out: list[str] = []
    for p in prs:
        icon = status_icons.get(p.get("status", "pending"), "?")
        deps = p.get("depends_on") or []
        dep_str = f" <- [{', '.join(deps)}]" if deps else ""
        machine = p.get("agent_machine")
        machine_str = f" ({machine})" if machine else ""
        active_str = " *" if p["id"] == active_pr else ""
        ts_str = ""
        if timestamps:
            ts = p.get("updated_at") or p.get("created_at") or ""
            if ts:
                try:
                    dt = datetime.fromisoformat(ts).astimezone()
                    ts_str = f" [{dt.strftime('%Y-%m-%d %H:%M')}]"
                except ValueError:
                    ts_str = f" [{ts}]"
        out.append(f"  {icon} {_pr_display_id(p)}: {p.get('title', '???')} [{p.get('status', '?')}]{dep_str}{machine_str}{active_str}{ts_str}")
        if workdirs:
            wd = p.get("workdir")
            if wd and Path(wd).exists():
                dirty = _workdir_is_dirty(Path(wd))
                dirty_str = " (dirty)" if dirty else " (clean)"
                out.append(f"      workdir: {wd}{dirty_str}")
            elif wd:
                out.append(f"      workdir: {wd} (missing)")
            else:
                out.append(f"      workdir: none")
    emit_paged(out)


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
    emit_paged([f"  ⏳ {_pr_display_id(p)}: {p.get('title', '???')}" for p in ready])


@pr.command("spec")
@click.argument("pr_id")
@click.argument("phase", default=None, required=False)
@click.option("--regenerate", is_flag=True, default=False, help="Regenerate even if spec exists")
def pr_spec(pr_id: str, phase: str | None, regenerate: bool):
    """View or generate specs for a PR.

    Without PHASE, shows all existing specs.
    With PHASE (impl, qa), shows or generates that spec.
    """
    root = state_root()
    data = store.load(root)
    pr_entry = _require_pr(data, pr_id)
    pr_id = pr_entry["id"]

    if phase is None:
        # Show all existing specs
        found = False
        for p in spec_gen.PHASES:
            spec_text = spec_gen.get_spec(pr_entry, p)
            if spec_text:
                found = True
                path = spec_gen.spec_file_path(root, pr_id, p)
                click.echo(f"\n{'='*60}")
                click.echo(f"spec_{p}  ({path})")
                click.echo(f"{'='*60}\n")
                click.echo(spec_text)
        if not found:
            click.echo(f"No specs generated yet for {_pr_display_id(pr_entry)}.")
            click.echo("Run `pm pr spec <pr-id> <phase>` to generate one.")
        return

    if phase not in spec_gen.PHASES:
        click.echo(f"Invalid phase: {phase}. Must be one of: {', '.join(spec_gen.PHASES)}", err=True)
        raise SystemExit(1)

    existing = spec_gen.get_spec(pr_entry, phase)
    if existing and not regenerate:
        click.echo(existing)
        return

    spec_text, needs_review = spec_gen.generate_spec(
        data, pr_id, phase, root=root, force=regenerate,
    )
    if spec_text:
        click.echo(spec_text)
        if needs_review:
            click.echo(f"\n[spec flagged for review — run `pm pr spec-approve {pr_id}`]", err=True)
    else:
        click.echo("Spec generation returned empty output.", err=True)


@pr.command("spec-path")
@click.argument("pr_id")
@click.argument("phase")
def pr_spec_path(pr_id: str, phase: str):
    """Print the file path for a PR's spec.

    Outputs just the path — suitable for use in shell pipelines:

      cat $(pm pr spec-path pr-001 impl)
      $EDITOR $(pm pr spec-path pr-001 qa)
    """
    root = state_root()
    data = store.load(root)
    pr_entry = _require_pr(data, pr_id)
    pr_id = pr_entry["id"]

    if phase not in spec_gen.PHASES:
        click.echo(f"Invalid phase: {phase}. Must be one of: {', '.join(spec_gen.PHASES)}", err=True)
        raise SystemExit(1)

    path = spec_gen.spec_file_path(root, pr_id, phase)
    click.echo(path)


@pr.command("spec-approve")
@click.argument("pr_id")
def pr_spec_approve(pr_id: str):
    """Approve a pending spec review for a PR.

    Opens the spec in an editor for review. Saving and closing approves it.
    """
    root = state_root()
    data = store.load(root)
    pr_entry = _require_pr(data, pr_id)
    pr_id = pr_entry["id"]

    phase = spec_gen.get_pending_spec_phase(pr_entry)
    if not phase:
        click.echo(f"No pending spec review for {_pr_display_id(pr_entry)}.")
        return

    spec_text = spec_gen.get_spec(pr_entry, phase) or ""
    if not spec_text:
        click.echo(f"Spec content is empty — nothing to review.", err=True)
        spec_gen.approve_spec(data, pr_id, root=root)
        return

    header_lines = [
        f"# Spec review: {phase} for {pr_id}",
        "# Edit as needed, then save and close to approve.",
        "# Delete all content to reject.",
        "",
    ]
    header = "\n".join(header_lines) + "\n"
    edited = click.edit(header + spec_text)
    if edited is not None:
        # Strip only the known header lines (not arbitrary # lines,
        # which would destroy markdown H1 headings in the spec).
        lines = edited.split("\n")
        # Remove leading lines that match our header exactly
        while lines and lines[0] in header_lines:
            lines.pop(0)
        edited_content = "\n".join(lines).strip()
        if not edited_content:
            feedback = click.prompt(
                "Spec rejected. Describe what to change (leave blank to regenerate as-is)",
                default="",
            )
            spec_gen.reject_spec(data, pr_id, feedback=feedback or None, root=root)
            # Reload to see whether spec_pending is still set after regen.
            # In prompt mode without ambiguity flags, generate_spec clears it.
            data = store.load(root)
            pr_entry = store.get_pr(data, pr_id) or pr_entry
            if spec_gen.has_pending_spec(pr_entry):
                click.echo(
                    f"Spec regenerated. Review again with: pm pr spec-approve {pr_id}"
                )
            else:
                click.echo(
                    "Spec regenerated and ready (no ambiguities flagged)."
                )
            trigger_tui_refresh()
            return
        spec_gen.approve_spec(data, pr_id, root=root, edited_text=edited_content)
        click.echo(f"Spec approved for {phase} phase.")
    else:
        # Editor returned None = no changes, approve as-is
        spec_gen.approve_spec(data, pr_id, root=root)
        click.echo(f"Spec approved (unchanged) for {phase} phase.")

    trigger_tui_refresh()


@pr.command("start")
@click.argument("pr_id", default=None, required=False)
@click.option("--workdir", default=None, help="Custom work directory")
@click.option("--fresh", is_flag=True, default=False, help="Start a fresh session (don't resume)")
@click.option("--background", is_flag=True, default=False, hidden=True,
              help="Create tmux window without switching focus (used by auto-start)")
@click.option("--transcript", default=None, hidden=True,
              help="Path to save Claude transcript symlink (used by auto-start)")
@click.option("--companion", is_flag=True, default=False,
              help="Open a companion shell pane in the PR workdir")
def pr_start(pr_id: str | None, workdir: str, fresh: bool, background: bool, transcript: str | None, companion: bool):
    """Start working on a PR: clone, branch, print prompt.

    If PR_ID is omitted, uses the active PR if it's pending/ready, or
    auto-selects the next ready PR (when there's exactly one).

    With --companion (or the ``companion-pane`` global setting), a second
    shell pane is opened alongside the Claude pane, cd'ed into the workdir.
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

    # Reload fresh data to catch any spec_pending written since load
    data = store.load(root)
    pr_entry = store.get_pr(data, pr_id) or pr_entry

    # Block if spec is pending review — must approve before implementation starts
    if spec_gen.has_pending_spec(pr_entry):
        phase = spec_gen.get_pending_spec_phase(pr_entry)
        click.echo(
            f"Spec ({phase}) for {_pr_display_id(pr_entry)} is pending review.",
            err=True,
        )
        click.echo(
            f"  Review: pm pr spec-approve {pr_id}  (or press 'V' in TUI)",
            err=True,
        )
        raise SystemExit(1)

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

    # Resolve companion: explicit flag or global setting
    from pm_core.paths import get_global_setting
    use_companion = companion or get_global_setting("companion-pane")

    # Fast path: if window already exists, switch to it (or kill it if --fresh)
    if pm_session:
        if tmux_mod.session_exists(pm_session):
            window_name = _pr_display_id(pr_entry)
            existing = tmux_mod.find_window_by_name(pm_session, window_name)
            if existing:
                if fresh:
                    tmux_mod.kill_window(pm_session, existing["id"])
                    click.echo(f"Killed existing window '{window_name}'")
                elif use_companion and not background:
                    # Add companion pane to existing window if missing
                    impl_workdir = pr_entry.get("workdir") or workdir
                    if impl_workdir:
                        _add_companion_pane(pm_session, existing, impl_workdir, "impl")
                    tmux_mod.select_window(pm_session, existing["id"])
                    click.echo(f"Switched to existing window '{window_name}' (session: {pm_session})")
                    return
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

    # Verify the PR exists in the committed project.yaml on base_branch.
    # The clone checks out base_branch, so if the PR isn't committed there
    # the workdir won't contain it, causing confusing downstream failures.
    internal = store.is_internal_pm_dir(root)
    repo_root = str(root.parent) if internal else str(root)
    yaml_path = "pm/project.yaml" if internal else "project.yaml"
    committed_result = git_ops.run_git(
        "show", f"{base_branch}:{yaml_path}", cwd=repo_root, check=False
    )
    pr_committed = committed_result.returncode == 0
    if pr_committed:
        try:
            committed_data = yaml.safe_load(committed_result.stdout) or {}
            if not isinstance(committed_data, dict):
                raise ValueError("not a mapping")
        except (yaml.YAMLError, ValueError):
            pr_committed = False
        else:
            pr_committed = bool(store.get_pr(committed_data, pr_id))
    if not pr_committed:
        # Distinguish: does the PR exist in the current (working) project.yaml?
        if store.get_pr(data, pr_id):
            click.echo(
                f"PR {pr_id} is not committed on {base_branch} yet. "
                f"Run `pm push` to commit project state before starting.",
                err=True,
            )
        else:
            click.echo(
                f"PR {pr_id} was not found in project.yaml. "
                f"Check that the PR ID is correct and has been added to the project.",
                err=True,
            )
        raise SystemExit(1)

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
            # Clone locally from the existing repo (fast) instead of
            # from the remote URL (slow, subject to network issues).
            # When PM state lives in a pm/ subdir, the git repo is the parent.
            local_source = str(root.parent) if store.is_internal_pm_dir(root) else str(root)
            click.echo(f"Cloning locally from {local_source}...")
            git_ops.clone(local_source, tmp_path, branch=base_branch)
            # Configure push URLs: push to both the local repo (keeps
            # it up to date, like the container push proxy does) and
            # the remote (GitHub).  Fetch stays local for speed.
            # PR branches aren't checked out in the main repo, so
            # pushing to the local path succeeds without issues.
            git_ops.run_git("remote", "set-url", "--push",
                            "origin", local_source, cwd=tmp_path)
            git_ops.run_git("remote", "set-url", "--add", "--push",
                            "origin", repo_url, cwd=tmp_path)

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

    is_git = work_path.exists() and git_ops.is_git_repo(work_path)
    if is_git and _workdir_is_dirty(work_path):
        click.echo("Workdir has uncommitted changes — skipping git pull/checkout.")
    else:
        if is_git:
            click.echo(f"Updating {work_path}...")
            git_ops.pull_rebase(work_path)

        click.echo(f"Checking out branch {branch}...")
        git_ops.checkout_branch(work_path, branch, create=True)

    # For GitHub backend: push branch and create draft PR if not already set
    backend_name = data["project"].get("backend", "vanilla")
    gh_pr_info = None
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
            gh_pr_info = gh_ops.create_draft_pr(str(work_path), title, base_branch, desc)
            if gh_pr_info:
                click.echo(f"Draft PR created: {gh_pr_info['url']}")
            else:
                click.echo("Warning: Failed to create draft PR.", err=True)

    # Update state under lock — only advance from pending; don't regress in_review/merged
    machine = platform.node()
    work_path_str = str(work_path)

    def apply(data):
        pr = store.get_pr(data, pr_id)
        if not pr:
            return
        if pr.get("status") == "pending":
            pr["status"] = "in_progress"
        _record_status_timestamp(pr, "in_progress")
        pr["agent_machine"] = machine
        pr["workdir"] = work_path_str
        if gh_pr_info:
            pr["gh_pr"] = gh_pr_info["url"]
            pr["gh_pr_number"] = gh_pr_info["number"]
        data["project"]["active_pr"] = pr_id

    data = store.locked_update(root, apply)
    # Reload pr_entry from updated data (now contains gh_pr_number)
    pr_entry = store.get_pr(data, pr_id) or pr_entry
    trigger_tui_refresh()

    click.echo(f"\nPR {_pr_display_id(pr_entry)} is now in_progress on {machine}")
    click.echo(f"Work directory: {work_path}")

    prompt = prompt_gen.generate_prompt(data, pr_id, session_name=pm_session)

    # Resolve model/provider for this implementation session
    from pm_core.model_config import resolve_model_and_provider, get_pr_model_override
    _resolution = resolve_model_and_provider(
        "impl",
        pr_model=get_pr_model_override(pr_entry),
        project_data=data,
    )
    resolved_model = _resolution.model
    resolved_provider = _resolution.provider

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
            # When running in a container, Claude's cwd is /workspace —
            # transcript symlinks must target where Claude actually writes
            # (see pr_review for the same pattern).
            from pm_core.container import (
                is_container_mode_enabled as _is_container_enabled,
                _CONTAINER_WORKDIR,
            )
            if _is_container_enabled():
                _claude_cwd = _CONTAINER_WORKDIR
                _claude_write_dir = str(work_path)
            else:
                _claude_cwd = str(work_path)
                _claude_write_dir = None
            cmd = build_claude_shell_cmd(prompt=prompt,
                                         transcript=transcript,
                                         cwd=_claude_cwd,
                                         write_dir=_claude_write_dir,
                                         model=resolved_model,
                                         provider=resolved_provider,
                                         effort=_resolution.effort)
            # Optionally wrap in a container for isolation
            from pm_core.container import wrap_claude_cmd, ContainerError
            _stag = pm_session.removeprefix("pm-") if pm_session else None
            try:
                cmd, _cname = wrap_claude_cmd(cmd, str(work_path), label=f"impl-{pr_id}",
                                              allowed_push_branch=branch,
                                              session_tag=_stag, pr_id=pr_id)
            except ContainerError as e:
                click.echo(str(e), err=True)
                raise SystemExit(1)
            try:
                if use_companion:
                    claude_pane = tmux_mod.new_window_get_pane(
                        pm_session, window_name, cmd, str(work_path),
                        switch=not background,
                    )
                    if claude_pane:
                        win = tmux_mod.find_window_by_name(pm_session, window_name)
                        if win:
                            _add_companion_pane(pm_session, win, str(work_path), "impl")
                else:
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
    launch_claude(prompt, cwd=str(work_path), session_key=session_key, pm_root=root, resume=not fresh,
                  provider=resolved_provider, model=resolved_model, effort=_resolution.effort)


def _add_companion_pane(pm_session: str, window_info: dict, workdir: str,
                        role_prefix: str) -> None:
    """Add a companion shell pane to an existing tmux window.

    Splits the first pane horizontally with a shell cd'ed into *workdir*.
    Registers both panes in the pane registry and rebalances the layout.

    If the window already has 2+ panes (companion already present), this
    is a no-op.
    """
    win_id = window_info["id"]
    win_index = window_info["index"]

    # Check if companion already exists (2+ panes = already has one)
    panes = tmux_mod.get_pane_indices(pm_session, win_index)
    if len(panes) >= 2:
        click.echo("Window already has a companion pane.")
        return

    if not panes:
        click.echo("Could not find panes in window.")
        return

    claude_pane = panes[0][0]

    # Split horizontally with an interactive shell in the workdir
    shell = os.environ.get("SHELL", "/bin/bash")
    companion_cmd = f"cd {shell_quote(workdir)} && exec {shell}"
    companion_pane = tmux_mod.split_pane_at(claude_pane, "h", companion_cmd,
                                             background=True)

    # Register panes for layout management
    tmux_mod.set_shared_window_size(pm_session, win_id)
    panes = [(claude_pane, f"{role_prefix}-claude", "claude")]
    if companion_pane:
        panes.append((companion_pane, f"{role_prefix}-companion", "companion-shell"))
    pane_layout.register_and_rebalance(pm_session, win_id, panes)
    click.echo("Added companion pane.")


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
    if not workdir or not Path(workdir).exists():
        root = state_root()
        workdir = _ensure_workdir(data, pr_entry, root)
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

    window_name = f"review-{display_id}"

    # Fast path: if review window already exists and we don't need fresh,
    # just switch to it — skip expensive prompt generation and container setup.
    existing = tmux_mod.find_window_by_name(pm_session, window_name)
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

    title = pr_entry.get("title", "")
    base_branch = data.get("project", {}).get("base_branch", "master")

    # Resolve model/provider for review session
    from pm_core.model_config import resolve_model_and_provider, get_pr_model_override
    _resolution = resolve_model_and_provider(
        "review",
        pr_model=get_pr_model_override(pr_entry),
        project_data=data,
    )

    # Generate review prompt and build Claude command
    review_prompt = prompt_gen.generate_review_prompt(data, pr_id, session_name=pm_session,
                                                      review_loop=review_loop,
                                                      review_iteration=review_iteration,
                                                      review_loop_id=review_loop_id)
    # When the review runs in a container, Claude's cwd is /workspace —
    # the transcript symlink must target ~/.claude/projects/-workspace/
    # where Claude actually writes, not the host workdir's mangled dir.
    # Host path is passed as write_dir so the prompt file lands on the
    # mounted volume.  Matches the QA pattern in qa_loop.py.
    from pm_core.container import is_container_mode_enabled as _is_container_enabled, _CONTAINER_WORKDIR
    if _is_container_enabled():
        _claude_cwd = _CONTAINER_WORKDIR
        _claude_write_dir = workdir
    else:
        _claude_cwd = workdir
        _claude_write_dir = None
    claude_cmd = build_claude_shell_cmd(prompt=review_prompt,
                                         transcript=transcript,
                                         cwd=_claude_cwd,
                                         write_dir=_claude_write_dir,
                                         model=_resolution.model,
                                         provider=_resolution.provider,
                                         effort=_resolution.effort)
    # Optionally wrap in a container for isolation.
    # Always remove any existing container for this review before creating a
    # new one.  The previous session's bash EXIT trap runs "docker rm -f"
    # asynchronously after its pane is killed; if wrap_claude_cmd runs while
    # that rm is still in flight it will "reuse" the dying container, then
    # the old trap's rm completes and kills the new session mid-init.
    # Removing it here (synchronously) closes that race regardless of whether
    # an existing tmux window was found above.
    branch = pr_entry.get("branch", "")
    from pm_core.container import wrap_claude_cmd, ContainerError, remove_container, is_container_mode_enabled, _make_container_name
    if is_container_mode_enabled():
        remove_container(_make_container_name(f"review-{pr_id}"))
    try:
        claude_cmd, _cname = wrap_claude_cmd(claude_cmd, workdir, label=f"review-{pr_id}",
                                              allowed_push_branch=branch)
    except ContainerError as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)

    # In review loop mode or background mode, create the window without
    # switching focus.  For review loops the explicit per-session switching
    # below handles moving exactly the sessions that were watching the old
    # window.  Background mode is used by auto-start to avoid stealing focus.
    switch = not review_loop and not background

    try:
        # Build the diff pane command first.  We use git --no-pager
        # and pipe through less ourselves so that quitting the pager
        # doesn't kill the pane (git's built-in pager can cause SIGPIPE
        # exit codes that break && chains).
        shell = os.environ.get("SHELL", "/bin/bash")
        header = f"=== Review: {display_id} — {title} ==="
        # Use backend-appropriate diff base:
        #   local:   merge-base between base_branch and HEAD (no remote)
        #   vanilla/github: origin/{base_branch}...HEAD
        backend_name = data.get("project", {}).get("backend", "vanilla")
        if backend_name == "local":
            diff_ref = base_branch
        else:
            diff_ref = f"origin/{base_branch}"
        # User-controlled values (workdir, title via header) MUST be
        # shell_quote'd. An apostrophe in a PR title would otherwise
        # break the surrounding single-quote and turn the rest of the
        # title into shell tokens, killing the pane shell before tmux
        # can register the new window.
        diff_cmd = (
            f"cd {shell_quote(workdir)}"
            f" && {{ echo {shell_quote(header)}"
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

        # Create the window with the diff pane first, then split to add
        # the claude pane.  This ensures the window is already at its
        # final 2-pane width before docker exec launches — so the
        # container PTY inherits the correct column count and Claude
        # Code renders at the right width.
        diff_pane = tmux_mod.new_window_get_pane(
            pm_session, window_name, diff_cmd, workdir,
            switch=switch,
        )
        if not diff_pane:
            _log.warning(
                "Review window: new_window_get_pane returned None for "
                "window=%s session=%s. The diff pane shell likely exited "
                "before tmux registered the window — check that "
                "user-controlled values in diff_cmd are shell_quote'd "
                "(e.g. PR title containing an apostrophe).",
                window_name, pm_session,
            )
            click.echo(f"Review window: failed to create tmux window '{window_name}'.")
            return

        claude_pane = tmux_mod.split_pane_at(diff_pane, "h", claude_cmd, background=True)

        # Register review panes under the review window (multi-window safe).
        # Derive window ID from the pane we just created rather than
        # searching by name, which is more robust.
        wid_result = subprocess.run(
            tmux_mod._tmux_cmd("display", "-t", diff_pane, "-p", "#{window_id}"),
            capture_output=True, text=True,
        )
        review_win_id = wid_result.stdout.strip()
        if review_win_id:
            tmux_mod.set_shared_window_size(pm_session, review_win_id)
            panes = [(claude_pane, "review-claude", claude_cmd)]
            if diff_pane:
                panes.append((diff_pane, "review-diff", "diff-shell"))
            # Register and reset user_modified, but defer rebalance until
            # after session switches so get_reliable_window_size() sees the
            # correct dimensions.
            from pm_core import pane_registry as _reg
            for pane_id, role, cmd in panes:
                _reg.register_pane(pm_session, review_win_id, pane_id, role, cmd)

            def _reset_user_modified(raw):
                data = _reg._prepare_registry_data(raw, pm_session)
                wd = _reg.get_window_data(data, review_win_id)
                wd["user_modified"] = False
                return data

            _reg.locked_read_modify_write(
                _reg.registry_path(pm_session), _reset_user_modified)

        # Switch ALL grouped sessions that were watching the old review
        # window to the new one.
        if sessions_on_review:
            tmux_mod.switch_sessions_to_window(
                sessions_on_review, pm_session, window_name)

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

    # For GitHub backend: upgrade draft PR to ready for review (before lock)
    backend_name = data["project"].get("backend", "vanilla")
    gh_pr_number = pr_entry.get("gh_pr_number")
    workdir = pr_entry.get("workdir")
    if workdir and not Path(workdir).exists():
        workdir = _ensure_workdir(data, pr_entry, root)

    if backend_name == "github" and gh_pr_number and workdir:
        from pm_core import gh_ops
        click.echo(f"Marking PR #{gh_pr_number} as ready for review...")
        if gh_ops.mark_pr_ready(workdir, gh_pr_number):
            click.echo("Draft PR upgraded to ready for review.")
        else:
            click.echo("Warning: Failed to upgrade draft PR. It may already be ready or was closed.", err=True)

    def apply(data):
        pr = store.get_pr(data, pr_id)
        if not pr:
            return
        pr["status"] = "in_review"
        _record_status_timestamp(pr, "in_review")

    store.locked_update(root, apply)
    click.echo(f"PR {_pr_display_id(pr_entry)} marked as in_review.")
    trigger_tui_refresh()
    _launch_review_window(data, pr_entry, fresh=fresh, background=background,
                          review_loop=review_loop,
                          review_iteration=review_iteration,
                          review_loop_id=review_loop_id,
                          transcript=transcript)


def _finalize_merge(root, pr_entry: dict, pr_id: str,
                    transcript: str | None = None) -> None:
    """Mark PR as merged, kill tmux windows, and show newly ready PRs."""
    def apply(data):
        pr = store.get_pr(data, pr_id)
        if not pr:
            return
        pr["status"] = "merged"
        _record_status_timestamp(pr, "merged")

    data = store.locked_update(root, apply)
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
                         transcript: str | None = None,
                         cwd: str | None = None,
                         companion: bool = False,
                         pull_from_workdir: str | None = None,
                         pull_from_origin: bool = False) -> None:
    """Launch a tmux window with Claude to resolve a merge conflict.

    Args:
        cwd: Directory to run the merge resolution in.  Defaults to the
             PR's workdir when *None*.
        companion: If True (or the ``companion-pane`` global setting is
                   enabled), a companion shell pane is opened alongside
                   the Claude pane.
        pull_from_workdir: When set, this is a pull-from-workdir failure
             (local backend).  The value is the workdir path containing
             the merged branch.
        pull_from_origin: When True, this is a pull-from-origin failure
             (vanilla/github backend).
    """
    if not tmux_mod.has_tmux() or not tmux_mod.in_tmux():
        click.echo("Merge window requires tmux.")
        return

    pm_session = _get_pm_session()
    if not pm_session or not tmux_mod.session_exists(pm_session):
        click.echo(f"Merge window: tmux session '{pm_session}' not found.")
        return

    workdir = cwd or pr_entry.get("workdir")
    if not workdir:
        click.echo(f"Merge window: no workdir for {pr_entry['id']}.")
        return
    if not Path(workdir).exists():
        root = state_root()
        workdir = _ensure_workdir(data, pr_entry, root)
        if not workdir:
            click.echo(f"Merge window: no workdir for {pr_entry['id']}.")
            return

    from pm_core.paths import get_global_setting
    use_companion = companion or get_global_setting("companion-pane")

    pr_id = pr_entry["id"]
    display_id = _pr_display_id(pr_entry)

    # Resolve model/provider for merge session
    from pm_core.model_config import resolve_model_and_provider, get_pr_model_override
    _resolution = resolve_model_and_provider(
        "merge",
        pr_model=get_pr_model_override(pr_entry),
        project_data=data,
    )

    merge_prompt = prompt_gen.generate_merge_prompt(
        data, pr_id, error_output, session_name=pm_session,
        pull_from_workdir=pull_from_workdir,
        pull_from_origin=pull_from_origin,
    )
    claude_cmd = build_claude_shell_cmd(prompt=merge_prompt,
                                         transcript=transcript, cwd=workdir,
                                         model=_resolution.model,
                                         provider=_resolution.provider,
                                         effort=_resolution.effort)
    # Merge runs on the host — it needs to push to master and modify the
    # main repo, which the branch-scoped push proxy would block.
    window_name = f"merge-{display_id}"

    # No-op if a merge window is already running for this PR
    existing = tmux_mod.find_window_by_name(pm_session, window_name)
    if existing:
        if background:
            click.echo(f"Merge window '{window_name}' already exists (background mode, no-op)")
            return
        tmux_mod.select_window(pm_session, existing["id"])
        click.echo(f"Switched to existing merge window '{window_name}'")
        return

    try:
        if use_companion:
            claude_pane = tmux_mod.new_window_get_pane(
                pm_session, window_name, claude_cmd, workdir,
                switch=not background,
            )
            if claude_pane:
                win = tmux_mod.find_window_by_name(pm_session, window_name)
                if win:
                    _add_companion_pane(pm_session, win, workdir, "merge")
        else:
            tmux_mod.new_window(
                pm_session, window_name, claude_cmd, workdir,
                switch=not background,
            )
        click.echo(f"Opened merge resolution window '{window_name}'")
    except Exception as e:
        _log.warning("Failed to launch merge window: %s", e)
        click.echo(f"Merge window error: {e}")


def _pull_after_merge(data: dict, pr_entry: dict, repo_dir: str,
                      base_branch: str, resolve_window: bool,
                      background: bool,
                      transcript: str | None,
                      companion: bool = False) -> bool:
    """Pull latest base branch into the main repo after a merge.

    *repo_dir* should be the main repository directory (on the base branch),
    not the PR's workdir (which is on the PR branch).

    Only pulls if *repo_dir* already has the base branch checked out.
    If on a different branch (implying local work in progress), the pull
    is skipped to avoid disrupting the user's working state.

    Dirty files are tolerated — git merge succeeds when they don't overlap
    with incoming changes.  If they do overlap, the dirty files are stashed,
    the merge is retried, and the stash is popped afterward.

    Returns True if the pull completed (or was skipped), False if a merge
    window was launched (caller should skip ``_finalize_merge``).
    """
    # Detect current branch — skip pull if not already on base branch
    head_result = git_ops.run_git("rev-parse", "--abbrev-ref", "HEAD",
                                  cwd=repo_dir, check=False)
    current_branch = head_result.stdout.strip() if head_result.returncode == 0 else ""
    if current_branch != base_branch:
        click.echo(f"Repo is on '{current_branch}', skipping pull of {base_branch}.")
        return True

    repo_path = Path(repo_dir)
    pr_display = _pr_display_id(pr_entry)

    # Fetch + merge (not pull --rebase, which requires a fully clean tree)
    git_ops.run_git("fetch", "origin", cwd=repo_dir, check=False)
    merge_result = git_ops.run_git("merge", "--ff-only",
                                   f"origin/{base_branch}",
                                   cwd=repo_dir, check=False)

    # If merge failed due to dirty-file overlap, stash and retry
    stash_info = None
    if merge_result.returncode != 0 and _is_dirty_overlap_error(merge_result):
        stash_info = _stash_for_merge(repo_path, pr_display)
        if stash_info:
            merge_result = git_ops.run_git("merge", "--ff-only",
                                           f"origin/{base_branch}",
                                           cwd=repo_dir, check=False)

    if merge_result.returncode != 0:
        if stash_info:
            _unstash_after_merge(repo_path, stash_info)
        error_detail = (merge_result.stdout.strip() + "\n"
                        + merge_result.stderr.strip()).strip()
        error_msg = (f"Pull failed in {repo_dir}:\n{error_detail}")
        click.echo(error_msg, err=True)
        if resolve_window:
            _launch_merge_window(data, pr_entry, error_msg,
                                 background=background, transcript=transcript,
                                 cwd=repo_dir, companion=companion,
                                 pull_from_origin=True)
            return False
        click.echo("Resolve conflicts manually, then re-run 'pm pr merge' to finalize.", err=True)
        return False

    if stash_info:
        _unstash_after_merge(repo_path, stash_info)
    click.echo(f"Pulled latest {base_branch}.")
    return True


def _pull_from_workdir(data: dict, pr_entry: dict, repo_dir: str,
                       workdir: str, base_branch: str,
                       resolve_window: bool, background: bool,
                       transcript: str | None,
                       companion: bool = False) -> bool:
    """Pull merged base branch from a workdir into the main repo.

    For local backend where origin is a non-bare repo with the base branch
    checked out, ``git push`` fails.  Instead we fetch from the workdir and
    fast-forward the base branch in the main repo.

    Returns True if successful (caller should finalize), False if a merge
    window was launched or the update failed.
    """
    repo_path = Path(repo_dir)

    # Check what branch is checked out in the repo
    head_result = git_ops.run_git("rev-parse", "--abbrev-ref", "HEAD",
                                  cwd=repo_dir, check=False)
    current = head_result.stdout.strip() if head_result.returncode == 0 else ""

    if current != base_branch:
        # Not on base branch — update just the ref (no working-tree changes)
        click.echo(f"Repo is on '{current}', updating {base_branch} ref...")
        fetch_r = git_ops.run_git(
            "fetch", workdir, f"{base_branch}:{base_branch}",
            cwd=repo_dir, check=False,
        )
        if fetch_r.returncode == 0:
            click.echo(f"Updated {base_branch} in repo.")
            return True
        error_msg = (f"Could not update {base_branch} ref: "
                     f"{fetch_r.stderr.strip()}")
        click.echo(error_msg, err=True)
        if resolve_window:
            _launch_merge_window(data, pr_entry, error_msg,
                                 background=background, transcript=transcript,
                                 cwd=repo_dir, companion=companion,
                                 pull_from_workdir=workdir)
            return False
        click.echo("Pull manually when ready, then re-run 'pm pr merge'.", err=True)
        return False

    # On base branch — need to update the working tree too.
    # Dirty files are tolerated; git merge --ff-only succeeds when they
    # don't overlap with the incoming changes.
    pr_display = _pr_display_id(pr_entry)

    fetch_r = git_ops.run_git("fetch", workdir, base_branch,
                              cwd=repo_dir, check=False)
    if fetch_r.returncode != 0:
        error_msg = f"Fetch from workdir failed: {fetch_r.stderr.strip()}"
        click.echo(error_msg, err=True)
        if resolve_window:
            _launch_merge_window(data, pr_entry, error_msg,
                                 background=background, transcript=transcript,
                                 cwd=repo_dir, companion=companion,
                                 pull_from_workdir=workdir)
            return False
        click.echo("Pull manually when ready, then re-run 'pm pr merge'.", err=True)
        return False

    merge_r = git_ops.run_git("merge", "--ff-only", "FETCH_HEAD",
                              cwd=repo_dir, check=False)

    # If merge failed due to dirty-file overlap, stash and retry
    stash_info = None
    if merge_r.returncode != 0 and _is_dirty_overlap_error(merge_r):
        stash_info = _stash_for_merge(repo_path, pr_display)
        if stash_info:
            merge_r = git_ops.run_git("merge", "--ff-only", "FETCH_HEAD",
                                      cwd=repo_dir, check=False)

    if merge_r.returncode != 0:
        if stash_info:
            _unstash_after_merge(repo_path, stash_info)
        error_detail = (merge_r.stdout.strip() + "\n"
                        + merge_r.stderr.strip()).strip()
        error_msg = f"Fast-forward of {base_branch} failed:\n{error_detail}"
        click.echo(error_msg, err=True)
        if resolve_window:
            _launch_merge_window(data, pr_entry, error_msg,
                                 background=background, transcript=transcript,
                                 cwd=repo_dir, companion=companion,
                                 pull_from_workdir=workdir)
            return False
        click.echo("Pull manually when ready, then re-run 'pm pr merge'.", err=True)
        return False

    if stash_info:
        _unstash_after_merge(repo_path, stash_info)
    click.echo(f"Updated {base_branch} in repo.")

    return True


@pr.command("qa")
@click.argument("args", nargs=-1)
@click.option("--session", "session_name", default=None,
              help="tmux session to target (defaults to PM_SESSION or "
                   "current pm session)")
def pr_qa(args: tuple[str, ...], session_name: str | None):
    """Manage the QA loop for a PR.

    Forms:

    \b
      pm pr qa <pr_id>          — focus existing QA window or start a
                                  one-shot QA run.
      pm pr qa fresh <pr_id>    — kill stale scenario windows and
                                  restart QA fresh.
      pm pr qa loop <pr_id>     — start a self-driving QA loop.

    The QA coordinator runs in a detached daemon (one per PR-action)
    so the loop survives this CLI invocation.  Verdict completion
    policy (NEEDS_WORK → review, PASS → merge) stays TUI-side and is
    driven from runtime_state once the daemon records its terminal
    state.
    """
    mode = "default"
    rest = list(args)
    if rest and rest[0] in ("fresh", "loop"):
        mode = rest.pop(0)
    pr_id = rest[0] if rest else None

    _run_qa(mode, pr_id, session_name)


def _run_qa(mode: str, pr_id: str | None, session_name: str | None) -> None:
    from pm_core.cli._session_target import resolve_target_session
    from pm_core import loop_daemon
    from pm_core import runtime_state as _rs
    from pm_core.qa_loop import (
        _compute_qa_window_name,
        _cleanup_stale_scenario_windows,
    )

    root = state_root()
    data = store.load(root)

    if pr_id is None:
        pr_id = _infer_pr_id(data, status_filter=("in_review", "qa"))
        if pr_id is None:
            click.echo("No PR specified and no eligible PR found.", err=True)
            raise SystemExit(1)
        click.echo(f"Auto-selected {pr_id}")

    pr_entry = _require_pr(data, pr_id)
    pr_id = pr_entry["id"]

    if pr_entry.get("status") not in ("in_progress", "in_review", "qa"):
        click.echo(
            f"PR {pr_id} has status '{pr_entry.get('status')}' — "
            f"QA requires in_progress, in_review, or qa.", err=True)
        raise SystemExit(1)

    target_session = resolve_target_session(session_name)
    loop_daemon.sweep_stale_pidfiles(target_session)

    # Default mode: if the QA window already exists, just focus it.
    if mode == "default":
        window_name = _compute_qa_window_name(pr_entry)
        win = tmux_mod.find_window_by_name(target_session, window_name)
        if win:
            suppress = _rs.consume_suppress_switch(pr_id, "qa")
            if not suppress:
                tmux_mod.select_window(target_session, window_name)
                click.echo(f"Focused QA window for {pr_id}")
            else:
                click.echo(
                    f"QA window for {pr_id} ready (focus suppressed)")
            return
        # No window yet — fall through to launch the daemon.

    # Refuse if an existing daemon is already coordinating QA for this PR.
    if loop_daemon.is_loop_alive(target_session, pr_id, "qa"):
        if mode == "fresh":
            # Fresh reset: stop the running daemon first.
            loop_daemon.request_stop(target_session, pr_id, "qa")
        else:
            click.echo(
                f"QA daemon already running for {pr_id} — use "
                f"'pm pr qa fresh {pr_id}' to restart.", err=True)
            raise SystemExit(1)

    if mode == "fresh":
        _cleanup_stale_scenario_windows(target_session, pr_entry,
                                         include_main=True)

    # Transition status to "qa" if currently in_review (mirrors qa_loop_ui).
    if pr_entry.get("status") == "in_review":
        def _set_qa(d):
            p = store.get_pr(d, pr_id)
            if p and p.get("status") == "in_review":
                p["status"] = "qa"
        try:
            store.locked_update(root, _set_qa)
        except (store.StoreLockTimeout, store.ProjectYamlParseError) as e:
            click.echo(f"Error transitioning to qa: {e}", err=True)
            raise SystemExit(1)
        # Reload after status change.
        data = store.load(root)
        pr_entry = _require_pr(data, pr_id)

    import secrets as _secrets
    loop_id = _secrets.token_hex(4)

    extras: dict = {"loop_id": loop_id, "verdict": None}
    if mode == "loop":
        from pm_core.tui.qa_loop_ui import _get_qa_pass_count
        extras["self_driving"] = {
            "pass_count": 0,
            "required_passes": _get_qa_pass_count(),
        }
    _rs.set_action_state(pr_id, "qa", "launching", **extras)

    # Capture the data the daemon's loop_main needs as plain values —
    # pr_entry is reloaded inside the daemon to avoid sharing dict
    # references across fork.
    captured_pr_id = pr_id
    captured_root = root
    captured_session = target_session

    def loop_main():
        # Propagate the resolved target session into the daemon — the
        # double-forked child may not share $TMUX with the original
        # caller, so loop_shared.get_pm_session() needs PM_SESSION to
        # find the right tmux session.
        os.environ["PM_SESSION"] = captured_session

        from pm_core import store as _store
        from pm_core import runtime_state as __rs
        from pm_core.qa_loop import QALoopState as _QAState
        from pm_core.qa_loop import run_qa_sync as _run

        _data = _store.load(captured_root)
        _pr = _store.get_pr(_data, captured_pr_id) or {}
        state = _QAState(pr_id=captured_pr_id, loop_id=loop_id)

        __rs.set_action_state(captured_pr_id, "qa", "running",
                               loop_id=loop_id)

        def on_update(s):
            try:
                __rs.set_action_state(
                    captured_pr_id, "qa", "running",
                    loop_id=loop_id,
                    verdict=s.latest_verdict or None,
                )
            except Exception:
                pass

        result = _run(state, captured_root, _pr, on_update)
        # Final verdict is recorded by the daemon's finally block, but
        # emit it explicitly so the verdict is in runtime_state before
        # the wrapper transitions to "done".
        __rs.set_action_state(
            captured_pr_id, "qa", "running",
            loop_id=loop_id,
            verdict=result.latest_verdict or "UNKNOWN",
        )

    try:
        pid = loop_daemon.spawn(
            session=target_session,
            pr_id=pr_id,
            action="qa",
            loop_id=loop_id,
            loop_main=loop_main,
        )
    except loop_daemon.LoopAlreadyRunning as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)

    if pid <= 0:
        click.echo(
            f"Failed to spawn QA daemon for {pr_id} (no PID returned).",
            err=True)
        raise SystemExit(1)
    click.echo(f"Started QA daemon for {pr_id} (pid={pid}, mode={mode})")


@pr.group("review-loop")
def review_loop_group():
    """Manage the review-loop coordinator for a PR."""


@review_loop_group.command("start")
@click.argument("pr_id", default=None, required=False)
@click.option("--session", "session_name", default=None,
              help="tmux session to target (defaults to PM_SESSION or "
                   "current pm session)")
def review_loop_start(pr_id: str | None, session_name: str | None):
    """Start a fresh review loop for a PR.

    Spawns a detached daemon that runs the review-loop coordinator
    (iterating ``pm pr review --review-loop`` until PASS).  Verdict
    completion policy stays TUI-side and reads from runtime_state.
    """
    from pm_core.cli._session_target import resolve_target_session
    from pm_core import loop_daemon
    from pm_core import runtime_state as _rs

    root = state_root()
    data = store.load(root)

    if pr_id is None:
        pr_id = _infer_pr_id(data, status_filter=("in_review",))
        if pr_id is None:
            click.echo("No PR specified and no in_review PR found.",
                       err=True)
            raise SystemExit(1)
        click.echo(f"Auto-selected {pr_id}")

    pr_entry = _require_pr(data, pr_id)
    pr_id = pr_entry["id"]

    if pr_entry.get("status") not in ("in_progress", "in_review"):
        click.echo(
            f"PR {pr_id} has status '{pr_entry.get('status')}' — "
            f"review-loop requires in_progress or in_review.", err=True)
        raise SystemExit(1)

    target_session = resolve_target_session(session_name)
    loop_daemon.sweep_stale_pidfiles(target_session)

    # Supersede any running review-loop daemon for this PR — matches
    # zz d's "always start a fresh loop" semantics in review_loop_ui.
    if loop_daemon.is_loop_alive(target_session, pr_id, "review-loop"):
        # Kill the existing review window so the running iteration's
        # verdict-poll bails immediately, mirroring start_or_stop_loop.
        try:
            display_id = _pr_display_id(pr_entry)
            tmux_mod.kill_window(target_session, f"review-{display_id}")
        except Exception:
            pass
        loop_daemon.request_stop(target_session, pr_id, "review-loop")

    import secrets as _secrets
    loop_id = _secrets.token_hex(4)

    tdir = loop_daemon.transcript_dir(root)

    _rs.set_action_state(pr_id, "review-loop", "launching",
                         loop_id=loop_id, iteration=0, verdict=None)

    captured_pr_id = pr_id
    captured_root = root
    captured_tdir = str(tdir)
    captured_session = target_session

    def loop_main():
        # Propagate the resolved target session into the daemon — the
        # double-forked child may not share $TMUX with the original
        # caller, so loop_shared.get_pm_session() needs PM_SESSION to
        # find the right tmux session.
        os.environ["PM_SESSION"] = captured_session

        from pm_core import store as _store
        from pm_core import runtime_state as __rs
        from pm_core.review_loop import (
            ReviewLoopState as _RLState,
            run_review_loop_sync as _run,
        )

        _data = _store.load(captured_root)
        _pr = _store.get_pr(_data, captured_pr_id) or {}
        state = _RLState(pr_id=captured_pr_id)
        state.loop_id = loop_id

        def on_iteration(s):
            try:
                __rs.set_action_state(
                    captured_pr_id, "review-loop", "running",
                    iteration=s.iteration,
                    loop_id=loop_id,
                    verdict=s.latest_verdict or None,
                )
            except Exception:
                pass

        __rs.set_action_state(captured_pr_id, "review-loop", "running",
                                iteration=0, loop_id=loop_id)
        result = _run(state, str(captured_root), _pr, captured_tdir,
                      on_iteration=on_iteration)
        __rs.set_action_state(
            captured_pr_id, "review-loop", "running",
            iteration=result.iteration,
            loop_id=loop_id,
            verdict=result.latest_verdict or "UNKNOWN",
        )

    try:
        pid = loop_daemon.spawn(
            session=target_session,
            pr_id=pr_id,
            action="review-loop",
            loop_id=loop_id,
            loop_main=loop_main,
        )
    except loop_daemon.LoopAlreadyRunning as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)

    if pid <= 0:
        click.echo(
            f"Failed to spawn review-loop daemon for {pr_id} "
            f"(no PID returned).", err=True)
        raise SystemExit(1)
    click.echo(f"Started review-loop daemon for {pr_id} (pid={pid})")


def _resolve_window_default() -> bool:
    """Whether ``pr merge`` should default to launching a resolve window.

    True when running inside the pm tmux session (PM_IN_TMUX_SESSION=1),
    so picker / shell-pane / typed-in-command-bar invocations all match
    the TUI command-bar behavior. False outside tmux.
    """
    return bool(os.environ.get("PM_IN_TMUX_SESSION"))


@pr.command("merge")
@click.argument("pr_id", default=None, required=False)
@click.option("--resolve-window/--no-resolve-window", "resolve_window",
              default=None, hidden=True,
              help="On merge conflict, launch a Claude resolution window instead of exiting")
@click.option("--background", is_flag=True, default=False, hidden=True,
              help="Create merge window without switching focus (used by auto-start)")
@click.option("--transcript", default=None, hidden=True,
              help="Path to save Claude transcript symlink (used by auto-start)")
@click.option("--companion", is_flag=True, default=False,
              help="Open a companion shell pane alongside the merge resolution window")
@click.option("--propagation-only", is_flag=True, default=False, hidden=True,
              help="Skip workdir merge, go straight to pull into repo dir (step 2)")
def pr_merge(pr_id: str | None, resolve_window: bool | None, background: bool,
             transcript: str | None, companion: bool, propagation_only: bool):
    """Merge a PR's branch into the base branch.

    For local/vanilla backends, performs a local git merge.
    For GitHub backend, merges via gh CLI if available, otherwise
    directs the user to merge on GitHub manually.
    If PR_ID is omitted, infers from cwd or auto-selects.
    """
    if resolve_window is None:
        resolve_window = _resolve_window_default()
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
        if workdir and not Path(workdir).exists():
            workdir = _ensure_workdir(data, pr_entry, root)
        if gh_pr_number and workdir and Path(workdir).exists() and shutil.which("gh"):
            gh_merged = False

            if propagation_only:
                # Step 2: skip gh pr merge, go straight to pull into repo dir
                click.echo(f"Propagation only: skipping gh pr merge for #{gh_pr_number}")
                gh_merged = True
            else:
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
                        stderr = merge_result.stderr.strip()
                        click.echo(f"gh pr merge failed: {stderr}", err=True)
                        if resolve_window:
                            _launch_merge_window(
                                data, pr_entry, stderr,
                                background=background,
                                transcript=transcript,
                                companion=companion,
                            )
                            return
                        click.echo("Falling back to manual instructions.", err=True)

            if gh_merged:
                repo_dir = str(_resolve_repo_dir(root, data))
                pull_ok = _pull_after_merge(
                    data, pr_entry, repo_dir, base_branch,
                    resolve_window=resolve_window,
                    background=background,
                    transcript=transcript,
                    companion=companion,
                )
                if pull_ok:
                    _finalize_merge(root, pr_entry, pr_id, transcript=transcript)
                    # Restart TUI when managing the project_manager repo itself,
                    # so it picks up the latest pm code from the pull.
                    repo = data.get("project", {}).get("repo", "")
                    if "project_manager" in repo or "project-manager" in repo:
                        trigger_tui_restart()
                # If not pull_ok and resolve_window, a merge window was launched.
                # The idle tracker will re-attempt and finalize after resolution.
                return

        # Fallback: direct user to merge manually. Exits non-zero so the
        # popup picker / TUI surfaces the message instead of closing
        # silently — the user must take a manual action to proceed.
        gh_pr = pr_entry.get("gh_pr")
        if gh_pr:
            click.echo(f"GitHub PR: {gh_pr}")
            click.echo("Merge via GitHub, then run 'pm pr sync' to detect it.", err=True)
        else:
            click.echo("No GitHub PR URL found. Merge manually on GitHub, then run 'pm pr sync'.", err=True)
        raise SystemExit(1)

    # For local/vanilla: merge in the PR's workdir (branch always exists there)
    workdir = pr_entry.get("workdir")
    if not workdir or not Path(workdir).exists():
        workdir = _ensure_workdir(data, pr_entry, root)
        if not workdir:
            click.echo(f"PR {pr_id} workdir not found. Cannot merge without the branch.", err=True)
            raise SystemExit(1)

    work_path = Path(workdir)

    if propagation_only:
        # Step 2: skip workdir merge, go straight to propagation
        click.echo("Propagation only: skipping workdir merge.")
    else:
        # Fetch latest from origin (important for vanilla backend where others may push)
        if backend_name == "vanilla":
            click.echo("Fetching latest from origin...")
            git_ops.run_git("fetch", "origin", cwd=workdir, check=False)

        # Capture the branch tip before merge for post-merge verification
        tip_result = git_ops.run_git("rev-parse", branch, cwd=workdir, check=False)
        branch_tip = tip_result.stdout.strip() if tip_result.returncode == 0 else None

        click.echo(f"Merging {branch} into {base_branch}...")

        # Checkout base branch — stash dirty files if they overlap
        stash_info = None
        result = git_ops.run_git("checkout", base_branch, cwd=workdir, check=False)
        if result.returncode != 0 and _is_dirty_overlap_error(result):
            # Workdir is a pm-managed clone, no TUI overlay needed
            stash_info = _stash_for_merge(work_path, lock_tui=False)
            if stash_info:
                result = git_ops.run_git("checkout", base_branch, cwd=workdir, check=False)
        if result.returncode != 0:
            if stash_info:
                _unstash_after_merge(work_path, stash_info)
            error_msg = f"Failed to checkout {base_branch}: {result.stderr.strip()}"
            click.echo(error_msg, err=True)
            if resolve_window:
                _launch_merge_window(data, pr_entry, error_msg, background=background,
                                     transcript=transcript, companion=companion)
                return
            raise SystemExit(1)

        result = git_ops.run_git("merge", "--no-ff", branch, "-m",
                                 f"Merge {branch}: {pr_entry.get('title', pr_id)}",
                                 cwd=workdir, check=False)
        if result.returncode != 0:
            # Abort the failed merge before unstashing
            git_ops.run_git("merge", "--abort", cwd=workdir, check=False)
            if stash_info:
                _unstash_after_merge(work_path, stash_info)
            # Git sends conflict details to stdout, other errors to stderr
            error_detail = (result.stdout.strip() + "\n" + result.stderr.strip()).strip()
            error_msg = f"Merge failed:\n{error_detail}" if error_detail else "Merge failed"
            click.echo(error_msg, err=True)
            click.echo("Resolve conflicts manually, then run 'pm pr merge' again.", err=True)
            if resolve_window:
                _launch_merge_window(data, pr_entry, error_msg, background=background,
                                     transcript=transcript, companion=companion)
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

        if stash_info:
            _unstash_after_merge(work_path, stash_info)

    # --- Propagate merged base_branch to the main repo / origin ---
    if backend_name == "local":
        # Local backend: pull from workdir into the main repo dir
        repo_dir = str(_resolve_repo_dir(root, data))
        pull_ok = _pull_from_workdir(
            data, pr_entry, repo_dir, str(work_path), base_branch,
            resolve_window=resolve_window, background=background,
            transcript=transcript, companion=companion,
        )
        if not pull_ok:
            # When resolve_window=True, a window was launched — exit 0
            # so callers (idle tracker, review loop) don't treat it as
            # failure. When resolve_window=False, the helper printed
            # "Pull manually..." — exit non-zero so the popup / TUI
            # surfaces it.
            if not resolve_window:
                raise SystemExit(1)
            return
        _finalize_merge(root, pr_entry, pr_id, transcript=transcript)
        repo = data.get("project", {}).get("repo", "")
        if "project_manager" in repo or "project-manager" in repo:
            trigger_tui_restart()
    else:
        if not propagation_only:
            # Vanilla backend: push to remote origin (already done in step 1 or by Claude)
            push_result = git_ops.run_git("push", "origin", base_branch,
                                          cwd=workdir, check=False)
            if push_result.returncode != 0:
                error_msg = f"Push to origin failed: {push_result.stderr.strip()}"
                click.echo(error_msg, err=True)
                if resolve_window:
                    _launch_merge_window(data, pr_entry, error_msg,
                                         background=background, transcript=transcript,
                                         companion=companion)
                    return
                click.echo("Push manually when ready, then re-run 'pm pr merge'.", err=True)
                raise SystemExit(1)
            click.echo(f"Pushed merged {base_branch} to origin.")
        else:
            click.echo("Propagation only: skipping push to origin.")
        # Pull into the main repo dir so it stays up to date
        repo_dir = str(_resolve_repo_dir(root, data))
        pull_ok = _pull_after_merge(
            data, pr_entry, repo_dir, base_branch,
            resolve_window=resolve_window,
            background=background,
            transcript=transcript,
            companion=companion,
        )
        if not pull_ok:
            # resolve_window=True: window launched — caller will retry
            # via idle tracker; exit 0 so they don't treat the handoff
            # as failure. resolve_window=False: helper printed "Resolve
            # conflicts manually..." — exit non-zero so the popup / TUI
            # actually surfaces it instead of closing silently.
            if not resolve_window:
                raise SystemExit(1)
            return
        _finalize_merge(root, pr_entry, pr_id, transcript=transcript)
        repo = data.get("project", {}).get("repo", "")
        if "project_manager" in repo or "project-manager" in repo:
            trigger_tui_restart()


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

    # Check merge status outside the lock (network/git calls)
    merged_ids = set()
    for pr_entry in prs:
        if pr_entry.get("status") not in ("in_review", "in_progress", "qa"):
            continue
        branch = pr_entry.get("branch", "")
        # Prefer PR's own workdir if it exists
        wd = pr_entry.get("workdir")
        check_dir = wd if (wd and Path(wd).exists()) else target_workdir

        if backend.is_merged(str(check_dir), branch, base_branch):
            merged_ids.add(pr_entry["id"])
            click.echo(f"  ✅ {_pr_display_id(pr_entry)}: merged")
            updated += 1

    if updated:
        def apply(data):
            for pr in data.get("prs") or []:
                if pr["id"] in merged_ids:
                    pr["status"] = "merged"
                    _record_status_timestamp(pr, "merged")

        data = store.locked_update(root, apply)
        trigger_tui_refresh()
    else:
        click.echo("No new merges detected.")

    # Show newly unblocked PRs
    ready = graph.ready_prs(data.get("prs") or [])
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

    # Network call first (outside lock)
    click.echo("Fetching PRs from GitHub...")
    gh_prs = gh_ops.list_prs(repo_dir, state=gh_state)
    if not gh_prs:
        click.echo("No PRs found on GitHub.")
        return

    # Build entries to import from network results
    entries_to_import = []
    existing_branches = {p.get("branch") for p in (data.get("prs") or [])}
    existing_gh_numbers = {p.get("gh_pr_number") for p in (data.get("prs") or []) if p.get("gh_pr_number")}
    existing_ids = {p["id"] for p in (data.get("prs") or [])}

    skipped = 0
    for gh_pr in gh_prs:
        branch = gh_pr.get("headRefName", "")
        number = gh_pr.get("number")
        title = gh_pr.get("title", "")

        if branch in existing_branches or number in existing_gh_numbers:
            skipped += 1
            continue

        status = _gh_state_to_status(gh_pr.get("state", "OPEN"), gh_pr.get("isDraft", False))
        url = gh_pr.get("url", "")
        body = gh_pr.get("body", "") or ""
        pr_id = store.generate_pr_id(title, body, existing_ids)

        entry = _make_pr_entry(pr_id, title, branch, status=status,
                               description=body, gh_pr=url,
                               gh_pr_number=number)
        entries_to_import.append(entry)
        existing_ids.add(pr_id)
        existing_branches.add(branch)
        existing_gh_numbers.add(number)
        click.echo(f"  + {pr_id}: {title} [{status}] (#{number})")

    if entries_to_import:
        def apply(data):
            if data.get("prs") is None:
                data["prs"] = []
            # Re-check existing to avoid duplicates from concurrent imports
            current_branches = {p.get("branch") for p in data["prs"]}
            current_gh_numbers = {p.get("gh_pr_number") for p in data["prs"] if p.get("gh_pr_number")}
            for entry in entries_to_import:
                if entry.get("branch") not in current_branches and entry.get("gh_pr_number") not in current_gh_numbers:
                    data["prs"].append(entry)

        store.locked_update(root, apply)
        click.echo(f"\nImported {len(entries_to_import)} PR(s), skipped {skipped} already tracked.")
        trigger_tui_refresh()
    else:
        click.echo(f"No new PRs to import ({skipped} already tracked).")


def _workdir_is_dirty(work_path: Path) -> bool:
    """Check if a workdir has uncommitted changes."""
    result = git_ops.run_git("status", "--porcelain", cwd=work_path, check=False)
    return bool(result.stdout.strip())


# ---------------------------------------------------------------------------
# Stash-retry helpers for merge operations
# ---------------------------------------------------------------------------

def _is_dirty_overlap_error(result: subprocess.CompletedProcess) -> bool:
    """True if a git operation failed because dirty files would be overwritten."""
    combined = result.stderr + result.stdout
    return "would be overwritten" in combined


def _dirty_file_paths(cwd: Path) -> list[str]:
    """Return relative paths of dirty files in the working tree."""
    result = git_ops.run_git("status", "--porcelain", cwd=cwd, check=False)
    paths = []
    for line in result.stdout.strip().splitlines():
        if not line.strip():
            continue
        # porcelain format: XY filename  (or XY orig -> renamed)
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        paths.append(path)
    return paths


def _stash_for_merge(cwd: Path, pr_display_id: str = "",
                     lock_tui: bool = True) -> dict | None:
    """Stash dirty files so a merge can proceed.

    If pm/ files are among the dirty files and *lock_tui* is True, writes
    a merge-lock marker so the TUI shows an overlay while the files are
    temporarily reverted.

    Returns a dict with stash metadata (``has_pm``, ``count``) on success,
    or None if stashing failed or there was nothing to stash.
    """
    dirty = _dirty_file_paths(cwd)
    if not dirty:
        return None

    has_pm = any(p.startswith("pm/") or p.startswith("pm\\") for p in dirty)

    if has_pm and lock_tui:
        trigger_tui_merge_lock(pr_display_id)

    click.echo(f"Stashing {len(dirty)} dirty file(s) to proceed with merge...")
    stash_r = git_ops.run_git("stash", "push", "--include-untracked",
                               "-m", "pm: auto-stash for merge",
                               cwd=cwd, check=False)
    if stash_r.returncode != 0:
        click.echo(f"Failed to stash: {stash_r.stderr.strip()}", err=True)
        if has_pm and lock_tui:
            trigger_tui_merge_unlock()
        return None

    return {"has_pm": has_pm, "count": len(dirty), "lock_tui": lock_tui}


def _unstash_after_merge(cwd: Path, info: dict) -> bool:
    """Pop the stash and remove the TUI merge-lock if one was set.

    Returns True if the stash popped cleanly.
    """
    pop_r = git_ops.run_git("stash", "pop", cwd=cwd, check=False)
    clean = pop_r.returncode == 0

    if info.get("has_pm") and info.get("lock_tui"):
        trigger_tui_merge_unlock()

    if clean:
        click.echo(f"Restored {info['count']} stashed file(s).")
    else:
        click.echo("Warning: stash pop had conflicts. Resolve manually.", err=True)
    return clean


def _cleanup_pr(pr_entry: dict, root: Path, force: bool) -> bool:
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
    return True


@pr.command("cleanup")
@click.argument("pr_id", default=None, required=False)
@click.option("--force", is_flag=True, default=False, help="Remove even if workdir has uncommitted changes")
@click.option("--all", "cleanup_all", is_flag=True, default=False, help="Clean up all PR workdirs")
@click.option("--prune", is_flag=True, default=False, help="Clear workdir references for paths that no longer exist")
@click.option("--resources", is_flag=True, default=False,
              help="Tear down live resources (tmux windows, QA containers, "
                   "pane registry, push-proxy sockets) instead of the workdir")
def pr_cleanup(pr_id: str | None, force: bool, cleanup_all: bool, prune: bool,
               resources: bool):
    """Remove work directory for a PR.

    Refuses to delete workdirs with uncommitted changes unless --force is given.
    Use --all to clean up all PR workdirs at once.
    Use --prune to clear stale workdir references from project.yaml.
    Use --resources to kill live tmux/docker/registry resources for a PR.
    """
    root = state_root()
    data = store.load(root)

    if resources:
        if pr_id is None:
            click.echo("--resources requires a PR id.", err=True)
            raise SystemExit(1)
        target = _resolve_pr_id(data, pr_id)
        if not target:
            click.echo(f"PR '{pr_id}' not found.", err=True)
            raise SystemExit(1)
        from pm_core import pr_cleanup as pr_cleanup_mod
        from pm_core.loop_shared import get_pm_session
        session = get_pm_session()
        summary = pr_cleanup_mod.cleanup_pr_resources(session, target)
        click.echo(f"Cleaned {target['id']}: {pr_cleanup_mod.format_summary(summary)}")
        if summary["windows"]:
            click.echo(f"  windows: {', '.join(summary['windows'])}")
        if summary["containers"]:
            click.echo(f"  containers: {', '.join(summary['containers'])}")
        if summary["registry_windows"]:
            click.echo(f"  registry: {', '.join(summary['registry_windows'])}")
        trigger_tui_refresh()
        return

    if prune:
        pruned = 0

        def apply_prune(data):
            nonlocal pruned
            for p in data.get("prs") or []:
                wd = p.get("workdir")
                if wd and not Path(wd).exists():
                    click.echo(f"  {p['id']}: cleared missing workdir {wd}")
                    p["workdir"] = None
                    pruned += 1

        store.locked_update(root, apply_prune)
        if pruned:
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
        # Do filesystem cleanup first (outside lock), collect cleaned IDs
        cleaned_ids = set()
        for pr_entry in with_workdir:
            if _cleanup_pr(pr_entry, root, force):
                cleaned_ids.add(pr_entry["id"])
        if cleaned_ids:
            def apply_cleanup_all(data):
                for pr in data.get("prs") or []:
                    if pr["id"] in cleaned_ids:
                        pr["workdir"] = None

            store.locked_update(root, apply_cleanup_all)
            trigger_tui_refresh()
        click.echo(f"Cleaned {len(cleaned_ids)}/{len(with_workdir)} workdirs.")
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

    target_id = pr_entry["id"]
    if _cleanup_pr(pr_entry, root, force):
        store.locked_update(root, lambda d: _clear_workdir(d, target_id))
        trigger_tui_refresh()


def _clear_workdir(data: dict, pr_id: str) -> None:
    """Clear the workdir field for a PR (used inside locked_update)."""
    pr = store.get_pr(data, pr_id)
    if pr:
        pr["workdir"] = None


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

    note_id = store.generate_note_id(pr_id, text)
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    note = {"id": note_id, "text": text, "created_at": created_at, "last_edited": created_at}

    def apply(data):
        pr = store.get_pr(data, pr_id)
        if not pr:
            return
        notes = pr.get("notes") or []
        notes.append(note)
        pr["notes"] = notes
        _record_status_timestamp(pr)

    store.locked_update(root, apply)
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

    # Validate note exists (on stale data, but good enough for error messages)
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

    new_id = store.generate_note_id(pr_id, text)

    def apply(data):
        pr = store.get_pr(data, pr_id)
        if not pr:
            return
        for n in pr.get("notes") or []:
            if n["id"] == note_id:
                n["id"] = new_id
                n["text"] = text
                n["last_edited"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                break
        _record_status_timestamp(pr)

    store.locked_update(root, apply)
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

    # Validate note exists
    notes = pr_entry.get("notes") or []
    if not any(n["id"] == note_id for n in notes):
        click.echo(f"Note '{note_id}' not found on {_pr_display_id(pr_entry)}.", err=True)
        if notes:
            click.echo("Available notes:", err=True)
            for n in notes:
                click.echo(f"  {n['id']}: {n['text']}", err=True)
        raise SystemExit(1)

    def apply(data):
        pr = store.get_pr(data, pr_id)
        if not pr:
            return
        pr["notes"] = [n for n in (pr.get("notes") or []) if n["id"] != note_id]
        _record_status_timestamp(pr)

    store.locked_update(root, apply)
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

    # Remove workdir if exists (filesystem op, safe outside lock)
    workdir = pr_entry.get("workdir")
    if workdir and Path(workdir).exists():
        shutil.rmtree(workdir)
        click.echo(f"Removed workdir: {workdir}")

    # Remove PR from list and update active_pr under lock
    target_id = pr_id

    def apply(data):
        data["prs"] = [p for p in (data.get("prs") or []) if p["id"] != target_id]
        if data.get("project", {}).get("active_pr") == target_id:
            remaining = data.get("prs") or []
            data["project"]["active_pr"] = remaining[0]["id"] if remaining else None

    store.locked_update(root, apply)
    click.echo(f"Removed {pr_id}: {pr_entry.get('title', '???')}")
    trigger_tui_refresh()


# ---------------------------------------------------------------------------
# Auto-sequence: chain start → review → QA on a single PR (stops before merge)
# ---------------------------------------------------------------------------

def _auto_seq_transcript_dir(root: Path, pr_id: str) -> Path:
    """Return the deterministic transcript dir for auto-sequence on *pr_id*.

    Stable across CLI ticks so successive invocations resolve the same
    impl/review/QA transcript symlinks.
    """
    return root / "transcripts" / "auto-sequence" / pr_id


def _impl_window_pane(session: str, pr_entry: dict) -> str | None:
    """Return the first pane id of the impl tmux window, or None."""
    win = tmux_mod.find_window_by_name(session, _pr_display_id(pr_entry))
    if not win:
        return None
    panes = tmux_mod.get_pane_indices(session, win["index"])
    return panes[0][0] if panes else None


def _review_window_pane(session: str, pr_entry: dict) -> str | None:
    """Return the first pane id of the review tmux window, or None."""
    name = f"review-{_pr_display_id(pr_entry)}"
    win = tmux_mod.find_window_by_name(session, name)
    if not win:
        return None
    panes = tmux_mod.get_pane_indices(session, win["index"])
    return panes[0][0] if panes else None


def _check_review_verdict(tdir: Path, pr_id: str) -> tuple[str | None, int]:
    """Return (verdict, latest_iteration) by scanning iteration transcripts.

    Verdicts: PASS / NEEDS_WORK / INPUT_REQUIRED.  Returns (None, 0) when
    no iteration transcripts exist.
    """
    from pm_core.verdict_transcript import extract_verdict_from_transcript

    if not tdir.is_dir():
        return None, 0
    iters: list[tuple[int, Path]] = []
    for p in tdir.iterdir():
        m = re.match(rf"review-{re.escape(pr_id)}-i(\d+)\.jsonl$", p.name)
        if m and (p.is_file() or p.is_symlink()):
            iters.append((int(m.group(1)), p))
    if not iters:
        return None, 0
    iters.sort()
    latest_iter, latest_path = iters[-1]
    verdict = extract_verdict_from_transcript(
        str(latest_path), ("PASS", "NEEDS_WORK", "INPUT_REQUIRED"),
    )
    return verdict, latest_iter


def _check_impl_idle(session: str, pr_entry: dict, tdir: Path) -> tuple[bool, bool]:
    """Return (idle, gone): polls the impl pane via PaneIdleTracker.

    *idle* is True when the Claude session has emitted ``idle_prompt``.
    *gone* is True when the tmux pane disappeared.
    """
    from pm_core.pane_idle import PaneIdleTracker

    pr_id = pr_entry["id"]
    pane_id = _impl_window_pane(session, pr_entry)
    if not pane_id:
        return False, True
    transcript = tdir / f"impl-{pr_id}.jsonl"
    if not transcript.exists():
        return False, False
    tracker = PaneIdleTracker()
    try:
        tracker.register(pr_id, pane_id, str(transcript))
    except ValueError:
        return False, False
    tracker.poll(pr_id)
    return tracker.is_idle(pr_id), tracker.is_gone(pr_id)


def _qa_status_for(pr_id: str) -> tuple[str | None, Path | None]:
    """Find the latest QA status.json for *pr_id*; return (overall, path)."""
    import json
    qa_dirs = Path.home() / ".pm" / "workdirs" / "qa"
    if not qa_dirs.is_dir():
        return None, None
    candidates = sorted(qa_dirs.glob(f"{pr_id}-*/qa_status.json"),
                        key=lambda p: p.stat().st_mtime if p.exists() else 0)
    if not candidates:
        return None, None
    latest = candidates[-1]
    try:
        data = json.loads(latest.read_text())
    except (OSError, ValueError):
        return None, latest
    return data.get("overall") or None, latest


@pr.command("auto-sequence")
@click.argument("pr_id")
def pr_auto_sequence(pr_id: str):
    """Advance a PR through start → review → QA, stopping before merge.

    Idempotent and non-blocking: each invocation examines the PR's current
    state and advances it by at most one phase.  Designed to be called
    repeatedly (e.g. by an implementation watcher) until the PR reports
    ``ready_to_merge`` or ``paused: ...``.

    Output is a single status line on stdout.  Exit codes:
      0 — advanced or status reported normally
      2 — PR not found / unknown state
    """
    root = state_root()
    data = store.load(root)
    pr_entry = _require_pr(data, pr_id)
    pr_id = pr_entry["id"]
    status = pr_entry.get("status", "")
    pm_session = _get_pm_session()
    tdir = _auto_seq_transcript_dir(root, pr_id)
    tdir.mkdir(parents=True, exist_ok=True)

    if status == "merged":
        click.echo("merged")
        return

    if status == "pending":
        impl_transcript = tdir / f"impl-{pr_id}.jsonl"
        ctx = click.get_current_context()
        ctx.invoke(pr_start, pr_id=pr_id, workdir=None, fresh=False,
                   background=True, transcript=str(impl_transcript),
                   companion=False)
        click.echo("started")
        return

    if status == "in_progress":
        if spec_gen.has_pending_spec(pr_entry):
            click.echo("paused: spec_pending")
            return
        if not pm_session:
            click.echo("paused: no pm tmux session")
            return
        idle, gone = _check_impl_idle(pm_session, pr_entry, tdir)
        if gone:
            # Window was killed — relaunch impl
            impl_transcript = tdir / f"impl-{pr_id}.jsonl"
            ctx = click.get_current_context()
            ctx.invoke(pr_start, pr_id=pr_id, workdir=None, fresh=False,
                       background=True, transcript=str(impl_transcript),
                       companion=False)
            click.echo("restarted: impl window relaunched")
            return
        if not idle:
            click.echo("running: implementation")
            return
        # Idle and no spec_pending → advance to review.  Persist the
        # transcript symlink under the auto-sequence dir so the next tick
        # can locate the verdict.  Use review-loop iteration 1 naming so
        # NEEDS_WORK retries (iteration 2+) follow the same scheme.
        iter_transcript = tdir / f"review-{pr_id}-i1.jsonl"
        ctx = click.get_current_context()
        ctx.invoke(pr_review, pr_id=pr_id, fresh=False, background=True,
                   review_loop=False, review_iteration=1,
                   review_loop_id="", transcript=str(iter_transcript))
        click.echo("advanced: in_review")
        return

    if status == "in_review":
        if not pm_session:
            click.echo("paused: no pm tmux session")
            return
        verdict, latest_iter = _check_review_verdict(tdir, pr_id)

        if verdict == "PASS":
            project = data.get("project") or {}
            if project.get("skip_qa"):
                click.echo("ready_to_merge (skip_qa)")
                return
            # Transition to qa and launch QA in a detached subprocess.
            def _to_qa(d):
                p = store.get_pr(d, pr_id)
                if p and p.get("status") == "in_review":
                    p["status"] = "qa"
                    _record_status_timestamp(p, "qa")
            store.locked_update(root, _to_qa)
            _launch_qa_detached(root, pr_id)
            click.echo("advanced: qa")
            return

        if verdict == "INPUT_REQUIRED":
            click.echo("paused: input_required (review)")
            return

        if verdict == "NEEDS_WORK":
            # Launch a fresh review-loop iteration.  Reuse pr_review with
            # --fresh + --review-loop so the existing review-loop
            # machinery in the launched window writes to the next
            # iteration transcript.
            next_iter = latest_iter + 1
            iter_transcript = tdir / f"review-{pr_id}-i{next_iter}.jsonl"
            ctx = click.get_current_context()
            ctx.invoke(pr_review, pr_id=pr_id, fresh=True, background=True,
                       review_loop=True, review_iteration=next_iter,
                       review_loop_id="", transcript=str(iter_transcript))
            click.echo(f"review: needs_work, retrying iteration {next_iter}")
            return

        # No verdict yet
        if _review_window_pane(pm_session, pr_entry) is None:
            # Review window absent — launch a review-loop iteration.
            next_iter = max(latest_iter, 0) + 1
            iter_transcript = tdir / f"review-{pr_id}-i{next_iter}.jsonl"
            ctx = click.get_current_context()
            ctx.invoke(pr_review, pr_id=pr_id, fresh=False, background=True,
                       review_loop=True, review_iteration=next_iter,
                       review_loop_id="", transcript=str(iter_transcript))
            click.echo("advanced: review_relaunched")
            return
        click.echo("running: review")
        return

    if status == "qa":
        overall, _path = _qa_status_for(pr_id)
        if overall == "PASS":
            click.echo("ready_to_merge")
            return
        if overall == "INPUT_REQUIRED":
            click.echo("paused: input_required (qa)")
            return
        if overall == "NEEDS_WORK":
            # Flip status to in_review and immediately launch a fresh
            # review-loop iteration with QA feedback.  Without launching
            # here, the next tick's in_review path would pick up the
            # *previous* iteration's PASS verdict and bounce straight
            # back to qa.  Mirrors the TUI's qa_loop_ui NEEDS_WORK path.
            def _to_review(d):
                p = store.get_pr(d, pr_id)
                if p and p.get("status") == "qa":
                    p["status"] = "in_review"
                    _record_status_timestamp(p, "in_review")
            store.locked_update(root, _to_review)
            _verdict, latest_iter = _check_review_verdict(tdir, pr_id)
            next_iter = latest_iter + 1
            iter_transcript = tdir / f"review-{pr_id}-i{next_iter}.jsonl"
            ctx = click.get_current_context()
            ctx.invoke(pr_review, pr_id=pr_id, fresh=True, background=True,
                       review_loop=True, review_iteration=next_iter,
                       review_loop_id="", transcript=str(iter_transcript))
            click.echo(
                f"qa: needs_work, returning to review (iteration {next_iter})"
            )
            return
        if overall is None:
            # No qa_status.json yet.  Could be a never-started run *or*
            # a freshly-launched run whose first status write hasn't
            # landed yet.  Check for the qa tmux window before
            # re-launching to avoid stacking duplicate QA subprocesses
            # during the launch→first-write race window.
            display_id = _pr_display_id(pr_entry)
            qa_win = tmux_mod.find_window_by_name(
                pm_session, f"qa-{display_id}",
            ) if pm_session else None
            if qa_win:
                click.echo("running: qa")
                return
            _launch_qa_detached(root, pr_id)
            click.echo("running: qa (launched)")
            return
        click.echo("running: qa")
        return

    click.echo(f"unknown status: {status}", err=True)
    raise SystemExit(2)


def _launch_qa_detached(root: Path, pr_id: str) -> None:
    """Spawn a detached subprocess to drive the QA loop for *pr_id*.

    Uses the hidden ``pm pr qa-run-bg`` subcommand so the QA scenarios
    run in tmux windows under their own long-lived process.  Subsequent
    auto-sequence ticks read the resulting ``qa_status.json``.
    """
    cmd = [sys.executable, "-m", "pm_core.wrapper",
           "pr", "qa-run-bg", pr_id]
    # start_new_session detaches from the parent process group so the
    # caller can exit while QA continues.
    subprocess.Popen(
        cmd, cwd=str(root), start_new_session=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
    )


@pr.command("qa-run-bg", hidden=True)
@click.argument("pr_id")
def pr_qa_run_bg(pr_id: str):
    """Hidden: run the QA loop synchronously to completion.

    Used by ``pm pr auto-sequence`` to spawn a detached QA driver.  Not
    intended for direct human use — prefer the TUI ``t`` key.
    """
    from pm_core.qa_loop import QALoopState, run_qa_sync

    root = state_root()
    data = store.load(root)
    pr_entry = _require_pr(data, pr_id)
    pr_id = pr_entry["id"]

    # Transition to qa if necessary
    def _to_qa(d):
        p = store.get_pr(d, pr_id)
        if p and p.get("status") == "in_review":
            p["status"] = "qa"
            _record_status_timestamp(p, "qa")
    store.locked_update(root, _to_qa)
    data = store.load(root)
    pr_entry = store.get_pr(data, pr_id) or pr_entry

    state = QALoopState(pr_id=pr_id)
    try:
        run_qa_sync(state, root, pr_entry, on_update=None, max_scenarios=None)
    except Exception as e:
        _log.exception("pr_qa_run_bg: QA crashed for %s: %s", pr_id, e)
        raise SystemExit(1)
