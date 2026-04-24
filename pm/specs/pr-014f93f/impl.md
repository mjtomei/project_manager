# Implementation Spec: Use Claude Code hooks for verdict and session-end detection

## Summary

Replace polling-based idle/verdict detection with Claude Code hooks. Previously pm polled tmux pane content every 5s (`poll_for_verdict` in `loop_shared.py`, `PaneIdleTracker` in `pane_idle.py`) using MD5 hashing and tail-line scanning to detect turn completion. Claude Code supports lifecycle hooks (`Notification` with `idle_prompt` matcher, `Stop`) that fire the instant Claude finishes a turn or exits — removing the need for stability polls, grace periods, and prompt-text filtering.

**Hook-driven detection is mandatory.** There is no polling fallback in the main loop paths (review, watcher, QA concretize/planner/scenarios/verification). Callers that cannot supply a Claude `session_id` cannot use `poll_for_verdict` or `wait_for_follow_up_verdict` — they either acquire one (via the transcript symlink or by pre-generating and passing one to `build_claude_shell_cmd`) or use one of the remaining idle-only helpers (`PaneIdleTracker` hash fallback, `VerdictStabilityTracker` on the TUI merge-verdict timer).

## Background: how Claude Code hooks work

Hooks are configured in a `settings.json` file (user-level `~/.claude/settings.json` or project-level `.claude/settings.json`). Each hook runs a shell command when its event fires; the hook receives a JSON payload on stdin including `session_id`, `transcript_path`, `cwd`, and event-specific fields. The two relevant events:

- **`Notification`** with `matcher: "idle_prompt"` — fires when Claude has finished its turn and is waiting at the input prompt. This is the "became idle" signal.
- **`Stop`** — fires when Claude finishes a response.

pm obtains a `session_id` for every Claude session it launches. Two routes:

1. When `build_claude_shell_cmd(transcript=...)` is called, it generates a UUID, creates a symlink `transcript → ~/.claude/projects/<mangled>/<uuid>.jsonl`, and writes the symlink. `claude_launcher.session_id_from_transcript(path)` recovers the UUID from the symlink target, avoiding plumbing `session_id` through every subprocess boundary.
2. Callers that do not use a transcript pre-generate `uuid.uuid4()` and pass it as `build_claude_shell_cmd(session_id=...)` so they retain the reference.

## Requirements

### R1: Hook receiver script

`pm_core/hook_receiver.py` (invokable as `python -m pm_core.hook_receiver <event_type>`):

- Reads a JSON payload from stdin (the Claude Code hook event).
- Extracts `session_id`, `cwd`, and event-specific fields.
- Derives a `session_tag` from `cwd` via `pm_core.paths.get_session_tag(start_path=cwd, use_github_name=False)`. Falls back to the literal `"_notag"` when no git repo is found.
- Writes an event record to `~/.pm/hooks/{session_tag}/{session_id}.json` atomically (tempfile in the same directory + `os.replace`).
- The file stores the **latest** event per session as `{"event_type": "...", "timestamp": <epoch>, "session_id": "...", "session_tag": "...", "matcher": "...", "cwd": "..."}`. Older events are overwritten — callers only care about the most recent turn-boundary.
- Exits 0 silently on any error (hook failures must not block Claude).

Using `pm_core.paths.get_session_tag` adds an import cost (~50–100 ms) but is the single source of truth for session-tag computation, so host-side readers and container-side writers agree on the path even when the receiver runs inside a container.

### R2: Hook installation

`pm_core/hook_install.py`:

- `ensure_hooks_installed(settings_path=None)` writes Notification(`idle_prompt`) and `Stop` hooks into `~/.claude/settings.json`, pointing at `{sys.executable} -m pm_core.hook_receiver <event_type>`.
- The current interpreter path (`sys.executable`) is baked in at install time so the hook is self-contained; re-running the installer updates the path if the user upgraded python.
- **No clobbering**: before writing, the installer calls `_detect_foreign_hooks(existing_hooks)`. If `~/.claude/settings.json` already contains any Notification(`idle_prompt`) or `Stop` hook that does not reference `pm_core.hook_receiver`, the installer raises `HookConflictError` with a message listing the offending entries. The user must remove or migrate them before pm can run.
- Idempotent: if pm's hooks are already present and the embedded command matches the current interpreter, returns `False` and does nothing. If pm's hooks are present with a stale interpreter path, the file is rewritten.
- Unrelated top-level settings keys (e.g. `"theme": "dark"`) are preserved. Notification hooks on matchers pm does not own are left untouched only when pm's hooks are already present; on a fresh install the entire `Notification` array is replaced (acceptable because the conflict guard rejects foreign idle_prompt entries upfront).
- Always creates the event base dir (`~/.pm/hooks/`) and sweeps event files older than 7 days.

`hooks_already_installed(settings_path=None)` is a read-only check that returns True iff pm's hooks are present with the expected command string — used by tests and by the runtime to detect whether a reinstall is needed.

### R3: Event-file watcher API (`pm_core/hook_events.py`)

Module exposes:

- `hooks_dir(session_tag=None) -> Path` — returns `~/.pm/hooks/{tag}` (or `_notag`). `session_tag=None` computes the tag from cwd via `get_session_tag(use_github_name=False)`.
- `event_path(session_id, session_tag=None) -> Path`.
- `read_event(session_id, session_tag=None) -> dict | None`.
- `clear_event(session_id, session_tag=None)`.
- `wait_for_event(session_id, event_types, timeout, newer_than=0.0, tick=0.2, stop_check=None, session_tag=None) -> dict | None` — busy-waits on the event file, returning the first event whose `event_type` is in `event_types` and whose `timestamp > newer_than`. Returns None on timeout or when `stop_check()` returns True.
- `hooks_available() -> bool` — True when `~/.claude/settings.json` has at least one hook pointing at `pm_core.hook_receiver`. Used by tests and by `PaneIdleTracker` to decide whether to consult events.

The file-poll tick is fast (200 ms); this is still "polling" but an order of magnitude lighter than pane-capture polling and needs no stability logic.

### R4: `poll_for_verdict` and `wait_for_follow_up_verdict` are hook-driven only

`pm_core/loop_shared.py`:

```python
def poll_for_verdict(
    pane_id, verdicts, keywords, session_id,  # session_id required
    prompt_text="", exclude_verdicts=None, grace_period=0,
    wait_timeout=15, stop_check=None, log_prefix="loop_shared",
    session_tag=None,
) -> str | None
```

- No polling / stability / grace-period fallback remains.
- Each iteration: check `stop_check`, check `pane_exists`, then block on `wait_for_event(session_id, {"idle_prompt", "Stop"}, timeout=wait_timeout, newer_than=hook_baseline)`.
- On `idle_prompt`: capture pane once, extract verdict. Return content on match.
- On `Stop` without a verdict: return None.
- `wait_timeout` (default 15 s) bounds how long `wait_for_event` blocks so we re-check pane liveness and `stop_check` periodically. Not a polling fallback — we simply re-enter `wait_for_event`.
- `grace_period` means "ignore events that fire before `grace_period` seconds have elapsed from the start of polling". Used by the review flow where Claude briefly emits idle during setup.

`wait_for_follow_up_verdict` has the same shape with `session_id` required.

### R5: Callers supply session_id

| Caller | How session_id is obtained |
|---|---|
| `review_loop._run_claude_review` | `session_id_from_transcript(transcript)` — review windows always launch with a transcript |
| `review_loop._wait_for_follow_up_verdict` | `session_id_from_transcript(iter_transcript)` from `state._transcript_dir` |
| `watcher_base._run_iteration` | `session_id_from_transcript(transcript)` — watchers require a transcript |
| `watcher_base._handle_input_required` | Same, with a log-and-return if the iteration transcript cannot be resolved |
| `qa_loop` concretize (`_concretize_scenario`) | `QAScenario.concretize_session_id` pre-generated by `_launch_scenarios_in_tmux` / `_launch_scenarios_in_containers` |
| `qa_loop` scenario agent | `QAScenario.session_id` populated from the transcript symlink right after the pane launches |
| `qa_loop` scenario relaunch (`_relaunch_scenario_window`) | Re-derives from the new transcript and overwrites `scenario.session_id` |
| `qa_loop` planner inline loop | `planner_session_id = uuid.uuid4()` passed into `build_claude_shell_cmd(session_id=...)` |
| `qa_loop` verification (`_verify_single_scenario`) | `verify_session_id = uuid.uuid4()` passed into `build_claude_shell_cmd(session_id=...)` |

### R6: QAScenario session fields

`QAScenario` (`pm_core/qa_loop.py`) stores two session_ids:

- `session_id` — the scenario-agent Claude session (set after the agent pane launches).
- `concretize_session_id` — the concretizer pass (set before the concretize pane launches).

Scenarios without a `session_id` at the time `_poll_tmux_verdicts` runs are marked `INPUT_REQUIRED` immediately (hook-driven polling requires one). This surfaces the problem rather than hanging silently.

### R7: `_poll_tmux_verdicts` is event-gated

`_poll_tmux_verdicts` still owns the scenario fan-out (relaunches, verification threading, queue launches, idle-reminder send), but the per-scenario verdict path is now event-gated:

- Per scenario, read the latest hook event for `scenario.session_id`.
- Skip unless the event is a new `idle_prompt` or `Stop` whose timestamp exceeds `_last_scenario_hook_ts[index]`.
- When a fresh event arrives, capture the pane once and run `extract_verdict_from_content`. Accept the verdict immediately on first non-stale detection — no `VerdictStabilityTracker`, no stability counter.
- `_verdict_context_fingerprint` is still used to skip stale re-detections after a verification follow-up round-trip.

On scenario relaunch, `_last_scenario_hook_ts[index]` is cleared so the new session's first idle_prompt triggers verdict extraction.

### R8: `PaneIdleTracker`

`pm_core/pane_idle.py` remains a hash-based tracker with a hook-aware fast path:

- `register(key, pane_id, session_id=None)` accepts an optional session_id.
- When `session_id` is set, `poll(key)` reads the latest hook event. A fresh `idle_prompt` event flips `idle=True` immediately; a `Stop` event marks the pane `gone=True`.
- When `session_id` is None, the hash fallback runs as before.

The hash fallback is retained because several TUI call sites (`tui/app.py`, `tui/review_loop_ui.py`, `tui/tech_tree.py`) don't have a session_id at registration time — they track arbitrary impl panes launched via `pm pr start` that don't always use a transcript. `content_has_interactive_prompt` is still checked by callers before acting on idle, so a gum-style permission prompt does not trigger auto-actions even when hooks say "idle".

### R9: `VerdictStabilityTracker`

Retained only for the TUI merge-verdict flow (`tui/review_loop_ui.py:_merge_verdict_tracker`), which polls the merge pane on the TUI timer without an available session_id. All other uses (review, watcher, QA) were removed because hook events are discrete turn boundaries — a verdict detected at an `idle_prompt` event is already "stable".

`STABILITY_POLLS` is kept as the tracker's internal constant.

### R10: Installed at every session start

- `pm_core/cli/session.py::_session_start` — calls `ensure_hooks_installed()` before tmux setup. `HookConflictError` aborts the session with a user-facing error.
- `pm_core/cli/tui.py::tui_cmd` — calls `ensure_hooks_installed()` before `ProjectManagerApp().run()`. `HookConflictError` writes to the TUI stderr log and re-raises so the user sees it.

Both entry points run the installer idempotently; it only writes when the settings file needs to be updated.

### R11: Container bind-mount

`pm_core/container.py::create_qa_container` bind-mounts `~/.pm/hooks` into the container at `$HOME/.pm/hooks`, so hook events from containerised Claude processes land in the host `~/.pm/hooks/{session_tag}/{session_id}.json` that the host-side pm reader watches. The directory is created on the host before the mount so the bind is safe.

### R12: Tests (`tests/test_hook_events.py`)

- Receiver writes the expected event file under a session-tag subdirectory.
- Receiver is silent on invalid JSON stdin.
- `wait_for_event` returns a matching event; times out correctly; respects `newer_than`.
- `hooks_available` reads `~/.claude/settings.json`.
- Installer installs cleanly, preserves unrelated top-level keys, is idempotent.
- Installer preserves Notification hooks on matchers other than `idle_prompt`.
- Installer raises `HookConflictError` when a foreign `Notification[idle_prompt]` hook is present.
- Installer raises `HookConflictError` when a foreign `Stop` hook is present.
- `poll_for_verdict` hook fast path returns within the timeout when an event is written mid-flight.
- `session_id_from_transcript` resolves a session_id from a symlink and returns None when the path is missing.

QA retry tests (`tests/test_qa_loop.py::TestScenarioRetryLogic`) were updated: scenarios set `session_id` and `pm_core.hook_events.read_event` is patched to return a fresh `idle_prompt` event.

## Implicit Requirements

1. **Atomic writes from hook receiver**: write via `tempfile.mkstemp` + `os.replace` in the same directory so readers never see partial JSON.

2. **Baseline timestamp per wait**: `wait_for_event(..., newer_than=<float>)` must not return an old event left over from a previous turn. Each caller captures `time.time()` when it starts a wait and passes it as `newer_than`. Consumers update the baseline to the consumed event's timestamp before the next call.

3. **Stale event file cleanup**: the installer sweeps event files under `~/.pm/hooks/` older than 7 days (recursive — traverses session-tag subdirectories). Cheap — directory has at most a few dozen entries per tag.

4. **Settings.json discovery**: pm installs into `~/.claude/settings.json` (user-level) so every Claude process pm launches — host and containerised — inherits the hooks via the existing `~/.claude` bind mount.

5. **Container event visibility**: `~/.pm/hooks` is bind-mounted read-write into the container at `$HOME/.pm/hooks` (see R11). Without this mount, the hook receiver would write inside the container and the host-side reader would never see the events. The receiver's `sys.executable` is a host path; if the container doesn't expose that interpreter the hook command silently fails (the receiver catches all exceptions), which is acceptable because the bind mount is the primary channel.

6. **Hook receiver ≠ virtualenv-dependent**: the hook command uses the absolute `sys.executable` captured at install time, so no virtualenv activation is needed. Re-running pm in a new interpreter context re-installs with the new path.

7. **Atomic vs concurrent hooks**: Notification and Stop may fire in rapid succession. Both write to the same `{session_id}.json`; last writer wins. `Stop` after `idle_prompt` is the intended final state.

8. **Session tag consistency**: host-side readers (`hook_events`) and the receiver both call `pm_core.paths.get_session_tag(use_github_name=False)`. Using the same function — not a hand-rolled duplicate — guarantees writer and reader agree on the directory path.

9. **Hook conflict safety**: the installer never overwrites third-party idle_prompt/Stop hooks. `HookConflictError` is raised and `pm session` / TUI launch refuse to proceed.

## Ambiguities (resolved)

### A1: Hook event storage — single file vs per-event
**Resolution**: single file per `(session_tag, session_id)`. Consumers only care about the latest turn-boundary; the `timestamp` + `newer_than` baseline prevents double-processing a single event.

### A2: How finely to split the Notification matcher
**Resolution**: install a matcher for `idle_prompt` only. Other Notification reasons (e.g. `waiting_for_tool_permission`) are not useful to pm and would cause false verdict captures.

### A3: Fallback detection for existing Claude processes
**Resolution**: no migration. Claude re-reads `~/.claude/settings.json` per session, so hooks fire for all subsequent turns.

### A4: What to do when `session_id` is not knowable
**Resolution**: the hook-driven code paths require `session_id`. Scenarios without one are marked `INPUT_REQUIRED` (R6). Review/watcher launches that somehow lack a resolvable transcript raise `RuntimeError` — this is a configuration bug, not a runtime fallback. The TUI `PaneIdleTracker` retains its hash-based fallback for tracking user-launched impl panes where session_id is not plumbed through.

### A5: Session-scoped vs global hook directory (new)
**Resolution**: session-scoped `~/.pm/hooks/{session_tag}/{session_id}.json`. Multiple concurrent pm sessions don't share a flat directory; the receiver and readers both derive the tag from cwd via `pm_core.paths.get_session_tag` so they agree on the path.

### A6: Clobbering pre-existing user hooks (new)
**Resolution**: refuse. `HookConflictError` surfaces the conflict; the user resolves it manually. Every `pm session` and TUI launch runs `ensure_hooks_installed` to guarantee our hooks are present and up-to-date.

## Edge Cases

1. **Verdict appears mid-turn, not at idle_prompt**: rare, but the hook fires at turn end, at which point the verdict is the last meaningful line in the pane — `extract_verdict_from_content` still finds it.

2. **Multiple rapid turns**: after consuming an event, the caller updates its baseline to the event's `timestamp` before re-calling `wait_for_event`. `poll_for_verdict` and the planner loop both do this.

3. **Hook script crash**: the receiver catches all exceptions and exits 0 — Claude never blocks. Reader-side `wait_for_event` times out every `wait_timeout` (15 s) and re-checks `pane_exists` / `stop_check`, so a persistently broken hook results in the loop idling rather than wedging. Pane death is still detected.

4. **Scenario pane relaunch**: `_relaunch_scenario_window` generates a new transcript + `session_id`, overwrites `QAScenario.session_id`, and `_poll_tmux_verdicts` clears `_last_scenario_hook_ts[index]` so the new session's first `idle_prompt` fires verdict extraction.

5. **Verification panes**: `_verify_single_scenario` pre-generates a UUID, threads it through `build_claude_shell_cmd(session_id=...)`, and passes it to `poll_for_verdict`. Hook-driven throughout.

6. **Interactive selection menus (gum / trust prompts)**: `idle_prompt` fires while Claude is at a gum-style permission prompt. TUI callers continue to gate on `content_has_interactive_prompt` before acting on idle.

7. **pm outside a git repo**: `get_session_tag` returns None → session_tag becomes `"_notag"`. Hooks still fire and land under `~/.pm/hooks/_notag/`. Install still succeeds because `~/.claude/settings.json` is user-global.

8. **Multiple pm instances on the same host**: each pm's session_tag differs (repo root path mixes into the MD5), so their event files live in separate subdirectories. `~/.claude/settings.json` is shared but the hook command is identical across instances.

9. **Hook receiver latency**: receiver imports `pm_core.paths` → `pm_core.git_ops` (subprocess for `git rev-parse`). Measured overhead ~50–100 ms per turn. Acceptable because turn boundaries are infrequent relative to pane rendering.

## Implementation notes (as landed)

- `claude_launcher.session_id_from_transcript(path)` — central helper used by `review_loop`, `watcher_base`, and `qa_loop` scenario pane setup to recover the Claude UUID from the transcript symlink target. No subprocess plumbing needed.
- `build_claude_shell_cmd(session_id=...)` is used by callers that don't have a transcript (verification pane, planner pane, concretize). They generate `uuid.uuid4()` themselves so they retain the reference.
- `STABILITY_POLLS` and `VerdictStabilityTracker` are kept only for the TUI merge-verdict flow. All blocking paths (review, watcher, qa) drop them; qa accepts the first non-stale verdict on each idle_prompt.
- `sleep_checking_pane` helper removed — no callers after the rewrite.
- Container runs bind-mount `~/.pm/hooks` so containerised Claude processes write events visible to the host reader.
- Installer at every session start (`pm session`, TUI launch) guarantees hooks are live; `HookConflictError` aborts startup if a foreign idle_prompt/Stop hook is present.
