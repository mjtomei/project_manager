# Watcher framework, session health, and decision points

Pluggable always-on watcher framework with specialized watchers for session health, project state, and review/QA oversight. Also introduces decision points as a first-class entity for speculative parallel exploration of design and implementation choices.

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
  - Detects: API errors, 500s, usage limits, OOM, stalled sessions
  - Recovers: restart/nudge sessions, parse retry-after times, retry count limits
  - Subsumes: pr-76fa48d (auto-retry on errors), pr-72f1278 (OOM watchdog)
  - Does NOT cover: pr-b53bfe2 (trust prompt — programmatic fix), pr-757a140 (SSH disconnect — outside tmux)

- **pr-945546e**: Project state watcher — monitor project health and recommend actions
  - Observes: stuck PRs, unblocked dependency chains, stale workdirs, orphaned tmux windows, missing config
  - Actions: recommends next steps, gated actions requiring user approval in watcher pane

- **pr-c21e2ed**: Review/QA oversight watcher — monitor loops for anomalies and shortcuts
  - Detects: stuck loops, repeated failures, inconsistent verdicts, shortcut-taking workers
  - Surfaces patterns in watcher TUI pane for user review

### Phase 3: Advanced watchers (depend on phase 1/2)

- **pr-871dbf5**: High-effort watcher supervisors (depends on pr-3032fb6)
  - Opus-level watchers that monitor lower-effort sessions and inject feedback
  - Configurable targeting, feedback logging, runtime scaling

- **pr-a94befb**: Replace guide flow with project-level watcher using prompt addendums (depends on pr-3032fb6, pr-945546e)
  - Dynamic addendums based on project state gaps (no project.yaml, no plans, no deps, etc.)
  - Extends to general-purpose status checks: API health, disk space, branch divergence, etc.

- **pr-f84cf3e**: LLM API health and failover watcher (depends on pr-3032fb6, pr-dad0069)
  - Health watcher that monitors all LLM API endpoints and routes/failovers automatically
  - Graceful degradation across providers (Opus → Sonnet → local)
  - Note: multi-provider LLM support already delivered by pr-dad0069 (merged) and pr-8463df9 (merged)

- **pr-1f35c6d**: Local model lifecycle watcher (depends on pr-3032fb6, pr-dad0069)
  - Keeps a local LLM model process always running and healthy
  - Auto-restarts on crash, respects hardware constraints
  - Distinct from pr-f84cf3e (routing decisions) — this is about process lifecycle

- **pr-4bd08d7**: Anthropic-to-OpenAI translation proxy (depends on pr-9a5b86e)
  - Enables targeting sglang, vLLM, and OpenAI-compatible servers without external tools
  - Health check endpoint for pr-1f35c6d to monitor
  - Infrastructure, not a watcher itself, but required by the local model ecosystem

### Phase 4: Extensibility

- **pr-3b4a1b1**: User-defined watcher registration (depends on pr-3032fb6)
  - Subclass BaseWatcher in a .py file, register with WatcherManager
  - `pm watcher register/list/install` commands
  - Distributable via standalone files or pip packages

### Phase 5: Decision points — speculative execution for development

Writing code is speculative execution: you don't know the ideal version until you've explored. Humans pursue one path and backtrack when wrong. Machines can pursue many paths in parallel. Decision points let the human+machine combination identify uncertainty during planning, spec generation, or implementation and fork into parallel explorations rather than committing prematurely.

Decision points are a first-class entity with their own commands, not tied to any specific prompt or workflow. A human can manage them entirely through CLI commands. Prompts (planning, spec generation, implementation) are made aware of decision points so they can suggest creating them when they detect uncertainty, but the mechanism is general-purpose.

#### Core concept

A decision point represents a fork where multiple approaches are worth exploring. Each branch of a decision point gets its own variant of the downstream work:
- At the **plan/PR level**: the tech tree forks — variant subtrees with different PR structures, each with their own workdirs
- At the **spec level**: multiple candidate specs branch from a base (title + short description), each with their own implementation
- Branches are first-class: they appear in `pm pr list`, the TUI tech tree, and are managed by watchers

Convergence is a decision made by either human or machine. For now, humans are better at understanding real-world constraints that inform the choice, so the interface prioritizes making large decision trees digestible and explorable. LLMs get list-style commands optimized for their consumption.

- **pr-848ba9b**: Decision point entity, CLI commands, and branch-aware PR targeting (no dependencies)
  - Data model: decision points in project.yaml with id, branches, status (open/resolved), resolution
  - `pm decision add/branch/resolve/list/show/remove` commands
  - Branch-aware PR commands: all existing PR commands gain `--branch` flag to target a specific branch
  - Default targeting: when no `--branch` specified, commands target the most recent branch that worked on that PR
  - Write ops (start, edit, note) target the branch's workdir; read ops (list, show, ready) aggregate across branches
  - No decision points = identical to current behavior (backward compatible)
  - Automated workdir management: creating a branch auto-creates workdirs, resolving auto-cleans losers

- **pr-d925d69**: TUI decision tree explorer with branch-aware project state (depends on pr-848ba9b)
  - Two view modes switchable via keybinding:
    - **Aggregate (default)**: merges state from all active branches on this machine — the "what's actually happening" view
    - **Single branch**: isolates one branch's state (including master) for focused inspection
  - Solves the stale/forked project.yaml problem as a side effect of making decisions first class
  - Decision points shown as fork nodes; navigate into branches, compare side-by-side, pick winner
  - Scales to large trees: progressive disclosure, search, breadcrumb navigation
  - Manual testing required: both view modes, mode switching, branch targeting, keyboard navigation

- **pr-3f7815c**: Spec tree branching (depends on pr-942aa21)
  - Extend spec generation to produce multiple candidate specs from a base (title + short description)
  - Each candidate spec is a branch of a decision point
  - Each spec branch can have its own implementation workdir
  - `pm decision add --spec <pr-id>` creates a spec-level decision point
  - Spec variants visible in the TUI within the PR detail view
  - Prompt for spec generation updated to suggest branching when it detects significant design uncertainty

- **pr-df6cd9f**: Prompt awareness for decision points (depends on pr-848ba9b)
  - Planning prompts (plan breakdown, plan review) made aware of decision points
  - Spec generation prompts can suggest forking when uncertain
  - Implementation prompts know which branch they're on and what alternatives exist
  - Review prompts can flag when a branch looks clearly better/worse than its siblings
  - No prompt is required to use decision points — awareness is additive guidance only

- **pr-ebc8615**: Decision point watcher (depends on pr-3032fb6, pr-848ba9b)
  - Monitors open decision points across the project
  - Surfaces when branches have diverged enough to be meaningfully comparable
  - Recommends pruning stale or clearly-losing branches
  - Alerts when workdir count is growing large due to open decisions
  - Tracks resource usage per branch (API costs, time, workdir disk usage)
  - Presents decision summaries in the watcher TUI pane for human review

## Dependency graph

```
pr-7122c11 (standalone, in_progress)

pr-dad0069 (local LLM provider — MERGED)
  └── pr-9a5b86e (harden local LLM — QA)
        └── pr-4bd08d7 (translation proxy)

pr-3032fb6 (core framework — QA)
  ├── pr-18ac983 (session health)
  ├── pr-945546e (project state)
  │     └── pr-a94befb (replace guide flow)
  ├── pr-871dbf5 (supervisor watchers)
  ├── pr-c21e2ed (review/QA oversight)
  ├── pr-3b4a1b1 (user-defined watchers)
  ├── pr-f84cf3e (LLM API failover — also depends on pr-dad0069)
  ├── pr-1f35c6d (local model lifecycle — also depends on pr-dad0069)
  └── pr-ebc8615 (decision point watcher — also depends on pr-848ba9b)

pr-848ba9b (decision point entity + CLI — standalone)
  ├── pr-d925d69 (TUI decision tree explorer)
  └── pr-df6cd9f (prompt awareness)

pr-942aa21 (spec generation — QA, plan-qa)
  └── pr-3f7815c (spec tree branching — also depends on pr-848ba9b)
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

## Manual testing notes

These PRs will need human-guided testing (INPUT_REQUIRED during review):
- **pr-3032fb6**: TUI `w` prefix key, `ww` watcher list pane, tmux pane management, watcher start/stop
- **pr-7122c11**: Observe watcher with multiple branches in different states — verify watcher emits READY (not INPUT_REQUIRED) when one or more branches are paused by their own review/QA loop INPUT_REQUIRED, while still noting the paused branches in its summary; verify watcher does emit INPUT_REQUIRED for a project-wide blocker or a genuinely stuck in_progress branch with no active loop
- **pr-18ac983**: Trigger real session failures (API errors, OOM) to verify detection and recovery
- **pr-945546e**: TUI watcher pane gated actions, user approval flow
- **pr-1f35c6d**: Hardware-dependent — local model process lifecycle, VRAM/RAM detection
- **pr-4bd08d7**: Requires a running local LLM server to test proxy translation end-to-end
- **pr-848ba9b**: CLI commands for creating/resolving/removing decision points, workdir lifecycle
- **pr-d925d69**: TUI decision tree navigation, branch comparison, progressive disclosure at scale
