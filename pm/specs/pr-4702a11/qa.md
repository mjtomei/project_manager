# QA Spec — pr-4702a11: pm rc mobile voice document viewer and editor

## 1. Requirements (what to exercise)

### 1.1 CLI: `pm rc start <path> [--port N]`
- Hard guard: outside a pm session → exits 1, message mentions "pm session".
- Missing optional deps (`fastapi`/`uvicorn`) → exits 1 with `pip install 'pm[rc]'` hint.
- `--port` collision: pre-bound port → exits 1 with "in use".
- No `--port`: picks a free port.
- LAN-only/no-auth warning printed to stderr at startup.
- On success: opens a new tmux window named `rc-<filename>`, registers the
  Claude pane under role `rc-driver`, spawns the FastAPI server as a
  detached daemon (start_new_session=True), records pid/port/host/lan_ip/
  path/log under `data["rc_servers"][window_id]`, and prints
  `Viewer: http://<lan-ip>:<port>/`, `Path: ...`, `Log: ...`.

### 1.2 FastAPI server (`pm_core.rc.server.create_app`)
- `GET /` returns the inline viewer HTML (`<!doctype html>`).
- `GET /api/doc` returns full snapshot incl. `text`.
- `POST /api/select`: sets selection; auto-focus viewport.top = max(1, start-3);
  validates 1<=start<=end<=line_count → 400 otherwise.
- `POST /api/focus`: sets viewport.top (clamped to [1, line_count]); does
  not change selection. Returns `{ok, viewport}`.
- `POST /api/propose`: 400 without selection; otherwise stashes text.
- `POST /api/accept`: writes proposal back to file (single-line, multi-line,
  with/without trailing newline preserves the file's overall trailing-NL
  convention); bumps version; clears selection+proposal; broadcasts state
  AND doc events.
- `POST /api/reject`: clears proposal; preserves selection.
- `POST /api/viewport`: stores viewport last-write-wins; does NOT broadcast.
- `GET /api/events`: SSE stream emits initial state event, then state/doc
  events on mutations; ping comments while idle; removes itself on
  disconnect; drops slow subscribers (queue full).

### 1.3 Webapp (`viewer.html`)
- Self-contained HTML, no external CDN, inline CSS/JS.
- Renders markdown readably; selection highlight; diff strip (red del /
  green add).
- Subscribes to SSE on load; reconnect with exponential backoff on error;
  visibilitychange→visible re-syncs via `/api/doc`.
- Debounced viewport reporting via POST `/api/viewport`.

### 1.4 Driver subcommands (run from rc-driver pane / loopback)
- `pm rc select <s> [e]`, `focus <top>`, `propose` (stdin),
  `accept`, `reject`, `status`. All resolve loopback URL via
  `data["rc_servers"][current_window]`. Outside a pm session → exit 1.
  Server unreachable → exit 1 with reason.
- `pm rc status` prints `path:`, `viewport:`, `selection:`, `proposal:`,
  `version:`, `lines:` lines.

### 1.5 Cleanup (`pm_core.rc.cleanup.maybe_kill_server`)
- Called from `pane_layout.handle_pane_exited`. If the rc-driver is gone
  from the window, SIGTERM the daemon pid and pop the rc_servers entry.
  If a driver still exists, no-op. Missing/dead pid → silent.

### 1.6 Registry helpers
- `_save_rc_server`, `_load_rc_server`, `_drop_rc_server` round-trip data
  under `data["rc_servers"][window]`. `_load` falls back to single entry
  when window unknown.

## 2. Setup
- Workdir already a git checkout at the PR branch.
- Optional deps may be missing (`fastapi`, `uvicorn`). Install with
  `pip install fastapi uvicorn pydantic` (or `pip install -e '.[rc]'`)
  before running server tests; tests use `pytest.importorskip`.
- For full TUI/tmux flow, `pm` must be on PATH; in container fall back to
  `./install.sh --local`.

## 3. Edge Cases
- Empty file (0 lines) — line_count returns 0; selection/focus on it.
- File with no trailing newline — accept must preserve no-trailing-NL.
- Multi-line proposal replacing a single line; single line replacing
  multi-line.
- Out-of-range / inverted selection (start>end, start<1, end>total).
- Propose with no selection → 400.
- Accept with no proposal → 400.
- Multiple SSE clients — both receive events; viewport last-write-wins.
- SSE subscriber whose queue is full gets dropped.
- Cleanup: rc-driver gone → server killed; driver alive → server kept.
- `pm rc <verb>` outside pm session → exit 1.
- `pm rc <verb>` when rc_servers entry missing → exit 1 with hint.

## 4. Pass/Fail Criteria
- PASS: all unit tests in `tests/test_rc.py` pass; manual checks (server
  endpoints exercised via curl or TestClient) match documented behavior;
  HTML root returns the inline viewer; CLI guards behave as specified;
  cleanup helper kills/keeps as expected.
- FAIL: a documented behavior diverges — wrong status codes, file written
  incorrectly on accept, version not incremented, missing broadcast,
  cleanup killing a live driver's server, registry shape inconsistent,
  or `pm rc start` not registering rc-driver / rc-server entries.

## 5. Ambiguities (resolved)
- We do not run real tmux/Claude — those are mocked. Real behavior in
  tmux is deferred to human-guided testing per PR description.
- We do not start a real uvicorn server in QA; we use FastAPI's
  `TestClient` against `create_app`.
- Line count of a fully-empty file is 0; `/api/select` should 400 on it
  (start>=1 cannot be <= 0). This is exercised.

## 6. Mocks
- **pm session lookup**: `pm_core.cli.rc._get_current_pm_session`
  monkey-patched per test (`return_value="pm-test"` or `None`).
- **registry path**: `pm_core.pane_registry.registry_dir` patched to
  `tmp_path` so registry JSON is isolated.
- **os.kill in cleanup**: monkey-patched to record (pid, sig) without
  actually signaling.
- **tmux**: not invoked from unit tests; `new_window_get_pane` and
  `pane_window_id` would be patched if a `pm rc start` happy-path test
  is added — for QA we skip the happy-path-with-tmux scenario and rely
  on the guard tests + endpoint tests.
- **subprocess.Popen** for the daemon: not exercised by QA (would be
  patched if `pm rc start` happy path were tested).
- Unmocked: file I/O on tmp_path, the FastAPI app, urllib (when CLI
  subcommand tests hit a TestClient's underlying app — but in this PR
  CLI subcommands hit a real server URL, so we test them only via the
  guard path that errors before HTTP).
