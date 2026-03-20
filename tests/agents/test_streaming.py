from unittest.mock import MagicMock

from google.adk.events import Event
from google.genai import types

from wptgen.agents.streaming import stream_adk_event_to_ui


def test_stream_adk_event_to_ui_text() -> None:
  """Test streaming text to stdout."""
  ui_mock = MagicMock()
  # Create an event with text content
  part = types.Part(text='Thinking...')
  event = Event(author='agent', content=types.Content(parts=[part]))

  stream_adk_event_to_ui(event, ui_mock)

  ui_mock.stream_text.assert_called_once_with('Thinking...')
  ui_mock.print.assert_not_called()


def test_stream_adk_event_to_ui_function_call() -> None:
  """Test streaming function calls to UI provider."""
  ui_mock = MagicMock()
  # Create an event with a function call
  part = types.Part(function_call=types.FunctionCall(name='run_wpt_test'))
  event = Event(author='agent', content=types.Content(parts=[part]))

  stream_adk_event_to_ui(event, ui_mock)

  ui_mock.print.assert_called_once_with(
    '\n[cyan]⚙️ ADK Agent calling tool:[/cyan] [bold]run_wpt_test[/bold]'
  )


def test_stream_adk_event_to_ui_empty_event() -> None:
  """Test handling of empty events."""
  ui_mock = MagicMock()
  event = Event(author='agent', content=types.Content(parts=[]))

  stream_adk_event_to_ui(event, ui_mock)

  ui_mock.stream_text.assert_not_called()
  ui_mock.print.assert_not_called()
