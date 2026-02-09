"""Test generation from problem descriptions.

Generates test cases using a local model from the exercise description and
starter code — without seeing the reference tests. The core insight: verification
is easier than generation, so even a weak model can produce useful tests that
filter better solutions from multiple candidates.
"""

from __future__ import annotations

from pm_core.bench.exercises import Exercise
from pm_core.bench.runner import GenerationResult, OllamaRunner

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
    return (
        f"Language: {exercise.language}\n"
        f"Test framework hint: {hint}\n\n"
        f"## Problem Description\n{exercise.description}\n\n"
        f"## Starter Code\n```\n{exercise.starter_code}\n```\n\n"
        f"Generate a complete test file for this exercise."
    )


def generate_tests(
    exercise: Exercise,
    runner: OllamaRunner,
    model: str,
    *,
    num_variants: int = 3,
    temperatures: list[float] | None = None,
) -> tuple[str, list[GenerationResult]]:
    """Generate test cases for an exercise.

    Generates multiple test variants at different temperatures and merges
    them into a single test suite by picking the longest valid result
    (heuristic: more tests = better coverage).

    Returns:
        Tuple of (best test code, list of all generation results).
    """
    temps = temperatures or [0.3, 0.7, 1.0]
    temps = temps[:num_variants]

    prompt = _build_prompt(exercise)
    results: list[GenerationResult] = []
    best_code = ""
    best_length = 0

    for temp in temps:
        result = runner.generate(
            model, prompt, system=_SYSTEM_PROMPT, temperature=temp
        )
        results.append(result)

        code = _extract_code(result.text)
        # Heuristic: longer test suites tend to have more coverage
        if len(code.strip()) > best_length:
            best_code = code
            best_length = len(code.strip())

    return best_code, results


def _extract_code(text: str) -> str:
    """Extract code from a model response, stripping markdown fences if present."""
    lines = text.strip().split("\n")

    # Check if wrapped in markdown code fences
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
        # Find closing fence
        for i in range(len(lines) - 1, -1, -1):
            if lines[i].strip() == "```":
                lines = lines[:i]
                break

    return "\n".join(lines)
