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
from wptgen.models import WorkflowContext
from wptgen.phases.evaluation import run_test_evaluation


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
    categories={'lightweight': 'test-model', 'reasoning': 'test-model'},
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
  llm.generate_content.return_value = 'PASS'
  llm.model = 'mock-model'
  return llm


@pytest.mark.asyncio
async def test_run_test_evaluation_pass(
  mock_config: Config, mock_ui: MagicMock, mock_llm: MagicMock, tmp_path: Path
) -> None:
  context = WorkflowContext(feature_id='feat')
  jinja_env = MagicMock()

  # Mock style guide and templates
  style_guide_content = 'Style Guide Content'

  test_path = tmp_path / 'test.html'
  test_path.write_text('original content')
  generated_tests = [(test_path, 'original content', '<suggestion></suggestion>')]

  # Targeted patch for the read_text call inside run_test_evaluation
  with patch('wptgen.phases.evaluation.Path.read_text', return_value=style_guide_content):
    await run_test_evaluation(context, mock_config, mock_llm, mock_ui, jinja_env, generated_tests)

  assert test_path.read_text() == 'original content'
  mock_ui.report_evaluation_result.assert_any_call(test_path.name, success=True)


@pytest.mark.asyncio
async def test_run_test_evaluation_correction(
  mock_config: Config, mock_ui: MagicMock, mock_llm: MagicMock, tmp_path: Path
) -> None:
  context = WorkflowContext(feature_id='feat')
  jinja_env = MagicMock()

  # Mock style guide and templates
  style_guide_content = 'Style Guide Content'

  test_path = tmp_path / 'test.html'
  test_path.write_text('original content')
  generated_tests = [(test_path, 'original content', '<suggestion></suggestion>')]

  # Mock LLM returning corrected content
  mock_llm.generate_content.return_value = 'corrected content'

  with patch('wptgen.phases.evaluation.Path.read_text', return_value=style_guide_content):
    await run_test_evaluation(context, mock_config, mock_llm, mock_ui, jinja_env, generated_tests)

  assert test_path.read_text() == 'corrected content'
  mock_ui.report_evaluation_result.assert_any_call(test_path.name, success=True, updated=True)


@pytest.mark.asyncio
async def test_run_test_evaluation_with_markdown(
  mock_config: Config, mock_ui: MagicMock, mock_llm: MagicMock, tmp_path: Path
) -> None:
  context = WorkflowContext(feature_id='feat')
  jinja_env = MagicMock()
  style_guide_content = 'Style Guide Content'
  test_path = tmp_path / 'test_markdown.html'
  test_path.write_text('original content')
  generated_tests = [(test_path, 'original content', '<suggestion></suggestion>')]

  # Mock LLM returning content wrapped in markdown blocks
  mock_llm.generate_content.return_value = '```html\ncorrected markdown content\n```'

  with patch('wptgen.phases.evaluation.Path.read_text', return_value=style_guide_content):
    await run_test_evaluation(context, mock_config, mock_llm, mock_ui, jinja_env, generated_tests)

  assert test_path.read_text() == 'corrected markdown content'
  mock_ui.report_evaluation_result.assert_any_call(test_path.name, success=True, updated=True)


@pytest.mark.asyncio
async def test_run_test_evaluation_no_response(
  mock_config: Config, mock_ui: MagicMock, mock_llm: MagicMock, tmp_path: Path
) -> None:
  context = WorkflowContext(feature_id='feat')
  jinja_env = MagicMock()
  test_path = tmp_path / 'test.html'
  test_path.write_text('original content')
  generated_tests = [(test_path, 'original content', '<suggestion></suggestion>')]

  # Mock LLM returning empty response (via generate_safe failing)
  with patch('wptgen.phases.evaluation.generate_safe', return_value=''):
    with patch('wptgen.phases.evaluation.Path.read_text', return_value='Style Guide'):
      await run_test_evaluation(context, mock_config, mock_llm, mock_ui, jinja_env, generated_tests)

  assert test_path.read_text() == 'original content'
  mock_ui.report_evaluation_result.assert_called_with(
    test_path.name, success=False, message=f'No response for evaluation of {test_path.name}.'
  )


@pytest.mark.asyncio
async def test_run_test_evaluation_reftest_correction(
  mock_config: Config, mock_ui: MagicMock, mock_llm: MagicMock, tmp_path: Path
) -> None:
  context = WorkflowContext(feature_id='feat')
  jinja_env = MagicMock()

  # Mock style guide and templates
  style_guide_content = 'Style Guide Content'

  test_path = tmp_path / 'test.html'
  ref_path = tmp_path / 'test-ref.html'
  test_path.write_text('original test content')
  ref_path.write_text('original ref content')

  suggestion_xml = '<test_suggestion><test_type>Reftest</test_type></test_suggestion>'
  generated_tests = [
    (test_path, 'original test content', suggestion_xml),
    (ref_path, 'original ref content', suggestion_xml),
  ]

  # Mock LLM returning corrected content for BOTH files using suffixes
  mock_llm.generate_content.return_value = """
[FILE_1: .html]
corrected test content
[/FILE_1]

[FILE_2: .html]
corrected ref content
[/FILE_2]
"""

  with patch('wptgen.phases.evaluation.Path.read_text', return_value=style_guide_content):
    await run_test_evaluation(context, mock_config, mock_llm, mock_ui, jinja_env, generated_tests)

  assert test_path.read_text() == 'corrected test content'
  assert ref_path.read_text() == 'corrected ref content'
  mock_ui.report_evaluation_result.assert_any_call('test.html', success=True, updated=True)
  mock_ui.report_evaluation_result.assert_any_call('test-ref.html', success=True, updated=True)


@pytest.mark.asyncio
async def test_run_test_evaluation_partitioning_logic(
  mock_config: Config, mock_ui: MagicMock, mock_llm: MagicMock, tmp_path: Path
) -> None:
  """Verify evaluation prompt formatting for reftests vs non-reftests."""
  jinja_env = MagicMock()
  eval_template_mock = MagicMock()
  system_template_mock = MagicMock()

  def get_template(name: str) -> MagicMock:
    if name == 'evaluation.jinja':
      return eval_template_mock
    if name == 'evaluation_system.jinja':
      return system_template_mock
    return MagicMock()

  jinja_env.get_template.side_effect = get_template

  # 1. Non-Reftest (Single File)
  js_test_path = tmp_path / 'feat-001.html'
  js_test_path.write_text('js content')

  generated_tests = [
    (
      js_test_path,
      'js content',
      '<test_suggestion><test_type>JavaScript Test</test_type></test_suggestion>',
    )
  ]

  context = WorkflowContext(feature_id='feat')

  with patch('wptgen.phases.evaluation.Path.read_text', return_value='Guide'):
    with patch('wptgen.phases.evaluation.generate_safe', return_value='PASS'):
      await run_test_evaluation(context, mock_config, mock_llm, mock_ui, jinja_env, generated_tests)

  # Check eval prompt for non-reftest: should be raw content (no tags)
  call_args = eval_template_mock.render.call_args.kwargs
  assert call_args['generated_code_content'] == 'js content'

  eval_template_mock.render.reset_mock()

  # 2. Reftest (Multi File)
  ref_test_path = tmp_path / 'feat-002.html'
  ref_test_path.write_text('test content')
  ref_ref_path = tmp_path / 'feat-002-ref.html'
  ref_ref_path.write_text('ref content')

  suggestion_xml = '<test_suggestion><test_type>Reftest</test_type></test_suggestion>'
  generated_reftests = [
    (ref_test_path, 'test content', suggestion_xml),
    (ref_ref_path, 'ref content', suggestion_xml),
  ]

  with patch('wptgen.phases.evaluation.Path.read_text', return_value='Guide'):
    with patch('wptgen.phases.evaluation.generate_safe', return_value='PASS'):
      await run_test_evaluation(
        context, mock_config, mock_llm, mock_ui, jinja_env, generated_reftests
      )

  # Check eval prompt for reftest: should have tags with suffixes
  call_args = eval_template_mock.render.call_args.kwargs
  assert '[FILE_1: .html]' in call_args['generated_code_content']
  assert 'test content' in call_args['generated_code_content']
  assert '[FILE_2: .html]' in call_args['generated_code_content']
  assert 'ref content' in call_args['generated_code_content']
