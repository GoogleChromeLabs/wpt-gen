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

from unittest.mock import MagicMock, patch

import pytest
from rich.table import Table

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


def test_rule(ui: RichUIProvider, mock_console: MagicMock) -> None:
  """Test that the rule method correctly delegates to the rich console."""
  ui.rule('test title', style='green')
  assert mock_console.print.call_count == 2
  mock_console.rule.assert_called_once_with('[bold green]test title')


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


def test_display_markdown(ui: RichUIProvider, mock_console: MagicMock) -> None:
  """Test that display_markdown correctly renders markdown content."""
  ui.display_markdown('# Hello')
  mock_console.print.assert_called_once()
  args, _ = mock_console.print.call_args
  assert args[0].markup == '# Hello'


def test_display_panel(ui: RichUIProvider, mock_console: MagicMock) -> None:
  """Test that display_panel correctly renders a rich panel."""
  ui.display_panel('panel content', title='Panel Title', border_style='red')
  mock_console.print.assert_called_once()
  args, _ = mock_console.print.call_args
  panel = args[0]
  assert panel.renderable == 'panel content'
  assert panel.title == '[bold]Panel Title[/bold]'
  assert panel.border_style == 'red'


def test_display_table(ui: RichUIProvider, mock_console: MagicMock) -> None:
  """Test that display_table correctly renders a rich table."""
  table = Table()
  ui.display_table(table)
  mock_console.print.assert_called_once_with(table)


def test_display_syntax(ui: RichUIProvider, mock_console: MagicMock) -> None:
  """Test that display_syntax correctly renders syntax-highlighted code in a panel."""
  with patch.object(ui, 'display_panel') as mock_display_panel:
    ui.display_syntax("print('hi')", 'python', 'Test Syntax')
    mock_display_panel.assert_called_once()
    args, kwargs = mock_display_panel.call_args
    assert kwargs['title'] == 'LLM Response: Test Syntax'
    assert kwargs['border_style'] == 'cyan'
