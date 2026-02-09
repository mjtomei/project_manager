"""Aider polyglot exercise loader.

Loads Exercism exercises from the aider polyglot-benchmark repo. Each exercise
has a problem description, starter code, and reference test suite.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

REPO_URL = "https://github.com/Aider-AI/polyglot-benchmark"
CACHE_DIR = Path.home() / ".cache" / "pm" / "polyglot-benchmark"

SUPPORTED_LANGUAGES = ("cpp", "go", "java", "javascript", "python", "rust")

# Maps language → patterns for finding exercise files within an exercise dir.
# Each entry: (starter_glob, test_glob, slug_to_filename_transform)
_LANG_PATTERNS: dict[str, dict] = {
    "python": {
        "starter": lambda slug, d: d / f"{slug.replace('-', '_')}.py",
        "tests": lambda slug, d: d / f"{slug.replace('-', '_')}_test.py",
    },
    "go": {
        "starter": lambda slug, d: d / f"{slug.replace('-', '_')}.go",
        "tests": lambda slug, d: next(d.glob("*_test.go"), None),
    },
    "rust": {
        "starter": lambda slug, d: d / "src" / "lib.rs",
        "tests": lambda slug, d: next((d / "tests").glob("*.rs"), None) if (d / "tests").is_dir() else None,
    },
    "javascript": {
        "starter": lambda slug, d: d / f"{slug}.js",
        "tests": lambda slug, d: d / f"{slug}.spec.js",
    },
    "cpp": {
        "starter": lambda slug, d: next(d.glob(f"*{slug.replace('-', '_')}*.cpp"), None),
        "tests": lambda slug, d: next(d.glob("*_test.cpp"), None),
    },
    "java": {
        "starter": lambda slug, d: _find_java_file(d / "src" / "main"),
        "tests": lambda slug, d: _find_java_file(d / "src" / "test"),
    },
}


def _find_java_file(base: Path) -> Path | None:
    if not base.is_dir():
        return None
    java_files = list(base.rglob("*.java"))
    return java_files[0] if java_files else None


@dataclass
class Exercise:
    """A single benchmark exercise."""

    language: str
    slug: str
    description: str
    starter_code: str
    reference_tests: str
    exercise_dir: Path  # root dir of this exercise on disk


def ensure_repo(cache_dir: Path = CACHE_DIR) -> Path:
    """Clone or update the polyglot-benchmark repo."""
    if (cache_dir / ".git").is_dir():
        subprocess.run(
            ["git", "pull", "--ff-only"],
            cwd=cache_dir,
            capture_output=True,
            timeout=60,
        )
        return cache_dir

    cache_dir.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", "--depth=1", REPO_URL, str(cache_dir)],
        check=True,
        capture_output=True,
        timeout=120,
    )
    return cache_dir


def load_exercises(
    *,
    languages: list[str] | None = None,
    slugs: list[str] | None = None,
    cache_dir: Path = CACHE_DIR,
) -> list[Exercise]:
    """Load exercises from the polyglot-benchmark repo.

    Args:
        languages: Filter to these languages (default: all supported).
        slugs: Filter to exercises matching these slug names.
        cache_dir: Override the cache directory (useful for testing).
    """
    repo = ensure_repo(cache_dir)
    langs = languages or list(SUPPORTED_LANGUAGES)
    exercises: list[Exercise] = []

    for lang in langs:
        if lang not in SUPPORTED_LANGUAGES:
            continue
        practice_dir = repo / lang / "exercises" / "practice"
        if not practice_dir.is_dir():
            continue

        patterns = _LANG_PATTERNS[lang]

        for ex_dir in sorted(practice_dir.iterdir()):
            if not ex_dir.is_dir() or ex_dir.name.startswith("."):
                continue

            slug = ex_dir.name
            if slugs and slug not in slugs:
                continue

            # Read description
            desc_path = ex_dir / ".docs" / "instructions.md"
            if not desc_path.is_file():
                continue
            description = desc_path.read_text()

            # Check for appended instructions
            append_path = ex_dir / ".docs" / "instructions.append.md"
            if append_path.is_file():
                description += "\n\n" + append_path.read_text()

            # Read starter code
            starter_path = patterns["starter"](slug, ex_dir)
            if starter_path is None or not starter_path.is_file():
                continue
            starter_code = starter_path.read_text()

            # Read reference tests
            test_path = patterns["tests"](slug, ex_dir)
            if test_path is None or not test_path.is_file():
                continue
            reference_tests = test_path.read_text()

            exercises.append(Exercise(
                language=lang,
                slug=slug,
                description=description,
                starter_code=starter_code,
                reference_tests=reference_tests,
                exercise_dir=ex_dir,
            ))

    return exercises
