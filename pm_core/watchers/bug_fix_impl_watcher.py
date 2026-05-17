"""Bug-fix implementation watcher.

Drives the bug-fix flow: reads pending PRs in ``plan=bugs``, picks the
best candidate dynamically each tick, advances chosen PRs through the
auto-sequence chain (``pm pr auto-sequence``), and **auto-merges** on
PASS. The auto-merge behaviour is what distinguishes this watcher from
the improvement-fix flow.

Mirrors ``pm_core/watchers/discovery_supervisor.py``: it inherits the
shared loop engine from ``BaseWatcher`` and only customises prompt
generation, launch command, and verdict parsing.
"""

import sys

from pm_core.paths import configure_logger
from pm_core.watcher_base import BaseWatcher, WatcherState
from pm_core.loop_shared import match_verdict

_log = configure_logger("pm.watchers.bug_fix_impl")


class BugFixImplWatcher(BaseWatcher):
    """Picks bug PRs, advances them through auto-sequence, auto-merges on PASS."""

    WATCHER_TYPE = "bug-fix-impl"
    DISPLAY_NAME = "Bug-Fix Implementation Watcher"
    WINDOW_NAME = "bug-fix-impl"
    DEFAULT_INTERVAL = 300  # 5 minutes
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
        from pm_core.prompt_gen import generate_bug_fix_impl_prompt

        try:
            data = store.load(Path(self.pm_root))
            return generate_bug_fix_impl_prompt(
                data, iteration=iteration, loop_id=self.state.loop_id,
                meta_pm_root=self.meta_pm_root,
            )
        except Exception as exc:
            _log.warning("bug_fix_impl_watcher: could not generate prompt: %s", exc)
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
