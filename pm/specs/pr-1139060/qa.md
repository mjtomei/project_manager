# QA spec — pr-1139060

## Scope and grounding

Baseline inspected: `git diff master...HEAD`, HEAD `86a70256`. This spec covers the container lifecycle, every changed launcher, recovery CLI, TUI reconciliation, shared push proxies, and the popup/session-routing changes included in this branch. It is an end-user integration contract, not a request to call internal helpers.

Primary surfaces: `pm pr start`, review, QA, sign-off and merge; `pm qa debug`; TUI run/stop/restart/resume/cleanup actions; `pm container status`, `reap`, `retain`, `restart`, legacy `cleanup`; `pm session cleanup`; tmux picker and command popups. No browser surface was changed. Host-only mode is a regression control.

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
| Runtime daemon/container namespace, deterministic impl/review/sign-off names and immutable IDs; QA PR/loop/scenario/attempt identities and labels | Two PRs and repeated attempts with identical scenario numbers, overlapping restart/launch/reap, delayed old-process exit; scenarios 2, 4, 8 |
| Per-name launch locks, launch grace and stale lock files under the isolated container-state directory | Launch/restart/reaper processes racing on the same name, including replacement after an inventory snapshot; scenarios 4, 7, 8 |
| Global reaper lock, background queue and `reaper.json`/temporary outcome file | Simultaneous scoped/manual/startup/run-end cleanup with a failed removal and a later retry; scenarios 3, 5, 8 |
| Retention markers bound to container identity | Retain/release concurrent with reconciliation, then same-name replacement; scenarios 3, 4 |
| tmux default/current/labeled/shared sockets; base/grouped sessions; pane/window identity, attached-client focus and pane registry | Multiple live clients and servers during cleanup/restart/popup use, including inaccessible ownership; scenarios 3, 4, 5, 9 |
| Shared `(session, PR)` push-proxy daemon, socket directory including hashed/legacy aliases, `owner.json`, cross-process lock and local reference maps | Separate launcher processes share a proxy while another container exits or cleanup runs; final removal races with fresh launch; scenario 4 |
| Global settings, per-process create semaphore, QA queues, runtime-wide running-container headroom | More workers than configured slots and simultaneous runs/processes under constrained headroom; scenario 8 |
| Kernel keyring quota, memory/PID cgroups and process trees | Several actual workers plus running leftovers; bounded failure/recovery on an isolated runtime, never host-wide exhaustion; scenarios 6, 7, 8 |
| Host workdirs, scenario clones/scratch, captures, transcripts/config, hook events, session/runtime/registry state | Concurrent worker writes and cleanup/relaunch; scenarios 1, 2, 4, 5, 6 |
| Session PM-root/override and fake-agent configuration; popup caller cwd and client identity | Two clients with different sessions/configuration invoke popups concurrently from PR workdirs; scenario 9 |

These resources are shared within a scenario only. No scenario relies on another scenario's files, daemons or state.

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

## Requirements — user stories

### R1 — Successful and reworked QA releases its own resources
Given a container-mode QA run with delayed PASS/NEEDS_WORK then PASS workers and durable evidence, when the user lets the run finish, then disposable scenario containers stop running without waiting for the next run, the verdict/rework history remains visible, and source changes, captures, transcripts and clones remain readable.

### R2 — Stop and supersede release abandoned work
Given an active QA run with workers and queued scenarios, when the user stops it, then abandoned workers are released, no stopped/unlaunched worker acquires a fabricated agent verdict, and its evidence remains. Given a stopped or completed attempt with leftover containers, when the user starts another attempt, then the new run starts without waiting serially for the previous attempt's cleanup and old workers are eventually reclaimed.

### R3 — Human input and discussion survive nondestructive cleanup
Given a scenario actually awaiting human input, an explicitly retained discussion container and another live PR/session, when the user runs ownership-aware cleanup, then their containers and required proxies remain usable and the preview explains why they are kept. Given a completed scenario viewed by a client in a base or grouped session, when that QA run finalizes, then the viewed scenario remains available for inspection. An aggregate INPUT_REQUIRED status alone does not make every failed or unowned worker immortal.

### R4 — Exact ownership defeats scenario-number collisions
Given two PRs, old/new QA attempts and scenarios with identical numbers including s1/s10, when the user stops or supersedes one attempt, then unrelated windows cannot keep its abandoned containers alive and the other PR/current attempt continues working. The same protection applies across project/session tags and labeled tmux servers.

### R5 — Launch/restart and cleanup serialize safely
Given cleanup and a fresh launch/restart of the same deterministic name are in flight, when a second actor starts the competing action, then one serialized outcome occurs without deleting a newer container or leaving its session attached to a missing container. An old pane's late EXIT cleanup cannot delete its replacement. A retain action or real owner attached before deletion must be respected.

### R6 — Shared push access survives another worker's exit
Given implementation/review/QA containers launched by separate processes for one session/PR share a push proxy, when one worker finishes or is reaped, then surviving workers can still push the allowed branch to the disposable origin and disallowed branch pushes remain rejected. Given no remaining container needs the proxy, when cleanup finishes, then the unused daemon/socket is reclaimed; an overlapping new launch keeps or restores usable push access.

### R7 — Startup and periodic reconciliation recover leftovers
Given expired-grace orphaned containers from merged/closed PRs, dead sessions and abandoned attempts, when the user starts/restarts the TUI, then background cleanup eventually removes leftovers while preserving active/retained resources and host evidence. Given leftovers appear after startup, when the user leaves the TUI running through its ten-minute cleanup interval, then they are reclaimed without another QA run. Navigation and status refresh remain responsive throughout slow cleanup.

### R8 — Recovery CLI is scoped and observable
Given a mixture of stale, owned, retained, legacy-named and unrelated containers, when the user requests a dry-run scoped by PR/session, then output identifies only matching resources with keep/remove reasons and changes nothing. Given the same scope, when the user applies cleanup, then output truthfully summarizes removed/kept/failed items and available running/keyring before/after counts. `pm session cleanup` uses the current session, including from a grouped session, rather than another caller's session. Explicit include-retained removes retention protection but not live-owner protection. Legacy destructive cleanup remains a distinct explicit operation and never selects substring-only names such as `npm-cache`.

### R9 — Cleanup failure remains retryable
Given one runtime removal fails while others can succeed, when the user applies cleanup, then successes complete, the CLI fails visibly for the failed item, and container status reports a retryable failure. Given the fault is removed, when cleanup is retried, then the leftover and its unused proxy are removed and the old failure clears. Concurrent cleanup callers do not corrupt the outcome or lose a run-end release request.

### R10 — Launch failure preserves cause and does not become a verdict
Given a runtime/setup/config/proxy failure, when the user starts a worker through a changed launcher, then the actual cause is visible in terminal/TUI/log evidence with an available recovery command, no partial container or unused proxy is silently abandoned, no unintended host-agent fallback appears, and QA distinguishes launch failure from an agent-authored verdict. Keyring, memory, PID, missing-image and timeout errors must not all become the generic memory-pressure timeout.

### R11 — Retry completes setup before agent startup
Given an earlier setup was interrupted before or after initial readiness, or required copied configuration/proxy readiness is missing, when the user retries/resumes the session, then PM either finishes setup safely or recreates the incomplete container, starts with required usable configuration and push access, and does not detour into missing-config onboarding. A complete healthy reusable container need not be recreated. An unrelated live owner of an incomplete/unhealthy container must not be killed to recover another launch.

### R12 — No-pane launch failure releases newly allocated containers
Given container creation succeeds but the worker window cannot launch, when the user starts implementation, review, sign-off, QA or QA debug, then the failure is visible and its newly allocated unused container/proxy is released. If a real worker pane was already created before a later layout/companion operation failed, the user must not receive duplicate worker sessions or lose the working container merely because the later operation failed.

### R13 — PID exhaustion is diagnosed and recoverable without data loss
Given a PM container near its enforced PID limit, when the user checks container status or cleanup preview, then PID pressure and an appropriate restart command are visible. Given it has a live owner, when the user requests ordinary restart, then PM refuses with an explanation and leaves the session usable. Given explicit force authorization for that disposable test session, when the user forces restart, then processes are cleared, the container ID/files/mounts remain and lower PID usage is reported. Given a fully configured but unowned PID-exhausted container, when the user resumes/reuses it, then restart-in-place or a clearly reported recovery outcome allows the launch without conflating it with keyring pressure.

### R14 — New containers reap orphan processes
Given a real PM-created container and a finite repeated workload that leaves adopted children, when the user lets that workload settle, then zombies/PID usage do not accumulate across repetitions and stop/recovery does not require raising limits.

### R15 — Queued work and launch concurrency remain bounded
Given more QA scenarios than configured creation slots and constrained running-container headroom, when the user starts the run, then the configured per-process creation bound is observed, excess work is visibly queued, and later batches progress to completion without indefinite starvation or linear orphan accumulation. Given another process is also launching/cleaning up, when a second run begins, then exact ownership is preserved and pressure/failure is visible rather than silently overcommitting or misreporting verdicts. Measure peak running counts over the entire run, not just its first launch batch.

### R16 — Every non-QA launcher releases on end/replacement
Given real container-backed implementation, review, sign-off and QA-debug sessions with evidence, when the user ends or replaces each session, then only its obsolete container disappears, shared live resources remain and relaunch has fresh usable setup. Review/sign-off must replace the correct session-tagged container; no untagged or other-session decoy is removed instead. Host-only launch still works with container mode disabled.

### R17 — Concurrent popups stay with their caller
Given two attached clients on distinct or grouped PM sessions viewing different PR workdirs with distinct session code/configuration, when each user opens a picker/command popup, then each overlay and resulting action belongs to the initiating client/session, not the last-active client. Popup dispatch uses session PM code or its explicit override, honors that session's fake-agent configuration, and does not import unmerged PM code from the PR cwd; a normal direct shell command in that cwd retains its intentional cwd-based code selection.

## Edge cases — Given / When / Then

- Given a dead pane retained by tmux's remain-on-exit behavior, when cleanup checks ownership, then that dead pane does not preserve an orphan; a truly live exact-name/full-ID pane does.
- Given a labeled custom/shared socket cannot be queried, when cleanup runs, then unknown ownership is kept for later retry rather than guessed abandoned, even for a merged PR.
- Given a container is still in its launch grace or its launch lock is held, when cleanup overlaps startup, then it is not removed before a pane can attach. Once genuinely abandoned and past grace, a later pass reclaims it.
- Given a retention/failure record belongs to a removed container ID, when a new container reuses its name, then that old record cannot retain or owner-release the replacement. Full cleanup can prune stale retention/old unlocked launch-lock files without breaking a concurrent launch.
- Given an unavailable runtime, when the user previews/applies cleanup, then PM reports unavailability, does not claim successful removal, and leaves unknown-use proxies intact.
- Given an existing live incomplete container cannot be repaired, when a competing launch requests it, then PM reports the incomplete state and preserves the owner rather than removing it.
- Given an existing setup-complete container has lost its shared proxy daemon, when the user resumes it, then PM restores usable branch-scoped push access or reports the actual proxy failure before treating the worker as launched.
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

No unresolved product ambiguities remain.
