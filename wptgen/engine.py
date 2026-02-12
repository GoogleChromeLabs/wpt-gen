import asyncio
import re
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from rich.console import Console
from rich.prompt import Prompt
from rich.panel import Panel
from typing import Any

from wptgen.config import Config
from wptgen.llm import get_llm_client
from wptgen.context import (
  extract_feature_metadata,
  fetch_feature_yaml,
  fetch_and_extract_text,
  find_feature_tests
)

console = Console()

class WPTGenEngine:
  def __init__(self, config: Config):
    self.config = config
    self.llm = get_llm_client(config)

    template_dir = Path(__file__).parent / 'templates'
    self.jinja_env = Environment(loader=FileSystemLoader(template_dir))

  def run_workflow(self, web_feature_id: str):
    """Entry point for the synchronous CLI to launch the async workflow."""
    asyncio.run(self._run_async_workflow(web_feature_id))

  async def _run_async_workflow(self, web_feature_id: str):
    """Orchestrates the end-to-end WPT generation workflow."""
    # Phase 1: Context Assembly
    context = await self._phase_context_assembly(web_feature_id)
    if not context: return

    # Phase 2: Requirements Analysis
    analysis = await self._phase_requirements_analysis(web_feature_id, context)
    if not analysis: return

    # Phase 3: Test Suggestions
    suggestions = await self._phase_test_suggestions(web_feature_id, analysis)
    if not suggestions: return

    # Phase 4: User Selection & Generation
    await self._phase_test_generation(context, suggestions)

  async def _phase_context_assembly(self, web_feature_id: str) -> dict[str, Any] | None:
    console.print(f'\n[bold cyan]--- Phase 1: Context Assembly ---[/bold cyan]')

    feature_data = fetch_feature_yaml(web_feature_id)
    if not feature_data:
      console.print(f'[bold red]Error:[/bold red] Feature {web_feature_id} not found.')
      return None

    metadata = extract_feature_metadata(feature_data)
    if not metadata.specs:
      console.print('[bold red]Error:[/bold red] No specification URL found.')
      return None

    console.print(f'Web Feature Name: {metadata.name}\nDescription: {metadata.description}')

    console.print(f'Fetching spec content from: {metadata.specs[0]}')
    with console.status(f"[blue]Fetching spec content...[/blue]"):
      spec_content = fetch_and_extract_text(metadata.specs[0])

    if not spec_content:
      console.print('[bold red]Error:[/bold red] Failed to extract spec content.')
      return None

    console.print('Scanning local WPT repository for existing tests...')
    test_paths = find_feature_tests(self.config.wpt_path, web_feature_id)

    test_files = []
    for path in test_paths:
      try:
        content = Path(path).read_text(encoding='utf-8')
        test_files.append({'path': path, 'content': content})
      except Exception as e:
        console.print(f'[yellow]Warning:[/yellow] Skipped {path}: {e}')

    console.print(f'✔ Context gathered: {len(spec_content)} chars of spec, {len(test_files)} existing tests.')

    return {
      'metadata': metadata,
      'spec_content': spec_content,
      'test_files': test_files
    }

  async def _phase_requirements_analysis(
    self,
    web_feature_id: str,
    context: dict[str, Any]
  ) -> tuple[str, str] | None:
    console.print(f'\n[bold cyan]--- Phase 2: Requirements Analysis ---[/bold cyan]')

    spec_prompt = self.jinja_env.get_template('spec_synthesis.jinja').render(
      feature_name=context['metadata'].name,
      feature_description=context['metadata'].description,
      spec_url=context['metadata'].specs[0],
      spec_content=context['spec_content']
    )

    test_prompt = self.jinja_env.get_template('test_analysis.jinja').render(
      feature_id=web_feature_id,
      existing_tests=context['test_files']
    )

    console.print('Submitting [bold]Spec Synthesis[/bold] and [bold]Test Analysis[/bold] tasks concurrently...')

    with console.status("[blue]Analyzing test suite and test requirements... [/blue]"):
      results = await asyncio.gather(
        self._generate_safe(spec_prompt, "Spec Synthesis"),
        self._generate_safe(test_prompt, "Test Analysis")
      )

    spec_analysis, test_analysis = results

    if not spec_analysis or not test_analysis:
      console.print('[bold red]Critical Error:[/bold red] One or more analysis steps failed.')
      return None

    console.print('\n[bold green]✔ Requirements Analysis Complete.[/bold green]')
    return (spec_analysis, test_analysis)

  async def _phase_test_suggestions(self, web_feature_id: str, analysis: tuple[str, str]) -> str | None:
    console.print(f'\n[bold cyan]--- Phase 3: Test Suggestions ---[/bold cyan]')

    spec_analysis, test_analysis = analysis

    suggestions_prompt = self.jinja_env.get_template('test_suggestions.jinja').render(
      feature_id=web_feature_id,
      feature_spec_summary=spec_analysis,
      test_summaries=[test_analysis]
    )

    with console.status("[blue]Brainstorming test scenarios...[/blue]"):
      response = await self._generate_safe(suggestions_prompt, "Test Suggestions")

    if not response:
      console.print('[bold red]Critical Error:[/bold red] Failed to generate test suggestions.')
      return None

    return response

  async def _phase_test_generation(
    self,
    context: dict[str, Any],
    suggestions_response: str
  ):
    console.print(f'\n[bold cyan]--- Phase 4: User Selection & Generation ---[/bold cyan]')
    suggestions = self._parse_suggestions(suggestions_response)

    if not suggestions:
      console.print('[yellow]No valid <test_suggestion> blocks found in the LLM response.[/yellow]')
      return

    console.print(f'{len(suggestions)} new test suggestions found!')
    approved_suggestions = []

    for idx, xml_block in enumerate(suggestions):
      title = self._extract_xml_tag(xml_block, 'title') or f"Suggestion #{idx+1}"
      desc = self._extract_xml_tag(xml_block, 'description') or "No description available"

      console.print(Panel(f"[bold]{title}[/bold]\nDescription: {desc}", border_style="blue"))
      if Prompt.ask("Generate this test?", choices=["y", "n"], default="y") == "y":
        approved_suggestions.append(xml_block)

    if not approved_suggestions:
      console.print('[yellow]No tests selected. Exiting.[/yellow]')
      return

    console.print(f'\nGenerating [bold]{len(approved_suggestions)}[/bold] tests in parallel...')

    tasks = []
    gen_template = self.jinja_env.get_template('test_generation.jinja')

    for suggestion_xml in approved_suggestions:
      final_prompt = gen_template.render(
        feature_name=context['metadata'].name,
        feature_description=context['metadata'].description,
        test_suggestion_xml_block=suggestion_xml,
      )

      raw_title = self._extract_xml_tag(suggestion_xml, 'title') or 'file'
      safe_filename = ('test_generated__' +
                       re.sub(r'[^a-z0-9_\-]', '_', raw_title.lower()) +
                       '.html'
      )

      tasks.append(self._generate_and_save(final_prompt, safe_filename))

    with console.status(f"[blue]Generating {len(tasks)} tests...[/blue]"):
      await asyncio.gather(*tasks)

    console.print(f'\n[bold green]✔ All selected tests generated successfully.[/bold green]')

  def _parse_suggestions(self, raw_text: str) -> list[str]:
    return re.findall(r'<test_suggestion>.*?</test_suggestion>', raw_text, re.DOTALL)

  def _extract_xml_tag(self, text: str, tag: str) -> str | None:
    match = re.search(f'<{tag}>(.*?)</{tag}>', text, re.DOTALL)
    return match.group(1).strip() if match else None

  async def _generate_safe(self, prompt: str, task_name: str) -> str:
    """Helper to run LLM generation in a thread and handle errors gracefully."""
    try:
      loop = asyncio.get_running_loop()
      response = await loop.run_in_executor(None, self.llm.generate_content, prompt)
      console.print(f'✔ {task_name} finished.')
      return response
    except Exception as e:
      console.print(f'[bold red]✘ {task_name} failed:[/bold red] {e}')
      return ""

  async def _generate_and_save(self, prompt: str, filename: str):
    """Helper to generate a specific test and save it to disk."""
    console.print(f'Starting generation for: {filename}...')
    content = await self._generate_safe(prompt, f"Gen: {filename}")

    if content:
      # Strip Markdown code blocks if the LLM added them (common behavior)
      clean_content = re.sub(
        r'^```html\s*|^```\s*|\s*```$', '',
        content,
        flags=re.MULTILINE,
      ).strip()
      Path(filename).write_text(clean_content, encoding='utf-8')
      console.print(f'[green]Saved:[/green] {Path(filename).absolute()}')
