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
import shlex
import shutil
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path

from pm_core.paths import configure_logger

_log = configure_logger("pm.container")


class ContainerError(RuntimeError):
    """Raised when container creation fails and container mode is enabled."""
    pass

# Default settings
DEFAULT_IMAGE = "pm-dev:latest"
DEFAULT_MEMORY_LIMIT = "8g"
DEFAULT_CPU_LIMIT = "4.0"
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
    # Local LLM provider support (Ollama, vLLM, llama.cpp, etc.)
    "OPENAI_API_KEY", "OPENAI_BASE_URL",
    "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN",
    # Provider and model selection
    "PM_PROVIDER", "PM_MODEL", "PM_EFFORT",
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
    result = subprocess.run(
        cmd, capture_output=True, text=True,
        check=False, timeout=timeout,
    )
    if result.returncode != 0:
        _log.error("docker failed (rc=%d): %s\nstderr: %s\nstdout: %s",
                   result.returncode, " ".join(cmd),
                   result.stderr.strip()[:500], result.stdout.strip()[:200])
        if check:
            raise subprocess.CalledProcessError(
                result.returncode, cmd,
                output=result.stdout, stderr=result.stderr)
    return result


def container_is_running(name: str) -> bool:
    """Return True if a container with *name* exists and is running."""
    result = _run_docker(
        "inspect", "-f", "{{.State.Running}}", name,
        check=False, timeout=10,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


# ---------------------------------------------------------------------------
# Git push proxy integration
# ---------------------------------------------------------------------------


def _build_git_setup_script(
    has_push_proxy: bool = False,
    host_workdir: str | None = None,
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

    # Install a git wrapper that intercepts remote-interacting commands
    # (push, fetch, pull, ls-remote) and forwards them to the host-side
    # proxy via the mounted Unix socket.  No credentials exist inside the
    # container — the proxy on the host validates push targets and runs
    # the real git commands.  All other git operations (commit, diff, log,
    # etc.) run directly via /usr/bin/git.
    if has_push_proxy:
        from pm_core.push_proxy import _CONTAINER_SOCKET_PATH
        # Escape the host workdir for safe embedding in a JSON string literal.
        # Backslash must come first to avoid double-escaping.
        _escaped_host_workdir = ""
        if host_workdir:
            _escaped_host_workdir = (
                host_workdir.replace("\\", "\\\\").replace('"', '\\"')
            )
        # NOTE: The inline Python block must start at column 0 inside the
        # shell $(...) substitution, so we can't use textwrap.dedent here.
        wrapper_script = (
            "#!/bin/sh\n"
            "# pm: git wrapper — remote commands go through the host-side proxy\n"
            "REAL_GIT=/usr/bin/git\n"
            f'SOCKET="{_CONTAINER_SOCKET_PATH}"\n'
            # HOST_WORKDIR is the host-side clone path for this container,
            # baked in at creation time so the proxy can use the correct
            # source/target when multiple scenario containers share a proxy.
            + (f'HOST_WORKDIR="{_escaped_host_workdir}"\n'
               if _escaped_host_workdir else "")
            + '# Commands that interact with remotes and need proxy forwarding\n'
            'case "$1" in\n'
            '  push|fetch|pull|ls-remote)\n'
            '    CMD="$1"\n'
            '    shift\n'
            '    args_json="["\n'
            '    first=1\n'
            '    for arg in "$@"; do\n'
            '      if [ "$first" = "1" ]; then first=0; else args_json="$args_json,"; fi\n'
            '      escaped=$(printf \'%s\' "$arg" | sed \'s/\\\\/\\\\\\\\/g; s/"/\\\\"/g\')\n'
            '      args_json="$args_json\\"$escaped\\""\n'
            '    done\n'
            '    args_json="$args_json]"\n'
            '    escaped_cmd=$(printf \'%s\' "$CMD" | sed \'s/"/\\\\"/g\')\n'
            + ('    escaped_workdir=$(printf \'%s\' "$HOST_WORKDIR" | sed \'s/\\\\/\\\\\\\\/g; s/"/\\\\"/g\')\n'
               '    request=\'{"cmd": "\'$escaped_cmd\'", "args": \'$args_json\', "workdir": "\'$escaped_workdir\'"}\'\n'
               if _escaped_host_workdir else
               '    request=\'{"cmd": "\'$escaped_cmd\'", "args": \'$args_json\'}\'\n')
            + '    if ! command -v python3 >/dev/null 2>&1; then\n'
            '      echo "pm: python3 required for git proxy client" >&2\n'
            '      exit 1\n'
            '    fi\n'
            '    response=$(python3 -c "\n'
            "import socket, sys, json\n"
            "s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)\n"
            "try:\n"
            "    s.connect('$SOCKET')\n"
            "except Exception as e:\n"
            f"    print(json.dumps({{'exit_code': 1, 'stdout': '', 'stderr': f'git-proxy: cannot connect: {{e}}\\\\n'}}))\n"
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
            '    printf \'%s\' "$response" | python3 -c "import sys,json; r=json.load(sys.stdin); sys.stdout.write(r.get(\'stdout\',\'\')); sys.stderr.write(r.get(\'stderr\',\'\')); sys.exit(r.get(\'exit_code\',1))"\n'
            '    exit $?\n'
            '    ;;\n'
            'esac\n'
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

def _make_container_name(label: str, session_tag: str | None = None) -> str:
    """Build a deterministic container name from the label.

    When *session_tag* is provided the name includes it so that all
    containers for a session can be listed with
    ``docker ps --filter name=pm-{session_tag}-``.

    Names are deterministic (no random suffix) so that an existing
    container can be detected and reused when the same step is
    re-launched after closing its window.
    """
    if session_tag:
        return f"{CONTAINER_PREFIX}{session_tag}-{label}"
    return f"{CONTAINER_PREFIX}{label}"


def qa_container_name(pr_id: str, loop_id: str, scenario_index: int,
                      session_tag: str | None = None) -> str:
    """Generate a deterministic container name for a QA scenario."""
    if session_tag:
        return f"{CONTAINER_PREFIX}{session_tag}-qa-{pr_id}-{loop_id}-s{scenario_index}"
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
    session_tag: str | None = None,
    pr_id: str | None = None,
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
        session_tag: Session tag for shared push proxies.  When provided
            together with *pr_id*, multiple containers on the same branch
            share a single proxy (socket at a deterministic path).
        pr_id: PR identifier — combined with *session_tag* to key shared
            push proxies.

    Returns:
        Container ID.
    """
    # If a running container with this name already exists, reuse it.
    # The proxy socket directory is bind-mounted (not the socket file),
    # so a restarted proxy is visible to the container immediately.
    if container_is_running(name):
        result = _run_docker(
            "inspect", "-f", "{{.Id}}", name,
            check=False, timeout=10,
        )
        container_id = result.stdout.strip()
        _log.info("Reusing existing container %s (id=%s)", name, container_id[:12])
        # Ensure the push proxy is running (it may have died in a crash)
        if allowed_push_branch:
            from pm_core.push_proxy import (
                start_push_proxy, get_proxy_socket_path, proxy_is_alive,
            )
            sock = get_proxy_socket_path(name, session_tag=session_tag,
                                         pr_id=pr_id)
            if not sock or not proxy_is_alive(sock):
                _log.warning("Push proxy dead/missing for container %s — "
                             "restarting proxy", name)
                start_push_proxy(
                    name, str(workdir), allowed_push_branch,
                    session_tag=session_tag, pr_id=pr_id,
                )
        return container_id

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

    # NOTE: .claude.json is NOT bind-mounted.  Claude writes it atomically
    # (write tmp + rename) which replaces the inode — a single-file bind
    # mount keeps the old inode so the container sees stale content.
    # Instead we copy it in after the container is created (see below).
    _claude_json_src = Path.home() / ".claude.json"

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
    # If an allowed push branch is set, start a host-side push proxy.
    # The proxy socket is mounted into the container; credentials stay
    # on the host.  The proxy handles all origin types: real remotes
    # (HTTP/SSH), local-path origins (from git clone --local), and
    # repos with no remote (push fails cleanly).
    has_push_proxy = False
    if allowed_push_branch:
        from pm_core.push_proxy import (
            start_push_proxy, _CONTAINER_SOCKET_DIR, _CONTAINER_SOCKET_PATH,
        )
        sock_path = start_push_proxy(
            name, str(workdir), allowed_push_branch,
            session_tag=session_tag, pr_id=pr_id,
        )
        # Mount the socket's parent *directory* rather than the socket
        # file itself.  This way, if the proxy restarts and recreates
        # the socket (new inode), the container sees the new one
        # through the directory mount.
        sock_dir = str(Path(sock_path).parent)
        cmd.extend(["-v", f"{sock_dir}:{_CONTAINER_SOCKET_DIR}"])
        has_push_proxy = True
        _log.info("Push proxy started for container %s (branch=%s)",
                  name, allowed_push_branch)

    # --- Create pm user with matching uid/gid, configure git, then sleep ---
    # A readiness sentinel file is written after setup completes so that
    # callers can ``docker exec`` immediately after create_container returns
    # without racing the setup script.
    _READY_SENTINEL = "/tmp/.pm-ready"
    host_uid = os.getuid()
    host_gid = os.getgid()
    # Propagate host git identity so container commits use the right author
    git_name = subprocess.run(
        ["git", "config", "user.name"], capture_output=True, text=True,
    ).stdout.strip()
    git_email = subprocess.run(
        ["git", "config", "user.email"], capture_output=True, text=True,
    ).stdout.strip()

    git_setup = _build_git_setup_script(has_push_proxy=has_push_proxy,
                                        host_workdir=str(workdir) if has_push_proxy else None)
    setup_parts = [
        f"groupadd -g {host_gid} {_CONTAINER_USER} 2>/dev/null",
        f"useradd -u {host_uid} -g {host_gid} -m -s /bin/bash {_CONTAINER_USER} 2>/dev/null",
        f"chown {host_uid}:{host_gid} {_CONTAINER_HOME}",
    ]
    if git_name and git_email:
        setup_parts.append(
            f"su -c 'git config --global user.name \"{git_name}\" && "
            f"git config --global user.email \"{git_email}\"' {_CONTAINER_USER}"
        )
    if git_setup:
        setup_parts.append(git_setup)
    setup_parts.append(f"touch {_READY_SENTINEL}")
    setup_parts.append("exec sleep infinity")
    setup = "; ".join(setup_parts)
    cmd.extend([config.image, "bash", "-c", setup])

    result = _run_docker(*cmd, timeout=60)
    container_id = result.stdout.strip()

    # Wait for the setup script to finish (sentinel file appears).
    import time
    for _ in range(50):  # up to ~5 seconds
        check = _run_docker(
            "exec", name, "test", "-f", _READY_SENTINEL,
            check=False, timeout=5,
        )
        if check.returncode == 0:
            break
        time.sleep(0.1)

    # Copy .claude.json into the container (not bind-mounted — see note above)
    if _claude_json_src.exists():
        try:
            _run_docker("cp", str(_claude_json_src),
                        f"{name}:{_CONTAINER_HOME}/.claude.json",
                        timeout=10)
            _run_docker("exec", name, "chown",
                        f"{host_uid}:{host_gid}",
                        f"{_CONTAINER_HOME}/.claude.json",
                        timeout=5)
        except Exception:
            _log.warning("Failed to copy .claude.json into container %s",
                         name, exc_info=True)

    _log.info("Created container %s (id=%s)", name, container_id[:12])
    return container_id


def build_exec_cmd(name: str, shell_cmd: str, cleanup: bool = True,
                   proxy_socket_path: str | None = None) -> str:
    """Build a ``docker exec -it`` command string for use in a tmux window.

    When the exec'd process exits, the container is removed (unless
    *cleanup* is False).  The tmux pane stays open so the user can
    inspect output.

    If *proxy_socket_path* is provided, the cleanup also removes the
    push proxy socket file and its parent directory.  This triggers the
    proxy daemon thread to self-terminate (it checks for socket existence).
    """
    escaped = shlex.quote(shell_cmd)
    exec_part = f"docker exec -it -u {_CONTAINER_USER} {shlex.quote(name)} bash -c {escaped}"
    if cleanup:
        cleanup_parts = []
        if proxy_socket_path:
            cleanup_parts.append(f"rm -f {shlex.quote(proxy_socket_path)}")
        cleanup_parts.append(
            f"docker rm -f {shlex.quote(name)} >/dev/null 2>&1")
        if proxy_socket_path:
            sock_dir = str(Path(proxy_socket_path).parent)
            cleanup_parts.append(f"rmdir {shlex.quote(sock_dir)} 2>/dev/null")
        # Wrap in a bash trap so cleanup runs even when the pane is killed
        # via tmux kill-pane/kill-window (SIGHUP to the outer shell causes
        # ';'-chained commands to be skipped, but EXIT traps always fire).
        # Use shlex.quote on the full inner script to avoid quote nesting
        # issues: exec_part already contains single-quoted arguments from
        # shlex.quote(), so wrapping in literal '...' would break parsing.
        inner = f"trap {shlex.quote('; '.join(cleanup_parts))} EXIT; {exec_part}"
        return f"bash -c {shlex.quote(inner)}"
    return exec_part


def remove_container(name: str) -> None:
    """Force-remove a container and its push proxy, then wait until it is gone.

    If another 'docker rm -f' is already in flight (e.g. the previous session's
    EXIT trap), this still blocks until the container has fully disappeared so
    that the caller can safely create a fresh container with the same name.
    """
    import time
    from pm_core.push_proxy import stop_push_proxy
    stop_push_proxy(name)
    _run_docker("rm", "-f", name, check=False, timeout=30)
    # Wait for the container to be fully gone.  When another rm is already in
    # flight the daemon returns "removal already in progress" and our rm returns
    # immediately, but the container still exists for a brief moment.
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        result = _run_docker("inspect", name, check=False, timeout=5)
        if result.returncode != 0:
            return  # container is gone
        time.sleep(0.1)
    _log.warning("remove_container: %s still present after 10 s", name)


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
    session_tag: str | None = None,
    pr_id: str | None = None,
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
        session_tag: Session tag — embedded in the container name and used
            for shared push proxies (with *pr_id*).
        pr_id: PR identifier — combined with *session_tag* to share push
            proxies across containers on the same branch.

    Returns:
        (wrapped_cmd, container_name).  container_name is "" if not containerised.
    """
    if not is_container_mode_enabled():
        return claude_cmd, ""

    config = load_container_config()
    cname = _make_container_name(label, session_tag=session_tag)

    try:
        create_container(
            name=cname,
            config=config,
            workdir=Path(workdir),
            extra_ro_mounts=extra_ro_mounts,
            extra_rw_mounts=extra_rw_mounts,
            allowed_push_branch=allowed_push_branch,
            session_tag=session_tag,
            pr_id=pr_id,
        )
    except Exception:
        _log.error("Failed to create container %s — aborting (container mode is enabled)",
                   cname, exc_info=True)
        raise ContainerError(
            f"Failed to create container '{cname}'. "
            f"Is Docker running? Disable container mode with 'pm container disable' "
            f"to run without containers."
        )

    # Rewrite any prompt-file reference that used the host workdir path.
    # build_claude_shell_cmd writes the file to the host and embeds
    # "$(cat <host_workdir>/pm_prompt_*.txt)" in the command.  Inside the
    # container that host path doesn't exist — the workdir is mounted at
    # _CONTAINER_WORKDIR — so replace the prefix now.
    host_prefix = f"$(cat {workdir}/"
    container_prefix = f"$(cat {_CONTAINER_WORKDIR}/"
    if host_prefix in claude_cmd:
        claude_cmd = claude_cmd.replace(host_prefix, container_prefix)
        _log.debug("wrap_claude_cmd: rewrote prompt-file path to container path")

    from pm_core.push_proxy import get_proxy_socket_path
    proxy_sock = get_proxy_socket_path(cname)
    # For shared proxies (session_tag + pr_id), don't embed socket cleanup
    # in the exec command — the socket is shared across containers and its
    # lifetime is managed via reference counting in stop_push_proxy().
    shared_proxy = session_tag is not None and pr_id is not None
    exec_cmd = build_exec_cmd(
        cname, claude_cmd,
        proxy_socket_path=None if shared_proxy else proxy_sock,
    )
    _log.info("Wrapped claude command in container %s", cname)
    return exec_cmd, cname


# ---------------------------------------------------------------------------
# QA-specific helpers
# ---------------------------------------------------------------------------

def create_qa_container(
    name: str,
    config: ContainerConfig,
    workdir: Path,
    scratch_path: Path,
    allowed_push_branch: str | None = None,
    session_tag: str | None = None,
    pr_id: str | None = None,
) -> str:
    """Create a detached container for a QA scenario.

    Convenience wrapper around create_container with QA-specific mounts:
      - workdir at /workspace (rw) — a standalone clone, not a worktree
      - scratch at /scratch (rw)

    The container has no access to the parent repo's git directory.
    If *allowed_push_branch* is set, a push proxy is started so the
    scenario can push fixes to the PR branch.
    """
    return create_container(
        name=name,
        config=config,
        workdir=workdir,
        extra_rw_mounts={scratch_path: _CONTAINER_SCRATCH},
        allowed_push_branch=allowed_push_branch,
        session_tag=session_tag,
        pr_id=pr_id,
    )


def cleanup_qa_containers(pr_id: str, loop_id: str,
                          exclude: set[str] | None = None,
                          session_tag: str | None = None) -> int:
    """Remove all containers for a given QA loop.

    *exclude* is an optional set of container names to skip (e.g. the
    interactive Scenario 0 container that should stay alive).

    Returns the number of containers removed.
    """
    # Search for both session-tagged and legacy container names
    prefixes = []
    if session_tag:
        prefixes.append(f"{CONTAINER_PREFIX}{session_tag}-qa-{pr_id}-{loop_id}-")
    prefixes.append(f"{CONTAINER_PREFIX}qa-{pr_id}-{loop_id}-")

    count = 0
    for prefix in prefixes:
        result = _run_docker(
            "ps", "-a", "--filter", f"name={prefix}",
            "--format", "{{.Names}}",
            check=False, timeout=30,
        )
        if result.returncode != 0:
            continue

        for line in result.stdout.strip().splitlines():
            cname = line.strip()
            if cname and cname not in (exclude or set()):
                remove_container(cname)
                count += 1

    if count:
        _log.info("Cleaned up %d container(s) for %s/%s", count, pr_id, loop_id)
    return count


def cleanup_orphaned_qa_containers(session: str, pr_id: str,
                                   session_tag: str | None = None) -> int:
    """Remove QA containers whose tmux windows no longer exist.

    Called at the start of a new QA run.  Scans all containers matching
    the QA prefix for *pr_id* (any loop_id) and removes those whose
    corresponding tmux scenario window is gone.

    Returns the number of containers removed.
    """
    from pm_core import tmux as tmux_mod

    # Search for both session-tagged and legacy container names
    prefixes = []
    if session_tag:
        prefixes.append(f"{CONTAINER_PREFIX}{session_tag}-qa-{pr_id}-")
    prefixes.append(f"{CONTAINER_PREFIX}qa-{pr_id}-")

    # Build set of live window names for fast lookup
    try:
        live_windows = {w["name"] for w in tmux_mod.list_windows(session)}
    except Exception:
        return 0

    count = 0
    for prefix in prefixes:
        result = _run_docker(
            "ps", "-a", "--filter", f"name={prefix}",
            "--format", "{{.Names}}",
            check=False, timeout=30,
        )
        if result.returncode != 0:
            continue

        for line in result.stdout.strip().splitlines():
            cname = line.strip()
            if not cname:
                continue
            # Container name: pm[-{session_tag}]-qa-{pr_id}-{loop_id}-s{N}
            # Window name:    qa-{display_id}-s{N}
            # Extract the -s{N} suffix to check against windows.
            parts = cname.split("-s")
            if len(parts) < 2:
                continue
            suffix = f"-s{parts[-1]}"
            # Check if ANY window ending with this suffix exists
            has_window = any(w.endswith(suffix) and w.startswith("qa-")
                             for w in live_windows)
            if not has_window:
                remove_container(cname)
                count += 1

    if count:
        _log.info("Cleaned up %d orphaned QA container(s) for %s",
                  count, pr_id)
    return count


def cleanup_session_containers(session_tag: str) -> int:
    """Remove all containers belonging to a session.

    Filters by ``pm-{session_tag}-`` which matches every container whose
    name was generated with this session tag embedded.

    Returns the number of containers removed.
    """
    prefix = f"{CONTAINER_PREFIX}{session_tag}-"
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
        _log.info("Cleaned up %d container(s) for session %s", count, session_tag)
    return count


def cleanup_stale_containers(session_name: str, session_tag: str) -> int:
    """Remove containers whose tmux windows no longer exist.

    For each container matching ``pm-{session_tag}-*``, derives the
    expected tmux window name and checks if it still exists.  Containers
    whose windows are gone are removed along with their push proxies.

    Returns the number of containers removed.
    """
    from pm_core import tmux as tmux_mod

    prefix = f"{CONTAINER_PREFIX}{session_tag}-"
    result = _run_docker(
        "ps", "-a", "--filter", f"name={prefix}",
        "--format", "{{.Names}}",
        check=False, timeout=30,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return 0

    # Build set of live window names
    try:
        live_windows = {w["name"] for w in tmux_mod.list_windows(session_name)}
    except Exception:
        return 0

    # Build pr_id → display_id map from the store so we can map container
    # names back to tmux window names.  If the store can't be loaded we
    # must bail out — an empty map would cause every container to be
    # treated as stale and removed.
    pr_display_map: dict[str, str] = {}
    try:
        from pm_core.cli.helpers import state_root
        from pm_core import store
        root = state_root()
        data = store.load(root)
        for pr in data.get("prs", []):
            pr_id = pr["id"]
            gh = pr.get("gh_pr_number")
            pr_display_map[pr_id] = f"#{gh}" if gh else pr_id
    except Exception:
        return 0

    count = 0
    for line in result.stdout.strip().splitlines():
        cname = line.strip()
        if not cname:
            continue
        # Strip the prefix to get the label
        label = cname.removeprefix(prefix)

        # Determine expected window name from the label
        window_name: str | None = None

        if label.startswith("impl-"):
            pr_id = label.removeprefix("impl-")
            display_id = pr_display_map.get(pr_id)
            if display_id:
                window_name = display_id
            else:
                # PR no longer in store — container is definitely stale
                remove_container(cname)
                count += 1
                continue

        elif label.startswith("review-"):
            pr_id = label.removeprefix("review-")
            display_id = pr_display_map.get(pr_id)
            if display_id:
                window_name = f"review-{display_id}"
            else:
                remove_container(cname)
                count += 1
                continue

        elif label.startswith("qa-"):
            # QA containers: pm-{tag}-qa-{pr_id}-{loop_id}-s{N}
            # Window names:  qa-{display_id}-s{N}
            # Use suffix matching (same logic as cleanup_orphaned_qa_containers)
            parts = cname.split("-s")
            if len(parts) < 2:
                continue
            suffix = f"-s{parts[-1]}"
            has_window = any(w.endswith(suffix) and w.startswith("qa-")
                             for w in live_windows)
            if not has_window:
                remove_container(cname)
                count += 1
            continue

        else:
            # Unknown label type — skip
            continue

        # Check if the expected window exists
        if window_name not in live_windows:
            remove_container(cname)
            count += 1

    if count:
        _log.info("Cleaned up %d stale container(s) for session %s",
                  count, session_tag)
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
