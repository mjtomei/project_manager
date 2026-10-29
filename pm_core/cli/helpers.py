"""Shared helpers for the pm CLI package.

Contains utility classes and functions used across multiple CLI submodules:
HelpGroup, state management, PR ID resolution, TUI refresh, and session helpers.
"""

import os
import shutil
import signal
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import click

from pm_core import tui_pidfile
from pm_core import store, git_ops
from pm_core.paths import configure_logger
from pm_core import tmux as tmux_mod
from pm_core import pane_layout
from pm_core import pane_registry

_log = configure_logger("pm.cli")


# Tokens at which record wrapping prefers to break a too-wide line, in
# priority order.  Each token marks a natural visual boundary in pm's
# record-style CLI output.  The leading space is stripped on continuation
# so the tail starts cleanly with the token itself.
_RECORD_BREAK_TOKENS = (" <- ", " (", " [")


def _cell_aware_fill(
    text: str, width: int, *,
    initial_indent: str = "", subsequent_indent: str = "",
) -> str:
    """Wrap ``text`` to visual ``width`` based on ``rich.cells.cell_len``.

    Same shape as ``textwrap.fill`` but counts cells, not codepoints.  Wide
    characters (emoji, CJK) consume the right number of columns.  Splits
    on whitespace only; never splits a word.  Long words that exceed the
    width go on their own line and overflow rather than being broken.
    """
    from rich.cells import cell_len
    words = text.split()
    if not words:
        return initial_indent
    lines = [initial_indent + words[0]]
    for word in words[1:]:
        candidate = lines[-1] + " " + word
        if cell_len(candidate) <= width:
            lines[-1] = candidate
        else:
            lines.append(subsequent_indent + word)
    return "\n".join(lines)


def _wrap_record_to_width(line: str, width: int, indent: str) -> str:
    """Return ``line`` possibly with embedded newlines so it fits in ``width``.

    Prefers breaking at the first record boundary token (``" <- "``,
    ``" ("``, ``" ["``).  If the indented tail still overflows, falls
    back to whitespace wrapping on the tail.  If no boundary token gives
    a head that fits, falls back to whitespace wrapping on the full line.

    Uses ``rich.cells.cell_len`` for visual width so wide characters
    (emoji status icons like ⏳ 👀 🧪 ✅, CJK, etc.) are counted as the
    two columns they actually occupy in a terminal.  ``len()`` would
    miscount them and let visually-overflowing lines slip through.
    """
    from rich.cells import cell_len
    if cell_len(line) <= width:
        return line
    for tok in _RECORD_BREAK_TOKENS:
        idx = line.find(tok)
        if idx <= 0:
            continue
        head = line[:idx]
        # Require the head (everything up to the leading space) to fit.
        if cell_len(head) > width:
            continue
        tail = line[idx + 1:]  # drop leading space, keep token onward
        indented_tail = indent + tail
        if cell_len(indented_tail) <= width:
            return head + "\n" + indented_tail
        return head + "\n" + _cell_aware_fill(
            tail, width,
            initial_indent=indent, subsequent_indent=indent,
        )
    # No break token gave a fitting head — fall back to whitespace wrapping
    # on the full line.  Preserve the line's own leading whitespace as the
    # initial indent so the first output line starts in the same column as
    # the original (e.g. ``"  ⏳ pr-..."`` keeps its two-space gutter).
    stripped = line.lstrip()
    leading = line[:len(line) - len(stripped)]
    return _cell_aware_fill(
        stripped, width,
        initial_indent=leading, subsequent_indent=indent,
    )


def echo_record(line: str, *, indent: str = "      ") -> None:
    """Echo one record-style line, wrapping at terminal width on a TTY.

    When stdout is *not* a TTY (e.g. piped into ``grep`` / ``jq``), the
    line is echoed as-is so consumers keep one-record-per-line semantics.
    Use ``emit_paged`` for listing commands that should also auto-page.
    """
    if not sys.stdout.isatty():
        click.echo(line)
        return
    width = shutil.get_terminal_size((80, 24)).columns
    click.echo(_wrap_record_to_width(line, width, indent))


def emit_paged(lines, *, indent: str = "      ") -> None:
    """Emit a sequence of record-style lines, auto-paging on a TTY.

    Mirrors the ``git log`` / ``man`` / ``journalctl`` pattern: when
    stdout is a TTY, collect all output, wrap each line at the terminal
    width (with the same record-boundary preferences as ``echo_record``),
    and pipe through ``$PAGER``.  ``less -FRX`` (the typical default)
    auto-quits when the output fits on one screen, so short listings
    don't feel paged at all.

    When stdout is piped (``grep`` / ``jq`` / a file), each line is
    emitted as-is, one per record, with no wrapping.
    """
    if not sys.stdout.isatty():
        for line in lines:
            click.echo(line)
        return
    width = shutil.get_terminal_size((80, 24)).columns
    wrapped = "\n".join(_wrap_record_to_width(line, width, indent) for line in lines)
    click.echo_via_pager(wrapped)


# Module-level state set by the cli() group callback via set_project_override()
_project_override: Path | None = None

# Shared Click settings: make -h and --help both work everywhere
CONTEXT_SETTINGS = dict(help_option_names=["-h", "--help"])


def set_project_override(path: Path | None) -> None:
    """Set the project directory override (called by the cli group callback)."""
    global _project_override
    _project_override = path


class HelpGroup(click.Group):
    """Click Group that treats 'help' as an alias for --help everywhere,
    and 'l'/'ls' as aliases for 'list' everywhere.

    Applied to the top-level group and auto-inherited by all child groups
    via ``group_class = type`` (Click uses ``type(self)`` as default cls).

    Handles two cases:
    - ``pm pr help`` — 'help' as the command name on a group
    - ``pm qa show help`` — 'help' as an arg to a leaf command
    """

    group_class = type  # auto-propagate HelpGroup to child groups

    def resolve_command(self, ctx, args):
        if args and args[0] == "help":
            # If there's a real 'help' command registered, let it run
            if super().get_command(ctx, "help") is not None:
                return super().resolve_command(ctx, args)
            # Otherwise replace 'help' with '--help'
            args = ["--help"] + args[1:]
        # Alias l/ls to list when the group has a list subcommand
        if args and args[0] in ("l", "ls") and super().get_command(ctx, "list") is not None:
            args = ["list"] + args[1:]
        cmd_name, cmd, remaining = super().resolve_command(ctx, args)
        # Also handle 'help' as first arg to a leaf command:
        # e.g. 'pm qa show help' → 'pm qa show --help'
        if (remaining and remaining[0] == "help"
                and cmd is not None and not isinstance(cmd, click.MultiCommand)):
            remaining = ["--help"] + remaining[1:]
        return cmd_name, cmd, remaining


def _normalize_repo_url(url: str) -> str:
    """Normalize git remote URL for comparison.

    git@github.com:org/repo.git -> github.com/org/repo
    https://github.com/org/repo.git -> github.com/org/repo
    """
    url = url.strip().rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]
    # SSH format: git@host:path
    if ":" in url and "@" in url.split(":")[0]:
        _, rest = url.split(":", 1)
        host = url.split("@")[1].split(":")[0]
        return f"{host}/{rest}"
    # HTTPS format
    for prefix in ("https://", "http://"):
        if url.startswith(prefix):
            return url[len(prefix):]
    return url


def _verify_pm_repo_matches_cwd(pm_root: Path) -> None:
    """Warn if the PM repo targets a different repo than the current git repo."""
    cwd = Path.cwd()
    if not git_ops.is_git_repo(cwd):
        return
    cwd_remote = git_ops.run_git("remote", "get-url", "origin", cwd=cwd, check=False)
    if cwd_remote.returncode != 0 or not cwd_remote.stdout.strip():
        return
    try:
        data = store.load(pm_root)
    except Exception:
        return
    pm_target = data.get("project", {}).get("repo", "")
    if not pm_target:
        return
    # If pm_target is a local path, check if cwd is that path
    pm_target_path = Path(pm_target)
    if pm_target_path.is_absolute() and pm_target_path.exists():
        try:
            if cwd.resolve() == pm_target_path.resolve():
                return
        except OSError:
            pass
    if _normalize_repo_url(cwd_remote.stdout.strip()) != _normalize_repo_url(pm_target):
        click.echo(
            f"Warning: PM repo targets {pm_target}\n"
            f"         but you're in a repo with remote {cwd_remote.stdout.strip()}\n",
            err=True,
        )


def state_root() -> Path:
    """Get the project root containing project.yaml."""
    if _project_override:
        _verify_pm_repo_matches_cwd(_project_override)
        return _project_override
    return store.find_project_root()


def _pr_id_sort_key(pr_id: str) -> tuple[int, str]:
    """Sort key for PR IDs. Numeric pr-NNN sorts by number, hash IDs sort after."""
    # pr-001 → (1, ""), pr-a3f2b1c → (0, "a3f2b1c")
    parts = pr_id.split("-", 1)
    if len(parts) == 2:
        try:
            return (int(parts[1]), "")
        except ValueError:
            return (0, parts[1])
    return (0, pr_id)


def _pr_display_id(pr: dict) -> str:
    """Display ID for a PR: prefer GitHub #N, fall back to local pr-NNN."""
    gh = pr.get("gh_pr_number")
    return f"#{gh}" if gh else pr["id"]


PR_STATUS_ICONS = {
    "pending": "⏳",
    "in_progress": "🔨",
    "in_review": "👀",
    "qa": "🧪",
    "sign_off": "✔️",
    "merged": "✅",
    "closed": "🚫",
    "blocked": "🚫",
}


def format_pr_line(p: dict, active_pr: str | None = None,
                   with_timestamp: bool = False) -> str:
    """Format a single PR list line.

    Shared between the `pm pr list` CLI and the home-window pr-list
    provider so both render PRs identically.
    """
    icon = PR_STATUS_ICONS.get(p.get("status", "pending"), "?")
    # For a sign_off PR, append the latest recorded router verdict icon; a
    # PR sign-off sent back shows the return verdict's icon.
    verdict_str = ""
    from pm_core.signoff import signoff_verdict_icon, display_signoff_verdict
    v_icon = signoff_verdict_icon(display_signoff_verdict(p))
    if v_icon:
        verdict_str = f" {v_icon}"
    deps = p.get("depends_on") or []
    dep_str = f" <- [{', '.join(deps)}]" if deps else ""
    machine = p.get("agent_machine")
    machine_str = f" ({machine})" if machine else ""
    active_str = " *" if active_pr and p.get("id") == active_pr else ""
    ts_str = ""
    if with_timestamp:
        ts = p.get("updated_at") or p.get("created_at") or ""
        if ts:
            try:
                dt = datetime.fromisoformat(ts).astimezone()
                ts_str = f" [{dt.strftime('%Y-%m-%d %H:%M')}]"
            except ValueError:
                ts_str = f" [{ts}]"
    return (
        f"  {icon} {_pr_display_id(p)}: {p.get('title', '???')} "
        f"[{p.get('status', '?')}{verdict_str}]{dep_str}{machine_str}{active_str}{ts_str}"
    )


def kill_pr_windows(session: str, pr: dict) -> list[str]:
    """Kill tmux work, review, merge, and QA windows for a PR.

    Returns a list of window names that were killed.
    """
    from pm_core import tmux as tmux_mod
    from pm_core import home_window

    killed = []
    display_id = _pr_display_id(pr)
    qa_prefix = f"qa-{display_id}-s"
    _log.info("kill_pr_windows: pr=%s session=%s", display_id, session)

    # Park *every* grouped session whose active window is one of the
    # windows we're about to kill — covers cross-session kills where the
    # caller isn't on the doomed window but another grouped session is.
    # No recreate follows here, so parked clients stay on home.
    for win_name in (display_id, f"review-{display_id}", f"merge-{display_id}",
                     f"qa-{display_id}", f"signoff-{display_id}"):
        win = tmux_mod.find_window_by_name(session, win_name)
        if win:
            home_window.park_if_on(session, win["id"])
            tmux_mod.kill_window(session, win["id"])
            killed.append(win_name)

    # Also kill any QA scenario windows (qa-{display_id}-s1, etc.)
    for win in tmux_mod.list_windows(session):
        if win.get("name", "").startswith(qa_prefix):
            home_window.park_if_on(session, win["id"])
            tmux_mod.kill_window(session, win["id"])
            killed.append(win["name"])

    _log.info("kill_pr_windows: pr=%s killed=%s", display_id, killed)
    return killed


def _resolve_pr_id(data: dict, identifier: str) -> dict | None:
    """Resolve a PR by pm ID (pr-NNN), GitHub PR number (#N or bare integer).

    Accepts: 'pr-001', '42', '#42'.
    """
    # Exact pm ID match first
    pr = store.get_pr(data, identifier)
    if pr:
        return pr
    # Strip leading '#' for GitHub-style references
    cleaned = identifier.lstrip("#")
    try:
        num = int(cleaned)
    except ValueError:
        return None
    for pr in data.get("prs") or []:
        if pr.get("gh_pr_number") == num:
            return pr
    return None


def _require_pr(data: dict, pr_id: str) -> dict:
    """Get a PR by pm ID or GitHub PR number, or exit with an error.

    Accepts: 'pr-001', '42', '#42'.
    """
    pr_entry = _resolve_pr_id(data, pr_id)
    if pr_entry:
        return pr_entry
    prs = data.get("prs") or []
    click.echo(f"PR '{pr_id}' not found.", err=True)
    if prs:
        ids = []
        for p in prs:
            ids.append(_pr_display_id(p))
        click.echo(f"Available PRs: {', '.join(ids)}", err=True)
    raise SystemExit(1)


def _require_plan(data: dict, plan_id: str) -> dict:
    """Get a plan by ID or exit with an error listing available plans."""
    plan_entry = store.get_plan(data, plan_id)
    if plan_entry:
        return plan_entry
    plans = data.get("plans") or []
    click.echo(f"Plan {plan_id} not found.", err=True)
    if plans:
        click.echo(f"Available plans: {', '.join(p['id'] for p in plans)}", err=True)
    raise SystemExit(1)


def _auto_select_plan(data: dict, plan_id: str | None) -> str:
    """Auto-select a plan ID when not specified, or exit with an error."""
    if plan_id is not None:
        return plan_id
    plans = data.get("plans") or []
    if len(plans) == 1:
        return plans[0]["id"]
    if len(plans) == 0:
        click.echo("No plans. Create one with: pm plan add <name>", err=True)
        raise SystemExit(1)
    click.echo("Multiple plans. Specify one:", err=True)
    for p in plans:
        click.echo(f"  {p['id']}: {p['name']}", err=True)
    raise SystemExit(1)


def _make_pr_entry(
    pr_id: str,
    title: str,
    branch: str,
    *,
    plan: str | None = None,
    status: str = "pending",
    depends_on: list[str] | None = None,
    description: str = "",
    gh_pr: str | None = None,
    gh_pr_number: int | None = None,
) -> dict:
    """Create a standard PR entry dict with all required keys."""
    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": pr_id,
        "plan": plan,
        "title": title,
        "branch": branch,
        "status": status,
        "depends_on": depends_on or [],
        "description": description,
        "agent_machine": None,
        "gh_pr": gh_pr,
        "gh_pr_number": gh_pr_number,
        "created_at": now,
        "updated_at": now,
        "started_at": None,
        "reviewed_at": None,
        "merged_at": None,
        "notes": [],
    }


def _record_status_timestamp(pr_entry: dict, status: str | None = None) -> None:
    """Record timestamps on *pr_entry*.

    Always sets ``updated_at``.  When *status* is provided, also sets
    the status-specific timestamp:

    * ``started_at`` — set once on the first transition to ``in_progress``.
    * ``reviewed_at`` — updated each time the PR enters ``in_review``.
    * ``signed_off_at`` — updated each time the PR enters ``sign_off``.
    * ``merged_at`` — set when the PR is ``merged``.
    """
    now = datetime.now(timezone.utc).isoformat()
    pr_entry["updated_at"] = now
    if status == "in_progress" and not pr_entry.get("started_at"):
        pr_entry["started_at"] = now
    elif status == "in_review":
        pr_entry["reviewed_at"] = now
    elif status == "sign_off":
        pr_entry["signed_off_at"] = now
    elif status == "merged":
        pr_entry["merged_at"] = now


def _canonical_session(session: str) -> str:
    """Strip the tmux session-group suffix (``~N``) from ``session``.

    The TUI keys its pidfile and command-queue by its own session name
    with the group suffix removed (see TechTreeApp: ``split("~")[0]``).
    A user started via ``pm session`` is attached to the *grouped*
    session (e.g. ``pm-foo~1``), so callers that resolve the current
    session name (``_find_tui_pane`` -> ``get_session_name``) see the
    ``~N`` form.  Normalizing here keeps every consumer pointed at the
    same canonical file the TUI actually wrote, so external mutations
    (``pm pr edit`` -> SIGUSR1 reload) reach the TUI.
    """
    return pane_registry.base_session_name(session)


def _tui_pidfile_for_session(session: str) -> Path:
    """Path to the pidfile a TUI in ``session`` writes at startup."""
    return tui_pidfile.pidfile_path(_canonical_session(session))


def _tui_command_queue_for_session(session: str) -> Path:
    """Path to the per-session TUI command queue file."""
    return tui_pidfile.command_queue_path(_canonical_session(session))


@dataclass(frozen=True)
class TuiIpcResult:
    """Outcome of a TUI IPC attempt.

    ``reason`` is a stable machine-readable code; ``message`` is a
    user-facing explanation suitable for a popup.
    """

    ok: bool
    reason: str = ""
    message: str = ""


def _read_tui_owner(
    session: str,
) -> tuple[Path, str | None, tui_pidfile.TuiPidfile | None, str | None]:
    """Read *session*'s pidfile and report why its owner is unusable.

    Returns ``(pidfile, raw_text, descriptor, problem)``.  ``problem`` is
    ``None`` when the file names a live TUI; otherwise it is a short
    human-readable reason (``"no pidfile"``, ``"unreadable pidfile"``,
    ``"empty pidfile"``, or an identity problem from
    :func:`tui_pidfile.identity_problem`).  Nothing is modified here, so
    the result is safe to poll; callers that want the stale file removed
    go through :func:`_validate_tui_owner`.
    """
    path = _tui_pidfile_for_session(session)
    raw = tui_pidfile.read_pidfile_text(path)
    if raw is None:
        return path, None, None, (
            "unreadable pidfile" if path.exists() else "no pidfile")
    if raw == "":
        # A TUI creates the file with O_EXCL and writes its descriptor a
        # moment later (``claim_tui_pidfile`` waits out that window on
        # the writing side).  A *zero-length* file is therefore ambiguous,
        # not stale: callers must not delete it, or a second TUI could
        # claim the session while the first is still starting.  Whitespace-
        # only content is not that window (the claim writes a whole JSON
        # descriptor in one go), so it falls through as unreadable — which
        # matches the claim, where only ``""`` is retried.
        return path, raw, None, "empty pidfile"
    desc = tui_pidfile.parse_pidfile(raw)
    if desc is None:
        return path, raw, None, "unreadable pidfile"
    return path, raw, desc, tui_pidfile.identity_problem(desc)


def _validate_tui_owner(
    session: str,
) -> tuple[Path, str | None, tui_pidfile.TuiPidfile | None, TuiIpcResult | None]:
    """Resolve the pidfile for *session* and validate its owner.

    Returns ``(pidfile, raw_text, descriptor, error)``.  On success
    ``error`` is ``None`` and the other three describe a live TUI.  On
    failure ``error`` carries the result to hand back to the caller and
    any stale pidfile has already been removed — except for an empty file
    (``"starting"``), which is left for the TUI that is mid-claim.
    """
    pidfile, raw, desc, problem = _read_tui_owner(session)
    if problem == "no pidfile":
        return pidfile, None, None, TuiIpcResult(
            False, "no_pidfile",
            f"No TUI is running for session {session}.")
    if problem == "empty pidfile":
        # A TUI is mid-claim (see ``_read_tui_owner``).  Leave the file
        # alone so the starting TUI keeps its claim.  It can also be
        # *permanently* empty if a TUI was killed between its ``O_EXCL``
        # create and its first write, so name the restart fix as well —
        # "try again in a moment" alone would be a dead end.
        return pidfile, raw, None, TuiIpcResult(
            False, "starting",
            f"The TUI for session {session} has not finished starting up; "
            f"try again in a moment, otherwise restart the TUI (Ctrl+R).")
    if problem is not None:
        # Unreadable, dead, recycled, or not a TUI: stale.
        tui_pidfile.unlink_if_unchanged(pidfile, raw)
        if desc is None:
            message = (f"The TUI pidfile for session {session} is "
                       f"unreadable; restart the TUI.")
        elif problem == "process is not running":
            message = (f"The TUI for session {session} is not running; "
                       f"restart the TUI.")
        else:
            message = (f"The TUI for session {session} is not available "
                       f"({problem}); restart the TUI.")
        return pidfile, raw, desc, TuiIpcResult(
            False, "stale_pidfile", message)
    return pidfile, raw, desc, None


def tui_owner_problem(session: str) -> str | None:
    """Why *session* has no live TUI to signal, or ``None`` when it does.

    Identity-only: capabilities are deliberately not checked, so this is
    safe to poll while a TUI is starting up or restarting.  Unlike
    :func:`_validate_tui_owner` it never removes the pidfile.
    """
    return _read_tui_owner(session)[3]


def _missing_command_cap_result(
    session: str, desc: tui_pidfile.TuiPidfile,
) -> TuiIpcResult:
    """Explain that the live TUI cannot handle a queued command.

    Only the command-queue path needs a user-facing explanation: a reload
    is fire-and-forget (see ``trigger_tui_reload``), so a TUI without
    ``sigusr1`` is simply not signaled and the caller keeps its state.
    """
    if desc.legacy:
        return TuiIpcResult(
            False, "missing_capability",
            f"The TUI for session {session} predates the command-queue "
            f"feature; restart the TUI (Ctrl+R) to use it.")
    if not desc.caps:
        # Claimed but nothing published yet: mid-startup, or the handler
        # install failed and the capabilities were never advertised.
        return TuiIpcResult(
            False, "starting",
            f"The TUI for session {session} has not advertised its signal "
            f"handlers yet; if it is still starting up, try again in a "
            f"moment, otherwise restart the TUI (Ctrl+R).")
    return TuiIpcResult(
        False, "missing_capability",
        f"The TUI for session {session} does not advertise the "
        f"command-queue capability; restart the TUI (Ctrl+R) to use it.")


# ``_signal_tui`` reasons that mean the pidfile no longer names a live TUI,
# so the file should be removed.
_STALE_SIGNAL_REASONS = frozenset({
    "process is not running",
    "process is a zombie",
    "pid was reused by another process",
})


def _signal_tui(pid: int, sig: int, starttime: int | None = None) -> str | None:
    """Send *sig* to *pid*; return an error reason or ``None``.

    Where the kernel supports it, the signal goes out through a pidfd
    (``pidfd_send_signal``) rather than ``os.kill``: a bare kill resolves
    the PID *number* again, so a TUI that died between validation and the
    signal could hand the signal to a recycled PID.  A pidfd names one
    exact process, and sending to it fails with ``ESRCH`` once that
    process is gone.  *starttime* is re-checked after the pidfd is opened
    to close the same window on kernels without pidfd support.

    A target that exited but has not been reaped (a zombie) is reported
    as dead: both ``os.kill`` and ``pidfd_send_signal`` "succeed" against
    a zombie and then discard the signal, so returning ``None`` there
    would claim a delivery that can never be handled.
    """
    pidfd = None
    try:
        try:
            pidfd = tui_pidfile.open_pidfd(pid)
        except ProcessLookupError:
            return "process is not running"
        if starttime is not None:
            live_starttime = tui_pidfile.proc_starttime(pid)
            if live_starttime is not None and live_starttime != starttime:
                return "pid was reused by another process"
        if tui_pidfile.is_zombie(pid):
            return "process is a zombie"
        sender = getattr(signal, "pidfd_send_signal", None)
        if pidfd is not None and sender is not None:
            sender(pidfd, sig)
        else:
            os.kill(pid, sig)
        return None
    except ProcessLookupError:
        return "process is not running"
    except PermissionError:
        return "permission denied"
    except OSError as e:
        return str(e)
    finally:
        if pidfd is not None:
            try:
                os.close(pidfd)
            except OSError:
                pass


def trigger_tui_reload(session: str | None = None) -> bool:
    """Ask the TUI to reload state from disk via SIGUSR1.

    The TUI registers a SIGUSR1 handler at startup that runs
    ``action_reload`` (state-only reload, no GitHub sync). This is
    focus-independent — unlike send-keys, it can't be eaten by the
    command input or any other focused widget.

    Resolves the target TUI by session: if ``session`` is given it is
    used directly, otherwise we look up the TUI for the current
    cwd/tmux context (same logic as ``_find_tui_pane``).

    The pidfile is validated before signaling: a dead/reused PID, a
    non-TUI process, or a TUI that does not advertise ``sigusr1`` means
    no signal is sent.  Returns True only when SIGUSR1 was delivered.
    """
    try:
        if session is None:
            _, session = _find_tui_pane()
        # Kick the home window in lockstep with the TUI: every state
        # mutation that warrants a TUI reload also warrants pm-home
        # rechecking its rendered content. With hash-diff in the home
        # loop, a redundant kick is free.
        try:
            from pm_core.home_window import refresh_home
            refresh_home(session)
        except Exception:
            _log.debug("trigger_tui_reload: refresh_home failed",
                       exc_info=True)
        if not session:
            return False
        pidfile, raw, desc, error = _validate_tui_owner(session)
        if error is not None:
            _log.debug("trigger_tui_reload: %s", error.message)
            return False
        if tui_pidfile.CAP_RELOAD not in desc.caps:
            _log.info("TUI pid %d (session %s) does not advertise %s; "
                      "not signaling", desc.pid, session,
                      tui_pidfile.CAP_RELOAD)
            return False
        problem = _signal_tui(desc.pid, signal.SIGUSR1, desc.starttime)
        if problem in _STALE_SIGNAL_REASONS:
            _log.debug("TUI pid %d gone, removing stale pidfile", desc.pid)
            tui_pidfile.unlink_if_unchanged(pidfile, raw)
            return False
        if problem is not None:
            _log.debug("Cannot signal TUI pid %d: %s", desc.pid, problem)
            return False
        _log.debug("Sent SIGUSR1 to TUI pid %d (session %s)",
                   desc.pid, session)
        return True
    except Exception as e:
        _log.debug("Could not trigger TUI reload: %s", e)
        return False


# Backwards-compatible alias for existing callers.
trigger_tui_refresh = trigger_tui_reload


# Every character ``str.splitlines`` treats as a line boundary.  A queued
# command must be exactly *one* line: the TUI's drain splits the file with
# ``splitlines`` while ``_unqueue_line`` splits on ``b"\n"``, so a line
# break left inside a command would make the drain see several commands
# and the rollback see one — a submission reported as failed could then
# never be taken back and would be applied by a later drain.
_LINE_BREAKS = str.maketrans({
    c: " " for c in "\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029"
})


def _queue_line(cmd: str) -> str:
    """Normalize *cmd* into a single ``\\n``-terminated queue line."""
    return cmd.strip().translate(_LINE_BREAKS) + "\n"


def _unqueue_line(queue: Path, line: str) -> None:
    """Best-effort removal of the line this process just appended.

    Used when the signal after the append fails: the caller is told the
    command was *not* applied, so it must not sit in the queue waiting
    for some later drain to execute it.  Runs under the same ``flock``
    the appender and the TUI's drain use, and matches whole lines only:
    every other line is kept byte-for-byte, and a later command that
    merely *ends* with ours (``pm qa pr-1`` ends with ``qa pr-1``) is
    never touched.  The match is the last identical line, so a caller
    that appended after us cannot be the one removed unless its command
    is byte-identical to ours — two identical submissions are
    indistinguishable by content, so at most one copy is rolled back and
    the other stays queued for its own caller.
    """
    import fcntl

    target = line.rstrip("\n").encode("utf-8")
    try:
        with open(queue, "r+b") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                lines = f.read().split(b"\n")
                if lines and lines[-1] == b"":
                    lines.pop()  # trailing newline, not an empty command
                for i in range(len(lines) - 1, -1, -1):
                    if lines[i] == target:
                        del lines[i]
                        break
                else:
                    return  # already drained, or never written
                remainder = b"".join(entry + b"\n" for entry in lines)
                f.seek(0)
                f.write(remainder)
                f.flush()
                f.truncate(len(remainder))
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except OSError as e:
        _log.debug("Could not unqueue TUI command %r: %s", line, e)


def submit_tui_command(session: str, cmd: str) -> TuiIpcResult:
    """Queue *cmd* for the TUI and signal it, with a reason on failure.

    Validation happens before anything is written: a missing/stale
    pidfile, a PID that is dead, recycled, or not a pm TUI, or a TUI
    that does not advertise ``sigusr2`` all return ``ok=False`` with a
    user-facing message and leave the process untouched.  A stale
    pidfile is removed so the next caller starts clean.
    """
    import fcntl

    pidfile, raw, desc, error = _validate_tui_owner(session)
    if error is not None:
        return error
    if tui_pidfile.CAP_COMMAND not in desc.caps:
        return _missing_command_cap_result(session, desc)
    queue = _tui_command_queue_for_session(session)
    line = _queue_line(cmd)
    try:
        # Binary append: the bytes are then exactly ``_unqueue_line``'s
        # UTF-8 target (it compares bytes), and a caller whose locale is
        # not UTF-8 can neither garble the command nor defeat the
        # rollback below.
        #
        # *Unbuffered* append, for two reasons.  (1) The line must be on
        # disk while the flock is held: the TUI's drain reads and
        # truncates the queue under the same lock, so bytes still sitting
        # in Python's buffer at LOCK_UN would land in the file *after* a
        # drain truncated it — the command would be silently dropped and
        # the caller would spin on "queued…" forever with a perfectly
        # healthy TUI (so the spinner's owner check would never abort
        # it).  (2) A buffered writer cannot be rolled back: when a flush
        # fails CPython keeps the unwritten remainder in its buffer, so
        # ``truncate`` re-raises from its own flush and the partial line
        # survives (a later ``close`` would even re-append the
        # remainder).  With a raw file the rollback is a plain
        # ``ftruncate``.
        with open(queue, "ab", buffering=0) as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                # The rollback target must be the file's end *as of the
                # lock*, not as of ``open()``: another appender (or a
                # drain) can run in between, and append mode pins the
                # stream position at open time, so ``tell()`` would be
                # stale.  Truncating back to a stale offset would delete a
                # line another caller was told was queued (or, after a
                # drain shrank the file, extend it with NULs).  ``st_size``
                # under the flock is the authoritative end.
                start = os.fstat(f.fileno()).st_size
                view = memoryview(line.encode("utf-8"))
                try:
                    # A raw write may be short (ENOSPC, quota); finish the
                    # line if the kernel lets us, the same way
                    # ``tui_pidfile._write_all`` does for the descriptor.
                    while view:
                        written = f.write(view)
                        if not written:
                            raise OSError(f"short write to {queue}")
                        view = view[written:]
                except OSError:
                    # A failed (possibly partial) write can leave *part*
                    # of the line behind.  ``_unqueue_line`` matches whole
                    # lines only, so it could not take that back — cut the
                    # partial bytes off here, under the same lock, or a
                    # later drain would run a truncated command the caller
                    # was told was not applied.  Best effort: the write
                    # itself just failed, so this may fail too.
                    try:
                        f.truncate(start)
                    except OSError:
                        pass
                    raise
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except OSError as e:
        _log.debug("Could not append to TUI command queue %s: %s", queue, e)
        return TuiIpcResult(
            False, "queue_error",
            f"Could not write to the TUI command queue: {e}")
    problem = _signal_tui(desc.pid, signal.SIGUSR2, desc.starttime)
    if problem is not None:
        # The command is already queued but nothing will drain it now (or
        # not soon); take it back (best effort) so the failure we report
        # is the truth.
        _unqueue_line(queue, line)
        if problem in _STALE_SIGNAL_REASONS:
            _log.debug("TUI pid %d gone, removing stale pidfile", desc.pid)
            tui_pidfile.unlink_if_unchanged(pidfile, raw)
            return TuiIpcResult(
                False, "stale_pidfile",
                f"The TUI for session {session} is not running "
                f"(process disappeared); restart the TUI.")
        _log.debug("Cannot signal TUI pid %d: %s", desc.pid, problem)
        return TuiIpcResult(
            False, "signal_error",
            f"Could not signal the TUI for session {session} ({problem}).")
    _log.debug("Queued command %r and sent SIGUSR2 to TUI pid %d (%s)",
               cmd, desc.pid, session)
    return TuiIpcResult(True)


def trigger_tui_command(session: str, cmd: str) -> bool:
    """Submit ``cmd`` to the TUI's command bar via SIGUSR2 + queue file.

    Thin boolean wrapper around :func:`submit_tui_command`; callers that
    want the failure reason use that instead.

    The TUI registers a SIGUSR2 handler at startup that drains the
    per-session queue file and dispatches each line through the same
    code path as a typed-and-submitted command bar entry.  This is
    focus-independent — unlike send-keys, it can't be eaten by the
    command input or get its literal text dispatched as TUI key
    bindings while waiting for the Input widget to focus.

    Multiple callers can append in any order; appends use ``flock`` to
    serialize and a SIGUSR2 fires per call, so racing writes are
    drained in the same handler invocation or the next one.

    Returns True if the signal was sent, False otherwise.
    """
    return submit_tui_command(session, cmd).ok


def trigger_tui_restart() -> None:
    """Send Ctrl+R to the TUI pane to restart it.

    Used after pulling new code so the TUI picks up the latest version.
    Writes a merge-restart marker so the TUI can distinguish this from
    a user-initiated Ctrl+R and preserve auto-start state.

    The marker must not outlive a restart that never happened: it is
    only consumed by ``save_breadcrumb`` when the TUI actually restarts,
    so a leftover marker would make the *next* start (even a plain Ctrl+R
    days later) behave as a merge restart.  It is therefore written after
    a live pane is resolved and removed again if the send fails.
    """
    marker = None
    try:
        if not tmux_mod.has_tmux():
            return
        # Resolve a *live* pane: the registry keeps a dead ``tui`` entry
        # until the next heal_registry pass, and send-keys to it fails.
        tui_pane, session = _find_live_tui_pane()
        if not (tui_pane and session):
            _log.debug("trigger_tui_restart: no live TUI pane to restart")
            return
        # Scoped to the session whose TUI is being restarted: the marker is
        # a single shared file, so an unscoped one would let a concurrent
        # restart in another session consume it (and preserve its own state).
        marker = tui_pidfile.write_merge_restart_marker(session)
        _log.debug("Wrote merge-restart marker %s", marker)
        tmux_mod.send_keys_literal(tui_pane, "C-r")
        _log.debug("Sent restart to TUI pane %s in session %s", tui_pane, session)
    except Exception as e:
        if marker is not None:
            tui_pidfile.clear_merge_restart_marker(session)
        _log.debug("Could not trigger TUI restart: %s", e)


def trigger_tui_merge_lock(pr_display_id: str) -> None:
    """Write merge-lock marker and signal TUI to show overlay.

    Called before stashing pm/ files during merge so the TUI pauses
    reads/writes while the files are temporarily reverted.
    """
    try:
        from pm_core.paths import pm_home
        lock = pm_home() / "merge-lock"
        lock.write_text(pr_display_id)
        _log.debug("Wrote merge-lock marker for %s", pr_display_id)
        # Signal TUI to reload — it will see the lock and show overlay
        trigger_tui_reload()
    except Exception as e:
        _log.debug("Could not set merge lock: %s", e)


def trigger_tui_merge_unlock() -> None:
    """Remove merge-lock marker.

    The TUI's MergeLockScreen polls for this file and auto-dismisses
    when it disappears, then reloads state.
    """
    try:
        from pm_core.paths import pm_home
        lock = pm_home() / "merge-lock"
        lock.unlink(missing_ok=True)
        _log.debug("Removed merge-lock marker")
    except Exception as e:
        _log.debug("Could not remove merge lock: %s", e)


def _resolve_repo_dir(root: Path, data: dict) -> Path:
    """Determine the target repo directory from pm state.

    Used when a command needs to run tools (like ``gh``) against the
    target repo.  Returns the parent of an internal pm/ dir, otherwise
    falls back to the repo URL (if it's a local path) or cwd.
    """
    if store.is_internal_pm_dir(root):
        return root.parent
    repo_url = data.get("project", {}).get("repo", "")
    if repo_url and Path(repo_url).is_dir():
        return Path(repo_url)
    return Path.cwd()


def _gh_state_to_status(state: str, is_draft: bool) -> str:
    """Map a GitHub PR state string to a local pm status."""
    if state == "MERGED":
        return "merged"
    if state == "CLOSED":
        return "closed"
    if state == "OPEN":
        return "in_progress" if is_draft else "in_review"
    return "pending"


def _workdirs_dir(data: dict) -> Path:
    """Return the workdirs base path for this project.

    Uses <name>-<repo_id[:8]> to avoid collisions between projects
    with the same name. repo_id is the root commit hash of the target
    repo, cached in project.yaml on first pr start.
    """
    project = data.get("project", {})
    name = project.get("name", "unknown")
    repo_id = project.get("repo_id")
    from pm_core.paths import workdirs_base
    base = workdirs_base()
    if repo_id:
        return base / f"{name}-{repo_id[:8]}"
    return base / name


def _ensure_workdir(data: dict, pr_entry: dict, root: Path) -> str | None:
    """Ensure the PR's workdir exists locally, cloning if necessary.

    When a PR was started on a different machine the recorded workdir path
    won't exist.  This helper recreates it by cloning the repo and checking
    out the PR branch, mirroring the logic in ``pr_start``.

    Returns the workdir path (str) on success, or *None* on failure.
    Updates *pr_entry["workdir"]* and persists the change when a new
    clone is created.

    Provisioning is serialized per-PR with an exclusive file lock: two
    commands that both find the workdir missing (e.g. two ``pm pr signoff``
    racing) would otherwise both clone into the fixed ``.tmp-{pr_id}`` path and
    corrupt each other — one ``rmtree``/moves the dir out from under the other,
    crashing its git ops with a traceback.  The lock makes the loser wait, then
    adopt the winner's freshly-persisted workdir instead of re-cloning.
    """
    import fcntl

    workdir = pr_entry.get("workdir")
    if workdir and Path(workdir).exists():
        return workdir

    pr_id = pr_entry.get("id")
    project_dir = _workdirs_dir(data)
    project_dir.mkdir(parents=True, exist_ok=True)

    lock_path = project_dir / f".workdir-{pr_id}.lock"
    lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        # Double-checked: another caller may have created and persisted the
        # workdir while we waited for the lock.  Re-read the authoritative
        # on-disk record and adopt it if it now exists.
        try:
            fresh_pr = store.get_pr(store.load(root), pr_id)
            fresh_wd = (fresh_pr or {}).get("workdir")
        except Exception:
            fresh_wd = None
        if fresh_wd and Path(fresh_wd).exists():
            pr_entry["workdir"] = fresh_wd
            return fresh_wd
        return _clone_workdir(data, pr_entry, root)
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def _clone_workdir(data: dict, pr_entry: dict, root: Path) -> str | None:
    """Clone + check out a PR's workdir.  Caller holds the per-PR lock.

    Extracted from :func:`_ensure_workdir` so the actual clone/move/checkout
    runs under the exclusive provisioning lock.  Do not call directly — go
    through :func:`_ensure_workdir`, which serializes concurrent callers.
    """
    import shutil

    branch = pr_entry.get("branch")
    if not branch:
        _log.warning("Cannot ensure workdir: PR %s has no branch", pr_entry.get("id"))
        return None

    repo_url = data.get("project", {}).get("repo", "")
    base_branch = data.get("project", {}).get("base_branch", "master")
    pr_id = pr_entry["id"]

    project_dir = _workdirs_dir(data)
    project_dir.mkdir(parents=True, exist_ok=True)

    # Determine clone source: prefer a local repo dir for speed.
    repo_dir = _resolve_repo_dir(root, data)
    if repo_dir and repo_dir.is_dir() and git_ops.is_git_repo(repo_dir):
        clone_source = str(repo_dir)
    elif repo_url:
        clone_source = repo_url
    else:
        _log.warning("Cannot ensure workdir: no repo source for PR %s", pr_id)
        return None

    tmp_path = project_dir / f".tmp-{pr_id}"
    if tmp_path.exists():
        shutil.rmtree(tmp_path)

    click.echo(f"Workdir missing — cloning for {pr_id}...")
    try:
        git_ops.clone(clone_source, tmp_path, branch=base_branch)
    except Exception as exc:
        _log.warning("Failed to clone for PR %s: %s", pr_id, exc)
        click.echo(f"Failed to clone: {exc}", err=True)
        if tmp_path.exists():
            shutil.rmtree(tmp_path, ignore_errors=True)
        return None

    # Set up remote URLs when cloned from a local repo: fetch from GitHub
    # (so we can find PR branches from other machines, and so the container
    # push proxy accepts pushes), push to both local and GitHub.
    if clone_source == str(repo_dir) and repo_url:
        git_ops.configure_dual_remote(tmp_path, clone_source, repo_url)

    # Resolve repo_id if not cached yet
    _resolve_repo_id(data, tmp_path, root)

    # Compute final directory name (same convention as pr_start)
    base_hash = git_ops.run_git(
        "rev-parse", "--short=8", "HEAD", cwd=tmp_path, check=False
    ).stdout.strip()
    branch_slug = store.slugify(branch.replace("/", "-"))
    dir_name = f"{branch_slug}-{base_hash}" if base_hash else branch_slug
    final_project_dir = _workdirs_dir(data)
    final_project_dir.mkdir(parents=True, exist_ok=True)
    work_path = final_project_dir / dir_name

    if work_path.exists():
        shutil.rmtree(tmp_path)
    else:
        shutil.move(str(tmp_path), str(work_path))

    # Checkout the PR branch
    git_ops.checkout_branch(work_path, branch, create=True)

    # Update and persist the new workdir path atomically
    workdir_str = str(work_path)
    pr_entry["workdir"] = workdir_str

    def apply(fresh_data):
        for pr in fresh_data.get("prs") or []:
            if pr["id"] == pr_id:
                pr["workdir"] = workdir_str
                break

    store.locked_update(root, apply)
    click.echo(f"Workdir created at {work_path}")
    return workdir_str


def _resolve_repo_id(data: dict, workdir: Path, root: Path) -> None:
    """Resolve and cache the target repo's root commit hash."""
    if data.get("project", {}).get("repo_id"):
        return
    result = git_ops.run_git("rev-list", "--max-parents=0", "HEAD", cwd=workdir, check=False)
    lines = result.stdout.strip().splitlines() if result.returncode == 0 else []
    if lines:
        repo_id = lines[0]
        data["project"]["repo_id"] = repo_id

        def apply(d):
            d.setdefault("project", {})["repo_id"] = repo_id

        store.locked_update(root, apply)


def _infer_pr_id(data: dict, status_filter: tuple[str, ...] | None = None) -> str | None:
    """Try to infer a PR ID from context.

    1. If cwd matches a PR's workdir, use that PR.
    2. If there's an active PR (and it matches the status filter if given), use that.
    3. If exactly one PR matches the status filter, use that.
    """
    cwd = str(Path.cwd().resolve())
    prs = data.get("prs") or []

    # Check if cwd is inside a PR's workdir
    for pr in prs:
        wd = pr.get("workdir")
        if wd and cwd.startswith(str(Path(wd).resolve())):
            return pr["id"]

    # Check active PR
    active = data.get("project", {}).get("active_pr")
    if active:
        pr_entry = store.get_pr(data, active)
        if pr_entry:
            if status_filter is None or pr_entry.get("status") in status_filter:
                return active

    # Fall back to single-match on status
    if status_filter:
        matches = [p for p in prs if p.get("status") in status_filter]
        if len(matches) == 1:
            return matches[0]["id"]

    return None


# ---------------------------------------------------------------------------
# Session / TUI helpers used by multiple submodules
# ---------------------------------------------------------------------------

def _set_share_mode_env(share_global: bool, share_group: str | None) -> None:
    """Set PM_SHARE_MODE env var from CLI flags so get_session_tag mixes it into the hash."""
    if share_global:
        os.environ["PM_SHARE_MODE"] = "global"
    elif share_group:
        os.environ["PM_SHARE_MODE"] = f"group:{share_group}"
    else:
        os.environ.pop("PM_SHARE_MODE", None)


def _get_session_name_for_cwd() -> str:
    """Generate the expected pm session name for the current working directory.

    Computes the name from the git root so it's deterministic regardless
    of which tmux session the caller is in.  Used by ``pm session`` to
    create/attach sessions and by ``pm pr start`` to find the session.

    When the caller is already inside the target pm session (e.g. TUI
    subprocesses), the computed name may not match the actual session
    (workdir clones have a different git-root hash).  Use
    ``_get_current_pm_session()`` in those cases.
    """
    from pm_core.paths import get_session_tag
    tag = get_session_tag()
    if tag:
        return f"pm-{tag}"

    # Fallback if not in a git repo
    return f"pm-{Path.cwd().name}-00000000"


def _get_current_pm_session() -> str | None:
    """Return the base pm session name when running inside one.

    Reads the actual session from $TMUX_PANE and strips any grouped-session
    ~N suffix.  Returns None if not inside tmux or not in a pm- session.
    """
    if not tmux_mod.in_tmux():
        return None
    try:
        name = tmux_mod.get_session_name()
    except OSError:
        # tmux missing/unexecutable while $TMUX is set (a forwarded pane
        # environment, or a container without tmux): "not inside a pm
        # session" rather than a crash out of `pm session mobile` /
        # `--print-connect`, like every other probe in this module.
        return None
    # Shared definition of "grouped session base" (see
    # ``pane_registry.base_session_name``), like the other call sites.
    name = pane_registry.base_session_name(name)
    if name.startswith("pm-"):
        return name
    return None


def _get_pm_session() -> str | None:
    """Get the pm tmux session name if running inside one.

    Also selects the server that hosts the resolved session, because every
    pm session runs on its own private socket: a command run outside tmux
    (or from an unrelated tmux session) would otherwise address the default
    server and conclude that a live session is gone.  Inside a pm session
    the ambient ``PM_TMUX_SOCKET``/``$TMUX`` is already correct, so the
    extra lookup is skipped there.
    """
    if not tmux_mod.has_tmux():
        return None
    current = _get_current_pm_session()
    if current:
        return current
    session = _get_session_name_for_cwd()
    _select_session_socket(session)
    return session


def _use_tmux_socket(socket_path: str | None) -> None:
    """Point subsequent ``tmux_mod`` calls at *socket_path*.

    ``None`` means the user's default server, which is addressed by its
    explicit path: tmux follows ``$TMUX`` when no ``-S`` is given, and from
    inside a pm pane that names the session's private server instead.
    """
    if not socket_path:
        from pm_core.paths import default_socket_path
        socket_path = str(default_socket_path())
    os.environ["PM_TMUX_SOCKET"] = socket_path


def _select_session_socket(session_name: str) -> str | None:
    """Point ``PM_TMUX_SOCKET`` at the server hosting *session_name*.

    Prefers the session's dedicated private socket, falls back to the
    legacy default server.  Returns the selected socket path, or None when
    the session is on the default server or was not found (the ambient
    setting is left untouched in the latter case).
    """
    base = pane_registry.base_session_name(session_name)
    if not base.startswith("pm-"):
        return None
    sock, on_private = tmux_mod.find_session_server(base)
    if sock is None:
        return None
    # ``None`` selects the default server by its explicit path: clearing
    # the override is not enough, because tmux would then follow $TMUX and
    # reach the private server this process happens to run on.
    _use_tmux_socket(sock if on_private else None)
    return sock if on_private else None


def _iter_registry_tui_panes(session: str):
    """Yield the pane ids the registry records with ``role="tui"``."""
    data = pane_registry.load_registry(session)
    for _, pane in pane_registry._iter_all_panes(data):
        if pane.get("role") == "tui":
            pane_id = pane.get("id")
            if pane_id:
                yield pane_id


def _recorded_tui_pane(session: str) -> str | None:
    """Return the pane id the registry records for *session*'s TUI.

    No liveness check: callers that drive the pane must use
    ``_find_live_tui_pane``, and ``pm autostart`` needs the recorded pane
    to report a stale pidfile for the right session.
    """
    return next(_iter_registry_tui_panes(session), None)


def _registry_tui_pane(session: str) -> str | None:
    """Return the registered TUI pane for *session* if it is still alive.

    Used where the answer decides *which server* to address (the in-tmux,
    cwd and cross-server branches of ``_find_tui_pane``): a pane that no
    longer exists must not be attributed to the server being probed.
    """
    for pane_id in _iter_registry_tui_panes(session):
        try:
            if tmux_mod.pane_exists(pane_id):
                return pane_id
        except OSError:
            # tmux missing/unexecutable: no pane is live (same contract
            # as find_session_server's degrade).
            return None
    return None


def _find_tui_pane(session: str | None = None) -> tuple[str | None, str | None]:
    """Find the TUI pane in a pm session.

    Returns ``(pane_id, session_name)``, or ``(None, None)`` when no session
    can be identified at all.  With an explicit *session* the name is
    returned even when the session or its TUI pane is gone, and the pane id
    is whatever the registry records — history/frames commands key their
    files off the session, and ``pm autostart`` reports a stale pidfile
    from it.  Callers that *drive* the pane use ``_find_live_tui_pane``,
    which filters dead panes.

    The returned session name is always the *base* session: a grouped
    suffix (``pm-x~2``) is normalised away, because the registry, the
    pidfile and the history/frames files are all keyed by the base name.

    Every pm session has its own tmux server, so resolution also selects
    the server hosting the found session: subsequent ``tmux_mod`` calls in
    the caller target it via ``PM_TMUX_SOCKET``.

    If session is provided, uses that. Otherwise:
    - If in a pm- tmux session, uses current session
    - Otherwise, tries to find session matching current directory
    - Falls back to scanning pm servers for a live TUI pane; when one of the
      two branches above identified a session, only *that* session's server
      is scanned (see the note on ``identified`` below).
    """
    # The scan below re-points PM_TMUX_SOCKET at each server it probes, and
    # the cwd branch selects a server before that scan runs, so read the
    # value this process started with *first*: a failed lookup has to leave
    # the caller addressing the server it came in with.
    ambient_socket = os.environ.get("PM_TMUX_SOCKET")
    # If session specified, use it (and its server).  The recorded pane is
    # returned as-is: naming the session is this branch's job, and
    # liveness is `_find_live_tui_pane`'s.
    if session:
        base = pane_registry.base_session_name(session)
        _select_session_socket(base)
        return _recorded_tui_pane(base), base

    # The session one of the branches below actually identified, if any.
    # The fallback scan is scoped to it: pane ids are only unique per tmux
    # server and ``pm tui send`` delivers keys unscoped, so resolving to a
    # *different* pm session's live ``pm _tui`` pane would drive the wrong
    # TUI — the cross-session damage this whole change exists to prevent.
    identified: str | None = None

    # If in a pm session, use current
    if tmux_mod.in_tmux():
        try:
            current_session = tmux_mod.get_session_name()
        except OSError:
            # tmux missing/unexecutable while $TMUX is set (a forwarded
            # pane environment, or a container without tmux).  Discovery
            # degrades to the cwd/cross-server branches instead of
            # crashing, like every other probe in this scan.
            current_session = ""
        if current_session.startswith("pm-"):
            base = pane_registry.base_session_name(current_session)
            identified = base
            pane_id = _registry_tui_pane(base)
            if pane_id:
                return pane_id, base

    # Try to find session matching current directory first
    expected_session = _get_session_name_for_cwd()
    _select_session_socket(expected_session)
    try:
        session_running = tmux_mod.session_exists(expected_session)
    except OSError:
        # tmux missing/unexecutable: discovery degrades to "no session"
        # instead of crashing (same contract as find_session_server).
        session_running = False
    if session_running:
        # Inside a pm session the ambient one stays the fallback target
        # (that is the server the pre-isolation scan would have used);
        # otherwise the running cwd session is.
        identified = identified or expected_session
        pane_id = _registry_tui_pane(expected_session)
        if pane_id:
            return pane_id, expected_session

    # Fall back to scanning pm servers (private sockets + legacy default)
    # for a session with a live registered TUI pane.  Only the identified
    # session's own server is eligible when there is one; with no session
    # identified at all (a plain shell) every server is scanned, which is
    # what makes `pm tui view` work from outside a pm session.  The scan
    # re-points PM_TMUX_SOCKET at each server in turn; the value captured
    # on entry is restored below if nothing is found.
    servers = tmux_mod.list_pm_sessions()
    if identified is not None:
        servers = [info for info in servers if info["name"] == identified]
    for info in servers:
        _use_tmux_socket(info["socket"])
        pane_id = _registry_tui_pane(info["name"])
        if pane_id:
            return pane_id, info["name"]

    # Last resort: search tmux directly for a pane running 'pm _tui'.
    # This handles cases where the TUI pane was removed from the registry
    # (e.g. during heal testing) but is still alive in tmux.  Reuses
    # ``_live_panes_and_tuis`` — the same query ``_find_live_tui_pane``
    # filters — so "a pane running the TUI" has one definition, and a tmux
    # that cannot be run degrades to "nothing found" instead of raising.
    #
    # The pane must belong to the *row's* session, not merely to some pm
    # session on the same server: a server is not a session, and the
    # legacy default server hosts every pre-isolation pm session, so
    # accepting any pm- TUI pane here would hand back another session's
    # pane (and ``pm tui send`` delivers keys unscoped).
    for info in servers:
        _use_tmux_socket(info["socket"])
        _, live_tuis = _live_panes_and_tuis()
        for pane_id, tui_session in live_tuis:
            if pane_registry.base_session_name(tui_session) == info["name"]:
                return pane_id, info["name"]

    # Nothing found: undo the scan's env mutations so the caller keeps the
    # server it started with.
    if ambient_socket is None:
        os.environ.pop("PM_TMUX_SOCKET", None)
    else:
        os.environ["PM_TMUX_SOCKET"] = ambient_socket
    return None, None


def _live_panes_and_tuis() -> tuple[dict[str, str], list[tuple[str, str]]]:
    """Return ``(pane_sessions, live_tui_panes)`` from tmux in one query.

    ``pane_sessions`` maps every pane tmux currently knows about to the
    session that owns it; ``live_tui_panes`` is the ``(pane_id,
    session_name)`` pairs whose start command is ``pm _tui``.  Returns
    ``({}, [])`` when tmux cannot be queried (no server), so callers
    degrade to "no live TUI".

    The owning session is returned alongside the id because pane ids are
    only unique *within* one tmux server, and every pm session now has its
    own server: a pane id recorded for one session can name an unrelated
    pane on another, so a bare id is not proof that a recorded pane is
    still the TUI.
    """
    try:
        result = subprocess.run(
            tmux_mod._tmux_cmd(
                "list-panes", "-a",
                "-F", "#{pane_id} #{session_name} #{pane_start_command}"),
            capture_output=True, text=True,
        )
    except Exception:
        _log.debug("_live_panes_and_tuis: tmux query failed", exc_info=True)
        return {}, []
    if result.returncode != 0:
        return {}, []
    panes: dict[str, str] = {}
    tuis: list[tuple[str, str]] = []
    for line in result.stdout.splitlines():
        parts = line.split(None, 2)
        if not parts:
            continue
        if len(parts) >= 2:
            panes[parts[0]] = parts[1]
        if len(parts) >= 3 and "_tui" in parts[2]:
            tuis.append((parts[0], parts[1]))
    return panes, tuis


def _find_live_tui_pane(
        session: str | None = None) -> tuple[str | None, str | None]:
    """Find the TUI pane, ignoring registry entries whose pane is gone.

    ``_find_tui_pane`` resolves the *session* even when the recorded pane
    no longer exists — callers such as ``pm autostart`` use that to report
    a stale pidfile for the right session.  Commands that drive the pane
    (``pm tui view`` / ``pm tui send`` / ``pm tui restart``) must not
    target a dead pane: the pane registry keeps its ``role="tui"`` entry
    after the TUI exits until the next ``heal_registry`` pass, and
    capturing or sending to that pane yields an empty frame with exit 0
    (view) or a raw tmux error (send).

    Returns ``(pane_id, session)`` only when the pane is still alive in
    tmux *and belongs to that session*.  When the recorded pane is gone,
    falls back to a live ``pm _tui`` pane in the same session (never
    another session's), and otherwise returns ``(None, session)``.

    The session check matters because pane ids are only unique per tmux
    server: when the session cannot be found on any server (stale
    registry, wrong ``--session``), the liveness query still runs against
    whatever server this process is attached to, where the recorded id may
    name an unrelated pane of a different session.
    """
    pane_id, sess = _find_tui_pane(session)
    if not sess:
        # Only an unresolved *implicit* lookup gets here: with an explicit
        # session ``_find_tui_pane`` always returns the base name, even
        # when the registry has no ``tui`` entry (a hand-started TUI before
        # the first ``heal_registry`` pass) — the live-pane scan below is
        # what resolves that case.
        return None, None
    live_panes, live_tuis = _live_panes_and_tuis()
    base = pane_registry.base_session_name(sess)
    if (pane_id and pane_id in live_panes
            and pane_registry.base_session_name(live_panes[pane_id]) == base):
        return pane_id, sess
    for tui_id, tui_sess in live_tuis:
        if pane_registry.base_session_name(tui_sess) == base:
            return tui_id, sess
    return None, sess
