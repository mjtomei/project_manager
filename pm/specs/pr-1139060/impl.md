# pr-1139060 — Container lifecycle: release, reconcile, verified reuse, real launch errors

## Background (grounded in current code)

- `pm_core/container.py::create_container` reuses any *running* container
  with the requested name (`container_is_running`) — no check that setup
  finished.  The readiness sentinel `/tmp/.pm-ready` is written by the
  in-container bash setup **before** `chown ~/.pm` and the
  `podman cp ~/.claude.json` step; a cp failure is only logged
  (`_log.warning("Failed to copy .claude.json ...")`).  A 30 s sentinel
  timeout raises a generic "memory pressure … `pm session cleanup`" error
  (that command does not exist) and leaves the half-built container running.
  `_run_runtime(... check=True)` on `run` raises `CalledProcessError`, which
  `wrap_claude_cmd` rewraps as "Is podman running?" — the real stderr is lost.
- Callers: impl `cli/pr.py::pr_start` (~L1024), review `cli/pr.py::pr_review`
  (~L1208), sign-off `signoff.py` (~L500), QA `qa_loop.py::
  _launch_scenarios_in_containers` (`create_qa_container`, ~L2274), QA debug
  `cli/qa.py` (~L549).  Review and sign-off "always remove before relaunch"
  call `remove_container(_make_container_name(label))` **without** the session
  tag, so they remove `pm-review-<pr>` while the real container is
  `pm-<tag>-review-<pr>` — the stale (possibly incomplete) container is then
  reused.  If tmux window creation fails after the container exists, nothing
  removes it.
- `build_exec_cmd(cleanup=True)` (impl/review/sign-off) installs a bash EXIT
  trap `podman rm -f <name>`; it removes *by name*, so a late trap from a
  killed window can delete a newer container with the same name.  QA
  concretizer/worker panes use `cleanup=False` — QA containers are never
  removed when a run ends (`_execute_and_finalize` docstring: "left alive …
  cleaned up at the start of the next QA run").
- `cleanup_orphaned_qa_containers` (start of every QA run, synchronous) keeps
  a container if *any* `qa-*` window ends with the same `-sN` suffix — across
  PRs and loops — the reported collision; and the new run pays for removing
  the old run's containers serially.
- `cleanup_pr_containers` (used by `pr_cleanup.cleanup_pr_resources`, i.e. TUI
  `Y`, merged-PR sync, `pm pr cleanup --resources`) only matches `-qa-`
  containers: impl/review/sign-off containers of merged PRs are never removed.
  CLI merge `_finalize_merge` only kills windows.
- `push_proxy.stop_push_proxy` refcounts shared `(session_tag, pr_id)` proxies
  **in process memory**; impl (CLI process), QA (TUI process) and review
  containers share one proxy, so the last container removed by one process
  kills the proxy other processes' live containers still use, while proxies
  whose containers were removed by traps/other processes leak forever.
- Prior art reused: commit `7b6dc7b9` (closed dup pr-4265093: name parser,
  `/proc/key-users` parsing, keyring signatures, `qa-max-containers` clamp);
  `origin/pm/pr-ac12b47` (#143, window-liveness session cleanup);
  `origin/pm/pr-cb2a29d` (#155, merged-PR cleanup on TUI startup).  This PR
  supersedes their container parts; it does not wait on them.

## 1. Requirements

### R1 — Ownership metadata on every pm container
`create_container` gains `kind`, `attempt`, `loop_id`, `scenario` inputs and
adds podman/docker labels: `pm.managed=1`, `pm.session_tag`, `pm.pr_id`,
`pm.kind` (`impl|review|signoff|qa|qa-debug|session`), `pm.loop_id`,
`pm.scenario`, `pm.attempt` (uuid per create), `pm.created` (epoch),
`pm.project_root` (pm state root, for PR status), `pm.tmux_socket` (socket of
the launching tmux server, from `PM_TMUX_SOCKET`/`$TMUX`).  Legacy unlabeled
containers are parsed from their names (`7b6dc7b9` parser, extended with
`signoff` and `qa-debug` kinds, pr ids matched against known PR ids).

### R2 — Ownership check (shared by every cleanup path)
New module `pm_core/container_reaper.py`.  A container is **owned** (never
removed by automatic or scoped cleanup) when any of:
1. a live (not `pane_dead`) tmux pane on its tmux server(s) — the labeled
   socket, the default server, and the shared-session socket for its tag —
   has a `#{pane_start_command}` that contains the exact container name
   (token-boundary match, so `…-s1` ≠ `…-s10`) or its full id;
2. it is explicitly retained (`pm container retain <name>`; marker file in
   `~/.pm/containers/retain/`);
3. a launch holds its per-name launch lock (fcntl lock in
   `~/.pm/containers/locks/container-<name>.lock`) or it was created < 120 s ago and
   no pane has attached yet (launch grace).

Otherwise it is a candidate with a reason: `PR <id> is merged|closed`,
`tmux session <s> gone`, `superseded QA run`, or `no owning pane`.
**Recheck before delete:** for each candidate the reaper takes the per-name
launch lock non-blockingly (skip if held), re-queries panes/retain, then
removes while holding the lock.  `create_container` holds the same lock for
create/verify/reuse, so a concurrent launch/relaunch and a reap of the same
name are serialized.

### R3 — Release on finish / supersede / cancel / launch failure
- **impl / review / sign-off**: the pane EXIT trap removes the container by
  **id** (not name) so a late trap cannot kill a newer container of the same
  name; review/sign-off pre-launch removal uses the session-tagged name
  (`_make_container_name(label, session_tag)`), fixing the stale-reuse bug;
  if tmux window creation fails after the container was created, the
  launcher releases it.
- **QA**: at the end of `_execute_and_finalize` (completed *or* stopped),
  scenario containers of **this loop** are released in bounded parallel,
  except scenarios whose verdict is `INPUT_REQUIRED` (awaiting a human), that
  are explicitly retained, or whose window is currently being viewed by an
  attached client.  Those stay until their pane goes away, the PR is
  merged/closed, or a later run supersedes them; then the reconciler takes
  them.  A scenario whose container/window fails to launch releases its
  partial container immediately.
- **Supersede**: a new QA run no longer removes the previous run's containers
  synchronously; it kicks a background, PR-scoped reconcile (old windows are
  already killed by `_cleanup_stale_scenario_windows`, so they are unowned).
- **Merge**: `pr_cleanup.cleanup_pr_containers` covers every kind for the PR
  (labels + name parse), and CLI `_finalize_merge` launches a detached
  PR-scoped reap after killing windows (the merge is not blocked).
- **Push proxies**: a shared `(session_tag, pr_id)` proxy is stopped only
  when the runtime reports **no container** (any state) labeled/named for
  that tag+PR, checked under a per-proxy fcntl lock; `create_container` holds
  that lock from proxy start until `run` returns so a concurrent release
  cannot stop a proxy a new container is about to mount.
  Workdirs, captures, transcripts, QA workdirs are never touched.

### R4 — Reconcile on startup and periodically
`container_reaper.reconcile(scope)` lists pm containers (`ps -a`, labels),
computes ownership (R2), removes candidates with a bounded thread pool
(default 4 workers, per-remove timeout), releases unused proxies (socket dirs
`/tmp/pm-push-proxy-*` whose tag+PR has no container), and records the
outcome in `~/.pm/containers/reaper.json` (last run, removed, failures).
Single-flight across processes via an fcntl lock (a concurrent caller skips).
- TUI: run in a background thread after `_deferred_startup` and every 10 min
  (`set_interval`, worker thread — never on the event loop).  Failures are
  logged to the TUI log line with the retry command; they are retried on the
  next pass.
- Scope: by default every pm container on this runtime, but a container of a
  *different* session tag whose tmux server cannot be queried is skipped
  (indeterminate → keep).

### R5 — Verified reuse and clean setup failure
- Setup splits into the in-container bash phase (writes `/tmp/.pm-ready`)
  and the host post-setup phase (chown `~/.pm`, copy `.claude.json` —
  **required** when the host file exists, failure is a launch failure).  After
  post-setup the host writes `/tmp/.pm-setup-complete`.
- Reuse requires: running **and** `/tmp/.pm-setup-complete` **and**
  `/home/pm/.claude.json` present (when the host has one) **and**, when a push
  branch is set, the proxy socket alive.  If incomplete: if `/tmp/.pm-ready`
  exists, finish post-setup in place (idempotent) and re-verify; otherwise (or
  if finishing fails) remove and recreate — but if the incomplete container
  has a live owning pane and cannot be finished, raise instead of killing it.
- Any failure after `run` (sentinel timeout, exec error, cp failure,
  keyring) removes the partial container (and releases the proxy if unused)
  before raising.

### R6 — Real launch errors
`ContainerLaunchError(ContainerError)` carries `kind`
(`keyring|memory|pids|image|timeout|runtime`), the runtime stderr tail, and a
remediation.  `classify_runtime_error(stderr)` detects keyring exhaustion
("session keyring", "create session key", "disk quota exceeded"+"key") vs
memory ("cannot allocate memory", "out of memory", "oom") vs pids. Keyring
message includes `/proc/key-users` usage, running pm container count, and
`pm container reap --dry-run` / `pm container reap`; it notes that raising
`kernel.keys.maxkeys` only adds headroom.  `wrap_claude_cmd` no longer hides
`CalledProcessError` stderr.  Every launcher prints/records this message.
QA records a failed scenario launch as `scenario_verdict_reasons[i] =
"launch failed: …"` with **no** entry in `scenario_verdicts` (not an agent
verdict); the overall verdict stays the existing "unverdicted ⇒
INPUT_REQUIRED" aggregation and `state._error` names the launch failure.
Deeper verdict presentation stays with pr-7ab0a99.

### R7 — Scoped manual cleanup with preview + summary
`pm container reap [--dry-run] [--pr ID] [--session TAG] [--include-retained]`
uses the same `reconcile` (R2/R4): prints each container with action
(`remove`/`keep`) and reason, then a summary (removed / kept / failed, plus
running-container and keyring counts before → after).  `pm session cleanup
[--dry-run]` = `reap --session <current tag>` (the command older messages
referenced).  `pm container retain NAME [--release]` manages retention.
`pm container status` shows running pm containers, keyring usage, and last
reaper failures.  Existing `pm container cleanup` (remove all / by PR) is kept.

### R8 — Bounded launch concurrency / backpressure
- A process-wide semaphore bounds concurrent container creates
  (`container-launch-concurrency`, default 4) — QA's per-scenario prep threads
  no longer fire N `podman run`+exec-poll loops at once.
- `container-max-running` (default 0 = unlimited; supersedes the
  `qa-max-containers` name from 7b6dc7b9): QA clamps its launch batch to the
  remaining headroom (≥1), the rest queue through the existing
  queued-scenario mechanism.
- Before a create, if keyring usage ≥ 90 % a scoped synchronous reconcile
  (bounded) runs first; the launch then proceeds and, if it still fails,
  surfaces R6's explicit error.

### R9 — PID exhaustion and zombie reaping (note-1943d8d, 2026-10-22)
Evidence: #236 QA s28 hit 2041/2048 PIDs (1929 `treesample.sh`), PID 1 was
`sleep`, `podman exec` failed "Cannot fork"; restarting that unowned
container cleared it and kept its files.  Running state is not health.
- Container PID 1 is a reaping wait loop
  (`trap 'exit 0' TERM; while :; do sleep 86400 & wait $!; done`) instead of
  `exec sleep infinity`, so orphaned/zombie processes are reaped.  Limits are
  not raised.
- "cannot fork" classifies as `pids`; the pids launch error names
  `pm container restart <name>` and says raising the limit only postpones it.
- Reuse probe distinguishes "can't exec" (pids/memory/keyring) from
  "unfinished setup": an exhausted container with **no** live owner pane is
  restarted in place (`restart_container`, files/id/mounts kept, setup
  re-verified; recreate on failure); with a live owner it raises the real
  error and is not touched.  Keyring failures raise (host-wide; recreating
  won't help).
- `pids_usage()` reads cgroup stats (`stats --no-stream`, works when exec
  can't) + `HostConfig.PidsLimit`.  Non-targeted reconcile passes report
  kept containers ≥ 90 % of their limit (`Outcome.pid_pressure`; TUI log
  line, `pm container reap` WARNING rows); `pm container status` lists
  ≥ 80 %.  Unowned ones are simply reaped like any leftover.
- `pm container restart NAME [--force]` refuses while a live pane uses the
  container unless `--force`, takes the launch lock, prints PIDs before → after.
- Retry scheduling of dead QA workers stays with pr-1ab9075.

## 2. Implicit requirements

- IR1 Container names stay deterministic (existing names/tests and the reuse
  path depend on them); labels are additive.
- IR2 QA relaunch on resume (`_relaunch_scenario_window`) must re-ensure its
  container via `create_qa_container` (verified reuse or recreate), since the
  reconciler may have removed an unowned container while the TUI was down.
- IR3 Reaper must never run on the Textual event loop; all its runtime/tmux
  calls have timeouts.
- IR4 The reaper must work with no project context (CLI outside a project)
  and with docker (labels and `ps --filter label=` are common to both).
- IR5 The proxy socket dir gets an `owner.json` (`session_tag`, `pr_id`,
  `workdir`) so the reconciler can map hashed dirs back to tag+PR.
- IR6 Tests that mock `_run_runtime` sequences in `tests/test_container.py`
  must keep passing or be updated for the extra exec/label calls.
- IR7 Removing a container removes only the container; bind-mounted host dirs
  (workdir, captures, scratch, `~/.claude` transcripts) are untouched.

## 3. Ambiguities (resolved)

- A1 *What is "deliberately retained"?* — explicit `pm container retain`, plus
  any container with a live owning pane.  Automatic release at QA end
  additionally spares `INPUT_REQUIRED` scenarios and windows being viewed.
- A2 *QA windows after release* — releasing a PASS/NEEDS_WORK scenario
  container ends its `exec`, so its window closes; transcript, captures and
  scenario workdir remain (status pane keeps the verdicts).  This replaces the
  old "leave everything alive until the next run" behaviour, which is the leak.
- A3 *Merged PR with a still-live pane* — automatic reconcile keeps it (pane
  wins); merge paths kill windows first, so the trap/reaper removes it next.
  `pm pr cleanup --resources` / TUI `Y` remain the explicit "remove all".
- A4 *Other projects' containers* — reconciled only when their tmux server is
  queryable (labeled socket / default / shared socket); otherwise kept.
- A5 *Raising kernel quotas* — mentioned only as headroom in the error text;
  not changed by pm.
- A6 *Bound defaults* — launch concurrency 4; max running unlimited (opt-in),
  because a safe universal ceiling depends on the host quota.

## 4. Edge cases

- E1 Same scenario number on different PRs/runs: ownership is exact name
  match in pane commands; names embed PR and loop id.
- E2 Late EXIT trap from a killed review window after relaunch: removes by
  container id, so the new container survives.
- E3 Concurrent `reconcile` + QA launch of the same container: per-name lock
  + 120 s launch grace.
- E4 Concurrent impl/QA on the same PR sharing a proxy: release checks the
  runtime for any remaining tag+PR container under the proxy lock.
- E5 TUI restart mid-QA: panes survive → owned; if the session died, resume
  recreates containers (IR2).
- E6 Runtime unavailable / `ps` fails: reconcile returns an "unavailable"
  outcome, removes nothing.
- E7 Retained container of a merged PR: kept by automatic reconcile, listed in
  preview as retained; `--include-retained` or `pm pr cleanup --resources`
  removes it.
- E8 Docker runtime: `podman exec --user 0` vs docker root semantics preserved;
  labels work identically.
- E10 Automatic merged-PR sync (TUI event loop) hands containers to a
  background PR-scoped reconcile (`cleanup_pr_resources(...,
  background_containers=True)`) — non-blocking and retention-aware; explicit
  `Y` / `pm pr cleanup --resources` still remove synchronously.
- E11 `container-launch-concurrency` / `container-max-running` are registered
  `pm set` int settings.
- E9 Reaper running inside a pm container (pm-on-pm): it only sees the nested
  runtime's containers.
