"""Discovery supervisor watcher.

Runs the regression test suite on a schedule, files newly-discovered bugs
and improvements as PRs into the ``bugs`` / ``ux`` plans, and reconciles
duplicates against existing open PRs.

Mirrors ``pm_core/watchers/auto_start_watcher.py``: it inherits the shared
loop engine from ``BaseWatcher`` and only customises prompt generation,
launch command, and verdict parsing.
"""

import sys

from pm_core.paths import configure_logger
from pm_core.watcher_base import BaseWatcher, WatcherState
from pm_core.loop_shared import match_verdict

_log = configure_logger("pm.watchers.discovery_supervisor")


class DiscoverySupervisorWatcher(BaseWatcher):
    """Schedules regression tests and reconciles their filings."""

    WATCHER_TYPE = "discovery"
    DISPLAY_NAME = "Discovery Supervisor"
    WINDOW_NAME = "discovery"
    DEFAULT_INTERVAL = 1800  # 30 minutes
    VERDICTS = ("READY", "INPUT_REQUIRED")
    KEYWORDS = ("READY", "INPUT_REQUIRED")

    def __init__(self, pm_root: str,
                 meta_pm_root: str | None = None,
                 state: WatcherState | None = None):
        super().__init__(pm_root, state=state)
        self.meta_pm_root = meta_pm_root

    def generate_prompt(self, iteration: int) -> str:
        from pathlib import Path
        from pm_core import store
        from pm_core.prompt_gen import generate_discovery_supervisor_prompt

        try:
            data = store.load(Path(self.pm_root))
            return generate_discovery_supervisor_prompt(
                data, iteration=iteration, loop_id=self.state.loop_id,
                meta_pm_root=self.meta_pm_root,
            )
        except Exception as exc:
            _log.warning("discovery_supervisor: could not generate prompt: %s", exc)
            return ""

    def build_launch_cmd(self, iteration: int,
                         transcript: str | None = None) -> list[str]:
        cmd = [
            sys.executable, "-m", "pm_core.wrapper",
            "watcher", "--watcher-type", self.WATCHER_TYPE,
            "--iteration", str(iteration),
        ]
        if self.state.loop_id:
            cmd.extend(["--loop-id", self.state.loop_id])
        if transcript:
            cmd.extend(["--transcript", transcript])
        if self.meta_pm_root:
            cmd.extend(["--meta-pm-root", self.meta_pm_root])
        return cmd

    def parse_verdict(self, output: str) -> str:
        lines = output.strip().splitlines()
        for line in reversed(lines):
            stripped = line.strip().strip("*").strip()
            verdict = match_verdict(stripped, self.VERDICTS)
            if verdict:
                return verdict
        return "READY"
