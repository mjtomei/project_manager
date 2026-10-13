"""Workspace-trust bootstrap for unattended agent sessions.

Interactive agent CLIs can refuse to start work in a directory until a
human confirms they trust it.  pm creates fresh checkouts for every PR,
QA run and QA scenario, so an unattended session launched there sits at
that dialog forever (pr-b53bfe2: a host QA planner waited the full hour,
then the finalizer blocked at the same prompt).

This module keeps the runtime-specific mechanics behind a small
interface so the launcher (``claude_launcher``) stays the only place
that knows which runtime is in use:

* :func:`approved_path` — the narrow policy: only PM-created workdirs
  (under ``~/.pm/workdirs``) and paths the user explicitly authorized
  with ``pm trust add`` may be trusted automatically.  Nothing else is
  ever written; unknown workspaces keep their explicit prompt.
* :class:`TrustRuntime` — per-runtime mechanics: ``bootstrap`` records
  trust for one approved checkout, ``seed_config`` prepares a config copy
  for a container, ``detect_prompt``/``accept_keys`` read the dialog off a
  pane.  :class:`ClaudeWorkspaceTrust` is the Claude Code implementation.

Workspace trust is deliberately separate from tool-permission bypass
(``--dangerously-skip-permissions``): neither implies the other.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from pm_core.paths import configure_logger

_log = configure_logger("pm.workspace_trust")

# Global setting (``~/.pm/settings/<name>``) holding explicitly authorized
# workspace roots, one absolute path per line.
TRUSTED_WORKSPACES_SETTING = "trusted-workspaces"

# Outcome statuses returned by TrustRuntime.bootstrap.
TRUSTED = "trusted"          # entry written by this call
ALREADY = "already"          # entry was already present
UNAPPROVED = "unapproved"    # path outside the approved roots; nothing written
UNSUPPORTED = "unsupported"  # runtime has no trust mechanism
ERROR = "error"              # approved, but the entry could not be written


@dataclass
class TrustOutcome:
    status: str
    path: str
    message: str = ""

    @property
    def ok(self) -> bool:
        return self.status in (TRUSTED, ALREADY, UNSUPPORTED)


# ---------------------------------------------------------------------------
# Approval policy
# ---------------------------------------------------------------------------

def _real(path: str | Path) -> str:
    return os.path.realpath(os.path.abspath(os.path.expanduser(str(path))))


def _is_within(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip("/") + "/")


def authorized_roots() -> list[str]:
    """Paths the user explicitly authorized via ``pm trust add``."""
    from pm_core.paths import get_global_setting_value
    raw = get_global_setting_value(TRUSTED_WORKSPACES_SETTING, "")
    return [line.strip() for line in raw.splitlines() if line.strip()]


def set_authorized_roots(roots: list[str]) -> None:
    from pm_core.paths import set_global_setting_value
    seen: list[str] = []
    for r in roots:
        if r not in seen:
            seen.append(r)
    set_global_setting_value(TRUSTED_WORKSPACES_SETTING, "\n".join(seen))


def approved_roots() -> list[str]:
    """Roots under which pm may establish workspace trust automatically."""
    from pm_core.paths import workdirs_base
    return [_real(workdirs_base())] + [_real(r) for r in authorized_roots()]


def approved_path(path: str | Path) -> bool:
    """True when *path* is a PM-created or explicitly authorized workdir."""
    real = _real(path)
    return any(_is_within(real, root) for root in approved_roots())


def _git_toplevel(path: str) -> str | None:
    try:
        r = subprocess.run(
            ["git", "-C", path, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    top = r.stdout.strip()
    return top if r.returncode == 0 and top else None


def trust_keys(path: str | Path) -> list[str]:
    """Approved config keys that establish trust for *path*.

    The checkout itself (absolute and resolved spellings) plus its git
    root when that root is itself approved.  Never a parent outside the
    approved roots.
    """
    keys: list[str] = []
    abspath = os.path.abspath(os.path.expanduser(str(path)))
    candidates = [abspath, _real(abspath)]
    top = _git_toplevel(abspath)
    if top:
        candidates += [top, _real(top)]
    for k in candidates:
        if k not in keys and approved_path(k):
            keys.append(k)
    return keys


# ---------------------------------------------------------------------------
# Runtime interface
# ---------------------------------------------------------------------------

class TrustRuntime:
    """Workspace-trust mechanics for one agent runtime.

    The default implementation is a no-op for runtimes without a trust
    dialog: bootstrap reports ``unsupported`` and no prompt is ever
    detected.
    """

    name = "none"

    def bootstrap(self, path: str | Path) -> TrustOutcome:
        return TrustOutcome(UNSUPPORTED, str(path),
                            f"runtime {self.name!r} has no workspace-trust mechanism")

    def is_trusted(self, path: str | Path) -> bool:
        return True

    def seed_config(self, src: Path, dest: Path,
                    trusted_paths: list[str]) -> bool:
        """Write a copy of the runtime config at *dest* that trusts
        *trusted_paths* (container-internal paths).  Returns False when the
        runtime has nothing to seed."""
        return False

    def detect_prompt(self, screen: str) -> str | None:
        """Return the workspace path shown by a trust dialog on *screen*
        ("" when the dialog is visible but the path is not), else None."""
        return None

    def accept_keys(self, screen: str) -> list[str] | None:
        """tmux key names that select the dialog's "trust" option and
        confirm it, or None when the screen can't be read safely."""
        return None


_TRUST_PROMPT_RE = re.compile(
    r"Accessing workspace:|Do you trust the files in this folder\?"
    r"|Is this a project you created or one you trust\?"
)
_YES_OPTION_RE = re.compile(r"Yes, I trust this folder|Yes, proceed")
_OPTION_RE = re.compile(r"^\s*(❯|>)?\s*(\d+\.\s*)?(Yes, I trust this folder|Yes, proceed|No, exit)\b")


class ClaudeWorkspaceTrust(TrustRuntime):
    """Claude Code: ``projects[<path>].hasTrustDialogAccepted`` in the
    global config, written under Claude's own ``<config>.lock`` lock."""

    name = "claude"
    LOCK_STALE_SECONDS = 10.0   # proper-lockfile default used by Claude
    LOCK_TIMEOUT_SECONDS = 15.0

    def config_path(self) -> Path:
        base = os.environ.get("CLAUDE_CONFIG_DIR")
        if base:
            return Path(base).expanduser() / ".claude.json"
        return Path.home() / ".claude.json"

    # --- config IO ---------------------------------------------------------

    def _acquire_lock(self, cfg: Path) -> Path:
        lock = Path(str(cfg) + ".lock")
        deadline = time.monotonic() + self.LOCK_TIMEOUT_SECONDS
        while True:
            try:
                os.mkdir(lock)
                return lock
            except FileExistsError:
                try:
                    age = time.time() - lock.stat().st_mtime
                except FileNotFoundError:
                    continue
                if age > self.LOCK_STALE_SECONDS:
                    _log.warning("workspace trust: removing stale lock %s "
                                 "(%.0fs old)", lock, age)
                    try:
                        os.rmdir(lock)
                    except OSError:
                        pass
                    continue
                if time.monotonic() > deadline:
                    raise TimeoutError(f"timed out waiting for {lock}")
                time.sleep(0.05)

    def _read(self, cfg: Path) -> dict:
        try:
            text = cfg.read_text()
        except FileNotFoundError:
            return {}
        data = json.loads(text) if text.strip() else {}
        if not isinstance(data, dict):
            raise ValueError(f"{cfg} is not a JSON object")
        return data

    @staticmethod
    def _write_atomic(cfg: Path, data: dict, mode: int = 0o600) -> None:
        cfg.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".claude.json.pm-", dir=str(cfg.parent))
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2)
            os.chmod(tmp, mode)
            os.replace(tmp, cfg)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    @staticmethod
    def _mark(data: dict, keys: list[str]) -> bool:
        projects = data.get("projects")
        if not isinstance(projects, dict):
            projects = {}
            data["projects"] = projects
        changed = False
        for k in keys:
            entry = projects.get(k)
            if not isinstance(entry, dict):
                entry = {}
            if entry.get("hasTrustDialogAccepted") is not True:
                projects[k] = {**entry, "hasTrustDialogAccepted": True}
                changed = True
        return changed

    # --- TrustRuntime ------------------------------------------------------

    def is_trusted(self, path: str | Path) -> bool:
        try:
            projects = self._read(self.config_path()).get("projects") or {}
        except (OSError, ValueError):
            return False
        # Mirror Claude's lookup: the path or any ancestor up to (and
        # including) its git root; unbounded when not in a git repo.
        start = os.path.abspath(os.path.expanduser(str(path)))
        top = _git_toplevel(start)
        for base in dict.fromkeys([start, _real(start)]):
            cur = base
            while True:
                if (projects.get(cur) or {}).get("hasTrustDialogAccepted") is True:
                    return True
                if top and cur in (top, _real(top)):
                    break
                parent = os.path.dirname(cur)
                if parent == cur:
                    break
                cur = parent
        return False

    def bootstrap(self, path: str | Path) -> TrustOutcome:
        path = str(path)
        if not approved_path(path):
            return TrustOutcome(
                UNAPPROVED, path,
                f"{path} is not a pm-created workdir or an authorized "
                f"workspace; run `pm trust add {path}` to authorize it")
        keys = trust_keys(path)
        cfg = self.config_path()
        try:
            lock = self._acquire_lock(cfg)
        except (OSError, TimeoutError) as e:
            return TrustOutcome(ERROR, path, f"could not lock {cfg}: {e}")
        try:
            try:
                data = self._read(cfg)
            except (OSError, ValueError) as e:
                return TrustOutcome(ERROR, path, f"could not read {cfg}: {e}")
            if not self._mark(data, keys):
                return TrustOutcome(ALREADY, path)
            try:
                mode = cfg.stat().st_mode & 0o777
            except FileNotFoundError:
                mode = 0o600
            self._write_atomic(cfg, data, mode)
        except OSError as e:
            return TrustOutcome(ERROR, path, f"could not write {cfg}: {e}")
        finally:
            try:
                os.rmdir(lock)
            except OSError:
                pass
        _log.info("workspace trust: trusted %s in %s", keys, cfg)
        return TrustOutcome(TRUSTED, path)

    def seed_config(self, src: Path, dest: Path,
                    trusted_paths: list[str]) -> bool:
        try:
            data = self._read(src)
        except (OSError, ValueError):
            _log.warning("workspace trust: cannot read %s to seed a copy", src,
                         exc_info=True)
            return False
        self._mark(data, trusted_paths)
        self._write_atomic(dest, data)
        return True

    def detect_prompt(self, screen: str) -> str | None:
        if not screen or not _TRUST_PROMPT_RE.search(screen):
            return None
        if not _YES_OPTION_RE.search(screen):
            return None
        lines = screen.splitlines()
        for i, line in enumerate(lines):
            if "Accessing workspace:" in line:
                for nxt in lines[i + 1:i + 4]:
                    if nxt.strip().startswith("/"):
                        return nxt.strip()
        return ""

    def accept_keys(self, screen: str) -> list[str] | None:
        options: list[tuple[bool, bool]] = []  # (selected, is_yes)
        for line in screen.splitlines():
            m = _OPTION_RE.match(line)
            if m:
                options.append((bool(m.group(1)), m.group(3) != "No, exit"))
        selected = [i for i, (sel, _) in enumerate(options) if sel]
        yes = [i for i, (_, is_yes) in enumerate(options) if is_yes]
        if len(selected) != 1 or len(yes) != 1:
            return None
        delta = yes[0] - selected[0]
        return (["Down"] * delta if delta > 0 else ["Up"] * -delta) + ["Enter"]


_RUNTIMES: dict[str, TrustRuntime] = {"claude": ClaudeWorkspaceTrust()}


def register_trust_runtime(name: str, runtime: TrustRuntime) -> None:
    _RUNTIMES[name] = runtime


def get_trust_runtime(name: str = "claude") -> TrustRuntime:
    return _RUNTIMES.get(name) or TrustRuntime()


def prompt_grace_seconds() -> float:
    """How long a trust dialog may stay on screen before pm gives up."""
    from pm_core.paths import get_global_setting_value
    raw = get_global_setting_value("trust-prompt-grace-seconds", "")
    try:
        return max(0.0, float(raw)) if raw else 120.0
    except ValueError:
        return 120.0


def blocked_message(path: str, waited: float) -> str:
    where = path or "the session workdir"
    return (
        f"Claude is waiting at the workspace-trust prompt for {where} "
        f"(visible {waited:.0f}s). pm only auto-trusts pm-created workdirs "
        f"(~/.pm/workdirs) and paths authorized with `pm trust add`. "
        f"To proceed: run `pm trust add {where}` (or accept the prompt in "
        f"the pane), then restart this step."
    )


__all__ = [
    "TrustOutcome", "TrustRuntime", "ClaudeWorkspaceTrust",
    "approved_path", "approved_roots", "authorized_roots",
    "set_authorized_roots", "trust_keys", "register_trust_runtime",
    "get_trust_runtime", "prompt_grace_seconds", "blocked_message",
    "TRUSTED", "ALREADY", "UNAPPROVED", "UNSUPPORTED", "ERROR",
]
