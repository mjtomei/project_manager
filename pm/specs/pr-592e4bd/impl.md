# pr-592e4bd — Route QA scenario refinement and execution through the claude-mixed work route

Scope update (note-da1f854, master 859657d8, 2026-10-22): BOTH scenario
refinement (`qa_concretize`) and execution (`qa_scenario`) run on
`work/claude-opus-5-5`/high. Every other role — interactive QA s0, planning,
verification, finalization, implementation, review, sign-off, watcher,
merge — stays on main/plain Claude (`claude-opus-5-5`/high) for remote
control. Manual merge/spec gates are unchanged.

## 1. Requirements (grounded)

R1. **Routed roles: refiner + worker only.** Routing is selected through the
existing model config, per session type:
`pm model set qa_concretize provider:<route> --effort high --project` and
`pm model set qa_scenario provider:<route> --effort high --project`.
- Refiner commands are built in one place, `qa_loop._build_concretize_cmd`
  (initial tmux/container launch and queued launches, which re-enter the
  launchers).
- Worker commands are built in one place, `qa_loop._build_scenario_run_cmd`,
  used by initial tmux launch (`_launch_scenarios_in_tmux`), initial
  container launch (`_launch_scenarios_in_containers`), queued launch
  (`_poll_tmux_verdicts._launch_next_queued`) and window-death retry
  (`_relaunch_scenario_window`).
Both resolve via `_resolve_qa_model`, so existing overrides (`PM_MODEL` > PR
`model` > project > global) apply identically to launch, retry and resume.

R2. **Route definition is host-local.** A route is a provider in
`~/.pm/providers.yaml` of new type `router` (`providers.ProviderConfig`):
`api_base` (router URL, e.g. `http://127.0.0.1:8790`), `model`
(`work/claude-opus-5-5`), optional `launcher` (host executable instead of
`claude`), optional `credentials_file` (only `claudeAiOauth.expiresAt` is
read), optional `refresh_command`, `remedy`, `alias_models`. No credential
value is stored in project.yaml, generated commands, logs or captures: the
router type contributes only `ANTHROPIC_BASE_URL`, model-pin env vars and
`CLAUDE_CODE_DISABLE_UNKNOWN_MODEL_WINDOW_ENFORCEMENT=1`, and *unsets*
`ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN` (`env -u`, as claude-mixed does),
so a stray key never makes an unattended session prompt.
`pm provider add --type router` (`--launcher`, `--credentials-file`,
`--refresh-command`; rejects `--api-key`, requires `--model`).

R3. **Launcher boundary.** `claude_launcher.build_claude_shell_cmd` no
longer hardcodes the executable for router providers: on the host it runs
the route's `launcher` when configured, else `claude`, with the router env
as a command-scoped prefix. Inside a container (new `container=True` kwarg)
it always runs plain `claude`, with `ANTHROPIC_BASE_URL` rewritten to
`http://127.0.0.1:<router port>`, after a bridge-ensure step (R4).
`CLAUDE_CONFIG_DIR` is never changed, so hooks, transcripts
(`~/.claude/projects/<mangled>/<sid>.jsonl`) and session identity
(`--session-id`) are unchanged. The fake-claude branch is untouched (no
ensure step). An explicitly named provider that is not configured raises
`ProviderNotFoundError` (strict `get_provider`) instead of silently falling
back to the built-in claude provider.

R4. **Container connectivity without exposing the router.** Stdlib-only
`pm_core/route_bridge.py`:
- *host*: detached process listening on a 0600 Unix socket in a 0700 dir
  `~/.pm/route-bridge/<route>/router.sock`, forwarding to the router's
  loopback TCP port. Survives TUI restarts; exits when its socket is removed
  or replaced. The directory is never removed (containers mount it).
- *ensure* (in container): verifies the mounted socket, then idempotently
  starts a detached `127.0.0.1:<port>` → socket forwarder in the container's
  own netns; on failure prints problem + remedy and exits 3, so
  `ensure && claude` never starts Claude. The forwarder exits when the
  mounted directory disappears.
- Both are run as the *file* in isolated mode
  (`python3 -I <pm-src>/pm_core/route_bridge.py`), never `-m pm_core…`: a
  `pm_core` in the cwd (the host checkout, or the project under test at
  `/workspace`) would otherwise shadow the right one (supervisor-found bug).
- Sockets use a setup-only connect timeout (`CONNECT_TIMEOUT`), then no
  timeout for the stream: thinking models pause far longer between chunks
  (supervisor-found bug: EOF after 10 s).
QA containers get the socket dir bind-mounted at `/run/pm-route` via
`create_qa_container(route_mounts=…)` only when refiner or worker is
routed; no published ports, no `--network` change, other containers
unchanged.

R5. **s0 and every other role stay on main.** `_launch_scenario_0` resolves
new session type `qa_interactive` (fallback `qa`) through
`_resolve_interactive_model`, still passing `session_type="qa_scenario"` to
`build_claude_shell_cmd` so fake-claude behaviour is unchanged. Planner,
verifier, finalize, impl/review/sign-off/watcher/merge keep their own types.

R6. **No silent fallback; recoverable errors.** `worker_route.check_route()`
validates: provider configured, type router, model set; router TCP port
answers; launcher executable (host); credentials present and not expiring
within 2 min (optional `refresh_command` tried, at most once per 5 min);
for containers the host bridge is alive, the container has the mount, and
the in-container ensure succeeds (`exec`). On failure, for refiner and
worker alike:
- initial launch: `_await_route` waits (stop-aware, rechecks every 15 s)
  with `latest_output` = problem + remedy, then launches by itself;
- queued launch: stays queued (`… deferred — …`). Queued launches run
  inside the verdict-collection loop (`_launch_next_queued`), so their
  launch gates never wait there (`_route_gate(deferred=…)`): if the route
  fails between the queue check and the refiner/worker gate, the scenario
  is restored to its pre-launch state, put back at the front of the queue
  and the failing status cached for the queue check; a refiner window
  already opened is closed (the refiner reruns at relaunch) and a QA
  container created for the launch is removed (the relaunch re-clones the
  workdir; a container reused by name would keep its bind mount on the
  deleted clone). The poll loop
  retries the queue every tick (cached check), so a deferred scenario also
  launches when no other verdict event would refill its slot;
- window-death retry: deferred without spending a retry slot;
- session idle without its verdict/markers while the route is unhealthy
  (`_RouteStallWatch`, workers in the poll loop, refiners via
  `poll_for_verdict(on_idle_without_verdict=, on_tick=)`): remedy surfaced,
  the verdict reminder suppressed, and once the route is healthy the
  session is nudged to continue (nudge text, then two bare Enters, as
  the verdict follow-ups do: Claude can take one text+Enter burst as a
  paste and leave it unsent);
- QA stopped during an initial launch's route wait: the scenario has no
  window and keeps reason `stopped while waiting for the work route`; the
  poll loop's "no window → INPUT_REQUIRED" marking skips it, so it stays
  unverdicted (overall INPUT_REQUIRED via the unverdicted check).
None of these records a verdict. Fake-claude sessions skip the gate.

R7. **Visibility.** Each refiner/worker launch logs
`route=<name> model=<m> effort=<e> via=<host|launcher:…|container-bridge>`
(`worker_route.describe`); Phase 2 `latest_output` names the refiner and
worker routes; `pm model show` adds a Routes section; `pm provider list`
prints URL, model, launcher, credentials *path* and expiry (never contents).
`pm provider test <route> [--container] [--live]` runs the preflight; with
`--container` in a throwaway container with the bridge mount; with `--live`
a tools-disabled `claude -p` through the route, reporting requested models
(must all equal the route model), transcript path + models, and hook event.

## 2. Implicit requirements
- Effort resolution is independent of provider, so routed types keep `high`.
- The router (`router.py`) sends any request whose model lacks the `work/`
  prefix to its default backend with the caller's (main) credentials, so
  `ANTHROPIC_DEFAULT_{OPUS,SONNET,HAIKU}_MODEL`, `ANTHROPIC_SMALL_FAST_MODEL`
  and `CLAUDE_CODE_SUBAGENT_MODEL` are pinned to the route model
  (overridable via `alias_models`).
- The router does not rewrite the response model, so transcripts record the
  physical name (`claude-opus-5-5`); requested-model checks use claude's
  `modelUsage` (`work/claude-opus-5-5`).
- Resume (`resume_qa_sync`) re-enters the same poll loop; `container_name` is
  persisted in `qa_resume.json`, so relaunch gating checks the adopted
  container's mount. Adopted live panes keep running untouched.
- The route socket dir must exist before container creation (bind source).

## 3. Ambiguities (resolved)
- *How is the route expressed?* As a `provider:` value (existing config
  surface) whose host-local definition carries URL/model/launcher.
- *Overrides.* Existing precedence kept; a PR-level `model` override also
  overrides routing (explicit user choice), consistently for launch, retry
  and resume.
- *Config changes mid-run.* Launches within a run use the project data the
  run loaded at start (as before this PR); a change takes effect on the next
  QA run. A container created without the bridge mount cannot gain it; the
  gate reports "restart QA" as the remedy.
- *Failure semantics.* "Recoverable" = wait with an explained message and
  continue automatically once fixed (no verdict), not INPUT_REQUIRED.
- *s0 legacy fallback.* `qa_interactive` → `qa`; if neither is configured and
  `qa_scenario` is a plain model (not a provider), s0 keeps using it.
- *Host launcher.* Optional and not recommended for the work route: the
  host `claude-mixed` falls back to plain Claude against Anthropic when the
  router is down, adds `--settings` and runs `ox-heal-settings`. Plain
  `claude` + the router env is equivalent for workers, and pm's
  `ANTHROPIC_BASE_URL` prefix keeps even a launcher run on the router.
  Containers never use the launcher.
- *Other session types on a router provider.* Routing is generic config, so
  a user could put any type on a router provider; only refiner and worker
  launches are gated, and this project configures only those two.

## 4. Edge cases
- Router up but work token expired → caught by the `expiresAt` check
  before launch; mid-run expiry → session idles with an API error, the
  stall watch surfaces the remedy and nudges it once fixed.
- Host bridge killed while containers run → next check restarts it at the
  same path; the container sees the new socket through the directory
  mount; the in-container forwarder reconnects per connection.
- Host networking in the container (port already the router) → ensure sees
  it listening and starts no forwarder.
- Multiple routes / sessions share one host bridge per route name
  (thread lock + flock).
- Unix socket path ≤ 100 bytes (hash fallback, then /tmp).
- Coordination with #241/#245/#247: changes confined to command building,
  route-gate calls, one `create_qa_container` kwarg and two optional
  `poll_for_verdict` callbacks.

## 5. Validation status
- Unit/regression: `tests/test_worker_route.py` (provider env, launcher
  boundary, role isolation incl. s0/planner/verifier/finalize/review,
  preflight, bridge delayed-stream + shadow-pm_core regressions, gate
  waits/queued/retry/stall/resume, CLI).
- Sandbox e2e (fake router recording model + auth presence, real
  `claude` 2.1.308): host `pm provider test --live` OK — only
  `work/claude-opus-5-5` requested, transcript + Stop hook. Real nested
  podman `--network slirp4netns`: unmounted container cannot reach the
  router and is refused with the restart remedy; mounted container passes
  the in-container ensure and a live probe (also after the host bridge was
  restarted), with a shadow `pm_core` at `/workspace`.
- Real work account, host (supervisor, isolated provider
  `pm249-work-smoke`; production provider/model config unchanged):
  - `/pm-captures/host-work-route-smoke-20261022T184915Z/` — host probe
    PASS (requested `work/claude-opus-5-5`, transcript
    `~/.claude/projects/-tmp-pm-route-probe-…/<sid>.jsonl` with
    `claude-opus-5-5`, Stop hook). Container preflight FAILED there: run
    from the main checkout, `python -m pm_core.route_bridge` imported the
    checkout's pm_core (no route_bridge) — bug 2 below.
  - `/pm-captures/host-work-route-smoke-20261022T185245Z/` — run from the
    main checkout (`cwd /home/matt/claude-work/project-manager`) on source
    hashes matching commit dbf8878b (both fixes): real slirp4netns QA-style
    container PASS — container route OK via the bridge socket, requested
    `work/claude-opus-5-5`, transcript `~/.claude/projects/-workspace/<sid>.jsonl`
    with `claude-opus-5-5`, Stop hook.
  - Independent host 12 s idle-stream repro: closed at 10.02 s before the
    fix, both chunks delivered after (host files
    `~/.local/state/pm-pr-shepherd/249-bridge-timeout-{repro,postfix}.json`).
  - b7712d21 (after these runs) only adds the forwarder exit-on-dir-gone
    and `container_name ⇒ container` in `check_route`; QA re-exercises it.
  - Final implementation 75f0dde6 (includes b7712d21 and the env-by-name
    container fix), real work account, production config unchanged:
    `/pm-captures/host-work-route-smoke-20261022T190834Z/{result.json,diagnostic.log}`
    — real slirp4netns QA-style container PASS (requested
    `work/claude-opus-5-5`, transcript `~/.claude/projects/-workspace/<sid>.jsonl`
    with `claude-opus-5-5`, Stop hook); host + container pair PASS at
    `/pm-captures/host-work-route-smoke-20261022T190309Z/`, whose
    `router-tail.txt` shows the router sending the `work/` prefix to
    `anthropic-work`.
  - Review loop 99cf i1 (no behaviour change): router launch parts
    (ensure prefix / env / executable) shared between
    `build_claude_shell_cmd` and the live probe via
    `worker_route.launch_parts`; `worker_route.ROUTED_SESSION_TYPES`
    replaces the stale `WORKER_SESSION_TYPE`, and remedies name both routed
    types.
  - Review loop 99cf i2: two queued-launch bugs (found by review 1 and
    while assessing it), fixed in scope. (a) A route failure between
    `_launch_next_queued`'s queue check and the in-launch gate entered the
    blocking `_await_route` inside `_poll_tmux_verdicts`, stalling every
    other scenario's verdicts, retries and stop until the route came back;
    queued gates are now non-blocking (defer → restore → requeue).
    (b) A queue deferred on the route was only retried on another verdict
    event, so with nothing else running it never launched after the route
    recovered; the loop now retries the queue every tick. Regressions
    (mutation-checked): `TestPollLoopRouteGating::
    test_route_failure_after_queue_check_requeues_without_blocking`,
    `test_queued_launch_gate_does_not_create_windows`,
    `test_queued_scenario_launches_once_route_recovers`. Not route-specific
    and left to pr-1ab9075 (#247, note added there): a queued launch still
    polls its refiner synchronously inside the verdict loop, so a long or
    stalled queued refiner blocks it as before this PR.
  - Review loop 99cf i3: `claude_launcher._resolve_provider` (the
    `launch_claude*` subprocess paths) also drops a router provider's
    `unset_env_vars` from the child env, matching the shell command's
    `env -u` (regression `TestResolveProvider`).
  - Review loop 99cf i4: the bridge dir is created through
    `worker_route._secure_bridge_dir`, which refuses anything but a real
    directory owned by the user (lstat). This matters for the shared
    `/tmp/pm-route-<uid>-<hash>` fallback: a planted symlink must not
    redirect the container bind mount, and `container_mounts` now returns
    no mount rather than an unsafe one (the gate then reports it).
    Regression `TestBridge::test_symlinked_bridge_dir_is_refused`
    (mutation-checked).

### Bugs found by live validation, with regressions
1. *Stream cut off after 10 s* — the bridge's connect timeout stayed on the
   upstream socket during splicing. Fix: `route_bridge._connect_tcp` /
   `_connect_unix` use `CONNECT_TIMEOUT` for setup only, then
   `settimeout(None)`. Regressions:
   `TestBridge::test_stream_survives_pause_longer_than_connect_timeout`
   (fails with the timeout left in place — checked by mutation) and
   `TestBridge::test_unix_side_has_no_stream_timeout`.
2. *Shadow pm_core* — `python -m pm_core.route_bridge` resolved pm_core from
   the cwd (host main checkout; `/workspace` in containers) despite
   PYTHONPATH. Fix: run the stdlib-only file in isolated mode,
   `python3 -I <pm-src>/pm_core/route_bridge.py` (host:
   `worker_route.bridge_host_argv`, cwd `/`; container:
   `container_ensure_cmd`, `/opt/pm-src`). Regressions:
   `TestBridge::test_host_bridge_and_container_forwarder_end_to_end`
   (host bridge + ensure from a cwd and PYTHONPATH holding a pm_core that
   raises on import; fails with `-m` — checked by mutation) and
   `TestBuildShellCmd::test_container_cmd_ensures_bridge_first`.
3. *Container env values in logs/errors* (found in the sandbox smoke) —
   `create_container` passed host env vars as `-e NAME=value`
   (`_CLAUDE_ENV_VARS`, which include API keys/tokens, and
   `ContainerConfig.env`), and `_run_runtime` writes the full argv to the
   pm.container debug log on every call, to the error log on failure and
   into the raised `CalledProcessError`. Fixed in scope (this PR's
   "no credentials in logs/captures" acceptance): variables are passed by
   name (`-e NAME`) and their values through the runtime's process
   environment (`_run_runtime(env=…)`); verified with real podman (values
   arrive in the container, absent from its create argv). Regressions:
   `tests/test_container.py::TestCreateContainer::test_passes_env_vars` and
   `test_failed_create_does_not_expose_env_values` (fails on the old form —
   checked by mutation). pm.container log files written before this fix
   may still contain such values; they are not rewritten.
4. *Live probe: transcript missed, still "Live OK"* (supervisor, final
   reviewed-head host smoke `host-work-route-smoke-20261022T194946Z`,
   `transcript-lookup-finding.json`; probe cwd `/tmp/pm-route-probe-020ea4s_`).
   Real Claude mangles every non-alphanumeric cwd character to `-`; pm's
   `claude_launcher._claude_project_dir` (pre-existing, master) mapped only
   `/` and `.`, so the probe looked in `…020ea4s_/` while Claude wrote
   `…020ea4s-/`, and `live_probe` then passed vacuously (empty transcript
   model list) without the transcript. Fix: `_claude_project_dir` and
   fake-claude's mirror use `re.sub(r"[^a-zA-Z0-9]", "-", cwd)`;
   `live_probe` falls back to `~/.claude/projects/*/<sid>.jsonl` and fails
   with `missing evidence: …` (expected paths named) when the transcript,
   its model or the pm hook event is absent. Regressions (mutation-checked):
   `TestLiveProbe::test_underscore_cwd_finds_transcript`,
   `test_missing_transcript_is_a_failure`,
   `test_missing_hook_event_is_a_failure`,
   `test_cli_reports_missing_evidence`,
   `test_transcript_path_matches_claude_mangling`.
5. *Stop during route wait recorded a verdict* (QA s3, 0b1edfca) —
   `_poll_tmux_verdicts` marked every windowless scenario INPUT_REQUIRED
   ("worker window never created") and wrote its verdict.md, including
   scenarios stopped inside `_await_route`. Fix: skip scenarios whose
   reason is `_ROUTE_WAIT_STOPPED_REASON`. Regression
   `TestPollLoopRouteGating::test_stop_during_route_wait_leaves_scenario_unverdicted`
   (fails on 81cebf17). Captures `/pm-captures/scenarios/3/story3`.
6. *Recovery nudge typed but never submitted* (QA s4, c5d7d64f, real
   Claude vs a stub router) — `_RouteStallWatch.tick` sent the nudge as
   one text+Enter burst, which Claude took as a paste. Fix: two follow-up
   Enters 1 s apart. Regression asserts `[NUDGE, "", ""]`
   (mutation-checked). Captures `/pm-captures/scenarios/4`.

### Post-81cebf17 live rerun
`/pm-captures/host-work-route-smoke-20261022T195845Z/result.json`
(19:59Z, real work account, production config unchanged): host probe from
a forced-underscore cwd (`/tmp/pm-route-probe-under-score-…`) and a real
rootless slirp4netns container probe both PASS — requested
`work/claude-opus-5-5`, transcript with `claude-opus-5-5`, Stop hook. Its
source hashes for worker_route.py, route_bridge.py, cli/provider.py and
container.py match review head 1c92c9cb (0b1edfca/c5d7d64f touch only
qa_loop.py and tests).

Review loop 03db i1: added
`TestBridge::test_host_bridge_exits_when_socket_removed_or_replaced`
(host bridge exit on socket removal / replacement by a newer bridge was
untested; both cases fail with the exit check disabled). The inode-only
identity check is sound: the old bridge's open listener pins its socket
inode, so a replacement socket cannot reuse the number.

### QA S9/S10 fixes (pre-existing on master, fixed in scope)
7. *Push proxy shadowed by a project pm_core* (dbb88ea8) —
   `_start_proxy_subprocess` ran `python -m pm_core.push_proxy` from the
   caller's cwd; now cwd `/` with pm's own root first on PYTHONPATH.
   Regression `test_proxy_subprocess_ignores_shadow_pm_core_in_cwd`.
8. *Dashboard dropped / mislabelled queued scenarios* (b97c0e3d) — both
   launch paths pass the full scenario list and queued indices
   (`_status_queued`).
9. *TUI resume picked a stale snapshot* (60574f28, aea1fb8a; ordering
   corrected in review loop acdb i1/i2) — one candidate per PR, the newest
   *run*, ordered by the run's first scenario index (runs of a PR number on
   from earlier runs' launched scenarios; the highest index is wrong
   because queued scenarios get no workdir, so an older run's queued tail
   can exceed a newer run's numbers — old 1-6 at cap 2, new 3-5), then
   unfinished, then mtime. mtime alone is wrong
   both ways: a stopped run's late write, or an older orphan beside a run
   that completed while the TUI was down (the orphan was revived and the
   completed run's snapshot dropped unprocessed). Superseded snapshots,
   finished or not, are dropped unless an in-memory loop or a live process
   elsewhere drives them, so a later restart cannot revive them.
   Regressions in `tests/test_qa_resume.py` (the two acdb i1 cases fail on
   aea1fb8a; `test_newer_run_with_fewer_scenarios_outranks_queued_tail`
   fails on 2dfd9768).  Review loop acdb i3: a run whose planner produced
   no scenarios still reaches the poll tail and writes a snapshot with
   `scenarios: []`, which ordered as 0, below an older orphan, so the
   orphan was revived and the newer run's INPUT_REQUIRED completion
   dropped.  The snapshot now carries the run's `scenario_start` (the
   index the planner was given, past every earlier run's launched
   scenarios), used when it has no scenarios. Regression
   `test_newer_run_without_scenarios_outranks_older_orphan` (fails on
   bb198e46).

Review loop acdb i4: a queued *container* launch deferred at the refiner
or worker route gate left its container running; the relaunch re-cloned
`s-N/repo` (rmtree + clone) and `create_container` reused the running
container by name, whose `/workspace` bind mount still pointed at the
deleted clone. `_drop_deferred_launch` (was `_drop_deferred_window`) now
also removes that container (and its push proxy). Regression
`TestPollLoopRouteGating::test_deferred_container_launch_removes_its_container`
(both gates; fails without the fix).

### QA S11/S12 fixes (fixed in scope)
10. *Stopped loop gated a dead worker on the route* (1b6e2c68) — after
    `z t` the stopped loop's next poll ran the relaunch route check (exec
    into the dying container) and surfaced "relaunch deferred" or burned a
    retry backoff; it now breaks before the gate when stop is requested.
    Regression `TestPollLoopRouteGating::test_stopped_run_does_not_gate_or_defer_dead_worker`.
11. *Repeat deferral not resurfaced; API-error turn never resumed*
    (7c401141) — `_RouteStallWatch.remember()` clears the surface dedupe on
    a healthy status, so a second outage with the same message is shown
    again. A routed session whose turn ended on a Claude Code API error
    (`isApiErrorMessage`, `verdict_transcript.latest_api_error`) while the
    route already answers again is resumed with the same nudge, once per
    error record and at most `MAX_ERROR_RESUMES` (3) per watch.
12. *Superseded snapshot revived* (ea78b9d1) — `z t` clears the stopped
    run's `qa_resume.json` at once, and `_write_resume_file` clears instead
    of writing once `stop_requested` is set (a stopped run is never
    resumed; its completion is processed in memory).
13. *NUL in the push-proxy reuse log line* (c23a2021, pre-existing).

Review loop 8a99 i1 (on 7c401141): (a) the API-error resume applied to
every worker, since unrouted workers also get a watch whose status is
always ok; a main-account worker's API error (usage limit, bad request)
was nudged up to 3 times with "work route 'None' answers again". It now
applies only when the status names a route. (b) The watch is keyed by
scenario index and outlived a window-death relaunch, so the new worker
session inherited the dead session's spent error budget and its
`stalled_pane` (a later tick announced "recovered — resumed" for the dead
pane). Intended behaviour is per worker session: a successful relaunch
drops the scenario's watch. Regressions (mutation-checked):
`TestPollLoopRouteGating::test_api_error_on_unrouted_session_is_not_resumed`,
`test_relaunched_worker_gets_a_fresh_route_watch`.

Review loop 8a99 i2 (race left open by ea78b9d1, raised by the shepherd):
`_write_resume_file` checked `stop_requested` and then built, wrote and
renamed the snapshot, while `fresh_start_qa` set `stop_requested` and
cleared the file from the TUI thread. A write already past its check could
rename `qa_resume.json` back after the clear. The stopped loop only clears
it again at its final write, after the finalizer (pr-f8acf21), or never if
the thread dies, so a restart in that window revived the superseded run
while the new run was still planning. Fix: `QALoopState._resume_lock`.
`qa_loop.supersede_run` (now used by `z t`) sets the stop flag and clears
the file under the lock, and the writer rechecks the stop flag and renames
under the same lock (when stopped it drops its tmp file and clears). Deterministic
regressions (both fail when the rename goes back to unlocked; logs
`/pm-captures/review-8a99-i2/`):
`test_supersede_during_snapshot_write_leaves_no_snapshot` (supersede
between check and rename) and `test_supersede_waits_for_an_in_flight_rename`
(write paused at rename; supersede blocks, then clears).

Review loop 590d i1 (on 7b765217): the four "send, then two Enters"
copies became `qa_loop._send_submitted` (a failed message send raises,
failed trailing Enters are logged and ignored). A failed verdict-format
reminder is logged and no longer crashes the QA thread; the dead-pane
handling relaunches the worker on the next tick.

Review loop 590d i2 (pre-existing pane races, fixed in scope at the
shepherd's request; logs `/pm-captures/review-590d-i2/`):
- *Flagged-verification follow-up to a worker pane that died after its
  liveness check*: the send error went up out of `_poll_tmux_verdicts`
  and the run ended as "QA thread crashed" (ERROR). The worker panes kept
  running with nothing supervising them and nothing was finalized. Now
  the scenario is settled like a window that was already gone:
  INPUT_REQUIRED, "window gone during PASS verification…".
- *Re-verification into a verifier pane that died after its liveness
  check*: this used to be "verification thread crashed", which flagged
  the worker and made it re-run. Now the check runs in a fresh verifier
  pane, the same as when the pane was already gone.
- *Verifier pane dying during the re-verification wait*:
  `loop_shared.wait_for_follow_up_verdict` only checked that the window
  still had a pane. The worker pane shares that window, so the wait (no
  time limit, by design) never ended and finalize was blocked. i1's
  tolerant Enters sent the race above down this path. The wait now takes
  `pane_id=` and the verifier passes its own pane. Review and watcher
  callers are unchanged.
Regressions (mutation-checked; with the wait mutation the unbounded test
hung until a timeout killed it, so it now fails fast):
`TestPollLoopRouteGating::test_flagged_followup_to_a_vanished_pane_is_input_required`,
`TestVerifySingleScenario::test_reverify_into_a_vanished_verifier_starts_a_new_one`,
`test_reverify_waits_on_the_verifier_pane`,
`test_follow_up_wait_ends_when_its_pane_dies`.
Still open and filed separately: a verifier that dies mid-check counts
as FLAGGED ("verifier pane disappeared"), so the worker re-runs, and
repeated deaths turn a PASS into NEEDS_WORK.

### QA5/S15/S16 fixes (reviewed in review loop b62f i1)
14. *"Resumed" claimed for a dead pane* (5432f736) —
    `_RouteStallWatch._resume` announces a resume only after the nudge
    is typed; otherwise it logs "pane gone — not resumed" and the
    dead-pane relaunch takes over.
15. *Flag follow-up / dead worker taken for the refiner* (32961096) — in
    host mode the scenario window's first pane is the still-live
    refiner. A recorded worker `pane_id` that died is kept (not cleared)
    and never replaced by the first-pane fallback, so the follow-up is
    not typed into the refiner and the dead worker is still relaunched.
    A snapshot from before this fix (`pane_id` null) still falls back:
    pr-d1d0139.
16. *Relaunch bound to the refiner* (296c08a7) — `new_window_get_pane`
    returns the pane tmux reports for the created window (`-P -F`), not a
    by-name lookup, and `_relaunch_scenario_window` splits the new worker
    into the surviving scenario window (fresh window only when it is
    gone), so one window per scenario remains.
17. *Shared push proxy start races* (75649ae4, b62f i1) — the
    check-then-spawn in `start_push_proxy` runs under a per-key lock, so
    parallel scenario container creates spawn one proxy and keep both
    refs. Review b62f i1: `stop_push_proxy` takes the same lock, so a
    start racing the last container's stop cannot reuse the proxy being
    killed (regression
    `TestSharedProxy::test_start_during_last_stop_spawns_a_new_proxy`,
    fails without the lock). Review b62f i2: the proxy daemon only checked
    that its socket *path* existed, so after a stop and an immediate start
    of the PR's proxy the old daemon kept running (orphan, bound to an
    unlinked socket), and its exit cleanup unlinked the path whatever was
    there, which could delete the newer proxy's socket. `PushProxy` now
    records its socket inode, exits when the path is removed *or replaced*
    (`owns_socket`, as `route_bridge` does) and unlinks only its own socket
    (regressions `TestPushProxyLifecycle::
    test_replaced_daemon_exits_and_keeps_the_new_socket` (real daemon) and
    `test_stop_of_a_replaced_proxy_leaves_the_new_socket`, each fails with
    its half reverted; logs `/pm-captures/review-b62f-i2/`).

### QA S17 fix (reviewed in review loop ab29 i1)
18. *Worker split into a closed refiner window logged as a launch*
    (a2ff954c, pre-existing on master, host and container) — PR cleanup
    (TUI `Y`) during a stopping run closed the refiner's window; the
    worker split then raised, `qa_loop` logged a traceback, and
    "Launched scenario N" was still logged because `window_name` is set
    while the refiner runs. `_split_worker_pane` now returns `None` on
    failure (plain warning when the refiner pane is gone, traceback
    otherwise) and both launch paths count only a created worker pane as
    a launch. Regressions `TestPollLoopRouteGating::
    test_worker_split_after_window_closed_is_not_a_launch[container|tmux]`
    and `test_worker_split_failure_with_live_refiner_keeps_traceback`
    (fail with the fix reverted). The relaunch path
    (`_relaunch_scenario_window`) already handles a vanished window in
    its own `try`. Review loop ab29 i2: a split failure with the refiner
    pane still alive left `window_name` set and no `pane_id`, so the poll
    loop's first-pane fallback took the refiner for the worker (and could
    remind it into a verdict for a scenario that never ran). The refiner
    pane (refinement is done; QA exec panes don't remove the container)
    is now closed, so the scenario takes the dead-worker path: route-gated
    relaunch with retries. Real-tmux regression
    `test_worker_split_failure_with_live_refiner_keeps_traceback` (fails
    without the kill).

### QA S20 fix (reviewed in review loop 6c6f i1)
19. *Closed refiner gated on the route; split error unnamed* (2314f1a8) —
    (a) TUI `Y` during a stopping container run closed the refiners'
    windows and removed their containers; the worker route gate then
    checked the container being removed and surfaced "worker waiting —
    work route … unavailable … Remedy: …". Both launch paths now check
    the refiner pane first (`_refiner_gone`): a closed refiner skips the
    gate and takes the dead-worker path, whose relaunch stays
    route-gated. (b) `tmux._run` raises `TmuxCommandError` (a
    `CalledProcessError` subclass, so existing handlers are unchanged)
    whose message ends with tmux's stderr, so a refused split's
    traceback names the reason ("no space for new pane"). Regressions
    `TestPollLoopRouteGating::test_closed_refiner_window_skips_the_worker_route_gate[container|tmux]`
    (fails with the check disabled, rechecked in 6c6f i1) and
    `test_split_failure_traceback_names_the_tmux_error` (real tmux).
