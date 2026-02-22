"""Cluster commands for the pm CLI.

Registers the ``cluster`` group and subcommands for codebase analysis.
"""

import os
from pathlib import Path

import click

from pm_core import store
from pm_core import tmux as tmux_mod
from pm_core.claude_launcher import find_claude, launch_claude, clear_session
from pm_core.prompt_gen import tui_section

from pm_core.cli import cli
from pm_core.cli.helpers import (
    _get_pm_session,
    _resolve_repo_dir,
    save_and_push,
    state_root,
    trigger_tui_refresh,
)


def _run_clustering(
    repo_root: Path,
    weights: dict[str, float],
    threshold: float = 0.15,
    max_commits: int = 500,
    verbose: bool = True,
) -> tuple[list, list, dict]:
    """Extract chunks, partition, cluster, and return (clusters, chunks, chunk_map).

    When *verbose* is True, prints per-partition progress lines.
    """
    from pm_core.cluster import extract_chunks, compute_edges, agglomerative_cluster, pre_partition
    from pm_core.cluster.cluster_graph import Cluster

    click.echo(f"Extracting chunks from {repo_root} ...")
    chunks = extract_chunks(repo_root)
    click.echo(f"  {len(chunks)} chunks extracted")

    click.echo("Pre-partitioning ...")
    partitions = pre_partition(chunks)
    click.echo(f"  {len(partitions)} partitions: {', '.join(partitions.keys())}")

    clusters = []
    cluster_id = 0
    for part_name, part_chunks in partitions.items():
        file_count = sum(1 for c in part_chunks if c.kind in ("function", "class", "file"))
        if file_count <= 3:
            cluster_id += 1
            clusters.append(Cluster(
                id=str(cluster_id),
                chunk_ids={c.id for c in part_chunks if c.kind in ("function", "class", "file")},
                name=part_name,
            ))
            if verbose:
                click.echo(f"  [{part_name}] {file_count} chunks → 1 cluster (small partition)")
            continue

        if verbose:
            click.echo(f"  [{part_name}] computing edges for {len(part_chunks)} chunks ...")
        part_edges = compute_edges(part_chunks, weights=weights, repo_root=repo_root, max_commits=max_commits)
        part_clusters = agglomerative_cluster(part_chunks, part_edges, threshold=threshold)
        for c in part_clusters:
            cluster_id += 1
            c.id = str(cluster_id)
            c.name = f"{part_name}: {c.name}" if c.name else part_name
        clusters.extend(part_clusters)
        if verbose:
            click.echo(f"  [{part_name}] {len(part_edges)} edges → {len(part_clusters)} clusters")

    click.echo(f"  {len(clusters)} clusters found")

    chunk_map = {c.id: c for c in chunks}
    return clusters, chunks, chunk_map


@cli.group()
def cluster():
    """Analyze codebase structure and discover feature clusters."""
    pass


@cluster.command("auto")
@click.option("--threshold", default=0.15, type=float, help="Merge threshold (0.0–1.0)")
@click.option("--max-commits", default=500, type=int, help="Max commits for co-change analysis")
@click.option("--weights", default=None, type=str,
              help="Metric weights: structural=0.2,semantic=0.3,cochange=0.2,callgraph=0.3")
@click.option("--output", "output_fmt", default="text", type=click.Choice(["plan", "json", "text"]),
              help="Output format")
def cluster_auto(threshold, max_commits, weights, output_fmt):
    """Discover feature clusters automatically."""
    from pm_core.cluster import clusters_to_plan_markdown, clusters_to_json, clusters_to_text

    root = state_root()
    data = store.load(root)
    repo_root = _resolve_repo_dir(root, data)

    # Parse weights
    w = {"structural": 0.2, "semantic": 0.3, "cochange": 0.2, "callgraph": 0.3}
    if weights:
        for pair in weights.split(","):
            k, v = pair.split("=")
            w[k.strip()] = float(v.strip())

    clusters, chunks, chunk_map = _run_clustering(
        repo_root, weights=w, threshold=threshold, max_commits=max_commits,
    )

    if output_fmt == "text":
        click.echo("")
        click.echo(clusters_to_text(clusters, chunk_map))
    elif output_fmt == "json":
        click.echo(clusters_to_json(clusters, chunk_map))
    elif output_fmt == "plan":
        md = clusters_to_plan_markdown(clusters, chunk_map)
        existing_ids = {p["id"] for p in (data.get("plans") or [])}
        plan_id = store.generate_plan_id(f"cluster-explore", existing_ids)
        plan_name = f"cluster-{plan_id}"
        plan_file = f"plans/{plan_name}.md"
        plan_path = root / plan_file
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(md)

        plans = data.setdefault("plans", [])
        plans.append({"id": plan_id, "name": plan_name, "file": plan_file, "status": "draft"})
        save_and_push(data, root, f"pm: cluster auto → {plan_id}")
        trigger_tui_refresh()

        click.echo(f"Plan written to {plan_path}")
        click.echo(f"  Plan ID: {plan_id}")
        click.echo(f"  Load PRs with: pm plan load {plan_id}")


@cluster.command("explore")
@click.option("--bridged", is_flag=True, default=False,
              help="Launch in a bridge pane (for agent orchestration)")
@click.option("--fresh", is_flag=True, default=False, help="Start a fresh session (don't resume)")
def cluster_explore(bridged, fresh):
    """Interactively explore code clusters with Claude."""
    import tempfile
    from pm_core.cluster import clusters_to_text

    root = state_root()
    data = store.load(root)
    repo_root = _resolve_repo_dir(root, data)

    w = {"structural": 0.25, "semantic": 0.25, "cochange": 0.25, "callgraph": 0.25}
    clusters, chunks, chunk_map = _run_clustering(
        repo_root, weights=w, verbose=False,
    )

    summary = clusters_to_text(clusters, chunk_map)

    # Write summary to temp file for Claude context
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, prefix='pm-cluster-') as f:
        f.write(summary)
        f.write("\n\n--- Cluster Data ---\n")
        f.write(f"Total chunks: {len(chunks)}\n")
        f.write(f"Clusters: {len(clusters)}\n")
        f.write(f"Threshold: 0.15\n")
        f.write(f"Weights: {w}\n")
        tmp_path = f.name

    prompt = (
        f"Your goal: Help the user refine code clusters into a plan they're happy with, "
        f"then create it using `pm cluster auto --output plan`.\n\n"
        f"This session is managed by `pm` (project manager for Claude Code). You have access "
        f"to the `pm` CLI tool — run `pm help` to see available commands.\n\n"
        f"I've analyzed the codebase and found {len(clusters)} code clusters. "
        f"The cluster summary is in {tmp_path}. Read it to understand the current groupings.\n\n"
        f"Discuss the clusters with the user. You can suggest:\n"
        f"- Adjusting the threshold (current: 0.15, higher = fewer larger clusters)\n"
        f"- Changing metric weights (structural, semantic, cochange, callgraph)\n"
        f"- Splitting or merging specific clusters\n\n"
        f"Re-run `pm cluster auto` with different parameters to iterate. When the user "
        f"is happy, run `pm cluster auto --output plan` to create the plan, then "
        f"`pm plan load` to create the PRs.\n"
    )

    # Add TUI interaction section if in a pm session
    pm_session = _get_pm_session()
    if pm_session:
        prompt += tui_section(pm_session)

    claude = find_claude()
    if not claude:
        click.echo("Claude CLI not found. Install it to use interactive explore.", err=True)
        click.echo(f"\nCluster summary written to: {tmp_path}")
        raise SystemExit(1)

    if bridged:
        import time
        from pm_core.claude_launcher import launch_bridge_in_tmux

        if not tmux_mod.in_tmux():
            click.echo("--bridged requires running inside tmux.", err=True)
            raise SystemExit(1)

        session_name = tmux_mod.get_session_name()

        socket_path = launch_bridge_in_tmux(prompt, cwd=str(repo_root), session_name=session_name)

        # Wait for socket to appear
        for _ in range(50):
            if os.path.exists(socket_path):
                break
            time.sleep(0.1)
        else:
            click.echo(f"Timed out waiting for bridge socket: {socket_path}", err=True)
            raise SystemExit(1)

        click.echo(f"Bridge socket: {socket_path}")
        return

    session_key = "cluster:explore"
    if fresh:
        clear_session(root, session_key)
    launch_claude(prompt, cwd=str(repo_root), session_key=session_key, pm_root=root, resume=not fresh)
