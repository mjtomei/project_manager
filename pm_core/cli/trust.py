"""Workspace-trust CLI commands."""

import os

import click

from pm_core.cli import cli


@cli.group("trust")
def trust_group():
    """Manage workspace trust for unattended Claude sessions.

    pm automatically trusts the workdirs it creates (~/.pm/workdirs) so
    implementation, review, QA, sign-off and merge sessions never stall at
    Claude's "Do you trust this folder?" prompt.  Any other directory keeps
    the prompt unless you authorize it here.  This is separate from
    --dangerously-skip-permissions.
    """


def _abs(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path))


@trust_group.command("status")
@click.argument("path", default=".", type=click.Path(file_okay=False))
def trust_status(path):
    """Show whether PATH is approved and trusted."""
    from pm_core import workspace_trust as wt
    p = _abs(path)
    runtime = wt.get_trust_runtime()
    approved = wt.approved_path(p)
    click.echo(f"path:     {p}")
    click.echo(f"approved: {'yes' if approved else 'no'}")
    click.echo(f"trusted:  {'yes' if runtime.is_trusted(p) else 'no'} "
               f"(runtime: {runtime.name})")
    if not approved:
        click.echo(f"Authorize with: pm trust add {p}")


@trust_group.command("list")
def trust_list():
    """List roots pm may trust automatically."""
    from pm_core import workspace_trust as wt
    from pm_core.paths import workdirs_base
    click.echo(f"{workdirs_base()}  (pm-created workdirs)")
    for root in wt.authorized_roots():
        click.echo(f"{root}  (authorized)")


@trust_group.command("add")
@click.argument("path", type=click.Path(exists=True, file_okay=False))
def trust_add(path):
    """Authorize PATH (and everything under it) and trust it now."""
    from pm_core import workspace_trust as wt
    p = _abs(path)
    # Home or any directory containing it (/, /home) would authorize every
    # workspace the user has — the blanket trust pm deliberately avoids.
    home = _abs("~")
    if wt.is_within(home, p) or wt.is_within(os.path.realpath(home),
                                             os.path.realpath(p)):
        raise click.ClickException(
            f"refusing to authorize {p}: pick a specific project directory")
    wt.set_authorized_roots(wt.authorized_roots() + [p])
    outcome = wt.get_trust_runtime().bootstrap(p)
    if not outcome.ok:
        raise click.ClickException(outcome.message)
    click.echo(f"Authorized {p} ({outcome.status})")


@trust_group.command("remove")
@click.argument("path", type=click.Path(file_okay=False))
def trust_remove(path):
    """Stop authorizing PATH for automatic trust.

    Does not edit Claude's own config; revoke trust there if needed.
    """
    from pm_core import workspace_trust as wt
    p = _abs(path)
    roots = wt.authorized_roots()
    if p not in roots:
        raise click.ClickException(f"{p} is not an authorized root")
    wt.set_authorized_roots([r for r in roots if r != p])
    click.echo(f"Removed {p}")
