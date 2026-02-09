"""Local model runner with Ollama integration.

Manages LLM inference via Ollama's HTTP API. Tracks token counts and
wall-clock time per request for downstream cost analysis.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field


@dataclass
class GenerationResult:
    """Result from a single LLM generation."""

    text: str
    model: str
    temperature: float
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    wall_clock_seconds: float = 0.0


@dataclass
class CostMetrics:
    """Accumulated cost metrics across multiple generations."""

    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_tokens: int = 0
    total_wall_clock_seconds: float = 0.0
    num_requests: int = 0

    def record(self, result: GenerationResult) -> None:
        self.total_prompt_tokens += result.prompt_tokens
        self.total_completion_tokens += result.completion_tokens
        self.total_tokens += result.total_tokens
        self.total_wall_clock_seconds += result.wall_clock_seconds
        self.num_requests += 1


class OllamaRunner:
    """Ollama API client for local LLM inference."""

    def __init__(self, base_url: str = "http://localhost:11434") -> None:
        self.base_url = base_url.rstrip("/")
        self.metrics = CostMetrics()

    def _request(self, path: str, payload: dict | None = None) -> dict:
        url = f"{self.base_url}{path}"
        if payload is not None:
            data = json.dumps(payload).encode()
            req = urllib.request.Request(
                url, data=data, headers={"Content-Type": "application/json"}
            )
        else:
            req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=300) as resp:
            return json.loads(resp.read())

    def list_models(self) -> list[str]:
        """List available models from Ollama."""
        resp = self._request("/api/tags")
        return [m["name"] for m in resp.get("models", [])]

    def generate(
        self,
        model: str,
        prompt: str,
        *,
        system: str = "",
        temperature: float = 0.7,
    ) -> GenerationResult:
        """Generate a completion from the model."""
        payload: dict = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature},
        }
        if system:
            payload["system"] = system

        start = time.monotonic()
        try:
            resp = self._request("/api/generate", payload)
        except (urllib.error.URLError, OSError) as exc:
            raise ConnectionError(
                f"Cannot reach Ollama at {self.base_url}: {exc}"
            ) from exc
        elapsed = time.monotonic() - start

        prompt_tokens = resp.get("prompt_eval_count", 0)
        completion_tokens = resp.get("eval_count", 0)

        result = GenerationResult(
            text=resp.get("response", ""),
            model=model,
            temperature=temperature,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            wall_clock_seconds=elapsed,
        )
        self.metrics.record(result)
        return result

    def is_available(self) -> bool:
        """Check if Ollama is reachable."""
        try:
            self._request("/api/tags")
            return True
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            return False
