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
  mock_ui.print.assert_any_call(f'[green]✔ {test_path.name} passed evaluation.[/green]')


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
  mock_ui.print.assert_any_call(f'[cyan]ℹ {test_path.name} was corrected and updated.[/cyan]')


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
  mock_ui.print.assert_any_call(f'[cyan]ℹ {test_path.name} was corrected and updated.[/cyan]')


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
  mock_ui.print.assert_any_call(
    f'[yellow]⚠ No response for evaluation of {test_path.name}. Keeping original.[/yellow]'
  )
