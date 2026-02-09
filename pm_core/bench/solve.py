"""Multi-candidate solution generation.

Generates N candidate solutions for an exercise using temperature and prompt
diversity. Each candidate is a complete implementation file.
"""

from __future__ import annotations

from dataclasses import dataclass

from pm_core.bench.exercises import Exercise
from pm_core.bench.runner import GenerationResult, OllamaRunner

PROMPT_VARIANTS = {
    "direct": (
        "Implement the solution. Write ONLY the code — no explanations, "
        "no markdown fences. Output a complete, working source file."
    ),
    "chain_of_thought": (
        "Think step by step about how to solve this problem, then write "
        "the complete implementation. Output ONLY the final code — no "
        "explanations or markdown fences."
    ),
    "test_driven": (
        "The tests below show the expected behavior. Implement the code "
        "to pass all tests. Write ONLY the code — no explanations, no "
        "markdown fences."
    ),
}


@dataclass
class Candidate:
    """A single candidate solution."""

    code: str
    temperature: float
    prompt_variant: str
    model: str
    generation_result: GenerationResult


def _build_prompt(exercise: Exercise, variant: str, tests: str = "") -> str:
    instruction = PROMPT_VARIANTS[variant]
    parts = [
        f"Language: {exercise.language}",
        f"\n## Problem Description\n{exercise.description}",
        f"\n## Starter Code\n```\n{exercise.starter_code}\n```",
    ]
    if tests and variant == "test_driven":
        parts.append(f"\n## Tests\n```\n{tests}\n```")
    parts.append(f"\n## Instructions\n{instruction}")
    return "\n".join(parts)


def generate_candidates(
    exercise: Exercise,
    runner: OllamaRunner,
    model: str,
    *,
    num_candidates: int = 8,
    temperatures: list[float] | None = None,
    tests: str = "",
) -> list[Candidate]:
    """Generate N candidate solutions for an exercise.

    Distributes candidates across temperature values and prompt variants
    for diversity.

    Args:
        exercise: The exercise to solve.
        runner: Ollama runner instance.
        model: Model name.
        num_candidates: Number of candidates to generate.
        temperatures: Custom temperature schedule. Default spreads 0.0–1.0.
        tests: Optional generated tests to include in test_driven prompts.
    """
    if temperatures is None:
        if num_candidates == 1:
            temperatures = [0.0]
        else:
            step = 1.0 / max(num_candidates - 1, 1)
            temperatures = [round(i * step, 2) for i in range(num_candidates)]

    variants = list(PROMPT_VARIANTS.keys())
    candidates: list[Candidate] = []

    for i in range(num_candidates):
        temp = temperatures[i % len(temperatures)]
        variant = variants[i % len(variants)]
        prompt = _build_prompt(exercise, variant, tests=tests)

        result = runner.generate(model, prompt, temperature=temp)
        code = _extract_code(result.text)

        candidates.append(Candidate(
            code=code,
            temperature=temp,
            prompt_variant=variant,
            model=model,
            generation_result=result,
        ))

    return candidates


def _extract_code(text: str) -> str:
    """Extract code from model response, stripping markdown fences if present."""
    lines = text.strip().split("\n")
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
        for i in range(len(lines) - 1, -1, -1):
            if lines[i].strip() == "```":
                lines = lines[:i]
                break
    return "\n".join(lines)
