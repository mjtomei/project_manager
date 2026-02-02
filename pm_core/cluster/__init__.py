"""Code clustering module — discover feature groups from codebase structure."""

from pm_core.cluster.chunks import Chunk, extract_chunks
from pm_core.cluster.metrics import compute_edges
from pm_core.cluster.cluster_graph import Cluster, agglomerative_cluster
from pm_core.cluster.partition import pre_partition, classify_file
from pm_core.cluster.output import clusters_to_plan_markdown, clusters_to_json, clusters_to_text

__all__ = [
    "Chunk",
    "extract_chunks",
    "compute_edges",
    "Cluster",
    "agglomerative_cluster",
    "pre_partition",
    "classify_file",
    "clusters_to_plan_markdown",
    "clusters_to_json",
    "clusters_to_text",
]
