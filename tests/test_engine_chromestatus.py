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

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_mock import MockerFixture

from wptgen.config import Config
from wptgen.engine import WPTGenEngine
from wptgen.models import WorkflowContext


@pytest.fixture
def mock_config(tmp_path: Path) -> Config:
  """Provides a basic Config object for testing."""
  return Config(
    provider='llmbargainbin',
    default_model='discountmodel',
    api_key='fake-key',
    categories={
      'lightweight': 'fastmodel',
      'reasoning': 'smartmodel',
    },
    phase_model_mapping={
      'requirements_extraction': 'reasoning',
      'coverage_audit': 'reasoning',
      'generation': 'lightweight',
      'evaluation': 'lightweight',
    },
    yes_tokens=False,
    wpt_path=str(tmp_path / 'wpt'),
    cache_path=str(tmp_path / '.wpt-gen-cache'),
    output_dir=str(tmp_path / 'output'),
  )


@pytest.fixture
def mock_llm() -> MagicMock:
  """Provides a mocked LLM client."""
  llm = MagicMock()
  llm.generate_content = AsyncMock(return_value='Mocked LLM Response')
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
async def test_run_async_chromestatus_workflow_full_path(
  engine: WPTGenEngine, mocker: MockerFixture
) -> None:
  """Verifies the ChromeStatus asynchronous workflow orchestration."""
  context = WorkflowContext(feature_id='chromestatus_123')
  requirements = 'reqs'
  audit = 'audit'
  generated_tests = [('path', 'content', 'suggestion')]

  mock_assembly = mocker.patch(
    'wptgen.engine.run_chromestatus_context_assembly', return_value=context
  )
  mock_extraction = mocker.patch(
    'wptgen.engine.run_chromestatus_requirements_extraction_categorized', return_value=requirements
  )
  mock_audit = mocker.patch('wptgen.engine.run_coverage_audit', return_value=audit)
  mock_gen = mocker.patch('wptgen.engine.run_test_generation', return_value=generated_tests)
  mock_eval = mocker.patch('wptgen.engine.run_test_evaluation', return_value=None)
  mock_exec = mocker.patch('wptgen.engine.run_test_execution', return_value=True)

  await engine._run_async_chromestatus_workflow('123')

  mock_assembly.assert_called_once_with('123', engine.config, engine.ui)
  mock_extraction.assert_called_once()
  mock_audit.assert_called_once()
  mock_gen.assert_called_once()
  mock_eval.assert_called_once()
  mock_exec.assert_called_once()


@pytest.mark.asyncio
async def test_run_async_chromestatus_workflow_detailed_requirements(
  engine: WPTGenEngine, mocker: MockerFixture
) -> None:
  """Verifies that run_chromestatus_requirements_extraction_iterative is called."""
  engine.config.detailed_requirements = True
  context = WorkflowContext(feature_id='chromestatus_123')
  requirements = 'reqs'

  mocker.patch('wptgen.engine.run_chromestatus_context_assembly', return_value=context)
  mock_extraction = mocker.patch(
    'wptgen.engine.run_chromestatus_requirements_extraction_categorized', return_value=requirements
  )
  mock_extraction_iterative = mocker.patch(
    'wptgen.engine.run_chromestatus_requirements_extraction_iterative', return_value=requirements
  )
  mocker.patch('wptgen.engine.run_coverage_audit', return_value='audit')
  mocker.patch('wptgen.engine.run_test_generation', return_value=[])

  await engine._run_async_chromestatus_workflow('123')

  mock_extraction.assert_not_called()
  mock_extraction_iterative.assert_called_once()
