"""Multi-candidate solution generation.

Generates N candidate solutions for an exercise using temperature and prompt
diversity. Each candidate is a complete implementation file.
"""

from __future__ import annotations

from dataclasses import dataclass

from pm_core.bench._utils import extract_code
from pm_core.bench.exercises import Exercise
from pm_core.bench.runner import GenerationResult, Runner

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
    starter = "\n".join(exercise.starter_code.values())
    parts = [
        f"Language: {exercise.language}",
        f"\n## Problem Description\n{exercise.description}",
        f"\n## Starter Code\n```\n{starter}\n```",
    ]
    if tests and variant == "test_driven":
        parts.append(f"\n## Tests\n```\n{tests}\n```")
    parts.append(f"\n## Instructions\n{instruction}")
    return "\n".join(parts)


def generate_candidates(
    exercise: Exercise,
    runner: Runner,
    model: str,
    *,
    num_candidates: int = 8,
    temperatures: list[float] | None = None,
    tests: str = "",
) -> list[Candidate]:
    """Generate N candidate solutions for an exercise.

    Distributes candidates across temperature values and prompt variants
    for diversity.
    """
    if temperatures is None:
        if num_candidates == 1:
            temperatures = [0.0]
        else:
            step = 1.0 / max(num_candidates - 1, 1)
            temperatures = [round(i * step, 2) for i in range(num_candidates)]

    variants = list(PROMPT_VARIANTS.keys())

    # Build all requests up front so they can run in parallel
    request_specs: list[tuple[str, float]] = []  # (variant, temperature)
    requests: list[tuple[list[dict[str, str]], float]] = []
    for i in range(num_candidates):
        temp = temperatures[i % len(temperatures)]
        variant = variants[i % len(variants)]
        prompt = _build_prompt(exercise, variant, tests=tests)
        request_specs.append((variant, temp))
        requests.append(([{"role": "user", "content": prompt}], temp))

    gen_results = runner.complete_batch(model=model, requests=requests)

    candidates: list[Candidate] = []
    for (variant, temp), result in zip(request_specs, gen_results):
        code = extract_code(result.content)
        candidates.append(Candidate(
            code=code,
            temperature=temp,
            prompt_variant=variant,
            model=model,
            generation_result=result,
        ))

    return candidates
