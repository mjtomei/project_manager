"""Load EvalPlus benchmark exercises (HumanEval+ and MBPP+).

Downloads datasets from HuggingFace and caches locally under
``~/.cache/pm-bench/evalplus/``.  Each exercise maps to the shared
:class:`Exercise` dataclass so the rest of the bench pipeline (candidate
generation, scoring, result collection) works unchanged.

HumanEval+ — 164 Python function-completion problems with ~10 000 expanded
assert-based tests (80× the original HumanEval).

MBPP+ — 378 Python tasks with similarly expanded test suites.

Both datasets store tests in a standardised format: helper functions
(``is_floats``, ``assertion``), an ``inputs`` list, a ``results`` list,
and a for-loop that checks ``assertion(func(*inp), exp, atol)`` for each
pair.  This module transforms that into pytest-compatible test files.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import Path

from pm_core.bench.exercises import Exercise
from pm_core.paths import bench_cache_dir

# HuggingFace datasets-server API for paginated row access.
_HF_ROWS_URL = "https://datasets-server.huggingface.co/rows"

# Dataset identifiers on HuggingFace.
_DATASETS: dict[str, dict] = {
    "humanevalplus": {
        "hf_dataset": "evalplus/humanevalplus",
        "cache_file": "humaneval_plus.jsonl",
        "num_rows": 164,
    },
    "mbppplus": {
        "hf_dataset": "evalplus/mbppplus",
        "cache_file": "mbpp_plus.jsonl",
        "num_rows": 378,
    },
}

_PAGE_SIZE = 100  # max rows per API request


def _evalplus_dir() -> Path:
    """Return the path to the EvalPlus cache directory."""
    return bench_cache_dir() / "evalplus"


def _exercises_dir() -> Path:
    """Return the path where per-exercise directories are stored."""
    return _evalplus_dir() / "exercises"


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def sync_evalplus(quiet: bool = False) -> Path:
    """Download EvalPlus datasets if not already cached. Returns cache dir."""
    cache = _evalplus_dir()

    for ds_key, ds_info in _DATASETS.items():
        dest = cache / ds_info["cache_file"]
        if dest.is_file():
            continue

        cache.mkdir(parents=True, exist_ok=True)
        if not quiet:
            print(f"Downloading {ds_key} from HuggingFace ...")

        rows = _fetch_all_rows(ds_info["hf_dataset"], ds_info["num_rows"])
        lines = [json.dumps(r, ensure_ascii=False) for r in rows]
        dest.write_text("\n".join(lines) + "\n", encoding="utf-8")

        if not quiet:
            print(f"  → {len(rows)} problems saved to {dest.name}")

    # Regenerate exercise dirs from JSONL (idempotent).
    _build_exercise_dirs(quiet=quiet)

    return cache


def _fetch_all_rows(hf_dataset: str, expected_rows: int) -> list[dict]:
    """Paginate through the HuggingFace datasets-server rows endpoint."""
    rows: list[dict] = []
    offset = 0

    while offset < expected_rows:
        url = (
            f"{_HF_ROWS_URL}?dataset={hf_dataset}"
            f"&config=default&split=test"
            f"&offset={offset}&length={_PAGE_SIZE}"
        )
        try:
            with urllib.request.urlopen(url, timeout=60) as resp:
                data = json.loads(resp.read())
        except (urllib.error.URLError, OSError) as exc:
            raise ConnectionError(
                f"Failed to download {hf_dataset} from HuggingFace: {exc}"
            ) from exc

        fetched_rows = data.get("rows", [])
        for entry in fetched_rows:
            rows.append(entry["row"])

        if not fetched_rows:
            break
        offset += len(fetched_rows)

    return rows


# ---------------------------------------------------------------------------
# JSONL parsing → Exercise objects
# ---------------------------------------------------------------------------

def load_evalplus_exercises(*, slug: str | None = None) -> list[Exercise]:
    """Load EvalPlus exercises from the local cache.

    Raises:
        FileNotFoundError: If the exercise cache doesn't exist yet.
    """
    cache = _evalplus_dir()
    exercises: list[Exercise] = []

    for ds_info in _DATASETS.values():
        jsonl_path = cache / ds_info["cache_file"]
        if not jsonl_path.is_file():
            raise FileNotFoundError(
                "EvalPlus cache not found. "
                "Run `pm bench exercises --source evalplus` to download."
            )
        for line in jsonl_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            ex = _parse_evalplus_record(record)
            if ex is None:
                continue
            if slug and slug.lower() not in ex.slug.lower():
                continue
            exercises.append(ex)

    exercises.sort(key=lambda e: (e.language, e.slug))
    return exercises


def _parse_evalplus_record(record: dict) -> Exercise | None:
    """Parse a single EvalPlus JSONL record into an Exercise."""
    task_id = record.get("task_id")
    prompt = record.get("prompt", "")
    test_code = record.get("test", "")

    if task_id is None or not prompt or not test_code:
        return None

    # Normalise task_id — HumanEval uses str ("HumanEval/0"),
    # MBPP uses int (2).
    task_id_str = str(task_id)

    # Determine entry_point.
    entry_point = record.get("entry_point")
    if not entry_point:
        # MBPP+ doesn't have entry_point; extract from `code` field.
        code = record.get("code", "")
        entry_point = _extract_entry_point(code)
    if not entry_point:
        return None

    slug = _task_id_to_slug(task_id_str)
    module_name = _slug_to_module(slug)

    # Ensure exercise directory exists with test file.
    ex_dir = _exercises_dir() / slug
    test_filename = f"{module_name}_test.py"
    test_filepath = ex_dir / test_filename

    if test_filepath.is_file():
        test_content = test_filepath.read_text(encoding="utf-8")
    else:
        ex_dir.mkdir(parents=True, exist_ok=True)
        test_content = _transform_test_code(test_code, entry_point, module_name)
        test_filepath.write_text(test_content, encoding="utf-8")

    return Exercise(
        language="python",
        slug=slug,
        description=prompt,
        starter_code={},
        reference_tests={test_filename: test_content},
        path=ex_dir,
        source="evalplus",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _task_id_to_slug(task_id: str) -> str:
    """Convert a task_id to a filesystem-safe slug.

    ``"HumanEval/0"`` → ``"humaneval-0"``
    ``"2"`` (MBPP)      → ``"mbpp-2"``
    """
    if "/" in task_id:
        # "HumanEval/0" → "humaneval-0"
        return task_id.replace("/", "-").lower()
    # MBPP task_id is just an int — prefix it.
    return f"mbpp-{task_id}"


def _slug_to_module(slug: str) -> str:
    """Convert a slug to a valid Python module name.

    ``"humaneval-0"`` → ``"humaneval_0"``
    """
    return slug.replace("-", "_")


def _extract_entry_point(code: str) -> str | None:
    """Extract the first function name from a code snippet."""
    m = re.search(r"^def (\w+)\s*\(", code, re.MULTILINE)
    return m.group(1) if m else None


def _transform_test_code(
    test_code: str, entry_point: str, module_name: str,
) -> str:
    """Transform EvalPlus test harness into a pytest-compatible test file.

    Both HumanEval+ and MBPP+ use a standard pattern::

        # helper functions (is_floats, assertion)
        inputs = [...]
        results = [...]
        for i, (inp, exp) in enumerate(zip(inputs, results)):
            assertion(func_or_candidate(*inp), exp, atol)

    HumanEval+ uses ``candidate`` as the function variable; MBPP+ calls the
    function by name.  The transformed file:

    1. Imports everything from the solution module (``from mod import *``).
    2. Assigns ``candidate = entry_point`` so HumanEval+ tests resolve.
    3. Keeps helpers and data at module level.
    4. Wraps the assertion loop in ``def test_check():``.
    """
    lines = test_code.split("\n")

    # Find the last top-level for-loop (the assertion loop).
    loop_start = None
    for i, line in enumerate(lines):
        if re.match(r"^for\s+", line):
            loop_start = i

    if loop_start is not None:
        setup = "\n".join(lines[:loop_start]).rstrip()
        loop_lines = lines[loop_start:]
        # Indent loop body into a test function.
        indented_loop = "\n".join(
            f"    {line}" if line.strip() else "" for line in loop_lines
        )
        body = (
            f"from {module_name} import *\n"
            f"candidate = {entry_point}\n\n"
            f"{setup}\n\n"
            f"def test_check():\n"
            f"{indented_loop}\n"
        )
    else:
        # Fallback: look for old-style ``check(entry_point)`` pattern.
        cleaned, _found = _strip_bare_check_call(lines)
        setup = "\n".join(cleaned).rstrip()
        body = (
            f"from {module_name} import *\n"
            f"candidate = {entry_point}\n\n"
            f"{setup}\n\n"
            f"def test_check():\n"
            f"    check({entry_point})\n"
        )

    return body


def _strip_bare_check_call(lines: list[str]) -> tuple[list[str], bool]:
    """Remove a trailing bare ``check(...)`` call from the test code."""
    cleaned = []
    found = False
    for line in reversed(lines):
        stripped = line.strip()
        if not found and re.match(r"^check\s*\(", stripped):
            found = True
            continue
        cleaned.append(line)
    cleaned.reverse()
    return cleaned, found


# ---------------------------------------------------------------------------
# Exercise directory construction
# ---------------------------------------------------------------------------

def _build_exercise_dirs(quiet: bool = False) -> None:
    """(Re)generate exercise directories from cached JSONL files.

    Each directory contains the pytest-wrapped test file.  Called by
    :func:`sync_evalplus` after downloading.
    """
    cache = _evalplus_dir()
    count = 0

    for ds_info in _DATASETS.values():
        jsonl_path = cache / ds_info["cache_file"]
        if not jsonl_path.is_file():
            continue
        for line in jsonl_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            ex = _parse_evalplus_record(record)
            if ex is not None:
                count += 1

    if not quiet:
        print(f"Prepared {count} exercise directories.")
