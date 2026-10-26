# pr-592e4bd — Route QA scenario refinement and execution through the claude-mixed work route

Scope update (2026-10-24): the original refiner/executor-only routing remains
available. The user also authorized running every role for this PR on the
work account because the main account has less than 5% weekly allowance.
Implementation, review, and sign-off containers must therefore support the
same router provider as QA workers. Host QA planning, interactive s0,
verification, and finalization already use the shared provider-aware launcher.
The per-PR `model: provider:claude-work` override selects all these roles;
project defaults can still keep other roles on plain Claude for remote control.
Manual merge/spec gates are unchanged.

The user subsequently requested Claude sign-off for the DeepSeek and GLM bug
trials. A PR's `session_models` mapping selects exceptions to its `model`:
`model: provider:deepseek-flash` plus
`session_models: {signoff: provider:claude-work}`. Role-specific values and
their parent-role fallbacks take precedence over the PR-wide model;
`PM_MODEL` remains the highest-priority override. Implementation, review,
all QA roles, sign-off, and merge resolve through this same rule.

## 1. Requirements (grounded)

R1. **Selective routing, with an all-role override.** The original split is selected through the
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
For implementation, review, and sign-off, the shared container wrapper checks
an explicitly selected provider before launch and mounts its router bridge.
Their command builders use container mode, avoiding host-only launcher paths.
An unavailable route blocks launch; it must not switch to the main account.
The isolated route tests cover bridge mount preservation, refusal to launch an
unavailable route, and the review/sign-off callers' container/provider wiring.


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
back to the built-in claude provider. So does an entry that is there but is
not a provider (`ProviderEntryError`, a subclass; review loop c189 i9).

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

R5. **s0 and every other role stay on main by default.** (Unless a PR-level
`model: provider:<route>` override selects the route for every role, as the
2026-10-24 scope update does for this PR.) `_launch_scenario_0` resolves
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

R8. **Subagents stay on the session's model** (note-6153fe1, 2026-10-25).
Every launch on which pm selects a model sets
`CLAUDE_CODE_SUBAGENT_MODEL=<effective --model value>` and
`CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1` (`providers.subagent_pin_env`). The
"effective" value is an explicit model if there is one, otherwise the
provider's model, kept verbatim with any route prefix (`work/`) or context
suffix (`[1m]`). This applies to router and plain-model sessions, every role,
host and container, new and `--resume` launches, the fake-claude path and
the `claude -p` helpers.

Since Claude Code 2.1.251 `CLAUDE_CODE_SUBAGENT_MODEL` alone is only a
default: an Agent call's `model`, an agent definition's `model` frontmatter
and the built-in Explore/Plan agents all bypass it. On the router a bypassing
child that asks for an unprefixed model (e.g. `fable` → `claude-fable-5-1`)
runs on the caller's main account. FORCE (Claude Code ≥ 2.1.257; 2.1.310 is
installed) makes the pin override all of them and removes `model` from the
Agent tool. A router's explicit `alias_models` entry for
`CLAUDE_CODE_SUBAGENT_MODEL` replaces the pinned value and is forced too.
When pm selects no model (CLI default) it sets no pin and removes an
inherited one (R9), so the children follow the CLI default rather than a
caller's pin (QA S61, 3ee69236: pm run inside a routed session passed its
`work/` pin and FORCE to a no-model session on the main endpoint, and every
child failed `model_not_found`). A pin a user sets in Claude's own
`settings.json` `env` is not affected.

Repro that prompted this: PR241 Astra review 6427 i4 had
`CLAUDE_CODE_SUBAGENT_MODEL=chatgpt/gpt-6-astra-high` without FORCE. Two
explicit Fable helpers ran `claude-fable-5-1` and exhausted the main
account.

R9. **Each launch's routing environment comes from pm's selection**
(user decision 2026-10-26, answering review loop c189 i6). A pm process
started inside a routed session inherits everything that session's launch
set. Before this, a no-model session launched from there ran its whole
main loop as `work/claude-opus-5-5`, because the CLI default resolves
through `ANTHROPIC_DEFAULT_OPUS_MODEL`. A main session's Fable, haiku and
background calls also followed the route, and the route's
`ANTHROPIC_BASE_URL` stayed. 3ee69236 and f0031965 had dropped only the
subagent and classifier pins.

Now `providers.launch_env(provider, env, model)` builds the launch's
routing variables (`LAUNCH_ROUTING_ENV_VARS`: the four
`ANTHROPIC_DEFAULT_*_MODEL` aliases, `ANTHROPIC_SMALL_FAST_MODEL`, the
subagent pin and FORCE, `CLAUDE_CODE_AUTO_MODE_MODEL` and
`PM_ROUTE_BASE_URL`):
- What the selection needs is assigned: a router's pins and classifier,
  any provider's own `alias_models` (now honoured for every provider
  type), and the subagent pin of the effective model.
- Every other routing variable is unset (`env -u`, or dropped from the
  `claude -p` run env), whatever the caller's environment holds.
- A routed launch also records the URL it set in `PM_ROUTE_BASE_URL`.
- An inherited `ANTHROPIC_BASE_URL` is removed when the selection names
  none and it is a route's: equal to that marker, or to a router
  configured here, in its host or in-container form. The second case
  covers a parent from before the marker, and the host `claude-mixed`
  launcher. A providers.yaml entry that is not a well-formed router (a
  null entry, a non-string `api_base`) names no address and is skipped;
  it never fails a launch that does not use it (review loop c189 i8).
- Any other `ANTHROPIC_BASE_URL` is the user's own (a proxy, a QA stub)
  and stays. So do all non-routing variables, the provider's own
  variables and Claude's own `settings.json` `env`.

One builder serves `build_claude_shell_cmd` (host, container and
`--resume` commands and the fake-claude path), `_resolve_provider`
(`launch_claude`, `launch_claude_print`,
`launch_claude_print_background`), the `pm provider test --live` probe,
and `pm_core/bridge.py`'s `claude -p` turn. The bridge selects no model,
so it only unsets. A main container session gets the host's
`ANTHROPIC_BASE_URL` and `ANTHROPIC_SMALL_FAST_MODEL` by name
(`container._CLAUDE_ENV_VARS`), and its command removes them the same way.

A user who exported alias variables in their own shell for a non-router
provider now sets them in that provider's `alias_models` (or in Claude's
`settings.json` `env`). Assigned accounts and models are unchanged.
Regressions: `tests/test_worker_route.py::TestInheritedRoutingEnv`, plus
the updated exact-command tests. `tests/conftest.py` clears the routing
variables, so the suite gives the same result inside a routed session.

## 2. Implicit requirements
- Effort resolution is independent of provider, so routed types keep `high`.
- The router (`router.py`) sends any request whose model lacks the `work/`
  prefix to its default backend with the caller's (main) credentials, so
  `ANTHROPIC_DEFAULT_{OPUS,SONNET,HAIKU,FABLE}_MODEL`,
  `ANTHROPIC_SMALL_FAST_MODEL` and `CLAUDE_CODE_SUBAGENT_MODEL` are pinned
  to the route model (overridable via `alias_models`), and
  `CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1` makes the subagent pin binding (R8).
  FORCE covers subagents only; the alias pins also keep main-loop switches
  on the route: a skill's or slash command's `model: fable` frontmatter and
  the `/model` picker's Fable entry resolve through
  `ANTHROPIC_DEFAULT_FABLE_MODEL` (QA S61, 79b6ddd7; these four are every
  `ANTHROPIC_DEFAULT_*_MODEL` alias Claude Code 2.1.310 reads). A full id
  typed into `/model` is outside the launch boundary.
- *Auto-mode permission classifier* (pr-1071c5a, QA S59/S61; user
  decision 2026-10-25: a session on the work account classifies on the
  work account, every other session on the main account). In auto
  permission mode Claude Code 2.1.310 picks the classifier model itself:
  a server-configured model first, then `CLAUDE_CODE_AUTO_MODE_MODEL`
  (refused if Opus/Sonnet 5.5-class), then
  `ANTHROPIC_DEFAULT_SONNET_MODEL` (same restriction), then its Sonnet 5
  default `claude-sonnet-5`, sent with no route prefix. The route's
  Opus pins are therefore refused and the default reached the main
  account. A router provider now sets
  `CLAUDE_CODE_AUTO_MODE_MODEL=<route prefix>/claude-sonnet-5`
  (`providers.route_classifier_model`: Claude's own default, through the
  route; nothing for an unprefixed route model, whose default already goes
  to the same backend; an `alias_models` entry wins). Only a route that
  serves Claude models (the name after the prefix is `claude-…`) gets
  the pin (review loop c189 i2): the host router's `deepseek/`, `z-ai/`
  and `chatgpt/` prefixes (the DeepSeek, GLM and Astra trial routes) are
  other vendors' namespaces with no `claude-sonnet-5`
  (`/pm-captures/review-c189-i2/router-v1-models.txt`), so f0031965's
  `<prefix>/claude-sonnet-5` named a model no backend serves. Those
  sessions keep the classifier Claude picks, as before f0031965: its
  unprefixed default goes to the router's default backend with the
  caller's credentials, the main account, which is the user's decision
  for every session not on the work account. Every launch that sets no
  classifier pin removes an inherited one (R9): a router session with no
  pin, so `pm` run inside a work-routed session does not put another
  route's classifier on the work account, and a main-account session, so
  its classifier keeps Claude's default on that account. Since R9 this also
  applies to `local`/`openai` sessions, which set a classifier model only
  through their own `alias_models`. `pm provider list` names
  the route's classifier model. Sessions launched with
  `--dangerously-skip-permissions` never classify. Residual outside pm's
  control: a server-configured classifier model takes priority over the
  env var (none was configured for these accounts in S59 or the c189 live
  check).
- The router does not rewrite the response model, so transcripts record the
  physical name (`claude-opus-5-5`); requested-model checks use claude's
  `modelUsage` (`work/claude-opus-5-5`). A `[1m]` suffix on the route model
  is a Claude Code selector sent as a beta header, so the transcript still
  records plain `claude-opus-5-5` (`worker_route.model_on_route` drops the
  suffix; QA S59, ff65f489).
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
- *Subagent pin for plain-model sessions (R8).* pm forces subagents onto
  the selected model for plain-model sessions too, not only routes. The
  account is the same either way. This enforces the selected model and stops
  Fable helpers spending the main account's allowance. With no model
  selected, the CLI default decides: pm sets no pin and removes one
  inherited from the caller's environment (R8).
- *Host launcher.* Optional and not recommended for the work route: the
  host `claude-mixed` falls back to plain Claude against Anthropic when the
  router is down, adds `--settings` and runs `ox-heal-settings`. Plain
  `claude` + the router env is equivalent for workers, and pm's
  `ANTHROPIC_BASE_URL` prefix keeps even a launcher run on the router.
  Containers never use the launcher.
- *Other session types on a router provider.* Routing is generic config, so
  a user could put any type on a router provider (a PR-level override puts
  every role there). Refiner and worker launches are gated with the
  recoverable waits of R6. In container mode, implementation, review and
  sign-off are gated once by the shared `container.wrap_claude_cmd`: an
  unavailable route is a `ContainerError` with the remedy, and nothing is
  launched. Host-mode launches of those roles, and host QA planner, s0,
  verifier and finalizer, are not gated: they start Claude with the
  router's `ANTHROPIC_BASE_URL`, so a down router shows an API error in the
  pane, never a main-account fallback.  A provider that is not configured
  on this host is refused for every role when its command is built: one
  `Error:` line from the CLI, `QA stopped: …` for a QA run (item 41(f)).

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

Full history (items 1–26, review-loop entries, live smokes, regressions
and capture paths) is kept verbatim in
[impl-validation-history.md](impl-validation-history.md). Every rule
below still holds; look there for the reasoning and evidence.

**Current evidence.** Regressions are in `tests/test_worker_route.py`
plus the files named per item. The real work account, with production
config unchanged, passed on the final implementation 75f0dde6
(`/pm-captures/host-work-route-smoke-20261022T190834Z/`: slirp4netns
container; host + container `…190309Z/`). After 81cebf17 it passed on the
host from an underscore cwd and in a container
(`…195845Z/result.json`). Live QA S1–S61 is in
`/pm-captures/scenarios/<N>/` (REPORT.md). S52 (RQ39) never executed
(run a871abafdd8bbc20, `verdict.md`: no recovery after 10 relaunches;
kept as the record of that failed attempt). Its Thens first ran live as
S55 (run a31ac0ae57566deb: all story Thens held, the preflight Routes
Then failed and was fixed in 2a6b14d4, item 42(k)). S56 (same run, PASS)
ran on 3a0c32e6, before 2a6b14d4: its story-1 W/X Routes lines show the
old split by effort, which 2a6b14d4 replaced with one line per route
(rechecked live in S55 post-fix and by
`test_model_show_pr_route_lines_with_the_real_route_description`). The
latest full suite is recorded at the end of "Subagent model enforcement"
below (item 42 records the suites up to 3738).

**Rules fixed during validation (index).** Commits in parentheses.
- Live smokes 1–4. The bridge stream has no timeout after connect
  (`CONNECT_TIMEOUT` is for setup only). The bridge runs as
  `python3 -I <pm-src>/pm_core/route_bridge.py` and never with `-m`,
  because a project pm_core would shadow it. Container env vars are
  passed as `-e NAME`, with values only in the runtime's process env.
  `_claude_project_dir` mangles every non-alphanumeric cwd character to
  `-`. `live_probe` fails with `missing evidence: …` (81cebf17).
- 5. A scenario stopped during a route wait stays unverdicted (0b1edfca).
- 6, 11, 14. Route nudges and the verdict reminder are submitted (text,
  then two Enters, `_send_submitted`; c5d7d64f, 7b765217). A repeat
  deferral is shown again. A routed API-error turn is resumed once the
  route answers, once per error record, max 3 per worker session. That
  applies to routed sessions only, and a relaunch gets a fresh watch
  (7c401141, 8a99 i1). A resume is announced only after the nudge is
  typed (5432f736).
- 99cf i1–i4. Shared `worker_route.launch_parts`. Queued gates never
  block the verdict loop (defer → restore → requeue, queue retried each
  tick). `_resolve_provider` drops a router provider's unset vars. The
  bridge dir must be a real directory the user owns (lstat).
- acdb i4. A queued container launch deferred at a gate removes its
  container and proxy (`_drop_deferred_launch`).
- 7, 17. The push proxy runs with cwd `/`. Shared proxy start and stop
  hold a per-key lock. The daemon exits when its socket is removed or
  replaced and unlinks only its own socket (dbb88ea8, 75649ae4, 8a3d3412,
  130e8ab9).
- 8. The dashboard keeps queued scenarios (`_status_queued`, b97c0e3d).
- 9, 12, 8a99 i2. Resume picks one snapshot per PR. That is the newest
  run, ordered by first scenario index (or `scenario_start` when it has
  no scenarios), then unfinished, then mtime. Superseded snapshots are
  dropped. `z t` (`supersede_run`) clears the stopped run's snapshot under
  `_resume_lock`, and a stopped loop never rewrites it (60574f28,
  aea1fb8a, ea78b9d1). Scenario numbering follows launched indices.
- 10, 19. A stopped loop does not route-gate dead workers (1b6e2c68). A
  closed refiner skips the worker gate (`_refiner_gone`). tmux errors
  carry stderr (`TmuxCommandError`, 2314f1a8).
- 13. No NUL in the proxy reuse log line (c23a2021).
- 590d i1–i2. A worker pane that dies before a flagged follow-up gives
  INPUT_REQUIRED (window gone). A dead verifier is replaced, and the
  follow-up wait watches its own `pane_id`. Filed: a verifier death
  counts as FLAGGED (pr-04dfffb).
- 15, 16, 18. A recorded dead worker `pane_id` is kept, with no
  first-pane fallback (32961096; pre-fix snapshots: pr-d1d0139). The
  relaunch uses the pane tmux reports and splits into the surviving
  window (296c08a7). Only a created worker pane counts as a launch. A
  split failure with a live refiner closes the refiner and takes the
  dead-worker path (a2ff954c, ded27fcd).
- 20, 21. With verification off, finalize runs. The gate uses the poll
  loop's `qa-verify-pass` (ee3d0644, 3ce6 i2). A stopped or superseded
  run spawns no finalizer (2ff602fc). A stop during the finalizer poll
  leaves that pane until the next cleanup (pr-1139060).
- 22. The TUI poll timer runs while a QA loop runs or has an
  unprocessed verdict (`_qa_needs_poll`; 89414241, fb7af748). Only a
  PR's first run with no cached workdir discriminates this (8ae55361).
- 23. After NEEDS_WORK the tree repaints (f57c500c). The zz t restart
  and NEEDS_WORK lines use `force=True, hold=CONFIRM_HOLD_SECONDS`
  (991addf9, 0697e450, 1098813c).
- 24. A live QA marker beats a finished review-loop badge
  (`_get_loop_marker(pane_live=)`), and `⏸M` survives (9cc2fb6b, 84662f7f).
  Kept on purpose: the idle `⟳N⏸` badge returns after QA. fake-claude
  `idle_once_after` is fixture-only. Known limitation: Ctrl+C in a review
  pane does not end an INPUT_REQUIRED wait (pr-89296d3, note-18c906b).
- 25. Turning auto-start off keeps transcripts that a reader still polls
  as symlinks (23df1ff1, c97aaf9c). Frozen older copies: pr-237d610.
- 26. `poll_qa_state` drops a PR's `qa:` keys that are not in the
  current run (94f36a18). Runtime-mirror residue: pr-b2db183.

### S33 follow-up: typed turn after idle (review loop d0d0 i1)
27. *An idle pane never read as working again when the user typed a new
    turn* (pr-2a44020, pre-existing on master; found in S33). pm had no
    prompt-submit hook, so `PaneIdleTracker` cleared `idle` only on
    `permission_prompt`; the node and picker kept `[idle]` through the
    whole typed turn. Scope decision note-1952e9c (0a854e58): retain RQ34
    and fix it here with a coexist-append install policy.
    - `hook_install` installs `UserPromptSubmit` → receiver `user_prompt`.
      `Notification[idle_prompt|permission_prompt]` and `Stop` keep the
      refuse-on-conflict policy (`_MANAGED_EVENTS`); `UserPromptSubmit`
      (`_COEXIST_EVENTS`) never conflicts: pm's entry is appended next to
      the user's. Merging is hook-level for every pm event: user hooks are
      kept in place (also user Notification hooks on other matchers, which
      the old wholesale list replacement dropped on every rewrite), only
      pm's own hooks are replaced, and an event whose pm hooks already
      match is not touched, so a user hook added after pm's entry causes
      no rewrite. A user hook sharing an entry with pm's on a managed
      matcher is now reported as a conflict instead of being kept
      silently.
    - Ownership (review loop a183 i1, shepherd finding on af19cfcf): a
      hook is pm's only when its whole command is a receiver invocation,
      either `python3 <receiver path> <event>` or the legacy
      `<python> -m pm_core.hook_receiver <event>`, with `<event>` one of
      pm's four. af19cfcf matched any command *containing* the receiver
      path or `pm_core.hook_receiver`. So it deleted a user logger such as
      `echo 'pm_core.hook_receiver observed' >> log`, and a mixed shell
      command such as `python3 <receiver> user_prompt && notify-send`, on
      the next rewrite. Such commands are now the user's: they are kept
      on `UserPromptSubmit`, and on a managed matcher they are a conflict
      that pm refuses and leaves in place. Regressions in
      `tests/test_hook_events.py`:
      `test_hook_is_pm_rejects_commands_that_only_mention_the_receiver`,
      `test_installer_keeps_user_prompt_hooks_that_mention_the_receiver`
      and `test_installer_refuses_mixed_user_command_on_a_managed_matcher`
      fail with the substring matcher. `test_hook_is_pm_recognises_receiver_invocations`
      covers both pm forms for all four events. Full suite 3525 passed (env -u PM_HOST_HOME, /usr/bin first). Logs:
      `/pm-captures/review-a183-i1/`. A malformed non-string `command`
      is the user's too and is kept; a183 i1's `shlex.split` raised on it
      at hook install (review loop a183 i2,
      `test_installer_keeps_malformed_user_prompt_hooks`).
    - The receiver stores only its fixed fields (never `prompt`) and
      prints nothing (a `UserPromptSubmit` hook's stdout is added to the
      prompt).
    - `PaneIdleTracker.poll`: `user_prompt` sets `idle`,
      `waiting_for_input` and `idle_notified` to False, so the turn's end
      is a fresh `became_idle`. `runtime_state._hook_state_for` already
      read any non-idle, non-permission event as working; the other
      `read_event` readers wait for `idle_prompt` newer than a send time or
      check "no event yet" (trust watches), and keep their meaning.
    - Blocked prompts (checked live on claude 2.1.309, no ordering between
      hooks assumed): a user `UserPromptSubmit` hook that exits 2 still
      lets pm's record land, no `Stop` follows, and Claude fires
      `idle_prompt` again ~60 s later, so the pane reads as working for
      about a minute and then idle. A re-armed `became_idle` there (or after
      a real typed turn) re-runs only idempotent handlers: impl idle →
      auto-review only for in-scope `in_progress` PRs with auto-start on;
      merge window idle → re-check the published merge.
    - Approving a permission prompt is not a prompt submit, so a pane
      keeps `⏸` after approval until its next hook event (unchanged, S30).
    Regressions: `tests/test_pane_idle.py::TestUserPromptTurnStart` (3,
    fail with the `user_prompt` branch disabled),
    `test_picker_status_reads_working_after_user_prompt`,
    `tests/test_hook_events.py` coexist/upgrade/idempotency/conflict and
    receiver tests (`test_installer_appends_user_prompt_hook_next_to_user_hooks`,
    `test_installer_upgrade_adds_user_prompt_and_keeps_all_user_hooks` and
    `test_installer_preserves_unrelated_notification_matcher` fail with the
    old list replacement; three fail with `UserPromptSubmit` treated as a
    managed event). Full suite 3510 passed (env -u PM_HOST_HOME, /usr/bin first). Live
    control replay `/pm-captures/review-d0d0-i1/live-control/` (README):
    isolated HOME, real claude 2.1.309 on the S33 stub, user hooks kept
    byte-identical by the install. On the same pane, the patched tracker
    reported working (`idle=false`) about 1.2 s after the typed Enter and
    reported idle again at the turn's next `idle_prompt`; the pre-fix
    tracker (HEAD 0a854e58) reported idle throughout. For a turn blocked
    by a user hook, the patched tracker reported working until Claude's
    next `idle_prompt` 60.7 s later, then idle (the pre-fix tracker stayed
    idle). That is the known, bounded limitation: a blocked prompt shows
    as working for about 60 s. The trust dialog showed waiting until the
    first `user_prompt`.

### S35/S36 follow-ups (reviewed in review loop 3992 i1)
28. Tree node and tracker fixes found live, all pre-existing on master,
    each with a regression that fails when reverted:
    - A live impl pane (spinner / `⏸`) also hides a finished loop's `⟳N`
      badge; QA and impl share one `live_state` in `PRNode.render`
      (41ff0d3c, 3992 i1 refactor).
    - The hook file keeps only the latest event, so a Stop newer than an
      observed `idle_prompt` is a new turn and reads as working until the
      next `idle_prompt` (ebf919e8).
    - The QA marker needs no cached workdir; a queued launch keeps the
      run's own tracker keys (`QALoopState._ui_tracker_keys`); the TUI
      mount sweep clears only its own project's PRs (93dca6ae).
    Refiner, s0, planner, verifier and finalizer panes stay untracked by
    design (qa.md RQ35; pr-eee7483). Full suite 3537 passed on 91f77840
    (env -u PM_HOST_HOME, /usr/bin first; `/pm-captures/review-3992-i2`).
    Captures `/pm-captures/scenarios/35`,
    `/36`.

### S39 follow-up (QA scenario 39)
29. *A TUI's restart-resume scan deleted another project's live QA
    snapshot.* `~/.pm/workdirs/qa` is shared by every project under
    `~/.pm`, like `~/.pm/runtime` (item 28, 93dca6ae). `_resume_incomplete_qa`
    treated a PR missing from its own project as "left QA" and deleted its
    `qa_resume.json` once the owner pid was gone. It also dropped that PR's
    older superseded snapshots. Live, P1's TUI deleted P2's snapshot for C
    within 30 ms of P2's TUI being killed, so P2's restart had nothing to
    resume: no `Resuming QA`, and C's node and picker lost the spinner and
    `[working]` while the C workers were still mid-turn. Pre-existing on
    master for the not-in-project drop; the superseded drop came from this
    PR (60574f28). The scan now ignores snapshots of PRs outside its own
    project (a711f411; regression
    `tests/test_qa_resume.py::test_other_projects_snapshots_are_left_alone`
    fails with the fix reverted: 1 failed / 36 passed at a711f411, and
    passes with it: 37 passed).
    The project is loaded only when a snapshot of a PR that is neither
    tracked nor resumed is present, and PR ids found to be another
    project's are remembered (`app._foreign_qa_pr_ids`), so a long-lived
    foreign snapshot does not reload project.yaml on every 5 s scan. The
    set is cleared whenever project.yaml changes (inode, mtime, size):
    `store.save` replaces the file, an editor under `pm edit` may rewrite
    it in place. So a PR pulled or added after its snapshot was first seen
    is resumed on the next scan (review loop 5e26 i1/i2;
    `test_other_projects_snapshots_load_the_project_once`,
    `test_snapshot_seen_before_its_pr_arrives_resumes_after_pull`,
    `test_in_place_project_edit_also_forgets_foreign_ids`).
    Evidence is in `/pm-captures/scenarios/39` (REPORT.md):
    - Pre-fix: `pre-fix/story3`, `pre-fix/p2/recording.mp4`.
    - Post-fix: `post-fix/recovery` (P1 restarted while the fixed P2 ran;
      A/B snapshots kept, both resumed) and `post-fix/story3` (P2 restart
      resumed C with A/B unchanged).
    Full suite 3538 passed on a711f411 (env -u PM_HOST_HOME, /usr/bin
    first; `suite/full-suite.log`), and 3540 passed on 7968f576
    (`/pm-captures/review-5e26-i1/full-suite.log`).

### S41 follow-ups (QA scenario 41: two clones of one project)
30. Adopting a run orphaned in another clone (its own pm session on the
    same tmux server; the PR arrives by `git pull` or an in-place
    `pm edit`). Found live; all four need normal independent re-review.
    (a) *Adopted run finalized nowhere.* `resume_qa_sync` drove the run in
        the adopting TUI's own session, so `_run_qa_finalize_pane` did not
        find its `qa-<pr>` window (in the other clone's session) and the
        run ended `PASS (finalize=None)` with no finalizer. Relaunches
        would also have opened windows in the wrong session. The resumed
        run now uses the snapshot's session when it still exists
        (`_resume_session`, f22e6f4c). Workers, finalizer and any relaunch
        stay in the session that holds the run; the adopting TUI collects
        verdicts and writes the note.
    (b) *Pulled PR missing from the tree for up to 300 s.* A pull signals
        no reload, so the adopted PR's node appeared only at the
        background sync (4 min 25 s live). The scan now reloads the TUI
        state when it resumes a PR not in its loaded data (f22e6f4c).
    (c) *Conflicted pull killed the TUI.* A `git pull` that conflicts on
        project.yaml leaves conflict markers; the scan's `store.load`
        raised `ProjectYamlParseError` out of the poll tick, which re-raises,
        and Textual exited as soon as an unknown snapshot appeared. The
        scan now logs once per file stamp and skips until the file parses
        (c8ab2f4c). Review loop 2b8a i1 widened this to every load
        failure: a plan reference that does not validate
        (`PlanValidationError`) and a file missing mid-checkout (`OSError`)
        escaped the same way
        (`test_unloadable_project_file_does_not_escape_the_scan`).
    (d) *Check-then-adopt race.* The scan checked `resume_owned_elsewhere`
        on a snapshot read earlier, and the adopted loop wrote its pid
        later, so two TUIs could both adopt one run. `claim_resume_file`
        re-reads the snapshot under an exclusive flock (`qa_resume.claim`),
        re-checks owner and `loop_id`, and writes this process as owner
        before adopting (ec227cf0). Live S41 runs showed one winner each
        time (B on old code, A on old code, and the claim-code replay).
        Those are favorable timings, not proof: the guarantee comes from
        the claim, shown by a deterministic barrier regression (fails
        without the claim) and a two-process regression (fails 4/4 with
        the lock removed).
    (e) *Stale status in this clone.* A PR present here at an older
        status while the other clone moved it to QA was treated as "left
        QA" and its snapshot deleted once that clone's TUI died, so its
        restart had nothing to resume (S39's loss, between clones). The
        "left QA" cleanup now applies only to runs launched from this
        TUI's own pm session (snapshot `session_tag`, or none recorded).
        A run from another session is left alone until this project.yaml
        changes, whether or not that session is still up: provenance, not
        liveness, decides (`qa_loop.launched_elsewhere`). If a pull then
        brings the PR here in QA it is adopted and driven in its own
        session, or in this TUI's when that session is gone
        (`_resume_session`). Cost: a snapshot from another clone whose PR
        really left QA stays on disk until that clone's TUI drops it.
        Review loop 2b8a i2; `test_stale_status_keeps_another_clones_snapshot`
        (live and gone session; fails with no guard, and its gone-session
        case fails with a liveness-only guard),
        `test_stale_status_drops_this_sessions_own_snapshot`.
    Regressions in `tests/test_qa_resume.py` (each fails with its fix
    reverted): `test_resume_of_a_pulled_pr_reloads_the_tree`,
    `test_resumed_run_is_driven_in_the_session_that_holds_its_windows`,
    `test_unparseable_project_file_does_not_escape_the_scan`,
    `test_scan_does_not_adopt_a_run_another_tui_claimed_after_the_check`,
    `test_two_processes_claiming_one_orphan_get_exactly_one_owner`.
    Full suite 3549 passed on the d809b358 tree (code-identical to ec227cf0 after the rebase onto ee423ea9) (env -u PM_HOST_HOME,
    /usr/bin first; `/pm-captures/scenarios/41/tests/full-suite.log`).
    Evidence: `/pm-captures/scenarios/41` (REPORT.md).
31. Two-clone resume edge cases (S43; QA17 open points (a) and (b)). Found
    live; all need normal independent re-review (a817f5c9, b8c111eb).
    (a) *Idle TUI adopted only at the 300 s sync.* The resume scan runs on
        the shared poll timer, which a TUI with no running loop and no
        active PR with a workdir in its cached data stops. Another
        clone's orphaned run whose PR arrived by a pull waited for the
        background sync (53 s after the pull live; up to 300 s). An
        always-on 5 s timer (`_idle_qa_resume_scan`) scans while the poll
        timer is off; a scan failure is logged, never raised.
    (b) *Run resumed without its QA window finalized nowhere.* When the
        session holding a run is gone (the TUI's own session killed and
        restarted, or another clone's whole session gone), no `qa-<pr>`
        window is left and `_run_qa_finalize_pane` returned None:
        `PASS (finalize=None)`, also in the single-clone control, so
        pre-existing. The finalizer now opens the window in the driving
        session ("QA finalize: no qa-<pr> window in <session> — opening
        one").
    (c) *Runs of one PR from two clones superseded or adopted each other.*
        The scan ordered all snapshots of a PR together and dropped the
        older ones on liveness, and adopted the other clone's run once its
        own run finished. Now runs supersede only within one session, only
        this session's are dropped, and another clone's run is not adopted
        while this clone QA'd the PR alongside it. "Alongside" uses a run
        record kept in each QA workdir (`qa_run.json`: session_tag,
        started_at, written once at launch): an own run that is resumable,
        or whose status file was last written after the other run started,
        overlaps it (`run_overlaps_own_run`). So the guard survives a TUI
        restart, not only in memory. Intended adoption semantics: a PR
        that reached QA here only by a pull or an edit (S41), or another
        clone's run that started after this clone's own QA of the PR was
        over, is adopted; runs without a record (older) overlap nothing.
    (d) *Relaunched pane persisted only at the next tick.* One tick
        relaunches dead scenarios one after another, each after its retry
        backoff (5 s, doubling), and the snapshot was rewritten at the top
        of the next tick, so the dead pane id stayed on disk for 10 s or
        more (minutes on later retries). A TUI death then made the resume
        relaunch again beside the surviving worker. The snapshot is now
        written right after each successful relaunch.
    Regressions (each fails with its fix reverted;
    `/pm-captures/scenarios/43/tests/mutation-checks.log`):
    `test_idle_tui_keeps_scanning_for_resumable_runs`,
    `test_idle_resume_scan_is_scheduled_at_mount`,
    `test_run_qa_finalize_pane_opens_the_qa_window_when_it_is_gone`,
    `test_another_clones_run_of_the_same_pr_is_neither_dropped_nor_adopted`,
    `test_restarted_tui_adopts_another_clones_run_only_after_its_own_qa`
    (fresh app, retained records), `test_run_qa_sync_writes_the_run_record`,
    `test_relaunched_pane_is_persisted_before_the_next_tick`.
    Not fixed here: an existing PR's tree box stayed at its old status
    after a pull until a later reload (32 s live in S43, on a817f5c9).
    S42 fixed that in bb39b92e (reload when the shown status differs),
    which landed before the S43 commits were rebased onto it; S43 did not
    rerun live on the merged tree. Evidence: `/pm-captures/scenarios/43`
    (REPORT.md).

### S44 follow-ups (QA scenario 44: unloadable project.yaml)
32. A TUI with live routed QA must survive project.yaml becoming
    unloadable in any way a pull, merge or checkout can leave it. Found
    live in S44 (deb23fea, a4a45ffa, 67ea18e8); each regression fails with
    its fix reverted.
    (a) *Plans that do not validate killed the TUI at the 300 s sync.*
        A clean merge can leave a file that parses but whose plan parent
        does not exist. `background_sync` and `_load_state` caught only
        `ProjectYamlParseError`, so `PlanValidationError` escaped the
        timer (item 30(c) covered only the resume scan). Both now keep
        the previous state.
    (b) *A briefly missing project.yaml dropped the project root.* A
        sync or reload while a checkout had unlinked the file set
        `app._root = None`, so the resume scan stopped (an orphan was
        adopted 4 min 55 s late). The root and state are kept while the
        pm dir exists.
    (c) *A fresh TUI never logged the missing-file scan skip* (the
        missing file's `None` stamp equalled the default); a sentinel.
    (d) Review loop c1d4 i1: about 40 other TUI handlers that keep their
        state on an unloadable file also caught only
        `ProjectYamlParseError`, e.g. the QA NEEDS_WORK completion reload,
        so a run finishing while plans did not validate still raised out
        of the poll timer (reproduced). `PlanValidationError` is now a
        subclass of `ProjectYamlParseError`, so every such handler (and
        the CLI's `Error:` exit) covers both, and the explicit tuples from
        (a) are folded back.
        `tests/test_store.py::test_invalid_plans_are_an_unloadable_file`,
        `tests/test_qa_self_driving.py::test_needs_work_survives_plans_that_do_not_validate`;
        with the subclass reverted these and the (a)/item 30(c)
        regressions fail (5 tests).
    (e) Review loop c1d4 i2: since (b) keeps the root while project.yaml
        is missing, those handlers then called `store.load` on a missing
        file and `FileNotFoundError` escaped the poll timer the same way
        (reproduced: QA NEEDS_WORK completion during the absence). `load`
        now raises `ProjectYamlMissingError`, both a
        `ProjectYamlParseError` and a `FileNotFoundError`: "no project"
        callers (the `_load_state`/`background_sync` root checks, the
        CLI) are unchanged, and keep-state handlers survive.
        `tests/test_store.py::TestMissingProjectFile`,
        `tests/test_qa_self_driving.py::test_needs_work_survives_a_missing_project_file`
        (both fail with the subclass reverted).
    Not fixed here: a TUI never resumes a later orphaned run of a PR it
    already resumed or dropped once (`_resumed_qa_pr_ids` is never
    cleared; pre-existing, filed pr-43b14d2).
    Full suite 3575 passed on the c1d4 i1 tree (env -u PM_HOST_HOME, /usr/bin first;
    `/pm-captures/review-c1d4-i1/full-suite.log`). Evidence:
    `/pm-captures/scenarios/44` (REPORT.md).
33. (S46, RQ37 completions and restarts; two clones) Live on 4d8f968a,
    every completion processed while project.yaml could not be loaded
    lost its result: `_record_qa_note` / `_transition_pr_status` only
    logged a warning and `poll_qa_state` cleared the snapshot right
    after, so an adopted run (driven in the other clone's session), this
    clone's own run (conflict markers) and an adopted run whose session
    was gone (file missing) each ended with 0 QA notes and nothing
    retried, while the TUI said "press i to sign off" and the picker read
    `[done PASS]`.  A TUI restarted on a conflicted file, or on plans
    that do not validate, died at mount (`guide.detect_state`
    RuntimeError, then `TUI unmount`).
    (a) a9b966ec: a finished run is processed only once project.yaml
        loads (`_completion_waits_for_project`; one "waiting for
        project.yaml" line per reason); its snapshot stays meanwhile, so
        a restart in between recovers it once.  `_load_state` with no
        previous state shows the tree instead of the guide and reloads
        on the 5 s idle timer once the file changes.
    (b) 54c88ad8 (review of (a), the race between the load check and a
        write): the transition and note are written first, each once
        (`_record_completion`); nothing else runs until both took, and
        the whole completion is retried.  Follow-ups (review loop start,
        zz t `start_qa`, sign-off, tree reload) report False on an
        unloadable file and are retried on their own; a retried zz t
        restart that replaced the run only drops the old snapshot.  The
        sticky "cannot be loaded" line is cleared on load (live it hid
        "QA PASS ... press i").
    (c) e52e8fac: the empty tree names the reason
        (`TechTree.update_prs(unavailable=)`), not Textual's
        "TechTree#tech-tree" placeholder.
    `tests/test_qa_completion_unloadable.py` (13, plus (d)'s 2; the 7 file-state tests
    fail on 4d8f968a, the 5 race tests on a9b966ec).  Planning-phase
    guards are S45's (e11b952a, 8400faf7, 0454edaf).  Full suite 3610
    passed on e52e8fac (`/pm-captures/scenarios/46/tests`).  Spec notes:
    the resume scan logs "scan skipped" only when it needs the file (an
    untracked snapshot exists), so a missing file with every run already
    adopted logs only the completion's wait line; release to "QA
    complete" takes ~90 s in the S41-S46 harness, longer than S46 story
    3's 60 s cap.  Evidence: `/pm-captures/scenarios/46` (REPORT.md).
    (d) Review loop 7026 i1: a follow-up that fails after both writes
        keeps the snapshot for its retry, so a TUI restart in that gap
        re-processed the completion from the snapshot and wrote the QA
        note a second time.  `_record_qa_note` now skips a note this run
        already has (same verdict, ending in this run's `(workdir: …)`;
        the summary is rebuilt from the snapshot, so it is not compared).
        Runs with no QA workdir are not deduplicated.  The sticky "cannot
        be loaded" line is cleared by its arrival number, so a newer
        message keeps the log line.
        `test_restart_while_a_follow_up_is_pending_records_no_second_note`
        (fails with no guard and with an exact-text guard),
        `test_qa_notes_of_different_runs_are_all_recorded`.  Full suite
        3624 passed on ba5dd6e7 (`/pm-captures/review-7026-i1`), again in
        review loop 7026 i2 (`/pm-captures/review-7026-i2`).
34. (S45, RQ37 one clone, every QA phase) Live on 4d8f968a, a run in
    planning died "QA thread crashed" 9 s after a conflicting pull (the
    mid-planning merge guard's `store.load`), and a review PASS during the
    failure dropped the zz t / auto-start review → QA hand-off for good.
    (a) e11b952a: the three merge guards skip a round
        (`_live_pr_status`, one warning per reason, then "loads again");
        the start, spec-gate and resume loads wait until the file loads
        (`_load_project_waiting`, 5 s retry, "Waiting for project.yaml to
        load again (…)" on the TUI).  `tests/test_qa_load_failures.py`.
    (b) 8400faf7: a stop during that wait ends the run quietly (no
        verdict from the stale data, no launch).
    (c) 0454edaf: the sync skip for an absent file names
        `<root>/project.yaml`, not the cwd lookup's "cd into your repo".
    (d) be8f23d1, 85463cfe, 195889a5: the review → QA hand-off is kept
        pending at the step that failed (`app._pending_auto_qa`: the
        in_review → qa write, or the QA start after it) and retried every
        poll tick, which stays on while one is pending; it launches once
        and is dropped when zz t is stopped, auto-start no longer covers
        the PR, the PR left qa or a QA run started.  One warning per
        reason.  `tests/test_review_qa_handoff_unloadable.py`.
    Observation (unchanged): zz t on an in_review PR does not move it to
    qa.  Full suite 3622 passed on 8ff5e7a2.  Evidence:
    `/pm-captures/scenarios/45` (REPORT.md).
35. (S49, RQ37 one note per run across two clones) Live on 3ebe4d7a:
    clone A adopted clone B's run (snapshot `session_tag` = B), recorded
    its PASS note, and the auto-start sign-off hand-off then failed (the
    project lock held, then an unloadable file), so the snapshot was kept
    for the retry.  A's TUI was killed and B's TUI started first.  B's scan
    took the run as its own (B's tag, dead owner), recovered it and wrote a
    second, separately created note in B's project.yaml, which lacked A's
    note.  Both notes had the same id (it hashes the text) and different
    `created_at` values (06:35:48 in A, 06:35:52 in B), so the ba5dd6e7
    dedupe cannot help across clones.  Fix: once `_record_completion` has
    written the result, `qa_loop.mark_result_recorded` writes
    `result_recorded_by: <this session tag>` into the snapshot under the
    claim lock.  `_resume_incomplete_qa` leaves a finished run recorded by
    another session to that session (kept, treated as foreign until
    project.yaml changes), and `claim_resume_file` refuses it.  A run this
    session recorded is processed here wherever it was launched: this
    session's own-run cleanup applies to it, and the same-PR overlap
    gate (which leaves another clone's run to that clone) does not hold
    it back.  `mark_result_recorded` writes only into the snapshot of the
    recorded run (same `loop_id`) and only when the process has a pm
    session; both guards are defensive, since every run has its own QA
    workdir (review loop 679d i3,
    `test_mark_result_recorded_touches_only_its_own_runs_snapshot`).
    Cost: if the recording clone never returns, its
    pending follow-up stays undone, as for any foreign snapshot.  Tests
    (each mutation-checked) are in `tests/test_qa_resume.py`:
    `test_run_recorded_by_another_clone_is_left_to_it`,
    `test_recorded_here_run_whose_pr_left_qa_is_dropped_here`,
    `test_claim_refuses_a_run_recorded_by_another_session`,
    `test_completion_marks_its_snapshot_and_the_launching_clone_records_no_second_note`,
    `test_recorded_here_run_is_processed_even_beside_this_clones_own_run`.
    Full suite 3629 passed.  Evidence: `/pm-captures/scenarios/49`.
36. (S47, RQ37 one note per run, one clone) Live on 3ebe4d7a: the
    `zz t` gap (note written, "restarting QA" `start_qa` failed on an
    unloadable file, snapshot kept) was reached, the TUI was killed, and
    after the restart the run was neither recovered nor reported.  The
    first `zz t` pass never moved an `in_review` PR to `qa` (later passes
    go through `start_qa`, which does), and `_resume_incomplete_qa` drops
    the snapshot of a run whose PR is not in `qa`.  So any first-pass `zz
    t` run of an `in_review` PR was lost silently at a TUI restart,
    mid-run or finished (pre-existing on master; the S45 observation
    "zz t on an in_review PR does not move it to qa").  Fix:
    `start_or_stop_qa_loop` makes the same in_review -> qa transition as
    `start_qa` (shared `_enter_qa_status`; on a lock timeout or an
    unloadable file it shows `Error: ...` and starts nothing).  Tests
    `TestZZTStart::test_moves_an_in_review_pr_to_qa` and
    `test_unlockable_project_starts_nothing` (both fail with the call
    removed).  Evidence: `/pm-captures/scenarios/47`.
37. (S47) A run whose driver died during the blocking finalizer (the S12
    method, `pm pr qa-run-bg` killed once `qa_status.json` had `overall`)
    was recovered once with one note, but the note read
    "QA PASS: S47 one: ?; S47 two: ?": `run_qa_sync` refreshed the resume
    snapshot with the final scenario verdicts only after the finalizer,
    while recovery rebuilds the summary from the snapshot (pre-existing on
    master).  The snapshot is now written before `overall` is published
    (a restart between the two writes resumes the run with every verdict
    in hand, which aggregates again).  Regression
    `TestSnapshotBeforeOverall` reads the snapshot when `overall` is
    written; it fails with the write after the publish and without it.
    This fixes only the note text.  The interrupted finalizer itself is
    still not re-run or adopted on recovery (pr-0f85376, unchanged).
38. (S48, RQ38: `pm edit` held open, project lock held until the editor
    quits) Live on 3ebe4d7a, a finished NEEDS_WORK run retried
    `_transition_pr_status` on every poll tick, and each try waited the
    full 2 s lock timeout on the TUI loop: keys took ~2 s, the spinner
    and cast had 4 s gaps, and a StoreLockTimeout warning was logged
    every ~4 s (15 in 154 s).  The result itself was kept (RQ37).
    (a) 716d6ce1: TUI writes retried per poll tick make one non-blocking
        attempt (`store.NO_WAIT`): the completion transition + note, the
        review → QA hand-off status write, the launch's
        `clear_return_awaiting` and the shared `_enter_qa_status` via
        `start_qa(lock_timeout=)`, and the recovered completion.  A held
        lock keeps the result / follow-up / hand-off pending with its
        snapshot, says so once (`store.LOCK_BUSY_REASON`, "waiting for
        project.yaml to be unlocked …") and lands on the first tick after
        the release.  There is no separate lock probe (no check-then-act
        race).  User keys and the CLI keep the 2 s wait.
        `tests/test_project_lock_held.py`.
    (b) 006d7b4d: the hand-off waiting line is sticky, so the sticky
        "Review loop done … PASS" line logged just before no longer hides
        it; the expected NO_WAIT timeout is not logged per tick.
    (c) Review loop 679d i1: `start_signoff` takes `lock_timeout`; only
        its retried callers (the QA completion follow-up
        `_trigger_signoff`, the `advance_all` scheduler pass) pass
        `NO_WAIT`.  716d6ce1 made every call non-blocking, including the
        skip_qa review PASS hand-off (`_maybe_auto_merge`), which nothing
        retries, so a pm process holding the lock for a moment (a
        `pm pr note add` from a pane) lost that hand-off and the TUI said
        it "waits".  That one-shot path keeps the 2 s wait and reports a
        longer hold as `Error:` (as on master).  Residual, pre-existing on
        master and not fixed here: a holder past 2 s (an open `pm edit`)
        or an unloadable file still loses that skip_qa hand-off, since
        nothing retries it (filed pr-7cf1fe4).  The "already said it
        waits" set is cleared on every other outcome, so a later
        hand-off of the same PR that meets a held lock says so again
        (review loop 679d i4,
        `test_later_sign_off_wait_of_the_same_pr_is_said_again`; it fails
        when a hand-off that went through keeps the PR in the set).  Also: once the
        result is recorded and only a follow-up waits for an unloadable
        file, the wait line says "recorded — follow-up waiting for
        project.yaml to load" instead of "… to load to record it" (S49
        observation).  `test_one_shot_sign_off_hand_off_rides_out_a_brief_holder`,
        `test_scheduler_pass_hands_off_without_waiting`,
        `test_wait_line_after_the_result_was_recorded_names_the_follow_up`,
        each fails with its fix reverted
        (`/pm-captures/review-679d-i1/mutation-checks.log`).
        `test_review_pass_waits_and_starts_qa_once_the_file_loads` read
        warnings through caplog, which sees nothing from a pm module
        logger (`configure_logger` sets `propagate = False`) unless an
        earlier test reset it: it failed on its own and passed only in
        suite order.  It now patches the module `_log`.
    Full suite 3645 passed on 64b41a91 (`/pm-captures/review-679d-i1`)
    and again on 82f22b1f in review loop 679d i2
    (`/pm-captures/review-679d-i2`; env -u PM_HOST_HOME, /usr/bin first),
    3646 in review loop 679d i3 (item 35 guard test added;
    `/pm-captures/review-679d-i3`), and 3647 in review loop 679d i4
    (sign-off wait-set test added; `/pm-captures/review-679d-i4`).
    Earlier QA19 runs: 3642 on the S47 tree (3a3dcc3e), 3641 on
    006d7b4d (S48), 3629 on b740e188 (S49), each in its REPORT.md.
    Evidence: `/pm-captures/scenarios/48` (REPORT.md).

39. (S50, RQ38 one-shot hand-offs, host, one clone + a pre-fix control on
    ca8fa055) 64b41a91 held live: a skip_qa review PASS that meets a
    1.5 s / 0.2 s cyclic holder waits once inside a hold (~0.9 s) and
    moves to sign_off at its release (one window); a hold past 2 s
    (`pm edit` open) is one `Error: Could not acquire lock …` plus one
    `start_signoff: StoreLockTimeout` warning, no "waits" line, and the
    PR stays in_review (pr-7cf1fe4); the control says "Sign-off for X
    waits …" and leaves X in_review (298 s).  The retried callers (QA
    completion follow-up across a SIGNOFF_REQA round; the scheduler pass
    after a kill -9 + `pm session` respawn and re-arm) stay non-blocking
    and say "waits" once per wait.  Three log-line visibility defects,
    all pre-existing on master, were fixed:
    (a) 4fb42e06: under skip_qa the hand-off runs in the same frame as
        the sticky "Review loop done … PASS" line (sticky=10), so
        "Auto-start: X review passed, skipping QA", "Auto-start: X →
        sign-off" and the one-shot "Error: …" (or a retried caller's
        "Sign-off for X waits …") were logged only as "(hidden by sticky
        message)".  The skipping line and `start_signoff`'s outcome lines
        are forced and held (`CONFIRM_HOLD_SECONDS`, `signoff_ui._SHOWN`).
        `test_skip_qa_hand_off_lines_are_painted_after_the_review_done_line`
        (real log-line logic) and a kwargs check in
        `test_start_signoff_waits_for_a_held_lock`.
    (b) e60c9927: `log_message` treated a hold as over when its time ran
        out, before its flush timer ran, so a message arriving in that gap
        was shown at once and dropped the confirmations the hold had
        queued (a fast sign-off's "✓ X signed off" dropped "→ sign-off").
        While queued confirmations wait for their flush, later messages
        are queued or deferred behind them as during the hold (flush
        replays exempt).  `test_message_after_expiry_waits_for_the_pending_flush`.
    (c) f19831c2: after a TUI restart the resume scan recovers a finished
        run and says "QA PASS for K — waiting for project.yaml to be
        unlocked to record it" once, but another run's "Resuming QA …"
        in the same frame replaced it before it was painted.  The
        completion wait lines (lock, load, "recorded — follow-up
        waiting") are forced and held (`qa_loop_ui._WAIT_SHOWN`).
        `test_completion_wait_line_is_not_replaced_by_a_same_frame_resume`.
    (d) Review loop 350f i1.  Since (b), a non-empty queue holds the line
        until a flush runs.  Textual sleeps 0.5 ms short of a timer's
        delay, so a flush can fire just before `_log_hold_until`.  It then
        returned ("a newer hold is active") although no other flush timer
        was pending, and the queue held the line for good: every later
        unforced or held message was deferred or queued and never painted,
        until a forced, unheld one.  Measured here, the timer fired 51–68
        µs after the deadline at minimum (idle and under full CPU load).
        That margin comes from Textual's internals, not a guarantee.  The
        flush now counts its pending timers (`_log_flush_timers`).  A timer
        that fires early with no other one pending re-arms for the time
        left, and a queue with no flush pending holds nothing.  Also, the
        one-shot skip_qa hand-off's `Error:` for an unloadable file is
        forced and held like the lock `Error:` from (a).  Unforced, the
        sticky "Review loop done" line hid it, so the loss (pr-7cf1fe4)
        went unseen.  A retried caller meets the same file on every tick,
        so its line stays unforced.
        `test_flush_timer_firing_just_before_the_hold_ends_rearms`,
        `test_queue_without_a_pending_flush_holds_nothing` and the
        `[unloadable]` case of
        `test_skip_qa_hand_off_lines_are_painted_after_the_review_done_line`
        each fail with their fix reverted
        (`/pm-captures/review-350f-i1/mutation-checks.log`).  Full suite
        3654 passed, rc 0 (`/pm-captures/review-350f-i1/full-suite.log`).
    (e) Review loop 350f i2.  `auto_start.check_and_start` forces
        "Auto-start: starting <pr>" unless a hold is active, and judged
        that from `_log_hold_until` alone.  Since (b) a hold also lasts
        while its queued confirmations wait for their flush, so in that gap
        the forced line dropped them.  Both now use one predicate,
        `app.log_line_held` (hold time, or a queue with a flush pending).
        `test_starting_message_waits_for_queued_confirmations_flush` fails
        with the old check
        (`/pm-captures/review-350f-i2/mutation-checks.log`).
    (f) Review loop 350f i3 (test only).  A flush's replays are judged by
        the hold's time alone, not by `log_line_held`: a flush timer
        delayed past a later hold runs while that hold's timer is still
        pending, and by the shared predicate each replay of a queue of two
        or more would be queued again behind the next, forever (TUI hang).
        No test caught that mutation;
        `test_late_flush_with_another_flush_pending_releases_the_queue`
        now does (`/pm-captures/review-350f-i3/mutation-checks.log`).
        Full suite 3656 passed, rc 0
        (`/pm-captures/review-350f-i3/full-suite.log`).
    10 mutations, each caught (`/pm-captures/scenarios/50/tests/mutations.log`).
    Live runtime heads (by process, not by checkout): story 1 final run in
    a TUI restarted in place on e60c9927; story 2 on e60c9927; story 3 on
    e60c9927 (P2 TUI restarted in place); story 4 final run pre-kill in a
    TUI spawned after f19831c2, post-restart in TUIs respawned after
    f19831c2.  Full suite 3651 passed, 4 warnings, 187.29 s, rc 0 on
    f19831c2 (`/pm-captures/scenarios/50/tests/full-suite-f19831c2.log`;
    env -u PM_HOST_HOME, scratch venv, PYTHONPATH=/workspace).
    Not fixed here: `pm meta` ends with `rm -rf ~/.pm/sessions/<tag>`
    (cli/meta.py), deleting the whole shared session dir on a normal exit
    (note-2bc73f1 on pr-7f90572).  Evidence: `/pm-captures/scenarios/50`
    (REPORT.md).

40. (2026-10-24 all-role scope update) c1c08d83: implementation, review and
    sign-off build their command with `container=` in container mode
    (bridge-ensure step, in-container router URL, plain `claude`) and pass
    the provider to `container.wrap_claude_cmd`, which runs
    `worker_route.check_route(container=True)` before creating the
    container and adds the route bridge mount; an unavailable route raises
    `ContainerError` (the callers print it and launch nothing).  The
    sign-off command now carries the tmux session tag like impl/review.
    Review loop e0e8 i1: `create_container` reuses a running container by
    name, and a container created before the route was selected has no
    socket mount, so its in-container ensure step would refuse to start
    Claude with a QA-worded remedy.  The wrapper now refuses that reuse up
    front ("running without the route socket mount", remedy: end the
    session using it, remove the container, launch again).  Review and
    sign-off remove their container first, so this matters for impl.
    Review loop e0e8 i2: that removal used the untagged name
    (`pm-review-<pr>`), while `wrap_claude_cmd` creates
    `pm-<session tag>-review-<pr>`, so it removed nothing and a still
    running container was reused (pre-existing on master for review and
    sign-off; the race the removal comment describes was never closed).
    Both now remove the session-tagged name.  The route remedies were
    QA-worded for these roles ("QA launches the session automatically",
    "pm model set qa_concretize …"); `check_route(session_type=)` (passed
    through `wrap_claude_cmd(session_type=)`) now says to launch the
    session again, or to move it to the main account by removing the PR
    override that selects the route (`session_models` entry or `model`;
    item 41) or `pm model set <type> <model> --project`.  The QA
    gates keep their wording.  The in-container ensure remedy also names
    relaunching a non-QA session.
    `test_workflow_role_remedy_says_relaunch_not_qa_wait[router_down|expired|unconfigured]`,
    `test_signoff_removes_the_session_tagged_container_it_recreates`, and
    assertions in the review/sign-off/impl wiring tests; 9 mutations
    caught (`/pm-captures/review-e0e8-i2/mutation-checks.log`).  Full
    suite 3673 passed, rc 0 (markdown 3.10.3 installed first;
    `/pm-captures/review-e0e8-i2/full-suite.log`).
    Regressions in `tests/test_worker_route.py`
    (`test_workflow_container_route_mount_and_fail_closed[down|fresh|reused_mounted|reused_unmounted]`,
    `test_unrouted_provider_reuses_a_running_container_untouched`,
    `test_impl_start_builds_and_wraps_for_the_selected_route`), plus the
    review and sign-off wiring tests; 9 mutations caught
    (`/pm-captures/review-e0e8-i1/mutation-checks.log`).  Review loop 350f
    i4's preserved tests (9c42bb6e) catch all 11 of its mutations
    (`/pm-captures/review-e0e8-i1/mutation-checks-i4-rerun.log`).  Live:
    this review ran in a routed review container (ensure step, router env,
    `ANTHROPIC_API_KEY`/`AUTH_TOKEN` unset;
    `/pm-captures/review-e0e8-i1/live-review-container-route.txt`).
    Full suite 3669 passed, rc 0 (env -u PM_HOST_HOME, /usr/bin first,
    PYTHONPATH=/workspace; markdown 3.10.3 installed first;
    `/pm-captures/review-e0e8-i1/full-suite.log`).

41. (Per-PR role exceptions, user commits f1865615 and 32df2893; review
    loop e0e8 i3.)  A PR's `session_models` mapping overrides its
    `model` for one role: `get_pr_model_override(pr, <type>)` returns the
    role's entry, then its parent role's (`_FALLBACK_TYPES`: `qa_*` ->
    `qa`, `signoff` -> `review`), then the PR `model`.  `PM_MODEL` still
    wins.  Implementation, review, merge, sign-off and every QA type
    (`_resolve_qa_model`, which the route gates, mounts and `describe`
    also use) pass their type.  s0 resolves `qa_interactive`, so a worker
    exception never moves it.  32df2893 sets the DeepSeek/GLM trial PRs
    (pr-ace66e5, pr-7f90572) to sign off on `provider:claude-work`; this
    PR keeps `model: provider:claude-work` for every role.
    Review loop e0e8 i3 fixes:
    (a) The route remedies (item 40 and the QA gates) told the user to
        remove the PR's `model` override, or only to `pm model set` the
        QA types, while a `session_models` entry may be what selects the
        route, and a PR override wins over `pm model set`.  Both now name
        "the PR's 'session_models' entry or 'model' override".
    (b) A non-mapping `session_models` (hand-edited YAML) is ignored: a
        string matched roles by substring and then raised `TypeError`.
    (c) `validate_model_config` reports a PR `session_models` that is
        not a mapping or names an unknown type (e.g. `sign_off` would
        leave sign-off on the PR-wide model), also when `model_config`
        itself is malformed.  `pm model show` lists PR overrides and
        prints those problems under "Problems in project.yaml model
        settings".
    Tests: `tests/test_model_config.py` (`test_qa_roles_resolve_their_pr_exception`,
    `test_merge_window_resolves_its_pr_exception`,
    `test_malformed_session_models_fall_back_to_the_pr_model`,
    `test_pr_session_models_problems_flagged`,
    `test_non_mapping_model_config_still_checks_prs`,
    `test_model_show_lists_pr_overrides_and_their_problems`), and the
    impl/review wiring tests now route by a role exception over a main
    PR-wide model and check the resolved role.  12 mutations caught,
    one per call site and fix
    (`/pm-captures/review-e0e8-i3/mutation-checks.log`).  Full suite
    3682 passed, rc 0 (env -u PM_HOST_HOME, /usr/bin first,
    PYTHONPATH=/workspace; markdown 3.10.3 installed first;
    `/pm-captures/review-e0e8-i3/full-suite.log`).
    (d) Review loop e0e8 i4: s0's legacy fallback (a plain-model
        `qa_scenario` from configs before `qa_interactive`) also read the
        PR's `session_models`, so `session_models: {qa_scenario: haiku}`
        on a PR without `model` moved s0 to haiku, contrary to the rule
        above.  That step now reads project/global settings only.
        `test_plain_worker_exception_does_not_move_s0` fails with the PR
        passed to it (`/pm-captures/review-e0e8-i4/mutation-checks.log`).
        Full suite 3683 passed, rc 0 (markdown 3.10.3 installed first;
        `/pm-captures/review-e0e8-i4/full-suite.log`).
    (e) Review loop e0e8 i5: a role entry that is blank (`signoff:` with
        no value) or not a string was taken as the role's value.  A blank
        one silently dropped the PR `model` for that role (sign-off on the
        project default), and a non-string one raised `AttributeError` at
        every launch of the role.  Such entries now count as absent (the
        parent role, then the PR `model` apply), and
        `validate_model_config` reports them.
        `test_blank_or_non_string_role_entries_count_as_absent`,
        `test_pr_session_models_bad_values_flagged` (each fails with its
        fix reverted; `/pm-captures/review-e0e8-i5/mutation-checks.log`).
        Full suite 3685 passed, rc 0 (markdown 3.10.3 installed first;
        `/pm-captures/review-e0e8-i5/full-suite.log`).
    (f) Review loop e0e8 i6: a provider that this host does not configure
        (strict `get_provider`, R3) raises `ProviderNotFoundError` from
        `build_claude_shell_cmd`.  Implementation, review, sign-off and merge
        build their command before `wrap_claude_cmd`'s route check, so the
        check's role-aware "unconfigured" remedy (item 40) never ran for
        them.  The CLI printed a traceback with the message on its last
        line, and the review loop shows only `stderr[:500]` of
        `pm pr review`, so its error had no remedy at all.  QA planner, s0,
        verifier and finalizer have no route gate, so the run ended with a
        bare "QA thread crashed".  Now `pm`'s `main()` prints one
        `Error: <message>; or change the model setting that selects it
        ('pm model show' lists them, PR overrides included)` line, rc 1, and
        a QA thread stopped by it shows `QA stopped: <message>; … then start
        QA again` (`qa_loop._crash_output`; other crashes keep their text).
        Nothing falls back to the main account.
        `test_unconfigured_provider_is_a_clean_cli_error`,
        `test_unconfigured_provider_explains_a_stopped_qa_run[start|resume]`,
        `test_other_qa_thread_crashes_keep_their_message`; 4 mutations
        caught (`/pm-captures/review-e0e8-i6/mutation-checks.log`).
        Full suite 3690 passed, rc 0 (markdown 3.10.3 installed first;
        `/pm-captures/review-e0e8-i6/full-suite.log`).
    (g) Review loop e0e8 i7: a routed sign-off whose route is unavailable
        in container mode (item 40's `ContainerError`) was caught in
        `launch_signoff_window`, printed to stdout, and `pm pr signoff`
        exited 0 (pre-existing handling, now reached by route failures).
        The TUI sign-off driver (`signoff_ui._launch_quiet`) discards
        stdout and shows a failed launch's last stderr line, so it logged
        "launched" and the remedy was never shown; only the 60 s relaunch
        backoff retried it silently.  The error now propagates to
        `pm pr signoff`, which prints it on stderr with rc 1, like
        `pm pr start`/`pm pr review`, so the TUI shows "Sign-off launch
        failed for <pr>: work route … Remedy: …".
        `test_container_error_is_a_failed_launch_on_stderr`,
        `test_unavailable_route_propagates_and_opens_no_window`; 3
        mutations caught (`/pm-captures/review-e0e8-i7/mutation-checks.log`).
        Full suite: `/pm-captures/review-e0e8-i7/full-suite.log`.
    (h) Review loop e0e8 i8: the same gap for implementation under
        auto-start.  `auto_start._start_pr_quiet` runs `pm pr start
        --background` and, on rc != 0, only logged a pm-log warning, so a
        routed impl whose work route is down (item 40's `ContainerError`,
        printed on stderr with rc 1) showed "Auto-start: starting <pr>"
        and nothing else; the scheduler has no periodic pass, so the PR
        then sat in_progress with no window until some unrelated event.
        Pre-existing for every start failure (i7 recorded it as an
        observation).  The last stderr line is now shown as "Auto-start:
        pm pr start <pr> failed: …" (markup-escaped), forced and held like
        the other one-shot errors.  Later passes start the PR again (an
        in_progress PR whose spec awaits approval fails on each), so each
        reason is said once per PR until a start goes through.  Review
        loop e0e8 i9: an explicit re-arm (`autostart` target re-add, `A`,
        `autostart all`) asks for a start now, so it forgets the reason
        shown for those PRs; a retry that fails the same way (route still
        down) is said again instead of leaving only the targets line
        (`test_explicit_rearm_says_a_shown_start_failure_again`, both
        cases fail with their clear removed;
        `/pm-captures/review-e0e8-i9/mutation-checks.log`).
        `test_failed_start_shows_its_reason_on_the_log_line`; 7 mutations
        caught.  i7's `test_unavailable_route_propagates_and_opens_no_window`
        now also checks that no window opened and the per-PR launch lock
        was released (mutation caught).
        (`/pm-captures/review-e0e8-i8/mutation-checks.log`; full suite
        `/pm-captures/review-e0e8-i8/full-suite.log`; after i9 3695
        passed, rc 0, `/pm-captures/review-e0e8-i9/full-suite.log`.)
    (i) Review loop e0e8 i10: the sign-off driver's failure line
        (`signoff_ui._launch_quiet`, which (g) made carry the route
        remedy) put the stderr line or exception text into markup
        unescaped, unlike (h)'s line.  A "[...]" in it was dropped, and a
        "[/...]" made the log line refuse the whole message (the
        `MarkupError` is swallowed, so nothing was shown).  Both are now
        escaped (pre-existing on master).
        `test_launch_failure_reason_is_text_not_markup`,
        `test_launch_exception_is_text_not_markup`; 2 mutations caught
        (`/pm-captures/review-e0e8-i10/mutation-checks.log`).  Full suite
        3698 passed, rc 0 (markdown 3.10.3 installed first;
        `/pm-captures/review-e0e8-i10/full-suite.log`).
    (j) Review loop e0e8 i11: (h)'s re-arm forgot the shown reason only
        for the PRs named as targets, but the pass it asks for starts the
        whole target closure, and the PR that fails is usually a
        dependency (a target waits for its dependencies).  Re-adding the
        target while the route was still down then left only the targets
        line, which is what (h)'s i9 fix was for.  An explicit re-add now
        forgets every shown reason, as `autostart all` does.
        `test_rearming_a_target_says_its_dependencys_shown_failure_again`
        fails with the i9 per-target clear
        (`/pm-captures/review-e0e8-i11/mutation-checks.log`).  Full suite:
        `/pm-captures/review-e0e8-i11/full-suite.log`.
    (k) Review loop e0e8 i12: (c) keeps checking PRs when `model_config`
        is not a mapping, but its only caller, `pm model show` (where a
        provider error points the user), resolved every type first and
        crashed on that file (`AttributeError`/`TypeError` for a string or
        blank `model_config`, or a string `session_models`/`session_effort`
        block), so the problems were never printed.  It now says "Effective
        config not shown: model_config is malformed", skips the per-type
        table and Routes, and still lists the PR overrides and the
        problems.  Launches with such a file still fail (pre-existing;
        never a silent fallback).
        `test_model_show_reports_a_malformed_model_config[string|blank|models_block|effort_block]`
        (all four crash pre-fix; 2 mutations caught,
        `/pm-captures/review-e0e8-i12/mutation-checks.log`).  Full suite:
        `/pm-captures/review-e0e8-i12/full-suite.log`.
    (l) Review loop e0e8 i13: (e)'s twin at project level.  A blank or
        non-string `model_config.session_models.<type>` value (`signoff:`
        with no value) raised `AttributeError` at every launch of that
        type and in `pm model show` (the block is a mapping, so (k) did
        not apply), and `validate_model_config` reported nothing
        (pre-existing on master).  Such a value now counts as absent (the
        parent type, then global settings apply) and is reported.
        `test_blank_or_non_string_project_entries_count_as_absent`,
        `test_project_session_models_bad_values_flagged`,
        `test_model_show_reports_a_blank_project_entry` (2 mutations
        caught, `/pm-captures/review-e0e8-i13/mutation-checks.log`).  Full
        suite: `/pm-captures/review-e0e8-i13/full-suite.log`.
    (m) Review loop e0e8 i14: a blank block (`model_config:`,
        `session_models:` or `session_effort:` with every entry commented
        out, e.g. after commenting out the last route entry) loads as
        None.  Every launch of every type raised (the effort block is
        read even under a PR override), and so did `pm model set
        --project`, the remedy the route errors name, and `pm model
        unset --project` (pre-existing on master; (k) reported a blank
        `model_config` as malformed).  A blank block selects nothing, so
        it now reads as empty (`project_model_config`, `config_block`) in
        resolution, validation, `pm model show`, `set` and `unset`; a
        non-mapping block is still malformed and still fails launches.
        A blank or non-string `session_effort` level counts as absent like
        a model entry (parent type, then global; it reached `--effort`
        before) and stays reported.
        `test_blank_blocks_count_as_empty[model_config|session_models|session_effort]`,
        `test_blank_block_keeps_the_other_block`,
        `test_blank_or_non_string_effort_entries_count_as_absent`,
        `test_blank_blocks_are_valid`,
        `test_model_show_resolves_blank_blocks`,
        `test_model_set_and_unset_fill_a_blank_block` (all 10 fail
        pre-fix; 6 mutations caught,
        `/pm-captures/review-e0e8-i14/mutation-checks.log`).  Full suite:
        `/pm-captures/review-e0e8-i14/full-suite.log`.
42. (S53, RQ40 route failures on workflow roles, container + host modes;
    live on 27258d15, captures `/pm-captures/scenarios/53`, REPORT.md.)
    Four display defects, each with a failed Then live and a post-fix
    replay:
    (a) Auto-start's "Auto-start: starting <pr>" was only deferred while
        the "targets +=" hold was active.  When `pm pr start` failed
        within that hold (route down), the failure line (a newer held
        confirmation) was queued and its flush dropped the older deferred
        line, so the user never saw that a start was attempted.  During a
        hold it is now queued with a hold of its own
        (`test_starting_message_survives_a_start_that_fails_within_the_hold`;
        the two older "deferred" tests now assert the queue).
    (b) `pr_view.run_command` (TUI `s`, `d`, `i`, …) put the CLI's last
        stdout/stderr line and exception text into log-line markup
        unescaped, so a route remedy naming `/tmp/s53/creds[work]/…`
        showed `/tmp/s53/creds/…` (the sign-off driver and auto-start
        already escaped their copies).  All five sites escape now
        (`tests/test_pr_view_command_text.py`).
    (c) "Review loop done … PASS" was sticky but not held, so the skip_qa
        hand-off's held lines logged in the same frame ("skipping QA",
        "→ sign-off", an "Error:") replaced it before it ever painted.
        The announcement (now `review_loop_ui._announce_loop_done`) holds
        the line like the other confirmations, so the hand-off lines queue
        behind it
        (`test_review_done_line_is_painted_before_the_skip_qa_hand_off[free|unloadable]`).
    (d) `pm model show` listed no Routes when only PR overrides select a
        route.  Each PR override now gets one Routes line per distinct
        route, naming the types it covers ("all types" when every type
        follows it), resolved as its launches do
        (`test_model_show_lists_routes_that_pr_overrides_select`).
    8 mutations caught (`/pm-captures/scenarios/53/post-fix/tests/mutations.log`).
    Full suite 3722 passed (`/pm-captures/scenarios/53/post-fix/tests/full-suite.log`).
    (e) Review loop 0f64 i1: (d) also listed types that a PR override
        leaves to the project, so a PR whose own exception is a plain model
        (S54's R: `qa_scenario` -> haiku) read "pr-r (qa_concretize)
        route=…", as if it selected the project's route.  A PR line now
        names only the types its override decides.  The review loop's
        ERROR line put the launch's stderr (RQ40: the route remedy) into
        markup unescaped, like (b): `creds[work]` lost `[work]` on the line
        and in `L`, and a `[/…]` refused the line.  It is escaped now.
        `test_model_show_routes_name_only_the_types_a_pr_override_decides`,
        `test_error_line_shows_the_remedy_as_text_not_markup`; 2 mutations
        caught (`/pm-captures/review-0f64-i1/mutation-checks.log`).  Full
        suite: `/pm-captures/review-0f64-i1/full-suite.log`.
    (f) Review loop 0f64 i2: a PR's Routes line also counted the
        watcher, which is a project session (`pm watcher` resolves it with
        no PR), so `model: provider:<route>` plus one plain-model role
        exception listed "watcher" among that PR's routed types.  PR lines
        now use `model_config.PR_SESSION_TYPES` (every type but the
        watcher); "all types" means all of those.  `validate_model_config`
        reports a PR `session_models` entry for `watcher` ("is not a PR
        session … Set it with 'pm model set watcher <model> --project'"),
        which was accepted and silently did nothing, and the unknown-type
        hint lists only the PR types.
        `test_model_show_pr_routes_never_count_the_project_watcher`,
        `test_pr_watcher_entry_flagged_as_not_a_pr_session`; 2 mutations
        caught (`/pm-captures/review-0f64-i2/mutation-checks.log`).  Full
        suite: `/pm-captures/review-0f64-i2/full-suite.log`.
    (g) Review loop 0f64 i3: (d)'s Routes lines resolved every PR
        override, so a hand-edited non-string PR `model` (`model: 5`, a
        list or a mapping) made `pm model show` crash with
        `AttributeError` (it printed before (d), as on master), and
        `validate_model_config` never reported it.  Such a value selects
        no route line; it is reported as "prs[<pr>].model: … is not a
        model name or 'provider:<name>' (launches that use it fail)".
        Launches still fail on it (pre-existing on master, not guessed
        around: a note on pr-6082c0d).
        `test_model_show_survives_a_non_string_pr_model[3 cases]`,
        `test_pr_non_string_model_flagged`; 2 mutations caught
        (`/pm-captures/review-0f64-i3/mutation-checks.log`).  Full suite:
        `/pm-captures/review-0f64-i3/full-suite.log`.
    (h) Review loop 0f64 i4: (g)'s problem line said "launches that use
        it fail" for every non-string PR `model`, but an empty one (`''`,
        `0`, `[]`, `{}`, `false`) selects nothing at launch
        (`resolve_model_and_provider` skips a falsy PR model), so the
        project settings apply.  Such a value is now reported as "ignored;
        the project settings apply"; a non-empty one (`5`, a list) still
        fails its launches.  `test_pr_empty_model_flagged_as_ignored[5
        cases]` (all fail with the old wording;
        `/pm-captures/review-0f64-i4/mutation-checks.log`).  Full suite
        3735 passed, rc 0 (`/pm-captures/review-0f64-i4/full-suite.log`).
    (i) Review loop 0f64 i5: (b) escaped `run_command`'s output lines but
        not its "> <cmd>" echo of a typed command (pre-existing on
        master), so `pr note add … 'creds[work]'` from the command bar
        showed "creds", and a `[/…]` in it refused the line.  Escaped now.
        `test_typed_command_echo_keeps_brackets` (checked with Textual's
        own markup parser; fails with the fix reverted,
        `/pm-captures/review-0f64-i5/mutation-checks.log`).  Full suite
        3736 passed, rc 0 (`/pm-captures/review-0f64-i5/full-suite.log`).
    (j) Review loop 0f64 i6: (d)'s PR Routes lines ignored `PM_MODEL`,
        which beats every PR override, so with
        `PM_MODEL=provider:<route>` a PR whose override is a plain model
        read "pr-b (all types) route=<route>", as if its override chose
        the route.  With `PM_MODEL` set no PR line is listed; the per-type
        lines already show its route.
        `test_model_show_pr_routes_defer_to_pm_model` (fails with the
        check removed, `/pm-captures/review-0f64-i6/mutation-checks.log`).
        Full suite 3737 passed, rc 0
        (`/pm-captures/review-0f64-i6/full-suite.log`).
    (k) QA S55 (live, container mode): (d) grouped a PR's Routes lines by
        the whole description, effort included, so a project
        `session_effort` (qa_scenario/qa_concretize high, the production
        setup) split a PR routed for every type into two lines, neither
        "all types".  Lines are now grouped by route without the effort;
        efforts that differ are named on the line ("effort=high
        (qa_scenario, qa_concretize), (default) otherwise").
        `test_model_show_pr_route_line_is_not_split_by_project_effort`
        (fails with the old grouping,
        `/pm-captures/scenarios/55/post-fix/tests/mutations.log`).  Full
        suite 3738 passed, rc 0
        (`/pm-captures/scenarios/55/post-fix/tests/full-suite.log`).
        Review loop 6915 i1 (test only): that test stubs `describe`, as
        the older Routes tests do, which is how the split stayed
        invisible to them.
        `test_model_show_pr_route_lines_with_the_real_route_description`
        runs a configured router provider through the real
        `describe` (the production line and S56's W shape: a plain-model
        impl exception with mixed efforts); it fails with the old grouping
        and without the effort summary
        (`/pm-captures/review-6915-i1/mutation-checks.log`).
    (l) QA S58 (live, container mode): `pm model show` built every Routes
        line without container mode, so in container mode it printed
        `via=host` for the project qa_scenario/qa_concretize lines and for
        A's "(all types)" line. Meanwhile the refiner/worker launch lines
        said `via=container-bridge`, and impl/review ran in mounted
        containers (`/pm-captures/scenarios/58/pre-fix`, `story2`). With
        container mode on, the container-run types
        (`worker_route.CONTAINER_SESSION_TYPES`: impl, review, signoff,
        qa_concretize, qa_scenario) now say `via=container-bridge`. The
        other types (qa, planner, s0, verifier, finalizer, merge) say
        `via=host`. A PR's route lines are grouped by route and path, so a
        PR routed for every type shows two lines in container mode. Each
        line names its types and efforts. Host mode is unchanged: one
        "(all types)" line, `via=host`.
        `test_model_show_routes_name_the_container_bridge_in_container_mode`
        and `test_model_show_routes_stay_on_host_outside_container_mode`
        (real describe; 4 mutations caught,
        `/pm-captures/scenarios/58/post-fix/tests/mutations.log`). The
        6915 i1 real-describe test now pins host mode.

### Subagent model enforcement (note-6153fe1, R8)

Fix: `providers.subagent_pin_env(model, provider)`. The router `env_vars()`
adds `CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1`. `build_claude_shell_cmd` and
`_resolve_provider`, which serve `launch_claude`, `launch_claude_print` and
`launch_claude_print_background`, compute the effective model first and add
the pin to the command-scoped env. An inherited pin from the pane's
environment is therefore overridden, and the fake-claude command gets the
same env. Every role launcher (impl, review, merge, sign-off, watcher, all QA
types) and the `pm provider test --live` probe build their command there.

Regressions, all in `tests/test_worker_route.py::TestSubagentPin`:
- host route, container route, `--resume`, explicit model with `[1m]`,
  plain model, no model selected (no pin; an inherited one removed),
  `alias_models` override,
  inherited values overridden, fake-claude env;
- every session type on a PR with `model: provider:claude-work`;
- `launch_claude`/`launch_claude_print` run env;
- the live-probe command.

Mutations caught: no FORCE, 25 failures; pinning the provider model instead
of the effective one, 4; no pin in `_resolve_provider`, 1.

Real Claude Code 2.1.310 child-request evidence:
- Location: `/pm-captures/subagent-pin-249/`, with `README.md`,
  `summary.txt` and the per-run `requests` slices.
- Endpoint: a controlled Anthropic-compatible endpoint standing in for the
  router. It logs each request's model and the account the real router
  picks for it (`work/` → work, else MAIN).
- Commands: built by pm itself, from `git archive HEAD` (ccf0959b, pre-fix)
  and from the working tree (post-fix).
- Environment: `env -i`, so the recovery process's own temporary FORCE never
  reaches a probe, and a dummy `apiKeyHelper` key, so no real credential is
  used.
- Paths: host, a slirp4netns container through pm's real bridge (the
  container cannot reach the endpoint directly), and `--resume`.

| child | pre-fix | post-fix |
|---|---|---|
| default general-purpose | work | work |
| Explore / Plan | work | work |
| custom agent `model: fable` | `claude-fable-5-1` → MAIN | work |
| `Agent(model="fable")` | `claude-fable-5-1` → MAIN | work |
| `Agent(model="fable")`, session `--model work/…[1m]` | `claude-fable-5-1` → MAIN | `work/claude-opus-5-5` + 1M beta |
| `Agent(model="fable")` after `--resume` | `claude-fable-5-1` → MAIN | work |

The container rows match the host rows; the pre-fix container resume was
not run. Post-fix, Claude Code also leaves `model` out of the Agent tool
schema.

Before this change Explore/Plan already stayed on the route, because they
inherit the main conversation's model, which is `work/`.

Live QA on the real work route (twenty-fourth pass, run da5cdfbc6f5e8370;
`/pm-captures/scenarios/59`, `/60`, `/61`, REPORT.md each). A recording
relay in front of the real `claude-work` route forwarded only `work/`
models. Every child of every launch path above requested the session's
`work/` model and got 200 from the work account (one org hash). Fixes
from that run, each with mutation-checked regressions:
- S59, ff65f489: `pm provider test --live` failed "model mismatch" on a
  healthy `[1m]` route; `model_on_route` drops a trailing `[..]` suffix
  (`TestLiveProbe::test_1m_route_model_matches_the_transcript_model`,
  `test_transcript_model_off_the_route_still_fails`).
- S61, 3ee69236: a no-model session inherited the caller's pin
  (`test_no_model_drops_an_inherited_pin`,
  `test_selected_model_is_not_unset`,
  `test_print_launcher_without_model_drops_an_inherited_pin`).
- S61, 79b6ddd7: `ANTHROPIC_DEFAULT_FABLE_MODEL` pinned for routers
  (`TestRouterProvider::test_fable_alias_is_pinned`).
- S60: no product change; qa.md clarifications 0e13c5f8.
Review loop c189 i1 re-checked these three fixes (7 mutations caught,
`/pm-captures/review-c189-i1/mutation-checks.log`) and, on the user's
decision, routed the auto-mode classifier (§2; pr-1071c5a):
`tests/test_worker_route.py::TestClassifierRoute` (7 mutations caught,
`mutation-checks-classifier.log`). Live through the real work route behind
the S59 work/-only relay (`/pm-captures/review-c189-i1/live-classifier/`),
with pm's own built command in auto mode: without the new pin the
classifier requested `claude-sonnet-5` (refused at the relay); with it both
classifier calls requested `work/claude-sonnet-5` and the work account
answered 200 (same org hash as the session), with no unprefixed request.
Review loop c189 i2 limited the pin to routes that serve Claude models
(5f5a1453, §2). Review loop c189 i3 re-checked ff65f489, 3ee69236,
79b6ddd7, f0031965 and 5f5a1453 independently: 10 mutations caught, one
equivalent (`_resolve_provider`'s `if v not in provider_env` filter is
reachable only through an `alias_models` entry naming
`ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN`; defensive, kept)
(`/pm-captures/review-c189-i3/mutation-checks.log`). Claude Code 2.1.310
reads `CLAUDE_CODE_BG_CLASSIFIER_MODEL` nowhere (env allowlists only), so
`CLAUDE_CODE_AUTO_MODE_MODEL` is the only classifier override.
Review loop c189 i4 re-checked the same five fixes with 13 new mutations,
all caught (`/pm-captures/review-c189-i4/mutation-checks.log`). Latest full
suite: 3791 passed, rc 0, on 0b02e164 (env -u PM_HOST_HOME, /usr/bin
first, PYTHONPATH=/workspace, markdown 3.10.3 installed first;
`/pm-captures/review-c189-i4/full-suite.log`; also 3791 in c189 i2 and i3).
Review loop c189 i5 re-checked them with 9 more mutations; three were missed
and are now caught by new assertions in `TestClassifierRoute`: `pm provider
list` names an `alias_models` classifier entry, a `claude`-type provider
with its own `api_base` also drops an inherited classifier pin, and the
`--live` probe command unsets what launches unset (stray keys, another
route's classifier pin) (`/pm-captures/review-c189-i5/mutation-checks.log`).
Latest full suite: 3793 passed, rc 0, on the i5 tree (same env;
`/pm-captures/review-c189-i5/full-suite.log`).
Review loop c189 i6 found that a pm process started inside a routed
session passed that session's aliases and route URL to the sessions it
launched (R9). On the user's decision of 2026-10-26, each launch's
routing environment is now built from pm's selection
(`providers.launch_env`).
- 10 mutations caught (`/pm-captures/review-c189-i6/mutation-checks.log`).
- Live: real Claude 2.1.310 ran pm-built commands under a work-routed
  parent env against local stubs, as a pre-fix (ee82dc0c) vs post-fix
  comparison (`/pm-captures/review-c189-i6/live-inherited/`).
  - Pre-fix, the no-model session and the Fable and haiku switches of a
    plain-model main session all requested `work/claude-opus-5-5` (404
    at the main stub).
  - Post-fix they requested `claude-opus-5-5`, `claude-fable-5-1` and
    `claude-haiku-5-5`.
  - The plain `--model` and the routed launch were unchanged.
- Not run live here: a container (no image in the review container) and
  interactive panes (qa.md twenty-fifth pass).
Review loop c189 i7 re-checked R9 with 10 new mutations. Six were missed and
are now caught by new tests (test only, no product change):
- an openai provider's `alias_models`;
- no marker for a non-router endpoint;
- a claude/local provider at the inherited URL is not a route;
- the marker alone identifies a route, trailing `/` included (a pm process
  in a container has no providers.yaml);
- a router `api_base` with no host does not break launches;
- `launch_env` reads the environment it is given.
See `/pm-captures/review-c189-i7/mutation-checks.log`. Live: this review
ran in a routed review container launched with `PM_ROUTE_BASE_URL`, so the
production launcher runs R9. pm's own no-model build there dropped every
routing variable, and a plain-model build kept only its own pin
(`live-routed-parent-env.txt`).
Full suite 3812 passed, rc 0, run inside a routed review session
(`/pm-captures/review-c189-i7/full-suite.log`).
Review loop c189 i8 found a regression from R9. To recognise an inherited
route URL, `_is_route_base_url` built every providers.yaml entry through
`list_providers`. One hand-edited entry that is not a provider (a null or
string entry, a non-string `api_base`, a list `alias_models`, a list
`providers:` block) then made launches raise `AttributeError`. That hit
every launch that sets no `ANTHROPIC_BASE_URL` of its own (every
main-account role) while an endpoint was inherited, such as a user's proxy,
a QA stub or the host `claude-mixed` env. Those launches built fine before
R9 (`/pm-captures/review-c189-i8/malformed-providers-repro.txt`: HEAD vs
ee82dc0c). Router addresses are now read raw (`_configured_router_urls`),
and an entry that is not a well-formed router is skipped.
`test_malformed_provider_entries_do_not_break_launches[5 cases]` and
`test_router_beside_a_malformed_entry_is_still_recognised`; 8 mutations
caught (`/pm-captures/review-c189-i8/mutation-checks.log`).
Full suite 3818 passed, rc 0 (env -u PM_HOST_HOME, /usr/bin first,
PYTHONPATH=/workspace, markdown 3.10.3 installed first;
`/pm-captures/review-c189-i8/full-suite.log`).
Review loop c189 i9 found i8 sound and closed the matching gap for the
*selected* provider, which was there on master for null and string entries.
A hand-edited entry that is not a provider (a null or string entry, a
non-string field, an unknown `type`, a list `alias_models`) raised
`AttributeError` or `ValueError` from whichever step first touched the
field. That broke the launch (a traceback, or "QA thread crashed" for
planner/s0/verifier/finalizer), the refiner/worker route gate
(`check_route` itself raised, so the QA thread died instead of waiting with
a remedy), `pm model show` and `pm provider list`.
- `get_provider` now raises `ProviderEntryError` for such an entry. It is a
  `ProviderNotFoundError` naming the file and the field, raised strict or
  not, and never falls back to plain claude.
- Every launch surface therefore reports it as it reports a missing
  provider: one `Error:` line, the route gate's wait with its remedy (the
  launch goes ahead once the entry is fixed), and `QA stopped: …`.
- `describe` (and so `pm model show`) says `(INVALID ENTRY in
  providers.yaml)`. `pm provider list` lists such entries as
  `INVALID ENTRY: <problem>` beside the valid ones.
- A blank field reads as unset, as an absent key does. A providers.yaml
  that is not a mapping is ignored like one that does not parse.
See `/pm-captures/review-c189-i9/invalid-selected-entry-repro.txt` (4847ac05
vs fix). Tests: `test_invalid_selected_entry_is_reported_like_a_missing_provider[6 cases]`,
`test_invalid_selected_entry_is_a_clean_cli_error`,
`test_provider_list_and_test_name_an_invalid_entry`,
`test_valid_entries_with_null_fields_still_load` and
`test_non_mapping_providers_file_is_ignored[2]`. 11 mutations caught
(`/pm-captures/review-c189-i9/mutation-checks.log`).
Full suite 3829 passed, rc 0 (env -u PM_HOST_HOME, /usr/bin first,
PYTHONPATH=/workspace, markdown 3.10.3 installed first;
`/pm-captures/review-c189-i9/full-suite.log`).
Review loop c189 i10 found i9's selected-entry handling sound and fixed
the provider CLI it points users to:
- Since i9 a blank `providers:` block (every entry commented out) reads as
  no providers, so a launch says "add it with 'pm provider add …'".
  `pm provider add`, `remove` and `default` still indexed the block and
  raised `TypeError`, so that remedy crashed.
- i9 also reads a providers.yaml that is not a mapping as empty, so
  `pm provider add` silently replaced such a file. Before i9 it crashed
  before writing. A file that is not valid YAML was replaced too, which
  was already the case on master.
- The three edit commands now load through
  `providers.load_providers_for_edit`. A blank block reads as empty. A
  file pm cannot read (not valid YAML, not a mapping, a `providers` block
  that is not a mapping) gets one `Error: <path> cannot be changed: …`
  line, rc 1, and is left unchanged. `add` refuses before its endpoint
  check and confirm prompt.
- `capabilities` is now validated like the other fields: a list of names.
  `pm provider list` joined it raw, so `capabilities: 5` crashed the
  listing that i9 made name invalid entries (pre-existing on master).
See `/pm-captures/review-c189-i10/providers-file-cli-repro-{before,after}.txt`
(4847ac05 and HEAD vs fix). Tests: `test_provider_edits_fill_a_blank_providers_block`,
`test_provider_edits_leave_an_unreadable_file_alone[3]`, plus an
`int_capabilities` case in the i9 tests. 8 mutations caught
(`/pm-captures/review-c189-i10/mutation-checks.log`).
Latest full suite: 3834 passed, rc 0 (env -u PM_HOST_HOME, /usr/bin first,
PYTHONPATH=/workspace, markdown 3.10.3 installed first;
`/pm-captures/review-c189-i10/full-suite.log`).
