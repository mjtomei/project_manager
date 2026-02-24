"""Multi-candidate solution generation.

Generates N candidate solutions for an exercise using temperature and prompt
diversity. Each candidate is a complete implementation file.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pm_core.bench._utils import extract_code
from pm_core.bench.exercises import Exercise
from pm_core.bench.runner import GenerationResult, Runner
from pm_core.bench.test_gen import sample_test_subset, split_test_functions

# Extra request body params: enable reasoning and give the full token budget.
_SOLVE_EXTRA_BODY: dict[str, Any] = {
    "chat_template_kwargs": {"reasoning_effort": "high"},
    "max_completion_tokens": 32768,
}

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
class HyperParams:
    """Per-run hyperparameter overrides.

    ``None``/``False`` fields mean "use existing default behavior" — fully
    backward compatible.
    """

    variant: str | None = None
    temperature: float | None = None
    chain: bool = False
    test_subset_size: int | None = None

    def validate(self) -> None:
        """Raise ``ValueError`` on invalid combinations."""
        if self.variant is not None and self.variant not in PROMPT_VARIANTS:
            raise ValueError(
                f"Unknown variant '{self.variant}'. "
                f"Choose from: {', '.join(PROMPT_VARIANTS)}"
            )
        if self.temperature is not None and not 0.0 <= self.temperature <= 2.0:
            raise ValueError(
                f"Temperature must be between 0.0 and 2.0, got {self.temperature}"
            )
        if self.test_subset_size is not None and self.test_subset_size < 1:
            raise ValueError(
                f"test_subset_size must be >= 1, got {self.test_subset_size}"
            )


def _build_chain_context(prior_solutions: list[str]) -> str:
    """Format prior solutions into a prompt suffix for chain mode."""
    parts = [
        "\n## Previous Attempts",
        "The following solutions were already tried. "
        "Try a DIFFERENT approach:\n",
    ]
    for i, sol in enumerate(prior_solutions, 1):
        parts.append(f"### Attempt {i}\n```\n{sol}\n```\n")
    return "\n".join(parts)


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
    starter_parts = []
    for filename, code in exercise.starter_code.items():
        starter_parts.append(f"# {filename}\n{code}")
    starter = "\n".join(starter_parts)
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
    hyper: HyperParams | None = None,
) -> list[Candidate]:
    """Generate N candidate solutions for an exercise.

    Distributes candidates across temperature values and prompt variants
    for diversity.  When *hyper* is provided, its overrides take precedence.
    """
    if temperatures is None:
        if hyper and hyper.temperature is not None:
            temperatures = [hyper.temperature] * num_candidates
        elif num_candidates == 1:
            temperatures = [0.0]
        else:
            step = 1.0 / max(num_candidates - 1, 1)
            temperatures = [round(i * step, 2) for i in range(num_candidates)]

    variants = list(PROMPT_VARIANTS.keys())

    # Optionally split tests for per-candidate subsets
    test_subsets: list[str] | None = None
    if hyper and hyper.test_subset_size is not None and tests:
        header, funcs = split_test_functions(tests, exercise.language)
        if funcs and hyper.test_subset_size < len(funcs):
            test_subsets = [
                sample_test_subset(funcs, header, hyper.test_subset_size)
                for _ in range(num_candidates)
            ]

    # Build per-candidate specs
    request_specs: list[tuple[str, float]] = []  # (variant, temperature)
    requests: list[tuple[list[dict[str, str]], float]] = []
    for i in range(num_candidates):
        temp = temperatures[i % len(temperatures)]
        variant = (
            hyper.variant if (hyper and hyper.variant) else variants[i % len(variants)]
        )
        candidate_tests = test_subsets[i] if test_subsets else tests
        prompt = _build_prompt(exercise, variant, tests=candidate_tests)
        request_specs.append((variant, temp))
        requests.append(([{"role": "user", "content": prompt}], temp))

    # Chain mode: generate sequentially, each candidate sees prior solutions
    if hyper and hyper.chain:
        candidates: list[Candidate] = []
        prior_solutions: list[str] = []
        for (variant, temp), (msgs, _) in zip(request_specs, requests):
            if prior_solutions:
                chain_suffix = _build_chain_context(prior_solutions)
                msgs = [{"role": "user", "content": msgs[0]["content"] + chain_suffix}]
            result = runner.complete(model=model, messages=msgs, temperature=temp,
                                       extra_body=_SOLVE_EXTRA_BODY)
            code = extract_code(result.content)
            prior_solutions.append(code)
            candidates.append(Candidate(
                code=code,
                temperature=temp,
                prompt_variant=variant,
                model=model,
                generation_result=result,
            ))
        return candidates

    # Default: parallel batch generation
    gen_results = runner.complete_batch(model=model, requests=requests,
                                           extra_body=_SOLVE_EXTRA_BODY)

    candidates = []
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
