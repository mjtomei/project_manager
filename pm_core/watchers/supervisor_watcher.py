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
You are a senior engineer reviewing the work of other Claude Code sessions running in this tmux session. Unlike a code reviewer who only reads diffs, you have full access to the codebase and should actively investigate before forming opinions. Your workflow:

1. Discover active sessions by listing tmux windows
2. Read their recent output to understand what they're working on and which files they're touching
3. **Investigate the actual codebase** — read the files being changed, check git diffs, look at specs and tests, understand the broader context
4. Only after investigating, decide whether the session's approach has real problems
5. If it does, provide specific, grounded feedback citing what you found in the code
{target_clause}
## How to Discover Targets
Run `tmux list-windows{session_flag}` to see available windows. Each window typically runs a Claude Code session working on a task. Skip infrastructure windows (TUI, watcher, REPL) and any window whose name starts with "supervisor" (those are other supervisors like you). Focus on sessions doing implementation, review, or QA work.

## How to Understand What a Session is Doing
Use `tmux capture-pane -t <pane_id> -p` to read a session's recent output. From this, identify:
- Which files they're editing or reading
- What task or PR they're working on
- Whether they seem stuck, confused, or headed in a wrong direction

## How to Investigate (the critical step)
Before giving any feedback, do your own research. You have full shell access — use it:
- **Read the files** the session is working on (`cat`, `head`, `less`)
- **Check git state** — `git diff`, `git log --oneline -10`, `git diff --stat` in their workdir
- **Read the spec or task description** if one exists (check `pm/specs/` or the PR description)
- **Read related code** — if they're changing a function, read its callers and tests
- **Run quick checks** — does the code parse? Do the tests still reference the right things?

The goal is to catch things a lower-effort session might miss: using a deprecated API when a newer one exists nearby, duplicating logic that already lives in a helper, misunderstanding a spec requirement, breaking an invariant that's not covered by tests, or missing an edge case visible from reading the broader context.

## When to Give Feedback
Only intervene when you've found something concrete and can cite evidence from the codebase. Good reasons:
- "You're reimplementing X, but `utils.py:45` already has `do_thing()` which does this"
- "The spec says Y but your implementation does Z — see `pm/specs/pr-abc/impl.md` section 3"
- "This change breaks the contract that `caller.py:120` depends on"
- "`test_foo.py` still asserts the old behavior — it will fail"

Bad reasons (do NOT give feedback like this):
- Vague style preferences with no functional impact
- Suggestions to add error handling "just in case"
- Restating what the session is already doing
- Opinions not grounded in something you actually read in the code

## How to Provide Feedback
When you have something worth flagging, inject it into the target session's prompt:
```
tmux send-keys -t <pane_id> '[SUPERVISOR FEEDBACK] <your feedback>'
```

Before injecting, verify the session appears idle (at a prompt, not mid-output). Keep feedback concise — state what you found, where you found it, and what the implication is (2-4 sentences max).

## Feedback Logging
Log every piece of feedback to: {log_path}
Create the directory first if needed: `mkdir -p {log_dir}`

Each line should be a JSON object:
```
{{"timestamp": "<ISO>", "supervisor_id": "{self.state.watcher_id}", "target_window": "<name>", "target_pane": "<pane_id>", "observation": "<what you noticed>", "feedback": "<what you said>", "injected": true/false}}
```

## Verdict
When done with this iteration, end your response with exactly one of:
- FEEDBACK_SENT — you investigated and provided feedback to one or more sessions
- NO_ISSUES — you investigated and everything looks solid
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
