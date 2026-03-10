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
from wptgen.engine import WorkflowError, WPTGenEngine
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
  """Provides a mocked LLM client using AsyncMock for async methods."""
  # We use MagicMock for the container, but AsyncMock for the specific async method
  llm = MagicMock()

  # generate_content is presumably awaited in the underlying phases
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
async def test_run_async_workflow_full_path(engine: WPTGenEngine, mocker: MockerFixture) -> None:
  """Full asynchronous workflow orchestration, ensuring each phase is called."""
  context = WorkflowContext(feature_id='feat-id')
  requirements = 'reqs'
  audit = 'audit'
  generated_tests = [('path', 'content', 'suggestion')]

  mock_assembly = mocker.patch('wptgen.engine.run_context_assembly', return_value=context)
  mock_extraction = mocker.patch(
    'wptgen.engine.run_requirements_extraction_categorized', return_value=requirements
  )
  mock_extraction_iterative = mocker.patch(
    'wptgen.engine.run_requirements_extraction_iterative', return_value=requirements
  )
  mock_audit = mocker.patch('wptgen.engine.run_coverage_audit', return_value=audit)
  mock_gen = mocker.patch('wptgen.engine.run_test_generation', return_value=generated_tests)
  mock_eval = mocker.patch('wptgen.engine.run_test_evaluation', return_value=None)

  await engine._run_async_workflow('feat-id')

  mock_assembly.assert_called_once()
  mock_extraction.assert_called_once()
  mock_extraction_iterative.assert_not_called()
  mock_audit.assert_called_once()
  mock_gen.assert_called_once()
  mock_eval.assert_called_once()


@pytest.mark.asyncio
async def test_run_async_workflow_phase_failures(
  engine: WPTGenEngine, mocker: MockerFixture
) -> None:
  """Test short-circuits when phases fail."""
  # Phase 1 failure
  mocker.patch('wptgen.engine.run_context_assembly', return_value=None)
  with pytest.raises(WorkflowError, match='Phase 1: Context Assembly failed.'):
    await engine._run_async_workflow('feat-id')

  # Phase 2 failure
  mocker.patch('wptgen.engine.run_context_assembly', return_value=WorkflowContext(feature_id='f'))
  mocker.patch('wptgen.engine.run_requirements_extraction_categorized', return_value=None)
  with pytest.raises(WorkflowError, match='Phase 2: Requirements Extraction failed.'):
    await engine._run_async_workflow('feat-id')

  # Phase 3 failure
  mocker.patch('wptgen.engine.run_requirements_extraction_categorized', return_value='reqs')
  mocker.patch('wptgen.engine.run_coverage_audit', return_value=None)
  with pytest.raises(WorkflowError, match='Phase 3: Coverage Audit failed.'):
    await engine._run_async_workflow('feat-id')


def test_run_workflow_sync(engine: WPTGenEngine, mocker: MockerFixture) -> None:
  """Tests the synchronous wrapper."""
  mock_async_workflow = mocker.patch.object(engine, '_run_async_workflow')
  engine.run_workflow('feat-id')
  mock_async_workflow.assert_called_once_with('feat-id')


@pytest.mark.asyncio
async def test_run_async_workflow_suggestions_only(
  engine: WPTGenEngine, mocker: MockerFixture
) -> None:
  """Verifies that the workflow short-circuits to provide_coverage_report when config.suggestions_only is True."""
  engine.config.suggestions_only = True
  context = WorkflowContext(feature_id='test-feat', audit_response='audit')

  mocker.patch('wptgen.engine.run_context_assembly', return_value=context)
  mocker.patch('wptgen.engine.run_requirements_extraction_categorized', return_value='reqs')
  mocker.patch('wptgen.engine.run_coverage_audit', return_value='audit')
  mock_provide = mocker.patch('wptgen.engine.provide_coverage_report', return_value=None)
  mock_gen = mocker.patch('wptgen.engine.run_test_generation', return_value=[])

  await engine._run_async_workflow(web_feature_id='test-feat')

  mock_provide.assert_called_once()
  mock_gen.assert_not_called()


@pytest.mark.asyncio
async def test_run_async_workflow_detailed_requirements(
  engine: WPTGenEngine, mocker: MockerFixture
) -> None:
  """Verifies that run_requirements_extraction_iterative is called when config.detailed_requirements is True."""
  engine.config.detailed_requirements = True
  context = WorkflowContext(feature_id='feat-id')
  requirements = 'reqs'

  mocker.patch('wptgen.engine.run_context_assembly', return_value=context)
  mock_extraction = mocker.patch(
    'wptgen.engine.run_requirements_extraction_categorized', return_value=requirements
  )
  mock_extraction_iterative = mocker.patch(
    'wptgen.engine.run_requirements_extraction_iterative', return_value=requirements
  )
  mocker.patch('wptgen.engine.run_coverage_audit', return_value='audit')
  mocker.patch('wptgen.engine.run_test_generation', return_value=[])

  await engine._run_async_workflow('feat-id')

  mock_extraction.assert_not_called()
  mock_extraction_iterative.assert_called_once()


def test_engine_init(engine: WPTGenEngine, mock_config: Config) -> None:
  """Verifies that the engine initializes correctly with the given configuration."""
  assert engine.config == mock_config
  assert engine.llm is not None
  assert engine.jinja_env is not None


@pytest.mark.asyncio
async def test_run_async_workflow_skip_evaluation(
  engine: WPTGenEngine, mock_ui: MagicMock, mocker: MockerFixture
) -> None:
  """Verifies that Phase 5: Evaluation is skipped when config.skip_evaluation is True."""
  engine.config.skip_evaluation = True
  context = WorkflowContext(feature_id='feat-id')
  requirements = 'reqs'
  audit = 'audit'
  generated_tests = [('path', 'content', 'suggestion')]

  mocker.patch('wptgen.engine.run_context_assembly', return_value=context)
  mocker.patch('wptgen.engine.run_requirements_extraction_categorized', return_value=requirements)
  mocker.patch('wptgen.engine.run_coverage_audit', return_value=audit)
  mocker.patch('wptgen.engine.run_test_generation', return_value=generated_tests)
  mock_eval = mocker.patch('wptgen.engine.run_test_evaluation', return_value=None)

  await engine._run_async_workflow('feat-id')

  mock_eval.assert_not_called()
  mock_ui.info.assert_called_with('Skipping Phase 5: Evaluation.')
