"""Load and parse Exercism exercises from aider's polyglot benchmark.

The exercises come from https://github.com/Aider-AI/polyglot-benchmark
and are cached locally under ~/.cache/pm-bench/exercises/.

Each exercise directory follows Exercism's standard layout:
    {language}/exercises/practice/{slug}/
        .docs/instructions.md          - problem description
        .meta/config.json              - metadata (solution/test/example files)
        .meta/example.{ext}            - reference solution (not always present)
        {starter_files}                - files to be edited
        {test_files}                   - unit test files
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from pm_core.paths import bench_cache_dir

REPO_URL = "https://github.com/Aider-AI/polyglot-benchmark.git"
LANGUAGES = ("cpp", "go", "java", "javascript", "python", "rust")


@dataclass
class Exercise:
    """A single benchmark exercise."""

    language: str
    slug: str
    description: str
    starter_code: dict[str, str]  # filename -> content
    reference_tests: dict[str, str]  # filename -> content
    path: Path = field(repr=False)

    @property
    def id(self) -> str:
        return f"{self.language}/{self.slug}"


def _repo_dir() -> Path:
    """Return the path to the cloned polyglot-benchmark repo."""
    return bench_cache_dir() / "polyglot-benchmark"


def sync_exercises(quiet: bool = False) -> Path:
    """Clone or update the polyglot-benchmark repo. Returns repo path."""
    repo = _repo_dir()

    if (repo / ".git").is_dir():
        # Pull latest
        if not quiet:
            print("Updating exercise cache ...")
        subprocess.run(
            ["git", "pull", "--ff-only", "-q"],
            cwd=repo,
            check=True,
            capture_output=quiet,
        )
    else:
        # Fresh clone
        if not quiet:
            print("Cloning polyglot-benchmark (first time — may take a moment) ...")
        repo.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", "--depth=1", "-q", REPO_URL, str(repo)],
            check=True,
            capture_output=quiet,
        )

    return repo


def list_languages() -> list[str]:
    """Return languages available in the cached exercise set.

    Only returns languages whose directories actually exist on disk.
    """
    repo = _repo_dir()
    if not repo.is_dir():
        return []
    return sorted(
        lang
        for lang in LANGUAGES
        if (repo / lang / "exercises" / "practice").is_dir()
    )


def _read_text(path: Path) -> str:
    """Read a file as UTF-8, returning empty string if missing."""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _parse_exercise(exercise_dir: Path, language: str) -> Exercise | None:
    """Parse a single exercise directory into an Exercise object."""
    slug = exercise_dir.name
    docs_dir = exercise_dir / ".docs"
    meta_dir = exercise_dir / ".meta"

    # Read problem description from .docs/instructions.md
    description = _read_text(docs_dir / "instructions.md")
    append = _read_text(docs_dir / "instructions.append.md")
    if append:
        description = description.rstrip() + "\n\n" + append

    if not description.strip():
        return None  # skip exercises without a description

    # Read .meta/config.json for file mappings
    config_path = meta_dir / "config.json"
    config = {}
    if config_path.is_file():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    files_cfg = config.get("files", {})

    # Starter code: files listed under "solution"
    solution_globs = files_cfg.get("solution", [])
    starter_code: dict[str, str] = {}
    for pattern in solution_globs:
        for match in exercise_dir.glob(pattern):
            if match.is_file():
                content = _read_text(match)
                starter_code[str(match.relative_to(exercise_dir))] = content

    # Test files: files listed under "test"
    test_globs = files_cfg.get("test", [])
    reference_tests: dict[str, str] = {}
    for pattern in test_globs:
        for match in exercise_dir.glob(pattern):
            if match.is_file():
                content = _read_text(match)
                reference_tests[str(match.relative_to(exercise_dir))] = content

    # Fallback: if config didn't list files, use heuristics
    if not starter_code:
        starter_code = _find_starter_files(exercise_dir, language)
    if not reference_tests:
        reference_tests = _find_test_files(exercise_dir, language)

    return Exercise(
        language=language,
        slug=slug,
        description=description,
        starter_code=starter_code,
        reference_tests=reference_tests,
        path=exercise_dir,
    )


def _find_starter_files(exercise_dir: Path, language: str) -> dict[str, str]:
    """Heuristic fallback: find starter code files by language convention."""
    patterns: dict[str, list[str]] = {
        "python": ["*.py"],
        "javascript": ["*.js"],
        "go": ["*.go"],
        "java": ["src/main/java/**/*.java"],
        "rust": ["src/**/*.rs"],
        "cpp": ["*.cpp", "*.h"],
    }
    skip_patterns = {"*_test.*", "*_test.go", "*.spec.*", "*Test.*", "*_test.cpp"}
    result: dict[str, str] = {}
    for pat in patterns.get(language, []):
        for match in exercise_dir.glob(pat):
            if match.is_file() and not match.name.startswith("."):
                rel = str(match.relative_to(exercise_dir))
                # Skip test files and hidden dirs
                if any(part.startswith(".") for part in match.parts):
                    continue
                if any(match.match(sp) for sp in skip_patterns):
                    continue
                result[rel] = _read_text(match)
    return result


def _find_test_files(exercise_dir: Path, language: str) -> dict[str, str]:
    """Heuristic fallback: find test files by language convention."""
    patterns: dict[str, list[str]] = {
        "python": ["*_test.py"],
        "javascript": ["*.spec.js"],
        "go": ["*_test.go", "cases_test.go"],
        "java": ["src/test/java/**/*.java"],
        "rust": ["tests/**/*.rs"],
        "cpp": ["*_test.cpp"],
    }
    result: dict[str, str] = {}
    for pat in patterns.get(language, []):
        for match in exercise_dir.glob(pat):
            if match.is_file():
                rel = str(match.relative_to(exercise_dir))
                result[rel] = _read_text(match)
    return result


def load_exercises(
    *,
    language: str | None = None,
    slug: str | None = None,
) -> list[Exercise]:
    """Load exercises from the local cache.

    Args:
        language: Filter to a single language (e.g. "python").
        slug: Filter to exercises whose slug contains this substring.

    Returns:
        List of Exercise objects, sorted by (language, slug).

    Raises:
        FileNotFoundError: If the exercise cache doesn't exist yet.
    """
    repo = _repo_dir()
    if not repo.is_dir():
        raise FileNotFoundError(
            "Exercise cache not found. Run `pm bench exercises` to download."
        )

    languages = [language] if language else list(LANGUAGES)
    exercises: list[Exercise] = []

    for lang in languages:
        practice_dir = repo / lang / "exercises" / "practice"
        if not practice_dir.is_dir():
            continue

        for exercise_dir in sorted(practice_dir.iterdir()):
            if not exercise_dir.is_dir() or exercise_dir.name.startswith("."):
                continue
            if slug and slug.lower() not in exercise_dir.name.lower():
                continue

            ex = _parse_exercise(exercise_dir, lang)
            if ex:
                exercises.append(ex)

    exercises.sort(key=lambda e: (e.language, e.slug))
    return exercises
