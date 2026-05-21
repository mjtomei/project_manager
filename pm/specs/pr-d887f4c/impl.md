# Implementation Spec — pr-d887f4c

**Web server skeleton + dashboard + proposed-changes walker + lock states + cycle nav + SSE + Apply button**

Part of `plan-litreview` (`pm/plans/plan-litreview.md`), this is **PR 3**. Depends only on
PR 2 (markdown format primitives, MERGED). PR 1 (`registry.py`, `paths.py`, `context.py`,
`cli.py`, the `pm review <target>` command) is **not** a dependency and is **not present** in
the tree, so this PR must be self-contained.

---

## 0. Current state of the tree (grounding)

- `pm_core/review/` contains only `__init__.py`, `md_parser.py`, `md_writer.py` (PR 2).
  - `md_parser`: `parse_response_blocks`, `parse_response_doc`, `parse_audit_doc`,
    `parse_state`, `parse_focus`; dataclasses `ResponseBlock`, `ResponseDoc`, `AuditDoc`,
    `AuditEntry`, `StateFile`, `FocusFile`.
  - `md_writer`: `update_response_block(path, change_id, updates)`,
    `append_interaction(path, change_id, event)`, `update_state(path, state)`,
    `update_focus(path, focus)`, `append_note(...)`. All atomic (temp+`os.replace`+`fsync`);
    the read-modify-write paths hold an `fcntl.flock` on a sibling `.lock` file.
  - `md_writer.update_state` does `out.setdefault("last-transition", _utc_now())` and writes
    the **whole** dict — callers must pass the full state, not a partial patch.
- `pm_core/review/cli.py` does **not** exist. The `pm` CLI is Click-based: the root group
  lives in `pm_core/cli/__init__.py`; submodules (`pm_core/cli/pr.py`, `plan.py`, …) are
  imported at the bottom of that file to register their commands on the `cli` group.
- `pm/project.yaml` has **no** `reviews:` key. `store.load(root)` returns the parsed dict;
  `store.find_project_root()` / `cli.helpers.state_root()` resolve the pm root.
- `pm/docs/adversarial-review/` exists with top-level legacy `CITATION_AUDIT_*.md` files but
  **no** `reviews/` subdir and **no** `METHODOLOGY.md`.
- Web deps (`fastapi`, `jinja2`, `watchdog`, `sse-starlette`, `uvicorn`, `httpx`) are now
  installed in the env. Python is 3.10; existing tests live in `tests/`, review tests in
  `tests/review/` with fixtures in `tests/review/fixtures/`.

---

## 1. Requirements (grounded)

### R1 — FastAPI single-file server (`pm_core/review/ui/server.py`)
- Single module exposing a FastAPI `app` plus a `build_app()`/`create_app()` factory so tests
  can construct an app rooted at a fixture pm dir (inject the pm root rather than relying on
  cwd discovery).
- Enumerates reviews by reading `project.yaml`'s `reviews:` list (via `store.load`); each entry
  is `{id, target, target-type, status}` per the plan schema. Missing key → empty list.
- Resolves per-review files via self-contained path helpers (PR 1's `paths.py` is absent):
  `REVIEWS_ROOT = <pm-root>/docs/adversarial-review/reviews`; `dir_for(id)`,
  `state_path(id)`, `focus_path(id)`, `review_cycle_path(id, n)`, `audit_cycle_path(id, n)`,
  `response_cycle_path(id, n)`, `notes_path(id)`. These mirror the names PR 1 will own so a
  later refactor can lift them into `paths.py`.
- Jinja2 templating via `fastapi.templating.Jinja2Templates` pointed at `ui/templates/`;
  static mount for `ui/static/`.

### R2 — `watchdog` filesystem watch → SSE
- Per review, watch the review **directory** (not individual file inodes — `md_writer` writes
  via temp-file + `os.replace`, so the canonical file's inode changes on every write; watching
  the directory catches the `moved`/`created`/`modified` events for the renamed-into target).
- Watched filenames per review: `STATE.md`, `UI_FOCUS.md`, and the **current cycle's**
  `REVIEW_CYCLE_N.md`, `CITATION_AUDIT_CYCLE_N.md`, `REVIEW_RESPONSE_CYCLE_N.md`. Because we
  watch the whole directory we naturally catch all cycle files; each emitted event carries the
  classified `type` and the cycle number so the client filters for relevance.
- A single `watchdog.observers.Observer` with one scheduled handler per review directory,
  scheduled lazily on first `/events` connection for that review (ref-counted; unscheduled when
  the last client disconnects). The handler classifies the changed basename:
  - `STATE.md` → `state` event (payload: parsed `StateFile` fields).
  - `UI_FOCUS.md` → `focus` event (payload: parsed `FocusFile` fields).
  - `REVIEW_RESPONSE_CYCLE_<n>.md` → `response` event (`{cycle: n}`).
  - `REVIEW_CYCLE_<n>.md` → `review` event (`{cycle: n}`).
  - `CITATION_AUDIT_CYCLE_<n>.md` → `audit` event (`{cycle: n, audited: K}` where K = count of
    complete entries from `parse_audit_doc`).
  - other basenames ignored.

### R3 — single `/events?review=<id>` SSE endpoint
- `sse_starlette.EventSourceResponse`. Each connection registers an `asyncio.Queue` with the
  per-review watcher; the watchdog thread bridges via
  `loop.call_soon_threadsafe(queue.put_nowait, event)` (loop captured from
  `asyncio.get_running_loop()` inside the endpoint). Generator yields
  `{"event": <type>, "data": json.dumps(payload)}`; periodic keep-alive comment to hold the
  connection. On client disconnect, deregister the queue and decref the watch.
- Latency budget: a watched-file change must surface as an SSE event in <200ms (tests assert
  this for STATE, FOCUS, current-cycle RESPONSE, current-cycle AUDIT).

### R4 — Dashboard (`templates/dashboard.html`, `GET /`)
- Lists every review from the registry, **active first, archived collapsed**. Per row:
  name/id, target, current cycle, current phase, **mode tag**, **engagement signals**.
- Clicking a review opens its per-cycle status view: review / audit-loop / response readiness,
  **audit-loop convergence indicator**, **cycle-selector dropdown** (latest first, defaults to
  current cycle).
- **Engagement signals** (derived from interaction logs across the rendered cycle's response
  blocks): bulk-accept ratio (bulk-accepted / acted), median view-time (from `viewed`
  `duration-ms`), and a suggester-confidence distribution summary for auto-run cycles. Compute
  best-effort; show "—" when no data.
- **Mode tag**: from `STATE.md` `mode` (`auto-run` / `human-reviewed`); show `mixed` at the
  artifact level when cycles differ in mode (best-effort across available cycles).
- **Convergence indicator**: surface the audit doc's convergence note when present (the
  fixture preamble carries `Convergence reached in N rounds.`), else "in progress" / "—".
- **`no cycles yet`**: when `STATE.md` is absent for a review, the row/status shows the
  placeholder and a one-line hint to run `pm review <target>` / `pm plan literature-review`.

### R5 — Proposed-changes walker (`templates/changes.html`, `GET /review/{id}/changes`)
- Renders every `<!-- proposed-change ... -->` block of the rendered cycle's
  `REVIEW_RESPONSE_CYCLE_N.md` (via `parse_response_doc`) as paginated entries with the
  before/after diff inline, the suggested verdict + rationale, and per-entry controls.
- **Filterable** by provenance (`reviewer-comment`/`audit-entry`), target-section,
  suggested-verdict (`accept`/`reject`/`modify`), status (`pending`/`accepted-as-suggested`/
  `edited`/`skipped`/`auto-accepted`). Filters are server-side query params and re-applied to
  the rendered set.
- **Per-entry actions**: accept (`accept-as-suggested`), edit (modify after/human-rationale/
  human-commentary + verdict), skip. Each writes the block via `md_writer.update_response_block`
  (sets `human-verdict`/`human-rationale`/`human-commentary`/`status`) **and** appends an
  interaction via `md_writer.append_interaction` (action type per the plan's logged-actions
  list, e.g. `accept-as-suggested`, `edit` field-tagged, `skip`, `reopen`).
- **Page-level bulk-accept-per-filter**: `POST …/bulk-accept` accepts every entry matching the
  current filter (default scope = current filter, per design decision 2), appending `bulk-accept`
  interactions with `scope` recording the filter.
- **Hotkeys** (`static/walker.js`): `j`/`k` next/prev entry, `a` accept, `m` modify, `s` skip.
- **View-time tracking**: client logs a `viewed` interaction with `duration-ms` (≥1s) per entry
  (best-effort; debounced) so engagement signals have data.

### R6 — Current-cycle in-progress artifact viewing (read-only, always allowed)
- The lock governs **modification**, not **visibility**. During `review`/`audit`/`response` the
  current cycle has no editable response yet, but its in-progress `REVIEW_CYCLE_N.md` (review
  phase) and `CITATION_AUDIT_CYCLE_N.md` (audit phase) must be **viewable read-only** and stream
  live via SSE.
- The main review page adapts its body to phase × availability:
  - response file present (`awaiting-human-review`/`applying`/`complete`, or any prior cycle) →
    proposed-changes walker (R5).
  - else current cycle in `review` → read-only render of `REVIEW_CYCLE_N.md`.
  - else current cycle in `audit` → read-only render of `CITATION_AUDIT_CYCLE_N.md` entries
    (parsed via `parse_audit_doc`) + the live `K citations audited` count.
  - else `response` with no response file yet → "response in progress" read-only placeholder.
  - The full canonical audit-browse view with per-citation click-through is **PR 4**; this PR
    ships a minimal read-only render sufficient for live viewing + the tests.

### R7 — Lock-state enforcement
- **Editable** iff `current-phase == awaiting-human-review` **and** rendered cycle ==
  `current-cycle`. In every other state (and on every prior cycle) the accept/edit/bulk-accept/
  skip/reopen controls render as **read-only badges** showing the verdict/status they carry.
- The mutating endpoints (`change`, `bulk-accept`) **server-side enforce** the same gate:
  reject writes (HTTP 409) when not `awaiting-human-review` on the current cycle, so a stale
  client can't bypass the lock.

### R8 — Apply button (the only UI → session signal)
- Visible **only** when `current-phase == awaiting-human-review`, rendered cycle == current
  cycle, **mode != auto-run**, **and this process holds the leader lock** (see R10).
- `POST /review/{id}/apply` reads current `STATE.md`, and via `md_writer.update_state` writes
  back the full state with `current-phase = applying` (preserving `current-cycle`, `mode`;
  `last-transition` re-stamped). Rejects (409) if not `awaiting-human-review` on current cycle
  or if not leader. The session, watching `STATE.md`, sees the transition and proceeds.
- Hidden in auto-run mode and outside `awaiting-human-review`.

### R9 — Phase-aware breadcrumb + Status panel + activity indicator
- Breadcrumb on every walker page per the plan table: cycle, phase, what the human can do.
  Prior cycles always `Cycle N · <phase> · read-only`.
- Dashboard Status panel mirrors it (phase, what's happening, what the human can do, progress
  hint such as audit round/`K citations audited`). Both update via SSE on `state` events.
- **Activity indicator** animates while phase ∈ {`review`,`audit`,`response`,`applying`}; idle
  at {`awaiting-human-review`,`complete`}. Audit phase animates the live `K citations audited`
  count, driven by `audit` SSE events.

### R10 — Multi-UI state ownership (leader lock) — from PR Notes
- Multiple `pm review ui` processes may render the same review (reads are lock-free,
  torn-read-safe via atomic-rename), but only **one** may write `STATE.md`.
- Each process tries `flock(LOCK_EX|LOCK_NB)` on a stable `STATE.md.leader` lockfile and holds
  it for its lifetime; the holder is the writer. Non-writers render Apply **disabled** with an
  "another UI owns this session" hint even in `awaiting-human-review`.
- **Failover**: OS releases the flock on process death; a follower's periodic `LOCK_NB` retry
  then succeeds and it takes the mantle (no stale-PID heartbeat). On leadership change, push an
  SSE `leader` event so Apply enables/disables on the right clients.
- This leader lock (who MAY write state) is distinct from `md_writer`'s per-write `.lock`
  (serializes the write itself); they compose — the leader still calls
  `md_writer.update_state`, whose check-then-write runs inside `md_writer`'s file lock.
- Implemented as a small `LeaderLock` class in `server.py` so it's unit-testable:
  `acquire()`/`is_leader`/`release()`; two instances over the same lockfile elect exactly one
  holder; releasing the holder lets a retry by the other succeed. (flock conflicts across
  distinct `open()` file descriptions even within one process, so this is testable in-process.)

### R11 — Cycle navigation
- Cycle selector (dropdown, latest first, default current) on the dashboard + reachable from the
  walker. Selecting a cycle re-renders every view against that cycle's files (`?cycle=N`). Prior
  cycles always read-only. Available cycles = union of cycle numbers discovered across
  `REVIEW_CYCLE_*.md` / `CITATION_AUDIT_CYCLE_*.md` / `REVIEW_RESPONSE_CYCLE_*.md` plus
  `current-cycle`.

### R12 — `pm review ui [--port]` CLI (`pm_core/review/cli.py`)
- New `pm_core/review/cli.py` defining a Click `review` group with a `ui` subcommand
  (`--port`, default e.g. 8765; `--host`, default `127.0.0.1`). `ui` runs the server via
  `uvicorn.run(build_app(...), host, port)`.
- Register the group on the root `cli` by adding `review` to the submodule import line at the
  bottom of `pm_core/cli/__init__.py`. The group is forward-compatible with PR 1 adding
  `pm review <target>` later (PR 1 owns the non-`ui` target dispatch).

### R13 — `pyproject.toml`
- Add `watchdog`, `fastapi`, `jinja2`, `sse-starlette` to `dependencies`. Also add `uvicorn`
  (required to actually serve `pm review ui`). Add `pm_core.review.ui` to the
  `[tool.setuptools] packages` list, and ensure templates/static ship (package-data or
  include). `httpx` is a test-only need (FastAPI `TestClient`) — add to the `test` extra.

---

## 2. Implicit requirements

- **App factory + injectable root.** Tests must build an app against a tmp fixture pm dir. A
  `build_app(pm_root: Path)` factory (with a module-level default that discovers the root) is
  required; routes read the root from app state, not cwd.
- **watchdog ↔ asyncio bridge** must capture the SSE endpoint's running loop and use
  `call_soon_threadsafe`; the observer thread must never touch asyncio objects directly.
- **Atomic-write awareness.** Because canonical files are replaced (not edited in place),
  directory-level watching is mandatory; file-level watches would go stale after the first write.
- **Reading right after a `moved` event is safe** (the rename is atomic), so the handler may
  parse STATE/AUDIT immediately to build the payload.
- **Server-side lock enforcement** (not just template hiding) so a stale browser tab cannot
  POST an edit/apply after the phase changed.
- **`update_state` writes the whole doc** → Apply must read-then-write the full state, never a
  partial patch, to avoid dropping `current-cycle`/`mode`.
- **Idempotent/no-op behavior** when STATE.md is absent (no cycles yet): every view renders the
  placeholder; SSE still connects; no writes possible.
- **JSON-friendly serialization**: `parse_state`/`parse_focus` already keep timestamps as
  strings (PR 2's custom loader), so SSE payloads serialize cleanly.
- **Graceful observer lifecycle**: start lazily, stop on app shutdown; avoid leaking observer
  threads across tests (provide a shutdown hook / context-manager friendliness).
- **Concurrent response-block edits across UIs are fine** (md_writer flock) — only STATE.md
  writes need the leader lock; edit controls are **not** leader-gated, only Apply is.

## 3. Ambiguities (resolved)

1. **Where does in-progress current-cycle review/audit content render, given the audit-browse
   view is PR 4?** → Render a minimal read-only view inline on the main walker page
   (`changes.html`) selected by phase (R6). Full canonical per-citation audit-browse with
   click-through stays PR 4. The tests only require that the content is viewable read-only and
   streams via SSE.
2. **Are accept/edit/skip controls available in auto-run + awaiting-human-review?** → In auto-run
   the session goes `response → applying` directly and never enters `awaiting-human-review`, so
   the combination shouldn't occur. The Apply button is hidden whenever `mode == auto-run`
   (explicit test). Edit controls follow the strict lock rule (awaiting-human-review + current
   cycle); they are not additionally mode-gated since the phase won't coincide in auto-run.
3. **Does the SSE response/review/audit event carry content or just a signal?** → State/focus
   events carry parsed payloads (cheap, avoids a round-trip, helps the <200ms budget). Cycle-file
   events (`response`/`review`/`audit`) carry `{cycle, …}`; the client re-fetches the rendered
   walker page (`GET …/review/{id}/changes?cycle=N`, preserving the active filters) and swaps in
   its `#walker-body` fragment to re-render — rather than a dedicated `/api/body` endpoint, the
   page route doubles as the fragment source. Audit events also carry the live `audited`
   count for the indicator.
4. **Default port for `pm review ui`.** → `8765` (arbitrary, high, unlikely to collide), `--port`
   overridable; host `127.0.0.1` (local-only per plan).
5. **PR 1 modules missing (`paths.py`, `registry.py`).** → Implement the minimal path/registry
   reads inline in `server.py` using the same names PR 1 will own, so a later refactor lifts them
   out cleanly. No new top-level modules beyond the task's file list (keep scope tight).
6. **`pm review` group vs PR 1.** → Create the `review` Click group with just `ui` now;
   forward-compatible with PR 1 adding target dispatch. If PR 1 lands first, the merge adds `ui`
   to its existing group instead.

No **[UNRESOLVED]** ambiguities.

## 4. Edge cases

- **STATE.md absent** → "no cycles yet" placeholder on dashboard + walker; cycle selector empty;
  status panel "no cycles yet"; no editable controls; Apply hidden; SSE still connects.
- **Response file absent but phase past response** (inconsistent state) → render in-progress/empty
  placeholder rather than 500.
- **Partial/mid-write response or audit file** → `parse_response_blocks` skips unterminated
  blocks; `parse_audit_doc` skips incomplete trailing entries (PR 2 behavior) — the live view
  shows only complete entries, which is the desired streaming behavior.
- **Prior cycle selected while current cycle is mid-write** → prior cycle is read-only history;
  current-cycle SSE events for `cycle != rendered` are ignored by the client.
- **Apply raced by two UIs** → leader lock guarantees only one writes; the non-leader's POST is
  rejected (409). The check-then-write also runs inside `md_writer`'s flock.
- **Leader dies mid-session** → its flock releases on process exit; a follower's periodic
  `LOCK_NB` retry acquires it and an SSE `leader` event flips Apply on its clients.
- **Filter yields zero entries** → walker renders an empty-state; bulk-accept is a no-op.
- **Edit on a skipped/accepted entry** → `reopen` interaction then the new action; status updated.
- **Mode == auto-run while viewing** → entries show `auto`/`auto-accepted` badges; Apply hidden;
  an `auto-accepted, never human-viewed` filter is available (status filter + interaction check).
- **New review created after server start** → lazy per-review watch on first `/events` connect
  means it works without restart; dashboard re-reads `project.yaml` each request.
- **TestClient SSE** → use `client.stream("GET", "/events?review=…")` and iterate lines while
  mutating files in a thread/after connect; assert event arrival under the latency budget.

## 5. Test plan (maps to task's required tests)

1. dashboard renders fixture multi-cycle state.
2. walker round-trips edits in `awaiting-human-review` (POST change → response block + interaction
   updated).
3. walker shows read-only badges in `review`/`audit`/`response`/`applying`/`complete` (no
   round-trip; mutating POST → 409).
4. current-cycle review/audit content viewable (read-only) during `review`/`audit`/`response`.
5. Apply writes the transition; hidden outside `awaiting-human-review` and in auto-run; POST
   rejected when not applicable.
6. cycle selector navigates between cycles (different cycle → different entries).
7. SSE STATE change locks walker <200ms.
8. SSE FOCUS change → navigation payload <200ms.
9. SSE current-cycle RESPONSE change pushes <200ms during `response`.
10. SSE current-cycle AUDIT change pushes <200ms during `audit` (with `audited` count).
11. activity indicator animates during `review`/`audit`/`response`/`applying`, idle at
    `awaiting-human-review`/`complete` (assert the indicator's state flag in rendered HTML / status
    JSON).
12. 'no cycles yet' placeholder renders when `STATE.md` absent.
13. leader-lock: two `LeaderLock` instances elect exactly one holder (second → Apply disabled);
    releasing the holder lets the other acquire (failover).

Fixtures: build a tmp pm dir with `project.yaml` carrying a `reviews:` entry and a
`docs/adversarial-review/reviews/<id>/` populated from the existing `tests/review/fixtures/*`
(state/focus/response/audit). Add helper to write multi-cycle layouts.

## 6. Files

- `pm_core/review/ui/__init__.py` (new, package marker — implied by `ui/` package).
- `pm_core/review/ui/server.py` (new) — FastAPI app, path/registry helpers, watcher manager,
  SSE, routes, `LeaderLock`, `build_app`.
- `pm_core/review/ui/templates/dashboard.html` (new).
- `pm_core/review/ui/templates/changes.html` (new).
- `pm_core/review/ui/static/style.css` (new).
- `pm_core/review/ui/static/walker.js` (new).
- `pm_core/review/cli.py` (new) — `review` Click group + `ui` subcommand.
- `pm_core/cli/__init__.py` (edit) — add `review` to the bottom submodule import.
- `pyproject.toml` (edit) — deps + package + test extra.
- `tests/review/test_ui_server.py` (new) — the test plan above.
