"""Side panel for PR details in the TUI."""

from textual.widget import Widget
from textual.reactive import reactive
from rich.text import Text
from rich.panel import Panel
from rich.console import RenderableType

from pm_core.tui.tech_tree import STATUS_ICONS


def _pr_display_id(pr: dict) -> str:
    """Display ID for a PR: prefer GitHub #N, fall back to local pr-NNN."""
    gh = pr.get("gh_pr_number")
    return f"#{gh}" if gh else pr.get("id", "???")


class DetailPanel(Widget):
    """Shows detailed information about the selected PR."""

    pr_data: reactive[dict | None] = reactive(None)

    def update_pr(self, pr: dict | None, all_prs: list[dict] | None = None) -> None:
        self._all_prs = all_prs or []
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

        lines.append("")
        lines.append("[dim]s=start  d=done  p=copy prompt  q=quit[/dim]")

        content = "\n".join(lines)
        return Panel(content, title=f"{display_id}", border_style="blue")
