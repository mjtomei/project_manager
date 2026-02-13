"""Multi-candidate solution generation.

Generates N candidate solutions for an exercise using temperature and prompt
diversity. Each candidate is a complete implementation file that should
compile and pass the tests.

Temperature ranges from 0.0 (deterministic) to 1.0 (creative), distributed
evenly across candidates. Prompt variants (direct, chain-of-thought,
example-driven) cycle across candidates to maximize solution diversity.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pm_core.bench.exercises import Exercise
from pm_core.bench.runner import GenerationResult, Runner


PROMPT_VARIANTS: dict[str, str] = {
    "direct": (
        "Implement the solution. Write ONLY the complete source code — "
        "no explanations, no markdown fences, no comments about the approach."
    ),
    "chain_of_thought": (
        "Think step by step about how to solve this problem:\n"
        "1. Analyze the requirements and edge cases\n"
        "2. Choose an algorithm or approach\n"
        "3. Implement the solution\n\n"
        "After reasoning through the steps, write the complete implementation. "
        "Output ONLY the final code — no explanations or markdown fences."
    ),
    "example_driven": (
        "Study the test cases carefully to understand the expected behavior. "
        "Use the examples and edge cases from the tests to guide your "
        "implementation. Write ONLY the complete source code — no "
        "explanations or markdown fences."
    ),
}


@dataclass
class Candidate:
    """A single candidate solution."""

    code: str
    temperature: float
    prompt_variant: str
    model: str
    generation_result: GenerationResult | None = field(default=None, repr=False)


def _format_starter_code(starter_code: dict[str, str] | str) -> str:
    """Format starter code dict into a single string for prompt inclusion."""
    if isinstance(starter_code, str):
        return starter_code
    parts = []
    for filename, content in sorted(starter_code.items()):
        if len(starter_code) > 1:
            parts.append(f"// {filename}")
        parts.append(content)
    return "\n".join(parts)


def _format_tests(tests: dict[str, str] | str) -> str:
    """Format test content into a single string for prompt inclusion."""
    if isinstance(tests, str):
        return tests
    parts = []
    for filename, content in sorted(tests.items()):
        if len(tests) > 1:
            parts.append(f"// {filename}")
        parts.append(content)
    return "\n".join(parts)


def build_prompt(
    *,
    language: str,
    description: str,
    starter_code: str,
    variant: str,
    tests: str = "",
) -> list[dict[str, str]]:
    """Build chat messages for a candidate generation request.

    Args:
        language: Programming language name.
        description: Problem description text.
        starter_code: Formatted starter code string.
        variant: One of the PROMPT_VARIANTS keys.
        tests: Optional test suite content for the example_driven variant.

    Returns:
        List of message dicts suitable for chat completion API.
    """
    system = (
        f"You are an expert {language} programmer. "
        "You write clean, correct, efficient code that passes all tests. "
        "You output only source code with no surrounding text or markdown."
    )

    instruction = PROMPT_VARIANTS[variant]

    parts = [f"## Problem\n\n{description}"]

    if starter_code.strip():
        parts.append(f"## Starter Code\n\n```{language}\n{starter_code}\n```")

    if tests.strip():
        parts.append(f"## Tests\n\n```{language}\n{tests}\n```")

    parts.append(f"## Instructions\n\n{instruction}")

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n\n".join(parts)},
    ]


def extract_code(text: str) -> str:
    """Extract code from model response, stripping markdown fences if present.

    Handles common patterns:
    - ```language\\n...\\n```
    - ```\\n...\\n```
    - Plain code with no fences
    - Multiple code blocks (takes the longest one)
    """
    text = text.strip()
    if not text:
        return text

    # Find all fenced code blocks
    blocks = re.findall(r"```(?:\w+)?\s*\n(.*?)```", text, re.DOTALL)
    if blocks:
        # Return the longest block (most likely the complete solution)
        return max(blocks, key=len).strip()

    # Handle unclosed fence at start
    lines = text.split("\n")
    if lines[0].startswith("```"):
        lines = lines[1:]
        # Strip trailing fence if present
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()

    return text


def temperature_schedule(num_candidates: int) -> list[float]:
    """Generate a temperature schedule evenly spread across 0.0 to 1.0.

    For N=1: [0.0]
    For N=2: [0.0, 1.0]
    For N=3: [0.0, 0.5, 1.0]
    For N=8: [0.0, 0.14, 0.29, 0.43, 0.57, 0.71, 0.86, 1.0]
    """
    if num_candidates <= 1:
        return [0.0]
    step = 1.0 / (num_candidates - 1)
    return [round(i * step, 2) for i in range(num_candidates)]


def generate_candidates(
    *,
    language: str,
    description: str,
    starter_code: dict[str, str] | str,
    runner: Runner,
    model: str,
    num_candidates: int = 8,
    temperatures: list[float] | None = None,
    tests: dict[str, str] | str = "",
    max_tokens: int = 4096,
) -> list[Candidate]:
    """Generate N candidate solutions with temperature and prompt diversity.

    Distributes candidates across temperature values and prompt variants
    for maximum diversity. Each candidate gets a different combination of
    temperature and prompt format.

    Args:
        language: Programming language (e.g. "python", "go").
        description: Problem description text.
        starter_code: Starter code as dict (filename->content) or string.
        runner: Runner instance for LLM inference.
        model: Model identifier string.
        num_candidates: Number of candidates to generate (default 8).
        temperatures: Custom temperature schedule. If None, spreads 0.0–1.0.
        tests: Optional test suite for inclusion in example_driven prompts.
        max_tokens: Maximum tokens per generation (default 4096).

    Returns:
        List of Candidate objects with code, metadata, and generation stats.
    """
    formatted_starter = _format_starter_code(starter_code)
    formatted_tests = _format_tests(tests) if tests else ""

    if temperatures is None:
        temperatures = temperature_schedule(num_candidates)

    variants = list(PROMPT_VARIANTS.keys())
    candidates: list[Candidate] = []

    for i in range(num_candidates):
        temp = temperatures[i % len(temperatures)]
        variant = variants[i % len(variants)]

        messages = build_prompt(
            language=language,
            description=description,
            starter_code=formatted_starter,
            variant=variant,
            tests=formatted_tests,
        )

        result = runner.complete(
            model=model,
            messages=messages,
            temperature=temp,
            max_tokens=max_tokens,
        )

        code = extract_code(result.content)

        candidates.append(
            Candidate(
                code=code,
                temperature=temp,
                prompt_variant=variant,
                model=result.model,
                generation_result=result,
            )
        )

    return candidates


def generate_candidates_for_exercise(
    exercise: Exercise,
    runner: Runner,
    model: str,
    *,
    num_candidates: int = 8,
    temperatures: list[float] | None = None,
    tests: dict[str, str] | str = "",
    max_tokens: int = 4096,
) -> list[Candidate]:
    """Convenience wrapper that unpacks an Exercise for candidate generation.

    If no tests are provided, falls back to the exercise's reference tests.
    """
    if not tests:
        tests = exercise.reference_tests

    return generate_candidates(
        language=exercise.language,
        description=exercise.description,
        starter_code=exercise.starter_code,
        runner=runner,
        model=model,
        num_candidates=num_candidates,
        temperatures=temperatures,
        tests=tests,
        max_tokens=max_tokens,
    )


def deduplicate_candidates(candidates: list[Candidate]) -> list[Candidate]:
    """Remove candidates with identical code, keeping the first occurrence."""
    seen: set[str] = set()
    unique: list[Candidate] = []
    for c in candidates:
        normalized = c.code.strip()
        if normalized not in seen:
            seen.add(normalized)
            unique.append(c)
    return unique
