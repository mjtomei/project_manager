"""CLI command: pm fake-github — out-of-process GitHub stand-in for testing.

Sibling of ``pm fake-claude``. Installs a per-session fake GitHub backend so
that a freshly-spawned ``pm pr ...`` subprocess (or TUI pane) is served by the
fake instead of the real ``gh`` CLI / GitHub API. The transport gate lives in
``gh_ops.run_gh``, which consults ``paths.fake_github_active()``.

The fake's state lives at ``~/.pm/sessions/<tag>/fake-github/`` (a
``state.json`` PR registry plus a real ``remote.git/`` backing repo).
"""

import json

import click

from pm_core.cli import cli


@cli.group("fake-github")
def fake_github() -> None:
    """Scriptable GitHub stand-in for integration testing.

    \b
    Subcommands:
      config  Manage the per-session fake-github state that redirects pm's
              github backend to the fake (set / show / clear).
    """


@fake_github.group("config")
def config() -> None:
    """Manage the per-session fake-github state.

    The state lives at ``~/.pm/sessions/<tag>/fake-github/``. When present, pm's
    github-backend `gh` calls for that session run against the fake instead of
    real GitHub; when absent, the real `gh` CLI is used.
    """


def _resolve_tag(tag: str | None) -> str:
    """Return *tag* or the current session's tag, erroring if neither resolves."""
    from pm_core.paths import get_session_tag
    resolved = tag or get_session_tag()
    if not resolved:
        raise click.ClickException(
            "No session tag: run this inside a pm session or pass --tag.")
    return resolved


@config.command("set")
@click.argument("config_json", required=False)
@click.option("--file", "-f", "file_path",
              type=click.Path(exists=True, dir_okay=False),
              help="Read the seed JSON from this file instead of an argument.")
@click.option("--tag", "-t", default=None,
              help="Session tag to write for (default: current session).")
def config_set_cmd(config_json: str | None, file_path: str | None,
                   tag: str | None) -> None:
    """Seed (or re-seed) the fake-github for a session.

    The JSON may be passed inline as the argument, via --file, or on stdin
    (precedence in that order). Shape::

      {
        "git_backed": true,
        "default_branch": "master",
        "prs": [
          {"head": "feat-x", "title": "Feature X", "draft": true}
        ],
        "scripts": [
          {"match": "pr merge", "returncode": 1, "stderr": "conflict", "times": 1}
        ]
      }

    \b
    Examples:
      pm fake-github config set '{"prs":[{"head":"feat-x","draft":true}]}'
      pm fake-github config set --file gh.json
      pm fake-github config set < gh.json
    """
    from pathlib import Path

    if config_json is not None:
        raw, source = config_json, "argument"
    elif file_path is not None:
        raw, source = Path(file_path).read_text(), file_path
    else:
        if click.get_text_stream("stdin").isatty():
            raise click.ClickException(
                "No config given: pass JSON as an argument, --file, or on stdin.")
        raw, source = click.get_text_stream("stdin").read(), "stdin"

    try:
        cfg = json.loads(raw)
    except json.JSONDecodeError as e:
        raise click.ClickException(f"Invalid JSON from {source}: {e}")
    if not isinstance(cfg, dict):
        raise click.ClickException("Config must be a JSON object (mapping).")

    resolved = _resolve_tag(tag)
    from pm_core import fake_github as fgh
    try:
        backend = fgh.install_session(cfg, resolved)
    except (RuntimeError, KeyError, ValueError) as e:
        raise click.ClickException(str(e))
    click.echo(
        f"Installed fake-github for session {resolved!r} "
        f"({len(backend.prs)} PR(s), "
        f"{'git-backed' if backend.git_repo else 'metadata-only'})."
    )


@config.command("show")
@click.option("--tag", "-t", default=None,
              help="Session tag to read (default: current session).")
def config_show_cmd(tag: str | None) -> None:
    """Print the fake-github state for a session (or note its absence)."""
    from pm_core.paths import fake_github_dir

    resolved = _resolve_tag(tag)
    d = fake_github_dir(resolved)
    state_file = d / "state.json" if d else None
    if not state_file or not state_file.exists():
        click.echo(f"No fake-github for session {resolved!r} "
                   "(github calls use real gh).")
        return
    click.echo(state_file.read_text().rstrip())


@config.command("clear")
@click.option("--tag", "-t", default=None,
              help="Session tag to clear (default: current session).")
def config_clear_cmd(tag: str | None) -> None:
    """Remove the fake-github state for a session (reverts to real gh)."""
    from pm_core.paths import clear_fake_github

    resolved = _resolve_tag(tag)
    clear_fake_github(resolved)
    click.echo(f"Cleared fake-github for session {resolved!r}.")
