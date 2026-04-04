"""Supervisor watcher: high-effort watcher that monitors and coaches other sessions.

Runs at high effort (Opus-level) and observes other running Claude sessions
(QA, implementation, review) by capturing their tmux pane output.  When it
spots issues, suboptimal approaches, or opportunities, it injects feedback
at the target session's message prompt.

The supervisor prompt instructs Claude to discover targets, analyze their
output, and inject feedback — all via tmux commands.  This gives Claude full
freedom to decide what to look at and how to respond, rather than constraining
it with hardcoded filtering or capture logic.
"""

import sys

from pm_core.paths import configure_logger
from pm_core.watcher_base import BaseWatcher, WatcherState
from pm_core.loop_shared import match_verdict, get_pm_session
from pm_core.supervisor_feedback import SUPERVISOR_LOG_DIR

_log = configure_logger("pm.watchers.supervisor")


class SupervisorWatcher(BaseWatcher):
    """High-effort watcher that monitors and coaches other sessions."""

    WATCHER_TYPE = "supervisor"
    DISPLAY_NAME = "Supervisor Watcher"
    WINDOW_NAME = "supervisor"
    DEFAULT_INTERVAL = 180  # 3 minutes between iterations
    VERDICTS = ("CONTINUE", "FEEDBACK_SENT", "NO_ISSUES", "INPUT_REQUIRED")
    KEYWORDS = ("CONTINUE", "FEEDBACK_SENT", "NO_ISSUES", "INPUT_REQUIRED")

    # Polling: supervisors run longer per iteration
    POLL_INTERVAL = 5
    TICK_INTERVAL = 1
    VERDICT_GRACE_PERIOD = 45  # give Claude more time to analyze

    def __init__(
        self,
        pm_root: str,
        target_filter: str | None = None,
        state: WatcherState | None = None,
    ):
        super().__init__(pm_root, state=state)
        self.target_filter = target_filter
        # Use a per-instance window name so multiple supervisors don't clobber
        # each other.  The watcher_id is already unique (e.g. "supervisor-ab12").
        self.WINDOW_NAME = self.state.watcher_id

    def should_continue(self, verdict: str) -> bool:
        """Continue on CONTINUE, FEEDBACK_SENT, or NO_ISSUES."""
        return verdict in ("CONTINUE", "FEEDBACK_SENT", "NO_ISSUES")

    # ── BaseWatcher interface ─────────────────────────────────────────

    def generate_prompt(self, iteration: int) -> str:
        """Generate a prompt that instructs Claude to discover and monitor targets."""
        session = get_pm_session()
        session_flag = f" -t {session}" if session else ""

        target_clause = ""
        if self.target_filter:
            target_clause = (
                f"\n**Target filter:** Focus on windows whose name contains "
                f"'{self.target_filter}'. Skip others unless they seem relevant.\n"
            )

        log_dir = str(SUPERVISOR_LOG_DIR)
        log_path = str(SUPERVISOR_LOG_DIR / f"{self.state.watcher_id}.jsonl")

        return f"""You are a high-effort supervisor watcher (iteration {iteration}, id: {self.state.watcher_id}).

## Your Role
You are an experienced senior engineer observing other Claude Code sessions running in this tmux session. Your job is to:
1. Discover active sessions by listing tmux windows
2. Read their recent output to understand what they're working on
3. Identify issues, suboptimal approaches, bugs, or missed opportunities
4. Provide targeted, actionable feedback when warranted
5. Be selective — only intervene when it adds genuine value
{target_clause}
## How to Discover Targets
Run `tmux list-windows{session_flag}` to see available windows. Each window typically runs a Claude Code session working on a task. Use your judgment about which windows are worth monitoring — skip infrastructure windows (like the TUI, watcher, or REPL) and focus on sessions doing implementation, review, or QA work. Skip any window whose name starts with "supervisor" (those are other supervisors like you).

## How to Read Session Output
Use `tmux capture-pane -t <pane_id> -p` to read a session's recent output. Focus on the most recent activity to understand what they're currently doing.

## How to Provide Feedback
When you identify an issue worth flagging, inject feedback into the target session's prompt using:
```
tmux send-keys -t <pane_id> '[SUPERVISOR FEEDBACK] <your feedback>'
```

Before injecting, verify that the session appears idle (at a prompt, not mid-output). Keep feedback concise and actionable (1-3 sentences).

## Feedback Logging
Log every piece of feedback to: {log_path}
Create the directory first if needed: `mkdir -p {log_dir}`

Each line should be a JSON object:
```
{{"timestamp": "<ISO>", "supervisor_id": "{self.state.watcher_id}", "target_window": "<name>", "target_pane": "<pane_id>", "observation": "<what you noticed>", "feedback": "<what you said>", "injected": true/false}}
```

## Verdict
When done with this iteration, end your response with exactly one of:
- FEEDBACK_SENT — you provided feedback to one or more sessions
- NO_ISSUES — all sessions look fine, no intervention needed
- CONTINUE — you want to keep observing (will trigger another iteration)
- INPUT_REQUIRED — you need human input to proceed
"""

    def build_launch_cmd(self, iteration: int,
                         transcript: str | None = None) -> list[str]:
        """Build the CLI command to launch the supervisor tmux window."""
        cmd = [
            sys.executable, "-m", "pm_core.wrapper",
            "watcher", "supervisor-iter",
            "--iteration", str(iteration),
            "--window-name", self.WINDOW_NAME,
        ]
        if self.state.loop_id:
            cmd.extend(["--loop-id", self.state.loop_id])
        if transcript:
            cmd.extend(["--transcript", transcript])
        if self.target_filter:
            cmd.extend(["--target", self.target_filter])
        return cmd

    def parse_verdict(self, output: str) -> str:
        """Extract a supervisor verdict from Claude output."""
        lines = output.strip().splitlines()
        for line in reversed(lines[-30:]):
            stripped = line.strip().strip("*").strip()
            verdict = match_verdict(stripped, self.VERDICTS)
            if verdict:
                return verdict
        return "NO_ISSUES"

    def on_verdict(self, verdict: str, output: str) -> None:
        """Log iteration completion. Claude handles feedback injection directly."""
        _log.info("supervisor[%s]: iteration complete, verdict=%s",
                  self.state.watcher_id, verdict)
