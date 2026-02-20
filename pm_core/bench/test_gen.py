"""Test generation from problem descriptions.

Generates test cases using a local model from the exercise description and
starter code — without seeing the reference tests. The core insight: verification
is easier than generation, so even a weak model can produce useful tests that
filter better solutions from multiple candidates.
"""

from __future__ import annotations

from pm_core.bench._utils import extract_code
from pm_core.bench.exercises import Exercise
from pm_core.bench.runner import GenerationResult, Runner

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
generate a comprehensive test suite. Write ONLY the test code — no explanations,
no markdown fences. The tests should:
- Cover basic/happy path cases
- Cover edge cases mentioned in the description
- Be syntactically valid for the target language
- Use the correct function/class names from the starter code
"""


def _build_prompt(exercise: Exercise) -> str:
    hint = _TEST_HINTS.get(exercise.language, "")
    starter = "\n".join(exercise.starter_code.values())
    return (
        f"Language: {exercise.language}\n"
        f"Test framework hint: {hint}\n\n"
        f"## Problem Description\n{exercise.description}\n\n"
        f"## Starter Code\n```\n{starter}\n```\n\n"
        f"Generate a complete test file for this exercise."
    )


def generate_tests(
    exercise: Exercise,
    runner: Runner,
    model: str,
    *,
    num_variants: int = 3,
    temperatures: list[float] | None = None,
) -> tuple[str, list[GenerationResult]]:
    """Generate test cases for an exercise.

    Generates multiple test variants at different temperatures and picks
    the longest valid result (heuristic: more tests = better coverage).

    Returns:
        Tuple of (best test code, list of all generation results).
    """
    temps = temperatures or [0.3, 0.7, 1.0]
    temps = temps[:num_variants]

    prompt = _build_prompt(exercise)
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]

    results = runner.generate(model=model, messages=messages, temperatures=temps)

    best_code = ""
    best_length = 0
    for result in results:
        code = extract_code(result.content)
        if len(code.strip()) > best_length:
            best_code = code
            best_length = len(code.strip())

    return best_code, results
