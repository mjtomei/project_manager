# Retired legacy regression scenarios

On 2026-11-01 (pr-7d5d036) the user retired every old-style agent regression
scenario from `pm/qa/regression/` instead of porting them. Reviewing and
re-executing the whole migrated corpus was not worth its cost for the delivery
MVP. New durable regressions are authored and reused through the QA flow
(pr-2680fbf); porting this historical corpus is pr-c77561b, deferred until
the user chooses to resume it.

This file is an inventory, not part of the active library: nothing under
`pm/qa/`'s root is discovered as a regression test.

## Coverage gap

This is an intentional coverage gap, not a migration. Removing these 20
scenarios is **not** equivalent coverage and **not** a passing rerun: none of
them was ported, re-run or verified as part of their removal, and no other
regression definition replaces them. The behaviors they exercised (listed below by
title) are now covered only by whatever unit/integration tests in `tests/`
already touch them; those tests, the setup/capture recipes in
`pm/qa/instructions/` and `pm/qa/artifacts/`, the mocks/fakes and all
historical QA evidence and captures are kept.

## Recovery

Every definition is recoverable from revision
`c1fcecc58b09695602043094b44c8d96ca66bfe0` (master, "Merge pull request #282",
2026-11-01), the last revision with the files present. The branch that removed
them had not changed any of them.

```
# one file
git show c1fcecc58b09695602043094b44c8d96ca66bfe0:pm/qa/regression/<id>.md
# the whole corpus, into the working tree
git checkout c1fcecc58b09695602043094b44c8d96ca66bfe0 -- pm/qa/regression/
# check a recovered file against the inventory
git rev-parse c1fcecc58b09695602043094b44c8d96ca66bfe0:pm/qa/regression/<id>.md
```

A port should restyle each one onto the shared setup/capture recipes
(pr-c77561b's scope) rather than restoring it verbatim, because the restored
monolithic text predates the isolated regression launch. For example, they
assume the tester drives a live tmux session directly.

## Inventory (20 files)

| Path | Title | Description | Blob |
|---|---|---|---|
| `pm/qa/regression/command-dedup.md` | Command Deduplication | Test that PR actions block concurrent/duplicate execution | `54d08c79fca0` |
| `pm/qa/regression/guide-progress.md` | Guide Progress Widget | Test that guide progress widget displays correct step indicators | `3df9ce4fce21` |
| `pm/qa/regression/help-keybindings.md` | Help Screen & Keybindings | Open help screen with ? and verify all documented keybindings work | `39d3b1638ad1` |
| `pm/qa/regression/init-empty.md` | Init: Empty Repo | Test pm init with an empty repo (no commits) -- verifies backend, commands, TUI | `f763cf1f4b0b` |
| `pm/qa/regression/init-github.md` | Init: GitHub Repo | Test pm init with a GitHub remote -- verifies backend, commands, TUI | `6cd9bbb93cab` |
| `pm/qa/regression/init-local.md` | Init: Local Repo | Test pm init with a local repo (no remote) -- verifies backend, commands, TUI | `5d6d35caa236` |
| `pm/qa/regression/launch-dedup.md` | Pane Launch Deduplication | Test that pane launch keys (g, n) don't create duplicates | `463beb92541b` |
| `pm/qa/regression/log-viewer.md` | TUI Log Viewer | Test L key opens log pane, verify content and pane lifecycle | `92f750dd2509` |
| `pm/qa/regression/meta-launch.md` | Meta Session Launch | Test m key launches meta pane with correct role and context | `9f151b4c1578` |
| `pm/qa/regression/mobile-mode.md` | Mobile Mode | Test mobile mode auto-zoom, force flag, pane switching, and status command | `42705d45cb41` |
| `pm/qa/regression/multi-window-registry.md` | Multi-Window Registry | Test multi-window pane registry, review window isolation, and heal on restart | `f887a6e72bc2` |
| `pm/qa/regression/pane-layout.md` | Pane Layout Refresh | Test that pane kill/relaunch properly refreshes layout | `744687a3cdc2` |
| `pm/qa/regression/plans-pane.md` | Plans Pane | Test plans view toggle, navigation, actions, and refresh persistence | `a9900536b4be` |
| `pm/qa/regression/pr-interaction.md` | PR Interaction | Test PR navigation, selection, status changes, and actions | `227066d824b8` |
| `pm/qa/regression/restart-dedup.md` | TUI Restart Pane Deduplication | Test that restarting TUI doesn't create duplicate panes | `795c0fb13056` |
| `pm/qa/regression/session-resume.md` | Cluster Session Resume | Test that cluster explore sessions are saved and resumed correctly | `c40f3dea9ff5` |
| `pm/qa/regression/status-filter.md` | Status Filter & Merged Toggle | Test F key status filter cycling and X key merged PR toggle | `c48f8b43d51e` |
| `pm/qa/regression/sync-refresh.md` | Sync Refresh | Test r key sync, log line updates, and PR status changes | `811da5d4c5ae` |
| `pm/qa/regression/tech-tree-visual.md` | Tech Tree Visual Review | Review tech tree appearance for visual issues and improvements | `e8ac0e519ed4` |
| `pm/qa/regression/window-resize.md` | Window Resize Rebalance | Test that layout auto-rebalances on window resize (portrait vs landscape) | `e6cff7501243` |
