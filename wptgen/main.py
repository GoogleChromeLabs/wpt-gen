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


from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as app_version
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel

from wptgen.config import DEFAULT_CONFIG_PATH, load_config
from wptgen.engine import WPTGenEngine

# Initialize Typer app and Rich console
app = typer.Typer(
  name='wpt-gen',
  help='AI-Powered Web Platform Test Generation CLI',
  add_completion=False,
)
console = Console()


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
  max_retries: Annotated[
    int,
    typer.Option(
      '--max-retries',
      help='Maximum number of retries for LLM calls.',
    ),
  ] = 3,
  spec_urls: Annotated[
    str | None,
    typer.Option(
      '--spec-urls',
      '-u',
      help='Comma-separated list of spec URLs to use, bypassing automatic fetching.',
    ),
  ] = None,
) -> None:
  """
  Generate Web Platform Tests for a specific web feature.
  """
  console.print(f'[bold blue]Starting WPT-Gen for feature:[/bold blue] {web_feature_id}')

  try:
    # 1. Load configuration (merging YAML, env vars, and CLI overrides)

    # Convert Path object back to string if it was provided, else pass None
    wpt_dir_str = str(wpt_dir) if wpt_dir else None

    # Parse comma-separated spec URLs
    spec_urls_list = [url.strip() for url in spec_urls.split(',')] if spec_urls else None

    config = load_config(
      config_path=config_path,
      provider_override=provider,
      wpt_dir_override=wpt_dir_str,
      show_responses=show_responses,
      yes_tokens_override=yes_tokens,
      suggestions_only=suggestions_only,
      max_retries_override=max_retries,
      spec_urls_override=spec_urls_list,
    )

    console.print(
      Panel(
        f'[bold]Provider:[/bold] {config.provider}\n[bold]Model:[/bold] {config.model}',
        title='Active Configuration',
        expand=False,
        border_style='green',
      )
    )

    # 2. Instantiate the core engine
    engine = WPTGenEngine(config=config)

    # 3. Execute the workflow
    # Note: In Phase 1, this will just print the skeleton output
    engine.run_workflow(web_feature_id)

    console.print('[bold green]✔ Workflow completed successfully.[/bold green]')

  except ValueError as e:
    # Catch configuration errors (like missing API keys) and exit gracefully
    console.print(f'[bold red]Configuration Error:[/bold red] {str(e)}')
    raise typer.Exit(code=1) from e
  except Exception as e:
    # Catch unexpected runtime errors
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
  app()
