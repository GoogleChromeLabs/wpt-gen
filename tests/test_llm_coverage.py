# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Tests for LLM coverage analysis."""

from unittest.mock import MagicMock, patch

import anthropic
import httpx
import pytest

from wptgen.llm import (
    AnthropicClient,
    GeminiClient,
    LLMTimeoutError,
    OpenAIClient,
)


@patch.object(GeminiClient, "verify_model")
def test_gemini_count_tokens_timeout(mock_verify: MagicMock) -> None:
    llm = GeminiClient(api_key="test", model="test-model", timeout=1)
    llm.client = MagicMock()
    llm.client.models.count_tokens.side_effect = httpx.TimeoutException(
        "timeout"
    )
    with pytest.raises(LLMTimeoutError):
        llm.count_tokens("prompt")


@patch.object(GeminiClient, "verify_model")
def test_gemini_prompt_exceeds_input_token_limit_timeout(
    mock_verify: MagicMock,
) -> None:
    llm = GeminiClient(api_key="test", model="test-model", timeout=1)
    llm.client = MagicMock()
    llm.client.models.count_tokens.return_value = MagicMock(total_tokens=10)
    llm.client.models.get.side_effect = httpx.TimeoutException("timeout")
    with pytest.raises(LLMTimeoutError):
        llm.prompt_exceeds_input_token_limit("prompt")


@patch.object(GeminiClient, "verify_model")
def test_gemini_generate_content_no_usage_metadata(
    mock_verify: MagicMock,
) -> None:
    llm = GeminiClient(api_key="test", model="test-model")
    llm.client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.text = "test response"
    del mock_resp.usage_metadata
    llm.client.models.generate_content.return_value = mock_resp
    llm.generate_content("prompt")


@patch.object(OpenAIClient, "verify_model")
def test_openai_generate_content_no_usage(mock_verify: MagicMock) -> None:
    llm = OpenAIClient(api_key="test", model="test-model")
    llm.client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.choices[0].message.content = "test response"
    del mock_resp.usage
    llm.client.chat.completions.create.return_value = mock_resp
    llm.generate_content("prompt")


@patch.object(AnthropicClient, "verify_model")
def test_anthropic_count_tokens_timeout(mock_verify: MagicMock) -> None:
    llm = AnthropicClient(api_key="test", model="test-model", timeout=1)
    llm.client = MagicMock()
    llm.client.messages.count_tokens.side_effect = anthropic.APITimeoutError(
        request=MagicMock()
    )
    with pytest.raises(LLMTimeoutError):
        llm.count_tokens("prompt")


@patch.object(AnthropicClient, "verify_model")
def test_anthropic_generate_content_timeout(mock_verify: MagicMock) -> None:
    llm = AnthropicClient(api_key="test", model="test-model", timeout=1)
    llm.client = MagicMock()
    llm.client.messages.create.side_effect = anthropic.APITimeoutError(
        request=MagicMock()
    )
    with pytest.raises(LLMTimeoutError):
        llm.generate_content("prompt")


@patch.object(AnthropicClient, "verify_model")
def test_anthropic_generate_content_no_text(mock_verify: MagicMock) -> None:
    llm = AnthropicClient(api_key="test", model="test-model")
    llm.client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.content = [MagicMock(text=123)]
    llm.client.messages.create.return_value = mock_resp
    with pytest.raises(ValueError, match="Anthropic API returned no text"):
        llm.generate_content("prompt")


@patch.object(AnthropicClient, "verify_model")
def test_anthropic_generate_content_no_usage(mock_verify: MagicMock) -> None:
    llm = AnthropicClient(api_key="test", model="test-model")
    llm.client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.content = [MagicMock(text="test content")]
    del mock_resp.usage
    llm.client.messages.create.return_value = mock_resp
    llm.generate_content("prompt")
