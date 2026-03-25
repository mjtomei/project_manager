"""Supervisor watcher: high-effort watcher that monitors and coaches other sessions.

Runs at high effort (Opus-level) and observes other running Claude sessions
(QA, implementation, review) by capturing their tmux pane output.  When it
spots issues, suboptimal approaches, or opportunities, it injects feedback
at the target session's message prompt.

Each supervisor targets a configurable subset of tasks based on a window
name filter pattern.  Multiple supervisors can run concurrently covering
different task subsets.
"""

import json
import re
import sys
import time
from datetime import datetime

# Minimum pane idle time (seconds) before injecting feedback.
# If the pane had activity more recently than this, the session is busy.
_MIN_IDLE_SECONDS = 5

# Regex matching a Claude Code prompt line with no text typed yet.
# Claude Code uses "> " as the input prompt prefix.
_EMPTY_PROMPT_RE = re.compile(r"^\s*>\s*$")

from pm_core.paths import configure_logger
from pm_core.watcher_base import BaseWatcher, WatcherState
from pm_core.loop_shared import match_verdict
from pm_core.supervisor_feedback import FeedbackEntry, log_feedback

_log = configure_logger("pm.watchers.supervisor")

# Windows the supervisor should never observe (infrastructure windows)
_EXCLUDED_WINDOWS = frozenset({
    "tui", "watcher", "supervisor", "repl",
})

# Maximum pane output to capture per target (chars)
_MAX_CAPTURE_CHARS = 8000

# Maximum feedback items per iteration
_MAX_FEEDBACK_PER_ITERATION = 5


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
        # Collected feedback from the latest iteration (parsed from output)
        self._pending_feedback: list[dict] = []

    def should_continue(self, verdict: str) -> bool:
        """Continue on CONTINUE, FEEDBACK_SENT, or NO_ISSUES."""
        return verdict in ("CONTINUE", "FEEDBACK_SENT", "NO_ISSUES")

    # ── Target discovery ──────────────────────────────────────────────

    def discover_targets(self) -> list[dict]:
        """Discover target tmux windows to observe.

        Returns list of dicts with keys: window_name, pane_id, content.
        """
        from pm_core import tmux as tmux_mod
        from pm_core.loop_shared import get_pm_session

        session = get_pm_session()
        if not session:
            _log.warning("supervisor: no PM session found")
            return []

        windows = tmux_mod.list_windows(session)
        targets = []

        for win in windows:
            name = win["name"]

            # Skip infrastructure windows
            if name.lower() in _EXCLUDED_WINDOWS:
                continue
            # Skip windows whose name starts with "supervisor"
            if name.lower().startswith("supervisor"):
                continue

            # Apply target filter if set
            if self.target_filter and self.target_filter not in name:
                continue

            # Get pane content
            panes = tmux_mod.get_pane_indices(session, win["index"])
            if not panes:
                continue

            pane_id = panes[0][0]  # first pane
            content = tmux_mod.capture_pane(pane_id, full_scrollback=False)
            if not content or not content.strip():
                continue

            # Truncate to limit
            if len(content) > _MAX_CAPTURE_CHARS:
                content = content[-_MAX_CAPTURE_CHARS:]

            targets.append({
                "window_name": name,
                "pane_id": pane_id,
                "content": content,
            })

        _log.info("supervisor: discovered %d target(s) (filter=%s)",
                  len(targets), self.target_filter)
        return targets

    # ── BaseWatcher interface ─────────────────────────────────────────

    def generate_prompt(self, iteration: int) -> str:
        """Generate a supervisor prompt with captured target session outputs."""
        targets = self.discover_targets()

        if not targets:
            return self._build_no_targets_prompt(iteration)

        return self._build_supervisor_prompt(iteration, targets)

    def _build_no_targets_prompt(self, iteration: int) -> str:
        return f"""You are a supervisor watcher (iteration {iteration}).

No active target sessions were found to monitor.

Respond with:
NO_ISSUES
"""

    def _build_supervisor_prompt(self, iteration: int,
                                  targets: list[dict]) -> str:
        target_sections = []
        for i, t in enumerate(targets, 1):
            target_sections.append(
                f"### Target {i}: Window '{t['window_name']}'\n"
                f"```\n{t['content']}\n```"
            )

        targets_text = "\n\n".join(target_sections)
        target_names = ", ".join(t["window_name"] for t in targets)

        return f"""You are a high-effort supervisor watcher monitoring {len(targets)} active Claude session(s).

## Your Role
You are an experienced senior engineer observing other Claude Code sessions. Your job is to:
1. Read the captured output from each target session
2. Identify issues, suboptimal approaches, bugs, or missed opportunities
3. Provide targeted, actionable feedback for each session that needs it
4. Be selective — only provide feedback when it adds genuine value

## Iteration
This is supervisor iteration {iteration}. Monitoring: {target_names}

## Captured Session Outputs

{targets_text}

## Instructions

Analyze each target session's output carefully. Look for:
- **Bugs or errors** the session is introducing or missing
- **Suboptimal approaches** where a better strategy exists
- **Missed edge cases** in testing or implementation
- **Architecture concerns** that could cause problems later
- **Wasted effort** on unnecessary work

For each piece of feedback, output a JSON block in this exact format:

```json
{{"target_window": "<window_name>", "observation": "<what you noticed>", "feedback": "<your coaching advice>"}}
```

You may output 0 to {_MAX_FEEDBACK_PER_ITERATION} feedback blocks.

After all feedback blocks (or if there are none), end your response with exactly one of:
- FEEDBACK_SENT — if you provided feedback for any session
- NO_ISSUES — if all sessions look fine
- CONTINUE — if you want to keep observing without sending feedback yet
- INPUT_REQUIRED — if you need human input to proceed

Important: Be concise in your feedback. Each feedback message will be injected into the target session's prompt, so keep it brief and actionable (1-3 sentences).
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
        # Also parse feedback blocks from output
        self._pending_feedback = self._extract_feedback(output)

        lines = output.strip().splitlines()
        for line in reversed(lines[-30:]):
            stripped = line.strip().strip("*").strip()
            verdict = match_verdict(stripped, self.VERDICTS)
            if verdict:
                return verdict
        # Default: if feedback was found, treat as FEEDBACK_SENT
        if self._pending_feedback:
            return "FEEDBACK_SENT"
        return "NO_ISSUES"

    def on_verdict(self, verdict: str, output: str) -> None:
        """After each iteration, inject feedback and log it."""
        if not self._pending_feedback:
            return

        from pm_core import tmux as tmux_mod
        from pm_core.loop_shared import get_pm_session

        session = get_pm_session()
        if not session:
            _log.warning("supervisor: no PM session for feedback injection")
            self._pending_feedback = []
            return

        for fb in self._pending_feedback[:_MAX_FEEDBACK_PER_ITERATION]:
            target_window = fb.get("target_window", "")
            observation = fb.get("observation", "")
            feedback_text = fb.get("feedback", "")

            if not feedback_text:
                continue

            # Find the target pane
            pane_id = self._find_target_pane(session, target_window)
            injected = False

            if pane_id:
                inject_text = f"[SUPERVISOR FEEDBACK] {feedback_text}"
                injected = self._safe_inject(pane_id, inject_text, target_window)

            # Log feedback regardless of injection success
            entry = FeedbackEntry(
                timestamp=datetime.now().isoformat(),
                supervisor_id=self.state.watcher_id,
                target_window=target_window,
                target_pane=pane_id or "",
                observation=observation,
                feedback=feedback_text,
                injected=injected,
            )
            log_feedback(entry)

        self._pending_feedback = []

    # ── Helpers ────────────────────────────────────────────────────────

    def _safe_inject(
        self,
        pane_id: str,
        text: str,
        window_name: str = "",
        min_idle_seconds: float = _MIN_IDLE_SECONDS,
    ) -> bool:
        """Inject feedback into a pane only when it is idle at a clean prompt.

        Two guards run before injecting:

        1. **Activity age** — the pane must have been idle for at least
           *min_idle_seconds*.  If the session had recent output or keystrokes,
           it is busy and injection would clobber in-progress work.

        2. **Empty prompt** — the last visible line of the pane must look like
           a clean Claude Code prompt (``> `` with nothing after it).  If the
           user or another process has already typed text, injecting would
           corrupt the partial input.

        Returns True if the feedback was sent, False otherwise.
        """
        from pm_core import tmux as tmux_mod

        # Guard 1: idle time
        age = tmux_mod.get_pane_activity_age(pane_id)
        if age is None or age < min_idle_seconds:
            _log.info(
                "supervisor: skipping injection into %s (pane %s): "
                "activity age=%.1fs < %.1fs",
                window_name, pane_id, age if age is not None else -1,
                min_idle_seconds,
            )
            return False

        # Guard 2: no text already typed into the prompt
        content = tmux_mod.capture_pane(pane_id, full_scrollback=False)
        last_line = ""
        for line in reversed(content.splitlines()):
            if line.strip():
                last_line = line
                break
        if not _EMPTY_PROMPT_RE.match(last_line):
            _log.info(
                "supervisor: skipping injection into %s (pane %s): "
                "prompt is not empty (last_line=%r)",
                window_name, pane_id, last_line[:60],
            )
            return False

        try:
            tmux_mod.send_keys(pane_id, text)
            _log.info("supervisor: injected feedback into %s (pane %s)",
                      window_name, pane_id)
            return True
        except Exception as e:
            _log.warning("supervisor: failed to inject into %s: %s",
                         window_name, e)
            return False

    def _find_target_pane(self, session: str, window_name: str) -> str | None:
        """Find the first pane ID for a window by name."""
        from pm_core import tmux as tmux_mod

        win = tmux_mod.find_window_by_name(session, window_name)
        if not win:
            return None
        panes = tmux_mod.get_pane_indices(session, win["index"])
        return panes[0][0] if panes else None

    @staticmethod
    def _extract_feedback(output: str) -> list[dict]:
        """Extract JSON feedback blocks from Claude's output."""
        feedback = []
        # Match any bare JSON object (no nested braces).  Key-ordering is NOT
        # enforced here — we rely on json.loads + the explicit key check below.
        json_pattern = re.compile(r'\{[^{}]+\}', re.DOTALL)

        for match in json_pattern.finditer(output):
            try:
                data = json.loads(match.group())
                if all(k in data for k in ("target_window", "observation", "feedback")):
                    feedback.append(data)
            except json.JSONDecodeError:
                continue

        _log.info("supervisor: extracted %d feedback block(s)", len(feedback))
        return feedback
