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

import asyncio

import typer
from rich.table import Table

from wptgen.config import Config
from wptgen.llm import LLMClient
from wptgen.ui import UIProvider


async def confirm_prompts(
  prompt_data: list[tuple[str, str]],
  phase_name: str,
  llm: LLMClient,
  ui: UIProvider,
  config: Config,
) -> None:
  """Calculates tokens for a list of prompts and asks for a single user confirmation."""
  loop = asyncio.get_running_loop()

  total_tokens = 0
  any_limit_exceeded = False

  with ui.status(f'[yellow]Calculating token usage for {phase_name}...[/yellow]'):
    # We do token counting concurrently for speed
    async def get_info(prompt: str, name: str) -> tuple[int, bool, str]:
      tokens = await loop.run_in_executor(None, llm.count_tokens, prompt)
      limit_exceeded = await loop.run_in_executor(
        None, llm.prompt_exceeds_input_token_limit, prompt
      )
      return tokens, limit_exceeded, name

    results = await asyncio.gather(*(get_info(p, n) for p, n in prompt_data))

  table = Table(
    title=f'Token Usage Summary ({phase_name})', show_header=True, header_style='bold magenta'
  )
  table.add_column('Task', style='dim')
  table.add_column('Tokens', justify='right', style='cyan')
  table.add_column('Status', justify='center')

  for tokens, limit_exceeded, name in results:
    total_tokens += tokens
    status = '[bold red]EXCEEDED[/bold red]' if limit_exceeded else '[bold green]OK[/bold green]'
    table.add_row(name, str(tokens), status)
    if limit_exceeded:
      any_limit_exceeded = True

  ui.display_table(table)
  if len(prompt_data) > 1:
    ui.print(f'[bold]Total Estimated Tokens:[/bold] [cyan]{total_tokens}[/cyan]')

  if any_limit_exceeded:
    ui.print('\n[bold red]Warning:[/bold red] One or more prompts exceed the model context limit!')

  if config.yes_tokens:
    ui.print('\n[yellow]Auto-confirming token usage (--yes-tokens).[/yellow]')
    return

  if not ui.confirm('\nProceed with these LLM requests?'):
    ui.print('[yellow]Aborting workflow due to user cancellation.[/yellow]')
    raise typer.Abort()


async def generate_safe(
  prompt: str,
  task_name: str,
  llm: LLMClient,
  ui: UIProvider,
  config: Config,
  system_instruction: str | None = None,
  temperature: float | None = None,
) -> str:
  """Helper to run LLM generation in a thread and handle errors gracefully."""
  try:
    loop = asyncio.get_running_loop()
    with ui.status(f'[blue]Executing {task_name}...[/blue]'):
      response = await loop.run_in_executor(
        None, llm.generate_content, prompt, system_instruction, temperature
      )

    ui.print(f'✔ {task_name} finished.')
    if config.show_responses:
      # Determine syntax highlighting based on content (defaulting to xml).
      syntax_lexer = 'xml'
      if 'gen:' in task_name.lower():
        syntax_lexer = 'html'

      ui.display_syntax(response, syntax_lexer, task_name)
    return response
  except Exception as e:
    ui.print(f'[bold red]✘ {task_name} failed:[/bold red] {e}')
    return ''
