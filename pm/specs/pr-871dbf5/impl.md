# Implementation Spec: pr-871dbf5 — Supervisor Watcher

## 1. Requirements (grounded in codebase)

### R1: SupervisorWatcher as a BaseWatcher subclass
**File:** `pm_core/watchers/supervisor_watcher.py`
- `SupervisorWatcher` extends `BaseWatcher` (from `pm_core/watcher_base.py`) with `WATCHER_TYPE = "supervisor"`, `DISPLAY_NAME = "Supervisor Watcher"`, `WINDOW_NAME = "supervisor"`, `DEFAULT_INTERVAL = 180`.
- Uses the standard `generate_prompt` / `parse_verdict` / `on_verdict` / `build_launch_cmd` hooks.
- Registered in `pm_core/watchers/__init__.py` under `WATCHER_REGISTRY["supervisor"]`.

### R2: Prompt-driven target discovery and feedback
- `generate_prompt()` produces instructions for Claude to discover targets, analyze their output, and inject feedback — all via tmux commands.
- Claude uses `tmux list-windows` to find sessions, `tmux capture-pane` to read their output, and `tmux send-keys` to inject feedback.
- The prompt includes the PM session name (if available), optional target filter, supervisor ID, and feedback log path.
- No hardcoded window exclusion lists, capture limits, or injection logic — Claude uses its own judgment.

### R3: High-effort execution
- `pm_core/model_config.py`: `DEFAULT_SESSION_EFFORT["supervisor"] = "high"` and `_FALLBACK_TYPES["supervisor"] = "watcher"`.
- `_create_supervisor_window()` in `pm_core/cli/watcher.py` calls `resolve_model_and_provider("supervisor", ...)` and sets `effort = "high"` if not already configured.

### R4: Configurable target filter and count
- `SupervisorWatcher.__init__(pm_root, target_filter=None)` accepts an optional filter.
- CLI: `pm watcher supervisor start [--target FILTER] [--count N] [--wait SECONDS]`.
- `--count > 1` is currently blocked with an explicit error (parallel execution not yet implemented).
- When a target filter is set, the prompt tells Claude to focus on windows matching that filter.

### R5: Persistent feedback logging
- `pm_core/supervisor_feedback.py`: `FeedbackEntry` dataclass with `timestamp`, `supervisor_id`, `target_window`, `target_pane`, `observation`, `feedback`, `injected`.
- `log_feedback(entry)` appends JSONL to `~/.pm/logs/supervisor/<supervisor-id>.jsonl`.
- `read_feedback_log(supervisor_id, target_filter, limit)` reads back entries.
- Claude is instructed to write log entries directly via bash; the same format is used by the `pm watcher supervisor log` CLI command.

### R6: pm watcher supervisor log command
- `pm watcher supervisor log [--target FILTER] [--limit N]` calls `read_feedback_log` and `format_feedback_log`.
- `format_feedback_log` displays timestamp, supervisor id, target window, observation, feedback, and injection status.

### R7: Per-instance unique window names
- `self.WINDOW_NAME = self.state.watcher_id` (e.g. `"supervisor-ab12"`) set in `__init__` so multiple concurrent supervisors don't clobber each other's tmux windows.
- `build_launch_cmd()` passes `--window-name` to `supervisor-iter`.

### R8: Internal supervisor-iter subcommand
- `pm watcher supervisor-iter --iteration N --window-name NAME [--loop-id ID] [--transcript PATH] [--target FILTER]` (hidden) creates the per-iteration tmux window.
- `_create_supervisor_window()` handles kill-and-recreate of the named window with session-switch preservation.

## 2. Implicit Requirements

- **tmux availability**: All supervisor operations require `tmux.has_tmux()` and `tmux.in_tmux()`. If absent, commands exit with an error message.
- **PM session**: `get_pm_session()` is called in `generate_prompt()` to include the session flag in tmux commands. If absent, the prompt omits the `-t` flag and Claude uses the current session.
- **Log directory creation**: Claude is instructed to `mkdir -p` the log directory before writing.
- **Verdict fallback**: If Claude's output contains no explicit verdict keyword, `parse_verdict()` returns `"NO_ISSUES"`.

## 3. Ambiguities and Resolutions

### A1: How does the supervisor discover and interact with targets?
**Question:** Should target discovery be hardcoded in Python or delegated to Claude?
**Resolution (implemented):** Fully delegated to Claude via prompt instructions. The prompt tells Claude how to use tmux commands to list windows, capture pane output, and inject feedback. This gives Claude maximum freedom to handle each session's state appropriately.

### A2: Logging "whether the target acted on feedback"
The task description mentioned logging this, but it doesn't need explicit tracking — if the supervisor injects feedback, the target session's subsequent behavior is visible in the supervisor's own conversation context on the next iteration. The log records `injected` (whether `send_keys` succeeded) which is sufficient for post-hoc review.

### A3: Multiple supervisors — concurrent vs. sequential?
**Question:** The task says "Multiple supervisors can run concurrently."
**Resolution (implemented):** `--count > 1` is blocked with an explicit error noting that parallel execution (threads/subprocesses) is not yet implemented. Users can launch multiple supervisors manually in separate terminals with different `--target` filters.

### A4: What is the supervisor's model (Opus vs. generic "high effort")?
**Question:** Task says "high effort (Opus-level)" — does this mean literally Opus or just high effort on whatever model?
**Resolution (implemented):** `DEFAULT_SESSION_EFFORT["supervisor"] = "high"` — uses the same model as watcher (via `_FALLBACK_TYPES["supervisor"] = "watcher"`) at high effort, not hardcoded to Opus. Users can override via `project.yaml` `model_config.session_models.supervisor`.

### A5: Rebalancing when sessions start/stop
Not a special concern. Claude discovers targets fresh on every iteration via tmux commands, so new windows are picked up and gone windows are dropped naturally.

### A6: Safety checks for feedback injection
**Question:** Should idle-time and empty-prompt checks be hardcoded in Python or left to Claude?
**Resolution (implemented):** Left to Claude. The prompt instructs Claude to verify the session appears idle before injecting. Claude can use its judgment about the current state rather than relying on rigid numeric thresholds.

## 4. Edge Cases

### E1: Supervisor targets another supervisor's window
Handled via prompt: Claude is instructed to skip windows whose name starts with "supervisor".

### E2: Target window disappears between discovery and injection
Claude handles this naturally — if `send_keys` fails, it can note the failure and move on.

### E3: Multiple supervisors sharing a name conflict
The per-instance `WINDOW_NAME = state.watcher_id` (e.g. `supervisor-ab12`) avoids window name collisions.

### E4: No active sessions to monitor
Claude outputs `NO_ISSUES` when there's nothing to monitor.

### E5: Log file format
Claude writes JSONL entries directly. `read_feedback_log()` catches `json.JSONDecodeError` and `TypeError` per line and skips bad entries, handling any formatting inconsistencies.

### E6: PM session unavailable
If `get_pm_session()` returns None, the prompt omits the session flag. Claude can still use tmux commands targeting the current session.
