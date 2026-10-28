"""Launch claude CLI sessions."""

import json
import logging
import os
import random
import re
import shlex
import shutil
import subprocess
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from pm_core.paths import configure_logger, log_shell_command, write_env_file
from pm_core.prompt_bounds import (
    PROMPT_ARG_LIMIT, PromptTooLargeError, prompt_bytes,
)
_log = configure_logger("pm.claude_launcher")

# The fake-claude executable is invoked by bare name and resolved from PATH —
# exactly like the real ``claude`` binary.  The on-PATH ``fake-claude`` is a
# tiny shim that resolves the actual binary via ``pm which`` at run time, so
# the pm install *under test* is used (host or container).  ``install.sh``
# writes the shim to ~/.local/bin on the host and
# ``container._build_git_setup_script`` writes the same shim at container
# startup, so the same command resolves correctly in *both* environments with
# no build-time path baking and no host->container rewrite.
_FAKE_CLAUDE_BIN = "fake-claude"


def _fake_claude_config_for_type(session_type: str | None) -> dict | None:
    """Return the merged fake-claude config for *session_type*, or None."""
    from pm_core.paths import fake_claude_config_for_type
    return fake_claude_config_for_type(session_type)


def _pick_fake_verdict(verdicts: dict) -> str:
    """Pick a verdict at random using the given weight map.

    Defensively tolerates a hand-edited weight map.  The supported
    ``pm fake-claude config set`` path validates weights (numeric,
    non-negative, not all-zero), but a directly-edited config must never
    crash the launcher — same invariant as review-loop 878e i1, which
    coerced malformed ``_all``/``_defaults``/per-type *shapes*; this covers
    malformed weight *values* inside an otherwise well-shaped per-type entry.
    Non-numeric / boolean / negative weights count as zero, and an all-zero
    (or otherwise unusable) map falls back to a uniform pick instead of
    crashing ``random.choices`` ("Total of weights must be greater than zero").
    """
    names = list(verdicts.keys())
    if not names:
        return "NONE"
    weights: list[float] = []
    for n in names:
        w = verdicts[n]
        if isinstance(w, bool) or not isinstance(w, (int, float)) or w < 0:
            weights.append(0.0)
        else:
            weights.append(float(w))
    if sum(weights) <= 0:
        return random.choice(names)
    return random.choices(names, weights=weights, k=1)[0]


def _clamp_cursor(raw, length: int, wrap: bool) -> int:
    """Normalise a stored cursor value into a valid index for a sequence.

    Coerces non-int / negative values to 0, then handles an out-of-range
    cursor (e.g. the config was edited to a shorter sequence): wrap → 0,
    clamp → the terminal slot.
    """
    cur = raw if isinstance(raw, int) and raw >= 0 else 0
    if cur >= length:
        cur = 0 if wrap else length - 1
    return cur


def _advance_scripted_cursor(session_tag: str | None, session_type: str,
                             sequence_len: int, wrap: bool) -> int:
    """Atomically advance the scripted-verdict cursor for *session_type*.

    The cursor lives in ``<session_dir>/fake-claude.state`` as JSON
    ``{"<session_type>": <next_index>}``.  Returns the index to use *this*
    invocation (then bumps it for the next).  Concurrent panes of the same
    session type advancing simultaneously are serialised via ``fcntl.flock``
    so neither grabs the same slot.

    ``wrap=False`` clamps the cursor at ``sequence_len - 1`` (the terminal
    entry keeps emitting once the script runs out).  ``wrap=True`` cycles
    back to 0.
    """
    import fcntl
    from pm_core.paths import session_dir

    if sequence_len <= 0:
        return 0
    sd = session_dir(session_tag)
    if sd is None:
        # No session dir → no place to persist the cursor.  Fall back to
        # always emitting the first entry (deterministic, drift-free).
        return 0
    state_path = sd / "fake-claude.state"
    fd = os.open(str(state_path), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            raw = os.read(fd, 1 << 20).decode("utf-8") or "{}"
            state = json.loads(raw) if raw.strip() else {}
            if not isinstance(state, dict):
                state = {}
        except (ValueError, OSError):
            state = {}
        cur = _clamp_cursor(state.get(session_type, 0), sequence_len, wrap)
        if wrap:
            nxt = (cur + 1) % sequence_len
        else:
            # Clamp toward the terminal slot; a one-entry sequence keeps
            # resolving to 0 (cur is already clamped above, so cur + 1 caps
            # at sequence_len - 1 == 0).
            nxt = min(cur + 1, sequence_len - 1)
        state[session_type] = nxt
        os.lseek(fd, 0, os.SEEK_SET)
        os.ftruncate(fd, 0)
        os.write(fd, (json.dumps(state) + "\n").encode("utf-8"))
        return cur
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _resolve_fake_verdict(verdicts, session_type: str | None,
                          session_tag: str | None) -> tuple[str, dict]:
    """Pick the next verdict and any per-iteration overrides.

    Returns ``(verdict_name, overrides_dict)``.  For weighted-random configs
    (a plain verdict→weight dict) the overrides dict is empty.  For
    scripted-sequence configs the overrides come from the per-entry dict (if
    any), layered later on top of the base config.

    ``"NONE"`` is returned when verdicts is empty/absent.
    """
    from pm_core.fake_claude import (_scripted_sequence, _scripted_entry_verdict,
                                      _scripted_wrap)

    if not verdicts:
        return "NONE", {}

    sequence = _scripted_sequence(verdicts)
    if sequence is None:
        # Existing weighted-random dict form.  A hand-edited config can put a
        # scalar here (e.g. ``"verdicts": "PASS"``); that is neither a weight
        # map nor a scripted sequence and would crash _pick_fake_verdict
        # (``.keys()`` on a str/int).  Per the i1/i2 invariant — a directly
        # edited config must never crash the launcher — treat any non-dict as
        # no-verdict rather than blowing up.
        if not isinstance(verdicts, dict):
            return "NONE", {}
        return _pick_fake_verdict(verdicts), {}

    if not sequence:
        return "NONE", {}

    # No persistent cursor without a session_type to key it under: emit slot 0.
    if not session_type:
        idx = 0
    else:
        idx = _advance_scripted_cursor(session_tag, session_type, len(sequence),
                                       _scripted_wrap(verdicts))
    entry = sequence[idx]
    name = _scripted_entry_verdict(entry) or "NONE"
    overrides: dict = {}
    if isinstance(entry, dict):
        overrides = {k: v for k, v in entry.items() if k != "verdict"}
    return name, overrides


def _fake_claude_args(config: dict, session_id: str | None = None,
                     session_type: str | None = None,
                     session_tag: str | None = None) -> list[str]:
    """Build the fake-claude argv (excluding the binary) from a config dict.

    Resolves the next verdict from the ``verdicts`` field, which may be:

    * a verdict→weight ``dict`` — random pick weighted by the values
    * a ``list`` of entries — scripted sequence (clamp-to-last by default)
    * a ``dict`` with ``"sequence"`` list and optional ``"wrap": true`` —
      scripted with wrap-around

    An empty / absent verdicts field means a no-verdict session
    (impl/watcher/merge, or a session type matched only by the ``_all``
    catch-all): the fake emits ``--verdict NONE`` and stays open like a real
    interactive session.

    Scripted entries may carry per-iteration overrides (``body``, ``delay``,
    ``preamble``, …) which are layered on top of the base config keys for
    just that invocation.

    When *session_id* is given it is passed through as ``--session-id`` so
    the fake writes a JSONL transcript and emits the ``idle_prompt`` hook
    event — the inputs the hook-driven verdict poller actually reads.
    """
    verdicts = config.get("verdicts") or {}
    verdict, overrides = _resolve_fake_verdict(verdicts, session_type, session_tag)

    # Layer per-entry overrides on top of the base config.  Caller's config
    # values lose to script-entry overrides for this single invocation.
    effective = {k: v for k, v in config.items() if k != "verdicts"}
    effective.update(overrides)

    args = ["--verdict", verdict]
    if session_id:
        args.extend(["--session-id", session_id])
    if "body" in effective:
        args.extend(["--body", str(effective["body"])])
    for cfg_key, flag in (
        ("preamble", "--preamble"),
        ("preamble_delay", "--preamble-delay"),
        ("delay", "--delay"),
        ("body_lines", "--body-lines"),
        ("body_batch", "--body-batch"),
        ("body_delay", "--body-delay"),
        ("hold", "--hold"),
        ("display_bullet", "--display-bullet"),
    ):
        if cfg_key in effective:
            args.extend([flag, str(effective[cfg_key])])
    return args


def peek_fake_verdicts(session_tag: str | None = None) -> dict:
    """Return ``{session_type: next_verdict}`` without advancing any cursors.

    Useful as a debug aid for scripted-sequence configs: shows which slot
    each session type would emit on its next launch.  Weighted-random
    configs report ``"<random>"`` since the pick is non-deterministic.
    Session types whose verdicts are empty/absent report ``"NONE"``.
    """
    from pm_core.fake_claude import (_scripted_sequence, _scripted_entry_verdict,
                                      _scripted_wrap)
    from pm_core.paths import fake_claude_config, session_dir

    raw = fake_claude_config(session_tag)
    if not raw:
        return {}
    sd = session_dir(session_tag)
    state: dict = {}
    if sd is not None:
        state_path = sd / "fake-claude.state"
        if state_path.exists():
            try:
                state = json.loads(state_path.read_text()) or {}
                if not isinstance(state, dict):
                    state = {}
            except (OSError, json.JSONDecodeError):
                state = {}

    out: dict = {}
    for key, value in raw.items():
        # Skip non-session-type keys: _defaults, _all (mirrors the
        # filtering in set_fake_claude_config).
        if key.startswith("_") or not isinstance(value, dict):
            continue
        verdicts = value.get("verdicts") or {}
        if not verdicts:
            out[key] = "NONE"
            continue
        seq = _scripted_sequence(verdicts)
        if seq is None:
            out[key] = "<random>"
            continue
        if not seq:
            out[key] = "NONE"
            continue
        cur = _clamp_cursor(state.get(key, 0), len(seq), _scripted_wrap(verdicts))
        out[key] = _scripted_entry_verdict(seq[cur]) or "NONE"
    return out


def _resolve_provider(provider: str | None = None):
    """Resolve provider config and return (env_vars, model_flag, run_env).

    Shared helper for launch_claude, launch_claude_print, and
    launch_claude_print_background to avoid repeating the same pattern.
    """
    from pm_core.providers import get_provider
    provider_cfg = get_provider(provider)
    provider_env = provider_cfg.env_vars()
    model_flag = provider_cfg.model_flag()
    run_env = {**os.environ, **provider_env} if provider_env else None
    return provider_env, model_flag, run_env

SESSION_REGISTRY = ".pm-sessions.json"


def _registry_path(pm_root: Path) -> Path:
    return pm_root / SESSION_REGISTRY


def load_session(root: Path, key: str) -> str | None:
    """Load a session ID from the registry, or None if not found."""
    path = _registry_path(root)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            return None
        entry = data.get(key)
        if entry and isinstance(entry, dict):
            return entry.get("session_id")
    except (json.JSONDecodeError, OSError):
        pass
    return None


def save_session(root: Path, key: str, session_id: str) -> None:
    """Save a session ID to the registry."""
    path = _registry_path(root)
    data = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text())
            if isinstance(loaded, dict):
                data = loaded
        except (json.JSONDecodeError, OSError):
            pass
    data[key] = {
        "session_id": session_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(data, indent=2) + "\n")


def clear_session(root: Path, key: str) -> None:
    """Remove a stored session from the registry."""
    path = _registry_path(root)
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return
    if key in data:
        del data[key]
        path.write_text(json.dumps(data, indent=2) + "\n")


def _parse_session_id(stderr_text: str) -> str | None:
    """Parse session_id from claude CLI verbose stderr output."""
    for line in stderr_text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict) and "session_id" in obj:
                return obj["session_id"]
        except (json.JSONDecodeError, ValueError):
            continue
    return None


def find_claude() -> str | None:
    """Return path to the claude CLI, or None if not found.

    Does not apply the fake-claude override — session-type is required for
    that.  Launch functions call ``_fake_claude_config_for_type`` directly.
    """
    return shutil.which("claude")


def _skip_permissions() -> bool:
    """Check if skip-permissions is enabled for current session.

    Looks for ~/.pm/sessions/{session-tag}/dangerously-skip-permissions
    file containing exactly 'true'.
    """
    from pm_core.paths import skip_permissions_enabled
    return skip_permissions_enabled()


def find_editor() -> str:
    """Return the user's preferred editor."""
    editor = os.environ.get("EDITOR")
    if editor:
        return editor
    for candidate in ("vim", "vi", "nano"):
        if shutil.which(candidate):
            return candidate
    return "vi"


# ---------------------------------------------------------------------------
# Workspace trust (runtime mechanics live in pm_core.workspace_trust)
# ---------------------------------------------------------------------------

class WorkspaceTrustBlocked(RuntimeError):
    """A launched session stayed at the workspace-trust prompt past the grace."""


def prepare_workspace(cwd: str | None):
    """Establish workspace trust for a host *cwd* before launching into it.

    Only pm-created or explicitly authorized workdirs are trusted (see
    ``workspace_trust.approved_path``); anything else is left to the
    runtime's own explicit prompt.  Never raises.
    """
    from pm_core import workspace_trust
    if not cwd or not os.path.isdir(cwd):
        return workspace_trust.TrustOutcome(
            workspace_trust.UNSUPPORTED, str(cwd or ""), "no host cwd")
    try:
        outcome = workspace_trust.get_trust_runtime().bootstrap(cwd)
    except Exception as e:  # never block a launch on bootstrap bugs
        _log.warning("workspace trust: bootstrap crashed for %s", cwd,
                     exc_info=True)
        return workspace_trust.TrustOutcome(workspace_trust.ERROR, cwd, str(e))
    if outcome.status == workspace_trust.UNAPPROVED:
        _log.info("workspace trust: %s not approved; leaving the prompt "
                  "explicit", cwd)
    elif not outcome.ok:
        _log.warning("workspace trust: %s", outcome.message)
    return outcome


class WorkspacePromptWatch:
    """Bounded watchdog for a pane that may be stuck at the trust prompt.

    ``check()`` is cheap to call from a poll loop: it captures the pane at
    most every *interval* seconds.  When the dialog is visible and
    *workdir* is approved, it selects the "trust" option by reading the
    cursor off the screen (never a blind Enter — the dialog defaults to
    "No, exit").  Returns an actionable message once the dialog has stayed
    visible longer than *grace* seconds, else None.

    *transcript_path* (the session's JSONL, or a symlink to it) ends the
    watch for good once it exists: Claude only writes it after the first
    prompt is submitted, i.e. after the dialog.  Without it, text later in
    the first turn that quotes the dialog could be mistaken for it.
    """

    MAX_ACCEPT_ATTEMPTS = 2
    # The cap is per pane, not per watch: one pane can be watched by
    # several watches (the QA loop's worker watch and the TUI idle
    # tracker's, and CLI pollers build a fresh tracker per call), so the
    # attempts already spent are also kept on the tmux pane itself.
    _ATTEMPTS_OPTION = "@pm_trust_accept_attempts"
    # The pid of the process that last reported this pane as blocked, so a
    # second watch in the same TUI (e.g. the orphan watch taking over a
    # review pane after its loop already failed on the dialog) does not
    # report it again.  A restarted TUI (new pid) still reports it once.
    _REPORTED_OPTION = "@pm_trust_reported_by"

    def __init__(self, pane_id: str, workdir: str | None = None,
                 grace: float | None = None, interval: float = 5.0,
                 transcript_path: str | Path | None = None):
        from pm_core import workspace_trust
        self.pane_id = pane_id
        self.workdir = workdir
        self.transcript_path = transcript_path
        self.started = False
        self.grace = workspace_trust.prompt_grace_seconds() if grace is None else grace
        self.interval = interval
        self._runtime = workspace_trust.get_trust_runtime()
        self._last_check = 0.0
        self._first_seen: float | None = None
        self._accept_attempts = 0
        self._reported = False
        # Set when the grace first runs out: another watch in this process
        # had already reported this pane.
        self.reported_elsewhere = False
        self.shown_path: str | None = None

    @property
    def visible(self) -> bool:
        """Whether the last check saw the trust dialog on screen."""
        return self._first_seen is not None

    def _accept_target(self, shown: str) -> str | None:
        """The approved directory the dialog may be accepted for, else None.

        A host path on the dialog decides: the session may have started
        somewhere other than *workdir* (never trust that by proxy).  Only an
        unreadable or container-internal path falls back to *workdir*; any
        other path that isn't a host directory (e.g. mis-parsed) is refused.
        """
        from pm_core import workspace_trust
        from pm_core.container import _CONTAINER_WORKDIR
        if shown and os.path.isdir(shown):
            target = shown
        elif not shown or workspace_trust.is_within(shown, _CONTAINER_WORKDIR):
            target = self.workdir
        else:
            return None
        if target and workspace_trust.approved_path(target):
            return target
        return None

    def _pane_attempts(self) -> int:
        """Accept attempts any watch has already made on this pane."""
        from pm_core import tmux as tmux_mod
        try:
            return int(tmux_mod.get_pane_option(
                self.pane_id, self._ATTEMPTS_OPTION) or 0)
        except ValueError:
            return 0

    def check(self, force: bool = False) -> str | None:
        from pm_core import tmux as tmux_mod, workspace_trust
        if self.started:
            return None
        if self.transcript_path and Path(self.transcript_path).exists():
            self.started = True
            self._first_seen = None
            return None
        now = time.monotonic()
        if not force and now - self._last_check < self.interval:
            return None
        self._last_check = now
        try:
            screen = tmux_mod.capture_pane(self.pane_id)
        except Exception:
            return None
        shown = self._runtime.detect_prompt(screen)
        if shown is None:
            self._first_seen = None
            return None
        self.shown_path = shown
        if self._first_seen is None:
            self._first_seen = now
            _log.warning("workspace trust: pane %s is at the trust prompt "
                         "(%s)", self.pane_id, shown or self.workdir)
        used = max(self._accept_attempts, self._pane_attempts())
        target = (self._accept_target(shown)
                  if used < self.MAX_ACCEPT_ATTEMPTS else None)
        if target:
            keys = self._runtime.accept_keys(screen)
            if keys:
                self._accept_attempts = used + 1
                tmux_mod.set_pane_option(self.pane_id, self._ATTEMPTS_OPTION,
                                         str(self._accept_attempts))
                _log.info("workspace trust: accepting prompt in pane %s for "
                          "approved workdir %s (keys=%s)", self.pane_id,
                          target, keys)
                prepare_workspace(target)
                for key in keys:
                    tmux_mod.send_keys_literal(self.pane_id, key)
                    time.sleep(0.2)
                return None
        waited = now - self._first_seen
        if waited >= self.grace:
            if not self._reported:
                self._reported = True
                pid = str(os.getpid())
                self.reported_elsewhere = tmux_mod.get_pane_option(
                    self.pane_id, self._REPORTED_OPTION) == pid
                tmux_mod.set_pane_option(self.pane_id, self._REPORTED_OPTION,
                                         pid)
            return workspace_trust.blocked_message(
                shown or self.workdir or "", waited)
        return None


def _prompt_is_oversized(prompt: str | None) -> bool:
    """True when *prompt* exceeds the single-argv-entry budget."""
    return bool(prompt) and prompt_bytes(prompt) > PROMPT_ARG_LIMIT


def _bootstrap_prompt(path: str) -> str:
    """A short argv prompt pointing claude at its full instructions on disk.

    Used when the real prompt is too large for one argv entry: the complete
    text is written to *path* and claude reads it on startup.  This preserves
    every instruction (no truncation) while keeping argv small.
    """
    return f"Your complete instructions are in the file at {path}."


def _materialize_oversized_prompt(
    prompt: str, *, cwd: str | None = None, write_dir: str | None = None,
    session_id: str | None = None,
) -> tuple[str, str | None]:
    """Return ``(argv_prompt, temp_path)`` for a possibly oversized *prompt*.

    Under the limit the prompt is returned unchanged with no temp path.  Over
    it, the full prompt is written to a file and a short bootstrap prompt is
    returned; the caller must delete *temp_path* after the process exits.
    Raises :class:`PromptTooLargeError` when no writable location exists.

    The file lands on the host path (*write_dir*) while the bootstrap names
    the path claude sees at runtime (*cwd*) — in a container those differ,
    because the host workdir is mounted at the container path (the same split
    ``build_claude_shell_cmd`` uses).  With only one of the two given, that
    one is used for both.
    """
    if not _prompt_is_oversized(prompt):
        return prompt, None
    candidates: list[tuple[str, str]] = []
    if write_dir:
        candidates.append((write_dir, cwd or write_dir))
    if cwd and cwd != write_dir:
        candidates.append((cwd, cwd))
    for write_base, ref_base in candidates:
        try:
            b = Path(write_base)
            if not b.is_dir():
                continue
            d = b / "pm" / "prompts"
            d.mkdir(parents=True, exist_ok=True)
            fname = f"pm_prompt_{session_id or uuid.uuid4()}.txt"
            f = d / fname
            # Explicit UTF-8: prompt_bytes measures UTF-8, and a user-authored
            # prompt can contain non-ASCII.  The default (locale) encoding
            # raises UnicodeEncodeError under an ASCII locale, which would
            # crash the fallback that exists to deliver this prompt.
            f.write_text(prompt, encoding="utf-8")
            ref = Path(ref_base) / "pm" / "prompts" / fname
            _log.warning(
                "prompt is %d bytes, over the %d-byte argv limit; using "
                "file-backed bootstrap %s", prompt_bytes(prompt),
                PROMPT_ARG_LIMIT, ref)
            return _bootstrap_prompt(str(ref)), str(f)
        except OSError:
            continue
    try:
        fd, path = tempfile.mkstemp(prefix="pm_prompt_", suffix=".txt")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(prompt)
        _log.warning(
            "prompt is %d bytes, over the %d-byte argv limit; using "
            "file-backed bootstrap %s", prompt_bytes(prompt),
            PROMPT_ARG_LIMIT, path)
        return _bootstrap_prompt(path), path
    except OSError as e:
        raise PromptTooLargeError(prompt_bytes(prompt), PROMPT_ARG_LIMIT,
                                  "claude prompt") from e


def launch_claude(prompt: str, session_key: str, pm_root: Path,
                  cwd: str | None = None, resume: bool = True,
                  provider: str | None = None,
                  model: str | None = None,
                  effort: str | None = None,
                  session_type: str | None = None) -> int:
    """Run claude interactively with a prompt. Returns exit code.

    Attempts to resume a previous session if one exists for session_key.
    If no session exists, generates a new UUID and passes it via --session-id
    so we can resume later.

    Args:
        provider: Name of the LLM provider to use. See providers.py.
        model: Explicit model ID to pass via --model (overrides provider model).
        effort: Effort level to pass via --effort (low, medium, high).
    """
    import uuid

    # Check fake-claude config before requiring real claude on PATH.
    fc_config = _fake_claude_config_for_type(session_type)

    claude = find_claude()
    if not claude and fc_config is None:
        raise FileNotFoundError("claude CLI not found. Install it first.")

    # Resolve provider for env vars and model flag
    _, provider_model_flag, run_env = _resolve_provider(provider)
    # Explicit model param overrides provider's model_flag
    model_flag = model or provider_model_flag

    # Try to resume existing session, or generate new session ID
    session_id = None
    is_resuming = False
    if resume:
        session_id = load_session(pm_root, session_key)
        if session_id:
            is_resuming = True

    # If no existing session, generate a new UUID
    if not session_id:
        session_id = str(uuid.uuid4())
        # Save immediately so we have it even if claude crashes
        save_session(pm_root, session_key, session_id)
        _log.info("Generated new session_id=%s for key=%s", session_id, session_key)

    # Over-limit prompts are written to a file and delivered via a short
    # bootstrap argv entry (see _materialize_oversized_prompt); the file is
    # removed once the process exits.
    cleanup_paths: list[str] = []
    if fc_config is not None:
        cmd = [_FAKE_CLAUDE_BIN]
        cmd.extend(_fake_claude_args(fc_config, session_type=session_type))
    else:
        prepare_workspace(cwd or os.getcwd())
        cmd = [claude]
        if _skip_permissions():
            cmd.append("--dangerously-skip-permissions")
        if model_flag:
            cmd.extend(["--model", model_flag])
        if effort:
            cmd.extend(["--effort", effort])
        if is_resuming:
            cmd.extend(["--resume", session_id])
            # Don't pass prompt when resuming - Claude already has the conversation
        else:
            cmd.extend(["--session-id", session_id])
            argv_prompt, _tmp = _materialize_oversized_prompt(
                prompt, cwd=cwd, session_id=session_id)
            if _tmp:
                cleanup_paths.append(_tmp)
            cmd.append(argv_prompt)

    _log.info("launch_claude: cmd=%s (cwd=%s, session_key=%s, session_id=%s)",
              cmd[:6], cwd, session_key, session_id[:8] + "...")

    log_shell_command(cmd, prefix="claude")
    # Log the names (never the values) of the provider env vars passed to
    # the claude CLI: this is a debug log and API keys live here.
    _log.debug("Claude env vars: %s", sorted(
        k for k in (run_env or {})
        if k.startswith("ANTHROPIC_") or k.startswith("OPENAI_")))
    try:
        result = subprocess.run(cmd, cwd=cwd, env=run_env)
        returncode = result.returncode
        if returncode != 0:
            log_shell_command(cmd, prefix="claude", returncode=returncode)

        # If session failed (possibly invalid/corrupted), try with a fresh session.
        # Skip the retry when using fake-claude — it always exits 0.
        if returncode != 0 and resume and fc_config is None:
            _log.warning("Session failed (rc=%d), retrying with fresh session", returncode)
            session_id = str(uuid.uuid4())
            save_session(pm_root, session_key, session_id)
            cmd = [claude]
            if _skip_permissions():
                cmd.append("--dangerously-skip-permissions")
            if model_flag:
                cmd.extend(["--model", model_flag])
            if effort:
                cmd.extend(["--effort", effort])
            cmd.extend(["--session-id", session_id])
            argv_prompt, _tmp = _materialize_oversized_prompt(
                prompt, cwd=cwd, session_id=session_id)
            if _tmp:
                cleanup_paths.append(_tmp)
            cmd.append(argv_prompt)
            log_shell_command(cmd, prefix="claude")
            result = subprocess.run(cmd, cwd=cwd, env=run_env)
            returncode = result.returncode
            if returncode != 0:
                log_shell_command(cmd, prefix="claude", returncode=returncode)
    finally:
        for _p in cleanup_paths:
            try:
                os.unlink(_p)
            except OSError:
                pass

    return returncode


def launch_claude_print(prompt: str, cwd: str | None = None,
                        message: str = "Claude is working",
                        provider: str | None = None,
                        model: str | None = None,
                        effort: str | None = None,
                        allowed_tools: list[str] | None = None,
                        session_type: str | None = None) -> str:
    """Run claude -p (non-interactive print mode). Returns stdout.

    Shows a spinner on stderr while waiting for Claude to finish.

    Args:
        provider: Name of the LLM provider to use. See providers.py.
        model: Explicit model ID (overrides provider model_flag).
        effort: Effort level for the Claude CLI --effort flag.
        allowed_tools: Tool patterns to allow without permission prompts
            (passed via ``--allowedTools``).  Useful for granting file
            access in print mode without ``--dangerously-skip-permissions``.
    """
    import sys
    import threading
    import time
    import itertools

    # Check fake-claude config before requiring real claude on PATH.
    fc_config = _fake_claude_config_for_type(session_type)

    claude = find_claude()
    if not claude and fc_config is None:
        raise FileNotFoundError("claude CLI not found. Install it first.")

    # Resolve provider
    _, model_flag, run_env = _resolve_provider(provider)
    cleanup_path: str | None = None
    if fc_config is not None:
        cmd = [_FAKE_CLAUDE_BIN]
        cmd.extend(_fake_claude_args(fc_config, session_type=session_type))
    else:
        cmd = [claude]
        if _skip_permissions():
            cmd.append("--dangerously-skip-permissions")
        # Explicit model takes precedence over provider model_flag
        effective_model = model or model_flag
        if effective_model:
            cmd.extend(["--model", effective_model])
        if effort:
            cmd.extend(["--effort", effort])
        if allowed_tools:
            for tool in allowed_tools:
                cmd.extend(["--allowedTools", tool])
        argv_prompt, cleanup_path = _materialize_oversized_prompt(
            prompt, cwd=cwd)
        cmd.extend(["-p", argv_prompt])

    done = threading.Event()

    def _spinner():
        frames = itertools.cycle(["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"])
        while not done.is_set():
            frame = next(frames)
            sys.stderr.write(f"\r{frame} {message}...")
            sys.stderr.flush()
            done.wait(0.1)
        sys.stderr.write("\r" + " " * (len(message) + 6) + "\r")
        sys.stderr.flush()

    spinner_thread = threading.Thread(target=_spinner, daemon=True)
    spinner_thread.start()

    try:
        log_shell_command(cmd, prefix="claude-print")
        # Print mode is one-shot; close stdin so a no-verdict fake-claude
        # (e.g. under "_all" mode) hits EOF in _hold_open instead of blocking
        # forever on inherited stdin.  Real `claude -p` gets its prompt via
        # argument, so it never needs stdin either.
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            env=run_env,
            stdin=subprocess.DEVNULL,
        )
        if result.returncode != 0:
            log_shell_command(cmd, prefix="claude-print", returncode=result.returncode)
    finally:
        done.set()
        spinner_thread.join()
        if cleanup_path:
            try:
                os.unlink(cleanup_path)
            except OSError:
                pass

    return result.stdout


def _claude_project_dir(cwd: str) -> Path:
    """Compute Claude's project directory for a given working directory.

    Claude Code stores transcripts in ~/.claude/projects/{mangled-path}/
    where the path has '/' replaced with '-' and '.' replaced with '-'.
    """
    mangled = cwd.replace("/", "-").replace(".", "-")
    return Path.home() / ".claude" / "projects" / mangled


def build_claude_shell_cmd(
    prompt: str | None = None,
    session_id: str | None = None,
    resume: bool = False,
    session_tag: str | None = None,
    transcript: str | None = None,
    cwd: str | None = None,
    model: str | None = None,
    provider: str | None = None,
    effort: str | None = None,
    write_dir: str | None = None,
    session_type: str | None = None,
    env_out: dict[str, str] | None = None,
) -> str:
    """Build a claude shell command string with proper flags and logging.

    All code that launches claude as a shell string (tmux, execvp, etc.)
    should use this to ensure --dangerously-skip-permissions is respected
    and the command is logged.

    Args:
        prompt: The prompt to pass to claude (omitted when resuming)
        session_id: Session ID for --session-id or --resume
        resume: If True and session_id is set, use --resume instead of --session-id
        session_tag: Override session tag for skip-permissions check
        transcript: Path where the transcript symlink should be created.
            Requires ``cwd`` to compute Claude's native transcript location.
            Generates a UUID session ID and creates a symlink from
            ``transcript`` to Claude's native .jsonl file.
        cwd: Working directory for computing Claude's project dir (required
            when ``transcript`` is set).  Also used as the reference path
            for the prompt file in the generated command (see ``write_dir``).
        model: Model identifier to pass via ``--model`` flag.  When set,
            overrides Claude CLI's default model selection and any
            provider-resolved model.
        provider: Name of the LLM provider to use (e.g. "ollama", "vllm").
            Resolves via providers.yaml config. When set, injects the
            appropriate environment variables and --model flag for the
            provider. None uses the default resolution order.
        effort: Effort level to pass via ``--effort`` flag (low, medium, high).
        write_dir: Host filesystem path where the prompt file should be
            written.  Defaults to ``cwd``.  When ``cwd`` is a
            container-internal path (e.g. ``/workspace``) that does not
            exist on the host, pass the corresponding host path here so
            the file can be written.  The command will still reference the
            file via ``cwd`` (the path claude sees at runtime).
        env_out: Receives the provider environment variables.  They are
            **never** interpolated into the returned command: that string is
            logged (``log_shell_command``), stored as the tmux
            ``#{pane_start_command}`` and kept in the pane registry.  Callers
            must transport the values through the launched process's
            environment: ``tmux`` pane helpers write a private env file the
            pane sources (``env=`` argument), foreground launches use
            ``os.execvpe(..., env=...)``, and ``send_keys`` sources the same
            kind of file.
    """
    # When transcript is requested, generate a UUID and create a symlink
    if transcript and cwd:
        sid = str(uuid.uuid4())
        session_id = sid
        resume = False
        claude_dir = _claude_project_dir(cwd)
        target = claude_dir / f"{sid}.jsonl"
        transcript_path = Path(transcript)
        transcript_path.parent.mkdir(parents=True, exist_ok=True)
        # Preserve the outgoing attempt before the canonical path is
        # reused: a sign-off return re-runs impl/sign-off (and a review
        # loop restarts at iteration 1), so unlinking here used to erase
        # the pre-return session from the run archive (pr-9ee4d64).  Fall
        # back to the old unlink if archiving fails, so a launch is never
        # blocked by it.
        if transcript_path.is_symlink() or transcript_path.exists():
            if archive_transcript(transcript_path) is None:
                # Archiving failed (e.g. the archive dir is unwritable).
                # Prefer launching over stalling the workflow; the native
                # JSONL still exists under ~/.claude/projects.
                _log.warning("transcript: could not archive %s before "
                             "reuse", transcript_path)
            # Archiving normally moves the path away; clear any leftover
            # (an entry that already existed, or a failed removal) so the
            # symlink below cannot raise FileExistsError and kill the
            # launch.
            transcript_path.unlink(missing_ok=True)
        transcript_path.symlink_to(target)
        _log.info("transcript: symlink %s -> %s", transcript_path, target)

    # Resolve provider configuration.  Values stay out of the command string
    # (see ``env_out``); the caller transports them via the process env.
    provider_env, model_flag, _ = _resolve_provider(provider)
    if provider_env:
        if env_out is not None:
            env_out.update(provider_env)
        else:
            _log.warning(
                "provider %r needs env vars (%s) but the caller did not pass "
                "env_out; they will not reach the launched process",
                provider or "<default>", ", ".join(sorted(provider_env)))

    from pm_core.paths import skip_permissions_enabled, fake_claude_config_for_type
    fc_config = fake_claude_config_for_type(session_type, session_tag)
    if fc_config is not None:
        # Thread the session_id (generated above for transcript=, or passed
        # by the caller) so the fake writes the JSONL transcript + hook event
        # the verdict poller reads.  None for interactive panes that aren't
        # polled — the fake then just writes to stdout.
        fake_args = _fake_claude_args(fc_config, session_id=session_id,
                                      session_type=session_type,
                                      session_tag=session_tag)
        cmd = shlex.quote(_FAKE_CLAUDE_BIN) + " " + " ".join(shlex.quote(a) for a in fake_args)
        log_shell_command(cmd, prefix="claude")
        return cmd
    else:
        # Host launches establish workspace trust here, at the one boundary
        # every workflow role goes through.  Container launches pass the
        # host path as ``write_dir`` and a container-internal ``cwd``; their
        # trust is seeded into the container's config copy at creation
        # (container.create_container).
        cd_prefix = ""
        if cwd and (write_dir is None
                    or os.path.realpath(write_dir) == os.path.realpath(cwd)):
            prepare_workspace(cwd)
            # Run Claude in the directory that was just bootstrapped, not
            # wherever the pane happens to start (a tmux split without -c
            # starts in the *caller's* cwd — the review pane once launched
            # in the TUI's pm/ dir and sat at the trust prompt there).
            if os.path.isdir(cwd):
                cd_prefix = f"cd {shlex.quote(cwd)} && "
        skip = " --dangerously-skip-permissions" if skip_permissions_enabled(session_tag) else ""
        cmd = f"{cd_prefix}claude{skip}"

    # Explicit model param overrides provider's model_flag
    effective_model = model or model_flag
    if effective_model:
        cmd += f" --model {shlex.quote(effective_model)}"

    if effort:
        cmd += f" --effort {shlex.quote(effort)}"

    if session_id:
        if resume:
            cmd += f" --resume {session_id}"
        else:
            cmd += f" --session-id {session_id}"

    if prompt and not resume:
        # Write the prompt to a file and use "$(cat file)" to avoid tmux
        # command-length limits (~16 KB) with large prompts.  Stored in a
        # ``pm/prompts/`` subdir so the host workdir root stays clean — the
        # cleanup ``rm -f`` at the end of the shell pipeline doesn't always
        # run (claude killed by container teardown skips trailing commands),
        # so leftovers accumulate.
        _host_dir = Path(write_dir) if write_dir else (Path(cwd) if cwd else None)
        _prompt_written = False
        if _host_dir:
            try:
                if _host_dir.is_dir():
                    _prompts_subdir = _host_dir / "pm" / "prompts"
                    _prompts_subdir.mkdir(parents=True, exist_ok=True)
                    _fname = f"pm_prompt_{session_id or uuid.uuid4()}.txt"
                    # Explicit UTF-8 — see _materialize_oversized_prompt: the
                    # prompt is measured in UTF-8 bytes and may be non-ASCII,
                    # so the locale default must not decide its encoding.
                    (_prompts_subdir / _fname).write_text(prompt,
                                                          encoding="utf-8")
                    _ref_base = Path(cwd) if cwd else _host_dir
                    _prompt_ref = _ref_base / "pm" / "prompts" / _fname
                    # Delete the temp file after claude reads it.  The
                    # semicolon ensures cleanup runs whether claude succeeds
                    # or fails.
                    if _prompt_is_oversized(prompt):
                        # "$(cat file)" still expands to one oversized argv
                        # entry, so it does NOT avoid E2BIG.  Pass a short
                        # bootstrap that points claude at the full prompt
                        # file instead — every instruction is preserved.
                        bootstrap = _bootstrap_prompt(str(_prompt_ref))
                        cmd += (f' {shlex.quote(bootstrap)}; '
                                f'rm -f {shlex.quote(str(_prompt_ref))}')
                        _log.warning(
                            "prompt is %d bytes, over the %d-byte argv limit; "
                            "using file-backed bootstrap %s",
                            prompt_bytes(prompt), PROMPT_ARG_LIMIT, _prompt_ref)
                    else:
                        cmd += f' "$(cat {_prompt_ref})"; rm -f {shlex.quote(str(_prompt_ref))}'
                    _prompt_written = True
            except Exception:
                pass
        if not _prompt_written:
            if _prompt_is_oversized(prompt):
                # No writable location for file-backed delivery: fail with a
                # clear error rather than letting execve raise a raw E2BIG.
                raise PromptTooLargeError(prompt_bytes(prompt),
                                          PROMPT_ARG_LIMIT, "claude prompt")
            escaped = prompt.replace("'", "'\\''")
            cmd += f" '{escaped}'"

    log_shell_command(cmd, prefix="claude")
    return cmd


def session_id_from_transcript(transcript_path: str | Path) -> str | None:
    """Return the Claude session_id associated with a transcript symlink.

    ``build_claude_shell_cmd(transcript=...)`` writes a symlink pointing at
    ``~/.claude/projects/<mangled>/<session-id>.jsonl``.  This helper lets
    callers recover the session_id without threading it through subprocess
    boundaries.
    """
    p = Path(transcript_path)
    target: Path = p
    try:
        if p.is_symlink():
            target = Path(os.readlink(p))
        elif p.exists():
            target = p
        # else: fall through and parse the path literally — callers
        # (QA verification/planner panes) may pass a path that Claude
        # has not yet opened.
    except OSError:
        return None
    return _session_id_of_path(target)


def transcript_path_for(cwd: str, session_id: str) -> Path:
    """Return Claude's native transcript path for a cwd + session_id.

    Lets callers pass a concrete JSONL path to hook-driven pollers when
    they generated the session_id themselves (no symlink) rather than
    letting ``build_claude_shell_cmd(transcript=...)`` create one.
    """
    return _claude_project_dir(cwd) / f"{session_id}.jsonl"


# Immutable per-attempt archive subdirectory of a run's transcript dir.
# Canonical names (``impl-<pr>.jsonl``, ``signoff-<pr>.jsonl``,
# ``review-<pr>-<loop>-i<N>.jsonl``, …) are reused by successive attempts;
# every superseded attempt is preserved here under a name keyed by its
# Claude session id so a sign-off return can never erase the run archive
# (pr-9ee4d64).  The subdirectory keeps every existing ``iterdir()`` scan
# of the run dir from mistaking an archive for the current transcript.
TRANSCRIPT_ARCHIVE_DIR = "archive"


def _session_id_of_path(target: Path) -> str | None:
    """Session id encoded in a native transcript file name, if any."""
    name = target.name
    if name.endswith(".jsonl"):
        name = name[:-6]
    if len(name) == 36 and name.count("-") == 4:
        return name
    return None


def transcript_archive_dir(transcript_path: str | Path) -> Path:
    """The archive directory beside *transcript_path* (a transcript file)."""
    return Path(transcript_path).parent / TRANSCRIPT_ARCHIVE_DIR


def _transcript_stem(transcript_path: Path) -> str:
    """The transcript's name without its ``.jsonl`` suffix."""
    name = transcript_path.name
    return name[:-len(".jsonl")] if name.endswith(".jsonl") else name


def _archive_name(transcript_path: Path, sid: str | None,
                  frozen: Path | None = None) -> str:
    """Archive file name for a transcript (``<stem>.<key>.jsonl``).

    Symlinks are keyed by the Claude session id of their target, so the
    same session always maps to the same immutable entry.  A finalized
    regular file has no recoverable session id; key it on its identity
    (mtime + size) instead.
    """
    stem = _transcript_stem(transcript_path)
    if sid:
        return f"{stem}.{sid}.jsonl"
    try:
        st = frozen.stat() if frozen is not None else None
        key = f"{st.st_mtime_ns}-{st.st_size}" if st else uuid.uuid4().hex[:12]
    except OSError:
        key = uuid.uuid4().hex[:12]
    return f"{stem}.{key}.jsonl"


def _absolute_link_target(p: Path, raw: str) -> Path:
    """Resolve a symlink's stored target against the link's directory."""
    target = Path(raw)
    return target if target.is_absolute() else p.parent / target


def _find_identical_archive(adir: Path, p: Path) -> Path | None:
    """An existing archive entry that is a copy of the frozen file *p*.

    ``finalize_transcript`` writes a session-id archive copy and freezes
    the canonical path with the same metadata (``copy2``).  When that
    frozen canonical is later replaced, this keeps the replacement from
    adding a second archive entry for the same session.

    Only entries for the same stem are considered: a different step's
    transcript must never be mistaken for a copy of this one (the caller
    drops *p* when a match is found).
    """
    stem = _transcript_stem(p)
    try:
        st = p.stat()
        entries = list(adir.glob(f"{stem}.*.jsonl"))
    except OSError:
        return None
    for cand in entries:
        try:
            cst = cand.stat()
        except OSError:
            continue
        if cst.st_size == st.st_size and cst.st_mtime_ns == st.st_mtime_ns:
            return cand
    return None


def _move_into_archive(p: Path, dest: Path, raw: str | None) -> bool:
    """Create *dest* without clobbering an existing entry, then drop *p*.

    ``raw`` is the symlink target when *p* is a symlink; ``None`` means a
    regular file (hard-linked so the move is cheap, copied when the
    filesystem refuses links).  Creation is no-clobber: an existing
    archive entry is never overwritten.
    """
    try:
        if raw is not None:
            os.symlink(raw, dest)
        else:
            try:
                os.link(p, dest)
            except FileExistsError:
                raise
            except OSError:
                # Filesystem without hard links; copy instead.  The copy
                # is created exclusively: a concurrent archive of the same
                # session must not be overwritten with different bytes.  A
                # partial copy must not stay behind either — archive
                # entries are immutable, so a truncated one would block
                # every later attempt.
                created = False
                try:
                    with open(p, "rb") as src:
                        with open(dest, "xb") as out:
                            created = True
                            shutil.copyfileobj(src, out)
                except FileExistsError:
                    raise
                except OSError:
                    # Remove only a partial copy of our own making; a
                    # concurrent creator's entry is never touched.
                    if created:
                        try:
                            dest.unlink()
                        except OSError:
                            pass
                    raise
                try:
                    shutil.copystat(p, dest)
                except OSError as e:
                    # Metadata only; the content copy is what matters, so
                    # a failure here must not discard the archive entry.
                    _log.debug("transcript: copystat %s failed: %s", dest, e)
    except FileExistsError:
        return False
    except OSError as e:
        _log.warning("transcript: archiving %s -> %s failed: %s", p, dest, e)
        return False
    try:
        p.unlink()
    except OSError as e:
        # Both copies exist; losing the canonical link is harmless.
        _log.debug("transcript: archived %s but could not remove it: %s", p, e)
    return True


def archive_transcript(transcript_path: str | Path) -> Path | None:
    """Preserve the transcript at *transcript_path* in the run archive.

    Moves the outgoing attempt (symlink or finalized copy) to
    ``<dir>/archive/<stem>.<session-id>.jsonl`` before a new attempt
    reuses the canonical path.  Returns the archive path, or ``None`` when
    there is nothing to archive.  Archive entries are immutable: an
    existing entry is never overwritten, and an already-archived session's
    redundant canonical link is dropped without touching its data.
    """
    p = Path(transcript_path)
    try:
        is_link = p.is_symlink()
    except OSError:
        return None
    if not is_link and not p.exists():
        return None
    raw: str | None = None
    sid: str | None = None
    if is_link:
        try:
            stored = os.readlink(p)
        except OSError:
            stored = None
        if stored:
            # Store an absolute target so the archive link resolves from
            # the archive subdirectory too.
            raw = str(_absolute_link_target(p, stored))
            sid = _session_id_of_path(Path(raw))
    adir = transcript_archive_dir(p)
    try:
        adir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        _log.warning("transcript: cannot create archive dir %s: %s", adir, e)
        return None
    if not is_link:
        # A frozen canonical is normally a copy of a session already
        # archived at finalize time; keep one entry per session.
        identical = _find_identical_archive(adir, p)
        if identical is not None:
            try:
                p.unlink()
            except OSError:
                pass
            _log.info("transcript: %s already archived at %s", p, identical)
            return identical
    dest = adir / _archive_name(p, sid, None if is_link else p)
    if dest.is_symlink() or dest.exists():
        if is_link and raw and dest.is_symlink():
            try:
                if os.readlink(dest) == raw:
                    # Same session already archived; drop the duplicate link.
                    p.unlink()
            except OSError:
                pass
        _log.info("transcript: %s already archived at %s", p, dest)
        return dest
    if not _move_into_archive(p, dest, raw if is_link else None):
        return None
    _log.info("transcript: archived %s -> %s", p, dest)
    return dest


def _freeze_archive_copy(p: Path, raw: str, target: Path,
                         sid: str | None) -> Path | None:
    """Write (or refresh) the immutable archive copy for the session at *p*.

    A symlink already placed by :func:`archive_transcript` is frozen in
    place; an existing regular archive entry is left untouched.
    """
    if p.parent.name == TRANSCRIPT_ARCHIVE_DIR:
        # *p* is itself the archive entry; finalize freezes it in place.
        return p
    adir = transcript_archive_dir(p)
    dest = adir / _archive_name(p, sid, target)
    try:
        adir.mkdir(parents=True, exist_ok=True)
        if dest.is_symlink():
            try:
                same = os.readlink(dest) == raw
            except OSError:
                same = False
            if not same:
                # Another session's immutable entry; never touch it.
                return dest
        elif dest.exists():
            return dest
        # Write beside the entry and replace atomically, so a crash can
        # never leave the archive without a copy of a session.  The name
        # is unique per call: two threads of one process can finalize
        # concurrently (a bulk sweep and a loop's completion), and a
        # shared temp path would let one replace the other's partial copy.
        tmp = adir / f".{dest.name}.tmp-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        try:
            shutil.copy2(target, tmp)
            os.replace(tmp, dest)
        finally:
            try:
                tmp.unlink()
            except OSError:
                pass
        return dest
    except OSError as e:
        _log.warning("transcript: archive copy of %s failed: %s", p, e)
        return None


_PANE_SESSION_RE = re.compile(
    r"--(?:session-id|resume)[ =]"
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})")
# shlex.quote() output: a bare word, or a single-quoted one (spaces).
_PANE_CD_RE = re.compile(r'^"?cd ((?:\'[^\']*\'|[^\s\'])+) && ')
_PANE_CONTAINER_RE = re.compile(r"\b(?:podman|docker) exec\b")


def pane_transcript_path(pane_id: str, workdir: str | None) -> Path | None:
    """Claude's native transcript for the session a pane was launched with.

    A restarted TUI can't find the transcript symlinks an earlier TUI made
    (they live in that TUI's run dir), so it would never track, idle-detect
    or trust-watch those panes again.  The session id is in the pane's own
    start command (``--session-id``/``--resume``), and the directory Claude
    runs in is the ``cd`` prefix of a host launch, ``/workspace`` for a
    container exec, else *workdir*.  Returns None when no session id shows.
    """
    from pm_core import tmux as tmux_mod
    from pm_core.container import _CONTAINER_WORKDIR
    cmd = tmux_mod.pane_start_command(pane_id)
    m = _PANE_SESSION_RE.search(cmd)
    if not m:
        return None
    cd = _PANE_CD_RE.match(cmd)
    if cd:
        try:
            cwd = shlex.split(cd.group(1))[0]
        except (ValueError, IndexError):
            return None
    elif _PANE_CONTAINER_RE.search(cmd):
        cwd = _CONTAINER_WORKDIR
    elif workdir:
        cwd = workdir
    else:
        return None
    return transcript_path_for(cwd, m.group(1))


def finalize_transcript(transcript_path: Path,
                        *, session_id: str | None = None) -> bool:
    """Freeze a transcript symlink into a copy of its target file.

    Called when a session finishes so the transcript is self-contained
    and survives Claude session pruning.  Returns True when this call
    froze the path.

    Ownership-checked (pr-9ee4d64): a superseded attempt's callback must
    never freeze, replace, unlink or redirect the live transcript of the
    attempt that now owns the path.

    * ``session_id`` (when given) must match the link target's session;
      otherwise the link belongs to another attempt and is left live.
    * The link is re-read immediately before replacement; a link
      redirected in between is left untouched.

    An immutable archive copy keyed by session id is written first, so
    the session survives even if the canonical path is later reused.
    """
    transcript_path = Path(transcript_path)
    if not transcript_path.is_symlink():
        return False
    try:
        raw = os.readlink(transcript_path)
    except OSError:
        return False
    target = _absolute_link_target(transcript_path, raw)
    sid = _session_id_of_path(target)
    if session_id and sid and sid != session_id:
        _log.info("transcript: %s now belongs to session %s (not %s); "
                  "leaving it live", transcript_path, sid, session_id)
        return False
    if not target.exists():
        _log.debug("transcript: target %s does not exist, skipping finalize", target)
        return False
    _freeze_archive_copy(transcript_path, str(target), target, sid)
    try:
        if os.readlink(transcript_path) != raw:
            _log.info("transcript: %s was redirected during finalize; "
                      "leaving the new link live", transcript_path)
            return False
    except OSError:
        return False
    # Copy beside the path and replace atomically: readers see either the
    # live symlink or the complete frozen copy, never a missing path or a
    # truncated one, and a failed copy leaves the link live.
    tmp = transcript_path.with_name(
        f".{transcript_path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex[:8]}")
    try:
        shutil.copy2(target, tmp)
        os.replace(tmp, transcript_path)
    except OSError as e:
        _log.warning("transcript: finalize %s failed: %s", transcript_path, e)
        return False
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass
    _log.info("transcript: finalized %s (copied from %s)", transcript_path, target)
    return True


def finalize_transcript_dir(directory: str | Path, *,
                            skip: Callable[[str], bool] | None = None) -> int:
    """Finalize every transcript symlink in *directory* and its archive.

    Returns the number of links frozen.  Archives are included so the
    per-attempt sessions kept by :func:`archive_transcript` also survive
    Claude transcript pruning.

    *skip* is a predicate on a file name: a transcript whose session may
    still be writing (a running loop or an existing step window) must be
    left live, otherwise its collector polls a frozen copy and never sees
    the verdict appended later (pr-9ee4d64).  Archive entries are never
    skipped — they are immutable snapshots of superseded attempts.
    """
    d = Path(directory)
    if not d.is_dir():
        return 0

    def _links_in(directory: Path) -> list[Path]:
        try:
            return [p for p in directory.iterdir()
                    if p.is_symlink() and p.suffix == ".jsonl"]
        except OSError:
            return []

    links = [p for p in _links_in(d)
             if not (skip is not None and skip(p.name))]
    adir = d / TRANSCRIPT_ARCHIVE_DIR
    if adir.is_dir():
        links.extend(_links_in(adir))
    return sum(1 for p in links if finalize_transcript(p))


def launch_claude_in_tmux(pane_target: str, prompt: str, cwd: str | None = None,
                          session_type: str | None = None) -> None:
    """Send a claude command to a tmux pane.

    Pass *session_type* to let the fake-claude override apply (see
    ``build_claude_shell_cmd``).
    """
    from pm_core.tmux import send_keys
    env: dict[str, str] = {}
    cmd = build_claude_shell_cmd(prompt=prompt, cwd=cwd,
                                 session_type=session_type, env_out=env)
    if env:
        # send_keys types into an existing shell, which has no pane-env
        # channel, so the values are handed over in a 0600 file that the
        # command sources and removes before claude starts.  sh -c so the
        # POSIX prefix also works when the pane's shell is fish.
        prefix, path = write_env_file(env)
        try:
            send_keys(pane_target, f"sh -c {shlex.quote(prefix + cmd)}")
        except Exception:
            try:
                os.unlink(path)
            except OSError:
                pass
            raise
    else:
        send_keys(pane_target, cmd)


def launch_bridge_in_tmux(prompt: str | None, cwd: str, session_name: str) -> str:
    """Launch a bridge in a tmux pane. Returns the socket path.

    The prompt is handed to the bridge as a shell argument, so it is one argv
    entry like every other prompt this module launches: an over-limit one
    would make the pane fail with a raw "Argument list too long" (E2BIG)
    before the bridge starts — the same failure ``build_claude_shell_cmd``
    guards against.  Above ``PROMPT_ARG_LIMIT`` the complete prompt is written
    to a file and passed with ``--prompt-file``, which the bridge reads (and
    removes) for its first turn, so every instruction is preserved.
    """
    import uuid
    from pm_core.tmux import split_pane_background

    socket_path = f"/tmp/pm-bridge-{uuid.uuid4().hex[:12]}.sock"
    bridge_cmd = f"python3 -m pm_core.bridge {socket_path} --cwd '{cwd}'"
    if prompt:
        # The bridge reads the prompt file itself, so only its path matters
        # here (the returned bootstrap text is for claude-as-argv launches).
        _bootstrap, prompt_file = _materialize_oversized_prompt(prompt, cwd=cwd)
        if prompt_file:
            bridge_cmd += f" --prompt-file {shlex.quote(prompt_file)}"
        else:
            escaped = prompt.replace("'", "'\\''")
            bridge_cmd += f" --prompt '{escaped}'"

    split_pane_background(session_name, "v", bridge_cmd)
    return socket_path


def launch_claude_print_background(prompt: str, cwd: str | None = None,
                                    callback=None,
                                    provider: str | None = None,
                                    session_type: str | None = None) -> None:
    """Run claude -p in a background thread. Calls callback(stdout, stderr, returncode) when done.

    Args:
        provider: Name of the LLM provider to use. See providers.py.
        session_type: Session type for fake-claude override selection.
    """
    import threading

    # Resolve provider and fake config outside the thread (caller's thread context)
    _, model_flag, run_env = _resolve_provider(provider)
    fc_config = _fake_claude_config_for_type(session_type)

    def _run():
        cleanup_path = None
        try:
            if fc_config is not None:
                cmd = [_FAKE_CLAUDE_BIN]
                cmd.extend(_fake_claude_args(fc_config, session_type=session_type))
            else:
                claude = find_claude()
                if not claude:
                    if callback:
                        callback("", "claude CLI not found", 1)
                    return
                cmd = [claude]
                if _skip_permissions():
                    cmd.append("--dangerously-skip-permissions")
                if model_flag:
                    cmd.extend(["--model", model_flag])
                argv_prompt, cleanup_path = _materialize_oversized_prompt(
                    prompt, cwd=cwd)
                cmd.extend(["-p", argv_prompt])
            log_shell_command(cmd, prefix="claude-print")
            # Print mode is one-shot; close stdin so a no-verdict fake-claude
            # (e.g. under "_all" mode) hits EOF in _hold_open instead of blocking
            # forever on inherited stdin.  Real `claude -p` gets its prompt via
            # argument, so it never needs stdin either.
            result = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                env=run_env,
                stdin=subprocess.DEVNULL,
            )
            if result.returncode != 0:
                log_shell_command(cmd, prefix="claude-print", returncode=result.returncode)
            if callback:
                callback(result.stdout, result.stderr, result.returncode)
        finally:
            if cleanup_path:
                try:
                    os.unlink(cleanup_path)
                except OSError:
                    pass

    t = threading.Thread(target=_run, daemon=True)
    t.start()
