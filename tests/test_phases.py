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
from wptgen.phases.requirements_extraction import (
  run_requirements_extraction,
  run_requirements_extraction_iterative,
)


@pytest.fixture
def mock_ui() -> MagicMock:
  """Fixture that provides a mocked UI provider with a status context manager."""
  ui = MagicMock()
  ui.status.return_value.__enter__.return_value = None
  return ui


@pytest.fixture
def mock_config() -> Config:
  """Fixture that provides a basic test configuration."""
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
      'evaluation': 'lightweight',
    },
    cache_path='/tmp/cache',
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
    assert 'MDN Content 1' in context.mdn_contents[0]
    assert 'Documentation from http://mdn1' in context.mdn_contents[0]
    assert 'MDN Content 2' in context.mdn_contents[1]
    assert 'Documentation from http://mdn2' in context.mdn_contents[1]
    assert mock_fetch.call_count == 3


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
    assert context.metadata.specs == ['http://manual-spec']
    assert context.metadata.description == 'Manual Description'


@pytest.mark.asyncio
async def test_run_context_assembly_not_found(mock_config: Config, mock_ui: MagicMock) -> None:
  """Test context assembly when feature is not found and no manual params provided."""
  with patch('wptgen.phases.context_assembly.fetch_feature_yaml', return_value=None):
    context = await run_context_assembly('not-found', mock_config, mock_ui)
    assert context is None


@pytest.mark.asyncio
async def test_run_context_assembly_override_metadata(
  mock_config: Config, mock_ui: MagicMock
) -> None:
  """Test that manual parameters override registered feature metadata."""
  mock_config.spec_urls = ['http://override-spec']
  mock_config.feature_description = 'Override Description'

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
    assert context.metadata is not None
    assert context.metadata.specs == ['http://override-spec']
    assert context.metadata.description == 'Override Description'


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


@pytest.mark.asyncio
async def test_run_context_assembly_spec_fetch_failure(
  mock_config: Config, mock_ui: MagicMock
) -> None:
  """Test context assembly failure when spec fetching fails."""
  with (
    patch('wptgen.phases.context_assembly.fetch_feature_yaml', return_value={'name': 'feat'}),
    patch(
      'wptgen.phases.context_assembly.extract_feature_metadata',
      return_value=WebFeatureMetadata('Feat', 'Desc', ['http://spec']),
    ),
    patch('wptgen.phases.context_assembly.fetch_and_extract_text', return_value=''),
  ):
    context = await run_context_assembly('feat-id', mock_config, mock_ui)
    assert context is None


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
  assert context.requirements_xml == '<reqs>cached</reqs>'


@pytest.mark.asyncio
async def test_run_requirements_extraction_success(
  mock_config: Config, mock_ui: MagicMock, mock_llm: MagicMock, tmp_path: Path
) -> None:
  """Test successful requirements extraction (single pass)."""
  context = WorkflowContext(
    feature_id='feat',
    metadata=WebFeatureMetadata('Feat', 'Desc', ['http://spec']),
    spec_contents='Spec',
  )
  jinja_env = MagicMock()
  jinja_env.get_template.return_value.render.return_value = 'Prompt'

  mock_llm.generate_content.return_value = '<reqs>generated</reqs>'

  with patch('wptgen.phases.requirements_extraction.confirm_prompts', return_value=None):
    res = await run_requirements_extraction(
      context, mock_config, mock_llm, mock_ui, jinja_env, tmp_path
    )

  assert res == '<reqs>generated</reqs>'
  assert context.requirements_xml == '<reqs>generated</reqs>'


@pytest.mark.asyncio
async def test_run_requirements_extraction_with_mdn(
  mock_config: Config, mock_ui: MagicMock, mock_llm: MagicMock, tmp_path: Path
) -> None:
  """Test that requirements extraction correctly passes mdn_contents to the template."""
  mdn_list = ['MDN 1', 'MDN 2']
  context = WorkflowContext(
    feature_id='feat',
    metadata=WebFeatureMetadata('Feat', 'Desc', ['http://spec']),
    spec_contents='Spec',
    mdn_contents=mdn_list,
  )
  jinja_env = MagicMock()
  template_mock = MagicMock()
  jinja_env.get_template.return_value = template_mock

  mock_llm.generate_content.return_value = '<reqs>generated</reqs>'

  with patch('wptgen.phases.requirements_extraction.confirm_prompts', return_value=None):
    await run_requirements_extraction(context, mock_config, mock_llm, mock_ui, jinja_env, tmp_path)

  # Verify render was called with mdn_contents for the main template
  # It gets called twice: once for the prompt, once for the system prompt
  prompt_call = next(
    call for call in template_mock.render.call_args_list if 'mdn_contents' in call.kwargs
  )
  assert prompt_call.kwargs['mdn_contents'] == mdn_list
  assert prompt_call.kwargs['spec_contents'] == 'Spec'


@pytest.mark.asyncio
async def test_run_requirements_extraction_iterative_with_mdn(
  mock_config: Config, mock_ui: MagicMock, mock_llm: MagicMock, tmp_path: Path
) -> None:
  """Test that iterative requirements extraction correctly passes mdn_contents."""
  mdn_list = ['MDN 1', 'MDN 2']
  context = WorkflowContext(
    feature_id='feat',
    metadata=WebFeatureMetadata('Feat', 'Desc', ['http://spec']),
    spec_contents='Spec',
    mdn_contents=mdn_list,
  )
  jinja_env = MagicMock()
  template_mock = MagicMock()
  jinja_env.get_template.return_value = template_mock

  mock_llm.generate_content.return_value = (
    '<requirements_list><status>EXHAUSTED</status></requirements_list>'
  )

  with patch('wptgen.phases.requirements_extraction.confirm_prompts', return_value=None):
    await run_requirements_extraction_iterative(
      context, mock_config, mock_llm, mock_ui, jinja_env, tmp_path
    )

  # Verify render was called with mdn_contents
  prompt_call = next(
    call for call in template_mock.render.call_args_list if 'mdn_contents' in call.kwargs
  )
  assert prompt_call.kwargs['mdn_contents'] == mdn_list


@pytest.mark.asyncio
async def test_run_requirements_extraction_failure(
  mock_config: Config, mock_ui: MagicMock, mock_llm: MagicMock, tmp_path: Path
) -> None:
  """Test requirements extraction failure when generation fails."""
  context = WorkflowContext(
    feature_id='feat',
    metadata=WebFeatureMetadata('Feat', 'Desc', ['http://spec']),
    spec_contents='Spec',
  )
  jinja_env = MagicMock()
  jinja_env.get_template.return_value.render.return_value = 'Prompt'

  # Mock generate_safe to return empty string
  with patch('wptgen.phases.requirements_extraction.generate_safe', return_value=''):
    res = await run_requirements_extraction(
      context, mock_config, mock_llm, mock_ui, jinja_env, tmp_path
    )

  assert res is None


@pytest.mark.asyncio
async def test_run_coverage_audit_success(
  mock_config: Config, mock_ui: MagicMock, mock_llm: MagicMock
) -> None:
  """Test successful coverage audit."""
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
  assert expected_path.read_text() == 'Audit markdown'

  # Test not saving to file
  mock_ui.confirm.return_value = False
  await provide_coverage_report(context, mock_config, mock_ui)

  # Test error during save
  mock_ui.confirm.return_value = True
  with patch('wptgen.phases.coverage_audit.Path.write_text', side_effect=Exception('error')):
    await provide_coverage_report(context, mock_config, mock_ui)
    mock_ui.print.assert_any_call('[bold red]Error saving file:[/bold red] error')


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
  mock_ui.display_panel.assert_called_once()
  assert 'satisfied' in mock_ui.display_panel.call_args[0][0].lower()


@pytest.mark.asyncio
async def test_run_test_generation_success(
  mock_config: Config, mock_ui: MagicMock, mock_llm: MagicMock, tmp_path: Path
) -> None:
  """Test successful test generation from suggestions."""
  suggestion_xml = (
    '<test_suggestion><title>T1</title><description>D1</description></test_suggestion>'
  )
  context = WorkflowContext(
    feature_id='feat',
    metadata=WebFeatureMetadata('Feat', 'Desc', ['http://spec']),
    audit_response=suggestion_xml,
  )
  jinja_env = MagicMock()
  jinja_env.get_template.return_value.render.return_value = 'Generated Content'

  mock_ui.confirm.return_value = True
  mock_llm.generate_content.return_value = '<html></html>'
  mock_config.output_dir = str(tmp_path)

  with (
    patch('wptgen.phases.generation.confirm_prompts', return_value=None),
    patch('wptgen.phases.generation.Path.read_text', return_value='Style Guide Content'),
  ):
    res = await run_test_generation(context, mock_config, mock_llm, mock_ui, jinja_env)

  expected_file = tmp_path / 't1__GENERATED_01_.html'
  assert expected_file.exists()

  assert expected_file.read_text() == '<html></html>'
  assert res == [(expected_file, '<html></html>', suggestion_xml)]


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
  mock_ui.print.assert_any_call(
    '[yellow]No valid <test_suggestion> blocks found in the LLM response.[/yellow]'
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
    metadata=WebFeatureMetadata('Feat', 'Desc', ['http://spec']),
    audit_response=suggestion_xml,
  )
  jinja_env = MagicMock()

  mock_ui.confirm.return_value = False

  res = await run_test_generation(context, mock_config, mock_llm, mock_ui, jinja_env)

  assert res == []
  mock_ui.print.assert_any_call('[yellow]No tests selected. Exiting.[/yellow]')


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
  mock_ui.print.assert_any_call('\n[bold red]✘ No tests were successfully generated.[/bold red]')


@pytest.mark.asyncio
async def test_run_requirements_extraction_iterative_success(
  mock_config: Config, mock_ui: MagicMock, mock_llm: MagicMock, tmp_path: Path
) -> None:
  """Test iterative requirements extraction success."""
  context = WorkflowContext(
    feature_id='feat',
    metadata=WebFeatureMetadata('Feat', 'Desc', ['http://spec']),
    spec_contents='Spec',
  )
  jinja_env = MagicMock()
  jinja_env.get_template.return_value.render.return_value = 'Prompt'

  # Mock sequence of responses: 1. some reqs, 2. EXHAUSTED
  mock_llm.generate_content.side_effect = [
    '<requirements_list><requirement id="R_NEW_1"><description>Req 1</description></requirement></requirements_list>',
    '<requirements_list><status>EXHAUSTED</status></requirements_list>',
  ]

  with patch('wptgen.phases.requirements_extraction.confirm_prompts', return_value=None):
    res = await run_requirements_extraction_iterative(
      context, mock_config, mock_llm, mock_ui, jinja_env, tmp_path
    )

  assert res is not None
  assert '<requirement id="R1">' in res
  assert 'Req 1' in res
  assert context.requirements_xml == res
  assert mock_llm.generate_content.call_count == 2


@pytest.mark.asyncio
async def test_run_requirements_extraction_iterative_reindexing(
  mock_config: Config, mock_ui: MagicMock, mock_llm: MagicMock, tmp_path: Path
) -> None:
  """Test that requirements are correctly re-indexed across iterations."""
  context = WorkflowContext(
    feature_id='feat',
    metadata=WebFeatureMetadata('Feat', 'Desc', ['http://spec']),
    spec_contents='Spec',
  )
  jinja_env = MagicMock()
  jinja_env.get_template.return_value.render.return_value = 'Prompt'

  mock_llm.generate_content.side_effect = [
    '<requirements_list><requirement id="R_NEW_1"><description>Req A</description></requirement></requirements_list>',
    '<requirements_list><requirement id="R_NEW_1"><description>Req B</description></requirement></requirements_list>',
    '<requirements_list><status>EXHAUSTED</status></requirements_list>',
  ]

  with patch('wptgen.phases.requirements_extraction.confirm_prompts', return_value=None):
    res = await run_requirements_extraction_iterative(
      context, mock_config, mock_llm, mock_ui, jinja_env, tmp_path
    )

  assert res is not None
  assert '<requirement id="R1">' in res
  assert '<requirement id="R2">' in res
  assert 'Req A' in res
  assert 'Req B' in res


@pytest.mark.asyncio
async def test_run_requirements_extraction_iterative_max_iterations(
  mock_config: Config, mock_ui: MagicMock, mock_llm: MagicMock, tmp_path: Path
) -> None:
  """Test iterative extraction stops at max iterations."""
  context = WorkflowContext(
    feature_id='feat',
    metadata=WebFeatureMetadata('Feat', 'Desc', ['http://spec']),
    spec_contents='Spec',
  )
  jinja_env = MagicMock()
  jinja_env.get_template.return_value.render.return_value = 'Prompt'

  # Return 1 req every time (10 iterations)
  mock_llm.generate_content.return_value = '<requirements_list><requirement id="R_NEW_1"><description>Req</description></requirement></requirements_list>'

  with patch('wptgen.phases.requirements_extraction.confirm_prompts', return_value=None):
    res = await run_requirements_extraction_iterative(
      context, mock_config, mock_llm, mock_ui, jinja_env, tmp_path
    )

  assert res is not None
  assert mock_llm.generate_content.call_count == 10
  assert '<requirement id="R10">' in res


@pytest.mark.asyncio
async def test_run_requirements_extraction_iterative_no_new_reqs(
  mock_config: Config, mock_ui: MagicMock, mock_llm: MagicMock, tmp_path: Path
) -> None:
  """Test iterative extraction stops if no new requirements are found in an iteration."""
  context = WorkflowContext(
    feature_id='feat',
    metadata=WebFeatureMetadata('Feat', 'Desc', ['http://spec']),
    spec_contents='Spec',
  )
  jinja_env = MagicMock()
  jinja_env.get_template.return_value.render.return_value = 'Prompt'

  # Iteration 1: Req found. Iteration 2: No req found (not EXHAUSTED though).
  mock_llm.generate_content.side_effect = [
    '<requirements_list><requirement id="R1"><description>R</description></requirement></requirements_list>',
    '<requirements_list></requirements_list>',
  ]

  with patch('wptgen.phases.requirements_extraction.confirm_prompts', return_value=None):
    res = await run_requirements_extraction_iterative(
      context, mock_config, mock_llm, mock_ui, jinja_env, tmp_path
    )

  assert res is not None
  assert mock_llm.generate_content.call_count == 2
  assert '<requirement id="R1">' in res


@pytest.mark.asyncio
async def test_run_requirements_extraction_iterative_failure(
  mock_config: Config, mock_ui: MagicMock, mock_llm: MagicMock, tmp_path: Path
) -> None:
  """Test iterative extraction stops if generate_safe returns empty string."""
  context = WorkflowContext(
    feature_id='feat',
    metadata=WebFeatureMetadata('Feat', 'Desc', ['http://spec']),
    spec_contents='Spec',
  )
  jinja_env = MagicMock()
  jinja_env.get_template.return_value.render.return_value = 'Prompt'

  with patch('wptgen.phases.requirements_extraction.generate_safe', return_value=''):
    res = await run_requirements_extraction_iterative(
      context, mock_config, mock_llm, mock_ui, jinja_env, tmp_path
    )

  assert res is None


@pytest.mark.asyncio
async def test_run_requirements_extraction_iterative_cached(
  mock_config: Config, mock_ui: MagicMock, mock_llm: MagicMock, tmp_path: Path
) -> None:
  """Test iterative extraction uses cache if available."""
  context = WorkflowContext(
    feature_id='feat',
    metadata=WebFeatureMetadata('Feat', 'Desc', ['http://spec']),
  )
  cache_dir = tmp_path
  cache_file = cache_dir / 'feat__requirements.xml'
  cache_file.write_text('<reqs>cached</reqs>')

  mock_ui.confirm.return_value = True

  res = await run_requirements_extraction_iterative(
    context, mock_config, mock_llm, mock_ui, MagicMock(), cache_dir
  )

  assert res == '<reqs>cached</reqs>'
  assert mock_llm.generate_content.call_count == 0


@pytest.mark.asyncio
async def test_run_requirements_extraction_iterative_no_reqs_at_all(
  mock_config: Config, mock_ui: MagicMock, mock_llm: MagicMock, tmp_path: Path
) -> None:
  """Test iterative extraction returns None if no requirements are ever found."""
  context = WorkflowContext(
    feature_id='feat',
    metadata=WebFeatureMetadata('Feat', 'Desc', ['http://spec']),
    spec_contents='Spec',
  )
  jinja_env = MagicMock()
  jinja_env.get_template.return_value.render.return_value = 'Prompt'

  # First response is EXHAUSTED
  mock_llm.generate_content.return_value = (
    '<requirements_list><status>EXHAUSTED</status></requirements_list>'
  )

  with patch('wptgen.phases.requirements_extraction.confirm_prompts', return_value=None):
    res = await run_requirements_extraction_iterative(
      context, mock_config, mock_llm, mock_ui, jinja_env, tmp_path
    )

  assert res is None
