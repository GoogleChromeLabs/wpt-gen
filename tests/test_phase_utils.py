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
from unittest.mock import MagicMock

import pytest
import typer

from wptgen.config import Config
from wptgen.phases.utils import confirm_prompts, generate_safe


@pytest.fixture
def mock_ui() -> MagicMock:
  """Fixture that provides a mocked UI provider with a status context manager."""
  ui = MagicMock()
  ui.status.return_value.__enter__.return_value = None
  return ui


@pytest.fixture
def mock_llm() -> MagicMock:
  """Fixture that provides a mocked LLM client."""
  llm = MagicMock()
  llm.model = 'test-model'
  llm.count_tokens.return_value = 100
  llm.prompt_exceeds_input_token_limit.return_value = False
  llm.generate_content.return_value = 'response'
  return llm


@pytest.fixture
def mock_config(tmp_path: Path) -> Config:
  """Fixture that provides a basic test configuration."""
  return Config(
    provider='test',
    default_model='test-model',
    api_key='key',
    categories={'reasoning': 'test-model', 'lightweight': 'test-model'},
    phase_model_mapping={
      'requirements_extraction': 'reasoning',
      'coverage_audit': 'reasoning',
      'generation': 'lightweight',
      'evaluation': 'lightweight',
    },
    wpt_path=str(tmp_path / 'wpt'),
    cache_path=str(tmp_path / 'cache'),
    output_dir=str(tmp_path / 'output'),
    yes_tokens=False,
    show_responses=False,
  )


@pytest.mark.asyncio
async def test_confirm_prompts_multiple(
  mock_ui: MagicMock, mock_llm: MagicMock, mock_config: Config
) -> None:
  """Test that confirm_prompts correctly displays estimated token usage."""
  prompt_data = [('p1', 'n1'), ('p2', 'n2')]
  mock_ui.confirm.return_value = True
  await confirm_prompts(prompt_data, 'Phase', mock_llm, mock_ui, mock_config)
  mock_ui.print.assert_any_call('[bold]Total Estimated Tokens:[/bold] [cyan]200[/cyan]')


@pytest.mark.asyncio
async def test_confirm_prompts_limit_exceeded(
  mock_ui: MagicMock, mock_llm: MagicMock, mock_config: Config
) -> None:
  """Test that confirm_prompts warns when a prompt exceeds the token limit."""
  mock_llm.prompt_exceeds_input_token_limit.return_value = True
  mock_ui.confirm.return_value = True
  await confirm_prompts([('p1', 'n1')], 'Phase', mock_llm, mock_ui, mock_config)
  mock_ui.print.assert_any_call(
    '\n[bold red]Warning:[/bold red] One or more prompts exceed the model context limit!'
  )


@pytest.mark.asyncio
async def test_confirm_prompts_yes_tokens(
  mock_ui: MagicMock, mock_llm: MagicMock, mock_config: Config
) -> None:
  """Test that confirm_prompts auto-confirms when yes_tokens is set."""
  mock_config.yes_tokens = True
  await confirm_prompts([('p1', 'n1')], 'Phase', mock_llm, mock_ui, mock_config)
  mock_ui.print.assert_any_call('\n[yellow]Auto-confirming token usage (--yes-tokens).[/yellow]')
  mock_ui.confirm.assert_not_called()


@pytest.mark.asyncio
async def test_confirm_prompts_abort(
  mock_ui: MagicMock, mock_llm: MagicMock, mock_config: Config
) -> None:
  """Test that confirm_prompts aborts the workflow when the user cancels."""
  mock_ui.confirm.return_value = False
  with pytest.raises(typer.Abort):
    await confirm_prompts([('p1', 'n1')], 'Phase', mock_llm, mock_ui, mock_config)
  mock_ui.print.assert_any_call('[yellow]Aborting workflow due to user cancellation.[/yellow]')


@pytest.mark.asyncio
async def test_generate_safe_show_responses_xml(
  mock_ui: MagicMock, mock_llm: MagicMock, mock_config: Config
) -> None:
  """Test that generate_safe displays response as XML when configured."""
  mock_config.show_responses = True
  res = await generate_safe('prompt', 'Task', mock_llm, mock_ui, mock_config)
  assert res == 'response'
  mock_ui.display_syntax.assert_called_once_with('response', 'xml', 'Task')


@pytest.mark.asyncio
async def test_generate_safe_show_responses_html(
  mock_ui: MagicMock, mock_llm: MagicMock, mock_config: Config
) -> None:
  """Test that generate_safe displays response as HTML for generation tasks."""
  mock_config.show_responses = True
  await generate_safe('prompt', 'gen: test', mock_llm, mock_ui, mock_config)
  mock_ui.display_syntax.assert_called_once_with('response', 'html', 'gen: test')


@pytest.mark.asyncio
async def test_generate_safe_exception(
  mock_ui: MagicMock, mock_llm: MagicMock, mock_config: Config
) -> None:
  """Test that generate_safe handles exceptions gracefully and returns an empty string."""
  mock_llm.generate_content.side_effect = Exception('test error')
  res = await generate_safe('prompt', 'Task', mock_llm, mock_ui, mock_config)
  assert res == ''
  mock_ui.print.assert_any_call('[bold red]✘ Task failed (test-model):[/bold red] test error')
