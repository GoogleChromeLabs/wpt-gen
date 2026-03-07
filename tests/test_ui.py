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

from wptgen.models import WebFeatureMetadata
from wptgen.ui import RichUIProvider


@pytest.fixture
def mock_console() -> MagicMock:
  """Fixture that provides a mocked rich console."""
  return MagicMock()


@pytest.fixture
def ui(mock_console: MagicMock) -> RichUIProvider:
  """Fixture that provides a RichUIProvider initialized with a mocked console."""
  return RichUIProvider(console=mock_console)


def test_print(ui: RichUIProvider, mock_console: MagicMock) -> None:
  """Test that the print method correctly delegates to the rich console."""
  ui.print('test message', style='bold red')
  mock_console.print.assert_called_once_with('test message', style='bold red')


def test_status(ui: RichUIProvider, mock_console: MagicMock) -> None:
  """Test that the status method correctly delegates to the rich console."""
  ui.status('loading...')
  mock_console.status.assert_called_once_with('loading...')


@patch('wptgen.ui.Confirm.ask')
def test_confirm(mock_ask: MagicMock, ui: RichUIProvider) -> None:
  """Test that the confirm method correctly uses rich.prompt.Confirm.ask."""
  mock_ask.return_value = True
  result = ui.confirm('Are you sure?')
  assert result is True
  mock_ask.assert_called_once_with('Are you sure?', default=True)


def test_info(ui: RichUIProvider, mock_console: MagicMock) -> None:
  """Test the info semantic method."""
  ui.info('info message')
  mock_console.print.assert_called_once_with('[blue]ℹ[/blue] info message')


def test_success(ui: RichUIProvider, mock_console: MagicMock) -> None:
  """Test the success semantic method."""
  ui.success('success message')
  mock_console.print.assert_called_once_with('[bold green]✔[/bold green] success message')


def test_warning(ui: RichUIProvider, mock_console: MagicMock) -> None:
  """Test the warning semantic method."""
  ui.warning('warning message')
  mock_console.print.assert_called_once_with('[yellow]⚠[/yellow] warning message')


def test_error(ui: RichUIProvider, mock_console: MagicMock) -> None:
  """Test the error semantic method."""
  ui.error('error message')
  mock_console.print.assert_called_once_with('[bold red]✘[/bold red] error message')


def test_on_phase_start(ui: RichUIProvider, mock_console: MagicMock) -> None:
  """Test on_phase_start semantic method."""
  ui.on_phase_start(1, 'Test Phase')
  mock_console.rule.assert_called_once_with('[bold cyan]Phase 1: Test Phase')


def test_report_metadata(ui: RichUIProvider, mock_console: MagicMock) -> None:
  """Test report_metadata semantic method."""
  metadata = WebFeatureMetadata('Feat', 'Desc', ['http://spec'])
  ui.report_metadata(metadata)
  mock_console.print.assert_called_once()
  args, _ = mock_console.print.call_args
  panel = args[0]
  assert panel.title == '[bold]Feature Metadata[/bold]'


def test_report_token_usage(ui: RichUIProvider, mock_console: MagicMock) -> None:
  """Test report_token_usage semantic method."""
  ui.report_token_usage('Phase', 'Model', [(100, False, 'Task')], 100)
  mock_console.print.assert_called_once()


def test_report_llm_response(ui: RichUIProvider, mock_console: MagicMock) -> None:
  """Test report_llm_response semantic method."""
  ui.report_llm_response('response', 'Task')
  mock_console.print.assert_called_once()


def test_report_coverage_audit(ui: RichUIProvider, mock_console: MagicMock) -> None:
  """Test report_coverage_audit semantic method."""
  ui.report_coverage_audit('audit response')
  # Rule + Print
  assert mock_console.rule.call_count == 1


def test_report_audit_worksheet(ui: RichUIProvider, mock_console: MagicMock) -> None:
  """Test report_audit_worksheet semantic method."""
  ui.report_audit_worksheet('R1: Req -> [UNCOVERED]')
  # Table + Print newline
  assert mock_console.print.call_count == 2


def test_report_test_suggestion(ui: RichUIProvider, mock_console: MagicMock) -> None:
  """Test report_test_suggestion semantic method."""
  ui.report_test_suggestion(1, 'Title', 'Desc', 'Type')
  mock_console.print.assert_called_once()


def test_report_generation_summary(ui: RichUIProvider, mock_console: MagicMock) -> None:
  """Test report_generation_summary semantic method."""
  ui.report_generation_summary([(Path('p'), 'c', 's')])
  # Newline + Table + Success message
  assert mock_console.print.call_count == 3


def test_report_evaluation_result(ui: RichUIProvider, mock_console: MagicMock) -> None:
  """Test report_evaluation_result semantic method."""
  ui.report_evaluation_result('test.html', success=True)
  mock_console.print.assert_called_once_with('[green]✔ test.html passed evaluation.[/green]')


@patch('wptgen.ui.Progress')
def test_progress_indicator(mock_progress_class: MagicMock, ui: RichUIProvider) -> None:
  """Test that progress_indicator correctly uses rich.progress.Progress."""
  mock_progress = mock_progress_class.return_value.__enter__.return_value
  mock_progress.add_task.return_value = 'task_1'

  with ui.progress_indicator('Testing...', total=10) as indicator:
    indicator.advance(2)
    indicator.update(description='Updated', outstanding=8)

  mock_progress_class.assert_called_once()
  mock_progress.add_task.assert_called_once_with('Testing...', total=10)
  mock_progress.advance.assert_called_once_with('task_1', advance=2)
  mock_progress.update.assert_called_once_with('task_1', description='Updated (8 outstanding)')
