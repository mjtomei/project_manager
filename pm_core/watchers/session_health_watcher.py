"""Session health watcher.

Monitors all Claude sessions in the pm tmux session for stuck/dead
states (API errors, 500s, usage limits, OOM, output stalls) and applies
recovery actions (nudge, restart, or wait for retry-after) within a
retry-count limit. Escalates via INPUT_REQUIRED when recovery has been
exhausted.

Inherits the shared loop engine from ``BaseWatcher``; only customises
prompt generation, launch command, and verdict parsing — same shape as
``discovery_supervisor.py``.
"""

import sys

from pm_core.paths import configure_logger
from pm_core.watcher_base import BaseWatcher, WatcherState
from pm_core.loop_shared import match_verdict

_log = configure_logger("pm.watchers.session_health")


class SessionHealthWatcher(BaseWatcher):
    """Detect and recover stuck or dead Claude sessions."""

    WATCHER_TYPE = "session-health"
    DISPLAY_NAME = "Session Health Watcher"
    WINDOW_NAME = "session-health"
    DEFAULT_INTERVAL = 60  # sessions can stall fast; tick frequently
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
        from pm_core.prompt_gen import generate_session_health_prompt

        try:
            data = store.load(Path(self.pm_root))
            return generate_session_health_prompt(
                data, iteration=iteration, loop_id=self.state.loop_id,
                meta_pm_root=self.meta_pm_root,
            )
        except Exception as exc:
            _log.warning("session_health: could not generate prompt: %s", exc)
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
