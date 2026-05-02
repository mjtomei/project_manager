# Spec: pr-2173cf1 — hook_install writes wrong RECEIVER_PATH inside containers

## Requirements

1. **`pm_core/hook_install.py` must compute `RECEIVER_PATH` (and `_HOOKS_BASE`,
   `_SETTINGS_PATH`) using the host user's home when running inside a
   pm-managed container.** Today line 31/32/36 use `Path.home()` unconditionally,
   which resolves to `/home/pm` inside the container. Because `~/.claude` is
   bind-mounted r/w from the host (container.py:587-589), writes to
   `settings.json` propagate back and embed the container path.

2. **`pm_core/container.py` `create_container` must export `PM_HOST_HOME`
   into every container it spawns**, set to the host user's home
   (`str(Path.home())` evaluated *before* entering the container — i.e.
   on the host where create_container actually executes).

3. **`hook_install.py` must prefer `PM_HOST_HOME` when set**, falling back to
   `Path.home()` otherwise. This keeps host behavior unchanged and only
   alters the path inside containers.

## Implicit Requirements

- The override must apply at *call time*, not at module-import time.
  `hook_install.py` currently sets `RECEIVER_PATH` as a module-level constant.
  The simplest robust shape: keep the constants but compute them via a small
  helper `_host_home()` that reads `PM_HOST_HOME` or falls back to
  `Path.home()`, and recompute the three paths each time `ensure_hooks_installed`
  / `hooks_already_installed` / `_hook_command_for` runs. (Tests already
  reload the module to pick up `$HOME` changes; we keep that working but
  also make env changes take effect without a reload.)
- `_install_receiver()` writes the standalone receiver to `RECEIVER_PATH`.
  When `PM_HOST_HOME` is set inside a container, that path is the *host*
  path which is bind-mounted read-only at the same path (container.py:614,
  `:ro`). Writing to it would fail. So inside a container, we must skip
  the copy. Detect this by: `PM_HOST_HOME` set AND it differs from
  `str(Path.home())`. In that case the host has already installed the
  receiver (and ensure_hooks_installed is mostly a no-op anyway via
  `hooks_already_installed`).
- Same logic for `_HOOKS_BASE.mkdir(...)` — when running in a container,
  the bind mount already exists; mkdir against a host path may fail or
  silently no-op. The current code wraps it in `try/except OSError: pass`
  so it is already tolerant, but we should still target the correct
  path so the host events directory is the one that gets created when
  pm runs on the host.
- `container.py:612` independently re-derives `_receiver_path` via
  `Path.home() / ".pm" / "hook_receiver.py"`. That code runs on the host
  (in `create_container`) so `Path.home()` is already correct there;
  no change required.

## Ambiguities

- **Where in `create_container` to add the `-e PM_HOST_HOME=...`?**
  Resolution: alongside the existing `-e` block at lines 645-652, before
  `config.env` so a user-set `PM_HOST_HOME` (unlikely, but possible)
  wins. Use `str(Path.home())`.

- **Should the env-var lookup happen in `_hook_command_for`, or once per
  call?** Resolution: introduce `_receiver_path()` helper that computes
  the path on demand. Update `_hook_command_for`, `_install_receiver`,
  `_entry_is_pm`, `hooks_already_installed`, `ensure_hooks_installed` to
  use it. Keep the module-level `RECEIVER_PATH` for backwards-compat with
  the existing test that asserts on `tmp_hooks_home / ".pm" / "hook_receiver.py"`,
  but redefine it as a property-like lookup is overkill — instead, just
  drop the import-time constant and let tests resolve the path themselves.
  Actually the simplest path: keep `RECEIVER_PATH` as a module attribute
  computed at import via the helper, AND have functions call the helper
  fresh. Tests that reload the module continue working; runtime paths
  inside containers honor the env var even without reload.

## Edge Cases

- Test `test_installer_writes_standalone_receiver` reloads the module after
  setting `$HOME` but does not set `PM_HOST_HOME`. Must continue to work —
  fallback to `Path.home()`.
- New behavior must not trigger `HookConflictError` on a host that already
  has hooks installed (idempotent path via `hooks_already_installed`).
- Receiver is already installed at `<host_home>/.pm/hook_receiver.py` from
  the host's earlier `ensure_hooks_installed`. Inside a container, since
  `hooks_already_installed` reads from the bind-mounted settings.json with
  the *host* path matching the desired command, it returns True early, and
  we never attempt the failing `shutil.copyfile` to a read-only mount.
  Belt-and-suspenders: also guard `_install_receiver` to skip when in a
  container (PM_HOST_HOME differs from Path.home()).
