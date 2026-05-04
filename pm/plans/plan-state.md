# Unified persistent state store

## Vision

Consolidate all pm-internal persistent state — project.yaml, scattered JSON files under `~/.pm/`, lock and pidfiles, hook event drops, launch queues — into a single host-local SQLite database. Eliminate the file-locking, atomic-staging, and parse-error workarounds those scattered stores require, get ACID transactions and WAL-backed concurrent reads for free, and design the schema so the same store can later swap to a remote backend without changing pm's API.

## Cross-reference

`plan-ambient`'s `pr-3fee106` (Persistent attention archive) uses the same SQLite-per-host primitive for attention/signal histories. Both efforts should converge on shared `pm_core/store/` infrastructure — connection management, schema migrations, query helpers — so attention data and pm-internal state share one database file and one set of operational tools (backup, vacuum, export, schema-version migrations). The two plans are complementary: this plan covers pm's control-plane state; ambient covers the user-attention data plane.

## Inventory of state to migrate

Found by walking `~/.pm/` and the project tree. Each entry below corresponds to a current file or directory layout that holds persistent or shared state.

| State | Today | Volume | Notes |
|---|---|---|---|
| Project graph (plans, PRs, notes, project metadata) | `pm/project.yaml` | Single file, in repo | The keystone; covered by existing `pr-945ba50` |
| Pane / window registry | `~/.pm/pane-registry/<session>.json` | Per-session JSON | Hot — every pane op reads/writes |
| QA loop runtime state | `~/.pm/runtime/pr-<id>.json` | Per-PR JSON | Live during QA loops |
| Launch queue | `~/.pm/launch-queue.json` | Single file | Auto-start scheduling |
| Hook events | `~/.pm/hooks/<session_id>` | Per-session-id files | High volume — Claude lifecycle events |
| TUI pidfiles | `~/.pm/tui-<session>.pid` | One per active TUI | For SIGUSR1 reload IPC (today's work) |
| TUI command queue | `~/.pm/tui-<session>.cmd-queue` | One per active TUI | TUI command IPC |
| Container governor lock | `~/.pm/governor.lock` | Single file | Memory-governor mutex |
| Per-session settings | `~/.pm/settings/` | Directory tree | Per-session config |
| Mobile-mode force flag | `~/.pm/<session>.mobile` | Sentinel file | Boolean |
| Generated specs | `~/.pm/specs/` | Directory tree | Per-PR spec output |
| Restart breadcrumbs | `~/.pm/<flow>-restart`, `~/.pm/merge-lock`, etc. | Sentinel files | Lifecycle markers |
| Session artifacts | `~/.pm/sessions/` | Deep tree | Session-scoped state |

Also in scope (added later — see Phase 9):

- Pm-internal logs at `~/.pm/debug/` — high write rate but moving them into the database makes cross-cutting queries ("last 100 errors across sessions", "what did this PR's QA loop log between T1 and T2") possible without file-globbing.

Out of scope (intentionally — these are not "state" in the same sense):

- Workdir clones at `~/.pm/workdirs/` — git clones, owned by git, not pm state.
- Claude transcripts at `pm/transcripts/` — append-only Claude session artifacts, in repo, fine as-is.
- The standalone `hook_receiver.py` at `~/.pm/hook_receiver.py` — code, not state.

## Goals

1. Single SQLite database per pm host (`~/.pm/state.db` or similar) containing every entry from the inventory above.
2. Migrations from each existing file-based store; existing installs keep working through a one-time import on first open.
3. WAL mode for concurrent readers without blocking; single writer with implicit transaction-per-write.
4. File-locking, atomic-staging, lock-file tricks, and parse-error guards retired wherever the scattered store they protected has moved to SQLite.
5. Schema designed to be swappable to a remote backend (Postgres etc.) later without changing the public `pm_core/store/` API.
6. Shared infrastructure with `plan-ambient`'s `pr-3fee106` — both write to the same SQLite file via the same connection-management helpers, so a host has one database to operate on, not two.

## Architecture

Single database at `~/.pm/state.db`. WAL journaling. Schema is additive — every PR adds tables/columns; nothing is renamed or removed in place. Schema version stored in a `schema_version` table; migrations applied idempotently on connection open.

`pm_core/store/db.py` is the connection layer (one-shot connect, WAL pragma, migration apply). `pm_core/store/schema.py` defines all tables in one place so the full shape is reviewable at a glance. Each domain (project, panes, qa_runtime, hooks, etc.) has its own `pm_core/store/<domain>.py` with typed query helpers; the public API of `pm_core/store/` (the package) keeps its current shape (`load(root)` / `locked_update(root, fn)` / etc.) so callers don't change.

Migrations from file-based stores are one-shot per host: on first open after a schema-version bump, if the legacy file exists and the corresponding table is empty, import the file and rename the file to `<original>.migrated-<timestamp>`. Imports are idempotent — re-running is a no-op.

## Phases

The phases are ordered so each PR ships standalone usefulness; the keystone (`pr-945ba50`) lands early so the most-touched store (project.yaml) gets ACID guarantees first.

### Phase 1 — Core infrastructure

PR: Core SQLite store infrastructure — connection layer, WAL pragma, schema-version table, migration runner. Stub schema with no domain tables. Subsequent PRs add domain tables additively.

PR: Change-log audit table and writer wrappers. Every domain write (INSERT / UPDATE / DELETE) emits a row into a `state_changes` table: `(id INTEGER PRIMARY KEY, timestamp_ns, actor, context, table_name, row_pk, op, before_json, after_json)`. Implemented as SQLite triggers per opted-in table, plus a thin Python wrapper that captures `actor` (user / agent session id) and `context` (the CLI command or TUI action that triggered the write). Per-table opt-in so high-volume already-event-shaped tables like `hook_events` don't double-log themselves. This makes "what changed today / over the last week / by whom" a single SELECT and gives us full replayable history of interactions for free.

### Phase 2 — Project graph (keystone)

PR: Replace project.yaml with SQLite (`pr-945ba50`, re-parented from `plan-003`). Project / plans / PRs / notes tables. Migration from project.yaml on first open. Existing `pm_core/store.py` API preserved.

### Phase 3 — Live registries

PR: Migrate pane / window registry from per-session JSON to SQLite.

### Phase 4 — Runtime state

PR: Migrate QA loop runtime state.

PR: Migrate launch queue.

PR: Migrate TUI pidfile + command queue.

PR: Migrate container governor lock to row-locked sentinel.

### Phase 5 — Hook events (high-volume)

PR: Migrate Claude hook events to SQLite. This is a high-write-rate store; schema includes a (session_id, timestamp_ns) index and a configurable retention policy so the table doesn't grow unbounded.

### Phase 6 — Configuration

PR: Migrate per-session settings.

PR: Migrate mobile-mode force flag.

### Phase 7 — Specs and breadcrumbs

PR: Migrate generated specs.

PR: Migrate restart breadcrumbs and merge-lock sentinels to a typed `markers` table.

### Phase 8 — Session artifacts

PR: Migrate `~/.pm/sessions/` deep tree. Idiosyncratic; may end up partially deferred if particular subtrees are better as files (e.g. binary blobs, large logs).

### Phase 9 — Logs

PR: Migrate `~/.pm/debug/*.log` and other pm-internal log streams into a `logs` table. Highest write rate of any store in this plan (every `_log.info` call lands here), so the table needs careful indexes (`timestamp_ns`, `(logger, timestamp_ns)`, `(session_id, timestamp_ns)`, `(pr_id, timestamp_ns)`) and an aggressive retention policy. The reader-side benefit is large: "show me the last 100 errors across all sessions" / "what did this PR's QA loop log between T1 and T2" become single SELECTs instead of file-globs and `grep`.

### Phase 10 — Data/view separation

PR: Extract a typed data-service layer between storage and every consumer of pm state. **This is a complete separation, not a TUI-only refactor.** Done means storage is internal: `pm_core/store/` is imported only from `pm_core/services/`, and every other module — TUI, CLI, watchers, qa_loop, prompt_gen, hooks, container/cleanup, pr_sync, auto_start, anything that touches state today — goes through `pm_core/services/`. An import-graph guard test enforces this on every future PR so the boundary can't be quietly punched through.

The service layer returns view-ready typed objects (frozen dataclasses or Pydantic models) on read and accepts typed command objects on write. No SQL, no rows, no internal IDs leak past it. The audit log (Phase 1's `state_changes`) integrates naturally because services are the only writers — actor and context get set in one place for every mutation.

With the separation complete, `plan-ambient`'s surface protocol (rc viewer, project browser, doc reader, future web frontend) becomes a UI-shaped consumer of this layer, not a parallel data path. Adding a new UI is "find or add the service methods you need" — no storage rework, no risk of state-shape drift across UIs.

## Out of scope

- **Remote backend**: schema is *designed* to allow swapping to remote later, but actually shipping a remote backend (Postgres adapter, server component) is a separate plan if and when needed.
- **Cross-host coordination**: this plan is host-local. Sharing state across hosts is a different problem (and would benefit from the same schema + a remote backend).
- **Workdir / transcript migration**: per the inventory, these are intentionally not state and stay file-based. Workdirs are git clones; transcripts are append-only Claude session artifacts.
