"""``pm rc`` — remote-control mobile voice document viewer/editor.

``pm rc start <path> [--port N]`` opens a new tmux window containing an
rc-driver Claude pane and starts a background FastAPI server that
serves a mobile-friendly viewer to any browser on the LAN.  Subcommands
(``select``, ``focus``, ``propose``, ``accept``, ``reject``, ``status``)
are issued by Claude in the rc-driver pane and hit the server over
loopback.

See ``pm/specs/pr-4702a11/impl.md`` for the full design.
"""

from __future__ import annotations

import json
import os
import shlex
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

import click

from pm_core import pane_registry, tmux as tmux_mod
from pm_core.cli import cli
from pm_core.cli.helpers import _get_current_pm_session


@cli.group("rc")
def rc_cmd():
    """Remote-control viewer/editor for voice-driven mobile review."""


# ---------------------------------------------------------------------------
# Registry helpers
# ---------------------------------------------------------------------------

def _save_rc_server(session: str, window: str, info: dict) -> None:
    """Record an rc-server's pid/port/host/path under a top-level key.

    We use a separate ``rc_servers`` dict (keyed by window id) instead of
    the per-window ``panes`` list because reconciliation
    (``_reconcile_registry``) drops entries whose IDs aren't live tmux
    panes — and the rc-server is a daemon process, not a pane.
    """
    def modifier(raw):
        data = pane_registry._prepare_registry_data(raw, session)
        servers = data.setdefault("rc_servers", {})
        servers[window] = info
        return data

    pane_registry.locked_read_modify_write(
        pane_registry.registry_path(session), modifier
    )


def _load_rc_server(session: str, window: str | None) -> dict | None:
    data = pane_registry.load_registry(session)
    servers = data.get("rc_servers") or {}
    if not servers:
        return None
    if window and window in servers:
        return servers[window]
    if len(servers) == 1:
        return next(iter(servers.values()))
    return None


def _drop_rc_server(session: str, window: str) -> dict | None:
    """Remove and return the rc-server entry for *window*."""
    removed: dict | None = None

    def modifier(raw):
        nonlocal removed
        data = pane_registry._prepare_registry_data(raw, session)
        servers = data.get("rc_servers") or {}
        if window in servers:
            removed = servers.pop(window)
            data["rc_servers"] = servers
            return data
        return None

    pane_registry.locked_read_modify_write(
        pane_registry.registry_path(session), modifier
    )
    return removed


# ---------------------------------------------------------------------------
# Network helpers
# ---------------------------------------------------------------------------

def _detect_lan_ip() -> str:
    """Best-effort LAN IP discovery via the UDP-connect trick."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def _port_in_use(host: str, port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind((host, port))
    except OSError:
        return True
    finally:
        s.close()
    return False


def _pick_free_port(host: str) -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind((host, 0))
    port = s.getsockname()[1]
    s.close()
    return port


# ---------------------------------------------------------------------------
# Subcommand HTTP plumbing
# ---------------------------------------------------------------------------

def _server_url() -> str:
    """Resolve the rc-server's loopback URL for the *current* pane.

    Errors out clearly when no rc-server is registered or when we can't
    determine which window we're in.
    """
    session = _get_current_pm_session()
    if session is None:
        click.echo("pm rc: must be run from inside a pm session", err=True)
        raise SystemExit(1)
    window = None
    pane = os.environ.get("TMUX_PANE")
    if pane:
        window = tmux_mod.pane_window_id(pane)
    info = _load_rc_server(session, window)
    if info is None:
        click.echo("pm rc: no rc-server registered for this window. "
                   "Run 'pm rc start <path>' first.", err=True)
        raise SystemExit(1)
    return f"http://127.0.0.1:{info['port']}"


def _http(method: str, path: str, body: dict | None = None) -> dict:
    url = _server_url() + path
    data = json.dumps(body).encode() if body is not None else None
    headers = {"content-type": "application/json"} if body is not None else {}
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read().decode())
            msg = payload.get("detail") or payload.get("error") or str(e)
        except Exception:
            msg = str(e)
        click.echo(f"pm rc: server error: {msg}", err=True)
        raise SystemExit(1)
    except urllib.error.URLError as e:
        click.echo(f"pm rc: cannot reach server: {e.reason}", err=True)
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# pm rc start
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are driving a remote-controlled document viewer for a user who is interacting
by voice from a separate device. The user can hear your text replies but is most
likely looking at the viewer (a phone or tablet browser), not your terminal output.

This session is managed by `pm` (Project Manager for Claude Code sessions). You
are running inside one tmux window of a pm session; other windows hold the pm
TUI, other PR sessions, etc. You don't need to interact with them — your job is
to drive the document viewer for this user. Useful pm context:
  - `pm help` lists pm commands; `pm status` shows the active project.
  - `pm rc ...` (below) is the only pm subtree you normally need here.
  - Don't run `pm pr start`, `pm plan add`, etc. from this pane — those spawn
    new Claude sessions and must come from the TUI. If you genuinely need to
    poke the TUI (rare), use `pm tui send <keys>` and `pm tui view`.

Tooling: you control the viewer via these CLI commands run in this pane:
  pm rc status              — print the doc path, current viewport (top/bottom
                              line), the user's selection, and any pending
                              proposal. Read this BEFORE choosing a focus line.
  pm rc select <s> [e]      — select line s (or range s..e). Auto-focuses near
                              the selection.
  pm rc focus <top_line>    — set the viewport so <top_line> is at the top.
  pm rc propose             — read replacement text from stdin and stage it as
                              a proposal for the current selection.
  pm rc accept              — write the proposal back to the file.
  pm rc reject              — discard the proposal (selection stays).

Rules:
  1. Always run `pm rc status` before choosing a focus line — viewport height
     varies with device, orientation, and font scaling.
  2. After every selection / proposal / accept / reject, set focus so both the
     selection AND the proposal stay visible together with as much surrounding
     context as fits.
  3. When they don't all fit, prioritize keeping the proposal in view. The user
     has already seen the selection; the proposal is what they're judging.
  4. Narrate non-trivial moves ("scrolling down to the goals section") so the
     user isn't surprised when the page jumps.
  5. The user can scroll by touch as a fallback. After their next turn, re-read
     `pm rc status` to see where they actually are before assuming.
"""


@rc_cmd.command("start")
@click.argument("path", type=click.Path(exists=True, dir_okay=False, resolve_path=True))
@click.option("--port", type=int, default=None,
              help="Bind the viewer server to this port. Errors if in use.")
def start_cmd(path: str, port: int | None):
    """Open a new tmux window with an rc-driver Claude pane and start the
    LAN viewer server for PATH. Must be run from inside a pm session."""
    session = _get_current_pm_session()
    if session is None:
        click.echo("pm rc start: must be run from inside a pm session", err=True)
        raise SystemExit(1)

    file_path = Path(path).resolve()
    host_bind = "0.0.0.0"
    lan_ip = _detect_lan_ip()

    if port is None:
        port = _pick_free_port("0.0.0.0")
    else:
        if _port_in_use(host_bind, port):
            click.echo(f"pm rc start: port {port} is already in use", err=True)
            raise SystemExit(1)

    click.echo("pm rc start: WARNING — LAN-only, no auth. "
               "Anyone on this network can read and edit the file.",
               err=True)

    # Launch server as detached daemon
    log_dir = Path.home() / ".pm" / "rc-logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"server-{port}.log"
    log_fh = open(log_path, "ab")
    server_proc = subprocess.Popen(
        [sys.executable, "-m", "pm_core.rc.server",
         "--path", str(file_path),
         "--port", str(port),
         "--host", host_bind],
        stdin=subprocess.DEVNULL,
        stdout=log_fh,
        stderr=log_fh,
        start_new_session=True,
        close_fds=True,
    )
    log_fh.close()

    # Open a new tmux window with a Claude session in rc-driver mode
    prompt_dir = Path.home() / ".pm" / "rc-prompts"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    prompt_file = prompt_dir / f"system-{port}.md"
    prompt_file.write_text(_SYSTEM_PROMPT)

    from pm_core.paths import skip_permissions_enabled
    skip = " --dangerously-skip-permissions" if skip_permissions_enabled(
        session.removeprefix("pm-")) else ""
    claude_cmd = (
        f"claude{skip} --append-system-prompt "
        f"\"$(cat {shlex.quote(str(prompt_file))})\""
    )

    window_name = f"rc-{file_path.name}"
    pane_id = tmux_mod.new_window_get_pane(
        session, window_name, claude_cmd, str(file_path.parent), switch=True,
    )

    if pane_id is None:
        click.echo("pm rc start: failed to create tmux window", err=True)
        try:
            server_proc.terminate()
        except OSError:
            pass
        raise SystemExit(1)

    window_id = tmux_mod.pane_window_id(pane_id) or ""

    # Register the Claude pane normally so it participates in layout
    pane_registry.register_pane(session, window_id, pane_id, "rc-driver", "claude")
    # Stash server info under rc_servers so reconciliation can't drop it
    _save_rc_server(session, window_id, {
        "pid": server_proc.pid,
        "port": port,
        "host": host_bind,
        "lan_ip": lan_ip,
        "path": str(file_path),
        "log": str(log_path),
    })

    click.echo(f"Viewer: http://{lan_ip}:{port}/")
    click.echo(f"Path:   {file_path}")
    click.echo(f"Log:    {log_path}")


# ---------------------------------------------------------------------------
# Driver subcommands
# ---------------------------------------------------------------------------

@rc_cmd.command("select")
@click.argument("start", type=int)
@click.argument("end", type=int, required=False)
def select_cmd(start: int, end: int | None):
    """Select line START (or range START..END)."""
    if end is None:
        end = start
    _http("POST", "/api/select", {"start": start, "end": end})
    click.echo(f"selected {start}..{end}")


@rc_cmd.command("focus")
@click.argument("top_line", type=int)
def focus_cmd(top_line: int):
    """Set the viewer's top visible line to TOP_LINE."""
    r = _http("POST", "/api/focus", {"top_line": top_line})
    vp = r.get("viewport") or {}
    click.echo(f"viewport top={vp.get('top')} bottom={vp.get('bottom')}")


@rc_cmd.command("propose")
def propose_cmd():
    """Read replacement text from stdin and stage as proposal."""
    text = sys.stdin.read()
    _http("POST", "/api/propose", {"text": text})
    click.echo(f"proposed {len(text)} chars")


@rc_cmd.command("accept")
def accept_cmd():
    """Apply the pending proposal to the file."""
    r = _http("POST", "/api/accept", {})
    click.echo(f"accepted (version={r.get('version')})")


@rc_cmd.command("reject")
def reject_cmd():
    """Discard the pending proposal (keeps selection)."""
    _http("POST", "/api/reject", {})
    click.echo("rejected")


@rc_cmd.command("status")
def status_cmd():
    """Print doc path, viewport, selection, and proposal preview."""
    s = _http("GET", "/api/doc", None)
    click.echo(f"path: {s.get('path')}")
    vp = s.get("viewport") or {}
    if vp:
        click.echo(f"viewport: top={vp.get('top')} bottom={vp.get('bottom')}")
    else:
        click.echo("viewport: (none reported yet)")
    sel = s.get("selection")
    if sel:
        click.echo(f"selection: {sel['start']}..{sel['end']}")
    else:
        click.echo("selection: (none)")
    prop = s.get("proposal")
    if prop:
        preview = prop["text"][:80].replace("\n", "⏎")
        suffix = "…" if len(prop["text"]) > 80 else ""
        click.echo(f'proposal: "{preview}{suffix}"')
    else:
        click.echo("proposal: (none)")
    click.echo(f"version: {s.get('version')}")
    text = s.get("text") or ""
    total = text.count("\n") + (0 if text.endswith("\n") else 1) if text else 0
    click.echo(f"lines: {total}")
