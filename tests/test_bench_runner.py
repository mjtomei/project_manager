"""Tests for pm_core.bench.runner — Ollama model runner."""

import json
from unittest import mock

import pytest

from pm_core.bench.runner import (
    GenerationResult,
    check_connection,
    generate,
    generate_batch,
    list_models,
)


def _mock_urlopen(response_body: dict, status: int = 200):
    """Create a mock for urllib.request.urlopen."""
    mock_resp = mock.Mock()
    mock_resp.read.return_value = json.dumps(response_body).encode()
    mock_resp.status = status
    return mock_resp


class TestGenerate:
    @mock.patch("urllib.request.urlopen")
    def test_returns_generation_result(self, mock_open):
        mock_open.return_value = _mock_urlopen({
            "response": "def test_foo(): pass",
            "model": "qwen3:32b",
            "prompt_eval_count": 50,
            "eval_count": 100,
        })

        result = generate("Write a test", model="qwen3:32b", temperature=0.5)

        assert isinstance(result, GenerationResult)
        assert result.text == "def test_foo(): pass"
        assert result.model == "qwen3:32b"
        assert result.temperature == 0.5
        assert result.prompt_tokens == 50
        assert result.completion_tokens == 100
        assert result.elapsed_s > 0

    @mock.patch("urllib.request.urlopen")
    def test_sends_correct_payload(self, mock_open):
        mock_open.return_value = _mock_urlopen({"response": ""})

        generate("hello", model="llama3", temperature=0.3)

        call_args = mock_open.call_args
        req = call_args[0][0]
        payload = json.loads(req.data)
        assert payload["model"] == "llama3"
        assert payload["prompt"] == "hello"
        assert payload["stream"] is False
        assert payload["options"]["temperature"] == 0.3

    @mock.patch("urllib.request.urlopen")
    def test_handles_missing_fields(self, mock_open):
        mock_open.return_value = _mock_urlopen({"response": "ok"})

        result = generate("test")
        assert result.prompt_tokens == 0
        assert result.completion_tokens == 0


class TestGenerateBatch:
    @mock.patch("urllib.request.urlopen")
    def test_generates_at_each_temperature(self, mock_open):
        mock_open.return_value = _mock_urlopen({
            "response": "test output",
            "prompt_eval_count": 10,
            "eval_count": 20,
        })

        results = generate_batch("prompt", temperatures=[0.2, 0.5, 0.8])

        assert len(results) == 3
        assert results[0].temperature == 0.2
        assert results[1].temperature == 0.5
        assert results[2].temperature == 0.8

    @mock.patch("urllib.request.urlopen")
    def test_default_temperatures(self, mock_open):
        mock_open.return_value = _mock_urlopen({"response": ""})

        results = generate_batch("prompt")
        assert len(results) == 3


class TestListModels:
    @mock.patch("urllib.request.urlopen")
    def test_returns_model_list(self, mock_open):
        mock_open.return_value = _mock_urlopen({
            "models": [
                {"name": "qwen3:32b", "size": 18000000000},
                {"name": "llama3:8b", "size": 4800000000},
            ]
        })

        models = list_models()
        assert len(models) == 2
        assert models[0]["name"] == "qwen3:32b"
        assert models[1]["name"] == "llama3:8b"

    @mock.patch("urllib.request.urlopen")
    def test_empty_model_list(self, mock_open):
        mock_open.return_value = _mock_urlopen({"models": []})
        assert list_models() == []


class TestCheckConnection:
    @mock.patch("urllib.request.urlopen")
    def test_returns_true_when_reachable(self, mock_open):
        mock_open.return_value = _mock_urlopen({"models": []})
        assert check_connection() is True

    @mock.patch("urllib.request.urlopen")
    def test_returns_false_when_unreachable(self, mock_open):
        import urllib.error
        mock_open.side_effect = urllib.error.URLError("connection refused")
        assert check_connection() is False
