# QA Spec: pr-2173cf1 — hook_install writes wrong hook_receiver path inside containers

## Requirements

1. With `PM_HOST_HOME` set (simulating container context), `ensure_hooks_installed` writes hook commands referencing `<PM_HOST_HOME>/.pm/hook_receiver.py`, not `Path.home()/.pm/...`.
2. With `PM_HOST_HOME` unset (host context), behavior is unchanged: hook commands use `Path.home()/.pm/hook_receiver.py`.
3. `_install_receiver()` skips writing the receiver file when running inside a container (PM_HOST_HOME set and != Path.home()) — this prevents writes to a read-only bind mount.
4. `pm_core.container.create_container` adds `-e PM_HOST_HOME=<host home>` to every container run command.
5. Idempotency: running `ensure_hooks_installed` twice does not produce a `HookConflictError` and produces stable settings.json content.
6. The reproduction tests added in `tests/test_hook_events.py` and `tests/test_container.py` pass.

## Setup

- Run the existing pytest suite (`pytest tests/test_hook_events.py tests/test_container.py -v`).
- Inspect the runtime command list emitted by `create_container` (mocked) for the `PM_HOST_HOME` env flag.
- For an integration check, simulate a container env: set `HOME=/tmp/container_home` and `PM_HOST_HOME=/tmp/host_home`, reload module, run `ensure_hooks_installed` against an isolated settings path, and assert the embedded receiver path uses host_home.

## Edge Cases

- `PM_HOST_HOME` set to a value equal to `Path.home()` (host with the env accidentally exported): should behave like host (still install receiver, no skip).
- `PM_HOST_HOME` set but path doesn't yet exist on the simulated host: `_install_receiver` skip path means we don't try to mkdir. `ensure_hooks_installed` should still write settings.json successfully.
- Pre-existing settings.json with non-pm hooks: pm hooks merge in without raising.
- Running `ensure_hooks_installed` a second time: `hooks_already_installed` returns True; no rewrite.

## Pass/Fail Criteria

- **Pass**: All four new/modified test functions pass; full `tests/test_hook_events.py` and `tests/test_container.py` suites pass; manual integration check confirms host path is embedded when PM_HOST_HOME differs from HOME, and Path.home() path is embedded when it doesn't.
- **Fail**: Any container-context invocation embeds the container's `/home/pm/...` path; `_install_receiver` attempts a write on the read-only bind mount; `create_container` does not export PM_HOST_HOME.

## Ambiguities

None unresolved. The PR clearly chose the env-var approach with a guard in `_install_receiver`.

## Mocks

- `pm_core.container._run_runtime` / `image_exists` / `_get_runtime` / `remove_container` — already mocked in the test class (TestCreateContainerPodman). Scenarios that exercise `create_container` use these mocks rather than spawning real containers.
- No real Claude session, tmux, or docker/podman invocation is needed. All assertions are filesystem + arg-list inspection.
