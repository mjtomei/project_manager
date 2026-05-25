"""Container isolation CLI commands."""

import click

from pm_core.cli.helpers import state_root, _get_pm_session
from pm_core.cli import cli


@cli.group("container")
def container_group():
    """Manage container isolation for Claude sessions.

    When enabled, all Claude sessions (implementation, review, QA, watcher)
    run inside Docker containers for isolation.  Only the Claude process
    itself runs in the container — companion panes and status panes remain
    on the host.
    """


@container_group.command("status")
def container_status():
    """Show current container isolation settings."""
    from pm_core.container import (
        is_container_mode_enabled, load_container_config, _runtime_available,
    )

    enabled = is_container_mode_enabled()
    cfg = load_container_config()
    runtime_ok = _runtime_available()

    click.echo(f"Container mode:  {'enabled' if enabled else 'disabled'}")
    click.echo(f"Runtime:         {cfg.runtime}")
    click.echo(f"Runtime available: {'yes' if runtime_ok else 'no'}")
    click.echo(f"Image:           {cfg.image}")
    click.echo(f"Memory limit:    {cfg.memory_limit}")
    click.echo(f"CPU limit:       {cfg.cpu_limit}")

    if enabled and not runtime_ok:
        click.echo(
            f"\nWarning: Container mode is enabled but {cfg.runtime} is not available.",
            err=True,
        )

    # Keyring headroom — leaked rootless-podman containers exhaust the
    # namespaced-root keyring quota, silently breaking container QA.
    from pm_core.container import (
        running_container_count, keyring_usage, keyring_pressure,
    )
    if enabled and runtime_ok:
        click.echo(f"Running pm containers: {running_container_count()}")
        rows = keyring_usage()
        if rows:
            worst = max(
                (r for r in rows.values() if r["max_keys"] > 0),
                key=lambda r: r["keys"] / r["max_keys"], default=None,
            )
            if worst:
                click.echo(
                    f"Keyring keys:    {worst['keys']}/{worst['max_keys']} "
                    f"(bytes {worst['bytes']}/{worst['max_bytes']})"
                )
        pressure = keyring_pressure()
        if pressure:
            click.echo(
                f"\nWarning: kernel keyring for uid {pressure['uid']} is "
                f"{pressure['ratio']*100:.0f}% full "
                f"({pressure['keys']}/{pressure['max_keys']} keys). "
                f"Reap leaked containers with 'pm container reap'.",
                err=True,
            )


@container_group.command("enable")
def container_enable():
    """Enable container isolation for Claude sessions."""
    from pm_core.paths import set_global_setting
    from pm_core.container import _runtime_available, _get_runtime

    if not _runtime_available():
        runtime = _get_runtime()
        click.echo(f"Error: {runtime} is not available. Install and start {runtime} first.",
                    err=True)
        raise SystemExit(1)

    set_global_setting("container-enabled", True)
    click.echo("Container isolation enabled.")


@container_group.command("disable")
def container_disable():
    """Disable container isolation (run Claude directly on the host)."""
    from pm_core.paths import set_global_setting

    set_global_setting("container-enabled", False)
    click.echo("Container isolation disabled.")


@container_group.command("set")
@click.argument("key", type=click.Choice(["image", "memory-limit", "cpu-limit", "runtime"]))
@click.argument("value")
def container_set(key: str, value: str):
    """Set a container configuration value.

    Keys: image, memory-limit, cpu-limit, runtime
    """
    from pm_core.paths import set_global_setting_value

    if key == "runtime" and value not in ("docker", "podman"):
        click.echo(f"Error: runtime must be 'docker' or 'podman', got '{value}'",
                    err=True)
        raise SystemExit(1)

    setting_name = f"container-{key}"
    set_global_setting_value(setting_name, value)
    click.echo(f"Set {key} = {value}")


@container_group.command("build-base")
@click.option("--tag", default=None, help="Image tag (default: pm-dev:latest)")
def container_build_base(tag: str | None):
    """Build the pm developer base image with pre-installed tools.

    The image includes git, python3, pip, node/npm, curl, jq, and
    build-essential. Building it once avoids installing these tools on
    every container start.
    """
    from pm_core.container import build_image, DEFAULT_IMAGE

    tag = tag or DEFAULT_IMAGE
    click.echo(f"Building image {tag}...")
    try:
        build_image(tag=tag)
        click.echo(f"Image {tag} built successfully.")
    except Exception as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1)


@container_group.command("build")
@click.option("--tag", default=None, help="Image tag (default: pm-project-<name>:latest)")
@click.option("--base", default=None, help="Base image (default: pm-dev:latest)")
def container_build(tag: str | None, base: str | None):
    """Launch a Claude session to build a project-specific Docker image.

    Analyzes the project's dependency files (requirements.txt, package.json,
    Cargo.toml, etc.) and the current base image, then generates a Dockerfile
    that installs all project dependencies. Builds and tags the image, and
    updates the container config to use it.

    If the build fails, Claude will fix the Dockerfile and retry.
    """
    from pm_core import tmux as tmux_mod
    from pm_core.claude_launcher import find_claude, build_claude_shell_cmd
    from pm_core.container import DEFAULT_IMAGE, load_container_config

    root = state_root()

    # Determine project root (repo root, parent of pm/)
    from pm_core import store
    data = store.load(root)
    project = data.get("project", {})
    project_name = project.get("name", "project")

    # Resolve the repo working directory
    if store.is_internal_pm_dir(root):
        project_dir = root.parent
    else:
        project_dir = root

    config = load_container_config()
    base_image = base or DEFAULT_IMAGE
    image_tag = tag or f"pm-project-{project_name}:latest"

    prompt = _build_container_build_prompt(
        project_name=project_name,
        project_dir=str(project_dir),
        base_image=base_image,
        image_tag=image_tag,
        runtime=config.runtime,
    )

    if not find_claude():
        click.echo("Claude CLI not found.", err=True)
        click.echo("\nPrompt:")
        click.echo("-" * 60)
        click.echo(prompt)
        raise SystemExit(1)

    claude_cmd = build_claude_shell_cmd(prompt=prompt, session_type="container")

    # Try to launch in tmux
    pm_session = _get_pm_session()
    if pm_session and tmux_mod.session_exists(pm_session):
        window_name = "container-build"
        existing = tmux_mod.find_window_by_name(pm_session, window_name)
        if existing:
            tmux_mod.select_window(pm_session, existing["index"])
            click.echo(f"Switched to existing window '{window_name}'")
            return
        try:
            tmux_mod.new_window(pm_session, window_name, claude_cmd,
                                str(project_dir))
            win = tmux_mod.find_window_by_name(pm_session, window_name)
            if win:
                tmux_mod.set_shared_window_size(pm_session, win["id"])
            click.echo(f"Launched container build session in window '{window_name}'")
            return
        except Exception as e:
            click.echo(f"Failed to create tmux window: {e}", err=True)

    # Fallback: launch interactively
    click.echo("Launching Claude...")
    from pm_core.claude_launcher import launch_claude
    launch_claude(prompt, cwd=str(project_dir), session_key="container:build",
                  pm_root=root, session_type="container")


def _build_container_build_prompt(
    project_name: str,
    project_dir: str,
    base_image: str,
    image_tag: str,
    runtime: str = "docker",
) -> str:
    """Build the prompt for the container build Claude session."""

    return f"""\
You are building a project-specific container image for "{project_name}".

## Goal

Set up the dependencies that containers used for implementation, review, or QA
of this project will need on top of the base image. The base image already
provides pm's runtime contract (pm user, PATH, git + host git identity, tmux,
sudo, python, no ENTRYPOINT) — you only need to add what *this project* needs
on top.

## Project directory

{project_dir}

## Base image

{base_image}

## Target image tag

{image_tag}

## Instructions

1. Discover what this project needs by scanning:
   - **Language/runtime manifests**: requirements.txt, pyproject.toml,
     package.json, Cargo.toml, go.mod, Gemfile, etc. — note language
     versions, package-manager deps, and any system packages required for
     native extensions.
   - **Existing Dockerfiles**: use as reference for system deps, but do not
     modify them — create Dockerfile.pm-project separately.
   - **pm QA instruction files**: read every file under {project_dir}/pm/qa/
     (these are instruction docs added via `pm qa` and consumed by the pm
     QA step). Any tool, binary, or service they reference must be
     available inside the container, since QA runs there. Also check any
     project-level CI / lint config (.github/, pre-commit, etc.) for tools
     that aren't already declared as language-level deps.
   - **Implementation/review needs**: anything else an interactive Claude
     session working on this project would expect to find (build tools,
     codegen utilities, project-specific CLIs).

2. Create a Dockerfile at {project_dir}/Dockerfile.pm-project that:
   - Starts `FROM {base_image}`
   - Installs the project's system + language deps
   - Installs QA/review tooling discovered above
   - Stays minimal — copy dependency specs, not the full source tree
   - For pm-on-pm or other cases where the base already covers everything
     this project needs, the file may be a near-empty thin wrapper. That's
     fine — don't invent work.

3. Build the image:
   ```bash
   {runtime} build -t {image_tag} -f {project_dir}/Dockerfile.pm-project {project_dir}
   ```

4. If the build fails, analyze the error, fix the Dockerfile, and retry.

5. Once the image builds successfully, update the pm container config:
   ```bash
   pm container set image {image_tag}
   ```

6. Verify the setup:
   ```bash
   pm container status
   ```
"""


@container_group.command("cleanup")
@click.option("--pr", "pr_id", default=None, help="Filter by PR ID")
def container_cleanup(pr_id: str | None):
    """Remove stale pm containers."""
    from pm_core.container import _run_runtime, remove_container, CONTAINER_PREFIX

    result = _run_runtime(
        "ps", "-a", "--filter", f"name={CONTAINER_PREFIX}",
        "--format", "{{.Names}}\t{{.Status}}",
        check=False, timeout=30,
    )
    if result.returncode != 0:
        click.echo("Failed to list containers.", err=True)
        raise SystemExit(1)

    lines = result.stdout.strip().splitlines()
    if not lines or not lines[0]:
        click.echo("No pm containers found.")
        return

    removed = 0
    for line in lines:
        parts = line.split("\t", 1)
        name = parts[0].strip()
        status = parts[1].strip() if len(parts) > 1 else ""
        if pr_id and pr_id not in name:
            continue
        click.echo(f"  Removing: {name} ({status})")
        remove_container(name)
        removed += 1

    click.echo(f"Removed {removed} container(s).")


@container_group.command("reap")
@click.option("--dry-run", is_flag=True, default=False,
              help="Show what would be reaped without removing anything.")
def container_reap(dry_run: bool):
    """Reap orphaned pm containers (running AND stopped).

    Removes containers whose PR is merged/closed or whose tmux session is
    gone, across all PRs.  Unlike 'pm container cleanup' (which removes every
    pm container), this is orphan-aware and leaves active sessions running.
    The keys held by leaked *running* containers are what exhaust the
    rootless-podman keyring and break container QA — pruning only stopped
    containers does not free them.
    """
    from pm_core.container import reap_orphaned_containers

    reaped = reap_orphaned_containers(dry_run=dry_run)
    if not reaped:
        click.echo("No orphaned pm containers found.")
        return
    verb = "Would reap" if dry_run else "Reaped"
    for name, reason in reaped:
        click.echo(f"  {name}  ({reason})")
    click.echo(f"{verb} {len(reaped)} orphaned container(s).")
