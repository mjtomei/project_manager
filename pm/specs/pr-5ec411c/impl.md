# pr-5ec411c — Implementation spec: effective Claude effort levels

Follow-up 3 from `followups-pr-592e4bd.md`, expanded by the user's 2026-10-31
clarification and narrowed by the user's 2026-11-01 answer: **for now this PR
supports the effort levels that both the selected model and the Claude Code
CLI accept.**  It does not add an OpenRouter request transformer, and it does
not add reasoning-token-budget or reasoning enabled/disabled controls.

The goal is truthfulness: what PM accepts, reports and launches must be a
level the harness accepts and, where PM knows the model's accepted levels,
one the model accepts too.  Where PM cannot verify a route, it says so
instead of reporting success.

The PR depends on `pr-e076433` (merged): routing is role-neutral and the
module is `pm_core/router_route.py`.

## Current state (grounded)

### The effort vocabulary is three levels

- `pm_core/model_config.py:97` — `EFFORT_LEVELS = ("low", "medium", "high")`.
  It is the single source for validation, CLI `click.Choice`, the TUI cycle
  and provider defaults.
- `pm_core/model_config.py:100-103` — `_NO_EFFORT_MODELS` (haiku) suppresses
  effort after resolution (`:283-288`).
- `pm_core/model_config.py:154-290` — `resolve_model_and_provider` resolves
  model/provider and effort through: `PM_EFFORT` > PR role > PR > provider
  default > project `session_effort` > global `effort-<type>` > built-in.
  It returns a `ModelResolution(model, provider, effort, source,
  effort_source)`.
- `pm_core/model_config.py:320-331` — `provider_effort` reads a provider's
  `effort`; an unknown level is silently ignored.
- `pm_core/model_config.py:348-454` — `validate_model_config` rejects any
  `session_effort` / `effort` value not in `EFFORT_LEVELS`; `_pr_override`
  (`:469-487`) treats an unknown level as absent.
- `pm_core/model_settings.py:32-103` — `RoleRow` / `role_rows` / `format_rows`
  display the effective effort and its source; `set_pr_value` /
  `set_project_value` (`:128-194`) refuse an unknown level.
- `pm_core/tui/model_screen.py:33,69-75` — `_EFFORT_CYCLE = (None, *EFFORT_LEVELS)`;
  `e` cycles it.
- `pm_core/cli/model.py:176`, `pm_core/cli/pr.py:3488`,
  `pm_core/cli/provider.py:132` — `click.Choice(list(EFFORT_LEVELS))`.
- `pm_core/providers.py:453-456` — a provider entry's `effort` is validated
  against `EFFORT_LEVELS`; `ProviderConfig.effort` (`:298`) carries it.
- `README.md:169-240` documents the model/effort model.

### The launch path ends at the Claude CLI

- `pm_core/claude_launcher.py:653-770` `launch_claude`, `:773-865`
  `launch_claude_print`, `:879-1096` `build_claude_shell_cmd`, and
  `:1270-1331` `launch_claude_print_background` all pass `--effort <level>`
  to the `claude` executable.  `launch_claude_print_background` takes no
  effort (its caller, `pm_core/plans/review.py:170`, is a review helper).
- `pm_core/providers.py:205-228` `launch_env` decides the environment of a
  launch: it assigns what the selection needs and **unsets** every other
  routing variable (`LAUNCH_ROUTING_ENV_VARS`), so a caller's environment
  cannot pick a model or account.  Effort is not in that set today.
- `pm_core/router_route.py:239-266` `describe` prints
  `route=… model=… effort=… via=…` from the resolution.

**There is no request transformer in this repository.**  `pm_core/route_bridge.py`
only forwards bytes between a Unix socket and a TCP port.  The router that
turns Claude Code's `output_config.effort` into an upstream request is
external and outside PM's control.  This PR therefore does not claim to
translate requests; it validates the level PM can actually send.

### What the installed Claude CLI (2.1.316) actually does

Verified from `claude --help` and the installed binary on 2026-11-01:

- `--effort <level>` accepts `low, medium, high, xhigh, max`.
- The CLI sends the level as `output_config.effort` in `/v1/messages`
  requests.  That is the only reasoning field PM can influence.
- `CLAUDE_CODE_EFFORT_LEVEL` **overrides** `--effort` for the session
  (binary strings: "env_override: CLAUDE_CODE_EFFORT_LEVEL overrides effort
  for this session", "Not applied: CLAUDE_CODE_EFFORT_LEVEL=… overrides
  effort this session").  `auto` and `unset` mean "no override".
- `MAX_THINKING_TOKENS` only toggles thinking on/off for the legacy
  `budget_tokens` regime; on the current effort-capable models it is not a
  reasoning budget.
- `--task-budget <tokens>` maps to `output_config.task_budget`, a task
  ceiling, not a reasoning budget or the output `max_tokens` limit.

## Requirements

### R1 — Native Claude effort levels everywhere
- `EFFORT_LEVELS` becomes `("low", "medium", "high", "xhigh", "max")` — the
  set the harness accepts.
- Every validation, CLI choice, provider default, project/PR/session
  override, helper, launch argument, `pm model show` / `pm pr model show`
  and the TUI effort cycle uses it.  No hard-coded three-level list remains
  (including the docstrings at `claude_launcher.py:668,919` and
  `tui/model_screen.py:70`).
- `None` still means "pass no `--effort`" (the CLI default).  `"none"` is
  never written into `--effort` (it is not a Claude level).
- Existing no-effort compatibility is preserved: Haiku models still
  suppress effort (`_NO_EFFORT_MODELS`), and a role with no setting still
  passes nothing.

### R2 — Per-model accepted levels (effort only)
Add an optional `supported_efforts` list to a `providers.yaml` entry
(`ProviderConfig.supported_efforts`), naming the effort levels the selected
model/route accepts.  Two optional provenance fields keep it honest:
`supported_efforts_source` (where the list came from) and
`supported_efforts_checked_at` (ISO date).

```yaml
my-router:
  type: router
  api_base: http://127.0.0.1:<port>
  model: deepseek/deepseek-v4.1-flash-1017
  supported_efforts: [max, high, low]          # Claude levels only
  supported_efforts_source: "GET /api/v1/models 2026-10-31"
  supported_efforts_checked_at: "2026-10-31"
```

Rules:
- All three fields are optional.  Wrong types make the provider entry
  invalid (the existing `_entry_problem` contract), so a broken entry fails
  a launch with the usual one-line `Error:` rather than being guessed
  around.
- `supported_efforts` is intersected with `EFFORT_LEVELS`.  Values outside
  the Claude vocabulary (e.g. OpenRouter's `none`) are kept in the file for
  provenance but are never offered, sent or treated as Claude levels.
- The list is **advisory and dated**.  PM never invents support from an
  absent list and never treats a stale list as authoritative.
- `pm provider add` / `edit` gain `--supported-efforts a,b`,
  `--supported-efforts-source TEXT`, `--supported-efforts-checked-at DATE`,
  and `--clear supported_efforts ...`.  `pm provider list` prints the list;
  `pm provider show` prints the list, its source, its checked-at date and
  its age (the one-line list line stays readable).
- No catalog fetch and no paid probe are added in this PR.

### R3 — Requested vs effective vs verified
`ModelResolution` gains, alongside `effort` / `effort_source`:
- `effort_requested`: the configured level before suppression, or `None`.
- `effort_status`: one of `none`, `cli`, `ok`, `unverified`, `unsupported`,
  `not_applicable`, `overridden`.
- `effort_notes`: human-readable diagnostics (list of strings).
- `supported_efforts`: the intersection PM used (or `None` when the
  provider declares none), for display.

Status semantics:
- `none` — nothing selected; the CLI default applies.
- `cli` — a plain Claude model; the CLI/model decides, PM has no metadata.
- `ok` — the selected route declares the level supported.
- `unverified` — routed, but the route declares no `supported_efforts`.
- `unsupported` — the route declares the level unsupported.
- `not_applicable` — the model is known not to take effort (Haiku).
- `overridden` — an ambient `CLAUDE_CODE_EFFORT_LEVEL` decides the session
  because PM selected nothing.

`pm model show`, `pm pr model show`, `pm provider show`, the TUI model
screen and `router_route.describe` all show the effective level, its
source, its status and the notes.  A level the route declares unsupported
is marked inline (`effort=high (unsupported)`, `high *` in the role table);
an `unverified` level (the route declares no `supported_efforts`) is left
unmarked in the inline column but always named in the effort notes, so a
bare `effort=high` never claims support the route did not declare.

### R4 — Environment precedence is visible and truthful
- `CLAUDE_CODE_EFFORT_LEVEL` (valid level, not `auto`/`unset`) is detected.
- When PM has its own effective effort, the launch **unsets**
  `CLAUDE_CODE_EFFORT_LEVEL` so `--effort` is authoritative, and records a
  note that the ambient value was overridden.  This fixes "PM reports high
  while actually running xhigh".
- When PM has no effort of its own, the ambient value is reported as the
  source (`effort_source="CLAUDE_CODE_EFFORT_LEVEL"`, `status="overridden"`)
  and the launch passes `--effort <value>` equal to it, so argv and the
  session agree.
- `auto`/`unset` is treated as absent; an invalid value is noted and ignored.
- The unset must cover both the shell-command path (`build_claude_shell_cmd`)
  and the subprocess paths (`launch_claude`, `launch_claude_print`), whose
  `run_env` is otherwise `None`/inherited.
- `maxEffortLevel` / `effortLevel` in Claude Code's own settings files are
  **not** read (documented limitation); PM notes in the README that they
  take precedence over `--effort`, and a user can check with `/effort`.

### R5 — Unsupported levels are visible, never faked
- Values outside `EFFORT_LEVELS` stay rejected at set time, as today.
- A configured level the selected route declares unsupported is a set-time
  warning (`pm model set` / `pm pr model set`), a `validate_model_config`
  warning and a launch/display note.  The launch still passes `--effort`
  (the CLI accepts it and the dated metadata may be stale), but the setting
  is never shown as verified.
- The TUI cycle and `click.Choice` offer all five levels, because a stale
  or missing `supported_efforts` list must not block a level the harness
  accepts (the user's working `xhigh` is the motivating case).  The
  per-row status shows when the model's declared list excludes it.
- A level and a reasoning-token budget are not interchangeable; this PR
  adds no budget/enabled setting, and no `--task-budget`/`MAX_THINKING_TOKENS`
  substitution is made.

### R6 — Preserve routing, precedence and user intent
- The existing precedence order is unchanged; the `CLAUDE_CODE_EFFORT_LEVEL`
  handling is additive (R4).
- No change to accounts, spend policy, or running sessions.
- No global account/config migration.  The `CLAUDE_CODE_EFFORT_LEVEL=xhigh`
  workaround is only replaced in documentation, and only after the user
  verifies the direct setting.

### R7 — Tests
- Unit tests for: the widened vocabulary; each status; env precedence and
  the unset on both launch paths; Haiku suppression; an unsupported level;
  absent and stale metadata; a provider whose `supported_efforts` uses a
  non-Claude value (`none`); save/load round-trips through project, PR,
  global and provider forms; `next_effort` wrapping all six states.
- `validate_model_config` warnings for an unsupported configured level, for
  both the per-role `session_effort` forms and the PR-wide `effort` (which
  decides every PR role, so one rejected level on one route is reported
  once, not once per role).
- Display tests: `format_rows` / `role_rows` never print a bare level for
  an `unsupported` or `overridden` one, and `router_route.describe` marks
  `unsupported`/`overridden`.  `unverified` is deliberately left bare
  inline (R3) and named in the notes, so route lines stay readable; the
  test asserts the note, not the marker.
- No paid probe and no network in tests.

## Implicit requirements

1. **`EFFORT_LEVELS` is imported by five modules and the tests.**  Widening
   it must not change the meaning of `None`; every `if effort:` /
   `if not effort:` branch keeps working.  `"max"`/`"xhigh"` are truthy
   strings, as before.
2. **`_pr_override` uses `EFFORT_LEVELS` membership as "usable".**  A
   stored `xhigh` must be usable; an unknown value must stay "absent" and
   still be reported by `validate_model_config`.
3. **Provider `effort` validation** (`providers._entry_problem`) must accept
   the new levels, or a user cannot set `effort: xhigh` on a router.
4. **The TUI cycle** must visit all six states (none + five levels) and
   still wrap; the existing `next_effort` test must be updated, not broken.
5. **Display width**: `format_rows` already pads to the widest cell; notes
   are printed as footnotes like the existing `problem` lines so the TUI
   popup stays sized to its widest row.
6. **Provider entries are read on every launch** (`provider_effort`,
   `launch_env`).  The new fields must be cheap to read and must never
   raise for a malformed entry; the existing "broken entry fails the launch
   with one Error line" behavior is preserved.
7. **`pm provider add/edit` writes providers.yaml under a lock and at 0600.**
   The new fields go through the same `providers_lock` /
   `load_providers_for_edit` / `save_providers` path.
8. **Secrets are never printed.**  The new fields carry no credentials.
9. **The `claude` binary may be older than 2.1.316.**  PM does not probe
   `--help` at launch; a level the CLI rejects fails the session as it does
   today.  The README records the tested version.

## Ambiguities and resolutions

### A1 — OpenRouter request transformer [resolved by the user, 2026-11-01]
The user answered: "for now we only need to support what effort levels both
the model and claude code accept."  This PR therefore does **not** add an
Anthropic→OpenRouter proxy, `reasoning.max_tokens`, or
`reasoning.enabled/disabled` controls.  It widens the Claude vocabulary,
models a provider's accepted levels, and reports requested vs effective vs
verified.  The router prerequisite (it must translate `output_config.effort`
upstream) is documented, not implemented.

### A2 — Precedence of `CLAUDE_CODE_EFFORT_LEVEL` vs PM's own setting [resolved by the user]
The user chose "PM setting wins, conflict shown".  Resolved as R4: PM unsets
the ambient variable in the launched environment when it has its own
effort, and notes the conflict; with no PM effort, the ambient value is
reported as the source.

### A3 — What an unsupported level does [resolved]
Resolved as R5: warn and mark `unsupported`; never refuse a level in
`EFFORT_LEVELS`, because `supported_efforts` is dated metadata and refusing
would block the user's verified `xhigh` workaround.

### A4 — Where accepted levels come from [resolved]
Declared per provider in `providers.yaml`, with optional source/date.  PM
does not hard-code a model list beyond the existing Haiku suppression and
does not fetch a catalog in this PR.

## Edge cases

- `effort: xhigh` with a plain `opus` model: no provider metadata, status
  `cli`; the CLI accepts it.
- A routed role with `effort: max` on a route declaring
  `supported_efforts: [max, high, low]`: `ok`.
- The same route with `effort: xhigh`: `unsupported`, note lists the
  declared set; the launch still passes `--effort xhigh`.
- A route with no `supported_efforts`: `unverified` for every effort.
- A route declaring `supported_efforts: [none, high]`: `none` is dropped
  from the intersection; `high` is `ok`.
- A route declaring `supported_efforts: []` accepts none of the Claude
  levels: every configured level is `unsupported` (not "unverified").
- Haiku + `effort: xhigh`: `not_applicable`, `effort=None`, nothing passed;
  the role table shows `xhigh (n/a)` so requested vs effective stays
  visible.
- `PM_EFFORT=xhigh` and `CLAUDE_CODE_EFFORT_LEVEL=high`: PM wins, launches
  `--effort xhigh`, unsets the ambient var, note records the conflict.
- `CLAUDE_CODE_EFFORT_LEVEL=xhigh` alone: source is the env, effective
  `xhigh`, `--effort xhigh` passed, status `overridden`.
- `CLAUDE_CODE_EFFORT_LEVEL=auto`: treated as absent.
- A hand-edited `session_effort: {qa: none}`: `validate_model_config`
  reports it, `_pr_override` treats it as absent, no `--effort none`.
- A provider entry whose `supported_efforts` is a string or a list with
  non-strings: invalid entry, one-line error, no launch.
- `supported_efforts_checked_at` older than 30 days: a `stale` note is
  appended; the status is still computed from the declared set.
- `pm model show` with a malformed `model_config`: unchanged behavior.
- The TUI popup with long notes: notes are footnotes, not columns, so the
  popup still sizes to its widest row.
- `launch_claude_print_background` (review helper) has no effort parameter;
  it must keep working unchanged.
- A routed launch with `env_out=None` in `build_claude_shell_cmd`: the
  existing `ValueError` for a router is unchanged.
- A provider that assigns `CLAUDE_CODE_EFFORT_LEVEL` through its `env:`
  block: PM leaves the provider's assignment (the user configured it
  explicitly) and notes it; it does not silently drop a user-set variable.
- A provider `env:` assignment *and* an ambient `CLAUDE_CODE_EFFORT_LEVEL`
  with a PM level of its own: the provider's value wins in the launched
  process, so the notes must not claim pm unsets the ambient variable (it
  does not, for that provider).  The provider note is the only one emitted.
- Haiku with the ambient variable as the *only* selection: the suppression
  note says the variable remains and nothing is passed; no note may claim
  pm passes the level as `--effort`.
- A route whose providers.yaml entry cannot be read: `unverified` with a
  "could not be read" note, not "declares no supported_efforts" (that
  would be a false statement about the file).
- `pm model show` and `pm pr model show` agree on the effort column: a
  suppressed level is shown as the requested one (`xhigh (n/a)`), not as
  `(default)`.  `effort_source` is kept alongside it, so the role table's
  "decided by" names the setting that asked for the level
  (`effort: project impl`) instead of `(CLI default)`.
- A provider that assigns `CLAUDE_CODE_EFFORT_LEVEL=auto` (or `unset`): the
  launcher keeps the provider's value, which means "no override" to Claude
  Code, so `--effort` applies; the note says so rather than calling `auto`
  an unknown level.
- A provider whose `unset_env` already lists `CLAUDE_CODE_EFFORT_LEVEL`
  while pm sets an effort: the command unsets it once, not twice.

## Implementation plan (files)

1. `pm_core/model_config.py` — widen `EFFORT_LEVELS`; add `is_effort_level`,
   `normalize_ambient_effort`, `accepted_efforts_of`, `provider_effort_env`
   and `unsupported_effort_problem`; extend `ModelResolution`; resolve the
   ambient `CLAUDE_CODE_EFFORT_LEVEL`; compute status/notes (including a
   provider `env:` assignment of it); extend `validate_model_config`.
2. `pm_core/providers.py` — `supported_efforts` / source / checked-at on
   `ProviderConfig`, entry validation, and a helper for the intersection.
3. `pm_core/claude_launcher.py` — unset `CLAUDE_CODE_EFFORT_LEVEL` when PM
   sets an effort (shell and subprocess paths); update docstrings.
4. `pm_core/model_settings.py` — `RoleRow.effort_status` / `effort_notes`,
   display footnotes, set-time warning.
5. `pm_core/cli/model.py`, `pm_core/cli/pr.py`, `pm_core/cli/provider.py` —
   choices, show output, provider fields.
6. `pm_core/tui/model_screen.py` — cycle the new levels; show status.
7. `pm_core/router_route.py` — `describe` includes status.
8. `README.md` — document the levels, the env precedence and
   `supported_efforts`.
9. `tests/` — `test_model_config.py`, `test_model_settings.py`,
   `test_claude_launcher.py`, `test_router_route.py`, `test_provider`-style
   coverage in the existing files.
