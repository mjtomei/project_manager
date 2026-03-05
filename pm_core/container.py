"""Docker container isolation for Claude sessions.

Wraps Claude CLI commands in Docker containers to provide isolation.
Each containerised session gets:
  - The working directory bind-mounted as /workspace (read-write)
  - Claude CLI config available inside the container
  - Configurable resource limits (memory, CPU)

The user experience is transparent: tmux windows look the same, but the
claude process runs inside a resource-limited container via
``docker exec -it`` rather than directly on the host.

Container lifecycle:
  create (detached, sleeping) -> tmux window runs ``docker exec -it``
  -> monitor via tmux pane capture (unchanged) -> cleanup: ``docker rm -f``
"""

import os
import secrets
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from pm_core.paths import configure_logger

_log = configure_logger("pm.container")

# Default settings
DEFAULT_IMAGE = "ubuntu:22.04"
DEFAULT_MEMORY_LIMIT = "4g"
DEFAULT_CPU_LIMIT = "2.0"
CONTAINER_PREFIX = "pm-"
_CONTAINER_WORKDIR = "/workspace"
_CONTAINER_SCRATCH = "/scratch"

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
        image=get_global_setting_value("qa-container-image", DEFAULT_IMAGE),
        memory_limit=get_global_setting_value(
            "qa-container-memory-limit", DEFAULT_MEMORY_LIMIT),
        cpu_limit=get_global_setting_value(
            "qa-container-cpu-limit", DEFAULT_CPU_LIMIT),
    )


def is_container_mode_enabled() -> bool:
    """Check if container isolation is enabled for Claude sessions."""
    from pm_core.paths import get_global_setting
    return get_global_setting("qa-container-enabled")


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
) -> str:
    """Create a detached container with the workdir mounted.

    The container runs ``sleep infinity`` and stays alive for
    ``docker exec -it`` from a tmux window.

    Args:
        name: Container name (must be unique).
        config: Container configuration (image, limits, env).
        workdir: Host path to mount at /workspace (read-write).
        extra_ro_mounts: Additional read-only mounts {host_path: container_path}.
        extra_rw_mounts: Additional read-write mounts {host_path: container_path}.

    Returns:
        Container ID.
    """
    remove_container(name)

    cmd = [
        "run", "-d",
        "--name", name,
        "--memory", config.memory_limit,
        "--cpus", config.cpu_limit,
        "-v", f"{workdir}:{_CONTAINER_WORKDIR}",
        "-w", _CONTAINER_WORKDIR,
    ]

    # Read-only mounts
    if extra_ro_mounts:
        for host_path, container_path in extra_ro_mounts.items():
            cmd.extend(["-v", f"{host_path}:{container_path}:ro"])

    # Read-write mounts
    if extra_rw_mounts:
        for host_path, container_path in extra_rw_mounts.items():
            cmd.extend(["-v", f"{host_path}:{container_path}"])

    # Pass through Claude-related env vars
    for env_var in _CLAUDE_ENV_VARS:
        val = os.environ.get(env_var)
        if val:
            cmd.extend(["-e", f"{env_var}={val}"])

    # Custom env vars from config
    for k, v in config.env.items():
        cmd.extend(["-e", f"{k}={v}"])

    # Mount Claude config dir if it exists
    claude_config = Path.home() / ".claude"
    if claude_config.is_dir():
        cmd.extend(["-v", f"{claude_config}:/root/.claude:ro"])

    # Extra mounts from config
    for mount in config.extra_mounts:
        cmd.extend(["-v", mount])

    cmd.extend([config.image, "sleep", "infinity"])

    result = _run_docker(*cmd, timeout=60)
    container_id = result.stdout.strip()
    _log.info("Created container %s (id=%s)", name, container_id[:12])
    return container_id


def build_exec_cmd(name: str, shell_cmd: str) -> str:
    """Build a ``docker exec -it`` command string for use in a tmux window.

    When the exec'd process exits, the tmux window exits too
    (same as the non-container path).
    """
    escaped = shlex.quote(shell_cmd)
    return f"docker exec -it {shlex.quote(name)} bash -c {escaped}"


def remove_container(name: str) -> None:
    """Force-remove a container (no-op if it doesn't exist)."""
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

    Returns:
        (wrapped_cmd, container_name).  container_name is "" if not containerised.
    """
    if not is_container_mode_enabled():
        return claude_cmd, ""

    config = load_container_config()
    cname = _make_container_name(label)

    create_container(
        name=cname,
        config=config,
        workdir=Path(workdir),
        extra_ro_mounts=extra_ro_mounts,
        extra_rw_mounts=extra_rw_mounts,
    )

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
