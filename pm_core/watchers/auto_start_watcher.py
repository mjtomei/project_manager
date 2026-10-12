"""Auto-start watcher: the original watcher loop refactored as a BaseWatcher.

This watcher monitors all active tmux panes for issues during auto-start
mode, attempting fixes when possible and surfacing problems that need
human input.  It uses the same prompt and window management as the legacy
``pm watcher`` command.
"""

import sys

from pm_core.paths import configure_logger
from pm_core.watcher_base import BaseWatcher, WatcherState
from pm_core.loop_shared import match_verdict

_log = configure_logger("pm.watchers.auto_start")


class AutoStartWatcher(BaseWatcher):
    """Concrete watcher for auto-start monitoring."""

    WATCHER_TYPE = "auto-start"
    DISPLAY_NAME = "Auto-Start Watcher"
    WINDOW_NAME = "watcher"
    DEFAULT_INTERVAL = 120
    VERDICTS = ("READY", "INPUT_REQUIRED")
    KEYWORDS = ("READY", "INPUT_REQUIRED")

    def __init__(self, pm_root: str,
                 auto_start_targets: list[str] | None = None,
                 meta_pm_root: str | None = None,
                 state: WatcherState | None = None,
                 auto_start_target: str | None = None):
        super().__init__(pm_root, state=state)
        # The TUI keeps this list current as targets are added/removed
        # (auto_start._sync_enabled).  ``auto_start_target`` is the legacy
        # single-target kwarg.
        targets = list(auto_start_targets or [])
        if auto_start_target and auto_start_target not in targets:
            targets.append(auto_start_target)
        self.auto_start_targets = targets
        self.meta_pm_root = meta_pm_root

    def generate_prompt(self, iteration: int) -> str:
        """Generate the watcher prompt via prompt_gen."""
        from pathlib import Path
        from pm_core import store
        from pm_core.prompt_gen import generate_watcher_prompt

        try:
            data = store.load(Path(self.pm_root))
            return generate_watcher_prompt(
                data, iteration=iteration, loop_id=self.state.loop_id,
                auto_start_targets=self.auto_start_targets,
                meta_pm_root=self.meta_pm_root,
            )
        except Exception as exc:
            _log.warning("auto_start_watcher: could not generate prompt: %s", exc)
            return ""

    def build_launch_cmd(self, iteration: int,
                         transcript: str | None = None) -> list[str]:
        """Build the ``pm watcher --iteration`` CLI command."""
        cmd = [
            sys.executable, "-m", "pm_core.wrapper",
            "watcher", "--iteration", str(iteration),
        ]
        if self.state.loop_id:
            cmd.extend(["--loop-id", self.state.loop_id])
        if transcript:
            cmd.extend(["--transcript", transcript])
        for target in self.auto_start_targets:
            cmd.extend(["--auto-start-target", target])
        if self.meta_pm_root:
            cmd.extend(["--meta-pm-root", self.meta_pm_root])
        return cmd

    def parse_verdict(self, output: str) -> str:
        """Extract a watcher verdict from Claude output."""
        lines = output.strip().splitlines()
        for line in reversed(lines):
            stripped = line.strip().strip("*").strip()
            verdict = match_verdict(stripped, self.VERDICTS)
            if verdict:
                return verdict
        # No clear verdict found — default to READY (continue watching)
        return "READY"
