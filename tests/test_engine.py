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
from unittest.mock import MagicMock, patch

import pytest

from wptgen.config import Config
from wptgen.context import WebFeatureMetadata, WPTContext
from wptgen.engine import WPTGenEngine


@pytest.fixture
def mock_config():
  """Provides a basic Config object for testing."""
  return Config(
    provider='llmbargainbin',
    model='discountmodel',
    api_key='fake-key',
    wpt_path=os.path.abspath(os.sep + 'fake' + os.sep + 'wpt'),
  )


@pytest.fixture
def mock_llm():
  """Provides a mocked LLM client."""
  llm = MagicMock()
  llm.generate_content.return_value = 'Mocked LLM Response'
  return llm


@pytest.fixture
def engine(mock_config, mock_llm):
  """Provides a WPTGenEngine instance with a mocked LLM client."""
  with patch('wptgen.engine.get_llm_client', return_value=mock_llm):
    return WPTGenEngine(mock_config)


def test_engine_init(engine, mock_config):
  """Verifies that the engine initializes correctly with the given configuration."""
  assert engine.config == mock_config
  assert engine.llm is not None
  assert engine.jinja_env is not None


@pytest.mark.asyncio
async def test_generate_safe_show_responses(engine, mock_llm, mocker):
  """Tests that _generate_safe prints the LLM response when show_responses is enabled."""
  engine.config.show_responses = True
  mock_llm.generate_content.return_value = 'Verbose Response'
  mock_console_print = mocker.patch.object(engine.console, 'print')

  result = await engine._generate_safe('prompt', 'Task')

  assert result == 'Verbose Response'
  # Check that console.print was called with the response in a Panel
  # We can't easily check the Panel object equality, but we can check if it was called.
  assert mock_console_print.call_count >= 2  # "✔ Task finished." and the Panel


@pytest.mark.asyncio
async def test_generate_safe_not_show_responses(engine, mock_llm, mocker):
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
async def test_generate_safe_failure(engine, mock_llm):
  """Tests that _generate_safe handles LLM exceptions gracefully and returns an empty string."""
  mock_llm.generate_content.side_effect = Exception('API Error')
  result = await engine._generate_safe('prompt', 'Task')
  assert result == ''


def test_parse_suggestions(engine):
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


def test_extract_xml_tag(engine):
  """Tests that _extract_xml_tag accurately extracts content from specific XML-like tags."""
  xml = '<title>My Title</title><desc>My Desc</desc>'
  assert engine._extract_xml_tag(xml, 'title') == 'My Title'
  assert engine._extract_xml_tag(xml, 'desc') == 'My Desc'
  assert engine._extract_xml_tag(xml, 'missing') is None


@pytest.mark.asyncio
async def test_generate_and_save_success(engine, mock_llm, tmp_path):
  """Generates content and writes it to a file, stripping markdown blocks."""
  mock_llm.generate_content.return_value = '```html\n<html></html>\n```'
  filename = tmp_path / 'test.html'

  # Patch Path to write to our tmp_path
  with patch('wptgen.engine.Path', return_value=filename):
    await engine._generate_and_save('prompt', 'test.html')

  assert filename.exists()
  assert filename.read_text() == '<html></html>'


@pytest.mark.asyncio
async def test_phase_context_assembly_success(engine, mocker):
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

  assert context['metadata'] == metadata
  assert context['spec_contents'] == 'Spec Text'
  assert context['wpt_context'] == mock_context


@pytest.mark.asyncio
async def test_phase_context_assembly_no_feature(engine, mocker):
  """Context assembly returns None if the web feature ID is not found."""
  mocker.patch('wptgen.engine.fetch_feature_yaml', return_value=None)
  result = await engine._phase_context_assembly('missing')
  assert result is None


@pytest.mark.asyncio
async def test_phase_context_assembly_no_specs(engine, mocker):
  """Context assembly fails if no specification URLs are found in the metadata."""
  mocker.patch('wptgen.engine.fetch_feature_yaml', return_value={'name': 'feat'})
  metadata = WebFeatureMetadata(name='Feature', description='Desc', specs=[])
  mocker.patch('wptgen.engine.extract_feature_metadata', return_value=metadata)

  result = await engine._phase_context_assembly('feat-id')
  assert result is None


@pytest.mark.asyncio
async def test_phase_context_assembly_fetch_spec_fails(engine, mocker):
  """Context assembly fails if the specification content cannot be fetched."""
  mocker.patch('wptgen.engine.fetch_feature_yaml', return_value={'name': 'feat'})
  metadata = WebFeatureMetadata(name='Feature', description='Desc', specs=['http://spec'])
  mocker.patch('wptgen.engine.extract_feature_metadata', return_value=metadata)
  mocker.patch('wptgen.engine.fetch_and_extract_text', return_value=None)

  result = await engine._phase_context_assembly('feat-id')
  assert result is None


@pytest.mark.asyncio
async def test_phase_requirements_analysis_success(engine, mock_llm):
  """Successful concurrent generation of spec synthesis and test analysis."""
  context = {
    'metadata': MagicMock(specs=['http://spec']),
    'spec_contents': 'spec',
    'wpt_context': MagicMock(),
  }
  mock_llm.generate_content.side_effect = ['Spec Synthesis', 'Test Analysis']

  result = await engine._phase_requirements_analysis('feat-id', context)
  assert result == ('Spec Synthesis', 'Test Analysis')


@pytest.mark.asyncio
async def test_phase_requirements_analysis_failure(engine, mock_llm):
  """Requirements analysis returns None if any part of the analysis fails."""
  context = {
    'metadata': MagicMock(specs=['http://spec']),
    'spec_contents': 'spec',
    'wpt_context': MagicMock(),
  }
  mock_llm.generate_content.side_effect = ['Spec Synthesis', Exception('Fail')]

  result = await engine._phase_requirements_analysis('feat-id', context)
  assert result is None


@pytest.mark.asyncio
async def test_phase_test_suggestions_success(engine, mock_llm):
  """Test suggestions are successfully generated from the analysis results."""
  analysis = ('Spec', 'Test')
  mock_llm.generate_content.return_value = 'Suggestions'

  result = await engine._phase_test_suggestions('feat-id', analysis)
  assert result == 'Suggestions'


@pytest.mark.asyncio
async def test_phase_test_suggestions_failure(engine, mock_llm):
  """Test suggestion phase returns None if the LLM call fails."""
  analysis = ('Spec', 'Test')
  mock_llm.generate_content.side_effect = Exception('Fail')

  result = await engine._phase_test_suggestions('feat-id', analysis)
  assert result is None


@pytest.mark.asyncio
async def test_phase_test_generation_success(engine, mocker):
  """Test generation proceeds for suggestions approved by the user."""
  context = {'metadata': MagicMock(name='Feat', description='Desc')}
  suggestions_response = (
    '<test_suggestion><title>Test 1</title><description>D1</description></test_suggestion>'
  )

  mocker.patch('wptgen.engine.Prompt.ask', return_value='y')
  mock_gen_save = mocker.patch.object(engine, '_generate_and_save', return_value=None)

  await engine._phase_test_generation(context, suggestions_response)

  mock_gen_save.assert_called_once()
  assert mock_gen_save.call_args[0][1] == 'test_generated_01_test_1.html'


@pytest.mark.asyncio
async def test_phase_test_generation_no_suggestions(engine):
  """Verifies that the generation phase handles cases where no valid suggestions are provided."""
  context = {'metadata': MagicMock()}
  await engine._phase_test_generation(context, 'no suggestions here')
  # No exception should be raised


@pytest.mark.asyncio
async def test_phase_test_generation_rejected(engine, mocker):
  """Generation is skipped for suggestions rejected by the user."""
  context = {'metadata': MagicMock(name='Feat', description='Desc')}
  suggestions_response = '<test_suggestion><title>Test 1</title></test_suggestion>'

  mocker.patch('wptgen.engine.Prompt.ask', return_value='n')
  mock_gen_save = mocker.patch.object(engine, '_generate_and_save', return_value=None)

  await engine._phase_test_generation(context, suggestions_response)
  mock_gen_save.assert_not_called()


@pytest.mark.asyncio
async def test_run_async_workflow_full_path(engine, mocker):
  """Full asynchronous workflow orchestration, ensuring each phase is called."""
  # Mock all phases
  context = {'metadata': 'meta'}
  analysis = ('spec', 'test')
  suggestions = 'sugg'

  mocker.patch.object(engine, '_phase_context_assembly', return_value=context)
  mocker.patch.object(engine, '_phase_requirements_analysis', return_value=analysis)
  mocker.patch.object(engine, '_phase_test_suggestions', return_value=suggestions)
  mocker.patch.object(engine, '_phase_test_generation', return_value=None)

  await engine._run_async_workflow('feat-id')

  engine._phase_context_assembly.assert_called_once()
  engine._phase_requirements_analysis.assert_called_once()
  engine._phase_test_suggestions.assert_called_once()
  engine._phase_test_generation.assert_called_once()


@pytest.mark.asyncio
async def test_phase_context_assembly_read_test_fails(engine, mocker):
  """Tests that context assembly continues even if reading an individual test file fails."""
  mocker.patch('wptgen.engine.fetch_feature_yaml', return_value={'name': 'feat'})
  metadata = WebFeatureMetadata(name='Feature', description='Desc', specs=['http://spec'])
  mocker.patch('wptgen.engine.extract_feature_metadata', return_value=metadata)
  mocker.patch('wptgen.engine.fetch_and_extract_text', return_value='Spec Text')
  test_path = os.path.abspath(os.sep + 'path' + os.sep + 'to' + os.sep + 'test.html')
  mocker.patch('wptgen.engine.find_feature_tests', return_value=[test_path])

  with patch('wptgen.engine.Path.read_text', side_effect=Exception('Read Error')):
    context = await engine._phase_context_assembly('feat-id')

  assert len(context['wpt_context'].test_contents) == 0


@pytest.mark.asyncio
async def test_generate_and_save_markdown_variants(engine, mock_llm, tmp_path):
  """Tests that _generate_and_save handles various markdown block formats correctly."""
  # Variant 1: No markdown blocks
  mock_llm.generate_content.return_value = '<html>No Markdown</html>'
  file1 = tmp_path / 'test1.html'
  with patch('wptgen.engine.Path', return_value=file1):
    await engine._generate_and_save('prompt', 'test1.html')
  assert file1.read_text() == '<html>No Markdown</html>'

  # Variant 2: Markdown without language tag
  mock_llm.generate_content.return_value = '```\n<html>No Tag</html>\n```'
  file2 = tmp_path / 'test2.html'
  with patch('wptgen.engine.Path', return_value=file2):
    await engine._generate_and_save('prompt', 'test2.html')
  assert file2.read_text() == '<html>No Tag</html>'


def test_extract_xml_tag_malformed(engine):
  """Tests that _extract_xml_tag handles malformed or missing tags gracefully."""
  xml = '<title>Valid</title><desc>Incomplete'
  assert engine._extract_xml_tag(xml, 'title') == 'Valid'
  assert engine._extract_xml_tag(xml, 'desc') is None
  assert engine._extract_xml_tag(xml, '') is None


@pytest.mark.asyncio
async def test_phase_test_generation_filename_sanitization(engine, mocker):
  """Tests that suggestion titles with special characters are sanitized into safe filenames."""
  context = {'metadata': MagicMock(name='Feat', description='Desc')}
  # Title with spaces, uppercase, and special characters
  suggestions_response = '<test_suggestion><title>Test: My Cool Feature!</title></test_suggestion>'

  mocker.patch('wptgen.engine.Prompt.ask', return_value='y')
  mock_gen_save = mocker.patch.object(engine, '_generate_and_save', return_value=None)

  await engine._phase_test_generation(context, suggestions_response)

  # Check the sanitized filename
  expected_filename = 'test_generated_01_test__my_cool_feature_.html'
  mock_gen_save.assert_called_once()
  assert mock_gen_save.call_args[0][1] == expected_filename


@pytest.mark.asyncio
async def test_phase_test_generation_mixed_approval(engine, mocker):
  """Tests that only suggestions approved by the user (y) are generated when multiple are present."""
  context = {'metadata': MagicMock(name='Feat', description='Desc')}
  suggestions_response = (
    '<test_suggestion><title>Test 1</title></test_suggestion>'
    '<test_suggestion><title>Test 2</title></test_suggestion>'
  )

  # User says 'y' to first, 'n' to second
  mocker.patch('wptgen.engine.Prompt.ask', side_effect=['y', 'n'])
  mock_gen_save = mocker.patch.object(engine, '_generate_and_save', return_value=None)

  await engine._phase_test_generation(context, suggestions_response)

  # Only Test 1 should be generated
  assert mock_gen_save.call_count == 1
  assert 'test_generated_01_test_1.html' == mock_gen_save.call_args[0][1]


@pytest.mark.asyncio
async def test_phase_test_generation_tag_fallbacks(engine, mocker):
  """Verifies that the engine uses fallback values when title or description tags are missing/empty."""
  context = {'metadata': MagicMock(name='Feat', description='Desc')}
  # Suggestion with no tags at all
  suggestions_response = '<test_suggestion>empty</test_suggestion>'

  mocker.patch('wptgen.engine.Prompt.ask', return_value='y')
  mock_gen_save = mocker.patch.object(engine, '_generate_and_save', return_value=None)

  await engine._phase_test_generation(context, suggestions_response)

  # Fallback filename when title tag is missing
  mock_gen_save.assert_called_once()
  assert mock_gen_save.call_args[0][1] == 'test_generated_01_file.html'


@pytest.mark.asyncio
async def test_generate_and_save_write_error(engine, mock_llm):
  """Tests that a file system error during writing is propagated."""
  mock_llm.generate_content.return_value = '<html></html>'
  with patch('wptgen.engine.Path.write_text', side_effect=OSError('Disk Full')):
    with pytest.raises(OSError, match='Disk Full'):
      await engine._generate_and_save('prompt', 'error.html')


@pytest.mark.asyncio
async def test_phase_test_generation_duplicate_titles(engine, mocker):
  """Tests that multiple suggestions with identical titles now generate unique filenames."""
  context = {'metadata': MagicMock(name='Feat', description='Desc')}
  # Two suggestions with the same title
  suggestions_response = (
    '<test_suggestion><title>Same Title</title></test_suggestion>'
    '<test_suggestion><title>Same Title</title></test_suggestion>'
  )

  mocker.patch('wptgen.engine.Prompt.ask', return_value='y')
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
async def test_phase_test_generation_partial_failure(engine, mocker):
  """Tests that a failure in one parallel generation task does not stop others."""
  context = {'metadata': MagicMock(name='Feat', description='Desc')}
  suggestions_response = (
    '<test_suggestion><title>Success Test</title></test_suggestion>'
    '<test_suggestion><title>Fail Test</title></test_suggestion>'
  )

  mocker.patch('wptgen.engine.Prompt.ask', return_value='y')

  # Mock _generate_and_save to succeed for one and fail for another
  async def side_effect(prompt, filename):
    if 'fail_test' in filename:
      raise Exception('Random Write Error')
    return None

  mocker.patch.object(engine, '_generate_and_save', side_effect=side_effect)

  # We expect the exception to bubble up from asyncio.gather if not caught
  with pytest.raises(Exception, match='Random Write Error'):
    await engine._phase_test_generation(context, suggestions_response)


def test_extract_xml_tag_empty_content(engine):
  """Tests that _extract_xml_tag treats empty or whitespace-only tags as None/empty string."""
  assert engine._extract_xml_tag('<title></title>', 'title') == ''
  assert engine._extract_xml_tag('<title>   </title>', 'title') == ''


@pytest.mark.asyncio
async def test_phase_test_generation_unicode_stability(engine, mocker):
  """Verifies that titles with Unicode/Emoji are sanitized correctly and don't break generation."""
  context = {'metadata': MagicMock(name='Feat', description='Desc')}
  suggestions_response = '<test_suggestion><title>Test 🚀 & 中文</title></test_suggestion>'

  mocker.patch('wptgen.engine.Prompt.ask', return_value='y')
  mock_gen_save = mocker.patch.object(engine, '_generate_and_save', return_value=None)

  await engine._phase_test_generation(context, suggestions_response)

  mock_gen_save.assert_called_once()
  filename = mock_gen_save.call_args[0][1]
  assert filename.startswith('test_generated_01_')
  assert filename.endswith('.html')


@pytest.mark.asyncio
async def test_run_async_workflow_short_circuit(engine, mocker):
  """Verifies that the workflow stops immediately if context assembly fails."""
  mocker.patch.object(engine, '_phase_context_assembly', return_value=None)
  mock_analysis = mocker.patch.object(engine, '_phase_requirements_analysis')

  await engine._run_async_workflow('feat-id')

  engine._phase_context_assembly.assert_called_once()
  # Analysis should never be called if assembly fails
  mock_analysis.assert_not_called()


@pytest.mark.asyncio
async def test_phase_requirements_analysis_concurrent_failure(engine, mock_llm):
  """Verifies that the engine handles cases where both concurrent analysis tasks return empty strings."""
  context = {
    'metadata': MagicMock(specs=['http://spec']),
    'spec_contents': 'spec',
    'wpt_context': MagicMock(),
  }
  # Both LLM calls return empty (failure mode of _generate_safe)
  mock_llm.generate_content.side_effect = ['', '']

  result = await engine._phase_requirements_analysis('feat-id', context)
  assert result is None


@pytest.mark.asyncio
async def test_phase_context_assembly_empty_spec_list(engine, mocker):
  """Tests that context assembly handles cases where the spec list is empty in the metadata."""
  mocker.patch('wptgen.engine.fetch_feature_yaml', return_value={'name': 'feat'})
  # Metadata with empty specs list
  metadata = WebFeatureMetadata(name='Feature', description='Desc', specs=[])
  mocker.patch('wptgen.engine.extract_feature_metadata', return_value=metadata)

  result = await engine._phase_context_assembly('feat-id')
  assert result is None


@pytest.mark.asyncio
async def test_generate_and_save_whitespace_resilience(engine, mock_llm, tmp_path):
  """Tests that markdown stripping handles markdown blocks when they are at the start of a line."""
  # LLM output with markdown blocks at the start of the line (current engine requirement)
  mock_llm.generate_content.return_value = '\n```html\n<html></html>\n```\n'
  filename = tmp_path / 'whitespace.html'

  with patch('wptgen.engine.Path', return_value=filename):
    await engine._generate_and_save('prompt', 'whitespace.html')

  assert '<html></html>' in filename.read_text()
  assert '```html' not in filename.read_text()


@pytest.mark.asyncio
async def test_phase_test_generation_long_title(engine, mocker):
  """Tests that extremely long suggestion titles are handled by the sanitization logic."""
  context = {'metadata': MagicMock(name='Feat', description='Desc')}
  # Title longer than 255 chars
  long_title = 'A' * 300
  suggestions_response = f'<test_suggestion><title>{long_title}</title></test_suggestion>'

  mocker.patch('wptgen.engine.Prompt.ask', return_value='y')
  mock_gen_save = mocker.patch.object(engine, '_generate_and_save', return_value=None)

  await engine._phase_test_generation(context, suggestions_response)

  mock_gen_save.assert_called_once()
  filename = mock_gen_save.call_args[0][1]
  assert len(filename) > 300
  assert filename.startswith('test_generated_01_')


def test_run_workflow(engine, mocker):
  """Verifies that the synchronous run_workflow entry point correctly launches the async workflow."""
  mock_run = mocker.patch('asyncio.run')
  # Use standard MagicMock to avoid automatic AsyncMock wrapping
  from unittest.mock import MagicMock

  mock_async_workflow = MagicMock(return_value='dummy_coro')
  with patch.object(engine, '_run_async_workflow', mock_async_workflow):
    engine.run_workflow('feat-id')

  mock_run.assert_called_once_with('dummy_coro')
  mock_async_workflow.assert_called_once_with('feat-id')
