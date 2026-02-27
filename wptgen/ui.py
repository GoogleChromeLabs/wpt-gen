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

from contextlib import AbstractContextManager
from typing import Any, Protocol

from rich.console import Console, RenderableType
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Confirm
from rich.syntax import Syntax
from rich.table import Table


class UIProvider(Protocol):
  def print(self, message: Any = '', style: str | None = None) -> None: ...
  def rule(self, title: str = '', style: str = 'cyan') -> None: ...
  def status(self, message: str) -> AbstractContextManager[Any]: ...
  def confirm(self, question: str, default: bool = True) -> bool: ...
  def display_markdown(self, content: str) -> None: ...
  def display_panel(
    self, content: RenderableType | str, title: str | None = None, border_style: str = 'blue'
  ) -> None: ...
  def display_table(self, table: Table) -> None: ...
  def display_syntax(self, code: str, lexer: str, title: str) -> None: ...


class RichUIProvider:
  def __init__(self, console: Console | None = None):
    self.console = console or Console()

  def print(self, message: Any = '', style: str | None = None) -> None:
    self.console.print(message, style=style)

  def rule(self, title: str = '', style: str = 'cyan') -> None:
    self.console.print()
    self.console.rule(f'[bold {style}]{title}')
    self.console.print()

  def status(self, message: str) -> AbstractContextManager[Any]:
    return self.console.status(message)

  def confirm(self, question: str, default: bool = True) -> bool:
    return Confirm.ask(question, default=default)

  def display_markdown(self, content: str) -> None:
    self.console.print(Markdown(content))

  def display_panel(
    self, content: RenderableType | str, title: str | None = None, border_style: str = 'blue'
  ) -> None:
    self.console.print(
      Panel(
        content,
        title=f'[bold]{title}[/bold]' if title else None,
        border_style=border_style,
        expand=False,
      )
    )

  def display_table(self, table: Table) -> None:
    self.console.print(table)

  def display_syntax(self, code: str, lexer: str, title: str) -> None:
    syntax = Syntax(code, lexer, theme='monokai', line_numbers=True, word_wrap=True)
    self.display_panel(syntax, title=f'LLM Response: {title}', border_style='cyan')
