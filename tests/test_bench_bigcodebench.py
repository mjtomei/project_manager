"""Tests for pm_core.bench.exercises_bigcodebench — BigCodeBench loader."""

import json
from pathlib import Path

import pytest

from pm_core.bench.exercises_bigcodebench import (
    _create_scaffolds,
    _parse_task,
    download_dataset,
    extract_libs,
    get_all_required_libs,
    load_bigcodebench_exercises,
)


# ---------------------------------------------------------------------------
# Sample task data
# ---------------------------------------------------------------------------

def _sample_task(task_num: int = 0, *, entry_point: str = "task_func",
                 libs: str = "pandas, numpy") -> dict:
    """Create a synthetic BigCodeBench task dict."""
    return {
        "task_id": f"BigCodeBench/{task_num}",
        "complete_prompt": (
            f"def {entry_point}(data):\n"
            f'    """Process the data and return results."""\n'
        ),
        "instruct_prompt": (
            f"Write a function that processes data using pandas.\n"
            f"The function should accept a list and return a DataFrame."
        ),
        "canonical_solution": f"    return pd.DataFrame(data)\n",
        "test": (
            "import unittest\n"
            f"from {entry_point} import {entry_point}\n\n"
            "class TestCases(unittest.TestCase):\n"
            "    def test_basic(self):\n"
            f"        result = {entry_point}([1, 2, 3])\n"
            "        self.assertIsNotNone(result)\n"
        ),
        "entry_point": entry_point,
        "libs": libs,
    }


def _make_cache(tmp_path: Path, tasks: list[dict], *, hard: bool = False) -> Path:
    """Write a fake cached dataset JSON and create scaffolds."""
    cache_dir = tmp_path / "bigcodebench"
    cache_dir.mkdir(parents=True, exist_ok=True)

    suffix = "hard" if hard else "full"
    cache_file = cache_dir / f"bigcodebench_{suffix}_v0.1.4.json"
    cache_file.write_text(json.dumps(tasks))

    _create_scaffolds(tasks, cache_dir)
    return cache_dir


@pytest.fixture
def sample_tasks():
    """A small set of synthetic tasks."""
    return [
        _sample_task(0, entry_point="task_func", libs="pandas, numpy"),
        _sample_task(13, entry_point="process_data", libs="pandas"),
        _sample_task(42, entry_point="analyze", libs="matplotlib, scipy"),
    ]


@pytest.fixture
def cached_full(tmp_path, sample_tasks):
    """Cache dir with a full dataset."""
    return _make_cache(tmp_path, sample_tasks)


@pytest.fixture
def cached_hard(tmp_path):
    """Cache dir with a hard dataset."""
    tasks = [_sample_task(13, entry_point="process_data", libs="pandas")]
    return _make_cache(tmp_path, tasks, hard=True)


# ---------------------------------------------------------------------------
# Tests — _parse_task
# ---------------------------------------------------------------------------

class TestParseTask:
    def test_instruct_mode(self, tmp_path):
        task = _sample_task(7, entry_point="my_func")
        scaffolds = tmp_path / "scaffolds"
        ex = _parse_task(task, "instruct", scaffolds)

        assert ex.language == "python"
        assert ex.slug == "bcb-7"
        assert ex.id == "python/bcb-7"
        assert "processes data" in ex.description
        assert "`my_func`" in ex.description
        assert "my_func.py" in ex.starter_code
        assert ex.starter_code["my_func.py"] == ""

    def test_complete_mode(self, tmp_path):
        task = _sample_task(7, entry_point="my_func")
        scaffolds = tmp_path / "scaffolds"
        ex = _parse_task(task, "complete", scaffolds)

        assert "def my_func(data):" in ex.description
        # Complete mode should NOT append the "define a function" hint
        assert "Define a function" not in ex.description

    def test_reference_tests_mapping(self, tmp_path):
        task = _sample_task(7)
        scaffolds = tmp_path / "scaffolds"
        ex = _parse_task(task, "instruct", scaffolds)

        # Test file key matches executor's test_file config for this slug
        assert "bcb_7_test.py" in ex.reference_tests
        assert "import unittest" in ex.reference_tests["bcb_7_test.py"]

    def test_scaffold_path(self, tmp_path):
        task = _sample_task(7)
        scaffolds = tmp_path / "scaffolds"
        ex = _parse_task(task, "instruct", scaffolds)

        assert ex.path == scaffolds / "bcb-7"

    def test_entry_point_in_solution_file(self, tmp_path):
        task = _sample_task(0, entry_point="custom_entry")
        scaffolds = tmp_path / "scaffolds"
        ex = _parse_task(task, "instruct", scaffolds)

        assert "custom_entry.py" in ex.starter_code

    def test_default_entry_point(self, tmp_path):
        task = _sample_task(0)
        del task["entry_point"]  # missing entry_point
        scaffolds = tmp_path / "scaffolds"
        ex = _parse_task(task, "instruct", scaffolds)

        assert "task_func.py" in ex.starter_code


# ---------------------------------------------------------------------------
# Tests — _create_scaffolds
# ---------------------------------------------------------------------------

class TestCreateScaffolds:
    def test_scaffold_directories(self, tmp_path):
        tasks = [_sample_task(0), _sample_task(13)]
        _create_scaffolds(tasks, tmp_path)

        assert (tmp_path / "scaffolds" / "bcb-0").is_dir()
        assert (tmp_path / "scaffolds" / "bcb-13").is_dir()

    def test_scaffold_test_file(self, tmp_path):
        tasks = [_sample_task(5)]
        _create_scaffolds(tasks, tmp_path)

        test_file = tmp_path / "scaffolds" / "bcb-5" / "bcb_5_test.py"
        assert test_file.is_file()
        content = test_file.read_text()
        assert "import unittest" in content

    def test_idempotent(self, tmp_path):
        tasks = [_sample_task(0)]
        _create_scaffolds(tasks, tmp_path)
        _create_scaffolds(tasks, tmp_path)  # should not error

        assert (tmp_path / "scaffolds" / "bcb-0" / "bcb_0_test.py").is_file()


# ---------------------------------------------------------------------------
# Tests — load_bigcodebench_exercises
# ---------------------------------------------------------------------------

class TestLoadExercises:
    def test_load_full(self, cached_full, monkeypatch):
        monkeypatch.setattr(
            "pm_core.bench.exercises_bigcodebench._cache_dir", lambda: cached_full
        )
        exercises = load_bigcodebench_exercises()
        assert len(exercises) == 3

    def test_load_hard(self, cached_hard, monkeypatch):
        monkeypatch.setattr(
            "pm_core.bench.exercises_bigcodebench._cache_dir", lambda: cached_hard
        )
        exercises = load_bigcodebench_exercises(hard_only=True)
        assert len(exercises) == 1
        assert exercises[0].slug == "bcb-13"

    def test_filter_by_slug(self, cached_full, monkeypatch):
        monkeypatch.setattr(
            "pm_core.bench.exercises_bigcodebench._cache_dir", lambda: cached_full
        )
        exercises = load_bigcodebench_exercises(slug="42")
        assert len(exercises) == 1
        assert exercises[0].slug == "bcb-42"

    def test_sorted_output(self, cached_full, monkeypatch):
        monkeypatch.setattr(
            "pm_core.bench.exercises_bigcodebench._cache_dir", lambda: cached_full
        )
        exercises = load_bigcodebench_exercises()
        slugs = [e.slug for e in exercises]
        assert slugs == sorted(slugs)

    def test_no_cache_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "pm_core.bench.exercises_bigcodebench._cache_dir",
            lambda: tmp_path / "nonexistent",
        )
        with pytest.raises(FileNotFoundError, match="BigCodeBench full cache not found"):
            load_bigcodebench_exercises()

    def test_instruct_mode_default(self, cached_full, monkeypatch):
        monkeypatch.setattr(
            "pm_core.bench.exercises_bigcodebench._cache_dir", lambda: cached_full
        )
        exercises = load_bigcodebench_exercises(mode="instruct")
        # Instruct mode: description is NL, includes function name hint
        assert "processes data" in exercises[0].description

    def test_complete_mode(self, cached_full, monkeypatch):
        monkeypatch.setattr(
            "pm_core.bench.exercises_bigcodebench._cache_dir", lambda: cached_full
        )
        exercises = load_bigcodebench_exercises(mode="complete")
        # Complete mode: description is function signature
        assert "def task_func" in exercises[0].description

    def test_all_exercises_are_python(self, cached_full, monkeypatch):
        monkeypatch.setattr(
            "pm_core.bench.exercises_bigcodebench._cache_dir", lambda: cached_full
        )
        exercises = load_bigcodebench_exercises()
        assert all(e.language == "python" for e in exercises)


# ---------------------------------------------------------------------------
# Tests — extract_libs / get_all_required_libs
# ---------------------------------------------------------------------------

class TestLibsExtraction:
    def test_extract_libs_basic(self):
        task = {"libs": "pandas, numpy, matplotlib"}
        assert extract_libs(task) == ["pandas", "numpy", "matplotlib"]

    def test_extract_libs_single(self):
        task = {"libs": "pandas"}
        assert extract_libs(task) == ["pandas"]

    def test_extract_libs_empty(self):
        assert extract_libs({"libs": ""}) == []
        assert extract_libs({}) == []

    def test_extract_libs_whitespace(self):
        task = {"libs": " pandas , numpy "}
        assert extract_libs(task) == ["pandas", "numpy"]

    def test_get_all_required_libs(self, cached_full, monkeypatch):
        monkeypatch.setattr(
            "pm_core.bench.exercises_bigcodebench._cache_dir", lambda: cached_full
        )
        libs = get_all_required_libs()
        assert "pandas" in libs
        assert "numpy" in libs
        assert "matplotlib" in libs
        assert "scipy" in libs

    def test_get_all_required_libs_hard(self, cached_hard, monkeypatch):
        monkeypatch.setattr(
            "pm_core.bench.exercises_bigcodebench._cache_dir", lambda: cached_hard
        )
        libs = get_all_required_libs(hard_only=True)
        assert libs == {"pandas"}

    def test_get_all_required_libs_no_cache(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "pm_core.bench.exercises_bigcodebench._cache_dir",
            lambda: tmp_path / "nonexistent",
        )
        assert get_all_required_libs() == set()


# ---------------------------------------------------------------------------
# Tests — download_dataset (mocked)
# ---------------------------------------------------------------------------

class TestDownload:
    def test_skips_if_cached(self, cached_full, monkeypatch, capsys):
        monkeypatch.setattr(
            "pm_core.bench.exercises_bigcodebench._cache_dir", lambda: cached_full
        )
        result = download_dataset(hard=False)
        assert result.is_file()
        captured = capsys.readouterr()
        assert "cached" in captured.out.lower()

    def test_returns_hard_cache_path(self, cached_hard, monkeypatch):
        monkeypatch.setattr(
            "pm_core.bench.exercises_bigcodebench._cache_dir", lambda: cached_hard
        )
        result = download_dataset(hard=True)
        assert "hard" in result.name
