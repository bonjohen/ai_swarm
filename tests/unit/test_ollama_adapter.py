"""Tests for core.adapters — OllamaAdapter, factory, and make_model_call."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from core.adapters import OllamaAdapter, make_model_call, make_ollama_adapter
from core.errors import ModelAPIError


# ---------------------------------------------------------------------------
# OllamaAdapter.call — success
# ---------------------------------------------------------------------------

@patch("core.adapters.httpx.post")
def test_call_success(mock_post: MagicMock) -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"message": {"content": "hello world"}}
    mock_post.return_value = mock_resp

    adapter = OllamaAdapter(model="test-model", host="http://myhost:11434")
    result = adapter.call("sys prompt", "user msg")

    assert result == "hello world"

    # Verify the request payload
    call_kwargs = mock_post.call_args
    assert call_kwargs[0][0] == "http://myhost:11434/api/chat"
    payload = call_kwargs[1]["json"]
    assert payload["model"] == "test-model"
    assert payload["stream"] is False
    assert payload["messages"][0]["role"] == "system"
    assert payload["messages"][0]["content"] == "sys prompt"
    assert payload["messages"][1]["role"] == "user"
    assert payload["messages"][1]["content"] == "user msg"


@patch("core.adapters.httpx.post")
def test_call_correct_endpoint_trailing_slash(mock_post: MagicMock) -> None:
    """Host with trailing slash should not produce double-slash in URL."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"message": {"content": "ok"}}
    mock_post.return_value = mock_resp

    adapter = OllamaAdapter(host="http://localhost:11434/")
    adapter.call("s", "u")

    url = mock_post.call_args[0][0]
    assert url == "http://localhost:11434/api/chat"


# ---------------------------------------------------------------------------
# OllamaAdapter.call — error cases
# ---------------------------------------------------------------------------

@patch("core.adapters.httpx.post")
def test_timeout_retryable(mock_post: MagicMock) -> None:
    mock_post.side_effect = httpx.TimeoutException("timed out")

    adapter = OllamaAdapter()
    with pytest.raises(ModelAPIError) as exc_info:
        adapter.call("s", "u")
    assert exc_info.value.retryable is True
    assert "Timeout" in str(exc_info.value)


@patch("core.adapters.httpx.post")
def test_connect_error_retryable(mock_post: MagicMock) -> None:
    mock_post.side_effect = httpx.ConnectError("refused")

    adapter = OllamaAdapter()
    with pytest.raises(ModelAPIError) as exc_info:
        adapter.call("s", "u")
    assert exc_info.value.retryable is True
    assert "Connection error" in str(exc_info.value)


@pytest.mark.parametrize("status_code", [429, 500, 502, 503])
@patch("core.adapters.httpx.post")
def test_retryable_http_errors(mock_post: MagicMock, status_code: int) -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.text = "error body"
    mock_post.return_value = mock_resp

    adapter = OllamaAdapter()
    with pytest.raises(ModelAPIError) as exc_info:
        adapter.call("s", "u")
    assert exc_info.value.retryable is True


@patch("core.adapters.httpx.post")
def test_http_400_not_retryable(mock_post: MagicMock) -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 400
    mock_resp.text = "bad request"
    mock_post.return_value = mock_resp

    adapter = OllamaAdapter()
    with pytest.raises(ModelAPIError) as exc_info:
        adapter.call("s", "u")
    assert exc_info.value.retryable is False


@patch("core.adapters.httpx.post")
def test_malformed_response_not_retryable(mock_post: MagicMock) -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"unexpected": "shape"}
    mock_post.return_value = mock_resp

    adapter = OllamaAdapter()
    with pytest.raises(ModelAPIError) as exc_info:
        adapter.call("s", "u")
    assert exc_info.value.retryable is False
    assert "Malformed" in str(exc_info.value)


# ---------------------------------------------------------------------------
# make_ollama_adapter factory
# ---------------------------------------------------------------------------

def test_factory_defaults() -> None:
    adapter = make_ollama_adapter()
    assert adapter.model == "llama3:8b-instruct-q8_0"
    assert adapter.host == "http://localhost:11434"
    assert adapter.temperature == 0.2
    assert adapter.timeout == 300.0


def test_factory_explicit_args() -> None:
    adapter = make_ollama_adapter(
        model="deepseek-r1:1.5b", host="http://gpu:9999",
        temperature=0.5, timeout=30.0,
    )
    assert adapter.model == "deepseek-r1:1.5b"
    assert adapter.host == "http://gpu:9999"
    assert adapter.temperature == 0.5
    assert adapter.timeout == 30.0


@patch.dict("os.environ", {"OLLAMA_MODEL": "env-model", "OLLAMA_HOST": "http://env:1234"})
def test_factory_env_vars() -> None:
    adapter = make_ollama_adapter()
    assert adapter.model == "env-model"
    assert adapter.host == "http://env:1234"


@patch.dict("os.environ", {"OLLAMA_MODEL": "env-model"})
def test_factory_explicit_overrides_env() -> None:
    adapter = make_ollama_adapter(model="explicit-model")
    assert adapter.model == "explicit-model"


# ---------------------------------------------------------------------------
# make_model_call dispatcher
# ---------------------------------------------------------------------------

def test_make_model_call_stub() -> None:
    fn = make_model_call("stub")
    with pytest.raises(NotImplementedError):
        fn("s", "u")


@patch("core.adapters.httpx.post")
def test_make_model_call_ollama(mock_post: MagicMock) -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"message": {"content": "response"}}
    mock_post.return_value = mock_resp

    fn = make_model_call("ollama")
    result = fn("sys", "user")
    assert result == "response"


@patch("core.adapters.httpx.post")
def test_make_model_call_ollama_with_model(mock_post: MagicMock) -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"message": {"content": "ok"}}
    mock_post.return_value = mock_resp

    fn = make_model_call("ollama:deepseek-r1:1.5b")
    fn("sys", "user")

    # Verify model name preserved colons
    payload = mock_post.call_args[1]["json"]
    assert payload["model"] == "deepseek-r1:1.5b"


def test_make_model_call_unknown_raises() -> None:
    with pytest.raises(ValueError, match="Unknown model-call mode"):
        make_model_call("gpt4")
