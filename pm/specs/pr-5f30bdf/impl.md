# pr-5f30bdf — Implementation spec: providers.yaml lock hardening + Textual floor

Found at sign-off of #249 (`pr-592e4bd`), non-blocking.  Three independent
hardening items, all user-approved and bounded to provider editing and the
model popup.  No behaviour changes to provider resolution, routing, model
settings, credentials, or `project.yaml`.

Base: `origin/master` @ `c1fcecc5` (branch already contains it).  PR #283
(`refs/pull/283/head` @ `21da65cd`) is **open, not merged**; it adds
`supported_efforts` metadata to the same files.  Nothing here renames or
removes anything it introduces, and it is not integrated (see A5).

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
- **A5 — PR #283.**  Open/unmerged at spec time; not integrated.  Its
  additions (`supported_efforts` fields/options) do not overlap with the
  names or interfaces touched here, so both can land independently.

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

## Tests to add/update

In `tests/test_providers.py`:

1. `set_default_provider` rejects a missing name and leaves the file
   unchanged; accepts `claude`.
2. The existence check runs under the lock (assert the lock is held while
   `load_providers_for_edit` is called) and a concurrent removal between
   CLI pre-check and locked update cannot resurrect `default: X`.
3. `providers_lock` times out with `ProvidersLockTimeout` when another fd
   holds the flock, and releases/closes its own fd.
4. An unwritable `pm_home` makes `providers_lock` raise
   `ProvidersWriteError` with the path, and `pm provider default claude`
   prints one `Error:` line with exit 1 (no traceback).
5. Update the failed-`os.replace` test to expect `ProvidersWriteError`
   (original kept, temp cleaned).

Existing provider permission/roundtrip/CLI tests must keep passing.
