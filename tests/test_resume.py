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

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pytest_mock import MockerFixture

from wptgen.config import Config
from wptgen.engine import WPTGenEngine
from wptgen.models import WebFeatureMetadata, WorkflowContext, WPTContext


@pytest.fixture
def mock_config(tmp_path: Path) -> Config:
  """Provides a basic Config object for testing."""
  return Config(
    provider='gemini',
    default_model='gemini-3.1-pro-preview',
    api_key='fake-key',
    categories={
      'lightweight': 'gemini-3-flash-preview',
      'reasoning': 'gemini-3.1-pro-preview',
    },
    phase_model_mapping={
      'requirements_extraction': 'reasoning',
      'coverage_audit': 'reasoning',
      'generation': 'lightweight',
      'evaluation': 'lightweight',
    },
    wpt_path=str(tmp_path / 'wpt'),
    cache_path=str(tmp_path / '.wpt-gen-cache'),
    output_dir=str(tmp_path / 'output'),
    resume=True,
  )


@pytest.fixture
def engine(mock_config: Config) -> WPTGenEngine:
  """Provides a WPTGenEngine instance with a mocked LLM client."""
  with patch('wptgen.engine.get_llm_client', return_value=MagicMock()):
    return WPTGenEngine(mock_config, MagicMock())


def test_workflow_context_serialization() -> None:
  """Verifies that WorkflowContext serializes and deserializes correctly."""
  metadata = WebFeatureMetadata(name='Test', description='Desc', specs=['http://spec.com'])
  wpt_context = WPTContext(
    test_contents={'test.html': 'content'},
    dependency_contents={'dep.js': 'js'},
    test_to_deps={'test.html': {'dep.js'}},
  )
  context = WorkflowContext(
    feature_id='test-feat',
    metadata=metadata,
    spec_contents='Spec contents',
    wpt_context=wpt_context,
    requirements_xml='<reqs/>',
    audit_response='<audit/>',
    suggestions=['suggestion 1'],
    approved_suggestions_xml=['<suggestion/>'],
    mdn_contents=['mdn'],
    generated_tests=[(Path('/tmp/test.html'), 'content', '<suggestion/>')],
  )

  serialized = context.to_dict()
  # Verify types are JSON-safe
  json_str = json.dumps(serialized)
  deserialized_data = json.loads(json_str)

  new_context = WorkflowContext.from_dict(deserialized_data)

  assert new_context.feature_id == context.feature_id
  assert new_context.metadata == context.metadata
  assert new_context.spec_contents == context.spec_contents
  assert new_context.wpt_context is not None
  assert context.wpt_context is not None
  assert new_context.wpt_context.test_contents == context.wpt_context.test_contents
  assert new_context.wpt_context.test_to_deps == context.wpt_context.test_to_deps
  assert new_context.requirements_xml == context.requirements_xml
  assert new_context.audit_response == context.audit_response
  assert new_context.generated_tests == context.generated_tests


def test_engine_save_load_resume_state(engine: WPTGenEngine) -> None:
  """Verifies that the engine correctly saves and loads the state file."""
  context = WorkflowContext(feature_id='test-feat', requirements_xml='<reqs/>')

  engine._save_resume_state(context)

  resume_file = engine._get_resume_file_path('test-feat')
  assert resume_file.exists()

  loaded_context = engine._load_resume_state('test-feat')
  assert loaded_context is not None
  assert loaded_context.feature_id == 'test-feat'
  assert loaded_context.requirements_xml == '<reqs/>'


@pytest.mark.asyncio
async def test_run_async_workflow_resume_skips_phases(
  engine: WPTGenEngine, mocker: MockerFixture
) -> None:
  """Verifies that completed phases are correctly skipped when resuming."""
  # Setup context with some phases completed
  context = WorkflowContext(
    feature_id='test-feat',
    metadata=WebFeatureMetadata(name='Test', description='Desc', specs=[]),
    wpt_context=WPTContext(),
    requirements_xml='<reqs/>',
  )
  engine._save_resume_state(context)

  mock_assembly = mocker.patch('wptgen.engine.run_context_assembly')
  mock_extraction = mocker.patch('wptgen.engine.run_requirements_extraction')
  mock_audit = mocker.patch('wptgen.engine.run_coverage_audit', return_value='audit')
  mock_gen = mocker.patch('wptgen.engine.run_test_generation', return_value=[])

  await engine._run_async_workflow('test-feat')

  # Phase 1 and 2 should be skipped
  mock_assembly.assert_not_called()
  mock_extraction.assert_not_called()
  # Phase 3 and onwards should be called
  mock_audit.assert_called_once()
  mock_gen.assert_called_once()


@pytest.mark.asyncio
async def test_run_async_workflow_cleans_up_resume_file(
  engine: WPTGenEngine, mocker: MockerFixture
) -> None:
  """Verifies that the resume file is deleted upon successful completion."""
  context = WorkflowContext(feature_id='test-feat')
  engine._save_resume_state(context)
  resume_file = engine._get_resume_file_path('test-feat')
  assert resume_file.exists()

  mocker.patch('wptgen.engine.run_context_assembly', return_value=context)
  mocker.patch('wptgen.engine.run_requirements_extraction', return_value='<reqs/>')
  mocker.patch('wptgen.engine.run_coverage_audit', return_value='audit')
  mocker.patch('wptgen.engine.run_test_generation', return_value=[])

  await engine._run_async_workflow('test-feat')

  assert not resume_file.exists()


@pytest.mark.asyncio
async def test_run_async_workflow_saves_after_each_phase(
  engine: WPTGenEngine, mocker: MockerFixture
) -> None:
  """Verifies that the state is saved after each phase."""
  context = WorkflowContext(feature_id='test-feat')

  mocker.patch('wptgen.engine.run_context_assembly', return_value=context)
  mocker.patch('wptgen.engine.run_requirements_extraction', return_value='<reqs/>')
  mocker.patch('wptgen.engine.run_coverage_audit', return_value='audit')
  mocker.patch('wptgen.engine.run_test_generation', return_value=[])

  spy_save = mocker.spy(engine, '_save_resume_state')

  await engine._run_async_workflow('test-feat')

  # Saved after: assembly, extraction, audit, generation
  assert spy_save.call_count == 4
