# QA Spec — pr-3fe2696: Switch container runtime from Docker to Podman

## 1. Requirements

| # | Behavior | Expected Outcome |
|---|----------|------------------|
| R1 | `_get_runtime()` reads `container-runtime` setting | Returns `"docker"` (default) or `"podman"` per config |
| R2 | `_run_runtime()` dispatches to configured runtime | Subprocess calls use the runtime binary name as argv[0] |
| R3 | `_runtime_available()` checks the configured runtime | Calls `<runtime> info` and returns bool |
| R4 | `load_container_config()` includes `runtime` field | ContainerConfig.runtime populated from settings |
| R5 | `create_container` adds `--userns=keep-id` for Podman | Flag present when runtime contains "podman", absent for docker |
| R6 | `build_exec_cmd` uses configured runtime in exec and cleanup | `<runtime> exec -it` and `<runtime> rm -f` in output |
| R7 | `container set runtime <value>` validates input | Accepts only "docker" or "podman"; rejects others with error |
| R8 | `container status` shows runtime name and availability | Output includes `Runtime:` and `Runtime available:` lines |
| R9 | `container enable` checks runtime availability | Error message names the configured runtime |
| R10 | Backward-compatible aliases `_docker_available` and `_run_docker` | Point to `_runtime_available` and `_run_runtime` respectively |
| R11 | Dockerfile installs podman + deps and configures vfs storage | `podman`, `fuse-overlayfs`, `slirp4netns`, `uidmap` installed; storage.conf uses vfs driver |
| R12 | All cleanup functions use `_run_runtime` | `cleanup_qa_containers`, `cleanup_session_containers`, `cleanup_all_containers`, `remove_container` |
| R13 | QA loop falls back gracefully when runtime unavailable | `run_qa_sync` logs warning and sets `use_containers = False` |

## 2. Setup

- **Unit tests**: Run `python3 -m pytest tests/test_container.py -x` — all 78 tests must pass.
- **CLI smoke tests**: Need a pm virtualenv (`pip install -e .`) and a test project directory.
- **Container integration**: Requires Podman installed on the host. Run `podman info` to verify.
- **Dockerfile build**: `podman build -t pm-dev:test -f Dockerfile .` to verify the image builds and includes podman.

## 3. Edge Cases

- **Runtime set to an invalid value** via `pm container set runtime nerdctl` — should error.
- **Runtime binary not on PATH** — `_runtime_available()` returns False; enable command errors.
- **`--userns=keep-id` with Docker runtime** — must NOT be present (Docker doesn't support it the same way).
- **Substring match on "podman"**: the check is `if "podman" in runtime` — edge case: a runtime binary named e.g. `/usr/bin/podman-remote` would also match.
- **Backward compat aliases**: Code importing `_docker_available` or `_run_docker` should still work identically.
- **Concurrent runtime changes**: `_get_runtime()` reads settings on every call (no caching) — changing the setting mid-session takes effect immediately.
- **Nested containers**: Inside the pm-dev image, `podman run` should work without `--privileged` on the outer container (vfs driver, host netns).

## 4. Pass/Fail Criteria

**Pass**: All of the following hold:
- `python3 -m pytest tests/test_container.py` — 78/78 pass
- `pm container set runtime podman` succeeds; `pm container set runtime nerdctl` errors
- `pm container status` shows correct runtime name when set to docker or podman
- `pm container enable` with an unavailable runtime prints the runtime name in the error
- Code review confirms no residual hardcoded `"docker"` strings in `container.py` subprocess calls (all go through `_get_runtime()`)

**Fail**: Any unit test failure, hardcoded "docker" in a subprocess call path, or missing `--userns=keep-id` for podman runtime.

## 5. Ambiguities

- **"podman" substring match vs exact match**: The code uses `if "podman" in runtime` which matches `podman-remote` etc. Resolved: this is intentional — podman-remote is a valid podman variant and should get `--userns=keep-id`.
- **Default runtime**: The PR defaults to `"docker"` (backward compatible). Existing users who never set a runtime get Docker behavior unchanged. Resolved: correct, no migration needed.
- **`build_image` with Podman**: Podman's `build` command is compatible with Docker's syntax. Resolved: Podman supports `podman build -t tag -f Dockerfile context` identically.

## 6. Mocks

### Container runtime subprocess calls
- **Contract**: All `subprocess.run([runtime, ...])` calls are mocked via `@patch("subprocess.run")` and `@patch("pm_core.container._get_runtime")`.
- **Scripted responses**: `MagicMock(returncode=0, stdout="container-id\n")` for success; `returncode=1` or `FileNotFoundError` for failures.
- **What remains unmocked**: The `_get_runtime()` function itself reads from `pm_core.paths.get_global_setting_value` — this is mocked separately when testing config loading.

### Settings / paths
- **Contract**: `get_global_setting_value("container-runtime", "docker")` returns the runtime name.
- **Scripted responses**: Return `"docker"` or `"podman"` depending on test scenario.

### No mocks needed for
- File system operations (Dockerfile existence checks use real paths in integration tests)
- The CLI Click commands (tested via Click's `CliRunner`)
