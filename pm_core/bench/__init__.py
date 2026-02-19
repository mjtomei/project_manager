"""Benchmark module — multi-candidate code generation with tournament selection.

Uses local LLM inference via OpenAI-compatible APIs to generate test cases and
candidate solutions, then selects the best candidate via test pass rate.
"""

from pm_core.bench.runner import (
    Backend,
    GenerationResult,
    RequestStats,
    Runner,
    chat_completion,
    detect_backend,
    generate_multiple,
    list_models,
)
from pm_core.bench.exercises import (
    Exercise,
    list_languages,
    load_exercises,
    sync_exercises,
)

__all__ = [
    "Backend",
    "Exercise",
    "GenerationResult",
    "RequestStats",
    "Runner",
    "chat_completion",
    "detect_backend",
    "generate_multiple",
    "list_languages",
    "list_models",
    "load_exercises",
    "sync_exercises",
]
