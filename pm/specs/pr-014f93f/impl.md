# Implementation Spec: Use Claude Code hooks + JSONL transcripts for verdict and waiting-state detection

## Summary

Pane-scraping-based verdict and idle detection is gone. Every code path that used to poll `tmux capture-pane` to decide whether Claude was done, had emitted a verdict keyword, or was waiting on input now reads state from two cooperating sources:

1. **Claude Code Notification hooks** (`idle_prompt` and `permission_prompt`) tell pm *when* the session crosses a state boundary. A standalone receiver writes the latest event to `~/.pm/hooks/{session_id}.json`.
2. **The Claude JSONL transcript** (`~/.claude/projects/<mangled>/<session_id>.jsonl`) tells pm *what* the assistant actually said, via a schema-light extractor that walks the raw JSON text backward.

The result is reliable, near-instant detection with no stability polls, grace periods, prompt-text filtering, or tail-line heuristics.

## Background: Claude Code hooks and matchers

Hooks live in `~/.claude/settings.json` (user-level). The installer merges pm's entries without touching unrelated keys and refuses to overwrite any `Notification[idle_prompt]`, `Notification[permission_prompt]`, or `Stop` hook that pm did not install.

pm registers three entries:

| Event | Matcher | Purpose |
|---|---|---|
| `Notification` | `idle_prompt` | Agent emitted `end_turn` and is waiting for the next user message. |
| `Notification` | `permission_prompt` | Claude Code is showing its own tool-approval dialog — the session is blocked until the user approves or denies. |
| `Stop` | *(none)* | Fires on every response. pm writes the event but does not use it — see R4 below. |

Each hook command is `python3 <HOST_ABS_PATH>/.pm/hook_receiver.py <event_type>`. The receiver has zero `pm_core` imports and is bind-mounted into QA containers at its host absolute path.

Explicitly not observable via hooks:

* `elicitation_dialog` — MCP-server elicitation (not relevant to pm today).
* Subprocess-level interactive prompts — `gum choose`, `fzf`, `git rebase -i`. These are part of a tool execution; Claude is still mid-turn from its own perspective and never fires a Notification. The TUI cannot know about them without pane scraping, which the old approach did with `content_has_interactive_prompt`. That guard was dropped as part of this work — we accept the blind spot because the PR's empirical data showed `idle_prompt` does not actually fire during these subprocess blocks (the earlier spec R8 was wrong on that point).

## Requirements

### R1: Hook receiver

`pm_core/hook_receiver.py` — standalone, stdlib only.

- Reads a JSON payload from stdin.
- Writes `~/.pm/hooks/{session_id}.json` atomically (tempfile + `os.replace` in the same directory).
- Record shape: `{event_type, timestamp, session_id, matcher, cwd}`. Last-writer-wins per session_id — the latest turn-boundary is all pm cares about.
- Never propagates exceptions; exits 0 so Claude never blocks on a broken hook.
- Event types it may write: `idle_prompt`, `permission_prompt`, `Stop`. (Anything else passed in argv works too; the receiver is event-type agnostic.)

### R2: Hook installation

`pm_core/hook_install.py`:

- `ensure_hooks_installed()` merges three hook entries (two Notification matchers + one Stop) into `~/.claude/settings.json`.
- Before writing, `_detect_foreign_hooks` rejects any existing `Notification[idle_prompt]`, `Notification[permission_prompt]`, or `Stop` hook pm did not install by raising `HookConflictError`.
- `_install_receiver()` copies `pm_core/hook_receiver.py` to `~/.pm/hook_receiver.py` so the same absolute path works on the host and inside any container that bind-mounts the file back at that path.
- `hooks_already_installed()` verifies **every** desired entry's command is present so adding a new matcher in the future correctly triggers a rewrite on upgrade.
- Creates `~/.pm/hooks/` and sweeps stale `*.json` files older than 7 days.

Called at the top of `pm_core/cli/session.py::_session_start` and `pm_core/cli/tui.py::tui_cmd`. `HookConflictError` aborts startup.

### R3: Event-file watcher API (`pm_core/hook_events.py`)

Exposes `hooks_dir()`, `event_path(session_id)`, `read_event(session_id)`, `clear_event(session_id)`, `wait_for_event(session_id, event_types, timeout, newer_than, stop_check)`, and `hooks_available()`. Default poll tick 200 ms.

### R4: `poll_for_verdict` and `wait_for_follow_up_verdict` (hook + JSONL driven)

`pm_core/loop_shared.py`:

```python
def poll_for_verdict(
    pane_id, transcript_path, verdicts, *,
    grace_period=0, wait_timeout=15,
    stop_check=None, log_prefix="loop_shared",
) -> str | None
```

- Recovers `session_id` via `claude_launcher.session_id_from_transcript(transcript_path)`. Raises `RuntimeError` when no UUID is recoverable — hook+JSONL polling has no pane-scrape fallback.
- Each iteration blocks on `wait_for_event(session_id, {"idle_prompt"}, timeout=wait_timeout, newer_than=hook_baseline)`. `Stop` is explicitly excluded — it fires every turn, not only at session exit. Session-gone is detected via `tmux.pane_exists`.
- On a fresh `idle_prompt` event: run `verdict_transcript.extract_verdict_from_transcript(transcript_path, verdicts)`. On match, return `verdict_transcript.read_latest_assistant_text(transcript_path)` (falling back to the verdict string if the assistant text can't be decoded).
- `grace_period` means "ignore events that fire within N seconds of polling start" — used by review where Claude may briefly idle during setup.
- `wait_timeout` bounds a single `wait_for_event` so we can re-check `pane_exists` and `stop_check` periodically.

`wait_for_follow_up_verdict` is the same shape with `session+window_name` in place of `pane_id` for finding the existing pane.

### R5: Callers supply a transcript_path

| Caller | How the transcript is provided |
|---|---|
| `review_loop._run_claude_review` | Passes the per-iteration `--transcript` path launched by `pm pr review` |
| `review_loop._wait_for_follow_up_verdict` | Derives `review-<pr>-i<iter>.jsonl` under `state._transcript_dir` |
| `watcher_base._run_iteration` | Passes the per-iteration transcript launched by the watcher |
| `watcher_base._handle_input_required` | Same derivation under `state._transcript_dir` |
| `qa_loop._poll_tmux_verdicts` | Reads `scenario.transcript_path` (set when the scenario pane launched) |
| `qa_loop._concretize_scenario` | Computes `claude_launcher.transcript_path_for(scenario_cwd, concretize_session_id)` |
| `qa_loop._verify_single_scenario` | Computes `transcript_path_for(_verify_cwd, verify_session_id)` |

`claude_launcher.transcript_path_for(cwd, session_id)` is the helper for callers that pre-generate a session_id and don't go through `build_claude_shell_cmd(transcript=...)`. `session_id_from_transcript` tolerates a path pointing at a not-yet-created `.jsonl` with a UUID filename.

### R6: `extract_verdict_from_transcript` (`pm_core/verdict_transcript.py`)

Schema-light JSONL reader.

- Walks the transcript text **backward** by line.
- Uses substring detection on `"type":"assistant"` / `"type":"user"` (whitespace-tolerant via regex) to bound the **latest assistant turn**. Records from earlier turns are not scanned, so a stale verdict from a previous turn can never leak.
- For each candidate line, matches `(?:\\[nr]|")<verdict>(?:\\[nr]|")` — the verdict must be bounded by a JSON newline-escape or a JSON string quote, i.e. it occupies its own line in the assistant's actual output. Incidental mentions like "PASS this file" are rejected.
- Verdicts are scanned longest-first so `PASS_WITH_SUGGESTIONS` wins over `PASS`.

`read_latest_assistant_text(transcript_path)` is a companion helper that decodes and concatenates the `text` content blocks of the latest assistant turn. This one *is* mildly schema-dependent (looks for `message.content[].type == "text"`); callers use it to feed downstream parsers like `extract_between_markers` for `REFINED_STEPS_END` / `FLAGGED_END` markers. If Anthropic changes that shape the helper can be updated in isolation — verdict detection is unaffected.

### R7: `PaneIdleTracker` — session + hook only

`pm_core/pane_idle.py`:

- `register(key, pane_id, transcript_path)` — transcript required. `session_id_from_transcript` recovers the UUID; `ValueError` if no session_id is recoverable.
- `poll(key)` — reads the latest hook event, updates state, returns `is_idle`.
- State has three orthogonal flags:
  * `idle` — most recent event was `idle_prompt`.
  * `waiting_for_input` — most recent event was `permission_prompt`.
  * `gone` — pane disappeared (from `tmux.pane_exists`).
- `Stop` events do not flip any flag (see R4).
- New public read: `is_waiting_for_input(key)` for TUI consumers.
- The old hash-based fallback (`_compute_hash` + `capture_pane`) is gone.

### R8: TUI — transcripts threaded through, waiting_for_input rendered

- `tui/review_loop_ui.py::_poll_impl_idle` looks up the transcript path from `auto_start.get_transcript_dir(app) / f"impl-{pr_id}.jsonl"` and passes it to `tracker.register`. Merge-pane registration uses `f"merge-{pr_id}.jsonl"` from the same directory.
- If the transcript dir isn't available (no auto-start session → no pm-managed launch), the impl/merge pane simply doesn't get tracked. Hook-driven automation doesn't apply to manual launches.
- `tui/tech_tree.py` renders a yellow `⏸` when `tracker.is_waiting_for_input(pr_id)`, the spinner when the pane is tracked-and-not-idle-and-not-waiting, and nothing when idle. The `pr-d3ae95e` permission-risk dashboard and `#137` tasks pane are expected to consume the same read.

### R9: QA scenario polling is event-gated + transcript-driven

`_poll_tmux_verdicts`:

- Per scenario, reads the latest hook event for `scenario.session_id`. Skip unless it's a fresh `idle_prompt` whose timestamp exceeds `_last_scenario_hook_ts[index]`.
- On a fresh event, call `extract_verdict_from_transcript(scenario.transcript_path, ALL_VERDICTS)`. Accept the verdict immediately on first non-`None` return — no fingerprint, no stability counter.
- Idle-reminder: when the hook fires with no verdict extractable, send a reminder to the pane (rate-limited by `_reminder_timeout`). The old content-hash tracking for "is the pane changing" is gone — hook events *are* the progress signal.

`VerdictStabilityTracker`, `_verdict_context_fingerprint`, `_last_content_hash`, `_last_content_change`, and `extract_verdict_from_content` are all deleted.

### R10: Installed at every session start

`pm_core/cli/session.py::_session_start` and `pm_core/cli/tui.py::tui_cmd` call `ensure_hooks_installed()`. `HookConflictError` aborts startup.

### R11: Container bind-mounts

`pm_core/container.py::create_qa_container` bind-mounts `~/.pm/hooks` and `~/.pm/hook_receiver.py` (at the host absolute path) so containerised Claude processes fire hooks that land on the host filesystem.

### R12: Tests

- `tests/test_verdict_transcript.py` — extractor: schema-agnostic boundary match, latest-turn only (stale PASS not leaked), longest-first, meta-line tolerance, incidental-mention rejection, multi-record turns.
- `tests/test_hook_events.py` — receiver writes the right file, `wait_for_event` timeouts + `newer_than`, `hooks_available`, installer idempotence, `HookConflictError` for foreign entries, `poll_for_verdict` hook fast path, `session_id_from_transcript`.
- `tests/test_pane_idle.py` — `register` requires a recoverable transcript, hook-event-driven idle/gone/waiting_for_input transitions, `became_idle` one-shot, `Stop` no-op, permission_prompt → waiting_for_input, subsequent idle_prompt clears waiting_for_input.
- QA retry tests patched to mock `extract_verdict_from_transcript` at the qa_loop boundary.

## Ambiguities (resolved)

### A1: Hook event storage — single file vs per-event
Single file per session_id. `timestamp` + `newer_than` baseline prevents double-consumption.

### A2: Which Notification matchers to install
`idle_prompt` (turn end) and `permission_prompt` (tool-approval dialog). `auth_success` and `elicitation_dialog` aren't useful to pm. Subprocess prompts don't fire any matcher — accepted as a hook blind spot.

### A3: Migration for existing Claude processes
No migration. Claude re-reads settings per session.

### A4: What when `session_id` is not knowable
Hook-driven code paths require a transcript. Scenarios without one are marked `INPUT_REQUIRED`. Review/watcher launches that lack a transcript raise `RuntimeError` — configuration bug, not runtime fallback. The TUI doesn't track manually-launched impl panes (no auto-start transcript dir).

### A5: Session-scoped vs global hook directory
Flat `~/.pm/hooks/{session_id}.json`. UUIDs prevent collisions; container and host agree on the path.

### A6: Clobbering pre-existing user hooks
Refuse. `HookConflictError` surfaces the conflict.

### A7: Stop vs idle_prompt for turn-end signalling (corrected)
Prior spec R3/R4 listened on both `idle_prompt` and `Stop`. `Stop` fires per-turn (not only at session exit), so treating it as a session-end signal produced false "session gone" returns mid-session. Fixed: we listen on `idle_prompt` only; `pane_exists` is the authoritative session-gone signal. The `Stop` hook is still installed (and written by the receiver) so future features can consume it, but `poll_for_verdict` / `PaneIdleTracker.poll` ignore it.

### A8: Distinguishing idle from waiting-on-user (new)
`permission_prompt` is installed as a second Notification matcher. Last-writer-wins semantics on the event file mean a subsequent `idle_prompt` (user approved, turn ended) cleanly replaces an earlier `permission_prompt`. `PaneIdleTracker.is_waiting_for_input(key)` exposes the state; `tech_tree` and downstream consumers (PR #137 tasks pane, `pr-d3ae95e` permission dashboard) render the indicator.

## Edge Cases

1. **Verdict mid-turn, not at idle_prompt**: the hook fires at turn end; at that point the verdict is the last meaningful text in the transcript — extractor finds it.
2. **Multiple rapid turns**: caller updates `hook_baseline` to the consumed event's timestamp before re-calling `wait_for_event`.
3. **Hook script crash**: receiver catches everything and exits 0. Readers time out every `wait_timeout` and re-check pane liveness / stop_check, so a broken hook means the loop idles instead of wedging.
4. **Scenario pane relaunch**: `_relaunch_scenario_window` creates a new transcript + session_id, overwrites `QAScenario.session_id`/`transcript_path`, and `_poll_tmux_verdicts` clears `_last_scenario_hook_ts[index]` so the new session's first `idle_prompt` triggers verdict extraction.
5. **Verification / concretize panes**: both pre-generate a UUID, pass it to `build_claude_shell_cmd(session_id=...)`, and call `transcript_path_for(cwd, session_id)` to get the JSONL path before Claude has opened it.
6. **Subprocess / gum menus**: no hook fires; `PaneIdleTracker` stays in its previous state. The user still sees the menu in the pane and responds there; pm just doesn't emit a "waiting" indicator for it. This is accepted.
7. **pm outside a git repo**: hook events are host-absolute (`~/.pm/hooks/`), independent of cwd.
8. **Multiple pm instances on the same host**: UUID session_ids keep event files unique; `~/.claude/settings.json` hook command is identical across instances.
9. **Hook receiver latency**: stdlib only, no pm_core imports. Overhead is negligible.

## Implementation notes (as landed)

- `verdict_transcript.extract_verdict_from_transcript` — schema-light.
- `verdict_transcript.read_latest_assistant_text` — schema-dependent helper, used by concretize/verify marker parsing.
- `claude_launcher.transcript_path_for(cwd, session_id)` — new helper.
- `claude_launcher.session_id_from_transcript` — tolerates non-existent paths with UUID names.
- `PaneIdleTracker.is_waiting_for_input(key)` — new public read.
- `loop_shared` lost: `extract_verdict_from_content`, `build_prompt_verdict_lines`, `is_prompt_line`, `is_prompt_line_with_neighbors`, `VerdictStabilityTracker`, `STABILITY_POLLS`. `match_verdict` stays for `auto_start_watcher` and its tests. `extract_between_markers` stays for QA planner output parsing (`QA_PLAN_END`, `REFINED_STEPS_END`, `FLAGGED_END`).
- `pane_idle` lost: `content_has_interactive_prompt`, `_compute_hash`, the `capture_pane` idle path. The tracker is session-only.
- `tui/review_loop_ui` lost: `VerdictStabilityTracker`-based merge-verdict stability; merge verdict is now a direct JSONL read.
- Container runs still bind-mount `~/.pm/hooks` and the receiver script at its host absolute path.
- Installer runs idempotently at every session start; `HookConflictError` aborts if foreign entries exist.
