"""Benchmark module — multi-candidate test-driven code generation."""

from pm_core.bench.runner import generate, list_models
from pm_core.bench.test_gen import generate_tests, validate_tests, deduplicate_tests

__all__ = [
    "generate",
    "list_models",
    "generate_tests",
    "validate_tests",
    "deduplicate_tests",
]
