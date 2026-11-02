# QA Spec: PR pr-5ec411c — effective Claude / OpenRouter reasoning controls

Grounded in `pm/specs/pr-5ec411c/impl.md` and in behavior observed on this
branch with a throwaway project (commands and outputs quoted below).

Scope of the branch as implemented: the effort vocabulary is widened to the
five levels the Claude Code CLI accepts (`low`, `medium`, `high`, `xhigh`,
`max`); a provider entry may declare dated `supported_efforts` metadata; PM
reports requested vs effective vs verified effort and its source; the
ambient `CLAUDE_CODE_EFFORT_LEVEL` and a provider's own `env:` assignment of
it are reconciled truthfully at launch.  No OpenRouter request transformer,
no reasoning-token budget, and no enabled/disabled control is added.

## 1. Requirements (Given / When / Then)

### R1 — Native level vocabulary is accepted everywhere
- **Given** a project with no model settings, **When** the user runs
  `pm model set impl opus --effort xhigh --project`, **Then** the command
  succeeds, `pm/model_config` stores `impl: xhigh`, and `pm model show`
  prints `xhigh` for impl with no warning and no mark.
- **Given** a PR, **When** the user runs
  `pm pr model set <pr> --effort max --role review`, **Then** the PR's
  `session_effort.review` is `max` and `pm pr model show <pr>` shows `max`
  for review with `effort: PR review` in the decided-by column.
- **Given** a project, **When** the user asks `pm model set --help`,
  **Then** the `--effort` choice lists exactly
  `low|medium|high|xhigh|max`.
- **Given** a project, **When** the user runs
  `pm model set impl opus --effort none --project` (or `turbo`), **Then**
  the CLI rejects the value as invalid and names the five valid levels;
  nothing is written.
- **Given** a project where a role has no effort setting, **When** the user
  runs `pm model show`, **Then** that role's effort column reads
  `(default)` — visibly distinct from any level.

### R2 — Unsupported / unverified levels are never shown as verified
- **Given** a router provider whose entry declares
  `supported_efforts: [max, high, low]`, **When** the user sets impl to
  `provider:<name>` with `--effort xhigh`, **Then** the set command still
  succeeds but prints a warning naming the declared list, and
  `pm model show` prints `xhigh *` with an effort note quoting the
  declared list, and the route line reads `effort=xhigh (unsupported)`.
- **Given** the same route, **When** the user sets `--effort max`,
  **Then** no warning is printed, the table shows a bare `max`, and the
  route line shows `effort=max` without a marker.
- **Given** a router provider with no `supported_efforts`, **When** a role
  on it has `--effort high`, **Then** the table shows a bare `high` but
  the effort notes say the route "declares no supported_efforts; the level
  cannot be verified" (unverified is named, not marked).
- **Given** a router whose entry cannot be read (e.g. hand-edited to a
  string), **When** a role on it has an effort, **Then** the note says the
  route "could not be read; the level cannot be verified" — not that it
  "declares no supported_efforts".
- **Given** a role whose model is Haiku with `--effort xhigh`, **When** the
  user runs `pm model show` / `pm pr model show`, **Then** the effort cell
  reads `xhigh (n/a)` and the decided-by column still names the setting
  that asked for it (not `(CLI default)`).
- **Given** a PR-wide effort the selected route rejects, **When** the user
  runs `pm pr model set <pr> --effort xhigh` (no `--role`), **Then** exactly
  one warning is printed per distinct problem, and `pm model show`'s
  problems section reports it under `prs[<id>].effort`, not once per role.

### R3 — Provider capability metadata lifecycle
- **Given** no provider yet, **When** the user runs
  `pm provider add my-router --type router --api-base ... --model ... \
   --supported-efforts max,high,low,none \
   --supported-efforts-source "GET /api/v1/models 2026-10-31" \
   --supported-efforts-checked-at 2026-10-31`, **Then**
  `pm provider list` shows `supported_efforts=max,high,low,none` and
  `pm provider show` prints `accepted Claude levels: low, high, max`,
  `non-Claude levels kept for provenance: none`, the source, and the
  checked date with its age.
- **Given** a provider whose metadata is older than 30 days, **When** a
  role on it has an effort, **Then** the effort notes carry a "days old"
  refresh hint while the status is still computed from the declared list.
- **Given** a provider with `supported_efforts: []`, **When** a role on it
  has any Claude level, **Then** the status is unsupported (not unverified)
  and the note says the route accepts none.
- **Given** a provider with a declared list, **When** the user changes its
  model with `pm provider edit <name> --model <other>` without updating the
  list, **Then** the command warns that the list was checked against the old
  model and names the new one.
- **Given** a provider entry hand-edited so `supported_efforts` is a string
  (or contains a blank name, or the checked date is not ISO), **When** the
  user runs `pm provider list`, **Then** the entry is listed as
  `INVALID ENTRY` with a one-line reason, and a launch on it fails with the
  usual one-line `Error:` rather than guessing.
- **Given** a provider with all three metadata fields, **When** the user
  runs `pm provider edit <name> --clear supported_efforts`, **Then** the
  list is removed from the file and the display no longer claims accepted
  levels.
- **Given** a provider `env:` block that assigns `CLAUDE_CODE_EFFORT_LEVEL`,
  **When** the user runs `pm provider show`, **Then** it prints an
  `effort env:` line saying whether the value overrides `--effort`, is a
  no-override (`auto`/`unset`/blank), or is not a known level.

### R4 — The launch does what the display reports
- **Given** a role with `--effort xhigh` on a plain model, **When** the
  user starts it (`pm pr start`), **Then** the launched command carries
  `--effort xhigh`.
- **Given** a role whose route declares the level unsupported, **When** it
  launches, **Then** the command still carries `--effort <level>` and the
  session log contains a warning naming the declared list (the metadata may
  be stale; the launch is not refused).
- **Given** no effort is configured for a role, **When** it launches,
  **Then** the command carries no `--effort` at all.
- **Given** a Haiku role with a configured effort, **When** it launches,
  **Then** the command carries no `--effort`.
- **Given** a provider with a default `effort: high` and a role with no
  effort of its own, **When** the role launches, **Then** the command
  carries `--effort high` and the display names `provider <name>` as the
  source.
- **Given** a project with a tmux session, **When** the user opens a review
  window (`pm pr review`) for a routed role, **Then** the pane-registry
  entry / command log for that pane contains the same `--effort` and the
  `env -u CLAUDE_CODE_EFFORT_LEVEL` prefix when PM has its own level.

### R5 — Ambient and provider env precedence is truthful
- **Given** `CLAUDE_CODE_EFFORT_LEVEL=xhigh` in the shell and a PM setting
  of `high`, **When** the user runs `pm model show` and then launches,
  **Then** the display shows `high *` with a note that PM unsets the
  ambient variable, and the launched process has `--effort high` with
  `CLAUDE_CODE_EFFORT_LEVEL` absent from its environment.
- **Given** the ambient variable as the only selection (`xhigh`), **When**
  the user launches, **Then** the display reports `CLAUDE_CODE_EFFORT_LEVEL`
  as the source and the launched process receives `--effort xhigh`.
- **Given** the ambient variable is `auto`, `unset`, blank, or an unknown
  value, **When** the user runs `pm model show`, **Then** `auto`/`unset`/
  blank are treated as absent and an unknown value is noted and ignored —
  no `--effort` is invented.
- **Given** a provider `env:` block assigning
  `CLAUDE_CODE_EFFORT_LEVEL=xhigh` and a PM setting of `high`, **When** the
  role launches, **Then** the launched process keeps `xhigh` (the user's
  explicit provider configuration), the command still passes
  `--effort high`, the session log warns that the provider value overrides
  it, and `pm model show` marks the row and says the provider value is what
  applies.
- **Given** a provider `env:` assignment of `auto` (or `unset`), **When**
  the role launches, **Then** `--effort` applies and the display says the
  assignment is "no override" rather than calling it an unknown level.
- **Given** a provider `env:` assignment and a PM level of its own,
  **When** the role launches, **Then** the display does not claim PM unsets
  the ambient variable (it does not, for that provider) — the provider note
  is the only one.

### R6 — TUI selector and display
- **Given** a project and a selected PR, **When** the user opens the model
  screen and presses `e` repeatedly on a role, **Then** the effort cycles
  `(default) → low → medium → high → xhigh → max → (default)` and each
  change is written to `project.yaml` / the PR entry and reflected in the
  table.
- **Given** a routed role with a rejected level, **When** the model screen
  is open, **Then** the row carries `*` and the explanation is printed as a
  dim footnote (not an error line).
- **Given** the project view of the model screen, **When** it lists
  providers, **Then** each router with metadata shows
  `supported_efforts=...` in its line.
- **Given** the model screen is open while a launch is prepared, **When**
  the user saves a new effort, **Then** the next launch uses it and the
  running session is unchanged.

### R7 — No regression to existing precedence or flows
- **Given** `PM_EFFORT` set, **When** a PR also has an effort, **Then**
  `PM_EFFORT` still wins (precedence order unchanged).
- **Given** a project with fake-claude configured, **When** a review loop
  runs, **Then** it still reaches its verdict (the fake path is unaffected
  by the effort changes).
- **Given** any command that prints provider details, **When** it prints,
  **Then** no credential value appears.

## 2. Setup (user steps)

1. Install the branch: `python3 -m venv /tmp/pm-venv && source
   /tmp/pm-venv/bin/activate && pip install -e .` from the workdir; or
   `./install.sh --local` if `pm` is not on PATH.  Confirm `pm which` points
   at this clone.
2. Isolate global state: `export HOME=$(mktemp -d)` (or a scratch home) so
   `~/.pm/providers.yaml`, `~/.pm/settings` and `~/.pm/debug` are disposable.
3. Create a throwaway project:
   `git init`, one commit, `pm init --backend local --no-import`,
   `pm pr add "Test PR"`.  For a startable PR, `pm push` then merge the
   sync branch on master, or use a PR created after the first commit.
4. **tmux isolation:** run launch-driving commands from a shell with `TMUX`
   and `TMUX_PANE` unset, or from a scratch tmux session whose name does not
   start with `pm-`.  Otherwise `pm` treats the current tmux session as the
   project's pm session and opens windows in it (observed: a `pm pr start`
   run inside another project's pm session opened a window there).
5. **Observing the launch:** the fake-claude config path short-circuits
   before `--model`/`--effort` are appended, so it cannot verify argv.
   Put a stub `claude` executable first on `PATH` that appends `$@` and
   `${CLAUDE_CODE_EFFORT_LEVEL-<unset>}` to a capture file and exits 0.
   For the tmux/shell path, read the command from the command log
   (`pm log grep effort`, `~/.pm/debug/<tag>.log`) or the pane registry.
6. Launch warnings are written to the session log, not stdout: read them
   with `pm log grep <pattern>` or the log file.

## 3. Edge cases / failure modes to probe

- `--effort none` rejected by the CLI; a hand-edited `session_effort: {qa:
  none}` reported by `pm model show` problems and treated as absent (no
  `--effort none` ever sent).
- Route declaring `supported_efforts: [none, high]`: `none` kept for
  provenance, dropped from the accepted set; `high` is ok.
- Route declaring `supported_efforts: []`: every level unsupported, not
  unverified.
- Metadata checked-at in the future: age is not printed as a negative
  number.
- `supported_efforts_checked_at` without a list: no stale note.
- A provider entry that cannot be read: `unverified` with a "could not be
  read" note, and a launch that fails with one line.
- Ambient `CLAUDE_CODE_EFFORT_LEVEL` and Haiku: the variable remains; no
  note may claim PM passes it as `--effort`.
- Provider `unset_env` already listing `CLAUDE_CODE_EFFORT_LEVEL` while PM
  sets an effort: the shell command unsets it once.
- Provider `env:` assignment with a level different from the PM level:
  the assignment wins in the process, and no note claims otherwise.
- Role with no `provider:` setting but a providers.yaml `default:` entry:
  its `env:` assignment is reported with source `provider <name> env`; its
  `supported_efforts` is not applied to the unrouted role (deliberate
  limitation — the launch warning still fires).
- Provider `effort:` default that its own `supported_efforts` excludes:
  the role table and launch mark it unsupported; `pm provider show` alone
  does not call it out.
- `pm provider edit --clear model` (rather than `--model new`) does not
  emit the stale-metadata warning; the list stays in the file.
- Concurrent edits to providers.yaml and to project.yaml.

## 4. Pass / Fail criteria

**Pass** when every Then above is observable on the user's surface (CLI
output, TUI render, project.yaml/providers.yaml content, launched argv and
environment, session log), the five-level vocabulary is accepted and a
`none`/unknown level is rejected, unsupported or unverified levels are
never displayed as confirmed, the launch never runs a different level than
the one PM reports without saying so, and existing precedence / fake-claude
/ no-effort flows are unchanged.

**Fail** on any of: a level the CLI accepts rejected by PM; `none` written
into `--effort`; a bare level shown as verified when the route rejects it;
`CLAUDE_CODE_EFFORT_LEVEL` overriding `--effort` silently while the display
claims PM's level; a provider `env:` assignment silently dropped; a broken
provider entry guessed around instead of reported; `supported_efforts`
values outside the Claude vocabulary sent to `--effort`; a concurrent edit
losing another's field or corrupting either YAML file; a crash on a
malformed entry; secrets printed.

## 5. Ambiguities (resolved)

- **Ambient-only effort is marked `*`.**  With no PM setting and
  `CLAUDE_CODE_EFFORT_LEVEL=xhigh`, every role shows `xhigh *` and the note
  says the variable selected the effort.  Read as "not confirmed by pm",
  which is accurate; not a failure.
- **Default-provider `supported_efforts` is not applied to unrouted roles.**
  The implementation deliberately ties `supported_efforts` to the
  explicitly selected provider; the launch warning still names the default
  provider's list.  QA reports the asymmetry as an observation, not a
  failure.
- **`pm provider show` does not flag a provider `effort:` that its own
  `supported_efforts` excludes.**  The conflict is surfaced where it
  matters (role table, set-time warning, launch warning).  Reported as an
  observation.
- **`--clear model` skips the stale-metadata warning.**  The warning is
  specified for a model *change*; `--clear model` leaves the list in the
  file without one.  Reported as an observation.
- **Case sensitivity.**  The ambient variable is lowercased before
  matching; `PM_EFFORT` is matched exactly.  `PM_EFFORT=XHIGH` is noted as
  invalid.  Not specified either way; report only if it surprises.
