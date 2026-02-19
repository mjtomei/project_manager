"""Tests for bench runner — local model runner with OpenAI-compatible API."""

import json
import urllib.error
from unittest import mock

import pytest

from pm_core.bench.runner import (
    Backend,
    CostMetrics,
    GenerationResult,
    RequestStats,
    Runner,
    _get_server_url,
    _probe_health,
    chat_completion,
    detect_backend,
    generate_multiple,
    list_models,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_urlopen(body: dict, status: int = 200):
    """Create a mock urlopen context manager returning JSON body."""
    raw = json.dumps(body).encode()
    resp = mock.MagicMock()
    resp.read.return_value = raw
    resp.status = status
    resp.__enter__ = mock.Mock(return_value=resp)
    resp.__exit__ = mock.Mock(return_value=False)
    return resp


def _chat_response(content: str = "Hello!", model: str = "test-model",
                   prompt_tokens: int = 10, completion_tokens: int = 5):
    """Build a standard OpenAI chat completion response dict."""
    return {
        "id": "chatcmpl-abc",
        "object": "chat.completion",
        "model": model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": content},
            "finish_reason": "stop",
        }],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


# ---------------------------------------------------------------------------
# Backend detection
# ---------------------------------------------------------------------------

class TestDetectBackend:
    def test_returns_none_when_nothing_running(self):
        with mock.patch("pm_core.bench.runner._probe_health", return_value=False):
            assert detect_backend() is None

    def test_detects_llama_cpp_on_macos(self):
        with mock.patch("pm_core.bench.runner.platform.system", return_value="Darwin"), \
             mock.patch("pm_core.bench.runner._probe_health") as probe:
            probe.side_effect = lambda url: "8080" in url
            result = detect_backend()
            assert result == Backend.LLAMA_CPP

    def test_detects_sglang_on_linux(self):
        with mock.patch("pm_core.bench.runner.platform.system", return_value="Linux"), \
             mock.patch("pm_core.bench.runner._probe_health") as probe:
            probe.side_effect = lambda url: "30000" in url
            result = detect_backend()
            assert result == Backend.SGLANG

    def test_detects_vllm_on_linux_when_sglang_down(self):
        with mock.patch("pm_core.bench.runner.platform.system", return_value="Linux"), \
             mock.patch("pm_core.bench.runner._probe_health") as probe:
            probe.side_effect = lambda url: "8000" in url
            result = detect_backend()
            assert result == Backend.VLLM

    def test_env_backend_override(self):
        with mock.patch.dict("os.environ", {"PM_BENCH_BACKEND": "vllm"}), \
             mock.patch("pm_core.bench.runner._probe_health", return_value=True):
            result = detect_backend()
            assert result == Backend.VLLM

    def test_env_backend_returned_even_if_unhealthy(self):
        with mock.patch.dict("os.environ", {"PM_BENCH_BACKEND": "sglang"}), \
             mock.patch("pm_core.bench.runner._probe_health", return_value=False):
            result = detect_backend()
            assert result == Backend.SGLANG

    def test_env_backend_invalid_returns_none(self):
        with mock.patch.dict("os.environ", {"PM_BENCH_BACKEND": "not-a-backend"}), \
             mock.patch("pm_core.bench.runner._probe_health", return_value=True):
            assert detect_backend() is None


# ---------------------------------------------------------------------------
# Server URL
# ---------------------------------------------------------------------------

class TestGetServerUrl:
    def test_defaults(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            assert _get_server_url(Backend.LLAMA_CPP) == "http://localhost:8080"
            assert _get_server_url(Backend.SGLANG) == "http://localhost:30000"
            assert _get_server_url(Backend.VLLM) == "http://localhost:8000"

    def test_env_override(self):
        with mock.patch.dict("os.environ", {"PM_BENCH_URL": "http://myhost:9999/"}):
            assert _get_server_url(Backend.LLAMA_CPP) == "http://myhost:9999"


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

class TestProbeHealth:
    def test_healthy_server(self):
        with mock.patch("urllib.request.urlopen", return_value=_mock_urlopen({"data": []})):
            assert _probe_health("http://localhost:8080") is True

    def test_unhealthy_server(self):
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
            assert _probe_health("http://localhost:8080") is False

    def test_timeout(self):
        with mock.patch("urllib.request.urlopen", side_effect=TimeoutError):
            assert _probe_health("http://localhost:8080") is False


# ---------------------------------------------------------------------------
# List models
# ---------------------------------------------------------------------------

class TestListModels:
    def test_returns_model_list(self):
        body = {
            "object": "list",
            "data": [
                {"id": "qwen3-32b", "object": "model"},
                {"id": "llama-3.1-8b", "object": "model"},
            ]
        }
        with mock.patch("urllib.request.urlopen", return_value=_mock_urlopen(body)):
            models = list_models("http://localhost:8080")
            assert len(models) == 2
            assert models[0]["id"] == "qwen3-32b"

    def test_empty_model_list(self):
        with mock.patch("urllib.request.urlopen", return_value=_mock_urlopen({"data": []})):
            assert list_models("http://localhost:8080") == []


# ---------------------------------------------------------------------------
# Chat completion
# ---------------------------------------------------------------------------

class TestChatCompletion:
    def test_basic_completion(self):
        body = _chat_response("Hello world!", prompt_tokens=15, completion_tokens=3)
        with mock.patch("urllib.request.urlopen", return_value=_mock_urlopen(body)):
            result = chat_completion(
                "http://localhost:8080",
                model="test-model",
                messages=[{"role": "user", "content": "Hi"}],
                temperature=0.5,
            )
            assert result.content == "Hello world!"
            assert result.model == "test-model"
            assert result.temperature == 0.5
            assert result.finish_reason == "stop"
            assert result.stats.prompt_tokens == 15
            assert result.stats.completion_tokens == 3
            assert result.stats.total_tokens == 18
            assert result.stats.wall_clock_seconds > 0

    def test_sends_correct_payload(self):
        body = _chat_response()
        with mock.patch("urllib.request.urlopen", return_value=_mock_urlopen(body)) as mock_open:
            chat_completion(
                "http://localhost:8080",
                model="qwen3-32b",
                messages=[{"role": "user", "content": "test"}],
                temperature=0.3,
                max_tokens=2048,
            )
            call_args = mock_open.call_args
            req = call_args[0][0]
            assert "v1/chat/completions" in req.full_url
            payload = json.loads(req.data)
            assert payload["model"] == "qwen3-32b"
            assert payload["temperature"] == 0.3
            assert payload["max_tokens"] == 2048


# ---------------------------------------------------------------------------
# Parallel generation
# ---------------------------------------------------------------------------

class TestGenerateMultiple:
    def test_generates_at_multiple_temperatures(self):
        responses = [
            _chat_response(f"Response at temp {t}", completion_tokens=10 + i)
            for i, t in enumerate([0.0, 0.5, 1.0])
        ]
        call_count = 0

        def fake_urlopen(req, timeout=None):
            nonlocal call_count
            idx = call_count % len(responses)
            call_count += 1
            return _mock_urlopen(responses[idx])

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            results = generate_multiple(
                "http://localhost:8080",
                model="test-model",
                messages=[{"role": "user", "content": "Hi"}],
                temperatures=[0.0, 0.5, 1.0],
            )

        assert len(results) == 3
        for r in results:
            assert isinstance(r, GenerationResult)
            assert r.content.startswith("Response at temp")

    def test_single_temperature(self):
        body = _chat_response("Solo")
        with mock.patch("urllib.request.urlopen", return_value=_mock_urlopen(body)):
            results = generate_multiple(
                "http://localhost:8080",
                model="m",
                messages=[{"role": "user", "content": "Hi"}],
                temperatures=[0.7],
            )
        assert len(results) == 1
        assert results[0].content == "Solo"


# ---------------------------------------------------------------------------
# Runner class
# ---------------------------------------------------------------------------

class TestRunner:
    def test_create_auto_detect(self):
        with mock.patch("pm_core.bench.runner.detect_backend", return_value=Backend.LLAMA_CPP), \
             mock.patch.dict("os.environ", {}, clear=True):
            runner = Runner.create()
            assert runner.backend == Backend.LLAMA_CPP
            assert runner.base_url == "http://localhost:8080"

    def test_create_explicit_backend(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            runner = Runner.create(backend=Backend.SGLANG)
            assert runner.backend == Backend.SGLANG
            assert runner.base_url == "http://localhost:30000"

    def test_create_raises_when_no_backend(self):
        with mock.patch("pm_core.bench.runner.detect_backend", return_value=None):
            with pytest.raises(RuntimeError, match="No local inference backend"):
                Runner.create()

    def test_aggregate_stats(self):
        runner = Runner(backend=Backend.LLAMA_CPP, base_url="http://localhost:8080")
        results = [
            GenerationResult(stats=RequestStats(10, 5, 15, 1.0)),
            GenerationResult(stats=RequestStats(10, 8, 18, 2.0)),
            GenerationResult(stats=RequestStats(10, 3, 13, 0.5)),
        ]
        total = runner.aggregate_stats(results)
        assert total.prompt_tokens == 30
        assert total.completion_tokens == 16
        assert total.total_tokens == 46
        assert total.wall_clock_seconds == 3.5


# ---------------------------------------------------------------------------
# CostMetrics
# ---------------------------------------------------------------------------

class TestCostMetrics:
    def test_record_accumulates(self):
        metrics = CostMetrics()
        r1 = GenerationResult(stats=RequestStats(10, 5, 15, 1.0))
        r2 = GenerationResult(stats=RequestStats(20, 10, 30, 2.0))
        metrics.record(r1)
        metrics.record(r2)
        assert metrics.total_tokens == 45
        assert metrics.num_requests == 2
        assert metrics.total_wall_clock_seconds == 3.0
