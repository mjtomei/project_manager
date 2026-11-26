# QA Spec — pr-294e53d

Bug: `providers.yaml` saves literal API keys with group/world-readable
permissions.

Grounded in `pm_core/providers.py` (`save_providers`, `load_providers`,
`_providers_path`, `set_default_provider`), `pm_core/cli/provider.py`
(`provider add` / `remove` / `default` / `list` / `test`), and
`pm_core/paths.py` (`pm_home`). The config lives at `~/.pm/providers.yaml`;
the fix writes a `0600` temp file in `~/.pm` and `os.replace`s it onto the
target.

## 1. Requirements

### R1 — A fresh `pm provider add` creates an owner-only credentials file

- **Given** a machine where `~/.pm/providers.yaml` does not exist and the
  process umask is the common `022`
- **When** the user runs `pm provider add <name> --api-base <url>
  --api-key <dummy> --skip-check`
- **Then** the command reports the provider was added, and
  `~/.pm/providers.yaml` exists with permission bits `rw-------` (0600) —
  no group or other access.

### R2 — The mode is owner-only under a permissive umask

- **Given** the same fresh state but a process umask of `000` (or `077`)
- **When** the user adds a provider
- **Then** `~/.pm/providers.yaml` is still exactly 0600 — the umask cannot
  widen the credential file.

### R3 — An existing permissive file is tightened on the next save

- **Given** `~/.pm/providers.yaml` already exists at 0644 (written by an
  older pm) and contains an existing provider with a literal dummy key
- **When** the user runs `pm provider add` for a second provider
- **Then** after the command the file is 0600, the pre-existing provider
  and its key are still present, the new provider was added, and
  `pm provider list` shows both.

### R4 — Every writer tightens, not just `add`

- **Given** `~/.pm/providers.yaml` is 0644 and contains providers
- **When** the user runs `pm provider remove <name>` (or
  `pm provider default <name>`)
- **Then** the save happens, the file is 0600, and the config change is
  visible (`provider list` reflects it).

### R5 — The configuration and credential values round-trip unchanged

- **Given** a provider was added with a literal dummy key, or with a
  `${ENV_VAR}` reference, a model, and capability tags
- **When** the user lists providers and inspects the saved file
- **Then** the same values load back: the literal key is byte-identical,
  `${ENV_VAR}` stays a reference (not resolved/expanded on disk), and
  type/api_base/model/capabilities are preserved.

### R6 — The normal (checked) add flow still saves securely

- **Given** a fresh state and a provider endpoint that is not reachable
- **When** the user runs `pm provider add` *without* `--skip-check`,
  sees the connectivity warning, and confirms "add anyway"
- **Then** the provider is added and the file is 0600.

### R7 — No temporary files are left behind

- **Given** any successful save
- **When** the command finishes
- **Then** `~/.pm` contains only the expected entries; no
  `.providers.yaml.pm-*` temp files remain.

### R8 — Concurrent writers never leave a corrupt or permissive file

- **Given** a shared `~/.pm/providers.yaml` and several pm processes
  saving at the same time
- **When** the user (or a script) runs multiple `pm provider add` /
  `default` invocations in parallel, while another process reads
- **Then** every save either succeeds completely or reports an error;
  the file is always valid YAML, always 0600, and no temp files remain.
  (Last-writer-wins on the *content* is pre-existing behaviour and is
  not itself a failure.)

### R9 — Failure is loud and non-destructive

- **Given** `~/.pm` exists but is not writable by the user (so the save
  cannot proceed)
- **When** the user runs `pm provider add`
- **Then** the command exits non-zero with a permission error, the
  pre-existing `providers.yaml` is unchanged (content and mode), and no
  temp file is left behind.

### R10 — A symlinked credentials file is replaced safely

- **Given** `~/.pm/providers.yaml` is a symlink to a 0644 file elsewhere
  (e.g. a dotfiles repo)
- **When** the user adds a provider
- **Then** `~/.pm/providers.yaml` becomes a regular 0600 file containing
  the merged config; the previously targeted file is not overwritten with
  the new credentials, and the config still loads.

## 2. Setup

Setup is per scenario, inside its own container:

1. Get pm runnable from the PR checkout (`./install.sh --local`, or an
   editable venv; confirm `pm which` points at the checkout).
2. Use an **isolated home** for every scenario: `export HOME=<tmpdir>`
   (or equivalent) so `~/.pm` is throwaway. Never touch the real `~/.pm`.
3. Use **dummy credentials only** (`sk-test-dummy-...`); never real
   secrets. The point is the file mode, not the value.
4. Set a known umask explicitly before invoking pm when the scenario
   cares about it, and restore it afterwards.

## 3. Edge Cases

- umask `000` / `077` / `022` on file creation (R2).
- Pre-existing modes `0644`, `0666`, `0640`, already-`0600`, and
  read-only `0400` — all must end at 0600 after a save.
- Empty config (`providers: {}`) still saves/loads.
- `${ENV_VAR}` reference is stored literally, never expanded.
- Two providers with the same name: the second add overwrites the entry,
  file stays 0600.
- A provider name containing unusual characters (e.g. `my.provider-1`)
  still round-trips.
- Concurrent add + remove/default.
- Save failure (unwritable `~/.pm`) leaves the original untouched.
- Symlinked target (R10).
- Directory `~/.pm` mode is out of scope: it may remain 0755; only the
  file's contents are protected. A 0600 file is not readable by
  group/others regardless of directory traversability.

## 4. Pass/Fail Criteria

**Pass** when, for every scenario:

- Every `THEN` is observable on the user surface: command output/exit
  code, `ls -l` / `stat` permission bits, file contents, `pm provider
  list` output, or the absence of stray temp files.
- A new `providers.yaml` is `0600` under umask 022 and 000.
- A pre-existing permissive file is `0600` after any of add / remove /
  default.
- Config values (including literal and `${ENV_VAR}` credentials) survive
  the write.
- The failure and concurrency cases leave valid, owner-only state and no
  temp litter.

**Fail** when any of the above does not hold — notably any save that
leaves the file at 0644/0666, a lost credential, a truncated/invalid YAML
file, a leftover temp file, or an error that silently corrupts the
existing config.

## 5. Ambiguities

- **A1 — Should `~/.pm` be 0700 too?** Resolved: out of scope. The
  requirement is the file's 0600 mode; a 0600 file inside a traversable
  directory is still unreadable by group/others. Scenarios assert the
  file mode, not the directory mode.
- **A2 — Should other secret-bearing files (launch env, logs) be
  tightened?** Resolved: out of scope; covered by #268.
- **A3 — Symlink behaviour.** Resolved: `os.replace` replaces the link
  itself. That is intentional for a credentials file (do not follow a
  planted link), so R10 asserts the safe outcome rather than preserving
  the link.
- **A4 — Concurrent adds losing entries.** Resolved: read-modify-write
  last-writer-wins is pre-existing and outside this fix; the concurrency
  scenario asserts only that no *corrupt* or *permissive* state is
  observable, not that every concurrent provider survives.
- **A5 — Failure injection.** The unit test patches `os.replace`; for
  user-level QA, an unwritable `~/.pm` directory is the natural way to
  reach the same failure. If the container runs as root (writes bypass
  mode bits), the worker should note the limitation and fall back to
  asserting the unit-level failure path.

No **[UNRESOLVED]** ambiguities.
