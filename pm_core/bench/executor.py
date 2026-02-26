"""Test execution and candidate scoring.

Runs test suites against candidate solutions in isolated temporary directories.
Supports 6 polyglot languages with appropriate build/test commands.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from pm_core.bench.exercises import Exercise

# Per-language configuration: which file to write the solution into,
# and the command to run tests.
_LANG_CONFIG: dict[str, dict] = {
    "python": {
        "solution_file": lambda slug: f"{slug.replace('-', '_')}.py",
        "test_file": lambda slug: f"{slug.replace('-', '_')}_test.py",
        "test_cmd": [sys.executable, "-m", "pytest", "--tb=short", "-q"],
    },
    "go": {
        "solution_file": lambda slug: f"{slug.replace('-', '_')}.go",
        "test_file": lambda slug: None,  # tests already in dir
        "test_cmd": ["go", "test", "-v", "./..."],
    },
    "rust": {
        "solution_file": lambda _slug: "src/lib.rs",
        "test_file": lambda _slug: None,
        "test_cmd": ["cargo", "test"],
    },
    "javascript": {
        "solution_file": lambda slug: f"{slug}.js",
        "test_file": lambda slug: f"{slug}.spec.js",
        "test_cmd": ["npx", "jest", "--no-cache"],
    },
    "cpp": {
        "solution_file": lambda slug: f"{slug.replace('-', '_')}.cpp",
        "test_file": lambda slug: None,
        "test_cmd": ["bash", "-c",
                     "cmake -B build . && cmake --build build && cd build && ctest --output-on-failure"],
    },
    "java": {
        "solution_file": lambda _slug: None,  # determined dynamically
        "test_file": lambda _slug: None,
        "test_cmd": ["./gradlew", "test"],
    },
}


@dataclass
class ScoreResult:
    """Result of running tests against a candidate."""

    passed: int = 0
    total: int = 0
    score: float = 0.0
    raw_output: str = ""
    error: str | None = None
    timed_out: bool = False


def _resolve_solution_path(work_dir: Path, exercise: Exercise, config: dict) -> Path | None:
    """Determine where to write the candidate solution."""
    # Prefer explicit starter_code filename — handles exercise sources where
    # the slug doesn't match the expected solution filename (e.g. slug
    # "bcb-0" but solution must be "task_func.py").
    if exercise.starter_code:
        first_key = next(iter(exercise.starter_code))
        return work_dir / first_key

    solution_file = config["solution_file"](exercise.slug)
    if solution_file is not None:
        return work_dir / solution_file

    # Java: find the main source file dynamically
    main_dir = work_dir / "src" / "main"
    java_files = list(main_dir.rglob("*.java")) if main_dir.is_dir() else []
    if java_files:
        return java_files[0]

    return None


def execute_tests(
    exercise: Exercise,
    candidate_code: str,
    test_code: str | None = None,
    *,
    timeout: int = 60,
) -> ScoreResult:
    """Run tests against a candidate solution in an isolated temp directory.

    .. warning::
        Candidate code runs **unsandboxed** via ``subprocess.run`` — no
        cgroup, seccomp, or network isolation.  This is acceptable for a
        local-only benchmark tool running locally-generated code, but should
        not be exposed to untrusted inputs without adding a sandbox layer.

    Args:
        exercise: The exercise (provides language, slug, and path).
        candidate_code: The candidate's source code.
        test_code: Custom test code (e.g. generated tests). If None, uses
                   reference tests from the exercise directory.
        timeout: Maximum seconds for the test run.
    """
    lang = exercise.language
    config = _LANG_CONFIG.get(lang)
    if config is None:
        return ScoreResult(error=f"Unsupported language: {lang}")

    with tempfile.TemporaryDirectory(prefix=f"pm-bench-{lang}-") as tmp:
        work_dir = Path(tmp)

        # Copy the exercise scaffold
        shutil.copytree(exercise.path, work_dir, dirs_exist_ok=True)

        # Write the candidate solution
        solution_path = _resolve_solution_path(work_dir, exercise, config)
        if solution_path is None:
            return ScoreResult(error="Cannot determine solution file path")

        solution_path.parent.mkdir(parents=True, exist_ok=True)
        solution_path.write_text(candidate_code)

        # Optionally override test code
        if test_code is not None:
            test_file = config["test_file"](exercise.slug)
            if test_file is not None:
                (work_dir / test_file).write_text(test_code)
            elif exercise.reference_tests:
                # For languages where test_file is not configured (Go, Rust, Java),
                # overwrite the first reference test file from the exercise scaffold.
                first_test = next(iter(exercise.reference_tests))
                (work_dir / first_test).write_text(test_code)
            else:
                return ScoreResult(
                    error="Cannot determine test file path for custom test code"
                )

        # Run tests
        try:
            proc = subprocess.run(
                config["test_cmd"],
                cwd=work_dir,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            output = proc.stdout + proc.stderr
            return _parse_test_output(output, proc.returncode)
        except subprocess.TimeoutExpired:
            return ScoreResult(
                raw_output="Test execution timed out",
                error="timeout",
                timed_out=True,
            )
        except FileNotFoundError as exc:
            return ScoreResult(error=f"Test runner not found: {exc}")
        except OSError as exc:
            return ScoreResult(error=f"Execution error: {exc}")


def _parse_test_output(output: str, returncode: int) -> ScoreResult:
    """Parse test runner output to extract pass/fail counts."""
    result = ScoreResult(raw_output=output)

    if returncode == 0:
        total = _count_tests_from_output(output)
        result.passed = total
        result.total = total
        result.score = 1.0
        return result

    passed, total = _parse_counts(output)
    result.passed = passed
    result.total = max(total, 1)
    result.score = passed / result.total if result.total > 0 else 0.0

    if total == 0:
        result.error = "compilation_or_parse_error"

    return result


def _count_tests_from_output(output: str) -> int:
    """Try to count total tests from passing output."""
    # pytest: "5 passed"
    m = re.search(r"(\d+) passed", output)
    if m:
        return int(m.group(1))

    # go test: "--- PASS" lines
    pass_count = output.count("--- PASS")
    if pass_count > 0:
        return pass_count

    # cargo test: "test result: ok. 5 passed"
    m = re.search(r"test result: ok\. (\d+) passed", output)
    if m:
        return int(m.group(1))

    # jest: "Tests: N passed, N total"
    m = re.search(r"Tests:\s+(\d+) passed", output)
    if m:
        return int(m.group(1))

    return 1


def _parse_counts(output: str) -> tuple[int, int]:
    """Parse passed/total counts from test runner output."""
    # pytest: "2 passed, 3 failed"
    passed = 0
    failed = 0
    m_pass = re.search(r"(\d+) passed", output)
    m_fail = re.search(r"(\d+) failed", output)
    m_err = re.search(r"(\d+) error", output)
    if m_pass or m_fail:
        if m_pass:
            passed = int(m_pass.group(1))
        if m_fail:
            failed += int(m_fail.group(1))
        if m_err:
            failed += int(m_err.group(1))
        return passed, passed + failed

    # go test: count PASS/FAIL lines
    go_pass = output.count("--- PASS")
    go_fail = output.count("--- FAIL")
    if go_pass + go_fail > 0:
        return go_pass, go_pass + go_fail

    # cargo test: "test result: FAILED. 2 passed; 1 failed"
    m = re.search(r"(\d+) passed; (\d+) failed", output)
    if m:
        return int(m.group(1)), int(m.group(1)) + int(m.group(2))

    # jest: "Tests: N failed, M passed, P total"
    m = re.search(r"Tests:\s+(?:\d+ failed,\s+)?(\d+) passed,\s+(\d+) total", output)
    if m:
        return int(m.group(1)), int(m.group(2))

    return 0, 0
