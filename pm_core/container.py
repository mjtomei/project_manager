"""Container isolation for Claude sessions.

Wraps Claude CLI commands in containers (Docker or Podman) to provide
isolation.  Each containerised session gets:
  - The working directory bind-mounted as /workspace (read-write)
  - The host's claude binary bind-mounted at /usr/local/bin/claude
  - Claude config (~/.claude) mounted read-write for auth and session state
  - Configurable resource limits (memory, CPU)
  - Git push via a host-side proxy (credentials never enter the container)

The user experience is transparent: tmux windows look the same, but the
claude process runs inside a resource-limited container via
``<runtime> exec -it`` rather than directly on the host.

Container lifecycle:
  create (detached, sleeping) -> tmux window runs ``<runtime> exec -it``
  -> monitor via tmux pane capture (unchanged) -> cleanup: ``<runtime> rm -f``

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
  - Docker or Podman must be installed and the current user must have access.
    Select the runtime via ``pm container set runtime podman`` (default: docker).
"""

import contextlib
import contextvars
import functools
import fcntl
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from pm_core.paths import configure_logger

_log = configure_logger("pm.container")


class ContainerError(RuntimeError):
    """Raised when container creation fails and container mode is enabled."""
    pass


class ContainerLaunchError(ContainerError):
    """A container could not be created, set up, or reused.

    ``kind`` classifies the cause (``keyring``, ``memory``, ``pids``,
    ``image``, ``timeout``, ``config``, ``proxy``, ``incomplete``,
    ``runtime``) and ``stderr`` keeps the runtime's own error text so the
    launcher can show the real cause instead of a generic guess.
    """

    def __init__(self, message: str, *, kind: str = "runtime",
                 stderr: str = "", name: str = "") -> None:
        super().__init__(message)
        self.kind = kind
        self.stderr = stderr
        self.name = name

# Default settings
DEFAULT_IMAGE = "pm-dev:latest"
DEFAULT_MEMORY_LIMIT = "8g"
DEFAULT_CPU_LIMIT = "4.0"
DEFAULT_RUNTIME = "docker"
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
    runtime: str = DEFAULT_RUNTIME
    env: dict[str, str] = field(default_factory=dict)
    extra_mounts: list[str] = field(default_factory=list)


def _detect_default_runtime() -> str:
    """Auto-detect the best available container runtime.

    Prefers podman (rootless, nested container support) over docker.
    Falls back to ``DEFAULT_RUNTIME`` if neither is found (will fail later
    with a clear error from ``_runtime_available``).
    """
    for candidate in ("podman", "docker"):
        if shutil.which(candidate):
            return candidate
    return DEFAULT_RUNTIME


def _get_runtime() -> str:
    """Return the configured container runtime binary name.

    If the user has explicitly set ``container-runtime``, use that.
    Otherwise auto-detect: prefer podman if installed, fall back to docker.
    """
    from pm_core.paths import get_global_setting_value
    explicit = get_global_setting_value("container-runtime", "")
    if explicit:
        return explicit
    return _detect_default_runtime()


def _nested_podman_enabled() -> bool:
    """True when the active pm project sets ``nested_podman: true``.

    Used to opt into a relaxed container sandbox so a podman process inside
    the container can spawn its own containers (rootless podman-in-podman).
    Default off — the relaxations remove defense-in-depth layers (AppArmor,
    /proc masks) and should only apply to projects that genuinely need it.
    """
    try:
        from pm_core.store import find_project_root, load
        data = load(find_project_root(), validate=False)
        return bool(data.get("project", {}).get("nested_podman", False))
    except Exception:
        return False


def _apparmor_enforcing() -> bool:
    try:
        return Path("/sys/module/apparmor/parameters/enabled").read_text().strip() == "Y"
    except OSError:
        return False


def _selinux_enabled() -> bool:
    return Path("/sys/fs/selinux/enforce").exists()


def _nested_podman_run_args() -> list[str]:
    """Extra ``podman run`` flags needed for nested rootless podman.

    Image-side prerequisites (baked into pm-dev): ``uidmap`` with
    ``newuidmap``/``newgidmap`` granted ``cap_setuid``/``cap_setgid`` via
    file capabilities (NOT setuid — file caps are evaluated within the
    user namespace), ``/etc/subuid`` + ``/etc/subgid`` entries for ``pm``
    constrained to the inner namespace's UID range, and overlay storage
    via ``fuse-overlayfs``.
    """
    args: list[str] = [
        "--device", "/dev/fuse",
        "--device", "/dev/net/tun",
        "--security-opt", "unmask=ALL",
        # Share the host UTS namespace instead of creating a fresh one.
        #
        # Why it's needed: creating a new UTS namespace makes podman call
        # ``sethostname(2)`` to give the container its own hostname. The
        # kernel requires CAP_SYS_ADMIN *in the user namespace that owns the
        # target UTS namespace* for that call. A container one level deep
        # (the env an inner podman runs in) has no CAP_SYS_ADMIN in its
        # bounding set and inherits the default seccomp filter, which gates
        # ``sethostname`` on that very capability — so every *nested*
        # ``podman run`` dies with "sethostname: Operation not permitted"
        # before any workload starts. ``--uts=host`` skips the namespace,
        # hence the syscall, so the inner launch succeeds. (The outer,
        # bare-metal launch doesn't need this — it has the cap and no
        # seccomp filter — but applying it unconditionally is harmless and
        # saves us detecting whether we're already inside a container.)
        #
        # Why it's safe here: pm runs *rootless* podman. With ``--uts=host``
        # the container shares the host UTS namespace, which is owned by the
        # host's (init) user namespace — one a rootless container has no
        # privileges over. So the container *cannot* rename the host: the
        # same CAP_SYS_ADMIN rule that forces this workaround also prevents
        # it from being abused (confirmed by the podman maintainers, gh
        # discussion #25061). The CIS Docker 5.20 warning against
        # ``--uts=host`` targets *rootful* containers, where the container
        # really can change the host's hostname; it does not apply to
        # rootless. The only real cost is functional: containers inherit the
        # host hostname and can't set their own (and ``--uts=host`` is
        # mutually exclusive with ``--hostname``, which pm never passes).
        "--uts=host",
    ]
    if _apparmor_enforcing():
        args.extend(["--security-opt", "apparmor=unconfined"])
    if _selinux_enabled():
        args.extend(["--security-opt", "label=disable"])
    return args


def _get_dockerfile_path() -> Path:
    """Return the path to the bundled Dockerfile."""
    return Path(__file__).resolve().parent.parent / "Dockerfile"


def _host_git_identity() -> tuple[str, str]:
    """Return (name, email) from the host's global git config, or empty strings."""
    def _read(key: str) -> str:
        try:
            r = subprocess.run(
                ["git", "config", "--global", key],
                capture_output=True, text=True, timeout=5,
            )
            return r.stdout.strip() if r.returncode == 0 else ""
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return ""
    return _read("user.name"), _read("user.email")


def build_image(tag: str = DEFAULT_IMAGE, quiet: bool = False) -> None:
    """Build the pm developer base image from the bundled Dockerfile.

    Args:
        tag: Image tag (default: pm-dev:latest).
        quiet: Suppress build output.
    """
    dockerfile = _get_dockerfile_path()
    if not dockerfile.exists():
        raise FileNotFoundError(f"Dockerfile not found: {dockerfile}")

    runtime = _get_runtime()
    git_name, git_email = _host_git_identity()
    cmd = [runtime, "build"]
    # Nested rootless podman: build RUN steps otherwise create a fresh UTS
    # namespace and call sethostname(2), which a nested env lacks
    # CAP_SYS_ADMIN for — every RUN dies with "sethostname: Operation not
    # permitted" before the image can be built (and create_container
    # auto-builds pm-dev on first use, so this blocks the whole flow).
    # Share the host UTS namespace (skipping the sethostname call), exactly
    # mirroring the --uts=host accommodation _nested_podman_run_args()
    # applies to the corresponding `podman run`.  (chroot isolation also
    # skips the namespace but breaks node's libuv fd handling at build time,
    # so --uts=host on the default OCI isolation is the right lever here.)
    if "podman" in runtime and _nested_podman_enabled():
        cmd.extend(["--uts", "host"])
    cmd += [
        "-t", tag,
        "--build-arg", f"GIT_USER_NAME={git_name}",
        "--build-arg", f"GIT_USER_EMAIL={git_email}",
        "-f", str(dockerfile), str(dockerfile.parent),
    ]
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
    _invalidate_image_exists_cache(tag)


_build_lock = threading.Lock()

# Cached image-existence results. When many QA scenarios launch in
# parallel, each one's ``create_container`` call invokes ``image_exists``
# concurrently; under load, ``podman image inspect`` hits the 10 s
# subprocess timeout and reports false negatives, so scenarios spuriously
# fail with "image not found".  Coalesce concurrent callers onto a
# single inspect and cache the result for a short TTL.
_image_exists_cache: dict[str, tuple[float, bool]] = {}
_image_exists_lock = threading.Lock()
_IMAGE_EXISTS_TTL = 30.0


def image_exists(tag: str = DEFAULT_IMAGE) -> bool:
    """Check if the container image exists locally.

    Thread-safe and cached for ``_IMAGE_EXISTS_TTL`` seconds.  The lock is
    held across the subprocess call so N concurrent callers collapse onto
    a single ``podman image inspect``; slow ones wait instead of racing
    and timing out.  Cache expiry lets pm notice rebuilds/removals
    without requiring a process restart.
    """
    now = time.monotonic()
    with _image_exists_lock:
        cached = _image_exists_cache.get(tag)
        if cached and now - cached[0] < _IMAGE_EXISTS_TTL:
            return cached[1]
        runtime = _get_runtime()
        try:
            result = subprocess.run(
                [runtime, "image", "inspect", tag],
                capture_output=True, timeout=10,
            )
            exists = result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            exists = False
        _image_exists_cache[tag] = (time.monotonic(), exists)
        return exists


def _invalidate_image_exists_cache(tag: str | None = None) -> None:
    """Clear the image_exists cache (all tags or just one)."""
    with _image_exists_lock:
        if tag is None:
            _image_exists_cache.clear()
        else:
            _image_exists_cache.pop(tag, None)


def _runtime_available() -> bool:
    """Check if the configured container runtime is available."""
    runtime = _get_runtime()
    try:
        result = subprocess.run(
            [runtime, "info"],
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
        runtime=_get_runtime(),
    )


def is_container_mode_enabled() -> bool:
    """Check if container isolation is enabled for Claude sessions."""
    from pm_core.paths import get_global_setting
    return get_global_setting("container-enabled")


def _run_runtime(*args: str, check: bool = True,
                 timeout: int | None = 30) -> subprocess.CompletedProcess:
    """Run a container runtime command."""
    runtime = _get_runtime()
    cmd = [runtime, *args]
    _log.debug("container: %s", " ".join(cmd))
    result = subprocess.run(
        cmd, capture_output=True, text=True,
        check=False, timeout=timeout,
    )
    if result.returncode != 0:
        _log.error("container runtime failed (rc=%d): %s\nstderr: %s\nstdout: %s",
                   result.returncode, " ".join(cmd),
                   result.stderr.strip()[:500], result.stdout.strip()[:200])
        if check:
            raise subprocess.CalledProcessError(
                result.returncode, cmd,
                output=result.stdout, stderr=result.stderr)
    return result


def current_container_id(name: str) -> str | None:
    """Full id of the container now holding *name*; "" if none, None if unknown."""
    result = _run_runtime("inspect", "-f", "{{.Id}}", name,
                          check=False, timeout=10)
    if result.returncode == 0:
        return result.stdout.strip() or None
    return "" if _container_absent(result.stderr or "") else None


def _container_absent(error: str) -> bool:
    """Only an explicit missing-object diagnostic proves absence, not socket ENOENT."""
    low = error.lower()
    return ("no such container" in low or "no such object" in low
            or "no container with" in low and "found" in low)


def container_is_running(name: str) -> bool:
    """Return True if a container with *name* exists and is running."""
    result = _run_runtime(
        "inspect", "-f", "{{.State.Running}}", name,
        check=False, timeout=10,
    )
    if result.returncode == 0 and result.stdout.strip() in ("true", "false"):
        return result.stdout.strip() == "true"
    error = (result.stderr or "").strip()
    if _container_absent(error):
        return False
    raise launch_error(name, classify_runtime_error(error),
                       error or "runtime returned an unknown running state",
                       stage="inspect existing container")


# ---------------------------------------------------------------------------
# Lifecycle state: locks, ownership labels, launch slots
# ---------------------------------------------------------------------------

# Written by the in-container setup script once git/user setup is done.
_READY_SENTINEL = "/tmp/.pm-ready"
# Written by the host only after the post-setup steps (``~/.pm`` ownership,
# ``.claude.json`` copy) succeeded.  Reuse requires this, not _READY_SENTINEL:
# a container whose setup timed out before the config copy has the first
# sentinel but would launch Claude into onboarding.
SETUP_COMPLETE_SENTINEL = "/tmp/.pm-setup-complete"

# Ownership labels (identical syntax under docker and podman).
LABEL_MANAGED = "pm.managed"
LABEL_SESSION = "pm.session_tag"
LABEL_PR = "pm.pr_id"
LABEL_KIND = "pm.kind"
LABEL_LOOP = "pm.loop_id"
LABEL_SCENARIO = "pm.scenario"
LABEL_ATTEMPT = "pm.attempt"
LABEL_CREATED = "pm.created"
LABEL_PROJECT = "pm.project_root"
LABEL_TMUX_SOCKET = "pm.tmux_socket"

_DEFAULT_LAUNCH_CONCURRENCY = 4


def container_state_dir() -> Path:
    """Directory for container lifecycle state (locks, retain markers, reaper log).

    ``PM_CONTAINER_STATE_DIR`` overrides it (tests, isolated QA homes).
    """
    env = os.environ.get("PM_CONTAINER_STATE_DIR")
    if env:
        return Path(env)
    return Path(os.path.expanduser("~")) / ".pm" / "containers"


def _lock_path(key: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in key)
    if len(safe) > 200:
        safe = safe[:150] + "-" + hashlib.sha256(key.encode()).hexdigest()[:16]
    return container_state_dir() / "locks" / f"{safe}.lock"


@contextlib.contextmanager
def _file_lock(key: str, *, timeout: float | None = None):
    """Exclusive cross-process lock (flock) on *key*.

    Yields True only when acquired.  ``timeout=0`` is a non-blocking try;
    timeout or an unavailable lock file yields False.  Lifecycle operations
    must not proceed without the exclusion that protects launches and owners.
    """
    path = _lock_path(key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o600)
    except OSError:
        _log.warning("lock %s unavailable; operation skipped", path, exc_info=True)
        yield False
        return
    acquired = False
    try:
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                # The reaper unlinks stale lock files while holding them; a
                # lock won on such an unlinked inode doesn't exclude whoever
                # opens the recreated path — reopen and try again.
                try:
                    current = os.stat(path).st_ino
                except FileNotFoundError:
                    current = None
                if current != os.fstat(fd).st_ino:
                    new_fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o600)
                    fcntl.flock(fd, fcntl.LOCK_UN)
                    os.close(fd)
                    fd = new_fd
                    continue
                acquired = True
                break
            except BlockingIOError:
                if deadline is not None and time.monotonic() >= deadline:
                    break
                time.sleep(0.05)
        yield acquired
    finally:
        if acquired:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
        os.close(fd)


def launch_lock(name: str, *, timeout: float | None = 300):
    """Per-container-name lock held by create/reuse and by the reaper's delete."""
    return _file_lock(f"container-{name}", timeout=timeout)


def launch_in_progress(name: str) -> bool:
    """True when a launch currently holds *name*'s launch lock.

    Probes without creating a lock file for names never launched here.
    """
    if not _lock_path(f"container-{name}").exists():
        return False
    with launch_lock(name, timeout=0) as free:
        return not free


def proxy_lock(session_tag: str, pr_id: str, *, timeout: float | None = 120):
    """Per shared-proxy lock: held from proxy start until the container exists,
    and while deciding whether an unused proxy can be stopped."""
    return _file_lock(f"proxy-{session_tag}-{pr_id}", timeout=timeout)


_create_semaphore: threading.BoundedSemaphore | None = None
_create_semaphore_lock = threading.Lock()


def _int_setting(name: str, default: int) -> int:
    """Integer global setting; *default* when unset, invalid or unreadable."""
    from pm_core.paths import get_global_setting_value
    try:
        return int(get_global_setting_value(name, str(default)))
    except (ValueError, OSError):
        return default


def _launch_concurrency() -> int:
    val = _int_setting("container-launch-concurrency", _DEFAULT_LAUNCH_CONCURRENCY)
    return val if val > 0 else _DEFAULT_LAUNCH_CONCURRENCY


def _create_slot() -> threading.BoundedSemaphore:
    """Process-wide bound on concurrent container creates (run + setup).

    Sized from ``container-launch-concurrency`` on first use; a changed
    setting applies to processes started afterwards.
    """
    global _create_semaphore
    with _create_semaphore_lock:
        if _create_semaphore is None:
            _create_semaphore = threading.BoundedSemaphore(_launch_concurrency())
        return _create_semaphore


def max_running_containers() -> int:
    """``container-max-running`` setting (0 = unlimited)."""
    return max(0, _int_setting("container-max-running", 0))


def _current_tmux_socket() -> str:
    sp = os.environ.get("PM_TMUX_SOCKET")
    if sp:
        return sp
    tmux_env = os.environ.get("TMUX", "")
    return tmux_env.split(",", 1)[0] if tmux_env else ""


def _current_project_root() -> str:
    try:
        from pm_core.store import find_project_root
        return str(find_project_root())
    except Exception:
        return ""


def _infer_kind(name: str) -> str:
    parsed = parse_container_name(name)
    return parsed.kind if parsed else "session"


def ownership_labels(name: str, *, session_tag: str | None, pr_id: str | None,
                     kind: str | None, loop_id: str | None = None,
                     scenario: int | None = None,
                     project_root: str | None = None) -> dict[str, str]:
    """Labels that let cleanup match a container to its exact owner."""
    labels = {
        LABEL_MANAGED: "1",
        LABEL_KIND: kind or _infer_kind(name),
        LABEL_ATTEMPT: uuid.uuid4().hex[:12],
        LABEL_CREATED: str(int(time.time())),
    }
    if session_tag:
        labels[LABEL_SESSION] = session_tag
    if pr_id:
        labels[LABEL_PR] = pr_id
    if loop_id:
        labels[LABEL_LOOP] = loop_id
    if scenario is not None:
        labels[LABEL_SCENARIO] = str(scenario)
    root = project_root if project_root is not None else _current_project_root()
    if root:
        labels[LABEL_PROJECT] = root
    sock = _current_tmux_socket()
    if sock:
        labels[LABEL_TMUX_SOCKET] = sock
    return labels


# ---------------------------------------------------------------------------
# Name parsing (legacy, unlabeled containers)
# ---------------------------------------------------------------------------

_CONTAINER_KINDS = ("qa-debug", "signoff", "review", "impl", "qa")


@dataclass
class ParsedContainerName:
    name: str
    kind: str
    session_tag: str | None
    rest: str  # text after "<kind>-": "<pr_id>[-<loop>-s<N>]"

    def pr_id(self, known_pr_ids: "set[str] | None" = None) -> str | None:
        """PR id embedded in the name.

        Session tags and PR ids both contain hyphens, so match against
        *known_pr_ids* when given; otherwise fall back to the ``pr-<hex>``
        shape pm generates.
        """
        if known_pr_ids:
            for pid in sorted(known_pr_ids, key=len, reverse=True):
                if self.rest == pid or self.rest.startswith(pid + "-"):
                    return pid
            return None
        import re
        m = re.match(r"(pr-[0-9a-f]+)(?:-|$)", self.rest)
        return m.group(1) if m else None


def parse_container_name(name: str) -> ParsedContainerName | None:
    """Decompose ``pm[-{tag}]-{kind}-{rest}`` (see :func:`_make_container_name`)."""
    if not name.startswith(CONTAINER_PREFIX):
        return None
    body = name[len(CONTAINER_PREFIX):]
    cands: list[ParsedContainerName] = []
    for kind in _CONTAINER_KINDS:
        if body.startswith(f"{kind}-"):
            cands.append(ParsedContainerName(name, kind, None, body[len(kind) + 1:]))
        i = body.rfind(f"-{kind}-")
        if i != -1:
            cands.append(ParsedContainerName(name, kind, body[:i],
                                             body[i + len(kind) + 2:]))
    if not cands:
        return None
    # A session tag may itself contain words like "review"; the real kind
    # marker is the one immediately followed by a pm PR id.
    with_pr = [c for c in cands if c.pr_id() is not None]
    if with_pr:
        return max(with_pr, key=lambda c: len(c.session_tag or ""))
    return min(cands, key=lambda c: len(c.session_tag or ""))


# ---------------------------------------------------------------------------
# Runtime error classification + keyring awareness
# ---------------------------------------------------------------------------

_KEYRING_SIGNATURES = (
    "session keyring",
    "create session key",
    "join session keyring",
)
_MEMORY_SIGNATURES = (
    "cannot allocate memory",
    "out of memory",
    "oom-kill",
    "oom killer",
    "memory: insufficient",
)
_PIDS_SIGNATURES = (
    "pids limit",
    "resource temporarily unavailable",
    "fork: retry",
    "cannot fork",
)


def classify_runtime_error(text: str | None) -> str:
    """Classify runtime stderr: keyring | memory | pids | image | runtime."""
    if not text:
        return "runtime"
    low = text.lower()
    if any(sig in low for sig in _KEYRING_SIGNATURES):
        return "keyring"
    if "disk quota exceeded" in low and "key" in low:
        return "keyring"
    if any(sig in low for sig in _MEMORY_SIGNATURES):
        return "memory"
    if any(sig in low for sig in _PIDS_SIGNATURES):
        return "pids"
    if "image not known" in low or "no such image" in low or "manifest unknown" in low:
        return "image"
    return "runtime"


_KEY_USERS_FILE = "/proc/key-users"


def keyring_usage(uid: int | None = None):
    """Parse ``/proc/key-users``: ``uid: usage nkeys/nikeys qnkeys/maxkeys qnbytes/maxbytes``.

    Returns ``{uid: {keys, max_keys, bytes, max_bytes}}`` (or one row for
    *uid*), or None when unreadable (non-Linux / restricted).
    """
    try:
        text = Path(_KEY_USERS_FILE).read_text()
    except OSError:
        return None
    rows: dict[int, dict[str, int]] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        head, rest = line.split(":", 1)
        try:
            uid_i = int(head.strip())
        except ValueError:
            continue
        parts = rest.split()
        if len(parts) < 4:
            continue
        try:
            nkeys, maxkeys = parts[2].split("/")
            nbytes, maxbytes = parts[3].split("/")
            rows[uid_i] = {"keys": int(nkeys), "max_keys": int(maxkeys),
                           "bytes": int(nbytes), "max_bytes": int(maxbytes)}
        except (IndexError, ValueError):
            continue
    if uid is not None:
        return rows.get(uid)
    return rows


def keyring_pressure(threshold: float = 0.9) -> dict | None:
    """Most-utilised keyring row if its key ratio is ≥ *threshold*, else None."""
    rows = keyring_usage()
    if not rows:
        return None
    worst = None
    for uid_i, row in rows.items():
        if row["max_keys"] <= 0:
            continue
        ratio = row["keys"] / row["max_keys"]
        if worst is None or ratio > worst["ratio"]:
            worst = {**row, "uid": uid_i, "ratio": ratio}
    if worst is not None and worst["ratio"] >= threshold:
        return worst
    return None


def keyring_summary() -> str:
    """One-line ``uid U: K/M keys`` for the most-utilised row, or ""."""
    worst = keyring_pressure(threshold=0.0)
    if not worst:
        return ""
    return (f"uid {worst['uid']}: {worst['keys']}/{worst['max_keys']} keys, "
            f"{worst['bytes']}/{worst['max_bytes']} bytes")


def running_container_count() -> int | None:
    """Number of running pm containers (the keyring-key holders); None if unknown."""
    from pm_core.container_reaper import list_containers
    inventory = list_containers()
    return None if inventory is None else sum(info.running for info in inventory)


_REMEDY_REAP = ("Preview leftover containers with 'pm container reap --dry-run' "
                "and remove them with 'pm container reap'.")


def launch_error(name: str, kind: str, stderr: str = "", *,
                 stage: str = "create") -> ContainerLaunchError:
    """Build a launch error that keeps the runtime's real message and a fix."""
    tail = (stderr or "").strip()
    if len(tail) > 600:
        tail = "…" + tail[-600:]
    cause = f" Runtime error: {tail}" if tail else ""
    if kind == "keyring":
        usage = keyring_summary()
        running = running_container_count()
        detail = []
        if usage:
            detail.append(f"keyring {usage}")
        if running is not None:
            detail.append(f"{running} running pm container(s)")
        extra = f" ({'; '.join(detail)})" if detail else ""
        msg = (f"Container '{name}' could not {stage}: the kernel session-keyring "
               f"quota is exhausted{extra}. Every running container holds keys, "
               f"so leaked containers block new launches (removing stopped "
               f"containers does not free keys). {_REMEDY_REAP} Raising "
               f"kernel.keys.maxkeys/maxbytes only adds headroom.{cause}")
    elif kind == "memory":
        msg = (f"Container '{name}' could not {stage}: the host is out of memory. "
               f"{_REMEDY_REAP} You can also lower 'pm container set memory-limit' "
               f"or 'pm set container-launch-concurrency'.{cause}")
    elif kind == "pids":
        msg = (f"Container '{name}' could not {stage}: its process/PID limit is "
               f"exhausted (runaway or zombie processes). Once no session needs "
               f"it, 'pm container restart {name}' clears it and keeps its files; "
               f"raising the limit only postpones the next exhaustion.{cause}")
    elif kind == "image":
        msg = (f"Container '{name}' could not {stage}: image not available. "
               f"Run 'pm container build'.{cause}")
    elif kind == "timeout":
        msg = (f"Container '{name}' setup did not finish ({stage}). The partial "
               f"container was removed. {_REMEDY_REAP}{cause}")
    else:
        msg = f"Container '{name}' could not {stage}.{cause}"
    return ContainerLaunchError(msg, kind=kind, stderr=stderr or "", name=name)


# ---------------------------------------------------------------------------
# Git push proxy integration
# ---------------------------------------------------------------------------


def _build_git_setup_script(
    has_push_proxy: bool = False,
    host_workdir: str | None = None,
    is_podman: bool = False,
) -> str:
    """Build a shell script snippet to configure git inside the container.

    This script runs at container start, configuring:
      - safe.directory for /workspace
      - A git wrapper that forwards ``git push`` to the host-side push proxy
        (if has_push_proxy is True)

    Under Docker (root), falls back to ``su - pm`` for git config.
    Under Podman (--userns=keep-id), the process is already the correct
    user, so direct git config works and ``su`` is not used.
    """
    lines: list[str] = []

    # Set safe directory for /workspace.
    if is_podman:
        # Already running as the correct user — direct git config works.
        lines.append(
            f"git config --global --add safe.directory {_CONTAINER_WORKDIR}"
        )
    else:
        # Use plain git config (works when already running as pm) with su
        # fallback (works when running as root in the default image).
        lines.append(
            f"git config --global --add safe.directory {_CONTAINER_WORKDIR} 2>/dev/null || "
            f"su - {_CONTAINER_USER} -c "
            f"'git config --global --add safe.directory {_CONTAINER_WORKDIR}'"
        )

    # Install the fake-claude shim onto PATH so the integration-test stand-in
    # resolves by bare name inside the container, exactly as the launcher
    # invokes it.  The shim resolves the actual binary via ``pm which`` *at run
    # time inside the container*, so it picks up whichever pm_core the wrapper
    # selects — e.g. the /workspace checkout under test for a pm-on-pm QA run,
    # not just the mounted /opt/pm-src.  ~/.local/bin is first on PATH; doing
    # it here (a runtime install, like the git wrapper below) avoids a
    # Dockerfile/PATH change and the image rebuild that would require.
    _fake_shim_path = f"{_CONTAINER_HOME}/.local/bin/fake-claude"
    _fake_shim = (
        "#!/bin/sh\n"
        "# pm: resolve fake-claude from the active pm install (pm which) so the\n"
        "# copy under test is used, even inside a container.\n"
        'core="$(pm which 2>/dev/null | tail -n1)"\n'
        "# A pipeline's status is tail's (almost always 0), so guard the value\n"
        "# itself: an empty core makes dirname yield '.' and exec a bogus path.\n"
        '[ -n "$core" ] || exit 127\n'
        'exec "$(dirname "$core")/bin/fake-claude" "$@"\n'
    )
    lines.append(
        f"mkdir -p {_CONTAINER_HOME}/.local/bin && "
        f"cat > {_fake_shim_path} << 'FAKEEOF'\n{_fake_shim}FAKEEOF\n"
        f"chmod 755 {_fake_shim_path}"
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
        # Install to the pm user's local bin — it's first on PATH in both
        # the default image and project-specific images, and doesn't need
        # root to write.  /usr/local/bin/git would require root which
        # project-specific images (USER pm) don't have.
        wrapper_path = f"{_CONTAINER_HOME}/.local/bin/git"
        lines.append(f"mkdir -p {_CONTAINER_HOME}/.local/bin && "
                     f"cat > {wrapper_path} << 'WRAPEOF'\n{wrapper_script}WRAPEOF\n"
                     f"chmod 755 {wrapper_path}")

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


_CONTAINER_PM_SRC = "/opt/pm-src"


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

def _runtime_domain_operation(func):
    """Bound runtime identity reuse to one synchronous lifecycle operation."""
    @functools.wraps(func)
    def wrapped(*args, **kwargs):
        from pm_core.container_reaper import runtime_domain_scope
        with runtime_domain_scope():
            return func(*args, **kwargs)
    return wrapped


@_runtime_domain_operation
def create_container(
    name: str,
    config: ContainerConfig,
    workdir: Path,
    extra_ro_mounts: dict[Path, str] | None = None,
    extra_rw_mounts: dict[Path, str] | None = None,
    allowed_push_branch: str | None = None,
    session_tag: str | None = None,
    pr_id: str | None = None,
    *,
    kind: str | None = None,
    loop_id: str | None = None,
    scenario: int | None = None,
    allocation_identity: dict[str, str] | None = None,
    reuse_identity: dict[str, str | None] | None = None,
) -> str:
    """Create a detached container with the workdir and claude mounted.

    The container's PID 1 is a reaping wait loop (see ``_PID1_REAPER``) and
    stays alive for ``docker exec -it`` from a tmux window.

    Automatically:
      - Bind-mounts the host's claude binary at /usr/local/bin/claude
      - Mounts ~/.claude read-write (for auth and session state)
      - Passes through Claude-related env vars
      - Applies resource limits from config
      - Starts a host-side push proxy for branch-scoped git push access
      - Labels the container with its owner (session, PR, kind, attempt,
        QA loop/scenario) so cleanup can match it exactly

    A running container with the same name is reused only when its setup
    verifiably completed (see :func:`_ensure_reusable`).  Any failure after
    ``run`` removes the partial container before raising, and runtime
    failures raise :class:`ContainerLaunchError` carrying the real stderr.

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
        kind / loop_id / scenario: ownership metadata recorded as labels.
        reuse_identity: prior ID/generation for a QA retry handing off its own
            allocation; otherwise live or still-attaching owners forbid reuse.

    Returns:
        Container ID.
    """
    with launch_lock(name) as _locked:
        if not _locked:
            raise launch_error(name, "runtime",
                               "another launch of this container is still in progress",
                               stage="acquire its launch lock")
        from pm_core import container_reaper
        # Recovery may restart an unowned allocation and renew its generation;
        # that new lease belongs to this launch, not a concurrent attaching one.
        was_attaching = recent_launch(name, container_reaper.LAUNCH_GRACE)
        prior_id = current_container_id(name) if was_attaching or reuse_identity else None
        same_owner = (bool(prior_id) and reuse_identity is not None
                      and reuse_identity.get("id") == prior_id
                      and reuse_identity.get("generation") == cleanup_generation(name))
        # Recovery can restart or remove an incomplete allocation. Protect the
        # create-to-pane gap before entering it, not just before renewing reuse.
        # Capture a QA handoff now: recovery itself may advance its generation.
        if was_attaching and prior_id != "" and not same_owner:
            raise launch_error(
                name, "runtime", "container is still owned by an attaching launch; "
                "use that session or wait for it to finish", stage="be reused")
        reused = _ensure_reusable(name, workdir, allowed_push_branch,
                                  session_tag=session_tag, pr_id=pr_id)
        if reused:
            same_owner = same_owner and prior_id == reused
            if not same_owner:
                owners = container_reaper.live_owner_panes(name, reused)
                if owners or was_attaching:
                    raise launch_error(
                        name, "runtime",
                        "container is still owned by a live session or an attaching launch; "
                        "use that session or wait for it to finish",
                        stage="be reused")
            _renew_launch(name, reused)
            if allocation_identity is not None:
                allocation_identity.update(id=reused, generation=cleanup_generation(name))
            return reused
        with _create_slot():
            container_id = _create_fresh(
                name, config, workdir,
                extra_ro_mounts=extra_ro_mounts,
                extra_rw_mounts=extra_rw_mounts,
                allowed_push_branch=allowed_push_branch,
                session_tag=session_tag, pr_id=pr_id,
                labels=ownership_labels(name, session_tag=session_tag,
                                        pr_id=pr_id, kind=kind,
                                        loop_id=loop_id, scenario=scenario),
            )
            try:
                _renew_launch(name, container_id)
                if allocation_identity is not None:
                    allocation_identity.update(id=container_id, generation=cleanup_generation(name))
            except ContainerError:
                discard_container(name)
                raise
            return container_id


# Container PID 1 after setup: wait forever, reaping adopted children; exit
# promptly on stop instead of waiting out the runtime's kill timeout.
_PID1_REAPER = "trap 'exit 0' TERM; while :; do sleep 86400 & wait $!; done"


def _host_claude_json() -> Path:
    return Path.home() / ".claude.json"


def _setup_complete(name: str) -> bool:
    """True when the host-side post-setup finished (config copied)."""
    return _probe_setup(name)[0]


def _probe_setup(name: str) -> tuple[bool, str, str]:
    """``(complete, exec_failure_kind, stderr)`` for a running container.

    *exec_failure_kind* is non-empty when the probe could not even run
    inside the container and the runtime said why (``pids``, ``memory``,
    ``keyring``) — the container is wedged, not merely unfinished.
    """
    check = f"test -f {SETUP_COMPLETE_SENTINEL}"
    if _host_claude_json().exists():
        check += f" && test -s {_CONTAINER_HOME}/.claude.json"
    r = _run_runtime("exec", name, "sh", "-c", check, check=False, timeout=15)
    if r.returncode == 0:
        return True, "", ""
    stderr = (r.stderr or "").strip()
    kind = classify_runtime_error(stderr)
    if kind in ("pids", "memory", "keyring"):
        return False, kind, stderr
    if r.returncode != 1 or stderr:
        raise launch_error(name, kind, stderr or f"setup probe exited {r.returncode}",
                           stage="verify existing setup")
    return False, "", ""


def _restart_generation_path(name: str, *, for_write: bool = False) -> Path:
    """Generation belongs to a runtime domain, not merely a reusable name.

    Read pre-domain markers for compatibility until this domain has its own
    marker. Unknown runtime identity cannot write state or fall back to a
    legacy generation after scoped state exists.
    """
    from pm_core.container_reaper import _runtime_domain
    domain = _runtime_domain()
    legacy = _lock_path(f"restart-{name}").with_suffix(".generation")
    name_key = hashlib.sha256(name.encode()).hexdigest()
    directory = container_state_dir() / "generations" / name_key
    if domain is None:
        if for_write or any(directory.glob("*.generation")):
            raise OSError(f"Cannot determine runtime domain for container '{name}' generation")
        return legacy
    domain_key = hashlib.sha256(json.dumps(domain, sort_keys=True).encode()).hexdigest()
    scoped = directory / f"{domain_key}.generation"
    if not for_write and not scoped.exists():
        return legacy
    return scoped


def canonical_container_name(name: str) -> str:
    """Resolve runtime ID/slash aliases before using name-keyed lifecycle locks."""
    if name.startswith(CONTAINER_PREFIX):
        return name
    result = _run_runtime("inspect", "--format", "{{.Name}}", name,
                          check=False, timeout=10)
    canonical = result.stdout.strip().lstrip("/")
    managed = canonical.startswith(CONTAINER_PREFIX)
    if result.returncode == 0 and canonical and not managed:
        labels = _run_runtime("inspect", "--format", '{{index .Config.Labels "pm.managed"}}',
                              name, check=False, timeout=10)
        managed = labels.returncode == 0 and labels.stdout.strip() == "1"
    if result.returncode != 0 or not managed:
        raise ContainerError(
            f"Cannot resolve managed container '{name}': "
            f"{(result.stderr or '').strip() or 'expected a pm container name or managed label'}")
    return canonical


def cleanup_generation(name: str) -> str:
    """Read the recovery generation; unreadable state must not authorize cleanup."""
    try:
        return _restart_generation_path(name).read_text().strip()
    except FileNotFoundError:
        return ""


def _identity_generation_path(container_id: str) -> Path:
    """Rename-stable recovery epoch within one runtime store."""
    from pm_core.container_reaper import _runtime_domain
    domain = _runtime_domain()
    if domain is None:
        raise OSError("Cannot determine runtime domain for allocation generation")
    key = hashlib.sha256(json.dumps([domain, container_id], sort_keys=True).encode()).hexdigest()
    return container_state_dir() / "identity-generations" / f"{key}.generation"


def _write_identity_generation(container_id: str, generation: str) -> None:
    marker = _identity_generation_path(container_id)
    marker.parent.mkdir(parents=True, exist_ok=True)
    temporary = marker.with_suffix(f".{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(generation)
        os.replace(temporary, marker)
    finally:
        temporary.unlink(missing_ok=True)


def _renew_launch(name: str, container_id: str = "") -> None:
    """Give an attaching owner a new generation and a bounded attachment lease.

    Called under the launch lock after successful create/reuse. Previous EXIT
    releases must not authorize deletion of this new ownership epoch.
    """
    try:
        marker = _restart_generation_path(name, for_write=True)
        marker.parent.mkdir(parents=True, exist_ok=True)
        generation = uuid.uuid4().hex
        marker.write_text(generation)
        if container_id:
            _write_identity_generation(container_id, generation)
    except OSError as exc:
        raise launch_error(name, "runtime", str(exc),
                           stage="record launch ownership") from exc


def recent_launch(name: str, grace: float, container_id: str | None = None) -> bool:
    """Protect attachment by name and by rename-stable allocation identity."""
    now = time.time()
    try:
        if now - _restart_generation_path(name).stat().st_mtime < grace:
            return True
    except FileNotFoundError:
        pass
    # Older installations may only have name generations. Avoid another runtime
    # inspection until ID generations exist; inventory callers already know the ID.
    if container_id is None:
        if not (container_state_dir() / "identity-generations").exists():
            return False
        container_id = current_container_id(name)
        if container_id is None:
            raise OSError("Cannot determine allocation identity for attachment lease")
    if container_id:
        try:
            return now - _identity_generation_path(container_id).stat().st_mtime < grace
        except FileNotFoundError:
            pass
    return False


@_runtime_domain_operation
def restart_container(name: str) -> None:
    """Restart *name* in place: ends every process inside (clearing PID or
    memory exhaustion) but keeps the container's filesystem, id and mounts.

    Setup state lives in the container filesystem, so a restarted container
    is still fully set up; this re-verifies that before returning.
    """
    # Callers hold the canonical name's launch lock (CLI resolves ID aliases).
    # Restart terminates attached exec clients. Their delayed EXIT traps must
    # not remove the very filesystem this recovery is meant to preserve.
    # Keep the new generation after restart: an old trap can arrive much later.
    try:
        marker = _restart_generation_path(name, for_write=True)
        marker.parent.mkdir(parents=True, exist_ok=True)
        generation = uuid.uuid4().hex
        marker.write_text(generation)
        container_id = current_container_id(name)
        if not container_id:
            raise OSError("container identity unavailable before restart")
        _write_identity_generation(container_id, generation)
    except OSError as exc:
        raise ContainerError(f"Cannot protect '{name}' from EXIT cleanup during restart: {exc}") from exc
    r = _run_runtime("restart", "-t", "5", name, check=False, timeout=90)
    if r.returncode != 0:
        stderr = (r.stderr or "").strip()
        raise launch_error(name, classify_runtime_error(stderr), stderr,
                           stage="restart")
    try:
        _wait_for_setup(name)
    except ContainerLaunchError as e:
        if e.kind != "timeout":
            raise
        # The "timeout" message says the partial container was removed —
        # true for a fresh create, not here: the restarted container stays.
        raise launch_error(name, "runtime", e.stderr,
                           stage="come back up after restart") from e
    if not _setup_complete(name):
        raise launch_error(name, "incomplete",
                           "setup markers missing after restart", stage="restart")


def pids_usage() -> dict[str, tuple[int, int]] | None:
    """``{name: (pids, limit)}`` for running pm containers (limit 0 = none).

    Read from the runtime's cgroup stats, so it works even when the
    container is too exhausted to ``exec`` into.  None if unavailable.
    """
    try:
        st = _run_runtime("stats", "--no-stream", "--format",
                          "{{.Name}}\t{{.PIDs}}", check=False, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if st.returncode != 0:
        return None
    from pm_core.container_reaper import list_containers
    inventory = list_containers()
    if inventory is None:
        return None
    managed = {info.name for info in inventory}
    current: dict[str, int] = {}
    for line in (st.stdout or "").splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] in managed:
            try:
                current[parts[0]] = int(parts[1])
            except ValueError:
                continue
    if not current:
        return {}
    try:
        insp = _run_runtime("inspect", "--format",
                            "{{.Name}}\t{{.HostConfig.PidsLimit}}", *current,
                            check=False, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        insp = None
    limits: dict[str, int] = {}
    for line in ((insp.stdout if insp else "") or "").splitlines():
        parts = line.split()
        if len(parts) == 2:
            try:
                limits[parts[0].lstrip("/")] = max(0, int(parts[1]))
            except ValueError:
                continue
    return {n: (c, limits.get(n, 0)) for n, c in current.items()}


def pids_pressure(threshold: float = 0.9) -> list[tuple[str, int, int]]:
    """Running pm containers at ≥ *threshold* of their PID limit."""
    usage = pids_usage() or {}
    return sorted((n, c, lim) for n, (c, lim) in usage.items()
                  if lim > 0 and c >= threshold * lim)


def _ensure_reusable(name: str, workdir: Path, allowed_push_branch: str | None,
                     *, session_tag: str | None, pr_id: str | None) -> str | None:
    """Return the id of a running, fully set-up container named *name*.

    "Running" is not enough: setup may have timed out before the
    ``.claude.json`` copy (Claude would start in onboarding) or the push
    proxy may be gone.  An incomplete container is finished in place when its
    in-container setup ran, else removed (returns None → caller recreates).
    A container that cannot be finished but has a live owning pane is not
    killed — that raises instead.
    """
    from pm_core import container_reaper
    if not container_is_running(name):
        # A retained allocation may have been renamed, so a name-only filter
        # cannot rule it out. Resolve the ID whenever retention records exist.
        if container_reaper.retained_names():
            cid = current_container_id(name)
            if cid is None or cid and container_reaper.is_retained(name, cid):
                raise launch_error(name, "incomplete", "container is explicitly retained or its identity is unknown; release it before recreation",
                                   stage="be reused")
        return None
    container_id = current_container_id(name)
    if not container_id:
        raise launch_error(name, "runtime", "existing container identity unavailable",
                           stage="be reused")

    complete, wedged, probe_err = _probe_setup(name)
    retained = container_reaper.is_retained(name, container_id)
    if retained and wedged in ("pids", "memory"):
        raise launch_error(name, wedged, f"{probe_err}\nContainer is explicitly retained; restart it explicitly.",
                           stage="be reused")
    if wedged in ("pids", "memory"):
        # Can't exec: the container's own processes exhausted it.  Restart
        # clears that and keeps its files, but ends every session inside —
        # so only when nothing owns it.
        from pm_core import container_reaper
        try:
            owners = container_reaper.live_owner_panes(name, container_id)
        except ContainerError as exc:
            raise launch_error(name, wedged, f"{probe_err}\n{exc}",
                               stage="be reused") from exc
        if owners:
            raise launch_error(
                name, wedged,
                f"{probe_err}\n(live pane(s) {', '.join(owners)} still use it, "
                f"so pm will not restart it)", stage="be reused")
        _log.warning("Container %s is exhausted (%s) and unowned — restarting "
                     "it in place", name, wedged)
        try:
            restart_container(name)
            complete = True
        except ContainerError:
            _log.warning("Restart of %s failed — preserving its filesystem", name, exc_info=True)
            raise
    elif wedged == "keyring":
        # Host-wide quota, not this container's fault: recreating won't help.
        raise launch_error(name, "keyring", probe_err, stage="be reused")

    if not complete:
        _log.warning("Container %s is running but its setup never completed", name)
        finished = False
        base = _run_runtime("exec", name, "test", "-f", _READY_SENTINEL,
                            check=False, timeout=10)
        if base.returncode == 0:
            _post_setup(name, workdir, "podman" in _get_runtime())
            finished = _setup_complete(name)
        elif base.returncode != 1 or (base.stderr or "").strip():
            raise launch_error(name, "runtime", (base.stderr or "").strip()
                               or f"readiness probe exited {base.returncode}",
                               stage="verify existing setup")
        if not finished:
            if retained:
                raise launch_error(name, "incomplete", "container is explicitly retained; release it before recreation",
                                   stage="be reused")
            if container_reaper.live_owner_panes(name, container_id):
                raise launch_error(
                    name, "incomplete",
                    "container setup is incomplete and a live pane still uses it",
                    stage="be reused")
            _log.warning("Removing incomplete container %s before recreating", name)
            remove_container(name)
            return None
        _log.info("Finished incomplete setup of container %s in place", name)

    _log.info("Reusing existing container %s (id=%s)", name, container_id[:12])
    # Ensure the push proxy is running (it may have died in a crash)
    if allowed_push_branch:
        from pm_core.push_proxy import (
            start_push_proxy, proxy_is_alive,
        )
        guard = (proxy_lock(session_tag, pr_id) if session_tag and pr_id
                 else contextlib.nullcontext(True))
        with guard as locked:
            if not locked:
                raise launch_error(name, "proxy", "shared proxy lock unavailable", stage="be reused")
            # Always pass through start_push_proxy's domain validation, even
            # when a healthy socket already exists. Serialize dead-socket repair.
            if session_tag and pr_id:
                from pm_core.push_proxy import validate_shared_proxy_mount
                validate_shared_proxy_mount(name, session_tag, pr_id)
                sock = start_push_proxy(name, str(workdir), allowed_push_branch,
                                        session_tag=session_tag, pr_id=pr_id)
            else:
                from pm_core.push_proxy import repair_unshared_proxy
                sock = repair_unshared_proxy(name, str(workdir), allowed_push_branch)
            if not proxy_is_alive(sock):
                raise launch_error(name, "proxy",
                                   f"push proxy at {sock} is not accepting connections",
                                   stage="be reused")
    return container_id


def _create_fresh(
    name: str,
    config: ContainerConfig,
    workdir: Path,
    *,
    extra_ro_mounts: dict[Path, str] | None,
    extra_rw_mounts: dict[Path, str] | None,
    allowed_push_branch: str | None,
    session_tag: str | None,
    pr_id: str | None,
    labels: dict[str, str],
) -> str:
    """Create a new container (caller holds the launch lock and a slot)."""
    remove_container(name)

    # Auto-build the pm-dev image if it's the default and not yet built.
    # Use a lock so concurrent create_container calls don't all build at once.
    if config.image == DEFAULT_IMAGE and not image_exists(config.image):
        with _build_lock:
            if not image_exists(config.image):
                _log.info("Default image %s not found — building automatically", config.image)
                build_image(tag=config.image, quiet=True)
    elif config.image != DEFAULT_IMAGE and not image_exists(config.image):
        runtime = _get_runtime()
        raise ContainerError(
            f"Image '{config.image}' not found in {runtime}. "
            f"Run 'pm container build' to rebuild it, or "
            f"'pm container build-base' for the base image."
        )

    runtime = _get_runtime()
    cmd = [
        "run", "-d",
        "--name", name,
    ]
    # Resource caps need delegated cgroup controllers.  Under nested
    # rootless podman the controllers usually aren't delegated to the
    # inner user's subtree (cgroupfs manager, empty cgroupControllers), so
    # crun can't create the container cgroup and ``podman run`` dies with
    # "could not find cgroup mount in /proc/self/cgroup" before the
    # workload starts.  Skip the limits there — they're unenforceable in
    # that environment anyway — matching the relaxed-sandbox intent of the
    # nested_podman opt-in (see _nested_podman_run_args).
    if not ("podman" in runtime and _nested_podman_enabled()):
        cmd += ["--memory", config.memory_limit, "--cpus", config.cpu_limit]
    cmd += [
        "-v", f"{workdir}:{_CONTAINER_WORKDIR}",
        "-w", _CONTAINER_WORKDIR,
    ]

    # Captures bind-mount: ~/.pm/sessions/<tag>/captures/<pr_id>/ on host
    # → /pm-captures inside the container. Lets QA scenario workers (and
    # any other in-container workers for the same PR) write recordings,
    # transcripts, manifests, and verdicts to a path that's durable on
    # the host without committing them to the project repo. Workers
    # resolve the path via :func:`paths.captures_dir`, which falls
    # through to the mount when the host path isn't visible.
    if session_tag and pr_id:
        try:
            from pm_core.paths import (captures_dir, CAPTURES_PR_ENV,
                                       CONTAINER_CAPTURES_MOUNT)
            host_captures = captures_dir(pr_id, session_tag=session_tag)
            if host_captures is not None:
                cmd.extend(["-v",
                            f"{host_captures}:{CONTAINER_CAPTURES_MOUNT}",
                            "-e", f"{CAPTURES_PR_ENV}={pr_id}"])
        except Exception:
            _log.warning("Failed to resolve captures dir for pr=%s tag=%s",
                         pr_id, session_tag, exc_info=True)

    # Podman rootless: map host UID into the container without manual
    # useradd/groupadd.  Harmless under Podman rootful (no-op).
    if "podman" in runtime:
        cmd.extend(["--userns=keep-id"])
        if _nested_podman_enabled():
            cmd.extend(_nested_podman_run_args())

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

    # ~/.pm/hooks bind-mount: Claude Code hooks installed at startup write
    # idle_prompt / Stop event files keyed by session_id.  When Claude runs
    # inside this container, the hook receiver writes *inside* the
    # container — mounting the host's ~/.pm/hooks at the container user's
    # HOME makes those events visible to pm on the host (the receiver
    # computes its output path via ``Path.home() / ".pm" / "hooks"``, which
    # resolves to $CONTAINER_HOME/.pm/hooks inside the container).
    pm_hooks_dir = Path.home() / ".pm" / "hooks"
    try:
        pm_hooks_dir.mkdir(parents=True, exist_ok=True)
        cmd.extend(["-v", f"{pm_hooks_dir}:{_CONTAINER_HOME}/.pm/hooks"])
    except OSError:
        _log.debug("could not create %s; hook events from container will fall back to polling", pm_hooks_dir)

    # Standalone hook receiver: the command embedded in
    # ~/.claude/settings.json references the receiver at its *host*
    # absolute path (e.g. /home/<user>/.pm/hook_receiver.py).  Bind-mount
    # that exact path into the container so the same command works on
    # the host and inside the container — no pm_core import required.
    # Path is derived directly (no pm_core.hook_install import) to keep
    # create_container import-clean for tests that patch Path internals.
    _receiver_path = Path.home() / ".pm" / "hook_receiver.py"
    if _receiver_path.is_file():
        cmd.extend(["-v", f"{_receiver_path}:{_receiver_path}:ro"])
    else:
        _log.debug("hook receiver %s missing; containerised Claude hooks will no-op",
                   _receiver_path)

    # pm source: bind-mount read-only so the setup script can ``pip install``
    # it into the container.  Makes the ``pm`` CLI available inside any
    # container regardless of target project — the wrapper still prefers a
    # local ``pm_core`` under /workspace when running in a pm PR workdir.
    # The repo root is the parent of the pm_core package dir (same path
    # ``pm which`` prints) when pm is installed editably — the only install
    # mode ``install.sh`` produces today.
    from pm_core.paths import pm_core_path
    _pm_src = pm_core_path().parent
    cmd.extend(["-v", f"{_pm_src}:{_CONTAINER_PM_SRC}:ro"])

    # NOTE: .claude.json is NOT bind-mounted.  Claude writes it atomically
    # (write tmp + rename) which replaces the inode — a single-file bind
    # mount keeps the old inode so the container sees stale content.
    # Instead we copy it in after the container is created (_post_setup).

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

    # PM_HOST_HOME tells code inside the container (notably
    # pm_core.hook_install) to embed the host's home path in any file
    # that is bind-mounted back to the host (~/.claude/settings.json).
    # Without this, hook commands written from the container would
    # reference /home/pm/... which does not exist on the host.
    cmd.extend(["-e", f"PM_HOST_HOME={Path.home()}"])

    for k, v in config.env.items():
        cmd.extend(["-e", f"{k}={v}"])

    # Extra mounts from config (user-specified, e.g. data dirs)
    for mount in config.extra_mounts:
        cmd.extend(["-v", mount])

    # --- Ownership labels ---
    for k, v in labels.items():
        cmd.extend(["--label", f"{k}={v}"])

    # --- Create pm user with matching uid/gid, configure git, then sleep ---
    # A readiness sentinel file is written after the in-container setup so
    # callers can tell when the git wrapper exists; the host then finishes
    # the remaining steps (_post_setup) and writes SETUP_COMPLETE_SENTINEL.
    host_uid = os.getuid()
    host_gid = os.getgid()
    # Propagate host git identity so container commits use the right author
    git_name = subprocess.run(
        ["git", "config", "user.name"], capture_output=True, text=True,
    ).stdout.strip()
    git_email = subprocess.run(
        ["git", "config", "user.email"], capture_output=True, text=True,
    ).stdout.strip()

    _is_podman = "podman" in runtime

    # Keys held by leaked running containers are what exhaust the rootless
    # keyring; when it is nearly full, reap orphans before adding another.
    _relieve_keyring_pressure()

    # --- Git push proxy ---
    # If an allowed push branch is set, start a host-side push proxy.
    # The proxy socket is mounted into the container; credentials stay
    # on the host.  The proxy handles all origin types: real remotes
    # (HTTP/SSH), local-path origins (from git clone --local), and
    # repos with no remote (push fails cleanly).  The shared-proxy lock is
    # held until the container exists so a concurrent cleanup that sees
    # "no container for this PR" cannot stop the proxy we're mounting.
    shared_proxy = bool(allowed_push_branch and session_tag and pr_id)
    proxy_guard = (proxy_lock(session_tag, pr_id) if shared_proxy
                   else contextlib.nullcontext(True))
    with _discard_on_failure(name), proxy_guard as proxy_locked:
        if not proxy_locked:
            raise launch_error(name, "proxy", "another operation still holds the proxy lock",
                               stage="acquire its shared proxy lock")
        has_push_proxy = False
        if allowed_push_branch:
            from pm_core.push_proxy import start_push_proxy, _CONTAINER_SOCKET_DIR
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

        git_setup = _build_git_setup_script(
            has_push_proxy=has_push_proxy,
            host_workdir=str(workdir) if has_push_proxy else None,
            is_podman=_is_podman)
        if _is_podman:
            # Podman with --userns=keep-id: the host UID is already mapped into
            # the container.  No user creation needed (and we're not root, so
            # groupadd/useradd would fail).  Just ensure /home/pm exists and
            # set HOME explicitly so git config writes to the right place.
            setup_parts = [
                f"mkdir -p {_CONTAINER_HOME}",
                f"export HOME={_CONTAINER_HOME}",
            ]
        else:
            # Docker: runs as root, create the pm user.  No-ops when the image
            # already has the pm user (e.g. project-specific images).
            setup_parts = [
                f"groupadd -g {host_gid} {_CONTAINER_USER} 2>/dev/null || true",
                f"useradd -u {host_uid} -g {host_gid} -m -s /bin/bash {_CONTAINER_USER} 2>/dev/null || true",
                f"chown {host_uid}:{host_gid} {_CONTAINER_HOME} 2>/dev/null || true",
            ]
        if git_name and git_email:
            if _is_podman:
                # Already running as the correct user — direct git config works.
                setup_parts.append(
                    f"git config --global user.name \"{git_name}\" && "
                    f"git config --global user.email \"{git_email}\""
                )
            else:
                # Try as current user first (works when running as pm), fall back
                # to su (works when running as root in the default image).
                setup_parts.append(
                    f"(git config --global user.name \"{git_name}\" && "
                    f"git config --global user.email \"{git_email}\") 2>/dev/null || "
                    f"su -c 'git config --global user.name \"{git_name}\" && "
                    f"git config --global user.email \"{git_email}\"' {_CONTAINER_USER}"
                )
        if git_setup:
            setup_parts.append(git_setup)
        # pm is made available inside the container via a shim at
        # /usr/local/bin/pm (installed in the base image) that execs
        # ``python3 -m pm_core.wrapper``, picking up pm_core through
        # PYTHONPATH=/opt/pm-src.  No per-container install step — keeping
        # container startup fast enough to beat the QA grace period.
        setup_parts.append(f"touch {_READY_SENTINEL}")
        # PID 1 must reap: processes orphaned inside the container are
        # reparented to it, and ``sleep`` never waits on them, so zombies
        # pile up against the PID limit until exec fails "Cannot fork".
        # bash's SIGCHLD handling reaps any child while it sits in ``wait``.
        setup_parts.append(_PID1_REAPER)
        # Required setup must stop before readiness on any failure. Do not
        # carry errexit into PID 1: an interrupted wait is normal on restart.
        setup = "set -e; " + "; ".join(setup_parts[:-1]) + "; set +e; " + setup_parts[-1]
        cmd.extend([config.image, "bash", "-c", setup])

        run_error: BaseException | None = None
        try:
            result = _run_runtime(*cmd, timeout=60, check=False)
            if result.returncode != 0:
                stderr = ((result.stderr or "").strip()
                          or (result.stdout or "").strip())
                run_error = launch_error(name, classify_runtime_error(stderr),
                                         stderr, stage="start")
        except subprocess.TimeoutExpired as exc:
            run_error = launch_error(
                name, "timeout",
                f"'{runtime} run' did not return within {exc.timeout}s",
                stage="start")
        except OSError as exc:
            run_error = launch_error(name, classify_runtime_error(str(exc)),
                                     str(exc), stage="start")
        except BaseException as exc:
            # Cancellation can arrive after run created the allocation. Defer
            # cleanup until the shared-proxy lock has been released below.
            run_error = exc

    if run_error is not None:
        # podman may leave a "created" container behind on failure.  Discard
        # outside the proxy lock: the removal re-takes it to decide whether
        # the shared proxy is now unused.
        discard_container(name)
        raise run_error
    container_id = result.stdout.strip()

    try:
        _wait_for_setup(name)
        _post_setup(name, workdir, _is_podman)
        if allowed_push_branch:
            from pm_core.push_proxy import proxy_is_alive
            if not proxy_is_alive(sock_path):
                raise launch_error(name, "proxy",
                                   f"push proxy at {sock_path} is not accepting connections",
                                   stage="finish setup")
    except BaseException:
        _log.error("Container %s setup failed — removing the partial container",
                   name, exc_info=True)
        discard_container(name)
        raise

    _log.info("Created container %s (id=%s)", name, container_id[:12])
    return container_id


_SETUP_TIMEOUT = 30  # seconds — needs headroom under memory pressure
_SETUP_POLL_INTERVAL = 0.2


def _wait_for_setup(name: str) -> None:
    """Wait for the in-container setup script to write its sentinel.

    The setup installs the git push-proxy wrapper and configures the
    user — if we proceed before it completes, the wrapper won't exist
    and git push will bypass the proxy, failing with no credentials.
    A probe failure the runtime classifies (keyring, memory) fails fast
    with the real error instead of waiting out the timeout.
    """
    last_err = ""
    deadline = time.monotonic() + _SETUP_TIMEOUT
    while time.monotonic() < deadline:
        check = _run_runtime(
            "exec", name, "test", "-f", _READY_SENTINEL,
            check=False, timeout=5,
        )
        if check.returncode == 0:
            return
        err = (check.stderr or "").strip()
        if err:
            last_err = err
            kind = classify_runtime_error(err)
            if kind in ("keyring", "memory", "pids"):
                raise launch_error(name, kind, err, stage="finish setup")
            if "is not running" in err.lower() or "no such container" in err.lower():
                logs = _run_runtime("logs", "--tail", "20", name,
                                    check=False, timeout=10)
                raise launch_error(
                    name, "runtime",
                    f"{err}\n{(logs.stdout or '') + (logs.stderr or '')}".strip(),
                    stage="finish setup")
        time.sleep(_SETUP_POLL_INTERVAL)
    _log.error("Container %s setup did not complete within %ds — "
               "git push proxy wrapper may not be installed",
               name, _SETUP_TIMEOUT)
    raise launch_error(name, "timeout",
                       last_err or f"setup sentinel missing after {_SETUP_TIMEOUT}s",
                       stage=f"finish setup within {_SETUP_TIMEOUT}s")


def _post_setup(name: str, workdir: Path, is_podman: bool) -> None:
    """Host-side setup steps, then write SETUP_COMPLETE_SENTINEL.

    Idempotent, so an incomplete reused container can be finished in place.
    The ``.claude.json`` copy is required whenever the host has one —
    without it Claude starts in onboarding.
    """
    host_uid = os.getuid()
    host_gid = os.getgid()
    # Repair ownership of ~/.pm inside the container.  When we bind-mount
    # ~/.pm/hooks, the container runtime auto-creates the parent
    # /home/pm/.pm as root-owned (uid 0 in the container's user namespace).
    # That blocks the pm user from creating siblings under ~/.pm (debug
    # logs, session registry, etc.) which crashes any ``pm`` invocation
    # inside the container on first logger setup.  Chown as root — under
    # podman with --userns=keep-id the container command runs as the pm
    # user and cannot chown a root-owned path, so we need an explicit
    # --user 0 exec; under docker the default exec user is already root.
    try:
        exec_args = ["exec"]
        if is_podman:
            exec_args.extend(["--user", "0"])
        exec_args.extend([
            name, "chown", f"{host_uid}:{host_gid}",
            f"{_CONTAINER_HOME}/.pm",
        ])
        ownership = _run_runtime(*exec_args, timeout=5, check=False)
    except subprocess.TimeoutExpired as exc:
        raise launch_error(name, "timeout", "chown of ~/.pm timed out",
                           stage="repair ~/.pm ownership") from exc
    except OSError as exc:
        raise launch_error(name, "runtime", str(exc),
                           stage="repair ~/.pm ownership") from exc
    if ownership.returncode != 0:
        stderr = (ownership.stderr or "").strip()
        raise launch_error(name, classify_runtime_error(stderr),
                           stderr or "chown of ~/.pm failed",
                           stage="repair ~/.pm ownership")

    # Copy .claude.json into the container (not bind-mounted — see note above)
    _claude_json_src = _host_claude_json()
    if _claude_json_src.exists():
        # Seed workspace trust for the container's workdir when the mounted
        # host workdir is pm-created or explicitly authorized; otherwise
        # copy the config verbatim and leave the prompt explicit.  The host
        # file is never modified for the container-internal path.
        _cfg_copy_src = _claude_json_src
        _seeded_tmp: Path | None = None
        try:
            from pm_core import workspace_trust
            if workspace_trust.approved_path(workdir):
                import tempfile
                fd, _tmp = tempfile.mkstemp(prefix="pm-claude-json-")
                os.close(fd)
                _seeded_tmp = Path(_tmp)
                if workspace_trust.get_trust_runtime().seed_config(
                        _claude_json_src, _seeded_tmp, [_CONTAINER_WORKDIR]):
                    _cfg_copy_src = _seeded_tmp
                    _log.info("workspace trust: seeded %s trust for "
                              "container %s (host workdir %s)",
                              _CONTAINER_WORKDIR, name, workdir)
            else:
                _log.info("workspace trust: %s not approved; container %s "
                          "keeps the explicit trust prompt", workdir, name)
        except Exception:
            _log.warning("workspace trust: could not seed config for "
                         "container %s", name, exc_info=True)
        try:
            _run_runtime("cp", str(_cfg_copy_src),
                         f"{name}:{_CONTAINER_HOME}/.claude.json",
                         timeout=10)
            # Under Docker (root), fix ownership so the pm user can read it.
            # Under Podman (--userns=keep-id), the file already has the
            # correct ownership via namespace mapping, and chown would fail
            # because the process is not root.
            if not is_podman:
                _run_runtime("exec", name, "chown",
                             f"{host_uid}:{host_gid}",
                             f"{_CONTAINER_HOME}/.claude.json",
                             timeout=5)
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").strip()
            raise launch_error(name, classify_runtime_error(stderr) if stderr else "config",
                               stderr or "copying ~/.claude.json failed",
                               stage="receive ~/.claude.json") from exc
        except subprocess.TimeoutExpired as exc:
            raise launch_error(name, "timeout", "copying ~/.claude.json timed out",
                               stage="receive ~/.claude.json") from exc
        finally:
            if _seeded_tmp is not None:
                _seeded_tmp.unlink(missing_ok=True)

    done = _run_runtime("exec", name, "touch", SETUP_COMPLETE_SENTINEL,
                        check=False, timeout=10)
    if done.returncode != 0:
        stderr = (done.stderr or "").strip()
        raise launch_error(name, classify_runtime_error(stderr), stderr,
                           stage="record completed setup")


@contextlib.contextmanager
def _discard_on_failure(name: str):
    """Cover pre-run proxy/setup failures after any inner proxy lock unwinds."""
    try:
        yield
    except BaseException:
        discard_container(name)
        raise


def discard_container(name: str) -> None:
    """Best-effort removal of a container whose launch failed or was abandoned
    before a pane attached to it (never raises)."""
    if not name:
        return
    try:
        remove_container(name)
    except Exception:
        _log.warning("Could not remove container %s", name, exc_info=True)


@_runtime_domain_operation
def discard_unowned_container(name: str, *, container_id: str | None = None,
                               generation: str | None = None,
                               allowed_owner_panes: set[str] | None = None) -> bool:
    """Best-effort cleanup after a pane failed to attach (never raises).

    Unlike ``discard_container`` (used inside a locked create), this acquires
    the name's launch lock and preserves retained, owned or uninspectable
    containers.  An optional expected id protects the caller's launch attempt;
    removal always addresses the freshly inspected id, never a reusable name.
    False leaves the container available for a subsequent cleanup pass.
    """
    if not name:
        return False
    from pm_core import container_reaper
    from pm_core.push_proxy import stop_push_proxy
    try:
        with launch_lock(name, timeout=0) as locked:
            if not locked:
                return False
            current = current_container_id(name)
            if current is None:
                return False
            if not current:
                return True  # already gone
            if container_id and current != container_id:
                return False
            if generation is not None and cleanup_generation(name) != generation:
                return False
            # Review/sign-off preflight has no allocation to release. Another
            # launcher may have just returned from create before attaching its
            # pane; only the captured owner may discard during that lease.
            if (not container_id or generation is None) and recent_launch(
                    name, container_reaper.LAUNCH_GRACE, current):
                return False
            if container_reaper.is_retained(name, current):
                return False
            if allowed_owner_panes is None:
                owners = container_reaper.live_owner_panes(name, current)
            else:
                owners = container_reaper.live_owner_panes(name, current, strict=True)
            if set(owners) - (allowed_owner_panes or set()):
                return False
            unshared_released = remove_container(current)
            # Removal by ID cannot derive a shared key. A captured unshared
            # mount, however, must never be followed by name-based cleanup.
            if not unshared_released:
                stop_push_proxy(name)
            return True
    except Exception:
        _log.warning("Could not safely discard container %s", name, exc_info=True)
        return False


def _relieve_keyring_pressure() -> None:
    """Reap orphaned containers first when the kernel keyring is nearly full.

    Synchronous so the launch that follows benefits from the freed keys; the
    pass skips immediately when another process is already reconciling, and
    never touches the container being launched (its launch lock is held).
    """
    pressure = keyring_pressure(0.9)
    if not pressure:
        return
    _log.warning("Keyring for uid %s at %d/%d keys — reaping orphaned "
                 "containers before launching", pressure["uid"],
                 pressure["keys"], pressure["max_keys"])
    try:
        from pm_core import container_reaper
        container_reaper.reconcile(reason="keyring-pressure")
    except Exception:
        _log.warning("pre-launch reap failed", exc_info=True)


def _activity_identity_key(cid: str) -> str:
    from pm_core.container_reaper import _runtime_domain
    domain = _runtime_domain()
    if domain is None:
        raise ContainerError("Cannot determine runtime domain for interactive ownership")
    identity = json.dumps([domain, cid], sort_keys=True)
    return "active-id-" + hashlib.sha256(identity.encode()).hexdigest()


def activity_owner(name: str, container_id: str = "") -> bool:
    """Whether an interactive exec owns this name or its rename-stable identity."""
    if container_id and _activity_lock_held(_activity_identity_key(container_id)):
        return True
    return _activity_lock_held(f"active-{name}")


def _activity_lock_held(key: str) -> bool:
    try:
        path = _lock_path(key)
        # Only interactive attachment creates this file. An absent file is
        # unowned; the final removal recheck is serialized with attachment by
        # the launch lock. Never unlink existing activity files: a waiter may
        # already hold their inode open.
        try:
            lock = path.open("r")
        except FileNotFoundError:
            return False
        with lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            fcntl.flock(lock, fcntl.LOCK_UN)
        return False
    except OSError as exc:
        raise ContainerError(f"Cannot check interactive owner '{key}': {exc}") from exc


@_runtime_domain_operation
def run_interactive_exec(name: str, cid: str, generation: str,
                         state_dir: str, command: str, runtime: str,
                         hold_activity: str = "1") -> int:
    """Validate allocation before exec; optionally hold foreground ownership.

    Tmux callers already have a pane owner and pass ``hold_activity="0"``.
    They still need the same stale-allocation check before attaching.
    """
    os.environ["PM_CONTAINER_STATE_DIR"] = state_dir
    global _get_runtime
    _get_runtime = lambda: runtime
    # Serialize attachment with cleanup; an old shell must not attach to a
    # replacement. The child inherits the lock so killing this helper alone
    # cannot make a still-running exec appear abandoned.
    with contextlib.ExitStack() as stack:
        activities = []
        with launch_lock(name) as locked:
            if not locked or not cid or current_container_id(name) != cid:
                raise ContainerError(f"Container '{name}' changed before interactive attachment")
            if cleanup_generation(name) != generation:
                raise ContainerError(f"Container '{name}' was recovered before interactive attachment")
            if hold_activity != "0":
                # Keep the legacy name lock for older readers, and an ID/domain
                # lock so a runtime rename cannot hide an active foreground exec.
                for key in (f"active-{name}", _activity_identity_key(cid)):
                    path = _lock_path(key)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    activity = stack.enter_context(path.open("a"))
                    fcntl.flock(activity, fcntl.LOCK_SH)
                    activities.append(activity)
        inherited = tuple(activity.fileno() for activity in activities)
        return subprocess.call(["bash", "-c", command], pass_fds=inherited)


def build_exec_cmd(name: str, shell_cmd: str, cleanup: bool = True,
                   proxy_socket_path: str | None = None,
                   container_id: str | None = None,
                   interactive_owner: bool = False,
                   generation: str | None = None) -> str:
    """Build a ``<runtime> exec -it`` command string for use in a tmux window.

    When the exec'd process exits, its allocation is released unless
    *cleanup* is False or it was explicitly retained. Failed release stays
    durable for the next reconcile; replacements and restarts are preserved.

    If *container_id* is given the cleanup removes that exact container,
    not whatever currently holds *name*: a trap that fires late (after the
    window was killed and the session relaunched under the same name) must
    not delete the replacement.

    *proxy_socket_path* remains accepted for compatibility; proxy release
    uses the original container name and the shared runtime-user inventory,
    never unconditional socket deletion.
    """
    runtime = _get_runtime()
    if generation is None:
        generation = cleanup_generation(name)
    escaped = shlex.quote(shell_cmd)
    # Under Podman with --userns=keep-id, the default user is already the
    # host user (correct UID).  The "pm" username doesn't exist in
    # /etc/passwd, so -u pm would fail.  Under Docker, -u pm switches
    # from root to the pm user created during setup.
    target = shlex.quote(container_id or name)
    if "podman" in runtime:
        exec_part = f"{runtime} exec -it {target} bash -c {escaped}"
    else:
        exec_part = f"{runtime} exec -it -u {_CONTAINER_USER} {target} bash -c {escaped}"
    if interactive_owner or container_id:
        import sys
        script = (
            f"import sys; sys.path.insert(0, {str(Path(__file__).resolve().parent.parent)!r}); "
            "from pm_core.container import run_interactive_exec; "
            "sys.exit(run_interactive_exec(*sys.argv[1:]))")
        exec_part = shlex.join([
            sys.executable, "-c", script, name, container_id or "",
            generation, str(container_state_dir()), exec_part, runtime,
            "1" if interactive_owner else "0"])
    if cleanup:
        import sys
        # Pin this checkout/interpreter, not whichever pm happens to be on the
        # pane's PATH. The release persists its exact identity before inventory,
        # then uses the same retention/launch-lock checks as manual cleanup.
        script = (
            f"import sys; sys.path.insert(0, {str(Path(__file__).resolve().parent.parent)!r}); "
            "from pm_core.container import release_on_exit; "
            "release_on_exit(*sys.argv[1:])")
        cleanup_cmd = shlex.join([
            sys.executable, "-c", script, name, container_id or "", generation,
            runtime, str(container_state_dir()), proxy_socket_path or ""])
        inner = f"trap {shlex.quote(cleanup_cmd)} EXIT; {exec_part}"
        return f"bash -c {shlex.quote(inner)}"
    return exec_part


def release_on_exit(name: str, cid: str, generation: str, runtime: str,
                    state_dir: str, proxy_socket_path: str = "") -> None:
    """Release only the pane's original allocation, preserving retained work."""
    from pm_core import container_reaper
    os.environ["PM_CONTAINER_STATE_DIR"] = state_dir
    # This helper runs in its own short-lived interpreter; keep the runtime
    # selected by the launcher even if global settings changed meanwhile.
    global _get_runtime
    _get_runtime = lambda: runtime
    outcome = container_reaper.release_containers(
        [name], owner_release=True, expected_ids={name: cid},
        expected_generations={name: generation}, reason="pane-exit")
    if outcome.error or outcome.failures or outcome.release_refused:
        _log.warning("Pane cleanup deferred for %s: %s %s", name,
                     outcome.summary(), outcome.release_refused)


def remove_container(name: str, *, container_id: str | None = None) -> bool:
    """Force-remove a container and its push proxy, then wait until it is gone.

    Return True when an authoritative unshared proxy mount was handled.
    When supplied, ``container_id`` pins inspection and runtime removal to the
    checked allocation; ``name`` is only the locked proxy-bookkeeping key.

    If another 'docker rm -f' is already in flight (e.g. the previous session's
    EXIT trap), this still blocks until the container has fully disappeared so
    that the caller can safely create a fresh container with the same name.
    """
    from pm_core.push_proxy import (
        stop_push_proxy, capture_unshared_proxy, release_captured_unshared_proxy,
        defer_unshared_release, forget_unshared_proxy,
    )
    _log.info("remove_container: name=%s", name)
    target = container_id or name
    proxy = capture_unshared_proxy(target)
    pending = defer_unshared_release(proxy, name) if proxy else None
    _run_runtime("rm", "-f", target, check=False, timeout=30)
    # Wait for the container to be fully gone.  When another rm is already in
    # flight the daemon returns "removal already in progress" and our rm returns
    # immediately, but the container still exists for a brief moment.
    gone = False
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        result = _run_runtime("inspect", target, check=False, timeout=5)
        if result.returncode != 0:
            error = (result.stderr or "").strip()
            if _container_absent(error):
                gone = True
                break
            raise ContainerError(
                f"could not confirm removal of container {name}: "
                f"{error or 'runtime inspect failed without an absence diagnostic'}")
        time.sleep(0.1)
    if not gone:
        _log.warning("remove_container: %s still present after 10 s", name)
        raise ContainerError(f"container {name} still present after 10 s")
    # Release the push proxy only after the container is gone.  Failed
    # removal must leave the surviving container's push access intact.
    if proxy:
        forget_unshared_proxy(name, proxy[1])
        if release_captured_unshared_proxy(proxy):
            pending.unlink(missing_ok=True)
        return True  # the actual mount is authoritative, not a reusable runtime name
    stop_push_proxy(name)
    return False


def containers_for_pr(session_tag: str, pr_id: str) -> set[str] | None:
    """Names of every pm container (any state) for *session_tag* + *pr_id*.

    Used to decide whether a shared push proxy is still needed.  Returns
    None when the runtime can't be queried (caller must assume "in use").
    """
    from pm_core.container_reaper import list_containers
    inventory = list_containers()
    if inventory is None:
        return None
    # Use the same label-first identity as the reaper. A renamed managed
    # container can still mount the shared proxy even without a parsed name.
    return {info.name for info in inventory
            if info.session_tag == session_tag and info.pr_id == pr_id}


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
    kind: str | None = None,
    allocation_identity: dict[str, str] | None = None,
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
    _log.info(
        "wrap_claude_cmd: label=%s workdir=%s container=%s session_tag=%s pr_id=%s",
        label, workdir, cname, session_tag, pr_id,
    )

    identity = allocation_identity if allocation_identity is not None else {}
    try:
        container_id = create_container(
            name=cname,
            config=config,
            workdir=Path(workdir),
            extra_ro_mounts=extra_ro_mounts,
            extra_rw_mounts=extra_rw_mounts,
            allowed_push_branch=allowed_push_branch,
            session_tag=session_tag,
            pr_id=pr_id,
            kind=kind,
            allocation_identity=identity,
        )
    except ContainerError:
        _log.error("Failed to create container %s — aborting (container mode is enabled)",
                   cname, exc_info=True)
        raise
    except Exception as exc:
        _log.error("Failed to create container %s — aborting (container mode is enabled)",
                   cname, exc_info=True)
        runtime = _get_runtime()
        detail = ""
        if isinstance(exc, subprocess.CalledProcessError):
            detail = (exc.stderr or exc.output or "").strip()
        detail = detail or str(exc)
        raise ContainerError(
            f"Failed to create container '{cname}': {detail[-600:]}. "
            f"Is {runtime} running? Disable container mode with 'pm container disable' "
            f"to run without containers."
        ) from exc

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
    # in the exec command — the socket is shared across containers and is
    # stopped once the runtime reports no container left for the PR
    # (push_proxy.release_proxy_if_unused, also run by the reaper).
    shared_proxy = session_tag is not None and pr_id is not None
    exec_cmd = build_exec_cmd(
        cname, claude_cmd,
        proxy_socket_path=None if shared_proxy else proxy_sock,
        container_id=container_id if isinstance(container_id, str) and container_id else None,
        generation=identity.get("generation", ""),
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
    loop_id: str | None = None,
    scenario: int | None = None,
    kind: str = "qa",
    allocation_identity: dict[str, str] | None = None,
    reuse_identity: dict[str, str | None] | None = None,
) -> str:
    """Create a detached container for a QA scenario.

    Convenience wrapper around create_container with QA-specific mounts:
      - workdir at /workspace (rw) — a standalone clone, not a worktree
      - scratch at /scratch (rw)

    The container has no access to the parent repo's git directory.
    If *allowed_push_branch* is set, a push proxy is started so the
    scenario can push fixes to the PR branch.  *loop_id* / *scenario* are
    recorded as ownership labels so cleanup can tell runs apart.
    """
    return create_container(
        name=name,
        config=config,
        workdir=workdir,
        extra_rw_mounts={scratch_path: _CONTAINER_SCRATCH},
        allowed_push_branch=allowed_push_branch,
        session_tag=session_tag,
        pr_id=pr_id,
        kind=kind,
        loop_id=loop_id,
        scenario=scenario,
        allocation_identity=allocation_identity,
        reuse_identity=reuse_identity,
    )


def _list_names(prefix: str, *, running_only: bool = False) -> list[str] | None:
    """Container names starting with *prefix*; None if the runtime failed.

    The runtime's ``name=`` filter matches substrings (``npm-cache`` matches
    ``pm-``), so the prefix is re-checked here.
    """
    result = _run_runtime(
        "ps", *(() if running_only else ("-a",)), "--filter", f"name={prefix}",
        "--format", "{{.Names}}",
        check=False, timeout=30,
    )
    if result.returncode != 0:
        return None
    return [ln.strip() for ln in (result.stdout or "").splitlines()
            if ln.strip().startswith(prefix)]


def _remove_captured_container(name: str, cid: str, generation: str,
                               include_retained: bool = True) -> bool:
    """Force-remove the captured allocation, never a concurrent replacement."""
    with launch_lock(name) as locked:
        if not locked:
            raise ContainerError(f"Container '{name}' lifecycle lock unavailable")
        current = current_container_id(name)
        if current is None:
            raise ContainerError(f"Container '{name}' identity unknown during cleanup")
        if not current:
            return True  # Already gone; do not touch a subsequently recreated proxy.
        if current != cid or cleanup_generation(name) != generation:
            raise ContainerError(f"Container '{name}' changed during cleanup; retry explicitly")
        if not include_retained:
            from pm_core import container_reaper
            if container_reaper.is_retained(name, current):
                return False
        # Keep removal and proxy cleanup in one launch exclusion. Explicit
        # force cleanup bypasses pane ownership and, by default, retention.
        remove_container(name, container_id=cid)
        return True


@_runtime_domain_operation
def remove_containers(names: list[str], *, workers: int = 4,
                      include_retained: bool = True) -> tuple[list[str], dict[str, str]]:
    """Force-remove captured allocations with bounded parallelism.

    Capture every identity before queueing deletions, then recheck under its
    launch lock. Returns ``(removed, failures)`` where failures maps name to
    an error (including a changed allocation that needs an explicit retry).
    """
    removed: list[str] = []
    failures: dict[str, str] = {}
    allocations: list[tuple[str, str, str]] = []
    for name in dict.fromkeys(names):
        try:
            with launch_lock(name) as locked:
                if not locked:
                    raise ContainerError(f"Container '{name}' lifecycle lock unavailable")
                cid = current_container_id(name)
                if cid is None:
                    raise ContainerError(f"Container '{name}' identity unknown during cleanup")
                if not cid:
                    continue
                allocations.append((name, cid, cleanup_generation(name)))
        except Exception as exc:
            failures[name] = str(exc)
    if not allocations:
        return removed, failures
    with ThreadPoolExecutor(max_workers=max(1, min(len(allocations), workers))) as ex:
        futures = [(c, ex.submit(contextvars.copy_context().run,
                                _remove_captured_container, c, cid, generation,
                                include_retained))
                   for c, cid, generation in allocations]
        for cname, fut in futures:
            try:
                if fut.result():
                    removed.append(cname)
            except Exception as e:
                _log.warning("remove_container(%s) failed: %s", cname, e)
                failures[cname] = str(e)
    return removed, failures


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

    names: list[str] = []
    for prefix in prefixes:
        names += [c for c in _list_names(prefix) or []
                  if c not in (exclude or set()) and c not in names]
    removed, _failures = remove_containers(names)
    count = len(removed)

    if count:
        _log.info("Cleaned up %d container(s) for %s/%s", count, pr_id, loop_id)
    return count


def cleanup_pr_containers(pr_id: str,
                          session_tag: str | None = None,
                          include_retained: bool = True) -> list[str]:
    """Remove every container for a PR: impl, review, sign-off and QA (all loops).

    Matches session-tagged (``pm-{session_tag}-{kind}-{pr_id}``) and legacy
    (``pm-{kind}-{pr_id}``) names.  Called after the PR's windows were
    killed (merge, ``pm pr cleanup --resources``, TUI cleanup), so pane
    ownership is not consulted; explicitly retained containers are kept
    when *include_retained* is False.  Returns the list of names removed.
    """
    from pm_core import container_reaper
    inventory = container_reaper.list_containers()
    if inventory is None:
        raise ContainerError("Cannot inventory PR containers; cleanup not performed")
    tags = {session_tag, None}
    candidates = [info.name for info in inventory
                  if info.session_tag in tags and info.pr_id == pr_id
                  and info.kind != "qa-debug"
                  and (include_retained or not container_reaper.is_retained(info.name, info.id))]

    removed, _failures = remove_containers(
        candidates, workers=8, include_retained=include_retained)
    if removed:
        _log.info("Cleaned up %d container(s) for %s", len(removed), pr_id)
    return removed


def cleanup_orphaned_qa_containers(session: str, pr_id: str,
                                   session_tag: str | None = None,
                                   wait: bool = True) -> int:
    """Remove this PR's QA containers that no live pane owns.

    Called at the start of a new QA run.  Ownership is exact: a container is
    kept only while a live tmux pane was started with *its* name (or it is
    retained / mid-launch) — a ``qa-*`` window of another PR or run with the
    same ``-sN`` suffix no longer keeps it alive.  With ``wait=False`` the
    removal runs in the background so the new run doesn't pay for the old
    run's cleanup.  Returns the number removed (0 when not waiting).
    """
    from pm_core import container_reaper
    if not session_tag:
        session_tag = session.removeprefix("pm-") if session else None
    scope = container_reaper.Scope(pr_id=pr_id, session_tag=session_tag,
                                   kinds={"qa"})
    outcome = container_reaper.reconcile(scope=scope, wait=wait,
                                         reason="qa-run-start")
    if outcome is None:
        return 0
    if outcome.removed:
        _log.info("Cleaned up %d orphaned QA container(s) for %s",
                  len(outcome.removed), pr_id)
    return len(outcome.removed)


def cleanup_session_containers(session_tag: str) -> int:
    """Remove containers with this exact session owner, including renamed ones.

    Returns the number of containers removed.
    """
    from pm_core import container_reaper
    inventory = container_reaper.list_containers()
    if inventory is None:
        _log.warning("Cannot inspect containers for session %s; cleanup deferred", session_tag)
        return 0
    names = [info.name for info in inventory if info.session_tag == session_tag]
    if not names:
        return 0
    removed, _failures = remove_containers(names)
    if removed:
        _log.info("Cleaned up %d container(s) for session %s", len(removed), session_tag)
    return len(removed)


def cleanup_all_containers() -> int:
    """Remove all pm containers. Returns count removed."""
    names = _list_names(CONTAINER_PREFIX)
    if not names:
        return 0
    removed, _failures = remove_containers(names)
    return len(removed)
