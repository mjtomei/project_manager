"""Ollama model runner — send prompts and collect responses."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

DEFAULT_BASE_URL = "http://localhost:11434"


@dataclass
class GenerationResult:
    """Result from a single LLM generation."""
    text: str
    model: str
    temperature: float
    prompt_tokens: int
    completion_tokens: int
    elapsed_s: float


def generate(
    prompt: str,
    model: str = "qwen3:32b",
    temperature: float = 0.7,
    base_url: str = DEFAULT_BASE_URL,
    timeout_s: float = 120.0,
) -> GenerationResult:
    """Generate a completion from an Ollama model.

    Calls POST /api/generate with stream=false and returns the full response.
    """
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": temperature},
    }).encode()

    req = urllib.request.Request(
        f"{base_url}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )

    t0 = time.monotonic()
    resp = urllib.request.urlopen(req, timeout=timeout_s)
    elapsed = time.monotonic() - t0

    body = json.loads(resp.read())
    return GenerationResult(
        text=body.get("response", ""),
        model=body.get("model", model),
        temperature=temperature,
        prompt_tokens=body.get("prompt_eval_count", 0),
        completion_tokens=body.get("eval_count", 0),
        elapsed_s=elapsed,
    )


def generate_batch(
    prompt: str,
    model: str = "qwen3:32b",
    temperatures: list[float] | None = None,
    base_url: str = DEFAULT_BASE_URL,
    timeout_s: float = 120.0,
) -> list[GenerationResult]:
    """Generate completions at multiple temperatures sequentially.

    Returns one result per temperature value.
    """
    if temperatures is None:
        temperatures = [0.2, 0.5, 0.8]

    results = []
    for temp in temperatures:
        result = generate(
            prompt=prompt,
            model=model,
            temperature=temp,
            base_url=base_url,
            timeout_s=timeout_s,
        )
        results.append(result)
    return results


def list_models(base_url: str = DEFAULT_BASE_URL) -> list[dict]:
    """List available Ollama models.

    Returns list of dicts with 'name' and 'size' keys.
    """
    req = urllib.request.Request(f"{base_url}/api/tags")
    resp = urllib.request.urlopen(req, timeout=10)
    body = json.loads(resp.read())
    return [
        {"name": m["name"], "size": m.get("size", 0)}
        for m in body.get("models", [])
    ]


def check_connection(base_url: str = DEFAULT_BASE_URL) -> bool:
    """Check if Ollama is running and reachable."""
    try:
        req = urllib.request.Request(f"{base_url}/api/tags")
        urllib.request.urlopen(req, timeout=5)
        return True
    except (urllib.error.URLError, OSError):
        return False
