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
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from wptgen.config import Config
from wptgen.engine import WPTGenEngine
from wptgen.models import WorkflowContext


@pytest.fixture
def mock_config(tmp_path: Path) -> Config:
  """Provides a basic Config object for testing."""
  return Config(
    provider='llmbargainbin',
    model='discountmodel',
    api_key='fake-key',
    wpt_path=os.path.abspath(os.sep + 'fake' + os.sep + 'wpt'),
    yes_tokens=False,
    cache_path=str(tmp_path / '.wpt-gen-cache'),
  )


@pytest.fixture
def mock_llm() -> MagicMock:
  """Provides a mocked LLM client."""
  llm = MagicMock()
  llm.generate_content.return_value = 'Mocked LLM Response'
  llm.count_tokens.return_value = 100
  llm.prompt_exceeds_input_token_limit.return_value = False
  return llm


@pytest.fixture
def mock_ui() -> MagicMock:
  """Provides a mocked UI provider."""
  return MagicMock()


@pytest.fixture
def engine(mock_config: Config, mock_llm: MagicMock, mock_ui: MagicMock) -> WPTGenEngine:
  """Provides a WPTGenEngine instance with a mocked LLM client."""
  with patch('wptgen.engine.get_llm_client', return_value=mock_llm):
    return WPTGenEngine(mock_config, mock_ui)


@pytest.mark.asyncio
async def test_run_async_workflow_full_path(engine: WPTGenEngine, mocker: MagicMock) -> None:
  """Full asynchronous workflow orchestration, ensuring each phase is called."""
  context = WorkflowContext(feature_id='feat-id')
  requirements = 'reqs'
  audit = 'audit'

  mock_assembly = mocker.patch('wptgen.engine.run_context_assembly', return_value=context)
  mock_extraction = mocker.patch(
    'wptgen.engine.run_requirements_extraction', return_value=requirements
  )
  mock_audit = mocker.patch('wptgen.engine.run_coverage_audit', return_value=audit)
  mock_gen = mocker.patch('wptgen.engine.run_test_generation', return_value=None)

  await engine._run_async_workflow('feat-id')

  mock_assembly.assert_called_once()
  mock_extraction.assert_called_once()
  mock_audit.assert_called_once()
  mock_gen.assert_called_once()


@pytest.mark.asyncio
async def test_run_async_workflow_suggestions_only(engine: WPTGenEngine, mocker: MagicMock) -> None:
  """Verifies that the workflow short-circuits to provide_coverage_report when config.suggestions_only is True."""
  engine.config.suggestions_only = True
  context = WorkflowContext(feature_id='test-feat')

  mocker.patch('wptgen.engine.run_context_assembly', return_value=context)
  mocker.patch('wptgen.engine.run_requirements_extraction', return_value='reqs')
  mocker.patch('wptgen.engine.run_coverage_audit', return_value='audit')
  mock_provide = mocker.patch('wptgen.engine.provide_coverage_report', return_value=None)
  mock_gen = mocker.patch('wptgen.engine.run_test_generation')

  await engine._run_async_workflow('test-feat')

  mock_provide.assert_called_once()
  mock_gen.assert_not_called()


def test_engine_init(engine: WPTGenEngine, mock_config: Config) -> None:
  """Verifies that the engine initializes correctly with the given configuration."""
  assert engine.config == mock_config
  assert engine.llm is not None
  assert engine.jinja_env is not None
