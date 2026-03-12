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
  mock_exec = mocker.patch('wptgen.engine.run_test_execution', return_value=True)

  await engine._run_async_workflow('feat-id')

  mock_assembly.assert_called_once()
  mock_extraction.assert_called_once()
  mock_extraction_iterative.assert_not_called()
  mock_audit.assert_called_once()
  mock_gen.assert_called_once()
  mock_eval.assert_called_once()
  mock_exec.assert_called_once()


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
  mocker.patch('wptgen.engine.run_test_execution', return_value=True)

  await engine._run_async_workflow('feat-id')

  mock_eval.assert_not_called()
  mock_ui.info.assert_called_with('Skipping Phase 5: Evaluation.')


@pytest.mark.asyncio
async def test_run_async_workflow_skip_execution(
  engine: WPTGenEngine, mock_ui: MagicMock, mocker: MockerFixture
) -> None:
  """Verifies that Phase 6: Test Execution is skipped when config.skip_execution is True."""
  engine.config.skip_execution = True
  context = WorkflowContext(feature_id='feat-id')
  requirements = 'reqs'
  audit = 'audit'
  generated_tests = [('path', 'content', 'suggestion')]

  mocker.patch('wptgen.engine.run_context_assembly', return_value=context)
  mocker.patch('wptgen.engine.run_requirements_extraction_categorized', return_value=requirements)
  mocker.patch('wptgen.engine.run_coverage_audit', return_value=audit)
  mocker.patch('wptgen.engine.run_test_generation', return_value=generated_tests)
  mocker.patch('wptgen.engine.run_test_evaluation', return_value=None)
  mock_exec = mocker.patch('wptgen.engine.run_test_execution', return_value=None)

  await engine._run_async_workflow('feat-id')

  mock_exec.assert_not_called()
  mock_ui.info.assert_called_with('Skipping Phase 6: Test Execution.')


def test_engine_load_resume_state_invalid_json(
  mocker: MockerFixture, tmp_path: Path, mock_config: Config
) -> None:
  ui_mock = MagicMock()
  mocker.patch('wptgen.engine.get_llm_client')
  engine = WPTGenEngine(mock_config, ui_mock)
  resume_file = tmp_path / 'mock_feature_resume.json'
  resume_file.write_text('invalid json')
  mocker.patch('wptgen.engine.WPTGenEngine._get_resume_file_path', return_value=resume_file)
  result = engine._load_resume_state('mock_feature')
  assert result is None


@pytest.mark.asyncio
async def test_engine_single_prompt_requirements(
  mocker: MockerFixture, mock_config: Config
) -> None:
  mock_config.single_prompt_requirements = True
  ui_mock = MagicMock()
  mocker.patch('wptgen.engine.get_llm_client')
  engine = WPTGenEngine(mock_config, ui_mock)

  mock_context = WorkflowContext(feature_id='mock_feature')

  mocker.patch(
    'wptgen.engine.run_context_assembly', new_callable=AsyncMock, return_value=mock_context
  )
  mocker.patch(
    'wptgen.engine.run_requirements_extraction', new_callable=AsyncMock, return_value='<xml></xml>'
  )
  mocker.patch(
    'wptgen.engine.run_coverage_audit', new_callable=AsyncMock, return_value='mock_audit_response'
  )
  mocker.patch(
    'wptgen.engine.run_test_generation', new_callable=AsyncMock, return_value=['mock_test']
  )
  mocker.patch('wptgen.engine.run_test_evaluation', new_callable=AsyncMock, return_value=None)
  mocker.patch('wptgen.engine.run_test_execution', new_callable=AsyncMock, return_value=True)
  mocker.patch('wptgen.engine.WPTGenEngine._save_resume_state')

  await engine._run_async_workflow('mock_feature')

  from typing import cast

  import wptgen.engine

  cast(AsyncMock, wptgen.engine.run_requirements_extraction).assert_called_once()


@pytest.mark.asyncio
async def test_engine_skip_phase_4(mocker: MockerFixture, mock_config: Config) -> None:
  ui_mock = MagicMock()
  mocker.patch('wptgen.engine.get_llm_client')
  engine = WPTGenEngine(mock_config, ui_mock)

  mock_context = WorkflowContext(
    feature_id='mock_feature',
    requirements_xml='<xml></xml>',
    audit_response='mock_audit',
    generated_tests=[(Path('mock_test_1.html'), 'content', '<xml>')],
  )

  mocker.patch(
    'wptgen.engine.run_context_assembly', new_callable=AsyncMock, return_value=mock_context
  )
  mocker.patch(
    'wptgen.engine.run_coverage_audit', new_callable=AsyncMock, return_value='mock_audit'
  )
  mocker.patch('wptgen.engine.run_test_generation', new_callable=AsyncMock, return_value=[])
  mocker.patch('wptgen.engine.run_test_evaluation', new_callable=AsyncMock, return_value=None)
  mocker.patch('wptgen.engine.run_test_execution', new_callable=AsyncMock, return_value=True)
  mocker.patch('wptgen.engine.WPTGenEngine._save_resume_state')

  await engine._run_async_workflow('mock_feature')

  ui_mock.success.assert_any_call('Skipping Phase 4: Tests already generated.')


def test_engine_load_resume_state_missing(
  mocker: MockerFixture, tmp_path: Path, mock_config: Config
) -> None:
  ui_mock = MagicMock()
  mocker.patch('wptgen.engine.get_llm_client')
  engine = WPTGenEngine(mock_config, ui_mock)
  resume_file = tmp_path / 'non_existent.json'
  mocker.patch('wptgen.engine.WPTGenEngine._get_resume_file_path', return_value=resume_file)
  result = engine._load_resume_state('mock_feature')
  assert result is None


@pytest.mark.asyncio
async def test_engine_resume_workflow_success(mocker: MockerFixture, mock_config: Config) -> None:
  mock_config.resume = True
  ui_mock = MagicMock()
  mocker.patch('wptgen.engine.get_llm_client')
  engine = WPTGenEngine(mock_config, ui_mock)

  mock_context = WorkflowContext(
    feature_id='mock_feature',
    requirements_xml='<xml>',
    audit_response='audit',
    generated_tests=[(Path('test.html'), 'content', '<xml>')],
  )
  mocker.patch('wptgen.engine.WPTGenEngine._load_resume_state', return_value=mock_context)

  mocker.patch(
    'wptgen.engine.run_context_assembly', new_callable=AsyncMock, return_value=mock_context
  )
  mocker.patch(
    'wptgen.engine.run_requirements_extraction_categorized',
    new_callable=AsyncMock,
    return_value='<xml></xml>',
  )
  mocker.patch(
    'wptgen.engine.run_coverage_audit', new_callable=AsyncMock, return_value='mock_audit'
  )
  mocker.patch(
    'wptgen.engine.run_test_generation', new_callable=AsyncMock, return_value=['mock_test']
  )
  mocker.patch('wptgen.engine.run_test_evaluation', new_callable=AsyncMock, return_value=None)
  mocker.patch('wptgen.engine.run_test_execution', new_callable=AsyncMock, return_value=True)
  mocker.patch('wptgen.engine.WPTGenEngine._save_resume_state')

  await engine._run_async_workflow('mock_feature')

  ui_mock.success.assert_any_call('Resuming workflow for mock_feature')


def test_engine_load_resume_state_success(
  mocker: MockerFixture, tmp_path: Path, mock_config: Config
) -> None:
  ui_mock = MagicMock()
  mocker.patch('wptgen.engine.get_llm_client')
  engine = WPTGenEngine(mock_config, ui_mock)
  resume_file = tmp_path / 'mock_feature_resume.json'
  resume_file.write_text(
    '{"feature_id": "mock_feature", "metadata": null, "spec_contents": null, "wpt_context": null, "requirements_xml": null, "audit_response": null, "suggestions": [], "approved_suggestions_xml": [], "mdn_contents": null, "generated_tests": null}'
  )
  mocker.patch('wptgen.engine.WPTGenEngine._get_resume_file_path', return_value=resume_file)
  result = engine._load_resume_state('mock_feature')
  assert result is not None
  assert result.feature_id == 'mock_feature'
