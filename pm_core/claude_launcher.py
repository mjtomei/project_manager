"""Launch claude CLI sessions."""

import json
import logging
import os
import random
import shlex
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pm_core.paths import configure_logger, log_shell_command
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

    if fc_config is not None:
        cmd = [_FAKE_CLAUDE_BIN]
        cmd.extend(_fake_claude_args(fc_config, session_type=session_type))
    else:
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
            cmd.append(prompt)

    _log.info("launch_claude: cmd=%s (cwd=%s, session_key=%s, session_id=%s)",
              cmd[:6], cwd, session_key, session_id[:8] + "...")

    log_shell_command(cmd, prefix="claude")
    # Log the environment variables passed to the claude CLI (filtered for ANTHROPIC_/OPENAI_ prefixes)
    _log.debug("Claude env vars: %s", {k: v for k, v in (run_env or {}).items() if k.startswith('ANTHROPIC_') or k.startswith('OPENAI_')})
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
        cmd.append(prompt)
        log_shell_command(cmd, prefix="claude")
        result = subprocess.run(cmd, cwd=cwd, env=run_env)
        returncode = result.returncode
        if returncode != 0:
            log_shell_command(cmd, prefix="claude", returncode=returncode)

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
        cmd.extend(["-p", prompt])

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
        # Remove stale symlink if present
        if transcript_path.is_symlink() or transcript_path.exists():
            transcript_path.unlink()
        transcript_path.symlink_to(target)
        _log.info("transcript: symlink %s -> %s", transcript_path, target)

    # Resolve provider configuration
    provider_env, model_flag, _ = _resolve_provider(provider)

    # Build env prefix for non-claude providers
    env_prefix = ""
    if provider_env:
        parts = [f"{k}={shlex.quote(v)}" for k, v in provider_env.items()]
        env_prefix = " ".join(parts) + " "

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
        cmd = env_prefix + shlex.quote(_FAKE_CLAUDE_BIN) + " " + " ".join(shlex.quote(a) for a in fake_args)
        log_shell_command(cmd, prefix="claude")
        return cmd
    else:
        skip = " --dangerously-skip-permissions" if skip_permissions_enabled(session_tag) else ""
        cmd = f"{env_prefix}claude{skip}"

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
                    (_prompts_subdir / _fname).write_text(prompt)
                    _ref_base = Path(cwd) if cwd else _host_dir
                    _prompt_ref = _ref_base / "pm" / "prompts" / _fname
                    # Delete the temp file after claude reads it via $(cat ...).
                    # The semicolon ensures cleanup runs whether claude succeeds or fails.
                    cmd += f' "$(cat {_prompt_ref})"; rm -f {shlex.quote(str(_prompt_ref))}'
                    _prompt_written = True
            except Exception:
                pass
        if not _prompt_written:
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
    name = target.name
    if name.endswith(".jsonl"):
        name = name[:-6]
    # Basic sanity check — session ids are UUIDs (32 hex + 4 dashes = 36 chars)
    if len(name) == 36 and name.count("-") == 4:
        return name
    return None


def transcript_path_for(cwd: str, session_id: str) -> Path:
    """Return Claude's native transcript path for a cwd + session_id.

    Lets callers pass a concrete JSONL path to hook-driven pollers when
    they generated the session_id themselves (no symlink) rather than
    letting ``build_claude_shell_cmd(transcript=...)`` create one.
    """
    return _claude_project_dir(cwd) / f"{session_id}.jsonl"


def finalize_transcript(transcript_path: Path) -> None:
    """Replace a transcript symlink with a copy of the target file.

    Called when a session finishes so the transcript is self-contained
    and survives Claude session pruning.  No-op if the path is not a
    symlink or the target doesn't exist.
    """
    if not transcript_path.is_symlink():
        return
    target = transcript_path.resolve()
    if target.exists():
        transcript_path.unlink()
        shutil.copy2(target, transcript_path)
        _log.info("transcript: finalized %s (copied from %s)", transcript_path, target)
    else:
        _log.debug("transcript: target %s does not exist, skipping finalize", target)


def launch_claude_in_tmux(pane_target: str, prompt: str, cwd: str | None = None,
                          session_type: str | None = None) -> None:
    """Send a claude command to a tmux pane.

    Pass *session_type* to let the fake-claude override apply (see
    ``build_claude_shell_cmd``).
    """
    from pm_core.tmux import send_keys
    cmd = build_claude_shell_cmd(prompt=prompt, cwd=cwd, session_type=session_type)
    send_keys(pane_target, cmd)


def launch_bridge_in_tmux(prompt: str | None, cwd: str, session_name: str) -> str:
    """Launch a bridge in a tmux pane. Returns the socket path."""
    import uuid
    from pm_core.tmux import split_pane_background

    socket_path = f"/tmp/pm-bridge-{uuid.uuid4().hex[:12]}.sock"
    bridge_cmd = f"python3 -m pm_core.bridge {socket_path} --cwd '{cwd}'"
    if prompt:
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
            cmd.extend(["-p", prompt])
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

    t = threading.Thread(target=_run, daemon=True)
    t.start()
