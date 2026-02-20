"""Reusable TUI widgets for Project Manager."""

from textual.containers import ScrollableContainer
from textual.widgets import Static


class TreeScroll(ScrollableContainer, can_focus=False, can_focus_children=True):
    """Scrollable container for the tech tree."""

    DEFAULT_CSS = """
    TreeScroll {
        scrollbar-background: $surface-darken-1;
        scrollbar-color: $text-muted;
        scrollbar-color-hover: $text;
        scrollbar-color-active: $accent;
        scrollbar-size-vertical: 1;
    }
    """


class StatusBar(Static):
    """Top status bar showing project info and sync state."""

    def update_status(self, project_name: str, repo: str, sync_state: str,
                       pr_count: int = 0, filter_text: str = "",
                       show_assist: bool = False,
                       review_loop: str = "") -> None:
        sync_icons = {
            "synced": "[green]synced[/green]",
            "pulling": "[yellow]pulling...[/yellow]",
            "no-op": "[dim]up to date[/dim]",
            "error": "[red]sync error[/red]",
        }
        sync_display = sync_icons.get(sync_state, f"[red]{sync_state}[/red]")
        from rich.markup import escape
        safe_repo = escape(repo)
        pr_info = f"[bold]{pr_count}[/bold] PRs" if pr_count else ""
        filter_display = f"    [dim]filter:[/dim] [italic]{filter_text}[/italic]" if filter_text else ""
        assist_display = "    [dim]\\[H] Assist[/dim]" if show_assist else ""
        loop_display = f"    {review_loop}" if review_loop else ""
        self.update(f" Project: [bold]{project_name}[/bold]    {pr_info}{filter_display}{loop_display}    repo: [cyan]{safe_repo}[/cyan]    {sync_display}{assist_display}")


class LogLine(Static):
    """Single-line log output above the command bar."""
    pass
