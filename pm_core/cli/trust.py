"""Workspace-trust CLI commands."""

import os

import click

from pm_core.cli import cli


@cli.group("trust")
def trust_group():
    """Manage workspace trust for unattended Claude sessions.

    pm automatically trusts the workdirs it creates (~/.pm/workdirs, or
    the 'workdirs-dir' setting) and QA scenario scratch (~/.pm/scratch/qa,
    or under 'scratch-dir') so implementation, review, QA, sign-off and
    merge sessions never stall at Claude's "Do you trust this folder?"
    prompt; 'pm trust list' shows the roots.  Any other directory keeps
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
    from pm_core.paths import qa_scratch_roots, workdirs_roots
    refused = "; NOT trusted: it contains your home directory"
    for root in workdirs_roots():
        click.echo(f"{root}  (pm-created workdirs"
                   f"{refused if wt.covers_home(root) else ''})")
    for root in qa_scratch_roots():
        click.echo(f"{root}  (pm-created QA scenario scratch"
                   f"{refused if wt.covers_home(root) else ''})")
    for root in wt.authorized_roots():
        click.echo(f"{root}  (authorized)")


@trust_group.command("add")
@click.argument("path", type=click.Path(exists=True, file_okay=False))
def trust_add(path):
    """Authorize PATH (and everything under it) and trust it now."""
    from pm_core import workspace_trust as wt
    p = _abs(path)
    if wt.covers_home(p):
        raise click.ClickException(
            f"refusing to authorize {p}: pick a specific project directory")
    added = wt.add_authorized_root(p)
    outcome = wt.get_trust_runtime().bootstrap(p)
    if not outcome.ok:
        # Don't leave a root authorized when the command reports failure.
        if added:
            wt.remove_authorized_root(p)
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
    if not wt.remove_authorized_root(p):
        raise click.ClickException(f"{p} is not an authorized root")
    click.echo(f"Removed {p}")
