"""Container memory governor — prevents OOM by gating launches on memory budget.

The governor tracks system or per-container memory usage and projects
whether launching a new container would exceed the user-configured target.
Historical peak memory per container type is recorded at container
end-of-life (stop or removal) and persisted across sessions.

Key concepts:
  - **Memory target**: aggregate soft ceiling (e.g. 48 GiB).
  - **Projection**: estimated peak memory for a new container, based on
    rolling average of observed end-of-life peaks.
  - **Gate check**: ``current_used + projection <= target``.
  - **Stop-on-idle**: completed containers are removed to free memory.
    The workdir is bind-mounted from the host so project state survives.

Settings (all via ``pm container set <key> <value>``):
  system-memory-target          — aggregate memory ceiling (e.g. "48g")
  system-memory-scope           — what "current used" measures: "pm" or "system"
  system-memory-default-projection — fallback when no historical data
  system-memory-history-size    — rolling window size (default 20)
  stop-idle-impl                — on/off (default off)
  stop-idle-review              — on/off (default off)
  stop-idle-qa                  — on/off (default on)
"""

import json
import platform
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from pm_core.paths import configure_logger, pm_home, get_global_setting_value

_log = configure_logger("pm.memory_governor")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_HISTORY_SIZE = 20
_STATS_FILE = "container-stats.json"
_DOCKER_STATS_TIMEOUT = 5  # seconds — must not block teardown

# Container name prefix (mirrors container.py)
_CONTAINER_PREFIX = "pm-"

# ---------------------------------------------------------------------------
# Memory unit parsing
# ---------------------------------------------------------------------------

# Regex: number (int or float) optionally followed by a unit.
_MEM_RE = re.compile(
    r"^\s*(\d+(?:\.\d+)?)\s*"
    r"(b|k|kb|kib|m|mb|mib|g|gb|gib|t|tb|tib)?\s*$",
    re.IGNORECASE,
)

_UNIT_TO_MB: dict[str, float] = {
    "b": 1 / (1024 * 1024),
    "k": 1 / 1024, "kb": 1 / 1024, "kib": 1 / 1024,
    "m": 1, "mb": 1, "mib": 1,
    "g": 1024, "gb": 1024, "gib": 1024,
    "t": 1024 * 1024, "tb": 1024 * 1024, "tib": 1024 * 1024,
}


def parse_memory(s: str) -> int:
    """Parse a memory string like ``"8g"``, ``"1.5GiB"``, ``"500MiB"`` to MB.

    Returns integer megabytes (rounded up).  Raises ``ValueError`` on bad input.
    """
    m = _MEM_RE.match(s)
    if not m:
        raise ValueError(f"Cannot parse memory value: {s!r}")
    value = float(m.group(1))
    unit = (m.group(2) or "b").lower()
    multiplier = _UNIT_TO_MB.get(unit)
    if multiplier is None:
        raise ValueError(f"Unknown memory unit: {unit!r}")
    mb = value * multiplier
    return max(1, int(mb + 0.5))  # round to nearest, min 1 MB


# ---------------------------------------------------------------------------
# Container type inference from name
# ---------------------------------------------------------------------------

# Container names follow these patterns (see container.py):
#   pm-{tag}-impl-{pr_id}   or  pm-impl-{pr_id}   or  pm-{tag}-impl
#   pm-{tag}-review-{pr_id}  or  pm-review-{pr_id}
#   pm-{tag}-qa-{pr}-{loop}-s{N}  or  pm-qa-{pr}-{loop}-s{N}
# The tag is a session identifier that may contain hyphens.

def infer_container_type(name: str) -> str | None:
    """Infer container type from its name.

    Returns one of "impl", "review", "qa_scenario", "qa_planner", or None.
    """
    if not name.startswith(_CONTAINER_PREFIX):
        return None

    suffix = name[len(_CONTAINER_PREFIX):]

    # QA scenario: contains "-qa-" or starts with "qa-", and ends with "-s{N}"
    if ("-qa-" in suffix or suffix.startswith("qa-")) and re.search(r"-s\d+$", suffix):
        return "qa_scenario"

    # QA planner: contains "-qa-planner" or ends with "qa-planner"
    if suffix.endswith("-qa-planner") or suffix == "qa-planner":
        return "qa_planner"

    # Impl: label is "impl-{pr_id}" so name contains "-impl-" or ends with "-impl"
    if "-impl-" in suffix or suffix.endswith("-impl") or suffix == "impl" or suffix.startswith("impl-"):
        return "impl"

    # Review: contains "-review-" or starts with "review-"
    if "-review-" in suffix or suffix.startswith("review-"):
        return "review"

    return None


# ---------------------------------------------------------------------------
# Docker stats helpers
# ---------------------------------------------------------------------------

def get_pm_container_memory() -> dict[str, int]:
    """Get current memory usage (MB) for all running pm containers.

    Returns a dict of {container_name: memory_mb}.  Returns empty dict
    on failure (Docker unavailable, timeout, etc.).
    """
    try:
        result = subprocess.run(
            ["docker", "stats", "--no-stream", "--format",
             "{{.Name}}\t{{.MemUsage}}"],
            capture_output=True, text=True, timeout=_DOCKER_STATS_TIMEOUT,
        )
        if result.returncode != 0:
            _log.warning("docker stats failed (rc=%d): %s",
                         result.returncode, result.stderr.strip()[:200])
            return {}
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        _log.warning("docker stats unavailable: %s", e)
        return {}

    containers: dict[str, int] = {}
    for line in result.stdout.strip().splitlines():
        parts = line.split("\t", 1)
        if len(parts) != 2:
            continue
        name, mem_usage = parts[0].strip(), parts[1].strip()
        if not name.startswith(_CONTAINER_PREFIX):
            continue
        # mem_usage looks like "1.5GiB / 8GiB" — we want the first part
        current = mem_usage.split("/")[0].strip()
        try:
            containers[name] = parse_memory(current)
        except ValueError:
            _log.debug("Cannot parse memory for %s: %r", name, current)
    return containers


def capture_container_memory(name: str) -> int | None:
    """Capture current memory usage (MB) for a single container.

    Returns None on failure.  Has a short timeout to avoid blocking
    container teardown.
    """
    try:
        result = subprocess.run(
            ["docker", "stats", "--no-stream", "--format",
             "{{.MemUsage}}", name],
            capture_output=True, text=True, timeout=_DOCKER_STATS_TIMEOUT,
        )
        if result.returncode != 0:
            return None
        mem_usage = result.stdout.strip()
        if not mem_usage:
            return None
        current = mem_usage.split("/")[0].strip()
        return parse_memory(current)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError, ValueError):
        return None


def get_container_age_minutes(name: str) -> float | None:
    """Get how long a container has been running, in minutes.

    Returns None on failure.
    """
    try:
        result = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.StartedAt}}", name],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return None
        started_str = result.stdout.strip()
        if not started_str:
            return None
        # Docker uses RFC 3339 with nanoseconds: 2026-04-07T14:30:00.123456789Z
        # Truncate nanoseconds to microseconds for fromisoformat()
        started_str = re.sub(r"(\.\d{6})\d*", r"\1", started_str)
        started = datetime.fromisoformat(started_str.replace("Z", "+00:00"))
        age = datetime.now(timezone.utc) - started
        return max(0.0, age.total_seconds() / 60.0)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError, ValueError):
        return None


# ---------------------------------------------------------------------------
# System memory (for "system" scope)
# ---------------------------------------------------------------------------

def get_system_memory_used_mb() -> int | None:
    """Get total system memory usage in MB.

    Reads /proc/meminfo on Linux, falls back to sysctl/vm_stat on macOS.
    Returns None if unavailable.
    """
    system = platform.system()

    if system == "Linux":
        try:
            with open("/proc/meminfo") as f:
                info: dict[str, int] = {}
                for line in f:
                    parts = line.split()
                    if len(parts) >= 2 and parts[0].endswith(":"):
                        key = parts[0][:-1]
                        # Values in /proc/meminfo are in kB
                        try:
                            info[key] = int(parts[1])
                        except ValueError:
                            pass
                total = info.get("MemTotal", 0)
                available = info.get("MemAvailable", 0)
                if total > 0:
                    return max(0, (total - available) // 1024)
        except OSError:
            pass
        return None

    if system == "Darwin":
        try:
            # Total memory via sysctl
            result = subprocess.run(
                ["sysctl", "-n", "hw.memsize"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                return None
            total_bytes = int(result.stdout.strip())
            total_mb = total_bytes // (1024 * 1024)

            # Free/inactive pages via vm_stat
            result = subprocess.run(
                ["vm_stat"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                return None
            # Parse page size and free/inactive counts
            page_size = 4096  # default
            m = re.search(r"page size of (\d+) bytes", result.stdout)
            if m:
                page_size = int(m.group(1))
            free_pages = 0
            for key in ("Pages free", "Pages inactive", "Pages purgeable"):
                m = re.search(rf"{key}:\s+(\d+)", result.stdout)
                if m:
                    free_pages += int(m.group(1))
            available_mb = (free_pages * page_size) // (1024 * 1024)
            return max(0, total_mb - available_mb)
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError, ValueError):
            pass
        return None

    return None


# ---------------------------------------------------------------------------
# Current usage dispatcher
# ---------------------------------------------------------------------------

def get_current_used_mb() -> int | None:
    """Get current memory usage based on the configured scope.

    Returns None if the measurement fails (graceful degradation — allow launch).
    """
    scope = get_global_setting_value("container-system-memory-scope", "pm")

    if scope == "system":
        result = get_system_memory_used_mb()
        if result is None:
            _log.warning("System memory scope requested but measurement "
                         "failed — falling back to pm scope")
            # Fall back to pm scope
            containers = get_pm_container_memory()
            return sum(containers.values()) if containers else None
        return result

    # Default: pm scope
    containers = get_pm_container_memory()
    if not containers:
        return 0  # No pm containers running = 0 MB used
    return sum(containers.values())


# ---------------------------------------------------------------------------
# Settings readers
# ---------------------------------------------------------------------------

def get_memory_target() -> int | None:
    """Read the system-memory-target setting.

    Returns target in MB, or None if not configured (governor inactive).
    """
    raw = get_global_setting_value("container-system-memory-target", "")
    if not raw:
        return None
    try:
        return parse_memory(raw)
    except ValueError:
        _log.warning("Invalid system-memory-target value: %r", raw)
        return None


def get_default_projection() -> int | None:
    """Read the system-memory-default-projection setting.

    Returns MB, or None if not configured.
    """
    raw = get_global_setting_value(
        "container-system-memory-default-projection", "")
    if not raw:
        return None
    try:
        return parse_memory(raw)
    except ValueError:
        _log.warning("Invalid system-memory-default-projection: %r", raw)
        return None


def get_history_size() -> int:
    """Read the system-memory-history-size setting (default 20)."""
    raw = get_global_setting_value(
        "container-system-memory-history-size", "")
    try:
        return max(1, int(raw))
    except (ValueError, TypeError):
        return _DEFAULT_HISTORY_SIZE


def get_stop_idle_policy(container_type: str) -> bool:
    """Check if stop-on-idle is enabled for the given container type.

    Maps container types to settings:
      impl           → container-stop-idle-impl      (default: off)
      review         → container-stop-idle-review     (default: off)
      qa_scenario    → container-stop-idle-qa         (default: on)
      qa_planner     → container-stop-idle-qa         (default: on)
      qa_verification → container-stop-idle-qa        (default: on)
    """
    if container_type in ("qa_scenario", "qa_planner", "qa_verification"):
        setting = "container-stop-idle-qa"
        default = "on"
    elif container_type == "review":
        setting = "container-stop-idle-review"
        default = "off"
    elif container_type == "impl":
        setting = "container-stop-idle-impl"
        default = "off"
    else:
        return False

    val = get_global_setting_value(setting, default)
    return val.lower() in ("on", "true", "1", "yes")


# ---------------------------------------------------------------------------
# Stats persistence
# ---------------------------------------------------------------------------

def _stats_path() -> Path:
    return pm_home() / _STATS_FILE


def load_stats() -> dict:
    """Load historical stats from ~/.pm/container-stats.json.

    Returns a dict keyed by container type, each with a "samples" list.
    Returns empty dict on missing/corrupt file.
    """
    path = _stats_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            return {}
        return data
    except (json.JSONDecodeError, OSError) as e:
        _log.warning("Failed to load stats file %s: %s", path, e)
        return {}


def save_stats(stats: dict) -> None:
    """Write stats atomically (temp + rename) to avoid corruption."""
    path = _stats_path()
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(stats, indent=2) + "\n")
        tmp.replace(path)
    except OSError as e:
        _log.warning("Failed to save stats file %s: %s", path, e)


def record_sample(container_type: str, memory_mb: int,
                  age_minutes: float) -> None:
    """Record an end-of-life memory sample for a container type.

    Appends to the rolling window, dropping the oldest sample if over
    the configured history size.  Cross-process safe via ``governor_lock``.
    """
    from pm_core.governor_lock import governor_lock

    with governor_lock():
        stats = load_stats()
        entry = stats.setdefault(container_type, {})
        samples = entry.setdefault("samples", [])

        samples.append({
            "memory_mb": memory_mb,
            "age_minutes": round(age_minutes, 1),
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        })

        # Trim to history size
        max_samples = get_history_size()
        if len(samples) > max_samples:
            entry["samples"] = samples[-max_samples:]

        save_stats(stats)


# ---------------------------------------------------------------------------
# Memory projection
# ---------------------------------------------------------------------------

def project_memory(container_type: str) -> int:
    """Project memory (MB) for a new container of the given type.

    Cascade:
      1. Average of stored end-of-life samples (any count >= 1)
      2. system-memory-default-projection setting (if set)
      3. Per-container memory-limit from ContainerConfig
    """
    stats = load_stats()
    entry = stats.get(container_type, {})
    samples = entry.get("samples", [])

    if samples:
        total = sum(s.get("memory_mb", 0) for s in samples)
        return max(1, total // len(samples))

    # No samples — try configured default
    default_proj = get_default_projection()
    if default_proj is not None:
        return default_proj

    # Fall back to per-container Docker memory limit
    from pm_core.container import load_container_config
    config = load_container_config()
    try:
        return parse_memory(config.memory_limit)
    except ValueError:
        return 8192  # 8 GiB as absolute fallback


# ---------------------------------------------------------------------------
# Launch gate check
# ---------------------------------------------------------------------------

def check_launch(container_type: str,
                 count: int = 1) -> tuple[bool, str]:
    """Check if launching ``count`` containers of the given type is safe.

    Returns ``(allowed, reason)``.  If the governor is inactive (no target
    configured), always returns ``(True, "")``.

    Cross-process safe via ``governor_lock``.  Kept as a convenience API
    for non-queued checks (status display, diagnostics).  Production
    launch gating should use ``launch_queue.try_acquire`` instead.
    """
    target = get_memory_target()
    if target is None:
        return True, ""

    from pm_core.governor_lock import governor_lock

    with governor_lock():
        current = get_current_used_mb()
        if current is None:
            # Can't measure — allow the launch but warn
            _log.warning("Cannot measure current memory — allowing launch")
            return True, ""

        projected = project_memory(container_type)
        needed = current + count * projected

        if needed > target:
            scope = get_global_setting_value(
                "container-system-memory-scope", "pm")
            reason = (
                f"Memory gate: {current}MB used + "
                f"{count}x{projected}MB projected = {needed}MB "
                f"> {target}MB target ({scope} scope)"
            )
            _log.info(reason)
            return False, reason

        _log.debug("Memory gate: %dMB used + %dx%dMB = %dMB <= %dMB target — OK",
                    current, count, projected, needed, target)
        return True, ""


def check_single_container_fits(container_type: str) -> tuple[bool, str]:
    """Check if a single container's projection fits within the target at all.

    Detects the E2 edge case where per-container limit > target.
    Returns ``(fits, reason)``.
    """
    target = get_memory_target()
    if target is None:
        return True, ""

    projected = project_memory(container_type)
    if projected > target:
        return False, (
            f"Container projection ({projected}MB) exceeds system memory "
            f"target ({target}MB) — a single container cannot fit. "
            f"Increase the target or lower the per-container memory limit."
        )
    return True, ""


# ---------------------------------------------------------------------------
# Memory capture before stop/removal
# ---------------------------------------------------------------------------

def capture_and_record(name: str) -> None:
    """Capture a container's memory and age, record as a sample.

    Best-effort: failures are logged but don't block the caller.
    """
    ctype = infer_container_type(name)
    if ctype is None:
        _log.debug("Cannot infer type for container %s — skipping stats", name)
        return

    memory_mb = capture_container_memory(name)
    if memory_mb is None:
        _log.debug("Cannot capture memory for %s — skipping stats", name)
        return

    age = get_container_age_minutes(name)
    if age is None:
        age = 0.0

    _log.info("Recording stats for %s (%s): %dMB, %.1f min",
              name, ctype, memory_mb, age)
    record_sample(ctype, memory_mb, age)


# ---------------------------------------------------------------------------
# Status display helpers
# ---------------------------------------------------------------------------

def format_memory_status() -> str:
    """Format memory status for the TUI status bar.

    Returns e.g. "34G/48G (pm)" or "" if governor is inactive.
    """
    target = get_memory_target()
    if target is None:
        return ""

    current = get_current_used_mb()
    if current is None:
        return ""

    scope = get_global_setting_value("container-system-memory-scope", "pm")
    scope_label = "sys" if scope == "system" else "pm"

    def _fmt(mb: int) -> str:
        if mb >= 1024:
            g = mb / 1024
            return f"{g:.0f}G" if g == int(g) else f"{g:.1f}G"
        return f"{mb}M"

    return f"{_fmt(current)}/{_fmt(target)} ({scope_label})"
