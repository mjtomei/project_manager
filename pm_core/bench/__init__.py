"""Bench module — local LLM benchmarking via OpenAI-compatible APIs."""

from pm_core.bench.runner import (
    Backend,
    RequestStats,
    GenerationResult,
    Runner,
    detect_backend,
    list_models,
    chat_completion,
    generate_multiple,
)

__all__ = [
    "Backend",
    "RequestStats",
    "GenerationResult",
    "Runner",
    "detect_backend",
    "list_models",
    "chat_completion",
    "generate_multiple",
]
