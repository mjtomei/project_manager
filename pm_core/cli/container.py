"""Container isolation CLI commands."""

import glob
import os
from pathlib import Path

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
        is_container_mode_enabled, load_container_config, _docker_available,
    )

    enabled = is_container_mode_enabled()
    cfg = load_container_config()
    docker_ok = _docker_available()

    click.echo(f"Container mode:  {'enabled' if enabled else 'disabled'}")
    click.echo(f"Docker available: {'yes' if docker_ok else 'no'}")
    click.echo(f"Image:           {cfg.image}")
    click.echo(f"Memory limit:    {cfg.memory_limit}")
    click.echo(f"CPU limit:       {cfg.cpu_limit}")

    if enabled and not docker_ok:
        click.echo(
            "\nWarning: Container mode is enabled but Docker is not available.",
            err=True,
        )


@container_group.command("enable")
def container_enable():
    """Enable container isolation for Claude sessions."""
    from pm_core.paths import set_global_setting
    from pm_core.container import _docker_available

    if not _docker_available():
        click.echo("Error: Docker is not available. Install and start Docker first.",
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
@click.argument("key", type=click.Choice(["image", "memory-limit", "cpu-limit"]))
@click.argument("value")
def container_set(key: str, value: str):
    """Set a container configuration value.

    Keys: image, memory-limit, cpu-limit
    """
    from pm_core.paths import set_global_setting_value

    setting_name = f"container-{key}"
    set_global_setting_value(setting_name, value)
    click.echo(f"Set {key} = {value}")


@container_group.command("build-image")
@click.option("--tag", default=None, help="Image tag (default: pm-dev:latest)")
def container_build_image(tag: str | None):
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
@click.option("--base", default=None, help="Base image (default: current container image)")
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
    from pm_core.container import load_container_config

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
    base_image = base or config.image
    image_tag = tag or f"pm-project-{project_name}:latest"

    # Scan for dependency files
    dep_files = _find_dependency_files(project_dir)

    prompt = _build_container_build_prompt(
        project_name=project_name,
        project_dir=str(project_dir),
        base_image=base_image,
        image_tag=image_tag,
        dep_files=dep_files,
    )

    if not find_claude():
        click.echo("Claude CLI not found.", err=True)
        click.echo("\nPrompt:")
        click.echo("-" * 60)
        click.echo(prompt)
        raise SystemExit(1)

    claude_cmd = build_claude_shell_cmd(prompt=prompt)

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
                  pm_root=root)


def _find_dependency_files(project_dir: Path) -> dict[str, str]:
    """Scan project directory for common dependency files.

    Returns a dict of {relative_path: file_contents}.
    """
    candidates = [
        "requirements.txt", "requirements/*.txt", "setup.py", "setup.cfg",
        "pyproject.toml", "Pipfile",
        "package.json",
        "Cargo.toml",
        "go.mod",
        "Gemfile",
        "Makefile", "CMakeLists.txt",
        "Dockerfile", "Dockerfile.*", ".dockerignore",
        "docker-compose.yml", "docker-compose.yaml",
        "compose.yml", "compose.yaml",
    ]

    found = {}
    for pattern in candidates:
        if "*" in pattern:
            matches = glob.glob(str(project_dir / pattern))
            for m in matches:
                rel = os.path.relpath(m, project_dir)
                try:
                    content = Path(m).read_text(errors="replace")
                    if len(content) < 50_000:  # skip huge lockfiles
                        found[rel] = content
                except OSError:
                    pass
        else:
            path = project_dir / pattern
            if path.is_file():
                try:
                    content = path.read_text(errors="replace")
                    if len(content) < 50_000:
                        found[pattern] = content
                except OSError:
                    pass

    return found


def _build_container_build_prompt(
    project_name: str,
    project_dir: str,
    base_image: str,
    image_tag: str,
    dep_files: dict[str, str],
) -> str:
    """Build the prompt for the container build Claude session."""

    dep_section = ""
    if dep_files:
        dep_section = "\n## Dependency files found\n\n"
        for rel_path, content in sorted(dep_files.items()):
            dep_section += f"### {rel_path}\n```\n{content}\n```\n\n"
    else:
        dep_section = "\n## No standard dependency files found\n\nInspect the project directory to identify dependencies manually.\n"

    return f"""\
You are building a project-specific Docker image for "{project_name}".

## Goal

Create a Dockerfile that installs all project dependencies on top of the base
image, build it, tag it, and update the pm container config to use it.

## Project directory

{project_dir}

## Base image

{base_image}

## Target image tag

{image_tag}

{dep_section}
## Instructions

1. Analyze the dependency files above (and any others you find in the project).
   Identify:
   - Language runtimes and versions needed
   - System packages (apt/yum) required for native extensions
   - Package manager dependencies (pip, npm, cargo, etc.)

2. Create a Dockerfile at {project_dir}/Dockerfile.pm-project with:
   - FROM {base_image}
   - System package installation (if needed)
   - COPY and install of dependency files
   - Any build steps needed for native extensions
   - Keep the image minimal — don't copy the full source tree, just dependency specs

3. Build the image:
   ```bash
   docker build -t {image_tag} -f {project_dir}/Dockerfile.pm-project {project_dir}
   ```

4. If the build fails, analyze the error, fix the Dockerfile, and retry.
   Common issues:
   - Missing system packages for native extensions
   - Wrong Python/Node version
   - Network issues (retry or use different mirrors)

5. Once the image builds successfully, update the pm container config:
   ```bash
   pm container set image {image_tag}
   ```

6. Verify the setup:
   ```bash
   pm container status
   ```

## Tips

- If the project has a Dockerfile already, use it as a reference but don't
  modify it — create Dockerfile.pm-project separately.
- For Python projects, prefer installing from requirements.txt or pyproject.toml.
- For Node.js projects, copy package.json and package-lock.json, then run npm ci.
- If you're unsure about system dependencies, try building first and fix errors.
- The goal is a reusable image — dependencies change rarely, so this image
  avoids reinstalling them on every container start.
"""


@container_group.command("cleanup")
@click.option("--pr", "pr_id", default=None, help="Filter by PR ID")
def container_cleanup(pr_id: str | None):
    """Remove stale pm containers."""
    from pm_core.container import _run_docker, remove_container, CONTAINER_PREFIX

    result = _run_docker(
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
