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

    # Memory governor settings
    from pm_core.paths import get_global_setting_value
    from pm_core import memory_governor as mg
    target_raw = get_global_setting_value("container-system-memory-target", "")
    scope = get_global_setting_value("container-system-memory-scope", "pm")
    reserve_raw = get_global_setting_value("container-system-memory-reserve", "")
    default_proj = get_global_setting_value(
        "container-system-memory-default-projection", "")
    history_size = get_global_setting_value(
        "container-system-memory-history-size", "20")

    click.echo("")
    click.echo("Memory governor:")
    click.echo(f"  Target:        {target_raw or '(not set — governor inactive)'}")
    click.echo(f"  Scope:         {scope}")
    click.echo(f"  Host reserve:  {reserve_raw or mg._DEFAULT_RESERVE + ' (default)'}")
    click.echo(f"  Default proj:  {default_proj or '(not set — uses memory-limit)'}")
    click.echo(f"  History size:  {history_size}")

    snap = mg.take_snapshot()
    if snap.error:
        click.echo(f"  Current:       unmeasurable — launches are refused: {snap.error}")
    elif snap.active:
        click.echo(f"  Current:       {mg._fmt_mb(snap.measured_mb or 0)} used"
                   f" + {mg._fmt_mb(snap.growth_mb)} expected growth"
                   f" / {mg._fmt_mb(snap.target_mb)} target")
        if snap.host is not None and snap.reserve_mb is not None:
            click.echo(f"  Host free:     {mg._fmt_mb(snap.host.available_mb)}"
                       f" of {mg._fmt_mb(snap.host.total_mb)}"
                       f" (reserve {mg._fmt_mb(snap.reserve_mb)})")
    for action, reason in mg.recent_blocked():
        click.echo(f"  Blocked:       {action} — {reason}")

    # Queue policy
    from pm_core.launch_queue import get_queue_policy, get_queue_status
    queue_policy = get_queue_policy()
    click.echo(f"  Queue policy:  {queue_policy}")

    queue = get_queue_status()
    waiting = [e for e in queue.get("entries", [])
               if e.get("status") == "waiting"]
    acquired = [e for e in queue.get("entries", [])
                if e.get("status") == "acquired"]
    if waiting or acquired:
        click.echo(f"  Queue depth:   {len(waiting)} waiting, {len(acquired)} acquired")

    click.echo("")
    click.echo("Stop-on-idle:")
    click.echo(f"  impl:          {'on' if mg.get_stop_idle_policy('impl') else 'off'}")
    click.echo(f"  review:        {'on' if mg.get_stop_idle_policy('review') else 'off'}")
    click.echo(f"  qa:            {'on' if mg.get_stop_idle_policy('qa_scenario') else 'off'}")

    if enabled and not runtime_ok:
        click.echo(
            f"\nWarning: Container mode is enabled but {cfg.runtime} is not available.",
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
@click.argument("key", type=click.Choice([
    "image", "memory-limit", "cpu-limit", "runtime",
    "system-memory-target", "system-memory-scope", "system-memory-reserve",
    "system-memory-default-projection", "system-memory-history-size",
    "system-memory-queue-policy",
    "stop-idle-impl", "stop-idle-review", "stop-idle-qa",
]))
@click.argument("value")
def container_set(key: str, value: str):
    """Set a container configuration value.

    Keys: image, memory-limit, cpu-limit, runtime,
          system-memory-target, system-memory-scope, system-memory-reserve,
          system-memory-default-projection, system-memory-history-size,
          system-memory-queue-policy,
          stop-idle-impl, stop-idle-review, stop-idle-qa
    """
    from pm_core.paths import set_global_setting_value

    # Validate specific keys
    if key == "runtime" and value not in ("docker", "podman"):
        click.echo(f"Error: runtime must be 'docker' or 'podman', got '{value}'",
                    err=True)
        raise SystemExit(1)
    if key == "system-memory-scope" and value not in ("pm", "system"):
        click.echo("Error: system-memory-scope must be 'pm' or 'system'", err=True)
        raise SystemExit(1)
    if key == "system-memory-queue-policy":
        from pm_core.launch_queue import VALID_POLICIES
        if value not in VALID_POLICIES:
            click.echo(
                f"Error: system-memory-queue-policy must be one of: "
                f"{', '.join(VALID_POLICIES)}", err=True)
            raise SystemExit(1)
    if key.startswith("stop-idle-") and value not in ("on", "off"):
        click.echo("Error: stop-idle value must be 'on' or 'off'", err=True)
        raise SystemExit(1)
    if key == "system-memory-history-size":
        try:
            n = int(value)
            if n < 1:
                raise ValueError
        except ValueError:
            click.echo("Error: system-memory-history-size must be a positive integer",
                        err=True)
            raise SystemExit(1)
    # Sizes need a unit: a bare number is bytes (the runtimes' --memory
    # convention), so "48" would be a 1 MiB target that refuses everything.
    if (key in ("system-memory-target", "system-memory-default-projection",
                "system-memory-reserve")
            and value.lower() not in ("off", "none", "unset")
            and not value.strip().endswith("%")
            and not value.strip()[-1:].isalpha()):
        click.echo(f"Error: {key} needs a unit, e.g. {value.strip()}g",
                   err=True)
        raise SystemExit(1)
    if key == "system-memory-reserve":
        from pm_core.memory_governor import parse_reserve
        try:
            parse_reserve(value, 1024)
        except ValueError:
            click.echo(f"Error: system-memory-reserve must be a size (8g) or "
                       f"a percentage (10%), got {value!r}", err=True)
            raise SystemExit(1)
    if key == "system-memory-target" and value.lower() in ("off", "none", "unset"):
        value = ""  # governor inactive
    elif key in ("system-memory-target", "system-memory-default-projection"):
        from pm_core.memory_governor import parse_memory
        try:
            parse_memory(value)
        except ValueError:
            click.echo(f"Error: cannot parse memory value: {value!r}", err=True)
            raise SystemExit(1)

    setting_name = f"container-{key}"
    set_global_setting_value(setting_name, value)
    click.echo(f"Set {key} = {value or '(unset)'}")


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
