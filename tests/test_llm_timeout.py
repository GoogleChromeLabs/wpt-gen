# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import httpx
import openai
import pytest
from google.genai import types
from pytest_mock import MockerFixture

from wptgen.config import DEFAULT_LLM_TIMEOUT, Config
from wptgen.llm import GeminiClient, LLMTimeoutError, OpenAIClient, get_llm_client


@pytest.fixture
def base_config() -> Config:
  return Config(
    provider='gemini',
    default_model='gemini-3.1-pro-preview',
    api_key='mock-key',
    wpt_path='dummy',
    categories={},
    phase_model_mapping={},
    timeout=DEFAULT_LLM_TIMEOUT,
  )


def test_llm_timeout_config_default() -> None:
  """Verify that the default timeout is correctly set in Config."""
  assert DEFAULT_LLM_TIMEOUT == 600
  config = Config(
    provider='gemini',
    default_model='model',
    api_key='key',
    wpt_path='path',
    categories={},
    phase_model_mapping={},
  )
  assert config.timeout == DEFAULT_LLM_TIMEOUT


def test_gemini_client_timeout_passed(mocker: MockerFixture, base_config: Config) -> None:
  """Verify that GeminiClient passes the timeout to the genai.Client."""
  mock_genai_client = mocker.patch('wptgen.llm.genai.Client')
  base_config.timeout = 123

  assert base_config.api_key is not None
  GeminiClient(
    api_key=base_config.api_key, model=base_config.default_model, timeout=base_config.timeout
  )

  mock_genai_client.assert_called_once_with(
    api_key='mock-key', http_options=types.HttpOptions(timeout=123000)
  )


def test_openai_client_timeout_passed(mocker: MockerFixture, base_config: Config) -> None:
  """Verify that OpenAIClient passes the timeout to the OpenAI constructor."""
  mock_openai_class = mocker.patch('wptgen.llm.OpenAI')
  base_config.timeout = 456

  assert base_config.api_key is not None
  OpenAIClient(
    api_key=base_config.api_key, model=base_config.default_model, timeout=base_config.timeout
  )

  mock_openai_class.assert_called_once_with(api_key='mock-key', timeout=456.0)


def test_gemini_timeout_handling(mocker: MockerFixture, base_config: Config) -> None:
  """Verify that GeminiClient catches httpx.TimeoutException and raises LLMTimeoutError."""
  mocker.patch('time.sleep')  # Speed up retries
  mock_genai_client_class = mocker.patch('wptgen.llm.genai.Client')
  mock_instance = mock_genai_client_class.return_value

  # Simulate a timeout from the underlying httpx call
  mock_instance.models.generate_content.side_effect = httpx.TimeoutException('Connection timed out')

  assert base_config.api_key is not None
  client = GeminiClient(api_key=base_config.api_key, model=base_config.default_model, max_retries=1)

  with pytest.raises(LLMTimeoutError, match='Gemini API request timed out after 600s'):
    client.generate_content('test prompt')


def test_openai_timeout_handling(mocker: MockerFixture, base_config: Config) -> None:
  """Verify that OpenAIClient catches openai.APITimeoutError and raises LLMTimeoutError."""
  mocker.patch('time.sleep')  # Speed up retries
  mock_openai_class = mocker.patch('wptgen.llm.OpenAI')
  mock_instance = mock_openai_class.return_value

  # Simulate an OpenAI timeout
  # APITimeoutError requires a request object, but we can just mock the exception
  mock_instance.chat.completions.create.side_effect = openai.APITimeoutError(
    request=httpx.Request('POST', 'https://api.openai.com')
  )

  assert base_config.api_key is not None
  client = OpenAIClient(api_key=base_config.api_key, model=base_config.default_model, max_retries=1)

  with pytest.raises(LLMTimeoutError, match='OpenAI API request timed out after 600s'):
    client.generate_content('test prompt')


def test_get_llm_client_passes_timeout(mocker: MockerFixture, base_config: Config) -> None:
  """Verify that get_llm_client passes the timeout from config to the client."""
  mocker.patch('wptgen.llm.genai.Client')
  base_config.timeout = 999
  base_config.provider = 'gemini'

  client = get_llm_client(base_config)
  assert client.timeout == 999

  mocker.patch('wptgen.llm.OpenAI')
  base_config.provider = 'openai'
  client = get_llm_client(base_config)
  assert client.timeout == 999
