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

Out of scope (intentionally — these are not "state" in the same sense):

- Workdir clones at `~/.pm/workdirs/` — git clones, owned by git, not pm state.
- Debug logs at `~/.pm/debug/` — append-only log files, fine as-is.
- Claude transcripts at `pm/transcripts/` — append-only, in repo, fine as-is.
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

### Phase 8 — Session artifacts (last)

PR: Migrate `~/.pm/sessions/` deep tree. Lowest priority and most idiosyncratic; may end up partially deferred if particular subtrees are better as files (e.g. binary blobs, large logs).

## Out of scope

- **Remote backend**: schema is *designed* to allow swapping to remote later, but actually shipping a remote backend (Postgres adapter, server component) is a separate plan if and when needed.
- **Cross-host coordination**: this plan is host-local. Sharing state across hosts is a different problem (and would benefit from the same schema + a remote backend).
- **Workdir / log / transcript migration**: per the inventory, these are intentionally not state and stay file-based.
