import typer
from rich.console import Console
from rich.panel import Panel
from typing_extensions import Annotated
from typing import Optional

from wptgen.config import load_config
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
    typer.Argument(help='The web feature ID to generate tests for (e.g., \'grid\', \'popover\').')
  ],
  provider: Annotated[
    Optional[str], 
    typer.Option('--provider', '-p', help='Override the default LLM provider (e.g., \'gemini\', \'openai\').')
  ] = None,
  config_path: Annotated[
    str, 
    typer.Option('--config', '-c', help='Path to a custom wpt-gen.yml file.')
  ] = 'wpt-gen.yml',
):
  """
  Generate Web Platform Tests for a specific web feature.
  """
  console.print(f'[bold blue]Starting WPT-Gen for feature:[/bold blue] {web_feature_id}')

  try:
    # 1. Load configuration (merging YAML, env vars, and CLI overrides)
    config = load_config(config_path=config_path, provider_override=provider)
    
    console.print(
      Panel(
        f'[bold]Provider:[/bold] {config.provider}\n'
        f'[bold]Model:[/bold] {config.model}',
        title='Active Configuration',
        expand=False,
        border_style='green'
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
    raise typer.Exit(code=1)
  except Exception as e:
    # Catch unexpected runtime errors
    console.print(f'[bold red]Unexpected Error:[/bold red] {str(e)}')
    raise typer.Exit(code=1)


@app.callback()
def main_callback():
    """
    AI-Powered Web Platform Test Generation CLI
    """
    pass


if __name__ == '__main__':
  app()