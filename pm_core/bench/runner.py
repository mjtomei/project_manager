"""Local model runner with OpenAI-compatible API.

Manages local LLM inference via the OpenAI-compatible chat/completions
endpoint exposed by local serving backends:
  - llama.cpp server (macOS default)
  - sglang (Linux)
  - vllm (Linux)

All three expose the same /v1/chat/completions endpoint, so the core runner
uses a single HTTP client with backend-specific server management.
"""

import asyncio
import json
import os
import platform
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from urllib.parse import urljoin


class Backend(Enum):
    LLAMA_CPP = "llama.cpp"
    SGLANG = "sglang"
    VLLM = "vllm"


# Default URLs per backend
_DEFAULT_URLS: dict[Backend, str] = {
    Backend.LLAMA_CPP: "http://localhost:8080",
    Backend.SGLANG: "http://localhost:30000",
    Backend.VLLM: "http://localhost:8000",
}

# Backend probe order per platform
_PLATFORM_BACKENDS: dict[str, list[Backend]] = {
    "Darwin": [Backend.LLAMA_CPP],
    "Linux": [Backend.SGLANG, Backend.VLLM, Backend.LLAMA_CPP],
}


@dataclass
class RequestStats:
    """Token counts and timing for a single completion request."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    wall_clock_seconds: float = 0.0


@dataclass
class GenerationResult:
    """Result of a single chat completion generation."""
    content: str = ""
    model: str = ""
    temperature: float = 0.0
    stats: RequestStats = field(default_factory=RequestStats)
    finish_reason: str = ""


@dataclass
class CostMetrics:
    """Accumulated cost metrics across multiple generations."""

    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_tokens: int = 0
    total_wall_clock_seconds: float = 0.0
    num_requests: int = 0

    def record(self, result: GenerationResult) -> None:
        self.total_prompt_tokens += result.stats.prompt_tokens
        self.total_completion_tokens += result.stats.completion_tokens
        self.total_tokens += result.stats.total_tokens
        self.total_wall_clock_seconds += result.stats.wall_clock_seconds
        self.num_requests += 1


def detect_backend() -> Backend | None:
    """Detect which backend is available based on platform and connectivity.

    Checks PM_BENCH_BACKEND env var first, then probes backends in
    platform-appropriate order.
    """
    env_backend = os.environ.get("PM_BENCH_BACKEND", "").lower()
    if env_backend:
        for b in Backend:
            if b.value == env_backend:
                url = _get_server_url(b)
                if _probe_health(url):
                    return b
                return b  # return even if not healthy; user explicitly chose it
        return None

    system = platform.system()
    candidates = _PLATFORM_BACKENDS.get(system, list(Backend))
    for backend in candidates:
        url = _get_server_url(backend)
        if _probe_health(url):
            return backend
    return None


def _get_server_url(backend: Backend) -> str:
    """Get server URL from env var or backend default."""
    env_url = os.environ.get("PM_BENCH_URL")
    if env_url:
        return env_url.rstrip("/")
    return _DEFAULT_URLS[backend].rstrip("/")


def _probe_health(base_url: str, timeout: float = 2.0) -> bool:
    """Check if a server is responding at the given URL."""
    try:
        req = urllib.request.Request(
            urljoin(base_url + "/", "v1/models"),
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=timeout):
            return True
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def list_models(base_url: str, timeout: float = 5.0) -> list[dict[str, Any]]:
    """List models available on the server.

    Returns list of model dicts from the /v1/models endpoint.
    """
    url = urljoin(base_url + "/", "v1/models")
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read())
    return body.get("data", [])


def chat_completion(
    base_url: str,
    *,
    model: str,
    messages: list[dict[str, str]],
    temperature: float = 0.7,
    max_tokens: int = 4096,
    timeout: float = 120.0,
) -> GenerationResult:
    """Send a single chat completion request.

    Uses the standard OpenAI /v1/chat/completions endpoint.
    """
    url = urljoin(base_url + "/", "v1/chat/completions")
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read())
    elapsed = time.monotonic() - t0

    choice = body.get("choices", [{}])[0]
    usage = body.get("usage", {})

    return GenerationResult(
        content=choice.get("message", {}).get("content", ""),
        model=body.get("model", model),
        temperature=temperature,
        stats=RequestStats(
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            wall_clock_seconds=elapsed,
        ),
        finish_reason=choice.get("finish_reason", ""),
    )


def generate_multiple(
    base_url: str,
    *,
    model: str,
    messages: list[dict[str, str]],
    temperatures: list[float],
    max_tokens: int = 4096,
    timeout: float = 120.0,
) -> list[GenerationResult]:
    """Generate multiple completions in parallel with different temperatures.

    Runs all requests concurrently using asyncio.
    """
    return asyncio.run(_generate_multiple_async(
        base_url,
        model=model,
        messages=messages,
        temperatures=temperatures,
        max_tokens=max_tokens,
        timeout=timeout,
    ))


async def _generate_multiple_async(
    base_url: str,
    *,
    model: str,
    messages: list[dict[str, str]],
    temperatures: list[float],
    max_tokens: int,
    timeout: float,
) -> list[GenerationResult]:
    """Async implementation of parallel generation."""
    loop = asyncio.get_event_loop()
    tasks = [
        loop.run_in_executor(
            None,
            lambda t=temp: chat_completion(
                base_url,
                model=model,
                messages=messages,
                temperature=t,
                max_tokens=max_tokens,
                timeout=timeout,
            ),
        )
        for temp in temperatures
    ]
    return list(await asyncio.gather(*tasks))


@dataclass
class Runner:
    """High-level runner that wraps backend detection and server communication.

    Usage:
        runner = Runner.create()  # auto-detect backend
        models = runner.list_models()
        result = runner.complete(model="...", messages=[...])
        results = runner.generate(model="...", messages=[...],
                                  temperatures=[0.0, 0.5, 1.0])
    """
    backend: Backend
    base_url: str
    metrics: CostMetrics = field(default_factory=CostMetrics)

    @classmethod
    def create(cls, backend: Backend | None = None) -> "Runner":
        """Create a runner, auto-detecting backend if not specified."""
        if backend is None:
            backend = detect_backend()
            if backend is None:
                raise RuntimeError(
                    "No local inference backend detected. "
                    "Ensure llama.cpp server (macOS) or sglang/vllm (Linux) "
                    "is running, or set PM_BENCH_URL."
                )
        base_url = _get_server_url(backend)
        return cls(backend=backend, base_url=base_url)

    def health_check(self) -> bool:
        """Check if the backend server is healthy."""
        return _probe_health(self.base_url)

    def list_models(self) -> list[dict[str, Any]]:
        """List models available on the backend."""
        return list_models(self.base_url)

    def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        timeout: float = 120.0,
    ) -> GenerationResult:
        """Run a single chat completion."""
        result = chat_completion(
            self.base_url,
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )
        self.metrics.record(result)
        return result

    def generate(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperatures: list[float],
        max_tokens: int = 4096,
        timeout: float = 120.0,
    ) -> list[GenerationResult]:
        """Generate multiple completions in parallel with different temperatures."""
        results = generate_multiple(
            self.base_url,
            model=model,
            messages=messages,
            temperatures=temperatures,
            max_tokens=max_tokens,
            timeout=timeout,
        )
        for r in results:
            self.metrics.record(r)
        return results

    def aggregate_stats(self, results: list[GenerationResult]) -> RequestStats:
        """Aggregate stats across multiple generation results."""
        total = RequestStats()
        for r in results:
            total.prompt_tokens += r.stats.prompt_tokens
            total.completion_tokens += r.stats.completion_tokens
            total.total_tokens += r.stats.total_tokens
            total.wall_clock_seconds += r.stats.wall_clock_seconds
        return total
