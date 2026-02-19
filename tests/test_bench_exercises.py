"""Tests for pm_core.bench.exercises — exercise parsing and loading."""

import json
from pathlib import Path

import pytest

from pm_core.bench.exercises import (
    Exercise,
    _parse_exercise,
    _find_starter_files,
    _find_test_files,
    load_exercises,
    list_languages,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_exercise(root: Path, language: str, slug: str, *, config: dict | None = None,
                   instructions: str = "# Problem\nDo the thing.",
                   append: str = "",
                   starter: dict[str, str] | None = None,
                   tests: dict[str, str] | None = None) -> Path:
    """Create a fake exercise directory."""
    ex_dir = root / language / "exercises" / "practice" / slug
    docs = ex_dir / ".docs"
    meta = ex_dir / ".meta"
    docs.mkdir(parents=True, exist_ok=True)
    meta.mkdir(parents=True, exist_ok=True)

    if instructions:
        (docs / "instructions.md").write_text(instructions)
    if append:
        (docs / "instructions.append.md").write_text(append)

    if config is not None:
        (meta / "config.json").write_text(json.dumps(config))

    if starter:
        for name, content in starter.items():
            p = ex_dir / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
    if tests:
        for name, content in tests.items():
            p = ex_dir / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)

    return ex_dir


@pytest.fixture
def exercise_tree(tmp_path):
    """Build a mini exercise repo with two languages."""
    _make_exercise(
        tmp_path, "python", "hello-world",
        config={"files": {"solution": ["hello_world.py"], "test": ["hello_world_test.py"]}},
        starter={"hello_world.py": "def hello():\n    pass\n"},
        tests={"hello_world_test.py": "def test_hello():\n    assert hello() == 'Hello, World!'\n"},
    )

    _make_exercise(
        tmp_path, "python", "two-fer",
        starter={"two_fer.py": "def two_fer(name='you'):\n    pass\n"},
        tests={"two_fer_test.py": "def test_two_fer():\n    assert two_fer() == 'One for you, one for me.'\n"},
    )

    _make_exercise(
        tmp_path, "go", "leap",
        config={"files": {"solution": ["leap.go"], "test": ["leap_test.go"]}},
        starter={"leap.go": "package leap\n\nfunc IsLeapYear(year int) bool {\n\treturn false\n}\n"},
        tests={"leap_test.go": "package leap\n\nimport \"testing\"\n\nfunc TestLeapYear(t *testing.T) {}\n"},
    )

    _make_exercise(
        tmp_path, "python", "clock",
        config={"files": {"solution": ["clock.py"], "test": ["clock_test.py"]}},
        instructions="# Clock\nImplement a clock.",
        append="## Additional\nHandle wraparound.",
        starter={"clock.py": "class Clock:\n    pass\n"},
        tests={"clock_test.py": "def test_clock():\n    pass\n"},
    )

    # Exercise with no description (should be skipped)
    ex_empty = tmp_path / "python" / "exercises" / "practice" / "no-desc"
    (ex_empty / ".docs").mkdir(parents=True, exist_ok=True)
    (ex_empty / ".meta").mkdir(parents=True, exist_ok=True)

    return tmp_path


# ---------------------------------------------------------------------------
# Tests — _parse_exercise
# ---------------------------------------------------------------------------

class TestParseExercise:
    def test_basic_parse(self, exercise_tree):
        ex_dir = exercise_tree / "python" / "exercises" / "practice" / "hello-world"
        ex = _parse_exercise(ex_dir, "python")
        assert ex is not None
        assert ex.language == "python"
        assert ex.slug == "hello-world"
        assert ex.id == "python/hello-world"
        assert "hello_world.py" in ex.starter_code
        assert "hello_world_test.py" in ex.reference_tests
        assert "# Problem" in ex.description

    def test_appended_instructions(self, exercise_tree):
        ex_dir = exercise_tree / "python" / "exercises" / "practice" / "clock"
        ex = _parse_exercise(ex_dir, "python")
        assert ex is not None
        assert "# Clock" in ex.description
        assert "Handle wraparound" in ex.description

    def test_no_description_returns_none(self, exercise_tree):
        ex_dir = exercise_tree / "python" / "exercises" / "practice" / "no-desc"
        assert _parse_exercise(ex_dir, "python") is None

    def test_heuristic_fallback(self, exercise_tree):
        ex_dir = exercise_tree / "python" / "exercises" / "practice" / "two-fer"
        ex = _parse_exercise(ex_dir, "python")
        assert ex is not None
        assert "two_fer.py" in ex.starter_code
        assert "two_fer_test.py" in ex.reference_tests


# ---------------------------------------------------------------------------
# Tests — load_exercises
# ---------------------------------------------------------------------------

class TestLoadExercises:
    def test_load_all(self, exercise_tree, monkeypatch):
        monkeypatch.setattr("pm_core.bench.exercises._repo_dir", lambda: exercise_tree)
        exercises = load_exercises()
        assert len(exercises) == 4  # no-desc skipped

    def test_filter_by_language(self, exercise_tree, monkeypatch):
        monkeypatch.setattr("pm_core.bench.exercises._repo_dir", lambda: exercise_tree)
        exercises = load_exercises(language="go")
        assert len(exercises) == 1
        assert exercises[0].slug == "leap"

    def test_filter_by_slug(self, exercise_tree, monkeypatch):
        monkeypatch.setattr("pm_core.bench.exercises._repo_dir", lambda: exercise_tree)
        exercises = load_exercises(slug="hello")
        assert len(exercises) == 1
        assert exercises[0].slug == "hello-world"

    def test_no_cache_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr("pm_core.bench.exercises._repo_dir", lambda: tmp_path / "nonexistent")
        with pytest.raises(FileNotFoundError):
            load_exercises()

    def test_sorted_output(self, exercise_tree, monkeypatch):
        monkeypatch.setattr("pm_core.bench.exercises._repo_dir", lambda: exercise_tree)
        exercises = load_exercises()
        ids = [e.id for e in exercises]
        assert ids == sorted(ids)


# ---------------------------------------------------------------------------
# Tests — list_languages
# ---------------------------------------------------------------------------

class TestListLanguages:
    def test_list_languages(self, exercise_tree, monkeypatch):
        monkeypatch.setattr("pm_core.bench.exercises._repo_dir", lambda: exercise_tree)
        langs = list_languages()
        assert "python" in langs
        assert "go" in langs
        assert "rust" not in langs

    def test_no_cache_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr("pm_core.bench.exercises._repo_dir", lambda: tmp_path / "nope")
        assert list_languages() == []


# ---------------------------------------------------------------------------
# Tests — heuristic finders
# ---------------------------------------------------------------------------

class TestHeuristicFinders:
    def test_find_starter_python(self, tmp_path):
        ex_dir = tmp_path / "exercise"
        ex_dir.mkdir()
        (ex_dir / "solution.py").write_text("pass")
        (ex_dir / "solution_test.py").write_text("test")
        result = _find_starter_files(ex_dir, "python")
        assert "solution.py" in result
        assert "solution_test.py" not in result

    def test_find_test_python(self, tmp_path):
        ex_dir = tmp_path / "exercise"
        ex_dir.mkdir()
        (ex_dir / "solution.py").write_text("pass")
        (ex_dir / "solution_test.py").write_text("test")
        result = _find_test_files(ex_dir, "python")
        assert "solution_test.py" in result
        assert "solution.py" not in result


# ---------------------------------------------------------------------------
# Tests — Exercise dataclass
# ---------------------------------------------------------------------------

class TestExerciseDataclass:
    def test_id_property(self):
        ex = Exercise(
            language="python",
            slug="hello-world",
            description="desc",
            starter_code={"hello.py": "pass"},
            reference_tests={"test.py": "assert True"},
            path=Path("/tmp/fake"),
        )
        assert ex.id == "python/hello-world"
