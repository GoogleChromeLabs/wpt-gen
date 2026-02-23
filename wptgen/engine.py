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
import re
from pathlib import Path
from typing import Any

import typer
from jinja2 import Environment, FileSystemLoader
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

from wptgen.config import Config
from wptgen.context import (
  extract_feature_metadata,
  fetch_and_extract_text,
  fetch_feature_yaml,
  find_feature_tests,
  gather_local_test_context,
)
from wptgen.llm import get_llm_client

# Regular expressions for parsing and sanitization
SUGGESTION_BLOCK_RE = re.compile(r'<test_suggestion>.*?</test_suggestion>', re.DOTALL)
FILENAME_SANITIZATION_RE = re.compile(r'[^a-z0-9_\-]')
MARKDOWN_CODE_BLOCK_RE = re.compile(r'^```html\s*|^```\s*|\s*```$', re.MULTILINE)


class WPTGenEngine:
  def __init__(self, config: Config):
    self.config = config
    self.console = Console()
    self.llm = get_llm_client(config)

    template_dir = Path(__file__).parent.joinpath('templates')
    self.jinja_env = Environment(loader=FileSystemLoader(template_dir))

    assert self.config.cache_path is not None, 'cache_path must be set in configuration'
    self.spec_synthesis_cache_dir = Path(self.config.cache_path) / 'spec_synthesis'
    self.spec_synthesis_cache_dir.mkdir(parents=True, exist_ok=True)

  def run_workflow(self, web_feature_id: str) -> None:
    """Entry point for the synchronous CLI to launch the async workflow."""
    asyncio.run(self._run_async_workflow(web_feature_id))

  async def _run_async_workflow(self, web_feature_id: str) -> None:
    """Orchestrates the end-to-end WPT generation workflow."""
    # Phase 1: Context Assembly
    context = await self._phase_context_assembly(web_feature_id)
    if not context:
      return

    # Try unified prompt first
    unified_prompt = self.jinja_env.get_template('test_suggestions_unified.jinja').render(
      feature_name=context['metadata'].name,
      feature_description=context['metadata'].description,
      spec_url=', '.join(context['metadata'].specs),
      spec_contents=context['spec_contents'],
      wpt_context=context['wpt_context'],
    )

    loop = asyncio.get_running_loop()
    with self.console.status('[yellow]Checking context window for unified prompt...[/yellow]'):
      fits = not await loop.run_in_executor(
        None, self.llm.prompt_exceeds_input_token_limit, unified_prompt
      )

    if fits:
      self.console.print('[green]Using unified prompt flow (fits in context window).[/green]')
      # Phase 2: Consolidated Test Suggestions
      suggestions = await self._phase_unified_suggestions(unified_prompt)
    else:
      self.console.print(
        '[yellow]Context too large for unified prompt. Using multi-step flow.[/yellow]'
      )
      # Phase 2: Requirements Analysis
      analysis = await self._phase_requirements_analysis(web_feature_id, context)
      if not analysis:
        return

      # Phase 3: Test Suggestions
      suggestions = await self._phase_test_suggestions(web_feature_id, analysis)

    if not suggestions:
      return

    # Skip Phase 4 if the user only wants the suggestions.
    if self.config.suggestions_only:
      await self._provide_test_suggestions(context, suggestions)
      return

    # Phase 4: User Selection & Generation
    await self._phase_test_generation(context, suggestions)

  async def _provide_test_suggestions(
    self, context: dict[str, Any], suggestions_response: str
  ) -> None:
    """Prints the test suggestions response and optionally saves it to a file."""
    self.console.print('\n[bold cyan]--- Test Suggestions ---[/bold cyan]')
    self.console.print(suggestions_response)

    if Confirm.ask('\nSave suggestions to a file?'):
      # Create a sanitized filename from the feature ID
      safe_id = FILENAME_SANITIZATION_RE.sub('_', context['feature_id'].lower())
      filename = f'{safe_id}_test_suggestions.md'
      try:
        Path(filename).write_text(suggestions_response, encoding='utf-8')
        self.console.print(f'[green]Saved:[/green] {Path(filename).absolute()}')
      except Exception as e:
        self.console.print(f'[bold red]Error saving file:[/bold red] {e}')

  async def _phase_unified_suggestions(self, prompt: str) -> str | None:
    self.console.print('\n[bold cyan]--- Phase 2: Consolidated Test Suggestions ---[/bold cyan]')
    await self._confirm_prompts([(prompt, 'Consolidated Suggestions')], 'Consolidated Suggestions')
    response = await self._generate_safe(prompt, 'Consolidated Suggestions')

    if not response:
      self.console.print(
        '[bold red]Critical Error:[/bold red] Failed to generate unified suggestions.'
      )
      return None

    return response

  async def _phase_context_assembly(self, web_feature_id: str) -> dict[str, Any] | None:
    self.console.print('\n[bold cyan]--- Phase 1: Context Assembly ---[/bold cyan]')

    feature_data = fetch_feature_yaml(web_feature_id)
    if not feature_data:
      self.console.print(f'[bold red]Error:[/bold red] Feature {web_feature_id} not found.')
      return None

    metadata = extract_feature_metadata(feature_data)
    if self.config.spec_urls:
      metadata.specs = self.config.spec_urls
    if not metadata.specs:
      self.console.print('[bold red]Error:[/bold red] No specification URL found.')
      return None

    self.console.print(f'Web Feature Name: {metadata.name}\nDescription: {metadata.description}')

    self.console.print(f'Fetching spec content from: {metadata.specs[0]}')
    with self.console.status('[blue]Fetching spec content...[/blue]'):
      spec_contents = fetch_and_extract_text(metadata.specs[0])

    if not spec_contents:
      self.console.print('[bold red]Error:[/bold red] Failed to extract spec content.')
      return None

    self.console.print('Scanning local WPT repository for existing tests and dependencies...')
    test_paths = find_feature_tests(self.config.wpt_path, web_feature_id)
    wpt_context = gather_local_test_context(test_paths, self.config.wpt_path)

    self.console.print(
      f'✔ Context gathered: {len(spec_contents)} chars of spec, '
      f'{len(wpt_context.test_contents)} tests, '
      f'{len(wpt_context.dependency_contents)} dependency files.'
    )

    return {
      'feature_id': web_feature_id,
      'metadata': metadata,
      'spec_contents': spec_contents,
      'wpt_context': wpt_context,
    }

  async def _phase_requirements_analysis(
    self, web_feature_id: str, context: dict[str, Any]
  ) -> tuple[str, str] | None:
    self.console.print('\n[bold cyan]--- Phase 2: Requirements Analysis ---[/bold cyan]')

    cache_file = self.spec_synthesis_cache_dir / f'{web_feature_id}.md'
    spec_analysis = None

    if cache_file.exists():
      self.console.print(f'[yellow]Found cached Spec Synthesis for {web_feature_id}.[/yellow]')
      if Confirm.ask('Use cached Spec Synthesis?'):
        spec_analysis = cache_file.read_text(encoding='utf-8')
        self.console.print('✔ Using cached Spec Synthesis.')

    spec_prompt = self.jinja_env.get_template('spec_synthesis.jinja').render(
      feature_name=context['metadata'].name,
      feature_description=context['metadata'].description,
      spec_url=context['metadata'].specs[0],
      spec_contents=context['spec_contents'],
    )

    test_prompt = self.jinja_env.get_template('test_analysis.jinja').render(
      feature_id=web_feature_id, wpt_context=context['wpt_context']
    )

    prompts_to_confirm = []
    if not spec_analysis:
      prompts_to_confirm.append((spec_prompt, 'Spec Synthesis'))
    prompts_to_confirm.append((test_prompt, 'Test Analysis'))

    await self._confirm_prompts(prompts_to_confirm, 'Requirements Analysis')

    if spec_analysis:
      self.console.print('Submitting [bold]Test Analysis[/bold] task...')
      test_analysis = await self._generate_safe(test_prompt, 'Test Analysis')
    else:
      self.console.print(
        'Submitting [bold]Spec Synthesis[/bold] and [bold]Test Analysis[/bold] tasks concurrently...'
      )
      results = await asyncio.gather(
        self._generate_safe(spec_prompt, 'Spec Synthesis'),
        self._generate_safe(test_prompt, 'Test Analysis'),
      )
      spec_analysis, test_analysis = results

    if not spec_analysis or not test_analysis:
      self.console.print('[bold red]Critical Error:[/bold red] One or more analysis steps failed.')
      return None

    # Save to cache if it was newly generated
    if not cache_file.exists() or (spec_analysis and not cache_file.read_text() == spec_analysis):
      cache_file.write_text(spec_analysis, encoding='utf-8')

    self.console.print('\n[bold green]✔ Requirements Analysis Complete.[/bold green]')
    return (spec_analysis, test_analysis)

  async def _phase_test_suggestions(
    self, web_feature_id: str, analysis: tuple[str, str]
  ) -> str | None:
    self.console.print('\n[bold cyan]--- Phase 3: Test Suggestions ---[/bold cyan]')

    spec_analysis, test_analysis = analysis

    suggestions_prompt = self.jinja_env.get_template('test_suggestions.jinja').render(
      feature_id=web_feature_id,
      feature_spec_summary=spec_analysis,
      test_summaries=[test_analysis],
    )

    await self._confirm_prompts([(suggestions_prompt, 'Test Suggestions')], 'Test Suggestions')

    response = await self._generate_safe(suggestions_prompt, 'Test Suggestions')

    if not response:
      self.console.print(
        '[bold red]Critical Error:[/bold red] Failed to generate test suggestions.'
      )
      return None

    return response

  async def _phase_test_generation(
    self, context: dict[str, Any], suggestions_response: str
  ) -> None:
    self.console.print('\n[bold cyan]--- Phase 4: User Selection & Generation ---[/bold cyan]')
    suggestions = self._parse_suggestions(suggestions_response)

    if not suggestions:
      self.console.print(
        '[yellow]No valid <test_suggestion> blocks found in the LLM response.[/yellow]'
      )
      return

    self.console.print(f'{len(suggestions)} new test suggestions found!')
    approved_suggestions_xml: list[str] = []

    for idx, xml_block in enumerate(suggestions):
      title = self._extract_xml_tag(xml_block, 'title') or f'Suggestion #{idx + 1}'
      desc = self._extract_xml_tag(xml_block, 'description') or 'No description available'

      self.console.print(Panel(f'[bold]{title}[/bold]\nDescription: {desc}', border_style='blue'))
      if Prompt.ask('Generate this test?', choices=['y', 'n'], default='y') == 'y':
        approved_suggestions_xml.append(xml_block)

    if not approved_suggestions_xml:
      self.console.print('[yellow]No tests selected. Exiting.[/yellow]')
      return

    # Prepare all generation prompts for batch confirmation
    gen_template = self.jinja_env.get_template('test_generation.jinja')
    prompts_to_confirm: list[tuple[str, str]] = []

    for idx, suggestion_xml in enumerate(approved_suggestions_xml):
      final_prompt = gen_template.render(
        feature_name=context['metadata'].name,
        feature_description=context['metadata'].description,
        test_suggestion_xml_block=suggestion_xml,
      )

      raw_title = self._extract_xml_tag(suggestion_xml, 'title') or 'file'
      # Include index to prevent filename collisions
      slug = FILENAME_SANITIZATION_RE.sub('_', raw_title.lower())
      safe_filename = f'test_generated_{idx + 1:02d}_{slug}.html'

      prompts_to_confirm.append((final_prompt, safe_filename))

    # Single confirmation for ALL tests
    await self._confirm_prompts(prompts_to_confirm, f'Generate {len(prompts_to_confirm)} Tests')

    self.console.print(f'\nGenerating [bold]{len(prompts_to_confirm)}[/bold] tests in parallel...')

    tasks = [self._generate_and_save(prompt, filename) for prompt, filename in prompts_to_confirm]
    await asyncio.gather(*tasks)

    self.console.print('\n[bold green]✔ All selected tests generated successfully.[/bold green]')

  def _parse_suggestions(self, raw_text: str) -> list[str]:
    return SUGGESTION_BLOCK_RE.findall(raw_text)

  def _extract_xml_tag(self, text: str, tag: str) -> str | None:
    # Use dynamic regex with re.search for per-tag extraction
    match = re.search(f'<{tag}>(.*?)</{tag}>', text, re.DOTALL)
    return match.group(1).strip() if match else None

  async def _confirm_prompts(self, prompt_data: list[tuple[str, str]], phase_name: str) -> None:
    """Calculates tokens for a list of prompts and asks for a single user confirmation."""
    loop = asyncio.get_running_loop()

    total_tokens = 0
    any_limit_exceeded = False

    with self.console.status(f'[yellow]Calculating token usage for {phase_name}...[/yellow]'):
      # We do token counting concurrently for speed
      async def get_info(prompt: str, name: str) -> tuple[int, bool, str]:
        tokens = await loop.run_in_executor(None, self.llm.count_tokens, prompt)
        limit_exceeded = await loop.run_in_executor(
          None, self.llm.prompt_exceeds_input_token_limit, prompt
        )
        return tokens, limit_exceeded, name

      results = await asyncio.gather(*(get_info(p, n) for p, n in prompt_data))

    self.console.print(f'[bold underline]Token Usage Summary ({phase_name}):[/bold underline]')
    for tokens, limit_exceeded, name in results:
      total_tokens += tokens
      status_icon = '[bold red]⚠[/bold red]' if limit_exceeded else '[green]✔[/green]'
      self.console.print(f'  {status_icon} [bold]{name}[/bold]: [cyan]{tokens}[/cyan] tokens')
      if limit_exceeded:
        any_limit_exceeded = True

    if len(prompt_data) > 1:
      self.console.print(f'  [bold]Total Estimate:[/bold] [cyan]{total_tokens}[/cyan] tokens')

    if any_limit_exceeded:
      self.console.print(
        '\n[bold red]Warning:[/bold red] One or more prompts exceed the model context limit!'
      )

    if self.config.yes_tokens:
      self.console.print('\n[yellow]Auto-confirming token usage (--yes-tokens).[/yellow]')
      return

    if not Confirm.ask('\nProceed with these LLM requests?'):
      self.console.print('[yellow]Aborting workflow due to user cancellation.[/yellow]')
      raise typer.Abort()

  async def _generate_safe(self, prompt: str, task_name: str) -> str:
    """Helper to run LLM generation in a thread and handle errors gracefully."""
    try:
      loop = asyncio.get_running_loop()
      with self.console.status(f'[blue]Submitting {task_name}...[/blue]'):
        response = await loop.run_in_executor(None, self.llm.generate_content, prompt)

      self.console.print(f'✔ {task_name} finished.')
      if self.config.show_responses:
        self.console.print(Panel(response, title=f'LLM Response: {task_name}', border_style='cyan'))
      return response
    except Exception as e:
      self.console.print(f'[bold red]✘ {task_name} failed:[/bold red] {e}')
      return ''

  async def _generate_and_save(self, prompt: str, filename: str) -> None:
    """Helper to generate a specific test and save it to disk."""
    self.console.print(f'Starting generation for: {filename}...')
    content = await self._generate_safe(prompt, f'Gen: {filename}')

    if content:
      # Strip Markdown code blocks if the LLM added them (common behavior)
      clean_content = MARKDOWN_CODE_BLOCK_RE.sub('', content).strip()
      Path(filename).write_text(clean_content, encoding='utf-8')
      self.console.print(f'[green]Saved:[/green] {Path(filename).absolute()}')
