"""Tests for extended adapters — tier factories, Anthropic, OpenAI, DGX."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from core.adapters import (
    AnthropicAdapter,
    DGXSparkAdapter,
    OllamaAdapter,
    OpenAIAdapter,
    make_light_adapter,
    make_micro_adapter,
    make_model_call,
)
from core.errors import ModelAPIError


# ---------------------------------------------------------------------------
# OllamaAdapter — max_tokens / context_length in payload
# ---------------------------------------------------------------------------

class TestOllamaAdapterConfig:
    @patch("core.adapters.httpx.post")
    def test_options_include_num_predict_and_num_ctx(self, mock_post: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"message": {"content": "ok"}}
        mock_post.return_value = mock_resp

        adapter = OllamaAdapter(max_tokens=256, context_length=8192)
        adapter.call("sys", "user")

        payload = mock_post.call_args[1]["json"]
        assert payload["options"]["num_predict"] == 256
        assert payload["options"]["num_ctx"] == 8192

    @patch("core.adapters.httpx.post")
    def test_extra_options_merged_after_defaults(self, mock_post: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"message": {"content": "ok"}}
        mock_post.return_value = mock_resp

        adapter = OllamaAdapter(extra_options={"top_k": 40})
        adapter.call("sys", "user")

        opts = mock_post.call_args[1]["json"]["options"]
        assert opts["top_k"] == 40
        assert "num_predict" in opts
        assert "num_ctx" in opts


# ---------------------------------------------------------------------------
# Tier factories
# ---------------------------------------------------------------------------

class TestMicroAdapter:
    def test_factory_config(self) -> None:
        adapter = make_micro_adapter()
        assert adapter.name == "micro"
        assert adapter.model == "deepseek-r1:1.5b"
        assert adapter.context_length == 2048
        assert adapter.max_tokens == 128
        assert adapter.temperature == 0.0


class TestLightAdapter:
    def test_factory_config(self) -> None:
        adapter = make_light_adapter()
        assert adapter.name == "light"
        assert adapter.model == "deepseek-r1:1.5b"
        assert adapter.context_length == 4096
        assert adapter.max_tokens == 1024
        assert adapter.temperature == 0.2


# ---------------------------------------------------------------------------
# make_model_call tier modes
# ---------------------------------------------------------------------------

class TestMakeModelCallTiers:
    @patch("core.adapters.httpx.post")
    def test_tier1_mode(self, mock_post: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"message": {"content": "tier1"}}
        mock_post.return_value = mock_resp

        fn = make_model_call("tier1")
        result = fn("sys", "user")
        assert result == "tier1"
        payload = mock_post.call_args[1]["json"]
        assert payload["model"] == "deepseek-r1:1.5b"
        assert payload["options"]["num_ctx"] == 2048

    @patch("core.adapters.httpx.post")
    def test_tier2_mode(self, mock_post: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"message": {"content": "tier2"}}
        mock_post.return_value = mock_resp

        fn = make_model_call("tier2")
        result = fn("sys", "user")
        assert result == "tier2"
        payload = mock_post.call_args[1]["json"]
        assert payload["model"] == "deepseek-r1:1.5b"
        assert payload["options"]["num_ctx"] == 4096


# ---------------------------------------------------------------------------
# AnthropicAdapter
# ---------------------------------------------------------------------------

class TestAnthropicAdapter:
    @patch("core.adapters.httpx.post")
    def test_call_success(self, mock_post: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "content": [{"type": "text", "text": "hello from claude"}],
        }
        mock_post.return_value = mock_resp

        adapter = AnthropicAdapter(api_key="sk-test", model="claude-test")
        result = adapter.call("system prompt", "user msg")

        assert result == "hello from claude"

        # Verify request format
        call_args = mock_post.call_args
        assert call_args[0][0] == "https://api.anthropic.com/v1/messages"
        headers = call_args[1]["headers"]
        assert headers["x-api-key"] == "sk-test"
        assert headers["anthropic-version"] == "2023-06-01"
        payload = call_args[1]["json"]
        assert payload["system"] == "system prompt"
        assert payload["messages"] == [{"role": "user", "content": "user msg"}]
        assert payload["model"] == "claude-test"

    @patch("core.adapters.httpx.post")
    def test_timeout_error(self, mock_post: MagicMock) -> None:
        mock_post.side_effect = httpx.TimeoutException("timed out")
        adapter = AnthropicAdapter(api_key="sk-test")
        with pytest.raises(ModelAPIError) as exc_info:
            adapter.call("s", "u")
        assert exc_info.value.retryable is True

    @patch("core.adapters.httpx.post")
    def test_connect_error(self, mock_post: MagicMock) -> None:
        mock_post.side_effect = httpx.ConnectError("refused")
        adapter = AnthropicAdapter(api_key="sk-test")
        with pytest.raises(ModelAPIError) as exc_info:
            adapter.call("s", "u")
        assert exc_info.value.retryable is True

    @patch("core.adapters.httpx.post")
    def test_bad_status(self, mock_post: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.text = "bad request"
        mock_post.return_value = mock_resp

        adapter = AnthropicAdapter(api_key="sk-test")
        with pytest.raises(ModelAPIError) as exc_info:
            adapter.call("s", "u")
        assert exc_info.value.retryable is False

    @patch("core.adapters.httpx.post")
    def test_529_overloaded_retryable(self, mock_post: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 529
        mock_resp.text = "overloaded"
        mock_post.return_value = mock_resp

        adapter = AnthropicAdapter(api_key="sk-test")
        with pytest.raises(ModelAPIError) as exc_info:
            adapter.call("s", "u")
        assert exc_info.value.retryable is True

    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": "env-key"})
    def test_api_key_from_env(self) -> None:
        adapter = AnthropicAdapter()
        assert adapter.api_key == "env-key"


# ---------------------------------------------------------------------------
# OpenAIAdapter
# ---------------------------------------------------------------------------

class TestOpenAIAdapter:
    @patch("core.adapters.httpx.post")
    def test_call_success(self, mock_post: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"role": "assistant", "content": "hello from gpt"}}],
        }
        mock_post.return_value = mock_resp

        adapter = OpenAIAdapter(api_key="sk-test", model="gpt-test")
        result = adapter.call("system prompt", "user msg")

        assert result == "hello from gpt"

        # Verify request format
        call_args = mock_post.call_args
        assert call_args[0][0] == "https://api.openai.com/v1/chat/completions"
        headers = call_args[1]["headers"]
        assert headers["Authorization"] == "Bearer sk-test"
        payload = call_args[1]["json"]
        assert payload["messages"][0] == {"role": "system", "content": "system prompt"}
        assert payload["messages"][1] == {"role": "user", "content": "user msg"}

    @patch("core.adapters.httpx.post")
    def test_custom_base_url(self, mock_post: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "ok"}}],
        }
        mock_post.return_value = mock_resp

        adapter = OpenAIAdapter(api_key="k", base_url="http://local:8080/v1/")
        adapter.call("s", "u")

        url = mock_post.call_args[0][0]
        assert url == "http://local:8080/v1/chat/completions"

    @patch("core.adapters.httpx.post")
    def test_timeout_error(self, mock_post: MagicMock) -> None:
        mock_post.side_effect = httpx.TimeoutException("timed out")
        adapter = OpenAIAdapter(api_key="sk-test")
        with pytest.raises(ModelAPIError) as exc_info:
            adapter.call("s", "u")
        assert exc_info.value.retryable is True

    @patch("core.adapters.httpx.post")
    def test_connect_error(self, mock_post: MagicMock) -> None:
        mock_post.side_effect = httpx.ConnectError("refused")
        adapter = OpenAIAdapter(api_key="sk-test")
        with pytest.raises(ModelAPIError) as exc_info:
            adapter.call("s", "u")
        assert exc_info.value.retryable is True

    @patch("core.adapters.httpx.post")
    def test_bad_status(self, mock_post: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.text = "unauthorized"
        mock_post.return_value = mock_resp

        adapter = OpenAIAdapter(api_key="sk-test")
        with pytest.raises(ModelAPIError) as exc_info:
            adapter.call("s", "u")
        assert exc_info.value.retryable is False

    @patch.dict("os.environ", {"OPENAI_API_KEY": "env-key"})
    def test_api_key_from_env(self) -> None:
        adapter = OpenAIAdapter()
        assert adapter.api_key == "env-key"


# ---------------------------------------------------------------------------
# DGXSparkAdapter
# ---------------------------------------------------------------------------

class TestDGXSparkAdapter:
    def test_delegates_to_ollama(self) -> None:
        adapter = DGXSparkAdapter(host="http://dgx:11434", model="llama3:70b")
        assert adapter._inner.host == "http://dgx:11434"
        assert adapter._inner.model == "llama3:70b"
        assert adapter._inner.context_length == 8192
        assert adapter._inner.name == "dgx_spark"

    @patch("core.adapters.httpx.post")
    def test_call_delegates(self, mock_post: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"message": {"content": "dgx response"}}
        mock_post.return_value = mock_resp

        adapter = DGXSparkAdapter()
        result = adapter.call("sys", "user")
        assert result == "dgx response"

        # Verify it used the DGX host
        url = mock_post.call_args[0][0]
        assert "dgx-spark" in url
