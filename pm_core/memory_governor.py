"""Container memory governor — prevents OOM by gating launches on memory budget.

Before a container launches, the governor checks that the memory already
committed, plus the new container's projected peak, stays within the
user-configured target and leaves the host a reserve of free memory.
Historical memory per container type is recorded at container end-of-life
(stop or removal) and persisted across sessions.

Key concepts:
  - **Memory target**: aggregate soft ceiling (e.g. 48 GiB).
  - **Projection**: estimated peak memory for a new container — a high
    percentile of recorded samples.  A sample is the container's cgroup
    peak when the runtime exposes one; otherwise an end-of-life snapshot,
    inflated by ``_SNAPSHOT_GROWTH_FACTOR`` because usage at teardown is
    not the peak the container reached.
  - **Committed usage**: what is in use now, plus the growth still ahead
    of every running pm container (up to its type's projection), plus
    in-flight reservations for granted-but-not-yet-running launches (see
    :mod:`pm_core.launch_queue`).
  - **Host reserve**: free host memory (``MemAvailable``) that must remain
    after the admitted container and the expected growth.
  - **Fail closed**: when usage cannot be measured (runtime stats fail, a
    pm container reports no usage, ``/proc/meminfo`` is unreadable, the
    target setting is invalid, the governor lock is busy), nothing is
    admitted and the reason is reported.  Unset the target to bypass.
  - **Stop-on-idle**: completed containers are removed to free memory.
    The workdir is bind-mounted from the host so project state survives.

Settings (all via ``pm container set <key> <value>``):
  system-memory-target          — aggregate memory ceiling (e.g. "48g")
  system-memory-scope           — what "current used" measures: "pm" or "system"
  system-memory-reserve         — free host memory to keep (e.g. "8g" or "10%")
  system-memory-default-projection — fallback when no historical data
  system-memory-history-size    — rolling window size (default 20)
  stop-idle-impl                — on/off (default off)
  stop-idle-review              — on/off (default off)
  stop-idle-qa                  — on/off (default on)
"""

import json
import math
import os
import platform
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from pm_core.paths import configure_logger, pm_home, get_global_setting_value

_log = configure_logger("pm.memory_governor")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_HISTORY_SIZE = 20
_STATS_FILE = "container-stats.json"
_BLOCKED_FILE = "governor-blocked.json"
_STATS_TIMEOUT = 10  # seconds — runtime stats can take a few seconds
_CAPTURE_TIMEOUT = 5  # seconds — must not block teardown

# End-of-life usage understates the peak a container reached (builds and
# test runs finish before teardown); inflate snapshot samples by this.
_SNAPSHOT_GROWTH_FACTOR = 1.5
# Projection = this percentile of the (adjusted) samples.
_PROJECTION_PERCENTILE = 0.9
_DEFAULT_RESERVE = "10%"
_BLOCKED_DISPLAY_SECONDS = 600

# Container name prefix (mirrors container.py)
_CONTAINER_PREFIX = "pm-"


class GovernorConfigError(ValueError):
    """A governor setting is present but invalid."""


class MemoryMeasurementError(RuntimeError):
    """Current memory usage could not be measured."""


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
    """Parse a user memory string like ``"8g"`` or ``"1.5GiB"`` to MiB.

    User settings follow the container runtimes' ``--memory`` convention:
    every unit is binary (``g`` = ``gb`` = GiB).  Returns integer MiB
    (rounded, min 1).  Raises ``ValueError`` on bad input.
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


# Runtime stats output: Docker prints binary units ("1.5GiB"), Podman
# prints decimal SI units ("1.06GB", "512kB").
_RUNTIME_MEM_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([kKMGTP]?i?B)\s*$")
_BINARY = {"B": 1, "KiB": 1024, "MiB": 1024 ** 2, "GiB": 1024 ** 3,
           "TiB": 1024 ** 4, "PiB": 1024 ** 5}
_DECIMAL = {"B": 1, "kB": 1000, "KB": 1000, "MB": 1000 ** 2,
            "GB": 1000 ** 3, "TB": 1000 ** 4, "PB": 1000 ** 5}


def parse_runtime_memory(s: str) -> int:
    """Parse a runtime stats value (``"1.5GiB"``, ``"1.06GB"``) to MiB.

    Raises ``ValueError`` for anything else, including the ``"--"`` a
    runtime prints when it has no figure — never read that as zero.
    """
    m = _RUNTIME_MEM_RE.match(s)
    if not m:
        raise ValueError(f"Cannot parse runtime memory value: {s!r}")
    unit = m.group(2)
    factor = _BINARY.get(unit) or _DECIMAL.get(unit)
    if factor is None:
        raise ValueError(f"Unknown runtime memory unit: {unit!r}")
    return int(math.ceil(float(m.group(1)) * factor / (1024 * 1024)))


def _fmt_mb(mb: int) -> str:
    if mb >= 1024:
        g = mb / 1024
        return f"{g:.0f}G" if g == int(g) else f"{g:.1f}G"
    return f"{mb}M"


# ---------------------------------------------------------------------------
# Container type inference from name
# ---------------------------------------------------------------------------

# Container names follow these patterns (see container.py):
#   pm-{tag}-impl-{pr_id}   or  pm-impl-{pr_id}   or  pm-{tag}-impl
#   pm-{tag}-review-{pr_id}  or  pm-review-{pr_id}
#   pm-{tag}-signoff-{pr_id} or  pm-signoff-{pr_id}
#   pm-{tag}-qa-{pr}-{loop}-s{N}  or  pm-qa-{pr}-{loop}-s{N}
#   pm-qa-debug-{instruction}-{debug_id}
# The tag is a session identifier that may contain hyphens.

def infer_container_type(name: str) -> str | None:
    """Infer container type from its name.

    Returns one of "impl", "review", "signoff", "qa_scenario",
    "qa_planner", "qa_debug", or None.
    """
    if not name.startswith(_CONTAINER_PREFIX):
        return None

    suffix = name[len(_CONTAINER_PREFIX):]

    if "-qa-debug-" in suffix or suffix.startswith("qa-debug-"):
        return "qa_debug"

    # QA scenario: contains "-qa-" or starts with "qa-", and ends with "-s{N}"
    if ("-qa-" in suffix or suffix.startswith("qa-")) and re.search(r"-s\d+$", suffix):
        return "qa_scenario"

    # QA planner: contains "-qa-planner" or ends with "qa-planner"
    if suffix.endswith("-qa-planner") or suffix == "qa-planner":
        return "qa_planner"

    if "-signoff-" in suffix or suffix.startswith("signoff-"):
        return "signoff"

    # Impl: label is "impl-{pr_id}" so name contains "-impl-" or ends with "-impl"
    if "-impl-" in suffix or suffix.endswith("-impl") or suffix == "impl" or suffix.startswith("impl-"):
        return "impl"

    # Review: contains "-review-" or starts with "review-"
    if "-review-" in suffix or suffix.startswith("review-"):
        return "review"

    return None


# ---------------------------------------------------------------------------
# Runtime helpers
# ---------------------------------------------------------------------------

def _runtime() -> str:
    from pm_core.container import _get_runtime
    return _get_runtime()


def _run_runtime(args: list[str], timeout: float) -> subprocess.CompletedProcess:
    """Run ``<runtime> args``; raise MemoryMeasurementError on any failure."""
    runtime = _runtime()
    try:
        result = subprocess.run([runtime, *args], capture_output=True,
                                text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise MemoryMeasurementError(
            f"{runtime} {args[0]} timed out after {timeout:.0f}s") from e
    except OSError as e:
        raise MemoryMeasurementError(f"{runtime} unavailable: {e}") from e
    if result.returncode != 0:
        err = (result.stderr or "").strip().splitlines()
        raise MemoryMeasurementError(
            f"{runtime} {args[0]} failed (rc={result.returncode})"
            + (f": {err[-1][:200]}" if err else ""))
    return result


def get_pm_container_memory() -> dict[str, int]:
    """Current memory usage (MiB) of every running pm container.

    Raises :class:`MemoryMeasurementError` when the runtime's stats fail
    (rootless Podman without a delegated memory cgroup, a container
    without a cgroup, runtime down) or any pm container's usage is
    unreadable.  An empty dict means no pm container is running.
    """
    # Not a tab: Podman runs --format output through a tabwriter that turns
    # tabs into padding spaces.
    result = _run_runtime(
        ["stats", "--no-stream", "--format", "{{.Name}}|{{.MemUsage}}"],
        timeout=_STATS_TIMEOUT)

    containers: dict[str, int] = {}
    for line in result.stdout.strip().splitlines():
        parts = line.split("|", 1)
        name = parts[0].strip()
        if not name.startswith(_CONTAINER_PREFIX):
            continue
        # mem_usage looks like "1.5GiB / 8GiB" — we want the first part
        current = parts[1].split("/")[0].strip() if len(parts) == 2 else ""
        try:
            mb = parse_runtime_memory(current)
        except ValueError:
            raise MemoryMeasurementError(
                f"no memory figure for running container {name} "
                f"({current or 'empty'!s})")
        if mb <= 0:
            # A running container always uses memory; 0 means the runtime
            # cannot see its cgroup.
            raise MemoryMeasurementError(
                f"{_runtime()} reports 0 memory for running container {name}")
        containers[name] = mb
    return containers


def list_running_pm_containers() -> list[str]:
    """Names of running pm containers.  Raises MemoryMeasurementError."""
    result = _run_runtime(
        ["ps", "--filter", f"name={_CONTAINER_PREFIX}", "--format", "{{.Names}}"],
        timeout=_STATS_TIMEOUT)
    return [n.strip() for n in result.stdout.splitlines()
            if n.strip().startswith(_CONTAINER_PREFIX)]


# cgroup v2 then v1 peak counters, read from inside the container (each
# container gets a private cgroup namespace, so these are its own).
_PEAK_FILES = ("/sys/fs/cgroup/memory.peak",
               "/sys/fs/cgroup/memory/memory.max_usage_in_bytes")


def capture_container_peak(name: str) -> int | None:
    """The container's cgroup peak memory (MiB), or None if unavailable."""
    for path in _PEAK_FILES:
        try:
            result = _run_runtime(["exec", name, "cat", path],
                                  timeout=_CAPTURE_TIMEOUT)
        except MemoryMeasurementError:
            continue
        try:
            value = int(result.stdout.strip())
        except ValueError:
            continue
        if value > 0:
            return int(math.ceil(value / (1024 * 1024)))
    return None


def capture_container_memory(name: str) -> int | None:
    """Current memory usage (MiB) for a single container, or None."""
    try:
        result = _run_runtime(
            ["stats", "--no-stream", "--format", "{{.MemUsage}}", name],
            timeout=_CAPTURE_TIMEOUT)
        current = result.stdout.strip().split("/")[0].strip()
        mb = parse_runtime_memory(current)
    except (MemoryMeasurementError, ValueError):
        return None
    return mb if mb > 0 else None


def _parse_started_at(s: str) -> datetime:
    """Parse a runtime StartedAt value.

    Docker (and Podman's JSON) use RFC 3339 with nanoseconds
    (``2026-04-07T14:30:00.123456789Z``); Podman's Go template renders
    ``2026-04-07 14:30:00.123456789 +0000 UTC``.
    """
    s = s.strip().strip('"')
    s = re.sub(r"\s+[A-Z]{2,5}$", "", s)          # trailing zone name
    s = re.sub(r"(\.\d{6})\d*", r"\1", s)          # ns -> us
    s = s.replace("Z", "+00:00")
    s = re.sub(r"\s([+-]\d{2})(\d{2})$", r"\1:\2", s)  # " +0000" -> "+00:00"
    return datetime.fromisoformat(s.replace(" ", "T", 1))


def get_container_age_minutes(name: str) -> float | None:
    """How long a container has been running, in minutes; None on failure."""
    try:
        result = _run_runtime(
            ["inspect", "--format", "{{.State.StartedAt}}", name],
            timeout=_CAPTURE_TIMEOUT)
        started = _parse_started_at(result.stdout)
    except (MemoryMeasurementError, ValueError):
        return None
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - started
    return max(0.0, age.total_seconds() / 60.0)


# ---------------------------------------------------------------------------
# Host memory
# ---------------------------------------------------------------------------

@dataclass
class HostMemory:
    total_mb: int
    available_mb: int

    @property
    def used_mb(self) -> int:
        return max(0, self.total_mb - self.available_mb)


def read_host_memory() -> HostMemory | None:
    """Host total/available memory (MiB), or None if unavailable.

    Reads /proc/meminfo on Linux, falls back to sysctl/vm_stat on macOS.
    """
    system = platform.system()

    if system == "Linux":
        try:
            info: dict[str, int] = {}
            with open("/proc/meminfo") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 2 and parts[0].endswith(":"):
                        try:
                            info[parts[0][:-1]] = int(parts[1])  # kB
                        except ValueError:
                            pass
        except OSError:
            return None
        total = info.get("MemTotal", 0)
        if total <= 0 or "MemAvailable" not in info:
            return None
        return HostMemory(total // 1024, info["MemAvailable"] // 1024)

    if system == "Darwin":
        try:
            result = subprocess.run(["sysctl", "-n", "hw.memsize"],
                                    capture_output=True, text=True, timeout=5)
            if result.returncode != 0:
                return None
            total_mb = int(result.stdout.strip()) // (1024 * 1024)
            result = subprocess.run(["vm_stat"], capture_output=True,
                                    text=True, timeout=5)
            if result.returncode != 0:
                return None
            page_size = 4096
            m = re.search(r"page size of (\d+) bytes", result.stdout)
            if m:
                page_size = int(m.group(1))
            free_pages = 0
            for key in ("Pages free", "Pages inactive", "Pages purgeable"):
                m = re.search(rf"{key}:\s+(\d+)", result.stdout)
                if m:
                    free_pages += int(m.group(1))
            return HostMemory(total_mb, (free_pages * page_size) // (1024 * 1024))
        except (subprocess.TimeoutExpired, OSError, ValueError):
            return None

    return None


def get_system_memory_used_mb() -> int | None:
    """Total host memory in use (MiB), or None if unavailable."""
    host = read_host_memory()
    return host.used_mb if host else None


# ---------------------------------------------------------------------------
# Settings readers
# ---------------------------------------------------------------------------

def _scope() -> str:
    scope = get_global_setting_value("container-system-memory-scope", "pm") or "pm"
    if scope not in ("pm", "system"):
        raise GovernorConfigError(
            f"invalid system-memory-scope {scope!r} (expected pm or system)")
    return scope


def get_memory_target() -> int | None:
    """The system-memory-target in MiB, or None if unset (governor inactive).

    Raises :class:`GovernorConfigError` for an unparseable value: a typo
    must not silently switch the governor off.
    """
    raw = get_global_setting_value("container-system-memory-target", "")
    if not raw:
        return None
    try:
        return parse_memory(raw)
    except ValueError:
        raise GovernorConfigError(
            f"invalid system-memory-target {raw!r}; fix it with "
            f"'pm container set system-memory-target <size>'") from None


def governor_active() -> bool:
    """True when a memory target is configured.  May raise GovernorConfigError."""
    return get_memory_target() is not None


def parse_reserve(raw: str, total_mb: int) -> int:
    """Parse a reserve value (``"8g"`` or ``"10%"`` of *total_mb*) to MiB."""
    raw = raw.strip()
    if raw.endswith("%"):
        pct = float(raw[:-1])
        if not 0 <= pct < 100:
            raise ValueError(f"reserve percentage out of range: {raw!r}")
        return int(total_mb * pct / 100)
    return parse_memory(raw)


def get_reserve_mb(total_mb: int) -> int:
    """Free host memory (MiB) that admission must leave untouched."""
    raw = get_global_setting_value("container-system-memory-reserve",
                                   _DEFAULT_RESERVE) or _DEFAULT_RESERVE
    try:
        return parse_reserve(raw, total_mb)
    except ValueError:
        raise GovernorConfigError(
            f"invalid system-memory-reserve {raw!r} (expected e.g. 8g or 10%)"
        ) from None


def get_default_projection() -> int | None:
    """Read the system-memory-default-projection setting (MiB) or None."""
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
                  age_minutes: float, kind: str = "snapshot") -> None:
    """Record an end-of-life memory sample for a container type.

    *kind* is ``"peak"`` for a cgroup peak counter and ``"snapshot"`` for
    usage at teardown.  Appends to the rolling window, dropping the oldest
    sample past the configured history size.  Cross-process safe via
    ``governor_lock``; a busy lock skips the sample rather than block
    container teardown.
    """
    from pm_core.launch_queue import governor_lock, GovernorLockTimeout

    try:
        with governor_lock(timeout=_CAPTURE_TIMEOUT):
            stats = load_stats()
            entry = stats.setdefault(container_type, {})
            samples = entry.setdefault("samples", [])

            samples.append({
                "memory_mb": memory_mb,
                "kind": kind,
                "age_minutes": round(age_minutes, 1),
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            })

            max_samples = get_history_size()
            if len(samples) > max_samples:
                entry["samples"] = samples[-max_samples:]

            save_stats(stats)
    except GovernorLockTimeout as e:
        _log.warning("Skipping %s memory sample: %s", container_type, e)


# ---------------------------------------------------------------------------
# Memory projection
# ---------------------------------------------------------------------------

def _sample_value(sample: dict) -> float:
    mb = float(sample.get("memory_mb", 0) or 0)
    if sample.get("kind") != "peak":
        mb *= _SNAPSHOT_GROWTH_FACTOR
    return mb


def _fallback_projection() -> int:
    default_proj = get_default_projection()
    if default_proj is not None:
        return default_proj
    from pm_core.container import load_container_config
    try:
        return parse_memory(load_container_config().memory_limit)
    except ValueError:
        return 8192  # 8 GiB as absolute fallback


def project_memory(container_type: str, stats: dict | None = None) -> int:
    """Project peak memory (MiB) for a new container of the given type.

    Cascade:
      1. 90th percentile (nearest rank) of the stored samples, snapshot
         samples inflated by ``_SNAPSHOT_GROWTH_FACTOR`` (any count >= 1)
      2. system-memory-default-projection setting (if set)
      3. Per-container memory-limit from ContainerConfig
    """
    if stats is None:
        stats = load_stats()
    entry = stats.get(container_type, {})
    samples = entry.get("samples", []) if isinstance(entry, dict) else []
    values = sorted(_sample_value(s) for s in samples
                    if isinstance(s, dict) and (s.get("memory_mb") or 0) > 0)
    if values:
        rank = max(1, math.ceil(_PROJECTION_PERCENTILE * len(values)))
        return max(1, int(math.ceil(values[rank - 1])))
    return _fallback_projection()


# ---------------------------------------------------------------------------
# Snapshot + admission
# ---------------------------------------------------------------------------

@dataclass
class MemorySnapshot:
    """What admission knows about memory right now."""
    target_mb: int | None = None
    scope: str = "pm"
    # Committed usage in the target's scope, including the growth still
    # ahead of running pm containers.  None when unmeasurable.
    used_mb: int | None = None
    measured_mb: int | None = None   # usage as measured, without growth
    growth_mb: int = 0
    host: HostMemory | None = None
    reserve_mb: int | None = None
    running_names: set[str] = field(default_factory=set)
    error: str = ""

    @property
    def active(self) -> bool:
        return self.target_mb is not None


def take_snapshot(stats: dict | None = None) -> MemorySnapshot:
    """Measure committed memory for admission.  Never raises.

    ``snapshot.error`` is set (and admission must refuse) when the target
    or scope is invalid, usage cannot be measured, or — on Linux — host
    memory is unreadable.
    """
    snap = MemorySnapshot()
    try:
        snap.target_mb = get_memory_target()
        snap.scope = _scope()
    except GovernorConfigError as e:
        snap.error = str(e)
        return snap
    if snap.target_mb is None:
        return snap
    if stats is None:
        stats = load_stats()

    projections: dict[str, int] = {}

    def _proj(name: str) -> int | None:
        ctype = infer_container_type(name)
        if ctype is None:
            return None
        if ctype not in projections:
            projections[ctype] = project_memory(ctype, stats=stats)
        return projections[ctype]

    snap.host = read_host_memory()
    if snap.host is None and platform.system() == "Linux":
        snap.error = "host memory unreadable (/proc/meminfo)"
        return snap
    if snap.host is not None:
        try:
            snap.reserve_mb = get_reserve_mb(snap.host.total_mb)
        except GovernorConfigError as e:
            snap.error = str(e)
            return snap

    running: dict[str, int] | None
    try:
        running = get_pm_container_memory()
        stats_error = ""
    except MemoryMeasurementError as e:
        running, stats_error = None, str(e)

    if running is not None:
        snap.running_names = set(running)
        snap.growth_mb = sum(max(0, (_proj(n) or 0) - mb)
                             for n, mb in running.items())
    if snap.scope == "pm":
        if running is None:
            snap.error = f"container stats unavailable: {stats_error}"
            return snap
        snap.measured_mb = sum(running.values())
        snap.used_mb = snap.measured_mb + snap.growth_mb
        return snap

    # System scope.
    if snap.host is None:
        snap.error = "system memory unavailable on this platform"
        return snap
    snap.measured_mb = snap.host.used_mb
    if running is None:
        # Per-container stats are unavailable but the host total is not:
        # assume every running pm container still has its full projection
        # ahead of it.
        try:
            names = list_running_pm_containers()
        except MemoryMeasurementError as e:
            snap.error = (f"container stats unavailable ({stats_error}) and "
                          f"cannot list running containers: {e}")
            return snap
        snap.running_names = set(names)
        snap.growth_mb = sum(_proj(n) or 0 for n in names)
    snap.used_mb = snap.measured_mb + snap.growth_mb
    return snap


def admit(snapshot: MemorySnapshot, projected_mb: int,
          inflight_mb: int = 0) -> tuple[bool, str]:
    """Would one more container projected at *projected_mb* fit?

    *inflight_mb* is memory already promised to granted launches whose
    containers are not running yet.  Returns ``(ok, reason)``.
    """
    if snapshot.error:
        return False, f"memory measurement unavailable: {snapshot.error}"
    if snapshot.target_mb is None:
        return True, ""
    assert snapshot.used_mb is not None
    needed = snapshot.used_mb + inflight_mb + projected_mb
    if needed > snapshot.target_mb:
        parts = f"{_fmt_mb(snapshot.measured_mb or 0)} used"
        if snapshot.growth_mb:
            parts += f" + {_fmt_mb(snapshot.growth_mb)} expected growth"
        if inflight_mb:
            parts += f" + {_fmt_mb(inflight_mb)} reserved"
        return False, (f"{parts} + {_fmt_mb(projected_mb)} projected "
                       f"> {_fmt_mb(snapshot.target_mb)} target "
                       f"({snapshot.scope} scope)")
    if snapshot.host is not None and snapshot.reserve_mb is not None:
        growth = snapshot.growth_mb
        left = snapshot.host.available_mb - growth - inflight_mb - projected_mb
        if left < snapshot.reserve_mb:
            return False, (
                f"host headroom: {_fmt_mb(snapshot.host.available_mb)} free "
                f"- {_fmt_mb(growth + inflight_mb + projected_mb)} committed "
                f"would leave {_fmt_mb(max(left, 0))} "
                f"< {_fmt_mb(snapshot.reserve_mb)} reserve")
    return True, ""


def check_launch(container_type: str,
                 count: int = 1) -> tuple[bool, str]:
    """Diagnostic gate check for ``count`` containers of a type.

    Accounts for in-flight queue reservations.  Production launches go
    through :mod:`pm_core.launch_queue` instead, which also orders
    competing launches.  Returns ``(True, "")`` when the governor is
    inactive and ``(False, reason)`` when it cannot measure.
    """
    from pm_core.launch_queue import (
        governor_lock, GovernorLockTimeout, _load_queue,
    )
    try:
        if get_memory_target() is None:
            return True, ""
    except GovernorConfigError as e:
        return False, str(e)
    try:
        with governor_lock():
            stats = load_stats()
            snapshot = take_snapshot(stats=stats)
            inflight = 0
            for e in _load_queue()["entries"]:
                if (e.get("status") == "acquired"
                        and e.get("container_name") not in snapshot.running_names):
                    inflight += project_memory(
                        e.get("container_type") or "other", stats=stats)
            projected = count * project_memory(container_type, stats=stats)
            return admit(snapshot, projected, inflight)
    except GovernorLockTimeout as e:
        return False, str(e)


def check_single_container_fits(container_type: str) -> tuple[bool, str]:
    """Check if a single container's projection fits within the target at all.

    Detects the E2 edge case where per-container limit > target.
    Returns ``(fits, reason)``.
    """
    try:
        target = get_memory_target()
    except GovernorConfigError as e:
        return False, str(e)
    if target is None:
        return True, ""

    projected = project_memory(container_type)
    if projected > target:
        return False, (
            f"Container projection ({_fmt_mb(projected)}) exceeds system "
            f"memory target ({_fmt_mb(target)}) — a single container cannot "
            f"fit. Increase the target or lower the per-container memory "
            f"limit / default projection."
        )
    return True, ""


# ---------------------------------------------------------------------------
# Memory capture before stop/removal
# ---------------------------------------------------------------------------

def capture_and_record(name: str) -> None:
    """Capture a container's peak (or current) memory and age as a sample.

    Best-effort: failures are logged but don't block the caller.
    """
    ctype = infer_container_type(name)
    if ctype is None:
        _log.debug("Cannot infer type for container %s — skipping stats", name)
        return

    kind = "peak"
    memory_mb = capture_container_peak(name)
    if memory_mb is None:
        kind = "snapshot"
        memory_mb = capture_container_memory(name)
    if memory_mb is None:
        _log.debug("Cannot capture memory for %s — skipping stats", name)
        return

    age = get_container_age_minutes(name)
    if age is None:
        age = 0.0

    _log.info("Recording stats for %s (%s): %dMB %s, %.1f min",
              name, ctype, memory_mb, kind, age)
    record_sample(ctype, memory_mb, age, kind=kind)


def transcript_touched_since(transcript_path: str | None, since: float,
                             slack: float = 2.0) -> bool:
    """True if the session transcript changed after *since* (+ *slack*).

    Claude appends to its JSONL as soon as a prompt is submitted, so a
    newer mtime means someone resumed the session after it went idle —
    stop-on-idle must then leave the container alone.
    """
    if not transcript_path:
        return False
    try:
        return os.stat(transcript_path).st_mtime > since + slack
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Blocked launches (shown in the TUI status bar)
# ---------------------------------------------------------------------------

def _blocked_path() -> Path:
    return pm_home() / _BLOCKED_FILE


def _load_blocked() -> dict:
    try:
        data = json.loads(_blocked_path().read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_blocked(data: dict) -> None:
    path = _blocked_path()
    tmp = path.with_suffix(".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(data, indent=2) + "\n")
        tmp.replace(path)
    except OSError as e:
        _log.debug("Failed to save %s: %s", path, e)


def record_blocked(action: str, reason: str) -> None:
    """Remember that *action* (e.g. ``"impl pr-123"``) was refused."""
    data = _load_blocked()
    data[action] = {"reason": reason, "at": time.time()}
    _save_blocked(data)


def clear_blocked(action: str) -> None:
    """Forget a refused *action* once it launches."""
    data = _load_blocked()
    if data.pop(action, None) is not None:
        _save_blocked(data)


def recent_blocked(window: float = _BLOCKED_DISPLAY_SECONDS) -> list[tuple[str, str]]:
    """``(action, reason)`` for launches refused within *window*, newest first."""
    now = time.time()
    rows = [(v.get("at", 0), k, v.get("reason", ""))
            for k, v in _load_blocked().items() if isinstance(v, dict)]
    return [(k, r) for at, k, r in sorted(rows, reverse=True) if now - at <= window]


# ---------------------------------------------------------------------------
# Status display helpers
# ---------------------------------------------------------------------------

def compute_memory_status() -> str:
    """Memory status for the status bar, measured now (may take seconds).

    Returns e.g. ``"mem 34G/48G (pm)"``, ``"mem ?/48G (pm) stats unavailable"``
    or "" when the governor is inactive.  A launch refused recently is
    appended (``"blocked: impl pr-1"``).
    """
    snap = take_snapshot()
    if not snap.active and not snap.error:
        return ""
    scope_label = "sys" if snap.scope == "system" else "pm"
    target = _fmt_mb(snap.target_mb) if snap.target_mb else "?"
    if snap.error:
        text = f"mem ?/{target} ({scope_label}) unmeasurable"
    else:
        text = f"mem {_fmt_mb(snap.used_mb or 0)}/{target} ({scope_label})"
    blocked = recent_blocked()
    if blocked:
        text += f" blocked: {blocked[0][0]}"
        if len(blocked) > 1:
            text += f" +{len(blocked) - 1}"
    return text


_status_lock = threading.Lock()
_status_text = ""
_status_at = 0.0
_status_refreshing = False


def refresh_memory_status() -> str:
    """Recompute and cache the status text.  Safe to call from a worker."""
    global _status_text, _status_at, _status_refreshing
    try:
        text = compute_memory_status()
    except Exception:
        _log.debug("memory status refresh failed", exc_info=True)
        text = _status_text
    with _status_lock:
        _status_text, _status_at = text, time.monotonic()
        _status_refreshing = False
    return text


def format_memory_status(max_age: float = 15.0) -> str:
    """Cached memory status for UI threads — never blocks on the runtime.

    Returns the last computed text and, when it is older than *max_age*,
    starts a background refresh (the next call sees the new value).
    """
    global _status_refreshing
    with _status_lock:
        text = _status_text
        stale = time.monotonic() - _status_at > max_age
        start = stale and not _status_refreshing
        if start:
            _status_refreshing = True
    if start:
        threading.Thread(target=refresh_memory_status, daemon=True,
                         name="pm-memory-status").start()
    return text
