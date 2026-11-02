# Implementation Spec — pr-294e53d

Bug: `providers.yaml` saves literal API keys with group/world-readable permissions.

## 1. Requirements (grounded in the codebase)

### R1 — New `providers.yaml` is created owner-only (0600) under any umask

- Writer: `save_providers(data)` — `pm_core/providers.py:158`.
- Target path: `_providers_path()` → `pm_home() / "providers.yaml"`
  (`pm_core/providers.py:137-139`), i.e. `~/.pm/providers.yaml`.
- Before this change the function was:
  ```python
  path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))
  ```
  `Path.write_text` opens with `O_CREAT|O_TRUNC` and mode `0o666`, so a new
  file becomes `0o666 & ~umask`. Under the common `umask 022` that is
  `0o644`, readable by group and others whenever `~/.pm` (created 0755 by
  `pm_home()`) is traversable.
- Required: a newly created `providers.yaml` must have `stat.S_IMODE ==
  0o600` for every process umask, including `0o022` and `0o000`.

### R2 — An existing permissive file is tightened to 0600 on the next save

- `Path.write_text` on an existing file only truncates it; it never changes
  the existing inode's mode. An install that already wrote a `0644` file
  must be fixed by the next `save_providers()` call (e.g. the next
  `pm provider add` / `remove` / `default`).
- Required: after any save, the target file's mode is exactly `0o600`,
  whether it was absent, `0644`, `0666`, `0640`, or already `0600`.

### R3 — Secure write mechanism

- Write to a temporary file created with restrictive permissions in the
  **same directory** as the target, then `os.replace()` it onto the target.
  `tempfile.mkstemp()` creates with `0600` regardless of umask; the mode is
  also set explicitly before replace so intent is not implicit.
- `os.replace` is atomic within a filesystem, so no reader ever sees a
  partially written or permissive file.
- On any failure, the temporary file must be removed and the original left
  untouched; the error propagates (no silent fallback to a permissive
  write).
- `os.replace` gives R2 for free: the destination is replaced by the
  0600 temp inode, so a pre-existing `0644` inode's mode does not survive.

### R4 — Preserve provider configuration and credential values

- Same YAML serialisation as today: `yaml.dump(data,
  default_flow_style=False, sort_keys=False)`.
- `load_providers()` (`pm_core/providers.py:142`) must return the same
  dict after the change: literal API keys (`api_key: sk-...`) and
  `${ENV_VAR}` references must round-trip unchanged.
- The `~/.pm` directory itself is not modified (see Ambiguity A1).

### R5 — Regression test through `pm provider add`

- CLI path: `provider_add` — `pm_core/cli/provider.py:70-127`; it calls
  `load_providers()` then `save_providers(config)` (line 124).
- Add a test that invokes `pm provider add <name> --api-base ... --api-key
  <dummy> --skip-check` (skip connectivity checks) via
  `click.testing.CliRunner` on the top-level `pm_core.cli.cli` group, with
  `pm_core.providers.pm_home` patched to an isolated temporary directory.
- Assertions:
  1. **New file under umask 022** — file did not exist before; after the
     command, `stat.S_IMODE(path.stat().st_mode) == 0o600`.
  2. **Pre-existing 0644 file** — seed a `providers.yaml` with an existing
     provider, `os.chmod(..., 0o644)`, run `pm provider add`; afterwards
     mode is `0o600`, the pre-existing provider is still present, and the
     new provider was added.
  3. `load_providers()` (or the CLI's own config) still parses and
     returns both providers and the dummy `api_key` value unchanged.
- Dummy credentials only (e.g. `sk-test-dummy-not-a-real-key`); never a
  real secret. Isolated `tmp_path` home; the real `~/.pm` is never touched.
- The test must set `umask 0o022` around the invocation and restore the
  previous umask in a `finally` block, so it fails deterministically on
  pre-fix code and does not perturb the rest of the suite.

## 2. Implicit Requirements

- **I1 — `~/.pm` creation is unchanged.** `pm_home()` (`pm_core/paths.py:27`)
  creates `~/.pm` with default mode (0755 under umask 022). With the file
  at 0600, group/others cannot read the contents; directory traversability
  only reveals that a `providers.yaml` exists. Changing the shared
  `pm_home()` mode is out of scope (see A1).
- **I2 — All save paths are fixed.** `provider add`
  (`pm_core/cli/provider.py:124`), `provider remove` (line 148), `provider
  default` (line ~172), and `set_default_provider`
  (`pm_core/providers.py:258-261`) all funnel through `save_providers`, so
  one fix covers every writer.
- **I3 — Same-directory temp file.** `os.replace` must not cross
  filesystems; the temp file is created with `dir=path.parent`.
- **I4 — No readable partial file window.** The temp inode is 0600 from
  creation (`mkstemp`), so even before `chmod`/replace there is no
  group/world-readable file on disk containing the credential.
- **I5 — Cleanup on failure.** Any exception after temp creation removes
  the temp; the pre-existing file is untouched.
- **I6 — Loader compatibility.** The written YAML is byte-compatible with
  what `load_providers` already parses; no schema change.
- **I7 — No secret exposure in tests or logs.** Tests use dummy keys and
  isolated dirs. `save_providers` logs only the path, as today.

## 3. Ambiguities

- **A1 — Should `~/.pm` itself be tightened to 0700?**
  **Resolution:** No. The stated requirement is the file mode (0600).
  Tightening the shared `pm_home()` would change behaviour for every pm
  component and for pre-existing user installs, well beyond this bug. A
  0600 file inside a 0755 directory is not readable by group/others.
- **A2 — Should other secret-bearing files (launch env, logs) get the same
  treatment?**
  **Resolution:** No — explicitly out of scope; #268 covers the
  launch-command/log exposure.
- **A3 — Symlinked `providers.yaml`.**
  **Resolution:** `os.replace` replaces the symlink itself rather than
  writing through it. That is the safer behaviour for a credentials file
  (no following an attacker-planted link) and is accepted as a behaviour
  change; no special handling needed.
- **A4 — Failure to replace (e.g. permission denied).**
  **Resolution:** Propagate the `OSError` as today. Never fall back to a
  permissive `write_text`.

No **[UNRESOLVED]** ambiguities.

## 4. Edge Cases

- **umask 000 / 077**: `mkstemp` yields 0600 regardless; explicit `chmod`
  keeps it exact.
- **Pre-existing file is read-only (0400)**: replace works when the
  directory is writable; result is 0600 (write bit restored for the owner,
  which is required for the next save).
- **Pre-existing file already 0600**: unchanged behaviour, content
  updated atomically.
- **Concurrent saves**: atomic replace means last-writer-wins with a
  complete file; no interleaved/truncated YAML.
- **Empty/`{}` config**: `yaml.dump({})` → `"{}\n"`; loader returns `{}`
  as before.
- **Exception during `yaml.dump`**: temp removed, original intact.
- **Windows**: `os.replace` is supported; POSIX mode assertions are
  POSIX-only. Project targets Linux, so the test runs unconditionally.
- **Existing tests**: `TestLoadSaveProviders.test_roundtrip` patches
  `pm_core.providers.pm_home` to `tmp_path` and must keep passing; the
  temp file is created inside that directory and cleaned by replace.
