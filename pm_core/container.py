"""Docker container isolation for Claude sessions.

Wraps Claude CLI commands in Docker containers to provide isolation.
Each containerised session gets:
  - The working directory bind-mounted as /workspace (read-write)
  - The host's claude binary bind-mounted at /usr/local/bin/claude
  - Claude config (~/.claude) mounted read-write for auth and session state
  - Configurable resource limits (memory, CPU)
  - Git push via a host-side proxy (credentials never enter the container)

The user experience is transparent: tmux windows look the same, but the
claude process runs inside a resource-limited container via
``docker exec -it`` rather than directly on the host.

Container lifecycle:
  create (detached, sleeping) -> tmux window runs ``docker exec -it``
  -> monitor via tmux pane capture (unchanged) -> cleanup: ``docker rm -f``

Git push support:
  Credentials (SSH keys, HTTPS tokens) stay on the host.  Each container
  gets a dedicated push proxy — a daemon on the host listening on a Unix
  socket that is mounted into the container.  A git wrapper inside the
  container intercepts ``git push`` and forwards the request to the proxy,
  which validates the target branch and executes the real push with host
  credentials.  All other git operations (commit, diff, log, etc.) work
  directly on the bind-mounted workdir with no proxy involvement.

  The branch restriction is enforced outside the container and cannot be
  bypassed from within — the container has no credentials and no way to
  push except through the proxy.

Requirements:
  - The default pm-dev:latest image includes git, python3, pip, node/npm,
    curl, jq, and build-essential.  It is auto-built from the bundled
    Dockerfile on first use.  Users can swap in a custom image via
    ``pm container set image <image>``.
  - Docker must be installed and the current user must have access.
"""

import os
import secrets
import shlex
import shutil
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path

from pm_core.paths import configure_logger

_log = configure_logger("pm.container")

# Default settings
DEFAULT_IMAGE = "pm-dev:latest"
DEFAULT_MEMORY_LIMIT = "4g"
DEFAULT_CPU_LIMIT = "2.0"
CONTAINER_PREFIX = "pm-"
_CONTAINER_WORKDIR = "/workspace"
_CONTAINER_SCRATCH = "/scratch"
_CONTAINER_USER = "pm"
_CONTAINER_HOME = f"/home/{_CONTAINER_USER}"

# Env vars to pass through to the container
_CLAUDE_ENV_VARS = (
    "ANTHROPIC_API_KEY", "CLAUDE_CODE_USE_BEDROCK",
    "AWS_PROFILE", "AWS_REGION", "AWS_DEFAULT_REGION",
    "CLAUDE_CODE_USE_VERTEX", "CLOUD_ML_REGION",
    "ANTHROPIC_MODEL", "ANTHROPIC_SMALL_FAST_MODEL",
)


@dataclass
class ContainerConfig:
    """Configuration for a Claude session container."""
    image: str = DEFAULT_IMAGE
    memory_limit: str = DEFAULT_MEMORY_LIMIT
    cpu_limit: str = DEFAULT_CPU_LIMIT
    env: dict[str, str] = field(default_factory=dict)
    extra_mounts: list[str] = field(default_factory=list)


def _get_dockerfile_path() -> Path:
    """Return the path to the bundled Dockerfile."""
    return Path(__file__).resolve().parent.parent / "Dockerfile"


def build_image(tag: str = DEFAULT_IMAGE, quiet: bool = False) -> None:
    """Build the pm developer base image from the bundled Dockerfile.

    Args:
        tag: Docker image tag (default: pm-dev:latest).
        quiet: Suppress build output.
    """
    dockerfile = _get_dockerfile_path()
    if not dockerfile.exists():
        raise FileNotFoundError(f"Dockerfile not found: {dockerfile}")

    cmd = ["docker", "build", "-t", tag, "-f", str(dockerfile), str(dockerfile.parent)]
    _log.info("Building image %s from %s", tag, dockerfile)
    result = subprocess.run(
        cmd,
        capture_output=quiet,
        text=True,
        timeout=600,
    )
    if result.returncode != 0:
        msg = result.stderr if quiet else "see output above"
        raise RuntimeError(f"Image build failed: {msg}")
    _log.info("Built image %s", tag)


_build_lock = threading.Lock()


def image_exists(tag: str = DEFAULT_IMAGE) -> bool:
    """Check if a Docker image exists locally."""
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", tag],
            capture_output=True, timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _docker_available() -> bool:
    """Check if docker is available and the daemon is running."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True, timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def load_container_config() -> ContainerConfig:
    """Load container configuration from global pm settings."""
    from pm_core.paths import get_global_setting_value

    return ContainerConfig(
        image=get_global_setting_value("container-image", DEFAULT_IMAGE),
        memory_limit=get_global_setting_value(
            "container-memory-limit", DEFAULT_MEMORY_LIMIT),
        cpu_limit=get_global_setting_value(
            "container-cpu-limit", DEFAULT_CPU_LIMIT),
    )


def is_container_mode_enabled() -> bool:
    """Check if container isolation is enabled for Claude sessions."""
    from pm_core.paths import get_global_setting
    return get_global_setting("container-enabled")


def _run_docker(*args: str, check: bool = True,
                timeout: int | None = 30) -> subprocess.CompletedProcess:
    """Run a docker command."""
    cmd = ["docker", *args]
    _log.debug("docker: %s", " ".join(cmd))
    return subprocess.run(
        cmd, capture_output=True, text=True,
        check=check, timeout=timeout,
    )


# ---------------------------------------------------------------------------
# Git push proxy integration
# ---------------------------------------------------------------------------

def _has_remote(workdir: Path) -> bool:
    """Check if the workdir has a git remote (i.e. push makes sense)."""
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=workdir, capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0 and bool(result.stdout.strip())
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _build_git_setup_script(
    has_push_proxy: bool = False,
) -> str:
    """Build a shell script snippet to configure git inside the container.

    This script runs as root at container start, configuring:
      - safe.directory for /workspace
      - A git wrapper that forwards ``git push`` to the host-side push proxy
        (if has_push_proxy is True)
    """
    lines: list[str] = []

    # Set safe directory for /workspace
    lines.append(
        f"su - {_CONTAINER_USER} -c "
        f"'git config --global --add safe.directory {_CONTAINER_WORKDIR}'"
    )

    # Install a git wrapper that intercepts ``git push`` and forwards it
    # to the host-side push proxy via the mounted Unix socket.
    # No credentials exist inside the container — the proxy on the host
    # validates the target branch and runs the real push.
    if has_push_proxy:
        from pm_core.push_proxy import _CONTAINER_SOCKET_PATH
        # NOTE: The inline Python block must start at column 0 inside the
        # shell $(...) substitution, so we can't use textwrap.dedent here.
        wrapper_script = (
            "#!/bin/sh\n"
            "# pm: git wrapper — pushes go through the host-side push proxy\n"
            "REAL_GIT=/usr/bin/git\n"
            f'SOCKET="{_CONTAINER_SOCKET_PATH}"\n'
            'if [ "$1" = "push" ]; then\n'
            '  shift\n'
            '  args_json="["\n'
            '  first=1\n'
            '  for arg in "$@"; do\n'
            '    if [ "$first" = "1" ]; then first=0; else args_json="$args_json,"; fi\n'
            '    escaped=$(printf \'%s\' "$arg" | sed \'s/\\\\/\\\\\\\\/g; s/"/\\\\"/g\')\n'
            '    args_json="$args_json\\"$escaped\\""\n'
            '  done\n'
            '  args_json="$args_json]"\n'
            "  request='{\"args\": '\"$args_json\"'}'\n"
            '  if ! command -v python3 >/dev/null 2>&1; then\n'
            '    echo "pm: python3 required for push proxy client" >&2\n'
            '    exit 1\n'
            '  fi\n'
            '  response=$(python3 -c "\n'
            "import socket, sys, json\n"
            "s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)\n"
            "try:\n"
            "    s.connect('$SOCKET')\n"
            "except Exception as e:\n"
            f"    print(json.dumps({{'exit_code': 1, 'stdout': '', 'stderr': f'push-proxy: cannot connect: {{e}}\\\\n'}}))\n"
            "    sys.exit(0)\n"
            "s.sendall((sys.argv[1] + '\\\\n').encode())\n"
            "data = b''\n"
            "while True:\n"
            "    chunk = s.recv(4096)\n"
            "    if not chunk:\n"
            "        break\n"
            "    data += chunk\n"
            "s.close()\n"
            "print(data.decode())\n"
            '" "$request" 2>&1)\n'
            '  printf \'%s\' "$response" | python3 -c "import sys,json; r=json.load(sys.stdin); sys.stdout.write(r.get(\'stdout\',\'\')); sys.stderr.write(r.get(\'stderr\',\'\')); sys.exit(r.get(\'exit_code\',1))"\n'
            '  exit $?\n'
            "fi\n"
            'exec $REAL_GIT "$@"\n'
        )
        wrapper_path = "/usr/local/bin/git"
        lines.append(f"cat > {wrapper_path} << 'WRAPEOF'\n{wrapper_script}WRAPEOF\nchmod 755 {wrapper_path}")

    return "; ".join(lines) if lines else ""


# ---------------------------------------------------------------------------
# Claude binary resolution
# ---------------------------------------------------------------------------

def _resolve_claude_binary() -> Path | None:
    """Find the real path to the claude CLI binary on the host.

    Follows symlinks to get the actual binary (e.g.
    ~/.local/bin/claude -> ~/.local/share/claude/versions/X.Y.Z).
    Returns None if claude is not found.
    """
    which = shutil.which("claude")
    if not which:
        return None
    return Path(which).resolve()


# ---------------------------------------------------------------------------
# Container naming
# ---------------------------------------------------------------------------

def _make_container_name(label: str) -> str:
    """Generate a unique container name with the given label."""
    suffix = secrets.token_hex(4)
    return f"{CONTAINER_PREFIX}{label}-{suffix}"


def qa_container_name(pr_id: str, loop_id: str, scenario_index: int) -> str:
    """Generate a deterministic container name for a QA scenario."""
    return f"{CONTAINER_PREFIX}qa-{pr_id}-{loop_id}-s{scenario_index}"


# ---------------------------------------------------------------------------
# Core container lifecycle
# ---------------------------------------------------------------------------

def create_container(
    name: str,
    config: ContainerConfig,
    workdir: Path,
    extra_ro_mounts: dict[Path, str] | None = None,
    extra_rw_mounts: dict[Path, str] | None = None,
    allowed_push_branch: str | None = None,
) -> str:
    """Create a detached container with the workdir and claude mounted.

    The container runs ``sleep infinity`` and stays alive for
    ``docker exec -it`` from a tmux window.

    Automatically:
      - Bind-mounts the host's claude binary at /usr/local/bin/claude
      - Mounts ~/.claude read-write (for auth and session state)
      - Passes through Claude-related env vars
      - Applies resource limits from config
      - Starts a host-side push proxy for branch-scoped git push access

    Args:
        name: Container name (must be unique).
        config: Container configuration (image, limits, env).
        workdir: Host path to mount at /workspace (read-write).
        extra_ro_mounts: Additional read-only mounts {host_path: container_path}.
        extra_rw_mounts: Additional read-write mounts {host_path: container_path}.
        allowed_push_branch: If set, restrict git push to this branch only.

    Returns:
        Container ID.
    """
    remove_container(name)

    # Auto-build the pm-dev image if it's the default and not yet built.
    # Use a lock so concurrent create_container calls don't all build at once.
    if config.image == DEFAULT_IMAGE and not image_exists(config.image):
        with _build_lock:
            if not image_exists(config.image):
                _log.info("Default image %s not found — building automatically", config.image)
                build_image(tag=config.image, quiet=True)

    cmd = [
        "run", "-d",
        "--name", name,
        "--memory", config.memory_limit,
        "--cpus", config.cpu_limit,
        "-v", f"{workdir}:{_CONTAINER_WORKDIR}",
        "-w", _CONTAINER_WORKDIR,
    ]

    # --- Claude binary ---
    # Mount the resolved claude binary into the container so the
    # ``claude`` command works inside.
    claude_bin = _resolve_claude_binary()
    if claude_bin and claude_bin.exists():
        cmd.extend(["-v", f"{claude_bin}:/usr/local/bin/claude:ro"])
        _log.info("Mounting claude binary: %s", claude_bin)
    else:
        _log.warning("Claude binary not found on host — "
                     "container will need claude pre-installed in image")

    # --- Claude config (~/.claude and ~/.claude.json) ---
    # Both mounted read-write: Claude needs to write session state, history,
    # file caches, etc.  Each container session gets its own session ID
    # so concurrent writes don't conflict.
    claude_config = Path.home() / ".claude"
    if claude_config.is_dir():
        cmd.extend(["-v", f"{claude_config}:{_CONTAINER_HOME}/.claude"])

    claude_json = Path.home() / ".claude.json"
    if claude_json.exists():
        cmd.extend(["-v", f"{claude_json}:{_CONTAINER_HOME}/.claude.json"])

    # --- Additional mounts ---
    if extra_ro_mounts:
        for host_path, container_path in extra_ro_mounts.items():
            cmd.extend(["-v", f"{host_path}:{container_path}:ro"])

    if extra_rw_mounts:
        for host_path, container_path in extra_rw_mounts.items():
            cmd.extend(["-v", f"{host_path}:{container_path}"])

    # --- Environment ---
    for env_var in _CLAUDE_ENV_VARS:
        val = os.environ.get(env_var)
        if val:
            cmd.extend(["-e", f"{env_var}={val}"])

    for k, v in config.env.items():
        cmd.extend(["-e", f"{k}={v}"])

    # Extra mounts from config (user-specified, e.g. data dirs)
    for mount in config.extra_mounts:
        cmd.extend(["-v", mount])

    # --- Git push proxy ---
    # If an allowed push branch is set and the workdir has a remote,
    # start a host-side push proxy.  The proxy socket is mounted into
    # the container; credentials stay on the host.
    has_push_proxy = False
    if allowed_push_branch and _has_remote(workdir):
        from pm_core.push_proxy import (
            start_push_proxy, _CONTAINER_SOCKET_PATH,
        )
        sock_path = start_push_proxy(name, str(workdir), allowed_push_branch)
        cmd.extend(["-v", f"{sock_path}:{_CONTAINER_SOCKET_PATH}"])
        has_push_proxy = True
        _log.info("Push proxy started for container %s (branch=%s)",
                  name, allowed_push_branch)

    # --- Create pm user with matching uid/gid, configure git, then sleep ---
    host_uid = os.getuid()
    host_gid = os.getgid()
    git_setup = _build_git_setup_script(has_push_proxy=has_push_proxy)
    setup_parts = [
        f"groupadd -g {host_gid} {_CONTAINER_USER} 2>/dev/null",
        f"useradd -u {host_uid} -g {host_gid} -m -s /bin/bash {_CONTAINER_USER} 2>/dev/null",
        f"chown {host_uid}:{host_gid} {_CONTAINER_HOME}",
    ]
    if git_setup:
        setup_parts.append(git_setup)
    setup_parts.append("exec sleep infinity")
    setup = "; ".join(setup_parts)
    cmd.extend([config.image, "bash", "-c", setup])

    result = _run_docker(*cmd, timeout=60)
    container_id = result.stdout.strip()
    _log.info("Created container %s (id=%s)", name, container_id[:12])
    return container_id


def build_exec_cmd(name: str, shell_cmd: str, cleanup: bool = True) -> str:
    """Build a ``docker exec -it`` command string for use in a tmux window.

    When the exec'd process exits, the container is removed (unless
    *cleanup* is False) and the tmux window exits too — same as the
    non-container path.

    Note: this uses raw ``docker rm`` rather than remove_container() since
    it runs in a tmux shell, not in the pm process.  Push proxy threads are
    daemon threads and will be cleaned up on pm exit or container reuse.
    """
    escaped = shlex.quote(shell_cmd)
    exec_part = f"docker exec -it -u {_CONTAINER_USER} {shlex.quote(name)} bash -c {escaped}"
    if cleanup:
        return f"{exec_part}; docker rm -f {shlex.quote(name)} >/dev/null 2>&1"
    return exec_part


def remove_container(name: str) -> None:
    """Force-remove a container and its push proxy (no-op if it doesn't exist)."""
    from pm_core.push_proxy import stop_push_proxy
    stop_push_proxy(name)
    _run_docker("rm", "-f", name, check=False, timeout=30)


# ---------------------------------------------------------------------------
# Shared wrapping: create container + return wrapped command
# ---------------------------------------------------------------------------

def wrap_claude_cmd(
    claude_cmd: str,
    workdir: str,
    label: str = "session",
    extra_ro_mounts: dict[Path, str] | None = None,
    extra_rw_mounts: dict[Path, str] | None = None,
    allowed_push_branch: str | None = None,
) -> tuple[str, str]:
    """Create a container and return a wrapped command for tmux.

    This is the main integration point for all Claude session launchers
    (implementation, review, QA).  If container mode is disabled, returns
    the original command unchanged.

    Args:
        claude_cmd: The claude CLI command string (from build_claude_shell_cmd).
        workdir: Host working directory to mount into the container.
        label: Short label for the container name (e.g. "impl", "review", "qa-s1").
        extra_ro_mounts: Additional read-only mounts {host_path: container_path}.
        extra_rw_mounts: Additional read-write mounts {host_path: container_path}.
        allowed_push_branch: If set, restrict git push to this branch inside the container.

    Returns:
        (wrapped_cmd, container_name).  container_name is "" if not containerised.
    """
    if not is_container_mode_enabled():
        return claude_cmd, ""

    config = load_container_config()
    cname = _make_container_name(label)

    try:
        create_container(
            name=cname,
            config=config,
            workdir=Path(workdir),
            extra_ro_mounts=extra_ro_mounts,
            extra_rw_mounts=extra_rw_mounts,
            allowed_push_branch=allowed_push_branch,
        )
    except Exception:
        _log.warning("Failed to create container %s — falling back to host",
                     cname, exc_info=True)
        return claude_cmd, ""

    exec_cmd = build_exec_cmd(cname, claude_cmd)
    _log.info("Wrapped claude command in container %s", cname)
    return exec_cmd, cname


# ---------------------------------------------------------------------------
# QA-specific helpers
# ---------------------------------------------------------------------------

def create_qa_container(
    name: str,
    config: ContainerConfig,
    repo_root: Path,
    worktree_path: Path,
    scratch_path: Path,
    allowed_push_branch: str | None = None,
) -> str:
    """Create a detached container for a QA scenario.

    Convenience wrapper around create_container with QA-specific mounts:
      - worktree at /workspace (rw)
      - scratch at /scratch (rw)
      - repo at /repo (ro)
    """
    return create_container(
        name=name,
        config=config,
        workdir=worktree_path,
        extra_ro_mounts={repo_root: "/repo"},
        extra_rw_mounts={scratch_path: _CONTAINER_SCRATCH},
        allowed_push_branch=allowed_push_branch,
    )


def cleanup_qa_containers(pr_id: str, loop_id: str) -> int:
    """Remove all containers for a given QA loop.

    Returns the number of containers removed.
    """
    prefix = f"{CONTAINER_PREFIX}qa-{pr_id}-{loop_id}-"
    result = _run_docker(
        "ps", "-a", "--filter", f"name={prefix}",
        "--format", "{{.Names}}",
        check=False, timeout=30,
    )
    if result.returncode != 0:
        return 0

    count = 0
    for line in result.stdout.strip().splitlines():
        cname = line.strip()
        if cname:
            remove_container(cname)
            count += 1

    if count:
        _log.info("Cleaned up %d container(s) for %s/%s", count, pr_id, loop_id)
    return count


def cleanup_all_containers() -> int:
    """Remove all pm containers. Returns count removed."""
    result = _run_docker(
        "ps", "-a", "--filter", f"name={CONTAINER_PREFIX}",
        "--format", "{{.Names}}",
        check=False, timeout=30,
    )
    if result.returncode != 0:
        return 0

    count = 0
    for line in result.stdout.strip().splitlines():
        cname = line.strip()
        if cname:
            remove_container(cname)
            count += 1
    return count
