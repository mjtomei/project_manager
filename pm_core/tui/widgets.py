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
                       sort_text: str = "",
                       show_assist: bool = False,
                       auto_start: bool = False,
                       watcher_status: str = "",
                       memory_status: str = "") -> None:
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
        sort_display = f"    [dim]sort:[/dim] [italic]{sort_text}[/italic]" if sort_text else ""
        assist_display = "    [dim]\\[H] Assist[/dim]" if show_assist else ""
        auto_display = "    [bold yellow]AUTO[/bold yellow]" if auto_start else ""
        if watcher_status == "input_required":
            watcher_display = "    [bold red]WCH!![/bold red]"
        elif watcher_status == "running":
            watcher_display = "    [bold cyan]WCH[/bold cyan]"
        else:
            watcher_display = ""
        memory_display = f"    [bold cyan]{memory_status}[/bold cyan]" if memory_status else ""
        self.update(f" Project: [bold]{project_name}[/bold]    {pr_info}{filter_display}{sort_display}    repo: [cyan]{safe_repo}[/cyan]    {sync_display}{auto_display}{watcher_display}{memory_display}{assist_display}")


class SessionBar(Static):
    """Second status bar row showing active session overrides."""

    def refresh_session_info(self) -> None:
        """Read session files and update display; hide self if nothing active."""
        from pathlib import Path
        from pm_core.paths import session_dir, skip_permissions_enabled

        sd = session_dir()
        parts: list[str] = []

        if sd:
            override_file = sd / "override"
            if override_file.exists():
                try:
                    content = override_file.read_text().strip()
                    if content:
                        from rich.markup import escape
                        parts.append(f"[dim]override:[/dim] [cyan]{escape(content)}[/cyan]")
                except OSError:
                    pass

            if skip_permissions_enabled():
                parts.append("[bold red]dangerously-skip-permissions[/bold red]")

        if parts:
            self.update(" " + "    ".join(parts))
            self.display = True
        else:
            self.display = False


class LogLine(Static):
    """Single-line log output above the command bar."""
    pass
