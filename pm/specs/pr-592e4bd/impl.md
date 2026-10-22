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
- queued launch: stays queued (`… deferred — …`);
- window-death retry: deferred without spending a retry slot;
- session idle without its verdict/markers while the route is unhealthy
  (`_RouteStallWatch`, workers in the poll loop, refiners via
  `poll_for_verdict(on_idle_without_verdict=, on_tick=)`): remedy surfaced,
  the verdict reminder suppressed, and once the route is healthy the
  session is nudged to continue.
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
