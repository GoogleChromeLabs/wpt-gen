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

from unittest.mock import MagicMock

import pytest
from google.adk.events import Event
from google.genai import types

from wptgen.agents.streaming import ADKStreamManager


def test_adk_stream_manager_text(capsys: pytest.CaptureFixture[str]) -> None:
  """Test streaming text to stdout."""
  ui_mock = MagicMock()
  part = types.Part(text='Thinking...')
  event = Event(author='agent', content=types.Content(parts=[part]))

  with ADKStreamManager(ui_mock) as manager:
    manager.process_event(event)

  ui_mock.stream_text.assert_called_once_with('Thinking...')
  ui_mock.print.assert_not_called()


def test_adk_stream_manager_thought() -> None:
  """Test streaming thought to ui."""
  ui_mock = MagicMock()
  part = types.Part(text='Pondering deeply...', thought=True)
  event = Event(author='agent', content=types.Content(parts=[part]))

  with ADKStreamManager(ui_mock) as manager:
    manager.process_event(event)

  ui_mock.stream_text.assert_called_once_with('Pondering deeply...')
  ui_mock.print.assert_not_called()


def test_adk_stream_manager_function_call() -> None:
  """Test streaming function calls stops the box and prints."""
  ui_mock = MagicMock()
  part = types.Part(function_call=types.FunctionCall(name='run_wpt_test'))
  event = Event(author='agent', content=types.Content(parts=[part]))

  with ADKStreamManager(ui_mock) as manager:
    manager.process_event(event)

  ui_mock.print.assert_called_once_with(
    '\n[cyan]⚙️ WPT-Gen Agent calling tool:[/cyan] [bold]run_wpt_test[/bold]'
  )


def test_adk_stream_manager_empty_event() -> None:
  """Test handling of empty events."""
  ui_mock = MagicMock()
  event = Event(author='agent', content=types.Content(parts=[]))

  with ADKStreamManager(ui_mock) as manager:
    manager.process_event(event)

  ui_mock.stream_text.assert_not_called()
  ui_mock.print.assert_not_called()
