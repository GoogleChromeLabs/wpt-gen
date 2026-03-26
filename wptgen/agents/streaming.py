"""Module docstring."""

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
from rich.panel import Panel
from rich.table import Table

if TYPE_CHECKING:
    from wptgen.ui import UIProvider


def format_tool_call(
    tool_name: str, args: Any, agent_name: str = "WPT-Gen Agent"
) -> Panel:
    """Formats a tool call and its arguments into a visually appealing Panel."""
    args_dict = None

    if args:
        try:
            if hasattr(args, "model_dump"):
                args_dict = args.model_dump()
            elif hasattr(args, "items"):
                args_dict = args
            elif hasattr(args, "__dict__"):
                args_dict = vars(args)
        except Exception:  # pylint: disable=broad-exception-caught
            pass

    content_renderable: str | Table
    if args_dict is not None and len(args_dict) == 0:
        # Valid dict, but empty
        content_renderable = "[dim italic]No arguments[/dim italic]"
    elif not args_dict:
        # If there are no extractable arguments, or None
        val_str = str(args) if args else "[dim italic]No arguments[/dim italic]"
        if args and not isinstance(args, str) and len(val_str) > 100:
            val_str = val_str[:97] + "..."
        if args:
            val_str = val_str.replace("[", "\\[").replace("]", "\\]")
        content_renderable = val_str
    else:
        table = Table(
            show_header=False, box=None, padding=(0, 1), collapse_padding=True
        )
        table.add_column(
            "Argument", style="cyan", justify="right", vertical="top"
        )
        table.add_column("Value", style="dim white", overflow="fold")

        # Define an intuitive ordering for common tool arguments
        priority_keys = [
            "command",
            "name",
            "dir_path",
            "file_path",
            "path",
            "filename",
            "test_path",
            "pattern",
            "start_line",
            "end_line",
            "content",
            "instruction",
            "old_string",
            "new_string",
        ]

        def get_sort_key(key: str) -> tuple[int, int, str]:
            try:
                idx = priority_keys.index(key)
                return (0, idx, key)
            except ValueError:
                return (1, 0, key)

        sorted_args = sorted(
            args_dict.items(), key=lambda item: get_sort_key(item[0])
        )

        for k, v in sorted_args:
            val_str = str(v)
            if len(val_str) > 500:
                val_str = val_str[:497] + "..."
            # Escape rich markup characters
            val_str = val_str.replace("[", "\\[").replace("]", "\\]")
            table.add_row(f"{k}:", val_str)
        content_renderable = table

    return Panel(
        content_renderable,
        title=f"[cyan]{agent_name} calling tool:[/cyan] [bold white]{tool_name}[/bold white]",  # pylint: disable=line-too-long
        title_align="left",
        border_style="cyan",
        padding=(0, 1),
    )


class ADKStreamManager:
    """Manages the streaming of ADK events into the UI."""

    def __init__(self, ui: UIProvider, include_thoughts: bool = False):
        self.ui = ui
        self.include_thoughts = include_thoughts

    def __enter__(self) -> ADKStreamManager:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        pass

    def process_event(self, event: Event) -> None:
        """Takes an ADK Event object and streams its contents/actions to the UI.

        Args:
            event: The incoming ADK Event yielded by the Runner.
        """
        if not event.content or not event.content.parts:
            return

        for part in event.content.parts:
            is_thought = getattr(part, "thought", False)

            if part.text:
                if is_thought:
                    if self.include_thoughts:
                        # Stream the agent's internal thought process directly
                        # to stdout in dim italic text
                        self.ui.stream_text(part.text)
                else:
                    # Regular text, print normally
                    self.ui.stream_text(part.text)

            if part.function_call:
                tool_name = part.function_call.name or "unknown"
                panel = format_tool_call(
                    tool_name,
                    getattr(part.function_call, "args", None),
                    "WPT-Gen Agent",
                )
                self.ui.print()
                self.ui.print(panel)
