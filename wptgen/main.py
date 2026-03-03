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


import shutil
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as app_version
from pathlib import Path
from typing import Annotated

import typer
from rich.align import Align
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from wptgen.config import DEFAULT_CONFIG_PATH, DEFAULT_LLM_TIMEOUT, load_config
from wptgen.engine import WorkflowError, WPTGenEngine
from wptgen.llm import LLMTimeoutError
from wptgen.ui import RichUIProvider

# Initialize Typer app and Rich console
app = typer.Typer(
  name='wpt-gen',
  help='AI-Powered Web Platform Test Generation CLI',
  add_completion=False,
)
console = Console()
ui = RichUIProvider(console)


@app.command()
def generate(
  web_feature_id: Annotated[
    str,
    typer.Argument(help="The web feature ID to generate tests for (e.g., 'grid', 'popover')."),
  ],
  provider: Annotated[
    str | None,
    typer.Option(
      '--provider', '-p', help="Override the default LLM provider (e.g., 'gemini', 'openai')."
    ),
  ] = None,
  wpt_dir: Annotated[
    Path | None,
    typer.Option(
      '--wpt-dir',
      '-w',
      help='Path to the local web-platform-tests repository.',
      exists=True,
      dir_okay=True,
      resolve_path=True,
    ),
  ] = None,
  output_dir: Annotated[
    Path | None,
    typer.Option(
      '--output-dir',
      '-o',
      help='Directory where generated tests will be saved.',
      dir_okay=True,
    ),
  ] = None,
  config_path: Annotated[
    str, typer.Option('--config', '-c', help='Path to a custom wpt-gen.yml file.')
  ] = DEFAULT_CONFIG_PATH,
  show_responses: Annotated[
    bool,
    typer.Option(
      '--show-responses', '-s', help='Display every LLM-generated response to the user.'
    ),
  ] = False,
  yes_tokens: Annotated[
    bool,
    typer.Option('--yes-tokens', help='Automatically confirm all token count prompts.'),
  ] = False,
  suggestions_only: Annotated[
    bool,
    typer.Option(
      '--suggestions-only',
      help='Only show test suggestions and skip the test generation step.',
    ),
  ] = False,
  resume: Annotated[
    bool,
    typer.Option(
      '--resume',
      help='Resume the workflow from the last successful phase.',
    ),
  ] = False,
  max_retries: Annotated[
    int,
    typer.Option(
      '--max-retries',
      help='Maximum number of retries for LLM calls.',
    ),
  ] = 3,
  timeout: Annotated[
    int,
    typer.Option(
      '--timeout',
      help='Timeout for LLM requests in seconds.',
    ),
  ] = DEFAULT_LLM_TIMEOUT,
  spec_urls: Annotated[
    str | None,
    typer.Option(
      '--spec-urls',
      '-u',
      help='Comma-separated list of spec URLs to use, bypassing automatic fetching.',
    ),
  ] = None,
  description: Annotated[
    str | None,
    typer.Option(
      '--description',
      '-d',
      help='Manually provide a description for the web feature.',
    ),
  ] = None,
  detailed_requirements: Annotated[
    bool,
    typer.Option(
      '--detailed-requirements',
      help='Use a more detailed, iterative requirements extraction process.',
    ),
  ] = False,
  use_lightweight: Annotated[
    bool,
    typer.Option('--use-lightweight', help='Use the lightweight model for all LLM requests.'),
  ] = False,
  use_reasoning: Annotated[
    bool,
    typer.Option('--use-reasoning', help='Use the reasoning model for all LLM requests.'),
  ] = False,
) -> None:
  """
  Generate Web Platform Tests for a specific web feature.
  """
  banner = Panel(
    Align.center(
      Text.from_markup(
        '[bold blue]WPT[/bold blue][bold white]-[/bold white][bold green]Gen[/bold green]\n'
        '[italic white]AI-Powered Web Platform Test Generation[/italic white]'
      )
    ),
    border_style='bright_blue',
  )
  console.print(banner)
  console.print(f'\n[bold]Target Feature:[/bold] [cyan]{web_feature_id}[/cyan]\n')

  if use_lightweight and use_reasoning:
    ui.error('Cannot use both --use-lightweight and --use-reasoning.')
    raise typer.Exit(code=1)

  try:
    # 1. Load configuration (merging YAML, env vars, and CLI overrides)

    # Convert Path object back to string if it was provided, else pass None
    wpt_dir_str = str(wpt_dir) if wpt_dir else None
    output_dir_str = str(output_dir) if output_dir else None

    # Parse spec_urls if provided
    spec_urls_list = None
    if spec_urls:
      spec_urls_list = [u.strip() for u in spec_urls.split(',')]

    config = load_config(
      config_path=config_path,
      provider_override=provider,
      wpt_dir_override=wpt_dir_str,
      output_dir_override=output_dir_str,
      show_responses=show_responses,
      yes_tokens_override=yes_tokens,
      suggestions_only=suggestions_only,
      resume_override=resume,
      max_retries_override=max_retries,
      timeout_override=timeout,
      spec_urls_override=spec_urls_list,
      feature_description_override=description,
      detailed_requirements_override=detailed_requirements,
      use_lightweight_override=use_lightweight,
      use_reasoning_override=use_reasoning,
    )

    config_info = Text.assemble(
      ('Provider: ', 'bold'),
      (f'{config.provider}\n', 'green'),
      ('Model:    ', 'bold'),
      (f'{config.default_model}', 'green'),
    )
    console.print(
      Panel(
        config_info,
        title='[bold]Configuration[/bold]',
        title_align='left',
        expand=False,
        border_style='bright_black',
      )
    )

    # 2. Instantiate the core engine
    engine = WPTGenEngine(config=config, ui=ui)

    # 3. Execute the workflow
    # Note: In Phase 1, this will just print the skeleton output
    engine.run_workflow(web_feature_id)

    console.print()
    console.print(
      Panel(
        '[bold green]✔ Workflow completed successfully![/bold green]',
        border_style='green',
        expand=False,
      )
    )

  except LLMTimeoutError as e:
    console.print(f'[bold red]LLM Request Timeout:[/bold red] {str(e)}')
    raise typer.Exit(code=1) from e
  except ValueError as e:
    # Catch configuration errors (like missing API keys) and exit gracefully
    console.print(f'[bold red]Configuration Error:[/bold red] {str(e)}')
    raise typer.Exit(code=1) from e
  except WorkflowError:
    console.print()
    console.print(
      Panel(
        '[bold red]✘ Workflow completed with errors.[/bold red]',
        border_style='red',
        expand=False,
      )
    )
    raise typer.Exit(code=1) from None
  except Exception as e:
    # Catch unexpected runtime errors
    console.print(f'[bold red]Unexpected Error:[/bold red] {str(e)}')
    raise typer.Exit(code=1) from e


@app.command(name='clear-cache')
def clear_cache(
  config_path: Annotated[
    str, typer.Option('--config', '-c', help='Path to a custom wpt-gen.yml file.')
  ] = DEFAULT_CONFIG_PATH,
) -> None:
  """
  Clear the existing cached data for wpt-gen.
  """
  try:
    config = load_config(config_path=config_path, require_api_key=False)
    if not config.cache_path:
      console.print('[bold red]Error:[/bold red] Cache path not configured.')
      return

    cache_dir = Path(config.cache_path)

    if not cache_dir.exists():
      console.print(f'Cache directory [cyan]{cache_dir}[/cyan] does not exist. Nothing to clear.')
      return

    files = list(cache_dir.iterdir())
    if not files:
      console.print(f'Cache directory [cyan]{cache_dir}[/cyan] is already empty.')
      return

    if ui.confirm(f'Are you sure you want to clear the cache at [cyan]{cache_dir}[/cyan]?'):
      for item in files:
        if item.is_file():
          item.unlink()
        elif item.is_dir():
          shutil.rmtree(item)
      console.print('[bold green]✔ Cache cleared successfully![/bold green]')
    else:
      console.print('Aborted.')

  except ValueError as e:
    console.print(f'[bold red]Configuration Error:[/bold red] {str(e)}')
    raise typer.Exit(code=1) from e
  except Exception as e:
    console.print(f'[bold red]Unexpected Error:[/bold red] {str(e)}')
    raise typer.Exit(code=1) from e


@app.command()
def version() -> None:
  """
  Print the version of wpt-gen.
  """
  try:
    # Replace 'your-package-name' with the name defined in pyproject.toml
    console.print(f'wpt-gen version {app_version("wpt-gen")}')
  except PackageNotFoundError:
    console.print('unknown')


@app.callback()
def main_callback() -> None:
  """
  AI-Powered Web Platform Test Generation CLI
  """
  pass


if __name__ == '__main__':
  app()  # pragma: no cover
