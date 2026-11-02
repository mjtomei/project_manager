# QA Spec for PR pr-5f30bdf — providers.yaml lock hardening + Textual floor

Found at sign-off of #249, non-blocking. Three bounded items: (1) the default
provider is re-checked against the config read *under* the `providers.yaml`
edit lock, so `pm provider default X` cannot race `pm provider remove X`;
(2) the flock wait is bounded (`PROVIDERS_LOCK_TIMEOUT = 5.0`) and write
failures (`~/.pm` / lock / temp / target unwritable) surface as one
`Error:` line instead of a traceback; (3) the declared Textual floor is
`textual>=2.0.1` (pyproject + Dockerfile) because `model_screen.py` imports
`textual.markup.to_content` and 2.0.0 mis-measures escaped `\[...]` text.
The Dockerfile's pre-install list also gained the already-declared
`markdown>=3.5` (incidental fix).

Everything here is exercised through the CLI (`pm provider …`), the TUI model
popup (`o`, `p`), and package installation — never by importing internals.

## Requirements

### R1 — Set the default to a configured provider
**Given** two providers are configured (`alpha`, `beta`) and the default is
`claude`,
**When** the user runs `pm provider default beta`,
**Then** the command prints `Default provider set to 'beta'`, exits 0,
`pm provider list` marks `beta` with `(default)`, and `~/.pm/providers.yaml`
reads `default: beta` with both provider entries unchanged.

### R2 — Refuse a default that is not configured
**Given** only `alpha` is configured,
**When** the user runs `pm provider default ghost`,
**Then** stderr carries exactly one line
`Error: Provider 'ghost' not found. Add it first with 'pm provider add'.`,
the exit status is 1, there is no traceback, and `~/.pm/providers.yaml` is
byte-for-byte unchanged (no new `default:` key, no rewrite).

### R3 — The built-in `claude` is always an acceptable default
**Given** `~/.pm/providers.yaml` is missing, or has an empty/commented-out
`providers` block,
**When** the user runs `pm provider default claude`,
**Then** the command succeeds, prints `Default provider set to 'claude'`,
and `pm provider list` shows `claude` with `(default)`.

### R4 — `default X` racing `remove X` never leaves a dangling default
**Given** provider `x` is configured and is (or is about to become) the
default,
**When** `pm provider default x` and `pm provider remove x` are run as two
concurrent processes (repeated over many rounds),
**Then** after every round the file is valid YAML and coherent:
- either `x` is gone and `default` is `claude` (removal won, or removal reset
  the default it had just set), or
- `default` names a provider that still exists;
- **never** `default: x` while `x` is absent from `providers`;
- the losing command reports its clean message (`Error: Provider 'x' not
  found. Add it first with 'pm provider add'.` for `default`, or
  `Provider 'x' not found.` for `remove`), never a traceback;
- `pm provider list` still shows a `(default)` marker on some listed
  provider, and `pm provider test` (no name) resolves to that provider.

### R5 — Concurrent edits are serialized, not lost
**Given** two users/terminals acting on the same `~/.pm/providers.yaml`,
**When** two provider edits run at the same time (e.g. `pm provider add one`
and `pm provider add two`, or `add` vs `edit` of an existing entry),
**Then** both commands report success, the final file contains both changes,
it is valid YAML, and no `.providers.yaml.pm-*` temp files are left in
`~/.pm`.

### R6 — A stuck lock holder no longer blocks edits forever
**Given** another process holds `~/.pm/providers.yaml.lock` (a stand-in for
a hung `pm provider` command),
**When** the user runs any provider write command (`add`, `edit`, `remove`,
`default`),
**Then** the command waits about five seconds, then exits 1 printing exactly
one line
`Error: timed out after 5s waiting for the providers.yaml edit lock (<lock path>); another 'pm provider' command may still be running. Wait for it to finish, then retry.`,
with no traceback and `~/.pm/providers.yaml` unchanged; once the holder
exits, the same command retried succeeds normally.

### R7 — A briefly held lock is waited out, not failed
**Given** another process holds the lock but releases it after ~2 seconds,
**When** the user runs a provider write command,
**Then** the command waits, succeeds, and prints its normal success message
(no timeout error).

### R8 — Reads never block on the lock
**Given** another process holds the write lock,
**When** the user runs `pm provider list`, `pm provider show <name>`, or
`pm provider test <name>`,
**Then** each returns immediately with its normal output (no five-second
stall, no error) — the lock only gates edits.

### R9 — An unwritable state is one `Error:` line, not a traceback
**Given** `~/.pm` is writable but `~/.pm/providers.yaml.lock` is read-only
(the reachable providers-specific unwritable case),
**When** the user runs `pm provider add|edit|remove|default`,
**Then** each exits 1 with exactly one stderr line of the form
`Error: cannot write <path>: <OS reason> (pm keeps providers.yaml in ~/.pm;
check that it is writable)`, no traceback, and `~/.pm/providers.yaml`
unchanged.

### R10 — A failed save keeps the old file and leaves no temp litter
**Given** a configured `providers.yaml` and a write that fails part-way
(read-only lock file, unwritable temp/target, or `os.replace` failure),
**When** the user runs a provider write command,
**Then** `~/.pm/providers.yaml` still holds the previous content, no
`.providers.yaml.pm-*` file remains in `~/.pm`, and the failure is the single
`Error:` line from R9.

### R11 — A malformed `providers.yaml` is still refused, never overwritten
**Given** `~/.pm/providers.yaml` is not valid YAML (or its `providers` block
is not a mapping),
**When** the user runs any provider write command,
**Then** one `Error:` line says the file `cannot be changed` (naming the
file), exit 1, no traceback, and the file is byte-for-byte unchanged.

### R12 — Credential-file protections are preserved
**Given** `~/.pm/providers.yaml` exists at mode `0600` with several entries,
**When** the user sets the default or edits one entry,
**Then** the file is still mode `0600`, every other entry is preserved, and
the write is an atomic replace (no reader ever sees a truncated or empty
file).

### R13 — The model popup renders providers correctly on the declared floor
**Given** a clean install of this checkout (`pip install -e .` in a fresh
venv, so the declared `textual>=2.0.1` is what gets installed) and a project
with a configured provider plus a `type: router` provider,
**When** the user opens the TUI and opens the model settings popup and
switches it to the project view,
**Then**:
- the popup opens with no `ImportError`;
- the providers block lists each provider, with `(default)` on the current
  default and `(default)` nowhere else;
- a router's route status renders in full — either `[OK]` or
  `[UNAVAILABLE: …]` with its closing bracket — and the box is wide enough
  that no column is clipped at the right edge;
- pressing Esc closes the popup and leaves the TUI running (2.0.1's
  `App.query_one` sees only the active screen, so App-level command-bar
  lookups must not raise while the popup is up — QA s5);
- keys the popup does not use (app-level `r` refresh and `z`/`w`/`y`
  prefixes) and a background state reload while the popup is open must not
  crash the TUI or take the popup's focus (`_command_bar()` returns None
  when the command bar is unreachable — QA s5 / ff85d13a). At Textual 2.x a
  background reload's default-screen queries are still dropped while a modal
  is open, so the reload does not apply (Esc then `r` shows the change).
  That gap is filed as **pr-3199f44** and is a follow-up, not a failure of
  this PR: record it, do not fail the scenario for it;
- the installed `textual` version satisfies `>=2.0.1`.

### R14 — The popup reflects a default changed elsewhere
**Given** the model popup is open in the TUI and the default is `alpha`,
**When** the user changes the default to `beta` from another terminal
(`pm provider default beta`) and reopens the popup,
**Then** the `(default)` marker is now on `beta`.

### R15 — Declared dependencies are installable and sufficient
**Given** a clean environment,
**When** the user installs this checkout and runs `pm md-render` on a
Markdown file, and (when practical) builds/runs the shipped container base
image from the repo `Dockerfile` and repeats both the `md-render` call and
the model popup there,
**Then** `pm md-render` emits body-only HTML with no `ImportError`, the
popup opens, and the installed `textual` satisfies `>=2.0.1` — the
Dockerfile pre-install list matches `[project.dependencies]`.

### R16 — The merged #283 provider metadata still round-trips
The branch merged master@5b352d16 (which brought #283's provider/model
configuration surfaces). This PR does not own #283's semantics; this
requirement only guards the integration:
**Given** a hand-written `providers.yaml` in the shape master produces, an
entry carrying `supported_efforts`, `supported_efforts_source`,
`supported_efforts_checked_at`, an effort assignment in `env`, and the
router fields,
**When** the user runs `pm provider list`, `pm provider show <name>`,
`pm provider edit <name> --model <new>`, and `pm provider edit <name>
--supported-efforts … --supported-efforts-checked-at …`,
**Then** the newer fields render in `list`/`show`, the other fields survive
an edit, changing only the model prints the stale-metadata warning without
dropping the declared list, and an invalid `--supported-efforts-checked-at`
is refused with one `Error:` line and an unchanged file.

## Setup

1. Use an **isolated HOME / `~/.pm`** for every scenario (e.g.
   `HOME=$SCRATCH/home`), so no real provider credentials or settings are
   read or written. Never touch the live user `~/.pm`.
2. Install pm from the PR checkout into a venv (`python3 -m venv` +
   `pip install -e .`), or `./install.sh --local` where the image has no pm.
   The container sets `PYTHONPATH=/opt/pm-src`; export `PYTHONPATH` to the
   checkout and confirm with `pm which`.
3. Provider entries can be created without network access using
   `pm provider add <name> --api-base http://localhost:<port> --model <m>
   --skip-check` (or `--type router`, which skips the connectivity check
   automatically). No real LLM endpoint is needed. Current master already
   includes #283's router fields (`launcher`, `remedy`, `classifier_model`,
   `unset_env`, `probe_models`, `supported_efforts`,
   `supported_efforts_source`, `supported_efforts_checked_at`, and an
   effort assignment in `env`); a hand-written `providers.yaml` from an
   older pm is a realistic starting state and those fields must survive.
4. For concurrency, run the two actors as separate shells/panes (tmux or
   background jobs) against the same isolated HOME — that is the real
   contention surface (`~/.pm/providers.yaml` + `providers.yaml.lock`).
5. A "stuck lock holder" is simulated with an independent process holding
   the flock on `~/.pm/providers.yaml.lock` (e.g.
   `flock ~/.pm/providers.yaml.lock sleep 30`) — it stands in for a hung
   `pm provider` command and holds exactly the same resource.
6. For TUI scenarios, create a throwaway project (`pm init --backend local
   --no-import`, a PR or two), start the pm session, and drive it with
   `pm tui send`; see `pm/qa/instructions/tui-manual-test.md`.
7. Hand-written `providers.yaml` fixtures must be indented as a YAML
   mapping (`providers:` then nested `  alpha:` then its fields). A
   column-0 `providers:` followed by a column-0 `alpha:` is a null
   `providers` block: pm lists only the built-in `claude` and
   `pm provider default alpha` reports `Provider 'alpha' not found`
   (observed in QA S4).

## Edge Cases

1. **Missing `providers.yaml`** — Given `~/.pm/providers.yaml` does not
   exist, When the user sets the default to `claude`, Then the command
   succeeds and creates/updates the file with `default: claude`.
2. **Empty providers block** — Given `providers.yaml` has `providers: {}`
   or every entry commented out, When the user sets the default to a name
   that is not there, Then the command refuses with the R2 error and writes
   nothing.
3. **Present-but-invalid entry** — Given `providers.yaml` has `bad: "oops"`
   (listed by `pm provider list` as `INVALID ENTRY`), When the user runs
   `pm provider default bad`, Then the name is accepted (the check is
   presence, not validity, matching pre-existing behavior) and the file gets
   `default: bad`; `pm provider list` then shows no `(default)` marker on a
   usable provider — this is existing behaviour and must not be reported as
   a regression of this PR, but the outcome should be recorded.
4. **Remove the current default** — Given `alpha` is the default, When the
   user removes `alpha`, Then it succeeds and the default resets to
   `claude` (existing behavior preserved).
5. **Remove a name that is not configured** — Given no such provider, When
   the user runs `pm provider remove ghost`, Then it exits 1 with
   `Provider 'ghost' not found.` and the file is unchanged.
6. **Two defaults at once** — Given `alpha` and `beta`, When two `pm
   provider default` commands run concurrently, Then both may report
   success, the file stays valid, and exactly one of them is `default`.
7. **Reader during a write** — Given one process is writing, When another
   repeatedly runs `pm provider list`, Then it never observes an empty or
   partial file (atomic replace).
8. **Lock file already present but stale** — Given a leftover
   `providers.yaml.lock` with no holder, When the user edits, Then the edit
   succeeds immediately (the lock is advisory and released by close).
9. **Lock fd hygiene** — Given repeated timeouts, When the user retries
   after the holder exits, Then the retry succeeds (no leaked lock state
   blocks it).
10. **`pm provider test` with no name** — Given the default is a configured
    local provider, When the user runs `pm provider test` with no name,
    Then it names that provider as the one under test — the observable
    proof that the default is the intended one.
11. **Textual 2.0.0-style clipping** — Given the popup renders a status
    with escaped brackets (`[OK]`, `[UNAVAILABLE: …]`), When the box is
    sized, Then the full bracketed text is visible and the rightmost column
    is not cut off (the failure mode that motivated `>=2.0.1`).
12. **`pm provider add` with an unreadable `~/.pm`** — a *wholly* unwritable
    `~/.pm` still tracebacks at import time in
    `pm_core/paths.py:configure_logger` before any provider code runs. This
    is a pre-existing, command-wide defect outside this PR (filed as
    `pr-78e8ebe`); record it but do not fail this PR for it.

## Pass/Fail Criteria

**Pass**
- Every `Then` above is observable as described: exact success/error text,
  exit statuses, file contents, mode `0600`, absence of tracebacks and of
  temp-file litter.
- Under concurrent `default X` / `remove X` runs, no round leaves
  `default: X` with `X` absent, and the file always parses.
- Write failures (held lock past timeout, unwritable lock/temp/target,
  malformed YAML) each produce exactly one `Error:` line and leave
  `providers.yaml` unchanged.
- Reads (`list`, `show`, `test`) return immediately while the lock is held.
- In the TUI, the model popup opens without `ImportError` on a clean
  install, shows `(default)` on the right provider, and renders bracketed
  route statuses in full without clipping.
- A clean install resolves `textual>=2.0.1` and `pm md-render` works.

**Fail**
- A traceback from any provider write command in the reachable failure
  modes (held lock, read-only lock file, malformed YAML).
- Any round of the default/remove race ending with a default naming a
  provider that is not configured.
- An edit blocked indefinitely, or a lock timeout that still writes the
  file.
- Lost updates: a concurrent edit that disappears from the file, or temp
  files left behind.
- `providers.yaml` rewritten (or its mode changed from `0600`) after a
  refused or failed command.
- The popup raising `ImportError`, or clipping the status column / right
  edge, on a clean install.
- `pm md-render` failing with `ImportError` in a clean install (or in the
  shipped container image).

## Run notes

- Scenarios 1-9 have run and are locked. Their verdicts: S1-S4 PASS (S4
  after a prompt indentation fix), S5 NEEDS_WORK (Esc crash at Textual
  2.0.1, fixed in ff85d13a), S6 PASS, S7 PASS (the floor popup re-run,
  including Esc, app-level keys and the background reload), S8 PASS
  (a router provider from an earlier pm survives list/show/edit/test/
  default/remove), S9 PASS (an interrupted/crashed edit leaves the next one
  usable). Do not rewrite or re-emit those scenarios; new plans start at
  scenario 10.
- The merge is now done: master@5b352d16 was merged in commit 44dbc92a
  (every code file auto-merged; only the `pm/project.yaml` registry needed
  `store.merge_3way`). The merged tree is what QA now tests — #283's
  provider metadata surfaces (`supported_efforts`, effort env, router
  fields) are present alongside this PR's hardening (R16).
- The Textual 2.x gap where a background reload is dropped while a modal is
  open is filed as **pr-3199f44**; record it, do not fail this PR for it
  (see R13).

## Ambiguities

1. **Wholly unwritable `~/.pm` traceback** — **[RESOLVED]** out of scope.
   `chmod 500 ~/.pm` fails earlier at import in `configure_logger` /
   `debug_dir` (pre-existing, command-wide; filed as `pr-78e8ebe`). The
   reachable providers-specific case is a read-only
   `~/.pm/providers.yaml.lock`, which must produce one `Error:` line. QA
   records the pre-existing traceback but does not fail this PR for it.
2. **Timeout value** — **[RESOLVED]** 5.0 s module constant; tests may pass
   a shorter timeout. Scenario checks allow "about five seconds" (roughly
   4–8 s wall clock).
3. **Is an invalid-but-present entry accepted as the default?** —
   **[RESOLVED]** Yes: the check is presence in the `providers` mapping, not
   entry validity (documented in the impl spec as A4). Changing it would
   alter behaviour for hand-edited files and is out of scope.
4. **Which surface shows the default** — **[RESOLVED]** `pm provider list`'s
   `(default)` marker, `pm provider test` with no name, and the TUI popup's
   `(default)` marker. There is no `pm provider show`-only "current default"
   line; scenarios use the three surfaces above.
5. **Exit statuses** — **[RESOLVED]** success 0; refusals and write failures
   1 (matching the existing `SystemExit(1)` handling).
6. **Verifying the Dockerfile change** — **[RESOLVED]** A full base-image
   build may be impractical inside a scenario container; the primary check
   is a clean `pip install -e .` (which the Dockerfile list mirrors) plus
   `pm md-render`. If a container build is feasible, repeat `pm md-render`
   and the popup inside the built image; if not, record the fallback in the
   capture manifest rather than failing.
7. **`pm provider remove` of a missing name lacks the `Error:` prefix** —
   **[RESOLVED]** pre-existing wording, deliberately unchanged by this PR;
   scenarios assert the message text but do not treat the missing prefix as
   a failure.

No **[UNRESOLVED]** ambiguities.
