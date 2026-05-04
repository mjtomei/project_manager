# Unified persistent state store

## Decision: not pursued

After scoping this plan in detail, we reconsidered the core architectural assumption and decided to **stay file-based and git-tracked**. This document is preserved as the record of that decision so future work doesn't relitigate it without seeing the prior reasoning.

## Why we considered it

The original motivation was real:
- Scattered persistent state across `~/.pm/` (per-session JSON, lock files, sentinel markers, hook drops, runtime state, logs).
- File-locking, atomic-staging, parse-error guards as workarounds for the absence of a real database.
- Occasional `pm/project.yaml` merge conflicts when concurrent agents work on different branches.
- No single tool to query "what is pm doing right now."

A SQLite-per-host store (or Dolt for the git-tracked pieces) would have given ACID transactions, concurrent-safe reads, branch-and-merge semantics for structured data, and a unified place to query state.

## Why we didn't pursue it

**Text files in git is a real feature, not just an implementation detail** — particularly for LLM-driven workflows. Agents grep, diff, blame, and edit project state with the same primitives they use for code. They read `pm/project.yaml`, `pm/plans/*.md`, and `pm/specs/*.md` as text and reason about them like any other file in the repo. A DB layer would force agents to learn a query interface, lose the ability to grep state, lose git-blame-style history attribution, and break the "everything is text" contract that makes pm composable with other tools.

The pain points (occasional project.yaml merge conflicts, scattered ~/.pm/ files) are real but don't outweigh that ergonomic value. Better merge tooling, smaller commit scope, and incremental polish on file-based primitives are cheaper than the wholesale migration would have been.

## What we kept

Two pieces survived the reconsideration as still-valuable:

- **`pr-a84a939` (Extract data-service layer between storage and UIs)** — reparented to `improvements`. A typed service layer between storage and consumers is a code-refactor improvement that doesn't depend on storage choice. It makes new UIs cheap (plan-ambient's surfaces) and catches shape errors at a clean boundary. Storage stays file-based; the service layer just routes through it.

- **`plan-ambient`'s `pr-3fee106` (Persistent attention archive)** — stays in plan-ambient. This is the one genuine DB use case in pm: long-horizon time-series of attention signals (gaze, dwell, viewport history). Not git-tracked (no review value), high write rate (file-per-event would be wasteful), query patterns (windowed aggregations) that are miserable as files. SQLite-per-host is the right primitive for this specific data class.

## What we closed

- `pr-945ba50` (project.yaml → SQLite) — keystone of the wrong direction.
- `pr-e81bfaf` (Core SQLite store infrastructure) — not needed without the broader migration.
- `pr-8620ca1`, `pr-54bc67d`, `pr-af845cd`, `pr-4e075b1`, `pr-c05ba7b`, `pr-1d5561d`, `pr-aa2429a`, `pr-75f9276`, `pr-e6a3a99`, `pr-026adcd` — per-domain ephemeral state migrations. Files work fine for these.
- `pr-51b9f26` (Change-log audit table) — for git-tracked state, git itself is the audit log. For ephemeral state, no audit need has emerged.

Each closed PR has a note explaining the decision and pointing back to this document.

## Future re-litigation criteria

If we ever revisit this, the bar to clear:

1. **A specific persistent pain point that file-based primitives genuinely cannot fix.** "Occasional merge conflicts" doesn't qualify; "we lose data N times a month" might.
2. **A concrete LLM-collab story for the new layer.** How will agents read, modify, and reason about state if it lives in a DB? An MCP-shaped interface? An export-on-edit YAML view? Whatever it is, must be at least as ergonomic as `cat pm/project.yaml`.
3. **A migration path that doesn't break the git-history audit trail** for plans, PRs, and review activity.

Nothing on the horizon today meets that bar.
