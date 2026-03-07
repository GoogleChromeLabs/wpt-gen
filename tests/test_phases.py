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
from wptgen.phases.generation import run_test_generation
from wptgen.phases.requirements_extraction import (
  run_requirements_extraction,
  run_requirements_extraction_categorized,
)


@pytest.fixture
def mock_ui() -> MagicMock:
  """Fixture that provides a mocked UI provider with a status context manager."""
  ui = MagicMock()
  ui.status.return_value.__enter__.return_value = None
  return ui


@pytest.fixture
def mock_config(tmp_path: Path) -> Config:
  """Fixture that provides a basic test configuration."""
  return Config(
    provider='test',
    default_model='test-model',
    api_key='test-key',
    categories={
      'lightweight': 'fast-model',
      'reasoning': 'smart-model',
    },
    phase_model_mapping={
      'requirements_extraction': 'reasoning',
      'coverage_audit': 'reasoning',
      'generation': 'lightweight',
      'evaluation': 'lightweight',
    },
    wpt_path=str(tmp_path / 'wpt'),
    cache_path=str(tmp_path / 'cache'),
    output_dir=str(tmp_path / 'output'),
  )


@pytest.fixture
def mock_llm() -> MagicMock:
  """Fixture that provides a mocked LLM client."""
  llm = MagicMock()
  llm.count_tokens.return_value = 10
  llm.prompt_exceeds_input_token_limit.return_value = False
  llm.generate_content.return_value = 'Mock Response'
  llm.model = 'mock-model'
  return llm


@pytest.mark.asyncio
async def test_run_context_assembly_success(mock_config: Config, mock_ui: MagicMock) -> None:
  """Test successful context assembly for a registered feature."""
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
    mock_ui.on_phase_start.assert_called_once_with(1, 'Context Assembly')
    mock_ui.report_metadata.assert_called_once()


@pytest.mark.asyncio
async def test_run_context_assembly_with_mdn(mock_config: Config, mock_ui: MagicMock) -> None:
  """Test context assembly with MDN documentation fetching."""
  with (
    patch('wptgen.phases.context_assembly.fetch_feature_yaml', return_value={'name': 'feat'}),
    patch(
      'wptgen.phases.context_assembly.extract_feature_metadata',
      return_value=WebFeatureMetadata('Feat', 'Desc', ['http://spec']),
    ),
    patch('wptgen.phases.context_assembly.fetch_and_extract_text') as mock_fetch,
    patch(
      'wptgen.phases.context_assembly.fetch_mdn_urls', return_value=['http://mdn1', 'http://mdn2']
    ),
    patch('wptgen.phases.context_assembly.find_feature_tests', return_value=[]),
    patch('wptgen.phases.context_assembly.gather_local_test_context', return_value=WPTContext()),
  ):
    mock_fetch.side_effect = ['Spec Content', 'MDN Content 1', 'MDN Content 2']

    context = await run_context_assembly('feat-id', mock_config, mock_ui)

    assert context is not None
    assert isinstance(context.mdn_contents, list)
    assert len(context.mdn_contents) == 2
    mock_ui.report_context_summary.assert_called_once()


@pytest.mark.asyncio
async def test_run_context_assembly_unregistered_with_params(
  mock_config: Config, mock_ui: MagicMock
) -> None:
  """Test context assembly for an unregistered feature with manual parameters."""
  mock_config.spec_urls = ['http://manual-spec']
  mock_config.feature_description = 'Manual Description'

  with (
    patch('wptgen.phases.context_assembly.fetch_feature_yaml', return_value=None),
    patch('wptgen.phases.context_assembly.fetch_and_extract_text', return_value='Spec Content'),
    patch('wptgen.phases.context_assembly.find_feature_tests', return_value=[]),
    patch('wptgen.phases.context_assembly.gather_local_test_context', return_value=WPTContext()),
  ):
    context = await run_context_assembly('unregistered', mock_config, mock_ui)

    assert context is not None
    assert context.metadata is not None
    assert context.metadata.name == 'unregistered'
    mock_ui.warning.assert_called_once()


@pytest.mark.asyncio
async def test_run_context_assembly_not_found(mock_config: Config, mock_ui: MagicMock) -> None:
  """Test context assembly when feature is not found and no manual params provided."""
  with patch('wptgen.phases.context_assembly.fetch_feature_yaml', return_value=None):
    context = await run_context_assembly('not-found', mock_config, mock_ui)
    assert context is None
    mock_ui.error.assert_called_once()


@pytest.mark.asyncio
async def test_run_context_assembly_no_specs(mock_config: Config, mock_ui: MagicMock) -> None:
  """Test context assembly failure when no spec URLs are found."""
  with (
    patch('wptgen.phases.context_assembly.fetch_feature_yaml', return_value={'name': 'feat'}),
    patch(
      'wptgen.phases.context_assembly.extract_feature_metadata',
      return_value=WebFeatureMetadata('Feat', 'Desc', []),
    ),
  ):
    context = await run_context_assembly('feat-id', mock_config, mock_ui)
    assert context is None
    mock_ui.error.assert_called_once()


@pytest.mark.asyncio
async def test_run_requirements_extraction_cached(
  mock_config: Config, mock_ui: MagicMock, mock_llm: MagicMock, tmp_path: Path
) -> None:
  """Test requirements extraction when a valid cache exists."""
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
  mock_ui.info.assert_called_once()
  mock_ui.success.assert_called_once_with('Using cached requirements.')


@pytest.mark.asyncio
async def test_run_requirements_extraction_categorized(
  mock_config: Config, mock_ui: MagicMock, mock_llm: MagicMock, tmp_path: Path
) -> None:
  """Test categorized requirements extraction with mocked LLM responses."""
  context = WorkflowContext(
    feature_id='feat',
    metadata=WebFeatureMetadata('Feat', 'Desc', ['http://spec']),
    spec_contents='Spec',
  )
  jinja_env = MagicMock()
  jinja_env.get_template.return_value.render.return_value = 'Mock Template'

  # Mock generate_safe to return a single requirement for each call
  with patch(
    'wptgen.phases.requirements_extraction.generate_safe',
    side_effect=[
      '<requirements_list><requirement id="R1"><category>Existence</category><description>D1</description></requirement></requirements_list>',
      '<requirements_list><requirement id="R1"><category>Common Use Cases</category><description>D2</description></requirement></requirements_list>',
      '<requirements_list><requirement id="R1"><category>Error Scenarios</category><description>D3</description></requirement></requirements_list>',
      '<requirements_list><requirement id="R1"><category>Invalidation</category><description>D4</description></requirement></requirements_list>',
      '<requirements_list><requirement id="R1"><category>Integration</category><description>D5</description></requirement></requirements_list>',
    ],
  ):
    res = await run_requirements_extraction_categorized(
      context, mock_config, mock_llm, mock_ui, jinja_env, tmp_path
    )

  assert res is not None
  assert '<requirement id="R1">' in res
  assert '<requirement id="R2">' in res
  assert '<requirement id="R3">' in res
  assert '<requirement id="R4">' in res
  assert '<requirement id="R5">' in res
  assert '<category>Existence</category>' in res
  assert '<category>Integration</category>' in res
  assert res.count('<requirement id=') == 5


@pytest.mark.asyncio
async def test_run_requirements_extraction_categorized_partial_empty(
  mock_config: Config, mock_ui: MagicMock, mock_llm: MagicMock, tmp_path: Path
) -> None:
  """Test categorized requirements extraction with some empty responses."""
  context = WorkflowContext(
    feature_id='feat-partial',
    metadata=WebFeatureMetadata('Feat', 'Desc', ['http://spec']),
    spec_contents='Spec',
  )
  jinja_env = MagicMock()
  jinja_env.get_template.return_value.render.return_value = 'Mock Template'

  # Mock generate_safe to return a mixture of requirements and empty lists
  with patch(
    'wptgen.phases.requirements_extraction.generate_safe',
    side_effect=[
      '<requirements_list><requirement id="R1"><category>Existence</category><description>D1</description></requirement></requirements_list>',
      '<requirements_list></requirements_list>',  # Empty
      '<requirements_list><requirement id="R1"><category>Error Scenarios</category><description>D3</description></requirement></requirements_list>',
      '<requirements_list></requirements_list>',  # Empty
      '<requirements_list></requirements_list>',  # Empty
    ],
  ):
    res = await run_requirements_extraction_categorized(
      context, mock_config, mock_llm, mock_ui, jinja_env, tmp_path
    )

  assert res is not None
  assert '<requirement id="R1">' in res
  assert '<requirement id="R2">' in res
  assert '<category>Existence</category>' in res
  assert '<category>Error Scenarios</category>' in res
  assert res.count('<requirement id=') == 2


@pytest.mark.asyncio
async def test_run_requirements_extraction_categorized_with_rationale(
  mock_config: Config, mock_ui: MagicMock, mock_llm: MagicMock, tmp_path: Path
) -> None:
  """Test categorized requirements extraction with a rationale for an empty category."""
  context = WorkflowContext(
    feature_id='feat-rationale',
    metadata=WebFeatureMetadata('Feat', 'Desc', ['http://spec']),
    spec_contents='Spec',
  )
  jinja_env = MagicMock()
  jinja_env.get_template.return_value.render.return_value = 'Mock Template'

  # Mock generate_safe to return one category with a requirement and one with a rationale
  with patch(
    'wptgen.phases.requirements_extraction.generate_safe',
    side_effect=[
      '<requirements_list><requirement id="R1"><category>Existence</category><description>D1</description></requirement></requirements_list>',
      '<requirements_list><rationale>This feature is a simple object and has no complex invalidation rules.</rationale></requirements_list>',
      '<requirements_list></requirements_list>',  # Empty without rationale
      '<requirements_list></requirements_list>',
      '<requirements_list></requirements_list>',
    ],
  ):
    res = await run_requirements_extraction_categorized(
      context, mock_config, mock_llm, mock_ui, jinja_env, tmp_path
    )

  assert res is not None
  assert '<requirement id="R1">' in res
  assert 'rationale' not in res  # Final XML should NOT contain rationales

  # Verify ui.info was called with the rationale
  mock_ui.info.assert_any_call(
    'No requirements found for category [Common Use Cases] This feature is a simple object and has no complex invalidation rules.'
  )


@pytest.mark.asyncio
async def test_provide_coverage_report(
  mock_config: Config, mock_ui: MagicMock, tmp_path: Path
) -> None:
  """Test saving and displaying the coverage report."""
  from wptgen.phases.coverage_audit import provide_coverage_report

  context = WorkflowContext(feature_id='feat-id', audit_response='Audit markdown')
  mock_config.output_dir = str(tmp_path)

  # Test saving to file
  mock_ui.confirm.return_value = True
  await provide_coverage_report(context, mock_config, mock_ui)

  expected_path = tmp_path / 'feat-id_coverage_audit.md'
  assert expected_path.exists()
  mock_ui.report_coverage_audit.assert_called_with('Audit markdown')
  mock_ui.success.assert_any_call(f'Saved: {expected_path.absolute()}')


@pytest.mark.asyncio
async def test_run_test_generation_satisfied(
  mock_config: Config, mock_ui: MagicMock, mock_llm: MagicMock
) -> None:
  """Test test generation when audit status is SATISFIED."""
  context = WorkflowContext(
    feature_id='feat',
    audit_response='<status>SATISFIED</status>',
    metadata=WebFeatureMetadata('Feat', 'Desc', ['http://spec']),
  )
  jinja_env = MagicMock()

  res = await run_test_generation(context, mock_config, mock_llm, mock_ui, jinja_env)

  assert res == []
  mock_ui.success.assert_called_once_with('All identified test requirements have been satisfied.')
  mock_ui.info.assert_called_once()


@pytest.mark.asyncio
async def test_run_test_generation_no_suggestions(
  mock_config: Config, mock_ui: MagicMock, mock_llm: MagicMock
) -> None:
  """Test test generation when no suggestions are found in audit response."""
  context = WorkflowContext(
    feature_id='feat',
    audit_response='no suggestions here',
    metadata=WebFeatureMetadata('Feat', 'Desc', ['http://spec']),
  )
  jinja_env = MagicMock()

  res = await run_test_generation(context, mock_config, mock_llm, mock_ui, jinja_env)

  assert res == []
  mock_ui.warning.assert_called_once_with(
    'No valid <test_suggestion> blocks found in the LLM response.'
  )


@pytest.mark.asyncio
async def test_run_test_generation_reftest_link_fix(
  mock_config: Config, mock_ui: MagicMock, mock_llm: MagicMock, tmp_path: Path
) -> None:
  """Verify that reftest links are corrected during generation."""
  mock_config.output_dir = str(tmp_path)
  context = WorkflowContext(
    feature_id='reftest-feat',
    audit_response='<status>TESTS_NEEDED</status><test_suggestion><test_type>Reftest</test_type><name>my-test</name></test_suggestion>',
    metadata=WebFeatureMetadata('Feat', 'Desc', ['http://spec']),
  )
  jinja_env = MagicMock()
  jinja_env.get_template.return_value.render.return_value = 'Mock Template'

  reftest_content = """
[FILE_1: .html]
<link rel="match" href="wrong-ref.html">
[/FILE_1]
[FILE_2: .html]
Reference content
[/FILE_2]
"""

  with patch('wptgen.phases.generation.generate_safe', return_value=reftest_content):
    res = await run_test_generation(context, mock_config, mock_llm, mock_ui, jinja_env)

  assert len(res) == 2
  test_path, test_content, _ = res[0]
  ref_path, ref_content, _ = res[1]

  assert test_path.name == 'reftest-feat-001.html'
  assert ref_path.name == 'reftest-feat-001-ref.html'
  assert '<link rel="match" href="reftest-feat-001-ref.html">' in test_content


@pytest.mark.asyncio
async def test_run_test_generation_none_selected(
  mock_config: Config, mock_ui: MagicMock, mock_llm: MagicMock
) -> None:
  """Test test generation when user rejects all suggestions."""
  suggestion_xml = (
    '<test_suggestion><title>T1</title><description>D1</description></test_suggestion>'
  )
  context = WorkflowContext(
    feature_id='feat',
    metadata=WebFeatureMetadata('Feat', 'Desc', ['http://spec']),
    audit_response=suggestion_xml,
  )
  jinja_env = MagicMock()

  mock_ui.confirm.return_value = False

  res = await run_test_generation(context, mock_config, mock_llm, mock_ui, jinja_env)

  assert res == []
  mock_ui.warning.assert_any_call('No tests selected. Exiting.')


@pytest.mark.asyncio
async def test_run_test_generation_failure(
  mock_config: Config, mock_ui: MagicMock, mock_llm: MagicMock, tmp_path: Path
) -> None:
  """Test test generation failure when LLM call fails."""
  suggestion_xml = (
    '<test_suggestion><title>T1</title><description>D1</description></test_suggestion>'
  )
  context = WorkflowContext(
    feature_id='feat',
    metadata=WebFeatureMetadata('Feat', 'Desc', ['http://spec']),
    audit_response=suggestion_xml,
  )
  jinja_env = MagicMock()
  jinja_env.get_template.return_value.render.return_value = 'Prompt'

  mock_ui.confirm.return_value = True
  # Mock generation_safe to return empty string (failure)
  with patch('wptgen.phases.generation.generate_safe', return_value=''):
    with patch('wptgen.phases.generation.Path.read_text', return_value='Style Guide'):
      res = await run_test_generation(context, mock_config, mock_llm, mock_ui, jinja_env)

  assert res == []
  mock_ui.report_generation_summary.assert_called_once_with([])


@pytest.mark.asyncio
async def test_run_test_generation_displays_worksheet(
  mock_config: Config, mock_ui: MagicMock, mock_llm: MagicMock
) -> None:
  """Verify that the audit worksheet is displayed before suggestions."""
  suggestion_xml = (
    '<test_suggestion><title>T1</title><description>D1</description></test_suggestion>'
  )
  audit_response = f'<audit_worksheet>R1: Req 1 -> [COVERED by test.html]\nR2: Req 2 -> [UNCOVERED]</audit_worksheet>\n{suggestion_xml}'
  context = WorkflowContext(
    feature_id='feat',
    metadata=WebFeatureMetadata('Feat', 'Desc', ['http://spec']),
    audit_response=audit_response,
  )
  jinja_env = MagicMock()
  jinja_env.get_template.return_value.render.return_value = 'Generated Content'

  mock_ui.confirm.return_value = False  # Stop after displaying worksheet and suggestions

  with (
    patch('wptgen.phases.generation.confirm_prompts', return_value=None),
    patch('wptgen.phases.generation.Path.read_text', return_value='Style Guide Content'),
  ):
    await run_test_generation(context, mock_config, mock_llm, mock_ui, jinja_env)

  # Check that the worksheet was displayed
  mock_ui.report_audit_worksheet.assert_called_once()
