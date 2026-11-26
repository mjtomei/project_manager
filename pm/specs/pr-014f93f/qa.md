# QA Spec: PR pr-014f93f — Claude Code hooks for verdict / session-end detection

## 1. Requirements (what to exercise)

Derived from `pm/specs/pr-014f93f/impl.md`. QA should confirm real-world behavior on top of the existing unit tests in `tests/test_hook_events.py`.

- **R-Hook-Receiver**: `python3 -m pm_core.hook_receiver <event>` reading a JSON Claude-hook payload on stdin writes `~/.pm/hooks/{session_id}.json` atomically with `{event_type, timestamp, session_id, matcher, cwd}`. Writes are the latest-wins; the receiver is silent on bad input and always exits 0.
- **R-Hook-Install**: `pm session` and TUI launch call `ensure_hooks_installed()`. The installer:
  - Writes `Notification[idle_prompt]` + `Stop` entries into `~/.claude/settings.json` calling `python3 <abs>/.pm/hook_receiver.py <event>`.
  - Copies `pm_core/hook_receiver.py` → `~/.pm/hook_receiver.py` (kept in sync each run).
  - Preserves unrelated keys (e.g. `"theme": "dark"`) and non-`idle_prompt` Notification matchers when pm's hooks are already present.
  - Is idempotent; rewrites only when python path / content changes.
  - Raises `HookConflictError` if a foreign `Notification[idle_prompt]` or `Stop` hook exists, and `pm session` / TUI abort with a user-facing error.
  - Ensures `~/.pm/hooks/` exists and sweeps files older than 7 days.
- **R-Hook-Events-API**: `pm_core.hook_events.wait_for_event(session_id, event_types, timeout, newer_than)` busy-waits (~200 ms tick) on `~/.pm/hooks/{session_id}.json`, returns first matching event whose timestamp > `newer_than`; honors timeout and `stop_check`.
- **R-Verdict-Path**: `poll_for_verdict`/`wait_for_follow_up_verdict` require a `session_id`. No polling/stability fallback remains. On `idle_prompt` they capture once and match; on `Stop` without a match they return None. `pane_exists` & `stop_check` are re-checked every `wait_timeout` iteration (default 15 s).
- **R-Session-ID**: All production call sites (review loop, watcher, QA planner/concretize/scenario/verification) acquire a `session_id`, either from the transcript symlink (`session_id_from_transcript`) or a pre-generated UUID threaded through `build_claude_shell_cmd(session_id=...)`.
- **R-QA-Poll**: `_poll_tmux_verdicts` is event-gated per scenario. A scenario with no `session_id` is marked `INPUT_REQUIRED`. `_last_scenario_hook_ts` tracks consumed events; fresh `idle_prompt` triggers a single pane capture + verdict extraction (no stability tracker).
- **R-PaneIdleTracker**: Hash fallback remains, plus hook-aware fast path when `register(..., session_id=...)` is used — fresh `idle_prompt` → `idle=True`; `Stop` → `gone=True`.
- **R-Container-Mounts**: `create_qa_container` bind-mounts `~/.pm/hooks` into `$CONTAINER_HOME/.pm/hooks` and mounts `~/.pm/hook_receiver.py` at the same absolute host path inside the container so the hook command `python3 <abs>/.pm/hook_receiver.py` resolves.
- **R-Tests-Green**: `pytest tests/test_hook_events.py tests/test_qa_loop.py tests/test_spec_gen.py` passes on the branch.

## 2. Setup

- Work from the PR workdir `/home/matt/.pm/workdirs/project-manager-828c8d0a/pm-pr-014f93f-use-claude-code-hooks-idle-prompt-st-33742570` or a fresh clone on branch `pm/pr-014f93f-use-claude-code-hooks-idle-prompt-stop-for-verdict`.
- Use `HOME=<tmp>` to isolate `~/.claude/settings.json` and `~/.pm/hooks/` during tests.
- Python 3.11+, pytest, tmux (for TUI scenarios).
- For CLI/TUI end-to-end scenarios follow `pm/qa/instructions/tui-manual-test.md`. If `pm` is not on PATH inside a container, run `./install.sh --local` from the pm repo.

## 3. Edge cases / failure modes to probe

- Foreign `Notification[idle_prompt]` or `Stop` hook already present in `~/.claude/settings.json` → pm refuses to start.
- Existing pm hook entry with stale interpreter path → installer rewrites it.
- Settings file missing entirely → installer creates it.
- Rapid successive hook events (`idle_prompt` then `Stop`) — last-writer-wins file; caller baseline prevents double-consume.
- Invalid JSON on stdin to receiver → exits 0, no file written.
- Scenario relaunch — `session_id` changes; `_last_scenario_hook_ts` must clear.
- Scenario with no `session_id` — marked `INPUT_REQUIRED`, not hung.
- 7-day-old event file swept during install.
- Container without either bind mount — hook no-ops silently, caller eventually surfaces `INPUT_REQUIRED`.

## 4. Pass / Fail Criteria

PASS: The requirement's observable behavior matches the impl spec and unit tests, with no regressions. Smoke-level CLI/TUI flow (where applicable) shows hooks firing and events landing in `~/.pm/hooks/`.

FAIL: Any of: installer clobbers a foreign hook; receiver crashes or writes non-atomically; `wait_for_event` returns stale events; `poll_for_verdict` reintroduces polling (pane MD5 hashing on the main path); `HookConflictError` is not surfaced; container scenarios silently hang; `pytest` hook/QA tests red.

## 5. Ambiguities (resolved)

- **QA environment**: Scenario agents likely run in sandbox/container without tmux/Claude. Prefer code-level verification (pytest + targeted scripts + reading source) unless the scenario explicitly sets up tmux per `tui-manual-test.md`.
- **"TUI manual test" applicability**: Only one scenario asks for full TUI bring-up; the rest rely on direct pytest / python invocations since they are faster and more deterministic.

## 6. Mocks

NEW_MOCK: claude-hook-payload
DEPENDENCY: Claude Code lifecycle hook invocation (idle_prompt / Stop)
REASON: QA cannot rely on a live Claude Code session firing hooks in a sandbox; instead drive `pm_core.hook_receiver` directly with synthetic JSON payloads on stdin (mimicking Claude's stdin contract: `{"session_id": "...", "cwd": "...", "transcript_path": "..."}`). The receiver is a pure stdlib script so stdin-mocking is sufficient and faithful.
SCRIPTED RESPONSES:
- idle_prompt event: `{"session_id": "<uuid>", "cwd": "/tmp", "transcript_path": "/tmp/x.jsonl"}` → receiver writes `~/.pm/hooks/<uuid>.json` with `event_type="idle_prompt"`.
- Stop event: same payload, argv `Stop` → file contains `event_type="Stop"`.
- Bad JSON stdin → receiver exits 0, file not created.
UNMOCKED: filesystem, `~/.claude/settings.json` content (real JSON parsing via `hook_install`), tmux panes where scenarios exercise them, pytest, git.

NEW_MOCK: claude-session-id
DEPENDENCY: Claude CLI generating a session id and writing a transcript JSONL file
REASON: No real Claude process available. Use `uuid.uuid4()` and craft a transcript symlink pointing at `~/.claude/projects/<mangled>/<uuid>.jsonl` to exercise `session_id_from_transcript` without launching Claude.
SCRIPTED RESPONSES:
- `session_id_from_transcript(symlink)` returns the UUID derived from the symlink target filename.
- Missing symlink → returns None.
UNMOCKED: pathlib / os.readlink real behavior.

---

QA_PLAN_START

SCENARIO 1: Hook receiver writes events atomically and handles bad input
FOCUS: R-Hook-Receiver — stdlib-only receiver contract.
INSTRUCTION: none
MOCKS: claude-hook-payload
STEPS:
1. In a scratch dir, set `HOME=$PWD` so `~` points there.
2. Run `echo '{"session_id":"s1","cwd":"/tmp"}' | python3 -m pm_core.hook_receiver idle_prompt` from the repo root.
3. Verify `$HOME/.pm/hooks/s1.json` exists, is valid JSON, has `event_type=="idle_prompt"`, numeric `timestamp`, `session_id=="s1"`.
4. Re-run with `argv=Stop` and a newer timestamp; confirm file is overwritten (latest-wins) and still valid JSON — open via `read_text()` in Python to check no partial write (no empty/truncated content).
5. Pipe `not-json` as stdin with `argv=Stop`; exit 0 expected, no `~/.pm/hooks/*.json` created for a new session id.
6. Pipe an empty stdin; exit 0 expected.
7. Confirm receiver has no `pm_core.*` imports: `python3 -c "import ast,sys; t=ast.parse(open('pm_core/hook_receiver.py').read()); print([n.module for n in ast.walk(t) if isinstance(n, ast.ImportFrom)])"` → must not include any `pm_core...`.

SCENARIO 2: Hook installer — fresh install, idempotence, stale-python rewrite, 7-day sweep
FOCUS: R-Hook-Install install path behaviors.
INSTRUCTION: none
MOCKS: none
STEPS:
1. Use a pytest harness or ad-hoc script: `HOME=<tmp>` then `from pm_core.hook_install import ensure_hooks_installed, hooks_already_installed`.
2. Call `ensure_hooks_installed()` on an empty home — assert: returns `True`, `~/.claude/settings.json` contains Notification[idle_prompt] + Stop entries whose command starts with `python3 ` and references `<abs>/.pm/hook_receiver.py`; `~/.pm/hook_receiver.py` exists and matches `pm_core/hook_receiver.py` byte-for-byte; `~/.pm/hooks/` dir exists.
3. Call again → returns `False` (idempotent, no rewrite). Verify `hooks_already_installed()` → `True`.
4. Pre-seed settings with `"theme":"dark"` and an unrelated top-level key; call `ensure_hooks_installed()` and confirm those keys are preserved in the output.
5. Mutate hook command in settings to reference `/nonexistent/python3`; call again — installer detects stale interpreter path and rewrites (returns `True`).
6. Place a dummy file in `~/.pm/hooks/old.json` with mtime 8 days ago (`os.utime`); call `ensure_hooks_installed()` → file is swept. A fresh file (mtime now) is preserved.

SCENARIO 3: Installer refuses to clobber foreign hooks
FOCUS: R-Hook-Install conflict detection.
INSTRUCTION: none
MOCKS: none
STEPS:
1. With `HOME=<tmp>`, write a `~/.claude/settings.json` containing `hooks.Notification[0]` with matcher `idle_prompt` and command `"/usr/local/bin/other-tool"` (no `pm_core.hook_receiver` reference, no `.pm/hook_receiver.py`).
2. Call `ensure_hooks_installed()` → expect `HookConflictError` raised. Assert message lists the offending entry.
3. Replace with a foreign `Stop` hook (no idle_prompt conflict) and repeat → `HookConflictError` still raised.
4. Replace with a non-conflicting Notification matcher (e.g. `waiting_for_tool_permission`) → install succeeds and that matcher is preserved alongside pm's `idle_prompt` entry.
5. Run `pm session` in a test project where a foreign idle_prompt hook exists (use `HOME` override). Expect the CLI to abort with a user-facing error, not silently overwrite.

SCENARIO 4: wait_for_event honors timeout, event types, and newer_than baseline
FOCUS: R-Hook-Events-API.
INSTRUCTION: none
MOCKS: claude-hook-payload
STEPS:
1. With `HOME=<tmp>`, reload `pm_core.hook_events` so `hooks_dir()` picks up the tmp home.
2. `wait_for_event("sX", {"idle_prompt"}, timeout=0.5)` with no file present → returns None within ~0.5–1s.
3. Write a `Stop` event at t0 to `~/.pm/hooks/sX.json`; call `wait_for_event("sX", {"idle_prompt"}, timeout=0.5)` → still None (wrong type).
4. Write an `idle_prompt` event at t0; call `wait_for_event("sX", {"idle_prompt"}, timeout=2, newer_than=t0+1)` → None (too old).
5. From a background thread, write an `idle_prompt` event at `time.time()` shortly after main thread calls `wait_for_event("sX", {"idle_prompt","Stop"}, timeout=2, newer_than=time.time()-0.01)` → returns the event within ~200–500 ms (tick is 200 ms).
6. `stop_check` returning True mid-wait aborts early and returns None.

SCENARIO 5: poll_for_verdict is hook-driven (no polling fallback)
FOCUS: R-Verdict-Path.
INSTRUCTION: none
MOCKS: claude-hook-payload
STEPS:
1. Read `pm_core/loop_shared.py`. Confirm `poll_for_verdict` signature requires `session_id` and that the body calls `wait_for_event` with `{"idle_prompt","Stop"}`. Confirm there is no pane-hash/stability loop in the main path.
2. Confirm `sleep_checking_pane` helper is deleted (grep should return 0 matches in `pm_core/`).
3. With a stub `pane_id` (`extract_verdict_from_content` can be monkey-patched) and `HOME=<tmp>`: call `poll_for_verdict(pane_id, verdicts=["DONE"], keywords={"DONE":"DONE"}, session_id="sY", wait_timeout=3, stop_check=lambda: False)` in a thread. Before 2 s, write an `idle_prompt` event with pane content containing `DONE`. Expect the function returns the matched content promptly after the event (no 5-s tick delays).
4. Repeat with `Stop` event and no verdict → function returns None immediately.
5. Confirm that with `stop_check` flipping True mid-wait, `poll_for_verdict` exits promptly.
6. Confirm that omitting `session_id` (pass None) raises or short-circuits — check code path to ensure there is no silent poll loop.

SCENARIO 6: Call sites pass a session_id (review / watcher / qa_loop)
FOCUS: R-Session-ID.
INSTRUCTION: none
MOCKS: claude-session-id
STEPS:
1. Grep `pm_core/review_loop.py`, `pm_core/watcher_base.py`, `pm_core/qa_loop.py` for every call to `poll_for_verdict` and `wait_for_follow_up_verdict`. Verify each passes a `session_id`.
2. Trace each session_id source:
   - review/watcher: `session_id_from_transcript(transcript_or_state_transcript_dir)`.
   - qa concretize: `QAScenario.concretize_session_id` set in `_launch_scenarios_in_tmux`/`_launch_scenarios_in_containers`.
   - qa scenario agent: populated from transcript symlink after launch; relaunch overwrites.
   - qa planner: `uuid.uuid4()` threaded via `build_claude_shell_cmd(session_id=...)`.
   - qa verification: `uuid.uuid4()` threaded similarly.
3. Unit-test `claude_launcher.session_id_from_transcript`: create a symlink `t -> /tmp/.claude/projects/abc/UUID.jsonl`; function returns `UUID`. With a missing symlink → None.
4. Confirm `QAScenario` dataclass has `session_id` and `concretize_session_id` fields (`grep -n 'session_id' pm_core/qa_loop.py`).

SCENARIO 7: _poll_tmux_verdicts is event-gated and handles relaunch
FOCUS: R-QA-Poll.
INSTRUCTION: none
MOCKS: claude-hook-payload
STEPS:
1. In `tests/test_qa_loop.py::TestScenarioRetryLogic`, run `pytest -x tests/test_qa_loop.py -k Retry -q` and confirm green. These tests patch `pm_core.hook_events.read_event` to simulate fresh `idle_prompt`.
2. Read `_poll_tmux_verdicts` in `pm_core/qa_loop.py`. Confirm:
   - scenario without `session_id` → marked `INPUT_REQUIRED`, not hung;
   - event timestamp compared to `_last_scenario_hook_ts[index]`; advances on consume;
   - on relaunch path, `_last_scenario_hook_ts[index]` is cleared;
   - no `VerdictStabilityTracker` invocation on per-scenario verdict path.
3. Run `pytest tests/test_qa_loop.py -q` and confirm all QA retry and poll tests pass.

SCENARIO 8: PaneIdleTracker hook-aware fast path + hash fallback preserved
FOCUS: R-PaneIdleTracker.
INSTRUCTION: none
MOCKS: claude-hook-payload
STEPS:
1. Read `pm_core/pane_idle.py`. Confirm `register(key, pane_id, session_id=None)` signature.
2. Write a small script: register key `"k1"` with a `session_id`; simulate pane capture returning constant content. With no event file, `poll("k1")` should NOT flip idle (hook path with session_id does not consult hash). Write an `idle_prompt` event → `poll("k1").idle == True` promptly. Write a `Stop` event → `poll("k1").gone == True`.
3. Register a key without a session_id. Keep pane content stable across two polls separated by the hash-stability interval → idle flips to True via hash fallback (confirming TUI panes without session_id still work).
4. Grep TUI files (`tui/app.py`, `tui/review_loop_ui.py`, `tui/tech_tree.py`) to confirm at least one register call still passes no session_id (legitimate hash fallback), matching the impl spec.

SCENARIO 9: Container QA bind mounts carry events from container to host
FOCUS: R-Container-Mounts.
INSTRUCTION: none
MOCKS: none
STEPS:
1. Read `pm_core/container.py::create_qa_container`. Confirm it adds two binds: host `~/.pm/hooks` → container `$CONTAINER_HOME/.pm/hooks`, and host `~/.pm/hook_receiver.py` → same absolute host path inside container (so hook command resolves identically).
2. If Docker/podman is available in the QA sandbox, start a minimal container with the same bind-mount spec, exec `python3 <abs>/.pm/hook_receiver.py idle_prompt` inside with a synthetic stdin payload (`session_id=ctest`), then on host read `~/.pm/hooks/ctest.json` and assert it exists. If container runtime is unavailable in the sandbox, instead verify the mount spec in code and document that live container verification is deferred.
3. Confirm the hook command in `~/.claude/settings.json` is a plain absolute `python3 <host-abs>/.pm/hook_receiver.py` — no `pm_core` on sys.path required inside the container.

SCENARIO 10: Hooks installed on `pm session` and TUI launch; conflict aborts startup
FOCUS: R-Hook-Install wiring at entry points.
INSTRUCTION: tui-manual-test.md
MOCKS: none
STEPS:
1. Follow the setup from `tui-manual-test.md` using an isolated `HOME` so we don't touch the real `~/.claude`.
2. Before running `pm session`, delete `~/.claude/settings.json` (if present). Run `pm session` per the instruction. Confirm `~/.claude/settings.json` now contains pm's Notification[idle_prompt] + Stop hooks, and `~/.pm/hook_receiver.py` exists.
3. Inside the tmux session, run a Claude-free smoke: `echo '{"session_id":"manual1","cwd":"/tmp"}' | python3 ~/.pm/hook_receiver.py idle_prompt` then `ls ~/.pm/hooks/manual1.json`.
4. Exit session. Pre-seed `~/.claude/settings.json` with a foreign Notification[idle_prompt] hook (non-pm command). Try `pm session` again → expect a user-facing `HookConflictError` and no session start.
5. Launch `pm tui` briefly (headless capture via `pm tui view` if needed) and confirm the same `HookConflictError` surfaces in TUI stderr log when a foreign hook is present; with it removed, TUI starts cleanly.

SCENARIO 11: Unit + integration test suite green
FOCUS: R-Tests-Green.
INSTRUCTION: none
MOCKS: none
STEPS:
1. From repo root on the PR branch: `pip install -e .[test]` (or equivalent) if needed.
2. Run `pytest tests/test_hook_events.py -v` — all hook-install/receiver/wait_for_event cases green.
3. Run `pytest tests/test_qa_loop.py -v` — QA retry paths green.
4. Run `pytest tests/test_spec_gen.py -v` — confirm spec-gen tests still pass after shared refactor.
5. Optionally `pytest -q` for a full suite; report any regressions.

QA_PLAN_END
