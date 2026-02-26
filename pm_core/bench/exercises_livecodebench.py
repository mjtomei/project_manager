"""Load LiveCodeBench competitive programming problems from HuggingFace.

Problems come from LeetCode, AtCoder, and Codeforces — continuously updated
post-training-cutoff to reduce contamination.  Uses stdin/stdout evaluation
rather than unit-test files.

Dataset: https://huggingface.co/datasets/livecodebench/code_generation_lite
Cache:   ~/.cache/pm-bench/livecodebench/
"""

from __future__ import annotations

import base64
import json
import pickle
import urllib.request
import zlib
from pathlib import Path

from pm_core.bench.exercises import Exercise
from pm_core.paths import bench_cache_dir

# HuggingFace raw file URLs for each version chunk.
_HF_BASE = (
    "https://huggingface.co/datasets/livecodebench/code_generation_lite"
    "/resolve/main"
)

# Each file contains problems added in that version.
_JSONL_FILES = [
    "test.jsonl",   # v1: ~400 problems
    "test2.jsonl",  # v2: ~111 problems
    "test3.jsonl",  # v3: ~101 problems
    "test4.jsonl",  # v4: ~101 problems
    "test5.jsonl",  # v5: ~167 problems
    "test6.jsonl",  # v6: latest additions
]

DIFFICULTIES = ("easy", "medium", "hard")


def _cache_dir() -> Path:
    """Return the LiveCodeBench cache directory."""
    return bench_cache_dir() / "livecodebench"


def sync_exercises(quiet: bool = False) -> Path:
    """Download JSONL files from HuggingFace if not already cached.

    Returns the cache directory path.
    """
    cache = _cache_dir()
    cache.mkdir(parents=True, exist_ok=True)

    for filename in _JSONL_FILES:
        dest = cache / filename
        if dest.is_file():
            continue

        url = f"{_HF_BASE}/{filename}"
        if not quiet:
            print(f"Downloading {filename} ...")

        try:
            urllib.request.urlretrieve(url, dest)
        except Exception as exc:
            # Clean up partial download
            if dest.exists():
                dest.unlink()
            raise RuntimeError(
                f"Failed to download {url}: {exc}"
            ) from exc

    return cache


def _parse_test_cases(raw: str) -> list[dict]:
    """Parse test cases from a JSON string, handling compressed format.

    LiveCodeBench stores private_test_cases either as plain JSON or as
    base64-encoded, zlib-compressed, pickled JSON.
    """
    if not raw:
        return []

    # Try plain JSON first
    try:
        cases = json.loads(raw)
        if isinstance(cases, list):
            return cases
    except (json.JSONDecodeError, TypeError):
        pass

    # Try compressed format: base64 → zlib → pickle → JSON string
    try:
        decoded = base64.b64decode(raw)
        decompressed = zlib.decompress(decoded)
        unpickled = pickle.loads(decompressed)  # noqa: S301
        cases = json.loads(unpickled)
        if isinstance(cases, list):
            return cases
    except Exception:
        pass

    return []


def _normalize_difficulty(raw: str) -> str:
    """Normalize difficulty strings from different platforms."""
    d = raw.strip().lower()
    # Map platform-specific difficulty labels
    mapping = {
        "easy": "easy",
        "medium": "medium",
        "hard": "hard",
        # AtCoder / Codeforces difficulty labels
        "a": "easy",
        "b": "easy",
        "c": "medium",
        "d": "medium",
        "e": "hard",
        "f": "hard",
        "q1": "easy",
        "q2": "easy",
        "q3": "medium",
        "q4": "hard",
    }
    return mapping.get(d, "medium")


def _parse_problem(row: dict) -> Exercise | None:
    """Parse a single JSONL row into an Exercise object."""
    question_content = row.get("question_content", "")
    if not question_content or not question_content.strip():
        return None

    question_id = row.get("question_id", "")
    title = row.get("question_title", question_id)
    slug = title.strip().lower().replace(" ", "-")
    # Remove non-alphanumeric chars except hyphens
    slug = "".join(c for c in slug if c.isalnum() or c == "-")
    slug = slug.strip("-") or question_id

    # Starter code — competitive programming problems often have empty starter
    starter = row.get("starter_code", "")
    starter_code: dict[str, str] = {}
    if starter and starter.strip():
        starter_code["solution.py"] = starter

    # Parse test cases from both public and private
    public_cases = _parse_test_cases(row.get("public_test_cases", ""))
    private_cases = _parse_test_cases(row.get("private_test_cases", ""))
    all_cases = public_cases + private_cases

    if not all_cases:
        return None

    # Store test cases as JSON in reference_tests under a synthetic key.
    # Each test case has {"input": ..., "output": ..., "testtype": ...}.
    reference_tests = {
        "_stdin_stdout_tests.json": json.dumps(all_cases),
    }

    # Difficulty normalization
    raw_difficulty = row.get("difficulty", "medium")
    difficulty = _normalize_difficulty(raw_difficulty)

    # Platform info
    platform = row.get("platform", "unknown").lower()

    # Build description with metadata header
    description = question_content

    # Cache dir for this problem (just use the cache root — no per-exercise dir needed)
    cache = _cache_dir()

    return Exercise(
        language="python",
        slug=slug,
        description=description,
        starter_code=starter_code,
        reference_tests=reference_tests,
        path=cache,  # No per-exercise scaffold needed
        source="livecodebench",
        difficulty=difficulty,
        platform=platform,
    )


def load_exercises(
    *,
    difficulty: str | None = None,
) -> list[Exercise]:
    """Load LiveCodeBench exercises from the local cache.

    Args:
        difficulty: Filter to easy/medium/hard.

    Raises:
        FileNotFoundError: If the cache doesn't exist yet.
    """
    cache = _cache_dir()
    if not cache.is_dir() or not any(cache.glob("*.jsonl")):
        raise FileNotFoundError(
            "LiveCodeBench cache not found. "
            "Run `pm bench exercises --source livecodebench` to download."
        )

    exercises: list[Exercise] = []
    seen_ids: set[str] = set()

    for filename in _JSONL_FILES:
        path = cache / filename
        if not path.is_file():
            continue

        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue

            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue

            # Deduplicate by question_id
            qid = row.get("question_id", "")
            if qid in seen_ids:
                continue
            seen_ids.add(qid)

            ex = _parse_problem(row)
            if ex is None:
                continue

            # Apply difficulty filter
            if difficulty and ex.difficulty != difficulty.lower():
                continue

            exercises.append(ex)

    exercises.sort(key=lambda e: e.slug)
    return exercises
