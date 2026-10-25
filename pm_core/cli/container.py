"""Container isolation CLI commands."""

import subprocess

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

    if runtime_ok:
        from pm_core.container import keyring_summary, running_container_count
        running = running_container_count()
        if running is not None:
            click.echo(f"Running pm containers: {running}")
        keyring = keyring_summary()
        if keyring:
            click.echo(f"Kernel keyring:  {keyring}")
        from pm_core.container import pids_pressure
        for name, pids, limit in pids_pressure(0.8):
            click.echo(f"PID pressure:    {name} at {pids}/{limit} — "
                       f"'pm container restart {name}' clears it")
    # Persisted failures and pending releases remain useful even when the
    # runtime executable is unavailable. They must not disappear with metrics.
    _echo_reaper_state()

    if enabled and not runtime_ok:
        click.echo(
            f"\nWarning: Container mode is enabled but {cfg.runtime} is not available.",
            err=True,
        )


def _echo_reaper_state() -> None:
    from pm_core import container_reaper
    state = container_reaper.last_state()
    if state.get("last_run"):
        import time as _time
        when = _time.strftime("%Y-%m-%d %H:%M:%S",
                              _time.localtime(state["last_run"]))
        click.echo(f"Last cleanup:    {when} ({state.get('last_reason', '')}): "
                   f"{state.get('last_summary', '')}")
    failures = container_reaper.pending_failures()
    if failures:
        click.echo(f"Cleanup failures ({len(failures)}) — retry with 'pm container reap':")
        for name, info in sorted(failures.items()):
            click.echo(f"  {name}: {info.get('error', '')}")
    retained = container_reaper.retained_names()
    if retained:
        click.echo(f"Retained:        {', '.join(retained)}")


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
    from pm_core.container import _run_runtime, remove_containers, CONTAINER_PREFIX

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

    names = []
    for line in lines:
        parts = line.split(None, 1)
        name = parts[0].strip()
        status = parts[1].strip() if len(parts) > 1 else ""
        # The name filter matches substrings — never touch e.g. "npm-cache".
        if not name.startswith(CONTAINER_PREFIX):
            continue
        if pr_id and pr_id not in name:
            continue
        click.echo(f"  Removing: {name} ({status})")
        names.append(name)

    removed, failures = remove_containers(names)
    for name, err in sorted(failures.items()):
        click.echo(f"  FAILED:   {name}: {err}", err=True)
    click.echo(f"Removed {len(removed)} container(s).")
    if failures:
        raise SystemExit(1)


def echo_reap_outcome(outcome) -> None:
    """Print a reconcile preview/outcome: one line per container, then a summary."""
    for d in outcome.decisions:
        action = d.action
        if not outcome.dry_run:
            if d.info.name in outcome.removed:
                action = "removed"
            elif d.info.name in outcome.failures:
                action = "FAILED"
        state = "running" if d.info.running else (d.info.status or "stopped")
        click.echo(f"  {action:<8} {d.info.name} [{state}] — {d.reason}")
        if d.info.name in outcome.failures:
            click.echo(f"           {outcome.failures[d.info.name]}")
    listed = {d.info.name for d in outcome.decisions}
    for name, error in outcome.failures.items():
        if name not in listed:
            click.echo(f"  FAILED   {name}: {error}")
    for proxy in outcome.proxies_released:
        click.echo(f"  stopped  push proxy {proxy}")
    for name, pids, limit, why in outcome.pid_pressure:
        click.echo(f"  WARNING  {name} at {pids}/{limit} PIDs ({why}) — run "
                   f"'pm container restart {name}' once its session is done")
    click.echo(outcome.summary())


def run_reap(scope, dry_run: bool) -> None:
    """Shared body of ``pm container reap`` and ``pm session cleanup``."""
    from pm_core import container_reaper
    outcome = container_reaper.reconcile(
        scope, dry_run=dry_run, reason="dry-run" if dry_run else "manual")
    if outcome.error or outcome.skipped:
        click.echo(outcome.summary(), err=True)
        raise SystemExit(1)
    if not outcome.decisions and not outcome.proxies_released:
        click.echo(f"No pm containers in scope ({outcome.scope}).")
    else:
        click.echo(f"Scope: {outcome.scope}")
    echo_reap_outcome(outcome)
    if outcome.failures:
        raise SystemExit(1)


@container_group.command("reap")
@click.option("--dry-run", is_flag=True, default=False,
              help="Only show what would be removed and why")
@click.option("--pr", "pr_id", default=None, help="Only this PR's containers")
@click.option("--session", "session_tag", default=None,
              help="Only containers of this session tag")
@click.option("--include-retained", is_flag=True, default=False,
              help="Also remove containers marked with 'pm container retain'")
def container_reap(dry_run: bool, pr_id: str | None, session_tag: str | None,
                   include_retained: bool):
    """Remove leaked pm containers that nothing owns any more.

    A container is kept while a live tmux pane runs in it, while it is being
    launched, or when it was retained with 'pm container retain'.  Everything
    else in scope (finished runs, merged/closed PRs, dead sessions) is
    removed, and push proxies no container uses are stopped.  Workdirs,
    captures and transcripts live on the host and are not touched.
    """
    from pm_core import container_reaper
    run_reap(container_reaper.Scope(pr_id=pr_id, session_tag=session_tag,
                                    include_retained=include_retained),
             dry_run)


@container_group.command("retain")
@click.argument("name")
@click.option("--release", is_flag=True, default=False,
              help="Drop the retention so cleanup may remove it again")
@click.option("--note", default="", help="Why the container is kept")
def container_retain(name: str, release: bool, note: str):
    """Keep container NAME out of automatic cleanup (e.g. for a discussion)."""
    from pm_core import container_reaper
    if release:
        if container_reaper.unretain(name):
            click.echo(f"Released {name}; cleanup may remove it once unowned.")
        else:
            click.echo(f"{name} was not retained.")
        return
    from pm_core import container as container_mod
    try:
        name = container_reaper.retain_current(name, note)
    except (container_mod.ContainerError, OSError, subprocess.TimeoutExpired) as exc:
        click.echo(str(exc), err=True)
        raise SystemExit(1)
    click.echo(f"Retained {name}. Release with 'pm container retain --release {name}'.")


@container_group.command("restart")
@click.argument("name")
@click.option("--force", is_flag=True, default=False,
              help="Restart even though a live tmux pane still uses it")
def container_restart(name: str, force: bool):
    """Restart container NAME in place to clear PID/memory exhaustion.

    Every process inside is ended (including a Claude session running
    there); the container's files, mounts and setup are kept.  Refuses while
    a live pane uses the container unless --force.
    """
    from pm_core import container as container_mod
    from pm_core import container_reaper
    try:
        name = container_mod.canonical_container_name(name)
    except (container_mod.ContainerError, OSError, subprocess.TimeoutExpired) as exc:
        click.echo(str(exc), err=True)
        raise SystemExit(1)
    before = (container_mod.pids_usage() or {}).get(name)
    with container_mod.launch_lock(name, timeout=60) as locked:
        if not locked:
            click.echo(f"{name} is being launched right now; try again.", err=True)
            raise SystemExit(1)
        # A launch may have attached its pane while we waited for the lock.
        try:
            owners = [] if force else container_reaper.live_owner_panes(name)
            if not force and container_mod.recent_launch(name, container_reaper.LAUNCH_GRACE):
                click.echo(f"{name} is awaiting attachment; retry after its launch lease "
                           "expires, or use --force only when it is safe to end the session.", err=True)
                raise SystemExit(1)
        except (container_mod.ContainerError, OSError) as e:
            click.echo(f"{e}. Retry once ownership can be checked, or use --force "
                       "only when it is safe to end the session.", err=True)
            raise SystemExit(1)
        if owners:
            click.echo(f"{name} is in use by live pane(s) {', '.join(owners)}; "
                       f"restarting would end that session. Re-run with --force "
                       f"once it is safe.", err=True)
            raise SystemExit(1)
        try:
            container_mod.restart_container(name)
        except container_mod.ContainerError as e:
            click.echo(str(e), err=True)
            raise SystemExit(1)
    after = (container_mod.pids_usage() or {}).get(name)

    def fmt(usage):
        return f"{usage[0]}/{usage[1]}" if usage else "?"
    click.echo(f"Restarted {name} (PIDs {fmt(before)} → {fmt(after)}).")
