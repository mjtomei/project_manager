# QA spec — pr-1139060

## Scope and grounding

Baseline refreshed on 2026-10-26: `git diff master...HEAD`, HEAD `25751700` (through review-loop 0b6f i10 PASS, including runtime-QA fixes and the resolved implementation A7). Earlier S1–S19 execution evidence remains historical evidence, not current runtime acceptance. Fresh scenarios begin at 20; previously started scenarios are not edited or replaced. This spec covers the container lifecycle, every changed launcher, recovery CLI, TUI reconciliation, shared push proxies, and the popup/session-routing changes included in this branch. It is an end-user integration contract, not a request to call internal helpers.

Primary surfaces: `pm pr start`, review, QA, sign-off and merge; `pm qa debug`; TUI run/stop/restart/resume/cleanup actions; `pm container status`, `reap`, `retain`, `restart`, legacy `cleanup`; `pm session cleanup`; `pm pr cleanup --resources`; `pm help`; the in-container push-proxy git commands; tmux picker and command popups. No browser surface was changed. Host-only mode is a regression control.

Refresh on 2026-10-27 at HEAD `8c5fad86` (review loops d019 i1–i4, 75b8 i1–i7, f54b i1–i10). Scenarios 20–33 are locked historical evidence; fresh scenarios begin at 34. Results of the 20–33 run (d42809cf, aggregate NEEDS_WORK): S22 PASS; S20/S21/S26/S27 NEEDS_WORK only because each found and fixed a real defect (4c43ba38 `--fresh` within grace, 0c9c05fc slow-runtime probe/image caching, 60e3d89e deferred-vs-failed status, 95dc7074 pre-readiness death) — they need clean reruns on the current head; S23 worker crashed with no verdict; S24 story 1 (locked-recheck under a release record) undriven; S25 stories 5 and 9 unexecuted; S31 dead-worker retry/cancel unexecuted; S32 container overlap unexecuted (fixture guard); S21 cancellation, `/pr qa fresh` overlap and mixed-ownership stories unexecuted; S28/S29/S30/S33 blocked on prerequisites (no Docker, no delegated PID cgroup, no disposable keyring UID, no hour-long budget).

User-visible behavior added after `25751700` that fresh scenarios must cover:
- tmux ownership/QA-release parsing is locale-independent (works under `LC_ALL=C`/unset locale); ownership probes tolerate non-UTF-8 argv/pane commands (unknown, never a traceback).
- Host-side git in the container-writable PR workdir runs no repository hooks (pre-push, post-merge, pre-merge-commit, reference-transaction, post-index-change) across push proxy, `pr start`, sign-off integration merge, publishing, QA planner hand-off and workdir status probes; the push proxy rejects abbreviated `--upload-pack`/`--receive-pack`/`--exec` prefixes. Config-key escapes (`remote.*.uploadpack`, `core.sshCommand`, `core.fsmonitor`) are out of scope (pr-c558b14); `--repo <path>` positional bypass is out of scope (pr-15734c1).
- `pm container restart` of a legacy container without a completion marker reports success with before/after PIDs; empty-ID `run` output is a retryable runtime error that leaves the allocation for reconcile.
- Every lifecycle probe timeout/OSError is a classified, retryable launch error naming the container (not a raw traceback or immutable ID); retained-container refusals print the runnable `pm container retain --release` / `pm container restart` command; `pm help` lists `reap`, `retain` and `restart`.
- Resolved/vanished proxy failures and identity-less releases stop showing as retryable reap failures; `pm container status` probes the runtime identity once and inventories once.
- `container-max-running` re-clamps before each queued launch from the run's desired batch (grows back after a full or unreadable inventory recovers; unreadable clamps to one); a stopped run downgrades never-verified PASS to INPUT_REQUIRED and opens no finalize pane; a PASS awaiting verification whose relaunches all fail becomes INPUT_REQUIRED.
- `pm pr cleanup --resources` from a plain terminal covers every session tag; sign-off/debug treat an existing window after a failed pane lookup as launched.

Refresh on 2026-10-27 at HEAD `76081338` (QA fixes from scenarios 34–45 plus review-loop c2fc i1). Scenarios 34–48 are locked historical evidence; fresh scenarios begin at 49. Results of the 34–48 run (aggregate NEEDS_WORK): S36, S38 (after 3d291aeb), S39, S40 (one spec conflict, resolved below as A16), S42, S43, S45 held live, and S37/S44 held after in-run fixes. S34 and S35 each found and fixed real bugs and need clean reruns. S34 T3 (stopping a large multi-PR run) was blocked by the worker's PID budget: PID 1 there is `sleep infinity`, zombies pile up, and the cgroup cap is 2048. S35 story 3 took about 94 minutes because inline retry backoff blocks the poll. S41 was refined live, but no result note exists, so its stories are rerun. S46 (keyring/PID pressure) was rejected, S47 (Docker) deferred and S48 (hour-aged locks) deferred: none of them had a qualified prerequisite.

User-visible behavior added after `8c5fad86` that fresh scenarios must cover:
- Supersede and resume: after `/pr qa fresh` over an active run, superseded workers whose panes are already gone are released within seconds, not left for the periodic pass (895b5b69). A TUI restart resumes only the newest QA snapshot for a PR (b913a424). A superseded run never rewrites its own snapshot, so after the replacement finishes, a later restart does not recover the stopped run as a completion: no duplicate note or transition, and the PR does not stay in `qa` after PASS (76081338).
- Stopping and dead workers: a stop during PASS verification sends no follow-up to the worker, records no FLAG and keeps the container live during the stop. The scenario becomes INPUT_REQUIRED "PASS was not verified before the run was stopped" (3d4f44c9). When a dead worker's relaunch fails, the run keeps retrying it. It never adopts the window's concretizer pane, so the run cannot hang showing PASS (48780e13).
- Process pressure: if forking fails in the TUI's QA poll tick (EAGAIN/ENOMEM), the tick is skipped and the TUI survives, so a stopped run's workers are still released (065aba13).
- Headroom and queued scenarios: settled workers whose release was deferred by an unreadable inventory are retried once per poll, so the batch grows back after recovery. The dashboard keeps every queued scenario and its queued label through launches (868a4654). In an 8-worker run, a slow identity inspect is retried within the bounded budget and does not abort every worker (b25c70e8).
- Restart and launch advice: `pm container restart` tags its generation, so the launch it tells the user to run reuses the container immediately and is not refused as "still owned by an attaching launch" (3d291aeb). PID-exhaustion advice for a fresh launch that PM already removed says to retry the launch, not to restart a container that no longer exists (76e1443e).
- Pane release after workdir deletion: the impl/review/sign-off pane EXIT release still works after `pm pr cleanup` or merge teardown has deleted the pane's cwd (3c9ab152). `pm tui restart --breadcrumb` logs its save/skip decision at INFO (9abd3c07).
- Popups and proxy reporting: a `pr start` launched from a popup labels the container with the session's project root (`-C`/`PM_PROJECT`), not the viewed PR workdir clone. Reap and `session cleanup` print `stopped  push proxy <dir>` for proxies they stop (9d26eb3a).
- Status output: `pm container status` lists only this runtime's retention markers (61cf62b5), and no longer lists a retained container that cleanup has since removed (incidental fix made during this planning pass). Against a hung runtime, status finishes within one bounded probe. A legacy unlabeled container's PR status is resolved through the owning session's project, not the caller's cwd (fdf4a1d5).

Refresh on 2026-10-28 at HEAD `afc151b5` (QA fixes from scenarios 49–57 plus review-loop 090d i1–i4). Scenarios 49–57 are locked historical evidence; fresh scenarios begin at 58. Results of the 49–57 run (aggregate NEEDS_WORK): S55 and S56 PASS. S49, S50, S52, S53, S54 and S57 held their stories only after in-run fixes (ae2c2520, e2aabd97, 4276eb87/53b5d4f8, 5292bea9, 700b0157, 025c8d53), so the fixed paths need clean reruns on the current head. S51 stories 1–2 held; story 3 found two reap bugs (ebba345e, 272e3c52) and a 7 = L+2 peak that the user ruled a failure (resolution 21, fixed by 7257da86), so it is rerun.

User-visible behavior added after `76081338` that fresh scenarios must cover:
- Process pressure: a fork failure (EAGAIN/ENOMEM) during the QA poll, a verification hand-back or its follow-up Enters no longer ends the run as ERROR or orphans its workers; a flagged verification is counted once, and a follow-up is never sent twice (ae2c2520, ab2c3d56, 7e824be9). A run-end release deferred because the runtime could not run is retried on the run's own thread for a bounded time, so the stopped run's containers go away after recovery without a manual reap.
- Pane exits at send boundaries: a worker pane that exits between PM's liveness check and the verification follow-up, the verdict-format reminder or the trust-prompt accept makes that scenario INPUT_REQUIRED ("window gone") or is retried on the next tick; the QA run itself continues (bf72c4fd, afc151b5).
- Dead-worker relaunch: a successful relaunch registers the new worker pane, never the still-open concretizer pane in the same-named window; the verifier runs in the worker's window; tmux's own error is logged when a relaunch fails; a run that keeps everything logs "released containers: none (kept sN INPUT_REQUIRED)" (e2aabd97).
- Retained containers count toward `container-max-running` (7257da86, resolution 21).
- Cleanup races: a container removed by another actor (pane EXIT release vs `pm pr cleanup --resources`, a replacing `--fresh` launch) during a listing or release is not a cleanup failure and leaves no "owner release pending" record; a Podman `ps`/inspect that races a removal retakes the inventory once instead of reporting "runtime inventory unavailable" (5292bea9, 53b5d4f8, 71b8f7b8, fcb5ce9c, 4276eb87). A reap stops a shared proxy and reports it once, not once per container (272e3c52). A young container whose launch already attached and whose window then closed is reclaimed, not kept as "launching (no pane yet)" (ebba345e).
- Periodic reconciliation waits up to 60 s for a busy reaper lock held by a short scoped pass instead of skipping a whole interval; startup and keyring-pressure passes still skip (025c8d53).
- Container commits work when the host git identity exists only in the system config (700b0157).

Refresh on 2026-10-28 at HEAD `1bc65b72` (QA fixes from scenarios 58–63 plus review-loop ad53 i1). Scenarios 58–63 are locked historical evidence; fresh scenarios begin at 64. Results of the 58–63 run (aggregate NEEDS_WORK): S58 (whole PR life from implementation to merge) and S63 (periodic pass waits for a busy reaper lock) PASS. S59, S60, S61 and S62 held their stories only after in-run fixes (70cd9492, fd9bbdb4/eac0ccdd, 60ccb95e, d3d1b4fc), and review ad53 i1 then corrected 70cd9492 (1bc65b72), so those paths need clean reruns on the current head. The run that started after ad53 i1 (loop 088f8dc8) ended QA ERROR with no recorded message before any scenario ran; this planning pass replaces it.

Refresh on 2026-10-28, HEAD `fb37dc36`, code unchanged since `1bc65b72`: QA loop `42a07a34` locked scenarios 64–68 and cloned their workdirs. About three minutes later the next run (`c8dbe953`) superseded it. No scenario launched a worker or produced a verdict, and no container from that loop remained in the runtime inventory. Scenarios 64–68 are therefore locked but unexecuted. Fresh scenarios 69–73 carry their stories forward unchanged in intent: 69 = 64, 70 = 65, 71 = 66, 72 = 67, 73 = 68. They also correct the expected deferred-retry log wording to "deferred container release retried". Requirements and resolutions are unchanged.

Refresh on 2026-10-28, HEAD `06d8aaa6`, code unchanged since `1bc65b72`: QA loop `c8dbe953` locked scenarios 69–73, created their concretizer containers and windows at 23:04 CDT and began concretization. At 23:05:57 a breadcrumb restart of the host TUI (running another PR's PM code) did not resume it, because a run writes `qa_resume.json` only after launch (pre-existing gap, tracked by pr-3201ea8). Auto-start began run `6086ab24`, which killed the stale s69–s73 windows and removed their five containers. Run `b49b38db` superseded that run at 23:09 before it planned. No scenario worker launched, no verdict was produced and no container from these loops is still running. Scenarios 69–73 are therefore locked but unexecuted. Fresh scenarios 74–78 carry them forward unchanged: 74 = 69, 75 = 70, 76 = 71, 77 = 72, 78 = 73. Requirements and resolutions are unchanged.

Refresh on 2026-10-28 at HEAD `6cb6149c` (QA fix from S77, review-loop 7faf i1–i2, and an incidental fix made during this planning pass). Scenarios 74–78 are locked historical evidence; fresh scenarios begin at 79. Results of the 74–78 run (aggregate NEEDS_WORK):
- S75 (container trust dialog, TUI restart during retry backoff) and S76 (removal-race truthfulness) PASS. The code they cover has not changed since, so they are not rerun.
- S77 held every Then, but only after fix 1f6c0a5a. Before it, with `qa-verify-pass` off, finalize was skipped forever and "QA complete" never carried `[finalize: …]`. Review 7faf then moved the finalize gate and the stop downgrade onto one helper that uses the run's own snapshot of the setting. This planning pass found that the snapshot was not saved in the resume file, so a TUI restart after toggling the setting relaunched workers for PASSes that had already settled; fixed in 6cb6149c. S77 is rerun and the verification-setting paths get their own scenario.
- S74 held all product behaviour. It ended INPUT_REQUIRED only because a Then expected C's final verdict to be INPUT_REQUIRED while C's fake also scripted NEEDS_WORK, and NEEDS_WORK outranks INPUT_REQUIRED (resolution 25). It is rerun with a consistent fake.
- S78 held all product behaviour. It ended INPUT_REQUIRED on three Then wordings (resolution 26). It is rerun as final-head acceptance.
- Open items remain open, not waived: Docker parity, genuine keyring relief, delegated PID-cgroup pressure and hour-aged lock contention without a 90-minute budget (resolution 20). pr-d022825 tracks the inline dead-worker retry backoff that stalls the poll; that is pre-existing behaviour, not an acceptance criterion here.

User-visible behavior added after `1bc65b72` that fresh scenarios must cover:
- With `qa-verify-pass` off, a PASS is final as soon as it is emitted. Finalize runs, "QA complete" carries `[finalize: …]`, and a stop never downgrades such a PASS (1f6c0a5a).
- Each run reads `qa-verify-pass` once and keeps that value for its whole life, including across a TUI restart. Turning the setting on mid-run neither holds finalize nor downgrades that run's PASSes on stop, and after a restart it does not relaunch released workers to verify them. Turning it off mid-run does not cancel verification the run already requires: a PASS still needs verification before finalize, and a stop before verification still downgrades it to INPUT_REQUIRED. A run started after the change uses the new value (4558c4dd, c07609ee, 6cb6149c).

Refresh on 2026-10-28 at HEAD `d6061445` (code `b6338490`: QA fixes from scenarios 79–82). Scenarios 79–82 are locked historical evidence; fresh scenarios begin at 83. Results of the 79–82 run (aggregate NEEDS_WORK):
- S79 (two runs share a full runtime through an inventory outage, retained container counts toward the limit) and S80 (partial run-end release, deferred retry judges "viewed" at retry time, finalize with verification off) PASS with no code change. Their code is unchanged apart from 2c26ddad, which adds a snapshot write in front of the per-poll release they exercise; S85 re-covers that path under an outage.
- S81 held every Then except one: a TUI restart within one 5 s poll after a per-poll release relaunched a settled scenario ("Scenario 11 window died — retry 1/10", new container), because `qa_resume.json` was written only at the top of the poll. Fixed in 2c26ddad; the post-fix race had no relaunch. S81 is rerun on the current head.
- S82 (final-head acceptance) held its product behaviour and found two presentation defects, both fixed: after `pm tui restart --breadcrumb` the TUI mount always logged `trigger=initial` (c5d0e0ba), and a stopped run's "QA complete" line gave no reason for the missing finalize pane (b6338490). Three Then wordings conflicted with the When timing or CLI output (resolution 29). S82 is rerun with corrected Thens.
- The aggregate note's "planner edited application code" refers to the incidental fix 6cb6149c made during the previous planning pass. S81's restart stories exercised it live (story 3 post-fix resumed with the run's own "disabled" snapshot while the setting was on).

User-visible behavior added after `6cb6149c` that fresh scenarios must cover:
- A settled scenario's verdict is saved to the resume snapshot before its per-poll release removes its container and window. A TUI restart at any moment after that release resumes the scenario as settled: no "window died — retry", no relaunch, no new container, and the verdict still shows (2c26ddad).
- A stopped run's TUI line reads `QA complete: <verdict> [finalize: skipped — run was stopped]`; a completed run still carries `[finalize: <verdict>]` (b6338490).
- A merge-triggered `pm tui restart --breadcrumb` mounts the new TUI with `TUI mount: … trigger=merge_restart` in the debug log; an ordinary restart still logs `trigger=initial`. The trigger variable is consumed on mount and is not inherited by panes the TUI spawns (c5d0e0ba).

Refresh on 2026-10-28 at HEAD `bfa7fc55` (merge of master@`89e3c501` as `7bca6ee2`, plus review-loop 8101 i1–i2). Scenarios 83–85 are locked historical evidence; fresh scenarios begin at 86. S83, S84 and S85 PASSed on code `b6338490` with no code change. Sign-off (note-26335a9) then returned the PR with SIGNOFF_IMPL because 11 files conflicted with master. Master had redesigned push proxies as workdir-keyed directories (pr-748e708) and also brought provider-secret env transport (pr-84ebabf), fail-closed captures routing (pr-1e9c117), sync-detected merge integrity (pr-2e06289), task-scoped verdict detection with resume identity (pr-8efa789) and abbreviated broad-push rejection (pr-8cdbe60). The merge kept one proxy ownership model (impl A9). Every earlier runtime PASS ran on pre-merge code, so it is not acceptance for the integrated head. Sign-off asked for reruns of the proxy stories (S14/S25/S39 shape), the launch/setup stories (S27 shape) and final acceptance (S84/S85 shape). It also asked, where cheap, for a before/after reproduction of the original incident on master versus this branch.

User-visible behavior on the integrated head that fresh scenarios must cover:
- Workdir-keyed proxies: implementation, review and sign-off on the PR workdir share one socket directory, and each QA scenario clone gets its own. A request that names another clone's workdir is refused, never served from the wrong clone. A live proxy is never replaced by a request for a different workdir or branch.
- Release: a directory is released only after a locked check of the runtime inventory, done by whichever PM process runs it (reaper, pane EXIT trap, restarted TUI, run-end release). When a PR has several directories, the users' actual mounts decide. A released directory is removed together with its discovery link and start lock; master instead kept it until session teardown. Session teardown releases only directories with no runtime users. A launch holds the directory's start lock from proxy start until `run` returns, so a concurrent release cannot stop a proxy that a new container is about to mount.
- Bounded release cost: with one directory per QA clone, a release reads the PR's container mounts once per decision rather than once per directory or container (d295eb3e, bfa7fc55). A ten-scenario run's releases therefore do not hold the per-PR proxy lock long enough to stall launches (30 s acquisition timeout).
- Proxy launch failures: a proxy that does not become ready fails container creation as a classified `proxy` launch error with its real cause. The fresh directory it created is removed, and no partial container is left behind.
- Upgrade from older containers: a container created before the merge that mounts the old tokenless `(session, PR)` directory is refused on reuse. The message names the container and gives a runnable `<runtime> rm -f NAME`. After removal, the next launch recreates the container with a workdir-keyed directory. Cleanup still finds and releases the old directories once unused.
- Push-proxy option guard: `_long_option_match` now covers both the dangerous options (`--upload-pack`, `--receive-pack`, `--exec`) and the broad push options (`--all`, `--branches`, `--mirror`, `--tags`). An unambiguous or ambiguous prefix is refused, naming the option git would read it as. Look-alikes still work (`--atomic`, `--follow-tags`, `--no-tags`, `-u`, `--`). Proxy git runs with hooks disabled.
- Provider env transport: a provider secret reaches container workers only as `-e NAME` on runtime exec. It never appears in a pane start command, the debug log or the pane registry. Ownership parsing treats `exec -e NAME … <container>` as a live owner of that container and does not mistake the variable name for the container.
- Captures routing: a container records its PR as `PM_CAPTURES_PR`. A worker in a PM-created, reused, restarted or recreated container resolves `/pm-captures` for its own PR. A nested throwaway project without the marker falls back to its own host session path.
- Merged-PR reconciliation through sync: a merge found by the TUI's GitHub sync (startup, periodic or `r`) still marks the PR merged and leads to cleanup of its containers and proxies. When the merge integrity check fails, the held `Merge integrity: …` line and note appear as well. Cleanup still keeps live, retained and human-waiting resources.

User-visible behavior added after `afc151b5` that fresh scenarios must cover:
- Inventory outage at a full runtime: the run makes one floor launch, then waits for a readable inventory (log "wait for a readable container inventory"). Its settled workers whose release is unconfirmed, and workers a release deliberately kept (INPUT_REQUIRED or viewed), count as held. So INPUT_REQUIRED settlements during the outage do not each admit another launch. Peak at most L+1; after recovery the deferred releases run, the peak returns to at most L and the batch grows back (70cd9492, 1bc65b72).
- A partial run-end release, or its deferred retry, logs which viewed/INPUT_REQUIRED workers it kept even when it released others (60ccb95e).
- A container QA worker's workspace-trust dialog naming `/workspace` is accepted for the mounted PR workdir even where the host also has a `/workspace`. Any other path in a container worker's dialog is refused rather than mapped to a host directory (fd9bbdb4).
- A TUI restart during a dead worker's retry backoff resumes the retry: the resumed run relaunches the worker, never polls the concretizer for a verdict and does not hang (eac0ccdd).
- Removal races report the truth: several containers vanishing during one listing (e.g. `pm pr cleanup --resources` racing a pane-exit release) are retaken and do not leave "runtime inventory unavailable; proxy preserved". A review/sign-off `--fresh` replacement that removes the old allocation before the old pane's release records itself does not leave "owner release pending" in status when the inventory is complete. With an unreadable inventory, status still lists it (d3d1b4fc).

Source grounding:
- `pm_core/container.py`: serialized launch/reuse, completed setup/config probes, runtime cause classification, ID-specific EXIT cleanup, PID recovery, bounded creation and legacy cleanup.
- `pm_core/container_reaper.py`: exact pane ownership, scope, retention, launch grace, pre-delete rechecks, bounded removal, persisted failures and unused-proxy cleanup.
- `pm_core/push_proxy.py`: cross-process runtime ownership, proxy lock, socket directories and owner records.
- `pm_core/qa_loop.py`: asynchronous start-of-run sweep, launch-error recording, queued work/headroom, resume re-ensure, final release and human/viewed-window exceptions.
- `pm_core/cli/pr.py`, `cli/qa.py`, `signoff.py`: launch failure cleanup, tagged replacement and merge release.
- `pm_core/pr_cleanup.py`, `tui/app.py`, `tui/sync.py`: startup/periodic/merged reconciliation and visible outcomes.
- `pm_core/cli/container.py`, `cli/session.py`, `wrapper.py`, `tmux.py`: CLI recovery and client/session/code routing.

## Shared-resource inventory and concurrent coverage

| Shared resource | Competing actors to exercise |
| --- | --- |
| Runtime daemon/container namespace, deterministic impl/review/sign-off names and immutable IDs; QA PR/loop/scenario/attempt identities and labels | Two PRs and repeated attempts with identical scenario numbers, overlapping restart/launch/reap, runtime rename and delayed old-process exit; scenarios 20–24, 27, 31 |
| Per-name launch locks, ID/domain-bound attachment leases, generation tombstones and foreground activity locks under the isolated container-state directory | Launch/restart/reaper processes racing on the same allocation, including rename/replacement after inventory and genuinely aged lock contention; scenarios 20, 24, 29, 33 |
| Global reaper/outcome locks, background queue, durable ID/domain/generation-bound releases, `reaper.json` and atomic temporary files | Simultaneous scoped/manual/startup/run-end/bulk cleanup with partial failures, interrupted ownership handoff and later retry; scenarios 21, 23, 26, 31 |
| Retention markers bound to runtime domain and immutable ID | Retain/release concurrent with reconciliation, rename and same-name replacement; scenarios 23, 24 |
| tmux default/current/labeled/shared sockets; base/grouped sessions; pane/window identity, descendant process ownership, attached-client focus and pane registry | Multiple live clients and servers during cleanup/restart/popup use, including inaccessible process snapshots and equal pane numbers on different sockets; scenarios 20–24, 26, 32 |
| Shared `(session, PR)` and unshared push-proxy daemons, actual mounted socket directory, hashed/legacy aliases, `owner.json`, socket inode identity, locks and local reference maps | Separate launcher processes share/repair a proxy while another exits; last-user release races with fresh launch and late old-daemon exit; two isolated runtime domains share lifecycle/proxy paths only within the scenario; scenarios 23–25 |
| Global settings, per-process create semaphore, QA queues/resume files, runtime-wide running-container headroom | More workers than configured slots, concurrent runs/processes, cleanup and settings applied to newly started processes; scenario 31 |
| Kernel keyring quota, memory/PID cgroups and process trees | Several actual workers plus running leftovers; bounded recovery only in a qualified disposable supported environment; diagnostic injection distinguished from real pressure; scenarios 27–31 |
| Host workdirs, scenario clones/scratch, captures, transcripts/config, hook events, session/runtime/registry state, disposable Git origin | Concurrent worker writes and cleanup/relaunch, serialized commits when roles share a workdir; scenarios 20, 21, 25–28 |
| Session PM-root/override and fake-agent configuration; popup caller cwd and client identity | Two clients with different sessions/configuration invoke popups concurrently from PR workdirs; scenario 32 |
| PR workdir `.git` (hooks directory, refs, index) writable by the container and operated on by host git; push-proxy daemon command parsing | A worker plants hooks while host-side pr start/sign-off integration/QA publish/status run and another worker pushes through the same shared proxy; scenario 40 |
| Process locale seen by TUI, reaper and QA release | C-locale and UTF-8 TUI/reaper processes reconciling the same runtime; scenario 42 |

These resources are shared within a scenario only. No scenario relies on another scenario's files, daemons or state. Fresh scenarios 34–48 re-cover every row on HEAD `8c5fad86`: runtime namespace/identity (34–39, 43, 44), locks/leases (38, 48), reaper outcomes (37, 42), retention (37, 38), tmux sockets/clients (34–38, 42, 45), push proxies (39, 40), headroom/queues (44), kernel pressure (46, 47), workdirs/evidence (all), popups (45). Fresh scenarios 49–57 re-cover them on HEAD `76081338`:
- runtime namespace/identity: 49–53, 55
- locks/leases: 52, 57
- reaper outcomes: 51, 53, 57
- retention: 53, 55
- tmux sockets/clients: 49, 50, 54, 55
- push proxies: 52–54
- headroom/queues: 51
- process trees/PID: 49, 56
- workdirs/evidence: all
- popups: 54
- locale: 55

Fresh scenarios 58–63 re-cover them on HEAD `afc151b5`:
- runtime namespace/identity: 58, 59, 62
- locks/leases: 62, 63
- reaper outcomes: 61, 62, 63
- retention: 59, 62
- tmux sockets/clients: 58, 60, 61
- push proxies: 58, 62
- headroom/queues: 59, 61
- process trees/PID: 61
- workdirs/evidence: all
- popups: none changed since S54 PASS; not re-run
- locale: none changed since S55 PASS; not re-run

Fresh scenarios 64–68 re-cover them on HEAD `1bc65b72`:
- runtime namespace/identity: 64, 66, 68
- locks/leases: 66
- reaper outcomes: 66, 67
- retention: 64, 67
- tmux sockets/clients: 65, 67, 68
- push proxies: 66, 68
- headroom/queues: 64
- process trees/PID: none changed since S61; not re-run
- workdirs/evidence: all
- popups/locale: none changed; not re-run

Fresh scenarios 69–73 carry 64–68 forward, unexecuted, with the same coverage map (69 for 64, 70 for 65, 71 for 66, 72 for 67, 73 for 68).

Fresh scenarios 74–78 carry 69–73 forward, unexecuted, with the same coverage map (74 for 69, 75 for 70, 76 for 71, 77 for 72, 78 for 73).

Fresh scenarios 79–82 re-cover them on HEAD `6cb6149c`:
- runtime namespace/identity: 79, 82
- reaper outcomes: 80, 82
- retention: 79, 80, 82
- tmux sockets/clients: 80, 81, 82
- push proxies: 79, 82
- headroom/queues: 79
- global settings read by concurrent runs (`qa-verify-pass`): 81
- QA resume snapshots: 80, 81
- workdirs/evidence: all
- Not rerun, because their code is unchanged since a PASS: locks/leases (S63), removal races (S76), trust dialog and retry-backoff restart (S75), process trees (S61), popups (S54) and locale (S55).

Fresh scenarios 83–85 re-cover them on HEAD `d6061445` (code `b6338490`):
- runtime namespace/identity: 84
- reaper outcomes: 84, 85
- retention: 84, 85
- tmux sockets/clients: 83, 84, 85
- push proxies: 84
- headroom/queues: 85
- global settings read by concurrent runs (`qa-verify-pass`): 83
- QA resume snapshots: 83, 85
- workdirs/evidence: all
- Not rerun, because their code is unchanged since a PASS: cross-process outage admission (S79), deferred whole-run retry (S80), locks/leases (S63), removal races (S76), trust dialog (S75), process trees (S61), popups (S54) and locale (S55).

Fresh scenarios 86–90 re-cover them on HEAD `bfa7fc55` (integrated code):
- runtime namespace/identity: 88, 89, 90
- locks/leases (proxy start lock vs. release): 86
- reaper outcomes: 86, 88, 90
- retention: 88, 90
- tmux sockets/clients: 86, 88, 89, 90
- push proxies (workdir-keyed directories, discovery links, start locks, legacy tokenless directories, option guard, hooks): 86, 87, 88
- headroom/queues: 90
- QA resume snapshots and verdict sources: 90
- provider env and pane commands: 89
- captures mount (`PM_CAPTURES_PR`): 89
- GitHub sync merge reconciliation: 88
- workdirs/evidence: all
- Not rerun, because their code is unchanged by the merge since a PASS: locale (S55), popups (S54), process trees (S61) and verify-pass toggles (S83). S90 samples them only incidentally.

## Setup

1. Follow `pm/qa/instructions/tui-manual-test.md`: use a throwaway git project with an initial commit, local bare origin and local backend; add PRs through PM and start its own named tmux session. Run PM commands in panes belonging to the test session, not the controller session. Confirm `pm which` selects this PR's code, overriding inherited `PYTHONPATH` when needed. Use `./install.sh --local` if PM is missing.
2. Isolate HOME, PM settings/state (including `PM_CONTAINER_STATE_DIR`), tmux sockets, runtime storage and capture paths for each scenario. Preserve required runtime environment such as a working rootless runtime directory. Do not mount or reap the production host runtime, change the user's real settings, or kill controller containers. Nested Podman requires bootstrap `project.nested_podman: true` and normal `pm container enable`.
3. Use real PM-created containers and a working developer image. Rootless Podman is the primary runtime; also run compatible cleanup/setup/launcher stories against Docker when accessible. Missing runtime/image/nesting/cgroup support is a blocked test with evidence, not PASS.
4. Use the bundled fake agent through `pm fake-claude config set` for deterministic delayed outcomes and rework, cancellation and human-wait flows. It controls the agent, not PM's container/tmux/proxy/cleanup implementation. Ensure configuration follows the actual session tag. Obtain valid session-type/verdict pairs from the bundled example and CLI help. Do not make paid provider calls or reconfigure provider accounts.
5. Establish all required PR status/workdir/config bootstrap state before driving a story. After bootstrap, use CLI/TUI actions, not edits to live project state, registry files, verdict maps or cleanup outcomes. Fault induction may use disposable images, terminating a test process/proxy, or an explicitly documented runtime-boundary fault harness; it must still drive a public PM action and cannot substitute imported PM functions for that action.
6. Save timestamped runtime inventories (IDs, names, state, ownership metadata), tmux panes/clients, process/PID statistics and keyring readings where supported. Record the relevant keyring UID, not just an unrelated most-utilized row. Measure startup latency and peak concurrent runtime operations during bounded-load stories.
7. Put distinctive source edits, an unpushed commit, capture files, scratch evidence and transcript content in their appropriate host-backed locations. Record paths and hashes before teardown and prove they remain accessible afterward. Never capture credentials or the contents of authentication configuration; check presence/usability only.
8. Read applicable regression guidance: `launch-dedup.md`, `restart-dedup.md`, `multi-window-registry.md` and `session-resume.md`. Adapt their user-visible invariants to the current PR workflows; their older cluster workflow is not itself a changed surface. New mocked coverage in `tests/test_container_lifecycle.py` and popup/PR-cleanup tests informs gaps but cannot replace real integration evidence.
9. Use `tmux-screen-recording.md` for TUI/popup stories and `cli-recording.md` for CLI interactions, with all prescribed transcripts, casts, H.264 MP4s and manifests, plus inventories/timings/checksums. Record a tooling fallback explicitly. `web-ui-recording.md` does not apply because these scenarios do not drive a browser UI.
10. Clean up only the scenario's own containers, sessions, proxies and background processes after evidence is saved. Controlled load has fixed process/container counts and a watchdog; never use an unbounded fork bomb, exhaust the host keyring, or change host kernel quotas.
11. Qualification must precede faults: verify nested-Podman opt-in in a writable disposable project's bootstrap, real runtime graphRoot/runRoot, an image that can create/exec a PM worker, and an allowed push to an absolute `file://` disposable bare origin using `/usr/bin/git` for host fixture operations. Never use the inherited outer-PR Git wrapper for fixture origins. Keep runtime selection `podman` or `docker`; a documented PATH forwarding shim may gate only named test operations. Record the original Chromium/inotify smoke failure if encountered. The previously authorized smoke-step-only image workaround must be explicitly labeled and must not be reported as a successful unmodified build-base; do not omit other setup checks or change host quotas. If qualification still fails, preserve evidence and mark dependent stories blocked.
12. Author fresh instructions through `pm qa add-instruction`; actual QA starts through the TUI or `pm qa run <instruction-id> --pr <canonical-id>` in the disposable session. `pm pr qa` is not a shell launcher and `pm pr show` is unavailable on this baseline. Debug takes an instruction ID (`pm qa debug`), uses the `qa_author` fake role and an unshared proxy. Configure held fake roles with empty verdict maps and bounded holds, including `_all` coverage for concretization. Verdict emission does not itself terminate an interactive TTY.
13. Distinguish terminal recordings from native agent transcripts. Enable supported transcript options for manual implementation/review/sign-off when testing native transcript preservation. Debug exposes no native transcript option on this baseline (tracked by pr-b28e042); test its real terminal recording and durable files, never fabricate a JSONL or require that unrelated missing feature for lifecycle PASS. Recorder clients count as viewers: move ordinary recording clients to the dashboard before asserting disposal; dedicate a separate client when testing deliberate viewed-window retention.
14. Deterministic race evidence needs an operation-specific boundary acknowledgment, not an arbitrary sleep. Use unique gate IDs, log actor PID/argv and immutable allocation IDs, verify PATH inheritance, and release short inspect gates inside their runtime timeout. Preserve genuine runtime output/status except for an explicitly identified fault. For tmux launch faults, use a one-shot external argv delegator preserving socket/options and changing only the armed window/split target to a nonexistent target before executing real tmux. Do not import PM helpers, edit live lifecycle records, or fake agent verdicts after launch. Use independently bootstrapped subfixtures for unrelated races; create age-qualified records through public actions and real elapsed time, not timestamp edits. Same-PR roles share a workdir, so serialize distinct commits/pushes while overlapping cleanup with a surviving worker's push.

15. Foreground debug is the intentional exception to the inside-tmux instruction: start it from a genuine non-tmux PTY in the disposable project without spoofing TMUX variables. It now derives project ownership. Other session-bound launchers still run in the actual disposable PM session.
16. Install the host fake executable before starting the TUI; keep concretizers alive longer than their 15-second grace (use a bounded 180-second hold or a documented longer finite budget). Fake sequence counters are role-wide and interactive s0 may consume an entry. Use ten contiguous scenarios to exercise s1/s10, not a sparse plan. A single `pm qa run` worker is not a substitute for multi-scenario/multi-attempt TUI QA. Restart the TUI with its genuine breadcrumb/snapshot; no `pm qa resume` or `pm session resume` command exists.
17. Split prerequisite-heavy coverage: Docker USER-pm setup (28; fresh 47), delegated PID pressure (29; fresh 46), isolated genuine keyring relief (30; fresh 46), and real hour-aged lock contention (33; fresh 48) have independent qualification. A blocked prerequisite does not waive it or prevent the ordinary Podman/setup/child-reaping scenarios from running. Record proxy process state explicitly: an exited zombie is not a running listener, but is not evidence of successful process reaping; preserve the existing pr-2111fa0 dependency if outer PID1 prevents disappearance.
18. Use current CLI semantics: safe preview is `container reap --dry-run` or `session cleanup --dry-run`, never legacy `container cleanup`; PR resource cleanup is explicit destructive teardown. Session kill must be driven from a surviving control session with the target directory, and does not promise a removal count. Absent telemetry is annotated in evidence even when CLI simply omits it. Manual reap callers serialize; use a separately acknowledged full-reap/explicit-cleanup interleaving to test stale outcome writes.
19. Fixture lessons from 20–33: use fake holds of at least 86400 seconds when a worker must outlive the story; make any fixture runtime wrapper executable (otherwise PM silently uses the real binary); read launcher output only after a per-attempt begin marker; close a leftover review window before a trial that must allocate (review otherwise only focuses it); `pm qa debug` clones locally so the PR branch must exist as a local ref; prefer an overlay storage driver over VFS for build budgets; PM resolves runtime storage through XDG paths, so record `podman info` graphRoot/runRoot rather than trusting `CONTAINERS_STORAGE_CONF`. Never kill the fixture TUI pane in a way that triggers the after-kill-pane respawn in an unrelated cwd: that runs an unscoped startup reconcile that legitimately removes unowned fixtures. Isolated fixture setup must not be run through a worktree-constrained helper that refuses isolated HOME (S32 blocker).

20. Fixture lessons from 34–48:
    - Environment and PATH:
      - Put the host fake-claude directory (`/workspace/bin`) on the PATH, plus a non-provider `claude` stub, since `pr start`/meta call `find_claude`.
      - tmux 3.2a ignores `respawn-pane -e PATH`, so respawn the TUI as `env PATH=... pm _tui`.
      - asciinema refuses a C locale: record under C.UTF-8 and run only the attached client under C.
    - Storage and image:
      - `/tmp` is overlayfs, so private Podman storage needs `mount_program=fuse-overlayfs`.
      - `build-base` needs the Dockerfile beside the project's `pm_core` copy.
      - New PRs need `pm push` and a merge of the `pm/sync` branch before `pr start`.
    - Podman 3.4.4 and git:
      - Podman 3.4.4 `rm` has no `-t`; use kill plus `rm -f`.
      - `git -C /workspace push` bypasses the container git wrapper (pr-a6e74e3); push with `podman exec -w /workspace`.
    - Fake agent:
      - The fake verdict cursor clamps at its last entry, so supply one entry per consumer.
      - Scenario numbers renumber across attempts.
    - Ownership fixtures:
      - Closing a PM-launched pane writes an owner-release record. Make unowned past-grace fixtures with `pm container restart --force` and wait more than 120 s.
      - Gates on inspect/list-panes must release within their 10 s or 5 s probe timeout, and must match tmux argv after `-S <sock>`.
    - PID budget: in a worker whose PID 1 does not reap zombies, size worker counts to the cgroup PID budget and record it.
    - Budget-heavy stories: dead-worker retry backoff and hour-aged lock aging need a declared wall-clock budget of up to 90 minutes. S35 showed that such a budget can be completed.

21. Fixture lessons from 49–57:
    - Shared Podman store with private tmux servers: one fixture's reap removes another fixture's containers whose tmux session it cannot see. Run independent fixtures sequentially or give each its own store.
    - Nested containers have no cgroup of their own; `podman stats` PIDs is the shared outer counter. Per-container process evidence comes from `podman exec ps`. Run any `sleep infinity` zombie control after PM iterations and remove it first.
    - Nested `podman run -d` decoys need `--uts host`. Create `$HOME/.claude` in an isolated HOME or container transcripts never reach the host.
    - Removal recheck inspect has a 10 s timeout and tmux probes 5 s; gates that must outlast them hold ≥12 s, gates that must not hold ≤4.5 s.
    - A worker whose PID 1 does not reap zombies should run the session under a child-subreaper loop so conmon zombies do not exhaust the PID budget (S49).
    - Fresh PR branches have no upstream: push with `git push origin HEAD`. `pm pr review` on a sign_off PR moves it back to in_review; reset status with `pm pr edit --status` before re-running sign-off.
    - Plain `pm pr start` after a forced restart only focuses a companion-only window (pr-bbad0d0); close the companion first.
    - Deleted-cwd releases may log to `~/.pm/debug/default.log`; grep every `~/.pm/debug/*.log`.

22. Fixture lessons from 58–63:
    - A grouped session (recorder or viewer) whose name does not start with `pm-` breaks TUI QA start (pr-5d90350). Name viewer sessions `<pm-session>~N`.
    - The fake planner needs a committed `pm/specs/<pr>/qa.md`. Interactive s0 consumes the first scripted `qa_scenario` fake entry. The fake config rejects non-dict `_` keys. Delete `~/.pm/sessions/<tag>/fake-claude.state` before a run whose launch cursor must restart.
    - The PM debug log contains NUL bytes: use `grep -a`. `pm pr signoff` needs a shell inside the PM tmux session.
    - QA scenario panes have no EXIT-trap release, so a closed INPUT_REQUIRED window is reclaimed only by a scoped reap, the next run-start reconcile or the ten-minute periodic pass.
    - Impl/review/sign-off panes do have an EXIT release (removed within about 2 s of kill-window). The young-abandoned path needs the pane's process group SIGKILLed.
    - The TUI periodic reconcile fires every 600 s from TUI start/restart; schedule faults away from it. For a fork-failure fault, use a strict soft limit; a limit equal to the current thread count lets forks through.
    - tmux 3.2a `display -t <gone pane>` exits 0. Install a fake-claude stand-in (e.g. one that first shows a trust dialog) by link plus rename-over, never `mv`. Use `setsid nohup` for a long nested `build-base`.
    - Long holds on a busy reaper lock need chained gates: inventory `ps` times out at 30 s and inspect at 60 s.

23. Fixture lessons from 74–78:
    - Reusable drivers: S59/S74 (two PM processes, outage shim, sampler, `owners.py`), S77 (PATH podman stand-in that fails everything except `info` while a flag file exists, grouped viewers `<S>~8`/`<S>~9`) and S78 (two-PR repeated runs, nogit image). Replace their hard-coded `/scratch/sNN` roots.
    - Finalize polls for at least 30 s (verdict grace). A runtime fault meant to defer the run-end release must last at least 60 s and begin before the late verdicts, or it clears before the run ends.
    - The host fake-claude must be on the TUI's PATH. Without it the planner exits and the run ends ERROR.
    - With `qa-verify-pass` off, PASS settles when it is emitted, so no verifier pane appears. With it on, the verifier is the third pane of the scenario window (after concretizer and worker).
    - `t` on a PR whose QA window is still open only focuses that window; use `z t` for a fresh run. Plain `t` on a completed QA also only focuses.
    - A nested `podman build` here needs `--uts host`. Launch decisions by two PM processes can read the same pre-launch sample; record such pairs rather than asserting cross-process admission (resolution 24).
    - `pm set qa-verify-pass on|off` writes the global setting that every PM process reads; record the time of each toggle against the run's "PASS verdict verification is enabled/disabled" log line.

24. Fixture lessons from 79–82:
    - Reusable drivers (captures `scenarios/<N>/drivers`): S81 (`keys.sh` to the TUI pane, `inpane.sh` for commands in a new session window, `mkcfg.py`, 1 s `podman ps -a --no-trunc` sampler, 2 s `list-panes -a` timeline mapping verifier panes to windows) and S82 (`drive.sh` stamping `[t0]`/`[rc t1]` in a recorded shell window, `sel.sh` pressing real h/l until `pm tui view` shows the wanted card, recorder `pm-<tag>~N` on a separate `tmux -L rec` server pinned to window 0, `wd.sh` workdir hashes). Retarget their hard-coded `/scratch/s81`, `/tmp/s82` roots.
    - To hit the per-poll-release restart race deterministically, fire `pm tui restart --breadcrumb` from a watcher that tails the debug log and triggers on the scenario's release line (S81 post-fix fired within the same second). A restart one full poll later passes even pre-fix.
    - The debug log is `~/.pm/debug/<tag>.log`, where the tag already begins with `repo-`/`proj-`; name it exactly, a glob matches one log per QA clone tag.
    - fake-claude writes its transcript only when it emits a verdict, so held workers that never emit have dangling transcript links. That is a fixture property, not data loss.
    - A dashboard watcher must target pane `qa-<pr>.1` (QA Status), not the window's active pane (the planner).
    - A 2 s pre-launch sample can race another process's removal; pair cross-process admission claims with shim ordering or a 0.25 s sampler (S79).
    - `pm pr review` prints "Opened review window"; `pm container status` has no proxy lines (list proxy dirs and process state separately); nested `podman run -d` decoys need `--uts host`.

25. Fixture lessons from 83–85 and the merge:
    - QA panes call `fake-claude` by name, so link `$R/bin/fake-claude` as well as `claude`. A run that ends ERROR consumes fake entry 0, so set the config again before retrying.
    - On a PR with earlier QA runs, `t` only focuses its QA window; use `z t`. A run-start reconcile reaps the previous run's kept INPUT_REQUIRED worker.
    - Gate a "run is live" step on the log line "Running N scenario(s)", not on containers being Up (workers start after concretizers). A watcher for per-poll releases must match "removed [1-9]", because resumed polls log "removed 0".
    - To provoke an outage without failing launches, make the podman stand-in fail only `ps --filter` (S85).
    - Proxy directories live under `/tmp/pm-push-proxy-*` as either a readable `<tag>-<pr>-<token>` name or a 16-hex hash with a discovery link. Each has `owner.json`, `proxy.json` and a sibling start lock. `/tmp` is shared by every fixture in a worker, so filter by session tag and record names, inodes and daemon PIDs before and after each step.
    - Pre-merge code for upgrade and incident stories: `a70331c1` (this branch before the merge) and master `89e3c501`. Install each with `./install.sh --local` from a separate checkout, confirm it with `pm which`, and switch back to HEAD the same way. Never run old code against the controller's runtime.

## Requirements — user stories

### R1 — Successful and reworked QA releases its own resources
Given a container-mode QA run with delayed PASS/NEEDS_WORK then PASS workers and durable evidence, when the user lets the run finish, then disposable scenario containers stop running without waiting for the next run, the verdict/rework history remains visible, and source changes, captures, transcripts and clones remain readable.

### R2 — Stop and supersede release abandoned work
Given an active QA run with workers and queued scenarios, when the user stops it, then abandoned workers are released, no stopped/unlaunched worker acquires a fabricated agent verdict, and its evidence remains. A scenario that emitted PASS but whose verification never ran is reported INPUT_REQUIRED, not PASS, and a stopped run opens no finalize pane. "Verification" here follows the run's own `qa-verify-pass` value, read once when the run starts polling and kept across a TUI restart. A run with verification off treats PASS as final: a stop keeps it, and a completed run finalizes. A later toggle affects only runs that start afterwards. A stopped run's "QA complete" line says why there was no finalize: `[finalize: skipped — run was stopped]`. Given a stopped or completed attempt with leftover containers, when the user starts another attempt, then the new run starts without waiting serially for the previous attempt's cleanup and old workers are eventually reclaimed.

### R3 — Human input and discussion survive nondestructive cleanup
Given a scenario actually awaiting human input, an explicitly retained discussion container and another live PR/session, when the user runs ownership-aware cleanup, then their containers and required proxies remain usable and the preview explains why they are kept. Given a completed scenario viewed by a client in a base or grouped session, when that QA run finalizes, then the viewed scenario remains available for inspection. An aggregate INPUT_REQUIRED status alone does not make every failed or unowned worker immortal.

### R4 — Exact ownership defeats scenario-number collisions
Given two PRs, old/new QA attempts and scenarios with identical numbers including s1/s10, when the user stops or supersedes one attempt, then unrelated windows cannot keep its abandoned containers alive and the other PR/current attempt continues working. The same protection applies across project/session tags and labeled tmux servers.

### R5 — Launch/restart and cleanup serialize safely
Given cleanup and a fresh launch/restart of the same deterministic name are in flight, when a second actor starts the competing action, then one serialized outcome occurs without deleting a newer container or leaving its session attached to a missing container. An old pane's late EXIT cleanup cannot delete its replacement. A retain action or real owner attached before deletion must be respected.

### R6 — Shared push access survives another worker's exit
Given implementation/review/QA containers launched by separate processes for one session/PR share a push proxy, when one worker finishes or is reaped, then surviving workers can still push the allowed branch to the disposable origin and disallowed branch pushes remain rejected. Given no remaining container needs the proxy, when cleanup finishes, then the unused daemon/socket is reclaimed; an overlapping new launch keeps or restores usable push access. On the integrated head, the "share" applies to implementation, review and sign-off on the PR workdir; each QA scenario clone has its own directory, and a container can never push another clone's commits.

### R7 — Startup and periodic reconciliation recover leftovers
Given expired-grace orphaned containers from merged/closed PRs, dead sessions and abandoned attempts, when the user starts/restarts the TUI, then background cleanup eventually removes leftovers while preserving active/retained resources and host evidence. Given leftovers appear after startup, when the user leaves the TUI running through its ten-minute cleanup interval, then they are reclaimed without another QA run. Navigation and status refresh remain responsive throughout slow cleanup.

### R8 — Recovery CLI is scoped and observable
Given a mixture of stale, owned, retained, legacy-named and unrelated containers, when the user requests a dry-run scoped by PR/session, then output identifies only matching resources with keep/remove reasons and changes nothing. Given the same scope, when the user applies cleanup, then output truthfully summarizes removed/kept/failed items and available running/keyring before/after counts. `pm session cleanup` uses the current session, including from a grouped session, rather than another caller's session. Explicit include-retained removes retention protection but not live-owner protection. Legacy destructive cleanup remains a distinct explicit operation and never selects substring-only names such as `npm-cache`.

### R9 — Cleanup failure remains retryable
Given one runtime removal fails while others can succeed, when the user applies cleanup, then successes complete, the CLI fails visibly for the failed item, and container status reports a retryable failure. Given the fault is removed, when cleanup is retried, then the leftover and its unused proxy are removed and the old failure clears. Concurrent cleanup callers do not corrupt the outcome or lose a run-end release request.

### R10 — Launch failure preserves cause and does not become a verdict
Given a runtime/setup/config/proxy failure, when the user starts a worker through a changed launcher, then the actual cause is visible in terminal/TUI/log evidence with an available recovery command, no partial container or unused proxy is silently abandoned, no unintended host-agent fallback appears, and QA distinguishes launch failure from an agent-authored verdict. Implementation may deliberately fall back to its current terminal only after proving failed tmux allocation disposal safe; live/unknown ownership or failed disposal must not permit a duplicate. Keyring, memory, PID, missing-image and timeout errors must not all become the generic memory-pressure timeout. Preparation/clone/instruction-copy and concretizer-poll failures follow the same no-fabricated-verdict rule in host and container modes; a timeout must not claim deletion of a preserved reused allocation.

### R11 — Retry completes setup before agent startup
Given an earlier setup was interrupted before or after initial readiness, or required copied configuration/proxy readiness is missing, when the user retries/resumes the session, then PM either finishes setup safely or recreates the incomplete container, starts with required usable configuration and push access, and does not detour into missing-config onboarding. A complete healthy reusable container need not be recreated. Failed readiness exec, post-setup or final verification on an existing allocation preserves its ID/files and reports the actual classified PID/memory/keyring/runtime cause; even missing completion/config after attempted in-place repair does not authorize recreation. Only confirmed missing initial readiness with successful test execution, known unowned state and no retention/lease permits recreation. An unrelated live owner of an incomplete/unhealthy container must not be killed to recover another launch.

### R12 — No-pane launch failure releases newly allocated containers
Given container creation succeeds but the worker window cannot launch, when the user starts implementation, review, sign-off, QA or QA debug, then the failure is visible and its newly allocated unused container/proxy is released. If a real worker pane was already created before a later layout/companion operation failed, the user must not receive duplicate worker sessions or lose the working container merely because the later operation failed.

### R13 — PID exhaustion is diagnosed and recoverable without data loss
Given a PM container near its enforced PID limit, when the user checks container status or cleanup preview, then PID pressure and an appropriate restart command are visible. Given it has a live owner, when the user requests ordinary restart, then PM refuses with an explanation and leaves the session usable. Given explicit force authorization for that disposable test session, when the user forces restart, then processes are cleared, the container ID/files/mounts remain and lower PID usage is reported. Given a fully configured but unowned PID-exhausted container, when the user resumes/reuses it, then restart-in-place or a clearly reported recovery outcome allows the launch without conflating it with keyring pressure.

### R14 — New containers reap orphan processes
Given a real PM-created container and a finite repeated workload that leaves adopted children, when the user lets that workload settle, then zombies/PID usage do not accumulate across repetitions and stop/recovery does not require raising limits.

### R15 — Queued work and launch concurrency remain bounded
Given more QA scenarios than configured creation slots and constrained running-container headroom, when the user starts the run, then the configured per-process creation bound is observed, excess work is visibly queued, and later batches progress to completion without indefinite starvation or linear orphan accumulation. Given another process is also launching/cleaning up, when a second run begins, then exact ownership is preserved and pressure/failure is visible rather than silently overcommitting or misreporting verdicts. Measure peak running counts over the entire run, not just its first launch batch. When headroom was reduced by a full or unreadable inventory at an earlier launch, later queued launches grow back toward the configured batch once headroom returns. A run's containers retained for a human (INPUT_REQUIRED) or otherwise kept count toward the limit: with a readable inventory, a run holding a retained container does not launch further queued work into a full runtime; that work stays visibly queued until room appears, and the retained container survives (resolution 21).

### R16 — Every non-QA launcher releases on end/replacement
Given real container-backed implementation, review, sign-off and QA-debug sessions with evidence, when the user ends or replaces each session, then only its obsolete container disappears, shared live resources remain and relaunch has fresh usable setup. Review/sign-off must replace the correct session-tagged container; no untagged or other-session decoy is removed instead. Host-only launch still works with container mode disabled.

### R17 — Concurrent popups stay with their caller
Given two attached clients on distinct or grouped PM sessions viewing different PR workdirs with distinct session code/configuration, when each user opens a picker/command popup, then each overlay and resulting action belongs to the initiating client/session, not the last-active client. Popup dispatch uses session PM code or its explicit override, honors that session's fake-agent configuration, and does not import unmerged PM code from the PR cwd; a normal direct shell command in that cwd retains its intentional cwd-based code selection.

### R18 — Cancellation and resume preserve settled work across preparation stages
Given QA is preparing a clone/instruction, concretizing, dequeuing, or allocating a dead-worker retry, when the user stops the run before that stage returns, then no late worker attaches, no synthetic human-wait retention/verdict is created, and allocated resources are released or visibly retryable. Given mixed completed, launch-failed, active and queued scenarios, when the user restarts/resumes QA, then settled entries are not silently replayed, active ownership remains correct and eligible queued work progresses. This holds for a restart that lands immediately after a settled worker's per-poll release removed its container: the scenario resumes as settled, never as a dead worker to retry. A middle queued launch failure must not starve later scenarios.

### R19 — Runtime identity and incomplete inventories fail closed
Given managed containers are renamed or multiple isolated runtime stores share lifecycle/proxy paths, when concurrent cleanup/reuse/restart runs, then ownership, retention, leases, releases and proxy access follow immutable allocation identity in its recorded runtime domain. Unknown/partial inventory, inaccessible ownership, malformed proxy ownership or unavailable lifecycle locks must not authorize deletion or erase retryable state. Full and scoped retries must remain possible after the fault clears. Explicit destructive cleanup and failed-attachment disposal still recheck captured IDs/generations: a missing old name alone is not proof that a renamed allocation was removed or permission for duplicate host fallback. Per resolved implementation A7, rename-safe attachment checks use immutable-ID clients or PM-managed activity locks. Arbitrary external exec by OLDNAME followed by runtime rename is not guaranteed; explicitly retain or use immutable IDs for that manual case. No substantial external-client tracking is required.

### R20 — Explicit teardown reports partial cleanup truthfully
Given one PR/session resource removal fails while another succeeds, when the user invokes PR resource cleanup, session kill or legacy container cleanup, then the successful count is accurate, the failed allocation and actual error are visible with nonzero CLI status where applicable, and status retains a retryable identity-bound diagnostic. A later ownership-aware reap must not inherit force authority merely because an earlier destructive action failed; a new live owner or replacement stays protected. A surviving container retains its mounted proxy through session teardown, and retry removes only resources now eligible.

### R21 — Current interactive owners survive without granting ownership to mere mentions
Given an ordinary shell/script pane subsequently starts a real runtime exec/attach client by exact name, full ID or supported abbreviated ID, when another user reaps or requests ordinary restart, then the live allocation is protected, including a fresh owner attached after the initial cleanup inventory. Given only a diagnostic inspect/restart command, host prompt or another container's unambiguous exec payload mentions the target, when cleanup checks current descendants, then that mention alone does not preserve the orphan. Unknown/global runtime option parsing remains conservatively protective. A failed/truncated process snapshot is unknown ownership, never proof of absence. Another tmux server's same-numbered pane cannot be treated as the local QA concretizer authorized for failed-attachment disposal.

### R22 — Diagnostics survive runtime outages without granting deletion authority
Given a genuine failed removal or pending owner release was recorded before a runtime outage, when the user checks container status during that outage, then saved errors/releases remain visible with source/domain qualification and recovery guidance. Restoring the runtime allows an identity-safe retry; displaying another domain's saved diagnostics never authorizes deleting its allocations. Original removal stderr remains visible even when subsequent absence verification also fails.

### R23 — Lifecycle ownership is locale-independent and tolerant of odd process text
Given the TUI, reaper or QA run executes under `LC_ALL=C` or an unset locale, when cleanup runs, then live tmux owners are still recognized, abandoned containers are still reclaimed and QA run-end release still happens — automatic cleanup is not silently disabled by every container appearing ownership-unknown. Given a host process or pane start command contains non-UTF-8 bytes, when reap or restart checks ownership, then the command completes with a correct or unknown-ownership decision, never a traceback.

### R24 — Container-authored git code never runs on the host
Given a worker writes hooks (pre-push, post-merge, pre-merge-commit, reference-transaction, post-index-change) into the shared PR workdir's `.git`, when the worker pushes/fetches/pulls through its push proxy and the user then drives pr start on that workdir, sign-off routing that merges the base, publishing, QA planner hand-off and workdir listing/cleanup, then every host operation still succeeds and no hook marker appears on the host. Given a worker passes an abbreviated `--upload-pack`/`--receive-pack`/`--exec` prefix through the proxy, when it runs, then the proxy refuses it naming the full option, while ordinary options (`--recurse-submodules`, `-u`, `--`) still work and allowed branch pushes still reach the origin.

### R25 — Recovery guidance is runnable and status is truthful
Given each classified launch/restart/retention refusal, when it is shown, then it names the container (not just an immutable ID) and a recovery command that exists in `pm help`. Given a pre-marker (legacy) container, when the user restarts it, then the restart is reported as successful with PID counts and the next launch finishes setup without onboarding. Given proxy failures or identity-less releases that can no longer be retried, when the user checks status or reaps, then they are shown as resolved or diagnostic-only rather than a permanent retryable failure that makes reap exit nonzero forever. Given a slow or hung runtime, when the user checks status, then it returns within its bounded probe budget rather than multiplying probe timeouts.

## Edge cases — Given / When / Then

- Given a dead pane retained by tmux's remain-on-exit behavior, when cleanup checks ownership, then that dead pane does not preserve an orphan; a truly live exact-name/full-ID pane does.
- Given a labeled custom/shared socket cannot be queried, when cleanup runs, then unknown ownership is kept for later retry rather than guessed abandoned, even for a merged PR.
- Given a container is still in its launch grace or its launch lock is held, when cleanup overlaps startup, then it is not removed before a pane can attach. Once genuinely abandoned and past grace, a later pass reclaims it.
- Given a retention/failure record belongs to a removed container ID, when a new container reuses its name, then that old record cannot retain or owner-release the replacement. Full cleanup can prune stale retention records for its successfully inventoried runtime domain and old unlocked launch-lock files using the inode recheck protocol. Activity-lock inodes and generation tombstones remain intact to protect concurrent waiters and delayed releases.
- Given a reused/restarted allocation is renamed during its attachment grace, when automatic cleanup, preflight, a competing reuse, or ordinary restart checks it, then the ID-bound lease still protects it until expiry. A different runtime store's matching ID does not inherit the lease.
- Given an unavailable runtime, when the user previews/applies cleanup, then PM reports unavailability, does not claim successful removal, and leaves unknown-use proxies intact.
- Given an existing live incomplete container cannot be repaired, when a competing launch requests it, then PM reports the incomplete state and preserves the owner rather than removing it.
- Given an existing setup-complete container has lost its shared proxy daemon, when the user resumes it, then PM restores usable branch-scoped push access or reports the actual proxy failure before treating the worker as launched.
- Given an unshared-proxy container is renamed, when reuse repairs its dead proxy or cleanup removes it, then PM uses the actual mounted directory rather than its new name. A different live allocation mounting that directory stays usable; failed or deferred socket removal remains retryable after the original container is gone, and a replacement socket is never unlinked by the old request.
- Given a runtime removal failed after owner-directed release despite a still-live worker pane, when automatic cleanup retries, then the obsolete exact ID is retried; a new replacement is protected.
- Given no keyring telemetry, Docker rather than Podman, or unenforceable nested cgroups, when diagnostics run, then available evidence remains accurate, unsupported metrics are recorded as unavailable, and lack of telemetry is not evidence of successful quota/PID recovery.

## Pass/fail criteria

PASS requires observed user-surface evidence for the relevant Then clauses, real runtime inventory proving resource release/preservation, and preserved evidence checksums. Repeated runs return to a stable baseline plus explicitly documented live/retained resources; cleanup must not depend on starting the next run. Wait for grace/async cleanup with a declared observation deadline, and record actual elapsed times; default manual grace is 120 seconds and periodic interval is ten minutes. For finite test inventories allow the configured bounded runtime timeouts plus a stated margin, not indefinite waiting.

FAIL includes any abandoned running container after completed cleanup/deadline, collision keeping unrelated old runs alive, lost live owner/proxy/new replacement, lost source/evidence, missing-config onboarding after successful setup, fabricated verdict, hidden runtime cause, missing recovery command, unreported failed cleanup, duplicate worker fallback, hung queue or TUI blocked on removal. A discrepancy with implementation is a finding, not a reason to silently relax acceptance.

BLOCKED/unsupported is required if the worker cannot obtain real runtime/image/nesting/telemetry needed for an assertion. A runtime-boundary error injection demonstrates error presentation only; it cannot establish actual rootless-keyring recovery. Do not report code searches or mocked helper tests as end-to-end QA passes.

## Ambiguities resolved

1. This phase produces the QA spec and executable scenario plan; isolated scenario workers perform the subsequent runtime QA. Planning alone makes no runtime-pass claim.
2. INPUT_REQUIRED is interpreted per live/human-waiting scenario, not as proof every container in an aggregate run is owned. Unowned stale human-wait containers become cleanup candidates once their actual owner is gone; explicit retention provides deliberate preservation.
3. Ownership-aware `reap`/`session cleanup` differ from intentional destructive legacy cleanup and PR resource cleanup. Automatic cleanup must preserve retained containers. Merge/resource actions may deliberately close PR windows; usability of retained evidence/discussion must still be demonstrated by reconnection, without promising preservation of a specifically closed tmux pane.
4. `container-launch-concurrency` is a per-process creation limit, not a global multi-process semaphore. `container-max-running` is QA batch headroom/backpressure (default zero/unlimited), not a promised universal hard admission limit. QA nevertheless checks whole-run resource growth and concurrent pressure so initial-batch-only clamping cannot conceal a lifecycle leak.
5. Keyring quota is kernel-wide and cannot safely be exhausted on the shared host. Prefer a disposable VM/runtime UID with a bounded load. If unavailable, reproduce a genuine setup failure and separately test keyring error presentation using a labeled runtime-boundary fault; actual key-count relief remains explicitly unverified.
6. PID-cgroup enforcement may be unavailable under nested Podman. Use delegated cgroups/a disposable supported runtime for exhaustion checks, otherwise report that portion blocked. A bounded orphan-child workload may still test PID 1 reaping.
7. No browser recipe is needed: changed user-facing surfaces are terminal, CLI and tmux popups. Included popup changes are in scope even though adjacent to the lifecycle bug.

8. Review6427 extended coverage to runtime renames, identity/domain-bound releases/leases, stopped owners, current-boot readiness, Docker USER pm and partial cleanup outcomes. Review0b6f additionally requires current descendant ownership with precise attachment targets/abbreviated IDs, socket-qualified handoff, foreground debug outside tmux, renamed failed-disposal protection, outage-visible diagnostics and nondestructive classified setup verification. Fresh scenarios 20–33 cover these and outstanding runtime acceptance; locked S1–S19 remain unchanged.
9. Existing S1 debug-native-transcript expectations were undriveable on this baseline; pr-b28e042 already tracks the limitation. New debug lifecycle evidence uses terminal recordings and actual durable files. Existing S4 sleeps/watchdog expiries were not proof of race ordering; fresh race stories require acknowledged boundaries. Prior blocked/partial runs remain unwaived historical evidence.
10. Isolation of Podman storage does not isolate the kernel keyring. Genuine pressure tests require a disposable VM or verified dedicated UID/resource budget with no shared users; otherwise only safe error-presentation injection and genuine non-quota setup recovery may be claimed. Foreground debug ownership outside tmux is supported and must survive a concurrent reap.

11. Implementation A7 resolves the external OLDNAME-after-rename ambiguity; QA does not demand new external-client tracking. This does not waive rename-safe PM attachments, immutable-ID clients, leases, retention, releases or actual-mount proxy cleanup.
12. The S10 outside-tmux blocker is fixed in source and needs fresh runtime evidence. S13 current-shell ownership, S12 removal diagnostics and S14 distinct-mount proxy retirement need fresh post-fix acceptance, not reuse of old passing fragments. S19's nonoverlapping grouped cleanup and missing post-launch picker navigation remain explicit fresh assertions. S11/S18 concretizer loss and un-injected setup timeouts require clean reruns, not reinterpretation as planned fault coverage.

13. Host git hook isolation and push-proxy option prefixes are incidental security fixes carried by this branch; they are in QA scope as user-visible host behavior. Config-key escapes (pr-c558b14) and positional/`--repo` local-path bypass (pr-15734c1) are tracked separately and are not acceptance criteria here.
14. Fresh 34–48 replace no locked scenario. NEEDS_WORK in 20/21/26/27 reflected defects fixed in-run; their stories are rerun on `8c5fad86` rather than inherited as passes. S22's PASS stands as historical evidence; its tolerant-decoding and locale extensions are new assertions.
15. Sign-off still exits 0 after printing a launch error (review exits 1) because auto-sequence calls it in-process; QA records the exit status but does not fail on it alone — the visible cause and absence of a leaked allocation are the acceptance criteria.

16. Impl `pm pr start --fresh` (S40 conflict) means a fresh agent session. Unlike review/sign-off, it does not discard its container first. It kills the window and relies on verified reuse (R5/R11): "a complete healthy reusable container need not be recreated." Either outcome passes: a new container, or the same verified healthy ID. In both cases the old agent process is gone, no second container leaks, and a delayed old EXIT cannot remove the reused or new allocation. R16 "obsolete container disappears" applies to containers that are not reused.
17. S43 C2 "config hash matches the fixture": PM seeds `/workspace` trust into the copied `.claude.json`. Compare content apart from that PM-added trust entry; the user-visible criterion is no onboarding.
18. S43 story 4c: when PM itself removed the failed fresh allocation, the correct recovery advice is to retry the launch (76e1443e). `pm container restart NAME` is correct only when the allocation still exists. In every case the printed command must run.
19. S44 outage peak: an unreadable inventory clamps to one launch (the at-least-one floor), and deferred releases still count. While the inventory is unreadable, the run's peak may therefore reach L+1. After recovery it must return to at most L, and the batch must grow back. A larger excess, or permanent serialization after recovery, fails.
20. Prerequisite-gated S46/S47/S48 are not re-emitted to unqualified workers. A fresh scenario that runs with a declared 90-minute budget covers hour-aged lock pruning (as S35's 94-minute run did). Docker parity, genuine keyring relief and delegated PID-cgroup pressure remain open acceptance items that need a provisioned VM or Docker host; they are not waived. PID-1 orphan reaping inside PM containers (R14) does not need those prerequisites and is planned separately under ordinary nested Podman.
21. S51 retained-container peak (resolved by the user, note-6e8fde3 / controller note-c21abc7: "Count retained containers toward the limit"; impl A8). With the inventory readable, the running count may reach L+1 only through one floor launch by a run that holds no container of its own. A run whose scenario is kept for a human after INPUT_REQUIRED must not launch another queued scenario past the limit: the queued row stays "queued" until another process frees room or the retained pane is closed and reclaimed. The retained container and its INPUT_REQUIRED evidence are preserved. S51's observed A4 + B + C s1 (retained) + C s2 = 7 = L+2 fails under this rule; the S51 Then "≤ L+1" stands. The unreadable-inventory peak of resolution 19 is unchanged.

22. A run-end release deferred by a runtime outage is retried as the whole run-end release (review 090d). A window that was viewed at run end but is no longer viewed when the retry runs is released by that retry; "viewed" is judged at release time. A window still viewed at retry time stays.
23. A release recorded while the runtime identity probe failed carries no runtime domain. It never authorizes removal and `pm container status` shows it only as a diagnostic ("Unverifiable release records … not retried"), never as a retryable failure that makes `pm container reap` exit nonzero. Such records are currently never cleared even after their allocation is gone (S49 open item); that accumulation is tracked separately as pr-a4c4500 and is not an acceptance criterion here. QA does require that the stopped run's containers are actually removed after recovery.

24. S59 open question (note-c91b547): with C holding a container retained for a human, C launched only while the running count was below L. A, which held no container of its own, then made its single at-least-one floor launch, reaching L+1. That matches resolution 21: the L+1 slot belongs to one floor launch by a run that holds nothing, and a run holding a retained container never launches at or above L. No cross-process coordination of the L+1 slot is required. Scenario Thens must not assert that every peak sample has a particular composition; they assert peak at most L+1, that the retaining run never launches at or above L, and that the retained container survives.

25. S74 conflict (note-fdfd4d7): QA's aggregate verdict ranks NEEDS_WORK above INPUT_REQUIRED, a rule that predates this PR. A run with both NEEDS_WORK and INPUT_REQUIRED scenarios ends NEEDS_WORK. Thens must agree with the fake's script: a run that must end INPUT_REQUIRED scripts no NEEDS_WORK.
26. S78 wording (note-0272a1d):
    - A PR's rerun numbers its scenarios after the scenario directories that already exist, not after the launches. Expect s11–s20 only when the new run starts after all ten of the previous run's scenarios exist.
    - Identical scenario numbers collide across PRs (`qa-<A>-s11` and `qa-<B>-s11`), not within one PR. A rerun of a PR kills its own earlier run's windows first, so the overlap to test is A's current run against B's current run.
    - The final running-container count is stated as the documented kept set: live implementation sessions, retained containers and live INPUT_REQUIRED workers. It is not a baseline plus that set, which would count the baseline's members twice.
27. A setup failure whose cause is outside PM (for example an image without git) shows the classified runtime error and its real stderr. It need not name a PM command: the recovery is to fix the image or run `pm container set image …`. Keyring, memory, PID, missing-image and timeout causes must still print a runnable PM command (R25).
28. `qa-verify-pass` is per run (see R2). Where two PRs' runs overlap a toggle, each keeps its own value. QA asserts that no run hangs, skips finalize forever, relaunches a settled worker, or downgrades a PASS its own setting made final.
29. S82 wording (note-7ec30d8):
    - When a PR is rerun with `z t` before the other PR starts, the first PR's same-numbered containers are released before the other PR's same-numbered workers launch. Identical scenario numbers across PRs are therefore asserted on windows (`qa-<A>-sN` and `qa-<B>-sN` open together), scenario directories and run-scoped container names, not on two same-numbered containers running at one instant. The ownership Then is that releasing one PR's `sN` never touches the other PR's `sN`.
    - `pm pr review` reports "Opened review window"; Thens must not demand "Launched".
    - `pm container status` has no push-proxy lines. Proxy liveness is proven by an allowed push from a surviving container and by the proxy socket directory and process; reap and `session cleanup` print `stopped  push proxy <dir>` for proxies they stop.
    - The run-end release line can read "removed 0, kept K … (kept …)" when per-poll releases already removed the settled workers (note-c4b88dc). Count the earlier per-poll removal lines together with the run-end line.

30. Upgrade with pre-merge containers (impl A9, note-ea47e47). A container that mounts the old tokenless proxy directory is refused on reuse. PM does not re-point it silently. The refusal names the container and a runnable `<runtime> rm -f NAME`, and after that removal the next launch succeeds without onboarding. A Then must expect this refusal, not transparent reuse. Ownership-aware cleanup releases the old directory once no container mounts it.
31. Proxy directory lifetime differs from master's pr-748e708 spec (which kept directories until teardown). On this head a released directory is removed with its discovery link and start lock. Thens assert that the directory is gone once no container uses it, and that it is still present and serving while any container mounts it. A directory created by master code (with `proxy.json` but no `owner.json`) counts as legacy-owned and is released once unused. An unreadable or malformed `owner.json` is never proof of legacy ownership and is preserved.
32. Before/after incident reproduction (sign-off gap). Master `89e3c501` is expected to leak containers and to reuse an incomplete container into onboarding; that outcome is the baseline, not a failure of this PR. Acceptance comes only from the HEAD half of that scenario. Record genuine keyring counts for the runtime UID where they can be read, and otherwise mark them unavailable (resolutions 5 and 10).

No unresolved product ambiguities remain. This refresh (bfa7fc55) records planning only; it does not claim runtime validation.
