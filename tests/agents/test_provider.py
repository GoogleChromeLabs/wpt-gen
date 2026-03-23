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

import os
from collections.abc import Generator
from unittest.mock import patch

import pytest

from wptgen.agents.provider import setup_adk_environment
from wptgen.config import Config


@pytest.fixture
def mock_env() -> Generator[None, None, None]:
  with patch.dict(os.environ, {}, clear=True):
    yield


def _create_config(provider: str, api_key: str, default_model: str) -> Config:
  return Config(
    provider=provider,
    api_key=api_key,
    default_model=default_model,
    wpt_path='/dummy/path',
    categories={},
    phase_model_mapping={},
  )


def test_setup_adk_environment_gemini(mock_env: None) -> None:
  config = _create_config('gemini', 'test-key-gemini', '')
  model = setup_adk_environment(config)

  assert os.environ.get('GOOGLE_API_KEY') == 'test-key-gemini'
  assert model == 'gemini-3.1-pro-preview'


def test_setup_adk_environment_google(mock_env: None) -> None:
  config = _create_config('google', 'test-key-google', '')
  model = setup_adk_environment(config)

  assert os.environ.get('GOOGLE_API_KEY') == 'test-key-google'
  assert model == 'gemini-3.1-pro-preview'


def test_setup_adk_environment_anthropic(mock_env: None) -> None:
  config = _create_config('anthropic', 'test-key-anthropic', '')
  model = setup_adk_environment(config)

  assert os.environ.get('ANTHROPIC_API_KEY') == 'test-key-anthropic'
  assert model == 'claude-opus-4-6'


def test_setup_adk_environment_openai(mock_env: None) -> None:
  config = _create_config('openai', 'test-key-openai', '')
  model = setup_adk_environment(config)

  assert os.environ.get('OPENAI_API_KEY') == 'test-key-openai'
  assert model == 'gpt-5.2-high'


def test_setup_adk_environment_custom_model(mock_env: None) -> None:
  config = _create_config('gemini', 'test-key', 'custom-model-123')
  model = setup_adk_environment(config)

  assert model == 'custom-model-123'


def test_setup_adk_environment_missing_api_key(mock_env: None) -> None:
  config = _create_config('gemini', '', '')
  with pytest.raises(ValueError, match='An API key is required for the gemini provider.'):
    setup_adk_environment(config)


def test_setup_adk_environment_unsupported_provider(mock_env: None) -> None:
  config = _create_config('unknown', 'test-key', '')
  with pytest.raises(ValueError, match='Unsupported ADK provider: unknown'):
    setup_adk_environment(config)
