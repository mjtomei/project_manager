"""Load BigCodeBench exercises from HuggingFace.

Downloads from https://huggingface.co/datasets/bigcode/bigcodebench and
bigcode/bigcodebench-hard, caches under ~/.cache/pm-bench/bigcodebench/.

Each task provides:
- instruct_prompt: Natural language description (best for chat models)
- complete_prompt: Function signature with docstring (code completion)
- test: unittest-based test code with mock.patch patterns
- entry_point: Expected function name (varies per task)
- libs: Stringified Python list of required library names
"""

from __future__ import annotations

import ast
import json
import urllib.error
import urllib.request
from pathlib import Path

from pm_core.bench.exercises import Exercise
from pm_core.paths import bench_cache_dir

# HuggingFace datasets-server API
_API_BASE = "https://datasets-server.huggingface.co"
_DATASET_FULL = "bigcode/bigcodebench"
_DATASET_HARD = "bigcode/bigcodebench-hard"
_SPLIT = "v0.1.4"
_PAGE_SIZE = 100


def _cache_dir() -> Path:
    """Return the BigCodeBench cache directory."""
    return bench_cache_dir() / "bigcodebench"


def _fetch_rows(dataset: str, split: str, *, quiet: bool = False) -> list[dict]:
    """Fetch all rows from a HuggingFace dataset via the datasets-server API."""
    rows: list[dict] = []
    offset = 0
    while True:
        url = (
            f"{_API_BASE}/rows?dataset={dataset}"
            f"&config=default&split={split}"
            f"&offset={offset}&length={_PAGE_SIZE}"
        )
        if not quiet:
            print(f"  Fetching rows {offset}\u2013{offset + _PAGE_SIZE} ...", flush=True)

        try:
            with urllib.request.urlopen(url, timeout=60) as resp:
                data = json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            raise RuntimeError(
                f"HuggingFace API returned HTTP {exc.code} for {dataset} "
                f"(split={split}, offset={offset}). Check the dataset name "
                f"and split version."
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"Cannot reach HuggingFace datasets-server: {exc.reason}"
            ) from exc

        page_rows = [r["row"] for r in data.get("rows", [])]
        if not page_rows:
            break
        rows.extend(page_rows)

        num_rows_total = data.get("num_rows_total", 0)
        offset += len(page_rows)
        if offset >= num_rows_total:
            break

    return rows


def download_dataset(*, hard: bool = False, quiet: bool = False) -> Path:
    """Download BigCodeBench from HuggingFace. Returns path to cached JSON.

    Downloads from the datasets-server API and caches locally. Skips
    download if the cache file already exists.
    """
    cache = _cache_dir()
    cache.mkdir(parents=True, exist_ok=True)

    suffix = "hard" if hard else "full"
    cache_file = cache / f"bigcodebench_{suffix}_{_SPLIT}.json"

    if cache_file.is_file():
        if not quiet:
            print(f"Using cached {suffix} dataset: {cache_file}")
        return cache_file

    dataset = _DATASET_HARD if hard else _DATASET_FULL
    if not quiet:
        print(f"Downloading BigCodeBench {suffix} from HuggingFace ...")

    rows = _fetch_rows(dataset, _SPLIT, quiet=quiet)
    cache_file.write_text(json.dumps(rows, indent=2))

    if not quiet:
        print(f"Cached {len(rows)} tasks \u2192 {cache_file}")

    # Create scaffold directories with test files
    _create_scaffolds(rows, cache)

    return cache_file


def _create_scaffolds(tasks: list[dict], cache: Path) -> None:
    """Create per-exercise scaffold directories with test files."""
    scaffolds = cache / "scaffolds"
    for task in tasks:
        task_id = task["task_id"]
        task_num = task_id.rsplit("/", 1)[-1]
        slug = f"bcb-{task_num}"
        scaffold = scaffolds / slug
        scaffold.mkdir(parents=True, exist_ok=True)

        # Write test file with name matching executor's test_file config
        # (slug.replace('-', '_') + '_test.py')
        test_filename = f"{slug.replace('-', '_')}_test.py"
        (scaffold / test_filename).write_text(task["test"])


def _parse_task(task: dict, mode: str, scaffolds_dir: Path) -> Exercise:
    """Convert a BigCodeBench task dict to an Exercise."""
    task_id = task["task_id"]  # e.g. "BigCodeBench/13"
    task_num = task_id.rsplit("/", 1)[-1]
    slug = f"bcb-{task_num}"

    entry_point = task.get("entry_point", "task_func")

    if mode == "complete":
        description = task["complete_prompt"]
    else:
        description = task["instruct_prompt"]
        # Ensure the model defines the function at module level
        description += (
            f"\n\nDefine a function named `{entry_point}` at module level."
        )

    test_code = task["test"]
    test_filename = f"{slug.replace('-', '_')}_test.py"
    solution_file = f"{entry_point}.py"

    scaffold = scaffolds_dir / slug

    return Exercise(
        language="python",
        slug=slug,
        description=description,
        starter_code={solution_file: ""},
        reference_tests={test_filename: test_code},
        path=scaffold,
        source="bigcodebench",
    )


def _slug_sort_key(slug: str) -> tuple[str, int]:
    """Sort key that orders bcb-2 before bcb-10 (numeric, not lexicographic)."""
    parts = slug.rsplit("-", 1)
    if len(parts) == 2 and parts[1].isdigit():
        return (parts[0], int(parts[1]))
    return (slug, 0)


def load_bigcodebench_exercises(
    *,
    hard_only: bool = False,
    mode: str = "instruct",
    slug: str | None = None,
) -> list[Exercise]:
    """Load BigCodeBench exercises from cache.

    Args:
        hard_only: Use only the 148-problem hard subset.
        mode: "instruct" (NL descriptions) or "complete" (docstring-based).
        slug: Filter by slug substring.

    Raises:
        FileNotFoundError: If the dataset cache doesn't exist.
    """
    suffix = "hard" if hard_only else "full"
    cache_file = _cache_dir() / f"bigcodebench_{suffix}_{_SPLIT}.json"

    if not cache_file.is_file():
        hard_flag = " --hard" if hard_only else ""
        raise FileNotFoundError(
            f"BigCodeBench {suffix} cache not found. "
            f"Run `pm bench exercises --source bigcodebench{hard_flag}` to download."
        )

    tasks = json.loads(cache_file.read_text())
    scaffolds_dir = _cache_dir() / "scaffolds"
    exercises = [_parse_task(t, mode, scaffolds_dir) for t in tasks]

    if slug:
        exercises = [e for e in exercises if slug.lower() in e.slug.lower()]

    exercises.sort(key=lambda e: _slug_sort_key(e.slug))
    return exercises


def extract_libs(task: dict) -> list[str]:
    """Extract library names from a task's libs field.

    The field is a stringified Python list like ``"['random', 'itertools']"``.
    """
    libs_str = task.get("libs", "")
    if not libs_str:
        return []
    # The field is a stringified Python list — parse it safely.
    try:
        parsed = ast.literal_eval(libs_str)
        if isinstance(parsed, list):
            return [str(lib).strip() for lib in parsed if str(lib).strip()]
    except (ValueError, SyntaxError):
        pass
    # Fallback: comma-separated
    return [lib.strip() for lib in libs_str.split(",") if lib.strip()]


def get_all_required_libs(*, hard_only: bool = False) -> set[str]:
    """Return the set of all libraries required across all cached tasks."""
    suffix = "hard" if hard_only else "full"
    cache_file = _cache_dir() / f"bigcodebench_{suffix}_{_SPLIT}.json"

    if not cache_file.is_file():
        return set()

    tasks = json.loads(cache_file.read_text())
    all_libs: set[str] = set()
    for task in tasks:
        all_libs.update(extract_libs(task))
    return all_libs
