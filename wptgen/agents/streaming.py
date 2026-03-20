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

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from google.adk.events import Event

if TYPE_CHECKING:
  from wptgen.ui import UIProvider


class ADKStreamManager:
  """Manages the streaming of ADK events into the UI."""

  def __init__(self, ui: UIProvider, include_thoughts: bool = False):
    self.ui = ui
    self.include_thoughts = include_thoughts

  def __enter__(self) -> ADKStreamManager:
    return self

  def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
    pass

  def _format_tool_args(self, args: Any) -> str:
    """Formats tool call arguments for display, truncating large values."""
    if not args:
      return ''

    try:
      # Extract dictionary representation
      args_dict = None
      if hasattr(args, 'model_dump'):
        args_dict = args.model_dump()
      elif hasattr(args, 'items'):
        args_dict = args
      elif hasattr(args, '__dict__'):
        args_dict = vars(args)

      if not args_dict:
        # Fallback for simple values or un-parseable objects
        val_str = str(args)
        if len(val_str) > 100:
          val_str = val_str[:97] + '...'
        val_str = val_str.replace('[', '\\[').replace(']', '\\]')
        return f' [dim white]({val_str})[/dim white]'

      formatted_parts = []
      for k, v in args_dict.items():
        val_str = str(v)
        if len(val_str) > 100:
          val_str = val_str[:97] + '...'
        # Escape rich markup characters
        val_str = val_str.replace('[', '\\[').replace(']', '\\]')
        formatted_parts.append(f'{k}="{val_str}"')

      if formatted_parts:
        return ' [dim white](' + ', '.join(formatted_parts) + ')[/dim white]'

    except Exception:
      pass

    return ''

  def process_event(self, event: Event) -> None:
    """Takes an ADK Event object and streams its contents/actions to the UI.

    Args:
        event: The incoming ADK Event yielded by the Runner.
    """
    if not event.content or not event.content.parts:
      return

    for part in event.content.parts:
      is_thought = getattr(part, 'thought', False)

      if part.text:
        if is_thought:
          if self.include_thoughts:
            # Stream the agent's internal thought process directly to stdout in dim italic text
            self.ui.stream_text(part.text)
        else:
          # Regular text, print normally
          self.ui.stream_text(part.text)

      if part.function_call:
        tool_name = part.function_call.name
        args_str = self._format_tool_args(getattr(part.function_call, 'args', None))
        self.ui.print(
          f'\n[cyan]⚙️ WPT-Gen Agent calling tool:[/cyan] [bold]{tool_name}[/bold]{args_str}'
        )


def _format_tool_args(args: Any) -> str:
  """Formats tool call arguments for display, truncating large values."""
  if not args:
    return ''

  try:
    # Extract dictionary representation
    args_dict = None
    if hasattr(args, 'model_dump'):
      args_dict = args.model_dump()
    elif hasattr(args, 'items'):
      args_dict = args
    elif hasattr(args, '__dict__'):
      args_dict = vars(args)

    if not args_dict:
      # Fallback for simple values or un-parseable objects
      val_str = str(args)
      if len(val_str) > 100:
        val_str = val_str[:97] + '...'
      val_str = val_str.replace('[', '\\[').replace(']', '\\]')
      return f' [dim white]({val_str})[/dim white]'

    formatted_parts = []
    for k, v in args_dict.items():
      val_str = str(v)
      if len(val_str) > 100:
        val_str = val_str[:97] + '...'
      # Escape rich markup characters
      val_str = val_str.replace('[', '\\[').replace(']', '\\]')
      formatted_parts.append(f'{k}="{val_str}"')

    if formatted_parts:
      return ' [dim white](' + ', '.join(formatted_parts) + ')[/dim white]'

  except Exception:
    pass

  return ''


def stream_adk_event_to_ui(event: Event, ui: UIProvider) -> None:
  """Takes an ADK Event object and streams its contents/actions to the UIProvider.

  Args:
      event: The incoming ADK Event yielded by the Runner.
      ui: The WPT-Gen UIProvider instance for formatting output.
  """
  if event.content and event.content.parts:
    for part in event.content.parts:
      if part.text:
        # Print directly to standard output for streaming text
        # We use dim text for streaming agent thoughts/generation logs
        ui.stream_text(part.text)
      if part.function_call:
        # Log the tool execution gracefully
        tool_name = part.function_call.name
        args_str = _format_tool_args(getattr(part.function_call, 'args', None))

        # Render nicely instead of raw JSON
        ui.print(f'\n[cyan]⚙️ ADK Agent calling tool:[/cyan] [bold]{tool_name}[/bold]{args_str}')
