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

import re
from contextlib import AbstractContextManager
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Confirm
from rich.syntax import Syntax
from rich.table import Table

if TYPE_CHECKING:
  from wptgen.models import WebFeatureMetadata


class UIProvider(Protocol):
  """Semantic UI interface for the WPT generation workflow."""

  # Core interaction
  def status(self, message: str) -> AbstractContextManager[Any]: ...
  def confirm(self, question: str, default: bool = True) -> bool: ...

  # Generic semantic messaging
  def print(self, message: Any = '', style: str | None = None) -> None: ...
  def info(self, message: str) -> None: ...
  def success(self, message: str) -> None: ...
  def warning(self, message: str) -> None: ...
  def error(self, message: str) -> None: ...

  # Phase and lifecycle events
  def on_phase_start(self, phase_num: int, phase_name: str) -> None: ...
  def on_phase_complete(self, phase_name: str) -> None: ...

  # Domain-specific reporting
  def report_metadata(self, metadata: WebFeatureMetadata) -> None: ...
  def report_context_summary(
    self, spec_len: int, mdn_count: int, test_count: int, dep_count: int
  ) -> None: ...
  def report_token_usage(
    self,
    phase_name: str,
    model: str,
    results: list[tuple[int, bool, str]],
    total_tokens: int,
    auto_confirmed: bool = False,
  ) -> None: ...
  def report_llm_response(self, response: str, task_name: str) -> None: ...
  def report_coverage_audit(self, audit_response: str) -> None: ...
  def report_audit_worksheet(self, worksheet_text: str) -> None: ...
  def report_test_suggestion(
    self, suggestion_index: int, title: str, description: str, test_type: str
  ) -> None: ...
  def report_generation_start(self, count: int) -> None: ...
  def report_test_generated(
    self, root_name: str, success: bool, path: Path | None = None, fallback: bool = False
  ) -> None: ...
  def report_generation_summary(self, generated_tests: list[tuple[Path, str, str]]) -> None: ...
  def report_evaluation_start(self, count: int) -> None: ...
  def report_evaluation_result(
    self, display_names: str, success: bool, updated: bool = False, message: str | None = None
  ) -> None: ...


class RichUIProvider:
  """Rich-based implementation of the UIProvider protocol."""

  def __init__(self, console: Console | None = None):
    self.console = console or Console()

  def status(self, message: str) -> AbstractContextManager[Any]:
    return self.console.status(message)

  def confirm(self, question: str, default: bool = True) -> bool:
    return Confirm.ask(question, default=default)

  def print(self, message: Any = '', style: str | None = None) -> None:
    self.console.print(message, style=style)

  def info(self, message: str) -> None:
    self.console.print(f'[blue]ℹ[/blue] {message}')

  def success(self, message: str) -> None:
    self.console.print(f'[bold green]✔[/bold green] {message}')

  def warning(self, message: str) -> None:
    self.console.print(f'[yellow]⚠[/yellow] {message}')

  def error(self, message: str) -> None:
    self.console.print(f'[bold red]✘[/bold red] {message}')

  def on_phase_start(self, phase_num: int, phase_name: str) -> None:
    self.console.print()
    self.console.rule(f'[bold cyan]Phase {phase_num}: {phase_name}')
    self.console.print()

  def on_phase_complete(self, phase_name: str) -> None:
    self.success(f'{phase_name} complete.')

  def report_metadata(self, metadata: WebFeatureMetadata) -> None:
    metadata_table = Table(show_header=False, box=None, padding=(0, 2))
    metadata_table.add_row('[bold]Web Feature Name:[/bold]', f'[cyan]{metadata.name}[/cyan]')
    metadata_table.add_row('[bold]Description:[/bold]', metadata.description)
    metadata_table.add_row('[bold]Spec URL:[/bold]', f'[blue]{metadata.specs[0]}[/blue]')

    self.console.print(
      Panel(
        metadata_table,
        title='[bold]Feature Metadata[/bold]',
        border_style='blue',
        expand=False,
      )
    )

  def report_context_summary(
    self, spec_len: int, mdn_count: int, test_count: int, dep_count: int
  ) -> None:
    self.success(
      f'Context gathered: {spec_len} chars of spec, '
      f'{mdn_count} MDN pages, '
      f'{test_count} tests, '
      f'{dep_count} dependency files.'
    )

  def report_token_usage(
    self,
    phase_name: str,
    model: str,
    results: list[tuple[int, bool, str]],
    total_tokens: int,
    auto_confirmed: bool = False,
  ) -> None:
    table = Table(
      title=f'Token Usage Summary ({phase_name})', show_header=True, header_style='bold magenta'
    )
    table.add_column('Task', style='dim')
    table.add_column('Model', style='blue')
    table.add_column('Tokens', justify='right', style='cyan')
    table.add_column('Status', justify='center')

    for tokens, limit_exceeded, name in results:
      status = '[bold red]EXCEEDED[/bold red]' if limit_exceeded else '[bold green]OK[/bold green]'
      table.add_row(name, model, str(tokens), status)

    self.console.print(table)
    if len(results) > 1:
      self.console.print(f'[bold]Total Estimated Tokens:[/bold] [cyan]{total_tokens}[/cyan]')

    if any(limit_exceeded for _, limit_exceeded, _ in results):
      self.console.print(
        '\n[bold red]Warning:[/bold red] One or more prompts exceed the model context limit!'
      )

    if auto_confirmed:
      self.console.print('\n[yellow]Auto-confirming token usage (--yes-tokens).[/yellow]')

  def report_llm_response(self, response: str, task_name: str) -> None:
    # Determine syntax highlighting based on content (defaulting to xml).
    syntax_lexer = 'xml'
    if 'gen:' in task_name.lower():
      syntax_lexer = 'html'

    syntax = Syntax(response, syntax_lexer, theme='monokai', line_numbers=True, word_wrap=True)
    self.console.print(
      Panel(
        syntax,
        title=f'[bold]LLM Response: {task_name}[/bold]',
        border_style='cyan',
        expand=False,
      )
    )

  def report_coverage_audit(self, audit_response: str) -> None:
    self.console.print()
    self.console.rule('[bold cyan]Coverage Audit Report')
    self.console.print()
    self.console.print(Markdown(audit_response))
    self.console.print()

  def report_audit_worksheet(self, worksheet_text: str) -> None:
    table = Table(title='Coverage Audit Worksheet', show_header=True, header_style='bold cyan')
    table.add_column('ID', style='dim')
    table.add_column('Requirement')
    table.add_column('Status', justify='center')

    # Regex to parse lines like: R1: [Requirement Text] -> [COVERED by filename.html]
    # or R1: [Requirement Text] -> [UNCOVERED]
    pattern = re.compile(r'^(R\d+):\s*(.*)\s*->\s*\[(.*)\]', re.MULTILINE)

    matches = list(pattern.finditer(worksheet_text))
    # Sort by numerical value of the ID (e.g., R1, R2, R10)
    matches.sort(key=lambda m: int(m.group(1)[1:]))

    for match in matches:
      req_id, req_text, status_info = match.groups()

      if 'UNCOVERED' in status_info.upper():
        status_display = f'[bold red]✘ {status_info}[/bold red]'
      else:
        status_display = f'[green]✔ {status_info}[/green]'

      table.add_row(req_id, req_text.strip(), status_display)

    self.console.print(table)
    self.console.print()

  def report_test_suggestion(
    self, suggestion_index: int, title: str, description: str, test_type: str
  ) -> None:
    self.console.print(
      Panel(
        f'[bold cyan]Description:[/bold cyan] {description}\n'
        f'[bold cyan]Test Type:[/bold cyan] {test_type}',
        title=f'[bold cyan] Test Suggestion #{suggestion_index}:[/bold cyan] [white]{title}[/white]',
        border_style='blue',
        expand=False,
      )
    )

  def report_generation_start(self, count: int) -> None:
    self.console.print(f'\nGenerating [bold]{count}[/bold] tests in parallel...')

  def report_test_generated(
    self, root_name: str, success: bool, path: Path | None = None, fallback: bool = False
  ) -> None:
    if success:
      if fallback:
        self.console.print(f'[green]✔ Saved (fallback):[/green] {path.absolute() if path else ""}')
      else:
        self.console.print(f'[green]✔ Saved:[/green] {path.absolute() if path else ""}')
    else:
      self.error(f'Failed to generate: {root_name}')

  def report_generation_summary(self, generated_tests: list[tuple[Path, str, str]]) -> None:
    if generated_tests:
      summary_table = Table(
        title='Generated Tests Summary', show_header=True, header_style='bold green'
      )
      summary_table.add_column('File Name', style='cyan')
      summary_table.add_column('Full Path', style='dim')

      for p, _content, _s_xml in generated_tests:
        summary_table.add_row(p.name, str(p.absolute()))

      self.console.print()
      self.console.print(summary_table)
      self.success(f'{len(generated_tests)} tests generated successfully.')
    else:
      self.error('No tests were successfully generated.')

  def report_evaluation_start(self, count: int) -> None:
    self.console.print(f'Evaluating [bold]{count}[/bold] test suggestions...')

  def report_evaluation_result(
    self, display_names: str, success: bool, updated: bool = False, message: str | None = None
  ) -> None:
    if success:
      if updated:
        self.console.print(f'[cyan]ℹ {display_names} was corrected and updated.[/cyan]')
      else:
        self.console.print(f'[green]✔ {display_names} passed evaluation.[/green]')
    else:
      if message:
        self.warning(f'{message}')
      else:
        self.warning(f'Evaluation of {display_names} failed or was skipped.')
