"""Test generation from problem descriptions.

Generates test cases using a local model from the exercise description and
starter code — without seeing the reference tests. The core insight: verification
is easier than generation, so even a weak model can produce useful tests that
filter better solutions from multiple candidates.
"""

from __future__ import annotations

import random
import re

from typing import Any

from pm_core.bench._utils import extract_code
from pm_core.bench.exercises import Exercise
from pm_core.bench.runner import GenerationResult, Runner

# Extra request body params for test generation: enable reasoning so the model
# thinks through expected values before writing assertions, and give it the
# full token budget.
_TEST_GEN_EXTRA_BODY: dict[str, Any] = {
    "chat_template_kwargs": {"reasoning_effort": "high"},
    "max_completion_tokens": 32768,
}

# Language-specific test framework hints for the prompt.
_TEST_HINTS: dict[str, str] = {
    "python": "Use pytest. Import the module and test functions directly.",
    "go": "Use the testing package. Each test function takes *testing.T.",
    "rust": "Use #[test] attribute in a tests module.",
    "javascript": "Use Jest describe/test/expect pattern.",
    "cpp": "Use Catch2 TEST_CASE and REQUIRE macros.",
    "java": "Use JUnit 5 @Test annotations with assertEquals etc.",
}

_SYSTEM_PROMPT = """\
You are an expert test writer. Given a problem description and starter code,
generate a comprehensive test suite. Think carefully about the expected outputs
before writing assertions — work through each computation step by step.

Output ONLY the test code at the end — no explanations, no markdown fences.

Rules:
- Match the function/class signature from the starter code EXACTLY — same name,
  same parameter order, same types.
- Cover basic/happy path cases and edge cases mentioned in the description.
- Be syntactically valid for the target language.
- Where possible, hard-code expected values directly in assertions. You may use
  small helper functions for setup or readability, but avoid writing a complete
  reference implementation — the goal is to test the solution, not reimplement it.
"""


def _build_prompt(exercise: Exercise) -> str:
    hint = _TEST_HINTS.get(exercise.language, "")
    starter_parts = []
    for filename, code in exercise.starter_code.items():
        starter_parts.append(f"# {filename}\n{code}")
    starter = "\n".join(starter_parts)
    return (
        f"Language: {exercise.language}\n"
        f"Test framework hint: {hint}\n\n"
        f"## Problem Description\n{exercise.description}\n\n"
        f"## Starter Code\n```\n{starter}\n```\n\n"
        f"Generate a complete test file for this exercise. "
        f"Import from the module shown above (the filename without extension)."
    )


def _build_chain_suffix(prior_tests: list[str]) -> str:
    """Format prior test suites into a prompt suffix for chain mode."""
    parts = [
        "\n## Previous Test Suites",
        "The following test suites were already written. Write a NEW test suite "
        "that covers DIFFERENT cases — focus on edge cases, error paths, and "
        "scenarios not already tested.\n",
        "IMPORTANT: Do NOT assume the previous suites are correct. Their expected "
        "values may be wrong. Independently verify any expected outputs by "
        "reasoning through the problem description from scratch before writing "
        "your assertions.\n",
    ]
    for i, code in enumerate(prior_tests, 1):
        parts.append(f"### Suite {i}\n```\n{code}\n```\n")
    return "\n".join(parts)


def generate_tests(
    exercise: Exercise,
    runner: Runner,
    model: str,
    *,
    num_variants: int = 3,
    temperatures: list[float] | None = None,
    chain: bool = False,
) -> tuple[str, list[GenerationResult]]:
    """Generate test cases for an exercise.

    When *chain* is False (default), generates multiple test variants in
    parallel at different temperatures and picks the longest result.

    When *chain* is True, generates sequentially — each variant sees the
    prior test suites and is asked to cover different cases.  All variants
    are then merged into one combined test file.

    Returns:
        Tuple of (best test code, list of all generation results).
    """
    temps = temperatures or ([0.3] * num_variants if chain else [0.3, 0.7, 1.0])
    temps = temps[:num_variants]

    prompt = _build_prompt(exercise)
    base_messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]

    if chain:
        return _generate_tests_chain(
            exercise, runner, model, base_messages, temps
        )

    # Default: parallel generation, pick longest
    results = runner.generate(
        model=model, messages=base_messages, temperatures=temps,
        extra_body=_TEST_GEN_EXTRA_BODY,
    )

    best_code = ""
    best_length = 0
    for result in results:
        code = extract_code(result.content)
        if len(code.strip()) > best_length:
            best_code = code
            best_length = len(code.strip())

    return best_code, results


def _generate_tests_chain(
    exercise: Exercise,
    runner: Runner,
    model: str,
    base_messages: list[dict[str, str]],
    temps: list[float],
) -> tuple[str, list[GenerationResult]]:
    """Chain mode: generate test suites sequentially, then merge."""
    results: list[GenerationResult] = []
    prior_codes: list[str] = []

    for temp in temps:
        msgs = list(base_messages)
        if prior_codes:
            suffix = _build_chain_suffix(prior_codes)
            msgs = [msgs[0], {"role": "user", "content": msgs[1]["content"] + suffix}]
        result = runner.complete(
            model=model, messages=msgs, temperature=temp,
            extra_body=_TEST_GEN_EXTRA_BODY,
        )
        code = extract_code(result.content)
        results.append(result)
        prior_codes.append(code)

    # Merge: use the first suite as the base, append unique test functions
    # from subsequent suites
    merged = _merge_test_suites(prior_codes, exercise.language)
    return merged, results


def _merge_test_suites(suites: list[str], language: str) -> str:
    """Merge multiple test suites into one, deduplicating by function name."""
    if not suites:
        return ""
    if len(suites) == 1:
        return suites[0]

    # Use the first suite as the base
    base_header, base_funcs = split_test_functions(suites[0], language)
    seen_names: set[str] = set()
    for func in base_funcs:
        name = _extract_func_name(func, language)
        if name:
            seen_names.add(name)

    # Add unique functions from subsequent suites
    for suite in suites[1:]:
        _, extra_funcs = split_test_functions(suite, language)
        for func in extra_funcs:
            name = _extract_func_name(func, language)
            if name and name not in seen_names:
                seen_names.add(name)
                base_funcs.append(func)

    parts = [base_header] if base_header else []
    parts.extend(base_funcs)
    return "\n\n".join(parts) + "\n"


def _extract_func_name(func_code: str, language: str) -> str | None:
    """Extract the test function name from the first line of a test function."""
    patterns: dict[str, re.Pattern[str]] = {
        "python": re.compile(r"def (test_\w+)"),
        "go": re.compile(r"func (Test\w+)"),
        "rust": re.compile(r"fn (test_\w+)"),
        "javascript": re.compile(r"(?:test|it)\(['\"](.+?)['\"]"),
    }
    pat = patterns.get(language)
    if pat is None:
        return None
    m = pat.search(func_code)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# Test splitting and subsetting
# ---------------------------------------------------------------------------

# Patterns that mark the start of a test function per language.
_TEST_PATTERNS: dict[str, re.Pattern[str]] = {
    "python": re.compile(r"^(def test_)", re.MULTILINE),
    "go": re.compile(r"^(func Test)", re.MULTILINE),
    "rust": re.compile(r"^(\s*fn test_)", re.MULTILINE),
    "javascript": re.compile(r"^(test\(|it\()", re.MULTILINE),
}


def split_test_functions(test_code: str, language: str) -> tuple[str, list[str]]:
    """Split a test file into a shared header and individual test functions.

    Returns:
        Tuple of (header, list_of_test_bodies). The header contains imports
        and setup code that appears before the first test function. Each
        entry in the list is one complete test function as a string.
    """
    pattern = _TEST_PATTERNS.get(language)
    if pattern is None:
        # Unknown language — return entire file as one "test"
        return "", [test_code]

    # Find all match positions
    matches = list(pattern.finditer(test_code))
    if not matches:
        return test_code, []

    header = test_code[: matches[0].start()].rstrip("\n")
    functions: list[str] = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(test_code)
        functions.append(test_code[start:end].rstrip("\n"))

    return header, functions


def sample_test_subset(
    tests: list[str], header: str, n: int, *, rng: random.Random | None = None
) -> str:
    """Randomly sample *n* test functions and reassemble with the header.

    If *n* >= len(tests), returns all tests unchanged.
    """
    if n >= len(tests):
        selected = tests
    else:
        r = rng or random.Random()
        selected = r.sample(tests, n)

    parts = [header] if header else []
    parts.extend(selected)
    return "\n\n".join(parts) + "\n"
