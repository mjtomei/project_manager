# Implementation Spec: Use Claude Code hooks for verdict and session-end detection

## Summary

Replace polling-based idle/verdict detection with Claude Code hooks. Currently pm polls tmux pane content every 5s (`poll_for_verdict` in `loop_shared.py`, `PaneIdleTracker` in `pane_idle.py`) using MD5 hashing and tail-line scanning to detect turn completion. Claude Code supports lifecycle hooks (`Notification` with `idle_prompt` matcher, `Stop`) that fire the instant Claude finishes a turn or exits — removing the need for stability polls, grace periods, and prompt-text filtering.

## Background: how Claude Code hooks work

Hooks are configured in a `settings.json` file (user-level `~/.claude/settings.json` or project-level `.claude/settings.json`). Each hook runs a shell command when its event fires; the hook receives a JSON payload on stdin including `session_id`, `transcript_path`, `cwd`, and event-specific fields. The two relevant events:

- **`Notification`** with `matcher: "idle_prompt"` — fires when Claude has finished its turn and is waiting at the input prompt. This is the "became idle" signal.
- **`Stop`** — fires when Claude finishes a response. (There is also `SessionEnd` when the CLI exits entirely; spec treats them as two related signals.)

pm already generates and tracks `session_id` for every Claude session it launches (`claude_launcher.build_claude_shell_cmd`, `save_session`), so hook events can be correlated back to pm state by `session_id`.

## Requirements

### R1: Hook receiver script

Add `pm_core/hook_receiver.py` (invokable as `python -m pm_core.hook_receiver <event_type>`) that:
- Reads a JSON payload from stdin (the Claude Code hook event).
- Extracts `session_id`, `cwd`, and the event-specific fields.
- Writes an event record to `~/.pm/hooks/{session_id}.json` atomically (temp + rename).
- The file stores the **latest** event per session as `{"event_type": "...", "timestamp": <epoch>, "matcher": "...", "cwd": "...", "session_id": "..."}`. Older events are overwritten — callers only care about the most recent turn-boundary.
- Exits 0 silently on any error (hook failures must not block Claude).

The script must be lightweight (no pm_core imports beyond `pathlib`/`json`) so it starts fast — Claude blocks on hook execution.

### R2: Hook installation

Add `pm_core/hook_install.py` with `ensure_hooks_installed(target: Path)` that:
- Writes/merges a `.claude/settings.json` containing Notification(idle_prompt) and Stop hooks pointing at `python -m pm_core.hook_receiver`.
- Target is the user's `~/.claude/settings.json` by default (covers all panes/sessions uniformly). Use JSON merge — don't clobber existing user hooks.
- The command in the hook must be resolvable from any pane (use absolute path to the current python interpreter or fall back to `python3 -m pm_core.hook_receiver`).
- Called once at pm startup from a convenient entry point (e.g. `pm_core/cli/tui.py` before TUI launch, and from `cli/session.py` session setup).
- Idempotent — safe to call repeatedly.

### R3: Event-file watcher API (`pm_core/hook_events.py`)

Add a small module exposing:
- `event_path(session_id) -> Path` — returns `~/.pm/hooks/{session_id}.json`.
- `read_event(session_id) -> dict | None` — returns the latest event dict, or None if no file.
- `clear_event(session_id)` — removes the file (used when pm has consumed the event).
- `wait_for_event(session_id, event_types: set[str], timeout: float, tick: float = 0.2, stop_check=None) -> dict | None` — polls the event file's mtime until a matching event appears with a newer timestamp than a provided baseline, or timeout elapses. Returns the event dict or None.
- `hooks_available() -> bool` — returns True if `~/.claude/settings.json` contains the pm hooks (used to choose between hook-driven and polling code paths).

The file-poll tick is fast (200 ms) because it only stats a small file; this is still "polling" but an order of magnitude lighter than pane-capture polling and needs no stability logic.

### R4: Replace polling in `poll_for_verdict` (`pm_core/loop_shared.py:325`)

Rewrite `poll_for_verdict` so that when a `session_id` is supplied and hooks are available:
- Wait (via `wait_for_event`) for an `idle_prompt` Notification newer than when polling started, rather than sleeping in a 5s loop.
- On event receipt: capture pane content **once**, extract a verdict. No stability counter, no grace period.
- If no verdict is found, clear the event and wait for the next idle_prompt (Claude may still be thinking, e.g. about to send tool output then go idle again).
- On `Stop` event or pane-gone: return None.
- **Fallback**: when `session_id` is None or `hooks_available()` is False, keep current polling behavior verbatim (stability polls + grace period). This preserves behavior for:
  - Non-Claude panes (concretizer, verification) that may not be Claude sessions.
  - Environments where `~/.claude/settings.json` can't be written or hooks are disabled.

Add a `session_id: str | None = None` parameter to `poll_for_verdict` and `wait_for_follow_up_verdict`. When hooks are active, `STABILITY_POLLS` is effectively 1.

### R5: Thread hook-aware polling through the callers

Update every call site of `poll_for_verdict` / `wait_for_follow_up_verdict` to pass the `session_id` associated with the pane's Claude process:

| Caller | File:Line | Session source |
|---|---|---|
| Review loop verdict poll | `pm_core/review_loop.py:190` (`_poll_for_verdict`) | `load_session(pm_root, f"review:{pr_id}")` |
| Review loop follow-up | `pm_core/review_loop.py:275` | same |
| QA concretize verdict | `pm_core/qa_loop.py:815` | session for concretize key |
| QA follow-up verdict | `pm_core/qa_loop.py:2101` | scenario-specific session key |
| QA scenario polling | `pm_core/qa_loop.py:1745-1794` (inline `capture_pane`+`extract_verdict_from_content`) | scenario session (see R6) |
| Watcher base verdict poll | `pm_core/watcher_base.py:162` | watcher-specific session key |
| Watcher follow-up | `pm_core/watcher_base.py:180` | same |

For `_poll_tmux_verdicts` in `qa_loop.py` (the inline per-scenario loop starting at line 1606), replace the 5s `time.sleep(_POLL_INTERVAL)` busy loop with a select/wait across all tracked scenario session_ids: on each tick, check each scenario's event file for a new `idle_prompt` event. Only scenarios that just went idle do a pane capture + verdict extraction. Scenarios with no new events are skipped entirely — no capture_pane subprocess.

### R6: Track scenario session_ids in QA loop

`QAScenario` (`pm_core/qa_loop.py`) does not currently store the `session_id` generated when its Claude pane is launched. Add a `session_id: str | None` field and populate it when building the launch command (`_launch_scenarios_in_tmux` / `_launch_scenarios_in_containers`, which call `build_claude_shell_cmd`). The session_id is currently generated inside `build_claude_shell_cmd` when caller passes none — change callers that need to track it to generate the UUID themselves and pass it in (so they retain the reference).

### R7: Replace `PaneIdleTracker` idle detection for Claude panes

`PaneIdleTracker` (`pm_core/pane_idle.py`) is used by the TUI (`tui/app.py:286`, `tui/review_loop_ui.py:667`, `tui/tech_tree.py:532`) to decide when a Claude pane has "become idle" (e.g. to auto-start a review loop). For keys that correspond to panes with a known `session_id`:
- Register the key with both `pane_id` and `session_id` (add `session_id: str | None = None` to `register`).
- `poll(key)` short-circuits: if `read_event(session_id)` returns a fresh `idle_prompt` event newer than the last seen, mark the state idle immediately. On a `Stop` event mark `gone=True`.
- `poll(key)` still runs the hash-based fallback when session_id is None (non-Claude panes or hooks unavailable).
- `content_has_interactive_prompt` (gum/trust prompts) logic is preserved — an idle_prompt event plus a gum menu still means "waiting for user" and should not trigger auto-actions. Callers that currently check `content_has_interactive_prompt` after idle detection keep doing so.

TUI callers (`review_loop_ui.py`, `tech_tree.py`) don't need changes beyond passing `session_id` into `register()`.

### R8: Remove/deprecate no-longer-needed code paths

Once hook-driven paths are primary:
- `STABILITY_POLLS` logic inside `poll_for_verdict` and `wait_for_follow_up_verdict` still runs for the fallback path. Keep `VerdictStabilityTracker` for the TUI merge-verdict flow (`review_loop_ui.py:35`) — that one polls pane content on the TUI timer without a session_id, so stability is still needed.
- `_VERDICT_GRACE_PERIOD` (`review_loop.py:67`, `qa_loop.py:52`) only meaningful for polling fallback. Hook path skips grace entirely because an `idle_prompt` event is a hard "Claude is done" signal.
- `is_prompt_line` / `is_prompt_line_with_neighbors` / `build_prompt_verdict_lines` logic remains necessary — even with hooks, Claude's response may echo prompt text (e.g. when it quotes the prompt back). Keep the prompt-line filter inside `extract_verdict_from_content`.

Do NOT delete fallback code. Hooks can fail (user has a weird settings.json, hook script crash, filesystem permission issue) and the polling path is the safety net.

### R9: Tests

Add `tests/test_hook_events.py`:
- Hook receiver script reads JSON from stdin, writes the expected file.
- `wait_for_event` returns quickly when a new event arrives; returns None on timeout.
- `poll_for_verdict` with hooks returns the instant an `idle_prompt` event appears and a verdict is present in pane content (mock `capture_pane`).
- `poll_for_verdict` fallback path (no session_id) behaves identically to the old behavior.
- Hook installer merges into an existing `settings.json` without losing user hooks, and is idempotent.

## Implicit Requirements

1. **Atomic writes from hook receiver**: The receiver writes from *inside the Claude process's hook-child*, while pm reads from a different process. Write via `tempfile` + `os.rename` (same filesystem) so readers never see partial JSON.

2. **Baseline timestamp per wait**: `wait_for_event(session_id, ..., newer_than=<float>)` must not return an old event left over from a previous turn. Callers capture `time.time()` at the moment they issue the prompt (or at the start of the wait) and pass it as `newer_than`. Hook events carry an epoch timestamp written by the receiver; the watcher filters by `event.timestamp > newer_than`.

3. **Stale event file cleanup**: Event files keyed by session_id never grow unbounded in practice (one file per ever-used Claude session). Add a best-effort sweep in `ensure_hooks_installed`: delete files in `~/.pm/hooks/` older than 7 days. Cheap — directory has maybe dozens of entries.

4. **Settings.json discovery order**: Claude Code reads hooks from (a) `~/.claude/settings.json`, (b) `<project>/.claude/settings.json`, (c) `<project>/.claude/settings.local.json`. Install into `~/.claude/settings.json` so every Claude process pm launches — including container'd ones that mount `~/.claude` — inherits the hooks.

5. **Container support**: When Claude runs inside a container (`_launch_scenarios_in_containers`), the hook command writes to the container's `~/.pm/hooks/`. pm reads from the host's `~/.pm/hooks/`. Existing container setup already bind-mounts `~/.pm` (confirm by reading `pm_core/container.py` — if not, hooks must write to a path that is mounted). If `~/.pm` is not mounted into the container, the hook path for containerized scenarios falls back to polling. Document this in the spec rather than forcing a container change in this PR.

6. **Hook receiver must not require virtualenv activation**: `python -m pm_core.hook_receiver` needs pm_core importable. Safest: use an absolute path to the python interpreter that launched pm (`sys.executable`) captured at install time and baked into settings.json. If the user upgrades their python, they re-run pm which re-installs the hook.

7. **Atomic event-file writes vs concurrent hooks**: A single Claude process fires Notification then Stop in rapid succession. Two hook processes may race. Each writes to `~/.pm/hooks/{session_id}.json`; last writer wins. That's the correct semantics — Stop after Notification is the intended final state.

8. **session_id propagation in `build_claude_shell_cmd`**: Callers that need to track the session before launch must pass it in. `build_claude_shell_cmd` already accepts `session_id=None` and generates internally; change: when `None` is passed, still generate, but make the generated id available to the caller. Cleanest: the caller generates and passes in (`uuid.uuid4()`) rather than relying on the internal generation path.

9. **TUI thread safety**: `PaneIdleTracker.poll` runs on a timer thread. Reading the hook event file is also cheap filesystem I/O — add it inside the existing outside-lock subprocess section.

## Ambiguities

### A1: Hook event storage — single file vs per-event
**Options**: (a) overwrite one `~/.pm/hooks/{session_id}.json` per session, or (b) append per-event files like `~/.pm/hooks/{session_id}-{event}-{ts}.json`.

**Resolution**: (a) single file. Simpler, cheaper, and consumers only care about the latest turn-boundary. The `timestamp` field plus the baseline-timestamp check prevents double-processing a single event.

### A2: How finely to split the Notification matcher
Claude Code's `Notification` event fires for multiple reasons (idle_prompt, waiting_for_tool_permission, etc.). The hook config can either match `idle_prompt` specifically or catch all Notifications and let the receiver filter.

**Resolution**: Install a matcher for `idle_prompt` only. Other Notification reasons are not useful to pm and would cause false verdict captures.

### A3: Fallback detection for existing Claude processes
Claude processes already running when pm starts won't have been launched with these hooks active — but `~/.claude/settings.json` is re-read per session, so the hook fires for them as soon as it's installed. No migration is needed for in-flight sessions beyond: hooks start firing as soon as installed.

**Resolution**: No special migration. Add a log line on install mentioning "hooks now active for all subsequent Claude turns".

### A4: What to do when `session_id` is not knowable (e.g. pm attached to a pane it didn't launch)
A few callers (TUI interactive panes, follow-up prompts in panes created by `pm pr start` before this change) may not have a recorded session_id.

**Resolution**: Fall back to polling for those keys. Add a log line noting "no session_id for key X, using polling fallback".

## Edge Cases

1. **Verdict appears mid-turn, not at idle_prompt**: Claude sometimes prints a verdict line then continues output (rare, but possible). The hook fires at turn end, at which point the verdict is the last meaningful line in the pane — `extract_verdict_from_content` still finds it. No behavior change.

2. **Multiple rapid turns**: User types a quick follow-up; Claude emits another idle_prompt shortly after. `wait_for_event(newer_than=baseline)` picks the first event past the baseline; after consuming it, the caller must update its baseline to the consumed event's timestamp before calling again.

3. **Hook script crash**: Hook command failure leaves no event file update. After a hook-specific timeout (e.g. 60s past the expected turn), fall back to a single polling capture. Simpler resolution: set `wait_for_event` timeout to `_POLL_INTERVAL * 3` (15s) and on timeout fall through to a poll capture. This bounds worst-case latency to the current polling latency.

4. **Scenario pane relaunch**: When a QA scenario window dies and `_relaunch_scenario_window` creates a new one, a new `session_id` is generated. The `QAScenario.session_id` field must be updated; the old event file becomes stale and is ignored (newer_than baseline is reset).

5. **Verification panes**: `_verify_single_scenario` launches its own Claude process with its own session_id. The same hook mechanism applies — verification already uses `poll_for_verdict`, so threading session_id through that path covers it.

6. **Interactive selection menus (gum trust prompts)**: `idle_prompt` fires even when Claude is waiting at a gum-style permission prompt. `content_has_interactive_prompt` check remains — callers that act on idle still need to gate on "no interactive prompt on screen".

7. **pm running outside a git repo / without session tag**: `ensure_hooks_installed` still writes `~/.claude/settings.json` (user-global). It doesn't depend on the session tag or any pm-root discovery.

8. **Multiple pm instances on the same host**: All share `~/.pm/hooks/` and `~/.claude/settings.json`. Hook receiver writes per-session_id files; session_ids are UUIDs so no collision. Installer merges idempotently.

9. **Hook receiver latency**: Every Claude turn pays the cost of spawning python+importing the receiver. Keep the receiver script minimal (no heavy imports) to keep that under ~50 ms.

## Implementation notes (as landed)

- **session_id recovery**: Rather than plumbing session_ids through every
  subprocess boundary, `claude_launcher.session_id_from_transcript(path)`
  derives the session_id from the transcript symlink target filename
  (`<uuid>.jsonl`). review_loop, watcher_base, and qa_loop scenarios all
  use this. Callers without a transcript (concretize pane, planner pane,
  inline `_poll_tmux_verdicts`) fall back to polling unchanged.
- **`_poll_tmux_verdicts` inline loop** (`qa_loop.py:1474`) was left on
  the polling path. Converting it to event-driven select across
  scenarios is a much larger rewrite; the two `poll_for_verdict` call
  sites in QA (concretize + verification) are where hook-driven
  detection is most valuable and both are wired.
- **QA verification** pre-generates a `uuid.uuid4()` session_id and
  passes it to `build_claude_shell_cmd(session_id=...)` so the verifier
  pane is fully hook-aware without needing a transcript.
- **Hooks install at startup** from both `pm session` (session.py) and
  the internal TUI command (tui.py). `ensure_hooks_installed()` is
  idempotent and merges into user-level `~/.claude/settings.json`
  without losing existing hooks.
