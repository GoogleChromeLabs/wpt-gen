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
from unittest.mock import MagicMock, patch

import pytest

from wptgen.config import Config
from wptgen.models import WebFeatureMetadata, WorkflowContext, WPTContext
from wptgen.phases.context_assembly import run_context_assembly
from wptgen.phases.coverage_audit import run_coverage_audit
from wptgen.phases.generation import run_test_generation
from wptgen.phases.requirements_extraction import run_requirements_extraction


@pytest.fixture
def mock_ui() -> MagicMock:
  ui = MagicMock()
  ui.status.return_value.__enter__.return_value = None
  return ui


@pytest.fixture
def mock_config() -> Config:
  return Config(
    provider='test',
    default_model='test-model',
    api_key='test-key',
    wpt_path='/fake/wpt',
    categories={
      'lightweight': 'fast-model',
      'reasoning': 'smart-model',
    },
    phase_model_mapping={
      'requirements_extraction': 'reasoning',
      'coverage_audit': 'reasoning',
      'generation': 'lightweight',
    },
    cache_path='/tmp/cache',
  )


@pytest.fixture
def mock_llm() -> MagicMock:
  llm = MagicMock()
  llm.count_tokens.return_value = 10
  llm.prompt_exceeds_input_token_limit.return_value = False
  llm.generate_content.return_value = 'Mock Response'
  llm.model = 'mock-model'
  return llm


@pytest.mark.asyncio
async def test_run_context_assembly_success(mock_config: Config, mock_ui: MagicMock) -> None:
  with (
    patch('wptgen.phases.context_assembly.fetch_feature_yaml', return_value={'name': 'feat'}),
    patch(
      'wptgen.phases.context_assembly.extract_feature_metadata',
      return_value=WebFeatureMetadata('Feat', 'Desc', ['http://spec']),
    ),
    patch('wptgen.phases.context_assembly.fetch_and_extract_text', return_value='Spec Content'),
    patch('wptgen.phases.context_assembly.find_feature_tests', return_value=[]),
    patch('wptgen.phases.context_assembly.gather_local_test_context', return_value=WPTContext()),
  ):
    context = await run_context_assembly('feat-id', mock_config, mock_ui)

    assert context is not None
    assert context.feature_id == 'feat-id'
    assert context.metadata is not None
    assert context.metadata.name == 'Feat'
    assert context.spec_contents == 'Spec Content'


@pytest.mark.asyncio
async def test_run_requirements_extraction_cached(
  mock_config: Config, mock_ui: MagicMock, mock_llm: MagicMock, tmp_path: Path
) -> None:
  context = WorkflowContext(
    feature_id='feat',
    metadata=WebFeatureMetadata('Feat', 'Desc', ['http://spec']),
    spec_contents='Spec',
  )
  cache_dir = tmp_path
  cache_file = cache_dir / 'feat__requirements.xml'
  cache_file.write_text('<reqs>cached</reqs>')

  mock_ui.confirm.return_value = True

  res = await run_requirements_extraction(
    context, mock_config, mock_llm, mock_ui, MagicMock(), cache_dir
  )

  assert res == '<reqs>cached</reqs>'
  assert context.requirements_xml == '<reqs>cached</reqs>'


@pytest.mark.asyncio
async def test_run_coverage_audit_success(
  mock_config: Config, mock_ui: MagicMock, mock_llm: MagicMock
) -> None:
  context = WorkflowContext(
    feature_id='feat', requirements_xml='<reqs></reqs>', wpt_context=WPTContext()
  )
  jinja_env = MagicMock()
  jinja_env.get_template.return_value.render.return_value = 'Prompt'

  mock_ui.confirm.return_value = True
  mock_llm.generate_content.return_value = 'Audit Response'

  res = await run_coverage_audit(context, mock_config, mock_llm, mock_ui, jinja_env)

  assert res == 'Audit Response'
  assert context.audit_response == 'Audit Response'


@pytest.mark.asyncio
async def test_run_test_generation_satisfied(
  mock_config: Config, mock_ui: MagicMock, mock_llm: MagicMock
) -> None:
  context = WorkflowContext(
    feature_id='feat',
    audit_response='<status>SATISFIED</status>',
    metadata=WebFeatureMetadata('Feat', 'Desc', ['http://spec']),
  )
  jinja_env = MagicMock()

  await run_test_generation(context, mock_config, mock_llm, mock_ui, jinja_env)

  mock_ui.display_panel.assert_called_once()
  assert 'satisfied' in mock_ui.display_panel.call_args[0][0].lower()


@pytest.mark.asyncio
async def test_run_test_generation_success(
  mock_config: Config, mock_ui: MagicMock, mock_llm: MagicMock, tmp_path: Path
) -> None:
  context = WorkflowContext(
    feature_id='feat',
    metadata=WebFeatureMetadata('Feat', 'Desc', ['http://spec']),
    audit_response='<test_suggestion><title>T1</title><description>D1</description></test_suggestion>',
  )
  jinja_env = MagicMock()
  jinja_env.get_template.return_value.render.return_value = 'Generated Content'

  mock_ui.confirm.return_value = True
  mock_llm.generate_content.return_value = '<html></html>'
  mock_config.output_dir = str(tmp_path)

  with patch('wptgen.phases.generation.confirm_prompts', return_value=None):
    await run_test_generation(context, mock_config, mock_llm, mock_ui, jinja_env)

  expected_file = tmp_path / 't1__GENERATED_01_.html'
  assert expected_file.exists()
  assert expected_file.read_text() == '<html></html>'
