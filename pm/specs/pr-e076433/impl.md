# pr-e076433 — Implementation spec: role-neutral routing names and docs

Follow-up 1 from `followups-pr-592e4bd.md` (item 1), after #249
(`pr-592e4bd`) merged.  Routing already works for every role; the module
name, the placement constant, diagnostics and examples still read as a
QA-worker feature.  This PR aligns the names and documentation with the
actual role-neutral behavior **without changing any configured route,
provider, account or effort**.

## Current state (grounded)

- `pm_core/worker_route.py` owns everything route-specific outside the
  launch command: `describe()`, `setup_problem()` / `require_setup()`,
  `launch_parts()`, `check_route()`, `live_probe()`, the host bridge, and
  `container_mounts()`.  Its docstring opens with the QA refiner
  (`qa_concretize`) / workers (`qa_scenario`) example, and its logger is
  `pm.worker_route`.
- `ROUTED_SESSION_TYPES = ("qa_concretize", "qa_scenario")`
  (`pm_core/worker_route.py:61`) is *placement*: the two QA roles that run
  in scenario containers and therefore need the route bridge mounted.
  `CONTAINER_SESSION_TYPES = ("impl", "review", "signoff") +
  ROUTED_SESSION_TYPES` is the full set that runs in a pm container in
  container mode.
- Routing eligibility is not gated by either constant: any session type
  may select `provider:<name>` through `PM_MODEL`, a PR override, project
  `model_config`, or a global setting
  (`pm_core/model_config.py:resolve_model_and_provider`).
- Call sites of the module: `pm_core/model_settings.py`,
  `pm_core/providers.py`, `pm_core/claude_launcher.py`,
  `pm_core/container.py`, `pm_core/tui/model_screen.py`,
  `pm_core/cli/model.py`, `pm_core/cli/provider.py`, `pm_core/qa_loop.py`.
  Tests: `tests/test_worker_route.py` (3425 lines),
  `tests/test_model_config.py`, `tests/test_model_settings.py`.
- `pm model show` prints a `Routes:` section whose code comment calls it
  "Router providers (worker routes)"; README's only routing example is
  `pm model set qa_scenario provider:my-router --project`.
- `resolve_model_and_provider` (`pm_core/model_config.py:220-233`) has a
  legacy Scenario-0 shim: when `session_type == "qa_interactive"` and the
  normal `qa_interactive -> qa` chain selects neither a model nor a
  provider, it re-resolves `qa_scenario` with project data only and
  inherits a plain model (and its effort) with source suffix
  `"(s0 legacy)"`.  A `qa_scenario` provider is discarded.

## Requirements

### R1 — Rename the module role-neutrally
Rename `pm_core/worker_route.py` to `pm_core/router_route.py` (pairs with
the existing `pm_core/route_bridge.py`).  Update every import, string
patch target, docstring reference, logger name (`pm.router_route`) and
comment in `pm_core/` and `tests/`.  Historical records stay untouched:
`pm/project.yaml` notes and `pm/specs/pr-592e4bd/*` describe past work and
must not be rewritten.

Rename `tests/test_worker_route.py` to `tests/test_router_route.py` and
update its module docstring from "QA worker routing" to role-neutral
routing.

### R2 — Rename the placement constant
Rename `ROUTED_SESSION_TYPES` to `SCENARIO_CONTAINER_TYPES` (the QA roles
that run in scenario containers).  Keep `CONTAINER_SESSION_TYPES` as the
union of `("impl", "review", "signoff")` and the scenario types.

Document explicitly, on both constants, that they describe **container
placement**, not routing eligibility: any session type may be routed, and
these constants only decide which launches reach a route through the
container bridge and which scenario containers need the bridge mount.

Update every use (`pm_core/qa_loop.py` `_require_scenario_setup`,
`_route_mounts`, `check_qa_providers`; `pm_core/model_settings.py`;
`pm_core/cli/model.py`; tests).

### R3 — Role-neutral diagnostics, docs and examples
- `pm_core/router_route.py` module docstring: describe routes as
  per-session-type / per-PR model selection, with examples beyond QA
  (`impl`, `signoff`) and a statement that an unset role runs plain
  `claude` on the CLI default.
- `pm model show`: replace the "worker routes" code comment; make the
  section header role-neutral and explicit (see Ambiguity A1).
- `pm_core/qa_loop.py` section header `# Worker routes
  (pm_core.worker_route)` -> role-neutral.
- `pm_core/providers.py`, `pm_core/container.py`,
  `pm_core/claude_launcher.py` references to the module and to
  "worker-route" bridge wording.
- README "Models, providers and effort": explain that the setting is
  explicit and per role for every session pm launches, show more than the
  `qa_scenario` example (`impl`, `signoff`, a PR-wide route), and state
  that with nothing configured the role runs plain Claude (CLI default).
- Keep the credential-free / fail-closed semantics unchanged in wording:
  a missing or broken provider stops the launch; pm never falls back to
  another provider or account.

### R4 — Legacy Scenario-0 fallback: document, retain, test
The legacy shim exists because Scenario 0 used to be `qa_scenario`; a
project/global plain-model `qa_scenario` must keep deciding s0 after the
`qa_interactive` type split.  Retirement is **not** safe: a config that
sets only `qa_scenario` (and no `qa`/`qa_interactive`) would silently fall
back to the CLI default, moving the model (and possibly the account) the
user intended for the interactive session.  Therefore:

- Keep the behavior byte-for-byte.
- Extract it into a documented helper (`_legacy_s0_resolution`) that
  states why it exists, that it reads project/global settings only (never
  a PR's worker exception), that it inherits only a plain model/effort,
  and that it never inherits a provider (a routed `qa_scenario` is the
  workers' route, not s0's).
- Record the compatibility decision in the module docstring.
- Add regression tests: plain project model inherited; plain global model
  inherited; provider not inherited; explicit `qa_interactive` model or
  provider wins over the legacy model; PR `qa_scenario` exception does not
  move s0.

### R5 — Preserve behavior
No change to effective model/provider/account/effort resolution for any
supported configuration: explicit role overrides, helpers, host and
container launches, and the no-configuration default (plain Claude).

## Implicit requirements

- **I1** `pm_core.router_route` must be importable everywhere the old
  module was; any string-based monkeypatch target in tests
  (`pm_core.worker_route.<name>`) must be updated, or tests silently stop
  patching.
- **I2** The renamed constant must not be used as a routing allowlist.
  `container_mounts()` and `require_setup()` stay keyed on the resolved
  provider, not on the constant.
- **I3** Scenario containers must still mount the bridge when
  `qa_concretize`/`qa_scenario` are routed, and must not mount it for an
  unrelated role's route (e.g. a routed `qa_planning` runs on the host).
- **I4** `pm model show`'s Routes output keeps its existing content and
  ordering; only the label/comment wording changes.
- **I5** No new routing policy, no broad refactor, no live account
  migration, no change to `providers.yaml` schema.
- **I6** Logging name changes from `pm.worker_route` to
  `pm.router_route`; no test may assert the old logger name after the
  change.

## Ambiguities (resolved)

- **A1 — `pm model show` section label.**  The current label is already
  `Routes:`; the "worker routes" text is a code comment.  Resolution:
  change the comment and make the header explicitly role-neutral:
  `Routes (roles set to a provider):`.  Update the ten tests that split on
  the old header.  No content change.
- **A2 — Module name.**  The task suggests `router_route`; chosen.  It
  matches `route_bridge` and describes "the route of a router provider"
  without naming a role.
- **A3 — Retire or keep the legacy shim.**  Retire would silently change
  s0's model for legacy configs, which the task forbids.  Keep it, with
  explicit documentation and tests.  No migration is performed; users who
  want to take control set `qa_interactive` explicitly, and
  `pm pr model show` (and the TUI) label the inherited value
  `(s0 legacy)`.
- **A4 — Backward-compatible alias for the old constant/module.**  None
  is added: both are internal (no public API, no entry point), and the
  task asks to rename them.  Historical specs keep their old spellings.

## Edge cases

- **E1** Project sets `qa_scenario: provider:route` and nothing else:
  s0 stays on the CLI default (no model, no provider, no effort), and no
  route is mounted for s0.  Existing behavior, re-tested.
- **E2** Project sets `qa: provider:route`: s0 follows the normal
  `qa_interactive -> qa` fallback onto the route (this is the designed
  role-neutral behavior, not the legacy shim).  Unchanged.
- **E3** Project sets both `qa_interactive: sonnet` and
  `qa_scenario: haiku`: s0 is `sonnet`; the shim is not consulted.
- **E4** PR sets `session_models: {qa_scenario: haiku}`: s0 ignores it
  (the shim resolves project data only); the worker gets `haiku`.
- **E5** Global `model-qa_scenario` plain model with no project setting:
  s0 inherits it with source `global qa_scenario (s0 legacy)`.
- **E6** Container mode: a route on `impl`/`review`/`signoff` still uses
  `wrap_claude_cmd`'s bridge; a route on `qa_concretize`/`qa_scenario`
  still mounts the scenario container bridge; a route on `qa_planning`
  runs on the host with no scenario bridge mount.
- **E7** `pm provider test` / `show` / TUI provider list diagnostics keep
  working through the renamed module.

## Validation plan

1. `pytest tests/test_router_route.py tests/test_model_config.py
   tests/test_model_settings.py` plus the full suite once after final
   edits (`PYTHONPATH=/workspace`; container venv has `pytest<9`).
2. New tests for R2/R3/R4 (placement constant identity and non-restriction;
   legacy inheritance and non-inheritance; explicit override precedence).
3. `grep -rn worker_route pm_core tests` returns nothing (historical
   `pm/specs/pr-592e4bd` and `pm/project.yaml` excluded).
4. Manual sanity: `pm model show` output and README example commands.

## Validation results

- `pytest tests/test_router_route.py` — 239 passed.
- `pytest tests/test_model_config.py` — 104 passed.
- `pytest tests/test_model_settings.py` — 43 passed.
- Full suite (`pytest -q`) — **5207 passed, 1 skipped** (pytest 8.4.2,
  `PYTHONPATH=/workspace`).
- `grep -rn 'worker_route|ROUTED_SESSION_TYPES'` — only historical records
  (`pm/project.yaml` notes, `pm/specs/pr-592e4bd/*`); no code or test.
- New regressions: `TestPlacement` (constant identity, routing not
  restricted, only scenario roles checked/mounted) and the Scenario-0
  legacy tests in `tests/test_model_config.py` (project/global plain-model
  inheritance, provider non-inheritance from both, explicit
  `qa_interactive` model/provider precedence).
