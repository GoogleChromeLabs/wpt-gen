"""Module docstring."""
# pylint: disable=redefined-outer-name
# pylint: disable=unused-argument
# pylint: disable=import-outside-toplevel
# pylint: disable=reimported
# pylint: disable=protected-access
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
from rich.panel import Panel
from rich.table import Table

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

    with ADKStreamManager(ui_mock, include_thoughts=True) as manager:
        manager.process_event(event)

    ui_mock.stream_text.assert_called_once_with('Pondering deeply...')
    ui_mock.print.assert_not_called()


def test_adk_stream_manager_function_call() -> None:
    """Test streaming function calls stops the box and prints with formatted arguments."""  # pylint: disable=line-too-long
    ui_mock = MagicMock()
    args = {
        'test_path':
            '/html/semantics/scripting-1/the-script-element/script-type-module.html'  # pylint: disable=line-too-long
    }
    part = types.Part(
        function_call=types.FunctionCall(name='run_wpt_test', args=args))
    event = Event(author='agent', content=types.Content(parts=[part]))

    with ADKStreamManager(ui_mock) as manager:
        manager.process_event(event)

    assert ui_mock.print.call_count == 2
    panel = ui_mock.print.call_args_list[1][0][0]
    assert isinstance(panel, Panel)
    assert 'run_wpt_test' in str(panel.title)


def test_adk_stream_manager_function_call_args_truncation() -> None:
    """Test that extremely large arguments are gracefully truncated."""
    ui_mock = MagicMock()
    long_content = 'A' * 1000
    args = {'content': long_content}
    part = types.Part(
        function_call=types.FunctionCall(name='write_file', args=args))
    event = Event(author='agent', content=types.Content(parts=[part]))

    with ADKStreamManager(ui_mock) as manager:
        manager.process_event(event)

    assert ui_mock.print.call_count == 2
    panel = ui_mock.print.call_args_list[1][0][0]
    assert isinstance(panel, Panel)
    assert 'write_file' in str(panel.title)
    assert isinstance(panel.renderable, Table)


def test_adk_stream_manager_empty_event() -> None:
    """Test handling of empty events."""
    ui_mock = MagicMock()
    event = Event(author='agent', content=types.Content(parts=[]))

    with ADKStreamManager(ui_mock) as manager:
        manager.process_event(event)

    ui_mock.stream_text.assert_not_called()
    ui_mock.print.assert_not_called()
