# QA Spec: pr-871dbf5 — Supervisor Watcher

## Summary

This PR adds a **supervisor watcher** — a high-effort (Opus-level) watcher that
monitors other running Claude sessions via tmux pane capture, identifies issues
or suboptimal approaches, and injects actionable feedback at the target
session's Claude Code prompt.

The implementation spans 8 files:
- `pm_core/watchers/supervisor_watcher.py` — core `SupervisorWatcher` class
- `pm_core/supervisor_feedback.py` — feedback logging (JSONL)
- `pm_core/cli/watcher.py` — CLI subcommands (`supervisor start/stop/log`, `supervisor-iter`)
- `pm_core/model_config.py` — "supervisor" session type, fallback to "watcher", default "high" effort
- `pm_core/tmux.py` — new `get_pane_activity_age()` helper
- `pm_core/tui/watcher_ui.py` — verdict icons, TUI integration stub
- `pm_core/watchers/__init__.py` — registry entry
- `tests/test_supervisor_watcher.py` — unit tests

---

## 1. Requirements

### R1: Target Discovery
- `discover_targets()` lists tmux windows in the PM session
- Excludes infrastructure windows: "tui", "watcher", "repl", and any starting with "supervisor"
- Applies optional `target_filter` (substring match on window name)
- Captures the first pane's content, truncated to `_MAX_CAPTURE_CHARS` (8000 chars)
- Skips windows with no panes or empty pane content

### R2: Prompt Generation
- `generate_prompt(iteration)` produces a prompt with all target outputs embedded
- No-targets case returns a simple prompt that expects `NO_ISSUES`
- Targets case includes role description, captured outputs, analysis instructions, and JSON feedback format

### R3: Verdict Parsing
- `parse_verdict(output)` scans the last 30 lines for CONTINUE, FEEDBACK_SENT, NO_ISSUES, or INPUT_REQUIRED
- If no explicit verdict but JSON feedback blocks found, returns FEEDBACK_SENT
- If no verdict and no feedback, returns NO_ISSUES
- Also extracts feedback via `_extract_feedback()` into `_pending_feedback`

### R4: Feedback Extraction
- `_extract_feedback(output)` uses regex `\{[^{}]+\}` to find JSON objects
- Validates each has keys: target_window, observation, feedback
- Skips invalid JSON and objects missing required keys
- Key ordering in JSON is irrelevant

### R5: Feedback Injection (on_verdict)
- Iterates `_pending_feedback` up to `_MAX_FEEDBACK_PER_ITERATION` (5) items
- Finds target pane via `_find_target_pane(session, window_name)`
- Injects via `_safe_inject()` which checks:
  - Pane idle time >= `_MIN_IDLE_SECONDS` (5s) via `get_pane_activity_age()`
  - Last non-blank line matches `_EMPTY_PROMPT_RE` (`^\s*>\s*$`)
- Prefixes feedback with `[SUPERVISOR FEEDBACK]`
- Logs every feedback entry (injected or not) to JSONL
- Clears `_pending_feedback` after processing
- When PM session is unavailable, logs feedback without injection (injected=False)

### R6: Feedback Logging
- `log_feedback(entry)` appends to `~/.pm/logs/supervisor/<supervisor-id>.jsonl`
- Each entry: timestamp, supervisor_id, target_window, target_pane, observation, feedback, injected
- `read_feedback_log()` supports supervisor_id filter, target_filter, and limit
- `format_feedback_log()` produces human-readable output

### R7: CLI Commands
- `pm watcher supervisor start [--target <filter>] [--count N] [--wait N]`
  - Requires tmux
  - `--count > 1` currently errors with a message explaining limitation
  - Creates transcript directory, runs blocking `run_sync()` loop
- `pm watcher supervisor stop` — directs user to Ctrl+C or TUI
- `pm watcher supervisor log [--target <filter>] [--limit N]` — reads and formats feedback logs
- `pm watcher supervisor-iter` (hidden, internal) — creates a single supervisor tmux window

### R8: Model Configuration
- "supervisor" added to `SESSION_TYPES`
- Falls back to "watcher" in `_FALLBACK_TYPES`
- Default effort = "high" in `DEFAULT_SESSION_EFFORT`

### R9: Watcher Registry
- `SupervisorWatcher` registered in `WATCHER_REGISTRY` as "supervisor"
- Discoverable via `get_watcher_class("supervisor")` and `list_watcher_types()`

### R10: Per-Instance Window Names
- Each `SupervisorWatcher` instance sets `self.WINDOW_NAME = self.state.watcher_id`
- Prevents window name collisions when multiple supervisors run concurrently
- `build_launch_cmd()` passes `--window-name` to the internal command

### R11: TUI Integration
- New verdict icons: CONTINUE (green), FEEDBACK_SENT (cyan), NO_ISSUES (green)
- `start_watcher()` passes `target_filter` kwarg for supervisor type

---

## 2. Setup

### Test Environment
- Python 3.10+ with pytest
- The project's existing test suite runs with `pytest tests/test_supervisor_watcher.py`
- All tmux interactions are mocked in unit tests (no real tmux needed)
- Feedback log tests use `tmp_path` fixture for isolated filesystem

### For Integration/Manual Testing
- Requires tmux session with a PM project loaded
- At least one non-infrastructure tmux window running a Claude session
- The `pm` CLI installed and functional

---

## 3. Edge Cases

### EC1: No Active Sessions
- When no target windows exist, prompt should instruct NO_ISSUES
- `on_verdict` should be a no-op when `_pending_feedback` is empty

### EC2: All Windows Excluded
- If every window is infrastructure (tui, watcher, repl, supervisor-*), targets = []

### EC3: Empty Pane Content
- Panes with empty/whitespace-only content are skipped

### EC4: Content Truncation
- Pane content exceeding 8000 chars is truncated from the start (keeps the tail)

### EC5: Malformed JSON in Claude Output
- Invalid JSON objects are silently skipped
- JSON objects missing required keys are silently skipped

### EC6: Injection Safety Guards
- Pane active more recently than 5 seconds: skip injection
- Activity age unknown (None): skip injection
- Prompt has text already typed: skip injection
- `send_keys` raises exception: return False, don't crash

### EC7: PM Session Unavailable During Injection
- Feedback is logged with `injected=False`, `_pending_feedback` is cleared

### EC8: Multiple Supervisors
- `--count > 1` is rejected with a clear error message
- Each instance gets a unique window name from `watcher_id`

### EC9: Feedback Rate Limiting
- At most 5 feedback items per iteration (`_MAX_FEEDBACK_PER_ITERATION`)

### EC10: Feedback with Empty Text
- Feedback blocks where `feedback` key is empty string are skipped (not injected, not logged)

### EC11: read_feedback_log with Missing Directory
- Returns empty list when `~/.pm/logs/supervisor/` doesn't exist

### EC12: Window Name Filter Case Sensitivity
- `_EXCLUDED_WINDOWS` check uses `.lower()` — case insensitive
- `target_filter` match is case-sensitive substring check

---

## 4. Pass/Fail Criteria

### Pass
- All existing unit tests in `tests/test_supervisor_watcher.py` pass
- Target discovery correctly filters infrastructure and applies target_filter
- Verdict parsing handles all verdict types and fallback logic
- Feedback extraction handles valid, invalid, and out-of-order JSON
- Safe injection respects idle time and empty prompt guards
- Feedback is logged to JSONL regardless of injection success
- CLI commands parse arguments correctly and reject invalid inputs
- Model config resolves supervisor to high effort by default
- Multiple supervisor instances have unique window names

### Fail
- Any unit test failure
- Feedback injected into a busy pane (idle < 5s) or pane with typed text
- Feedback lost (not logged) when injection fails
- `_pending_feedback` not cleared after `on_verdict`
- Window name collision between supervisor instances
- `--count > 1` silently succeeds or crashes instead of clean error

---

## 5. Ambiguities

### A1: send_keys Does Not Press Enter
**Observation:** `_safe_inject` calls `tmux_mod.send_keys(pane_id, text)` but
does not append Enter. This means the injected text appears in the prompt buffer
but is not submitted automatically.
**Resolution:** This is intentional — the target session's Claude Code will see
the text at its next prompt read. The supervisor injects *into* the prompt, not
as a submitted message. The target agent picks it up when it next reads input.

### A2: Supervisor Targets Case Sensitivity
**Observation:** `_EXCLUDED_WINDOWS` uses `.lower()` for case-insensitive
exclusion, but `target_filter` is a plain `in` check (case-sensitive).
**Resolution:** This is consistent with how window names are typically
lowercase in the PM system. The case-insensitive exclusion is defensive;
the case-sensitive filter matches exact naming conventions.

### A3: --count > 1 Not Implemented
**Observation:** The `--count` option exists but errors for values > 1.
**Resolution:** This is explicitly documented in the error message and code
comments as a TODO. The infrastructure (unique window names) is in place for
future multi-supervisor support.

### A4: Feedback Ordering in parse_verdict
**Observation:** `parse_verdict` both extracts feedback AND determines the
verdict as a side effect.
**Resolution:** This is by design — the verdict parsing needs to know whether
feedback was extracted to determine the fallback verdict (FEEDBACK_SENT vs
NO_ISSUES).

### A5: No Deduplication of Feedback
**Observation:** If a supervisor sends the same feedback in consecutive
iterations, there's no dedup.
**Resolution:** Acceptable — the supervisor prompt changes each iteration
(different captured content), and the idle/prompt guards prevent injection
into busy sessions anyway.

---

## 6. Mocks

### Mock: tmux Session and Windows
**Contract:** Simulates a PM tmux session with configurable windows and panes.
**Scripted Responses:**
- `get_pm_session()` → returns `"test-session"` or `None`
- `list_windows(session)` → returns list of `{"id": "@N", "index": "N", "name": "<name>"}` dicts
- `get_pane_indices(session, index)` → returns `[("%N", 0)]` tuples
- `capture_pane(pane_id)` → returns configurable string content
- `find_window_by_name(session, name)` → returns window dict or `None`
- `send_keys(pane_id, text)` → no-op or raises exception
- `get_pane_activity_age(pane_id)` → returns float (seconds) or `None`
**What Remains Unmocked:** The `BaseWatcher.run_sync()` loop engine is not
exercised in unit tests — only the individual methods are tested.

### Mock: Feedback Logging
**Contract:** Simulates the JSONL logging filesystem.
**Scripted Responses:**
- `log_feedback(entry)` → mock that records calls for assertion
- For `read_feedback_log` tests, use `tmp_path` with real filesystem writes
**What Remains Unmocked:** Actual JSONL file I/O is tested with real tmp dirs.

### Mock: Model Resolution
**Contract:** Validates supervisor session type resolves correctly.
**Scripted Responses:**
- `get_global_setting_value()` → returns `None` (no global overrides)
- Environment variables PM_EFFORT, PM_MODEL cleared
**What Remains Unmocked:** `resolve_model_and_provider()` runs with real logic.
