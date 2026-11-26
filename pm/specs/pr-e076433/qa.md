# pr-e076433 — QA spec: role-neutral model routing names and docs

Follow-up 1 from `followups-pr-592e4bd.md` (item 1).  Routing already worked
for every role; this PR renames `pm_core/worker_route.py` to
`pm_core/router_route.py`, renames the placement constant
`ROUTED_SESSION_TYPES` to `SCENARIO_CONTAINER_TYPES`, makes the diagnostics
and documentation say "role" instead of "QA worker", and extracts the
legacy Scenario-0 `qa_scenario` shim into a documented, tested helper.
No configured route, provider, account or effort may change.

The user-visible surfaces are: `pm model show`, `pm model set`,
`pm pr model show` / `pm pr model set`, `pm provider show` /
`pm provider test`, the TUI model popup (`o`) and the README examples.
Everything the rename touched (`model_settings`, `cli/model`,
`cli/provider`, `tui/model_screen`, `container`, `claude_launcher`,
`providers`, `qa_loop`) is reached from those surfaces, so a broken import
or a stale constant use shows up as a command failing or a route being
described/mounted wrongly.

## Setup

Cross-cutting; each requirement's Given assumes this unless stated.

- `python3 -m venv` + `pip install -e .` from the clone, and
  `PYTHONPATH` pointing at the clone so `pm which` prints it (the QA
  container otherwise shadows it with `/opt/pm-src`).  See
  `tui-manual-test.md`.
- A throwaway project: `pm init --backend local --no-import`, a few PRs
  added with `pm pr add` (note the generated ids).
- A router provider defined on the host, e.g.
  `pm provider add my-router --type router --api-base http://127.0.0.1:<port> --model <model>`
  (and a second one for the "one role, two routes" checks).  A stub HTTP
  server on that port can stand in for the router for live probes; a router
  that is down must still be describable and must fail closed.
- `~/.pm/settings` global model/effort files only where a requirement names
  a global setting; the harness's own `PM_MODEL` / `PM_EFFORT` must be
  cleared so they do not mask project settings.
- Container-mode requirements additionally enable container mode through
  the surface (`pm container enable`) and, in the QA container, opt the
  throwaway project into `nested_podman: true` as described in
  `tui-manual-test.md`.

## Requirements

### R1 — Any role can be routed, explicitly and independently
- **G1** Given a project with a configured router provider and no model
  settings, When the user routes `impl` to it project-wide, Then
  `pm model show` lists `impl` on that provider while every other role
  still shows `(default)`.
- **G2** Given `impl` is routed, When the user also routes `signoff` to
  the same provider, Then both are listed independently and no other role
  moves.
- **G3** Given a role inherits from a parent (`qa_scenario` -> `qa`,
  `signoff` -> `review`), When the parent is routed, Then the child role
  resolves to the same provider, and `pm model show` says so.
- **G4** Given a project with no model configuration at all, When the
  user runs `pm model show`, Then every role reads `(default)` and no
  Routes section is printed (plain Claude on the CLI default).
- **G5** Given the README's example block, When the user runs each
  `pm model set …` line against the throwaway project, Then every
  command succeeds (including the non-QA `impl` / `signoff` examples and
  a plain model value) and `pm model show` reflects each.

### R2 — `pm model show` describes routes role-neutrally and correctly
- **G6** Given several routed roles, When the user runs `pm model show`,
  Then the route section is labelled role-neutrally (a "routes" heading
  that says the roles are set to a provider, not "worker routes"), and
  one line per routed role names the role, the route, the model and the
  effort.
- **G7** Given a PR whose model override selects a provider, When the
  user runs `pm model show`, Then that PR gets its own route line naming
  the types the override decides (not the project watcher), and a
  plain-model PR override does not appear as a route.
- **G8** Given `PM_MODEL` selects a provider, When the user runs
  `pm model show`, Then the env selection wins and no PR override line
  claims the route.
- **G9** Given a role is set to `provider:<name>` but that provider is
  not configured (or its entry is invalid), When the user runs
  `pm model show`, Then the route line says so (`NOT CONFIGURED` /
  `INVALID ENTRY`) and the command still exits successfully.

### R3 — Scenario 0 legacy compatibility
- **G10** Given the project sets only `qa_scenario` to a plain model
  (and an effort), When the user views a PR's role settings, Then
  `qa_interactive` (Scenario 0) runs that model and effort and its
  "decided by" names the `qa_scenario` setting with an `(s0 legacy)`
  marker.
- **G11** Given the same setting comes from the global settings file
  rather than `project.yaml`, When the user views the PR's roles, Then
  Scenario 0 inherits it the same way and the label names the global
  setting.
- **G12** Given the project sets `qa_scenario` to `provider:<name>`,
  When the user views the PR's roles, Then Scenario 0 does **not** use
  that provider or its effort: it stays on the CLI default, and no route
  is listed for `qa_interactive`.
- **G13** Given the project sets `qa_interactive` explicitly (plain model
  or provider), When the user views the PR's roles, Then the explicit
  `qa_interactive` setting wins over the legacy `qa_scenario` model and
  the source does not say "s0 legacy".
- **G14** Given a PR sets its own `qa_scenario` model exception, When the
  user views that PR's roles, Then Scenario 0 is unaffected while the QA
  worker role gets the exception.
- **G15** Given Scenario 0 inherits the legacy model, When a Scenario 0
  session is launched, Then the launched command carries that model (and
  its effort) and nothing else about the launch changes.

### R4 — Router provider diagnostics keep working
- **G16** Given a router provider, When the user runs `pm provider show
  <name>`, Then its settings, launch environment and route status are
  printed without credentials.
- **G17** Given a reachable stub router, When the user runs
  `pm provider test <name>` (and `--live`), Then the host preflight
  passes and the live probe reports the router's answer.
- **G18** Given a router provider missing its model (or with an
  unusable `api_base`), When the user runs `pm provider test <name>`,
  Then the preflight fails with the concrete problem and a remedy, exits
  non-zero, and no fallback account is used.
- **G19** Given a routed role whose provider is fine, When a session is
  launched, Then its log/status shows the `route=… model=… effort=…
  via=…` line, credential-free, naming the role-appropriate path.

### R5 — Container placement stays distinct from routing eligibility
- **G20** Given container mode is on and `impl`, `review`, `signoff`,
  `qa_concretize`, `qa_scenario` are routed, When the user runs
  `pm model show`, Then those roles are described `via=container-bridge`
  and host roles (`qa_planning`, `qa_interactive`, `watcher`, `merge`,
  `qa_verification`, `qa_finalize`) `via=host`.
- **G21** Given only `qa_planning` is routed (a host role), When a QA
  scenario container is created, Then the container is not given the
  route socket mount and the host role launches on the host.
- **G22** Given `qa_scenario`/`qa_concretize` are routed, When a QA
  scenario container is created, Then it has the route socket directory
  mounted and its session reaches the route through the bridge.
- **G23** Given a routed `impl` in container mode, When a container that
  was created before the route was selected is reused, Then the launch
  refuses with a remedy naming the container rather than starting Claude
  without the mount.

### R6 — No regression in the surrounding surfaces
- **G24** Given a project with a routed role, When the user opens the TUI
  model popup on that PR and on the project, Then role rows, provider
  list and route/command columns render, and picking a provider for a
  role updates the rows.
- **G25** Given two pm processes act at once (both starting the host
  bridge for one provider / one writing project model settings while the
  other reads them), Then neither crashes, no partial or duplicate
  socket/state is left behind, and each observes a consistent
  before-or-after view.

## Edge Cases

- **E1** Project sets `qa_scenario: provider:route` and nothing else:
  Scenario 0 stays `(default)` (no model, provider or effort), and no
  route is listed for it.  (Same as G12.)
- **E2** Project sets `qa: provider:route` (parent, not the shim):
  Scenario 0 follows the normal `qa_interactive -> qa` fallback onto the
  route — this is the designed role-neutral behavior, not legacy
  inheritance.
- **E3** `qa_scenario` plain model plus `qa_interactive` plain model:
  the explicit `qa_interactive` wins; no `(s0 legacy)`.
- **E4** Legacy effort: a `qa_scenario` effort is inherited only when no
  other effort setting decides; a Haiku model suppresses effort as before.
- **E5** A blank/non-string `session_models` entry (hand-edited YAML)
  must not crash `pm model show` or a launch; it is reported under
  problems.
- **E6** A router that is down: `pm model show` still describes the
  route; a launch fails inside the session like any unreachable endpoint
  (no silent fallback).
- **E7** Two routes selected by two roles: each role's line names its
  own route; one route never leaks into another role's description.

## Pass/Fail Criteria

A scenario passes when every Then clause is observable in the captured
artifact (recording, pane transcript, command output, created container
inspect) and the command exits as described.  It fails on: a crash or
traceback from a renamed-module import; any role's effective model,
provider, effort or account differing from the pre-change behavior for
the same configuration; the legacy `qa_scenario` provider being inherited
by Scenario 0; a scenario container mounting the bridge for an unrelated
role's route (or missing it for a routed scenario role); a diagnostic
that names a QA-only feature when describing a general role; or a
concurrent invocation producing a duplicate/partial socket or a corrupt
project.yaml read.

## Ambiguities (resolved)

- **A1 — Exact wording of the `pm model show` route heading.**  The impl
  spec chose `Routes (roles set to a provider):`.  QA asserts the
  role-neutral meaning (roles, provider), not the byte-exact string, so a
  later rewording does not fail QA.
- **A2 — Does the legacy shim inherit effort?**  Yes — the pre-change code
  and the extracted helper both do, and the new tests assert it.  QA treats
  effort inheritance as required, but only when no other effort setting
  decides.
- **A3 — Is `qa_interactive` in the container placement set?**  No:
  Scenario 0 is a host session.  A route on `qa_interactive` (via the
  normal `qa` fallback) must be described `via=host` and must not mount
  the bridge into a scenario container.
- **A4 — Concurrency surface for the rename.**  The only shared on-disk
  routing resource is the per-provider host bridge socket directory and
  its lock, plus `project.yaml`.  Both are exercised in one concurrent
  scenario; provider sockets for different routes are independent.

No unresolved ambiguities.
