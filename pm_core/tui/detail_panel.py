"""Side panel for PR details in the TUI."""

import re
from pathlib import Path

from textual.widget import Widget
from textual.reactive import reactive
from rich.text import Text
from rich.panel import Panel
from rich.console import RenderableType

from pm_core.plan_parser import extract_field
from pm_core.tui.tech_tree import STATUS_ICONS


def _extract_plan_section(plan_file: Path, pr_title: str) -> dict | None:
    """Extract the plan section for a specific PR from a plan markdown file.

    Finds the ``### PR: <pr_title>`` block and returns its ``tests`` and
    ``files`` fields, or None if no matching section is found.
    """
    try:
        text = plan_file.read_text()
    except OSError:
        return None

    # Split on ### PR: headings
    blocks = re.split(r'^### PR:\s*', text, flags=re.MULTILINE)
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        first_line = block.split('\n', 1)[0].strip()
        if first_line == pr_title:
            body = block.split('\n', 1)[1] if '\n' in block else ""
            tests = extract_field(body, "tests")
            files = extract_field(body, "files")
            if tests or files:
                return {"tests": tests, "files": files}
            return None
    return None


def _pr_display_id(pr: dict) -> str:
    """Display ID for a PR: prefer GitHub #N, fall back to local pr-NNN."""
    gh = pr.get("gh_pr_number")
    return f"#{gh}" if gh else pr.get("id", "???")


class DetailPanel(Widget):
    """Shows detailed information about the selected PR."""

    pr_data: reactive[dict | None] = reactive(None)

    def update_pr(self, pr: dict | None, all_prs: list[dict] | None = None,
                  plan: dict | None = None, project_root: Path | None = None) -> None:
        self._all_prs = all_prs or []
        self._plan = plan
        self._project_root = project_root
        self.pr_data = pr
        self.refresh()

    def render(self) -> RenderableType:
        pr = self.pr_data
        if pr is None:
            return Panel("Select a PR and press Enter to view details",
                         title="Details", border_style="dim")

        display_id = _pr_display_id(pr)
        title = pr.get("title", "???")
        status = pr.get("status", "pending")
        icon = STATUS_ICONS.get(status, "?")
        branch = pr.get("branch", "")
        plan = pr.get("plan", "")
        machine = pr.get("agent_machine")
        gh_pr = pr.get("gh_pr")
        description = pr.get("description", "").strip()
        deps = pr.get("depends_on") or []

        lines = []
        lines.append(f"[bold]{display_id}[/bold]: {title}")
        lines.append(f"Status: {icon} {status}")
        lines.append(f"Branch: [cyan]{branch}[/cyan]")
        if plan:
            plan_obj = getattr(self, "_plan", None)
            plan_name = plan_obj.get("name", "") if plan_obj else ""
            if plan_name:
                lines.append(f"Plan: {plan} — {plan_name}")
            else:
                lines.append(f"Plan: {plan}")
        if machine:
            lines.append(f"Machine: {machine}")
        if gh_pr:
            lines.append(f"GH PR: {gh_pr}")
        lines.append("")

        if deps:
            lines.append("[bold]Dependencies:[/bold]")
            pr_map = {p["id"]: p for p in (self._all_prs if hasattr(self, "_all_prs") else [])}
            for dep_id in deps:
                dep = pr_map.get(dep_id)
                if dep:
                    dep_icon = STATUS_ICONS.get(dep.get("status", "pending"), "?")
                    dep_display = _pr_display_id(dep)
                    lines.append(f"  {dep_icon} {dep_display}: {dep.get('title', '???')}")
                else:
                    lines.append(f"  ? {dep_id}")
            lines.append("")

        if description:
            lines.append("[bold]Description:[/bold]")
            lines.append(description)

        # Show plan section info (tests/files) if available
        plan_obj = getattr(self, "_plan", None)
        root = getattr(self, "_project_root", None)
        if plan_obj and root and pr.get("title"):
            plan_file = root / plan_obj.get("file", "")
            section = _extract_plan_section(plan_file, pr.get("title", ""))
            if section:
                lines.append("")
                lines.append("[bold]From plan:[/bold]")
                if section.get("tests"):
                    lines.append(f"  Tests: {section['tests']}")
                if section.get("files"):
                    lines.append(f"  Files: {section['files']}")

        content = "\n".join(lines)
        return Panel(content, title=f"{display_id}", border_style="blue")
