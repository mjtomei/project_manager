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
(`…195845Z/result.json`). Live QA S1–S39 is in
`/pm-captures/scenarios/<N>/` (REPORT.md). The latest full suite is
recorded with item 29.

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
        (c8ab2f4c).
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
    Regressions in `tests/test_qa_resume.py` (each fails with its fix
    reverted): `test_resume_of_a_pulled_pr_reloads_the_tree`,
    `test_resumed_run_is_driven_in_the_session_that_holds_its_windows`,
    `test_unparseable_project_file_does_not_escape_the_scan`,
    `test_scan_does_not_adopt_a_run_another_tui_claimed_after_the_check`,
    `test_two_processes_claiming_one_orphan_get_exactly_one_owner`.
    Full suite 3549 passed on the d809b358 tree (code-identical to ec227cf0 after the rebase onto ee423ea9) (env -u PM_HOST_HOME,
    /usr/bin first; `/pm-captures/scenarios/41/tests/full-suite.log`).
    Evidence: `/pm-captures/scenarios/41` (REPORT.md).
