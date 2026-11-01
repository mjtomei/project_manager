# Spec: centralize fail-closed container launches across all session types (pr-cd04629)

Follow-up to #280 / pr-574e851, requested by the user after its sign-off
discussion on 2026-11-01.  #280 made the **QA run** fail closed when
container mode is enabled and the runtime is unusable.  It did not audit
the other session types or the alternate entry points of the two roles it
touched, and it left the container-create/wrap primitive
(`wrap_claude_cmd`) as a per-caller convention rather than a boundary.

This PR owns the **launch invariant**:

> Once an operation requires a container, no runtime/preflight/create/
> setup/reuse/exec/tmux failure and no absent tmux session may select a
> host agent launch.  Explicitly disabled container mode is the only
> intentional host path for a container-eligible role.

It also owns the two confirmed downgrades on the implementation path
(#280's original sign-off checked creation failure and missed these).
Broader containerization of currently host-only roles stays in
pr-efab0ce; those paths must consume this boundary, not grow their own
fallbacks.

## Scheduling status (this session)

**Audit and interface documentation only.**  The user authorized the
audit now and asked that overlapping product/lifecycle implementation
wait until:

- #241 / **pr-1139060** (container cleanup ownership) merges and is
  integrated, and
- #278 / **pr-073910f** (per-session tmux server isolation) merges and is
  integrated.

At the time of writing both are `status: pending` in `pm/project.yaml`
(pr-1139060 at `pm/project.yaml:12344`, pr-073910f at `:4382`).  This
session therefore records the matrix, the interface and the integration
assumptions, commits them, and leaves a PR-note handoff.  No product code
from this spec is implemented until the scheduling watcher releases it.

## Confirmed downgrade paths (grounded, current base `81e5d7f4`)

### D1 — `pm pr start`: window failure after container allocation falls through to the host

`pm_core/cli/pr.py:1187-1267` (`pr_start`):

```python
if pm_session:                                  # 1188
    if tmux_mod.session_exists(pm_session):     # 1189
        ...
        cmd, _cname = wrap_claude_cmd(...)      # 1221-1230  (container created)
        try:
            tmux_mod.new_window(...)            # 1232-1247
            return
        except Exception as e:                  # 1254
            click.echo(f"Failed to create tmux window: {e}", err=True)
            click.echo("Launching Claude in current terminal...")
# Fall through: launch interactively in current terminal
launch_claude(...)                              # 1265  (HOST agent)
```

`wrap_claude_cmd` has already created (or reused) the container.  A tmux
window-creation failure then runs the impl agent **on the host** and
leaves the allocated container unused (until some later cleanup).  The
printed message actively claims a host launch is happening.

### D2 — `pm pr start` outside a PM tmux session skips the container path entirely

Same function.  When `pm_session` is `None` (no tmux binary) or
`tmux_mod.session_exists(pm_session)` is `False` (tmux up, but no session
for this project), the whole `if` block — including the
`is_container_mode_enabled()` decision and `wrap_claude_cmd` — is skipped
and control reaches `launch_claude(...)` at `cli/pr.py:1265` directly.
Container mode is enabled, yet the impl agent runs on the host.  This is
the second confirmed case in the PR description.

### D3 — Review: window failure after allocation leaks the container

`pm_core/cli/pr.py:1353-1650` (`_launch_review_window`).  It refuses
cleanly with no container when tmux is absent (`:1363`) and when the
session is missing (`:1365-1367`) — both **before** `wrap_claude_cmd`
(`:1476`).  But `wrap_claude_cmd` runs at `:1476`, and the diff pane
creation at `:1541` returns `None` → `:1555` prints "failed to create
tmux window" and returns, leaving the just-created container running.  No
host fallback (good), but the allocation is leaked and the user is not
told the container was reclaimed.

### D4 — Sign-off: window failure after allocation leaks the container

`pm_core/signoff.py:401-597` (`launch_signoff_window`).  It refuses with
no container when tmux is absent (`:425`) or the session is missing
(`:430-432`).  `wrap_claude_cmd` runs at `:539`; `new_window_get_pane`
returning `None` at `:557` prints `"Sign-off window: failed to create
tmux window"` (`:559`) and returns, leaving the container running.  The
outer `except Exception` (`:583-585`) has the same leak.

### D5 — The create/wrap primitive reports no allocation ownership

`pm_core/container.py:720-1139` (`create_container`) reuses a running
container by name (`:759-783`) or creates one; both return only the
container id.  `wrap_claude_cmd` (`:1235-1382`) likewise returns only
`(cmd, name)`.  Callers therefore cannot tell "I allocated this" from "I
reused a live session's container", so a safe reclaim-on-failure rule
cannot be written at the call sites.  This is why D3/D4 leak (and why a
naive "remove on failure" would be dangerous).

### D6 — Policy selection is scattered and sometimes conjunctive

- `pm_core/cli/pr.py:1195-1201` and `:1436-1444` decide the container
  cwd from `is_container_mode_enabled()` directly.
- `pm_core/signoff.py:507-519` and `:533` do the same.
- `pm_core/qa_loop.py:3600-3682` (`_build_scenario_run_cmd`) decides
  container-vs-host from `bool(scenario.container_name)`, not from the
  run's policy.
- `pm_core/qa_loop.py:5600-5619` re-derives the mode + runtime preflight
  locally; `pm_core/cli/qa.py:502-508` does it again for `pm qa debug`.
- The historical `is_container_mode_enabled() and _runtime_available()`
  conjunctions (#280 P2/P3) were the direct cause of silent downgrades;
  #280 removed them in QA, but nothing prevents a future caller from
  writing another one.

### Already fail-closed after #280 (verify, do not regress)

- QA run preflight: `qa_loop.py:5596-5619` → `_fail_run_infrastructure`.
- Container create/setup failure → `ContainerLaunchError`:
  `qa_loop.py:3327-3351` and `_execute_and_finalize` handling.
- Relaunch with no/lost container → `ContainerLaunchError`:
  `qa_loop.py:3745-3854` + `_ensure_scenario_container` (`:3684-3743`).
- Resume with a container snapshot and a dead runtime: `_resume_qa_sync`
  preflight.
- `pm qa debug` preflight + create + window-failure reclaim:
  `cli/qa.py:502-508`, `:594-627`, `:650-687`.
- `wrap_claude_cmd` raises `ContainerError` on create failure
  (`container.py:1330-1356`).

## Complete caller / session matrix

Legend: **C-eligible** = the role is containerized today in container
mode.  **Host-only** = the role never consults container mode and runs a
host agent; it is not a downgrade today, and its containerization is
pr-efab0ce's scope.  Line numbers are on base `81e5d7f4`.

### A. Container-eligible roles (this PR owns their launch invariant)

| Role | Session type | Entry points (actual calls) | Current container path | Defect |
|---|---|---|---|---|
| Implementation | `impl` | `pm pr start` → `cli/pr.py:891`; TUI `s`/`S` → `tui/pr_view.py:79` → wrapper subprocess → `pm pr start`; auto-start `tui/auto_start.py:1774` → `pm pr start --background` | `wrap_claude_cmd` at `cli/pr.py:1221` inside the tmux block | **D1** window failure → host `launch_claude`; **D2** no PM session → host; **D5** no reclaim |
| Review | `review` | `pm pr review` → `cli/pr.py:1618`; `_launch_review_window` `:1353`; TUI `d`; review loop; auto-start | `wrap_claude_cmd` at `:1476` | **D3** leak on window failure; **D6** cwd policy scattered |
| Sign-off | `signoff` | `pm pr signoff` → `cli/pr.py:1794`; `launch_signoff_window` `signoff.py:401`; TUI `signoff_ui.py:207`; auto-sequence | `wrap_claude_cmd` at `signoff.py:539` | **D4** leak on window failure |
| QA refiner / concretizer | `qa_concretize` | `_launch_scenarios_in_containers` `qa_loop.py:3210`; `_launch_scenarios_in_tmux` `:2977` (host control) | `create_qa_container` `:3329` + `_build_concretize_cmd` `:2591` → `build_exec_cmd` `:2638` | **D6** policy from `bool(container_name)`; create/failure handling is local |
| QA worker / scenario | `qa_scenario` | `_launch_scenarios_in_containers` `:3210`; relaunch `_relaunch_scenario_window` `:3745`; `_build_scenario_run_cmd` `:3600` | `create_qa_container` `:3329`/`:3719` + `build_exec_cmd` `:3672` | **D6** policy from `bool(container_name)`; `_ensure_scenario_container` duplicates start/reuse |
| QA debug (execution-only) | `qa_author` | `pm qa debug` → `cli/qa.py:464` | `create_qa_container` `:594` + `build_exec_cmd` `:634` | already fail-closed; route through the shared boundary for consistency |

`CONTAINER_SESSION_TYPES` (`pm_core/router_route.py:76`) is the existing
declaration of this set: `("impl", "review", "signoff", "qa_concretize",
"qa_scenario")`.  The new policy module should consume it rather than
re-declare it, and `qa_interactive` (scenario 0) must stay outside it.

### B. Host-only roles (not downgrades; document + pr-efab0ce)

| Role | Session type | Entry point | Why host-only today |
|---|---|---|---|
| QA planning | `qa_planning` | `qa_loop.py:5644-5652` (`build_claude_shell_cmd` in the QA window) | Planner reads/commits the repo; never wrapped (parent spec §Out of scope) |
| QA Scenario 0 | `qa_scenario` (fake) / `qa_interactive` (model) | `_launch_scenario_0` `qa_loop.py:2738-2820`, comment `:2779-2781` | Deliberate: full host tools/credentials for the user |
| QA verification | `qa_verification` | `_verify_single_scenario` `qa_loop.py:5145`, cmd at `:5256` | Runs in the PR workdir; never wrapped |
| QA finalization | `qa_finalize` | `_run_qa_finalize_pane` `qa_loop.py:843`, cmd at `:920` | Runs in the PR workdir; never wrapped |
| Merge / repo update | `merge` | `_launch_merge_window` `cli/pr.py:2073-2175` | Updates the main checkout; branch-scoped push proxy does not fit |
| Plan authoring/review/deps | `plan` | `cli/plan.py:158,267,475,584,756,914` | Interactive host session on the plan file |
| Guide | `guide` | `cli/guide.py:101,146` | Interactive host session |
| Cluster explore | `cluster` | `cli/cluster.py:224`; bridge `:207` | Host-side bridge/daemon by design |
| Watcher / discovery / bug-fix-impl / improvement-fix-impl | `watcher`, … | `cli/watcher.py:377-419`; `watcher_base.py:142-155`; `build_launch_cmd` per type | Monitors host panes/state |
| TUI discuss / claude / watcher-review / qa-item | `discuss`, `watcher_review`, `qa_author`, `qa_regression` | `tui/pane_ops.py:347,396,461,515` | TUI-hosted helper panes |
| QA authoring / regression | `qa_author`, `qa_regression` | `cli/qa.py:246,351`; `pm qa launch` `:694` | Authoring helpers |
| Spec generation | (none) | `spec_gen.py:304` (`launch_claude_print`) | One-shot host print |
| Plan review (background) | (none) | `plans/review.py:170` (`launch_claude_print_background`) | One-shot host print |
| Mock generation | (none) | `qa_loop.py:2361` (`launch_claude_print`) | One-shot host print |
| Container image build helper | `container` | `cli/container.py:188` (`launch_claude`) | Builds the image on the host |

Host **services** (no agent): push proxy (`push_proxy.py`), route bridge
(`route_bridge.py`), tmux/pane management, git ops, cleanup
(`pr_cleanup.py`).  These stay on the host and are not launch paths.

### C. Alternate / lifecycle entry points that reuse A

- **Retry/relaunch**: `_poll_tmux_verdicts` → `_relaunch_scenario_window`
  (`qa_loop.py:4365` `_launch_next_queued`, `:3745`).
- **Resume/restart**: `resume_qa_sync` / `_resume_qa_sync`
  (`qa_loop.py:6440/6463`), TUI resume, `qa_resume.json`.
- **Replacement windows**: review `--fresh`, sign-off `--fresh`,
  watcher recreate (`cli/watcher.py:392-405`), QA stale-window cleanup.
- **Nested helpers**: `_ensure_scenario_container`, `_split_worker_pane`,
  `_concretize_and_launch`, `_add_companion_pane` (shell only, no agent).
- **Background/print**: `launch_claude_print`,
  `launch_claude_print_background` (host-only roles above).
- **Foreground/no-tmux**: `pr_start` `launch_claude` (D2);
  `pm qa debug --foreground` (`cli/qa.py:650`, already containerized).

## Requirements

### R1 — One execution-policy resolver

Add `pm_core/launch.py` (new module; `container.py` stays the low-level
runtime/mount layer):

```python
class LaunchRole(str, Enum):
    # container-eligible (must match router_route.CONTAINER_SESSION_TYPES)
    IMPL = "impl"; REVIEW = "review"; SIGNOFF = "signoff"
    QA_CONCRETIZE = "qa_concretize"; QA_SCENARIO = "qa_scenario"
    # host-only by design (documented; pr-efab0ce owns containerization)
    QA_PLANNING = "qa_planning"; QA_INTERACTIVE = "qa_interactive"
    QA_VERIFICATION = "qa_verification"; QA_FINALIZE = "qa_finalize"
    MERGE = "merge"; PLAN = "plan"; GUIDE = "guide"; CLUSTER = "cluster"
    WATCHER = "watcher"; DISCUSS = "discuss"; QA_AUTHOR = "qa_author"
    QA_REGRESSION = "qa_regression"; SPEC = "spec"; CONTAINER_BUILD = "container"

CONTAINER_ELIGIBLE_ROLES = frozenset({
    LaunchRole.IMPL, LaunchRole.REVIEW, LaunchRole.SIGNOFF,
    LaunchRole.QA_CONCRETIZE, LaunchRole.QA_SCENARIO,
})
HOST_ONLY_ROLES = frozenset(LaunchRole) - CONTAINER_ELIGIBLE_ROLES

@dataclass(frozen=True)
class ExecutionPolicy:
    role: LaunchRole
    mode: str      # "container" | "host"
    reason: str    # "container-mode-enabled" | "container-mode-disabled"
                   # | "role-host-only"

def execution_policy(role: LaunchRole) -> ExecutionPolicy:
    """The only place a container/host decision is made.

    Container-eligible role + container mode enabled -> container.
    Container-eligible role + disabled            -> host (explicit).
    Host-only role                                -> host (role-host-only),
        regardless of the container setting: this is not a downgrade.
    """
```

No runtime probe participates in this decision.  A missing runtime makes
a **container** policy fail at start (R2), never flip to host.

### R2 — One required-container launch path

```python
@dataclass
class LaunchCommand:
    command: str                 # shell string for tmux/foreground
    container_name: str          # "" for an intentional host launch
    policy: ExecutionPolicy
    newly_created: bool          # this launch allocated the container
    exec_started: bool = False   # set when the command is handed to a pane/exec

    def mark_exec_started(self) -> None: ...
    def release_unused(self) -> None:
        """Remove the container only when newly_created and not exec_started.
        Reused/retained containers, workdirs, scratch, captures, dirty files
        and drafts are never touched."""

def required_container_launch(
    *, role: LaunchRole, claude_cmd: str, workdir: str, label: str,
    extra_ro_mounts=None, extra_rw_mounts=None, allowed_push_branch=None,
    session_tag=None, pr_id=None, provider=None, env=None,
    cleanup: bool = True,
) -> LaunchCommand:
    """Start/reuse the container and return the exec command.

    Host-only role -> raises ProgrammingError (callers must use
    host_launch()).
    Container policy -> container_preflight_error() first (raises
    ContainerError with container_unavailable_message); then
    ensure_container(); then build_exec_cmd().  Every failure raises
    ContainerError with the cause and container_retry_remedy, after
    releasing only this attempt's newly created container.
    """
```

`ensure_container()` is a new `container.py` helper that returns
`(container_id, reused: bool)` and is what `create_container` delegates
to (D5).  `wrap_claude_cmd` is kept as a thin compatibility shim that
calls `required_container_launch` and returns `(command, name)`;
`pr_start`, review and sign-off switch to the richer `LaunchCommand` so
they can reclaim on failure.

### R3 — Implementation launch (D1 + D2)

`pr_start` resolves `policy = execution_policy(LaunchRole.IMPL)` once,
before the tmux block, and uses `policy.mode` for the container cwd
(replacing `is_container_mode_enabled()` at `cli/pr.py:1195`).

- `policy.mode == "container"`:
  - tmux available **and** window creation succeeds → unchanged.
  - tmux unavailable, session missing, or window creation fails →
    **containerized foreground launch**: run the `LaunchCommand.command`
    (which is `build_exec_cmd(..., cleanup=True)`) via
    `subprocess.run(["bash", "-c", cmd], cwd=workdir, env=...)` when
    `sys.stdin.isatty()`.  Mark exec started, return its rc.
  - no TTY (e.g. launched from a non-interactive context) →
    `launch_command.release_unused()` if newly created, then raise
    `ContainerError` with an actionable message: an interactive
    container session needs a TTY; use the TUI/tmux, or deliberately
    `pm container disable`.  **Never** print "Launching Claude in current
    terminal" and **never** call `launch_claude`.
- `policy.mode == "host"` (container mode disabled): keep the existing
  `launch_claude` foreground fallback and message, but phrase it as an
  explicit host launch ("Container mode is disabled; launching on the
  host").

### R4 — Review and sign-off failure handling (D3 + D4)

Both use `LaunchCommand` and call `release_unused()` before reporting a
failed window, so a newly allocated container is reclaimed and a reused
one is preserved.  The refusal messages (no tmux / no session, already
before allocation) stay, and gain a one-line note that no agent ran.  No
host fallback is introduced.

### R5 — Route the QA container-eligible callers through R2

`_launch_scenarios_in_containers`, `_ensure_scenario_container`,
`_build_scenario_run_cmd` / `_build_concretize_cmd` and `pm qa debug`
call `required_container_launch` (or a QA-specialised wrapper that adds
the scratch mount and route mounts) instead of open-coding
`create_qa_container` + `build_exec_cmd`.  The run's `use_containers`
(the requested mode) is the policy input; `bool(scenario.container_name)`
is demoted to an invariant check (a container run must have a name, else
`ContainerLaunchError`) rather than a mode decision.  Existing fail-closed
behaviour (#280) is preserved; only the plumbing moves.

### R6 — Guard against future bypasses

Host execution primitives (`launch_claude`, `launch_claude_print`,
`launch_claude_print_background`, `launch_claude_in_tmux`) call
`assert_host_execution_allowed(role_or_session_type)` first: when the
role is container-eligible and `is_container_mode_enabled()`, they raise
`HostLaunchRefused(ContainerError)` with the remedy.  Host-only roles and
disabled mode are unaffected.  Scenario 0 uses `build_claude_shell_cmd`
directly (host by design) and is unaffected; if it is later routed
through a primitive it must pass `LaunchRole.QA_INTERACTIVE`.

A structural test additionally asserts that every container-eligible
launch entry point (impl, review, sign-off, QA refiner/worker, QA debug)
imports and calls `required_container_launch` / `execution_policy`, so a
future caller cannot silently reintroduce a direct host launch.

### R7 — Cleanup ownership and evidence preservation

- Reclaim only a container this launch **newly created** and **never
  exec'd**.
- Never call broad cleanup (`cleanup_qa_containers`,
  `cleanup_*_containers`, `tmux kill-*`) on a failure path.
- Preserve workdirs, clones, scratch, captures, prompts, dirty files,
  drafts and diagnostic output.  Reused/retained containers are never
  removed.
- The existing QA exact-name reclaim (`qa_loop.py:3337-3345`) and
  `pm qa debug` reclaim (`cli/qa.py:607-612`, `:664-668`) keep their
  semantics through the shared helper.

### R8 — Preserve routing, prompts, gates, verdicts

Model/provider resolution, `env_out` transport, prompt files,
`session_type` (fake-claude/route placement), the QA gates
(PASS verification, finalize gate) and verdict collection are unchanged.
`required_container_launch` passes `provider`/`env` through to the same
`wrap_claude_cmd` internals (router mount check, prompt-path rewrite,
shared push-proxy keying) so no route can lose its bridge mount.

## Proposed interface — integration assumptions

1. **pr-1139060 (#241)** owns container lifecycle/cleanup.  This PR must
   not invent a parallel reaper: `release_unused()` is a narrow,
   caller-owned `remove_container(name)` for one exact, never-exec'd
   allocation.  If #241 changes `create_container`/`remove_container`
   signatures or adds a lifecycle registry, `ensure_container` and
   `release_unused` adapt to it rather than duplicating it.
2. **pr-073910f (#278)** owns per-session tmux servers.  The shared
   boundary takes a resolved `session` name and calls the existing
   `tmux_mod` helpers; it must not hard-code the default socket.  The
   no-tmux detection uses the same `has_tmux()/session_exists()` the
   entry points already use, so the per-session socket change is
   transparent.
3. **pr-efab0ce** consumes `execution_policy` + `required_container_launch`
   for every newly containerized role.  It adds roles to
   `CONTAINER_ELIGIBLE_ROLES` (and removes them from `HOST_ONLY_ROLES`)
   in one place; it must not add a per-role fallback.
4. **pr-6820cbc** owns the shared route-bridge / push-proxy lifecycle.
   `required_container_launch` keeps calling `router_route.container_mounts`
   and `push_proxy.get_proxy_socket_path` exactly as `wrap_claude_cmd`
   does today; no competing lifecycle is introduced.

## Implicit requirements

1. **Policy must not be re-derived after the fact.**  Every caller in A
   resolves `execution_policy` once and threads the result; a later
   `is_container_mode_enabled()` check must not be able to disagree.
2. **The container cwd/write_dir split must follow the policy**, not a
   second setting read (`cli/pr.py:1195`, `:1436`, `signoff.py:510`).
3. **No invented verdicts.**  A container failure on a QA path must keep
   surfacing as infrastructure `ERROR`/`ContainerLaunchError`, never
   `INPUT_REQUIRED` (already fixed by #280; the refactor must not regress
   the raise-before-aggregation ordering).
4. **No settings mutation.**  Nothing in this PR writes
   `container-enabled`; tests isolate `HOME` so a scratch project cannot
   touch the real global setting.
5. **Host-only roles stay explicitly host-only**, with their
   containerization follow-up named (pr-efab0ce) — not silently described
   as isolated.
6. **`session_type` and `LaunchRole` are distinct.**  `session_type`
   drives fake-claude/route placement; `LaunchRole` drives policy.
   Scenario 0 keeps `session_type="qa_scenario"` for fake compatibility
   while being `QA_INTERACTIVE` for policy.

## Ambiguities and resolutions

- **[RESOLVED] Foreground containerized launch vs refusal (D1/D2).**  Use
  the containerized foreground command when a TTY exists (preserves the
  current outside-tmux UX without a host agent); refuse with an
  actionable error otherwise.  The task allows either; this is the one
  that keeps `pm pr start` usable from a plain shell.
- **[RESOLVED] Reclaim on failure.**  Only a newly created, never-exec'd
  container is removed.  A reused container belongs to a live session and
  is preserved.
- **[RESOLVED] Host-only roles.**  Planner, scenario 0, verifier,
  finalizer, merge, plan/guide/cluster/watcher/authoring/print helpers
  stay host-only; pr-efab0ce owns their containerization.  They are not
  downgrade paths because they never select container mode.
- **[RESOLVED] Guard mechanism.**  Runtime guard on the host primitives
  plus a structural test; no signature churn across the many host-only
  call sites.
- **[RESOLVED] QA policy source.**  The run's persisted `use_containers`
  is the policy input; `scenario.container_name` is an invariant, not a
  mode.

No **[UNRESOLVED]** ambiguities.

## Edge cases

| Situation | Expected |
|---|---|
| impl, container mode on, no tmux binary | containerized foreground (TTY) or actionable refusal; no host claude |
| impl, container mode on, tmux up but no project session | same as above |
| impl, container mode on, window creation fails after create | foreground container exec (TTY) or reclaim + refusal; no host claude, no "Launching Claude in current terminal" |
| impl, container mode on, window fails after **reuse** | container preserved; foreground/refusal per TTY |
| impl, container mode on, create fails | `ContainerError` with cause + remedy; nothing launched; no host claude |
| impl, container mode **off** | host `launch_claude` fallback unchanged, message says container mode is disabled |
| review/signoff, container mode on, no tmux/session | refuse before allocation; no container, no host claude |
| review/signoff, container mode on, window fails after create | reclaim newly created container, report; no host claude |
| review/signoff, container mode on, window fails after reuse | container preserved, report; no host claude |
| QA refiner/worker, runtime down | `ContainerLaunchError` → run ERROR (unchanged) |
| QA worker dies, container running | relaunch in same container (unchanged) |
| QA worker dies, container gone | recreate same name; failure → `ContainerLaunchError` (unchanged) |
| QA resume, snapshot container + runtime down | ERROR, no host (unchanged) |
| QA debug, runtime down | exit 1 with remedy (unchanged) |
| host-only role, container mode on | host launch unchanged (documented; pr-efab0ce) |
| any container-eligible role reaching a host primitive with mode on | `HostLaunchRefused` |
| `pm container status` / `enable` with runtime down | unchanged |

## Test plan (parameterized, `tests/test_launch_policy.py` + additions)

Matrix dimensions: `role ∈ {impl, review, signoff, qa_concretize,
qa_scenario}`, `condition ∈ {runtime missing, info nonzero, info timeout,
create failure, setup timeout, reuse running, exec failure, tmux window
failure after allocation, no PM session, relaunch/retry, resume}`.

For each cell assert:
1. **Zero host agent invocations** — spy on `launch_claude`,
   `launch_claude_print`, `launch_claude_print_background`,
   `launch_claude_in_tmux`, and on the raw `subprocess.run`/`os.execvpe`
   argv, asserting no argv contains the host `claude` binary.  (Do not
   assert only on an error string.)
2. The container path was selected when mode is on (create/exec called),
   or an actionable `ContainerError` was raised.
3. **Controls**: healthy runtime → container used; global disabled → host
   path used intentionally (and the message says so).
4. **Cleanup ownership**: newly created → removed exactly once on
   failure; reused → not removed; workdir/scratch/captures untouched.
5. **Guard**: `launch_claude(session_type="impl")` with mode on raises
   `HostLaunchRefused`; a structural test asserts each A-role entry point
   calls `execution_policy`/`required_container_launch`.

Reuse `tests/test_container_fail_closed.py` for the QA cells already
covered; add impl/review/sign-off cells and the policy/guard units.
Tests must isolate `HOME`/`CLAUDE_CONFIG_DIR`, use a fake runtime and a
fake `claude` on `PATH`, and never touch live host tmux or the real
container setting.

## Manual verification plan

Real isolated launches (not mocks) are feasible here: nested podman
3.4.4 is present and `container._runtime_status()` answers OK.  If the
`pm-dev:latest` image cannot be built in the impl container, fall back to
the scratch-`HOME` + fake-runtime repro and say so in the manifest.

1. Scratch `HOME`, scratch project, private tmux socket (never the live
   pm session), fake/real `claude` marker log at `$SCRATCH/host-launch.log`.
2. Pre-fix: `pm pr start` (a) outside tmux and (b) with window creation
   forced to fail → marker records a host launch (D2/D1).
3. Post-fix: same commands → a container is created and `podman exec`
   runs the agent, or an actionable refusal is printed; marker is empty;
   `podman ps` shows the expected container; on window failure the newly
   created container is gone and a reused one survives.
4. Verify the host PM state, tmux sessions and
   `~/.pm/settings/container-enabled` are unchanged.
5. Record with the `pm/qa/artifacts/cli-recording.md` recipe under
   `$CAP/impl/{pre,post}-fix/`.

## Implementation plan (gated on scheduling)

1. `pm_core/launch.py`: `LaunchRole`, `CONTAINER_ELIGIBLE_ROLES`,
   `HOST_ONLY_ROLES`, `ExecutionPolicy`, `execution_policy`,
   `LaunchCommand`, `required_container_launch`,
   `assert_host_execution_allowed`, `HostLaunchRefused`.
2. `pm_core/container.py`: `ensure_container() -> (id, reused)`;
   `create_container` delegates; `wrap_claude_cmd` becomes a shim.
3. `pm_core/cli/pr.py`: R3 impl (policy once, containerized foreground /
   refusal, reclaim), R4 review.
4. `pm_core/signoff.py`: R4.
5. `pm_core/qa_loop.py` + `pm_core/cli/qa.py`: R5 routing.
6. R6 guard on `claude_launcher` primitives + structural test.
7. Tests + manual captures.

## Audit handoff (what this session leaves)

- This matrix and design, committed on the PR branch.
- The four defects D1–D5 with file:line evidence.
- The interface and the four coordination assumptions.
- No product code changed; implementation waits for #241/#278.
