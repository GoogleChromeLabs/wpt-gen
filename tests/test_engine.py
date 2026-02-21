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
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest
import typer
from pytest_mock import MockerFixture

from wptgen.config import Config
from wptgen.context import WebFeatureMetadata, WPTContext
from wptgen.engine import WPTGenEngine


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
def engine(mock_config: Config, mock_llm: MagicMock) -> WPTGenEngine:
  """Provides a WPTGenEngine instance with a mocked LLM client."""
  with patch('wptgen.engine.get_llm_client', return_value=mock_llm):
    return WPTGenEngine(mock_config)


@pytest.mark.asyncio
async def test_confirm_prompts_yes_tokens_enabled(
  engine: WPTGenEngine, mocker: MockerFixture
) -> None:
  """If yes_tokens is True, _confirm_prompts should return without calling Confirm.ask."""
  engine.config.yes_tokens = True
  mock_confirm = mocker.patch('wptgen.engine.Confirm.ask')

  await engine._confirm_prompts([('prompt', 'Task')], 'Phase')

  mock_confirm.assert_not_called()


@pytest.mark.asyncio
async def test_confirm_prompts_user_accepts(engine: WPTGenEngine, mocker: MockerFixture) -> None:
  """If user accepts, _confirm_prompts should return normally."""
  engine.config.yes_tokens = False
  mock_confirm = mocker.patch('wptgen.engine.Confirm.ask', return_value=True)

  await engine._confirm_prompts([('prompt', 'Task')], 'Phase')

  mock_confirm.assert_called_once()


@pytest.mark.asyncio
async def test_confirm_prompts_user_rejects(engine: WPTGenEngine, mocker: MockerFixture) -> None:
  """If user rejects, _confirm_prompts should raise typer.Abort."""
  engine.config.yes_tokens = False
  mocker.patch('wptgen.engine.Confirm.ask', return_value=False)

  with pytest.raises(typer.Abort):
    await engine._confirm_prompts([('prompt', 'Task')], 'Phase')


@pytest.mark.asyncio
async def test_confirm_prompts_batch_calculation(
  engine: WPTGenEngine, mocker: MockerFixture
) -> None:
  """Verify that multiple prompts are summarized together and warnings are shown."""
  engine.config.yes_tokens = False
  mocker.patch('wptgen.engine.Confirm.ask', return_value=True)
  mock_console = mocker.patch.object(engine.console, 'print')

  # Mock token counting to return different values
  cast(MagicMock, engine.llm.count_tokens).side_effect = [100, 200]
  cast(MagicMock, engine.llm.prompt_exceeds_input_token_limit).side_effect = [False, True]

  await engine._confirm_prompts([('p1', 'T1'), ('p2', 'T2')], 'Phase')

  # Check that count_tokens was called
  cast(MagicMock, engine.llm.count_tokens).assert_called_with('p2')

  # Check that it printed total tokens (100 + 200 = 300)
  found_total = False
  for call in mock_console.call_args_list:
    if '300' in str(call):
      found_total = True
      break
  assert found_total

  # Check that it warned about limit (at least one prompt exceeded)
  assert any('Warning' in str(call) for call in mock_console.call_args_list)


@pytest.mark.asyncio
async def test_phase_requirements_analysis_calls_confirm(
  engine: WPTGenEngine, mocker: MockerFixture, mock_llm: MagicMock
) -> None:
  """Verify that Phase 2 calls _confirm_prompts before generation."""
  context = {
    'metadata': MagicMock(specs=['http://spec']),
    'spec_contents': 'spec',
    'wpt_context': MagicMock(),
  }
  mock_confirm = mocker.patch.object(engine, '_confirm_prompts', return_value=None)
  mock_llm.generate_content.side_effect = ['Spec', 'Test']

  await engine._phase_requirements_analysis('feat-id', context)

  mock_confirm.assert_called_once()
  # It should have passed both prompts to confirm
  passed_prompts = mock_confirm.call_args[0][0]
  assert len(passed_prompts) == 2


@pytest.mark.asyncio
async def test_phase_test_suggestions_calls_confirm(
  engine: WPTGenEngine, mocker: MockerFixture, mock_llm: MagicMock
) -> None:
  """Verify that Phase 3 calls _confirm_prompts before generation."""
  analysis = ('Spec', 'Test')
  mock_confirm = mocker.patch.object(engine, '_confirm_prompts', return_value=None)
  mock_llm.generate_content.return_value = 'Suggestions'

  await engine._phase_test_suggestions('feat-id', analysis)

  mock_confirm.assert_called_once()


@pytest.mark.asyncio
async def test_phase_test_generation_calls_confirm(
  engine: WPTGenEngine, mocker: MockerFixture, mock_llm: MagicMock
) -> None:
  """Verify that Phase 4 calls _confirm_prompts with all approved tests."""
  context = {'metadata': MagicMock(name='Feat', description='Desc')}
  suggestions_response = (
    '<test_suggestion><title>T1</title></test_suggestion>'
    '<test_suggestion><title>T2</title></test_suggestion>'
  )

  mocker.patch('wptgen.engine.Prompt.ask', return_value='y')
  mock_confirm = mocker.patch.object(engine, '_confirm_prompts', return_value=None)
  mocker.patch.object(engine, '_generate_and_save', return_value=None)

  await engine._phase_test_generation(context, suggestions_response)

  mock_confirm.assert_called_once()
  # Both T1 and T2 should be in the confirmation list
  assert len(mock_confirm.call_args[0][0]) == 2


@pytest.mark.asyncio
async def test_provide_test_suggestions_save(
  engine: WPTGenEngine, mocker: MockerFixture, tmp_path: Path
) -> None:
  """Verifies that _provide_test_suggestions saves the response to a file when the user confirms."""
  context = {'feature_id': 'test-feat'}
  suggestions_response = 'Mock Suggestions Content'
  engine.config.output_dir = str(tmp_path)

  mocker.patch('wptgen.engine.Confirm.ask', return_value=True)
  # Default filename will be test-feat_test_suggestions.md
  expected_path = tmp_path / 'test-feat_test_suggestions.md'

  await engine._provide_test_suggestions(context, suggestions_response)

  assert expected_path.exists()
  assert expected_path.read_text(encoding='utf-8') == suggestions_response


@pytest.mark.asyncio
async def test_provide_test_suggestions_no_save(
  engine: WPTGenEngine, mocker: MockerFixture
) -> None:
  """Verifies that _provide_test_suggestions does NOT save if the user declines."""
  context = {'feature_id': 'test-feat'}
  suggestions_response = 'Mock Suggestions Content'

  mocker.patch('wptgen.engine.Confirm.ask', return_value=False)
  mock_write = mocker.patch('wptgen.engine.Path.write_text')

  await engine._provide_test_suggestions(context, suggestions_response)

  mock_write.assert_not_called()


@pytest.mark.asyncio
async def test_run_async_workflow_suggestions_only(
  engine: WPTGenEngine, mocker: MockerFixture
) -> None:
  """Verifies that the workflow short-circuits to _provide_test_suggestions when config.suggestions_only is True."""
  engine.config.suggestions_only = True

  mock_metadata = MagicMock()
  mock_metadata.name = 'Test Feature'
  mock_metadata.description = 'Test Description'
  mock_metadata.specs = ['http://spec']

  context = {
    'feature_id': 'test-feat',
    'metadata': mock_metadata,
    'spec_contents': 'spec content',
    'wpt_context': MagicMock(),
  }

  mocker.patch.object(engine, '_phase_context_assembly', return_value=context)
  # Mock token check to fit in context
  mocker.patch.object(engine.llm, 'prompt_exceeds_input_token_limit', return_value=False)
  mocker.patch.object(engine, '_phase_unified_suggestions', return_value='suggestions')
  mock_provide = mocker.patch.object(engine, '_provide_test_suggestions', return_value=None)
  mock_gen = mocker.patch.object(engine, '_phase_test_generation')

  await engine._run_async_workflow('test-feat')

  mock_provide.assert_called_once_with(context, 'suggestions')
  mock_gen.assert_not_called()


def test_engine_init(engine: WPTGenEngine, mock_config: Config) -> None:
  """Verifies that the engine initializes correctly with the given configuration."""
  assert engine.config == mock_config
  assert engine.llm is not None
  assert engine.jinja_env is not None


@pytest.mark.asyncio
async def test_generate_safe_show_responses(
  engine: WPTGenEngine, mock_llm: MagicMock, mocker: MockerFixture
) -> None:
  """Tests that _generate_safe prints the LLM response when show_responses is enabled."""
  engine.config.show_responses = True
  mock_llm.generate_content.return_value = 'Verbose Response'
  mock_console_print = mocker.patch.object(engine.console, 'print')

  result = await engine._generate_safe('prompt', 'Task', 'System Instruction')

  assert result == 'Verbose Response'
  mock_llm.generate_content.assert_called_with('prompt', 'System Instruction', None)
  # Check that console.print was called with the response in a Panel
  assert mock_console_print.call_count >= 2


@pytest.mark.asyncio
async def test_generate_safe_not_show_responses(
  engine: WPTGenEngine, mock_llm: MagicMock, mocker: MockerFixture
) -> None:
  """Tests that _generate_safe does NOT print the LLM response when show_responses is disabled."""
  engine.config.show_responses = False
  mock_llm.generate_content.return_value = 'Quiet Response'
  mock_console_print = mocker.patch.object(engine.console, 'print')

  result = await engine._generate_safe('prompt', 'Task')

  assert result == 'Quiet Response'
  # Should only print the success message
  assert mock_console_print.call_count == 1
  assert 'finished' in mock_console_print.call_args[0][0]


@pytest.mark.asyncio
async def test_generate_safe_failure(engine: WPTGenEngine, mock_llm: MagicMock) -> None:
  """Tests that _generate_safe handles LLM exceptions gracefully and returns an empty string."""
  mock_llm.generate_content.side_effect = Exception('API Error')
  result = await engine._generate_safe('prompt', 'Task')
  assert result == ''


def test_parse_suggestions(engine: WPTGenEngine) -> None:
  """Verifies that _parse_suggestions correctly extracts test suggestion blocks from raw text."""
  raw_text = """
  <test_suggestion>
    <title>Test 1</title>
  </test_suggestion>
  random text
  <test_suggestion>
    <title>Test 2</title>
  </test_suggestion>
  """
  suggestions = engine._parse_suggestions(raw_text)
  assert len(suggestions) == 2
  assert 'Test 1' in suggestions[0]
  assert 'Test 2' in suggestions[1]


def test_extract_xml_tag(engine: WPTGenEngine) -> None:
  """Tests that _extract_xml_tag accurately extracts content from specific XML-like tags."""
  xml = '<title>My Title</title><desc>My Desc</desc>'
  assert engine._extract_xml_tag(xml, 'title') == 'My Title'
  assert engine._extract_xml_tag(xml, 'desc') == 'My Desc'
  assert engine._extract_xml_tag(xml, 'missing') is None


@pytest.mark.asyncio
async def test_generate_and_save_success(
  engine: WPTGenEngine, mock_llm: MagicMock, tmp_path: Path
) -> None:
  """Generates content and writes it to a file, stripping markdown blocks."""
  mock_llm.generate_content.return_value = '```html\n<html></html>\n```'
  engine.config.output_dir = str(tmp_path)
  filename = 'test.html'
  expected_path = tmp_path / filename

  await engine._generate_and_save('prompt', filename, 'System Instruction')

  mock_llm.generate_content.assert_called_with('prompt', 'System Instruction', None)
  assert expected_path.exists()
  assert expected_path.read_text() == '<html></html>'


@pytest.mark.asyncio
async def test_phase_context_assembly_success(engine: WPTGenEngine, mocker: MockerFixture) -> None:
  """Successful assembly of feature context including metadata, spec, and existing tests."""
  mocker.patch('wptgen.engine.fetch_feature_yaml', return_value={'name': 'feat'})
  metadata = WebFeatureMetadata(name='Feature', description='Desc', specs=['http://spec'])
  mocker.patch('wptgen.engine.extract_feature_metadata', return_value=metadata)
  mocker.patch('wptgen.engine.fetch_and_extract_text', return_value='Spec Text')
  mocker.patch('wptgen.engine.find_feature_tests', return_value=['/path/to/test.html'])

  mock_context = WPTContext(
    test_contents={'/path/to/test.html': 'existing test content'},
    dependency_contents={},
    test_to_deps={'/path/to/test.html': set()},
  )
  mocker.patch('wptgen.engine.gather_local_test_context', return_value=mock_context)

  context = await engine._phase_context_assembly('feat-id')
  assert context is not None
  assert context['metadata'] == metadata
  assert context['spec_contents'] == 'Spec Text'
  assert context['wpt_context'] == mock_context


@pytest.mark.asyncio
async def test_phase_context_assembly_with_spec_urls(
  engine: WPTGenEngine, mocker: MockerFixture
) -> None:
  """Context assembly correctly uses spec_urls from config, overriding metadata specs."""
  engine.config.spec_urls = ['http://url1', 'http://url2']
  # fetch_feature_yaml must succeed now
  mocker.patch('wptgen.engine.fetch_feature_yaml', return_value={'name': 'feat'})

  # Should only fetch the FIRST URL in the current implementation
  mock_fetch = mocker.patch('wptgen.engine.fetch_and_extract_text', return_value='Content 1')
  mocker.patch('wptgen.engine.find_feature_tests', return_value=[])
  mock_context = WPTContext()
  mocker.patch('wptgen.engine.gather_local_test_context', return_value=mock_context)

  context = await engine._phase_context_assembly('feat-id')

  assert context is not None
  assert context['metadata'].specs == ['http://url1', 'http://url2']
  assert context['spec_contents'] == 'Content 1'
  mock_fetch.assert_called_once_with('http://url1')


@pytest.mark.asyncio
async def test_phase_context_assembly_no_feature(
  engine: WPTGenEngine, mocker: MockerFixture
) -> None:
  """Context assembly returns None if the web feature ID is not found."""
  mocker.patch('wptgen.engine.fetch_feature_yaml', return_value=None)
  result = await engine._phase_context_assembly('missing')
  assert result is None


@pytest.mark.asyncio
async def test_phase_context_assembly_no_specs(engine: WPTGenEngine, mocker: MockerFixture) -> None:
  """Context assembly fails if no specification URLs are found in the metadata."""
  mocker.patch('wptgen.engine.fetch_feature_yaml', return_value={'name': 'feat'})
  metadata = WebFeatureMetadata(name='Feature', description='Desc', specs=[])
  mocker.patch('wptgen.engine.extract_feature_metadata', return_value=metadata)

  result = await engine._phase_context_assembly('feat-id')
  assert result is None


@pytest.mark.asyncio
async def test_phase_context_assembly_fetch_spec_fails(
  engine: WPTGenEngine, mocker: MockerFixture
) -> None:
  """Context assembly fails if the specification content cannot be fetched."""
  mocker.patch('wptgen.engine.fetch_feature_yaml', return_value={'name': 'feat'})
  metadata = WebFeatureMetadata(name='Feature', description='Desc', specs=['http://spec'])
  mocker.patch('wptgen.engine.extract_feature_metadata', return_value=metadata)
  mocker.patch('wptgen.engine.fetch_and_extract_text', return_value=None)

  result = await engine._phase_context_assembly('feat-id')
  assert result is None


@pytest.mark.asyncio
async def test_phase_requirements_analysis_success(
  engine: WPTGenEngine, mock_llm: MagicMock, mocker: MockerFixture
) -> None:
  """Successful concurrent generation of spec synthesis and test analysis."""
  context = {
    'metadata': MagicMock(specs=['http://spec']),
    'spec_contents': 'spec',
    'wpt_context': MagicMock(),
  }
  mocker.patch.object(engine, '_confirm_prompts', return_value=None)
  mock_llm.generate_content.side_effect = ['Spec Synthesis', 'Test Analysis']

  result = await engine._phase_requirements_analysis('feat-id', context)
  assert result == ('Spec Synthesis', 'Test Analysis')


@pytest.mark.asyncio
async def test_phase_requirements_analysis_failure(
  engine: WPTGenEngine, mock_llm: MagicMock, mocker: MockerFixture
) -> None:
  """Requirements analysis returns None if any part of the analysis fails."""
  context = {
    'metadata': MagicMock(specs=['http://spec']),
    'spec_contents': 'spec',
    'wpt_context': MagicMock(),
  }
  mocker.patch.object(engine, '_confirm_prompts', return_value=None)
  mock_llm.generate_content.side_effect = ['Spec Synthesis', Exception('Fail')]

  result = await engine._phase_requirements_analysis('feat-id', context)
  assert result is None


@pytest.mark.asyncio
async def test_phase_test_suggestions_success(
  engine: WPTGenEngine, mock_llm: MagicMock, mocker: MockerFixture
) -> None:
  """Test suggestions are successfully generated from the analysis results."""
  analysis = ('Spec', 'Test')
  mocker.patch.object(engine, '_confirm_prompts', return_value=None)
  mock_llm.generate_content.return_value = 'Suggestions'

  result = await engine._phase_test_suggestions('feat-id', analysis)
  assert result == 'Suggestions'


@pytest.mark.asyncio
async def test_phase_test_suggestions_failure(
  engine: WPTGenEngine, mock_llm: MagicMock, mocker: MockerFixture
) -> None:
  """Test suggestion phase returns None if the LLM call fails."""
  analysis = ('Spec', 'Test')
  mocker.patch.object(engine, '_confirm_prompts', return_value=None)
  mock_llm.generate_content.side_effect = Exception('Fail')

  result = await engine._phase_test_suggestions('feat-id', analysis)
  assert result is None


@pytest.mark.asyncio
async def test_phase_test_generation_success(engine: WPTGenEngine, mocker: MockerFixture) -> None:
  """Test generation proceeds for suggestions approved by the user with system instruction."""
  context = {'metadata': MagicMock(name='Feat', description='Desc')}
  suggestions_response = (
    '<test_suggestion><title>Test 1</title><description>D1</description></test_suggestion>'
  )

  mocker.patch('wptgen.engine.Prompt.ask', return_value='y')
  mocker.patch.object(engine, '_confirm_prompts', return_value=None)
  mock_gen_save = mocker.patch.object(engine, '_generate_and_save', return_value=None)

  await engine._phase_test_generation(context, suggestions_response)

  mock_gen_save.assert_called_once()
  assert mock_gen_save.call_args[0][1] == 'test_1__GENERATED_01_.html'
  assert mock_gen_save.call_args[0][2] is not None
  assert 'SYSTEM ROLE' in mock_gen_save.call_args[0][2]


@pytest.mark.asyncio
async def test_phase_test_generation_no_suggestions(engine: WPTGenEngine) -> None:
  """Verifies that the generation phase handles cases where no valid suggestions are provided."""
  context: dict[str, Any] = {'metadata': MagicMock()}
  await engine._phase_test_generation(context, 'no suggestions here')
  # No exception should be raised


@pytest.mark.asyncio
async def test_phase_test_generation_rejected(engine: WPTGenEngine, mocker: MockerFixture) -> None:
  """Generation is skipped for suggestions rejected by the user."""
  context = {'metadata': MagicMock(name='Feat', description='Desc')}
  suggestions_response = '<test_suggestion><title>Test 1</title></test_suggestion>'

  mocker.patch('wptgen.engine.Prompt.ask', return_value='n')
  mock_gen_save = mocker.patch.object(engine, '_generate_and_save', return_value=None)

  await engine._phase_test_generation(context, suggestions_response)
  mock_gen_save.assert_not_called()


@pytest.mark.asyncio
async def test_run_async_workflow_full_path(engine: WPTGenEngine, mocker: MockerFixture) -> None:
  """Full asynchronous workflow orchestration, ensuring each phase is called."""
  # Mock all phases
  mock_metadata = MagicMock()
  mock_metadata.name = 'Test Feature'
  mock_metadata.description = 'Test Description'
  mock_metadata.specs = ['http://spec']

  mock_wpt_context = MagicMock()
  mock_wpt_context.test_contents = {}
  mock_wpt_context.dependency_contents = {}

  context = {
    'metadata': mock_metadata,
    'spec_contents': 'spec content',
    'wpt_context': mock_wpt_context,
  }
  analysis = ('spec', 'test')
  suggestions = 'sugg'

  mocker.patch.object(engine, '_phase_context_assembly', return_value=context)
  # Mock token check to force multi-step flow (default behavior for this test)
  cast(MagicMock, engine.llm.prompt_exceeds_input_token_limit).return_value = True

  mocker.patch.object(engine, '_phase_requirements_analysis', return_value=analysis)
  mocker.patch.object(engine, '_phase_test_suggestions', return_value=suggestions)
  mocker.patch.object(engine, '_phase_test_generation', return_value=None)

  await engine._run_async_workflow('feat-id')

  cast(MagicMock, engine._phase_context_assembly).assert_called_once()
  cast(MagicMock, engine._phase_requirements_analysis).assert_called_once()
  cast(MagicMock, engine._phase_test_suggestions).assert_called_once()
  cast(MagicMock, engine._phase_test_generation).assert_called_once()


@pytest.mark.asyncio
async def test_phase_context_assembly_unregistered_feature_with_spec_urls_and_description(
  engine: WPTGenEngine, mocker: MockerFixture
) -> None:
  """Context assembly succeeds for unregistered features if spec_urls and description are provided."""
  engine.config.spec_urls = ['http://custom-spec']
  engine.config.feature_description = 'Custom Description'
  mocker.patch('wptgen.engine.fetch_feature_yaml', return_value=None)
  mocker.patch('wptgen.engine.fetch_and_extract_text', return_value='Custom Spec Content')
  mocker.patch('wptgen.engine.find_feature_tests', return_value=[])
  mocker.patch('wptgen.engine.gather_local_test_context', return_value=WPTContext())

  context = await engine._phase_context_assembly('custom-feat')

  assert context is not None
  assert context['feature_id'] == 'custom-feat'
  assert context['metadata'].name == 'custom-feat'
  assert context['metadata'].description == 'Custom Description'
  assert context['metadata'].specs == ['http://custom-spec']
  assert context['spec_contents'] == 'Custom Spec Content'


@pytest.mark.asyncio
async def test_phase_context_assembly_unregistered_feature_missing_spec_or_desc(
  engine: WPTGenEngine, mocker: MockerFixture
) -> None:
  """Context assembly fails for unregistered features if either spec_urls or description are missing."""
  mocker.patch('wptgen.engine.fetch_feature_yaml', return_value=None)

  # Case 1: Only spec_urls provided
  engine.config.spec_urls = ['http://spec']
  engine.config.feature_description = None
  result = await engine._phase_context_assembly('custom-feat')
  assert result is None

  # Case 2: Only description provided
  engine.config.spec_urls = None
  engine.config.feature_description = 'Description'
  result = await engine._phase_context_assembly('custom-feat')
  assert result is None


@pytest.mark.asyncio
async def test_phase_context_assembly_read_test_fails(
  engine: WPTGenEngine, mocker: MockerFixture
) -> None:
  """Tests that context assembly continues even if reading an individual test file fails."""
  mocker.patch('wptgen.engine.fetch_feature_yaml', return_value={'name': 'feat'})
  metadata = WebFeatureMetadata(name='Feature', description='Desc', specs=['http://spec'])
  mocker.patch('wptgen.engine.extract_feature_metadata', return_value=metadata)
  mocker.patch('wptgen.engine.fetch_and_extract_text', return_value='Spec Text')
  test_path = os.path.abspath(os.sep + 'path' + os.sep + 'to' + os.sep + 'test.html')
  mocker.patch('wptgen.engine.find_feature_tests', return_value=[test_path])

  with patch('wptgen.engine.Path.read_text', side_effect=Exception('Read Error')):
    context = await engine._phase_context_assembly('feat-id')

  assert context is not None
  assert len(context['wpt_context'].test_contents) == 0


@pytest.mark.asyncio
async def test_generate_and_save_with_output_dir(
  engine: WPTGenEngine, mock_llm: MagicMock, tmp_path: Path
) -> None:
  """Verifies that generated tests are saved to the correct output_dir when configured."""
  output_dir = tmp_path / 'custom_output'
  engine.config.output_dir = str(output_dir)
  mock_llm.generate_content.return_value = '<html></html>'
  filename = 'test.html'
  expected_path = output_dir / filename

  await engine._generate_and_save('prompt', filename)

  assert expected_path.exists()
  assert expected_path.read_text() == '<html></html>'


@pytest.mark.asyncio
async def test_generate_and_save_markdown_variants(
  engine: WPTGenEngine, mock_llm: MagicMock, tmp_path: Path
) -> None:
  """Tests that _generate_and_save handles various markdown block formats correctly."""
  engine.config.output_dir = str(tmp_path)

  # Variant 1: No markdown blocks
  mock_llm.generate_content.return_value = '<html>No Markdown</html>'
  file1 = 'test1.html'
  await engine._generate_and_save('prompt', file1)
  assert (tmp_path / file1).read_text() == '<html>No Markdown</html>'

  # Variant 2: Markdown without language tag
  mock_llm.generate_content.return_value = '```\n<html>No Tag</html>\n```'
  file2 = 'test2.html'
  await engine._generate_and_save('prompt', file2)
  assert (tmp_path / file2).read_text() == '<html>No Tag</html>'


def test_extract_xml_tag_malformed(engine: WPTGenEngine) -> None:
  """Tests that _extract_xml_tag handles malformed or missing tags gracefully."""
  xml = '<title>Valid</title><desc>Incomplete'
  assert engine._extract_xml_tag(xml, 'title') == 'Valid'
  assert engine._extract_xml_tag(xml, 'desc') is None
  assert engine._extract_xml_tag(xml, '') is None


@pytest.mark.asyncio
async def test_phase_test_generation_filename_sanitization(
  engine: WPTGenEngine, mocker: MockerFixture
) -> None:
  """Tests that suggestion titles with special characters are sanitized into safe filenames."""
  context = {'metadata': MagicMock(name='Feat', description='Desc')}
  # Title with spaces, uppercase, and special characters
  suggestions_response = '<test_suggestion><title>Test: My Cool Feature!</title></test_suggestion>'

  mocker.patch('wptgen.engine.Confirm.ask', return_value=True)
  mocker.patch('wptgen.engine.Prompt.ask', return_value='y')
  mocker.patch.object(engine, '_confirm_prompts', return_value=None)
  mock_gen_save = mocker.patch.object(engine, '_generate_and_save', return_value=None)

  await engine._phase_test_generation(context, suggestions_response)

  # Check the sanitized filename
  expected_filename = 'test__my_cool_feature___GENERATED_01_.html'
  mock_gen_save.assert_called_once()
  assert mock_gen_save.call_args[0][1] == expected_filename


@pytest.mark.asyncio
async def test_phase_test_generation_mixed_approval(
  engine: WPTGenEngine, mocker: MockerFixture
) -> None:
  """Tests that only suggestions approved by the user (y) are generated when multiple are present."""
  context = {'metadata': MagicMock(name='Feat', description='Desc')}
  suggestions_response = (
    '<test_suggestion><title>Test 1</title></test_suggestion>'
    '<test_suggestion><title>Test 2</title></test_suggestion>'
  )

  # User says 'y' to first, 'n' to second
  mocker.patch('wptgen.engine.Prompt.ask', side_effect=['y', 'n'])
  mocker.patch.object(engine, '_confirm_prompts', return_value=None)
  mock_gen_save = mocker.patch.object(engine, '_generate_and_save', return_value=None)

  await engine._phase_test_generation(context, suggestions_response)

  # Only Test 1 should be generated
  assert mock_gen_save.call_count == 1
  assert 'test_1__GENERATED_01_.html' == mock_gen_save.call_args[0][1]


@pytest.mark.asyncio
async def test_phase_test_generation_tag_fallbacks(
  engine: WPTGenEngine, mocker: MockerFixture
) -> None:
  """Verifies that the engine uses fallback values when title or description tags are missing/empty."""
  context = {'metadata': MagicMock(name='Feat', description='Desc')}
  # Suggestion with no tags at all
  suggestions_response = '<test_suggestion>empty</test_suggestion>'

  mocker.patch('wptgen.engine.Prompt.ask', return_value='y')
  mocker.patch.object(engine, '_confirm_prompts', return_value=None)
  mock_gen_save = mocker.patch.object(engine, '_generate_and_save', return_value=None)

  await engine._phase_test_generation(context, suggestions_response)

  # Fallback filename when title tag is missing
  mock_gen_save.assert_called_once()
  assert mock_gen_save.call_args[0][1] == 'file__GENERATED_01_.html'


@pytest.mark.asyncio
async def test_generate_and_save_write_error(engine: WPTGenEngine, mock_llm: MagicMock) -> None:
  """Tests that a file system error during writing is propagated."""
  mock_llm.generate_content.return_value = '<html></html>'
  with patch('wptgen.engine.Path.write_text', side_effect=OSError('Disk Full')):
    with pytest.raises(OSError, match='Disk Full'):
      await engine._generate_and_save('prompt', 'error.html')


@pytest.mark.asyncio
async def test_phase_test_generation_duplicate_titles(
  engine: WPTGenEngine, mocker: MockerFixture
) -> None:
  """Tests that multiple suggestions with identical titles now generate unique filenames."""
  context = {'metadata': MagicMock(name='Feat', description='Desc')}
  # Two suggestions with the same title
  suggestions_response = (
    '<test_suggestion><title>Same Title</title></test_suggestion>'
    '<test_suggestion><title>Same Title</title></test_suggestion>'
  )

  mocker.patch('wptgen.engine.Prompt.ask', return_value='y')
  mocker.patch.object(engine, '_confirm_prompts', return_value=None)
  mock_gen_save = mocker.patch.object(engine, '_generate_and_save', return_value=None)

  await engine._phase_test_generation(context, suggestions_response)

  # Both should be "generated" with unique filenames
  assert mock_gen_save.call_count == 2
  filename1 = mock_gen_save.call_args_list[0][0][1]
  filename2 = mock_gen_save.call_args_list[1][0][1]
  assert filename1 != filename2
  assert '01' in filename1
  assert '02' in filename2


@pytest.mark.asyncio
async def test_phase_test_generation_partial_failure(
  engine: WPTGenEngine, mocker: MockerFixture
) -> None:
  """Tests that a failure in one parallel generation task does not stop others."""
  context = {'metadata': MagicMock(name='Feat', description='Desc')}
  suggestions_response = (
    '<test_suggestion><title>Success Test</title></test_suggestion>'
    '<test_suggestion><title>Fail Test</title></test_suggestion>'
  )

  mocker.patch('wptgen.engine.Prompt.ask', return_value='y')
  mocker.patch.object(engine, '_confirm_prompts', return_value=None)

  # Mock _generate_and_save to succeed for one and fail for another
  async def side_effect(prompt: str, filename: str, system_instruction: str | None = None) -> None:
    if 'fail_test' in filename:
      raise Exception('Random Write Error')

  mocker.patch.object(engine, '_generate_and_save', side_effect=side_effect)

  # We expect the exception to bubble up from asyncio.gather if not caught
  with pytest.raises(Exception, match='Random Write Error'):
    await engine._phase_test_generation(context, suggestions_response)


def test_extract_xml_tag_empty_content(engine: WPTGenEngine) -> None:
  """Tests that _extract_xml_tag treats empty or whitespace-only tags as None/empty string."""
  assert engine._extract_xml_tag('<title></title>', 'title') == ''
  assert engine._extract_xml_tag('<title>   </title>', 'title') == ''


@pytest.mark.asyncio
async def test_phase_test_generation_unicode_stability(
  engine: WPTGenEngine, mocker: MockerFixture
) -> None:
  """Verifies that titles with Unicode/Emoji are sanitized correctly and don't break generation."""
  context = {'metadata': MagicMock(name='Feat', description='Desc')}
  suggestions_response = '<test_suggestion><title>Test 🚀 & 中文</title></test_suggestion>'

  mocker.patch('wptgen.engine.Prompt.ask', return_value='y')
  mocker.patch.object(engine, '_confirm_prompts', return_value=None)
  mock_gen_save = mocker.patch.object(engine, '_generate_and_save', return_value=None)

  await engine._phase_test_generation(context, suggestions_response)

  mock_gen_save.assert_called_once()
  filename = mock_gen_save.call_args[0][1]
  assert '__GENERATED_01_' in filename
  assert filename.endswith('.html')


@pytest.mark.asyncio
async def test_run_async_workflow_short_circuit(
  engine: WPTGenEngine, mocker: MockerFixture
) -> None:
  """Verifies that the workflow stops immediately if context assembly fails."""
  mocker.patch.object(engine, '_phase_context_assembly', return_value=None)
  mock_analysis = mocker.patch.object(engine, '_phase_requirements_analysis')

  await engine._run_async_workflow('feat-id')

  cast(MagicMock, engine._phase_context_assembly).assert_called_once()
  # Analysis should never be called if assembly fails
  mock_analysis.assert_not_called()


@pytest.mark.asyncio
async def test_phase_requirements_analysis_concurrent_failure(
  engine: WPTGenEngine, mock_llm: MagicMock, mocker: MockerFixture
) -> None:
  """Verifies that the engine handles cases where both concurrent analysis tasks return empty strings."""
  context = {
    'metadata': MagicMock(specs=['http://spec']),
    'spec_contents': 'spec',
    'wpt_context': MagicMock(),
  }
  mocker.patch.object(engine, '_confirm_prompts', return_value=None)
  # Both LLM calls return empty (failure mode of _generate_safe)
  mock_llm.generate_content.side_effect = ['', '']

  result = await engine._phase_requirements_analysis('feat-id', context)
  assert result is None


@pytest.mark.asyncio
async def test_phase_context_assembly_empty_spec_list(
  engine: WPTGenEngine, mocker: MockerFixture
) -> None:
  """Tests that context assembly handles cases where the spec list is empty in the metadata."""
  mocker.patch('wptgen.engine.fetch_feature_yaml', return_value={'name': 'feat'})
  # Metadata with empty specs list
  metadata = WebFeatureMetadata(name='Feature', description='Desc', specs=[])
  mocker.patch('wptgen.engine.extract_feature_metadata', return_value=metadata)

  result = await engine._phase_context_assembly('feat-id')
  assert result is None


@pytest.mark.asyncio
async def test_generate_and_save_whitespace_resilience(
  engine: WPTGenEngine, mock_llm: MagicMock, tmp_path: Path
) -> None:
  """Tests that markdown stripping handles markdown blocks when they are at the start of a line."""
  # LLM output with markdown blocks at the start of the line (current engine requirement)
  mock_llm.generate_content.return_value = '\n```html\n<html></html>\n```\n'
  engine.config.output_dir = str(tmp_path)
  filename = 'whitespace.html'

  await engine._generate_and_save('prompt', filename)

  assert '<html></html>' in (tmp_path / filename).read_text()
  assert '```html' not in (tmp_path / filename).read_text()


@pytest.mark.asyncio
async def test_phase_test_generation_long_title(
  engine: WPTGenEngine, mocker: MockerFixture
) -> None:
  """Tests that extremely long suggestion titles are handled by the sanitization logic."""
  context = {'metadata': MagicMock(name='Feat', description='Desc')}
  # Title longer than 255 chars
  long_title = 'A' * 300
  suggestions_response = f'<test_suggestion><title>{long_title}</title></test_suggestion>'

  mocker.patch('wptgen.engine.Prompt.ask', return_value='y')
  mocker.patch.object(engine, '_confirm_prompts', return_value=None)
  mock_gen_save = mocker.patch.object(engine, '_generate_and_save', return_value=None)

  await engine._phase_test_generation(context, suggestions_response)

  mock_gen_save.assert_called_once()
  filename = mock_gen_save.call_args[0][1]
  assert len(filename) > 300
  assert '__GENERATED_01_' in filename


def test_run_workflow(engine: WPTGenEngine, mocker: MockerFixture) -> None:
  """Verifies that the synchronous run_workflow entry point correctly launches the async workflow."""
  mock_run = mocker.patch('asyncio.run')
  # Use standard MagicMock to avoid automatic AsyncMock wrapping
  from unittest.mock import MagicMock

  mock_async_workflow = MagicMock(return_value='dummy_coro')
  with patch.object(engine, '_run_async_workflow', mock_async_workflow):
    engine.run_workflow('feat-id')

  mock_run.assert_called_once_with('dummy_coro')
  mock_async_workflow.assert_called_once_with('feat-id')
