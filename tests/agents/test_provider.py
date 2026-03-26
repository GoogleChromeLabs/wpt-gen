"""Module docstring."""

# pylint: disable=redefined-outer-name
# pylint: disable=unused-argument
# pylint: disable=import-outside-toplevel
# pylint: disable=reimported
# pylint: disable=protected-access
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

import pytest
from pytest_mock import MockerFixture

from wptgen.agents.provider import setup_adk_environment
from wptgen.config import Config


@pytest.fixture(autouse=True)
def _mock_env(mocker: MockerFixture) -> None:
    mocker.patch.dict(os.environ, {}, clear=True)


def _create_config(provider: str, api_key: str, default_model: str) -> Config:
    return Config(
        provider=provider,
        api_key=api_key,
        default_model=default_model,
        wpt_path="/dummy/path",
        categories={},
        phase_model_mapping={},
    )


@pytest.mark.parametrize(
    ("provider", "expected_env_var", "expected_model"),
    [
        ("gemini", "GOOGLE_API_KEY", "gemini-3.1-pro-preview"),
        ("google", "GOOGLE_API_KEY", "gemini-3.1-pro-preview"),
        ("anthropic", "ANTHROPIC_API_KEY", "claude-opus-4-6"),
        ("openai", "OPENAI_API_KEY", "gpt-5.2-high"),
    ],
)
def test_setup_adk_environment_providers(
    provider: str, expected_env_var: str, expected_model: str
) -> None:
    config = _create_config(provider, f"test-key-{provider}", "")
    model = setup_adk_environment(config)

    assert os.environ.get(expected_env_var) == f"test-key-{provider}"
    assert model == expected_model


def test_setup_adk_environment_custom_model() -> None:
    config = _create_config("gemini", "test-key", "custom-model-123")
    model = setup_adk_environment(config)

    assert model == "custom-model-123"


def test_setup_adk_environment_missing_api_key() -> None:
    config = _create_config("gemini", "", "")
    with pytest.raises(
        ValueError, match="An API key is required for the gemini provider."
    ):
        setup_adk_environment(config)


def test_setup_adk_environment_unsupported_provider() -> None:
    config = _create_config("unknown", "test-key", "")
    with pytest.raises(ValueError, match="Unsupported ADK provider: unknown"):
        setup_adk_environment(config)
