# Watcher framework and session health

Pluggable always-on watcher framework with specialized watchers for session health, project state, and review/QA oversight.

## Motivation

The existing watcher/auto-start loop is a monolithic piece that handles too many concerns. This plan refactors it into a pluggable framework where each watcher is a focused, independent unit that shares common infrastructure (polling, TUI integration, prompt templates, tmux pane management).

## Phases

### Phase 1: Foundation

- **pr-7122c11**: Refine watcher INPUT_REQUIRED to distinguish project-wide vs branch-specific issues (in_progress, GH #115)
  - Standalone fix to the current watcher. Prevents a single branch needing human input from blocking all other branches.

- **pr-3032fb6**: Watcher core framework — BaseWatcher, WatcherManager, auto-start refactor
  - The critical path item. All other watchers depend on this.
  - BaseWatcher abstract class with shared polling, prompt templates, tmux pane management, state persistence
  - WatcherManager orchestrator for scheduling, notification dedup, unified interaction layer
  - TUI integration: `w` prefix key, `ww` watcher list pane, status indicators
  - Refactors existing auto-start loop as proof of concept
  - `pm watcher start/stop` CLI commands

### Phase 2: Built-in watchers (all depend on pr-3032fb6)

- **pr-18ac983**: Session health watcher — detect and recover stuck/dead Claude sessions
  - Detects: trust prompts, API errors, 500s, usage limits, OOM, SSH disconnect garbage, stalled sessions
  - Recovers: restart/nudge sessions, reset garbled terminals
  - Subsumes previously standalone PRs: pr-b53bfe2, pr-76fa48d, pr-72f1278, pr-757a140

- **pr-945546e**: Project state watcher — monitor project health and recommend actions
  - Observes: stuck PRs, unblocked dependency chains, stale workdirs, orphaned tmux windows, missing config
  - Actions: recommends next steps, gated actions requiring user approval in watcher pane

- **pr-c21e2ed**: Review/QA oversight watcher — monitor loops for anomalies and shortcuts
  - Detects: stuck loops, repeated failures, inconsistent verdicts, shortcut-taking workers
  - Surfaces patterns in watcher TUI pane for user review

### Phase 3: Advanced watchers (depend on phase 2)

- **pr-871dbf5**: High-effort watcher supervisors (depends on pr-3032fb6)
  - Opus-level watchers that monitor lower-effort sessions and inject feedback
  - Configurable targeting, feedback logging, runtime scaling

- **pr-a94befb**: Replace guide flow with project-level watcher using prompt addendums (depends on pr-3032fb6, pr-945546e)
  - Dynamic addendums based on project state gaps (no project.yaml, no plans, no deps, etc.)
  - Extends to general-purpose status checks: API health, disk space, branch divergence, etc.

- **pr-f84cf3e**: Multi-provider LLM support with API failover watcher (depends on pr-3032fb6, pr-18ac983)
  - Multiple LLM providers (local models, OpenAI-compatible endpoints)
  - Health watcher that monitors API endpoints and routes/failovers automatically
  - Cost-aware routing: cheaper providers for bulk work, premium for critical decisions

### Phase 4: Extensibility

- **pr-3b4a1b1**: User-defined watcher registration (depends on pr-3032fb6)
  - Subclass BaseWatcher in a .py file, register with WatcherManager
  - `pm watcher register/list/install` commands
  - Distributable via standalone files or pip packages

## Dependency graph

```
pr-7122c11 (standalone, in_progress)

pr-3032fb6 (core framework)
  ├── pr-18ac983 (session health)
  │     └── pr-f84cf3e (multi-provider LLM + failover)
  ├── pr-945546e (project state)
  │     └── pr-a94befb (replace guide flow)
  ├── pr-871dbf5 (supervisor watchers)
  ├── pr-c21e2ed (review/QA oversight)
  └── pr-3b4a1b1 (user-defined watchers)
```

## Subsumed PRs

These standalone PRs were closed in favor of built-in watchers in this framework:
- pr-fd01c70 (periodic auto-start scan) — covered by pr-945546e
- pr-76fa48d (auto-retry on 500/usage limits) — covered by pr-18ac983
- pr-72f1278 (OOM-aware memory watchdog) — covered by pr-18ac983

## Related standalone PRs (bugs plan)

These remain as separate fixes outside the watcher framework:
- pr-757a140 (SSH disconnect garbage) — outside tmux, can't be handled by a watcher
- pr-b53bfe2 (trust prompt blocking) — simpler as a programmatic fix, saves tokens vs watcher approach
