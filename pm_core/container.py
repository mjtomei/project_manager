"""Docker container management for QA scenario isolation.

Each QA scenario worker runs in its own container, presented to the user
via an interactive tmux window.  The container gets:
  - The scenario's git worktree bind-mounted as /workspace (read-write)
  - A scratch directory at /scratch (read-write)
  - The main repo mounted read-only at /repo for reference
  - Claude CLI and config available inside the container
  - Configurable resource limits (memory, CPU)

The user experience is identical to the non-container path: each scenario
appears as a tmux window running Claude.  The difference is that the claude
process runs inside a resource-limited container rather than directly on
the host.

Container lifecycle:
  create (detached, sleeping) -> tmux window runs ``docker exec -it``
  -> monitor via tmux pane capture -> cleanup: ``docker rm -f``
"""

import os
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
CONTAINER_PREFIX = "pm-qa-"
_CONTAINER_WORKDIR = "/workspace"
_CONTAINER_SCRATCH = "/scratch"


@dataclass
class ContainerConfig:
    """Configuration for a QA scenario container."""
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


def container_name(pr_id: str, loop_id: str, scenario_index: int) -> str:
    """Generate a deterministic container name for a scenario."""
    return f"{CONTAINER_PREFIX}{pr_id}-{loop_id}-s{scenario_index}"


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
    """Check if QA container isolation is enabled."""
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


def create_scenario_container(
    name: str,
    config: ContainerConfig,
    repo_root: Path,
    worktree_path: Path,
    scratch_path: Path,
) -> str:
    """Create a detached container for a QA scenario.

    The container is started with ``sleep infinity`` so it stays alive
    while the tmux window runs ``docker exec -it`` into it.

    Args:
        name: Container name.
        config: Container configuration.
        repo_root: Path to the main repo (bind-mounted read-only).
        worktree_path: Path to the scenario's git worktree (bind-mounted rw).
        scratch_path: Path to the scratch directory (bind-mounted rw).

    Returns:
        Container ID.
    """
    # Remove any existing container with the same name
    remove_container(name)

    cmd = [
        "run", "-d",
        "--name", name,
        "--memory", config.memory_limit,
        "--cpus", config.cpu_limit,
        # Mount the worktree as the workspace (read-write)
        "-v", f"{worktree_path}:{_CONTAINER_WORKDIR}",
        # Mount scratch dir
        "-v", f"{scratch_path}:{_CONTAINER_SCRATCH}",
        # Mount repo root read-only for reference
        "-v", f"{repo_root}:/repo:ro",
        "-w", _CONTAINER_WORKDIR,
    ]

    # Pass through Claude-related env vars
    for env_var in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_USE_BEDROCK",
                    "AWS_PROFILE", "AWS_REGION", "AWS_DEFAULT_REGION",
                    "CLAUDE_CODE_USE_VERTEX", "CLOUD_ML_REGION",
                    "ANTHROPIC_MODEL", "ANTHROPIC_SMALL_FAST_MODEL"):
        val = os.environ.get(env_var)
        if val:
            cmd.extend(["-e", f"{env_var}={val}"])

    # Pass through custom env vars from config
    for k, v in config.env.items():
        cmd.extend(["-e", f"{k}={v}"])

    # Mount Claude config dir if it exists
    claude_config = Path.home() / ".claude"
    if claude_config.is_dir():
        cmd.extend(["-v", f"{claude_config}:/root/.claude:ro"])

    # Mount additional paths
    for mount in config.extra_mounts:
        cmd.extend(["-v", mount])

    # Keep container alive for docker exec
    cmd.extend([config.image, "sleep", "infinity"])

    result = _run_docker(*cmd, timeout=60)
    container_id = result.stdout.strip()
    _log.info("Created container %s (id=%s)", name, container_id[:12])
    return container_id


def build_exec_cmd(name: str, shell_cmd: str) -> str:
    """Build a ``docker exec -it`` command string for use in a tmux window.

    The returned string is meant to be passed to tmux new-window as the
    command.  When the exec'd process exits, the tmux window exits too
    (same as the non-container path).

    Args:
        name: Container name.
        shell_cmd: The shell command to run inside the container (e.g. claude CLI).

    Returns:
        Shell command string suitable for tmux.
    """
    escaped = shlex.quote(shell_cmd)
    return f"docker exec -it {shlex.quote(name)} bash -c {escaped}"


def remove_container(name: str) -> None:
    """Force-remove a container (no-op if it doesn't exist)."""
    _run_docker("rm", "-f", name, check=False, timeout=30)


def cleanup_containers(pr_id: str, loop_id: str) -> int:
    """Remove all containers for a given QA loop.

    Returns the number of containers removed.
    """
    prefix = f"{CONTAINER_PREFIX}{pr_id}-{loop_id}-"
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
