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
import yaml
from rich.align import Align
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.text import Text

from wptgen.config import (
  DEFAULT_CONFIG_PATH,
  DEFAULT_LLM_TIMEOUT,
  DEFAULT_PROVIDER_MODELS,
  _get_global_config_path,
  load_config,
)
from wptgen.engine import WorkflowError, WPTGenEngine
from wptgen.llm import LLMTimeoutError
from wptgen.models import WorkflowPhase
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
      '--provider',
      '-p',
      help="Override the default LLM provider (e.g., 'gemini', 'openai', 'anthropic').",
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
  wf_yml_update: Annotated[
    bool,
    typer.Option(
      '--wf-yml-update',
      help='Update WEB_FEATURES.yml with generated tests.',
    ),
  ] = False,
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
  yes_tests: Annotated[
    bool,
    typer.Option(
      '--yes-tests',
      help='Automatically confirm and generate all proposed test suggestions without prompting.',
    ),
  ] = False,
  yes_cache: Annotated[
    bool,
    typer.Option(
      '--yes-cache',
      help='Automatically use the cache if it exists without prompting.',
    ),
  ] = False,
  no_cache: Annotated[
    bool,
    typer.Option(
      '--no-cache',
      help='Automatically ignore and overwrite the cache if it exists without prompting.',
    ),
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
  resume_from: Annotated[
    WorkflowPhase | None,
    typer.Option(
      '--resume-from',
      help='Resume the workflow explicitly from a specific phase.',
    ),
  ] = None,
  state_dir: Annotated[
    Path | None,
    typer.Option(
      '--state-dir',
      '--tests-dir',
      help='Directory containing the necessary artifacts to hydrate the requested phase.',
      dir_okay=True,
      exists=True,
    ),
  ] = None,
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
  draft: Annotated[
    bool,
    typer.Option(
      '--draft',
      help='Enable fetching metadata from the draft features directory.',
    ),
  ] = False,
  single_prompt_requirements: Annotated[
    bool,
    typer.Option(
      '--single-prompt-requirements',
      help='Use a single-prompt requirements extraction process (legacy).',
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
  skip_evaluation: Annotated[
    bool,
    typer.Option(
      '--skip-evaluation',
      '--no-eval',
      help='Skip the evaluation phase after generating tests.',
    ),
  ] = False,
  skip_execution: Annotated[
    bool,
    typer.Option(
      '--skip-execution',
      '--no-exec',
      help='Skip the test execution phase after generating tests.',
    ),
  ] = False,
  tentative: Annotated[
    bool,
    typer.Option(
      '--tentative',
      help='Generate test files with the .tentative flag.',
    ),
  ] = False,
  save_traces: Annotated[
    bool,
    typer.Option(
      '--save-traces',
      help='Save LLM interaction traces to the .wptgen/traces/ directory.',
    ),
  ] = False,
  max_parallel_requests: Annotated[
    int | None,
    typer.Option(
      '--max-parallel-requests',
      help='Maximum number of parallel asynchronous LLM requests.',
    ),
  ] = None,
  temperature: Annotated[
    float | None,
    typer.Option(
      '--temperature',
      help='Global temperature setting for all LLM requests (e.g., 0.01). Overrides phase-specific defaults.',
    ),
  ] = None,
  wpt_binary: Annotated[
    str | None,
    typer.Option(
      '--binary',
      help='Path to a custom browser binary executable for the execution phase.',
    ),
  ] = None,
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

  if wf_yml_update and not output_dir:
    ui.error('--output-dir is required when using --wf-yml-update.')
    raise typer.Exit(code=1)

  if use_lightweight and use_reasoning:
    ui.error('Cannot use both --use-lightweight and --use-reasoning.')
    raise typer.Exit(code=1)

  if yes_cache and no_cache:
    ui.error('Cannot use both --yes-cache and --no-cache.')
    raise typer.Exit(code=1)

  if detailed_requirements and single_prompt_requirements:
    ui.error('Cannot use both --detailed-requirements and --single-prompt-requirements.')
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
      yes_tests_override=yes_tests,
      yes_cache_override=yes_cache,
      no_cache_override=no_cache,
      suggestions_only=suggestions_only,
      resume_override=resume,
      resume_from_override=resume_from,
      state_dir_override=str(state_dir) if state_dir else None,
      max_retries_override=max_retries,
      timeout_override=timeout,
      spec_urls_override=spec_urls_list,
      feature_description_override=description,
      detailed_requirements_override=detailed_requirements,
      draft_override=draft,
      single_prompt_requirements_override=single_prompt_requirements,
      use_lightweight_override=use_lightweight,
      use_reasoning_override=use_reasoning,
      skip_evaluation_override=skip_evaluation,
      skip_execution_override=skip_execution,
      tentative_override=tentative,
      save_traces_override=save_traces,
      max_parallel_requests_override=max_parallel_requests,
      temperature_override=temperature,
      wpt_binary_override=wpt_binary,
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
    context = engine.run_workflow(web_feature_id)

    if wf_yml_update and output_dir and context and context.generated_tests:
      from wptgen.metadata import update_web_features_yml

      generated_paths = [path for path, _, _ in context.generated_tests]
      update_web_features_yml(output_dir, web_feature_id, generated_paths)
      console.print(f'[bold green]✔ Updated WEB_FEATURES.yml for {web_feature_id}[/bold green]')

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


@app.command(name='doctor')
def doctor_command(
  config_path: Annotated[
    str, typer.Option('--config', '-c', help='Path to a custom wpt-gen.yml file.')
  ] = DEFAULT_CONFIG_PATH,
) -> None:
  """
  Verify that all system prerequisites are met.
  """
  import os

  success = True
  console.print('[bold]WPT-Gen System Check[/bold]\n')

  try:
    config = load_config(config_path=config_path, require_api_key=False)
    console.print('[bold green]✔[/bold green] Configuration loaded successfully.')
  except Exception as e:
    console.print(f'[bold red]✘[/bold red] Configuration error: {str(e)}')
    raise typer.Exit(code=1) from e

  if config.api_key:
    console.print(f'[bold green]✔[/bold green] API key for {config.provider} is configured.')
  else:
    console.print(f'[bold red]✘[/bold red] API key for {config.provider} is missing.')
    success = False

  wpt_path = Path(config.wpt_path)
  if wpt_path.is_dir():
    console.print(f'[bold green]✔[/bold green] WPT directory found: {wpt_path}')
    if (wpt_path / '.git').exists():
      console.print('[bold green]✔[/bold green] WPT directory is a valid git repository.')
    else:
      console.print('[bold red]✘[/bold red] WPT directory is not a git repository.')
      success = False

    wpt_exec = wpt_path / 'wpt'
    if wpt_exec.exists() and os.access(wpt_exec, os.X_OK):
      console.print('[bold green]✔[/bold green] WPT executable (./wpt) is runnable.')
    else:
      console.print('[bold red]✘[/bold red] WPT executable (./wpt) is missing or not executable.')
      success = False
  else:
    console.print(f'[bold red]✘[/bold red] WPT directory not found: {wpt_path}')
    success = False

  console.print()
  if success:
    console.print(
      Panel('[bold green]All checks passed! System is ready.[/bold green]', expand=False)
    )
  else:
    console.print(
      Panel(
        '[bold red]Some checks failed. Please resolve the issues above.[/bold red]', expand=False
      )
    )
    raise typer.Exit(code=1)


config_app = typer.Typer(
  help='Manage WPT-Gen configuration.',
  add_completion=False,
)
app.add_typer(config_app, name='config')


def _display_config(config_path: str) -> None:
  try:
    import dataclasses

    import yaml

    config = load_config(config_path=config_path, require_api_key=False)
    config_dict = dataclasses.asdict(config)

    if config.loaded_from:
      console.print(f'Reading configuration from: [cyan]{config.loaded_from}[/cyan]')
    else:
      console.print('Reading configuration from: [yellow]Defaults (no config file found)[/yellow]')

    # Remove internal or sensitive fields from display
    config_dict.pop('loaded_from', None)
    config_dict.pop('api_key', None)

    yaml_str = yaml.dump(config_dict, sort_keys=False, default_flow_style=False)
    console.print(
      Panel(yaml_str, title='Resolved Configuration', border_style='blue', expand=False)
    )
  except Exception as e:
    console.print(f'[bold red]Error:[/bold red] {str(e)}')
    raise typer.Exit(code=1) from e


@config_app.callback(invoke_without_command=True)
def config_callback(
  ctx: typer.Context,
  config_path: Annotated[
    str, typer.Option('--config', '-c', help='Path to a custom wpt-gen.yml file.')
  ] = DEFAULT_CONFIG_PATH,
) -> None:
  """
  Manage WPT-Gen configuration. Displays active configuration if no subcommand is provided.
  """
  if ctx.invoked_subcommand is None:
    _display_config(config_path)


@config_app.command(name='show')
def config_show(
  config_path: Annotated[
    str, typer.Option('--config', '-c', help='Path to a custom wpt-gen.yml file.')
  ] = DEFAULT_CONFIG_PATH,
) -> None:
  """
  Display the currently active, fully resolved configuration.
  """
  _display_config(config_path)


@config_app.command(name='set')
def config_set(
  key: Annotated[
    str, typer.Argument(help='Configuration key using dot-notation (e.g., default_provider).')
  ],
  value: Annotated[str, typer.Argument(help='Value to set for the configuration key.')],
  config_path: Annotated[
    str, typer.Option('--config', '-c', help='Path to a custom wpt-gen.yml file.')
  ] = DEFAULT_CONFIG_PATH,
) -> None:
  """
  Update an individual configuration setting using dot-notation.
  """
  from pathlib import Path
  from typing import Any

  import yaml

  path = Path(config_path)
  target_file = path

  if not path.exists() and config_path == DEFAULT_CONFIG_PATH:
    global_path = Path(_get_global_config_path())
    if global_path.exists():
      target_file = global_path

  yaml_data: dict[str, Any] = {}
  if target_file.exists():
    try:
      with open(target_file, encoding='utf-8') as f:
        yaml_data = yaml.safe_load(f) or {}
    except Exception as e:
      console.print(f'[bold red]Error reading config file:[/bold red] {e}')
      raise typer.Exit(code=1) from e

  keys = key.split('.')
  current = yaml_data
  for k in keys[:-1]:
    if k not in current or not isinstance(current[k], dict):
      current[k] = {}
    current = current[k]

  typed_value: Any
  val_lower = value.lower()
  if val_lower == 'true':
    typed_value = True
  elif val_lower == 'false':
    typed_value = False
  elif value.isdigit():
    typed_value = int(value)
  else:
    try:
      typed_value = float(value)
    except ValueError:
      typed_value = value

  current[keys[-1]] = typed_value

  try:
    with open(target_file, 'w', encoding='utf-8') as f:
      yaml.dump(yaml_data, f, sort_keys=False, default_flow_style=False)
    console.print(
      f'[bold green]✔[/bold green] Set [cyan]{key}[/cyan] = [yellow]{typed_value}[/yellow] in [magenta]{target_file.resolve()}[/magenta]'
    )
  except Exception as e:
    console.print(f'[bold red]Error writing config file:[/bold red] {e}')
    raise typer.Exit(code=1) from e


@app.command(name='list-models')
def list_models(
  provider: Annotated[
    str | None,
    typer.Option(
      '--provider',
      '-p',
      help="Override the default LLM provider (e.g., 'gemini', 'openai', 'anthropic').",
    ),
  ] = None,
  config_path: Annotated[
    str, typer.Option('--config', '-c', help='Path to a custom wpt-gen.yml file.')
  ] = DEFAULT_CONFIG_PATH,
) -> None:
  """
  Display the configured LLM models for the active provider.
  """
  try:
    from rich.table import Table

    config = load_config(config_path=config_path, provider_override=provider, require_api_key=False)

    table = Table(title=f'Configured Models for {config.provider.capitalize()}')
    table.add_column('Category', justify='left', style='cyan', no_wrap=True)
    table.add_column('Model Name', justify='left', style='magenta')

    table.add_row('default', config.default_model)
    for cat_name, mod_name in config.categories.items():
      table.add_row(cat_name, mod_name)

    console.print()
    console.print(table)
  except Exception as e:
    console.print(f'[bold red]Error:[/bold red] {str(e)}')
    raise typer.Exit(code=1) from e


@app.command(name='audit')
def audit(
  web_feature_id: Annotated[
    str,
    typer.Argument(help="The web feature ID to generate tests for (e.g., 'grid', 'popover')."),
  ],
  provider: Annotated[
    str | None,
    typer.Option(
      '--provider',
      '-p',
      help="Override the default LLM provider (e.g., 'gemini', 'openai', 'anthropic').",
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
  wf_yml_update: Annotated[
    bool,
    typer.Option(
      '--wf-yml-update',
      help='Update WEB_FEATURES.yml with generated tests.',
    ),
  ] = False,
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
  yes_cache: Annotated[
    bool,
    typer.Option(
      '--yes-cache',
      help='Automatically use the cache if it exists without prompting.',
    ),
  ] = False,
  no_cache: Annotated[
    bool,
    typer.Option(
      '--no-cache',
      help='Automatically ignore and overwrite the cache if it exists without prompting.',
    ),
  ] = False,
  resume: Annotated[
    bool,
    typer.Option(
      '--resume',
      help='Resume the workflow from the last successful phase.',
    ),
  ] = False,
  resume_from: Annotated[
    WorkflowPhase | None,
    typer.Option(
      '--resume-from',
      help='Resume the workflow explicitly from a specific phase.',
    ),
  ] = None,
  state_dir: Annotated[
    Path | None,
    typer.Option(
      '--state-dir',
      '--tests-dir',
      help='Directory containing the necessary artifacts to hydrate the requested phase.',
      dir_okay=True,
      exists=True,
    ),
  ] = None,
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
  draft: Annotated[
    bool,
    typer.Option(
      '--draft',
      help='Enable fetching metadata from the draft features directory.',
    ),
  ] = False,
  single_prompt_requirements: Annotated[
    bool,
    typer.Option(
      '--single-prompt-requirements',
      help='Use a single-prompt requirements extraction process (legacy).',
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
  save_traces: Annotated[
    bool,
    typer.Option(
      '--save-traces',
      help='Save LLM interaction traces to the .wptgen/traces/ directory.',
    ),
  ] = False,
  max_parallel_requests: Annotated[
    int | None,
    typer.Option(
      '--max-parallel-requests',
      help='Maximum number of parallel asynchronous LLM requests.',
    ),
  ] = None,
  temperature: Annotated[
    float | None,
    typer.Option(
      '--temperature',
      help='Global temperature setting for all LLM requests (e.g., 0.01). Overrides phase-specific defaults.',
    ),
  ] = None,
) -> None:
  """
  Perform a gap analysis and generate coverage blueprints without generating WPT files.
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

  if wf_yml_update and not output_dir:
    ui.error('--output-dir is required when using --wf-yml-update.')
    raise typer.Exit(code=1)

  if use_lightweight and use_reasoning:
    ui.error('Cannot use both --use-lightweight and --use-reasoning.')
    raise typer.Exit(code=1)

  if yes_cache and no_cache:
    ui.error('Cannot use both --yes-cache and --no-cache.')
    raise typer.Exit(code=1)

  if detailed_requirements and single_prompt_requirements:
    ui.error('Cannot use both --detailed-requirements and --single-prompt-requirements.')
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
      yes_tests_override=False,
      yes_cache_override=yes_cache,
      no_cache_override=no_cache,
      suggestions_only=True,
      resume_override=resume,
      resume_from_override=resume_from,
      state_dir_override=str(state_dir) if state_dir else None,
      max_retries_override=max_retries,
      timeout_override=timeout,
      spec_urls_override=spec_urls_list,
      feature_description_override=description,
      detailed_requirements_override=detailed_requirements,
      draft_override=draft,
      single_prompt_requirements_override=single_prompt_requirements,
      use_lightweight_override=use_lightweight,
      use_reasoning_override=use_reasoning,
      skip_evaluation_override=True,
      skip_execution_override=True,
      tentative_override=False,
      save_traces_override=save_traces,
      max_parallel_requests_override=max_parallel_requests,
      temperature_override=temperature,
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
        '[bold green]✔ Audit completed successfully! Blueprints generated.[/bold green]',
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


@app.command(name='init')
def init(
  config_path: Annotated[
    str | None, typer.Option('--config', '-c', help='Path to a custom wpt-gen.yml file.')
  ] = None,
  wpt_path: Annotated[
    str | None,
    typer.Option('--wpt-path', help='Absolute path to local web-platform-tests directory.'),
  ] = None,
) -> None:
  """
  Initialize a new wpt-gen configuration file interactively.
  """
  if config_path:
    resolved_path = Path(config_path)
  else:
    resolved_path = Path(_get_global_config_path())

  # Ensure the directory exists
  resolved_path.parent.mkdir(parents=True, exist_ok=True)

  if resolved_path.exists():
    overwrite = Confirm.ask(
      f'[bold yellow]Warning:[/bold yellow] Configuration file already exists at [cyan]{resolved_path}[/cyan]. Overwrite?',
      default=False,
    )
    if not overwrite:
      console.print('Aborted.')
      return

  provider = Prompt.ask(
    'Preferred LLM Provider', choices=['gemini', 'openai', 'anthropic'], default='gemini'
  )

  defaults = DEFAULT_PROVIDER_MODELS[provider]

  console.print(f'\n[cyan]Configuring models for {provider}[/cyan]')
  default_model = Prompt.ask('Default model', default=defaults['default'])
  lightweight_model = Prompt.ask('Lightweight model', default=defaults['lightweight'])
  reasoning_model = Prompt.ask('Reasoning model', default=defaults['reasoning'])

  if wpt_path is None:
    wpt_path = Prompt.ask(
      '\nAbsolute path to local web-platform-tests directory', default=str(Path.home() / 'wpt')
    )

  config_data = {
    'default_provider': provider,
    'wpt_path': str(Path(wpt_path).expanduser().resolve()),
    'providers': {
      provider: {
        'default_model': default_model,
        'categories': {
          'lightweight': lightweight_model,
          'reasoning': reasoning_model,
        },
      }
    },
  }

  try:
    with open(resolved_path, 'w', encoding='utf-8') as f:
      yaml.dump(config_data, f, default_flow_style=False, sort_keys=False)
    console.print(
      f'\n[bold green]✔ Configuration saved successfully to [cyan]{resolved_path}[/cyan][/bold green]'
    )
  except Exception as e:
    console.print(f'[bold red]Failed to save configuration:[/bold red] {str(e)}')
    raise typer.Exit(code=1) from e


@app.callback()
def main_callback() -> None:
  """
  AI-Powered Web Platform Test Generation CLI
  """
  pass


if __name__ == '__main__':
  app()  # pragma: no cover
