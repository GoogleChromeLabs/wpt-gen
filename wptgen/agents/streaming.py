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

from google.adk.events import Event

from wptgen.ui import UIProvider


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

        # Render nicely instead of raw JSON
        ui.print(f'\n[cyan]⚙️ ADK Agent calling tool:[/cyan] [bold]{tool_name}[/bold]')
