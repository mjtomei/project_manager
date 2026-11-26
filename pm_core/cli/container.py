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
    from pm_core import image_cache
    consumer = image_cache.read_consumer_entry()
    if consumer:
        click.echo(f"Image cache:     {image_cache.mode()} (consumer of "
                   f"{consumer.get('key')}: "
                   f"{', '.join(consumer.get('names') or [])})")
    else:
        click.echo(f"Image cache:     {image_cache.mode()}")

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

    env: dict[str, str] = {}
    claude_cmd = build_claude_shell_cmd(prompt=prompt,
                                        session_type="container", env_out=env)

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
                                str(project_dir), env=env)
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
        # Split on whitespace, not "\t": podman 3.x prints the format's
        # "\t" as spaces, and container names never contain whitespace.
        parts = line.split(None, 1)
        if not parts:
            continue
        name = parts[0]
        status = parts[1].strip() if len(parts) > 1 else ""
        if pr_id and pr_id not in name:
            continue
        click.echo(f"  Removing: {name} ({status})")
        remove_container(name)
        removed += 1

    click.echo(f"Removed {removed} container(s).")


# ---------------------------------------------------------------------------
# Shared image cache (pm_core.image_cache) and scenario storage reclaim
# ---------------------------------------------------------------------------

@container_group.group("cache")
def cache_group():
    """Shared, read-only image cache for nested container engines.

    For projects with nested_podman, pm prepares the container image's
    unpacked layers once per image version (keyed by image ID) on local
    disk and mounts them read-only into every container it launches; each
    engine keeps only its private writable layers.  The 'container-image-
    cache' setting is auto (default: on for a podman host), on or off.
    """


@cache_group.command("status")
def cache_status():
    """List cache entries and which containers use them."""
    from pm_core import image_cache
    from pm_core.image_cache import ImageCacheError
    click.echo(f"Mode: {image_cache.mode()}")
    consumer = image_cache.read_consumer_entry()
    if consumer:
        click.echo(f"This container consumes entry {consumer.get('key')} "
                   f"({', '.join(consumer.get('names') or [])}) at "
                   f"{image_cache.CONSUMER_MOUNT}")
        return
    try:
        root = image_cache.cache_root()
        entries = image_cache.list_entries(root)
    except ImageCacheError as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1)
    click.echo(f"Root: {root}")
    refs = image_cache.referenced_keys()
    if not entries:
        click.echo("No entries.")
    for e in entries:
        if not e.meta:
            click.echo(f"  {e.key}  (incomplete)")
            continue
        used = ("?" if refs is None else
                ("in use" if e.key in refs else "unused"))
        size = e.meta.get("store_bytes")
        size_s = f"{size / 1e9:.2f} GB" if isinstance(size, int) else "?"
        click.echo(f"  {e.key}  {', '.join(e.names)}  {size_s}  "
                   f"prepared {e.meta.get('created_at')} in "
                   f"{e.meta.get('prep_seconds')}s  [{used}]")


@cache_group.command("prepare")
@click.option("--image", default=None,
              help="Image to prepare (default: the configured container image)")
def cache_prepare(image: str | None):
    """Prepare the cache entry for an image now (normally done on first launch)."""
    import time
    from pm_core import image_cache
    from pm_core.container import load_container_config
    image = image or load_container_config().image
    if image_cache.is_consumer():
        click.echo("Error: this container consumes a shared cache entry; "
                   "prepare entries on the host.", err=True)
        raise SystemExit(1)
    t = time.monotonic()
    try:
        entry = image_cache.ensure_prepared(image)
    except image_cache.ImageCacheError as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1)
    click.echo(f"{image}: entry {entry.key} at {entry.path} "
               f"({time.monotonic() - t:.1f}s)")


@cache_group.command("check")
@click.option("--image", default=None, help="Image the engine must see")
@click.option("--home", default=None,
              help="Engine HOME to check (default: $HOME)")
def cache_check(image: str | None, home: str | None):
    """Verify the shared cache works for an engine in this container."""
    from pm_core import image_cache
    res = image_cache.consumer_check(image_ref=image, home=home)
    for ok, text in res.lines:
        click.echo(f"  [{'ok' if ok else 'FAIL'}] {text}")
    if not res.ok:
        raise SystemExit(1)


@cache_group.command("gc")
@click.option("--dry-run", is_flag=True, help="Only show what would be removed")
@click.option("--all-unreferenced", is_flag=True,
              help="Also remove unused entries whose image still exists "
                   "(never the configured image's)")
def cache_gc(dry_run: bool, all_unreferenced: bool):
    """Remove cache entries no container uses and whose image is gone."""
    from pm_core import image_cache
    try:
        summary = image_cache.gc(dry_run=dry_run,
                                 all_unreferenced=all_unreferenced)
    except image_cache.ImageCacheError as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1)
    if summary["problem"]:
        click.echo(f"Nothing removed: {summary['problem']}.", err=True)
        raise SystemExit(1)
    for path, reason in summary["planned"]:
        verb = "would remove" if dry_run else (
            "removed" if (path, reason) in summary["removed"] else "FAILED")
        click.echo(f"  {verb}: {path} ({reason})")
    if not summary["planned"]:
        click.echo("Nothing to remove.")
    if summary["failed"]:
        raise SystemExit(1)


@container_group.command("engine-setup")
@click.option("--home", default=None,
              help="Engine HOME (default: $HOME)")
@click.option("--force", is_flag=True,
              help="Replace an existing containers config pm did not write")
def engine_setup(home: str | None, force: bool):
    """Configure a container engine (in this container) to use the shared cache.

    Writes HOME/.config/containers/storage.conf (overlay, fuse-overlayfs, a
    private graphroot under HOME, the shared store as an additional image
    store) and, for any HOME but the default user's, a containers.conf
    giving the engine its own runroot and tmp dir — so several isolated
    engines can run side by side on the same shared layers.  Then runs
    'pm container cache check' for that HOME.
    """
    from pm_core import image_cache
    try:
        written = image_cache.write_engine_config(home, force=force)
    except image_cache.ImageCacheError as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1)
    for path in written.values():
        click.echo(f"wrote {path}")
    res = image_cache.consumer_check(home=home)
    for ok, text in res.lines:
        click.echo(f"  [{'ok' if ok else 'FAIL'}] {text}")
    if not res.ok:
        raise SystemExit(1)


@container_group.command("reclaim")
@click.option("--pr", "pr_id", default=None,
              help="Only this PR's QA runs (default: every run)")
@click.option("--dry-run", is_flag=True, help="Only show what would be removed")
def container_reclaim(pr_id: str | None, dry_run: bool):
    """Reclaim container stores and image archives left in QA scenario scratch.

    Removes only container-engine stores and image archives (podman save
    output) under scenario scratch dirs that no existing container mounts,
    no process is working in, and whose QA run has ended.  Checkouts,
    captures, notes, drafts and other scratch files are never touched.
    """
    from pm_core import storage_reclaim
    out = storage_reclaim.reclaim(pr_id=pr_id, dry_run=dry_run,
                                  reason="manual")
    if out.problem:
        click.echo(f"Nothing removed: {out.problem}.", err=True)
        raise SystemExit(1)
    removed = {str(d.path) for d in out.removed}
    failed = {str(d.path): err for d, err in out.failed}
    for p in out.plans:
        if p.held:
            if p.items or dry_run:
                click.echo(f"  keep {p.scratch}: {p.held}")
            continue
        for d in p.items:
            size = storage_reclaim.human_bytes(d.bytes) if d.bytes else "?"
            if dry_run:
                state = "would remove"
            elif str(d.path) in removed:
                state = "removed"
            else:
                state = f"FAILED ({failed.get(str(d.path), '?')})"
            click.echo(f"  {state} {d.kind} {d.path} ({size})")
    click.echo(out.summary())
    if out.failed:
        raise SystemExit(1)
