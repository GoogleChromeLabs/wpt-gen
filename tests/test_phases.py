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

import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_mock import MockerFixture

from wptgen.config import Config
from wptgen.models import FeatureMetadata, WorkflowContext, WPTContext
from wptgen.phases.context_assembly import run_context_assembly
from wptgen.phases.coverage_audit import (
  combine_audit_responses,
  partition_requirements_xml,
  provide_coverage_report,
)
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
async def test_run_context_assembly_success(
  mock_config: Config, mock_ui: MagicMock, mocker: MockerFixture
) -> None:
  """Test successful context assembly for a registered feature."""
  mocker.patch('wptgen.phases.context_assembly.fetch_feature_yaml', return_value={'name': 'feat'})
  mocker.patch(
    'wptgen.phases.context_assembly.extract_feature_metadata',
    return_value=FeatureMetadata('Feat', 'Desc', ['http://spec']),
  )
  mocker.patch('wptgen.phases.context_assembly.fetch_and_extract_text', return_value='Spec Content')
  mocker.patch('wptgen.phases.context_assembly.find_feature_tests', return_value=[])
  mocker.patch(
    'wptgen.phases.context_assembly.gather_local_test_context', return_value=WPTContext()
  )

  context = await run_context_assembly('feat-id', mock_config, mock_ui)

  assert context is not None
  assert context.feature_id == 'feat-id'
  assert context.metadata is not None
  assert context.metadata.name == 'Feat'
  assert context.spec_contents == {'http://spec': 'Spec Content'}
  mock_ui.on_phase_start.assert_called_once_with(1, 'Context Assembly')
  mock_ui.report_metadata.assert_called_once()


@pytest.mark.asyncio
async def test_run_context_assembly_with_mdn(
  mock_config: Config, mock_ui: MagicMock, mocker: MockerFixture
) -> None:
  """Test context assembly with MDN documentation fetching."""
  mocker.patch('wptgen.phases.context_assembly.fetch_feature_yaml', return_value={'name': 'feat'})
  mocker.patch(
    'wptgen.phases.context_assembly.extract_feature_metadata',
    return_value=FeatureMetadata('Feat', 'Desc', ['http://spec']),
  )
  mock_fetch = mocker.patch('wptgen.phases.context_assembly.fetch_and_extract_text')
  mocker.patch(
    'wptgen.phases.context_assembly.fetch_mdn_urls', return_value=['http://mdn1', 'http://mdn2']
  )
  mocker.patch('wptgen.phases.context_assembly.find_feature_tests', return_value=[])
  mocker.patch(
    'wptgen.phases.context_assembly.gather_local_test_context', return_value=WPTContext()
  )

  mock_fetch.side_effect = ['Spec Content', 'MDN Content 1', 'MDN Content 2']

  context = await run_context_assembly('feat-id', mock_config, mock_ui)

  assert context is not None
  assert isinstance(context.mdn_contents, list)
  assert len(context.mdn_contents) == 2
  mock_ui.report_context_summary.assert_called_once()


@pytest.mark.asyncio
async def test_run_context_assembly_unregistered_with_params(
  mock_config: Config, mock_ui: MagicMock, mocker: MockerFixture
) -> None:
  """Test context assembly for an unregistered feature with manual parameters."""
  mock_config.spec_urls = ['http://manual-spec']
  mock_config.feature_description = 'Manual Description'

  mocker.patch('wptgen.phases.context_assembly.fetch_feature_yaml', return_value=None)
  mocker.patch('wptgen.phases.context_assembly.fetch_mdn_urls', return_value=[])
  mocker.patch('wptgen.phases.context_assembly.fetch_and_extract_text', return_value='Spec Content')
  mocker.patch('wptgen.phases.context_assembly.find_feature_tests', return_value=[])
  mocker.patch(
    'wptgen.phases.context_assembly.gather_local_test_context', return_value=WPTContext()
  )

  context = await run_context_assembly('unregistered', mock_config, mock_ui)

  assert context is not None
  assert context.metadata is not None
  assert context.metadata.name == 'unregistered'
  assert mock_ui.warning.call_count == 2
  mock_ui.warning.assert_any_call('Feature unregistered not found in the web-features repository.')
  mock_ui.warning.assert_any_call('No existing Web Platform Tests were successfully loaded.')


@pytest.mark.asyncio
async def test_run_context_assembly_not_found(
  mock_config: Config, mock_ui: MagicMock, mocker: MockerFixture
) -> None:
  """Test context assembly when feature is not found and no manual params provided."""
  mocker.patch('wptgen.phases.context_assembly.fetch_feature_yaml', return_value=None)
  context = await run_context_assembly('not-found', mock_config, mock_ui)
  assert context is None
  mock_ui.error.assert_called_once()


@pytest.mark.asyncio
async def test_run_context_assembly_no_specs(
  mock_config: Config, mock_ui: MagicMock, mocker: MockerFixture
) -> None:
  """Test context assembly failure when no spec URLs are found."""
  mocker.patch('wptgen.phases.context_assembly.fetch_feature_yaml', return_value={'name': 'feat'})
  mocker.patch(
    'wptgen.phases.context_assembly.extract_feature_metadata',
    return_value=FeatureMetadata('Feat', 'Desc', []),
  )
  context = await run_context_assembly('feat-id', mock_config, mock_ui)
  assert context is None
  mock_ui.error.assert_called_once()


@pytest.mark.asyncio
async def test_run_context_assembly_chromestatus_with_wpt_descr(
  mock_config: Config, mock_ui: MagicMock, mocker: MockerFixture
) -> None:
  """Test context assembly for a ChromeStatus feature with wpt_descr."""
  mock_config.chromestatus = True
  metadata = FeatureMetadata('Feat', 'Desc', ['http://spec'], wpt_descr='css/test.html')

  mock_fetch_meta = mocker.patch(
    'wptgen.phases.context_assembly.fetch_chromestatus_metadata', return_value=metadata
  )
  mocker.patch('wptgen.phases.context_assembly.fetch_and_extract_text', return_value='Spec Content')
  mocker.patch('wptgen.phases.context_assembly.find_feature_tests', return_value=[])
  mock_extract = mocker.patch(
    'wptgen.phases.context_assembly.extract_wpt_paths', return_value=['css/test.html']
  )
  mock_validate = mocker.patch(
    'wptgen.phases.context_assembly.validate_wpt_paths',
    return_value=(['/abs/css/test.html'], ['invalid/path']),
  )
  mock_gather = mocker.patch(
    'wptgen.phases.context_assembly.gather_local_test_context', return_value=WPTContext()
  )

  context = await run_context_assembly('feat-id', mock_config, mock_ui)

  assert context is not None
  assert context.wpt_urls == ['css/test.html']
  mock_fetch_meta.assert_called_once()
  mock_extract.assert_called_once_with('css/test.html')
  mock_validate.assert_called_once_with(['css/test.html'], mock_config.wpt_path)
  mock_ui.warning.assert_called_with(
    'Referenced WPT test file could not be found or read: invalid/path'
  )
  # Check that gather_local_test_context was called with the validated path
  mock_gather.assert_called_once_with(['/abs/css/test.html'], mock_config.wpt_path)


@pytest.mark.asyncio
async def test_run_context_assembly_chromestatus_too_many_tests(
  mock_config: Config, mock_ui: MagicMock, mocker: MockerFixture
) -> None:
  """Test that context assembly warns but proceeds if too many tests are found."""
  mock_config.chromestatus = True
  metadata = FeatureMetadata('Feat', 'Desc', ['http://spec'], wpt_descr='css/')

  mocker.patch('wptgen.phases.context_assembly.fetch_chromestatus_metadata', return_value=metadata)
  mocker.patch('wptgen.phases.context_assembly.fetch_and_extract_text', return_value='Spec Content')
  mocker.patch('wptgen.phases.context_assembly.find_feature_tests', return_value=[])
  mocker.patch('wptgen.phases.context_assembly.extract_wpt_paths', return_value=['css/'])
  mocker.patch(
    'wptgen.phases.context_assembly.validate_wpt_paths',
    side_effect=ValueError('Too many tests found (60). Max allowed is 50.'),
  )
  mocker.patch(
    'wptgen.phases.context_assembly.gather_local_test_context',
    return_value=WPTContext(test_contents={}),
  )

  await run_context_assembly('feat-id', mock_config, mock_ui)

  # Should have warned about skipping ChromeStatus tests
  mock_ui.warning.assert_any_call(
    'Skipping ChromeStatus tests: Too many tests found (60). Max allowed is 50.'
  )
  # Should also have warned that no tests were loaded (since find_feature_tests returned [])
  mock_ui.warning.assert_any_call('No existing Web Platform Tests were successfully loaded.')


@pytest.mark.asyncio
async def test_run_requirements_extraction_cached(
  mock_config: Config, mock_ui: MagicMock, mock_llm: MagicMock, tmp_path: Path
) -> None:
  """Test requirements extraction when a valid cache exists."""
  context = WorkflowContext(
    feature_id='feat',
    metadata=FeatureMetadata('Feat', 'Desc', ['http://spec']),
    spec_contents={'http://spec': 'Spec'},
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
  mock_ui.success.assert_any_call('Using cached requirements.')
  mock_ui.success.assert_any_call('Extracted 0 test requirements.')


@pytest.mark.asyncio
async def test_run_requirements_extraction_with_explainer(
  mock_config: Config, mock_ui: MagicMock, mock_llm: MagicMock, tmp_path: Path
) -> None:
  """Test requirements extraction when explainer contents are present."""
  context = WorkflowContext(
    feature_id='feat-explainer',
    metadata=FeatureMetadata('Feat', 'Desc', ['http://spec']),
    spec_contents={'http://spec': 'Spec Content'},
    explainer_contents={
      'http://explainer1': 'Explainer Content 1',
      'http://explainer2': 'Explainer Content 2',
    },
  )
  jinja_env = MagicMock()
  template_mock = MagicMock()
  jinja_env.get_template.return_value = template_mock

  with patch(
    'wptgen.phases.requirements_extraction.generate_safe',
    return_value='<requirements_list><requirement id="R1"><category>Existence</category><description>D1</description></requirement></requirements_list>',
  ):
    await run_requirements_extraction(context, mock_config, mock_llm, mock_ui, jinja_env, tmp_path)

  # Verify explainer_contents was passed to render
  template_mock.render.assert_any_call(
    feature_name='Feat',
    feature_description='Desc',
    specs={'http://spec': 'Spec Content'},
    mdn_contents=None,
    explainer_contents={
      'http://explainer1': 'Explainer Content 1',
      'http://explainer2': 'Explainer Content 2',
    },
  )


@pytest.mark.asyncio
async def test_run_requirements_extraction_categorized_with_explainer(
  mock_config: Config, mock_ui: MagicMock, mock_llm: MagicMock, tmp_path: Path
) -> None:
  """Test categorized requirements extraction when explainer contents are present."""
  context = WorkflowContext(
    feature_id='feat-explainer-cat',
    metadata=FeatureMetadata('Feat', 'Desc', ['http://spec']),
    spec_contents={'http://spec': 'Spec Content'},
    explainer_contents={'http://explainer1': 'Explainer Content 1'},
  )
  jinja_env = MagicMock()
  template_mock = MagicMock()
  jinja_env.get_template.return_value = template_mock

  with patch(
    'wptgen.phases.requirements_extraction.generate_safe',
    return_value='<requirements_list><requirement id="R1"><category>Existence</category><description>D1</description></requirement></requirements_list>',
  ):
    await run_requirements_extraction_categorized(
      context, mock_config, mock_llm, mock_ui, jinja_env, tmp_path
    )

  # Verify explainer_contents was passed to render
  template_mock.render.assert_any_call(
    feature_name='Feat',
    feature_description='Desc',
    specs={'http://spec': 'Spec Content'},
    mdn_contents=None,
    explainer_contents={'http://explainer1': 'Explainer Content 1'},
  )


@pytest.mark.asyncio
async def test_run_requirements_extraction_categorized(
  mock_config: Config,
  mock_ui: MagicMock,
  mock_llm: MagicMock,
  tmp_path: Path,
  mocker: MockerFixture,
) -> None:
  """Test categorized requirements extraction with mocked LLM responses."""
  context = WorkflowContext(
    feature_id='feat',
    metadata=FeatureMetadata('Feat', 'Desc', ['http://spec']),
    spec_contents={'http://spec': 'Spec'},
  )
  jinja_env = MagicMock()
  jinja_env.get_template.return_value.render.return_value = 'Mock Template'

  # Mock generate_safe to return a single requirement for each call
  mocker.patch(
    'wptgen.phases.requirements_extraction.generate_safe',
    side_effect=[
      '<requirements_list><requirement id="R1"><category>Existence</category><description>D1</description></requirement></requirements_list>',
      '<requirements_list><requirement id="R1"><category>Common Use Cases</category><description>D2</description></requirement></requirements_list>',
      '<requirements_list><requirement id="R1"><category>Error Scenarios</category><description>D3</description></requirement></requirements_list>',
      '<requirements_list><requirement id="R1"><category>Invalidation</category><description>D4</description></requirement></requirements_list>',
      '<requirements_list><requirement id="R1"><category>Integration</category><description>D5</description></requirement></requirements_list>',
    ],
  )
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
  mock_config: Config,
  mock_ui: MagicMock,
  mock_llm: MagicMock,
  tmp_path: Path,
  mocker: MockerFixture,
) -> None:
  """Test categorized requirements extraction with some empty responses."""
  context = WorkflowContext(
    feature_id='feat-partial',
    metadata=FeatureMetadata('Feat', 'Desc', ['http://spec']),
    spec_contents={'http://spec': 'Spec'},
  )
  jinja_env = MagicMock()
  jinja_env.get_template.return_value.render.return_value = 'Mock Template'

  # Mock generate_safe to return a mixture of requirements and empty lists
  mocker.patch(
    'wptgen.phases.requirements_extraction.generate_safe',
    side_effect=[
      '<requirements_list><requirement id="R1"><category>Existence</category><description>D1</description></requirement></requirements_list>',
      '<requirements_list></requirements_list>',  # Empty
      '<requirements_list><requirement id="R1"><category>Error Scenarios</category><description>D3</description></requirement></requirements_list>',
      '<requirements_list></requirements_list>',  # Empty
      '<requirements_list></requirements_list>',  # Empty
    ],
  )
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
  mock_config: Config,
  mock_ui: MagicMock,
  mock_llm: MagicMock,
  tmp_path: Path,
  mocker: MockerFixture,
) -> None:
  """Test categorized requirements extraction with a rationale for an empty category."""
  context = WorkflowContext(
    feature_id='feat-rationale',
    metadata=FeatureMetadata('Feat', 'Desc', ['http://spec']),
    spec_contents={'http://spec': 'Spec'},
  )
  jinja_env = MagicMock()
  jinja_env.get_template.return_value.render.return_value = 'Mock Template'

  # Mock generate_safe to return one category with a requirement and one with a rationale
  mocker.patch(
    'wptgen.phases.requirements_extraction.generate_safe',
    side_effect=[
      '<requirements_list><requirement id="R1"><category>Existence</category><description>D1</description></requirement></requirements_list>',
      '<requirements_list><rationale>This feature is a simple object and has no complex invalidation rules.</rationale></requirements_list>',
      '<requirements_list></requirements_list>',  # Empty without rationale
      '<requirements_list></requirements_list>',
      '<requirements_list></requirements_list>',
    ],
  )
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
    metadata=FeatureMetadata('Feat', 'Desc', ['http://spec']),
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
    metadata=FeatureMetadata('Feat', 'Desc', ['http://spec']),
  )
  jinja_env = MagicMock()

  res = await run_test_generation(context, mock_config, mock_llm, mock_ui, jinja_env)

  assert res == []
  mock_ui.warning.assert_called_once_with(
    'No valid <test_suggestion> blocks found in the LLM response.'
  )


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
    metadata=FeatureMetadata('Feat', 'Desc', ['http://spec']),
    audit_response=suggestion_xml,
  )
  jinja_env = MagicMock()

  mock_ui.confirm.return_value = False

  res = await run_test_generation(context, mock_config, mock_llm, mock_ui, jinja_env)

  assert res == []
  mock_ui.warning.assert_any_call('No tests selected. Exiting.')


def test_partition_requirements_xml() -> None:
  """Test partition logic."""
  # Empty or no tags
  assert partition_requirements_xml('') == []
  assert partition_requirements_xml('just text') == ['just text']

  # Less than threshold
  reqs = '<requirement id="1">A</requirement>\n<requirement id="2">B</requirement>'
  assert partition_requirements_xml(reqs, max_threshold=2) == [reqs]

  # Even split (4 total, max 2)
  reqs4 = '\n'.join(f'<requirement id="{i}">{i}</requirement>' for i in range(1, 5))
  parts = partition_requirements_xml(reqs4, max_threshold=2)
  assert len(parts) == 2
  assert 'id="1"' in parts[0]
  assert 'id="2"' in parts[0]
  assert 'id="3"' in parts[1]
  assert 'id="4"' in parts[1]

  # Uneven split: 41 requirements, max 40 -> chunks of 21 and 20
  reqs41 = '\n'.join(f'<requirement id="{i}">{i}</requirement>' for i in range(1, 42))
  parts41 = partition_requirements_xml(reqs41, max_threshold=40)
  assert len(parts41) == 2
  assert len(re.findall(r'<requirement\b[^>]*>', parts41[0])) == 21
  assert len(re.findall(r'<requirement\b[^>]*>', parts41[1])) == 20
  assert 'id="21"' in parts41[0]
  assert 'id="22"' in parts41[1]

  # Straggler distribution (42 reqs, max 40 -> 21 and 21)
  reqs42 = '\n'.join(f'<requirement id="{i}">{i}</requirement>' for i in range(1, 43))
  parts42 = partition_requirements_xml(reqs42, max_threshold=40)
  assert len(parts42) == 2
  assert len(re.findall(r'<requirement\b[^>]*>', parts42[0])) == 21
  assert len(re.findall(r'<requirement\b[^>]*>', parts42[1])) == 21


def test_combine_audit_responses() -> None:
  """Test combine audit logic."""
  resp1 = """<status>SATISFIED</status>
<audit_worksheet>
R1: COVERED
</audit_worksheet>"""

  resp2 = """<status>TESTS_NEEDED</status>
<audit_worksheet>
R2: UNCOVERED
</audit_worksheet>
<test_suggestion>Suggestion 1</test_suggestion>"""

  resp3 = """<status>SATISFIED</status>
<audit_worksheet>
R3: COVERED
</audit_worksheet>
<test_suggestion>Suggestion 2</test_suggestion>"""

  combined = combine_audit_responses([resp1, resp2, resp3])

  assert '<status>TESTS_NEEDED</status>' in combined
  assert 'R1: COVERED' in combined
  assert 'R2: UNCOVERED' in combined
  assert 'R3: COVERED' in combined
  assert '<test_suggestion>Suggestion 1</test_suggestion>' in combined
  assert '<test_suggestion>Suggestion 2</test_suggestion>' in combined


@pytest.mark.asyncio
async def test_run_test_generation_adk(
  mock_config: Config, mock_ui: MagicMock, mock_llm: MagicMock, mocker: MockerFixture
) -> None:
  """Test that ADK generation branches correctly and calls _generate_adk_loop."""
  from wptgen.models import WorkflowContext
  from wptgen.phases.generation import run_test_generation

  suggestion_xml = (
    '<test_suggestion><title>T1</title><description>D1</description></test_suggestion>'
  )
  context = WorkflowContext(
    feature_id='feat',
    metadata=FeatureMetadata('Feat', 'D', ['url']),
    audit_response=f'<audit_worksheet>W</audit_worksheet>{suggestion_xml}',
  )
  mock_ui.confirm.return_value = True

  mock_adk = mocker.patch('wptgen.phases.generation._generate_adk_loop')
  mock_adk.return_value = []

  from jinja2 import BaseLoader, Environment

  jinja_env = Environment(loader=BaseLoader())

  results = await run_test_generation(context, mock_config, mock_llm, mock_ui, jinja_env)

  assert mock_adk.called
  assert results == []


@pytest.mark.asyncio
async def test_generate_adk_loop(
  mock_config: Config, mock_ui: MagicMock, mocker: MockerFixture
) -> None:
  """Test that _generate_adk_loop properly maps the suggestions and triggers tasks."""
  from wptgen.models import WorkflowContext
  from wptgen.phases.generation import _generate_adk_loop

  mock_config.output_dir = 'test_dir'
  mock_config.brief_suggestions = False

  suggestion_xml = '<test_suggestion><title>T1</title><test_type>JavaScript Test</test_type><description>D1</description></test_suggestion>'
  context = WorkflowContext(
    feature_id='feat',
    metadata=FeatureMetadata('Feat', 'D', ['url']),
  )

  mock_adk = mocker.patch(
    'wptgen.agents.adk_test_generator.generate_test_with_adk',
    new_callable=AsyncMock,
    create=True,
  )
  mock_adk.return_value = [(Path('test_dir/feat.html'), 'content', suggestion_xml)]

  from jinja2 import BaseLoader, Environment

  jinja_env = Environment(loader=BaseLoader())

  results = await _generate_adk_loop([suggestion_xml], context, mock_config, mock_ui, jinja_env)

  assert mock_adk.called
  assert len(results) == 1
  assert results[0][1] == 'content'
