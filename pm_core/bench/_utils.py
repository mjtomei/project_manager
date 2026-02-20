"""Shared utilities for the bench module."""

from __future__ import annotations


def extract_code(text: str) -> str:
    """Extract code from a model response, stripping markdown fences if present."""
    lines = text.strip().split("\n")
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
        for i in range(len(lines) - 1, -1, -1):
            if lines[i].strip() == "```":
                lines = lines[:i]
                break
    return "\n".join(lines)
