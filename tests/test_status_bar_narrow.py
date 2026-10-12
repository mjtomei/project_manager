"""Status bar keeps its short indicators visible on a narrow terminal.

The bar is a single row; the repo path used to sit before sync/AUTO/WCH, so
at ~100 columns (e.g. with the L log pane split beside the TUI) the long
path pushed ``AUTO ×N`` off the row entirely.
"""

import asyncio

from textual.app import App, ComposeResult

from pm_core.tui.app import ProjectManagerApp
from pm_core.tui.widgets import StatusBar


class _BarApp(App):
    CSS = ProjectManagerApp.CSS

    def compose(self) -> ComposeResult:
        yield StatusBar(id="status-bar")


def _bar_text(width: int) -> str:
    async def run():
        app = _BarApp()
        async with app.run_test(size=(width, 6)) as pilot:
            bar = app.query_one("#status-bar", StatusBar)
            bar.update_status("pm-test-s6-1791844686",
                              "/tmp/pm-test-s6-1791844686",
                              "synced", pr_count=4, filter_text="hide closed",
                              show_assist=True, auto_start=True,
                              auto_label="×2")
            await pilot.pause()
            return bar.render_line(0).text
    return asyncio.run(run())


def test_auto_segment_visible_at_100_columns():
    line = _bar_text(100)
    assert "AUTO ×2" in line
    assert "synced" in line


def test_repo_path_still_shown_when_wide():
    line = _bar_text(200)
    assert "repo: /tmp/pm-test-s6-1791844686" in line
    assert line.index("AUTO ×2") < line.index("repo:")
