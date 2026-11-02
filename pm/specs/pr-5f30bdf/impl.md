# pr-5f30bdf — Implementation spec: providers.yaml lock hardening + Textual floor

Found at sign-off of #249 (`pr-592e4bd`), non-blocking.  Three independent
hardening items, all user-approved and bounded to provider editing and the
model popup.  No behaviour changes to provider resolution, routing, model
settings, credentials, or `project.yaml`.

Base: `origin/master` @ `c1fcecc5` (branch already contains it).  PR #283
(`pr-5ec411c`) adds `supported_efforts` metadata to the same files; it was
open at spec time and has since **merged** to master as `b8576981`.  Nothing
here renames or removes anything it introduces.  The branch does not merge
master itself (sign-off integrates the latest base); a merge preview is
clean and the merged tree passes the provider/router/model tests (see A5).

## Current state (grounded)

- `pm_core/providers.py:572-586` — `providers_lock()` opens
  `~/.pm/providers.yaml.lock` and calls `fcntl.flock(..., LOCK_EX)` with no
  timeout.  `pm_home()` (`pm_core/paths.py:27-31`) itself does
  `mkdir(parents=True, exist_ok=True)`, and `open(..., "a")` can raise
  `OSError`; both escape as a traceback from every `pm provider
  add|edit|remove|default`.
- `pm_core/providers.py:589-619` — `save_providers()` writes a private
  `mkstemp` file at 0600 and `os.replace`s it, cleaning the temp on any
  `BaseException`.  `OSError` from `mkstemp`/`chmod`/`replace` propagates
  unchanged (one existing test asserts `pytest.raises(OSError)`).
- `pm_core/providers.py:722-730` — `set_default_provider(name)` takes
  `providers_lock()`, re-reads with `load_providers_for_edit()`, sets
  `default`, saves.  It does **not** check that `name` still exists.
- `pm_core/cli/provider.py:407-427` — `provider_default` validates `name`
  against a read **outside** the lock, then calls `set_default_provider()`,
  which re-reads under the lock.  A concurrent `pm provider remove X`
  between the two reads leaves `default: X` pointing at a deleted provider.
- `pm_core/cli/provider.py:111-120` — `_load_for_edit()` already turns
  `ProvidersFileError` (unreadable/invalid YAML) into one `Error:` line and
  exit 1.  It does not catch `OSError`.
- `pm_core/cli/provider.py:216-403` — `add`/`edit`/`remove` each wrap their
  read-modify-write in `providers_lock()` with no error handling around the
  lock acquisition or `save_providers`.
- `pm_core/tui/model_screen.py:194-196` — `_resize()` lazily imports
  `textual.markup.to_content` to measure markup-free row widths.  Verified
  present (with `textual.content.Content`) in textual **2.0.1** and in the
  installed 8.2.7; absent from the declared floor `textual>=0.40`.  It is
  also present in `2.0.0`, but there `to_content` mis-parses an escaped
  `\[...]`, which breaks the popup's width measurement (see R3).
- `pyproject.toml:13` declares `textual>=0.40`; `Dockerfile:150` repeats the
  same floor in its pre-installed dependency list.  No other declaration of
  the floor exists (`install.sh` installs the project, so it follows
  `pyproject.toml`).
- Tests already use 2.x APIs (`tests/test_pr_view_command_text.py:68`,
  `tests/test_review_launch_retry.py:2417` import `textual.content.Content`),
  so the real floor is already 2.x.

## Requirements

### R1 — Re-check the default provider under the lock
Move the existence check into `set_default_provider()` so it runs on the
config read inside `providers_lock()`:

- `name == "claude"` (built-in) is always allowed.
- Otherwise `name` must be a key of the `providers` mapping in the config
  read **under the lock**; if not, raise `ProviderNotFoundError` with the
  existing user-facing text (`Provider 'X' not found. Add it first with
  'pm provider add'.`) and write nothing.
- `provider_default` drops its outside-the-lock pre-check and catches
  `ProviderNotFoundError` to print `Error: <msg>` and exit 1 (so the
  generic CLI handler's model-setting hint is not appended).
- Behaviour parity with today: presence is required; entry validity
  (`_entry_problem`) is not re-classified here (see A4).

### R2 — Bound the lock wait and make write failures one `Error:` line
In `pm_core/providers.py`:

- Add `PROVIDERS_LOCK_TIMEOUT = 5.0` (module constant, documented).
- `providers_lock(timeout: float | None = None)` acquires with
  `LOCK_EX | LOCK_NB` in a poll loop (50 ms) against a `time.monotonic()`
  deadline; on contention past the deadline raise `ProvidersLockTimeout`
  (subclass of `ProvidersFileError`) naming the lock path, the timeout and
  the likely cause (another `pm provider` command still running).
- Wrap `_providers_path()` / `mkdir` / `open(lock)` failures in
  `ProvidersWriteError` (subclass of `ProvidersFileError`) with the path
  and `strerror`, telling the user to check that `~/.pm` is writable.
- Always close the lock fd and release the lock on every path (including
  timeout and exceptions inside the `with` body); do not leave an fd open.
- `save_providers()` keeps its 0600 `mkstemp` + `os.replace` mechanism and
  temp cleanup; convert `OSError` raised there into `ProvidersWriteError`
  with the target path and reason.  Non-`OSError` exceptions are re-raised
  unchanged after cleanup.
- `ProvidersFileError` remains the common base, so `_load_for_edit()`'s
  existing handling is unchanged.

In `pm_core/cli/provider.py`:

- Add a small `_write_errors()` context manager that converts
  `ProvidersFileError` (hence lock timeout / write errors) and any stray
  `OSError` into exactly one `Error: ...` line on stderr and `SystemExit(1)`.
- Use it around the write sections of `add`, `edit`, `remove`, and around
  `set_default_provider` in `default`.  `SystemExit` raised by existing
  checks/`_load_for_edit` passes through untouched (no double printing).
  In `add`, also wrap the early `_load_for_edit()` (the fail-before-prompt
  read): `load_providers_for_edit()` reaches `pm_home()`, whose `mkdir` can
  raise a raw `OSError` before the lock is ever taken, and that read is the
  reachable path for the CLI's `pm_home` failure test.
- Preserve the current success messages and exit codes.

### R3 — Declare the Textual floor the code actually needs
Raise the declared floor from `textual>=0.40` to `textual>=2.0.1` in
`pyproject.toml` and in the `Dockerfile`'s pre-install list.  `2.0.1` is
the minimum verified to provide both `textual.markup.to_content` and
`textual.content.Content`, which the code and tests use, *and* to render
the popup correctly: `2.0.0` has `to_content` but it drops the closing `]`
of an escaped `\[...]` (review-loop i3), so a `[OK]` status line measures
two cells short, the box is sized too narrow and the column is clipped —
`tests/test_model_settings.py::test_tui_project_view_shows_ok_route_status`
fails at `2.0.0` and passes at `2.0.1`.  Keep the lazy import in
`model_screen.py` (it is only needed when sizing the popup); no
compatibility shim is needed once the floor is honest.

Incidental (review-loop i2): the Dockerfile pre-install list — whose comment
says keep it in sync with `[project.dependencies]` — was also missing
`markdown>=3.5` (added to `pyproject.toml` by `fb988d1f`), so containers
could not run `pm md-render` (sign-off report embedding) without an
`ImportError`.  It is added there too.

### R4 — The TUI must work at the declared floor (QA s5 follow-up)
Declaring `textual>=2.0.1` (R3) makes 2.0.1 a *supported* install, and
there `App.query_one` searches only the **active** screen's DOM.  With a
modal screen pushed (the model popup, `o`), the default screen's
`#command-bar` is unreachable, so `App.query_one("#command-bar", ...)`
raised `NoMatches` from `App.on_key` — and a background reload could hit
`_command_bar_in_use()` the same way.  QA s5: Esc in the model popup
killed the TUI at 2.0.1.

- `ProjectManagerApp._command_bar()` returns the bar, or `None` when the
  query raises `NoMatches`, and every App-level lookup goes through it
  (six sites: `on_key`, `check_action`, `_command_bar_in_use`,
  `_drain_command_queue`'s refocus, `action_focus_command`,
  `action_unfocus_command`).
- "No command bar" means "not focused / not in use": App-level prefix keys
  stay out of the way (the `len(screen_stack) > 1` guard already returns),
  a background reload never crashes, and nothing silently refocuses the
  bar under a modal.
- Regression test `tests/test_view_focus_command_bar.py::
  test_modal_on_top_treats_missing_command_bar_as_idle` pushes a
  `ModalScreen` over a real command bar, asserts `_command_bar_in_use()`
  is `False`, and calls `App.on_key` with a `z` event (the pre-fix crash)
  asserting it neither raises nor swallows the key.

Verified by QA at 2.0.1 (live TUI closes the popup cleanly on Esc; full
suite 5461 passed / 1 skipped) and at 8.2.7/8.2.8.

## Implicit requirements

- **No credential/settings mutation in tests.**  Every new test patches
  `pm_core.providers.pm_home` (or uses `CliRunner` with the same patch) to a
  temp dir; no test reads or writes the real `~/.pm`.
- **Existing atomic-save protections stay.**  0600 mode, private temp file,
  inode swap, temp cleanup, symlink replacement semantics.
- **One error line, no traceback.**  All new failure paths end in
  `Error: ...` + exit 1 from the CLI; library callers get typed exceptions.
- **No behaviour change for successful edits.**  Same YAML output, same
  messages (`Default provider set to 'X'`, `Removed provider 'X'`, etc.).
- **No lost updates.**  Every write still re-reads under the lock; the
  default re-check must use that same locked read, not a second read.
- **Lock users stay compatible.**  `providers_lock()` remains a context
  manager with an optional timeout; existing no-argument callers behave
  the same apart from being bounded.
- **Library compatibility.**  `set_default_provider(name)` keeps its
  signature; it now raises `ProviderNotFoundError` for a missing name.
- **Textual floor is consistent.**  `pyproject.toml` and `Dockerfile`
  agree; no other floor declaration exists.

## Ambiguities (resolved)

- **A1 — timeout value.**  Not specified.  Resolved: 5.0 s module constant
  `PROVIDERS_LOCK_TIMEOUT`, overridable per call for tests.  Provider edits
  hold the lock only for a re-read + write (connectivity checks happen
  outside it), so 5 s is ample and keeps a stuck holder from hanging a
  shell indefinitely.
- **A2 — exception type.**  Resolved: `ProvidersLockTimeout` and
  `ProvidersWriteError`, both subclasses of the existing
  `ProvidersFileError`, so CLI handling and `_load_for_edit()` stay
  coherent.  The one existing test that asserts `pytest.raises(OSError)`
  for a failed `os.replace` is updated to the new type; it still asserts
  the original file survives and the temp is cleaned.
- **A3 — pin vs. guard.**  Resolved: pin `textual>=2.0.1`.  The codebase
  already imports `textual.content` in tests, and `2.0.1` was verified to
  contain both APIs and to pass the popup tests; `2.0.0` has both APIs but
  clips escaped `[OK]` status text (R3).  A guard would only hide a stale
  environment the project does not support.
- **A4 — validate entry contents in `set_default_provider`?**  Resolved:
  no.  The stated bug is the existence race; adding validation would change
  behaviour for hand-edited invalid entries and is out of scope.
- **A5 — PR #283.**  Merged to master as `b8576981` while this PR was in
  review.  Its additions (`supported_efforts` fields/options, and the
  `model_screen` effort cycle/legend changes) do not overlap with the names
  or interfaces touched here: master's `set_default_provider`,
  `provider_default`, `providers_lock`, `save_providers`, and the popup's
  `to_content` sizing are unchanged by it.  A merge preview of the branch
  onto `b8576981` is clean, and the merged tree passes
  `tests/test_providers.py tests/test_router_route.py
  tests/test_model_settings.py` (418 passed), so sign-off can integrate the
  base without rework.  This branch does not merge master itself.
  Sign-off (2026-11-02): master had moved to `5b352d16` (adds #293 /
  `pr-3d3b3ce`).  The integration check conflicts only in `pm/project.yaml`
  (registry; resolvable with `store.merge_3way(base, ours=master,
  theirs=branch)` -- 586 unique ids, this PR's notes intact); every code
  file auto-merges, and the trial-merged candidate passes the full suite at
  textual 2.0.1 (5554 passed / 1 skipped) and 8.2.7 (5553 passed / 1
  skipped, plus one load-related `test_push_proxy` lifecycle flake that
  passes 3/3 when re-run alone).

No **[UNRESOLVED]** ambiguities.

## Edge cases

- `set_default_provider("claude")` on a missing `providers.yaml` still
  creates/updates the file with `default: claude`.
- Interleavings: default-then-remove resets the default to `claude` in
  `remove`; remove-then-default now fails cleanly and writes nothing.
- `timeout=0` means one non-blocking attempt (used by tests); a negative
  timeout behaves the same.
- Lock file exists but is unwritable (e.g. owned by another user) → one
  `Error:` line naming the path, not a traceback.
- `~/.pm` exists but its lock file or temp file cannot be written → one
  `Error:` line naming the path, not a traceback.  A *wholly* unwritable
  `~/.pm` still tracebacks earlier, at import time, in
  `configure_logger`/`debug_dir` (`pm_core/paths.py`) before any provider
  code runs: a pre-existing, command-wide defect outside this PR's scope,
  filed as `pr-78e8ebe`.
- `save_providers` fails mid-write (disk full, `os.replace` failure) →
  temp is removed, the old file is untouched, `ProvidersWriteError` is
  raised and surfaced as one line.
- Invalid/unreadable `providers.yaml` still takes the existing
  `ProvidersFileError` path from `_load_for_edit()` and is never
  overwritten.
- Nested `providers_lock()` in one process is not supported (separate
  `open()` → separate flock description); it now fails with the timeout
  instead of hanging forever.
- A user on textual 1.x who did not reinstall keeps the old behaviour
  (lazy `ImportError` on opening the popup); the declared floor and the
  Docker image now prevent new installs from landing there.  A user on
  textual 2.0.0 gets the popup but with a clipped status column (R3), so
  the floor names 2.0.1.
- A modal screen is on top of the default screen (the model popup): every
  App-level command-bar lookup returns `None` instead of raising
  `NoMatches`, so Esc and prefix keys keep working and a background reload
  no longer crashes at the textual floor (R4).  The reload itself is still
  *dropped* at textual 2.x while a modal is up (sign-off probe): its other
  default-screen queries (`#tech-tree` in `_update_status_bar` /
  `_update_display`) raise `NoMatches` after `_data` is replaced, so the
  tree stays stale and `auto_start.on_state_loaded` is skipped for that
  reload; the 5-minute sync tick logs `Sync error: No nodes match
  '#tech-tree'`.  textual >= 3.0.0 lets `App.query_one` reach the default
  screen and is unaffected; master is worse at 2.x (any key in the popup
  crashes).  Out of this PR's scope -- a follow-up (raise the floor to
  `textual>=3.0` or make the reload's default-screen queries screen-aware)
  was recommended at sign-off.

## Tests to add/update

In `tests/test_providers.py`:

1. `set_default_provider` rejects a missing name and leaves the file
   unchanged; accepts `claude`; accepts a configured provider and writes
   `default: <name>` (library and `pm provider default` CLI success paths).
2. The existence check runs under the lock (assert the lock is held while
   `load_providers_for_edit` is called) and a concurrent removal between
   CLI pre-check and locked update cannot resurrect `default: X`.
3. `providers_lock` times out with `ProvidersLockTimeout` when another fd
   holds the flock, releases the lock after an exception in the body, and
   closes its own lock fd on the timeout path (a spy on `open` asserts
   `closed`).
4. An unwritable `pm_home` makes `providers_lock` raise
   `ProvidersWriteError` with the path, and `pm provider default claude`
   prints one `Error:` line with exit 1 (no traceback).  A `pm_home()`
   failure on `pm provider add` and a held lock on `pm provider default`
   are covered the same way.
5. Update the failed-`os.replace` test to expect `ProvidersWriteError`
   (original kept, temp cleaned); add the `mkstemp`-failure branch
   (typed error naming the target, file untouched, no temp left).

In `tests/test_view_focus_command_bar.py`:

6. A modal screen on top of the command bar: `_command_bar_in_use()` is
   `False`, and `App.on_key` neither raises `NoMatches` nor handles the
   key — the pre-fix crash QA s5 found at the textual floor (R4).

Existing provider permission/roundtrip/CLI tests must keep passing.
