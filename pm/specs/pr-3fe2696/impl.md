# Implementation Spec: Switch Container Runtime from Docker to Podman

**PR:** pr-3fe2696
**Branch:** pm/pr-3fe2696-switch-container-runtime-from-docker-to-podman-for

---

## 1. Requirements

### R1: Configurable container runtime (docker or podman)

**Files:** `pm_core/container.py`, `pm_core/cli/container.py`

Replace all hardcoded `"docker"` CLI references with a configurable runtime binary name. The runtime is selected via a new `container-runtime` global setting (default: `"docker"` for backward compatibility).

Affected code paths:
- `_run_docker()` (line 167): The central command runner — prepends `["docker", *args]`. Rename to `_run_runtime()` and source the binary name from config/module-level helper.
- `build_image()` (line 107): Direct `subprocess.run(["docker", "build", ...])` call — must use the configured runtime.
- `image_exists()` (line 127): Direct `subprocess.run(["docker", "image", "inspect", ...])`.
- `_docker_available()` (line 136): Direct `subprocess.run(["docker", "info", ...])`.
- `build_exec_cmd()` (line 614): Hardcoded `"docker exec -it"` and `"docker rm -f"` in shell strings.
- `remove_container()` (line 645): Calls `_run_docker("rm", ...)` and `_run_docker("inspect", ...)` — these go through the wrapper, so they'll be fine once the wrapper is updated.
- All cleanup functions (lines 796-917): Use `_run_docker("ps", ...)` and `_run_docker("rm", ...)` — same, goes through wrapper.
- Module docstring (line 1): References "Docker" — update terminology.

### R2: Add `--userns=keep-id` to container run commands

**File:** `pm_core/container.py`, `create_container()` (line 431)

When the configured runtime is `podman`, add `--userns=keep-id` to the `docker run` command arguments. This flag maps the host UID into the container without needing manual `useradd`/`groupadd` — Podman rootless handles the user namespace mapping automatically.

This flag is Podman-specific and must NOT be added when using Docker.

### R3: Install podman in the base image (Dockerfile)

**File:** `Dockerfile`

Add `podman` (and dependencies like `fuse-overlayfs`, `slirp4netns`) to the apt-get install list so that QA scenarios running inside containers can spawn their own nested containers without `--privileged`.

Podman's rootless mode with user namespaces enables nested container creation without elevated privileges, which is the core motivation for this PR.

### R4: Update `_docker_available()` and related checks

**Files:** `pm_core/container.py`, `pm_core/cli/container.py`, `pm_core/qa_loop.py`, `pm_core/cli/qa.py`

Rename `_docker_available()` to `_runtime_available()` (or similar) and have it check the configured runtime binary instead of hardcoded `docker`. All call sites (14 references across 6 files) must be updated.

---

## 2. Implicit Requirements

### IR1: Settings infrastructure for `container-runtime`

A new setting `container-runtime` must be loadable via `get_global_setting_value()` and settable via `set_global_setting_value()`. The CLI's `pm container set` command (line 68-80 of `cli/container.py`) must accept `"runtime"` as a valid key. The CLI's `pm container status` must display the current runtime.

### IR2: User creation logic adapts to Podman's `--userns=keep-id`

With `--userns=keep-id`, the container process runs as the host user (non-root). `groupadd`/`useradd` require root and fail silently, leaving no "pm" user in `/etc/passwd`. This breaks `exec -u pm` and `su - pm` downstream.

**Fix:** When `"podman" in runtime`, the setup script must:
1. Skip `groupadd`/`useradd`/`chown` entirely
2. Run `mkdir -p /home/pm` to ensure the home dir exists (the UID already has write access via namespace mapping)
3. Set `HOME=/home/pm` explicitly so git config writes to the right place

### IR3: `build_exec_cmd()` must not use `-u pm` under Podman

Under Docker, `exec -u pm` switches to the pm user. Under Podman with `--userns=keep-id`, the "pm" user doesn't exist in `/etc/passwd`, so `-u pm` fails with "unable to find user pm".

**Fix:** When `"podman" in runtime`, omit `-u {_CONTAINER_USER}` from the exec command. The default user is already the host user with the correct UID mapping.

### IR3a: Git setup must not use `su` under Podman

Both `_build_git_setup_script()` and the git identity setup in `create_container()` use `su - pm` as a fallback. Under Podman, the process is already the correct user (non-root), so `su` is unnecessary and fails (no pm user in passwd). The `su` fallback should only be attempted when running as root (Docker).

### IR4: `build_exec_cmd()` must use configured runtime in shell strings

`build_exec_cmd()` constructs shell command strings (not subprocess calls) with hardcoded `"docker exec"` and `"docker rm"`. These must also use the configured runtime name.

### IR5: Test updates

Tests in `tests/test_container.py` and `tests/test_cli_container.py` that assert `"docker"` in command arguments or mock `subprocess.run` with docker commands must be updated to work with the configurable runtime.

### IR6: Podman storage configuration for nested containers

For nested container support inside the base image, Podman needs proper storage configuration. The Dockerfile should configure `/etc/containers/storage.conf` to use `fuse-overlayfs` as the storage driver (required for rootless Podman inside a container).

---

## 3. Ambiguities

### A1: Default runtime value — RESOLVED

**Resolution:** Default to `"docker"` for backward compatibility. Users opt into Podman by running `pm container set runtime podman`.

### A2: Should `_run_docker` be renamed? — RESOLVED

**Resolution:** Yes, rename to `_run_runtime()` to be runtime-agnostic. The function signature stays the same. Update all internal callers. Keep the logging prefix generic (e.g., `"container:"` instead of `"docker:"`).

### A3: How to determine the runtime for `--userns=keep-id` — RESOLVED

**Resolution:** Use the configured runtime setting string. If it contains "podman" (or equals "podman"), add the flag. This is simpler than runtime detection and aligned with explicit configuration.

### A4: Podman compatibility with Docker commands — RESOLVED

**Resolution:** Podman is designed as a drop-in CLI replacement for Docker. All Docker CLI commands used in this codebase (`run`, `exec`, `build`, `cp`, `rm`, `ps`, `inspect`, `image inspect`, `info`) are supported by Podman with identical syntax. No command translation needed.

### A5: Should the `pm container enable` error message reference the configured runtime? — RESOLVED

**Resolution:** Yes. Change from "Install and start Docker first" to reference the configured runtime name dynamically.

### A6: Container entrypoint script user creation under Podman — RESOLVED

**Resolution:** The original assumption was wrong: `2>/dev/null || true` guards are NOT sufficient. With `--userns=keep-id`, the container runs as the host user (non-root), so `groupadd`/`useradd` fail silently — but the "pm" user is never created in `/etc/passwd`. This causes `podman exec -u pm` and `su - pm` to fail fatally later. The fix requires runtime-aware branching:

- **Podman path:** Skip `groupadd`/`useradd` entirely. Instead `mkdir -p /home/pm` to ensure the home directory exists. The host UID is already mapped by the user namespace — no passwd entry needed. Drop `-u pm` from `exec` commands (the default user is already correct). Remove `su` fallbacks from git config (the process is already the correct user).
- **Docker path:** Unchanged — runs as root, creates the pm user, execs as `-u pm`.

---

## 4. Edge Cases

### E1: Mixed Docker/Podman environments

If both `docker` and `podman` are installed, the configured setting determines which one runs. There is no auto-detection or fallback chain — the user explicitly chooses.

### E2: Podman rootful mode

The `--userns=keep-id` flag is only relevant for rootless Podman. If someone runs Podman as root, the flag is harmless (Podman accepts it but it's a no-op in rootful mode).

### E3: Existing containers after runtime switch

If a user switches from Docker to Podman (or vice versa), existing containers created by the previous runtime won't be visible to the new one. Cleanup commands will only see containers from the active runtime. The old containers become orphaned until the user manually removes them with the previous runtime.

### E4: Image compatibility

Docker and Podman use the same OCI image format. Images built with `docker build` work with `podman run` and vice versa. However, the image caches are separate — switching runtimes requires rebuilding or pulling images.

### E5: `docker-entrypoint.sh` naming

The file `docker-entrypoint.sh` is referenced in the Dockerfile's implicit entrypoint. The filename is conventional and doesn't need renaming — it's an OCI container entrypoint, not Docker-specific.

### E6: Nested Podman inside container needs `/dev/fuse`

For Podman to work inside a container (the nested case), the container needs access to `/dev/fuse` for `fuse-overlayfs`. With `--userns=keep-id` and `--device /dev/fuse`, this works without `--privileged`. Alternatively, using `vfs` storage driver avoids the fuse requirement but is slower. The Dockerfile should configure storage to use `vfs` for maximum compatibility (no device mounting needed).

---

## 5. Implementation Plan

### Step 1: Add runtime configuration to `container.py`

- Add `DEFAULT_RUNTIME = "docker"` constant
- Add `runtime` field to `ContainerConfig` dataclass
- Update `load_container_config()` to read `container-runtime` setting
- Add helper `_get_runtime()` that returns the configured runtime binary name

### Step 2: Replace hardcoded `docker` references in `container.py`

- Rename `_run_docker()` to `_run_runtime()`, use `_get_runtime()` for the binary
- Update `build_image()` to use configured runtime
- Update `image_exists()` to use configured runtime
- Rename `_docker_available()` to `_runtime_available()`, use configured runtime
- Update `build_exec_cmd()` shell strings to use configured runtime
- Update all internal callers and log messages

### Step 3: Add `--userns=keep-id` for Podman in `create_container()`

- When runtime is podman, add `--userns=keep-id` to the `run` command
- Branch the setup script: Podman skips `groupadd`/`useradd`, just `mkdir -p /home/pm`; Docker keeps existing user creation
- Branch git config: Podman uses direct `git config` with `HOME=/home/pm`; Docker keeps `su` fallback
- Branch `_build_git_setup_script`: Podman skips `su` fallback for safe.directory
- Branch `build_exec_cmd`: Podman omits `-u pm` from exec commands

### Step 4: Update Dockerfile for nested Podman support

- Add `podman`, `fuse-overlayfs`, `slirp4netns`, `uidmap` packages
- Configure `/etc/containers/storage.conf` with `vfs` driver for nested use
- Configure `/etc/containers/containers.conf` if needed

### Step 5: Update CLI commands

- Add `"runtime"` to `pm container set` choices
- Update `pm container status` to show runtime
- Update `pm container enable` error messages

### Step 6: Update all external call sites

- `pm_core/qa_loop.py`: Update imports and calls
- `pm_core/cli/qa.py`: Update imports and calls
- `pm_core/cli/container.py`: Update imports and calls
- `pm_core/cli/pr.py`: No changes needed (uses `wrap_claude_cmd`)

### Step 7: Update tests

- Update test imports for renamed functions
- Update assertions that check for `"docker"` in command arrays
- Add tests for podman-specific behavior (`--userns=keep-id`)
- Add test for `_runtime_available()` with configurable runtime
